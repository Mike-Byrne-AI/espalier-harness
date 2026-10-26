# TP-703i — The suite has a platform axis: the stand-ins the seats improvised become cells of the axis registry

## Status

- Version target: self-host only. Everything here lives under `tests/`, which `espalier init`
  does not deploy; nothing under `tools/cc/` or `espalier/` changes.
- Type: test infrastructure (one new helper module, one axis in an existing registry, two
  existing tests parametrised).
- **Kind: PACK.** One lane, `lane/platform-stand-ins`. Parent: `TP-703`
  (`task-packs/TP-703-multi-seat-discipline.md`, Wave 3, item 9), whose roadmap Task 0 does not
  gate this child; this file's Task 0 is a census and it decides the roster, or ends the pack.
- Authored 2026-10-18 (local) by the dispatcher seat `air` on the operator's word ("good, lets
  make task packs for fixing these issues"), from the lessons reviewer's unification U3 in the
  `/reflect` of the same day.
- **The sibling store, read first.** `tests/_axis_registry.py` (the adopter-axes registry,
  `DEF-975`) already lists the dimensions the suite runs the harness along, as `AXES`
  (`stack`, `host`, `session`, `root`, `tree`) and `AXIS_REGISTRY` cells, each proven by a node
  parametrised over its axis or declaring its gap, with a dated `PROVEN_FLOOR` that only rises,
  and `tests/test_axis_registry.py` as its contract. Its `host` axis is the interpreter-name
  shapes of `tests/_interpreter_hosts.py` and nothing else (the module says so). The operating
  system a test behaves as is not an axis there. This pack adds that axis to the registry it
  belongs in and builds no `tests/_platform_axis.py`
  (`memory/grep-for-a-sibling-store-before-building-a-rival.md`).
- **The registry's own pack.** `tests/_axis_registry.py` landed with `TP-468`
  (`task-packs/TP-468-adopter-axes.md`, `Kind: PACK`, `State: DRAFT`, its foundation lane landed
  2026-10-06), whose later waves prove the `host`, `session`, `root` and `tree` cells. This pack
  adds the `os` axis under that registry's rules and raises its floor by what it proves; it
  takes none of `TP-468`'s waves and changes none of its cells, and `TP-468`'s Status gets one
  sentence naming the `os` axis as this pack's, so two packs never edit one cell.
- Boundary with `TP-703h`: an expectation (a red the suite expects on a host) is that pack's
  table; a stand-in (a test that runs the harness AS another host, on this one) is a proving
  node here. Boundary with `TP-703b` Wave 1: `DEF-5024`'s contract pins that every `SIGALRM`
  arming function guards itself; this pack pins that the test which takes the alarm away runs
  on every cell as the `windows` cell's proof.
- Ledger: no row filed at authoring. `DEF-975` is the registry's own row and this pack extends
  the registry; the pack's claim about what the stand-ins would have prevented is a reading of
  their docstrings, tagged below.
