"""TP-SYN-08 §2 — public docs count claims match the live inventory.

Pre-TP-SYN-08, README.md said "3 helper modules" while the live count
was 4 — the kind of drift a regex scanner can catch but a human
review misses. These tests pin the contract that public docs (README,
CONVENTIONS, CHEAT-SHEET) reference the live counts from
``tests/_surface_expected.py`` and ``espalier.managed_inventory``.

Each numeric claim about commands / skills / agents / helpers is
either equal to the canonical count or absent. Drift fails loudly
with the doc name + the wrong number.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from espalier.managed_inventory import (
    get_hook_entry_files,
    get_hook_helper_files,
)
from tests._surface_expected import (
    EXPECTED_AGENT_COUNT_MIN,
    EXPECTED_COMMAND_COUNT,
    EXPECTED_SKILL_COUNT,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Marker assignment lives in tests/conftest.py::_MARKER_RULES.


PUBLIC_DOCS = (
    "README.md",
    "CONTRIBUTING.md",
    "docs/CHEAT-SHEET.md",
    "docs/CONVENTIONS.md",
)


def _doc_lines(rel: str) -> list[str]:
    path = REPO_ROOT / rel
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _scan_count_claims(rel: str, pattern: re.Pattern[str]) -> list[tuple[int, int, str]]:
    """Return (line_no, claimed_n, line_text) for each match."""
    matches = []
    for i, line in enumerate(_doc_lines(rel), start=1):
        for m in pattern.finditer(line):
            matches.append((i, int(m.group(1)), line.strip()))
    return matches


# Ignore lines that talk about rate limits / threads / etc. — number is not
# about the harness surface.
_SKIP_MARKERS = ("per minute", "per second", "concurrent")


def _filter_skip(matches: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    return [m for m in matches if not any(s in m[2].lower() for s in _SKIP_MARKERS)]


# ---------------------------------------------------------------------------
# Command / skill / agent / helper claim parity
# ---------------------------------------------------------------------------


COMMAND_RE = re.compile(
    r"\b(\d+)\s+(?:always-loaded\s+|slash\s+|harness\s+)?commands?\b",
    re.IGNORECASE,
)
SKILL_RE = re.compile(r"\b(\d+)\s+(?:on-demand\s+)?skills?\b", re.IGNORECASE)
AGENT_RE = re.compile(r"\b(\d+)\s+(?:rich\s+|harness\s+|canonical\s+)?agents?\b", re.IGNORECASE)
HELPER_RE = re.compile(
    r"\b(\d+)\s+(?:hook\s+)?helper(?:\s+modules?)?\b", re.IGNORECASE,
)


@pytest.mark.parametrize("doc", PUBLIC_DOCS)
def test_command_count_claims_match_inventory(doc):
    matches = _filter_skip(_scan_count_claims(doc, COMMAND_RE))
    bad = [
        (line_no, n, text) for (line_no, n, text) in matches
        if n != EXPECTED_COMMAND_COUNT
    ]
    assert not bad, (
        f"{doc} claims a command count that drifted from "
        f"EXPECTED_COMMAND_COUNT={EXPECTED_COMMAND_COUNT}:\n  "
        + "\n  ".join(f"line {ln}: '{txt}' (claims {n})" for ln, n, txt in bad)
    )


@pytest.mark.parametrize("doc", PUBLIC_DOCS)
def test_skill_count_claims_match_inventory(doc):
    matches = _filter_skip(_scan_count_claims(doc, SKILL_RE))
    bad = [
        (line_no, n, text) for (line_no, n, text) in matches
        if n != EXPECTED_SKILL_COUNT
    ]
    assert not bad, (
        f"{doc} claims a skill count that drifted from "
        f"EXPECTED_SKILL_COUNT={EXPECTED_SKILL_COUNT}:\n  "
        + "\n  ".join(f"line {ln}: '{txt}' (claims {n})" for ln, n, txt in bad)
    )


@pytest.mark.parametrize("doc", PUBLIC_DOCS)
def test_helper_count_claims_match_inventory(doc):
    actual = len(get_hook_helper_files())
    matches = _filter_skip(_scan_count_claims(doc, HELPER_RE))
    bad = [
        (line_no, n, text) for (line_no, n, text) in matches
        if n != actual
    ]
    assert not bad, (
        f"{doc} claims a hook-helper count that drifted from "
        f"managed_inventory.get_hook_helper_files() = {actual}:\n  "
        + "\n  ".join(f"line {ln}: '{txt}' (claims {n})" for ln, n, txt in bad)
    )


@pytest.mark.parametrize("doc", PUBLIC_DOCS)
def test_agent_count_claims_meet_floor(doc):
    """Agent count claims should be >= EXPECTED_AGENT_COUNT_MIN.

    The agent floor is 6 (universal canonical set); profile-aware extras
    can layer on top in user repos. Public docs that name an agent count
    are pinning the universal floor.
    """
    matches = _filter_skip(_scan_count_claims(doc, AGENT_RE))
    bad = [
        (line_no, n, text) for (line_no, n, text) in matches
        if n < EXPECTED_AGENT_COUNT_MIN
    ]
    assert not bad, (
        f"{doc} claims an agent count below the canonical floor "
        f"EXPECTED_AGENT_COUNT_MIN={EXPECTED_AGENT_COUNT_MIN}:\n  "
        + "\n  ".join(f"line {ln}: '{txt}' (claims {n})" for ln, n, txt in bad)
    )


# ---------------------------------------------------------------------------
# Hook entry count — README.md anchor
# ---------------------------------------------------------------------------


def test_readme_claims_correct_hook_entry_count():
    """README.md's 'N hook entry scripts' line must match the entry count."""
    actual = len(get_hook_entry_files())
    pattern = re.compile(r"\b(\d+)\s+hook\s+entry\s+scripts?\b", re.IGNORECASE)
    matches = _filter_skip(_scan_count_claims("README.md", pattern))
    if not matches:
        # No claim — nothing to verify
        return
    for line_no, n, text in matches:
        assert n == actual, (
            f"README.md line {line_no} claims {n} hook entry scripts "
            f"but get_hook_entry_files() = {actual}: '{text}'"
        )
