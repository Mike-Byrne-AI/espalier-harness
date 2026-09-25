"""Pin TP-157 157-D cross-scanner composition + the report-shape SoT.

Why this contract exists. The 10 per-scanner reports expose SIX distinct
path-extraction shapes (findings[].file / .path / .caller_path / .writer_path,
godfiles files[].path, perf/test_loosening results[].file). A naive
``report["findings"][i]["path"]`` walk catches only three scanners
(convergence_theater, magic_depth, retired_vocab) and silently drops the
other seven — a divergence this test pins per scanner. Two traps the test
guards explicitly:

  - godfiles ``files`` lists EVERY scanned file, not just the big ones; without
    the loc>=threshold filter every file reads as a godfiles hit (false
    intersections). This test proves a below-threshold file does NOT count.
  - the 'godfiles_report.json IS read' criterion is a blind oracle if it only
    asserts the file is opened; here we assert an above-threshold godfiles file
    co-flagged by another scanner actually PROPAGATES into intersect() output.

``scan_summary.json`` (counts-only) must never contribute a phantom path.
"""
from __future__ import annotations

import argparse
import json

from espalier import cli, scan_composition


def _write(reports, name, payload):
    reports.mkdir(parents=True, exist_ok=True)
    (reports / name).write_text(json.dumps(payload), encoding="utf-8")


class TestIntersect:
    def test_file_hit_by_two_scanners_appears(self, tmp_path):
        reports = tmp_path / "reports"
        _write(reports, "scan_magic_depth.json", {"findings": [{"path": "x.py", "lineno": 1}]})
        _write(reports, "scan_convergence_theater.json", {"findings": [{"path": "x.py", "lineno": 2}]})
        result = scan_composition.intersect(reports)
        assert result == {"x.py": ["convergence_theater", "magic_depth"]}

    def test_single_scanner_file_excluded(self, tmp_path):
        reports = tmp_path / "reports"
        _write(reports, "scan_magic_depth.json", {"findings": [{"path": "solo.py", "lineno": 1}]})
        assert scan_composition.intersect(reports) == {}

    def test_filesystem_contracts_recursive_walks_path_collected(self, tmp_path):
        """TP-313b ITEM F-3: filesystem_contracts nests a second finding class
        under ``recursive_walks.findings[].path`` (the bare-rglob recurrence
        guard). A file tripped ONLY by a nested recursive_walks finding must
        still be collected — pre-fix _extract_paths read only top-level
        ``findings[]``, silently under-collecting it for the cross-scanner join."""
        reports = tmp_path / "reports"
        _write(reports, "scan_filesystem_contracts.json", {
            "count": 0,
            "findings": [],
            "recursive_walks": {
                "count": 1,
                "findings": [{
                    "path": "walk.py", "lineno": 3, "call": "rglob",
                    "severity": "WARN", "explanation": "bare rglob",
                }],
            },
        })
        by_scanner = scan_composition.report_finding_paths(reports)
        assert by_scanner["filesystem_contracts"] == {"walk.py"}

    def test_divergent_path_keys_all_resolve(self, tmp_path):
        """subprocess_contracts(caller_path) + filesystem_contracts(writer_path)
        on the same file must intersect — the two non-`path`/`file` key shapes."""
        reports = tmp_path / "reports"
        _write(reports, "scan_subprocess_contracts.json",
               {"findings": [{"caller_path": "dual.py", "caller_lineno": 1}]})
        _write(reports, "scan_filesystem_contracts.json",
               {"findings": [{"writer_path": "dual.py", "writer_lineno": 2}]})
        result = scan_composition.intersect(reports)
        assert result == {"dual.py": ["filesystem_contracts", "subprocess_contracts"]}

    def test_exceptions_prints_use_file_key(self, tmp_path):
        reports = tmp_path / "reports"
        _write(reports, "scan_exceptions.json", {"findings": [{"file": "e.py", "lineno": 1}]})
        _write(reports, "scan_prints.json", {"findings": [{"file": "e.py", "lineno": 2}]})
        assert scan_composition.intersect(reports) == {"e.py": ["exceptions", "prints"]}

    def test_scan_summary_never_contributes(self, tmp_path):
        """A path named inside scan_summary.json must NOT create a phantom 2nd
        hit. Here ghost.py is flagged by exactly one real scanner; if summary
        were read it would appear (2 hits) — it must stay absent."""
        reports = tmp_path / "reports"
        _write(reports, "scan_magic_depth.json", {"findings": [{"path": "ghost.py", "lineno": 1}]})
        _write(reports, "scan_summary.json",
               {"status": "scanned", "path": "ghost.py", "file": "ghost.py"})
        assert scan_composition.intersect(reports) == {}


