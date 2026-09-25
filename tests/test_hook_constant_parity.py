#!/usr/bin/env python3
"""TP-149 (149-B) — hook constant-SoT parity + cross-hook predicate parity.

Two classes of silent desync are pinned here:

1. **Bare-literal SoT duplication across standalone hook scripts.** The
   ``tools/cc/`` isolation rule forbids cross-module imports (each hook
   runs as a standalone subprocess), so a constant shared between two
   hooks is duplicated as a literal in each. This contract keeps the
   duplicates in sync WITHOUT importing across modules — it AST-reads
   each source file and asserts the consumer's literal still equals the
   producer's named constant:

     - ``reflect_trigger.WARN_FLAG_FILE`` (``"reflect_trigger_warned"``)
       must appear in ``session_start.py``'s per-session flag-clear list,
       else the one-shot reflect WARN never re-fires after session one.
     - ``stop_gate.STOP_GATE_MODE_ENV`` (``"ESPALIER_STOP_GATE"``) must be
       the literal both ``session_start.py`` (dormant-skip warning) and
       ``statusline.py`` (STOP indicator) read, else a rename strands one.

2. **Predicate parity between the two ``_has_active_plan`` functions.**
   ``plan_guard._has_active_plan`` gates writes; ``task_router._has_active_plan``
   suppresses routing noise. Both answer "is an execution plan OPEN?" and
   must agree across every plan state. TP-149 (L08) aligned task_router on
   the in_progress-but-empty-``steps`` case (plan_guard already treated it
   as ``no-steps`` → not active); this test pins the agreement so the two
   predicates can't silently drift apart again.

The AST helpers read source text only — no cross-module import — so the
``tools/cc/`` standalone-script isolation is preserved (and the statusline
cross-dir import problem is sidestepped).
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"
STATUSLINE = REPO_ROOT / "tools" / "cc" / "statusline.py"


# --------------------------------------------------------------------------
# AST helpers — extract literals without importing the standalone modules.
# --------------------------------------------------------------------------
def _module_assign_str(path: Path, name: str) -> str:
    """Return the str value assigned to a top-level ``name = "..."`` in path."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        for target in targets:
            if (
                isinstance(target, ast.Name)
                and target.id == name
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                return node.value.value
    raise AssertionError(f"{name} = <str literal> not found at module scope in {path}")


def _module_assign_str_tuple(path: Path, name: str) -> tuple[str, ...]:
    """Return the str-tuple assigned to a top-level ``name = ("a", "b")`` in path.

    Same AST-only discipline as ``_module_assign_str`` (441-E): the hook is a
    standalone script under the ``tools/cc/`` zero-espalier-import rule, so its
    constants are read from source text and never imported.

    Rejects a non-literal element rather than skipping it — a computed member
    would make the parity assertion below silently partial, which is the same
    fail-quiet shape the assertion exists to close.

    Collects EVERY module-scope match and requires exactly one, rather than
    returning the first. With first-match-wins, three shapes diverge silently
    from the runtime value: the name assigned twice, a ``del`` then redefine,
    and ``NAME += (...)``. In each the helper reads the first literal while the
    module actually uses the last, so the parity assertion would compare against
    a value the hook does not have. Making the resolution rule explicit costs
    one assert and removes all three.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    matches: list[ast.expr] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                matches.append(node.value)

    assert matches, (
        f"{name} = <str tuple literal> not found at module scope in {path}"
    )
    assert len(matches) == 1, (
        f"{name} is assigned {len(matches)} times at module scope in {path}. "
        f"This reader would take one of them while the module uses the last, so "
        f"the parity assertion could pass against a value the hook does not "
        f"actually hold. Collapse to a single assignment."
    )
    value = matches[0]
    assert isinstance(value, (ast.Tuple, ast.List)), (
        f"{name} in {path} is no longer a literal tuple/list (found "
        f"{type(value).__name__}); a computed value cannot be compared across "
        f"the zero-import boundary by reading source text"
    )
    out: list[str] = []
    for elt in value.elts:
        assert (
            isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        ), (
            f"{name} in {path} has a non-str-literal element "
            f"({ast.dump(elt)[:60]}...); this parity check reads "
            f"literals only and must not silently skip a member"
        )
        out.append(elt.value)
    return tuple(out)


def _string_constants(path: Path) -> set[str]:
    """All str constants anywhere in path's AST (literals only — not comments)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


# --------------------------------------------------------------------------
# B-2 — bare-literal SoT parity (AST reads; no import).
# --------------------------------------------------------------------------
class TestHookConstantParity:
    def test_reflect_warn_flag_cleared_by_session_start(self):
        flag = _module_assign_str(HOOKS_DIR / "reflect_trigger.py", "WARN_FLAG_FILE")
        cleared = _string_constants(HOOKS_DIR / "session_start.py")
        assert flag in cleared, (
            f"session_start must clear reflect_trigger.WARN_FLAG_FILE ({flag!r}) "
            f"each session, else the one-shot missing-script WARN goes silent "
            f"after the first session"
        )

    def test_stop_gate_env_literal_matches_consumers(self):
        """ALL FIVE readers, not two.

        This pinned ``session_start`` and ``statusline`` only, while
        ``subagent_start`` and ``_reinject`` each declare their OWN
        ``_STOP_GATE_ENV = "ESPALIER_STOP_GATE"`` — unpinned against the SoT, so
        a rename would strand them silently, which is the exact failure this
        test names. Measured at 2-of-5 during TP-410's 0-A.
        """
        env = _module_assign_str(HOOKS_DIR / "stop_gate.py", "STOP_GATE_MODE_ENV")
        consumers = (
            HOOKS_DIR / "session_start.py",
            HOOKS_DIR / "subagent_start.py",
            HOOKS_DIR / "_reinject.py",
            STATUSLINE,
        )
        for consumer in consumers:
            assert env in _string_constants(consumer), (
                f"{consumer.name} must read the stop-gate env literal ({env!r}) "
                f"defined by stop_gate.STOP_GATE_MODE_ENV — a rename here strands "
                f"the consumer silently"
            )

    def test_core_flow_fallback_matches_sot(self):
        """441-E: the SECOND half of the CORE_FLOW_COMMANDS two-site class.

        ``espalier/render_surface.py::CORE_FLOW_COMMANDS`` is the SoT;
        ``session_start.py::_CORE_FLOW_COMMANDS`` is a forced crash-fallback
        copy across the zero-espalier-import boundary. Each site carries a
        ``# sister-site: ok`` marker that DECLARES the relationship.

        ⚠ Those markers are NOT decorative, and the first draft of this docstring
        claimed they were. MEASURED: sister_site_probe reads an opt-out marker
        above every module-level ASSIGNMENT, not only above a def — its
        constant/concept detector and its alias-miss detector each consult
        _opt_out_marker_above at the top of their module-body loop. Remove the
        two markers, re-run the probe, and a NEW concept_overlaps finding
        appears naming both sites with an identical value hash. So the probe
        ALREADY had a live detector for this exact pair and the marker was
        SUPPRESSING it. tests/_surface_expected.py records the same fact about
        EXPECTED_OPT_OUT_CEILING: a def-only reading "passed vacuously at 0".

        That matters past this test. Root CLAUDE.md Core Rule 12 names the probe
        as THE class oracle, so believing a marker above a constant is inert
        turns a quiet run into false reassurance — and the rule's own text
        already warns that rc=0 is not evidence of no class. A confident wrong
        mechanism is worse than no explanation.

        The CONCLUSION survives, for a different reason than first written: the
        marker suppresses the one detector that saw this pair, and the surviving
        concept_overlaps arm is advisory rather than blocking, so nothing reds on
        divergence. Hence this assertion.

        Fixing only the doc-facing half of this class is the Core-Rule-12 trap:
        the docs would go green while a fresh adopter's SessionStart banner
        still lost ``/smoke /preflight /handoff`` on the fallback path (the
        path taken whenever cc/COMMANDS.md is missing, unreadable, or
        pre-regen — i.e. exactly on a fresh adopter's first session).

        Exact ordered equality, not set equality: the banner joins in tuple
        order, so a reorder is a real divergence.
        """
        from espalier.render_surface import CORE_FLOW_COMMANDS

        fallback = _module_assign_str_tuple(
            HOOKS_DIR / "session_start.py", "_CORE_FLOW_COMMANDS"
        )
        assert fallback == tuple(CORE_FLOW_COMMANDS), (
            "session_start._CORE_FLOW_COMMANDS has drifted from "
            "render_surface.CORE_FLOW_COMMANDS (the SoT).\n"
            f"  SoT      : {tuple(CORE_FLOW_COMMANDS)}\n"
            f"  fallback : {fallback}\n"
            "The fallback is what a fresh adopter's FIRST banner renders, so a "
            "narrowing here is invisible until an adopter hits it. Update the "
            "hook, then run python3 scripts/sync_vendor_cc.py for the "
            "espalier/_vendor/cc mirror row."
        )


# --------------------------------------------------------------------------
# B-3 — cross-hook predicate parity. Imports both standalone modules in the
# TEST process (not across the source files) to drive the predicates with the
# same plan JSON. plan_guard takes ``root``; task_router reads CLAUDE_PROJECT_DIR.
# --------------------------------------------------------------------------
sys.path.insert(0, str(HOOKS_DIR))
import plan_guard  # noqa: E402
import task_router  # noqa: E402

# (label, plan-dict, expected-active)
_PLAN_STATES = [
    ("in_progress_with_steps", {"status": "in_progress", "steps": ["s1"]}, True),
    ("in_progress_no_steps", {"status": "in_progress", "steps": []}, False),
    ("in_progress_missing_steps", {"status": "in_progress"}, False),
    ("complete", {"status": "complete", "steps": ["s1"]}, False),
    ("planned", {"status": "planned", "steps": ["s1"]}, False),
    ("empty_status", {"status": "", "steps": ["s1"]}, False),
]


class TestActivePlanPredicateParity:
    @pytest.mark.parametrize(
        "label,plan,expected",
        _PLAN_STATES,
        ids=[s[0] for s in _PLAN_STATES],
    )
    def test_predicates_agree(self, tmp_path, monkeypatch, label, plan, expected):
        cc_dir = tmp_path / "cc"
        cc_dir.mkdir()
        (cc_dir / "execution_plan.json").write_text(json.dumps(plan), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        pg = plan_guard._has_active_plan(tmp_path)
        tr = task_router._has_active_plan()
        assert pg == tr == expected, (
            f"{label}: plan_guard={pg!r} task_router={tr!r} expected={expected!r} "
            f"— the two _has_active_plan predicates disagree"
        )

    def test_missing_plan_file_both_inactive(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        assert plan_guard._has_active_plan(tmp_path) is False
        assert task_router._has_active_plan() is False

    def test_malformed_plan_file_both_inactive(self, tmp_path, monkeypatch):
        cc_dir = tmp_path / "cc"
        cc_dir.mkdir()
        (cc_dir / "execution_plan.json").write_text("{not valid json", encoding="utf-8")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        assert plan_guard._has_active_plan(tmp_path) is False
        assert task_router._has_active_plan() is False


class TestStopGateGrammarParity:
    """The LITERAL axis above proves the readers name the same env var. It says
    nothing about whether they AGREE on what a value MEANS — and they did not.

    Measured at HEAD: five readers, five grammars —
      stop_gate      ``.strip().lower()`` + recognized-set  (canonical)
      session_start  raw ``!= "full"``
      statusline     ``.lower()`` only
      subagent_start ``or "light"``, raw
      _reinject      raw ``!= "light"``
    so a space-padded value ran the FULL pytest suite on every Stop while the
    statusline showed no indicator and the dormancy note never fired.

    Severity is honestly small — a normal parent-shell launch cannot produce a
    padded value, so the fully-silent shape needs a deliberately odd one — but
    five spellings of one decision is a class, and the fix is one helper.
    """

    @pytest.mark.parametrize("raw,expected", [
        ("full", "full"), ("Full", "full"), ("full ", "full"),
        (" full", "full"), ("  FULL  ", "full"), ("\tfull\n", "full"),
        ("light", "light"), ("scan-clean", "scan-clean"),
        ("", "light"), (None, "light"), ("   ", "light"),
    ])
    def test_normalizer_canonicalizes_case_and_whitespace(self, raw, expected):
        import _hook_utils
        assert _hook_utils.stop_gate_mode(raw) == expected

    def test_normalizer_never_returns_an_empty_mode(self):
        import _hook_utils
        for raw in ("", "   ", None, "\t\n"):
            assert _hook_utils.stop_gate_mode(raw), repr(raw)

    def test_no_hook_reimplements_the_normalization(self):
        """Every reader routes through the helper rather than re-spelling
        ``.lower()`` / ``.strip()`` / a bare ``!=`` on the env value — the
        divergence that produced five grammars in the first place."""
        import re as _re

        offenders = []
        for name in ("session_start.py", "subagent_start.py", "_reinject.py"):
            src = (HOOKS_DIR / name).read_text(encoding="utf-8")
            for line in src.splitlines():
                # Inspect the whole LINE, not the regex match: the helper call
                # WRAPS the os.environ.get(...), so a match-scoped check cannot
                # see the `stop_gate_mode(` prefix and reports a false offender.
                if not _re.search(r"os\.environ\.get\([^)\n]*STOP_GATE", line):
                    continue
                if "stop_gate_mode" in line:
                    continue
                offenders.append(f"{name}: {line.strip()[:80]}")
        assert not offenders, (
            "reader parses the stop-gate env inline instead of via "
            "_hook_utils.stop_gate_mode:\n  " + "\n  ".join(offenders)
        )
