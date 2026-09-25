"""Shared report-IO helpers for the espalier engine.

Single owner for the report-sidecar JSON loader + the "safe" text read
used across handoff, reflection, diffing, proofs, cognitive_blueprint,
analyze, and reflect_protocol.

Boundary: this is the espalier-side hoist. The hook-side standalone
loader (tools/cc/cognitive_blueprint.py::_load_json) is a SEPARATE owner
by the zero-import contract and is intentionally NOT shared with this.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from espalier.managed_markers import strip_managed_marker_line


def load_report_json(path: Path) -> dict[str, Any]:
    """Best-effort loader for reports/*.json sidecars.

    Contract:

    - missing file              -> {}
    - OSError / UnicodeDecodeError / JSONDecodeError (denied read,
      mid-rename, non-UTF-8, malformed JSON) -> {}
    - valid JSON but non-dict   -> {}  (callers .get() on the result)

    Strips a leading managed-marker comment line via the managed_markers
    SoT before parsing.
    """
    if not path.exists():
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        lines = strip_managed_marker_line(lines)
        data = json.loads("\n".join(lines))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def report_is_json_object(path: Path) -> bool:
    """True iff ``path`` exists AND parses to a JSON object (dict).

    A present-but-corrupt / non-dict / non-UTF-8 report returns False — the
    signal a fail-closed gate needs to distinguish "unreadable" from "absent"
    (``load_report_json`` alone collapses both a corrupt file and a valid empty
    one to ``{}``). Strips a leading managed-marker line via the SoT first.

    Lifted here (from ``doctor``) so ``proofs`` can reuse it without a
    ``proofs -> doctor -> proofs`` circular import.
    """
    if not path.exists():
        return False
    try:
        lines = strip_managed_marker_line(path.read_text(encoding="utf-8").splitlines())
        return isinstance(json.loads("\n".join(lines)), dict)  # json-dict-safe: ok -- isinstance-wrapped, returns bool
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def safe_text(path: Path) -> str:
    """Read text with replacement decoding, OSError-degrading to ''."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def load_harness_plan(repo_root: Path) -> dict[str, Any] | None:
    """Load reports/harness_config.json as the saved plan, or None.

    Single owner for the cleanup/doctor _load_plan pair. Catches the full
    exception set: a non-UTF-8 / BOM-prefixed harness_config.json raises
    UnicodeDecodeError (NOT JSONDecodeError) and an exists()->read race
    raises OSError. Returns None (not {}) to preserve the plan-or-None
    contract.
    """
    path = repo_root / "reports" / "harness_config.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
