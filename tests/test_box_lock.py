"""The box lock: two xdist runs of the suite on one machine never run tests at once.

``tests/_box_lock.py`` takes a kernel lock on the file ``ESPALIER_BOX_LOCK``
names when the run is an xdist run that will run tests, names the holder while
it waits, passes a nested run through on the inherited holder pair, says what
it did in the terminal summary, and leaves a record of every wait and every
release. Each case here but ``TestEachHoldLogsItsRelease`` (in-process, on
what the plugin writes) drives real pytest children on a scratch test file
with the plugin loaded by ``-p``, the way ``tests/test_file_lock.py`` drives the primitive: what the
kernel does is the question, so only real processes can answer it. A holder
never sleeps for a margin: it waits on a release marker the test writes, and
the test writes it at the waiter's own first waiting line, never after a sleep,
so a loaded box slows a case down and never turns it red. This file pins that
contract because a lock the suite forgets is the note protocol again: it guards
the gate (xdist runs only), the holder pair, the record's lifetime, the wait
log, the summary line and the census of pytest spawners against the drift a
refactor would bring. Each docstring names the mutation the test dies to
(tests/CLAUDE.md rule 1).
"""
# pytest-marker: security -- the lock serialises the suite's own runs on a box;
# every case spawns real pytest children with xdist workers, so the file is
# also in conftest's _SLOW_FILES beside test_file_lock.
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import types
from pathlib import Path
from typing import IO

import pytest

from tests._tree_spawn import communicate_tree_bounded

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Every wait here stays well under pytest-timeout's 60 s: under the thread
#: method (Windows) a test that reaches it ends the WHOLE run, so a hang must
#: fail this test on its own clock first.
_CHILD_DEADLINE_S = 45

_SCRATCH_TEST = '''\
import os, time
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract


def test_marks_and_waits():
    stamp = Path(os.environ["BOX_PROBE_STAMP"])
    stamp.write_text(f"{time.time():.3f}", encoding="utf-8")
    hold = os.environ.get("BOX_PROBE_HOLD")
    if hold:
        deadline = time.monotonic() + 40
        while not Path(hold).exists() and time.monotonic() < deadline:
            time.sleep(0.05)
    (stamp.parent / (stamp.name + ".done")).write_text(f"{time.time():.3f}", encoding="utf-8")
'''

#: How long, at most, a waiter's controller sits in the scratch conftest before
#: its ``pytest_configure`` takes the lock: until the lock is free, or this
#: long. A case that releases its holder at the waiter's own line holds the lock
#: all along, so its waiter sits the whole time, as a loaded runner still
#: importing pytest would. A case that releases on a margin instead (the 0.8 to
#: 1.0 s the waits once slept) frees the lock first, so its waiter arrives to a
#: free lock, takes it without a word, and the case reds wherever the holder
#: frees the lock inside this time (0.05 to 0.11 s after the marker on the win
#: box, 2026-10-31; DEF-2027). A fixed sleep here would only race the holder's
#: release. The xdist worker never sits.
_SLOW_WAITER_S = 3.0

_SCRATCH_CONFTEST = '''\
import os, time

if "PYTEST_XDIST_WORKER" not in os.environ:
    pid_file = os.environ["BOX_PROBE_STAMP"] + ".pid"
    with open(pid_file + ".tmp", "w", encoding="utf-8") as out:
        out.write(str(os.getpid()))
    os.replace(pid_file + ".tmp", pid_file)
    slow, path = float(os.environ.get("BOX_PROBE_SLOW_S") or 0), os.environ.get("ESPALIER_BOX_LOCK")
    if slow and path:
        from tests._box_lock import _primitive
        lock, deadline = _primitive(), time.monotonic() + slow
        with open(path, "a+", encoding="utf-8") as fh:
            while time.monotonic() < deadline:
                if lock.try_lock_file(fh):
                    lock.unlock_file(fh)
                    break
                time.sleep(0.05)
'''


def _box_lock():
    from tests import _box_lock
    return _box_lock


def _scratch(tmp_path: Path) -> Path:
    tree = tmp_path / "scratch"
    tree.mkdir(exist_ok=True)
    (tree / "test_probe.py").write_text(_SCRATCH_TEST, encoding="utf-8")
    (tree / "conftest.py").write_text(_SCRATCH_CONFTEST, encoding="utf-8")
    return tree


def _child_env(tmp_path: Path, lock: Path | None, *, stamp: str, hold: bool = False,
               holder: str | None = None, slow: bool = False) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "ESPALIER_BOX_LOCK", "PYTEST_ADDOPTS", "PYTEST_XDIST", "BOX_PROBE"))}
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["BOX_PROBE_STAMP"] = str(tmp_path / stamp)
    if hold:
        env["BOX_PROBE_HOLD"] = str(tmp_path / f"{stamp}.release")
    if slow:
        env["BOX_PROBE_SLOW_S"] = str(_SLOW_WAITER_S)
    if lock is not None:
        env["ESPALIER_BOX_LOCK"] = str(lock)
    if holder is not None:
        env["ESPALIER_BOX_LOCK_HOLDER"] = holder
    return env


def _spawn(tmp_path: Path, tree: Path, env: dict[str, str], *extra: str, workers: str | None = "1") -> subprocess.Popen:
    # A basetemp of its own: the planted tree loads no suite conftest, and its
    # xdist controller would mint a numbered dir on pytest's shared root and
    # delete the finished ones there at its end (DEF-5056).
    basetemp = tempfile.mkdtemp(prefix="basetemp-", dir=tmp_path)
    argv = [sys.executable, "-m", "pytest", str(tree / "test_probe.py"), "-q", "-p", "no:cacheprovider",
            "-p", "tests._box_lock", f"--basetemp={basetemp}",
            *(["-n", workers] if workers is not None else []), *extra]
    return subprocess.Popen(argv, cwd=str(tree), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8")


def _release(tmp_path: Path, stamp: str) -> None:
    (tmp_path / f"{stamp}.release").write_text("1", encoding="utf-8")


def _wait_for(path: Path, timeout: float = 25.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.02)
    return path.exists()


def _finish(child: subprocess.Popen, rc: int = 0) -> tuple[str, str]:
    # A run past the deadline is ended with its xdist workers, never left at parent 1.
    out, err = communicate_tree_bounded(child, timeout=_CHILD_DEADLINE_S)
    assert child.returncode == rc, f"rc={child.returncode}\n{out}\n{err}"
    return out, err


def _stamp(tmp_path: Path, name: str) -> float:
    return float((tmp_path / name).read_text(encoding="utf-8"))


def _said_pid(path: Path) -> int:
    """The pid a run wrote for itself (the scratch conftest's ``<stamp>.pid``,
    a plain holder's ``<tag>.ready``). Under a Windows venv ``Popen.pid`` is the
    ``python.exe`` redirector's, never the interpreter's whose pid the lock
    record holds, so a case that compared it red on a lock that works
    (DEF-2028: the three names the win box's full tier carried)."""
    return int(path.read_text(encoding="utf-8"))


def _holding(tmp_path: Path, tree: Path, lock: Path, stamp: str = "a", *, workers: str = "1") -> subprocess.Popen:
    """A gated run that holds the box until the test releases it: a serial
    line at one worker (every slot), a parallel line's one slot at more."""
    first = _spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp=stamp, hold=True), workers=workers)
    assert _wait_for(tmp_path / stamp), _finish(first)
    return first


_WAITING = "box lock: waiting on"


class _Waiter:
    """A run spawned to wait behind a holder, its stderr read on a thread from
    the spawn on, so the test releases the holder at the run's first ``box
    lock: waiting on`` line (the plugin prints it, flushed, at its first failed
    try) and never after a margin. A margin's check, that the run has not
    exited and wrote no stamp, is also true of a run still importing pytest, so
    a slow runner released the holder before the run reached the lock and the
    line never came (DEF-2027: the Windows portability leg on #354). Mutation:
    a margin put back at any site (each case asserts after the run what only a
    run that waited prints or logs, and every waiter sits in the scratch
    conftest until the lock is free, ``_SLOW_WAITER_S``); the line read
    anywhere but the waiter's stderr."""

    def __init__(self, tmp_path: Path, tree: Path, env: dict[str, str], *extra: str) -> None:
        self.child = _spawn(tmp_path, tree, env, *extra)
        self.lines: list[str] = []
        self._said = threading.Event()  # at the waiting line, or at the stream's end without one
        # The reader owns the pipe from here, so communicate() reads stdout alone.
        stream, self.child.stderr = self.child.stderr, None
        self._reader = threading.Thread(target=self._read, args=(stream,), daemon=True)
        self._reader.start()

    def _read(self, stream: IO[str]) -> None:
        with stream:
            for line in stream:
                self.lines.append(line)
                if line.startswith(_WAITING):
                    self._said.set()
        self._said.set()

    @property
    def stderr(self) -> str:
        return "".join(self.lines)

    def at_the_lock(self, timeout: float = 25.0) -> bool:
        """Whether the run said it waits within ``timeout``: False as soon as
        its stderr ends without the line (a run that never waited)."""
        self._said.wait(timeout)
        return any(line.startswith(_WAITING) for line in self.lines)

    def finish(self, rc: int = 0) -> tuple[str, str]:
        out, _ = communicate_tree_bounded(self.child, timeout=_CHILD_DEADLINE_S)
        self._reader.join(timeout=_CHILD_DEADLINE_S)
        err = self.stderr
        assert self.child.returncode == rc, f"rc={self.child.returncode}\n{out}\n{err}"
        return out, err


