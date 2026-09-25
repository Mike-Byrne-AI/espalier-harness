---
name: reflect
description: Cross-artifact gap surfacing after a substantial implementation pass — looks across the files just changed for structural drift, missing connections, and inconsistencies the file-by-file review pass cannot see. Use when the user asks to reflect, after generating 3+ interconnected files, when the user senses something was missed, or before /handoff on significant sessions. Distinct from /review (single-file correctness lens) and /adversarial (failure-mode discovery). For non-trivial sessions, delegates the cross-artifact review to the code-reviewer agent for orthogonal context.
---

# Reflect — Engineered Context Consolidation

This skill deliberately recreates the cognitive effect observed when
tool-use limits force a continuation: all accumulated work becomes
input for parallel re-examination, enabling cross-artifact pattern
detection that's invisible during sequential generation.

**Do NOT use mid-file or mid-thought.** Finish the current unit of
work first. The value comes from reviewing completed artifacts, not
interrupting production.

## The Protocol

### Phase 1 — Force Context Reload

Re-read every file created or modified this session. Don't skim —
actually load the content. Content you generated is now content you're
reading, which activates different attention patterns.

```bash
# List recently changed files
git diff --name-only HEAD 2>/dev/null
git ls-files --others --exclude-standard 2>/dev/null
# Surface the last 5 reasoning entries from this session's blueprint
# (silently no-ops when there's no active blueprint yet).
python tools/cc/cognitive_blueprint.py show-recent --n 5 2>/dev/null || true
```

For each file: read it completely. Not "I know what's in there because
I wrote it" — actually re-process the content as input.

### Phase 2 — Cross-Artifact Scan

With all artifacts loaded simultaneously, look for:

**Structural gaps** — File A references something in File B that
doesn't exist. A command references a path that was never created.
An agent's role overlaps with another agent's. A schema defines fields
no writer produces. A document promises something the code doesn't
deliver.

**Emergent patterns** — Do three separately-built things share an
underlying structure that should be unified? Is an abstraction trying
to emerge from repeated patterns? Did an early decision get implicitly
contradicted later? Is a capability 80% built across several files but
never explicitly assembled?

**Missing connections** — Two systems that should reference each other
but don't. A data format produced in one place that could be consumed
in another. A pattern solved in one file but unsolved in another.
Insights from one area that change the design of another.

**Quality gradient** — Are early files lower quality than later files?
Inconsistencies in terminology, naming, or approach across files
written at different points in the session?

### Phase 3 — Report

```
REFLECTION
━━━━━━━━━━
Files reviewed: {N}

STRUCTURAL GAPS: {N found}
{For each: what's missing, where, severity}

EMERGENT PATTERNS: {N observed}
{For each: what's trying to emerge, how to actualize it}

MISSING CONNECTIONS: {N found}
{For each: what should connect to what, and why}

QUALITY GRADIENT: {assessment}
{Which early files need refresh? What changed in understanding?}

RECOMMENDED ACTIONS:
1. {highest-impact fix}
2. {second highest}
3. {third}

EMERGENT OPPORTUNITIES:
{Things that weren't in the original plan but are now possible/obvious
given what's been built. These are the highest-value finds.}

MEMORY CANDIDATES: {N | none}
{Durable insights worth promoting. For each: the candidate, its nearest
existing note (advisory), a proposed ship-tier (SHIP_ADOPTER →
docs/FAILURE_MODES.md / SELFHOST_DEV → memory/ / OPERATOR_PRIVATE → keep
local), and a disposition (promote-new / append-to-<note> / skip / hold). See
Memory Promotion below. "none" is the common, correct result.}
```

### Phase 4 — Act or Defer

- **Fix now** if it's a structural gap or broken reference (quick,
  prevents downstream issues).
- **Note for next pass** if it's an emergent opportunity (may need
  design discussion).
- **Add to docs/SHARP_EDGES.md** if it's a discovered footgun *this repo* trips
  on. That is this file's job and it is the right home — but note it is NOT a
  ship target; see the tier note below.
