"""Tests for espalier.surface_contract — the canonical managed-surface authority.

Pack 1 creates the authority; this file locks its shape so later packs can
rely on it without reintroducing the drift Pack 1 was built to end.
"""
# slow-exempt: the one subprocess call is a single fast `git check-ignore --no-index`
# over a dozen probe paths (the task-pack boundary parity, 2026-09-21)
from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

from _legacy_pathlib import probes_raise_on_eacces
from _locked import locked
from espalier import surface_contract as sc

REPO_ROOT = Path(__file__).resolve().parent.parent


STATIC_GETTERS = [
    sc.get_required_init_files,
    sc.get_canonical_hook_scripts,
    sc.get_managed_report_paths,
    sc.get_internal_path_prefixes,
    sc.get_internal_filename_patterns,
    sc.get_transient_path_patterns,
    sc.get_local_only_paths,
    sc.get_public_release_exclusions,
    sc.get_protected_mutation_paths,
    sc.get_protected_mutation_prefixes,
    sc.get_protected_integrity_paths,
    sc.get_protected_ci_files,
    sc.get_protected_ci_prefixes,
]


class TestStaticInventories:
    @pytest.mark.parametrize("getter", STATIC_GETTERS)
    def test_inventory_non_empty(self, getter):
        assert len(getter()) > 0

    @pytest.mark.parametrize("getter", STATIC_GETTERS)
    def test_inventory_sorted(self, getter):
        items = list(getter())
        assert items == sorted(items)

    @pytest.mark.parametrize("getter", STATIC_GETTERS)
    def test_inventory_forward_slash_only(self, getter):
        for item in getter():
            assert "\\" not in item, f"backslash in {getter.__name__}: {item!r}"

    @pytest.mark.parametrize("getter", STATIC_GETTERS)
    def test_inventory_is_immutable(self, getter):
        assert isinstance(getter(), (tuple, frozenset))

    def test_canonical_hook_scripts_exact_set(self):
        expected = {
            "config_guard.py",
            "context_reinject_failure.py",  # TP-163
            "plan_guard.py",
            "post_compact.py",
            "post_write_check.py",
            "reflect_trigger.py",
            "session_start.py",
            "stop_gate.py",
            "subagent_start.py",  # TP-163
            "subagent_stop.py",  # TP-40
            "task_router.py",
            "write_guard.py",
        }
        assert set(sc.get_canonical_hook_scripts()) == expected

    def test_required_init_files_includes_cc_docs(self):
        required = set(sc.get_required_init_files())
        assert "cc/LIVE_SURFACE.md" in required
        assert "cc/COMMANDS.md" in required
        assert "cc/PACK_MANIFEST.txt" in required

    def test_managed_reports_includes_harness_config(self):
        reports = set(sc.get_managed_report_paths())
        assert "reports/harness_config.json" in reports
        assert "reports/repo_fingerprint.json" in reports


class TestDiscoveryAgainstRealRepo:
    def test_discover_wired_hooks_exact_set(self, initialized_repo_root):
        # TP-40: 9 -> 10 hooks (added subagent_stop.py). TP-163: 10 -> 12
        # (added subagent_start.py + context_reinject_failure.py). Test name
        # reflects "expected set," not a hardcoded count.
        hooks = sc.discover_wired_hooks(initialized_repo_root)
        assert set(hooks) == {
            "tools/cc/hooks/session_start.py",
            "tools/cc/hooks/task_router.py",
            "tools/cc/hooks/plan_guard.py",
            "tools/cc/hooks/write_guard.py",
            "tools/cc/hooks/config_guard.py",
            "tools/cc/hooks/post_write_check.py",
            "tools/cc/hooks/reflect_trigger.py",
            "tools/cc/hooks/stop_gate.py",
            "tools/cc/hooks/subagent_stop.py",
            "tools/cc/hooks/post_compact.py",
            "tools/cc/hooks/subagent_start.py",
            "tools/cc/hooks/context_reinject_failure.py",
        }

    def test_discover_wired_hooks_sorted(self, initialized_repo_root):
        hooks = sc.discover_wired_hooks(initialized_repo_root)
        assert hooks == sorted(hooks)

    def test_discover_wired_hooks_forward_slash(self, initialized_repo_root):
        for h in sc.discover_wired_hooks(initialized_repo_root):
            assert "\\" not in h

    def test_discover_installed_agents_matches_expected_count(self):
        from tests._surface_expected import EXPECTED_UNIVERSAL_AGENTS
        agents = sc.discover_installed_agents(REPO_ROOT)
        # TP-40: agent count was hardcoded to 6; now drawn from SoT.
        assert len(agents) == len(EXPECTED_UNIVERSAL_AGENTS)
        for a in agents:
            assert a.startswith(".claude/agents/")

    def test_discover_installed_commands_matches_expected_count(self):
        from tests._surface_expected import EXPECTED_COMMAND_COUNT
        commands = sc.discover_installed_commands(REPO_ROOT)
        assert len(commands) == EXPECTED_COMMAND_COUNT
        for c in commands:
            assert c.startswith(".claude/commands/")

    def test_discover_installed_skills_finds_nested_skill_md(self, tmp_path):
        skill_dir = tmp_path / ".claude" / "skills" / "reflect"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: reflect\n---\n", encoding="utf-8")
        found = sc.discover_installed_skills(tmp_path)
        assert ".claude/skills/reflect/SKILL.md" in found

    def test_discover_self_host_surface_shape(self, initialized_repo_root):
        surface = sc.discover_self_host_surface(initialized_repo_root)
        for key in ("agents", "commands", "skills", "hooks", "managed_reports", "required_init_files"):
            assert key in surface
            assert isinstance(surface[key], list)
            assert surface[key] == sorted(surface[key])
            for p in surface[key]:
                assert "\\" not in p

    def test_discover_self_host_surface_populated(self, initialized_repo_root):
        from tests._surface_expected import (
            EXPECTED_AGENT_COUNT_MIN,
            EXPECTED_COMMAND_COUNT,
            EXPECTED_HOOK_COUNT,
            EXPECTED_SKILL_COUNT,
        )
        surface = sc.discover_self_host_surface(initialized_repo_root)
        assert len(surface["agents"]) >= EXPECTED_AGENT_COUNT_MIN
        assert len(surface["commands"]) == EXPECTED_COMMAND_COUNT
        assert len(surface["skills"]) == EXPECTED_SKILL_COUNT
        assert len(surface["hooks"]) == EXPECTED_HOOK_COUNT
        assert len(surface["required_init_files"]) >= 3


