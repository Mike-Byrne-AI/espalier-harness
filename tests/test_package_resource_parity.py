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

import ast
import re
from importlib.resources import as_file
from pathlib import Path

import pytest

from espalier._safe_walk import visible
from espalier.asset_inventory import packaged_agent_names
from espalier.assets import (
    AssetNotFound,
    assets_root,
    github_workflow_asset,
    iter_claude_asset_files,
)
from espalier.asset_inventory import get_packaged_surface
from espalier import surface_contract
from tests._surface_expected import (
    EXPECTED_AGENT_COUNT_MIN,
    EXPECTED_COMMAND_COUNT,
    EXPECTED_HOOK_ENTRY_COUNT,
    EXPECTED_HOOK_HELPER_COUNT,
    EXPECTED_SKILL_COUNT,
    EXPECTED_WORKFLOW_COUNT,
)

# The parametrize lists below read the one owner of the kinds; a kind added there is
# a kind these parity tests cover with no edit here. The SUBDIRS pin further down is
# the deliberate exception (a literal, so a kind dropped from the sync is caught).
CLAUDE_KINDS = list(surface_contract.CLAUDE_SURFACE_KINDS)

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
        assert surface.workflows.count == EXPECTED_WORKFLOW_COUNT
        assert surface.github_workflows.count == 1
        assert surface.hook_entries.count == EXPECTED_HOOK_ENTRY_COUNT
        assert surface.hook_helpers.count == EXPECTED_HOOK_HELPER_COUNT
        # Name-presence: the two formerly-omitted files must be present.
        assert "subagent_stop.py" in surface.hook_entries.paths
        assert "_denial_reasons.py" in surface.hook_helpers.paths

    def test_inventory_serializes_to_dict(self):
        surface = get_packaged_surface()
        d = surface.as_dict()
        for key in (
            "commands", "skills", "agents", "workflows",
            "github_workflows", "hook_entries", "hook_helpers",
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
    truth for the agent/command/skill/workflow set; examples/dogfooding/.claude/ and
    espalier/assets/claude/ are GENERATED from it by scripts/sync_claude_mirrors.py.

    TP-31: agents/commands/skills moved from espalier/assets/claude/ to
    examples/dogfooding/.claude/. The deploy loop was removed; init no longer
    deploys these subdirs to user repos. The byte-equality asserted here is
    symmetric, so this test pins the trees together regardless of direction; the
    SoT direction (edit .claude/, regenerate the mirrors) lives in the generator
    and is pinned by TestClaudeMirrorGenerator.
    """

    @pytest.mark.parametrize("subdir", CLAUDE_KINDS)
    def test_root_claude_mirrors_dogfooding(self, subdir):
        dogfooding_dir = REPO_ROOT / "examples" / "dogfooding" / ".claude" / subdir
        root_dir = REPO_ROOT / ".claude" / subdir
        if not dogfooding_dir.is_dir():
            pytest.skip(f"examples/dogfooding/.claude/{subdir}/ absent")
        assert root_dir.is_dir(), f"root .claude/{subdir}/ missing"

        df_files = [p for p in visible(dogfooding_dir.rglob("*"), dogfooding_dir) if p.is_file()]
        df_rels = {p.relative_to(dogfooding_dir) for p in df_files}
        assert df_rels, f"examples/dogfooding/.claude/{subdir}/ enumerated as empty: a wrong `visible` base drops everything quietly"

        root_files = [p for p in visible(root_dir.rglob("*"), root_dir) if p.is_file()]
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
    ``espalier/assets/claude/{agents,commands,skills,workflows}`` (what adopters receive
    via ``get_packaged_surface`` / ``cli.deploy_harness``) must match
    ``examples/dogfooding/.claude/`` byte-for-byte.

    This is the THIRD leg of the three-way invariant. ``TestRootMirrorParity``
    pins the self-host root ``.claude/`` <-> dogfooding leg; pre-TP-151 nothing
    pinned the asset-body <-> dogfooding leg, so an asset-file edit that skipped
    the dogfooding reference would ship to adopters while the self-host root
    copy stayed correct, with no test catching the divergence.
    """

    @pytest.mark.parametrize("subdir", CLAUDE_KINDS)
    def test_asset_claude_mirrors_dogfooding(self, subdir):
        dogfooding_dir = REPO_ROOT / "examples" / "dogfooding" / ".claude" / subdir
        asset_dir = REPO_ROOT / "espalier" / "assets" / "claude" / subdir
        if not dogfooding_dir.is_dir():
            pytest.skip(f"examples/dogfooding/.claude/{subdir}/ absent")
        assert asset_dir.is_dir(), f"espalier/assets/claude/{subdir}/ missing"

        df_files = [p for p in visible(dogfooding_dir.rglob("*"), dogfooding_dir) if p.is_file()]
        df_rels = {p.relative_to(dogfooding_dir) for p in df_files}
        assert df_rels, f"examples/dogfooding/.claude/{subdir}/ enumerated as empty: a wrong `visible` base drops everything quietly"
        asset_files = [p for p in visible(asset_dir.rglob("*"), asset_dir) if p.is_file()]
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
    """The .claude asset set is GENERATED from the live .claude/ SoT by
    scripts/sync_claude_mirrors.py (the .claude analog of sync_vendor_cc.py).
    Byte-parity alone (TestRootMirrorParity / TestAssetClaudeMirrorParity) only
    proves the trees match each other -- it cannot catch a buggy or empty
    generator. This pins that the committed mirrors are EXACTLY what the
    generator produces from the SoT, and that it covers every asset class.
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

    def test_generator_covers_every_asset_class(self):
        """Guard the generator's scope. SUBDIRS now reads the owner, so this pin
        cannot catch a kind dropped from the sync alone; what it does is force a
        review on any change to the kind set (four names, literal on purpose),
        and the enumeration below proves the SoT actually holds each kind."""
        gen = self._load_generator()
        assert set(gen.SUBDIRS) == {"agents", "commands", "skills", "workflows"}
        src = gen._files(gen.SRC)
        for sub in ("agents", "commands", "skills", "workflows"):
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


# ---------------------------------------------------------------------------
# §C28 (DEF-479 / DEF-489, 2026-10-06): a hidden name is never a member of a
# .claude kind, at EVERY enumerator -- and the enumerators are found, not listed.
# ---------------------------------------------------------------------------

#: The source roots an enumerator of a deployed ``.claude/`` kind can live in.
#: The two byte-mirrors of other roots (``espalier/_vendor/cc/`` of ``tools/cc/``,
#: ``espalier/assets/`` of ``.claude/``) are governed by their source's rules and
#: would double every site.
_KIND_ENUMERATION_ROOTS = ("tests", "scripts", "tools/cc", "espalier")
_KIND_ENUMERATION_SKIP = ("espalier/_vendor/", "espalier/assets/")
#: Listing METHODS (`x.glob(p)`, `x.iterdir()`, `os.walk(x)`'s attribute form) and
#: listing FUNCTIONS called by name (`safe_rglob(x, p)`, `glob.iglob(x)`): the
#: filesystem-contracts gate pushes a recursive kind walk under `espalier/` or
#: `tools/` toward `safe_rglob`, so a walk that read only methods went silent on
#: exactly the site that gate produces (the failure-mode review, 2026-10-06).
_LISTING_METHODS = frozenset({"glob", "rglob", "iterdir", "listdir", "scandir", "walk"})
_LISTING_FUNCTIONS = frozenset({"safe_rglob", "_safe_rglob", "safe_glob", "iglob", "glob"})
#: Under tests/, a receiver is in the population when it reaches the live tree
#: or a fixture copied from it; a `tmp_path` tree nothing but the test writes
#: never meets a sidecar. `__file__` covers every `X = Path(__file__)...` root
#: constant whatever its name; the two fixture names are conftest's copies of
#: the live `.claude/` (its `_ignore` drops no dot-name, by design: the fixture
#: mirrors the developer's tree and the ENUMERATORS filter).
_LIVE_TREE_TOKENS = ("REPO_ROOT", "__file__", "initialized_repo_root", "self_host_tree_copy")
_KIND_MENTION = re.compile(r"\bclaude\b|agents|commands|skills|workflows|SKILL\.md", re.I)
#: ``.github/workflows`` shares a word with the ``.claude/workflows`` kind and a
#: bench count globs JSON: neither is a deployed body.
_NOT_A_KIND = re.compile(r"\.github|\.ya?ml\b|\.json\b")
#: The two-line form counts only on the entry's OWN name or stem: a dot-check on
#: `p.parent.name` reads as routed by text and keeps every sidecar.
_HIDDEN_FILTER = re.compile(
    r"\bvisible\(|\b_visible\(|is_hidden_name\(|\.(?:name|stem)\.startswith\(\"\.\"\)|\.(?:name|stem)\.startswith\('\.'\)"
)


_PROBE_PARENTS: dict[ast.AST, ast.AST] = {}


def _is_probe_with(node: ast.Call) -> bool:
    item = _PROBE_PARENTS.get(node)
    stmt = _PROBE_PARENTS.get(item) if isinstance(item, ast.withitem) else None
    return (
        isinstance(stmt, ast.With)
        and len(stmt.body) == 1
        and isinstance(stmt.body[0], ast.Pass)
    )


def _listing_call(node: ast.AST) -> tuple[ast.AST, ast.AST | None] | None:
    """``(receiver, pattern)`` when ``node`` is a directory listing, else None:
    the object of a listing method, or the first argument of a listing
    function called by name (``safe_rglob(root, pattern)``, ``os.walk(root)``,
    ``glob.iglob(spec)``)."""
    if not isinstance(node, ast.Call):
        return None
    f = node.func
    # `with os.scandir(d): pass` is a readability probe (surface_contract's
    # settings-dir check): it opens the directory and lists nothing.
    if isinstance(f, ast.Attribute) and f.attr == "scandir" and _is_probe_with(node):
        return None
    # `next(d.iterdir())` asks "any entry at all?" (cleanup's empty-directory
    # check): a `.DS_Store` rightly keeps the directory non-empty, since the
    # `rmdir` that follows would fail on it. One entry is not an enumeration.
    parent = _PROBE_PARENTS.get(node)
    if (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name)
            and parent.func.id == "next" and parent.args and parent.args[0] is node):
        return None
    if isinstance(f, ast.Attribute) and f.attr in _LISTING_METHODS:
        if isinstance(f.value, ast.Name) and f.value.id in {"os", "glob"} and node.args:
            return node.args[0], (node.args[1] if len(node.args) > 1 else None)
        return f.value, (node.args[0] if node.args else None)
    if isinstance(f, ast.Name) and f.id in _LISTING_FUNCTIONS and node.args:
        return node.args[0], (node.args[1] if len(node.args) > 1 else None)
    return None


def _resolved_receiver_source(
    recv: ast.AST, pattern: ast.AST | None, owner: ast.AST, module: ast.Module, lines: list[str],
) -> tuple[str, str]:
    """``(own, hops)``: the receiver's and pattern's own source, and the source
    of every assignment the receiver's names resolve through, up to three
    hops (``src_dir`` -> ``asset_root / kind`` -> ``harness_root / "espalier"
    / "assets" / "claude"``), bounded so a self-reference cannot loop. The
    module scope is its TOP-LEVEL statements only: a walk of the whole module
    would read another function's local of the same name (a ``root = tmp_path
    / "agents"`` in one test flagged the pin's own walk). A receiver that is a
    parameter (the engine's ``_list_dir_relative``, the sync script's
    ``_files``) resolves to nothing here; those two carry their own two-arm
    tests instead."""
    def seg(n: ast.AST) -> str:
        return "\n".join(lines[n.lineno - 1: n.end_lineno])
    own = seg(recv) + ("\n" + seg(pattern) if pattern is not None else "")
    candidates = list(module.body) if owner is module else list(ast.walk(owner)) + list(module.body)
    assigns = [n for n in candidates if isinstance(n, ast.Assign)]
    # A loop target resolves to the loop's iterable: `for d in ["cc",
    # ".claude"]: dd = root / d` names the kind in the list, not in an
    # assignment (the deployed reflect twin's shape, missed on 2026-10-06).
    loops = [n for n in candidates if isinstance(n, ast.For)]
    hops: list[str] = []
    pending = {n.id for n in ast.walk(recv) if isinstance(n, ast.Name)}
    seen: set[str] = set()
    for _hop in range(3):
        if not pending:
            break
        seen |= pending
        found: set[str] = set()
        for n in assigns:
            if any(isinstance(t, ast.Name) and t.id in pending for t in n.targets):
                hops.append(seg(n.value))
                found |= {m.id for m in ast.walk(n.value) if isinstance(m, ast.Name)}
        for n in loops:
            if isinstance(n.target, ast.Name) and n.target.id in pending:
                hops.append(seg(n.iter))
                found |= {m.id for m in ast.walk(n.iter) if isinstance(m, ast.Name)}
        pending = found - seen
    return own, "\n".join(hops)


def _claude_kind_listing_sites() -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """Every directory-listing call under the source roots whose receiver (or
    the receiver's own assignment, or the pattern) names a ``.claude`` kind,
    split into (routed, unrouted): routed when the call sits inside
    ``visible(...)`` / ``is_hidden_name(...)`` or inside a comprehension that
    filters on ``startswith(".")`` (the deployed ``tools/cc`` tree cannot
    import the engine helper and carries the two-line form). A derived
    population: a new enumerator anywhere under these roots is found by this
    walk, never by a list someone remembered to extend (docs/SHARP_EDGES.md,
    the hand-maintained enumeration entry;
    memory/completeness-gate-must-discover-its-population.md). The receiver is
    read as source because the kind is usually a variable (``agents_dir``,
    ``AGENTS_DIR``) the AST alone cannot tell from any other directory.
    """
    routed: list[tuple[str, int]] = []
    unrouted: list[tuple[str, int]] = []
    for root in _KIND_ENUMERATION_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel.startswith(_KIND_ENUMERATION_SKIP):
                continue
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            tree = ast.parse(text)
            parents: dict[ast.AST, ast.AST] = {}
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    parents[child] = node
            _PROBE_PARENTS.clear()
            _PROBE_PARENTS.update(parents)
            for node in ast.walk(tree):
                listing = _listing_call(node)
                if listing is None:
                    continue
                recv, pattern = listing
                owner: ast.AST = node
                while not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                    owner = parents[owner]
                own, hops = _resolved_receiver_source(recv, pattern, owner, tree, lines)
                receiver_src = own + "\n" + hops
                # `.github`/yml/json are judged on the receiver's OWN segment: a
                # same-named sibling assignment (`wf = .github/...` then `wf =
                # .claude/workflows`) must not drop a real kind listing.
                if not _KIND_MENTION.search(receiver_src) or _NOT_A_KIND.search(own):
                    continue
                if rel.startswith("tests/") and not any(t in receiver_src for t in _LIVE_TREE_TOKENS):
                    continue
                routed_here = False
                anc = parents.get(node)
                while anc is not None and anc is not owner:
                    if isinstance(anc, ast.Call) and isinstance(anc.func, ast.Name) \
                            and anc.func.id in {"visible", "_visible", "is_hidden_name"} and anc is not node:
                        routed_here = True
                        break
                    if isinstance(anc, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
                        seg = "\n".join(lines[anc.lineno - 1: anc.end_lineno])
                        if _HIDDEN_FILTER.search(seg):
                            routed_here = True
                            break
                    anc = parents.get(anc)
                (routed if routed_here else unrouted).append((rel, node.lineno))
    return routed, unrouted


class TestHiddenNamesStayOutOfEveryClaudeKindEnumeration:
    """§C28: the predicate has one home (``espalier._safe_walk.visible``) and
    every enumerator of a ``.claude`` kind under the four source roots goes
    through it -- or, in the deployed ``tools/cc`` tree that cannot import the
    engine, carries the ``startswith(".")`` form. Measured 2026-10-06 on a
    clone carrying one ``._planted.md`` and one ``.DS_Store`` under the agents
    and commands directories of the root and both mirrors: 16 rows red across
    five modules, every one reporting a wrong count or a parity gap and none
    naming the sidecar (DEF-479, DEF-489); the engine's own
    ``discover_installed_agents`` counted it too, so doctor and the uninstall
    inventory on a macOS adopter's tree would have as well.
    """

    def test_every_kind_enumerator_is_routed_through_the_hidden_name_filter(self):
        routed, unrouted = _claude_kind_listing_sites()
        assert routed, "the walk found no routed site: the population derivation is broken"
        assert not unrouted, (
            "directory listings over a .claude kind that a sidecar can enter "
            f"unfiltered: {unrouted}. Wrap the listing in espalier._safe_walk.visible(paths, base) "
            "(tools/cc: filter on `not p.name.startswith(\".\")`)."
        )

    def test_the_walk_sees_the_receiver_named_sites(self):
        """A floor against a vacuous walk: three receiver-named sites that
        exist today must be in the population, whatever else the walk finds.
        The two parameter-driven sites the walk cannot name
        (``surface_contract._list_dir_relative``, ``sync_claude_mirrors._files``)
        are pinned by their own two-arm tests, not by this walk."""
        routed, unrouted = _claude_kind_listing_sites()
        files = {rel for rel, _ in routed + unrouted}
        assert {"tests/test_count_claims.py", "tools/cc/session_resume.py", "espalier/pre_release.py"} <= files
        # 80 sites at close on 2026-10-06; a narrowing of the walk that drops
        # most of them must red here, not pass on the three names above.
        assert len(routed) + len(unrouted) >= 70, len(routed) + len(unrouted)


class TestTheSyncEnumeratorSeesWhatTheParityRowsSee:
    """DEF-489's second half (§C28, 2026-10-06): the parity rows and the sync
    script's ``_files`` must enumerate the same set, so the hidden-name
    predicate sits on both sides. Both arms on the enumerator: the planted
    body is listed, the planted sidecar, sidecar directory and ``.DS_Store``
    are not (docs/SHARP_EDGES.md, the presence-not-absence parity entry).
    Before the filter the row's own remedy copied the sidecar into both
    mirrors."""

    @staticmethod
    def _load():
        import importlib.util
        path = REPO_ROOT / "scripts" / "sync_claude_mirrors.py"
        spec = importlib.util.spec_from_file_location("sync_claude_mirrors_hidden", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        return mod

    def test_a_planted_sidecar_is_absent_and_the_planted_body_is_present(self, tmp_path):
        gen = self._load()
        root = tmp_path / ".claude"
        (root / "agents").mkdir(parents=True)
        (root / "agents" / "x.md").write_text("real\n", encoding="utf-8")
        (root / "agents" / "._x.md").write_text("AppleDouble sidecar\n", encoding="utf-8")
        (root / "agents" / ".DS_Store").write_bytes(b"\x00\x00")
        (root / "skills" / "real").mkdir(parents=True)
        (root / "skills" / "real" / "SKILL.md").write_text("real\n", encoding="utf-8")
        (root / "skills" / "._real").mkdir()
        (root / "skills" / "._real" / "SKILL.md").write_text("sidecar directory\n", encoding="utf-8")
        assert gen._files(root) == {"agents/x.md", "skills/real/SKILL.md"}


class TestThePackagedWalkerIgnoresHiddenNames:
    """§C28's packaged sibling (2026-10-06): ``espalier.assets._collect_files``
    is the one walk under every packaged-surface reader and under ``init``'s
    deploy, so a sidecar beside a packaged body must stop here. Driven on a
    ``Path`` tree, which satisfies the traversable protocol the walker reads
    (``is_file``, ``iterdir``, ``name``). Both arms: the planted body is
    listed, the sidecar, sidecar directory and ``.DS_Store`` are not."""

    def test_a_planted_sidecar_is_absent_and_the_planted_body_is_present(self, tmp_path):
        from espalier.assets import _collect_files
        root = tmp_path / "agents"
        root.mkdir()
        (root / "x.md").write_text("real\n", encoding="utf-8")
        (root / "._x.md").write_text("AppleDouble sidecar\n", encoding="utf-8")
        (root / ".DS_Store").write_bytes(b"\x00\x00")
        (root / "._nested").mkdir()
        (root / "._nested" / "y.md").write_text("under a sidecar directory\n", encoding="utf-8")
        (root / "nested").mkdir()
        (root / "nested" / "z.md").write_text("real, nested\n", encoding="utf-8")
        out: list = []
        _collect_files(root, out)
        assert [p.relative_to(root).as_posix() for p in out] == ["nested/z.md", "x.md"]
