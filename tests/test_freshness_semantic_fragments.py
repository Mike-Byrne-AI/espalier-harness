"""TP-56-C Sub-task 1-B: semantic-fragment bound-path existence.

The 6 semantic fragments seeded in TP-56-C use ``verify-on-touch``
policy. Each fragment's ``bound`` list must point at code paths that
actually exist in the repo — a typo or dead reference would silently
break drift detection (the bound paths never receive commits, so the
fragment is eternally fresh).

This test is the type-check equivalent for semantic fragments: it
catches stale or wrong bound paths at pytest time, before they hide
real drift.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The six fragments the seeding pack wrote by hand, kept as the non-vacuity
#: floor of the derived set below: each must still be discovered, or the
#: derivation has silently lost a marker.
SEEDED_SEMANTIC_FRAGMENTS: frozenset[str] = frozenset({
    "marker-contract",
    "release-noise-patterns",
    "hook-entrypoint-discipline",
    "freshness-cache-discipline",
    "ci-trigger-aware-marker",
    "dual-witness-release-gate",
})


def _verify_on_touch_fragments() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Every discovered fragment whose MARKER says verify-on-touch, with its
    bounds -- derived, never retyped, so a fragment flipped to the policy (the
    seven the pin-tax lane moved off numeric-contract on 2026-09-10) joins the
    sweep without an edit here."""
    from espalier.scanners.freshness import discover_fragments
    return tuple(
        (f.id, tuple(f.bound))
        for f in discover_fragments(REPO_ROOT)
        if f.policy == "verify-on-touch"
    )


SEMANTIC_FRAGMENTS: tuple[tuple[str, tuple[str, ...]], ...] = _verify_on_touch_fragments()


def _symbol_exists(path: str, symbol: str) -> bool:
    full = REPO_ROOT / path
    if not full.is_file():
        return False
    try:
        tree = ast.parse(full.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return False
    # A nested symbol (``Class::method`` or ``Class.method``) resolves one
    # segment per scope: each part must be defined in the body of the last.
    scope: ast.AST = tree
    for part in symbol.replace(".", "::").split("::"):
        names: dict[str, ast.AST] = {}
        for node in ast.iter_child_nodes(scope):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names[node.name] = node
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names[target.id] = node
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names[node.target.id] = node
        if part not in names:
            return False
        scope = names[part]
    return True


class TestSemanticFragmentBounds:
    """Each semantic fragment's bound entries must resolve to real code.

    The set is derived from the discovered markers (every verify-on-touch
    fragment), floored by the six seeded ids so it cannot go vacuous.

    The check is mechanical: split each entry on ``::``, verify the
    file exists, and (when a ``::symbol`` suffix is present) verify
    the symbol is defined at module scope via AST inspection.
    """

    def test_the_derived_set_holds_every_seeded_fragment(self) -> None:
        derived = {fid for fid, _ in SEMANTIC_FRAGMENTS}
        missing = SEEDED_SEMANTIC_FRAGMENTS - derived
        assert not missing, f"seeded verify-on-touch fragments no longer discovered: {sorted(missing)}"
        assert len(derived) >= len(SEEDED_SEMANTIC_FRAGMENTS)

    def test_all_bound_paths_exist(self) -> None:
        missing: list[str] = []
        for fragment_id, bounds in SEMANTIC_FRAGMENTS:
            for entry in bounds:
                path = entry.split("::", 1)[0]
                if not (REPO_ROOT / path).exists():
                    missing.append(f"{fragment_id}: {entry}")
        assert not missing, (
            f"semantic fragment bound paths do not exist: {missing}"
        )

    def test_all_bound_symbols_exist(self) -> None:
        missing: list[str] = []
        for fragment_id, bounds in SEMANTIC_FRAGMENTS:
            for entry in bounds:
                if "::" not in entry:
                    continue
                path, symbol = entry.split("::", 1)
                if not _symbol_exists(path, symbol):
                    missing.append(f"{fragment_id}: {entry}")
        assert not missing, (
            f"semantic fragment bound symbols not found at module scope: "
            f"{missing}"
        )

    def test_all_seeded_fragments_discoverable(self) -> None:
        from espalier.scanners.freshness import discover_fragments
        seeded = {fid for fid, _ in SEMANTIC_FRAGMENTS}
        discovered = {f.id for f in discover_fragments(REPO_ROOT)}
        missing = seeded - discovered
        assert not missing, (
            f"semantic fragments not discovered (marker missing or "
            f"surface excluded by allowlist/denylist): {missing}"
        )

    def test_all_seeded_fragments_pinned_with_verify_on_touch(
        self,
    ) -> None:
        import json
        manifest = json.loads(
            (REPO_ROOT / ".espalier" / "freshness.json")
            .read_text(encoding="utf-8")
        )
        for fid, _ in SEMANTIC_FRAGMENTS:
            entry = manifest["fragments"].get(fid)
            assert entry is not None, f"{fid} not in manifest"
            assert entry.get("last_verified_sha"), (
                f"{fid} present but unpinned"
            )
            assert entry.get("policy") == "verify-on-touch", (
                f"{fid} policy={entry.get('policy')!r}, expected "
                f"verify-on-touch"
            )


class TestMarkerContractClosure:
    """``marker-contract`` is the one seeded semantic fragment that
    opts into ``bound_closure=true``. Verify the parser recognizes it."""

    def test_marker_contract_has_bound_closure_true(self) -> None:
        from espalier.scanners.freshness import discover_fragments
        for f in discover_fragments(REPO_ROOT):
            if f.id == "marker-contract":
                assert f.bound_closure is True
                return
        raise AssertionError("marker-contract fragment not found")
