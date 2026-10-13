"""A spawn's ``timeout`` bounds the call even when a grandchild holds its pipe.

On Windows ``subprocess.run`` kills only the child at the timeout and then
reads the pipes with no timeout, so a ``.bat`` shim's program, or the real git
behind Git for Windows's ``cmd\\git.exe`` launcher, set the bound instead
(2026-10-12, CPython 3.11.9: a 2 s cap returned after 20.1 s through a shim, a
1 s cap on ``git ls-remote`` after 21.1 s). ``_json_safe.run_bounded`` kills
the tree and drains under a grace; ``_hook_utils.spawn_checked`` is built on
it, and ``tests/test_spawn_chokepoint.py`` holds every timed spawn under
``tools/cc`` to one of the two.

Unbounded, each case below takes ``HOLD_SECONDS``; bounded, the cap and the
kill grace. On POSIX ``run`` was already bounded, so the cases hold there as
regression cases. Real processes on every OS, so the module is slow.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

TOOLS_CC = Path(__file__).resolve().parents[1] / "tools" / "cc"
CAP_SECONDS = 3.0  # long enough that the holder has surely started inside it
HOLD_SECONDS = 20  # what an unbounded call takes
BOUND_SECONDS = 12.0  # the cap, the kill grace and slack for a loaded box: well under HOLD_SECONDS


def _load_hook_utils():
    spec = importlib.util.spec_from_file_location("hook_utils_for_bound", str(TOOLS_CC / "hooks" / "_hook_utils.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hook_utils_for_bound"] = mod
    spec.loader.exec_module(mod)
    return mod


def _alive(pid: int) -> bool:
    """Whether ``pid`` names a running process (Windows: ``tasklist``; POSIX: signal 0)."""
    if os.name == "nt":
        listed = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        return f'"{pid}"' in listed.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _end_holder(pidfile: Path) -> None:
    """Teardown: end the holder a case started, where it is still alive (on
    POSIX the bound kills only the child, so the grandchild sleeps on)."""
    try:
        pid = int(pidfile.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def _holder(tmp_path: Path) -> tuple[list[str], Path]:
    """A launcher (``.bat`` on Windows, ``sh`` elsewhere) whose child -- the
    spawn's grandchild -- inherits stdout, writes its pid and sleeps."""
    pidfile = tmp_path / "holder.pid"
    body = (f"import os, time; open({str(pidfile)!r}, 'w').write(str(os.getpid())); "
            f"print(1, flush=True); time.sleep({HOLD_SECONDS})")
    if os.name == "nt":
        shim = tmp_path / "holder.bat"
        shim.write_bytes(f'@echo off\r\n"{sys.executable}" -c "{body}"\r\n'.encode("ascii"))
    else:
        shim = tmp_path / "holder.sh"
        shim.write_bytes(f'#!/bin/sh\n"{sys.executable}" -c "{body}"\n'.encode("ascii"))
        shim.chmod(0o755)
    return [str(shim)], pidfile


class TestTheTimeoutIsABound:
    def test_a_grandchild_holding_the_pipe_cannot_outlast_the_chokepoints_timeout(self, tmp_path):
        hu = _load_hook_utils()
        argv, pidfile = _holder(tmp_path)
        start = time.monotonic()
        try:
            with pytest.raises(subprocess.TimeoutExpired) as caught:
                hu.spawn_checked(argv, root=tmp_path, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=CAP_SECONDS)
            elapsed = time.monotonic() - start
            assert pidfile.exists(), "the holder never started inside the cap, so the case did not run"
            holder_alive = _alive(int(pidfile.read_text(encoding="utf-8").strip()))
        finally:
            _end_holder(pidfile)
        assert elapsed < BOUND_SECONDS, (
            f"a {CAP_SECONDS:.0f} s timeout returned after {elapsed:.1f} s: the grandchild holding the "
            "pipe set the bound, not the timeout"
        )
        if os.name == "nt":
            # The bound alone holds without the tree kill (the drain gives up at
            # its grace); these two hold only with it: the holder is ended, so
            # its pipe closed and what it wrote was read.
            assert not holder_alive, "the timeout returned but the grandchild outlived the tree kill"
            assert "1" in (caught.value.stdout or ""), f"the drain read nothing: {caught.value.stdout!r}"

    def test_the_banners_mail_fetch_is_bounded_by_its_cap(self, tmp_path):
        """The hook-level case: ``mail.fetch_mail``, the SessionStart ``Mail:``
        line's network read, through ``record_merge.run``, against an origin
        whose upload-pack sleeps (local, so no network decides the outcome).
        git's own processes hold the pipe here: the launcher on Windows."""
        if shutil.which("git") is None:
            pytest.skip("git is not on PATH")
        remote, clone = tmp_path / "remote.git", tmp_path / "clone"
        for argv in (["git", "init", "-q", "--bare", str(remote)], ["git", "init", "-q", str(clone)],
                     ["git", "-C", str(clone), "remote", "add", "origin", str(remote)],
                     ["git", "-C", str(clone), "config", "remote.origin.uploadpack", f"sleep {HOLD_SECONDS} #"]):
            subprocess.run(argv, check=True, capture_output=True, timeout=30)
        sys.path.insert(0, str(TOOLS_CC))
        try:
            import mail
        finally:
            sys.path.remove(str(TOOLS_CC))
        start = time.monotonic()
        ok, problem = mail.fetch_mail(clone, timeout=CAP_SECONDS)
        elapsed = time.monotonic() - start
        assert not ok and "longer than" in problem, (ok, problem)
        assert elapsed < BOUND_SECONDS, (
            f"the mail fetch's {CAP_SECONDS:.0f} s cap returned after {elapsed:.1f} s: git's own "
            "processes held the pipe past it, so the banner waits on the network, not its cap"
        )
