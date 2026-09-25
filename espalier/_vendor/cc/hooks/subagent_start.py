#!/usr/bin/env python3
"""SubagentStart hook — cold-subagent orientation + the fan-out finding-schema pointer.

A freshly-spawned subagent has not loaded the host's resolved facts (which
interpreter exists, what OS, whether MAINTENANCE / STOP_GATE modes are active)
and, for review/audit fan-outs, has not loaded the FINDING_SCHEMA return
contract. This hook injects both via ``hookSpecificOutput.additionalContext``
(delivered at the start of the subagent's context, per the pinned protocol —
``docs/external/cc-hook-protocol.md``). Stdlib only, zero espalier imports.

NOTE: the FINDING_SCHEMA *delivery* here is belt-and-suspenders. The PRIMARY,
depth-robust delivery is the parent-Task prompt (the pin gives no firing
guarantee for nested fan-out agents). The schema contract is enforced on the
returned DATA (``espalier.fan_out_findings.iter_finding_errors``), never on
this hook firing.

Protocol contract (cc-hook-protocol.md):
- SubagentStart delivers ``additionalContext`` at the start of the conversation.
- Exit 0 + ``hookSpecificOutput`` JSON → inject context (this hook's only path).
- This hook is a non-blocking reporter; it NEVER exits 2.

Host facts are resolved INLINE (not via a ``_hook_utils`` helper) to keep the
hook self-contained and avoid coupling the shared helper module to a single
caller.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _hook_utils import (  # noqa: E402
    os_error_text,
    host_orientation_line,
    read_stdin_safely,
    stop_gate_mode,
)
from _maintenance_mode import ENV_VAR  # noqa: E402

# Read mode flags directly from the environment so this reporter has NO side
# effects (notably: no maintenance-bypass stderr log — we import the env-var
# NAME from _maintenance_mode, not its .is_active() which logs; the literal
# itself must not live in a non-exempt hook, for constant-parity).
_STOP_GATE_ENV = "ESPALIER_STOP_GATE"


def _orientation_line() -> str:
    """One-line host orientation: OS, interpreter resolution, mode flags.

    The host+interpreter facts come from the shared
    ``_hook_utils.host_orientation_line()`` (also feeds the SessionStart
    parent-orientation in ``_reinject``); the mode flags are appended here
    UNCONDITIONALLY (cold subagents get the full state, unlike the conditional
    SessionStart twin).
    """
    maintenance = os.environ.get(ENV_VAR) == "1"
    # ONE grammar, shared with every other reader (_hook_utils.stop_gate_mode).
    # This used a raw `or "light"`, so a padded or mis-cased value was reported
    # verbatim while stop_gate resolved it differently.
    stop_mode = stop_gate_mode(os.environ.get(_STOP_GATE_ENV))
    return (
        f"{host_orientation_line()}. "
        f"MAINTENANCE={'on' if maintenance else 'off'} "
        f"STOP_GATE={stop_mode}."
    )


_SCHEMA_POINTER = (
    "If you are a review/audit subagent, return results in the fan-out "
    "FINDING_SCHEMA your parent prompt specified (the parent prompt is the "
    "authoritative copy; this is a belt-and-suspenders reminder, not the "
    "schema source)."
)


def _run_main() -> int:
    # Consume stdin via the shared helper (BOM/UTF-8 safety) even though the
    # SubagentStart payload isn't needed for orientation — the every-hook
    # stdin-discipline contract (tests/test_hook_contracts.py) requires it.
    read_stdin_safely()
    context = "\n".join([_orientation_line(), _SCHEMA_POINTER])
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": context,
        }
    }))
    return 0


def main() -> int:
    """Public entry-point. Fail-OPEN umbrella: subagent_start is an advisory
    SubagentStart reporter, so an uncaught crash must degrade to a no-op
    advisory (exit 0 + one [ERROR] line), never a traceback that breaks
    subagent launch. Mirrors task_router.main.
    """
    try:
        return _run_main()
    except BaseException as exc:  # noqa: BLE001 — fail-open crash guard (advisory hook)
        print(
            f"[ERROR] subagent_start crashed: {type(exc).__name__}: {os_error_text(exc)}",
            file=sys.stderr,
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
