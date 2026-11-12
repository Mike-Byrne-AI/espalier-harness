# TP-707 — The guard pays for what it judges: write_guard's cost per call, measured first, the cuts asked after

## Status

- Version target: the next minor after TP-706's release step.
- Type: instrument (a per-call cost census and a deterministic ratchet); performance (levers,
  each gated on the instrument's figure) only on the operator's later yes (ruling 1a). No
  verdict changes, in any wave.
- Kind: PACK
- State: DRAFT, authored by the dispatcher seat `air` on the operator's ruling of
  2026-11-10 ~19:55Z ("rule all as recommended": option B of the operator call
  `20261108T085409Z-air-d842df`, ack `20261110T195850Z-air-2c7fab`). Reported with three
  questions (operator call `20261110T203629Z-air-dcaa02`) after a fresh reviewer's
  changes were folded.
- **The report's rulings** (read 2026-11-12 04:05Z, ack `20261112T041026Z-air-8ecf8f`):
  - **1a: Wave 1 only.** Wave 1 (the instrument) is approved and assignable. Wave 2's three
    levers are not approved: they are asked again later as a plain friction question, with
    Wave 1's census figures. They stay below as the shapes that question would put.
  - **2b: the ratchet keeps its +10% line.** So it catches a #516-sized jump and not the
    smaller growths a draft of this pack claimed for it; 1-B and the Pass criteria say
    what it catches, by arithmetic.
  - **3a: timings under the box lock the tiers already take, and on Windows from one
    seat** (win and win-2 share a box). The load average is read and reported, never a
    gate.
- Binding rulings: `20261108T204346Z-air-40ec7f` (2026-11-08: no per-call weight for an
  unbounded list of spellings; protect the target), the coverage contract
  (`docs/HOOKS.md`, "The coverage contract for the jobs the parser keeps", 2026-10-08),
  and per-call cost at or under main's, measured, for every lane of this pack.
- Frame: the guard is a friction slip-catcher, not a security boundary
  (`docs/STANDING_PRINCIPLES.md` §2, "Toolbelt, not security boundary"). A lever that
  changes a verdict is refuted, not adjusted.

## Motivation

`write_guard.py` is wired on PreToolUse with matcher `*` and a 5 s timeout
(`espalier/harness_config.py::CANONICAL_HOOK_WIRING`), so every tool call starts a thin
parent and, since #519 (DEF-3048, closed 2026-11-07), a judging child under
`tools/cc/hooks/write_guard.py::HARD_DEADLINE_S` (4.0 s from the parent's first line).
DEF-946 (closed 2026-11-08) took the two pattern modules off a read-only call: a Read,
Grep, Glob or TodoWrite returns from `tools/cc/hooks/write_guard.py::_run_main` before
`::_load_the_pattern_path`. Every Bash, PowerShell, mutation and `mcp__` call still loads
the whole path.

**Measured in this draft** (the Air, Python 3.14.7, load averages 5.6 to 6.0 throughout:
high, so every figure below is indicative, not a baseline; the prototypes are in the
authoring session's scratchpad, `compile_census.py` and `call_census.py`, not landed):

- Per call, the checkout at 1b34b46, n=9 a kind, order shuffled, each call spawned as
  Claude Code spawns it (`python3 -B tools/cc/hooks/write_guard.py`, payload on stdin) in
  a temp project of its own: a bare interpreter start 26.3 ms median (IQR 25.3 to 28.7);
  a Read 126.7 ms (121.8 to 130.1); a Bash `ls -la` 327.6 ms (317.3 to 342.5); an MCP
  `read_file` 321.2 ms (312.3 to 331.1). All four allowed. So on this box the pattern path
  is about 200 ms of a 330 ms Bash call, and an MCP read pays what a Bash call pays.
- What the path compiles at 1b34b46 (every `re._compile` call recorded while
  `_bash_patterns`, `_speedbump` and `write_guard` import and the path's steps run): 301
  distinct patterns, 204,553 compiled characters. `_bash_patterns._CMD_POS_NO_VERB` is
  1,580 characters (`_CMD_POS` 1,665), and 61 of the 301 compiled patterns embed it:
  144,558 of the 204,553 characters (70.7%).
- The proxy, calibrated at two points (both from `git archive` of `tools/cc`, no bytecode
  cache, 3 rounds each): at caae022 (#516's head, closed unmerged 2026-11-08) the fragment
  is 4,301 characters, 387,144 characters compile, and the two modules import in 334.0 to
  340.8 ms and 73.5 to 78.8 ms, against 242.8 to 250.7 and 43.3 to 48.2 ms at 1b34b46.
  Compiled characters moved +89% and the import time +41%; the distinct-compile count
  moved the other way (291 against 301). So the compiled-character count tracks the cost
  and the compile count does not (two points, hypothesis for the slope: about 0.66 ms per
  1,000 compiled characters on this box).
- Real sessions: 0 records of `pretooluse_blocked_time_budget` or
  `pretooluse_failed_open_time_budget` in this box's audit logs for the main checkout and
  the `work` worktree (`~/.espalier/audit/espalier-harness-*.log` and `work-*.log`, 46
  files, 2026-10-11 to 2026-11-10). The Windows seats' logs are not on this box.

**Cited, not re-derived here:**

- #516's growth of the fragment (1,580 to 4,301 characters) cost +154.2 ms a call, paired,
  IQR +138 to +173, n=104 an arm, on the Windows box under a tier's load (win-2,
  `20261108T062036Z-win-2-f9801f`); DEF-3049's on top of it (4,301 to 6,506) +139.9 ms
  (`20261108T080105Z-win-2-eaf346`). **Neither is on main**: #516 closed unmerged and the
  slashed-arm lane was dropped under ruling 40ec7f. They are what a growth of the shared
  fragment costs, which is the ratchet's case, not today's cost.
- DEF-946's stub prototype: a Read call 244 to 87 ms cached, 326 to 120 with no cache,
  n=25 (air-work, `20261108T080916Z-air-work-929cb9`); its closure lists three optional
  items not done: lazy compilation inside the two modules, `compileall` at init and
  upgrade, and a re-measured `docs/HOOK_ASSUMPTIONS.md` snapshot.
- The thin parent: +40 to +67 ms a call on Windows 3.11.9, about +30 ms on the Air (the
  comment above `tools/cc/hooks/write_guard.py::HARD_DEADLINE_S`). A read-only allowlist
  in the parent, about 37 ms more off a call (air-work, 929cb9; unmeasured as a fix).
- The deadline in CI: #519's Windows and clean-checkout legs, 13 and 6 errors in one class
  fixture each (jobs 128643242129, 128643101750; `20261108T075429Z-air-1893cc`); #574's
  Windows leg 4 budget refusals and #575's 1 (run 42799398479,
  `test_hooks_as_wired::test_every_wired_entry_starts_and_answers_on_one_channel`), both the
  dispatcher's reads on 2026-11-10, run ids for #574 not re-read.

Who is hurt (§16): every harness user, on every Bash, PowerShell, mutation and MCP call,
about 0.2 s on the Air before any judging (direction measured, size indicative under
load), more on the Windows box; and a seat whose PR draws a slow Windows cell, where a test
that spawns the hook meets the 4 s deadline and reds with no defect of its own. That the
cost moves the deadline refusal rate in a user's real session is direction only: none is
recorded on this box.

## Scope (in)

1. **The instrument** (Wave 1): `scripts/guard_cost_census.py`, stdlib only, self-host.
   `--calls N`: per call kind (a bare interpreter start as the control, Read, Bash, an MCP
   read, an MCP write), N spawns each, shuffled, each in a temp project of its own, the
   median, IQR, min and max, the decision seen, the load average at the start and the end,
   the interpreter's version and HEAD. `--compile`: the compile proxy (distinct patterns,
   compiled characters, the fragment's length, the patterns and characters that embed it)
   from a fresh interpreter. `--import-time --rounds N`: the two pattern modules' import
   time in a fresh interpreter (Task 0's R3). `--at <sha>` runs any of them against `git
   archive <sha> tools/cc` in a temp folder. `--json`.
2. **The ratchet** (Wave 1): a test that reds when the pattern path's compiled characters,
   or the shared fragment's length, grow past a pinned ceiling, read from a fresh
   interpreter so an import elsewhere in the run cannot hide a growth.
3. **The Windows leg** (Wave 1): one Windows seat (win and win-2 share a box; ruling 3a)
   runs the census at main's head under the box lock, counts the two budget records in
   the audit logs of every checkout on that box, and sends the lines by mail naming this
   pack.
4. **The snapshot** (Wave 1): `docs/HOOK_ASSUMPTIONS.md`'s "Measured latency footprint"
   gains write_guard's per-kind figures from the census, dated, with the load, on both
   boxes (DEF-946's third optional item); its assets twin by the asset-doc sync.

**Not approved (ruling 1a): the levers, Wave 2.** Kept as the shapes the later friction
question would put, each its own lane and each gated on Wave 1's figure and on Task 0's
exits: 2-A compile on first use per pattern family (DEF-946's first optional item; an MCP
read first, since it pays a Bash call's cost); 2-B fewer compiles of the shared
command-position fragment; 2-C the thin parent's read-only allowlist. The files they would
touch: `tools/cc/hooks/write_guard.py`, `tools/cc/hooks/_speedbump.py`,
`tools/cc/hooks/_bash_patterns.py`, `tests/test_write_guard.py`, and the vendored copies by
sync. No lane builds one before the operator answers that question.

## Scope (out)

- **The deadline and the timeout.** `write_guard.py::HARD_DEADLINE_S`, `::JUDGMENT_BUDGET_S`,
  `::EXIT_BY_S` and the wired 5 s stay, and so does their order, pinned by
  `tests/test_write_guard_time_budget.py::TestTheBudgetSitsBelowTheWiring`. Cutting the
  cost buys headroom under them; moving them is another decision.
- **What the guard judges.** Every lever is verdict-neutral, proved on the bench and the
  guard suites. A spelling a lever happens to read differently is a refutation of that
  lever, never a row filed in-lane to excuse it.
- **A persistent judging process, a pattern cache on disk, or a third-party regex
  engine.** Each changes the hook's architecture or its standard-library-only floor, and a
  cache file is shared state across sessions (Core Rule 14). Not this pack.
- **`compileall` at init and upgrade** (DEF-946's second optional item). The census's
  `--at` runs read the no-cache figure; a lever only if Wave 1 shows an adopter tree runs
  without a bytecode cache, re-raised to the operator then.
- **Every other hook's cost.** `task-packs/Deferred/TP-321d-hook-profiler.md` is the
  all-hooks profiler and stays deferred; this pack is write_guard alone.
- **The tests that spawn the hook under a parallel tier.** A test fixture's own bound
  against the 4 s deadline is the test's, a row where one reds; this pack lowers what the
  hook spends, it does not re-time the fixtures.

## Task 0 — Verify

**The oracle.** On the Air and on one Windows seat (ruling 3a), each run holding the box
lock the tiers take (the file `$ESPALIER_BOX_LOCK` names, `tests/_box_lock.py`), so no
tier on that box runs beside it, at main's head, after 1-A lands the script. The load
average at the start and the end is printed beside every figure and quoted with it, never
a gate (ruling 3a chose the lock over waiting for a load under 2.0, which at the 6 to 13
read on 2026-11-10 may never come):

```bash
python3 scripts/guard_cost_census.py --calls 30 --json
python3 scripts/guard_cost_census.py --compile --json
python3 scripts/guard_cost_census.py --compile --at caae022 --json
python3 scripts/guard_cost_census.py --import-time --rounds 10 --json
python3 scripts/guard_cost_census.py --import-time --rounds 10 --at caae022 --json
```

`--import-time` times the two pattern modules' import in a fresh interpreter, N rounds, under
the box lock; it is R3's instrument. caae022 predates `write_guard._load_the_pattern_path`,
so an `--at` tree without it is read by importing the modules alone, and the output says so
rather than raising. caae022 is reachable only from a closed pull request's ref (`pr/516`),
so fetch it first (`git fetch origin pull/516/head`).

And on each box, the real-session count: the two event types,
`pretooluse_blocked_time_budget` and `pretooluse_failed_open_time_budget`, in
`~/.espalier/audit/<slug>-*.log` for each slug the box's checkouts write (the checkout
folder's name, `tools/cc/hooks/_integrity.py::audit_path`; on the Windows box, win's and
win-2's both).

**The refuting results.** R3 gates Wave 1's ratchet. R1 and R2 gate nothing in Wave 1:
they are the figures the later friction question on Wave 2 carries (ruling 1a).

- R1, the levers. If on both boxes the Bash and the MCP-read medians sit within 25% of the
  Read median, the pattern path is under a quarter of the call and the levers buy too
  little for their risk: the friction question says so. (This draft read 2.6 times, under
  load, n=9.)
- R2, the deadline premise. If neither box's audit logs hold a real-session budget record, the
  deadline case is CI-only, and the friction question is per-call friction alone. (This
  draft found 0 on the Air.)
- R3, the proxy. If at n=10 per point the import-time difference between main and caae022
  sits inside either point's IQR, compiled characters do not track the cost on that box and
  the ratchet pins the wrong quantity: 1-B is not built as written.

**The exit.** On R3, stop 1-B and re-raise to the operator with the census lines; 1-A, 1-C
and 1-D still land, since the instrument and the snapshot are what the friction question
reads. R1 and R2 are reported in Landing and carried to that question, never acted on in
Wave 1.

**What was already driven.** The two prototypes and the audit-log count in Motivation,
under load; neither prototype is the script this pack lands. The first thing 1-A proves is
that its `--compile` line reads this draft's 301, 204,553, 1,580 and 61 at 1b34b46, and its
`--at caae022` line 4,301 and 387,144.

## Relevant memory

What has been biting lately: the figures this pack's call was filed on measured two
growths that never merged (#516, and DEF-3049's lane), and the last two cost changes on
this surface each moved a behavior beside the cost: DEF-946 turned a broken pattern module
from a failure to start into a crash a mutation meets, and #519's child moved the start-up
inside a 4 s deadline. Budget the red-team for what the lever moves besides milliseconds.

| Entry | Where |
|---|---|
| The measuring instrument is a claim too | `docs/sharp-edges/the-measuring-instrument-is-a-claim-too.md` |
| Re-measure a calibration's premise when its key changes | `memory/re-measure-a-calibrations-premise-when-its-key-changes.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| Hook authoring | `memory/hook-authoring.md` |
| ReDoS budget receipt | `docs/SHARP_EDGES.md` :: ReDoS budget receipt |

Resolved at authoring time (2026-11-10) by hand: `python3 tools/cc/hooks/_recall.py
"write_guard cost per call import time"` and `"regex compile cost guard hook latency"`
surfaced no cost entry, so the list is from
`ls docs/sharp-edges memory | grep -iE 'measur|budget|one-writer'` and the hooks folder's
`CLAUDE.md`. Re-run them rather than trusting this list if the pack has been sitting.

## Implementation

### 1-A — The census script *(the instrument; its own test is the proof)*

`scripts/guard_cost_census.py`, stdlib only, beside the other censuses in `scripts/`.
Each spawn gets a temp project of its own (`CLAUDE_PROJECT_DIR` and the payload's `cwd`),
`ESPALIER_MAINTENANCE_MODE` and every `CLAUDE_*` variable popped, so no state lands in
the checkout and no session's markers are touched (Core Rule 14: the census runs beside
seats' tiers on one box). The control is a bare `python -B -c pass` on the same
interpreter, so a reader nets the interpreter's start out. The MCP write kind uses a write
verb with a path inside the temp project, so the zone layer allows it and the bump is the
only nudge (read the decision; a nudge is reported, not counted as a different cost).
`--compile` records every `re._compile` call while the modules import and
`write_guard._load_the_pattern_path` runs, in a fresh interpreter.

`--calls` holds the box lock for its spawns (ruling 3a). Before the first spawn it takes
the lock on the file `$ESPALIER_BOX_LOCK` names, through the primitive the tiers' plugin
uses (`tools/cc/_json_safe.py::try_lock_file`, loaded by path as `scripts/host_check.py`
does). `tests/_box_lock.py` imports pytest at its top, so the stdlib-only census writes its
own holder record, with keys pinned by a test to `tests/_box_lock.py::build_record`'s, so a
tier that waits behind it names the census. It does what that module's docstring says a
holder does: it reads the old default path as the new one (`::current_path`), stamps
`started` when it takes the lock, honours `ESPALIER_BOX_LOCK_WAIT_S` with that module's exit
status, appends its outcome line to `<lock path>.log` (TP-703's re-measure sums `waited_s`
from it), and clears its record on release. While a tier holds the lock it waits and says
who holds it. **Inside a holder it passes through:** `ESPALIER_BOX_LOCK_HOLDER` equals the
pid in the lock file's record and that pid is alive (`tests/_box_lock.py::inside_holder`).
Otherwise the census's own test, spawned under the tier that holds the lock, would wait on
its own tier (the lock is per open handle, so a child cannot take it). With the variable
unset it runs, and its output says `unguarded` beside every figure. `--compile` takes no
lock, since it counts and does not time; `--import-time` takes it.

Its test, `tests/test_guard_cost_census.py`: the statistics on fixed inputs (median and
IQR of known lists); `--compile` on a fixture hooks folder of two tiny modules whose
counts are known; one real `--calls 1` row per kind against the checkout's guard, asserting
the decision only, never a time; a `--calls 1` run against a fixture lock another process
holds waits and names that holder; and one inside the holder pair passes through.

### 1-B — The ratchet *(fix shape, untested — refuted by Task 0's R3)*

`tests/test_guard_compile_ratchet.py` runs the census's `--compile` in a fresh interpreter
and asserts two ceilings, named constants beside a dated comment: the pattern path's
compiled characters, and `_bash_patterns._CMD_POS_NO_VERB`'s length. Each ceiling is
Task 0's figure at main's head plus 10% (ruling 2b), rounded up to a thousand characters for
the first and fifty for the second. The failure message names the census command and the
rule (a growth owes a measured per-call figure at or under main's, or the operator's word),
and a floor beside it reds where the census reads no pattern at all, so a loader that
silently loads nothing cannot pass. A lever that lands moves the ceilings down in its own
lane.

**What +10% catches, by arithmetic** at this draft's 1b34b46 figures (Task 0 re-derives
them at main's head, and Landing restates this paragraph with them). The ceilings would be
226,000 compiled characters (204,553 plus 10% is 225,008) and a 1,750-character fragment
(1,580 plus 10% is 1,738).

- **Caught:** a #516-sized jump. caae022's fragment is 4,301 characters and its path
  compiles 387,144, each well past its ceiling. So is the smallest growth past either
  ceiling: the fragment past 1,750 characters (+171), or 21,448 more compiled characters.
- **Not caught:**
  - one 100-character alternation added to the fragment, which is 1,680 characters and,
    across the 65 copies the 61 embedding patterns hold (58 hold one, 2 hold two, 1 holds
    three), +6,500 compiled characters (+3.2%). A second such alternation reds, since
    the fragment is then 1,780;
  - a second copy of the fragment in one pattern, +1,580 compiled characters (+0.8%).
    Thirteen such copies pass, and the fourteenth reds (+22,120).

  An earlier draft claimed the ratchet reds on both; it does not, and ruling 2b kept the
  line knowing that (8ecf8f). Every figure here was re-derived by a fresh reviewer at
  authoring, by `git archive` of each commit and a wrapped `re._compile`.

### 1-C — The Windows leg

One Windows seat (ruling 3a; the dispatcher names which in the assign) runs the oracle at
main's head under the box lock (`python`, or `py -3`, per the root `CLAUDE.md`'s
interpreter rule) and the audit-log count for every checkout on its box, and sends the
lines as one note naming TP-707. No code.

### 1-D — The snapshot

Add write_guard's per-kind rows to `docs/HOOK_ASSUMPTIONS.md`'s "Measured latency
footprint", dated, with each box's load and interpreter, beside the July snapshot (left as
the record it is); `python3 scripts/sync_asset_docs.py` for the assets twin.

### 2-A — Compile on first use per family *(fix shape, untested — refuted if the MCP read's
census median does not fall toward the Read median, or if any verdict moves)*

Today every `mcp__` call reaches `::_load_the_pattern_path` in `::_run_main`, and
`_speedbump` imports `_bash_patterns` whole, so an MCP read compiles the Bash and PowerShell
families it never reads. The shape: each family compiles where its first reader asks
(the PowerShell walls on a PowerShell call, the Bash walls on a Bash call, the MCP bump's
patterns on an MCP call), behind one lock as the path is today. First step: list, by the
source, which names an MCP judgment actually reads; if it reads `_bash_patterns` names
through `_speedbump`, the split is that read, not the files. Gate: the targeted kind's
median falls at least 10% at n=30 an arm, paired, on both boxes, and no other kind rises.

### 2-B — Fewer compiles of the shared fragment *(fix shape, untested — refuted if any
verdict moves on the bench or the guard suites)*

61 compiled patterns embed the 1,580-character fragment, 70.7% of the path's compiled
characters (this draft, 1b34b46). The shape: match the command position once per command
and run each verb pattern from the positions it yields, so the fragment compiles once. This
is the riskiest lever (lookbehinds and alternations that read across the position may not
survive the split), so its first sub-step is a census of the 61 by how each uses the
fragment, before any edit. `tests/test_write_guard.py::test_every_command_position_verb_regex_excludes_an_assignment`
floors the family that holds `_CMD_POS`; a lever that changes how the family is built
re-expresses that guard over the new shape, never loosens it.

### 2-C — The thin parent's read-only allowlist *(fix shape, untested — refuted if a
kill-switch or secret-path deny no longer fires on a read-only call)*

