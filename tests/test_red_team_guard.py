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

import re
import string
import sys
from itertools import product

import pytest

from espalier.red_team_guard import (
    _CATCH_ALL_MATCHES,
    format_report,
    guard_findings,
    verify_repro,
)

# Signatures one ordinary character satisfies on its own, so each fires on nearly
# any output and cannot tie a failure to its claimed cause. Composed as atom x
# wrapper so the rows cover the family, not a list of spellings: the atoms are the
# bare dot, negated one-character classes (one naming a letter a fixed stand-in set
# would hold), word / non-space / any-character classes, a digit or lowercase
# class, a lone letter, and three that only punctuation or whitespace satisfies (a
# non-word class, a whitespace class, a lone hyphen) -- those pin the net's breadth
# past letters and digits; the wrappers add grouping, a quantifier, a lazy
# quantifier, a bounded repeat, an inline flag, and an alternation with a branch
# that never appears. Spellings already in the literal catch-all set are dropped,
# so every row here was accepted before the single-character net landed.
_ONE_CHARACTER_ATOMS = (
    ".", "[^q]", "[^a]", "[0-9A-Za-z_]", r"\w", r"\S", r"[\s\S]", r"\d", "[a-z]", "e",
    r"\W", r"\s", "-",
)
_SIGNATURE_WRAPPERS = (
    "{}", "({})", "(?:{})", "{}+", "{}+?", "{}{{1,3}}", "(?i){}", "(?:{}|NEVER_PRINTED)",
)
_GENERALISING_SIGNATURES = sorted(
    {wrapper.format(atom) for atom, wrapper in product(_ONE_CHARACTER_ATOMS, _SIGNATURE_WRAPPERS)}
    - _CATCH_ALL_MATCHES
)

# Every `match` value this tree feeds the guard that is meant to be usable. No repro
# artifact (cc/red_team_repros.json) has ever been committed, so the fixtures in
# this file are the whole real population; `Traceback` is the canonical shape a
# red-team writes. U+FFFD is a one-character signature that is not ordinary text:
# a program under test that decodes with replacement prints it, and the guard's
# own strict UTF-8 decode never makes one, so in the captured output it can only
# come from the child. If the guard ever decodes with replacement itself, U+FFFD
# would fire on any mis-encoded output and this row must move to the refused side.
_REAL_SIGNATURES = ("BOOM", "ok", "NOPE", "DOES_NOT_APPEAR", "Traceback", "\ufffd")


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
        # Every _CATCH_ALL_MATCHES spelling must be rejected. Bare, each is now caught
        # by a net as well: `.*`, `.*?`, `(.*)`, `^.*$` re.search-match "", and `.+`
        # is satisfied by one ordinary character. The literal set stays load-bearing
        # only for the space-padded spellings (` .+ ` demands surrounding spaces, so
        # neither net sees it), pinned below; deleting
        # `or value.strip() in _CATCH_ALL_MATCHES` regresses exactly those.
        for pat in [".*", ".+", ".*?", "(.*)", "^.*$", " .+ ", " .* "]:
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

    @pytest.mark.parametrize("pat", _GENERALISING_SIGNATURES)
    def test_signature_one_character_satisfies_is_malformed(self, pat):
        # None of these is a literal catch-all and none matches the empty string,
        # yet each fires on the first ordinary character of any output -- so a
        # repro that failed for an unrelated reason would read as verified. The
        # guard must refuse it before running anything.
        verdict = verify_repro({"id": "f1", "argv": _fail_cmd(), "expect": "fail", "match": pat})
        assert verdict.ran is False, pat
        assert verdict.observed == "error", pat
        assert verdict.verified is False, pat
        assert "is satisfied by" in verdict.detail, pat  # the one-character net, by name

    def test_every_printable_ascii_character_alone_is_refused(self):
        # The net's breadth, pinned by behaviour rather than by the constant: each
        # printable ASCII character, whitespace included, escaped into a literal
        # signature, is refused and the refusal names that character. A stand-in set
        # narrowed to lowercase letters and digits would re-admit a lone `E`, `-`,
        # `:` or a space, and reds here.
        admitted = []
        for ch in string.printable:
            verdict = verify_repro(
                {"id": "f1", "argv": _fail_cmd(), "expect": "fail", "match": re.escape(ch)}
            )
            if verdict.ran or f"is satisfied by {ch!r} alone" not in verdict.detail:
                admitted.append(ch)
        assert admitted == []

    def test_refusal_names_why_the_signature_is_unusable(self):
        # A halted unattended chain is read by an operator after the session ended:
        # the refusal must say which rule fired, not one message for every cause.
        cases = {
            "(unclosed": "is not a valid regex",
            ".*": "is a catch-all",
            "Z*": "matches the empty string",
            r"\w": "is satisfied by '0' alone",  # the first stand-in that fires
        }
        for pat, cause in cases.items():
            verdict = verify_repro({"id": "f1", "argv": _fail_cmd(), "expect": "fail", "match": pat})
            assert verdict.ran is False, pat
            assert cause in verdict.detail, (pat, verdict.detail)

    @pytest.mark.parametrize("pat", _REAL_SIGNATURES)
    def test_real_signature_survives_the_single_character_net(self, pat):
        # The false-reject direction: a real signature (two or more characters, or
        # one character that is not ordinary text) is still run, not refused.
        # Whether it then matches is not asserted: that depends on what the child
        # prints, which a host's start-up noise can change.
        verdict = verify_repro({"id": "f1", "argv": _fail_cmd(), "expect": "fail", "match": pat})
        assert verdict.ran is True, pat
        assert verdict.observed == "fail", pat

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

    @pytest.mark.parametrize("pat", [".*", ".", r"\w"])
    def test_blocker_with_catch_all_match_is_rejected(self, pat):
        # The gate's own per-blocker check reaches the same predicate as
        # verify_repro: a one-character signature is refused here too, before the
        # repro runs, rather than verifying against the first character of output.
        findings = [_blocker("B1")]
        repros = [{"id": "B1", "argv": _fail_cmd(), "expect": "fail", "match": pat}]
        result = guard_findings(findings, repros, min_finders=1)
        assert result.passed is False, pat
        assert result.unverified_blockers == ("B1",), pat
        assert result.verified_blockers == (), pat
        assert result.verdicts == (), pat
        assert any("specific failure signature" in r for r in result.reasons), pat

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
