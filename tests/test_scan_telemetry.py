"""Pin the TP-157 157-A scan-telemetry history substrate.

Why this contract exists: ``scan_summary.json`` is overwritten every run, so
the harness could never answer "which self-gov scanner is wallpaper (never
fires) vs noisy (always exempted) over time." 157-A adds an append-only
``scan_telemetry.jsonl`` history beside it. Without this test a refactor could
silently regress the append (truncating instead of appending), break the
round-trip read, or let one malformed tail line poison the whole history —
none of which the point-in-time summary would surface. The integration test
also guards the invariant that wiring telemetry into ``cmd_scan`` does NOT
change the existing ``scan_summary.json`` shape.
"""
from __future__ import annotations

import argparse
import json

from espalier import cli, scan_telemetry

# The 11 scanners cmd_scan drives; one telemetry row each per run.
_SCANNERS = [
    "exceptions", "prints", "godfiles", "perf_smells", "test_loosening",
    "convergence_theater", "subprocess_contracts", "filesystem_contracts",
    "magic_depth", "retired_vocab", "encoding_contracts",
]


def _counts(fires: int = 1, exemptions: int = 0) -> dict:
    return {s: {"fires": fires, "exemptions": exemptions} for s in _SCANNERS}


class TestAppendRun:
    def test_writes_one_row_per_scanner(self, tmp_path):
        n = scan_telemetry.append_run(tmp_path, "2026-06-02T00:00:00+00:00", _counts())
        assert n == 11
        records = scan_telemetry.read_history(tmp_path)
        assert len(records) == 11
        assert {r["scanner"] for r in records} == set(_SCANNERS)

    def test_two_runs_are_additive(self, tmp_path):
        """The pack's 157-A pass criterion: >=20 lines after two runs."""
        scan_telemetry.append_run(tmp_path, "2026-06-02T00:00:00+00:00", _counts())
        scan_telemetry.append_run(tmp_path, "2026-06-02T01:00:00+00:00", _counts(fires=2))
        records = scan_telemetry.read_history(tmp_path)
        assert len(records) == 22
        # both run timestamps survive — history, not a snapshot.
        assert {r["run_ts"] for r in records} == {
            "2026-06-02T00:00:00+00:00", "2026-06-02T01:00:00+00:00"
        }

    def test_round_trips_fires_and_exemptions(self, tmp_path):
        counts = {"magic_depth": {"fires": 7, "exemptions": 3}}
        scan_telemetry.append_run(tmp_path, "T", counts)
        (rec,) = scan_telemetry.read_history(tmp_path)
        assert rec == {"run_ts": "T", "scanner": "magic_depth", "fires": 7, "exemptions": 3}

    def test_history_is_capped_to_max_rows(self, tmp_path):
        """Append-only history stays bounded: once past _MAX_TELEMETRY_ROWS only
        the most-recent rows survive, and they are the LATEST (highest run_ts)."""
        one = {"prints": {"fires": 0, "exemptions": 0}}  # 1 row/run
        runs = scan_telemetry._MAX_TELEMETRY_ROWS + 25
        for i in range(runs):
            scan_telemetry.append_run(tmp_path, f"T{i:05d}", one)
        records = scan_telemetry.read_history(tmp_path)
        assert len(records) == scan_telemetry._MAX_TELEMETRY_ROWS
        # the survivors are the tail (newest), not the head
        assert records[-1]["run_ts"] == f"T{runs - 1:05d}"
        assert records[0]["run_ts"] == f"T{runs - scan_telemetry._MAX_TELEMETRY_ROWS:05d}"

    def test_empty_counts_writes_nothing(self, tmp_path):
        assert scan_telemetry.append_run(tmp_path, "T", {}) == 0
        assert scan_telemetry.read_history(tmp_path) == []

    def test_creates_reports_dir_if_absent(self, tmp_path):
        target = tmp_path / "nested" / "reports"
        assert not target.exists()
        scan_telemetry.append_run(target, "T", {"prints": {"fires": 0, "exemptions": 0}})
        assert (target / scan_telemetry.TELEMETRY_FILENAME).exists()


class TestReadHistory:
    def test_absent_returns_empty(self, tmp_path):
        assert scan_telemetry.read_history(tmp_path) == []

    def test_skips_malformed_line(self, tmp_path):
        """A partial-write tail or hand-edit must not poison the whole read."""
        scan_telemetry.append_run(tmp_path, "T", {"prints": {"fires": 1, "exemptions": 0}})
        path = tmp_path / scan_telemetry.TELEMETRY_FILENAME
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("{not valid json\n")
            fh.write('{"run_ts": "T2", "scanner": "magic_depth", "fires": 0, "exemptions": 0}\n')
        records = scan_telemetry.read_history(tmp_path)
        assert len(records) == 2  # the good first line + the good last line
        assert {r["scanner"] for r in records} == {"prints", "magic_depth"}


class TestCmdScanWiring:
    """Integration: cmd_scan appends a 10-row telemetry run AND leaves the
    point-in-time scan_summary.json shape unchanged (no duplication)."""

    def _run_scan(self, repo):
        return cli.cmd_scan(argparse.Namespace(repo=str(repo)))

    def _python_repo(self, tmp_path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "mod.py").write_text(
            "def f(x):\n    return x + 1\n", encoding="utf-8"
        )
        return tmp_path

    def test_two_scans_yield_twenty_telemetry_rows(self, tmp_path):
        repo = self._python_repo(tmp_path)
        assert self._run_scan(repo) == 0
        assert self._run_scan(repo) == 0
        records = scan_telemetry.read_history(repo / "reports")
        assert len(records) >= 20
        # every scanner appears in the history
        assert set(_SCANNERS).issubset({r["scanner"] for r in records})

    def test_summary_shape_preserved(self, tmp_path):
        repo = self._python_repo(tmp_path)
        assert self._run_scan(repo) == 0
        summary = json.loads((repo / "reports" / "scan_summary.json").read_text(encoding="utf-8"))
        assert summary["status"] == "scanned"
        # the 11 count keys cmd_scan writes remain present.
        for key in ("exceptions", "prints", "large_files", "perf_hotspots",
                    "test_loosening", "convergence_theater", "subprocess_contracts",
                    "filesystem_contracts", "magic_depth", "retired_vocab",
                    "encoding_contracts"):
            assert key in summary
