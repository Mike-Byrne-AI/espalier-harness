# pytest-marker: default-unit
"""TP-217c — the five espalier-pinned scanners are gated to the self-host repo.

On an adopter (non-self-host) repo `cmd_scan` must EMIT empty reports for
subprocess_contracts / filesystem_contracts / magic_depth / retired_vocab /
encoding_contracts (count 0, findings []) rather than walking the repo — but
must NOT drop the report files, the 11 summary count keys, or the 11 telemetry rows. The
precision boundary is "report 0, don't vanish": the summary/telemetry
contracts (test_scan_telemetry.py) pin all 11, so an over-aggressive gate
that removed keys/rows would regress them.
"""
from __future__ import annotations

import argparse
import json

from espalier import cli, surface_contract


def _adopter_python_repo(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(
        "def f(x):\n    return x + 1\n", encoding="utf-8"
    )
    return tmp_path


def test_adopter_repo_is_not_self_host(tmp_path):
    repo = _adopter_python_repo(tmp_path)
    assert not surface_contract.is_self_host_repo(repo)


def test_pinned_scanners_emit_empty_reports_on_adopter(tmp_path):
    repo = _adopter_python_repo(tmp_path)
    assert cli.cmd_scan(argparse.Namespace(repo=str(repo))) == 0
    reports = repo / "reports"
    for name in (
        "scan_subprocess_contracts.json",
        "scan_filesystem_contracts.json",
        "scan_magic_depth.json",
        "scan_retired_vocab.json",
        "scan_encoding_contracts.json",
    ):
        path = reports / name
        assert path.exists(), f"{name} must still be written on an adopter repo"
        report = json.loads(path.read_text(encoding="utf-8"))
        assert report["count"] == 0
        assert report["findings"] == []


def test_gate_does_not_drop_summary_keys_on_adopter(tmp_path):
    repo = _adopter_python_repo(tmp_path)
    assert cli.cmd_scan(argparse.Namespace(repo=str(repo))) == 0
    summary = json.loads((repo / "reports" / "scan_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "scanned"
    for key in (
        "exceptions", "prints", "large_files", "perf_hotspots",
        "test_loosening", "convergence_theater", "subprocess_contracts",
        "filesystem_contracts", "magic_depth", "retired_vocab",
        "encoding_contracts",
    ):
        assert key in summary
    # the five gated scanners report 0 on an adopter
    for key in ("subprocess_contracts", "filesystem_contracts",
                "magic_depth", "retired_vocab", "encoding_contracts"):
        assert summary[key] == 0


def test_gate_keeps_the_encoding_scanners_pragma_walks_off_an_adopter(tmp_path):
    """The report is gated, and so are the two pragma walks that feed the
    overrides corpus: encoding_contracts is the one scanner that walks the whole
    root, and an adopter tree gets neither its findings nor its walk."""
    repo = _adopter_python_repo(tmp_path)
    (repo / "pkg" / "ok.py").write_text(
        "from pathlib import Path\n"
        "# encoding-locale-ok: an adopter pragma that must never be counted here\n"
        "x = Path('f').read_text(encoding='ascii')\n",
        encoding="utf-8",
    )
    assert cli.cmd_scan(argparse.Namespace(repo=str(repo))) == 0
    overrides = json.loads((repo / "reports" / "scan_overrides.json").read_text(encoding="utf-8"))
    assert not [o for o in overrides["overrides"] if o["scanner"] == "encoding_contracts"]
    from espalier import scan_telemetry
    rows = [r for r in scan_telemetry.read_history(repo / "reports") if r["scanner"] == "encoding_contracts"]
    assert rows and all(r["fires"] == 0 and r["exemptions"] == 0 for r in rows)
