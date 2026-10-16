"""The sandbox posture (TP-476 Wave B-1): ``init`` and ``upgrade`` print, and
on ``--sandbox-posture`` write, Claude Code's ``sandbox.filesystem`` deny
lists for the harness zones and the secret paths; ``doctor`` says which of
three states the tree is in.

Why these pins exist. The lists are DERIVED, never copied: ``denyWrite`` from
the prefixes the hook denies at runtime on this kind of tree (an adopter's
own CI files are never denied) plus the adopter's ``protected_paths``,
``denyRead`` parsed out of the deployed ``write_guard.py``'s secret roster.
A hand copy drifts the day a roster moves, so the derivation tests change a
roster and watch the entries follow, and a parity test holds the engine's
runtime roster equal to the hook's. ``sandbox.enabled`` is never written,
because turning the sandbox on changes the adopter's network and approval
behaviour; a test guards that the flag writes the lists alone. Measured
2026-10-09 (the pack's 0-C, macOS Seatbelt): ``denyWrite`` holds for shell
writes and ``git checkout`` and NOT for the ``Write`` tool, so the posture is
a shell layer beside ``write_guard``, and doctor's line says so. On native
Windows there is no sandbox at all, which is the first of doctor's states.
The failure-mode review of the first cut found the upgrade path skipping the
flag on a current tree, adopter workflows denied, malformed settings keys
read as written, and user-scope entries counted as present: each has a pin.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from espalier import sandbox_posture as sp
from espalier import surface_contract
from espalier.cli import (
    MERGE_ALREADY,
    MERGE_PARSE_ERROR,
    MERGE_WIRED,
    cmd_init,
    cmd_upgrade,
    fresh_settings,
    merge_hooks_into_settings,
)
from espalier.doctor import run_doctor_check

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_GUARD = REPO_ROOT / "tools" / "cc" / "hooks" / "write_guard.py"
HOOK_UTILS = REPO_ROOT / "tools" / "cc" / "hooks" / "_hook_utils.py"
PY = "python"


def _roster_source(tmp_path: Path, labels: dict[str, str], name: str = "write_guard.py") -> Path:
    """A write_guard-shaped module holding only the roster the parser reads."""
    body = "_SECRET_PATH_LABEL = " + json.dumps(labels, indent=4) + "\n"
    path = tmp_path / name
    path.write_bytes(("'''a copy of the guard for the derivation test'''\n" + body).encode())
    return path


def _lists(deny_write: list[str], deny_read: list[str], allow_read: list[str] | None = None) -> dict[str, list[str]]:
    return {"denyWrite": deny_write, "denyRead": deny_read, "allowRead": allow_read or []}


class TestTheDenyReadDerivation:
    """``denyRead`` follows the deployed guard's ``_SECRET_PATH_LABEL``: a
    label with two spellings split on ``' / '``, each spelling written at the
    project root and anywhere below it (the guard matches a dotenv by name
    wherever it sits, and whether ``**/`` matches zero directories is not in
    the docs). Parsed by AST so the engine never imports the hook; a label
    that is not a path or a glob is refused by name."""

    def test_the_live_guards_four_labels_yield_these_ten_globs(self):
        """Every live label pinned, so a reworded label moves this test and
        not the adopter's settings file."""
        assert sp.deny_read_entries(LIVE_GUARD) == [
            "./.env", "./**/.env", "./.env.*", "./**/.env.*",
            "./secrets/**", "./**/secrets/**",
            "./.aws/credentials", "./**/.aws/credentials",
            "./credentials.json", "./**/credentials.json",
        ]

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

    def test_a_label_that_is_prose_is_refused_not_written_as_a_path(self, tmp_path):
        reworded = _roster_source(tmp_path, {"env": "the dotenv file and its variants"})
        with pytest.raises(ValueError, match="not a path or a glob"):
            sp.deny_read_entries(reworded)

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


class TestTheAllowReadDerivation:
    """The guard allows a read of the dotenv template files (its
    ``_DOTENV_TEMPLATE_SUFFIXES``, DEF-816), which the ``denyRead`` glob
    would refuse at the OS; the dispatcher settled (air c3a5c0) that they
    become ``allowRead`` entries derived from that tuple, under the sandbox's
    documented narrower-allow rule for reads, driven on macOS 2026-10-15 (the
    five templates read with the entries, none without) and not on Linux or
    WSL2, which the print says."""

    def test_the_live_guards_four_suffixes_yield_eight_entries(self):
        assert sp.allow_read_entries(LIVE_GUARD) == [
            "./.env.example", "./**/.env.example", "./.env.sample", "./**/.env.sample",
            "./.env.template", "./**/.env.template", "./.env.dist", "./**/.env.dist",
        ]

    def test_the_entries_follow_the_guards_tuple(self, tmp_path):
        source = _roster_source(tmp_path, {"env": ".env"})
        source.write_bytes(source.read_bytes() + b'_DOTENV_TEMPLATE_SUFFIXES = (".example", ".local")\n')
        assert sp.allow_read_entries(source) == ["./.env.example", "./**/.env.example",
                                                 "./.env.local", "./**/.env.local"]

    def test_a_guard_without_the_tuple_allows_none(self, tmp_path):
        assert sp.allow_read_entries(_roster_source(tmp_path, {"env": ".env"})) == []

    def test_a_tuple_that_is_not_suffix_strings_is_refused_by_name(self, tmp_path):
        source = _roster_source(tmp_path, {"env": ".env"})
        source.write_bytes(source.read_bytes() + b'_DOTENV_TEMPLATE_SUFFIXES = ("the example file",)\n')
        with pytest.raises(ValueError, match="_DOTENV_TEMPLATE_SUFFIXES"):
            sp.allow_read_entries(source)

    def test_the_posture_carries_the_list_and_describe_says_where_it_was_driven(self, tmp_path):
        """Dies to the line going back to "not yet driven on a live sandbox", or
        dropping the hosts the drive did not reach."""
        found = sp.posture(tmp_path)
        assert found.lists["allowRead"] == sp.allow_read_entries(root=tmp_path)
        line = next(x for x in sp.describe(found, written=False, prefix="[init]", remedy_py=PY)
                    if "allowRead re-opens the dotenv template files" in x)
        assert "driven on macOS" in line and "Linux and WSL2 not yet" in line, line
        assert "live sandbox" not in line, line

    def test_describe_names_read_among_the_file_tools(self, tmp_path):
        """Dies to the Read tool dropping off the line: the macOS drive read a
        denied dotenv through Read with the sandbox on, so the guard is its layer."""
        found = sp.posture(tmp_path)
        line = next(x for x in sp.describe(found, written=False, prefix="[init]", remedy_py=PY)
                    if "shell layer beside write_guard" in x)
        tools = line.split("run outside it")[0]
        assert "run outside it" in line and all(t in tools for t in ("Read", "Write", "Edit", "NotebookEdit")), line

    def test_the_layer_line_says_only_macos_was_driven(self, tmp_path):
        """Dies to the line claiming Linux and WSL2 as covered (the drive ran on
        macOS only), or dropping the late-file risk the settings reference names
        there. Doctor's twin line is pinned in TestDoctorsThreeStates."""
        found = sp.posture(tmp_path)
        layer = next(x for x in sp.describe(found, written=False, prefix="[init]", remedy_py=PY)
                     if "shell layer beside write_guard" in x)
        assert "driven on macOS" in layer and "Linux and WSL2 not yet" in layer, layer
        assert "created after the session starts may stay readable" in layer, layer


def _hook_utils(monkeypatch, self_host: bool):
    spec = importlib.util.spec_from_file_location("hook_utils_for_posture_parity", HOOK_UTILS)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "is_self_host_repo", lambda root: self_host)
    return mod


