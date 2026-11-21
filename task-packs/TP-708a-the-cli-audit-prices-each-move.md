# TP-708a — The cli audit prices each move before anything moves

## Status

- Version target: self-host only. Nothing here deploys: `scripts/` is not copied by `init`, and
  no file under `espalier/`, `tools/cc/` or `.claude/` changes.
- Type: audit plus self-host tooling. Wave 0 of the roadmap
  `task-packs/TP-708-the-cli-is-mapped-before-it-moves.md`.
- **Kind: PACK.** Its Task 0 can end the refactor waves, though not this wave: the census and the
  Audit result land either way, since they are the evidence the operator rules on at Gate A.
- **"Read-only", as this pack reads it (flagged for the operator):** no change to product code.
  `espalier/cli.py`, `espalier/doctor.py` and every other file under `espalier/`, `tools/cc/` and
  `.claude/` stay byte-identical. The lane does add self-host tooling and records: one census
  script and its test, one entry in the script-name pin, this file's `## Audit result`, and any
  ledger row the patch census confirms (Task 4). If the operator meant "no tracked file at all",
  the census runs from the scratchpad, the result goes as mail, and Tasks 1 and 9 shrink to that.
  This pack recommends the reading above: a census kept out of the tree cannot re-derive the
  baseline after each refactor wave.
- Authored 2026-11-17 by the dispatcher seat `air` (a drafter fork) on the operator's ruling of
  call `20261115T192546Z-air-35136c` (ack `20261117T212142Z-air-581de4`): authored now as a
  roadmap; wave 0, the read-only audit, to the next free worker slot; scope `espalier/cli.py`
  with its `espalier/doctor.py` boundary read inside the audit and doctor.py's own refactor out;
  the metric a maintainer cost the audit pre-registers, never a line count.
- **Reviewed at authoring and folded** (2026-11-17, each in its own context): the reasoning review
  (checklist v1, failure-mode reviewer, REQUEST CHANGES) and the architecture review (13
  findings); Landing holds the counts. Figures are tagged `[verified]` (re-run against the tree or
  GitHub) or `[probable]` (an approximate read whose method is named).
- Standing from ack `df6595` (2026-11-15): no seat starts cli.py refactor work before the pack's
  refactor waves are approved. The lanes in cli.py now go on as assigned: win's `DEF-985`
  (`lane/an-engine-spawn-that-never-started-says-so`) and air-work's `DEF-5118`
  (`lane/a-bad-entry-outside-pretooluse-leaves-the-gates-wired`). So every read is pinned to one
  commit, **P**, named and committed at step 1 (Sub-task ordering), never to the clock.
- Ledger: `DEF-4123` is the row. Wave 0 strikes nothing and edits no existing row.

## Motivation

`DEF-4123` gives the premise: a lane that changes one command reads a file of more than 17,000
lines, and "collides with the next lane in it". The operator reopened the split on maintainer cost
(ruling 2 on call `cc862b`, ack `df6595`). The figures below were read at authoring at `17d83e0`
(2026-11-17), and the executor re-derives every one at P. A collision figure carries its window
and the number of cli.py PRs in it, because the same instrument over a different window can flip
the verdict.

| Figure at `17d83e0` | Value | Window and command |
|---|---|---|
| Lines | 17,790 [verified] | `wc -l espalier/cli.py` |
| Top-level functions / public / classes / `cmd_*` | 310 / 64 / 13 / 36 [verified] | an `ast.parse` read of `module.body`: `FunctionDef`/`ClassDef`, public = no leading `_` |
| Largest functions (lines) | `::cmd_upgrade` 929, `::build_parser` 890, `::deploy_harness` 344, `::cmd_init` 337, `::cmd_scope_check` 311, `::cmd_scan` 304, `::_print_init_summary` 293, `::_detect_python_command` 284 [verified] | the same read, `end_lineno - lineno + 1` |
| Conflicts on replay, cli.py | **1 of 511** (`42cd25d4c`, 2026-10-01) [verified] | every merge reachable from `17d83e0` whose subject is not `Merge pull request`, replayed with `git merge-tree --write-tree --name-only --no-messages <m>^1 <m>^2` (rc 1 is a conflict) |
| Conflicts on replay, any file | 150 of the 511 [verified], so the instrument does see conflicts | the same replay |
| Concurrent PR pairs sharing cli.py, 30 days | 3 (669/668, 589/588, 430/429) [probable] | 30 days to `17d83e0`, 35 cli.py PRs; `gh` `createdAt`/`mergedAt` open windows (the reasoning review's read) |
| Concurrent PR pairs sharing cli.py, last 40 PRs | 0 of 30 concurrent pairs (14 shared some file) [verified] | `--prs 40` = #673 to #713, about 44 hours, **2 cli.py PRs** (#680, #686); `scripts/lane_overlap_census.py --prs 40 --json` |
| Cross-seat lane pairs whose claim windows overlap on cli.py | 18, all cross-seat, over 70 lanes, median claim to release 2.4 h [probable] | 2026-10-06 to `17d83e0`; the mail refs' claims and releases (the reasoning review's read). This is the opportunity: 18 chances, 1 conflict and 1 hold |
| Catch-up conflicts, any file, last 40 PRs | 0 of 21 catch-ups [verified] | the same 44 h; `python3 scripts/merge_cost_census.py --prs 40 catch-ups conflicts --json` |
| Dispatcher holds over a cli.py overlap | 1 (`20261117T191812Z-air-479698`) [verified] | the whole mail record. A lower bound: `re.paths` is the sender's own declaration |
| Lines a lane reads in cli.py functions | median 337, max 2,784, over 36 lanes [verified]; median 345 over 35 hours later as the window slid | the top-level definitions each lane's `git diff -U0 <merge-base> <m>^2 -- espalier/cli.py` hunks fall in, lengths summed at the merge-base. `::cmd_upgrade` is 30.4% of the summed read, `::build_parser` 17.0% |

Three facts about the record:

- **The replayed merges are lane-side merges** (catch-ups and stacks onto a lane, the second-parent
  side of a PR), not first-parent commits: 701 of 704 first-parent commits are PR merges. The
  record starts 2026-09-24, so "the whole record" is about 54 days, not a longer history
  [verified].
- **The up-to-date rule is off** (branch protection reads `strict: false`) [verified]. So a
  catch-up that carries cli.py changes is main's churn, unless a conflict or a hold forced it.
  The 54 such catch-ups in 30 days [verified] are context, not a cost. The conflicts and holds
  are counted on their own rows.
- **The ship driver never rebases** (`tools/cc/ship.py`: never rebase or force-push a pushed
  lane) [verified]. So the replay misses no conflict to a rebase.

**What is still open.** The collision half reads low over the record. It has not been tested for
what keeps it low. One possibility is that the claim protocol prevents collisions at a cost no
census counts: mail `45df70` placed code "by function, to stay off the live claims". The reading
half is also unmeasured as a cost, as distinct from a length. And `lines a lane reads` is a
length: a decomposition lowers it by construction, and a module move cannot change it by
construction. So it cannot be the metric alone (Task 7).

**Who is hurt** (`docs/STANDING_PRINCIPLES.md` §16, from `DEF-4123`): the maintainer or seat
whose lane edits a command. They read a function hundreds of lines long to change one branch of
it. The row also claims their lane collides with another seat's change to the same file. The
audit measures both halves rather than assuming either.

## Scope (in)

The census (Task 1) is the instrument. Each item below is one section of its `--json`, read and
interpreted in this file's `## Audit result`.

- **(a) The concern map and the layer view** (Task 2): every top-level definition in exactly one
  unit, by a stated mechanical method. Any unit assigned by hand is tagged so.
- **(b) The accretion read** (Task 2): for the largest functions, the special cases that rows
  bolted on, logic duplicated with doctor.py, and the deploy paths.
- **(c) The move cost per unit** (Task 3): the importers outside tests (both entry points among
  them), the four import cycles, the test patches, the readers of cli.py by path, the citations in
  every spelling and file type, and the ledger probes that read cli.py symbols.
- **(d) The patch-target contract, sized for both re-export branches** (Task 4), plus today's
  vacuous patches.
- **(e) The citation re-key tool, sized** (Task 4), including the `tools/cc/` sites the roadmap
  would have to allow.
- **(f) The doctor.py boundary** (Task 5): the cycle, as a hypothesis with its refutation.
- **(g) The ledger triage** (Task 6): the live rows on cli.py in three tiers, each row placed in a
  unit and a class.
- **(h) The metric, pre-registered** (Task 7): its components, baselines, thresholds and the shape
  that can move each, with the thresholds committed before any metric read.
- **The recommendation and the Gate A decisions** (Task 8).

## Scope (out)

- **Any change to `espalier/cli.py` or `espalier/doctor.py`.** Ack `df6595` forbids it before
  approval, and doctor.py's own refactor is out by ruling 2 of 581de4. A finding that a cli.py
  function belongs in doctor.py is recorded for the operator; this lane does not act on it.
- **Building the patch-target contract or the re-key tool.** That is wave 1, after the operator
  approves on this audit's sizing.
- **Any move or decomposition.** That is waves 2 and up, one unit per lane, each approved at Gate
  A.
- **Fixing or editing any triaged row.** Each stays with its seat and job (`DEF-985` with win, and
  `DEF-5118` with air-work, parked at authoring). The triage lives in the Audit result only.
- **A line-count metric, and the god-file scanner's thresholds** (ruling 3). A count can still be
  reported, but never as the goal.
- **Re-classifying a surface as a record.** The declared set is
  `tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS`, plus the struck-row lines that file
  exempts. Any other surface the audit thinks is a record goes to the operator as a candidate
  (Core Rule 13).
- **Re-reading the merge rules or the board's overlap verdicts.** This pack consumes
  `scripts/merge_cost_census.py` and `scripts/lane_overlap_census.py` and loads them by path.
  This is not a licence to use a window that cannot decide Task 0: pass PRs by `--window lo-hi`
  (`scripts/lane_overlap_census.py::window_limit` pages to 1000) and `--prs-json` for the merge
  census. A defect in either script that the Audit result relies on is fixed in-lane or the
  section is reported unread (Pass criteria).

## Task 0 — Verify (can end the refactor waves)

Each item names the oracle, the result that refutes, and the exit. The exit is stop and re-raise
to the operator, never adjust and continue. Items 2 and 3 are graded against thresholds committed
at step 1, before the metric is read (Task 7).

1. **Do the authoring figures hold at P?** *Oracle:* the census at P, every window anchored to P's
   commit date, against the Motivation table. *Tolerance:* a structural figure (lines, counts, the
   replay at a pin) reproduces exactly; a windowed one differs only by the PRs and merges between
   `17d83e0` and P, listed by number. *Refuting result:* a difference that list does not explain. *Exit:* re-raise with both reads.
   Treat the instrument as a claim first (`docs/sharp-edges/the-measuring-instrument-is-a-claim-too.md`),
   and never pick the more convenient read.
2. **Is there a collision cost?** *Oracle:* the census's `collision` section at P over the 30 days
   to P's commit date, each component with its window and its count of cli.py PRs: conflicts on
   replay (whole record, reported against its floor), concurrent PR pairs sharing a CLI module by
   verdict, cross-seat lane pairs whose claim windows overlap on one, and dispatcher holds.
   *Real* when a graded component is at or above its committed threshold; *not real* otherwise.
3. **Is there a reading cost?** *Oracle:* the census's `transcripts` section at P: the lines of the
   CLI modules that the seats' Read calls actually returned, per cli.py lane, against the lanes
   that did not touch the CLI modules (Task 1). The minimum detectable difference at the lanes'
   counts is written down with the threshold at step 1. *Real* when cli.py lanes read past the
   committed threshold; *not real* when the read can detect the committed effect and does not
   find it. The length of the functions is not this item's oracle: every function keeps its
   length under a move, so a test on it decides nothing.

A component the census cannot decide (too few lanes to detect the committed effect, or a lane
attribution the hand sample cannot confirm) is reported as **unmeasured**. That is a result of
its own, never a silent kill and never a license, and a cell built on it says so in the call.

**The exit table** (the roadmap's Task 0 is the one home of this gate; the cells here are its
cells):

| | Reading cost not real | Reading cost real |
|---|---|---|
| **Collision cost not real** | **No refactor waves.** `DEF-4123` re-scoped or struck on the operator's word; the census and the map land as evidence | Decomposition waves, graded on reading |
| **Collision cost real** | Module or layer moves, graded on the collision components | Both, with the layer moves first |

The alternatives of Task 8 go to Gate A beside the cell, never in its place.

*Expected at authoring (hypothesis, tagged).* The collision reads that gave "zero" cover about 44
hours and 2 cli.py PRs. Over 30 days the reasoning review found 3 concurrent cli.py PR pairs
[probable] and 18 claim-overlapping lane pairs [probable] beside 1 conflict and 1 hold. The
reading half is unread. Neither cell is the likely one on what is known. The in-lane reviewer's
brief withholds this paragraph (Task 9).

## Relevant memory

