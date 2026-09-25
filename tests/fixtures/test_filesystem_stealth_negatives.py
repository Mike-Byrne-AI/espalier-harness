"""Must-NOT-trip negative corpus for ``espalier.scanners.filesystem_contracts``.

Every function below is a *clean-but-tempting* near-boundary variant of a
shape the positives fixture flags as UNPINNED — defanged so the scanner
extracts NO write target and the file produces ZERO findings. This proves
the scanner stays SILENT on legitimate file I/O instead of over-firing.

The temptations and why each stays clean:
- ``open(path, "r")`` / read-only ``with`` blocks — file I/O, but not a
  write, so no alias binding and no target.
- ``write_text``/``write_bytes`` to a NON-structured suffix
  (.log / .md / .csv / .txt) — a real disk write, but the suffix is not
  in STRUCTURED_SUFFIXES, so no target is extracted.
- ``Path(variable).write_text(...)`` — the path is a runtime variable the
  resolver cannot trace to a literal, so there is nothing to classify.
- ``json.dumps(...)`` / ``json.dump(obj, buf)`` to an in-memory buffer —
  serialization with no file write, so no contract surface.
- a wrapper whose name contains neither "write"+"json" nor a
  WRAPPER_WRITE_PATTERNS entry — an ordinary helper, not a write sink.

The companion test in tests/test_scanner_filesystem_contracts.py calls
``_scan_file`` directly against this fixture path and asserts the result
is empty — ``scan_repo`` walks ``espalier/`` and ``tools/`` only, so the
fixture would be invisible to a default ``scan_repo(REPO_ROOT)`` call.

Discoverability: prefixed `test_` so pytest's `rglob('test_*.py')`
collector sees the file. The file contains no `def test_*` functions and
no real assertions — it is fixtures-only.
"""
from __future__ import annotations

import io
import json
from pathlib import Path


# precision-boundary: a helper whose NAME merely contains the action/format
# letters (rewrite, overwrite) with no adjacent action+format snake-token pair —
# not a serialise-write sink; plus a partial basename hint matching two
# contracts (AMBIGUOUS, not a falsely PINNED all-clear).


def clean_read_only_open() -> dict:
    """open(..., "r") is a read, not a write — no alias binding."""
    with open("config.json", "r") as f:
        return json.load(f)


def clean_read_block_then_use() -> dict:
    """Structured suffix, but read mode — the with-block resolver only
    binds write-mode opens."""
    with open("settings.json", "r") as fh:
        return json.load(fh)


def clean_write_text_log() -> None:
    """A real disk write, but .log is not a structured suffix."""
    Path("audit.log").write_text("event occurred\n")


def clean_write_text_markdown() -> None:
    """.md is prose output, never a schema contract."""
    Path("README.md").write_text("# heading\n")


def clean_write_text_csv() -> None:
    """.csv is tabular, not in STRUCTURED_SUFFIXES."""
    Path("data.csv").write_text("a,b\n1,2\n")


def clean_write_bytes_text() -> None:
    """write_bytes to a .txt target — structured method, plain suffix."""
    Path("report.txt").write_bytes(b"summary\n")


def clean_variable_path_write(target: str) -> None:
    """The path is a runtime parameter the resolver cannot trace to a
    literal, so no write target is extracted even though the payload is
    JSON."""
    Path(target).write_text(json.dumps({"a": 1}))


def clean_serialize_to_string() -> str:
    """json.dumps with no file argument — serialization, not a write."""
    return json.dumps({"a": 1})


def clean_dump_to_buffer() -> str:
    """json.dump to an in-memory StringIO — the second arg is not an
    open()-bound alias, so the with-block resolver never sees it."""
    buf = io.StringIO()
    json.dump({"a": 1}, buf)
    return buf.getvalue()


def clean_dump_to_open_logfile() -> None:
    """with open(..., "w") binds an alias, but the .log suffix is not
    structured, so the bound dump produces no target."""
    with open("events.log", "w") as handle:
        json.dump({"a": 1}, handle)


def clean_render_payload(obj: dict) -> str:
    """A wrapper whose name contains neither "write"+"json" nor a
    WRAPPER_WRITE_PATTERNS entry — an ordinary in-memory helper."""
    return render_template(obj)


# ── unused helper stub (referenced by the wrapper fixture above) ───────
def render_template(obj: dict) -> str: ...


def clean_rewrite_overwrite_are_not_write_json_sinks() -> None:
    # Twin of a write-json wrapper: `rewrite`/`overwrite` CONTAIN "write" and the
    # call site mentions json, but neither is the `write`/`save`/`dump` action
    # token adjacent to a format token, so they are NOT serialise sinks (sweep
    # T4-A). Must extract NO target.
    rewrite_json_cache("cfg.json")
    overwrite_jsonish("state.json")


def rewrite_json_cache(p):  # ordinary helper, not a write sink
    return p


def overwrite_jsonish(p):
    return p
