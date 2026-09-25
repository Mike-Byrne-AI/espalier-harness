# Espalier-Harness Test Suite

Espalier-Harness is a repo governance harness. Its tests are larger and more
adversarial than a typical CLI project because they prove load-bearing
properties: bypass resistance, hook behavior, kill-switch detection,
source-vs-wheel parity, release artifact cleanliness, public surface
truth, and self-hosting docs/code alignment.

## Markers

The suite is sliced by `pytest` markers (declared in `pyproject.toml`,
assigned in `conftest.py` based on filename patterns):

Five **primary** markers — exactly one per file, saying what KIND of test it is:

- `unit` — pure function/model tests; fast, hermetic. The **"no subprocess"**
  half is mechanically enforced. The **"no filesystem-heavy work"** half is
  enforced only where a module declares its own heaviness — see **What keeps
  `unit` honest** below, which states plainly what is and is not covered.
- `integration` — subprocess, CLI, hook, filesystem, or rendered-surface tests.
- `contract` — self-hosting, docs, generated-surface, public-claim truth tests.
- `security` — bypass, write-guard, plan-guard, kill-switch, enforcement regression tests.
- `release` — packaging, artifact parity, version, benchmark, release-readiness tests.

Three **additive overlays** — stacked on top of the primary marker, saying what a
test COSTS rather than what it is. The two axes are independent, which is why a
fast `integration` module still runs in the `not slow` slice:

- `slow` — builds wheels, runs heavy subprocesses, does git-heavy work, or walks
  the live tree in-process. Declared per file in `tests/conftest.py::_SLOW_FILES`
  **or** per test with an inline `@pytest.mark.slow`; both count.
- `heavy_e2e` — multi-minute end-to-end stages that spawn the suite as a child.
- `full_tree` — asserts full-dev-tree invariants; auto-skipped on a release export.

### What keeps `unit` honest

`unit`'s description is a contract, not a hope. Two structural gates in
`tests/test_test_suite_contract.py` enforce it, and both derive their own
populations rather than checking a hand-written copy:

- `test_no_unit_module_spawns_a_child_process` — clause 1 ("no subprocess").
  Resolution goes through `tests/conftest.py::_primary_marker`, the same
  function the collection hook calls, so the gate cannot answer a question the
  live dispatch would answer differently. It has **no opt-out hatch**: if the
  module really spawns a child, `integration` is the honest label.
- `test_every_self_declared_slow_site_is_slow_or_exempt` — clause 2 ("no
  filesystem-heavy work"), **partially**. A site that raises its own
  `pytest.mark.timeout` above pyproject's global ceiling has declared itself
  heavy in its own source, and must then be marked `slow` at one of the two
  granularities or carry a `# timeout-exempt: <reason>` saying why the raised
  bound is headroom. That marker is deliberately **not** `# slow-exempt:` —
  that one answers "is the child process cheap", which is a different question,
  and reusing it would pre-forgive every module already carrying it.
  **Read the limit honestly:** this enforces *self-declared-heavy ⇒ marked
  slow*, which is strictly weaker than *`unit` ⇒ not filesystem-heavy*. A module
  that walks the tree in-process for a minute and never raises its timeout
  passes every gate here. `test_derived_population_census` was findable only
  because its author happened to write `timeout(300)`; had they written `60`,
  nothing in this file would have seen it. Clause 2 has a floor, not a fence.

**Neither asserts a wall-clock number, deliberately.** Perf budgets measured in
wall time false-fail on scheduler wait rather than on a real regression (see the
xdist-safety table below), and a gate that reds for load is one the reader learns
to skip. Both gates ask the source what it declared instead of timing anything.

To opt a file out of deliberate classification, add `# pytest-marker:
default-unit` as a real comment — `tests/test_marker_taxonomy.py` reads it with
the tokenizer, so the same text inside a docstring does **not** count, and a file
already named in `_MARKER_RULES` may not also carry it.

Marker assignment is centralized in `tests/conftest.py::pytest_collection_modifyitems`.
Files not matching any pattern default to `unit`. The `slow` marker is
additive — it's added on top of the file's primary marker for known
heavyweight files.

## Running slices

```bash
# cheapest precursor — hermetic, no subprocess, seconds not minutes:
python -m pytest -m unit

# fast local loop (everything except slow):
python -m pytest -m "not slow"

# per-batch truth tier (self-host): the tree-wide contracts -- enumerations,
# mirrors, citations, doc claims, census, scanners. Measured 2026-09-06:
# 2,834 tests, 164 s serial. Run it serially; its `-n auto` form (62 s)
# raced on the live tree three times in one run.
python -m pytest -m contract

# release confidence:
python -m pytest -m "contract or release or security"

# pre-merge gate (if you touched hooks or guards):
python -m pytest -m security

# packaging confidence (if you touched the release surface):
python -m pytest -m release
```

**CI mirrors this split** (PERF-2; retiered 2026-09-25): the `test` job runs,
in every cell of the five-interpreter matrix, the proof tier the pull request
earns (`scripts/proof_tier.py --base`, the same rule as the local run): the
contract slice plus any changed test files for a docs, tests or scripts change;
that plus the recall files for a corpus change; the full parallel tier for an
engine, hook, workflow, suite-config or shared-helper change. The
`clean-checkout` (tagless clone) job runs the full tier in a different
environment on full-tier pull requests only, across the same five interpreters.
Nothing runs on a push to `main`: the pull request's merge result is what was
tested. The
`portability` (cross-OS) job lives in its own workflow
(`.github/workflows/portability.yml`) and runs the suite minus the `heavy_e2e`
stages on ubuntu, macOS and Windows whenever Python or packaging source
changes, and on demand (those stages' answer does not vary by host OS, and the
two ubuntu matrices already run them). The full cross-OS release matrix
(`release.yml`) runs only at release/tag time.

One further job exists purely for *selection*: **`ripgrep-parity`** installs
ripgrep and is the only environment in which the `shutil.which("rg")`-gated
tests in `tests/test_scope_walker.py` execute at all. Before it existed no
workflow installed `rg`, so the rg-vs-python parity those tests assert had
never run anywhere — while `walk_references(..., use_ripgrep=True)` is the
default path, reached from shipped code by `espalier scope-check`. It is
deliberately not folded into `test` (a five-interpreter matrix, when this is
about two search backends agreeing) or `clean-checkout` (which exists to
reproduce a fresh contributor clone — one that does not have `rg`).

### Which tests are selected at all

The paragraph above says which *slice* runs in which job. This says which
tests are *selected*, which is a different question and was recorded nowhere
until 2026-08-02 — that gap is how a group of structurally unreachable tests
survived eight review rounds. A green run says nothing about a test that never
ran, and a skip reads as "environment-conditional, fine" whether or not it is.

Every skip that fires belongs to exactly one of these classes:

| Class | Reachable where | Example |
|---|---|---|
| interpreter-gated | another Python leg of the `test` matrix | `tests/test_assets.py` |
| tool-gated | the single job that installs the tool | `tests/test_scope_walker.py` → `ripgrep-parity` |
| session-state-gated | when a live state flag is present; each has an **unconditional twin** carrying the actual contract | `tests/test_state_file_flag_parity.py` |
| deliberate | nowhere, on purpose — a documented archeology skip whose load moved elsewhere | `tests/test_corpus_count_parity.py` |
| **dead** | **nowhere, by accident** | none — drain it or delete it |

The last row must stay empty. A test that can never *not* skip is not
coverage, it is a comment. Two mechanical tells: a `skipif` on a tool no
workflow installs, and a fixture path under a gitignored prefix.

**The trap this section exists to expose: the local suite and the CI suite
skip different sets.** Several tests are gated on paths that are present on a
contributor's working tree but gitignored, so they are absent in every CI
checkout — `tests/test_forward_ledger_completeness.py`,
`tests/test_handoff_truth.py`, `tests/test_manifest_truth.py`,
`tests/test_surface_contract.py`. These **run locally and skip in CI**, which
means a local green run cannot observe the gap and a CI green run cannot
observe the coverage. Neither environment sees the whole picture, so when you
add a test gated on a gitignored path, say so in its skip reason — that string
is the only place the distinction is visible.

Counts are deliberately absent here; see *Why no exact test count is
documented* below. The classification is the durable part.

## Parallel runs (optional)

`pytest-xdist` is an optional dev dependency. To parallelize the fast slice:

    pytest -n auto -m "not slow" \
        --ignore=tests/test_redos.py \
        --ignore=tests/test_speedbump_irreversible.py \
        --ignore=tests/test_hooks.py \
        --ignore=tests/test_documented_claims.py

`-n auto` uses one worker per CPU (`os.cpu_count()` when psutil is absent, so 8
on the self-host Air). `PYTEST_XDIST_AUTO_NUM_WORKERS=<n>` in the environment
caps it without touching any command line; the Air runs 4 (measured 2026-09-10
with VS Code and one Claude Code session open: 9:32 at 4 workers against 15:22
at 2, Python RSS peaking at 1.8 GB across the workers and their children, swap
flat; 8 workers was killed by memory pressure in 3 of 7 runs). Three of the four `--ignore`d files hold
**wall-clock-budget** perf tests (`signal.setitimer` + `elapsed_ms < 100ms`):
under `-n auto` the box is oversubscribed (~5–6× CPU), so a regex that costs a
few ms of CPU can exceed the 100 ms *wall* budget purely from scheduler wait
and false-fail. They pass serially; run them in the normal serial loop. The
ceilings they assert follow one rule since 2026-09-24 (`DEF-922`): a named
constant no less than **ten times** a named, dated floor -- the slowest row's
timed window, the minimum of three serial passes on the self-host box --
because a shared ubuntu runner reads about 1.65x this box on ordinary rows
and over 3x on one (Release CI `35932546999` and CI `35954967897`,
2026-09-23/24); `tests/test_redos.py`'s constants block states the rule and
`tests/test_proof_tier.py::test_every_wall_clock_ceiling_is_ten_times_a_dated_floor`
derives every bound in the three files and reds on a literal, an unpaired
ceiling, or one under ten times its floor. With
those four excluded, the parallel fast slice is fully green (measured: 3120
passed under `-n auto`). **Not enabled in CI** — see the xdist-safety audit
below (owed by TP-223 D). Shared session/module fixtures such as
`initialized_repo_root` and `_built_sdist`, plus tests that read the live
`bench/RESULTS.md`, can erode the speedup or collide across workers. Run
serially in CI until that audit's go/no-go clears the full-suite flip.

To run the slow lane while skipping the single multi-minute end-to-end stage:

    pytest -m "slow and not heavy_e2e"

### xdist-safety audit (TP-223 D)

Walk of the shared-state surface, scoped to the documented fast-slice
parallel command `pytest -n auto -m "not slow"`. Verdicts are grounded against
`tests/conftest.py` and a repo-wide grep of `bench/RESULTS.md` /
`os.chdir` / `monkeypatch.chdir`.

| Surface | Mechanism | Verdict under `-n auto` |
|---|---|---|
| `_isolate_maintenance_mode` (autouse) | per-test `monkeypatch.delenv` | **Safe** — per-test, no shared path |
| `_isolate_audit_dir` (autouse) | per-test `monkeypatch.setenv` → `tmp_path/audit` | **Safe** — each worker gets its own tmp |
| `initialized_repo_root` (session) | clones REPO_ROOT into `tmp_path_factory.mktemp` + runs `init` | **Safe but costly** — each worker re-runs the session fixture (N clones + N `init`s); correctness-clean, erodes speedup |
| `_built_sdist` (module, `test_wheel_payload.py`) | one `build --sdist` per module | **Safe but costly** — rebuilt once per worker; same multiplication caveat |
| live `bench/RESULTS.md` | only `test_update_canonical_refuses_write_on_regression` invokes `--update-canonical`, and it asserts the file is *untouched* on a regression | **Safe for the fast slice** — that test is now `slow` (TP-223 A), so `-m "not slow"` never collects it; no fast-slice test mutates the live file (`test_fuse` writes only to a `tmp_path/out` tree) |
| cwd | `test_execution_plan_cli.py` uses `monkeypatch.chdir(tmp_path)` (auto-restore); `test_init_upgrade_paths.py` uses `os.chdir` with explicit restore to `orig_cwd`, both into tmp dirs | **Safe** — xdist workers are separate processes (cwd is per-worker), and every chdir restores |
| `legacy_pathlib_probes()` (`tests/_legacy_pathlib.py`) | swaps four probe bodies onto `pathlib.Path` for the duration of a `with` block, restoring in `finally` | **Safe** — xdist workers are separate processes, so the patch cannot reach a sibling test. **NOT thread-safe**: these are process-globals, so a thread-parallel runner (`pytest-run-parallel`, not xdist) would race. Also note the patch is live for anything executing inside the block, so keep the block tight around the call under test |
| wall-clock perf budgets (`test_redos.py`, `test_speedbump_irreversible.py`, `test_hooks.py`; `test_documented_claims.py` is `--ignore`d too but **verified 2026-08-24 to hold no elapsed assertion any more** — its carve-out is now unexamined rather than justified, and is kept only because nobody has measured what removing it costs) | `signal.setitimer` + `elapsed_ms < <ceiling>` measure **wall** time, not CPU time; every ceiling is a named constant at ten times a dated floor (`DEF-922`, the rule above) | **False-fails under `-n auto`** — CPU oversubscription inflates wall-time past the budget (observed: a 5 ms-CPU regex hit 100.6 ms wall). Pass serially. Must be `--ignore`d from the parallel command or run serially; correctness is unaffected (no shared state) |

**Go/no-go for the CI flip (open decision — no pack owns this; see the ledger row):**
- **`-n auto -m "not slow"` (fast slice): GO with one carve-out** — no live-file mutation and per-test/per-worker isolation throughout (3120 passed under `-n auto`). The three wall-clock-budget perf files must be `--ignore`d or run serially; they false-fail on scheduler wait, not on a real regression. (`test_documented_claims.py` is `--ignore`d alongside them but no longer holds an elapsed assertion — see the table row.)
- **Full-suite `-n auto` (incl. `slow`): two clean runs recorded, the count this record asked for** — measured 2026-09-06 on the 8 GB self-host box with the three perf files `--ignore`d and then run serially afterwards: 391 s (6:31) for 9,797 tests, then 372 s (6:12) for 9,838 tests plus the three carve-outs in 16 s (627 tests), against 18:41–19:52 serial the same day, with no live-tree race in either run; the `-m contract -n auto` run between them hit three (`test added or removed entries in the LIVE repo tree`), so the race is timing-dependent and has so far shown up in the slice, not in the full run. **GO locally, and the default in the command bodies since 2026-09-06:** `scripts/proof_tier.py --run` runs the two lines (xdist with the three wall-clock-budget files `--ignore`d, then those three serially) under one receipt and holds the file list as `WALL_CLOCK_SERIAL_FILES`, with contracts that each exists, that no other test file asserts a wall-clock upper bound, and that the root `CLAUDE.md` build block quotes the same two lines. **Condition (2) below is NOT satisfied by those two runs:** the slow lane's live-tree behaviour is unaudited, and the contract slice, whose tests are also in this run, raced three times the same day. The local flip is a measured bet on a low race rate, not a cleared gate; the live-tree guard now compares entry sets (an add and a remove no longer cancel) and says so when it fires under xdist. **Races observed under the parallel full form:** one, 2026-09-06, in the fourth parallel full run of the day (the other three were race-free): `tests/test_doctor.py::TestCountRegexesUseHardenedHelper::test_bypass_class_count_uses_hardened_helper` errored at teardown because a sibling worker's atomic-write temp `reports/.cc_surface_gate.json.<rand>.tmp` was removed while the test watched `reports/`; the file serially: 143 passed in 29 s. Two more on 2026-09-06, in the fifth and sixth parallel full runs of the day (the fifth also carried a real red, an unstaged corpus deletion, which is not a race): `tests/test_surface_matrix_module.py::TestLoadMatrixLive::test_missing_path_returns_empty_matrix` errored at teardown on the same `reports/.cc_surface_gate.json.<rand>.tmp` removal, and `tests/test_verify_pins.py::TestIsolation::test_a_run_does_not_touch_the_live_tree` saw a sibling's `espalier_harness-<version>/` release-build tree appear (530 paths) while it watched the live tree; both files serially: 68 passed in 110 s. Two more on 2026-09-06 in the eighth parallel full run of the day (the seventh was killed by memory pressure at 94 percent on the 8 GB box, no red): `tests/test_denial_reasons.py::TestRequiredClaudeMdSectionsAreRendered::test_required_section_renders_for_every_adopter_layout[Cross-platform Python invocation-no-architecture]` and `tests/test_categorized_memory_layout.py::TestCategorizedMemoryLayout::test_sharp_edges_folder_exists_with_readme`, both errored at teardown on a sibling's `reports/.cc_surface_gate.json.<rand>.tmp` appearing; both files serially: 52 passed in 1.5 s. One more on 2026-09-07, in the first parallel full run of the first-hour lane: `tests/test_cli_deploy.py::test_upgrade_dry_run_no_nudge_when_already_migrated` errored at setup under xdist; the file serially: 18 passed in 3.84 s. One more on 2026-09-08, in the first parallel full run of the §C12 reflect lane: `tests/test_speedbump_metacognitive.py::TestCpGateweakenPredicate::test_fires_for_each_guard_file[stop_gate.py]` errored under xdist; the class serially: passed in the same re-run that isolated four real reds. One more on 2026-09-08, in the first parallel full run of the §C10 scanner-predicate lane: `tests/test_verify_pins.py::TestIsolation::test_a_run_does_not_touch_the_live_tree` saw a sibling worker rewrite `reports/cc_surface_gate.json` while it watched the live tree (the same report file as the earlier teardown races); the file serially: 50 passed in 115 s. One more on 2026-09-08, in the first parallel full run of the §C13 release-archive lane: `tests/test_golden_examples.py::test_golden_examples_pass_under_bare_pytest` errored at teardown on a sibling worker's `reports/.cc_surface_gate.json.<rand>.tmp` appearing while it watched `reports/`; the file serially: 5 passed in 0.28 s. One more on 2026-09-09, in the second parallel full run of the §C11 nested-repo-litter lane: `tests/test_guard_false_positives.py::TestThePowerShellTierMatchesBash::test_tier[relative-non-roster-out]` errored because a sibling worker's `reports/.cc_surface_gate.json.<rand>.tmp` was removed while it watched `reports/`; the file serially: 179 passed in 27 s. One more on 2026-09-10, in the second parallel full run of the §C5 DEF-754 walker lane (the first, for DEF-753, was race-free): `tests/test_agent_frontmatter_contract.py::test_agent_capability_matches_tier[harness-config-advisor-review-with-comments]` errored at teardown on a sibling worker's `reports/.cc_surface_gate.json.<rand>.tmp` appearing while it watched `reports/`; the file serially: 9 passed in 0.07 s. One more on 2026-09-11, in the second parallel full run of the §C5 447-A step-1 lane (the first carried one real red and no race): `tests/test_check_pack_landing.py::test_non_pack_files_are_not_in_the_population` errored under xdist; the file serially: 22 passed in 0.33 s. One more on 2026-09-11, in the parallel full run of the §C20 seed-banner lane: `tests/test_audit_accuracy.py::TestUnicodeDigitDefeat::test_fullwidth_digit_rejected` errored at teardown on a sibling worker's `reports/.cc_surface_gate.json.<rand>.tmp` appearing while it watched `reports/`; the file serially: 47 passed in 0.51 s. One more on 2026-09-12, in the second parallel full run of the §C6 lane A (the first carried four real reds and no race): `tests/test_e2e_bench.py::TestAggregation::test_empty_behavior_block_evaluates_to_fail` errored at teardown on a sibling worker's `reports/.cc_surface_gate.json.<rand>.tmp` appearing while it watched `reports/`; the file serially: 35 passed in 0.16 s. One more on 2026-09-12, in the parallel full run of the group-7 audit-log-and-freshness lane: `tests/test_atomic_io.py::TestConcurrency::test_commit_is_a_single_atomic_rename_never_in_place[engine]` errored under xdist; the class serially: 12 passed in 0.11 s. One more on 2026-09-13, in the first parallel full run of the group-9 write-guard lane: `tests/test_speedbump_metacognitive.py::TestIsWritingBash::test_writing_commands[sed -i 's/a/b/' f.py]` errored at teardown on a sibling worker's `reports/.cc_surface_gate.json.<rand>.tmp` being removed while it watched `reports/`; the file serially: 58 passed in 0.58 s. One more on 2026-09-13, in the third parallel full run of the same lane (the second was race-free): `tests/test_settings_profile_fingerprint.py::test_self_host_inherits_workflow_helper` errored at teardown on a sibling worker's `reports/.cc_surface_gate.json.<rand>.tmp` moving while it watched `reports/`; the file serially: 16 passed in 0.09 s. One more on 2026-09-13, in the first parallel full run of the group-10 guard-trio lane: `tests/test_scanner_filesystem_contracts.py::test_scanner_no_espalier_import` errored at teardown on a sibling worker's `reports/.cc_surface_gate.json.<rand>.tmp` appearing while it watched `reports/`; the file serially: 19 passed in 2.06 s. One more on 2026-09-13, in the first parallel full run of the Windows pair lane (`DEF-729` / `DEF-734`): `tests/test_audit_accuracy.py::TestAuditOrchestrator::test_only_failing_omits_unverifiable_section` errored at teardown on a sibling worker's `reports/.cc_surface_gate.json.<rand>.tmp` appearing while it watched `reports/`; the file serially: 50 passed in 0.57 s. One more on 2026-09-14, in the parallel full run of the group-12 lane (`DEF-792` / `DEF-789` / `DEF-710` / `DEF-667`): `tests/test_scan_composition.py::TestPathFormParity::test_absolute_and_relative_paths_intersect` errored at teardown on a sibling worker's `reports/.cc_surface_gate.json.<rand>.tmp` appearing while it watched `reports/`; the file serially: 16 passed in 0.14 s. One more on 2026-09-14, in the second parallel full run of the group-13a lane (`DEF-777` / `DEF-781`; the first carried two real reds -- an unsynced doc mirror and the recall calibration table the memory folds moved -- and no race): `tests/test_atomic_io.py::TestReplaceWriters::test_the_release_archive_gets_the_mode_open_would_give` errored at teardown on a sibling worker's `reports/.cc_surface_gate.json.<rand>.tmp` appearing while it watched `reports/`; the file serially: 97 passed in 2.26 s. One more on 2026-09-15, in the parallel full run of lane 2 (`DEF-795` / `DEF-796`, the remove/relocate operand class): `tests/test_surface_contract.py::TestN7ExecutabilityHelpers::test_matcher_covers_mutations[Bash-False]` errored at teardown on a sibling worker's `reports/.cc_surface_gate.json.<rand>.tmp` being removed while it watched `reports/`; the file serially: 303 passed in 2.81 s. One more on 2026-09-16, in the parallel full run of the `DEF-821` decode-guard lane (its first launch was killed by memory pressure with a browser open, no red): `tests/test_sister_site_probe_unit.py::TestAdopterScanTargets::test_pruned_directories_are_named` errored at teardown under xdist (the live-tree guard saw a sibling worker's entries move while it watched); the file serially: 63 passed in 0.25 s. One more on 2026-09-16, in the first parallel full run of the `DEF-826` carrier lane: `tests/test_check_handoff_landing.py::TestOwedListIsReDerived::test_an_item_with_neither_cmd_nor_why_not_is_refused` errored at setup under xdist; the test serially: passed in 0.47 s. Two more on 2026-09-18, in the parallel full run of the `DEF-837` lane's snapshot-arm and nudge-text steps (the lane's first full run, earlier the same day, was race-free): `tests/test_portability_contract.py::TestOsErrorsRenderAsPaths::test_the_gate_reds_on_a_raw_render[return str(exc)-BaseException]` and `tests/test_release_archive_filtering.py::TestEspalierRuntimeClassification::test_gitignored_runtime_files_are_local_only[.espalier/integrity.json]` errored because `reports/.cc_surface_gate.json.<rand>.tmp` was removed in one and appeared in the other while each watched `reports/` -- plausibly the session's own post-tool hook rewriting the surface-gate report on read-only tool calls made during the run, not a sibling worker; both classes serially: 51 passed in 3.30 s. One more on 2026-09-18, in the parallel full run of the `DEF-842` / `DEF-846` rm-tier lane: `tests/test_guard_false_positives.py::TestThePowerShellTierMatchesBash::test_tier[native-unlink-unprotected]` errored at teardown on a sibling worker's `reports/.cc_surface_gate.json.<rand>.tmp` appearing while it watched `reports/`; the file serially: 368 passed in 85 s. Ten more on 2026-09-20, in the parallel full run of the pre-cut M0 lane (the freshness carried-literal fix): every `tests/test_release_check.py::test_check_passes_on_live_repo[...]` row plus `test_run_all_checks_covers_every_declared_check` and `test_main_exit_zero_on_passing_repo` failed on worker gw2 because its session-scoped `initialized_repo_root` tree was no longer an espalier repo root when the rows ran (ten checks failing on a tree with `cc/LIVE_SURFACE.md` missing and `cli_entrypoint` exiting 1 with no output); the file serially: 58 passed in 5.36 s. Two more on 2026-09-23, in the parallel full run of the archive-tree pack's lane group 2: `tests/test_python_floor.py::TestFloorAtTheThreeDecisionSites::test_detect_python_command_refuses_a_below_floor_host` and `::test_the_warning_quotes_the_first_candidate_that_answered` red because the detector's 2 s `--version` probe of an `sh` stub timed out (`probe failed: TimeoutExpired`, so the resolver fell to the literal `python` and the warning quoted the wrong candidate) while the stage-one smoke's nested not-slow suite ran beside the four workers (a load race one level up from the timing rows: a subprocess budget, not a wall-clock assertion); the file serially: 83 passed in 4.54 s. Append the date and the failing test here when the next one shows. The CI flip stays pending (1) acceptance of the per-worker session/module fixture rebuild cost (the Amdahl floor is the serial `heavy_e2e` stage, about twelve minutes: its 604 s child not-slow leg measured 2026-09-23 plus release_check and self-host), (2) a confirmation pass that no `slow`-lane test races on the live tree, and (3) a decision on the wall-clock-budget perf tests (mark-and-deselect, or pin to a serial worker). The commonly-cited ~3–4× speedup is an **estimate**, not a measurement on this suite (the fast-slice carve-out above measured ~52s serial → ~14s on this box when it held ~3,100 tests; re-measured 2026-09-06 at 5,532 tests: 236 s serial → 91 s with `-n auto` on the 8 GB self-host box).
- **Why it has not flipped:** the fast-slice numbers above are **local** (`~52s -> ~14s` on a multi-core dev box at ~3,100 tests; `236s -> 91s` at 5,532 tests on 2026-09-06) and the commonly-cited ~3–4x is an estimate. CI hardware measured ~50s for the same slice on far fewer cores, and CPU oversubscription is exactly what makes the wall-clock files false-fail. The local parallel command is already documented above, so developers have the win today. **The flip is gated on live CI returning plus a CI-hardware re-measure — the same measurement INV-16 needs.**

## Why no exact test count is documented

The collected test count changes whenever parametrization changes, even
without behavior changes. Documenting an exact count creates drift —
every parametrize edit becomes a doc edit, and stale counts mislead
reviewers. A contract test (`tests/test_test_suite_contract.py`)
enforces that the marker taxonomy stays consistent, that no exact count
is hard-coded in operator docs, that this README exists, and that the
suite has a reasonable lower bound on the number of test files. The
exact number of collected items is intentionally not pinned.

## Adding a new test file

When you add a new test file:

- Use one of the established filename patterns so `conftest.py` can
  assign the right marker automatically (`test_write_guard_*` →
  `security`, `test_release_*` → `release`, etc.).
- If your file fits a new category, add a pattern to `_MARKER_RULES` in
  `tests/conftest.py` and document the new marker here.
- Adversarial/security tests must each name a distinct attack vector.
  Do not consolidate them into parametrized smoke tests; each name is
  part of the regression narrative.
- If your file does heavy work (subprocess, wheel build, git-heavy),
  add its stem to `_SLOW_FILES` in `tests/conftest.py`.

## Anti-patterns this suite explicitly avoids

- `assert True` / trivial-body tests — caught by `tests/test_test_quality.py`.
- Hard-coded exact test counts in docs — caught by the contract test.
- Silent skips on release-critical tests — `tests/test_artifact_parity.py`
  hard-fails when `python -m build` is missing unless
  `ESPALIER_ALLOW_PARITY_SKIP=1` is set explicitly.
- Stale phantom-command/agent references in operator docs — caught by
  `tests/test_operator_docs.py` and `tests/test_handoff_truth.py`.
