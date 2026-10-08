# TP-475 — Know when work is worth doing: lineage at filing, and the layer questions before the class question

## Status

- Version target: after `0.8.0b2`, on its own lane. Execution waits on Task 0.
- Type: feature (ledger tooling) + process (the discipline the tooling feeds).
- **Kind: PACK.**
- Ledger: one §3 row names this pack (filed 2026-10-07). Task 1 closes an unfiled candidate: `scripts/ledger_trend.py` prints an unchecked per-step identity on a merge-heavy ref.
- Gate: the operator's words, 2026-10-07.
  - First session, approving the direction: "We want to know when something is 'worth doing' and when something is 'banging against a brick wall'".
  - Second session, after the first draft's alarm was refuted: "If we are in that patchwork mode, that is a good trigger to check. Sibbling sites keep poping up, or many fixes same issue, also signes. The issue is sometimes we are targeting 'the symptom' not 'the real issue' and we want to build systems that helpo with that."
- **Revision history:**
  - **Draft 1** (first session) proposed a per-surface replacement alarm, which fires when a surface's replacements per drained row stay at 1.0 or above.
  - Its Task 0-A ran in the second session, with its thresholds fixed before the run, and **refuted it** (record under Task 0).
  - **Draft 2** (second session) kept Task 1, and replaced the alarm with lineage recorded at filing and two advisories keyed on it.
  - **This is draft 3** (2026-10-08, third session), amended after the pack was assessed against its purpose: make the system notice when work is aimed at the symptom in a layer that cannot reach the goal. The operator approved the amendments. They are:
    - **0-B is not run.** Its merge-level proxy cannot see lineage on this tree, because sibling rows land in separate filing merges (record under 0-B). Its pre-registered exit is taken directly.
    - **0-C gains a blind, out-of-sample arm**, because the five questions were derived from the guard rows they were to be tested on, and graded by the session that wrote them.
    - **A second firing point at plan time.** Filing is where lineage is recorded, but the layer is chosen when a session picks a row and plans its fix. A read-only `ledger_row.py lineage <id>` verb serves both, and `/implement-task` and `/implement-pack` run it.
    - **Lineage is carried from where it is found:** the reviewer's finding and the handoff's notes name the parent row, so the filing lane can pass `--sibling-of`.
  - **Draft 3, amended 2026-10-08 (fourth session):** 0-C ran with both arms and refuted nothing (record under Task 0). Question 3 gained the irreversibility exception, because the blind arm routed rows away that no layer can take. The operator approved that wording.
    - **§20 waits on 0-C's blind arm,** and must not cite `TP-476` as a proven instance until `TP-476` wave C has struck rows.
    - **The Motivation's lineage record is corrected:** it was attributed per lane, not per row.
- Siblings:
  - `TP-476` (guard by location) is the instance that motivated this pack.
  - `TP-477` (re-target the check) is the audit of other live classes, which the questions in Task 4 would route.
- Provenance: measured on the Windows clone, 2026-10-07. Each measured claim names its command or driver. The scratch drivers lived in the session's job directory and are not committed; Task 0 rebuilds what it needs.

## Motivation

**The operator's question.** When rows are filed faster than they close, is the work converging, or banging against a brick wall? And when it is a wall, is the fix aimed at the symptom rather than the real issue?

**The first answer was net flow, and it does not work (measured; full record under Task 0-A).**
- Draft 1 grouped the ledger's flow by surface and proposed firing an alarm when a surface replaced itself at 1.0 or more.
- Back-tested over first-parent, end-of-day snapshots of `origin/main` from 2026-09-24, with W = 5 days and D = 5 drained fixed before reading:
  - keyed by class, the only surface that ever fired was `§C0`, the standalone catch-all, which is not a surface;
  - keyed by file, no surface reached 5 drained on any day, so the guard never fired.
- Three reasons it fails:
  - **Discovery and replacement are mixed.** The ledger grew from 179 live rows (end of 09-26) to 325 (end of 10-04), mostly in three filing bursts (+34 on 09-29, +78 on 10-02, +51 on 10-03, with nothing dropped). Any trailing window that touches them reads 2 to 10 replacements per drained row on every surface.
  - **A brick wall drains almost nothing,** so a floor on drained rows hides exactly the surface it is meant to catch. The guard files drained 0 to 4 rows per window while 3 to 9 were filed.
  - **Neither key is a job.** Class collapses into the catch-all, and file splits one job (the guard) across three modules.
- The motivating number does reproduce: end of day 10-04 to 10-07 read 0.80 overall, and pooled the guard read 1.43 (7 drained, 10 replaced) against 0.69 for the rest. That holds only in a window starting after the bursts, and that window was chosen after seeing the data.

**What the motivating evidence actually was: lineage.** Each guard fix lane's reviewers filed one to three sibling spellings of the row the lane fixed:
- #126 -> `DEF-1161`, `DEF-1162`
- #132 -> `DEF-1173`, `DEF-1174`, `DEF-1175`
- #131 -> `DEF-1176`
- #136 -> `DEF-1170`, `DEF-1171`

That is "sibling sites keep popping up" and "many fixes, same issue", in the operator's words. Net flow cannot see it: it mixes an audit filing fifty latent rows, which is healthy, with a fix filing its own siblings, which is the wall.

