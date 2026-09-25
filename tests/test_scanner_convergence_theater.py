"""Pin the convergence-theater scanner's behavioral contract.

Eight checks: earn-the-gate (every documented shape detected in the
fixture file), pragma cap, EXEMPT_FILES cap, missing-reason pragma
non-exemption, valid-reason pragma exemption, independent-witness
non-flag, scanner stdlib-only self-containment, and build_report
shape (for cmd_scan integration).

The earn-the-gate test is TP-105 pattern: without it, a future
scanner change that silently breaks detection passes CI. The fixture
at tests/fixtures/test_convergence_theater_positives.py contains at least
one known-positive per shape (approx-self carries both operand orders, so
do not "dedupe" it); monkeypatching both EXEMPT_FILES and
EXEMPT_PREFIXES off lets the scanner walk the fixture.
"""

from __future__ import annotations

from pathlib import Path

from espalier.scanners import convergence_theater as ct


REPO_ROOT = Path(__file__).resolve().parents[1]
NEG_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "test_convergence_theater_negatives.py"
)


def test_does_not_trip_on_negatives() -> None:
    """Must-NOT-trip corpus: clean-but-tempting twins of every theater
    shape (independent witnesses, floor/inequality contracts, distinct
    operands, approx-against-other, pragma-with-reason). DIRECT-CALL
    `_scan_file` on the fixture path -- immune to live-tree drift, unlike
    scan_repo(REPO_ROOT) -- and assert ZERO findings.

    Pairs with test_earn_the_gate_*: that proves the scanner FIRES on
    real theater; this proves it STAYS SILENT on near-boundary clean
    input, so the green is non-vacuous.
    """
    findings = list(ct._scan_file(NEG_FIXTURE, REPO_ROOT, frozenset()))
    assert findings == [], (
        "convergence_theater scanner tripped on clean negatives fixture: "
        f"{[(f.shape, f.lineno) for f in findings]}"
    )


def test_earn_the_gate_detects_every_fixture_shape(monkeypatch) -> None:
    """Run scanner against the known-positives fixture (with file AND
    prefix exemption monkeypatched off) -- every documented shape must
    surface.

    Two exemption layers must both be lifted:
    - EXEMPT_FILES: in case the fixture filename is ever added there
    - EXEMPT_PREFIXES: ('tests/fixtures/',) -- fires FIRST in scan_repo
      and would silently skip the fixture file without this patch
    """
    monkeypatch.setattr(ct, "EXEMPT_FILES", frozenset())
    monkeypatch.setattr(ct, "EXEMPT_PREFIXES", ())
    findings = ct.scan_repo(REPO_ROOT)
    fixture_findings = [
        f for f in findings
        if str(f.path).replace("\\", "/")
        == "tests/fixtures/test_convergence_theater_positives.py"
    ]
    found_shapes = {f.shape for f in fixture_findings}
    expected_shapes = {
        "literal-pair", "same-call", "same-attribute",
        "derived-constant", "approx-self",
        "assertEqual-self", "assertEqual-same-call",
    }
    missing = expected_shapes - found_shapes
    assert not missing, (
        f"Scanner failed to detect fixture shapes: {missing}. "
        f"This is the earn-the-gate validation (TP-105 pattern). "
        f"Found shapes: {found_shapes}"
    )
    # Severity is the load-bearing signal, not just the shape set. A relabel-defang
    # preserves the shape while inverting the hedged/hard verdict:
    #   SUSPECT -> THEATER at the assertEqual-same-call arm of
    #   `_check_unittest_call` and the approx-self / derived-constant arms of
    #   `_compare_two_sides` in convergence_theater.py (content anchors; the
    #   line numbers this comment once carried drifted within a month).
    # Pin severity per shape so any such flip goes red here. (Closes A-5's unittest
    # same-call path and the C-2 SUSPECT shapes in one severity-emission contract.)
    sev_by_shape: dict[str, set[str]] = {}
    for f in fixture_findings:
        sev_by_shape.setdefault(f.shape, set()).add(f.severity)
    expected_sev = {
        "literal-pair": {"THEATER"},
        "same-call": {"SUSPECT"},
        "same-attribute": {"THEATER"},
        "derived-constant": {"SUSPECT"},
        "approx-self": {"SUSPECT"},
        "assertEqual-self": {"THEATER"},
        "assertEqual-same-call": {"SUSPECT"},
    }
    assert sev_by_shape == expected_sev, (
        f"severity-by-shape drift: expected {expected_sev}, got {sev_by_shape}"
    )


def test_pragma_count_within_cap() -> None:
    """Pragma usage across tests/ must not exceed MAX_PRAGMA_COUNT.
    Growing past the cap requires a deliberate cap raise -- surfaces
    accumulating technical debt."""
    actual = ct.count_pragmas(REPO_ROOT)
    assert actual <= ct.MAX_PRAGMA_COUNT, (
        f"Theater pragma count ({actual}) exceeds cap "
        f"({ct.MAX_PRAGMA_COUNT}). Either close pragmas via "
        f"refactor, or raise MAX_PRAGMA_COUNT explicitly with rationale."
    )


def test_exempt_files_within_cap() -> None:
    """EXEMPT_FILES growth surfaces accumulating exemption debt.
    Raising MAX_EXEMPT_FILES is a deliberate operator act (mirrors
    the MAX_PRAGMA_COUNT discipline)."""
    actual = len(ct.EXEMPT_FILES)
    assert actual <= ct.MAX_EXEMPT_FILES, (
        f"EXEMPT_FILES count ({actual}) exceeds cap "
        f"({ct.MAX_EXEMPT_FILES}). Either refactor flagged files to "
        f"avoid the exemption, or raise MAX_EXEMPT_FILES explicitly."
    )


def test_pragma_without_reason_does_not_exempt(tmp_path: Path) -> None:
    """The pragma regex requires >=12-char reason; bare `# theater: ok`
    does NOT exempt."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_bare_pragma.py").write_text(
        "def test_silly():\n"
        "    # theater: ok\n"      # no reason -- should NOT exempt
        "    assert 1 == 1\n",
        encoding="utf-8",
    )
    findings = ct.scan_repo(tmp_path)
    assert any(f.shape == "literal-pair" for f in findings), (
        "Bare `# theater: ok` (no reason) must not exempt the assertion."
    )


def test_derived_constant_order_agnostic_and_qualified(tmp_path: Path) -> None:
    """TP-192 W4-2: the derived-constant shape now fires on the REVERSED
    orientation (``EXPECTED_X == len(...)``) and on a module-qualified
    ``mod.EXPECTED_X`` (ast.Attribute), not just ``len(...) == EXPECTED_X`` with
    a bare Name. This repo's own ``tests/test_wheel_smoke.py`` uses both forms,
    so the prior left-only/bare-Name-only check was blind to a shape it ships."""
    f = tmp_path / "test_x.py"
    f.write_text(
        "def test_a():\n"
        "    assert EXPECTED_N == len(items)\n"        # reversed, bare Name
        "    assert mod.EXPECTED_M == len(items)\n"    # reversed, qualified
        "    assert len(items) == mod.EXPECTED_K\n",   # forward, qualified
        encoding="utf-8",
    )
    findings = list(ct._scan_file(f, tmp_path, frozenset()))
    dc = [x for x in findings if x.shape == "derived-constant"]
    assert len(dc) == 3, [(x.shape, x.lineno) for x in findings]


def test_approx_self_order_agnostic(tmp_path: Path) -> None:
    """DEF-410l earn-the-red: ``pytest.approx(X) == X`` is the same tolerance
    check against self as ``X == pytest.approx(X)``, and the arm only looked at
    the right operand while the derived-constant arm directly below it had been
    made order-agnostic for exactly this reason. Both orders and the bare
    ``approx`` Name form must fire; approx against a DIFFERENT operand, in
    either order, must not."""
    f = tmp_path / "test_x.py"
    f.write_text(
        "from pytest import approx\n"
        "def test_a():\n"
        "    assert pytest.approx(x) == x\n"      # reversed, qualified
        "    assert x == pytest.approx(x)\n"      # forward, qualified
        "    assert approx(x) == x\n"             # reversed, bare Name
        "    assert pytest.approx(y) == x\n"      # reversed, different operand
        "    assert x == pytest.approx(y)\n",     # forward, different operand
        encoding="utf-8",
    )
    findings = list(ct._scan_file(f, tmp_path, frozenset()))
    hits = sorted(x.lineno for x in findings if x.shape == "approx-self")
    assert hits == [3, 4, 5], [(x.shape, x.lineno) for x in findings]


def test_derived_constant_negatives_still_cleared(tmp_path: Path) -> None:
    """Negative control: a literal ``EXPECTED_N == 5`` and an unrelated
    ``len(x) == y`` must NOT be flagged derived-constant."""
    f = tmp_path / "test_y.py"
    f.write_text(
        "def test_b():\n"
        "    assert EXPECTED_N == 5\n"     # literal RHS, not len()
        "    assert len(x) == y\n",        # y is not an EXPECTED_ constant
        encoding="utf-8",
    )
    findings = list(ct._scan_file(f, tmp_path, frozenset()))
    dc = [x for x in findings if x.shape == "derived-constant"]
    assert dc == [], [(x.shape, x.lineno) for x in findings]


def test_pragma_with_reason_exempts(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_good_pragma.py").write_text(
        "def test_silly():\n"
        "    # theater: ok intentional sanity check\n"
        "    assert 1 == 1\n",
        encoding="utf-8",
    )
    findings = ct.scan_repo(tmp_path)
    assert not findings


def test_independent_witnesses_not_flagged(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ok.py").write_text(
        "from a import producer_a\nfrom b import producer_b\n"
        "def test_two_witnesses():\n"
        "    assert len(producer_a.items()) == len(producer_b.items())\n",
        encoding="utf-8",
    )
    findings = ct.scan_repo(tmp_path)
    # Different producers -- not theater
    assert not findings


def test_scanner_no_espalier_import() -> None:
    """Reinforce the existing TestScannerSelfContainment contract
    (tests/test_scanners.py::TestScannerSelfContainment at line 58)
    at the new module's location."""
    target = REPO_ROOT / "espalier" / "scanners" / "convergence_theater.py"
    source = target.read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Catches both `from espalier...` and `import espalier...` --
        # the substring covers both prefixes since the package name
        # is what we're forbidding here.
        assert "from espalier" not in stripped, (
            f"Scanner violates self-containment: {stripped}"
        )
        assert "import espalier" not in stripped, (
            f"Scanner violates self-containment: {stripped}"
        )


