"""DEF-3081: config_guard judges a change to the user settings file, and a
variable that switches a gate in any settings ``env`` map.

Why: Claude Code names a change to ``~/.claude/settings.json`` by its absolute
path (``source: user_settings``, the hooks reference), and the hook dropped
that path as out of root and scanned the two project files instead, so
``disableAllHooks`` or a gate variable written there was let through. A
settings ``env`` map reaches the hook process (driven 2026-11-14 on Claude
Code 2.1.319, one nested headless run: SessionStart and UserPromptSubmit), and
the settings reference says a user-settings ``env`` change is applied to the
running session.

Precision, from the same references: hook lists merge across settings files,
so an emptied hook list in the user file removes no project hook and is not a
finding; ``disableAllHooks`` and each ``env`` variable take the value of the
highest-precedence file (local, project, user).

The CHANGE is judged, not the file's state: SessionStart snapshots the values
the three files supply (``_integrity.SETTINGS_GATES_SNAPSHOT``), and a change
is refused where it loosens a gate against that snapshot -- at the files'
layer, so a switch written for every later session is refused even where this
session's launch already carries it, and at the session's layer, where the
launch shell supplies a value no file set. A value the files do not own
(managed settings, ``--settings``) is not the change's to move.

Every config_guard row drives the source hook with a scratch home, a scratch
project and the scratch home's own audit directory, the gate variables and
``CLAUDE_CONFIG_DIR`` stripped from the inherited environment unless the row
sets them. The SessionStart snapshot is taken in-process through
``session_start._record_settings_gate_values`` under the same environment.
"""
# slow-exempt: deployed-hook subprocesses over scratch trees, about 0.15 s each
from __future__ import annotations

import functools
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests._hook_runner import HOOKS_DIR, run_hook

GATE_VARS = ("ESPALIER_MAINTENANCE_MODE", "ESPALIER_STOP_GATE", "ESPALIER_STOP_GATE_TEST_CMD")
MM, SG, CMD = GATE_VARS


