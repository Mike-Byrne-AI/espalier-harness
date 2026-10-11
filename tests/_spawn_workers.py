"""The spawn-pool machinery two concurrency tests drive, in a module whose
imports are the standard library alone.

``tests/test_reflect_trigger_concurrency.py`` and ``tests/test_session_signals.py``
run their step in eight spawned interpreters. Under the ``spawn`` start method a
child imports the module that defines the initializer, the worker loop and the
step, by name, so while those lived in the test modules every child imported a
test module and everything it imports (``pytest`` among them, and for the
session-signals test two test modules, since its module imports the other). On
the windows-latest portability runner the eight workers took 115 s to start
(DEF-1130, run 37420133724) and no run had measured where the start-up went.
This module is the lighter target, and it stamps the child's timeline so the
runner's next reading is a measurement: ``_MODULE_UP_AT`` when the interpreter
reached this module (after the spawn, the parent main's re-import and these
imports), "started" when the initializer finished. ``run_spawned_workers``
reports both in its verdict and in its warning.

Standard library only, on purpose: the hook under test is loaded by path inside
the step, after the worker has counted itself started. The per-test
pytest-timeout the callers carry, ``WORKER_TIMEOUT_S``, stays in
``tests/test_reflect_trigger_concurrency.py``: the suite contract that reads a
``timeout(NAME)`` resolves the name from a sibling ``test_*.py`` only.
"""
from __future__ import annotations

import concurrent.futures
import multiprocessing
import os
import sys
import time
import warnings
from pathlib import Path

#: When this interpreter reached this module (wall clock, the clock the workers
#: stamp with). The standard-library imports above cost milliseconds; what the
#: stamp measures against the parent's submission is the spawn itself.
_MODULE_UP_AT = time.time()

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"

#: A run fails when no worker has finished an increment for this long: a held
#: lock nobody releases, or workers that never start. Progress, not the clock,
#: decides, because the same 200 increments take under a second on a desktop
#: and 27 s on the windows-latest runner (the 4x50 test, run 37169270105,
#: 2026-10-04).
_STALL_S = 30
#: Start-up is not an increment, so it has its own, longer window: a spawned
#: worker is a fresh interpreter importing this module and its imports, and on
#: the windows-latest runner none of eight had started 30 s after submission in
#: every Windows portability run from #86 to #102 (2026-10-04/05), while the
#: same rows pass on a Windows desktop in under a second. Progress during
#: start-up is a worker starting; from the first increment on, ``_STALL_S``
#: applies.
_STARTUP_S = 120
#: A run that is still climbing stops here, under ``WORKER_TIMEOUT_S``.
_WORKER_CAP_S = 240

# Set in each spawned worker by _init_worker: the shared count of increments.
_ticks = None

#: Seconds each spawned worker sleeps before it counts itself started, read
#: from the environment it inherits at spawn. Only the start-up-window rows set
#: it: a desktop starts eight workers in under a second, so this is how the
#: runner's slow start is reproduced here.
_STARTUP_DELAY_ENV = "SPAWN_TEST_STARTUP_DELAY_S"


