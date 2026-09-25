---
name: adversarial
description: Failure-mode discovery — the ways future-me forgets a step, an AI collaborator drifts, or a refactor misses a sister-site. Use when shipping a hook, gate, or governance change; before a release; when you want a pre-mortem before the implementation lands. Distinct from /review (per-file correctness) and /reflect (cross-artifact gap surfacing). Delegates to the failure-mode-reviewer agent.
---

# Adversarial — failure-mode-reviewer delegation

Failure-mode review is delegated to the **failure-mode-reviewer**
agent. The agent frames every change as "how does this quietly fail
in normal use?" — distinct from `/review`'s correctness lens.

The skill name `/adversarial` is retained for muscle memory. The
framing has shifted: Espalier-Harness is single-operator, so the relevant
failure modes come from future-you, AI-collaborator drift, hurried
sessions, and documented behaviors the code doesn't enforce. Not
hostile contributors.

## Step 1 — Frame the contract under review

Identify what the change is claiming and where the contract lives:

- What just changed? (diff or files in scope)
- What does the change promise (in docstrings, in `docs/`, in the
  pack spec, in the test names)?
- Is that promise enforced by code, or only by prose?

If the user didn't state the contract, ask. The failure-mode pass is
most useful when the claim being checked is on the table.

## Step 2 — Delegate to failure-mode-reviewer

Dispatch the **failure-mode-reviewer** subagent (`subagent_type='failure-mode-reviewer'`) with:

- The diff / files in scope.
- The stated contract (verbatim if possible).
- The documented failure classes the failure-mode-reviewer agent
  recognizes — these act as priors so the project doesn't
  re-discover the same edge cases.

The agent returns a structured list of failure modes with severity
labels:

- **REGRESSION** — existing documented behavior no longer enforced
- **GAP** — claim that lives only in prose; no mechanical enforcement
- **ROUGH-EDGE** — works but invites workaround or surprise

Each finding names the trigger sequence (operator action, AI pattern,
refactor shape) that produces the failure and proposes the smallest
mechanical fix.

## Step 3 — Triage

The agent ranks findings; you decide which to ship now and which to
file as follow-ups. A REGRESSION usually warrants a fix in the same
pack. A ROUGH-EDGE may be added to the project's failure log (if
one exists) as a documented failure class for institutional memory.

## Fan-out dataflow — the return contract

When a failure-mode pass fans out across many targets (every changed
file, every module, every hook), use the shared fan-out machinery in
the engine's `espalier.fan_out_findings` module instead of hand-rolling a one-off schema
and returning N verbose rationales into the window:

1. **Emit the shared finding shape.** Finders and refuters return
   `FINDING_SCHEMA` objects, not a bespoke per-pass schema — so findings
   aggregate, dedup, and validate for free (`aggregate_findings`).
2. **Refute, then persist survivors.** An adversarial verify culls each
   candidate; survivors persist to the round's report via
   `append_findings_to_corpus`, which is idempotent (re-running the pass
   does not double-write).
3. **Return ONLY the compact summary.** The window reads the
   `FindingsSummary` scalars (totals, survival rate, by-category) plus a
   survivors-slim list (id / title / severity / location) and the corpus
   path — never the full rationales, the refuted rows, or the clean rows.
   Drill into one finding by grepping the corpus, not by re-ingesting the
   whole batch.

This keeps a large fan-out cheap to read: a dozen scalars and the
survivors, instead of one regenerated rationale per target.
