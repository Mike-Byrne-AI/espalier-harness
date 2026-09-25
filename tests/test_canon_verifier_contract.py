"""Pin every load-bearing claim resolves to a canon (or is explicit
convention/dormant).

TP-142 (FM-6 / TP-141-H) flipped enforcement default-on by removing
the ``@enforcing_only`` decorators below. The seven enforcement tests
now run on every pytest invocation; they no longer require
``ESPALIER_CANON_VERIFIER=enforce`` to fire.

The ``enforcing_only`` marker is retained (with the constant
``_ENFORCING`` and the env-var read) so operators can temporarily
re-gate a single test during debugging — re-add ``@enforcing_only`` to
one test, set ``unset ESPALIER_CANON_VERIFIER`` in the shell, and pytest
will skip it. This avoids re-deriving the env-var logic in an emergency.
"""

import os
import pytest

from espalier.scanners import canon_verifier as cv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_ENFORCING = (
    os.environ.get("ESPALIER_CANON_VERIFIER", "").lower() == "enforce"
)
# TP-142 / TP-141-H: retained for debugging convenience after the flip.
# Re-add ``@enforcing_only`` to any test below to gate it on the env
# var; without the decorator the test runs unconditionally.
enforcing_only = pytest.mark.skipif(
    not _ENFORCING,
    reason="ESPALIER_CANON_VERIFIER=enforce not set (re-gating opt-in)",
)


def test_verifier_runs_in_advisory_mode_by_default() -> None:
    """Always-on smoke: verifier imports cleanly and walks repo without
    raising. Does NOT assert on findings — that's the enforcement test."""
    findings = cv.verify_repo(REPO_ROOT)
    assert isinstance(findings, list)


def test_no_unregistered_claim_surfaces() -> None:
    findings = cv.verify_repo(REPO_ROOT)
    unregistered = [f for f in findings if f.severity == "UNREGISTERED_SURFACE"]
    assert not unregistered, (
        f"{len(unregistered)} doc surface(s) contain canon annotations "
        f"but aren't in CLAIM_SURFACES:\n" + "\n".join(
            f"  {f.claim.surface_path} — {f.explanation}"
            for f in unregistered
        )
    )


def test_no_missing_canons() -> None:
    findings = cv.verify_repo(REPO_ROOT)
    missing = [f for f in findings if f.severity == "MISSING_CANON"]
    assert not missing, (
        f"{len(missing)} claim(s) reference non-existent canon:\n" + "\n".join(
            f"  {f.claim.surface_path}:{f.claim.claim_lineno} — "
            f"canon=`{f.claim.canon}` — {f.explanation}"
            for f in missing
        )
    )


def test_no_missing_claim_ids() -> None:
    findings = cv.verify_repo(REPO_ROOT)
    no_id = [f for f in findings if f.severity == "MISSING_CLAIM_ID"]
    assert not no_id, (
        f"{len(no_id)} claim(s) have `<!-- canon: -->` but no adjacent "
        f"`<!-- claim-id: -->`."
    )


def test_no_missing_pins() -> None:
    findings = cv.verify_repo(REPO_ROOT)
    no_pins = [f for f in findings if f.severity == "MISSING_PINS"]
    assert not no_pins, (
        f"{len(no_pins)} test canon(s) lack `# pins: claim:<slug>` "
        f"annotation."
    )


def test_no_pins_mismatch() -> None:
    findings = cv.verify_repo(REPO_ROOT)
    mismatch = [f for f in findings if f.severity == "PINS_MISMATCH"]
    assert not mismatch, (
        f"{len(mismatch)} bidirectional slug mismatch(es):\n" + "\n".join(
            f"  {f.explanation}" for f in mismatch
        )
    )


def test_stacked_canon_binds_within_block() -> None:
    """A canon-first multi-canon block binds each canon to ITS OWN claim-id,
    not the PREVIOUS claim's. Regression guard for the block-bounded scan in
    ``_find_adjacent_claim_id``; the old ±window scan (above-before-below)
    returns the previous claim's id for the top canon (a PINS_MISMATCH in the
    full corpus when a multi-canon claim is written in the natural order)."""
    lines = [
        "3. Previous rule prose",
        "<!-- canon: convention -->",
        "<!-- claim-id: prev-rule -->",
        "4. This rule prose",
        "<!-- canon: tests/test_x.py::A -->",   # TOP canon (canon-first order)
        "<!-- canon: tests/test_x.py::B -->",
        "<!-- claim-id: this-rule -->",          # claim-id LAST (sibling order)
    ]
    assert cv._find_adjacent_claim_id(lines, 4) == "this-rule"   # top canon
    assert cv._find_adjacent_claim_id(lines, 5) == "this-rule"   # second canon
    assert cv._find_adjacent_claim_id(lines, 1) == "prev-rule"   # unaffected


