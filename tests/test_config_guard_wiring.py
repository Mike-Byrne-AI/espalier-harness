"""TP-476 wave A-0: config_guard refuses a project settings change that leaves
a deployed governance gate unwired, or deletes the file.

Why: 0-E (2026-10-08, Claude Code 2.1.294) drove a mid-session edit that removed
``.claude/settings.json``'s ``hooks`` key, and one that deleted the file. Each
switched every hook off at once (6/6 runs), ConfigChange fired for both, and a
ConfigChange deny kept the hooks for the session (7/7). The deny itself is
silent by protocol and leaves the file as written; doctor and the next
SessionStart name the restore route.

The six earn-the-red rows are the pack's, each named with the mutation it
was seen red against. The recorded-write rows keep DEF-1060's in-session
uninstall working: ``espalier clean-generated`` unwires in one run and deletes
the scripts in the next, which only works if the unwire is let through.
"""
# slow-exempt: eleven deployed-hook subprocesses over scratch trees, measured 2.7 s on Windows
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from tests._interpreter_hosts import HOOK_PYTHON

ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = ROOT / "tools" / "cc" / "hooks"
GATES = ("write_guard.py", "plan_guard.py", "config_guard.py", "stop_gate.py")


def _integrity():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_integrity_a0", HOOKS_DIR / "_integrity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _hook(script: str, *, command: str = "python", lead: tuple[str, ...] = ()) -> dict:
    return {"type": "command", "command": command,
            "args": [*lead, f"${{CLAUDE_PROJECT_DIR}}/tools/cc/hooks/{script}"]}


def _settings(make=_hook) -> dict:
    """The four blocking gates wired under their events, each entry built by ``make``."""
    return {"permissions": {"allow": []}, "hooks": {
        "PreToolUse": [
            {"matcher": "*", "hooks": [make("write_guard.py")]},
            {"matcher": "Write|Edit|NotebookEdit", "hooks": [make("plan_guard.py")]},
        ],
        "ConfigChange": [{"hooks": [make("config_guard.py")]}],
        "Stop": [{"hooks": [make("stop_gate.py")]}],
    }}


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """An Espalier tree: the four gate files on disk and a wired project file."""
    hooks = tmp_path / "tools" / "cc" / "hooks"
    hooks.mkdir(parents=True)
    for script in GATES:
        (hooks / script).write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    _write(tmp_path, _settings())
    return tmp_path