- **Promote a reusable insight** — run the candidate pass (see *Memory
  Promotion* below). Each candidate carries a proposed **ship-tier**: a
  `SHIP_ADOPTER` insight routes to **`docs/FAILURE_MODES.md`**, the one catalog
  deployed with its content and so reachable by adopters via `/recall`; a
  `SELFHOST_DEV` insight goes to the recall-indexed `memory/` folder (tracked,
  non-shipping); an `OPERATOR_PRIVATE` one stays local. The pass never writes
  without your approval, and never touches the hot `ESPALIER_MEMORY.md` index
  (that stays the Session-Log's job).

  **`docs/SHARP_EDGES.md` and `docs/CONVENTIONS.md` are not ship targets.** `init`
  seeds both from `assets/seed/` as near-empty **stubs** — *"refreshed on re-init
  only while it still matches the copy it was deployed from"* — so the host repo
  fills them with its own patterns. This repo's copies are contributor content an
  adopter never receives, and an adopter-relevant lesson written there reaches
  nobody. Put it in `FAILURE_MODES.md`.

After acting on fixes, run reflect again if more than 3 files were
modified — the second pass catches issues introduced by the fixes.

## Stacked Reflections

For large work (20+ files), a single pass may not be enough:

1. Reflect after initial generation → structural gaps
2. Fix gaps → may introduce new issues
3. Reflect again → second-order issues + emergent opportunities
4. Act on opportunities → adds capabilities
5. Reflect a third time → integration issues between old and new

Each layer operates on a richer context. Diminishing returns set in
after 3 passes; if structural gaps persist past then, the architecture
has a deeper problem that reflection won't solve — step back and
redesign.

## Why This Works

The intuition — a description of the observed effect, not a claim about
transformer internals: while generating sequentially, the model stays
focused on the work directly in front of it, so a contract set in File 1
that File 15 quietly violates is easy to miss. Re-reading every artifact
as one fresh input puts File 1 and File 15 on equal footing, which
surfaces the cross-file inconsistencies sequential generation glosses over.

The tool-use limit forces this transition accidentally. Reflect forces it
deliberately — and the `## Mechanical Backing` below is what actually
substantiates it.

## Mechanical Backing

The reflect operation has programmatic teeth: `tools/cc/reflect_protocol.py`
runs cross-reference matrix checks, orphan detection, and drift
analysis. The script does the mechanical part; this skill guides the
LLM-layer pattern recognition. Both run together when reflect is
invoked.

## Memory Promotion (`--candidates`)

Phase 4's "promote a reusable insight" step has mechanical teeth: a
candidate detector that surfaces durable insights from this session,
shows the nearest existing note, and proposes a **ship-tier** so an
adopter-relevant lesson routes to a SHIPPING docs catalog rather than the
non-shipping `memory/` folder by default. This is the PUSH side of the
recall engine (`/recall` is the pull side); without it, durable judgment
dies in Session-Log rows instead of reaching the surface that carries it
to its audience.

### Run the candidate pass

```bash
python tools/cc/reflect_protocol.py --candidates
```

It reads this session's blueprint reasoning entries (the same ones
Phase 1 surfaced), keeps only the eligible kinds — `decision`,
`pattern_discovered`, `alternative_rejected` — drops the auto-recorded
`[subagent:…]` activity logs, and for each remaining entry attaches the
nearest existing `memory/` note via the recall ranker. The mechanical
layer deliberately does NOT try to regex-classify "durable insight vs
terse status line" — that judgment is yours (a heuristic would
false-drop real insights that happen to quote a pack id or a test
count). So a terse "… executed, suite NNNN passed" entry will surface;
just mark it **skip**. Most sessions produce nothing durable; the
default output is `MEMORY CANDIDATES: none`, the correct common result.

The nearest note is **advisory context, not a verdict**: the recall
ranker finds the most topically-related note, which is not the same as
a duplicate — token overlap can't tell "shares vocabulary" from "states
the same insight". You make the call.

### Act on each candidate

For each surfaced candidate, decide one of:

- **promote** — route by the proposed ship-tier. `SHIP_ADOPTER`: draft a
  generalized entry into **`docs/FAILURE_MODES.md`** (the catalog that ships
  with its content), stripped of internal pack ids / self-host names /
  operator identity so it reads as adopter guidance. `SELFHOST_DEV`:
  draft a new `memory/<slug>.md` using the `memory/README.md` structure (H1
  = slug, `**Status:** active`, a `**Linked from:** ESPALIER_MEMORY.md row "<row>"`
  back-reference) and wire the reciprocal `[[slug]]` link into the
  Session-Log row.
- **update** — when the nearest note already covers the topic, propose
  an append to THAT note rather than a duplicate file.
- **skip** — not durable enough; leave it in the blueprint.
- **hold** — read, but not ready to decide this session. Log it as `held`
  (below) and the pass brings it back, labelled, on every later run until you
  decide. This is the only way a candidate outlives the session.

**Log every disposition you make.** Any of the three decisions (with the
candidate's `key`) SUPPRESSES that candidate from future passes, so you are not
re-asked about it every session — and that includes `promoted`. Logging is not optional
bookkeeping: a promotion you make but never log is re-proposed forever, and
the only two answers to a re-proposal are "skip it again", which inflates the
skip-rate that then advises your durability bar is too low, or "promote a
duplicate". The metric degrades as a function of successful promotions.

**Never auto-write.** Promotion proposes a draft; you approve. This
honors the standing "never record a memory without asking" rule.

### Anti-theater disposition log

Append one JSON line per disposition to
`.espalier/memory_candidate_log.jsonl` (gitignored):
`{session_ts, candidate, key, nearest_note, disposition}` where `session_ts` is
the moment you write the row, in ONE spelling -- ISO 8601, UTC, whole seconds,
`+00:00` -- produced by
`python -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'))"`
(the skip-rate window is the last twenty rows by THIS clock, not by file
position; the reader still parses the older spellings and the legacy `date`
key it inherited, but no new row is written in them), `disposition`
is one of `promoted`, `updated`, `skipped`, `held`, and `key` is the 12-char
`key:` the candidate pass PRINTS beside each candidate — copy it **verbatim**,
never hand-derive it (that re-opens the render->key footgun). The first three
are DECISIONS and are fed back into the pass: the same candidate is **not
re-proposed** on later runs (a `SUPPRESSED: N ...` line reports how many were
hidden); delete the row to let a dispositioned insight resurface. `held` is the
one that is not a decision: a candidate you have read but will not decide this
session. A held row suppresses nothing — the pass **re-proposes it from the
log** on every later run, labelled `[held since <session_ts>]`, until a
`promoted`/`updated`/`skipped` row with the same key lands. That is the ONLY
way a candidate outlives the session: the pass reads the blueprint lineage back
to a 60-minute gap and no further, so a key written into the Session-Log row
and called "logged" is gone by the next session, and the `/handoff` landing
check reds on a cited key that has no log row. A held row may also carry
`kind` (the candidate's printed kind); without it the label reads `[held]`.
An unrecognized `disposition` value suppresses nothing and is not held either
— the predicate is an enumeration, so a mistyped *decision* fails open (the
candidate comes back) while a mistyped *hold* (`hold`, `HOLD`) loses the
candidate, which is why the landing check reds on a cited key whose row the
pass cannot read. The
candidate pass PRINTS the skip-rate for you (all-time + last-20), so you no
longer eyeball it: `SKIP-RATE: 3/6 last-20 (50%), 3/6 all-time (50%)`. The rate
counts decisions only — `held` and unrecognized rows leave the denominator. A
high recent rate (>=60% trips an advisory hint) means the durability bar is too
low and the pass is drifting toward alert-fatigue — raise it. Still no
mechanical enforcement; the tightening is operator judgment. Re-evaluate after
~10 sessions.

## Orthogonal-Context Delegation

When the session crossed many files or the user explicitly wants an
external pass, dispatch the **code-reviewer** subagent (`subagent_type='code-reviewer'`)
after Phase 2 to do the cross-artifact scan in its own context. Brief
it on:

- The list of changed files (from `git diff --name-only HEAD`).
- The session's stated goal (so it can grade against intent).
- Specific worries the operator named (or the open Pending Issues
  list from the active task pack).

Fold the agent's findings into Phase 3's report. The agent's external
perspective catches what this conversation's own framing missed —
structurally analogous to the production-to-review transition the
skill engineers in the main thread.

## Reasoning Review (`--reasoning` mode)

Invoke as `/reflect --reasoning <pack-path>`.

Reasoning review audits the *generation process* of a pack — not
the pack's artifact-level content (that is the pack-artifact
review run at pack-execution step 0-A). It asks: was the thinking
that produced this pack sound?

The two gates are complementary:

- **Mechanical review (pack-artifact):** is the pack internally consistent?
- **Cognitive review (this mode):** is the thinking that produced
  the pack sound?

A pack can pass mechanical review and still fail cognitive review — internal consistency
does not imply the reasoning chain is valid.

### Dispatch flow

1. Read the pack file at `<pack-path>`.
2. The reasoning-review checklist (v1) is inlined in the prompt
   template in step 4 below — there is no separate file to read.
3. Identify a reasoning-review agent. **Default: opus-class
   general-purpose** instructed to take an external-context posture.
   Override: any agent type that did NOT participate in the pack's
   generation. For packs introducing hooks, gates, or governance
   contracts prefer the `failure-mode-reviewer` — its lens differs
   maximally from generation lenses.
4. Dispatch the chosen subagent by name (`subagent_type='<name>'`). Prompt template:

   > You are doing a reasoning review of a task pack. Read the pack
   > below and evaluate the THINKING that produced it against this
   > fixed checklist. For each checklist item, report severity
   > (PASS / GAP / BIAS / UNCHECKED) formatted as
   > `SEVERITY • CATEGORY • FINDING • EVIDENCE • SUGGESTED_ADDRESS`.
   >
   > Checklist (Reasoning review — fixed checklist, v1):
   >
   > <!-- reasoning-review-checklist: BEGIN generated region -- do not hand-edit. Regenerated by scripts/sync_checklist_regions.py, Espalier-Harness self-host tooling; an adopter repo has no scripts/ and never runs it. -->
   > For each item below, evaluate the pack's generation process and
   > report one of: PASS, GAP, BIAS, UNCHECKED.
   >
   > **1. Agent composition adequacy.**
   > What review angles did the generation pass? What angles are
   > conspicuously missing for this pack's domain?
   >
   > - Failure-mode-sensitive packs (hooks, gates, governance changes)
   >   MUST have had failure-mode-reviewer.
   > - Cross-module packs MUST have had architecture-analyst.
   > - OSS-surface packs MUST have had consumer-UX review (general-
   >   purpose simulating downstream).
   > - Net-new-subsystem packs MUST have had at least 3 angles.
   >
   > Report GAP if any required angle is missing.
   >
   > **2. Premise inheritance.**
   > List claims the pack imports from prior context (ESPALIER_MEMORY.md,
   > prior packs, the user's framing) and used without independent
   > verification.
   >
   > Each unchecked premise = UNCHECKED finding.
   >
   > **3. Synthesis validity.**
   > List the synthesis leaps the generation made. For each: is it
   > evidence-backed (concrete agent finding citations) or
   > pattern-matched (the shape feels familiar from training)?
   >
   > Pattern-matched synthesis = BIAS finding.
   >
   > **4. Scope-narrowing choices.**
   > What was implicitly excluded from consideration? Per scope-out
   > entry: is the reason given a substantive justification ("would
   > require X cost not warranted by Y benefit") or a default
   > ("seemed out of scope")?
   >
   > Default-scoped-out = GAP finding.
   >
   > **5. Counterfactual checks.**
   > For the pack's two or three central design choices: what would
   > the conclusion be if a key premise were inverted? Are there
   > premises whose negation would invert the conclusion?
   >
   > If no counterfactual was considered for a load-bearing choice =
   > UNCHECKED finding.
   >
   > **6. Diversity-of-context check.**
   > Did the generation use the same agent type multiple times, or
   > multiple agent types? Single-agent reasoning chains inherit
   > that agent's blind spots.
   >
   > Single-agent dominance = BIAS finding.
   >
   > **7. Alternative framings.**
   > Were 2+ design alternatives considered for major decisions, or
   > was one path treated as obvious?
   >
   > Single-path reasoning without alternatives weighed = GAP finding.
   > <!-- reasoning-review-checklist: END generated region -->
   >
   > --- PACK CONTENT ---
   > {{contents of <pack-path>}}

5. Parse the agent's response for GAP / BIAS / UNCHECKED / PASS
   severities and surface findings to the operator.

### Acting on findings

Reasoning review is **advisory, not blocking**. For each non-PASS
finding the operator picks one of three responses:

- **Address** — edit the pack to fix the reasoning gap (rewrite
  the scope-out justification, add the counterfactual analysis,
  broaden agent composition for the original generation).
- **Acknowledge** — add a `# reasoning-review: acknowledged
  <reason>` line in the pack so future readers see the conscious
  trade-off.
- **Defer** — note as a tracked follow-up; do not block on it.

Record the checklist version (v1) in the blueprint
reasoning entry so historical reviews are reproducible.

### When to invoke

Discipline, not mechanical enforcement:

- Pack `Status:` includes "security", "critical", or "architectural".
- Pack introduces a net-new subsystem (freshness-signal style).
- Pack's effort estimate exceeds 4 hours.
- Pack-artifact review is clean but stakes are high.
- User explicitly invokes `/reflect --reasoning`.

Reasoning review is more expensive (longer prompt, more cognitive
load on the reviewer) and finds different errors than mechanical
review. Use selectively, not on every pack.

### Anti-theater calibration

Reasoning review's known failure mode is **theater** — the agent
returns plausible-sounding inert findings that operators never act
on; the gate appears to function while providing zero real value.

Defense: track operator disposition per finding in
`.espalier/reasoning_review_log.jsonl` (gitignored, one JSON line
per session) with fields:
`{session_ts, pack, checklist_version, severity, category,
disposition}` where `disposition` is one of `addressed`,
`acknowledged`, `deferred`.

Aggregate: **acknowledge-rate** = `acknowledged / (addressed +
acknowledged + deferred)`. Threshold-based reassessment:

- **>70% acknowledge rate** — reasoning review is degrading toward
  theater. Suspect the checklist generates inert findings; revise
  to v2 or change agent-selection policy.
- **<30%** — gate is catching things operators rewrite for; sustain.
- **30-70%** — expected steady state; mix of real findings + noise.

No mechanical enforcement — operator judgment. Re-evaluate after
10+ packs have run through the gate.

### Bypass acknowledgment

Discipline-based gates have well-documented compliance decay.
Operators rationally skip advisory steps under deadline pressure.
This skill does NOT mechanically prevent bypass. The signal:
packs that *should* have a Bootstrap completion record footer
(security / critical / architectural / net-new-subsystem packs)
but don't are an observable indicator. If bypass rate exceeds the
acknowledge-rate threshold, a future iteration moves the gate
toward mechanical enforcement.

### Agent-diversity discipline

Diversity-of-context is the load-bearing property. Same-agent
self-review inherits the same blind spots — the agent that chose
to narrow scope to markdown-only fragments will likely not flag
that narrowing as a finding when reviewing its own output.

- If a pack was generated primarily by one model, do the reasoning
  review with a different-context agent.
- If a pack was generated through multi-agent synthesis, the
  reviewer should not have been one of the synthesizers.
- For packs introducing hooks, gates, or governance contracts,
  prefer the failure-mode-reviewer agent specifically.
