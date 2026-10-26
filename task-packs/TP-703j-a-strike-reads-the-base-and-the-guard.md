# TP-703j — A strike reads the base and the guard: the probe driven on both sides, the test red there and green here

## Status

- Version target: adopter-facing where the forward ledger is kept: `tools/cc/ledger_row.py`
  deploys through `espalier init` via the vendored byte-copy, `espalier/_vendor/cc/`, and
  `tools/cc/check_ledger_probes.py`, whose runner this pack reuses, deploys beside it.
- Type: workflow tooling (two flags on one verb; one new refusal) plus its tests.
- **Kind: PACK.** One lane, `lane/strike-reads-the-base`, suited to any seat; its Task 0's replay
  runs on any clone that holds `origin/main`'s history.
- Parent: `TP-703` (`task-packs/TP-703-multi-seat-discipline.md`), Scope (in) item 10, Wave 3.
  Nothing in Wave 1 or 2 gates it; it waits only on its own Task 0.
- Authored 2026-10-18 (local; 2026-10-19 UTC) by the dispatcher seat `air` on the operator's word
  ("good, lets make task packs for fixing these issues"), from the lessons reviewer's unification
  of the same evening: "strike `--base/--guard` 80% built". That figure was the reviewer's read
  and is corrected under Motivation: the runner is built and used at two of the three verbs; the
  strike is the one verb that drives nothing.
- Ledger: no row filed at authoring (`memory/parallel-work-protocol.md` item 8). The lane strikes
  nothing and mints nothing; a defect its Task 0 finds in the runner is filed in-lane.
- Executed 2026-10-25 by the seat `air-work` on `lane/strike-reads-the-base` (the dispatcher's
  assign `20261025T224349Z-air-7e0520`). The 0-A review (code-reviewer, checklist v2: REQUEST
  CHANGES, WARN and NIT only, the premise intact) and the readiness leads of 2026-10-19 were
  folded in just in time, each marked *(0-A, 2026-10-25)* below; the request to the dispatcher
  carrying them is `20261025T231336Z-air-work-3ea70d`, its ack `20261025T231952Z-air-6a811c`.
- The discipline this pack carries forward is `docs/STANDING_PRINCIPLES.md` §7, earn the red, and
  the blueprint-authoring skill's rule that the measuring instrument is a claim: a strike's probe
  that was never driven at the base has never shown the defect existed where the row said it did.

## Motivation

A ledger row is struck with `python3 tools/cc/ledger_row.py strike <id> --text-file <closing
text>`. Read on 2026-10-18 at `397799c8`:

- `tools/cc/ledger_row.py::strike` reads the row, writes the struck member and index lines, and
  queues the probe file's deletion through `::_retire_probe_files`. It drives nothing. The
  closing text is the author's sentence.
- `tools/cc/ledger_row.py::file_row` and `::repin` drive the row's probe before they write,
  through `tools/cc/check_ledger_probes.py::run_probe` (loaded by the verb's `_load` helper, its
  `_ROOT` set to the repo root): the three-way verdict `STILL_OPEN`, `STRIKE_CANDIDATE` ("prints
  X, open_value is Y") or `UNRESOLVED`, the same argv split, cwd and timeout the recurring
  check uses. A filing whose probe does not print its open value files nothing
  (`tests/test_ledger_row.py::test_a_probe_that_does_not_print_its_open_value_files_nothing`).
- So the runner, the verdicts and the gate at the write exist; what the strike lacks is the call,
  and what no verb has is the other side: the probe's reading on the tree before the lane, where
  the row says the defect is, and a guard test's reading there.

**What a drive on both sides would have caught.** On 2026-10-18 the dispatcher wrote that a
landed census "closes `DEF-985`"; the row's probe at the time read an adjacent question (raw
spawn sites, not quiet handlers) and would have printed its closed value at the head while the
named harm stood. The row was re-pinned instead (`task-packs/probes.d/DEF-985.json`,
`verified_2026_10_18`: the probe now reads the harm, 35 quiet handlers on the lane's head). A
base-and-head drive of that probe would have passed too: the proxy closed on both sides for the
wrong reason. That is the pack's honest limit (Scope (out), sufficiency): the drive is necessary,
not sufficient. What it does catch is the other two ways a strike lies: a probe never open at the
base (the defect was not there, or the probe never read it), and a guard green on the unfixed code.

**The named user (§16).** The seat that strikes a row at the end of a lane and types its closing
sentence from the diff it just wrote, with no tool between the sentence and the record; the next
seat, who reads a struck row as a measured closure; and the operator, who approved the lane on
the row's claim that the probe showed a defect.

## Scope (in)

1. **`--base <ref>` on `strike`.** The row's probe is driven at `<ref>` (default:
   `git merge-base HEAD origin/<base>`, the commit the lane branched from, so a fix another lane
   merged after that does not make a true strike refuse; `<base>` is the default branch read
   offline from `origin/HEAD`, else `main`, else `master`, never `gh`, and where none resolves
   and no `--base` was given the strike prints one line and proceeds, since an adopter's clone may
   have no remote and the suite's own strike fixtures are plain directories *(0-A, 2026-10-25)*),
   on a temp-index checkout of the whole
   base tree in a temporary directory outside the checkout (`GIT_INDEX_FILE` pointed at a scratch
   file, `git read-tree <ref>`, `git checkout-index -a --prefix=<scratch>/tree/`: no
   `export-ignore` is honoured and no shared worktree state is written), with the runner rooted
   there through `check_ledger_probes.rooted` (J-2, J-5); the verdict there must be
   `STILL_OPEN` (the probe prints its open value: the defect was there). The probe is then driven
   at the head, this checkout, where the verdict must be `STRIKE_CANDIDATE` (it no longer prints
   the open value). Any other pair refuses the strike by name, nothing written, exit 2, the way
   `tests/test_ledger_row.py::test_a_refused_strike_writes_neither_file` pins the existing
   refusals.
2. **`--guard <pytest node id>` on `strike`**, repeatable. The named test is run at the head
   (green required) and at the base with the head's `tests/` directory laid over the base
   checkout (red required: the new test against the unfixed code, which is what earn-the-red
   means), with `PYTHONPATH` set to the tree each run is on, the base run's to the scratch tree
   and the head run's to the checkout, so `espalier` resolves to that tree's own package
   (`tests/_engine_check.py::pytest_sessionstart` exits 4 otherwise, and from a worktree seat the
   head run would too *(0-A, 2026-10-25)*), the box lock's variables (`ESPALIER_BOX_LOCK` and
   `ESPALIER_BOX_LOCK_HOLDER`) and the session marker removed from the child, no bytecode written
   into either tree, and the failure's exception read from the strike's own one-file pytest plugin
   on the child's path (pytest's junit report carries no exception type, measured on pytest 9: a
   `<failure message="assert 1 == 2">` with no `type` attribute *(0-A, 2026-10-25)*): an earned
   red fails by `AssertionError` or `pytest.fail`; `ImportError`, `ModuleNotFoundError`,
   `AttributeError` or `NameError` at the base is a refusal (the guard proves only that the symbol
   is new), any other exception there is a refusal too (the test never reached its assertion: a
   helper raising because the scratch tree is not a repository proves nothing about the defect), as
   is a failure outside the test's call, exit 2, 3, 4 or 5 (a collection error, an internal error,
   the engine check, nothing collected), a run of skips, a run past the guard's own 300 s bound,
   and green on both sides (a fix that lives under `tests/` rides the overlay to the base, and so
   does a guard that does not read the defect: the refusal says the guard cannot tell the two trees
   apart). A guard needs a readable base: `--no-base --guard` refuses.
3. **The reads that cannot be made are said, not skipped.** A probe the runner itself reports
   undrivable at the base (`NO_ORACLE` for a `why_not` row, 48 of 270 probe files at the lane's
   HEAD; `UNRESOLVED`
   for a missing subject or input, or a command that could not run outside a repository) is
   printed as such, by the runner's verdict and never by a word match; a `why_not` row has no
   command, so neither side is read: its reason is said once, and an explicit `--base` refuses it,
   as it refuses a row with no probe entry at all *(0-A and code review, 2026-10-25)*. Every id of a multi-id cell is driven, not the id typed alone (the cell
   closes together, `DEF-863`) *(0-A, 2026-10-25)*. The default, stated once:
   the base drive runs, and a probe it cannot drive is one printed line; `--no-base` says so on stderr, and the closing text is the author's place to
   record it; an explicit `--base <ref>` makes a failure to drive a refusal.
