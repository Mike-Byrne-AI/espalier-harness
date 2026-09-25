#!/usr/bin/env python3
"""PostToolUseFailure hook — Rule A: untrusted-oracle re-derivation on a failed edit.

When an Edit/Write fails on ``old_string``-not-found, the model is reading a
stale or fabricated frame of the file (the phantom-SHA class). This
injects the re-derivation discipline next to the tool result so the NEXT
attempt re-anchors against the real bytes rather than transcribing the stale
Read. No mechanical gate catches this class; no offline review does either.
Stdlib, zero espalier imports, non-blocking.

Protocol contract (cc-hook-protocol.md): PostToolUseFailure fires after a tool
call FAILS (e.g. an Edit whose ``old_string`` is not found) and delivers
``additionalContext`` next-to-result. Exit 0 + ``hookSpecificOutput`` JSON →
inject. This hook is a reporter; it NEVER exits 2.

Matcher: ``Write|Edit|NotebookEdit`` (the edit tools whose old_string
replacement can fail against a stale frame; canonical token order per
``harness_config.matcher_token_string``).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _reinject  # noqa: E402
from _hook_utils import os_error_text, read_stdin_safely, resolve_project_root  # noqa: E402

# The Rule-A TEXT + cap-exempt/priority live in the recall registry
# (_reinject.RULE_A); the FIRING predicate (_is_old_string_failure) stays
# HERE because it keys on the failure payload (tool_response/error), which check()'s
# signature does not carry. This hook calls check() only after its predicate passes.


def _is_old_string_failure(data: dict) -> bool:
    """True iff this is an edit-tool failure whose error is an explicit
    old_string-replacement-match failure (the stale-frame / phantom-SHA class).

    A bare ``"not found" in err`` substring would false-fire on unrelated
    failures — a parent-dir-missing Write ("No such file or directory"),
    "command not found", "module not found", "file not found". Rule A is the
    untrusted-oracle re-derive for a STALE-FRAME edit, NOT a generic error
    reporter; a false reinject next to an unrelated error is banner noise.
    Require an explicit replacement-match-failure shape. (Real Claude Code
    phrasing observed: "String to replace not found in file".)
    """
    tool = data.get("tool_name", "")
    if tool not in ("Edit", "Write", "NotebookEdit"):
        return False
    # Use ``or`` so an explicit ``tool_response: null`` falls through to
    # ``error`` rather than ``json.dumps(None) == "null"`` silently swallowing
    # the failure signal.
    payload = data.get("tool_response") or data.get("error", "")
    err = json.dumps(payload).lower()
    return (
        "old_string" in err
        or "no match" in err
        or "string to replace" in err
    )


def _run_main() -> int:
    data = read_stdin_safely()
    if not _is_old_string_failure(data):
        return 0  # silent for unrelated failures
    # Predicate passed -> dispatch through the registry. The full `data` dict rides
    # the tool_input slot (the RULE-A render ignores it; it returns the text
    # unconditionally for this event). `root` is LOAD-BEARING, not decorative:
    # check() records recall-engine telemetry under `root/.espalier-state/` for
    # every matched rule, cap_exempt ones included, so a sloppy root writes a
    # stray state dir. (It was genuinely unused here before that telemetry landed.)
    payloads = _reinject.check(
        "PostToolUseFailure", data.get("tool_name", ""), data, resolve_project_root(),
    )
    if not payloads:
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUseFailure",
            "additionalContext": "\n".join(payloads),
        }
    }))
    return 0


def main() -> int:
    """Public entry-point. Fail-OPEN umbrella: context_reinject_failure is an
    advisory PostToolUseFailure reporter, so an uncaught crash must degrade to
    a no-op advisory (exit 0 + one [ERROR] line), never a traceback that breaks
    the failed-edit path. Mirrors task_router.main.
    """
    try:
        return _run_main()
    except BaseException as exc:  # noqa: BLE001 — fail-open crash guard (advisory hook)
        print(
            f"[ERROR] context_reinject_failure crashed: {type(exc).__name__}: {os_error_text(exc)}",
            file=sys.stderr,
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
