# Workflow schema catalog — task-authored fan-out schemas

**Status:** active
**Linked from:** (unlinked) — standalone reference; see [[fan-out-finding-schema]] for the canonical wire format this catalog sits beside.

A running record of the **structured-output schemas we author per task** when
running a Workflow fan-out. A `Workflow` `agent()` call returns **prose by
default**; a schema is opt-in — you pass a JSON-Schema `dict`/object as the
`schema:` option and the subagent is forced into StructuredOutput (validated,
retried on mismatch). Each schema we write for a specific review lens is a
**compressed design decision** — "here is the exact shape of a *useful result*
for this kind of question" — cheap to lose, annoying to re-derive. This catalog
keeps the effective ones.

## What this is NOT — the canonical schema lives in code

This is **not** the canonical fan-out wire format. That is `FINDING_SCHEMA` in
[`espalier/fan_out_findings.py`](../espalier/fan_out_findings.py) — the single
source of truth for a correctness/release-gate finding (severity
`blocker|major|minor|nit`, `blocks_release` bool), importable and usable
directly, with aggregation + corpus persistence built around it. See
[[fan-out-finding-schema]].

This catalog holds the **lens variants and one-off task schemas** that diverge
from the canonical shape because the *question* diverges — e.g. an
adopter-friction review needs a *bounce-probability* axis, which
`blocks_release` cannot express. They are records of craft, not supported
machinery.

## Anti-drift note (why embedding the literal here is OK)

`fan-out-finding-schema.md` deliberately does **not** re-embed the
`FINDING_SCHEMA` literal — a second copy of a *live code constant* is a drift
hazard. That rule is about two copies of one SoT. The schemas below have **no
code SoT** (they were authored inline in a one-shot workflow script that no
longer runs), so the catalog entry is their *only* copy — nothing to drift
from. The catalog IS the record.

**Graduation path:** if a schema here gets reused across workflows, promote it
to a named constant in `espalier/fan_out_findings.py` (or a sibling module),
and replace its catalog entry with a one-line pointer to the constant — at that
point it has a code SoT and the anti-drift rule reattaches.

## How to add an entry

When a fan-out schema earns its keep, append a `## Entry N` with: the **lens**
it embodies, **when to use** it, the **schema literal(s)** copy-ready, its
**provenance** (which workflow run / pack), and **what made it effective** +
any known weakness for the next author.

---

## Entry 1 — Adopter-bounce review (findings + verdict)

**Lens:** OSS-adopter friction / *bounce-probability*, not correctness. Finders
are seated as adopter *moments* (skim → install → first-action → friction →
skeptic → escape-hatch → docs), and severity answers *"would a real person give
up or dismiss the tool here?"* rather than *"is this a bug?"* Deliberately
diverges from `FINDING_SCHEMA`: a `BOUNCE|FRICTION|POLISH` enum + a
`reachability` axis replace `severity`/`blocks_release`, because abandonment
risk — not release-gating — is the thing being measured.

**When to use:** first-hour/first-impression reviews weighted to the adopter
experience — pre-launch "it just works" audits, onboarding-friction sweeps.
Pair with a default-**downgrade** refuter (below): friction findings over-index
on severity, so the refute pass is what separates a real bounce from reviewer
taste.

**Finder schema** (`agent(prompt, {schema: FINDINGS_WRAPPER})`):

```js
const FINDING = {
  type: 'object', additionalProperties: false,
  required: ['lane','title','what_adopter_sees','bounce_trigger','severity','reachability','evidence','fix_sketch'],
  properties: {
    lane:              { type: 'string' },
    title:             { type: 'string', description: 'short headline' },
    what_adopter_sees: { type: 'string', description: 'the concrete friction, in adopter terms' },
    bounce_trigger:    { type: 'string', description: 'why a real person gives up or dismisses' },
    severity:          { type: 'string', enum: ['BOUNCE','FRICTION','POLISH'] },
    reachability:      { type: 'string', enum: ['first-5-min','first-hour','rare'] },
    evidence:          { type: 'string', description: 'file:line read OR command run + its real output' },
    fix_sketch:        { type: 'string' },
  },
}
const FINDINGS_WRAPPER = {
  type: 'object', additionalProperties: false, required: ['findings'],
  properties: { findings: { type: 'array', items: FINDING } },
}
```

**Refuter schema** (`agent(refutePrompt, {schema: VERDICT})`, default-downgrade):

```js
const VERDICT = {
  type: 'object', additionalProperties: false,
  required: ['verdict','adjusted_severity','reasoning'],
  properties: {
    // the four failure modes of a friction claim; the last three all downgrade
    verdict:           { type: 'string', enum: ['real_bounce','overblown','not_reachable','our_taste_not_theirs'] },
    adjusted_severity: { type: 'string', enum: ['BOUNCE','FRICTION','POLISH','INVALID'] },
    reasoning:         { type: 'string' },
  },
}
```

The synthesis stage used a third one-off schema (`headline` +
`it_just_works_verdict` enum + `ranked[]` + `themes[]` + `uncovered`) to force a
ranked punch list; it is task-specific and not reproduced here.

**Provenance:** workflow `wf_5468c1d6-a45` (`oss-adopter-bounce-review`),
2026-07-09/10. 8 finder lanes → per-finding adversarial refute → synth. Fed the
day-one adopter-friction pack (TP-264). It was a **default fan-out** (generic
workflow subagents, this bespoke schema), NOT the espalier `fanout-audit`
machinery — deliberately, since the adopter lens wants naive outside-in eyes,
not repo specialists who can't un-know the codebase.

**What made it effective:**
- The `BOUNCE|FRICTION|POLISH` enum + `reachability` gave the refuter two
  independent downgrade axes (is it severe? is it reachable?), which is what let
  it correctly cull 18/19 finder-inflated severities without discarding the
  underlying observations.
- The four-way `verdict` enum names the *distinct* ways a friction claim fails
  (`overblown` / `not_reachable` / `our_taste_not_theirs`), so the refuter had to
  pick a mechanism rather than a vibe — the reasoning came back substantive.

**Known weakness (fix in the next variant):** the workflow did **not** persist
survivors to a corpus or dedup against the shared findings corpus of the time
(retired 2026-09-21; dedup against `task-packs/FORWARD_LEDGER.md` now) — so the
findings live only in the run journal + TP-264, invisible to future dedup. A
reusable adopter-friction variant should add the two-hop persist bridge (see
`_fanout_audit.js`) with a bounce-severity sibling field, so friction findings
converge across rounds the way correctness findings do.
