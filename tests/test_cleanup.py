"""Tests for ``espalier.cleanup.clean_generated_surface``.

Pins the rule that cleanup removes only files carrying the
``espalier:managed`` marker — user code like ``app.py`` is never
touched. Without this guard, a marker-detection regression could
silently delete adopter user files on uninstall, or quietly leave
orphaned managed surface files behind so re-init double-writes.
"""
# slow-exempt: the only child processes are the git setup of a scratch tree
# and one real `espalier init` per driven test in TestUninstallAccountsForEvery
# Survivor (four tests, measured 0.46-0.55s each, 2.1s together, 2026-09-11);
# everything else in this module is in-process over tmp_path.
from __future__ import annotations

import argparse
import compileall
import json
import subprocess
import sys
from pathlib import Path

import os

import pytest

from tests._symlink_support import requires_symlink

from espalier.cleanup import clean_generated_surface
from espalier.managed_inventory import get_install_ci_artifacts, get_seed_docs


class TestDryRun:
    def test_dry_run_lists_files_without_deleting(self, harness_repo):
        """dry_run=True reports what would be deleted without touching anything."""
        result = clean_generated_surface(harness_repo, dry_run=True)
        assert result["dry_run"] is True
        assert len(result["deleted"]) > 0
        # No files were actually removed
        for rel in result["deleted"]:
            assert (harness_repo / rel).exists() or rel.endswith("/"), \
                f"{rel} should still exist after dry run"

    def test_user_files_never_touched_dry_run(self, harness_repo):
        """app.py (user file) is not in the deleted list during dry run."""
        result = clean_generated_surface(harness_repo, dry_run=True)
        assert "app.py" not in result["deleted"]


class TestSettingsNewArtifactCleanup:
    """TP-176 W2-3: re-init writes `.claude/settings.json.new` (an inert
    diff template carrying the _espalier_managed sentinel) when a
    settings.json already exists. clean-generated previously left it
    orphaned. It must now be removed when marked, and preserved when a
    user hand-saved an unmarked file of the same name."""

    def test_managed_settings_new_is_removed(self, harness_repo):
        new_path = harness_repo / ".claude" / "settings.json.new"
        new_path.write_text(
            json.dumps({"_espalier_managed": True, "hooks": {}}) + "\n",
            encoding="utf-8",
        )
        result = clean_generated_surface(harness_repo, dry_run=False)
        assert ".claude/settings.json.new" in result["deleted"]
        assert not new_path.exists()

    def test_unmarked_settings_new_is_preserved(self, harness_repo):
        new_path = harness_repo / ".claude" / "settings.json.new"
        new_path.write_text(
            json.dumps({"hooks": {}}) + "\n",  # no _espalier_managed sentinel
            encoding="utf-8",
        )
        result = clean_generated_surface(harness_repo, dry_run=False)
        assert ".claude/settings.json.new" not in result["deleted"]
        assert new_path.exists()
        assert ".claude/settings.json.new" in result["preserved_user_files"]


class TestExecute:
    def test_execute_removes_marked_managed_files(self, harness_repo):
        """TP-04: execute removes files carrying the espalier:managed marker.

        ``cc/COMMANDS.md`` is written by the harness_repo fixture WITH the
        marker, so cleanup must remove it. Files that lack the marker
        (CLAUDE.md, ESPALIER_MEMORY.md, settings.json runtime artifact) are
        preserved per the TP-04 contract.
        """
        result = clean_generated_surface(harness_repo, dry_run=False)
        assert result["status"] == "pass"
        # cc/COMMANDS.md was deployed with the marker — removed
        assert not (harness_repo / "cc" / "COMMANDS.md").exists()
        # CLAUDE.md is a user-edited scaffold without marker — preserved
        assert (harness_repo / "CLAUDE.md").exists()
        # settings.json is local-runtime — preserved by classification
        assert (harness_repo / ".claude" / "settings.json").exists()

    def test_user_files_survive_execute(self, harness_repo):
        """app.py and pyproject.toml are not removed by execute cleanup."""
        clean_generated_surface(harness_repo, dry_run=False)
        assert (harness_repo / "app.py").exists()
        assert (harness_repo / "pyproject.toml").exists()

    def test_prunes_empty_directories(self, tmp_path):
        """After cleanup, dirs emptied by managed-file deletion are pruned.

        TP-04: settings.json is classified as local-runtime and never
        auto-deleted, so this test seeds a *marker-carrying* command file
        instead — the contract path that cleanup actually removes.
        """
        from espalier.managed_markers import MARKER_HTML_COMMENT_RICH
        managed_dir = tmp_path / ".claude" / "commands"
        managed_dir.mkdir(parents=True)
        # Use a canonical command name so it appears in the inventory.
        managed_cmd = managed_dir / "audit.md"
        managed_cmd.write_text(
            f"{MARKER_HTML_COMMENT_RICH}\n# audit command\n",
            encoding="utf-8",
        )

        result = clean_generated_surface(tmp_path, dry_run=False)

        assert not managed_cmd.exists()
        assert not managed_dir.exists(), (
            "Expected cleanup to prune empty .claude/commands directory after "
            f"deleting audit.md. Deleted entries: {result['deleted']}"
        )
        assert ".claude/commands" in result["deleted"]

    def test_does_not_prune_non_empty_directory(self, tmp_path):
        """Non-managed user files in a managed directory must keep the directory alive."""
        managed_dir = tmp_path / ".claude"
        managed_dir.mkdir(parents=True)
        (managed_dir / "settings.json").write_text("{}\n", encoding="utf-8")
        (managed_dir / "user_notes.txt").write_text("local-only", encoding="utf-8")

        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "harness_config.json").write_text(
            '{"generated_docs": [".claude/settings.json"]}\n',
            encoding="utf-8",
        )

        result = clean_generated_surface(tmp_path, dry_run=False)

        assert managed_dir.exists(), (
            "Cleanup must not prune .claude when non-managed files remain. "
            f"Deleted entries: {result['deleted']}"
        )
        assert (managed_dir / "user_notes.txt").exists()


class TestCustomUserFile:
    def test_custom_user_file_untouched(self, harness_repo):
        """A file written by the user is not deleted by cleanup."""
        custom = harness_repo / "my_notes.md"
        custom.write_text("# Notes\n", encoding="utf-8")
        clean_generated_surface(harness_repo, dry_run=False)
        assert custom.exists()


class TestMissingOrCorruptPlan:
    def test_works_without_harness_config(self, harness_repo):
        """Cleanup falls back to directory scan when harness_config.json is absent."""
        (harness_repo / "reports" / "harness_config.json").unlink()
        result = clean_generated_surface(harness_repo, dry_run=True)
        # Should return a result dict without crashing
        assert isinstance(result, dict)
        assert "deleted" in result

    def test_malformed_harness_config_graceful(self, harness_repo):
        """Cleanup does not crash when harness_config.json is invalid JSON."""
        (harness_repo / "reports" / "harness_config.json").write_text(
            "not json", encoding="utf-8"
        )
        result = clean_generated_surface(harness_repo, dry_run=True)
        assert isinstance(result, dict)
        assert "failures" in result

    def test_on_never_initialized_repo(self, tmp_path):
        """Cleanup on a bare repo returns empty deleted list without crashing."""
        result = clean_generated_surface(tmp_path, dry_run=True)
        assert isinstance(result, dict)
        assert result["deleted"] == []


class TestSeedDocsAccounting:
    """TP-255 R2: init seeds three convention/doc scaffolds outside the managed
    inventory and outside the .claude/{commands,skills,agents} scan
    (memory/README.md, docs/sharp-edges/README.md, docs/TROUBLESHOOTING.md).
    They ship UNMARKED (operator-editable), so cleanup must PRESERVE them AND
    ACCOUNT for any present seed in a report bucket — never leave it silently
    absent from every list. Parametrized over get_seed_docs() so a future 4th
    seed auto-extends coverage rather than drifting.
    """

    def _seed_unmarked(self, repo):
        for rel in get_seed_docs():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# convention guide\n", encoding="utf-8")  # no marker

    def test_present_seeds_preserved_and_reported(self, harness_repo):
        self._seed_unmarked(harness_repo)
        result = clean_generated_surface(harness_repo, dry_run=False)
        for rel in get_seed_docs():
            assert rel in result["preserved_user_files"], (
                f"{rel} must be accounted for in preserved_user_files, not "
                f"silently absent from every bucket. Report: {result}"
            )
            assert (harness_repo / rel).exists(), f"{rel} must be preserved"

    def _seed_stamped(self, repo):
        # Deploy-realistic: init writes each seed doc with the seed-version stamp
        # ahead of the body (TP-348 1-B). The stamp token is espalier:seed-version,
        # NOT espalier:managed, so the seed must stay operator-owned.
        from espalier.managed_inventory import seed_stamp_line
        for rel in get_seed_docs():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            body = "# convention guide\n"
            p.write_text(seed_stamp_line(body) + body, encoding="utf-8")

    def test_seed_version_stamped_seed_is_preserved_not_deleted(self, harness_repo):
        # Lifecycle guard: a seed doc carrying the seed-version stamp lands in
        # preserved_user_files, never deleted. The crux is the distinct token --
        # had the stamp reused espalier:managed, _file_is_managed would read the
        # seed as harness-owned and clean-generated would delete it.
        from espalier.cleanup import _file_is_managed
        self._seed_stamped(harness_repo)
        for rel in get_seed_docs():
            assert _file_is_managed(harness_repo / rel) is False, (
                f"seed-version-stamped {rel} must NOT read as espalier:managed"
            )
        result = clean_generated_surface(harness_repo, dry_run=False)
        for rel in get_seed_docs():
            assert rel in result["preserved_user_files"], (
                f"seed-version-stamped {rel} must be preserved_user, not "
                f"{'deleted' if rel in result['deleted'] else 'absent'}. Report: {result}"
            )
            assert (harness_repo / rel).exists(), f"stamped {rel} must survive cleanup"

    def test_every_seed_accounted_in_some_bucket(self, harness_repo):
        """Every present seed lands in exactly one report bucket (dry-run)."""
        self._seed_unmarked(harness_repo)
        result = clean_generated_surface(harness_repo, dry_run=True)
        buckets = (
            set(result["deleted"])
            | set(result["already_missing"])
            | set(result["preserved_user_files"])
            | set(result["preserved_local_runtime"])
            | {f.split(":", 1)[0] for f in result["failures"]}
        )
        for rel in get_seed_docs():
            assert rel in buckets, f"{rel} accounted for in no report bucket"


class TestInstallCiArtifactAccounting:
    """TP-383 block 2 (drafted as TP-384, which folded into TP-383 and names no
    pack file — the commit that added these tests, 5ba9d7f, is itself tagged
    TP-383 block 2, so the id was stale the day it was written):
    install-ci (cmd_install_ci) writes ci_guard.py + harness-guard.yml
    (+ the harness-guard.yml.new twin) OUTSIDE the managed inventory and outside
    the .claude/{commands,skills,agents} scan, so pre-fix clean-generated left a
    present install-ci artifact silently absent from every report bucket. Cleanup
    must ACCOUNT for each present artifact (unmarked -> preserved_user).
    Parametrized over get_install_ci_artifacts() so a future 4th artifact
    auto-extends coverage rather than drifting.
    """

    def _write_unmarked(self, repo):
        for rel in get_install_ci_artifacts():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# no espalier marker\n", encoding="utf-8")

    def test_every_install_ci_artifact_accounted_in_some_bucket(self, harness_repo):
        self._write_unmarked(harness_repo)
        result = clean_generated_surface(harness_repo, dry_run=True)
        buckets = (
            set(result["deleted"])
            | set(result["already_missing"])
            | set(result["preserved_user_files"])
            | set(result["preserved_local_runtime"])
            | {f.split(":", 1)[0] for f in result["failures"]}
        )
        for rel in get_install_ci_artifacts():
            assert rel in buckets, (
                f"{rel} must be accounted for in a report bucket, not silently "
                f"absent from every list. Report: {result}"
            )

    def test_unmarked_install_ci_artifact_preserved_not_deleted(self, harness_repo):
        self._write_unmarked(harness_repo)
        result = clean_generated_surface(harness_repo, dry_run=False)
        for rel in get_install_ci_artifacts():
            assert rel in result["preserved_user_files"], (
                f"unmarked {rel} must be preserved_user, not "
                f"{'deleted' if rel in result['deleted'] else 'absent'}."
            )
            assert (harness_repo / rel).exists(), f"unmarked {rel} must survive cleanup"


class TestInstallCiArtifactDriftPin:
    """Canon-derived drift pin (TP-383 block 2; drafted as TP-384 — see the
    sibling class above for why that id resolves to nothing):
    get_install_ci_artifacts() is a
    hand-maintained MIRROR of cmd_install_ci's write set -- cmd_install_ci does
    NOT read the tuple, it hard-codes its own destinations. The other
    install-ci tests iterate the tuple as their reference set, so they can only
    prove "the cleanup loop covers the tuple", never "the tuple covers what
    install-ci writes" -- a closed loop blind to drift. This test closes it: it
    runs the REAL cmd_install_ci across BOTH branches (fresh repo ->
    harness-guard.yml; pre-seeded differing yml -> the harness-guard.yml.new
    twin) and asserts the union of what it ACTUALLY writes under the CI
    directories equals the tuple. A future install-ci write added without
    updating _INSTALL_CI_ARTIFACT_REL_PATHS reds here -- so the mirror cannot
    silently drift and re-orphan a new artifact on uninstall (the exact class
    TestInstallCiArtifactAccounting fixes). Scope note: install-ci's only
    non-CI-dir write is the .espalier/integrity.json re-seed, which is skipped
    when no manifest exists (a fresh temp repo) and is separately owned by
    _LOCAL_RUNTIME_REL_PATHS -- so scanning the two CI dirs captures the full
    CI-artifact write set.
    """

    _CI_DIRS = (".github", "tools/cc")

    def _ci_files(self, repo: Path) -> set[str]:
        found: set[str] = set()
        for d in self._CI_DIRS:
            for p in (repo / d).rglob("*"):
                if p.is_file():
                    found.add(p.relative_to(repo).as_posix())
        return found

    def _run_install_ci(self, repo: Path) -> int:
        from espalier.cli import cmd_install_ci
        return cmd_install_ci(argparse.Namespace(repo=str(repo)))

    def test_observed_ci_writes_equal_the_tuple(self, tmp_path):
        # cmd_install_ci only needs an existing directory (_resolve_repo_arg),
        # not a git repo -- so no child process is spawned (keeps test_cleanup
        # in the fast in-process `not slow` slice).
        # Branch A -- fresh repo: install-ci writes harness-guard.yml + ci_guard.py.
        repo_a = tmp_path / "fresh"
        repo_a.mkdir()
        assert self._run_install_ci(repo_a) == 0, "install-ci (fresh) must succeed"
        observed_a = self._ci_files(repo_a)

        # Branch B -- a DIFFERING harness-guard.yml already present: install-ci
        # parks its gate in the harness-guard.yml.new twin instead of clobbering.
        repo_b = tmp_path / "preseeded"
        repo_b.mkdir()
        wf = repo_b / ".github" / "workflows" / "harness-guard.yml"
        wf.parent.mkdir(parents=True, exist_ok=True)
        wf.write_text("name: host-differing-workflow\n", encoding="utf-8")
        preseeded = {wf.relative_to(repo_b).as_posix()}
        assert self._run_install_ci(repo_b) == 0, "install-ci (pre-seeded) must succeed"
        observed_b = self._ci_files(repo_b) - preseeded

        observed = observed_a | observed_b
        expected = set(get_install_ci_artifacts())
        assert observed == expected, (
            "cmd_install_ci's observed CI writes drifted from "
            "get_install_ci_artifacts().\n"
            f"  observed across both branches: {sorted(observed)}\n"
            f"  tuple: {sorted(expected)}\n"
            "If install-ci gained/renamed a write, update "
            "_INSTALL_CI_ARTIFACT_REL_PATHS (cleanup.py then reconciles it)."
        )


