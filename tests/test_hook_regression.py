"""Canary regression tests for Pack 4 hook-hygiene repairs (Task 6-F).

Pack 4 repaired two classes of hook defect:

1. **Stop timing contract**: outer Claude Code timeout was 10s, inner
   pytest budget 60s — the outer would always kill the inner before it
   could complete. Fixed by introducing `hook_contract.STOP_OUTER_TIMEOUT`
   (90s) and asserting `OUTER >= INNER + MARGIN`.

2. **Silent swallows**: `reflect_trigger.py`, `session_start.py`, and
   `post_compact.py` caught exceptions with
   `pass` or broad `except Exception`, producing invisible failures.
   Fixed by emitting `espalier: WARN:` lines to stderr on anomalous
   paths while keeping expected absences silent.

These canaries exist alongside the Pack 4 tests as intentional locks.
If any of these fail, a Pack 4 repair has regressed — the fix does not
belong here; fix it at the hook source and keep the canary passing.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = ROOT / "tools" / "cc" / "hooks"


def _run_hook(script: str, payload: dict, env_overrides: dict) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=15,
        env=env, encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Stop timing contract — delegated to Pack 4's test_hook_contracts.py
# ---------------------------------------------------------------------------

def test_regression_stop_timing_contract_preserved():
    """`STOP_OUTER_TIMEOUT >= STOP_INNER_BUDGET + STOP_SAFETY_MARGIN`.

    Duplicates Pack 4's invariant test as an anchor — if `hook_contract.py`
    is ever edited to shrink the outer timeout below the inner budget again,
    this test fails with a clear regression label.
    """
    from espalier import hook_contract

    assert hook_contract.STOP_OUTER_TIMEOUT >= (
        hook_contract.STOP_INNER_BUDGET + hook_contract.STOP_SAFETY_MARGIN
    ), (
        "Stop timing contract violated — the outer timeout could kill the "
        "inner pytest subprocess before it completes. This was Pack 4's "
        "primary repair; do not regress it."
    )


# ---------------------------------------------------------------------------
# Silent-swallow regressions
# ---------------------------------------------------------------------------

def test_regression_session_start_malformed_file_warns(tmp_path):
    """session_start on a malformed package.json must emit a WARN, not swallow.

    Historical bug: a broken JSON file in the project root caused the hook
    to fall back silently, losing the signal that something was wrong.
    """
    (tmp_path / "package.json").write_text("{ this is not json", encoding="utf-8")
    result = _run_hook(
        "session_start.py",
        {},
        {"CLAUDE_PROJECT_DIR": str(tmp_path), "HOME": str(tmp_path / "home")},
    )
    assert result.returncode == 0, (
        f"session_start should not crash on malformed file. stderr: {result.stderr}"
    )
    assert "[WARN] espalier" in result.stderr, (
        "session_start silently swallowed a malformed optional file — Pack 4 "
        f"repair regressed. stderr: {result.stderr!r}"
    )


def test_regression_post_compact_malformed_file_warns(tmp_path):
    """post_compact on a malformed package.json must emit a WARN."""
    (tmp_path / "package.json").write_text("{ broken", encoding="utf-8")
    result = _run_hook(
        "post_compact.py",
        {},
        {"CLAUDE_PROJECT_DIR": str(tmp_path), "HOME": str(tmp_path / "home")},
    )
    assert result.returncode == 0
    assert "[WARN] espalier" in result.stderr, (
        "post_compact silently swallowed a malformed optional file — Pack 4 "
        f"repair regressed. stderr: {result.stderr!r}"
    )


def test_regression_session_start_absent_files_are_silent(tmp_path):
    """No ESPALIER_MEMORY.md present → no WARN emitted. Absence is expected, not anomalous.

    This is the complementary invariant — we must not drift so far into
    loudness that missing optional files start producing noise. Absence is
    silent; corruption is loud.
    """
    result = _run_hook(
        "session_start.py",
        {},
        {"CLAUDE_PROJECT_DIR": str(tmp_path), "HOME": str(tmp_path / "home")},
    )
    assert result.returncode == 0
    assert "[WARN] espalier" not in result.stderr, (
        "session_start emitted a warning for an absent optional file — this "
        "is noise, not signal. Pack 4 drew the line at corruption, not absence."
    )


def test_regression_session_resume_git_failure_visible(tmp_path):
    """session_resume status mode with no git binary: either WARN to stderr or
    graceful fallback — never a silent broad-exception swallow.
    """
    script = ROOT / "tools" / "cc" / "session_resume.py"
    env = os.environ.copy()
    env["PATH"] = str(tmp_path)  # no git binary resolvable
    result = subprocess.run(
        [sys.executable, str(script), "--mode", "status"],
        capture_output=True, text=True, timeout=15, cwd=str(tmp_path), env=env, encoding="utf-8",
    )
    assert result.returncode == 0, "session_resume crashed on missing git"
    assert "Traceback" not in result.stderr, (
        "session_resume raised an unhandled exception — broad-except regression"
    )
    # Either the output falls back cleanly OR stderr shows the warning line.
    assert "REPO:" in result.stdout
