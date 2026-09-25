"""Self-tests for ``tests/_hook_assertions`` — the
``assert_hook_denied`` / ``assert_hook_allowed`` helpers every hook
test suite delegates to for parsing structured deny/allow payloads.

Pins the helpers' strict parsing: a returncode-0-with-empty-stdout
must NOT count as deny, an ``allow`` decision must NOT pass the
deny assertion, and the deny path requires the full
``hookSpecificOutput.permissionDecision`` shape. Without this guard,
a silent regression in the helpers would make every downstream hook
test pass on the wrong contract, hiding broken deny paths from CI.
"""
from __future__ import annotations

import json
from subprocess import CompletedProcess

import pytest

from tests._hook_assertions import assert_hook_allowed, assert_hook_denied


def _make_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> CompletedProcess:
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestAssertHookDenied:
    def test_passes_on_valid_deny(self):
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "test reason",
            }
        }
        assert_hook_denied(_make_result(stdout=json.dumps(payload)))

    def test_fails_on_returncode_zero_with_empty_stdout(self):
        with pytest.raises(AssertionError, match="JSON deny payload"):
            assert_hook_denied(_make_result(stdout=""))

    def test_fails_on_allow_decision(self):
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }
        with pytest.raises(AssertionError, match="permissionDecision='deny'"):
            assert_hook_denied(_make_result(stdout=json.dumps(payload)))

    def test_fails_on_wrong_event(self):
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "permissionDecision": "deny",
            }
        }
        with pytest.raises(AssertionError, match="hookEventName"):
            assert_hook_denied(_make_result(stdout=json.dumps(payload)))

    def test_contains_reason(self):
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "no active execution plan",
            }
        }
        assert_hook_denied(
            _make_result(stdout=json.dumps(payload)),
            contains_reason="execution plan",
        )

    def test_fails_on_nonzero_returncode(self):
        with pytest.raises(AssertionError, match="rc=2"):
            assert_hook_denied(_make_result(returncode=2, stdout="{}"))


class TestAssertHookAllowed:
    def test_passes_on_empty_stdout(self):
        assert_hook_allowed(_make_result())

    def test_fails_on_deny_payload(self):
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
            }
        }
        with pytest.raises(AssertionError, match="emitted deny"):
            assert_hook_allowed(_make_result(stdout=json.dumps(payload)))

    def test_fails_on_configchange_block(self):
        payload = {"decision": "block", "reason": "kill-switch"}
        with pytest.raises(AssertionError, match="emitted block"):
            assert_hook_allowed(_make_result(stdout=json.dumps(payload)))

    def test_passes_on_non_json_stdout(self):
        # Some hooks log to stdout without JSON; tolerated.
        assert_hook_allowed(_make_result(stdout="some log line\n"))
