"""Shared hygiene predicates for adopter-facing shipped bodies (SoT).

Consumed by ``tests/test_init_tier_split.py`` (the full-suite
``TestCommonTierAssetHygiene`` contract) AND ``espalier surface-impact``
(the pre-flight content scan), so the pre-flight and the shipped-surface
contract cannot drift on what counts as an internal-ID or self-host-vocab
leak — one oracle, two callers.

Two data objects are the source of truth:

- :data:`SPECIFIC_ID_RE` — a digit-bearing ``TP`` / ``TASK_PACK`` / ``BC``
  pack identifier. Generic placeholders that carry no digit (``TP-NN``,
  ``BC-NNN``) are documentation vocabulary and are deliberately NOT
  matched — only IDs with an embedded digit trip the contract.
- :data:`FORBIDDEN_SELF_HOST_PATTERNS` — ``(label, pattern)`` pairs for
  prose that frames the harness as the adopter's own development target
  rather than a tool they installed.

The two ``*_hits`` helpers are the convenience surface the pre-flight
calls (whole-text scan, returns the offending strings/labels). The
full-suite contract keeps its own richer line-by-line + wrapped-text
scan for line-number reporting, but sources these same patterns.

Stdlib-only by contract: importable from both ``espalier/`` and the test
tree without pulling a third-party dependency into the pre-flight path.
"""
from __future__ import annotations

import re

# Specific IDs contain at least one digit (a real pack number). Generic
# placeholders without a digit (``TP-NN``, ``BC-NNN``) are explicitly
# allowed as documentation vocabulary and must not match.
SPECIFIC_ID_RE = re.compile(
    r"\b(?:TP|TASK_PACK|BC)-[A-Z0-9_-]*\d[A-Z0-9_-]*\b",
)

# Forbidden self-host vocabulary in common-tier asset bodies. The
# specific-ID sweep above catches digit-bearing pack-ID leaks; this
# catches the prose that survives because it carries no embedded digit:
#
#  - "Self-host meaning:" -- review-pass narrative that frames each
#    pattern through the harness's own development experience.
#  - "THIS harness" / "this harness's own" -- emphatic self-reference
#    that reads as "the harness you just installed" rather than "the
#    source repo we extracted examples from."
#  - an "R" + one-or-two digits adjacent to "round" / "review" --
#    references to internal review iterations adopters never saw.
FORBIDDEN_SELF_HOST_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("Self-host meaning:", re.compile(r"Self-host meaning:", re.IGNORECASE)),
    ("THIS harness", re.compile(r"\bTHIS\s+harness\b")),
    ("this harness's own", re.compile(r"this\s+harness'?s\s+own", re.IGNORECASE)),
    # Catch the plain lowercase "this harness" variant that the
    # uppercase-emphatic and possessive patterns above miss. Order
    # matters: this entry sits AFTER the more-specific "this harness's
    # own" so error messages report the more-specific label when both
    # match.
    ("this harness", re.compile(r"\bthis\s+harness\b", re.IGNORECASE)),
    (
        "R-NNN review-round ref",
        re.compile(r"\bR\d{1,2}\b(?=[^.]{0,80}\b(?:round|review)\b)", re.IGNORECASE),
    ),
)


def internal_id_hits(text: str) -> list[str]:
    """Return the specific (digit-bearing) internal pack IDs in ``text``.

    De-duplicated and sorted so a caller printing the hits gets a stable
    order. An empty list means clean.
    """
    return sorted(set(SPECIFIC_ID_RE.findall(text)))


def self_host_vocab_hits(text: str) -> list[str]:
    """Return the labels of forbidden self-host-vocab patterns in ``text``.

    Whole-text scan — the pre-flight's cheap check. The full-suite
    contract additionally reports line numbers and catches phrases that
    wrap across a line break; that richer scan stays in the test.
    """
    return [label for label, pat in FORBIDDEN_SELF_HOST_PATTERNS if pat.search(text)]
