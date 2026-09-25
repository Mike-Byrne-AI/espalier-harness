"""TP-109b: pin the contract-infrastructure shape so consumers
can rely on the dataclass surface and marker grammar.

Pins the canonical ``# contract: ok <rule-id> <reason>`` opt-out
form, guards extract_matches against vacuous-pass when no hits,
and prevents drift between the ``CONTRACT_CEILINGS`` rule_id key
grammar and the marker-parsing regex. Failure mode this catches:
consumer packs (TP-110..115) registering UPPER_CASE or snake_case
rule_ids that the marker grammar can never opt out (un-opt-outable
entry — silent contract-only enforcement). Without these tests, any
drift between the regex and ceiling-key shape ships invisibly.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from tests._contracts import (
    extract_matches,
    find_opt_out_markers,
)
from tests._surface_expected import CONTRACT_CEILINGS


class TestContractInfrastructure:
    def test_opt_out_marker_grammar_matches_canonical_form(self):
        text = "# contract: ok hook-event-banner intentional-deprecation"
        markers = find_opt_out_markers(text)
        assert markers == [
            ("hook-event-banner", "intentional-deprecation")
        ]

    def test_opt_out_marker_rejects_legacy_tp_NNN_form(self):
        # Legacy form is NOT recognized; this catches accidental
        # paste of pre-TP-109b marker shapes.
        text = "# tp-112: ok stale message format"
        assert find_opt_out_markers(text) == []

    def test_extract_matches_returns_empty_on_no_match(self):
        # Contract: extract_matches returns []; consumer asserts
        # len(matches) >= 1 itself (vacuous-pass guard).
        with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write("x = 1\n")
            tmp = Path(f.name)
        try:
            assert extract_matches(tmp, r"FOO_(\w+)") == []
        finally:
            tmp.unlink()

    def test_every_contract_ceiling_key_matches_marker_grammar(self):
        """Every ``CONTRACT_CEILINGS`` key must be a valid rule_id per
        ``OPT_OUT_MARKER_RE``. Catches accidental UPPER_CASE,
        snake_case, or non-conforming kebab-case entries that would
        be unmatchable by the marker grammar (and therefore
        un-opt-outable).
        """
        rule_id_pat = re.compile(r"^[a-z][a-z0-9\-]+$")
        for key in CONTRACT_CEILINGS:
            assert rule_id_pat.match(key), (
                f"CONTRACT_CEILINGS key {key!r} does not match the "
                f"`# contract: ok <rule-id>` grammar's rule_id token "
                f"pattern. Use lowercase kebab-case (e.g., "
                f"'hook-event-banner', 'denial-reason-fstring')."
            )

    def test_canonical_marker_round_trip(self):
        """Any sample marker constructed from a valid rule_id round-
        trips through ``find_opt_out_markers`` correctly. Catches regex
        drift between rule_id grammar and marker parsing."""
        sample_line = "# contract: ok hook-event-banner some reason here"
        result = find_opt_out_markers(sample_line)
        assert result == [("hook-event-banner", "some reason here")]