def _write(root: Path, data: object, name: str = "settings.json") -> Path:
    path = root / ".claude" / name
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _change(root: Path, name: str = "settings.json", source: str = "project_settings") -> dict | None:
    """Run config_guard on a ConfigChange for ``.claude/<name>``; the decision JSON, or None for allow."""
    result = subprocess.run(
        [HOOK_PYTHON, str(HOOKS_DIR / "config_guard.py")],
        input=json.dumps({"hook_event_name": "ConfigChange", "source": source,
                          "file_path": str(root / ".claude" / name)}),
        capture_output=True, text=True, timeout=30, encoding="utf-8",
        env={**_clean_env(), "CLAUDE_PROJECT_DIR": str(root)},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None


def _clean_env() -> dict:
    import os
    return {k: v for k, v in os.environ.items() if k != "ESPALIER_MAINTENANCE_MODE"}


def _denied_naming(decision: dict | None, scripts) -> None:
    assert decision is not None and decision.get("decision") == "block", decision
    for script in scripts:
        assert script in decision["reason"], (script, decision["reason"])


class TestTheWiringIsCheckedWhereSettingsChange:
    def test_removing_the_hooks_key_is_denied_naming_the_gates(self, tree):
        """Earn-the-red 1. Mutation: keep only the kill-switch shapes (today's predicate)."""
        data = _settings()
        del data["hooks"]
        _write(tree, data)
        _denied_naming(_change(tree), GATES)

    def test_deleting_the_file_on_an_espalier_tree_is_denied(self, tree):
        """Earn-the-red 2. Mutation: skip a missing file (today's behaviour)."""
        (tree / ".claude" / "settings.json").unlink()
        _denied_naming(_change(tree), GATES)

    def test_deleting_the_file_where_no_hook_is_deployed_is_allowed(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        assert _change(tmp_path) is None

    def test_a_launcher_wired_file_and_the_host_init_file_pass(self, tree):
        """Earn-the-red 3. Mutation: match each hook against one hardcoded
        interpreter word. The fixture uses the Windows launcher with its version
        flag, never the default word, or the mutation stays green."""
        _write(tree, _settings(lambda s: _hook(s, command="py", lead=("-3",))))
        assert _change(tree) is None
        from espalier.cli import _build_settings_json
        _write(tree, _build_settings_json())
        assert _change(tree) is None

    def test_the_harness_commands_plus_an_adopters_own_hooks_pass(self, tree):
        """Earn-the-red 4. Mutation: require an exact list."""
        data = _settings()
        data["hooks"]["PostToolUse"] = [
            {"matcher": "Write", "hooks": [
                {"type": "command", "command": "python", "args": ["scripts/format_check.py"]},
                {"type": "command", "command": "npm", "args": ["run", "lint"]},
            ]},
        ]
        data["hooks"]["PreToolUse"].append(
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "python", "args": ["scripts/audit.py"]}]})
        _write(tree, data)
        assert _change(tree) is None

    def test_an_entry_that_only_mentions_the_hook_path_is_denied(self, tree):
        """Earn-the-red 5. Mutation: a substring match, the false green
        ``cli._settings_has_espalier_hooks``' docstring records."""
        _write(tree, _settings(lambda s: {"type": "command", "command": "echo",
                                          "args": [f"tools/cc/hooks/{s}"]}))
        _denied_naming(_change(tree), GATES)

    def test_a_local_file_with_no_hooks_key_is_not_denied(self, tree):
        """Earn-the-red 6. Mutation: apply the wiring check to every settings
        file, not the project file only."""
        _write(tree, {"permissions": {"allow": ["Bash(ls:*)"]}}, "settings.local.json")
        assert _change(tree, "settings.local.json", "local_settings") is None
        # Nor while a refused project change is outstanding: a local change is
        # never judged in the project file's place.
        _started(tree)
        (tree / ".claude" / "settings.json").unlink()
        assert _change(tree) is not None
        assert _change(tree, "settings.local.json", "local_settings") is None

    def test_an_emptied_or_unparseable_project_file_wires_nothing(self, tree):
        """Driven 2026-10-08 (Claude Code 2.1.295): an emptied file and a
        syntax-broken one each dropped every hook mid-session, so each is
        judged as a file that wires nothing. Refusing it blocks no repair: the
        next change is judged on its own content. Mutation: keep the
        kill-switch scan's leave-it-editable fail-open for an unparseable file."""
        ig = _integrity()
        _started(tree)
        (tree / ".claude" / "settings.json").write_text('{"hooks": {"Stop": [', encoding="utf-8")
        _denied_naming(_change(tree), GATES)
        notice = ig.take_unwired_notice(tree)
        assert notice and "unreadable as JSON" in notice and "repair the file's JSON" in notice, notice
        (tree / ".claude" / "settings.json").write_text("", encoding="utf-8")
        _denied_naming(_change(tree), GATES)
        _write(tree, _settings())  # the repair
        assert _change(tree) is None


