"""Hook timing constants — single source of truth for Stop hook contract.

These constants are consumed by:
- espalier/cli.py  (settings generator emits STOP_OUTER_TIMEOUT)
- espalier/harness_config.py  (CANONICAL_HOOK_WIRING uses STOP_OUTER_TIMEOUT)
- tools/cc/hooks/_hook_contract.py  (copy for standalone hook scripts)

Contract invariant (enforced by tests/test_hook_contracts.py):
    STOP_OUTER_TIMEOUT >= STOP_INNER_BUDGET + STOP_SAFETY_MARGIN
"""
from __future__ import annotations

# Stop hook — outer Claude Code timeout (seconds).
# Claude Code kills the hook process if it exceeds this value.
STOP_OUTER_TIMEOUT: int = 90

# Stop hook — inner subprocess budget for pytest inside stop_gate.py (seconds).
# Must satisfy: STOP_OUTER_TIMEOUT >= STOP_INNER_BUDGET + STOP_SAFETY_MARGIN.
STOP_INNER_BUDGET: int = 60

# Stop hook — safety margin between inner budget and outer timeout (seconds).
# Covers gates 2-4 overhead and process startup.
STOP_SAFETY_MARGIN: int = 15
