"""The record-path answers the tree-wide sweeps share, read from their one home.

A sweep that exempts a record by its file name (``task-packs/FORWARD_LEDGER.md``,
``ESPALIER_MEMORY.md``, ``CHANGELOG.md``) misses the same record once it is kept
one file per change: the Session Log rows under ``memory/session-log.d/``, the
changelog entries under ``changelog.d/``, and, where a repository sets
``ledger_fragments = true``, the ledger's rows and probes under
``task-packs/ledger.d/`` and ``task-packs/probes.d/``. These answers come from
``tools/cc/_record_fragments.py`` (loaded by path, registered before it runs),
never from a list typed here.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_NAME = "_tests_record_paths_record_fragments"


def _load():
    if _NAME in sys.modules:
        return sys.modules[_NAME]
    spec = importlib.util.spec_from_file_location(_NAME, REPO_ROOT / "tools" / "cc" / "_record_fragments.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_NAME] = mod  # before exec: its dataclasses look their module up
    spec.loader.exec_module(mod)
    return mod


_FRAG = _load()


def record_fragments():
    """The loader module."""
    return _FRAG


def is_ledger_record(rel: str) -> bool:
    """The ledger or its roster, or a file under one of their two directories."""
    return _FRAG.is_ledger_record(rel)


def is_dated_fragment(rel: str) -> bool:
    """A file under the Session Log's or the changelog's fragment directory."""
    return _FRAG.is_dated_fragment(rel)