class TestSettingsHookUnwiring:
    """DEF-424d: an uninstall must not leave `.claude/settings.json` pointing at
    hook scripts it just deleted.

    `clean-generated` removes every `tools/cc/hooks/*.py` but preserves
    settings.json as local runtime, so the adopter is left with wiring whose
    targets are gone -- every subsequent tool call errors (a MISSING script is a
    non-blocking error per docs/external/cc-hook-protocol.md, so the session is
    noisy-and-unguarded rather than blocked) and nothing says so. The uninstall
    must finish the job.

    The surgical requirement is the load-bearing half: settings.json also holds
    the adopter's OWN configuration. Stripping the file, or every hook in it,
    would destroy config Espalier never wrote -- the user-code-sovereignty line
    this repo draws everywhere else.
    """

    @staticmethod
    def _settings(repo):
        return json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))

    def test_espalier_hooks_are_unwired_on_execute(self, harness_repo):
        """No surviving entry may execute a canonical Espalier hook script."""
        from espalier.surface_contract import (
            _hook_executes_script_path,
            get_canonical_hook_scripts,
        )
        canonical = set(get_canonical_hook_scripts())
        clean_generated_surface(harness_repo, dry_run=False)
        hooks = self._settings(harness_repo).get("hooks", {})
        survivors = [
            path
            for groups in hooks.values()
            for group in (groups if isinstance(groups, list) else [])
            for hook in (group.get("hooks", []) if isinstance(group, dict) else [])
            if (path := _hook_executes_script_path(hook))
            and path.rsplit("/", 1)[-1] in canonical
        ]
        assert survivors == [], (
            f"{len(survivors)} Espalier hook wiring(s) survived the uninstall while "
            f"their scripts were deleted: {survivors}. Every subsequent tool call in "
            f"the adopter's repo errors on a script that is no longer there."
        )

    def test_adopter_own_config_survives(self, harness_repo):
        """Stripping is surgical: non-Espalier config is never collateral."""
        settings_path = harness_repo / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["hooks"]["PreToolUse"].append(
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": "python3", "args": ["scripts/mine.py"]}
            ]}
        )
        settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

        clean_generated_surface(harness_repo, dry_run=False)
        after = self._settings(harness_repo)
        assert after.get("permissions") == {"allow": ["Read", "Write"]}, (
            "the adopter's own `permissions` block was altered by an uninstall that "
            "should only remove Espalier's hook entries"
        )
        mine = [
            hook
            for group in after.get("hooks", {}).get("PreToolUse", [])
            for hook in group.get("hooks", [])
            if hook.get("args", [""])[0].endswith("mine.py")
        ]
        assert len(mine) == 1, (
            f"the adopter's own PreToolUse hook did not survive the uninstall "
            f"(found {len(mine)}) -- cleanup must strip only Espalier's entries"
        )

    def test_dry_run_leaves_settings_byte_identical(self, harness_repo):
        """A preview must not mutate the adopter's config."""
        settings_path = harness_repo / ".claude" / "settings.json"
        before = settings_path.read_bytes()
        clean_generated_surface(harness_repo, dry_run=True)
        assert settings_path.read_bytes() == before, (
            "dry_run rewrote settings.json -- a preview must never mutate"
        )

    def test_report_names_what_it_unwired(self, harness_repo):
        """Silent success is indistinguishable from a no-op that did nothing."""
        result = clean_generated_surface(harness_repo, dry_run=False)
        assert result.get("unwired_hooks"), (
            "clean_generated_surface reported no `unwired_hooks` while the fixture "
            "wired five Espalier hooks -- the operator cannot tell the strip ran"
        )


class TestUnwireSurvivesOperatorEncodings:
    """`uninstall` must strip Espalier's hooks whatever encoding the operator's
    settings.json is in.

    Driven 2026-08-26: with a plain `read_text(encoding="utf-8")`, a UTF-16
    settings.json -- what Windows PowerShell's `Out-File` writes by default --
    raised inside the reader, was swallowed by the `except (OSError, ValueError)`
    below it, and returned `[]`. `[]` means "no Espalier hooks here", so
    `uninstall` reported success and left all twelve hook entries wired into the
    adopter's file, pointed at scripts it had just deleted. Measured both ways:
    0 unwired before the fix, 12 after.

    Parametrized over the encodings an operator's file actually arrives in
    rather than the one we happen to write.
    """

    @staticmethod
    def _wired_repo(tmp_path: Path) -> Path:
        """A tree with Espalier's hooks wired, via the real merge primitive."""
        from espalier.cli import merge_hooks_into_settings

        repo = tmp_path / "adopter"
        (repo / ".claude").mkdir(parents=True)
        settings = repo / ".claude" / "settings.json"
        settings.write_text(
            json.dumps({"permissions": {"allow": ["Read"]}}, indent=2) + "\n",
            encoding="utf-8",
        )
        merge_hooks_into_settings(settings, repo_root=repo)
        return repo

    @staticmethod
    def _reencode(path: Path, how: str) -> None:
        if how == "utf-8":
            return
        if how == "utf-8-bom":
            path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
            return
        if how == "utf-16":
            path.write_bytes(path.read_text(encoding="utf-8").encode("utf-16"))
            return
        raise AssertionError(f"unknown encoding {how!r}")

    @pytest.mark.parametrize("encoding", ["utf-8", "utf-8-bom", "utf-16"])
    def test_hooks_are_unwired_whatever_the_encoding(self, tmp_path, encoding):
        from espalier.cleanup import _unwire_espalier_hooks

        repo = self._wired_repo(tmp_path)
        settings = repo / ".claude" / "settings.json"
        self._reencode(settings, encoding)

        unwired = _unwire_espalier_hooks(repo, False)

        assert unwired, (
            f"uninstall found no Espalier hooks to strip in a {encoding} "
            "settings.json, so it would leave the adopter wired to deleted "
            "scripts and report success"
        )

    @pytest.mark.parametrize("encoding", ["utf-8", "utf-8-bom", "utf-16"])
    def test_no_espalier_hook_entry_survives(self, tmp_path, encoding):
        """The other direction: 'reported some' is not 'removed all'."""
        from espalier import surface_contract
        from espalier.cleanup import _unwire_espalier_hooks

        repo = self._wired_repo(tmp_path)
        settings = repo / ".claude" / "settings.json"
        self._reencode(settings, encoding)

        _unwire_espalier_hooks(repo, False)

        remaining = json.dumps(
            json.loads(surface_contract.decode_bom(settings.read_bytes()))
            .get("hooks", {})
        )
        assert "tools/cc/hooks" not in remaining, (
            f"an Espalier hook entry survived uninstall in a {encoding} file"
        )

    def test_entries_that_lost_their_type_are_still_unwired(self, tmp_path):
        """"Is this entry OURS?" must stay PERMISSIVE, whatever the governance
        oracle does.

        ⚠ Driven regression. When ``_hook_executes_script_path`` was tightened
        to require ``type == "command"``, this function shared that predicate --
        so on a tree whose espalier entries had lost their ``type`` (exactly the
        state that tightening exists to detect) uninstall removed 0 of 12
        entries, deleted every hook script, and left all 10 events wired to
        files that no longer exist. That is verbatim the failure this
        function's docstring says it prevents.

        The two questions have opposite risk polarity and must not share a
        predicate: "does this EXECUTE the gate?" fails CLOSED, "is this OURS to
        remove?" must be permissive.
        """
        from espalier import surface_contract
        from espalier.cleanup import _unwire_espalier_hooks

        repo = self._wired_repo(tmp_path)
        settings = repo / ".claude" / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        before = sum(len(g.get("hooks", []))
                     for groups in data["hooks"].values() for g in groups)
        for groups in data["hooks"].values():
            for group in groups:
                for hook in group.get("hooks", []):
                    hook.pop("type", None)
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        unwired = _unwire_espalier_hooks(repo, False)

        # The subject is the HOOK entries that lost their type: count those
        # labels, not the whole list -- the merge also writes espalier's
        # statusLine (DEF-798) and the fixture builds through the real merge,
        # so a whole-list count reads "13 of 12" the day the merge grows a key.
        hook_labels = [u for u in unwired if not u.startswith(("statusLine:", "key:"))]
        assert len(hook_labels) == before, (
            f"uninstall left espalier entries wired to scripts it is about to "
            f"delete: removed {len(hook_labels)} of {before} (all labels: {unwired})"
        )
        remaining = json.dumps(
            json.loads(surface_contract.decode_bom(settings.read_bytes()))
            .get("hooks", {})
        )
        assert "tools/cc/hooks" not in remaining, (
            "an untyped Espalier hook entry survived uninstall"
        )

    def test_the_operators_own_keys_survive(self, tmp_path):
        """Guard against the fix over-reaching into content we do not own."""
        from espalier import surface_contract
        from espalier.cleanup import _unwire_espalier_hooks

        repo = self._wired_repo(tmp_path)
        settings = repo / ".claude" / "settings.json"
        self._reencode(settings, "utf-16")

        _unwire_espalier_hooks(repo, False)

        data = json.loads(surface_contract.decode_bom(settings.read_bytes()))
        assert data["permissions"]["allow"] == ["Read"], (
            "uninstall destroyed an operator key while stripping our hooks"
        )


