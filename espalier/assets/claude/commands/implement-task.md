Canonical repo-change command. Use for focused changes or coordinated multi-phase work.

## Usage

```
/implement-task <task>          — focused mode (one bounded change)
/implement-task --multi <task>  — multi-phase mode (coordinated changes, migrations, refactors)
```

`--multi` is a manual override. Use it for any task that touches 3+ files or multiple subsystems. `/implement-task` may also auto-escalate to multi-phase when the task clearly spans multiple subsystems, but `--multi` always wins.

---

## Focused mode (default)

For one bounded change, one main proof path, or a small localized edit.

1. **Restate the task.** Identify affected files and their test counterparts.
   **Then recall the hazards of those files, not the task:** `/recall <the
   artifact's idiom or the failure shape>` -- a markdown-table parser asks
   `escaped pipes`, a new test file asks `new test file marker`, an operator
   doc asks `operator docs python`, a hand-kept list asks `hand-maintained
   enumeration`. Measured 2026-09-06: the task and step texts of two lanes
   recalled none of the four catalog entries the red teams then found; the
   hazard words recalled all four. The PostToolUse pointer rows in
   `_reinject.py` fire on the event when you forget, once per session each.
   (Espalier-Harness self-host: when the hazard query finds an entry the
   task text did not, append `(task text, entry source)` to `_TASK_ARM` in
   `tests/test_recall.py` at the lane's handoff, with a dated mark -- the
   task arm of `scripts/recall_eval.py` (Espalier source repo only) measures exactly this gap and grows
   only that way.)
   **Then write the constraint each chosen entry imposes on THIS change, one
   line per entry, before the first edit.** Retrieval is not application:
   measured 2026-09-08, the DEF-717 lane recalled the ReDoS rule (adjacent
   quantifiers must be mutually exclusive) and still shipped a regex that hung
   the deployed hook for 20 s on 305 bytes, because the entry was read and
   never turned into a check the diff could fail. The line is that check --
   the reviewer compares the diff against it instead of re-deriving it. Carry
   the lines into the plan: each step's text gains a `constraints:` field
   beside `files:` / `proof:` / `rollback:`, so they are greppable in the plan
   file rather than living only in the transcript (a body line with no
   artifact behind it is the one that gets skipped).

2. **Present plan and wait for approval.** List what changes, in what order, and what test proves each change.

3. **Create a one-step execution plan** (after approval, before source writes):
   ```bash
   python tools/cc/execution_plan.py create \
     --task "<task description>" \
     --goal "<one-sentence motivation>" \
     --not-doing "<one-sentence scope-out>" \
     --steps "Focused implementation: <change>; files: <expected files>; proof: <targeted proof>; rollback: <rollback note>"
   ```
   The `--goal` and `--not-doing` flags enable auto-compose of an
   `action_justification` on the subsequent `mark <i> running` (both
   flags required together; partial population falls through to the
   existing advisory).

4. **Implement the change.**

5. **Run targeted proof:**
   ```bash
   pytest tests/test_{affected_module}.py -q
   ```
   If no targeted test exists, generate one with `/test-this <file>` (it
   matches the project's existing test patterns) rather than leaning on the
   full suite; fall back to the full suite only if writing a test isn't
   feasible.

6. **Review before the one full run.** If the diff touches a trigger surface
   (`tools/cc/`, `.claude/`, `.github/workflows/`, `bench/`, `scripts/`, or
   `espalier/` engine code), dispatch `code-reviewer` on it now; if it also
   ships or modifies a hook, a gate, or a command / agent / skill body,
   dispatch `failure-mode-reviewer` in the same message (the trigger surface,
   the two-tier rule and the stop vocabulary are `/preflight` step 6's — keep
   them in step). **Dispatch both at once and freeze your edits until both
   reports are in:** read the failure-mode report second (its frame assumes
   the code is correct), then land the accepted findings from both as ONE fix
   batch and re-run the targeted proof. An edit applied while a reviewer is
   still reading makes it re-derive against a tree that moved under it
   (measured twice on 2026-09-06). A doc-only or test-only diff skips the
   dispatch and goes straight to step 7. **Before dispatching, run this
   repo's enumerator pins** — the tests that count or classify files (on the
   Espalier-Harness tree `tests/test_test_suite_contract.py
   tests/test_marker_taxonomy.py tests/test_portability_contract.py`, about
   seventeen seconds): a NEW file in `scripts/` or `tests/` is invisible to a
   targeted run, and five such pins went red under green targeted proofs on
   2026-09-06.

