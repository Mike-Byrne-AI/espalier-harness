# TP-259 — Goal-anchor: opportunistic-scope drift trigger (G1)

## Status

- **State: DRAFT — execution-ready.** No structural blocks found (unlike its
  siblings TP-260/261); this is the clean flagship of the goal-anchor family.
- **Review verdict (2026-07-09, `wf_9d4d2eb4`): SOUND-TO-EXECUTE — add one scope
  note.** Code is genuinely wired and fires on self-host, but G1's data source
  (`cc/GOAL.md ## Standing owed`) is gitignored/self-host-only, so it silently
  no-ops for essentially all adopters — graceful + frictionless, but the "flagship
  drift-catcher" framing overclaims reach. Add a Scope/Motivation note (fires only
  where a self-host-style `cc/GOAL.md` exists; opt-in for adopters), or broaden the
  gate to an always-present source. Not a block. Parked (Deferred) post-launch.
- **⚠ 0-A pre-flight (added 2026-07-27, TP-363 1-E): the anchor heading is GONE.** Fix 2 /
  `_goal_owed_digest` keys on `cc/GOAL.md`'s `## Standing owed` heading, which has since been
  **pruned** (current headings: `## Notes to next session` / `## Where the build stands`). As
  drafted, `_goal_owed_digest` returns `''` → the `if not digest: return None` gate suppresses
  the advisory for **everyone incl. self-host**. Re-point Fix 2 to an extant section (or broaden
  the source) before executing — the "owed digest is honest" pass criterion otherwise fails on
  the live GOAL.
- Version target: next minor
- Kind: PACK
- Type: feature (a new drift-from-goal advisory on an already-wired hook)
- Change class: extends `task_router`'s existing decision-shape advisory —
  UserPromptSubmit, plain-stdout, **frictionless** (advisory, never a deny). No
  new hook, no hook-count change, no `write_guard` surgery.

## Motivation