def _load(name: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, HOOKS_DIR / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _integrity():
    return _load("_integrity.py", "_integrity_def3081")


@functools.lru_cache(maxsize=1)
def _session_start():
    return _load("session_start.py", "_session_start_def3081")


class Box:
    """A scratch home and project; ``start`` takes SessionStart's snapshot,
    ``change`` runs config_guard on one event."""

    def __init__(self, tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.home = tmp / "home"
        self.project = tmp / "proj"
        self.mp = monkeypatch
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

    def _env(self, live: dict | None, config_dir: Path | None) -> dict:
        env: dict = {name: None for name in GATE_VARS}
        env.update(HOME=str(self.home), USERPROFILE=str(self.home), CLAUDE_PROJECT_DIR=str(self.project),
                   ESPALIER_AUDIT_DIR=None, CLAUDE_CONFIG_DIR=str(config_dir) if config_dir else None)
        env.update(live or {})
        return env

    def start(self, live: dict | None = None, source: str = "startup", config_dir: Path | None = None) -> None:
        """What SessionStart records, under the session's environment."""
        with self.mp.context() as m:
            for name, value in self._env(live, config_dir).items():
                if value is None:
                    m.delenv(name, raising=False)
                else:
                    m.setenv(name, value)
            _session_start()._record_settings_gate_values(self.project, source)

    def change(self, source: str, file_path: object = "user", live: dict | None = None,
               config_dir: Path | None = None) -> dict | None:
        """The decision JSON, or None for an allow. ``file_path``: ``"user"`` for
        the user file's absolute path, None to leave the field out, else a path."""
        payload: dict = {"hook_event_name": "ConfigChange", "source": source}
        if file_path == "user":
            payload["file_path"] = str(self.user)
        elif file_path is not None:
            payload["file_path"] = str(file_path)
        result = run_hook("config_guard.py", payload, self._env(live, config_dir))
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout) if result.stdout.strip() else None

    def audit_events(self) -> list[dict]:
        records = []
        for log in self.audit.glob("*.log"):
            records += [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
        return records


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Box:
    return Box(tmp_path, monkeypatch)


def _blocked(decision: dict | None, *needles: str) -> None:
    assert decision is not None and decision.get("decision") == "block", decision
    for needle in needles:
        assert needle in decision["reason"], (needle, decision["reason"])


class TestAUserSettingsChangeIsRead:
    def test_disable_all_hooks_in_the_user_file_is_refused(self, box):
        """The row's first shape. Red at base: the path is dropped as out of root."""
        box.start()
        box.write(box.user, {"disableAllHooks": True})
        _blocked(box.change("user_settings"), "~/.claude/settings.json: disableAllHooks: true")

    def test_the_user_file_is_found_by_source_when_the_payload_names_no_path(self, box):
        box.start()
        box.write(box.user, {"disableAllHooks": True})
        _blocked(box.change("user_settings", file_path=None), "disableAllHooks")

    def test_the_user_file_under_claude_config_dir_is_read(self, box, tmp_path):
        """Claude Code keeps user settings under CLAUDE_CONFIG_DIR when it is set."""
        config = tmp_path / "config"
        box.start(config_dir=config)
        path = box.write(config / "settings.json", {"disableAllHooks": True})
        _blocked(box.change("user_settings", file_path=path, config_dir=config),
                 "$CLAUDE_CONFIG_DIR/settings.json: disableAllHooks: true")

    def test_a_project_false_outranks_the_user_true(self, box):
        """Precedence: the project file's ``false`` is the value Claude Code reads."""
        box.write(box.project_file(), {"disableAllHooks": False})
        box.start()
        box.write(box.user, {"disableAllHooks": True})
        assert box.change("user_settings") is None

    def test_an_emptied_hook_list_in_the_user_file_is_not_a_finding(self, box):
        """Hook lists merge across files: an empty user list removes no project hook."""
        box.start()
        box.write(box.user, {"hooks": {"PreToolUse": [], "Stop": [{"hooks": []}]}})
        assert box.change("user_settings") is None

    def test_an_ordinary_user_change_is_let_through(self, box):
        box.start()
        box.write(box.user, {"model": "opus", "env": {"SOME_TOOL_FLAG": "1"}})
        assert box.change("user_settings") is None

    def test_a_path_outside_the_root_that_is_not_the_user_file_is_not_read(self, box, tmp_path):
        """The root bound stays for every other path: a project-named source
        pointing elsewhere opens nothing outside the tree."""
        box.start()
        other = box.write(tmp_path / "elsewhere" / ".claude" / "settings.json", {"disableAllHooks": True})
        assert box.change("project_settings", file_path=other) is None


class TestTheChangeIsJudgedAgainstTheStart:
    """The failure-mode review's four holes in a judgment of the file's state
    against the hook's live environment."""

    def test_a_maintenance_launch_writing_the_switch_into_the_user_file_is_refused(self, box):
        """Hole (a): the session already runs maintenance mode, so the live
        value matched and the write passed, but the file carries the switch
        into every later session on the machine."""
        box.start(live={MM: "1"})
        box.write(box.user, {"env": {MM: "1"}})
        _blocked(box.change("user_settings", live={MM: "1"}), f"env.{MM}")

    def test_a_switch_the_files_held_at_the_start_refuses_nothing(self, box):
        """Nothing changed: the operator's own file, loaded at launch."""
        box.write(box.user, {"env": {MM: "1"}})
        box.start(live={MM: "1"})
        box.write(box.user, {"env": {MM: "1"}, "model": "opus"})
        assert box.change("user_settings", live={MM: "1"}) is None

    def test_deleting_the_full_stop_gate_from_the_user_file_is_refused(self, box):
        """Hole (b): a deleted key supplies no value, and was skipped."""
        box.write(box.user, {"env": {SG: "full"}})
        box.start(live={SG: "full"})
        box.write(box.user, {})
        _blocked(box.change("user_settings", live={SG: "full"}), f"env.{SG}")

    def test_removing_a_higher_key_that_unmasks_a_looser_lower_value_is_refused(self, box):
        """Hole (c): the local file's ``full`` masked the user file's ``light``."""
        box.write(box.user, {"env": {SG: "light"}})
        local = box.write(box.project_file("settings.local.json"), {"env": {SG: "full"}})
        box.start(live={SG: "full"})
        box.write(local, {})
        _blocked(box.change("local_settings", file_path=local, live={SG: "full"}), f"env.{SG}")

    def test_a_value_owned_above_the_three_files_is_not_the_changes_to_move(self, box):
        """Hole (d): managed settings or ``--settings`` own the value (the
        session runs one the files do not supply), so a user-file value never
        applies, and judging it refused every user-file change."""
        live = {SG: "full", CMD: "make test"}
        box.write(box.user, {"env": {CMD: "pytest -q"}})
        box.start(live=live)
        box.write(box.user, {"env": {CMD: "true"}, "model": "opus"})
        assert box.change("user_settings", live=live) is None

    def test_a_looser_file_value_over_the_launch_shells_is_refused(self, box):
        """The session layer: no file set the gate, the launch shell did, and
        a file value now outranks it."""
        box.start(live={SG: "full"})
        box.write(box.user, {"env": {SG: "light"}})
        _blocked(box.change("user_settings", live={SG: "full"}), f"env.{SG}")

    def test_a_compaction_keeps_the_snapshot_the_process_started_with(self, box):
        """Only a process start loads the files afresh."""
        box.start()
        box.write(box.user, {"env": {MM: "1"}})
        box.start(source="compact")
        _blocked(box.change("user_settings"), f"env.{MM}")

    def test_with_no_snapshot_a_value_the_session_runs_is_the_start(self, box):
        """A session that began before this hook (or whose SessionStart was cut)
        is judged against the values it runs with."""
        box.write(box.user, {"env": {MM: "1"}})
        assert box.change("user_settings", live={MM: "1"}) is None

    def test_with_no_snapshot_a_value_the_session_does_not_run_is_refused(self, box):
        box.write(box.user, {"env": {MM: "1"}})
        _blocked(box.change("user_settings"), f"env.{MM}")

    def test_a_change_let_through_with_no_snapshot_records_one(self, box):
        """The let-through writes the start for the next change."""
        box.write(box.user, {"env": {SG: "full"}})
        assert box.change("user_settings") is None
        box.write(box.user, {})
        _blocked(box.change("user_settings"), f"env.{SG}")


class TestAGateVariableInAnEnvMapIsJudged:
    def test_the_maintenance_switch_in_the_user_env_map_is_refused(self, box):
        """The row's second shape. Red at base: no reader judges an env map."""
        box.start()
        box.write(box.user, {"env": {MM: "1"}})
        _blocked(box.change("user_settings"), f"env.{MM}")

    @pytest.mark.parametrize("value", ["0", "", "yes"])
    def test_a_maintenance_value_that_reads_inactive_is_let_through(self, box, value):
        box.start()
        box.write(box.user, {"env": {MM: value}})
        assert box.change("user_settings") is None

    @pytest.mark.parametrize("value", ["full", "light"])
    def test_a_stop_gate_value_that_loosens_nothing_is_let_through(self, box, value):
        """Light is the default floor: turning the gate to full tightens it, and
        naming light where the session runs the default changes nothing."""
        box.start()
        box.write(box.user, {"env": {SG: value}})
        assert box.change("user_settings") is None

    @pytest.mark.parametrize("name,source", [("settings.json", "project_settings"),
                                             ("settings.local.json", "local_settings")])
    def test_the_project_files_env_maps_are_judged_too(self, box, name, source):
        """The sibling sites (SP 18): no reader judged an env map in either project file."""
        box.start()
        path = box.write(box.project_file(name), {"env": {MM: "1"}})
        _blocked(box.change(source, file_path=path), f".claude/{name}: env.{MM}")

    def test_a_local_value_outranks_the_user_one(self, box):
        """Precedence per variable: the local file's ``0`` is the value that applies."""
        box.write(box.project_file("settings.local.json"), {"env": {MM: "0"}})
        box.start()
        box.write(box.user, {"env": {MM: "1"}})
        assert box.change("user_settings") is None

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows folds env name case; POSIX does not")
    def test_a_mixed_case_name_is_the_variable_on_windows(self, box):
        """The first review's finding 1 (verified): a child process on Windows
        reads ``Espalier_Maintenance_Mode`` as the maintenance switch."""
        box.start()
        box.write(box.user, {"env": {"Espalier_Maintenance_Mode": "1"}})
        _blocked(box.change("user_settings"), f"env.{MM}")

    def test_an_integral_number_is_read_as_javascript_renders_it(self, box):
        """``1.0`` reaches the process as ``"1"``."""
        box.start()
        box.write(box.user, {"env": {MM: 1.0}})
        _blocked(box.change("user_settings"), f"env.{MM}")

    def test_a_null_in_a_higher_file_masks_nothing(self, box):
        box.write(box.project_file("settings.local.json"), {"env": {MM: None}, "disableAllHooks": None})
        box.start()
        box.write(box.user, {"env": {MM: "1"}})
        _blocked(box.change("user_settings"), f"env.{MM}")

    def test_the_user_file_is_found_by_location_when_the_source_is_missing(self, box):
        box.start()
        box.write(box.user, {"env": {MM: "1"}})
        _blocked(box.change("", file_path=box.user), f"env.{MM}")

    def test_a_skills_change_judges_no_settings_file(self, box):
        box.start()
        box.write(box.user, {"env": {MM: "1"}})
        assert box.change("skills", file_path=box.project / ".claude" / "skills" / "x" / "SKILL.md") is None

    def test_a_policy_settings_change_is_audit_only(self, box):
        """policy_settings cannot be blocked (the protocol); nothing here blocks it."""
        box.start()
        box.write(box.user, {"env": {MM: "1"}})
        assert box.change("policy_settings", file_path=None) is None


class TestTheStopGateTestCommand:
    """Item 2: the command is judged only where Gate 1 runs it -- the stop gate
    full and an env command already in effect. Under light the gate runs
    nothing, and a full gate with no command is the dormancy banner's advice
    to set one: both are tightenings."""

    def test_a_replaced_command_under_the_full_gate_is_refused(self, box):
        live = {SG: "full", CMD: "pytest -q"}
        box.start(live=live)
        box.write(box.user, {"env": {CMD: "true"}})
        _blocked(box.change("user_settings", live=live), f"env.{CMD}")

    def test_a_command_set_under_the_light_gate_is_let_through(self, box):
        box.start()
        box.write(box.user, {"env": {CMD: "true"}})
        assert box.change("user_settings") is None

    def test_a_command_set_where_the_full_gate_has_none_is_let_through(self, box):
        box.start(live={SG: "full"})
        box.write(box.user, {"env": {CMD: "pytest -q"}})
        assert box.change("user_settings", live={SG: "full"}) is None

    def test_the_command_the_session_already_runs_is_let_through(self, box):
        live = {SG: "full", CMD: "pytest -q"}
        box.start(live=live)
        box.write(box.user, {"env": {CMD: "pytest -q"}})
        assert box.change("user_settings", live=live) is None


class TestTheRefusalIsRecordedAndTold:
    def test_the_refusal_writes_an_audit_record_naming_the_file_by_label(self, box):
        """Item 6: the record carries the label, never the home directory."""
        box.start()
        box.write(box.user, {"env": {MM: "1"}})
        _blocked(box.change("user_settings"))
        events = [r for r in box.audit_events() if r.get("event_type") == "configchange_blocked_kill_switch"]
        assert events, box.audit_events()
        details = events[-1]["details"]
        assert details["source"] == "user_settings" and details["kind"] == "gate_switch", details
        assert details["file_path"] == "~/.claude/settings.json", details
        assert any(f"env.{MM}" in f for f in details["findings"])
        assert str(box.home) not in json.dumps(events[-1]) and box.home.name not in json.dumps(details)

    def test_the_next_tool_result_is_told_once(self, box):
        """ConfigChange has no channel: the note waits for the next PostToolUse.
        Item 7: it says what happened and leaves the call to the reader."""
        box.start()
        box.write(box.user, {"disableAllHooks": True})
        _blocked(box.change("user_settings"))
        ig = _integrity()
        notice = ig.take_switch_notice(box.project)
        assert notice and "~/.claude/settings.json: disableAllHooks: true" in notice, notice
        assert "not applied" in notice and "next launch" in notice and notice.isascii(), notice
        assert "before this session ends" not in notice, notice
        assert ig.take_switch_notice(box.project) is None, "told once"

    def test_post_write_check_tells_it_beside_the_next_tool_result(self, box):
        """The delivery itself: the PostToolUse hook's one JSON object carries it."""
        box.start()
        box.write(box.user, {"env": {MM: "1"}})
        _blocked(box.change("user_settings"))
        result = run_hook("post_write_check.py",
                          {"hook_event_name": "PostToolUse", "tool_name": "Read",
                           "tool_input": {"file_path": "notes.txt"}, "tool_response": {}},
                          {"HOME": str(box.home), "USERPROFILE": str(box.home),
                           "CLAUDE_PROJECT_DIR": str(box.project), "ESPALIER_AUDIT_DIR": None})
        assert result.returncode == 0, result.stderr
        assert f"env.{MM}" in result.stdout, result.stdout
        assert "would switch a gate off" in result.stdout, result.stdout

    def test_an_allowed_change_leaves_nothing_to_tell(self, box):
        box.start()
        box.write(box.user, {"model": "opus"})
        assert box.change("user_settings") is None
        assert _integrity().take_switch_notice(box.project) is None

    def test_a_later_change_let_through_clears_the_note(self, box):
        """Item 3: the file fixed is no longer told as unfixed."""
        box.start()
        box.write(box.user, {"env": {MM: "1"}})
        _blocked(box.change("user_settings"))
        box.write(box.user, {})
        assert box.change("user_settings") is None
        assert _integrity().take_switch_notice(box.project) is None

    def test_a_change_let_through_becomes_the_start_for_the_next(self, box):
        """The session now runs the accepted value: tightened to full, then
        loosened back, is a loosening."""
        box.start()
        box.write(box.user, {"env": {SG: "full"}})
        assert box.change("user_settings") is None
        box.write(box.user, {})
        _blocked(box.change("user_settings"), f"env.{SG}")

    def test_a_refused_change_does_not_move_the_start(self, box):
        box.start()
        box.write(box.user, {"env": {MM: "1"}})
        _blocked(box.change("user_settings"))
        box.write(box.user, {"env": {MM: "1"}, "model": "opus"})
        _blocked(box.change("user_settings"), f"env.{MM}")


class TestSessionStartTakesTheSnapshot:
    def test_a_fresh_start_drops_a_pending_note(self, box):
        """Item 5: a new process loads the files, so an earlier refusal is moot."""
        ig = _integrity()
        ig.record_switch_pending(box.project, ["~/.claude/settings.json: disableAllHooks: true"])
        box.start()
        assert ig.take_switch_notice(box.project) is None

    def test_a_compaction_keeps_a_pending_note(self, box):
        ig = _integrity()
        box.start()
        ig.record_switch_pending(box.project, ["~/.claude/settings.json: disableAllHooks: true"])
        box.start(source="compact")
        assert ig.take_switch_notice(box.project)

    def test_the_snapshot_keeps_no_variable_outside_the_harness_namespace(self, box):
        """An env map can carry a credential: only ESPALIER_ names are kept."""
        box.write(box.user, {"env": {"SOME_API_TOKEN": "s3cr3t-value", SG: "full"}})
        box.start(live={SG: "full"})
        text = box.project.joinpath(*_integrity().SETTINGS_GATES_SNAPSHOT).read_text(encoding="utf-8")
        assert "s3cr3t" not in text and "SOME_API_TOKEN" not in text and SG in text, text
