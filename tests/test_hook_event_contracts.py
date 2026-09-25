"""TP-110: pin hook event-name strings across CHW + external CC
protocol + hook script ``"hookEventName"`` JSON output.

Two assertion chains:

1. ``test_chw_events_subset_of_cc_protocol`` — CHW events must be a
   subset of the events declared in ``docs/external/cc-hook-protocol.md``.
   Catches CHW referencing an event Claude Code doesn't ship (typo,
   deprecated event) OR the external-pin doc going stale relative to
   the live CC release CHW is built against. Drift in either direction
   surfaces here, before runtime.

2. ``TestHookEventContracts`` — every hook script that emits a
   ``"hookEventName": "<Event>"`` JSON field (3 hooks per C-S07
   registry narrowing: ``plan_guard``, ``session_start``,
   ``write_guard``) declares the same event name CHW wires it to.
   Vacuous-pass guarded by ``len(matches) >= 1`` per TP-109b
   dataclass contract — a source listed in ``StringContract.sources``
   must produce at least one match.

Failure mode this catches: a future hook rename or event-renaming
refactor that updates CHW but forgets to update the hook script's
emitted ``hookEventName`` field (or vice-versa) — the two would
silently diverge until a CC user reports the wrong event name in
their hook log.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from espalier.harness_config import HOOK_EVENTS
from tests._contracts import StringContract, extract_matches

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_DOC = REPO_ROOT / "docs/external/cc-hook-protocol.md"

# Pattern matches the `"hookEventName": "<Event>"` JSON literal that
# hook scripts emit when reporting structured decisions back to Claude
# Code (per docs/external/cc-hook-protocol.md channel-XOR protocol).
# Only 7 hooks emit this field (TP-163 added subagent_start +
# context_reinject_failure to the original C-S07 three; TP-164 added
# post_write_check's PostToolUse recall-reinject emit; TP-189-A added
# reflect_trigger's PostToolUse drift emit; verified by
# `grep -l hookEventName tools/cc/hooks/*.py`).
_HOOK_EVENT_NAME_RE = r'"hookEventName":\s*"([A-Z][a-zA-Z]+)"'


HOOK_EVENT_CONTRACTS: tuple[StringContract, ...] = (
    StringContract(
        name="PreToolUse hookEventName JSON output",
        expected_value="PreToolUse",
        sources=(
            # Both PreToolUse-wired hooks per CANONICAL_HOOK_WIRING.
            ("tools/cc/hooks/write_guard.py", _HOOK_EVENT_NAME_RE),
            ("tools/cc/hooks/plan_guard.py", _HOOK_EVENT_NAME_RE),
        ),
    ),
    StringContract(
        name="SessionStart hookEventName JSON output",
        expected_value="SessionStart",
        sources=(
            ("tools/cc/hooks/session_start.py", _HOOK_EVENT_NAME_RE),
        ),
    ),
    # TP-163: the two new reporter hooks emit hookEventName too. Without
    # these entries, test_every_hookEventName_emitter_in_contracts (the
    # completeness backstop below) goes RED the moment the scripts exist.
    StringContract(
        name="SubagentStart hookEventName JSON output",
        expected_value="SubagentStart",
        sources=(
            ("tools/cc/hooks/subagent_start.py", _HOOK_EVENT_NAME_RE),
        ),
    ),
    StringContract(
        name="PostToolUseFailure hookEventName JSON output",
        expected_value="PostToolUseFailure",
        sources=(
            ("tools/cc/hooks/context_reinject_failure.py", _HOOK_EVENT_NAME_RE),
        ),
    ),
    # TP-164: post_write_check gained a PostToolUse additionalContext emit path
    # (the recall-engine reinject dispatch) -- it previously reported only via
    # stderr. Pin its emitted event name so the completeness backstop stays green.
    StringContract(
        name="PostToolUse hookEventName JSON output",
        expected_value="PostToolUse",
        sources=(
            ("tools/cc/hooks/post_write_check.py", _HOOK_EVENT_NAME_RE),
            # TP-189-A (OVERCLAIM-2): reflect_trigger's non-clean branch now emits
            # a PostToolUse additionalContext (surface drift -> the agent), where
            # it previously reported only via stderr.
            ("tools/cc/hooks/reflect_trigger.py", _HOOK_EVENT_NAME_RE),
        ),
    ),
    # Only these 7 hook scripts emit "hookEventName" (the original C-S07
    # three + TP-163's subagent_start + context_reinject_failure + TP-164's
    # post_write_check + TP-189-A's reflect_trigger); other hooks return
    # decisions via different channels and are not in scope.
)


def _parse_cc_protocol_events() -> frozenset[str]:
    """Extract event names from the per-event exit-2 table in the
    pinned external CC protocol doc.

    Table shape (per cc-hook-protocol.md:78-87):
        | Event | Exit 2 effect |
        |---|---|
        | PreToolUse | Blocks tool call; stderr → Claude |
        | Stop / SubagentStop | Blocks stoppage; ...
        | ...

    Compound cells like "Stop / SubagentStop" are split into
    individual event names. Header row "Event" is skipped.
    """
    text = PROTOCOL_DOC.read_text(encoding="utf-8")
    events: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"\|\s*([A-Z][\w/ ]*?)\s*\|", line)
        if not m:
            continue
        cell = m.group(1)
        if cell == "Event":
            continue
        for tok in re.split(r"\s*/\s*", cell):
            tok = tok.strip()
            if re.fullmatch(r"[A-Z][a-zA-Z]+", tok):
                events.add(tok)
    return frozenset(events)


def test_chw_events_subset_of_cc_protocol():
    """Every event in CHW must be a known CC protocol event.

    Catches: CHW references an event CC doesn't ship (typo or
    deprecated event), OR cc-hook-protocol.md is stale relative to
    the CC release CHW is built against.
    """
    protocol_events = _parse_cc_protocol_events()
    missing = HOOK_EVENTS - protocol_events
    assert not missing, (
        f"CHW references {missing!r} not declared in "
        f"docs/external/cc-hook-protocol.md. Either refresh the "
        f"external pin (via espalier-refresh-externals workflow) "
        f"or remove the unsupported hook from CHW."
    )


class TestHookEventContracts:
    @pytest.mark.parametrize(
        "contract", HOOK_EVENT_CONTRACTS, ids=lambda c: c.name
    )
    def test_every_source_extracts_matching_value(
        self, contract: StringContract
    ):
        for relpath, pattern in contract.sources:
            matches = extract_matches(REPO_ROOT / relpath, pattern)
            # Vacuous-pass guard per TP-109b dataclass contract:
            # absence of match is itself a failure (a source listed
            # in contracts.sources MUST have at least one extractable
            # value).
            assert len(matches) >= 1, (
                f"{relpath}: regex {pattern!r} extracted zero matches; "
                f"source-listing without a match is a contract bug "
                f"(rule: hook-event-banner)."
            )
            for value in matches:
                assert value == contract.expected_value, (
                    f"{relpath}: expected {contract.expected_value!r}, "
                    f"got {value!r}"
                )


def test_every_hookEventName_emitter_in_contracts():
    """TP-151 H-2: completeness backstop (U ⊆ R). Every hook script that emits
    a ``"hookEventName"`` JSON field must be covered by a HOOK_EVENT_CONTRACTS
    source — else a new emitter ships with its event-name unpinned against CHW
    (the registry is the iteration domain; an unlisted emitter is invisible).
    Sister to the TP-150 'registration-set as iteration domain' mode."""
    hooks_dir = REPO_ROOT / "tools" / "cc" / "hooks"
    emitters = {
        f"tools/cc/hooks/{p.name}"
        for p in hooks_dir.glob("*.py")
        if '"hookEventName"' in p.read_text(encoding="utf-8")
    }
    registered = {
        src_path
        for contract in HOOK_EVENT_CONTRACTS
        for src_path, _regex in contract.sources
    }
    missing = emitters - registered
    assert not missing, (
        f"hooks emitting hookEventName not in HOOK_EVENT_CONTRACTS: "
        f"{sorted(missing)}. Add a StringContract source pinning the emitted "
        f"event name to CANONICAL_HOOK_WIRING."
    )


def test_governance_blocking_hooks_match_canonical_wiring():
    """TP-169 §13 #8 (N7): GOVERNANCE_BLOCKING_HOOKS is the SoT for the
    deleted-event completeness oracle (espalier.doctor + ci_guard mirror). Each
    ``script -> event`` must agree with CANONICAL_HOOK_WIRING and each script
    must be a real canonical hook — so the oracle can never demand a wiring CHW
    does not declare. The membership is pinned explicitly so adding a new
    blocking hook forces an oracle update (5th surface for the blocking-set)."""
    from espalier.harness_config import (
        CANONICAL_HOOK_WIRING,
        GOVERNANCE_BLOCKING_HOOKS,
    )

    assert set(GOVERNANCE_BLOCKING_HOOKS) == {
        "write_guard.py", "plan_guard.py", "config_guard.py", "stop_gate.py"
    }, "the blocking-governance subset drifted — update the oracle deliberately"
    for script, event in GOVERNANCE_BLOCKING_HOOKS.items():
        assert script in CANONICAL_HOOK_WIRING, f"{script} not a canonical hook"
        assert CANONICAL_HOOK_WIRING[script]["event"] == event, (
            f"{script} mapped to {event!r} but CANONICAL_HOOK_WIRING wires it "
            f"under {CANONICAL_HOOK_WIRING[script]['event']!r}"
        )


def test_governance_reporter_hooks_are_the_canonical_remainder():
    """DEF-619: the two tiers PARTITION the canonical roster, and the reporter
    tier is derived rather than typed, so a new hook is in a tier the moment
    it is declared. ``GATE_EVENT_OF`` answers for every canonical hook -- the
    shape classifier and both narrators read it for a reporter too."""
    from espalier.harness_config import (
        CANONICAL_HOOK_WIRING,
        GATE_EVENT_OF,
        GOVERNANCE_BLOCKING_HOOKS,
        GOVERNANCE_REPORTER_HOOKS,
    )

    assert set(GOVERNANCE_BLOCKING_HOOKS) | set(GOVERNANCE_REPORTER_HOOKS) == set(
        CANONICAL_HOOK_WIRING
    ), "the two tiers no longer cover the canonical roster"
    assert not set(GOVERNANCE_BLOCKING_HOOKS) & set(GOVERNANCE_REPORTER_HOOKS), (
        "a hook is in both tiers"
    )
    for script, event in GOVERNANCE_REPORTER_HOOKS.items():
        assert CANONICAL_HOOK_WIRING[script]["event"] == event
        assert GATE_EVENT_OF(script) == event
    for script, event in GOVERNANCE_BLOCKING_HOOKS.items():
        assert GATE_EVENT_OF(script) == event
    assert GATE_EVENT_OF("not_a_hook.py") == "?"


def test_blocking_tier_stays_readable_by_the_ci_twin():
    """DEF-619: the engine predicate now checks a matcher wherever the canonical
    wiring declares one and every token of it; tools/cc/ci_guard.py's twin
    still checks PreToolUse only and the mutation trio only. The two agree
    exactly while every blocking gate's canonical matcher is empty or a
    PreToolUse matcher made of mutation-tool tokens -- true today, asserted
    here so a wider blocking matcher (or a blocking gate on another event)
    reds until the twin is widened with it. That is the doctor-closed /
    ci-open drift the parity lock exists to end."""
    from espalier import surface_contract as sc
    from espalier.harness_config import (
        CANONICAL_HOOK_WIRING,
        GOVERNANCE_BLOCKING_HOOKS,
    )

    fire_all = {"", "*", ".*"}
    mutation_tools = set(sc._MUTATION_MATCHER_TOOLS)
    for script, event in GOVERNANCE_BLOCKING_HOOKS.items():
        matcher = CANONICAL_HOOK_WIRING[script]["matcher"]
        if matcher in fire_all:
            continue
        assert event == "PreToolUse", (
            f"{script} carries a matcher under {event!r}; ci_guard checks "
            "matchers on PreToolUse only -- widen the twin first"
        )
        assert set(matcher.split("|")) <= mutation_tools, (
            f"{script}'s canonical matcher {matcher!r} has tokens outside the "
            "mutation trio; ci_guard's twin cannot see them -- widen it first"
        )


def test_every_canonical_matcher_token_has_a_probe_shape():
    """`surface_contract.matcher_token_probe` knows two shapes: a plain tool
    name and a `.*`-wildcard pattern. A third shape must red when declared,
    not when a narrowed matcher on it reads as wired."""
    import re

    from espalier.harness_config import CANONICAL_HOOK_WIRING

    for script, spec in CANONICAL_HOOK_WIRING.items():
        for token in spec["matcher"].split("|"):
            if token in ("", "*", ".*"):
                continue
            assert re.fullmatch(r"[A-Za-z0-9_]+", token) or token.endswith(".*"), (
                f"{script}: matcher token {token!r} has a shape "
                "matcher_token_probe does not know"
            )


class TestGateShapeRoster:
    """A new gate shape must red at BIRTH, not when a tree carrying one appears.

    ``classify_unwired_gate`` returns one of the ``GATE_SHAPES``, and two narrators
    dispatch on them (``cli._unwired_gate_diagnosis`` and ``doctor``'s
    partial-disarm arm). Both consult ``harness_config.GATE_SHAPES`` to decide
    what they do NOT recognize, so a fifth shape degrades to a vague-but-honest
    line instead of vanishing.

    ⚠ That degradation is a floor, not the gate. A review pass named the
    residual precisely: someone who adds ``GATE_KILLSWITCHED`` and gives it a
    proper clause in both narrators, but forgets to add it to this roster, gets
    a gate narrated TWICE -- its own sentence plus "a shape this banner cannot
    name" -- and nothing reds, because the fifth-shape row only asserts that the
    gate appears. This row is the one that fires the moment the constant is
    written, which is the only moment the author is still looking.

    Same remedy the sibling script set already uses (``GOVERNANCE_BLOCKING_HOOKS``
    is pinned against ``CANONICAL_HOOK_WIRING``); this is docs/FAILURE_MODES.md
    §18.4 applied to the shape set instead of the script set.
    """

    def test_roster_matches_the_live_constants(self):
        from espalier import harness_config as hc

        live = {
            value for name, value in vars(hc).items()
            if name.startswith("GATE_") and isinstance(value, str)
        }

        assert live == set(hc.GATE_SHAPES), (
            "a GATE_* shape constant is not in harness_config.GATE_SHAPES.\n"
            "Adding a shape means FIVE edits, not one:\n"
            "  1. classify_unwired_gate -- return it\n"
            "  2. cli._unwired_gate_diagnosis -- give it a clause AND decide "
            "whether merge-settings fixes it (if not, it belongs in `unfixed`)\n"
            "  3. doctor's partial-disarm arm -- give it a next_step\n"
            "  4. cli._REPAIR_HANDLED_SHAPES or _REPAIR_SKIPPED_SHAPES -- file "
            "it on one side of the --repair dispatch\n"
            "  5. GATE_SHAPES -- add it here last\n"
            f"missing from the roster: {sorted(live - set(hc.GATE_SHAPES))}\n"
            f"in the roster but not a constant: "
            f"{sorted(set(hc.GATE_SHAPES) - live)}"
        )

    def test_every_shape_in_the_roster_is_actually_narrated(self):
        """The roster pin has INVERTED polarity; this is the row that fixes it.

        ⚠ Both narrators compute their honest-degradation arm as
        ``shape not in GATE_SHAPES``. So enrolling a shape in the roster is
        precisely what DISARMS the "a shape this banner cannot name" fallback --
        and ``test_roster_matches_the_live_constants`` above goes GREEN at that
        same instant. The two mitigations 56dc018 shipped are mutually
        exclusive: satisfying one switches off the other, and the state where a
        shape has a roster entry but no clause is the state where nothing reds
        and the gate VANISHES from the banner entirely (reason renders as the
        literal ``'Hooks are NOT yet active: .'``).

        Measured, not reasoned: adding a shape constant + roster entry and no
        clause reproduces that string. This row closes it by asserting the thing
        that actually matters -- an operator is TOLD which gate is dead -- for
        every member of the roster, so a new shape reds until it is narrated.
        """
        from espalier import cli, harness_config as hc

        for shape in sorted(hc.GATE_SHAPES):
            reason, remedies = cli._unwired_gate_diagnosis(
                {shape: ["write_guard.py"]}, "python3"
            )
            spoken = reason + " " + " ".join(remedies)
            assert "write_guard.py" in spoken, (
                f"shape {shape!r} is in harness_config.GATE_SHAPES but "
                f"cli._unwired_gate_diagnosis never NAMES the affected gate, so "
                f"it silently drops out of the banner.\n"
                f"  reason:   {reason!r}\n"
                f"  remedies: {remedies!r}\n"
                "Roster membership switches OFF the unrecognized-shape "
                "fallback, so a shape added to GATE_SHAPES without its own "
                "clause is worse than one left out of it."
            )
            if shape == hc.GATE_LEGACY_FORM:
                # The ONE documented exemption, and it is not a loophole: the
                # claim ABSTAINS on legacy_form, so `_disarmed_diagnosis` guards
                # the narrator with `set(shapes) - {GATE_LEGACY_FORM}` and a
                # legacy-only tree never reaches this function at all. Asserting
                # a clause here would pin an unreachable state. It still must be
                # NAMED (the assertion above) because it rides in the caveat
                # when it CO-OCCURS with a shape that does reach the narrator.
                #
                # ⚠ Exactly one shape may sit here. If the abstention ever grows
                # a second member, this branch must grow with it -- and the fact
                # that that coupling is written in prose rather than derived is
                # a known weakness, tracked for the claim-policy partition.
                continue
            assert reason.strip() not in ("Hooks are NOT yet active: .",
                                          "Hooks are NOT yet active:."), (
                f"shape {shape!r} renders the empty-clause banner verbatim -- "
                "the gate is named nowhere and the operator is told nothing"
            )

    def test_every_shape_is_filed_on_one_side_of_the_repair_dispatch(self):
        """DEF-618: `--repair` dispatches on the shapes by name and skips what
        it does not know. A shape narrated by both narrators as "run --repair"
        but missing from the dispatch is a loop (doctor -> --repair -> "nothing
        to repair" -> doctor) with nothing red. The two frozensets partition
        the roster, so a new shape reds here until it is filed."""
        from espalier import cli, harness_config as hc

        assert cli._REPAIR_HANDLED_SHAPES | cli._REPAIR_SKIPPED_SHAPES == set(hc.GATE_SHAPES), (
            sorted(set(hc.GATE_SHAPES) ^ (cli._REPAIR_HANDLED_SHAPES | cli._REPAIR_SKIPPED_SHAPES))
        )
        assert not cli._REPAIR_HANDLED_SHAPES & cli._REPAIR_SKIPPED_SHAPES

    def test_every_repairable_shape_is_offered_the_repair_by_the_banner(self):
        """The narrator must not send an operator to a hand edit for a shape
        the command rewrites (that was the DEF-618 defect on every surface)."""
        from espalier import cli

        for shape in sorted(cli._REPAIR_HANDLED_SHAPES):
            _reason, remedies = cli._unwired_gate_diagnosis({shape: ["write_guard.py"]}, "python3")
            spoken = " ".join(remedies)
            assert "merge-settings" in spoken, (shape, remedies)
            if shape != cli.GATE_ABSENT:
                assert "--repair" in spoken, (shape, remedies)

    def test_every_name_the_gate_shapes_pointer_cites_resolves(self):
        """The ``#:`` pointer above ``GATE_SHAPES`` names the narrators a new
        one must route through. A prose enumeration of symbols is the
        hand-maintained-doc-enumeration footgun in miniature: nothing reds when
        a narrator moves, so the pointer sends the next author to a name that
        is gone. Derive the names from the comment, resolve each on its module.
        ``_dead_reporters_line`` was named by no test before this one
        (failure-mode pass, 2026-09-08)."""
        import inspect
        import re

        from espalier import cli, doctor, harness_config as hc

        source = inspect.getsource(hc)
        head, sep, _tail = source.partition("\nGATE_SHAPES = frozenset(")
        assert sep, "GATE_SHAPES is no longer defined as a frozenset literal"
        comment = "\n".join(
            ln for ln in head.splitlines()[-40:] if ln.startswith("#:")
        )
        cited = set(re.findall(r"``(cli|doctor)\.([A-Za-z_]+)``", comment))
        assert len(cited) >= 6, (
            f"the pointer comment names {len(cited)} dotted symbols -- the parser "
            "or the comment shape changed; fix the extraction, do not lower the floor"
        )
        modules = {"cli": cli, "doctor": doctor}
        missing = sorted(f"{m}.{n}" for m, n in cited if not hasattr(modules[m], n))
        assert not missing, (
            f"the GATE_SHAPES pointer names symbols that no longer exist: {missing}. "
            "Repoint the comment at the surviving narrator."
        )

    def test_both_narrators_read_the_same_roster(self):
        """One roster, not three. There were three for about an hour."""
        import inspect

        from espalier import cli, doctor

        for module in (cli, doctor):
            source = inspect.getsource(module)
            assert "GATE_SHAPES" in source, (
                f"{module.__name__} no longer consults the shared shape roster "
                "-- a local copy of the shape set is free to drift from it"
            )
