"""Kill-switch enforcement on the blocking hook surfaces.

Per the Claude Code hook protocol (docs/external/cc-hook-protocol.md):
- SessionStart cannot block; it can only audit + warn (visibility).
- PreToolUse can block tool calls.
- ConfigChange can block project/local/user settings changes; managed
  policy_settings are audit-only (non-blockable).
- CI is the merge-time guarantee.

This file pins the blocking-surface contract for kill-switch findings:

  TestWriteGuardKillSwitchGate     — PreToolUse (write_guard.py)
  TestConfigGuardBlocking          — ConfigChange (config_guard.py)
  TestConfigGuardPolicyAuditOnly   — ConfigChange policy_settings audit
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"


def _run_hook(
    script_name: str, payload: dict, tmp_path: Path, *, home: Path | None = None
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Don't let the test-suite ESPALIER_AUDIT_DIR override bleed in when the
    # caller supplies an explicit home= to control the audit-log location.
    if home is not None:
        env.pop("ESPALIER_AUDIT_DIR", None)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    if home is not None:
        # Path.home() reads USERPROFILE on Windows, HOME on POSIX — set both so
        # the audit dir resolves under `home` on either platform.
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / script_name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=15,
        env=env, encoding="utf-8",
    )


def _write_settings(tmp_path: Path, payload: dict, *, name: str = "settings.json") -> Path:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    path = claude_dir / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ── PreToolUse: write_guard kill-switch gate ────────────────────────────


class TestWriteGuardKillSwitchGate:
    """write_guard.py blocks all PreToolUse calls while a kill-switch is set.

    The gate runs before the read-only fast path so it fires for every tool
    call, including tools with no mutation potential. This is intentional —
    once a kill-switch is armed, nothing should proceed until it is removed.
    """

    def test_blocks_write_when_disable_all_hooks_set(self, tmp_path):
        _write_settings(tmp_path, {"disableAllHooks": True})
        result = _run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "src/x.py", "content": "x"}},
            tmp_path,
        )
        assert result.returncode == 0  # exit-0 + JSON deny per TP-9 protocol
        data = json.loads(result.stdout)
        hso = data.get("hookSpecificOutput", {})
        assert hso.get("permissionDecision") == "deny"
        reason = hso.get("permissionDecisionReason", "")
        assert "kill-switch" in reason.lower()
        assert "disableAllHooks" in reason

    def test_blocks_read_only_tool_when_kill_switch_set(self, tmp_path):
        """Read tool would normally pass via the fast path; kill-switch
        gate runs before that fast path, so it blocks anyway."""
        _write_settings(tmp_path, {"disableAllHooks": True})
        result = _run_hook(
            "write_guard.py",
            {"tool_name": "Read", "tool_input": {"file_path": "anything.txt"}},
            tmp_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_blocks_when_settings_local_has_bypass_permissions(self, tmp_path):
        _write_settings(
            tmp_path,
            {"permissions": {"defaultMode": "bypassPermissions"}},
            name="settings.local.json",
        )
        result = _run_hook(
            "write_guard.py",
            {"tool_name": "Glob", "tool_input": {"pattern": "*.py"}},
            tmp_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "bypassPermissions" in data["hookSpecificOutput"]["permissionDecisionReason"]

    def test_allows_when_no_kill_switch_present(self, tmp_path):
        """Sanity: a clean settings file does NOT trigger the gate."""
        _write_settings(tmp_path, {})
        result = _run_hook(
            "write_guard.py",
            {"tool_name": "Read", "tool_input": {"file_path": "anything.txt"}},
            tmp_path,
        )
        assert result.returncode == 0
        # Clean exit means stdout is empty (no JSON deny block).
        assert not result.stdout.strip()

    def test_audit_event_recorded_on_kill_switch_block(self, tmp_path):
        home = tmp_path / "home"
        _write_settings(tmp_path, {"disableAllHooks": True})
        result = _run_hook(
            "write_guard.py",
            {"tool_name": "Edit", "tool_input": {"file_path": "src/x.py"}},
            tmp_path,
            home=home,
        )
        assert result.returncode == 0
        audit_files = list((home / ".espalier" / "audit").glob("*.log"))
        assert audit_files, "expected audit entry for pretooluse_blocked_kill_switch"
        combined = "\n".join(f.read_text(encoding="utf-8") for f in audit_files)
        assert "pretooluse_blocked_kill_switch" in combined


# ── ConfigChange: config_guard blocking ─────────────────────────────────


class TestConfigGuardBlocking:
    """config_guard.py blocks unsafe project/local/user settings changes."""

    @pytest.mark.parametrize("source", ["project", "local", "user"])
    def test_blocks_disable_all_hooks(self, tmp_path, source):
        _write_settings(tmp_path, {"disableAllHooks": True})
        result = _run_hook(
            "config_guard.py",
            {"hook_event_name": "ConfigChange",
             "source": source,
             "file_path": ".claude/settings.json"},
            tmp_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data.get("decision") == "block"
        assert "kill-switch" in data.get("reason", "").lower()
        assert "disableAllHooks" in data.get("reason", "")

    def test_blocks_bypass_permissions(self, tmp_path):
        _write_settings(
            tmp_path,
            {"permissions": {"defaultMode": "bypassPermissions"}},
        )
        result = _run_hook(
            "config_guard.py",
            {"hook_event_name": "ConfigChange",
             "source": "project",
             "file_path": ".claude/settings.json"},
            tmp_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data.get("decision") == "block"
        assert "bypassPermissions" in data.get("reason", "")

    def test_blocks_empty_hook_list(self, tmp_path):
        _write_settings(
            tmp_path,
            {"hooks": {"PreToolUse": []}},
        )
        result = _run_hook(
            "config_guard.py",
            {"hook_event_name": "ConfigChange",
             "source": "project",
             "file_path": ".claude/settings.json"},
            tmp_path,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data.get("decision") == "block"

    def test_empty_hook_list_for_nongoverned_event_passes(self, tmp_path):
        """R3: an empty list for an event Espalier does NOT wire (e.g. an
        adopter's own 'PreCompact': []) is semantically identical to omitting
        the key and must NOT be flagged as a kill-switch / blocked. Only
        Espalier-governed events neuter a deployed hook when emptied."""
        _write_settings(
            tmp_path,
            {"hooks": {"PreCompact": []}},
        )
        result = _run_hook(
            "config_guard.py",
            {"hook_event_name": "ConfigChange",
             "source": "project",
             "file_path": ".claude/settings.json"},
            tmp_path,
        )
        assert result.returncode == 0
        # Non-governed event → not a kill-switch → clean pass-through (no block).
        assert not result.stdout.strip()

    def test_clean_settings_pass_through(self, tmp_path):
        _write_settings(tmp_path, {})
        result = _run_hook(
            "config_guard.py",
            {"hook_event_name": "ConfigChange",
             "source": "project",
             "file_path": ".claude/settings.json"},
            tmp_path,
        )
        assert result.returncode == 0
        # Clean → no JSON, no stderr noise.
        assert not result.stdout.strip()


# ── ConfigChange: policy_settings is audit-only ─────────────────────────


class TestConfigGuardPolicyAuditOnly:
    """ConfigChange cannot block managed policy_settings per the hook
    protocol. config_guard must audit + warn but never emit a block JSON
    for source='policy_settings'."""

    def test_policy_settings_kill_switch_audit_only(self, tmp_path):
        home = tmp_path / "home"
        _write_settings(tmp_path, {"disableAllHooks": True})
        result = _run_hook(
            "config_guard.py",
            {"hook_event_name": "ConfigChange",
             "source": "policy_settings",
             "file_path": ".claude/settings.json"},
            tmp_path,
            home=home,
        )
        assert result.returncode == 0
        # No JSON block emitted.
        assert not result.stdout.strip(), (
            f"policy_settings must not emit a structured block; got stdout={result.stdout!r}"
        )
        # Stderr warns about the audit-only nature.
        assert "policy_settings" in result.stderr.lower() or "policy" in result.stderr.lower()
        assert "audit-only" in result.stderr.lower()
        # Audit log records the visibility-only event.
        audit_files = list((home / ".espalier" / "audit").glob("*.log"))
        assert audit_files, "expected audit entry for policy_settings finding"
        combined = "\n".join(f.read_text(encoding="utf-8") for f in audit_files)
        assert "configchange_policy_settings_kill_switch_detected" in combined