class TestTwoRunsOnOneBox:
    def test_the_second_run_waits_names_the_holder_and_runs_after_it(self, tmp_path):
        """Mutation: the non-blocking try replaced by the blocking ``lock_file``
        (the waiter sits silent and never prints the holder); the plugin not
        registered under ``-n`` (both runs' tests overlap)."""
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        first = _holding(tmp_path, tree, lock)
        second = _Waiter(tmp_path, tree, _child_env(tmp_path, lock, stamp="b", slow=True))
        assert second.at_the_lock(), second.stderr
        assert second.child.poll() is None and not (tmp_path / "b").exists(), "the second run's test ran while the first held the box"
        _release(tmp_path, "a")
        out, err = second.finish()
        _finish(first)
        holder_pid = _said_pid(tmp_path / "a.pid")
        assert "box lock: waiting on" in err and f"pid {holder_pid}" in err, err
        assert "box lock: waited" in out and f"pid {holder_pid}" in out, out
        assert _stamp(tmp_path, "b") >= _stamp(tmp_path, "a.done")

    def test_a_finished_holder_leaves_an_empty_record_and_the_next_run_waits_on_nobody(self, tmp_path):
        """Mutation: the record not truncated at ``pytest_unconfigure``, so the
        next waiter would read a finished run's pid as the holder."""
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        _finish(_spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp="a")))
        assert lock.read_text(encoding="utf-8") == ""
        out, err = _finish(_spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp="b")))
        assert "box lock" not in err and "box lock" not in out

    def test_every_gated_run_leaves_a_line_naming_what_the_lock_did_and_each_hold_its_release(self, tmp_path):
        """DEF-4053: the log held waits alone, so an empty one could not tell
        no waits from no gated runs. Now the holder that took the lock at once
        leaves a ``taken`` line and the run behind it a ``waited`` line naming
        its holder and its wait; and DEF-3084: each hold leaves a ``released``
        line, the holder's before the waiter's acquire, so the two processes'
        lines pair in file order. Mutation: a line written for waits alone, or
        a wait's line without its holder or its length; no release line, or
        one for the run that only waited (the hold's length is
        :class:`TestEachHoldLogsItsRelease`'s)."""
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        first = _holding(tmp_path, tree, lock)
        second = _Waiter(tmp_path, tree, _child_env(tmp_path, lock, stamp="b", slow=True))
        assert second.at_the_lock(), second.stderr
        _release(tmp_path, "a")
        second.finish()
        _finish(first)
        lines = [json.loads(ln) for ln in (tmp_path / "box.lock.log").read_text(encoding="utf-8").splitlines() if ln.strip()]
        holder_pid, waiter_pid = _said_pid(tmp_path / "a.pid"), _said_pid(tmp_path / "b.pid")
        assert [(ln["outcome"], ln["run"]["pid"]) for ln in lines] == [
            ("taken", holder_pid), ("released", holder_pid), ("waited", waiter_pid), ("released", waiter_pid)], lines
        assert lines[0]["waited_s"] == 0 and lines[0]["holder"]["pid"] is None
        assert lines[2]["holder"]["pid"] == holder_pid and lines[2]["waited_s"] > 0
        assert all(ln["held_s"] > 0 for ln in (lines[1], lines[3])), lines

    def test_the_locks_own_missing_folder_is_made_and_a_deeper_one_is_not(self, tmp_path):
        """DEF-4053: the launcher's default lives in ``~/.espalier``, which
        no run has made on a fresh home; the plugin makes the lock's own
        folder, one level, so the first gated run takes the lock. Mutation:
        no folder made (that run goes unguarded), or a chain of folders made
        (a mistyped path builds directories instead of saying so)."""
        tree = _scratch(tmp_path)
        (tmp_path / "home").mkdir()
        lock = tmp_path / "home" / ".espalier" / "box.lock"
        out, err = _finish(_spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp="m")))
        assert "box lock" not in err and "unguarded" not in out, (out, err)
        line = json.loads((lock.parent / "box.lock.log").read_text(encoding="utf-8").splitlines()[0])
        assert line["outcome"] == "taken" and line["run"]["pid"] == _said_pid(tmp_path / "m.pid")
        deep = tmp_path / "home" / "no" / "such" / "box.lock"
        out, err = _finish(_spawn(tmp_path, tree, _child_env(tmp_path, deep, stamp="n")))
        assert "box lock: not taken (FileNotFoundError" in err and not (tmp_path / "home" / "no").exists(), err


class TestEachHoldLogsItsRelease:
    """DEF-3084: the log named each acquire and no release, so how long the
    lock was held, and so how full a box was, could not be read from it (2174
    lines on the win box's log on 2026-11-15, none a release). In-process on
    the plugin's own ``BoxLock``, since what the kernel does is the subprocess
    cases' above; the holder variable a take exports is put back after each
    test. A run that never held writes no release: the pass-through and
    unguarded cases above pin their logs whole."""

    @staticmethod
    def _lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, primitive: object = None) -> object:
        import io
        bl = _box_lock()
        # Recorded first, so the take's export of this pid is undone: an xdist
        # worker's later nested runs must keep their tier's holder pid.
        monkeypatch.setenv(bl.HOLDER_KEY, os.environ.get(bl.HOLDER_KEY, "0"))
        record = {"seat": "s", "lane": "l", "checkout": str(tmp_path), "pid": os.getpid(), "argv": ["pytest"]}
        return bl.BoxLock(tmp_path / "box.lock", record, primitive or bl._primitive(), stream=io.StringIO())

    @staticmethod
    def _lines(tmp_path: Path) -> list[dict]:
        log = tmp_path / "box.lock.log"
        return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()] if log.exists() else []

    def test_a_hold_logs_its_length_and_its_start_at_the_take(self, tmp_path, monkeypatch):
        """Mutation: no line at the release; a release line without
        ``held_s``, or with the wait in its place; its start stamped at the
        release (a hold past a second reads a start and an end a second or
        more apart)."""
        from datetime import datetime
        lock = self._lock(tmp_path, monkeypatch)
        lock.acquire()
        # The hold's length, which the line must carry: nothing races it. Past
        # the 1.2 asserted, since Windows' monotonic clock ticks at 15.6 ms and
        # a 1.2 s sleep read 1.187 in 10 of 150 holds (the lane's review).
        time.sleep(1.3)
        lock.release()
        lines = self._lines(tmp_path)
        assert [ln["outcome"] for ln in lines] == ["taken", "released"], lines
        taken, released = lines
        assert released["run"] == taken["run"] and released["run"]["pid"] == os.getpid(), lines
        assert released["held_s"] >= 1.2 and released["waited_s"] == 0 and "held_s" not in taken, lines
        start, end = (datetime.fromisoformat(released[k]) for k in ("start", "end"))
        assert 1 <= (end - start).total_seconds() <= released["held_s"] + 1, released
        assert lock.fh is None and not lock.held

    def test_the_release_line_is_written_before_the_lock_goes(self, tmp_path, monkeypatch):
        """Written after the unlock, a waiter polling every ``POLL_S`` could
        take the lock and log its acquire first, and a reader pairing a hold's
        lines in file order would read the wrong pair. Mutation: the line
        logged after ``unlock_file``, or not at all."""
        bl = _box_lock()
        real, at_unlock = bl._primitive(), []

        def unlock_file(fh: IO[str]) -> None:
            at_unlock.append([ln["outcome"] for ln in self._lines(tmp_path)])
            real.unlock_file(fh)

        lock = self._lock(tmp_path, monkeypatch, types.SimpleNamespace(try_lock_file=real.try_lock_file,
                                                                       unlock_file=unlock_file,
                                                                       box_lock_slots=real.box_lock_slots,
                                                                       BOX_LOCK_MAX_SLOTS=real.BOX_LOCK_MAX_SLOTS))
        lock.acquire()
        lock.release()
        assert at_unlock == [["taken", "released"]], at_unlock

    def test_the_holds_length_runs_from_the_take_never_from_the_queue(self, tmp_path, monkeypatch):
        """A run that queued must not read its wait as its hold (DEF-4077's
        class, there for the hold's age). The take is refused three times at a
        0.1 s poll, then the hold is released at once. Mutation: the hold
        timed from the wait's start."""
        bl = _box_lock()
        real, refusals = bl._primitive(), [3]

        def try_lock_file(fh: IO[str]) -> bool:
            if refusals[0]:
                refusals[0] -= 1
                return False
            return real.try_lock_file(fh)

        monkeypatch.setattr(bl, "POLL_S", 0.1)
        monkeypatch.delenv(bl.WAIT_KEY, raising=False)
        lock = self._lock(tmp_path, monkeypatch, types.SimpleNamespace(try_lock_file=try_lock_file,
                                                                       unlock_file=real.unlock_file,
                                                                       box_lock_slots=real.box_lock_slots,
                                                                       BOX_LOCK_MAX_SLOTS=real.BOX_LOCK_MAX_SLOTS))
        lock.acquire()
        lock.release()
        waited, released = self._lines(tmp_path)
        assert (waited["outcome"], released["outcome"]) == ("waited", "released"), (waited, released)
        assert waited["waited_s"] >= 0.25 and released["held_s"] < waited["waited_s"] / 2, (waited, released)

    def test_an_acquire_that_fails_before_its_line_logs_no_release(self, tmp_path, monkeypatch):
        """A failure between the take and its acquire line (here the stamp)
        releases the lock and leaves no ``released`` line without an acquire
        line to pair with (the lane's review drove it). Mutation: the release
        line keyed on the hold alone."""
        bl = _box_lock()
        lock = self._lock(tmp_path, monkeypatch)

        def stamp() -> str:
            raise RuntimeError("stamp")

        monkeypatch.setattr(bl, "_now_stamp", stamp)
        with pytest.raises(RuntimeError):
            lock.acquire()
        assert not lock.held and self._lines(tmp_path) == []


