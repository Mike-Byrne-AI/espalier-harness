"""Tests for ``espalier.managed_paths`` — the ownership-classification
helpers that ``espalier.cleanup``, the integrity manifest, and the
init lifecycle all delegate to for "is this file harness-managed?"

Pins the managed-path discovery rules: ``managed_paths_from_plan``
includes the standard CC files, output is deduped+sorted,
``ownership_summary`` correctly classifies
self-host vs adopter layouts. Without this contract a classification
regression would silently let cleanup delete adopter user files
(over-reach) OR refuse to remove harness artifacts on uninstall
(under-reach) — both modes are hard for the adopter to recover from.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path


from espalier import surface_contract
from espalier.managed_paths import (
    HARNESS_OWNED_ROOTS,
    fallback_managed_paths,
    managed_paths_for_repo,
    managed_paths_from_plan,
    ownership_summary,
    self_host_managed_paths,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_plan(harness_repo: Path) -> dict:
    return json.loads((harness_repo / "reports" / "harness_config.json").read_text(encoding="utf-8"))


class TestHarnessOwnedRootsSingleOwner:
    """1-A single-owner pin: the coarse owned-roots literal
    ``[".claude", "cc", "tools/cc"]`` must exist at exactly ONE non-test
    production site — the ``HARNESS_OWNED_ROOTS`` definition. Guards against a
    re-introduced hard-copy (a future ownership dict that inlines the list
    again) silently re-breaking the single-source-of-truth invariant
    (STANDING_PRINCIPLES §8) the dedup established. The dedup's earn-red only
    pins that the two known consumers DERIVE from the constant; without this
    pin, a third copy reds nothing and the invariant decays to manual vigilance.
    """

    # HARNESS_OWNED_ROOTS is the SoT; the literal sequence is derived from it so
    # a future edit to the constant keeps this pin in lock-step (no second copy).
    _SEQUENCE = tuple(HARNESS_OWNED_ROOTS)

    @staticmethod
    def _iter_production_files():
        # Shipping surfaces where an owned-roots hard-copy could regress.
        # Exclude espalier/_vendor/ (a byte-mirror of tools/cc/ — would
        # double-count) and __pycache__; tests/ is out of scope (this pins
        # production sites, and the pin's own fixtures use the literal).
        for root in (REPO_ROOT / "espalier", REPO_ROOT / "tools" / "cc"):
            for path in sorted(root.rglob("*.py")):
                if "_vendor" in path.parts or "__pycache__" in path.parts:
                    continue
                yield path

    @classmethod
    def _matches_sequence(cls, node: ast.AST) -> bool:
        if not isinstance(node, (ast.List, ast.Tuple)):
            return False
        if len(node.elts) != len(cls._SEQUENCE):
            return False
        values = [
            e.value for e in node.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
        return tuple(values) == cls._SEQUENCE

    @classmethod
    def _literal_sites(cls) -> list[str]:
        sites: list[str] = []
        for path in cls._iter_production_files():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if cls._matches_sequence(node):
                    # as_posix(), not str(): a bare f-string interpolation of a
                    # Path uses the OS separator, so Windows produced
                    # 'espalier\managed_paths.py:99' and the forward-slash
                    # startswith() below failed for an otherwise-correct site.
                    rel = path.relative_to(REPO_ROOT).as_posix()
                    sites.append(f"{rel}:{node.lineno}")
        return sites

    def test_owned_roots_literal_has_single_owner(self):
        sites = self._literal_sites()
        assert len(sites) == 1, (
            "The coarse owned-roots literal must have exactly one owner "
            "(managed_paths.HARNESS_OWNED_ROOTS). A re-introduced hard-copy "
            "re-breaks the single-source-of-truth invariant — derive from the "
            f"constant instead. Sites found: {sites!r}"
        )
        assert sites[0].startswith("espalier/managed_paths.py:"), (
            f"the sole owned-roots literal is not HARNESS_OWNED_ROOTS: {sites[0]!r}"
        )

    def test_matcher_detects_synthetic_hardcopy(self, tmp_path):
        """Vacuous-pass guard: prove the AST matcher detects the ordered literal,
        so the single-owner assertion can't pass merely because the matcher
        silently found nothing."""
        synthetic = tmp_path / "fake_owner.py"
        synthetic.write_text(
            'd = {"harness_owned_roots": [".claude", "cc", "tools/cc"]}\n',
            encoding="utf-8",
        )
        tree = ast.parse(synthetic.read_text(encoding="utf-8"))
        found = [n.lineno for n in ast.walk(tree) if self._matches_sequence(n)]
        assert found, "AST matcher failed to detect a synthetic owned-roots hard-copy"


class TestManagedPathsFromPlan:
    def test_managed_paths_includes_standard_files(self, harness_repo):
        """managed_paths_from_plan returns the core CC managed files."""
        plan = _load_plan(harness_repo)
        paths = managed_paths_from_plan(plan)
        assert ".claude/settings.json" in paths
        assert "CLAUDE.md" in paths
        assert "cc/LIVE_SURFACE.md" in paths

    def test_managed_paths_deduped_and_sorted(self, harness_repo):
        """Result is sorted and has no duplicates."""
        plan = _load_plan(harness_repo)
        paths = managed_paths_from_plan(plan)
        assert paths == sorted(set(paths))

    def test_managed_paths_includes_all_canonical_hooks(self, harness_repo):
        """Generic plan ownership covers every canonical hook path."""
        plan = _load_plan(harness_repo)
        paths = set(managed_paths_from_plan(plan))
        for hook in surface_contract.get_canonical_hook_scripts():
            assert f"tools/cc/hooks/{hook}" in paths


class TestFallbackManagedPaths:
    def test_fallback_discovers_deployed_files(self, harness_repo):
        """fallback_managed_paths finds the files the fixture deployed."""
        paths = fallback_managed_paths(harness_repo)
        assert ".claude/settings.json" in paths

    def test_fallback_on_empty_repo(self, tmp_path):
        """fallback_managed_paths returns an empty list for a bare repo."""
        paths = fallback_managed_paths(tmp_path)
        assert paths == []

    def test_fallback_names_every_claude_file_the_deploy_writes(self, tmp_path):
        """The adopter's disk-reality view names every ``.claude/`` file
        ``init`` deploys from packaged bodies, and nothing under ``.claude/``
        outside those kinds -- both directions. The deploy's own enumerator is
        the oracle, so a kind the deploy learns and this view does not reds
        here; the kinds it writes must equal the kinds the contract owns.
        Driven 2026-09-11 on a fresh init: nine skill files deployed and named
        by clean-generated, none owned, because two hand-written globs here saw
        agents and commands and never skills (DEF-532)."""
        from espalier.cli import _packaged_md_assets
        deployed = {rel for rel, _src in _packaged_md_assets(REPO_ROOT)}
        assert deployed, "the packaged .claude/ surface enumerated as empty"
        kinds = {rel.split("/")[1] for rel in deployed}
        owned = set(surface_contract.CLAUDE_SURFACE_KINDS)
        assert kinds == owned, (
            "the deploy writes a kind the contract does not own, or the "
            f"contract names one the deploy never writes: {sorted(kinds ^ owned)}"
        )
        for rel in deployed:
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text("x", encoding="utf-8")
        # Not the deploy's: a kind nothing deploys, a stray file inside a
        # skill directory that is not the SKILL.md body, and a lowercase
        # skill.md -- on APFS and NTFS a precise glob component matched it
        # and reported it under the SKILL.md spelling (driven 2026-09-11).
        decoys = (
            ".claude/plugins/x.md",
            ".claude/skills/reflect/README.md",
            ".claude/skills/mine/skill.md",
        )
        for rel in decoys:
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text("x", encoding="utf-8")
        got = set(fallback_managed_paths(tmp_path))
        missing = deployed - got
        assert not missing, (
            f"deployed .claude/ files the ownership view does not name: {sorted(missing)}"
        )
        assert not (set(decoys) & got), sorted(set(decoys) & got)
        assert not [p for p in got if p.startswith(".claude/skills/mine/")], (
            "the adopter's own skill.md was claimed under a spelling not on disk"
        )


class TestOwnershipSummary:
    def test_ownership_summary_structure(self, harness_repo):
        """ownership_summary returns all expected keys in plan mode."""
        plan = _load_plan(harness_repo)
        summary = ownership_summary(plan)
        expected_keys = {
            "mode", "harness_owned_roots", "managed_paths", "managed_settings",
            "managed_cc_docs", "managed_tools", "managed_reports",
            "managed_root_docs", "plan_derived_managed_paths",
        }
        assert expected_keys.issubset(summary.keys())
        assert summary["mode"] == "plan"

    def test_ownership_summary_self_host_mode(self):
        """Self-host mode reports disk reality and plan-derived separately."""
        summary = ownership_summary(repo_root=REPO_ROOT)
        assert summary["mode"] == "self_host"
        assert "espalier" in summary["harness_owned_roots"]
        # Disk reality includes commands, agents, skills, hooks
        assert any(p.startswith(".claude/commands/") for p in summary["managed_paths"])
        assert any(p.startswith(".claude/agents/") for p in summary["managed_paths"])
        assert any(p.startswith(".claude/skills/") for p in summary["managed_paths"])

    def test_ownership_summary_adopter_reports_disk_reality(self, tmp_path):
        """TP-197: a plan-bearing adopter's ownership report reflects DISK reality,
        not the plan — it includes every deployed agent (not just the plan-listed
        ones) and excludes docs init did not deploy; the plan view stays separate."""
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        for name in ("alpha", "beta", "gamma"):
            (agents_dir / f"{name}.md").write_text("x", encoding="utf-8")
        (tmp_path / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        (tmp_path / "CLAUDE.md").write_text("x", encoding="utf-8")
        # Plan lists only alpha; beta/gamma are tier-deployed. No generated docs on disk.
        plan = {"agents": [{"name": "alpha"}], "generated_docs": []}

        summary = ownership_summary(plan, repo_root=tmp_path)
        managed = summary["managed_paths"]
        # Under-claim fixed: every on-disk agent is reported, not just the plan's one.
        assert ".claude/agents/beta.md" in managed
        assert ".claude/agents/gamma.md" in managed
        # Over-claim fixed: a doc init did not deploy is absent from the disk report...
        assert "docs/CONVENTIONS.md" not in managed
        # ...but the intended (plan-derived) view still names it.
        assert "docs/CONVENTIONS.md" in summary["plan_derived_managed_paths"]

    def test_ownership_summary_root_docs_excludes_dotclaude_paths(self, tmp_path):
        """DR8 round-8: managed_root_docs must not mislabel .claude/ config paths
        as root documentation — only no-slash root files and docs/ entries qualify."""
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "alpha.md").write_text("x", encoding="utf-8")
        (tmp_path / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        (tmp_path / "CLAUDE.md").write_text("x", encoding="utf-8")
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "CONVENTIONS.md").write_text("x", encoding="utf-8")
        plan = {"agents": [{"name": "alpha"}]}

        summary = ownership_summary(plan, repo_root=tmp_path)
        root_docs = summary["managed_root_docs"]
        # .claude/ config paths are NOT root docs (the old `startswith(".")` bug).
        assert not any(p.startswith(".claude/") for p in root_docs)
        # Real root docs are classified correctly: a no-slash file and a docs/ entry.
        assert "CLAUDE.md" in root_docs
        assert "docs/CONVENTIONS.md" in root_docs


class TestSelfHostManagedPaths:
    """Pack 2-A exit criteria — self-host ownership derived from surface_contract."""

    def test_self_host_contains_smoke_command(self):
        # TP-40: /audit was folded into /smoke; /smoke is the new anchor.
        paths = self_host_managed_paths(REPO_ROOT)
        assert ".claude/commands/smoke.md" in paths

    def test_self_host_contains_repo_analyst_agent(self):
        paths = self_host_managed_paths(REPO_ROOT)
        assert ".claude/agents/repo-analyst.md" in paths

    def test_self_host_contains_every_installed_claude_kind(self):
        """Each ``.claude/`` kind the contract owns is discovered non-empty on
        this checkout and every discovered path is owned (DEF-532: the skills
        key was reported by the discoverer and never read here)."""
        paths = set(self_host_managed_paths(REPO_ROOT))
        surface = surface_contract.discover_self_host_surface(REPO_ROOT)
        for kind in surface_contract.CLAUDE_SURFACE_KINDS:
            assert surface[kind], f"{kind}: nothing discovered on this checkout"
            assert set(surface[kind]) <= paths, sorted(set(surface[kind]) - paths)
        assert ".claude/skills/reflect/SKILL.md" in paths

    def test_self_host_contains_task_router_hook(self):
        paths = self_host_managed_paths(REPO_ROOT)
        assert "tools/cc/hooks/task_router.py" in paths

    def test_self_host_contains_plan_guard_hook(self):
        paths = self_host_managed_paths(REPO_ROOT)
        assert "tools/cc/hooks/plan_guard.py" in paths

    def test_self_host_contains_harness_config_report(self):
        paths = self_host_managed_paths(REPO_ROOT)
        assert "reports/harness_config.json" in paths

    def test_self_host_excludes_phantom_convention_monitor(self):
        paths = self_host_managed_paths(REPO_ROOT)
        assert ".claude/agents/convention-monitor.md" not in paths

    def test_self_host_is_sorted_deduped_forward_slash(self):
        paths = self_host_managed_paths(REPO_ROOT)
        assert paths == sorted(paths)
        assert len(paths) == len(set(paths))
        for p in paths:
            assert "\\" not in p


class TestManagedPathsForRepo:
    """Dispatch function routes by is_self_host_repo."""

    def test_dispatch_self_host(self):
        paths = managed_paths_for_repo(REPO_ROOT)
        # TP-40: /audit folded into /smoke; anchor on /smoke now.
        assert ".claude/commands/smoke.md" in paths
        assert "tools/cc/hooks/task_router.py" in paths

    def test_dispatch_plan_mode(self, harness_repo):
        plan = _load_plan(harness_repo)
        paths = managed_paths_for_repo(harness_repo, plan)
        # harness_repo is not the Espalier-Harness repo (wrong project name), so plan wins
        assert ".claude/settings.json" in paths

    def test_dispatch_fallback_on_empty(self, tmp_path):
        paths = managed_paths_for_repo(tmp_path)
        assert paths == []


class TestCanonicalHookCountFromContract:
    """Pack 2-A replacement for the deleted STANDARD_MANAGED_HOOKS test."""

    def test_canonical_hook_count_matches_expected(self):
        from tests._surface_expected import EXPECTED_HOOK_COUNT
        assert len(surface_contract.get_canonical_hook_scripts()) == EXPECTED_HOOK_COUNT

    def test_canonical_hooks_match_disk(self):
        hooks_dir = REPO_ROOT / "tools" / "cc" / "hooks"
        disk_hooks = sorted(
            p.name for p in hooks_dir.glob("*.py") if not p.name.startswith("_")
        )
        assert sorted(surface_contract.get_canonical_hook_scripts()) == disk_hooks
