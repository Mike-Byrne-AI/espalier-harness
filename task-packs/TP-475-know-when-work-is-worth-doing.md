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
  - **This is draft 2.** It keeps Task 1, and replaces the alarm with lineage recorded at filing and two advisories keyed on it.
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
2. **Task 2** — lineage at filing: `ledger_row.py file --sibling-of <id>` records that the new row was found as a sibling of an existing row, in a store that survives strikes.
3. **Task 3** — the two advisories where the next member is born, both advice and never a refusal:
   - **a chain advisory:** at `file --sibling-of`, when the new row makes a chain two deep, or the parent's third sibling;
   - **a standalone-cluster advisory:** at `file --section C0`, when the row's site family already holds five or more live standalone rows.

   Both print the five questions of Task 4.
4. **Task 4** — the questions as discipline:
   - a `memory/` note with the five questions, the two kinds of move, and the counter-warning;
   - a clause in Core Rule 12;
   - a principle (a new §20, or a paragraph under §15: the operator decides);
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
- **A SessionStart banner line.** One firing place first.
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

**0-B Back-test lineage at the merge level (new; run before Task 2).**

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

**0-C Back-test the questions on the guard rows.**
- Take the guard rows first seen 2026-10-02 to 2026-10-07, using 0-A's series and the guard-job site families.
- Answer the five questions of Task 4 from each row's **headline sentence only**.
- Count the rows the questions would have routed away from another fix in the same layer.
- **Share the reading with `TP-476` Task 0-A,** which classifies the same rows by job. Read once, record in both.
- **Refuting result:** fewer than three rows would route differently.
- **Exit:** drop Task 4's reviewer and principle edits, and keep only the memory note.

**0-D Hygiene, binding on every task.**
- 0-C reads headlines in effect-words, one row's first sentence at a time, never full rows in a run.
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

### Task 3-A The two advisories *(fix shape, untested; thresholds are first guesses with a pre-registered review)*

Both print to stderr, exit 0, and never refuse. On a tree whose ledger has no lineage yet, they stay silent and say why once (`docs/CONVENTIONS.md`, "Fail-open with voice").

- **The chain advisory,** in `file_row` when `--sibling-of` is given:
  - depth = 1 + the parent's depth, read from `_lineage`; fan-out = the parent's children, counting the new row;
  - fire when depth >= 2 (a sibling of a sibling) or fan-out >= 3;
  - print the chain by id, the job, and the five questions.
- **The standalone-cluster advisory,** in `file_row` when `--section` is `C0`:
  - compute the new row's site family (the k2 key of 0-A) and count the live `§C0` rows with the same family in the current ledger;
  - fire at 5 or more, and suggest `ledger_row.py class` with the five questions.
  - Today this would fire for three families:
    - the guard files (7 rows each on `_bash_patterns`, `write_guard` and `_speedbump`);
    - `espalier/cli.py` (20);
    - `scripts/check_handoff_landing.py` (6).

    Driver: 0-A's series, live `§C0` rows by k2.
- **The thresholds are first guesses, and their review is pre-registered here:**
  - after the first 20 rows filed with `--sibling-of`, and the first 20 `§C0` filings after landing, count how often each advisory fired;
  - fired on more than half: the threshold is noise; re-raise;
  - never fired: report it, and do not lower the threshold to make it speak.
- **Refuted if:** computing the site family and the count adds more than a second to `file_row` on this tree. It reads the current ledger only, with no history walk, so it is not expected to.
- **Earn the red:**
  - a fixture with a parent and a grandchild fires the chain advisory; mutation: compute depth from the immediate parent only;
  - a fixture with five same-family `§C0` rows fires the cluster advisory; mutation: key on the class instead of the family, which counts every standalone row.

### Task 4-A The questions as discipline *(prose; earned by 0-C)*

**The five questions**, asked before the class question:
1. **State the job without naming the mechanism.** "Harness files do not change mid-session without the operator knowing", not "the reader must handle form X". If the job can only be written in the mechanism's own words (spellings, shapes, anchors, row forms), the fix is aimed at the mechanism, not the job.
2. **Does the fix observe the effect, or predict it from a representation?**
3. **Is the input closed and ours, or open and someone else's?** Open input plus prediction is enumerating badness: move the check. Closed input we own: own the producer and make the consumer strict.
4. **Would a slip plausibly produce this instance?** (§16) If not, it is a declared limit, not work.
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
- **The principle:** a new `## 20.` in `docs/STANDING_PRINCIPLES.md`, or a paragraph under §15 (the operator decides). It names re-targeting beside consolidation (§14, §18), with the prior art.
  - Check `docs/STANDING_PRINCIPLES.aliases.md` and the SessionStart standing-principles index first, because both pin the principle set.
  - Check the record-surface list (`tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS`) before editing any doc (Core Rule 13).
- **`.claude/agents/failure-mode-reviewer.md` and `.claude/agents/code-reviewer.md`** each gain one question and one instruction:
  - the question: "is this fix in a layer that can reach its goal, or one more instance in a layer that cannot?";
  - the instruction: "a finding that is a sibling of the row this lane fixes says so, so the filer passes `--sibling-of`".
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

- Task 0's records are in this pack: 0-A as written above; 0-B and 0-C with their numbers and, where a refuting result held, the exit taken.
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
  - `docs/STANDING_PRINCIPLES.md` (and its aliases and index pins if a §20);
  - `.claude/agents/failure-mode-reviewer.md` and `.claude/agents/code-reviewer.md`, and their mirrors;
  - `CHANGELOG.md`.
- **Unmodified on purpose:**
  - `task-packs/FORWARD_LEDGER.md`'s grammar;
  - `tools/cc/generate_ledger_regions.py`. Lineage lives beside the ledger, not in a cell.

## Sub-task ordering

1. Task 0: 0-B, then 0-C, read together with `TP-476` 0-A. 0-A is done. Checkpoint: the records written here; stop where refuted.
2. Task 1-A. Checkpoint: the fixture test red, then green; the real run's identity clean.
3. Task 2-A. Checkpoint: the strike-survival test.
4. Task 3-A, which depends on 2-A. Checkpoint: the two advisory tests.
5. Task 4-A, which depends on 0-C. Checkpoint: the mirrors clean; the doc contracts green.
6. Task 5, red-team: both reviewers. Ask for:
   - the chain the store loses;
   - the sibling that is filed without the flag, so the chain never forms (the advisory's blind spot);
   - the advisory that fires on every filing;
   - the question a hurried filer answers in the mechanism's own words.
7. Task 6: proof tier, landing stanza, ledger strike of the pack's §3 row.

## Estimated effort

| Task | Budget |
|---|---|
| 0 (0-B, 0-C) | 1.5 h |
| 1 | 1 h |
| 2 | 1.5 h |
| 3 | 1.5 h |
| 4 | 1 h |
| Red-team | 1 h |
| Verify and land | 1 h |
| **Total** | **about 8.5 h**, one lane |

**Most likely to be wrong:**
- that filers use `--sibling-of`. A flag nobody passes records nothing; the reviewer instruction is the only push, and the red-team should attack it;
- that the k2 site family is a stable job key: one live row was unkeyed of 315, but one job can span several families, as the guard does;
- the thresholds, which are guesses with a pre-registered review.

## Landing

- State: DRAFT
- Task 0-A (draft 1's alarm): REFUTED 2026-10-07; see Task 0.
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