class TestWhichRunsTheLockGates:
    def test_a_run_without_xdist_takes_no_lock_and_runs_beside_a_holder(self, tmp_path):
        """A run without ``-n`` is not a tier: a reviewer's or an agent's
        node-id or file run never waits (and never past a Bash call's cap).
        Mutation: every run gated."""
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        first = _holding(tmp_path, tree, lock)
        plain = _spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp="b"), workers=None)
        out, err = _finish(plain)
        assert first.poll() is None, "the holder had finished before the plain run did"
        assert "box lock" not in err and "box lock" not in out
        _release(tmp_path, "a")
        _finish(first)

    def test_a_contract_marked_xdist_run_takes_the_lock_too(self, tmp_path):
        """Every tier line runs under xdist, the contract slice included (since
        2026-10-16), so a seat's slice waits behind a sibling's tier: the gate
        reads the option, not the selection. Mutation: a marker expression or
        a selection read as an exemption; the waiting line left unasserted
        after the run (a holder released early keeps the stamp order, so the
        order alone passes an exempted slice)."""
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        first = _holding(tmp_path, tree, lock)
        slice_ = _Waiter(tmp_path, tree, _child_env(tmp_path, lock, stamp="b", slow=True), "-m", "contract")
        assert slice_.at_the_lock(), slice_.stderr
        assert slice_.child.poll() is None and not (tmp_path / "b").exists()
        _release(tmp_path, "a")
        _out, err = slice_.finish()
        _finish(first)
        assert "box lock: waiting on" in err, err
        assert _stamp(tmp_path, "b") >= _stamp(tmp_path, "a.done")

    def test_without_the_variable_nothing_is_registered(self, tmp_path):
        """CI never sets the variable, so the suite there is unchanged.
        Mutation: a default path taken when the variable is unset."""
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        first = _holding(tmp_path, tree, lock)
        unset = _spawn(tmp_path, tree, _child_env(tmp_path, None, stamp="b"))
        out, err = _finish(unset)
        assert first.poll() is None and "box lock" not in err and "box lock" not in out
        _release(tmp_path, "a")
        _finish(first)

    def test_the_gate_reads_numprocesses_from_the_config_never_the_argv(self):
        """``PYTEST_ADDOPTS=-n 2`` counts and ``-n 0`` takes none (the
        dispatcher's reading, 2026-10-26); ``--help`` and ``--markers`` run no
        test. Mutation: a scan of ``sys.argv`` for ``-n``, or a gate on the
        option's presence rather than its value."""
        bl = _box_lock()
        cfg = types.SimpleNamespace(option=types.SimpleNamespace(numprocesses=2, collectonly=False))
        assert bl.gated(cfg) is True
        cfg.option.numprocesses = 0
        assert bl.gated(cfg) is False
        cfg.option.numprocesses = None
        assert bl.gated(cfg) is False
        cfg.option.numprocesses = "auto"
        assert bl.gated(cfg) is True
        cfg.option.collectonly = True
        assert bl.gated(cfg) is False
        cfg.option.collectonly = False
        cfg.option.help = True
        assert bl.gated(cfg) is False

    def test_configure_on_a_config_without_options_takes_nothing_and_raises_nothing(self, tmp_path, monkeypatch):
        """The suite's own configure tests call ``conftest.pytest_configure``
        with a stub config that has no ``option``; with the variable set (any
        seat the launcher started) the first cut raised there (failure-mode
        review, 2026-10-26). Mutation: a config read outside the plugin's
        ``try``."""
        bl = _box_lock()
        lock = tmp_path / "box.lock"
        monkeypatch.setenv("ESPALIER_BOX_LOCK", str(lock))
        registered: list = []
        manager = types.SimpleNamespace(hasplugin=lambda name: False, register=lambda obj, name: registered.append(name))
        bl.pytest_configure(types.SimpleNamespace(pluginmanager=manager))
        assert registered == [] and not lock.exists()
        bl.pytest_configure(types.SimpleNamespace())  # no plugin manager either
        assert registered == []


