"""TP-189-A (OVERCLAIM-1): SessionStart injects the prior session's REASONING
(Next steps + continuation fragments + recent decisions), not just the depth
header, so the next session re-engages instead of re-deriving (README:89).

``_load_blueprint`` previously returned ``lines[0][:120]`` — the first line only
— silently dropping everything ``cognitive_blueprint.cmd_load`` formats below the
header. ``_bound_blueprint_context`` now returns the whole load output, bounded
to its budget share. These tests pin the multi-line preservation (the deliver)
and the bound (the budget guard).

Earn-the-red: under the old code ``_bound_blueprint_context`` did not exist
(AttributeError) AND only line 0 was kept — the first test fails both ways.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _import_session_start():
    """Load the hook module fresh with the correct sys.path discipline."""
    hooks_dir = Path(__file__).parent.parent / "tools" / "cc" / "hooks"
    tools_cc_dir = Path(__file__).parent.parent / "tools" / "cc"
    sys.path.insert(0, str(hooks_dir))
    sys.path.insert(0, str(tools_cc_dir))
    if "session_start" in sys.modules:
        del sys.modules["session_start"]
    import session_start  # type: ignore[import-not-found]
    return session_start


def test_bound_blueprint_context_preserves_multiline_reasoning() -> None:
    """The deliver: multi-line blueprint reasoning survives (old code kept only
    line 0). Header + Next-steps + decisions must come back whole."""
    ss = _import_session_start()
    payload = (
        "# Session Context (depth 7)\n\n"
        "## Next steps\nFinish TP-189-A.\n\n"
        "## Recent decisions\n- delivered blueprint context"
    )
    out = ss._bound_blueprint_context(payload)
    assert out == payload, "the full reasoning must survive, not just line 0"
    assert "Next steps" in out and "Recent decisions" in out


def test_bound_blueprint_context_truncates_over_budget() -> None:
    """The guard: an oversized payload is capped to the blueprint budget share
    (+ a truncation marker) so it cannot flood the SessionStart context block."""
    ss = _import_session_start()
    cap = ss._MAX_BLUEPRINT_CONTEXT_BYTES
    big = "x" * (cap + 5_000)
    out = ss._bound_blueprint_context(big)
    # A single runaway line keeps its HEAD (byte-cut) with the honest newest-entry
    # marker -- bounded so it cannot flood the block, never lost whole (Phase-3b MAJOR).
    assert out.endswith("pull cc/blueprints/latest.json]") or out.endswith("[blueprint context truncated]")
    assert len(out.encode("utf-8")) <= cap + len(ss._NEWEST_ENTRY_MARKER)
    assert len(out) < len(big)
    assert out.startswith("x")  # the head survives, not lost whole
