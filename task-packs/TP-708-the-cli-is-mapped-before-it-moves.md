# TP-708 — The CLI is mapped before it moves: an audit of `espalier/cli.py`, and only the refactor it can justify

## Status

- Version target: self-host maintainer cost. No wave changes what an adopter sees: the
  `espalier` command names, flags, help text, exit codes and output stay as they are, and so do
  both entry points. Those are the console script `espalier.cli:main` (`pyproject.toml`,
  `[project.scripts]`) and `python -m espalier.cli`, which `.github/workflows/refresh-externals.yml`,
  `bench/baselines/espalier/setup.sh` and the shipped `espalier/assets/docs/INSTALL-CI.md` run.
  `espalier/cli.py` is not a `tools/cc/` file and has no vendored mirror.
- Type: refactor, audit first. The god-file scanner's line count is reported in the audit and
  never graded (ruling 3 below).
- **Kind: ROADMAP.** Wave 0 is one child, `TP-708a` (`Kind: PACK`): a read-only audit of the
  module that lands a census and its own Audit result, assigned to the next free worker slot.
  Waves 1 and 2+ are named here in shape only. The dispatcher authors their children from
  `TP-708a`'s Audit result, and they go to the operator for approval before any is assigned
  (Gate A, below).
- Authored 2026-11-17 by the dispatcher seat `air` on the operator's ruling on call
  `20261115T192546Z-air-35136c` (ack `20261117T212142Z-air-581de4`, given as "rule questions as
  recommended"):
  1. The pack is authored now as a roadmap. Wave 0, the read-only audit, goes to the next free
     worker slot. Its refactor waves are scoped from the audit and come back to the operator for
     approval.
  2. Scope: `espalier/cli.py`, with its boundary to `espalier/doctor.py` read inside the audit;
     `doctor.py`'s own refactor is out.
  3. The success metric is pre-registered by the audit: a maintainer cost it measures (the
     catch-ups and conflicts `cli.py` causes, the lines a lane must read), never a line count.
- Standing from the operator's earlier ruling (call cc862b, ack df6595): no seat starts `cli.py`
  refactor work before this pack's refactor waves are approved. Lanes already touching `cli.py`
  (win's `DEF-985`, air-work's `DEF-5118` at authoring) go on as assigned.
- **The dispatcher's folds, each reversible by the operator:**
  1. **Wave 0's population** is the live rows whose site cell names `espalier/cli.py` (31 at
     `17d83e0`), a lower bound: 8 more cite `cli.py` only in their body (Reach). The 581de4 ack's
     23 is the first-path subset, which reads 22 with a dotfile-aware tokenizer.
  2. **"Read-only" means no product code changes.** The lane lands a self-host census script
     (`scripts/`, never deployed) and records: the metric is re-read after every wave, and a
     census in prose cannot be.
  3. **The wave-1 infrastructure is approved with the refactor waves**, not built ahead of them:
     it pays only if a move happens, and wave 0 sizes it.
- Ledger: `DEF-4123` (§C0) is the module's row. One §3 pack row names this roadmap and `TP-708a`.
  No `DEF` row is filed at authoring.

## Motivation