**Shared frame (goal-anchor family — TP-259/260/261).** "There is no drift, only
drift *from a goal*." The fix is to make the goal impossible to miss — but as a
**speed-bump (surface the goal at the moment it's about to be violated), not a
billboard (ambient re-surfacing you learn to ignore).** Three design invariants
bind every rule in the family:
1. **Mechanical trigger, not introspection.** Key on a detectable event; never ask
   "do you feel like you're drifting?" (maximally interpretation-open — the
   anti-pattern).
2. **Force the comparison.** The payload carries the goal and asks Claude to *name
   which owed item this serves* — a linkage you can state or can't.
3. **Inherit the anti-wallpaper gate.** `task_router._detect_decision_shape` already
   fires only on *pattern-match AND blueprint-has-≥1-decision*, deliberately —
   "without it the advisory fires on every 'should we'… training the agent to
   ignore the channel." Every family rule carries a gate like that or it
   self-destructs.

**This pack (G1).** The existing decision-shape detector catches *deliberative*
pivots ("should we X vs Y", "reconsider", "switch to"). It misses the highest-drift
class: **opportunistic scope** — adding work because a resource looks free.

Grounded evidence (the reason this pack exists): the actual drift-onset prompt this
session — *"maybe we could do this if it's worth it, considering there is time that
otherwise would be unused?"* — was checked against all 8 live
`_DECISION_SHAPE_PATTERNS` and **matches none of them.** The mechanism closest to a
drift-catcher stayed silent at the exact moment drift began. G1 closes that gap and
upgrades the payload from "surface prior decisions" to "surface the GOAL's standing-
owed list + force an ROI comparison."

## Scope (in)

- **1. Opportunistic-scope idiom class.** Add a second pattern tuple
  (`_OPPORTUNISTIC_SCOPE_PATTERNS`) covering the free-resource idiom: *worth it,
  might as well, while (I'm|we're|you're) (gone|out|here), while we're at it, since
  (we|there|you)('?re| are) …, spare time, time … unused, could we just, low-hanging,
  quick win, no harm in.*
- **2. GOAL owed-list re-surface.** A `_goal_owed_digest(root)` helper parses
  `cc/GOAL.md`'s `## Standing owed` bullets (the section pruned to fit the banner in
  the same session this pack was designed) and renders them as the anchor payload.
- **3. The forcing advisory.** On an opportunistic-scope match (gated), emit:
  *"[harness] This reads as opportunistic scope (a 'free resource' framing). Before
  proceeding, name which standing-owed item it serves — or, if it's a new thread,
  state its ROI against the #1 owed item. Current owed: {digest}."*

## Scope (out)

- **Blocking / denying.** G1 stays advisory (the `task_router`/`_reinject`
  frictionless contract). An opportunistic proposal can be excellent; the rule asks
  for the ROI, it does not veto. Deferred permanently by design, not cost.
- **Semantic "is this actually low-ROI?" judgment.** That's the LLM-judge path
  (design option B) the family rejected — interpretation relocated to a judge. G1
  only detects the *linguistic signature* + forces the human/Claude comparison.
- **Plan-scope divergence** (a *mechanical* drift signal) → TP-260.
- **Footgun-memory surfacing** → TP-261.

## Implementation

`task_router.py` already computes `_detect_decision_shape(...)` and composes it
additively into the UserPromptSubmit stdout ([task_router.py:256-260]). G1 adds a
sibling detector composed the same way.

**Fix 1 — the idiom tuple (near `_DECISION_SHAPE_PATTERNS`, ~line 71):**

```python
# Opportunistic-scope idioms: the "free resource -> might as well" framing that
# precedes scope drift. Distinct from _DECISION_SHAPE_PATTERNS (deliberative
# pivots): this class is the one the live detector MISSES (TP-259 grounded case).
_OPPORTUNISTIC_SCOPE_PATTERNS = (
    re.compile(r"\bworth\s+it\b", re.IGNORECASE),
    re.compile(r"\bmight\s+as\s+well\b", re.IGNORECASE),
    re.compile(r"\bwhile\s+(?:i'?m|we'?re|you'?re)\s+(?:gone|out|here|away)\b", re.IGNORECASE),
    re.compile(r"\bwhile\s+we'?re\s+at\s+it\b", re.IGNORECASE),
    re.compile(r"\b(?:spare|unused|otherwise\s+unused)\s+time\b", re.IGNORECASE),
    re.compile(r"\btime\s+that\s+(?:would\s+)?otherwise\b", re.IGNORECASE),
    re.compile(r"\blow[-\s]?hanging\b", re.IGNORECASE),
    re.compile(r"\bquick\s+win\b", re.IGNORECASE),
    re.compile(r"\bno\s+harm\s+in\b", re.IGNORECASE),
    re.compile(r"\bcould\s+we\s+just\b", re.IGNORECASE),
)
```

**Fix 2 — the owed-list parser (mirror `session_start._parse_core_flow`'s
section-walk shape; stdlib-only):**

```python
_GOAL_OWED_HEADING = "## Standing owed"

def _goal_owed_digest(root: Path, max_items: int = 4) -> str:
    """The GOAL's Standing-owed bullets, one line each, for the anchor payload.
    '' when cc/GOAL.md or the section is absent (rule then no-ops -> gate)."""
    try:
        text = (root / "cc" / "GOAL.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    out, in_section = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            if in_section:
                break
            in_section = line.strip() == _GOAL_OWED_HEADING
            continue
        if in_section and line.lstrip().startswith("- "):
            out.append(line.strip()[2:].strip())
    return " | ".join(out[:max_items])
```

**Fix 3 — the gated detector (sibling to `_detect_decision_shape`):**

```python
def _detect_opportunistic_scope(prompt: str, root: Path) -> str | None:
    """Fire on an opportunistic-scope idiom, gated on a non-empty GOAL owed list
    (the anti-wallpaper gate: no owed list -> nothing to anchor to -> silent)."""
    if not prompt or not any(p.search(prompt) for p in _OPPORTUNISTIC_SCOPE_PATTERNS):
        return None
    digest = _goal_owed_digest(root)
    if not digest:
        return None
    return (
        "[harness] Opportunistic-scope framing detected ('free resource'). Before "
        "proceeding, name which standing-owed item this serves — or, if it is a new "
        "thread, state its ROI against the #1 owed item.\n"
        f"  Current owed: {digest}"
    )
```

Compose it into the same stdout block `_detect_decision_shape` uses (additive; if
both fire, decision-shape first, then a blank line, then the goal-anchor — mirror the
existing ROUTING_GUIDANCE ordering). **Vendor mirror:** re-run
`python3 scripts/sync_vendor_cc.py` (task_router is mirrored at
`espalier/_vendor/cc/hooks/`).

## Affected symbols

### Added-paths
- `tools/cc/hooks/task_router.py` — `_OPPORTUNISTIC_SCOPE_PATTERNS`,
  `_goal_owed_digest`, `_detect_opportunistic_scope` (+ `espalier/_vendor/cc/hooks/`
  byte-parallel mirror).
- `tests/test_hooks.py` (or a new `tests/test_task_router_goal_anchor.py` matching
  the sibling test-naming) — must-fire / must-not-fire / grounded-case fixtures.

### Changed-semantics
- `tools/cc/hooks/task_router.py::_run_main` (or its advisory-composition point) —
  append the goal-anchor advisory to the UserPromptSubmit stdout, additively.

## Pass criteria

- **Grounded earn-the-red:** a fixture feeding the verbatim 2026-07-08 drift-onset
  prompt (*"maybe we could do this if it's worth it, considering there is time that
  otherwise would be unused?"*) to `task_router.main()` on stdin **emits the
  goal-anchor advisory** (RED before Fix 3 — it matches no live pattern today).
- **Must-not-fire:** a plain task prompt ("fix the typo in README") stays silent;
  an opportunistic idiom with an **empty** GOAL owed list stays silent (gate).
- **Drive `main()`, not the helper:** at least one fixture drives
  `task_router.main()` end-to-end (stdin → stdout advisory), not just
  `_detect_opportunistic_scope` directly (the false-green class, TP-258 MAJOR).
- **Owed digest is honest:** `_goal_owed_digest` returns the real `## Standing owed`
  bullets on the live `cc/GOAL.md`; '' on a tree with no GOAL.
- **Regression floor:** `pytest tests/test_hooks.py tests/test_hook_protocol.py -q`
  green; `ruff check .` clean; vendor mirror byte-parallel
  (`tests/test_vendor_cc_parity.py`); `espalier audit .` 0/0.

## Files touched

**New:** `task-packs/TP-259-*`; the test fixture file.
**Modified:** `tools/cc/hooks/task_router.py` + `espalier/_vendor/cc/hooks/task_router.py`
mirror.
**Unmodified on purpose:** `_reinject.py` (G1 rides task_router's own stdout, not the
reinject rail); `cc/GOAL.md` (read-only here); the existing `_DECISION_SHAPE_PATTERNS`
(G1 is additive — it does not retune the deliberative class).

## Sub-task ordering

1. **Idiom tuple + owed parser** (smallest concrete change; no behavior yet) →
   checkpoint: `_goal_owed_digest` unit test green on live GOAL.
2. **Gated detector + compose into stdout** → checkpoint: grounded must-fire fixture
   RED→GREEN through `main()`; must-not-fire fixtures green.
3. **Vendor-sync + verify + tag** → `sync_vendor_cc.py`; full hook suite + parity +
   ruff + audit.

## Estimated effort

Idiom tuple + parser 0.5h · detector + compose 0.75h · fixtures (grounded + gate +
drive-main) 1h · vendor-sync/verify/tag 0.5h. **Total ≈ 2.75h.** Lowest-risk of the
family.

## Landing
- State: DRAFT — execution-ready (no blocks)
- Commits:
- Suite:
- Earn-the-red: the grounded drift-onset prompt fires the anchor through
  `task_router.main()` (RED before Fix 3 — matches no live pattern); the empty-owed
  gate + plain-prompt near-misses stay silent (RED if the gate is dropped)
- Date:
