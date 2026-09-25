"""Earn-the-gate fixture for ``espalier.scanners.filesystem_contracts``.

Each function below writes a structured file (.json / .toml / .yaml)
the scanner is expected to flag as UNPINNED. Real production code
either uses one of the FILESYSTEM_CONTRACTS-pinned paths or writes to
``reports/`` (the scanner-output exemption); this file's job is to be
the corpus that proves the scanner sees each documented write shape.

The earn-the-gate test in
tests/test_scanner_filesystem_contracts.py calls ``_scan_file``
directly against this fixture path — ``scan_repo`` walks
``espalier/`` and ``tools/`` only, so the fixture would be invisible
to a default ``scan_repo(REPO_ROOT)`` invocation.

Discoverability: prefixed `test_` so pytest's `rglob('test_*.py')`
collector sees the file. The file contains no `def test_*` functions.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path


def theater_write_text_json() -> None:
    Path("data.json").write_text(json.dumps({"a": 1}))


def theater_write_text_toml() -> None:
    Path("config.toml").write_text("a = 1")


def theater_write_bytes_yaml() -> None:
    Path("config.yaml").write_bytes(b"a: 1\n")


def theater_json_dump_to_open() -> None:
    with open("output.json", "w") as f:
        json.dump({"a": 1}, f)


def theater_pickle_dump_to_open() -> None:
    with open("pickled.json", "wb") as f:
        pickle.dump({"a": 1}, f)


def theater_atomic_write_text() -> None:
    atomic_write_text(Path("atomic.json"), '{"a": 1}\n')


def theater_atomic_write_json() -> None:
    atomic_write_json(Path("atomic2.json"), {"a": 1})


def theater_dump_json_wrapper() -> None:
    dump_json(Path("dumped.json"), {"a": 1})


# ── unused helper stubs (referenced by fixtures above) ─────────────────
def atomic_write_text(path: Path, content: str) -> None: ...
def atomic_write_json(path: Path, obj) -> None: ...
def dump_json(path: Path, obj) -> None: ...