def test_stacked_canon_binds_claim_id_first() -> None:
    """The block-scan UP-walk is the load-bearing half for the claim-id-FIRST
    ordering (claim-id ABOVE its canons). ``_find_adjacent_claim_id``'s docstring
    promises "canon-first and claim-id-first orderings both resolve", but no live
    ``CLAIM_SURFACES`` claim exercises the claim-id-first half today (Core Rule 4,
    the only multi-canon claim, is written canon-first), so a down-only-walk refactor
    would keep the whole suite AND the corpus green while silently breaking the
    documented promise. This is the missing witness: the two canons below sit BELOW
    their shared claim-id and must both bind up to it.

    Earn-red (recorded, not run here): monkeypatching ``_annotation_block_bounds`` to
    drop the up-walk (``lo = idx``) makes both assertions RED (they return ``""``); the
    production up-walk keeps them GREEN. The canon-first sibling stays bound regardless.
    """
    lines = [
        "3. Previous rule prose",
        "<!-- canon: convention -->",
        "<!-- claim-id: prev-rule -->",
        "4. This rule prose",
        "<!-- claim-id: this-rule -->",          # claim-id FIRST (above its canons)
        "<!-- canon: tests/test_x.py::A -->",    # TOP canon (claim-id-first order)
        "<!-- canon: tests/test_x.py::B -->",    # second canon
    ]
    assert cv._find_adjacent_claim_id(lines, 5) == "this-rule"   # top canon binds UP
    assert cv._find_adjacent_claim_id(lines, 6) == "this-rule"   # second canon binds UP
    assert cv._find_adjacent_claim_id(lines, 1) == "prev-rule"   # canon-first sibling unaffected


def test_annotation_block_bounds_edges() -> None:
    """Forward guard for the block-scan boundaries (a gate helper — a future
    off-by-one must red here): out-of-range idx returns "" without raising, a
    canon at line 0 binds a claim-id below it, and a canon-only block running
    to EOF with no claim-id returns "" (surfaces MISSING_CLAIM_ID)."""
    assert cv._find_adjacent_claim_id(["x"], -1) == ""
    assert cv._find_adjacent_claim_id(["x"], 5) == ""
    assert cv._find_adjacent_claim_id([], 0) == ""
    top = ["<!-- canon: convention -->", "<!-- claim-id: only -->"]
    assert cv._find_adjacent_claim_id(top, 0) == "only"        # canon at line 0
    eof = ["4. claim prose", "<!-- canon: convention -->"]
    assert cv._find_adjacent_claim_id(eof, 1) == ""            # block to EOF, no id


def test_no_naked_claims() -> None:
    """v3 originating-failure-mode close: any claim discovered by a
    surface's ``CLAIM_DISCOVERERS`` entry but missing an annotation."""
    findings = cv.verify_repo(REPO_ROOT)
    naked = [f for f in findings if f.severity == "MISSING_ANNOTATION"]
    assert not naked, (
        f"{len(naked)} naked claim(s) on registered surfaces:\n" + "\n".join(
            f"  {f.claim.surface_path}:{f.claim.claim_lineno} — "
            f"`{f.claim.claim_text[:80]}` — {f.explanation}"
            for f in naked
        )
    )


def test_pins_stub_count_within_budget() -> None:
    """Stubs are allowed (bootstrap reality) but capped. Raising
    MAX_PINS_STUB_COUNT is deliberate operator action that signals
    growing canon-vs-claim debt (same pattern as TP-138 MAX_PRAGMA_COUNT)."""
    findings = cv.verify_repo(REPO_ROOT)
    stubs = [f for f in findings if f.severity == "PINNED-STUB"]
    assert len(stubs) <= cv.MAX_PINS_STUB_COUNT, (
        f"PINNED-STUB count ({len(stubs)}) exceeds cap "
        f"({cv.MAX_PINS_STUB_COUNT}). Either upgrade stubs to real "
        f"behavioral pins (`# pins-stub:` -> `# pins:`) or raise the cap "
        f"explicitly with rationale."
    )


