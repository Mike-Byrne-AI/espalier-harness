"""Completeness pin for Core Rule #4's claim↔canon binding.

Guards against silently re-conflating the three-strength memory claim that was
split apart: Core Rule #4 states one thing that is mechanically bounded
(`TestMemoryMdLineLimit`), one that is mechanically injected every session
(`test_self_host_repo_includes_memory_digest`), and one that is convention only
(update at each `/handoff` — no `stop_gate.py` check verifies the file was
saved). The generic canon contract (`test_canon_verifier_contract.py`) proves
each *present* canon resolves, but it cannot catch a cited canon being *dropped*
(the other canon still covers the claim line, so it is not a naked claim) nor the
handoff clause being re-presented as enforced. This file pins both, because those
are exactly the two ways a future edit re-understates or re-inflates the rule's
backing.

Two earn-the-reds live here: any enforced canon (the line-cap OR the
SessionStart-digest) failing to resolve PINNED for Rule #4 REDs
`test_both_enforced_canons_resolve_pinned`; removing the convention marker from
the handoff clause REDs `test_handoff_clause_marked_convention`.

Why assert BOTH canons, not just the digest: Rule #4 is the only multi-canon
claim in the corpus. The generic contract proves each PRESENT canon resolves
but cannot catch a canon being DROPPED — the surviving canon still covers the
claim line, so it is not a naked claim. Asserting both PINNED is the only thing
that reds when a future edit silently deletes one. (The claim's annotation order
is no longer load-bearing: `_find_adjacent_claim_id` binds each canon within its
own annotation block, so canon-first and claim-id-first both resolve — the
earlier claim-id-FIRST workaround for the parser's ±window asymmetry is retired.)
"""

from pathlib import Path

from espalier.scanners import canon_verifier as cv

_REPO = Path(__file__).resolve().parents[1]
_CLAUDE_MD = _REPO / "CLAUDE.md"
_CLAIM_ID = "claude-core-rule-4-memory-state"
# The two mechanically-enforced clauses of Rule #4, each cited as its own canon.
# Both fail LOUD here on a rename (the canon line + def + this constant are the
# three coupled sites) — self-correcting, not a silent miss.
_CAP_CANON_TEST = "TestMemoryMdLineLimit"
_DIGEST_CANON_TEST = "test_self_host_repo_includes_memory_digest"


def _rule_4_pinned_canons() -> list[str]:
    """Canon strings that resolve PINNED for Core Rule #4's claim-id."""
    return [
        f.claim.canon
        for f in cv.verify_repo(_REPO)
        if f.claim.claim_id == _CLAIM_ID and f.severity == "PINNED"
    ]


def _rule_4_prose_line() -> str:
    """Return the Core Rule #4 prose line, located by claim-id (never by line
    number — the spine reorder moves the block). The prose is the nearest
    non-empty, non-annotation line above the `claim-id` annotation."""
    lines = _CLAUDE_MD.read_text(encoding="utf-8").splitlines()
    claim_idx = next(
        (
            i
            for i, ln in enumerate(lines)
            if (m := cv.CLAIM_ID_ANNOTATION_RE.search(ln)) and m.group(1) == _CLAIM_ID
        ),
        None,
    )
    assert claim_idx is not None, (
        f"claim-id {_CLAIM_ID!r} not found in CLAUDE.md — Core Rule #4's "
        f"annotation is missing or was renamed."
    )
    for j in range(claim_idx - 1, -1, -1):
        stripped = lines[j].strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        return stripped
    raise AssertionError(
        f"no prose line found above claim-id {_CLAIM_ID!r} in CLAUDE.md"
    )


class TestCoreRule4CanonCompleteness:
    def test_both_enforced_canons_resolve_pinned(self) -> None:
        """Both enforced halves — the line-cap AND the SessionStart-digest — must
        resolve PINNED for Core Rule #4, proving neither backing was dropped. RED
        if either is missing: a dropped canon still leaves the claim line covered
        by the surviving canon, so only a both-canons assertion catches it."""
        pinned = _rule_4_pinned_canons()
        for needle, clause in (
            (_CAP_CANON_TEST, "cross-session state / bounded"),
            (_DIGEST_CANON_TEST, "loaded every session"),
        ):
            assert any(needle in c for c in pinned), (
                f"Core Rule #4's {clause!r} clause has no PINNED canon citing "
                f"{needle!r}. Both enforced halves must resolve PINNED — asserting "
                f"BOTH (not just the digest) is what catches a DROPPED canon: the "
                f"surviving canon still covers the claim line, so the generic "
                f"contract can't see the deletion. "
                f"Rule-4 PINNED canons: {pinned}"
            )

    def test_handoff_clause_marked_convention(self) -> None:
        """The handoff-update half has no mechanical backing (stop_gate only
        mentions /handoff in a comment); the prose must mark it convention so it
        doesn't read as enforced. RED if the convention marker is removed."""
        prose = _rule_4_prose_line()
        assert "/handoff" in prose, (
            f"Core Rule #4 prose no longer mentions /handoff: {prose!r}"
        )
        assert "convention" in prose.lower(), (
            f"Core Rule #4's handoff-update clause must be marked convention — no "
            f"mechanical check verifies the file was updated at handoff; coverage "
            f"'falls back to /handoff'. Prose: {prose!r}"
        )
