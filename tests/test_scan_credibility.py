"""Pin TP-157 157-B (override-reason corpus) + 157-C (wallpaper budget).

Why this contract exists. The three pragma scanners discard the override
*reason* ``PRAGMA_RE`` captures — exactly the labeled false-positive-budget
data a credibility pass would consume. 157-B adds ``collect_pragmas`` beside
each ``count_pragmas`` to keep that reason. The load-bearing invariant is
``len(collect_pragmas(root)) == count_pragmas(root)`` PER SCANNER, under each
scanner's OWN divergent scope — a uniform walk would silently break it for
convergence_theater (``tests/`` only) and subprocess_contracts (excludes
``tests/``). Without the cross-scope fixture below, an all-``espalier/`` test
would pass vacuously for convergence_theater (which never walks ``espalier/``),
hiding that divergence. 157-C's wallpaper report reads telemetry history and
must NOT exit non-zero — it is advisory; a regression to ``exit 1`` would gate
``espalier scan`` on a threshold calibrated against one tree.
"""
from __future__ import annotations

import argparse
import json

from espalier import cli, scan_credibility, scan_telemetry
from espalier.scanners import convergence_theater as ct
from espalier.scanners import magic_depth as md
from espalier.scanners import subprocess_contracts as sc

# Reasons must be >=12 chars to satisfy each scanner's PRAGMA_RE `(.{12,})`.
_CT_PRAGMA = "# theater: ok cross-scope-fixture reason here"
_SC_PRAGMA = "# subprocess-contract: ok cross-scope-fixture reason"
_MD_PRAGMA = "# magic-depth: ok cross-scope-fixture reason here"


def _plant_cross_scope_repo(root):
    """Construct a tmp repo exercising the three divergent scopes.

    tests/test_planted.py : a theater: pragma (CT scope) + a magic-depth:
                            pragma (MD also walks tests/).
    espalier/planted.py   : a subprocess-contract: pragma (SC scope) + a
                            magic-depth: pragma (MD also walks espalier/).
    tests/fixtures/...    : a theater: pragma that EXEMPT_PREFIXES excludes.
    """
    (root / "tests").mkdir()
    (root / "tests" / "fixtures").mkdir()
    (root / "espalier").mkdir()
    (root / "tests" / "test_planted.py").write_text(
        f"{_CT_PRAGMA}\nassert 1 == 1\n{_MD_PRAGMA}\nx = p.parents[3]\n",
        encoding="utf-8",
    )
    (root / "espalier" / "planted.py").write_text(
        f"{_SC_PRAGMA}\nrun_thing()\n{_MD_PRAGMA}\ny = q.parents[4]\n",
        encoding="utf-8",
    )
    # Excluded: a theater pragma under tests/fixtures/ must be counted by NEITHER
    # count_pragmas nor collect_pragmas (EXEMPT_PREFIXES).
    (root / "tests" / "fixtures" / "test_excluded.py").write_text(
        f"{_CT_PRAGMA}\nassert 2 == 2\n", encoding="utf-8",
    )
    return root


class TestOverrideCorpus:
    """157-B: collect_pragmas mirrors count_pragmas per scanner, keeps reasons,
    and the divergent scopes are exercised so no scanner passes vacuously."""

    def test_parity_per_scanner(self, tmp_path):
        repo = _plant_cross_scope_repo(tmp_path)
        # collect ⊆ count, same divergent scope, exact equality.
        assert len(ct.collect_pragmas(repo)) == ct.count_pragmas(repo) == 1
        assert len(sc.collect_pragmas(repo)) == sc.count_pragmas(repo) == 1
        assert len(md.collect_pragmas(repo)) == md.count_pragmas(repo) == 2

    def test_convergence_theater_sees_only_tests(self, tmp_path):
        repo = _plant_cross_scope_repo(tmp_path)
        paths = {r["path"] for r in ct.collect_pragmas(repo)}
        assert paths == {"tests/test_planted.py"}  # NOT espalier/planted.py

    def test_subprocess_contracts_excludes_tests(self, tmp_path):
        repo = _plant_cross_scope_repo(tmp_path)
        paths = {r["path"] for r in sc.collect_pragmas(repo)}
        assert paths == {"espalier/planted.py"}  # tests/ is out of SC scope

    def test_magic_depth_sees_both_scopes(self, tmp_path):
        repo = _plant_cross_scope_repo(tmp_path)
        paths = {r["path"] for r in md.collect_pragmas(repo)}
        assert paths == {"tests/test_planted.py", "espalier/planted.py"}

    def test_reason_text_captured(self, tmp_path):
        repo = _plant_cross_scope_repo(tmp_path)
        reasons = {r["reason"] for r in ct.collect_pragmas(repo)}
        assert reasons == {"cross-scope-fixture reason here"}

    def test_exempt_fixture_pragma_excluded(self, tmp_path):
        repo = _plant_cross_scope_repo(tmp_path)
        # The tests/fixtures/ theater pragma is counted by neither.
        for rec in ct.collect_pragmas(repo):
            assert not rec["path"].startswith("tests/fixtures/")
        # And the cap counter agrees (==1, not 2).
        assert ct.count_pragmas(repo) == 1


class TestCmdScanWritesOverrides:
    """Integration: `espalier scan` persists reports/scan_overrides.json with
    the concatenated three-scanner corpus."""

    def test_scan_writes_overrides_json(self, tmp_path):
        repo = _plant_cross_scope_repo(tmp_path)
        # cmd_scan needs >=1 scanned .py file for status=="scanned".
        assert cli.cmd_scan(argparse.Namespace(repo=str(repo))) == 0
        overrides_path = repo / "reports" / "scan_overrides.json"
        assert overrides_path.exists()
        data = json.loads(overrides_path.read_text(encoding="utf-8"))
        # CT(1) + MD(2) + SC(1) = 4 honored pragmas in the constructed repo.
        assert data["count"] == 4
        scanners = {o["scanner"] for o in data["overrides"]}
        assert scanners == {"convergence_theater", "magic_depth", "subprocess_contracts"}


def _history(scanner, fires, exemptions, runs, start=0):
    """``runs`` rows for one scanner with distinct ``run_ts`` values ``T{start}``
    onward; pass ``start`` when concatenating slices for one scanner, because
    ``wallpaper_report`` counts distinct ``run_ts``, not rows."""
    return [
        {"run_ts": f"T{start + i}", "scanner": scanner, "fires": fires, "exemptions": exemptions}
        for i in range(runs)
    ]


class TestWallpaperReport:
    """157-C: credibility status is advisory and threshold-gated; a fresh repo
    with few runs must read insufficient-data, not be falsely cried wallpaper."""

    def test_never_firing_scanner_is_candidate_wallpaper(self):
        report = scan_credibility.wallpaper_report(
            _history("dead_scanner", fires=0, exemptions=0, runs=6)
        )
        assert report["dead_scanner"]["status"] == "candidate-wallpaper"

    def test_high_exemption_is_candidate_noisy(self):
        report = scan_credibility.wallpaper_report(
            _history("noisy", fires=1, exemptions=9, runs=6)
        )
        assert report["noisy"]["status"] == "candidate-noisy"
        assert report["noisy"]["exemption_rate"] == 0.9

    def test_firing_scanner_is_healthy(self):
        report = scan_credibility.wallpaper_report(
            _history("good", fires=5, exemptions=0, runs=6)
        )
        assert report["good"]["status"] == "healthy"

    def test_below_min_runs_is_insufficient_data(self):
        report = scan_credibility.wallpaper_report(
            _history("young", fires=0, exemptions=0, runs=2)
        )
        assert report["young"]["status"] == "insufficient-data"

    def test_rarely_firing_scanner_is_candidate_wallpaper(self):
        """DEF-410e earn-the-red: the wallpaper bucket is a per-run RATE, not a
        strict-zero total. One fire in twenty runs (0.05 candidates per run)
        is below WALLPAPER_MAX_CANDIDATES_PER_RUN and reads candidate-wallpaper;
        the total-based cliff read it as healthy."""
        history = _history("rare", fires=0, exemptions=0, runs=19) + _history(
            "rare", fires=1, exemptions=0, runs=1, start=19
        )
        report = scan_credibility.wallpaper_report(history)
        assert report["rare"]["candidates_per_run"] == 0.05
        assert report["rare"]["status"] == "candidate-wallpaper"

    def test_calibration_snapshot_reproduces_its_verdicts(self):
        """A dated SYNTHETIC snapshot, not a live witness: the four scanners at
        the calibration's boundaries with the totals the constants' comment
        block quotes (2026-09-08, 74 runs; the live file is gitignored and
        grows with every scan, so this test cannot read it and stays green
        through any drift by construction). The rule changes exactly one
        verdict against the strict-zero cliff: test_loosening (one fire in 74
        runs) healthy -> candidate-wallpaper."""
        history = (
            _history("retired_vocab", fires=0, exemptions=0, runs=74)
            + _history("test_loosening", fires=0, exemptions=0, runs=73)
            + _history("test_loosening", fires=1, exemptions=0, runs=1, start=73)
            + _history("magic_depth", fires=1, exemptions=0, runs=69)
            + _history("magic_depth", fires=1, exemptions=1, runs=5, start=69)
            + _history("convergence_theater", fires=0, exemptions=0, runs=64)
            + _history("convergence_theater", fires=1, exemptions=0, runs=2, start=64)
            + _history("convergence_theater", fires=0, exemptions=1, runs=8, start=66)
        )
        report = scan_credibility.wallpaper_report(history)
        assert {s: r["runs"] for s, r in report.items()} == {
            "retired_vocab": 74, "test_loosening": 74,
            "magic_depth": 74, "convergence_theater": 74,
        }
        assert {s: r["status"] for s, r in report.items()} == {
            "retired_vocab": "candidate-wallpaper",
            "test_loosening": "candidate-wallpaper",
            "magic_depth": "healthy",
            "convergence_theater": "candidate-noisy",
        }

    def test_runs_count_distinct_run_ts_not_rows(self):
        """The denominator became load-bearing with the per-run rate: a run
        written twice (a re-appended roster, a hand-edited history) must count
        once, or the rate is diluted and the verdict moves."""
        history = _history("s", fires=1, exemptions=0, runs=6)
        history += [dict(row) for row in history]  # every run duplicated
        report = scan_credibility.wallpaper_report(history)
        assert report["s"]["runs"] == 6
        assert report["s"]["total_fires"] == 12
        assert report["s"]["candidates_per_run"] == 2.0

    def test_aggregates_totals_across_runs(self):
        report = scan_credibility.wallpaper_report(
            _history("s", fires=2, exemptions=1, runs=5)
        )
        assert report["s"]["runs"] == 5
        assert report["s"]["total_fires"] == 10
        assert report["s"]["total_exemptions"] == 5

    def test_non_numeric_fires_does_not_raise(self):
        """Regression (final-review): a hand-edited JSON-valid-but-non-numeric
        `fires` must coerce to 0, not raise — this is an advisory module."""
        history = [{"run_ts": "T", "scanner": "s", "fires": "bad", "exemptions": None}]
        report = scan_credibility.wallpaper_report(history)  # must NOT raise
        assert report["s"]["total_fires"] == 0
        assert report["s"]["total_exemptions"] == 0


