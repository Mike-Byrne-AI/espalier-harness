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
import inspect
import multiprocessing
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"


def _load_reflect_trigger():
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        import reflect_trigger  # type: ignore
        return reflect_trigger
    finally:
        sys.path.pop(0)


@pytest.mark.skipif(sys.platform == "win32", reason="fcntl unavailable on Windows; fallback documented")
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


def _increment_n_times(state_dir: str, n: int) -> int:
    """Worker for multiprocessing pool: increment counter n times."""
    sys.path.insert(0, str(HOOKS_DIR))
    import reflect_trigger
    last = 0
    for _ in range(n):
        last = reflect_trigger._locked_increment(Path(state_dir))
    return last


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX flock contract")
class TestConcurrentIncrement:
    """The whole point of B1: concurrent processes must produce a counter
    equal to the total call count, not less.
    """

    def test_eight_workers_each_incrementing_25_times(self, tmp_path):
        state = tmp_path / ".espalier-state"
        workers = 8
        each = 25
        expected_total = workers * each

        with multiprocessing.get_context("spawn").Pool(workers) as pool:
            pool.starmap(_increment_n_times, [(str(state), each)] * workers)

        final = int((state / "write_count").read_text(encoding="utf-8").strip())
        assert final == expected_total, (
            f"counter drift: expected {expected_total} after {workers}*{each} "
            f"concurrent increments, got {final}. Pre-fix this would be "
            f"<{expected_total}; the flock contract requires exact equality."
        )

    def test_four_workers_each_incrementing_50_times(self, tmp_path):
        """Heavier contention than the 8x25 case — same invariant."""
        state = tmp_path / ".espalier-state"
        workers = 4
        each = 50

        with multiprocessing.get_context("spawn").Pool(workers) as pool:
            pool.starmap(_increment_n_times, [(str(state), each)] * workers)

        assert int((state / "write_count").read_text(encoding="utf-8").strip()) == workers * each
