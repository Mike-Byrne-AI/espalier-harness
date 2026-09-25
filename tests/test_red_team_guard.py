"""Behavioral guard for espalier.red_team_guard.

The guard exists to make a red-team blocker count as verified ONLY when an
independent run reproduces the claimed failure signature — closing the
gate-gaming surface where a finding claims blocks_release with a prose repro that
was never run (or a trivially-failing one that proves nothing). These tests pin
that behavior with REAL subprocess repros (no mocking, so the re-execution is
exercised): a genuinely failing+signed command verifies; a command that fails
for the wrong reason, emits no signature, uses a catch-all match, claims a
blocker via expect="pass", or has an ambiguous id is rejected; and an honest
null (zero blockers) passes so the guard never pressures an agent to manufacture
findings. The discriminating cases are the *_rejected tests — they guard against
the exact theater the module was built to prevent; weaken the signature binding
and they silently go red.
"""
from __future__ import annotations

import sys

from espalier.red_team_guard import (
    format_report,
    guard_findings,
    verify_repro,
)


def _fail_cmd() -> list[str]:
    """An argv that genuinely exits non-zero and emits a 'BOOM' signature."""
    return [sys.executable, "-c", "import sys; sys.stderr.write('BOOM\\n'); sys.exit(1)"]


def _pass_cmd() -> list[str]:
    """An argv that genuinely exits zero (prints 'ok')."""
    return [sys.executable, "-c", "print('ok')"]


def _blocker(fid: str) -> dict:
    """A minimal finding that claims blocks_release."""
    return {
        "id": fid,
        "rule_or_scanner": "lens-a",
        "severity": "blocker",
        "blocks_release": True,
    }


def _signed_repro(fid: str) -> dict:
    """A well-formed blocker repro: fails AND emits its claimed signature."""
    return {"id": fid, "argv": _fail_cmd(), "expect": "fail", "match": "BOOM"}


class TestVerifyRepro:
    def test_real_failure_with_signature_is_verified(self):
        verdict = verify_repro({"id": "f1", "argv": _fail_cmd(), "expect": "fail", "match": "BOOM"})
        assert verdict.ran is True
        assert verdict.observed == "fail"
        assert verdict.verified is True

    def test_real_pass_with_expect_pass_is_verified(self):
        verdict = verify_repro({"id": "f1", "argv": _pass_cmd(), "expect": "pass"})
        assert verdict.observed == "pass"
        assert verdict.verified is True

    def test_claim_fail_but_command_passes_is_unverified(self):
        verdict = verify_repro({"id": "f1", "argv": _pass_cmd(), "expect": "fail", "match": "ok"})
        assert verdict.observed == "pass"
        assert verdict.verified is False

    def test_signature_must_appear_in_output(self):
        missing = verify_repro({"id": "f1", "argv": _fail_cmd(), "expect": "fail", "match": "NOPE"})
        assert missing.verified is False
        assert missing.match_ok is False

    def test_catch_all_match_is_malformed(self):
        # Every _CATCH_ALL_MATCHES spelling must be rejected. `.+` is the ONLY one
        # the empty-string net (`compiled.search("") is None`, red_team_guard.py:116)
        # does not already catch — `.*`, `.*?`, `(.*)`, `^.*$` all re.search-match ""
        # — so `.+` alone makes the literal-set disjunct at line 110 load-bearing:
        # deleting `or value.strip() in _CATCH_ALL_MATCHES` regresses exactly `.+`
        # (it would be wrongly accepted as specific). The rest are pinned as
        # regression insurance so a future net change can't silently re-admit them.
        for pat in [".*", ".+", ".*?", "(.*)", "^.*$"]:
            verdict = verify_repro({"id": "f1", "argv": _fail_cmd(), "expect": "fail", "match": pat})
            assert verdict.observed == "error", pat
            assert verdict.verified is False, pat

    def test_empty_matching_signature_is_malformed(self):
        # CV2 F3: a signature that re.search-matches the empty string fires on ANY
        # (even empty) output, so it carries no signal and must be rejected like the
        # literal catch-alls — even though these spellings are NOT in _CATCH_ALL_MATCHES.
        for pat in ["Z*", r"\d*", "[A-Z]*", "$", "^", ".*.*", "(?:)", "(foo)?"]:
            verdict = verify_repro(
                {"id": "f1", "argv": _fail_cmd(), "expect": "fail", "match": pat}
            )
            assert verdict.observed == "error", pat
            assert verdict.verified is False, pat

    def test_specific_signature_survives_empty_match_guard(self):
        # A real, specific signature (does NOT match "") is still accepted.
        verdict = verify_repro(
            {"id": "f1", "argv": _fail_cmd(), "expect": "fail", "match": "BOOM"}
        )
        assert verdict.verified is True

    def test_invalid_regex_match_does_not_raise(self):
        verdict = verify_repro({"id": "f1", "argv": _fail_cmd(), "expect": "fail", "match": "(unclosed"})
        assert verdict.observed == "error"
        assert verdict.verified is False

    def test_malformed_argv_errors_not_raises(self):
        verdict = verify_repro({"id": "f1", "argv": "not-a-list", "expect": "fail"})
        assert verdict.ran is False
        assert verdict.observed == "error"

    def test_bad_expect_value_errors(self):
        verdict = verify_repro({"id": "f1", "argv": _fail_cmd(), "expect": "explode"})
        assert verdict.observed == "error"
        assert verdict.verified is False


