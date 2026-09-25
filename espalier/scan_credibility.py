"""Scanner credibility budget + findings baseline.

Consumes the append-only telemetry history (``scan_telemetry.read_history``)
and surfaces per-scanner *credibility* over time:

  - **candidate-wallpaper** — sees fewer than one candidate finding per ten
    runs (a gate nobody's code ever trips is habit-formation-against-friction
    debt, not protection). A per-run RATE, not a strict-zero total: the total
    read one fire in 73 runs as healthy (DEF-410e).
  - **candidate-noisy** — exemption rate over a budget (everyone pragmas it
    away; the false-positive corpus 157-B captures is the evidence).
  - **healthy** / **insufficient-data** — otherwise.

ADVISORY ONLY. The thresholds are calibrated against one tree's telemetry
history (each constant carries the measurement that set it), and a calibration
is a claim about that tree, so nothing in this module exits non-zero or blocks;
``cmd_scan`` surfaces the report as stdout advisory text and returns 0. An
``exit 1`` here would gate ``espalier scan`` on a number measured somewhere else.

The ``--baseline`` snapshot records which files each scanner currently flags so
a later run can annotate findings ``new`` vs ``pre-existing`` (set-diff). It
reads through ``scan_composition.report_finding_paths`` (the single report-shape
SoT) rather than re-implementing the 10 divergent report parsers.

Stdlib-only; pure ``espalier`` layer.
"""
from __future__ import annotations

import json
from pathlib import Path

from espalier import scan_composition
from espalier._atomic_io import atomic_write_text

BASELINE_FILENAME = "scan_baseline.json"

# Calibrated 2026-09-08 against the self-host tree's ``reports/scan_telemetry.jsonl``
# as it stood then: 740 rows, 74 runs, 10 scanners, 2026-06-10 to 2026-09-08. That
# file is machine-local and gitignored, and every ``espalier scan`` appends a run,
# so the numbers below are a dated snapshot, not the current state; re-derive the
# current one with
#   python3 -c "import json; from pathlib import Path; from espalier import
#     scan_credibility as c, scan_telemetry as t; print(json.dumps(
#     c.wallpaper_report(t.read_history(Path('reports'))), indent=1))"
# and re-pin from the history, never by feel. The reasoning is in the maintainer's
# release-decisions log under 2026-09-08. The values drive ADVISORY text only,
# never a gate (see the module docstring).
WALLPAPER_MIN_RUNS = 5
# Runs of history before any verdict. Over every prefix of the snapshot from run
# 5 onward, all ten scanners' verdicts already equal their final verdict, so a
# higher floor buys nothing there; a lower one was not measured.
NOISY_EXEMPTION_RATE = 0.5
# exemption_rate at or above this -> candidate-noisy. Snapshot rates: 0.0 (seven
# scanners), 0.06 (magic_depth), 0.74 (subprocess_contracts), 0.80
# (convergence_theater). Margins: the nearest below is 0.44 away; the nearest
# above, convergence_theater, is seven exemption-free firing runs from crossing
# down to healthy, which is the classifier reading new evidence, not a defect.
WALLPAPER_MAX_CANDIDATES_PER_RUN = 0.1
# candidate findings (fires + exemptions) per run below this -> candidate-
# wallpaper, i.e. fewer than one per ten runs. Snapshot rates: 0.0
# (retired_vocab), 0.014 (test_loosening), 0.135 (convergence_theater), 1.07
# (magic_depth), 5.9 and up (the other six). The nearest above sits 0.035 over
# the line. The strict-zero total this replaces bucketed test_loosening's one
# fire in 74 runs as healthy and retired_vocab's zero as wallpaper; the rate
# reads both as the same thing.


