"""Maintenance-mode bypass helper for harness self-edits.

Single env var (`ESPALIER_MAINTENANCE_MODE=1`) opt-in, set in the parent
shell before launching Claude Code. When active, the friction-adding
checks early-return so the harness can edit itself without ceremony:
write_guard's protected-zone check, plan_guard's plan-required check,
stop_gate's docs/review gates and subagent_stop's blueprint append. The
roster IS the set of hooks that call `is_active`; tests/test_maintenance_mode.py
derives it from the hook sources and checks every doc that restates it.
CI (`tools/cc/ci_guard.py`) still gates merges regardless of this flag.

Stdlib-only, zero espalier imports — same pattern as `_integrity.py` and
`_hook_utils.py`. Hooks `sys.path.insert(0, str(Path(__file__).parent))`
and `import _maintenance_mode`.

Visibility: every bypass logs to stderr. Every caller exits 0, and Claude
Code routes the stderr of a hook that exits 0 to its debug log rather than
the transcript, so that line is a debug-log record; the one a session reads
back is the once-per-session audit row its `write_guard`, `plan_guard` and
`stop_gate` callers write -- `subagent_stop`'s bypass writes none, by the
design its own early return states. `/status --log` counts those rows and
`_integrity` holds their two event-type names, which this docstring
deliberately does not repeat: the written-set proof in
tests/test_governance_audit_log.py derives its writer set by grepping this
directory for that spelling, so quoting a row name here would enrol this
helper as a fourth writer. No per-process suppression —
repeated logs are the point.
"""
from __future__ import annotations

import os
import sys

ENV_VAR = "ESPALIER_MAINTENANCE_MODE"


def is_active(hook_name: str, *, action: str = "bypass") -> bool:
    """Return True if MAINTENANCE_MODE is set; log a stderr line when it triggers."""
    if _maintenance_mode_active(os.environ.get(ENV_VAR)):
        # voice: debug-log by design: the per-session audit record and the SessionStart banner carry the bypass
        print(f"[{hook_name}] MAINTENANCE_MODE -- {action}", file=sys.stderr)
        return True
    return False

def _maintenance_mode_active(env_value: str | None) -> bool:
    """Pure bool predicate over ENV_VAR value (no side effects).

    Distinct from ``is_active(hook_name, ...)`` which logs to stderr.
    Used by the truth-table contract test which expects a
    side-effect-free predicate; the existing ``is_active`` is the
    operator-facing form with stderr observability.

    THE one grammar for the value: every reader goes through here (pinned by
    tests/test_maintenance_mode.py::TestNoRawMaintenanceCompare), except
    ``tools/cc/statusline.py``, which sits outside ``hooks/`` and carries a
    lockstep one-liner. Surrounding whitespace is stripped because cmd.exe
    keeps the space before ``&&`` in ``set VAR=1 && claude``, so the session
    receives ``"1 "`` (DEF-992); a raw ``== "1"`` relaunched the operator
    who followed the remedy into the same deny.
    """
    return (env_value or "").strip() == "1"


def relaunch_hint(*, command: str = "claude --continue") -> str:
    """The relaunch an operator types in THEIR OWN terminal, spelled for THIS
    host's shell, backticked and ready to embed in a deny message.

    ``--continue`` by default: the deny that prints this happened INSIDE a
    session, and a bare ``claude`` relaunch starts a new conversation and a
    new blueprint node, losing the one the operator was in (DEF-676). A bare
    ``VAR=1 cmd`` env-prefix is POSIX-only -- pasted into PowerShell it is a
    parse error (DEF-640) -- so on Windows the PowerShell form leads and the
    cmd.exe and Git Bash / WSL forms follow. The cmd.exe form quotes the
    assignment: unquoted, cmd.exe keeps the space before ``&&`` in the value
    (DEF-992, driven 2026-10-01); the readers strip it now, but the quoted
    form is the one that sets exactly ``1`` on any reader.

    Host-keyed on purpose: a hook message is rendered on the operator's machine
    at that moment. Sister of ``espalier.cli._maintenance_mode_invocation``,
    the engine's one dialect-aware renderer, which a hook cannot import
    (zero-espalier-imports rule); keep the dialect list in step by hand.
    ``sys.platform == "win32"`` is this repo's established spelling.
    """
    if sys.platform == "win32":
        return (
            f'`$env:{ENV_VAR}="1"; {command}` (PowerShell) / '
            f'`set "{ENV_VAR}=1" && {command}` (cmd.exe) / '
            f"`{ENV_VAR}=1 {command}` (Git Bash / WSL)"
        )
    return f"`{ENV_VAR}=1 {command}`"
