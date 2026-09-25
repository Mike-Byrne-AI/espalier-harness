"""Append-only scan telemetry history (Tier 1).

``espalier scan`` already computes a per-scanner finding count and an
overwrite-every-run ``reports/scan_summary.json`` snapshot. That snapshot is
point-in-time: it answers "what fired on THIS run" but never "which self-gov
scanner is wallpaper (never fires) vs noisy (always exempted) OVER TIME."

This module persists the missing *history*: one JSON line per scanner per run
appended to ``reports/scan_telemetry.jsonl`` (a local-only, gitignored artifact
under the ``reports/`` prefix — see ``surface_contract._LOCAL_ONLY_PREFIXES``).
It deliberately does NOT duplicate ``scan_summary.json`` (that stays the
point-in-time view); ``scan_credibility`` (157-C) consumes this history.

Stdlib-only. Pure ``espalier``-layer module — it never touches the hook-side
audit log (``tools/cc/hooks/_integrity.append_audit``); self-gov telemetry
lands in an ``espalier``-owned ``reports/`` artifact by design (the
import-direction boundary).
"""
from __future__ import annotations

import json
from pathlib import Path

from espalier._atomic_io import atomic_write_text

TELEMETRY_FILENAME = "scan_telemetry.jsonl"

# Bound the append-only history the way the blueprint chain is bounded by
# BLUEPRINT_RETENTION. reports/ is gitignored + local-only (never ships), but
# read_history() parses the WHOLE file on every scan, so an uncapped log would
# slowly tax each subsequent scan. ~10 rows/run => 2000 rows ≈ 200 recent runs.
_MAX_TELEMETRY_ROWS = 2000


def append_run(reports_dir: Path, run_ts: str, counts: dict) -> int:
    """Append one telemetry record per scanner for a single scan run.

    ``counts`` maps ``scanner_name -> {"fires": int, "exemptions": int}`` (the
    shape ``cmd_scan`` assembles from the existing ``summary`` dict + the three
    pragma scanners' ``count_pragmas``). Writes one JSON object per line to
    ``reports_dir/scan_telemetry.jsonl`` (append-only history), each carrying
    ``{run_ts, scanner, fires, exemptions}``. Returns the number of rows written.

    The whole run's rows are written in a single append (one ``open(...,"a")``)
    so a run never lands half its scanners; sorted by scanner name for stable,
    diffable output. ``reports_dir`` is created if absent.
    """
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for scanner in sorted(counts):
        record = counts[scanner]
        lines.append(json.dumps({
            "run_ts": run_ts,
            "scanner": scanner,
            "fires": int(record.get("fires", 0)),
            "exemptions": int(record.get("exemptions", 0)),
        }, sort_keys=True))
    if not lines:
        return 0
    path = reports_dir / TELEMETRY_FILENAME
    # newline="" so the appended rows and _trim_history's rewrite share one
    # line ending on every platform (the rewrite goes through the helper,
    # which writes \n verbatim).
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(lines) + "\n")
    _trim_history(path)
    return len(lines)


def _trim_history(path: Path) -> None:
    """Keep only the most-recent ``_MAX_TELEMETRY_ROWS`` lines so the append-only
    history stays bounded. Best-effort: any read/write failure leaves the file
    as-is (telemetry is advisory, never load-bearing). Whole rows only — a record
    is one line — so trimming never produces a half-record read_history would skip.
    """
    try:
        existing = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return
    if len(existing) <= _MAX_TELEMETRY_ROWS:
        return
    try:
        # Load-modify-save: the helper prevents a torn file, not a lost update.
        # Unguarded because the history is advisory, read_history skips a torn
        # or missing row, and a run that appended between the read and the
        # replace loses at most its own rows.
        atomic_write_text(path, "\n".join(existing[-_MAX_TELEMETRY_ROWS:]) + "\n")
    except OSError:
        pass


def read_history(reports_dir: Path) -> list[dict]:
    """Parse ``reports_dir/scan_telemetry.jsonl`` into a list of records.

    Returns ``[]`` when the file is absent. Malformed lines (a partially
    written tail, or a hand-edit) are skipped rather than raising — the file is
    an append-only diagnostic, not a transactional store, so one bad line must
    not poison the whole history read.
    """
    path = Path(reports_dir) / TELEMETRY_FILENAME
    if not path.exists():
        return []
    records: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return records
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records