`::_answer_from_a_judging_child` spawns the child for every call. For a read-only tool the
child runs only the kill-switch scan and `::check_secret_path_access`; answering those in
the parent skips one interpreter start and the child's imports (about 37 ms on the Air,
929cb9, unmeasured as a fix). The deny paths must still fire unloaded, as
`tests/test_write_guard.py::TestThePatternPath` pins for the child today, and the parent
then holds a regex judgment outside the deadline's kill, which is the question this lever's
Task 0 must answer first: is the secret-path read bounded so it cannot outrun 4 s.

## Affected symbols

### Changed-semantics
- `tools/cc/hooks/write_guard.py::_load_the_pattern_path`
- `tools/cc/hooks/write_guard.py::_run_main`
- `tools/cc/hooks/write_guard.py::_answer_from_a_judging_child`
- `tools/cc/hooks/_bash_patterns.py::_CMD_POS`
- `tools/cc/hooks/_bash_patterns.py::_CMD_POS_NO_VERB`

### Renamed
- None.

### Added-paths
- `scripts/guard_cost_census.py`
- `tests/test_guard_cost_census.py`
- `tests/test_guard_compile_ratchet.py`

### Removed-paths
- None.

## Reach

This pack claims no ledger class and closes no row. DEF-946 is closed; of its three
optional items this pack carries two (lazy compilation, 2-A; the snapshot, 1-D) and leaves
`compileall` out (Scope out). DEF-3048 is closed and its deadline is kept. No live row names
the per-call cost. R1 and R2 are recorded in Landing with their figures for the friction
question (ruling 1a), and a row is filed only where the dispatcher or the operator asks for
one.