class TestTheDenyWriteDerivation:
    """``denyWrite`` follows the prefixes the hook denies AT RUNTIME on this
    kind of tree (``tools/cc/`` everywhere; ``.github/workflows/`` and
    ``espalier/`` on the self-host tree alone, since an adopter edits its own
    CI files), the exact protected files not under a prefix, then the
    adopter's ``protected_paths``. ``cc/`` and the two ``.espalier``
    manifests stay with ``write_guard``: the harness's own shell commands
    write them. No entry carries a wildcard (Linux and WSL2 skip one), and an
    adopter entry the sandbox could not honour is left out and named."""

    @pytest.mark.parametrize("self_host", [False, True])
    def test_the_engines_runtime_roster_equals_the_hooks(self, monkeypatch, tmp_path, self_host):
        hook = _hook_utils(monkeypatch, self_host)
        assert tuple(hook.harness_protected_prefixes(tmp_path)) == \
            surface_contract.get_runtime_protected_prefixes(self_host)

    def test_an_adopter_tree_gets_its_zones_the_guard_file_and_its_own_paths(self, tmp_path):
        entries = sp.deny_write_entries(tmp_path, self_host=False, protected_paths=["data/", "models"])
        assert entries[0] == "./tools/cc"
        assert "./.github/workflows" not in entries, entries
        assert "./.github/workflows/harness-guard.yml" in entries, entries
        assert "./.claude/settings.json" in entries and "./.claude/settings.local.json" in entries
        assert entries[-2:] == ["./data", "./models"]
        assert "./espalier" not in entries
        assert "./cc" not in entries and "cc/" in sp.HOOK_KEPT_ZONES
        assert not any(e.startswith("./.espalier/") for e in entries), entries
        assert ".espalier/integrity.json" in sp.HOOK_KEPT_FILES

    def test_the_self_host_tree_adds_its_engine_source_and_its_workflows(self, tmp_path):
        entries = sp.deny_write_entries(tmp_path, self_host=True, protected_paths=[])
        assert "./espalier" in entries and "./.github/workflows" in entries
        assert "./.github/workflows/harness-guard.yml" not in entries, "under the prefix now"

    def test_the_self_host_switch_is_read_from_the_tree_by_default(self, tmp_path):
        """A scratch directory is nobody's self-host tree."""
        assert "./espalier" not in sp.deny_write_entries(tmp_path, protected_paths=[])

    @pytest.mark.parametrize("raw, entry, why", [
        ("data/", "./data", None),
        ("./ok/", "./ok", None),
        ("a/./b", "./a/b", None),
        ("a//b", "./a/b", None),
        ("sub\\dir", "./sub/dir", None),
        (".", None, "whole project"),
        ("./", None, "whole project"),
        ("a/../../b", None, "climb"),
        ("../b", None, "climb"),
        ("/abs", None, "absolute"),
        ("C:/x", None, "absolute"),
        ("c:\\x", None, "absolute"),
        ("~/z", None, "home"),
        ("a/*", None, "wildcard"),
        ("", None, "empty"),
    ])
    def test_an_entry_is_normalised_or_dropped_with_its_reason(self, raw, entry, why):
        got, reason = sp.write_entry(raw)
        assert got == entry
        assert (reason is None) == (why is None)
        if why:
            assert why in reason

    def test_dropped_entries_are_reported_not_swallowed(self, tmp_path):
        dropped: list[str] = []
        entries = sp.deny_write_entries(tmp_path, self_host=False, protected_paths=["a/*", "/abs", "ok"],
                                        dropped=dropped)
        assert "./ok" in entries and len(dropped) == 2
        assert dropped[0].startswith("a/*: ") and dropped[1].startswith("/abs: ")
        assert all(not any(ch in e for ch in "*?[") for e in entries), entries

    def test_a_file_under_a_denied_prefix_is_not_repeated(self, tmp_path):
        entries = sp.deny_write_entries(tmp_path, self_host=False, protected_paths=[])
        assert not any(e.startswith("./tools/cc/") for e in entries), entries


class TestThePosture:
    def test_the_posture_carries_both_lists_the_drops_and_its_source(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sp, "_adopter_paths", lambda root: ["data/", "a/*"])
        found = sp.posture(tmp_path)
        assert found.lists["denyWrite"][-1] == "./data" and found.dropped == ["a/*: a wildcard: Linux and "
                                                                               "WSL2 skip a denyWrite entry "
                                                                               "that holds one"]
        assert found.lists["denyRead"][0] == "./.env" and "_vendor" in found.source
        assert found.total == sum(len(found.lists[name]) for name in ("denyWrite", "denyRead", "allowRead"))

    def test_a_roster_less_guard_is_a_refusal_with_its_reason_never_a_raise(self, tmp_path):
        hooks = tmp_path / "tools" / "cc" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "write_guard.py").write_bytes(b"X = 1\n")
        found, why = sp.posture_or_refusal(tmp_path)
        assert found is None and "_SECRET_PATH_LABEL" in why

    def test_describe_names_the_hints_the_drops_and_the_deployed_doc(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sp, "_adopter_paths", lambda root: ["a/*"])
        found = sp.posture(tmp_path)
        lines = sp.describe(found, written=False, prefix="[init]", remedy_py=PY)
        text = "\n".join(lines)
        assert f"{PY} -m espalier init . --sandbox-posture" in text
        assert f"{PY} -m espalier upgrade . --execute --sandbox-posture" in text
        assert "left out of denyWrite, from protected_paths: a/*" in text
        assert "docs/TROUBLESHOOTING.md" in text and "sandbox.enabled" in text
        written = sp.describe(found, written=True, prefix="[init]", remedy_py=PY)
        assert "written to .claude/settings.json" in written[0]


