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

from tests._hook_spawn import run_hook_through

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
    return run_hook_through(
        [sys.executable, str(HOOKS_DIR / script_name)],
        input=json.dumps(payload),
        env=env,
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

    def test_a_bypass_default_does_not_wedge_the_session(self, tmp_path):
        """DEF-1108: a bypassPermissions default in the operator's local settings
        was classed as a kill-switch, so every tool call was denied, Glob and
        Read included, until the file was edited outside the session. Hooks
        still run and deny in bypass mode, so it is a posture, not a kill-switch:
        an ordinary call passes, and a guard still bites."""
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
        assert not result.stdout.strip(), result.stdout
        result = _run_hook(
            "write_guard.py",
            {"tool_name": "Read", "tool_input": {"file_path": str(tmp_path / ".env")}},
            tmp_path,
        )
        data = json.loads(result.stdout)
        assert data["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "Secret-path" in data["hookSpecificOutput"]["permissionDecisionReason"]

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

    @pytest.mark.parametrize("name,source", [("settings.json", "project"), ("settings.local.json", "local")])
    def test_a_bypass_default_is_not_refused(self, tmp_path, name, source):
        """DEF-1108: a bypassPermissions default is not a kill-switch, and
        config_guard does not judge it: the hooks still run and deny in bypass
        mode, a ConfigChange block is shown to no one and does not revert the
        file, and the mode is chosen at launch. A session writing one is stopped
        at the write by write_guard (both files are protected); a change to the
        operator's own bypass file (an allow rule added, say) is not refused."""
        _write_settings(
            tmp_path,
            {"permissions": {"defaultMode": "bypassPermissions", "allow": ["Bash(ls)"]}},
            name=name,
        )
        result = _run_hook(
            "config_guard.py",
            {"hook_event_name": "ConfigChange",
             "source": source,
             "file_path": f".claude/{name}"},
            tmp_path,
        )
        assert result.returncode == 0
        assert not result.stdout.strip(), result.stdout

    def test_a_bypass_beside_a_kill_switch_is_refused_for_the_kill_switch(self, tmp_path):
        _write_settings(
            tmp_path,
            {"disableAllHooks": True, "permissions": {"defaultMode": "bypassPermissions"}},
        )
        result = _run_hook(
            "config_guard.py",
            {"hook_event_name": "ConfigChange", "source": "project",
             "file_path": ".claude/settings.json"},
            tmp_path,
        )
        data = json.loads(result.stdout)
        assert data.get("decision") == "block"
        assert "disableAllHooks" in data.get("reason", "")
        assert "bypassPermissions" not in data.get("reason", "")

    def test_an_unrelated_change_is_not_refused_for_a_bypass_elsewhere(self, tmp_path):
        """The inventory fallback reads kill-switches only: a bypass default in
        the local file no longer blocks a change to a clean project file."""
        _write_settings(tmp_path, {"permissions": {"defaultMode": "bypassPermissions"}},
                        name="settings.local.json")
        _write_settings(tmp_path, {"permissions": {"allow": ["Bash(ls)"]}})
        result = _run_hook(
            "config_guard.py",
            {"hook_event_name": "ConfigChange",
             "source": "project",
             "session_id": "s-any",
             "file_path": ".claude/settings.json"},
            tmp_path,
        )
        assert result.returncode == 0
        assert not result.stdout.strip(), result.stdout

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


# ── The local file's hook lists merge: no kill-switch there ─────────────

# The scan's three hook-list arms, each as a settings payload carrying it on one
# governed event.
_HOOK_LIST_ARMS = {
    "empty-list": {"hooks": {"PreToolUse": []}},
    "inner-empty": {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": []}]}},
    "no-op-commands": {"hooks": {"PreToolUse": [
        {"matcher": "*", "hooks": [{"type": "command", "command": "true"}]}]}},
}

_SOURCE_OF = {"settings.json": "project", "settings.local.json": "local"}


class TestALocalHookListIsNoKillSwitch:
    """DEF-4121: Claude Code merges hook lists across the user, project and
    local files (the hooks reference), so an emptied or no-op list in
    ``.claude/settings.local.json`` removes no project hook (driven on Claude
    Code 2.1.321, macOS: each of the three arms in the local file, on
    UserPromptSubmit and Stop, and the empty list on PreToolUse, left the
    project file's marker hooks firing; a local marker hook fired beside them,
    and a local ``disableAllHooks`` silenced both). The scan read the
    arms in both files, so write_guard refused every call, a Read included,
    over a local file that unwires nothing, and config_guard refused the local
    change. In the project file, where ``init`` writes the wiring, each arm
    still unwires a gate and stays a kill-switch; ``disableAllHooks`` turns
    every hook off from either file and stays one in both."""

    @staticmethod
    def _read(root: Path) -> subprocess.CompletedProcess:
        return _run_hook(
            "write_guard.py",
            {"tool_name": "Read", "tool_input": {"file_path": "anything.txt"}},
            root,
        )

    @staticmethod
    def _change(root: Path, name: str) -> subprocess.CompletedProcess:
        return _run_hook(
            "config_guard.py",
            {"hook_event_name": "ConfigChange", "source": _SOURCE_OF[name],
             "file_path": f".claude/{name}"},
            root,
        )

    @pytest.mark.parametrize("arm", sorted(_HOOK_LIST_ARMS))
    def test_write_guard_lets_a_read_through_over_the_local_list(self, tmp_path, arm):
        _write_settings(tmp_path, _HOOK_LIST_ARMS[arm], name="settings.local.json")
        result = self._read(tmp_path)
        assert result.returncode == 0, result.stderr
        assert not result.stdout.strip(), (
            f"the {arm} arm in settings.local.json removes no project hook (hook "
            f"lists merge), yet write_guard refused a Read: {result.stdout}"
        )

    @pytest.mark.parametrize("arm", sorted(_HOOK_LIST_ARMS))
    def test_write_guard_refuses_the_same_list_in_the_project_file(self, tmp_path, arm):
        _write_settings(tmp_path, _HOOK_LIST_ARMS[arm])
        data = json.loads(self._read(tmp_path).stdout)
        hso = data["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"
        assert ".claude/settings.json: hooks.PreToolUse" in hso["permissionDecisionReason"]

    @pytest.mark.parametrize("arm", sorted(_HOOK_LIST_ARMS))
    def test_config_guard_lets_the_local_change_through(self, tmp_path, arm):
        _write_settings(tmp_path, _HOOK_LIST_ARMS[arm], name="settings.local.json")
        result = self._change(tmp_path, "settings.local.json")
        assert result.returncode == 0, result.stderr
        assert not result.stdout.strip(), (
            f"config_guard refused a local change carrying the {arm} arm, which "
            f"unwires nothing: {result.stdout}"
        )

    @pytest.mark.parametrize("arm", sorted(_HOOK_LIST_ARMS))
    def test_config_guard_refuses_the_same_change_to_the_project_file(self, tmp_path, arm):
        _write_settings(tmp_path, _HOOK_LIST_ARMS[arm])
        data = json.loads(self._change(tmp_path, "settings.json").stdout)
        assert data.get("decision") == "block"

    def test_the_project_file_reached_through_a_symlink_keeps_its_arms(self, tmp_path, monkeypatch):
        """config_guard resolves the payload's path before it labels the file,
        so a project file that is a symlink is read under its target's path. It
        still takes the project label and its arms are read, with the
        inventory fallback stubbed to find nothing."""
        import importlib.util
        root = tmp_path.resolve()
        real = _write_settings(root, _HOOK_LIST_ARMS["empty-list"], name="real-settings.json")
        try:
            (root / ".claude" / "settings.json").symlink_to(real)
        except (OSError, NotImplementedError):
            pytest.skip("this host cannot make a symlink")
        spec = importlib.util.spec_from_file_location(
            "_config_guard_def4121", HOOKS_DIR / "config_guard.py")
        cg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cg)
        monkeypatch.setattr(cg._integrity, "scan_for_kill_switches", lambda _root, **_kw: [])
        assert cg._scan_payload(".claude/settings.json", root) == [
            ".claude/settings.json: hooks.PreToolUse is an empty list"]

    def test_disable_all_hooks_in_the_local_file_is_still_refused(self, tmp_path):
        _write_settings(tmp_path, {"disableAllHooks": True}, name="settings.local.json")
        hso = json.loads(self._read(tmp_path).stdout)["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"
        assert ".claude/settings.local.json: disableAllHooks: true" in hso["permissionDecisionReason"]
        data = json.loads(self._change(tmp_path, "settings.local.json").stdout)
        assert data.get("decision") == "block"
        assert "disableAllHooks" in data.get("reason", "")


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