class TestTheInheritedPair:
    @staticmethod
    def _holder(tmp_path: Path, lock: Path, record_pid: int | None, *, tag: str = "h") -> subprocess.Popen:
        """A plain process holding the lock with a record naming ``record_pid``
        (its own when None), the shape of a parent run's hold; it says its own
        pid in ``<tag>.ready``, written whole and renamed into place, and
        releases when the test writes ``<tag>.release``."""
        code = textwrap.dedent(f"""
            import json, os, sys, time
            from pathlib import Path
            sys.path.insert(0, {str(REPO_ROOT / 'tools' / 'cc')!r})
            from _json_safe import try_lock_file
            fh = open({str(lock)!r}, "a+", encoding="utf-8")
            assert try_lock_file(fh)
            fh.seek(0); fh.truncate()
            fh.write(json.dumps({{"pid": {record_pid if record_pid is not None else 'os.getpid()'}, "seat": "s", "lane": "l",
                                 "started": "2026-10-26T00:00:00Z", "argv": ["pytest"]}}))
            fh.flush()
            ready = Path({str(tmp_path / (tag + '.ready'))!r})
            ready.with_suffix(".tmp").write_text(str(os.getpid()))
            os.replace(ready.with_suffix(".tmp"), ready)
            release = Path({str(tmp_path / (tag + '.release'))!r})
            deadline = time.monotonic() + 40
            while not release.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
        """)
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8")
        assert _wait_for(tmp_path / f"{tag}.ready"), proc.communicate(timeout=_CHILD_DEADLINE_S)
        return proc

    def test_a_child_of_the_live_holder_passes_through(self, tmp_path):
        """A nested run (xdist's workers) inherits the holder's pid and runs
        while its parent holds the box. Mutation: the pass-through dropped (a
        deadlock on the parent's own hold); the pair named by ``Popen.pid``
        (a Windows venv's redirector, which no record names)."""
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        holder = self._holder(tmp_path, lock, None)
        child = _spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp="c", holder=str(_said_pid(tmp_path / "h.ready"))))
        out, err = _finish(child)
        assert holder.poll() is None, "the holder had already released when the child finished"
        assert "box lock: waiting" not in err and "box lock: inside the holder" in out, out
        _release(tmp_path, "h")
        holder.wait(timeout=_CHILD_DEADLINE_S)
        # DEF-4053: the run that passed through leaves its line, naming the holder.
        lines = [json.loads(ln) for ln in (tmp_path / "box.lock.log").read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert [(ln["outcome"], ln["holder"]["pid"]) for ln in lines] == [("inside", _said_pid(tmp_path / "h.ready"))], lines

    def test_a_dead_holders_pid_in_the_pair_is_no_pass(self, tmp_path):
        """Mutation: the pass-through taken on the variable alone (a forged or
        stale holder pid lets a run past a live hold)."""
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        holder = self._holder(tmp_path, lock, dead.pid)
        waiter = _Waiter(tmp_path, tree, _child_env(tmp_path, lock, stamp="c", holder=str(dead.pid), slow=True))
        assert waiter.at_the_lock(), f"the child ran past a live hold: {waiter.stderr}"
        assert waiter.child.poll() is None and not (tmp_path / "c").exists(), "the child ran past a live hold"
        _release(tmp_path, "h")
        out, err = waiter.finish()
        holder.wait(timeout=_CHILD_DEADLINE_S)
        assert "box lock: waiting on" in err, err

    def test_an_empty_record_under_a_held_lock_is_said_and_still_waited_on(self, tmp_path):
        """A holder that died between the lock and its record, or a record a
        reader caught mid-write, is "no holder record" on the line and never a
        pass. Mutation: an unreadable record read as nobody holding."""
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        code = textwrap.dedent(f"""
            import sys, time
            from pathlib import Path
            sys.path.insert(0, {str(REPO_ROOT / 'tools' / 'cc')!r})
            from _json_safe import try_lock_file
            fh = open({str(lock)!r}, "a+", encoding="utf-8"); assert try_lock_file(fh)
            Path({str(tmp_path / 'e.ready')!r}).write_text("1")
            release = Path({str(tmp_path / 'e.release')!r}); deadline = time.monotonic() + 40
            while not release.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
        """)
        holder = subprocess.Popen([sys.executable, "-c", code])
        assert _wait_for(tmp_path / "e.ready")
        waiter = _Waiter(tmp_path, tree, _child_env(tmp_path, lock, stamp="c", slow=True))
        assert waiter.at_the_lock(), waiter.stderr
        assert waiter.child.poll() is None
        _release(tmp_path, "e")
        out, err = waiter.finish()
        holder.wait(timeout=_CHILD_DEADLINE_S)
        assert "no holder record" in err, err

    def test_a_record_that_is_not_utf8_is_no_record(self, tmp_path):
        """Mutation: a decode error escaping ``read_record`` (code review,
        2026-10-26: the first cut caught OSError alone, so a holder record in
        another encoding made the run go unguarded without waiting)."""
        bl = _box_lock()
        path = tmp_path / "box.lock"
        path.write_bytes(b"\xff\xfe\x00\x01")
        assert bl.read_record(path) is None
        path.write_text("[1, 2]", encoding="utf-8")
        assert bl.read_record(path) is None


def _log_lines(tmp_path: Path) -> list[dict]:
    log = tmp_path / "box.lock.log"
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()] if log.exists() else []


