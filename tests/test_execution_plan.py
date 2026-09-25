"""Regression tests for tools/cc/execution_plan.py — index guard and basic flow.

Tests run the real script via subprocess in a temp working directory so they
exercise the CLI surface rather than just the internal function.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "cc" / "execution_plan.py"
PLAN_PATH_REL = "cc/execution_plan.json"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False, encoding="utf-8",
    )


def _create_plan(cwd: Path, steps: int = 3) -> None:
    """Create a plan with N steps in the given working directory."""
    step_list = "|".join(f"step {i}" for i in range(steps))
    result = _run(["create", "--task", "test task", "--steps", step_list], cwd)
    assert result.returncode == 0, f"create failed: {result.stderr}"
    assert (cwd / PLAN_PATH_REL).exists()


class TestNegativeIndexGuard:
    def test_negative_index_exits_nonzero(self, tmp_path):
        _create_plan(tmp_path)
        result = _run(["mark", "-1", "passed"], tmp_path)
        assert result.returncode != 0

    def test_negative_index_stderr_message(self, tmp_path):
        _create_plan(tmp_path)
        result = _run(["mark", "-1", "passed"], tmp_path)
        assert "Invalid step index: -1" in result.stderr

    def test_negative_index_does_not_mutate_plan(self, tmp_path):
        _create_plan(tmp_path)
        plan_path = tmp_path / PLAN_PATH_REL
        before = json.loads(plan_path.read_text(encoding="utf-8"))
        _run(["mark", "-1", "passed"], tmp_path)
        after = json.loads(plan_path.read_text(encoding="utf-8"))
        assert after == before

    def test_valid_positive_index_succeeds(self, tmp_path):
        _create_plan(tmp_path)
        result = _run(["mark", "0", "passed"], tmp_path)
        assert result.returncode == 0
        plan = json.loads((tmp_path / PLAN_PATH_REL).read_text(encoding="utf-8"))
        assert plan["steps"][0]["status"] == "passed"

    def test_index_equal_to_len_fails(self, tmp_path):
        _create_plan(tmp_path, steps=3)
        result = _run(["mark", "3", "passed"], tmp_path)
        assert result.returncode != 0
        assert "Invalid step index: 3" in result.stderr

    def test_index_equal_to_len_does_not_mutate_plan(self, tmp_path):
        _create_plan(tmp_path, steps=3)
        plan_path = tmp_path / PLAN_PATH_REL
        before = json.loads(plan_path.read_text(encoding="utf-8"))
        _run(["mark", "3", "passed"], tmp_path)
        after = json.loads(plan_path.read_text(encoding="utf-8"))
        assert after == before


class TestLoadDecodeGuarded:
    """Ledger DEF-829: a plan file re-saved in a Windows code page."""

    def _load_module(self):
        spec = importlib.util.spec_from_file_location("execution_plan", str(SCRIPT))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_load_reads_a_latin1_plan_instead_of_crashing(self, tmp_path, monkeypatch):
        """``UnicodeDecodeError`` is a ``ValueError``, so ``except OSError``
        let it past ``_load``; the bytes now go to ``load_json_dict_safe``."""
        mod = self._load_module()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        plan_path = tmp_path / "cc" / "execution_plan.json"
        plan_path.parent.mkdir(parents=True)
        plan_path.write_bytes(b'{"task": "caf\xe9", "status": "in_progress", "steps": []}\n')
        plan = mod._load()
        assert plan is not None and plan["status"] == "in_progress"


class TestSaveAtomic:
    """_save must leave the prior plan intact when a torn write occurs."""

    def _load_module(self):
        spec = importlib.util.spec_from_file_location("execution_plan", str(SCRIPT))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_save_atomic_on_replace_failure(self, tmp_path, monkeypatch):
        mod = self._load_module()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

        # Write an initial plan so there is something to protect.
        initial = {"task": "original", "status": "in_progress", "steps": []}
        plan_path = tmp_path / "cc" / "execution_plan.json"
        plan_path.parent.mkdir(parents=True)
        plan_path.write_text(json.dumps(initial) + "\n", encoding="utf-8")

        # Patch os.replace to raise after the tempfile is written.
        original_replace = os.replace

        def _fail_replace(src, dst):
            raise OSError("injected failure")

        monkeypatch.setattr(os, "replace", _fail_replace)

        with pytest.raises(OSError, match="injected failure"):
            mod._save({"task": "new", "status": "in_progress", "steps": []})

        # Original plan must be untouched.
        after = json.loads(plan_path.read_text(encoding="utf-8"))
        assert after == initial

    def test_save_atomic_no_tmpfile_left_on_failure(self, tmp_path, monkeypatch):
        mod = self._load_module()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

        plan_path = tmp_path / "cc" / "execution_plan.json"
        plan_path.parent.mkdir(parents=True)
        plan_path.write_text('{"task":"x","steps":[]}\n', encoding="utf-8")

        monkeypatch.setattr(os, "replace", lambda s, d: (_ for _ in ()).throw(OSError("boom")))

        with pytest.raises(OSError):
            mod._save({"task": "y", "steps": []})

        # No stray .tmp files should remain in cc/.
        tmps = list((tmp_path / "cc").glob("*.tmp"))
        assert tmps == [], f"stray tmp files: {tmps}"


class TestCmdMarkConcurrencyLock:
    """Fix C: ``cmd_mark``'s read-modify-write runs under ``_plan_lock`` so two
    concurrent ``mark`` calls -- e.g. a git-capable subagent sharing the live
    tree ([[subagent-git-access-mutates-shared-tree]]) -- can't lose an update.

    Deliberately NOT a timing race: a wall-clock "both threads load then save"
    test is non-deterministic (it false-greened even with the lock removed,
    the exact [[pack-code-examples-are-claims-test-them]] trap). Instead two
    deterministic tests prove the mechanism: (A) ``_plan_lock`` is a real
    mutex (event-coordinated, no sleeps decide correctness), and (B)
    ``cmd_mark``'s ``_save`` runs strictly *inside* that lock. Both go RED
    against the pre-fix shape (no lock / lock not wrapping the save).
    """

    def _load_module(self):
        spec = importlib.util.spec_from_file_location("execution_plan", str(SCRIPT))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _seed_two_step_plan(self, mod):
        mod._save({
            "task": "race",
            "status": "in_progress",
            "steps": [
                {"index": 0, "description": "s0", "status": "pending", "note": "", "timestamp": ""},
                {"index": 1, "description": "s1", "status": "pending", "note": "", "timestamp": ""},
            ],
        })

    def test_plan_lock_is_a_mutex(self, tmp_path, monkeypatch):
        """Two threads entering ``_plan_lock`` serialize: while thread A holds
        it, thread B blocks at acquire and does not enter the section. Skipped
        without ``fcntl`` (there the lock is a documented best-effort no-op).
        RED with the lock removed: B's critical section interleaves A's."""
        pytest.importorskip("fcntl")
        import threading
        import time

        mod = self._load_module()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

        order = []
        a_holding = threading.Event()
        release_a = threading.Event()
        b_started = threading.Event()

        def worker_a():
            with mod._plan_lock():
                order.append("A-in")
                a_holding.set()
                release_a.wait(timeout=5)
                order.append("A-out")

        def worker_b():
            b_started.set()
            with mod._plan_lock():
                order.append("B-in")
                order.append("B-out")

        ta = threading.Thread(target=worker_a)
        ta.start()
        assert a_holding.wait(timeout=5), "thread A never acquired the lock"
        tb = threading.Thread(target=worker_b)
        tb.start()
        assert b_started.wait(timeout=5)
        # Give B ample time to reach (and, under the lock, block on) acquire.
        time.sleep(0.2)
        # Mutual exclusion: B must NOT have entered while A holds the lock.
        assert "B-in" not in order, f"B entered while A held the lock: {order}"
        release_a.set()
        ta.join(timeout=5)
        tb.join(timeout=5)
        assert order == ["A-in", "A-out", "B-in", "B-out"], order

    def test_cmd_mark_saves_inside_the_lock(self, tmp_path, monkeypatch):
        """``cmd_mark`` must call ``_save`` between ``_plan_lock`` enter and
        exit. RED pre-fix: an un-wrapped ``cmd_mark`` never enters the lock, so
        ``lock-enter`` is absent and the ordering assert fails."""
        from contextlib import contextmanager

        mod = self._load_module()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        self._seed_two_step_plan(mod)

        events = []

        @contextmanager
        def spy_lock():
            events.append("lock-enter")
            try:
                yield
            finally:
                events.append("lock-exit")

        real_save = mod._save

        def spy_save(plan):
            events.append("save")
            return real_save(plan)

        monkeypatch.setattr(mod, "_plan_lock", spy_lock)
        monkeypatch.setattr(mod, "_save", spy_save)

        mod.cmd_mark(0, "passed")

        assert "lock-enter" in events, f"cmd_mark did not enter _plan_lock: {events}"
        assert "save" in events
        assert (
            events.index("lock-enter") < events.index("save") < events.index("lock-exit")
        ), f"_save did not run inside the lock: {events}"

    def test_plan_lock_body_oserror_propagates_not_masked(self, tmp_path, monkeypatch):
        """A body-raised ``OSError`` inside ``_plan_lock`` must propagate AS
        ITSELF, not be masked. RED against the pre-fix shape where the body
        ``yield`` sat inside the acquisition ``except OSError``: there a body
        OSError was thrown into the generator, re-caught, and re-yielded,
        surfacing ``RuntimeError: generator didn't stop after throw()`` and
        burying the real cause. Needs ``fcntl`` — the bug only exists on the
        flock path (the no-fcntl path yields once and never double-yields)."""
        pytest.importorskip("fcntl")
        mod = self._load_module()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

        with pytest.raises(OSError, match="disk full"):
            with mod._plan_lock():
                raise OSError("disk full")

    def test_cmd_mark_surfaces_real_save_failure(self, tmp_path, monkeypatch):
        """End-to-end: when ``_save`` fails mid-``cmd_mark`` (disk full / RO /
        permission), the operator must see the real OSError, not a misleading
        contextlib ``RuntimeError``. RED pre-fix on the flock path."""
        pytest.importorskip("fcntl")
        mod = self._load_module()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        self._seed_two_step_plan(mod)

        def _fail_save(plan):
            raise OSError("No space left on device")

        monkeypatch.setattr(mod, "_save", _fail_save)

        with pytest.raises(OSError, match="No space left on device"):
            mod.cmd_mark(0, "passed")

    def test_plan_lock_no_fcntl_degrade_runs_body_once_and_propagates(
        self, tmp_path, monkeypatch
    ):
        """The no-``fcntl`` (Windows) degrade branch runs the body exactly once
        and lets a body-raised ``OSError`` propagate as itself. Forces the
        ``ImportError`` path via ``builtins.__import__`` so it RUNS on POSIX (no
        ``importorskip``) — every other lock test skips without ``fcntl``,
        leaving this documented Windows posture otherwise uncovered on CI. RED if
        the degrade branch double-yields or ``NameError``s on ``fcntl``."""
        import builtins

        mod = self._load_module()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

        real_import = builtins.__import__

        def _no_fcntl(name, *args, **kwargs):
            if name == "fcntl":
                raise ImportError("simulated: no fcntl on this platform")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_fcntl)

        # (1) body runs exactly once on the degrade path
        runs = 0
        with mod._plan_lock():
            runs += 1
        assert runs == 1, f"degrade path yielded {runs} times, expected 1"

        # (2) a body-raised OSError propagates as itself, not a contextlib
        # RuntimeError from an accidental double-yield
        with pytest.raises(OSError, match="disk full"):
            with mod._plan_lock():
                raise OSError("disk full")


class TestPlanStatusUnsticks:
    """A previously-failed step that's re-marked passed must transition the
    plan's overall status out of "blocked" — otherwise every subsequent
    mark exits 1 even though the operation itself succeeded.

    Pre-fix, ``cmd_mark`` only set status to "complete" (all-passed) or
    "blocked" (any-failed). Missing else clause meant status was sticky
    forever once anything had ever failed.
    """

    def test_mark_fail_then_pass_returns_status_to_in_progress(self, tmp_path):
        _create_plan(tmp_path, steps=3)
        # Step 0 fails, plan goes to "blocked".
        _run(["mark", "0", "failed"], tmp_path)
        plan = json.loads((tmp_path / PLAN_PATH_REL).read_text(encoding="utf-8"))
        assert plan["status"] == "blocked"

        # Step 0 re-marked passed, no other failures, not all passed yet.
        # Status must return to "in_progress".
        _run(["mark", "0", "passed"], tmp_path)
        plan = json.loads((tmp_path / PLAN_PATH_REL).read_text(encoding="utf-8"))
        assert plan["status"] == "in_progress", (
            f"expected status='in_progress' after re-marking sole failed "
            f"step passed; got {plan['status']!r}"
        )

    def test_mark_passed_exits_zero_after_unstick(self, tmp_path):
        """The visible bug: ``mark`` exited 1 every time after a prior
        failure, even when the mark itself succeeded. The unstick fix
        means a successful mark on a no-longer-blocked plan exits 0."""
        _create_plan(tmp_path, steps=3)
        _run(["mark", "0", "failed"], tmp_path)
        # Sanity: blocked → exit 1 on subsequent marks.
        result = _run(["mark", "1", "passed"], tmp_path)
        assert result.returncode == 1, "blocked plan: mark should still exit 1"
        # Unstick: re-mark the failed step, then mark another step. Both
        # the unstick mark AND the subsequent mark must exit 0.
        result = _run(["mark", "0", "passed"], tmp_path)
        assert result.returncode == 0, (
            f"unstick mark should exit 0; got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        result = _run(["mark", "2", "running"], tmp_path)
        assert result.returncode == 0, (
            f"mark on unstuck plan should exit 0; got {result.returncode}"
        )

    def test_all_passed_still_reaches_complete(self, tmp_path):
        """The else clause must not interfere with the all-passed → complete
        transition (the only other path that exits 0)."""
        _create_plan(tmp_path, steps=2)
        _run(["mark", "0", "passed"], tmp_path)
        _run(["mark", "1", "passed"], tmp_path)
        plan = json.loads((tmp_path / PLAN_PATH_REL).read_text(encoding="utf-8"))
        assert plan["status"] == "complete"

    def test_remaining_failure_still_blocks(self, tmp_path):
        """Two failures, then only one is re-marked passed — status must
        stay "blocked" because the other failure is still present."""
        _create_plan(tmp_path, steps=3)
        _run(["mark", "0", "failed"], tmp_path)
        _run(["mark", "1", "failed"], tmp_path)
        _run(["mark", "0", "passed"], tmp_path)
        plan = json.loads((tmp_path / PLAN_PATH_REL).read_text(encoding="utf-8"))
        assert plan["status"] == "blocked"


class TestTP117StepTransitions:
    """TP-117 transition coverage for execution_plan.steps[i].status.

    Domain: ("pending", "running", "passed", "failed").
    Function naming follows the TP-117 normalization: field name
    ``execution_plan.steps[i].status`` -> stem ``step_status``;
    each transition test is named
    ``test_step_status_<from>_to_<to>_transition``. The contract test
    in ``tests/test_state_transitions.py`` walks for these names.
    """

    def _step_status(self, tmp_path: Path, index: int) -> str:
        plan = json.loads((tmp_path / PLAN_PATH_REL).read_text(encoding="utf-8"))
        return plan["steps"][index]["status"]

    def test_step_status_pending_to_running_transition(self, tmp_path):
        _create_plan(tmp_path, steps=2)
        assert self._step_status(tmp_path, 0) == "pending"
        _run(["mark", "0", "running"], tmp_path)
        assert self._step_status(tmp_path, 0) == "running"

    def test_step_status_running_to_passed_transition(self, tmp_path):
        _create_plan(tmp_path, steps=2)
        _run(["mark", "0", "running"], tmp_path)
        _run(["mark", "0", "passed"], tmp_path)
        assert self._step_status(tmp_path, 0) == "passed"

    def test_step_status_running_to_failed_transition(self, tmp_path):
        _create_plan(tmp_path, steps=2)
        _run(["mark", "0", "running"], tmp_path)
        _run(["mark", "0", "failed"], tmp_path)
        assert self._step_status(tmp_path, 0) == "failed"

    def test_step_status_failed_to_running_transition(self, tmp_path):
        """TP-102 fix: re-open a failed step by marking it running."""
        _create_plan(tmp_path, steps=2)
        _run(["mark", "0", "failed"], tmp_path)
        _run(["mark", "0", "running"], tmp_path)
        assert self._step_status(tmp_path, 0) == "running"

    def test_step_status_passed_to_running_transition(self, tmp_path):
        """Re-run after passed (idempotent re-entry)."""
        _create_plan(tmp_path, steps=2)
        _run(["mark", "0", "passed"], tmp_path)
        _run(["mark", "0", "running"], tmp_path)
        assert self._step_status(tmp_path, 0) == "running"

    def test_step_status_pending_to_failed_transition(self, tmp_path):
        """Skip-mark-failed: jump straight from pending to failed."""
        _create_plan(tmp_path, steps=2)
        assert self._step_status(tmp_path, 0) == "pending"
        _run(["mark", "0", "failed"], tmp_path)
        assert self._step_status(tmp_path, 0) == "failed"


class TestTP117PlanStatusTransitions:
    """TP-117 transition coverage for execution_plan.status (plan-level).

    Domain: ("in_progress", "complete", "blocked"). The plan-level
    status is derived by ``execution_plan.py::_plan_lock`` from the
    aggregate of step statuses. TP-102 fixed the missing ``else``
    branch that left ``blocked`` sticky.
    """

    def _plan_status(self, tmp_path: Path) -> str:
        plan = json.loads((tmp_path / PLAN_PATH_REL).read_text(encoding="utf-8"))
        return plan["status"]

    def test_plan_status_in_progress_to_complete_transition(self, tmp_path):
        """All steps passed -> complete."""
        _create_plan(tmp_path, steps=2)
        assert self._plan_status(tmp_path) == "in_progress"
        _run(["mark", "0", "passed"], tmp_path)
        _run(["mark", "1", "passed"], tmp_path)
        assert self._plan_status(tmp_path) == "complete"

    def test_plan_status_in_progress_to_blocked_transition(self, tmp_path):
        """Any step failed -> blocked."""
        _create_plan(tmp_path, steps=2)
        assert self._plan_status(tmp_path) == "in_progress"
        _run(["mark", "0", "failed"], tmp_path)
        assert self._plan_status(tmp_path) == "blocked"

    def test_plan_status_blocked_to_in_progress_transition(self, tmp_path):
        """TP-102 fix: failed step re-marked passed (but others still
        running) demotes plan from blocked back to in_progress.
        Without the load-bearing else clause at execution_plan.py:124,
        this stayed sticky-blocked forever."""
        _create_plan(tmp_path, steps=2)
        _run(["mark", "0", "failed"], tmp_path)
        assert self._plan_status(tmp_path) == "blocked"
        _run(["mark", "0", "passed"], tmp_path)
        # step 1 is still pending => plan goes to in_progress, not complete
        assert self._plan_status(tmp_path) == "in_progress"

    def test_plan_status_blocked_to_complete_transition(self, tmp_path):
        """All failures now passed AND all other steps passed -> complete."""
        _create_plan(tmp_path, steps=2)
        _run(["mark", "0", "failed"], tmp_path)
        _run(["mark", "1", "passed"], tmp_path)
        assert self._plan_status(tmp_path) == "blocked"
        _run(["mark", "0", "passed"], tmp_path)
        assert self._plan_status(tmp_path) == "complete"


class TestMalformedPlanGuard:
    """TP-200 (R9-COG-1 sister-site): _load returns any valid-dict plan, including
    a hand-edited / older-schema execution_plan.json that lacks a `steps` list.
    cmd_status / cmd_mark must degrade gracefully (exit 1 + a malformed message)
    instead of raising an uncaught KeyError traceback on the raw plan["steps"]
    subscript — the same fail-open-vs-crash class as the blueprint mutators."""

    def _write_malformed(self, cwd: Path) -> None:
        p = cwd / PLAN_PATH_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        # Valid dict, no `steps` key.
        p.write_text(json.dumps({"task": "x", "status": "in_progress"}), encoding="utf-8")

    def test_status_on_plan_without_steps_degrades(self, tmp_path):
        self._write_malformed(tmp_path)
        result = _run(["status"], tmp_path)
        assert result.returncode == 1
        # earn-the-red: pre-fix this was a KeyError traceback, not a clean message.
        assert "Traceback" not in result.stderr, result.stderr
        assert "malformed" in result.stderr.lower(), result.stderr

    def test_mark_on_plan_without_steps_degrades(self, tmp_path):
        self._write_malformed(tmp_path)
        result = _run(["mark", "0", "passed"], tmp_path)
        assert result.returncode == 1
        assert "Traceback" not in result.stderr, result.stderr
        assert "malformed" in result.stderr.lower(), result.stderr
