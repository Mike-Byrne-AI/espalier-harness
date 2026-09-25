# TP-450 — Make the 2026-09-17 incident's remedy a mechanism, not a discipline note

## Status

- Version target: pre-alpha hardening (no release dependency)
- Change type: safety / test-infrastructure
- **Kind: PACK**
- Ledger row: `DEF-841` (§C0, `major` / HYGIENE / MAINTAINER)
- Sibling lane: the loop-head reader family (`DEF-836`, `DEF-837`). **That lane runs FIRST** — see *Scope (out)*.

---

## Motivation

On 2026-09-17 a scratch driver, written to size the `DEF-830` loop-carrier class,
executed a fixture row carrying a variable the driver never bound. The shell
expanded it to nothing and the adjacent glob to the filesystem root, and a
recursive delete ran as the operator's admin user for twenty seconds. Full
record: `docs/incidents/2026-09-17-real-shell-fixture-wipe.md`.

That record closes with four rules. **Measured at HEAD, by reading the source:**

| Rule | Mechanism today |
|---|---|
| 1 — every operand relative, every variable bound | `bench/reachability_differential.py::assert_safe_to_execute`, conditions 4–6 |
| 2 — `$`, `~`, leading `/`, or a glob beside a variable → classifier-only | same, condition 6 |
| 3 — a subprocess timeout is not a blast-radius bound | **none** |
| 4 — past one headline spelling per shell, answers come from a test class run by name | **none** |

Three further facts, all **measured**, and the third is why this pack may not be
worth building:

1. The conditions have **two independent hand-written definitions** —
   `bench/reachability_differential.py::assert_safe_to_execute` and
   `bench/powershell_reachability_differential.py::assert_safe_to_execute`.
   A condition strengthened on one shell is not strengthened on the other.
   Derive the count: see Task 0's oracle.
2. Both are **private to `bench/`**, reachable only by code that imports them.
3. **There is no live unprotected executing site.** A stronger premise was
   drafted and **refuted** during authoring: that `bench/guard_metamorphic.py`
   executes delete rows on a thinner check. Its two raw `run_bash_group` calls
   are a `command -v` resolution probe and a `bash -n` parse-only probe that
   execute no delete; its delete rows route through the imported `bash_reaches`
   to `bash_run`, which calls `assert_safe_to_execute`. **This pack is not
   claiming a live hole and must not be executed as though it were.**

**The gap is therefore reachability, not coverage.** The incident's driver was a
*scratch* artifact. It imported nothing, so it was protected by nothing, and a
shared helper it would not have called changes that not at all. That is the
question Task 0 exists to decide.

Precedent for not closing this onto prose: §C21 was closed with a sentence, the
helper was never built, five more sites re-introduced it and the class reopened
four days later. The sibling done right is `DEF-833`/`DEF-834`, where one shared
ascent (`tests/_site_path.py`) was extracted **after** two consumers needed it.

---

## Scope (in)

- **0** — Task 0: decide whether any proposed mechanism reaches the incident's
  actual cause. Licensed to end the pack.
- **1** — Derive the consumer population (the oracle, not a roster).
- **2** — *Conditional on Task 0:* collapse the two condition sets into one
  shared definition with a per-shell operand lexer, bench as first consumer.
- **3** — *Conditional on Task 0:* a **push-tier** mechanism that fires without
  being called — the only leg that addresses the scratch-driver shape.
- **4** — Rules 3 and 4: give each a mechanism or record why it cannot have one.

## Scope (out)

| Deferred | Reason |
|---|---|
| Any change to `write_guard` / `_bash_patterns` | The guard behaved correctly throughout the incident (`STANDING_PRINCIPLES` §2, and the incident report says so). This is maintainer test-driving method, not a guard defect. |
| The `DEF-836`/`DEF-837` loop-reader lane | Runs first. It executes nothing (its rows go through `tests/test_write_guard.py::run_bash_guard`, structurally incapable of executing), and it will add loop-carrier rows to the differential bench — which teaches this pack which conditions bite and which are over-strict. Writing the shared helper with a second calibrated consumer in hand is the `DEF-833` pattern. |
| A Time Machine destination | Operator console action, no code fix. Tracked separately; still not configured. |
| Retrofitting `tests/` guard drivers | `run_bash_guard` hands text to the hook as a JSON payload and executes nothing, so conditions there would guard a path that cannot fire. Task 0's population derivation must confirm this rather than assume it. |

⚠ **Scope-out is a claim.** The second row above asserts the loop-reader lane
executes nothing. Verify it at execution time rather than trusting this
sentence; if that lane grew an executing driver, this pack's ordering inverts.

---

## Task 0 — Verify (may end this pack)

**The question:** does *any* mechanism this pack could build fire on the
artifact that actually caused the incident — a freshly written scratch driver
that imports nothing?

### Oracle

Reconstruct the incident driver's **shape** from the incident report — a
standalone module under the scratchpad that builds rows and executes them.
**Reconstruct the shape, never the row:** every fixture text in this pack is
asked of a classifier in memory and never executed (incident rules 1–2; a row
with a glob beside a variable is classifier-only, and every row in this family
is that shape). Then, for each candidate mechanism, answer one question:

```
would this mechanism have fired on that module, unmodified, with no import of it?
```

Candidates to score, cheapest first:

| Candidate | Fires without being called? |
|---|---|
| A shared `assert_safe_to_execute` in `tests/` or `bench/` | **no** — import required |
| A folder `CLAUDE.md` ladder entry on `bench/` and the scratchpad | instruction-layer only |
| A scanner rule: a module that invokes a shell on **non-literal** text without the guard | only if the module is scanned — a scratchpad file is not in the tree |
| A `PreToolUse` arm: the harness's own guard refusing a `python3 <driver>` call whose source carries an unbound expansion beside a delete | fires at the moment that matters — **but** the guard judged the `python3` call correctly at the time and reading the driver's source is a new capability with its own false-positive surface |

Derive the current duplicate count:

```bash
python3 -c "import ast,pathlib;print(sum(1 for p in ['bench/reachability_differential.py','bench/powershell_reachability_differential.py'] for n in ast.walk(ast.parse(pathlib.Path(p).read_text(encoding='utf-8'))) if isinstance(n,ast.FunctionDef) and n.name=='assert_safe_to_execute'))"
```

Derive the would-be consumer population:

```bash
command grep -rln "run_bash_group\|shell=True\|\"bash\", \"-c\"\|\"sh\", \"-c\"" bench tests scripts --include="*.py"
```

then, for each hit, establish whether it executes a **delete row** or only a
resolution/parse probe. The refuted premise in *Motivation* is the worked
example of why the grep alone is not the answer.

### Refuting result

**If no candidate fires without being called**, the extraction is a `§C35`
cross-boundary dedup wearing a safety label. That is a real but much smaller
piece of work, and it is **not** what `DEF-841` was filed as.

### Exit

**Stop and re-raise.** Do not adjust and continue. Report to the operator with
the scoring table, and offer three options: re-scope to the push-tier mechanism
alone; demote the row to a `§C35` dedup and re-grade its severity to `minor`;
or close `DEF-841` WONTFIX with the reasoning recorded. The approval for this
pack was granted against "make the remedy a mechanism" — if measurement says no
mechanism reaches it, the approval is gone with the reason.

⚠ **`DEF-841`'s severity is explicitly contingent on this task.** The row grades
`major` on realised consequence and records the steelman for `minor` inline.
Task 0 refuting the mechanism is the trigger to re-grade.

---

## Relevant memory

Recent pattern, measured: the 2026-09-17 severity re-audit found that of 88
findings raised across 8 lanes, 85 died under adversarial refute — and that
several died because the finder proposed a change identical to what was already
recorded. Author this pack expecting its central claim to be the thing that
breaks. One already did: the `guard_metamorphic` premise in *Motivation* was
drafted, driven, and refuted before this pack was finished.