4. **The words.** `ledger_row.py`'s module docstring and `strike --help`; one sentence in
   `memory/parallel-work-protocol.md` item 8 (a struck row's probe was driven on both sides where
   it could be); the two flags on the `/handoff` body's strike line only if one exists (none
   found at authoring: `grep -rn 'ledger_row.py strike' .claude/` is empty).
5. **Files, for the pre-flight** (the same set as Files touched): `tools/cc/ledger_row.py`,
   `tools/cc/check_ledger_probes.py`, `tests/test_ledger_row.py`, `tests/test_check_ledger_probes.py`,
   `memory/parallel-work-protocol.md`; by the sync only, `espalier/_vendor/cc/ledger_row.py` and
   `espalier/_vendor/cc/check_ledger_probes.py`.

## Scope (out)

- **Sufficiency.** A probe that reads an adjacent question passes both sides (`DEF-985`, above).
  Whether a probe reads the harm the row names is the author's judgment, contestable by `repin`;
  no drive decides it. The pack's refusals are necessary conditions and the docstring says so.
- **A worktree of the base instead of a temp-index checkout.** `git worktree add --detach`
  would give git-reading probes a repository, but it writes the clone's shared `.git/worktrees`
  state, which two seats' worktrees of one clone both read (Core Rule 14), and SessionStart's
  clean-up removes stray worktrees. The temp-index checkout was taken after the reasoning review
  weighed it against `git archive`: no `export-ignore`, no worktree, no shared git state. A probe
  that needs a repository at the base is reported undrivable; a later lane may add
  `--base-worktree` if Task 0 item 3's count warrants it.
- **Driving the probe at the merge commit.** The head is this checkout: a strike is part of the
  lane's commit and the lane is tested merged with the base by its own CI. The combination's
  reading is the post-merge proof's, not this verb's.
- **Replaying every struck row.** Task 0 item 2 replays three to decide the pack's shape; a
  census of all 76 rows struck 10-16 to 10-18 is an instrument, not a strike flag, and is
  `TP-703f`'s kind of work if wanted.
- **The checkout's blind spots.** The scratch tree is a plain directory, not a repository: a
  probe that runs `git` cannot run there, and the runner says so (`UNRESOLVED`); the inputs gate
  `DEF-858` keeps refusing an absent input on either side. Not widened here. *(Measured
  2026-10-25 at a pristine checkout of `origin/main` 57e6846f: 7 of 222 commands undrivable by
  verdict, and 2 of the 215 drivable, `DEF-1143` and `DEF-877`, ask git inside the one-liner,
  swallow its failure and print a false STRIKE_CANDIDATE on the plain directory, which the strike
  reads as a refusal of a true strike, the safe direction; the refusal sentence names the no-.git
  base, and `--no-base` is the way past. The worktree form stays a later lane's.)*

## Task 0 — Verify (try to kill this pack)

Each item names the oracle, the result that ends the pack, and the exit, which is stop and
re-raise to the dispatcher, never adjust and continue.

1. *Oracle:* `grep -n 'run_probe\|_retire_probe_files' tools/cc/ledger_row.py` inside `strike`'s
   body. *Refuting result:* the strike already drives the probe at the head or at the base.
   *Exit:* the pack's premise is stale; re-raise. (Read 2026-10-18: the strike calls
   `_retire_probe_files` and never `run_probe`; `file_row` and `repin` call `run_probe`.)