## Pass criteria

- No assertion is weakened and no fixture removed in
  `tests/test_write_guard_time_budget.py`, `tests/test_write_guard.py::TestThePatternPath`,
  `tests/test_redos.py` or the guard's polarity files; one that strengthens is welcome.
- 1-A: `--compile` at 1b34b46 reads 301, 204,553, 1,580 and 61, and `--at caae022` reads
  4,301 and 387,144, or Landing says why the method's figure differs; the census test green.
- 1-A: a census run behind a held box lock waits and names its holder; inside the holder
  pair it passes through (the census test's two rows).
- 1-B: green at main. The ceiling check is a pure function, tested on synthetic figures,
  not on a mutated tree (main's path already compiles 206,005 characters at f6d2b1f, 1,452
past 1b34b46, so a hard-coded
  mutation drifts with every guard lane): red one character past each ceiling, green at
  it and one under it; red at caae022's figures held as fixed data (4,301 and 387,144;
  CI has no ref to caae022); red when the loader is made to load nothing. Landing records
  each red, and the 100-character alternation and the second copy as growths that pass
  (ruling 2b).
- Each lever, if the friction question approves one (ruling 1a): `python3
  bench/run_benchmark.py --quiet` exits 0 at base and head; the guard
  suites green; the census's paired figure at n=30 an arm on the Air and on one Windows
  seat, each under the box lock, in the PR body with the load; every kind at or under
  main's; the ratchet's
  ceilings moved down in the same lane; the tier the diff earns
  (`python3 scripts/proof_tier.py --base origin/main`, the full tier for a hook change).

