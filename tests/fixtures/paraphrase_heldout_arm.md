<!-- Repo-facing note prepended on adoption; everything below the rule is the
     authoring agent's own text, unedited. -->

# Held-out paraphrase arm (fixture)

The uncontaminated yardstick for `/recall` document-expansion work, and the only
reason the alias gain reported in `docs/STANDING_PRINCIPLES.aliases.md` is credible.

**Provenance.** Authored 2026-08-19 by an agent given `docs/STANDING_PRINCIPLES.md`
and forbidden to open anything under `tests/`. A *second*, independent agent wrote the
aliases under the same prohibition and never saw this file. Neither could see the
other's output. That mutual blindness is the whole asset — it is what separates a
measured retrieval gain from a memorised one.

**⚠ This fixture is consumable, and spending it is silent.** The moment anyone writes
an alias because a query here missed, that query stops measuring retrieval and starts
measuring the alias. It is not a hypothetical: during authoring, a self-scored probe
set went 15/48 to 31/48 once its author saw which probes failed, and roughly thirteen
of those sixteen gains were worthless. If you tune against a row, **delete the row**
and say so in the commit. A benchmark that only ever goes up is not measuring anything.

**Scoring.** 24 of the 48 rows are marked `CONTESTED:` by the author, usually because
a `memory/` or `sharp-edges/` document is a defensible answer instead of the filed
principle. `tests/test_recall.py` therefore scores the **uncontested rows only**, as a
characterisation ratchet rather than a hard gate.

---

# Held-out recall evaluation set — `docs/STANDING_PRINCIPLES.md`

Authored 2026-08-19 from the principles text alone, independently of any existing
benchmark. Nothing under `tests/` was opened, grepped, listed, or globbed.

48 queries: 16 sections x 3. Each triple varies register — one **terse** (3-6 words),
one **full question**, one **symptom statement** that asks nothing. Section-title words
are avoided throughout (mechanically checked: zero token overlap after stopword
removal), and body phrasing plus each section's attested case study are paraphrased or
replaced. A query lifted from a section's own postmortem can only be answered by that
section, which measures echo rather than retrieval.

---

## READ THIS BEFORE SCORING

**The principles are not the whole answer space.** `memory/recall-engine-extension.md`
(verified) states the `/recall` pull corpus as `memory/*.md` + `docs/SHARP_EDGES.md`
sections + `docs/sharp-edges/*.md` + `docs/STANDING_PRINCIPLES.md` sections +
self-host `FAILURE_MODES` §1 coinages + exemplars. So the engine ranks these 16
sections against a few hundred rival documents, and for a number of rows below **a
`memory/` or `sharp-edges/` doc is the better human answer than the principle it is
filed under.** Every such rival is named on the row as `CONTESTED:`, with a verified
path.

Consequences for the measurement:

1. **A named rival returned instead of the filed key is not a miss.** Score it as a
   hit, or the metric will punish the engine for being right. Only an unnamed,
   unrelated return is a miss.
2. **Four sections declare a home elsewhere, and that covers all three of their rows** —
   so these are section-level, not marked per row. §8 defers the upstream is-this-a-class
   question to `memory/fix-the-class-not-the-instance.md`; §12 names
   `docs/sharp-edges/source-tree-is-not-an-artifact-oracle.md` as its footgun form;
   §13 declares **"Sole home: `memory/read-the-neighbours-before-adding-a-sibling.md`"**;
   §15 defers its corollary to `memory/classify-the-surface-before-measuring-it.md`.
   Returning the named doc for any row in those sections is correct.
3. **Some rows have a canonical answer the engine physically cannot return.**
   `docs/FAILURE_MODES.md` §§2-15 are outside the corpus (only §1 coinages are
   indexed). The best answer to §7 r2 is §13.7, to §6 r1/r3 is §5.12, to §5 r2 is
   §13.13, to §12 r3 is §13.30. Those rows will score as clean hits on the principle
   while measuring nothing about ranking quality. Treat them as filler, not signal —
   or index FAILURE_MODES and re-key them.
4. **This arm tests one of two rankers.** Root `CLAUDE.md` records that `/recall` runs
   a namer and a describer, calibrated differently. This set is ~48/48 describe-shaped
   **by instruction** — the brief called the describing query "the whole difficulty
   being measured". A change measured only here is unmeasured on the naming ranker.

---

## 1. Make it prove it

- no evidence beyond the transcript
    why: the standing answer to "should I believe an assertion" is make it mechanically checkable.
    CONTESTED: §4 (independent oracle) — a transcript is a rendered frame, which is §4's subject. §1 wins only as the general standard rather than the tool-output case.
