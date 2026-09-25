"""Cross-scanner contract: every scanner under espalier/scanners/
(excluding canon_verifier) MUST have a corresponding earn-the-gate test.

FM-7 §1.7 close: without this contract, a new scanner could ship
without a positive-case fixture, recreating the gate tuning-to-HEAD
blind spot the rest of TP-143 closes.

Sibling: tests/test_scanners.py::TestScannerExemptPrefixesParity
(TP-139) -- same shape, different aspect (exemption presence vs
earn-the-gate test presence).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNER_DIR = REPO_ROOT / "espalier" / "scanners"
TEST_DIR = REPO_ROOT / "tests"

# canon_verifier uses a different contract pattern
# (tests/test_canon_verifier_contract.py covers per-shape detection
# via the CLAIM_SURFACES + CLAIM_DISCOVERERS registry, not via a
# positive-case fixture).
EARN_THE_GATE_EXEMPT = frozenset({"canon_verifier"})


class TestEveryScannerHasEarnTheGate:
    """Walk espalier/scanners/, assert each .py file (non-exempt) has a
    paired tests/test_scanner_<name>.py with a function whose name
    starts with `test_earn_the_gate`."""

    @pytest.mark.parametrize("scanner_path", [
        p for p in sorted(SCANNER_DIR.glob("*.py"))
        if p.name != "__init__.py" and p.stem not in EARN_THE_GATE_EXEMPT
    ], ids=lambda p: p.stem)
    def test_scanner_has_earn_the_gate(self, scanner_path: Path) -> None:
        name = scanner_path.stem
        test_file = TEST_DIR / f"test_scanner_{name}.py"
        assert test_file.exists(), (
            f"Scanner espalier/scanners/{name}.py has no earn-the-gate test "
            f"({test_file}). Add a tests/fixtures/test_{name}_positives.* "
            f"fixture and a tests/test_scanner_{name}.py::test_earn_the_gate_* "
            f"per TP-105/TP-143 pattern."
        )
        body = test_file.read_text(encoding="utf-8")
        # TP-184 B9: require the `def test_earn_the_gate` token, not a bare
        # `test_earn_the_gate` name mention (a docstring/comment that merely names
        # the function no longer satisfies the contract). This is still a substring
        # check, not an AST parse — exactly symmetric with the sibling negative-
        # corpus parity check in test_scanner_negative_corpus_parity.py (which
        # requires `def test_does_not_trip`); both trade full exactness for a one-
        # token tightening that catches the realistic regression (named-but-undef).
        assert "def test_earn_the_gate" in body, (
            f"{test_file} exists but contains no `def test_earn_the_gate*` "
            f"function. Earn-the-gate is the named contract; naming it "
            f"differently (or only mentioning it in prose) breaks the "
            f"cross-scanner parity check."
        )