**The module.** Read at `17d83e0` (2026-11-17) by `wc -l espalier/cli.py` and an `ast` read of
its top-level nodes: 17,790 lines, 310 top-level functions (64 public, 36 `cmd_*`), 13 classes.
The largest functions are `espalier/cli.py::cmd_upgrade` (929 lines),
`espalier/cli.py::build_parser` (890), `espalier/cli.py::deploy_harness` (344) and
`espalier/cli.py::cmd_init` (337). It grew from 11,060 lines on 2026-09-21 (`CLO-25`'s
re-derivation) through 17,265 at `600d93f` on 2026-11-15 (`DEF-4123`'s read) to 17,790: 6,730
lines in 57 days.
36 of the 385 first-parent commits in the 30 days to the read touch it
(`git log --first-parent --since="30 days ago" --format=%h 17d83e0 -- espalier/cli.py | wc -l`,
against the same read without the path). That window counts back from the clock, so it slides:
the reasoning review read 35 of 384 a few hours later. `TP-708a` anchors every window to its
pin's commit date.

**What the record says the cost is: the authoring-time reads, which narrow the premise.**
`DEF-4123` says a lane changing one command "collides with the next lane in it". The merge
record does not show that:

- **Conflicts.** Every non-pull-request merge in main's history was replayed with
  `git merge-tree --write-tree --name-only --no-messages <m>^1 <m>^2`, where exit 1 means a
  conflict: 511 of them. These are catch-ups, stacked lanes and hand merges, all on the lane side,
  reached through the pull-request merges' second parents; none is on the first-parent line. The
  record starts 2026-09-24 (`git log --reverse 17d83e0`). `espalier/cli.py` conflicted in **1**
  of the 511 (`42cd25d`, 2026-10-01). The instrument does see conflicts: 150 of the 511 conflicted
  on some file. Of the 30 that conflicted in the last 30 days, `tests/test_declared_limits_contract.py`
  was in 10 and `docs/HOOKS.md` in 4, and `cli.py` was in none. *(Measured; the reasoning review
  re-derived every figure. The ship driver never rebases a pushed lane (`tools/cc/ship.py`), so no
  lane escaped the replay that way.)*
- **Concurrent pull requests.** `TP-708a`'s Motivation reads 0 conflicts in 21 catch-ups
  (`scripts/merge_cost_census.py --prs 40`) and 0 of 30 concurrent pairs sharing `cli.py`
  (`scripts/lane_overlap_census.py --prs 40`), over #673 to #713: **about 44 hours, with only 2
  `cli.py` pull requests** (#680, #686), so it says little. The reasoning review's 30-day read:
  **3 concurrent `cli.py` pairs** by pull-request open windows (669/668, 589/588, 430/429) over 35
  `cli.py` pull requests, and **18 cross-seat pairs** by claim-to-release windows over 70 lanes
  from 2026-10-06 *(both probable: `gh` stamps and the mail)*. Claims are where seats overlap: a
  pull request is open a median 1.07 h, a claim 2.4 h.
- **Sequencing holds.** The dispatcher held a lane over a `cli.py` overlap once in the whole mail
  record (note 479698, 2026-11-17). 98 claims across the four seats name the file in their paths.
  *(Measured over the four mail refs. A message's paths are its sender's own declaration, so a
  hold written without the path is missed.)*
- **Catch-ups are not a file-caused cost here.** The up-to-date rule is off (branch protection
  reads `strict: false`; the banner's `Merging:` line). So a catch-up that carries `cli.py`
  changes is main's churn arriving, not something the file caused, except through a conflict or a
  hold, and both are counted above. 54 of the 264 non-pull-request merges in the 30 days changed
  `cli.py`, and that figure grades nothing.
- **Unchecked premise.** Collisions may be rare because the claim protocol prevents them, at a
  cost nobody counts. Claim 45df70 (air, 2026-10-09) reads "By function, to stay off the live
  claims": a lane bent its own shape around another seat's claim. `TP-708a` reports this as
  unmeasured unless it finds a read.

So the collision half of the premise reads low over every window read; the 30-day pairs show
where lanes could have collided, not a collision. What remains is the reading cost (one
command's change inside a function hundreds of lines long) and the accretion `DEF-4123` names.
Neither has been observed, only predicted from function lengths. The audit decides whether
either is worth a refactor wave.

**The history.** `CLO-25` declined a split on 2026-09-21 (no adopter cost named; the god-file
scanner exempted the file, an exemption since gone:
`espalier/scanners/godfiles.py::EXEMPT_PREFIXES` holds `tests/fixtures/` alone). The operator
reopened it on maintainer cost on 2026-11-15 (cc862b, df6595) and ruled this pack in on
2026-11-17 (581de4).

**Who is hurt** (`docs/STANDING_PRINCIPLES.md` §16): the seat whose lane changes one command in
`cli.py`. It reads a function hundreds of lines long to change one branch of it. It also waits,
or bends its lane around a live claim, when another seat is in the same file. Both happened on
the record: note 479698 (win's `DEF-985` against air-work's `DEF-5118`) and claim 45df70.

## Scope (in) — the waves

1. **Wave 0 — `TP-708a`, the audit** (`task-packs/TP-708a-the-cli-audit-prices-each-move.md`),
   beside live lanes, no product code changed. It lands a concern map and the module's layer
   order; an accretion read of the largest functions; each unit's move cost (the tests that
   patch it, every importer, every citation in any tracked file type, the ledger probes and
   path-reading tests that would go stale); the size, only, of the wave-1 infrastructure; the
   `doctor.py` boundary; the triage of the population under Reach; and the metric (below), its
   thresholds committed before the census runs. Its Task 0 mirrors this file's. It waits on
   nothing: it reads one pinned commit and edits no file a live lane claims.
2. **Gate A — the operator.** At wave 0's landing the dispatcher sends one `OPERATOR CALL:` with
   the Audit result and the decisions listed below. No wave-1 or wave-2 child is authored before
   the ruling.
3. **Wave 1 — the infrastructure**, approved at Gate A only if a refactor wave is. Both land
   before any move. Shape only here; wave 0 sizes them.
   - **`TP-708b`, the patch check.** It is a check on each lane's diff, not a rule about names.
     For every definition the lane moves, each `cli.<name>` patch of a global that definition
     reads or writes must be re-pointed, and the red is earned on a seeded partial move. The
     name-level rule 35136c sketched ("loaded by some function in the module patched") stays
     green after a partial move whenever unmoved code still loads the name, and 36 of the 43
     patched targets are helpers several commands share (both reviewers' AST reads; probable).
     So it would be born weak (`docs/FAILURE_MODES.md` §2.14; `docs/SHARP_EDGES.md`, *A mutation
     proves what it kills, not what you meant it to kill*).
   - **`TP-708c`, the citation re-key tool.** It re-points live citations and leaves the record
     surfaces alone (Core Rule 13, `tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS`).
     It covers every tracked file type, not `.md` and `.json` alone: 57 more citations sit in
     `.py` and `.cmd` files, which no test resolves (verified). It covers every spelling (bare
     `cli.py::`, `cli.py:NNN`, `espalier.cli.X`), and the 48 citations in tracked packs, which
     `espalier/surface_contract.py::is_shipped_pack` leaves neither record nor checked.
4. **Waves 2+ — one unit per lane** (`TP-708d` onward), each approved at Gate A, its shape read
   off the audit's "moved by" column:
   - **A layer move, bottom-up.** The call graph at `17d83e0` is acyclic apart from one
     3-function cycle (`::_detect_python_command`, `::_remedy_interpreter`,
     `::_warn_interpreter_below_floor`); the interpreter core (18 functions, 656 lines) calls no
     other `cli.py` function, and the settings set calls nothing above it. Interpreter core, then
     settings, then deploy, then the commands creates no new import cycle; a higher layer first
     does. *(The architecture review; graph verified, order its inference.)*
   - **A cluster move.** Weaker than it reads: by the concern-map method 197 of 310 functions
     (8,250 of 15,515 function lines) are shared between commands, and init, upgrade,
     merge-settings, install-ci, fingerprint and render-template reach 225 functions, 61% of the
     file (verified).
   - **A decomposition** of one large function: the only shape that can move per-function
     reading cost, since a moved function keeps its length. `::cmd_upgrade` and `::build_parser`
     carry about 47% of the summed function-length read (30.4% and 17.0%; verified).

   Whichever shape: new modules are flat siblings in `espalier/`, never a subpackage
   (`tools/cc/sister_site_probe.py` and the memo census scan `espalier/*.py` only); a write-only
   global (a latch, a memo dict) moves with every function that reads or writes it
   (`::_detect_python_command` writes `_BELOW_FLOOR_ANSWER`, `::_refuse_below_floor_wiring` reads
   it, and a reads-only graph splits them); its tests and citations are re-pointed in the same
   lane; it starts only when no live claim names the unit's symbols (the board's `claims:` and
   `overlaps:`, not a remembered list); and it is re-measured at its landing on the component
   its shape can move. A wave that misses its threshold stops the next, and the dispatcher
   re-raises.

### Decisions Gate A takes

1. **Which shapes are allowed**, from the alternatives below. 35136c put the moves "into a new
   module" on the strength of `docs/CONVENTIONS.md`, *A "decompose godfile" refactor into
   in-file helpers doesn't move the godfile metric*. That entry grades line count, which ruling 3
   excludes, so it does not by itself rule out decomposing a function in place.
2. **Re-exports.** Should a moved name stay importable from `espalier.cli`? This is now the
   load-bearing design decision. Tests touch 242 `cli` names, 233 of them defined in `cli.py`
   (verified), almost all private. The architecture reviewer recommends no re-exports, so a stale
   patch fails loudly *(their recommendation; untested)*. With re-exports, a latch splits into two
   copies (`tests/conftest.py::_restore_interpreter_warn_flag` would restore the wrong one), and a
   patch of the old name goes silently vacuous.
3. **The `doctor.py` cycle.** It does not break by moving the names only doctor reaches.
   `espalier/doctor.py` takes 43 names from `cli.py` through 20 lazy import lines. Only 2 of them
   are reached by doctor alone. The closure of all 43 is 139 definitions and 3,283 function lines,
   and it reaches `espalier/doctor.py::_interpreter_is_python3` (verified). Ending the cycle needs
   a `doctor.py` code change, which ruling 2 excludes. Gate A decides whether to leave the cycle,
   or to lift ruling 2 for doctor's import lines and interpreter probes alone. This roadmap does
   not promise a cycle break. `espalier/cleanup.py` and `espalier/render_surface.py` hold the two
   other lazy back-import cycles.
4. **`tools/cc/` citations.** Some citations of `cli.py` constants live in `tools/cc/` hooks and
   their vendored twins: `tools/cc/hooks/_reinject.py::_GENERATED_DOC_REGIONS`, the hooks
   `_start_refusal.py` and `session_start.py`, and the deployed `tools/cc/statusline.cmd`. A move
   lane either keeps the cited constant in `cli.py`, or re-keys the comment or docstring
   citation with the vendor sync. No `tools/cc/` behaviour changes either way.
5. **Which components grade.** Taken from the audit's 2x2 (Task 0) and its thresholds.

**The alternatives Gate A weighs**, any of which `TP-708a` may recommend: strike `DEF-4123` now;
decompose only `::cmd_upgrade` and `::build_parser`; keep the concern map as a maintained
navigation aid (a generated index) and move nothing; layer moves, bottom-up; cluster moves.

## Scope (out)

- **`doctor.py`'s own refactor.** Ruling 2. The boundary is read inside the audit, and the cycle
  is a Gate A question (above), not a wave's assumption.
- **A mechanical split.** That is `DEF-4123`'s fix shape: a move graded on no pre-registered
  component, or one that only shortens the file, is not a wave.
- **Line count as the success metric.** Ruling 3. The scanner's count is reported, never graded.
- **Any change to the CLI's adopter-facing behaviour:** command names, flags, help text, exit
  codes, output, and both entry points (Status). A move is internal. A defect a mover finds in a
  command is its own ledger row, never a drive-by in a move lane.
- **A subpackage conversion** (`espalier/cli/`). It would escape the scanners that read
  `espalier/*.py`, and it would need its own `__main__.py` for the `-m` entry point.
- **Fixing the population's rows in wave 0.** Wave 0 triages them and edits no ledger row. Each
  stays with its assigned seat or on the ledger.
- **`tools/cc/` behaviour changes.** A re-keyed citation in a comment or docstring is the most a
  move lane may do there, with Gate A's word and the vendor sync.
- **`cli.py` refactor work of any kind before Gate A** (df6595, standing).

## Task 0 — Verify (the roadmap's; `TP-708a` mirrors it)

The exit from every cell is stop and re-raise to the operator at Gate A, never adjust and
continue.

**The one rule that ends the waves: a 2x2.** Two questions, each answered by components
pre-registered in `TP-708a` (below):

- **Is the collision cost real?** The components run over a fixed window anchored at the pin's
  commit date. Every figure carries its window and its count of `cli.py` pull requests.
- **Is the reading cost real?** Answered by the observed reading instrument, never by the
  function-length proxy alone.

| | Reading cost not real | Reading cost real |
|---|---|---|
| **Collision cost not real** | No refactor waves. Gate A's call recommends `DEF-4123` re-scoped or struck on the operator's word | Decomposition waves |
| **Collision cost real** | Module or layer moves | Both, with the layer moves first |

A component the audit cannot tie to a lane's real time is a result of its own. It is reported
to Gate A as **unmeasured**: never a silent kill and never a license. A cell built on an
unmeasured component says so in the call.

**Pre-registration, stated honestly.** The thresholds are committed in `TP-708a`'s file at its
step 1, before the census runs at the pin and before any wave is proposed. None may change after
that commit.
- The authoring reads (conflicts, pairs, holds, the function-length proxy) are visible in both
  packs, and the packs say so.
- The observed reading instrument has never been read, so it is the one blind component.
- Conflicts grade nothing because their baseline sits at the floor (1 in 511), where no move can
  show a gain. Having been read is not the reason.

**A second reader.** The Audit result gets a reasoning review in a fresh context before Gate A's
call goes out. A recommendation only its author has read is not sent.

## Relevant memory

Recent pattern: the last `cli.py` "decompose" grew the file by 104 lines. The loudest stated cost
of this module, collisions, reads 1 merge in 511 on replay. And both reviews of this roadmap
found its first metric able to pass its own treatment by construction. So the obvious fix, the
obvious premise and the obvious grade have all been wrong here before measurement.

| Entry | Where |
|---|---|
| A "decompose godfile" refactor into in-file helpers doesn't move the godfile metric | `docs/CONVENTIONS.md` |
| An early-return guard silently hollows out the tests below it | `docs/FAILURE_MODES.md` §2.14 |
| A mutation proves what it kills, not what you meant it to kill | `docs/SHARP_EDGES.md` |
| The measuring instrument is a claim too | `docs/sharp-edges/the-measuring-instrument-is-a-claim-too.md` |
| Classify a surface before you measure it | `memory/classify-the-surface-before-measuring-it.md` |
| Check the layer before the class | `memory/check-the-layer-before-the-class.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| Parallel work is safe by construction | `memory/parallel-work-protocol.md` |

These were picked by hand from the tree at authoring. Three `python3 tools/cc/hooks/_recall.py`
queries returned nothing that bears on this work ("god file split refactor large module", "test
patches a module attribute after a move", "pre-register the metric before measuring"). Re-run
them rather than trusting this list if the pack has been sitting.

## Implementation — the wave map, the gates, the metric's shape

### The wave map

| Wave | Child | Kind | Assigned | Waits for | Approved by |
|---|---|---|---|---|---|
| 0 | `TP-708a` | PACK, read-only of product code | the next free worker slot | nothing | the operator's ruling on 35136c (given) |
| A | (Gate) | an `OPERATOR CALL:` | the dispatcher, at `TP-708a`'s landing | `TP-708a` merged; its Audit result reviewed | the operator |
| 1 | `TP-708b`, `TP-708c` | PACK each | after Gate A, if a move is approved | Gate A | Gate A |
| 2+ | `TP-708d` onward | PACK, one unit each (a layer, a cluster, or a decomposed function) | one at a time | wave 1 merged; no live claim on the unit's symbols; the previous wave met its threshold | Gate A |

### The metric's shape *(`TP-708a` pre-registers the numbers)*

A maintainer cost, never a line count. Each component has a command that a later wave re-runs at
its own pin, and a shape that can move it (`TP-708a` Task 7 holds the full table).

**Reading.**
1. **Lines actually read (primary, observed).** Count the lines of the CLI modules that the
   seats' Read tool calls returned, per lane, against the lane's total reads. The source is the
   seats' own session transcripts, `~/.claude/projects/<project>/<session>.jsonl`. On this box
   that is the air and air-work seats: 388 and 203 session files at authoring. The Windows seats'
   transcripts are not here, so the population read is named on every figure. A lane that reads
   with `grep` or `sed` is undercounted by an instrument that counts Read calls *(probable;
   `TP-708a` says how it treats them)*. This component has never been read.
2. **The function-length proxy (secondary, predicted).** The summed lengths of the top-level
   functions a lane's hunks fall in, at the lane's base. It is never a decomposition's grade on
   its own. Splitting a function lowers it by construction, whether or not a lane reads less, so
   an arbitrary equal split of one function is its must-not-pass case.

**Collision.**
3. **Conflicts on replay.** At the floor; grades nothing.
4. **Concurrent pull-request pairs sharing a CLI module**, over the fixed window
   (`scripts/lane_overlap_census.py --window <lo>-<hi>`, never `--prs 40`).
5. **Cross-seat claim overlaps**, by claim-to-release windows.
6. **Dispatcher holds** over an overlap, from the mail.

**"The CLI modules"** means `espalier/cli.py` plus every module that receives a moved
definition, existing ones included (`espalier/_python_floor.py` and `espalier/_venv.py` are the
natural homes for the interpreter core). Every component is counted over that set, so a move
cannot zero a component by changing which file the events land on.

The rules:
- A wave counts as paid only on a component committed before the census ran, whose threshold was
  written down first, and that its shape can move.
- A component no proposed shape can move is reported, and never offered as a wave's payoff.
- Every baseline is reproducible: the census takes `--at` with no default; windows are anchored
  to the pin's commit date; pull-request windows are given by number range; the mail-ref oids
  and the transcript files read are recorded; the pin is committed in `TP-708a` at its step 1.
  The job spans two windows and a scratchpad is per-session, so nothing load-bearing lives only
  in a scratchpad.

### What every refactor lane carries *(shape, untested; the wave-2 children make it exact)*

- **Behaviour preserved, by a byte oracle.** The help text of every subcommand is byte-equal at
  the lane's base and head, through both entry points. So are the exit code, stdout and stderr of
  each command on a fixed fixture tree. `COLUMNS` is pinned for every run, since argparse wraps
  help at the terminal width and an unpinned compare flakes across hosts. A move that changes any
  of these is not a move.
- **Every importer still served**, outside tests too, about 62 names in all (verified):
  `espalier/doctor.py`, `espalier/cleanup.py` and `espalier/render_surface.py` (each a lazy
  back-import), `espalier/fuse.py` (calls `::cmd_init` and `::cmd_install_ci` with a hand-built
  `argparse.Namespace`), `espalier/__main__.py`, `scripts/generate_doc_regions.py`, and
  `bench/run_benchmark.py` (imports `::deploy_harness` for the release-gating bench).
- **No vacuous patch.** Wave 1's diff check is green at the lane's head.
- **No silent stale reader.** The ledger probes that read a moved symbol: 27 live rows' probes
  depend on `cli.py`, and one reading a moved symbol can turn its row into a false STRIKE
  CANDIDATE, as `DEF-1079`'s would (it reads `REQUIRED_GITIGNORE` from `cli.py`), since
  `tools/cc/check_ledger_probes.py` checks a probe's subject at file level only *(mechanism and
  `DEF-1079` verified; the rest probable)*. And the 5 tests that read `cli.py` by path, which
  stop guarding moved code without failing (verified). The 88 path literals and 34 (path,
  symbol) keys that go red loudly are a cost, not a risk.
- **Record surfaces untouched.** The re-key tool's run in the lane leaves every path in
  `tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS` byte-equal.
- **The re-measure**, on the component its shape moves, written into the lane's own Landing.

### What the children do not do

- None moves `espalier/doctor.py` code without Gate A lifting ruling 2 for it by name.
- None changes `tools/cc/` behaviour. At most, a comment or docstring citation is re-keyed with
  the vendor sync, on Gate A's word.
- None fixes a population row except as its own triaged item, and then only in a lane of its own.

## Affected symbols

A roadmap: each child declares its own `## Affected symbols`, and `/scope-check` runs on the
child, not here. The four sub-sections declare nothing on purpose.

### Changed-semantics
- None.

### Renamed
- None.

### Added-paths
- None.

### Removed-paths
- None.

## Reach

Not a class pack. It mints no row, and wave 0 closes none. The rows it touches, so that no later
pass reads them as shut:

Members derived by: the live rows of `task-packs/ledger.d/*.md` whose site cell names
`espalier/cli.py`. A row is the fragment's second line, split on `|`. Its id cell is the first
cell, and a struck row's id cell opens with `~~`. Its site cell is the second. At `17d83e0` that
gives **31** when `cli.py` appears anywhere in the site cell, and **23** when it is the cell's
first path (22 with a dotfile-aware tokenizer). The population is a lower bound: 8 more live rows
cite `cli.py` symbols only in their body (`DEF-5118` among them). Re-run the read at the pin; the
counts here are its value on the day.

| Item | Status | Evidence |
|---|---|---|
| `DEF-4123` (the module's row) | **NOT CLOSED by wave 0.** Closed only by refactor waves that meet the pre-registered metric, or struck or re-scoped on the operator's word at Gate A | `TP-708a`'s Audit result and Gate A's ruling |
| The population above (31 live rows at `17d83e0`, `DEF-4123` among them) | **NOT REACHED by wave 0**: triaged into units and classed (fix before the move, fix in the move's lane, independent), never fixed or edited | the triage table in `TP-708a`'s Audit result |
| The 8 body-only rows | **NOT REACHED**: reported apart in the triage | the same table |
| A vacuous test patch the audit finds today | **Filed in-lane if any**, as its own row, never fixed in wave 0. None is expected: both reviewers' AST reads found 0 name-level candidates (probable) | the census's patch read |

## Pass criteria

- `TP-708a` is `LANDED`, with its Audit result, its Task 0 cell and its reviewer's verdict in its
  own Landing.
- Its thresholds were committed before its census ran at the pin: the commit order on its lane
  shows it.
- Gate A's call has been sent and ruled, and the ruling is recorded in this file's Landing.
- Every child is `LANDED` or `SCRAPPED` in its own Landing stanza before this file's state
  leaves `ROADMAP`.
- Each refactor lane's Landing carries its re-measure on the component its shape moves, and the
  byte oracles above at its head.
- No criterion here licenses shipping a defect in a gate a child delivers: a patch check green on
  a seeded partial move, a re-key tool that edits a record surface or misses a file type, a
  census whose replay cannot see a conflict, or a reading grade an arbitrary split passes is that
  child's defect, never a scope-out.

## Files touched

- **This authoring lane:** `task-packs/TP-708-the-cli-is-mapped-before-it-moves.md` (new);
  `task-packs/TP-708a-the-cli-audit-prices-each-move.md` (new); `task-packs/FORWARD_LEDGER.md`
  (one §3 pack row).
- **Wave 0's lane:** `TP-708a`'s own Files touched.
- **Unmodified on purpose:** `espalier/cli.py`, `espalier/doctor.py`, `tools/cc/`,
  `task-packs/ledger.d/` (no row is edited at authoring or in wave 0).

## Sub-task ordering

1. **Author** (this lane). The roadmap by hand, `TP-708a` by a drafter fork, a reasoning review
   and an architecture review in fresh contexts, folded by one fork per file before the push.
   *Checkpoint:* `python3 scripts/check_pack_fences.py <both packs>`, `espalier scope-check` on
   `TP-708a`, and
   `pytest tests/test_forward_ledger_completeness.py tests/test_cross_pack_assertions.py -q`
   green, then the tier the tier script prints.
2. **Assign wave 0** at the next free worker slot, by its lane, in the assign shape.
   *Checkpoint:* the board's `jobs:` row.
3. **Wave 0 lands.** *Checkpoint:* its PR merged and post-merge green.
4. **Review the Audit result, then Gate A.** *Checkpoint:* the call on the board's `asks:` line,
   then the ruling's ack.
5. **Waves 1 and 2+**, if ruled in, authored from the Audit result. *Checkpoint:* each child's
   own.

## Estimated effort

- Authoring, with the two reviews and the fold: about 4.5 hours (measured on this lane).
- Wave 0: `TP-708a`'s own estimate (one worker, two windows).
- Gate A: the review of the Audit result and one call, about 1.5 hours of dispatcher time.
- Wave 1: two lanes, unmeasured until wave 0 sizes them.
- Waves 2+: one lane per unit, sized by the audit, unmeasured here.

## Landing
- State: ROADMAP
- Commits:
- Suite: `python3 scripts/proof_tier.py --run --base origin/main` on the authoring lane (packs and
  one ledger row)
- Earn-the-red: per child, against the mutation its Implementation names
- Red-team: two reviews in fresh contexts, 2026-11-17, folded before the first push. The
  reasoning review (failure-mode-reviewer, checklist v1): REQUEST CHANGES, PASS 4, GAP 4, BIAS 5,
  UNCHECKED 8; failure modes Gap 10, Rough-edge 7, Regression 0. Folded: one 2x2 end rule for two
  that disagreed, the observed reading instrument with its must-not-pass split, the 44-hour
  window named, catch-ups dropped as a cost, thresholds committed at the child's step 1, a
  reproducible baseline, decomposition waves allowed, the alternatives named. The architecture
  review (architecture-analyst): 13 findings, most verified in the code. Folded: the doctor cycle
  as a Gate A question, layer moves, the shared-function share, write-only globals, the diff-level
  patch check, re-exports as the load-bearing decision, the second entry point and every
  importer, citations in every file type and in `tools/cc/`, ledger probes and path-reading tests,
  flat sibling modules, receiving modules in "the CLI modules". Acknowledged, not changed: the
  claim protocol's hidden cost (45df70) stays an unchecked premise with no instrument. Process
  slip: the two reviewers shared one scratch directory and one overwrote the other's script
  mid-run (Core Rule 14); it re-ran in its own subdirectory, and the next fan-out gives each its
  own.
- Reach: see Reach; no row closed at authoring
- Task 0: the 2x2 is `TP-708a`'s to read; the authoring reads are in Motivation
- Gate A:
- Date: 2026-11-17 (authored)
