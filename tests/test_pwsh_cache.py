"""``tests/_pwsh_cache.py``: the private pwsh startup cache each test process
hands the pwsh it starts (DEF-4115). Pinned because parallel workers sharing
the user's cache corrupted it on the Air, and a corrupt cache aborts every
pwsh start on the box until the file is moved aside. The units read the
environment the helper builds and the directory it owns; the live row starts a
real pwsh and finds its cache in this process's directory, so a pwsh that stops
reading ``XDG_CACHE_HOME`` reds here instead of sharing the user's cache again.
``tests/test_test_suite_contract.py`` holds every pwsh spawn under tests/ to
the helper."""
from __future__ import annotations

# slow-exempt: one pwsh start of about 0.3 s on the Air, measured 2026-11-13

import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from tests import _pwsh_cache as pc
from tests import _temp_sweep as ts
from tests._wait_budget import scaled

# Keyed on the host, never on pc.REDIRECTS: a helper that stopped redirecting
# on POSIX would otherwise skip the rows that prove it redirects.
_POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="Windows is not redirected (tests/_pwsh_cache.py says why)")


class TestThePrivateCacheEnv:
    @_POSIX_ONLY
    def test_one_locked_directory_serves_every_spawn_in_this_process(self):
        directory = pc.cache_dir()
        assert pc.private_cache_env()["XDG_CACHE_HOME"] == str(directory)
        assert pc.private_cache_env({"PATH": "/bin"}) == {"PATH": "/bin", "XDG_CACHE_HOME": str(directory)}
        assert pc.cache_dir() == directory and directory.is_dir()
        # the sweep's own roster and lock: a killed run's cache goes at the next start
        assert directory.name.startswith(ts.OWNED_PREFIXES) and ts.lock_is_ours(directory)

    def test_the_callers_environment_is_copied_never_changed(self):
        base = {"PATH": "/bin"}
        before = dict(os.environ)
        env = pc.private_cache_env(base)
        assert base == {"PATH": "/bin"} and env is not base
        assert dict(os.environ) == before

    def test_windows_gets_the_environment_it_was_given(self, monkeypatch):
        monkeypatch.setattr(pc, "REDIRECTS", False)
        assert pc.private_cache_env({"PATH": "x", "XDG_CACHE_HOME": "/kept"}) == {
            "PATH": "x", "XDG_CACHE_HOME": "/kept"}
        # no base: None, so the child inherits this process's environment exactly
        assert pc.private_cache_env() is None

    @_POSIX_ONLY
    def test_each_thread_gets_a_directory_of_its_own(self):
        """The host-binding test starts pwsh four at a time from a thread pool:
        one directory a thread keeps each cache to one writer."""
        made: dict[int, Path] = {}
        both_alive = threading.Barrier(2)  # two live threads, so two idents

        def make(slot: int) -> None:
            both_alive.wait(timeout=scaled(10))
            made[slot] = pc.cache_dir()

        threads = [threading.Thread(target=make, args=(slot,)) for slot in (0, 1)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=scaled(10))
        assert sorted(made) == [0, 1], made
        assert made[0] != made[1] and made[0].is_dir() and made[1].is_dir()
        assert pc.cache_dir() not in (made[0], made[1])

    def test_a_forked_child_makes_a_directory_of_its_own(self, monkeypatch):
        """A forked child inherits the parent's mapping; keyed by pid, it makes
        its own directory rather than writing the parent's cache beside it."""
        parent = pc.cache_dir()
        child_pid = os.getpid() + 1
        monkeypatch.setattr(pc.os, "getpid", lambda: child_pid)
        try:
            child = pc.cache_dir()
            assert child != parent and child.is_dir() and parent.is_dir()
        finally:
            monkeypatch.undo()
            made = pc._OWNED.pop((child_pid, threading.get_ident()), None)
            if made is not None:
                ts.remove(made, ts.deleter())

    def test_the_exit_handler_removes_the_directory_in_its_maker_alone(self, tmp_path):
        made = tmp_path / "cache"
        (made / "powershell").mkdir(parents=True)
        ts.write_lock(made)
        pc._remove_if_ours(made, os.getpid() + 1, ts.deleter())  # a forked child's exit
        assert made.is_dir()
        pc._remove_if_ours(made, os.getpid(), ts.deleter())
        assert not made.exists()


class TestARealPwshWritesItsCacheHere:
    @_POSIX_ONLY
    def test_the_startup_cache_lands_in_this_processs_directory(self):
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if shell is None:
            pytest.skip("no pwsh or powershell on PATH to start")
        profile: Path = pc.cache_dir() / "powershell" / "StartupProfileData-NonInteractive"
        profile.unlink(missing_ok=True)  # this process is the file's one writer
        run = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", "Write-Output 1"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=scaled(30), env=pc.private_cache_env())
        assert run.stdout.strip() == "1", run.stderr
        assert profile.is_file(), sorted(str(p.relative_to(pc.cache_dir())) for p in pc.cache_dir().rglob("*"))
