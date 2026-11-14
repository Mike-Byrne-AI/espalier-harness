"""DEF-3081: config_guard judges a change to the user settings file, and a
variable that switches a gate in any settings ``env`` map.

Why: Claude Code names a change to ``~/.claude/settings.json`` by its absolute
path (``source: user_settings``, the hooks reference), and the hook dropped
that path as out of root and scanned the two project files instead, so
``disableAllHooks`` or a gate variable written there was let through. A
settings ``env`` map reaches the hook process (driven 2026-11-14 on Claude
Code 2.1.319, one nested headless run), and the settings reference says a
user-settings ``env`` change is applied to the running session.

Precision, from the same references: hook lists merge across settings files,
so an emptied hook list in the user file removes no project hook and is not a
finding; ``disableAllHooks`` and each ``env`` variable take the value of the
highest-precedence file (local, project, user). A gate variable is judged
against the hook process's live value, so one already in effect at the start
refuses nothing.

Every row drives the source hook with a scratch home, a scratch project and a
scratch audit directory (the scratch home's own), the gate variables and ``CLAUDE_CONFIG_DIR`` stripped
from the inherited environment unless the row sets them.
"""
# slow-exempt: deployed-hook subprocesses over scratch trees, about 0.15 s each
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tests._hook_runner import HOOKS_DIR, run_hook

GATE_VARS = ("ESPALIER_MAINTENANCE_MODE", "ESPALIER_STOP_GATE", "ESPALIER_STOP_GATE_TEST_CMD")


