Comprehensive pre-PR gate — run everything before pushing.

Run each check in order. Stop and report on first failure — with two
exceptions: **Steps 7 and 8 are advisory** and never stop the run.

**Order of proof, stated once.** The steps are numbered by what they check,
not by when the expensive one starts. The executed order is: Step 1, then the
cheap gates whose failures are edits — Steps 3, 4, 5 and 8, each seconds on
its own tree (two of them stand down on an adopter repo) — then, when the diff touches a
trigger surface, Step 6's reviewers, dispatched in one message with edits
frozen until both reports are in; the accepted findings land as one fix
batch; and only then the expensive tier, Steps 2 and 7, once. A full run or a
pin check started before the reviews return is stale the moment they land
(measured 2026-09-06: two full runs started early "for signal" were killed the
same day when the reviews produced edits, and neither had surfaced anything
the targeted proof had not).

## Step 1: Lint (if available)
```bash
if command -v ruff >/dev/null 2>&1; then
  ruff check . || exit 1
elif command -v eslint >/dev/null 2>&1; then
  eslint . || exit 1
elif command -v golangci-lint >/dev/null 2>&1; then
  golangci-lint run ./... || exit 1
elif command -v cargo >/dev/null 2>&1 && [ -f Cargo.toml ]; then
  cargo clippy --all-targets -- -D warnings || exit 1
else
  echo 'No linter detected - skipping'
fi
# Espalier-Harness tree only: the near-strict type gate on the hook layer, the
# one Harness Guard's mypy-hooks job runs. It ran ONLY in CI from 2026-07-23
# and sat red across two pushes unread (2026-09-06); the full proof tier runs
# it too (`python scripts/proof_tier.py --run`), so a hook edit meets it twice.
if [ -f scripts/proof_tier.py ] && command -v mypy >/dev/null 2>&1; then
  mypy tools/cc/hooks/ || exit 1
fi
```

## Step 2: Tests (the expensive tier — run once, after Steps 3-5, 8 and 6)
Run this **once, after Step 6's fix batch has landed** (see the order note at
the top). Until the reviewers return, targeted tests only. Stage every new
file first (`git add -N`): the gates that read `git ls-files` cannot see an
untracked one. On the Espalier-Harness tree the suite has three tiers, and
`python scripts/proof_tier.py` computes which one a diff earns (the same
boundary `/implement-task` step 7 and `/implement-pack` step 6 cite): a diff
that touched no file under `tools/cc/` and no `.py` under `espalier/` outside
its byte-mirrors runs `pytest -m contract -q` here (the tree-wide truth
tests; measured 2026-09-06 at 164 s serial, and the five contracts that
caught that day's batch are all in it), then the recall engine's own test
files as well when it touched a file the pull-recall corpus reads (`memory/`,
the two catalogs, `docs/sharp-edges/`, the principles -- the `recall` tier,
because a corpus edit moves the calibration pins while touching no runtime
path, `DEF-775`), and leaves the full suite to the handoff's preflight; a diff
on the shipped runtime, and every handoff, runs the full suite: on the
Espalier-Harness tree, one command,
`python scripts/proof_tier.py --run --tier full`, which runs both halves
(xdist across the cores with the three wall-clock-budget files left out, then
those three serially: 6:31 and 6:12 on the two clean runs that form was gated
on, against about nineteen minutes serial) and prints a receipt naming both;
a live-tree race, if one ever shows, is a loud error -- rerun the failing file
serially and add it to the races line in `tests/README.md` (self-host only). Elsewhere, the
generic branches below.
```bash
if [ -f scripts/proof_tier.py ]; then
  python scripts/proof_tier.py --run --tier full
elif command -v pytest >/dev/null 2>&1; then
  pytest -q
elif [ -f package.json ] && command -v npm >/dev/null 2>&1; then
  npm test
elif [ -f Cargo.toml ] && command -v cargo >/dev/null 2>&1; then
  cargo test
elif [ -f go.mod ] && command -v go >/dev/null 2>&1; then
  go test ./...
else
  echo 'No test runner detected - skipping'
fi
```

## Step 3: Surface audit + protected-file integrity
```bash
python -m espalier audit .
python -m espalier integrity verify .
```
Two different subjects, and `audit` does **not** cover the second: it checks the
harness *surface*, while `integrity verify` checks the protected-file *manifest*
(`.espalier/integrity.json`). They can disagree — an `audit` reporting `0 errors,
0 warnings` while the manifest is stale is a real, observed state, which is how a
hooks change once left tamper-detection blind for several commits without any gate
noticing. `SessionStart` does warn on drift, but only to **stderr**, so it never
reaches the injected session banner.

Exit codes: `0` clean — **or a repo that was never `espalier init`'d**, which is
guidance, not a failure, matching what `audit` and `doctor` already do on a fresh
checkout · `1` real drift, or a manifest that is missing from an *initialized* repo,
or one that is unreadable · `2` a kill-switch setting is live. Each non-zero case
prints its own remediation on stderr.

For drift you legitimately caused — you edited `espalier/` or a hook — the fix is to
refresh the manifest. That needs maintenance mode set in the **parent shell before
launching**, so it CANNOT be run from this gate:

    # ⚠ Run this in your own terminal, BEFORE launching Claude Code.
    # Do NOT paste it into a Bash tool call: write_guard denies an inline
    # harness-env assignment, and the denial drops any commands bundled with it.
    ESPALIER_MAINTENANCE_MODE=1 python -m espalier integrity refresh .

Then relaunch and re-run this step.

## Step 4: Release gate (Tier 1 — Espalier-Harness self-host only)
```bash
PY=python3; command -v "$PY" >/dev/null 2>&1 || PY=python
if "$PY" -c "import sys; from pathlib import Path; from espalier.surface_contract import is_self_host_repo; sys.exit(0 if is_self_host_repo(Path('.')) else 1)" 2>/dev/null; then
  "$PY" -m espalier pre-release . --skip-tests --skip-parity
else
  echo 'Release gate applies only to the Espalier-Harness source tree - skipping (adopter repo).'
fi
```
This gate is **specific to publishing Espalier-Harness itself**: even with
`--skip-parity` it still runs release-archive cleanliness, count-claim,
version-truth, and required-PyPI-scaffolding checks that have no meaning in
an adopter repo and would hard-fail there. It is therefore skipped
automatically outside the harness's own source tree (`is_self_host_repo`).
`--skip-tests` avoids re-running pytest (Step 2 already did); `--skip-parity`
skips the source-vs-wheel parity gates. On self-host, stop on first non-PASS.

**For a release commit, this is only Tier 1.** Escalate per
`docs/RELEASE_CHECKLIST.md` (self-host only — Espalier-Harness's own release
ladder; not deployed to adopter repos):
- Tier 2: `python -m espalier pre-release .` (drop the skip flags; about 45
  minutes serial -- the test leg measured 2,711 s on 2026-09-23 and the bound
  is twice it).
- Tier 3: full publish-proof matrix (self-host only; see the
  release checklist in your own repo).

Tier 1 SKIPs are env-gated, not failures — the summary line shows
`N passed, M skipped`. Exit 0 means no FAIL, not full
ladder green.

## Step 5: Reflect
```bash
python -m espalier reflect-deep .
```

## Step 6: Diff review
```bash
git diff --stat
```
Review each changed file for anything risky.

**Conditional orthogonal-context review.** `/preflight` is the pre-PR gate — the one
moment the `code-reviewer` (correctness) and `failure-mode-reviewer` (adversarial) triggers
are both meant to fire. But a scripted command executes its listed steps and will not
auto-fire a skill, so dispatch the agents explicitly, gated on what the diff touched. The
trigger surface is `tools/cc/`, `.claude/`, `.github/workflows/`, `bench/`, `scripts/`, or
`espalier/` engine code (`bench/` gates releases; `scripts/` holds the mirror-sync + release
tooling — both governance-load-bearing, and both are Espalier-Harness release-tooling surfaces a
plain `espalier init` adopter doesn't have, so those two rarely trigger in an adopter repo — a
`fuse`-derived repo may carry a small `bench/`/`scripts/` subset). Routine diffs (docs, tests, adopter source) skip it
— keep the gate fast. But a `.claude/` change is NOT routine: it is a governance change, so
it is reviewed, not skipped.

- **Correctness first.** If the diff touches any trigger surface, dispatch the
  `code-reviewer` subagent (`subagent_type='code-reviewer'`) on the diff.
- **Adversarial second — read AFTER code-reviewer, dispatched WITH it.** If the diff also
  ships or modifies a hook, a gate, or a command / agent / skill body, ALSO dispatch
  `failure-mode-reviewer` (the `/adversarial` lens). Its own spec says it "fires AFTER
  code-reviewer agrees the change is correct" — that is a reading order, not a wall-clock
  one: dispatch both in one message, read the failure-mode report second, and never run it
  alone. **Freeze edits while both are out**, then land the accepted findings from both as
  one batch and run Step 2 once. A fix applied mid-review makes the second reviewer
  re-derive its findings against a tree that moved under it (measured twice, 2026-09-06).

Report each by its own vocabulary — the two agents do not share one:
- `code-reviewer`: a **BLOCK** finding, OR a **REQUEST CHANGES** / **NEEDS DISCUSSION**
  verdict, is NO-GO. WARN / NIT are advisory.
- `failure-mode-reviewer`: a **REGRESSION** finding, OR a **REQUEST CHANGES** verdict, is
  NO-GO. GAP / ROUGH-EDGE are advisory.

If you did not dispatch, say so — `Correctness: clean` / `Adversarial: clean` must never
stand in for a review that never ran. This trigger surface AND two-tier dispatch
(code-reviewer then failure-mode-reviewer) are shared with `/implement-pack` step 6 — keep
the two commands in step: same surfaces, same dispatch-together rule, same reading order.

## Step 7: Pin check (advisory — Espalier-Harness self-host only)
```bash
if [ -f scripts/verify_pins.py ]; then
  PY=python3; command -v "$PY" >/dev/null 2>&1 || PY=python
  "$PY" scripts/verify_pins.py || true    # the `|| true` is deliberate -- see below
else
  echo 'Pin check is Espalier-Harness self-host tooling - skipping (not in this repo).'
fi
```
**This step never stops the run.** It is the one exception to the rule at the top
of this file: read the verdict, then continue regardless of it. `verify_pins.py`
exits 0 on every verdict unless you pass `--strict`, and the `|| true` keeps even
a crash from turning it into a gate.

What it does: clone to a throwaway tree, restore the changed **non-test** files
to their `HEAD` state, leave the changed **test** files at their new state, and
run the change's own tests. Nothing going red means no selected test notices the
change being undone — the fix and its proof were written in one pass, and until
this step nothing independent ever checked that the proof *can* fail.

- `PINNED` — a selected test went red. A floor, never a ceiling: one test
  noticed, which is not the same as that test asserting the right thing.
- `UNPINNED` — **a prompt to look, not a defect finding.** A docs-only change
  lands here and owes nothing (measured 2026-08-21: 5 of the preceding 20
  commits; `--calibrate 20` re-derives the table). So does a change whose pin is
  *relational* — a byte-mirror sync, a generated-block parity, a tree-wide cap —
  because a whole-change revert drops both sides at once and they cancel. Re-run
  with `--per-file` before concluding anything from an `UNPINNED`. And a change
  touching no test file has an EMPTY selection — nothing ran, so nothing could
  notice; the report names which of the two you got.
- `NOT_APPLICABLE` — no non-test files changed, so there is nothing to revert.
- `ERROR` — the answer is unavailable (an already-red selection, a merge commit,
  a bad sha). Information, not a stop.

**Why it is advisory, and must stay that way.** Nothing here separates "owes a
pin" from "owes nothing", so `--strict` would fail every docs-only commit for
owing something it does not owe. A gate that reds on correct work gets switched
off, which costs more than it catches. `--explain` prints the full list of what
this tool cannot detect; read it before treating any verdict as a result.

Cost: one clone plus at most two pytest runs — a baseline, then the post-revert
run — over the change's own tests and name-derived candidates, never the whole
suite; an empty selection costs neither. `--full` opts into the whole suite and
costs about Step 2's runtime on each side.

## Step 8: Ledger claim check (advisory — Espalier-Harness self-host only)
```bash
if [ -f scripts/check_ledger_probes.py ]; then
  PY=python3; command -v "$PY" >/dev/null 2>&1 || PY=python
  "$PY" scripts/check_ledger_probes.py || true   # advisory; see below
else
  echo 'Ledger probes are Espalier-Harness self-host tooling - skipping.'
fi
```
**Never stops the run.** Re-derives every tracked forward-ledger row's claim
against the live tree, ~13s (measured 2026-09-06; an earlier note said ~90s). (The ledger itself is maintainer-only and is not
deployed, which is why it is described here rather than linked.)

**Why this step exists at all.** The runner has existed since the 2026-08-20
rebuild, where it found **41 of 222 rows already dead** — and nothing scheduled
it, so it ran when someone remembered. On 2026-08-26 it was run for the first
time in weeks and reported **five live rows as strike candidates**, one of which
had been written into a class as a live member an hour earlier, by someone
re-cutting that very class. A documented failure mode with no scheduled check is
a description, not a defence.

Read the three-way verdict, plus a fourth line on a separate axis:

- `STRIKE_CANDIDATE` — the probe stopped printing its `open_value`. **Evidence,
  never a verdict.** A wrong strike deletes live work (with no git undo at all
  until the ledger was tracked on 2026-09-21). Re-verify by hand before striking
  anything.
- `UNRESOLVED` — the probe could not answer (subject moved, a declared `inputs`
  member missing or empty on this checkout, command unparseable, timeout). Not
  evidence the defect was fixed; re-anchor the row, or run on the tree that
  carries the path.
- `NO_ORACLE` — declared unmeasurable from this tree, with a reason. Legitimate:
  "re-enable Actions at the repo level" has no local oracle.
- `STALE_CLAIM` — **orthogonal to the verdict above, not a fourth verdict.** The
  row's PROSE changed and its probe did not. A row can be `STILL_OPEN` *and*
  stale simultaneously — `DEF-493` was, for five days, carrying a cause a matrix
  had already refuted while its probe correctly reported the original symptom
  still reproduced. This line says a claim was **rewritten without being
  re-measured**. It does *not* say the new claim is wrong; nothing mechanical
  can, which is why a pack's Task 0 still has to.

Coverage is gated separately, in the suite rather than here (Espalier source repo):
`tests/test_forward_ledger_completeness.py::test_every_live_row_is_probed_or_declared`
holds every live row to *probed or declared, no third bucket*, so a newly-minted
row cannot be silently invisible to this step.

## Report
```
PREFLIGHT RESULT
━━━━━━━━━━━━━━━━
Lint:        {pass/fail/skipped}
Tests:       {pass/fail}
Surface:     {pass/fail}
Integrity:   {pass | drift (N files) | manifest absent | kill-switch}
Release gate: {pass | fail (gate: <name>) | skipped (adopter repo)}
Reflect:     {gaps found / clean}
Correctness: {code-reviewer verdict + finding count | not dispatched (reason)}
Adversarial: {failure-mode-reviewer verdict + finding count | not dispatched (reason)}
Pins:        {PINNED | UNPINNED | NOT_APPLICABLE | ERROR | skipped (adopter repo)}
Ledger:      {N still-open, N strike candidates, N stale claims | skipped (adopter repo)}
Verdict:     {GO / NO-GO + reason}
```

`Pins:` is on the record so the answer exists; it never moves the verdict.
An `UNPINNED` next to a `GO` is a normal, correct line.

`Ledger:` is on the record for the same reason and likewise never moves the
verdict — a strike candidate is a prompt to re-verify, and striking a row is
an unrecoverable edit to a gitignored file. Non-zero next to a `GO` is normal.
