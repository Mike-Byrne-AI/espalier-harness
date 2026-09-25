"""TP-287 — scope-breaker + convergence-critic stage-presence contract.

Decision A: a committed ``.claude/workflows/*.js`` review scaffold that CLAIMS to be
scope-breaker-complete (it carries the ``SCOPE-BREAKER`` sentinel) MUST wire all four
scope-breakers *and* the terminal convergence-critic — so a copy of the canonical
template cannot silently drop a stage, and a hand-authored round that opts in is held
to the same floor.

Honest ceiling (memory/convergence-review-protocol.md "Enforcement ceiling"): a review
authored INLINE via the Workflow tool is not a committed file, so no contract can inspect
it — inline ad-hoc reviews stay *discipline*-enforced. This is the mechanical layer over
committed scaffolds, NOT a claim of inline enforcement.

Reads ``.claude/workflows/`` content, which a shipping export prunes
(``.gitattributes`` ``export-ignore`` / ``surface_contract._LOCAL_ONLY_PREFIXES``) — so
the two tests that read them are registered ``full_tree`` in
``tests/conftest.py::_FULL_TREE_NODEIDS`` and run on the dev tree / a fresh clone,
not against an extracted archive; the fixture-driven third runs everywhere
(measured on a seeded export, 2026-09-23).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".claude" / "workflows"
CANONICAL_TEMPLATE = "_convergence_review_template.js"
SENTINEL = "SCOPE-BREAKER"

def _code_lines(src: str) -> str:
    """Drop whole-line ``//`` JS comments so a marker check can't be satisfied
    by a commented-out stage. Inline ``//`` (e.g. an ``https://`` literal) is
    left intact — only lines whose first non-space characters are ``//`` are
    removed."""
    return "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("//")
    )


# BEHAVIORAL markers are load-bearing wiring — a phase() call, the per-run ledger
# read, the cross-round ledger-append constant. They MUST appear in a NON-COMMENT
# line: a scaffold that carries them only as a `//` comment has dropped the stage
# while still passing a bare-substring check (a false-green).
BEHAVIORAL_MARKERS = {
    "penumbra phase": "phase('Penumbra')",
    "actionable-critic phase": "phase('Actionable-critic')",
    "delta-attacker phase": "phase('Delta-attacker')",
    "convergence-critic phase": "phase('Convergence-critic')",
    "critic reads the per-run ledger": "read_ledger",
    "critic appends to the convergence ledger": "LEDGER_PATH",
}
# LABEL markers are section-label sentinels that live legitimately in comments, so
# a bare-substring match anywhere in the source is the correct, intended check.
LABEL_MARKERS = {
    "penumbra — scope-breaker 1": "SCOPE-BREAKER 1",
    "actionable-critic — scope-breaker 2": "SCOPE-BREAKER 2",
    "corpus-blind — scope-breaker 3": "SCOPE-BREAKER 3",
    "delta-attacker — scope-breaker 4": "SCOPE-BREAKER 4",
    "convergence-critic — terminal": "CONVERGENCE-CRITIC",
}


class TestConvergenceWorkflowStages:
    """Decision A — the mechanical layer of the scope-breaker enforcement ceiling."""

    @staticmethod
    def _scope_breaker_scaffolds() -> dict[str, str]:
        """Every committed workflow that self-identifies as scope-breaker-complete
        (carries the ``SCOPE-BREAKER`` sentinel), name → source. A one-shot review
        without the sentinel is deliberately EXEMPT — it never claimed completeness."""
        out: dict[str, str] = {}
        if not WORKFLOWS.is_dir():
            return out
        for path in sorted(WORKFLOWS.glob("*.js")):
            text = path.read_text(encoding="utf-8")
            if SENTINEL in text:
                out[path.name] = text
        return out

    def test_canonical_template_is_a_scope_breaker_scaffold(self):
        """Floor: the canonical template exists and self-identifies. Without this the
        stage-presence assertion below is vacuously true on an empty set."""
        scaffolds = self._scope_breaker_scaffolds()
        assert CANONICAL_TEMPLATE in scaffolds, (
            f"{CANONICAL_TEMPLATE} must exist under .claude/workflows/ and carry the "
            f"{SENTINEL!r} sentinel (the canonical scope-breaker-complete scaffold). "
            "Did it move, get renamed, or lose its scope-breaker markers?"
        )

    def test_every_scope_breaker_scaffold_carries_all_stages(self):
        """Any scaffold that claims scope-breaker completeness must wire ALL four
        scope-breakers + the terminal convergence-critic. A copy that drops one is the
        exact silent-narrowing failure TP-287 mechanizes against."""
        scaffolds = self._scope_breaker_scaffolds()
        assert scaffolds, (
            "no scope-breaker scaffold found — floor failed (template moved or "
            "lost its sentinel?)"
        )
        for name, text in scaffolds.items():
            code = _code_lines(text)
            # Behavioral wiring must be live (non-comment); labels may be comments.
            missing = [
                label
                for label, marker in BEHAVIORAL_MARKERS.items()
                if marker not in code
            ]
            missing += [
                label
                for label, marker in LABEL_MARKERS.items()
                if marker not in text
            ]
            assert not missing, (
                f"{name} carries the {SENTINEL!r} sentinel (claims scope-breaker "
                f"completeness) but is MISSING stage(s): {missing}. A scope-breaker "
                "scaffold MUST wire all four scope-breakers + the terminal "
                "convergence-critic — see memory/convergence-review-protocol.md "
                '"Scope-breakers (mandatory floor)".'
            )

    def test_behavioral_marker_commented_out_is_caught(self):
        """A scaffold that carries a behavioral stage only as a ``//`` comment
        must FAIL the behavioral (non-comment) check — the bare-substring check
        this partition replaces would have passed it (the false-green)."""
        fake = "\n".join(
            [
                "// phase('Penumbra')",  # commented — must NOT satisfy behavioral
                "phase('Actionable-critic')",
                "phase('Delta-attacker')",
                "phase('Convergence-critic')",
                "read_ledger",
                "const LEDGER_PATH = '...'",
                "// SCOPE-BREAKER 1",
                "// SCOPE-BREAKER 2",
                "// SCOPE-BREAKER 3",
                "// SCOPE-BREAKER 4",
                "// CONVERGENCE-CRITIC",
            ]
        )
        code = _code_lines(fake)
        behavioral_missing = [
            label
            for label, marker in BEHAVIORAL_MARKERS.items()
            if marker not in code
        ]
        assert "penumbra phase" in behavioral_missing, (
            "the commented-out phase('Penumbra') should be caught by the "
            "behavioral (non-comment) check"
        )
        # Regression guard: the old bare-substring check would have passed it.
        assert "phase('Penumbra')" in fake
        # Labels (in comments) still satisfy their substring check, as intended.
        label_missing = [
            label for label, marker in LABEL_MARKERS.items() if marker not in fake
        ]
        assert not label_missing, label_missing
