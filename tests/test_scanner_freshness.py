"""Pin the freshness scanner's behavioral contract.

Earn-the-gate: every documented policy in `_ALLOWED_POLICIES` surfaces
when parse_fragment_markers walks the fixture markdown.

The freshness scanner is the structural outlier among the 6 TP-143
target scanners: it walks `FRAGMENT_SURFACE_ALLOWLIST` markdown files
only (README.md, CHANGELOG.md, ESPALIER_MEMORY.md, CLAUDE.md, `docs/**/*.md`,
`.claude/**/*.md`). `tests/fixtures/*.md` is NOT in the allowlist, so
no `EXEMPT_PREFIXES` addition is needed -- the fixture is naturally
invisible to `discover_fragments` and therefore to `scan_repo`.

TP-105 / TP-143 / FM-7 §1.7 close.
"""
from __future__ import annotations

import ast
from pathlib import Path

from espalier.scanners import freshness as scn


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_freshness_positives.md"
NEG_FIXTURE_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "test_freshness_negatives.md"
)


def test_earn_the_gate_detects_every_fixture_shape() -> None:
    """Parse the fixture markdown directly. Assert each policy in
    _ALLOWED_POLICIES surfaces at least once."""
    content = FIXTURE_PATH.read_text(encoding="utf-8")
    fragments = scn.parse_fragment_markers(content, source_path=str(FIXTURE_PATH))
    policies_seen = {f.policy for f in fragments}
    missing = scn._ALLOWED_POLICIES - policies_seen
    assert not missing, (
        f"earn-the-gate: scanner failed to detect policies {missing}. "
        f"Found: {policies_seen}."
    )


def test_does_not_trip_on_negatives() -> None:
    """Must-NOT-trip: parse_fragment_markers the negatives corpus
    directly. Every construct is a clean-but-tempting near-miss of a
    real fragment marker (fenced code blocks, YAML frontmatter, a
    foreign namespace, plain HTML comments, prose mentions). The parser
    must extract ZERO Fragments. Direct-call mirrors the earn-the-gate
    test and is immune to live-tree drift; parse_fragment_markers does
    no date arithmetic, so this corpus is permanently date-stable (no
    time-bomb). TP-156 Tier 1."""
    content = NEG_FIXTURE_PATH.read_text(encoding="utf-8")
    fragments = scn.parse_fragment_markers(
        content, source_path=str(NEG_FIXTURE_PATH)
    )
    assert fragments == [], (
        f"negatives corpus tripped the scanner: extracted "
        f"{[f.id for f in fragments]}. A construct thought clean is "
        f"being parsed as a fragment. TP-156 Tier 1."
    )


def test_fixture_not_in_live_scan() -> None:
    """FRAGMENT_SURFACE_ALLOWLIST excludes tests/fixtures/ implicitly
    (no glob covers it). Confirm scan_repo does not surface any
    FragmentState for the fixture path."""
    states = scn.scan_repo(REPO_ROOT)
    fixture_rel = "tests/fixtures/test_freshness_positives.md"
    fixture_states = [
        s for s in states
        if fixture_rel in s.fragment.source_path.replace("\\", "/")
    ]
    assert fixture_states == [], (
        f"discover_fragments unexpectedly walked the fixture; found "
        f"{len(fixture_states)} state(s). The allowlist may have grown "
        f"to include tests/fixtures/."
    )


def test_git_log_name_only_has_no_dead_commits_counter() -> None:
    """TP-174b R38: the write-only ``commits`` counter in
    ``_git_log_name_only`` was removed (assigned at 3 sites, never read; ruff
    F841 doesn't flag an AugAssign). Assert no ``commits`` Name or AugAssign
    survives in that function so the dead store cannot silently reappear."""
    src = (REPO_ROOT / "espalier" / "scanners" / "freshness.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "_git_log_name_only"
    )
    commits_names = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Name) and n.id == "commits"
    ]
    assert not commits_names, (
        f"dead 'commits' counter reappeared in _git_log_name_only "
        f"({len(commits_names)} reference(s))"
    )
