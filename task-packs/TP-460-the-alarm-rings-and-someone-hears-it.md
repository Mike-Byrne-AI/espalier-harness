# TP-460 — The alarm rings and someone hears it: a green Windows baseline, a post-merge red receiver, and a required Windows slice

## Status

- Version target: `0.8.0b3` (the CI changes are self-host-only; the banner is a hook `init`
  deploys)
- Change type: CI + hook (reporter) + one test expectation. The hook and workflow edits need
  the approval marker in the PR title (`HARNESS-UPDATE-APPROVED@<sha>`; `/ship` step 3).
- **Kind: PACK**
- Ledger rows: `DEF-939` (§C0, the `fcntl`-only corpus lock) is **expected, not closed**, here:
  authoring's class question (Core Rule 12) found eight `fcntl`-only lock sites across
  `tools/cc/`, `tools/cc/hooks/` and `espalier/` (`command grep -ln fcntl tools/cc/*.py
  tools/cc/hooks/*.py espalier/*.py`, 2026-09-30), every one degrading to an unlocked
  best-effort path on Windows, so the fix is a chokepoint-plus-gate refactor across two
  import boundaries and a mirror — its own pack, filed as the class row `DEF-974` at authoring. No row exists for the receiver, the slice or the no-summary case; this pack
  is their first record, and its Landing is their close. The four packs of the detection-system lane are ordered alarm → silent →
  axes → registry (operator, 2026-09-30); this is the first, because every later pack's
  Windows evidence needs a leg that can go green and a person who sees it go red.
- Cross-pack: `TP-461` (no silent no-op) touches `tools/cc/hooks/session_start.py` for a
  different symbol (its fail-open census); expect a merge collision on that file only if both
  are in flight. Two things TP-461's own 0-A must read against this pack's landing: Fix 4's
  optional `gh pr checks` call is a new spawn site in `session_start.py`, so TP-461's floored
  spawn census admits it; and TP-461 names `.github/windows-slice.txt` as a file it edits,
  which this pack no longer creates (1-D held at 0-B, below). The adopter-axes pack (`DEF-975`)
  will add a perturbation cell to `test.yml`; this pack no longer touches that file.
- Authored 2026-09-30 on the public tree at `4eef108b` (PR #47 merged). Every "measured"
  sentence names its command; execution re-runs it rather than trusting the snapshot.
- Executed from 2026-09-30 on `a413da67` (PR #49 merged). Task 0 ran first: 0-A read **build**
  on all three arms and 0-B's refuting result **fired** (five files red on the Windows leg in the window,
  only three of them red there alone: the known `DEF-939` file and the two timing flakes
  Scope-out already names),
  so 1-D is held and the pack shrank to 1-A, 1-B, 1-C. The 0-A pack-artifact review (checklist v2)
  returned one BLOCK (Fix 1 read the input dict for the warnings) and eleven WARNs; every one that
  survives the shrink is folded below. The two records are `reports/tp460/0-A.md` and
  `reports/tp460/0-A-code-reviewer.md` (gitignored, on the executing box).

---

## Motivation

The one Windows CI signal cannot raise an alarm today, and the review of 2026-09-30 (four
read-only lanes over the 46 post-cut findings) found this was the *mechanism* by which known
Windows reds went unheeded, not a one-off:

- **It is not a required check.** Measured 2026-09-30:
  `gh api repos/Mike-Byrne-AI/espalier-harness/branches/main/protection/required_status_checks/contexts`
  prints `verify, benchmark, freshness, test (3.10) … test (3.14)`. `portability (windows-latest)`,
  `clean-checkout` and `release-readiness gate` are absent.
- **It finishes after the merge.** The Windows leg runs serially (`.github/workflows/portability.yml`,
  the `Test` step: `python -m pytest -q -m "not heavy_e2e" …` with no `-n`, though `pytest-xdist`
  is a dev dependency) and took 67–90 minutes on the last ten runs. PR #46 merged 28 minutes
  before its Windows verdict; PR #33, which *introduced* the `DEF-939` test, merged 73 minutes
  before the leg that first went red on it (run `36399241887`, 2026-09-28).
- **It has been red for a known reason since 2026-09-28** (three `DEF-939` failures on every
  run), so a new Windows-only failure turns "3 failed" into "4 failed" inside a job already
  marked failed. Run `36518927194` (PR #41) died at seven minutes under `pytest-timeout` with
  no summary line at all, and read the same as "3 failed".
- **No one is told after the merge.** `tools/cc/hooks/session_start.py::_merged_prs_line` admits
  a merged pull request only while the local base branch lacks its merge commit; once `main` is
  pulled the line is empty, and the data that names the post-merge red (`statusCheckRollup`,
  already fetched by `_PR_FIELDS`) is discarded. `_pr_summary` prints "held by the red" for an
  open pull request with a non-required red, which is false: auto-merge ignores that check.
  `.claude/commands/ship.md` step 4 arms auto-merge without reading any check, and step 5's
  four red shapes are all required-check shapes.

The gap is not Windows-specific. PR #40 merged with Portability red on all three OS legs and
`release-readiness gate` red while the required `test (3.x)` cells were green on the contract
tier (`gh pr checks 40`). The class is *any non-required red*, and this pack's receiver names
them all; the required slice is the Windows-specific half the operator chose (2026-09-30) so
that a Windows regression can block a merge rather than only be reported after one.

---

## Scope (in)

- **0-A** the alarm census: the required-check list, the serial leg, and the receiver's
  blindness, each re-derived by its command; the refuting results stated first.
- **0-B** the slice derivation and the timing baseline: the initial Windows slice derived from
  the leg's own failure history (a deriving command over run logs, not a hand list), and one
  narrowed Windows dispatch that measures the slice's wall clock before the job exists.
- **1-A** the green baseline: the three `DEF-939` cases carry a strict expectation keyed on the
  lock's capability (not the OS name), so the leg reads green while the defect is open and
  goes red by itself the day the class pack lands an arm; graded on a Windows dispatch.
- **1-B** the leg fails loudly when pytest prints no summary line, and runs under `-n auto`,
  with the saving measured, not assumed.
- **1-C** the receiver: the `Merged:` line names a merged pull request whose latest checks
  hold a red; the false "held by the red" clause is scoped to required checks; `/ship` step 0
  prints the last merged pull requests' post-merge reds before a new lane is armed, and step 4
  says which legs finish after the merge.
- **2-A** the red-team.
- **Files this pack may write** (named so `/scope-check` can walk them):
  `tests/test_finding_ledger.py`, `.github/workflows/portability.yml`,
  `tools/cc/hooks/session_start.py` (and `espalier/_vendor/cc/hooks/session_start.py` by
  `scripts/sync_vendor_cc.py`, never by hand), `tests/test_session_banner.py` (the file that
  pins `_merged_prs_line`), `.claude/commands/ship.md` (and its two mirrors by
  `scripts/sync_claude_mirrors.py`), `CHANGELOG.md`, `task-packs/FORWARD_LEDGER.md` and
  `task-packs/LEDGER_PROBES.json` (the `DEF-939` repin and the 1-D row, through the verb).

## Scope (out)

- **The `fcntl`-only lock class** (eight sites; `DEF-939` is one): a chokepoint at
  `tools/cc/_file_lock.py` (the `_json_safe.py` precedent: importable by `tools/cc/*.py` and
  the hooks) with an engine twin under the mirror registry, two arms (`fcntl.flock`,
  `msvcrt.locking`) and a degrade that speaks, plus a gate that no shipped module calls
  `fcntl` outside the two chokepoints (`DEF-974`). Eight sites with eight pinned degrade behaviours
  (`tests/test_fan_out_findings.py`'s lock class, `tests/test_atomic_io.py::_APPEND_EXEMPT`,
  the execution-plan and blueprint lock tests) is a pack, not a sub-task of the alarm; the
  class row filed at authoring is its home.
- **A baseline-delta step** (junit + a committed known-reds list that fails only on new ids):
  a second hand-kept population that can absorb a real regression. Not taken; 1-A's
  expectation is one conditional assertion keyed on a capability the fix changes, so it
  retires itself the day an arm lands (no `xfail`: a strict `xfail` on the whole test would
  hide every other assertion in it on the host it excuses).
- **The required Windows slice (1-D), held at 0-B on 2026-09-30.** The pack's threshold was
  six files; the deriving command over the last forty runs (2026-09-25 to 09-29, the window the
  pack names), filtered to the `windows-latest` job, yields **five**, and only three of those
  were red on Windows alone: `tests/test_finding_ledger.py` (seven runs, `DEF-939`),
  `tests/test_write_guard_command_position.py` (one run, `36097120794`) and
  `tests/test_speedbump_irreversible.py` (one run, `36222363651`) -- the last two being the
  timing flakes the next bullet refuses to block merges on. The other two
  (`tests/test_front_door_numbers.py`, `tests/test_recall.py`) were red on the macOS and
  Ubuntu legs of the same runs, so the required `test (3.x)` cells already catch that class
  and a Windows slice adds nothing for them.
  Authoring's "twelve" was the review record's all-time classification, eight of whose files
  are the `DEF-921` reds fixed on 2026-09-24 and red in no run since. A required job over
  one real file and two flakes is not worth its merge latency; the receiver (1-C) is the
  Windows net until the admission rule has something to admit. Filed as a ledger row with
  the count; re-raise when the `Merged:` line has named Windows reds the rule would admit.
- **Making the full Windows leg required**: 67–90 minutes of merge latency on every pull
  request, and two of the three non-`DEF-939` Windows reds in the last two weeks were timing
  flakes (runs `36097120794`, `36222363651`). The slice is the required half; the full leg
  stays advisory and the receiver carries it.
- **A marker-derived slice** (`-m portability`): measured at authoring by classifying the
  files that have ever been Windows-red, no existing marker covers them (they fall under
  `contract`, `unit`, `security`, `integration`, and `slow`), and inventing a marker is a
  hand-kept list under another name. When 1-D is re-raised, the slice is a path list with a
  mechanical admission rule and a floor, and its test carries the `contract` marker in
  `tests/conftest.py` so the contract tier runs it on a slice-only change.
- **The other non-required checks** (`clean-checkout`, `release-readiness gate`): the receiver
  names them when they go red, which is this pack's reach for them; making either required is
  its own decision.
- **`DEF-968`** (an interpreter path holding a space draws a false fail-open warning in
  `session_start.py::_warn_if_hook_interpreter_unresolved`): a different symbol in the same
  file, its own row and oracle.
- **The `end-to-end-bench.yml` workflow** (zero runs ever; a schedule commented out pending a
  secret): the run-or-delete decision belongs to the adopter-axes pack (`DEF-975`), which owns the end-to-end path.
- **xdist safety on Windows**: 1-B measures `-n auto` on a dispatch; if the parallel leg reds
  on tests the serial leg passes, the flag is dropped and the finding is a row, not a fix here.

---

## Task 0 — Verify (may end this pack)

Task 0 has three outcomes, stated before the measurements: **build** (the census holds and
the slice derives non-empty), **partial** (the receiver is already live or the leg is already
green: drop the sub-task the measurement retires and continue), and **do not build** (the
refuting results below). The default exit on a refutation is stop and re-raise.

### 0-A The alarm census (deriving commands; the roster is their output)

**Refuting results, stated first:**
- If `portability (windows-latest)` is already in the required-check list, 1-D is retired and
  the pack shrinks to 1-A, 1-B and 1-C.
- If `_merged_prs_line` already names a post-merge red (the drive below prints a non-empty
  line with `local_has_commit=True`), 1-C's banner half is retired.
- If the Windows leg is green on the latest run of `main` (no `DEF-939` failures), 1-A is retired.
- If **all three** hold, do not build this; re-raise with the three outputs.

```bash
gh api repos/Mike-Byrne-AI/espalier-harness/branches/main/protection/required_status_checks/contexts --jq '. | join(", ")'
command grep -n '\-n auto\|pytest -q' .github/workflows/portability.yml
gh run list --workflow portability.yml --limit 10 --json databaseId,conclusion,headBranch --jq '.[] | "\(.databaseId) \(.conclusion) \(.headBranch)"'
```

The receiver drive (the helpers are importable; this is the same shape the banner runs):

```bash
python3 - <<'EOF'
import json, subprocess, sys
sys.path.insert(0, "tools/cc/hooks")
import session_start as ss
# _PR_FIELDS is already the comma-joined string; `listing` is the gh JSON text (parsed by
# _prs); local_has_commit takes (base, oid) and True means "the local base has it".
listing = subprocess.check_output(
    ["gh", "pr", "list", "--state", "merged", "--limit", "5", "--json", ss._PR_FIELDS], text=True)
for pr in json.loads(listing):
    reds = [c for c in ss._latest_run_per_check(pr.get("statusCheckRollup") or [])
            if ss._check_outcome(c) == "red"]
    print(pr["number"], [c.get("name") or c.get("context") for c in reds])
print("line:", repr(ss._merged_prs_line(listing, local_has_commit=lambda base, oid: True)))
EOF
```

*(The authoring draft passed a list, a one-argument lambda and a joined tuple; the 0-A review
caught all three and execution ran the shape above. Production adds `--author @me`; the drive
leaves it off so it sees every merge.)*

**Measured at authoring, 2026-09-30:** the required list is the eight above; the `Test` step
has no `-n`; the last ten runs are eight `failure`, two `cancelled`, none `success`; the
receiver drive returns `#46 ['portability (windows-latest)']` and `#43 ['portability
(windows-latest)']` from the rollup while the `Merged:` line is empty. **Build.**

**Measured at execution, 2026-09-30 on `a413da67`:** the same eight; `portability.yml:85` has no
`-n`; the last ten runs (`36626644050` back to `36399241887`) are eight `failure`, two
`cancelled`, none `success`; the drive prints `46 ['portability (windows-latest)']` and `[]` for
#49, #47, #45, #44 (#43 has aged out of the five-row window), and the line is `''`. **Build.**

### 0-B The slice derivation (refuting result fired 2026-09-30; 1-D held)

**Refuting result:** if the derivation below yields fewer than **six** files, the slice is
too thin to be worth a required job; land 1-A, 1-B and 1-C and re-raise 1-D with the count.

The initial slice is the set of test files that have failed **on the Windows leg** in the
window, derived from the leg's own logs (the population is the output of this command, never a
list in this pack). `--log-failed` prefixes every line with the job name, so the filter on
`portability (windows-latest)` is what makes the count Windows evidence; the authoring draft
had no filter and counted the macOS and Ubuntu legs too:

```bash
for r in $(gh run list --workflow portability.yml --limit 40 --json databaseId --jq '.[].databaseId'); do
  gh run view "$r" --log-failed 2>/dev/null | command grep -E '^portability \(windows-latest\)' \
    | command grep -oE 'FAILED tests/[A-Za-z0-9_]+\.py' | sort -u ;
done | sort | uniq -c | sort -rn
```

**Measured at execution, 2026-09-30:** the forty runs span 2026-09-25 to 2026-09-29 (16 `success`,
11 `failure`, 7 `cancelled`; every `failure` run produced `FAILED` lines, so the instrument
read every red). The command prints **five** files: `tests/test_finding_ledger.py` (7 runs,
`DEF-939`), `tests/test_front_door_numbers.py` (3), `tests/test_write_guard_command_position.py`
(1, `36097120794`), `tests/test_speedbump_irreversible.py` (1, `36222363651`),
`tests/test_recall.py` (1). Reading the same runs' macOS and Ubuntu lines, `test_front_door_numbers`
and `test_recall` were red on every leg (a `requires-python` mismatch and a recall headline
contract), so the Windows-only subset is three, one of them real. The
authoring sentence "the runs since 2026-09-25 name twelve files" was wrong: the twelve were
`G3_ci_review.md`'s all-time classification, including eight `DEF-921` files fixed on
2026-09-24. **Fewer than six: 1-D held**, the count is a ledger row, the pack continues with
1-A, 1-B, 1-C (the timing dispatch that was to budget the slice job is not run; 1-B still
measures `-n auto` on the full leg).

---

## Relevant memory

Recent pattern: the last two weeks' Windows reds were all *reported* by CI and none was
*received*. The mechanism is present, the receiver is not. Separately, two consecutive
Windows-only reds were timing flakes, which is the reason the full leg stays advisory.

| Entry | Where |
|---|---|
| A gate can be blind along a whole dimension of its input | `memory/a-gate-can-be-blind-along-a-whole-dimension.md` |
| Completeness gate must discover its population | `memory/completeness-gate-must-discover-its-population.md` |
| Gates the targeted proofs never show | `memory/four-gates-the-targeted-proofs-never-show.md` |
| A New Guard Is Blind The Way It Claims To See | `docs/SHARP_EDGES.md :: A New Guard Is Blind The Way It Claims To See` |
| The Measuring Instrument Is a Claim Too | `docs/SHARP_EDGES.md :: The Measuring Instrument Is a Claim Too` |
| POSIX-only `os.O_*` flags need `getattr` guards for Windows | `docs/SHARP_EDGES.md :: POSIX-only os.O_* flags need getattr guards for Windows` |

Resolved at authoring by `python3 tools/cc/hooks/_recall.py "a check that is red for a known
reason hides a new red"` and `"hand-kept test list floor the population"`; re-run rather than
trust this list if the pack has been sitting.

Files this pack touches, so the folder-`CLAUDE.md` ladder fires on entry:
`tools/cc/hooks/` (hook contract; sync the vendor mirror), `.claude/commands/` (sync the
mirrors), `.github/workflows/` (protected zone; marker in the PR title).

---

## Implementation

### 1-A The green baseline (`DEF-939` expected, keyed on capability)

**Fix 1 — the expectation lives on the one assertion, not on the test** *(prescribed; the
authoring failure-mode review refuted the first shape, a strict `xfail` on the whole test: on a
host with no `fcntl` every other assertion in that test — return code, valid count, appended
rows, the corpus file, the ledger row — would read `xfailed`, and a new Windows break inside
it would stay green, which is the "known red hides a new red" defect reproduced inside one
test):* `tests/test_finding_ledger.py` binds only `FINDING_SCHEMA` and `aggregate_findings`
from the producer today (its import block), so the module is bound first:

```python target=tests/test_finding_ledger.py
from espalier import fan_out_findings as _fof
from espalier.fan_out_findings import FINDING_SCHEMA, aggregate_findings
```

then, in `TestPersistProgramExecutes::test_a_standing_persist_program_runs_end_to_end`, the
warning-channel assertion (today: `assert out["warnings"] == []`, where `out` is the program's
last stdout line parsed as JSON -- `payload` is the *input* dict and has no `warnings` key; the
authoring draft read it there and the 0-A review caught the `KeyError`) becomes conditional on
the lock's real capability and every other assertion runs on every host:

```python target=tests/test_finding_ledger.py
        warnings_out = out["warnings"]
        if _fof._HAS_FCNTL:
            assert warnings_out == []
        else:
            # DEF-939: no lock arm on this platform; the persist program reports the
            # unlocked read-modify-write and nothing else. Retires itself when the
            # lock class pack (DEF-974) lands a second arm and the flag it keys on
            # reads true there.
            assert len(warnings_out) == 1 and "UNLOCKED" in warnings_out[0], (name, warnings_out)
```

(Keep `name` in the assertion messages, as the test's neighbours do; the exact warning text is
read from `espalier/fan_out_findings.py` at execution, and the substring is what is pinned.) A
host whose `fcntl` imports but whose filesystem refuses `flock` (an NFS temp dir
without lockd) fails this assertion outright — loud, and correct: that host is not in CI and a
red there names a real degrade.

**Earn the red:** on a Windows dispatch against the pushed lane (`gh workflow run
portability.yml --ref <lane> -f os=windows-latest -f select=tests/test_finding_ledger.py`; a
dispatch with no `--ref` runs `main`'s copy of the test) the three cases read `passed` and the
job reads `success`. Mutation: drop the conditional and assert `warnings_out == []`
unconditionally; the cases red on Windows again while a POSIX run is unchanged. (The
authoring mutation, keying on `sys.platform == "linux"`, cannot red on Windows: there it takes
the else branch and expects the warning Windows really emits -- the 0-A review.)

**Checkpoint:** the Windows dispatch reads `0 failed`; `pytest -q tests/test_finding_ledger.py`
locally is unchanged.

### 1-B The leg fails loudly, and faster

**Fix 2 — no summary line is a failure** *(prescribed; refuted if `pytest -q` under `-rfEs`
prints its summary in a shape the pattern below misses on any of the three runners — 0-A's
last green run on each OS is the sample to grep first). Keep the step's existing comments (the
one-shell note and the `heavy_e2e` rationale) above the fence; the fence replaces the `run:`
body, not the step:*

```yaml target=.github/workflows/portability.yml
      - name: Test
        shell: bash
        run: |
          # GitHub runs `shell: bash` as `bash -eo pipefail`: a non-zero pytest exit would
          # end the step before the guard below ran, so the guard would only ever run on
          # green runs (the authoring failure-mode review). Keep the exit code by hand.
          set +e
          python -m pytest -q -n auto -m "not heavy_e2e" --durations=25 -rfEs ${{ github.event.inputs.select }} 2>&1 | tee pytest-out.txt
          rc=${PIPESTATUS[0]}
          # A session pytest-timeout kill prints no summary line and reads like a
          # normal red (run 36518927194, 2026-09-29, seven minutes, "3 failed"-shaped).
          # Under -q the summary is `N passed, M failed in T` -- or `N deselected in T` when a
          # `-k` matches nothing, or `no tests ran in T`; every shape is admitted so that pytest's
          # own exit code (5 on an empty selection) reaches the step instead of this guard's 70.
          if ! command grep -qE '^(=+ )?([0-9]+ (passed|failed|errors?|xfailed|xpassed|skipped|deselected|warnings?)|no tests ran)' pytest-out.txt; then
            echo "::error::pytest printed no summary line -- the session died (rc=$rc)"; exit 70
          fi
          exit "$rc"
```

`exit 70` is the repository's "the gate itself refused" code (`scripts/fresh_clone_gate.py::GATE_REFUSED`),
so the failure reads as *instrument*, not *tests*.

**`-n auto` is measured, not assumed.** 0-B's dispatch already ran the slice in parallel; 1-B
runs one full dispatch on `windows-latest` with `-n auto` and records minutes beside the
serial figure (67–90). If the parallel leg reds on any test the serial leg passes, drop the
flag, keep Fix 2, and file the xdist finding as a row; that is a *partial* outcome, not a
refutation of the pack.

**Checkpoint:** the dispatched Windows run is `success` with a summary line; a deliberate
`select="-p no:terminal"` dispatch (rc 0, no summary — the guard alone must turn it red) reads
`failure` with the `::error::` line (drop `-n auto` for this one dispatch if xdist refuses to
start without the terminal plugin; the guard is what is under test); a deliberate
`select="-k no_such_test"` dispatch (rc 5, a `deselected` summary line) reads `failure` with
pytest's own exit code, proving the code survives the tee. All three run ids go in Landing.

### 1-C The receiver

**Fix 3 — the `Merged:` line names a post-merge red** *(prescribed; refuted if
`_latest_run_per_check` drops the rollup rows of a merged pull request — 0-A's drive says it
does not):*

In `tools/cc/hooks/session_start.py::_merged_prs_line`, beside the existing admission (a merged
pull request the local base lacks), admit a merged pull request among the already-bounded
last five whose latest run per check holds a red, and render it as:

```text
Merged:    #46 lane/fix-adopter-… -- merged 2026-09-29 21:13Z; red after merge: portability (windows-latest)
```

The red list comes from
`_latest_run_per_check(pr["statusCheckRollup"])` filtered by
`_check_outcome(row) == "red"` — the two helpers the drive in 0-A already exercised; no new
`gh` call, because `_PR_FIELDS` fetches the rollup for merged pull requests today. **Per check
name, not per pull request:** over the window of five, the latest merged pull request *that
ran a given check* decides that check's state, so five ledger-only chores that never ran
`portability` cannot push a red code merge out of view, and a later merge whose leg ran green
does supersede an older red (the authoring failure-mode review named both). **`_check_outcome`
reads CANCELLED as `red` by contract** (its comment: a cancelled cell holds a merge exactly as
a failure does), and for an *open* pull request that is the right reading; for a *merged* one a
cancelled latest run has no verdict, so the receiver splits it explicitly -- a row whose
`conclusion` is `CANCELLED` renders as `no verdict: <name>` (only when no later run of that
name exists) and is not counted among the reds; the filter is not `== "red"` alone (the 0-A
review). One line per pull request that still owns a red, the same eight-second budget as the
block it joins. A pull request that is both un-pulled and red renders once with both clauses.

**Fix 4 — "held by the red" only when the red is required** *(prescribed):* in `_pr_summary`,
the clause that sets `held = "the red"` is emitted only when the red check's name is in the
required set. `gh pr list --json` carries no is-required flag; the cheapest true statement is
to reword to `red: <name> (required checks decide the merge)` and leave "held" for a red whose
name appears in the `required` list the banner can read with one extra bounded call,
`gh pr checks <n> --required --json name,bucket`, **only when a red exists** (so the common
green path pays nothing). Execution picks the reword if the extra call pushes the block past
its budget; Landing says which. Either way the call is a new spawn site in the file, and
TP-461's floored spawn census admits it when that pack executes (Cross-pack, above).

**Fix 5 — `/ship` sees the last reds before arming** *(prescribed):* `.claude/commands/ship.md`
step 0 gains the same read the banner does (the last five merged pull requests' post-merge
reds, printed as `red after merge: #46 portability (windows-latest)`), and step 4's sentence
"merges on its own when every required check is green" gains: "the advisory legs
(`portability`, `clean-checkout`, `release-readiness`) finish after the merge; the SessionStart
`Merged:` line and step 0 name a red one." Sync the mirrors (`scripts/sync_claude_mirrors.py`).

**Earn the red:** `tests/test_session_banner.py` (it pins `_merged_prs_line`) gains a case
with a merged, already-pulled pull request whose rollup holds one red row: the line is
non-empty and names the check. Mutation: remove the red-admission branch; the case reds.
A second case: the same pull request with the red row superseded by a later green run of the
same check renders nothing (the `_latest_run_per_check` contract), so the receiver cannot
nag on a red that was fixed by a re-run. A third: a red on merge N followed by four merges that
never ran that check still renders N's red; a fourth: a later merge that ran the check green
clears it; a fifth: a `cancelled` latest run is not named as red.

**Checkpoint:** `python3 tools/cc/hooks/session_start.py` driven with a SessionStart payload
on this checkout prints a `Merged:` line naming `#46`'s Windows red while that red stands (it
does at authoring); `pytest -q tests/test_session_banner.py`; `python3 scripts/sync_vendor_cc.py`
and `python3 scripts/sync_claude_mirrors.py` leave no diff.

### 1-D The required Windows slice -- held

Held at 0-B (the measurement and the reasoning are in Scope (out)). Nothing here lands: no
slice file, no slice test, no `test.yml` job, no branch-protection step. The row that carries
the count names the re-raise condition -- the `Merged:` line has named Windows reds the
admission rule would admit -- and the design that was drafted here (a path list with a header
admission rule and a declared floor pinned by a `contract`-marked test, a `windows-slice` job
with no `if:`/`paths:`/`needs:`/`continue-on-error:`, one `POST` to the required-contexts
list after the job has run once on `main`'s pull requests) is recoverable from this pack's
authoring commit `2891d7af`.

### 2-A Red-team

Budget it. What this pack is most likely to have gotten wrong, in the author's order:

1. **The expectation's key** (Fix 1): `_HAS_FCNTL` is true on a POSIX host whose filesystem
   refuses `flock` (NFS), where the lock degrades with the same warning and the assertion
   fails loud. Ask whether that host exists in CI (it does not today) and whether the key
   should be the lock's *observed* behaviour rather than the module's presence.
2. **The receiver's negative** (Fix 3): a red superseded by a green re-run must render nothing;
   a check that was red on an *older* head of the same pull request must not be named against
   the merged head. `_latest_run_per_check` is the contract; ask whether it keys on head sha.
   And the CANCELLED split: a merged pull request whose latest run of a check was cancelled
   must not be named as red, and must not hide an older red of the same name either.
3. **The no-summary guard's pattern** (Fix 2) on the three runners' actual `-q` output,
   including the `deselected` and `no tests ran` shapes.
4. **The receiver on a repository with no `gh`** or no network: the block already has an
   eight-second deadline; ask whether the new admission adds a read that can outlive it.

Lanes: `code-reviewer` and `failure-mode-reviewer` on a snapshot clone of the diff
(`memory` note: reviewers get a snapshot clone; check the stash list after). A clean red-team
is recorded as a result.

---

## Affected symbols

### Changed-semantics
- `tools/cc/hooks/session_start.py::_merged_prs_line` (admits a merged pull request whose latest
  checks hold a red)
- `tools/cc/hooks/session_start.py::_pr_summary` (the "held by the red" clause is scoped to a
  required red, or reworded)
- `tests/test_finding_ledger.py::TestPersistProgramExecutes::test_a_standing_persist_program_runs_end_to_end`
  (the warning-channel assertion becomes conditional on the lock's capability; every other
  assertion runs on every host)

### Renamed
- None.

### Added-paths
- None (1-D, which added two files and a job, is held).

### Removed-paths
- None.

## Reach

Members derived by: the receiver drive in 0-A (post-merge reds on the last five merged pull
requests) and `command grep -n "DEF-939\|portability\|auto-merge" task-packs/FORWARD_LEDGER.md`
(scope: the ledger's live rows; a clean grep is not an absence proof for a defect no row names).

| Item | Status | Evidence |
|---|---|---|
| `DEF-939` | **NOT CLOSED** (expected by 1-A; `DEF-974`, the class row, is its home) | the three cases pass on a Windows dispatch with the unlocked warning expected there, the leg reads green, and the expectation retires itself when an arm lands |
| the post-merge red on `#46` and `#43` (no row) | **CLOSED** by 1-C | the `Merged:` line names it on this checkout |
| the no-summary crash of run `36518927194` (no row) | **CLOSED** by 1-B | a suppressed-summary dispatch reads `failure` with the `::error::` line |
| a Windows-only red before the merge (no row) | **NOT REACHED** (1-D held at 0-B: five files in the window, three Windows-only, one real) | reached after the merge by 1-C; the row carrying the count names the re-raise condition |
| `clean-checkout` and `release-readiness gate` reds | **NOT REACHED** before the merge; named after it by 1-C | making either required is its own decision (Scope out) |
| `DEF-968` | **NOT REACHED** | a different symbol in `session_start.py`; its own row |

---

## Pass criteria

- A Windows portability dispatch against the lane reads `success` with a summary line after 1-A
  and 1-B (run id in Landing; the leg never runs on `main` pushes, so a dispatch is the only
  reading of `main`'s state); no assertion in `tests/test_finding_ledger.py` is weakened, and the
  warning-channel assertion is not removed — it is *expected* on a platform with no arm and
  *asserted empty* on one with an arm, keyed on the capability so the expectation cannot
  outlive the fix.
- `_merged_prs_line` names a merged, already-pulled pull request whose latest run of any
  check is red, and names nothing for one whose red was superseded by a green re-run; both
  pinned by tests that red under the named mutations.
- `/ship` step 0 prints post-merge reds; its three copies (the SoT and two mirrors) are
  byte-equal after the sync.
- `_merged_prs_line` names nothing as red for a merged pull request whose latest run of a check
  was cancelled (the CANCELLED split), pinned by a test.
- The `-n auto` figure is recorded beside the serial figure, or the flag is absent and a row
  says why.
- `ruff check .`, `mypy tools/cc/hooks/`, the contract tier, `python3 scripts/sync_vendor_cc.py`
  and `python3 scripts/sync_claude_mirrors.py` all clean; the hook type gate on the Linux view.

## Files touched

- **New:** none (1-D held).
- **Modified:** `tests/test_finding_ledger.py`, `.github/workflows/portability.yml`,
  `tools/cc/hooks/session_start.py`, `espalier/_vendor/cc/hooks/session_start.py` (by sync),
  `tests/test_session_banner.py`, `.claude/commands/ship.md` +
  `espalier/assets/claude/commands/ship.md` + `examples/dogfooding/.claude/commands/ship.md`
  (by sync), `CHANGELOG.md`, `task-packs/FORWARD_LEDGER.md` + `task-packs/LEDGER_PROBES.json`
  (a repin of `DEF-939` naming the expectation, and the 1-D row with the count; through the
  verb, `--dry-run` first; no strike).
- **Deleted:** none.
- **Unmodified on purpose:** `.github/workflows/test.yml`, `.gitattributes`,
  `tests/conftest.py`, `docs/RELEASE_CHECKLIST.md`, `tests/test_required_status_checks.py`
  (all 1-D), `scripts/proof_tier.py`, `bench/` (untouched).

## Sub-task ordering

1. **0-A** census (30 min budget) — may end or shrink the pack. Checkpoint: the three
   commands' output pasted into `reports/tp460/0-A.md` (gitignored, record-rooted).
2. **0-B** slice derivation (15 min; done 2026-09-30, fired). Checkpoint: the derived list and
   the held 1-D.
3. **1-A** the expectation, Windows dispatch against the lane (30 min). Checkpoint: `0 failed`
   on Windows.
4. **1-B** no-summary guard + `-n auto` measured (45 min). Checkpoint: three dispatch ids.
5. **1-C** receiver + `/ship` (90 min). Checkpoint: the `Merged:` line on this checkout.
6. **2-A** red-team (60 min). Checkpoint: verdicts folded, mutations named.
7. Landing: the `DEF-939` repin and the 1-D row through the verb; `/preflight`; `/commit`;
   `/ship` with the marker in the title.

## Estimated effort

Budgets, quoted as budgets (the last pack ran about 2.7× over its numbers): 0-A 0.5 h, 0-B
0.25 h, 1-A 0.5 h, 1-B 0.75 h, 1-C 1.5 h, 2-A 1 h, landing 0.5 h — **5 h** after 1-D was
held (it carried 1.5 h), of which about an hour and a half is waiting on Windows runners.

## Landing
- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
