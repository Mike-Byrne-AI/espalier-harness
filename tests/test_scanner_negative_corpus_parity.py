"""Cross-scanner contract: every scanner under espalier/scanners/
(excluding canon_verifier) MUST have a must-NOT-trip NEGATIVE corpus
plus a `test_does_not_trip*` test.

This is the silent-direction sibling of
tests/test_scanner_earn_the_gate_parity.py. That contract proves every
scanner FIRES on its positive corpus; this one proves every scanner is
also pinned to STAY SILENT on clean-but-tempting input. Without it, an
over-broad detector or a quietly-widened exemption that starts ignoring
real hits would be invisible — the harness would only ever measure the
fire direction. TP-156 Tier 1.

Negatives-path derivation (single source of truth):
    The negatives fixture path is DERIVED from each
    tests/test_scanner_<name>.py's OWN positives reference, swapping
    `_positives.` -> `_negatives.`. The scanner -> fixture mapping is
    therefore read from the place that already records it, so the
    naming divergences are honored automatically and never duplicated:
        filesystem_contracts -> test_filesystem_stealth_*
        subprocess_contracts -> test_subprocess_stealth_*
        retired_vocab        -> retired_vocab_*           (no test_ prefix)

Sibling: tests/test_scanner_earn_the_gate_parity.py (must-trip axis);
tests/test_scanners.py::TestScannerExemptPrefixesParity (exemption
presence). Same shape, different aspect.

§13.9 precision-boundary tier (PRECISION_BOUNDARY_REQUIRED):
    A scanner whose matcher OVER-fires (substring/regex/mixed) must do
    more than ship *any* clean corpus — its negatives fixture must label
    the matcher's PRECISION BOUNDARY (the near-miss it could over-fire on)
    with a `precision-boundary:` marker that NAMES the boundary class and
    never quotes the live trigger token. The required set is declared
    explicitly (not auto-classified, since a mixed-mode matcher would make
    a classifier itself a complacent oracle) and is an OPEN registry: it
    grows as each over-firing scanner earns its fixture. A future scanner
    author adds the name to PRECISION_BOUNDARY_REQUIRED and a marker line
    to its negatives fixture; AST-pure matchers (prints, godfiles,
    test_loosening) are precision-safer and may opt in but are not
    required. `freshness` is NOT one of them -- its FIRE DECISION is a
    raw-line regex -- so it is in the required set.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNER_DIR = REPO_ROOT / "espalier" / "scanners"
TEST_DIR = REPO_ROOT / "tests"

# canon_verifier is exempt on the NEGATIVE axis too: it has no fixture
# corpus (its surface is the CLAIM_SURFACES + CLAIM_DISCOVERERS registry,
# not a synthetic file), so there is no clean-corpus file to under-trip.
# Mirrors EARN_THE_GATE_EXEMPT in tests/test_scanner_earn_the_gate_parity.py.
# If a CLAIM_SURFACES over-fire surface is later found, give canon_verifier
# its own negative test rather than widening this exemption.
NEGATIVE_CORPUS_EXEMPT = frozenset({"canon_verifier"})

# §13.9 (complacent oracle): a scanner whose matcher OVER-fires must ship a
# negative case that covers its matcher's PRECISION BOUNDARY — the near-miss it
# could over-fire on — not just any clean corpus. The fixture labels that case
# with a `precision-boundary:` marker (an HTML comment in `.md` fixtures, a `#`
# comment in `.py` fixtures) naming the boundary CLASS. This bites the
# substring/regex/MIXED matchers that over-fire; the genuinely AST-pure matchers
# (prints, godfiles, test_loosening -- 0 `re.compile` between them; test_loosening's
# `.startswith` predicates run on AST node NAMES, not raw source) are precision-safer
# and may opt in later but are not required. `freshness` was previously grouped with
# them in error: its FIRE DECISION is a raw-line regex (`_FRAGMENT_OPEN_RE.search`);
# the `_ast` walk it also contains resolves the `bound=` import closure and never
# gates a finding. So it belongs in the required set below.
#
# We declare the required set explicitly rather than auto-classifying a
# `match_mode`: subprocess_contracts mixes AST + regex + substring, so a
# heuristic classifier is itself a complacent oracle. An explicit registry is
# the honest, mechanizable form — it grows as each scanner earns its fixture.
#
# MARKER CONVENTION: the marker NAMES the boundary class; it must NOT quote the
# live trigger token (a naive `precision-boundary` line quoting the trigger
# itself tripped perf_smells's matcher, since test_does_not_trip* scans the
# WHOLE fixture, marker line included).
PRECISION_BOUNDARY_MARKER = "precision-boundary:"
PRECISION_BOUNDARY_REQUIRED = frozenset(
    {
        "retired_vocab",          # reference impl — earned in this contract
        "perf_smells",            # bare-open substring over-match
        "exceptions",             # receiver-blind logger match
        "subprocess_contracts",   # leading-token interpreter substring
        "filesystem_contracts",   # wrapper-substring + basename collision
        "magic_depth",            # multi-line line-attribution
        "convergence_theater",    # same-call no-hedge
        "freshness",              # raw-line fragment-opener regex near-miss
    }
)

# Matches the positives-fixture BASENAME each test_scanner_<name>.py
# declares. We match the basename (not the full `tests/fixtures/...`
# path) because some test files build the path via Path joins
# (REPO_ROOT / "tests" / "fixtures" / "test_<x>_positives.py"), so only
# the basename is guaranteed to appear as a single string literal — it
# must, since the file is opened by name. The negatives ref (also
# present in the edited test files) is deliberately NOT matched.
#
# Extension-agnostic (`_positives.<ext>`) so a future scanner whose
# corpus is e.g. `.txt`/`.toml` is still derived, not falsely failed.
# Callers dedupe distinct basenames and refuse to guess when more than
# one is present (see _derive_negatives_basename) — a silent false-pass
# off a sibling scanner's basename is worse than a loud false-fail.
_POSITIVES_RE = re.compile(r"[A-Za-z0-9_]+_positives\.[A-Za-z0-9]+")


def _non_exempt_scanner_names() -> list[str]:
    """Scanner module stems under espalier/scanners/, minus __init__ and
    the negative-axis exemptions."""
    return sorted(
        p.stem
        for p in SCANNER_DIR.glob("*.py")
        if p.name != "__init__.py" and p.stem not in NEGATIVE_CORPUS_EXEMPT
    )


def _derive_negatives_basename(test_body: str) -> tuple[str | None, str | None]:
    """Return (negatives_basename, error_reason) — exactly one is non-None.

    Derived from the DISTINCT positives-fixture basenames the test file
    references as string literals:
      * zero references   -> (None, "references no ... basename")
      * one reference     -> (`<x>_negatives.<ext>`, None)
      * two or more       -> (None, "references multiple distinct ...")

    The multi-reference case refuses to guess: `_POSITIVES_RE.search`
    used to take the FIRST match, so a future test whose docstring
    mentioned a sibling scanner's positives basename ("mirrors
    test_prints_positives.py") before its own would derive the SIBLING's
    negatives path — which exists — and false-pass while its own corpus
    is missing. Deduping and refusing on ambiguity turns that silent
    false-pass into a loud false-fail. The live tree has exactly one
    distinct positives basename per scanner, so this stays green.
    """
    basenames = sorted(set(_POSITIVES_RE.findall(test_body)))
    if not basenames:
        return None, "references no `<name>_positives.*` fixture basename"
    if len(basenames) > 1:
        return None, (
            f"references multiple distinct positives basenames {basenames}; "
            f"cannot disambiguate which is this scanner's own corpus"
        )
    return basenames[0].replace("_positives.", "_negatives."), None


def _scanner_negative_status(name: str, repo_root: Path) -> str | None:
    """Return None when scanner `name` has a complete must-NOT-trip
    corpus, else a human-readable reason describing the gap.

    Pure function over the filesystem so the hermetic earn-the-red test
    can drive it against a synthetic tree (see
    test_contract_detects_each_gap).
    """
    test_file = repo_root / "tests" / f"test_scanner_{name}.py"
    if not test_file.exists():
        return (
            f"missing tests/test_scanner_{name}.py — add the scanner's "
            f"earn-the-gate + must-NOT-trip tests (TP-105/TP-156 pattern)"
        )
    body = test_file.read_text(encoding="utf-8")
    # Require an actual function def, not a bare substring: a comment or
    # docstring mention of `test_does_not_trip` must not satisfy the
    # contract (the real coverage is the def the suite then runs).
    if "def test_does_not_trip" not in body:
        return (
            f"tests/test_scanner_{name}.py has no `def test_does_not_trip*` "
            f"function — the must-NOT-trip contract. Add a direct-call "
            f"negative test asserting the scanner returns zero findings on "
            f"its negatives corpus."
        )
    neg_basename, derive_error = _derive_negatives_basename(body)
    if neg_basename is None:
        return (
            f"tests/test_scanner_{name}.py {derive_error}, so the negatives "
            f"path cannot be derived. Keep a single positives reference so "
            f"the negative corpus mirrors it."
        )
    neg_rel = f"tests/fixtures/{neg_basename}"
    neg_path = repo_root / "tests" / "fixtures" / neg_basename
    if not neg_path.exists():
        return (
            f"missing negatives corpus {neg_rel} (derived from the positives "
            f"reference in tests/test_scanner_{name}.py). Add the "
            f"clean-but-tempting must-NOT-trip fixture."
        )
    if name in PRECISION_BOUNDARY_REQUIRED:
        if PRECISION_BOUNDARY_MARKER not in neg_path.read_text(encoding="utf-8"):
            return (
                f"{neg_rel} has no `{PRECISION_BOUNDARY_MARKER}` marker (§13.9). "
                f"{name}'s matcher over-fires, so its negative corpus must label "
                f"the near-miss its matcher could over-fire on. Add a marker line "
                f"NAMING the boundary class (do NOT quote the live trigger token) "
                f"and confirm the scanner stays silent on it."
            )
    return None


class TestEveryScannerHasNegativeCorpus:
    """Walk espalier/scanners/, assert each non-exempt scanner has a
    derived negatives fixture AND a `test_does_not_trip*` function."""

    @pytest.mark.parametrize(
        "scanner_name", _non_exempt_scanner_names(), ids=lambda n: n
    )
    def test_scanner_has_negative_corpus(self, scanner_name: str) -> None:
        reason = _scanner_negative_status(scanner_name, REPO_ROOT)
        assert reason is None, reason

    def test_registry_is_not_vacuous(self) -> None:
        """Guard against the parametrize set silently collapsing to empty
        (e.g. a glob/exemption bug), which would make every assertion above
        vacuously pass. Anchor on three scanners that must always be in
        scope. Mirrors the vacuous-registry idiom used elsewhere."""
        checked = set(_non_exempt_scanner_names())
        anchors = {"subprocess_contracts", "filesystem_contracts", "magic_depth"}
        assert anchors <= checked, (
            f"negative-corpus parity registry is missing expected scanners "
            f"{sorted(anchors - checked)}; the parametrize set "
            f"({sorted(checked)}) collapsed — the contract would pass "
            f"vacuously."
        )

    def test_canon_verifier_is_exempt_not_flagged(self) -> None:
        """canon_verifier has no fixture corpus by design; it must be
        exempt on the negative axis, never parametrized."""
        assert "canon_verifier" in NEGATIVE_CORPUS_EXEMPT
        assert "canon_verifier" not in _non_exempt_scanner_names()

    def test_contract_detects_every_gap(self, tmp_path: Path) -> None:
        """Hermetic earn-the-red: drive the core predicate against a
        synthetic tree through EVERY failure branch, then the satisfied
        state. Proves the contract is non-vacuous — it goes RED for each
        distinct gap and only clears once a complete corpus exists.

        Branches exercised, in order: (1) no test file, (2) no
        `def test_does_not_trip`, (3) no positives reference to derive
        from, (4) ambiguous — two distinct positives basenames (the
        sibling-cross-reference false-pass guard), (5) negatives fixture
        missing, (6) satisfied."""
        tests = tmp_path / "tests"
        fixtures = tests / "fixtures"
        fixtures.mkdir(parents=True)
        test_file = tests / "test_scanner_demo.py"

        # (1) no test file at all.
        assert _scanner_negative_status("demo", tmp_path) is not None

        # (2) test file exists but has no `def test_does_not_trip`.
        test_file.write_text(
            'FIXTURE = "tests/fixtures/test_demo_positives.py"\n'
            "def test_earn_the_gate_demo():\n    pass\n",
            encoding="utf-8",
        )
        reason = _scanner_negative_status("demo", tmp_path)
        assert reason is not None and "test_does_not_trip" in reason

        # (3) has the def but NO positives reference to derive from.
        test_file.write_text(
            "def test_does_not_trip_on_negatives():\n    pass\n",
            encoding="utf-8",
        )
        reason = _scanner_negative_status("demo", tmp_path)
        assert reason is not None and "references no" in reason

        # (4) ambiguous: a sibling scanner's positives basename appears in
        # the docstring BEFORE this scanner's own — the first-match
        # false-pass scenario. The guard must refuse to guess.
        test_file.write_text(
            '"""This contract mirrors test_prints_positives.py for the '
            'convention."""\n'
            'FIXTURE = "tests/fixtures/test_demo_positives.py"\n'
            "def test_does_not_trip_on_negatives():\n    pass\n",
            encoding="utf-8",
        )
        reason = _scanner_negative_status("demo", tmp_path)
        assert reason is not None and "multiple distinct" in reason

        # (5) def + a single positives reference, but the derived
        # negatives fixture does not exist.
        test_file.write_text(
            'FIXTURE = "tests/fixtures/test_demo_positives.py"\n'
            "def test_does_not_trip_on_negatives():\n    pass\n",
            encoding="utf-8",
        )
        reason = _scanner_negative_status("demo", tmp_path)
        assert reason is not None and "test_demo_negatives.py" in reason

        # (6) satisfied for a NON-required scanner: create the derived negatives
        # fixture -> clears (no precision-boundary marker needed).
        (fixtures / "test_demo_negatives.py").write_text("", encoding="utf-8")
        assert _scanner_negative_status("demo", tmp_path) is None

        # (7) §13.9: a REQUIRED (over-firing) scanner whose corpus lacks the
        # precision-boundary marker must RED on the marker branch, then clear
        # once the marker is present. Insert `demo` into the required set for
        # this assertion only — a module-attribute rebind so the predicate (which
        # reads the module global) sees it; the `finally` restores it.
        import sys

        mod = sys.modules[__name__]
        original = mod.PRECISION_BOUNDARY_REQUIRED
        mod.PRECISION_BOUNDARY_REQUIRED = original | {"demo"}
        try:
            reason = _scanner_negative_status("demo", tmp_path)
            assert reason is not None and "precision-boundary:" in reason
            (fixtures / "test_demo_negatives.py").write_text(
                "<!-- precision-boundary: synthetic boundary class -->\n",
                encoding="utf-8",
            )
            assert _scanner_negative_status("demo", tmp_path) is None
        finally:
            mod.PRECISION_BOUNDARY_REQUIRED = original
