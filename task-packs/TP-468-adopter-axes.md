# TP-468 — Adopter axes: run the suite on the trees, hosts and session paths an adopter brings

## Status

- Version target: unscheduled (after `0.8.0b2`).
- Change type: tests (shared helpers, contracts, a session driver), CI (one non-required cell),
  one release script (`scripts/wheel_smoke.py`), one release doc step, one config key
  (`[tool.mypy] platform`), and two shipped bodies (the blueprint-authoring and hook-authoring
  skills). The engine changes only in one scanner's invoker set
  (`espalier/scanners/test_loosening.py`, and `encoding_contracts.py` only if 0-E licenses
  it). No hook edit is planned. A **product** defect an
  axis finds is filed as a row (finding it is the axis's job). A **test-fixture** red the new
  cell shows is fixed in-lane, because the cell is this pack's deliverable and must land green
  (`memory/verify-a-packs-scope-out-rationale.md`, the carve-out).
- **Kind: PACK**. Task 0 can end it, or end one axis of it (partial closure is a licensed
  outcome; see Reach).
- Gate: **approved 2026-10-06.** The answers to the seven authoring questions are recorded
  under *Decisions*. Decision 4 leaves 3-C's oracles pending a mail reply, and Decision 7
  leaves the lane split to execution, with a recommended three-lane split.
- Ledger: the unit of work for `DEF-975`. `DEF-937` (the dirty-machine install fixture) and
  `DEF-970` (the mypy platform pin) land inside it, as the row says. `DEF-1049` (skills missing
  from the portability doc scan) is folded in by root `CLAUDE.md` Core Rule 12: it is one more
  member of the collector population Task 3-D widens. The operator kept it in on 2026-10-06
  (Decision 6).
  Third of the four detection-system packs (alarm, then voice, then **axes**, then the stack
  registry; operator, 2026-09-30).
- Cross-pack: the stack-registry row `DEF-976` is authored after this lands and is proven on the
  Node tree this pack builds. §C57's oracle ("`espalier init` into a throwaway Node tree ... with
  stub `ruff` and `pytest` first on PATH") and §C58's oracle (an init'd tree with
  `src/pkg/mod.py` and no `espalier/`) consume this pack's builder rather than building their
  own. §C69's stubbed-PATH fixture `tests/_interpreter_hosts.py` is reused here, not rebuilt
  (the class section says so). The voice pack (landed 2026-09-30) routed `DEF-915` and
  `DEF-947` to this pack's launch-as-wired runner as an oracle, and its voice channels are what
  that runner asserts on.
- Authored 2026-10-06 at `fc742de` on the Windows box. That host is python-only (`python3` is
  not on PATH) and its main checkout sits under a spaced path, so it is itself a perturbed host
  for two of the three axes. Every measured sentence names its command. Execution re-runs it.
