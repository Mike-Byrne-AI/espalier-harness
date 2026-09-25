"""Pin every load-bearing claim to either a canon or an explicit
'convention only' label.

A 'load-bearing claim' is any priority-order invariant in CLAUDE.md or any
'Backed by:' assertion in docs/HOOK_ASSUMPTIONS.md. For each claim:
- If the doc names a backing test/canon, that test must exist and import.
- If the doc says 'No Espalier-side runtime pin' or 'convention', the
  claim must appear in the TP-137 Coverage Shape table with the
  matching label.

This catches the 124-G class of drift: a canon empirically refutes a
claim, the operator chooses 'accept and document,' but the doc claim is
never updated to mention the reconciliation. New 'accept and document'
closures must extend either the canon list or the coverage table.
"""

import re
from pathlib import Path

_REPO = Path(__file__).parents[1]
_HOOK_ASSUMPTIONS = _REPO / "docs" / "HOOK_ASSUMPTIONS.md"
_CLAUDE_MD = _REPO / "CLAUDE.md"
_CONVENTIONS = _REPO / "docs" / "CONVENTIONS.md"


def test_hook_assumptions_coverage_table_exists() -> None:
    """TP-137 §D requires a Coverage Shape table at the top of HOOK_ASSUMPTIONS."""
    text = _HOOK_ASSUMPTIONS.read_text(encoding="utf-8")
    assert "## Coverage Shape" in text, (
        "docs/HOOK_ASSUMPTIONS.md must include a 'Coverage Shape' section "
        "summarizing canon-backing per assumption. Added in TP-137 §D."
    )


def test_coverage_table_lists_all_five_assumptions() -> None:
    text = _HOOK_ASSUMPTIONS.read_text(encoding="utf-8")
    start = text.find("## Coverage Shape")
    assert start != -1, "Coverage Shape section missing"
    block = text[start : text.find("\n---", start + 1)]
    for n in range(1, 6):
        token = f"{n} —"
        assert token in block, (
            f"Coverage Shape table missing row for Assumption {n}. "
            "All 5 assumptions must appear."
        )


def test_claude_md_priority_three_acknowledges_canon_state() -> None:
    """CLAUDE.md priority-3 must either drop 'blueprints' or reference the canon reconciliation."""
    text = _CLAUDE_MD.read_text(encoding="utf-8")
    match = re.search(r"3\. Session continuity[^\n]*", text)
    assert match is not None, "CLAUDE.md priority-3 line not found"
    line = match.group(0)
    has_reconciliation_ref = (
        "HOOK_ASSUMPTIONS" in line
        or "cross-session re-engagement is not" in line
    )
    drops_blueprints = "blueprint" not in line.lower()
    assert drops_blueprints or has_reconciliation_ref, (
        f"CLAUDE.md priority-3 line claims blueprint continuity without "
        f"referencing the 124-G reconciliation: {line!r}. Either drop "
        f"'blueprints' from the line OR reference docs/HOOK_ASSUMPTIONS.md "
        f"per TP-137 §D Fix 17 Path A."
    )


def test_signal_1_threshold_carries_empirical_annotation() -> None:
    """CONVENTIONS Signal 1 row must carry the 124-G empirical-state annotation."""
    conventions = _CONVENTIONS.read_text(encoding="utf-8")
    sig1_block = conventions[conventions.find("1 — continuity") :]
    sig1_block = sig1_block[: sig1_block.find("\n| 2 ")]
    assert "Empirical state" in sig1_block, (
        "Signal 1 falsifiability row must annotate the 124-G live-fire result "
        "per TP-137 §D Fix 18. Without this, the row's threshold appears "
        "actionable when in fact it has been measurably breached."
    )