class TestARecordedHarnessWriteIsLetThrough:
    """DEF-1060's in-session uninstall: the unwire is let through when the
    harness writer recorded writing exactly this content, a moment ago."""

    @staticmethod
    def _unwired(tree: Path) -> dict:
        data = _settings()
        del data["hooks"]
        _write(tree, data)
        return data

    @staticmethod
    def _record(tree: Path, data: object, *, age: float = 0.0, writer: str = "espalier clean-generated") -> None:
        ig = _integrity()
        path = tree.joinpath(*ig.SETTINGS_WRITE_RECORD)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"writer": writer, "sha256": ig.settings_content_digest(data),
                                    "written_at": time.time() - age}), encoding="utf-8")

    def test_a_fresh_record_of_this_content_allows_the_unwire(self, tree):
        data = self._unwired(tree)
        self._record(tree, data)
        assert _change(tree) is None

    def test_a_record_of_other_content_does_not(self, tree):
        self._unwired(tree)
        self._record(tree, _settings())
        _denied_naming(_change(tree), GATES)

    def test_a_stale_record_does_not(self, tree):
        data = self._unwired(tree)
        self._record(tree, data, age=3600)
        _denied_naming(_change(tree), GATES)

    def test_a_record_dated_in_the_future_does_not(self, tree):
        data = self._unwired(tree)
        self._record(tree, data, age=-3600)
        _denied_naming(_change(tree), GATES)

    def test_a_record_naming_another_writer_does_not(self, tree):
        data = self._unwired(tree)
        self._record(tree, data, writer="a session that wanted the hooks off")
        _denied_naming(_change(tree), GATES)

    def test_the_digest_ignores_layout_and_byte_order_mark(self):
        ig = _integrity()
        data = {"b": [1, {"c": "x"}], "a": None}
        compact = json.dumps(data, separators=(",", ":")).encode("utf-8")
        crlf_bom = b"\xef\xbb\xbf" + json.dumps(data, indent=4).replace("\n", "\r\n").encode("utf-8")
        assert ig.settings_content_digest(ig.load_json_dict_safe(compact, default=None)) == \
            ig.settings_content_digest(ig.load_json_dict_safe(crlf_bom, default=None)) == \
            ig.settings_content_digest(data)



def _session_start():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_session_start_a0", HOOKS_DIR / "session_start.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _started(root: Path, source: str = "startup") -> None:
    """What SessionStart records: the gates the session starts with."""
    _session_start()._record_wired_gates(root, source)