**Correction to that record (measured 2026-10-08, third session).** The attribution above is per lane, not per row, and the rows did not land with the lanes:
- Each fix merge filed none of the rows attributed to it. #131, #132 and #136 filed no row; #126 filed only a row it minted and struck itself. The sibling rows arrived in filing-only merges that struck nothing: `DEF-1160` to `DEF-1162` in #128, and `DEF-1170` to `DEF-1179` in #139.
  - Driver: for each merge on `origin/main`'s first-parent line, the ids new at the merge and the ids that went from live to struck, read from `task-packs/FORWARD_LEDGER.md` at the merge and at its first parent. Ids only; the script lived in the session's job directory.
- Not every attributed child is a spelling sibling. `DEF-1176` is an import-skew row in the hooks' module-top imports. The parent `DEF-1042` sits in the denial text's module, and shares no module with the children attributed to it.
- **Lineage cannot be derived from the site cells instead of recorded.** Of the 16 parent-to-child pairs the lane-level attribution implies, 3 share a `path::symbol` in their site cells, against a base rate of 2.5% for any two rows, live or struck, whose site cell names `_bash_patterns.py` (11 of 435 pairs among 30 rows). A shared module is near-universal on the guard, so it carries no signal either. Driver: the `path::symbol` tokens of each row's site cell, compared pairwise.

The pattern the operator named still stands on the parser rows: fix lanes on one job whose reviews kept finding the next member. But lineage has to be **recorded by the person who sees it**, at the moment they see it; neither history nor the site cells hold it.
- **The ledger does not record lineage today.** `tools/cc/ledger_row.py file` takes no relation flag, and the 210 lines of `task-packs/FORWARD_LEDGER.md` that mention "sibling", "spawned", "found by" or "fold" are free text (`grep -c`, 2026-10-07).

**The wider finding: the repo moves controls, but nearly always by consolidating them (second session).** A history read found 13 places where a control was moved instead of patched instance by instance. It read docs and commit subjects; git history is squashed at 2026-09-24, so earlier outcomes rest on the docs.
- **Consolidation.** Many sites become one chokepoint or one derived list; the same question is asked in one place.
  - Instances: the JSON reader chokepoint, the spawn chokepoint, the fail-open voice helper, the path-separator chokepoint, the stack table, the mirrors, the derived counts.
  - Doctrine names it: `docs/STANDING_PRINCIPLES.md` §14, §18, and `docs/CONVENTIONS.md` "Don't restate the SoT".
  - It stops sibling sites spreading. Defects kept arriving at the new site, though: a second defect in the path chokepoint, the voice gate counting debug-log stderr as speech, the line-ending canon recurring on two new consumers.
- **Re-targeting.** This changes *what* is checked:
  - the effect instead of a prediction of it;
  - the producer instead of every shape at the consumer;
  - behaviour instead of a name.
  - Instances are rarer: the interpreter chosen by what it answers (`§C69`, all members closed), drift compared on signals rather than census (`§C67`, all closed), the uninstall's own predicate (`§C55`, all closed), gates keyed on the event (`§C14`), the artifact that ships (`§C24`), and `TP-476`.
  - **No doctrine names it.** "end-to-end", "enumerating badness" and "complete mediation" appear nowhere in the docs or memory outside this pack pair. Grep, 2026-10-07; the one "Parse, don't validate" mention is `docs/FAILURE_MODES.md`, about a tokenizer.
  - Caveat: the class titles were written once the fix shape was known, so "re-targeted classes close" partly selects for itself. Probable, not proven.
- Consolidation alone stalls when the one remaining question is "recognise every shape of an open input". `tools/cc/hooks/_bash_patterns.py` is such a chokepoint: +1,446 net lines and 14 fix commits on `origin/main` from 2026-09-24 to 2026-10-07 (`git log --no-merges --numstat`).

**Why every gate let the guard stream through.** Each gate checks a fix *inside the frame it is handed*:
- the ledger row states the root cause at the reader level;
- the class question (root `CLAUDE.md` Core Rule 12) answers with a bigger fix in the same layer, which is consolidation;
- reviewers find the next sibling;
- `/implement-task` plans the fix as given;
- §16 names the user truthfully.

None asks whether the layer can reach the goal. The detectors existed and nothing fired them: §2 (false positives outrank closing bypass classes), §15 (a different failure each time means the problem is mis-specified), and the operator's global rule ("which layer is 'it', which is the fix?").

**Prior art** (cited from memory, not re-checked this session):
- Saltzer, Reed and Clark, "End-to-End Arguments in System Design" (1984): a function can be completely implemented only where the knowledge lives; lower-layer versions are optimisations.
- Saltzer and Schroeder (1975), on complete mediation.
- Ranum (2005), on enumerating badness.
- King (2019), "Parse, don't validate".

This also reconciles §17 ("move the catch earlier") with keeping the guards. The early check stays as the cheap optimisation, and the end check becomes the guarantee.

**The named user (§16):**
- the operator deciding which ledger work to fund, who saw filings outpace closes and could not tell a converging stream from a wall;
- every lane agent who files a sibling-spelling row as one more fix in the same layer.

## Scope (in)

1. **Task 1** — `ledger_trend.py` reads a merge-heavy ref first-parent, and its per-step reconciliation checks itself. Unchanged from draft 1; it is the smallest change.
2. **Task 2** — lineage at filing: `ledger_row.py file --sibling-of <id>` records that the new row was found as a sibling of an existing row, in a store that survives strikes. **The parent travels with the finding:** a reviewer's finding names the row it is a sibling of, and so does the handoff's note for a finding left unfiled, so a filing lane in a later session can pass the flag.
3. **Task 3** — the advisories, both advice and never a refusal, at two moments:
   - **where the next member is born (filing):**
     - **a chain advisory:** at `file --sibling-of`, when the new row makes a chain two deep, or the parent's third sibling;
     - **a standalone-cluster advisory:** at `file --section C0`, when the row's site family already holds five or more live standalone rows.
   - **where the layer is chosen (plan time):** a read-only `ledger_row.py lineage <id>` prints a row's chain and its site family's standalone count. `/implement-task` step 1 and `/implement-pack` step 0-A run it for every row the work names. When it reports a chain or a cluster, the plan answers the five questions before it proposes a fix.

   All three print the five questions of Task 4.
