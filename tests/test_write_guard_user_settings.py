"""DEF-5112: write_guard refuses a Write or Edit of the user settings file
whose result turns ``disableAllHooks`` on or loosens a gate variable in its
``env`` map; every other edit of that file passes.

Why: the project and local settings files are a protected zone, refused
whole, while the user file (``~/.claude/settings.json``, or ``settings.json``
under ``CLAUDE_CONFIG_DIR``) sits in no zone. config_guard refuses the same
change at ConfigChange (DEF-3081), but that refusal leaves the file as written,
and every session on the machine launches from it next. Before this check a
Write setting ``disableAllHooks`` there drew the CP-GATEWEAKEN speed bump and
passed on its re-issue; an Edit, and an ``env`` map turning the maintenance
switch on, passed at once (read live at ``d6ff8d4``; operator call 5cf1dc,
ruled A in 54f420).

The judgment is config_guard's rule (``_integrity.gate_value_loosens``) at two
layers, against the files on disk now: the user file's own values (the file
reaches every repository, so a value a higher file in this one outranks is
judged all the same) and the session's (each key from the highest-precedence
file, else the launch environment's). Claude Code's own tools set the edges,
each driven on Claude Code 2.1.321 (2026-11-15) before it was pinned here: an
Edit with a non-unique ``old_string`` and no ``replace_all`` fails, and so does
an empty ``old_string`` on a file that exists; ``replace_all`` replaces every
match; an empty ``old_string`` on a missing file creates it from
``new_string``; NotebookEdit refuses any file that is not ``.ipynb``; a
settings file that is not strict JSON (a comment, a trailing comma, a cut) is
not loaded at all ("Invalid or malformed JSON", driven on a project's local
file). A shell write of the file is a declared limit: the operator ruled no
per-call weight for it, and a row below pins the pass.

Every row drives the source hook with a scratch home, project and config
directory, the gate variables and ``CLAUDE_CONFIG_DIR`` stripped from the
inherited environment unless the row sets them, and the record lands in the
scratch home's own audit directory.
"""
# slow-exempt: deployed-hook subprocesses over scratch trees, about 0.2 s each
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from tests._hook_runner import run_hook

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import write_guard  # noqa: E402

GATE_VARS = ("ESPALIER_MAINTENANCE_MODE", "ESPALIER_STOP_GATE", "ESPALIER_STOP_GATE_TEST_CMD")
MM, SG, CMD = GATE_VARS
WALL = "of the user settings file ("


