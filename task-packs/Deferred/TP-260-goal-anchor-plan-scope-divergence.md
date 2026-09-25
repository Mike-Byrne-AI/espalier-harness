# TP-260 — Goal-anchor: plan-scope divergence advisory (G2)

## Status

- **State: DRAFT — has ONE structural block (read [Block](#block--the-runtime-plan-carries-no-affected-set) first).**
  The mechanism is the purest of the family (zero LLM judgment) but the data it
  needs does not exist at runtime yet; a bounded schema addition resolves it.
- **Review verdict (2026-07-09, `wf_9d4d2eb4`): EXECUTE-AFTER-FIX — a SECOND,
  self-missed block.** Fix 3 pins `parse_affected_symbols` as "unmodified on
  purpose", but that function DISCARDS the path prefix of every `path::symbol`
  bullet (`pack_manifest.py:201` — the `rpartition("::")` drops the `_path`
  token), so even after Block-1's `affected_paths` schema addition G2 has NO
  reliable path source and would dogfood-false-fire on its own `execution_plan.py`
  edit. Reopen the Block: extend `parse_affected_symbols`/`AffectedSymbol` to
  retain the token-before-`::`, or add a dedicated path extractor, then populate
  `--affected` from it. Real work — parked (Deferred) post-launch.
- Version target: next minor
- Kind: PACK
- Type: feature (a mechanical drift-from-goal advisory) + a small
  `execution_plan` schema addition
- Change class: adds one PostToolUse advisory + an `affected_paths` field to the
  execution-plan JSON. Frictionless (advisory, never a deny).

## Motivation

Goal-anchor family — see the shared frame in
[TP-259](TP-259-goal-anchor-opportunistic-scope.md#motivation) (speed-bump not
billboard; force the comparison; inherit the anti-wallpaper gate).

**This pack (G2) is the *purest* trigger in the family: no idioms, no judgment, just
arithmetic.** When an execution plan is active, it declares an intended scope; an
`Edit`/`Write` that lands *outside* that scope is drift or deliberate creep — and
either way the plan should be updated or the write refocused. The plan **is** the
stated goal; the write **is** the mechanical evidence; divergence is set membership.

## Block — the runtime plan carries no Affected set

Grep-verified against HEAD before authoring (the TP-258 dead-wiring lesson):
`execution_plan.json` has keys `task / created / status / goal / not_doing / steps`,
and each step is `{index, description, status, note, timestamp}`
([execution_plan.py::cmd_create], verified on the live `cc/execution_plan.json`).
**There is no path/Affected field anywhere in the runtime plan.** The Affected-symbol
set lives only in the *pack markdown* (`## Affected symbols`), walked offline by
`/scope-check` (`pack_manifest.parse_affected_symbols`) — it never reaches the running
plan. So "is this write outside the plan's scope?" has **nothing to compare against**
at PostToolUse time.

This is G2's BLOCK 2 analogue. Resolution options (decide before building):

- **(a) Add an `affected_paths: list[str]` field to `execution_plan.py create`**,
  populated at plan-creation. For `/implement-pack`, populate it from the pack's
  `## Affected symbols` paths; for a hand-made `/implement-task` plan, accept an
  optional `--affected "src/,lib/"`. G2 then matches the written repo-relative path
  against those prefixes. **Bounded, honest, recommended.**
- **(b) Derive scope from step `description` prose** (fuzzy path-mention matching).
  Rejected: descriptions are prose, not paths — high false-rate, violates the
  "least interpretation" invariant.
- **(c) Ship G2 dormant** until a future plan-schema pack adds paths. Rejected:
  leaves the purest trigger unbuilt for no real saving over (a).

**Recommended: (a).** The rest of this pack assumes (a).

## Scope (in)

- **1. `affected_paths` on the plan schema.** `execution_plan.py create` gains an
  optional `--affected` (pipe- or comma-delimited repo-relative path prefixes),
  stored on the plan dict; absent → empty list → **G2 silent** (the gate: no declared
  scope, no divergence signal).
- **2. `/implement-pack` populates it** from the executing pack's `## Affected
  symbols` path set (the paths `parse_affected_symbols` already extracts).
- **3. The divergence advisory** (PostToolUse `Write|Edit`): when a plan is
  `in_progress` AND has a non-empty `affected_paths` AND the written path matches
  none of them (and is not a plan-exempt harness prefix), emit:
  *"[harness] This edit ({path}) is outside the active plan's declared scope
  ({affected_paths}). Intended scope expansion, or drift? Update the plan
  (`execution_plan.py add-affected`) or refocus."*

## Scope (out)

- **Denying the out-of-scope write.** Advisory only (family contract). Scope
  expansion is often correct; the rule surfaces it, doesn't block it.
- **Symbol-level granularity.** G2 matches *path prefixes*, not `path::symbol`. The
  pack's symbol-level Affected set is `/scope-check`'s offline job; a PostToolUse hook
  only sees the file path. Symbol-level runtime divergence is deferred (no clean
  mechanical signal at the hook).
- **Global reinject-cap re-think.** G2 adds one PostToolUse row to a rail whose
  session/per-turn caps are GLOBAL (shared with ORIENT + 7 sync rows + a future M1) —
  see the TP-258 "cap cannibalization" minor. Tracked there, not re-solved here;
  G2 notes its budget cost in Pass criteria.

## Implementation

**Fix 1 — `affected_paths` in `execution_plan.py::cmd_create`** (add the param +
store it; keep back-compat — absent means `[]`):

```python
def cmd_create(task, steps, goal="", not_doing="", affected=""):
    plan = {
        "task": task,
        "created": _now(),
        "status": "in_progress",
        "goal": goal,
        "not_doing": not_doing,
        "affected_paths": [p.strip().replace("\\", "/") for p in
                           re.split(r"[|,]", affected) if p.strip()],
        "steps": [ ... ],  # unchanged
    }
```

**Fix 2 — the reinject rule** in `_reinject.py` (a new PostToolUse `_render_*`
sibling of the existing sync rows; reads the plan via `root`, self-excludes the plan
file). Rendered advisory listed above. Registered as a `face="sync"` (or a new
`face="orientation"`) `ReinjectRule`, priority below the SoT-sync rows so a co-fire
drops G2 first (a divergence nudge is less urgent than a sister-site data loss).

**Fix 3 — `/implement-pack` populates `--affected`** from
`parse_affected_symbols(pack)` path set at plan creation.

**Self-host-gate fork (decide):** the PostToolUse reinject rail is gated to self-host
at the call site (`post_write_check` calls `check("PostToolUse", …)` only when
`is_self_host_repo`). Plan-scope divergence is a **generic** adopter value, not a
self-host internal — so G2 wants adopter reach. Either (i) move the divergence check
to a non-self-host-gated call point, or (ii) accept self-host-only for v1 and bank the
adopter-reach limitation. *Lean: (ii) for v1* (smaller blast radius; revisit with
telemetry), **banked as a Scope note, not silently shipped.**

## Affected symbols

### Changed-semantics
- `tools/cc/execution_plan.py::cmd_create` — add `affected_paths` (back-compat:
  absent → `[]`). New `add-affected` subcommand to append at runtime.
- `tools/cc/hooks/_reinject.py` — new `_render_plan_scope_divergence` + its
  `ReinjectRule`; registered in `REINJECTS` (+ vendor mirror).
- `.claude/commands/implement-pack.md` — populate `--affected` from the pack's
  Affected paths at plan creation.

### Added-paths
- `tests/test_reinject_plan_scope.py` — must-fire (write outside scope) / must-not-fire
  (write inside scope; no plan; empty `affected_paths`) fixtures.

## Pass criteria

- **Earn-the-red (drive the hook, not `check()`):** with an active plan whose
  `affected_paths=["espalier/"]`, a PostToolUse `Edit` to `tools/cc/hooks/foo.py`
  driven through `post_write_check.main()` emits the divergence advisory; an `Edit`
  to `espalier/bar.py` stays silent. Both RED-provable before the rule exists.
- **Gate:** no active plan → silent; plan with empty `affected_paths` → silent
  (the block-(a) default must not fire on every write).
- **Schema back-compat:** an existing plan JSON with no `affected_paths` key loads and
  G2 no-ops (no `KeyError`).
- **Cap accounting:** document that G2 consumes one shared reinject slot; a co-fire
  with an SoT-sync row drops G2 first (priority ordering asserted).
- **Regression floor:** `pytest tests/test_hooks.py tests/test_reinject*.py
  tests/test_execution_plan*.py -q` green; ruff clean; vendor parity; audit 0/0.

## Files touched

**New:** `task-packs/TP-260-*`; `tests/test_reinject_plan_scope.py`.
**Modified:** `tools/cc/execution_plan.py`, `tools/cc/hooks/_reinject.py`,
`.claude/commands/implement-pack.md` + `espalier/_vendor/cc/**` mirrors.
**Unmodified on purpose:** `_scope-check` / `pack_manifest.parse_affected_symbols`
(reused, not changed); the self-host call-site gate (untouched under lean (ii)).

## Sub-task ordering

0. **Resolve the Block:** confirm option (a) + the self-host-gate lean with the
   operator → checkpoint: decision recorded in the pack.
1. **`affected_paths` schema + `add-affected`** (smallest; pure data) → checkpoint:
   `execution_plan` unit tests incl. back-compat-load.
2. **The divergence reinject rule** → checkpoint: must-fire/​must-not-fire through
   `post_write_check.main()`.
3. **`/implement-pack` populate** → checkpoint: a real pack's Affected paths land in
   the plan JSON.
4. **Vendor-sync + verify + tag.**

## Estimated effort

Block/fork decision 0.25h · schema + `add-affected` 1h · reinject rule + fixtures
1.5h · implement-pack populate 0.75h · vendor-sync/verify/tag 0.5h. **Total ≈ 4h**
(assuming option (a) + lean (ii); +1h if adopter-reach (i) is chosen).

## Landing
- State: DRAFT — 1 block (no runtime Affected set; resolved by schema-addition
  option (a)) + 1 open fork (self-host gate; lean (ii)). Resolve both before execute.
- Commits:
- Suite:
- Earn-the-red: out-of-scope Edit fires through `post_write_check.main()`; in-scope
  Edit + no-plan + empty-paths near-misses stay silent (RED if the gate is dropped)
- Date:
