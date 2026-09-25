"""TP-152 B-5: plan_guard and write_guard must read the SAME MCP
path-field set — the ``_hook_utils.MCP_PATH_FIELDS`` single source of
truth.

Pre-fix write_guard swept 10 path-shaped fields while plan_guard's
inline ``or``-chain read only 5. The gap is dormant under the current
plan_guard matcher (MCP tools aren't matched today), but a widened
matcher would let a move/rename via ``target``/``uri``/``src``/``dst``/
``target_uri`` slip past the plan check while write_guard still saw it.
Promoting one shared tuple keeps the two hooks aligned by construction.
This pins that both hooks read the shared field set, preventing a
move/rename bypass from diverging between them.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOKS = REPO / "tools" / "cc" / "hooks"


def _hook_utils():
    sys.path.insert(0, str(HOOKS))
    try:
        import _hook_utils  # type: ignore[import-not-found]

        return _hook_utils
    finally:
        sys.path.pop(0)


def test_shared_tuple_is_the_ten_field_superset():
    fields = _hook_utils().MCP_PATH_FIELDS
    assert isinstance(fields, tuple)
    assert len(fields) == len(set(fields)) == 10
    # the five plan_guard previously missed (latent move/rename bypass)
    assert {"src", "dst", "target", "uri", "target_uri"} <= set(fields)


def test_both_hooks_reference_shared_tuple_and_define_no_local_set():
    pg = (HOOKS / "plan_guard.py").read_text(encoding="utf-8")
    wg = (HOOKS / "write_guard.py").read_text(encoding="utf-8")
    assert "_hook_utils.MCP_PATH_FIELDS" in pg
    assert "_hook_utils.MCP_PATH_FIELDS" in wg
    # the pre-fix inline literals must be gone (no divergent local copy)
    assert "candidate_fields = (" not in wg
    assert 'tool_input.get("destination", "")' not in pg