class TestResilience:
    def test_discover_wired_hooks_on_empty_dir(self, tmp_path):
        assert sc.discover_wired_hooks(tmp_path) == []

    def test_discover_installed_agents_on_empty_dir(self, tmp_path):
        assert sc.discover_installed_agents(tmp_path) == []

    def test_discover_installed_commands_on_empty_dir(self, tmp_path):
        assert sc.discover_installed_commands(tmp_path) == []

    def test_discover_installed_skills_on_empty_dir(self, tmp_path):
        assert sc.discover_installed_skills(tmp_path) == []

    def test_discover_managed_reports_on_empty_dir(self, tmp_path):
        assert sc.discover_managed_reports(tmp_path) == []

    def test_discover_self_host_surface_on_empty_dir(self, tmp_path):
        surface = sc.discover_self_host_surface(tmp_path)
        assert surface["agents"] == []
        assert surface["commands"] == []
        assert surface["skills"] == []
        assert surface["hooks"] == []
        assert surface["managed_reports"] == []

    def test_is_self_host_on_empty_dir(self, tmp_path):
        assert sc.is_self_host_repo(tmp_path) is False

    def test_is_self_host_on_real_repo(self):
        assert sc.is_self_host_repo(REPO_ROOT) is True

    def test_is_self_host_requires_pyproject(self, tmp_path):
        (tmp_path / "espalier").mkdir()
        (tmp_path / "tools" / "cc").mkdir(parents=True)
        # no pyproject.toml
        assert sc.is_self_host_repo(tmp_path) is False

    def test_is_self_host_wrong_project_name(self, tmp_path):
        (tmp_path / "espalier").mkdir()
        (tmp_path / "tools" / "cc").mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "something-else"\n', encoding="utf-8"
        )
        assert sc.is_self_host_repo(tmp_path) is False

    def test_malformed_settings_json_returns_empty(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text("{not valid json", encoding="utf-8")
        assert sc.discover_wired_hooks(tmp_path) == []

    def test_settings_json_with_no_hooks_key(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        assert sc.discover_wired_hooks(tmp_path) == []


def _make_self_host_tree(root: Path, *, prune_sentinels: bool) -> Path:
    """Synthesize a tree that ``is_self_host_repo`` accepts (True).

    Copies the real ``write_guard.py`` so the signal-5 SHA pin matches, and the
    real ``.gitattributes`` so ``export_ignore_patterns`` yields the live
    sentinel set. ``prune_sentinels=True`` models a shipping *export* (the
    tracked export-ignored dev docs are absent); ``False`` models the full dev
    tree / a fresh clone (they are present). Both pass ``is_self_host_repo`` --
    that is the whole point: only ``is_release_export`` can tell them apart.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "espalier").mkdir()
    hooks = root / "tools" / "cc" / "hooks"
    hooks.mkdir(parents=True)
    (root / "bench").mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "espalier-harness"\n', encoding="utf-8"
    )
    shutil.copyfile(
        REPO_ROOT / "tools" / "cc" / "hooks" / "write_guard.py",
        hooks / "write_guard.py",
    )
    shutil.copyfile(REPO_ROOT / ".gitattributes", root / ".gitattributes")
    if not prune_sentinels:
        (root / "ESPALIER_MEMORY.md").write_text("# dev tree\n", encoding="utf-8")
        (root / "docs").mkdir(exist_ok=True)
        for name in (
            "REDEFINED_INFORMATION_REGISTRY.md",
            "RELEASE_FINDINGS_LEDGER.md",
        ):
            (root / "docs" / name).write_text("internal\n", encoding="utf-8")
    return root


class TestIsReleaseExport:
    """espalier.surface_contract.is_release_export -- distinguishes a pruned
    source export from the full dev tree. Both trees pass is_self_host_repo
    (they share the code LAYOUT); only the export prunes the tracked
    export-ignored dev CONTENT. All fixtures are tmp_path-synthesized, so these
    tests are portable -- they do not assert anything about the tree they run in
    (which may itself be an export under the release matrix)."""

    def test_true_on_synthesized_export(self, tmp_path):
        export = _make_self_host_tree(tmp_path / "export", prune_sentinels=True)
        # Earn-the-red: is_self_host_repo alone CANNOT discriminate -- it returns
        # True for the pruned export (the S2 trap). is_release_export is the fix.
        assert sc.is_self_host_repo(export) is True
        assert sc.is_release_export(export) is True

    def test_false_on_synthesized_dev_tree(self, tmp_path):
        dev = _make_self_host_tree(tmp_path / "dev", prune_sentinels=False)
        assert sc.is_self_host_repo(dev) is True
        assert sc.is_release_export(dev) is False

    def test_is_self_host_repo_cannot_discriminate(self, tmp_path):
        # The concrete earn-the-red for the class: a naive is_self_host_repo-only
        # check gives the SAME answer (True) for dev tree and export, so it is
        # the wrong tool for "is the full dev tree present"; is_release_export
        # gives DIFFERENT (correct) answers for the two.
        dev = _make_self_host_tree(tmp_path / "dev", prune_sentinels=False)
        export = _make_self_host_tree(tmp_path / "export", prune_sentinels=True)
        assert sc.is_self_host_repo(dev) is True
        assert sc.is_self_host_repo(export) is True
        assert sc.is_release_export(dev) != sc.is_release_export(export)

    def test_false_on_adopter_layout(self, tmp_path):
        # No espalier/+bench self-host layout -> is_self_host_repo False -> never
        # an export (the helper only fires on the harness's own layout).
        (tmp_path / "src").mkdir()
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "some-adopter"\n', encoding="utf-8"
        )
        assert sc.is_self_host_repo(tmp_path) is False
        assert sc.is_release_export(tmp_path) is False

    def test_false_without_gitattributes(self, tmp_path):
        # Self-host layout but no .gitattributes -> no sentinels -> conservative
        # False (cannot positively confirm an export; keep running dev checks).
        tree = _make_self_host_tree(tmp_path / "no_ga", prune_sentinels=True)
        (tree / ".gitattributes").unlink()
        assert sc.is_self_host_repo(tree) is True
        assert sc.is_release_export(tree) is False


class TestClassifiersInternalLeak:
    @pytest.mark.parametrize("path,expected", [
        ("docs/internal/foo.md", True),
        ("docs/internal/nested/deep.md", True),
        ("docs/internal", True),
        ("docs/session-archive.md", True),
        ("TASK_PACK_FOO.md", True),
        ("TASK_PACK_13_CLAUDE_MD.md", True),
        ("BLUEPRINT_FOO.md", True),
        ("BLUEPRINT_ESPALIER_MEMORY.md", True),
        # TP-171 §3.1a / §3.1b — internal harness-dev material that previously
        # classified as `public` and shipped to git-archive. (ESPALIER_MEMORY.md is
        # deliberately NOT reclassified — see the note in surface_contract.py /
        # deferred to TP-172; its git-archive leak is closed via export-ignore.)
        ("blueprint.md", True),
        ("memory/injection-opportunity-atlas.md", True),
        ("memory/generative-injection-atlas.md", True),
        ("memory/speedbump-checkpoint-atlas.md", True),
        ("README.md", False),
        ("docs/public/whatever.md", False),
        ("espalier/cli.py", False),
        # ESPALIER_MEMORY.md stays `public` (a shipped managed surface per the inventory);
        # only its archive exposure is closed via .gitattributes export-ignore.
        ("ESPALIER_MEMORY.md", False),
        # The shipping boundary (2026-09-21): a pack directly under task-packs/
        # or task-packs/Deferred/ ships; one anywhere else is internal.
        ("task-packs/TP-452-the-ledger-ships.md", False),
        ("task-packs/Deferred/TP-203a-learning-loop.md", False),
        ("task-packs/Done/TP-1-x.md", True),
        ("task-packs/Merged/TP-2-x.md", True),
        ("task-packs/Scrapped/TP-3-x.md", True),
        ("task-packs/Deferred/old/TP-4-x.md", True),
        ("TP-9-stray.md", True),
        ("docs/TP-9-stray.md", True),
        # A shipped pack ships whatever its basename says: the atlas vocabulary
        # does not reclassify it (the code-review lane drove the fail-closed
        # case and its misleading remedy).
        ("task-packs/TP-999-injection-atlas.md", False),
        # The publish memo: export-ignored, and internal since 2026-09-21 so the
        # MANIFEST.in exclude has its classify-side twin.
        ("memory/publish-from-a-generated-public-repo.md", True),
    ])
    def test_is_internal_release_leak(self, path, expected):
        assert sc.is_internal_release_leak(path) is expected


class TestShippedPackBoundary:
    """The 2026-09-21 boundary: the forward ledger, its probes file, the router
    and the active packs ship; the landed / merged / scrapped subtrees and the
    dated archive families stay out. Both directions, through
    classify_release_path -- the bucket the archive builders read."""

    @pytest.mark.parametrize("path", [
        "task-packs/FORWARD_LEDGER.md",
        "task-packs/LEDGER_PROBES.json",
        "task-packs/CLAUDE.md",
        "task-packs/TP-452-the-ledger-ships.md",
        "task-packs/Deferred/TP-203a-learning-loop.md",
    ])
    def test_ship_set_is_public(self, path):
        assert sc.classify_release_path(path) == "public"

    @pytest.mark.parametrize("path,bucket", [
        ("task-packs/Done/TP-1-x.md", "internal"),
        ("task-packs/Merged/TP-2-x.md", "internal"),
        ("task-packs/Scrapped/TP-3-x.md", "internal"),
        ("task-packs/Merged/README.md", "local_only"),
        ("task-packs/Done", "local_only"),
        ("task-packs/FORWARD_LEDGER_PRE_REBUILD_2026-09-20.md", "local_only"),
        ("task-packs/ARCHIVE_review_findings_2026-08-05.md", "local_only"),
        ("task-packs/CONSOLIDATED_REGISTER_2026-08-05.md", "local_only"),
        ("task-packs/RUNBOOK_precut_2026-09-20.md", "local_only"),
        ("task-packs/Done/LAYER1-SPEC.md", "local_only"),
        ("task-packs/TP-176-oss-convergence-findings.json", "local_only"),
        # The allow-list is exact: a file nobody named, a non-pack under
        # Deferred/, a pack one level too deep -- all stay local-only.
        ("task-packs/notes.txt", "local_only"),
        ("task-packs/Deferred/notes.md", "local_only"),
        ("task-packs/Deferred/old/TP-4-x.md", "internal"),
    ])
    def test_internal_set_never_reaches_public(self, path, bucket):
        assert sc.classify_release_path(path) == bucket

    def test_the_folder_is_not_a_prune_dir_but_every_other_local_prefix_is(self):
        # The walkers must descend into task-packs/ to find the ship set; the
        # other local-only prefixes still prune wholesale.
        pruned = sc.get_release_excluded_prefixes()
        assert "task-packs/" not in pruned
        for other in sc._LOCAL_ONLY_PREFIXES:
            if other != "task-packs/":
                assert other in pruned, other

    @pytest.mark.parametrize("path,expected", [
        ("task-packs/CLAUDE.md", True),
        ("task-packs/FORWARD_LEDGER.md", True),
        ("task-packs/LEDGER_PROBES.json", True),
        ("task-packs/TP-452-the-ledger-ships.md", True),
        ("task-packs/Deferred/TP-1-x.md", True),
        ("task-packs/notes.txt", False),
        ("task-packs/Done/TP-1-x.md", False),
        ("espalier/assets/task-packs/CLAUDE.md", False),
    ])
    def test_is_shipped_task_pack_surface(self, path, expected):
        assert sc.is_shipped_task_pack_surface(path) is expected

    def test_the_gitignore_allow_list_mirrors_the_classifier_carve_out(self):
        """The two allow-lists are INDEPENDENTLY WRITTEN (a hand-kept .gitignore,
        a hand-kept tuple) and must agree, or a file one side ships the other
        side never tracks -- the parallel-inventories drift docs/SHARP_EDGES.md
        records for the noise patterns, one directory over. Read from the live
        .gitignore; the dogfooding mirror is not this repo's ignore file."""
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        negations = {ln[1:] for ln in gitignore if ln.startswith("!task-packs/")}
        plain = {n for n in negations if not n.endswith("/") and "*" not in n}
        globs = negations - plain
        assert plain == set(sc.SHIPPED_TASK_PACK_FILES), (
            f".gitignore re-includes {sorted(plain)} by name; the classifier carves out "
            f"{sorted(sc.SHIPPED_TASK_PACK_FILES)} -- move both together"
        )
        # One TP-*.md re-include per shipped pack directory, plus the directory
        # re-include Deferred/ needs so its packs can be re-included at all.
        expected_globs = {f"{d}/TP-*.md" for d in sc.SHIPPED_PACK_DIRS} | {"task-packs/Deferred/"}
        assert globs == expected_globs, (
            f".gitignore pack re-includes {sorted(globs)} vs the shipped pack dirs "
            f"{sc.SHIPPED_PACK_DIRS} -> {sorted(expected_globs)}"
        )

    # Shipped-classified packs withheld from the seed ON PURPOSE, each with the
    # reason and the date. A dict, not a set: an unexplained exclusion inside a
    # mechanical gate is itself an untested assertion (the archive-parity file's
    # rule, one directory over). A registered path MUST be matched by a row --
    # a mistyped row would otherwise ship the pack with the whole suite green.
    WITHHELD_SHIPPED_PACKS: dict[str, str] = {
        "task-packs/TP-456-m4-the-console-then-the-cut.md": (
            "2026-09-24, Round 12: the M4 release-console pack carries the operator's "
            "console notes, not product; export-ignored until 4-G moves it to Done/, "
            "then drop the row and this entry together. On an export the dangling-id "
            "baseline (tests/test_forward_ledger_completeness.py) derives the id from "
            "this row; when the public repository drops the row, add the id there by hand."
        ),
    }

    def test_no_export_ignore_row_reaches_the_ship_set(self):
        """The .gitattributes wall is a deny-list (git cannot re-include a pruned
        directory), so its rows must never match a member of the ship set; a
        row that did would drop a public file from every archive with the
        classifier still saying `public`.

        Population: the LIVE tracked pack set filtered through the classifier's
        own carve-out, plus the two fixture names. Until 2026-09-24 the loop ran
        over the hand-written names alone, so a row pruning a real shipped pack
        (the TP-456 withholding) satisfied it unseen (Round 12)."""
        from _git_oracle import require_tracked_paths

        rows = sc.export_ignore_patterns(REPO_ROOT)
        assert any(p.startswith("/task-packs/") for p in rows), "the task-pack export-ignore rows are gone"
        live = [
            rel for rel in require_tracked_paths(REPO_ROOT, "task-packs/", what="task-pack paths")
            if sc.is_shipped_task_pack_surface(rel)
        ]
        assert live, "test setup: no tracked shipped pack surface"
        population = [*sc.SHIPPED_TASK_PACK_FILES,
                      "task-packs/TP-452-the-ledger-ships.md",
                      "task-packs/Deferred/TP-203a-learning-loop.md",
                      *live]
        for rel in population:
            hits = [p for p in rows if sc.matches_export_ignore(rel, p)]
            if rel in self.WITHHELD_SHIPPED_PACKS:
                assert hits, (
                    f"{rel} is registered as withheld from the seed yet no export-ignore "
                    f"row matches it -- the row is mistyped or gone, and the pack ships"
                )
                continue
            assert not hits, f"{rel} is export-ignored by {hits} yet ships"
        # The stale-entry arm holds on a development tree only: an export (and the
        # public repository seeded from one) never carries a withheld pack, so
        # there the entry and its row are dead on arrival and the first post-seed
        # commit drops both.
        if sc.is_release_export(REPO_ROOT):
            return
        for rel in self.WITHHELD_SHIPPED_PACKS:
            assert rel in population, (
                f"{rel} is registered as withheld but is not a tracked shipped pack -- "
                f"drop the entry and its .gitattributes row together"
            )

    @pytest.mark.parametrize("path,expected", [
        ("task-packs/TP-452-the-ledger-ships.md", True),
        ("task-packs/Deferred/TP-1-x.md", True),
        ("task-packs/Done/TP-1-x.md", False),
        ("task-packs/Deferred/old/TP-1-x.md", False),
        ("task-packs/FORWARD_LEDGER.md", False),
        ("task-packs/CLAUDE.md", False),
        ("TP-9-stray.md", False),
        ("src/vendor/task-packs/TP-1-x.md", False),
        # Case-sensitive on every platform: git on a case-insensitive checkout
        # re-includes this name, the classifier does not, and the derived gates
        # below are what report the disagreement.
        ("task-packs/tp-953-lowercase.md", False),
    ])
    def test_is_shipped_pack(self, path, expected):
        assert sc.is_shipped_pack(path) is expected

    def test_every_tracked_task_pack_path_is_in_the_ship_set(self):
        """The catch-all the .gitattributes rows cannot be: git offers no
        re-include inside a pruned directory, so once part of the folder ships
        its export-ignore wall is a named deny-list and a force-added stray
        (a spec, a note, a nested findings file, a backup) reaches the archive
        with every spelling-based test green -- both review lanes drove it.
        Derived from the index, so it holds for any spelling of the walls."""
        from tests._git_oracle import require_tracked_paths
        out = require_tracked_paths(REPO_ROOT, "task-packs/", minimum=3,
                                    what="tracked paths under task-packs/")
        stray = sorted(p for p in out if not sc.is_shipped_task_pack_surface(p))
        assert not stray, (
            f"tracked under task-packs/ but not in the ship set: {stray} -- untrack it "
            "(git rm --cached), or name it in SHIPPED_TASK_PACK_FILES / SHIPPED_PACK_DIRS"
        )

    def test_git_and_the_classifier_agree_on_the_task_pack_boundary(self):
        """The behavioural twin of the string-compare parity test above: ask git
        (`check-ignore --no-index`, so the RULES answer, not the index) whether it
        would track each probe path, and the classifier whether it ships. A
        re-include spelled with a leading slash, a case-folded match, or the loss
        of the `task-packs/*` line that makes the shape fail-closed all show up
        here and in none of the string tests (the failure-mode lane drove each).
        The oracle's `require_is_gitignored` answers about the index first, so a
        tracked ship-set member reads "not ignored" whatever the rules say; this
        asks the RULES (`--no-index`), which is the question the parity is about.
        A raw git call, counted by the suite contract's raw-git ratchet with this
        reason."""
        import subprocess
        from tests._git_oracle import owns_its_worktree
        if not owns_its_worktree(REPO_ROOT):
            pytest.skip("check-ignore answers 'ignored' for every path under an ignored ancestor")
        probes = [
            *sc.SHIPPED_TASK_PACK_FILES,
            *(f"{d}/TP-999-probe.md" for d in sc.SHIPPED_PACK_DIRS),
            "task-packs/notes.txt", "task-packs/Done/LAYER1-SPEC.md",
            "task-packs/TP-999-probe-findings.json",
            "task-packs/Done/TP-999-probe.md", "task-packs/Merged/TP-999-probe.md",
            "task-packs/Scrapped/TP-999-probe.md", "task-packs/Deferred/old/TP-999-probe.md",
            "task-packs/Deferred/notes.md",
            "task-packs/FORWARD_LEDGER_PRE_REBUILD_2026-09-20.md",
        ]
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "check-ignore", "--no-index", "-n", "-v", "--stdin"],
            # bytes, not a text pipe: `text=True` writes `\n` as os.linesep, so on
            # Windows every probe reached git with a `\r` and came back quoted
            # (Portability, 2026-09-23)
            input=("\n".join(probes) + "\n").encode("utf-8"), capture_output=True,
        )
        # `source:line:pattern<TAB>path`; `::<TAB>path` when no rule matched; a
        # matching rule that starts with `!` is a re-include, so NOT ignored.
        ignored: dict[str, bool] = {}
        for ln in out.stdout.decode("utf-8").splitlines():
            src, _, path = ln.rpartition("\t")
            pattern = src.split(":", 2)[2] if src and not src.startswith("::") else ""
            ignored[path] = bool(pattern) and not pattern.startswith("!")
        assert set(ignored) == set(probes), f"git answered for {sorted(ignored)}, asked {probes}"
        disagreements = [
            f"{rel}: git ignores={ignored[rel]}, classifier public={sc.classify_release_path(rel) == 'public'}"
            for rel in probes
            if (sc.classify_release_path(rel) == "public") != (not ignored[rel])
        ]
        assert not disagreements, "the two allow-lists disagree:\n  " + "\n  ".join(disagreements)


class TestClassifiersTransient:
    @pytest.mark.parametrize("path,expected", [
        ("__pycache__/foo.pyc", True),
        ("src/foo.py", False),
        (".DS_Store", True),
        ("dist/lib.whl", True),
        ("build/output.txt", True),
        ("foo.egg-info/PKG-INFO", True),
        (".pytest_cache/v/cache/lastfailed", True),
        (".git/HEAD", True),
        # §C13 (DEF-417f): the bare gitlink FILE of a worktree / submodule
        # checkout is transient; tracked names sharing the prefix are not.
        (".git", True),
        ("vendor/lib/.git", True),
        (".gitignore", False),
        (".gitattributes", False),
        (".gitmodules", False),
        (".github/workflows/ci.yml", False),
        ("espalier/cli.py", False),
        ("tests/test_foo.py", False),
        # TP-247a #4 — OS/editor/tool droppings the first witness must also prune
        # so the builder excludes them (not just the second-witness post-scan).
        ("._resourcefork", True),
        ("docs/._notes.md", True),
        ("main.c.swp", True),
        ("cli.py.orig", True),
        ("patch.rej", True),
        ("settings.bak", True),
        ("README.md~", True),
        (".tox/py312/bin/python", True),
        (".nox/tests/foo", True),
        # TP-247a #5 — secret/credential files the builder must exclude.
        (".env", True),
        (".env.local", True),
        (".pypirc", True),
        (".netrc", True),
        ("id_rsa", True),
        (".aws/credentials", True),
        ("secrets/credentials.json", True),
        # Over-match guards — near-miss shapes stay shippable.
        (".environment", False),
        ("credential_helper.py", False),
        ("id_rsa.pub", False),
    ])
    def test_is_transient(self, path, expected):
        assert sc.is_transient(path) is expected


