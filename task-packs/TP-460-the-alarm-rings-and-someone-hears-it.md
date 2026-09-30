# TP-460 — The alarm rings and someone hears it: a green Windows baseline, a post-merge red receiver, and a required Windows slice

## Status

- Version target: `0.8.0b3` (the CI changes are self-host-only; the banner is a hook `init`
  deploys)
- Change type: CI + hook (reporter) + one engine fix. The hook and workflow edits need the
  approval marker in the PR title (`/ship` step 3 binds it).
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
  are in flight. The adopter-axes pack (`DEF-975`) will add a perturbation cell to `test.yml`; this
  pack adds the Windows slice job to the same file. Land this one first.
- Authored 2026-09-30 on the public tree at `4eef108b` (PR #47 merged). Every "measured"
  sentence names its command; execution re-runs it rather than trusting the snapshot.

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
- **1-D** the required Windows slice: a job on every pull request that runs the slice file
  under `-n auto`, a test that every listed path collects and the list is floored, the
  admission rule written where the receiver's reader will see it, and the branch-protection
  step the operator runs.
- **2-A** the red-team.
- **Files this pack may write** (named so `/scope-check` can walk them):
  `tests/test_finding_ledger.py`,
  `.github/workflows/portability.yml`, `.github/workflows/test.yml`,
  `.github/windows-slice.txt`, `tests/test_windows_slice.py`,
  `tools/cc/hooks/session_start.py` (and `espalier/_vendor/cc/hooks/session_start.py` by
  `scripts/sync_vendor_cc.py`, never by hand), `tests/test_session_banner.py` (the file that pins `_merged_prs_line`), `.claude/commands/ship.md` (and its two
  mirrors by `scripts/sync_claude_mirrors.py`), `docs/RELEASE_CHECKLIST.md` (one sentence),
  `CHANGELOG.md`, `task-packs/FORWARD_LEDGER.md` and `task-packs/LEDGER_PROBES.json` (the
  `DEF-939` repin, through the verb).

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
- **Making the full Windows leg required**: 67–90 minutes of merge latency on every pull
  request, and two of the three non-`DEF-939` Windows reds in the last two weeks were timing
  flakes (runs `36097120794`, `36222363651`). The slice is the required half; the full leg
  stays advisory and the receiver carries it.
- **A marker-derived slice** (`-m portability`): measured at authoring by classifying the
  twelve files that have been Windows-red, no existing marker covers them (they fall under
  `contract`, `unit`, `security`, `integration`, and `slow`), and inventing a marker is a
  hand-kept list under another name. The slice is a path list with a mechanical admission
  rule (1-D) and a floor.
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
rows = json.loads(subprocess.check_output(
    ["gh", "pr", "list", "--state", "merged", "--limit", "5", "--json", ",".join(ss._PR_FIELDS)]))
for pr in rows:
    reds = [c for c in ss._latest_run_per_check(pr.get("statusCheckRollup") or [])
            if ss._check_outcome(c) == "red"]
    print(pr["number"], [c.get("name") or c.get("context") for c in reds])
print("line:", repr(ss._merged_prs_line(rows, local_has_commit=lambda sha: True)))
EOF
```

*(The exact keyword of `_merged_prs_line`'s "does the local base have this commit" argument
is read from the function at execution; the shape above is the intent, and the authoring
drive used the live helper.)*

**Measured at authoring, 2026-09-30:** the required list is the eight above; the `Test` step
has no `-n`; the last ten runs are eight `failure`, two `cancelled`, none `success`; the
receiver drive returns `#46 ['portability (windows-latest)']` and `#43 ['portability
(windows-latest)']` from the rollup while the `Merged:` line is empty. **Build.**

### 0-B The slice derivation and the timing baseline

**Refuting result:** if the derivation below yields fewer than **six** files, the slice is
too thin to be worth a required job; land 1-A, 1-B and 1-C and re-raise 1-D with the count.

The initial slice is the set of test files that have ever failed on the Windows leg, derived
from the leg's own logs (the population is the output of this command, never a list in this
pack):

```bash
for r in $(gh run list --workflow portability.yml --limit 40 --json databaseId --jq '.[].databaseId'); do
  gh run view "$r" --log-failed 2>/dev/null | command grep -oE 'FAILED tests/[A-Za-z0-9_]+\.py' ;
done | sort | uniq -c | sort -rn
```

Then the timing baseline, one narrowed Windows dispatch with the derived files as `select`
(the input takes pytest arguments; pass the paths space-separated) plus `-n auto`:

```bash
gh workflow run portability.yml -f os=windows-latest -f select="-n auto tests/test_finding_ledger.py …"
```

Record the leg's wall clock. **Measured at authoring:** the first command over the runs since
2026-09-25 names twelve files (listed in the review record
`reports/detection-review-2026-09-30/G3_ci_review.md`, gitignored, on the authoring box; the
command is the source, not the record). The dispatch was **not** run at authoring; 0-B runs it and its
number is the budget 1-D's job must meet (target: under fifteen minutes, hypothesised from the
serial leg's 0.26 s mean per test and a 4-vCPU runner; if the measured slice exceeds twenty
minutes, 1-D drops the slowest file by `--durations` output and records why).

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
warning-channel assertion (today: the channel is empty) becomes conditional on the lock's
real capability and every other assertion runs on every host:

```python target=tests/test_finding_ledger.py
        warnings_out = payload["warnings"]
        if _fof._HAS_FCNTL:
            assert warnings_out == []
        else:
            # DEF-939: no lock arm on this platform; the persist program reports the
            # unlocked read-modify-write and nothing else. Retires itself when the
            # lock class pack (DEF-974) lands a second arm and the flag it keys on
            # reads true there.
            assert len(warnings_out) == 1 and "UNLOCKED" in warnings_out[0], warnings_out
```

(`payload["warnings"]` is the name the test already reads; execution uses the test's own
binding.) A host whose `fcntl` imports but whose filesystem refuses `flock` (an NFS temp dir
without lockd) fails this assertion outright — loud, and correct: that host is not in CI and a
red there names a real degrade.

**Earn the red:** on a Windows dispatch (`-f os=windows-latest -f select=tests/test_finding_ledger.py`)
the three cases read `passed` and the job reads `success`. Mutation: key the branch on
`sys.platform == "linux"` instead of the capability; the cases red on Windows again. A POSIX
run is unchanged.

**Checkpoint:** the Windows dispatch reads `0 failed`; `pytest -q tests/test_finding_ledger.py`
locally is unchanged.

### 1-B The leg fails loudly, and faster

**Fix 2 — no summary line is a failure** *(prescribed; refuted if `pytest -q` under `-rfEs`
prints its summary in a shape the pattern below misses on any of the three runners — 0-A's
last green run on each OS is the sample to grep first):*

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
          if ! command grep -qE '^(=+ )?[0-9]+ (passed|failed|error|xfailed|skipped)' pytest-out.txt; then
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
`failure` with the `::error::` line; a deliberate `select="-k no_such_test"` dispatch (rc 5,
a summary line) reads `failure` with pytest's own exit code, proving the code survives the
tee. All three run ids go in Landing.

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
does supersede an older red (the authoring failure-mode review named both). A `cancelled`
run is not a red; it renders as `no verdict: <name>` only when no later run of that name
exists. One line per pull request that still owns a red, the same eight-second budget as the
block it joins. A pull request that is both un-pulled and red renders once with both clauses.

**Fix 4 — "held by the red" only when the red is required** *(prescribed):* in `_pr_summary`,
the clause that sets `held = "the red"` is emitted only when the red check's name is in the
required set. `gh pr list --json` carries no is-required flag; the cheapest true statement is
to reword to `red: <name> (required checks decide the merge)` and leave "held" for a red whose
name appears in the `required` list the banner can read with one extra bounded call,
`gh pr checks <n> --required --json name,bucket`, **only when a red exists** (so the common
green path pays nothing). Execution picks the reword if the extra call pushes the block past
its budget; Landing says which.

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

### 1-D The required Windows slice

**Fix 6 — the slice file and its test** *(prescribed):* `.github/windows-slice.txt`, one
repo-relative test path per line, seeded from 0-B's derivation, with a header comment stating
the admission rule:

```text target=.github/windows-slice.txt
# Windows slice: the required, fast Windows leg (test.yml job `windows-slice`).
# Admission rule: a test file named by a post-merge Windows red (the SessionStart
# `Merged:` line, or the full portability leg) joins this list in the fix that
# closes the red. Nothing leaves the list without a ledger row saying why.
# Floor and collection are pinned by tests/test_windows_slice.py.
tests/test_finding_ledger.py
…
```

`tests/test_windows_slice.py` asserts: every non-comment line is a path that exists; the count
is at least the floor 0-B derived (write the number 0-B produced, as a declared floor, with the
deriving command in the docstring); and `pytest --collect-only -q <paths>` collects at least one
test per path (so a renamed file cannot rot the slice silently). The floor is declared, not
derived, because a derived floor cannot notice a deleted entry
(`scripts/derived_population_census.py` is the precedent); the admission rule couples growth
to it — the fix that admits a file raises the floor to the new count in the same change — so
a later removal back to an old floor is the one gap, and 2-A names it. `.gitattributes` pins
the slice file `text eol=lf` beside the workflow bodies and the probes file, because a Windows
checkout under `autocrlf` would hand pytest paths ending in a carriage return (exit 4, no
tests). The same test pins the job: `windows-slice` in `test.yml` has no `if:`, no `paths:`,
no `needs:` and no `continue-on-error:` (a skipped required job counts as passed).

**Fix 7 — the job** *(prescribed; refuted if the measured slice exceeds twenty minutes on the
0-B dispatch — then drop the slowest file with its `--durations` line recorded, and re-measure):*
a `windows-slice` job in `.github/workflows/test.yml` on `windows-latest`, Python 3.12, `shell:
bash`, that installs `.[dev]` and runs `python -m pytest -q -n auto -rfEs $(command grep -v '^#'
.github/windows-slice.txt)` with the same no-summary guard as Fix 2. It has **no `paths:`
filter and no `if:`**: a required job that does not run leaves the pull request at "Expected"
forever, which is a worse hang than a fifteen-minute Windows cell on a docs-only change. It
runs every tier (`scripts/proof_tier.py --base` is not consulted), and `docs/RELEASE_CHECKLIST.md`
gains the one sentence that says so.

**The branch-protection step (operator, AFTER this pack has merged and the job has run
once on `main`'s pull requests):** add the one name, never replace the set (a hand-typed
replacement can drop a cell, and `-f strict=true` would send a string where the API wants a
boolean — the authoring failure-mode review):

```bash
gh api -X POST repos/Mike-Byrne-AI/espalier-harness/branches/main/protection/required_status_checks/contexts \
  -f 'contexts[]=windows-slice'
gh api repos/Mike-Byrne-AI/espalier-harness/branches/main/protection/required_status_checks/contexts --jq '. | join(", ")'
```

Order matters: a pull request whose head predates the job never runs it and would wait at
"Expected"; under the up-to-date rule such a lane is already `BEHIND` once this pack merges,
and `/ship` step 5's catch-up re-runs the checks on the merged base. `tests/test_required_status_checks.py`
derives the required population; execution reads that test before the POST so the new name is
admitted where the test expects it.

**Earn the red:** with the job live, a pull request that deliberately reds one slice test on
Windows only (a `pytest.skip` inverted under `sys.platform == "win32"` in a scratch branch,
never merged) shows the pull request `BLOCKED` with `windows-slice` red while the eight
`test (3.x)` cells are green. Landing records the scratch pull request number and that it was
closed unmerged.

**Checkpoint:** `pytest -q tests/test_windows_slice.py tests/test_required_status_checks.py`;
the job's first run on the pack's own pull request is green inside the 0-B budget.

### 2-A Red-team

Budget it. What this pack is most likely to have gotten wrong, in the author's order:

1. **The expectation's key** (Fix 1): `_HAS_FCNTL` is true on a POSIX host whose filesystem
   refuses `flock` (NFS), where the lock degrades with the same warning and the assertion
   fails loud. Ask whether that host exists in CI (it does not today) and whether the key
   should be the lock's *observed* behaviour rather than the module's presence.
2. **The receiver's negative** (Fix 3): a red superseded by a green re-run must render nothing;
   a check that was red on an *older* head of the same pull request must not be named against
   the merged head. `_latest_run_per_check` is the contract; ask whether it keys on head sha.
3. **The slice as a new hand-kept list** (Fix 6): the admission rule is prose plus a floor.
   Ask what removes an entry silently — a file rename passes the exists check if the old path
   is deleted *and* the new one added; the collect check catches a rename that leaves the old
   line, not one that drops it. Is the floor enough?
4. **A required job that can hang or be skipped**: an `if:`, `paths:`, `needs:` or
   `continue-on-error:` added later by a well-meaning edit re-opens the hole. The pin is in
   `tests/test_windows_slice.py`; ask whether it reads the job the way GitHub does.
6. **The slice shrinking to an old floor** (Fix 6): the floor rises with admissions and
   nothing forbids a later removal back to it. Ask whether a removal should require a ledger
   row by mechanism, not by prose.
5. **The no-summary guard's pattern** (Fix 2) on the three runners' actual `-q` output.

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
- `.github/windows-slice.txt`
- `tests/test_windows_slice.py`
- `.github/workflows/test.yml::windows-slice` (a job, declared by its file path for the walk)

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
| a Windows-only red on a slice file, before the merge (no row) | **CLOSED** by 1-D | the scratch pull request reads `BLOCKED` on `windows-slice` alone |
| a Windows-only red **outside** the slice | **NOT REACHED** by 1-D; reached after the merge by 1-C | the admission rule adds the file at the closing fix; until then the full leg and the receiver are its only net |
| `clean-checkout` and `release-readiness gate` reds | **NOT REACHED** before the merge; named after it by 1-C | making either required is its own decision (Scope out) |
| `DEF-968` | **NOT REACHED** | a different symbol in `session_start.py`; its own row |

---

## Pass criteria

- The Windows portability leg on `main` reads `success` with a summary line after 1-A and 1-B
  (run id in Landing); no assertion in `tests/test_finding_ledger.py` is weakened, and the
  warning-channel assertion is not removed — it is *expected* on a platform with no arm and
  *asserted empty* on one with an arm, keyed on the capability so the expectation cannot
  outlive the fix.
- `_merged_prs_line` names a merged, already-pulled pull request whose latest run of any
  check is red, and names nothing for one whose red was superseded by a green re-run; both
  pinned by tests that red under the named mutations.
- `/ship` step 0 prints post-merge reds; its three mirrors are byte-equal after the sync.
- `.github/windows-slice.txt` has at least the 0-B floor of paths, every path collects, and
  `tests/test_windows_slice.py` reds when a listed path is deleted or the floor is undercut.
- The `windows-slice` job has no `paths:` and no `if:`, pinned by a test; it is in the
  required-check list (0-A's command prints it) after the operator's PATCH.
- A deliberate Windows-only red on a slice file blocks a scratch pull request while the eight
  `test (3.x)` cells are green.
- The `-n auto` figure is recorded beside the serial figure, or the flag is absent and a row
  says why.
- `ruff check .`, `mypy tools/cc/hooks/`, the contract tier, `python3 scripts/sync_vendor_cc.py`
  and `python3 scripts/sync_claude_mirrors.py` all clean; the hook type gate on the Linux view.

## Files touched

- **New:** `.github/windows-slice.txt`, `tests/test_windows_slice.py`.
- **Modified:** `tests/test_finding_ledger.py`, `.gitattributes` (the slice file pinned LF),
  `.github/workflows/portability.yml`, `.github/workflows/test.yml`,
  `tools/cc/hooks/session_start.py`, `espalier/_vendor/cc/hooks/session_start.py` (by sync),
  `tests/test_session_banner.py`, `tests/test_required_status_checks.py`,
  `.claude/commands/ship.md` + `espalier/assets/claude/commands/ship.md` +
  `examples/dogfooding/.claude/commands/ship.md` (by sync), `docs/RELEASE_CHECKLIST.md`,
  `CHANGELOG.md`, `task-packs/FORWARD_LEDGER.md` + `task-packs/LEDGER_PROBES.json` (a repin
  of `DEF-939` naming the expectation, through the verb, `--dry-run` first; no strike).
- **Deleted:** none.
- **Unmodified on purpose:** `scripts/proof_tier.py` (the slice is not a tier; it runs every
  pull request), `tests/conftest.py` (no marker is invented), `bench/` (untouched).

## Sub-task ordering

1. **0-A** census (30 min budget) — may end or shrink the pack. Checkpoint: the three
   commands' output pasted into `reports/tp460/0-A.md` (gitignored, record-rooted).
2. **0-B** slice derivation + timing dispatch (45 min, most of it waiting on the runner).
   Checkpoint: the derived list and the minutes.
3. **1-A** the expectation, Windows dispatch (30 min). Checkpoint: `0 failed` on Windows.
4. **1-B** no-summary guard + `-n auto` measured (45 min). Checkpoint: two dispatch ids.
5. **1-C** receiver + `/ship` (90 min). Checkpoint: the `Merged:` line on this checkout.
6. **1-D** slice file, test, job; first green on the pack's own pull request; the operator's
   PATCH; the scratch-branch block (90 min). Checkpoint: the required list prints
   `windows-slice`.
7. **2-A** red-team (60 min). Checkpoint: verdicts folded, mutations named.
8. Landing: the `DEF-939` repin through the verb; `/preflight`; `/commit`; `/ship` with the
   marker in the title.

## Estimated effort

Budgets, quoted as budgets (the last pack ran about 2.7× over its numbers): 0-A 0.5 h, 0-B
0.75 h, 1-A 0.5 h, 1-B 0.75 h, 1-C 1.5 h, 1-D 1.5 h, 2-A 1 h, landing 0.5 h — **7 h**, of
which about two hours is waiting on Windows runners.

## Landing
- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
