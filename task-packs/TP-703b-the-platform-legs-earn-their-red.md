# TP-703b — The platform legs earn their red: the alarm-guard contract, a slim Windows leg on main, and the macOS race counted

## Status

- Version target: self-host for W1 and W3, whose files are this repository's own (`tests/`,
  `.github/workflows/`, `scripts/`). W2-B edits two deployed files, `tools/cc/_post_merge.py`
  and `tools/cc/board.py` (`espalier/managed_paths.py` deploys both), and one deployed command
  body, `.claude/commands/inbox.md`, so W2 syncs the vendored and `.claude` mirrors and
  refreshes the integrity manifest (corrected at W2's 0-A, 2026-10-31; the first text said
  nothing deploys).
- Type: test-suite contract plus CI workflow. Three waves, each its own lane and pull request,
  because two of them wait on a decision the third does not.
- **Kind: PACK.** `lane/tests-each-sigalrm-arming-function-guards-itself` (W1, the name the ship
  driver derives from its subject; authored as `lane/alarm-guard-contract`), `lane/windows-main-leg` (W2),
  `lane/tests-macos-race-rows-run-as-expected-failures` (W3, the name the ship driver derives
  from its subject). Each wave has its own Task 0, and each Task 0 can end its wave.
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
  operator re-opens `DEF-2025`. **Given 2026-10-19**, with the kind changed by the operator: the
  six rows are marked non-strict expected failures on the runners instead of skipped, so they
  still run and `DEF-2025`'s crash watch keeps counting (W3 below).

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
  `TP-703a` would print it on every tick. **The class is wider than the one test the row is
  anchored on** (read 2026-10-19 by the dispatcher, before any assign, over the six red macOS
  legs of runs 39143193815, 39147472099, 39155912533, 39165290167, 39165778649 and
  39169603099, `gh run view <id> --log-failed`): every leg failed the anchor test, three of
  the six also failed the four consumers of the module-scoped `crashed` fixture
  (`tests/test_xdist_never_ran.py:344`, four setup ERRORs), and one of those three also failed
  `test_no_summary_asked_for_none_and_gets_none` (corrected at W3's 0-A: the first text had all
  three failing five more ids) -- with the same execnet `cannot send (already closed?)` after a
  worker's `Not properly terminated`, the mechanism the row names; the three-attempt driver
  (`_ATTEMPTS`, line 86) lost all three attempts in those runs. One mechanism, six node ids: W3's
  roster takes the class, keyed on the row, or the leg stays red on half its runs with the anchor
  alone marked.
- **No check runs on Windows after a merge** (`DEF-977`'s text): the only Windows leg is the
  pull-request one, path-filtered, 66 to 81 minutes on 10-18 (`gh run view <id> --json jobs` on
  #313's and #316's runs), finishing after the 47-minute median merge; a red the merge
  combination makes has no Windows reader at all.

Over 10-10 to 10-18 the workflow ran 65 failures, 67 successes and 45 cancellations
(`gh run list --workflow portability.yml --limit 200 --json conclusion`, counted by conclusion).
A leg red half the time is read by nobody; the roadmap's re-measure line 2 asks for 90% green
after this pack and `TP-703h`. With the anchor test alone marked, three of the last six red
macOS legs would still be red on the sibling node ids above, so that line is reachable
only by the class-sized roster.

**The named user (`STANDING_PRINCIPLES` §16).** A developer or adopter running the suite on
Windows, who gets twelve reds on a green tree; the Windows leg itself, which catches no new
Windows regression while it is always red; and the seat whose merge is judged red by a macOS leg
for a race it did not make, and who learns to ignore the leg, which is how the next real red is
missed.

## Scope (in)

1. **W1 (`lane/tests-each-sigalrm-arming-function-guards-itself`)**: the contract `DEF-5024` prescribes,
   `test_every_sigalrm_arming_function_guards_itself`, in `tests/test_test_suite_contract.py`
   beside `_sigalrm_offenders`, reusing its `_memo_parser`, `_terminal_name` and
   `_all_test_dir_modules` and the `spellings` rule (today a closure inside `_sigalrm_offenders`;
   it is hoisted to module level so two detectors read one rule, and the existing test keeps
   every assertion). The rule, as built at W1's review round (1-B): every read of an alarm name
   Windows lacks under `tests/` (`SIGALRM`, `setitimer`, `alarm`, `ITIMER_REAL` and their kin, as
   a `signal` attribute or a `from signal import`) sits under a guard that covers it, a branch
   that runs only with the alarm or an earlier quiet exit without it. No caller-path analysis: the
   tree meets the rule today (33 reading scopes, 0 uncovered). The row's second clause lands in
   the same lane (1-D): a module that deletes a `signal` name the timeout plugin reads
   (`monkeypatch.delattr(signal, ...)`, as
   `tests/test_redos.py::test_the_walker_and_ps_body_timers_skip_on_a_host_without_sigalrm` does),
   or imports a function that does, must declare the thread method, since under the signal method
   pytest-timeout's cancel reads the name while it is gone. The file is in the contract slice (`tests/conftest.py::_MARKER_RULES`
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
   it. W2 gives `tools/cc/_post_merge.py` (`TP-703a`'s module, landed) the rule and the words of
   a second base-workflow read, as pure functions over the parsed run listing (the module has no
   `gh`, no window and no `Unresolvable`: `base_run_verdict`, `base_run_lines`), and
   `tools/cc/board.py::read_post_merge_checks` the one bounded `gh run list --workflow
   post-merge-windows.yml --branch main --event push --limit N --json
   databaseId,status,conclusion,headSha,url` call under its own try/except, beside the section's
   merged read; the same no-verdict rule as `read_post_merge` (cancelled, stale, skipped and
   neutral read no verdict, and the read walks back to the newest run that reached one), then on
   a red back to the streak's first red and the green before it, rendered on the board's
   `checks:` line as `post-merge-windows (main, advisory): red since <sha> (run <id>)`, with its own budget
   and its own tests; a repository without the workflow renders nothing. The leg runs with the
   same `PYTEST_TIMEOUT=180` the portability leg sets on Windows, under `shell: bash`, and a
   `timeout-minutes` of 25 (the serial files' longest own timeout mark plus ten minutes). Its
   pytest line is the serial leg `scripts/proof_tier.py` prints (`python3 scripts/proof_tier.py
   --tier full --leg serial`), never a copied file list. (Corrected at W2's 0-A, 2026-10-31.)
3. **W3 (`lane/tests-macos-race-rows-run-as-expected-failures`)**: a roster in
   `tests/conftest.py`, `PLATFORM_EXPECTED_FAILURES`, each entry a node id or a class's node-id
   prefix, a platform key, the row id, the reason and the date. The platform key maps to a pure
   predicate of `sys.platform` and the environment (`"macos-ci"`: `darwin` and
   `GITHUB_ACTIONS == "true"`, `tests/conftest.py`'s spelling at its three runner checks, never a
   truthy `CI`: the runners, where the race lives; the Windows box ran the child 12 of 12 and this
   Mac never showed it). Applied in `tests/conftest.py::pytest_collection_modifyitems` as
   `pytest.mark.xfail(strict=False, raises=..., reason=f"{row id}: {reason}")`, the reason form of
   the strict bridge in `tests/test_adopter_lifecycle_diagnostics.py`, on the operator's word of
   2026-10-19: non-strict, the declared exception to `test_pyproject_declares_xfail_strict`,
   because the rows complete on the runners about one run in five and a strict mark would red
   those; the rows still run, so `tests/conftest.py::report_nested_controller_crashes` keeps
   counting the race; `raises` names only the race's two shapes (pytest's own failure from the
   three-attempt driver, and an assertion over a child the race cut short), so any other error
   still reds the leg. Contract tests in `tests/test_test_suite_contract.py` hold each entry to
   its facts (its id names a test class or function in its file, its row is live in the assembled
   ledger view, its mark is non-strict with the row id leading the reason, its predicate fires
   only on the runners), derive the class from the source and hold the roster to it (the rows
   whose child kills its xdist workers inside the build, `PROBE_BUILD_DIES`, directly or through
   the module-scoped `crashed` fixture, are exactly the tests the row's entries cover), and find
   no other non-strict expected failure under `tests/`. The first entries are `DEF-2025`'s
   successor row over that class in `tests/test_xdist_never_ran.py`: the anchor test
   (`TestACrashedWorkerIsNamedOnlyWhereItsBuildCanBe::test_a_worker_that_dies_in_its_build_is_named_each_time`)
   and the class `TestACrashedControllerStillPrintsWhatItSaw` (the four consumers of the `crashed`
   fixture and `test_no_summary_asked_for_none_and_gets_none`), six node ids measured red on the
   runners (Motivation), a count derived from the source and never written by hand
   (`memory/fix-the-class-not-the-instance.md`). This is the expand half; `TP-703h`'s registry is
   the contract half (Cross-pack coordination says what it must add to take the roster).

## Scope (out)

- **Making the Windows leg a required check** (`DEF-977`'s full form). The measured leg is 66
  to 81 minutes against a 47-minute median merge; W2's figure is what the operator decides on.
- **The full Windows suite on `main`,** or a macOS leg on `main`. The serial files are where the
  two Windows fix-forwards of the week landed (`tests/test_redos.py` both times); a full leg on
  every merge is the required-check question in another form.
- **Fixing `DEF-2025`'s race.** It is the runners' (execnet's channel to a dying worker raising
  inside the controller); the row's closing text names the parser as never the fault. An
  expected failure, counted, dated and still run, is honest; a fix is not in this pack's reach.
- **The `TP-703h` registry.** W3's roster is one tuple in one file by design, so the registry
  can take it whole.
- **A reader of the new leg outside `TP-703a`'s module.** The base-run rule and its words land
  in that module (Scope (in) item 2, 2-B) beside its rollup rule, and the one `gh` call in
  `tools/cc/board.py`, where the module's other readers' calls are; the banner and the ship
  preflight take the module's lines as `TP-703a` wires them, unchanged here.
- **The `DEF-5023` walker budget** and `DEF-2025`'s per-worker report file (`DEF-2023`): their
  own rows.

## Cross-pack coordination

Added at W3's 0-A (2026-10-19), from the pack-artifact review.

- **`TP-703h`** takes W3's roster into its registry (expand here, contract there). Its kinds at
  authoring are a strict expected failure and a skip; the operator's 2026-10-19 decision makes
  W3's entries a third kind, non-strict and still run, counted by the crash watch. `TP-703h`'s
  0-A adds that kind or keeps this roster, and its row for `DEF-2025` names the successor row
  and the class (at authoring it names only the anchor). Shared file: `tests/conftest.py`.
- **`TP-703i`** edits `tests/conftest.py` (a stand-in roster line, if its census needs one), and
  meets W1: W1's 1-D delete clause would flag `TP-703i`'s planned stand-in helper, which deletes
  the signal names under no thread mark. *Resolved at W1's 0-A, corrected at its review round:*
  neither authoring option held (with the clause counting the module, a marked helper beside an
  unmarked importer read clean, on a scratch run). The clause counts the unit and the importer arm
  follows a function from module to module, so every test module that imports such a helper,
  directly or through another helper's function imported by name, is asked for the thread method
  (a whole-module import of a wrapping helper, and a subclass of an arming class, are followed since 2026-10-26: `DEF-4035` closed), and the helper itself is
  asked for nothing, since a `pytestmark` in a module pytest never collects applies to no test.
  `tests/test_bounded_spawn.py` carries no `pytestmark` today, so `TP-703i` adds one where it
  imports `as_os`. *(Superseded 2026-10-26 by `TP-703i`'s build: the alarm deletion is its own
  module-level function, `without_the_alarm`, which `as_os` never calls, so a module importing
  `as_os` alone is asked for no mark and `tests/test_bounded_spawn.py` keeps none; that pack's
  Decisions at execution.)* Keep `as_os`'s deletes in a module-level function: a helper that deletes under
  a module-level or class-level statement is reported. A `tests/conftest.py` that imports such a
  helper is read and reds (no mark in `conftest.py` reaches a test), so wire `as_os` into the test
  modules, not through `conftest.py`. Not read: a `pytest_plugins` module, a relative or
  `importlib` import, and the value a module passes (one that imports `as_os` only for linux or
  macOS is still asked for the thread method).
- **`TP-703a`** (LANDED, kept in `task-packs/` until the roadmap lands) cites `DEF-5024`'s
  contract in its Scope (out) as this pack's. The strike verb reads every pack in the root as
  active and refuses on that line, so W1 strikes with `--despite-deferrals` and a closing text
  that says the work landed here; the landed record is not edited. Added at W1's 0-A.
- **W2's own 0-A**: `tools/cc/board.py` and `tools/cc/_post_merge.py` are deployed
  (`espalier/managed_paths.py`), so the Status line's "nothing deploys through `espalier init`"
  did not hold for W2-B. Pre-flagged at W1's 0-A, not corrected there; corrected at W2's 0-A
  (2026-10-31), the Status line now says which files deploy. The deployed `board.py` runs on
  adopter trees with no `post-merge-windows.yml`, and on this repository between W2's merge and
  its first push run, so the reader's absent state renders nothing (2-B).
- **`TP-703c`** edits `tests/conftest.py`'s `pytest_configure`, a hunk disjoint from the
  collection hook W3 changes.
- Sequential single-seat lanes make each of these a catch-up, never a conflict; the board's
  `overlaps:` section is the oracle when seats run again.

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

*Read 2026-10-19 at W1's start (`main` at 3dd2850e):* item 1, a scratch prototype of the detector,
under both unit rules the 0-A weighed, read 31 arming functions in the pre-fix text and exactly
`_ps_body_call_ms` and `_walker_alarmed_ms` unguarded (the real detector re-reads it at 1-C);
item 2, at the head 33 arming (31 in `tests/test_redos.py`, 2 in
`tests/test_speedbump_irreversible.py`), 0 unguarded, no nested def arming, and every guard in its
function's own body before the first arm; item 3, the only open pull request is #327
(`docs/external/` only) and no live claim names the file. Build.

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
   would be born red; file the row in-lane, fix it or enter it in W3's roster first, then build.
4. *Oracle:* the required cells' queue time over one day: per `test.yml` run (`gh run list
   --workflow test.yml --limit 50 --json databaseId,createdAt`), the `startedAt` of its `test (3.x)`
   jobs from `gh run view <id> --json jobs` minus the run's `createdAt`; the median and the worst. *Refuting result for a concurrency group:* the advisory leg's self-overlap
   does not move that queue time. *Exit:* the choice is written from the figure, never
   copied from `post-merge.yml` (its "no concurrency group" reason bounds revert suspects for a
   blocking proof and does not apply here): a group with `cancel-in-progress` only if the overlap
   is measured to delay the required cells, else none; the header says which and why. *Corrected
   at W2's 0-A:* the first text's premise (a run of 66 to 172.9 minutes on every merge) was the
   old full leg; the serial leg measured 2:16 and 3:59, so a self-overlap needs two merges within
   about four minutes, and the re-measure "after the leg's first day" is a post-merge follow-up,
   not a build step.

*Read 2026-10-30 and re-read 2026-10-31 at W2's start (`main` at f333e8c9, then 70bc9778):*
item 1, two dispatched runs of the serial files on `windows-latest`, 40402314684 (the job
3 min 59 s, 21:12:04 to 21:16:03Z) and 40828944655 (2 min 16 s, 06:23:51 to 06:26:07Z), both
`success`, both `workflow_dispatch`; the one `bash` datum for `proof_tier.py`'s own serial leg is
win's Git Bash run of that line (note f03c27: 171 s, exit 0, 1274 passed, 870 skipped). Item 2,
`read_post_merge` (`board.py`) and `base_red_after_merge` (`ship.py`) both read `conclusion`, so
the leg stays a sibling workflow. Item 3, both runs green. Item 4, the required cells' queue over
240 jobs (2026-10-18 to 10-29): median 0.2 min, worst 1.7; no concurrency group, and the header
says so. Not refuted: build. `gh workflow list --all` showed no `post-merge-windows` workflow.

**W3-0 (the counted expected failure).**
1. *Oracle:* the operator's word on re-opening `DEF-2025` (a successor row). *Refuting result:*
   no. *Exit:* W3 is not built; the leg stays red on the runners and `TP-703a`'s line names it
   every tick, which is the honest state. (Given 2026-10-19: yes, with the kind changed to a
   non-strict expected failure; recorded in the blueprint.)
2. *Oracle:* each of the class's six node ids over the last ten `portability (macos-latest)`
   runs (`gh run list --workflow portability.yml --limit 60 --json databaseId,conclusion`, then
   `gh run view <id> --log-failed` per red run). *Refuting result:* fewer than 3 of 10 red on
   the anchor test. *Exit:* the flake has moved or faded; re-raise with the count rather than
   mark a test that passes. A sibling node id red on none of the ten leaves the selector's
   reach and the Landing says so; the count is the measurement's, never the pack's. (Read
   2026-10-19 by the dispatcher: of the last ten runs, 8 completed macOS legs, 6 red, all 6 on
   the anchor, 3 of the 6 on the five siblings too: build, with the class. Re-read at W3's
   start, 2026-10-19, over the last ten COMPLETED macOS legs: the anchor red on 8, the four
   `crashed` consumers on 4 or 5 each, `test_no_summary_asked_for_none_and_gets_none` on 2, no
   other test red on any: build, with the class.)
3. *Oracle:* `grep -n 'skipif\|mark.skip\|xfail' tests/conftest.py tests/test_xdist_never_ran.py`
   and `git grep -n xfail -- tests/`. *Refuting result:* a per-platform skip or expected-failure
   convention already exists in the suite (read 2026-10-18: one `skipif(sys.platform != "darwin")`
   in `tests/test_archive_transcripts.py`, no roster; read 2026-10-19: the adopter axes registry
   forbids marks on its proving nodes, and the strict bridge in
   `tests/test_adopter_lifecycle_diagnostics.py` is a per-file decorator, so no roster; W3 reuses
   the bridge's `<row>: <claim>` reason form). *Exit:* if one exists, register there rather than
   add a second.

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
| Converting a self-detecting skipif to a marker drops every filter-less consumer (W3 applies its mark at collection, so every consumer carries it) | `docs/sharp-edges/skipif-to-marker-drops-filterless-consumers.md` |
| The marker taxonomy and `_MARKER_RULES` (the collection hook W3 extends assigns markers today) | `docs/SHARP_EDGES.md` (the `_MARKER_RULES` section); `docs/CONVENTIONS.md` (Marker taxonomy) |
| Classify the surface before measuring it | `memory/classify-the-surface-before-measuring-it.md` |
| 14. Derive the list, don't test a hand-written copy of it | `docs/STANDING_PRINCIPLES.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "SIGALRM thread timeout
method Windows portability leg"` and `... "a known red skipped per platform and counted"`; the
second returned lexical neighbours (hook authoring, the hardlinked clone) rather than an answer,
and no entry on counted platform skips exists, which is part of why W3 writes one down. Re-run
them rather than trusting this list if the pack has been sitting. Re-run at W3's start
(2026-10-19) with hazard words ("a marker added to collected items in the conftest collection
hook, and an expected failure that is non-strict"): the skipif-to-marker note above is the one
that bears; the rest were lexical neighbours.

## Implementation

Every fix below is a **fix shape (untested)** unless marked measured; its refutation is named.
The pack prescribes prose shapes: no fence here is copy-ready, because W1's edit hoists a closure
whose exact lines the lane reads at its head, W2's file does not exist until its Task 0 says so,
and W3's roster is a tuple whose one entry waits on the operator.

### W1 — the alarm-guard contract (`lane/tests-each-sigalrm-arming-function-guards-itself`)

**1-A Hoist the spelling reader.** `tests/test_test_suite_contract.py`'s `spellings(tree)` and
`arms(node, names)` move from inside `_sigalrm_offenders` to module level as `_sigalrm_spellings`
and `_arms_sigalrm`, with `_sigalrm_offenders` calling them; the two existing tests keep every
assertion (`test_every_module_that_arms_sigalrm_declares_the_thread_method`'s floor of two arming
modules included). *Refuted if:* the closures read a variable of the enclosing function other
than their arguments (read them first).

**1-B The detector.** `_sigalrm_unguarded(modules)` returns (every scope under `tests/` that
reads an alarm name, the ones with a read no guard covers), each as `tests/<stem>.py::<qualified
name>`. `_ALARM_NAMES` are the names an alarm reads from `signal` that Windows lacks (`SIGALRM`,
`setitimer`, `getitimer`, `alarm` and the three `ITIMER_*`); a read is a `signal` attribute of one,
under any spelling of the module (`import signal as s` counts), or a `from signal import` of one.
A scope is each def at any depth (`_every_def`) and a module's own statements with its defs'
decorators and defaults (`<module>`). A read is covered when it sits in a branch of an `if` or a
conditional expression that runs only with the alarm (`hasattr(<signal module>, <an alarm
name>)`, a name assigned from one such as `has_alarm`, or an `and` holding one), or follows a
statement of a block around it that leaves quietly without the alarm (`if not ...:` ending in
`return` or a call named `skip`). A mark, an `assert`, a `raise`, a guard in a caller and a guard
after the read do not count, so a helper answers for itself. *Corrected twice.* At W1's 0-A the
authoring text's unit rule was wrong (`_collect_units` folds a nested def into its parent), so the
detector walks every def itself. At W1's review round both reviewers showed the first build's rule,
any `hasattr` call before the first arm, accepting a guard that covers nothing: an `assert`, an
unused flag, and `tests/test_speedbump_irreversible.py::_search_ms` with one `if has_alarm:`
branch dropped; a module-level `from signal import` went unread. The rule became read coverage,
which the tree meets for free and which names exactly the two pre-fix helpers. *Refuted if:* W1-0
item 1 does not read the two pre-fix helpers.

**1-C The test.** `test_every_sigalrm_arming_function_guards_itself` over
`_all_test_dir_modules()`: asserts the detector read alarm names in at least two modules (the
floor that says it is not policing an empty set; `tests/test_redos.py` and
`tests/test_speedbump_irreversible.py` read them today) and that no scope holds an uncovered read,
each offender printed as `path::qualname` beside the guard shapes that count and those that do
not. Its calibration is `TestTheAlarmGuardDetectorReportsBothVerdicts`, beside
`TestTheSigalrmDetectorReportsBothVerdicts`: an unguarded timer and handler reported; an early
quiet exit covers what follows it; the `_search_ms` branch shape reads clean and reds with its
`finally` disarm unbranched; the wrong polarity reds, and the other branch of a negated test does
not; a guarded caller leaves its unguarded helper reported, and an unguarded caller of a guarded
helper is not read; a late guard, an `assert`, a `raise` and a skipif mark each red; a guard on
`SIGTERM` or on another module does not count, while a guard name and another alarm name do; the
aliased spellings; import-time reads (a module-level `from signal import`, a default argument)
red, and a module-level skip covers them; a nested def, a method, an async def and a def under a
module-level `if` are read; a `finally` after a skip inside the `try` is not covered; a call named
`alarm` on another object is not a read. Earned red three ways: those cases; the detector run by
hand over `9c4ca09d^1`'s `tests/test_redos.py` reads the two helpers (recorded in Landing; old
history is absent from a shallow clone, so this is not a test); and the test itself, in situ, reds
naming the helper when `_walker_alarmed_ms`'s guard is removed from the live file, which is then
restored.

**1-D The delete clause.** `_sigalrm_offenders` also counts a unit as arming when its body
deletes a name the timeout plugin's signal method reads: `<x>.delattr(<signal spelling>, <name>,
...)` (a fixture's `monkeypatch.delattr`, or the builtin), `<x>.delattr("signal.<name>")`, or
`del <signal spelling>.<name>`, where `<name>` is any non-constant expression or a constant among
the names `pytest_timeout`'s own source reads from `signal`, derived from the installed plugin (at
2.4.0: `SIGALRM`, `setitimer`, `ITIMER_REAL`, `SIG_DFL` and `signal`; a floor of `SIGALRM` and
`setitimer` says the derivation read the plugin). The module that holds the unit, and through the
existing importer arm every module that imports it, must then carry the thread method. The word
filter that decides which modules are parsed gains `delattr`, the derived names, and the one
spelling with none of them (`del <alias>.signal`). The real instance today,
`tests/test_redos.py::test_the_walker_and_ps_body_timers_skip_on_a_host_without_sigalrm`, loops
`for name in ("SIGALRM", "setitimer", "ITIMER_REAL")` into `monkeypatch.delattr(signal, name,
raising=False)`, so a literal-only match is blind to the likeliest copy source. A module pytest
never collects (its name matches neither `test_*.py` nor `*_test.py`: the `_*.py` helpers) is no
longer asked for a `pytestmark` of its own, since a mark there applies to no test (a scratch run
read none from `conftest.py`), and `tests/conftest.py`'s line says so and asks for the arm to move
into the test module that needs it. Earned red: a must-trip fixture copied from that loop under
no `pytestmark`, the literal form, the string form, an aliased module, and a helper that deletes
beside an unmarked importer (the importer flagged, the helper not). *Corrected at W1's 0-A:* as
first written the clause counted the module, so a marked helper beside an unmarked importer read
clean (a scratch run), and only `"SIGALRM"` was a constant, while the cancel reads four more
names. *Premise, re-read at W1's 0-A* (installed pytest-timeout 2.4.0; `pyproject.toml` pins only
a floor, `>=2.1.0`): `pytest_timeout_set_timer`'s `cancel()` reads `signal.setitimer`,
`signal.ITIMER_REAL`, `signal.signal`, `signal.SIGALRM` and `signal.SIG_DFL` unguarded, and
`pytest_exception_interact` runs it after a failing call phase, before teardown restores a deleted
name. On a scratch run under the signal method, a failing test with `SIGALRM` deleted ended the
session in an INTERNALERROR (one test reported of three); under the thread method it was a plain
failure. *Refuted if:* a later plugin guards its cancel (1-D is then dropped and the row's text
corrected at the strike). *Changed at W1's review round:* the importer arm follows a function from
module to module until nothing new arms (a helper that wraps another helper's function asks the
wrapper's importers); a helper that arms or deletes outside a module-level function (under a
module-level or class-level statement), where no importer can be followed, is reported instead of
skipped; each offender's line names the hazard of its kind (a delete: the session ends in
INTERNALERROR); and pyproject's `python_files` is read as a string or a multi-line array, an
unreadable value failing loudly. The calibration adds the keyword `target=`, the tuple `del`, a
module-level delete, a non-signal string target, the `*_test.py` default, `conftest.py` importing
a helper, the two-hop wrapper and the def under a module-level `if`; the cases that need a plugin
name skip without pytest-timeout. The imports followed are `_imports_from_tests`' (not a relative
import, `importlib` or `pytest_plugins`).

**1-E Strike `DEF-5024`.** Drive the row's own probe first (`task-packs/probes.d/DEF-5024.json`'s
`cmd`: it reads the contract file for the test's name, an `assert` inside it and the double-quoted
`"hasattr"` string) and record True in Landing: the strike verb never runs it, and deletes the
probe file (corrected 2026-10-25 by the dispatcher: true when W1 struck the row on 2026-10-20;
since `TP-703j` landed as #340 the strike drives the row's probe at the merge-base, where it must
read STILL_OPEN, and at the head, where it must read STRIKE_CANDIDATE, before it retires the
file, so a strike in W2 follows that verb). Then `python3 tools/cc/ledger_row.py strike DEF-5024 --despite-deferrals --text-file
<outside the checkout>`: `TP-703a`'s Scope (out) cites this row as this pack's (Cross-pack
coordination), and the closing text says the deferred work landed here, without naming the loop in
`tests/test_redos.py` as the one permanent instance (`TP-703i` moves it into a helper).

### W2 — the slim Windows leg on `main` (`lane/windows-main-leg`; after W2-0 and the operator)

**2-A `.github/workflows/post-merge-windows.yml`.** `on: push: branches: [main]` and
`workflow_dispatch`; `permissions: contents: read`; the concurrency choice W2-0 item 4 measured
(a group with `cancel-in-progress` only where the leg's self-overlap delayed the required cells,
else none: none, on the 0.2-minute median), never the reason `post-merge.yml` gives, which bounds
revert suspects for a blocking proof and does not apply here; one job on `windows-latest`,
`timeout-minutes` 25: the serial files' longest own timeout mark (900 s, the PowerShell gate's;
a mark outranks the ceiling) plus the ten minutes `tests/test_ci_job_bounds.py` gives the
test-serial cell on top of its worst mark (twice the measured 3:59 would round to ten and cut that
mark with no test named; corrected at the review round from fifteen); a shallow checkout with the
same pinned action versions as `post-merge.yml` (the measured runs were shallow, and no serial
file reads history or tags); Python 3.12; `pip
install -e .[dev]`; `shell: bash` as the portability step runs on every runner (the Windows
default is PowerShell) and `PYTEST_TIMEOUT: "180"` as an `env:` key of the step (the portability
leg exports it under `RUNNER_OS` because its one step runs on three hosts; this job runs on one);
the step runs `python scripts/proof_tier.py --run --tier full --leg serial`, so the file list has
one home, and that line runs under xdist at one worker, where a ceiling crossing names its test
and the controller replaces the worker (`scripts/proof_tier.py`'s own note), so the portability
step's no-summary guard is not copied. The header says in its first lines that it is advisory,
that it is a separate workflow because the proof's readers read a run's conclusion, which
concurrency choice the queue-time figure decided, and that `tools/cc/board.py` reads it through
`tools/cc/_post_merge.py`'s base-run rule. On this repository `.github/workflows/` is CI-gated
(`tools/cc/ci_guard.py`), so the pull request's title carries the approval marker, which
`ship.py open` binds at creation (the workflow file earns it; the two `tools/cc/` modules are
runtime-protected and earn none, and this record must not name the marker beside them). The runner proof is a dispatch of the workflow on the
pushed lane where GitHub takes one for a workflow not yet on the default branch, else the first
push run after the merge, read and recorded in Landing after it. *Corrected at W2's 0-A
(2026-10-31):* the shell, the `env:` key, the floor, the pins, the guard, the marker line and
the runner proof were unnamed. *Refuted if:* `proof_tier.py --run --leg serial` cannot run under
`bash` on the Windows runner (the portability step runs `bash` on every runner;
`scripts/proof_tier.py` is Python and spawns `pytest` by name; W2-0 item 1's dispatch measured
the pytest line under the runner's `bash`, and win's Git Bash run measured `proof_tier.py`'s
serial leg itself).

**2-B The reader.** The rule in `tools/cc/_post_merge.py`, as pure functions, since the module
has no `gh`, no window and no `Unresolvable` (those are `board.py`'s): `base_run_verdict(runs)`
walks a parsed `gh run list` listing newest first, a run that is not completed read as going
(`running` when it is newer than the verdict), `SUCCESS` green, `RUN_RED` (`FAILURE`,
`TIMED_OUT`, `STARTUP_FAILURE`; `board._RED` becomes an alias of it, so the board's pin against
`ship.POST_MERGE_RED` still holds and the set has one home short of the driver's) red, and
cancelled, stale, skipped or neutral walked past as no verdict, as `read_post_merge` does; on a
red it walks on to the streak's first red and the green before it, since "red since" must name
where the streak began, not the newest red. `base_run_lines(state, workflow=..., base=...)`
renders the words: `post-merge-windows (main, advisory): red since <sha> (run <id>)`, then `, still red on
<sha> (run <id>)` when the newest red is a later run, or ` (no green among the runs read)` when
none is in the listing, then `; a newer run is going`; a plain green newest renders nothing (the
`none red` line stands), and completed runs without a verdict newer than a green are named above
it rather than hidden (a hang the job's bound cuts may conclude cancelled on every push; added at
the review round); every completed run without a verdict renders `post-merge-windows (main,
advisory): no verdict on every run read (<kinds>)`; no completed run, and a repository without the workflow
(`absent`), render nothing, so the deployed board is silent on an adopter tree and on this one
until the first push run completes; a failed read renders `post-merge-windows (main, advisory): unread
(<reason>)`. `board_lines` takes the base-run state and prints its lines after the pull-request
legs, with the `none red among the last N merges` line kept off when the base run is red. The
one `gh` call is `tools/cc/board.py::read_base_runs`, made only where the checkout holds the
workflow file (an adopter tree, and this one before the leg lands, spawn nothing and read
`absent`: added at the review round, since any failure but the 404 printed a line for a leg the
tree never had), named by `read_post_merge_checks` beside the section's merged read, under its own
try/except (a not-found text naming the workflow is the
`absent` state, the same rule `read_post_merge` applies to its own, moved to a helper both
share; any other `Unresolvable` is the leg's own `unread` state, never the section's), with the
board's `GH_TIMEOUT` as its budget. The rule's tests run on frozen listings in
`tests/test_post_merge.py::TestTheBaseRunVerdict` (a red newest; a cancelled newest over an
older red; a green newest; a streak walked back to its first red; no green in the window; a
newer run going; every run without a verdict; an empty listing; a row that is not a dict) and
`TestTheBaseRunWords` holds the lines; `tests/test_board.py::TestChecksLine` gains the rendered line on
a red listing with the `main:` line unchanged, the silent cases (green, absent, empty), and the
failed read as its own line with the section still rendered, through the `_gh` stand-in keyed by
the `--workflow` value (the proof's own workflow keeps its key; another workflow answers `[]`
unless the test names it, so every older test stays honest). `.claude/commands/inbox.md`'s
`checks:` bullet gains one adopter-valid sentence in the base bullet's form ("where the
repository runs a workflow named ..."), then `scripts/sync_claude_mirrors.py`;
`scripts/sync_vendor_cc.py` after both module edits, then `espalier integrity refresh .`.
The leg's red is not written to the transitions log, which is keyed by merge (a follow-up,
named in Landing); a dispatched run of the workflow carries `workflow_dispatch` and never clears
the line: the next push run does. The line's shape, the file check and the no-verdict-above-green
line were the review round's (both reviewers, REQUEST CHANGES, one fix batch).
*Corrected at W2's 0-A (2026-10-31):* the first text put the `gh` call, the window and the
`unread` clause in the module, which has none of them; the `absent` state and the streak's first
red were unnamed; the test classes were unnamed. *Refuted if:* `TP-703a` has not merged (it has:
`State: LANDED`, read at W2's 0-A).

**2-C `DEF-977`'s text** gains one sentence at its tail naming the advisory leg and the measured
duration, by `python3 tools/cc/ledger_row.py repin DEF-977 --reason ...`; the row stays open,
since its probe counts Windows jobs that gate a merge and this one gates nothing.

### W3 — the macOS race, counted (`lane/tests-macos-race-rows-run-as-expected-failures`; after the operator re-opens)

Corrected at W3's 0-A (2026-10-19) for the operator's change of kind and the pack-artifact
review's findings: the skip became a non-strict expected failure; the live-row read moved to the
assembled ledger view; the tier is full; the runner proof comes before the merge. Corrected again
by the lane's review round (both reviewers, REQUEST CHANGES, one fix batch): the mark is bounded
to the race's own failure type, not to the error types the race happens to raise; the roster's
counts print on the runners; the hook is held on every host; the runner proof runs before the
pull request opens.

**3-A The row first.** The successor row for `DEF-2025` is filed on the operator's word from the
building seat's block (`tools/cc/ledger_row.py file` with the id left out) before the roster names
it, with the sighting count W3-0 item 2 measured. It declares `--why-not`: the race has never
shown on either box, so a local probe would read the roster, the mitigation, not the race; the
oracle is the crash watch on the runners. The struck row's closing text is not edited.

**3-B The roster.** In `tests/conftest.py`, beside `_FULL_TREE_NODEIDS`, a tuple
`PLATFORM_EXPECTED_FAILURES` of entries (node id or class prefix, platform key, row id, reason,
date), with a comment that says the tuple is a declared population and the contract tests keep
it honest; `_platform_holds(platform, sys_platform, environ)`, a pure function the hook calls
with the live values (`"macos-ci"`: `darwin` and `GITHUB_ACTIONS == "true"`; a truthy `CI` would
fire on `CI=false` and on local tooling that sets it; an unknown key is never true); and
`_expected_failure_mark(entry)`, the one place the mark is built. *Refuted if:* W3-0 item 3 finds
a convention already there.

**3-B' The race's own failure.** `tests/_nested_race.py` holds `NestedControllerRaceLost` (a
subclass of pytest's failure, so the row still fails wherever it is not expected to),
`RACE_RAISE` (`OSError: cannot send (already closed?)`, the last raise every red macOS leg read)
and `lost_to_the_race`. `tests/test_xdist_never_ran.py::_drive_to_a_reading` raises it only where
every attempt's last raise was the race's, and pytest's plain failure otherwise; the conftest's
mark is bounded to it alone. One home, so the mark's `raises` and the driver's `raise` are one
class. A pytest-timeout ceiling, another internal error and an assertion over a child that
completed (`DEF-4033`'s never-ran count, read once) still red the leg.

**3-C The mark.** `pytest_collection_modifyitems` adds the marks
`_expected_failures_for(nodeid, sys.platform, os.environ)` returns: each entry that covers the
node id (its own id, its parametrized instances, or every test under a class prefix) and whose
platform holds; nothing else changes in that hook. The summary then reads `xfailed` for a row
that lost every attempt to the race and `xpassed` for one whose child completed, on the runners
and nowhere else, and `report_platform_expected_failures` prints one line per roster row there,
zeros included (the rows that lost, the rows that completed, the entry's age), with a notice
annotation under GitHub Actions. The crash watch's line names `DEF-4032`.

**3-D The contracts.** In `tests/test_test_suite_contract.py`, through one checker that the live
test and its must-trip siblings share: each entry names a test class or function in its file (an
AST read of the file), its row is live (the id is among
`tools/cc/generate_ledger_regions.py::live_cell_ids` over `tools/cc/_record_fragments.py`'s
assembled ledger view: over a row file alone that reader returns nothing, live or struck, and a
direct read of the row directory is what the record loader's census polices), its date has the
`YYYY-MM-DD` shape, and its mark is exactly the roster's (non-strict, bounded to the race's
failure, run: no `run=False`, which would read every row as lost and the watch as silent), its
reason leading with the row id. Beside it: the predicate's table (`darwin` with `"true"` holds;
`darwin` unset, `darwin` with `"1"`, `linux` with `"true"` and `win32` with `"true"` do not); the
hook itself on the runners and on four other hosts; the bound absorbing the race's failure and
none of pytest's plain failure, an assertion, a hung child's timeout or an ordinary error; the
class derived from the source equals the tests the successor row's entries cover, while the
roster names that row; one platform key until the registry generalizes these contracts; the
summary line; and no other `strict=False` or `**`-splatted expected-failure mark under `tests/`,
the allow-list keyed on a builder's file and name together. Earned red against an entry naming a
test that does not exist, one naming a struck row (`DEF-2025` itself), one naming a row that does
not exist, and mutants of every conftest function; the roster's length is never written anywhere
but derived from it.

**3-E The runner proof, before the pull request.** The pull request's own portability legs
finish after auto-merge, which the ship driver always arms, so the lane is pushed first and the
workflow dispatched on it before the pull request opens: `gh workflow run portability.yml --ref
<lane> -f os=macos-latest -f select="tests/test_xdist_never_ran.py -rfEsxX"` (pytest keeps the
last `-r`, so the flags are combined, never appended). The six must read as `xfailed` plus
`xpassed`, each reason naming the successor row, the roster line printed, and no other test in
the file failed or errored. Measured 2026-10-19: an isolated run does not load the runner enough
for the race (two runs, at one worker and at four, 12 of 12 rows completed; a third was cancelled
by the workflow's concurrency group, so dispatch one at a time), so it shows the mark takes on the
runner and cannot show a loss absorbed. The absorption is shown instead by driving the real
conftest, retry driver and mark under xdist with a child that prints the runners' recorded race
lines (6 `xfailed`, the watch and the roster line counting them; with a crash that is not the
race, 2 failed and 4 errors), and by replaying the driver's race check over the eight red macOS
legs on record (every row that lost three attempts lost each to the race's signature). The first
live reading of a loss absorbed is the pull request's own full macOS leg, read after it
finishes. Then `/ship`. Locally, `GITHUB_ACTIONS=true` meets the predicate on this Mac: the six
read `xpassed` with the reason, and unset they carry no mark.

**3-F Beside the lane.** The lane's own changelog fragment was the first to cite a test file with
no negation word beside it, and the citation sweep's completeness contract redded: both
doc-citation gates now read `changelog.d/` beside `CHANGELOG.md` (all 71 fragments resolve).

## Affected symbols

`/scope-check` keys on bare names. `spellings` and `arms` collide with other test helpers; re-run
it at each wave's start and accept the collision gap by name.

### Changed-semantics
- `tests/test_test_suite_contract.py::_sigalrm_offenders` (calls the hoisted readers; counts a
  module that deletes the name as arming)
- `tests/test_test_suite_contract.py::test_every_module_that_arms_sigalrm_declares_the_thread_method`
  (the delete clause widens what it flags; its assertions are kept)
- `tests/conftest.py::pytest_collection_modifyitems` (W3: applies the roster)
- `tests/conftest.py::report_nested_controller_crashes` (W3: its line names `DEF-4032`)
- `tests/test_xdist_never_ran.py::_drive_to_a_reading` (W3: a row that lost every attempt to the
  race fails as `NestedControllerRaceLost`)
- `tests/test_doc_test_citations.py::_SCAN_GLOBS` and
  `tests/test_doc_source_citations.py::_swept_docs` (W3, 3-F: the changelog's fragments swept)
- `tools/cc/_post_merge.py::board_lines` (W2-B: takes the base-run state and keeps the `none
  red` line off when that run is red; the module is `TP-703a`'s)
- `tools/cc/board.py::collect` (W2-B: passes the base branch to the `checks:` section's read)
- `tools/cc/board.py::read_post_merge_checks` (W2-B: the base-run read joins the `checks:`
  section's read, under its own try/except)
- `tools/cc/board.py::read_post_merge` (W2-B: its not-found test moves to a helper both base
  reads share; its verdict is unchanged)
- `tools/cc/board.py::_RED` (W2-B: an alias of the module's `RUN_RED`)

### Renamed
- None.

### Added-paths
- `tests/test_test_suite_contract.py::_sigalrm_spellings`
- `tests/test_test_suite_contract.py::_arms_sigalrm`
- `tests/test_test_suite_contract.py::_sigalrm_unguarded`
- `tests/test_test_suite_contract.py::test_every_sigalrm_arming_function_guards_itself`
- `tests/test_test_suite_contract.py::test_every_platform_expected_failure_is_a_live_row_over_a_real_test`
- `tests/test_test_suite_contract.py::test_the_race_roster_covers_every_row_whose_child_kills_its_workers_in_the_build`
- `tests/test_test_suite_contract.py::test_no_other_expected_failure_is_non_strict`
- `tests/conftest.py::PLATFORM_EXPECTED_FAILURES`
- `tests/conftest.py::_platform_holds`
- `tests/conftest.py::_expected_failure_mark`
- `tests/conftest.py::_expected_failures_for`
- `tests/conftest.py::report_platform_expected_failures`
- `tests/_nested_race.py`
- `.github/workflows/post-merge-windows.yml`
- `tools/cc/_post_merge.py::RUN_RED`
- `tools/cc/_post_merge.py::WINDOWS_WORKFLOW`
- `tools/cc/_post_merge.py::base_run_verdict`
- `tools/cc/_post_merge.py::base_run_lines`
- `tools/cc/board.py::read_base_runs`
- `tools/cc/board.py::workflow_absent`
- `tests/test_post_merge.py::TestTheBaseRunVerdict`
- `tests/test_post_merge.py::TestTheBaseRunWords`
- `tests/test_ci_job_bounds.py::TestThePostMergeWindowsLegKeepsItsContracts`

### Removed-paths
- None.

## Reach

The pack closes one row and touches two. Members derived by:
`grep -lE 'SIGALRM|portability|windows-latest|macos-latest|xdist_never_ran' task-packs/ledger.d/*.md`
over live and struck rows (re-run it; the rows below are the ones a wave's mechanism reaches).

| Item | Status | Evidence |
|---|---|---|
| `DEF-4034` (the alarm-guard contract judges a guard by its spelling) | **FILED by W1** (its review round) | four shapes, none in the tree; the row's probe is the fix's calibration test |
| `DEF-4035` (the thread-method contract follows an arming import only by name) | **FILED by W1** (its review round); **CLOSED 2026-10-26** (the whole-module branch reads the arming names a module exports, a class arms through its bases; two calibration rows) | a whole-module import of a wrapping helper, and a subclass; none in the tree |
| `DEF-5024` (no check that each `SIGALRM`-arming test function guards itself) | **CLOSED by W1** | the detector reads 2 unguarded on `9c4ca09d^1` and 0 at the head; the must-trip module is flagged; the row's probe prints True; struck in-lane |
| `DEF-977` (no Windows check gates a merge) | **NOT CLOSED**; W2 is its first step and gates nothing | the row's probe (Windows jobs in `test.yml`) still prints 0; the tail sentence names the advisory leg and its measured minutes |
| `DEF-2025` (struck 2026-10-18; the runners' race in the nested child) | **RE-OPENED as a successor row, and its red marked a non-strict expected failure on the runners by W3, counted and still run**, on the operator's word (given 2026-10-19); the successor stays live while the race stands | the roster's entries; the contract tests; the crash watch; the leg's green rate (the roadmap's line 2) |
| `DEF-5023` (the walker row's warm call under its alarm) | **NOT REACHED** | its own row; W1 guards the function, not the budget |
| `DEF-2023` (a per-worker build report file) | **NOT REACHED** | named in `DEF-2025`'s fix shape; not this pack's |

## Pass criteria

- W1: `pytest tests/test_test_suite_contract.py -q` green at the head; the detector, run by hand
  over the text of `9c4ca09d^1:tests/test_redos.py`, reads exactly the two helpers (recorded in
  Landing); the new test reds in situ with a helper's guard removed, and each must-trip case of
  1-C and 1-D reds against its mutation; no assertion in
  `test_every_module_that_arms_sigalrm_declares_the_thread_method` or
  `test_no_engine_or_hook_module_arms_sigalrm` is weakened and no floor lowered; `DEF-5024`'s
  probe prints True before the strike (recorded in Landing) and the row is struck.
- W2: the measured duration of the dispatched serial run on `windows-latest` is in this file's
  Landing before the workflow exists; the workflow's `timeout-minutes` is at least twice it and
  outlasts the serial files' longest own timeout mark by ten minutes, and the leg's contracts
  are pinned in `tests/test_ci_job_bounds.py` (the file, the push trigger, no
  `continue-on-error`, no Windows job in `post-merge.yml`, the ceiling equal to the portability
  leg's, the bound); `tools/cc/board.py` names the leg's red on the `checks:` line through 2-B's
  rule (the frozen listings' cases pass, a push run appearing in no merged pull request's rollup)
  and never on the `main:` line, and prints nothing for it on a green leg, an absent workflow or
  an empty listing; `tools/cc/board.py::read_post_merge`'s verdict is unchanged by any run of it
  (its tests pass unchanged); the concurrency choice in the header names the queue-time figure
  that decided it; the pull request's title carries the approval marker. A push to `main`
  running the workflow, and the board naming a live red, are manual smokes (a green tree has no
  red to show): the first push run after the merge is read and recorded in Landing, and the
  `checks:` line is read on the next board tick.
- W3: before the pull request opens, the dispatched macOS run (3-E) reads the six marked, each
  reason carrying the successor row's id, the roster line printed, and nothing else in the file
  failed; a loss is shown absorbed by 3-E's end-to-end drive and replay, and live on the pull
  request's own macOS leg; on this Mac with `GITHUB_ACTIONS=true` the six
  read `xpassed` with that reason, and unset they carry no mark; the predicate's table and the
  hook hold on every host; the bound absorbs the race's failure and nothing else; the contract reds
  on a roster entry naming a missing test, on one naming a row that does not exist, and on one
  naming a struck row; the derived class equals the roster's coverage; no other non-strict mark
  exists under `tests/`; the roster's count appears in no prose.
- Earn-the-red recorded per fix against the mutation named in Implementation; a test that only
  ever passed does not count.
- The tier each lane earns is run with `--base origin/main` and its receipt is in the pull
  request body: W1 is tests-only (the contract slice, by the rule `scripts/proof_tier.py`
  prints); W3 edits `tests/conftest.py`, which the tier script reads as suite config, so it earns
  the full tier and the code reviewer; W2 is a CI definition and earns both reviewers.
- No criterion here licenses shipping a defect in a gate the pack delivers: a detector that reads
  a guard in a sibling function as the arming function's own, or an expected-failure mark that
  fires off the runners or absorbs an error that is not the race's, is a defect of this pack, not
  a scope-out.

## Files touched

**New:** `.github/workflows/post-merge-windows.yml` (W2, after its Task 0 and the operator);
`tests/_nested_race.py` (W3, the race's own failure type); a changelog fragment each (W1, W3).

**Modified:** `tests/test_test_suite_contract.py` (W1, W3); `tests/conftest.py` (W3);
`tests/test_xdist_never_ran.py` (W3: the driver raises the race's failure, the watch's label);
`tests/test_doc_test_citations.py` and `tests/test_doc_source_citations.py` (W3, 3-F);
`task-packs/TP-703-multi-seat-discipline.md` and `task-packs/TP-703h-host-expectations-have-one-registry.md`
(W3: the decision recorded, and a pointer where the registry's text predates it);
`tools/cc/_post_merge.py` and `tools/cc/board.py`, each with its vendored twin by
`scripts/sync_vendor_cc.py` (W2-B); `tests/test_post_merge.py` (W2-B); `tests/test_board.py`
(W2-B, the rendered line); `.claude/commands/inbox.md` and its two mirrors by
`scripts/sync_claude_mirrors.py` (W2-B, the `checks:` bullet's sentence); the integrity manifest
(W2-B, refreshed, per-install); `task-packs/ledger.d/DEF-5024.md` (struck by the verb, W1); `docs/CONVENTIONS.md` (W1: the
wait-budget bullet names the read-coverage rule and the delete clause); `tests/README.md` and one
docstring of `tests/test_redos.py` (W1: the thread-method sentence, and the pointer to the gate);
`task-packs/TP-703-multi-seat-discipline.md`'s Children line (W1, W2);
`task-packs/ledger.d/DEF-977.md` (repinned by the verb, W2); two new row files under
`task-packs/ledger.d/` and their probe files under `task-packs/probes.d/` (W3, by the verb:
`DEF-4032`, `DEF-2025`'s successor, on the operator's word; `DEF-4033`, the completed-child
count the review round split out).

**Deleted:** `task-packs/probes.d/DEF-5024.json` (W1, by the strike verb).

**Unmodified on purpose:** `.github/workflows/post-merge.yml` (the proof's verdict is the
revert trigger and stays one job); `.github/workflows/portability.yml` (`TP-703a` corrects its
header; its legs stay as they are); `tests/test_redos.py`'s code (already guarded by #320; W1 changes one docstring);
`scripts/proof_tier.py::SERIAL_FILES` (the one home W2 reads). The six rows of
`tests/test_xdist_never_ran.py` carry no mark in the file: the mark is applied at collection.

## Sub-task ordering

1. **W1-0, then W1** (1-A, 1-B, 1-C, 1-D, 1-E): the smallest change and the one that needs no
   decision. Checkpoint: the contract slice, the red on `9c4ca09d^1`, the strike.
2. **W2-0 item 1**, the dispatched measurement, by the dispatcher or the assigned seat at any
   time; its figure goes to the operator with `DEF-977`'s question. **W2** only on the operator's
   word and after `TP-703a` merges. Checkpoint: a `main` push runs the workflow; the board names
   it on `checks:`.
3. **W3-0 items 1 and 2**, then **W3** only on the operator's re-open and after `TP-703a` merges.
   Checkpoint: the successor row, the roster, the contract tests' reds, the dispatched macOS run.
4. **Red-team each wave** before its tier, the reviewers its diff earns on a snapshot clone.
   W1's diff is tests and records, so the tier's `review:` line reads `none`; it ships a gate, so a
   code-reviewer and a failure-mode-reviewer read it anyway (added at W1's 0-A), and the contract
   file runs once through `scripts/archive_probe.py` (`tests/CLAUDE.md` rule 5: the new test
   asserts a population of the tree).
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
| W1 | 3 to 4 h (re-estimated at its 0-A) | 1 h plus the contract slice, two reviewers and the archive probe | a hoist, a detector, the delete clause at unit level, two calibration classes, a strike |
| W2 | about 2 h after a 1 to 2 h dispatched run (re-estimated at its 0-A from 1 h) | 1 h plus the full tier | a workflow, a reader with four frozen cases, the board line, tests in two files, two mirrors, a repin; the operator's call first |
| W3 | 1.5 to 2 h | 0.5 h plus the full tier and a dispatched macOS run | a roster, a hook change, contract tests, a row by the verb |
| Total | 5.5 to 7 h | 2.5 h | expect the measured overrun |

## Landing
- State: LANDED
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
- W2-0 measured duration of the serial files on `windows-latest`: 3 min 59 s (run 40402314684,
  2026-10-29) and 2 min 16 s (run 40828944655, 2026-10-30), both dispatched through
  `portability.yml`'s selection input, both green; the analysis's "about ten minutes" was
  unmeasured and high
- Corrected 2026-10-19 before any assign (the dispatcher's lane
  `lane/packs-the-tp-703-children-corrected-before-wave`): the macOS red is one mechanism over
  six node ids, not one test; Motivation, W3 and W3-0 item 2 carry the measurement and the
  class-sized roster
- Corrected 2026-10-25 (the dispatcher, after `TP-703j` landed as #340): 1-E's "the strike verb
  never runs it" held when W1 struck `DEF-5024` on 2026-10-20 and is false since; the step's text
  stands as the record of what ran, with the dated note beside it
- W2 landed 2026-10-31, single-seat (air-work, under the dispatcher's assign by lane, on the
  operator's call read through the dispatcher after the measured leg), on `lane/windows-main-leg`;
  with W1 and W3 landed the pack is LANDED and stays in `task-packs/` until the roadmap lands, as
  `TP-703a` does:
  - Commits: the lane's commit (its pull request names it).
  - Task 0: W2-0's four items, read above (both dispatched runs green at 3:59 and 2:16; both
    base-run readers read `conclusion`; the queue median 0.2 min): build.
  - 0-A (2026-10-31, `main` at f333e8c9): code-reviewer, Pack-artifact review checklist v2,
    REQUEST CHANGES (0 BLOCK, 10 WARN, 5 NIT), folded before any code (the reader as pure
    functions, `read_post_merge_checks` named, the `absent` state, the streak's first red, the
    shell and the `env:` key, the floor, the mirrors, the marker line, the realism of the live
    red); fence check 0 fences (prose shapes); 0-B, 0-C and 0-D accepted with written reasons.
  - Earn-the-red: 11 named mutants on the first build on a snapshot clone, each killed by its
    named test (one first written as an equivalent mutant, `frozenset` of a frozenset, re-run as a
    literal copy and killed); 15 of 15 after the review round (the checkout's file check, the
    no-verdict-above-green line, the stem match on the cut 404 text and the base read among them).
  - Red-team: code-reviewer REQUEST CHANGES (0 BLOCK, 3 WARN, 6 NIT) and failure-mode-reviewer
    REQUEST CHANGES (0 REGRESSION, 5 GAP, 8 ROUGH-EDGE), both on a snapshot clone with its own
    venv; one fix batch: the bound at 25 (the serial files' 900 s mark plus ten, where fifteen
    sat at the PowerShell gate's own mark and under five worker restarts), the read made only
    where the checkout holds the workflow file (any failure but the 404 printed a line on every
    adopter board), the stem match on gh's cut 404 text, the line in the legs' shape with the base
    and `advisory` in its name (never `main:`, the revert rule's label), newer no-verdict runs
    named above a green (a hang the bound cuts may conclude cancelled on every push), the
    completed-only count, the no-green wording, the base-branch board test, the shallow checkout
    and the measured-as wording, the leg's contract tests, the inbox and pack folds. Named here
    as follow-ups for the dispatcher, not built: the leg's red into the transitions log (keyed by
    merge); what GitHub concludes for a job cut by `timeout-minutes` (one dispatched run with a
    short bound, after the merge: a `cancelled` there is read as no verdict by both base-run
    readers); the ship driver's literal red set and the parity test's hand list of sets
    (`ship.py` is the next job's file); the queue re-measure after the leg's first day, whose
    thresholds the header pre-registers.
  - Suite (`scripts/proof_tier.py --run`, the full tier on the uncommitted lane, after the last
    code edit): mypy and ruff clean; the parallel leg 25,362 passed, 101 skipped, 3 xfailed,
    1 failed in 26:33 (this record's own text, which spelled the approval marker beside the two
    runtime-only module names; corrected after the run, and
    `tests/test_protected_path_contract_parity.py` re-run green); the serial leg 2,135 passed,
    9 skipped in 4:33.
  - Runner proof: the first push run after the merge, read and recorded by the session that reads
    it (`gh run list --workflow post-merge-windows.yml --branch main --event push --limit 1`), and
    the board's `checks:` line on the next tick; a dispatch of the workflow on the pushed lane was
    not attempted (a workflow not yet on the default branch).
  - Reach: `DEF-977` repinned (a tail sentence naming the leg and its measured minutes); it stays
    open, since its probe counts Windows jobs that gate a merge.
- W3 landed 2026-10-19, single-seat, on `lane/tests-macos-race-rows-run-as-expected-failures`;
  the pack stayed DRAFT while W1 and W2 were open:
  - Commits: the lane's commit (its pull request names it).
  - Task 0: item 1 the operator's word, yes, with the kind changed to a non-strict expected
    failure; item 2 the anchor red on 8 of the last ten completed macOS legs, the four `crashed`
    consumers on 4 or 5, `no_summary` on 2, nothing else red: build, with the class; item 3 no
    roster convention to register in.
  - 0-A: code-reviewer, Pack-artifact review checklist v2, REQUEST CHANGES (1 BLOCK, the
    live-row reader read a row file alone; WARNs), folded before any code; fence check 0 fences
    (prose shapes); 0-B, 0-C and 0-D exit 2, each accepted with a written reason.
  - Earn-the-red: 19 mutants of the conftest, the driver and the race module, each killed by the
    named tests; the checker's must-trip rows; a scratch pytest 9.1.1 run of the mark over a
    module fixture's failure at setup, a body failure, an assertion, a `TypeError` and a pass,
    with and without `-n 1`.
  - Red-team: code-reviewer REQUEST CHANGES (1 BLOCK, 2 WARN, 7 NIT) and failure-mode-reviewer
    REQUEST CHANGES (4 GAP, 3 ROUGH-EDGE, 0 REGRESSION), both on a snapshot clone; one fix batch:
    the race's own failure type, the hook held on every host, the mark pinned to run, the roster
    line, the watch's label, the parametrized boundary, the co-id-aware reader, the date shape,
    the figures, `DEF-4033` split out, the changelog sweep, the TP-703h pointer, the proof before
    the pull request. Declined: a contract that reds once the roster's date passes a grace (a
    dated red in every tier is friction; the roster line prints the entry's age).
  - Suite: the contract slice after the batch, 5413 passed with one known box-local red
    (`tests/test_record_merge.py`, Apple git 2.39.5's `update-index --unresolve`); the first full
    tier after the batch red on that and on one summary test this lane's roster line moved on a
    darwin host, fixed by printing the line only where the rows ran; the second full tier
    (`scripts/proof_tier.py --run`, the uncommitted lane): mypy and ruff clean, the parallel leg
    24,763 passed with the same one known box-local red, the serial leg 2,134 passed.
  - Runner proof, before the pull request: portability runs 39344647007 (one worker) and
    39344849177 (four workers), dispatched on the pushed lane with `-rfEsxX`: the six marked on
    the runner with the successor row's reason, 12 of 12 completed (an isolated run does not load
    the runner enough for the race), the roster line printed, nothing else in the file failed.
    Absorption: the end-to-end drive under xdist read 6 `xfailed` on the recorded race lines and
    2 failed and 4 errors on a crash that is not the race; the replay over the eight recorded red
    legs read every three-attempt loss as the race. The first live reading of a loss absorbed is
    the pull request's own macOS leg.
  - Reach: `DEF-2025` re-opened as `DEF-4032` (live; it closes when the watch reads zero crashed
    children and the roster line every row completed over 30 macOS legs, in the lane that removes
    the entries); `DEF-4033` filed (a completed child's never-ran count, read once).
- W1 landed 2026-10-20, single-seat, on `lane/tests-each-sigalrm-arming-function-guards-itself`;
  the pack stays DRAFT while W2 is open:
  - Commits: the lane's commit (its pull request names it).
  - Suite (`scripts/proof_tier.py --run`, the contract tier, after the last edit): ruff clean;
    the contract slice 5,448 passed, 1 failed (the known box-local record-merge test, Apple git
    2.39.5's `update-index --unresolve`); the contract file 206 passed; `tests/test_redos.py` at
    one worker 955 passed; the contract file in an extracted release archive 206 passed.
  - 0-A (2026-10-19, `main` at 3dd2850e): code-reviewer, Pack-artifact review checklist v2,
    REQUEST CHANGES (0 BLOCK, 4 WARN, 13 NIT), folded before any code: the strike's deferral
    refusal (1-E), the delete clause at unit level with the helper carve-out and the plugin's
    five names (1-D), 1-B's unit rule, the pass criteria's hand run, the files and the effort;
    fence check 0 fences (prose shapes). Out of W1: W2-B edits deployed files (Cross-pack).
  - Task 0: item 1, the detector run by hand over `9c4ca09d^1:tests/test_redos.py` named exactly
    `_ps_body_call_ms` and `_walker_alarmed_ms`; item 2, at the head 33 scopes read, 0 flagged;
    item 3, no other lane in the file. Build.
  - Earn-the-red, first build: in situ the contract named `_walker_alarmed_ms` with its guard
    removed (the file restored identical); the delete clause's 11 cases red against the code
    before it; 20 of 20 named mutants killed; the contract file 194 passed here and in an
    extracted release archive.
  - Red-team: code-reviewer REQUEST CHANGES (0 BLOCK, 2 WARN, 13 NIT) and failure-mode-reviewer
    REQUEST CHANGES (0 REGRESSION, 3 GAP, 4 ROUGH-EDGE), both on a snapshot clone. One fix
    batch: read coverage in place of a guard's position (1-B), import-time reads, the importer
    arm followed module to module and an unfollowed helper reported (1-D), the hazard per kind,
    the plugin-dependent cases skipped without the plugin, `python_files` read loudly, the docs
    and this record. Declined: pinning pytest-timeout or a fallback name set (a respelled plugin
    reds the floor test, the signal wanted); the `pyproject.toml` comment (incomplete, not wrong,
    and an edit there earns both reviewers).
  - Earn-the-red, the review round's code: 37 of 37 named mutants killed by their named tests;
    in situ the contract named `_walker_alarmed_ms` with its guard removed and
    `tests/test_speedbump_irreversible.py::_search_ms` with its `finally` disarm unbranched (both
    restored identical); the detector over the pre-fix text named exactly the two helpers;
    `DEF-5024`'s probe printed True through the checker's own runner before the strike.
  - Second red-team round: failure-mode-reviewer on the refreshed clone, APPROVE with notes
    (1 REGRESSION, against the first build's draft and not `main`; 4 GAP; 1 ROUGH-EDGE; each a
    shape not in the tree, and each false green falls back to the Windows leg). Filed as
    `DEF-4034` (the guard judged by its spelling) and `DEF-4035` (import following past a
    whole-module import); the failure message and `docs/CONVENTIONS.md` name the safe spellings
    meanwhile.
  - Reach: `DEF-5024` struck (`--despite-deferrals`, for `TP-703a`'s Scope (out) line);
    `DEF-4034` and `DEF-4035` filed, both probes driven open at filing.
- Date: 2026-10-18 (authored, local)