class TestBaseline:
    """157-C: --baseline snapshots current findings; a later run annotates an
    injected finding `new` and a retained finding `pre-existing` (set-diff)."""

    def _write_report(self, reports, name, payload):
        reports.mkdir(parents=True, exist_ok=True)
        (reports / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_snapshot_then_diff_marks_new_and_pre_existing(self, tmp_path):
        reports = tmp_path / "reports"
        self._write_report(reports, "scan_magic_depth.json",
                            {"count": 1, "findings": [{"path": "a.py", "lineno": 3}]})
        self._write_report(reports, "scan_prints.json",
                            {"count": 1, "findings": [{"file": "b.py", "lineno": 1}]})
        total = scan_credibility.snapshot_baseline(reports)
        assert total == 2
        baseline = scan_credibility.load_baseline(reports)
        assert baseline["by_scanner"]["magic_depth"] == ["a.py"]

        # Inject a NEW finding from a different scanner; a.py/b.py persist.
        self._write_report(reports, "scan_convergence_theater.json",
                            {"count": 1, "findings": [{"path": "c.py", "lineno": 9}]})
        diff = scan_credibility.diff_against_baseline(reports, baseline)
        assert "convergence_theater:c.py" in diff["new"]
        assert "magic_depth:a.py" in diff["pre_existing"]
        assert "prints:b.py" in diff["pre_existing"]
        assert "convergence_theater:c.py" not in diff["pre_existing"]

    def test_load_baseline_absent_returns_none(self, tmp_path):
        assert scan_credibility.load_baseline(tmp_path / "reports") is None


class TestScanExitsZeroOverThreshold:
    """157-C pass criterion: `espalier scan` exits 0 even when the credibility
    budget flags a candidate-wallpaper scanner — it is ADVISORY, never a gate."""

    def test_scan_returns_zero_with_wallpaper_advisory(self, tmp_path, capsys):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        reports = tmp_path / "reports"
        # Seed 5 runs of a never-firing scanner so a 6th (this scan) crosses
        # WALLPAPER_MIN_RUNS and the advisory fires.
        for i in range(5):
            scan_telemetry.append_run(
                reports, f"T{i}", {"retired_vocab": {"fires": 0, "exemptions": 0}}
            )
        rc = cli.cmd_scan(argparse.Namespace(repo=str(tmp_path), baseline=False))
        assert rc == 0  # advisory, NOT a gate
        out = capsys.readouterr().out
        assert "credibility (advisory)" in out
        assert "candidate-wallpaper" in out

    def test_scan_baseline_flag_writes_snapshot(self, tmp_path, capsys):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        rc = cli.cmd_scan(argparse.Namespace(repo=str(tmp_path), baseline=True))
        assert rc == 0
        assert (tmp_path / "reports" / "scan_baseline.json").exists()
        assert "Baseline snapshot" in capsys.readouterr().out

    def test_second_scan_emits_baseline_diff(self, tmp_path, capsys):
        """Regression (final-review): diff_against_baseline was defined+tested
        but never WIRED into cmd_scan — the other half of 157-C. A scan after a
        --baseline snapshot must annotate new vs pre-existing on stdout."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        # A file with a bare-except so the exceptions scanner flags it (a finding
        # that survives into the baseline).
        (pkg / "m.py").write_text(
            "def f():\n    try:\n        pass\n    except:\n        pass\n", encoding="utf-8"
        )
        assert cli.cmd_scan(argparse.Namespace(repo=str(tmp_path), baseline=True)) == 0
        capsys.readouterr()  # drain the snapshot run
        # Re-scan without --baseline: the prior baseline drives a diff advisory.
        assert cli.cmd_scan(argparse.Namespace(repo=str(tmp_path), baseline=False)) == 0
        assert "Baseline diff (advisory)" in capsys.readouterr().out
