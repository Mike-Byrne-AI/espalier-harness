"""Round-9 B1: ``reflect_trigger`` counter must be atomic under
contention.

Pins the post-fix atomicity invariant against a documented race.
Pre-fix, two concurrent Claude Code sessions both read N then both
wrote N+1, so the counter drift caused the every-10th-write
reflect cadence to silently break — reflect passes started firing
at random intervals instead of regular ones, and the operator had
no way to notice. The fix uses ``fcntl.flock`` on POSIX. This
test runs many concurrent incrementers and asserts the final
count equals the number of calls. Without this contract a future
"simplification" that drops the file-lock would re-introduce the
silent cadence regression with no other test catching it.
"""
from __future__ import annotations

import ast
import concurrent.futures
import inspect
import multiprocessing
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"

#: A run fails when no worker has finished an increment for this long: a held
#: lock nobody releases, or workers that never start. Progress, not the clock,
#: decides, because the same 200 increments take under a second on a desktop
#: and 27 s on the windows-latest runner (the 4x50 test, run 37169270105,
#: 2026-10-04).
_STALL_S = 30
#: A run that is still climbing stops here, under ``WORKER_TIMEOUT_S``.
_WORKER_CAP_S = 240
#: The per-test pytest-timeout every caller of :func:`run_spawned_workers`
#: carries. The ini default (60 s, thread method) kills the WHOLE session with
#: no summary line, and the runner's 8x25 needed more than 45 s.
WORKER_TIMEOUT_S = 300

# Set in each spawned worker by _init_worker: the shared count of increments.
_ticks = None


def _init_worker(started, ticks) -> None:
    """Executor initializer: count this worker as started and keep the shared
    increment counter. The two values reach the child as spawn arguments, the one
    route a synchronized ``Value`` may take into another process."""
    global _ticks
    _ticks = ticks
    with started.get_lock():
        started.value += 1


def _worker_loop(step, state_dir: str, each: int) -> int:
    """Run ``step(state_dir)`` ``each`` times, counting each finished call."""
    last = 0
    for _ in range(each):
        last = step(state_dir)
        if _ticks is not None:
            with _ticks.get_lock():
                _ticks.value += 1
    return last


def run_spawned_workers(step, state: Path, workers: int, each: int) -> None:
    """Run ``step(str(state))`` ``each`` times in each of ``workers`` spawned
    processes, and fail with a verdict when the run stops making progress.

    The windows-latest portability leg first hung the session here under a
    ``multiprocessing.Pool`` (PRs #79 to #81, 2026-10-02/03: the session died
    with the main thread parked in ``starmap``), then, under this
    executor and a flat 45 s budget, failed #83 with all eight workers of both
    8x25 tests still running. That reading could not separate a deadlock from a
    slow run, since eight workers taking a fair lock in turns all finish near
    the end, while the 4x50 test beside them finished its 200 increments in
    27 s. So the workers count start-up and every increment into shared values
    and the wait reads them: a dead worker raises ``BrokenProcessPool``, no
    increment for ``_STALL_S`` fails as a stall (start-up or lock, by the
    started count), and a run still climbing at ``_WORKER_CAP_S`` fails as a
    slow host, each with its trail of counts."""
    ctx = multiprocessing.get_context("spawn")
    started, ticks = ctx.Value("i", 0), ctx.Value("i", 0)
    total = workers * each
    pool = concurrent.futures.ProcessPoolExecutor(
        max_workers=workers, mp_context=ctx,
        initializer=_init_worker, initargs=(started, ticks))
    hung = False
    try:
        futures = [pool.submit(_worker_loop, step, str(state), each) for _ in range(workers)]
        begun = last_change = time.monotonic()
        last_count, verdict, trail = 0, "", []
        while True:
            _done, not_done = concurrent.futures.wait(futures, timeout=1.0)
            if not not_done:
                break
            now, count = time.monotonic(), ticks.value
            if count != last_count:
                last_count, last_change = count, now
            if not trail or now - trail[-1][0] >= 5:
                trail.append((now, count))
            if now - last_change >= _STALL_S:
                verdict = (
                    f"no increment for {_STALL_S}s at {count}/{total} with "
                    f"{started.value}/{workers} workers started: "
                    + ("a stalled start-up" if started.value < workers
                       else "a stall inside the step, the lock or its import"))
            elif now - begun >= _WORKER_CAP_S:
                verdict = (f"still climbing at {count}/{total} after "
                           f"{_WORKER_CAP_S}s: a slow host, not a deadlock")
            if verdict:
                hung = True
                break
        assert not hung, (
            f"{len(not_done)} of {workers} spawned workers unfinished, {verdict}. "
            "Counts every 5 s: "
            + ", ".join(f"{t - begun:.0f}s {n}" for t, n in trail)
        )
        for f in futures:
            f.result()  # re-raises a worker's own exception, or BrokenProcessPool
    finally:
        if hung:  # the executor holds the only handle to a stuck worker
            terminate_workers = getattr(pool, "terminate_workers", None)   # 3.14+
            if terminate_workers is not None:
                terminate_workers()
            else:
                # Private before 3.14. Asserted, not defaulted: without it a
                # stuck worker outlives the test and hangs interpreter exit, the
                # session-level hang moved to teardown (failure-mode review, driven).
                assert hasattr(pool, "_processes"), "no handle to terminate stuck workers"
                for proc in list(pool._processes.values()):
                    proc.terminate()
        pool.shutdown(wait=not hung, cancel_futures=True)


