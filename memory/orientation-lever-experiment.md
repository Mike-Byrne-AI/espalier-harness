# Orientation lever experiment

**Status:** experimental
**Linked from:** (unlinked — wire `[[orientation-lever-experiment]]` into the next Session-Log row at /handoff)

**This is a hypothesis register, NOT a finding. Do NOT credit any lever until
the tests below separate the confounds.** One session (2026-06-30) compacted
near 1M tokens and the post-compaction pickup was — per the operator's
cross-harness read across many harnesses (bespoke + Espalier at various
stages) — the most seamless seen. Tempting to credit the TP-240 compact
orientation. But the cause is confounded three ways and N=1.

## The three entangled confounds
1. **VOLUME** — first session ever near 1M tokens, so the CC summarizer had
   unusually much to compress. **Cost-AMPLIFIER**: even if true, useless — we
   can't afford 1M/session.
2. **META-AWARENESS** — the session was *about* orientation/handoff/summary
   design, so (a) the model reasoned toward good handoffs all session, and/or
   (b) it engaged the `_ORIENTATION_COMPACT` "reason over the summary"
   instruction harder. **Cost-SAVER**: cheap, harvestable.
3. **BREADCRUMBS** — the session produced unusually structured handoff
   artifacts (GOAL Notes, blueprint entries, 9-section working summary), so the
   raw material the summarizer compressed was unusually well-shaped for
   orientation. **Cost-SAVER**: cheap, harvestable.

## Test order — by USEFULNESS, not by likelihood (operator frame)
We want a cheap, reusable lever, not an expensive one.
1. Test META and BREADCRUMBS first, **at NORMAL context size** (the operator's
   harness fleet is the rig).
2. **A positive on either at normal size simultaneously rules out
   VOLUME-necessity** — a seamless pickup at small context proves 1M wasn't
   required. So the expensive 1M test is likely **NEVER run**; it is reached
   ONLY if both cheap levers fail at normal size.
3. Only then → test VOLUME last to confirm/deny. If it's the driver, it's a
   cost-amplifier we shelve.

## Reframe: usable lever, not "the cause"
The levers need not be mutually exclusive (the outlier may be additive). The
useful question is **"does pulling lever X cheaply improve pickup?"** — not
"was X THE cause." Success = a cheap lever that reliably helps, not a full
explanation of one outlier session.

## Pre-registered metric (distrust the qualitative "seamless")
"Seamless" is the operator's self-report — distrust it
([[premise-check-before-authoring-a-fix]]; distrust-self-report). Pre-register;
don't move goalposts. Objective proxies scored on the FIRST post-compact turn:
- corrections the operator had to issue (count),
- re-asked an already-settled question (y/n),
- re-litigated a settled decision (y/n),
- turns-to-first-productive-action.
Nondeterministic → run N per condition, report the SPREAD, not one good run.

## No-regret build
The compression redesign (writers META-AWARE they write for reinjection,
inverted-pyramid for the next Claude) IS the harvest mechanism for the
meta-awareness lever IF that's the real one. So build it regardless: it
improves compression AND captures meta-awareness if that's the cause. **Build ≠
credit** — keep checking. Same family of bets (and same UNMEASURED-magnitude
caution) as [[orientation-self-generated-priming]].

## Measured result (2026-07-01) — cheap levers DISCONFIRMED at normal scale (double null)

Ran the cheap-lever half as a **cold-subagent A/B proxy** (a spawned agent = a
genuine no-memory pickup — a real post-compaction analog at normal context).
Two rounds; pre-registered metric = settled-state reconstruction accuracy,
blind-judged vs a fixed key; spread reported.

- **v1** (5 clean facts, NO compression): 2×2 structure×orient, N=8/arm →
  **total ceiling, 5/5 every arm, both effects 0.00, 0% re-litigation.**
  Instrument too easy — it stripped the compression/volume that makes real
  pickup hard, so there was no headroom to detect a lever.
- **v2** (headroom: ~650-word noisy transcript with **3 reversed-decision
  traps** → compressed to ≤110 words → cold pickup on an 8-field quiz incl. a
  0–3 trap sub-score), N=6/arm → **near-ceiling again.** STYLE (inverted-pyramid
  handoff vs naive summarize): composite **+0.08**, **trap +0.00**. META (pickup
  orient instruction): composite **+0.08**, trap **+0.00**. Even *naive*
  summaries preserved all 3 reversals (trap **3/3 in 12/12**). Re-litigation of
  settled items: **0% across all 56 samples, both rounds.** (Judge verified
  discriminating — it marked one non-trap field wrong, so the ceiling is real
  correct answers, not rubber-stamping.)

**Bounded conclusion:** for a capable (Opus-class) model doing single-shot
summarize→pickup of a moderate session, neither BREADCRUMBS (summary structure)
nor META (orient instruction) produces a detectable orientation-accuracy gain —
the model reconstructs the settled state near-perfectly from even a naive
summary, and does not re-litigate. Per this register's own decision tree, a null
on the cheap levers at normal size means they don't explain the seamless-1M
outlier → the residual candidate is **VOLUME**, the cost-amplifier we shelve
regardless. **Net: no cheap harvestable lever found.**

**Does NOT test:** the genuine near-1M compaction regime (can't feasibly run
controlled 1M compactions with scoring), nor weaker reader models (levers may
bite for Haiku-class — but the harness runs on capable models, so this null is
the deployment-relevant result).

**Product implication:** justify the priming / inverted-pyramid-summary work on
**cheapness + human-readability**, NOT on a measured model-pickup gain. The
no-regret build stays (cheap; helps humans read handoffs) but must not be
credited with pickup gains at normal scale, and elaborate breadcrumb machinery
should not be built expecting orientation gains. **Build ≠ credit — and here the
measurement says don't credit (at this scale).** Retroactively consistent with
scrapping TP-237 (pushing *more* structured context wouldn't have moved pickup).