Recent pattern: the instruments this repo built to price coordination cost have twice corrected
their own author (a lane-overlap count read as conflicts was mostly path-only pairs; the
merge-cost census found 0 conflicts in the changelog until the union merge driver was turned off,
per `scripts/merge_cost_census.py`'s docstring, 2026-10-09). At this pack's own authoring a 44-hour
window was read as "no concurrent pairs", and a metric was chosen whose result its definition
decides. Each correction came from reading what the instrument counted, not its total.

| Entry | Where |
|---|---|
| The Measuring Instrument Is a Claim Too | `docs/sharp-edges/the-measuring-instrument-is-a-claim-too.md` |
| A mutation proves what it kills, not what you meant it to kill | `docs/SHARP_EDGES.md` (its section of that title) |
| 2.14 An early-return guard silently hollows out the tests below it | `docs/FAILURE_MODES.md` |
| Classify a surface before you measure it | `memory/classify-the-surface-before-measuring-it.md` |
| Check the layer before the class | `memory/check-the-layer-before-the-class.md` |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| A "decompose godfile" refactor into in-file helpers doesn't move the godfile metric | `docs/CONVENTIONS.md` (its section of that title; it grades line count, which ruling 3 excludes) |
| Citation rot: verify the fix target tree-wide | `docs/sharp-edges/citation-rot-verify-fix-target-tree-wide.md` |

Resolved at authoring with `python3 tools/cc/hooks/_recall.py "<topic>"` for "measuring
instrument is a claim", "classify the surface before measuring" and "fix the class not the
instance". The reviewers added the two canon entries on inert patches, and the rest were picked
by hand. Re-run the recall if this pack has been sitting. The folder ladder fires
`tests/CLAUDE.md` on the test file: marker classification, `git add` before gating, and
`scripts/archive_probe.py` for any test that reads the live tree.

## Implementation

### Task 1 — The census, `scripts/cli_cost_census.py` *(fix shape, untested)*

Self-host tooling (stdlib, `git`, `gh`) in the shape of `scripts/lane_overlap_census.py` and
`scripts/seat_day_census.py`. It loads by path, and keeps no copy of, what it does not own:
`tools/cc/_symbols.py` (hunks on symbols), `scripts/merge_cost_census.py` (the replay with
GitHub's merge rules, drivers off, in a throwaway shared clone), `scripts/lane_overlap_census.py`
(concurrent pairs) and `tools/cc/mail.py` (the mail fold).

```text
python3 scripts/cli_cost_census.py --at <P> --json                  # every section
python3 scripts/cli_cost_census.py --at <P> functions layers        # named sections
python3 scripts/cli_cost_census.py --at <P> collision transcripts   # Task 0's two oracles
```

- **`--at` is required and has no default.** A run without it refuses; it never falls back to
  `origin/main`.
- **Every window is anchored to P's commit date,** never to the clock (`--since="30 days ago"`
  moved a figure from 36/385 to 35/384 within hours). PRs are read by `--window lo-hi`, resolved
  from P's date and written into the output.
- **The `pin` block records everything a re-run needs:** P, its date, the PR window, and the
  object id of each mail ref read. Two runs at one pin print the same `collision` section (a
  test).
- **"The CLI modules"** means `espalier/cli.py` plus every module that receives a moved
  definition, an existing one included (`espalier/_python_floor.py` and `espalier/_venv.py` are
  the likeliest homes for the interpreter core). A re-run after a wave takes that set as an
  argument. C1, C3 and C4 are counted over the set, so a move cannot zero them by changing the
  file the events land on. **C2 is not** (Task 9's reasoning review; verified, `::claim_overlaps`):
  it counts an overlap only where another seat's claim names the same CLI module the lane
  changed, so any split of cli.py, an arbitrary one included, lowers it by construction. The
  Gate A decisions say what follows.

**The `transcripts` section** reads the session transcripts of the seats on this box. These are
`~/.claude/projects/<the project folder of each checkout of this clone>/*.jsonl`: the main
checkout's and each named worktree's, never the scratchpad drive projects. At authoring the
folders held 388 and 203 transcripts [verified, `ls`]. For each Read tool call on a CLI module it
records the lines returned (from `limit`, or the file's length up to the tool's cap) and the
session, attributed to a lane by the seat's claim and release stamps. Grep calls on the CLI
modules are counted apart. The population is named in the output. The
Windows seats' transcripts are on their own box, so the section covers 2 of the 4 seats, says so,
and is never read as the whole. *Refuted if* the attribution of sessions to lanes cannot be
checked on a hand sample of five lanes; the section is then reported unread.

The `--json` top level holds `pin`, `functions`, `layers`, `clusters`, `importers`, `readers`,
`patches`, `citations`, `probes`, `doctor_boundary`, `ledger_rows`, `collision`, `transcripts`,
`lane_read`, and `unread`: each section that could not be read, by name, never reported as zero.

*Refuted if* a section's figure on the frozen fixtures (Task 9) cannot be told apart from what its
mutation produces. The census is then not an instrument for that section.

### Task 2 — The concern map, the layer view and the accretion read (items a, b)

**Method (prescribed as a method; the units it yields are a result):**

1. **The graph.** Build a call graph over every top-level definition at P: functions, the 13
   classes, and the module-level names (about 115 at authoring [verified, architecture review]).
   An edge is an `ast.Name` load resolving to a module-level definition, a dispatch edge
   `::build_parser` wires (`set_defaults(func=...)`), a module-level dict or tuple literal of
   functions, or a **write** (a `global` statement's target): `::_detect_python_command` writes
   `_BELOW_FLOOR_ANSWER` and `_VENV_FALLBACK_OUTSIDE` and never reads them, while
   `::_refuse_below_floor_wiring` reads both [verified].
2. **Latches and memos move as one.** Each of the five `global` latches (`_INTERPRETER_WARNING_EMITTED`,
   `_BELOW_FLOOR_ANSWER`, `_BELOW_FLOOR_REFUSING`, `_VENV_FALLBACK_OUTSIDE`,
   `_POWERSHELL_CALL_NOTE_SAID`) and the two memo dicts changed in place (`_VENV_ONLY_VERDICTS`,
   `_WRITERS_GATE_VERDICTS`) is tied to every function that reads or writes it. A unit holds all
   of them or none.
3. **What the graph cannot read** is counted apart, never dropped: `getattr`, a name as a string,
   a call through another module, a lazy import inside a function (124 at authoring; these are
   the outbound edges, priced in Task 3).
4. **Ownership by command.** From each `cmd_*` entry point, take the closure. A definition reached
   by exactly one command is **owned** by it; by several, **shared** (with the commands named); by
   none, **unreached**, split into reached only from other modules (doctor, fuse, cleanup,
   render_surface, bench) and **dead** (for example `::_interpreter_base_name`, probable).
5. **Recompute ownership at the concern level.** Group the commands into concerns by hand, tagging
   each grouping `cluster_source: hand` with the closure overlap printed beside it, then compute
   ownership over each concern's union. By command alone, most of the file lands in "shared" (98
   owned, 197 shared, 15 unreached; shared holds 8,250 of 15,515 function lines [verified,
   architecture review]). Grouping init, upgrade, merge-settings, install-ci, fingerprint and
   render-template gives one concern of 225 functions and 10,905 lines, 61% of the file
   [verified].
6. **The layer view, a first-class output beside the concerns.** Take the strongly connected
   components (one at authoring: `::_detect_python_command`, `::_remedy_interpreter`,
   `::_warn_interpreter_below_floor` [verified]) and the condensation's topological order. Then
   name each layer, a set closed under what it calls: the interpreter core (18 functions, 656
   lines, 6 names [verified]), the settings set, deploy, and the commands. Print the bottom-up
   order, and for any other proposed order, the cycle it would create (a unit moved above a layer
   it still calls leaves the new module importing cli).
7. **The sum.** Assert that owned, shared and unreached, over functions, classes and module-level
   names, equal the AST count at P.

The 35136c concern list (init and deploy; upgrade and merge-settings; settings reconciliation;
the diagnosis beside doctor; scan and scope-check; memory; the parser) is a starting guess, not
the answer. By reach at authoring [verified]: upgrade cannot be separated from init
(`::cmd_upgrade` owns 17 functions, and 929 of their 1,270 lines are itself); the diagnosis beside
doctor is two functions, 114 lines; and the list misses the interpreter core.

**The accretion read**, for the top definitions by length at P (eight at authoring). Mechanical
cues first (the `DEF-\d+`/`TP-\d+` ids cited inside the span; its history from
`git log -L :<name>:espalier/cli.py`; string literals of 30 characters or more shared with
`espalier/doctor.py`; the deploy helpers it calls), then a reader. The reader classes each large branch as a row's special case, logic duplicated with doctor, or
the function's own work, and says which class dominates.

### Task 3 — The move cost per unit (item c)

- **Importers outside tests, by AST over every tracked `.py` file** [verified]:
  - Two entry points, neither of which any move may change: the console entry
    `espalier.cli:main` (`pyproject.toml`), and `python -m espalier.cli`, which runs cli.py's
    `__main__` block. The second is used by `.github/workflows/refresh-externals.yml`,
    `bench/baselines/espalier/setup.sh`, `docs/INSTALL-CI.md` and its shipped copy
    `espalier/assets/docs/INSTALL-CI.md`, which adopters read.
  - `espalier/__main__.py`, `espalier/cleanup.py`, `espalier/doctor.py`, `espalier/fuse.py`,
    `espalier/render_surface.py`, `scripts/generate_doc_regions.py` and the release-gating
    `bench/run_benchmark.py` (`from espalier.cli import deploy_harness`): 62 distinct names in
    all.
  - `espalier/fuse.py` calls `::cmd_init` and `::cmd_install_ci` with an `argparse.Namespace` it
    builds by hand, so a move that changes either command's attributes breaks fuse with no parser
    to catch it.
  - Under `-m`, cli runs as `__main__`, so the first lazy back import may load a second copy with
    its own latches (unmeasured: a census line reads it or marks it unread).
- **The four import cycles**, each edge by name both ways: doctor (Task 5), cleanup (8 names
  back), render_surface (`_deploy_sources`) and fuse (13 names back, lazy both ways). Each unit is
  priced by its **outbound** edges (the lazy imports inside its functions, which
  decide whether a move closes a new cycle) as well as its inbound ones.
- **Test patches, by AST over `tests/`:** `monkeypatch.setattr` on an alias bound to
  `espalier.cli`; string targets in `monkeypatch.setattr`, `mock.patch` and `patch.dict`;
  `patch.object`; `delattr`; and direct assignment `cli.X = ...`. At authoring both reviewers
  read 43 distinct targets, at 149 sites in 19 files [verified, architecture review] and 146
  sites [probable, reasoning review]. No `mock.patch` used a string target. Four sites patch
  other modules through cli (`cli.shutil`, `cli.sys`, `cli._doctor`). The row's "124 test lines"
  is superseded.
- **Test importers, by AST** (the import regex read 82 at authoring; looser greps 109 to 123):
  report the AST count with its rule, and drop the unreproduced 101.
- **Readers of cli.py by path** (tests and scripts), each classed [verified, architecture review]:
  - **silent**, asserting something of cli.py's text that moved code escapes with no red:
    `tests/test_init_interactive_arming.py::test_no_raw_sys_isatty_calls_in_cli`,
    `tests/test_python_floor.py::TestFloorAtTheThreeDecisionSites::test_the_two_python_2_admitting_predicates_are_narrowed_together`,
    `tests/test_hook_contracts.py::test_no_stray_literal_ten_for_stop` (its `if` guard asserts
    nothing once the block moves), `tests/test_cli_deploy.py::test_no_naked_write_text_anywhere_in_cli`
    and `tests/test_no_bare_espalier_hints.py::SCANNED_FILES`;
  - **loud**, red on a move (a cost, not a risk): 34 `("espalier/cli.py", symbol)` keys in 12
    files, 88 path literals in 35 files and 19 `/ "cli.py"` reads in 14 files;
  - **flat-module readers**, scanning only top-level `espalier/*.py`, so a subpackage escapes them:
    `tools/cc/sister_site_probe.py` (the Core Rule 12 oracle) and
    `tests/test_python_floor.py::test_every_engine_verdict_memo_is_cleared_between_tests`. New
    modules are flat siblings in `espalier/`.
- **Citations, in every spelling and file type**: `espalier/cli.py::X`, bare `cli.py::X`, the
  line form `espalier/cli.py:NNN` and `espalier.cli.X`, across every tracked file. At authoring
  733 `espalier/cli.py::` occurrences in all [verified, architecture review], 676 of them in
  `.md`/`.json` [verified]. They split five ways:
  - the declared record set (`_RECORD_SURFACE_DOCS`);
  - struck ledger rows: 452 in 95 fragments [verified];
  - swept-live, the `.md` files `tests/test_doc_source_citations.py` resolves, the only ones that
    go red after a move: 132 in 36 live ledger fragments and 31 in 7 swept docs [verified];
  - unchecked-live, which rot with no red: 48 in 10 tracked packs (excluded as dated plans via
    `espalier/surface_contract.py::is_shipped_pack`), 6 in `bench/corpus` JSON, the `.claude`
    bodies, and code comments (57 in 29 `.py`/`.cmd` files) [verified];
  - code surfaces in protected zones, each with its `espalier/_vendor/cc/` twin:
    `tools/cc/hooks/_reinject.py::_GENERATED_DOC_REGIONS`, `::_HOOK_COUNT_WITNESSES` and
    `::_HELPER_COUNT_WITNESSES` (`INIT_TOOL_SCRIPTS`, `REQUIRED_GITIGNORE`, `INIT_HOOK_SCRIPTS`);
    `tools/cc/hooks/_start_refusal.py` (`_deploy_managed_py`); `tools/cc/hooks/session_start.py`
    and `tools/cc/record_merge.py` (`cmd_memory_prune`, `_MEMORY_DATE_RE`); and
    `tools/cc/statusline.cmd` (`STATUSLINE_FALLBACK_TEXT`), which is deployed to adopters.
- **Ledger probes that read cli.py symbols.** `tools/cc/check_ledger_probes.py` checks a probe's
  subject at file level, and cli.py survives a move. So a probe that reads a moved symbol out of
  cli.py prints a new value, and its live row is offered as a strike candidate. `DEF-1079`'s
  probe AST-reads `REQUIRED_GITIGNORE` from cli.py [verified]. About 27 live rows' probes depend
  on cli at authoring [probable]. The census lists each probe, the symbols it reads, and the units
  that would flip it.

### Task 4 — The patch contract, sized for both re-export branches; the re-key tool, sized (items d, e)

- **Vacuous today, expected 0 [probable].** By the name-level rule ("a target no cli function
  loads"), both reviewers read 0 of 43 targets. So do not rest on that rule: run the raising
  sentinel over a sample of all sites, not over the name-level candidates. Patch the target with a
  sentinel that raises, run that one test, and see whether it still passes. Report the vacuous
  share. A confirmed one is filed in-lane with `python3 tools/cc/ledger_row.py file` (no id); where
  several share a cause, they go in one row with a class question.
- **Why the name-level rule is born weak** [verified, architecture review]. It is satisfied by any
  one loader anywhere in cli.py:
  - 31 of the 43 targets (131 sites) have more than one loader, so a partial move stays green
    while the moved path goes unpatched; 12 targets (30 sites) are names cli imports from
    elsewhere, so a new module gets its own binding;
  - `tests/test_fuse.py` patches `cli.cmd_install_ci` to steer fuse's lazy import, and
    `tests/test_doctor.py` has 15 sites that steer doctor through its back imports;
  - `tests/test_init_rewire_interpreter.py` patches `cli._doctor._interpreter_is_python3`, which
    works only because cli calls doctor through the module attribute;
  - 39 of the 45 patches of `_INTERPRETER_WARNING_EMITTED` pass `raising=False`, which creates a
    missing attribute silently. The canon for this class: `docs/FAILURE_MODES.md` 2.14 and
  `docs/SHARP_EDGES.md`'s "A mutation proves what it kills, not what you meant it to kill".
- **Wave 1's contract shape (untested): a check on each lane's diff.** For every definition the
  lane moves, every global it reads or writes has its `cli.<name>` patches re-pointed, its
  `raising=False` patches named, and its `cli._doctor` and fuse-steering patches re-checked.
  *Earn-the-red:* a seeded partial move, where a shared helper is still loaded by an unmoved
  function and the moved caller's test must go red. *Refuted if* the check cannot tell a
  re-pointed patch from one that still lands on cli and reaches nothing.
- **Both branches, sized.** The census sizes the contract and the move cost twice. **With
  re-exports** (moved names stay importable from cli), stale `cli.X` bindings stay alive, the bool
  and `None` latches split into two copies, and `tests/conftest.py::_restore_interpreter_warn_flag`
  would restore cli's copy. **Without** them, the same sites fail loudly. Tests touch 242 cli names, 233 of them defined in cli.py [verified, architecture review]. The
  cut is the names a test, probe or importer touches, not "public". Which branch applies is a
  Gate A decision (Task 8).
- **The re-key tool's work list per unit**: the live citations of its members, in every spelling
  of Task 3. Mirrored surfaces (`espalier/mirror_registry.py`) are re-keyed at the source and
  regenerated by their sync. Record surfaces stay as they are. The protected-zone sites are listed
  apart, because moving a constant they cite needs a `tools/cc/` edit and a vendor sync. Gate A
  decides between keeping those constants in cli.py and a re-key lane in the protected zone
  (Task 8).

### Task 5 — The doctor.py boundary (item f)

**The hypothesis (from 35136c and this pack's first draft):** moving the cli.py functions that
only doctor and the diagnosis cluster reach, into a neutral module, breaks the cycle without
touching doctor.py's code. **The refutation, read at authoring [verified, architecture review]:**
- doctor.py's 20 lazy import lines take 43 names from cli (10 constants, 1 class, 32 functions),
  across 19 doctor functions;
- only 2 are reached by doctor alone (`::settings_foreign_read_denies`, `::_foreign_read_denies`);
  the other 42 are reached by init, upgrade, merge-settings, render-template, integrity, or by 12
  or 13 commands;
- moving the 2 leaves 42 back edges. The closure of all 43 is 139 definitions and 3,283 function
  lines;
- even that move only relocates the cycle. The closure holds `::_not_python3_from_entries`
  (reached through `::_retired_rules_to_name` and `::_enforcement_claim_blockers`), which calls
  `doctor.py::_interpreter_is_python3` and three sibling interpreter probes through `_doctor`.

So ending the cycle needs a doctor.py code change, which ruling 2 excludes. The census re-reads
this at P and prints each of the 43 names with the commands that reach it, the closure and its
size, the outbound edges that would close a cycle, and the doctor.py change an end to the cycle
would need. That last item is for the operator at Gate A, never for this lane. Precedent:
`::_count_unstamped_seed_docs` says doctor must not import this module, and doctor imports it in
20 places.

### Task 6 — The ledger triage (item g)

The population, as the dispatcher folds it (the operator can reverse this), read at P over
`task-packs/ledger.d/*.md` in three tiers:

```text
for each fragment: line 2, cells = split on '|', stripped; struck = cells[1] starts with '~~'
  tier 1, first path:  not struck and the first token of cells[2] that contains '/' or a
                       leading '.' and an extension is 'espalier/cli.py'       # 23 at 17d83e0 (22 if a dotfile counts)
  tier 2, site cell:   not struck and 'espalier/cli.py' in cells[2]            # 31 at 17d83e0
  tier 3, body only:   not struck, not tier 2, and a cli.py symbol cited in cells[3]
                       (DEF-1089, 3065, 346c, 5095, 5118, 877, 883, 900 at 17d83e0)
```

The 31 are a lower bound, and the triage covers tiers 2 and 3. The tokenizer is stated, because
`DEF-623` opens with `.gitignore` and the subset reads 23 or 22 by the rule chosen. For each row,
the Audit result records the unit its cited symbols fall in; its class (fix **before** the unit
moves, fix **in** the move's lane, or **independent**); and whether a live claim or job holds it,
from the board at P.

### Task 7 — The metric, pre-registered (item h)

Each component carries a window anchored to P, a baseline at P, a threshold, a target, the read
after each wave, and **the shape that can move it**. A component no proposed shape can move is
reported, and never offered as a wave's payoff. A component at its floor is reported and graded on
nothing. Being read at authoring does not make a component ungradable.

| Component | Instrument | Window | Moved by | Graded |
|---|---|---|---|---|
| **Lines of the CLI modules a lane's seat actually read** (primary) | the census's `transcripts` | 30 days to P; 2 of 4 seats | a module move (navigation), a decomposition, the navigation aid: each a hypothesis the read after the wave tests | yes |
| Lines a lane reads: summed lengths of the definitions its hunks fall in (secondary) | the census's `lane_read` | 30 days to P | a decomposition, **by construction** | only beside the primary. Must-not-pass case: an arbitrary split of the top functions into equal chunks reads as no payoff |
| Concurrent PR pairs sharing a CLI module, by verdict (shared symbol, unplaced, different functions) | `lane_overlap_census.py --window lo-hi` | 30 days to P | a module move, mostly for **unplaced** pairs | yes, if above its floor |
| Cross-seat lane pairs whose claim windows overlap on a CLI module | the mail fold | 30 days to P | a module move | yes, if above its floor |
| Dispatcher holds over a CLI-module overlap | the mail fold | whole record | a module move | yes, if above its floor |
| Conflicts on replay on the CLI modules | `merge_cost_census.py` replays, filtered | whole record | a module move | **reported, never graded** (floor: 1 in 511) |

Catch-ups that carry the file are not a component: with the up-to-date rule off they are main's
churn, and the conflicts and holds that would make one a cost are counted already. **The
thresholds are committed at step 1, before any metric read** (Sub-task ordering), and that
commit's sha goes in Landing. None may change after it.

### Task 8 — The Audit result, the recommendation and the Gate A decisions

Fill `## Audit result` in this file at P: the unit table (concerns and layers: members, lines,
move cost), the accretion findings, the doctor boundary, the triage, the metric table with
baselines and the committed thresholds, and Task 0's three verdicts with the exit cell they land
in.

**The recommendation** is an ordered list of units, each naming its shape (a layer moved
bottom-up, a cluster moved, a function decomposed, or the concern map kept as a maintained
navigation aid the census regenerates) and the component it is expected to move, by how much (each
a hypothesis). It may be any mix of those, or **no refactor waves**, with the reason. Beside it, priced, go
the alternatives the reviews named: strike or re-scope `DEF-4123` now on this evidence; decompose
only `::cmd_upgrade` and `::build_parser`, with no wider map; and the navigation aid alone.

**The Gate A decisions**, each stated with the census's figures for the operator:
- re-exports or none (Task 4);
- the doctor cycle: left as it is, or a doctor.py change that ruling 2 would have to allow
  (Task 5);
- the protected-zone citations: keep those constants in cli.py, or allow a `tools/cc/` re-key
  lane with its vendor sync (Task 4);
- which components grade a wave (Task 7).

The dispatcher turns the result into one operator call that links the Audit result at its merge
commit rather than restating it. Wave 1 and the unit waves are authored from it as children of
TP-708.

## Affected symbols

### Changed-semantics
- `tests/_surface_expected.py::EXPECTED_SCRIPT_NAMES` (gains `cli_cost_census.py`; `EXPECTED_SCRIPT_COUNT` is derived)

### Renamed
- (none -- wave 0 renames nothing)

### Added-paths
- `scripts/cli_cost_census.py`
- `tests/test_cli_cost_census.py`

### Removed-paths
- (none -- wave 0 removes nothing)

## Reach

This pack closes no class. Its rows, so that no later pass reads them as shut:

Members derived by: Task 6's read over `task-packs/ledger.d/*.md` at P.

| Item | Status | Evidence |
|---|---|---|
| `DEF-4123` | **NOT CLOSED**. The audit half is done in this wave. The row stays live until refactor waves land, or the operator re-scopes or strikes it at Gate A | the Audit result |
| Tiers 2 and 3 of the population (31 + 8 at `17d83e0`, among them `DEF-985` held by win and `DEF-5118` held by air-work) | **NOT REACHED**. Triaged only; the 31 are a lower bound | the triage table |
| Vacuous patches found by the Task 4 sentinel sample | **FILED if any**, in-lane, as one row or one class; expected none [probable] | the rows' probes, or the sample's size and result |

## Pass criteria

- The census refuses a run without `--at`, and at P every section is filled or named under
  `unread`. No unread section reads as zero.
- Two runs at one pin print the same `collision` and `transcripts` sections.
- Each section earned its red on frozen fixtures (Task 9) against the named mutation. No fixture
  agrees with the implementation by accident: positions and values disagree in both directions.
- Every top-level definition at P (functions, classes, module-level names) is in exactly one unit
  or marked shared or unreached, and the census asserts the sum.
- The triage covers every row tiers 2 and 3 derive at P, and the counts are equal.
- The thresholds commit precedes the first metric read in the lane's history.
- Every figure in the Audit result names P, its window and its command, and a figure with no
  command is tagged unmeasured.
- `git diff --name-only origin/main...HEAD` lists only the files under Files touched.
- The reasoning review ran, and its verdict and folds are in Landing.
- No criterion here licenses landing a census with a known defect in a section the Audit result
  relies on. Such a section is fixed or reported unread.

## Files touched

- New: `scripts/cli_cost_census.py`, `tests/test_cli_cost_census.py` (`git add` before gating).
- Modified: `tests/_surface_expected.py` (`EXPECTED_SCRIPT_NAMES`, with a dated comment);
  `tests/conftest.py`'s `_MARKER_RULES`, only if the test spawns `git` (otherwise the test file
  carries a `# pytest-marker: default-unit` line saying why); this file (its pre-registration at
  step 1, `## Audit result` and `## Landing`); the seat's Session Log fragment, at the handoff.
- Modified, added at the full tier, where two tree-wide contracts each asked for an entry for the
  new files: `scripts/derived_population_census.py`'s `ADJUDICATED`, one entry adjudicating the
  test file's one derived-population row; and `tests/test_record_fragments.py`'s
  `_ONE_DIRECTORY_SITES`, registering the census's names for the ledger, probe and changelog
  directories, with the reason.
- New, only if Task 4 confirms a vacuous patch: `task-packs/ledger.d/DEF-<n>.md`, its probe under
  `task-packs/probes.d/`, and any `task-packs/lineage.d/` file the file verb writes, all through
  `tools/cc/ledger_row.py file`.
- Unmodified on purpose: `espalier/cli.py`, `espalier/doctor.py`, every file under `tools/cc/`,
  every test that patches cli, every existing ledger row, and the roadmap
  `task-packs/TP-708-the-cli-is-mapped-before-it-moves.md` (the dispatcher's).

## Sub-task ordering

1. **Pin and pre-register.** Name P, and write its date and the PR window. Write Task 7's
   thresholds and Task 0 Item 3's minimum detectable difference, chosen from what is known before
   the read, never from the data. Commit them as the lane's first commit. *Checkpoint:* the commit
   sha, recorded for Landing.
2. **Task 1, the skeleton.** The census with the `pin` and `functions` sections and its fixture
   test, the smallest concrete piece. *Checkpoint:* `pytest tests/test_cli_cost_census.py -q`.
3. **Task 0 Item 1.** Re-derive the Motivation table at P. *Checkpoint:* the table with its deltas,
   each explained by a listed PR or merge.
4. **Task 1 (cont.).** The `collision`, `transcripts` and `lane_read` sections and their fixtures,
   then Task 0 Items 2 and 3 read against the committed thresholds. *Checkpoint:* the exit cell
   named.
5. **Tasks 2 and 3.** The map, the layer view, the accretion read and the move cost.
   *Checkpoint:* the census's sum assertion holds at P.
6. **Tasks 4, 5 and 6.** The sentinel sample (any row filed), the two re-export branches, the
   doctor boundary and the triage. *Checkpoint:* the triage count equals the tiers' read.
7. **Task 8.** The Audit result filled. *Checkpoint:* every figure names P, a window and a command.
8. **Task 9.** Red-team, folded. *Checkpoint:* the verdict recorded.
9. **Proof and land.** `python3 scripts/proof_tier.py` computes the tier and names the reviewers.
   Run what it prints, then `/handoff` (`/ship`). A window edge before this step hands off with
   `ship.py handoff --unfinished`, so the committed pin and thresholds carry over. *Checkpoint:*
   the PR green, and the dispatcher reading the Audit result into the operator call.

### Task 9 — Red-team and earn-the-red

**Earn-the-red, per section, against the named mutation**, on frozen fixtures (a `git init` tree
in `tmp_path`, saved JSON, or a saved transcript):

| Section | Mutation the test must die to |
|---|---|
| pin | read the window from the wall clock instead of P's commit date |
| collision, conflicts | read rc 1 from `git merge-tree` as clean |
| collision, pairs | count cli.py pairs over `pairs[].paths` only, dropping the symbol verdicts |
| collision, catch-ups | count a catch-up that carries cli.py with no overlap |
| transcripts | count a Read call's lines from the whole file instead of its `limit`, or attribute a session to the seat's other lane |
| lane_read | place a hunk on the definition *after* the one it falls in |
| lane_read must-not-pass | read an arbitrary equal split of a fixture function as a payoff |
| layers | order a unit above a layer it calls and report no cycle |
| functions | drop the write edge of a `global`, so a latch leaves its readers behind |
| patches | resolve a patch target by a line grep for `cli` (a fixture comment holds `cli.foo`) |
| citations | count a struck ledger row's citation as live, or miss the bare `cli.py::` spelling |
| ledger_rows | read a struck id cell (`~~`) as live |

**Reviews, before the dispatcher sends the operator call:**
- the reasoning review: the reflect skill's checklist, run by the failure-mode reviewer in its own
  context, on the Audit result and the census. Its brief withholds Task 0's *Expected at
  authoring* paragraph;
- a test-infrastructure read of Task 4's sentinel sample by the code reviewer, briefed on
  `tests/CLAUDE.md`'s "patch the object the code under test reads";
- the code review the tier script names.

Each reviewer writes to its own scratch subdirectory (Core Rule 14). A clean review is the
surprise; record it either way.

What this audit is most likely to get wrong (the reviews' starting points):

1. **A metric whose result its definition decides:** `lane_read` falls under any decomposition,
   and a loosely attributed transcript read can show anything (the must-not-pass case and the
   hand sample).
2. **Windows that slide:** a figure read off the clock, or over 44 hours, given as the record.
3. **A unit that drags its latches apart, or closes a cycle** (the layer order and write edges).
4. **Blind surfaces:** unswept citations, silent path readers, probes that flip a live row.
5. **Records re-classified by convenience,** and **vacuous patches filed without the sentinel.**

## Estimated effort

| Step | Budget |
|---|---|
| Step 1, pin and pre-registration | 1 h |
| Task 1, the census core and fixtures | 4 to 5 h |
| The `transcripts` section and its hand sample | 1.5 h |
| Tasks 2 and 3: the map, layers, accretion, importers, readers, citations, probes | 4 h |
| Tasks 4, 5 and 6 | 2.5 h |
| Tasks 7 and 8 | 1.5 h |
| Task 9, red-team and folds | 2 h |
| Proof and land | 1 h, plus the tier's wall clock |
| **Total** | **about 17 to 19 h: three windows for one seat** |

## Audit result

*(Filled at execution, at P. Empty at authoring. Step 1 writes the pin and the thresholds here
first.)*

**The 0-A review, folded as ruled.** The in-lane 0-A pack review read REQUEST CHANGES, 1 BLOCK
and 4 WARN (request `20261118T022759Z-air-work-7e16a8`). The dispatcher ruled all five fold,
amended (ack `20261118T024509Z-air-aae43b`, note `20261118T024512Z-air-b96288`). Each fold is
below, where the rule it changes sits.

### Pin and pre-registration (step 1, committed before any metric read)

**P** = `3330a5a4dcadb35c1872edb0f6b14d9feb487886`, the merge of #718, committed
2026-11-18T01:23:09Z [verified, `git log -1 --format=%cI`]. Every figure below and in the census
is read at P, never at `origin/main` or the clock.

**Windows, anchored to P's commit date:**
- *30 days to P:* merged at or after 2026-10-19T01:23:09Z and at or before 2026-11-18T01:23:09Z.
  The census resolves the pull-request number range from `mergedAt` and writes it into its `pin`
  block. At step 1 a `gh pr list --search "merged:2026-10-19T01:23:09Z..2026-11-18T01:23:09Z"`
  read 387 merged pull requests, #323 to #717, with #718 (P itself) on the boundary [verified].
- *Whole record:* from the first merge on the record (2026-09-24) to P.

**Population at P, counts only, read before any metric** (the minimum detectable difference
needs them):
- The 387 by seat (`tools/cc/mail.py::lane_seats`): air-work 147, air 48, win 96, win-2 78,
  unattributed 18. Those touching `espalier/cli.py`: air-work 14, air 1, win 8, win-2 10,
  unattributed 3 [verified].
- Transcript folders on this box: the main checkout's 391 `*.jsonl`, the `work` worktree's 207
  [verified, `find -maxdepth 1`], and the subagents' transcripts under `<session>/subagents/`,
  1,183 at the ruling [the dispatcher's verifier; unverified here]. This lane opened no
  transcript before this commit. The main checkout's folder is the dispatcher's, which reads
  almost nothing of cli.py, so on this box the reading cost is in effect air-work's alone. Every
  "2 of 4 seats" figure says so.

**What was known before this commit, and so could have steered a threshold.** The Motivation
table's authoring reads are visible: 1 replay conflict on cli.py in 511, 3 concurrent cli.py
pairs in 30 days (probable, all verdicts together), 18 cross-seat claim-overlap pairs over about
42 days (probable), 1 hold, and the function-length proxy (median 337). The observed reading
figure has never been read. The rule each threshold follows is stated first. Where a known
figure sits near a threshold, that is said beside it.

The ruling carried one more read: a verifier's count of **calls** over about 8 days of the
air and air-work transcripts. Read on cli.py was 18 calls in 6 sessions; Bash commands naming the
path were 241 in 49 sessions, 73 of them reads (in 20 sessions), plus 9 `git show rev:path`; the
subagents made 479 cli.py calls to the seats' 259. These are counts of calls, not of lines
returned, over a shorter window than the census reads. Every threshold below was drafted before
the ruling arrived and is committed as drafted: the threshold handoff set the draft aside in
commit `b958adb42` at 2026-11-18T02:29:20Z, 16 minutes before the ruling, and the diff from it to
this commit changes no threshold. That commit is on no branch (the restore's soft reset took it
off), so the check runs only on this box's reflog [verified locally; a second witness is the
dispatcher's note `20261118T025422Z-air-6fe8f9`, read from the objects there, which stays on
origin]. Only the counting rules changed.

*Added at Task 9's reasoning review, after every read below* [verified, the diff from
`b958adb42`]. "Only the counting rules changed" undersells one of them. The subagent exclusion
under *Whose reads*, and its reason that a subagent's reads do not spend the seat's budget, entered
this commit after the ruling's count of 479 subagent calls against the seats' 259 was known. The
exclusion moves R toward *not real*. For (a) the harm is bounded by the forks' beside figure
(air-work's median with its forks is 416, under 1,500). For (b) no fork figure was read for the
control arm, so the harm there is unbounded by any read. Two premises were also never put to the
operator: the weekly-tax rule and "an overlap grades only when it is the norm" (C2's 50%) are the
author's judgment. When C2's threshold was set, the known 18 pairs over 70 lanes already bounded
the share at 51.4% or under [probable].

**The rule for the collision thresholds: a weekly standing tax.** A collision event that
recurs about once a week is a standing cost on the dispatcher or a seat. One that is rarer is an
incident, and a refactor program of several lanes plus its wave-1 tooling does not pay for an
incident rate [judgment]. A component is graded on its own, and Item 2 reads *real* when any
graded component is at or above its threshold.

| Component (CLI modules = `espalier/cli.py` plus any module that receives a moved definition) | Window | Threshold: real at or above | Known before this commit |
|---|---|---|---|
| C1. Concurrent PR pairs sharing a CLI module whose verdict is not certified: `shared symbol` or `unplaced` (`different functions` is certified, `path only` cannot occur on a `.py`) | 30 days to P | **4** | 3 pairs, all verdicts, in another 30-day read [probable]. Near the threshold: the weekly rule set it, not the known figure |
| C2. Share of the window's cli.py lanes whose claim window overlaps another seat's live claim on the same CLI module | 30 days to P | **50%** | 18 overlapping pairs over 70 lanes in 42 days [probable]. The share of lanes in any overlap was never read. An overlap is an opportunity for cost, so it grades only when it is the norm |
| C3. Dispatcher holds over a CLI-module overlap (a dispatcher message whose text holds a lane for another's) | whole record (about 54 days) | **1 per 7 days of record**, so **8** at P | 1, a lower bound [verified] |
| C4. Replay conflicts on a CLI module | whole record | **not graded** (floor: 1 in 511) | 1 |

**The replay (WARN 1 and 2, as ruled).** `scripts/merge_cost_census.py` turns merge drivers off and
replays only the catch-up merges its pull-request list holds (469 of the 511 at authoring), while
the authoring replay ran with the CHANGELOG union driver on over all 511. It slices `--prs-json` to
`--prs`, whose default is 30, so the census passes `--prs` at the list's length, and the list must
reach #57 for cli.py's one conflict (`42cd25d4c`) to be in it. cli.py's 1 must then reproduce
exactly. The "any file" figure is reported under both instruments, each by name.

**Item 3, the reading cost (the primary, never read before this commit).**
- *Unit:* a merged lane of seat air or air-work in the 30 days to P (the Windows seats'
  transcripts are on their own box: 2 of 4 seats, said on every figure).
- *Reads counted (the BLOCK's fold, as ruled):* the primary counts `Read` calls on a file and the
  `Bash` reads of one. A seat on this box reads with `sed -n` more often than with `Read`, so a
  `Read`-only count would undercount both arms. A `Bash` read is found by stripping heredocs,
  splitting the command into simple commands, and keeping only a program on the read allowlist:
  `sed` without `-i`, `cat`, `head`, `tail`, `nl`, `awk`, and `git show <rev>:<path>`. The path
  must be a whole file operand; a path inside a commit message, a mail text or a plan step is a
  mention and is not counted. The `Grep` tool and the search programs (`grep`, `rg`, `ugrep`,
  `git grep`) are counted apart and reported beside the primary, each with its share.
- *Lines returned:* for `Read`, the result's `numLines`. For a lone range read, the line count of
  its result. For a piped or multi-file read, the command's own range. A whole-file read that the
  tool saved under `tool-results/` is followed to the later `Read` of that saved file, which
  never names the source path.
- *Whose reads:* the seats' own sessions. The subagents' reads (the `subagents/` transcripts, the
  ruling's WARN 4) are counted apart, each attributed to its lane through its `meta.json`
  `toolUseId` (the parent's `Agent` call), and reported beside the primary, never inside it.
  Threshold (a) is set by the seat's own context budget, which a subagent's reads do not spend.
- *Attribution:* a call is attributed to a lane by the transcript entry's own `gitBranch` where it
  names a lane, else by the seat's claim-to-release window on the mail. *Refuted if* a hand sample
  of five lanes cannot confirm the attribution: the section is then reported unread.
- *Reproducible at one pin (WARN 3, as amended):* the `pin` block records the transcript folder
  list (matched case-insensitively: the main folder is spelled with capitals on disk), each
  file's record count, and the object id of each mail ref read. A file in the list that is
  missing at a re-run is reported unread. Records are cut off by each record's own UTC
  timestamp at P's commit date, never by file mtime (live sessions append). Blob records are
  skipped, calls are deduped by `tool_use` id, and the census lane's own sessions and its
  reviewers' (the dispatcher's verifier included) are excluded. The output is sorted.
- *Treatment:* lanes whose diff touches a CLI module. Their **R** is the lines returned on the
  CLI modules.
- *Control:* lanes whose diff touches no CLI module, and whose edited non-test `.py` files each
  had under 3,000 lines at the lane's merge-base (an ordinary module, so that another god file
  does not stand in as the baseline). Their **E** is the lines returned on the files they edited.
- *Real* when all three hold:
  (a) median R ≥ **1,500 lines**. At cli.py's 52 bytes a line plus the Read tool's line-number
  prefix, that is about 22k tokens, about a tenth of the 200k-token handoff threshold
  (`handoff_context_tokens`) [the bytes verified at P, the token rate probable];
  (b) median R ≥ **2 ×** median E;
  (c) a one-sided Mann-Whitney test of R over E at **p < 0.05**.
- *Minimum detectable difference, written down now:* at one-sided α = 0.05 and power 0.8, the
  smallest standardised difference in ln(1 + lines) is d = 2.49 · √(1/n_t + 1/n_c). With
  n_t = 15 (the air and air-work cli.py lanes above) and n_c = 30, d = 0.79. As a ratio that is
  exp(0.79 · s), where s is the pooled standard deviation of ln(1 + lines): 2.2× at s = 1.0, 1.7×
  at s = 0.7. The census computes the realised figure, exp(2.49 · s · √(1/n_t + 1/n_c)), from
  the observed s and counts.
- *Not real* only when (a), (b) or (c) fails **and** the realised minimum detectable ratio is at
  most 2.0, with n_t ≥ 8 and n_c ≥ 8. Otherwise Item 3 is **unmeasured**.
- *Reported beside it, never graded:* R as a share of the lane's total lines returned (the
  roadmap's "against the lane's total reads"), and the function-length proxy `lane_read`.

**Task 7's targets for a later wave** (graded at that wave's own pin, over an equal window):
a wave is paid on a component only when that component falls by at least **30%** from its
baseline at P, and it was graded at P. For the primary, the post-wave R is compared with the
same rule (a) to (c), against the baseline R in place of E. `lane_read` is never a payoff alone.
Its must-not-pass case is an arbitrary equal split of a top function, which a decomposition grade
must read as no payoff.

**Fixed by this commit:** none of the figures above may change after it. A census defect that
moves a figure changes the census, never the threshold.

### Task 0 Item 1 at P: the authoring figures re-derived

Every row is read by `python3 scripts/cli_cost_census.py --at <pin> --json <sections>` at both
pins, P (`3330a5a`) and the authoring pin (`17d83e0`). A structural row must reproduce exactly.
A windowed row may differ only by the pull requests between the two pins (#714 to #718).

| Authoring row | At `17d83e0` | At P | Verdict |
|---|---|---|---|
| Lines | 17,790 | 17,817 | exact; +27 by #715 |
| Functions / public / classes / `cmd_*`; the largest eight | as the table | as the table | exact |
| Replay conflicts on cli.py | 1 of 511 (`42cd25d4c`, #57), drivers on | 1 of 514 | exact under both instruments; +3 catch-ups at P (#714, #718) |
| Replay conflicts, any file | 150 of 511, drivers on (156 drivers off) | 150 of 514 drivers on, 156 off | exact (lane-side). Beside it, `merge_cost_census.replay_all` over every pull request's catch-ups, drivers off: 136 of 469 at `17d83e0`, 136 of 472 at P, cli.py 1 (#57) under both |
| Concurrent cli.py PR pairs, 30 days | 3 (429/430 unplaced, 588/589, 668/669 different functions) | 3 | exact |
| Lines a lane reads (`lane_read`) | 37 lanes, median 345, max 2,784 over the pin's 30 days; 36, 337, 2,784 without #319 | 36 lanes, median 337, max 2,784, summed 26,298 | exact: #319 falls inside the pin's window and outside the authoring's clock window. An insertion is placed by its line alone (an L+1 fallback read 2,816 and was a defect, removed) |
| Declared holds | 1 (`479698`) | 1 | exact, once the dispatcher's own claims are excluded (`66aaa6` was one) |
| Importers outside tests | 62 | 65 | **reproduced under the authoring's rule**, which sums each file's from-imported names over the 7 files. The census counts the union across files plus the names loaded through an alias (`doctor`'s `_cli.X`, `generate_doc_regions`' `cli.X`): 56 from-imports + 9. The pack's label "distinct names in all" was wrong. The census's 65 stands for Task 3 (air, ack `491050`) |
| Patches of another module through cli | four | 8 sites, 3 targets, 3 files | **reproduced under the authoring's rule**, a same-line text match of `setattr(cli.<module>`, which misses four wrapped calls in `tests/test_cli_commands.py`. The census reads by AST, and its 8 stand (ack `491050`) |
| Catch-ups carrying cli.py, 30 days | 54 | 48 at `17d83e0`, 49 at P | **reproduced under the authoring's rule**: 48 catch-ups plus 6 other lane-side merges (stacks and merges of a commit) = 54. The census counts `merge_cost_census.CATCH_UP` alone. Context, never graded |
| Cross-seat claim-overlap lane pairs | 18 (stated over 30 days and over about 42) | 10 over the 30 days to P; 9 over 30 days to `17d83e0`; 20 over 2026-10-06 to `17d83e0` (a claim-side rule: 20 over 71 lanes) | **NOT reproduced** under either stated window. Item 1's refuting result, re-raised (request `651334`) and put to the operator by the dispatcher as call `20261118T032647Z-air-7a763a` (continue, recommended, or stop). The 18 grades nothing: C2 is graded from the census over the 30 days to P |

Items 2 and 3 were graded after that call's ruling: (A), continue, by the operator at
2026-11-18T08:07Z (ack `20261118T080812Z-air-2bef6b`). The 42-day C2 share (31 of 71, 43.7%) is
context and stays out of the graded section.

### The transcripts read, diagnosed (Item 3's oracle, before any grade)

**The first read at P** (census at `aa3fa7d01`, the counting rules as committed): 194 merged lanes
of air and air-work in the window; 15 treatment lanes, 126 control; median R 33 lines against
median E 275; 6 of the 15 cli.py lanes read R = 0; 8,729 of the seats' own calls landed on no
lane.

**What the unplaced calls are** [verified, a dump of every call the census reads, attributed by
its own rule]: 8,504 are the dispatcher's own calls on `main` in the main checkout outside any
claim window of its lanes (board, review and pack-authoring reads), and 225 are air-work's. They
are not lane reads lost by a defect, with one exception: the dispatcher's own lanes, below.

**Why six cli.py lanes read R = 0**, each by a hand read of its sessions:
- **#357, #429, #540:** the seat delegated the cli.py work to a fork in its own git worktree.
  The seat's own R = 0 is genuine under the committed rule (own reads only, since threshold (a)
  is the seat's context budget). But the forks' reads were lost to the subagent figure beside
  it: a fork's worktree was gone by the read, so its files mapped to
  `.claude/worktrees/agent-*/espalier/cli.py`, never to the CLI module. **A census defect**, fixed.
- **#530:** built in a scratchpad clone (`.../scratchpad/d5087/`) while the seat's checkout stayed
  on #527's branch after #527 merged (17:10Z). The worktree's reflog holds it on that branch from
  16:04Z to 18:47Z. The committed rule takes a record's `gitBranch` on its word, so #530's calls
  went to #527, a control lane: Task 9's "attribute a session to the seat's other lane", found
  in the record. **A census defect**, fixed: a merged lane's branch yields to the one other claim
  the seat holds after that merge. The scratchpad copy's reads map onto the repo path where the
  rest of the path is a file at the pin.
- **#512:** read through `git diff ... -- espalier/cli.py | sed` and grep (a search, counted apart),
  plus a fork.
- **#349:** the dispatcher's lane (below).

Two more defects, found and fixed in the same pass: a redirection's target (`cat > file <<EOF`)
was read as a read operand, which counted 1,857 writes as calls; and the population block
counted every line of each transcript, so a live session appending after P would change a
re-run's section (Pass criteria). It now counts the records stamped at or before P.

**The hand sample** (the five lanes named at step 1, 349, 504, 661, 324 and 463, each against its
own commits, claim windows, merge and the seat's calls in its build span, with the times in UTC):
- **air-work, 3 of 3 confirmed** (#504, #661, #463). Each lane's calls are on its own branch from
  just before its claim until its release. Reads of its files that went uncredited are on the
  seat's neighbouring lanes, as those lanes' own work.
- **air, 0 of 2 confirmed** (#349, #324). The dispatcher builds a lane on `main` in its own
  checkout and claims it at the commit. #349's 36 calls, which read 1,607 lines of its own files
  in the six hours before its claim, are unattributed (the census credits it 1 call and 0 lines),
  and so are #324's 16 calls and 2,305 lines (credited 9 calls, 2 lines). No signal in the record
  places them: the branch is `main` and no claim is live.

So by the refutation committed at step 1, the section is **unread for the two-seat population**:
the attribution cannot be confirmed for air's lanes. The reads below are reported for the record
and graded on nothing until the call's ruling:

| Read at P | n_t / n_c | median R | median E | realised MDR | by the committed rule |
|---|---|---|---|---|---|
| Census at `aa3fa7d01` (as committed) | 15 / 126 | 33 | 275 | 6.35 | unmeasured |
| Census at `e592d0b5f` (the defects fixed) | 15 / 126 | 42 | 277 | 6.31 | unmeasured |
| Census at `ae313a4a8` (the review folds) | 15 / 126 | 42 | 277 | 6.24 | unmeasured |
| Census at `e26e0f25f` (the second fold) | 15 / 126 | 42 | 277 | 6.24 | unmeasured |
| air-work alone, the confirmed seat (**post hoc**, not pre-registered) | 14 / 82 | 88 | 558.5 | 4.21 | unmeasured |

**What moved from `e592d0b5f` to `ae313a4a8`, and why** [verified: two runs on this box at P,
2026-11-18 08:21-08:30Z, each rc 0 with empty stderr]. The census as it stood before the review
folds (`dd00ad351`'s copy), run again in the same window, reproduces the `e592d0b5f` row in every figure: 194
lanes, 15 / 126, median R 42, median E 277, MDR 6.31, 7,854 unattributed, subagent R 6,786. So
the transcripts did not change, and the move is the code fixes' alone. Those fixes were made
**after these reads had been seen**:
- fold items 14, 15 and 24 (`5bb09b9e3`): a `#` comment line no longer drops the rest of a
  multi-line command; the splitter joins continuations, leaves here-strings alone, counts a file
  fed on stdin, and skips `head -c`'s count and git's global options; a `Read` that reports 0
  lines counts 0;
- the heredoc scanner (`ae313a4a8`): a `<<` the shell does not read as a here-document no longer
  drops the command's later lines;
- `skipped_never_named` (`ae313a4a8`): a fork's worktree with no transcript folder is listed
  instead of refusing the read. It is empty at P.

Lane by lane: R and the search calls are unchanged on all 15 cli.py lanes, and so is subagent R.
E moved on 11 control lanes (10 up and 1 down, net +51 lines) and on one cli.py lane (+1); median
E stays 277. The seats' own read calls fell from 28,179 to 27,697, the unattributed from 7,854 to
7,814, and the calls moved off a merged branch from 117 to 109. So the MDR moves (6.31 to 6.24)
only through the spread of ln E (pooled SD 2.709 to 2.691), and the verdict stays unmeasured.
Beside it, never graded: with only the control lanes that edit a Python file, the MDR moves from
3.60 to 3.56.

**What moved from `ae313a4a8` to `e26e0f25f`, and why** [verified: one run on this box at P,
2026-11-18 09:41-09:47Z, empty stderr, the JSON whole; compared lane by lane with `ae313a4a8`'s
run of 08:30Z]. The input is the same: the population block lists the same 391 and 206 files with
the same record counts at P. The mail refs read are later oids, and each holds the earlier one,
cut at P by its messages' own stamps. So the move is the second fold's code alone, and that fold
was made after these reads had been seen. Its reader items (stdin, `git show` paths,
`head --lines`, refused `Read`s, a here-document's delimiter) are where a line count can move.
Which item moved which lane is not read [probable].
- R and the search calls are unchanged on all 15 cli.py lanes.
- E moved on one cli.py lane (#530, 371 to 510) and on five control lanes, four up and one down,
  net +77 lines (#353 +34, #461 +14, #591 +25, #632 -1, #654 +5). The total lines read moved
  on two of those control lanes (#591 +1, #632 -1). Median E stays 277. The pooled
  SD of ln E moves from 2.691 to 2.692, and the MDR stays 6.24. With only the control lanes that
  edit a Python file, median E moves from 888 to 889 and the MDR stays 3.56.
- Subagent R moved on one lane (#669, 3,761 to 3,888), so the forks' sum is 6,913.
- The seats' own read calls rose from 27,697 to 27,698 and the subagents' from 31,138 to 31,140.
  The 7,814 unattributed calls and the 109 moved off a merged branch are unchanged.
- Two counts are newly disclosed, each beside the figures and never a grade:
  - `calls.unlexed`: Bash commands the lexer refuses, own 17 and subagents 5. They book no read
    and are named under `unread`.
  - `calls.heredoc_tag_missed`: own 4 and subagents 2. These are candidates where the scanner may
    have read a here-document's body as commands. They still book reads, so a count can be wrong
    in either direction, and they are a count to look at, never a verdict.

  None of them holds a CLI module's path in its literal spelling (`espalier/cli.py`, a substring
  match). A relative or variable spelling would go uncounted, so "R lost no read to them" is
  probable, not verified. E may be off in either direction on those 21 own commands, unread.
- `skipped_never_named` now lists one worktree, `.claude/worktrees/agent-a0bed478225d3241f`. It
  is this seat's second-fold builder (branch `fold2-census`, commit `7066f5c09`, cherry-picked as
  `e26e0f25f` with the same patch id). It is labelled `air` because it has no per-worktree
  `espalier.machine`, so git falls back to the clone's shared `.git/config`, which names `air`
  [verified, `git config --show-origin`]. It has no transcript folder, so no read is lost. The
  list is read from the checkouts on the box at the run, not at P, and so is the set of transcript
  folders read. So "two runs at one pin print the same section" (Pass criteria) holds only for
  two runs with the same checkouts present.

Beside them, never graded: at `e26e0f25f` the forks' reads of the CLI modules on the 15 lanes sum
to 6,913 lines. That figure was 6,786 at `ae313a4a8` and 1,635 before the worktree fix. air-work's
median R plus its forks' reads is 416. Search calls on the CLI modules: 77. The air seat has one
cli.py lane in the window (#349), so the reading cost on this box is in effect air-work's, as
step 1 said.

**The scope of R against E** (F5 of Task 9's reasoning review) [verified, the code:
`scripts/cli_cost_census.py`'s transcripts row books a line to `r` when its path is a CLI module,
and to `e` when its path is one the lane edited].
- R counts the lines read of the CLI modules, which is one module at P (`espalier/cli.py`).
- E counts the lines read of every file the lane edited, docs and tests included.

So R < E is likely by construction: a cli.py lane's reads of its own tests, docs and other
modules are in neither its R nor any control lane's E. Three reads at `e26e0f25f`, each beside
the grade and never graded:
- *R's share of the lane's total lines read* (`beside.r_share_of_total`, step 1's beside
  figure), per lane in PR order: 0, 0, 0.017, 0.236, 0, 0.17, 0, 0.134, 0, 0.026, 0.002, 0.033,
  0.336, 0.284, 0.58. The median share is 0.026: on 8 of the 15 lanes, cli.py was 2.6% or less of
  what the seat read.
- *On the same scope*, every edited file (post hoc): the cli.py lanes' own E has a median of
  1,412. That E counts every file they edited, cli.py included. The control lanes' median E is
  277, or 889 for the 71 that edit a non-test `.py` file. The medians of all lines read are 2,373
  against 1,469.5 (2,108).
- *What this does not say* [probable: the medians; the cause unmeasured]:
  - how much of that gap is lane size, since a cli.py lane may edit more files;
  - how much is file size. Step 1's control rule leaves out any lane with a non-test `.py` file of
    3,000 lines or more at its merge-base (`CONTROL_MAX_LINES`), while every cli.py lane edits a
    file of 17,817 lines;
  - how much is cli.py itself.

So on the same scope, the cli.py lanes read more, not less. The direction that R against E
suggests cannot be told apart from the scope difference, and this design reads no direction for
a relative reading cost. What it can bound is the absolute one, below.

#### Item 3's (a) alone

**Post hoc, never graded** (F2 of Task 9's reasoning review). Threshold (a) is a bound on R alone:
median R ≥ 1,500. It needs no E, no control lane and no minimum detectable ratio. Item 3's two
causes of *unmeasured* sit elsewhere:
- the MDR is the comparison with E, (b) and (c);
- the attribution fails on air's lanes, and only one of them (#349) is a cli.py lane.

So (a) can be read on its own, with #349 taken at its hand read.

- **The 15 R values at `e26e0f25f`**, ascending: 0, 0, 0, 0, 0, 8, 33, 42, 134, 165, 187, 403,
  897, 1,057, 1,951. #349 is one of the five 0s.
- **#349 at its hand read.** The census credits #349 with 0 lines. Its sessions read 1,607 lines
  of the lane's own files in the six hours before its claim (the hand sample above). The lane
  edited 49 files, `espalier/cli.py` among them, so at most 1,607 of those lines are R. How many
  were cli.py's is not read. Taking all 1,607, the values become 0, 0, 0, 0, 8, 33, 42, 134, 165,
  187, 403, 897, 1,057, 1,607, 1,951. The bound below does not rest on the hand read: x(12) is at
  most 897 whatever #349's R is, and at most 1,128 whatever its R plus forks' reads is, since
  #349 then sits above the 12th of the other 14.
- **The bound.**
  - The rule: for any distribution with median m, the k-th smallest of n draws, x(k), falls below
    m only when k or more draws do. So P(x(k) ≥ m) ≥ P(Bin(n, 1/2) ≤ k - 1), and ties at 0 only
    raise the coverage.
  - For n = 15, the smallest k at 95% is 12: P(Bin(15, 1/2) ≤ 11) = 0.982, against 0.941 at
    k = 11. So x(12), the 4th-largest, is a one-sided upper bound on the population median R at
    98.2% or more: the median R of air-work's cli.py lanes, assuming the lanes are independent.
  - The bounds, each under 1,500:

    | R as read | x(12), the bound at 98.2% or more, one-sided |
    |---|---|
    | the census's R | 403 |
    | with #349 at its hand read | 897 (at most 897 for any value of #349's R) |
    | R plus the forks' reads, #349 at its hand read | 1,128 (at most 1,128 for any value of #349's) |

    The third row adds the forks' reads, which threshold (a) does not price and step 1 put beside.
    It is the largest reading of the seat's cli.py cost any figure here supports.
- **What it assumes** [judgment]:
  - It treats the 15 lanes as independent draws from one population of cli.py lanes.
  - They are not independent: one seat ran 14 of them one after another, and its habit of handing
    cli.py work to forks carries from lane to lane. How much that narrows the true coverage is not
    read.
  - They are the window's whole set of cli.py lanes for two seats, and 14 of them are
    air-work's. So the bound speaks for air-work's way of working over these 30 days. It does not
    speak for a seat that reads otherwise, or for the Windows seats.
  - The hand sample confirms air-work's attribution, 3 lanes of 3.
- **What it is, and is not.**
  - The order statistic and the level were chosen after the R values were seen: the reasoning
    review proposed this read after the first read at P. It changes no verdict. Item 3 stays
    *unmeasured*, as step 1 grades it, because step 1 allows *not real* only with an MDR at or
    under 2.0.
  - It bounds the size of the seat's cli.py reading. It says nothing on (b), the cost relative to
    other files.
  - It is a candidate for the next pin's pre-registration, never a change to step 1's.
- **The next pin's design** (named here, not committed) [judgment, untested]:
  1. The bound on (a) alone as above, committed before the read: *not real on (a)* when the 95%
     upper bound on median R is under 1,500, whatever the MDR.
  2. For (b), a within-lane paired design: each cli.py lane's reads of cli.py against the same
     lane's reads of its other edited files. Pairing within a lane drops the between-lane spread,
     which is the obstacle named in *How far a decidable read is*.
     - The unit of the comparison is open. Per line of the file decides the direction in advance:
       a 17,817-line file read in slices always shows a small rate, and a small file read whole
       shows a rate near 1. That measures coverage, not context cost.
     - Lines read per edited symbol or per hunk is one candidate. Pairing against lanes that edit
       another large file is another.

  Who authors that pre-registration, and when, is left to air's call on TP-708's later waves.

### Task 0 Item 2 at P: the collision read

Every figure is from `python3 scripts/cli_cost_census.py --at 3330a5a collision --json`, with the
census as at `ae313a4a8` [verified: run 2026-11-18 08:37-08:41Z, rc 0, empty stderr, no part
unread]. The window is the 30 days to P, with 36 cli.py pull requests in it. Every pull request
from all four seats is counted (the mail and the pull requests are not per box). The mail refs
are read as of the run, and each message is cut off by its own stamp at P. Thresholds are the
ones committed at step 1.

| Component | Read at P | Threshold: real at or above | Known before step 1 | Grade |
|---|---|---|---|---|
| C1. Concurrent cli.py pairs whose verdict is not certified | **1** (#429 / #430, `unplaced`). Beside it, two `different functions` pairs (#588 / #589, #668 / #669) are certified; no pair was `shared symbol` | 4 | 3 pairs, all verdicts [probable]: **reproduces**, 3 concurrent pairs | not real |
| C2. Share of cli.py lanes whose claim window overlaps another seat's live claim on cli.py | **15 of 33 = 45.5%**. 3 lanes had no claim (#336, #491, #531). Over all 36, 41.7%. All 15 are also strict overlaps (the lane's own claim names cli.py). 10 cross-seat lane pairs | 50% | 18 pairs over about 42 days [probable]; not reproduced at P (10 in 30 days), recorded under 7a763a | not real, **near the threshold** |
| C3. Dispatcher holds over a cli.py overlap, whole record | **2** by hand read (below), over the mail's 43.6 days (from 2026-10-05T10:27Z) | 8 (1 per 7 days over about 54 days) | 1, a lower bound [verified] | not real |
| C4. Replay conflicts on cli.py, whole record | **1** (`42cd25d4c`, #57, 2026-10-01): in 472 catch-up merges over 706 pull requests, and in 514 lane-side merges with drivers off and on alike | not graded (floor 1 in 511) | 1: **reproduces exactly** | not graded |

**C2 sits 4.5 points under its threshold, and the margin is two lanes.** 17 of 33 is 51.5%. The
three lanes with no claim have no window, and the committed rule leaves them out of the graded
share. If all three had overlapped and been counted, the share would be 18 of 36, exactly 50%.
The grade is *not real* by the committed rule. A later window can cross it without any change in
how the seats work.

**C3's hand read.** The census lists 19 candidates: 1 declared (the message's paths name cli.py
and its text holds a lane), and 18 where the module is named only in the text. Each was read in
full against the rule (a dispatcher message whose text holds one lane for another's, over cli.py).
The prior window's hand read also found 2, and these are the same two:
- `20261117T191812Z-air-479698` (declared): win's DEF-985 lane and air-work's DEF-5118 lane meet
  at cli.py; "the first to open goes; the other waits for it to merge".
- `20261010T225709Z-air-95186b`: win-2's upgrade lane is gated ("your first edit waits until
  #177 ... is MERGED"); #177 is air's lane, and it edits cli.py.

The other 17 hold nothing over cli.py (ids by their suffix):
- 2 say only that the second to merge runs catch-up, which is not a hold (`703425`, `37b3b6`).
- 8 order the seat's own lanes: one open pull request per seat, or a lane built on the seat's
  earlier one (`516427`, `38360b`, `a58fb5`, `36ebc6`, `73bb69`, `9587c6`, `a59c5c`, `f6ff33`).
  Three of them also say the second to merge catches up.
- 3 hold something other than cli.py: the ledger's format (`16625d`), three guard files
  (`79e19c`) and a tier slot on the box (`647932`).
- 4 hold nothing at all: a ruling (`d26d85`), an operator call (`cc862b`), its forwarding
  (`c7fb7e`) and a held row candidate (`130130`).

Two holds in 43.6 days is one in about 22 days. The committed figure of 8 assumed about 54 days of
record, from the first merge. The mail starts 11 days later, where the same rule gives 7. The
grade is the same under either figure, and the committed 8 stands.

**Item 2: not real.** No graded component is at or above its threshold: C1 1 against 4, C2 45.5%
against 50%, C3 2 against 8. C2's margin is the one to watch.

**Graded on point estimates, which Item 3 is not** (Task 9's reasoning review; the arithmetic
re-run here [probable]). Item 3 needs a decidable read. Item 2 is graded on its counts as read. At
95% one-sided:
- C1's 1 has a Poisson upper bound of 4.74, at or over its threshold of 4;
- C2's 15 of 33 has a Clopper-Pearson upper bound of 61.1%, over 50%;
- only C3 is decided: its 2 has an upper bound of 6.30, under 7 or 8.

So *not real* is the committed rule's grade, and it stands. But it is not a bound that excludes a
collision cost, and it does not by itself support striking `DEF-4123` for collisions.

**The own-lane bucket, re-read** (Task 9's reasoning review; verified, the three messages in the
dispatcher's mail). Three of the 8 that "order the seat's own lanes" hold one of a seat's
cli.py lanes for its other (`516427`, `38360b`, `f6ff33`). The committed rule reads a hold as one
lane held for another's, and these were read as the seat's own ordering. Counted as holds, C3 is
5, still under 7 or 8: the grade does not move.

Beside them, never graded: 49 of the window's 246 catch-up merges carry cli.py.

**The census's mail refs at P** (the collision run's `pin.mail_refs`, 08:37-08:41Z [verified,
its output]). The run read four seats, each cut at P by its messages' own stamps:

| Seat | Mail ref read |
|---|---|
| air | `10f67fc59ef3744b8504919695b6827dd22b359d` |
| air-work | `801c51e766d69fbdec45aef6a06f241e5e2ca431` |
| win | `70319476b7f5c1296223ed441d45aff04f650d0d` |
| win-2 | `ccf326526f8e48b2cc89f0a3b7769cd34badc973` |

Mail refs only grow, so a later ref holds each of these. Before Task 9's reasoning review, a
clone holding only some of the refs read C2 and C3 over those seats alone, with nothing unread:
the reviewer's clone held 2 of 4 [verified, its run]. The census now names a seat the mail names
whose ref the clone lacks as unread.

### Task 2: the accretion read, the eight longest definitions at P

The same eight as at authoring, at the same lengths, at P and at `17d83e0` [verified, by AST at
both pins]. Only the offsets past `::deploy_harness` moved (+27, from #715's `2e50d259b`, which
touches none of the eight).

**The mechanical cues** [mechanical], each read on the definition's exact AST span at P:
- the `DEF-\d+` and `TP-\d+` ids cited inside the span;
- its commits, from `git log -L <start>,<end>:espalier/cli.py 3330a5a`. The span is given by
  line, because no Python diff driver is configured and the `:funcname:` form runs past the
  function's end;
- the string literals of 30 characters or more it shares with `espalier/doctor.py` at P;
- the deploy helpers it calls.

The history at P is short. The repository's root commit is `d00f6de45`, the seeded public tree of
2026-09-24, so `git log -L` covers about eight weeks. The history before it is read from
`archive/main` (`238a00ab1`), whose cli.py is byte-identical to the seed's. Of the commits traced
after the seed, 2 name a row in their message, so the ids are read from the span's text, not the
log.

**The branches and their classes.** A branch is an `if`/`elif`/`else` arm, a loop or a `try` at
the first or second nesting level, 20 lines or more. A first-level branch with second-level
children is classed on its own lines, so the branches partition the lines they cover. Each one is
classed by a reader in its own context [hand]: (a) a row's special case, (b) logic duplicated
with doctor, (c) the function's own work.

| Definition | Lines at P (at the seed) | Ids cited | Commits, at P / before the seed | Shared doctor literals | Branches by class: count/lines | Dominant: branches / whole |
|---|---|---|---|---|---|---|
| `::cmd_upgrade` | 929 (498) | 26 | 41 / 26 | 0 | a 5/363, b 1/21, c 5/304; the rest 241, c | a / c |
| `::build_parser` | 890 (836) | 1 | 14 / 70 | 0 | 18 subparser blocks, c 660; the rest 230, c | c / c |
| `::deploy_harness` | 344 (264) | 4 | 13 / 43 | 0 | c 3/114; the rest 230, c | c / c |
| `::cmd_init` | 337 (211) | 9 | 22 / 54 | 0 | c 1/77; the rest 260, c | c / c |
| `::cmd_scope_check` | 311 (311) | 3 | 2 / 14 | 0 | a 1/80, c 3/46; the rest 185, c | a / c |
| `::cmd_scan` | 304 (260) | 1 | 5 / 22 | 0 | c 2/128; the rest 176, c | c / c |
| `::_print_init_summary` | 293 (233) | 7 | 19 / 18 | 0 | a 2/77; the rest 216, c | a / c |
| `::_detect_python_command` | 284 (128) | 8 | 12 / 11 | 0 | a 2/104; the rest 180, a | a / a |

"Commits at P" includes the seed commit. The 0 shared doctor literals is a real zero: the same
check finds 7 shared-literal sites elsewhere in cli.py [mechanical], and those, not these eight,
are where Task 5's boundary should look.

**What the read finds** [hand, unless tagged]:
1. **`::cmd_upgrade`'s "nothing to do" arm is row special cases, not doctor duplication.** It is
   216 lines: a stack of about 12 guards, each added by a row that found "nothing to do" false
   (`DEF-715`, `DEF-798`, `DEF-929`, `DEF-618`, `DEF-3088`, `DEF-2007` and `DEF-4071` among them).
   It grew from 97 lines at the seed, over 17 commits since [mechanical]. Where it checks what
   doctor checks, it calls doctor's own functions, so moving it into doctor.py would remove no
   duplicate. A table of check, clause and remedy is the natural cut (a hypothesis, untested).
2. **The one (b) branch is small.** It is 17 lines in `::cmd_upgrade`: the unstamped-seed note,
   with the same state and the same remedies doctor prints. The two texts have already drifted
   apart [verified, read at P].
3. **`::_detect_python_command` is row special cases throughout.** It holds a 77-line docstring and
   has more than doubled since the seed (128 to 284 lines) [mechanical]. Its fallback order, nine
   ranked returns, lives in control flow. It writes `_BELOW_FLOOR_ANSWER` and
   `_VENV_FALLBACK_OUTSIDE`, and doctor imports it. So any move takes both globals with it and
   keeps the doctor cycle (Task 2's step 2, Task 5).
4. **The alternative "decompose only `::cmd_upgrade` and `::build_parser`" prices two unlike
   things.** `::build_parser` is declaration: 324 of its 890 lines are help text, and it cites one
   id (`DEF-772`). `::cmd_upgrade` is accretion.
5. **The growth is concentrated.** The eight grew by 951 lines since the seed. 853 of them are in
   upgrade, init, deploy, the summary and the resolver [mechanical]. `::cmd_scope_check`'s 80-line
   row branch predates the seed and has had no commits since [mechanical].

The read ran in a scratch directory. Its scripts and per-branch list are not in this lane
(Files touched), so a re-run rebuilds them from the rules above.

### Task 4: the raising-sentinel sample

**The population** is the census's own `patch_sites` at P, loaded read-only: 149 direct patch
sites on 43 targets in 19 files, plus 8 sites that patch another module through cli, 157 in all
[mechanical]. The `_INTERPRETER_WARNING_EMITTED` figures match the pack: 45 sites, 39 of them
`raising=False`. The population is as the census read it when the sample was drawn: its rule
has since been widened (Task 3's test patches) and reads 150 sites on 44 targets. The 44th,
`_git_ignorecase` (one site in `tests/test_bounded_spawn.py`), was not in the draw.

**The sample** is 56 sites, drawn by a fixed rule, never by hand:
- the first site (by file, then line) of each of the 43 targets;
- all 8 sites that patch through cli;
- 5 `raising=False` patches of `_INTERPRETER_WARNING_EMITTED`, at evenly spaced indices of the
  sorted list, the sites already drawn removed.

**Each site's tests.** The test the site sits in. For a site in a shared helper, up to 3 tests
whose text holds `helper(` as a substring. This rule was stated only after the review asked for
it. Three lists were set by hand:
- sites 0 and 28 had no candidate, and both were set before any result;
- site 51 first ran 3 tests (5 nodes) and read green, then was re-run with 6 tests (8 nodes),
  which is the conservative direction.

The substring rule matched `_host(` inside `build_host(`, so one of site 51's six tests never
runs the patch, and the stderr it reads is a subprocess's. Site 51's verdict, inert, stands on
its other 7 nodes [the test-infrastructure review, verified].

**The method.** It ran in a fresh clone at P, never in a live checkout. For each site, the patched
value is replaced by a sentinel that raises on any use and logs where it is used. The site's tests
run green first, and each run imports espalier from the clone. That import goes through the
`work` worktree's interpreter with `PYTHONPATH` set to the clone. The review re-ran 10 of the
verdicts in a venv of its own, and none moved.

**The result** [measured, at P]:
- **49 sites go red, so their patches are read.** 48 are read by the code under test. The other,
  site 0, is conftest's teardown restore, read by the next test's assertion. All 8 through-cli
  sites are among the 49.
- **7 stay green, and each is read by hand, never counted as vacuous.**
  - 3 are live. One of them is called by cli, which swallows the sentinel's error; the original
    patch value raises too, so the sentinel is the same input. The other two assert that a
    recorder was not called. With the defect each test guards seeded, both go red, and the
    sentinel is read.
  - 4 are inert. The patched value is never read on the test's path, and the test's claim does
    not depend on it. One function resets `_BELOW_FLOOR_ANSWER` itself before reading it; two set
    the warn-once flag on paths that never warn; one asserts a refusal message the flag does not
    control, and a seeded refusal turns it red with the flag never read.
  - Inert does not mean the patch can be left un-repointed. Site 38's patch isolates
    `_BELOW_FLOOR_ANSWER`, and under re-exports it would restore a stale copy. Wave 1's "reads or
    writes" rule covers it.
- **Vacuous: 0 of 56.** The pack expected 0 [probable], and it holds on what was drawn. Two of
  the three strata are censuses, not samples: each target's first site (43 of 43) and the
  through-cli sites (8 of 8). So "0 vacuous" is a fact about those 51 at P.
  - The warn-flag stratum draws 5 of 39. Read as a random draw, 0 of 5 does not exclude a vacuous
    share near 45%.
  - Its green rate, 3 of 5, is unlike the censuses' (4 of 43, 0 of 8), so the strata do not pool.
  - 101 direct sites were never drawn: 62 later sites of the other targets and 39 more warn-flag
    sites. They are unread, beyond the name-level rule.
  - The draw is thin in late-alphabet files: `tests/test_python_floor.py` holds 51 of the 157
    sites and 10 were drawn.

  [the test-infrastructure review]

Across all 88 test nodes the sample ran, 20 stay green under the sentinel. Five of those sit
inside shared helpers that reach the code in some tests and not in others:
- four are inert by reading: one re-patches the helper's target itself, one reads no stderr, and
  two run before the teardown restore's reader;
- the fifth was not hand-read at first. It is
  `tests/test_cli.py::TestARemedysProgramWordRunsInEveryShell::test_a_spaced_interpreter_on_windows_is_its_short_path`,
  green under site 9's patch of `_POWERSHELL_CALL_NOTE_SAID`. It asserts the PowerShell note is
  absent, and that latch arms exactly that note.

The review seeded the defect the fifth node guards (`::_remedy_program_word` without its
`word.startswith('"')` clause) and read it three ways:
- the original patch reds with the test's own message;
- the sentinel reds, and is read;
- with the latch patched to `True`, the test is green with the defect present.

conftest does not restore this latch, so the test goes vacuous in suite order if the patch is
dropped or mis-pointed. That is the shape of sites 36 and 41.

**What a red licenses: read, not guarded** [verified, the review's deletion arm, its raw results
recounted here]. Each sampled patch statement was replaced by `pass` and its tests run. 25 of the
56 stay green:
- by verdict, 19 of the 49 that go red under the sentinel and 6 of the 7 greens;
- by stratum, 14 first-of-target, 6 of the 8 through-cli and all 5 warn-flag sites.

No red came from the edit itself. The greens stay green because the patch equals the shipped
default, a stub already on `PATH` answers the real lookup, a sibling patch sets the same value, or
the real value matches on this host.

So a red says a patch is read, not that its test would notice the patch missing. At those 25 sites
a test run cannot tell a re-pointed patch from one left on cli's stale copy. That is the
refutation Task 4 names for wave 1's contract:
- its oracle is the static re-pointing check on the lane's diff, never a green suite after a
  move;
- its earn-the-red is seeded at a site whose deletion reds (30 of the 56 do) [probable].

Two limits on the arm: each test ran alone, so a reset patch that guards suite-order state reads
green here; and it ran on this host, so a host-pinning patch may go red on a Windows cell.

**What it cannot see** [the review's op table, measured]:
- **Unseen:** `is None` and `is True`, `type(x)`, `callable(x)`, `id(x)`, `isinstance(x, object)`,
  membership in an empty container, and forwarding the value into a list or dict.
- **Seen:** `==`, truthiness, `isinstance(x, str)`, `hasattr` and a call.
- **Swallowed:** `except Exception` swallows the raise, but the log keeps the read.

That is why every green with no logged read was checked by hand. A patch through cli onto a
process-wide module (`cli.sys`, `cli.shutil`) reds without saying who read it. Site 50's first
reader is the hook, not cli, and its patch duplicates a sibling's (`mm.sys` is the same `sys`).
Every cli name exists at P, so the hazard of `raising=False` does not show yet: it appears after a
move without re-exports. Two of the 5 sampled `raising=False` patches are read today and would
then miss silently. That is Task 4's re-export branch, priced below.

**One test defect, found and filed** (`DEF-5127`, §C0, minor): in
`tests/test_python_floor.py::TestFloorAtTheThreeDecisionSites::test_detect_python_command_does_not_promise_working_guards_on_python_2`
the recorder over `::_warn_interpreter_below_floor` takes one argument, and its one caller passes
two. With `DEF-727`'s shape seeded back, the test fails with a `TypeError` and its assertion never
runs. The row is not a vacuous patch, so it is outside the one case Files touched names. The
dispatcher kept it on the lane (ack `20261118T040752Z-air-ff0cf7` on request `71f10f`): the
lane's own sample found it, and it was filed through the same verb. Landing names its two files as a
deviation from the Files-touched pass criterion. The test itself stays unmodified, as Files
touched requires.

The test-infrastructure review re-ran the row's arms: the defect, the fix shape, and the fix with
the defect seeded all hold. It also found that the filed probe read the spelling, not the fix: it
printed 0 on `lambda *a, **k: None`, the empty stub the row warns against, which passes with
`DEF-727` seeded.

The probe was re-pinned through `tools/cc/ledger_row.py repin`. It now reads closed only on a
recorder that takes the caller's two arguments and still appends to `below_floor_calls`. Dry-run
on six variants of the test file, it reads open on the file at P, on the empty stub and on the
test renamed away, and closed on three correct fix shapes [verified]. The fix shape now takes
keywords. The row's "not a class" is widened to stub arity against call sites over the 157 sites:
of 103 callable stubs, it is the only one that mismatches every call site.

**Task 4's two counts overlap; they are not a split** [verified, the census's `patches` section at
P]. Task 4 names 31 targets with more than one loader (131 sites) and 12 that cli imports from
elsewhere (30 sites). The census first read the same four figures; since its rule was widened
(Task 3's test patches, below) it reads 32 targets with more than one loader (132 sites) and
the same 12 (30 sites). They sum to 162 sites against the 150 in all because the two sets
overlap: 10 of the 12 imported names also have more than one loader. The 44 add up by
coincidence. The partition at P, the one new target in its first row:

| Targets of the 44 | Targets | Sites |
|---|---|---|
| More than one loader, defined in cli | 22 | 105 |
| More than one loader, imported into cli | 10 | 27 |
| One loader, imported into cli | 2 | 3 |
| One loader, defined in cli | 10 | 15 |
| All | 44 | 150 |

This read was first sent to the dispatcher as an inconsistency (request `71f10f`). It is not one.

The sample ran in a scratch clone. Its harness is not in this lane (Files touched). A re-run
rebuilds the draw from the rule above and the test lists from the selection rule, plus the three
lists named as set by hand.

### Task 3: what a move touches, read at P (the per-unit join follows)

Each figure is from `python3 scripts/cli_cost_census.py --at 3330a5a --json <section>`, and each
section names its rule in its output. Two runs at P (the builder's and mine) printed the five new
sections equal as data. Their 20 mutants were all killed on the lane's copy, against a green
control of 75 tests.

- **Importers** (`importers`): 65 names from 7 files outside tests (the census's union rule;
  Item 1's table has the authoring's 62 beside it). Tests import 242 distinct cli names from 101
  files, which is the figure Task 4 quotes. The unreproduced 101 of the regex reads is dropped, as
  Task 3 says.
- **Test patches** (`patches`): 150 sites on 44 targets in 20 files (147 `setattr`, 3 direct
  assignments), no string targets, and 8 more that patch another module through cli. The
  partition is under Task 4 above. **These moved after they were first read** (149 sites on 43
  targets in 19 files, 146 `setattr`): the census's own code review found a patcher the rule did
  not read as cli, `m.setattr(__import__("espalier.cli").cli, "_git_ignorecase", ...)` in
  `tests/test_bounded_spawn.py`, and the widened rule counts it (one site on `_git_ignorecase`,
  defined in cli, three loaders, all in the "init, upgrade and deploy" group). The section now
  also counts apart the 47 patcher calls in 11 test files whose first argument it cannot resolve
  statically (a `getattr(import_module(...))`, a `sys.modules[...]`), so a patch of cli the AST
  read misses still shows; none is counted as cli's.
- **Readers by path** (`readers`), by class:
  - loud: 20 symbol keys in 7 files, 67 path literals in 33 files and 16 `/ "cli.py"` joins in 11;
  - silent: 3 joins in 3 files and 1 literal;
  - flat-module: 1 literal.
  By kind: 20 keys in 7 files, 69 literals in 34 and 19 joins in 14. The census counts each site
  once, so a key's path element is not counted again as a literal; beside that rule, counting it
  gives 89 in 36. Every hand-listed silent and flat-module reader exists at P.
  `tests/test_cli_deploy.py::test_no_naked_write_text_anywhere_in_cli` has no site of its own: it
  reads through the module's `CLI_PATH`.
- **Citations** (`citations`), 737 `espalier/cli.py::X` occurrences in 185 files, a name required
  after the `::`. A plain-text count of `espalier/cli.py::` reads 740. Beside those 737 are 37
  bare `cli.py::X`, 33 dotted `espalier.cli.X` and 17 line-form occurrences. The `path::X` split,
  first match wins:
  - record set: 7 in 1 file;
  - struck: 455 in 96 struck fragments, plus 3 on lines the sweep skips as closed rows;
  - swept-live, which reds after a move: 128 in 34 live fragments and 28 in 7 docs;
  - unchecked-live, which rots with no red: 53 in 12 packs, 6 in `bench/corpus` and 37 in code
    comments;
  - protected zone: 10 in 5 `tools/cc/` files, plus 10 in their `espalier/_vendor/cc/` twins,
    each twin matching its source.
  The parts sum to the 737. The sweep's population rule is ported from P and pinned by a digest, so a change to it makes
  those parts unread rather than wrong.
- **Ledger probes** (`probes`): 24 of the 169 probes read cli, all on live rows: 19 by their
  command and 5 by subject alone. The census counts each way a probe reads cli, so the 19 read it
  23 ways: 11 by import, 8 by path, 3 by running it and 1 by a patch. Four read it two ways:
  `DEF-1001` by import and a patch, and `DEF-1005`, `DEF-736` and `DEF-945` by path and import.
  21 of the 24 also name cli in their subject. The
  rows are `DEF-1001`, `1005`, `1006`, `1021`, `1057`, `1077`, `1079`, `1085`, `1086`, `1088`,
  `2095`, `3096`, `400b`, `4123`, `5089`, `5099`, `5113`, `736`, `930`, `932`, `943`, `945`,
  `947` and `996`. A probe that reads a moved symbol out of cli.py prints a new value, and its
  row is offered as a strike candidate.

### Tasks 3 and 4: the move cost per unit, in both re-export branches, at P

Every figure is from `python3 scripts/cli_cost_census.py --at 3330a5a --json move_cost`, a static
read at P with no window. The section names its rule for each count in its own `rule` block. Two
runs at P printed every figure equal: the builder's, in its own worktree, and mine on the lane's
copy. Their rule text differs by the one sentence added since, named below. It has 110 fixture tests and 51 mutants, each killed by the test it names, against a green
control. Its rules review (in its own context) found 2 BLOCKERs, 3 MAJORs and 5 MINORs, all
folded before these figures were read. The one minor left is named in the rule text: a builtin
`setattr(cli, ...)`, a `create=True` patch and a `patch.dict` on a re-exported memo are not told
apart from a plain patch. `tests/` holds none of them at P [verified, `git grep` at `3330a5a`].

**The units are two cuts, and only one partitions.** The layer rows (each layer's members, and its
tie-closed set) and the concern rows (the two hand groups and the 28 single-command concerns)
price the same definitions two ways, so rows do not add across the two. The concern units own 380
of the 438 top-level definitions at P, and the other 58 are shared or unreached. The census
asserts that no two concern units hold one definition, and that for every ingredient the concern
units plus the rest equal the defined total (`move_partition`). It also asserts that each
ingredient's per-name tally meets its section's own total (`move_sums`). The names each sum sets
apart are listed, not absorbed. Citations, for example: 780 occurrences on names defined in cli, 1
on a name cli imports, and 26 on 21 names cli does not bind, 807 in all. The 21 are placeholders
such as `cmd_frobnicate` and `X`, the prefix `INIT_`, and names cli no longer defines, such as
`get_seed_docs` and `DENIED_PATTERNS`. All 39 `raising=False` patches sit on a target no concern
unit owns: `_INTERPRETER_WARNING_EMITTED`, which is shared.

**What a move touches, per unit** [mechanical, at P]. Citations are split as in Task 3 above,
but counted in all three spellings that name a member (`path::X`, bare `cli.py::X` and dotted
`espalier.cli.X`; the line form names none), where Task 3's split counts `path::X` alone. So the
hand group's protected 24 is 12 sources and their 12 twins [verified, `move_cost`'s `rule`].
Swept-live and unchecked-live are the re-key tool's work list. Protected counts each `tools/cc/`
source with its vendor twin, and that is the Gate A question. Struck and record stay as they are.

| Unit | Definitions (functions) | Function lines | Importers outside tests: names / pairs | Test imports: names / files | Patches: targets / sites | Symbol keys | Citations: swept / unchecked / protected / struck / record | Probes | Doctor names | Back edges (definitions) | Cycles closed |
|---|---|---|---|---|---|---|---|---|---|---|---|
| interpreter core layer, members | 26 (18) | 656 | 4 / 5 | 14 / 10 | 12 / 68 | 0 | 3 / 4 / 2 / 35 / 2 | 0 | 4 | 0 | none |
| interpreter core layer, tie-closed | 34 (24) | 807 | 6 / 7 | 17 / 10 | 13 / 72 | 0 | 3 / 5 / 2 / 41 / 2 | 0 | 5 | 0 | none |
| settings layer (members = tie-closed) | 82 (46) | 1,812 | 14 / 15 | 51 / 30 | 3 / 14 | 3 | 15 / 20 / 12 / 66 / 0 | 2 | 13 | 3 | none |
| deploy layer, members | 101 (70) | 3,637 | 29 / 33 | 55 / 38 | 8 / 18 | 4 | 37 / 35 / 10 / 115 / 1 | 3 | 18 | 28 | `doctor`, `render_surface` |
| deploy layer, tie-closed | 104 (73) | 3,752 | 30 / 34 | 56 / 38 | 9 / 22 | 4 | 37 / 35 / 10 / 118 / 1 | 3 | 18 | 35 | `doctor`, `render_surface` |
| init, upgrade and deploy (hand group) | 323 (225) | 10,929 | 55 / 62 | 163 / 73 | 17 / 47 | 12 | 131 / 91 / 24 / 338 / 6 | 13 | 37 | 22 | `doctor`, `render_surface` |
| scan and scope-check (hand group) | 11 (5) | 658 | 0 / 0 | 5 / 10 | 0 / 0 | 0 | 2 / 5 / 0 / 15 / 0 | 0 | 0 | 2 | none |
| the 28 single-command concerns, summed | 46 (39) | 1,974 | 1 / 2 | 33 / (not summed) | 1 / 2 | 5 | 3 / 9 / 8 / 40 / 0 | 1 | 1 | 51 | `cleanup` (`cmd_clean_generated`), `doctor` (`cmd_doctor`) |

- **One unit moved after it was first read.** The "init, upgrade and deploy" group's patches
  (17 / 47 in 12 files) and its re-export figures below (45 stale sites, 486 and 381 loud) each
  hold one site more than at the first read: the `_git_ignorecase` patch the widened `patches`
  rule counts (Task 3's test patches). The concern sums move with it (150 sites on 44 targets,
  120 on 32 defined in cli, 49 on 18 in concern units). No other unit's figure moved.
- The hand group "init, upgrade and deploy" holds 10,929 of the file's 15,542 function lines
  (70%) and most of every ingredient. It is also the only unit whose members fuse calls with an
  `argparse.Namespace` built by hand (`::cmd_init` and `::cmd_install_ci`), which no parser
  checks.
- Interpreter core is the one unit with no back edge: its members load no cli definition outside
  it, so a new module holding it would not import cli. 41 cli definitions outside it load or
  write its members.
- Settings is the same set under both cuts: its tie closure pulls in nothing.
- The 28 single commands are small: the largest by function lines are `::cmd_memory_prune` (351),
  `::cmd_integrity` (242) and `::cmd_freshness_pin` (232).
- Not attributed to any unit, by rule: 8 patch sites through cli (targets
  `_doctor._interpreter_is_python3`, `shutil.which` and `sys.platform`, none of them a member's
  name), 17 line-form citations, 69 path literals and 19 path joins (they name no symbol), and 9
  probes (4 read cli with no symbol named, 5 by subject alone).

**The two branches, per unit** [mechanical, at P, except the `-m` column]:
- *With re-exports* (moved names stay importable from cli):
  - a stale site is a patch on cli's binding of a target a moved member loads, so the moved
    loader goes unpatched. The bracket counts those whose target also keeps a loader in cli, so
    the test stays green through the loader left behind;
  - stale in both is a target outside the unit that a member loads, taken by the new module's
    from-import;
  - a split latch is a bool or `None` latch among the members, which cli's re-export copies once
    and never sees rebound.
- *Without re-exports* (cli reaches the names it still loads through the module, `newmod.X`):
  - a loud site fails at once (a test import, a patch with neither `raising=False` nor an
    assignment, an outside importer, a loud symbol key);
  - a silent create is a `raising=False` or assigned patch, which creates the attribute on cli
    and reaches nothing.
- *Without, cli from-imports* is the spelling where cli instead writes
  `from espalier.newmod import X` for each name it still loads. cli then keeps a binding, so
  those parts stop failing, and their patches stay green on a stale binding, as with re-exports.
- *Latches across* are latches left in cli that a member writes or reads. They split in **both**
  branches unless the moved code reaches them through the module (`cli.X`).
- *`-m`* is the state a second copy of cli would hold under `python -m espalier.cli`. It is read
  from Python's `-m` semantics and never run [probable].

| Unit | With: stale sites (loaders both sides) | With: stale in both | With: latches split | Memos shared | Latches across (both branches) | Without: loud sites | Without, cli from-imports: loud sites | Without: silent creates | `-m`: second-copy state |
|---|---|---|---|---|---|---|---|---|---|
| interpreter core layer, members | 65 (55) | 20 | 5 | 1 | 0 | 54 | 15 | 42 | 0 |
| interpreter core layer, tie-closed | 67 (10) | 20 | 5 | 2 | 0 | 63 | 24 | 42 | 0 |
| settings layer (members = tie-closed) | 9 (0) | 19 | 0 | 0 | 0 | 137 | 33 | 0 | 0 |
| deploy layer, members | 18 (17) | 18 | 0 | 1 | 0 | 161 | 52 | 0 | 0 |
| deploy layer, tie-closed | 18 (17) | 65 | 0 | 1 | 4 | 167 | 53 | 0 | 4 |
| init, upgrade and deploy (hand group) | 45 (10) | 86 | 0 | 1 | 4 | 486 | 381 | 0 | 4 |
| scan and scope-check (hand group) | 0 (0) | 6 | 0 | 0 | 0 | 15 | 4 | 0 | 0 |
| the 28 single-command concerns, summed | 0 (0) | 17 | 0 | 0 | 0 | 84 | 16 | 0 | 0 |

What the two tables say for Gate A's re-export decision:
- **No branch is safe by a test run, for interpreter core.** With re-exports, 65 of its 68 patch
  sites go stale. 55 of them are on targets that a loader left in cli still reads, so the old
  patch stays green there while the moved loader goes unpatched. The 5 latches it owns split:
  - `_BELOW_FLOOR_ANSWER`, `_BELOW_FLOOR_REFUSING`, `_INTERPRETER_WARNING_EMITTED`,
    `_POWERSHELL_CALL_NOTE_SAID` and `_VENV_FALLBACK_OUTSIDE`;
  - `tests/conftest.py::_restore_interpreter_warn_flag` would restore cli's copy of the third.

  Without re-exports, 26 of the 68 patch sites fail loudly (54 loud sites in all, with its test
  imports and outside importers), which is a cost and not a risk. The other 42 patch sites create
  the attribute on cli and reach nothing: the 39 `raising=False` patches of the warn-once flag and
  3 direct assignments. This is Task 4's sentinel finding, priced: a red means read, not guarded. So the
  oracle for wave 1 is the static re-pointing check on the lane's diff, in either branch.
- **The latch hazard does not depend on the branch.** Under the deploy layer's tie closure and
  under the "init, upgrade and deploy" group, `::_refuse_below_floor_wiring` and
  `::_warn_venv_fallback_outside` write four latches by `global` that stay in cli:
  `_BELOW_FLOOR_ANSWER`, `_BELOW_FLOOR_REFUSING`, `_INTERPRETER_WARNING_EMITTED` and
  `_VENV_FALLBACK_OUTSIDE`. Moved with a from-import of the latch, the write rebinds the new
  module's copy, and cli's reader never sees it, with no error in either branch. Wave 1's contract
  either moves those latches with their writers or has the writers write `cli.X`. Under `-m`, the
  same four would also live in a second copy of cli [probable, never run]. `python -m
  espalier.cli` is named in 11 code, 4 doc, 39 test and 9 record files at P.
- **Without re-exports, the loud count depends on how cli reaches the moved names.**
  - For the big hand group, 486 sites fail where cli reaches them through the module, and 381
    where cli from-imports the 24 names it still loads.
  - For deploy's members, the drop is from 161 to 52, because cli keeps 57 of them bound.
  - The difference between the two counts is the sites that stop failing under the from-import
    spelling. Their imports then work, and the patches among them stay green on cli's stale
    binding. So the branch decision names the spelling as well as the branch.

These tables are the move cost Task 8's unit table carries, and nothing here grades a wave.
Gate A is the operator's. Nothing was graded while operator call `20261118T032647Z-air-7a763a`
was open. It was ruled (A), continue, at 08:07Z (ack `20261118T080812Z-air-2bef6b`), and the
grades are in Task 0's verdicts below.

### Task 5: the doctor boundary at P

Read by `python3 scripts/cli_cost_census.py --at 3330a5a --json doctor_boundary` [verified, the
census at P]:
- **The edges:** `espalier/doctor.py` holds 20 lazy import statements of cli. They take 43
  names: 34 functions, 1 class and 8 constants. They sit in 11 doctor functions (innermost):
  `::run_doctor_check`, `::_check_python_resolver`, `::_check_reporter_hook_wiring`,
  `::_deployed_surface_remains`, `::_generated_claude_headings`, `::_merge_refusal_step`,
  `::_merge_would_be_refused`, `::_remedy_hint`, `::_resolver_hint`, `::_unheard_on_path` and
  `::foreign_statusline_note`.
- **Doctor alone** reaches 1 of the 43 names, `::settings_foreign_read_denies`. Moving it leaves
  42 back edges.
- **The closure of the 43** is 141 definitions and 3,301 function lines. Of those, 139 are
  reached by loads; `_BELOW_FLOOR_ANSWER` and `_VENV_FALLBACK_OUTSIDE` are reached only by a
  write. Two closure members are reached by no command: `::settings_foreign_read_denies` and
  `::_foreign_read_denies`.
- **The cycle relocates rather than ends.** The closure holds `::_not_python3_from_entries`, which
  calls 4 doctor functions through `_doctor`: `_interpreter_is_python3`,
  `_interpreter_banner_unanswered`, `_interpreter_start_failure` and
  `_interpreter_start_unconfirmed`. Any module the closure moves to calls doctor, and doctor
  imports it.
- **What would end it, for the operator at Gate A, never for this lane** [hand, from the census's
  fields]: doctor.py's 20 import lines would read the 43 names from a module that does not import
  doctor. That needs the 4 interpreter probes moved out of doctor.py, or the closure's one caller
  of them changed. Either is a doctor.py change, which ruling 2 excludes.

The census prints, for each of the 43 names, the commands that reach it and its concern
(`names.per_name`).

### Task 6: the ledger triage at P

**The population** [verified, `python3 scripts/cli_cost_census.py --at 3330a5a --json ledger_rows`,
whose `rule` field states the tokenizer]: tier 2 holds 30 rows and tier 3 holds 6, so 36 rows.
The triage below lists the same 36 ids, checked equal to the census's. Beside them are the 2 rows
that count only under the authoring's rule, which counts a path mention (`DEF-346c`, `DEF-883`).
`DEF-985` was tier 2 at `17d83e0` and is struck at P (#715). Tier 1 reads 23, or 22 if a dotfile
counts as a first path (`DEF-623`).

**How each column is read:**
- *Layer and concern* [mechanical]: the census's units for the row's cited `espalier/cli.py::X`
  symbols. `none` means a symbol in no layer (reached only from `::main` or `::build_parser`).
  `—` means the row cites no symbol.
- *Class* [hand]: judged against a **module move**, meaning bodies copied verbatim, with the
  row's tests and citations re-pointed in the move's lane by wave 1's tools. Under the
  operator's definitions:
  - `before`: the move would change or bury the code the fix edits;
  - `in`: the fix is what the move's lane itself rewrites;
  - `independent`: neither.

  A verbatim move changes no body, so **under this rule `before` is empty by construction**, and
  the column separates `DEF-4123` from the rest and nothing else. Two other columns do separate
  rows:
  - *If decomposed* [hand]: the class if the unit's large functions are rewritten from the
    inside, as the accretion read's cuts would rewrite them.
  - *Probe reads cli.py by path* [mechanical, the census's `probes` section, `by` holding
    `path`]: once the cited symbol moves, the probe prints a new value while the defect stands,
    and the row is offered as a false strike.

  Counting those 8 rows as `before` makes the probe flip a class. Task 3 already prices the
  flips as a move cost, so the class column leaves them out rather than count them twice [hand].
  Both readings are printed, and which one grades the rows is the operator's choice.
- *Held at P* [mechanical]: a live claim or live dispatcher job whose `re.ids` names the row. It is
  folded by `tools/cc/mail.py`'s own `live_claims` and `live_assignments` over every mail ref, cut
  at P's commit time, with the dispatcher read from `espalier.toml`.

| Row | Tier | Layer | Concern | Class (module move) | If decomposed | Probe reads cli.py by path | Held at P |
|---|---|---|---|---|---|---|---|
| `DEF-400b` | 2 | commands | refresh-self-host-pin | independent | independent | yes |  |
| `DEF-623` | 2 | commands | init-upgrade-deploy | independent | independent |  |  |
| `DEF-736` | 2 | deploy | init-upgrade-deploy | independent | independent | yes |  |
| `DEF-835` | 2 | none | entry | independent | independent |  |  |
| `DEF-875` | 2 | commands | init-upgrade-deploy | independent | independent |  |  |
| `DEF-930` | 2 | commands | init-upgrade-deploy | independent | before | yes |  |
| `DEF-932` | 2 | commands | init-upgrade-deploy | independent | before | yes |  |
| `DEF-943` | 2 | commands | init-upgrade-deploy | independent | independent |  |  |
| `DEF-945` | 2 | commands | init-upgrade-deploy | independent | independent | yes |  |
| `DEF-947` | 2 | commands, interpreter core | init-upgrade-deploy, shared by 11 | independent | in |  |  |
| `DEF-996` | 2 | commands, deploy, none, settings | init-upgrade-deploy, entry | independent | independent |  |  |
| `DEF-1001` | 2 | commands, deploy, settings | init-upgrade-deploy | independent | before |  |  |
| `DEF-1005` | 2 | commands, none | init-upgrade-deploy, entry | independent | independent | yes |  |
| `DEF-1006` | 2 | none | entry | independent | independent |  |  |
| `DEF-1021` | 2 | commands, deploy | init-upgrade-deploy | independent | independent |  |  |
| `DEF-1028` | 2 | deploy | init-upgrade-deploy | independent | independent |  |  |
| `DEF-1057` | 2 | commands | init-upgrade-deploy | independent | independent |  |  |
| `DEF-1077` | 2 | deploy | init-upgrade-deploy | independent | independent |  |  |
| `DEF-1079` | 2 | commands | init-upgrade-deploy | independent | independent | yes |  |
| `DEF-1085` | 2 | commands | init-upgrade-deploy | independent | independent |  |  |
| `DEF-1086` | 2 | commands | init-upgrade-deploy | independent | independent |  |  |
| `DEF-1088` | 2 | commands | init-upgrade-deploy | independent | independent |  |  |
| `DEF-1093` | 2 | deploy | init-upgrade-deploy | independent | before |  |  |
| `DEF-1094` | 2 | commands | shared: release (3 commands) | independent | independent |  |  |
| `DEF-2095` | 2 | commands | init-upgrade-deploy | independent | independent |  |  |
| `DEF-3096` | 2 | — | — | independent | independent | yes, and a bare file cite |  |
| `DEF-4123` | 2 | — | — | in | in |  |  |
| `DEF-5089` | 2 | commands | init-upgrade-deploy | independent | independent |  |  |
| `DEF-5099` | 2 | commands | init-upgrade-deploy | independent | independent |  |  |
| `DEF-5113` | 2 | commands, settings | init-upgrade-deploy | independent | before |  |  |
| `DEF-877` | 3 | commands | init-upgrade-deploy | independent | independent |  |  |
| `DEF-900` | 3 | deploy | init-upgrade-deploy | independent | independent |  |  |
| `DEF-1089` | 3 | deploy | init-upgrade-deploy | independent | independent |  |  |
| `DEF-3065` | 3 | none | entry | independent | independent |  |  |
| `DEF-5095` | 3 | commands | init-upgrade-deploy | independent | independent |  |  |
| `DEF-5118` | 3 | settings | init-upgrade-deploy | independent | independent |  | claim `631616` |
| `DEF-346c` (authoring rule only) | 3 | — | — | independent | independent |  |  |
| `DEF-883` (authoring rule only) | 3 | — | — | independent | independent |  |  |

**The counts, over the census's 36:**
- *Class, module move:* `in` 1 (`DEF-4123`, whose fix is the moves) and `independent` 35.
- *If decomposed:* `before` 5 (`DEF-930`, `DEF-932`, `DEF-1001`, `DEF-1093`, `DEF-5113`), `in` 2
  (`DEF-4123`, `DEF-947`) and `independent` 29.
- *Probe by path:* 8 rows.
- *Layer:* commands 24, deploy 9, settings 4, interpreter core 1, none 5 and no symbol 2. A row
  citing several layers counts in each.
- *Concern:* 29 of the 36 sit in init-upgrade-deploy, the concern that holds 61% of the file
  (Task 2).
- *Held:* 1 (`DEF-5118`).

So the rows a split would meet are concentrated in the last unit a bottom-up order moves, the
commands layer of that concern.

**A second, blind read** [hand]: a reader in its own context was given the rows' text and their
placements, but not the first read's classes. It agreed on 33 of the 38. On `DEF-1001` the first
read's rule was at fault: it counted a fix that spans units as `before`, a rule it did not apply
to `DEF-5113`, which crosses the same line. The class was taken from the second read and the
rule corrected. The 4 rows still differing (`DEF-930`, `DEF-932`, `DEF-1005`, `DEF-3096`) differ
by rule, not by reading: the second read let a path-reading probe decide the class, and it did
so for 4 of the 8 such rows. 10 rows are marked unsure in the triage's own record: `DEF-930`,
`DEF-932`, `DEF-947`, `DEF-996`, `DEF-1001`, `DEF-1005`, `DEF-1093`, `DEF-3096`, `DEF-5113` and
`DEF-5118`.

**What the triage adds to a move's cost:**
- **False strike offers** [verified on the probe files at P]. The 8 path-reading probes are listed
  in Task 3. One the first read missed: `DEF-736`'s probe AST-reads `espalier/cli.py` for the
  `differs from packaged` literal. Once `::deploy_harness`'s narrator leaves cli.py, the probe
  prints False while the defect stands.
- **Citations the re-key tool's four spellings do not match** (Task 3):
  - `DEF-3096`'s site cell cites the bare file with no `::X`;
  - `DEF-835` anchors `::main` at a line number, which drifts as units leave even though `main`
    stays;
  - 7 rows cite with a shorthand `::X` after a first full cite (`DEF-4123`, `DEF-736`, `DEF-930`,
    `DEF-945`, `DEF-947`, `DEF-996`, `DEF-5113`).

  The shorthand is a fifth spelling for wave 1's tool, unmeasured beyond these rows.
- **Rows to schedule as one:**
  - `DEF-2095` and `DEF-5089`, entirely before or entirely after the commands unit moves.
    `DEF-2095`'s row says "the lane that takes DEF-5089 takes this" [verified].
  - `DEF-930` and `DEF-5113` probably share one fix. In both, `::cmd_init` writes
    `reports/harness_config.json` before `::deploy_harness` has decided what it did. Neither row
    says so [probable].
- **The held row:** `DEF-5118`'s lane is built and parked under claim `631616`, which names
  cli.py. A settings-unit move landing first would make that diff re-derive onto moved lines: a
  sequencing cost, not a class.

The triage ran in a scratch directory. Its per-row record (reasons, unsure notes, the second
read's verdicts) is not in this lane (Files touched), so a re-run rebuilds it from the rules above.

### The authoring figures that do not reproduce, in one place

For the Gate A call to link one list (the dispatcher's ack `20261118T042249Z-air-0b1f6b`). Each
entry gives the authoring figure, the census at P (or at `17d83e0`, where the authoring pin
decides), and the rule difference where one is named. **Only the first is Item 1's refuting
result.** The rest are recorded where they fall and raise nothing.

| Where | Authoring | Census | The difference |
|---|---|---|---|
| Item 1, claim-overlap lane pairs | 18 (over 30 days and over about 42) | 10 over the 30 days to P; 20 over 42 days to `17d83e0` | **not explained**: operator call `7a763a`, ruled continue (ack `2bef6b`) |
| Item 1, importers outside tests | 62 | 65 | reproduced under the authoring's rule (each file's from-imports summed) |
| Item 1, patches through cli | four | 8 sites, 3 targets, 3 files | reproduced under the authoring's rule (a same-line text match) |
| Item 1, catch-ups carrying cli.py | 54 | 49 at P | reproduced under the authoring's rule (48 catch-ups + 6 other lane merges, at `17d83e0`) |
| Task 3, readers: symbol keys | 34 in 12 | 20 in 7 | the census counts a 2-tuple whose second element is a name; any second element gives 32 in 12. Not reproduced under either |
| Task 3, readers: path literals | 88 in 35 | 69 in 34 | the census counts a key's path element once; counting it again gives 89 in 36. Not reproduced under either |
| Task 3, citations: in `.py`/`.cmd` | 57 in 29 files | 56 in 30 (57 in 31 by plain text), at `17d83e0` | the occurrence differs by one non-citation (a string prefix in `tests/test_python_floor.py`); the file count is **not explained** |
| Task 3, citations: live fragments and swept docs | 132 in 36; 31 in 7 | 131 in 35; 28 in 7 plus 3 struck, at `17d83e0` | one prose mention in `DEF-4123`; 3 on lines the sweep skips as closed rows. Each reproduces by plain text |
| Task 3, ledger probes on cli | about 27 [probable] | 24 | the authoring counted the word "cli" in a probe file; `DEF-5043`, `DEF-645` and `DEF-900` do not read cli |
| Task 4, the 31 and 12 targets | 131 + 30 sites | the same at the first read; 32 and 12, 132 + 30 sites since the rule was widened | reproduced at the first read; the widened rule adds one target with more than one loader (`_git_ignorecase`, Task 3's test patches). They overlap rather than split (Task 4 above) |
| Task 5, the 43 names by kind | 32 functions, 1 class, 10 constants | 34, 1, 8 | **rule not named** |
| Task 5, doctor functions holding the imports | 19 | 11 (innermost) | **rule not named** |
| Task 5, doctor alone | 2 names | 1 name, plus 2 closure members no command reaches | the second of the authoring's two is a closure member, not one of the 43 |
| Task 5, the closure | 139 definitions, 3,283 lines | 141 and 3,283 at `17d83e0`; 141 and 3,301 at P | 139 on loads alone; the two latches reached only by a write make 141 |
| Task 6, tier 3 | 8 at `17d83e0` | 6 | `DEF-346c` and `DEF-883` cite cli.py by path only. Counting a path mention gives 8 |
| Task 6, tier 2 | 31 at `17d83e0` | 31 at `17d83e0`, 30 at P | reproduced. #715 struck `DEF-985` |

### Task 0 at P: the three verdicts and the exit cell

Each item is graded on the thresholds committed at step 1 (`6a91bc51b`). Items 2 and 3 were
graded after the operator ruled on call `20261118T032647Z-air-7a763a`: (A), continue, at
2026-11-18T08:07Z (ack `20261118T080812Z-air-2bef6b`) [verified, the mail].

| Item | Verdict | The read at P | Where it is read |
|---|---|---|---|
| 1. Do the authoring figures hold? | **Refuted on one figure; ruled continue** | Every structural row reproduces exactly, and every windowed row but one is explained. The 18 cross-seat claim-overlap pairs reproduce under neither stated window: 10 over the 30 days to P, 20 over the 42 days to `17d83e0`. The 18 grades nothing | Item 1 at P; the list above |
| 2. Is there a collision cost? | **Not real**, on point estimates | C1 1 against 4. C2 15 of 33 lanes (45.5%) against 50%, two lanes short. C3 2 holds against 8. C4 1 replay conflict, not graded. At 95% only C3 is decided: C1's upper bound is 4.74 and C2's 61.1% | Item 2 at P |
| 3. Is there a reading cost? | **Unmeasured** | Two causes, each enough alone. The hand sample confirms 3 of 3 air-work lanes and 0 of 2 air lanes, so the attribution fails for the two-seat population. And the realised minimum detectable ratio is 6.24 at `e26e0f25f`, above the committed 2.0. Post hoc and never graded: the median R of air-work's cli.py lanes is under (a)'s 1,500 at 98.2% one-sided, assuming independent lanes | The transcripts read; *Item 3's (a) alone* |

**The exit cell: collision not real, reading unmeasured. The exit table has no such cell.** Its
row for "collision not real" has two cells: no refactor waves (reading not real), and
decomposition waves graded on reading (reading real). Task 0 says what an unmeasured item is:
never a silent kill and never a license. So this read licenses no wave. It also cannot support
striking `DEF-4123` as "no cost". The call says both.

**Beside the verdict, never graded** (at `e26e0f25f`). On the median cli.py lane, the seat read
42 lines of the CLI modules, and threshold (a) is 1,500. Post hoc, the one-sided upper bound on
the median R of air-work's cli.py lanes is 403 lines, at 98.2% or more with the lanes assumed
independent. It is 897 with #349 at its hand read, and 1,128 with the forks' reads added, so each
reading is under 1,500 (*Item 3's (a) alone*). That bounds the size of the seat's cli.py reading.
It says nothing on (b).

The comparison with E says less than it seems to. R counts one module, while E counts a lane's
whole edit set. On the same scope, the cli.py lanes read more of their edited files than the
control lanes do: medians of 1,412 against 277 (*The scope of R against E*). Two size confounds
are unread: lane size, and the control rule that leaves out files of 3,000 lines or more. So this
read gives no direction on a relative reading cost, and it gives a post hoc upper bound on an
absolute one, for air-work's lanes.

**How far a decidable read is** [probable: the step-1 formula at the observed spread; nothing was
read for it]. The committed minimum detectable ratio is exp(2.49 · s · √(1/n_t + 1/n_c)). At P,
the pooled s of ln(1 + lines) is 2.691. For the ratio to reach 2.0, 1/n_t + 1/n_c must be at
most (ln 2 / (2.49 · 2.691))², which is 0.0107. So:
- even with unlimited control lanes, it needs 94 or more cli.py lanes;
- at this box's rate (15 cli.py lanes and 126 control lanes in the 30 days to P), that is about
  7 months: about 105 cli.py lanes and 880 control lanes;
- with all four seats' transcripts read (36 cli.py lanes in the 30 days to P), it is at least
  2.6 months, and about 2.9 at this box's ratio of control lanes. That needs the Windows seats'
  transcripts read on their own box, and their attribution passing a hand sample. Here, air's
  lanes fail one;
- for air-work alone (post hoc; its s is about 2.0, worked back from its ratio of 4.21 at
  14 / 82), it is about 4.3 months.

The spread is the obstacle, more than the count. At P's counts, the ratio would reach 2.0 only
with s at about 1.02. Many lanes read few lines or none, and ln(1 + 0) is 0. **So on this box,
under the committed design, Item 3 cannot be decided inside a quarter.** A later pin could
pre-register a read with less spread, or read all four seats' transcripts. That is a new
pre-registration, never a change to this one.

### The recommendation

**No refactor waves now.** No graded component is at its threshold. The one item that could
license decomposition waves is unmeasured, and on this box it stays unmeasured for about seven
months under its committed design. Unmeasured is never a license.

In order:
1. **Re-scope `DEF-4123`; do not strike it.** That is the operator's word at Gate A; this lane
   edits no row (Status). A strike says there is no cost, and Item 3 cannot say that. Each of the
   row's two premises, as read at P:
   - "collides with the next lane in it": not real on every graded component;
   - "reads a file of more than 17,000 lines": unmeasured as a cost. Post hoc and never graded,
     the median R of air-work's cli.py lanes on this box is under threshold (a) at 98.2%
     one-sided, assuming independent lanes (*Item 3's (a) alone*). No other seat is read, and no
     direction is read for a cost relative to other files.

   The size and the accretion stand [verified, Task 2]. The re-scoped row names what reopens it:
   C2 at or over 50% in two consecutive 30-day windows, or C2's 95% lower bound at or over 50%
   in one; or a decidable reading read. One window at 50% does not reopen it: at P's share of
   45.5%, a window reads 17 or more of 33 by noise alone with probability 0.30 (Task 9's
   reasoning review [probable]). A C2 reopening reopens the collision premise only. It does not
   license a module move, which C2 cannot grade (the Gate A decisions, 4).
2. **Re-read the collision section at a later pin.** That is one census run plus a hand grade
   against step 1's table, not a lane. C1 to C3 have no verdict function in the census, as
   Item 3 has. The run needs a clone holding every seat's mail ref: the census names a seat
   that the mail names but whose ref the clone lacks as unread, and the pin's oids are under
   "The census's mail refs at P" below. C2 is the one component near its threshold: 17 of 33
   lanes would have crossed it. A later window can cross it with no change in how the seats
   work. Expected: C2 near 45% again, the rest at their floors [judgment].
3. **Land the census as the standing instrument.** It lands under every cell (Status). Each later
   read is one run at a new pin.

No unit is offered as a wave's payoff. A component no proposed shape can move is reported and
never offered (Task 7). The one component a decomposition is built to move, the primary, is
unmeasured.

**The strongest case for refactoring anyway, and why it does not hold on this evidence.**
- cli.py is 17,817 lines [verified, at P]. One hand group holds 70% of its function lines.
- `::cmd_upgrade` grew from 498 to 929 lines since the seed, through about 12 row guards in one
  arm, and it cites 26 ids [verified, Task 2].
- The seats hand cli.py work to forks (#357, #429, #540). The forks' reads of the CLI modules sum
  to 6,913 lines on the 15 lanes at `e26e0f25f`, against the seats' own median of 42.
- C2 says nearly half the cli.py lanes overlap another seat's live claim on the file. C1, C3 and
  C4 say almost none of those overlaps became a conflict or a hold. That could be the claim
  protocol working at a cost no census counts: mail `45df70` placed code "by function, to stay
  off the live claims".
- Deferral compounds (Task 9's reasoning review). The patch sites on cli went from 39 (on 18
  targets) at the seed to 102 (29) at the window's start and 150 (44) at P. Over the same
  commits, cli.py went from 11,084 to 15,939 to 17,817 lines, +61% in 55 days [verified: the census's
  `patches` at `d00f6de45`, `397799c8b` and P; the lines by `git show`].

Each of these is real or plausible. None is a measured cost to a seat:
- The size and the growth are lengths. Task 0 says a function's length decides nothing, since a
  move keeps it. That answers length, not move cost. A later move touches more patch sites
  than one now, so deferral has a price [verified, the figures above]. That price argues for the
  options that cap it without moving anything, (iv) and (v) below, and not for a wave whose
  payoff is unmeasured [judgment].
- The forks' reads spend the forks' context, not the seat's, and the seat's is what threshold (a)
  prices. Counted with them, air-work's median is 416, still under 1,500 by more than three times.
- The protocol's placement cost is a hypothesis with one mail behind it. No section reads it
  [unmeasured]. The call should name it as the cost the audit could not price, not as a
  payoff.

What holds is narrower. `::cmd_upgrade`'s "nothing to do" arm is a stack of row special cases,
and a table of check, clause and remedy is a cut worth testing [hand, Task 2; a hypothesis].
That is a lane for a row that names its cost, not a refactor wave.

**What the audit does not price** (Task 9's reasoning review). The pack's "maintainer" is read
as a Claude seat on this box. Three costs fall outside that read, and none was scoped out by name:
- human and outside contributors to a tree about to be open-sourced;
- the dispatcher's review reads of cli.py, which sit inside the 8,504 unplaced calls;
- defect density. The reviewer's rough read is 1.68 live ledger rows per thousand lines for
  cli.py, against 1.62 to 1.82 for `tools/cc/hooks/session_start.py`, `tools/cc/hooks/_hook_utils.py`
  and `espalier/doctor.py` [probable, the reviewer's; not re-read here]. If it holds, cli.py's
  size buys no more defects per line than the other large files, which supports the
  recommendation.

### The alternatives, priced

**(i) Strike or re-scope `DEF-4123` now.** Neither costs a lane: either is one edit to the
row, made by the operator or the dispatcher.
- *Strike:* says there is no cost. Item 2 grades collisions not real on point estimates, and at
  95% only C3 excludes a cost (Item 2 at P), so Item 2 does not support a strike by a bound
  either. Item 3 does not support it for reading, and the row's who-is-hurt goes with it. Not
  recommended.
- *Re-scope:* keeps the row live with its premises re-read at P and its reopening condition
  named (the recommendation, item 1). New evidence comes only from later census runs.
  Recommended.

**(ii) Decompose only `::cmd_upgrade` and `::build_parser`, with no wider map.**
- *What they are at P* [verified, the census at P]. `::cmd_upgrade` has 929 lines and
  `::build_parser` 890: 1,819 together, 11.7% of the file's 15,542 function lines. In
  `lane_read` they are 30.1% (7,910 lines) and 16.8% (4,428 lines) of the 26,298 lines summed
  over the window's 36 cli.py lanes, and they appear in 9 and 5 of those lanes. They are unlike
  things (Task 2). `::build_parser` is declaration: 324 of its lines are help text, and it cites
  1 id. `::cmd_upgrade` is accretion, with 26 ids.
- *What an in-file split touches* [verified, the census at P, unless tagged]. The two names stay
  in cli, so nothing breaks that imports, test-imports or patches them by name. The split
  touches only what reads their bodies:
  - 1 symbol key, `tests/test_json_safe_program_word.py::_TYPED_IN_A_WRITER`, which counts 7
    typed spellings in `::cmd_upgrade`'s body. A split that moves one into a helper reds it,
    loudly [probable];
  - 1 patch site on `build_parser`;
  - 2 probes that read `build_parser` by path, `DEF-1005` and `DEF-945`. Either could print a
    new value once its text moves into a helper, which offers a false strike [probable].
    9 more probes name `cmd_upgrade` among the commands that reach their symbols;
  - name citations stay valid: `cmd_upgrade` 36 (26 struck, 6 swept-live, 4 unchecked) and
    `build_parser` 20 (7 struck, 8 swept-live, 5 unchecked). The 17 line-form citations in the
    file drift with any edit.
- *Cost* [judgment]: two lanes, one for each function, each a pure refactor inside cli.py with
  its review. `::cmd_upgrade`'s lane carries the risk, since the order of its arm's guards is
  behaviour.
- *What it can move:* `lane_read`, by construction. That is never a payoff alone, and this
  shape is the must-not-pass case's own shape. The primary, which is unmeasured. No collision
  component: C1's one uncertified pair (#429 / #430) is `unplaced`, and a split inside a function
  moves no module-level line [judgment].
- *Evidence it would produce:* nothing that grades under this pack's rules.

**(iii) The navigation aid alone.**
- *What exists:* the census already prints the concern map and the layer view at any pin
  (`clusters`, `layers`), and each unit's move cost (`move_cost`).
- *Cost* [judgment]: one lane to land the map as a generated region the census rewrites, with a
  check that reds when the map is stale. After that, the upkeep is a census run whenever cli.py's
  top level changes.
- *What it touches:* nothing in cli.py. No importer, patch, citation or probe moves.
- *What it can move:* the primary only, as a hypothesis (Task 7's table). Its payoff is unread on
  this box inside the quarter, as is every shape's.
- It is the cheapest shape that could move the primary. If the operator wants one lane spent on
  the reading premise, this is the one whose cost is near zero and whose risk to the code is
  none.

**(iv) Stop the accretion** (Task 9's reasoning review named it; not priced by any read).
- *What it is:* new commands land in new modules, pinned by a guard that refuses a new top-level
  command in cli.py outside an allow-list.
- *Cost* [judgment]: one small lane for the guard, plus a rule every later CLI lane follows.
  Where a new command goes is the operator's call, not this pack's.
- *What it touches:* nothing in cli.py now.
- *What it can move:* the growth of the move cost (the patch sites above), which no component
  grades. It is never a payoff under Task 7.

**(v) Land wave 1's re-pointing check now** (Task 9's reasoning review named it).
- *What it is:* the static check that every `cli.<name>` patch a move's diff leaves is
  re-pointed (Task 4). It is wave 1's oracle in either re-export branch.
- *Cost* [judgment]: one tools lane, with its tests. It moves nothing.
- *What it can move:* nothing at P. It lowers the risk of any later move, whichever shape is
  approved, and so prices deferral down.
- *Evidence it would produce:* none that grades. Like (iv), it is a hedge, not a payoff.

### The Gate A decisions

**1. Re-exports or none (Task 4).** Moot under no waves. If a wave is approved: **none**, with cli
reaching the moved names through the module (`newmod.X`), and the static re-pointing check on the
lane's diff as wave 1's oracle in either branch. One inconsistency, moot under no waves (Task 9's
reasoning review): `newmod.X` rewrites cli's remaining call sites to the moved names, while
Task 6's triage judges against a move whose bodies are copied verbatim, so that `before` is empty
by construction. A wave's approval settles which first. The figures, all at P:
- *With re-exports,* for interpreter core: 65 of its 68 patch sites go stale, and 55 of those stay
  green through a loader left in cli. Its 5 latches split.
- *Without:* 54 sites fail loudly, which is a cost, not a risk. 42 patch sites (the 39
  `raising=False` patches of the warn-once flag and 3 assignments) create the attribute on cli and
  reach nothing. So a red means the site was read, not that it is guarded, and a green run proves
  nothing in either branch.
- *The from-import spelling is re-exports in effect.* For the hand group, 486 sites fail when cli
  reaches the names through the module, and 381 when it from-imports them. The 105 that stop
  failing stay green on a stale binding.
- *The latch hazard holds in both branches.* Under the deploy layer's tie closure and the hand
  group, `::_refuse_below_floor_wiring` and `::_warn_venv_fallback_outside` write four latches by
  `global`: `_BELOW_FLOOR_ANSWER`, `_BELOW_FLOOR_REFUSING`, `_INTERPRETER_WARNING_EMITTED` and
  `_VENV_FALLBACK_OUTSIDE`. Move them with their writers, or have the writers write `cli.X`.

**2. The doctor cycle (Task 5). Leave it as it is.** The answer is the same with waves or without.
- doctor.py holds 20 lazy imports of 43 cli names, in 11 functions.
- Their closure is 141 definitions and 3,301 function lines.
- Moving the closure moves the cycle rather than ending it: `::_not_python3_from_entries` calls 4
  doctor functions.
- Ending it is a doctor.py change, which ruling 2 excludes.

**3. The protected-zone citations (Task 4).** Moot under no waves. If a wave is approved: **keep
the cited names in cli.py for wave 1.** Allow a `tools/cc/` re-key lane, with its vendor sync,
only for a unit that has to move one of them. The figures at P [verified, `citations` and
`move_cost`]:
- In all three spellings, 17 occurrences sit in 9 `tools/cc/` files, on 12 names, and each is
  matched by its twin under `espalier/_vendor/cc/`. 10 of the 17, in 5 files, are the `path::X`
  spelling Task 3 lists.
- 12 of the 17 name members of the "init, upgrade and deploy" group, led by `INIT_HOOK_SCRIPTS`
  (4) and `INIT_TOOL_SCRIPTS` (2). 4 name members of two single-command concerns
  (`cmd_memory_prune` 3, `cmd_integrity` 1), and 1 a member of the interpreter core layer.
- A re-key edits the harness's protected zone, so it runs under maintenance mode with
  `scripts/sync_vendor_cc.py` [judgment on what that costs].

**4. Which components grade a wave (Task 7).** Moot for now; it is needed at the next pin.
Recommended: **no component grades a module move as the census reads it at P. C1 and C3 are
reported and graded on nothing. The primary grades nothing until a read of it can be decided.
`lane_read` never grades alone, and C4 never.** Task 8 recommended C2 here. Task 9's reasoning
review found that any split of cli.py lowers C2 by construction (Task 1, corrected; verified,
`::claim_overlaps`), which is `lane_read`'s must-not-pass shape. A module move needs a
move-invariant overlap first: C2 counted on the definitions both claims name, wherever they
sit among the CLI modules, with a must-not-pass fixture (an arbitrary split must not read as a
payoff). That is a new component with a new baseline, so it is the next pin's pre-registration,
never this one's.

| Component | Baseline at P | Committed threshold | Graded at P | Recommended to grade a wave |
|---|---|---|---|---|
| Primary: lines of the CLI modules a lane's seat read | median R 42; median E 277; MDR 6.24 (at `e26e0f25f`). Post hoc, never graded: the 98.2% upper bound on air-work's median R is 403 (897 with #349's hand read), assuming independent lanes | (a) median R ≥ 1,500, (b) ≥ 2 × E, (c) p < 0.05; not real only with MDR ≤ 2.0 | unmeasured | no, until a decidable read |
| `lane_read` (secondary) | 36 lanes, median 337, max 2,784, summed 26,298 | none: only beside the primary | not graded | never alone |
| C1. Uncertified concurrent cli.py pairs | 1 | 4 | not real | no: reported |
| C2. Share of cli.py lanes in a cross-seat claim overlap | 45.5% (15 of 33) | 50% | not real, near | no: a split lowers it by construction. A symbol-aware form, pre-registered at the next pin, could |
| C3. Dispatcher holds over a cli.py overlap | 2 | 8 | not real | no: reported |
| C4. Replay conflicts on cli.py | 1 | not graded (floor) | not graded | never |

Why. Task 7 pays a wave on a component only when that component falls at least 30% from its
baseline at P. C2's baseline is 45.5%, so a 30% fall is to 31.8% or under, a share a 30-day
window can show. That is why Task 8 chose it. But a split shows that fall whether or not the
seats' work separated, so the fall would not be a payoff. C1's baseline is 1 pair and C3's is 2 holds. With counts that small, one event
missing reads as a fall of 100% or 50%, which is noise, not a payoff [judgment]. The primary is
unmeasured at P (Task 0's verdicts above).


## Landing
- State: LANDED
- Commits: `lane/the-cli-audit-prices-each-move` (seat `air-work`): `6a91bc51b` (the pin and the
  pre-registration), `522ad6f0c` (the census skeleton), `730aca4af` (the collision at P),
  `025c6626f` and `718bbac94` (the map, layers, accretion and move cost), `590cbd5dd`,
  `fc0e8bdd1`, `d099489513` and `c6d2ef349` (Tasks 4 to 6), `d5a81e110` (the Audit result),
  `9ce0f656a` and `b8488da8e` (the reasoning review's fold and its F7 fix), `5bb09b9e3`,
  `ae313a4a8` and `e26e0f25f` (the code reviews' fold), `c0c0b74bb` (the verifier's fold),
  `3195445cb` (the six contract fixes) and `35c9c1116` (the Session Log row); merged as `7efbcd1`
  (#725, 2026-11-18T14:28:39Z)
- Suite: the full tier's second run, on `3195445cb` (`proof_tier.py --run --base origin/main`),
  PASS 4 of 4: xdist 36,720 passed, 160 skipped, 3 xfailed; serial 3,643 passed, 13 skipped. The
  landing check on `35c9c1116` (`check_handoff_landing.py --skip-shape`, air's ruling
  `20261118T090753Z-air-b3bfcb`) clean, 1,018 passed: `check_message_shape` read 22 subjects past
  72 characters at the final head (16 of the seat's pack and script commits, 6 of its Session Log
  rows), none an internal id. After the merge, on `7efbcd1`: the post-merge proof run
  44324669032 green, and the post-merge Windows leg run 44324668942 green
- Earn-the-red: per section, from #725's body: the census skeleton's 27 fixture tests, 21 mutants
  killed; Tasks 2 and 3, 110 tests and 51 mutants killed; F7's tests red on the unfixed script;
  the code reviews' 19 folds, 48 red on the unfixed script and 328 green after (the named mutants
  killed but the effect-equivalent five, below); each of the first full run's 6 contract
  failures red on the unfixed head
- Red-team at authoring (2026-11-17, each reviewer in its own context): the reasoning review
  (checklist v1, failure-mode reviewer), REQUEST CHANGES (checklist PASS 4, GAP 4, BIAS 5,
  UNCHECKED 8; failure modes Regression 0, Gap 10, Rough-edge 7); the architecture review, 13
  findings, each load-bearing one verified in the code. All folded, except one acknowledged: the
  collision floor's cause is left to the census (its claim-overlap row) rather than argued. One
  process slip: the two reviewers shared one scratch directory, and one overwrote the other's
  script mid-run (Core Rule 14). The reruns went to a subdirectory, and in-lane reviews each get
  their own (Task 9).
- Red-team in lane, each reviewer in its own scratch directory:
  - **the test-infrastructure read of Task 4's sentinel sample and `DEF-5127`** (code reviewer,
    briefed on `tests/CLAUDE.md`'s "patch the object the code under test reads"): REQUEST
    CHANGES, BLOCK 0, WARN 4, NOTE 8, NIT 1. "0 of 56 vacuous" and `DEF-5127` hold on its re-runs
    in its own venv. All are folded in Task 4's section:
    - W1, a red means read and not guarded: the deletion arm's 25 of 56, recounted from its raw
      results, with wave 1's oracle and earn-the-red named;
    - W2: site 9's unread green node, hand-read as live under its defect;
    - W3: `DEF-5127`'s probe read the spelling and passed the empty stub, so it was re-pinned to
      match the fix;
    - W4: the test-selection rule and the three hand-set lists;
    - N1, N2, N4, N5, N6 and N7 in the text, N8 in the row, and N9 in the row's fix shape;
  - **the reasoning review on the Audit result and the census** (Task 9; checklist v1,
    failure-mode reviewer, in a snapshot clone at `d5a81e110` with Task 0's *Expected at
    authoring* paragraph withheld): REQUEST CHANGES, PASS 7, GAP 6, BIAS 4, UNCHECKED 3. It
    re-derived every static figure and matched each one. It found that the recommendation follows
    from the verdicts, and that four places could mislead the call. Every finding is folded, each
    load-bearing one verified here first:
    - F1, C2 lowered by any split: verified in `::claim_overlaps`. Task 1 and the census's
      docstring are corrected, decision 4 no longer has C2 grade a move, and the reopener needs
      two windows or a lower bound;
    - F2, a decidable bound on (a) alone: the transcripts read, *Item 3's (a) alone*;
    - F3, the deferral cost: re-read here at the three commits, folded into the steelman, with
      alternatives (iv) and (v);
    - F4, the bounds on Item 2: re-computed, in Item 2 at P;
    - F5, the scope of R against E: the transcripts read, *The scope of R against E*, with the
      "Beside the verdict" paragraph corrected to match (on the same scope the medians lean the
      other way, with two size confounds unread);
    - F6 and F10, the pre-registration's addendum: verified against the diff from `b958adb42`;
    - F7, a clone missing seats' mail refs read with nothing unread: fixed in the census
      (`::mail_seats_named`, its tests red on the unfixed script), with the pin's oids recorded;
    - F8, F11 and F12, in the text.

    F9 stands as a gap: no methods review of Item 3's statistics ran, and F2, F4 and F5 are each
    a methods finding. A methods read is owed before the next pin's pre-registration;
  - **the verifier of the transcripts re-run's fold** (a fresh general-purpose reviewer, read-only,
    working from the two runs' JSON, the census code and git). It re-derived every figure of the
    `e26e0f25f` row, its "what moved" list, *The scope of R against E* and *Item 3's (a) alone*,
    and every figure reproduced. It found 3 wrong statements: the builder worktree's seat label,
    `has_py`'s scope, and "the median lane". It found 4 overclaims:
    - `naming_cli`'s literal match;
    - "matched scopes" with `CONTROL_MAX_LINES` unnamed;
    - "an artefact";
    - the bound's population left out of the verdict row, the Gate A row and `DEF-4123`'s premise.

    It also gave a stronger form of the bound (it does not rest on #349's hand read) and two
    correlations the assumptions left out. It found that a per-line unit in the paired design
    decides its direction in advance. Each load-bearing finding was verified here in the code or
    git, and each is folded. It read the fold's new statistics and not step 1's design, so F9
    stands;
  - **the code review the tier names**, three reviewers in snapshot clones, on the first fold
    (`5bb09b9e3`) and on `ae313a4a8`:
    - rv-ab (pin through `move_cost`, `census`, `main`): no BLOCKER, no MAJOR, MINOR 6;
    - rv-c (collision, `lane_read`, transcripts, the splitter): REQUEST CHANGES, BLOCKER 0,
      MAJOR 1, MINOR 6;
    - rv-sib (`ae313a4a8`): BLOCKER 0, MAJOR 1, MINOR 6, with 89 real-shell cases.

    All of them are folded as 19 items in one fix batch (`e26e0f25f`), each defect's test red on
    the unfixed script (48 failed, 280 passed, read here; the builder read 49) and green after
    (328 passed). The named mutants are killed except the effect-equivalent M23b, M26, m05, m15 and
    m17 (the builder's runs). The static sections read the same at P as rv-ab's run there, except
    the new `citations.rule.fragments` key [verified, a diff here].
- Pre-registration commit: `6a91bc51b` (2026-11-18T02:46:56Z), "the cli audit's thresholds are
  fixed before any metric is read"
- Deviation, not a pass: the criterion that `git diff --name-only origin/main...HEAD` lists only
  Files touched fails by its letter on `task-packs/ledger.d/DEF-5127.md` and
  `task-packs/probes.d/DEF-5127.json`. These are a test that reds for the wrong reason, found by
  Task 4's sample, and not a vacuous patch. They are kept on the lane by the dispatcher's ack
  `20261118T040752Z-air-ff0cf7`.
- The full tier's first run (on `c0c0b74bb`, 2026-11-18, `proof_tier.py --run --base
  origin/main`): mypy 0, ruff 0, and the serial line 3,643 passed. The xdist line had 6 failed
  and 36,713 passed. Each failure was a tree-wide contract the lane's two new files had not yet
  met, and each was red on the unfixed head:
  - the derived-population census's health (an unadjudicated row);
  - the hidden-name filter on a `.claude` listing (the transcript folders, which never start with
    a dot, so no figure moves);
  - a TOML-module fallback spelled in a fixture string;
  - a determinism test whose two operands were one expression;
  - the test file's rationale docstring;
  - a fragment directory named outside the registry.

  All 6 were fixed in one batch, and the six modules ran 807 passed. Those fixes add the two
  Modified entries under Files touched.
- Reach: see Reach; `DEF-4123` stays live
- Task 0: Item 1 refuted on one figure (the 18 claim-overlap pairs), ruled continue (ack
  `20261118T080812Z-air-2bef6b`); Item 2 not real; Item 3 unmeasured. The cell, collision not
  real × reading unmeasured, is not one of the table's: no wave is licensed, and `DEF-4123` is
  recommended for a re-scope, not a strike
- Date: 2026-11-18
