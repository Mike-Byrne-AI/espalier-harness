# TP-703b — The platform legs earn their red: the alarm-guard contract, a slim Windows leg on main, and the macOS skip counted

## Status

- Version target: self-host. Every file this pack touches is this repository's own
  (`tests/`, `.github/workflows/`, `scripts/`); nothing deploys through `espalier init`.
- Type: test-suite contract plus CI workflow. Three waves, each its own lane and pull request,
  because two of them wait on a decision the third does not.
- **Kind: PACK.** `lane/alarm-guard-contract` (W1), `lane/windows-main-leg` (W2),
  `lane/macos-skip-counted` (W3). Each wave has its own Task 0, and each Task 0 can end its wave.
- Parent: `TP-703` (`task-packs/TP-703-multi-seat-discipline.md`), Wave 2, item 5. W2 and W3
  wait on `TP-703a`'s merge, so that the verdicts they change are read by a board line and not
  only by a person; W1 waits on nothing.
- Authored 2026-10-18 (local) by the dispatcher seat `air` on the operator's word ("good, lets
  make task packs for fixing these issues"), from the `/reflect` of the same evening.
- Ledger: W1 strikes `DEF-5024` in-lane (its probe is the row's own). W2 is the first step of
  `DEF-977` and does not close it (Reach says why). W3 touches `DEF-2025`, struck 2026-10-18,
  whose re-open is **the operator's call**: the ledger verbs have no un-strike, so a re-open is a
  successor row minted from the building seat's block that cites the struck row's closure, filed
  only on the operator's word. Nothing else is minted.
- **Two operator calls sit inside this pack**, and the pack says where each wave stops for one:
  W2 is built only after its Task 0 measures the slim leg and the operator reads the figure
  (`DEF-977`'s question returns as written if the leg is not slim); W3 is built only after the
  operator re-opens `DEF-2025`.

## Motivation

The three non-required portability legs (`.github/workflows/portability.yml`: ubuntu, Windows,
macOS) are the suite's only run on a host that is not Linux, and on 2026-10-18 their verdicts
meant nothing, for two different reasons that need two different fixes:

- **Windows was red for a reason the tree made and no cheap gate caught.** `DEF-5024`'s row,
  measured 2026-10-18: the walker row's warm call went under its alarm (`DEF-5023`) through
  `tests/test_redos.py::_walker_alarmed_ms`, one of 2 of that file's 31 arming functions with no
  `hasattr(signal, "SIGALRM")` guard in itself; twelve simulated-clock rows reached it, and the
  Windows leg read "12 failed, 1272 passed, 857 skipped" on #313's run and on #316's, while the
  required cells and the macOS leg passed the same rows (the signal exists there). The fix-forward
  (#320) guarded both helpers and pinned those two timers and no third. The existing contract,
  `tests/test_test_suite_contract.py::test_every_module_that_arms_sigalrm_declares_the_thread_method`,
  asks whether an arming module declares the thread timeout method; nothing asks whether each
  arming function asks for the signal first. So the next unguarded helper passes every required
  cell and reds the Windows leg about 80 minutes after the merge, as this one did.
- **macOS was red for a reason the runners make and nothing counts.** `DEF-2025`'s closing text:
  the nested child's controller crashes inside execnet on the runners, so the build report never
  prints; five sightings by the strike, and `gh pr view 312 --json statusCheckRollup` and the
  same for 313 (read 2026-10-18) show `portability (macos-latest)` `FAILURE` on both post-fix
  merges. The same child completed 12 of 12 times on the Windows box. A leg that is red on every
  run for a known race certifies nothing about the merge it ran on, and a reader built by
  `TP-703a` would print it on every tick.
- **No check runs on Windows after a merge** (`DEF-977`'s text): the only Windows leg is the
  pull-request one, path-filtered, 66 to 81 minutes on 10-18 (`gh run view <id> --json jobs` on
  #313's and #316's runs), finishing after the 47-minute median merge; a red the merge
  combination makes has no Windows reader at all.

Over 10-10 to 10-18 the workflow ran 65 failures, 67 successes and 45 cancellations
(`gh run list --workflow portability.yml --limit 200 --json conclusion`, counted by conclusion).
A leg red half the time is read by nobody; the roadmap's re-measure line 2 asks for 90% green
after this pack and `TP-703h`.

**The named user (`STANDING_PRINCIPLES` §16).** A developer or adopter running the suite on
Windows, who gets twelve reds on a green tree; the Windows leg itself, which catches no new
Windows regression while it is always red; and the seat whose merge is judged red by a macOS leg
for a race it did not make, and who learns to ignore the leg, which is how the next real red is
missed.

## Scope (in)

1. **W1 (`lane/alarm-guard-contract`)**: the contract `DEF-5024` prescribes,
   `test_every_sigalrm_arming_function_guards_itself`, in `tests/test_test_suite_contract.py`
   beside `_sigalrm_offenders`, reusing its `_memo_parser`, `_terminal_name` and
   `_all_test_dir_modules` and the `spellings` rule (today a closure inside `_sigalrm_offenders`;
   it is hoisted to module level so two detectors read one rule, and the existing test keeps
   every assertion). The rule: every function under `tests/` that arms `SIGALRM` (calls
   `setitimer` or `alarm`, or installs a `SIGALRM` handler, under any spelling `from signal
   import ...` gives it) calls `hasattr(signal, "SIGALRM")` in its own body. No caller-path
   analysis: the tree meets the per-function rule today (0 unguarded of 33 after #320, the row's
   census). The row's second clause lands in the same lane: a module that deletes `signal.SIGALRM`
   (`monkeypatch.delattr(signal, ...)`, as
   `tests/test_redos.py::test_the_walker_and_ps_body_timers_skip_on_a_host_without_sigalrm` does)
   must declare the thread method, since under the signal method pytest-timeout's cancel reads the
   name while it is gone. The file is in the contract slice (`tests/conftest.py::_MARKER_RULES`
   names `test_test_suite_contract` under `contract`), so a tests-only diff runs it. `DEF-5024`
   struck in-lane with its own probe.
2. **W2 (`lane/windows-main-leg`)**: after Task 0 measures it, a Windows job over the serial
   files only, run on `main` after each merge, in a workflow of its own,
   `.github/workflows/post-merge-windows.yml`, never as a second job in `post-merge.yml`:
   `tools/cc/board.py::read_post_merge` and `tools/cc/ship.py::base_red_after_merge` read a
   run's conclusion, and a run is red when any job fails, so a flaky Windows job inside the proof
   would turn `main` red and fire the revert-first rule on every flake. The sibling workflow is
   advisory, and it needs a reader of its own: a push run attaches to the merge commit and never
   appears in a merged pull request's `statusCheckRollup`, so `TP-703a`'s rollup read cannot see
   it. W2 gives `tools/cc/_post_merge.py` (`TP-703a`'s module, which must exist first) a second
   base-workflow reader in the shape of `tools/cc/board.py::read_post_merge`: one
   bounded `gh run list --workflow post-merge-windows.yml --branch main --event push --limit N
   --json databaseId,status,conclusion,headSha,url` call, the same no-verdict rule (cancelled,
   stale, skipped and neutral read no verdict, and the read walks back to the newest run that
   reached one), rendered on the board's `checks:` line as `main: post-merge-windows red since
   <sha> (run <id>)`, with its own budget and its own test. The leg runs with the same
   `PYTEST_TIMEOUT=180` the portability leg sets on Windows and a `timeout-minutes` twice the
   measured duration. Its
   pytest line is the serial leg `scripts/proof_tier.py` prints (`python3 scripts/proof_tier.py
   --tier full --leg serial`), never a copied file list.
3. **W3 (`lane/macos-skip-counted`)**: a roster in `tests/conftest.py`, `PLATFORM_EXPECTED_SKIPS`,
   each entry a node id, a platform predicate (`sys.platform == "darwin"` and
   `os.environ.get("GITHUB_ACTIONS") == "true"`, `tests/conftest.py`'s spelling at its three runner
   checks, never a truthy `CI`: the runners, where the race lives; the Windows box ran the child
   12 of 12), the row id, the
   reason and the date; applied in `tests/conftest.py::pytest_collection_modifyitems` as a skip
   whose reason carries the row id; and a contract test in `tests/test_test_suite_contract.py`
   that derives the count from the roster and holds each entry to three facts: its node id
   collects, its row id resolves to a file under `task-packs/ledger.d/`, and its reason names the
   id. The first and only entry is `DEF-2025`'s successor row over
   `tests/test_xdist_never_ran.py::TestACrashedWorkerIsNamedOnlyWhereItsBuildCanBe::test_a_worker_that_dies_in_its_build_is_named_each_time`.
   This is the expand half; `TP-703h`'s registry is the contract half, which takes the roster
   and retires the local one.

## Scope (out)

- **Making the Windows leg a required check** (`DEF-977`'s full form). The measured leg is 66
  to 81 minutes against a 47-minute median merge; W2's figure is what the operator decides on.
- **The full Windows suite on `main`,** or a macOS leg on `main`. The serial files are where the
  two Windows fix-forwards of the week landed (`tests/test_redos.py` both times); a full leg on
  every merge is the required-check question in another form.
- **Fixing `DEF-2025`'s race.** It is the runners' (execnet's channel to a dying worker raising
  inside the controller); the row's closing text names the parser as never the fault. A skip
  counted and dated is honest; a fix is not in this pack's reach.
- **The `TP-703h` registry.** W3's roster is one tuple in one file by design, so the registry
  can take it whole.
- **A reader of the new leg outside `TP-703a`'s module.** The base-run read lands in that module
  (Scope (in) item 2, 2-B) beside its rollup read; the banner and the ship preflight take the
  module's lines as `TP-703a` wires them, unchanged here.
- **The `DEF-5023` walker budget** and `DEF-2025`'s per-worker report file (`DEF-2023`): their
  own rows.

## Task 0 — Verify (per wave; each can end its wave)

Each item names the oracle, the result that ends or holds the wave, and the exit, which is stop
and re-raise to the dispatcher, never adjust and continue.

**W1-0 (the contract).**
1. *Oracle:* the new detector run over the pre-fix text, `git show 9c4ca09d^1:tests/test_redos.py`
   (#320's first parent, which holds the two unguarded helpers), fed as one `(path, text)` module.
   *Refuting result:* it does not read exactly `_walker_alarmed_ms` and `_ps_body_call_ms` as
   unguarded. *Exit:* the rule or its spelling reader is wrong; fix the detector, never the
   figure; if the rule cannot name the two, stop, since a contract that misses the measured
   instance guards nothing.
2. *Oracle:* the detector over `tests/` at the lane's head. *Refuting result:* an unguarded
   function the row's census did not count (the row read 0 of 33 after #320). *Exit:* not a stop:
   guard it in the same lane, and the row's figure is repinned in the closing text.
3. *Oracle:* `grep -n 'def spellings' tests/test_test_suite_contract.py` and the two tests that
   call `_sigalrm_offenders`. *Refuting result:* another open lane edits the function (the
   board's `overlaps:` line names the file). *Exit:* wait for that merge, then hoist.

**W2-0 (the slim leg; the operator reads the figure before anything is written).**
1. *Oracle:* one dispatched run, the serial files only on Windows:
   `SEL=$(python3 scripts/proof_tier.py --tier full --leg serial | sed -n "s/^run: pytest -q -n 1 -m 'not heavy_e2e' //p")`
   then `gh workflow run portability.yml -f os=windows-latest -f select="$SEL"`, and the job's
   duration from `gh run view <id> --json jobs`. The analysis that proposed this leg said "about
   ten minutes"; that figure is **unmeasured** and this is its measurement. *Refuting result:* over
   30 minutes (the `test-serial` cells' `timeout-minutes` in `.github/workflows/test.yml`, the
   serial leg's ceiling on Linux). *Exit:* the leg is not slim; stop, and `DEF-977`'s question
   returns to the operator as written, with the figure.
2. *Oracle:* `grep -n 'conclusion' tools/cc/board.py tools/cc/ship.py` at `read_post_merge` and
   `base_red_after_merge`. *Measured 2026-10-18:* both read the run's conclusion, so a failing job
   inside `post-merge.yml` reds `main`. *Refuting result:* none; this is why W2 is a sibling
   workflow. If a later lane makes the base-run readers job-aware, W2 may fold into
   `post-merge.yml` as a non-blocking job, and says so.
3. *Oracle:* the dispatched run's summary line. *Refuting result:* a red among the serial files
   on a green tree (a Windows-only red the week's two fix-forwards did not cover). *Exit:* the leg
   would be born red; file the row in-lane, fix or skip under W3's roster first, then build.
4. *Oracle:* the required cells' queue time over one day: per `test.yml` run (`gh run list
   --workflow test.yml --limit 50 --json databaseId,createdAt`), the `startedAt` of its `test (3.x)`
   jobs from `gh run view <id> --json jobs` minus the run's `createdAt`; the median and the worst. *Refuting result for a concurrency group:* the advisory leg's self-overlap
   (a run of 66 to 172.9 minutes on every merge, about 25 a day) does not move that queue time,
   measured again after the leg's first day. *Exit:* the choice is written from the figure, never
   copied from `post-merge.yml` (its "no concurrency group" reason bounds revert suspects for a
   blocking proof and does not apply here): a group with `cancel-in-progress` only if the overlap
   is measured to delay the required cells, else none; the header says which and why.

**W3-0 (the counted skip).**
1. *Oracle:* the operator's word on re-opening `DEF-2025` (a successor row). *Refuting result:*
   no. *Exit:* W3 is not built; the leg stays red on the runners and `TP-703a`'s line names it
   every tick, which is the honest state.
2. *Oracle:* the test's node id over the last ten `portability (macos-latest)` runs
   (`gh run list --workflow portability.yml --limit 60 --json databaseId,conclusion`, then `gh
   run view <id> --log-failed` per red run). *Refuting result:* fewer than 3 of 10 red on that
   test. *Exit:* the flake has moved or faded; re-raise with the count rather than skip a test
   that passes.
3. *Oracle:* `grep -n 'skipif\|mark.skip' tests/conftest.py tests/test_xdist_never_ran.py`.
   *Refuting result:* a per-platform skip convention already exists in the suite (read
   2026-10-18: one `skipif(sys.platform != "darwin")` in `tests/test_archive_transcripts.py`, no
   roster). *Exit:* if one exists, register there rather than add a second.

## Relevant memory

Recent pattern, measured: both Windows fix-forwards of the week landed in `tests/test_redos.py`,
and both were found by a person reading a job log after the merge; the contract that exists for
the file's alarms asks a module-level question, and the defect was per-function. The macOS red
has been "known" in bodies and notes for five sightings and counted nowhere a tool reads.

| Entry | Where |
|---|---|
| Parallel work protocol (item 7, a red `main`) | `memory/parallel-work-protocol.md` |
| On Windows, `subprocess.run(timeout=...)` waits for a grandchild that holds the pipe | `docs/SHARP_EDGES.md` (section of that title) |
| POSIX-only `os.O_*` flags need `getattr` guards for Windows | `docs/SHARP_EDGES.md` (section of that title) |
| Convergence theater is a class, not a bug | `docs/SHARP_EDGES.md` (section of that title) |
| Converting a self-detecting skipif to a marker drops every filter-less consumer (W3 applies its skip at collection, so every consumer self-skips) | `docs/sharp-edges/skipif-to-marker-drops-filterless-consumers.md` |
| The marker taxonomy and `_MARKER_RULES` (the collection hook W3 extends assigns markers today) | `docs/SHARP_EDGES.md` (the `_MARKER_RULES` section); `docs/CONVENTIONS.md` (Marker taxonomy) |
| Classify the surface before measuring it | `memory/classify-the-surface-before-measuring-it.md` |
| 14. Derive the list, don't test a hand-written copy of it | `docs/STANDING_PRINCIPLES.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "SIGALRM thread timeout
method Windows portability leg"` and `... "a known red skipped per platform and counted"`; the
second returned lexical neighbours (hook authoring, the hardlinked clone) rather than an answer,
and no entry on counted platform skips exists, which is part of why W3 writes one down. Re-run
them rather than trusting this list if the pack has been sitting.

## Implementation

Every fix below is a **fix shape (untested)** unless marked measured; its refutation is named.
The pack prescribes prose shapes: no fence here is copy-ready, because W1's edit hoists a closure
whose exact lines the lane reads at its head, W2's file does not exist until its Task 0 says so,
and W3's roster is a tuple whose one entry waits on the operator.

### W1 — the alarm-guard contract (`lane/alarm-guard-contract`)

**1-A Hoist the spelling reader.** `tests/test_test_suite_contract.py`'s `spellings(tree)` and
`arms(node, names)` move from inside `_sigalrm_offenders` to module level as `_sigalrm_spellings`
and `_arms_sigalrm`, with `_sigalrm_offenders` calling them; the two existing tests keep every
assertion (`test_every_module_that_arms_sigalrm_declares_the_thread_method`'s floor of two arming
modules included). *Refuted if:* the closures read a variable of the enclosing function other
than their arguments (read them first).

**1-B The detector.** `_sigalrm_unguarded(modules)` returns, per module, the qualified names of
every function or method whose body arms (by `_arms_sigalrm`) and whose body holds no call
`hasattr(<name>, "SIGALRM")` where `<name>` is a spelling of the `signal` module (`import signal
as s` counts). A nested function is its own unit, as `_sigalrm_offenders` treats units. *Refuted
if:* W1-0 item 1 does not read the two pre-fix helpers.

**1-C The test.** `test_every_sigalrm_arming_function_guards_itself` over
`_all_test_dir_modules()`: asserts the detector read at least one arming function (the floor
that says the detector is not policing an empty set) and that the unguarded list is empty, each
offender printed as `path::qualname`. Earned red twice: a synthetic module string with an
unguarded `def` is flagged (the must-trip case, in a sibling test), and the detector over
`9c4ca09d^1`'s `tests/test_redos.py` reads the two helpers (W1-0 item 1, recorded in Landing).

**1-D The delete clause.** `_sigalrm_offenders` also counts a module as arming when any unit
calls `monkeypatch.delattr(signal, <name>, ...)` or `del signal.SIGALRM` under any spelling, where
`<name>` is the constant `"SIGALRM"` or any non-constant expression: the one real instance,
`tests/test_redos.py::test_the_walker_and_ps_body_timers_skip_on_a_host_without_sigalrm`, loops
`for name in ("SIGALRM", "setitimer", "ITIMER_REAL")` into `monkeypatch.delattr(signal, name,
raising=False)`, so a literal-only match is blind to the likeliest copy source. The thread-method
test then flags a module that deletes the name without the mark. Earned red against a must-trip
fixture copied from that loop (under no `pytestmark`), the literal form a second case. *Refuted
if:* the row's
reasoning is wrong about the signal method's cancel reading the name (the row says the
failure-mode review measured it; the lane re-reads `pytest_timeout`'s source at the pinned
version before relying on it, and if the cancel is guarded there, 1-D is dropped and the row's
text corrected at the strike).

**1-E Strike `DEF-5024`** with the row's own probe (it reads the contract file for the test's
name, an assert and the detector's `"hasattr"` string), `python3 tools/cc/ledger_row.py strike
DEF-5024 --text-file <outside the checkout>`.

### W2 — the slim Windows leg on `main` (`lane/windows-main-leg`; after W2-0 and the operator)

**2-A `.github/workflows/post-merge-windows.yml`.** `on: push: branches: [main]` and
`workflow_dispatch`; `permissions: contents: read`; the concurrency choice W2-0 item 4 measured
(a group with `cancel-in-progress` only where the leg's self-overlap delayed the required cells,
else none), never the reason `post-merge.yml` gives, which bounds revert suspects for a blocking
proof and does not apply here; one job on `windows-latest`, `timeout-minutes` at twice
W2-0's measured duration, rounded up to ten; checkout with full history as `post-merge.yml`
does; Python 3.12; `pip install -e .[dev]`; `PYTEST_TIMEOUT=180` as the portability leg sets on
Windows; the step runs `python scripts/proof_tier.py --run --tier full --leg serial`, so the file
list has one home. The header says in its first lines that it is advisory, that it is a separate
workflow because the proof's readers read a run's conclusion, which concurrency choice the
queue-time figure decided, and that `tools/cc/_post_merge.py`'s base-run read reads it. *Refuted if:* `proof_tier.py --run --leg serial` cannot run under `bash` on the Windows
runner (the portability step runs `bash` on every runner; `scripts/proof_tier.py` is Python and
spawns `pytest` by name; W2-0 item 1's dispatch is the measurement of both).

**2-B The reader.** A second base-workflow reader in `tools/cc/_post_merge.py`, in the shape of
`tools/cc/board.py::read_post_merge`: one bounded `gh run list --workflow post-merge-windows.yml
--branch main --event push --limit N --json databaseId,status,conclusion,headSha,url` call (`N`
the module's window), the newest completed run with a verdict decides, and cancelled, stale,
skipped or neutral runs read no verdict and are walked past, as `read_post_merge` does; the
module renders `main: post-merge-windows red since <sha> (run <id>)` among its `checks:` lines,
and `none` when the newest verdict is green. Its test runs on a frozen run listing (a red newest,
a cancelled newest over an older red, a green newest) and `tests/test_board.py` gains the rendered
line; the read has its own budget inside the board's section read, and a failed `gh` call is its
own `unread` clause, never the board's. *Refuted if:* `TP-703a` has not merged (W2 waits on it;
the board's open-PR list is the read), or its module takes no second workflow name (then the
reader is a sibling function in the same module, added here).

**2-C `DEF-977`'s text** gains one sentence at its tail naming the advisory leg and the measured
duration, by `python3 tools/cc/ledger_row.py repin DEF-977 --reason ...`; the row stays open,
since its probe counts Windows jobs that gate a merge and this one gates nothing.

### W3 — the macOS skip, counted (`lane/macos-skip-counted`; after the operator re-opens)

**3-A The roster.** In `tests/conftest.py`, beside `_FULL_TREE_NODEIDS`, a tuple
`PLATFORM_EXPECTED_SKIPS` of entries `(node id, platform, row id, reason, date)`, the platform
one of a small enumerated set the predicate function maps (`"macos-ci"`: `sys.platform ==
"darwin"` and `os.environ.get("GITHUB_ACTIONS") == "true"`, the spelling `tests/conftest.py` uses
at its three existing runner checks; a truthy `CI` would fire on `CI=false` and on local tooling
that sets it), with a docstring that says the tuple is a declared
population and the contract test is what keeps it honest. *Refuted if:* W3-0 item 3 finds a
convention already there.

**3-B The skip.** `pytest_collection_modifyitems` adds `pytest.mark.skip(reason=f"{row id}:
{reason}")` to a collected item whose node id is in the roster and whose platform predicate
holds; nothing else changes in that hook. The summary's `skipped` count then carries the entry on
the runners and nowhere else.

**3-C The contract.** `test_every_platform_skip_is_a_live_row_over_a_real_test` in
`tests/test_test_suite_contract.py`: for each entry, the node id is among the collected items of
its file (a `pytest --collect-only -q <file>` subprocess, or the suite's own collection list where
a fixture already carries it), the row is LIVE (its member line is not struck: the id is among
`tools/cc/generate_ledger_regions.py::live_member_ids` over the row file's text, since a struck
row keeps its file under `task-packs/ledger.d/` and a file-exists check would let the skip outlive
its row), and the reason starts with the id. Earned red against an entry naming a test that does
not exist, against one naming a row file that does not, and against one naming a struck row
(`DEF-2025`'s own struck file is that fixture). The roster's length is never written anywhere but
derived from it.

**3-D The row.** The successor row for `DEF-2025` is filed by the operator's word only, from the
building seat's block, with the sighting count W3-0 item 2 measured, and the roster's one entry
names it. The struck row's closing text is not edited.

## Affected symbols

`/scope-check` keys on bare names. `spellings` and `arms` collide with other test helpers; re-run
it at each wave's start and accept the collision gap by name.

### Changed-semantics
- `tests/test_test_suite_contract.py::_sigalrm_offenders` (calls the hoisted readers; counts a
  module that deletes the name as arming)
- `tests/test_test_suite_contract.py::test_every_module_that_arms_sigalrm_declares_the_thread_method`
  (the delete clause widens what it flags; its assertions are kept)
- `tests/conftest.py::pytest_collection_modifyitems` (W3: applies the roster)
- `tools/cc/_post_merge.py` (W2-B: a second base-workflow reader beside its pull-request rollup
  read; the module is `TP-703a`'s)
- `tools/cc/board.py::collect` (W2-B: the base-run read joins the `checks:` section's read)

### Renamed
- None.

### Added-paths
- `tests/test_test_suite_contract.py::_sigalrm_spellings`
- `tests/test_test_suite_contract.py::_arms_sigalrm`
- `tests/test_test_suite_contract.py::_sigalrm_unguarded`
- `tests/test_test_suite_contract.py::test_every_sigalrm_arming_function_guards_itself`
- `tests/test_test_suite_contract.py::test_every_platform_skip_is_a_live_row_over_a_real_test`
- `tests/conftest.py::PLATFORM_EXPECTED_SKIPS`
- `.github/workflows/post-merge-windows.yml`

### Removed-paths
- None.

## Reach

The pack closes one row and touches two. Members derived by:
`grep -lE 'SIGALRM|portability|windows-latest|macos-latest|xdist_never_ran' task-packs/ledger.d/*.md`
over live and struck rows (re-run it; the rows below are the ones a wave's mechanism reaches).

| Item | Status | Evidence |
|---|---|---|
| `DEF-5024` (no check that each `SIGALRM`-arming test function guards itself) | **CLOSED by W1** | the detector reads 2 unguarded on `9c4ca09d^1` and 0 at the head; the must-trip module is flagged; the row's probe prints True; struck in-lane |
| `DEF-977` (no Windows check gates a merge) | **NOT CLOSED**; W2 is its first step and gates nothing | the row's probe (Windows jobs in `test.yml`) still prints 0; the tail sentence names the advisory leg and its measured minutes |
| `DEF-2025` (struck 2026-10-18; the runners' race in the nested child) | **RE-OPENED as a successor row and its red SKIPPED, counted, by W3**, on the operator's word only | the roster's one entry; the contract test; the leg's green rate (the roadmap's line 2) |
| `DEF-5023` (the walker row's warm call under its alarm) | **NOT REACHED** | its own row; W1 guards the function, not the budget |
| `DEF-2023` (a per-worker build report file) | **NOT REACHED** | named in `DEF-2025`'s fix shape; not this pack's |

## Pass criteria

- W1: `pytest tests/test_test_suite_contract.py -q` green at the head; the new test reds on the
  text of `9c4ca09d^1:tests/test_redos.py` and on the synthetic unguarded module; no assertion in
  `test_every_module_that_arms_sigalrm_declares_the_thread_method` or
  `test_no_engine_or_hook_module_arms_sigalrm` is weakened and no floor lowered; `DEF-5024`'s
  probe prints True and the row is struck.
- W2: the measured duration of the dispatched serial run on `windows-latest` is in this file's
  Landing before the workflow exists; the workflow's `timeout-minutes` is at least twice it; a
  push to `main` runs it and `tools/cc/board.py` names its red on the `checks:` line through
  2-B's base-run read (the frozen listing's three cases pass, a push run appearing in no merged
  pull request's rollup) and never on the `main:` line; `tools/cc/board.py::read_post_merge`'s
  verdict is unchanged by any run of it; the concurrency choice in the header names the queue-time
  figure that decided it.
- W3: on a runner where the predicate holds the skip reason carries the successor row's id; on
  this Mac, where `GITHUB_ACTIONS` is unset, the test runs; the contract test reds on a roster
  entry naming a missing test, on one naming a missing row file, and on one naming a struck row;
  the roster's count appears in no prose.
- Earn-the-red recorded per fix against the mutation named in Implementation; a test that only
  ever passed does not count.
- The tier each lane earns is run with `--base origin/main` and its receipt is in the pull
  request body: W1 and W3 are tests-only (the contract slice, by the rule `scripts/proof_tier.py`
  prints); W2 is a CI definition and earns both reviewers.
- No criterion here licenses shipping a defect in a gate the pack delivers: a detector that reads
  a guard in a sibling function as the arming function's own, or a skip that fires off the
  runners, is a defect of this pack, not a scope-out.

## Files touched

**New:** `.github/workflows/post-merge-windows.yml` (W2, after its Task 0 and the operator).

**Modified:** `tests/test_test_suite_contract.py` (W1, W3); `tests/conftest.py` (W3);
`tools/cc/_post_merge.py` and its vendored twin by `scripts/sync_vendor_cc.py` (W2-B);
`tests/test_post_merge.py` (W2-B); `tools/cc/board.py` and `tests/test_board.py` (W2-B, the
rendered line); `task-packs/ledger.d/DEF-5024.md` (struck by the verb, W1);
`task-packs/ledger.d/DEF-977.md` (repinned by the verb, W2); one new row file under
`task-packs/ledger.d/` and its probe under `task-packs/probes.d/` (W3, by the verb, on the
operator's word).

**Deleted:** none.

**Unmodified on purpose:** `.github/workflows/post-merge.yml` (the proof's verdict is the
revert trigger and stays one job); `.github/workflows/portability.yml` (`TP-703a` corrects its
header; its legs stay as they are); `tests/test_redos.py` (already guarded by #320);
`tests/test_xdist_never_ran.py` (the skip is applied at collection, never written into the file);
`scripts/proof_tier.py::SERIAL_FILES` (the one home W2 reads).

## Sub-task ordering

1. **W1-0, then W1** (1-A, 1-B, 1-C, 1-D, 1-E): the smallest change and the one that needs no
   decision. Checkpoint: the contract slice, the red on `9c4ca09d^1`, the strike.
2. **W2-0 item 1**, the dispatched measurement, by the dispatcher or the assigned seat at any
   time; its figure goes to the operator with `DEF-977`'s question. **W2** only on the operator's
   word and after `TP-703a` merges. Checkpoint: a `main` push runs the workflow; the board names
   it on `checks:`.
3. **W3-0 items 1 and 2**, then **W3** only on the operator's re-open and after `TP-703a` merges.
   Checkpoint: the roster, the contract test's two reds, the successor row.
4. **Red-team each wave** before its tier, the reviewers its diff earns on a snapshot clone.
   What this pack most likely got wrong, for the passes to bite on: 1-B reading a guard in a
   caller as the callee's (the row says no caller-path analysis is needed because the tree meets
   the per-function rule; a reviewer should try the shape where a guarded wrapper calls an
   unguarded helper and confirm the helper is flagged); 2-A's `timeout-minutes` from one
   measurement of a leg the row says ran 172.9 minutes serial once; 3-B's predicate reading a
   `GITHUB_ACTIONS` value other than `true` as the runners. W2's reviewer brief names two angles
   the authoring review lacked (its reasoning review's first finding): GitHub semantics (which
   runs attach to a pull request's rollup and which to `main`; the shared job pool the thirteen
   required checks draw on) and Windows release behaviour.
5. **Landing** per wave in this file's stanza; W2-0's figure also goes to the operator's
   `DEF-977` decision, and the roadmap's re-measure line 2 opens at W3's merge.

## Estimated effort

Pack budgets on this repository have run about 2.7 times over on one measured pack (`TP-459`);
read these as the author's guess, not a schedule.

| Wave | Build | Red-team and tier | Notes |
|---|---|---|---|
| W1 | 2 to 3 h | 0.5 h plus the contract slice | a hoist, a detector, two tests, a strike |
| W2 | 1 h after a 1 to 2 h dispatched run | 1 h plus the full tier | a workflow and one reader line; the operator's call first |
| W3 | 1.5 to 2 h | 0.5 h plus the contract slice | a roster, a hook change, a contract test, a row by the verb |
| Total | 4.5 to 6 h | 2 h | expect the measured overrun |

## Landing
- State: DRAFT
- Commits:
- Suite:
- Earn-the-red: per wave, against the mutation its Implementation names; W1's red on
  `9c4ca09d^1:tests/test_redos.py` recorded here when run
- Red-team: reasoning review at authoring (the reflect skill's checklist v1, failure-mode-reviewer,
  2026-10-18): REQUEST CHANGES on the set; this file's Part 2 items 3, 10, 12, 19, 20 addressed (the
  base-run reader in W2; the variable-name delete; the live-row rule; the `GITHUB_ACTIONS` predicate;
  the queue-time read before any concurrency choice); checklist item 1 acknowledged. The executor still runs the reviewers each diff earns.
- Reach: see Reach; `DEF-5024` closes at W1; `DEF-977` stays open; `DEF-2025`'s successor only
  on the operator's word
- W2-0 measured duration of the serial files on `windows-latest`: not yet run (the analysis's
  "about ten minutes" is unmeasured)
- Date: 2026-10-18 (authored, local)
