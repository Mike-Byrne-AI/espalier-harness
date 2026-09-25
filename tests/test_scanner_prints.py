"""Pin the prints scanner's behavioral contract.

Earn-the-gate: every bare print() call in the fixture surfaces.
Live-scan exemption: EXEMPT_PREFIXES keeps the fixture out of normal
`espalier scan prints` runs.

TP-105 / TP-143 / FM-7 §1.7 close.
"""
from __future__ import annotations

from pathlib import Path

from espalier.scanners import prints as scn


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_prints_positives.py"
NEG_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_prints_negatives.py"


def test_earn_the_gate_detects_every_fixture_shape() -> None:
    """scan_file the fixture directly; assert each documented print
    call produces a finding."""
    findings = scn.scan_file(str(FIXTURE_PATH))
    assert len(findings) >= 3, (
        f"earn-the-gate: expected >=3 fixture findings, got "
        f"{len(findings)}. Fixture has 3 distinct print invocations."
    )


def test_does_not_trip_on_negatives() -> None:
    """scan_file the negatives fixture directly; assert ZERO findings.

    The negatives corpus holds clean-but-tempting constructs (logging,
    sys.stdout.write, pprint, print-as-attribute/string/shadowed-name)
    that sit near the scanner's boundary but contain no bare print()
    Name call. This proves the scanner STAYS SILENT on clean input,
    complementing the earn-the-gate FIRES proof (TP-156 Tier 1).
    """
    findings = scn.scan_file(str(NEG_FIXTURE_PATH))
    assert findings == [], (
        f"prints scanner over-fired on the negatives corpus: expected "
        f"0 findings, got {len(findings)}: {findings}"
    )


def test_fixture_skipped_by_live_scan() -> None:
    """EXEMPT_PREFIXES added in TP-143 must keep the fixture out of
    live scans."""
    report = scn.scan_repo(str(REPO_ROOT))
    fixture_rel = "tests/fixtures/test_prints_positives.py"
    fixture_findings = [
        f for f in report["findings"]
        if fixture_rel in f["file"].replace("\\", "/")
    ]
    assert fixture_findings == [], (
        f"EXEMPT_PREFIXES did not skip the fixture. Found "
        f"{len(fixture_findings)} fixture finding(s)."
    )
