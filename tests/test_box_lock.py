"""The box lock: two xdist runs of the suite on one machine never run tests at once.

``tests/_box_lock.py`` takes a kernel lock on the file ``ESPALIER_BOX_LOCK``
names when the run is an xdist run that will run tests, names the holder while
it waits, passes a nested run through on the inherited holder pair, says what
it did in the terminal summary, and leaves a record of every wait. Each case
here drives real pytest children on a scratch test file with the plugin loaded
by ``-p``, the way ``tests/test_file_lock.py`` drives the primitive: what the
kernel does is the question, so only real processes can answer it. A holder
never sleeps for a margin: it waits on a release marker the test writes, so a
loaded box slows a case down and never turns it red. Each docstring names the
mutation the test dies to (tests/CLAUDE.md rule 1).
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
import textwrap
import time
import types
from pathlib import Path

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


def _box_lock():
    from tests import _box_lock
    return _box_lock


def _scratch(tmp_path: Path) -> Path:
    tree = tmp_path / "scratch"
    tree.mkdir(exist_ok=True)
    (tree / "test_probe.py").write_text(_SCRATCH_TEST, encoding="utf-8")
    (tree / "conftest.py").write_text("", encoding="utf-8")
    return tree


def _child_env(tmp_path: Path, lock: Path | None, *, stamp: str, hold: bool = False,
               holder: str | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "ESPALIER_BOX_LOCK", "PYTEST_ADDOPTS", "PYTEST_XDIST"))}
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["BOX_PROBE_STAMP"] = str(tmp_path / stamp)
    if hold:
        env["BOX_PROBE_HOLD"] = str(tmp_path / f"{stamp}.release")
    if lock is not None:
        env["ESPALIER_BOX_LOCK"] = str(lock)
    if holder is not None:
        env["ESPALIER_BOX_LOCK_HOLDER"] = holder
    return env


def _spawn(tmp_path: Path, tree: Path, env: dict[str, str], *extra: str, workers: str | None = "1") -> subprocess.Popen:
    argv = [sys.executable, "-m", "pytest", str(tree / "test_probe.py"), "-q", "-p", "no:cacheprovider",
            "-p", "tests._box_lock", *(["-n", workers] if workers is not None else []), *extra]
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
    out, err = child.communicate(timeout=_CHILD_DEADLINE_S)
    assert child.returncode == rc, f"rc={child.returncode}\n{out}\n{err}"
    return out, err


def _stamp(tmp_path: Path, name: str) -> float:
    return float((tmp_path / name).read_text(encoding="utf-8"))


def _holding(tmp_path: Path, tree: Path, lock: Path, stamp: str = "a") -> subprocess.Popen:
    """A gated run that holds the box until the test releases it."""
    first = _spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp=stamp, hold=True))
    assert _wait_for(tmp_path / stamp), _finish(first)
    return first


class TestTwoRunsOnOneBox:
    def test_the_second_run_waits_names_the_holder_and_runs_after_it(self, tmp_path):
        """Mutation: the non-blocking try replaced by the blocking ``lock_file``
        (the waiter sits silent and never prints the holder); the plugin not
        registered under ``-n`` (both runs' tests overlap)."""
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        first = _holding(tmp_path, tree, lock)
        second = _spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp="b"))
        time.sleep(1.0)
        assert second.poll() is None and not (tmp_path / "b").exists(), "the second run's test ran while the first held the box"
        _release(tmp_path, "a")
        out, err = _finish(second)
        _finish(first)
        assert "box lock: waiting on" in err and f"pid {first.pid}" in err, err
        assert "box lock: waited" in out and f"pid {first.pid}" in out, out
        assert _stamp(tmp_path, "b") >= _stamp(tmp_path, "a.done")

    def test_a_finished_holder_leaves_an_empty_record_and_the_next_run_waits_on_nobody(self, tmp_path):
        """Mutation: the record not truncated at ``pytest_unconfigure``, so the
        next waiter would read a finished run's pid as the holder."""
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        _finish(_spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp="a")))
        assert lock.read_text(encoding="utf-8") == ""
        out, err = _finish(_spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp="b")))
        assert "box lock" not in err and "box lock" not in out

    def test_every_wait_leaves_one_log_line_and_a_run_that_did_not_wait_leaves_none(self, tmp_path):
        """Mutation: the wait log unwritten, or written for a run that never
        waited."""
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        first = _holding(tmp_path, tree, lock)
        second = _spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp="b"))
        time.sleep(0.8)
        _release(tmp_path, "a")
        _finish(second)
        _finish(first)
        lines = [json.loads(ln) for ln in (tmp_path / "box.lock.log").read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 1, lines
        assert lines[0]["holder"]["pid"] == first.pid and lines[0]["waiter"]["pid"] == second.pid
        assert lines[0]["waited_s"] > 0


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
        a selection read as an exemption."""
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        first = _holding(tmp_path, tree, lock)
        slice_ = _spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp="b"), "-m", "contract")
        time.sleep(1.0)
        assert slice_.poll() is None and not (tmp_path / "b").exists()
        _release(tmp_path, "a")
        _finish(slice_)
        _finish(first)
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
        (its own when None), the shape of a parent run's hold; it releases
        when the test writes ``<tag>.release``."""
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
            Path({str(tmp_path / (tag + '.ready'))!r}).write_text("1")
            release = Path({str(tmp_path / (tag + '.release'))!r})
            deadline = time.monotonic() + 40
            while not release.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
        """)
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert _wait_for(tmp_path / f"{tag}.ready"), proc.communicate(timeout=_CHILD_DEADLINE_S)
        return proc

    def test_a_child_of_the_live_holder_passes_through(self, tmp_path):
        """A nested run (xdist's workers) inherits the holder's pid and runs
        while its parent holds the box. Mutation: the pass-through dropped (a
        deadlock on the parent's own hold)."""
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        holder = self._holder(tmp_path, lock, None)
        child = _spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp="c", holder=str(holder.pid)))
        out, err = _finish(child)
        assert holder.poll() is None, "the holder had already released when the child finished"
        assert "box lock: waiting" not in err and "box lock: inside the holder" in out, out
        _release(tmp_path, "h")
        holder.wait(timeout=_CHILD_DEADLINE_S)

    def test_a_dead_holders_pid_in_the_pair_is_no_pass(self, tmp_path):
        """Mutation: the pass-through taken on the variable alone (a forged or
        stale holder pid lets a run past a live hold)."""
        tree, lock = _scratch(tmp_path), tmp_path / "box.lock"
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        holder = self._holder(tmp_path, lock, dead.pid)
        child = _spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp="c", holder=str(dead.pid)))
        time.sleep(1.0)
        assert child.poll() is None and not (tmp_path / "c").exists(), "the child ran past a live hold"
        _release(tmp_path, "h")
        out, err = _finish(child)
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
        child = _spawn(tmp_path, tree, _child_env(tmp_path, lock, stamp="c"))
        time.sleep(1.0)
        assert child.poll() is None
        _release(tmp_path, "e")
        out, err = _finish(child)
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


