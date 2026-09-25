"""TP-114: pin the canonical severity scale across all review surfaces.

Option A consolidation. `BLOCK / WARN / NIT / PASS` replaces the prior
three-vocabulary state (BLOCKER/MAJOR/MINOR for code reviews;
BLOCK/WARN/NIT for the /preflight gates; WRONG/CONFLICTING/
VAGUE/CORRECT for the pack-artifact pre-execution checklist).

Two contracts per surface:

1. ``test_surface_uses_only_canonical_severity_tokens`` — every
   severity-callout token extracted from the surface is a member of
   ``CANONICAL_SEVERITY_SCALE``. Catches a foreign token leaking in
   (e.g., a CRITICAL severity added to code-reviewer without
   updating the SoT).

2. ``test_surface_has_no_legacy_severity_tokens`` — no pre-TP-114
   token (``LEGACY_SEVERITY_TOKENS``) appears. Catches migration
   debris (a leftover MAJOR or WRONG that slipped through the edit
   pass). Per-line opt-out via ``# contract: ok severity-scale
   <reason>`` for transitional mentions during multi-step migrations.

Per-surface regexes are tuned to avoid false-matching prose: case-
sensitive matching means lowercase "block the request" / "correct
the path" / "minor version" don't false-fire on the legacy
all-caps tokens.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._surface_expected import (
    CANONICAL_SEVERITY_SCALE,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# Per-surface extraction config:
#   relpath           — file under audit
#   token_pattern     — regex to extract canonical severity tokens
#                       (group 1 OR group 2; tuple alternation)
#   legacy_pattern    — regex to detect any legacy token (case-sensitive)
#   expected_subset   — tokens this surface is permitted to use
#                       (subset of CANONICAL_SEVERITY_SCALE)
SURFACES: dict[str, dict] = {
    "code-reviewer": {
        "relpath": ".claude/agents/code-reviewer.md",
        # Bold-wrapped (severity guide) or pipe-separated (Severity:
        # line) or = ... (description binding).
        "token_pattern": r"\*\*(BLOCK|WARN|NIT)\*\*|\b(BLOCK|WARN|NIT)\b\s*(?:\||$|=)",
        "legacy_pattern": r"\b(BLOCKER|MAJOR|MINOR)\b",
        "expected_subset": frozenset({"BLOCK", "WARN", "NIT"}),
    },
    "pack-artifact-checklist": {
        "relpath": "tools/cc/pack_artifact_checklist.md",
        # Trailing class includes `:` so `PASS:` in opening-line
        # context is also extracted (pre-fix the regex matched PASS
        # only via the closing line's trailing period — fragile).
        "token_pattern": r"\b(BLOCK|WARN|NIT|PASS)\b(?:\s|$|/|\,|\.|:)",
        "legacy_pattern": r"\b(WRONG|CONFLICTING|VAGUE|CORRECT|BLOCKER|MAJOR|MINOR)\b",
        "expected_subset": frozenset({"BLOCK", "WARN", "NIT", "PASS"}),
    },
}


def _flatten_groups(matches) -> set[str]:
    """``re.findall`` with alternation groups returns tuples; flatten
    to a set of non-empty tokens."""
    out: set[str] = set()
    for m in matches:
        if isinstance(m, tuple):
            out.update(t for t in m if t)
        elif m:
            out.add(m)
    return out


@pytest.mark.parametrize("surface", sorted(SURFACES.keys()))
def test_surface_uses_only_canonical_severity_tokens(surface: str):
    """Surface emits only tokens from CANONICAL_SEVERITY_SCALE; the
    per-surface ``expected_subset`` further constrains which of those
    are permitted in this specific surface.
    """
    cfg = SURFACES[surface]
    relpath = cfg["relpath"]
    text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    extracted = _flatten_groups(re.findall(cfg["token_pattern"], text))
    foreign = extracted - CANONICAL_SEVERITY_SCALE
    assert not foreign, (
        f"Surface {surface!r} ({relpath}) emits tokens outside the "
        f"canonical scale {sorted(CANONICAL_SEVERITY_SCALE)}: "
        f"{sorted(foreign)}. Either rename the token or add it to "
        f"CANONICAL_SEVERITY_SCALE in tests/_surface_expected.py."
    )
    extra = extracted - cfg["expected_subset"]
    assert not extra, (
        f"Surface {surface!r} ({relpath}) extracted tokens "
        f"{sorted(extra)} that exceed its declared subset "
        f"{sorted(cfg['expected_subset'])}. If intentional, update "
        f"the subset in tests/test_severity_scales.py::SURFACES."
    )


@pytest.mark.parametrize("surface", sorted(SURFACES.keys()))
def test_surface_has_no_legacy_severity_tokens(surface: str):
    """No pre-TP-114 token (BLOCKER/MAJOR/MINOR/WRONG/CONFLICTING/
    VAGUE/CORRECT) appears in the surface. Per-line opt-out via
    ``# contract: ok severity-scale <reason>`` for transitional
    mentions during multi-step migrations.
    """
    cfg = SURFACES[surface]
    relpath = cfg["relpath"]
    text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    # Strip opt-out lines before applying the legacy-token scan.
    kept_lines = [
        line for line in text.splitlines()
        if "contract: ok severity-scale" not in line
    ]
    kept = "\n".join(kept_lines)
    leftover = _flatten_groups(re.findall(cfg["legacy_pattern"], kept))
    assert not leftover, (
        f"Surface {surface!r} ({relpath}) still mentions legacy "
        f"severity tokens (TP-114 migration debris): {sorted(leftover)}. "
        f"Either complete the migration (replace with canonical "
        f"BLOCK/WARN/NIT/PASS) or annotate the line with "
        f"`# contract: ok severity-scale <reason>` if the mention "
        f"is genuinely transitional."
    )
