"""Parity rail + dispatch canary for the generative recall face (TP-166).

The generative ``EXEMPLAR_MAP`` is the inverse of the defensive/sync rules: inject
the canonical exemplar BEFORE an artifact is born (at ``UserPromptSubmit``). TP-166
ships the substrate ALL PULL-ONLY -- the catalog is inert (zero live generative
``REINJECTS`` rows) until TP-167's ``_recall.py`` serves it. This file proves:

  1. the ``task_router`` UserPromptSubmit dispatch is wired (the canary);
  2. the ``push_eligible`` parity rail BITES -- a pushed generative rule with no
     parity test is flagged (the earn-the-gate red proof, TP-105 discipline);
  3. every catalogued exemplar is pull-only and the catalog is pinned.

Without this rail a pushed exemplar silently drifts from its canonical source -- the
drift bomb (docs/SHARP_EDGES.md) this contract prevents. The non-vacuous earn-the-gate
proof guards against the worse failure mode: a rail that passes only because nothing is
pushed yet, then never reddens when the first un-pinned push row lands.

Note on the dispatch canary: ``_reinject.check(..., *, rules=REINJECTS)`` binds its
default at def-time, so monkeypatching ``_reinject.REINJECTS`` does NOT reach the
default. The wiring proof therefore spies on ``_reinject.check`` itself (proving
task_router calls it with the right event/args and prints its payloads); check()'s
own internals are covered by tests/test_reinject.py + tests/test_reinject_sync.py.
"""
# pytest-marker: default-unit  (in-process imports of task_router / _reinject with
# tmp_path roots + capsys; no subprocess, no security/integration surface)
from __future__ import annotations

import re
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import _reinject  # noqa: E402
import task_router  # noqa: E402


# ── 166-A: the UserPromptSubmit generative dispatch is wired ──────────────────

def test_task_router_dispatches_check_payloads_to_stdout(tmp_path, monkeypatch, capsys):
    """task_router calls _reinject.check for the UserPromptSubmit event with the
    prompt, and PRINTS each returned payload to plain stdout (the wiring proof)."""
    seen = {}

    def fake_check(event, tool_name, tool_input, root, *, rules=None):
        seen["args"] = (event, tool_name, tool_input, root)
        return ["GEN-EXEMPLAR-1", "GEN-EXEMPLAR-2"]

    monkeypatch.setattr(_reinject, "check", fake_check)
    monkeypatch.setattr(task_router, "resolve_project_root", lambda: tmp_path)
    monkeypatch.setattr(task_router, "read_stdin_safely",
                        lambda: {"prompt": "draft a brand new task pack"})

    rc = task_router._run_main()
    out = capsys.readouterr().out

    assert rc == 0                                                   # advisory: never rejects
    assert seen["args"] == ("UserPromptSubmit", "",
                            {"prompt": "draft a brand new task pack"}, tmp_path)
    assert "GEN-EXEMPLAR-1" in out and "GEN-EXEMPLAR-2" in out       # dispatch printed them


def test_generative_payload_prints_after_routing_nudge(tmp_path, monkeypatch, capsys):
    """When both fire, the recall payload prints AFTER the routing nudge (the
    safety/routing advisory keeps first position; recall enriches, never preempts)."""
    monkeypatch.setattr(_reinject, "check", lambda *a, **k: ["GEN-PAYLOAD"])
    monkeypatch.setattr(task_router, "resolve_project_root", lambda: tmp_path)
    monkeypatch.setattr(task_router, "read_stdin_safely",
                        lambda: {"prompt": "implement a new feature end to end"})

    rc = task_router._run_main()
    out = capsys.readouterr().out

    assert rc == 0
    assert task_router.ROUTING_GUIDANCE in out
    assert "GEN-PAYLOAD" in out
    assert out.index(task_router.ROUTING_GUIDANCE) < out.index("GEN-PAYLOAD")


def test_task_router_never_rejects_and_stays_plain_stdout(tmp_path, monkeypatch, capsys):
    """channel-XOR: UserPromptSubmit is advisory -- exit 0, output is plain stdout
    (no JSON envelope). A generative payload does not change that posture."""
    monkeypatch.setattr(_reinject, "check", lambda *a, **k: ["EXEMPLAR-TEXT"])
    monkeypatch.setattr(task_router, "resolve_project_root", lambda: tmp_path)
    monkeypatch.setattr(task_router, "read_stdin_safely",
                        lambda: {"prompt": "a quiet prompt with no routing signal"})

    rc = task_router._run_main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "EXEMPLAR-TEXT" in out
    assert not out.lstrip().startswith("{")                          # not a JSON envelope


def test_real_registry_emits_no_generative_payload(tmp_path):
    """The SHIPPED registry has zero UserPromptSubmit generative rows, so the real
    check() returns [] even for a prompt that names an artifact -- the catalog is
    PULL-ONLY this pack (inert until TP-167 serves it)."""
    assert _reinject.check(
        "UserPromptSubmit", "", {"prompt": "write a new scanner and a new hook"}, tmp_path
    ) == []


# ── 166-C: the §11 #10 parity rail (mechanically NON-VACUOUS) ─────────────────

def unpinned_pushed(rules, parity_tested):
    """The rail predicate: ids of generative push_eligible rules that LACK a parity
    test. A non-empty result means a drift-prone exemplar can auto-inject without a
    red-on-violation guard -> the rail must redden."""
    return {r.id for r in rules
            if r.face == "generative" and r.push_eligible and r.id not in parity_tested}


# Exemplar ids with a real red-on-violation parity test in THIS file. EMPTY this pack:
# every catalogued exemplar is pull-only (no single byte-source), so none is pushed,
# so none needs a parity test yet. The moment TP-167+ adds a push_eligible generative
# REINJECTS row it MUST add its id here AND a parity test, or test_rail_holds reddens.
PARITY_TESTED: set[str] = set()


def test_rail_holds_for_shipped_registry():
    """The live rail: no pushed generative rule lacks a parity test. Passes because the
    shipped registry has zero generative push rows (all-pull-only this pack)."""
    assert unpinned_pushed(_reinject.REINJECTS, PARITY_TESTED) == set()


def test_rail_is_non_vacuous():
    """Earn-the-gate (TP-105 discipline): prove the rail BITES. A synthetic
    push_eligible generative rule with no parity test MUST be flagged -- otherwise the
    live pass above is meaningless."""
    synth = _reinject.ReinjectRule(
        id="SYNTH-UNPINNED", event="UserPromptSubmit",
        render=lambda tn, ti, root: "exemplar text",
        face="generative", push_eligible=True,
    )
    assert unpinned_pushed(_reinject.REINJECTS + (synth,), PARITY_TESTED) == {"SYNTH-UNPINNED"}


def test_check_mechanically_gates_pull_only_generative_rule(tmp_path):
    """Defense in depth: push_eligible gates the FIRING path, not just this test file. A
    pull-only (push_eligible=False) generative row never fires via check(); a
    push_eligible=True one does. So 'pull-only = never auto-pushed' is mechanical."""
    pull = _reinject.ReinjectRule(id="PULL", event="UserPromptSubmit",
                                  render=lambda tn, ti, root: "PULL-TEXT",
                                  face="generative", push_eligible=False)
    push = _reinject.ReinjectRule(id="PUSH", event="UserPromptSubmit",
                                  render=lambda tn, ti, root: "PUSH-TEXT",
                                  face="generative", push_eligible=True)
    assert _reinject.check("UserPromptSubmit", "", {"prompt": "x"}, tmp_path, rules=(pull,)) == []
    assert _reinject.check("UserPromptSubmit", "", {"prompt": "x"}, tmp_path, rules=(push,)) == ["PUSH-TEXT"]


def test_all_catalogued_exemplars_are_pull_only():
    """Every EXEMPLAR_MAP entry ships pull-only this pack (push_eligible=False). Flipping
    one to True without going through the rail (a parity test + a generative REINJECTS
    row) is exactly the drift the rail exists to catch."""
    pushed = {eid for eid, ex in _reinject.EXEMPLAR_MAP.items() if ex.push_eligible}
    assert pushed == set()


def test_exemplar_catalog_pinned():
    """The five canonical shapes are catalogued, each keyed by its own id."""
    expected = {"GEN-NEW-SCANNER", "GEN-NEW-HOOK", "GEN-NEW-TEST",
                "GEN-PACK-SKELETON", "GEN-CHANGELOG-FLATPROSE"}
    assert set(_reinject.EXEMPLAR_MAP) == expected
    assert len(_reinject.EXEMPLAR_MAP) == 5
    assert all(eid == ex.id for eid, ex in _reinject.EXEMPLAR_MAP.items())


def test_exemplar_triggers_are_valid_regexes():
    """Each catalogued trigger is a compilable re pattern (TP-167's pull engine compiles
    + matches them; a typo here would silently break recall later)."""
    for ex in _reinject.EXEMPLAR_MAP.values():
        re.compile(ex.trigger)  # raises re.error on a bad pattern
