# Fix the pack and proceed when the pre-flight gate finds a defect

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "Fix the pack and proceed on a 0-A defect"

When `/implement-pack`'s pre-flight 0-A `code-reviewer` gate surfaces a **pack
defect** — wrong prescribed-fix code, an under-scoped Files-touched list, a stale
claim, a mis-pointed test — the established response is **"fix the pack and
proceed."** Patch the pack document *and* execute in the same turn, surfacing
what changed. Do **not** hand the pack back and wait for re-ratification.

## Why

The 0-A gate is *supposed* to catch these. Catching one is **the system working**,
not a reason to halt.

Both observed instances earned the gate's keep:

- **TP-284** — a real source-misattribution bug in the prescribed fix, which
  hardcoded `cc/GOAL.md` into what was meant to be a section-generic flag.
- **TP-284b** — a stale `CHANGELOG [Unreleased]` claim plus a mis-pointed
  `test_init` exemplar.

In both, the operator wanted **momentum, not a checkpoint**.

## How to apply

Run the gates; fix the pack for any BLOCK or defect; narrate the fix
transparently; keep executing. Still **surface** the finding — do not silently
absorb it — so the operator can veto.

## Calibration (the honest bound)

Two instances, **both contained docs/packaging packs**. A genuinely high-risk
pack — a broad engine refactor, something security-adjacent — may still warrant a
pause before executing the patched version. Do not over-generalize two
low-blast-radius data points into a universal rule.

## Not to be confused with

[[make-a-pack-means-author-then-stop]] governs **authoring**: stop after
drafting. This entry governs **execution**: don't stop mid-run.
