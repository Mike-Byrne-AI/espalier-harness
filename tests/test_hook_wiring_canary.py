"""The user-scope canary that says so when an Espalier tree's own hooks did not load
(``scripts/hook_wiring_canary.py``).

Measured 2026-10-08: sessions launched in a Claude Code worktree of this repo ran
with no hooks, because the gitignored ``.claude/settings.json`` is not checked out
there and Claude Code reads it from the session's directory. The canary runs from
the operator's user settings, in every project, so two properties carry it: it is
loud inside an Espalier tree whose banner is unwired, and silent everywhere else.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = REPO_ROOT / "scripts" / "hook_wiring_canary.py"

if not _SCRIPT.is_file():
    pytest.skip("scripts/hook_wiring_canary.py is dev tooling not shipped in the sdist",
                allow_module_level=True)


def _load():
    spec = importlib.util.spec_from_file_location("_hook_wiring_canary", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_WIRED = {"hooks": {"SessionStart": [{"hooks": [{
    "type": "command", "command": "python",
    "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/session_start.py"],
}]}]}}


def _tree(root: Path) -> Path:
    hooks = root / "tools" / "cc" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "session_start.py").write_text("", encoding="utf-8")
    return root


def _settings(root: Path, data: dict) -> None:
    path = root / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _run(capsys, session_dir: Path) -> dict | None:
    assert _load().main("", {"CLAUDE_PROJECT_DIR": str(session_dir)}) == 0
    out = capsys.readouterr().out.strip()
    return json.loads(out) if out else None


class TestTheCanarySpeaksOnlyInsideAnUnwiredTree:
    """Earn-the-red: an Espalier tree with no settings speaks (mutation: treat an
    absent file as wired); a file without the banner's entry speaks (mutation:
    check presence only); a session started in a subdirectory speaks (mutation:
    look for the tree only at the session directory); every other project stays
    silent (mutation: speak whenever the settings file is absent); a tree wired
    through the local file is silent (mutation: read the shared file only); a
    stdin that cannot be read still checks (mutation: read stdin unguarded,
    which raises out of a hook that runs in every project)."""

    def test_an_espalier_tree_with_no_settings_tells_the_operator_and_claude(self, tmp_path, capsys):
        out = _run(capsys, _tree(tmp_path))
        assert out is not None
        assert "did NOT load" in out["systemMessage"]
        assert ".claude/settings.json" in out["systemMessage"]
        assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "make no edits" in out["hookSpecificOutput"]["additionalContext"]

    def test_a_wired_tree_is_silent(self, tmp_path, capsys):
        root = _tree(tmp_path)
        _settings(root, _WIRED)
        assert _run(capsys, root) is None

    def test_a_settings_file_without_the_banner_entry_speaks(self, tmp_path, capsys):
        root = _tree(tmp_path)
        _settings(root, {"permissions": {"allow": []}})
        out = _run(capsys, root)
        assert out is not None and "no SessionStart entry" in out["systemMessage"]

    def test_a_session_started_in_a_subdirectory_speaks(self, tmp_path, capsys):
        root = _tree(tmp_path)
        _settings(root, _WIRED)
        sub = root / "src"
        sub.mkdir()
        out = _run(capsys, sub)
        assert out is not None and "a subdirectory of the Espalier tree" in out["systemMessage"]

    def test_a_project_that_is_not_an_espalier_tree_is_silent(self, tmp_path, capsys):
        (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
        assert _run(capsys, tmp_path) is None

    def test_an_unreadable_settings_file_speaks(self, tmp_path, capsys):
        root = _tree(tmp_path)
        (root / ".claude").mkdir()
        (root / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
        out = _run(capsys, root)
        assert out is not None and "could not be read" in out["systemMessage"]

    def test_a_tree_wired_through_the_local_file_is_silent(self, tmp_path, capsys):
        root = _tree(tmp_path)
        _settings(root, {"permissions": {}})
        (root / ".claude" / "settings.local.json").write_text(json.dumps(_WIRED), encoding="utf-8")
        assert _run(capsys, root) is None

    def test_a_stdin_that_cannot_be_read_still_checks(self, tmp_path, capsys, monkeypatch):
        class _Closed:
            def read(self):
                raise ValueError("I/O operation on closed file")

        monkeypatch.setattr(sys, "stdin", _Closed())
        root = _tree(tmp_path)
        assert _load().main(None, {"CLAUDE_PROJECT_DIR": str(root)}) == 0
        assert "did NOT load" in capsys.readouterr().out

    def test_the_payload_cwd_is_read_when_the_project_variable_is_unset(self, tmp_path, capsys):
        root = _tree(tmp_path)
        assert _load().main(json.dumps({"cwd": str(root)}), {}) == 0
        out = capsys.readouterr().out
        assert "did NOT load" in out


class TestTheCanaryRunsInAnyProject:
    def test_it_imports_the_standard_library_only(self):
        """It runs from the operator's user settings in every project, so it can
        import nothing a project might lack."""
        tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
        assert names <= set(sys.stdlib_module_names) | {"__future__"}, names