def _safe_int(value: object) -> int:
    """Coerce a telemetry count to int, defaulting to 0. ``scan_telemetry``
    already writes ints, but a hand-edited (JSON-valid, schema-invalid) line
    could carry a non-numeric ``fires``; this advisory module must not turn
    that into a non-zero exit (its whole point is to never gate)."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def wallpaper_report(history: list[dict]) -> dict:
    """Aggregate telemetry rows (``{run_ts, scanner, fires, exemptions}``) into
    a per-scanner credibility view: ``{runs, total_fires, total_exemptions,
    exemption_rate, candidates_per_run, status}``.

    ``exemption_rate`` = exemptions / (fires + exemptions), the fraction of
    candidate findings that were pragma'd away (0.0 when neither).
    ``candidates_per_run`` = (fires + exemptions) / runs, how often the rule
    sees anything at all. ``runs`` counts DISTINCT ``run_ts`` values per
    scanner, not rows: the denominator decides the verdict now, and a
    duplicated or partially-written run must not dilute it. ``status``:

      - ``insufficient-data`` when ``runs < WALLPAPER_MIN_RUNS`` (don't cry
        wallpaper on a fresh repo with one clean scan);
      - ``candidate-noisy`` when ``exemption_rate >= NOISY_EXEMPTION_RATE``;
      - ``candidate-wallpaper`` when ``candidates_per_run <
        WALLPAPER_MAX_CANDIDATES_PER_RUN`` -- a rule that sees something in
        fewer than one run in ten is dead weight whether its total is 0 or 1;
      - ``healthy`` otherwise.
    """
    agg: dict[str, dict] = {}
    for row in history:
        if not isinstance(row, dict):
            continue
        scanner = row.get("scanner")
        if not isinstance(scanner, str):
            continue
        bucket = agg.setdefault(
            scanner, {"run_ts": set(), "total_fires": 0, "total_exemptions": 0}
        )
        bucket["run_ts"].add(str(row.get("run_ts")))
        bucket["total_fires"] += _safe_int(row.get("fires"))
        bucket["total_exemptions"] += _safe_int(row.get("exemptions"))

    report: dict[str, dict] = {}
    for scanner, b in agg.items():
        fires, exempt, runs = b["total_fires"], b["total_exemptions"], len(b["run_ts"])
        denom = fires + exempt
        rate = (exempt / denom) if denom else 0.0
        per_run = (denom / runs) if runs else 0.0
        if runs < WALLPAPER_MIN_RUNS:
            status = "insufficient-data"
        elif rate >= NOISY_EXEMPTION_RATE:
            status = "candidate-noisy"
        elif per_run < WALLPAPER_MAX_CANDIDATES_PER_RUN:
            status = "candidate-wallpaper"
        else:
            status = "healthy"
        report[scanner] = {
            "runs": runs, "total_fires": fires, "total_exemptions": exempt,
            "exemption_rate": round(rate, 4),
            "candidates_per_run": round(per_run, 4), "status": status,
        }
    return report


def _current_findings(reports_dir: Path) -> dict[str, list[str]]:
    """``{scanner: sorted(file paths flagged)}`` from the live finding reports."""
    paths = scan_composition.report_finding_paths(reports_dir)
    return {scanner: sorted(p) for scanner, p in paths.items()}


def snapshot_baseline(reports_dir: Path) -> int:
    """Write ``reports/scan_baseline.json`` = the files each scanner currently
    flags. Returns the total finding-path count snapshotted."""
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    findings = _current_findings(reports_dir)
    total = sum(len(v) for v in findings.values())
    payload = {"total": total, "by_scanner": findings}
    atomic_write_text(
        reports_dir / BASELINE_FILENAME,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )
    return total


def load_baseline(reports_dir: Path) -> dict | None:
    """Read a prior baseline, or ``None`` if absent/malformed."""
    path = Path(reports_dir) / BASELINE_FILENAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def diff_against_baseline(reports_dir: Path, baseline: dict) -> dict:
    """Annotate current findings ``new`` vs ``pre-existing`` against a baseline.

    Keys are ``"{scanner}:{path}"``. ``new`` = present now, absent in baseline;
    ``pre_existing`` = present in both. Returns sorted lists of each.
    """
    base_by_scanner = baseline.get("by_scanner", {}) if isinstance(baseline, dict) else {}
    base_keys = {
        f"{scanner}:{p}"
        for scanner, paths in base_by_scanner.items()
        if isinstance(paths, list)
        for p in paths
    }
    current = _current_findings(reports_dir)
    cur_keys = {f"{scanner}:{p}" for scanner, paths in current.items() for p in paths}
    return {
        "new": sorted(cur_keys - base_keys),
        "pre_existing": sorted(cur_keys & base_keys),
    }