def test_exempt_prose_files_within_budget() -> None:
    """The canon-exempt prose-file allowlist is capped. Each entry is a doc that
    quotes canon syntax inside prose without carrying real annotations; growing the
    allowlist is deliberate operator action (same pattern as MAX_PINS_STUB_COUNT).
    TP-190: wires the previously-inert ``MAX_EXEMPT_PROSE_FILES`` cap — it had zero
    readers, so the budget it documents was never enforced."""
    assert len(cv.EXEMPT_PROSE_FILES) <= cv.MAX_EXEMPT_PROSE_FILES, (
        f"EXEMPT_PROSE_FILES count ({len(cv.EXEMPT_PROSE_FILES)}) exceeds cap "
        f"({cv.MAX_EXEMPT_PROSE_FILES}). Adding a doc to the canon-exempt allowlist "
        f"is deliberate — raise the cap explicitly with rationale."
    )


def test_scanner_is_stdlib_only() -> None:
    target = REPO_ROOT / "espalier" / "scanners" / "canon_verifier.py"
    source = target.read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        assert "from espalier" not in stripped
        assert "import espalier" not in stripped


class TestClaimDiscoverersNotStubs:
    """FM-11 close: every registered claim discoverer must have a
    non-stub function body. A stub (single ``return []`` or
    ``return list()``) creates §5.4 self-verifying canon -- the
    ``test_no_naked_claims`` test for the discoverer's surface passes
    vacuously because the discoverer never reports any claim line.

    AST-walks every function in CLAIM_DISCOVERERS.values(); rejects any
    whose body (after the optional docstring) is a single ``return []``
    / ``return list()`` statement.
    """

    def test_no_stub_discoverers(self) -> None:
        import ast
        import inspect

        stubs: list[str] = []
        for shape_label, fn in cv.CLAIM_DISCOVERERS.items():
            source = inspect.getsource(fn)
            tree = ast.parse(source)
            fn_def = tree.body[0]
            assert isinstance(fn_def, ast.FunctionDef)
            body = fn_def.body
            # Strip docstring if present (first stmt is Expr/Constant/str).
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body = body[1:]
            # Stub shapes to reject:
            #   return []          -- empty list literal
            #   return list()      -- empty list() call
            if len(body) == 1 and isinstance(body[0], ast.Return):
                ret = body[0].value
                is_empty_list = (
                    isinstance(ret, ast.List) and not ret.elts
                )
                is_list_call = (
                    isinstance(ret, ast.Call)
                    and isinstance(ret.func, ast.Name)
                    and ret.func.id == "list"
                    and not ret.args
                    and not ret.keywords
                )
                if is_empty_list or is_list_call:
                    stubs.append(f"{fn.__name__} (shape={shape_label!r})")

        assert not stubs, (
            f"{len(stubs)} CLAIM_DISCOVERERS entries are structurally "
            f"stubs (return [] unconditionally), creating §5.4 "
            f"self-verifying canon. Either implement a real discoverer or "
            f"remove the surface from CLAIM_SURFACES. Stubs: {stubs}"
        )

    def test_every_registered_surface_has_a_discoverer(self) -> None:
        """441-E / FAILURE_MODES §18.4: the DELETION spelling of the same
        vacuity ``test_no_stub_discoverers`` bans above.

        ``_verify_surface`` reads the walker with
        ``CLAIM_DISCOVERERS.get(shape_label)`` and returns early on ``None``
        (canon_verifier.py:322-324). So REMOVING a discoverer while leaving its
        ``CLAIM_SURFACES`` row retires the naked-claim gate for that entire
        document -- byte-identically to the ``return []`` stub next door, but
        with no stub to find. Nothing shrinks and no count moves: this is
        §18.4's mechanism (B), a fail-open registry lookup, not the
        population-shrinks-with-subject shape.

        Measured at HEAD 2026-08-18 by calling each discoverer over its live
        surface: 26 claims total (CLAUDE.md 18, docs/HOOK_ASSUMPTIONS.md 5,
        docs/CONVENTIONS.md 3). Dropping ``priority-order-numbered-list``
        alone unpolices **18 of 26 (69%)** with the suite green.

        Set-equality, deliberately BOTH ways:
          registered - implemented -> a surface that fails open (the bug);
          implemented - registered -> an orphan walker, i.e. a surface was
          deleted without its discoverer, which hides the reverse mistake.
        """
        registered = {shape for _, shape in cv.CLAIM_SURFACES}
        implemented = set(cv.CLAIM_DISCOVERERS)
        assert implemented == registered, (
            "CLAIM_SURFACES and CLAIM_DISCOVERERS have drifted, so at least "
            "one claim surface is policed by nothing.\n"
            f"  registered with no discoverer (FAILS OPEN): "
            f"{sorted(registered - implemented)}\n"
            f"  discoverer with no registered surface (orphan): "
            f"{sorted(implemented - registered)}\n"
            "Fix by adding the missing CLAIM_DISCOVERERS entry, not by "
            "deleting the CLAIM_SURFACES row -- deleting the row is what the "
            "gate is here to notice.\n"
            "NOTE for whoever arrived here from the scanner's own "
            "UNREGISTERED_SURFACE message: that text names this edit as "
            "TWO parts (the CLAIM_SURFACES row AND a matching "
            "CLAIM_DISCOVERERS entry), so landing here means the shape "
            "label in your new row has no discoverer -- add it, rather "
            "than reaching for an exemption. "
            f"EXEMPT_PROSE_FILES holds {len(cv.EXEMPT_PROSE_FILES)} of a "
            f"capped {cv.MAX_EXEMPT_PROSE_FILES}, so it is not an escape "
            "hatch."
        )

    #: 441-E / F1: the EXACT per-surface claim yield, ASSERTED rather than
    #: recorded in prose. The first cut of this fix wrote these three numbers
    #: into a docstring and asserted none of them -- FAILURE_MODES §18.1
    #: (a measurement that lives in prose is not a gate) committed inside a fix
    #: for §18.4. Hand-written on purpose: computing it from the discoverers is
    #: the tautology this whole pack exists to remove.
    _EXPECTED_CLAIM_YIELD = {
        "CLAUDE.md": 19,
        "docs/HOOK_ASSUMPTIONS.md": 5,
        "docs/CONVENTIONS.md": 3,
    }

    def test_every_discoverer_still_engages_its_live_surface(self) -> None:
        """Set-equality on shape labels is NOT enough: two more axes of the same
        registry fail open, and both were measured live.

        AXIS 1 -- TRIGGER. ``_discover_priority_order`` keys on the substrings
        "Priority Order" / "Core Rules" appearing in a line. Renaming the
        heading ``## Core Rules`` to ``## Core rules`` -- ONE character, an
        ordinary prose tidy -- drops its yield from 18 claims to 5, and the full
        suite is BIT-IDENTICAL. An unannotated Core Rule added afterwards is
        then accepted silently (MISSING_ANNOTATION 1 -> 0). A live, non-stub
        walker whose trigger no longer occurs is indistinguishable in effect
        from the ``return []`` stub the sibling test bans.

        ⚠ A ``yield > 0`` floor is BLIND to this: CLAUDE.md carries TWO matching
        headings, so renaming one leaves 5, not 0. That is §18.4's own warning
        about ``>=`` floors with slack, landing on this fix. Exact counts are
        required, which is why the numbers above are literals.

        AXIS 2 -- PATH. ``verify_repo`` skips a registered surface whose file is
        absent (``if not target.exists(): continue``), a SECOND fail-open eleven
        lines above the ``.get()`` the sibling assertion cites. A moved or
        renamed doc silently stops being policed.

        Growth is expected to red here, and that is the design: adding a Core
        Rule or Priority Order item means bumping the count below, in the same
        edit that adds the item's ``<!-- canon: -->`` annotation. Both signals
        fire on one change, so the ceremony is one number.
        """
        from pathlib import Path

        registered = {rel for rel, _ in cv.CLAIM_SURFACES}
        assert set(self._EXPECTED_CLAIM_YIELD) == registered, (
            "a claim surface was registered or removed without declaring its "
            "expected yield, so its discoverer's engagement is unasserted -- "
            "registering a new surface under an EXISTING shape label whose "
            "discoverer finds nothing there is green without this.\n"
            f"  registered with no expected yield: "
            f"{sorted(registered - set(self._EXPECTED_CLAIM_YIELD))}\n"
            f"  expected yield with no surface:    "
            f"{sorted(set(self._EXPECTED_CLAIM_YIELD) - registered)}"
        )

        root = Path(__file__).resolve().parent.parent
        actual: dict[str, int] = {}
        for rel, shape_label in cv.CLAIM_SURFACES:
            target = root / rel
            assert target.exists(), (
                f"registered claim surface {rel} does not exist, and verify_repo "
                f"SKIPS a missing surface silently -- so this doc is policed by "
                f"nothing. Re-point CLAIM_SURFACES or remove the row "
                f"deliberately."
            )
            discoverer = cv.CLAIM_DISCOVERERS[shape_label]
            lines = target.read_text(encoding="utf-8").splitlines()
            actual[rel] = len(discoverer(lines))

        assert actual == self._EXPECTED_CLAIM_YIELD, (
            "a claim discoverer's yield changed against its live surface.\n"
            f"  expected: {self._EXPECTED_CLAIM_YIELD}\n"
            f"  actual  : {actual}\n"
            "If you ADDED a claim: bump the number here (and annotate the claim "
            "-- the naked-claim gate wants that too).\n"
            "If you did NOT touch the claims, a DISCOVERER'S TRIGGER STOPPED "
            "MATCHING. Most likely a heading was reworded: the walkers key on "
            "literal substrings, so a one-character case change silently "
            "unpolices a whole section. Restore the heading rather than "
            "lowering the count."
        )


# ─────────────────────────────────────────────────────────────────────
# TP-150 F-1 / §5.10: a meta-gate enforcing a validation artifact must
# assert the artifact DISCRIMINATES, not merely that it exists + slug-
# matches. For a claim naming a numeric threshold, the pinned test body
# must reference at least one of those literals to earn PINNED -- a body
# that asserts only arithmetic shape is a stub in disguise (PINNED-STUB).
# Earn-the-red: pre-F-1 `_verify_test_canon` returned PINNED on slug-match
# alone, so both synthetic threshold cases below would have been PINNED.

def _synthetic_claim(canon: str, claim_id: str, claim_text: str) -> cv.ClaimRecord:
    return cv.ClaimRecord(
        surface_path=Path("docs/CONVENTIONS.md"),
        claim_lineno=1,
        claim_text=claim_text,
        canon=canon,
        claim_id=claim_id,
    )


def test_threshold_claim_without_literal_drops_to_stub(tmp_path: Path) -> None:
    """A numeric-threshold claim whose pinned test asserts only arithmetic
    shape (never the threshold literal) is PINNED-STUB, not PINNED."""
    test_file = tmp_path / "tests" / "test_synthetic.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "# pins: claim:synthetic-threshold\n"
        "def test_shape():\n"
        "    assert compute() == 5\n",
        encoding="utf-8",
    )
    claim = _synthetic_claim(
        "tests/test_synthetic.py::test_shape",
        "synthetic-threshold",
        "Mean must stay below 0.42 across the chain.",
    )
    finding = cv._verify_test_canon(claim, tmp_path)
    assert finding.severity == "PINNED-STUB", finding.explanation


