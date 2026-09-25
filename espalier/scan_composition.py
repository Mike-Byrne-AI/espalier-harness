"""Cross-scanner composition (Tier 2, ADVISORY).

Reads the 11 per-scanner *finding* reports ``cmd_scan`` writes and surfaces
files flagged by >=2 scanners — a combined-signal heuristic (a file that trips
both ``magic_depth`` and ``convergence_theater`` is a stronger triage target
than either alone). Advisory only; never gates.

The 10 reports expose SIX distinct path-extraction shapes — a single naive
``report["findings"][i]["path"]`` walk catches only three scanners
(``convergence_theater``, ``magic_depth``, ``retired_vocab``) and silently
misses the other seven:

  - ``findings[].file``         exceptions, prints
  - ``findings[].path``         convergence_theater, magic_depth, retired_vocab
  - ``findings[].caller_path``  subprocess_contracts
  - ``findings[].writer_path``  filesystem_contracts
  - ``files[].path``  loc>=threshold   godfiles  (``files`` lists ALL scanned
                      files, not just the big ones — filter or every file reads
                      as a godfiles hit)
  - ``results[].file`` total_hits>0    perf_smells
  - ``results[].file`` count>0         test_loosening

``scan_summary.json`` is a counts-only snapshot with NO per-file paths; it (and
the telemetry/override/baseline artifacts) are explicitly skipped. This module
is the single source of truth for "which files did each scanner flag" — both
this file's ``intersect`` and ``scan_credibility``'s baseline read through
``report_finding_paths`` so the report-shape knowledge lives in one place.

Stdlib-only; pure ``espalier`` layer (no hook-audit coupling).
"""
from __future__ import annotations

import json
from pathlib import Path

# Finding-report filename -> scanner name. The 10 ``scan_<name>.json`` + the
# oddly-named ``godfiles_report.json`` (NOT scan_godfiles.json).
REPORT_FILES: dict[str, str] = {
    "scan_exceptions.json": "exceptions",
    "scan_prints.json": "prints",
    "godfiles_report.json": "godfiles",
    "scan_perf_smells.json": "perf_smells",
    "scan_test_loosening.json": "test_loosening",
    "scan_convergence_theater.json": "convergence_theater",
    "scan_subprocess_contracts.json": "subprocess_contracts",
    "scan_filesystem_contracts.json": "filesystem_contracts",
    "scan_magic_depth.json": "magic_depth",
    "scan_retired_vocab.json": "retired_vocab",
    "scan_encoding_contracts.json": "encoding_contracts",
}

# Per-finding path keys used by the ``findings[]``-shaped reports.
_FINDINGS_PATH_KEYS = ("file", "path", "caller_path", "writer_path")


def _rel(p: str, repo_roots: tuple[str, ...]) -> str:
    """Normalize a report path to repo-RELATIVE so paths are COMPARABLE across
    scanners. This is load-bearing: exceptions/prints/perf_smells write
    ABSOLUTE ``file`` paths (cmd_scan passes ``str(repo_root.resolve())`` to
    them), while convergence_theater/magic_depth/subprocess_contracts/
    retired_vocab/godfiles write RELATIVE paths — without relativizing, a file
    co-flagged by one of each NEVER intersects (silent under-collection).

    Pure string op (no FS). ``repo_roots`` carries BOTH the literal and the
    symlink-resolved repo root (on macOS ``/tmp`` -> ``/private/tmp``), so the
    strip works whether the caller passed a resolved ``reports_dir`` or not.
    """
    np = p.replace("\\", "/").removeprefix("./")
    for rr in repo_roots:
        rr = rr.replace("\\", "/").rstrip("/")
        if rr and np.startswith(rr + "/"):
            return np[len(rr) + 1:]
    return np


