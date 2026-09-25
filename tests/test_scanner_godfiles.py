"""Pin the godfiles scanner's behavioral contract.

Earn-the-gate: synthetic fixture above DEFAULT_THRESHOLD must surface
in outline_file's reported LOC count. Live-scan exemption:
EXEMPT_PREFIXES keeps the fixture out of `espalier scan godfiles`'s
files list and outlines dict.

TP-105 / TP-143 / FM-7 §1.7 close.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from espalier.scanners import godfiles as scn


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_godfiles_positives.py"
NEG_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_godfiles_negatives.py"


def test_earn_the_gate_detects_every_fixture_shape() -> None:
    """outline_file the fixture directly and confirm reported LOC
    exceeds DEFAULT_THRESHOLD. The fixture is synthetic boilerplate
    above 750 lines; if the threshold or fixture is trimmed this
    fails."""
    outline = scn.outline_file(str(FIXTURE_PATH))
    assert outline["loc"] > scn.DEFAULT_THRESHOLD, (
        f"earn-the-gate: fixture has {outline['loc']} lines, expected "
        f">{scn.DEFAULT_THRESHOLD}. Fixture may have been trimmed."
    )


def test_does_not_trip_on_negatives() -> None:
    """Must-NOT-trip: the negatives corpus is structurally tempting
    (three top-level classes, multiple naming-prefix function clusters,
    dunder helpers) but its LOC sits well under DEFAULT_THRESHOLD, so
    outline_file -- the same direct-call entrypoint the earn-the-gate
    test uses -- must NOT report it as above threshold. Direct-call on
    the fixture path is immune to live-tree drift."""
    outline = scn.outline_file(str(NEG_FIXTURE_PATH))
    assert outline["loc"] < scn.DEFAULT_THRESHOLD, (
        f"negatives corpus has {outline['loc']} lines, expected "
        f"<{scn.DEFAULT_THRESHOLD}. A clean fixture must stay under "
        f"threshold; trim it back below the godfile boundary."
    )


def test_fixture_skipped_by_live_scan() -> None:
    """EXEMPT_PREFIXES added in TP-143 must keep the fixture out of
    both `files` and `outlines` in scan_repo's output."""
    report = scn.scan_repo(str(REPO_ROOT))
    fixture_rel = "tests/fixtures/test_godfiles_positives.py"
    fixture_rows = [
        r for r in report["files"]
        if fixture_rel in r["path"].replace("\\", "/")
    ]
    assert fixture_rows == [], (
        "EXEMPT_PREFIXES did not skip the fixture from scan_repo files."
    )
    # outlines only contains top-10 above-threshold files; primary
    # guard is the files[] check above. This is a secondary witness.
    assert fixture_rel not in report["outlines"], (
        "Fixture appeared in outlines dict despite EXEMPT_PREFIXES."
    )


def test_main_md_count_matches_json_above_threshold(tmp_path, monkeypatch) -> None:
    """TP-174b R23: main()'s Markdown report ``Files above threshold`` count
    must equal the JSON ``above_threshold``. Both paths now filter
    EXEMPT_PREFIXES; pre-fix the MD render used unfiltered build_report rows
    and over-counted tests/fixtures relative to the JSON."""
    out_json = tmp_path / "godfiles.json"
    out_md = tmp_path / "godfiles.md"
    monkeypatch.setattr(sys, "argv", [
        "godfiles", "--root", str(REPO_ROOT),
        "--out", str(out_json), "--md", str(out_md),
    ])
    assert scn.main() == 0
    report = json.loads(out_json.read_text(encoding="utf-8"))
    m = re.search(r"Files above threshold: (\d+) / \d+", out_md.read_text(encoding="utf-8"))
    assert m, "MD report missing the 'Files above threshold' header line"
    assert int(m.group(1)) == report["above_threshold"], (
        f"MD count {m.group(1)} != JSON above_threshold "
        f"{report['above_threshold']} — EXEMPT_PREFIXES filter drift between "
        f"the MD render and scan_repo."
    )
