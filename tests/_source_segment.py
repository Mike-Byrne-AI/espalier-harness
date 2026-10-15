"""Split a module's source once, then slice each node's text from the split.

``ast.get_source_segment(source, node)`` re-splits the WHOLE source on every
call, and on Python 3.10 (and on 3.11.9, read 2026-10-14) that split is a
per-character loop, so one call per node over a large file crosses the 60 s
per-test ceiling on the required ``test (3.10)`` cell alone (DEF-762, DEF-3005)::

    lines = source_lines(text)    # once per text
    segment(lines, node)          # per node: the stdlib's answer, padded=False

Not a test module (leading underscore), so it needs no marker classification.
The implementation is ``scripts/derived_population_census.py``'s
``_source_lines`` / ``_segment``, loaded by path on first use: one copy, pinned
equal to the stdlib by ``tests/test_derived_population_census.py`` and
``tests/test_maintenance_mode.py``. ``padded=`` is unsupported (no caller needs
it; passing it is a TypeError). Any other stdlib reference under the census's
roots reds ``TestSegmentHelper`` in ``tests/test_derived_population_census.py``.
"""
from __future__ import annotations

import ast
import functools
import importlib.util
from pathlib import Path
from types import ModuleType

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "derived_population_census.py"


@functools.lru_cache(maxsize=1)
def _impl() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_source_segment_impl", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Lines(tuple):
    """What ``source_lines`` returns, and the only argument ``segment`` takes."""

    __slots__ = ()


@functools.lru_cache(maxsize=8)
def source_lines(text: str) -> _Lines:
    """``text`` split on ``\\r\\n``, ``\\n`` and ``\\r`` only (never ``\\f``): the parser's lines.

    Cached for the last eight texts, so ``segment(source_lines(text), node)``
    written inside a node loop still splits once, not once per node.
    """
    return _Lines(_impl()._source_lines(text))


def segment(lines: _Lines, node: ast.AST) -> str | None:
    """``ast.get_source_segment(text, node)`` over ``source_lines(text)``; None without positions."""
    if not isinstance(lines, _Lines):
        # The text itself would slice single characters, and ``text.splitlines()``
        # breaks on the form feed: both answer quietly wrong.
        raise TypeError("segment() takes source_lines(text), not the text or another split of it")
    return _impl()._segment(lines, node)
