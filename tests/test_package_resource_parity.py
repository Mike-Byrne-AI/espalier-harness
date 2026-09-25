"""TP-01 — Package Resource Parity.

Wheel-installed Espalier-Harness must deploy the same harness surface as a
source checkout.

Direction, per ``espalier/mirror_registry.py`` — the census, not this prose: the
``.claude/`` SOURCE TREE is the source of truth and the packaged
``espalier/assets/claude/`` copy is generated (rows ``claude-asset`` and
``claude-dogfooding``, both ``sot-is-source-tree``). Only ``harness-guard.yml``
runs the other way: ``harness-guard`` is the single ``is_inverted`` row, where
the packaged asset IS the SoT and the root file is generated. An earlier version
of this docstring stated the package as SoT for all three, which is true for one
row and backwards for two -- a compound sentence that survives review because
half of it is right. The root ``.claude/`` mirror is enforced byte-for-byte
(modulo line endings) by ``test_root_claude_mirrors_dogfooding``.
"""
from __future__ import annotations

from importlib.resources import as_file
from pathlib import Path

import pytest

from espalier.asset_inventory import packaged_agent_names
from espalier.assets import (
    AssetNotFound,
    assets_root,
    github_workflow_asset,
    iter_claude_asset_files,
)
from espalier.asset_inventory import get_packaged_surface
from tests._surface_expected import (
    EXPECTED_AGENT_COUNT_MIN,
    EXPECTED_COMMAND_COUNT,
    EXPECTED_HOOK_ENTRY_COUNT,
    EXPECTED_HOOK_HELPER_COUNT,
    EXPECTED_SKILL_COUNT,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Stub agents are <500 bytes; rich agents are 7KB+. 2KB is comfortably above
# the largest plausible stub and below the smallest rich agent.
RICH_AGENT_MIN_BYTES = 2048


pytestmark = [pytest.mark.contract, pytest.mark.release]


# ---------------------------------------------------------------------------
# Cardinality — package contains the documented surface
# ---------------------------------------------------------------------------


class TestPackagedAssetCounts:
    """TP-50: agents / commands / skills ship as packaged assets; deploy_harness
    deploys them with TP-03 marker discipline. Counts derive from
    ``tests/_surface_expected.py`` so a new surface item updates one
    constant and every consumer follows.
    """

    def test_command_count_matches_expected(self):
        commands = iter_claude_asset_files("commands")
        assert len(commands) == EXPECTED_COMMAND_COUNT, (
            f"Expected {EXPECTED_COMMAND_COUNT} packaged commands "
            f"(see EXPECTED_COMMAND_COUNT in _surface_expected.py), "
            f"got {len(commands)}"
        )

    def test_skill_count_matches_expected(self):
        skills = iter_claude_asset_files("skills")
        skill_md = [p for p in skills if p.name == "SKILL.md"]
        assert len(skill_md) == EXPECTED_SKILL_COUNT, (
            f"Expected {EXPECTED_SKILL_COUNT} packaged SKILL.md files, "
            f"got {len(skill_md)}"
        )

    def test_agent_count_at_or_above_floor(self):
        agents = iter_claude_asset_files("agents")
        assert len(agents) >= EXPECTED_AGENT_COUNT_MIN, (
            f"Expected at least {EXPECTED_AGENT_COUNT_MIN} packaged agents, "
            f"got {len(agents)}"
        )

    def test_workflow_packaged(self):
        node = github_workflow_asset("harness-guard.yml")
        assert node.is_file()
        assert node.read_bytes().startswith(b"name:")


# ---------------------------------------------------------------------------
# Rich agents — the package asset tree ships the roster again (seven at HEAD).
# TestBundledRichAgents was removed when TP-31 emptied the tree; today the
# bytes are pinned by TestAssetClaudeMirrorParity (against .claude/) and
# TestRootMirrorParity (against the dogfooding mirror), and the count by
# TestPackagedAgentNames below.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Inventory — get_packaged_surface() agrees with the resource view
# ---------------------------------------------------------------------------


class TestPackagedSurfaceInventory:
    def test_inventory_counts_match_resource_view(self):
        surface = get_packaged_surface()
        # TP-50: assets ship; counts derive from _surface_expected.py SoT.
        # TP-151 G-1: hook_entries / hook_helpers are now derived from the
        # managed SoT (surface_contract / managed_inventory), so they pin to
        # the independent _surface_expected witnesses (10 / 8), not the former
        # third hand-maintained copy (which was stale at 9 / 7 — missing
        # subagent_stop.py and _denial_reasons.py).
        assert surface.commands.count == EXPECTED_COMMAND_COUNT
        assert surface.skills.count == EXPECTED_SKILL_COUNT
        assert surface.agents.count >= EXPECTED_AGENT_COUNT_MIN
        assert surface.workflows.count == 1
        assert surface.hook_entries.count == EXPECTED_HOOK_ENTRY_COUNT
        assert surface.hook_helpers.count == EXPECTED_HOOK_HELPER_COUNT
        # Name-presence: the two formerly-omitted files must be present.
        assert "subagent_stop.py" in surface.hook_entries.paths
        assert "_denial_reasons.py" in surface.hook_helpers.paths

    def test_inventory_serializes_to_dict(self):
        surface = get_packaged_surface()
        d = surface.as_dict()
        for key in (
            "commands", "skills", "agents",
            "workflows", "hook_entries", "hook_helpers",
        ):
            assert key in d
            assert "count" in d[key]
            assert "paths" in d[key]
            assert isinstance(d[key]["paths"], list)


# ---------------------------------------------------------------------------
# Drift — root .claude/ mirror must match the package SoT byte-for-byte
# ---------------------------------------------------------------------------


def _normalize(content: bytes) -> bytes:
    """Normalize line endings only; do not normalize content differences."""
    return content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


class TestRootMirrorParity:
    """Root .claude/ is Espalier's self-host deployment AND the single source of
    truth for the agent/command/skill triplet; examples/dogfooding/.claude/ and
    espalier/assets/claude/ are GENERATED from it by scripts/sync_claude_mirrors.py.

    TP-31: agents/commands/skills moved from espalier/assets/claude/ to
    examples/dogfooding/.claude/. The deploy loop was removed; init no longer
    deploys these subdirs to user repos. The byte-equality asserted here is
    symmetric, so this test pins the trees together regardless of direction; the
    SoT direction (edit .claude/, regenerate the mirrors) lives in the generator
    and is pinned by TestClaudeMirrorGenerator.
    """

    @pytest.mark.parametrize("subdir", ["agents", "commands", "skills"])
    def test_root_claude_mirrors_dogfooding(self, subdir):
        dogfooding_dir = REPO_ROOT / "examples" / "dogfooding" / ".claude" / subdir
        root_dir = REPO_ROOT / ".claude" / subdir
        if not dogfooding_dir.is_dir():
            pytest.skip(f"examples/dogfooding/.claude/{subdir}/ absent")
        assert root_dir.is_dir(), f"root .claude/{subdir}/ missing"

        df_files = sorted(p for p in dogfooding_dir.rglob("*") if p.is_file())
        df_rels = {p.relative_to(dogfooding_dir) for p in df_files}

        root_files = sorted(p for p in root_dir.rglob("*") if p.is_file())
        root_rels = {p.relative_to(root_dir) for p in root_files}

        missing = df_rels - root_rels
        extra = root_rels - df_rels
        assert not missing, (
            f"root .claude/{subdir}/ missing files in dogfooding reference: "
            f"{sorted(str(p) for p in missing)}"
        )
        assert not extra, (
            f"root .claude/{subdir}/ has files not in its generated dogfooding "
            f"mirror: {sorted(str(p) for p in extra)} — .claude/ is the SoT; run "
            f"`python scripts/sync_claude_mirrors.py` to regenerate the mirrors"
        )

        for rel in sorted(df_rels):
            df_bytes = _normalize((dogfooding_dir / rel).read_bytes())
            root_bytes = _normalize((root_dir / rel).read_bytes())
            assert df_bytes == root_bytes, (
                f".claude/{subdir}/{rel} differs from its generated dogfooding "
                f"mirror -- .claude/ is the SoT; run "
                f"`python scripts/sync_claude_mirrors.py` to regenerate the mirrors"
            )

    def test_root_workflow_mirrors_package(self):
        package_node = github_workflow_asset("harness-guard.yml")
        root_path = REPO_ROOT / ".github" / "workflows" / "harness-guard.yml"
        assert root_path.is_file(), "root .github/workflows/harness-guard.yml missing"
        pkg_bytes = _normalize(package_node.read_bytes())
        root_bytes = _normalize(root_path.read_bytes())
        assert pkg_bytes == root_bytes, (
            "harness-guard.yml differs from package SoT — sync "
            "espalier/assets/github/workflows/harness-guard.yml → "
            ".github/workflows/harness-guard.yml"
        )


class TestAssetClaudeMirrorParity:
    """TP-151 G-4: the wheel DEPLOY SOURCE
    ``espalier/assets/claude/{agents,commands,skills}`` (what adopters receive
    via ``get_packaged_surface`` / ``cli.deploy_harness``) must match
    ``examples/dogfooding/.claude/`` byte-for-byte.

    This is the THIRD leg of the three-way invariant. ``TestRootMirrorParity``
    pins the self-host root ``.claude/`` <-> dogfooding leg; pre-TP-151 nothing
    pinned the asset-body <-> dogfooding leg, so an asset-file edit that skipped
    the dogfooding reference would ship to adopters while the self-host root
    copy stayed correct, with no test catching the divergence.
    """

    @pytest.mark.parametrize("subdir", ["agents", "commands", "skills"])
    def test_asset_claude_mirrors_dogfooding(self, subdir):
        dogfooding_dir = REPO_ROOT / "examples" / "dogfooding" / ".claude" / subdir
        asset_dir = REPO_ROOT / "espalier" / "assets" / "claude" / subdir
        if not dogfooding_dir.is_dir():
            pytest.skip(f"examples/dogfooding/.claude/{subdir}/ absent")
        assert asset_dir.is_dir(), f"espalier/assets/claude/{subdir}/ missing"

        df_files = sorted(p for p in dogfooding_dir.rglob("*") if p.is_file())
        df_rels = {p.relative_to(dogfooding_dir) for p in df_files}
        asset_files = sorted(p for p in asset_dir.rglob("*") if p.is_file())
        asset_rels = {p.relative_to(asset_dir) for p in asset_files}

        missing = df_rels - asset_rels
        extra = asset_rels - df_rels
        assert not missing, (
            f"espalier/assets/claude/{subdir}/ missing files in dogfooding "
            f"reference: {sorted(str(p) for p in missing)}"
        )
        assert not extra, (
            f"espalier/assets/claude/{subdir}/ has files not in the generated "
            f"set: {sorted(str(p) for p in extra)} — .claude/ is the SoT; run "
            f"`python scripts/sync_claude_mirrors.py` to regenerate the mirrors"
        )
        for rel in sorted(df_rels):
            df_bytes = _normalize((dogfooding_dir / rel).read_bytes())
            asset_bytes = _normalize((asset_dir / rel).read_bytes())
            assert df_bytes == asset_bytes, (
                f"espalier/assets/claude/{subdir}/{rel} differs from the .claude/ "
                f"SoT -- run `python scripts/sync_claude_mirrors.py` to "
                f"regenerate the mirrors"
            )


class TestClaudeMirrorGenerator:
    """The .claude triplet is GENERATED from the live .claude/ SoT by
    scripts/sync_claude_mirrors.py (the .claude analog of sync_vendor_cc.py).
    Byte-parity alone (TestRootMirrorParity / TestAssetClaudeMirrorParity) only
    proves the trees match each other -- it cannot catch a buggy or empty
    generator. This pins that the committed mirrors are EXACTLY what the
    generator produces from the SoT, and that it covers all three asset classes.
    """

    @staticmethod
    def _load_generator():
        import importlib.util

        path = REPO_ROOT / "scripts" / "sync_claude_mirrors.py"
        spec = importlib.util.spec_from_file_location("sync_claude_mirrors", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_mirrors_are_in_sync_with_sot(self):
        """Running the generator is a no-op: every mirror already equals the
        .claude/ SoT (no stale, no orphans). If this reds, the SoT and its
        generated mirrors drifted."""
        gen = self._load_generator()
        drift = {m: r for m, r in gen.plan().items() if r["stale"] or r["orphans"]}
        assert not drift, (
            "generated .claude mirror(s) drifted from the .claude/ SoT -- run "
            f"`python scripts/sync_claude_mirrors.py`. Drift: {drift!r}"
        )

    def test_generator_covers_all_three_asset_classes(self):
        """Guard the generator's scope: dropping a class from SUBDIRS would
        silently stop syncing it while the byte-parity tests still pass on the
        classes that remain."""
        gen = self._load_generator()
        assert set(gen.SUBDIRS) == {"agents", "commands", "skills"}
        src = gen._files(gen.SRC)
        for sub in ("agents", "commands", "skills"):
            assert any(rel.startswith(f"{sub}/") for rel in src), (
                f"generator SoT enumeration found no {sub}/ files -- "
                f"scope regression in scripts/sync_claude_mirrors.py"
            )

    def test_asset_router_documents_the_generator(self):
        """The espalier/assets/ folder-router README is auto-injected as the
        'Read first' guidance for editing that tree, but lives OUTSIDE the
        synced subdirs so no parity test witnesses it. Pin that it points at
        the generator (and not the pre-SoT 'edits land HERE first' inversion)
        so the router can't silently drift from the contract again."""
        router = (REPO_ROOT / "espalier" / "assets" / "CLAUDE.md").read_text(
            encoding="utf-8"
        )
        assert "sync_claude_mirrors.py" in router, (
            "espalier/assets/CLAUDE.md must point editors at the .claude SoT "
            "generator (scripts/sync_claude_mirrors.py)"
        )
        assert "land HERE first" not in router, (
            "espalier/assets/CLAUDE.md still teaches the pre-SoT inverted "
            "edit direction"
        )


# ---------------------------------------------------------------------------
# AssetNotFound — clear error path
# ---------------------------------------------------------------------------


class TestAssetNotFound:
    def test_missing_workflow_raises(self):
        with pytest.raises(AssetNotFound, match="not found"):
            github_workflow_asset("does-not-exist.yml")

    def test_missing_subtree_raises(self):
        with pytest.raises(AssetNotFound, match="not found"):
            iter_claude_asset_files("does-not-exist")

    def test_assets_root_resolves(self):
        # Sanity: assets_root() materializes to a directory in editable installs.
        with as_file(assets_root()) as p:
            assert p.is_dir()


class TestPackagedAgentNames:
    """`asset_inventory.packaged_agent_names` (DEF-766, 2026-09-12) is the one
    set doctor, the surface gate and init's summary tell a recommendation from
    a deploy by. Its two normalisations assume a flat `.md` leaf per agent;
    the assumption is pinned here so a nested or non-.md asset reds before it
    mangles a path."""

    def test_every_packaged_agent_path_is_a_flat_md_leaf(self):
        paths = get_packaged_surface().agents.paths
        assert paths, "no packaged agents; the asset tree did not ship"
        assert all("/" not in p and "\\" not in p and p.endswith(".md") for p in paths), paths

    def test_the_names_are_the_leaves_without_their_suffix(self):
        names = packaged_agent_names()
        assert names == frozenset(p[:-3] for p in get_packaged_surface().agents.paths)
        assert "code-reviewer" in names, sorted(names)
