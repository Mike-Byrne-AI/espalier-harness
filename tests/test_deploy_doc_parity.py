"""Deploy/source doc-reference parity contract (TP-129).

Pins: every ``docs/<path>.md`` reference emitted from user-facing hook
output or the generated ``CLAUDE.md`` resolves to a doc that ships with
``espalier init`` -- or is allowlisted with a reason.

Prevents: the TP-129 B1 / TP-120a class -- hook hints and orientation
blocks pointing at ``docs/SHARP_EDGES.md`` (or another harness-internal
doc) that the adopter never receives. The split between source-tree
docs (this repo) and deploy-tree docs (what ``cmd_init`` writes) is
silently wrong by default; without this contract a new reference can
slip into a denial reason and reach the adopter as a phantom-file
advisory.

Failure mode: an operator adds ``"see docs/NEWDOC.md"`` to a
``_denial_reasons`` template, ships, and the adopter sees the deny
message but cannot read the named doc. The contract catches this at
pytest time.

Scope (narrow on purpose; sister-shape to TP-127's planned coherence
registry):
- Hook source string literals (AST-extracted from ``tools/cc/hooks/*.py``).
- Generated ``CLAUDE.md`` body (the output of
  ``espalier.cli._build_claude_md`` on a synthetic fingerprint).

Common-tier asset bodies are out of scope here -- they typically guard
references with ``[ -f docs/X.md ] && cat docs/X.md`` so the references
are advisory rather than promises. Asset bodies are covered by 129-G
(branding scrub) on a different axis.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from espalier.managed_inventory import get_managed_public_files, get_seed_docs

pytestmark = [pytest.mark.contract]


REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
ASSETS_DOCS_DIR = REPO_ROOT / "espalier" / "assets" / "docs"

# ── deploy manifest ───────────────────────────────────────────────────
#
# Files under ``docs/`` that ``espalier init`` writes into an adopter
# repo. The list is anchored to ``espalier/cli.py`` deploy logic, NOT
# to filesystem discovery -- a stale asset file should not silently
# expand this set.
#
# Sourced from the init seed SoT (``managed_inventory.get_seed_docs``) so this
# set auto-tracks the deploy manifest rather than duplicating it. A doc added to
# the seed tuple is deployed; its former allowlist entry (if any) must drop out
# (``test_allowlist_and_deployed_sets_are_disjoint``).

_DEPLOYED_DOCS: frozenset[str] = frozenset(get_seed_docs())

# Paths intentionally referenced from hook source or CLAUDE.md but NOT
# deployed by ``cmd_init``. Each entry pairs a path with a *reason* so
# future readers know why the reference is allowed to land in adopter-
# visible output.
_ALLOWED_UNDEPLOYED_DOC_REFS: dict[str, str] = {
    # NOTE: docs/SHARP_EDGES.md and docs/CONVENTIONS.md were allowlisted here
    # until they became init-seeded (managed_inventory._SEED_DOC_REL_PATHS,
    # sourced from espalier/assets/seed/ via _SEED_ASSET_SOURCES). They are now
    # in _DEPLOYED_DOCS, so an entry here would red
    # ``test_allowlist_and_deployed_sets_are_disjoint``. Every reference that
    # was allowed-because-not-shipped now resolves for the adopter.
    # QUICKSTART named in _reinject.py's 165-A hook-count witness DATA (TP-165).
    # Self-host-only: the witness fires when wiring a tools/cc/hooks script, a
    # harness-internal activity adopters never perform.
    "docs/QUICKSTART.md": (
        "self-host quickstart; named in _reinject.py 165-A hook-count witness "
        "(harness-dev hook-wiring aid, not adopter-deployed)"
    ),
    # Local-only session-log archive (autoprune writes it). Hook
    # message about archiving is operator-facing; the file gets
    # created on first prune.
    "docs/session-archive.md": (
        "local-only archive; created by autoprune at first overflow"
    ),
    # Generic placeholder name occasionally used in asset-body
    # examples (e.g., "docs/ARCHITECTURE.md or your project's"). Not
    # a real Espalier surface; adopters supply their own if any.
    "docs/ARCHITECTURE.md": (
        "generic-placeholder example name; not an Espalier doc"
    ),
    # RELEASE_CHECKLIST referenced in cli.py release-check error text.
    # Self-host-only; adopters do not run release-check.
    "docs/RELEASE_CHECKLIST.md": (
        "self-host release ritual; referenced in cli.py release-check "
        "error text"
    ),
    # Surface support matrix; self-host-only.
    "docs/SURFACE_SUPPORT_MATRIX.md": (
        "self-host surface ladder; cli.py default arg for scope-check"
    ),
    # The standing-principles index is rendered into the banner ONLY when
    # is_self_host_repo (_standing_principles_index is called behind the same
    # gate); the doc is a contributor-facing lessons catalog, never deployed to
    # adopters. The string literal is a self-host code path, not an instruction.
    "docs/STANDING_PRINCIPLES.md": (
        "self-host standing-principles index; contributor lessons catalog, never "
        "adopter-deployed. ⚠ This reason previously said 'gated on "
        "is_self_host_repo' and that was false: _iter_corpus gates the principles "
        "tier on sp.is_file(), deliberately NOT on repo identity, because an "
        "adopter who writes their own principles SHOULD get them back from /recall"
    ),
    "docs/STANDING_PRINCIPLES.aliases.md": (
        "machine-facing retrieval aliases for the principles tier (document "
        "expansion). Same gate and same reason as its parent: _load_principle_aliases "
        "returns {} when the file is absent, so an adopter without a sidecar loses "
        "expansion and nothing else -- a no-op, not a degradation"
    ),
}


# Matches ``docs/<path>.md`` and ``docs/<dir>/...<path>.md`` references.
# Excludes trailing punctuation (period, comma, paren, brace) so prose
# like ``...docs/X.md.`` extracts cleanly.
_DOC_REF_RE = re.compile(r"docs/[A-Za-z0-9_./-]+?\.md\b")


def _extract_doc_refs_from_string_literals(source: str) -> set[str]:
    """Walk the AST and return every ``docs/...md`` reference appearing
    in a string literal (Constant of type str)."""
    refs: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return refs
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            refs.update(_DOC_REF_RE.findall(node.value))
    return refs


def _extract_doc_refs_from_text(text: str) -> set[str]:
    """Plain-text regex pass for non-Python sources (the generated
    ``CLAUDE.md`` body, which is itself a Python f-string return value
    but is consumed as text by the adopter)."""
    return set(_DOC_REF_RE.findall(text))


def _hook_string_literal_refs() -> dict[str, set[str]]:
    """Return ``{filename: {ref, ...}}`` for every ``tools/cc/hooks/*.py``."""
    out: dict[str, set[str]] = {}
    for hook in sorted(HOOKS_DIR.glob("*.py")):
        if hook.name.startswith("_"):
            # Helpers like _hook_utils.py / _denial_reasons.py: still
            # in scope -- their string literals reach hook output via
            # the templates imported into the entry hooks.
            pass
        source = hook.read_text(encoding="utf-8")
        refs = _extract_doc_refs_from_string_literals(source)
        if refs:
            out[hook.name] = refs
    return out


def _generated_claude_md_refs() -> set[str]:
    """Render ``_build_claude_md`` with a synthetic fingerprint and
    extract its ``docs/...md`` references."""
    from espalier.cli import _build_claude_md
    from espalier.models import BuildPlan, RepoFingerprint

    fp = RepoFingerprint(
        repo_name="adopter-repo",
        repo_root=str(REPO_ROOT),
        languages=["python"],
        test_commands=["pytest -q"],
    )
    harness = BuildPlan(repo_name="adopter-repo", profiles=["general"])
    body = _build_claude_md(fp, harness)
    return _extract_doc_refs_from_text(body)


def _allowed_or_deployed(ref: str) -> bool:
    return ref in _DEPLOYED_DOCS or ref in _ALLOWED_UNDEPLOYED_DOC_REFS


class TestHookStringLiteralDocRefs:
    """Every ``docs/...md`` in a hook string literal must be deployed
    or carry an explicit allowlist reason."""

    def test_every_hook_doc_ref_is_deployed_or_allowlisted(self) -> None:
        all_refs = _hook_string_literal_refs()
        gaps: list[str] = []
        for hook_name, refs in sorted(all_refs.items()):
            for ref in sorted(refs):
                if not _allowed_or_deployed(ref):
                    gaps.append(f"{hook_name}: {ref}")
        assert not gaps, (
            "Hook string literal references docs that are neither "
            "deployed by cmd_init nor in _ALLOWED_UNDEPLOYED_DOC_REFS:\n"
            + "\n".join(f"  - {g}" for g in gaps)
            + "\n\nResolve by (a) adding the doc to the deploy manifest, "
            "(b) gating the reference on is_self_host_repo, or "
            "(c) adding an entry to _ALLOWED_UNDEPLOYED_DOC_REFS with "
            "a reason."
        )


class TestGeneratedClaudeMdDocRefs:
    """Every ``docs/...md`` in the generated ``CLAUDE.md`` body must be
    deployed or allowlisted. Catches the same class as the hook-string
    test but on the post-init operator-facing surface."""

    def test_every_claude_md_doc_ref_is_deployed_or_allowlisted(self) -> None:
        refs = _generated_claude_md_refs()
        gaps = sorted(r for r in refs if not _allowed_or_deployed(r))
        assert not gaps, (
            "Generated CLAUDE.md references docs that are neither "
            "deployed by cmd_init nor in _ALLOWED_UNDEPLOYED_DOC_REFS:\n"
            + "\n".join(f"  - {g}" for g in gaps)
        )


class TestAllowlistHygiene:
    """The allowlist itself must remain narrow -- every entry needs a
    reason string, and entries that become deployed should drop out."""

    def test_every_allowlist_entry_has_a_reason(self) -> None:
        empty = [k for k, v in _ALLOWED_UNDEPLOYED_DOC_REFS.items() if not v.strip()]
        assert not empty, (
            f"allowlist entries missing reason: {empty!r}"
        )

    def test_allowlist_and_deployed_sets_are_disjoint(self) -> None:
        overlap = sorted(set(_ALLOWED_UNDEPLOYED_DOC_REFS).intersection(_DEPLOYED_DOCS))
        assert not overlap, (
            f"deployed docs should not be in the allowlist: {overlap!r}; "
            "drop the allowlist entry once the deploy lands."
        )


class TestSourceAssetDocByteParity:
    """Every `docs/<x>.md` that has a mirror at
    `espalier/assets/docs/<x>.md` must be byte-equal to its mirror.
    The asset copy is what `pip install espalier-harness` ships;
    silent drift between source and asset means adopters see stale
    content while the source tree shows a fix.

    TP-135 closed the original instance of this drift class:
    `docs/TROUBLESHOOTING.md` and its asset mirror both carried the
    same `[plan_guard]` schema bug; fixing one without the other
    would have left wheel adopters with the broken example. This
    test pins the parity going forward.
    """

    def test_source_asset_docs_are_byte_equal(self) -> None:
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        source_docs_dir = repo_root / "docs"
        asset_docs_dir = repo_root / "espalier" / "assets" / "docs"
        if not asset_docs_dir.is_dir():
            return  # no asset docs to compare (early-stage repos)
        mismatches: list[str] = []
        for asset_path in sorted(asset_docs_dir.rglob("*.md")):
            rel = asset_path.relative_to(asset_docs_dir)
            source_path = source_docs_dir / rel
            if not source_path.is_file():
                mismatches.append(
                    f"asset {rel} has no source-tree counterpart at "
                    f"docs/{rel} (orphan asset or moved source file)"
                )
                continue
            if source_path.read_bytes() != asset_path.read_bytes():
                mismatches.append(
                    f"docs/{rel} differs from "
                    f"espalier/assets/docs/{rel} — single-side edit "
                    "ships stale content to wheel adopters"
                )
        assert not mismatches, (
            "Source/asset doc byte-parity drift:\n  "
            + "\n  ".join(mismatches)
        )

    def test_mirrored_covers_every_asset_doc(self) -> None:
        """TP-274 7-A: the sync script's ``_MIRRORED`` set must
        cover every asset doc the byte-parity test pins via rglob.

        ``_MIRRORED`` is DERIVED from the deploy inventory, not hand-kept -- see
        ``scripts/sync_asset_docs.py::_mirrored``, whose docstring opens "DERIVE
        the mirror set from the deploy inventory, don't hand-keep it." This
        docstring called it "hand-maintained" long after that stopped being true,
        which inverts the reader's model of what can go stale: a derived set
        cannot drift from the inventory, so the risk this test guards is the
        rglob and the inventory disagreeing, not someone forgetting a row.

        A doc under
        ``espalier/assets/docs/**`` whose source is NOT in ``_MIRRORED`` can never
        be propagated by ``python scripts/sync_asset_docs.py`` — editing the source
        then leaves the asset stale while ``test_source_asset_docs_are_byte_equal``
        reds (edit-then-sync gives a false 'synced'). RED before (``_MIRRORED``
        omitted ``docs/TROUBLESHOOTING.md`` + ``docs/sharp-edges/README.md``), GREEN
        after. Pins the sync list and the parity test to ONE rglob so they cannot
        drift apart (the 'one oracle' discipline)."""
        import importlib.util
        import sys

        asset_docs_dir = REPO_ROOT / "espalier" / "assets" / "docs"
        if not asset_docs_dir.is_dir():
            return
        spec = importlib.util.spec_from_file_location(
            "_tp274_sync_asset_docs", REPO_ROOT / "scripts" / "sync_asset_docs.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        mirrored = set(mod._MIRRORED)

        uncovered = [
            f"docs/{p.relative_to(asset_docs_dir).as_posix()}"
            for p in sorted(asset_docs_dir.rglob("*.md"))
            if f"docs/{p.relative_to(asset_docs_dir).as_posix()}" not in mirrored
        ]
        assert not uncovered, (
            "sync_asset_docs.py::_MIRRORED omits asset docs the byte-parity test "
            "pins (edit-then-sync would leave them stale):\n  " + "\n  ".join(uncovered)
        )

    def test_task_packs_asset_matches_source(self) -> None:
        # task-packs/CLAUDE.md mirrors to espalier/assets/task-packs/CLAUDE.md
        # but lives OUTSIDE assets/docs/**, so the rglob above never sees it.
        # Guard it explicitly (same drift class as the docs mirrors).
        asset = REPO_ROOT / "espalier" / "assets" / "task-packs" / "CLAUDE.md"
        source = REPO_ROOT / "task-packs" / "CLAUDE.md"
        assert asset.read_bytes() == source.read_bytes(), (
            "espalier/assets/task-packs/CLAUDE.md drifted from "
            "task-packs/CLAUDE.md — run scripts/sync_asset_docs.py"
        )


def _load_sync_asset_docs():
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "_tp274_sync_asset_docs_check", REPO_ROOT / "scripts" / "sync_asset_docs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestSyncAssetDocsCheck:
    """TP-274 8-A: surface_impact.py cites ``scripts/sync_asset_docs.py --check``
    as a byte-parity verify command, but pre-fix the script had no argparse — the
    cited 'check' silently OVERWROTE the asset from source and exited 0 (a phantom
    flag). ``--check`` must verify WITHOUT writing and exit nonzero on drift."""

    def test_check_detects_drift_without_mutating(self, monkeypatch, tmp_path) -> None:
        """RED before (main had no argv → TypeError; running it mutated + exited 0),
        GREEN after: --check reports drift (rc 1) and leaves the asset untouched."""
        mod = _load_sync_asset_docs()
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "X.md").write_text("source\n", encoding="utf-8")
        asset = tmp_path / "espalier" / "assets" / "docs"
        asset.mkdir(parents=True)
        (asset / "X.md").write_text("STALE\n", encoding="utf-8")
        before = (asset / "X.md").read_bytes()
        monkeypatch.setattr(mod, "_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_MIRRORED", ("docs/X.md",))

        assert mod.main(["--check"]) == 1, "--check did not report drift"
        assert (asset / "X.md").read_bytes() == before, "--check mutated the asset"

    def test_check_clean_returns_zero(self, monkeypatch, tmp_path) -> None:
        mod = _load_sync_asset_docs()
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "X.md").write_text("same\n", encoding="utf-8")
        asset = tmp_path / "espalier" / "assets" / "docs"
        asset.mkdir(parents=True)
        (asset / "X.md").write_text("same\n", encoding="utf-8")
        monkeypatch.setattr(mod, "_ROOT", tmp_path)
        monkeypatch.setattr(mod, "_MIRRORED", ("docs/X.md",))

        assert mod.main(["--check"]) == 0


# ── init-seeded doc link validity ─────────────────────────────────────
#
# TP-271a owed this in writing: "no systematic test proves seeded docs
# link only to init-deployed targets." It had to de-link HOOKS/WORKFLOW
# -> SHARP_EDGES by hand mid-execution and nothing pinned it afterwards.
# The narrower sibling of the fuse-tree link test: the fuse covers the
# WIDER fuse tree, this covers the NARROWER init seed set, which is what
# an adopter actually receives.

_SEED_ASSET_ROOT = REPO_ROOT / "espalier" / "assets"
_FENCE_RE = re.compile(r"^\s*```.*?^\s*```", re.MULTILINE | re.DOTALL)
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

# RETIRED, deliberately empty -- kept as a named seam rather than deleted so a
# future body-less seed has somewhere to be declared with a reason.
#
# Its premise expired. The stanza used to read "seeds `init` writes from a
# generated adopter STUB rather than copying an asset body, so there is nothing
# under espalier/assets/ to scan", and excluded `docs/CONVENTIONS.md` and
# `docs/SHARP_EDGES.md` on that basis. Both DO have asset bodies --
# `espalier/assets/seed/{CONVENTIONS,SHARP_EDGES}.md` -- reached through
# `managed_inventory.get_seed_asset_source`. The exclusion survived only
# because the reader below resolved `_SEED_ASSET_ROOT / dest` (the identity
# derivation) instead of the accessor, so the bodies looked absent. Reading
# through the accessor pulls both stubs into the link scan, which is the whole
# point: they are the two seeds whose destination path collides with a far
# larger self-host document.
_SEEDS_WITHOUT_ASSET_BODY: frozenset[str] = frozenset()


def _seed_body_path(dest_rel: str) -> Path:
    """The asset body `init` actually copies for ``dest_rel``.

    Through ``get_seed_asset_source``, never ``_SEED_ASSET_ROOT / dest``. Of the
    20 seed docs, 18 are identity-mirrored and the two agree; for the two Tier-3
    stubs (``docs/CONVENTIONS.md``, ``docs/SHARP_EDGES.md``) they do not, and the
    identity form silently reported "no body" for exactly the two files whose
    bodies matter most. Counts are re-derivable -- ``len(_SEED_DOC_REL_PATHS)``
    and ``len(_mirrored())`` -- and an earlier "16 of the 17" here was both stale
    and self-inconsistent (17 minus 16 is one, while the sentence said two).
    """
    from espalier import managed_inventory

    return _SEED_ASSET_ROOT.joinpath(
        *managed_inventory.get_seed_asset_source(dest_rel).split("/")
    )


def _normalize_rel(dest: str, target: str) -> str:
    """Resolve ``target`` against ``dest``'s directory, PURELY textually.

    Never ``Path.resolve()``: that touches the real filesystem and would
    resolve against the source tree instead of the adopter's deploy tree.
    """
    parts = [p for p in Path(dest).parent.as_posix().split("/") if p and p != "."]
    for seg in target.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
        else:
            parts.append(seg)
    return "/".join(parts)


def _unresolved_seed_links(
    bodies: dict[str, str], allowed: set[str]
) -> list[tuple[str, str]]:
    """``(seed_dest, link_target)`` for links pointing outside what ``init`` deploys.

    Pure over its two inputs -- no filesystem read -- so the earn-the-red drives
    a SYNTHETIC bodies dict and never mutates the protected, byte-mirrored
    ``espalier/assets/`` tree. A trailing-slash target is a DIRECTORY reference
    and resolves if any deployed path lives under it: 2 such links exist
    (``memory/README.md`` -> ``../docs/sharp-edges/``, ``docs/sharp-edges/README.md``
    -> ``../../memory/``) and BOTH are correct, so without this branch the
    contract ships 2 false positives on day one.
    """
    out: list[tuple[str, str]] = []
    for dest, body in sorted(bodies.items()):
        for raw in _MD_LINK_RE.findall(_FENCE_RE.sub("", body)):
            target = raw.split("#", 1)[0]
            if not target or target.startswith(("http", "mailto:", "#")):
                continue
            norm = _normalize_rel(dest, target)
            if target.endswith("/"):
                if not any(a.startswith(norm + "/") for a in allowed):
                    out.append((dest, raw))
                continue
            if norm not in allowed:
                out.append((dest, raw))
    return out


def test_seeded_doc_links_resolve_to_deployed_targets():
    """Every markdown link in an init-seeded doc points at something `init` deploys.

    Scans the DEPLOY bodies under ``espalier/assets/**``, not the source tree: the
    deploy copies are already de-linked in places (``memory/README.md`` ->
    ``../docs/MEMORY_SYSTEMS.md`` is de-linked in the deploy copy), so a
    source-tree scan yields false hits. Fences are stripped -- an illustrative
    link inside a code fence is not a promise (``memory/README.md``'s table row
    is exactly that).
    """
    seeds = get_seed_docs()
    allowed = set(seeds) | {
        str(p).replace("\\", "/") for p in get_managed_public_files(REPO_ROOT)
    }
    auditable = sorted(set(seeds) - _SEEDS_WITHOUT_ASSET_BODY)
    # Coverage floor, not a presence floor: every seed is EITHER audited here or
    # named in the exclusion set with a reason. An `is_file()` filter plus a bare
    # `assert bodies` would let a future body-less seed drop out silently while
    # this stayed green -- a presence check standing in for a coverage check.
    missing_bodies = [
        s for s in auditable if not _seed_body_path(s).is_file()
    ]
    assert not missing_bodies, (
        "seed docs with no body under espalier/assets/ -- either the asset is "
        f"missing or it belongs in _SEEDS_WITHOUT_ASSET_BODY with a reason: {missing_bodies}"
    )
    bodies = {
        s: _seed_body_path(s).read_text(encoding="utf-8") for s in auditable
    }
    unresolved = _unresolved_seed_links(bodies, allowed)
    assert not unresolved, (
        "init-seeded doc links pointing at targets `init` never deploys -- de-link "
        f"them or add the target to the seed set: {unresolved}"
    )


def test_unresolved_seed_link_is_detected():
    # RED-equivalent: the exact TP-271a regression -- a seeded doc linking at
    # docs/SHARP_EDGES.md, which `init` does not deploy as a link target.
    offenders = _unresolved_seed_links(
        {"docs/HOOKS.md": "see [sharp edges](SHARP_EDGES.md)\n"},
        {"docs/HOOKS.md"},
    )
    assert offenders == [("docs/HOOKS.md", "SHARP_EDGES.md")]


def test_fenced_link_is_not_a_link():
    # FP calibration: an illustrative link inside a code fence is not a promise.
    assert _unresolved_seed_links(
        {"docs/HOOKS.md": "```\n[x](docs/NOPE.md)\n```\n"}, {"docs/HOOKS.md"}
    ) == []


def test_directory_target_branch_discriminates():
    # Second, orthogonal mutation: the directory branch must not pass everything.
    # A slash-target under a deployed path resolves; one under nothing does not.
    bodies = {"memory/README.md": "[a](../docs/sharp-edges/) [b](../docs/nope/)\n"}
    allowed = {"docs/sharp-edges/README.md"}
    assert _unresolved_seed_links(bodies, allowed) == [
        ("memory/README.md", "../docs/nope/")
    ]


def test_relative_parent_traversal_is_resolved_textually():
    # `..` must pop, and must not underflow past the root into a bogus match.
    assert _normalize_rel("memory/README.md", "../docs/X.md") == "docs/X.md"
    assert _normalize_rel("docs/sharp-edges/README.md", "../../memory/Y.md") == "memory/Y.md"
    assert _normalize_rel("README.md", "../../../etc/passwd") == "etc/passwd"
