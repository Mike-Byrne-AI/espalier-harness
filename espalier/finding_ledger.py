"""Run-boundaried fan-out finding ledger.

Every fan-out review already computes a :class:`~espalier.fan_out_findings.FindingsSummary`
(``by_category``, ``by_refutation_outcome``, ``survival_rate``, per-survivor
``corroboration_count``) and then **throws it away to stdout** — only the
survivors are persisted, as three-field markdown bullets, to the round's
report under ``reports/`` (and, until it was retired 2026-09-21, to a shared
cross-round dedup corpus).

A markdown findings file is the wrong store for the learning loop A2 wants to
build on:
``_render_finding_bullet`` keeps only ``location + severity + claim`` and the
round-trip parser recovers only ``location + claim``. It is **deduped on
(location, claim) with no run boundary**, so it physically cannot express
"this class recurred across N *distinct* runs" — you cannot tell three runs that
each found a thing once from one run that found it three times. The file is
fine for *dedup* within a round; it is useless for *recurrence*.

This module is the irreducible foundation: a **structured, append-only,
run-boundaried** ledger. ``append_summary`` writes exactly one JSON line per
fan-out run::

    {run_id, ts, finder_identities: [...rule_or_scanner...],
     summary: {total, by_category, by_refutation_outcome, survival_rate, corroborated},
     findings: [<deduped survivor dicts, raw — verification + corroboration_count intact>]}

``run_id`` and the producer identity live on the **wrapper**, never on a finding
— so the finding wire shape (``FINDING_SCHEMA``, ``additionalProperties: false``,
pinned across the inlined JS copies by ``TestFanoutSchemaParity``) is untouched.

Design (grounded against the live machinery, not the originating pack prose):

* **Plain append, not atomic-overwrite.** ``espalier/_atomic_io`` is a
  whole-file ``tempfile + os.replace`` write — wrong tool for an append. We
  mirror ``scan_telemetry.append_run``: one ``open(path, "a")`` write of one
  line. Batch-atomic (the whole record lands or none of it), tolerant of a
  partially-written tail on read (see :func:`read_ledger`).
* **Fail-open.** This is observability wired into the fan-out persist path; a
  ledger-write failure must never break a review. Every entry point returns a
  row count (``0`` on any failure) and never raises.
* **Stdlib-only leaf.** No runtime ``espalier`` import — ``append_summary``
  duck-types the summary object (reads attributes), so the offline writer never
  pulls in the heavy producer module. ``tools/cc/`` can never import this
  (pinned by ``tests/test_contracts.py::TestToolsCcNoEspalierImports``, which
  matches the whole ``espalier.`` namespace).

The ledger is local-only (``cc/finding_ledger.jsonl``): per-operator accreting
signal, gitignored, never a release artifact (registered in
``surface_contract._LOCAL_ONLY_PATHS``).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotation only — never imported at runtime (keeps this a leaf)
    from espalier.fan_out_findings import FindingsSummary

LEDGER_DIRNAME = "cc"
LEDGER_FILENAME = "finding_ledger.jsonl"


def ledger_path(root: Path | str = ".") -> Path:
    """The ledger location for a repo root: ``<root>/cc/finding_ledger.jsonl``."""
    return Path(root) / LEDGER_DIRNAME / LEDGER_FILENAME


def _clean_findings(raw: object) -> list[dict]:
    """The serialisable dict findings from ``raw``, dropping the rest.

    Malformed elements — non-dicts, or dicts carrying a non-JSON-serialisable
    value — are dropped individually so one bad survivor never costs the whole
    run's record (fail-open at element granularity). ``aggregate_findings``
    already filters schema-invalid findings upstream; this is the second belt.
    """
    clean: list[dict] = []
    if not isinstance(raw, (list, tuple)):
        return clean
    for finding in raw:
        if not isinstance(finding, dict):
            continue
        try:
            json.dumps(finding)
        except (TypeError, ValueError):
            continue
        clean.append(finding)
    return clean


def _build_record(summary: "FindingsSummary", *, run_id: str | None, ts: str | None) -> dict:
    """Assemble the per-run wrapper record. Duck-types ``summary`` via getattr."""
    findings = _clean_findings(getattr(summary, "findings", None))
    finder_identities: list[str] = []
    for finding in findings:
        producer = finding.get("rule_or_scanner")
        if isinstance(producer, str) and producer and producer not in finder_identities:
            finder_identities.append(producer)
    return {
        "run_id": run_id or uuid.uuid4().hex[:12],
        "ts": ts or datetime.now(timezone.utc).isoformat(),
        "finder_identities": finder_identities,
        "summary": {
            "total": getattr(summary, "total", None),
            # by_category keys may be None (a null/unbucketed category); json
            # coerces a None key to the string "null" — acceptable and lossless
            # for the recurrence roll-up A2 does over string category labels.
            "by_category": dict(getattr(summary, "by_category", {}) or {}),
            "by_refutation_outcome": dict(getattr(summary, "by_refutation_outcome", {}) or {}),
            "survival_rate": getattr(summary, "survival_rate", None),
            "corroborated": getattr(summary, "corroborated", None),
        },
        "findings": findings,
    }


def append_summary(
    summary: "FindingsSummary",
    *,
    run_id: str | None = None,
    ts: str | None = None,
    root: Path | str = ".",
) -> int:
    """Append one run-boundaried ledger record for a fan-out's ``summary``.

    ``summary`` is a :class:`~espalier.fan_out_findings.FindingsSummary` (or any
    object exposing the same attributes). ``run_id`` defaults to a fresh random
    handle and ``ts`` to the current UTC time when omitted — each fan-out run is
    a distinct ledger row by design. Returns ``1`` when a record was written,
    ``0`` on any failure (fail-open — never raises; a logging error must never
    affect a review).
    """
    try:
        # No sort_keys: by_category may carry a None key (a null/unbucketed
        # category). sort_keys would compare str vs None across the key set and
        # raise TypeError, which the fail-open ``except`` below would silently
        # swallow — dropping the ENTIRE run's record. json's default coerces a
        # None key to the string "null" (lossless), so plain dumps is correct;
        # JSONL rows are appended, never byte-compared, so ordering buys nothing.
        line = json.dumps(_build_record(summary, run_id=run_id, ts=ts))
        path = ledger_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return 1
    except Exception:  # noqa: BLE001 -- fail-open observability writer; never break a review
        return 0


def read_ledger(root: Path | str = ".") -> list[dict]:
    """Parse the ledger into a list of run records (newest-last).

    Returns ``[]`` when the file is absent. Malformed lines (a partially-written
    tail, a hand-edit) are skipped rather than raising — the ledger is an
    append-only diagnostic, not a transactional store, so one bad line must not
    poison the whole read. Mirrors ``scan_telemetry.read_history``.
    """
    path = ledger_path(root)
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