def test_build_report_shape() -> None:
    """build_report must return the dict-of-counts shape that cmd_scan
    expects -- matches the existing scanner reports."""
    report = ct.build_report(REPO_ROOT)
    assert isinstance(report, dict)
    assert "count" in report
    assert "theater_count" in report
    assert "suspect_count" in report
    assert "findings" in report
    assert isinstance(report["findings"], list)
    # Counts split correctly
    assert (
        report["theater_count"] + report["suspect_count"] == report["count"]
    ), "theater_count + suspect_count must equal total count"


def test_dangling_class_marker_does_not_crash(tmp_path) -> None:
    """TP-174a: a dangling '# class:' (no token after the colon) must not crash
    the whole scan with IndexError — it is treated as non-literal."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "_surface_expected.py").write_text(
        "EXPECTED_X = 5  # class:\n", encoding="utf-8"
    )
    (tmp_path / "tests" / "test_foo.py").write_text(
        "def test_a():\n    assert 1 == 1\n", encoding="utf-8"
    )
    # Must not raise (pre-fix: IndexError aborts scan_repo). scan_repo returns
    # a list of findings; completing the call at all is the assertion.
    report = ct.scan_repo(tmp_path)
    assert isinstance(report, list)


def test_bare_assert_same_call_is_suspect_not_theater() -> None:
    """The bare-assert same-call shape reports SUSPECT (symmetry with the
    already-hedged assertEqual-same-call path), never hard THEATER (sweep T6).
    A stateful callable (`next(it) == next(it)`) genuinely differs at runtime,
    so the matcher hedges instead of certifying theater."""
    pos = REPO_ROOT / "tests" / "fixtures" / "test_convergence_theater_positives.py"
    findings = list(ct._scan_file(pos, REPO_ROOT, frozenset()))
    same_call = [f for f in findings if f.shape == "same-call"]
    assert same_call, "same-call fixture shape should still be detected"
    assert all(f.severity == "SUSPECT" for f in same_call), (
        "bare-assert same-call must be SUSPECT, not THEATER: "
        + "; ".join(f"{f.lineno}:{f.severity}" for f in same_call)
    )
