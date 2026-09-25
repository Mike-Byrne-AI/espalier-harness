"""Hook protocol assertion helpers.

Per Claude Code hook protocol:
- exit 0 + JSON deny payload on stdout = block (PreToolUse shape)
- exit 0 + JSON {"decision": "block"} on stdout = block (Stop / ConfigChange shape)
- exit 0 + empty stdout = allow
- exit 2 = ignored (per docs/SHARP_EDGES.md "Hook Exit Codes — Channel XOR")

A test asserting only `returncode == 0` proves the hook didn't crash; it
does NOT prove a deny was emitted. These helpers enforce the full contract,
closing a class of false-pass regressions identified in TP-13 Task 13-C.

Two protocol shapes:
- PreToolUse: hookSpecificOutput.permissionDecision = "deny"
- ConfigChange / Stop: top-level decision = "block"

assert_hook_denied() handles PreToolUse; assert_hook_allowed() verifies
no-deny across both shapes. Existing ConfigChange tests in
test_kill_switch_blocking_surfaces.py already use direct JSON parse for
the block shape.

Naming contract (load-bearing): the `assert_hook_*` prefix is treated as a
decision-channel observation by BOTH arms of the `test_loosening` scanner —
`nondiscriminating_hook_assert` (deny-side) and `nondiscriminating_hook_allow`
(allow-side) — via the shared `_observes_decision_channel`. A hook test that calls
any `assert_hook_*` helper is judged to discriminate and is NOT flagged by either
arm. Any new helper added here under that prefix MUST actually verify the decision
channel (parse stdout / check permissionDecision or the block shape); a
lifecycle/smoke helper that does not would let a genuinely non-discriminating hook
test call it and silently escape the scanner.
"""
from __future__ import annotations

import json
from subprocess import CompletedProcess


def assert_hook_denied(
    result: CompletedProcess,
    *,
    contains_reason: str | None = None,
    expected_event: str = "PreToolUse",
) -> None:
    """Assert that a PreToolUse-shape hook produced a valid deny payload.

    Verifies: exit 0, valid JSON on stdout, hookSpecificOutput.
    permissionDecision == "deny", hookEventName matches expectation, and
    (optionally) the reason string contains a substring.

    Use this in every regression test whose intent is "this bypass must be
    blocked." Asserting result.returncode == 0 alone is not sufficient —
    that only proves the hook process didn't crash.
    """
    assert result.returncode == 0, (
        f"expected deny (exit 0 + JSON), got rc={result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"expected JSON deny payload on stdout, got: {result.stdout!r}\n"
            f"json.loads raised: {exc}"
        ) from exc

    hook_specific = payload.get("hookSpecificOutput")
    assert hook_specific is not None, (
        f"hook output missing hookSpecificOutput key: {payload!r}"
    )

    decision = hook_specific.get("permissionDecision")
    assert decision == "deny", (
        f"expected permissionDecision='deny', got {decision!r}\n"
        f"full payload: {payload!r}"
    )

    event = hook_specific.get("hookEventName")
    assert event == expected_event, (
        f"expected hookEventName={expected_event!r}, got {event!r}\n"
        f"full payload: {payload!r}"
    )

    if contains_reason is not None:
        reason = hook_specific.get("permissionDecisionReason", "")
        assert contains_reason in reason, (
            f"expected reason to contain {contains_reason!r}, got: {reason!r}"
        )


def assert_hook_allowed(result: CompletedProcess) -> None:
    """Assert that a hook produced an allow (no deny payload).

    Verifies: exit 0 and either empty stdout OR a JSON payload that does NOT
    contain a block decision. Use in tests whose intent is "this is a
    legitimate operation that must pass" or "this command is documented
    out-of-scope."
    """
    assert result.returncode == 0, (
        f"expected allow (exit 0), got rc={result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    if not result.stdout.strip():
        return
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        # Non-JSON stdout from an allowed hook is unusual but not itself a
        # contract violation — some hooks log to stdout.
        return
    decision = (
        payload.get("hookSpecificOutput", {}).get("permissionDecision")
    )
    if decision == "deny":
        raise AssertionError(
            f"expected allow but hook emitted deny payload: {payload!r}"
        )
    cc_decision = payload.get("decision")
    if cc_decision == "block":
        raise AssertionError(
            f"expected allow but hook emitted block payload: {payload!r}"
        )
