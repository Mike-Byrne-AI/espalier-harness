# Recall keys on the hazard, not the task

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "Recall keys on the hazard, not the task"

`/recall` and the engine behind it rank by vocabulary overlap. A lane's task
text carries the GOAL's vocabulary ("scripts/ledger_row.py strike and file");
the catalog entry that would have saved the lane carries the HAZARD's
("escaped pipes silently drop rows"). They share almost no words.

## Measured, 2026-09-06

Seven queries -- the batch task text, five execution-plan step texts, the
operator's prompt -- were fed to `tools/cc/hooks/_recall.py`. They recalled
**none** of the four entries the two red teams then found applicable
(escaped pipes in a markdown table; a new test file defaulting to `unit`;
`python3 ` in an operator doc; a hand-kept inventory). Four queries written
with the hazard words recalled **all four**. The two largest docs in the
corpus ("Convergence ledger", "Task pack authoring") topped nearly every
task-shaped query instead.

Telemetry for the same day: 62 recall events, 30 of them SessionStart
orientation, 29 my own pull-side queries, **3** PostToolUse pushes across
hundreds of tool calls -- the push side reads `file_path` from the tool
input, and a heredoc edit through Bash carries none.

## How to apply

1. Before writing, ask `/recall` about the artifact's IDIOM or the failure
   SHAPE: the table format you parse, the kind of file you create, the
   interpreter name you type into a doc, the list you extend by hand.
2. Do not expect a task-title query to find its entry, and do not read what
   it does return as a signal. Until 2026-09-12 the first line was the
   corpus's two largest notes (the convergence ledger, the pack-authoring
   note); the pull ranker no longer indexes either
   (`PULL_EXCLUDED_MEMORY_NOTES` in `tools/cc/hooks/_recall.py`), and the
   measured point is that removing them did NOT make the entry appear: the
   row's three levers (exclude the aggregates, raise the length norm, drop the
   tie window) were each driven through the eval's corpus-injection path and
   none moved the task arm's control@1 off 1 of 29 (union@any 3 of 29 over 16
   queries), so the gap is vocabulary, not ranking, and `DEF-699` was struck
   on that measurement. Instrumented 2026-09-11: the task arm of
   `scripts/recall_eval.py` (`_TASK_ARM` in `tests/test_recall.py`) scored
   1 of 7 on both paths at 310 documents, the one hit being the row whose
   claim names its entry's title; the number prints on every run, and the
   arm grows one row per lane at handoff (29 labels after the recall lane,
   each filed row also in `_TASK_ARM_FILED`). Read that rate as an optimistic
   bound, not a measurement:
   three of the seven labels are entries a hazard-word recall surfaced and a
   lane's review then used, so they are ranker-reachable by construction and
   an applicable entry no phrasing can reach is not in the arm at all. The arm
   says so per row; the number without that caveat overstates the front door.
3. The mechanical net for when you forget: `_reinject.py`'s once-per-session
   pointer rows fire on the EVENT (a new file under `tests/` or `scripts/`,
   `python3 ` written into an operator doc, a parser opened over the ledger),
   and `post_write_check` now derives the written paths from a Bash command
   so a heredoc edit reaches them.
4. A red test outside the lane is a ledger key too: grep the forward ledger
   for the test's name before fixing it. Measured 2026-09-10: DEF-719 had
   described the handoff dry-run test's cap assumption two days earlier; the
   fix landed under a tier red before the row was read, and only its flipped
   probe surfaced it afterwards. The strike text would have been the fix's
   own receipt had the name been looked up first.
   **And before renaming or deleting a symbol, not only before fixing one
   (three instances by 2026-09-20).** The recall corpus indexes `memory/` and
   `docs/`, never `task-packs/FORWARD_LEDGER.md`, so the ledger is a grep, not
   a recall. 2026-09-20 at 1-C: the row tool's MIXED fix already had a live
   row (`DEF-776`) the code-reviewer lane found, not the author. 2026-09-20
   at 1-D: renaming `test_every_deferred_pack_is_ledger_tracked` after a repo
   grep that skipped the ledger left four ledger sites citing the old name and
   flipped `DEF-646`'s probe, which AST-searched for that exact name, to
   STRIKE_CANDIDATE for the wrong reason (symbol gone, not defect fixed); the
   failure-mode lane caught it. Two rules: `grep task-packs/FORWARD_LEDGER.md`
   for the symbol before a fix, a rename or a delete; and key a probe on the
   claim (a population, a predicate over the tree), never on a function's
   name, because a name-keyed probe flips on every rename.

**Retrieval is not application (2026-09-08, 2026-09-14).** Twice a lane
recalled the ReDoS rule minutes before shipping the shape it forbids: the entry
was read and never turned into a check the diff could fail. The remedy is the
constraint line: for each recalled entry, write the one-line constraint it
imposes on THIS change before the first edit, carry it into the plan step's
`constraints:` field, and let the reviewer compare the diff against it
(`/implement-task` step 1 says so). A recall hit that produced no such line was
not applied, whatever the transcript says.

Related: [[reviews-before-the-one-full-run]] (the other half of the same
day's lesson: put the cheap check where the work actually happens).

5. When the hazard is a symbol name, grep the catalogue headings too.
   Measured 2026-09-12 (group 6): the task text recalled none of the five
   entries the hazard words found (the chmod-444 decision, the two parity
   entries, the derive-the-list principle, the hardlink backstop), and the
   entry that mattered most for a hand-rolled `os.open` -- "POSIX-only
   `os.O_*` flags need `getattr` guards for Windows" -- was found by neither
   the task text nor any hazard query, only by a heading grep over
   `docs/SHARP_EDGES.md`. A heading whose tokens are symbols (`os.O_*`,
   `getattr`) is outside the retriever's vocabulary; the heading grep is the
   second oracle whenever the hazard word is code.