def _integrity():
    spec = importlib.util.spec_from_file_location("_integrity_def3081", HOOKS_DIR / "_integrity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Box:
    """A scratch home and project; ``change`` runs config_guard on one event."""

    def __init__(self, tmp: Path) -> None:
        self.home = tmp / "home"
        self.project = tmp / "proj"
        # With HOME moved, an ESPALIER_AUDIT_DIR override is refused as outside
        # it, so the record lands in the scratch home's own audit directory.
        self.audit = self.home / ".espalier" / "audit"
        for d in (self.home / ".claude", self.project / ".claude"):
            d.mkdir(parents=True)
        self.user = self.home / ".claude" / "settings.json"

    def write(self, path: Path, data: object) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def project_file(self, name: str = "settings.json") -> Path:
        return self.project / ".claude" / name

    def change(self, source: str, file_path: object = "user", live: dict | None = None,
               config_dir: Path | None = None) -> dict | None:
        """The decision JSON, or None for an allow. ``file_path``: ``"user"`` for
        the user file's absolute path, None to leave the field out, else a path."""
        payload: dict = {"hook_event_name": "ConfigChange", "source": source}
        if file_path == "user":
            payload["file_path"] = str(self.user)
        elif file_path is not None:
            payload["file_path"] = str(file_path)
        env: dict = {name: None for name in GATE_VARS}
        env.update(HOME=str(self.home), USERPROFILE=str(self.home), CLAUDE_PROJECT_DIR=str(self.project),
                   ESPALIER_AUDIT_DIR=None, CLAUDE_CONFIG_DIR=str(config_dir) if config_dir else None)
        env.update(live or {})
        result = run_hook("config_guard.py", payload, env)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout) if result.stdout.strip() else None

    def audit_events(self) -> list[dict]:
        records = []
        for log in self.audit.glob("*.log"):
            records += [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
        return records


@pytest.fixture
def box(tmp_path: Path) -> Box:
    return Box(tmp_path)


def _blocked(decision: dict | None, *needles: str) -> None:
    assert decision is not None and decision.get("decision") == "block", decision
    for needle in needles:
        assert needle in decision["reason"], (needle, decision["reason"])


class TestAUserSettingsChangeIsRead:
    def test_disable_all_hooks_in_the_user_file_is_refused(self, box):
        """The row's first shape. Red at base: the path is dropped as out of root."""
        box.write(box.user, {"disableAllHooks": True})
        _blocked(box.change("user_settings"), "~/.claude/settings.json: disableAllHooks: true")

    def test_the_user_file_is_found_by_source_when_the_payload_names_no_path(self, box):
        box.write(box.user, {"disableAllHooks": True})
        _blocked(box.change("user_settings", file_path=None), "disableAllHooks")

    def test_the_user_file_under_claude_config_dir_is_read(self, box, tmp_path):
        """Claude Code keeps user settings under CLAUDE_CONFIG_DIR when it is set."""
        config = tmp_path / "config"
        path = box.write(config / "settings.json", {"disableAllHooks": True})
        _blocked(box.change("user_settings", file_path=path, config_dir=config),
                 "$CLAUDE_CONFIG_DIR/settings.json: disableAllHooks: true")

    def test_a_project_false_outranks_the_user_true(self, box):
        """Precedence: the project file's ``false`` is the value Claude Code reads."""
        box.write(box.user, {"disableAllHooks": True})
        box.write(box.project_file(), {"disableAllHooks": False})
        assert box.change("user_settings") is None

    def test_an_emptied_hook_list_in_the_user_file_is_not_a_finding(self, box):
        """Hook lists merge across files: an empty user list removes no project hook."""
        box.write(box.user, {"hooks": {"PreToolUse": [], "Stop": [{"hooks": []}]}})
        assert box.change("user_settings") is None

    def test_an_ordinary_user_change_is_let_through(self, box):
        box.write(box.user, {"model": "opus", "env": {"SOME_TOOL_FLAG": "1"}})
        assert box.change("user_settings") is None

    def test_a_path_outside_the_root_that_is_not_the_user_file_is_not_read(self, box, tmp_path):
        """The root bound stays for every other path: a project-named source
        pointing elsewhere opens nothing outside the tree."""
        other = box.write(tmp_path / "elsewhere" / ".claude" / "settings.json", {"disableAllHooks": True})
        assert box.change("project_settings", file_path=other) is None


class TestAGateVariableInAnEnvMapIsJudged:
    def test_the_maintenance_switch_in_the_user_env_map_is_refused(self, box):
        """The row's second shape. Red at base: no reader judges an env map."""
        box.write(box.user, {"env": {"ESPALIER_MAINTENANCE_MODE": "1"}})
        _blocked(box.change("user_settings"), "env.ESPALIER_MAINTENANCE_MODE")

    def test_a_switch_already_in_effect_refuses_nothing(self, box):
        """The session already runs with it (the operator's launch): no change to judge."""
        box.write(box.user, {"env": {"ESPALIER_MAINTENANCE_MODE": "1"}})
        assert box.change("user_settings", live={"ESPALIER_MAINTENANCE_MODE": "1"}) is None

    @pytest.mark.parametrize("value", ["0", "", "yes"])
    def test_a_maintenance_value_that_reads_inactive_is_let_through(self, box, value):
        box.write(box.user, {"env": {"ESPALIER_MAINTENANCE_MODE": value}})
        assert box.change("user_settings") is None

    def test_the_stop_gate_leaving_full_is_refused(self, box):
        box.write(box.user, {"env": {"ESPALIER_STOP_GATE": "light"}})
        _blocked(box.change("user_settings", live={"ESPALIER_STOP_GATE": "full"}), "env.ESPALIER_STOP_GATE")

    @pytest.mark.parametrize("value", ["full", "light"])
    def test_a_stop_gate_value_that_loosens_nothing_is_let_through(self, box, value):
        """Light is the default floor: turning the gate to full tightens it, and
        naming light where the session runs the default changes nothing."""
        box.write(box.user, {"env": {"ESPALIER_STOP_GATE": value}})
        assert box.change("user_settings") is None

    def test_a_replaced_stop_gate_test_command_is_refused(self, box):
        box.write(box.user, {"env": {"ESPALIER_STOP_GATE_TEST_CMD": "true"}})
        _blocked(box.change("user_settings"), "env.ESPALIER_STOP_GATE_TEST_CMD")

    def test_the_test_command_the_session_already_runs_is_let_through(self, box):
        box.write(box.user, {"env": {"ESPALIER_STOP_GATE_TEST_CMD": "pytest -q"}})
        assert box.change("user_settings", live={"ESPALIER_STOP_GATE_TEST_CMD": "pytest -q"}) is None

    @pytest.mark.parametrize("name,source", [("settings.json", "project_settings"),
                                             ("settings.local.json", "local_settings")])
    def test_the_project_files_env_maps_are_judged_too(self, box, name, source):
        """The sibling sites (SP 18): no reader judged an env map in either project file."""
        path = box.write(box.project_file(name), {"env": {"ESPALIER_MAINTENANCE_MODE": "1"}})
        _blocked(box.change(source, file_path=path), f".claude/{name}: env.ESPALIER_MAINTENANCE_MODE")

    def test_a_local_value_outranks_the_user_one(self, box):
        """Precedence per variable: the local file's ``0`` is the value that applies."""
        box.write(box.user, {"env": {"ESPALIER_MAINTENANCE_MODE": "1"}})
        box.write(box.project_file("settings.local.json"), {"env": {"ESPALIER_MAINTENANCE_MODE": "0"}})
        assert box.change("user_settings") is None

    def test_a_change_to_another_file_does_not_answer_for_the_user_file(self, box):
        """A switch the user file already held is the user file's change, not
        this one's: a project edit is judged on what it supplies."""
        box.write(box.user, {"env": {"ESPALIER_MAINTENANCE_MODE": "1"}})
        path = box.write(box.project_file(), {"model": "opus"})
        assert box.change("project_settings", file_path=path) is None

    def test_a_skills_change_judges_no_settings_file(self, box):
        box.write(box.user, {"env": {"ESPALIER_MAINTENANCE_MODE": "1"}})
        assert box.change("skills", file_path=box.project / ".claude" / "skills" / "x" / "SKILL.md") is None

    def test_a_policy_settings_change_is_audit_only(self, box):
        """policy_settings cannot be blocked (the protocol); nothing here blocks it."""
        box.write(box.user, {"env": {"ESPALIER_MAINTENANCE_MODE": "1"}})
        assert box.change("policy_settings", file_path=None) is None


class TestTheRefusalIsRecordedAndTold:
    def test_the_refusal_writes_the_kill_switch_audit_record(self, box):
        box.write(box.user, {"env": {"ESPALIER_MAINTENANCE_MODE": "1"}})
        _blocked(box.change("user_settings"))
        events = [r for r in box.audit_events() if r.get("event_type") == "configchange_blocked_kill_switch"]
        assert events and events[-1]["details"]["source"] == "user_settings", box.audit_events()
        assert any("env.ESPALIER_MAINTENANCE_MODE" in f for f in events[-1]["details"]["findings"])

    def test_the_next_tool_result_is_told_once(self, box):
        """ConfigChange has no channel: the note waits for the next PostToolUse."""
        box.write(box.user, {"disableAllHooks": True})
        _blocked(box.change("user_settings"))
        ig = _integrity()
        notice = ig.take_switch_notice(box.project)
        assert notice and "~/.claude/settings.json: disableAllHooks: true" in notice, notice
        assert "NEXT session" in notice and notice.isascii(), notice
        assert ig.take_switch_notice(box.project) is None, "told once"

    def test_post_write_check_tells_it_beside_the_next_tool_result(self, box):
        """The delivery itself: the PostToolUse hook's one JSON object carries it."""
        box.write(box.user, {"env": {"ESPALIER_STOP_GATE_TEST_CMD": "true"}})
        _blocked(box.change("user_settings"))
        result = run_hook("post_write_check.py",
                          {"hook_event_name": "PostToolUse", "tool_name": "Read",
                           "tool_input": {"file_path": "notes.txt"}, "tool_response": {}},
                          {"HOME": str(box.home), "USERPROFILE": str(box.home),
                           "CLAUDE_PROJECT_DIR": str(box.project), "ESPALIER_AUDIT_DIR": None})
        assert result.returncode == 0, result.stderr
        assert "env.ESPALIER_STOP_GATE_TEST_CMD" in result.stdout, result.stdout
        assert "would switch a gate off" in result.stdout, result.stdout

    def test_an_allowed_change_leaves_nothing_to_tell(self, box):
        box.write(box.user, {"model": "opus"})
        assert box.change("user_settings") is None
        assert _integrity().take_switch_notice(box.project) is None