2. *Oracle:* three rows struck 10-16 to 10-18 whose probe file was retired in a commit this clone
   holds, recovered from history (`git log -1 --format=%H --diff-filter=D --
   task-packs/probes.d/<id>.json`, then `git show <sha>^:task-packs/probes.d/<id>.json`); for each,
   the probe driven on a temp-index checkout of the strike commit's first parent (the base) and
   of its second parent or the lane head (the head). *(0-A, 2026-10-25: the deleting commit is a
   `records:` commit whose first parent already holds the lane's fix, so the base is the pull
   request's merge commit's first parent, read with `git log --merges --first-parent`, and the
   head its second parent; read literally, the item met its own refuting result on a fixed tree.)*
   Candidates read 2026-10-18, none git-reading:
   `DEF-1189` (deleted in `15fa4d35`, subject `tools/cc/hooks/_recall.py`), `DEF-1119`
   (`bc4f6f47`, `scripts/check_handoff_landing.py`), `DEF-1172` (`1e2473c8`,
   `tools/cc/ledger_row.py`), `DEF-928` (`a4ea6e03`, `espalier/analyze.py`), `DEF-982`
   (`7d0feb16`, `tools/cc/hooks/_recall.py`). *Refuting result:* two of three cannot be driven at
   the base because their inputs are files the lane added, or read `STRIKE_CANDIDATE` at the base
   (the defect was already closed there, so the strike was right and the base drive would have
   refused a true strike). *Exit:* `--base` is advisory (printed, never refusing) and the pack is
   re-scoped to the guard alone; re-raise with the three readings.