class TestTheChangeIsJudgedNotTheState:
    """The review's REGRESSION (both reviewers): judging the file's state
    refused every project-settings edit on a tree already partly unwired, or
    wired in the pre-v0.6.5 shell form the exec-form reader cannot prove (which
    `upgrade`'s plain merge leaves in place), for gates never live to lose. So a
    CHANGE is judged against the gates the session started with. Mutation:
    judge every deployed gate (ignore the snapshot), and the first row reds."""

    @staticmethod
    def _without_plan_guard(tree: Path) -> dict:
        data = _settings()
        del data["hooks"]["PreToolUse"][1]
        _write(tree, data)
        return data

    def test_a_tree_already_missing_a_gate_keeps_its_other_edits(self, tree):
        data = self._without_plan_guard(tree)
        _started(tree)
        data["permissions"] = {"allow": ["Bash(ls:*)"]}
        _write(tree, data)
        assert _change(tree) is None

    def test_it_still_refuses_losing_the_gates_it_was_running(self, tree):
        data = self._without_plan_guard(tree)
        _started(tree)
        del data["hooks"]
        _write(tree, data)
        decision = _change(tree)
        _denied_naming(decision, ("write_guard.py", "config_guard.py", "stop_gate.py"))
        assert "plan_guard.py" not in decision["reason"], "never live, so not this change's to lose"

    def test_a_shell_form_tree_is_a_declared_limit(self, tree):
        """Its gates most likely fire but cannot be proven, so the session
        starts with none on record and the change test stays quiet, a removal
        included. doctor and the SessionStart line name the shell form."""
        _write(tree, _settings(lambda s: {
            "type": "command", "command": f"python ${{CLAUDE_PROJECT_DIR}}/tools/cc/hooks/{s}"}))
        _started(tree)
        assert _integrity().read_wired_gates(tree) == []
        _write(tree, {"permissions": {}})
        assert _change(tree) is None

    def test_an_http_hook_added_to_a_wired_tree_passes(self, tree):
        """The voiding rule shared with ci_guard and doctor predates the hook
        types the pinned protocol names beside command and prompt (its own
        ledger row); such an entry runs no gate, so the live check sets it aside."""
        _started(tree)
        data = _settings()
        data["hooks"]["PostToolUse"] = [{"hooks": [{"type": "http", "url": "http://localhost:9/x"}]}]
        _write(tree, data)
        assert _change(tree) is None
        assert sorted(_integrity().read_wired_gates(tree)) == sorted(GATES)

    def test_an_allowed_change_becomes_the_sessions_and_a_refusal_is_noted_once(self, tree):
        ig = _integrity()
        data = self._without_plan_guard(tree)
        _started(tree)
        _write(tree, _settings())  # plan_guard wired back: allowed, and now the session's
        assert _change(tree) is None
        assert sorted(ig.read_wired_gates(tree)) == sorted(GATES)
        (tree / ".claude" / "settings.json").unlink()
        _denied_naming(_change(tree), GATES)
        notice = ig.take_unwired_notice(tree)
        assert notice and "deleted the file" in notice and "espalier init ." in notice, notice
        assert notice.isascii()
        assert ig.take_unwired_notice(tree) is None, "told once"
        _write(tree, _settings())
        assert _change(tree) is None
        assert not tree.joinpath(*ig.UNWIRED_PENDING).exists(), "a rewire clears the note"

    def test_a_payload_without_a_path_is_judged_by_its_source(self, tree):
        data = _settings()
        del data["hooks"]
        _write(tree, data)
        result = subprocess.run(
            [HOOK_PYTHON, str(HOOKS_DIR / "config_guard.py")],
            input=json.dumps({"hook_event_name": "ConfigChange", "source": "project_settings"}),
            capture_output=True, text=True, timeout=30, encoding="utf-8",
            env={**_clean_env(), "CLAUDE_PROJECT_DIR": str(tree)},
        )
        _denied_naming(json.loads(result.stdout), GATES)

    def test_a_settings_file_symlinked_out_of_the_repo_is_judged(self, tree, tmp_path_factory):
        outside = tmp_path_factory.mktemp("dotfiles") / "settings.json"
        data = _settings()
        del data["hooks"]
        outside.write_text(json.dumps(data), encoding="utf-8")
        link = tree / ".claude" / "settings.json"
        link.unlink()
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("this host cannot create a symlink")
        _denied_naming(_change(tree), GATES)

    def test_a_compaction_keeps_the_snapshot_and_the_note(self, tree):
        """A clear or compact keeps the hooks already loaded, which a refusal
        may have left different from the file: neither rewrites the record."""
        ig = _integrity()
        _started(tree)
        (tree / ".claude" / "settings.json").unlink()
        _denied_naming(_change(tree), GATES)
        _started(tree, "compact")
        assert sorted(ig.read_wired_gates(tree)) == sorted(GATES)
        assert tree.joinpath(*ig.UNWIRED_PENDING).exists()
        _started(tree, "startup")  # a new process loads the file as it is
        assert ig.read_wired_gates(tree) == []
        assert not tree.joinpath(*ig.UNWIRED_PENDING).exists()



class TestTheRefusalIsTold:
    """The ConfigChange refusal reaches no one (the protocol pin), so the note
    config_guard leaves is told beside the next tool result, once. Mutation:
    drop the notice from post_write_check, and the first assertion reds."""

    @staticmethod
    def _post_tool_use(root: Path) -> str:
        result = subprocess.run(
            [HOOK_PYTHON, str(HOOKS_DIR / "post_write_check.py")],
            input=json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                              "tool_input": {"command": "echo hi"}, "tool_response": {}}),
            capture_output=True, text=True, timeout=30, encoding="utf-8",
            env={**_clean_env(), "CLAUDE_PROJECT_DIR": str(root)},
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    def test_the_next_tool_result_carries_the_note_once(self, tree):
        _integrity().record_unwired_pending(tree, ["stop_gate.py", "write_guard.py"], kind="unwired")
        first = self._post_tool_use(tree)
        assert "left these governance gates unwired: stop_gate.py, write_guard.py" in first, first
        assert "espalier merge-settings --repair" in first
        assert "left these governance gates unwired" not in self._post_tool_use(tree)
