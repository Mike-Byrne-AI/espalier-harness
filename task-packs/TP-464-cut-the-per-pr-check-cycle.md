# TP-464 — Cut the per-pull-request check cycle: the heavy stages leave the per-PR tier, the serial leg runs beside the parallel one, and a required re-run never waits on a non-required cell

## Status

- Kind: PACK
- Version target: 0.8.0b3
- Type: CI / infrastructure (workflow, tier script, docs that instruct check names)
- Authored: 2026-10-01, after the TP-462 repair session, at the operator's request
  ("author the pack now, run it once #53 merges"). Executes on a lane branched
  from `main` after PR #53 merges.

## Motivation

The operator asked on 2026-10-01 whether the pull-request workflow's cost is
worth it. Measured on the merged list since the 2026-09-25 cut: 50 pull
requests in six days; a docs-only one merges in 7 to 18 minutes, a full-tier one
in 40 to 130 (typically 45 to 50). A full-tier cell spends its whole time in one
step, the tier itself (queue wait measured at zero on PR #54's run). Inside that
step, two things dominate, both measured on PR #54 (run `36795690840`):

| Component | First-run `test (3.12)` cell (24:48) | Re-run cell (39:48) |
|---|---|---|
| parallel leg (`pytest -n auto`, 16,272 tests) | 16:32 | about 26 min |
| of which `test_stage_one_source_checkout_smoke`, one worker | **848 s (14:08)** | not read |
| serial leg (the wall-clock-budget and timeout-near files, 1,828 tests) | 8:02 | 13:46 |

So the nested smoke is the long pole of the parallel leg in every cell, and the
serial leg is a third of the cell on top. Neither is the suite's size; both are
the recipe's shape. A third cost is structural: `clean-checkout` shares a run
with the required `test` cells, so when one required cell flakes, GitHub refuses
the re-run until every cell of the run has finished (measured 2026-10-01: a
20-minute wait on `clean-checkout (3.10)` before the 3.12 cell could re-run).

The ledger's `DEF-919` row names the smoke's cost and its fix shape. Its claim
that "CI already does the deselection" is **stale**: it predates the 2026-09-25
CI flip, after which every `test` and `clean-checkout` cell runs
`scripts/proof_tier.py --run --tier full`, whose parallel line carries no `-m`
(`scripts/proof_tier.py::_PYTEST` is `("pytest", "-q")`; the workflow's own
comment says the heavy stages "run here and in every clean-checkout cell").

## Scope (in)

- **1-A** The heavy end-to-end stages (`tests/conftest.py::_HEAVY_E2E_TESTS`)
  leave the per-pull-request tier: the full tier's parallel line selects
  `not heavy_e2e`; the stages keep one CI home (the floor-version
  `clean-checkout` cell, which passes a new `--heavy` flag) and one local home
  (the fresh-clone gate's leg on this box's interpreter); the release matrix's
  archive and sdist stages deselect them too (the row's own reach); the
  conftest note that says the deselection lives only in CI is rewritten.
- **1-B** The serial leg runs beside the parallel one: `proof_tier.py` gains
  `--leg {parallel,serial,both}` (default `both`, so every existing command
  line is unchanged), `test.yml` splits the `test` job's run into a
  `test (3.x)` cell running `--leg parallel` and a `test-serial (3.x)` cell
  running `--leg serial`; the docs that instruct the required-check names gain
  the five new names; the branch-protection update is a paste-ready operator
  command, run **after** the pack's own pull request merges.
- **1-C** `clean-checkout` moves to its own workflow file on the floor version
  only, with its own tier computation so a docs-only pull request still skips
  it; a required re-run then never waits on it, and four full-suite executions
  per pull request go away.
- **2-A** Red-team, then one full tier, then the landing.

- Files this scope covers: `scripts/proof_tier.py`, `scripts/fresh_clone_gate.py`,
`scripts/final_release_matrix.py`, `tests/conftest.py`, `tests/test_proof_tier.py`,
`tests/test_final_release_matrix.py`, `tests/test_fresh_clone_gate.py`,
`tests/test_marker_parity.py`, `.github/workflows/test.yml`,
`.github/workflows/clean-checkout.yml`, `CLAUDE.md`, `docs/RELEASE_CHECKLIST.md`,
`docs/INSTALL-CI.md`, `tests/README.md`, `task-packs/FORWARD_LEDGER.md`,
`task-packs/LEDGER_PROBES.json`.

## Scope (out)

- **The live-tree race writers** (the `reports/.cc_surface_gate.json.<hex>.tmp`
  and `espalier_harness-<version>/` artifacts the races line in
  `tests/README.md` names; 31 events logged since 2026-09-06). Its own pack:
  the writers must be located first, and the fix is in the engine and the
  session hooks, not the workflow. Deriving command for that pack:
  `grep -rn "cc_surface_gate.json" tools/cc/hooks espalier scripts | grep -v test`
  and `grep -rn "espalier_harness-" espalier scripts | grep -iv "\.whl"`.
- **Profiling the suite's growth** (9,800 to 18,100 tests in three and a half
  weeks). The `--durations=25` table is already in every CI cell's log; a
  pruning pack reads it after this one lands, when the heavy stage no longer
  tops it.
- **`DEF-981`** (the up-to-date livelock with three lanes in flight): unmeasured,
  and this pack does not change the rule.
- **Portability's matrix** (three OS legs, already `-m "not heavy_e2e"`, already
  its own workflow): untouched; it never blocks a `test.yml` re-run.
- **Dropping the local full tier for engine lanes**: a judgment call for the
  operator, not a mechanism; this pack shortens the local tier instead (1-A
  takes the smoke out of the handoff tier too).

## Task 0 — Verify (may end this pack)

### 0-A The two components are where the minutes go (measured; re-run on the lane)

Oracle, on the most recent full-tier run of `main`'s pull requests:

```bash
RUN=<run id of a test.yml run on a merged full-tier PR>
gh api "repos/Mike-Byrne-AI/espalier-harness/actions/runs/$RUN/jobs?per_page=50" \
  --jq '.jobs[]|select(.name|test("^test \\("))|{name,total:(((.completed_at|fromdateiso8601)-(.started_at|fromdateiso8601))/60|floor)}'
JOB=<one test (3.x) job id from that run>
gh api --allow-escape-sequences "repos/Mike-Byrne-AI/espalier-harness/actions/jobs/$JOB/logs" \
  | sed 's/\x1b\[[0-9;]*m//g' | grep -E "passed.* in [0-9]+\.[0-9]+s|slowest|test_stage_one_source_checkout_smoke"
```

Measured 2026-10-01 on run `36795690840`, job `110158515031`: parallel leg
`16272 passed ... in 992.54s`, serial leg `1828 passed in 482.23s`, the smoke
`848.21s call` at the top of the slowest-25 table.

Refuting results: the smoke under 300 s in two cells means the parallel leg is
bounded elsewhere and 1-A's CI gain is small (keep 1-A for the local tier,
drop its CI claim from the pass criteria); the serial leg under 20 percent of
the cell means 1-B's five extra required checks buy little, so drop 1-B and
re-raise. If both refute, stop: this pack's premise is gone.

### 0-B The `DEF-919` row's CI claim is stale (measured; re-run)

```bash
python3 scripts/proof_tier.py --tier full          # prints the three lines; none carries -m
grep -n "heavy_e2e" .github/workflows/test.yml     # comments only, no argument
python3 tools/cc/check_ledger_probes.py --id DEF-919   # prints STILL_OPEN: neither the tier nor stage 02 deselects
```

Refuting result: a `-m "not heavy_e2e"` on the tier's parallel line or in the
`test` job's run step means the stages already leave the cells and 1-A's CI
half is done; keep only its local and matrix halves.

### 0-C A required re-run waits on the run's other cells (measured 2026-10-01)

Measured: `gh run rerun 36795690840 --failed` answered "is still in progress"
until `clean-checkout (3.10)` finished at 01:05Z; the 3.12 cell had failed at
00:45Z. Oracle for the per-job form, on the next run with a red cell while
another cell runs: `gh run rerun --job <job id>`. Refuting result: the per-job
re-run starts while the run is in progress. Then 1-C's re-run rationale
weakens to the four fewer full-suite executions; keep 1-C on that rationale
and say so in the Landing.

### 0-D The required-check names this pack adds are reportable (contract; re-run)

`pytest -q tests/test_required_status_checks.py` after the docs in 1-B name
`test-serial (3.10)` to `test-serial (3.14)`: the resolver derives the
expectation from the workflow YAML, so a job-id or workflow-name spelling reds
here before branch protection can park a pull request on "Expected -- waiting
for status to be reported". Refuting result: a red naming the new spelling
means the matrix job's check-run name is not what the docs say; fix the docs,
never the protection.

## Relevant memory

Recent pattern, measured: the last three lanes on this surface each found their
defects in the repair, not the original code (the tier's own races in
`tests/README.md`; TP-463's seven contract classes found by the tier after two
reviews; TP-462's bytecode litter found by CI after four green tiers). Expect
the pins, not the workflow, to bite.

| Entry | Where |
|---|---|
| `.github/workflows/` Is a Provenance Shipping Surface | `docs/SHARP_EDGES.md` |
| CI Approval Marker — Trust the Trigger, Not the OR | `docs/SHARP_EDGES.md` |
| Gates the targeted proofs never show | `memory/four-gates-the-targeted-proofs-never-show.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| The three spellings of a required check that never report | `tests/test_required_status_checks.py` (module docstring) |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "github actions
workflow matrix required status checks branch protection"` and `... "proof tier
recipe pinned by test and quoted in the build block"`; re-run rather than trust
this list if the pack has been sitting.

## Implementation

### 1-A The heavy stages leave the per-pull-request tier

**Fix 1 — the tier's parallel line deselects the heavy stages, and `--heavy`
puts them back** *(fix shape, untested -- refuted if `DEF-919`'s probe still
prints `tier=True` after it, which 0-B's third command decides):*

```python target=scripts/proof_tier.py
_PYTEST: tuple[str, ...] = ("pytest", "-q")
_CONTRACT_ARGV: tuple[str, ...] = ("pytest", "-m", "contract", "-q")
#: The heavy end-to-end stages (tests/conftest.py::_HEAVY_E2E_TESTS) leave the
#: per-pull-request tier: the stage-one smoke alone ran 848 s on one xdist
#: worker of a 992 s parallel leg (CI, 2026-10-01). Their one CI home is the
#: floor-version clean-checkout cell and their one local home is the fresh-clone
#: gate's leg on this box's interpreter, both of which pass --heavy.
_NOT_HEAVY: tuple[str, ...] = ("-m", "not heavy_e2e")
```

The `full` entry of `_TIER_ARGVS` gains `_NOT_HEAVY` on its parallel line; a
`--heavy` flag on `--run` drops it (the receipt names which form ran).
Constraint: `FULL_COMMANDS` stays three lines in its default form -- the
gate's receipt check (`scripts/fresh_clone_gate.py::full_tier_command_count`)
and `tests/test_fresh_clone_gate.py` count three, and `tests/test_proof_tier.py`
splits them by prefix -- so `--heavy` and `--leg` are selectors over those
lines, never new lines. The
`clean-checkout` run step and `scripts/fresh_clone_gate.py`'s leg for the
current interpreter pass `--heavy`. The pins that quote the recipe
(`tests/test_proof_tier.py`; the contract that the root `CLAUDE.md` build block
quotes the same lines) move with it: the build block's parallel line gains the
marker expression.

**Fix 2 — the matrix's archive and sdist stages deselect the stages too**
*(fix shape, untested -- the row's own reach; refuted if `DEF-919`'s probe reads
a stage other than `stage_source_archive`, which `--id DEF-919` after the edit
decides):* in `scripts/final_release_matrix.py::stage_source_archive` and
`::stage_sdist`, the child `pytest -q -m "not full_tree"` becomes
`-m "not full_tree and not heavy_e2e"`.

**Fix 3 — the conftest note names the homes** *(docs):* the comment above
`tests/conftest.py::_HEAVY_E2E_TESTS` says the deselection is CI's alone;
rewrite it to name the parallel line, the `--heavy` flag, the clean-checkout
home and the gate leg.

Earn the red: `--run --tier full --heavy` on the lane must collect the smoke and
plain `--run --tier full` must not (`--collect-only -q | grep -c
test_stage_one_source_checkout_smoke` on each argv prints 1 then 0); the
`DEF-919` probe prints its closed value after Fix 1 and Fix 2 and its open value
with either reverted.

### 1-B The serial leg runs beside the parallel one

**Fix 4 — `--leg`** *(fix shape, untested -- refuted if the wall-clock-budget
files still false-fail alone on a shared runner, which the lane's first
`test-serial` cells decide; then the leg stays in the same job and 1-B is
withdrawn with the measurement in the Landing):* `scripts/proof_tier.py --run`
gains `--leg {parallel,serial,both}`, default `both`. `parallel` runs the mypy
line and the `-n auto` line; `serial` runs the `SERIAL_FILES` line; on the
`contract` and `recall` tiers `serial` runs nothing and prints a receipt saying
so with exit 0, because a required check must report on every pull request.

**Fix 5 — the workflow** *(fix shape, untested):* in `.github/workflows/test.yml`
the `test` job's run step passes `--leg parallel`; a new matrix job
`test-serial` (same `needs: tier`, same `if`, same matrix, `fail-fast: false`,
same install) passes `--leg serial`. Check-run names are `test-serial (3.10)`
to `test-serial (3.14)`: a matrix job's bare id never reports, so the docs name
the cells, never the job.

**Fix 6 — the instructing surfaces** *(docs):* the root `CLAUDE.md` Core Rule 10
("eight passing checks"), `docs/RELEASE_CHECKLIST.md`'s required-check list and
its `clean-checkout` sentences, `docs/INSTALL-CI.md` where it names the checks,
`tests/README.md`'s CI paragraph. `tests/test_required_status_checks.py` derives
both halves and is the oracle (0-D).

**Operator step, after this pack's pull request merges** *(not before: the pull
request must pass the set that exists while it is open):*

```bash
gh api -X PATCH repos/Mike-Byrne-AI/espalier-harness/branches/main/protection/required_status_checks \
  --input - <<'JSON'
{"strict": true, "contexts": ["verify", "benchmark", "freshness",
  "test (3.10)", "test (3.11)", "test (3.12)", "test (3.13)", "test (3.14)",
  "test-serial (3.10)", "test-serial (3.11)", "test-serial (3.12)", "test-serial (3.13)", "test-serial (3.14)"]}
JSON
gh api repos/Mike-Byrne-AI/espalier-harness/branches/main/protection/required_status_checks --jq '.contexts'
```

Verify the endpoint's field names against the live API help at execution; the
second command is the read-back and must list thirteen.

### 1-C `clean-checkout` on the floor version, in its own workflow

**Fix 7 — the workflow file** *(fix shape, untested):* `.github/workflows/clean-checkout.yml`,
triggered on `pull_request` and `workflow_dispatch`, with its own copy of the
`tier` job (so a docs-only pull request skips it, as today), a one-cell matrix
(`python-version: ["3.10"]`, `fail-fast: false`), the shallow tagless checkout
the job exists for, and `proof_tier.py --run --tier full --heavy`. The job
leaves `test.yml`. No build-history tag in any comment: the folder is a
provenance shipping surface.

Earn the red: `pytest -q tests/test_required_status_checks.py` with the new
file's matrix missing `fail-fast: false` reds on the file's name; with it,
green. The `workflow-lint` job lints every file in the folder.

### 2-A Red-team

Dispatch `code-reviewer` and `failure-mode-reviewer` on a snapshot clone, both
at once, edits frozen until both report. What this pack is most likely to have
got wrong, for them to bite on: the wall-clock budgets on a shared runner alone
(1-B's refutation); a required-check spelling that never reports (0-D is the
contract, but the branch-protection JSON is hand-typed); the `--leg serial`
receipt on a cheaper tier reading as a vacuous green; the fresh-clone gate
passing `--heavy` on every leg instead of one; a `clean-checkout` workflow that
runs on docs-only pull requests because its tier job was dropped.

## Affected symbols

### Changed-semantics

- `scripts/proof_tier.py::_TIER_ARGVS` (the full tier's parallel line selects `not heavy_e2e`)
- `scripts/proof_tier.py::FULL_COMMANDS` (quoted by the build block; moves with the line)
- `scripts/proof_tier.py::tier_argvs` (selects the lines `--leg` and `--heavy` name)
- `scripts/fresh_clone_gate.py::run_tier` (passes `--heavy` on the current interpreter's leg)
- `scripts/fresh_clone_gate.py::run_leg` (decides which leg is this box's interpreter)
- `scripts/final_release_matrix.py::stage_source_archive` (the child selects `not full_tree and not heavy_e2e`)
- `scripts/final_release_matrix.py::stage_sdist` (same)
- `tests/conftest.py::_HEAVY_E2E_TESTS` (the note above it names the homes; the set is unchanged)

### Renamed

- (none -- `test (3.x)` keeps its name on purpose; the new cells are additions)

### Added-paths

- `.github/workflows/clean-checkout.yml`

### Removed-paths

- (none -- the `clean-checkout` job leaves `test.yml`, the file stays)

## Reach

Members derived by: the ledger rows whose subject is the tier recipe or the
workflow set, `grep -n "proof_tier.py\|test.yml\|heavy_e2e" task-packs/FORWARD_LEDGER.md`
(a clean grep is not an absence proof: the race class has no row of its own yet).

| Item | Status | Evidence |
|---|---|---|
| `DEF-919` | **CLOSED** by 1-A | its probe prints the closed value once both the tier and stage 02 deselect; struck with a reason that re-keys the stale CI sentence |
| the live-tree race class (no row; 31 events in `tests/README.md`) | **NOT REACHED** | the writers are in the engine and the hooks; Scope (out) names the deriving commands for its pack |
| `DEF-981` | **NOT REACHED** | the up-to-date rule is untouched |

## Pass criteria

- No assertion is weakened and no file leaves `SERIAL_FILES` or
  `_HEAVY_E2E_TESTS`; the wall-clock-budget files still run on every full-tier
  pull request, in the `test-serial` cells.
- The heavy stages run in exactly one CI cell per pull request
  (`clean-checkout (3.10)`) and once per cut locally (the gate's leg), and in
  no `test` cell: `--collect-only` on the two argv forms proves 1 and 0.
- `DEF-919`'s probe prints its closed value; the row is struck through the verb
  with the reason naming the stale CI sentence.
- `pytest -q tests/test_required_status_checks.py tests/test_proof_tier.py`
  green; the build-block contract green; `workflow-lint` green on the lane.
- On the lane's own pull request, measured and written into the Landing: the
  `test (3.x)` step durations against PR #54's (24:48 first run); the
  `test-serial (3.x)` durations; whether any serial cell reds on a budget.
- After the merge and the operator's protection update, the read-back lists
  thirteen contexts.

## Files touched

- Modified: `scripts/proof_tier.py`, `scripts/fresh_clone_gate.py`,
  `scripts/final_release_matrix.py`, `tests/conftest.py` (a comment),
  `tests/test_proof_tier.py`, `.github/workflows/test.yml`, `CLAUDE.md`,
  `docs/RELEASE_CHECKLIST.md`, `docs/INSTALL-CI.md`, `tests/README.md`,
  `task-packs/FORWARD_LEDGER.md` and `task-packs/LEDGER_PROBES.json` (the
  strike), `ESPALIER_MEMORY.md` (the handoff's row);
  `tests/test_final_release_matrix.py` (it introspects `stage_source_archive`'s
  body and pins the stages' child argv), `tests/test_fresh_clone_gate.py` (it
  pins the full tier as three commands and the `run_tier` / `run_leg`
  signatures), `tests/test_marker_parity.py` (re-run; it reads
  `_HEAVY_E2E_TESTS`, which does not change).
- New: `.github/workflows/clean-checkout.yml`.
- Deleted: none.
- Unmodified on purpose: `docs/CONVENTIONS.md` (the marker taxonomy; no marker is
  added), `.github/workflows/portability.yml`,
  `.github/workflows/harness-guard.yml` and its asset (the marker gate is not
  this pack's), branch protection itself (an operator action after the merge).

## Sub-task ordering

1. Task 0 (0-A to 0-D); stop and re-raise if 0-A refutes both halves.
2. 1-A Fix 1, earn its red, then Fix 2 and Fix 3; checkpoint: `pytest -q
   tests/test_proof_tier.py` and the `DEF-919` probe.
3. 1-B Fix 4, then Fix 5, then Fix 6; checkpoint: `pytest -q
   tests/test_required_status_checks.py tests/test_proof_tier.py`.
4. 1-C Fix 7; checkpoint: the same two files plus `python -m espalier provenance .`.
5. 2-A red-team; one fix batch; the enumerator pins
   (`tests/test_test_suite_contract.py tests/test_marker_taxonomy.py
   tests/test_portability_contract.py`) because a file was added.
6. One full tier (`python3 scripts/proof_tier.py --run`, the tier the diff earns
   is `full`: workflows and the tier script), then `/commit`, then `/handoff`
   and the lane's one push. The pack's pull request is its own first
   measurement: read the cell durations into the Landing.
7. After the merge: the operator's protection command and its read-back.

## Estimated effort

Budgets, not forecasts (TP-459's ran about 2.7 times over actual):
Task 0 0.5 h; 1-A 1.5 h; 1-B 2.5 h; 1-C 1 h; 2-A 1 h; tier and landing 1 h.
Total 7.5 h.

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