class TestTheBoxsSlots:
    """DEF-2105, the shape the review in air's 8dda84 fixed: a box may hold more
    than one tier, its count one number in a file beside the lock, a parallel
    line one slot, a serial line every slot, the inherited pair read before any
    slot, and the slot on every log line. The kernel's part (two runs holding
    two slots at once, a serial run behind a parallel one with a slot free, a
    nested run on slot 2) drives real children as the cases above do; what the
    hold does with the slots it reads is driven in-process, with the test
    holding the other slots on handles of its own."""

    @staticmethod
    def _slots(tmp_path: Path, count: str) -> Path:
        lock = tmp_path / "box.lock"
        (tmp_path / "box.lock.slots").write_text(count, encoding="utf-8")
        return lock

    @staticmethod
    def _hold(path: Path, record: dict | None) -> IO[str]:
        """A slot held by this test process on a handle of its own, its record
        written; the caller closes the handle to free it."""
        fh = open(path, "a+", encoding="utf-8")
        assert _box_lock()._primitive().try_lock_file(fh), path
        fh.seek(0)
        fh.truncate()
        if record is not None:
            fh.write(json.dumps(record))
        fh.flush()
        return fh

    @staticmethod
    def _lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, every: bool) -> object:
        import io
        bl = _box_lock()
        monkeypatch.setenv(bl.HOLDER_KEY, os.environ.get(bl.HOLDER_KEY, "0"))
        monkeypatch.setattr(bl, "POLL_S", 0.05)
        record = {"seat": "s", "lane": "l", "checkout": str(tmp_path), "pid": os.getpid(), "argv": ["pytest"]}
        return bl.BoxLock(tmp_path / "box.lock", record, bl._primitive(), stream=io.StringIO(), every=every)

    def test_the_count_is_one_number_in_the_file_beside_the_lock(self, tmp_path):
        """Absent, one slot (the lock itself), as every box ran before; a whole
        number from 1 to the cap names that many; anything else is one slot,
        said. Mutation: an absent file read as no slot or as the cap; a value
        past the cap clamped to it (a typo would put that many tiers on a box);
        a non-ASCII digit read as a number; the note left off."""
        prim = _box_lock()._primitive()
        lock = str(tmp_path / "box.lock")
        assert prim.box_lock_slots(lock) == ([lock], "")
        side = tmp_path / "box.lock.slots"
        for body, count in (("2", 2), ("3\n", 3), (f" {prim.BOX_LOCK_MAX_SLOTS} ", prim.BOX_LOCK_MAX_SLOTS), ("1", 1)):
            side.write_text(body, encoding="utf-8")
            paths, note = prim.box_lock_slots(lock)
            assert paths == [lock, *(f"{lock}.slot{k}" for k in range(2, count + 1))] and note == "", (body, paths, note)
        for body in ("0", str(prim.BOX_LOCK_MAX_SLOTS + 1), "-2", "two", "", "２"):
            side.write_text(body, encoding="utf-8")
            paths, note = prim.box_lock_slots(lock)
            assert paths == [lock] and "not a slot count" in note and note.isascii(), (body, paths, note)
        side.write_bytes(b"\xff\xfe\x00")
        paths, note = prim.box_lock_slots(lock)
        assert paths == [lock] and "could not be read" in note, note
        # Windows PowerShell 5.1 writes UTF-16 (`echo 2 > f`) or a BOM
        # (`Set-Content -Encoding UTF8`): both reviews read them as one slot.
        for raw in ("2\r\n".encode("utf-16"), b"\xef\xbb\xbf2"):
            side.write_bytes(raw)
            assert prim.box_lock_slots(lock) == ([lock, f"{lock}.slot2"], ""), raw

    def test_a_serial_line_is_xdist_at_one_worker(self):
        """Mutation: a serial line read from the argv, or ``auto`` read as one."""
        bl = _box_lock()
        for value, every in ((1, True), ("1", True), (2, False), ("auto", False), (None, False), (0, False)):
            cfg = types.SimpleNamespace(option=types.SimpleNamespace(numprocesses=value))
            assert bl.takes_every_slot(cfg) is every, value
        assert bl.takes_every_slot(types.SimpleNamespace()) is False

    def test_two_parallel_runs_hold_one_slot_each_at_once(self, tmp_path):
        """At a count of 2 a second parallel line runs while the first holds,
        and each names its slot and the count on its line. Mutation: the count
        file not read (the second waits behind the first); a parallel line
        taking every slot; the slot or the count left off the log line."""
        tree, lock = _scratch(tmp_path), self._slots(tmp_path, "2")
        first = _holding(tmp_path, tree, lock, workers="2")
        second = _spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp="b"), workers="2")
        ran_beside = _wait_for(tmp_path / "b.done", timeout=30)
        _release(tmp_path, "a")
        out, err = _finish(second)
        _finish(first)
        assert ran_beside, f"the second run did not finish while the first held: {out}\n{err}"
        assert _stamp(tmp_path, "b.done") < _stamp(tmp_path, "a.done"), "the second ran after the first, not beside it"
        assert "box lock: wait" not in err + out, (out, err)
        taken = [(ln["outcome"], ln["run"]["pid"], ln["slot"], ln["slots"]) for ln in _log_lines(tmp_path)
                 if ln["outcome"] == "taken"]
        assert taken == [("taken", _said_pid(tmp_path / "a.pid"), 1, 2), ("taken", _said_pid(tmp_path / "b.pid"), 2, 2)], taken

    def test_a_serial_run_waits_for_every_slot_though_one_is_free(self, tmp_path):
        """At a count of 2, with a parallel line on slot 1 and slot 2 free, a
        serial line waits for the whole box and runs after (DEF-4062's shape:
        a one-worker leg beside another seat's pool). Mutation: a serial line
        taking one slot (it runs at once on slot 2); its line's slot not
        ``every``."""
        tree, lock = _scratch(tmp_path), self._slots(tmp_path, "2")
        first = _holding(tmp_path, tree, lock, workers="2")
        serial = _Waiter(tmp_path, tree, _child_env(tmp_path, lock, stamp="s", slow=True))
        assert serial.at_the_lock(), serial.stderr
        assert serial.child.poll() is None and not (tmp_path / "s").exists(), "the serial run ran beside a parallel one"
        _release(tmp_path, "a")
        _out, err = serial.finish()
        _finish(first)
        assert _stamp(tmp_path, "s") >= _stamp(tmp_path, "a.done"), err
        waited = [ln for ln in _log_lines(tmp_path) if ln["outcome"] in ("waited", "released")
                  and ln["run"]["pid"] == _said_pid(tmp_path / "s.pid")]
        assert [(ln["outcome"], ln["slot"], ln["slots"]) for ln in waited] == [
            ("waited", "every", 2), ("released", "every", 2)], waited
        assert waited[0]["holder"]["pid"] == _said_pid(tmp_path / "a.pid"), waited

    @pytest.mark.parametrize("workers", ["1", "2"], ids=["serial-child", "parallel-child"])
    def test_a_nested_run_passes_through_its_parents_slot_and_takes_none(self, tmp_path, workers):
        """8dda84's second blocker: a nested run tried a slot before its
        inherited pair, so with its parent on slot 2 it took slot 1 (or, a
        serial child, waited on its own parent). The pair is read over every
        slot first. Mutation: the pair read after the first try, or over slot
        1 alone."""
        tree, lock = _scratch(tmp_path), self._slots(tmp_path, "2")
        holder = TestTheInheritedPair._holder(tmp_path, tmp_path / "box.lock.slot2", None)
        parent = _said_pid(tmp_path / "h.ready")
        child = _spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp="c", holder=str(parent)), workers=workers)
        out, err = _finish(child)
        assert holder.poll() is None, "the holder had already released when the child finished"
        _release(tmp_path, "h")
        holder.wait(timeout=_CHILD_DEADLINE_S)
        assert "box lock: inside the holder" in out and "box lock: wait" not in err, (out, err)
        assert [(ln["outcome"], ln["holder"]["pid"], ln["slot"]) for ln in _log_lines(tmp_path)] == [
            ("inside", parent, 2)], _log_lines(tmp_path)

    def test_a_parallel_line_waits_behind_a_serial_line_taking_the_box(self, tmp_path, monkeypatch):
        """A serial line holding slot 1 while it waits for slot 2 is in the
        way of a parallel line, though slot 3 is free: a parallel line taking
        it would starve the serial one. A parallel record on slot 1 is no such
        line (the control). Mutation: the serial record not read at slot 1
        (the parallel line takes slot 3)."""
        bl = _box_lock()
        self._slots(tmp_path, "3")
        monkeypatch.setenv(bl.WAIT_KEY, "0")
        serial = {"seat": "x", "lane": "lane/serial", "pid": os.getpid(), "slot": "every", "draining": True,
                  "started": "2026-11-18T00:00:00+00:00", "argv": ["pytest"]}
        # A pid of its own: the line names each holder's pid once.
        held = [self._hold(tmp_path / "box.lock", serial),
                self._hold(tmp_path / "box.lock.slot2", {"seat": "y", "lane": "l", "pid": 424242, "slot": 2})]
        try:
            lock = self._lock(tmp_path, monkeypatch, every=False)
            with pytest.raises(pytest.exit.Exception):
                lock.acquire()
            said = lock.stream.getvalue()
            assert [ln["outcome"] for ln in _log_lines(tmp_path)] == ["gave_up"], _log_lines(tmp_path)
            assert "x lane/serial (pid" in said and "taking every slot" in said, said
            # The serial line itself is never handed the ceiling; behind it, the
            # holder of the slot it waits for is named too.
            serial_line = next(ln for ln in said.splitlines() if "x lane/serial (pid" in ln)
            assert " -- " not in serial_line and "waiting on y l (pid" in said, said
            held[0].seek(0)
            held[0].truncate()
            held[0].write(json.dumps({**serial, "slot": 1, "draining": False}))
            held[0].flush()
            control = self._lock(tmp_path, monkeypatch, every=False)
            control.acquire()
            assert control.taken == [3] and control.held, control.taken
            control.release()
        finally:
            for fh in held:
                fh.close()
        assert [(ln["outcome"], ln["slot"]) for ln in _log_lines(tmp_path)][1:] == [("taken", 3), ("released", 3)]

    def test_a_serial_line_holds_what_it_takes_and_says_it_waits_for_the_rest(self, tmp_path, monkeypatch):
        """A serial line takes slot 1 at once and keeps it, its record saying
        it is taking every slot, while slot 2's holder runs; at slot 2's
        release it holds both and its record names every slot in each.
        Mutation: a serial line that takes nothing until every slot is free
        (parallel lines keep slot 1 and it starves), or one whose record does
        not say so (a parallel line takes slot 3 beside it)."""
        bl = _box_lock()
        self._slots(tmp_path, "2")
        monkeypatch.delenv(bl.WAIT_KEY, raising=False)
        other = self._hold(tmp_path / "box.lock.slot2", {"seat": "y", "lane": "l", "pid": os.getpid(), "slot": 2})
        lock = self._lock(tmp_path, monkeypatch, every=True)
        worker = threading.Thread(target=lock.acquire, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 20
            record = None
            while time.monotonic() < deadline:
                record = bl.read_record(tmp_path / "box.lock")
                if record:
                    break
                time.sleep(0.02)
            assert record and record.get("draining") and record.get("slot") == "every", record
            with open(tmp_path / "box.lock", "a+", encoding="utf-8") as probe:
                assert bl._primitive().try_lock_file(probe) is False, "slot 1 was not kept while slot 2 was waited on"
        finally:
            other.close()
        worker.join(timeout=20)
        assert lock.held and lock.taken == [1, 2], lock.taken
        for slot in ("box.lock", "box.lock.slot2"):
            record = bl.read_record(tmp_path / slot)
            assert record and record["slot"] == "every" and "draining" not in record, (slot, record)
        lock.release()
        assert [(ln["outcome"], ln["slot"], ln["slots"]) for ln in _log_lines(tmp_path)] == [
            ("waited", "every", 2), ("released", "every", 2)], _log_lines(tmp_path)

    def test_a_serial_line_that_gives_up_clears_and_frees_what_it_took(self, tmp_path, monkeypatch):
        """Past its bound a serial line holding slot 1 of 2 leaves it empty and
        free, and logs no release (it never held the box). Mutation: the
        part-hold kept past the give-up, or its draining record left behind
        for the next reader to read as a holder."""
        bl = _box_lock()
        self._slots(tmp_path, "2")
        monkeypatch.setenv(bl.WAIT_KEY, "0.3")
        other = self._hold(tmp_path / "box.lock.slot2", {"seat": "y", "lane": "l", "pid": os.getpid(), "slot": 2})
        try:
            lock = self._lock(tmp_path, monkeypatch, every=True)
            with pytest.raises(pytest.exit.Exception):
                lock.acquire()
            assert bl.read_record(tmp_path / "box.lock") is None and lock.fh is None and not lock.taken
            with open(tmp_path / "box.lock", "a+", encoding="utf-8") as probe:
                assert bl._primitive().try_lock_file(probe) is True
                bl._primitive().unlock_file(probe)
        finally:
            other.close()
        assert [ln["outcome"] for ln in _log_lines(tmp_path)] == ["gave_up"], _log_lines(tmp_path)

    @pytest.mark.parametrize("record", [None, {"seat": "old", "lane": "l", "pid": os.getpid(), "argv": ["pytest"]}],
                             ids=["mid-write", "older-checkout"])
    def test_slot_one_stops_a_parallel_line_unless_it_holds_a_parallel_record(self, tmp_path, monkeypatch, record):
        """An older checkout's record (no slot: it locks the lock file alone,
        whatever the count, so its serial leg would run beside the slot this
        line takes), or a record caught between another line's take and its
        write, stops a parallel line at slot 1 (both reviews). Mutation: only
        a serial record read as a stop."""
        bl = _box_lock()
        self._slots(tmp_path, "2")
        monkeypatch.setenv(bl.WAIT_KEY, "0")
        held = self._hold(tmp_path / "box.lock", record)
        try:
            lock = self._lock(tmp_path, monkeypatch, every=False)
            with pytest.raises(pytest.exit.Exception):
                lock.acquire()
        finally:
            held.close()
        assert [ln["outcome"] for ln in _log_lines(tmp_path)] == ["gave_up"], _log_lines(tmp_path)

    def test_a_serial_line_stops_at_its_first_refused_slot(self, tmp_path, monkeypatch):
        """With slot 1 held by another serial line taking the box and slot 2
        free, a serial line takes nothing: taking slot 2 out of order, the two
        would each hold half the box and wait on each other (the code review's
        surviving mutant). Mutation: a refused slot skipped and the next one
        tried."""
        self._slots(tmp_path, "2")
        first = {"seat": "x", "lane": "l", "pid": os.getpid(), "slot": "every", "draining": True}
        held = self._hold(tmp_path / "box.lock", first)
        lock = self._lock(tmp_path, monkeypatch, every=True)
        lock.slot_paths = [tmp_path / "box.lock", tmp_path / "box.lock.slot2"]
        lock.handles = {n: open(p, "a+", encoding="utf-8") for n, p in enumerate(lock.slot_paths, 1)}
        try:
            done, _refused = lock._try_take()
            assert not done and lock.taken == [], lock.taken
        finally:
            lock.release()
            held.close()

    def test_a_lowered_count_still_passes_a_nested_run_through(self, tmp_path, monkeypatch):
        """A parent took slot 2, then the count was written down to 1 (or read
        mid-write as one): its nested run still finds it and passes through
        (the failure-mode review). Mutation: the pair read over the count's
        slots alone (the child takes slot 1 beside its own parent)."""
        bl = _box_lock()
        self._slots(tmp_path, "1")
        parent = self._hold(tmp_path / "box.lock.slot2", {"seat": "p", "lane": "l", "pid": os.getpid(), "slot": 2})
        try:
            lock = self._lock(tmp_path, monkeypatch, every=False)
            monkeypatch.setenv(bl.HOLDER_KEY, str(os.getpid()))
            lock.acquire()
            assert lock.passed_through and not lock.taken and lock.fh is None
        finally:
            parent.close()
        assert [(ln["outcome"], ln["slot"], ln["slots"]) for ln in _log_lines(tmp_path)] == [("inside", 2, 1)]


class TestTheWaitingLine:
    def test_past_the_ceiling_the_line_names_the_holder_with_its_commands(self):
        """The ceiling is the holder's own age, never this waiter's wait: an
        unfair lock can keep one waiter past an hour behind a run of healthy
        holders. Mutation: the commands keyed on the wait, left off, or printed
        before the ceiling; the pid interpolated without coercion."""
        from datetime import datetime, timedelta, timezone
        bl = _box_lock()
        pid = os.getpid()  # a live holder: a dead pid gets no command at all (below)
        recent = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat(timespec="seconds")
        record = {"pid": pid, "seat": "win-2", "lane": "lane/x", "started": recent, "argv": ["/v/bin/pytest", "-n", "4"]}

        def unread(_record):
            raise AssertionError("the seat is read before the ceiling")

        short = bl.waiting_line(record, waited_s=bl.WAIT_CEILING_MIN * 60 + 1, read_seat=unread)
        assert short.startswith(f"box lock: waiting on win-2 lane/x (pid {pid}, held ") and ": pytest -n 4" in short, short
        assert "ends with" not in short, "a long wait behind a young holder must not name the stop command"
        old = (datetime.now(timezone.utc) - timedelta(minutes=bl.WAIT_CEILING_MIN + 1)).isoformat(timespec="seconds")
        long = bl.waiting_line({**record, "started": old}, waited_s=5.0, read_seat=lambda _r: False)
        assert f"kill -9 {pid}" in long or f"taskkill /T /F /PID {pid}" in long, long
        assert "inspect it with" in long and "no live Claude Code session" in long and long.isascii()
        forged = bl.waiting_line({**record, "pid": f"{pid}; rm", "started": old}, waited_s=5.0, read_seat=lambda _r: False)
        assert "ends with" not in forged and "pid ?" in forged

    def test_past_the_ceiling_a_seat_with_a_session_or_an_unread_one_is_asked_never_handed_the_kill(self):
        """DEF-4077: past sixty minutes is the ordinary case for a seat's tier
        on a loaded box, and a window once ended a live seat's leg by pid. The
        stop command goes only to a checkout with no live session; a live one,
        an unread one and a line built with no reader (the row's probe) name
        the mail instead. Mutation: the kill printed whatever the seat's
        answer, or for an unread one."""
        from datetime import datetime, timedelta, timezone
        bl = _box_lock()
        old = (datetime.now(timezone.utc) - timedelta(minutes=bl.WAIT_CEILING_MIN + 1)).isoformat(timespec="seconds")
        record = {"pid": os.getpid(), "seat": "air-work", "lane": "lane/x", "started": old}
        asked = []
        for read_seat, why in ((lambda r: asked.append(r) or True, "its seat has a live session"),
                               (lambda r: None, "could not be read"), (None, "could not be read")):
            line = bl.waiting_line(record, waited_s=5.0, read_seat=read_seat)
            assert why in line and "ask air-work on the mail" in line and "mail.py send --type request" in line, line
            assert "kill -9" not in line and "taskkill" not in line and "ends with" not in line, line
        assert asked == [record], "the reader is handed the holder's record"

        def unread(_record):
            raise AssertionError("an unnamed seat's checkout is read")

        for seat in ("?", "", None):
            # A fresh-clone gate leg or a scratch clone's run names no seat,
            # and its checkout holds no session of its own (both reviews).
            line = bl.waiting_line({**record, "seat": seat}, waited_s=5.0, read_seat=unread)
            assert "names no seat" in line and "read its parents" in line, line
            assert "kill -9" not in line and "taskkill" not in line, line

    def test_a_dead_holders_pid_gets_no_command_and_its_seat_is_never_read(self):
        """A record whose pid has exited does not name the lock's holder (the
        lock goes with the process that took it): there is nothing to end by
        it, and a pid reused since would be a stranger. Mutation: the dead pid
        handed the stop command, as the line's old text did."""
        from datetime import datetime, timedelta, timezone
        bl = _box_lock()
        child = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True,
                               encoding="utf-8")
        dead = int(child.stdout.strip())
        assert not bl.holder_alive(dead)
        old = (datetime.now(timezone.utc) - timedelta(minutes=bl.WAIT_CEILING_MIN + 1)).isoformat(timespec="seconds")

        def unread(_record):
            raise AssertionError("a dead pid's seat is read")

        line = bl.waiting_line({"pid": dead, "seat": "win-2", "started": old}, waited_s=5.0, read_seat=unread)
        assert f"pid {dead} has exited" in line and "find the real one" in line, line
        assert "kill -9" not in line and "taskkill" not in line, line

    def test_the_line_is_ascii_and_names_an_unreadable_record(self):
        bl = _box_lock()
        line = bl.waiting_line({}, waited_s=5.0)
        assert "no holder record" in line and line.isascii()


class TestTheHoldersSeat:
    def test_the_reader_counts_the_sessions_in_the_holders_checkout(self, tmp_path):
        """DEF-4077's one reader: ``checkout_sync.sessions_in`` over Claude
        Code's registry (planted here, its entry's pid this live process), run
        in a child so ``tools/cc`` never joins this run's path. A session
        inside the checkout is live; one in another folder is not. Mutation:
        the checkout ignored (every session counted), the count read as live
        at zero."""
        bl = _box_lock()
        checkout, elsewhere = tmp_path / "seat", tmp_path / "other"
        (checkout / "sub").mkdir(parents=True)
        elsewhere.mkdir()
        config = tmp_path / "claude"
        (config / "sessions").mkdir(parents=True)
        entry = config / "sessions" / f"{os.getpid()}.json"
        entry.write_text(json.dumps({"pid": os.getpid(), "sessionId": "s1", "cwd": str(checkout / "sub")}), encoding="utf-8")
        path_before, modules_before = list(sys.path), set(sys.modules)
        assert bl.holder_seat_live({"checkout": str(checkout)}, config_dir=config) is True
        bare = {name for name in set(sys.modules) - modules_before
                if "/tools/cc/" in (getattr(sys.modules[name], "__file__", None) or "").replace("\\", "/")}
        assert sys.path == path_before and bare <= {"_temp_sweep_checkout_sync"}, bare
        entry.write_text(json.dumps({"pid": os.getpid(), "sessionId": "s1", "cwd": str(elsewhere)}), encoding="utf-8")
        assert bl.holder_seat_live({"checkout": str(checkout)}, config_dir=config) is False

    def test_a_record_with_no_checkout_or_a_registry_it_cannot_read_cannot_tell(self, tmp_path):
        """None, never False: an older plugin's record names no checkout, and a
        registry that is not there cannot say no session runs. Mutation: either
        read as False, which would hand a live seat's holder the kill."""
        bl = _box_lock()
        assert bl.holder_seat_live({}) is None
        assert bl.holder_seat_live({"checkout": "?"}) is None
        missing = tmp_path / "no-claude"
        assert bl.holder_seat_live({"checkout": str(tmp_path)}, config_dir=missing) is None


