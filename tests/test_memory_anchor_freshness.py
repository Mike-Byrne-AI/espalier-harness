"""TP-152 152-D — anchor freshness for ESPALIER_MEMORY.md.

The ESPALIER_MEMORY.md index carries the same kind of ``symbol`` + ``file.py:NN`` anchors
as docs/FAILURE_MODES.md (e.g. the `initialized_repo_root` fixture row and the
`auto_continuation_fragments` continuity row). Those line anchors drift exactly
like the catalog's did — W24 and the MEMORY:55 conftest anchor both pointed at
the wrong line after the code moved. This contract pins them so the drift is
caught mechanically. This is the MEMORY-side companion of the
mechanical anchor-resolution contract; it reuses the same resolver so the two
docs are guarded by one canon.

Earn-the-red lives with the resolver in test_catalog_self_consistency.py; this
module exercises it against the live ESPALIER_MEMORY.md (Mode 1) plus the registered
MEMORY anchors (Mode 2).
"""
from __future__ import annotations

from pathlib import Path

from test_catalog_self_consistency import (
    _ROTATING_ANCHOR_HOSTS,
    _SYMBOL_ANCHORS,
    _check_line_anchors_fresh,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MEMORY = REPO_ROOT / "ESPALIER_MEMORY.md"


def test_memory_line_anchors_fresh():
    """Mode 1: every `symbol`+`file.py:NN` line anchor in ESPALIER_MEMORY.md resolves
    within tolerance of the symbol's live def."""
    _check_line_anchors_fresh(MEMORY.read_text(encoding="utf-8"))


def test_memory_is_a_declared_rotating_host_with_no_symbol_anchors():
    """Mode 2 is REFUSED here (DEF-621), and this asserts the refusal rather than
    looping over zero rows.

    Deleting the registry row alone would have left the old Mode-2 test passing
    vacuously -- green because it iterated an empty match, indistinguishable from
    green because it checked something. So the contract is stated positively: this
    file is a declared rotating host, and no anchor may target it.
    """
    assert "ESPALIER_MEMORY.md" in _ROTATING_ANCHOR_HOSTS, (
        "ESPALIER_MEMORY.md is a bounded, auto-pruned Session Log; dropping it from "
        "_ROTATING_ANCHOR_HOSTS re-opens DEF-621."
    )
    rows = [a for a in _SYMBOL_ANCHORS if a[0] == "ESPALIER_MEMORY.md"]
    assert not rows, (
        f"{len(rows)} Mode-2 anchor row(s) target ESPALIER_MEMORY.md: {rows}. Eviction "
        "removes the prose they pin, so they red on a commit that changes no code."
    )
