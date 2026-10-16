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

from pathlib import Path
# The freshness scanner raises on a duplicate fragment id before any filter can
# run (a second seat's worktree or a copy-duplicate doc holds one), so it reads a
# copy of the surface git sees, cut by its own allowlist.
from tests._live_tree import checkout_copy

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
    from espalier.scanners.freshness import FRAGMENT_SURFACE_ALLOWLIST, discover_fragments
    return tuple(
        (f.id, tuple(f.bound))
        for f in discover_fragments(checkout_copy(FRAGMENT_SURFACE_ALLOWLIST))
        if f.policy == "verify-on-touch"
    )


SEMANTIC_FRAGMENTS: tuple[tuple[str, tuple[str, ...]], ...] = _verify_on_touch_fragments()


def _symbol_exists(path: str, symbol: str) -> bool:
    """Placed by the scanner's own walk, on the file as it is on disk: the suite
    calls a bound valid exactly when drift can be counted on its lines. Until
    2026-10-16 this was a second walk that took ``Class::method`` while the
    scanner placed top-level names only, so memory-line-cap's bound read valid
    here and drifted on every commit to its file there."""
    from espalier.scanners.freshness import _span_in_source
    full = REPO_ROOT / path
    if not full.is_file():
        return False
    try:
        source = full.read_text(encoding="utf-8")
    except OSError:
        return False
    return _span_in_source(source, symbol)[0] is not None


def _every_symbol_bound() -> tuple[tuple[str, str], ...]:
    """Every ``path::symbol`` entry of every discovered fragment, whatever its
    policy: each one's drift is counted on the symbol's lines or the file's."""
    from espalier.scanners.freshness import FRAGMENT_SURFACE_ALLOWLIST, discover_fragments
    return tuple(
        (f.id, entry)
        for f in discover_fragments(checkout_copy(FRAGMENT_SURFACE_ALLOWLIST))
        for entry in f.bound
        if "::" in entry
    )


class TestSemanticFragmentBounds:
    """Each semantic fragment's bound entries must resolve to real code.

    The set is derived from the discovered markers (every verify-on-touch
    fragment), floored by the six seeded ids so it cannot go vacuous.

    The check is mechanical: split each entry on ``::``, verify the
    file exists, and (when a ``::symbol`` suffix is present) verify the
    scanner's own walk places the symbol, nested ones one segment per scope.
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
            f"semantic fragment bound symbols the scanner cannot place: "
            f"{missing}"
        )

    def test_every_symbol_bound_the_scanner_counts_is_one_it_can_place(self) -> None:
        """Dies to: a bound the scanner cannot place, which counts every commit
        to its file (memory-line-cap re-pinned three days running over commits
        that never touched its method), on any policy, not only the six seeded."""
        entries = _every_symbol_bound()
        assert entries, "no symbol bound discovered: the derivation went vacuous"
        unplaced = [f"{fid}: {entry}" for fid, entry in entries if not _symbol_exists(*entry.split("::", 1))]
        assert not unplaced, f"symbol bounds the scanner cannot place (it counts the whole file): {unplaced}"

    def test_all_seeded_fragments_discoverable(self) -> None:
        from espalier.scanners.freshness import FRAGMENT_SURFACE_ALLOWLIST, discover_fragments
        seeded = {fid for fid, _ in SEMANTIC_FRAGMENTS}
        discovered = {f.id for f in discover_fragments(checkout_copy(FRAGMENT_SURFACE_ALLOWLIST))}
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
        from espalier.scanners.freshness import FRAGMENT_SURFACE_ALLOWLIST, discover_fragments
        for f in discover_fragments(checkout_copy(FRAGMENT_SURFACE_ALLOWLIST)):
            if f.id == "marker-contract":
                assert f.bound_closure is True
                return
        raise AssertionError("marker-contract fragment not found")
