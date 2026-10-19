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
  Linux)", reloading the module under test by path (`_load_copy`) so an import-time read of the
  platform is re-made. `tests/test_spawn_chokepoint.py` carries the same `win32` read for its
  sibling.
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
   removed (no contract step in this pack).
3. **Proving nodes**: the alarm test (`tests/test_redos.py`) and the bounded-spawn Windows
   branch (`tests/test_bounded_spawn.py`) parametrised over `os`, so the `windows` cell is proven by tests that already run on every cell, as the
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
- `as_os("windows")` refuses in a module without the thread method (earn the red: a scratch
  module under the default method), and the alarm test's assertion is unchanged in strength.
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
3. **I-2** the stand-in, with its refusal driven red first (a scratch module under the default
   timeout method). Checkpoint: `pytest tests/test_redos.py -q -k sigalrm` unchanged green.
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
- State: DRAFT
- Commits:
- Suite: `python3 scripts/proof_tier.py --run --base origin/main` on the lane
- Earn-the-red: the stand-in's refusal and the contract test, each against the mutation named
  in I-2 and I-4; the proving nodes keep the assertions they had
- Red-team: not yet run
- Reach: see Reach; no row closed at authoring
- Task 0: not yet run (the census in Motivation is the authoring-time run, 2026-10-18)
- Budget (the `os`-proving nodes per cell, pre-registered 60 s): unmeasured
- Date: 2026-10-18 (authored, local)