# ── §C8: one inventory for write, claim and uninstall (2026-09-11) ─────────


def _git_repo_with_readme(root: Path, *, own_gitignore: bool) -> Path:
    """A committed adopter tree: a README, a source file, and (optionally) one
    ignore line of the adopter's own so init APPENDS rather than creates."""
    root.mkdir(parents=True, exist_ok=True)
    for argv in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t.t"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(argv, cwd=root, check=True)
    (root / "README.md").write_text("# theirs\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    if own_gitignore:
        (root / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)
    return root


def _run_real_init(repo: Path) -> None:
    """The real ``init`` through argparse in a fresh process: a hand-built
    Namespace silently gets older behaviour (DEF-399b)."""
    result = subprocess.run(
        [sys.executable, "-m", "espalier.cli", "init", str(repo)],
        capture_output=True, text=True, check=False, encoding="utf-8",
    )
    assert result.returncode == 0, (result.stdout, result.stderr)


def _files_under(root: Path) -> set[str]:
    return {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and not p.relative_to(root).as_posix().startswith(".git/")
    }


def _buckets(report: dict) -> set[str]:
    return (
        set(report["deleted"])
        | set(report["already_missing"])
        | set(report["preserved_user_files"])
        | set(report["preserved_local_runtime"])
        | {f.split(":", 1)[0] for f in report["failures"]}
    )


def _simulate_sessions(repo: Path) -> None:
    """What a few Claude Code sessions leave on an initialised tree: hook
    bytecode, a stop_gate flag, a blueprint, a merge-settings backup."""
    compileall.compile_dir(str(repo / "tools" / "cc" / "hooks"), quiet=1)
    (repo / ".espalier-state").mkdir(exist_ok=True)
    (repo / ".espalier-state" / "flag").write_text("1\n", encoding="utf-8")
    (repo / "cc" / "blueprints").mkdir(parents=True, exist_ok=True)
    (repo / "cc" / "blueprints" / "20260911-000000-abc.json").write_text(
        "{}\n", encoding="utf-8"
    )
    # The deployed PostCompact hook rewrites this directly under cc/ on every
    # compaction -- the reviewers' driven miss on 2026-09-11: no prefix covers
    # it, and only the surface contract's runtime-generated list names it.
    (repo / "cc" / "_working_summary.md").write_text("# summary\n", encoding="utf-8")
    settings = repo / ".claude" / "settings.json"
    (repo / ".claude" / "settings.json.bak").write_bytes(settings.read_bytes())


class TestUninstallAccountsForEverySurvivor:
    """DEF-410d, driven: after a real ``init`` and a few sessions' worth of
    runtime state, ``clean-generated --execute`` leaves files behind on
    purpose -- and the contract is that every one of them is NAMED in a
    report bucket, so an adopter reconciling the report against ``ls`` can
    tell a deliberately kept file from a forgotten one. Before 2026-09-11 the
    integrity manifest's write-lock and the appended ``.gitignore`` block
    survived in no bucket at all (measured on a three-file tree: 29
    survivors, 27 named). The assertion is on the ABSENCE of an unaccounted
    survivor, never the presence of the known ones, so a new kind of runtime
    file cannot slip past it."""

    def test_execute_names_every_file_init_wrote_and_left(self, tmp_path):
        repo = _git_repo_with_readme(tmp_path / "adopter", own_gitignore=False)
        before = _files_under(repo)
        _run_real_init(repo)
        _simulate_sessions(repo)

        report = clean_generated_surface(repo, dry_run=False)

        survivors = _files_under(repo) - before
        unaccounted = sorted(p for p in survivors if p not in _buckets(report))
        assert unaccounted == [], (
            f"files the harness wrote survived the uninstall in no report "
            f"bucket: {unaccounted}. Report: {report}"
        )
        # The two escapes the driven re-count found at HEAD, by name.
        if os.name != "nt":
            # the lock is `fcntl`'s: on Windows the manifest writer has no
            # flock and never creates it, so there is no survivor to name
            assert ".espalier/.manifest.write.lock" in report["preserved_local_runtime"]
        assert ".gitignore" in report["preserved_user_files"], (
            "init created .gitignore and entries still guard preserved state, "
            "so the file must be named as kept"
        )
        # The adopter's README is not claimed as ours in either direction
        # (DEF-556).
        assert "README.md" not in report["preserved_user_files"]
        assert "README.md" not in report["deleted"]

    def test_dry_run_previews_the_same_verdicts_and_touches_nothing(self, tmp_path):
        """Absent a delete failure (where the execute keeps the entry guarding
        the file it could not remove), the preview and the execute agree."""
        repo = _git_repo_with_readme(tmp_path / "adopter", own_gitignore=True)
        _run_real_init(repo)
        _simulate_sessions(repo)
        snapshot = {p: (repo / p).read_bytes() for p in _files_under(repo)}

        preview = clean_generated_surface(repo, dry_run=True)

        assert {p: (repo / p).read_bytes() for p in _files_under(repo)} == snapshot, (
            "a dry run changed the tree"
        )
        executed = clean_generated_surface(repo, dry_run=False)
        for key in (
            "unwired_hooks", "gitignore_entries_removed", "gitignore_entries_kept",
            "gitignore_entries_kept_for",
        ):
            assert preview[key] == executed[key], (
                f"the preview's {key} disagrees with what --execute did: "
                f"{preview[key]} vs {executed[key]}"
            )
        assert set(preview["deleted"]) <= set(executed["deleted"])
        assert (repo / ".gitignore").read_text(encoding="utf-8").startswith(
            "node_modules/\n"
        ), "the adopter's own ignore line was touched"

    def test_bytecode_under_a_managed_prefix_goes_with_the_scripts(self, tmp_path):
        repo = _git_repo_with_readme(tmp_path / "adopter", own_gitignore=False)
        _run_real_init(repo)
        _simulate_sessions(repo)
        cache = repo / "tools" / "cc" / "hooks" / "__pycache__"
        assert cache.is_dir(), "the fixture did not compile the hooks"

        report = clean_generated_surface(repo, dry_run=False)

        assert not cache.exists()
        assert "tools/cc/hooks/__pycache__" in report["deleted"]
        assert not (repo / "tools").exists(), (
            "tools/ outlived the uninstall holding nothing but bytecode"
        )

    def test_adopter_bytecode_outside_managed_prefixes_survives(self, tmp_path):
        repo = _git_repo_with_readme(tmp_path / "adopter", own_gitignore=False)
        _run_real_init(repo)
        theirs = repo / "src" / "__pycache__" / "app.cpython-3.pyc"
        theirs.parent.mkdir()
        theirs.write_bytes(b"\x00")

        report = clean_generated_surface(repo, dry_run=False)

        assert theirs.exists()
        assert "src/__pycache__" not in report["deleted"]
        # ...and the two any-depth entries that guard it are kept, not retired.
        assert {"__pycache__/", "*.pyc"} <= set(report["gitignore_entries_kept"])

    def test_a_file_the_adopter_committed_is_theirs_not_runtime(self, tmp_path):
        """A path in git's index is the adopter's whatever wrote it first: the
        freshness manifest they chose to commit must not be named as
        disposable runtime state the docs tell them to clear by hand."""
        repo = _git_repo_with_readme(tmp_path / "adopter", own_gitignore=False)
        _run_real_init(repo)
        canon = repo / ".espalier" / "freshness.json"
        canon.write_text("{}\n", encoding="utf-8")
        subprocess.run(["git", "add", "-f", ".espalier/freshness.json"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "pin"], cwd=repo, check=True)

        report = clean_generated_surface(repo, dry_run=False)

        assert canon.exists()
        assert ".espalier/freshness.json" not in report["preserved_local_runtime"]
        assert ".espalier/integrity.json" in report["preserved_local_runtime"]
        assert ".espalier/" in report["gitignore_entries_kept"]

    def test_init_writes_a_delimited_block_and_uninstall_retires_it_exactly(self, tmp_path):
        """With the end marker, a line the adopter appends straight under the
        block -- even one spelled like a harness entry -- is outside it."""
        from espalier.cli import GITIGNORE_BLOCK_FOOTER as F, GITIGNORE_BLOCK_HEADER as H
        repo = _git_repo_with_readme(tmp_path / "adopter", own_gitignore=True)
        _run_real_init(repo)
        gitignore = repo / ".gitignore"
        text = gitignore.read_text(encoding="utf-8")
        assert text.startswith("node_modules/\n\n" + H + "\n")
        assert text.endswith("\n" + F + "\n")
        with gitignore.open("a", encoding="utf-8") as fh:
            fh.write("*.pyc\nmine/\n")

        report = clean_generated_surface(repo, dry_run=False)

        after = gitignore.read_text(encoding="utf-8")
        assert after.startswith("node_modules/\n\n" + H + "\n")
        assert after.endswith("\n" + F + "\n*.pyc\nmine/\n"), after
        assert ".espalier-state/" not in after
        assert report["gitignore_entries_removed"].count("*.pyc") == 1, (
            "the adopter's duplicate past the footer was read as ours"
        )


class TestBytecodeSweep:
    """The cache sweep is the one deletion no marker vouches for, so it is
    scoped to the single managed prefix where the harness deploys Python;
    an adopter's Python-backed skill keeps its own cache."""

    def test_every_deployed_python_file_lives_under_the_sweep_root(self, tmp_path):
        from espalier.cleanup import _BYTECODE_SWEEP_ROOT
        from espalier.managed_inventory import get_managed_public_files
        outside = [
            rel for rel in get_managed_public_files(tmp_path)
            if rel.endswith(".py") and not rel.startswith(_BYTECODE_SWEEP_ROOT)
        ]
        assert outside == [], (
            f"managed Python outside the bytecode sweep root: {outside}"
        )

    def test_an_adopters_python_skill_keeps_its_cache(self, harness_repo):
        cache = harness_repo / ".claude" / "skills" / "mine" / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "tool.cpython-3.pyc").write_bytes(b"\x00")
        (harness_repo / ".claude" / "skills" / "mine" / "SKILL.md").write_text(
            "# mine\n", encoding="utf-8"
        )

        report = clean_generated_surface(harness_repo, dry_run=False)

        assert cache.exists()
        assert ".claude/skills/mine/__pycache__" not in report["deleted"]