class TestClassifiersLocalOnly:
    def test_is_local_only_positive(self):
        assert sc.is_local_only(".claude/settings.local.json") is True
        assert sc.is_local_only("reports/analysis.json") is True
        assert sc.is_local_only("reports/cc_surface_gate.json") is True
        assert sc.is_local_only("cc/GOAL.md") is True

    def test_compact_summaries_routes_local_only(self):
        # TP-215: post_compact captures the verbatim native compaction summary
        # to cc/blueprints/compact_summaries/<session>.md. It inherits the
        # existing cc/blueprints/ local-only prefix, so it never ships in the
        # wheel/release archive. Contract test (green by inheritance) pinning
        # that the captured-summary artifact stays local-only.
        rel = "cc/blueprints/compact_summaries/abc123.md"
        assert sc.is_local_only(rel) is True
        assert sc.classify_release_path(rel) == "local_only"

    def test_lock_sentinel_inherits_its_base_paths_classification(self):
        """A `<x>.lock` is local-only exactly when `<x>` is.

        `_LOCAL_ONLY_PATHS` is deliberately exact-match, and the lock sentinels
        were enumerated one at a time — so the *fourth* one was simply missed:
        `cc/execution_plan.json` was local-only while `cc/execution_plan.json.lock`
        classified `public` and SHIPPED in the release archive (measured: one of
        exactly two untracked files in a 917-file payload).

        Deriving the lock's class from its base closes the enumeration gap
        without a blanket `*.lock` rule, which would be wrong for adopters:
        `poetry.lock`, `Cargo.lock` and `package-lock.json` are shipped
        artifacts, and their bases are not local-only, so they stay public.
        """
        assert sc.is_local_only("cc/execution_plan.json") is True
        assert sc.is_local_only("cc/execution_plan.json.lock") is True
        assert sc.classify_release_path("cc/execution_plan.json.lock") == "local_only"

        # The blanket rule this deliberately is NOT: a lock whose base carries
        # no local-only classification must remain shippable.
        assert sc.is_local_only("poetry.lock") is False
        assert sc.is_local_only("Cargo.lock") is False
        assert sc.is_public_release_allowed("poetry.lock") is True

        # Pre-existing exact entries keep working (their bases are not listed,
        # so they are covered by enumeration, not by inheritance).
        assert sc.is_local_only(".espalier/.manifest.write.lock") is True
        assert sc.is_local_only(".claude/scheduled_tasks.lock") is True

    def test_is_local_only_negative(self):
        # TP-07: .claude/settings.json and reports/* (including
        # harness_config.json) are now classified as local_only — they're
        # per-install runtime artifacts, not part of the public release
        # archive. This test pins what is NOT local-only.
        assert sc.is_local_only("README.md") is False
        assert sc.is_local_only("espalier/cli.py") is False
        assert sc.is_local_only("cc/COMMANDS.md") is False
        assert sc.is_local_only("docs/CONVENTIONS.md") is False


class TestProtectedInventories:
    def test_mutation_files_covers_settings_and_hooks(self):
        files = set(sc.get_protected_mutation_paths())
        assert ".claude/settings.json" in files
        assert ".claude/settings.local.json" in files
        assert "tools/cc/hooks/write_guard.py" in files
        assert ".github/workflows/harness-guard.yml" in files
        assert "tools/cc/ci_guard.py" in files
        assert ".espalier/integrity.json" in files

    def test_mutation_prefixes_covers_harness_zones(self):
        prefixes = set(sc.get_protected_mutation_prefixes())
        assert "tools/cc/" in prefixes
        assert "espalier/" in prefixes
        assert "cc/" in prefixes

    def test_integrity_files_excludes_per_machine_settings(self):
        files = set(sc.get_protected_integrity_paths())
        assert ".claude/settings.json" not in files
        assert ".claude/settings.local.json" not in files
        assert "tools/cc/hooks/write_guard.py" in files
        assert "tools/cc/ci_guard.py" in files
        assert ".github/workflows/harness-guard.yml" in files

    def test_ci_files_covers_settings_and_workflow(self):
        files = set(sc.get_protected_ci_files())
        assert ".claude/settings.json" in files
        assert ".github/workflows/harness-guard.yml" in files
        assert "tools/cc/ci_guard.py" in files

    def test_ci_prefixes_covers_hooks_dir(self):
        prefixes = set(sc.get_protected_ci_prefixes())
        assert "tools/cc/hooks/" in prefixes

    @pytest.mark.parametrize("path,expected", [
        ("tools/cc/hooks/write_guard.py", True),
        ("tools/cc/hooks/session_start.py", True),
        ("tools/cc/ci_guard.py", True),
        (".github/workflows/harness-guard.yml", True),
        (".claude/settings.json", True),
        (".espalier/integrity.json", True),
        ("tools/cc/hooks/write_guard.py".replace("/", "\\"), True),
        # TP-05 §3: every workflow under .github/workflows/ is CI-protected
        # because workflow mutation can change release/test/benchmark
        # enforcement. Any workflow change requires HARNESS-UPDATE-APPROVED.
        (".github/workflows/test.yml", True),
        (".github/workflows/release.yml", True),
        (".github/workflows/benchmark.yml", True),
        ("README.md", False),
        ("espalier/cli.py", False),
        ("tools/cc/cognitive_blueprint.py", False),
    ])
    def test_is_protected_from_ci(self, path, expected):
        assert sc.is_protected_from_ci(path) is expected


class TestClassifiersPublicReleaseAllowed:
    @pytest.mark.parametrize("path,expected", [
        ("README.md", True),
        ("espalier/cli.py", True),
        ("tests/test_foo.py", True),
        ("docs/internal/secret.md", False),
        (".claude/settings.local.json", False),
        ("__pycache__/foo.pyc", False),
        ("TASK_PACK_1.md", False),
        ("BLUEPRINT_X.md", False),
        (".DS_Store", False),
    ])
    def test_is_public_release_allowed(self, path, expected):
        assert sc.is_public_release_allowed(path) is expected