def _extract_paths(scanner: str, report: dict, repo_root: tuple[str, ...]) -> set[str]:
    """Pull the set of repo-relative file paths a scanner flagged, honoring
    that scanner's report shape (and filtering to ACTUAL hits — godfiles
    ``files`` lists every scanned file; perf/test_loosening ``results`` may
    include zero-hit rows). All paths are relativized to ``repo_root`` so the
    abs-vs-rel divergence across scanners doesn't break the join.

    Known advisory limitation: three upstream scanners truncate
    their result lists *before* this join sees them, so the intersection is over
    the capped sets, not the full hit lists:
      - godfiles writes ``files = rows[:50]`` (top 50 by LOC desc);
      - perf_smells writes ``results = results[:30]`` (top 30 by hits desc);
      - test_loosening writes ``results = hotspots[:30]`` (top 30 by hits desc).
    If MORE files exceed threshold than the cap, the rank-(cap+1)+ files are
    absent from this set — acceptable for an advisory composition signal (the
    largest are still surfaced); documented here rather than silently capped
    ("No silent caps").
    """
    if scanner == "godfiles":
        threshold = report.get("threshold", 0)
        return {
            _rel(f["path"], repo_root) for f in report.get("files", [])
            if isinstance(f, dict) and isinstance(f.get("path"), str)
            and f.get("loc", 0) >= threshold
        }
    if scanner == "perf_smells":
        return {
            _rel(r["file"], repo_root) for r in report.get("results", [])
            if isinstance(r, dict) and isinstance(r.get("file"), str)
            and r.get("total_hits", 0) > 0
        }
    if scanner == "test_loosening":
        return {
            _rel(r["file"], repo_root) for r in report.get("results", [])
            if isinstance(r, dict) and isinstance(r.get("file"), str)
            and r.get("count", 0) > 0
        }
    # Default: a ``findings[]`` list; first matching path-key per finding.
    paths: set[str] = set()
    for fnd in report.get("findings", []):
        if not isinstance(fnd, dict):
            continue
        for key in _FINDINGS_PATH_KEYS:
            value = fnd.get(key)
            if isinstance(value, str):
                paths.add(_rel(value, repo_root))
                break
    # filesystem_contracts nests a SECOND finding class under
    # ``recursive_walks.findings[].path`` — the bare-rglob / recursive-glob
    # recurrence guard, distinct from the top-level ``writer_path`` findings but
    # still files this scanner flagged. Fold them into the join too; otherwise a
    # file tripped ONLY by a bare-rglob finding is silently under-collected. Only
    # filesystem_contracts emits this key, so other reports are unaffected.
    nested = report.get("recursive_walks")
    if isinstance(nested, dict):
        for fnd in nested.get("findings", []):
            if isinstance(fnd, dict) and isinstance(fnd.get("path"), str):
                paths.add(_rel(fnd["path"], repo_root))
    return paths


def report_finding_paths(reports_dir: Path) -> dict[str, set[str]]:
    """Map ``scanner_name -> {repo-relative file paths it flagged}`` across the
    10 finding reports. Missing or malformed reports contribute nothing (an
    advisory join must not crash on a partial ``reports/`` tree). Scanners
    whose report is absent are simply omitted from the mapping.
    """
    reports_dir = Path(reports_dir)
    # reports/ lives at <repo_root>/reports/, so its parent is the scanned repo
    # root — the base every absolute report path is relativized against. Carry
    # BOTH the literal and the symlink-resolved form so the strip works whether
    # the caller passed a resolved reports_dir or not (macOS /tmp vs /private/tmp).
    parent = reports_dir.parent
    try:
        repo_root = (str(parent), str(parent.resolve()))
    except OSError:
        repo_root = (str(parent),)
    out: dict[str, set[str]] = {}
    for filename, scanner in REPORT_FILES.items():
        path = reports_dir / filename
        if not path.exists():
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(report, dict):
            out[scanner] = _extract_paths(scanner, report, repo_root)
    return out


def intersect(reports_dir: Path, *, min_scanners: int = 2) -> dict:
    """Files flagged by ``>= min_scanners`` distinct scanners.

    Returns ``{path: sorted([scanner, ...])}`` for every file at least
    ``min_scanners`` scanners flagged — the combined-signal triage set. Reads
    through ``report_finding_paths`` (the report-shape SoT), so ``godfiles``
    below-threshold files, ``perf``/``test_loosening`` zero-hit rows, and
    ``scan_summary.json`` never leak phantom hits into the join. The perf/test
    inputs are also upstream-capped to the top 30 by hits (godfiles to the top
    50 by LOC) before they reach this join — see ``_extract_paths`` — so the
    join is over the capped sets, not the full hit lists.
    """
    by_scanner = report_finding_paths(reports_dir)
    path_to_scanners: dict[str, set[str]] = {}
    for scanner, paths in by_scanner.items():
        for p in paths:
            path_to_scanners.setdefault(p, set()).add(scanner)
    return {
        p: sorted(scanners)
        for p, scanners in path_to_scanners.items()
        if len(scanners) >= min_scanners
    }