## Files touched

- New: `scripts/guard_cost_census.py`, `tests/test_guard_cost_census.py`,
  `tests/test_guard_compile_ratchet.py`, a `changelog.d/` fragment per lane.
- Modified, Wave 1: `tests/conftest.py` (`_MARKER_RULES` rows for the two new test files;
  both spawn, so `tests/test_test_suite_contract.py` runs in the targeted set),
  `tests/_surface_expected.py::EXPECTED_SCRIPT_NAMES` (the new script, or
  `test_test_suite_contract` reds),
  `docs/HOOK_ASSUMPTIONS.md` and `espalier/assets/docs/HOOK_ASSUMPTIONS.md` by the sync.
- Modified, Wave 2, by lever: `tools/cc/hooks/write_guard.py`, `tools/cc/hooks/_speedbump.py`,
  `tools/cc/hooks/_bash_patterns.py`, their `espalier/_vendor/cc/` copies by
  `scripts/sync_vendor_cc.py`, `tests/test_write_guard.py` (each lever's rows), the
  ratchet's ceilings, and `docs/HOOK_ASSUMPTIONS.md` with its twin by the sync where a
  lever changes what that section says loads.
- Unmodified on purpose: `write_guard.py::HARD_DEADLINE_S`, `::JUDGMENT_BUDGET_S`,
  `::EXIT_BY_S`, `espalier/harness_config.py::CANONICAL_HOOK_WIRING`, `docs/HOOKS.md`'s
  coverage contract.

## Sub-task ordering

1. **0-A Task 0** — after 1-A's script lands on the Wave 1 lane: the oracle on both boxes,
   the audit-log counts, the mail round trip. Checkpoint: the lines in Landing and R1 to R3
   read.
2. **1-A The census script and its test** — the smallest change. Checkpoint
   `pytest tests/test_guard_cost_census.py`, with the test's real rows stripping
   `ESPALIER_BOX_LOCK` and `ESPALIER_BOX_LOCK_HOLDER` (a run without `-n` exports no
   holder, so on a seat the census would take the box lock and wait, unbounded, behind
   another seat's tier); the lock rows use a fixture lock file of their own.
3. **1-B The ratchet** (built only if R3 holds) — checkpoint its reds and greens (Pass criteria).
4. **1-C, 1-D The Windows leg and the snapshot** — checkpoint the asset-doc sync and the
   contract slice. Wave 1 ships as one lane.
5. **The friction question** (ruling 1a) — after Wave 1 lands, the dispatcher puts Wave 2
   to the operator as a plain friction question with the census's figures and R1 and R2.
   Then **2-A, then 2-B, then 2-C**, each its own lane, only on the operator's yes to that
   lever; checkpoint each lever's gate.
6. **Red-team, per approved lever** — the `adversarial` skill over the hook diff, with the likeliest
   error named: a lever that moves a verdict on a spelling no row pins (2-B), a family
   loaded late on a reader the AST contract does not see (2-A), a parent-side read that
   outruns the deadline's kill (2-C). Ask for the mutation that survives.
7. **Verification** — the tier, `/handoff`, Landing.

## Estimated effort

| Sub-task | Budget |
|---|---|
| 0-A Task 0 (two boxes, one seat on each, the mail round trip) | 1.5 h |
| 1-A census script + test | 2 h |
| 1-B ratchet + its reds | 1 h |
| 1-C, 1-D Windows leg + snapshot | 1 h |
| 2-A per-family first use | 4 h |
| 2-B the shared fragment (census of the 61 first) | 6 h |
| 2-C the parent's allowlist | 2 h |
| Red-team, per lever (three) | 3 h |
| Verification (the full tier, per lane) | 2 h |
| **Total** | **22.5 h** (Wave 1 alone 5.5 h; Wave 2's 17 h only on the operator's yes, ruling 1a) |

## Landing
- State: DRAFT (ruled 2026-11-12, ack `20261112T160700Z-air-421d04` on request `20261112T155757Z-air-work-38081f`: the pack outlives Wave 1, since Sub-task ordering step 5 puts Wave 2 to the operator after Wave 1 lands; its pack-table row stays live)
- Wave 1 (the instrument; ruling 1a):
  - 1-A: LANDED 2026-11-12 (#605, b3eefcf, seat air-work). The first proof, read at a `git archive` of each commit: `--compile` at 1b34b46 reads 298 patterns, 204,539 characters, the 1,580-character fragment and 61 embedding patterns (144,558 characters), and at caae022 4,301 and 387,130. The draft's 301, 204,553 and 387,144 are the census's own figures on an interpreter whose startup had not imported `glob` and `fnmatch` (a plain 3.14.7 reads them again at 1b34b46 and caae022): those modules' import-time compiles (`([*?[])` as str and as bytes, and `([&~|])`: 3 patterns, 14 characters) are reached through a hook frame there, where a venv's `.pth` files import them before the recorder starts. An earlier reading of this line gave the draft run's own input as the cause; it was not.
  - Task 0 on the Air, 2026-11-12 at b3eefcf, Python 3.14.7 (the checkout's venv), the box lock taken for every timed line, the 1-minute load average 4.69 to 4.56 over `--calls` and 4.56 to 4.60 over `--import-time`. `--calls 30`, medians in ms (IQR): control 34.6 (32.4 to 36.6), Read 132.0 (126.1 to 138.9), Bash `ls -la` 303.2 (297.1 to 313.5), MCP read 302.9 (297.8 to 308.4), MCP write 300.1 (294.3 to 317.9); all 150 calls allowed. `--compile`: 308 patterns, 206,695 characters (207,211 on 3.11: the standard library's compiles a hook frame reaches move by interpreter and by what its startup imported first), the fragment 1,580, 61 embedding patterns holding 65 copies. `--at caae022`: 288 patterns, 387,130 characters, the fragment 4,301. `--import-time --rounds 10`: 180.3 ms (171.2 to 182.1) at b3eefcf, 282.9 (276.3 to 289.2) at caae022.
    - R3 HOLDS on the Air: 102.7 ms apart, outside both IQRs, so 1-B is built.
    - R1, the Air's half: the Bash and MCP-read medians are 2.30 and 2.29 times the Read median, well past 25%; the pattern path is about 170 ms of a 300 ms call. Carried to the friction question; acts on nothing in Wave 1.
    - R2, the Air's half: no record of either budget event in 47 daily audit logs (the main checkout and `work`), 2026-10-13 to 2026-11-12. Carried to the friction question.
  - Task 0 on Windows (1-C), win's note `20261112T171637Z-win-a5a5ce`: Windows 11, Python 3.11.9 (the main checkout's venv), at 43d8879, the box lock held for L1, L4 and L5; no load average on Windows, the CPU's busy share 0.13 to 0.17 beside each line; other work on the box during the run. `--calls 30`, medians in ms (IQR): control 37.9 (36.7 to 40.5), Read 174.7 (166.7 to 188.2), Bash 423.8 (417.1 to 440.6), MCP read 422.4 (416.5 to 431.5), MCP write 420.7 (416.3 to 440.0); every decision as expected, 0 budget records. Four modules read a stale cache (main had just fast-forwarded): the census adds `-B` and the wiring does not, so the row may overstate a warm live call. `--compile`: 319 patterns, 207,203 characters, the fragment 1,580, 61 embedding; `--at caae022` 299, 387,638, 4,301. `--import-time --rounds 10`: 202.5 ms (195.6 to 203.9) at 43d8879, 337.8 (329.7 to 350.1) at caae022.
    - R3 HOLDS on Windows: 135.3 ms apart, outside both IQRs.
    - R1, the Windows half: the Bash and MCP-read medians are 2.43 and 2.42 times the Read median; the pattern path is about 250 ms of a 420 ms call.
    - R2, the Windows half: 5 `pretooluse_blocked_time_budget` records in the 30 days to 2026-11-12, all on 2026-10-14 (1 under the main checkout's slug, 4 under win-2's worktree), and 0 fail-open records. Carried to the friction question.
  - 1-B: BUILT on `lane/the-guard-cost-snapshot`. `tests/test_guard_compile_ratchet.py` holds the figure inside a band cut from its `PINNED` reading (b3eefcf, 3.14.7 venv, Task 0's `--calls 30` as the per-call figure), the limits derived from it: ceilings of 228,000 compiled characters (206,695 plus 10% is 227,365) and 1,750 for the fragment (1,738), and floors of 186,000 and 1,400 (less 10%, rounded down), so a lower figure moves the band down in its own lane. It also reds where the reader read no pattern; where the loader compiled none of its own, read by the census's new `loader_patterns` (8 patterns, 8,997 characters at b3eefcf: the imports compile 95.6%, so a stubbed loader on the real tree sat inside the ceiling, and "red when the loader is made to load nothing" now holds of the loader itself); where no pattern read embeds the fragment; and where a cached first-use compile appears beyond `_bash_patterns._carrier_fed_remove_re` (an AST read of the three pattern modules), since the count is the imports and the loader alone. Its integration `_MARKER_RULES` row and its `TestSecurityMarkerCoverage` exemption. 1-B's arithmetic restated at b3eefcf: caught, caae022 (both ceilings, and its missing loader) and the smallest growth past either, 21,306 compiled characters or the fragment past 1,750 (+171). Not caught (ruling 2b): one 100-character alternation (the fragment 1,680; 65 copies, +6,500 compiled characters, +3.1%), though a second reds on the fragment (1,780); and a second copy of the fragment in one pattern (+1,580, +0.8%), thirteen passing and the fourteenth red (+22,120).
  - 1-D: both boxes' rows BUILT on the same lane, in `docs/HOOK_ASSUMPTIONS.md` ("write_guard, per call kind (2026-11-12 snapshot)", under a heading that now reads "dated snapshots", since it holds two) and its assets twin by the sync (265 of the 266 seeded hits).
  - Left for Wave 2: the compile reader counts the imports and the loader, so 2-A, which moves families to first use, owes the reader a judged call per family or a re-pin that says what left the count; 2-B, which restructures the fragment, owes the fragment limits a re-target, since `scripts/guard_cost_census.py::COMPILE_CHILD` reads `_CMD_POS_NO_VERB` by name. Whether each re-pin's +10% is the intended escalator is the operator's (ruling 2b); the ratchet's RULE re-pins at the new figure plus 10% against a named per-call figure.
- Commits:
- Suite:
- Earn-the-red: the first build, 13 mutations of the check and its shared reader, each killed (the loader, no-pattern and fragment-found checks dropped; `>` to `>=` on each ceiling; each ceiling raised a step and each dropped; the characters read as 0; the live row reading its scratch; the reader dropping the breaches or reading the checkout for its root), and caae022's archive driven red three ways. The fix batch, 26 mutations on a scratch copy of the ratchet, the census and `tools/cc`, each restored with `cmp`, all killed with the control green (24 passed): the band's ten (the loader-share, embedding and both floor checks dropped; each floor's `<` to `<=`; the floor at -20%; the ceiling at +20%; the pinned figure moved; an empty `per_call`), the six first-build checks again, the shared reader never raising or reading the checkout, the first-use reader's four (the called decorator form alone, no compile test, the pinned set widened, one module read), and the census's four (the loader share never taken, taken as everything, its characters read as 0, its snapshot taken after the loader).
- Red-team: on a snapshot clone of the first build, `code-reviewer` (named by `scripts/proof_tier.py` for `tests/conftest.py`) APPROVE-WITH-NOTES, 0 BLOCKER, 4 SHOULD, 10 NIT, and `failure-mode-reviewer` (discretionary) APPROVE-WITH-NOTES, 3 MAJOR gaps, 4 rough edges, 0 regressions. One fix batch took every SHOULD and MAJOR: the loader's share as a census key, so the floor holds of the loader rather than a rewording of its claim; the 1-A cause above; "never reached", naming both edges; this Landing's reds; the floors and the synthetic trees' import-time bulk (two census refactors had read 10,770 characters with every row green); the count's boundary, the first-use pin and the embedding floor; `PINNED` with its provenance and the re-pin spelled in RULE. Of the rest it took N1 to N5 and N7 to N10, the merge-skew sentence, the interpreter in the live row's failure, `COMPILE_CHILD` named in the breach texts, the doc's past tense and its `-B` claim (the census docstring's too), and the slow-exempt count; it declined N6 (a commit id on the public repository resolves) and the direct-caller count (a census change for its own lane, as the reviewer says).
- Reach: no row closed or filed (see Reach); R1 and R2 above are the friction question's, not rows.
- Date:
