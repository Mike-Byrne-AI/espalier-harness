# TP-450 — Make the 2026-09-17 incident's remedy a mechanism, not a discipline note

## Status

- Version target: pre-alpha hardening (no release dependency)
- Change type: safety / developer tooling (one PostToolUse advisory)
- **Kind: PACK**
- Ledger row: `DEF-841` (§C0, `major` / HYGIENE / MAINTAINER), repinned 2026-11-06 to this scope.
- **Re-scoped 2026-11-06** on the operator's ruling of 2026-11-04 (operator call
  `20261102T072655Z-air-bcd005`, ruling `20261104T065604Z-air-2e9498`: option (1),
  narrowed). The pack is now **the write-time advisory alone**. The 2026-09-19 draft,
  its Task 0 result and the ruling are recorded under *How the scope moved*; the
  dispatcher's ruling on the re-scope's three open choices (the probe, the grade,
  the draft's 4-A) is `20261107T024101Z-air-d26d85`.
- Split out: `DEF-5085` (§C0, `minor`): the two hand-written condition copies, formerly
  sub-task 2-A.
- Sibling lane: the loop-head reader family (`DEF-836`, `DEF-837`), which the draft
  ordered first, landed as TP-451 (`task-packs/Done/`, `State: LANDED`).

---

## Motivation

On 2026-09-17 a scratch driver, written to size the `DEF-830` loop-carrier class,
executed a fixture row carrying a variable the driver never bound. The shell
expanded it to nothing and the adjacent glob to the filesystem root, and a
recursive delete ran as the operator's admin user for twenty seconds. Full
record: `docs/incidents/2026-09-17-real-shell-fixture-wipe.md`.

That record closes with four rules. **Measured at HEAD, by reading the source:**

| Rule | Mechanism today | After this pack |
|---|---|---|
| 1 — every operand relative, every variable bound | `bench/reachability_differential.py::assert_safe_to_execute` (and its PowerShell twin), for code that imports them | unchanged |
| 2 — `$`, `~`, leading `/`, or a glob beside a variable → classifier-only | same, for code that imports them | **plus** the advisory, on the glob-beside-a-variable shape in any Python file Claude writes, imported or not |
| 3 — a subprocess timeout is not a blast-radius bound | **none** | none (*Scope (out)*) |
| 4 — past one headline spelling per shell, answers come from a test class run by name | **none** | none (*Scope (out)*) |

**The gap is reachability, not coverage.** The incident's driver was a scratch
artifact: it imported nothing, so the bench's conditions protected it not at
all, and no tree scanner reads a scratchpad file. **There is no live
unprotected executing site in the tree** (measured during the 2026-09-19
authoring: `bench/guard_metamorphic.py` reaches the conditions by import
through `bench/reachability_differential.py::bash_reaches`); this pack is not
claiming a live hole and must not be executed as though it were.

**Who is hurt** (`STANDING_PRINCIPLES` §16): the maintainer who writes a scratch
driver to size a guard class, adds a row with a variable beside a glob, and runs
it on a box with no backup destination. Adopters never drive this population
(the incident report's last section).

### How the scope moved

1. **2026-09-19, the draft.** Four candidate mechanisms and a Task 0 licensed to
   end the pack: would any of them fire on an import-free scratch driver?
2. **2026-11-02, Task 0** (win-2's request `830911` at `54caffb`; nothing executed):

   | Candidate | Fires on the incident's driver without being called? |
   |---|---|
   | A shared `assert_safe_to_execute` | **no** — import required |
   | A folder `CLAUDE.md` ladder on `bench/` | **no** — the scratchpad is outside the repo; instruction-layer |
   | A tree scanner (a shell run on non-literal text) | **no** — a scratchpad file is not scanned |
   | A `PreToolUse` arm reading the driver at `python3 <driver>` | **yes** — new guard capability with its own false-positive surface |
   | *(not in the draft)* a `PostToolUse` rule on the driver's own write | **yes** — advisory, before the run |

3. **2026-11-04, the fact-check** (a fresh verifier, read-only, for the operator's
   ruling: agent `a1516bb` in the dispatcher's session `68742f14`, a transcript, not
   a commit; its census scripts lived in that session's scratchpad). Its scoring,
   copied:

   | Mechanism | Fires on the incident's driver? |
   |---|---|
   | A shared helper | **no** — the driver imports nothing (verified) |
   | A `bench/` ladder | **no** — the scratchpad is outside the repo |
   | A tree scanner | **no** — scratchpad files are not scanned |
   | A write-time `PostToolUse` rule | **yes**, on both Edits, 28 s before the run (probable) |
   | A `PreToolUse` arm | **yes**, if the driver's path variable resolves (probable) |

   The incident's driver was a scratchpad file named drive830.py, written by the Write tool at
   05:09:38Z; the rows that wiped the host were added by two Edits at 05:11:19Z and
   05:11:27Z; the driver ran at 05:11:47Z. The write-time rule fires on both Edits,
   about 28 s before the run. Its census, over the full-file state of every `.py`
   Write and Edit in 1,175 Mac transcripts (5,513 operations), fired twice, both on
   those two Edits: 0 false positives. Asked of each Edit's payload alone, it fires
   **0** times, because the dangerous Edit added rows and no shell call. **The rule
   must read the file from disk.** Limits it named: 4,656 Edits unreconstructable
   (their base file is not in the transcript, mostly repo files), Windows transcripts
   unread, the literal covers rule 2's glob shape only.
4. **2026-11-04, the ruling:** (1), narrowed. The write-time advisory alone, with
   that census as its first calibration. The `PreToolUse` arm stays out (*Scope (out)*).
   2-A is filed as a `minor` HYGIENE row under §C0 (now `DEF-5085`). `DEF-841` is
   unparked under this scope. A Time Machine destination is the operator's action,
   outside the pack.
5. **2026-11-06, the re-scope's own measurement** (at `140d937`, read-only, the
   detector below run over each population; nothing executed):
   - Transcripts: 1,200 Mac transcripts, 5,840 `.py` Write/Edit operations, 4,969
     unreconstructable, 4 states that do not parse. The detector fires twice, still
     the incident's two Edits.
   - **The tracked tree, the population the census could not read.** The census's
     regex reading fires on `tests/test_write_guard.py` (828 tracked `.py` files, 1
     fire): the file holds the delete literal and `shell=True` inside fixture strings
     and as a keyword to a guard helper, not a shell call. Every edit to the guard's
     main test file would have drawn the advisory.
   - An **AST reading** of the same two predicates (*Task 0*, *The detector*) fires
     **0** times on the tree and twice on the transcripts, the same two Edits.

**The steelman against.** The advisory is advisory, and the incident's session
already knew its rows were dangerous: it labelled them "unset-var glob". The
advisory's value is the interruption at the moment of writing, naming rule 2 and
the classifier-only route, 28 s before the run. Whether that is enough is what the
`PreToolUse` arm's separate ruling would decide, on a measured recurrence.

---

## Scope (in)

- **0** — Task 0: re-verify the detector on the three populations the hook will
  read before wiring it. Licensed to end the pack.
- **1-A** — The advisory: after a Write or Edit of a `.py` file, read the file from
  disk and, when it runs a shell on non-literal text and holds the delete literal,
  tell Claude. Advisory; never blocks; self-host tree only (*Task 0*, item 5).
- **1-B** — The calibration pinned as tests: the fire and silent rows below, and
  the tracked tree at zero fires.
- **1-C** — The incident record names the advisory beside rules 1 and 2.

## Scope (out)

| Deferred | Reason |
|---|---|
| A `PreToolUse` arm refusing `python3 <driver>` when the driver's source holds the shape | The ruling keeps it out: it lifts this pack's own scope-out (below) and is ruled apart only if the advisory proves insufficient. The trigger to raise it: a recurrence the advisory spoke on and the run still went ahead, filed as a row with the transcript cited. |
| Collapsing the two condition copies (the draft's 2-A) | `DEF-5085`, §C0 `minor`. Its reach to the incident is zero: the driver imported neither copy. |
| Rules 3 and 4 (the draft's 4-A) | Rule 3's bound in reach is Claude Code's sandbox, whose default write boundary refuses deletes outside the project: `task-packs/TP-476-guard-by-location.md`, wave B, which offers it; the sandbox is off by default and set in neither the project nor the user settings file on the Air (verified 2026-11-06; this checkout has no local settings file). A backup destination is recovery, not a bound: an operator action the ruling places outside the pack (none configured on the Air, verified 2026-11-04). Rule 4 is a method rule. The incident report already presents both rules as discipline, not mechanism, so there is no record to correct. |
| Any change to `write_guard` / `_bash_patterns` / `_speedbump` | The guard behaved correctly throughout the incident (`STANDING_PRINCIPLES` §2; the incident report says so). |
| Files written by a shell (`>`, a heredoc), `NotebookEdit`, MCP writes | The ruling names Write and Edit, and the census read only those. `tools/cc/hooks/post_write_check.py::_bash_derived_payloads` already derives a shell call's written paths on the self-host tree; it is the seam if a recurrence arrives that way. |
| Non-Python drivers (`.sh`, `.ps1`) | Unmeasured; the incident's driver was Python. |
| Widening the literal to `~` or a leading `/` (rule 2's other tokens) | A new calibration: the fact-check judged it would add false positives (probable, not driven). File a row with its census if wanted. |
| Every-tree wiring (adopter trees) | The calibration population is this repository's transcripts and tree; an adopter tree's false-positive surface is unmeasured (*Task 0*, item 5). |
| A backup destination | Recovery, not a bound; an operator console action, no code. |

⚠ **Scope-out is a claim.** The last row of *Task 0* decides the tree scope from a
measurement; if that measurement says every tree, this table's last-but-one row
moves into scope by re-raise, not by edit.

---

## Task 0 — Verify (may end this pack)

**The question:** does the detector fire on the incident's two Edits and on nothing
else in the populations this hook will read, and does it still need the file from
disk?

### The detector

Two predicates over the file's full text, both read from its syntax tree, so a
fixture string or a comment never satisfies the first:

1. **Runs a shell on non-literal text:** a call to `subprocess.run`, `Popen`,
   `call`, `check_output` or `check_call` whose first argument is a list or tuple
   of at least three items (a name, or a shell literal: `bash`, `sh`, `zsh`,
   `pwsh`, `powershell`, or the first three under `/bin/`; then `"-c"` or
   `"-Command"`; then anything that is not a string constant), or which passes
   `shell=True` with a first argument that is not a string constant.
2. **Holds the delete literal:** a string constant holding `rm` with flags that
   include `r`, `R` or `f`, followed within twenty characters by `$NAME` or
   `${NAME}`, quoted or not, then an optional `/` and a `*`. This is rule 2's glob
   beside a variable, the census's own literal, unchanged.

A file that does not parse is silent: a mid-edit state may not parse, and 4 of the
transcript states did not.

### Oracle

Run read-only, from a scratchpad script, never executing a row (incident rules 1
and 2; the fixture shape is asked of the predicates as text):

1. **Transcripts.** For every `.py` Write and Edit in this repository's Claude Code
   project folders on the Air (the sessions and their `subagents/`), reconstruct
   the file's full state per (transcript, path) from its Write and the Edits after
   it, and judge the state after each operation. An Edit whose base is not in the
   transcript is counted unreconstructable, never guessed. **Expected:** two fires,
   transcript `30c71df3`, the Edits at 05:11:19Z and 05:11:27Z on 2026-09-17.
2. **Payload alone.** Judge each Edit's `new_string` by itself. **Expected:** 0 on
   the incident's Edits.
3. **The tracked tree.** Judge every `git ls-files '*.py'` file read from disk.
   **Expected:** 0. (The regex reading's one fire, `tests/test_write_guard.py`, is
   the worked example of why the predicates are read from the syntax tree.)
4. **Windows transcripts.** The same census on a Windows seat's box, or recorded in
   *Landing* as unmeasured.
5. **The tree scope.** The populations above are this repository's. Wire the
   advisory on the self-host tree only (`_hook_utils.is_self_host_repo`), which is
   the measured population and `DEF-841`'s audience (MAINTAINER); an adopter
   tree's arm needs an adopter tree's census first.

### Refuting result

- (a) The incident's two Edits do not both fire.
- (b) Any other fire in population 1 or 3 that is not a true positive (a file that
  would run that delete on an unbound variable).
- (c) Population 2 fires on the incident's Edits: then the file read buys nothing,
  and the cheaper payload rule is the question.

### Exit

(a) or (b): stop and re-raise to the dispatcher with the fires listed. Do not
narrow or widen the predicates to clear them in place: a detector tuned to its own
calibration set is calibrated to nothing. (c): re-raise; the ruling chose the file
read on the census's evidence, so evidence against it is the ruling's to re-make.

---

## Relevant memory

What has gone wrong lately, measured: on 2026-11-04 fresh verifiers overturned a
premise in 5 of the dispatcher's 7 operator calls, and this pack's census, the
calibration the ruling named, could not read the tracked tree; the re-scope found a
false positive there on the first read. Expect the next unread population to hold
the next one.

| Entry | Where |
|---|---|
| A real-shell drive never runs a row with an unbound variable | auto-memory `a-real-shell-drive-never-runs-a-row-with-an-unbound-variable` |
| Calibrate an enforcement contract against the live population | `memory/calibrate-an-enforcement-contract-against-the-live-population.md` |
| A new pattern-detector trips the harness's own defenses | `docs/SHARP_EDGES.md` |
| Hook authoring patterns and gotchas | `memory/hook-authoring.md` |
| Fail-open with voice | `docs/CONVENTIONS.md` |
| Toolbelt, not security boundary | `docs/STANDING_PRINCIPLES.md` §2 |
| ReDoS budget receipt | `docs/SHARP_EDGES.md` |

Resolved at re-scope by reading those files; re-run `/recall` on "PostToolUse
advisory detector calibration" rather than trusting this list if the pack has been
sitting.

---

## Implementation

### 1-A The advisory *(fix shape: the predicates measured on populations 1 and 3; the wiring probable, not driven)*

- **Where:** `tools/cc/hooks/post_write_check.py::_check`, before its
  `_is_harness_file` gate, beside `record_file_marker_advisory` and the
  observers. A scratchpad file is not a harness file, so a check placed after the
  gate never sees one (the fact-check read the gate's position; nobody has driven
  a check there). **This hook is the home, not one choice among several:** an Edit
  runs two `PostToolUse` hooks (this one and `reflect_trigger.py`), and
  `DEF-841`'s probe drives this one, so an advisory built in the other or in a new
  hook never flips it (the dispatcher's ruling `20261107T024101Z-air-d26d85`). The
  module docstring, which says the hook reads harness files only, moves with it.
- **What it reads:** the written file, from disk, after a Write or an Edit whose
  path ends in `.py`. A path outside the checkout is read as given, since
  `_hook_utils.resolve_in_checkout` relates a path to a checkout and the incident's
  driver sat in no checkout. Bound the read: skip a file past a stated size, and
  say why in the code.
- **What it says:** one advisory through `_hook_utils.advise`, rendered into the
  hook's one JSON object, naming the file, the delete literal's line, incident
  rules 1 and 2, and the route: ask the row of the guard's classifier in memory;
  never execute it. 7-bit ASCII. Say it once per file and literal per session (a
  hypothesis: per file alone would hide a second dangerous row added later). A
  once-per-session record is a new `.espalier-state/` file: register it where the
  `docs/SHARP_EDGES.md` sweep says (the state-file parity test and the
  keep-or-clean family at SessionStart).
- **Where the predicates live:** in `tools/cc/hooks/post_write_check.py` itself (a hypothesis:
  it is a reporter with no `return 2` literal, and a new `tools/cc/hooks/_*.py`
  helper costs the helper census's sister sites, `docs/SHARP_EDGES.md`). A reason
  found at execution for a helper is declared under *Added-paths* before the edit.
- **Failure:** a read, decode or parse failure is silent with a
  `# fail-open: ok <kind> <reason>` marker (`tests/test_failopen_voice.py`), and
  costs none of the hook's other checks.
- **What the hook's description owes** (the dispatcher's note `20261107T024104Z-air-69142c`):
  every surface that says what this hook does says "harness files only" today:
  the module docstring, the root `CLAUDE.md` hook table's row, the hook table
  `espalier/cli.py` writes into an adopter's `CLAUDE.md`, and `docs/HOOKS.md`;
  each gains the advisory in the same lane, then `python3 scripts/sync_vendor_cc.py`.

### 1-B The calibration, pinned *(rows to write; each written to a temp folder and driven through the hook, never executed)*

Fire rows: the incident's shape written by the Write tool; the same file reached
by an Edit whose `new_string` carries the delete row alone (the payload-only
case, the load-bearing one); the `shell=True` form with a non-literal command;
`${V}` braces; `$V/*` unquoted.

Silent rows: the same driver with a literal command (`"ls"` as the third item); the
delete literal with no shell call (the `tests/test_write_guard.py` shape: fixture
strings and a helper's `shell=` keyword); a shell call with no delete literal; the
shape in a file that is not `.py`; a file that does not parse; the shape on a tree
that is not self-host.

The tree: a test that runs the detector over every tracked `.py` file and asserts
zero fires, so the next file that trips it is seen at its commit. It reads the
whole tree, so run the tree-walk ratchets beside it (auto-memory
`after-adding-a-test-that-reads-the-tree-run-the-five-walk-ratchets-in-the-targeted-set`).

Earn the red, one named mutation per predicate: drop the file read (the
payload-only row reds); drop the non-literal test (the literal-command row reds);
read the regex instead of the syntax tree (the fixture row reds); drop the
self-host gate (the adopter row reds).

### 1-C The incident record

`docs/incidents/2026-09-17-real-shell-fixture-wipe.md`: one sentence under rules 1
and 2 naming the advisory as the mechanism that speaks on rule 2's glob shape in a
Python file Claude writes, and its last section's "a discipline note and a memory
entry" gains "and one write-time advisory". Rules 3 and 4 stay as written. (Not a
record surface: `tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS` does not
list it.)

---

## Affected symbols

### Changed-semantics
- `tools/cc/hooks/post_write_check.py::_check`

### Renamed
- (none.)

### Added-paths
- (none declared: 1-A places the predicates in `tools/cc/hooks/post_write_check.py`; a helper module chosen at execution is declared here first, or `scope-check` cannot walk it.)

### Removed-paths
- (none.)

---

## Reach

Members derived by: the populations in *Task 0* (the Air's transcripts and the
tracked tree; Windows unread until item 4 runs).

| Item | Status | Evidence |
|---|---|---|
| `DEF-841` | **CLOSES** with 1-A, Task 0 green | its probe drives this hook on two Edits of files outside an isolated project root, each Edit's payload carrying the delete row alone: the incident's driver (a shell call on non-literal text and the row) and a twin holding the row with no shell call; it prints `open` while the hook is silent on the driver or speaks on the twin. At `140d937`: `open=True rc=0,0`. Earned on two scratch copies of the hook: a file-reading advisory on both predicates reads `open=False`; a payload-only rule keyed on the row reads `open=True`, so it cannot close the row |
| The incident's cause: a scratch driver written by Write or Edit | **REACHED** by 1-A (advisory) | populations 1 and 3 |
| A driver written by a shell or a notebook tool | **NOT REACHED** | *Scope (out)* |
| `DEF-5085` (the two condition copies) | **NOT CLAIMED** | its own row |
| Rules 3 and 4 | **NOT CLAIMED** | *Scope (out)* |

---

## Pass criteria

- Task 0's populations are counted, each fire listed, with population 4 measured
  or named unmeasured in *Landing*.
- `DEF-841`'s probe reads `open=False rc=0,0` at the head and `open=True rc=0,0`
  at the base, and the row is struck with the fix through
  `tools/cc/ledger_row.py strike --guard <a 1-B node red at the base by assertion>`.
- Every 1-B row passes, and each mutation above was shown red before the fix.
- No existing assertion on `tools/cc/hooks/post_write_check.py`'s outputs is weakened, and its
  outputs for harness files are unchanged.
- The advisory never blocks and never raises; its strings are 7-bit ASCII; any
  regex it adds passes `tests/test_redos.py`'s budget.
- `python3 scripts/proof_tier.py --base origin/main --run` at the tier the diff
  earns (a hook edit earns the full tier), after `python3 scripts/sync_vendor_cc.py`.

---

## Files touched

- **New:** none declared (see *Added-paths*).
- **Modified:** `tools/cc/hooks/post_write_check.py` and its vendored twin under
  `espalier/_vendor/cc/hooks/`, `tests/test_hooks.py` (or a test file of its own
  beside it), `docs/incidents/2026-09-17-real-shell-fixture-wipe.md`, the hook's
  rows in `CLAUDE.md`, `espalier/cli.py` and `docs/HOOKS.md` (1-A), a
  `changelog.d/` entry, and `DEF-841`'s row and probe at the strike.
- **Deleted:** none.
- **Unmodified on purpose:** `tools/cc/hooks/write_guard.py`,
  `tools/cc/hooks/_bash_patterns.py`, `tools/cc/hooks/_speedbump.py` (the guard is
  not the defect); `bench/reachability_differential.py` and
  `bench/powershell_reachability_differential.py` (`DEF-5085`'s).

---

## Sub-task ordering

1. **Task 0** — the four populations and the tree-scope reading. → checkpoint: a
   refuting result goes to the dispatcher; the pack may end here.
2. **1-B** — the rows, each red at the base. → checkpoint: the rows fail for the
   named reason, not an import error.
3. **1-A** — the advisory. → checkpoint: 1-B green; the hook's existing tests green.
4. **1-C** — the incident record. → checkpoint.
5. **Red-team** — `failure-mode-reviewer`, briefed: "this advisory may speak only
   where the session already knew", beside the reviewers
   `scripts/proof_tier.py --base origin/main` names. → checkpoint.
6. **Verify + Landing.**

---

## Estimated effort

| Sub-task | Budget |
|---|---|
| Task 0 | 45 min (the scripts are a scratchpad rewrite of the re-scope's) |
| 1-B | 60 min |
| 1-A | 60 min |
| 1-C | 15 min |
| Red-team | 40 min |
| **Total** | **about 3.5 h** |

---

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