class TestTheWaitersBound:
    def test_past_its_bound_a_waiter_ends_before_any_test_with_its_own_status(self, tmp_path):
        """DEF-4056: under a caller's cap (an agent's Bash call) a waiter
        killed at the cap read as the run's verdict. With the bound set it ends
        itself before any test: ``DID_NOT_RUN_EXIT``, a did-not-run line, a
        ``gave_up`` log line. Mutation: the bound not read; the exit swallowed
        by configure's ``except Exception`` (the run proceeds unguarded and its
        test runs)."""
        bl = _box_lock()
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        first = _holding(tmp_path, tree, lock)
        env = _child_env(tmp_path, lock, stamp="b")
        env[bl.WAIT_KEY] = "1"
        out, err = _finish(_spawn(tmp_path, tree, env), rc=bl.DID_NOT_RUN_EXIT)
        _release(tmp_path, "a")
        _finish(first)
        holder_pid = _said_pid(tmp_path / "a.pid")
        assert "box lock: did not run: waited" in err and f"pid {holder_pid}" in err and "no test ran" in err, err
        assert not (tmp_path / "b").exists() and "passed" not in out, out
        lines = [json.loads(ln) for ln in (tmp_path / "box.lock.log").read_text(encoding="utf-8").splitlines() if ln.strip()]
        gave_up = [ln for ln in lines if ln["outcome"] == "gave_up"]
        assert len(gave_up) == 1 and gave_up[0]["run"]["pid"] == _said_pid(tmp_path / "b.pid"), lines
        assert gave_up[0]["holder"]["pid"] == holder_pid and gave_up[0]["waited_s"] >= 1, gave_up
        assert gave_up[0]["why"] == f"{bl.WAIT_KEY}=1"

    def test_the_bound_reads_seconds_and_a_value_that_is_not_one_is_said_and_unbounded(self):
        """Unset or blank is unbounded, as before the bound; a finite number at
        or above 0 is the bound; anything else is said, never a run that ends
        at once on a typo. Mutation: a bad value read as 0, or read silently."""
        import io
        bl = _box_lock()
        for raw, want in ((None, None), ("", None), ("  ", None), ("0", 0.0), ("90", 90.0), ("2.5", 2.5)):
            stream = io.StringIO()
            assert bl.wait_bound(raw, stream=stream) == want and stream.getvalue() == "", raw
        for raw in ("ten", "-1", "nan", "inf"):
            stream = io.StringIO()
            assert bl.wait_bound(raw, stream=stream) is None, raw
            assert f"{bl.WAIT_KEY}={raw} is not a number of seconds" in stream.getvalue(), raw


class TestTheHoldersStart:
    def test_a_run_that_queued_is_stamped_at_the_lock_and_names_its_checkout(self, tmp_path):
        """DEF-4077: stamped at configure, a run that queued behind another
        seat's tier read as that much older, and past the ceiling sooner. The
        waiter here queues past two seconds after its waiting line; the record
        it writes once it holds is stamped no earlier than the second its
        holder let go. Mutation: the start kept from configure."""
        from datetime import datetime, timezone
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        first = _holding(tmp_path, tree, lock)
        second = _Waiter(tmp_path, tree, _child_env(tmp_path, lock, stamp="b", hold=True, slow=True))
        assert second.at_the_lock(), second.stderr
        time.sleep(2.5)  # lengthens the queue only: the holder keeps the lock all along
        _release(tmp_path, "a")
        _finish(first)
        assert _wait_for(tmp_path / "b"), second.stderr
        record = json.loads(lock.read_text(encoding="utf-8"))
        _release(tmp_path, "b")
        second.finish()
        # The holder's own stamp, written once it was let go and before its
        # lock went: the waiter's hold began after it.
        let_go = int(_stamp(tmp_path, "a.done"))
        started = datetime.fromisoformat(record["started"].replace("Z", "+00:00"))
        assert started >= datetime.fromtimestamp(let_go, tz=timezone.utc), (record, let_go)
        assert record["pid"] == _said_pid(tmp_path / "b.pid") and "checkout" in record, record


class TestTheSummaryNamesAnUnguardedRun:
    def test_a_lock_path_that_cannot_be_opened_is_one_line_and_an_unguarded_summary(self, tmp_path):
        """A lock that cannot be taken must not cost a seat its tier, and the
        one stderr line at configure scrolls off a 30-minute run: the terminal
        summary says it too (failure-mode review, 2026-10-26). Mutation: the
        summary plugin not registered on failure."""
        tree = _scratch(tmp_path)
        missing = tmp_path / "no" / "such" / "dir" / "box.lock"
        out, err = _finish(_spawn(tmp_path, tree, _child_env(tmp_path, missing, stamp="u")))
        assert "box lock: not taken (FileNotFoundError" in err, err
        assert "box lock: unguarded (FileNotFoundError" in out, out
        assert (tmp_path / "u.done").exists()

    def test_an_unguarded_run_leaves_its_line_with_the_reason(self, tmp_path):
        """DEF-4053: a gated run the lock could not be taken for is in the
        log too, with why, so an empty log means no gated run came. Here the
        lock's path is a folder, which opens for no one. Mutation: the
        unguarded run left out of the log."""
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        lock.mkdir()
        out, err = _finish(_spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp="g")))
        assert "box lock: unguarded (" in out, out
        lines = [json.loads(ln) for ln in (tmp_path / "box.lock.log").read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert [ln["outcome"] for ln in lines] == ["unguarded"], lines
        assert lines[0]["run"]["pid"] == _said_pid(tmp_path / "g.pid") and lines[0]["why"].split(":")[0] in err, (lines, err)


class TestTheLaunchersOldDefaultIsReadAsItsNewOne:
    def test_the_old_temp_path_alone_is_read_as_the_home_default_and_said(self, tmp_path, monkeypatch):
        """DEF-4053's failure-mode review: a seat launched before the move
        keeps the temp directory's path in its environment for days (a /clear
        keeps the process), while a relaunched sibling locks the home file,
        two files on one box. The plugin reads that one path as the new
        default and says so; any other path is the operator's own. Mutation:
        no alias, or an alias of every path with the lock's name."""
        bl = _box_lock()
        monkeypatch.setattr(bl.tempfile, "gettempdir", lambda: str(tmp_path / "temp"))
        monkeypatch.setattr(bl.Path, "home", staticmethod(lambda: tmp_path / "home"))
        new = str(tmp_path / "home" / ".espalier" / "espalier-box.lock")
        said: list[str] = []
        stream = types.SimpleNamespace(write=said.append, flush=lambda: None)
        assert bl.current_path(str(tmp_path / "temp" / "espalier-box.lock"), stream=stream) == new
        assert "is the launcher's old default; this run locks" in "".join(said), said
        said.clear()
        own = str(tmp_path / "shared" / "espalier-box.lock")
        assert bl.current_path(own, stream=stream) == own and said == []

    def test_the_plugins_home_default_is_the_launchers(self):
        """The plugin mirrors ``seat.box_lock_default``'s rule (it cannot load
        the driver, whose imports reach the mail channel). Dies to: one rule
        changed without the other."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("_seat_for_box_lock", REPO_ROOT / "tools" / "cc" / "seat.py")
        seat = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = seat
        spec.loader.exec_module(seat)
        assert _box_lock().home_default() == seat.box_lock_default()

    def test_the_banner_reads_a_lock_path_as_the_plugin_opens_it(self, tmp_path, monkeypatch):
        """DEF-2106's failure-mode review: the banner's
        ``session_start._same_lock`` says a set path is the box's file
        exactly where the plugin, after ``current_path``, opens the box's
        file, so a change to either rule (the old default's alias dropped,
        ``~`` expanded) reds here rather than as a seat's silence or a false
        note. Dies to: either rule edited alone."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_session_start_for_box_lock", REPO_ROOT / "tools" / "cc" / "hooks" / "session_start.py")
        banner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(banner)
        bl = _box_lock()
        monkeypatch.setattr(bl.tempfile, "gettempdir", lambda: str(tmp_path / "temp"))
        monkeypatch.setattr(bl.Path, "home", staticmethod(lambda: tmp_path / "home"))
        # `expanduser` reads the variables, not `Path.home`: point them at the
        # same home, so the `~` row tells an expanding rule from one that does not.
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
        box = bl.home_default()
        assert box == str(tmp_path / "home" / ".espalier" / "espalier-box.lock")
        assert os.path.normcase(os.path.abspath(os.path.expanduser("~/.espalier/espalier-box.lock"))) == (
            os.path.normcase(box)), "the `~` row would not tell the two rules apart"
        spellings = [box, os.path.join(os.path.dirname(box), ".", os.path.basename(box)),
                     str(tmp_path / "temp" / "espalier-box.lock"), str(tmp_path / "shared" / "espalier-box.lock"),
                     str(tmp_path / "home" / ".espalier" / "other.lock"), "~/.espalier/espalier-box.lock",
                     "espalier-box.lock", box + "\r"]
        if os.name == "nt":
            spellings.append(box.swapcase().replace("\\", "/"))
        sink = types.SimpleNamespace(write=lambda _s: None, flush=lambda: None)

        def key(path: str) -> str:
            return os.path.normcase(os.path.abspath(path))

        for held in spellings:
            opens_the_box = key(bl.current_path(held, stream=sink)) == key(box)
            assert banner._same_lock(held, box) == opens_the_box, held
        assert banner._same_lock(spellings[2], box), "the old temp default is the box's, as the plugin reads it"


