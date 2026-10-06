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


def _run(root: Path, env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Drive the deployed hook rooted on ``root`` -- the ``self_host_tree_copy``
    fixture, never REPO_ROOT: a SessionStart rewrites the running session's
    ``session_started`` stamp and clears its gate counters wherever it is
    rooted (the live tree paid that on every suite run until 2026-10-05). The
    payload carries a session id so the run leaves a marker: a marker is the
    one write the ``_no_live_session_markers`` guard can attribute, so a re-root
    on the live tree reds there instead of passing silently."""
    assert root.resolve() != REPO_ROOT, "drive self_host_tree_copy, never the live tree"
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(root)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(SESSION_START)],
        input='{"hook_event_name":"SessionStart","session_id":"maint-test"}',
        cwd=str(root),
        capture_output=True,
        env=env,
        text=True,
        timeout=15, encoding="utf-8",
    )


def test_session_start_warns_when_maintenance_mode_active(self_host_tree_copy):
    result = _run(self_host_tree_copy, {"ESPALIER_MAINTENANCE_MODE": "1"})
    assert "ESPALIER_MAINTENANCE_MODE" in result.stderr, (
        "TP-147 147-F: SessionStart did not emit the maintenance-mode "
        "WARN banner. stderr was:\n" + result.stderr
    )
    assert "[WARN]" in result.stderr
    assert "bypassed" in result.stderr.lower()


def test_session_start_silent_when_maintenance_mode_unset(self_host_tree_copy):
    # Use a sentinel value other than "1" to confirm the gate is
    # strict-equal (not just "any truthy string").
    result = _run(self_host_tree_copy, {"ESPALIER_MAINTENANCE_MODE": "0"})
    assert "ESPALIER_MAINTENANCE_MODE active" not in result.stderr, (
        "SessionStart emitted the maintenance-mode banner when the "
        "env var was set to '0'; the gate must be a strict '==1' check."
    )