7. **Run the proof tier once — after the fix batch, never before.** First
   stage every NEW file, because the gates that read `git ls-files` (encoding
   pins, citation resolvers, inventory counts) cannot see an untracked file
   and go green over it until the commit makes it visible:
   ```bash
   git add -N <each new file>
   ```
   Then the tier the batch's surface earns -- computed, not remembered. On
   the Espalier-Harness tree `python scripts/proof_tier.py` prints `full`,
   `recall` or `contract`, names any runtime or recall-corpus path that
   decided it, and lists every untracked file with its `git add -N` line
   (exit 2 until none remain). The rule it computes: a file under `tools/cc/`
   or a `.py` under `espalier/` outside its two byte-mirrors (`assets/`,
   `_vendor/`) is the shipped runtime and earns the whole suite; a file the
   pull-recall corpus reads (`memory/`, `docs/SHARP_EDGES.md`,
   `docs/sharp-edges/`, `docs/FAILURE_MODES.md`, the standing principles and
   their aliases sidecar) earns the tree-wide truth tests and then the recall
   engine's own test files, because a corpus edit moves the calibration pins
   while touching no runtime path (a doc-only fold landed with five of them
   red under the contract slice on 2026-09-11, `DEF-775`); anything else
   (other docs, tests, scripts, `bench/`, `.claude/` bodies) earns the
   tree-wide truth tests. The handoff's `/preflight` runs the whole suite
   regardless:
   ```bash
   # Espalier-Harness tree: ONE command runs the tier the diff earns and prints
   # a receipt naming every command it ran -- full is two (xdist across the
   # cores with the three wall-clock-budget files left out, then those three
   # serially: about six and a half minutes, measured twice), recall is the
   # contract slice then the recall engine's test files (about three and a
   # half minutes on top, measured 2026-09-12), contract is one (the tree-wide
   # contracts, about three minutes serial); on the two cheaper tiers a changed
   # `scripts/<name>.py` adds one more line running its own `tests/test_<name>.py`
   # when that file exists (derived from the diff -- a script's tests are
   # integration-classified, so the contract slice alone never collected them)
   python scripts/proof_tier.py --run
   # adopter tree: its own tree-wide contracts if it has them, else the suite
   pytest -m contract -q
   pytest -q
   python -m espalier audit .
   ```
   Measured 2026-09-06 on the Espalier-Harness tree: three full runs in one
   day caught nothing beyond the targeted proofs except five `contract`-marked
   tests, each seconds long; the contract slice ran in 164 s serial against
   about nineteen minutes for the suite serial, and 6:31 then 6:12 for the
   suite in the parallel form the script runs, clean both times (the count
   the xdist-safety audit asked for before that form became the default). The
   slice's own `-n auto` form (62 s) raced on the live tree, so the slice runs
   serially; a parallel full run that errors on a live-tree race is a loud
   error, never a false green -- rerun the failing file serially and add the
   date and the test to the races line in `tests/README.md` (self-host only). Do not start either tier while the
   reviewers are out "for early signal": every lane in a week produced review
   findings, so a run started earlier is stale the moment they land. One
   review round, one fix batch, one run; if the batch touched a shipped
   surface after the run, the run is stale again — re-run it rather than
   reason about it. The one carve-out: a change after the run that *reverts a
   shipped file to HEAD* or touches tests and docs only earns the contract
   slice plus the touched files, not a second full tier (measured 2026-09-10:
   a second sixteen-minute run over a three-line revert the failing contract
   had already proved; the slice plus three files took four).
   *Optional — confirm it runs (not a gate):* tests passing isn't the same
   as "it works." For a user-facing change, launch the project's real
   entrypoint and observe behavior (the environment's `/run` + `/verify`
   skills are project-aware via `reports/repo_fingerprint.json`). Additive
   verification only — never a blocking gate.

8. **Close the execution plan.** Mark the plan's single step `passed` so it
   reads `complete`:
   ```bash
   python tools/cc/execution_plan.py mark 0 passed
   ```
   Focused mode creates a one-step plan (step 3) but otherwise never marks
   it; leaving it open makes the *next* session's compact-orientation banner
   surface this finished task as the in-flight `ACTIVE PLAN (live -- this is
   where you were)`. The plan file is gitignored local state — housekeeping,
   no commit.

9. **Record significant decisions:**
   ```bash
   python tools/cc/cognitive_blueprint.py record --kind decision --description "..."
   ```

10. **Report results.** Summarize changed files, test results, and any follow-up needed.

### If tests fail

1. Read the failure output carefully.
2. Determine if the failure is in the new code or was pre-existing.
3. Fix and re-run. If the fix is non-trivial, present it for approval.
4. If you cannot fix it, revert the change and report what went wrong.

---

## Multi-phase mode (`--multi`)

For coordinated changes, migrations, refactors, release hardening, or any task touching multiple subsystems.

### Phase 1: Decompose

Analyze the request. Produce a step-by-step execution plan. Each step must specify: what files change, what test proves it, and what to roll back if it fails.
Run focused step 1 first -- the hazard recall for each step's artifacts and
the one-line constraint each recalled entry imposes -- before creating the plan,
and carry each step's constraints into its step text as `constraints:`.

```bash
python tools/cc/execution_plan.py create \
  --task "<task description>" \
  --goal "<one-sentence motivation>" \
  --not-doing "<one-sentence scope-out>" \
  --steps "step1|step2|step3"
```

The `--goal` and `--not-doing` flags enable auto-compose: every
`mark <i> running` records an `action_justification` on the active
blueprint when both fields are populated. Pass only one (or neither)
to keep the existing advisory-on-empty behavior.

Present the plan and wait for approval.

### Phase 2: Execute with gates

For each step:

1. Mark it running:
   ```bash
   python tools/cc/execution_plan.py mark <index> running
   ```
2. Make the change.
3. Run the targeted proof (the specific test for this step, not the full suite).
   If the step added a new surface (CLI subcommand, test file,
   agent/command/skill), also run its registration contract now — cheat-sheet
   CLI parity, marker taxonomy, and mirror parity fire only in the full suite
   otherwise; `espalier provenance` covers the shipping-tag class on the
   Espalier-Harness source tree (elsewhere it stands down at exit 0 — the tags
   it hunts are Espalier's own, so that class is not yours to clear).
4. If it passes, mark it:
   ```bash
   python tools/cc/execution_plan.py mark <index> passed
   ```
5. If it fails, mark it and stop:
   ```bash
   python tools/cc/execution_plan.py mark <index> failed --note "reason"
   ```
   Report the failure and ask how to proceed.

### Phase 3: Review, then the one integration run

After all steps pass, dispatch the reviewers FIRST — the same trigger surface,
two-tier rule and edit freeze as focused-mode step 6 — land both reports'
accepted findings as one fix batch, re-run the affected step proofs, and only
then run the integration check once:

```bash
pytest -q   # Espalier-Harness tree: `python scripts/proof_tier.py --run` (the tier the diff earns, one receipt)
python tools/cc/reflect_protocol.py
python tools/cc/execution_plan.py status   # expect: complete
```

Report any cross-file issues the individual steps didn't catch. If `status`
still reads `in_progress` — a step landed but was never marked `passed` —
close the straggler with `execution_plan.py mark <i> passed`, so the next
session's compact-orientation banner doesn't surface this finished task as
the in-flight `ACTIVE PLAN (live -- this is where you were)`.

### Phase 4: Record

```bash
python tools/cc/cognitive_blueprint.py record --kind decision --description "..."
```

### Resume after interruption

```bash
python tools/cc/execution_plan.py status
```

Resume from the first pending step.
