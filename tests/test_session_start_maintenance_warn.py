"""TP-147 147-F: SessionStart emits a WARN line when
``ESPALIER_MAINTENANCE_MODE`` is set at session boot.

Per-bypass logs from ``_maintenance_mode.is_active`` only fire when a
friction check is invoked. Operators who set the env var in a shell
rc for permanence may not trip a friction check at all in a given
session — the persistence cost stays invisible. SessionStart making
it visible at every boot is the discoverability surface.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSION_START = REPO_ROOT / "tools" / "cc" / "hooks" / "session_start.py"


def _run(env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(REPO_ROOT)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(SESSION_START)],
        input='{"hook_event_name":"SessionStart"}',
        capture_output=True,
        env=env,
        text=True,
        timeout=15, encoding="utf-8",
    )


def test_session_start_warns_when_maintenance_mode_active():
    result = _run({"ESPALIER_MAINTENANCE_MODE": "1"})
    assert "ESPALIER_MAINTENANCE_MODE" in result.stderr, (
        "TP-147 147-F: SessionStart did not emit the maintenance-mode "
        "WARN banner. stderr was:\n" + result.stderr
    )
    assert "[WARN]" in result.stderr
    assert "bypassed" in result.stderr.lower()


def test_session_start_silent_when_maintenance_mode_unset():
    # Use a sentinel value other than "1" to confirm the gate is
    # strict-equal (not just "any truthy string").
    result = _run({"ESPALIER_MAINTENANCE_MODE": "0"})
    assert "ESPALIER_MAINTENANCE_MODE active" not in result.stderr, (
        "SessionStart emitted the maintenance-mode banner when the "
        "env var was set to '0'; the gate must be a strict '==1' check."
    )
