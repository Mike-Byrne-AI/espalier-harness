"""Canary regression tests for the three Pack 5 security layers (Task 6-E).

Each test here reproduces the exact historical failure mode that motivated
the corresponding layer. Unlike the general Pack 5 tests, these canaries
are named after the specific incident. A failure here means the bypass is
working again — the layer has regressed.

Layers:

1. Friction layer — write_guard.py PreToolUse Bash matcher.
   Incident: April 2026 CC session wrote `{"disableAllHooks": true}` to
   `.claude/settings.json` via a single Bash redirect, disabling every
   hook for the remainder of the session.

2. Visibility layer — session_start.py integrity scan + kill-switch check.
   Incident: `.claude/settings.local.json` with `{"disableAllHooks": true}`
   silently suppressed all enforcement until detection was wired.

3. Guarantee layer — ci_guard.py branch-protection check.
   Incident: unmarked commits modifying protected harness files merged to
   main without friction; CI did not flag the drift.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path



ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = ROOT / "tools" / "cc" / "hooks"
CI_GUARD = ROOT / "tools" / "cc" / "ci_guard.py"


# ---------------------------------------------------------------------------
# Layer 1 — Friction: write_guard blocks the exact April-2026 bypass
# ---------------------------------------------------------------------------

def _run_write_guard(command: str, tmp_path: Path) -> subprocess.CompletedProcess:
    script = HOOKS_DIR / "write_guard.py"
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=15,
        env=env, encoding="utf-8",
    )


def test_regression_cc_bypass_attempt_april_2026(tmp_path):
    """The exact Bash bypass from the April 2026 CC session must be denied.

    Original command: `echo '{"disableAllHooks": true}' > .claude/settings.json`
    Expected: exit 0 + deny JSON on stdout with permissionDecision=deny.
    """
    command = "echo '{\"disableAllHooks\": true}' > .claude/settings.json"
    result = _run_write_guard(command, tmp_path)
    assert result.returncode == 0, (
        f"write_guard did not deny the April 2026 bypass command.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # Block JSON must be parseable and explicit about denial.
    payload = json.loads(result.stdout)
    decision = (
        payload.get("hookSpecificOutput", {}).get("permissionDecision")
        or payload.get("permissionDecision")
        or payload.get("decision")
    )
    assert decision in ("deny", "block"), (
        f"write_guard returned non-deny decision: {payload}"
    )


# ---------------------------------------------------------------------------
# Layer 2 — Visibility: session_start warns and audits on kill-switch findings
#
# SessionStart cannot block Claude Code execution per the official hook
# protocol (docs/external/cc-hook-protocol.md). It surfaces findings via
# stderr + audit; PreToolUse (write_guard) and ConfigChange (config_guard)
# are the blocking surfaces; CI is the merge-time gate.
# ---------------------------------------------------------------------------

def _run_session_start(
    repo: Path, home: Path, payload: dict | None = None
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Don't let the test-suite ESPALIER_AUDIT_DIR override bleed into
    # subprocess hooks that set HOME explicitly to control audit-log placement.
    env.pop("ESPALIER_AUDIT_DIR", None)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    # Path.home() reads USERPROFILE on Windows, HOME on POSIX — set both so
    # the audit dir resolves under `home` on either platform.
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / "session_start.py")],
        input=json.dumps(payload or {}),
        capture_output=True,
        text=True,
        timeout=15,
        env=env, encoding="utf-8",
    )


def test_session_start_warns_and_audits_kill_switch_without_claiming_block(tmp_path):
    """session_start emits a visibility warning + audit event on kill-switch.

    Per the Claude Code hook protocol, SessionStart cannot block. This test
    asserts the visibility-only contract:
      - exit 0 (no blocking)
      - stderr mentions `kill-switch` and includes visibility-only wording
        ("cannot block")
      - audit log records `session_kill_switch_detected`
    """
    home = tmp_path / "home"
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.local.json").write_text(
        json.dumps({"disableAllHooks": True}), encoding="utf-8"
    )
    result = _run_session_start(tmp_path, home)
    assert result.returncode == 0, (
        f"SessionStart must not block (cannot block per protocol); "
        f"got rc={result.returncode}. stderr: {result.stderr}"
    )
    assert "kill-switch" in result.stderr.lower(), (
        f"session_start stderr must mention kill-switch. stderr: {result.stderr}"
    )
    assert "cannot block" in result.stderr.lower(), (
        f"session_start stderr must use visibility-only wording. "
        f"stderr: {result.stderr}"
    )
    audit_files = list((home / ".espalier" / "audit").glob("*.log"))
    assert audit_files, "no audit log entry was written for the kill-switch event"
    combined = "\n".join(f.read_text(encoding="utf-8") for f in audit_files)
    assert "session_kill_switch_detected" in combined, (
        "audit log must record the visibility-only event "
        "session_kill_switch_detected"
    )


# ---------------------------------------------------------------------------
# Layer 3 — Guarantee: ci_guard flags unmarked protected-settings changes
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    merged = {**os.environ}
    if env:
        merged.update(env)
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=str(cwd), env=merged, encoding="utf-8"
    )


def _git_identity() -> dict:
    return {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@t",
    }


def test_regression_unmarked_settings_change(tmp_path):
    """ci_guard must deny a commit that modifies .claude/settings.json without
    the HARNESS-UPDATE-APPROVED marker.

    Exit 1 and the offending path named on stdout.
    """
    env = _git_identity()
    _git(["init", "-b", "main"], tmp_path, env)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {}}), encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("init\n", encoding="utf-8")
    _git(["add", "."], tmp_path, env)
    _git(["commit", "-m", "init"], tmp_path, env)

    _git(["checkout", "-b", "feature"], tmp_path, env)
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"PreToolUse": []}}), encoding="utf-8"  # looks like a bypass
    )
    _git(["add", "-A"], tmp_path, env)
    _git(["commit", "-m", "tweak settings"], tmp_path, env)

    env_run = {**os.environ}
    # Mirrors tests/test_ci_guard.py::_run_guard — scrub every ambient input
    # ci_guard reads, including GITHUB_ACTOR (the Dependabot allowance) and
    # GITHUB_EVENT_NAME, or a real runner's values leak into the subprocess.
    for k in ("BASE_SHA", "BEFORE_SHA", "PR_TITLE", "PR_HEAD_SHA", "GITHUB_ACTOR",
              "GITHUB_EVENT_NAME"):
        env_run.pop(k, None)
    result = subprocess.run(
        [sys.executable, str(CI_GUARD)],
        capture_output=True, text=True, timeout=15, cwd=str(tmp_path), env=env_run, encoding="utf-8",
    )
    assert result.returncode == 2, (
        f"ci_guard did not flag unmarked settings change. stdout: {result.stdout}"
    )
    assert ".claude/settings.json" in result.stdout, (
        f"ci_guard did not name the offending path. stdout: {result.stdout}"
    )
