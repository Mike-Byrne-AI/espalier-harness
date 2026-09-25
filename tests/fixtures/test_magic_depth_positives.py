"""Earn-the-gate fixture for ``espalier.scanners.magic_depth``.

Each function below uses ``parents[N >= 2]`` (constant or dynamic) so
the scanner is expected to flag at least one UNPINNED finding per
shape. Real production code either keeps depth < 2 or pins the depth
via ``MAGIC_DEPTH_SITES`` or an inline ``# magic-depth: ok <reason>``
pragma.

The earn-the-gate test monkeypatches EXEMPT_PREFIXES to () so the
fixture under ``tests/fixtures/`` is walked.

Discoverability: prefixed `test_` so pytest's `rglob('test_*.py')`
collector sees the file. The file contains no `def test_*` functions.
"""
from __future__ import annotations

from pathlib import Path


def theater_parents_2() -> Path:
    return Path(__file__).resolve().parents[2]


def theater_parents_3() -> Path:
    return Path(__file__).resolve().parents[3]


def theater_parents_dynamic() -> Path:
    n = 2
    return Path(__file__).resolve().parents[n]


def theater_parents_4_multiline() -> Path:
    # The `.parents[4]` sits on a DIFFERENT line from the expression start, so
    # the finding must cite THIS line, not the `Path(` line (sweep T5). A
    # distinct depth (4) keeps the T5 assertion unambiguous vs the [2]/[3] above.
    root = (
        Path(__file__)
        .resolve()
        .parents[4]
    )
    return root