class TestGuardFindings:
    def test_real_blocker_with_signed_reproducing_repro_passes(self):
        result = guard_findings([_blocker("B1")], [_signed_repro("B1")], min_finders=1)
        assert result.passed is True
        assert result.verified_blockers == ("B1",)
        assert result.unverified_blockers == ()

    def test_non_list_findings_fails_closed(self):
        # CV2 F8: a malformed (non-list) findings payload must NOT be silently
        # treated as an honest null (passed=True) — it fails CLOSED with a reason.
        for bad in [{"a": 1}, "some string", 42, None]:
            result = guard_findings(bad, [], min_finders=1)
            assert result.passed is False, bad
            assert result.blocker_count == 0
            assert any("malformed findings payload" in r for r in result.reasons), bad

    def test_empty_findings_is_honest_null_and_passes(self):
        # The genuine empty run still passes — fail-closed must not penalise the null.
        result = guard_findings([], [], min_finders=1)
        assert result.passed is True
        assert result.blocker_count == 0

    def test_trivially_failing_repro_without_signature_is_rejected(self):
        # The /usr/bin/false bypass: command fails but asserts no signature.
        findings = [_blocker("B1")]
        repros = [{"id": "B1", "argv": _fail_cmd(), "expect": "fail"}]  # no match
        result = guard_findings(findings, repros, min_finders=1)
        assert result.passed is False
        assert "B1" in result.unverified_blockers

    def test_failing_repro_with_wrong_signature_is_rejected(self):
        # Command fails, but not with the claimed signature — not bound to the finding.
        findings = [_blocker("B1")]
        repros = [{"id": "B1", "argv": _fail_cmd(), "expect": "fail", "match": "DOES_NOT_APPEAR"}]
        result = guard_findings(findings, repros, min_finders=1)
        assert result.passed is False
        assert "B1" in result.unverified_blockers

    def test_fabricated_blocker_command_passes_is_rejected(self):
        findings = [_blocker("B1")]
        repros = [{"id": "B1", "argv": _pass_cmd(), "expect": "fail", "match": "ok"}]
        result = guard_findings(findings, repros, min_finders=1)
        assert result.passed is False
        assert "B1" in result.unverified_blockers

    def test_blocker_repro_must_expect_fail(self):
        findings = [_blocker("B1")]
        repros = [{"id": "B1", "argv": _pass_cmd(), "expect": "pass", "match": "ok"}]
        result = guard_findings(findings, repros, min_finders=1)
        assert result.passed is False
        assert "B1" in result.unverified_blockers

    def test_blocker_with_catch_all_match_is_rejected(self):
        findings = [_blocker("B1")]
        repros = [{"id": "B1", "argv": _fail_cmd(), "expect": "fail", "match": ".*"}]
        result = guard_findings(findings, repros, min_finders=1)
        assert result.passed is False
        assert "B1" in result.unverified_blockers

    def test_blocker_without_repro_is_unverified(self):
        result = guard_findings([_blocker("B1")], [], min_finders=1)
        assert result.passed is False
        assert "B1" in result.unverified_blockers

    def test_blocker_without_usable_id_is_unverified(self):
        # A None-id blocker cannot bind a repro; a repro keyed "<no-id>" must not rescue it.
        findings = [{"rule_or_scanner": "lens-a", "severity": "blocker", "blocks_release": True}]
        repros = [{"id": "<no-id>", "argv": _fail_cmd(), "expect": "fail", "match": "BOOM"}]
        result = guard_findings(findings, repros, min_finders=1)
        assert result.passed is False

    def test_duplicate_blocker_id_is_ambiguous(self):
        findings = [_blocker("DUP"), _blocker("DUP")]
        result = guard_findings(findings, [_signed_repro("DUP")], min_finders=1)
        assert result.passed is False
        assert result.unverified_blockers == ("DUP", "DUP")

    def test_invalid_regex_in_blocker_repro_does_not_crash_gate(self):
        findings = [_blocker("B1")]
        repros = [{"id": "B1", "argv": _fail_cmd(), "expect": "fail", "match": "(unclosed"}]
        result = guard_findings(findings, repros, min_finders=1)  # must not raise
        assert result.passed is False
        assert "B1" in result.unverified_blockers

    def test_honest_null_passes(self):
        findings = [
            {
                "id": "N1",
                "rule_or_scanner": "lens-a",
                "severity": "minor",
                "blocks_release": False,
            }
        ]
        result = guard_findings(findings, [], min_finders=1)
        assert result.passed is True
        assert result.blocker_count == 0

    def test_diversity_below_floor_warns_not_fails(self):
        result = guard_findings([_blocker("B1")], [_signed_repro("B1")], min_finders=3)
        assert result.diversity_ok is False
        assert result.warnings  # non-empty
        assert result.passed is True  # diversity never fails the gate

    def test_severity_blocker_without_flag_still_gated(self):
        findings = [{"id": "B1", "rule_or_scanner": "lens-a", "severity": "blocker"}]
        result = guard_findings(findings, [], min_finders=1)
        assert result.passed is False
        assert "B1" in result.unverified_blockers

    def test_format_report_renders_pass_and_fail(self):
        passing = guard_findings([], [], min_finders=1)
        report = format_report(passing)
        assert "PASS" in report
        assert "does NOT certify" in report  # residual stated honestly on PASS
        failing = guard_findings([_blocker("B1")], [], min_finders=1)
        assert "FAIL" in format_report(failing)