- how much of what i've been told this session could i actually go and check?
    why: self-asserted confidence is a hypothesis, not a result, including your own.
    CONTESTED: §3 (a finding is a claim until grep-verified) if the reader hears "check" as "grep-verify a citation".
- three paragraphs explaining why it's correct and not one thing i can execute.
    why: load-bearing claims must be mechanically provable, not argued.

## 2. Toolbelt, not security boundary

- am i over-hardening this
    why: false-positives and workflow friction outrank closing bypass classes.
- someone determined could get round write_guard by shelling out, do i actually need to close that off?
    why: the threat model is operator/AI mistakes, not malice.
    CONTESTED: `docs/SHARP_EDGES.md` § "Local Hooks Are Not a Sandbox", whose stated trigger is treating a hook event as a security boundary — the concrete form of this exact question.
- the tighter matcher catches the thing i was worried about and also three edits i make every day.
    why: reads a guard decision through the cost-of-false-positive lens the principle mandates.

## 3. A finding is a claim until grep-verified

- agent report cites a missing line
    why: agent citations are unverified assertions until checked against HEAD.
    CONTESTED: `docs/sharp-edges/citation-rot-verify-fix-target-tree-wide.md` owns the concrete form; `memory/classify-the-surface-before-measuring-it.md` disputes the premise, since on a record surface a stale pointer is expected aging rather than a defect.
- before these lane results go into the ledger, how much of each citation do i have to confirm myself?
    why: the extension the principle paid for — a citation is laundered into fact by being written down.
- the refute pass killed three findings and i haven't checked any of its reasoning.
    why: §3's second paid-for extension owns this outright — "the refutation is a claim too".

## 4. Verify tool output through an independent oracle

- command returned nothing at all
    why: an empty or stale frame needs a second, independent mechanical check.
    CONTESTED: `memory/untrusted-oracle-protocol.md` is Core Rule 8's declared sole home and covers empty/echoed/stale frames verbatim; `memory/complacent-oracle.md` is a third fit.
- pytest printed a pass but i never saw it collect anything, how do i tell whether it actually ran?
    why: a rendered pass is not a test result; `exit 0` is not acceptance.
    CONTESTED: `docs/SHARP_EDGES.md` § "A rendered test-failure frame is not a test result" is the same claim at footgun altitude.
- the scan says zero hits on a tree i know has at least a dozen.
    why: output that looks fabricated must be confirmed by a second oracle before acting.
    CONTESTED: `docs/sharp-edges/the-measuring-instrument-is-a-claim-too.md` is arguably the *better* answer — its class signature is "the probe is unverified, and its failure mode is a plausible null", and its lead instance is a probe that walked an empty directory and reported zero. §4 is the parent frame; that doc is the diagnosis.

## 5. The null result is the signal

- three clean rounds running
    why: repeatedly turning up nothing new is the strongest correctness evidence there is.
    CONTESTED: `docs/sharp-edges/convergence-is-an-angle-set-property.md` reads the same symptom as a fact about the angles attacked rather than the code; §16 reads it as a reason to stop.
- yields have dropped every sweep for a month, do i keep paying for these?
    why: §5 says read the BLOCKER yield and severity trend rather than the raw count.
    CONTESTED: genuinely two-sided and the `why:` should not be read as settled — `docs/FAILURE_MODES.md` §13.13 holds that declining yield is the *signature of a degraded instrument* (dedup-corpus staleness), the opposite conclusion. `memory/gating-on-count-manufactures-findings.md` is a third. Note §13.13 is outside the pull corpus, so the engine cannot offer it.
- last two passes came back with nothing and i'm about to stop running them.
    why: a quiet pass is the outcome being paid for, not evidence the instrument has failed.
    CONTESTED: §16 (name the user) reaches the opposite conclusion from the same symptom — a clean pass is evidence, not licence to re-point.

## 6. Direction ≠ magnitude

- did it actually help
    why: a sound mechanism is not a measured effect.
    CONTESTED: §16 (name the user) — its operator form, "how the change affects the reality of the program", is close to a gloss of this four-word query.
- the reasoning for why this is faster is airtight, how do i get an actual number on it?
    why: measure before/after on the repo's own metrics; never let plausibility imply size.
- eleven packs shipped this month and i can't tell anyone what changed as a result.
    why: shipping is not measurement; the effect size was never taken.

## 7. Earn the red

- test passes without my patch
    why: a fix needs a test that fails without it.
    CONTESTED: `docs/SHARP_EDGES.md` § on an earn-the-red snapshot-restore masked by stale bytecode is the concrete cause of this exact observation.
- this only reproduces on windows and i'm on a mac, how do i lock the behaviour when i can't make it fail here?
    why: the version/OS-gated carve-out — version-agnostic fix plus a contract-lock, labelled unverified-on-host.
- wrote the test after the fix and it went green first try.
    why: an unearned green means the test does not discriminate the mutation it names.

## 8. Class-fix scope = every shipped surface

- did i get all the instances
    why: enumerate the real population; a declared site count is a floor.
- i fixed this in the engine and the same code ships in two other places, how do i prove i got all of them?
    why: the fix and its contract must reach every shipped/overlaid directory, not just the engine dirs.
    CONTESTED: `memory/asset-mirroring.md` owns the byte-pinned mirror rows and answers "the same code in two other places" directly.
- the pack named three call sites and a grep turns up nine, no idea whether nine is all of them.
    why: a declared count is a floor to be replaced with a mechanical enumeration.
    CONTESTED: structurally a twin of §10 r3 — declared count versus found count, separated only by "call sites" (fix reach) versus "violations" (rule calibration). `memory/completeness-gate-must-discover-its-population.md` owns the second clause.

## 9. Fast earns scrutiny

- this feels too easy
    why: breakthrough-feeling is the cue to slow down and check harder.
- i think i've found the one thing that explains all of it, what should i do before i build on that?
    why: the better an idea feels, the harder it should get checked.
    CONTESTED: `memory/premise-check-before-authoring-a-fix.md` may be the better answer — "verify that premise FIRST, against an independent oracle, before you design the fix, not after you've built on it" is this query's operative clause verbatim. §9 supplies only the slow-down half.
- it all clicked about ten minutes ago and i've committed twice since.
    why: strip the most flattering evidence and see what still stands.

## 10. Match the net to the hole

- rule passes my one example
    why: a new gate is green on its synthetic fixture while its real calibration is untested.
    CONTESTED: `docs/sharp-edges/a-new-guard-is-blind-the-way-it-claims-to-see.md` is the same observation as a footgun.
- my new scanner is green on the fixture i wrote for it, how do i find out whether the rule holds for the code that's already here?
    why: calibrating a contract against the live population is a different check from a discriminating test.
    CONTESTED: `memory/calibrate-an-enforcement-contract-against-the-live-population.md` is arguably the better answer — §10's own prescription is that doc's title, and the doc carries the worked measurement. §12 also fits any "my new gate passes for me" phrasing; §10 is right only because the axis is population, not tree.
- wrote the check expecting a handful of hits and it's lighting up most of the tree.
    why: the mis-calibration symptom — the rule's mesh does not match the hole it was written for.

## 11. Scope-out cannot cover the deliverable's own defects

- amend the criterion or defer
    why: §11's central fork, and it answers it — amend and record, never defer a flaw in what you are delivering.
- the pass criteria i wrote are stopping me from strengthening a check inside the thing this pack delivers. amend or defer?
    why: the corollary — an anti-loosening criterion must constrain strength, not text.
- opened a DEF row against a gate i finished writing yesterday.
    why: the tell — that is not a backlog item, it is an unfinished fix.
    CONTESTED: `docs/sharp-edges/a-new-guard-is-blind-the-way-it-claims-to-see.md` covers the artifact built to catch class X being an instance of X.

## 12. A gate is proven only on a tree it was not written on

<!-- Row deleted 2026-09-04 under this file's own rule: the alias sidecar's header
     quoted this row's query verbatim as its motivating example, and that header is the
     brief every blind alias author is handed. The channel was open, so the row stopped
     measuring retrieval. It was CONTESTED (unscored); _HELDOUT_ROWS 48 -> 47. -->
- the check i just added passes locally. where else should i run it before i believe it?
    why: the acceptance oracle must be a real clone, extracted archive, non-editable install, fresh venv, or CI.
    CONTESTED: §10 (match the net to the hole) — the seam is marked on the §10 side too. "Passes for me" triggers both; the tree-versus-population disambiguator is not in the query.
- green here, and the first thing a fresh checkout did was fail it.
    why: a gate validated only where it was authored has been tested against its own author's assumptions.

## 13. Read the neighbours before adding a sibling

- wrote a helper that existed
    why: question one of the habit — does this already exist? Import it.
    CONTESTED: `memory/grep-for-a-sibling-store-before-building-a-rival.md` covers building a duplicate store.