def test_threshold_claim_referencing_literal_stays_pinned(tmp_path: Path) -> None:
    """When the pinned test body references the threshold literal, the
    discrimination is satisfied and the canon earns PINNED."""
    test_file = tmp_path / "tests" / "test_synthetic.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "# pins: claim:synthetic-threshold\n"
        "def test_threshold():\n"
        "    assert compute_mean() < 0.42\n",
        encoding="utf-8",
    )
    claim = _synthetic_claim(
        "tests/test_synthetic.py::test_threshold",
        "synthetic-threshold",
        "Mean must stay below 0.42 across the chain.",
    )
    finding = cv._verify_test_canon(claim, tmp_path)
    assert finding.severity == "PINNED", finding.explanation


def test_non_threshold_claim_unaffected_by_discrimination(tmp_path: Path) -> None:
    """A claim with no numeric-threshold literal in its prose is not subject
    to the reference check -- it earns PINNED on a clean slug match."""
    test_file = tmp_path / "tests" / "test_synthetic.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "# pins: claim:synthetic-prose\n"
        "def test_behavior():\n"
        "    assert run() == 'ok'\n",
        encoding="utf-8",
    )
    claim = _synthetic_claim(
        "tests/test_synthetic.py::test_behavior",
        "synthetic-prose",
        "tools/cc scripts have zero espalier imports.",
    )
    finding = cv._verify_test_canon(claim, tmp_path)
    assert finding.severity == "PINNED", finding.explanation
