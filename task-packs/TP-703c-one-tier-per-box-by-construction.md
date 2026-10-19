# TP-703c — One tier per box, by construction: a kernel lock replaces the START and END notes

## Status

- Version target: self-host first. The plugin and its test live under `tests/`, which `espalier
  init` does not deploy; the deployed changes are a non-blocking sibling of
  `tools/cc/_json_safe.py::lock_file` (via `espalier/_vendor/cc/`) with its engine twin in
  `espalier/_atomic_io.py`, one variable `tools/cc/seat.py` sets, and one banner line. An
  adopter's box gets those and not the plugin (Scope out).
- Type: workflow infrastructure (a pytest plugin, a lock primitive, the launcher's environment)
  plus one protocol sentence that names a mechanism where the record held a conversation.
- **Kind: PACK.** One lane, `lane/one-tier-per-box`, suited to a `win` seat: the contention it
  removes is on that box, and Task 0's second item is driven where two seats share one clone.
- Parent: `TP-703` (`task-packs/TP-703-multi-seat-discipline.md`), Scope (in) item 2, Wave 1. The
  roadmap's own Task 0 item 2 (seat-on-seat wait minutes) can hold this child before it is
  assigned; it is restated here as Task 0 item 2.
- Authored 2026-10-18 (local; 2026-10-19 UTC) by the dispatcher seat `air` on the operator's word
  ("good, lets make task packs for fixing these issues"), from the fix analysis of the same
  evening: "One writer per shared state became a lock negotiated by mail on the win box."
- Ledger: no row filed at authoring (`memory/parallel-work-protocol.md` item 8: the finding, its
  probe and its fix are the assigned seat's one job). The lane files one in-lane if its Task 0
  finds a defect that needs its own oracle, and strikes nothing: no live row names this gap.
- Core Rule 14 is the rule this pack carries forward: "serialise only what cannot be isolated,
  and never enforce it by remembering to run things one at a time." Two tiers on an 8 GB box
  cannot be isolated, so a lock the kernel holds serialises them, not a note a seat remembers.

## Motivation

On the shared Windows box two seats, `win` and `win-2`, worktrees of one clone, ran one tier at a
time because two full tiers at once reached Claude Code's low-memory reaper. The operator's
standing word for a reap (a seat restarts with fewer workers, without asking; CI's full tier is
the proof) is recorded in `memory/session-log.d/2026-10-15-231832-air.md`; the caps themselves
live in each box's shell profile (`PYTEST_XDIST_AUTO_NUM_WORKERS`, root `CLAUDE.md`), read from
the box, never from a record (the `cc/GOAL.md` note this pack cited at authoring is gitignored
and was rewritten at the 10-18 handoff; corrected 2026-10-19). There was no serialisation rule:
the one-tier-at-a-time
protocol was the seats' own, improvised on 10-18 (`START` notes: 0 on 10-16, 2 on 10-17, 87 on
10-18). It was carried by mail: a seat sent a `START` note before its tier and an `END` note
after, and the other seat read the mail before starting. Measured on the mail record
(`python3 tools/cc/mail.py inbox --all --json`, every worker message, a whole-word match on the
text; re-derived 2026-10-18 from the dispatcher's saved copy of the same read):

- 240 worker messages on 2026-10-18; 87 mention `START`, 85 mention `END`. On 10-16 the count
  was 0 and on 10-17 it was 2: the protocol was improvised on 10-18 and consumed a third of the
  day's channel at once.
- 3 crossed starts and 4 corrections to the protocol itself on 10-18, read from the dispatcher's
  tick notes (unmeasured beyond the notes).
- 15 holds for test suites from the operator's other projects on the same box, at least five
  hours of box time, counted by the dispatcher from the seats' "box read first" lines
  (unmeasured beyond the notes). No mail protocol between seats can see those: the suites are
  not seats.

The protocol has no written home. `memory/parallel-work-protocol.md` does not mention it (a
grep for `START`, `END note`, `one tier at a time` and `box` finds only the two-seats-on-one-box
sentence and the launcher); `docs/WORKFLOW.md`'s "Parallel seats" section does not either. It
lived in assigns, in the seats' notes and in the dispatcher's context, which is the shape Core
Rule 14 names: serialisation enforced by remembering.

**Why a lock and not a better protocol.** A note is written before the thing it announces and
read by a reader that may be stale: a fetch that failed passed one seat's gate with exit 0 (the
failure-mode reviewer's finding on 10-18), and a seat killed by the reaper never sends `END`. A
kernel lock is taken by the process that runs the tier, waits exactly as long as the other run
holds it, and is released when the handle closes or the process dies; a killed seat whose pytest
tree survives as an orphan still holds it, which is a real run and is named on the line.
`tools/cc/_json_safe.py::lock_file` is already that primitive on both operating systems
(`fcntl.flock` on POSIX, `LockFileEx` on one byte on Windows); `tests/test_file_lock.py` drives it
across processes.

**The named user (§16).** Each `win` seat: the one that waited on a note that never came because
its sibling was reaped, the one that crossed a start on a stale fetch; the dispatcher that ruled
four times in a day on a protocol a tool should hold; and the operator, who read 87 messages of
box bookkeeping on the channel built for claims and asks.

## Scope (in)

1. **`tests/_box_lock.py`**, a pytest plugin object registered from
   `tests/conftest.py::pytest_configure` the way `tests/_never_ran.py::pytest_configure` and
   `tests/_timeout_backstop.py::pytest_configure` are (controller only: no `workerinput` on the
   config), active only when `ESPALIER_BOX_LOCK` names a path and the run will run tests
   (`tests/_never_ran.py::NO_TEST_RUNS` says which options do not). It builds its holder record
   (seat, lane, pid, started-at, the argv head) BEFORE it tries the lock, tries without blocking,
   writes the record the instant the lock is held, exports `ESPALIER_BOX_LOCK_HOLDER=<pid>` so
   every child inherits it, and at `pytest_unconfigure` truncates the record and closes the
   handle. While refused it polls, printing one stderr line per report interval with the holder
   and its age (past a ceiling, the command that kills the holder by pid), and appends one JSON
   line per wait to `<lock path>.log`, the record the roadmap's re-measure line 3 reads.
2. **A nested run passes through on the inherited pair**: when `ESPALIER_BOX_LOCK_HOLDER` names
   the record's pid and that pid is alive, the run is inside its parent's hold; a run that inherits
   neither variable has no plugin and is inside it by construction. The one shape that would
   deadlock, a child that keeps the path, loses the holder and loads `tests/conftest.py`, is pinned
   ABSENT by a census test over the pytest-spawning files (Task 0 item 3); no ancestry walk is built.
3. **`try_lock_file`**, a non-blocking sibling of `lock_file` in `tools/cc/_json_safe.py` and
   its twin `espalier/_atomic_io.py`, held equal by
   `tests/test_surface_contract.py::test_lock_file_two_copy_parity` (its name tuple widened).
4. **The launcher sets the variable.** `tools/cc/seat.py::child_env` adds `ESPALIER_BOX_LOCK`
   (a per-host path under the temp directory unless the environment already names one) and
   `::command_line` prints it in both shells' forms, so a seat launched by the tool or by its
   printed line runs under the lock and CI, which never runs the launcher, never sees it; the two
   variables join `docs/ENV_CATALOG.md` (read by `tests/test_catalog_self_consistency.py`) and its
   asset twin by `scripts/sync_asset_docs.py`.
5. **The release gate keeps it.** `scripts/fresh_clone_gate.py::ENV_WHITELIST` drops every
   `ESPALIER_` name today, so the gate's legs (about 25 minutes each) would run unlocked beside a
   seat's tier. The two lock names join the whitelist, and
   `tests/test_fresh_clone_gate.py::TestChildEnv::test_the_whitelist_names_no_carrier` names them
   as its exceptions with the reason (a lock carries nothing of the parent's state into the proof).
6. **The banner says when it is off.** Where `tools/cc/hooks/session_start.py::_sessions_line`
   names another live session in this clone and this session has no `ESPALIER_BOX_LOCK`, one more
   line, `Box lock: off (relaunch through seat.py launch, or export ESPALIER_BOX_LOCK=<path> before
   claude)`, so a seat relaunched by hand after a reap (`claude --continue`, the maintenance-mode
   form in the root `CLAUDE.md`) is told before its first tier. Reporter only, no spawn.
7. **The words.** One sentence in `memory/parallel-work-protocol.md` item 1 naming the lock as
   what serialises two seats' runs on one box, the holder line a waiter prints, and the rule that a
   tool running pytest as a probe inside a seat's own run (`TP-703j`'s guard drive among them)
   removes `ESPALIER_BOX_LOCK` from the child's environment; one sentence in `docs/WORKFLOW.md`'s
   "Parallel seats" and its asset twin by `scripts/sync_asset_docs.py`. Nothing is struck from
   either: neither carries the note protocol today.
8. **Files, for the pre-flight** (the same set as Files touched): `tests/_box_lock.py`, `tests/test_box_lock.py`,
   `tests/conftest.py`, `tools/cc/_json_safe.py`, `espalier/_atomic_io.py`, `tests/test_surface_contract.py`,
   `tools/cc/seat.py`, `tests/test_seat.py`, `scripts/fresh_clone_gate.py`, `tests/test_fresh_clone_gate.py`,
   `tools/cc/hooks/session_start.py`, `tests/test_session_banner.py`, `memory/parallel-work-protocol.md`,
   `docs/WORKFLOW.md`; by the syncs only, `espalier/_vendor/cc/_json_safe.py`, `espalier/_vendor/cc/seat.py`,
   `espalier/_vendor/cc/hooks/session_start.py`, `espalier/assets/docs/WORKFLOW.md`.

## Scope (out)

- **Foreign suites.** The lock serialises pytest runs that load this repository's `tests/`
  conftest; a suite from another project takes no lock, so the seat tick's "box read first" step
  stays and the roadmap's re-measure line 3 reports those minutes apart. The remedy is the
  operator's (one seat per box, a third machine, a VM), in `TP-703`'s Scope (out).
- **A hold across a whole tier.** `scripts/proof_tier.py::run_commands` runs several pytest
  lines in order; under this pack each line takes and releases the lock, so two tiers interleave
  line by line, fair and one run at a time. Whether a tier-level hold is wanted (interleaved tiers
  each take about twice the wall clock) is the re-measure's to say from the wait log; if so, a flag
  on the tier script takes the same lock and exports the same holder, in a later lane.
- **A free-memory admission floor.** A floor is admission, not mutual exclusion, with its own
  oracle, and it would refuse a run on a box whose other tenant is a foreign suite this pack
  cannot see. Not here.
- **The adopter form.** `tests/` is not deployed, so an adopter running seats gets the primitive
  and the variable and no plugin; a deployed form (a `tools/cc/` module the adopter's conftest
  registers, with the four roster homes `TP-702` 1-D names) is a later child if a second adopter
  box appears.
- **Two users on one Windows box.** The temp directory is per user there, so two seats under two
  accounts would not share the lock file; both `win` seats run under one. A declared limit, printed
  by the launcher when the path is under a per-user directory.

- **The operator's settled remedies as the fix.** Weighed, not taken: the worker caps (each
  box's `PYTEST_XDIST_AUTO_NUM_WORKERS`) bound one run's memory, not two runs' sum, so two capped tiers still meet
  the reaper; and "the contract slice locally, CI's full tier is the proof" makes the merge the
  first place a full-tier red is seen, the shape `TP-703a` exists to report. Both stay beside the lock.
- **Probe children of a seat's own run.** A tool that runs pytest inside a run that already holds
  the box (`TP-703j`'s guard drive, a mutation runner) must not take the lock again or it waits on
  its own parent past its timeout; Scope (in) item 7's sentence is the rule and that pack's J-3 is
  named to follow it. No code here: the child's environment is the caller's.

## Task 0 — Verify (try to kill this pack)

Each item names the oracle, the refuting result and the exit (stop and re-raise, never adjust).

1. *Oracle:* two pytest processes on a scratch test file, both with `ESPALIER_BOX_LOCK` naming
   one path, started one second apart; the second must print the holder's line while the first
   runs. Then the kill shapes, on the `win` box and on the Air: the holder's pytest tree killed
   (`taskkill /T /F` on Windows, `SIGKILL` on POSIX), the second proceeding within one poll
   interval; the holder's `claude` alone killed, its pytest tree left as an orphan (root
   `CLAUDE.md` "Reap first": children survive at PPID 1) and who holds the lock read after, since
   the orphan does; both under two concurrent xdist runs, five kills each, the release latency as a
   spread, since a release that depends on free resources is slowest on the starved box the lock
   exists for. *Refuting result:* the lock is not released when the holder's tree is killed on
   Windows (then the record's pid-alive check becomes the admission rule, with the window a dead
   holder keeps the box said), or `lock_file` cannot take the path from both worktrees of one
   clone. *Exit:* if neither OS releases on kill, stop: a lock a dead holder keeps is the note
   protocol with a worse failure mode. The orphan is not a refutation: it is a real run holding
   the box, and the holder line with its age and kill command is the remedy.
2. *Oracle:* the roadmap's item 2, on the mail record (`python3 tools/cc/mail.py inbox --all
   --json`): for 10-16 to 10-18, the minutes a `win` seat waited for the other's `END` note, dated
   only by notes that say "waiting" or "holding for" (an `END`-to-`START` gap is the hand-off, not
   the wait). *Refuting result:* under one hour a day. *Exit:* the lock buys little time; re-raise,
   since 87 messages a day is still the cost, and the operator decides whether that alone builds it.
3. *Oracle:* the census the contract test pins: over the test files that spawn pytest (`grep -l
   -E '"-m", "pytest"|"pytest",' tests/test_*.py`, 18 on 2026-10-18), each child environment read
   for the rule that matters: keeps `ESPALIER_BOX_LOCK`, loses `ESPALIER_BOX_LOCK_HOLDER`, loads
   `tests/conftest.py`. Read at authoring: `tests/test_write_guard.py` (`os.environ.copy()`),
   `tests/test_timeout_backstop.py` (minus `PYTEST_ADDOPTS`, its own conftest) and
   `tests/test_xdist_never_ran.py` (`_drive`, only its `conftest_text` loaded) keep both names or
   load no suite conftest; `ENV_WHITELIST` drops both (item 5 keeps both);
   `tests/test_node_adopter_defaults.py` drops three other `ESPALIER_` names. *Refuting result:* a
   child with the one shape. *Exit:* not a stop: its env builder carries the holder too, and the
   census test reds if a later one forgets. (The first draft answered this with a process-ancestry
   walk; the review found no child that needs it and a forged-holder rule indistinguishable from
   the environment-alone rule the pack forbids, so the census is the pin.)
4. *Oracle:* `tests/test_fresh_clone_gate.py::TestChildEnv::test_the_whitelist_names_no_carrier`
   and the gate's docstring on why it drops `ESPALIER_` names. *Refuting result:* the gate's design
   forbids any such passthrough for a stated reason (the proof must not inherit the parent's
   harness state). *Exit:* the gate's legs stay unlocked, the banner's off-note (item 6) is the one
   guard there, and Landing says so. (Read 2026-10-18: the test refuses the four prefixes and
   `VIRTUAL_ENV` with no reason beyond "no carrier"; a lock path carries nothing into the proof.)

## Relevant memory

Recent pattern, measured: the win box's protocol was corrected four times in one day by the
dispatcher and crossed three times, and every correction was a sentence. The incident that shapes
the lock, a seat killed by the reaper that never sent `END` (the dispatcher's notes; unmeasured
beyond them), is one a note protocol cannot close; the kernel closes it when the tree dies, and
names the orphan when it does not.

| Entry | Where |
|---|---|
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| Parallel work protocol | `memory/parallel-work-protocol.md` |
| The ledger verbs refuse a second writer, but their content rules red only after they write | `docs/SHARP_EDGES.md` (section of that title) |
| New Files Under `.espalier/` Need `surface_contract._LOCAL_ONLY_PATHS` Registration | `docs/SHARP_EDGES.md` (section of that title) |
| A state-file allowed-set must glob dynamic flag families | `docs/SHARP_EDGES.md` (section of that title) |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "two seats on one box run one
pytest tier at a time a lock on a shared file"`; re-run it rather than trusting this list if the
pack has been sitting. The retriever's first line was the protocol and the next three were the
ledger verbs' and the state-file entries, lexical neighbours; the first two rows above are the
ones that bear, and the third is the shape to copy for the holder record (a refusal that names
the other writer).

## Implementation

Every fix below is a **fix shape (untested)** unless marked driven; its refutation is named. Two
short fences, each tagged with the file it lands in; the rest is prose.

**C-1 The non-blocking primitive** *(fix shape, untested; refuted if `LockFileEx` with the
fail-immediately flag reports anything but the lock-violation error on a held byte, which Task 0
item 1 drives on the `win` box)*. In `tools/cc/_json_safe.py`, beside `lock_file`, a
`try_lock_file(fh, *, shared=False) -> bool` that returns False when another process holds the
lock and raises `OSError` where `lock_file` would: on POSIX `fcntl.flock` with `LOCK_NB` added,
`BlockingIOError` read as False; on Windows `_lock_byte` with the fail-immediately flag (the Win32
constant `LOCKFILE_FAIL_IMMEDIATELY`, 0x1, not in the tree today) and the lock-violation error
(33) read as False. `_lock_byte` gains that translation, so its body changes in both copies, and
`tests/test_surface_contract.py::test_lock_file_two_copy_parity` adds `try_lock_file` to its name
tuple and the two new constants to its constant tuple; `_LOCK_OFFSET_HIGH` is never changed (the
test's last assertion says why). `tests/test_file_lock.py::lock_primitive_sites` counts
`fcntl` spellings under `espalier/` and `tools/cc/`; the new function lives inside the one home it
allows.

```python target=tools/cc/_json_safe.py
def unlock_file(fh: IO[Any]) -> None:
    """Release :func:`lock_file`'s lock. Unlocking a file this process does not
    hold is a no-op, as ``flock(LOCK_UN)`` is."""


def try_lock_file(fh: IO[Any], *, shared: bool = False) -> bool:
    """:func:`lock_file` without the wait: True when the lock is now held,
    False when another process holds it. Raises where ``lock_file`` would."""
```

**C-2 The plugin** *(fix shape, untested; refuted by Task 0 item 1 if the lock does not release
on kill)*. `tests/_box_lock.py`, standard library and pytest only, loading `_json_safe` by path
as the suite's helpers do. `pytest_configure(config)`: return when `workerinput` is on the config,
when `ESPALIER_BOX_LOCK` is unset or empty, when any of `tests/_never_ran.py::NO_TEST_RUNS` is
set, or when the plugin is already registered; else register a `BoxLock` object. `BoxLock` first
builds its record as one JSON object (seat from `git config espalier.machine`, lane from `git
rev-parse --abbrev-ref HEAD`, both through `run_bounded` with a two-second cap and `?` on failure;
pid; started-at in UTC; the first eight argv words), then opens the path for read and write
(created if absent) and calls `try_lock_file`. While it returns False it reads the holder record:
if the record's pid equals this process's `ESPALIER_BOX_LOCK_HOLDER` and is alive (C-3), it passes
through holding nothing; an empty or unparsable record is `no holder record` on the line and the
wait goes on, never a pass; otherwise it sleeps the poll interval and, once per report interval,
writes one stderr line, `box lock: waiting on <seat> <lane> (pid N, held M min): <argv head>`,
which past the ceiling (`WAIT_CEILING_MIN = 60`, pre-registered above the post-merge proof's
measured worst case, 48.2 minutes over ten runs to 2026-10-16 in `.github/workflows/post-merge.yml`'s
comment) ends with the command that kills the holder by pid; the wait itself has no ceiling, since
a box with one slot must wait, and the line is the remedy. Once held it writes the prebuilt record,
flushes, sets `os.environ["ESPALIER_BOX_LOCK_HOLDER"] = str(os.getpid())` before any worker or
child is spawned (xdist spawns after configure), and appends one JSON line to `<lock path>.log`
for the wait it just ended (waiter seat and lane, holder seat, lane and pid, start and end); a run
that did not wait writes none. `pytest_unconfigure` truncates the record, then closes the handle,
so the next waiter never reads a finished holder's pid. A failure inside the plugin is one stderr
line and the run proceeds unlocked, named: a lock that cannot be taken must not cost a seat its
tier, and the line says the box is unguarded.

**C-3 The inherited pair** *(fix shape, untested; refuted by Task 0 item 3)*. `inside_holder(pid)
-> bool`: `os.environ.get("ESPALIER_BOX_LOCK_HOLDER") == str(pid)` and that pid alive (`os.kill(pid,
0)` on POSIX; `OpenProcess` through `ctypes` on Windows). Nothing else: a child that inherited the
variable is a child of the run that set it (xdist workers, the stage-one smoke's nested pytest,
`DEF-919`); one that did not is unlocked (no `ESPALIER_BOX_LOCK` either) or the shape Task 0 item
3's census pins absent. The census is a test in `tests/test_box_lock.py` over the pytest-spawning
files' `env=` expressions, so a scrubber that keeps one name and drops the other reds the suite.

**C-4 The launcher** *(fix shape, untested; refuted if `tests/test_seat.py`'s environment pins
cannot take one more key without weakening)*. `tools/cc/seat.py::child_env` sets
`ESPALIER_BOX_LOCK` to the inherited value when one is set, else to
`os.path.join(tempfile.gettempdir(), "espalier-box.lock")`; `::command_line` adds the same to
the POSIX `env` words and the PowerShell `$env:` lines; `cmd_launch` says, once, when the path is
under a per-user directory on Windows (Scope out). Pinned beside
`tests/test_seat.py::TestLaunch::test_the_childs_environment_drops_the_parent_sessions_and_names_the_seats_venv`
and `::test_the_command_line_is_quoted_for_each_shell` by new cases, never by loosening those.

```python target=tools/cc/seat.py
import tempfile

#: The box-wide lock file the suite's plugin takes (TP-703c): one path per
#: host, set by the launcher for every seat and never by CI.
BOX_LOCK_KEY = "ESPALIER_BOX_LOCK"
BOX_LOCK_NAME = "espalier-box.lock"


def child_env(target: Target, *, maintenance: bool, base: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in (os.environ if base is None else base).items() if k not in SESSION_ENV}
    # the maintenance switch and the seat's .venv, as today, then:
    env.setdefault(BOX_LOCK_KEY, os.path.join(tempfile.gettempdir(), BOX_LOCK_NAME))
    return env
```

**C-5 The gate and the banner** *(fix shape, untested; refuted by Task 0 item 4 for the gate)*.
`scripts/fresh_clone_gate.py::ENV_WHITELIST` gains the two lock names with a comment naming the
reason, and `tests/test_fresh_clone_gate.py::TestChildEnv::test_the_whitelist_names_no_carrier`
names them as its exceptions (a tuple beside the prefixes) so the next `ESPALIER_` name still
reds. In `tools/cc/hooks/session_start.py`, beside `_sessions_line`: when that line names another
live session in this clone and `ESPALIER_BOX_LOCK` is not in the environment, one more banner
line, `Box lock: off (relaunch through seat.py launch, or export ESPALIER_BOX_LOCK=<path> before
claude)`; reporter only, silent otherwise; pinned in `tests/test_session_banner.py` beside the
`Sessions:` tests with both polarities.

**C-6 The words** *(prose; lands with the lane)*. `memory/parallel-work-protocol.md` item 1
gains: "Two seats on one box run one pytest at a time by construction: the suite takes a lock on
the box's lock file (`ESPALIER_BOX_LOCK`, set by `seat.py launch`), waits while another run holds
it and prints the holder and its age; a note on the mail channel announces nothing; a tool that
runs pytest as a probe inside a run that holds the box removes the variable from the child's
environment." `docs/WORKFLOW.md` "Parallel seats" gains one sentence of the same content, carried
to `espalier/assets/docs/WORKFLOW.md` by `scripts/sync_asset_docs.py`. The registration in
`tests/conftest.py::pytest_configure` is one line; `_MARKER_RULES` classifies the new test file, and
the two rosters that list `test_file_lock` (a real process tree on every OS) list `test_box_lock`.

**Earn the red, per fix.** `tests/test_box_lock.py` reuses `tests/test_file_lock.py`'s shape
(`_child_env`, `_wait_for`, a locker child under `_CHILD_DEADLINE_S`), running real pytest
children on a scratch test file with `-p tests._box_lock` and `ESPALIER_BOX_LOCK` set. The
mutations each test must die to:
- the non-blocking try replaced by the blocking `lock_file`: the second child never prints the
  holder line while the first holds;
- the record written after the try, or not truncated at `pytest_unconfigure`: a waiter started in
  the window names no holder, and a third child names a finished run's pid;
- the pass-through taken on the variable alone: a grandchild given a dead holder's pid must wait;
- the census rule dropped: a seeded env builder that keeps `ESPALIER_BOX_LOCK` and drops
  `ESPALIER_BOX_LOCK_HOLDER` is not flagged;
- the wait log unwritten: a child that waited leaves `<lock path>.log` empty;
- the past-ceiling kill command left off the line at a stubbed clock past `WAIT_CEILING_MIN`;
- the whitelist's two names dropped: `fresh_clone_gate.child_env` returns no lock path from a
  parent that set one;
- the banner line printed while the variable is set, or while no other session is live.
Each test's docstring names its mutation (`tests/CLAUDE.md` rule 1).

## Affected symbols

`/scope-check` keys on bare names; `pytest_configure`, `child_env` and `main` collide across the
tree, so the gap list at authoring is collisions (and the catalog's asset twin); re-run it at the start.

### Changed-semantics
- `tools/cc/_json_safe.py::_lock_byte` (the fail-immediately flag read as False, not raised)
- `espalier/_atomic_io.py::_lock_byte` (the twin, held equal)
- `tests/test_surface_contract.py::test_lock_file_two_copy_parity` (one more name, two more constants)
- `tests/conftest.py::pytest_configure` (one more registration)
- `tools/cc/seat.py::child_env` (one more key)
- `tools/cc/seat.py::command_line` (the key in both shells' forms)
- `tools/cc/seat.py::cmd_launch` (the per-user-directory note)
- `scripts/fresh_clone_gate.py::ENV_WHITELIST` (the two lock names)
- `tests/test_fresh_clone_gate.py::TestChildEnv::test_the_whitelist_names_no_carrier` (two named exceptions)
- `tools/cc/hooks/session_start.py::_sessions_line` (the off-note beside it)

### Renamed
- None.

### Added-paths
- `tools/cc/_json_safe.py::try_lock_file`
- `espalier/_atomic_io.py::try_lock_file`
- `tests/_box_lock.py`
- `tests/test_box_lock.py`

### Removed-paths
- None.

## Reach

Not a class pack: it closes no ledger class, strikes no row and mints none. The protocol
sentence it adds replaces no recorded rule, because the note protocol was never recorded; the
roadmap's re-measure line 3 (`START` messages per day, 87 to 0; seat-on-seat waits) is the
figure that says it worked.

## Pass criteria

- With `ESPALIER_BOX_LOCK` set, two pytest controllers on one box never run tests at once; the
  waiter prints the holder and its age within one report interval; a killed holder tree frees the
  waiter within one poll interval on both OSes; an orphaned holder tree is named as the holder
  (Task 0 item 1 driven, the spreads in Landing).
- A nested pytest that inherits both variables passes through while the holder is alive and waits
  when its pid is dead; the census finds no child that keeps the path, loses the holder and loads
  the suite conftest; no pytest-spawning test deadlocks under the variable (the full tier run once
  with it set on the `win` box is the proof, in Landing).
- Every wait writes one JSON line to `<lock path>.log` and a run that did not wait writes none;
  the report line past the stubbed ceiling carries the kill command.
- Without the variable the plugin registers nothing and the suite is byte-for-byte unchanged (CI
  never sets it); the release gate's legs inherit it (`fresh_clone_gate.child_env` with a parent
  that set it returns it) and no other `ESPALIER_` name passes the whitelist; the banner prints
  `Box lock: off` only when another live session shares this clone and the variable is unset.
- `tests/test_surface_contract.py::test_lock_file_two_copy_parity` holds the widened tuples; no
  assertion in `tests/test_file_lock.py` is weakened and no sample removed; `_LOCK_OFFSET_HIGH`
  is unchanged.
- Earn-the-red recorded per fix against the mutations above; a test that only ever passed does
  not count.
- The two syncs report clean; the six touched test files green at one worker; the full tier with
  `--base origin/main` (a hook and a `tools/cc/` module changed) green with its receipt in the
  pull request body.
- No criterion here licenses shipping a defect in the gate the pack delivers: a lock a dead
  holder keeps, a pass-through on a dead holder's pid, a waiter that names a finished run, or a
  waiter that never names the holder is a defect of this pack, not a scope-out.

## Files touched

**New:** `tests/_box_lock.py`; `tests/test_box_lock.py`.

**Modified:** `tools/cc/_json_safe.py`; `espalier/_atomic_io.py`; `tests/test_surface_contract.py`;
`tests/conftest.py`; `tools/cc/seat.py`; `tests/test_seat.py`; `scripts/fresh_clone_gate.py`;
`tests/test_fresh_clone_gate.py`; `tools/cc/hooks/session_start.py`; `tests/test_session_banner.py`;
`memory/parallel-work-protocol.md`; `docs/WORKFLOW.md`; `docs/ENV_CATALOG.md`; the vendored twins
under `espalier/_vendor/cc/` (by `scripts/sync_vendor_cc.py` only) and the asset twins under
`espalier/assets/docs/` (by `scripts/sync_asset_docs.py` only).

**Deleted:** none.

**Unmodified on purpose:** `scripts/proof_tier.py` (Scope out: no tier-level hold);
`tests/test_file_lock.py` (read, not edited, unless `test_the_census_sees_every_spelling_it_claims`
reds on the new function, and then the census learns the spelling); `tools/cc/seat.py::WORKER_TICK`
(the operator's paste); the pytest-spawning test files (read by the census, changed only if Task 0
item 3 finds the one shape).

## Sub-task ordering

1. **Task 0 items 3 and 4** (read-only), then **item 1** on the `win` box with a throwaway
   primitive, then **item 2** on the mail record. Checkpoint: the four results in Landing; any
   refuting result stops here.
2. **C-1** the primitive in both copies and the parity test (the smallest change). Checkpoint:
   `pytest tests/test_surface_contract.py tests/test_file_lock.py -q`, the vendor sync.
3. **C-2** with **C-3** and the census test, `tests/test_box_lock.py` red first against a plugin
   that blocks (C-1 unused), one that writes its record after the try, and one whose census rule
   is dropped. Checkpoint: the new test file green on the Air and on the `win` box.
4. **C-4**, **C-5** and **C-6** with their pins and syncs. Checkpoint: `pytest tests/test_seat.py
   tests/test_fresh_clone_gate.py tests/test_session_banner.py -q`, `python3 scripts/sync_asset_docs.py`
   clean.
5. **Red-team** before the tier: both reviewers on a snapshot clone (a hook changed). What this
   pack most likely got wrong, for the pass to bite on: a Windows handle opened in a mode
   `LockFileEx` refuses; a record write that itself blocks on a full disk; the banner's off-note
   firing on a worktree seat beside the operator's own single session in the clone.
6. **The full tier**, once, with `ESPALIER_BOX_LOCK` set on the `win` box, so the eighteen
   pytest-spawning files run under the lock. Checkpoint: the receipt in the pull request body.
7. **Landing** here; the roadmap's line 3 window opens at the merge, read from `<lock path>.log`.

## Estimated effort

Pack budgets here have run about 2.7 times over on one measured pack (`TP-459`); a guess, not a schedule.

| Step | Build | Red-team and tier | Notes |
|---|---|---|---|
| Task 0 | 2 h | | two OSes, four kill shapes with spreads, one mail read, one census |
| C-1 | 1 h | | two copies, one parity tuple |
| C-2, C-3 | 2 to 3 h | | the plugin, the record's order, the log, the census test; eight mutations |
| C-4, C-5, C-6 | 1.5 h | | the launcher, the gate's whitelist, the banner line, three sentences |
| Review and tier | | 2 h plus the full tier | the tier run under the lock is itself a proof |
| Total | 6.5 to 7.5 h | 2 h | expect the measured overrun |

## Landing
- State: DRAFT
- Commits:
- Suite: `python3 scripts/proof_tier.py --run --base origin/main` (the full tier: a hook and a
  `tools/cc/` module changed)
- Earn-the-red: per fix, against the eight mutations named under Implementation
- Red-team: reasoning review at authoring (the reflect skill's checklist v1, failure-mode-reviewer,
  2026-10-18): REQUEST CHANGES on the set; this file's findings: Part 2 items 5, 8, 9, 11, 17, 18,
  21 and checklist items 4, 5, 8 addressed (the gate's whitelist and the banner's off-note; the
  ancestry walk dropped for the inherited-pair rule plus a census pin; the record written before
  the try and truncated at release; the orphan kill case and the holder-age line with its ceiling;
  the wait log; the GOAL quote corrected; the probe child's environment); checklist item 13
  acknowledged. The executor still runs both reviewers on a snapshot clone.
- Reach: not a class pack; no row closed
- Task 0: items 1 to 4 not yet run (item 3's authoring read is in the item; the test re-runs it)
- Date: 2026-10-18 (authored, local)