- **Foundation lane landed (2026-10-06, `lane/adopter-axes-foundation`, Windows box): Task 0,
  1-A, 1-B and 2-A.** Landing has the commits and proof.
  - Task 0 verdicts: build on all three axes; 0-E **stops** 3-E (no `newline=` rule); 0-F
    has no refutation. The record is *Task 0 at execution*, below.
  - `DEF-970` is struck.
  - `DEF-975` is **not** struck. The builder half flipped its old probe, so the probe was
    re-pinned to the registry's pass criterion (stack, host and session at two or more proven
    values each). It closes with the last lane.
  - What the next lanes inherit, where execution departed from the text below:
    - **The registry's rule reads parameters, not ids** (1-B, after review). A proving node
      must be parametrised with an argument *named after the axis* (`stack`, `host`,
      `session`, `root`, `tree`), at the cell's value with `-` read as `_`. It must carry no
      `skip` or `xfail` mark, and it must run and pass on the checking host (one nested
      `pytest -v` over the proven ids).
    - The rule was first written on id tokens. Review showed that rule reading
      `[node-pnpm]` as proving `node`, and a strict-xfail param as proving its value.
    - The run check skips while no cell is proven. When 2-B/2-C prove heavy cells, give that
      test its own timeout and move the module from `# slow-exempt:` to `_SLOW_FILES`.
    - Still unseen by the rule: whether the body *uses* the parameter (Risk 1's second
      witness). Add it with the first proof.
    - **Cells:**
      - host is exactly `_interpreter_hosts.SHAPES`;
      - root gains `spaced_interpreter` (0-C's override-pair finding);
      - tree gains `crlf` (2-A's fixtures stopped building CRLF trees on Windows by
        accident).
    - Every cell is a gap, with `PROVEN_FLOOR = 0`.
    - **Open for the operator:** whether `go` and `rust` count as proven by
      `tests/test_stack_trees.py::TestEveryStackInstalls::test_init_and_install_ci_run_on_every_stack[go]`
      (Decision 2's "builder cell and init-exits-zero cell"). The rule would accept it. The
      registry holds them as gaps, because the cell is read as "the hooks govern a session on
      that tree".
    - **2-A writes LF on every host.** The rows are text-identical to the old fixture bodies
      and byte-identical on POSIX. On Windows the old fixtures wrote CRLF, so the on-disk
      bytes there moved, deliberately. The pass criterion "no fixture body changes a byte"
      holds for the bodies, not for Windows line endings.
    - **2-A's mutation claim is narrower than written.** Changing the `print` line or a
      `_cache_*` helper in the `python` row reds the scanner tests. Changing the bare
      `except:` to `except Exception:` does not, because
      `tests/test_scanners.py::TestScanners::test_exception_scanner_finds_swallowed` accepts
      either finding kind.
    - **The Node adopter tree reads as no language.** Its fingerprint has `languages: []`,
      because `.mjs` and `.astro` are unmapped. That is `DEF-961`'s engine half, recorded as a
      strict xfail (`raises=AssertionError`) in `tests/test_stack_trees.py`.
    - The pnpm tree's test command reads `npm test` (`DEF-976`).
    - For 2-C: Gate 1 is dormant on the **Python** adopter tree too when no override is set.
      0-D drove it.

## Motivation

`DEF-975`: every pre-release check ran the harness on a tree shaped like the harness. The
pattern is the one `memory/a-gate-can-be-blind-along-a-whole-dimension.md` records for the
bench corpus, applied to the whole verification system along three axes:

- **stack**: what the adopter's tree is;
- **host**: which interpreter names answer, and whether paths hold spaces;
- **session path**: one event, or a working session that carries state from event to event.

**The axis is measured blind at authoring, not only argued.** Measured 2026-10-06 on a
scratch export of HEAD (`git archive HEAD | tar -x`, outside the tree): with `.js`, `.ts`,
`.jsx` and `.tsx` deleted from `tools/cc/hooks/_hook_utils.py::SOURCE_LANGUAGE_EXTENSIONS`,
the set that decides whether `plan_guard` gates a root file
(`tools/cc/hooks/plan_guard.py::PLAN_REQUIRED_ROOT_EXTENSIONS` unions it) and whether
`reflect_trigger` counts a write toward Stop Gates 2 and 3, the eight files that read it or
the gates behind it changed **0 of 327 verdicts**:

- `tests/test_plan_guard.py`, `tests/test_plan_guard_adopter_config.py`,
  `tests/test_explain_path.py`, `tests/test_reflect_trigger_path_normalization.py` and
  `tests/test_reflect_trigger_additionalcontext.py`: 152 passed.
- `tests/test_stop_gate.py`, `tests/test_hook_utils.py` and `tests/test_forced_copy_parity.py`:
  174 passed, 1 failed. The failure is
  `tests/test_stop_gate.py::TestEnvOverrideGate1::test_end_to_end_failing_override_blocks_under_full`,
  which is on this host's baseline-red list (the operator's Windows baseline, last confirmed
  against HEAD on 2026-10-02 and 2026-10-04) and is unrelated to the edit.

So nothing in those files sees a Node adopter lose every gate. The vendor byte-parity pin was
not run: it reds on any edit to the file, which is parity, not behaviour.

### The row's counts, re-derived at HEAD

The census instrument is Appendix A. Run it from the root. Each line below names its source.

| Row claim (2026-09-30) | At `fc742de` (2026-10-06) | Status |
|---|---|---|
| `build_adopter_tree` has no stack parameter | Parameters `['dest']`. The row's probe prints `0` (driven by `python tools/cc/check_ledger_probes.py --id DEF-975`: STILL_OPEN) | **holds** (verified) |
| "the six stack fixtures ... three have no users" | `tests/conftest.py` has **nine** `*_repo` stack fixtures. The six non-Python-primary ones are `node_repo`, `node_repo_with_tests`, `typescript_repo`, `go_repo`, `rust_repo` and `rust_repo_with_tests`. Three have no user (`rust_repo`, `rust_repo_with_tests`, `node_repo_with_tests`). The users back language detection (`tests/test_fingerprint.py`, `tests/test_analyze.py`) and init-exits-zero (`tests/test_non_python_consumer_init.py`). The selfcheck mirror extracts a **different** six verbatim (`scripts/sync_selfcheck_tests.py::_PORTABLE_FIXTURES`: python, ml, node, typescript, go, polyglot) | **holds, population named** (verified) |
| "fourteen private hook runners ... every one starts the hook with `sys.executable`" | Fourteen is the name-keyed count: `run_hook`/`_run_hook` definitions in 14 files, plus `tests/test_ci_guard.py::_run_guard`, which runs `ci_guard`. The structural census (Appendix A, line 3) finds **57 functions in 34 files**: 53 open with `sys.executable` and 4 with `HOOK_PYTHON` (`tests/test_hooks.py::run_hook` and three in `tests/test_task_router.py`, since the 2026-10-06 sessions-tests lane). None launches the deployed copy | **moved** (verified) |
| "no test launches a hook through the command `settings.json` wires" | Since 2026-10-02, one test does: `tests/test_hook_exec_form.py::TestInitOnTheTwoInterpreterHosts::test_the_launcher_wired_write_guard_spawns_and_denies`. That is one hook (`write_guard`), one host shape (launcher-only), on a bare `git init` tree with no stack file | **moved** (verified) |
| "no test carries a session across events on one tree" | Appendix A has no line for this; a name census floors it. 69 test functions name two or more hook scripts. The ones read (in `tests/test_integrity.py`, `tests/test_hook_utils.py` and `tests/test_speedbump_metacognitive.py`) spawn **one** hook each, and the other name is payload or wiring data. `tests/test_hooks.py::TestSessionMarkerEndToEnd` re-fires SessionStart on a bare temp dir | **holds** (probable: name-keyed floor, and in-process `main()` drives are not counted) |
| the Walk "drives init, **upgrade**, scan and doctor on a Python-only tree" | `tests/test_adopter_lifecycle_diagnostics.py::walked` drives `init`, a re-init, `scan`, `--help`, `scaffolding-bench` twice, `selfcheck --contracts`, `doctor` four times and `clean-generated --execute`. It drives **no `upgrade`**. Its tree is a README and `app.py` on a bare `git init`, not `build_adopter_tree`. `::api_walked` adds `init` and `audit` on a FastAPI file | **corrected** (verified) |
| `--basetemp` is never used | Never used. The only mentions are `stop_gate`'s argv parser and its test | **holds** (verified) |
| "no test builds a PATH shim beyond three single cases" | `tests/_interpreter_hosts.py::build_host` (three host shapes in two flavours, since 2026-10-02) is consumed by 9 test modules. No suite-wide run uses one | **moved** (verified) |
| `scripts/wheel_smoke.py` has one `_git_init` site | It does, and its target holds **no stack file at all**: an empty `git init`, then `init`, `install-ci`, `doctor`, `audit` and `integrity verify`. A sibling release instrument builds a second target: `scripts/final_release_matrix.py::stage_wheel` (`doctor_target`: a README on `git init`, `doctor` only) | **holds, sibling named** (verified) |
| no CI cell is perturbed | `test.yml` (`tier`, `test`×5, `test-serial`×5, `ripgrep-parity`, `stdlib-audit`, `code-review-audit`, `artifact-parity`, `workflow-lint`) and `portability.yml` (the not-heavy suite on ubuntu, windows and macos at 3.12) set no `--basetemp` and no PATH shim. Whether the windows-latest PATH answers `python3` is **not measured** (Task 0-C) | **holds** (verified, one cell open) |
| `docs/RELEASE_CHECKLIST.md` has no blind-axis step | None | **holds** (verified) |
| 46 post-cut findings: 30 catchable statically, 10 by a `package.json` tree, none needing Windows | `reports/detection-review-2026-09-30/` is gitignored and not on this box | **carried, not re-derived** |
| `DEF-970`: 29 errors in four files | `mypy tools/cc/hooks/` (in process, cache to the null device) reports **1 error in 1 of 26 files**: `tools/cc/hooks/_integrity.py`, `os.getuid`. The row's probe still prints `win32 1` | **moved, still open** (verified) |

Three more measurements bear on the prescription:

- **The builder is not cheap.** `build_adopter_tree` took 5.86, 5.35 and 5.83 s on this host
  (three runs, `C:\tmp`). Its docstring says "~200ms". Folding about 40 function-scoped fixture
  users into a real `init` would add minutes per run, so the fold has to happen at the file-set
  layer (Task 2-A).
- **A host-axis red is already sitting in the suite.**
  `tests/test_merge_settings.py::TestEnforcementClaimSurvivesRealSettingsShapes::test_legacy_quoted_shell_form_is_not_reported_as_disarmed`
  reds on this python-only host (driven 2026-10-06). Its fixture wires `python3`, and the
  product correctly reports that name dead here. Five bare `'python3'` argv literals in
  `tests/test_run_pack_chain.py` are skipped on win32, so no host that lacks `python3` ever
  runs them. Two ledger probes (`DEF-411a`, `DEF-412h`) spawn `['python3', ...]` inside their
  `-c` body, past `tools/cc/check_ledger_probes.py::_under_this_interpreter`'s leading-name
  rewrite. That failure is probable, not driven: both probes are UNRESOLVED here because their
  `task-packs/Done` input is absent.
- **The `newline=` prescription is refuted as written.** The census (Appendix A, line 5)
  counts **3,266** text-mode write sites, and 19 of them pass `newline=` (espalier 162/3,
  tools 24/4, scripts 16/2, tests 3,029/10, bench 35/0).
  `espalier/scanners/encoding_contracts.py` holds **zero** findings on this tree with
  `MAX_PRAGMA_COUNT = 1`. An unscoped rule joining it would add thousands of findings to a
  scanner held at zero. Task 0-E scopes the rule or drops it.

**Who is hurt** (`docs/STANDING_PRINCIPLES.md` §16): the next adopter on a Node, Go or Rust
tree, or on a python-only host, who meets the class of defect the suite cannot see (the five
§C57 members were all found by a human on one Node tree). Also the maintainer, whose green
suite certified it.

## Scope (in)

Each item maps to a task and to *Files touched*.

1. **1-A** The mypy platform pin (`DEF-970`).
2. **1-B** An axis registry under `tests/` in the shape of `tests/_closed_loop_registry.py`.
   Each `(axis, value)` cell names the test node it is proven by or declares its gap with a
   reason. A contract test floors it and collects every named node.
3. **2-A** One stack table, `tests/_stack_trees.py` (stdlib only). `build_adopter_tree` gains
   `stack=` and `tree=`. The nine conftest stack fixtures fold onto the table. The three with
   no user are deleted. The selfcheck mirror carries the table.
4. **2-B** A shared hook runner, `tests/_hook_runner.py`, promoted from
   `tests/test_hooks.py::run_hook`, with a launch-as-wired option. It also gets a wired-hooks
   matrix test and a ratchet on private runners. It also lands two sites the authoring
   scope-check found:
   - `espalier/scanners/test_loosening.py::_HOOK_INVOKERS`, which keys on the helper names
     `run_hook` and `_run_hook`, gains `run_hook_as_wired`. Otherwise deny tests on the new
     launcher escape the scanner.
   - The hook-authoring skill's sentence saying `run_hook` "lives in `tests/conftest.py`"
     is false today (it lives in `tests/test_hooks.py`). It is corrected to name the shared
     module, and its mirrors are synced.
5. **2-C** A cross-event session driver on one tree per stack: SessionStart, a prompt, a
   source write, ten counted writes, Stop with the stack's test command, a commit, a config
   edit, and `upgrade`, then SessionStart again.
6. **2-D** The lifecycle `Walk` parametrised by stack, and given the `upgrade` verb it never had.
7. **3-A** One perturbed CI cell: a spaced `--basetemp`, a PATH whose `python3` is the Store
   stub, and optionally a spaced checkout (Task 0-C decides). Plus the test-fixture reds it
   shows.
8. **3-B** `scripts/wheel_smoke.py` gains `--stack` and `--spaced-root` at its `_git_init`
   site, and `release.yml` gains one perturbed leg.
9. **3-C** The dirty-machine install cell (`DEF-937`): a `master` default branch, a
   pre-existing `.claude/`, a spaced root, and a stale `espalier` first on PATH. Its oracles
   are pending the Air's reply (Decision 4).
10. **3-D** The portability collectors over workflow bodies, command and skill code blocks,
    subprocess argv lists and probe `-c` bodies (with `DEF-1049`'s skills arm).
11. **3-E** A `newline=` rule, at the scope Task 0-E measures, or none.
12. **3-F** The blind-axis step in `docs/RELEASE_CHECKLIST.md`, fed by a report the registry
    prints.

The paths these touch, for the scope walk:

- `tests/` and `espalier/_vendor/selfcheck_tests/` (the second by `scripts/sync_selfcheck_tests.py`)
- `scripts/wheel_smoke.py`, `scripts/sync_selfcheck_tests.py`
- `.github/workflows/test.yml`, `.github/workflows/release.yml`
- `pyproject.toml`, `docs/RELEASE_CHECKLIST.md`, `CHANGELOG.md`
- `.claude/skills/blueprint-authoring/SKILL.md`, `espalier/assets/claude/skills/blueprint-authoring/SKILL.md`
  and `examples/dogfooding/.claude/skills/blueprint-authoring/SKILL.md` (the two mirrors, by the sync script)
- `.claude/skills/hook-authoring/SKILL.md`, `espalier/assets/claude/skills/hook-authoring/SKILL.md`
  and `examples/dogfooding/.claude/skills/hook-authoring/SKILL.md` (the `run_hook` home sentence; mirrors by the sync script)
- `espalier/scanners/test_loosening.py` (the invoker set)
- `espalier/scanners/encoding_contracts.py` (only under 0-E)
- `task-packs/FORWARD_LEDGER.md`, `task-packs/LEDGER_PROBES.json`, `task-packs/TP-468-adopter-axes.md`

## Scope (out)

- **Migrating the 57 private hook runners onto the shared one.** The ratchet in 2-B stops
  growth. Migration buys de-duplication, not axis coverage. Reason, checked against the fix
  shape: the shared runner's default spawn is `HOOK_PYTHON` on the source script, which is
  today's `tests/test_hooks.py::run_hook`, so a migrated runner would exercise nothing new.
  Only the launch-as-wired arm does, and 2-B's matrix is where it runs.
- **Fixing the product defects the axes find.** Each becomes a row. Already-known members
  stay with their owners: `DEF-961` to `DEF-965` (§C57), `DEF-976` (the next pack),
  `DEF-915` (the resolver's start-up probe), `DEF-947` (a container is not a PATH shape, so
  the runner cannot model a bind mount), and `DEF-968` (the spaced-interpreter extractor). The
  cell and the session driver are expected to show some of them red (`DEF-961`'s shape on the
  Node tree is 0-D's pre-registered hypothesis). The pack records each as a declared
  gap in the registry or as a `strict=True` xfail that names the row, never as a silent skip.
  (The xfail-versus-gap call is Decision 5.)
- **`scripts/final_release_matrix.py::stage_wheel`'s `doctor_target`.** It is recorded in the
  blind-axis table, not given a stack. Reason, read from the stage: it runs `import espalier`,
  `--help` and `doctor` on a README tree, and accepts unparsed `doctor` output ("structured
  output not parsed (acceptable)"). So its job is "the installed CLI starts", not adopter-tree
  behaviour.
- **Making the new cell a required check.** It lands non-required. Promotion is an operator
  call after a run of greens, because a required name that never reports parks every pull
  request (`tests/test_required_status_checks.py`'s docstring).
- **A Windows or macOS variant of the perturbed cell.** `portability.yml` already runs the
  suite on both. 0-C measures whether its windows cell lacks `python3`, and the blind-axis
  table records the answer.
- **The `.claude/workflows/*.js` persist lines.** The canonical resolver line already pins
  them (`tests/test_interpreter_hosts.py::TestShellResolverLine`, from `DEF-1055`'s closure),
  so 3-D's workflow-body arm covers only the other tokens.
- **The stack registry itself.** That is `DEF-976`'s unit. This pack builds the trees and the
  driver that unit is proven on, and changes no production extension list.

## Task 0 — Verify (may end this pack, or one axis of it)

Outcomes:

- **build**;
- **partial** (an axis whose differential is zero is dropped, with its measurement in
  Landing, and the rest continues);
- **do not build** (every axis refuted).

On a refutation the default exit is **stop and re-raise with the measurement**, not "adjust
and continue". Records go to `reports/tp468/` (gitignored). Never run the full tier or
`-n auto` for Task 0. Every drive below is a slice, run from the repository root.

Commands here spell `python`, the name that answers on the authoring host. On a host where
only `python3` answers (stock macOS), substitute it, per root `CLAUDE.md` "Cross-platform
Python invocation".

### 0-A The census (re-derive the Motivation table)

**Oracle:** Appendix A, saved to a scratch path outside the tree and run from the root with
the suite's interpreter.

**Refuting result:** line 1 lists `stack`; then 2-A's builder half has landed and 2-A shrinks
to the fixture fold.

**Also re-derive:** any count that moved again. The table is a 2026-10-06 snapshot.

### 0-B The stack differential (the axis, measured)

**Oracle:** the authoring drive in Motivation. Re-run it, then run its twin on the Python
side:

1. Export HEAD to a scratch directory.
2. Delete `".js", ".ts", ".jsx", ".tsx"` from `SOURCE_LANGUAGE_EXTENSIONS` in the export's
   `tools/cc/hooks/_hook_utils.py`.
3. Run the eight files named there with
   `python -m pytest -q -p no:randomly -p no:cacheprovider --timeout=300`.
4. Repeat steps 2 and 3 with `".py"` deleted instead. This is the control: a Python-shaped
   suite should red here.

**Refuting result:** the Node deletion changes one or more verdicts. Then the stack axis is
already partly seen. Narrow 2-A to 2-D to the stacks the differential stays blind on, and
record which.

**Control failure:** the `.py` deletion **also** reds nothing. Then those eight files see no
extension at all, the differential is not evidence about stacks, and you re-raise.

**Measured 2026-10-06** (Node deletion only): 0 changed verdicts across 327 tests. **Build.**

### 0-C The host differential

**Oracle:** on a POSIX host, build the Store-stub host:

```
python -c "from pathlib import Path; from tests._interpreter_hosts import build_host, STORE_PYTHON3, SH; print(build_host(Path('<scratch>/axis hosts'), STORE_PYTHON3, SH))"
```

Prepend the printed directory to PATH and run, with
`--basetemp "<scratch>/axis basetemp/bt"`:

- the `test_merge_settings` row named in Motivation;
- `tests/test_run_pack_chain.py`;
- the two override rows on this host's baseline list:
  `tests/test_stop_gate.py::TestEnvOverrideGate1::test_end_to_end_failing_override_blocks_under_full`
  and
  `tests/test_governance_audit_log.py::TestStopGateBlocksReachTheLog::test_the_override_gate_block_lands_a_pytest_record_end_to_end`.

Run the same slice unperturbed as the control.

**Pre-registered:** the `test_merge_settings` row reds under the shim and passes in the
control, as it already does on the Windows host. The five `python3` argv sites in
`tests/test_run_pack_chain.py` red.

**Refuting result:** nothing reds under the shim that passes in the control. Then a no-`python3`
cell shows nothing today. Re-raise the cell half: it would be a regression-only gate, and
that is the operator's call.

**Also measure:**

- whether `PYTEST_ADDOPTS="--basetemp='<spaced path>'"` survives `scripts/proof_tier.py`'s
  argv (it sets no `--basetemp` of its own; grep `basetemp` in it prints nothing);
- whether a spaced **checkout** reds the override pair on Linux. On Windows a space-free
  worktree also redded them, so the space is not established as the cause (the host baseline
  note, 2026-10-04);
- whether the windows-latest runner answers `python3`. No existing step prints it; the
  setup-python step's log in the latest windows-latest `portability.yml` run is the only
  existing witness (`gh run list --workflow=portability.yml -L5`, then `gh run view <id> --log`).
  If that log does not say, 3-F's table records "not measured". Adding a probe step to a
  workflow for this is out of 0-C's budget.

### 0-D The session differential

**Oracle:** by hand, on one init'd Python tree and one init'd Node tree, launch as wired
(command and args from the tree's `.claude/settings.json`, `${CLAUDE_PROJECT_DIR}` expanded):

1. `session_start.py` (startup);
2. `plan_guard.py` and `write_guard.py` on a Write to a stack source file (`src/app.py`;
   `src/index.mjs` then `src/index.js`);
3. `tools/cc/execution_plan.py create`;
4. ten PostToolUse fires of `reflect_trigger.py` on that file;
5. `stop_gate.py` with `ESPALIER_STOP_GATE=full`.

**Pre-registered (hypothesis, from code reading):**

- On the Python tree, Stop blocks at Gate 2 (`write_count` reaches 10, and
  `tools/cc/hooks/stop_gate.py` arms Gates 2 and 3 at `write_count >= 10`).
- On the Node tree, `.mjs` writes leave `write_count` at 0 and Stop allows (`DEF-961`'s
  shape), and Gate 1 reports `dormant_non_pytest`
  (`tools/cc/hooks/stop_gate.py::_resolve_core_tests`).

**Refuting result:** both trees reach the same Stop decision for the same reason. Then the
session axis shows nothing the single-event tests do not, and 2-C shrinks to the wired matrix
(2-B). Re-raise.

### 0-E Scope the `newline=` rule (the prescription is refuted as written)

**Oracle:**

- Appendix A, line 5 (the whole population).
- Then the narrower population: production write sites in `espalier/` and `tools/cc/`
  (186 at authoring) that append to, or rewrite, a file the adopter owns. That means mode
  `'a'`, or a `write_text` whose target was `read_text`'d earlier in the same function. This
  is the shape `DEF-940` closed at one site in `espalier/cli.py::_handle_gitignore`.
- Count both, and list the narrower one.

**Stop condition:** if the narrower population has more than 10 sites, or the AST cannot
separate it without a per-site judgement, ship **no** rule. Record the census in Landing and
re-raise. A pragma budget of one cannot absorb it, and an advisory scanner nobody reads is
noise.

**Otherwise:** 3-E lands the narrow rule.

### 0-F Cost

**Oracle:**

- Time `build_adopter_tree` per stack (Appendix A has the Python figure).
- Time the 2-C chain per stack.
- Time one full-tier parallel leg on a `test` cell (`gh run view --log`, the `--durations`
  footer).

**Refuting result:** the new cell's wall time exceeds the slowest required cell's. Then the
cell runs the tier the PR earns minus the parallel leg's heaviest files, or moves to
`portability.yml`'s path filter. Re-raise if neither fits.

### Task 0 at execution (the foundation lane, 2026-10-06, Windows host, `e5a2f10`)

The drivers and their raw output are under `reports/tp468/` (gitignored), with
`task0_verdicts.txt` as the index. Every differential ran on a `git archive` export outside
the tree, serially, at most five files per invocation, never `-n`.

- **0-A: build.**
  - Appendix A, re-run, moved on line 5 only: `tests` went from 3,029 to 3,035 text-mode
    writes, so the total is 3,272. Lines 1 to 4 and 6 print exactly what is printed above.
    Line 1 is `['dest']`.
  - 1-A's pre-check found three `sys.platform == "win32"` arms in `tools/cc/hooks/` beside
    `relaunch_hint`: the `lock_file` and `unlock_file` fallbacks and `_REPLACE_ATTEMPTS` in
    `_hook_utils.py`. None carries an expression the gate must type (a literal raise, a
    bare return, an int literal), so 1-A is not re-raised.
- **0-B: build. The stack axis is blind, and the control proves the instrument can see.**
  - Base: 328 passed, 1 failed (the host-baseline `TestEnvOverrideGate1` row), 329 tests.
    Batch one gained two tests since authoring.
  - Node extensions deleted: **0 of 329** verdicts changed.
  - `.py` deleted (the control): **8 of 329** changed:
    - 3 in `tests/test_plan_guard_adopter_config.py`;
    - 2 in `tests/test_plan_guard.py`;
    - 2 in `tests/test_reflect_trigger_path_normalization.py`;
    - 1 in `tests/test_explain_path.py`.
  - The second batch (`test_stop_gate`, `test_hook_utils`, `test_forced_copy_parity`) moved
    0 verdicts under either deletion.
- **0-C: build** (adapted to this host, which is not POSIX).
  - Setup:
    - Control: a working `python3.cmd` shim first on PATH (the CI shape).
    - Perturbations: the native `STORE_PYTHON3` host, and a spaced `--basetemp` passed
      through `PYTEST_ADDOPTS`.
  - Under the stub, one test reds that passes in the control: the `test_merge_settings` row
    the Motivation names. The spaced basetemp alone reds nothing, and it survives
    `PYTEST_ADDOPTS` quoting.
  - Not measured here:
    - `tests/test_run_pack_chain.py`: its 49 tests all skip on win32, so its five `python3`
      argv sites are unreachable on this host.
    - A spaced checkout on Linux.
  - Measured, new:
    - The override pair reds in every configuration, the control included. The failure
      message gives the cause: the test spells `sys.executable` unquoted inside
      `ESPALIER_STOP_GATE_TEST_CMD`, and this host's interpreter sits under
      `...\Systems and Software\...\.venv`. So it is a spaced-**interpreter** red, not the
      `python3` axis and not a spaced checkout. On CI the interpreter lives in the tool
      cache, so 3-A's spaced checkout reds the pair only if the venv lives inside it.
    - pytest's `--basetemp` needs its parent directory to exist. 3-A's step must create it.
    - A PATH-shim probe must resolve on the child's PATH (`shutil.which(name, path=...)`).
      On Windows a bare-name argv resolves on the parent's PATH and never applies
      `PATHEXT`, so the first probe reported `python3` absent while the shim was in force.
      That is Risk 4, met in the instrument itself.
    - `scripts/proof_tier.py` spawns pytest with the inherited environment and sets no
      `--basetemp`, so `PYTEST_ADDOPTS` reaches it (read, not driven).
    - Whether windows-latest answers `python3` is **probable yes, not measured directly**.
      Portability run 37435570204's windows leg reports 18,101 passed and 0 failed, and the
      `test_merge_settings` row, which hard-codes `python3` and reds where that name does
      not answer, is not in its skip list. No log line names the interpreter.
- **0-D: build.** Driven as wired on three init'd trees (`python`, Node with `.mjs`, Node
  with `.js`):
  - Python tree:
    - `plan_guard` denies `src/app.py` and root `app.py` with no plan.
    - Ten PostToolUse fires leave `write_count` at 10.
    - Stop under `full` blocks at Gate 2 on three Stops running.
  - Node tree with `.mjs`:
    - Root `index.mjs` is **allowed** with no plan.
    - `write_count` stays absent after ten fires.
    - Stop allows.
    - Gate 1 notes `dormant_non_pytest`.
  - Node tree with `.js` (the stack-matched control): root `index.js` is denied, the count
    reaches 10, and Stop blocks at Gate 2.
  - The pre-registration holds.
  - New for 2-C: Gate 1 is dormant on the Python adopter tree too ("the detected pytest
    command names no files"). Only `ESPALIER_STOP_GATE_TEST_CMD` arms it, on either stack.
- **0-E: stop. No `newline=` rule lands; 3-E is dropped, and this is re-raised.**
  - The "186 production sites" at authoring counted the selfcheck **test** mirror: 148 of
    `espalier/`'s 162 sites are in `espalier/_vendor/selfcheck_tests/`.
  - The production population is 38 sites (14 in `espalier/`, 24 in `tools/cc/`), 7 of
    them with `newline=`.
  - The narrower population is **16** append-mode sites and 0 read-then-rewrite sites
    (same target expression). Most are `'a+'` flock lock files or harness-owned logs and
    counters.
  - That is over the 10-site bound, and telling "a file the adopter owns" apart needs a
    judgement at each site.
- **0-F: no refutation (projected).**
  - `build_adopter_tree` took 4.48, 4.95 and 4.84 s here. Per-stack `init` plus
    `install-ci`: Python 4.8 s, Node 4.5 and 5.3 s.
  - The 0-D chain, build included: Python 13.0 s, Node 8.7 and 9.2 s.
  - Full-tier parallel leg, `test (3.12)` in run 37443569869: 1,555.9 s for 17,391 tests.
    Cell walls ran 21.6 to 29.0 min, and the slowest required cell is `test (3.10)` at
    29.0 min.
  - The perturbed cell runs the same tier and leg, so its first run is 3-A's measurement.

## Relevant memory

Recent pattern: the defects reviewers find on this tree sit in the **repair** and in the
**tests that prove it**, not in the original code. The voice pack recorded three of six
post-cut hook fixes reviewed red on the repair (its Relevant memory, at `2891d7a`). The
sessions pack's blocker was a hand-kept roster in a test (its Landing stanza). This pack's own
census drifted on three definitions before it settled (fixture names, which calls count as a
spawn, the `-m espalier` spelling). Re-run Appendix A rather than trust its printed output. In
this pack the likeliest repair defect is a registry cell that names a test not actually
parametrised over its value. That cell is born-blind exactly the way the bench corpus was.

| Entry | Where |
|---|---|
| A gate can be blind along a whole dimension of its input | `memory/a-gate-can-be-blind-along-a-whole-dimension.md` |
| Completeness gate must discover its population | `memory/completeness-gate-must-discover-its-population.md` |
| The source tree is not an oracle for the produced artifact | `docs/sharp-edges/source-tree-is-not-an-artifact-oracle.md` |
| Hook Wiring vs. File Existence | `docs/SHARP_EDGES.md :: Hook Wiring vs. File Existence` |
| A Content-Hash Pin Over Raw Bytes Is CRLF-Sensitive | `docs/SHARP_EDGES.md` (the entry of that title) |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |

Resolved at authoring by `python tools/cc/hooks/_recall.py "<topic>"` with these topics:

- `a gate blind along a whole dimension of its input corpus`
- `hook launched through the command settings.json wires interpreter`
- `suite run from a path with a space python3 missing host`
- `text-mode write produces CRLF on Windows newline`

The topic `test fixtures shaped like the harness not like an adopter tree` returned nothing
that fits, which is the gap this pack fills. Re-run rather than trust this list if the pack
has been sitting.

The folders this pack touches, so the folder-`CLAUDE.md` ladder fires on entry:

- `tests/`:
  - a new `test_*.py` is classified in `tests/conftest.py::_MARKER_RULES`;
  - `git add` a new file before gating;
  - a module asserting on a spawned hook's parent pid spawns through `HOOK_PYTHON`;
  - a test that reads live-tree content is driven once through `scripts/archive_probe.py`.
- `.github/workflows/`: protected zone; maintenance mode or the approval marker.
- `espalier/_vendor/`: a mirror; never hand-edited.

## Implementation

Every fix below is a **fix shape, untested**, unless it says otherwise. Each sub-task names the
mutation its new test must die to. Landing records that it did.

### 1-A The mypy platform pin (`DEF-970`) — *fix shape from the row; the row drove it in throwaway copies on 2026-09-29*

Pin the target view beside the version pin, for the reason that pin already states:

```toml target=pyproject.toml
# required cell alone.
python_version = "3.10"
platform = "linux"
disallow_untyped_defs = true
warn_no_return = true
```

Then pin `platform` in `tests/test_mypy_config_stays_near_strict.py::test_mypy_config_keeps_near_strict_flags`
beside a `python_version` pin.

**Proof:** `mypy tools/cc/hooks/` on the Windows host reports no issues (today: 1 error). The
row's probe flips from `win32 1`.

**Mutation:** delete the `platform` line, and the new pin reds.

**Refutation of the shape:** the pin turns the one `sys.platform == "win32"` arm in the hooks
(`_maintenance_mode.relaunch_hint`) unreachable to mypy on every host. That is accepted in the
row, and already so in CI. If 0-A finds a second Windows-only arm the gate must type, re-raise.

### 1-B The axis registry — `tests/_axis_registry.py`, `tests/test_axis_registry.py`

A frozen-dataclass registry in the `tests/_closed_loop_registry.py` shape. One entry per cell:

```python target=tests/_axis_registry.py
@dataclass(frozen=True)
class AxisCell:
    axis: str           # "stack" | "host" | "session" | "root" | "tree"
    value: str          # e.g. "node", "store_python3", "cross_event", "spaced", "dirty"
    proven_by: str      # a pytest node id whose parametrisation carries `value`, or ""
    gap: str            # why no test proves this cell yet (a row id, or a reason); "" if proven
```

The contract, `tests/test_axis_registry.py`:

- Every cell has exactly one of `proven_by` or `gap`.
- Every `proven_by` node id **collects**, via `pytest --collect-only -q` on that file in a
  subprocess, and its id carries `value`. A cell that names a test not parametrised over its
  own value is the born-blind shape, and this is what refuses it.
- The count of proven cells only rises. The floor is a dated constant, like the
  `_RAW_GIT_POPULATION_SITES` ratchet in `tests/test_test_suite_contract.py`.
- An axis with exactly one proven value is reported (not failed), because 3-F's table reads
  that report.
- `python tests/_axis_registry.py` prints the table 3-F pastes.

It lands first with every cell a declared gap, except the one cell that is proven today
(`host` / `launcher_only` →
`tests/test_hook_exec_form.py::TestInitOnTheTwoInterpreterHosts::test_the_launcher_wired_write_guard_spawns_and_denies`,
which carries no value in its id. So the contract's id rule reds on it, and the cell must name
a parametrised node or declare the gap. That is the first earn-the-red).

**Mutation:** point a cell at a test whose id lacks the value, and the contract reds.

### 2-A One stack table, the builder, the fold — `tests/_stack_trees.py`

**Fold at the table, not at `init`** (measured reason: 5.4–5.9 s per real build on this host).

- `tests/_stack_trees.py` is stdlib-only with no `espalier` import. It holds
  `STACKS: dict[str, dict[str, str]]` (row name to relative path to body). Its rows are:
  - **byte-identical** to today's fixture bodies (`python`, `ml`, `node`, `typescript`, `go`,
    `polyglot`, `rust`), because their users assert on that content (for instance the bare
    `except:` and `print` in `python_repo`'s `app.py` feed the scanner tests);
  - `adopter-python`, today's `build_adopter_tree` file set, byte-identical so every current
    caller's tree is unchanged;
  - the adopter stacks the downstream packs need: `adopter-node` (`package.json` with `test`,
    `lint` and `build` scripts, `src/index.mjs`, `src/pages/index.astro`, a `.gitignore` with
    `node_modules/`), `adopter-node-pnpm` (the same plus `pnpm-lock.yaml`, `DEF-976`'s probe
    tree), `adopter-go` and `adopter-rust`.
- `write_stack(dest, row)` writes a row's files with `newline=""`.
- The selfcheck mirror carries the table. Add `_stack_trees.py` to
  `scripts/sync_selfcheck_tests.py::BYTE_MIRRORED`, and add its import to the transform's
  conftest header. Check that `pyproject.toml`'s package-data glob ships it.
- `build_adopter_tree` gains its two parameters. `stack` names an adopter row without its
  prefix (`stack="node"` writes `adopter-node`). `tree` is the depth: `"files"` writes the
  table row only; `"git"` adds a real `git init`, identity and initial commit; `"adopter"`
  (the default) adds `init` and `install-ci` as today. A `dirty=` knob for 3-C may land here
  or there.

```python target=tests/_adopter_tree.py
def build_adopter_tree(
    dest: Path, *, stack: str = "python", tree: str = "adopter", branch: str = "main",
) -> Path:
```

- The six conftest fixtures that have users (`python_repo`, `ml_repo`, `node_repo`,
  `typescript_repo`, `go_repo`, `polyglot_repo`, which are also the selfcheck mirror's six)
  become calls to `write_stack(tmp_path, <row>)` that keep today's fake `.git` marker. The
  three with no user are deleted (`rust_repo`, `rust_repo_with_tests`,
  `node_repo_with_tests`); the `rust` row stays in the table.
- Run `python scripts/sync_selfcheck_tests.py`.

**Proof:**

- `tests/test_selfcheck_tests_parity.py` is green.
- `espalier selfcheck` (or `python -m pytest espalier/_vendor/selfcheck_tests -q` from a
  scratch cwd) is green.
- A new test asserts each fixture's tree is byte-identical to its row.
- The probe prints `1`.

**Mutations:**

- Change one byte of the `python` row, and the scanner tests that read `python_repo` red.
- Drop `_stack_trees.py` from `BYTE_MIRRORED`, and the parity test reds.

**Refutation:** the selfcheck conftest cannot import a sibling module under `espalier
selfcheck`'s cwd. That is untested; pytest's default import mode puts the conftest's
directory on `sys.path`. Then the six portable fixtures stay self-contained, and a parity test
pins them to the table instead.

### 2-B The shared runner, launch-as-wired, the matrix, the ratchet — `tests/_hook_runner.py`

**Promote.**

- `tests/test_hooks.py::run_hook` moves here unchanged (`HOOK_PYTHON`, source script, its
  `env_overrides` deletion semantics).
- `tests/test_hooks.py` keeps the name as a **module-level assignment**
  (`run_hook = _hook_runner.run_hook`), not a bare `from ... import`. Measured by reading
  `tests/test_doc_test_citations.py::_defined_names`: a `file::symbol` citation resolves
  through defs and assignments only, never imports. `docs/SHARP_EDGES.md` cites
  `tests/test_hooks.py::run_hook`, so a bare import would turn that citation into a phantom.
- The four modules that already import `run_hook` from `test_hooks` for reuse
  (`tests/test_hooks_worktree_checkouts.py`, `tests/test_nested_repo_litter.py`,
  `tests/test_reinject_pins.py` and `tests/test_subprocess_env_isolation.py`) import it from
  the shared module instead. They are the demand this module answers.
- `tests/test_hook_exec_form.py`'s `_iter_hooks` and `_script_arg` move here, and that module
  imports them.
- `espalier/scanners/test_loosening.py::_HOOK_INVOKERS` (`{"run_hook", "_run_hook"}` today)
  gains `run_hook_as_wired`. Otherwise a deny-intent test that calls the new launcher and
  observes only its return escapes the scanner's deny arm. The authoring scope-check surfaced
  this. Earn its red with a planted deny test on the launcher, in the scanner's fixture
  corpus.
- `.claude/skills/hook-authoring/SKILL.md` says `run_hook` "lives in `tests/conftest.py`",
  which is already false (it lives in `tests/test_hooks.py`). It is corrected to name the
  shared module and the launcher. Then run `python scripts/sync_claude_mirrors.py`.

**Add the wired launch:**

```python target=tests/_hook_runner.py
def run_hook_as_wired(
    tree: Path, script_name: str, payload: dict, *, path: str | None = None,
    env_overrides: dict | None = None, timeout: int = 60,
) -> subprocess.CompletedProcess:
    """Launch the entry `tree/.claude/settings.json` wires for `script_name`, the way Claude
    Code does: `command` resolved on `path` (shutil.which), `args` verbatim with
    `${CLAUDE_PROJECT_DIR}` expanded, cwd and CLAUDE_PROJECT_DIR the tree. Raises when the
    entry is missing or `command` does not resolve: a missing wiring is a finding, never a skip."""
```

This generalises the launch block that
`TestInitOnTheTwoInterpreterHosts::test_the_launcher_wired_write_guard_spawns_and_denies`
hand-rolls. That test moves onto it.

**The matrix,** `tests/test_hooks_as_wired.py`:

- For each adopter stack (2-A) and each `_interpreter_hosts` shape, build one tree
  (module-scoped, `tree="adopter"`) and never share it with another module.
- Launch every wired entry (twelve today, derived from the settings file, never a literal)
  with a no-op payload for its event.
- Assert the exit is in `{0, 2}` and the stdout/stderr channel rule
  (`tests/_hook_assertions.py`).

This is the cell that would have caught `DEF-915`'s shape (an interpreter that answers
`--version` and cannot start). Its regression test can use it as the launch oracle.

**The ratchet:**

- `tests/test_test_suite_contract.py` gains `test_private_hook_runners_only_shrink`: the
  Appendix A census (line 3) per module, with a dated per-file baseline that may only fall.
- It has a floor: a census of zero reds, the "matcher broke" guard the raw-git ratchet has.
- It excludes `tests/_hook_runner.py`.

**Mutations:**

- On the STORE_PYTHON3 host, make `espalier/cli.py::_detect_python_command` return `python3`
  in a scratch copy. The matrix reds, and today's suite does not on Linux.
- Add a private runner to any test file, and the ratchet reds.

**Not a parent-pid oracle:** on a Windows venv the wired `python` resolves through PATH to the
venv's redirector. A launch-as-wired spawn therefore never asserts on `os.getppid()`. The
docstring says so, and the suite contract's parent-pid pin is unchanged.

### 2-C The session driver — `tests/_session_driver.py`, `tests/test_adopter_session.py`

One tree per stack (`python` and `node`, Decision 2), all launches through
`run_hook_as_wired`. A stub test binary goes first on PATH, built the way
`tests/_interpreter_hosts.py` builds its stubs. It records each call and exits 1, then 0.

The chain, with the state each step hands the next:

1. SessionStart `startup` writes the session marker and the flags.
2. UserPromptSubmit touches the marker.
3. PreToolUse Write on a root-level source file of the stack is denied without a plan. Root
   level, because there `plan_guard` decides by the extension set
   (`PLAN_REQUIRED_ROOT_EXTENSIONS`), the set `DEF-961` says misses `.mjs`. Then
   `tools/cc/execution_plan.py create` runs, and the same Write is allowed.
4. Ten PostToolUse fires on stack source files raise `write_count`.
5. Stop runs with `ESPALIER_STOP_GATE=full` and `ESPALIER_STOP_GATE_TEST_CMD` set to the stub
   spelled as that stack's test command (`pytest`, `npm test`). Gate 1 blocks on the stub's
   exit 1. With the stub at 0, Gates 2 and 3 arm on step 4's count.
6. A real `git commit`.
7. ConfigChange: a kill-switch written into `.claude/settings.local.json` is denied by
   `config_guard`.
8. `python -m espalier.cli upgrade --execute`.
9. SessionStart `startup` again. The banner reads the state steps 1 to 8 left.

Each step asserts its own decision **and** the cross-step read.

**Record today's Node behaviour as it is.** Gates 2 and 3 do not arm on `.mjs` writes
(`DEF-961`), and Gate 1 is dormant without the override. Record each as a `strict=True` xfail
naming its row, so the fix that closes the row flips it loud.

**Mutations:**

- Delete `reflect_trigger`'s increment in a scratch copy, and step 5's Gate 2 block reds on
  the Python tree.
- Apply 0-B's mutation (the Node extensions deleted from the source set), and the Node
  chain's `.js` steps red. That is the stack axis's earn-the-red: the differential that read
  0 of 327 at authoring must read at least one here.

### 2-D The Walk by stack

`tests/test_adopter_lifecycle_diagnostics.py::walked` becomes parametrised over
`("python", "node")`. Its tree comes from `build_adopter_tree(stack=..., tree="git")`; the
Walk runs `init` itself. It gains `upgrade`
(dry-run, then `--execute`) between `scan` and the `doctor` detours.
`TestTheWalkRan::test_every_verb_exited_as_documented` names both new verbs.

`::api_walked` stays Python (it is about `api-reviewer`).

Keep the module's `# slow-exempt:` line honest. Re-measure it, since the module now walks two
trees. At 0-F's per-stack figure it may need the `slow` marker instead.

**Mutation:** make `upgrade --execute` exit 1 on a non-Python fingerprint in a scratch copy,
and the Node walk reds.

### 3-A The perturbed cell (non-required, in `test.yml`) — *fix shape, untested; home settled by Decision 1*

**Recipe:** after install, build the Store-stub host (0-C's command) under
`$RUNNER_TEMP/axis hosts`, then append its directory to `$GITHUB_PATH`. Run the tier the PR
earns, with `PYTEST_ADDOPTS: --durations=25 --basetemp='${{ runner.temp }}/axis basetemp/bt'`,
through `python scripts/proof_tier.py --run --tier "$TIER" --base "${BASE_SHA:-HEAD}" --leg parallel`.

Optionally, `actions/checkout` with `path: "spaced root/espalier-harness"` and every step's
`working-directory` set to it (0-C decides whether the space reds anything).

**From the foundation lane's 0-C, for this cell:**

- **Create `--basetemp`'s parent first.** pytest makes only the leaf. Without the parent,
  every test errors with `FileNotFoundError`.
- **Probe the shim on the child's PATH.** Resolve the shim with
  `shutil.which(name, path=<the PATH you set>)` before trusting it (Risk 4). The first 0-C
  probe ran a bare name and reported `python3` absent while the shim was in force.
- **A nested pytest inherits `PYTEST_ADDOPTS`, and with it `--basetemp`.** A child pytest
  that asks for a temp dir empties the explicit basetemp, which holds every xdist worker's
  directories. Probable, not driven. Sites seen:
  - `espalier/selfcheck.py::run_selfcheck`, driven by `tests/test_selfcheck_channel.py`;
  - `tests/test_declared_limits_contract.py::test_every_cited_pin_runs_and_passes_on_this_host`;
  - `tests/test_golden_examples.py`.
  `tests/test_axis_registry.py` drops the variable for its children. The cell should isolate
  this inside the tool (one writer per shared state) before it lands.
- **The override pair's red is a spaced interpreter, not a spaced checkout** (Task 0 at
  execution). On CI it reds only if the venv lives inside the spaced checkout.

**Land it with the test-fixture reds 0-C named fixed:**

- the `test_merge_settings` row wires the interpreter that answers, not a literal `python3`;
- the five `tests/test_run_pack_chain.py` argv sites use `sys.executable`.

A **product** red is a row plus a registry gap (Scope (out)).

**Locally:** the cell's slice reproduces with the shim and `--basetemp` on any POSIX host,
**serially or with a capped `PYTEST_XDIST_AUTO_NUM_WORKERS`**. Never `-n auto` on an 8 GB box.

**Proof:**

- The cell is green on the lane's own pull request.
- Its registry cells (`host`/`store_python3`, `root`/`spaced`) are proven.

**Mutation:** revert the `test_merge_settings` fixture fix, and the cell reds on Linux, which
no existing cell does.

### 3-B `wheel_smoke --stack --spaced-root`

- `scripts/wheel_smoke.py::parse_args` gains `--stack {none,python,node,go,rust}` (default
  `none`, today's empty tree) and `--spaced-root`.
- `run_smoke` puts the scratch under `<mkdtemp>/spaced root/` when asked. Before `_git_init`
  it writes the `adopter-<stack>` row of `tests/_stack_trees.py`, loaded by path through
  `importlib.util.spec_from_file_location` from `REPO_ROOT / "tests"`. The script stays
  standalone, and the table stays stdlib-only.
- When the table is absent, it fails with `format_failure`. It never falls back silently.
- `release.yml` gains one leg: `--wheel "$WHEEL" --skip-build --stack node --spaced-root`.

**Proof:** `tests/test_wheel_smoke.py` gains a row for the two flags.

**Mutation:** make `--stack node` write nothing, and the new row reds.

### 3-C The dirty-machine cell (`DEF-937`)

`tests/test_dirty_machine_install.py` builds a tree with:

- `build_adopter_tree(stack="python", tree="git", branch="master")`;
- under a spaced parent;
- a pre-existing `.claude/settings.json` carrying the adopter's own hook and allow rule, and
  `.claude/agents/my-reviewer.md`;
- a stale `espalier` stub first on PATH that prints an old version and records each call.

It drives `init`, `doctor` and `upgrade` through `sys.executable -m espalier.cli` and asserts
on what the adopter keeps and what the harness wires.

**Seed its oracles from the first Windows walk's `# VERIFICATION PASS` appendix**, as the row
says (`memory/windows-walk-output-routing.md` points to it). **Pending (Decision 4):** the five
platform-independent findings are not on the authoring box. The coordinator mailed the Air
for them on 2026-10-06 (request `20261006T083426Z-win-876895`). Before writing 3-C's
assertions, the executor runs `python tools/cc/mail.py inbox` and reads the reply. Until it
arrives, 3-C's oracles are pending and 3-C does not land. If the reply never comes,
re-raise rather than guess.

It runs in the not-heavy suite, so `portability.yml` carries it on three OSes. That is
`DEF-937`'s "OS matrix" home, with no new job.

**Mutation:** make `init` overwrite an existing `.claude/settings.json` hook in a scratch copy,
and the cell reds.

### 3-D The portability collectors (with `DEF-1049`)

In `tests/test_portability_contract.py`. Each collector earns its red on a planted line in a
temp tree, the `DEF-1049` probe's form.

1. **Skills and workflow bodies.**
   - `TestOperatorDocsPortability`'s population gains `.claude/skills/*/SKILL.md` and
     `.claude/workflows/*.js`.
   - For skills, use `DEF-1049`'s command-shaped check: a backticked `python3` followed by
     `tools/`, `scripts/` or `-m espalier`. `hook-authoring`'s quoted guard patterns and its
     `/tmp/` examples stay allowed.
   - Spell `python` at the two `blueprint-authoring` lines (`_recall.py`,
     `sister_site_probe.py`), then run `python scripts/sync_claude_mirrors.py`.
2. **Command-body code blocks.** Fenced shell blocks in shipped command, skill and agent
   bodies: a bare `python3` at command position, outside `shell_resolver_line`'s canonical
   form. Before adding any GNU-only or BSD-only flag ban, count its hits (zero hits and no
   post-cut finding means it is not added; a ban list of hypotheticals is noise).
3. **Workflow YAML.** A `run:` step in `.github/workflows/*.yml` (and the shipped
   `espalier/assets/github/workflows/harness-guard.yml`) whose job's `runs-on` can be a
   Windows runner names no bare `python3`. Hits today: zero (`harness-guard.yml`'s one
   `python3` step runs on ubuntu). This collector is regression-only, and its earn-the-red is
   the planted line.
4. **Subprocess argv and probe text.** An argv list literal opening with a bare `'python3'` or
   `'python'`, in `espalier/`, `tools/cc/`, `scripts/` and `tests/`. Exempt `tests/fixtures/`
   (the two `'python'` hits are scanner corpus) and `espalier/_vendor/`. Also cover each
   `LEDGER_PROBES.json` `-c` body. Hits today:
   - the five `tests/test_run_pack_chain.py` sites (fixed in 3-A);
   - `DEF-411a` and `DEF-412h`, re-pinned in-lane with `ledger_row.py repin --probe-cmd`
     (`sys.executable` inside the body), each probe driven first. Both read
     `task-packs/Done`, so the re-pin runs on a clone that carries it (the Windows clone does
     not; both read UNRESOLVED there).

### 3-E The `newline=` rule — *only at 0-E's scope*

If 0-E licenses it, `espalier/scanners/encoding_contracts.py` gains one shape:

- an append-mode or read-then-rewrite text write of an existing file, with no `newline=`;
- its own severity (for instance `NEWLINE_TRANSLATED`);
- an earn-the-red fixture and a must-not-trip negative corpus (a fresh file the harness
  owns);
- the zero-finding posture kept, with the sites it finds fixed through
  `_atomic_io`/`_dominant_line_ending` (the `DEF-940` pattern).

If 0-E's stop condition fires, nothing lands, and Landing says why.

### 3-F The blind-axis step — `docs/RELEASE_CHECKLIST.md`

A new step before Tier 3. Run `python tests/_axis_registry.py` and paste its table into the
release notes. The table lists:

- the instruments: `fresh_clone_gate`, `final_release_matrix` stages 1 to 6, `wheel_smoke`'s
  `release.yml` legs, `test.yml`'s cells, the perturbed cell, `portability.yml`'s three cells
  and `clean-checkout.yml`;
- for each instrument, the value of each axis: stack, the `python`/`python3`/`py` names that
  answer, a spaced root, single-event or session.

An axis that every instrument ran at **one** value is a blind axis, and the notes say so in
those words.

The step names its owner (whoever cuts the tag) and its exit: a blind axis is disclosed, not
blocking.

**Mutation:** remove a proven cell, and the printed table names that axis blind.

### 4-A Red-team (budgeted; see Risks)

`code-reviewer` and `failure-mode-reviewer` on a snapshot clone built from the diff against
HEAD, with edits frozen. Ask each for the mutation that survives, not for approval:

- a registry cell that collects but does not vary its value;
- a wired launch that silently falls back to `HOOK_PYTHON`;
- a selfcheck mirror that drifts from the table;
- a cell that is green because the shim never reached PATH.

One fix batch follows.

## Affected symbols

Two changed symbols are declared by a more specific neighbour, because their bare names are
generic words the walk would grep across the tree (measured at authoring: 241 hits for one, 149
for the other, nearly all prose and argparse calls in unrelated modules):

- the Walk's module fixture `walked` is declared through `TestTheWalkRan`, the test that names
  its verbs;
- `scripts/wheel_smoke.py`'s argument parser is declared through `run_smoke`, which consumes
  both new flags.

### Changed-semantics

- `tests/_adopter_tree.py::build_adopter_tree` (gains `stack=`, `tree=`, `branch=`; default reproduces today's tree)
- `tests/conftest.py::python_repo` (and `ml_repo`, `node_repo`, `typescript_repo`, `go_repo`, `polyglot_repo`: bodies become table writes)
- `tests/test_hooks.py::run_hook` (re-exported from the shared module)
- `tests/test_hook_exec_form.py::TestInitOnTheTwoInterpreterHosts` (its wired launch moves onto the shared runner)
- `tests/test_adopter_lifecycle_diagnostics.py::TestTheWalkRan` (the Walk is parametrised by stack and gains `upgrade`; this test names both verbs)
- `tests/test_portability_contract.py::TestOperatorDocsPortability` (skills and workflow bodies join its population)
- `tests/test_mypy_config_stays_near_strict.py::test_mypy_config_keeps_near_strict_flags` (pins `platform`)
- `tests/test_test_suite_contract.py::test_private_hook_runners_only_shrink` (new ratchet in an existing module)
- `scripts/wheel_smoke.py::run_smoke` (reads the new `--stack` and `--spaced-root` flags; writes the stack's files before `_git_init`; the spaced scratch)
- `scripts/sync_selfcheck_tests.py::BYTE_MIRRORED` (gains the stack table)
- `espalier/scanners/test_loosening.py::_HOOK_INVOKERS` (gains `run_hook_as_wired`)
- `espalier/scanners/encoding_contracts.py::sites_in_source` (only if 0-E licenses 3-E)

### Renamed

- (none -- `run_hook` keeps its name and gains a second home.)

### Added-paths

- `tests/_axis_registry.py`
- `tests/test_axis_registry.py`
- `tests/_stack_trees.py`
- `espalier/_vendor/selfcheck_tests/_stack_trees.py`
- `tests/_hook_runner.py`
- `tests/_hook_runner.py::run_hook_as_wired`
- `tests/test_hooks_as_wired.py`
- `tests/_session_driver.py`
- `tests/test_adopter_session.py`
- `tests/test_dirty_machine_install.py`
- `task-packs/TP-468-adopter-axes.md`

### Removed-paths

- `tests/conftest.py::rust_repo` (no user; its files stay as a table row)
- `tests/conftest.py::rust_repo_with_tests` (no user)
- `tests/conftest.py::node_repo_with_tests` (no user)

## Reach

**How the members were derived:**

- the row's own clauses (`grep -n "^| \`DEF-975\`" task-packs/FORWARD_LEDGER.md`);
- the rows the row names as landing inside it;
- the rows the voice pack's Reach routed here (`DEF-915`, `DEF-947`);
- §C69's scope-out sentence naming this row;
- the collector sibling `DEF-1049`;
- the probe-text hits from Appendix A, line 6.

This is not an absence proof. Another row may name this shape in words no grep above reads.

| Item | Status | Evidence |
|---|---|---|
| `DEF-975` stack axis | **CLOSED by 2-A to 2-D** if 0-B builds | 0-B's own mutation (the Node extensions deleted), 0 of 327 at authoring, reds 2-C's Node chain at its `.js` steps |
| `DEF-975` host axis | **CLOSED by 3-A** if 0-C builds | the cell reds on the reverted fixture fix |
| `DEF-975` session axis | **CLOSED by 2-B and 2-C** if 0-D builds | the counter-deletion mutation reds the chain |
| `DEF-975` release instruments | **CLOSED by 3-B and 3-F** | the blind-axis table prints from the registry; `wheel_smoke` runs a Node tree under a spaced root |
| `DEF-975` collectors | **CLOSED by 3-D**; the `newline=` arm **CLOSED or NOT REACHED by 0-E's measurement** | each collector's planted-line red |
| `DEF-970` | **CLOSED by 1-A** | the native gate reports no issues; the probe flips |
| `DEF-937` | **CLOSED by 3-C** once its oracles are seeded from the Air's reply (Decision 4) | the overwrite mutation reds |
| `DEF-1049` | **CLOSED by 3-D** (folded; kept by Decision 6) | its probe flips to True |
| `DEF-411a`, `DEF-412h` (probe text only) | **CLOSED in-lane** (re-pinned; their defects stay open) | the argv collector reds before the re-pin |
| `DEF-915` | **NOT CLOSED** | 2-B gives its regression test a launch oracle; the fix is in `espalier/cli.py`, its own row |
| `DEF-947` | **NOT REACHED** | a bind-mounted container is not a PATH shape |
| `DEF-968` | **NOT CLOSED** | a spaced checkout in 3-A may show its test half red on Linux; its fix is its own row |
| `DEF-961` to `DEF-965` (§C57) | **NOT REACHED** (consumers) | 2-C records `DEF-961` as a strict xfail; §C57's oracle runs on 2-A's `adopter-node` tree with 2-C's stub-binary PATH |
| `DEF-976` | **NOT REACHED** (the next pack) | its probe tree is 2-A's `adopter-node-pnpm` row; its proof is 2-C's driver |

## Pass criteria

- Appendix A, line 1, prints `['dest', 'stack', 'tree', 'branch']` (or a superset), and the
  row's probe prints `1`.
- Every test this pack adds was seen red against its named mutation, recorded in Landing.
  For each, the mutation reconstructs the pre-fix state where one exists.
- **No assertion in an existing test is weakened, and no fixture body changes a byte** (the
  table rows are byte-identical to the fixtures they replace). Strengthening an existing test
  is allowed and recorded.
- `python tests/_axis_registry.py` prints a table in which `stack`, `host` and `session` each
  have at least two proven values. Any axis left at one value is named in Landing with its
  0-B, 0-C or 0-D measurement.
- The perturbed cell is green on the lane's pull request and reds on the reverted fixture fix.
- `tests/test_selfcheck_tests_parity.py` is green; `python scripts/sync_selfcheck_tests.py`,
  `python scripts/sync_claude_mirrors.py` and `python scripts/sync_vendor_cc.py` leave no
  diff.
- The private-runner census never rises above its seeded baseline.
- `mypy tools/cc/hooks/` reports no issues on Windows and on POSIX; `ruff check .` is clean.
- `python scripts/proof_tier.py` names the tier this diff earns, and it is green. Expect `full`,
  because `.github/workflows/` and `scripts/` change.
- No new test needs `-n auto`. Each new module builds its trees once per module or session,
  and the local recipe in 3-A runs serially.

## Risks — what this pack most likely got wrong

1. **The registry's id rule may be too weak or too strong.** A value carried in a node id is
   a proxy for "this test varies along the axis". A test can carry `[node]` and build a Python
   tree. The red-team is asked for exactly that mutation. If it survives, the rule needs a
   second witness: the builder records the stack it built, and the contract reads it.
2. **The fold may move a byte.** About 40 fixture users, and the scanner tests read the
   fixtures' exact content. The byte-identity test in 2-A is the guard. Run it before
   anything else lands on the table.
3. **The selfcheck mirror may not import a sibling** under `espalier selfcheck`. 2-A names the
   fallback.
4. **The cell may be green because the shim never reached PATH.** The cell's first step after
   the shim asserts that `python3 -c pass` exits non-zero and `python -c pass` exits zero, and
   fails loudly otherwise.
5. **Cost.** Each adopter tree is about 5.5 s here, and 2-B's matrix is stacks × host shapes.
   Decision 2 holds the expensive cells to Python and Node, with Go and Rust as builder plus
   init-exits-zero cells only. 0-F's figure decides whether even that fits the cell's budget.
6. **Two writers on one tree** (`memory/one-writer-per-shared-state.md`). The session-scoped
   `adopter_tree` fixture is read by 28 test functions in 7 modules at authoring
   (`git grep -l -w adopter_tree -- tests` lists them, plus the fixture's definition in
   `tests/conftest.py` and one mention in `tests/test_test_suite_contract.py`), and an
   xdist worker runs several of them in one session. 2-C's chain writes into its tree (flags, a plan, a commit, an upgrade), so
   mutating the shared tree would change what a later module in that worker reads. 2-C builds
   its own module-scoped tree and never takes the shared fixture.
7. **The row's "upgrade" was never in the Walk.** Both 2-C and 2-D now drive `upgrade`. The
   overlap is deliberate: 2-D reads the verb's output as an adopter reads it, while 2-C reads
   the state it leaves for the next SessionStart. If the red-team finds the two assert the
   same thing, drop 2-D's addition and say so in Landing.

## Decisions (the operator's answers to the authoring questions, 2026-10-06)

The pack was approved on 2026-10-06 with these answers. Each is recorded with its reason so
the executor does not re-ask. Re-open one only on a measurement that falsifies its reason,
and re-raise with that measurement.

1. **The perturbed cell lives in `test.yml`, non-required.** Reason: there it runs the tier
   every pull request earns, beside the `test` cells. `portability.yml` runs only on Python
   or packaging changes. A required name that never reports parks every pull request, so
   promotion to required waits for a run of greens.
2. **The expensive cells run the `python` and `node` stacks only** (2-B's matrix, 2-C's
   driver, 2-D's Walk). Reason: those two have downstream consumers (`DEF-976` and §C57 on
   Node; every current caller on Python), and each adopter tree costs about 5.5 s. Go and Rust
   get the table rows, a builder cell and an init-exits-zero cell.
3. **`tree=` is the build depth:** `"files"`, `"git"`, or `"adopter"` (full `init` plus
   `install-ci`). Reason: the measured 5.4–5.9 s per real build forces the fold to the
   file-set layer, and the depth knob is what lets the fixtures stay cheap.
4. **`DEF-937`'s five platform-independent findings are not on the authoring box.** The
   coordinator mailed the Air for them on 2026-10-06 (request `20261006T083426Z-win-876895`).
   3-C's oracles are **pending that reply**. The executor reads `python tools/cc/mail.py inbox`
   for it before writing 3-C's assertions. 3-C does not land on the four conditions alone
   while the reply is outstanding. If it never comes, re-raise rather than guess.
5. **A product red an axis shows** is a `strict=True` xfail naming its row where a row
   exists, and a registry gap (with the row filed) where none does. Reason: the xfail flips
   loud when the row's fix lands, and a gap is quiet.
6. **`DEF-1049` stays folded in.** Reason: root `CLAUDE.md` Core Rule 12. It is one more
   member of the collector population 3-D widens, and a class is not patched one instance
   at a time.
7. **The lane split is decided at execution.** The recommended split, in three lanes:
   - **Foundation:** Task 0, 1-A, 1-B and 2-A. Every later lane builds on the registry and
     the stack table.
   - **Session and stack:** 2-B, 2-C and 2-D.
   - **Release and collectors:** 3-A to 3-F, then the red-team (4-A) on each lane's own diff.

   Each lane runs its own Task 0 slice for the axes it closes, and its own reviewers.

## Downstream consumers (what the next packs read from this one)

- **`DEF-976`** (stack registry):
  - `tests/_stack_trees.py`'s `adopter-node` and `adopter-node-pnpm` rows (its probe tree);
  - `build_adopter_tree(stack="node")`;
  - 2-C's driver, where its "Stop gate 1 and `/preflight` arm from the table" flips the
    recorded xfails;
  - the registry's `stack` cells, where its table rows become proven cells.
- **§C57** (`DEF-961` to `DEF-965`): its one oracle runs on `build_adopter_tree(stack="node")`
  with 2-C's stub-binary PATH for `ruff` and `pytest`, and on `run_hook_as_wired` for the hook
  predicates. It builds no competing tree.
- **§C58:** `build_adopter_tree(stack="python")` is the "init'd tree with no `espalier/`" its
  fences run on. The current default is already that shape.
- **`DEF-915` and `DEF-947`:** `run_hook_as_wired` is the launch oracle their regression tests
  assert through.

## Files touched

- **New:**
  - `tests/_axis_registry.py`, `tests/test_axis_registry.py`, `tests/_stack_trees.py`
  - `espalier/_vendor/selfcheck_tests/_stack_trees.py` (by the sync script)
  - `tests/_hook_runner.py`, `tests/test_hooks_as_wired.py`
  - `tests/_session_driver.py`, `tests/test_adopter_session.py`
  - `tests/test_dirty_machine_install.py`
  - this pack
- **Modified:**
  - `pyproject.toml` (`[tool.mypy]`; package-data if the glob misses the table)
  - `tests/_adopter_tree.py`, `tests/conftest.py` (fixtures; `_MARKER_RULES` for the new modules)
  - `tests/test_hooks.py`, `tests/test_hook_exec_form.py`
  - `tests/test_hooks_worktree_checkouts.py`, `tests/test_nested_repo_litter.py`,
    `tests/test_reinject_pins.py`, `tests/test_subprocess_env_isolation.py` (import from the
    shared module)
  - `tests/test_adopter_lifecycle_diagnostics.py`
  - `tests/test_portability_contract.py`, `tests/test_mypy_config_stays_near_strict.py`
  - `tests/test_test_suite_contract.py`, `tests/test_wheel_smoke.py`
  - `tests/test_merge_settings.py` and `tests/test_run_pack_chain.py` (the fixture reds)
  - `scripts/wheel_smoke.py`, `scripts/sync_selfcheck_tests.py`
  - `espalier/_vendor/selfcheck_tests/conftest.py` (by the sync script)
  - `.github/workflows/test.yml` (the perturbed cell, Decision 1)
  - `.github/workflows/release.yml`
  - `.claude/skills/blueprint-authoring/SKILL.md` and `.claude/skills/hook-authoring/SKILL.md`,
    with their mirrors (by the sync script)
  - `espalier/scanners/test_loosening.py` (the invoker set) and its scanner test corpus
  - `docs/RELEASE_CHECKLIST.md`, `CHANGELOG.md`
  - `task-packs/FORWARD_LEDGER.md`, `task-packs/LEDGER_PROBES.json` (the strike and two re-pins)
  - `espalier/scanners/encoding_contracts.py` (only if 3-E lands)
- **Unmodified on purpose:**
  - `tools/cc/hooks/` (no hook edit; the axes find, the rows fix)
  - `espalier/analyze.py`, `espalier/settings_profiles.py`, `tools/cc/hooks/_hook_utils.py::SOURCE_LANGUAGE_EXTENSIONS` (`DEF-976`'s)
  - `scripts/final_release_matrix.py` (Scope (out))
  - `.claude/agents/test-writer.md` (its `run_hook` is a template an adopter's suite defines for
    itself, not a pointer to this repository's helper)
  - `docs/SHARP_EDGES.md` (its `tests/test_hooks.py::run_hook` citation keeps resolving through
    the assignment 2-B keeps)

**Authoring scope-check** (2026-10-06, `python -m espalier.cli scope-check` on this file):
exit 2, 26 files in scope, 26 symbols. After the two edits above it surfaced, the remaining gap
lines are:

- prose mentions in `docs/CONVENTIONS.md`, `espalier/surface_impact.py` and
  `memory/CONVERGENCE_LEDGER.md` (a record);
- the `docs/SHARP_EDGES.md` citation (kept resolving by 2-B's assignment);
- the test-writer template's two deployed mirrors.

0-B at execution re-runs it on the live tree. Accept that gap with this reason only if the list
is unchanged.

## Sub-task ordering

The order below is the whole pack's. When it runs as the three lanes Decision 7 recommends,
each lane takes its own contiguous slice:

- foundation: steps 0 to 4;
- session and stack: step 5;
- release and collectors: steps 6 to 9.

Each lane runs its own pre-flight and red-team.

0. **Pre-flight**, the four gates in `memory/task-packs.md`, per pack immediately before
   execution:
   - 0-A: `code-reviewer` with `tools/cc/pack_artifact_checklist.md`;
   - 0-B: `espalier scope-check task-packs/TP-468-adopter-axes.md`;
   - 0-C: `python tools/cc/sister_site_probe.py --json`;
   - 0-D: `espalier surface-impact task-packs/TP-468-adopter-axes.md`.

   Then `python tools/cc/execution_plan.py create` (plan_guard), and the claims pre-flight on
   the mail channel for `tests/conftest.py` and `.github/workflows/`.
1. **Task 0** (0-A to 0-F). Checkpoint: the per-axis verdicts recorded in `reports/tp468/`.
   Stop here on any refutation.
2. **1-A.** Checkpoint: `mypy tools/cc/hooks/` and `pytest -q tests/test_mypy_config_stays_near_strict.py`.
3. **1-B.** Checkpoint: `pytest -q tests/test_axis_registry.py`.
4. **2-A.** Checkpoint:
   `pytest -q tests/test_selfcheck_tests_parity.py tests/test_fingerprint.py tests/test_analyze.py tests/test_scanners.py tests/test_non_python_consumer_init.py tests/test_adopter_pointer_resolution.py`,
   plus the selfcheck run.
5. **2-B,** then **2-C,** then **2-D.** Checkpoint: the four new or changed modules serially,
   plus `tests/test_test_suite_contract.py`.
6. **3-D** (it reds 3-A's fixture sites first, which is its earn-the-red), then **3-A**, then
   **3-B**, **3-C** and **3-E.** Checkpoint: the enumerator pins
   (`tests/test_test_suite_contract.py tests/test_marker_taxonomy.py tests/test_portability_contract.py`)
   and the `scripts/archive_probe.py` drive of every touched test file.
7. **3-F.** Checkpoint: `python tests/_axis_registry.py`.
8. **4-A red-team,** one fix batch.
9. The tier the diff earns, under `nohup` with `EXIT=$?` appended (never `-n auto` on an 8 GB
   box; cap `PYTEST_XDIST_AUTO_NUM_WORKERS`). Then the ledger strike, the commit, and
   `/handoff`, which ships.

## Estimated effort

| Step | Estimate |
|---|---|
| Task 0 | half a day (0-C needs a POSIX host or a dispatch) |
| 1-A and 1-B | 1.5 h |
| 2-A | half a day (the byte-identity fold and the mirror) |
| 2-B | half a day |
| 2-C | half a day |
| 2-D | 1 h |
| 3-A | 3 h, plus a CI round-trip |
| 3-B and 3-C | 3 h, plus the walk-record seeding |
| 3-D | 3 h |
| 3-E | 1 h, or 0 if 0-E stops it |
| 3-F | 1 h |
| Red-team and fix batch | half a day |

Total about four days of lane time. Pack budgets on this tree have run about 2.7 times over
on the one pack measured, so read this as a floor. Decision 7's split does not shrink the
total; it shrinks each review.

## Landing

- State: DRAFT (foundation lane landed on `lane/adopter-axes-foundation`, 2026-10-06; the
  session-and-stack lane, 2-B to 2-D, and the release-and-collectors lane, 3-A to 3-F, are
  open)
- Commits (foundation lane):
  - `b92ce7d` Task 0 record
  - `68689b5` 1-A
  - `cb2ba51` 1-B
  - `44748db` 2-A
  - the review fix batch, the commit that adds this stanza
  - `cb2ba51` and `44748db` alone red
    `tests/test_test_quality.py::TestContractRationale::test_every_file_has_rationale_docstring`
    (two docstrings lacked a rationale anchor). The fix batch fixes it, so the lane is green
    at its head, not at every commit.
- Suite (Windows host, serial, five files at a time, no `-n`; the full tier is CI's):
  - 2-A's 40 files: 1,726 passed, 22 skipped, 2 xfailed, 0 failed;
  - the contract tier over its 186 files: 4,248 passed, 75 skipped, 1 xfailed and 1 failed
    (the rationale-docstring red above, fixed and re-run green);
  - the fix batch's own modules: 67 passed, 1 skipped, 2 xfailed;
  - the ledger tests: 350 passed, 3 skipped;
  - the touched test files driven in an extracted release archive (`scripts/archive_probe.py`):
    48 passed, 2 xfailed;
  - `mypy tools/cc/hooks/` clean both bare and with `--platform linux`;
  - `ruff check .` and the provenance census clean.
- Earn-the-red:
  - 1-A: the platform pin red against the unpinned config. The Windows-arm pin red on a call
    planted in `relaunch_hint`'s Windows branch.
  - 1-B:
    - the launcher-only write-guard test named as `host/launcher_only`'s proof red twice (the
      id rule and the floor);
    - mutants killed: a substring match, the collect check dropped, any parameter accepted,
      id tokens accepted, marks ignored, a run check that passes everything, an orphan host
      cell, a stack row with no cell.
  - 2-A:
    - a text-mode `write_stack` (11 reds on Windows);
    - an extra directory in one fixture;
    - the table dropped from `BYTE_MIRRORED` (the parity test and the new pin);
    - the `print` line and a `_cache_*` helper changed in the `python` row (the scanner tests).
    - Survived: `except:` changed to `except Exception:`, which
      `test_exception_scanner_finds_swallowed` accepts.
- Red-team: `code-reviewer` (REQUEST CHANGES) and `failure-mode-reviewer` (REQUEST CHANGES:
  0 regressions, 3 gaps, 5 rough edges), both on the lane's diff with edits frozen. One fix
  batch:
  - the rule moved to parameters, marks and a run check;
  - the rosters checked both ways;
  - `spaced_interpreter` moved to the root axis, and a `tree/crlf` gap added;
  - the fixture roster derived from the conftest;
  - the xfail limited to `AssertionError`;
  - the Windows-arm pin added;
  - `DEF-975`'s probe re-pinned.
  Rejected, with reasons:
  - a floor compared against the merge base (it needs a raw git population call the suite
    routes through its oracle, and the in-file ratchet is the precedent);
  - the nested-`PYTEST_ADDOPTS` helper shared now (the hazard exists only under 3-A's cell;
    recorded in 3-A);
  - a reported duplicate line (not in the file).
  Open for the operator: whether `go` and `rust` count as proven by their install cells.
- Reach (foundation lane):
  - `DEF-970` closed.
  - `DEF-975` open: its probe was re-pinned to the registry's stack, host and session floor,
    and it prints `1`.
  - 0-E's `newline=` arm is **not reached**: 16 sites, over the 10-site bound, and ownership
    needs a judgement at each site.
- Date: 2026-10-06 (authored; foundation lane landed)

## Appendix A — the census instrument

A measuring instrument, not a deliverable. Save it outside the tree (for instance
`<scratch>/tp468_census.py`) and run it from the repository root with the suite's interpreter.

Output at `fc742de` on the Windows host:

```
1 build_adopter_tree params: ['dest']
2 stack fixtures: {'python_repo': 31, 'ml_repo': 3, 'node_repo': 2, 'rust_repo': 0, 'rust_repo_with_tests': 0, 'typescript_repo': 3, 'go_repo': 2, 'polyglot_repo': 1, 'node_repo_with_tests': 0}
3 private hook runners: 57 functions in 34 files; argv[0]: {'sys.executable': 53, 'HOOK_PYTHON': 4}
4 init-driving helpers: 46 in 31 files; writing a non-Python manifest: 0
5 text-mode writes (total, with newline=): {'espalier': (162, 3), 'tools': (24, 4), 'scripts': (16, 2), 'tests': (3029, 10), 'bench': (35, 0)}
6 bare 'python3' argv literals: {'tests/test_run_pack_chain.py': 5} | probe bodies: ['DEF-411a', 'DEF-412h']
```

Definitions, stated before the numbers:

- A **runner** is a non-test function that calls `subprocess.run`, `Popen`, `check_output`,
  `check_call` or `call` with a literal argv whose first element is not `'git'`, and whose
  source mentions the hooks directory.
- An **init driver** is a non-test function whose source calls `cmd_init(` or spawns
  `espalier.cli` or `espalier` with `'init'`.
- A **fixture user** is a test-module function with a parameter of that name. Line 2 counts
  parameters, not `usefixtures` strings.

```python
"""Adopter-axes census: re-derives every count the adopter-axes pack cites. Stdlib only;
run from the repository root with the interpreter that runs the suite."""
import ast
import inspect
import json
import shlex
import sys
from collections import Counter
from pathlib import Path

T = Path("tests")
SPAWN = {"run", "Popen", "check_output", "check_call", "call"}


def parse(p):
    try:
        return ast.parse(p.read_text(encoding="utf-8-sig"))
    except (SyntaxError, UnicodeDecodeError):
        return None


def callee(n):
    """The spawn name, only when called on the subprocess module (any alias the suite
    uses) or imported bare from it; a local helper named `run` is not a spawn."""
    f = n.func
    if isinstance(f, ast.Attribute):
        return f.attr if ast.unparse(f.value) in ("subprocess", "sp") else ""
    return getattr(f, "id", "") if getattr(f, "id", "") in ("Popen", "check_output", "check_call") else ""


def argv0(n):
    a = n.args[0] if n.args else None
    if isinstance(a, (ast.List, ast.Tuple)) and a.elts:
        return ast.unparse(a.elts[0])
    return None


# 1. the builder's parameters (the row's probe)
sys.path.insert(0, "tests")
import _adopter_tree  # noqa: E402
print("1 build_adopter_tree params:", list(inspect.signature(_adopter_tree.build_adopter_tree).parameters))

# 2. *_repo stack fixtures in conftest and their users (a parameter of that name)
conf = parse(T / "conftest.py")
fixtures = [f.name for f in conf.body if isinstance(f, ast.FunctionDef) and "_repo" in f.name
            and f.name not in ("harness_repo", "initialized_repo_root")
            and any(ast.unparse(d).startswith("pytest.fixture") for d in f.decorator_list)]
users = Counter()
for p in T.rglob("test_*.py"):
    for fn in ast.walk(parse(p) or ast.Module(body=[], type_ignores=[])):
        if isinstance(fn, ast.FunctionDef):
            for a in fn.args.args:
                if a.arg in fixtures:
                    users[a.arg] += 1
print("2 stack fixtures:", {f: users[f] for f in fixtures})

# 3. private hook runners: non-test functions that spawn and mention the hooks dir
runners, interp = [], Counter()
for p in sorted(T.rglob("*.py")):
    tree = parse(p)
    for fn in ast.walk(tree) if tree else []:
        if not isinstance(fn, ast.FunctionDef) or fn.name.startswith("test_"):
            continue
        heads = {argv0(n) for n in ast.walk(fn) if isinstance(n, ast.Call) and callee(n) in SPAWN}
        heads.discard(None)
        heads -= {"'git'"}
        src = ast.unparse(fn)
        if heads and ("hooks" in src or "HOOK" in src.upper()):
            runners.append(f"{p.name}::{fn.name}")
            interp.update(heads)
print(f"3 private hook runners: {len(runners)} functions in {len({r.split('::')[0] for r in runners})} files;"
      f" argv[0]: {dict(interp)}")

# 4. helpers/fixtures that drive `init` on a scratch tree
drivers = []
for p in sorted(T.glob("*.py")):
    tree = parse(p)
    for fn in ast.walk(tree) if tree else []:
        if isinstance(fn, ast.FunctionDef) and not fn.name.startswith("test_"):
            s = ast.unparse(fn)
            if "cmd_init(" in s or (("'espalier.cli'" in s or "'espalier'" in s) and "'init'" in s):
                drivers.append((p.name, any(m in s for m in ("package.json", "go.mod", "Cargo.toml"))))
print(f"4 init-driving helpers: {len(drivers)} in {len({d[0] for d in drivers})} files;"
      f" writing a non-Python manifest: {sum(d[1] for d in drivers)}")

# 5. text-mode write sites with no newline= (the prospective rule's population)
tot, nl = Counter(), Counter()
for r in ("espalier", "tools", "scripts", "tests", "bench"):
    for p in Path(r).rglob("*.py"):
        if p.as_posix().startswith(("espalier/_vendor/cc/", "tests/fixtures/")):
            continue
        tree = parse(p)
        for n in ast.walk(tree) if tree else []:
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            name, w = (f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")), False
            if name == "write_text":
                w = True
            elif name == "open":
                idx = 1 if isinstance(n.func, ast.Name) else 0
                m = next((k.value.value for k in n.keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)),
                         n.args[idx].value if len(n.args) > idx and isinstance(n.args[idx], ast.Constant) else None)
                w = isinstance(m, str) and "b" not in m and any(c in m for c in "wax+")
            if w:
                tot[r] += 1
                nl[r] += any(k.arg == "newline" for k in n.keywords)
print("5 text-mode writes (total, with newline=):", {r: (tot[r], nl[r]) for r in tot})

# 6. subprocess argv literals opening with a bare 'python3', in source and in probe -c bodies
def py3_sites(tree, where, out):
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and callee(n) in SPAWN and argv0(n) == "'python3'":
            out.append(where)
src_hits, probe_hits = [], []
for r in ("espalier", "tools", "scripts", "tests", "bench"):
    for p in Path(r).rglob("*.py"):
        if not p.as_posix().startswith("espalier/_vendor/"):
            tree = parse(p)
            if tree:
                py3_sites(tree, p.as_posix(), src_hits)
for pr in json.load(open("task-packs/LEDGER_PROBES.json", encoding="utf-8"))["probes"]:
    try:
        a = shlex.split(pr.get("cmd") or "")
        if len(a) >= 3 and a[1] == "-c":
            py3_sites(ast.parse(a[2]), pr["id"], probe_hits)
    except (ValueError, SyntaxError):
        pass
print("6 bare 'python3' argv literals:", dict(Counter(src_hits)), "| probe bodies:", probe_hits)
```