class TestGitignoreBlockRetire:
    """DEF-552: ``init`` appends a block under ``GITIGNORE_BLOCK_HEADER``; an
    uninstall retires the entries in it that no surviving file needs, keeps
    the ones still guarding preserved runtime state, and never reads a line
    outside the block. Both spellings of one entry match through
    ``cli._gitignore_key``."""

    @staticmethod
    def _tree(tmp_path: Path, gitignore_text: str, *present: str) -> Path:
        repo = tmp_path / "adopter"
        repo.mkdir()
        # bytes: `write_text` translates `\n` to os.linesep, so on Windows a
        # CRLF fixture arrived as CR CR LF and the preserved-endings row read
        # the engine's faithful copy as a defect (Portability, 2026-09-23)
        (repo / ".gitignore").write_bytes(gitignore_text.encode("utf-8"))
        for rel in present:
            target = repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x\n", encoding="utf-8")
        return repo

    def test_entries_nothing_needs_go_and_guarding_entries_stay(self, tmp_path):
        from espalier.cli import GITIGNORE_BLOCK_HEADER, REQUIRED_GITIGNORE
        text = (
            "node_modules/\n\n" + GITIGNORE_BLOCK_HEADER + "\n"
            + "\n".join(REQUIRED_GITIGNORE) + "\n"
        )
        repo = self._tree(
            tmp_path, text, ".claude/settings.json", ".espalier/integrity.json",
        )

        report = clean_generated_surface(repo, dry_run=False)

        guarding = {".claude/settings.json", ".espalier/"}
        assert set(report["gitignore_entries_kept"]) == guarding
        assert set(report["gitignore_entries_removed"]) == set(REQUIRED_GITIGNORE) - guarding
        assert (repo / ".gitignore").read_text(encoding="utf-8") == (
            "node_modules/\n\n" + GITIGNORE_BLOCK_HEADER + "\n"
            ".claude/settings.json\n.espalier/\n"
        )
        assert ".gitignore" in report["preserved_user_files"]

    def test_an_emptied_block_goes_whole_and_an_init_created_file_with_it(self, tmp_path):
        from espalier.cli import GITIGNORE_BLOCK_HEADER
        repo = self._tree(
            tmp_path, "\n" + GITIGNORE_BLOCK_HEADER + "\ncc/blueprints/\n.espalier-state/\n",
        )

        report = clean_generated_surface(repo, dry_run=False)

        assert not (repo / ".gitignore").exists()
        assert ".gitignore" in report["deleted"]
        assert report["gitignore_entries_kept"] == []
        assert set(report["gitignore_entries_removed"]) == {
            "cc/blueprints/", ".espalier-state/",
        }

    def test_lines_outside_the_blocks_are_never_read(self, tmp_path):
        from espalier.cli import GITIGNORE_BLOCK_HEADER as H
        # Two legacy blocks (a re-init appended the second) with the adopter's
        # own lines before, between and after them. The second block's edge
        # is uncertain -- `dist/` follows it with no blank line -- so its
        # entry is retired but its header stays.
        text = (
            "*.log\n\n" + H + "\ncc/blueprints/\n.espalier/\n"
            + "\n# mine\nbuild/\n\n" + H + "\n.espalier-state/\n" + "dist/\n"
        )
        repo = self._tree(tmp_path, text, ".espalier/integrity.json")

        clean_generated_surface(repo, dry_run=False)

        assert (repo / ".gitignore").read_text(encoding="utf-8") == (
            "*.log\n\n" + H + "\n.espalier/\n" + "\n# mine\nbuild/\n\n" + H + "\n" + "dist/\n"
        )

    def test_a_footer_delimited_block_has_an_exact_edge(self, tmp_path):
        from espalier.cli import GITIGNORE_BLOCK_FOOTER as F, GITIGNORE_BLOCK_HEADER as H
        # The adopter appended their own `*.pyc` and `mine.txt` straight under
        # the footer; the harness's `*.pyc` above it is retired, theirs is not.
        repo = self._tree(tmp_path, "\n" + H + "\n*.pyc\n" + F + "\n*.pyc\nmine.txt\n")

        report = clean_generated_surface(repo, dry_run=False)

        assert (repo / ".gitignore").read_text(encoding="utf-8") == "*.pyc\nmine.txt\n"
        assert report["gitignore_entries_removed"] == ["*.pyc"]

    def test_a_legacy_block_with_an_uncertain_edge_keeps_its_header(self, tmp_path):
        from espalier.cli import GITIGNORE_BLOCK_HEADER as H
        # `build/` may be the adopter's line or an entry a later release
        # dropped; either way nothing past it is read and the header stays.
        repo = self._tree(tmp_path, "\n" + H + "\n.espalier-state/\nbuild/\n")

        report = clean_generated_surface(repo, dry_run=False)

        assert (repo / ".gitignore").read_text(encoding="utf-8") == "\n" + H + "\nbuild/\n"
        assert report["gitignore_entries_removed"] == [".espalier-state/"]

    def test_an_adopter_comment_inside_a_legacy_block_stops_the_scan(self, tmp_path):
        from espalier.cli import GITIGNORE_BLOCK_HEADER as H
        repo = self._tree(
            tmp_path, "\n" + H + "\n.espalier-state/\n# keep this one\ncc/blueprints/\n",
        )

        report = clean_generated_surface(repo, dry_run=False)

        assert (repo / ".gitignore").read_text(encoding="utf-8") == (
            "\n" + H + "\n# keep this one\ncc/blueprints/\n"
        )
        assert report["gitignore_entries_removed"] == [".espalier-state/"]
        assert report["gitignore_entries_kept"] == []

    def test_a_block_nothing_was_retired_from_is_not_touched(self, tmp_path):
        from espalier.cli import GITIGNORE_BLOCK_HEADER as H
        # An empty header the adopter left behind, above a block that does
        # retire something: the first is not ours to tidy.
        repo = self._tree(tmp_path, "\n" + H + "\nmine/\n\n" + H + "\n__pycache__/\n")

        report = clean_generated_surface(repo, dry_run=False)

        assert (repo / ".gitignore").read_text(encoding="utf-8") == "\n" + H + "\nmine/\n"
        assert report["gitignore_entries_removed"] == ["__pycache__/"]

    def test_crlf_line_endings_are_preserved(self, tmp_path):
        from espalier.cli import GITIGNORE_BLOCK_HEADER as H
        repo = self._tree(
            tmp_path,
            "\r\n" + H + "\r\n.espalier/\r\ncc/blueprints/\r\n",
            ".espalier/integrity.json",
        )

        report = clean_generated_surface(repo, dry_run=False)

        assert (repo / ".gitignore").read_bytes() == (
            "\r\n" + H + "\r\n.espalier/\r\n"
        ).encode("utf-8")
        assert report["gitignore_entries_kept"] == [".espalier/"]

    def test_no_header_means_the_entries_are_not_ours(self, tmp_path):
        from espalier.cli import REQUIRED_GITIGNORE
        repo = self._tree(tmp_path, "\n".join(REQUIRED_GITIGNORE) + "\n")
        before = (repo / ".gitignore").read_bytes()

        report = clean_generated_surface(repo, dry_run=False)

        assert (repo / ".gitignore").read_bytes() == before
        assert report["gitignore_entries_removed"] == []
        assert report["gitignore_entries_kept"] == []
        assert ".gitignore" not in _buckets(report)

    def test_the_bare_spelling_matches_the_anchored_requirement(self, tmp_path):
        from espalier.cli import GITIGNORE_BLOCK_HEADER as H
        # A tree initialised before the anchoring fix carries `reports/` for
        # today's `/reports/`; the key makes them one entry.
        repo = self._tree(
            tmp_path, "\n" + H + "\nreports/\n", "reports/repo_fingerprint.json",
        )

        report = clean_generated_surface(repo, dry_run=False)

        assert report["gitignore_entries_kept"] == ["reports/"]
        assert (repo / ".gitignore").read_text(encoding="utf-8") == "\n" + H + "\nreports/\n"

        (repo / "reports" / "repo_fingerprint.json").unlink()
        report = clean_generated_surface(repo, dry_run=False)

        assert report["gitignore_entries_removed"] == ["reports/"]
        assert not (repo / ".gitignore").exists()

    def test_dry_run_computes_the_verdicts_and_leaves_the_file_byte_identical(self, tmp_path):
        from espalier.cli import GITIGNORE_BLOCK_HEADER as H
        repo = self._tree(
            tmp_path, "\n" + H + "\ncc/blueprints/\n.espalier/\n", ".espalier/integrity.json",
        )
        before = (repo / ".gitignore").read_bytes()

        report = clean_generated_surface(repo, dry_run=True)

        assert (repo / ".gitignore").read_bytes() == before
        assert report["gitignore_entries_removed"] == ["cc/blueprints/"]
        assert report["gitignore_entries_kept"] == [".espalier/"]