class TestN7ExecutabilityHelpers:
    """TP-169 §13 #8 re-attack: direct unit pins for the executability/matcher
    primitives the governance oracle relies on (the path-only extractors are too
    weak — a neutered gate must read as UNWIRED)."""

    @pytest.mark.parametrize("matcher,covered", [
        ("*", True), ("", True), (".*", True),
        ("Write|Edit|NotebookEdit", True),
        ("Write|Edit|NotebookEdit|Bash|PowerShell|mcp__.*", True),
        ("(Write|Edit|NotebookEdit)", True),
        ("Bash", False), ("Read|Task", False),
        ("Write|Edit|Notebook", False),   # substring-only — fail-CLOSED via fullmatch
        ("[", False),                     # unparseable — fail-CLOSED
    ])
    def test_matcher_covers_mutations(self, matcher, covered):
        assert sc.matcher_covers_mutations(matcher) is covered

    _PWC = "Write|Edit|NotebookEdit|Bash|PowerShell|mcp__.*"

    @pytest.mark.parametrize("deployed, canonical, covered", [
        (_PWC, _PWC, True),                                   # exact
        ("*", _PWC, True),                                    # fire-all covers all
        ("Write|Edit|NotebookEdit", _PWC, False),             # narrowed: Bash/PowerShell/mcp gone
        ("Write|Edit|NotebookEdit|Bash|PowerShell", _PWC, False),  # mcp__.* gone
        ("Read|" + _PWC, _PWC, True),                         # wider is fine
        ("Write|Edit|NotebookEdit", "Write|Edit|NotebookEdit", True),  # plan_guard exact
        ("Write|Edit", "Write|Edit|NotebookEdit", False),     # gate narrowed
        ("(", _PWC, False),                                   # unparseable fails closed
    ])
    def test_matcher_covers_canonical_checks_every_canonical_token(
        self, deployed, canonical, covered
    ):
        """DEF-619 (found by review): the old test stopped at the three
        mutation tools, so post_write_check's matcher narrowed to that trio
        read as fully wired. Every token of the canonical alternation must be
        matched, a pattern token via a name it would match."""
        assert sc.matcher_covers_canonical(deployed, canonical) is covered

    def test_matcher_token_probe(self):
        assert sc.matcher_token_probe("Bash") == "Bash"
        assert sc.matcher_token_probe("mcp__.*") == "mcp__probe"

    @pytest.mark.parametrize("hook,expected", [
        # canonical exec form (the ONLY recognized shape) — positives:
        ({"type": "command", "command": "python3",
          "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"]},
         "tools/cc/hooks/write_guard.py"),
        # ⚠ These four carry an explicit `"type": "command"` that they did NOT
        # need before. Their subject is PATH NORMALIZATION, and they used to
        # omit `type` on the strength of a comment reading "absent type →
        # command". That premise was measured FALSE against real Claude Code
        # 2.1.247 (an untyped entry does not run, and voids the whole file), so
        # the rows keep their subject and the premise moved to
        # TestHookTypeIsRequiredAndVoidsTheWholeFile as its own row. This is a
        # TIGHTENING — a shape that used to read wired now reads dead.
        ({"type": "command", "command": "python3", "args": ["x.py"]}, "x.py"),
        ({"type": "command", "command": "/usr/bin/python3",
          "args": ["x.py"]}, "x.py"),  # full-path interpreter
        # leading ./ and ${CLAUDE_PROJECT_DIR}/./ normalize to canonical (parity):
        ({"type": "command", "command": "python3",
          "args": ["./tools/cc/hooks/x.py"]}, "tools/cc/hooks/x.py"),
        ({"type": "command", "command": "python3",
          "args": ["${CLAUDE_PROJECT_DIR}/./tools/cc/hooks/x.py"]}, "tools/cc/hooks/x.py"),
        # the premise those rows used to rest on, now pinned as the negative:
        ({"command": "python3", "args": ["x.py"]}, None),  # absent type → DEAD
        # ── fail-CLOSED: anything that is NOT canonical exec form ──
        # ⚠ These rows carry an explicit `"type": "command"` so they still
        # earn their red. Tightening the type gate made it the FIRST check,
        # so an untyped row returns None before the interpreter/args/`.py`
        # logic runs at all -- a mutation test proved 12 of 14 rows passed
        # against a predicate gutted of everything BUT the type gate. A guard
        # that stops its siblings earning red has made them decorative.
        # The single untyped negative lives at the row above, on purpose.
        # round-1 baits (non-interpreter / wrong type):
        ({"type": "command", "command": "true",
          "args": ["# ${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"]}, None),
        ({"type": "prompt", "command": "python3", "args": ["tools/cc/hooks/x.py"]}, None),
        # round-2 -c/-m flag: the .py is inert sys.argv, never the program:
        ({"type": "command", "command": "python3",
          "args": ["-c", "pass", "tools/cc/hooks/x.py"]}, None),
        ({"type": "command", "command": "python3",
          "args": ["-m", "mod", "tools/cc/hooks/x.py"]}, None),
        ({"type": "command", "command": "python3",
          "args": ["-c", "tools/cc/hooks/x.py"]}, None),
        # round-2 shell-form (command string with spaces) — ALL rejected structurally:
        ({"type": "command", "command": "python3 ${CLAUDE_PROJECT_DIR}/tools/cc/hooks/x.py"}, None),
        ({"type": "command", "command": "false && python3 tools/cc/hooks/x.py"}, None),
        ({"type": "command",
          "command": "python3 -c 'pass' && echo tools/cc/hooks/x.py"}, None),
        ({"type": "command", "command": "python3 -m pytest tools/cc/hooks/x.py"}, None),
        ({"type": "command", "command": ": tools/cc/hooks/x.py"}, None),
        ({"type": "command", "command": "echo tools/cc/hooks/x.py"}, None),
        # env-wrapper — non-canonical, fail-CLOSED:
        ({"type": "command", "command": "env",
          "args": ["python3", "tools/cc/hooks/x.py"]}, None),
        # no args (shell form) / empty args:
        ({"type": "command", "command": "python3"}, None),
        ({"type": "command", "command": "python3", "args": []}, None),
    ])
    def test_hook_executes_script_path(self, hook, expected):
        assert sc._hook_executes_script_path(hook) == expected

    @pytest.mark.parametrize("hook", [
        {"command": "python3", "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"]},
        {"command": "python3", "args": ["${CLAUDE_PROJECT_DIR}/./tools/cc/hooks/write_guard.py"]},
        {"command": "python3", "args": ["./tools/cc/hooks/write_guard.py"]},
        {"command": "python3", "args": ["-c", "pass", "tools/cc/hooks/write_guard.py"]},
        {"command": "python3 -m pytest tools/cc/hooks/write_guard.py"},
        {"command": "true", "args": ["tools/cc/hooks/write_guard.py"]},
        {"type": "prompt", "command": "python3", "args": ["tools/cc/hooks/write_guard.py"]},
    ])
    def test_doctor_ci_extractor_parity(self, hook):
        """The zero-imports ci_guard mirror must agree with surface_contract on
        every shape — no parity drift (TP-169 §13 #8 round-2 ./-strip drift)."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_ci_guard_parity", Path(__file__).resolve().parent.parent / "tools/cc/ci_guard.py")
        cig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cig)
        assert sc._hook_executes_script_path(hook) == cig._ci_hook_executes_script_path(hook)


class TestHookTypeIsRequiredAndVoidsTheWholeFile:
    """``type`` absent is NOT ``"command"``, and one bad ``type`` kills the FILE.

    This repo modelled ``type`` absent as CC's default ``"command"`` at two
    sites (``surface_contract._hook_executes_script_path`` and its zero-imports
    mirror ``tools/cc/ci_guard._ci_hook_executes_script_path``). That model was
    never pinned against the platform -- ``docs/external/cc-hook-protocol.md``
    says nothing about ``type`` -- and it is WRONG, which made it a fail-OPEN:
    the governance oracle read a fully-disarmed file as fully wired.

    DRIVEN against real Claude Code 2.1.247, every negative bracketed by a
    control that fired, marker-file rig, stderr empty on every voided run:

      | settings.json                                   | typed hook fires |
      | one entry, type="command"                       | YES              |
      | one entry, type absent                          | no               |
      | one entry, type="prompt"                        | no               |
      | two entries, BOTH typed            (control)    | YES, both        |
      | typed + untyped, same event                     | NEITHER          |
      | typed SessionStart + untyped PostToolUse        | NEITHER          |
      | typed + type="prompt", same event               | NEITHER          |

    So the rule is not per-entry and not per-event: ANY hook object whose
    ``type`` is not exactly ``"command"`` makes Claude Code load NO hooks from
    the file at all, silently. One stray entry -- an adopter's OWN unrelated
    hook, not espalier's -- disarms every governance gate while every espalier
    surface reports armed.

    ⚠ Why the sibling rows in :class:`TestN7ExecutabilityHelpers` gained an
    explicit ``"type": "command"``: four of them omitted ``type`` and asserted a
    PATH, with the comment "absent type -> command". Those rows exist to pin
    path NORMALIZATION, not type handling, so they keep their subject and the
    false premise moves here as its own row. That edit TIGHTENS the oracle (a
    shape that used to read wired now reads dead); it is not a loosening.
    """

    def test_absent_type_does_not_execute(self):
        assert sc._hook_executes_script_path(
            {"command": "python3", "args": ["tools/cc/hooks/write_guard.py"]}
        ) is None, (
            "an entry with no `type` was read as executable -- measured on CC "
            "2.1.247 it does not run, and it voids the whole settings file"
        )

    @pytest.mark.parametrize("hooks_cfg,expected_bad", [
        # ── LOADS NORMALLY (driven). A row here that flips to True is a FALSE
        # RED: it tells a healthy adopter every gate is dead and fails their CI.
        ({}, False),
        ({"E": []}, False),
        ({"E": [{"hooks": []}]}, False),
        ({"E": [{"hooks": [{"type": "command", "command": "python3",
                            "args": ["a.py"]}]}]}, False),
        # ⚠ THE ROW THAT WAS MISSING, and whose absence let a false red ship in
        # the first draft: a well-formed prompt hook is a legitimate Claude Code
        # feature. Driven 3x — the typed sibling FIRES. The earlier
        # "type=prompt voids the file" measurement used a malformed entry that
        # carried `command`/`args` instead of `prompt`.
        ({"E": [{"hooks": [{"type": "prompt", "prompt": "say hi"}]}]}, False),
        # extra keys are tolerated by CC (driven with `timeout`)
        ({"E": [{"hooks": [{"type": "command", "command": "python3",
                            "args": ["a.py"], "timeout": 5}]}]}, False),
        ({"E": [{"matcher": "*", "hooks": [{"type": "command",
                                            "command": "python3"}]}]}, False),

        # ── VOIDS THE WHOLE FILE (each driven against real CC 2.1.247 with a
        # control hook that fired in the same file).
        ({"E": [{"hooks": [{"command": "python3", "args": ["a.py"]}]}]}, True),
        ({"E": [{"hooks": [{"type": "wibble", "prompt": "x"}]}]}, True),
        ({"E": [{"hooks": [{"type": "prompt", "command": "python3",
                            "args": ["a.py"]}]}]}, True),
        ({"E": [{"hooks": [{"type": "command"}]}]}, True),
        ({"E": [{"hooks": [{"type": "command", "command": "python3",
                            "args": "a.py"}]}]}, True),
        ({"E": [{"hooks": ["python3 a.py"]}]}, True),
        ({"E": [{"hooks": [None]}]}, True),
        ({"E": ["i-am-a-string"]}, True),
        ({"E": [{"matcher": "*"}]}, True),
        ({"E": [{"hooks": "python3 a.py"}]}, True),
        ({"E": [{"matcher": 123, "hooks": []}]}, True),
        ({"E": "not-a-list"}, True),

        # ── blast radius: a valid sibling does NOT rescue a bad entry, and the
        # offender may sit under a completely different event.
        ({"E": [{"hooks": [{"type": "command", "command": "python3",
                            "args": ["a.py"]}]},
                {"hooks": [{"command": "python3", "args": ["b.py"]}]}]}, True),
        ({"SessionStart": [{"hooks": [{"type": "command", "command": "python3",
                                       "args": ["a.py"]}]}],
          "PostToolUse": [{"hooks": [{"command": "python3",
                                      "args": ["b.py"]}]}]}, True),
    ])
    def test_voiding_detector_matches_the_measured_platform(
        self, hooks_cfg, expected_bad
    ):
        got = sc.hooks_config_voided_by(hooks_cfg)
        assert (got is not None) == expected_bad, (
            f"voiding detector disagrees with the driven CC matrix: {hooks_cfg!r} "
            f"-> {got!r}"
        )

    def test_a_voided_file_yields_no_executable_wirings(self, tmp_path):
        """The whole point: CC loads NOTHING, so the oracle must see nothing.

        Without this the per-entry fix is not enough -- the untyped entry is
        skipped and its correctly-typed SIBLINGS still read as live, which is
        precisely the state CC does not produce.
        """
        import json
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"hooks": {
            "PreToolUse": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "python3",
                                            "args": ["tools/cc/hooks/write_guard.py"]}]},
            ],
            "PostToolUse": [
                {"hooks": [{"command": "python3", "args": ["somebody_elses_hook.py"]}]},
            ],
        }}), encoding="utf-8")

        assert sc.discover_executable_hook_wirings(tmp_path) == [], (
            "a correctly-typed write_guard read as live on a file Claude Code "
            "voids whole -- the fail-open this class exists to close"
        )

    def test_ci_guard_mirror_agrees_on_the_type_rule(self):
        """The mirror is count-parity-locked; a one-sided fix is a silent split."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_ci_guard_type_parity", REPO_ROOT / "tools/cc/ci_guard.py")
        cig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cig)
        for hook in (
            {"command": "python3", "args": ["tools/cc/hooks/x.py"]},
            {"type": "command", "command": "python3", "args": ["tools/cc/hooks/x.py"]},
            {"type": "prompt", "command": "python3", "args": ["tools/cc/hooks/x.py"]},
        ):
            assert (sc._hook_executes_script_path(hook)
                    == cig._ci_hook_executes_script_path(hook)), hook
        # ⚠ This was a bare `hasattr` and review called it vacuous -- correctly.
        # A mirror that EXISTS but traverses differently, or returns a different
        # description, is exactly the silent split the parity lock exists to
        # prevent, and `hasattr` passes on all of it. Compare the RETURNED
        # VALUES over the same matrix the sibling row drives.
        assert hasattr(cig, "_ci_hooks_config_voided_by"), (
            "ci_guard has no mirror of the whole-file voiding rule -- CI would "
            "pass a tree whose hooks Claude Code refuses to load"
        )
        for cfg in (
            {},
            {"SessionStart": [{"hooks": [{"type": "command",
                                          "command": "python3", "args": ["a.py"]}]}]},
            {"SessionStart": [{"hooks": [{"command": "python3", "args": ["a.py"]}]}]},
            {"SessionStart": [{"hooks": [{"type": "prompt",
                                          "command": "python3", "args": ["b.py"]}]}]},
            {"PreToolUse": [{"matcher": "*", "hooks": [{"command": "python3",
                                                        "args": ["c.py"]}]}]},
            # shapes where the two traversals could diverge rather than agree
            {"SessionStart": "not-a-list"},
            {"SessionStart": ["not-a-dict"]},
            {"SessionStart": [{"hooks": "not-a-list"}]},
            {"SessionStart": [{"hooks": [None]}]},
            {"SessionStart": [{}]},
            "not-a-dict",
        ):
            assert (sc.hooks_config_voided_by(cfg)
                    == cig._ci_hooks_config_voided_by(cfg)), (
                f"engine and ci_guard disagree about whether Claude Code would "
                f"load this hooks config: {cfg!r}"
            )