def _load_reflect_trigger():
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        import reflect_trigger  # type: ignore
        return reflect_trigger
    finally:
        sys.path.pop(0)


class TestLockedIncrementContract:
    def test_single_call_increments_by_one(self, tmp_path):
        rt = _load_reflect_trigger()
        state = tmp_path / ".espalier-state"
        assert rt._locked_increment(state) == 1
        assert rt._locked_increment(state) == 2
        assert rt._locked_increment(state) == 3

    def test_first_call_creates_state_dir_and_file(self, tmp_path):
        rt = _load_reflect_trigger()
        state = tmp_path / ".espalier-state"
        assert not state.exists()
        rt._locked_increment(state)
        assert (state / "write_count").exists()
        assert (state / "write_count").read_text(encoding="utf-8").strip() == "1"

    def test_handles_corrupt_counter_gracefully(self, tmp_path):
        rt = _load_reflect_trigger()
        state = tmp_path / ".espalier-state"
        state.mkdir()
        (state / "write_count").write_text("not-a-number", encoding="utf-8")
        # Corrupt counter resets to 0; increment returns 1
        assert rt._locked_increment(state) == 1


class TestWriterIsAtomic:
    """TP-151 D-2: the counter write must be atomic (temp + os.replace via
    ``_hook_utils.atomic_write_text``), not an in-place truncate. The reader
    ``stop_gate._read_write_count`` takes no ``LOCK_SH``, so an in-place
    ``seek/truncate/write`` exposes an empty-file window the reader can catch —
    reading 0 and resetting the every-10th-write cadence, skipping Gates 2/3.
    Atomic replace closes that POSIX window. Writer-writer serialization is
    pinned separately by ``TestConcurrentIncrement``.
    """

    def test_write_counter_routes_through_atomic_write_text(self):
        rt = _load_reflect_trigger()
        tree = ast.parse(inspect.getsource(rt._write_counter))
        called = {
            (
                n.func.attr if isinstance(n.func, ast.Attribute)
                else n.func.id if isinstance(n.func, ast.Name)
                else None
            )
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
        }
        assert "atomic_write_text" in called, (
            "_write_counter must route through _hook_utils.atomic_write_text "
            "(temp + os.replace), not a bare write_text — TP-151 D-2."
        )

    def test_locked_increment_does_not_truncate_in_place(self):
        rt = _load_reflect_trigger()
        tree = ast.parse(inspect.getsource(rt._locked_increment))
        truncates = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "truncate"
        ]
        assert not truncates, (
            "_locked_increment still truncates the counter in place — that is "
            "the empty-file window the unlocked reader can catch (TP-151 D-2)."
        )


def _increment_once(state_dir: str) -> int:
    """One worker step: increment the write counter once."""
    return _load_reflect_trigger()._locked_increment(Path(state_dir))


class TestConcurrentIncrement:
    """The whole point of B1: concurrent processes must produce a counter
    equal to the total call count, not less.
    """

    @pytest.mark.timeout(WORKER_TIMEOUT_S)
    def test_eight_workers_each_incrementing_25_times(self, tmp_path):
        state = tmp_path / ".espalier-state"
        workers = 8
        each = 25
        expected_total = workers * each

        run_spawned_workers(_increment_once, state, workers, each)

        final = int((state / "write_count").read_text(encoding="utf-8").strip())
        assert final == expected_total, (
            f"counter drift: expected {expected_total} after {workers}*{each} "
            f"concurrent increments, got {final}. Pre-fix this would be "
            f"<{expected_total}; the flock contract requires exact equality."
        )

    @pytest.mark.timeout(WORKER_TIMEOUT_S)
    def test_four_workers_each_incrementing_50_times(self, tmp_path):
        """Heavier contention than the 8x25 case — same invariant."""
        state = tmp_path / ".espalier-state"
        workers = 4
        each = 50

        run_spawned_workers(_increment_once, state, workers, each)

        assert int((state / "write_count").read_text(encoding="utf-8").strip()) == workers * each
