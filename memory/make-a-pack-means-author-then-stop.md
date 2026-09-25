# "Make a pack" means author the pack, then stop

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "'Make a pack' = author then STOP"

When the operator says **"make a task pack," author the pack document and STOP.**
Do not author-and-execute in the same turn.

In TP-254 the pack was written and then all 11 fixes plus the commit landed in
one turn — collapsing the very checkpoint the workflow exists to create.

## Why the gap is load-bearing

The task-pack workflow deliberately splits planning across multiple turns:

- **"Phase 0"** — the operator's term for the pre-execution self-review that the
  pack turn creates. It "almost always catches something for correction"; since
  it was added, fixes land much cleaner. Authoring-then-pausing forces real
  thought about the plan before any source is touched.
- It is the operator's window to **override or scope** before anything executes —
  which fixes, how to batch and commit, the design-fork calls. Executing in the
  same turn takes that away. In TP-254 scope calls that were the operator's
  (soften-vs-push-tags, one-commit batching) were made unilaterally and surfaced
  only *after* the commit.

**Landing clean is outcome bias.** It does not justify skipping the gate.

## How to apply

1. "Make a pack" → write `task-packs/TP-N-*.md`, present a short summary, and
   **stop**. Wait for the operator's Phase-0 review, override, or go-ahead.
2. Execute in a **separate turn**, and drive the **`/implement-pack` skill**
   rather than hand-executing. The skill runs the phased gates *and* does the
   pack lifecycle bookkeeping — including stamping `State: LANDED` and **moving
   the file to `task-packs/Done/`**. A landed pack left in the `task-packs/` root
   re-surfaces as pending next session and trips a smoke check. Hand-executing
   skips that move.

Related: [[fix-the-pack-and-proceed-on-a-pre-flight-defect]] (the execution-side
counterpart: once you *are* running, don't stop mid-run).