- need a path check in this module. do i write one or is there already a way this file does it?
    why: question two — if it must be new, match the shape of what is around it or state why not.
    CONTESTED: `docs/SHARP_EDGES.md` § on every new tree-walking scanner re-implementing the walk contract, whose stated trigger is copying the nearest sibling's walker.
- my new warning reads fine in the diff and i haven't looked at the rest of the file.
    why: exactly the failure review cannot catch — the diff is locally correct, the defect is visible only against the whole file.

## 14. Derive the list, don't test a hand-written copy of it

- still typing this out twice
    why: two maintained copies of something the code can already compute.
- about to write a check that recomputes the answer and compares it to a table someone typed. is that the right move?
    why: the tell — if the typed copy only exists so the check has something to compare against, delete it.
- the readme table and the code drifted again and the fix is always to retype the table.
    why: emit or read from the computation and drop the second copy; a generated region has nothing to drift against.
    CONTESTED: `docs/SHARP_EDGES.md` § on a hand-maintained doc enumeration with no code-pinned parity test rotting silently is at least as good an answer, and is the concrete form.

## 15. Many attempts, a different failure each time — the problem is mis-specified

- fourth try, new breakage
    why: novelty of the failure mode, not the count of tries, is the diagnostic.
- every round i patch this the next run breaks in a way i hadn't seen before. keep going or back up?
    why: a hard defect fails the same way; a mis-specified one fails a new way each round.
- this keeps dying of a new thing and i'm out of theories.
    why: when the failure mode is novel every round, stop writing fix code and re-ask what the thing is.

## 16. Name the user, or it is not a defect yet

- nothing has ever hit this
    why: latent is not urgent; a mechanism that would fail is not a person who does.
    CONTESTED: `docs/SHARP_EDGES.md` § "A Long-Latent Issue That Just-Now Bites Is a Class" argues the inverted polarity — "it only happened once" *is* the under-scoping. A real contest rather than a distractor.
- it's real and it reproduces but i can't picture who it happens to. does it still get worked?
    why: if you cannot say who gets hurt and what they were doing, record it and move on.
- everything in the backlog is real and none of it is anything a person would notice.
    why: a finding earns work only when it maps to an outward change; the rest is recorded and left.

---

## Provenance

One authoring pass from `docs/STANDING_PRINCIPLES.md`, then three independent review
lanes that had not seen the authoring reasoning. All three confirmed in their replies
that they read nothing under `tests/`.

**Lane A — blind re-keying.** Read each query cold and named the principle it would
return, without seeing the filed key: 48/48 agreement, 0 unanswerable. It attached its
own caveat, which is the part worth keeping: the agreement rate was partly an artifact
of **lexical echo**, since several terse rows lifted phrasing from the body of their own
section. Those were rewritten, so **48/48 was measured against an easier draft and is
not a property of this set.**

**Lane B — realism and register.** Confirmed register discipline passes literally, then
found that (i) six rows were the target section's own case study read back with its
numbers decremented, (ii) nearly every full question used the same `context — question?`
em-dash pivot, (iii) there were zero contractions and zero concrete identifiers across
48 rows, and (iv) seven symptom rows narrated the reasoning error rather than the state.
All four fixed: em-dashes are now absent from every query, casing and contractions are
typed-query shaped, real repo nouns appear where they do not hijack the key, and the
symptom rows describe what is on screen.

**Lane C — key challenge.** The most consequential lane. It found the answer-space
problem now written up under READ THIS BEFORE SCORING, showed that the contested
markers had been allocated one-per-section by habit rather than by rival density, and
named specific better answers for five rows. Its citations were spot-checked verbatim
against four source docs and the corpus-scope claim against
`memory/recall-engine-extension.md`; all held, so its analysis was accepted broadly.
Acting on it: four rows rewritten (§3 r1, §8 r1, §11 r1, §14 r1), markers reallocated by
rival density with verified paths, two parenthood markers dropped (§1 is the generic
parent of ~20 rows, so marking it on two made the marker non-discriminating), and one
`why:` corrected — §5 r2 had asserted that declining yield is "not a degraded
instrument", which contradicts this repo's own canon.

**Convergence note.** Lanes A and C independently flagged the same lexical-echo class
on largely the same rows, from different angles and without seeing each other. That
agreement is the main reason the echo rewrite was treated as necessary rather than
stylistic.

**One unresolved disagreement, left visible rather than settled.** Lane A flagged
`exit 0` (§4 terse) as body echo; Lane B rated that section's rows among the strongest
in the set. The row was rewritten to remove the echo, satisfying A at some realism cost,
since `exit 0` is genuinely how the phrase gets typed.
