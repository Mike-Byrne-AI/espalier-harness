"""A spawn's ``timeout`` bounds the call even when a grandchild holds its pipe.

On Windows ``subprocess.run`` kills only the child at the timeout and then
reads the pipes with no timeout, so a ``.bat`` shim's program, or the real git
behind Git for Windows's ``cmd\\git.exe`` launcher, set the bound instead
(2026-10-12, CPython 3.11.9: a 2 s cap returned after 20.1 s through a shim, a
1 s cap on ``git ls-remote`` after 21.1 s). ``_json_safe.run_bounded`` kills
the tree and drains under a grace; ``_hook_utils.spawn_checked`` is built on
it, and ``tests/test_spawn_chokepoint.py`` holds every timed spawn under
``tools/cc`` to one of the two (and drives the Windows branch on every OS with
a stand-in ``Popen``).

The oracle is an order, not a clock: each holder writes a ``done`` marker when
its ``HOLD_SECONDS`` sleep ends, and a bounded call returns before that marker
exists, where an unbounded one waits for the holder and finds it. A loaded box
can slow the call but cannot reorder it, so the module asserts no wall-clock
bound (``scripts/proof_tier.py::WALL_CLOCK_SERIAL_FILES`` is for those). On
POSIX ``run`` was already bounded, so the cases hold there as regression cases.
Real processes on every OS, so the module is slow.
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
from tests._platform_standin import as_os

TOOLS_CC = Path(__file__).resolve().parents[1] / "tools" / "cc"
CAP_SECONDS = 3.0  # long enough that the holder has surely started inside it
HOLD_SECONDS = 20  # how long the holder sleeps before it writes its marker


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


def _holder(tmp_path: Path) -> tuple[list[str], Path, Path]:
    """A launcher (``.bat`` on Windows, ``sh`` elsewhere) whose child -- the
    spawn's grandchild -- inherits stdout, writes its pid, sleeps, and then
    writes the ``done`` marker."""
    pidfile, done = tmp_path / "holder.pid", tmp_path / "holder.done"
    body = (f"import os, time; open({str(pidfile)!r}, 'w').write(str(os.getpid())); "
            f"print(1, flush=True); time.sleep({HOLD_SECONDS}); open({str(done)!r}, 'w').write('done')")
    if os.name == "nt":
        shim = tmp_path / "holder.bat"
        shim.write_bytes(f'@echo off\r\n"{sys.executable}" -c "{body}"\r\n'.encode("ascii"))
    else:
        shim = tmp_path / "holder.sh"
        shim.write_bytes(f'#!/bin/sh\n"{sys.executable}" -c "{body}"\n'.encode("ascii"))
        shim.chmod(0o755)
    return [str(shim)], pidfile, done


class TestTheTimeoutIsABound:
    def test_a_grandchild_holding_the_pipe_cannot_outlast_the_chokepoints_timeout(self, tmp_path):
        hu = _load_hook_utils()
        argv, pidfile, done = _holder(tmp_path)
        start = time.monotonic()
        try:
            with pytest.raises(subprocess.TimeoutExpired) as caught:
                hu.spawn_checked(argv, root=tmp_path, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=CAP_SECONDS)
            returned_first = not done.exists()
            took = time.monotonic() - start
            assert pidfile.exists(), "the holder never started inside the cap, so the case did not run"
            holder_alive = _alive(int(pidfile.read_text(encoding="utf-8").strip()))
        finally:
            _end_holder(pidfile)
        assert returned_first, (
            f"a {CAP_SECONDS:.0f} s timeout returned only after the holder finished its "
            f"{HOLD_SECONDS} s sleep ({took:.1f} s): the grandchild holding the pipe set the bound"
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
        whose upload-pack sleeps and then writes the marker (local, so no
        network decides the outcome). git's own processes hold the pipe here:
        the launcher on Windows."""
        if shutil.which("git") is None:
            pytest.skip("git is not on PATH")
        remote, clone, done = tmp_path / "remote.git", tmp_path / "clone", tmp_path / "upload-pack.done"
        uploadpack = f"sleep {HOLD_SECONDS}; echo done > '{done.as_posix()}' #"
        for argv in (["git", "init", "-q", "--bare", str(remote)], ["git", "init", "-q", str(clone)],
                     ["git", "-C", str(clone), "remote", "add", "origin", str(remote)],
                     ["git", "-C", str(clone), "config", "remote.origin.uploadpack", uploadpack]):
            subprocess.run(argv, check=True, capture_output=True, timeout=30)
        sys.path.insert(0, str(TOOLS_CC))
        try:
            import mail
        finally:
            sys.path.remove(str(TOOLS_CC))
        start = time.monotonic()
        ok, problem = mail.fetch_mail(clone, timeout=CAP_SECONDS)
        returned_first = not done.exists()
        took = time.monotonic() - start
        assert not ok and "longer than" in problem, (ok, problem)
        assert returned_first, (
            f"the mail fetch's {CAP_SECONDS:.0f} s cap returned only after the upload-pack finished "
            f"its {HOLD_SECONDS} s sleep ({took:.1f} s): git's own processes held the pipe past it, "
            "so the banner waits on the network, not its cap"
        )

    def test_an_engine_command_runner_is_bounded_by_its_cap(self, tmp_path):
        """The engine-level case (DEF-3004): ``espalier/pre_release.py``'s
        command runner, which ``espalier pre-release`` runs each gate command
        through, on the same holder. Before the engine had its own bounded
        spawn (``espalier/_spawn.py``) its call was ``subprocess.run``'s, and on
        Windows it returned only after the holder ended."""
        from espalier import pre_release

        argv, pidfile, done = _holder(tmp_path)
        start = time.monotonic()
        try:
            result = pre_release._run_command(argv, tmp_path, timeout_seconds=int(CAP_SECONDS))
            returned_first = not done.exists()
            took = time.monotonic() - start
            assert pidfile.exists(), "the holder never started inside the cap, so the case did not run"
        finally:
            _end_holder(pidfile)
        assert result["timed_out"], result
        assert returned_first, (
            f"the engine's {CAP_SECONDS:.0f} s command cap returned only after the holder finished "
            f"its {HOLD_SECONDS} s sleep ({took:.1f} s): the grandchild holding the pipe set the bound"
        )


def _load_script(rel: str):
    """A ``scripts/`` module by path, registered so its dataclasses resolve."""
    name = "_bound_" + rel.replace("/", "_").removesuffix(".py")
    spec = importlib.util.spec_from_file_location(name, str(TOOLS_CC.parents[1] / rel))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestAWatchdogEndsTheTree:
    """The same defect in the shape no census reads: a parent that streams its
    child's pipe line by line under a watchdog thread. A watchdog that kills
    only the child leaves the loop reading while a grandchild holds the pipe,
    on Windows (a venv's ``python.exe`` is a redirector, so the real
    interpreter is already a grandchild) and on POSIX (the tier's pytest
    outlives a killed parent). Both watchdogs end the whole tree."""

    def test_the_fresh_clone_gates_leg_bound_ends_the_tier(self, tmp_path):
        """``scripts/fresh_clone_gate.py::run_tier``: a leg past
        ``--leg-timeout`` is refused at the bound, not when the tier ends."""
        gate = _load_script("scripts/fresh_clone_gate.py")
        argv, pidfile, done = _holder(tmp_path)
        clone = tmp_path / "clone"
        (clone / "scripts").mkdir(parents=True)
        (clone / "scripts" / "proof_tier.py").write_bytes(
            f"import subprocess\nsubprocess.call({argv!r})\n".encode("utf-8"))
        start = time.monotonic()
        try:
            with pytest.raises(gate.GateRefusal, match="--leg-timeout"):
                gate.run_tier(Path(sys.executable), clone, dict(os.environ), tmp_path / "tier.log",
                              echo=lambda _line: None, timeout_s=CAP_SECONDS)
            returned_first = not done.exists()
            took = time.monotonic() - start
            assert pidfile.exists(), "the holder never started inside the bound, so the case did not run"
        finally:
            _end_holder(pidfile)
        assert returned_first, (
            f"the gate's {CAP_SECONDS:.0f} s leg bound returned only after the holder finished its "
            f"{HOLD_SECONDS} s sleep ({took:.1f} s): the watchdog ended the child, not the tree"
        )

    def test_the_archive_probes_suite_bound_ends_pytest(self, tmp_path):
        """``scripts/archive_probe.py::run_pytest``: pytest past the suite bound
        is ended with everything it started."""
        probe = _load_script("scripts/archive_probe.py")
        argv, pidfile, done = _holder(tmp_path)
        target = tmp_path / "target"
        target.mkdir()
        (target / "test_hold.py").write_bytes(
            f"import subprocess\n\ndef test_hold():\n    subprocess.call({argv!r})\n".encode("utf-8"))
        bound = 3 * CAP_SECONDS  # pytest's own start-up comes first
        start = time.monotonic()
        try:
            rc = probe.run_pytest(Path(sys.executable), target,
                                  ["-q", "-s", "-p", "no:cacheprovider", "test_hold.py"],
                                  dict(os.environ), timeout_s=bound, echo=lambda _line: None)
            returned_first = not done.exists()
            took = time.monotonic() - start
            assert pidfile.exists(), "the holder never started inside the bound, so the case did not run"
        finally:
            _end_holder(pidfile)
        assert rc == probe.EXIT_TIMEOUT, rc
        assert returned_first, (
            f"the probe's {bound:.0f} s suite bound returned only after the holder finished its "
            f"{HOLD_SECONDS} s sleep ({took:.1f} s): the watchdog ended pytest, not its tree"
        )