def _init_worker(started, ticks, first_up_at, last_up_at,
                 first_module_up_at, last_module_up_at) -> None:
    """Executor initializer: count this worker as started, stamp when the first
    and the last worker started (wall clock: a monotonic reading is not
    comparable across processes), and keep the shared increment counter. The
    values reach the child as spawn arguments, the one route a synchronized
    ``Value`` may take into another process."""
    global _ticks
    _ticks = ticks
    # First, before any delay: when this interpreter reached this module. The
    # gap from the parent's submission to this stamp is the spawn itself (the
    # interpreter, the parent main's re-import, this module's imports); the gap
    # from here to "started" is the initializer. A stalled start-up with the
    # module stamp set and "started" unset puts the stall in the initializer;
    # with neither set, in the spawn (DEF-1130: measure before widening).
    with first_module_up_at.get_lock():
        if not first_module_up_at.value or _MODULE_UP_AT < first_module_up_at.value:
            first_module_up_at.value = _MODULE_UP_AT
        last_module_up_at.value = max(last_module_up_at.value, _MODULE_UP_AT)
    delay = float(os.environ.get(_STARTUP_DELAY_ENV) or 0)
    if delay > 0:
        time.sleep(delay)
    with started.get_lock():
        started.value += 1
        now = time.time()
        if not first_up_at.value:
            first_up_at.value = now
        last_up_at.value = max(last_up_at.value, now)


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
    and the wait reads them: a dead worker raises ``BrokenProcessPool``;
    before the first increment, no new start for ``_STARTUP_S`` fails as a
    stalled start-up; from the first increment on, no progress for
    ``_STALL_S`` fails as a stall (start-up or lock, by the started count); a
    run still climbing at ``_WORKER_CAP_S`` fails as a slow host. Every
    verdict carries the trail of increments and starts and when the first and
    the last worker started, and a green run whose first start outlasted
    ``_STALL_S`` says so in a warning, so the runner's reading is recorded
    either way."""
    ctx = multiprocessing.get_context("spawn")
    started, ticks = ctx.Value("i", 0), ctx.Value("i", 0)
    first_up_at, last_up_at = ctx.Value("d", 0.0), ctx.Value("d", 0.0)
    first_module_up_at, last_module_up_at = ctx.Value("d", 0.0), ctx.Value("d", 0.0)
    total = workers * each
    pool = concurrent.futures.ProcessPoolExecutor(
        max_workers=workers, mp_context=ctx,
        initializer=_init_worker,
        initargs=(started, ticks, first_up_at, last_up_at, first_module_up_at, last_module_up_at))
    hung = False
    try:
        submitted = time.time()  # wall clock, the clock the workers stamp with
        futures = [pool.submit(_worker_loop, step, str(state), each) for _ in range(workers)]
        begun = last_change = time.monotonic()
        last_count, last_up, verdict, trail = 0, 0, "", []
        while True:
            _done, not_done = concurrent.futures.wait(futures, timeout=1.0)
            if not not_done:
                break
            now, count, up = time.monotonic(), ticks.value, started.value
            if count != last_count or up != last_up:
                last_count, last_up, last_change = count, up, now
            if not trail or now - trail[-1][0] >= 5:
                trail.append((now, count, up))
            # Start-up lasts until the first increment: an idle worker takes the
            # next task, so the last worker may still be starting when the rest
            # are done, and a stall among the running ones is caught at _STALL_S.
            window = _STARTUP_S if count == 0 else _STALL_S
            if now - last_change >= window:
                verdict = (
                    f"no progress for {window}s at {count}/{total} increments with "
                    f"{up}/{workers} workers started: "
                    + ("a stalled start-up" if up < workers
                       else "a stall inside the step, the lock or its import"))
            elif now - begun >= _WORKER_CAP_S:
                verdict = (f"still climbing at {count}/{total} after "
                           f"{_WORKER_CAP_S}s: a slow host, not a deadlock")
            if verdict:
                hung = True
                break
        up_count = started.value
        first_s = first_up_at.value - submitted if up_count else None
        reached_s = first_module_up_at.value - submitted if first_module_up_at.value else None
        reached = (
            f"; the first interpreter reached the worker module {reached_s:.0f}s after "
            f"submission and the last {last_module_up_at.value - submitted:.0f}s (the spawn: "
            f"interpreter, the parent main's re-import, this module's imports)"
            if reached_s is not None else "; no interpreter reached the worker module")
        started_at = (
            f"{up_count}/{workers} started, the first {first_s:.0f}s and the last "
            f"{last_up_at.value - submitted:.0f}s after submission"
            if first_s is not None else f"0/{workers} started") + reached
        assert not hung, (
            f"{len(not_done)} of {workers} spawned workers unfinished, {verdict}; "
            f"{started_at}. Increments and starts every 5 s: "
            + ", ".join(f"{t - begun:.0f}s {n} ({u} up)" for t, n, u in trail)
        )
        if first_s is not None and first_s > _STALL_S:
            # Green, but only because start-up has its own window: record how
            # long it took, so the runner's slow start is a reading, not a guess.
            warnings.warn(
                f"spawned workers took {first_s:.0f}s to start: {started_at} "
                f"(over the {_STALL_S}s increment window)",
                stacklevel=2,
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


def load_reflect_trigger():
    """The hook under test, loaded by path (``tools/cc/hooks/`` is not a package)."""
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        import reflect_trigger  # type: ignore
        return reflect_trigger
    finally:
        sys.path.pop(0)


def _increment_once(state_dir: str) -> int:
    """One worker step: increment the write counter once."""
    return load_reflect_trigger()._locked_increment(Path(state_dir))


def _record_once(state_dir: str) -> int:
    """One worker step: count one tool call."""
    return load_reflect_trigger()._record_tool_call(Path(state_dir), "Read")[0]