class TestGodfilesShape:
    """The godfiles files[] over-collection trap (N2) + blind-oracle fix (N3)."""

    def test_above_threshold_godfiles_file_propagates(self, tmp_path):
        reports = tmp_path / "reports"
        _write(reports, "godfiles_report.json", {
            "threshold": 500,
            "files": [{"path": "big.py", "loc": 900}, {"path": "small.py", "loc": 10}],
        })
        _write(reports, "scan_prints.json", {"findings": [{"file": "big.py", "lineno": 3}]})
        result = scan_composition.intersect(reports)
        # big.py (above threshold) co-flagged by prints -> appears WITH godfiles.
        assert result == {"big.py": ["godfiles", "prints"]}

    def test_below_threshold_godfiles_file_not_counted(self, tmp_path):
        reports = tmp_path / "reports"
        _write(reports, "godfiles_report.json", {
            "threshold": 500,
            "files": [{"path": "small.py", "loc": 10}],
        })
        _write(reports, "scan_prints.json", {"findings": [{"file": "small.py", "lineno": 1}]})
        # small.py is below the godfiles threshold -> godfiles does NOT flag it,
        # so it has only 1 scanner and must not intersect.
        assert scan_composition.intersect(reports) == {}

    def test_godfiles_paths_present_in_reader(self, tmp_path):
        reports = tmp_path / "reports"
        _write(reports, "godfiles_report.json", {
            "threshold": 100,
            "files": [{"path": "huge.py", "loc": 200}],
        })
        paths = scan_composition.report_finding_paths(reports)
        assert paths["godfiles"] == {"huge.py"}


class TestPathFormParity:
    """Regression (final-review F-composition): exceptions/prints/perf_smells
    write ABSOLUTE file paths while CT/MD/SC/RV write RELATIVE ones. Without
    relativizing, a file co-flagged by one of each NEVER intersects (silent
    under-collection). reports/ lives at repo_root/reports/, so paths are
    relativized against reports_dir.parent."""

    def test_absolute_and_relative_paths_intersect(self, tmp_path):
        reports = tmp_path / "reports"
        abs_path = str(tmp_path / "pkg" / "m.py")  # as exceptions/prints emit
        _write(reports, "scan_prints.json", {"findings": [{"file": abs_path, "lineno": 6}]})
        _write(reports, "scan_magic_depth.json", {"findings": [{"path": "pkg/m.py", "lineno": 1}]})
        result = scan_composition.intersect(reports)
        # Both must relativize to "pkg/m.py" and intersect — pre-fix they did NOT.
        assert result == {"pkg/m.py": ["magic_depth", "prints"]}

    def test_absolute_path_relativized_in_reader(self, tmp_path):
        reports = tmp_path / "reports"
        _write(reports, "scan_exceptions.json",
               {"findings": [{"file": str(tmp_path / "a" / "b.py"), "lineno": 1}]})
        paths = scan_composition.report_finding_paths(reports)
        assert paths["exceptions"] == {"a/b.py"}  # repo-relative, not absolute


class TestPerfAndTestLooseningShape:
    def test_perf_zero_hits_excluded(self, tmp_path):
        reports = tmp_path / "reports"
        _write(reports, "scan_perf_smells.json", {
            "results": [{"file": "hot.py", "total_hits": 4}, {"file": "cold.py", "total_hits": 0}],
        })
        paths = scan_composition.report_finding_paths(reports)
        assert paths["perf_smells"] == {"hot.py"}  # cold.py (0 hits) excluded

    def test_test_loosening_count_zero_excluded(self, tmp_path):
        reports = tmp_path / "reports"
        _write(reports, "scan_test_loosening.json", {
            "results": [{"file": "loose.py", "count": 2}, {"file": "tight.py", "count": 0}],
        })
        paths = scan_composition.report_finding_paths(reports)
        assert paths["test_loosening"] == {"loose.py"}


class TestRobustness:
    def test_missing_reports_dir_returns_empty(self, tmp_path):
        assert scan_composition.intersect(tmp_path / "nope") == {}

    def test_malformed_report_skipped(self, tmp_path):
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "scan_magic_depth.json").write_text("{not json", encoding="utf-8")
        _write(reports, "scan_prints.json", {"findings": [{"file": "ok.py", "lineno": 1}]})
        # No crash; the good report still parses.
        assert scan_composition.report_finding_paths(reports).get("prints") == {"ok.py"}


class TestCmdScanAdvisory:
    """Integration: cross-scanner advisory is stdout (CLI layer) and never
    changes the exit code."""

    def test_scan_returns_zero(self, tmp_path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        assert cli.cmd_scan(argparse.Namespace(repo=str(tmp_path), baseline=False)) == 0