#: The bounded spawn's three copies (``tests/test_contracts.py::
#: TestTheBoundedSpawnTwins`` holds their code equal; this drives each).
_COPIES = ("tools/cc/_json_safe.py", "espalier/_spawn.py", "espalier/scanners/freshness.py")


def _load_copy(rel: str):
    if rel == "espalier/_spawn.py":
        from espalier import _spawn
        return _spawn
    if rel == "espalier/scanners/freshness.py":
        from espalier.scanners import freshness
        return freshness
    spec = importlib.util.spec_from_file_location("json_safe_for_every_copy", str(TOOLS_CC / "_json_safe.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stand_in_popen(calls: list) -> type:
    """A ``Popen`` that records what the harness does with it in ``calls`` and
    answers from a ``plan`` the test sets (a return code, ``"timeout"``, or an
    exception to raise). It is a context manager too, so the standard library's
    own ``subprocess.run`` can hold it when the platform is read as POSIX."""

    class StandInPopen:
        plan: list = []

        def __init__(self, args, **kw):
            calls.append(("popen", args, kw))
            self.args, self.pid, self.returncode = args, 4242, None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def poll(self):
            return self.returncode

        def communicate(self, input=None, timeout=None):
            calls.append(("communicate", input, timeout))
            step = StandInPopen.plan.pop(0)
            if isinstance(step, BaseException):
                raise step
            if step == "timeout":
                raise subprocess.TimeoutExpired(self.args, timeout)
            self.returncode = step
            return ("out", "err")

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            return self.returncode if self.returncode is not None else 1

        def kill(self):
            calls.append(("kill",))

    return StandInPopen


class TestEveryCopysWindowsBranch:
    """Each copy's Windows branch, driven on every OS with a stand-in ``Popen``
    and the platform read as ``win32`` through ``tests/_platform_standin.py``
    (the required cells are Linux, where the call is ``subprocess.run``), the
    tree kill recorded rather than made."""

    @pytest.fixture(params=_COPIES)
    def windows(self, request, monkeypatch):
        mod = _load_copy(request.param)
        calls: list[tuple] = []
        StandInPopen = _stand_in_popen(calls)
        as_os(monkeypatch, "windows", os_name=False)
        monkeypatch.setattr(subprocess, "Popen", StandInPopen)
        monkeypatch.setattr(mod, "_end_tree", lambda proc, end: calls.append(("end_tree", proc.pid)))
        return mod, StandInPopen, calls

    def test_at_the_timeout_the_tree_ends_then_the_pipes_drain_then_the_child_is_reaped(self, windows):
        mod, popen, calls = windows
        popen.plan = ["timeout", 0]
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            mod.run_bounded(["git", "log"], timeout=3, capture_output=True, text=True, encoding="utf-8")
        assert [c[0] for c in calls] == ["popen", "communicate", "end_tree", "communicate", "wait"], calls
        assert calls[0][2]["stdout"] is subprocess.PIPE and calls[0][2]["stderr"] is subprocess.PIPE
        assert calls[1][2] == 3 and calls[3][2] <= mod.SPAWN_KILL_GRACE_SECONDS, calls
        assert (caught.value.stdout, caught.value.stderr) == ("out", "err")

    def test_check_and_the_argument_errors_are_runs_own(self, windows):
        mod, popen, calls = windows
        popen.plan = [2]
        with pytest.raises(subprocess.CalledProcessError) as caught:
            mod.run_bounded(["git"], timeout=3, capture_output=True, check=True)
        assert (caught.value.returncode, caught.value.output) == (2, "out")
        with pytest.raises(ValueError, match="stdin and input"):
            mod.run_bounded(["git"], timeout=3, input="x", stdin=subprocess.PIPE)

    def test_an_interrupt_mid_call_ends_the_tree_and_goes_on(self, windows):
        mod, popen, calls = windows
        popen.plan = [KeyboardInterrupt()]
        with pytest.raises(KeyboardInterrupt):
            mod.run_bounded(["git"], timeout=3)
        assert [c[0] for c in calls] == ["popen", "communicate", "end_tree", "wait"], calls

    def test_a_stand_in_run_is_honoured(self, windows, monkeypatch):
        mod, popen, calls = windows
        seen: list = []

        def fake(args, **kw):
            seen.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake)
        mod.run_bounded(["git"], timeout=3)
        assert seen == [["git"]] and calls == [], (seen, calls)

    @pytest.mark.parametrize("target_os", ["linux", "windows"])
    def test_the_timeout_shape_follows_the_platform_the_harness_reads(self, target_os, monkeypatch):
        """Read as ``windows``, every copy ends the child's whole tree at the
        timeout, drains the pipes and reaps it (the one shape that bounds a
        grandchild holding the pipe, the sharp edge this module exists for);
        read as ``linux``, the call is ``subprocess.run``'s own and the child
        alone is killed. The standard library's ``run`` stays in place on
        purpose: ``_is_stdlib_run`` (``tools/cc/_json_safe.py``, the guard on
        the Windows branch) sends a replaced ``run`` down the run branch at
        BOTH values, so a node observing a fake ``run`` could not tell the two
        apart; only the stand-in ``Popen`` is replaced, and ``run`` holds it as
        its context manager. One node, two platforms, on whatever host runs it:
        this is the adopter-axes registry's proof of the ``target_os/linux`` and
        ``target_os/windows`` cells (tests/_axis_registry.py), so it carries the
        ``target_os`` parameter and no skip, since a Linux cell that skipped the
        Windows shape would prove nothing about it."""
        copies = [(rel, _load_copy(rel)) for rel in _COPIES]  # imported before the platform is faked
        as_os(monkeypatch, target_os, os_name=False)
        for rel, mod in copies:
            calls: list[tuple] = []
            popen = _stand_in_popen(calls)
            popen.plan = ["timeout", 0]
            monkeypatch.setattr(subprocess, "Popen", popen)
            monkeypatch.setattr(mod, "_end_tree", lambda proc, end: calls.append(("end_tree", proc.pid)))
            with pytest.raises(subprocess.TimeoutExpired):
                mod.run_bounded(["git", "log"], timeout=3, capture_output=True, text=True, encoding="utf-8")
            names = [c[0] for c in calls]
            if target_os == "windows":
                assert names == ["popen", "communicate", "end_tree", "communicate", "wait"], (rel, calls)
            else:
                # subprocess.run's own handler: kill the child, then wait (POSIX)
                # or drain (a Windows host); the tree is never ended.
                assert "end_tree" not in names and names[:3] == ["popen", "communicate", "kill"], (rel, calls)


class TestTheEngineWrapperClosesTheChildsStdin:
    """``espalier/_spawn.py::run_no_stdin`` (DEF-928): ``run_bounded`` with the
    child's stdin closed unless the caller feeds it."""

    @pytest.fixture
    def handed(self, monkeypatch):
        from espalier import _spawn
        calls = []
        monkeypatch.setattr(_spawn, "run_bounded", lambda args, **kw: calls.append(kw) or "ran")
        return _spawn.run_no_stdin, calls

    def test_a_child_handed_nothing_gets_a_closed_stdin(self, handed):
        run_no_stdin, calls = handed
        assert run_no_stdin(["git", "log"], timeout=5) == "ran"
        assert calls == [{"input": None, "stdin": subprocess.DEVNULL, "timeout": 5}]

    def test_a_stdin_of_none_counts_as_none_given(self, handed):
        run_no_stdin, calls = handed
        run_no_stdin(["git", "log"], stdin=None)
        assert calls == [{"input": None, "stdin": subprocess.DEVNULL}]

    def test_a_stdin_the_caller_gives_is_left_as_given(self, handed):
        run_no_stdin, calls = handed
        run_no_stdin(["git", "log"], stdin=subprocess.PIPE)
        assert calls == [{"input": None, "stdin": subprocess.PIPE}]

    def test_a_child_fed_input_gets_no_stdin_of_the_wrappers(self, handed):
        """The two engine spawns that feed their child keep feeding it."""
        run_no_stdin, calls = handed
        run_no_stdin(["git", "hash-object", "--stdin"], input="body")
        assert calls == [{"input": "body"}]

    def test_the_child_reads_end_of_file_at_once(self):
        """A real child: the stdin it is handed is empty and closed, so a read
        returns at once instead of waiting on a pipe the suite holds open."""
        from espalier._spawn import run_no_stdin
        proc = run_no_stdin([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert proc.returncode == 0 and proc.stdout.strip() == "''", (proc.stdout, proc.stderr)


@pytest.mark.skipif(sys.platform != "win32", reason="the handle duplication is Windows's (Popen._get_handles)")
class TestTheWrappersHandleTradeOnWindows:
    """What ``run_no_stdin`` costs (DEF-928, the dispatcher's 3bbff2): a child
    handed a stdin has its stdout and stderr duplicated from the parent, so a
    child that streams to a dead output handle no longer starts, where with all
    three handles left alone it did. Measured, not guarded: a dead stdout with a
    live stdin is not the row's user. A guard that changes this reds here."""

    def test_a_streaming_child_on_a_dead_stdout_starts_bare_and_not_through_the_wrapper(self, tmp_path):
        import json

        out = tmp_path / "trade.json"
        driver = (
            "import ctypes, json, subprocess, sys, _winapi\n"
            "from espalier._spawn import run_no_stdin\n"
            "ctypes.windll.kernel32.SetStdHandle(_winapi.STD_OUTPUT_HANDLE, ctypes.c_void_p(0x0BAD0))\n"
            "seen = {}\n"
            "for name, start in (('bare', lambda: subprocess.run([sys.executable, '-c', 'pass'])),\n"
            "                    ('wrapper', lambda: run_no_stdin([sys.executable, '-c', 'pass']))):\n"
            "    try:\n"
            "        seen[name] = start().returncode\n"
            "    except OSError as exc:\n"
            "        seen[name] = getattr(exc, 'winerror', None)\n"
            "open(sys.argv[1], 'w', encoding='utf-8').write(json.dumps(seen))\n"
        )
        subprocess.run([sys.executable, "-c", driver, str(out)], check=True, stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=30)  # two bare starts, about 1 s; under the 60 s ceiling
        assert json.loads(out.read_text(encoding="utf-8")) == {"bare": 0, "wrapper": 6}