def _plant_survivor(repo: Path, entry: str) -> str:
    """One file that required-gitignore ``entry`` guards, placed where the
    entry's own grammar puts it: a root-anchored or multi-component directory
    at that path, a single-component unanchored one (git matches it at every
    depth) one level down under ``src/``, a glob with each ``*`` spelled out
    (a probe name, then ``1``), a file as itself. Returns the repo-relative
    posix path it wrote. The shapes the roster gate bans (``?``, ``[``, ``!``,
    ``**`` -- ``test_required_entry_shapes_are_covered``) never reach here; a
    new shape past that gate is written as a literal file, which the guard
    will not match, so the derived test reds until the planter learns it."""
    pattern = entry.lstrip("/")
    body = pattern.rstrip("/")
    any_depth = not entry.startswith("/") and "/" not in body
    if entry.endswith("/"):
        rel = f"src/{body}/probe" if any_depth else f"{body}/probe"
    elif "*" in pattern:
        name = pattern.replace("*", "probe", 1).replace("*", "1")
        rel = f"src/{name}" if any_depth else name
    else:
        rel = pattern
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x\n", encoding="utf-8")
    return rel


class TestKeptEntriesNameTheirWitness:
    """DEF-808: a required entry is kept because SOMETHING matching it
    survives, and until 2026-09-15 the report never said what. Driven on the
    Windows host (walk 3, leg 5-F) and again on POSIX: an adopter's own
    ``.claude/mine.json.new`` kept ``.claude/*.new`` and appeared in no
    bucket, so the line read as kept for a reason the report never gave.
    Every kept entry now carries the surviving path that keeps it, under
    ``gitignore_entries_kept_for``."""

    def test_a_file_the_harness_never_wrote_is_named_as_the_witness(self, tmp_path):
        repo = _git_repo_with_readme(tmp_path / "adopter", own_gitignore=False)
        _run_real_init(repo)
        decoy = repo / ".claude" / "mine.json.new"
        decoy.write_text('{"mine": 1}\n', encoding="utf-8")

        report = clean_generated_surface(repo, dry_run=False)

        assert ".claude/*.new" in report["gitignore_entries_kept"]
        assert report["gitignore_entries_kept_for"][".claude/*.new"] == (
            ".claude/mine.json.new"
        ), report["gitignore_entries_kept_for"]
        assert decoy.is_file(), "the adopter's own file is theirs to keep"

    def test_an_adopter_bytecode_file_is_the_witness_of_the_any_depth_entries(
        self, tmp_path
    ):
        """The same shape one directory deeper: the adopter's own cache under
        ``src/`` keeps ``__pycache__/`` and ``*.pyc``, and the report names
        the file rather than leaving two kept lines unexplained."""
        repo = _git_repo_with_readme(tmp_path / "adopter", own_gitignore=False)
        _run_real_init(repo)
        theirs = repo / "src" / "__pycache__" / "app.cpython-314.pyc"
        theirs.parent.mkdir()
        theirs.write_bytes(b"\x00")

        report = clean_generated_surface(repo, dry_run=False)

        witness = "src/__pycache__/app.cpython-314.pyc"
        assert report["gitignore_entries_kept_for"]["__pycache__/"] == witness
        assert report["gitignore_entries_kept_for"]["*.pyc"] == witness

    def test_every_kept_entry_names_the_survivor_planted_for_it(self, tmp_path):
        """Derived over every REQUIRED_GITIGNORE shape: one survivor planted
        per entry, from the entry itself, and each kept entry names exactly
        its own. A new entry enrols itself here and reds until the guard can
        name what it keeps."""
        from espalier.cli import (
            GITIGNORE_BLOCK_FOOTER, GITIGNORE_BLOCK_HEADER, REQUIRED_GITIGNORE,
        )
        from espalier.cleanup import _retire_gitignore_block
        repo = tmp_path / "adopter"
        repo.mkdir()
        planted = {entry: _plant_survivor(repo, entry) for entry in REQUIRED_GITIGNORE}
        (repo / ".gitignore").write_text(
            GITIGNORE_BLOCK_HEADER + "\n" + "\n".join(REQUIRED_GITIGNORE) + "\n"
            + GITIGNORE_BLOCK_FOOTER + "\n",
            encoding="utf-8",
        )

        result = _retire_gitignore_block(repo, dry_run=True, doomed=set())

        assert result["removed"] == []
        assert sorted(result["kept"]) == sorted(REQUIRED_GITIGNORE)
        assert result["kept_for"] == planted
        assert set(result["kept_for"]) == set(result["kept"])

    def test_two_blocks_list_the_entry_twice_and_key_it_once(self, tmp_path):
        """A re-init that appended a second harness block: ``kept`` carries
        the entry once per block (the entries as they stood), ``kept_for``
        once. The two agree as sets, never by length -- a consumer zipping
        them is wrong, and the docstring says so."""
        from espalier.cli import GITIGNORE_BLOCK_HEADER
        from espalier.cleanup import _retire_gitignore_block
        repo = tmp_path / "adopter"
        repo.mkdir()
        block = GITIGNORE_BLOCK_HEADER + "\n.espalier/\ncc/blueprints/\n"
        (repo / ".gitignore").write_text(block + "\n" + block, encoding="utf-8")
        (repo / ".espalier").mkdir()
        (repo / ".espalier" / "integrity.json").write_text("{}\n", encoding="utf-8")

        result = _retire_gitignore_block(repo, dry_run=True, doomed=set())

        assert result["kept"] == [".espalier/", ".espalier/"]
        assert result["removed"] == ["cc/blueprints/", "cc/blueprints/"]
        assert result["kept_for"] == {".espalier/": ".espalier/integrity.json"}
        assert set(result["kept_for"]) == set(result["kept"])

    def test_a_retired_entry_has_no_witness(self, tmp_path):
        """The two views agree: an entry under ``kept_for`` is kept, a removed
        one is absent from it, and the report carries the map through."""
        from espalier.cli import GITIGNORE_BLOCK_HEADER
        repo = tmp_path / "adopter"
        repo.mkdir()
        (repo / ".gitignore").write_text(
            GITIGNORE_BLOCK_HEADER + "\n.espalier/\ncc/blueprints/\n", encoding="utf-8"
        )
        (repo / ".espalier").mkdir()
        (repo / ".espalier" / "integrity.json").write_text("{}\n", encoding="utf-8")

        report = clean_generated_surface(repo, dry_run=True)

        assert report["gitignore_entries_removed"] == ["cc/blueprints/"]
        assert report["gitignore_entries_kept"] == [".espalier/"]
        assert report["gitignore_entries_kept_for"] == {
            ".espalier/": ".espalier/integrity.json"
        }


