# Convergence review protocol

**Status:** active
**Linked from:** [CLAUDE.md "Core Rules"](../CLAUDE.md)

A repeatable, multi-agent review for hardening a codebase too large for any
single pass — human or model. It is the method behind the TP-169→193 pre-OSS
arc, codified here so it is a reusable tool rather than something re-improvised
each round. It pairs with [the fan-out finding schema](fan-out-finding-schema.md)
(the wire format) and the `fanout-audit` scaffold (the generic engine).

## What it is

A **fan-out** of finder agents, each pointed at a *different* slice of the
surface, each returning `FINDING_SCHEMA` objects; **adversarial refuters** cull
them (default-refuted, oracle-confirmed); **survivors persist** to a dedup
corpus; and only a **compact summary** returns to the main window (the two-hop
anti-bloat dataflow — verbose rationales never reach the orchestrator chat). The
machinery lives in `espalier/fan_out_findings.py`
(`FINDING_SCHEMA` + `aggregate_findings` + `append_findings_to_corpus`); the
cross-round dedup source is `task-packs/FORWARD_LEDGER.md` (live rows plus the
section-6 do-not-rediscover entries); the shared findings corpus retired to the
record branch on 2026-09-21.

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
  that maps what the other finders did *not* cover (→ next round's targets).
- Read every finder through the **governing frame**: Espalier is a workflow
  toolbelt, not a security boundary; the threat model is operator/AI *mistakes*,
  not malice; **friction and false-positives are the high-severity class**, not
  un-closed bypasses.
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
  share the premise *"this surface asserts NOW"*. Attested 2026-08-09: a 21-agent
  pass overturned 8 of 13 already-done verdicts, and every "residual" it produced
  was **record-surface aging reported as rot**. The refute prompts asked for *"a
  count updated in one place and left stale in another"* and *"a doc edited but
  its mirror twin not"* — on a `_Source:`-dated record a diligent agent finds
  exactly that, accurately, and is confidently wrong. More adversarial passes
  bought more precise measurements of the wrong thing, which is
  `docs/STANDING_PRINCIPLES.md` §15's corollary showing up in the **verification**
  layer rather than in a fix. Carry surface-class as a per-finding field the
  finder must fill, so the refuter inherits a premise it can attack; a lens
  applied afterwards arrives too late.
  See [[classify-the-surface-before-measuring-it]] — including the granularity
  trap, where a path-keyed record registry cannot express a file that is claim
  and record in one.

- **When the pass sorts findings into tiers, attack BOTH directions or say you
  did not.** A refute lane pointed at one tier measures only the error that tier
  can make. Attested 2026-09-02: a classification put 205 ledger rows into
  adopter-facing / adopter-visible / host-only, and the adversarial stage ran over
  the 67 adopter-facing rows only — trying to demote each. It overturned **38, a
  55% rate**, which reads as a rigorous pass and is. But nothing ran the other
  way: not one of the 98 adopter-visible or 40 host-only rows was challenged for
  *promotion*. The reported blocking set was 31, and at even a fifth of the
  demotion rate through 98 untested rows that is roughly **5 missed blockers** —
  a sixth of the release scope, invisible, and invisible in the flattering
  direction, because a one-sided pass can only ever shrink the number it reports.
  A high overturn rate is evidence the lane WORKS, never evidence the tiering is
  right. Either run the promotion lane too, or state the untested direction and
  its expected magnitude in the readout so the reader can price it.

  ⚠ **The tiering rule itself can bias one direction.** The same pass keyed tier A
  on *"name a concrete symptom a stranger experiences"* — a rule an invisible
  failure cannot satisfy by construction, so every fail-open defect was pushed
  down a tier unless a reviewer happened to reach for a coverage argument instead.
  Two rows of one shape landed in opposite tiers on exactly that difference. When
  a rule cannot be met by a whole class of defect, it is not a filter, it is a
  blind spot with a rationale.

## How to read the result (the part that is easy to get wrong)

The findings are only half the value; the **trend across rounds** is the other
half, and it is where the method is most often misread.

- **Track BLOCKER / major yield + the severity trend, NOT the raw finding count.**
  The count never reaches zero — each round re-points at a new corner, so there is
  always *something* ("the drill moved, not the well is dry"). Raw count is a false
  convergence signal.
- **Zero blockers + decaying majors across 2-3 INDEPENDENT rounds = the
  high-severity classes are exhausted.** That is good news and a strong signal. What
  it licenses depends on the mode — see **When to stop** below. It is not, on its
  own, a reason to run another round.
- **The accumulating "nothing new" across independent passes IS the correctness
  signal** — like research, a result you cannot break across many independent
  attempts. A null result is a real deliverable, not a wasted pass; N *independent*
  nulls compound into confidence the way replications do.
- **When the static rounds mature, ADD a modality they cannot reach** (a dynamic
  end-to-end run: real `init`/`fuse` → real PR → real session → non-Darwin) —
  *additive*, not a replacement. Keep making passes, but make each one
  **independent and differently-angled**; identical repeats add little, independent
  ones compound. In **hardening** mode the cost discipline is "spend on a NEW angle"
  rather than repeating an old one. In **release** mode it is "stop checking and go
  ship" — see **When to stop**.

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

**In release mode the gate is a driven adopter walk, not a review.** *"Did a review
find something?"* is not a release criterion — it is always yes. *"Does a stranger
succeed on a clean machine?"* is (`scripts/wheel_smoke.py`: built wheel → fresh venv
→ fresh repo → `init` → `install-ci`).

**Severity is measured in user-facing terms**, per `docs/STANDING_PRINCIPLES.md` §16.
A finding no user can reach is not a BLOCKER however sound the mechanism behind it —
it is a ledger row. **Read the BLOCKER-yield trend on findings that pass §16**, or the
trend measures the instrument's reach rather than the product's health.

**The failure this closes (2026-08-11).** Four review rounds against one pack, every
finding real, not one of them ever fired, zero source changed — while twelve verified
day-one defects sat open. The rounds were correct and the mode was wrong. Recorded
because the previous wording of this section (*"not a reason to stop"*, *"the cost
discipline is 'spend on a NEW angle,' not 'stop checking'"*) was the most direct
instruction in the repo toward exactly that outcome.
- **Adversarially self-check a "we've converged" claim** with a small agent panel
  (a theater-prosecutor vs a value-defender, both grounded in the corpus). Putting
  the *conclusion* through the same scrutiny as a finding is how it earns trust.

## Honest limits

- **Earn-the-red has a platform ceiling.** A version/OS-gated bug cannot go red on
  a host that already has the safe default (e.g. a CPython <3.13 symlink bug on a
  3.14 host). Ship the version-agnostic fix + a contract-lock test and label the
  target-version magnitude *unverified-on-host* — do not stamp it "verified." This
  is one reason the dynamic non-Darwin / old-runtime pass matters.
- **A fan-out finding is a CLAIM until grep-verified vs HEAD** — even an
  "adversarially verified" one. Re-confirm load-bearing findings yourself.
- **Each round is Opus-scale** (≈2-4M tokens). Proportion the finder count to the
  ask; `log()` any coverage the round bounded (top-N, no-retry) so silent
  truncation does not read as "covered everything."

## Tooling

- **Engine / schema:** `espalier/fan_out_findings.py` and
  [fan-out-finding-schema.md](fan-out-finding-schema.md).
- **Generic scaffold:** the `fanout-audit` skill / `.claude/workflows/_fanout_audit.js`
  (finders → refute → persist, with the two-hop bridge).
- **Scope-breaker-complete scaffold (start here for a full round):**
  `.claude/workflows/_convergence_review_template.js` — the successor to
  `_fanout_audit.js` with all four scope-breakers + the convergence-critic pre-wired
  (see the "Scope-breakers (mandatory floor)" section below). Copy it and swap `DIMENSIONS`.
- **Worked example:** `.claude/workflows/_oss_convergence_round4.js` — 16
  least-attacked-surface dimensions, a general adversarial refute, and a one-hop
  persist to its per-round report (a dated one-off: it writes no finding-ledger
  row). Copy it and edit the `DIMENSIONS` for your surface.
- **Dedup source:** `task-packs/FORWARD_LEDGER.md` (live rows + section-6
  do-not-rediscover; the shared findings corpus retired 2026-09-21). The
  per-round report under `reports/` is the round's own record.
- **Per-run ledger:** `cc/finding_ledger.jsonl` (`espalier/finding_ledger.py`) — one
  run-boundaried JSON record per fan-out (scalars + raw survivors); the structured
  substrate the convergence-critic reads for yield/recurrence (`read_ledger`).
- **Cross-round ledger:** `memory/CONVERGENCE_LEDGER.md` — one curated row per review
  round (coverage map, open leads, convergence read); appended by the convergence-critic.
- **Blocker re-verification:** when a pass claims a release blocker, the blocker
  is verified by **re-executing its repro** via `espalier/red_team_guard.py` (an
  independent oracle re-runs `{argv, expect=fail, match}` and a specific
  non-catch-all signature must appear), NOT by the finder's assertion. Gate on
  process + reproducibility, never on finding-count — an honest null PASSES. The
  repro-artifact contract + the count-gating anti-pattern live in
  `docs/CONVENTIONS.md` "Red-team repro contract" and FAILURE_MODES §11.12 /
  §13.10. This is the mechanical form of "read by BLOCKER-yield, not count".

## Scope-breakers (mandatory floor)

Iterated scoped review converges to silence BY CONSTRUCTION: each round scopes off the
prior round, so the blind spot is the *intersection of every lens's exclusions*, and the
dedup corpus inherits prior framing — the microscope zooms in until broadly-visible
problems fall outside every lens. Two structural blind spots compound the more the method
is used: **spatial** (the never-pointed-at region every round assumed was caught earlier)
and **temporal** ("was good ≠ is good" — a static HEAD snapshot cannot see a supplanted
system's DELTA: a commit adds the new path, wires it, and leaves the old one still
reachable; static reachability sees both as live). The operator is explicit that nobody
holds a live codebase's full ripple-map, so ripple-detection must be **mechanized**, not
left to operator vigilance or Claude's memory. Do not read a late-round null as "clean"
unless a corpus-blind, scope-blind pass produced it. Every convergence review MUST
include these four scope-breakers:

1. **Penumbra pass** (spatial) — after finders, hunt the ring just outside each lens:
   per-finding sister-sites / callers, and each lane's structural exclusions.
2. **Actionable critic** (meta) — the completeness critic's named gaps become a SECOND
   finder wave in the SAME run, not just a report Claude reads.
3. **Corpus-blind parallel deep-dive** (temporal) — 1–2 agents (3–5 for a pre-launch
   sweep) with NO scope / NO corpus / NO "already-known" list, run PARALLEL to the scoped
   lanes, allowed to re-find "known-good" things.
4. **Recent-change delta attacker** (temporal) — from `git diff` / recent commits, hunt
   sister-sites / contracts / docs the change TOUCHED but did NOT update. Derives the
   ripple from the diff instead of asking the operator to predict it. This is
   [class-fix scope = every shipped surface](../docs/STANDING_PRINCIPLES.md#8-class-fix-scope--every-shipped-surface)
   as a review stage.

**Default floor** = (1) + (2) + one of (3); (4) fires on any uncommitted/recent work;
full (3) is reserved for the pre-launch "this is it" sweep. The convergence-critic
(below) is the mandatory FINAL stage.

**Classification guard — deferred-intentional ≠ abandoned.** Any finder flagging a
half-finished / abandoned / supplanted / orphaned item MUST cross-reference the Forward
Ledger (`task-packs/FORWARD_LEDGER.md` — its `DEF-*` / `drafted-pack` entries) and in-code
dormant notes before scoring it a defect. A documented deferral (a ledger entry, or an
`audit_accuracy`-style "planned / dormant / not-yet-built" docstring) is a KEEP, not rot.
The refute stage rejects any "dead / half-finished" finding whose subject is a
ledger-documented deferral. (Provenance: a round-3 pass mis-flagged `strengthen --suggest`
/ `DEF-3` as a half-finished build for want of this check.)

### The convergence-critic (mandatory final stage)

Iterated review has no cross-round sight by default: the yield trend, premature
"converged" calls, findings refuted in one round and confirmed in a later one, and
slow-drip *classes* (N isolated per-round nits of one shape) are visible only with the
whole series in view — and Claude otherwise reconstructs them from memory each time, the
exact unreliable self-report the epistemic rules warn against. The convergence-critic
mechanizes that view. It is **stateless**, runs LAST in every review, and its state is
the durable ledger. Inputs: the convergence ledger (`memory/CONVERGENCE_LEDGER.md`, prior
rows) + the structured per-run finding ledger (`cc/finding_ledger.jsonl`, read via
`espalier.finding_ledger.read_ledger` — the machine substrate for yield/recurrence, so
those parts are *computed*, not recalled) + this round's finder/critic output. Steps:

1. **Yield trend** vs prior rows — is blocker/major yield actually declining, or did the
   round just re-point at easier targets?
2. **Refutation-recurrences** — a finding refuted 2+ times is either a corpus that fails
   to record the KEEP rationale, or a genuine attractor to skip next round.
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
rival to either: the forward ledger (with the per-round reports) is the per-FINDING store, and
`cc/finding_ledger.jsonl` is the per-RUN structured raw record. The convergence ledger is
the per-ROUND curated narrative — coverage map, open leads, convergence read — which
neither of the other two captures.

### Enforcement ceiling (honest)

The scope-breaker + convergence-critic stages are enforced at three layers, descending in
strength: a **contract test** over committed `.claude/workflows/*.js` review scaffolds
(`tests/test_convergence_workflow_stages.py`) asserts the scaffold carries every stage;
the **scaffold** (`.claude/workflows/_convergence_review_template.js`) is a
start-from-complete base so a copy inherits them; and this **protocol** is the source of
truth. A review authored inline via the Workflow tool is NOT a committed file, so no
contract can inspect it — inline ad-hoc reviews remain *discipline*-enforced. Do not claim
mechanical enforcement of inline reviews.

### The dedup register can eat findings (2026-09-21)

The finder DISCIPLINE block tells a finder to DROP a finding whose file and symbol are
already in the dedup register, and the refute lane refutes on the same match. That is
correct only while every register entry that is still a defect is also a ledger row. When
the register stops being written (the persist hop broke in July 2026 and nothing noticed
for two months), an entry that never became a row suppresses its own re-discovery in every
later round, silently: the 2026-09-19 round left no trace of what it dropped. Consequences:
a low yield from a large round is NOT evidence of a clean repo while a second register
exists; and a stale register is retired by *verifying* its entries, never by recording
them. The shape that verified 609 entries in three hours for tens of dollars: one Sonnet
agent per entry with a fresh context (does the claim hold at HEAD by symbol, is it already
a row by claim), one Opus critic per still-open verdict with DEFAULT = REFUTED and an
oracle required, a mechanical grep gate that demotes any verdict whose quoted evidence is
not found verbatim in the cited file (never to FIXED), and a twenty-entry hand sample
formed BEFORE any agent result exists, with the distrust threshold pre-registered. Read the
run's journal, not the lane files (a fifth of agents wrote none), and eyeball the critic's
"mechanism true, harm false" refutations rather than trusting them blind
(`reports/ledger-rebuild-2026-09-20/corpus-fold/`, TP-452 1-E).

### Filing the survivors is a second pipeline, and its checkers carry the value (2026-09-21)

Verifying an entry and writing the ledger row it becomes are different jobs, and the second
one needs its own checker. The filings that closed the fold above ran as **draft → check →
revise → recheck**: one Opus drafter per confirmed group wrote the row text, the site anchor
and a structural probe in the ledger's own grammar, and **one Opus checker per draft** drove
that probe in the clone and audited the text against HEAD. Of **42** drafts the checkers
passed **7** clean and named a real fault on **35** — a symbol that does not exist, a count
off by one, a fix shape that closes 3 of 7 sites, a probe a comment could flip. One revise
round, with the operator's settled calls (severity, section, population, audience) written
into the reviser's brief so the agent applies them rather than re-litigating them, cleared
**29 of the 35**; the residue was **six** rows decided by hand. The drafts alone were right
about one time in six, so budget the pass by its checkers rather than its drafters, and
expect a hand residue rather than a second revise round.

Two costs to plan for.

- **A capped cell is a budget you spend, not one you append to.** The drafting brief caps a
  row's text (1900 characters at 1-E) and nothing mechanical enforces it — `ledger_row.py`
  writes whatever the `--text-file` holds. Every over-length cell rewritten by hand overran
  the cap again on the first try, because a hand edit reaches for the clause that is missing
  and adds it. Count the characters before writing, then shed to make room for the correction.
- **A throwaway gate over the ledger is still a reader, and it owes the ledger's one home.**
  The first cut of the verdict gate resolved `ALREADY_ROWED` against the §2 index table alone
  and demoted four true verdicts to `CANNOT_TELL`.
  `scripts/generate_ledger_regions.py::live_cell_ids` is the membership reader and already
  spans every id-leading member row in every `§CN` section
  ([[four-gates-the-targeted-proofs-never-show]] item 22 says which of the two readers a gate
  wants); a one-off script under `reports/` is not exempt from
  [[grep-for-a-sibling-store-before-building-a-rival]].