class TestTheMergeKeepsTheOperatorsKeys:
    def test_missing_entries_are_appended_and_nothing_else_moves(self):
        existing = {"sandbox": {"enabled": True, "filesystem": {"denyWrite": ["~/x"], "allowWrite": ["/tmp/b"]}}}
        result = sp.merge_posture(existing, _lists(["./tools/cc", "~/x"], ["./.env"]))
        assert result.added == ["denyWrite ./tools/cc", "denyRead ./.env"] and result.skipped == []
        fs = existing["sandbox"]["filesystem"]
        assert fs["denyWrite"] == ["~/x", "./tools/cc"] and fs["denyRead"] == ["./.env"]
        assert fs["allowWrite"] == ["/tmp/b"] and existing["sandbox"]["enabled"] is True

    def test_a_second_merge_adds_nothing(self):
        existing: dict = {}
        posture = _lists(["./tools/cc"], ["./.env"])
        assert sp.merge_posture(existing, posture)
        assert not sp.merge_posture(existing, posture)
        assert "enabled" not in existing["sandbox"]

    @pytest.mark.parametrize("existing, skipped, untouched", [
        ({"sandbox": True}, ["sandbox is not an object"], {"sandbox": True}),
        ({"sandbox": {"filesystem": ["x"]}}, ["sandbox.filesystem is not an object"],
         {"sandbox": {"filesystem": ["x"]}}),
    ])
    def test_a_malformed_sandbox_key_is_named_and_left_alone(self, existing, skipped, untouched):
        result = sp.merge_posture(existing, _lists(["./tools/cc"], ["./.env"]))
        assert result.added == [] and result.skipped == skipped
        assert existing == untouched

    def test_a_malformed_list_is_named_and_the_other_list_still_lands(self):
        existing = {"sandbox": {"filesystem": {"denyWrite": "./data"}}}
        result = sp.merge_posture(existing, _lists(["./tools/cc"], ["./.env"]))
        assert result.skipped == ["sandbox.filesystem.denyWrite is not a list"]
        assert result.added == ["denyRead ./.env"]
        assert existing["sandbox"]["filesystem"]["denyWrite"] == "./data"

    def test_the_merge_function_takes_the_posture_on_an_unwired_file(self, tmp_path):
        """``init --wire-hooks --sandbox-posture`` on a permissions-only file
        goes through the one merge path, so the backup and the refusals hold
        for the posture too: the hooks land and the posture with them."""
        claude = tmp_path / ".claude"
        claude.mkdir()
        (tmp_path / ".git").mkdir()
        settings = claude / "settings.json"
        settings.write_text(json.dumps({"permissions": {"allow": ["Read"]}, "sandbox": {"enabled": False}}),
                            encoding="utf-8")
        posture = {"denyWrite": ["./tools/cc"], "denyRead": ["./.env"]}  # an empty list is never created
        result = merge_hooks_into_settings(settings, repo_root=tmp_path, sandbox_posture=posture)
        assert result.status == MERGE_WIRED and result.event_count > 0
        assert result.posture_added == ("denyWrite ./tools/cc", "denyRead ./.env")
        body = json.loads(settings.read_text(encoding="utf-8"))
        assert body["sandbox"]["filesystem"] == posture
        assert body["sandbox"]["enabled"] is False and body["permissions"]["allow"] == ["Read"]

    def test_a_fully_wired_file_lacking_only_the_posture_is_still_written(self, tmp_path):
        """The merge's idempotence gate (every event wired, nothing to append)
        used to be the only reason to write; the posture is a second one, so a
        wired install that opts in later gets the lists, and a second run on
        the same file writes nothing (no .bak churn)."""
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

    def test_a_malformed_key_is_carried_on_the_already_outcome(self, tmp_path):
        (tmp_path / ".git").mkdir()
        claude = tmp_path / ".claude"
        claude.mkdir()
        settings = claude / "settings.json"
        body = fresh_settings(tmp_path, "workflow")
        body["sandbox"] = True
        settings.write_text(json.dumps(body), encoding="utf-8")
        result = merge_hooks_into_settings(settings, repo_root=tmp_path,
                                           sandbox_posture=_lists(["./tools/cc"], ["./.env"]))
        assert result.status == MERGE_ALREADY and result.posture_skipped == ("sandbox is not an object",)

    def test_a_refused_file_is_left_byte_identical_with_the_posture_requested(self, tmp_path):
        (tmp_path / ".git").mkdir()
        claude = tmp_path / ".claude"
        claude.mkdir()
        settings = claude / "settings.json"
        settings.write_bytes(b"{not json")
        result = merge_hooks_into_settings(settings, repo_root=tmp_path,
                                           sandbox_posture=_lists(["./tools/cc"], ["./.env"]))
        assert result.status == MERGE_PARSE_ERROR and result.posture_added == ()
        assert settings.read_bytes() == b"{not json"