- **Execution read (2026-10-25 local, seat `air-work`, `main` at 78c16510; the 0-A code-reviewer
  returned REQUEST CHANGES, no BLOCK).** Figures re-derived: nine platform-patch sites in **six**
  files, not five (`tests/test_bounded_spawn.py`, `tests/test_spawn_chokepoint.py`,
  `tests/test_demo_end_to_end.py`, `tests/test_final_release_matrix.py`, `tests/test_write_guard.py`,
  `tests/test_redos.py`), plus the `core.ignorecase` toggle; the pack's own `skipif|xfail` command
  prints **76** platform-conditional marks, not 80; `_emulate_windows_paths` has **15** call sites,
  not 16; the alarm test deletes its three names in **one** `for` loop (`tests/test_redos.py:2785-2786`),
  not three lines. Two claims were wrong, not stale: `_load_copy` loads the `tools/cc` copy under a
  fresh module name for module identity, not to re-make an import-time platform read -- every
  platform read the bounded-spawn tests drive is at call time (`tools/cc/_json_safe.py:358`, the
  one in `run_bounded`; lines 255, 268 and 281 are the lock helpers'; `espalier/_spawn.py:73`;
  `espalier/scanners/freshness.py:78`), so no proving node
  reloads and I-2's `reload` parameter is not built; and Task 0 item 5's oracle reads blind until
  **two** cells are proven (`blind_axes`: fewer than two proven values), so with one proven value the
  `os` line says every proving test ran at that value. New since authoring and excluded from the
  census by name: the two `sys.platform` patches in `tests/test_test_suite_contract.py` (lines 4143
  and 4455, `TP-703b` Wave 3) drive the roster predicate of
  `tests/conftest.py::PLATFORM_EXPECTED_FAILURES`, `TP-703h`'s population, not a stand-in. No read
  of `darwin` exists under `tools/cc/` or `espalier/`, and the one Mac-differing read is
  `platform.system()` in `tools/cc/hooks/_hook_utils.py::host_orientation_line`, from `uname`, which no
  `sys.platform` patch reaches (the dispatcher's read): no stand-in can make the harness do anything
  as macOS that it does not do as `linux`, so the `macos` cell is a declared gap with that reason.
  The decisions the review opened are under *Cross-pack coordination* and *Decisions at execution*.

## Motivation

**The census, measured 2026-10-18 on `main` at 397799c.** Deriving command:
`grep -nE 'delattr\(signal|setattr\((sys, "platform"|os, "name")|core\.ignorecase|StandInPopen|_emulate_windows_paths' tests/*.py`,
plus `tests/_interpreter_hosts.py::SHAPES`. What it finds, each a fixture the suite uses to make
the harness read another host on this one:

- `tests/test_redos.py::test_the_walker_and_ps_body_timers_skip_on_a_host_without_sigalrm`
  deletes `SIGALRM`, `setitimer` and `ITIMER_REAL` from `signal` with `monkeypatch.delattr`
  (the one `delattr(signal` site) so the two timers' Windows branch runs on every host. It merged
  with #320 (`lane/walker-rows-skip-without-the-alarm`, 2026-10-18 17:10 local, `git log -1
  9c4ca09d`), after #313's twelve Windows reds on the same file (`DEF-5024`'s row). Its own
  docstring says a dropped guard "reds on any cell that runs this file": the claim that it would
  have caught #313 on a Linux cell is that docstring's, hypothesised, not driven against #313's
  tree.
- `tests/test_write_guard.py::_emulate_windows_paths` sets `os.name` to `nt` with a Windows home
  (4 `setattr(os, "name"` sites in the file, 16 call sites of the helper) so the hook normalisers
  run with Windows path semantics on POSIX. It needed a companion,
  `tests/_report_os_name_guard.py`, after one red emulated row became a session
  `INTERNALERROR` on 3.10 and 3.11 (that module's docstring, the pre-cut review's D2,
  2026-09-20): a stand-in that patches process-global state meets every other reader of it.
- `tests/test_bounded_spawn.py::TestEveryCopysWindowsBranch` drives each copy's Windows branch
  "on every OS with a stand-in `Popen` and the platform read as `win32` (the required cells are
  Linux)", loading the `tools/cc` copy by path under a fresh module name (`_load_copy`; the two
  `espalier` copies import plainly) for module identity, not for an import-time platform read:
  every platform read `run_bounded` makes is at call time (corrected 2026-10-25).
  `tests/test_spawn_chokepoint.py` carries the same `win32` read for its sibling.
- `tests/test_init_gitignore_default.py::test_case_folding_follows_the_adopters_repo_not_the_scratch_dir`
  sets `core.ignorecase` both ways in a scratch repository: the case-folding half of a
  case-insensitive host, pinned "so the test is portable" (its docstring).
- `tests/test_final_release_matrix.py` parametrises `_venv_python` over `platform`;
  `tests/test_demo_end_to_end.py` reads the relaunch hint as `win32`. Nine `sys.platform` or
  `os.name` monkeypatch sites in five files in all.
- `tests/_interpreter_hosts.py::SHAPES` (`store_python3`, `launcher_only`, `python3_only`): the
  interpreter-name hosts, built from stubbed PATHs through `tests/_stubs.py::write_stub`. These
  are already the `host` axis's three cells, all declared gaps.

Not a stand-in, and not counted: the 80 platform-conditional `skipif` marks over `tests/`
(`grep -nE 'pytest\.mark\.(skipif|xfail)' tests/*.py tests/_*.py | grep -E 'platform|os\.name|win32|darwin|linux|SIGALRM|fcntl|msvcrt'`),
which skip a test on the other host rather than run as it. Not built: a PowerShell 5.1 alias
host (`DEF-4029`'s `sc`, the Set-Content alias 7.x dropped) and a git-version host (Apple Git
2.39's `update-index --unresolve` exit, which `TP-703h` carries as an expectation instead).

**The pattern.** Each stand-in that simulates an operating system was written after the merge
it would have prevented, by the seat that read the red: the alarm one after #313, the path one
after the Windows guard reds of 2026-09 (its companion's docstring dates the abort to the pre-cut
review). None is registered anywhere as "the suite runs the harness as Windows here", so a reader
asking which Windows behaviours the required Linux cells prove has to grep for them, and a new
stand-in has no roster to join. One limit the stand-ins cannot cross is measured too: five
modules under `tools/cc/` read the platform at import into a constant
(`grep -nE '^[A-Za-z_]+ *= *.*sys\.platform ==' tools/cc/*.py tools/cc/hooks/*.py`: the
`_REPLACE_ATTEMPTS` line in `_paths.py`, `cognitive_blueprint.py`, `generate_ledger_regions.py`,
`execution_plan.py` and `hooks/_hook_utils.py`), which a `sys.platform` patch after import does
not reach; `test_bounded_spawn.py`'s reload by path is the shape that does.

**The named user (§16).** A Windows adopter whose red arrives on a non-required leg 66 to 81
minutes after the merge (`TP-703`'s table), which `TP-703a` will report and this axis can prevent
on the required cells where the behaviour is simulable; and a seat on a Mac that cannot see
Windows and has no list of what the suite sees for it.

## Scope (in)

1. **The `os` axis** in `tests/_axis_registry.py`: `AXES` gains `os`; `AXIS_REGISTRY` gains
   three cells, `(os, linux)`, `(os, macos)`, `(os, windows)`, each proven by a node parametrised
   over `os` or declaring its gap; `PROVEN_FLOOR` rises in the change that proves a cell, with
   its dated line, as the file's comment block prescribes; `task-packs/TP-468-adopter-axes.md`'s
   Status gets the one sentence naming the axis as this pack's.
2. **One shared stand-in**, `tests/_platform_standin.py` (new): `as_os(monkeypatch, value)`,
   which sets `sys.platform` and `os.name` together for the value, deletes the `signal` names
   Windows lacks for `windows` (only in a module under pytest-timeout's thread method, which it
   checks through the module's `pytestmark`, refusing otherwise: under the signal method the
   cancel reads `signal.SIGALRM` while it is gone and the session ends in an `INTERNALERROR`,
   `tests/test_redos.py`'s comment and `DEF-5024`'s row), and reloads a named module by path when
   the caller asks (the `_load_copy` shape), returning what it set. The existing stand-ins keep
   their bodies and call it for the platform half, one caller at a time (expand); nothing is
   removed (no contract step in this pack). *Corrected at execution (2026-10-25, the dispatcher's
   ruling on request `20261026T034822Z-air-work-2234dc`): `as_os(monkeypatch, value, *,
   os_name=False)` sets `sys.platform` and returns it, `os.name` opt-in; the alarm deletion is
   `without_the_alarm(monkeypatch)`, a function `as_os` never calls, and the thread-method rule's
   one home is the suite contract, so there is no runtime refusal; no `reload`.*
3. **Proving nodes**: the alarm test (`tests/test_redos.py`) and the bounded-spawn Windows
   branch (`tests/test_bounded_spawn.py`) parametrised over `os`, so the `windows` cell is proven by tests that already run on every cell, as the
   *(As built, 2026-10-25: one node in the bounded-spawn file proves both `linux` and `windows`; the
   alarm test calls the stand-in's alarm half and carries no axis parameter, Decisions at execution,
   items 3 and 6.)*
   Node-defaults session test proved the `stack` cells (the registry's comment block). `linux`
   and `macos` are proven where a test varies along them (the release matrix's `_venv_python`
   parametrisation is the candidate), else declared gaps with their reason.
4. **The contract**: no new rule for the cells, since `tests/test_axis_registry.py`'s
   `TestEveryCellIsWellFormed` and `TestProvenCellsVaryRunAndPass` already hold every axis to
   the parameter rule, the mark rule and the floor; one new test, that every `os`-proving node
   collects and is not skipped on the Linux cell, since a Linux cell proving Windows is the point.
5. **The budget**, pre-registered: the `os`-proving nodes together under 60 seconds per CI cell
   (unmeasured at authoring), read from the post-merge run's `--durations=25`.

## Scope (out)

- **A `--platform-axis` selection in `scripts/proof_tier.py`.** The proving nodes are ordinary
  tests in files every tier already runs; a flag would be a second selection rule beside the
  tier's, and `TIERS` is one home. Re-raised only if the budget line fails.
- **A PowerShell 5.1 alias host.** `DEF-4029`'s lane (shelved after a platform safety stop;
  resumes on `win`); a stand-in for the 5.1 alias table is that lane's to build if it wants one.
- **A git-version stand-in.** The Air is that host; `TP-703h` registers the expectation.
- **Turning capability skips into stand-ins.** A `skipif` on POSIX symlinks or an `sh` stub is
  a premise that does not hold on the other host, not a behaviour to simulate.
- **Behaviours the kernel decides.** `LockFileEx` on one byte (`tools/cc/_json_safe.py::lock_file`),
  `PATHEXT` resolution, a grandchild holding a pipe past `subprocess.run`'s timeout
  (`docs/SHARP_EDGES.md`, the section of that title): no stand-in on Linux proves them, and the
  `windows` cell's row says so in its gap text for those surfaces. The Windows leg (`TP-703b`)
  stays their home.
- **`tests/_report_os_name_guard.py`.** It stays as it is; the shared stand-in routes `os.name`
  through what it already protects.

## Cross-pack coordination

Written at execution (2026-10-25, `air-work`); the authoring text above predates `TP-703b` Wave 1
and Wave 3.

- **`TP-703b` Wave 1 (landed; `tests/test_test_suite_contract.py::_sigalrm_offenders`).** A unit
  that deletes a name pytest-timeout's signal method reads is an arming unit, and a test module
  that imports an arming function by name must carry
  `pytestmark = pytest.mark.timeout(method="thread")`; a `tests/_*.py` helper is asked for no
  mark, its importers are. So the stand-in keeps the alarm deletion in a module-level function of
  its own, `without_the_alarm`, never inside `as_os`: `tests/test_bounded_spawn.py` imports
  `as_os` alone and needs no mark (`TP-703b`'s sentence that this pack adds one there is
  superseded by the split, which spares a file of real-timeout cases a change of timeout method),
  and `tests/test_redos.py` imports `without_the_alarm` and already carries it. That contract is
  the rule's one home: the runtime `pytestmark` check I-2 prescribed is not built (two homes for
  one rule), and the red is earned against the static one (the mark removed on a snapshot copy
  names the import).
- **`TP-703b` Wave 3 (landed; `tests/conftest.py::PLATFORM_EXPECTED_FAILURES`).** An expectation
  table, `TP-703h`'s ground; its predicate tests patch `sys.platform` and are excluded from this
  pack's census by name (Status).
- **`TP-703h`.** Reads `AXIS_REGISTRY` and `tests/test_axis_registry.py::collected_items`, edits
  neither file; order-neutral with this pack.
- **`TP-468`.** `State: DRAFT`, no wave live on the board at execution; this pack raises
  `PROVEN_FLOOR` by the two cells it proves (6 to 8) and `TP-468`'s Status names the `os` axis as
  this pack's; a later wave there raises the floor from where this pack left it.

## Decisions at execution

Request `20261026T034822Z-air-work-2234dc` to the dispatcher carried each with its citation;
proceeded on the recommendations at 04:03Z (2026-10-26 UTC) with no answer, the protocol's
fifteen minutes. The dispatcher's ack (`20261026T040933Z-air-116ca9`, 04:09Z) confirmed all six
with conditions, folded here, in the Status bullet and in the code; its note (`...-aa83de`) named
the pack corrections above and the census below.

1. `as_os(monkeypatch, value, *, os_name=False)` sets `sys.platform` and returns it; `os.name` is
   opt-in, because a bare `Path(...)` under `nt` raises on 3.10 and 3.11
   (`tests/_report_os_name_guard.py` covers report formation only) and neither proving node reads
   it. No `reload` parameter (Status).
2. The alarm deletion is `without_the_alarm(monkeypatch)`, a second function (Cross-pack
   coordination); no runtime thread-method refusal.
3. Two cells proven, not one, both by a new node in
   `tests/test_bounded_spawn.py::TestEveryCopysWindowsBranch`,
   `test_the_timeout_shape_follows_the_platform_the_harness_reads`, parametrised over `os` in
   (`linux`, `windows`): read as Windows every copy ends the tree, drains and reaps at the
   timeout; read as Linux the call is `subprocess.run`'s and the child alone is killed, on
   whatever host runs it, since the stand-in `Popen` is a context manager the standard library's
   `run` holds, and `run` itself stays in place (the dispatcher's trap: `_is_stdlib_run` sends a
   replaced `run` down the run branch at both values). The alarm test carries no axis parameter:
   its timers are the suite's own, skip on `hasattr(signal, "SIGALRM")` and read no platform, so
   a parameter there would never vary anything, the born-blind shape with a parameter on it (both
   reviewers' finding, driven: as `linux` with the alarm gone both legs still skip; the
   recommendation had named it the `windows` proof); it calls `without_the_alarm` alone.
   `os/macos` stays a gap (Status). The axis is not blind. The census by one command over
   every spelling of a platform patch, bare and through a module alias
   (`grep -nE '(setattr|patch\.object)\(([A-Za-z_][A-Za-z_0-9]*\.)*(sys|os), "(platform|name)"' tests/*.py`):
   20 sites in 10 files, 9 of them through an alias in 5 files (`mm.sys`, `cli.sys`,
   `_maintenance_mode.sys`, `hu.os`, `mod.os`), `tests/test_hook_utils.py:1283`'s tmp-reader test
   among them, a stand-in by this pack's definition; the roster stays at the two proving nodes,
   and the chokepoint's `win32` read is routed through `as_os` in this lane (the one expand step
   taken; the rest are a later lane's).
4. I-4 is a collection-time refusal of `skipif` on an `os` cell's node (`_REFUSING_MARKS_BY_AXIS`
   in `tests/test_axis_registry.py`, read by the existing `refusal`), with planted rows for the
   refusal and for its scope; the run-time check stays
   `test_every_proven_node_runs_and_passes_here`'s.
5. `PROVEN_FLOOR` 6 to 8, dated.
6. **The axis is named `target_os`, not `os`** (request `20261026T042549Z-air-work-5bd2e5`, the
   failure-mode review's finding): the registry names a proving node's parameter after its axis, so
   `os` would shadow the module inside every proving function, where `hasattr(os, "geteuid")` (the
   suite's root check, 22 sites) or `getattr(os, "name", "posix")` reads False or the default
   silently and no selected lint rule sees it (probed on the clone). Every `os` axis, cell and
   parameter in the authoring text above reads as `target_os`; the values (`linux`, `macos`,
   `windows`) and the ids are unchanged. The dispatcher's ruling (`20261026T043446Z-air-9a0be0`):
   the name, and the class fixed with it (Core Rule 12) -- `tests/_axis_registry.py::stdlib_shadowing`
   and a well-formedness rule that no axis is named for a module in `sys.stdlib_module_names`, the
   interpreter's own list (3.10 and later), with a planted axis named `os` as the earned red; the
   alarm test stays named in the registry's comment as the Windows-alarm behaviour's home; the
   platform pin's allowed site is cited path::symbol
   (`tools/cc/hooks/_hook_utils.py::host_orientation_line`), never by line.
7. From the two reviews on the snapshot clone (code-reviewer and failure-mode-reviewer, both
   REQUEST CHANGES, no BLOCK), folded in one batch: a proving function must be collected at two or
   more values of its axis (`tests/test_axis_registry.py::refusal`, every axis; a one-value
   parametrisation passed the parameter rule and never varied); `as_os`'s `os_name` is keyword-only
   with no default, so each call writes down which half it simulates; the bounded-spawn node loads
   the three copies before it fakes the platform (an import under the fake platform is cached for
   the session); two pins in `tests/test_axis_registry.py` hold the cells on every host -- no
   proving node is on `tests/conftest.py::PLATFORM_EXPECTED_FAILURES` for any host, and every
   `sys.platform` or `os.name` comparison under `tools/cc/` and `espalier/` is to `win32` or
   `nt`/`posix` with the one `platform.system()` site allowed by name, so the `macos` gap text
   cannot go stale silently; the chokepoint's `win32` read routed through `as_os`. Not this lane's:
   `tests/test_test_suite_contract.py::_sigalrm_offenders` does not follow a helper that only
   re-exports `without_the_alarm` (by name or `import *`), so that helper's importers are not asked
   for the thread method; `DEF-4035`'s class (an import shape the follow misses), widened by the
   dispatcher; the probe's command and result are a note on the lane, and the helper's docstring
   names the blind spot.

## Task 0 — Verify (the census decides the roster; it can end the pack)

Each item names the oracle, the result that ends the pack, and the exit, which is stop and
re-raise to the dispatcher, never adjust and continue.

1. *Oracle:* the census grep in Motivation, re-run at execution, each hit read: does it make the
   harness run AS another operating system (a stand-in), or skip on one (a capability skip)?
   *Refuting result:* fewer than three members that run as another host. *Exit:* an axis is
   premature; the members stay where they are and the pack is held. (Authoring read: five
   operating-system stand-ins across six files, plus the three interpreter hosts the `host` axis
   already holds.)
2. *Oracle:* can a node be parametrised over `os` and vary along it under the registry's rule:
   `tests/test_axis_registry.py::collected_items` over the two candidate nodes after
   parametrisation, reading each item's callspec for an `os` parameter and no `skip` or `xfail`
   mark. *Refuting result:* the module under test reads the platform at import (the five
   `_REPLACE_ATTEMPTS` sites, or another the grep shows) and the stand-in cannot reach it without
   a reload. *Exit:* not a stop: the stand-in reloads by path (`test_bounded_spawn.py::_load_copy`),
   and the pack says which modules need it.
3. *Oracle:* `grep -n 'pytestmark' tests/test_redos.py tests/test_bounded_spawn.py` against
   `tests/test_test_suite_contract.py::test_pyproject_leaves_the_timeout_method_to_the_platform`
   and `::test_every_module_that_arms_sigalrm_declares_the_thread_method`. *Refuting result:* a
   candidate module runs under the signal method. *Exit:* `as_os("windows")` refuses there (its
   check), and that module cannot prove the `windows` cell; another candidate or a declared gap.
4. *Oracle:* `pytest --durations=0 <the os-proving nodes>` on this box, three runs, the spread
   reported. *Refuting result:* over 60 seconds. *Exit:* fewer proving nodes, or the heavier one
   moves to the serial leg; the budget line is not loosened.
5. *Oracle:* `python3 tests/_axis_registry.py` before and after: the `os` axis prints as blind
   until a cell is proven ("fewer than two proven values is a blind axis", the module's rule).
   *Refuting result:* the table cannot say so for a new axis. *Exit:* the table's rule is the
   defect, fixed in-lane before the cells land.

## Relevant memory

Recent pattern, measured: both operating-system stand-ins that touch process-global state
(`os.name`, the `signal` table) broke the session the first time, not the test: the path one
with an `INTERNALERROR` at report formation on 3.10 and 3.11, the alarm one with the
timeout-cancel read the docstring warns of. The shared stand-in exists to carry those two lessons
so a third author does not relearn them.

| Entry | Where |
|---|---|
| Grep for a sibling store before building a rival | `memory/grep-for-a-sibling-store-before-building-a-rival.md` |
| A gate can be blind along a whole dimension | `memory/a-gate-can-be-blind-along-a-whole-dimension.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| On Windows, `subprocess.run(timeout=...)` waits for a grandchild that holds the pipe | `docs/SHARP_EDGES.md` (section of that title) |
| The install path can be broken while every test is green: cwd shadowing hides it | `docs/sharp-edges/install-path-green-masked-by-cwd-shadow.md` |
| 7. Earn the red | `docs/STANDING_PRINCIPLES.md` |
| 12. A gate is proven only on a tree it was not written on | `docs/STANDING_PRINCIPLES.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "a stand-in that simulates
another host inside the test suite"`, which returned the grandchild-pipe footgun first (a Windows
behaviour no stand-in proves: the Scope (out) line), the test-idiom pointer, the cwd-shadow
footgun and Earn the red; the sibling-store and blind-dimension entries came from the sibling
pack's query. Re-run them rather than trusting this list if the pack has been sitting.

## Implementation

Every fix below is a **fix shape (untested)** unless marked measured; its refutation is named.
The fence that prescribes the NEW module carries no `target=` tag, because
`scripts/check_pack_fences.py` resolves a fence against an existing module and a new file has
none; its names are the standard library's and `pytest`'s.

### I-1 The `os` axis *(fix shape, untested)*

Three gap cells land first, appended to `AXIS_REGISTRY` after the `tree` cells (shown here as a tuple so the fence parses on its own), so the registry says the axis exists and is blind; the proving nodes
in I-3 fill them and raise the floor. Refuted if `TestEveryCellIsWellFormed` holds a rule the
new axis cannot meet (every axis declares at least two values: it declares three).

```python target=tests/_axis_registry.py
AXES: tuple[str, ...] = ("stack", "host", "session", "root", "tree", "os")
```

```python target=tests/_axis_registry.py
# ...the tree cells end here; the os cells follow them inside AXIS_REGISTRY...
_OS_CELLS = (
    # -- os ------------------------------------------------------------------
    # The operating system a test makes the harness read, through
    # tests/_platform_standin.py::as_os, on whatever host runs it. A cell is
    # proven by a node parametrised over `os`; the kernel-decided surfaces
    # (LockFileEx, PATHEXT, a grandchild on a pipe) are the Windows leg's and
    # stay in the gap text.
    AxisCell("os", "linux", "", "no test is parametrised over the operating system yet"),
    AxisCell("os", "macos", "", "no test is parametrised over the operating system yet"),
    AxisCell("os", "windows", "",
             "tests/test_redos.py takes the alarm away and tests/test_bounded_spawn.py reads "
             "win32 with a stand-in Popen, neither parametrised over the axis (TP-703i I-3)"),
)
```

### I-2 The shared stand-in *(fix shape, untested)*

*Built as the Decisions at execution say (2026-10-25): two functions, `os_name` opt-in, no
`reload`, no runtime refusal; the fence below is the authoring shape.*

```python
"""One stand-in for the operating system a test makes the harness read (TP-703i)."""
from __future__ import annotations

import importlib.util
import os
import signal
import sys

OS_VALUES = {"linux": ("linux", "posix"), "macos": ("darwin", "posix"), "windows": ("win32", "nt")}
_WINDOWS_LACKS = ("SIGALRM", "setitimer", "ITIMER_REAL")


def as_os(monkeypatch, value: str, *, module, reload: tuple[str, ...] = ()) -> tuple[str, str]:
    """Make the harness read ``value`` for the rest of the test: ``sys.platform``
    and ``os.name`` together, the ``signal`` names Windows lacks deleted for
    ``windows`` (only where ``module``'s ``pytestmark`` runs pytest-timeout's
    thread method; refused otherwise), and each path in ``reload`` re-imported
    so an import-time read of the platform is re-made."""
    platform, name = OS_VALUES[value]
    if value == "windows":
        marks = getattr(module, "pytestmark", ())
        marks = marks if isinstance(marks, (list, tuple)) else (marks,)
        if not any(getattr(m, "name", "") == "timeout" and m.kwargs.get("method") == "thread" for m in marks):
            raise RuntimeError("as_os('windows') deletes signal.SIGALRM; the caller's module must run "
                               "pytest-timeout's thread method (pytestmark = pytest.mark.timeout(method='thread'))")
        for attr in _WINDOWS_LACKS:
            monkeypatch.delattr(signal, attr, raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(os, "name", name)
    return platform, name
```

Refuted if `os.name` patched to `nt` reaches report formation on a host where
`tests/_report_os_name_guard.py` is not the outermost wrapper (its contract,
`tests/test_test_suite_contract.py::test_the_report_os_name_guard_is_registered`, says it is);
and if a reloaded module keeps a sibling import of the old copy (the `test_bounded_spawn.py`
comment on loading by path warns of this; the stand-in reloads only what the caller names).

### I-3 The proving nodes *(fix shape, untested)*

The alarm test gains an `os` parameter (`windows` only at first, so the id is
`[walker-windows]`), calls `as_os` instead of its own three `delattr` lines, and keeps its
assertion; the bounded-spawn class's `windows` fixture takes its platform from `as_os` and keeps
its stand-in `Popen`. The two cells' `proven_by` strings and the floor's dated line land in the
same change (the registry's rule: raise the floor in the change that proves the cell). `linux`
and `macos` stay gaps unless the release-matrix parametrisation varies the harness along them,
which Task 0 item 2 reads; a cell proven by a test that only reads a constant is the born-blind
shape the registry refuses, and this pack does not fake one.

### I-4 The contract addition *(fix shape, untested)*

```python target=tests/test_axis_registry.py
class TestProvenCellsVaryRunAndPass:
    def test_the_proven_count_equals_the_dated_floor(self):
        count = len(reg.proven())
```

One new test in that class, `test_every_os_proving_node_runs_on_the_linux_cell`: over the
`os` axis's proven cells, `collected_items` reports no `skip` or `skipif` mark and, under
`GITHUB_ACTIONS` on `linux`, the node's report is a pass (read through the same child run
`test_every_proven_node_runs_and_passes_here` makes). Dies to a proving node that carries
`skipif(sys.platform != "win32")`: a Linux cell that skips the Windows proof proves nothing.

### What this pack most likely got wrong, for the red-team to bite on

That `as_os` can stand in for the three `delattr` lines without changing what the alarm test
proves (the test's own `monkeypatch.delattr` runs before the timers are called; a stand-in that
patches after import of `tests/test_redos.py` but before the call is the same order, but the
reviewer should drive it); and that a `windows` cell proven by two tests reads as "the suite runs
the harness as Windows" when it runs two functions as Windows: the cell's `proven_by` names the
strongest test, and the gap text must keep naming what the leg alone proves.

## Affected symbols

`/scope-check` keys on bare names; `pytestmark`, `windows` and `as_os` are common words, so
re-run it at the lane's start and accept the collision gap by name.

### Changed-semantics
- `tests/_axis_registry.py::AXES` (gains `os`)
- `tests/_axis_registry.py::AXIS_REGISTRY` (three cells)
- `tests/_axis_registry.py::PROVEN_FLOOR` (rises with each proven cell, dated)
- `tests/test_redos.py::test_the_walker_and_ps_body_timers_skip_on_a_host_without_sigalrm` (parametrised over `os`; calls the stand-in)
- `tests/test_bounded_spawn.py::TestEveryCopysWindowsBranch` (its `windows` fixture reads the stand-in)
- `tests/test_axis_registry.py::TestProvenCellsVaryRunAndPass` (one new test)

### Renamed
- None.

### Added-paths
- `tests/_platform_standin.py`

### Removed-paths
- None.

## Reach

Not a class pack: it closes no ledger class and mints no row. The rows it touches:

Members derived by: the Task 0 item 1 census grep; re-run it.

| Item | Status | Evidence |
|---|---|---|
| `DEF-975` (the adopter-axes registry's row) | **NOT CLOSED**; one more axis in its registry | the three cells and the table's blind-axis line |
| `DEF-5024` | **NOT REACHED**; `TP-703b` Wave 1's contract | this pack parametrises the test that pack's row cites, and changes no guard |
| `DEF-4029` | **NOT REACHED** | the 5.1 alias host is that lane's (Scope out) |

## Pass criteria

- `python3 tests/_axis_registry.py` prints an `os` axis; before I-3 it reads as a blind axis in
  those words, after I-3 it names the `windows` cell's proving node.
- `tests/test_axis_registry.py` is green with `PROVEN_FLOOR` raised by exactly the cells proven,
  each with its dated line; the floor is never lowered.
- Every `os`-proving node collects with an `os` parameter and no `skip` or `xfail` mark, and
  passes on the Linux cells (the new test), on the Air and on the Windows leg.
- *(As built, 2026-10-25.)* A test module that imports `without_the_alarm` by name under the
  default timeout method reds
  `tests/test_test_suite_contract.py::test_every_module_that_arms_sigalrm_declares_the_thread_method`
  (earn the red: a scratch module planted under `tests/`, the receipt in the pull request body), and
  the alarm test's assertion is unchanged in strength.
- The `os`-proving nodes together under 60 seconds per cell, read from `--durations=25` in the
  post-merge run and written into Landing with the spread.
- No existing stand-in is removed and no capability `skipif` is touched; `tests/_report_os_name_guard.py`
  is unchanged and its registration test stays green.
- The tier the lane earns is run with `--base origin/main` and its receipt is in the pull request
  body (the two edited test files are suite code; `tests/_axis_registry.py` is a helper the suite
  config class may cover); the reviewers the `review:` line names run on a snapshot clone.
- No criterion here licenses shipping a defect in the gate this pack delivers: a `windows` cell
  proven by a node that the Linux cell skips, or a stand-in that leaves `os.name` patched past
  the test, is a defect of this pack, not a scope-out.

## Files touched

**New:** `tests/_platform_standin.py`.

**Modified:** `tests/_axis_registry.py`; `tests/test_axis_registry.py`; `tests/test_redos.py`;
`tests/test_bounded_spawn.py`; `task-packs/TP-468-adopter-axes.md` (one Status sentence); `tests/conftest.py` only if the helper module needs a roster line
(the suite's helper modules are not classified in `_MARKER_RULES`; a test file would be, and this
pack adds none).

**Deleted:** none.

**Unmodified on purpose:** `tests/_report_os_name_guard.py`; `tests/test_write_guard.py` (its
`_emulate_windows_paths` keeps its body; a later lane may route it through the stand-in);
`tests/_interpreter_hosts.py` (the `host` axis is complete as it is); `scripts/proof_tier.py`
(Scope out); `tools/cc/` and `espalier/`.

## Sub-task ordering

1. **Task 0**, items 1 to 5; item 1 can end the pack; item 2 decides which modules reload; item
   3 decides which modules can prove `windows`. Checkpoint: the results written into Landing.
2. **I-1** the three gap cells (smallest; the table prints the blind axis). Checkpoint:
   `python3 tests/_axis_registry.py`, `pytest tests/test_axis_registry.py -q`.
3. **I-2** the stand-in; the static contract's red driven against a scratch module importing
   `without_the_alarm` under the default timeout method (as built, 2026-10-25). Checkpoint:
   `pytest tests/test_redos.py -q -k sigalrm` unchanged green.
4. **I-3** the two proving nodes and the floor, then **I-4** the contract test, red first
   against a seeded `skipif`. Checkpoint: the two files' targeted runs, then
   `pytest tests/test_axis_registry.py -q`, then the budget read (Task 0 item 4).
5. **Red-team**, both reviewers on a snapshot clone as the tier's `review:` line names; the two
   likely errors above are the brief's first lines.
6. **The tier**, once, with `--base origin/main`; the push through the ship driver; Landing.

## Estimated effort

Pack budgets on this repository have run about 2.7 times over on one measured pack (`TP-459`);
read these as the author's guess, not a schedule.

| Step | Build | Red-team and tier | Notes |
|---|---|---|---|
| Task 0 | 1 h | | the census read, two collections, one timing |
| I-1, I-2 | 1.5 to 2 h | | three cells, one module, one refusal |
| I-3, I-4 | 2 to 3 h | | two tests reshaped, the floor, one contract test |
| Review and tier | | 1 h plus the tier the diff earns | test files only, expect `contract` or `full` by the suite-config rule |
| Total | 4.5 to 6 h | 1 h | expect the measured overrun |

## Landing
- State: LANDED (2026-10-25 local; lane `lane/platform-stand-ins`, seat `air-work`)
- Commits: c5a97746 (the build), 14ea9215 (the review batch, the two rulings), and the commit that fills this Landing
- Suite: `python3 scripts/proof_tier.py --run --base origin/main` on the lane, the full tier (two
  suite-config files): mypy and ruff clean; the parallel leg 24983 passed, 100 skipped, 3 xfailed, 1 failed in 25 min 40 s, the one red the box-local record-merge test (`tests/test_record_merge.py::TestTheShipBodysRecordFinish::test_a_record_file_staged_with_its_markers_is_refused_until_unresolved`, Apple Git 2.39.5's `update-index --unresolve` exit, red on `main` before this lane and on every lane this seat has run; `TP-703h`'s Task 0 item 4 names it), so `proof: FAIL (worst exit 1)` on that red alone; the serial leg 2134 passed, 9 skipped in 4 min 31 s. The tier ran on the tree before #343 merged, so without the box lock.
- Earn-the-red: nine named mutants, one at a time in fresh interpreters on the committed tree, the
  files restored and compared, 9 of 9 killed: the `skipif` refusal dropped from the `os` axis; a
  `skipif` planted on a live `os` proving node; the thread mark removed from `tests/test_redos.py`;
  a scratch module importing `without_the_alarm` by name under the default method (the alarm
  contract names it, the receipt the dispatcher asked for); `as_os` reading `linux` as `win32`,
  setting no platform, `without_the_alarm` leaving `SIGALRM`; the tree kill dropped from the
  harness's Windows branch; the floor left at 6. The alarm test keeps the assertion it had; the
  new node's are new and each mutant above that reaches them reds by name.
- Red-team: `scripts/proof_tier.py --base origin/main` named `review: code-reviewer`; both
  reviewers were dispatched on a snapshot clone at c5a97746 with a venv of its own. both dispatched on the snapshot clone at c5a97746 (a venv of its own), code-reviewer (pinned Sonnet) and failure-mode-reviewer (pinned Opus): both REQUEST CHANGES, no BLOCK. Agreed on by both and driven on the clone: the alarm test's `os` parameter was decorative (its timers are the suite's own, skip on `hasattr(signal, "SIGALRM")` and read no platform; as `linux` with the alarm gone both legs still skip), so the `windows` cell moves to the bounded-spawn node and the parameter is dropped. Code-reviewer: the helper's "one caller" claim was false (`_emulate_windows_paths` patches inline) and the 3.12+ clause under-stated the guard docstring; both reworded; the chokepoint's `StandInPopen` twin noted and left (not a defect class). Failure-mode-reviewer: a parameter named `os` shadows the module in every proving function and `hasattr(os, ...)`/`getattr(os, ..., default)` read False or the default silently with no lint catching it -- the axis is renamed `target_os` (request `20261026T042549Z-air-work-5bd2e5` with the recommendation, proceeded at 04:40Z); a one-value parametrisation passes the parameter rule and never varies -- the two-value rule, every axis, with planted rows; `_sigalrm_offenders` misses a helper that only re-exports `without_the_alarm` -- not this lane's code, named in the helper's docstring and sent to the dispatcher as a row to file; the copies now load before the platform is faked; `os_name` is keyword-only with no default; the platform roster and the harness's platform comparisons are pinned so "proven on every host" and the `macos` gap text cannot go stale silently. Attacks that found nothing: `subprocess.run`'s timeout path is the same shape in 3.9 to 3.14 and `_mswindows` is import-time, so the linux leg's assertion holds on every host; pytest-timeout picks its method per test, no session switch; module-level `pytestmark` and `pytest.param` skipifs are caught at collection; no mirror or sync is owed. One fix batch, commit 14ea9215; the dispatcher's rulings 116ca9 and 9a0be0 folded in it.
- Reach: see Reach; no row closed; `DEF-975`'s registry gains the axis.
- Task 0: item 1, the census read at 78c16510 (Status: five families in six files plus
  `core.ignorecase`; the two roster-predicate tests excluded; by one command over every spelling,
  20 sites in 10 files, 9 through an alias in 5 files: Decisions at execution, item 3), over the
  threshold of three; item 2, both candidate nodes collect with an `os` parameter and no refusing
  mark, `collected_items` over the two files in 0.7 s, and no module needs a reload; item 3, the
  thread mark at `tests/test_redos.py:87` only, and the split helper means
  `tests/test_bounded_spawn.py` needs none; item 4, the Budget line; item 5, before: no `os` line;
  with the axis and no cells the contract reds `axes declaring fewer than two values: ['os']`
  (I-1's earned red); with three gap cells `- os: **a blind axis** -- no value is proven.`; after
  I-3 `- os: proven at 2 values (linux, windows).`
- Budget (the `os`-proving nodes per cell, pre-registered 60 s): the four `os` nodes together
  0.28 s, 0.24 s, 0.49 s over three runs on the Air (`--durations=0`); `collected_items` over the
  two files 0.7 s. The post-merge run's `--durations=25` will not list them, which is the budget
  met, not unread.
- Interpreters: the targeted set (the registry contract with its proven-nodes child, the
  bounded-spawn class, the alarm test, the three alarm contracts) 67 passed on 3.14.7 and on
  3.10.21 (a fresh venv of this tree); the four touched files and the suite contracts whole under
  xdist, 260 passed, 1 skipped; `tests/test_redos.py` whole, 955 passed.
- Date: 2026-10-25 (landed, local)
