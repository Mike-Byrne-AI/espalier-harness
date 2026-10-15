"""The sandbox posture (TP-476 Wave B-1): ``init`` and ``upgrade`` print, and
on ``--sandbox-posture`` write, Claude Code's ``sandbox.filesystem`` deny
lists for the harness zones and the secret paths; ``doctor`` says which of
three states the tree is in.

Why these pins exist. The lists are DERIVED, never copied: ``denyWrite`` from
the engine's protected-zone roster plus the adopter's ``protected_paths``,
``denyRead`` parsed out of the deployed ``write_guard.py``'s secret roster.
A hand copy drifts the day a roster moves, so the derivation tests change a
roster and watch the entries follow. ``sandbox.enabled`` is never written,
because turning the sandbox on changes the adopter's network and approval
behaviour; a test guards that the flag writes the lists alone. Measured
2026-10-09 (the pack's 0-C, macOS Seatbelt): ``denyWrite`` holds for shell
writes and ``git checkout`` and NOT for the ``Write`` tool, so the posture is
a shell layer beside ``write_guard``, and doctor's line says so. On native
Windows there is no sandbox at all, which is the first of doctor's states.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import pytest

from espalier import sandbox_posture as sp
from espalier.cli import cmd_init, merge_hooks_into_settings
from espalier.doctor import run_doctor_check

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_GUARD = REPO_ROOT / "tools" / "cc" / "hooks" / "write_guard.py"


def _roster_source(tmp_path: Path, labels: dict[str, str], name: str = "write_guard.py") -> Path:
    """A write_guard-shaped module holding only the roster the parser reads."""
    body = "_SECRET_PATH_LABEL = " + json.dumps(labels, indent=4) + "\n"
    path = tmp_path / name
    path.write_bytes(("'''a copy of the guard for the derivation test'''\n" + body).encode())
    return path


class TestTheDenyReadDerivation:
    """``denyRead`` follows the deployed guard's ``_SECRET_PATH_LABEL``: a
    label with two spellings split on ``' / '``, each spelling written at the
    project root and anywhere below it (the guard matches a dotenv by name
    wherever it sits, and whether ``**/`` matches zero directories is not in
    the docs). Parsed by AST so the engine never imports the hook."""

    def test_the_live_guards_roster_yields_a_root_and_an_anywhere_glob_per_spelling(self):
        entries = sp.deny_read_entries(LIVE_GUARD)
        assert "./.env" in entries and "./**/.env" in entries, entries
        assert "./.env.*" in entries and "./**/.env.*" in entries, entries
        assert all(e.startswith("./") for e in entries), entries
        assert len(entries) == len(set(entries)) and len(entries) % 2 == 0

    def test_removing_a_roster_key_removes_its_entries(self, tmp_path):
        full = _roster_source(tmp_path, {"env": ".env / .env.*", "secrets": "secrets/**"})
        assert sp.deny_read_entries(full) == [
            "./.env", "./**/.env", "./.env.*", "./**/.env.*", "./secrets/**", "./**/secrets/**",
        ]
        trimmed = _roster_source(tmp_path, {"secrets": "secrets/**"}, name="trimmed.py")
        assert sp.deny_read_entries(trimmed) == ["./secrets/**", "./**/secrets/**"]

    def test_adding_a_roster_key_adds_its_entries_and_an_anywhere_spelling_is_not_doubled(self, tmp_path):
        wider = _roster_source(tmp_path, {"env": ".env", "tokens": "**/token.json"})
        assert sp.deny_read_entries(wider) == ["./.env", "./**/.env", "./token.json", "./**/token.json"]

    def test_a_source_without_the_roster_is_refused_by_name(self, tmp_path):
        bare = tmp_path / "write_guard.py"
        bare.write_bytes(b"X = 1\n")
        with pytest.raises(ValueError, match="_SECRET_PATH_LABEL"):
            sp.deny_read_entries(bare)

    def test_the_deployed_copy_wins_over_the_engines_vendored_one(self, tmp_path):
        """An adopter's tree runs the guard it deployed; a tree without one
        (a fresh init) reads the engine's vendored source."""
        hooks = tmp_path / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True)
        _roster_source(hooks, {"only": "only.txt"})
        assert sp.write_guard_source(tmp_path) == hooks / "write_guard.py"
        assert sp.deny_read_entries(root=tmp_path) == ["./only.txt", "./**/only.txt"]
        vendored = sp.write_guard_source(tmp_path / "elsewhere")
        assert vendored.is_file() and "_vendor" in vendored.parts


class TestTheDenyWriteDerivation:
    """``denyWrite`` follows the engine's zone roster: the protected prefixes
    (``espalier/`` only on the self-host tree), the exact protected files not
    under a prefix, then the adopter's ``protected_paths``. ``cc/`` is left
    to ``write_guard``, whose carve-outs (the plan, the blueprints, the
    working summary) the harness's own shell commands write into and the
    sandbox cannot express; no entry carries a wildcard, because Linux and
    WSL2 skip a ``denyWrite`` entry that holds one."""

    def test_an_adopter_tree_gets_the_zones_the_files_and_its_own_paths(self, tmp_path):
        entries = sp.deny_write_entries(tmp_path, self_host=False, protected_paths=["data/", "models"])
        assert "./tools/cc" in entries and "./.github/workflows" in entries, entries
        assert "./.claude/settings.json" in entries and "./.espalier/integrity.json" in entries
        assert entries[-2:] == ["./data", "./models"]
        assert "./espalier" not in entries
        assert "./cc" not in entries and "cc/" in sp.HOOK_KEPT_ZONES

    def test_the_self_host_tree_adds_its_engine_source(self, tmp_path):
        assert "./espalier" in sp.deny_write_entries(tmp_path, self_host=True, protected_paths=[])

    def test_the_self_host_switch_is_read_from_the_tree_by_default(self, tmp_path):
        """A scratch directory is nobody's self-host tree."""
        assert "./espalier" not in sp.deny_write_entries(tmp_path, protected_paths=[])

    def test_no_deny_write_entry_carries_a_wildcard_or_climbs(self, tmp_path):
        entries = sp.deny_write_entries(tmp_path, self_host=True, protected_paths=["a/*", "../b", "/abs", "ok/"])
        assert all(not any(ch in e for ch in "*?[") for e in entries), entries
        assert all(not e.startswith(("./../", "/")) for e in entries), entries
        assert "./ok" in entries and not any("abs" in e or "a/" in e for e in entries)

    def test_a_file_under_a_denied_prefix_is_not_repeated(self, tmp_path):
        entries = sp.deny_write_entries(tmp_path, self_host=False, protected_paths=[])
        assert not any(e.startswith("./tools/cc/") for e in entries), entries
        assert "./.github/workflows/harness-guard.yml" not in entries


class TestTheMergeKeepsTheOperatorsKeys:
    def test_missing_entries_are_appended_and_nothing_else_moves(self):
        existing = {"sandbox": {"enabled": True, "filesystem": {"denyWrite": ["~/x"], "allowWrite": ["/tmp/b"]}}}
        posture = {"denyWrite": ["./tools/cc", "~/x"], "denyRead": ["./.env"]}
        added = sp.merge_posture(existing, posture)
        assert added == ["denyWrite ./tools/cc", "denyRead ./.env"]
        fs = existing["sandbox"]["filesystem"]
        assert fs["denyWrite"] == ["~/x", "./tools/cc"] and fs["denyRead"] == ["./.env"]
        assert fs["allowWrite"] == ["/tmp/b"] and existing["sandbox"]["enabled"] is True

    def test_a_second_merge_adds_nothing(self):
        existing: dict = {}
        posture = {"denyWrite": ["./tools/cc"], "denyRead": ["./.env"]}
        assert sp.merge_posture(existing, posture)
        assert sp.merge_posture(existing, posture) == []
        assert "enabled" not in existing["sandbox"]

    def test_the_merge_function_takes_the_posture_on_an_existing_wired_file(self, tmp_path):
        """``upgrade --execute --sandbox-posture`` and ``init --wire-hooks
        --sandbox-posture`` go through the one merge path, so the backup and
        the refusals hold for the posture too."""
        claude = tmp_path / ".claude"
        claude.mkdir()
        (tmp_path / ".git").mkdir()
        settings = claude / "settings.json"
        settings.write_text(json.dumps({"permissions": {"allow": ["Read"]}, "sandbox": {"enabled": False}}),
                            encoding="utf-8")
        posture = {"denyWrite": ["./tools/cc"], "denyRead": ["./.env"]}
        result = merge_hooks_into_settings(settings, repo_root=tmp_path, sandbox_posture=posture)
        assert result.status in ("wired", "already"), result
        body = json.loads(settings.read_text(encoding="utf-8"))
        assert body["sandbox"]["filesystem"] == posture
        assert body["sandbox"]["enabled"] is False and body["permissions"]["allow"] == ["Read"]


    def test_a_fully_wired_file_lacking_only_the_posture_is_still_written(self, tmp_path):
        """The merge's idempotence gate (every event wired, nothing to append)
        used to be the only reason to write; the posture is a second one, so a
        wired install that opts in later gets the lists, and a second run on
        the same file writes nothing (no .bak churn)."""
        from espalier.cli import MERGE_ALREADY, MERGE_WIRED, fresh_settings

        (tmp_path / ".git").mkdir()
        claude = tmp_path / ".claude"
        claude.mkdir()
        settings = claude / "settings.json"
        settings.write_text(json.dumps(fresh_settings(tmp_path, "workflow")), encoding="utf-8")
        assert merge_hooks_into_settings(settings, repo_root=tmp_path).status == MERGE_ALREADY
        posture = {"denyWrite": ["./tools/cc"], "denyRead": ["./.env"]}
        first = merge_hooks_into_settings(settings, repo_root=tmp_path, sandbox_posture=posture)
        assert first.status == MERGE_WIRED and first.posture_added == ("denyWrite ./tools/cc", "denyRead ./.env")
        assert first.event_count == 0
        second = merge_hooks_into_settings(settings, repo_root=tmp_path, sandbox_posture=posture)
        assert second.status == MERGE_ALREADY and second.posture_added == ()
        body = json.loads(settings.read_text(encoding="utf-8"))
        assert body["sandbox"]["filesystem"] == posture and "enabled" not in body["sandbox"]


class TestInitWritesThePostureOnlyOnTheFlag:
    def _make_repo(self, tmp_path: Path) -> Path:
        (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-app"\n', encoding="utf-8")
        (tmp_path / ".git").mkdir(exist_ok=True)
        return tmp_path

    def _run_init(self, repo: Path, **overrides) -> int:
        return cmd_init(argparse.Namespace(repo=str(repo), config=None, **overrides))

    def test_without_the_flag_no_sandbox_key_is_written_and_the_posture_is_printed(self, tmp_path, capsys):
        repo = self._make_repo(tmp_path)
        assert self._run_init(repo) == 0
        body = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
        assert "sandbox" not in body
        out = capsys.readouterr().out
        assert "sandbox posture" in out and sp.FLAG in out and "./tools/cc" in out

    def test_with_the_flag_the_two_lists_are_written_and_enabled_is_not(self, tmp_path, capsys):
        repo = self._make_repo(tmp_path)
        assert self._run_init(repo, sandbox_posture=True) == 0
        body = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
        fs = body["sandbox"]["filesystem"]
        assert fs["denyWrite"] == sp.deny_write_entries(repo)
        assert fs["denyRead"] == sp.deny_read_entries(root=repo)
        assert "enabled" not in body["sandbox"]
        assert "written" in capsys.readouterr().out

    def test_the_flag_merges_into_a_preserved_settings_file_with_wire_hooks(self, tmp_path):
        repo = self._make_repo(tmp_path)
        claude = repo / ".claude"
        claude.mkdir()
        (claude / "settings.json").write_text(
            json.dumps({"permissions": {"allow": ["Read"]}, "sandbox": {"filesystem": {"denyWrite": ["~/mine"]}}}),
            encoding="utf-8")
        assert self._run_init(repo, wire_hooks=True, sandbox_posture=True) == 0
        body = json.loads((claude / "settings.json").read_text(encoding="utf-8"))
        assert body["sandbox"]["filesystem"]["denyWrite"][0] == "~/mine"
        assert "./tools/cc" in body["sandbox"]["filesystem"]["denyWrite"]
        assert body["permissions"]["allow"][0] == "Read" and "enabled" not in body["sandbox"]


class TestDoctorsThreeStates:
    """No sandbox on native Windows; off (the default); on. The user-scope
    ``allowUnsandboxedCommands`` is read from the config directory the
    environment names, never the real home, and is never written."""

    def _settings(self, repo: Path, body: dict, name: str = "settings.json") -> None:
        (repo / ".claude").mkdir(exist_ok=True)
        (repo / ".claude" / name).write_text(json.dumps(body), encoding="utf-8")

    def _user(self, tmp_path: Path, monkeypatch, body: dict | None) -> Path:
        home = tmp_path / "config-dir"
        home.mkdir()
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
        if body is not None:
            (home / "settings.json").write_text(json.dumps(body), encoding="utf-8")
        return home

    def test_native_windows_has_no_sandbox_and_names_the_location_layer(self, tmp_path, monkeypatch):
        self._user(tmp_path, monkeypatch, None)
        state = sp.read_state(tmp_path, posture={"denyWrite": [], "denyRead": []}, host_is_windows=True)
        assert state.supported is False
        info, warnings = sp.doctor_lines(state)
        assert warnings == [] and len(info) == 1
        assert "native Windows" in info[0] and "WSL2" in info[0] and "write_guard" in info[0]

    def test_off_names_the_missing_entries_and_the_flag(self, tmp_path, monkeypatch):
        self._user(tmp_path, monkeypatch, None)
        posture = {"denyWrite": ["./tools/cc"], "denyRead": ["./.env"]}
        state = sp.read_state(tmp_path, posture=posture, host_is_windows=False)
        assert state.supported and not state.enabled
        assert state.missing == posture and state.present == {"denyWrite": [], "denyRead": []}
        info, warnings = sp.doctor_lines(state)
        assert warnings == []
        assert any("sandbox: off" in line and sp.FLAG in line for line in info), info
        assert any("shell layer" in line and "Write, Edit and NotebookEdit" in line for line in info), info

    def test_on_with_the_posture_present_is_reported_whole(self, tmp_path, monkeypatch):
        self._user(tmp_path, monkeypatch, {"sandbox": {"allowUnsandboxedCommands": False}})
        posture = {"denyWrite": ["./tools/cc"], "denyRead": ["./.env"]}
        self._settings(tmp_path, {"sandbox": {"enabled": True, "filesystem": posture}})
        state = sp.read_state(tmp_path, posture=posture, host_is_windows=False)
        assert state.enabled and state.source == ".claude/settings.json"
        assert state.present == posture and state.missing == {"denyWrite": [], "denyRead": []}
        assert state.user_retry is False
        info, warnings = sp.doctor_lines(state)
        assert warnings == []
        assert any("sandbox: on" in line and "all 2 posture entries present" in line for line in info), info
        assert any("allowUnsandboxedCommands" in line and "holds" in line for line in info), info

    def test_on_with_entries_missing_is_a_warning_and_the_local_file_wins(self, tmp_path, monkeypatch):
        self._user(tmp_path, monkeypatch, {"sandbox": {"allowUnsandboxedCommands": True}})
        posture = {"denyWrite": ["./tools/cc", "./.github/workflows"], "denyRead": ["./.env"]}
        self._settings(tmp_path, {"sandbox": {"enabled": False}})
        self._settings(tmp_path, {"sandbox": {"enabled": True, "filesystem": {"denyRead": ["./.env"]}}},
                       name="settings.local.json")
        state = sp.read_state(tmp_path, posture=posture, host_is_windows=False)
        assert state.enabled and state.source == ".claude/settings.local.json"
        assert state.missing == {"denyWrite": ["./tools/cc", "./.github/workflows"], "denyRead": []}
        info, warnings = sp.doctor_lines(state)
        assert len(warnings) == 1 and "2 posture entries missing" in warnings[0] and sp.FLAG in warnings[0]
        assert any("allowUnsandboxedCommands" in line and "never writes" in line for line in info), info

    def test_an_unreadable_user_file_is_reported_not_raised(self, tmp_path, monkeypatch):
        home = self._user(tmp_path, monkeypatch, None)
        (home / "settings.json").write_bytes(b"{not json")
        state = sp.read_state(tmp_path, posture={"denyWrite": [], "denyRead": []}, host_is_windows=False)
        assert state.user_retry is None
        info, _ = sp.doctor_lines(state)
        assert any("could not be read" in line for line in info), info

    def test_doctor_carries_the_lines_through_its_host_seam(self, harness_repo, monkeypatch, tmp_path):
        from espalier import doctor as doctor_module

        self._user(tmp_path, monkeypatch, None)
        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: True)
        report = run_doctor_check(harness_repo, skip_self_host=True)
        assert any(line.startswith("sandbox: none on native Windows") for line in report["info"]), report["info"]
        # The fixture's guard is a stub with no roster; the deployed guard an
        # adopter runs is the real one, so give the tree that one.
        guard = harness_repo / "tools" / "cc" / "hooks" / "write_guard.py"
        guard.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(LIVE_GUARD, guard)
        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: False)
        report = run_doctor_check(harness_repo, skip_self_host=True)
        assert any(line.startswith("sandbox: off") for line in report["info"]), report["info"]

    def test_a_guard_without_the_roster_is_a_named_warning_not_silence(self, harness_repo, monkeypatch, tmp_path):
        """A deployed guard whose roster is gone (a hand edit, a stub) must
        not read as "no secret paths": doctor names it and the upgrade."""
        from espalier import doctor as doctor_module

        self._user(tmp_path, monkeypatch, None)
        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: False)
        guard = harness_repo / "tools" / "cc" / "hooks" / "write_guard.py"
        guard.parent.mkdir(parents=True, exist_ok=True)
        guard.write_bytes(b"'''a guard with no roster'''\n")
        report = run_doctor_check(harness_repo, skip_self_host=True)
        hits = [w for w in report["warnings"] if w.startswith("sandbox: the posture could not be derived")]
        assert len(hits) == 1 and "_SECRET_PATH_LABEL" in hits[0] and "upgrade --execute" in hits[0], report["warnings"]
        assert any("sandbox" in step for step in report["next_steps"]), report["next_steps"]


class TestTheUserSettingsPath:
    def test_the_config_dir_variable_wins_over_the_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        assert sp.user_settings_path() == tmp_path / "cfg" / "settings.json"
        monkeypatch.delenv("CLAUDE_CONFIG_DIR")
        assert sp.user_settings_path({"HOME": str(tmp_path)}).parts[-2:] == (".claude", "settings.json")
        assert os.sep not in sp.FLAG