def _make_repo(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-app"\n', encoding="utf-8")
    (tmp_path / ".git").mkdir(exist_ok=True)
    return tmp_path


def _init(repo: Path, **overrides) -> int:
    return cmd_init(argparse.Namespace(repo=str(repo), config=None, **overrides))


def _upgrade(repo: Path, **overrides) -> int:
    return cmd_upgrade(argparse.Namespace(repo=str(repo), config=None, **overrides))


def _settings(repo: Path) -> dict:
    return json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))


class TestInitWritesThePostureOnlyOnTheFlag:
    def test_without_the_flag_no_sandbox_key_is_written_and_the_posture_is_printed(self, tmp_path, capsys):
        repo = _make_repo(tmp_path)
        assert _init(repo) == 0
        assert "sandbox" not in _settings(repo)
        out = capsys.readouterr().out
        assert "sandbox posture" in out and sp.FLAG in out and "./tools/cc" in out

    def test_with_the_flag_the_two_lists_are_written_and_enabled_is_not(self, tmp_path, capsys):
        repo = _make_repo(tmp_path)
        assert _init(repo, sandbox_posture=True) == 0
        body = _settings(repo)
        fs = body["sandbox"]["filesystem"]
        assert fs["denyWrite"] == sp.deny_write_entries(repo)
        assert fs["denyRead"] == sp.deny_read_entries(root=repo)
        assert fs["allowRead"] == sp.allow_read_entries(root=repo) and fs["allowRead"]
        assert "enabled" not in body["sandbox"]
        assert "written to .claude/settings.json" in capsys.readouterr().out

    def test_the_flag_merges_into_a_preserved_settings_file_with_wire_hooks(self, tmp_path):
        repo = _make_repo(tmp_path)
        claude = repo / ".claude"
        claude.mkdir()
        (claude / "settings.json").write_text(
            json.dumps({"permissions": {"allow": ["Read"]}, "sandbox": {"filesystem": {"denyWrite": ["~/mine"]}}}),
            encoding="utf-8")
        assert _init(repo, wire_hooks=True, sandbox_posture=True) == 0
        body = _settings(repo)
        assert body["sandbox"]["filesystem"]["denyWrite"][0] == "~/mine"
        assert "./tools/cc" in body["sandbox"]["filesystem"]["denyWrite"]
        assert body["permissions"]["allow"][0] == "Read" and "enabled" not in body["sandbox"]

    def test_the_flag_on_a_preserved_file_without_wire_hooks_writes_nothing_and_says_which_commands_do(
        self, tmp_path, capsys,
    ):
        repo = _make_repo(tmp_path)
        claude = repo / ".claude"
        claude.mkdir()
        before = json.dumps({"permissions": {"allow": ["Read"]}})
        (claude / "settings.json").write_text(before, encoding="utf-8")
        assert _init(repo, sandbox_posture=True) == 0
        assert (claude / "settings.json").read_text(encoding="utf-8") == before
        out = capsys.readouterr().out
        assert "did not write it" in out and "preserved" in out
        assert "init . --wire-hooks --sandbox-posture" in out and "upgrade . --execute --sandbox-posture" in out

    def test_a_dropped_protected_path_is_said_in_the_print(self, tmp_path, capsys):
        repo = _make_repo(tmp_path)
        (repo / "espalier.toml").write_text('protected_paths = ["data/", "logs/*"]\n', encoding="utf-8")
        assert _init(repo, sandbox_posture=True) == 0
        assert "./data" in _settings(repo)["sandbox"]["filesystem"]["denyWrite"]
        out = capsys.readouterr().out
        assert "left out of denyWrite, from protected_paths: logs/*" in out


class TestUpgradeAnswersTheFlagOnACurrentTree:
    """The failure-mode review drove ``upgrade --execute --sandbox-posture``
    on an install already at this version: it printed "nothing to do" and
    wrote no key, because the version-current branch returns before the
    settings stage. The flag is answered there now, in both modes."""

    def test_the_dry_run_prints_and_execute_writes_then_a_second_run_finds_them_there(self, tmp_path, capsys):
        repo = _make_repo(tmp_path)
        assert _init(repo) == 0
        assert "sandbox" not in _settings(repo)
        capsys.readouterr()
        assert _upgrade(repo, execute=False, sandbox_posture=True) == 0
        out = capsys.readouterr().out
        assert "[upgrade] sandbox posture" in out and "a dry run; --execute writes them" in out
        assert "sandbox" not in _settings(repo)
        assert _upgrade(repo, execute=True, sandbox_posture=True) == 0
        out = capsys.readouterr().out
        assert "sandbox posture entries" in out and "written to .claude/settings.json" in out
        body = _settings(repo)
        assert body["sandbox"]["filesystem"]["denyWrite"] == sp.deny_write_entries(repo)
        assert "enabled" not in body["sandbox"]
        assert _upgrade(repo, execute=True, sandbox_posture=True) == 0
        assert "every entry was already there" in capsys.readouterr().out

    def test_without_the_flag_a_current_tree_prints_no_posture(self, tmp_path, capsys):
        repo = _make_repo(tmp_path)
        assert _init(repo) == 0
        capsys.readouterr()
        assert _upgrade(repo, execute=True) == 0
        assert "sandbox posture" not in capsys.readouterr().out

    def test_with_no_settings_file_the_dry_run_says_so_and_execute_recreates_it_with_the_posture(
        self, tmp_path, capsys,
    ):
        """A missing settings file makes the tree stale, so the main path
        runs: the dry run has no file to write into and says so; ``--execute``
        re-deploys the file and the merge carries the posture into it."""
        repo = _make_repo(tmp_path)
        assert _init(repo) == 0
        (repo / ".claude" / "settings.json").unlink()
        capsys.readouterr()
        assert _upgrade(repo, execute=False, sandbox_posture=True) == 0
        assert "no .claude/settings.json to write into" in capsys.readouterr().err
        assert _upgrade(repo, execute=True, sandbox_posture=True) == 0
        body = _settings(repo)
        assert body["sandbox"]["filesystem"]["denyWrite"] == sp.deny_write_entries(repo)
        assert "enabled" not in body["sandbox"]


class TestDoctorsThreeStates:
    """No sandbox on native Windows; off (the default); on. The user-scope
    ``allowUnsandboxedCommands`` is read from the config directory the
    environment names, never the real home, and is never written; a ``./``
    entry in the user file counts for nothing (it resolves under
    ``~/.claude``)."""

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
        state = sp.read_state(tmp_path, posture=_lists([], []), host_is_windows=True)
        assert state.supported is False
        info, warnings, steps = sp.doctor_lines(state, remedy_py=PY)
        assert warnings == [] and steps == [] and len(info) == 1
        assert "native Windows" in info[0] and "WSL2" in info[0] and "write_guard" in info[0]

    def test_off_names_the_missing_entries_and_the_commands(self, tmp_path, monkeypatch):
        self._user(tmp_path, monkeypatch, None)
        posture = _lists(["./tools/cc"], ["./.env"])
        state = sp.read_state(tmp_path, posture=posture, host_is_windows=False)
        assert state.supported and not state.enabled
        assert state.missing == posture and state.present == _lists([], [])
        info, warnings, steps = sp.doctor_lines(state, remedy_py=PY)
        assert warnings == [] and steps == []
        assert any("sandbox: off" in line and f"{PY} -m espalier upgrade . --execute {sp.FLAG}" in line
                   for line in info), info
        assert any("shell layer" in line and "Write, Edit and NotebookEdit" in line
                   and "read deny on Read" in line and "on Linux and WSL2 not yet" in line
                   and "created after the session starts may stay readable" in line for line in info), info
        assert any("managed settings file or --settings is not read" in line for line in info), info
        # tests/test_doctor.py::TestDoctorFailures guards the report against a
        # spurious bypass-mode info line from the kill-switch check by that
        # token; the retry line must describe the mode without spelling it.
        assert not any("bypassPermissions" in line for line in info), info

    def test_on_with_the_posture_present_is_reported_whole(self, tmp_path, monkeypatch):
        self._user(tmp_path, monkeypatch, {"sandbox": {"allowUnsandboxedCommands": False}})
        posture = _lists(["./tools/cc"], ["./.env"])
        self._settings(tmp_path, {"sandbox": {"enabled": True, "filesystem": posture}})
        state = sp.read_state(tmp_path, posture=posture, host_is_windows=False)
        assert state.enabled and state.source == ".claude/settings.json"
        assert state.present == posture and state.missing == _lists([], [])
        assert state.user_retry is False
        info, warnings, steps = sp.doctor_lines(state, remedy_py=PY)
        assert warnings == [] and steps == []
        assert any("sandbox: on" in line and "all 2 posture entries present" in line for line in info), info
        assert any("allowUnsandboxedCommands" in line and "holds" in line for line in info), info

    def test_on_with_entries_missing_is_a_warning_with_a_step_and_the_local_file_wins(self, tmp_path, monkeypatch):
        self._user(tmp_path, monkeypatch, {"sandbox": {"allowUnsandboxedCommands": True}})
        posture = _lists(["./tools/cc", "./.claude/settings.json"], ["./.env"])
        self._settings(tmp_path, {"sandbox": {"enabled": False}})
        self._settings(tmp_path, {"sandbox": {"enabled": True, "filesystem": {"denyRead": ["./.env"]}}},
                       name="settings.local.json")
        state = sp.read_state(tmp_path, posture=posture, host_is_windows=False)
        assert state.enabled and state.source == ".claude/settings.local.json"
        assert state.missing == _lists(["./tools/cc", "./.claude/settings.json"], [])
        info, warnings, steps = sp.doctor_lines(state, remedy_py=PY)
        assert len(warnings) == 1 and "2 posture entries missing of 3" in warnings[0]
        assert f"{PY} -m espalier upgrade . --execute {sp.FLAG}" in warnings[0]
        assert len(steps) == 1 and "the sandbox is on" in steps[0]
        assert any("allowUnsandboxedCommands" in line and "never writes" in line for line in info), info

    def test_a_user_scope_entry_counts_for_nothing(self, tmp_path, monkeypatch):
        """``./`` in the user file resolves under ``~/.claude``: a posture
        pasted there protects nothing in the project, so doctor must not
        read it as present."""
        posture = _lists(["./tools/cc"], ["./.env"])
        self._user(tmp_path, monkeypatch, {"sandbox": {"enabled": True, "filesystem": posture}})
        state = sp.read_state(tmp_path, posture=posture, host_is_windows=False)
        assert state.enabled and state.source == "the user settings"
        assert state.present == _lists([], []) and state.missing == posture
        _info, warnings, _steps = sp.doctor_lines(state, remedy_py=PY)
        assert len(warnings) == 1 and "2 posture entries missing of 2" in warnings[0]

    def test_a_project_false_outranks_a_user_true(self, tmp_path, monkeypatch):
        self._user(tmp_path, monkeypatch, {"sandbox": {"enabled": True}})
        self._settings(tmp_path, {"sandbox": {"enabled": False}})
        state = sp.read_state(tmp_path, posture=_lists([], []), host_is_windows=False)
        assert not state.enabled and state.source == ".claude/settings.json"

    def test_a_malformed_list_is_named_in_the_warning_not_counted_missing(self, tmp_path, monkeypatch):
        self._user(tmp_path, monkeypatch, None)
        posture = _lists(["./tools/cc"], ["./.env"])
        self._settings(tmp_path, {"sandbox": {"enabled": True, "filesystem": {"denyWrite": "./tools/cc",
                                                                                   "denyRead": ["./.env"]}}})
        state = sp.read_state(tmp_path, posture=posture, host_is_windows=False)
        assert any("sandbox.filesystem.denyWrite is not a list" in n for n in state.notes), state.notes
        _info, warnings, steps = sp.doctor_lines(state, remedy_py=PY)
        assert len(warnings) == 1 and "denyWrite is not a list" in warnings[0]
        assert steps and steps[0].startswith("fix the sandbox key")

    def test_a_retired_entry_still_present_is_named_for_the_operator_to_delete(self, tmp_path, monkeypatch):
        self._user(tmp_path, monkeypatch, None)
        monkeypatch.setattr(sp, "RETIRED_ENTRIES", (("denyWrite", "./.github/workflows", "an adopter edits its own CI files"),))
        self._settings(tmp_path, {"sandbox": {"filesystem": {"denyWrite": ["./.github/workflows", "./tools/cc"]}}})
        state = sp.read_state(tmp_path, posture=_lists(["./tools/cc"], []), host_is_windows=False)
        assert state.retired == ["denyWrite ./.github/workflows (an adopter edits its own CI files)"]
        info, _warnings, _steps = sp.doctor_lines(state, remedy_py=PY)
        assert any("no longer derives" in line and "./.github/workflows" in line for line in info), info

    def test_an_unreadable_user_file_is_reported_not_raised(self, tmp_path, monkeypatch):
        home = self._user(tmp_path, monkeypatch, None)
        (home / "settings.json").write_bytes(b"{not json")
        state = sp.read_state(tmp_path, posture=_lists([], []), host_is_windows=False)
        assert state.user_retry is None
        info, _warnings, _steps = sp.doctor_lines(state, remedy_py=PY)
        assert any("could not be read" in line for line in info), info

    def test_doctor_carries_the_lines_through_its_host_seam(self, harness_repo, monkeypatch, tmp_path):
        from espalier import doctor as doctor_module

        self._user(tmp_path, monkeypatch, None)
        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: True)
        report = run_doctor_check(harness_repo, skip_self_host=True)
        assert any(line.startswith("sandbox: none on native Windows") for line in report["info"]), report["info"]
        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: False)
        report = run_doctor_check(harness_repo, skip_self_host=True)
        assert any(line.startswith("sandbox: off") for line in report["info"]), report["info"]
        assert not any(w.startswith("sandbox:") for w in report["warnings"]), report["warnings"]

    def test_a_guard_without_the_roster_is_a_named_warning_with_the_marker_step(self, harness_repo, monkeypatch, tmp_path):
        """A deployed guard whose roster is gone (a hand edit, a stub) must
        not read as "no secret paths": doctor names it, and the step names
        the managed marker, since ``upgrade`` keeps an unmarked edit as yours."""
        from espalier import doctor as doctor_module

        self._user(tmp_path, monkeypatch, None)
        monkeypatch.setattr(doctor_module, "_host_is_windows", lambda: False)
        guard = harness_repo / "tools" / "cc" / "hooks" / "write_guard.py"
        guard.write_bytes(b"'''a guard with no roster'''\n")
        report = run_doctor_check(harness_repo, skip_self_host=True)
        hits = [w for w in report["warnings"] if w.startswith("sandbox: the posture could not be derived")]
        assert len(hits) == 1 and "_SECRET_PATH_LABEL" in hits[0], report["warnings"]
        assert any("# espalier:managed" in step and "-m espalier init ." in step for step in report["next_steps"]), report["next_steps"]


class TestTheUserSettingsPath:
    def test_the_config_dir_variable_wins_over_the_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        assert sp.user_settings_path() == tmp_path / "cfg" / "settings.json"
        monkeypatch.delenv("CLAUDE_CONFIG_DIR")
        both = {"HOME": str(tmp_path / "posix-home"), "USERPROFILE": str(tmp_path / "win-home")}
        picked = sp.user_settings_path(both)
        expected = "win-home" if os.name == "nt" else "posix-home"
        assert picked == tmp_path / expected / ".claude" / "settings.json"
        assert sp.user_settings_path({}) is None or sp.user_settings_path({}).name == "settings.json"