| Entry | Where |
|---|---|
| A real-shell drive never runs a row with an unbound variable | auto-memory `a-real-shell-drive-never-runs-a-row-with-an-unbound-variable` |
| Derive a guard from its calibrated sibling, don't author it fresh | `memory/derive-a-guard-from-its-calibrated-sibling.md` |
| Calibrate an enforcement contract against the live population | `memory/calibrate-an-enforcement-contract-against-the-live-population.md` |
| Gates the targeted proofs never show | `memory/four-gates-the-targeted-proofs-never-show.md` |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| Toolbelt, not security boundary | `docs/STANDING_PRINCIPLES.md` §2 |
| ReDoS budget receipt | `docs/SHARP_EDGES.md :: ReDoS budget receipt` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "<topic>"`;
re-run rather than trusting this list if the pack has been sitting.

---

## Implementation

Sub-tasks 2–4 are **conditional on Task 0** and are written as *fix shapes*, not
specifications.

### 2-A Collapse the two condition sets *(fix shape, untested)*

Refuted if Task 0's population derivation returns a consumer count of 2 — at
which point this is a dedup, not a safety fix, and belongs in §C35.

The two definitions differ in their operand lexer (POSIX word-splitting vs
PowerShell parameter binding) and agree on the six conditions. The shape is one
condition set parameterised by a per-shell operand extractor, not a copy with a
flag. `_delete_operands` and its PowerShell counterpart are the seam.

⚠ **Do not author a fresh condition set.** `memory/derive-a-guard-from-its-calibrated-sibling.md`:
a freshly written version is a regression against a calibrated one, and nothing
reds, because the two were never the same. Move the calibrated body; do not
retype it.

### 3-A The push-tier mechanism *(fix shape, untested — Task 0 decides which)*

Whichever candidate Task 0 scores as firing without being called. If that is the
scanner rule, its population is modules invoking a shell on non-literal text,
and it must be calibrated against the live tree before it is wired to anything
(`memory/calibrate-an-enforcement-contract-against-the-live-population.md`: a
naive first draft went from 30 false positives to 0 only after a throwaway probe
over the real population).

### 4-A Rules 3 and 4

Rule 3 already has a partial mechanism — `run_bash_group` kills the process
*group* rather than the parent. State plainly in the incident record whether
that is the whole of rule 3's mechanism or a down payment on it. Rule 4 is a
method rule; if it cannot have a mechanism, record that it cannot, in the
incident report, rather than leaving it to read as enforced.

---

## Affected symbols

### Changed-semantics
- `bench/reachability_differential.py::assert_safe_to_execute`
- `bench/powershell_reachability_differential.py::assert_safe_to_execute`

### Renamed
- (none — conditional on Task 0.)

### Added-paths
- (none declared at authoring time. Task 0 decides whether a shared module is added and where; declare it before execution, or `scope-check` cannot walk it.)

### Removed-paths
- (none.)

---

## Reach

Members derived by: the Task 0 population command above (scope: `bench`,
`tests`, `scripts`; a clean result is not an absence proof — the incident's own
driver lived in the scratchpad, outside every one of those roots, which is the
whole finding).

| Item | Status | Evidence |
|---|---|---|
| `DEF-841` | **CONDITIONAL** | closes only if Task 0 scores a candidate that fires without being called; otherwise re-graded or WONTFIX |
| The 2026-09-17 incident's actual cause | **NOT REACHED by sub-task 2** | a scratch driver imports nothing; extraction serves only code that already chose to be safe |
| §C35 (cross-boundary duplicates) | **NOT CLAIMED** | if Task 0 reduces this to a dedup, the row moves there rather than this pack claiming the class |

---

## Pass criteria

- Task 0's scoring table exists, with a verdict per candidate and the derived
  consumer population beside it.
- **If the pack proceeds:** no condition is weakened and no row is removed from
  either bench's population; the shared definition is the *moved* calibrated
  body, demonstrated by the earn-the-red below.
- Earn-the-red, per condition: each of the six must be shown RED against a named
  mutation before the fix — the incident's own shape (an unbound expansion in a
  delete operand) is condition 6's mutation, asked in memory, never executed.
- `pytest -q tests/test_reachability_differential.py tests/test_powershell_reachability_differential.py` green, and its assertions **strengthened or unchanged** — never relaxed to clear a red this pack introduces.
- `python3 scripts/proof_tier.py --run` at the tier the diff earns.

---

## Files touched

- **New:** none declared at authoring time (Task 0 decides).
- **Modified:** `bench/reachability_differential.py`, `bench/powershell_reachability_differential.py`, `docs/incidents/2026-09-17-real-shell-fixture-wipe.md` (rules 3–4 status).
- **Deleted:** none.
- **Unmodified on purpose:** `tools/cc/hooks/write_guard.py`, `tools/cc/hooks/_bash_patterns.py`, `tools/cc/hooks/_speedbump.py` — the guard is not the defect.

---

## Sub-task ordering

1. **Task 0** — scoring table + population derivation. → checkpoint: report to operator; pack may end here.
2. **1** — consumer population confirmed, `tests/` non-execution verified rather than assumed. → checkpoint.
3. **2-A** — conditional collapse, earn-the-red per condition first. → checkpoint: both bench test files green.
4. **3-A** — conditional push-tier mechanism, calibrated against the live tree. → checkpoint.
5. **4-A** — rules 3 and 4 recorded. → checkpoint.
6. **Red-team** — dispatch `failure-mode-reviewer` with the brief "this pack's mechanism may protect only code that was already safe." → checkpoint.
7. **Verify + Landing stanza.**

---

## Estimated effort

| Sub-task | Budget |
|---|---|
| Task 0 | 45 min — the pack may end here, and that is a good outcome |
| 1 | 20 min |
| 2-A | 90 min (conditional) |
| 3-A | 2 h (conditional; calibration dominates) |
| 4-A | 20 min |
| Red-team | 40 min |
| **Total** | **~1 h if Task 0 kills it, ~5 h if it proceeds** |

---

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