class TestTheWaitingLine:
    def test_past_the_ceiling_the_line_names_the_holder_with_its_commands(self):
        """The ceiling is the holder's own age, never this waiter's wait: an
        unfair lock can keep one waiter past an hour behind a run of healthy
        holders. Mutation: the commands keyed on the wait, left off, or printed
        before the ceiling; the pid interpolated without coercion."""
        from datetime import datetime, timedelta, timezone
        bl = _box_lock()
        recent = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat(timespec="seconds")
        record = {"pid": 4242, "seat": "win-2", "lane": "lane/x", "started": recent, "argv": ["/v/bin/pytest", "-n", "4"]}
        short = bl.waiting_line(record, waited_s=bl.WAIT_CEILING_MIN * 60 + 1)
        assert short.startswith("box lock: waiting on win-2 lane/x (pid 4242, held ") and ": pytest -n 4" in short, short
        assert "ends with" not in short, "a long wait behind a young holder must not name the stop command"
        old = (datetime.now(timezone.utc) - timedelta(minutes=bl.WAIT_CEILING_MIN + 1)).isoformat(timespec="seconds")
        long = bl.waiting_line({**record, "started": old}, waited_s=5.0)
        assert "4242" in long and ("kill -9 4242" in long or "taskkill /T /F /PID 4242" in long), long
        assert "inspect it with" in long and long.isascii()
        forged = bl.waiting_line({**record, "pid": "4242; rm", "started": old}, waited_s=5.0)
        assert "ends with" not in forged and "pid ?" in forged

    def test_the_line_is_ascii_and_names_an_unreadable_record(self):
        bl = _box_lock()
        line = bl.waiting_line({}, waited_s=5.0)
        assert "no holder record" in line and line.isascii()


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

    def test_no_spawner_in_the_tree_names_one_of_the_pair_and_drops_the_other(self):
        from tests._live_tree import checkout_rglob
        bl = _box_lock()
        spawns = re.compile(r'"-m", "pytest"|"pytest",')
        flagged = []
        for sub in ("tests", "scripts", "tools/cc", "espalier", "bench"):
            for py in checkout_rglob(REPO_ROOT / sub, "*.py"):
                if py.name in ("_box_lock.py", "test_box_lock.py") or "/_vendor/" in py.as_posix():
                    continue
                text = py.read_text(encoding="utf-8")
                if "ESPALIER_BOX_LOCK" not in text or not spawns.search(text):
                    continue
                dropped = bl.pair_asymmetry(text)
                if dropped:
                    flagged.append(f"{py.relative_to(REPO_ROOT).as_posix()}: names one of the pair ({dropped}) and not the other")
        assert not flagged, flagged
