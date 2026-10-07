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

Reads ``.claude/workflows/`` content. The scaffolds ship on every surface (the fourth
deployed .claude kind, no export-ignore row), so an export carries them and this module
is no longer registered ``full_tree``: the dev-only-chain audit measures it at zero.
"""

import re
from pathlib import Path

from espalier._safe_walk import visible
from tests._interpreter_hosts import shell_resolver_line

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
        for path in visible(WORKFLOWS.glob("*.js"), WORKFLOWS):
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


class TestWorkflowBodiesResolveTheInterpreterOnTheHost:
    """A deployed workflow body is a prompt an agent follows on the adopter's
    host, and its persist command is marked "run EXACTLY as written". Neither
    bare spelling is portable: ``python3`` is absent on many Windows installs,
    ``python`` on a stock Mac (the maintainer's own, DEF-383a). So the command
    opens with the identity-probe resolver line the command bodies share
    (`tests/_interpreter_hosts.py::shell_resolver_line`, then `$PY -c '`), and
    no body hands an agent a bare versioned invocation. The line it replaced
    asked `command -v`, which a Store alias satisfies: on a Windows host whose
    `python3` is the App Execution Alias it ran the stub (2026-10-01).
    Measured 2026-09-28: eleven ``python3`` lines across the three scaffolds,
    beside a probe runner with the same defect one layer down
    (``tests/test_check_ledger_probes.py::TestAProbeRunsUnderTheInterpreterRunningTheChecker``);
    the first cut of this guard swept them to ``python`` and would have
    stranded the Mac instead (the failure-mode pass caught it).
    """

    _RESOLVER = shell_resolver_line(espalier=True)
    _BARE_INVOCATION = re.compile(r"\bpython3\s+-[cm]\b")
    _PERSIST_HEAD = re.compile(r"const persistCmd =\n  `([^\n]*)\\n` \+\n  `([^\n]*)\\n` \+\n")

    def test_no_workflow_body_hands_an_agent_a_bare_versioned_invocation(self):
        hits = [
            f"{path.name}:{n}: {line.strip()[:80]}"
            for path in visible(WORKFLOWS.glob("*.js"), WORKFLOWS)
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if self._BARE_INVOCATION.search(line) and self._RESOLVER not in line
        ]
        assert not hits, (
            "workflow bodies invoking a bare `python3` (open with the resolver idiom "
            "or spell `python` in prose):\n  " + "\n  ".join(hits)
        )

    def test_every_persist_command_opens_with_the_resolver_idiom(self):
        bodies = visible(WORKFLOWS.glob("*.js"), WORKFLOWS)
        assert len(bodies) >= 3, bodies
        for path in bodies:
            text = path.read_text(encoding="utf-8")
            if "const persistCmd =" not in text:
                continue
            m = self._PERSIST_HEAD.search(text)
            assert m, (path.name, "persistCmd head not in the two-line shape")
            assert m.group(1) == self._RESOLVER, (path.name, m.group(1))
            assert m.group(2) == "$PY -c '", (path.name, m.group(2))

    def test_the_invocation_guard_reads_the_shape_it_claims_to(self):
        """The guard's own regression guard: an invocation in a template literal
        or a ``//`` comment is caught; the idiom line, a prose mention and the
        bare ``python`` are not."""
        rx = self._BARE_INVOCATION
        assert rx.search("  `  python3 -c 'import json'\\n` +")
        assert rx.search("// can't break the  python3 -m espalier quoting")
        assert not rx.search("  `" + self._RESOLVER + "\\n` +")
        assert not rx.search("  `  python -c 'import json'\\n` +")
        assert not rx.search("(python3 only, per the host line)")
