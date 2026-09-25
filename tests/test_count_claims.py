"""Mechanical agent/command count-claim verification — TP-RELEASE-05 §B.

Public docs make claims like "6 governance agents" and "12 slash commands".
Without an automated check these claims drift silently when the surface
changes. This test reads the live count from `.claude/agents/` and
`.claude/commands/` and fails if any public doc carries a number that
disagrees.

The regex tolerates an optional one-word adjective between the count and
the noun ("6 governance agents", "12 slash commands") because that's the
phrasing Espalier-Harness docs actually use. Bare claims ("6 agents", "12
commands") are also caught.

Stem `test_count_claims` is registered in `tests/conftest.py::_MARKER_RULES`
under the `contract` group so this test runs with `-m contract`.
"""
from __future__ import annotations

import re
from pathlib import Path

from espalier.surface_contract import (
    classify_release_path,
    discover_public_docs,
    get_public_doc_relpaths,
    make_count_claim_regex,
    parse_count_token,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# TP-RELEASE-13: route through the canonical helper. The hand-curated
# three-doc list missed docs/QUICKSTART.md, which let the "three helper
# modules" drift survive through 0.5.0.
PUBLIC_DOCS: tuple[Path, ...] = tuple(discover_public_docs(REPO_ROOT))


def test_every_shippable_public_doc_resolves():
    """`discover_public_docs` SILENTLY SKIPS missing files by design, and every
    scan below is a per-noun `matched > 0` vacuity guard the other docs satisfy
    on their own — so the audited population can shrink with nothing noticing.

    DERIVED, not a pinned floor. A `len(PUBLIC_DOCS) >= 12` floor was the first
    draft and it was wrong twice over: it had zero margin against the real export
    (dev tree resolves 13, an export resolves 12), and as a MODULE-LEVEL assert it
    raised at COLLECTION — turning one legitimately-absent doc into
    `Interrupted: 1 error during collection`, zero tests run, in exactly the lane
    it was written to protect (`scripts/final_release_matrix.py` runs
    `pytest -m "not full_tree"` inside the extracted archive, where a
    collection error cannot be marker-skipped).

    Asking "does every doc that SHOULD be here resolve?" is exact in both lanes:
    `internal` members are pruned from an export legitimately, so they are not
    expected there — and a `docs/` file vanishing for any other reason still reds.
    """
    expected = [
        rel for rel in get_public_doc_relpaths()
        if classify_release_path(rel) != "internal"
    ]
    assert expected, "test setup: no shippable public docs declared"
    resolved = {p.name for p in PUBLIC_DOCS}
    missing = [rel for rel in expected if Path(rel).name not in resolved]
    assert not missing, (
        f"declared public docs that did not resolve: {missing}. "
        "discover_public_docs() skips missing files silently, so the count audit "
        "below would pass while scanning a shrunken population. Either the file "
        "moved, or it became `internal` and should be classified as such rather "
        "than quietly absent."
    )

# TP-RELEASE-13: regexes built from the shared helper, accepting
# spelled-out small numbers in addition to digits.
_AGENT_CLAIM_RE = make_count_claim_regex(r"agents?")
_COMMAND_CLAIM_RE = make_count_claim_regex(r"commands?")
_HELPER_CLAIM_RE = make_count_claim_regex(r"(?:hook\s+)?helpers?(?:\s+modules?)?")

# Phrases where a count appears coincidentally near the noun but isn't
# a roster claim. Lines containing any of these substrings are skipped.
_FALSE_POSITIVE_LINE_MARKERS: tuple[str, ...] = (
    "per minute",
    "per second",
    "concurrent",
)


def _live_agent_count() -> int:
    return len(list((REPO_ROOT / ".claude" / "agents").glob("*.md")))


def _live_command_count() -> int:
    return len(list((REPO_ROOT / ".claude" / "commands").glob("*.md")))


def _claims_in(text: str, pattern: re.Pattern[str]) -> list[tuple[int, str]]:
    """Return (count_value, line) tuples for every count claim in text.

    TP-RELEASE-13: accepts spelled-out numbers via parse_count_token.
    Lines where the token does not parse (rare) are silently skipped.
    """
    out: list[tuple[int, str]] = []
    for line in text.splitlines():
        if any(marker in line.lower() for marker in _FALSE_POSITIVE_LINE_MARKERS):
            continue
        for m in pattern.finditer(line):
            n = parse_count_token(m.group(1))
            if n is None:
                continue
            out.append((n, line.strip()))
    return out


def test_agent_count_claims_match_filesystem():
    actual = _live_agent_count()
    assert actual > 0, "no agent files found under .claude/agents/"
    matched = 0
    for doc in PUBLIC_DOCS:
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8")
        for n, line in _claims_in(text, _AGENT_CLAIM_RE):
            matched += 1
            assert n == actual, (
                f"{doc.name} claims {n} agent(s); filesystem has {actual}. "
                f"Line: {line!r}. Update the doc or regenerate the surface."
            )
    # TP-174a: the assertion lives only inside the match loop, so a regex that
    # matches nothing makes ZERO comparisons and the test passes vacuously —
    # re-opening the 0.5.0 drift class. Require at least one parsed claim.
    assert matched > 0, (
        "agent-count regex matched no public-doc claim — regex drift or docs "
        "reworded; the test would have passed vacuously"
    )


def test_command_count_claims_match_filesystem():
    actual = _live_command_count()
    assert actual > 0, "no command files found under .claude/commands/"
    matched = 0
    for doc in PUBLIC_DOCS:
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8")
        for n, line in _claims_in(text, _COMMAND_CLAIM_RE):
            matched += 1
            assert n == actual, (
                f"{doc.name} claims {n} command(s); filesystem has {actual}. "
                f"Line: {line!r}. Update the doc or regenerate the surface."
            )
    assert matched > 0, (
        "command-count regex matched no public-doc claim — regex drift or docs "
        "reworded; the test would have passed vacuously"
    )


def test_helper_count_claims_match_filesystem():
    """TP-RELEASE-13: spelled-out helper counts in QUICKSTART must match.

    The 0.5.0 release shipped 'three helper modules' in QUICKSTART while
    the filesystem had 4. This test would have caught it had it existed.
    """
    actual = _live_helper_count()
    # TP-174a: this test, unlike its siblings, was missing the >0 guard.
    assert actual > 0, "no hook helper modules found under tools/cc/hooks/"
    matched = 0
    for doc in PUBLIC_DOCS:
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8")
        for n, line in _claims_in(text, _HELPER_CLAIM_RE):
            matched += 1
            assert n == actual, (
                f"{doc.relative_to(REPO_ROOT).as_posix()}: "
                f"claims {n} helpers; filesystem has {actual}\n"
                f"  line: {line.strip()}"
            )
    assert matched > 0, (
        "helper-count regex matched no public-doc claim — regex drift or docs "
        "reworded; the test would have passed vacuously"
    )


def _live_helper_count() -> int:
    """Count hook helper modules (tools/cc/hooks/_*.py, excluding __init__)."""
    hooks_dir = REPO_ROOT / "tools" / "cc" / "hooks"
    if not hooks_dir.is_dir():
        return 0
    return len([
        p for p in hooks_dir.glob("_*.py")
        if p.name != "__init__.py"
    ])