class TestTheSummaryHooksHonourNoSummary:
    def test_neither_the_locks_line_nor_the_unguarded_line_is_written_where_none_was_asked_for(self, tmp_path):
        """pytest 9.2.0 calls every plugin's terminal-summary hook under
        ``--no-summary`` and leaves the gating to the plugin (9.1.1 never called
        it there): the lock's line and the unguarded line are the summary's,
        written only where one was asked for. Mutation: either hook writing
        before it reads the reporter's ``no_summary``."""
        bl = _box_lock()
        lock = bl.BoxLock(tmp_path / "box.lock", {"seat": "s", "lane": "lane/s", "pid": 1}, None)
        lock.passed_through, lock.holder_seen = True, {"seat": "air", "lane": "lane/x", "pid": 7}
        unguarded = bl._Unguarded("FileNotFoundError: no such lock")
        asked_for_none: list[str] = []
        reporter = types.SimpleNamespace(write_line=asked_for_none.append, no_summary=True)
        lock.pytest_terminal_summary(reporter)
        unguarded.pytest_terminal_summary(reporter)
        assert asked_for_none == [], asked_for_none
        written: list[str] = []
        reporter = types.SimpleNamespace(write_line=written.append, no_summary=False)
        lock.pytest_terminal_summary(reporter)
        unguarded.pytest_terminal_summary(reporter)
        assert written == ["box lock: inside the holder air lane/x (pid 7)",
                           "box lock: unguarded (FileNotFoundError: no such lock)"], written


class TestTheCensusOfPytestSpawners:
    """The one deadlock shape: a child that keeps ``ESPALIER_BOX_LOCK``, loses
    ``ESPALIER_BOX_LOCK_HOLDER`` and loads the suite's conftest. No spawner in
    the tree has it (census 2026-10-26: every test spawner copies the whole
    environment; the release gate's whitelist drops both; the strike's guard
    child strips both by prefix), and this pins that a later one does not
    forget. Mutation: the census rule dropped."""

    def test_the_rule_flags_a_builder_that_names_one_of_the_pair_alone(self):
        bl = _box_lock()
        assert bl.pair_asymmetry('env.pop("ESPALIER_BOX_LOCK_HOLDER", None)') == "ESPALIER_BOX_LOCK_HOLDER"
        assert bl.pair_asymmetry('env.pop("ESPALIER_BOX_LOCK_HOLDER", None)\nenv["ESPALIER_BOX_LOCK"] = p') is None
        assert bl.pair_asymmetry('env = {k: v for k, v in os.environ.items() if k != "ESPALIER_BOX_LOCK"}') == "ESPALIER_BOX_LOCK"
        assert bl.pair_asymmetry('env = {k: v for k, v in os.environ.items() if not k.startswith("ESPALIER_BOX_LOCK")}') is None
        assert bl.pair_asymmetry('env = dict(os.environ)') is None
        assert bl.pair_asymmetry('WHITELIST = ("ESPALIER_BOX_LOCK", "ESPALIER_BOX_LOCK_HOLDER")') is None

    def test_the_rule_reads_the_pair_by_the_plugins_and_the_launchers_constants(self):
        """DEF-2034's second half: a builder that names the key through its
        constant (``LOCK_KEY`` here, ``seat.py``'s ``BOX_LOCK_KEY``) is read as
        naming it, and the wait bound, a third name sharing the prefix, is
        neither of the pair. Mutation: the constants left out of the rule's
        words or its prefix strip."""
        bl = _box_lock()
        assert bl.pair_asymmetry("env[LOCK_KEY] = path") == bl.LOCK_KEY
        assert bl.pair_asymmetry("env[seat.BOX_LOCK_KEY] = path") == bl.LOCK_KEY
        assert bl.pair_asymmetry("env.pop(_box_lock.HOLDER_KEY, None)") == bl.HOLDER_KEY
        assert bl.pair_asymmetry("env[seat.BOX_LOCK_KEY] = path\nenv.pop(HOLDER_KEY, None)") is None
        assert bl.pair_asymmetry("env = {k: v for k, v in os.environ.items() if not k.startswith(bl.LOCK_KEY)}") is None
        assert bl.pair_asymmetry("env = {k: v for k, v in env.items() if not k.startswith(seat.BOX_LOCK_KEY)}") is None
        assert bl.pair_asymmetry("env = {k: v for k, v in env.items() if not k.startswith(HOLDER_KEY)}") == bl.HOLDER_KEY
        assert bl.pair_asymmetry('env["ESPALIER_BOX_LOCK_WAIT_S"] = "60"') is None

    @pytest.mark.contract
    def test_the_census_reads_every_root_of_the_checkout_and_the_key_by_its_constant(self, tmp_path):
        """DEF-2034: a spawner under a root no typed list names, and one that
        names the key by its constant, are each flagged; the walk's own leave-
        outs (the vendored mirror, this file and the plugin) stay out. Planted
        with no ``.git``, so git's view is the plain walk of the planted tree.
        Mutation: the walk narrowed to typed roots; a file skipped unless it
        spells the key's literal."""
        spawn = '\nsubprocess.run([sys.executable, "-m", "pytest", "-q"], env=env)\n'
        planted = {
            # The root half: a typed root list never reached examples/.
            "examples/demo/run_suite.py": 'env = dict(os.environ)\nenv.pop("ESPALIER_BOX_LOCK_HOLDER", None)' + spawn,
            # The key half: under a typed root, but naming the key by constant.
            "tests/drive_by_constant.py": "env = dict(os.environ)\nenv[LOCK_KEY] = scratch_lock" + spawn,
            "tests/keeps_both.py": "env = dict(os.environ)" + spawn,
            "espalier/_vendor/cc/copied.py": 'env.pop("ESPALIER_BOX_LOCK_HOLDER", None)' + spawn,
            "tests/test_box_lock.py": 'env.pop("ESPALIER_BOX_LOCK_HOLDER", None)' + spawn,
            # Left out by its path, never its name: a namesake elsewhere is read.
            "examples/tests/test_box_lock.py": 'env.pop("ESPALIER_BOX_LOCK_HOLDER", None)' + spawn,
        }
        for rel, text in planted.items():
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        assert [line.split(":", 1)[0] for line in _spawner_census(tmp_path)] == [
            "examples/demo/run_suite.py", "examples/tests/test_box_lock.py", "tests/drive_by_constant.py"]

    @pytest.mark.contract
    def test_no_spawner_in_the_tree_names_one_of_the_pair_and_drops_the_other(self):
        flagged = _spawner_census(REPO_ROOT)
        assert not flagged, flagged


#: A file that spawns pytest, as the census reads one: the module form or a
#: bare argv head.
_SPAWNS = re.compile(r'"-m", "pytest"|"pytest",')


def _spawner_census(root: Path) -> list[str]:
    """The census over git's view of ``root``, the whole checkout (a typed list
    of roots missed a spawner under any other, DEF-2034): each ``.py`` file that
    spawns pytest and names one of the pair without the other, by its literal
    or its constant (the rule's own reading), the vendored mirror and the
    plugin's own two files left out."""
    from tests._live_tree import checkout_rglob
    bl = _box_lock()
    flagged = []
    for py in checkout_rglob(root, "*.py", root=root):
        rel = py.relative_to(root).as_posix()
        if rel in ("tests/_box_lock.py", "tests/test_box_lock.py") or rel.startswith("espalier/_vendor/"):
            continue
        text = py.read_text(encoding="utf-8")
        if not _SPAWNS.search(text):
            continue
        dropped = bl.pair_asymmetry(text)
        if dropped:
            flagged.append(f"{rel}: names one of the pair ({dropped}) and not the other")
    return flagged