class Box:
    """A scratch home, project and config directory; ``call`` runs write_guard
    on one tool call and returns ``(decision, reason)``, ``(None, "")`` for an
    allow."""

    def __init__(self, tmp: Path) -> None:
        self.home = tmp / "home"
        self.project = tmp / "proj"
        self.config = tmp / "cfg"
        for d in (self.home / ".claude", self.project / ".claude", self.config):
            d.mkdir(parents=True)
        self.user = self.config / "settings.json"
        self.audit = self.home / ".espalier" / "audit"

    def env(self, live: dict | None = None, *, config_dir: bool = True) -> dict:
        env: dict = {name: None for name in GATE_VARS}
        env.update(HOME=str(self.home), USERPROFILE=str(self.home), CLAUDE_PROJECT_DIR=str(self.project),
                   ESPALIER_AUDIT_DIR=None, CLAUDE_CONFIG_DIR=str(self.config) if config_dir else None)
        env.update(live or {})
        return env

    def write(self, path: Path, data: object) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else json.dumps(data, indent=2), encoding="utf-8")
        return path

    def call(self, tool: str, tool_input: dict, live: dict | None = None, *,
             config_dir: bool = True) -> tuple[str | None, str]:
        result = run_hook("write_guard.py", {"tool_name": tool, "tool_input": tool_input},
                          self.env(live, config_dir=config_dir))
        assert result.returncode == 0, result.stderr
        if not result.stdout.strip():
            return None, ""
        out = json.loads(result.stdout).get("hookSpecificOutput", {})
        return out.get("permissionDecision"), out.get("permissionDecisionReason", "")

    def writes(self, content: object, path: Path | None = None) -> dict:
        text = content if isinstance(content, str) else json.dumps(content)
        return {"file_path": str(path or self.user), "content": text}

    def audit_events(self) -> list[dict]:
        records = []
        for log in self.audit.glob("*.log"):
            records += [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
        return records


@pytest.fixture
def box(tmp_path: Path) -> Box:
    return Box(tmp_path)


def _walled(decision: tuple[str | None, str], *needles: str) -> None:
    verdict, reason = decision
    assert verdict == "deny" and WALL in reason, decision
    for needle in needles:
        assert needle in reason, (needle, reason)


def _passes(box: Box, tool: str, tool_input: dict, live: dict | None = None) -> None:
    """Allowed, or bumped once by a checkpoint and allowed on the re-issue:
    never the wall. CP-GATEWEAKEN bumps any Write or Edit of a settings.json
    whose text names disableAllHooks, the wall's twin for a call that passes."""
    first = box.call(tool, tool_input, live)
    assert WALL not in first[1], first
    if first[0] == "deny":
        second = box.call(tool, tool_input, live)
        assert second[0] != "deny", (first, second)


class TestAWriteThatSwitchesAGateOffIsRefused:
    def test_a_write_turning_disable_all_hooks_on_is_refused_and_its_reissue_too(self, box):
        """The row's first shape. Red at base: the bump fired once and the
        re-issue passed."""
        call = box.writes({"disableAllHooks": True})
        _walled(box.call("Write", call), "disableAllHooks: true", "$CLAUDE_CONFIG_DIR/settings.json")
        _walled(box.call("Write", call))
        assert not box.user.exists()

    def test_an_edit_turning_disable_all_hooks_on_is_refused(self, box):
        box.write(box.user, {"model": "x"})
        _walled(box.call("Edit", {"file_path": str(box.user), "old_string": '"model": "x"',
                                  "new_string": '"model": "x",\n  "disableAllHooks": true'}))

    def test_an_env_map_turning_the_maintenance_switch_on_is_refused(self, box):
        """The row's second shape. Red at base: a plain allow."""
        _walled(box.call("Write", box.writes({"env": {MM: "1"}})), f"env.{MM}", "(the file had unset)")

    def test_the_stop_gate_moved_off_full_in_the_file_is_refused(self, box):
        box.write(box.user, {"env": {SG: "full"}})
        _walled(box.call("Edit", {"file_path": str(box.user), "old_string": '"full"', "new_string": '"light"'}),
                f"env.{SG}")

    def test_the_test_command_changed_while_the_file_runs_full_is_refused(self, box):
        box.write(box.user, {"env": {SG: "full", CMD: "pytest -q"}})
        _walled(box.call("Write", box.writes({"env": {SG: "full", CMD: "true"}})), f"env.{CMD}")

    def test_a_switch_a_higher_file_outranks_here_is_refused_all_the_same(self, box):
        """The user file reaches every repository on the machine: a local file
        here setting disableAllHooks false hides the switch from this repo
        only (config_guard's merged read lets it through)."""
        box.write(box.project / ".claude" / "settings.local.json", {"disableAllHooks": False})
        _walled(box.call("Write", box.writes({"disableAllHooks": True})), "disableAllHooks: true")

    def test_a_file_value_outranking_a_stricter_launch_value_is_refused(self, box):
        """The session's layer: the stop gate runs full from the launch
        environment, and a value written into the user file outranks it."""
        _walled(box.call("Write", box.writes({"env": {SG: "light"}}), live={SG: "full"}),
                f"env.{SG}", '(the session runs "full")')

    def test_an_edit_creating_the_file_is_judged_on_its_whole_text(self, box):
        """An empty old_string on a missing file creates it from new_string
        (driven on 2.1.321), so new_string is the whole result."""
        _walled(box.call("Edit", {"file_path": str(box.user), "old_string": "",
                                  "new_string": json.dumps({"disableAllHooks": True})}))

    def test_replace_all_is_applied_to_every_match(self, box):
        """replace_all replaces every match (driven on 2.1.321); the same
        Edit without it names a non-unique string and fails, so it passes."""
        box.write(box.user, {"disableAllHooks": False, "includeCoAuthoredBy": False})
        edit = {"file_path": str(box.user), "old_string": "false", "new_string": "true"}
        _passes(box, "Edit", edit)
        _walled(box.call("Edit", {**edit, "replace_all": True}), "disableAllHooks: true")

    def test_an_edit_of_a_crlf_file_is_matched_as_claude_code_matches_it(self, box):
        """The Edit tool matches an old_string written with LF against a CRLF
        file (driven on 2.1.321), so a Windows-saved file is judged, not read
        as an Edit the tool would fail."""
        box.user.write_bytes(b'{\r\n  "model": "x",\r\n  "theme": "dark"\r\n}\r\n')
        _walled(box.call("Edit", {"file_path": str(box.user), "old_string": '"model": "x",\n  "theme": "dark"',
                                  "new_string": '"model": "x",\n  "disableAllHooks": true'}))

    def test_an_edit_of_a_file_holding_a_byte_that_does_not_decode_is_judged(self, box):
        """A stray byte is read with a replacement, as the JSON read of the same
        bytes is, so the two reads of one file agree."""
        box.user.write_bytes(b'{"theme": "caf\xe9", "model": "x"}')
        _walled(box.call("Edit", {"file_path": str(box.user), "old_string": '"model": "x"',
                                  "new_string": '"model": "x", "disableAllHooks": true'}))

    def test_maintenance_mode_does_not_lift_it(self, box):
        """The maintenance bypass is for harness self-edits; none writes a
        hooks-off switch into the user's own file."""
        _walled(box.call("Write", box.writes({"disableAllHooks": True}), live={MM: "1"}))

    def test_the_file_under_home_is_read_where_no_config_dir_is_set(self, box):
        user = box.home / ".claude" / "settings.json"
        decision = box.call("Write", box.writes({"disableAllHooks": True}, user), config_dir=False)
        _walled(decision, "~/.claude/settings.json")

    @pytest.mark.skipif(sys.platform == "win32", reason="a symlink needs a privilege on Windows")
    def test_a_write_through_a_link_to_the_file_is_refused(self, box, tmp_path):
        """A dotfiles checkout often links the file in: a write naming the
        link's target, or the link, rewrites the same bytes."""
        real = box.write(tmp_path / "dotfiles" / "claude-settings.json", {"model": "x"})
        box.user.symlink_to(real)
        _walled(box.call("Write", box.writes({"disableAllHooks": True}, real)))
        _walled(box.call("Write", box.writes({"disableAllHooks": True})))

    def test_the_refusal_is_recorded_by_label_never_the_home_path(self, box):
        box.call("Write", box.writes({"env": {MM: "1"}}))
        records = [r for r in box.audit_events() if r.get("event_type") == "pretooluse_blocked_kill_switch"]
        assert len(records) == 1, box.audit_events()
        details = records[0]["details"]
        assert details["kind"] == "user_settings_write" and details["tool"] == "Write", details
        assert details["file_path"] == "$CLAUDE_CONFIG_DIR/settings.json", details
        assert str(box.config) not in json.dumps(records[0]) and str(box.home) not in json.dumps(records[0])


class TestEveryOtherEditOfTheFilePasses:
    def test_an_edit_adding_another_setting_passes(self, box):
        box.write(box.user, {"model": "x"})
        _passes(box, "Write", box.writes({"model": "y", "env": {"OTHER": "1"}}))

    def test_a_switch_already_in_the_file_kept_passes(self, box):
        """A change is judged, not the file's state: a write that keeps a
        value the file already holds switches nothing off."""
        box.write(box.user, {"env": {MM: "1"}})
        _passes(box, "Write", box.writes({"env": {MM: "1"}, "model": "y"}))

    def test_a_tightening_passes(self, box):
        box.write(box.user, {"env": {SG: "light"}})
        _passes(box, "Edit", {"file_path": str(box.user), "old_string": '"light"', "new_string": '"full"'})

    def test_turning_disable_all_hooks_off_passes(self, box):
        box.write(box.user, {"disableAllHooks": True})
        _passes(box, "Edit", {"file_path": str(box.user), "old_string": "true", "new_string": "false"})

    @pytest.mark.parametrize("edit", [
        pytest.param({"old_string": "absent", "new_string": '"disableAllHooks": true'}, id="old-string-absent"),
        pytest.param({"old_string": "", "new_string": json.dumps({"disableAllHooks": True})}, id="empty-on-an-existing-file"),
    ])
    def test_an_edit_claude_code_fails_passes(self, box, edit):
        """Driven on 2.1.321: an Edit whose old_string is not in the file, and
        an empty old_string on a file that exists, fail and change nothing."""
        box.write(box.user, {"model": "x"})
        _passes(box, "Edit", {"file_path": str(box.user), **edit})

    @pytest.mark.parametrize("text", [
        pytest.param('{\n  // a note\n  "disableAllHooks": true,\n}\n', id="comment-and-trailing-comma"),
        pytest.param('{"disableAllHooks": true\n', id="cut"),
        pytest.param('["disableAllHooks"]', id="not-an-object"),
    ])
    def test_a_result_claude_code_would_not_load_passes(self, box, text):
        """A settings file that is not a strict JSON object is not loaded, so
        it sets nothing (driven on 2.1.321 for a project's local file)."""
        _passes(box, "Write", box.writes(text))

    def test_a_notebook_edit_naming_the_file_passes(self, box):
        """NotebookEdit refuses a file that is not .ipynb (driven on 2.1.321),
        so it never writes this one."""
        box.write(box.user, {"model": "x"})
        _passes(box, "NotebookEdit", {"notebook_path": str(box.user), "new_source": json.dumps({"disableAllHooks": True})})

    @pytest.mark.parametrize("live", [
        pytest.param({MM: "1"}, id="launched-in-maintenance"),
        pytest.param({SG: "full", CMD: "pytest -q"}, id="launched-with-the-stop-gate-full"),
    ])
    def test_an_ordinary_edit_passes_in_a_session_launched_with_a_gate_variable(self, box, live):
        """The session's layer reads the launch environment; an edit that sets
        no gate variable moves nothing there, however the session started."""
        box.write(box.user, {"model": "x"})
        _passes(box, "Edit", {"file_path": str(box.user), "old_string": '"model": "x"',
                              "new_string": '"model": "x",\n  "permissions": {"allow": ["Bash(ls:*)"]}'}, live)

    @pytest.mark.skipif(sys.platform == "win32" or getattr(os, "geteuid", lambda: 1)() == 0,
                        reason="a mode-000 file stays readable to root and on Windows")
    def test_a_create_edit_of_a_file_that_exists_but_cannot_be_read_passes(self, box):
        """An empty old_string on a file that exists fails in Claude Code
        (driven on 2.1.321), readable or not: it is never judged as a create."""
        box.write(box.user, {"model": "x"})
        box.user.chmod(0)
        try:
            _passes(box, "Edit", {"file_path": str(box.user), "old_string": "",
                                  "new_string": json.dumps({"disableAllHooks": True})})
        finally:
            box.user.chmod(0o600)

    def test_a_tilde_path_naming_no_known_user_passes_and_crashes_nothing(self, box):
        """``Path.expanduser`` raises on an unknown user; the check expands the
        way ``os.path.expanduser`` does, which leaves the path as it is."""
        assert box.call("Write", {"file_path": "~no-such-user-5112/notes.txt", "content": "x"}) == (None, "")

    def test_another_settings_file_outside_every_zone_passes(self, box, tmp_path):
        other = tmp_path / "elsewhere" / ".claude" / "settings.json"
        other.parent.mkdir(parents=True)
        _passes(box, "Write", box.writes({"env": {MM: "1"}}, other))


class TestAShellWriteOfTheFileIsADeclaredLimit:
    def test_a_shell_or_mcp_write_of_the_user_file_passes(self, box):
        """The operator's ruling (54f420): a shell write of the user file is a
        declared limit, its content unread, with no per-call weight; an MCP
        server's write is the same limit (its payload shape is the server's).
        A Bash redirect and a PowerShell Set-Content carrying the switch are
        each a plain allow, and an MCP write is never the wall (the MCP tier's
        speed bump may ask once); the row reds the day a reader closes any of
        them, so the HOOKS.md sentence that declares the limit is rewritten on
        purpose."""
        switch = json.dumps({"disableAllHooks": True})
        for tool, command in (("Bash", f"printf '%s' '{switch}' > '{box.user}'"),
                              ("PowerShell", f"Set-Content -Path '{box.user}' -Value '{switch}'")):
            assert box.call(tool, {"command": command}) == (None, ""), (tool, command)
        _passes(box, "mcp__filesystem__write_file", {"path": str(box.user), "content": switch})
        assert not box.user.exists()  # the hook judged each call; nothing ran it


class TestNoShellCallPaysForIt:
    def test_a_shell_call_or_a_read_never_locates_the_user_file(self, box, monkeypatch):
        """The ruling's cost bound, read in-process: the check tests the tool
        name before anything else, so a Bash call, a PowerShell call or a read
        pays no stat and no read for it; a Write elsewhere locates the file."""
        calls: list = []
        monkeypatch.setattr(write_guard._integrity, "user_settings_path", lambda: calls.append(1) or box.user)
        for tool, tool_input in (("Bash", {"command": "true"}), ("PowerShell", {"command": "Get-Date"}),
                                 ("Read", {"file_path": str(box.user)})):
            assert write_guard.check_user_settings_write(tool, tool_input, box.project) == 0, tool
        assert calls == [], calls
        other = str(box.project / "notes.json")
        assert write_guard.check_user_settings_write("Write", {"file_path": other, "content": "{}"}, box.project) == 0
        assert calls == [1], calls