class TestSettingsUnwireFinishesTheJob:
    """A wheel-driven walk (2026-09-05) saw an uninstalled tree whose
    ``settings.json`` still ran ``tools/cc/statusline.py`` -- deleted with
    ``tools/cc/`` -- so every prompt render printed the fallback text; the
    managed sentinel and an emptied ``hooks`` key outlived the uninstall too,
    and the dry run said nothing about any of it."""

    @staticmethod
    def _settings(repo: Path) -> dict:
        return json.loads(
            (repo / ".claude" / "settings.json").read_text(encoding="utf-8")
        )

    @staticmethod
    def _wire(repo: Path, command: str) -> None:
        path = repo / ".claude" / "settings.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["statusLine"] = {"type": "command", "command": command}
        data["_espalier_managed"] = True
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def test_the_harness_statusline_goes_with_its_script(self, harness_repo):
        self._wire(
            harness_repo,
            'python3 "${CLAUDE_PROJECT_DIR}/tools/cc/statusline.py" || echo fallback',
        )

        report = clean_generated_surface(harness_repo, dry_run=False)

        assert "statusLine" not in self._settings(harness_repo)
        assert "statusLine:statusline.py" in report["unwired_hooks"]

    def test_an_adopters_own_statusline_survives(self, harness_repo):
        self._wire(harness_repo, "~/bin/my-status.sh")

        clean_generated_surface(harness_repo, dry_run=False)

        assert self._settings(harness_repo)["statusLine"] == {
            "type": "command", "command": "~/bin/my-status.sh",
        }

    def test_the_sentinel_and_an_emptied_hooks_key_are_dropped(self, harness_repo):
        self._wire(harness_repo, "x")

        report = clean_generated_surface(harness_repo, dry_run=False)

        after = self._settings(harness_repo)
        assert "_espalier_managed" not in after
        assert "key:_espalier_managed" in report["unwired_hooks"]
        assert "hooks" not in after, "an emptied hooks key is hollow scaffolding"
        assert after["permissions"] == {"allow": ["Read", "Write"]}

    def test_dry_run_previews_the_strip_and_writes_nothing(self, harness_repo):
        self._wire(harness_repo, "python3 tools/cc/statusline.py")
        path = harness_repo / ".claude" / "settings.json"
        before = path.read_bytes()

        report = clean_generated_surface(harness_repo, dry_run=True)

        assert path.read_bytes() == before
        assert "statusLine:statusline.py" in report["unwired_hooks"]
        assert any(
            ":" in label and label.split(":", 1)[0] not in ("statusLine", "key")
            for label in report["unwired_hooks"]
        ), "the hook entries themselves must be previewed too"

    def test_the_statusline_script_is_a_managed_tool(self):
        from espalier.cleanup import _STATUSLINE_SCRIPT, _STATUSLINE_SHIM
        from espalier.managed_paths import STANDARD_MANAGED_TOOLS
        assert _STATUSLINE_SCRIPT in STANDARD_MANAGED_TOOLS, (
            "the unwire names a script the cleanup does not delete"
        )
        assert _STATUSLINE_SHIM in STANDARD_MANAGED_TOOLS, (
            "the unwire names a shim the cleanup does not delete"
        )

    def test_the_windows_shim_statusline_goes_with_its_shim(self, harness_repo):
        """DEF-729: an nt render names statusline.py nowhere -- the head is
        the shim -- so the unwire must match the shim, and its label says
        which file the wiring ran."""
        self._wire(
            harness_repo,
            '"${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" python',
        )

        report = clean_generated_surface(harness_repo, dry_run=False)

        assert "statusLine" not in self._settings(harness_repo)
        assert "statusLine:statusline.cmd" in report["unwired_hooks"]
        assert "statusLine:statusline.py" not in report["unwired_hooks"]


class TestRenderArtifactAccounting:
    """DEF-737: the files ``init`` and ``merge-settings`` render beside
    ``settings.json`` are the harness's own. Init's untracked-conflict
    advisory must not name them back as the adopter's uncommitted work, and
    an uninstall must account for each one present."""

    def test_backup_copies_are_preserved_and_named(self, harness_repo):
        for name in ("settings.json.bak", "settings.json.bak.3"):
            (harness_repo / ".claude" / name).write_text("{}\n", encoding="utf-8")

        report = clean_generated_surface(harness_repo, dry_run=False)

        for name in ("settings.json.bak", "settings.json.bak.3"):
            assert f".claude/{name}" in report["preserved_user_files"]
            assert (harness_repo / ".claude" / name).exists()
        assert report["settings_backups_kept"] == [
            ".claude/settings.json.bak", ".claude/settings.json.bak.3",
        ]

    def test_settings_backups_are_listed_in_ladder_order(self, harness_repo):
        """DEF-809: the copies are the adopter's own pre-wire settings, listed
        again as one view in the order they were taken (a numeric climb, not
        a lexical sort), so the count is visible without reading the whole
        preserved list; the ``.new`` template is not one of them."""
        for name in ("settings.json.bak.10", "settings.json.bak", "settings.json.bak.2"):
            (harness_repo / ".claude" / name).write_text("{}\n", encoding="utf-8")
        (harness_repo / ".claude" / "settings.json.new").write_text("{}\n", encoding="utf-8")

        report = clean_generated_surface(harness_repo, dry_run=True)

        assert report["settings_backups_kept"] == [
            ".claude/settings.json.bak",
            ".claude/settings.json.bak.2",
            ".claude/settings.json.bak.10",
        ]
        assert set(report["settings_backups_kept"]) <= set(report["preserved_user_files"])

    def test_no_backup_means_an_empty_ladder(self, harness_repo):
        report = clean_generated_surface(harness_repo, dry_run=True)
        assert report["settings_backups_kept"] == []

    def test_only_the_exact_shapes_are_render_artifacts(self):
        from espalier.managed_inventory import is_render_artifact
        for rel in (
            ".claude/settings.json.new",
            ".claude/settings.json.bak",
            ".claude/settings.json.bak.12",
            ".claude\\settings.json.new",
        ):
            assert is_render_artifact(rel), rel
        for rel in (
            ".claude/notes.new",
            ".claude/settings.json.bak.x",
            ".claude/sub/settings.json.new",
            "settings.json.new",
            ".claude/settings.local.json.new",
        ):
            assert not is_render_artifact(rel), rel

    def test_the_ladder_grammar_has_one_spelling(self):
        """DEF-809: the predicate, the wire's rung scan and the uninstall
        listing all read ``settings_backup_rung``; a name it rejects is on no
        ladder anywhere, and a digit ``int`` would refuse never reaches it."""
        from espalier.managed_inventory import is_render_artifact, settings_backup_rung
        assert settings_backup_rung("settings.json.bak") == 0
        assert settings_backup_rung("settings.json.bak.2") == 2
        assert settings_backup_rung("settings.json.bak.10") == 10
        assert settings_backup_rung("mine.json.bak.3", base="mine.json") == 3
        for name in (
            "settings.json", "settings.json.bakup", "settings.json.bak.old",
            "settings.json.bak.", "settings.json.bak.1.bak", "settings.json.bak.\u00b2",
            "settings.json.bak.-1", "settings.json.bak.1a", "mine.json.bak",
        ):
            assert settings_backup_rung(name) is None, name
        assert is_render_artifact(".claude/settings.json.bak.\u00b2") is False

    def test_init_advisory_recognises_its_own_render(self):
        from espalier import cli
        assert cli._is_harness_owned(".claude/settings.json.new", set(), fold=False)
        assert cli._is_harness_owned(".claude/settings.json.bak.2", set(), fold=True)
        assert not cli._is_harness_owned(".claude/notes.new", set(), fold=False), (
            "a .new the adopter authored is theirs and must be named"
        )


class TestLocalRuntimePrefixes:
    """One owner for "is this runtime file ours?": the inventory's prefixes,
    read by init's advisory and by cleanup's accounting, each covered by a
    required ``.gitignore`` entry so the state they hold never stages."""

    def test_every_prefix_is_covered_by_a_required_gitignore_entry(self):
        from espalier.cli import REQUIRED_GITIGNORE, _gitignore_key
        from espalier.managed_inventory import get_local_runtime_prefixes
        keys = {_gitignore_key(entry) for entry in REQUIRED_GITIGNORE}
        uncovered = [
            prefix for prefix in get_local_runtime_prefixes()
            if _gitignore_key(prefix) not in keys
        ]
        assert uncovered == [], (
            f"runtime roots no required .gitignore entry covers: {uncovered}"
        )

    def test_init_advisory_and_cleanup_read_the_same_owner(self):
        from espalier import cli
        from espalier.managed_inventory import get_local_runtime_prefixes
        assert cli._HARNESS_OWNED_PREFIXES == get_local_runtime_prefixes()

    def test_every_adopter_runtime_generated_path_is_nameable(self, tmp_path):
        """Derived from the canon, not from a fixture: each path deployed code
        creates later (the surface contract's list, each member with a cited
        writer) is named by the accounting once present. The working summary
        under cc/ is the one no prefix covers."""
        from espalier import surface_contract
        from espalier.managed_inventory import local_state_on_disk
        for rel in surface_contract.ADOPTER_RUNTIME_GENERATED:
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x\n", encoding="utf-8")

        named = set(local_state_on_disk(tmp_path))

        assert set(surface_contract.ADOPTER_RUNTIME_GENERATED) <= named

    def test_every_file_shaped_required_gitignore_entry_is_nameable(self, tmp_path):
        """A required ignore entry that names one file names a file the
        harness writes; the accounting must be able to name it back."""
        from espalier.cli import REQUIRED_GITIGNORE
        from espalier.managed_inventory import local_state_on_disk
        files = [
            entry for entry in REQUIRED_GITIGNORE
            if not entry.endswith("/") and not any(c in entry for c in "*?[")
        ]
        assert files, "REQUIRED_GITIGNORE names no single file any more"
        for rel in files:
            target = tmp_path / rel.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x\n", encoding="utf-8")

        named = set(local_state_on_disk(tmp_path))

        assert {rel.lstrip("/") for rel in files} <= named

    def test_local_state_on_disk_names_files_under_the_prefixes(self, tmp_path):
        from espalier.managed_inventory import local_state_on_disk
        ours = (
            ".espalier/.manifest.write.lock",
            ".espalier-state/stop_flag",
            "reports/scan_prints.json",
            "cc/blueprints/a.json",
            "cc/execution_plan.json",
        )
        for rel in (*ours, "src/app.py"):
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x\n", encoding="utf-8")

        named = set(local_state_on_disk(tmp_path))

        assert set(ours) <= named
        assert "src/app.py" not in named


@requires_symlink
class TestSymlinkedAdopterFiles:
    """DEF-784: an adopter whose ``.gitignore`` or ``settings.json`` is a
    symlink into a dotfiles checkout. The engine rule (``_atomic_io``): the
    file is edited where it lives and the link stays. Before the fix init's
    append wrote through the link while the retire on uninstall, the settings
    merge and the settings unwire replaced it with a regular file, so the
    shared file kept the harness's block and the repo lost its link."""

    @staticmethod
    def _linked_gitignore(tmp_path: Path, text: str) -> tuple[Path, Path]:
        shared = tmp_path / "dotfiles" / "gitignore"
        shared.parent.mkdir()
        shared.write_text(text, encoding="utf-8")
        repo = tmp_path / "adopter"
        repo.mkdir()
        (repo / ".gitignore").symlink_to(shared)
        return repo, shared

    def test_the_retire_edits_the_file_behind_the_link_and_keeps_the_link(self, tmp_path):
        from espalier.cli import GITIGNORE_BLOCK_HEADER as H
        repo, shared = self._linked_gitignore(
            tmp_path, "*.log\n\n" + H + "\ncc/blueprints/\n.espalier/\n",
        )
        (repo / ".espalier").mkdir()
        (repo / ".espalier" / "integrity.json").write_text("{}\n", encoding="utf-8")

        report = clean_generated_surface(repo, dry_run=False)

        assert report["gitignore_entries_removed"] == ["cc/blueprints/"]
        assert (repo / ".gitignore").is_symlink(), (
            "the retire replaced the adopter's link with a regular file"
        )
        assert shared.read_text(encoding="utf-8") == "*.log\n\n" + H + "\n.espalier/\n"

    def test_an_emptied_file_behind_a_link_is_not_deleted(self, tmp_path):
        """init never creates a link, so an emptied linked file is not init's
        to delete: the link stays and the emptied text goes through it."""
        from espalier.cli import GITIGNORE_BLOCK_HEADER as H
        repo, shared = self._linked_gitignore(tmp_path, "\n" + H + "\ncc/blueprints/\n")

        report = clean_generated_surface(repo, dry_run=False)

        assert report["gitignore_entries_removed"] == ["cc/blueprints/"]
        assert (repo / ".gitignore").is_symlink()
        assert shared.exists()
        assert shared.read_text(encoding="utf-8").strip() == ""
        assert ".gitignore" not in report["deleted"]
        assert ".gitignore" in report["preserved_user_files"], (
            "an emptied linked .gitignore is on disk and the adopter's; it "
            "must be named in a bucket, not fall between them"
        )

    def test_init_appends_through_the_link_and_the_retire_takes_it_back_out(self, tmp_path, capsys):
        from espalier import cli
        repo, shared = self._linked_gitignore(tmp_path, "*.log\n")

        cli._handle_gitignore(repo, write_gitignore=True)

        assert (repo / ".gitignore").is_symlink()
        assert cli.GITIGNORE_BLOCK_HEADER in shared.read_text(encoding="utf-8")

        clean_generated_surface(repo, dry_run=False)

        assert (repo / ".gitignore").is_symlink()
        assert shared.read_text(encoding="utf-8") == "*.log\n"

    def test_the_settings_merge_and_unwire_edit_the_file_behind_the_link(self, tmp_path):
        from espalier.cleanup import _unwire_espalier_hooks
        from espalier.cli import merge_hooks_into_settings
        shared = tmp_path / "dotfiles" / "claude-settings.json"
        shared.parent.mkdir()
        shared.write_text(
            json.dumps({"permissions": {"allow": ["Read"]}}, indent=2) + "\n",
            encoding="utf-8",
        )
        repo = tmp_path / "adopter"
        (repo / ".claude").mkdir(parents=True)
        link = repo / ".claude" / "settings.json"
        link.symlink_to(shared)

        merge_hooks_into_settings(link, repo_root=repo)

        assert link.is_symlink(), "init's merge replaced the adopter's link"
        assert "tools/cc/hooks" in shared.read_text(encoding="utf-8")

        unwired = _unwire_espalier_hooks(repo, False)

        assert unwired
        assert link.is_symlink(), "the unwire replaced the adopter's link"
        after = json.loads(shared.read_text(encoding="utf-8"))
        assert "tools/cc/hooks" not in json.dumps(after)
        assert after["permissions"] == {"allow": ["Read"]}