class TestStaleWriteGuardMatcher:
    """TP-169 §13 #9 / 169-D: the `espalier init` re-init stale-matcher WARN must
    fire ONLY when write_guard's OWN matcher cannot reach MCP tool calls — never on
    plan_guard / context_reinject_failure's narrow-by-design "Write|Edit|NotebookEdit"
    matchers (the pre-fix false positive that fired on every re-init of a CORRECT
    config and advised a destructive `rm + re-init`)."""

    @staticmethod
    def _settings(*entries):
        """Build a minimal settings dict from (event, matcher, script) tuples,
        wiring each script in the canonical exec form."""
        hooks: dict = {}
        for event, matcher, script in entries:
            hooks.setdefault(event, []).append({
                "matcher": matcher,
                "hooks": [{
                    "type": "command", "command": "python3",
                    "args": [f"${{CLAUDE_PROJECT_DIR}}/tools/cc/hooks/{script}"],
                }],
            })
        return {"hooks": hooks}

    # ── negatives: canonical / current config must NOT warn (the 169-D fix) ──
    def test_canonical_wiring_does_not_warn(self):
        s = self._settings(
            ("PreToolUse", "*", "write_guard.py"),
            ("PreToolUse", "Write|Edit|NotebookEdit", "plan_guard.py"),
            ("PostToolUseFailure", "Write|Edit|NotebookEdit",
             "context_reinject_failure.py"),
        )
        assert sc.write_guard_matcher_excludes_mcp(s) is False

    def test_live_settings_json_does_not_warn(self):
        """Earn-the-red inverse: the live on-disk settings.json tripped the pre-fix
        heuristic on EVERY re-init (matcher 'Write|Edit|NotebookEdit'); the scoped
        predicate clears it."""
        import json
        settings = REPO_ROOT / ".claude" / "settings.json"
        if not settings.is_file():
            # .claude/settings.json is gitignored + machine-specific: absent on
            # a fresh clone / CI (which never runs `espalier init`). The built-
            # settings variants below (test_freshly_built_settings_do_not_warn)
            # cover the same predicate without the local artifact. (TP-177 W0-1)
            pytest.skip(".claude/settings.json is local-only (gitignored)")
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert sc.write_guard_matcher_excludes_mcp(data) is False

    @pytest.mark.parametrize("profile", ["minimal", "workflow", "self-host", "full"])
    def test_freshly_built_settings_do_not_warn(self, profile):
        from espalier.cli import _build_settings_json
        built = _build_settings_json(profile_name=profile)
        assert sc.write_guard_matcher_excludes_mcp(built) is False

    def test_default_built_settings_do_not_warn(self):
        from espalier.cli import _build_settings_json
        assert sc.write_guard_matcher_excludes_mcp(_build_settings_json()) is False

    def test_plan_guard_narrow_with_write_guard_star_does_not_warn(self):
        # The exact 169-D shape: a narrow matcher present, write_guard '*' present.
        s = self._settings(
            ("PreToolUse", "Write|Edit|NotebookEdit", "plan_guard.py"),
            ("PreToolUse", "*", "write_guard.py"),
        )
        assert sc.write_guard_matcher_excludes_mcp(s) is False

    def test_write_guard_unwired_does_not_warn(self):
        # Deleted gate is the #8/N7 oracle's concern (doctor + ci_guard), not this
        # advisory — narrow matchers present, write_guard absent → stays silent.
        s = self._settings(
            ("PreToolUse", "Write|Edit|NotebookEdit", "plan_guard.py"),
            ("PostToolUseFailure", "Write|Edit|NotebookEdit",
             "context_reinject_failure.py"),
        )
        assert sc.write_guard_matcher_excludes_mcp(s) is False

    def test_old_combined_matcher_with_mcp_does_not_warn(self):
        # The deb5a0b-era combined matcher that INCLUDED mcp__.* was never stale.
        s = self._settings(
            ("PreToolUse", "Write|Edit|NotebookEdit|Bash|PowerShell|mcp__.*",
             "write_guard.py"),
        )
        assert sc.write_guard_matcher_excludes_mcp(s) is False

    def test_write_guard_absent_matcher_does_not_warn(self):
        # Absent matcher == fire-on-all in CC → reaches MCP → not stale.
        s = {"hooks": {"PreToolUse": [{
            "hooks": [{"type": "command", "command": "python3",
                       "args": ["tools/cc/hooks/write_guard.py"]}],
        }]}}
        assert sc.write_guard_matcher_excludes_mcp(s) is False

    def test_sibling_basename_does_not_false_match(self):
        # A hypothetical not_write_guard.py must not be read as the write_guard
        # entry (path-anchored /write_guard.py needle).
        s = self._settings(
            ("PreToolUse", "Write|Edit|NotebookEdit", "not_write_guard.py"),
        )
        assert sc.write_guard_matcher_excludes_mcp(s) is False

    # ── positives: genuinely stale write_guard MUST warn ──
    def test_stale_combined_matcher_warns(self):
        s = self._settings(
            ("PreToolUse", "Write|Edit|NotebookEdit|Bash|PowerShell",
             "write_guard.py"),
        )
        assert sc.write_guard_matcher_excludes_mcp(s) is True

    def test_stale_shell_form_write_guard_warns(self):
        # OLD shell-form command: the exec-form-only #8 resolver would MISS this,
        # but the upgrade WARN must recognize it (that is its whole purpose).
        s = {"hooks": {"PreToolUse": [{
            "matcher": "Write|Edit|NotebookEdit|Bash|PowerShell",
            "hooks": [{
                "type": "command",
                "command": "bash -c 'python3 "
                           "\"$CLAUDE_PROJECT_DIR/tools/cc/hooks/write_guard.py\"'",
            }],
        }]}}
        assert sc.write_guard_matcher_excludes_mcp(s) is True

    def test_non_string_matcher_on_write_guard_fails_closed(self):
        s = {"hooks": {"PreToolUse": [{
            "matcher": ["Write"],  # malformed
            "hooks": [{"type": "command", "command": "python3",
                       "args": ["tools/cc/hooks/write_guard.py"]}],
        }]}}
        assert sc.write_guard_matcher_excludes_mcp(s) is True

    # ── fullmatch semantics: a matcher CONTAINING "mcp__" but not fullmatching a
    #    real MCP tool name is stale (the #9 adversarial round — substring leniency).
    @pytest.mark.parametrize("matcher", [
        "Write|Edit|mcp__",                    # bare token (typo for mcp__.*)
        r"Write|Edit|NotebookEdit|mcp__\.\*",  # escaped .* (typo)
        "Write|mcp__nonexistent",              # non-functional mcp fragment
        "[",                                   # unparseable → fail-CLOSED
    ])
    def test_mcp_substring_that_does_not_fullmatch_warns(self, matcher):
        s = self._settings(("PreToolUse", matcher, "write_guard.py"))
        assert sc.write_guard_matcher_excludes_mcp(s) is True

    @pytest.mark.parametrize("matcher", [
        "*", "", ".*",
        "mcp__.*",
        "Write|Edit|NotebookEdit|Bash|PowerShell|mcp__.*",
        ".*mcp.*",
        "mcp__filesystem__.*",
        "mcp__[a-z_]+__.*",
        "(?i)MCP__.*",
    ])
    def test_matchers_that_reach_mcp_do_not_warn(self, matcher):
        s = self._settings(("PreToolUse", matcher, "write_guard.py"))
        assert sc.write_guard_matcher_excludes_mcp(s) is False

    @pytest.mark.parametrize("matcher,reaches", [
        ("*", True), ("", True), (".*", True),
        ("mcp__.*", True), ("mcp__filesystem__.*", True),
        (".*mcp.*", True), ("(?i)MCP__.*", True),
        ("Write|Edit|NotebookEdit|Bash|PowerShell|mcp__.*", True),
        ("Write|Edit|mcp__", False),            # bare token, fullmatches nothing real
        (r"mcp__\.\*", False),                  # escaped, literal mcp__.* tool name only
        ("Write|Edit|NotebookEdit", False),     # no mcp coverage at all
        ("[", False),                           # unparseable → fail-CLOSED
    ])
    def test_matcher_reaches_mcp_unit(self, matcher, reaches):
        assert sc._matcher_reaches_mcp(matcher) is reaches

    # ── resilience: malformed input never crashes, never warns ──
    @pytest.mark.parametrize("bad", [
        None, [], "x", 42, {}, {"hooks": None}, {"hooks": []},
        {"hooks": {"PreToolUse": "x"}}, {"hooks": {"PreToolUse": [None, 7]}},
        {"hooks": {"PreToolUse": [{"hooks": "nope"}]}},
    ])
    def test_malformed_settings_do_not_warn(self, bad):
        assert sc.write_guard_matcher_excludes_mcp(bad) is False


def test_decode_bom_three_copy_parity():
    """TP-169 §13 #8 round-7: the BOM-decode helper has 3 isolation-domain copies
    (surface_contract / tools/cc/_json_safe / ci_guard inline). They must agree
    byte-for-byte on every encoding, or a BOM'd settings.json is read differently
    by the offline vs runtime vs CI legs."""
    import codecs as _c
    import importlib.util
    root = Path(__file__).resolve().parent.parent
    js = importlib.util.spec_from_file_location("_js_bom", root / "tools/cc/_json_safe.py")
    jsm = importlib.util.module_from_spec(js); js.loader.exec_module(jsm)
    cg = importlib.util.spec_from_file_location("_cg_bom", root / "tools/cc/ci_guard.py")
    cgm = importlib.util.module_from_spec(cg); cg.loader.exec_module(cgm)
    payload = '{"hooks":{}}'
    samples = {
        "plain": payload.encode("utf-8"),
        "utf8-bom": _c.BOM_UTF8 + payload.encode("utf-8"),
        "utf16-le": _c.BOM_UTF16_LE + payload.encode("utf-16-le"),
        "utf16-be": _c.BOM_UTF16_BE + payload.encode("utf-16-be"),
        "utf32-le": _c.BOM_UTF32_LE + payload.encode("utf-32-le"),
        "utf32-be": _c.BOM_UTF32_BE + payload.encode("utf-32-be"),
    }
    for name, raw in samples.items():
        a = sc.decode_bom(raw)
        b = jsm.decode_bom(raw)
        c = cgm._ci_decode_bom(raw)
        assert a == b == c == payload, f"decode_bom parity/decode broke on {name}: {a!r}/{b!r}/{c!r}"


def test_decode_text_or_problem_two_copy_parity():
    """DEF-797: the decode-then-check helper for the files an operator writes by
    hand has two isolation-domain copies (surface_contract / tools/cc/_json_safe).
    They must agree on every shape: marked UTF-8/16/32 read clean, a mark-less
    UTF-16 file is named by its NULs, bytes that are not UTF-8 are named by the
    codec's reason, and the sentence is one sentence."""
    import codecs as _c
    import importlib.util
    root = Path(__file__).resolve().parent.parent
    js = importlib.util.spec_from_file_location("_js_dtp", root / "tools/cc/_json_safe.py")
    jsm = importlib.util.module_from_spec(js); js.loader.exec_module(jsm)
    payload = "# Memory\n\n**Repo:** demo\n"
    samples = {
        "plain": payload.encode("utf-8"),
        "utf8-bom": _c.BOM_UTF8 + payload.encode("utf-8"),
        "utf16-le": _c.BOM_UTF16_LE + payload.encode("utf-16-le"),
        "utf16-be": _c.BOM_UTF16_BE + payload.encode("utf-16-be"),
        "utf32-le": _c.BOM_UTF32_LE + payload.encode("utf-32-le"),
        "utf16-le-no-bom": payload.encode("utf-16-le"),
        "cp1252": "caf\xe9\n".encode("cp1252"),
        "empty": b"",
    }
    for name, raw in samples.items():
        a = sc.decode_text_or_problem(raw)
        b = jsm.decode_text_or_problem(raw)
        assert a == b, f"decode_text_or_problem parity broke on {name}: {a!r}/{b!r}"
    for name in ("plain", "utf8-bom", "utf16-le", "utf16-be", "utf32-le"):
        assert sc.decode_text_or_problem(samples[name]) == (payload, ""), name
    assert sc.decode_text_or_problem(samples["empty"]) == ("", "")
    text, problem = sc.decode_text_or_problem(samples["utf16-le-no-bom"])
    assert text == "" and "NUL bytes -- UTF-16 without a byte-order mark?" in problem
    text, problem = sc.decode_text_or_problem(samples["cp1252"])
    assert text == "" and problem.startswith("not UTF-8 text (invalid continuation byte at byte 3)")
    assert problem.endswith("re-save it as UTF-8; a UTF-8 or UTF-16 byte-order mark is read")


def test_os_error_text_two_copy_parity():
    """DEF-799: the OSError renderer has two isolation-domain copies
    (espalier/_text / tools/cc/_json_safe). They must agree on every shape
    Python's own ``OSError.__str__`` distinguishes: a filename (rendered plain,
    not through repr), a second filename after ``->``, a spaced path (quoted),
    a bytes or path-like filename, no filename at all (``str(exc)`` unchanged),
    and a non-OSError from the same handler tuple (unchanged too)."""
    import importlib.util
    import subprocess
    from espalier import _text
    root = Path(__file__).resolve().parent.parent
    js = importlib.util.spec_from_file_location("_js_oet", root / "tools/cc/_json_safe.py")
    jsm = importlib.util.module_from_spec(js); js.loader.exec_module(jsm)
    samples = {
        "windows-path": OSError(13, "Access is denied", r"C:\repo\.claude"),
        "two-paths": OSError(2, "No such file or directory", "/a/b", None, "/c/d"),
        "spaced": OSError(13, "Permission denied", "/Program Files/x"),
        "bytes": OSError(2, "No such file or directory", b"/by/tes"),
        "pathlike": OSError(2, "No such file or directory", Path("/p/q")),
        "no-filename": OSError(5, "Input/output error"),
        "bare": OSError("just a message"),
        "not-oserror": subprocess.TimeoutExpired(["git"], 5),
    }
    for name, exc in samples.items():
        a = _text.os_error_text(exc)
        b = jsm.os_error_text(exc)
        assert a == b, f"os_error_text parity broke on {name}: {a!r}/{b!r}"
    assert _text.os_error_text(samples["windows-path"]) == r"[Errno 13] Access is denied: C:\repo\.claude"
    assert _text.os_error_text(samples["two-paths"]) == "[Errno 2] No such file or directory: /a/b -> /c/d"
    assert _text.os_error_text(samples["spaced"]) == '[Errno 13] Permission denied: "/Program Files/x"'
    assert _text.os_error_text(samples["bytes"]) == "[Errno 2] No such file or directory: /by/tes"
    # the path-like sample spells itself per host: `Path("/p/q")` is `\p\q` on Windows
    assert _text.os_error_text(samples["pathlike"]) == f"[Errno 2] No such file or directory: {os.fspath(Path('/p/q'))}"
    for name in ("no-filename", "bare", "not-oserror"):
        assert _text.os_error_text(samples[name]) == str(samples[name]), name


def test_load_json_dict_safe_reads_a_utf16_byte_order_mark():
    """The dict loader is one of the helpers the settings-reader BOM contract
    accepts as tolerant; until 2026-09-15 it read only the UTF-8 mark, so a
    UTF-16 settings file came back as the fallback (fail-open for a kill-switch
    reader). It decodes through ``decode_bom`` now."""
    import codecs as _c
    import importlib.util
    root = Path(__file__).resolve().parent.parent
    js = importlib.util.spec_from_file_location("_js_ldj", root / "tools/cc/_json_safe.py")
    jsm = importlib.util.module_from_spec(js); js.loader.exec_module(jsm)
    payload = '{"disableAllHooks": true}'
    for raw in (_c.BOM_UTF16_LE + payload.encode("utf-16-le"), _c.BOM_UTF32_BE + payload.encode("utf-32-be"),
                _c.BOM_UTF8 + payload.encode("utf-8"), payload.encode("utf-8")):
        assert jsm.load_json_dict_safe(raw) == {"disableAllHooks": True}, raw[:4]
    assert jsm.load_json_dict_safe(b"\xff\xfe\x00") == {}
    assert jsm.load_json_dict_safe(b"caf\xe9", default=None) is None


class TestIsEffectivelyEmptyFile:
    """`is_effectively_empty_file` is the one predicate behind init's
    "an empty settings.json is absent" decision (DEF-700), so its false side
    is the load-bearing one: any content, and any read failure, must read as
    NOT empty or init would overwrite a file it should preserve."""

    def test_empty_shapes(self, tmp_path):
        from espalier.surface_contract import is_effectively_empty_file
        for raw in (b"", b"   ", b"\n\t\r\n", b"\xef\xbb\xbf", b"\xef\xbb\xbf \n",
                    b"\xff\xfe", b"\xff\xfe\x00\x00", b"\xfe\xff\x00 \x00\n"):
            p = tmp_path / "s.json"
            p.write_bytes(raw)
            assert is_effectively_empty_file(p), raw

    def test_content_absent_and_unreadable_are_not_empty(self, tmp_path):
        from espalier.surface_contract import is_effectively_empty_file
        p = tmp_path / "s.json"
        for raw in (b"{}", b" x ", b'{"hooks": {"PreToolUse": [', b"\x80\x81"):
            p.write_bytes(raw)
            assert not is_effectively_empty_file(p), raw
        p.unlink()
        assert not is_effectively_empty_file(p)
        assert not is_effectively_empty_file(tmp_path)  # a directory: read fails


class TestDiscoverClaudeKinds:
    """The ``.claude/`` kinds have one owner and one discoverer each (DEF-532)."""

    def test_a_precise_leaf_is_matched_by_exact_name(self, tmp_path):
        """``*/SKILL.md`` has a precise final component, which pathlib resolves
        with an existence check: on APFS and NTFS a stray ``skill.md`` matched
        and was reported as ``SKILL.md``, a spelling not on disk and a file the
        deploy never wrote. The listing is by wildcard, filtered by exact name,
        so the lowercase file is not a skill on any filesystem."""
        (tmp_path / ".claude" / "skills" / "mine").mkdir(parents=True)
        (tmp_path / ".claude" / "skills" / "mine" / "skill.md").write_text("x", encoding="utf-8")
        (tmp_path / ".claude" / "skills" / "real").mkdir()
        (tmp_path / ".claude" / "skills" / "real" / "SKILL.md").write_text("x", encoding="utf-8")
        assert sc.discover_installed_skills(tmp_path) == [".claude/skills/real/SKILL.md"]

    def test_every_owned_kind_has_a_glob_and_the_composite_reports_each(self, tmp_path):
        assert tuple(sc.CLAUDE_KIND_GLOBS) == sc.CLAUDE_SURFACE_KINDS
        assert sc.discover_claude_surface(tmp_path) == {k: [] for k in sc.CLAUDE_SURFACE_KINDS}
        composite = sc.discover_self_host_surface(tmp_path)
        assert set(sc.CLAUDE_SURFACE_KINDS) <= composite.keys()
        for kind, glob in sc.CLAUDE_KIND_GLOBS.items():
            rel = f".claude/{kind}/" + glob.replace("*", "one")
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text("x", encoding="utf-8")
        assert sc.discover_claude_surface(tmp_path) == {
            kind: [f".claude/{kind}/" + glob.replace("*", "one")]
            for kind, glob in sc.CLAUDE_KIND_GLOBS.items()
        }


_posix_perms = pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permission bits and a non-root user",
)


class TestPathPresenceIsClassifiedByErrno:
    """DEF-763: pathlib's existence methods answer a parent that denies
    traversal per interpreter -- CPython 3.10-3.13 raise ``PermissionError``,
    3.14 returns ``False`` -- so the same tree read as a crash on four
    supported floors and as "absent" on the fifth. The oracle answers by the
    stat's errno; these rows hold on every interpreter the suite runs under,
    and the first row pins the boundary itself, so a CI cell reds the day
    the claim drifts.
    """

    @_posix_perms
    def test_the_interpreter_boundary_is_where_the_docs_say(self, tmp_path):
        """Measured on real 3.10, 3.13 and 3.14 interpreters 2026-09-13: the
        first cut of this lane wrote "3.13+" at eight sites on the strength of
        a 3.10-vs-3.14 drive alone. `tests/_legacy_pathlib.py` transcribes the
        3.10-3.13 bodies; this row makes the boundary a measurement on every
        cell rather than a sentence in a comment."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text("{}", encoding="utf-8")
        with locked(claude_dir):
            raises = probes_raise_on_eacces(claude_dir / "settings.json")
        assert raises == (sys.version_info < (3, 14)), (
            f"Path.exists() {'raised' if raises else 'swallowed'} EACCES on "
            f"{sys.version.split()[0]}; the oracle's comments and docs/SHARP_EDGES.md "
            "place the switch at 3.14 -- move every one of them if this is real."
        )

    def test_an_absent_parent_and_an_absent_leaf_read_as_absent(self, tmp_path):
        assert sc.path_presence(tmp_path / "nowhere" / "settings.json") == (sc.PRESENCE_ABSENT, "")
        assert sc.path_presence(tmp_path / "settings.json") == (sc.PRESENCE_ABSENT, "")

    def test_a_parent_that_is_a_plain_file_reads_as_absent(self, tmp_path):
        (tmp_path / ".claude").write_text("not a directory\n", encoding="utf-8")
        assert sc.path_presence(tmp_path / ".claude" / "settings.json") == (sc.PRESENCE_ABSENT, "")

    def test_a_present_file_and_a_present_directory_read_as_present(self, tmp_path):
        present = tmp_path / "settings.json"
        present.write_text("{}", encoding="utf-8")
        assert sc.path_presence(present) == (sc.PRESENCE_PRESENT, "")
        assert sc.path_presence(tmp_path) == (sc.PRESENCE_PRESENT, "")

    def test_a_dangling_symlink_reads_as_absent(self, tmp_path):
        link = tmp_path / "settings.json"
        try:
            link.symlink_to(tmp_path / "gone.json")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable here")
        assert sc.path_presence(link) == (sc.PRESENCE_ABSENT, "")

    @_posix_perms
    def test_a_parent_that_denies_traversal_reads_as_unreadable(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text("{}", encoding="utf-8")
        with locked(claude_dir):
            kind, detail = sc.path_presence(claude_dir / "settings.json")
        assert kind == sc.PRESENCE_UNREADABLE
        assert "Permission denied" in detail and "settings.json" in detail

    @_posix_perms
    def test_a_file_with_no_read_bit_is_present_not_unreadable(self, tmp_path):
        """Reachability, not readability: the read reports its own error,
        with its own message, as the merge and the predicate already do."""
        present = tmp_path / "settings.json"
        present.write_text("{}", encoding="utf-8")
        with locked(present):
            assert sc.path_presence(present) == (sc.PRESENCE_PRESENT, "")

    @_posix_perms
    def test_the_hooks_loader_answers_none_for_a_locked_parent(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text('{"hooks": {}}', encoding="utf-8")
        with locked(claude_dir):
            assert sc._load_settings_hooks_cfg(tmp_path) is None
        assert sc._load_settings_hooks_cfg(tmp_path) == {}


class TestUnreadableHarnessRoot:
    """One question every command asks first: can ``.claude`` be searched and
    listed? ``None`` hands the tree on to the arms that own absence and the
    not-a-directory shape; a detail is the one sentence the command prints."""

    def test_an_absent_claude_is_not_unreadable(self, tmp_path):
        assert sc.unreadable_harness_root(tmp_path) is None

    def test_a_claude_that_is_a_plain_file_is_not_unreadable(self, tmp_path):
        (tmp_path / ".claude").write_text("x", encoding="utf-8")
        assert sc.unreadable_harness_root(tmp_path) is None

    def test_a_readable_claude_is_not_unreadable_with_or_without_settings(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        assert sc.unreadable_harness_root(tmp_path) is None
        (claude_dir / "settings.json").write_text("{}", encoding="utf-8")
        assert sc.unreadable_harness_root(tmp_path) is None

    @_posix_perms
    @pytest.mark.parametrize(
        "mode", [0, stat.S_IRUSR, stat.S_IXUSR], ids=["no bits", "read only", "search only"],
    )
    def test_each_lock_shape_on_claude_is_named(self, tmp_path, mode):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text("{}", encoding="utf-8")
        with locked(claude_dir, mode):
            detail = sc.unreadable_harness_root(tmp_path)
        assert detail is not None and "Permission denied" in detail, detail

    @_posix_perms
    def test_a_locked_parent_of_claude_is_named(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".claude").mkdir(parents=True)
        with locked(repo):
            detail = sc.unreadable_harness_root(repo)
        assert detail is not None and "Permission denied" in detail, detail

    def test_a_symlink_loop_at_claude_is_unreadable_not_absent(self, tmp_path):
        """ELOOP: pathlib's own ignored-errno table reads a loop as absent;
        this oracle deliberately does not (`_ABSENT_ERRNOS`), because `init`
        could not write through it either and the operator has to resolve
        it. The sentence says "resolve that", and names permissions only as
        the usual cause."""
        try:
            (tmp_path / ".claude").symlink_to(tmp_path / ".claude")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable here")
        kind, detail = sc.path_presence(tmp_path / ".claude" / "settings.json")
        assert kind == sc.PRESENCE_UNREADABLE, (kind, detail)
        root_detail = sc.unreadable_harness_root(tmp_path)
        assert root_detail is not None and "symbolic links" in root_detail, root_detail
        sentence = sc.unreadable_root_sentence(root_detail)
        assert sentence.startswith(".claude cannot be read (") and "resolve that" in sentence


class TestTrackedPathsWhenGitPrintsANameTheDecoderRefuses:
    """Ledger DEF-821. ``tracked_paths`` reads ``git ls-files --cached -z`` --
    raw bytes -- and on a name that is not UTF-8 answered None ("no index"),
    so every path in the tree read as untracked because of one file. One
    replaced character in one path is the narrower wrong answer: the set is
    complete and only the unnameable file misses. The oracle is a ``git`` on
    PATH that prints such a name (APFS cannot hold one). Skips where ``sh`` is
    absent; unverified on Windows."""

    def test_one_unnameable_file_does_not_empty_the_index(self, tmp_path, monkeypatch):
        if os.name == "nt" or shutil.which("sh") is None:
            pytest.skip("the git shim is a /bin/sh script")
        bindir = tmp_path / "bin"
        bindir.mkdir()
        shim = bindir / "git"
        shim.write_text("#!/bin/sh\nprintf 'ok.txt\\0caf\\351.txt\\0'\n", encoding="utf-8")
        shim.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        assert sc.tracked_paths(repo) == {"ok.txt", "caf�.txt"}
