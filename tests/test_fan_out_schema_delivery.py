"""TP-163: the fan-out parent-prompt schema-delivery contract.

The recall-engine design delivers the FINDING_SCHEMA to review/audit subagents
two ways: (1) PRIMARY — the parent Task prompt states the schema; (2) belt-and-
suspenders — ``subagent_start.py`` injects a pointer at spawn. The pinned
protocol grants SubagentStart ``additionalContext`` only "at conversation start"
with NO firing guarantee for nested fan-out agents, so the hook delivery is not
load-bearing.

What IS load-bearing: the contract is enforced on the RETURNED DATA, via
``espalier.fan_out_findings.iter_finding_errors`` / ``aggregate_findings`` —
independent of how (or whether) the schema reached the agent. This module pins
that. A batch reconstructed as if returned by N parent-prompt-briefed agents
aggregates with ``invalid == 0``; a finding from an agent that did NOT honor the
schema is caught on the data. Together that proves the parent prompt suffices and
no hook firing is required — the claim TP-163 corrects in
``memory/injection-opportunity-atlas.md`` (the struck "without each prompt
re-stating the contract" over-claim).

Sister to ``tests/test_fan_out_findings.py`` (which pins the schema mechanics on
single findings, in isolation); this module pins the *batch-delivery* contract.
"""
from __future__ import annotations

import pytest

from espalier.fan_out_findings import aggregate_findings, iter_finding_errors

# pytest-marker: default-unit

# The pack-review category vocabulary (domain-supplied — the schema carries NO
# enum for ``category``; aggregate_findings validates it via known_categories).
KNOWN_CATEGORIES = [
    "unbuildable-code", "false-green-gate", "stale-prereq",
    "sister-site", "doc-drift", "dead-prescription", "predicate-bug",
]


def _finding(fid: str, *, category: str = "doc-drift",
             outcome: str = "survived", confidence: str = "high") -> dict:
    """A complete, schema-conforming finding as a parent-prompt-briefed agent
    would return it: every required field present, ``verification`` the closed
    ``{positive, negative}`` object, and a DISTINCT ``location`` / ``named_unit``
    per id so aggregate_findings does not dedup the batch."""
    return {
        "id": fid,
        "title": f"delivery {fid}",
        "rule_or_scanner": "fan-out reviewer",
        "named_unit": f"espalier/harness_config.py::{fid}",
        "location": f"espalier/hooks_{fid}.py:10",
        "claim": "the schema reached this agent via the parent Task prompt",
        "violated_invariant": "schema-delivery must not depend on a hook firing",
        "category": category,
        "minimal_repro": "reconstruct a batch; run aggregate_findings",
        "verification": {
            "positive": "conforming batch aggregates invalid==0",
            "negative": "a non-conforming finding is flagged on the data",
        },
        "confidence": confidence,
        "proposed_fix": "none (positive sample)",
        "severity": "minor",
        "blocks_release": False,
        "refutation_outcome": outcome,
    }


def _reconstructed_batch() -> list[dict]:
    """A batch as if returned by several parent-prompt-briefed fan-out agents,
    spanning categories and outcomes (3 survived, 1 refuted, 1 unattempted)."""
    return [
        _finding("a1", category="doc-drift", outcome="survived"),
        _finding("a2", category="stale-prereq", outcome="survived"),
        _finding("b1", category="dead-prescription", outcome="refuted"),
        _finding("c1", category="predicate-bug", outcome="survived", confidence="med"),
        _finding("d1", category="false-green-gate", outcome="unattempted", confidence="low"),
    ]


class TestParentPromptDelivery:
    def test_conforming_batch_aggregates_clean(self):
        """A batch from parent-prompt-briefed agents has zero invalid findings —
        the schema contract is satisfied on the DATA, no hook required."""
        batch = _reconstructed_batch()
        summary = aggregate_findings(batch, known_categories=KNOWN_CATEGORIES)
        assert summary.total == len(batch)
        assert summary.invalid == 0
        assert summary.valid == len(batch)
        assert summary.unique == len(batch)  # distinct locations -> no dedup
        assert summary.unknown_categories == []

    def test_every_finding_carries_required_fields(self):
        """iter_finding_errors is empty for each reconstructed finding —
        required-field presence on the returned data IS the delivery payload."""
        for f in _reconstructed_batch():
            assert iter_finding_errors(f) == [], (f["id"], iter_finding_errors(f))

    def test_survival_rate_is_data_derived(self):
        """survival_rate = survived / (survived + refuted), over contested
        findings only — derived from the returned data, not from a hook."""
        summary = aggregate_findings(
            _reconstructed_batch(), known_categories=KNOWN_CATEGORIES
        )
        # 3 survived, 1 refuted, 1 unattempted (not contested) -> 3/4.
        assert summary.survival_rate == pytest.approx(3 / 4)


class TestDeliveryChannelIndependence:
    """The contract is enforced on the data regardless of how (or whether) the
    schema was delivered — so an agent that did NOT honor it is caught, and a
    hook firing is neither necessary nor sufficient. The negatives below also
    prove the positive assertions above are not vacuous."""

    def test_agent_that_dropped_a_required_field_is_caught(self):
        bad = _finding("bad1")
        del bad["proposed_fix"]  # an agent that ignored the schema
        errors = iter_finding_errors(bad)
        assert any("proposed_fix" in e for e in errors), errors
        summary = aggregate_findings(
            _reconstructed_batch() + [bad], known_categories=KNOWN_CATEGORIES
        )
        assert summary.invalid == 1

    def test_non_object_verification_is_caught(self):
        """An agent that returned a string ``verification`` (the very workflow-
        schema mismatch the TP-163 fan-out itself hit) is flagged on the data,
        not silently accepted."""
        bad = _finding("bad2")
        bad["verification"] = "I checked it"  # not the closed {positive,negative} object
        assert iter_finding_errors(bad) != []

    def test_unknown_category_surfaces_without_failing_schema(self):
        """A category outside the domain vocab is SURFACED (not silently
        accepted), yet is not a schema error — ``category`` carries no enum, so
        the vocabulary is the parent's to define, not the schema's."""
        f = _finding("x1", category="totally-made-up")
        assert iter_finding_errors(f) == []  # schema-valid: category is free-form
        summary = aggregate_findings([f], known_categories=KNOWN_CATEGORIES)
        assert "totally-made-up" in summary.unknown_categories
        assert summary.invalid == 0