3. *Oracle:* the runner's own verdicts over the live probes at a temp-index checkout of the
   base (J-1's helper, driven by hand first, inside `rooted(scratch, pristine=True)`): the probes
   it reports undrivable there (`NO_ORACLE`; `UNRESOLVED` whose detail names a missing subject, a
   missing input or a command that failed outside a repository). *Refuting result:* more than
   half of the 216 commands. *Exit:* a plain checkout cannot drive the population; the worktree
   form (Scope out) is the shape, and this pack re-raises rather than builds it. (Read 2026-10-18
   by text, not by the runner: 255 probe files, 39 with no command, 19 commands the runner's
   `_TREE_WALK_MARKERS` read as tree-walking, 20 naming `git`; the reasoning review estimated 38
   to 48 of 216 undrivable without the pristine-root argument, a figure this item measures.)
4. *Oracle:* the time to check out the whole base tree through a temp index
   (`GIT_INDEX_FILE=<scratch>/index git read-tree <sha>`, then `git checkout-index -a
   --prefix=<scratch>/tree/`), on the Air and the `win` box (the tree of `397799c8` is 42 MB as an
   archive; the count is this read's, not a pin). *Refuting result:* over the probe runner's own
   timeout. *Exit:* check out only the paths the probe names (its `subject` and `inputs`) plus
   `tools/cc/`, the board's narrower shape, and say what a probe that walks the tree then misses.

## Cross-pack coordination *(0-A, 2026-10-25)*

- `TP-703b` (W1, the strike of `DEF-5024`) says the strike verb never runs the probe; once this
  lane lands that sentence is false and W1's strike is the first default base drive on a live row.
  Named to the dispatcher in the lane's request; the dispatcher corrects 703b in its next record
  edit after this lane lands (ack `20261025T231952Z-air-6a811c`).
- `TP-703c` names this pack's guard drive and prescribes stripping `ESPALIER_BOX_LOCK`; it also
  exports `ESPALIER_BOX_LOCK_HOLDER` for the nested pass-through. The guard child strips both.
- `memory/parallel-work-protocol.md` is shared with 703c, 703d, 703f, 703g and 703h; this lane
  adds one sentence to item 8 and nothing else.
- `tools/cc/_pack_scope.py` and `scripts/check_pack_landing.py` share the Scope (out) reader with
  the strike verb; the drive sits after that reader's refusal and changes nothing it reads.

## Relevant memory

Recent pattern, measured: the two closures this roadmap re-examined, `DEF-985` and `DEF-2025`,
were both struck on a reading at the head alone, and both were re-opened within a day by a
measurement someone made by hand. A strike that drives nothing records a sentence; this pack
makes the strike the place where the sentence is checked.

| Entry | Where |
|---|---|
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| A New Guard Is Blind The Way It Claims To See | `docs/SHARP_EDGES.md` (section of that title) |
| A reverting proof is a claim so stash the one file | `memory/a-reverting-proof-is-a-claim-so-stash-the-one-file.md` |
| 7. Earn the red | `docs/STANDING_PRINCIPLES.md` |
| 19. Name the mutation before you write the gate | `docs/STANDING_PRINCIPLES.md` |
| Parallel work protocol (item 8: a finding's row, its probe and its fix are one job) | `memory/parallel-work-protocol.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "strike a ledger row drive its
probe and a guard test red on the base green on the head"`; re-run it rather than trusting this
list if the pack has been sitting. Of the retriever's four lines the guard-blind entry and the
reverting-proof note bear directly; the protocol only through item 8.

## Implementation

Every fix below is a **fix shape (untested)** unless marked driven; its refutation is named.
The pack prescribes shapes in prose and one fence tagged with the file it lands in.

**J-1 The base checkout** *(fix shape, untested; refuted by Task 0 item 4 on time, by item 3 on
the population)*. A helper beside `strike`, `_base_tree(root, ref) -> Path`: `<ref>` defaults to
`git merge-base HEAD origin/<base>` (the base as the ship driver names it, resolved as
`tools/cc/board.py::read_ledger_at_base` resolves its ref), and the tree is built through a temp
index inside a `tempfile.TemporaryDirectory(prefix="strike-base-", ignore_cleanup_errors=True)`:
`GIT_INDEX_FILE` pointed at a file in the scratch directory, `git read-tree <ref>`, then `git
checkout-index -a --prefix=<scratch>/tree/`. The clone's own index and worktrees are untouched,
and no `export-ignore` applies (`.gitattributes` marks `ESPALIER_MEMORY.md`,
`memory/session-log.d/`, `task-packs/Done/`, `Merged/` and `Scrapped/` and `RUNBOOK_*` that way,
which `git archive` would have dropped, differing at the base for a reason other than the fix).
A ref this clone does not hold, or a checkout that fails, is a refusal naming the ref. The
scratch root is outside the checkout, so no guard reads it as a live-tree write.

**J-2 The probe on both sides** *(fix shape, untested; refuted by Task 0 item 2)*. In `strike`,
after the row is found and before anything is queued: load the row's probe entry as `repin` does
(the probe file under `task-packs/probes.d/` by id, else the roster); when it has a command and
`--base` is given or defaulted, drive it twice through `check_ledger_probes.run_probe`, first
inside `with checker.rooted(scratch_tree, pristine=True):`, then inside `with
checker.rooted(root):` (J-5's context manager; never a bare `_ROOT` assignment, which would carry
the contamination memo from one tree into the other). The probe driven on both trees is the
HEAD's probe file (the row's current probe under `task-packs/probes.d/`), never one recovered
from the base. Required pair: `STILL_OPEN` at the base, `STRIKE_CANDIDATE` at the head. Each other pair is its own refusal sentence: "the probe
reads its open value at the head too (the defect is still there)"; "the probe did not read its
open value at the base (`<verdict>: <detail>`): the defect was not where the row says, or the
probe never read it; strike with `--no-base` to record that in the closing text"; "`UNRESOLVED`
at the base: `<detail>`". A probe the runner reports undrivable at the base (Scope (in) item 3)
is one printed line by default and a refusal under an explicit `--base`; the verdict decides,
never a word match on the command. `--no-base` skips the base drive and prints that the base was
not read, so a strike whose probe cannot run at the base is a recorded choice, not a silent default.

```python target=tools/cc/ledger_row.py
def _drive_both_sides(rid: str, *, root: Path, ledger: Path, probes: Path, base: str | None,
                      guards: tuple[str, ...]) -> str | None:
    """The refusal sentence when a side disagrees (J-2, J-3), else None."""


def strike(rid: str, *, ledger: Path, probes: Path, text_file: Path, day: str,
           anchor: str | None, dry_run: bool, despite_deferrals: bool = False,
           root: Path | None = None, base: str | None = None, guards: tuple[str, ...] = ()) -> int:
    ...
    if why := _half_struck(rid, line):
        print(f"ledger_row: {why}", file=sys.stderr)
        return 2
    sides = _drive_both_sides(rid, root=root or ledger.parent.parent, ledger=ledger, probes=probes,
                              base=base, guards=guards)
    if sides is not None:
        print(f"ledger_row: {sides}; nothing struck", file=sys.stderr)
        return 2
```

**J-3 The guard on both sides** *(fix shape, untested; refuted if the suite's conftest cannot
run against an overlaid base tree, which the replay in Task 0 item 2 drives with one guard)*.
For each `--guard <node id>`: run `python -m pytest <node id> -q -p no:cacheprovider
--junitxml=<scratch>/guard-head.xml` with cwd at the head (`root`); then copy the head's `tests/`
directory over the base scratch tree's `tests/` and run the same node there with cwd the scratch
tree, `PYTHONPATH` set to the scratch tree (prepended) so `espalier` resolves to the base tree's
own package (`tests/_engine_check.py::foreign_engine` asks a child where
`importlib.util.find_spec("espalier")` resolves and `::pytest_sessionstart` exits 4 when that is
not the tree's own `espalier/__init__.py`: on a seat with an editable install every base run would
otherwise exit 4), and `ESPALIER_BOX_LOCK` removed from the child's environment (the parent run
holds the box under `TP-703c`; a child waiting on it would hit the probe timeout). The junit
report gives the failure's exception type (the `-q` text is not parsed). Required
pair: exit 0 at the head; exit 1 at the base with a failure whose exception is not `ImportError`,
`AttributeError` or `NameError`, which prove only that the lane's symbol is new. Refusals, each
naming its reason: exit 2 (a collection error), 4 (a usage error, or the engine check) or 5 (no
test collected) at the base ("the guard does not collect on the base tree with this lane's
tests/: a helper the lane added outside tests/, a node id that does not exist, or the engine
check"); exit 1 at the base with one of the three exceptions. Each run is bounded by the probe
runner's timeout through `run_bounded`.

**J-5 The runner's `rooted` context manager** *(fix shape, untested; refuted if a caller of
`check_ledger_probes.main` depends on the four globals being rebound after the call, which its
`finally` already forbids)*. `tools/cc/check_ledger_probes.py::main` already swaps `_ROOT`,
`_PROBES`, `_LEDGER` and `_CONTAMINATION` for a `--root` call, resets the memo per tree and
restores all four in `finally`. That swap becomes `rooted(root, *, pristine=False)`, a context
manager the module exports and `main` calls, so the strike (and any later caller) roots the runner
without touching its globals. `pristine=True` records that the caller built the tree itself from
a ref and that it holds no generated duplicate: the contamination memo is an empty map for the
block instead of being derived by `git ls-files`, which in a plain directory takes the runner's
git-unavailable path and answers `UNRESOLVED` for every tree-walking probe (19 of the live
commands by `_TREE_WALK_MARKERS`). The subject and inputs gates are unchanged. One test in
`tests/test_check_ledger_probes.py` pins that the four globals are restored after the block and
that `pristine=True` passes a tree-walking probe on a directory with no repository; the vendored
copy follows by `python3 scripts/sync_vendor_cc.py`.

**J-4 The words** *(prose; lands with the lane)*. The module docstring's `strike` example gains
the two flags; `strike --help` says what each side must read; `memory/parallel-work-protocol.md`
item 8 gains: "A strike drives the row's probe at the base and at the head and runs the guard it
names on both (`ledger_row.py strike --base --guard`); a probe that cannot run at the base is
said in the closing text, never skipped silently."

**Earn the red, per fix.** `tests/test_ledger_row.py` gains a fixture beside `tree`: a scratch
repository with two commits, the base (the probe's subject unfixed, the guard red) and the head
(fixed, green), with `origin/<base>` pointing at the first. The mutations each new test must die
to:
- the base drive removed: a row whose probe already reads closed at the base is struck; the test
  asserts the refusal names the base;
- the head drive removed: a row whose probe still reads open at the head is struck; the test
  asserts the refusal;
- the guard run at the head only: a guard green on both sides passes; the test asserts the refusal
  names the base;
- the `tests/` overlay dropped, or `PYTHONPATH` not set on the base run: a guard new in the lane
  reads exit 4 or 5 at the base; the test asserts the refusal names the overlay or the engine
  check, not a red (the fixture's base tree carries an `espalier/__init__.py`, so a base run
  without `PYTHONPATH` on a seat with an editable install exits 4);
- the exception read dropped: a guard that fails at the base with `ImportError` is struck; the
  test asserts the refusal;
- the undrivable read dropped: a probe the runner reports undrivable at the base is refused with
  no `--base` given; the test asserts the strike proceeds without `--base` and refuses with it
  (the no-flag default's pin);
- the runner rooted by a bare `_ROOT` assignment instead of `rooted`: the base tree's
  contamination memo leaks into the head drive; the test asserts the head verdict is the head's;
- the base taken as `origin/<base>`'s tip instead of the merge-base: a fixture whose base branch
  gained the fix after the lane branched refuses a true strike; the test asserts the strike
  proceeds.
Each docstring names its mutation (`tests/CLAUDE.md` rule 1).

## Affected symbols

`/scope-check` keys on bare names; `strike` and `main` collide across the tree (the ledger's
strike verb is named in bodies and docs; every CLI has a `main`), so the gap list at authoring is
collisions, re-run at the lane's start. The runner's `main` changes too (its `--root` swap
becomes a call to `rooted`, J-5) and is not declared below for that reason.

### Changed-semantics
- `tools/cc/ledger_row.py::strike` (drives the probe on both sides and the guards before it writes; two new refusals)
- `tools/cc/ledger_row.py::_mint` (unchanged body; named because the parser it shares gains flags under `strike` only)

### Renamed
- None.

### Added-paths
- `tools/cc/ledger_row.py::_base_tree`
- `tools/cc/ledger_row.py::_drive_both_sides`
- `tools/cc/check_ledger_probes.py::rooted`

### Removed-paths
- None.

## Reach

Not a class pack: it closes no ledger class, strikes no row and mints none. `DEF-985` is named
under Motivation as the case the pack does not catch, so no later pass reads it as reached.

## Pass criteria

- `python3 tools/cc/ledger_row.py strike <id> --text-file <f> --base origin/main --guard
  <node>` on the two-commit fixture refuses on each of the mutations above and strikes on
  the fixed pair; the refusal writes neither the row nor the probe file
  (`test_a_refused_strike_writes_neither_file`'s shape, re-used).
- Without `--base` and without `--no-base`, a strike of a row whose probe cannot run at the base
  prints one line saying so and proceeds; with `--base` it refuses; one test pins the no-flag
  run.
- A base guard run without `PYTHONPATH` on a tree whose fixture carries `espalier/__init__.py`
  and whose seat has an editable engine install exits 4 and the strike refuses naming the engine
  check; with it, the run reaches the test. A guard child runs with `ESPALIER_BOX_LOCK` absent.
- `check_ledger_probes.rooted` restores `_ROOT`, `_PROBES`, `_LEDGER` and `_CONTAMINATION` after
  its block, and `pristine=True` lets a tree-walking probe run on a directory with no repository;
  no assertion in `tests/test_check_ledger_probes.py` is weakened.
- Task 0 item 2's three replays are recorded in Landing with their verdicts on each side.
- No existing assertion in `tests/test_ledger_row.py` or `tests/test_check_ledger_probes.py` is
  weakened and no fixture removed; `tests/test_vendor_cc_parity.py` green after
  `python3 scripts/sync_vendor_cc.py`.
- The tier the lane earns (`scripts/proof_tier.py --base origin/main`: a `tools/cc/` edit earns
  the full tier, `::is_runtime`'s full prefixes; the line decides, never this sentence) with its
  receipt in the pull request body.
- No criterion here licenses shipping a defect in the gate the pack delivers: a base drive that
  reads a missing subject as `STRIKE_CANDIDATE`, or a guard's collection error read as red, is a
  defect of this pack, not a scope-out.

## Files touched

**New:** none (the fixture and tests join `tests/test_ledger_row.py`).

**Modified:** `tools/cc/ledger_row.py`; `tools/cc/check_ledger_probes.py` (the `rooted` context
manager, J-5); `espalier/_vendor/cc/ledger_row.py` and `espalier/_vendor/cc/check_ledger_probes.py`
(by `scripts/sync_vendor_cc.py` only); `tests/test_ledger_row.py`;
`tests/test_check_ledger_probes.py`; `memory/parallel-work-protocol.md`.

**Deleted:** none.

**Unmodified on purpose:** `tools/cc/check_ledger_probes.py::run_probe` and its gates (the
runner is called through `rooted`, its verdicts unchanged; a defect found in it is filed
in-lane); `tools/cc/board.py::read_ledger_at_base` (the shape is copied for the ref, not shared:
the board archives a few paths and runs a child interpreter, the strike checks out the whole
tree and runs the runner in-process); `.gitattributes` (its `export-ignore` rows stand; the
checkout does not read them); `tests/_engine_check.py` (the base run satisfies it through
`PYTHONPATH`); `docs/PACK_AUTHORING.md` (its sentence on the Scope (out) refusal stands).

## Sub-task ordering

1. **Task 0 items 1, 3 and 4** (read-only; an hour), then **item 2**, the three replays, by
   hand with the recovered probe files. Checkpoint: the readings in this file's Landing; a
   refuting result re-scopes to the guard alone and re-raises.
2. **J-5** the runner's `rooted` context manager, red first against a leaked memo, then the
   vendor sync. Checkpoint: `pytest tests/test_check_ledger_probes.py tests/test_vendor_cc_parity.py -q`.
3. **J-1** the checkout helper and its test (the smallest change in the verb). Checkpoint:
   `pytest tests/test_ledger_row.py -q -k base_tree`.
4. **J-2** the probe on both sides, red first on the fixture against a strike that drives nothing.
5. **J-3** the guard on both sides, red first against a guard run at the head only, then against
   a base run without `PYTHONPATH`.
6. **J-4** the words, the vendor sync. Checkpoint: `python3 scripts/sync_vendor_cc.py` clean,
   `pytest tests/test_ledger_row.py tests/test_vendor_cc_parity.py -q`.
7. **Red-team** before the tier, as the tier's `review:` line names. What this pack most likely
   got wrong, for the pass to bite on: a probe whose `inputs` name a path the lane added, refused
   at the base where the honest reading is "not drivable"; the overlaid `tests/` importing a
   head-only module outside `tests/`; a Windows `checkout-index` failing on a long path;
   `PYTHONPATH` on the base run shadowing a module the overlaid `tests/` expects from the head.
8. **Landing** here.

## Estimated effort

Pack budgets on this repository have run about 2.7 times over on one measured pack (`TP-459`);
read these as the author's guess, not a schedule.

| Step | Build | Red-team and tier | Notes |
|---|---|---|---|
| Task 0 | 1.5 h | | three replays by hand |
| J-5 | 0.5 h | | one context manager in the runner, one test, the sync |
| J-1 | 0.5 h | | one helper, one test |
| J-2 | 1.5 h | | two drives, three refusals, its tests |
| J-3 | 1 h | | two runs, the overlay |
| J-4 | 0.5 h | | words and the sync |
| Review and tier | | 1 h plus the full tier | a `tools/cc/` edit |
| Total | 5.5 h | 1 h | expect the measured overrun |

## Landing
- State: DRAFT
- Commits:
- Suite: `python3 scripts/proof_tier.py --run --base origin/main` (the tier the line names)
- Earn-the-red: per fix, against the mutations named under Implementation
- Red-team: reasoning review at authoring (the reflect skill's checklist v1, failure-mode-reviewer,
  2026-10-18): REQUEST CHANGES on the set; this file's findings: Part 2 items 4, 6, 7, 15, 16, 21
  addressed (PYTHONPATH on the base guard and the fixture's package; the temp-index checkout and
  the runner's pristine-root argument, undrivable decided by the runner; the exception read and
  exit 2; the rooted context manager; the merge-base, the pinned default, the HEAD probe; the probe
  child's environment); checklist item 13 acknowledged. The executor still runs the reviewers the
  tier line names.
- Reach: not a class pack; no row closed
- Task 0: items 1 to 4 not yet run (item 1's reading at authoring: the strike drives nothing)
- Date: 2026-10-18 (authored, local)