4. **Task 4** — the questions as discipline:
   - a `memory/` note with the five questions, the two kinds of move, and the counter-warning;
   - a clause in Core Rule 12;
   - a new principle, §20 (the operator's decision, 2026-10-08);
   - one question in the two reviewer agents' bodies;
   - the five questions printed by `ledger_row.py class` when a class is opened.
5. **Task 5** — red-team. **Task 6** — verify and land.

## Scope (out)

- **The per-surface net-flow alarm** (draft 1's Tasks 2 and 3). Refuted by its own back-test (Task 0-A). Do not re-propose it without a new back-test that removes filing bursts and still discriminates.
- **Back-filling lineage from the free-text mentions.** That is a census of prose, which is unreliable, and reading guard rows in bulk trips the platform classifier (`docs/CLASSIFIER_FALSE_POSITIVES.md`). Lineage is recorded forward only.
- **Making either advisory a gate.** A refusal keyed on a count teaches the filer to suppress or fabricate (`memory/gating-on-count-manufactures-findings.md`). The filer still files.
- **Deciding a row's layer mechanically.** No oracle can. The questions are for the filer and the reviewer, answered in their words.
- **An enumeration-growth detector** (fix commits whose added lines are mostly new patterns or list entries). It is plausible but unmeasured; it is a candidate for a later pack with its own back-test.
- **Re-targeting any live class.** That is `TP-477`, which this pack's questions feed.
- **A SessionStart banner line.** Draft 2 kept one firing place, at filing. Draft 3 adds plan time, which is where a lane decides its layer, and stops there. A banner line would fire on every session whether or not it touches a chained row. Re-raise it with the plan-time data.
- **Making the plan-time answer a gate.** The plan answers the questions in its own words, and nothing refuses a plan that skips them (`memory/gating-on-count-manufactures-findings.md`).
- **Deriving lineage from the site cells or from history.** Both were measured on 2026-10-08 and neither holds it (the Motivation's correction, and 0-B).
- **The `record` ref's behaviour.** Unchanged; Task 1 verifies the flag is a no-op there.

## Task 0 — Verify (try to kill this pack)

**0-A Back-test the per-surface alarm (draft 1). RAN 2026-10-07, second session: REFUTED.**
- Pre-registered before reading any surface, in the session's own words: W = 5 days trailing, D = 5 drained, fire when replacement / drained >= 1.0.
- Keys:
  - **k1** is the class (`§C`);
  - **k2** is the first path family of the site cell: top-level directory plus module stem. k2 left 1 of 315 live rows unkeyed.
- Series: first-parent, end-of-day snapshots of `task-packs/FORWARD_LEDGER.md` on `origin/main` from 2026-09-24, parsed with `tools/cc/generate_ledger_regions.py` the way `scripts/ledger_trend.py::state` does. Drained = backlog struck; replacement = filed minus churn, as `::window` defines them.
- Result, evaluated on 2026-10-04 to 2026-10-07:
  - **k1:** `§C0` fired on all four days (ratios 8.50, 4.80, 9.83, 1.95). It was the only class firing; 4 of 7 surface-days fired. That breaks the "more than half fire" refutation, and the firing class is the catch-all.
  - **k2:** no surface reached D on any day; the guard files drained 0 to 4 per window. That breaks the "guard surface does not fire under either key" refutation.
  - **Pooled guard files:** ratios of 9.0, 9.5, n/a and 2.2, against 7.67, 5.83, 8.46 and 1.87 for the rest. No separation in any 5-day window.
- Exit taken: draft 1's Tasks 2 and 3 were not built. W and D were not tuned. Re-raised to the operator, who asked for systems that catch symptom-chasing, which is this draft.

**0-B Back-test lineage at the merge level. NOT RUN 2026-10-08, third session: the oracle cannot see what it tests. Its exit is taken.**

- **Why it was not run.** The proxy counts a merge that strikes a row on a job and also files a row on that job. On this tree a fix lane's reviewer findings are filed by a later, separate filing lane:
  - the fix merges #131, #132 and #136 filed no row;
  - the rows attributed to them arrived in #128 and #139, which struck nothing (the Motivation's correction carries the ids and the driver).

  So the guard job would read a low spawn share because of how the work is staffed, not because of whether the work replicates itself. The refuting line would fire for a reason unrelated to the hypothesis.
- **No replacement proxy is proposed.** The id sets of eleven merges were read to find this. A merge-level or time-window proxy designed now would be designed after seeing the data, which the pre-registration rule forbids.
- **Exit taken,** as written below before any data was read:
  - Task 2 is built;
  - the chain advisory ships recording-only until 20 filed rows carry `--sibling-of`, then re-raises with that data;
  - the cluster advisory and the plan-time verb are unaffected.

The design as pre-registered, kept for the record:

The only lineage history that exists is implicit: a merged pull request that strikes rows on a job and also files new rows on the same job. This back-test asks whether that proxy separates the guard from the rest. If it does not, explicit lineage is still worth recording (it is forward and cheap), but its advisory thresholds have no support yet.

- **Oracle.** Every first-parent commit on `origin/main` from 2026-09-24 that touches `task-packs/FORWARD_LEDGER.md`:
  - `git log --first-parent --format=%H origin/main -- task-packs/FORWARD_LEDGER.md`;
  - parse the ledger at the commit's first parent and at the commit, with the same parsers as 0-A.
- **Definitions:**
  - **filed:** ids new at the commit;
  - **struck:** ids live before and struck after;
  - **fold-strike:** a struck row whose closing text contains "fold" (case-insensitive) is a fold, not a fix;
  - **job:** k2, with the guard pooled as one job. The guard job is `tools:_bash_patterns`, `tools:write_guard`, `tools:_speedbump`, `tools:_protected_zones`, `bench:guard_metamorphic`, `bench:guard_row_probe` and `bench:powershell_guard_rehearsal`.
  - **striking merge on job J:** it strikes at least one non-fold row on J.
  - **self-replacing on J:** a striking merge on J that also files at least one row on J.
  - **spawn share of J:** self-replacing merges ÷ striking merges.
- **Pre-registered (written here before the back-test has been run):**
  - the guard job has at least 4 striking merges and a spawn share of 0.5 or more;
  - the median spawn share over the other jobs with at least 3 striking merges is at most half the guard's.
- **Known in advance, stated so it is not mistaken for a result:** the four guard pull requests in the Motivation were seen while drafting. What has not been computed is the comparison with other jobs, and that half is the test.
- **Refuting result:** either line fails.
- **Exit:**
  - Build Task 2 anyway (recording is forward and costs one flag).
  - Ship Task 3's chain advisory recording-only, printing nothing, until 20 filed rows carry `--sibling-of`. Then re-raise with that data.
  - The standalone-cluster advisory does not depend on lineage and is unaffected.

**0-C Back-test the questions: in sample on the guard rows, and blind out of sample (amended 2026-10-08).**

Why two arms: the five questions were derived from the guard case. Routing the guard rows is therefore partly a test of where the questions came from, and the session that wrote them would be grading them. The second arm asks whether the questions *discriminate*, routing wrong-layer work away without routing everything away.

- **The answering rule, fixed here before any row is read:** a row **routes away** when question 2 is answered "predicts the effect" *and* question 3 "open input, someone else's", or when question 4 is answered "a slip would not produce this".
- **Arm 1, in sample.** The guard rows first seen 2026-10-02 to 2026-10-07, using 0-A's series and the guard-job site families. Shared with `TP-476` Task 0-A, which classifies the same rows by job: read once, record in both.
- **Arm 2, blind.** A control cluster outside the guard: the live `§C0` rows whose site family is `espalier/cli.py`, derived at execution time with 0-A's k2 key.
  - **The grader** is a fresh agent. It is given the five questions, the answering rule above, and the row ids of both clusters, interleaved, unlabeled and in shuffled order. It is not given this pack, the hypothesis, or which cluster an id belongs to.
  - It reads each row's headline sentence itself, one row at a time (0-D).
- **Refuting results, either one:**
  - in arm 1 (the grader's answers), fewer than three guard rows route away;
  - the control cluster's routed-away share is more than half the guard's. The questions then route everything away, and the advisories would be noise.
- **Exit:** drop Task 4's reviewer and principle edits, keep only the memory note, and re-raise with both arms' answers.
- Record both shares, the grader's per-row answers, and the date. The session's own reading for `TP-476` 0-A is recorded separately and does not count toward either arm.
- **Result, 2026-10-08: neither refuting line fires. Arm 1 routes 26 of 29 guard rows away (90%); the control routes 0 of 22 (0%). Task 4 is earned by this pack's rule, with a wording caveat below that is re-raised to the operator.**
  - **The grader** was a fresh agent given the five questions, the answering rule and the 51 ids, interleaved, unlabeled and shuffled with a fixed seed. It read each headline itself, one per call, through a printer keyed by id, and was not given this pack, the hypothesis or the arms. "Routes away" was re-derived from its raw answers, and agreed with its own flags on all 51.
  - **How the brief differed from this pack's text,** so the questions would not name the hypothesis: each question was given as its first sentence, rephrased plainly, without its follow-up guidance. That dropped question 1's two examples, question 3's "enumerating badness: move the check" line, and question 4's references to §16 and to `TP-476` C3.
  - **Arms.** Arm 1 is the 29 rows whose site family is the guard job and that were first seen 2026-10-02 to 2026-10-07 in the end-of-day series (14 snapshots from 2026-09-24; 22 still live), each read as its headline stood on its first day. Arm 2 is the 22 live §C0 rows whose site family is `espalier:cli`. 22 of arm 1's rows are also in `TP-476` 0-A's population.
  - **Per-row answers**, as q2/q3/q4 (P predicts the effect, O observes it; open or closed input; slip or no-slip; ? unclear). Question 1 was yes on all 51. Question 5 was unclear on 26 guard rows and no on the rest.
    - Arm 1: `DEF-1012` P/open/slip; `DEF-1013` P/open/slip; `DEF-1014` P/open/slip; `DEF-1015` P/open/slip; `DEF-1016` P/open/slip; `DEF-1025` P/open/slip; `DEF-1037` P/open/slip; `DEF-1038` P/open/slip; `DEF-1039` P/open/slip; `DEF-1041` P/open/slip; `DEF-1043` P/open/slip; `DEF-1044` P/open/slip; `DEF-1045` P/open/slip; `DEF-1070` P/open/slip; `DEF-1071` P/open/no-slip; `DEF-1123` P/open/slip; `DEF-1124` O/closed/slip; `DEF-1125` P/open/slip; `DEF-1131` P/open/no-slip; `DEF-1132` P/open/slip; `DEF-1151` P/open/slip; `DEF-1160` O/closed/slip; `DEF-1161` P/open/slip; `DEF-1162` P/open/no-slip; `DEF-1170` P/open/no-slip; `DEF-1171` P/open/no-slip; `DEF-1173` P/open/no-slip; `DEF-1174` P/open/slip; `DEF-1176` O/closed/slip.
    - Arm 2: `DEF-415h`, `DEF-623`, `DEF-736`, `DEF-901`, `DEF-929`, `DEF-930`, `DEF-945`, `DEF-989`, `DEF-993`, `DEF-996`, `DEF-1001`, `DEF-1005`, `DEF-1006`, `DEF-1023`, `DEF-1057`, `DEF-1062`, `DEF-1063`, `DEF-1064`, `DEF-1146`, `DEF-1187` O/closed/slip; `DEF-947` and `DEF-1192` ?/?/slip.
  - **What the result does not show** (read before Task 4 builds on it):
    - Question 1 does not discriminate (yes on every row), and question 5 cannot be answered from a headline.
    - The separation is carried by questions 2 and 3, which describe nearly any reader of shell text. The control, the CLI's own code, is an easy contrast: the arm shows the questions do not route everything away, not that they route away only wrong-layer work.
    - **The rule routes away rows that must stay predictive.** The arm-1 rows `TP-476` 0-A classes as speed bumps (`DEF-1038`, `DEF-1039`) route away on questions 2 and 3, that is "move the check", where `TP-476`'s table says no location layer can take them. The project-root deletes (`DEF-1162`, `DEF-1170`, `DEF-1173`) route away too. "Routes away" lumps "move the check" together with "a declared limit". Before Task 4 writes the questions as discipline, question 3 needs the exception `TP-476` carries: an effect that cannot be undone stays predicted, and question 4 (decision C3's contract) decides which spellings are work.
  - **Exit:** not taken (neither line fired). The caveat is re-raised for the operator to decide the wording.

**0-D Hygiene, binding on every task.**
- 0-C reads headlines in effect-words, one row's first sentence at a time, never full rows in a run. That binds the blind grader too. Its brief carries ids, never headlines; the coordinator never pastes guard text into a brief.
- No task builds a roster or generator of command spellings (`docs/CLASSIFIER_FALSE_POSITIVES.md`, "Variant generation").
- 0-B reads ids, closing-text fold markers and site cells only.

## Relevant memory

Recent pattern, measured 2026-10-07:
- The ledger-wide flow read convergent (0.80) while one job's fix lanes filed their own siblings.
- A per-surface flow alarm could not separate them, because filing bursts swamp flow.
- The repo's moves of a control were mostly consolidations, and defects kept arriving at the consolidated site.

| Entry | Where |
|---|---|
| Classify the surface before you measure it | `memory/classify-the-surface-before-measuring-it.md` |
| Gating on count manufactures findings | `memory/gating-on-count-manufactures-findings.md` |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| A fixed fail-open can move rather than close | `memory/a-fixed-fail-open-can-move-rather-than-close.md` |
| Fix the surface the reader consumes | `memory/fix-the-surface-the-reader-consumes.md` |
| A gate can be blind along a whole dimension of its input | `memory/a-gate-can-be-blind-along-a-whole-dimension.md` |
| Convergence review protocol | `memory/convergence-review-protocol.md` |

Resolved with:
- at draft 1: `python tools/cc/hooks/_recall.py "a fix whose layer cannot reach the goal; many attempts failing a new way"` and `python tools/cc/hooks/_recall.py "measure backlog flow replacement per drained row"`;
- at draft 2, the fourth and fifth rows: a history read of `memory/` for moves of a control.

Re-run them if the pack has been sitting.

## Implementation

### Task 1-A `ledger_trend.py` walks a merge-heavy ref first-parent *(fix shape, untested)*

**Defect (measured 2026-10-07).** `python scripts/ledger_trend.py --ref origin/main --since 2026-10-04` printed "the steps' struck column sums to 199 = backlog 46 + churn struck in a later step 9" with no warning. `scripts/ledger_trend.py::snapshots` runs `git log <ref> -- <path>` without `--first-parent`, so consecutive snapshots alternate between parallel lanes and the same rows strike again and again. The window lines (first snapshot against last) are sound.

```python target=scripts/ledger_trend.py
    run = _git(repo, "log", "--first-parent", "--format=%H %ad", "--date=short", ref, "--", path)
```

Second part: `scripts/ledger_trend.py::render` checks the reconciliation identity it prints, and prints `WARN` when the identity fails, as the window identity already does.

- **Refuted if:** `git log --first-parent record -- task-packs/FORWARD_LEDGER.md` differs from the plain log on a machine holding the `record` ref (that ref is meant to be linear). Then gate the flag to refs other than the record ref.
- **Earn the red:** build a two-lane fixture repo in a test, where a row is struck on one lane and a later-dated commit on the other lane still carries it live. The per-step struck sum must equal backlog plus churn-struck-later. The test must be red against the current `snapshots`.

### Task 2-A Record lineage at filing *(fix shape, untested; refuted below)*

- `tools/cc/ledger_row.py::file_row` gains `--sibling-of <id>` (repeatable). Each named id must exist in the ledger, live or struck; an unknown id is refused, because a typo would silently cut a chain.
- **Where it is stored:** a top-level `_lineage` map in `task-packs/LEDGER_PROBES.json`, of the form `{child_id: [parent_id, ...]}`. `file_row` writes it.
  - **`::strike` and `::repin` never remove an entry from it.** Strike deletes the struck row's probe entry (`data["probes"] = [p for p in ... if p["id"] not in ids]`, read 2026-10-07), so lineage kept inside a probe entry would vanish with its parent and cut every chain through it.
  - The ledger's markdown grammar is unchanged. Lineage is owned by its one writer rather than parsed out of a cell, which is the re-targeting this pack argues for, applied to itself.
- **Refuted if:**
  - a reader of the probe file refuses an unknown top-level key. Check `tools/cc/check_ledger_probes.py`, `::_load_probes`, the regions converger, and `tools/cc/record_merge.py`.
  - or two lanes adding `_lineage` entries cannot be merged by the path the probe file already merges by.
  - Then the fallback is an append-only `task-packs/LEDGER_LINEAGE.json`, written only by `ledger_row.py`. It is a new record file, with the record-file obligations that brings (the conflict-marker advisory, the record merge).
- **Earn the red:**
  - file a row with `--sibling-of`, strike the parent, then read the chain from the child. It must survive. Mutation: store the parent inside the probe entry, which the strike then deletes.
  - an unknown parent id is refused. Mutation: drop the existence check.

**The hop from finder to filer** *(prose; untested)*. A flag only the filer can pass records nothing when the filer is a later session reading prose. On this tree, measured in the Motivation's correction, every sibling attributed to the guard lanes was filed by a separate filing lane.
- `.claude/commands/handoff.md` step 7, where the `## Notes to next session` are written: an unfiled finding a lane's review found as a sibling of a row the lane worked on is written with `(sibling of DEF-N)`. The filing lane copies that id into `--sibling-of`.
- The two reviewer bodies' instruction (Task 4-A) asks for the same words in the finding itself, so the note can copy it rather than reconstruct it.
- **Refuted if:** after landing, a filing lane files a row whose source note names a parent, without the flag. Then the instruction is not reaching the filer. Make `ledger_row.py file` itself print an advisory when the new row's text cites a struck id and no `--sibling-of` was passed. Decide from the first ten filings.

### Task 3-A The two filing advisories and the plan-time verb *(fix shape, untested; thresholds are first guesses with a pre-registered review)*

The two filing advisories print to stderr, exit 0, and never refuse. The plan-time verb prints its report to stdout, because its output is the content a planning session reads; it also exits 0. On a tree whose ledger has no lineage yet, they stay silent and say why once (`docs/CONVENTIONS.md`, "Fail-open with voice").

- **The chain advisory,** in `file_row` when `--sibling-of` is given:
  - depth = 1 + the parent's depth, read from `_lineage`; fan-out = the parent's children, counting the new row;
  - fire when depth >= 2 (a sibling of a sibling) or fan-out >= 3;
  - print the chain by id, the job, and the five questions.
- **The standalone-cluster advisory,** in `file_row` when `--section` is `C0`:
  - compute the new row's site family (the k2 key of 0-A) and count the live `§C0` rows with the same family in the current ledger;
  - fire at 5 or more, and suggest `ledger_row.py class` with the five questions.
  - Today this would fire for five k2 families (k2 keys by module, so the guard is three of them; corrected 2026-10-08 from "three families"):
    - the three guard modules (7 rows each on `_bash_patterns`, `write_guard` and `_speedbump`);
    - `espalier/cli.py` (20);
    - `scripts/check_handoff_landing.py` (6).

    Driver: 0-A's series, live `§C0` rows by k2.
- **The thresholds are first guesses, and their review is pre-registered here:**
  - after the first 20 rows filed with `--sibling-of`, and the first 20 `§C0` filings after landing, count how often each advisory fired;
  - fired on more than half: the threshold is noise; re-raise;
  - never fired: report it, and do not lower the threshold to make it speak.
  - **The cluster advisory starts with a backlog** (added 2026-10-08, before any data). Five k2 families were at or over 5 when the counts above were measured (2026-10-07); re-derive them on the day it lands. Report fires on families already over the threshold at landing separately from fires on the rest, and judge the more-than-half noise line on the rest. A family over the threshold at landing is a class waiting to be opened; that is a finding for the operator, not noise in the advisory.
- **The plan-time verb, `ledger_row.py lineage <id>`** *(fix shape, untested)*.
  - It is read-only, writes nothing and exits 0. It prints:
    - the row's chain (its parents to the root, and its parent's children, from `_lineage`);
    - its k2 site family and that family's live `§C0` count;
    - the five questions, when the chain is two deep or more, or the family is at the cluster threshold.

    On a row with no lineage and no cluster, it prints one line saying so.
  - `.claude/commands/implement-task.md` step 1 (restate the task) and `.claude/commands/implement-pack.md` step 0-A (pack-artifact review) gain one instruction: for each ledger row id the work names, run the verb; when it prints the questions, the plan answers them before proposing a fix. Then run `python scripts/sync_claude_mirrors.py`.
  - **Refuted if:** the verb's output on a row in a live chain is not read by the planning session. Check the first three lanes after landing for a plan that names a chained row and does not answer. Then the instruction is in the wrong step; re-raise with where the plan was actually formed.
  - **Earn the red:** a fixture with a three-row chain; `lineage` on the leaf prints the chain root and the questions. Mutation: read the immediate parent only.
- **Refuted if:** computing the site family and the count adds more than a second to `file_row` on this tree. It reads the current ledger only, with no history walk, so it is not expected to.
- **Earn the red:**
  - a fixture with a parent and a grandchild fires the chain advisory; mutation: compute depth from the immediate parent only;
  - a fixture with five same-family `§C0` rows fires the cluster advisory; mutation: key on the class instead of the family, which counts every standalone row.

### Task 4-A The questions as discipline *(prose; earned by 0-C)*

**The five questions**, asked before the class question:
1. **State the job without naming the mechanism.** "Harness files do not change mid-session without the operator knowing", not "the reader must handle form X". If the job can only be written in the mechanism's own words (spellings, shapes, anchors, row forms), the fix is aimed at the mechanism, not the job.
2. **Does the fix observe the effect, or predict it from a representation?**
3. **Is the input closed and ours, or open and someone else's?** Open input plus prediction is enumerating badness: move the check. Closed input we own: own the producer and make the consumer strict. **Except where the effect cannot be undone** (a delete, a push, a release, a secret read that leaves nothing to compare): no after-the-fact layer can help there, so the prediction stays, and question 4, asked once for the whole job, decides which forms are work (`TP-476` decision C3's coverage contract). Without this exception the questions say "move the check" for jobs no layer can take (added 2026-10-08, the operator's decision, after 0-C's blind arm routed the speed-bump and project-root delete rows away).
4. **Would a slip plausibly produce this instance?** (§16) If not, it is a declared limit, not work. Where a whole job must stay in a predicting layer, ask this once for the job, not once per row. That answer is a coverage contract, which `TP-476` decision C3 writes for the guard's residual parser.
5. **Was this already moved once, and are defects arriving at the new site?** Then the move was consolidation, and the next one is re-targeting.

**Where the questions go:**
- **`memory/check-the-layer-before-the-class.md`.** Contents:
  - the class this pack names: a fix whose layer cannot reach its goal passes every gate;
  - the two kinds of move, with the instances from the Motivation;
  - the five questions;
  - the tells: a chain of siblings, a standalone cluster, recurrence at a consolidated site;
  - the counter-warning: a move can relocate a defect rather than close it. Link `memory/a-fixed-fail-open-can-move-rather-than-close.md`.
  - the worked instance: `TP-476`;
  - a cross-link to `memory/fix-the-class-not-the-instance.md`, which this note precedes.
- **Root `CLAUDE.md` Core Rule 12:** one clause before the class question: "first ask whether the layer can reach the goal (the five questions); a chain of siblings on one job is the tell". Rule 12's sole home stays the memory note.
- **The principle: a new `## 20.` in `docs/STANDING_PRINCIPLES.md`.** The operator chose §20 over a paragraph under §15 on 2026-10-08; on that day §19 was the last section. It names re-targeting beside consolidation (§14, §18), with the prior art.
  - §20 is earned the same way as the rest of this task: if 0-C refutes, the principle is not written, and the choice of §20 stands for whenever it is. Since draft 3 that means both arms of 0-C, the blind one included.
  - **What §20 may cite as evidence.** Until `TP-476` wave C has struck rows, and those strikes have not been followed by a new stream of rows at wave A's layer, §20 names `TP-476` as the instance it proposes, *not* as one it proves. The re-targeted classes named in the Motivation (`§C69`, `§C67`, `§C55`) carry the caveat written there: their titles were written once the fix shape was known.
  - Check `docs/STANDING_PRINCIPLES.aliases.md` and the SessionStart standing-principles index first, because both pin the principle set.
  - Check the record-surface list (`tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS`) before editing any doc (Core Rule 13).
- **`.claude/agents/failure-mode-reviewer.md` and `.claude/agents/code-reviewer.md`** each gain one question and one instruction:
  - the question: "is this fix in a layer that can reach its goal, or one more instance in a layer that cannot?";
  - the instruction: "a finding that is a sibling of the row this lane fixes says so in the words `(sibling of DEF-N)`, so the handoff's note and the filer can copy the id into `--sibling-of`".
  - Then run `python scripts/sync_claude_mirrors.py`.
- **`tools/cc/ledger_row.py::new_class`** prints the five questions after it opens a class, so they are asked at class formation.

## Affected symbols

`/scope-check` keys on bare names. `main` and `render` match more than a thousand unrelated sites across the tree, so its gap list for this pack is name collisions, checked at authoring.

The real referrers of the script are derived by `grep -rln ledger_trend tests scripts tools espalier`. On 2026-10-07 that listed six files besides the script itself: its own tests, `tests/conftest.py`, a surface-expectation table under `tests/`, `scripts/ledger_rebuild_assemble.py`, and `tools/cc/generate_ledger_regions.py` with its vendored twin. Read each before changing `snapshots`. Draft 1's move of the flow core into a new `tools/cc/_ledger_flow.py` is withdrawn with the alarm, because the advisories read the current ledger and `_lineage`, not history.

### Changed-semantics
- `scripts/ledger_trend.py::snapshots`
- `scripts/ledger_trend.py::render`
- `tools/cc/ledger_row.py::file_row`
- `tools/cc/ledger_row.py::new_class`
- `tools/cc/ledger_row.py::main`

### Renamed
- (none -- no symbol is renamed)

### Added-paths
- `memory/check-the-layer-before-the-class.md`

### Removed-paths
- None.

## Reach

This pack builds an instrument and a set of questions. It closes no defect class, so it claims no member closed. The one row-shaped item:

| Item | Status | Evidence |
|---|---|---|
| the unchecked per-step identity in `ledger_trend.py` (unfiled candidate) | **CLOSED by Task 1** | the two-lane fixture test, red before the fix |

## Pass criteria

- Task 0's records are in this pack: 0-A as written above; 0-B's not-run record and its exit; 0-C's two arms with the grader's answers, both shares and, where a refuting result held, the exit taken.
- `python tools/cc/ledger_row.py lineage <id>` on a fixture chain prints the chain root and the five questions, and exits 0 having written nothing (`git status` unchanged).
- `.claude/commands/implement-task.md`, `.claude/commands/implement-pack.md` and `.claude/commands/handoff.md` carry the plan-time and parent-note instructions, and their mirrors are in sync.
- `python scripts/ledger_trend.py --ref origin/main --since 2026-10-04` prints no failed identity, and its window lines are unchanged in value from the pre-fix run.
- `python tools/cc/ledger_row.py file --dry-run --sibling-of <id> ...` on a fixture chain prints the chain advisory and exits 0. On a fixture with five same-family `§C0` rows, `--section C0` prints the cluster advisory and exits 0.
- A chain survives the strike of its middle row (Task 2-A's red test).
- No assertion in the ledger tool tests may be weakened to make room. Each new test was seen red against its named mutation.
- `python scripts/sync_vendor_cc.py` and `python scripts/sync_claude_mirrors.py` leave the tree clean.
- The tier `python scripts/proof_tier.py --base origin/main` prints, run as the lane conventions say.

## Files touched

- **New:**
  - `memory/check-the-layer-before-the-class.md`;
  - tests for lineage and the advisories (names follow `tests/` conventions).
- **Modified:**
  - `scripts/ledger_trend.py`;
  - `tools/cc/ledger_row.py` and its vendored mirror;
  - `task-packs/LEDGER_PROBES.json` (only through `ledger_row.py`, as rows are filed);
  - root `CLAUDE.md` (Core Rule 12);
  - `docs/STANDING_PRINCIPLES.md` (the new §20), with `docs/STANDING_PRINCIPLES.aliases.md` and the SessionStart standing-principles index pins;
  - `.claude/agents/failure-mode-reviewer.md` and `.claude/agents/code-reviewer.md`, and their mirrors;
  - `.claude/commands/implement-task.md` (step 1), `.claude/commands/implement-pack.md` (step 0-A) and `.claude/commands/handoff.md` (step 7), and their mirrors;
  - `CHANGELOG.md`.
- **Unmodified on purpose:**
  - `task-packs/FORWARD_LEDGER.md`'s grammar;
  - `tools/cc/generate_ledger_regions.py`. Lineage lives beside the ledger, not in a cell.

## Sub-task ordering

1. Task 0: 0-C's two arms; the session's own reading of the guard rows is shared with `TP-476` 0-A. 0-A is done; 0-B was not run (its exit is taken). Checkpoint: the records written here; stop where refuted.
2. Task 1-A. Checkpoint: the fixture test red, then green; the real run's identity clean.
3. Task 2-A, with the finder-to-filer note in `handoff.md`. Checkpoint: the strike-survival test.
4. Task 3-A, which depends on 2-A: the two filing advisories, then the `lineage` verb and the plan-time instruction. Checkpoint: the three advisory tests; the mirrors clean.
5. Task 4-A, which depends on 0-C. Checkpoint: the mirrors clean; the doc contracts green.
   - **Coordination** (2026-10-08): the adopter-readiness packs edit `.claude/commands/implement-task.md` in a declared order (`TP-470` 3-A first, then `TP-471` 3-A to 3-C, `TP-473` 1-B last). This pack's one instruction in step 1 is a separate sentence, not a rewrite. Land it between their lanes, and say in the claim which step it touches.
   - `task-packs/LEDGER_PROBES.json` is written by five packs through `ledger_row.py`, and Task 2 changes that writer. Land Task 2 between other lanes' strikes, never during one.
6. Task 5, red-team: both reviewers. Ask for:
   - the chain the store loses;
   - the sibling that is filed without the flag, so the chain never forms (the advisory's blind spot);
   - the advisory that fires on every filing;
   - the question a hurried filer answers in the mechanism's own words.
7. Task 6: proof tier, landing stanza, ledger strike of the pack's §3 row.

## Estimated effort

| Task | Budget |
|---|---|
| 0 (0-C, two arms) | 1.5 h |
| 1 | 1 h |
| 2 | 1.5 h |
| 3 (two advisories, the verb, the plan-time instruction) | 2 h |
| 4 | 1 h |
| Red-team | 1 h |
| Verify and land | 1 h |
| **Total** | **about 9 h**, one lane |

**Most likely to be wrong:**
- that filers use `--sibling-of`. A flag nobody passes records nothing. The reviewer instruction and the handoff's note are the push, across a hop between sessions; the red-team should attack it, and Task 2-A's refutation says what moves next;
- that the planning session reads the verb's output before it plans (Task 3-A's refutation);
- that the k2 site family is a stable job key: one live row was unkeyed of 315, but one job can span several families, as the guard does;
- the thresholds, which are guesses with a pre-registered review.

## Landing

- State: DRAFT
- Task 0-A (draft 1's alarm): REFUTED 2026-10-07; see Task 0.
- Task 0-B (merge-level lineage): NOT RUN 2026-10-08, its oracle cannot see lineage on this tree; its exit taken. See Task 0.
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
