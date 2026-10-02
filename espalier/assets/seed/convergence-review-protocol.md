# Convergence review protocol

**Status:** active
**Read with:** `memory/CONVERGENCE_LEDGER.md` (the ledger the convergence-critic appends to)

A repeatable, multi-agent review for hardening a codebase too large for any
single pass — human or model. This file is your copy of the method: it states
the shape, not anyone else's results, so adapt the dimensions and the stopping
rule to your own repo. It pairs with the fan-out finding schema
(`FINDING_SCHEMA` in `espalier.fan_out_findings`) — the wire format — and the
`fanout-audit` scaffold, the generic engine.

## What it is

A **fan-out** of finder agents, each pointed at a *different* slice of the
surface, each returning `FINDING_SCHEMA` objects; **adversarial refuters** cull
them (default-refuted, oracle-confirmed); **survivors persist** to a dedup
corpus; and only a **compact summary** returns to the main window (the two-hop
anti-bloat dataflow — verbose rationales never reach the orchestrator chat). The
machinery lives in `espalier.fan_out_findings` (`FINDING_SCHEMA` +
`aggregate_findings` + `append_findings_to_corpus`); the cross-round dedup
source is your repository's forward ledger (`task-packs/FORWARD_LEDGER.md`,
which `init` seeds: its live rows plus its do-not-rediscover entries), or your
issue tracker where you keep the work there instead.

## When to run it

- Pre-release hardening (the canonical use — repeated rounds before a cut).
- After a substantial sprint, before declaring it done.
- Periodically, to keep the "nothing new" signal fresh as the code evolves.

## How to design the finder dimensions

- **Weight to the LEAST-attacked surface.** Track which areas the corpus already
  covers; point new finders at the gaps, not the well-trodden ground. Each round
  should explore a *different* slice — that independence is what makes the result
  compound (see "How to read the result").
- One dimension per distinct surface or lens; include a **completeness critic**
  that maps what the other finders did *not* cover (→ the next round's targets).
- Read every finder through your **governing frame** — write it down before the
  pass and hand it to every agent. Espalier's own frame, as an example of the
  shape: a workflow toolbelt, not a security boundary; the threat model is
  operator/AI *mistakes*, not malice; friction and false positives are the
  high-severity class, not un-closed bypasses. Yours will differ; an unstated
  frame means each agent invents its own.
- Each finder must: **dedup** against the corpus before emitting; **earn-the-red**
  with an oracle (run something — grep/git/build/parse — never cite from memory);
  and treat an **empty findings array as the honest, expected result** for mature
  code.

## How to refute

- **Default to refuted.** A finding survives only on an oracle-confirmed
  reproduction against HEAD; re-judge `blocks_release` through the governing frame
  (downgrade theoretical edges; keep real first-run/install/CI/doc defects).
- **Refuter output fields MUST be a subset of `FINDING_SCHEMA`.** The verdict is
  merged into the finding (`{...f, ...v}`) and the schema is
  `additionalProperties: false`, so any refute-only field that is *not* a schema
  property marks **every** finding invalid (`valid: 0`) even though survivors
  persist fine. There is no `corrected_severity` — re-judge via `blocks_release`
  (+ `corrected_confidence`).
- **Classify the surface BEFORE the refute lane, not after.** A refuter cannot
  catch a classification error that is upstream of it, because finder and refuter
  share the premise *"this surface asserts NOW"*. A **record** surface — a dated
  log, a changelog, an append-only register — is *supposed* to age; a stale
  pointer on one is expected, and editing it falsifies the record. Point a refute
  prompt at *"a count updated in one place and left stale in another"* or *"a doc
  edited but its mirror twin not"* and a diligent agent finds exactly that on a
  record surface, accurately, and is confidently wrong. More adversarial passes
  then buy more precise measurements of the wrong thing. Carry surface-class as a
  per-finding field the finder must fill, so the refuter inherits a premise it can
  attack; a lens applied afterwards arrives too late. Watch for the granularity
  trap too: a path-keyed record registry cannot express a file that is claim and
  record in one.

- **When the pass sorts findings into tiers, attack BOTH directions or say you
  did not.** A refute lane pointed at one tier measures only the error that tier
  can make. Run a lane that tries to *demote* the rows in your blocking tier and
  you will overturn some of them, which reads as rigour and is. But if nothing
  ran the other way — nothing challenged the rows below the line for *promotion* —
  the pass can only ever shrink the number it reports, and it shrinks it in the
  flattering direction. Price the untested side before you trust the readout:
  take your demotion overturn rate, discount it (a fifth is a defensible guess),
  apply it to the count of rows you never challenged, and compare the product
  with your reported blocking set. If that product is a material fraction of it,
  the tiering is unproven. A high overturn rate is evidence the lane WORKS, never
  evidence the tiering is right. Either run the promotion lane too, or state the
  untested direction and its expected magnitude in the readout so the reader can
  price it.

  ⚠ **The tiering rule itself can bias one direction.** A rule such as *"name a
  concrete symptom a stranger experiences"* cannot be satisfied by an invisible
  failure, by construction — so every fail-open defect gets pushed down a tier
  unless a reviewer happens to reach for a coverage argument instead, and two
  findings of one shape can land in opposite tiers on exactly that difference.
  When a rule cannot be met by a whole class of defect, it is not a filter, it is
  a blind spot with a rationale. Read your own tier rules for that shape before
  the pass, not after it.

## How to read the result (the part that is easy to get wrong)

The findings are only half the value; the **trend across rounds** is the other
half, and it is where the method is most often misread.

- **Track BLOCKER / major yield + the severity trend, NOT the raw finding count.**
  The count never reaches zero — each round re-points at a new corner, so there is
  always *something* ("the drill moved, not the well is dry"). Raw count is a false
  convergence signal.
- **Zero blockers + decaying majors across two or three INDEPENDENT rounds = the
  high-severity classes are exhausted.** That is good news and a strong signal. What
  it licenses depends on the mode — see **When to stop** below. It is not, on its
  own, a reason to run another round.
- **The accumulating "nothing new" across independent passes IS the correctness
  signal** — like research, a result you cannot break across many independent
  attempts. A null result is a real deliverable, not a wasted pass; N *independent*
  nulls compound into confidence the way replications do.
- **When the static rounds mature, ADD a modality they cannot reach** (a dynamic
  end-to-end run: a real install on a clean machine → a real pull request → a real
  session → a platform you do not develop on) — *additive*, not a replacement. Keep
  making rounds, but make each one **independent and differently-angled**; identical
  repeats add little, independent ones compound. In **hardening** mode the cost
  discipline is "spend on a NEW angle" rather than repeating an old one. In
  **release** mode it is "stop checking and go ship" — see **When to stop**.

### When to stop

This instrument has no natural terminator: every round re-points at a new
least-attacked corner, so it will return findings for as long as it is run. That is
by design and it is why the stopping rule has to come from outside the instrument.

**Two modes, and naming which one you are in is the whole discipline.**

- **Hardening** (no release in flight). Everything above applies. Nulls compound,
  a new angle beats a repeat, and "exhausted" means go find a modality these rounds
  cannot reach.
- **Release** (a version is being cut, or a day-one defect list is open). The
  exhaustion signal means **stop the instrument and go ship.** A round that returns
  only latent findings has told you the release is not blocked; running another to
  see whether a *different* corner also returns latent findings buys nothing a user
  will ever feel. Findings are ledgered unread and the review resumes after the cut.

**In release mode the gate is a driven walk, not a review.** *"Did a review
find something?"* is not a release criterion — it is always yes. *"Does a stranger
succeed on a clean machine?"* is. Build the artefact, install it into a fresh
environment, drive it on a fresh repo, and watch where a newcomer stalls.

**Severity is measured in user-facing terms.** Name the user who gets hurt and
what they were doing, or it is not a defect yet — it is a ledger row. A finding no
user can reach is not a BLOCKER however sound the mechanism behind it. **Read the
BLOCKER-yield trend on findings that name a user**, or the trend measures the
instrument's reach rather than the product's health.

**The failure this closes.** Repeated rounds against one artefact, every finding
real, not one of them ever acted on, no source changed — while verified day-one
defects sat open. The rounds were correct and the mode was wrong. A protocol that
only ever says *"not a reason to stop"* and *"spend on a NEW angle"* is an
instruction toward exactly that outcome; the mode rule above is the correction.

- **Adversarially self-check a "we've converged" claim** with a small agent panel
  (a theater-prosecutor vs a value-defender, both grounded in the corpus). Putting
  the *conclusion* through the same scrutiny as a finding is how it earns trust.

## Honest limits

- **Earn-the-red has a platform ceiling.** A version/OS-gated bug cannot go red on
  a host that already has the safe default (a runtime whose older releases carried
  the bug, probed on a newer one that does not). Ship the version-agnostic fix + a
  contract-lock test and label the target-version magnitude *unverified-on-host* —
  do not stamp it "verified." This is one reason the dynamic cross-platform /
  old-runtime pass matters.
- **A fan-out finding is a CLAIM until grep-verified vs HEAD** — even an
  "adversarially verified" one. Re-confirm load-bearing findings yourself.
- **A round is frontier-model-scale.** Proportion the finder count to the ask, and
  `log()` any coverage the round bounded (top-N, no-retry) so silent truncation does
  not read as "covered everything."

## Tooling

**What a run costs, and when you are asked.** Each scaffold spends dozens of agents a run and
needs dynamic workflows on (paid plans). Whether Claude Code asks before the run depends on
the permission mode: manual and accept-edits ask every run unless "don't ask again" was chosen
for that workflow in that project; auto mode asks on the first launch only; bypass permissions
and headless runs (`claude -p`, the Agent SDK) never ask. A `Workflow(<name>)` allow rule
pre-approves one saved workflow by name; the harness writes none, so the first run of each
scaffold asks.

- **Engine / schema:** `espalier.fan_out_findings` and its `FINDING_SCHEMA` (the
  fan-out finding schema).
- **Generic scaffold:** `.claude/workflows/_fanout_audit.js` (finders → refute →
  persist, with the two-hop bridge). There is no `fanout-audit` skill: the scaffold
  is run through the Workflow tool.
- **Scope-breaker-complete scaffold (start here for a full round):**
  `.claude/workflows/_convergence_review_template.js` — the successor to
  `_fanout_audit.js` with all four scope-breakers + the convergence-critic pre-wired
  (see the "Scope-breakers (mandatory floor)" section below). Copy it and swap `DIMENSIONS`.
- **Launch a scaffold by path, and name the model.** The `/<name>` registry serves the
  copy Claude Code read at session start: a scaffold edited mid-session and launched by
  name runs the pre-edit file, so its agents take no model override and inherit the
  session's model. `Workflow({scriptPath: ".claude/workflows/_convergence_review_template.js", args})`
  reads the file on disk. Every scaffold routes `args.model` to every `agent()` call;
  pass it on every launch, because the agents inherit the session model otherwise.
  `args.smoke: true` bounds the open-ended lanes so a wiring check stays under ten
  agents; without it the corpus-blind lane reviews your repository for real.
- **Dedup source:** your repository's forward ledger or issue tracker — whichever
  one you keep. Keep each round's own report wherever you keep analysis output.
- **Per-run ledger:** the file the persist step writes under `cc/`
  (`espalier.finding_ledger`) — one run-boundaried JSON record per fan-out (scalars
  + raw survivors); the structured substrate the convergence-critic reads for
  yield/recurrence (`read_ledger`).
- **Cross-round ledger:** `memory/CONVERGENCE_LEDGER.md` — one curated row per review
  round (coverage map, open leads, convergence read); appended by the convergence-critic.
- **Blocker re-verification:** when a pass claims a release blocker, the blocker
  is verified by **re-executing its repro** via `espalier.red_team_guard` (an
  independent oracle re-runs `{argv, expect=fail, match}` and a specific
  non-catch-all signature must appear), NOT by the finder's assertion. Gate on
  process + reproducibility, never on finding-count — an honest null PASSES. Record
  the repro as an artefact the gate can re-run, and never gate on a count; the
  failure classes behind both rules are in `docs/FAILURE_MODES.md` (§11.12 and
  §13.10). This is the mechanical form of "read by BLOCKER-yield, not count".

## Scope-breakers (mandatory floor)

Iterated scoped review converges to silence BY CONSTRUCTION: each round scopes off the
prior one, so the blind spot is the *intersection of every lens's exclusions*, and the
dedup corpus inherits prior framing — the microscope zooms in until broadly-visible
problems fall outside every lens. Two structural blind spots compound the more the method
is used: **spatial** (the never-pointed-at region every round assumed was caught earlier)
and **temporal** ("was good ≠ is good" — a static HEAD snapshot cannot see a supplanted
system's DELTA: a commit adds the new path, wires it, and leaves the old one still
reachable; static reachability sees both as live). Nobody holds a live codebase's full
ripple-map, so ripple-detection must be **mechanized**, not left to anyone's vigilance or
an agent's memory. Do not read a late-round null as "clean" unless a corpus-blind,
scope-blind pass produced it. Every convergence review MUST include these four
scope-breakers:

1. **Penumbra pass** (spatial) — after finders, hunt the ring just outside each lens:
   per-finding sister-sites / callers, and each lane's structural exclusions.
2. **Actionable critic** (meta) — the completeness critic's named gaps become a SECOND
   finder wave in the SAME run, not just a report the orchestrator reads.
3. **Corpus-blind parallel deep-dive** (temporal) — one or two agents (three to five for a
   pre-launch sweep) with NO scope / NO corpus / NO "already-known" list, run PARALLEL to
   the scoped lanes, allowed to re-find "known-good" things.
4. **Recent-change delta attacker** (temporal) — from `git diff` / recent commits, hunt
   sister-sites / contracts / docs the change TOUCHED but did NOT update. Derives the
   ripple from the diff instead of asking anyone to predict it. It is the rule that a
   class-fix is scoped to every shipped surface, run as a review stage.

**Default floor** = (1) + (2) + one of (3); (4) fires on any uncommitted/recent work;
full (3) is reserved for the pre-launch "this is it" sweep. The convergence-critic
(below) is the mandatory FINAL stage.

**Classification guard — deferred-intentional ≠ abandoned.** Any finder flagging a
half-finished / abandoned / supplanted / orphaned item MUST cross-reference your forward
ledger (its deferred and drafted entries) and in-code dormant notes before scoring it a
defect. A documented deferral (a ledger entry, or a "planned / dormant / not-yet-built"
docstring) is a KEEP, not rot. The refute stage rejects any "dead / half-finished" finding
whose subject is a ledger-documented deferral. Without this check a round will eventually
score a documented deferral as a half-finished build.

### The convergence-critic (mandatory final stage)

Iterated review has no cross-round sight by default: the yield trend, premature
"converged" calls, findings refuted in one round and confirmed in a later one, and
slow-drip *classes* (N isolated per-round nits of one shape) are visible only with the
whole series in view — and an agent otherwise reconstructs them from memory each time, the
exact unreliable self-report the epistemic rules warn against. The convergence-critic
mechanizes that view. It is **stateless**, runs LAST in every review, and its state is
the durable ledger. Inputs: the convergence ledger (`memory/CONVERGENCE_LEDGER.md`, prior
rows) + the structured per-run finding ledger (what the persist step writes under `cc/`,
read via `espalier.finding_ledger.read_ledger` — the machine substrate for
yield/recurrence, so those parts are *computed*, not recalled) + this round's
finder/critic output. Steps:

1. **Yield trend** vs prior rows — is blocker/major yield actually declining, or did the
   round just re-point at easier targets?
2. **Refutation-recurrences** — a finding refuted twice or more is either a corpus that
   fails to record the KEEP rationale, or a genuine attractor to skip next round.
3. **Confirmed-after-refuted** — a finding refuted in a prior round but confirmed now
   means the earlier refutation was wrong; the corpus over-trusted a refute.
4. **Cross-round classes** — N isolated per-round nits of the same shape → a class worth a
   mechanical contract.
5. **Cumulative coverage map** — the union of never-covered surfaces.
6. **Scope-narrowing** — this round's covered surface as a fraction of the whole vs prior
   rounds: is the microscope zooming in?
7. **Verdict + the "converged" gate** — the word "converged" is permitted ONLY if a
   corpus-blind pass produced the null AND the coverage map has no high-value
   never-covered surface. Otherwise the honest label is **"coverage-null, not
   convergence-null."**
8. **Append** the new ledger row (append-only; never rewrite prior rows).

The critic and its ledger are the interpretive layer ON TOP of two existing stores, not a
rival to either: the forward ledger (with the per-round reports) is the per-FINDING store,
and the per-run ledger the first persist writes under `cc/` is the per-RUN structured raw
record. The convergence ledger is the per-ROUND curated narrative — coverage map, open
leads, convergence read — which neither of the other two captures.

### Enforcement ceiling (honest)

The scope-breaker + convergence-critic stages are enforced at three layers, descending in
strength: a **contract test** over committed `.claude/workflows/*.js` review scaffolds
asserts the scaffold carries every stage (write it in your own suite — the harness pins
its own copies that way); the **scaffold**
(`.claude/workflows/_convergence_review_template.js`) is a start-from-complete base so a
copy inherits them; and this **protocol** is the source of truth. A review authored inline
via the Workflow tool is NOT a committed file, so no contract can inspect it — inline
ad-hoc reviews remain *discipline*-enforced. Do not claim mechanical enforcement of
inline reviews.

### The dedup register can eat findings

The finder DISCIPLINE block tells a finder to DROP a finding whose file and symbol are
already in the dedup register, and the refute lane refutes on the same match. That is
correct only while every register entry that is still a defect is also a ledger row. If
the register stops being written — the persist hop breaks and nothing notices — an entry
that never became a row suppresses its own re-discovery in every later round, silently,
leaving no trace of what it dropped. Two consequences: a low yield from a large round is
NOT evidence of a clean repo while a second register exists; and a stale register is
retired by *verifying* its entries, never by re-recording them.

A verification sweep that scales: one cheap agent per entry with a fresh context (does the
claim hold at HEAD by symbol, is it already a row by claim), one frontier-model critic per
still-open verdict with DEFAULT = REFUTED and an oracle required, a mechanical grep gate
that demotes any verdict whose quoted evidence is not found verbatim in the cited file
(never to FIXED), and a hand sample of a couple of dozen entries formed BEFORE any agent
result exists, with the distrust threshold pre-registered. Read the run's journal rather
than the per-agent lane files — expect a fraction of agents to write none — and eyeball the
critic's "mechanism true, harm false" refutations rather than trusting them blind.

### Filing the survivors is a second pipeline, and its checkers carry the value

Verifying an entry and writing the ledger row it becomes are different jobs, and the second
one needs its own checker. Run the filings as **draft → check → revise → recheck**: one
drafter per confirmed group writes the row text, the site anchor and a structural probe in
the ledger's own grammar, and **one checker per draft** drives that probe in a clone and
audits the text against HEAD. Expect the checkers to name a real fault on most drafts — a
symbol that does not exist, a count off by one, a fix shape that closes some of the sites
and not the rest, a probe a comment could flip. One revise round, with the settled calls
(severity, section, population, audience) written into the reviser's brief so the agent
applies them rather than re-litigating them, clears most of what the checkers caught; a
residue stays to be decided by hand. Budget the round by its checkers rather than its
drafters, and expect a hand residue rather than a second revise round.

Two costs to plan for.

- **A capped cell is a budget you spend, not one you append to.** Where your drafting brief
  caps a row's text, nothing mechanical enforces it — a row writer writes whatever its
  input holds. Every over-length cell rewritten by hand overruns the cap again on the first
  try, because a hand edit reaches for the clause that is missing and adds it. Count the
  characters before writing, then shed to make room for the correction.
- **A throwaway gate over the ledger is still a reader, and it owes the ledger's one home.**
  A verdict gate that resolves "already recorded" against an index table alone will demote
  true verdicts to "cannot tell", because the index is a summary and the membership answer
  lives elsewhere. Your ledger has exactly one membership reader — in Espalier it is
  the deployed `tools/cc/generate_ledger_regions.py`, which spans every id-leading member
  row in every section. Use it. A one-off script is not exempt from the rule to grep for a
  sibling store before building a rival.
