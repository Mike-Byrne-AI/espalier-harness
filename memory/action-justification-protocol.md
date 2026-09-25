# Action-justification protocol

**Status:** active
**Linked from:** [CLAUDE.md "Core Rules"](../CLAUDE.md), TP-126 pack (`task-packs/Done/TP-126-action-justification-typed.md` after landing)

When the agent is about to perform a state-changing operation
(Write, Edit, NotebookEdit, destructive Bash), recording a typed
`action_justification` is the durable audit trail. The 4 prose fields:

- `goal` — what the agent is trying to accomplish
- `step_rationale` — why this specific operation advances the goal
- `expected_outcome` — what will be true after the tool returns
- `not_doing` — the counterfactual that was considered and skipped

Each is ≤500 chars (validator-enforced). Plus `tool` (closed set:
`Write|Edit|NotebookEdit|Bash|PowerShell|mcp__*`) + `content_hash`
(`sha256:<64-hex>`) + auto-populated `timestamp` + `session_id`.

## When to record

**Inside a plan step:** populate the step's `action_justification`
field at plan-creation time, or pass `--justification-fields k=v ...`
to `python tools/cc/execution_plan.py mark <i> running`. The planner
subprocesses to `cognitive_blueprint justify` and records the entry
on the active blueprint.

**Auto-compose at plan creation (TP-128).** Pass `--goal` and
`--not-doing` to `execution_plan create`. Every subsequent
`mark <i> running` then auto-composes the 6-field justification dict
from plan-level metadata + step description and records it via the
same subprocess. The composed `content_hash` is deterministic
(`sha256:<sha256(task|index|description)>`) and will not match
per-file mutation hashes — that's by design; the post_write trigger
surfaces per-file gaps as separate advisories. Precedence:
`--justification-fields` (explicit) > pre-populated
`step.action_justification` (rare) > auto-compose > existing
missing-justification advisory. Both `--goal` AND `--not-doing` are
required together for auto-compose to fire; passing only one falls
through to the advisory (prevents silently fabricating a default
for the missing field).

**Composed fields are clamped; typed ones are not.** The composed
`step_rationale` is the step *description* verbatim, and pack
conventions put files, proof and rollback in that one string — so
before clamping, the relationship was inverted: the more carefully a
step was written, the more certainly it overflowed the 500-char cap,
was refused, and left the step with no audit trail at all. The
composed path now truncates to the cap and stamps
`_AJ_TRUNCATION_MARKER` (` [...clamped]`) so a reader can tell a
short rationale from a cut one. Prose you typed yourself
(`--justification-fields`, a pre-populated step field) is **never**
clamped — silently truncating an operator's words is worse than
refusing them.

Two consequences worth knowing:

- `sha256(task|index|step_rationale)` does **not** reproduce the
  recorded `content_hash` for a clamped entry. The hash is over the
  raw description on purpose — it identifies the *step*, and
  re-keying it on truncated text would change a step's identity the
  moment its description grew past the cap.
- A blank composed field (a doubled pipe in `--steps`, a
  whitespace-only `--goal`) is a malformed **plan**, not a bad
  justification. It routes to the advisory, which names the real
  remedy, rather than to the refusal banner.
  Its sibling bites earlier and quieter: `create` splits on EVERY `|`, so a
  single pipe inside one step's own prose (a `constraints:` clause, a regex,
  a clobber operator) silently becomes two steps, and the plan's count is
  wrong before any justification is composed. There is no escape; keep the
  pipe out of the text.

**A refusal and an unavailable blueprint are different answers.**
`justify` exits **2** when the validator refuses the payload and
**3** when there was simply nowhere to write it. Only the first says
anything about the justification, so only the first drops it from the
step. This matters on the resume path: re-running `mark <i> running`
with no active blueprint used to delete a justification the validator
had already accepted and recorded — the plan then claimed *less* than
the blueprint, which is the same disagreement the write-after-validate
rule exists to prevent, merely inverted.

**For ad-hoc mutations outside a plan:** invoke
`python tools/cc/cognitive_blueprint.py justify --goal ... --step-rationale ... --expected-outcome ... --not-doing ... --tool Write --from-tool-input-file /tmp/proposed.txt`
*before* the mutation. The `post_write_check` hook fires an advisory
if no matching justification appears within 60s.

## What this is NOT

- **Not enforcement.** Both triggers (planner + post_write_check) are
  observational. The hook count stays at 10; no PreToolUse hook denies
  on a missing justification. Mandatory capture is a separate decision
  gated on observed signal value.
- **Not narrative.** The 4 fields are short (≤500 chars each).
  Validators reject empty or oversized strings — typed prose is
  refused outright, composed prose is clamped (above). Use
  `reasoning_entries[kind=decision]` for session-level narrative.
- **Not session priming.** Tool-call grain is not session-priming
  grain. The blueprint renderer, fragment filters, and
  `render_context_load` deliberately do NOT surface
  `action_justifications`.

## Why the 60-second window

Tight enough that stale justifications don't false-pass. Loose enough
to accommodate the agent invoking `justify` then `Write` sequentially.
The chosen value lives at
`tools/cc/hooks/post_write_check.py::_AJ_WINDOW_SECS`; tunable based
on empirical adoption.

## Storage shape

`CognitiveBlueprint.action_justifications: list[ActionJustification]`.
Typed dataclass with 8 fields (the 4 prose + 4 metadata listed above).
Distinct from `reasoning_entries` (session grain). Not rendered into
markdown / fragments / load output.

## Two rejected mechanisms (don't resurrect)

- **JSON-in-`description:`** under a fifth `kind="action_justification"`
  (rejected `New TP/TP-118`). Overloading a string field with a JSON
  blob breaks `_sanitize_for_priming`'s `_MAX_FRAGMENT_LEN=200`
  truncation and opts out of typed validation. Pinned by
  `TestNoJSONInDescription`.
- **PreToolUse capture hook** (rejected `New TP/TP-121`). Instruction-
  layer enforcement masquerading as mechanical: deny → agent appends
  stub → retry succeeds. Also bumps canonical hook count 10 → 11.
  Pinned by `TestHookCountUnchanged`.
