"""One spawn for the rows that run write_guard, or the statusline, as a real
child (DEF-2014).

The windows-latest portability cell stalls now and then. Before DEF-979's
split, a third of its cells redded on a ``write_guard`` hook-through row the
change never touched, a different row each time: seven of ten at the rows'
15 s spawn bound and three at the hook's own judgment budget
(``tools/cc/hooks/write_guard.py::JUDGMENT_BUDGET_S``), whose refusal a
verdict row reads as a wrong answer. A stall is transient; a regression is
not. So a miss (a timeout, or the budget's refusal) is retried once under the
SAME bound: a stalled runner answers the second time, while a hook that hangs,
or is slow every time, misses both and reds on every runner, naming both
elapsed times. Any other answer, a wrong verdict included, is the first
attempt's.

Three limits keep the retry honest:

- one retry per test row, so a row that spawns several times waits at most
  one bound longer than it did, and a second miss fails at once;
- no retry when the missed attempt left anything under the project's
  ``.espalier-state`` (a speed bump's one-shot flag, say), since the retry
  would read it as a re-issue and answer differently; an ordinary judgment
  leaves nothing there (driven 2026-10-17);
- the statusline keeps its own 5 s bound, its prompt-delay check.

A retry that answers is a ``HookSpawnRetried`` warning, which the run's summary
counts (``tests/conftest.py::pytest_terminal_summary``). The budget itself is
the hook's and is not touched here: it fails closed by design.
"""
from __future__ import annotations

import os
import subprocess
import time
import warnings
from pathlib import Path

import pytest

#: The text of write_guard's refusal when its judgment outran its budget
#: (``tools/cc/hooks/_denial_reasons.py::WRITE_GUARD_TIME_BUDGET``).
BUDGET_REFUSAL = "could not finish judging"
#: Each attempt's bound for a hook: the 15 s every hook row ran under before.
HOOK_S = 15.0
#: Each attempt's bound for the statusline: its prompt-delay check (BC-027).
STATUSLINE_S = 5.0

#: The test rows that have spent their one retry, by PYTEST_CURRENT_TEST.
_RETRIED: set[str] = set()


class HookSpawnRetried(UserWarning):
    """A hook row's first attempt missed and its retry answered."""


def _attempt(argv: list[str], *, statusline: bool, binary: bool, **kwargs) -> subprocess.CompletedProcess:
    # One call per bound, each bound a module constant written at its call: the
    # suite contract holding every wait under its test's ceiling reads only that
    # (tests/test_test_suite_contract.py); a bound passed in would be unread.
    if statusline:
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              timeout=STATUSLINE_S, **kwargs)
    if binary:
        return subprocess.run(argv, capture_output=True, timeout=HOOK_S, **kwargs)
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                          timeout=HOOK_S, **kwargs)


def _state(env: dict | None) -> list[tuple[str, int, int]] | None:
    """What lies under the project's ``.espalier-state``: (path, size, mtime)."""
    project = (env if env is not None else os.environ).get("CLAUDE_PROJECT_DIR")
    if not project:
        return None
    state = Path(project) / ".espalier-state"
    if not state.is_dir():
        return []
    out = []
    for p in sorted(state.rglob("*")):
        try:
            st = p.stat()
        except OSError:
            continue
        out.append((str(p.relative_to(state)), st.st_size, st.st_mtime_ns))
    return out


def _row() -> str:
    return os.environ.get("PYTEST_CURRENT_TEST", "").rsplit(" (", 1)[0]


def run_hook_through(
    argv: list[str], *, env: dict | None = None, input: str | bytes | None = None,
    cwd: str | None = None, statusline: bool = False,
) -> subprocess.CompletedProcess:
    """Run a hook as Claude Code does, text in and out (or bytes, when the
    input is bytes), with one retry on a miss under the same bound."""
    name = Path(argv[1]).name if len(argv) > 1 else str(argv[0])
    bound = STATUSLINE_S if statusline else HOOK_S
    before = _state(env)
    misses: list[str] = []
    for _attempt_no in range(2):
        began = time.monotonic()
        try:
            result = _attempt(argv, statusline=statusline, binary=isinstance(input, bytes),
                              input=input, cwd=cwd, env=env)
        except subprocess.TimeoutExpired:
            misses.append(f"no answer in {time.monotonic() - began:.1f} s")
        else:
            out = result.stdout if isinstance(result.stdout, str) else (result.stdout or b"").decode("utf-8", "replace")
            if BUDGET_REFUSAL not in (out or ""):
                if misses:
                    warnings.warn(HookSpawnRetried(
                        f"{name}: the first attempt missed ({misses[0]}); "
                        f"the retry answered in {time.monotonic() - began:.1f} s"), stacklevel=2)
                return result
            misses.append(f"the budget's refusal after {time.monotonic() - began:.1f} s")
        if len(misses) == 2:
            break
        row = _row()
        if row and row in _RETRIED:
            pytest.fail(f"{name} missed ({misses[0]}) and this row has spent its one retry "
                        f"(each attempt bounded at {bound:.0f} s).")
        after = _state(env)
        if after != before:
            pytest.fail(f"{name} missed ({misses[0]}) after leaving state under .espalier-state, "
                        "which a retry would read as a re-issue; so it is not retried.")
        _RETRIED.add(row)
    pytest.fail(
        f"{name} missed on both attempts: {misses[0]}, then {misses[1]} (each bounded at "
        f"{bound:.0f} s). A stalled runner misses once; a hook that hangs, or is slow "
        "every time, misses every time, on every runner.")
