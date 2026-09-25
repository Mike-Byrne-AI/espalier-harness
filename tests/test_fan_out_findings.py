"""Parity + behavior contract for the fan-out finding schema and aggregator.

``espalier.fan_out_findings.FINDING_SCHEMA`` is the single source of truth for
the agent-finding wire shape (the markdown doc references it, does not embed
it). This test pins the shape against a frozen EXPECTED set — the
frozenset-as-canon precedent of ``tests/test_execution_plan_schema_parity.py``
— with a negative-proof subtest so the guard earns its red (per the
de-circularization recipe in ``docs/SHARP_EDGES.md``).
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

from espalier.fan_out_findings import (
    FINDING_SCHEMA,
    FindingsSummary,
    _ID_PATTERN,
    _KEY_ANNOTATION_RE,
    _corpus_dedupe_key,
    _dedupe_key,
    _report_unbound_after_write,
    _parse_corpus_findings,
    _render_finding_bullet,
    aggregate_findings,
    append_findings_to_corpus,
    finding_schema_json,
    iter_finding_errors,
)
from tests._git_oracle import require_is_gitignored

REPO_ROOT = Path(__file__).resolve().parents[1]


def _finding(**overrides) -> dict:
    """A complete, schema-conforming finding; override any field per test."""
    base = {
        "id": "espalier/x.py:10",
        "title": "x is wrong",
        "rule_or_scanner": "code-reviewer",
        "named_unit": None,
        "location": "espalier/x.py:10",
        "claim": "thing is wrong",
        "violated_invariant": "things must be right",
        "minimal_repro": "call x()",
        "verification": {"positive": "catches it", "negative": "clears good"},
        "confidence": "high",
        "proposed_fix": "fix x",
        "category": "design_goal",
        "severity": "major",
        "blocks_release": False,
        "refutation_outcome": "survived",
    }
    base.update(overrides)
    return base

# Frozen canon: the 20 top-level properties of a fan-out finding (TP-185 v2).
# Independent of the module so a silent add/drop/rename of a property is caught
# here. The 13 CORE fields are required; the rest are optional, accreted by the
# refuter / aggregator downstream.
EXPECTED_FINDING_PROPERTIES: frozenset[str] = frozenset({
    # CORE (required)
    "id",
    "title",
    "rule_or_scanner",
    "violated_invariant",
    "category",
    "location",
    "claim",
    "minimal_repro",
    "verification",
    "confidence",
    "proposed_fix",
    "severity",
    "blocks_release",
    # OPTIONAL (accreted downstream)
    "named_unit",
    "refutation_outcome",
    "refutation_reason",
    "corrected_confidence",
    "corrected_category",
    "externally_verified",
    "corroboration_count",
})

EXPECTED_REQUIRED_PROPERTIES: frozenset[str] = frozenset({
    "id",
    "title",
    "rule_or_scanner",
    "violated_invariant",
    "category",
    "location",
    "claim",
    "minimal_repro",
    "verification",
    "confidence",
    "proposed_fix",
    "severity",
    "blocks_release",
})

EXPECTED_CONFIDENCE_ENUM: list[str] = ["high", "med", "low"]
EXPECTED_SEVERITY_ENUM: list[str] = ["blocker", "major", "minor", "nit"]
EXPECTED_REFUTATION_OUTCOMES: list[str] = ["unattempted", "survived", "refuted"]
EXPECTED_VERIFICATION_KEYS: frozenset[str] = frozenset({"positive", "negative"})


def _shape_violations(schema: dict) -> list[str]:
    """Structural problems in a finding schema vs the frozen canon.

    Returns ``[]`` for a conforming schema. Used by both the positive
    assertion and the negative-proof: a mutated copy must yield a non-empty
    list, proving the equality checks are load-bearing rather than vacuous.
    """
    problems: list[str] = []
    props = schema.get("properties", {})
    if set(props.keys()) != set(EXPECTED_FINDING_PROPERTIES):
        problems.append("property set != EXPECTED_FINDING_PROPERTIES")
    # v2 (TP-185) split: only the CORE fields are required; the rest are optional.
    if set(schema.get("required", [])) != set(EXPECTED_REQUIRED_PROPERTIES):
        problems.append("required set != EXPECTED_REQUIRED_PROPERTIES")
    conf = props.get("confidence", {})
    if conf.get("enum") != EXPECTED_CONFIDENCE_ENUM:
        problems.append("confidence.enum != ['high','med','low']")
    corrected = props.get("corrected_confidence", {})
    if corrected.get("enum") != EXPECTED_CONFIDENCE_ENUM:
        problems.append("corrected_confidence.enum != ['high','med','low']")
    severity = props.get("severity", {})
    if severity.get("enum") != EXPECTED_SEVERITY_ENUM:
        problems.append("severity.enum != ['blocker','major','minor','nit']")
    # v2 non-string fields: pin the bool/int types (and the integer minimum) so
    # the schema can't silently drift from what iter_finding_errors enforces.
    for boolean_field in ("blocks_release", "externally_verified"):
        if props.get(boolean_field, {}).get("type") != "boolean":
            problems.append(f"{boolean_field}.type != boolean")
    corr = props.get("corroboration_count", {})
    if corr.get("type") != "integer":
        problems.append("corroboration_count.type != integer")
    if corr.get("minimum") != 1:
        problems.append("corroboration_count.minimum != 1")
    outcome = props.get("refutation_outcome", {})
    if outcome.get("enum") != EXPECTED_REFUTATION_OUTCOMES:
        problems.append(
            "refutation_outcome.enum != ['unattempted','survived','refuted']"
        )
    category = props.get("category", {})
    if "enum" in category:
        problems.append("category must NOT carry an enum (domain-supplied vocab)")
    if category.get("type") != ["string", "null"]:
        problems.append("category.type != ['string','null']")
    verification = props.get("verification", {})
    if set(verification.get("required", [])) != set(EXPECTED_VERIFICATION_KEYS):
        problems.append("verification.required != {positive, negative}")
    if set(verification.get("properties", {}).keys()) != set(EXPECTED_VERIFICATION_KEYS):
        problems.append("verification.properties keys != {positive, negative}")
    return problems


class TestFindingSchemaShape:
    def test_schema_matches_frozen_canon(self):
        assert _shape_violations(FINDING_SCHEMA) == []

    def test_schema_is_closed_object(self):
        assert FINDING_SCHEMA["type"] == "object"
        assert FINDING_SCHEMA["additionalProperties"] is False
        assert (
            FINDING_SCHEMA["properties"]["verification"]["additionalProperties"]
            is False
        )

    def test_schema_is_json_serializable(self):
        # It is a wire format — it must round-trip through JSON unchanged.
        assert json.loads(json.dumps(FINDING_SCHEMA)) == FINDING_SCHEMA

    def test_negative_proof_dropped_property_is_caught(self):
        mutated = copy.deepcopy(FINDING_SCHEMA)
        del mutated["properties"]["named_unit"]
        assert _shape_violations(mutated), (
            "dropping a property must register a violation — otherwise the "
            "shape contract is vacuous"
        )

    def test_negative_proof_enum_drift_is_caught(self):
        mutated = copy.deepcopy(FINDING_SCHEMA)
        mutated["properties"]["confidence"]["enum"] = ["high", "medium", "low"]
        assert "confidence.enum != ['high','med','low']" in _shape_violations(mutated)

    def test_negative_proof_refutation_outcome_drift_is_caught(self):
        mutated = copy.deepcopy(FINDING_SCHEMA)
        mutated["properties"]["refutation_outcome"]["enum"] = ["yes", "no"]
        assert any(
            "refutation_outcome.enum" in p for p in _shape_violations(mutated)
        )

    def test_negative_proof_category_must_stay_enum_free(self):
        # category is a DOMAIN-SUPPLIED vocab — adding an in-schema enum is the
        # falsified design and must be flagged so it cannot be frozen.
        mutated = copy.deepcopy(FINDING_SCHEMA)
        mutated["properties"]["category"]["enum"] = ["bug", "design"]
        assert any(
            "category must NOT carry an enum" in p for p in _shape_violations(mutated)
        )

    def test_negative_proof_severity_drift_is_caught(self):
        # The workflows historically used 'critical'; the SoT enum is 'blocker'
        # (it implies blocks_release). A drift back must be flagged.
        mutated = copy.deepcopy(FINDING_SCHEMA)
        mutated["properties"]["severity"]["enum"] = ["critical", "major", "minor", "nit"]
        assert any("severity.enum" in p for p in _shape_violations(mutated))

    def test_negative_proof_required_split_is_caught(self):
        # The v2 CORE/optional split is load-bearing: promoting an optional field
        # (named_unit) back into `required` must register a violation, otherwise
        # the split is vacuous.
        mutated = copy.deepcopy(FINDING_SCHEMA)
        mutated["required"] = list(mutated["required"]) + ["named_unit"]
        assert "required set != EXPECTED_REQUIRED_PROPERTIES" in _shape_violations(
            mutated
        )

    def test_negative_proof_corrected_confidence_enum_drift_is_caught(self):
        # The corrected_confidence enum is pinned to the same canon as confidence;
        # a drift must be flagged (this check was previously unwitnessed).
        mutated = copy.deepcopy(FINDING_SCHEMA)
        mutated["properties"]["corrected_confidence"]["enum"] = ["high", "medium", "low"]
        assert any(
            "corrected_confidence.enum" in p for p in _shape_violations(mutated)
        )

    def test_negative_proof_typed_field_drift_is_caught(self):
        # The v2 bool/int fields must stay pinned so the schema can't drift away
        # from iter_finding_errors' runtime type checks.
        for field in ("blocks_release", "externally_verified", "corroboration_count"):
            mutated = copy.deepcopy(FINDING_SCHEMA)
            mutated["properties"][field]["type"] = "string"
            assert any(field in p for p in _shape_violations(mutated)), field
        # the integer minimum is pinned too
        mutated = copy.deepcopy(FINDING_SCHEMA)
        mutated["properties"]["corroboration_count"]["minimum"] = 0
        assert any(
            "corroboration_count.minimum" in p for p in _shape_violations(mutated)
        )


class TestIdPattern:
    """W1-B: the id `pattern` is PERMISSIVE — it accepts the legacy {path:line}
    handle AND the new namespaced TP-N:LABEL, so external-agent findings without
    TP context are never rejected (friction-averse). The schema carries the
    pattern (StructuredOutput enforces it); these tests pin that it is neither
    over-strict (rejects real ids) nor vacuous."""

    pat = re.compile(_ID_PATTERN)

    def test_schema_id_carries_the_pattern(self):
        assert FINDING_SCHEMA["properties"]["id"]["pattern"] == _ID_PATTERN

    def test_accepts_legacy_and_namespaced(self):
        for good in ("espalier/cli.py:965", "TP-184:B2", "TP-1:A", "a-bare-token"):
            assert self.pat.match(good), good

    def test_rejects_garbage_earns_the_red(self):
        # Without a negative, an accept-everything regex would be vacuous.
        for bad in ("", "a: b"):
            assert not self.pat.match(bad), bad

    # A `test_accepts_full_round0_corpus` lived here: it asserted that 100% of a
    # real round-0 findings corpus matched `_ID_PATTERN`, as a regression guard
    # against the regex becoming over-strict. It was DELETED as structurally
    # unreachable — its fixture was `task-packs/TP-169-round0-findings.json`,
    # `task-packs/` was gitignored, and the file exists in no checkout and in no
    # commit in this repo's history (`git rev-list --all --objects` → 0 hits), so
    # the skip fired everywhere and it was never once executed.
    #
    # Deliberately NOT replaced with a synthesized fixture: the test's whole
    # value was that its input was REAL, and hand-authored ids would only restate
    # the three cases above while reading like real-world coverage. The id
    # pattern's three alternatives (`TP-N:LABEL`, `path:token`, bare) are each
    # covered by `test_accepts_legacy_and_namespaced`, with the negatives in
    # `test_rejects_garbage_earns_the_red`; what deletion loses is volume on real
    # data, not a distinct shape.


class TestIterFindingErrors:
    def test_valid_finding_has_no_errors(self):
        assert iter_finding_errors(_finding()) == []

    def test_non_object_is_rejected(self):
        assert iter_finding_errors("not a dict") == ["finding is not an object"]

    def test_missing_required_field(self):
        bad = _finding()
        del bad["claim"]
        assert "missing required field: claim" in iter_finding_errors(bad)

    def test_unexpected_field(self):
        assert "unexpected field: bogus_extra" in iter_finding_errors(
            _finding(bogus_extra="x")
        )

    def test_verification_rejects_unexpected_subkey(self):
        """R3: additionalProperties:false applies INSIDE verification too — an
        injected sub-key must be flagged, mirroring the top-level check (the real
        schema + StructuredOutput reject it; the light validator must as well)."""
        bad = _finding(
            verification={"positive": "p", "negative": "n", "INJECTED": "x"}
        )
        assert "verification unexpected field: 'INJECTED'" in iter_finding_errors(bad)

    def test_bad_confidence_enum(self):
        errors = iter_finding_errors(_finding(confidence="medium"))
        assert any("confidence not in enum" in e for e in errors)

    def test_severity_enum_earns_the_red(self):
        # W1-A earn-the-red: a bad severity errors, a good one passes.
        assert any(
            "severity not in enum" in e
            for e in iter_finding_errors(_finding(severity="catastrophic"))
        )
        assert iter_finding_errors(_finding(severity="blocker")) == []

    def test_blocks_release_must_be_bool(self):
        # An int 1 must NOT pass as the boolean gate flag (bool-is-int trap).
        assert "blocks_release must be a boolean" in iter_finding_errors(
            _finding(blocks_release=1)
        )
        assert iter_finding_errors(_finding(blocks_release=True)) == []

    def test_corrected_confidence_enum(self):
        assert any(
            "corrected_confidence not in enum" in e
            for e in iter_finding_errors(_finding(corrected_confidence="medium"))
        )
        assert iter_finding_errors(_finding(corrected_confidence="low")) == []

    def test_corrected_category_accepts_string_or_null(self):
        assert iter_finding_errors(_finding(corrected_category=None)) == []
        assert iter_finding_errors(_finding(corrected_category="rebucketed")) == []
        assert "corrected_category must be a string or null" in iter_finding_errors(
            _finding(corrected_category=123)
        )

    def test_externally_verified_must_be_bool(self):
        assert "externally_verified must be a boolean" in iter_finding_errors(
            _finding(externally_verified="yes")
        )
        assert iter_finding_errors(_finding(externally_verified=True)) == []

    def test_corroboration_count_must_be_positive_int(self):
        assert iter_finding_errors(_finding(corroboration_count=3)) == []
        # bool is a subclass of int but is not a valid count
        assert "corroboration_count must be an integer >= 1" in iter_finding_errors(
            _finding(corroboration_count=True)
        )
        assert "corroboration_count must be an integer >= 1" in iter_finding_errors(
            _finding(corroboration_count=0)
        )
        # a float and a numeric string are both rejected (not ints)
        assert "corroboration_count must be an integer >= 1" in iter_finding_errors(
            _finding(corroboration_count=1.5)
        )
        assert "corroboration_count must be an integer >= 1" in iter_finding_errors(
            _finding(corroboration_count="3")
        )

    def test_named_unit_optional_after_demote(self):
        # W1-C narrow demote: a finding WITHOUT named_unit is valid (a generic
        # agent with no coinage vocab omits it) — it is no longer required.
        f = _finding()
        del f["named_unit"]
        assert iter_finding_errors(f) == []

    def test_refutation_outcome_optional_after_demote(self):
        # W1-D: refutation_outcome is set by the refuter, absent at finder time.
        f = _finding()
        del f["refutation_outcome"]
        assert iter_finding_errors(f) == []

    def test_title_is_required_core(self):
        f = _finding()
        del f["title"]
        assert "missing required field: title" in iter_finding_errors(f)

    def test_verification_must_have_both_halves(self):
        errors = iter_finding_errors(_finding(verification={"positive": "x"}))
        assert "verification.negative missing" in errors

    def test_bad_refutation_outcome_enum(self):
        errors = iter_finding_errors(_finding(refutation_outcome="maybe"))
        assert any("refutation_outcome not in enum" in e for e in errors)

    def test_category_accepts_string_or_null(self):
        assert iter_finding_errors(_finding(category=None)) == []
        assert iter_finding_errors(_finding(category="anything")) == []

    def test_bad_category_type(self):
        errors = iter_finding_errors(_finding(category=123))
        assert "category must be a string or null" in errors

    def test_required_string_field_must_be_str(self):
        # A null/non-str value for a plain string-typed field is rejected — the
        # dedupe fallback key (location, claim) relies on these being real strings.
        assert "claim must be a string" in iter_finding_errors(_finding(claim=None))
        assert "location must be a string" in iter_finding_errors(_finding(location=42))

    def test_named_unit_wrong_type(self):
        # named_unit may be str or null; an int is rejected. The validator
        # docstring advertises this branch but it was previously unwitnessed.
        errors = iter_finding_errors(_finding(named_unit=123))
        assert "named_unit must be a string or null" in errors

    def test_verification_not_an_object(self):
        # verification must be an object; a string is rejected (advertised but
        # previously untested branch).
        errors = iter_finding_errors(_finding(verification="catches it"))
        assert "verification must be an object" in errors

    def test_verification_subvalues_must_be_strings(self):
        """LANEA-05 earn-the-red: presence was checked, type was not.

        Pre-fix this returned [] — the finding counted as `valid` and flowed
        into dedup, corroboration and the persisted corpus, even though the
        StructuredOutput layer would have rejected it.
        """
        errors = iter_finding_errors(
            _finding(verification={"positive": 1, "negative": None})
        )
        assert "verification.positive must be a string" in errors
        assert "verification.negative must be a string" in errors

    def test_verification_subvalue_checks_derive_from_the_schema(self):
        """The sub-value checks read FINDING_SCHEMA, not a restated tuple.

        Second, orthogonal mutation: asserting only the two field names today
        would pass against a hand-kept ("positive", "negative") literal — the
        exact shape that let the type gap exist. Adding a string field to the
        verification sub-schema must make it validated with no edit to
        iter_finding_errors; a restated tuple stays blind and this goes red.
        """
        sub = FINDING_SCHEMA["properties"]["verification"]
        original = sub["properties"]
        try:
            sub["properties"] = {**original, "caveat": {"type": "string"}}
            errors = iter_finding_errors(
                _finding(
                    verification={"positive": "a", "negative": "b", "caveat": 7}
                )
            )
        finally:
            sub["properties"] = original
        assert "verification.caveat must be a string" in errors, (
            "a field added to the verification sub-schema was not type-checked "
            "— the checks have drifted back into a hand-kept literal"
        )

    def test_boolean_and_integer_checks_derive_from_the_schema(self):
        """The type loop must cover every declared type, not only strings.

        Found by the failure-mode review of this pack: the docstring claimed
        "a field added to the schema is validated without editing this
        function", but the derived loops filtered on type == "string" while
        boolean / integer / nullable-string were three hand-kept tuples. A
        boolean or integer field added later was a DECLARED property, so the
        no-extra-keys check passed it through and nothing type-checked it.
        """
        props = FINDING_SCHEMA["properties"]
        original = dict(props)
        try:
            props["auto_promoted"] = {"type": "boolean"}
            props["rank"] = {"type": "integer"}
            errors = iter_finding_errors(_finding(auto_promoted="yes", rank="three"))
        finally:
            FINDING_SCHEMA["properties"] = original
        assert "auto_promoted must be a boolean" in errors
        assert "rank must be an integer" in errors

    def test_range_checked_field_keeps_its_combined_message(self):
        """`corroboration_count` states type AND range in one error.

        It is excluded from the derived type loop via _RANGE_CHECKED_FIELDS so
        the two do not both fire, which would replace the specific message with
        a weaker one. Pins that the exclusion has not dropped the type half.
        """
        from espalier.fan_out_findings import _RANGE_CHECKED_FIELDS

        assert "corroboration_count" in _RANGE_CHECKED_FIELDS
        for bad in (True, "3", 0):
            assert "corroboration_count must be an integer >= 1" in (
                iter_finding_errors(_finding(corroboration_count=bad))
            ), f"{bad!r} slipped past the combined type+range check"


class TestAggregateFindings:
    def test_dedupes_by_location_and_named_unit(self):
        dup = _finding(location="a.py:1", named_unit="convergence theater")
        other = _finding(location="b.py:2", named_unit="convergence theater")
        summary = aggregate_findings([dup, dict(dup), other], known_units=[])
        assert summary.total == 3
        assert summary.unique == 2
        assert summary.duplicates == 1

    def test_same_location_different_unit_not_deduped(self):
        a = _finding(location="a.py:1", named_unit="convergence theater")
        b = _finding(location="a.py:1", named_unit="stealth contracts")
        summary = aggregate_findings([a, b], known_units=[])
        assert summary.unique == 2

    def test_counts_by_category_and_confidence(self):
        findings = [
            _finding(location="a:1", category="bug", confidence="high"),
            _finding(location="b:2", category="bug", confidence="low"),
            _finding(location="c:3", category="design", confidence="high"),
        ]
        summary = aggregate_findings(findings, known_units=[])
        assert summary.by_category == {"bug": 2, "design": 1}
        assert summary.by_confidence == {"high": 2, "low": 1}

    def test_survival_rate(self):
        findings = [
            _finding(location="a:1", refutation_outcome="survived"),
            _finding(location="b:2", refutation_outcome="survived"),
            _finding(location="c:3", refutation_outcome="refuted"),
        ]
        summary = aggregate_findings(findings, known_units=[])
        assert summary.survival_rate == 2 / 3
        assert summary.by_refutation_outcome == {"survived": 2, "refuted": 1}

    def test_survival_rate_none_when_uncontested(self):
        # All unattempted -> nothing contested -> None (distinct from "all refuted").
        findings = [_finding(location="a:1", refutation_outcome="unattempted")]
        summary = aggregate_findings(findings, known_units=[])
        assert summary.survival_rate is None

    def test_empty_input(self):
        summary = aggregate_findings([], known_units=[])
        assert summary.total == 0
        assert summary.unique == 0
        assert summary.survival_rate is None

    def test_unknown_named_unit_flagged_against_explicit_vocab(self):
        findings = [
            _finding(location="a:1", named_unit="convergence theater"),
            _finding(location="b:2", named_unit="made up thing"),
            _finding(location="c:3", named_unit=None),
        ]
        summary = aggregate_findings(
            findings, known_units=["convergence theater", "stealth contracts"]
        )
        assert summary.vocab_checked is True
        assert summary.unknown_named_units == ["made up thing"]

    def test_named_unit_match_is_case_insensitive(self):
        findings = [_finding(location="a:1", named_unit="Convergence Theater")]
        summary = aggregate_findings(findings, known_units=["convergence theater"])
        assert summary.unknown_named_units == []

    def test_default_vocab_recognizes_real_coinage(self):
        # No explicit known_units -> loads the harness coinage set.
        findings = [
            _finding(location="a:1", named_unit="convergence theater"),
            _finding(location="b:2", named_unit="definitely not a coinage"),
        ]
        summary = aggregate_findings(findings)
        assert summary.vocab_checked is True
        assert "convergence theater" not in summary.unknown_named_units
        assert "definitely not a coinage" in summary.unknown_named_units

    def test_returns_findings_summary_type(self):
        assert isinstance(aggregate_findings([], known_units=[]), FindingsSummary)

    def test_unknown_named_units_dedupe_is_case_insensitive(self):
        # Two casings of the same unknown coinage collapse to one entry,
        # matching the case-insensitive membership test; first-seen casing wins.
        findings = [
            _finding(location="a:1", named_unit="made up thing"),
            _finding(location="b:2", named_unit="Made Up Thing"),
        ]
        summary = aggregate_findings(findings, known_units=["convergence theater"])
        assert summary.unknown_named_units == ["made up thing"]

    def test_vocab_uncheckable_degrades_gracefully(self, monkeypatch):
        # When the coinage catalog cannot be read, the aggregator sets
        # vocab_checked=False and leaves unknown_named_units empty rather than
        # flagging every named_unit (the docstring's adopter-degradation promise).
        def _raise():
            raise FileNotFoundError("no FAILURE_MODES.md here")

        monkeypatch.setattr(
            "espalier.fan_out_findings.load_failure_mode_coinages", _raise
        )
        summary = aggregate_findings([_finding(location="a:1", named_unit="anything")])
        assert summary.vocab_checked is False
        assert summary.unknown_named_units == []

    def test_findings_attr_is_the_deduped_set(self):
        # FindingsSummary.findings carries the deduped (not raw) finding list,
        # each survivor a COPY enriched with corroboration_count (caller input is
        # never mutated).
        dup = _finding(location="a:1", named_unit="convergence theater")
        raw = [dup, dict(dup)]
        summary = aggregate_findings(raw, known_units=[])
        assert len(summary.findings) == 1
        survivor = summary.findings[0]
        assert survivor["corroboration_count"] == 2
        # The caller's finding was NOT mutated.
        assert "corroboration_count" not in dup
        # Stripping the aggregator-added key recovers the original finding.
        assert {k: v for k, v in survivor.items() if k != "corroboration_count"} == dup

    def test_corroboration_count_counts_independent_finders(self):
        # Three independent agents surface the SAME finding (same location+unit);
        # one other agent surfaces a distinct one. corroboration_count reflects
        # the multiplicity that was previously discarded.
        same = _finding(location="a:1", named_unit="convergence theater")
        other = _finding(location="b:2", named_unit="stealth contracts")
        summary = aggregate_findings(
            [same, dict(same), dict(same), other], known_units=[]
        )
        counts = {f["location"]: f["corroboration_count"] for f in summary.findings}
        assert counts == {"a:1": 3, "b:2": 1}
        assert summary.corroborated == 1  # only a:1 has count > 1

    def test_effective_confidence_uses_corrected(self):
        # by_confidence aggregates on the refuter's corrected_confidence when
        # present, the finder's confidence otherwise.
        findings = [
            _finding(location="a:1", confidence="high", corrected_confidence="low"),
            _finding(location="b:2", confidence="high"),
        ]
        summary = aggregate_findings(findings, known_units=[])
        assert summary.by_confidence == {"low": 1, "high": 1}

    def test_effective_category_uses_corrected(self):
        # by_category aggregates on corrected_category when the key is present.
        findings = [
            _finding(location="a:1", category="bug", corrected_category="design"),
            _finding(location="b:2", category="bug"),
        ]
        summary = aggregate_findings(findings, known_units=[])
        assert summary.by_category == {"design": 1, "bug": 1}

    def test_externally_verified_count(self):
        findings = [
            _finding(location="a:1", externally_verified=True),
            _finding(location="b:2", externally_verified=False),
            _finding(location="c:3"),  # field absent
        ]
        summary = aggregate_findings(findings, known_units=[])
        assert summary.externally_verified == 1

    def test_unknown_categories_flagged(self):
        # category is validated against a DOMAIN-SUPPLIED known_categories,
        # mirroring known_units; out-of-vocab categories surface for triage.
        findings = [
            _finding(location="a:1", category="known"),
            _finding(location="b:2", category="bogus"),
        ]
        summary = aggregate_findings(
            findings, known_units=[], known_categories=["known"]
        )
        assert summary.categories_checked is True
        assert summary.unknown_categories == ["bogus"]
        # known_categories=None skips the check entirely (no canonical SoT).
        s2 = aggregate_findings([_finding(location="a:1", category="x")], known_units=[])
        assert s2.categories_checked is False
        assert s2.unknown_categories == []

    def test_category_none_is_a_single_bucket(self):
        # Keystone of the redesign: category=None is ONE visible bucket, not N
        # unique strings — the aggregation actually aggregates.
        findings = [
            _finding(location="a:1", category=None),
            _finding(location="b:2", category=None),
        ]
        summary = aggregate_findings(findings, known_units=[])
        assert summary.by_category == {None: 2}

    def test_unknown_categories_dedupe_is_case_insensitive(self):
        # Sister to the unknown_named_units case-insensitive dedupe (5fe6a69).
        findings = [
            _finding(location="a:1", category="made up cat"),
            _finding(location="b:2", category="Made Up Cat"),
        ]
        summary = aggregate_findings(
            findings, known_units=[], known_categories=["known"]
        )
        assert summary.unknown_categories == ["made up cat"]

    def test_malformed_finding_does_not_crash(self):
        # A non-dict element must not AttributeError the whole batch — it lands
        # in `invalid`. The documented use case is aggregating many LLM returns.
        summary = aggregate_findings(["x"], known_units=[])
        assert summary.invalid == 1
        assert summary.valid == 0

    def test_invalid_count_partitions(self):
        # valid + invalid == total over a mixed batch (one good, two malformed).
        findings = [_finding(location="a:1"), "bad", {"not": "a finding"}]
        summary = aggregate_findings(findings, known_units=[])
        assert summary.total == 3
        assert summary.valid == 1
        assert summary.valid + summary.invalid == summary.total

    def test_distinct_findings_same_location_null_unit_not_collapsed(self):
        # Two distinct novel findings (named_unit=None) at the same location but
        # different claim must NOT collapse — the (location, claim) dedupe key.
        findings = [
            _finding(location="a:1", named_unit=None, claim="first"),
            _finding(location="a:1", named_unit=None, claim="second"),
        ]
        summary = aggregate_findings(findings, known_units=[])
        assert summary.unique == 2
        assert {f["claim"] for f in summary.findings} == {"first", "second"}

    def test_distinct_findings_same_location_empty_unit_not_collapsed(self):
        # TP-168 #8: named_unit="" is NOT a coinage — it must route to the
        # (location, claim) branch exactly like None. Pre-fix, "" is not None so
        # it collapsed two distinct co-located findings into one ("U", loc, "")
        # key. Found by dogfooding aggregate_findings on its own review output.
        findings = [
            _finding(location="a:1", named_unit="", claim="first"),
            _finding(location="a:1", named_unit="", claim="second"),
        ]
        summary = aggregate_findings(findings, known_units=[])
        assert summary.unique == 2
        assert {f["claim"] for f in summary.findings} == {"first", "second"}

    def test_empty_named_unit_is_not_an_unknown_coinage(self):
        # The unknown_named_units loop must also treat "" as no-unit, else an
        # empty string leaks into the unknown-coinage triage list.
        summary = aggregate_findings(
            [_finding(location="a:1", named_unit="")], known_units=[]
        )
        assert summary.unknown_named_units == []

    def test_dedupe_key_namespaces_are_disjoint(self):
        # A unit-set finding and a null-unit finding at the same location must NOT
        # collide even when the coinage string equals the other's claim — the
        # residual F5-b collision the namespace tag ('U'/'C') closes.
        findings = [
            _finding(location="a:1", named_unit="collide", claim="cl"),
            _finding(location="a:1", named_unit=None, claim="collide"),
        ]
        summary = aggregate_findings(findings, known_units=[])
        assert summary.unique == 2

    def test_malformed_dict_routed_to_invalid(self):
        # A dict that fails iter_finding_errors (non-str named_unit) routes to
        # `invalid`, not a crash — pins the iter_finding_errors half of the F5-a
        # partition (known_units non-empty so the old unit.strip() path would fire).
        summary = aggregate_findings([_finding(named_unit=123)], known_units=["x"])
        assert summary.invalid == 1
        assert summary.valid == 0

    def test_survival_rate_zero_when_all_refuted(self):
        # The None-vs-0.0 boundary: all-refuted is a real fraction (0.0), distinct
        # from uncontested (None) — the distinction the design rests on.
        findings = [
            _finding(location="a:1", refutation_outcome="refuted"),
            _finding(location="b:2", refutation_outcome="refuted"),
        ]
        summary = aggregate_findings(findings, known_units=[])
        assert summary.survival_rate == 0.0

    def test_null_claim_finding_is_invalid(self):
        # claim is a load-bearing string field (the dedupe fallback key); a null
        # claim is malformed and lands in `invalid` rather than silently collapsing.
        findings = [
            _finding(location="a:1", named_unit=None, claim=None),
            _finding(location="a:1", named_unit=None, claim=None),
        ]
        summary = aggregate_findings(findings, known_units=[])
        assert summary.valid == 0
        assert summary.invalid == 2


class TestEmittedSchemaParity:
    """The `python -m` emit must reproduce the exact FINDING_SCHEMA constant.

    This is the JS-Workflow export path (F3): a JS orchestrator that cannot
    import Python emits the schema on demand instead of hand-copying a mirror
    that would drift. Mirrors the subprocess idiom of tests/test_main_module.py.
    """

    def test_helper_matches_constant(self):
        assert json.loads(finding_schema_json()) == FINDING_SCHEMA

    def test_module_emits(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-m", "espalier.fan_out_findings"],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == FINDING_SCHEMA


class TestDedupeKeyAnnotationNormalization:
    """A stored resolution annotation must not participate in the dedup key.

    A bulk migration prefixed ``**[RESOLVED ...]**`` INTO the claim text of part of
    the corpus, and the claim IS the ``("C", location, claim)`` key's third element.
    So an annotated stored entry and its bare re-find keyed DIFFERENTLY, and the
    re-find re-appended as new -- on every round, forever. Normalizing the
    annotation out for key purposes makes the two sides agree again.
    """

    def test_annotated_claim_keys_equal_to_its_bare_re_find(self):
        # The whole point: the stored (annotated) entry and the fresh re-find are
        # the SAME finding and must collapse to one key.
        annotated = _finding(
            named_unit=None,
            location="a/b.py::sym",
            claim="**[RESOLVED 2026-01-01]** the widget leaks",
        )
        bare = _finding(named_unit=None, location="a/b.py::sym", claim="the widget leaks")
        assert _dedupe_key(annotated) == _dedupe_key(bare)

    def test_annotation_whose_body_contains_a_bracket_is_still_stripped(self):
        # THE EARN-THE-RED, and the reason the pattern is non-greedy rather than a
        # negated character class. A negated class `[^\]]*` stops at the FIRST `]`
        # -- which inside the annotation body is not the terminator -- so it fails
        # on exactly the inputs that mention bracketed code. Live, that was one
        # entry in ninety-eight: the pattern failing on the single input containing
        # its own delimiter. Assert the asymmetry; do not merely describe it.
        body_has_bracket = "**[RESOLVED — see cleaned[2:] handling]** the widget leaks"
        negated_class = re.compile(r"^\s*\*\*\[(?:RESOLVED|FIXED)\b[^\]]*\]\*\*\s*", re.S)

        assert _KEY_ANNOTATION_RE.match(body_has_bracket), "non-greedy must match"
        assert not negated_class.match(body_has_bracket), (
            "the negated-class variant must FAIL here -- if this ever passes, the "
            "asymmetry that justifies the non-greedy form is gone and the comment "
            "on _KEY_ANNOTATION_RE needs re-deriving"
        )

        annotated = _finding(named_unit=None, location="a/b.py::sym", claim=body_has_bracket)
        bare = _finding(named_unit=None, location="a/b.py::sym", claim="the widget leaks")
        assert _dedupe_key(annotated) == _dedupe_key(bare)

    def test_only_a_LEADING_annotation_is_stripped(self):
        # A bracketed span mid-claim is CONTENT, not an annotation. Stripping it
        # would merge two genuinely distinct findings -- a split's mirror image and
        # the one direction this normalization must never take.
        mid = _finding(
            named_unit=None,
            location="a/b.py::sym",
            claim="the widget **[RESOLVED nope]** leaks",
        )
        other = _finding(named_unit=None, location="a/b.py::sym", claim="the widget leaks")
        assert _dedupe_key(mid) != _dedupe_key(other)

    def test_normalization_is_monotonic_never_splits(self):
        # Two claims equal BEFORE normalization must stay equal after. Stripping may
        # only MERGE keys that should have been one; a split would unbind a stored
        # entry from its own re-find, which is the failure this fix exists to end.
        a = _finding(named_unit=None, location="a/b.py::sym", claim="same text")
        b = _finding(named_unit=None, location="a/b.py::sym", claim="same text")
        assert _dedupe_key(a) == _dedupe_key(b)

    def test_named_unit_branch_is_untouched(self):
        # The ("U", ...) keyspace never held the annotation and must not be
        # normalized -- the two keyspaces are deliberately disjoint.
        f = _finding(named_unit="**[RESOLVED x]** coinage", location="a/b.py::sym")
        assert _dedupe_key(f) == ("U", "a/b.py::sym", "**[RESOLVED x]** coinage")

    def test_non_string_claim_keys_without_raising(self):
        # Callers treat the key as total. A malformed payload must key, not explode.
        f = _finding(named_unit=None, location="a/b.py::sym", claim=None)
        assert _dedupe_key(f) == ("C", "a/b.py::sym", None)


class TestAppendFindingsToCorpus:
    """The persist/append side of a round's findings file (TP-185 W2; the shared
    cross-pack corpus it once fed by default was retired 2026-09-21).

    Reuses ``_dedupe_key`` (via ``_corpus_dedupe_key``) so re-running a review
    does not re-append findings already recorded — the corpus's reason to exist.
    """

    def _corpus(self, tmp_path, body):
        p = tmp_path / "findings.md"
        p.write_text(body, encoding="utf-8")
        return p

    def test_appends_new_findings_and_bumps_count(self, tmp_path):
        p = self._corpus(tmp_path, "# Known findings\n\n## SURVIVED (0)\n")
        n = append_findings_to_corpus(
            p,
            [
                _finding(location="a.py:1", claim="first defect", severity="major"),
                _finding(location="b.py:2", claim="second defect", severity="minor"),
            ],
        )
        assert n == 2
        text = p.read_text(encoding="utf-8")
        assert "## SURVIVED (2)" in text
        assert "- `a.py:1` [major] first defect" in text
        assert "- `b.py:2` [minor] second defect" in text

    def test_idempotent_reappend_is_byte_identical(self, tmp_path):
        # Earn-the-red for the dedup contract: a second identical run adds nothing
        # and does not churn the file. A broken dedup would re-append (n>0).
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        findings = [_finding(location="a.py:1", claim="dupe", severity="major")]
        assert append_findings_to_corpus(p, findings) == 1
        first = p.read_text(encoding="utf-8")
        assert append_findings_to_corpus(p, findings) == 0
        assert p.read_text(encoding="utf-8") == first

    def test_same_location_distinct_claim_not_collapsed(self, tmp_path):
        # F5-b discipline: two findings at one location with different claims are
        # distinct entries, not a single collapsed bullet.
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        n = append_findings_to_corpus(
            p,
            [
                _finding(location="a.py:1", claim="defect one"),
                _finding(location="a.py:1", claim="defect two"),
            ],
        )
        assert n == 2

    def test_intra_batch_duplicate_appended_once(self, tmp_path):
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        f = _finding(location="a.py:1", claim="same", severity="major")
        assert append_findings_to_corpus(p, [f, dict(f)]) == 1

    def test_creates_section_when_absent(self, tmp_path):
        p = self._corpus(tmp_path, "# Known findings\n\n## SURVIVED (0)\n")
        n = append_findings_to_corpus(
            p, [_finding(location="x:1", claim="refuted thing")], section="REFUTED"
        )
        assert n == 1
        text = p.read_text(encoding="utf-8")
        assert "## REFUTED (1)" in text
        assert "- `x:1`" in text
        assert "## SURVIVED (0)" in text  # the other section is untouched

    def test_creates_file_when_absent(self, tmp_path):
        p = tmp_path / "nope.md"
        assert not p.exists()
        assert append_findings_to_corpus(p, [_finding(location="x:1", claim="c")]) == 1
        assert "## SURVIVED (1)" in p.read_text(encoding="utf-8")

    def test_non_dict_elements_skipped(self, tmp_path):
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        n = append_findings_to_corpus(
            p, [_finding(location="a:1", claim="real"), "not a dict", None]
        )
        assert n == 1

    def test_appends_after_existing_bullets(self, tmp_path):
        p = self._corpus(
            tmp_path, "## SURVIVED (1)\n\n- `old.py:1` [major] existing defect\n"
        )
        append_findings_to_corpus(
            p, [_finding(location="new.py:2", claim="fresh", severity="minor")]
        )
        text = p.read_text(encoding="utf-8")
        assert "## SURVIVED (2)" in text
        # Existing bullet preserved; the new one follows it.
        assert text.index("old.py:1") < text.index("new.py:2")

    def test_round_trip_parse_render(self):
        # A rendered bullet parses back to the same (location, claim) — the
        # property that makes re-append idempotent.
        f = _finding(location="z.py:9", claim="round trips", severity="nit")
        assert _parse_corpus_findings(_render_finding_bullet(f)) == [
            {"location": "z.py:9", "claim": "round trips"}
        ]

    def test_parses_severity_optional_refuted_shape(self):
        # The seeded REFUTED entries carry no [severity] bracket; parse must
        # still recover location + claim from that shape.
        survived = "- `a.py:1` [critical] strips one leading slash"
        refuted = "- `b.py:2` deploy_harness emits no warning"
        assert _parse_corpus_findings(survived + "\n" + refuted) == [
            {"location": "a.py:1", "claim": "strips one leading slash"},
            {"location": "b.py:2", "claim": "deploy_harness emits no warning"},
        ]

    # --- idempotency under adversarial field shapes (TP-185 W2 adversarial pass).
    # Each appends, then re-appends the SAME finding; the second call must add
    # nothing. Keying on the render->parse round-trip is what makes these hold.

    def test_idempotent_location_with_backtick(self, tmp_path):
        # A backtick in the location truncates the rendered bullet's first field;
        # keying on the render->parse projection still re-dedups it.
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        f = _finding(location="a.py`weird:1", claim="c", severity="major")
        assert append_findings_to_corpus(p, [f]) == 1
        assert append_findings_to_corpus(p, [f]) == 0

    def test_idempotent_location_with_leading_backtick(self, tmp_path):
        # The sibling the test ABOVE masked. It picked the INTERIOR backtick,
        # which survives because `[^`]+` still has a character to match and both
        # dedup sides agree on the truncated value. A LEADING backtick renders
        # ``- ``x`` …``, which `_CORPUS_BULLET_RE` matches NOWHERE — the entry
        # never enters the seen-set and re-appends forever. Reproduced at 611fbc1
        # as [1, 1, 1] appended with _parse_corpus_findings recovering 0.
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        f = _finding(
            location="`espalier/fan_out_findings.py`:677",
            claim="a leading-backtick location",
            severity="major",
        )
        assert append_findings_to_corpus(p, [f]) == 1
        assert append_findings_to_corpus(p, [f]) == 0
        assert append_findings_to_corpus(p, [f]) == 0

        text = p.read_text(encoding="utf-8")
        assert "## SURVIVED (1)" in text
        parsed = _parse_corpus_findings(text)
        assert len(parsed) == 1
        # ONLY the leading run is shed. The interior backtick still truncates
        # the field, exactly as it did before — deliberately unchanged, because
        # the immutable reports/ records are already keyed on the truncated form
        # (see _normalize_location). The entry is parseable, which is the whole
        # property at stake; it is not required to be pretty.
        assert parsed[0]["location"] == "espalier/fan_out_findings.py"

    def test_interior_backtick_location_is_left_truncated_not_cleaned(self, tmp_path):
        # Pins the NARROWNESS as a property, so a future "tidy up the location"
        # change has to argue with a test instead of silently unbinding the
        # per-round reports from the corpus.
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        f = _finding(location="a.py:1 (`sym`)", claim="c", severity="major")
        assert append_findings_to_corpus(p, [f]) == 1
        assert append_findings_to_corpus(p, [f]) == 0
        assert _parse_corpus_findings(p.read_text(encoding="utf-8"))[0]["location"] == (
            "a.py:1 ("
        )

    def test_backtick_only_location_is_rejected_not_written(self, tmp_path):
        # The guard and the renderer share _normalize_location, so a location the
        # renderer would empty is refused HERE instead of landing as ``- `` …``.
        # Without the shared normaliser the raw-value guard passed it through.
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        f = _finding(location="``", claim="degenerate", severity="major")
        assert append_findings_to_corpus(p, [f]) == 0
        assert "- `" not in p.read_text(encoding="utf-8")

    def test_degenerate_key_raises_rather_than_returning_an_unmatchable_value(self):
        """A finding that cannot survive the corpus round-trip must be LOUD.

        The old fallback keyed it on the raw projection — a value no parsed corpus
        entry can ever equal, so the finding re-appended on every single run. That
        is the failure this module exists to prevent, expressed as silence. It is
        reachable only by a caller that skipped the writer's guard, so the raise
        fires on programmer error, never on data.
        """
        for location in ("``", "` `", "\n"):
            with pytest.raises(ValueError, match="does not survive the corpus round-trip"):
                _corpus_dedupe_key({"location": location, "claim": "c", "severity": "major"})

    def test_writer_still_skips_a_degenerate_finding_without_raising(self, tmp_path):
        # The raise above must NOT change writer behaviour for data: the guard runs
        # first, so a degenerate finding is skipped exactly as before. If this ever
        # raises, a review round loses every survivor in the batch over one bad
        # record -- the precise outcome the raise was chosen to avoid causing.
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        degenerate = [
            _finding(location=loc, claim="c", severity="major") for loc in ("``", "` `", "\n")
        ]
        assert append_findings_to_corpus(p, degenerate) == 0

    def test_a_degenerate_finding_does_not_block_its_batch(self, tmp_path):
        # Blast-radius arm: one unwritable record must not cost the good ones.
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        batch = [
            _finding(location="``", claim="degenerate", severity="major"),
            _finding(location="real/file.py::sym", claim="a real one", severity="major"),
        ]
        assert append_findings_to_corpus(p, batch) == 1
        assert "a real one" in p.read_text(encoding="utf-8")

    def test_post_write_check_is_silent_when_everything_round_trips(self, tmp_path):
        # The ordinary path must stay quiet, and the return value must be exactly
        # what it was before the check existed.
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            n = append_findings_to_corpus(
                p, [_finding(location="a.py::x", claim="one"),
                    _finding(location="b.py::y", claim="two")]
            )
        assert n == 2
        # Filtered on the MESSAGE, not the category. This test is about the
        # post-write round-trip check being silent; `RuntimeWarning` is also
        # what `_corpus_write_lock` emits on a host with no fcntl, where it
        # fires on every call by design. A category-only filter therefore
        # caught a warning this test never meant to police and reddened on
        # Windows for a reason unrelated to what it asserts. The sibling
        # below pins the same string from the positive direction.
        unparsed = [
            w for w in caught
            if issubclass(w.category, RuntimeWarning)
            and "did not re-parse" in str(w.message)
        ]
        assert unparsed == []

    def test_post_write_check_reports_a_finding_that_does_not_round_trip(self, tmp_path):
        # A finding stored but unfindable is re-found and re-appended every round,
        # and the writer's own return value cannot see it -- it counts what it MEANT
        # to append. This is the check that makes that visible.
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        append_findings_to_corpus(p, [_finding(location="a.py::x", claim="one")])
        with pytest.warns(RuntimeWarning, match="did not re-parse under their own dedupe key"):
            unbound = _report_unbound_after_write(p, [("C", "never/stored.py", "nope")])
        assert unbound == [("C", "never/stored.py", "nope")]

    def test_post_write_check_never_routes_through_the_raising_key_function(
        self, tmp_path, monkeypatch
    ):
        """The composed failure: 432-D's raise reaching the check built not to raise.

        `_corpus_dedupe_key` raises on a degenerate finding. If the post-write check
        recomputed keys with it, that raise would propagate out of a verification
        step and lose the round's survivors -- the exact failure the check exists to
        detect, caused by the check. It reuses the pre-write keys instead, so the
        raising function is never on this path.
        """
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        append_findings_to_corpus(p, [_finding(location="a.py::x", claim="one")])

        def _boom(_f):
            raise ValueError("432-D degenerate raise")

        monkeypatch.setattr(
            "espalier.fan_out_findings._corpus_dedupe_key", _boom
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert _report_unbound_after_write(p, [("C", "a.py::x", "one")]) == []
        assert [w for w in caught if issubclass(w.category, RuntimeWarning)] == []

    def test_no_post_write_calls_to_the_fresh_side_key_function(self, tmp_path, monkeypatch):
        # The structural half of the arm above: count the calls. One per candidate
        # finding, all before the write. Any extra means someone recomputed.
        import espalier.fan_out_findings as mod

        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        real, calls = mod._corpus_dedupe_key, []

        def _counting(f):
            calls.append(1)
            return real(f)

        monkeypatch.setattr(mod, "_corpus_dedupe_key", _counting)
        n = append_findings_to_corpus(
            p, [_finding(location="c.py::z", claim="three"),
                _finding(location="d.py::w", claim="four")]
        )
        assert n == 2
        assert len(calls) == 2, f"expected one call per candidate, got {len(calls)}"

    def test_report_never_raises_under_warnings_as_error(self, tmp_path):
        """`-W error` must not turn the report into the failure it reports on.

        The hole this pins: the fallback handler's own warning lives OUTSIDE the
        try/except by necessity, so a bare `warnings.warn` there escapes when an
        ambient filter escalates warnings to exceptions -- `PYTHONWARNINGS=error`,
        `python -W error`, or a `filterwarnings = ["error"]` a future hygiene pass
        might reasonably add to pyproject. The append has already hit disk by that
        point, so the caller would see an exception from a function contracted
        never to produce one, and a review round would lose its survivors to its
        own verification step. Both arms below ran RED before `_warn_never_raise`.

        Each arm asserts the warning is STILL EMITTED, not merely that nothing
        raised. Without that half the test is vacuous: a `_warn_never_raise` that
        silently swallowed everything would satisfy "never raises" while deleting
        the only signal the check produces -- trading a loud failure for the exact
        silence this pack exists to end.
        """
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        append_findings_to_corpus(p, [_finding(location="a.py::x", claim="one")])

        # Arm 1: the ordinary "unbound" report, under warnings-as-error.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("error")
            assert _report_unbound_after_write(p, [("C", "never/stored.py", "nope")]) == [
                ("C", "never/stored.py", "nope")
            ]
        assert any("did not re-parse" in str(w.message) for w in caught), (
            "no raise, but no report either -- the channel was silenced, not hardened"
        )

        # Arm 2: the FALLBACK report -- the one outside the try -- under the same
        # filter, with the verification itself broken so the fallback is reached.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("error")
            broken = tmp_path / "does-not-exist" / "c.md"
            assert _report_unbound_after_write(broken, [("C", "a.py::x", "one")]) == []
        assert any("verification failed" in str(w.message) for w in caught), (
            "the fallback swallowed its own report"
        )

    def test_post_write_check_swallows_its_own_failure(self, tmp_path, monkeypatch):
        # Belt-and-braces: even if the verification itself breaks, the append stands.
        # A check that can destroy the output it verifies is worse than no check.
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        monkeypatch.setattr(
            "espalier.fan_out_findings._parse_corpus_findings",
            lambda _t: (_ for _ in ()).throw(RuntimeError("parser exploded")),
        )
        with pytest.warns(RuntimeWarning, match="post-write corpus verification failed"):
            assert _report_unbound_after_write(p, [("C", "a.py::x", "one")]) == []

    def test_idempotent_claim_trailing_and_inner_whitespace(self, tmp_path):
        # _render_finding_bullet collapses whitespace; the dedup key must agree.
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        f = _finding(location="a.py:1", claim="defect   with   spaces  ", severity="major")
        assert append_findings_to_corpus(p, [f]) == 1
        assert append_findings_to_corpus(p, [f]) == 0

    def test_idempotent_claim_with_embedded_newlines(self, tmp_path):
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        f = _finding(location="a.py:1", claim="line one\nline two", severity="minor")
        assert append_findings_to_corpus(p, [f]) == 1
        assert append_findings_to_corpus(p, [f]) == 0

    def test_idempotent_location_with_embedded_newlines(self, tmp_path):
        # The sibling site the claim fix above missed for five weeks (a C1
        # half-landed fix: _render_finding_bullet collapsed `claim` and not
        # `location`). A newline in location split the bullet across two physical
        # lines, so _CORPUS_BULLET_RE matched neither, the entry never entered the
        # seen-set, and it re-appended on EVERY run while inflating (N).
        # Reproduced [1,1,1,1] with 0 parseable entries at cb8c46f.
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        f = _finding(
            location="espalier/cli.py:10\nespalier/cli.py:20",
            claim="a newline-carrying location",
            severity="major",
        )
        assert append_findings_to_corpus(p, [f]) == 1
        assert append_findings_to_corpus(p, [f]) == 0
        assert append_findings_to_corpus(p, [f]) == 0

        text = p.read_text(encoding="utf-8")
        # ONE parseable bullet, on ONE physical line, and the count stays honest.
        assert "## SURVIVED (1)" in text
        parsed = _parse_corpus_findings(text)
        assert len(parsed) == 1
        assert parsed[0]["location"] == "espalier/cli.py:10 espalier/cli.py:20"
        assert parsed[0]["claim"] == "a newline-carrying location"

    def test_already_corrupted_multiline_entry_is_recovered_not_reappended(self, tmp_path):
        # Half 2 of the fix, and the half that sanitizing alone cannot deliver:
        # a corpus written by the PRE-FIX writer already holds split bullets.
        # Collapsing on write stops new corruption but leaves existing corruption
        # immortal — the entry stays unparseable, so it re-appends forever.
        # Recovery must key the salvaged entry the same way the fixed writer keys
        # a fresh one, or the dedup still misses.
        p = self._corpus(
            tmp_path,
            "## SURVIVED (1)\n\n"
            "- `espalier/cli.py:10\nespalier/cli.py:20` [major] a newline-carrying location\n",
        )
        f = _finding(
            location="espalier/cli.py:10\nespalier/cli.py:20",
            claim="a newline-carrying location",
            severity="major",
        )
        assert append_findings_to_corpus(p, [f]) == 0
        assert "## SURVIVED (1)" in p.read_text(encoding="utf-8")

    def test_multiline_recovery_does_not_swallow_following_content(self, tmp_path):
        # Second, orthogonal mutation on the recovery path: the continuation scan
        # must stop at the closing backtick, not run on into neighbouring bullets
        # or headings. A greedy join would eat the next entry and silently shrink
        # the corpus — a worse failure than the one being fixed.
        p = self._corpus(
            tmp_path,
            "## SURVIVED (2)\n\n"
            "- `a.py:1\na.py:2` [major] split entry\n"
            "- `b.py:3` [minor] intact neighbour\n",
        )
        parsed = _parse_corpus_findings(p.read_text(encoding="utf-8"))
        assert [e["location"] for e in parsed] == ["a.py:1 a.py:2", "b.py:3"]
        assert [e["claim"] for e in parsed] == ["split entry", "intact neighbour"]

    def test_unterminated_backtick_is_not_recovered_across_a_blank_line(self, tmp_path):
        # The bound on recovery: an unterminated bullet followed by a blank line
        # or a heading is malformed prose, not a split entry. Recovering across
        # that boundary would invent entries out of surrounding text.
        text = (
            "## SURVIVED (0)\n\n"
            "- `a.py:1 an unterminated bullet\n"
            "\n"
            "## REFUTED (0)\n"
        )
        assert _parse_corpus_findings(text) == []

    def test_idempotent_severity_bearing_claim_leading_bracket(self, tmp_path):
        # TP-186 adversarial S1: a severity-bearing finding whose CLAIM begins with
        # a bracket (the "[State: LANDED] but OWED" shape the landing-audit finder
        # emits) once double-wrote on every re-run. The stored entry re-rendered
        # without its real [severity], so the claim's own leading bracket was
        # mis-read as severity and the dedup key diverged. Reproduced [1,1,1,1].
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        f = _finding(
            location="task-packs/Done/TP-156.md",
            claim="[State: LANDED] but check_born_weak_guard.py is OWED",
            severity="major",
        )
        assert append_findings_to_corpus(p, [f]) == 1
        assert append_findings_to_corpus(p, [f]) == 0
        assert append_findings_to_corpus(p, [f]) == 0

    def test_idempotent_claim_leading_with_a_severity_word_bracket(self, tmp_path):
        # The harder edge the projection-render close: a claim that begins with a
        # literal severity word in brackets ("[major] ...") must also re-dedup, not
        # just a non-severity bracket. Keying on the {location, claim} projection
        # (severity dropped on both sides) makes the two round-trips symmetric.
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        f = _finding(location="x.py:1", claim="[major] regression in the parser", severity="minor")
        assert append_findings_to_corpus(p, [f]) == 1
        assert append_findings_to_corpus(p, [f]) == 0

    def test_skips_findings_missing_location_or_claim(self, tmp_path):
        # A bullet stores only location + claim; a finding missing either (None or
        # empty — iter_finding_errors permits "") must not persist a degenerate
        # bullet. Only the one real finding is appended.
        p = self._corpus(tmp_path, "## SURVIVED (0)\n")
        n = append_findings_to_corpus(
            p,
            [
                _finding(location="", claim="has no location"),
                _finding(location="a.py:1", claim=""),
                _finding(location=None, claim="none location"),
                _finding(location="b.py:2", claim="real one", severity="major"),
            ],
        )
        assert n == 1
        text = p.read_text(encoding="utf-8")
        assert "- `b.py:2` [major] real one" in text
        # No degenerate / claimless bullets leaked in.
        assert "- `` " not in text
        assert "has no location" not in text
        assert "none location" not in text


class TestCorpusWriteLock:
    """TP-436-A: the corpus read-modify-write is serialized across processes.

    ``append_findings_to_corpus`` reads the whole file, splices, and replaces
    it atomically. An atomic *replace* is not an atomic *update*: two rounds
    that both read the same pre-state both replace it, and the first writer's
    appends vanish while BOTH calls return a success count.

    Per ``docs/FAILURE_MODES.md`` §2.9 no assertion here is decided by a
    ``sleep``. The threads are event-coordinated, and each proof is written so
    that removing the lock turns it RED (proven in-suite by
    ``test_lost_update_is_real_without_the_lock``, which drives the unlocked
    path directly).
    """

    def _corpus(self, tmp_path):
        p = tmp_path / "findings.md"
        p.write_text("# Known findings\n\n## SURVIVED (0)\n", encoding="utf-8")
        return p

    def test_lost_update_is_real_without_the_lock(self, tmp_path, monkeypatch):
        """The defect the lock exists to close, driven on the UNLOCKED path.

        This is the earn-the-red: with ``_HAS_FCNTL`` false the module takes
        exactly the code path it had before TP-436, and a deterministic
        interleaving destroys one round's appends while both report success.
        """
        import threading

        from espalier import fan_out_findings as fof

        monkeypatch.setattr(fof, "_HAS_FCNTL", False)
        corpus = self._corpus(tmp_path)

        b_finished = threading.Event()
        a_may_write = threading.Event()
        real_write = fof.atomic_write_text

        def coordinating_write(path, text):
            # The FIRST writer (A) parks here — after its read, before its
            # write — until B has completed its entire read-modify-write.
            # No sleep decides this; B signals.
            if threading.current_thread().name == "round-A":
                a_may_write.set()
                b_finished.wait(timeout=10)
            return real_write(path, text)

        monkeypatch.setattr(fof, "atomic_write_text", coordinating_write)

        results = {}

        def round_a():
            results["a"] = append_findings_to_corpus(
                corpus, [_finding(location="a.py:1", claim="from round A")]
            )

        def round_b():
            a_may_write.wait(timeout=10)   # A has read; B now reads the SAME state
            results["b"] = append_findings_to_corpus(
                corpus, [_finding(location="b.py:2", claim="from round B")]
            )
            b_finished.set()

        ta = threading.Thread(target=round_a, name="round-A")
        tb = threading.Thread(target=round_b, name="round-B")
        ta.start(); tb.start(); ta.join(timeout=15); tb.join(timeout=15)

        text = corpus.read_text(encoding="utf-8")
        # BOTH calls reported success...
        assert results == {"a": 1, "b": 1}, results
        # ...but only one round's finding survived. This is the failure mode.
        assert "from round A" in text
        assert "from round B" not in text, (
            "the unlocked read-modify-write unexpectedly preserved both writes; "
            "this proof no longer earns its red"
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX fcntl only")
    def test_concurrent_appends_both_survive_with_the_lock(self, tmp_path):
        """The same two rounds, on the real (locked) path: nothing is lost.

        The lock makes the interleaving above unreachable, so this runs the
        threads without coordination — the assertion is on the OUTCOME the
        lock guarantees, not on any observed timing.

        HONEST BOUND: this is the one proof in the class whose red is
        PROBABILISTIC rather than structural. It cannot force the interleaving
        (coordinating the threads under a working lock deadlocks by
        construction), so it relies on the RMW window — a file read, a parse, a
        splice, an atomic replace — being wide enough for the race to
        materialise. Measured at authoring time: 5 of 5 runs FAILED with the
        lock replaced by a nullcontext. The structural proofs are
        ``test_second_writer_blocks_while_the_first_holds_the_lock`` (mutex)
        and ``test_lock_wraps_read_through_post_write_verification``
        (wrap-order); if this one ever flakes green, fix it by deleting it, not
        by widening a timeout.
        """
        import threading

        corpus = self._corpus(tmp_path)
        results = {}

        def run(tag, loc, claim):
            results[tag] = append_findings_to_corpus(
                corpus, [_finding(location=loc, claim=claim)]
            )

        threads = [
            threading.Thread(target=run, args=("a", "a.py:1", "from round A")),
            threading.Thread(target=run, args=("b", "b.py:2", "from round B")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        text = corpus.read_text(encoding="utf-8")
        assert results == {"a": 1, "b": 1}, results
        assert "from round A" in text
        assert "from round B" in text

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX fcntl only")
    def test_second_writer_blocks_while_the_first_holds_the_lock(self, tmp_path):
        """Mutex proof (§2.9 form (a)): B provably does not enter while A holds.

        Goes RED if ``_corpus_write_lock`` is replaced with a no-op: B would
        then complete immediately and ``b_done.wait`` would return True while A
        still holds.
        """
        import threading

        from espalier.fan_out_findings import _corpus_write_lock

        corpus = self._corpus(tmp_path)
        b_done = threading.Event()
        b_started = threading.Event()
        a_holds = threading.Event()
        a_may_release = threading.Event()

        def hold_the_lock():
            with _corpus_write_lock(corpus):
                a_holds.set()
                a_may_release.wait(timeout=10)

        def contender():
            b_started.set()
            append_findings_to_corpus(
                corpus, [_finding(location="b.py:2", claim="from round B")]
            )
            b_done.set()

        ta = threading.Thread(target=hold_the_lock)
        ta.start()
        assert a_holds.wait(timeout=10), "holder never acquired the lock"

        tb = threading.Thread(target=contender)
        tb.start()
        # The contender must be RUNNING before its non-completion means
        # anything. Without this the proof degrades to a tautology under load:
        # on a busy box the thread may simply not be scheduled inside the
        # bounded wait below, and the test would pass because B never started
        # rather than because B blocked — passing for the wrong reason under
        # exactly the conditions that would also mask a real regression.
        assert b_started.wait(timeout=10), "contender thread never started"
        # A negative with a bound: without the lock B completes at once and
        # this returns True. The lock is what makes it False.
        entered_early = b_done.wait(timeout=1.0)
        assert not entered_early, (
            "the second writer completed while the first held the lock — the "
            "corpus RMW is not mutually excluded"
        )

        a_may_release.set()
        ta.join(timeout=10)
        assert b_done.wait(timeout=10), "second writer never completed after release"
        tb.join(timeout=10)
        assert "from round B" in corpus.read_text(encoding="utf-8")

    def test_lock_wraps_read_through_post_write_verification(self, tmp_path, monkeypatch):
        """Wrap-order proof (§2.9 form (b)): enter < read < write < verify < exit.

        A lock held only across the write would close nothing — the lost-update
        window opens at the read. This asserts the span mechanically rather
        than trusting the call site to look right.
        """
        import contextlib

        from espalier import fan_out_findings as fof

        order: list[str] = []
        real_lock = fof._corpus_write_lock
        real_write = fof.atomic_write_text
        real_verify = fof._report_unbound_after_write

        @contextlib.contextmanager
        def spy_lock(path):
            order.append("lock-enter")
            with real_lock(path):
                yield
            order.append("lock-exit")

        def spy_write(path, text):
            order.append("write")
            return real_write(path, text)

        def spy_verify(path, keys):
            order.append("verify")
            return real_verify(path, keys)

        monkeypatch.setattr(fof, "_corpus_write_lock", spy_lock)
        monkeypatch.setattr(fof, "atomic_write_text", spy_write)
        monkeypatch.setattr(fof, "_report_unbound_after_write", spy_verify)

        corpus = self._corpus(tmp_path)
        real_read = type(corpus).read_text

        def spy_read(self, *a, **kw):
            if self == corpus:
                order.append("read")
            return real_read(self, *a, **kw)

        monkeypatch.setattr(type(corpus), "read_text", spy_read)
        append_findings_to_corpus(
            corpus, [_finding(location="a.py:1", claim="spanned")]
        )

        assert order[0] == "lock-enter", order
        assert order[-1] == "lock-exit", order
        assert order.index("read") < order.index("write") < order.index("verify"), order

    def test_append_still_succeeds_when_fcntl_is_unavailable(self, tmp_path, monkeypatch):
        """Criterion 2: a lock that cannot be taken must never cost a round its
        survivors. Simulates the Windows / flock-less path via the same
        ``_HAS_FCNTL`` guard ``espalier.freshness`` uses."""
        from espalier import fan_out_findings as fof

        monkeypatch.setattr(fof, "_HAS_FCNTL", False)
        corpus = self._corpus(tmp_path)
        assert append_findings_to_corpus(
            corpus, [_finding(location="a.py:1", claim="unlocked but written")]
        ) == 1
        assert "unlocked but written" in corpus.read_text(encoding="utf-8")

    def test_append_succeeds_when_the_lock_file_cannot_be_created(
        self, tmp_path, monkeypatch
    ):
        """The other never-raise path: an unwritable directory yields UNLOCKED
        rather than erroring. A locking failure must not become the §C14
        failure it exists to prevent."""
        import builtins

        corpus = self._corpus(tmp_path)
        real_open = builtins.open

        def refuse_lock_file(file, *a, **kw):
            if str(file).endswith(".lock"):
                raise OSError("read-only filesystem")
            return real_open(file, *a, **kw)

        monkeypatch.setattr(builtins, "open", refuse_lock_file)
        assert append_findings_to_corpus(
            corpus, [_finding(location="a.py:1", claim="lockfile refused")]
        ) == 1
        assert "lockfile refused" in corpus.read_text(encoding="utf-8")

    def _written_lock_names(self, tmp_path) -> list[str]:
        from espalier.fan_out_findings import _corpus_write_lock

        corpus = self._corpus(tmp_path)
        with _corpus_write_lock(corpus):
            pass
        return [p.name for p in tmp_path.iterdir() if p.name.endswith(".lock")]

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX fcntl only")
    def test_lock_sentinel_is_a_sibling_dotfile(self, tmp_path):
        """The NAME half, split out so an export keeps it.

        This drives `_corpus_write_lock` entirely under `tmp_path` against
        shipped code, so it is answerable anywhere -- and it is the only pin on
        the sentinel's filename. It used to share a body with the gitignore
        assertion below, which needs a real worktree; registering that body as a
        full-tree invariant (2026-08-14) therefore silenced this half too, on
        exactly the artifact where the shipped locking code runs.
        """
        assert self._written_lock_names(tmp_path) == [".findings.md.write.lock"]

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX fcntl only")
    def test_lock_sentinel_is_a_tracked_dirs_gitignored_artifact(self, tmp_path):
        """The CLAIM half: whatever the name is, git must ignore it.

        Asserts the claim, not just the name. The earlier version asserted the
        hard-coded filename while its docstring claimed gitignore coverage — so
        the one thing it said was protected was the one thing untested, and a
        rename could satisfy the assertion while silently producing an untracked
        artifact in a tracked directory.
        """
        locks = self._written_lock_names(tmp_path)
        assert locks, (
            "no lock sentinel was written, so the gitignore claim below "
            "would be asserted about nothing -- an IndexError here used to "
            "hide that as a crash rather than name it."
        )

        # Checked
        # against the repo's own .gitignore, at a path inside a TRACKED dir.
        #
        # §C21/`DEF-573`: "the repo's OWN .gitignore" is the load-bearing phrase
        # and a bare rc read does not deliver it. With REPO_ROOT inside another
        # worktree's ignored directory, `check-ignore` returns rc 0 for every
        # name ever asked, so this positive assertion passed on a release archive
        # extracted under `dist/` while failing on the same archive unpacked
        # outside a worktree. The oracle refuses rather than answering about the
        # wrong tree.
        rel = f"docs/{locks[0]}"
        ignored = require_is_gitignored(REPO_ROOT, rel)
        assert ignored, (
            f"{rel} is NOT gitignored — the lock sentinel would land as an "
            f"untracked artifact in a tracked directory. Fix the .gitignore "
            f"pattern or the sentinel name; do not delete this assertion."
        )

    @pytest.mark.parametrize(
        "degrade",
        ["no_fcntl", "flock_unsupported", "lockfile_unopenable"],
    )
    def test_every_lock_degrade_path_preserves_survivors_and_warns(
        self, tmp_path, monkeypatch, degrade
    ):
        """The never-raise contract has THREE holes, not two, and each must
        also be OBSERVABLE.

        ``flock`` itself raises ``OSError`` (ENOTSUP / ENOLCK) on flock-less
        mounts — NFS, SMB, some FUSE and bind mounts — so a successful ``import
        fcntl`` does not mean the syscall works. That path was unguarded and
        cost the round every survivor while the docstring above promised it
        never would.

        Each path also warns, because a lock silently never taken is a
        mechanism with no reader — on Windows that is every run, forever. The
        warning rides the channel the persist payload already captures.
        """
        import builtins

        from espalier import fan_out_findings as fof

        # Without fcntl the module returns at the `_HAS_FCNTL` branch before
        # `flock` is called or a `.lock` file is opened, so neither of those
        # arms can be staged. `flock_unsupported` then errors outright
        # (`fcntl` is None), while `lockfile_unopenable` quietly PASSES via
        # the no_fcntl path -- reporting coverage of a path it never entered.
        # The no_fcntl arm is the live one on such a host and still runs.
        if degrade in ("flock_unsupported", "lockfile_unopenable") and not fof._HAS_FCNTL:
            pytest.skip(
                f"{degrade} is unreachable without fcntl; the no_fcntl arm "
                f"covers this host's only degrade path"
            )

        if degrade == "no_fcntl":
            monkeypatch.setattr(fof, "_HAS_FCNTL", False)
        elif degrade == "flock_unsupported":
            def unsupported(*_a):
                raise OSError(45, "Operation not supported")
            monkeypatch.setattr(fof.fcntl, "flock", unsupported)
        else:
            real_open = builtins.open

            def refuse_lock_file(file, *a, **kw):
                if str(file).endswith(".lock"):
                    raise OSError("read-only filesystem")
                return real_open(file, *a, **kw)
            monkeypatch.setattr(builtins, "open", refuse_lock_file)

        corpus = self._corpus(tmp_path)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            n = append_findings_to_corpus(
                corpus, [_finding(location="a.py:1", claim="survived the degrade")]
            )
        assert n == 1
        assert "survived the degrade" in corpus.read_text(encoding="utf-8")
        assert any("UNLOCKED" in str(w.message) for w in caught), (
            f"the {degrade} degrade path took no lock and said nothing — "
            f"a mechanism with no reader. Warnings seen: "
            f"{[str(w.message) for w in caught]}"
        )


class TestCorpusDestinationValidation:
    """TP-436-D: a wrong working directory must not fork a second corpus.

    ``atomic_write_text`` calls ``mkdir(parents=True, exist_ok=True)``, so a
    caller that resolves a relative corpus path against the wrong cwd does not
    error — it creates a brand-new file, writes every survivor into it, and
    returns a success count. The round reports "151 appended" and the tracked
    corpus never changes.
    """

    def test_missing_corpus_is_created_by_default(self, tmp_path):
        """The per-round-report caller shape: creating is correct here, and
        must stay the default. This is the arm that makes the guard opt-in."""
        target = tmp_path / "reports" / "round-42.md"
        assert not target.exists()
        n = append_findings_to_corpus(
            target, [_finding(location="a.py:1", claim="new round, new report")]
        )
        assert n == 1
        assert target.exists()

    def test_missing_corpus_is_refused_when_existence_is_required(self, tmp_path):
        """The shared-corpus caller shape: absence is a wrong-cwd bug."""
        target = tmp_path / "docs" / "findings.md"
        with pytest.raises(FileNotFoundError) as excinfo:
            append_findings_to_corpus(
                target,
                [_finding(location="a.py:1", claim="would have been forked")],
                require_existing=True,
            )
        assert not target.exists(), "refused but still created the file"
        assert not target.parent.exists(), "refused but still made the directory"

    def test_refusal_names_the_resolved_path_and_cwd(self, tmp_path):
        """The message must answer the question the bug raises — 'where did
        this actually write?' — or it just moves the confusion."""
        target = tmp_path / "docs" / "findings.md"
        with pytest.raises(FileNotFoundError) as excinfo:
            append_findings_to_corpus(
                target, [_finding(location="a.py:1", claim="c")],
                require_existing=True,
            )
        message = str(excinfo.value)
        assert str(target.resolve()) in message
        assert os.getcwd() in message

    def test_existing_corpus_appends_normally_under_the_requirement(self, tmp_path):
        """The guard must not cost the happy path anything."""
        target = tmp_path / "findings.md"
        target.write_text("# Known findings\n\n## SURVIVED (0)\n", encoding="utf-8")
        n = append_findings_to_corpus(
            target, [_finding(location="a.py:1", claim="appended normally")],
            require_existing=True,
        )
        assert n == 1
        assert "appended normally" in target.read_text(encoding="utf-8")
