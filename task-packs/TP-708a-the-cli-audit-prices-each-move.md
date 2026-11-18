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
  argument. Every component is counted over the set, so a move cannot zero a component by
  changing the file the events land on.

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
off), so the check runs only on this box's reflog [verified locally]. Only the counting rules
changed.

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

Items 2 and 3 are graded only after that call's ruling. The 42-day C2 share (31 of 71, 43.7%) is
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
| air-work alone, the confirmed seat (**post hoc**, not pre-registered) | 14 / 82 | 88 | 558.5 | 4.21 | unmeasured |

Beside them, never graded: the forks' reads of the CLI modules on the 15 lanes sum to 6,786 lines
(1,635 before the worktree fix), and air-work's median R plus its forks' is 416. Search calls on
the CLI modules: 77. The air seat has one cli.py lane in the window (#349), so the reading cost on
this box is in effect air-work's, as step 1 said.

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
`raising=False`.

**The sample** is 56 sites, drawn by a fixed rule, never by hand:
- the first site (by file, then line) of each of the 43 targets;
- all 8 sites that patch through cli;
- 5 `raising=False` patches of `_INTERPRETER_WARNING_EMITTED`, at evenly spaced indices of the
  sorted list, the sites already drawn removed.

**The method.** It ran in a fresh clone at P, never in a live checkout. For each site, the patched
value is replaced by a sentinel that raises on any use and logs where it is used. The site's tests
run green first, and each run imports espalier from the clone.

**The result** [measured, at P]:
- **49 sites go red**, so their patches reach the code. All 8 through-cli sites are among them.
- **7 stay green, and each is read by hand, never counted as vacuous.**
  - 3 are live. One of them is called by cli, which swallows the sentinel's error; the original
    patch value raises too, so the sentinel is the same input. The other two assert that a
    recorder was not called. With the defect each test guards seeded, both go red, and the
    sentinel is read.
  - 4 are inert. The patched value is never read on the test's path, and the test's claim does
    not depend on it. One function resets `_BELOW_FLOOR_ANSWER` itself before reading it; two set
    the warn-once flag on paths that never warn; one asserts a refusal message the flag does not
    control, and a seeded refusal turns it red with the flag never read.
- **Vacuous: 0 of 56.** The pack expected 0 [probable], and it holds on this sample.

Across all 88 test nodes the sample ran, 20 stay green under the sentinel. Five of those sit
inside shared helpers that reach the code in some tests and not in others.

**What it cannot see.** A read such as `x is None` passes the sentinel without triggering it,
which is why every green with no logged read was checked by hand. Every cli name exists at P, so
the hazard of `raising=False` does not show yet: it appears after a move without re-exports. Two
of the 5 sampled `raising=False` patches are read today and would then miss silently. That is
Task 4's re-export branch, priced below.

**One test defect, found and filed** (`DEF-5127`, §C0, minor): in
`tests/test_python_floor.py::TestFloorAtTheThreeDecisionSites::test_detect_python_command_does_not_promise_working_guards_on_python_2`
the recorder over `::_warn_interpreter_below_floor` takes one argument, and its one caller passes
two. With `DEF-727`'s shape seeded back, the test fails with a `TypeError` and its assertion never
runs. The row is not a vacuous patch, so it is outside the one case Files touched names. The
dispatcher kept it on the lane (ack `20261118T040752Z-air-ff0cf7` on request `71f10f`): the
lane's own sample found it, and it was filed through the same verb. Landing names its two files as a
deviation from the Files-touched pass criterion. The test itself stays unmodified, as Files
touched requires.

**Task 4's two counts overlap; they are not a split** [verified, the census's `patches` section at
P]. Task 4 names 31 targets with more than one loader (131 sites) and 12 that cli imports from
elsewhere (30 sites). The census reads the same four figures. They sum to 161 sites against the
149 in all because the two sets overlap: 10 of the 12 imported names also have more than one
loader. The 43 add up by coincidence. The partition at P:

| Targets of the 43 | Targets | Sites |
|---|---|---|
| More than one loader, defined in cli | 21 | 104 |
| More than one loader, imported into cli | 10 | 27 |
| One loader, imported into cli | 2 | 3 |
| One loader, defined in cli | 10 | 15 |
| All | 43 | 149 |

This read was first sent to the dispatcher as an inconsistency (request `71f10f`). It is not one.

The sample ran in a scratch clone. Its harness is not in this lane (Files touched), so a re-run
rebuilds it from the rule and the method above.


## Landing
- State: DRAFT
- Commits:
- Suite: `python3 scripts/proof_tier.py --run --base origin/main` on the lane (the tier it prints)
- Earn-the-red: per section, against Task 9's table
- Red-team at authoring (2026-11-17, each reviewer in its own context): the reasoning review
  (checklist v1, failure-mode reviewer), REQUEST CHANGES (checklist PASS 4, GAP 4, BIAS 5,
  UNCHECKED 8; failure modes Regression 0, Gap 10, Rough-edge 7); the architecture review, 13
  findings, each load-bearing one verified in the code. All folded, except one acknowledged: the
  collision floor's cause is left to the census (its claim-overlap row) rather than argued. One
  process slip: the two reviewers shared one scratch directory, and one overwrote the other's
  script mid-run (Core Rule 14). The reruns went to a subdirectory, and in-lane reviews each get
  their own (Task 9).
- Red-team in lane: the reasoning review on the Audit result and the census; the test-infrastructure read; the code review the tier names
- Pre-registration commit:
- Deviation, not a pass: the criterion that `git diff --name-only origin/main...HEAD` lists only
  Files touched fails by its letter on `task-packs/ledger.d/DEF-5127.md` and
  `task-packs/probes.d/DEF-5127.json`. These are a test that reds for the wrong reason, found by
  Task 4's sample, and not a vacuous patch. They are kept on the lane by the dispatcher's ack
  `20261118T040752Z-air-ff0cf7`.
- Reach: see Reach; `DEF-4123` stays live
- Task 0:
- Date:
