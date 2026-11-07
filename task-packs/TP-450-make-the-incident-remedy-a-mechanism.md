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
- Sibling lane: the loop-head reader lane the draft ordered first landed as TP-451
  (`task-packs/Done/`, `State: LANDED`; it struck `DEF-837`, and `DEF-836`'s
  PowerShell arm was its scope-out).

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
artifact: it imported neither bench module (it imported the guard's pattern module
and the standard library), so the bench's conditions protected it not at all, and no tree scanner reads a scratchpad file. **There is no live
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
   end the pack: would any of them fire on a scratch driver that imports neither bench module?
2. **2026-11-02, Task 0** (win-2's request `830911` at `54caffb`; nothing executed):

   | Candidate | Fires on the incident's driver without being called? |
   |---|---|
   | A shared `assert_safe_to_execute` | **no** — import required |
   | A folder `CLAUDE.md` ladder on `bench/` | **no** — the scratchpad is outside the repo; instruction-layer |
   | A tree scanner (a shell run on non-literal text) | **no** — a scratchpad file is not scanned |
   | A `PreToolUse` arm reading the driver at `python3 <driver>` | **yes** — new guard capability with its own false-positive surface |
   | *(not in the draft)* a `PostToolUse` rule on the driver's own write | **yes** — advisory, before the run (probable from the wiring, not driven) |

3. **2026-11-04, the fact-check** (a fresh verifier, read-only, for the operator's
   ruling: agent `a1516bb` in the dispatcher's session `68742f14`, a transcript, not
   a commit; its census scripts lived in that session's scratchpad). Its scoring,
   copied:

   | Mechanism | Fires on the incident's driver? |
   |---|---|
   | A shared helper | **no** — the driver imports neither bench copy (verified; the verifier's table says "nothing", its own text names the guard's pattern module) |
   | A `bench/` ladder | **no** — the scratchpad is outside the repo |
   | A tree scanner | **no** — scratchpad files are not scanned |
   | A write-time `PostToolUse` rule | **yes**, on both Edits, 28 s before the run (probable) |
   | A `PreToolUse` arm | **yes**, if the driver's path variable resolves (probable) |

   The incident's driver was a scratchpad file named drive830.py, written by the Write tool at
   05:09:38Z; the rows that wiped the host were added by the Edit at 05:11:19Z; the
   driver ran at 05:11:47Z. The write-time rule fires on the file's state after that
   Edit and after the next one at 05:11:27Z (which carried no row), the first about
   28 s before the run. Its census, over the full-file state of every `.py`
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
     fire): the file holds the delete literal and `shell=True` inside fixture strings,
     and the regex, which has no word boundary, reads the tail of `powershell=True`
     keywords to two guard helpers as `shell=True`; no shell call. Every edit to the guard's
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
  tell Claude. Advisory; never blocks; self-host tree only (the pack's proposal: *Task 0*, *The tree scope*).
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
| Every-tree wiring (adopter trees) | The calibration population is this repository's transcripts and tree; an adopter tree's false-positive surface is unmeasured (*Task 0*, *The tree scope*). |
| A backup destination | Recovery, not a bound; an operator console action, no code. |

⚠ **The tree scope is the pack's proposal** (*Task 0*, *The tree scope*): the
build's assign can overrule it, and an every-tree arm then moves into scope by
re-raise, not by edit.

---

## Task 0 — Verify (may end this pack)

**The question:** does the detector fire on the incident's Edits and on nothing else
in the populations this hook will read, and does it still need the file from disk?

### The detector (the pack's proposal: an AST reading of the census's predicates)

Two predicates over the file's full text, both read from its syntax tree, so a
fixture string or a comment never satisfies the first. The code that measured them
is the appendix (*The re-scope's census predicates*); Task 0 runs it unchanged.

1. **Runs a shell on non-literal text:** a call to `subprocess.run`, `Popen`,
   `call`, `check_output` or `check_call` whose first argument is a list or tuple
   of at least three items (a name, or a shell literal: `bash`, `sh`, `zsh`,
   `pwsh`, `powershell`, or the first three under `/bin/`; then `"-c"` or
   `"-Command"`; then anything that is not a string constant), or which passes
   `shell=True` with a first argument that is not a string constant. An aliased
   or bare-name import of `subprocess` is not matched (a declared limit of the
   measured reading).
2. **Holds the delete literal:** a string constant holding `rm` with flags that
   include `r`, `R` or `f`, followed within twenty characters by `$NAME` or
   `${NAME}`, quoted or not, then an optional `/` and a `*`. This is rule 2's glob
   beside a variable, the census's own literal, unchanged.

A file that does not parse is silent: a mid-edit state may not parse, and 4 of the
transcript states did not.

**What the re-scope already spent.** The re-scope read the tracked tree and the
two main transcript folders, and moved predicate 1 from the census's regex to the
syntax tree on what the tree showed (a string is not a call). That re-read used
the tree as a tuning set. Task 0 freezes the reading above and judges it on
populations it was not tuned on (items 4 and 5). A linear-time re-spelling of
predicate 2's regex with the same matches (1-A, *ReDoS*) is not a change of
reading.

### Oracle

Run read-only, from a scratchpad copy of the appendix's code, never executing a
row (incident rules 1 and 2; a fixture is asked of the predicates as text):

1. **Transcripts already read.** Every `.py` Write and Edit in every Claude Code
   project folder on the Air whose name starts with this clone's slug (Claude
   Code names a project folder for the checkout's absolute path, each `/` read as
   `-`; the main checkout's, its worktrees' and the pre-rename clone's all share
   it; the sessions and their `subagents/`).
   Reconstruct each file's full state per (transcript, path) from its Write and
   the Edits after it, and judge the state after each operation; an Edit whose
   base is not in the transcript is counted unreconstructable, never guessed.
   **Expected:** two fires, transcript `30c71df3`, on the file's state after the
   Edits at 05:11:19Z and 05:11:27Z on 2026-09-17, and nothing else. (Read at the
   re-scope: the two main folders, 1,200 transcripts, 5,840 operations, 4,969
   unreconstructable, 4 unparsed. Read at review: the 48 other folders, 488
   transcripts, 5,621 operations, no fire.)
2. **Payload alone.** Judge each Edit's `new_string` by itself. **Expected:** 0 on
   the incident's Edits.
3. **The tracked tree,** re-read at the build's base: every `git ls-files '*.py'`
   file read from disk. **Expected:** 0. (The regex reading's one fire,
   `tests/test_write_guard.py`, is the worked example for item 1 of *The detector*.)
4. **Held out by date (mandatory).** The transcripts written after 2026-11-06 in
   the same folders, judged apart: the first population the frozen reading was not
   tuned on. **Expected:** no fire, or true positives only.
5. **Windows transcripts.** The same census on a Windows seat's box, or recorded in
   *Landing* as unmeasured.
6. **Too narrow?** Shapes no population above holds, asked of the predicates as
   text: a literal shell head (`"bash"` as the first item), `subprocess.Popen`,
   `shell=True` with a variable command. **Expected:** each fires.

### Refuting result

- (a) The incident's Edits do not fire.
- (b) Any other fire in populations 1, 3, 4 or 5 that is not a true positive. A
  true positive is a file that hands a shell a row with rule 2's shape (a glob
  beside a variable, bound or not), judged by reading the file, never by running
  it.
- (c) Population 2 fires on the incident's Edits: then the file read buys nothing,
  and the cheaper payload rule is the question.
- (d) A shape in item 6 does not fire.

### Exit

(a), (b) or (d): stop and re-raise to the dispatcher with the fires listed. Do not
narrow or widen the predicates to clear them in place: a detector tuned to its own
calibration set is calibrated to nothing. A path exemption, the detector's own
test file included (under the syntax-tree reading none is needed), is a re-raise,
not an edit. (c): re-raise; the ruling chose the file read on the census's
evidence, so evidence against it is the ruling's to re-make.

### The tree scope (the pack's proposal, not ruled)

Wire the advisory on the self-host tree only (`_hook_utils.is_self_host_repo`):
the populations above are this repository's, and `DEF-841`'s audience is
MAINTAINER. An adopter tree's arm needs an adopter tree's census first, which is a
row, not this pack. Neither ruling (`2e9498`, `d26d85`) speaks to it, so the
build's assign may overrule it; `DEF-841`'s probe closes either way, since its
isolated root is self-host-shaped.

---

## Relevant memory

What has gone wrong lately, measured: on 2026-11-04 fresh verifiers overturned a
premise in 5 of the dispatcher's 7 operator calls
(`memory/session-log.d/2026-11-04-020109-air.md`); the census the ruling named
could not read the tracked tree, where the re-scope found a false positive on the
first read; and the re-scope's two reviewers found its first probe could never
close under the pack's own self-host gate (fixed before landing). Expect the next
unread population to hold the next one.

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
  gate never sees one (the fact-check read the gate's position; the probe's
  earning drove a minimal check there on scratch copies, and the advisory itself
  is undriven). **This hook is the home, not one choice among several:** an Edit
  runs two `PostToolUse` hooks (this one and `reflect_trigger.py`), and
  `DEF-841`'s probe drives this one, so an advisory built in the other or in a new
  hook never flips it (the dispatcher's ruling `20261107T024101Z-air-d26d85`).
- **What it reads:** the written file, from disk, after a Write or an Edit whose
  path ends in `.py`. A path outside the checkout is read as given, since
  `_hook_utils.resolve_in_checkout` relates a path to a checkout and the incident's
  driver sat in no checkout. Bound the read: skip a file past a stated size, and
  say why in the code.
- **What it says:** one advisory through
  `tools/cc/hooks/post_write_check.py::_say_once_to_claude`, keyed on the file and
  the literal (once per key per session through `_hook_utils.say_once`, whose flags
  SessionStart already sweeps, so no new state file), naming the file, the delete
  literal's line, incident rules 1 and 2, and the route: ask the row of the guard's
  classifier in memory; never execute it. 7-bit ASCII. Its event type is the audit
  record that `/status --log` counts, and the record the `PreToolUse` arm's trigger
  reads (*Scope (out)*). A proposal, untested (no ruling names the channel): a line
  in the hook's `operator` list as well, since the incident's session knew its rows
  were dangerous and the operator did not.
- **Where the predicates live:** in `tools/cc/hooks/post_write_check.py` itself (a
  hypothesis: it is a reporter with no `return 2` literal, and a new
  `tools/cc/hooks/_*.py` helper costs the helper census's sister sites,
  `docs/SHARP_EDGES.md`). A reason found at execution for a helper is declared
  under *Added-paths* before the edit.
- **ReDoS:** predicate 2's census regex has a quadratic flag class (6, 24 and 97 ms
  on runs of 1k, 2k and 4k flag letters, measured at review; about 6 s at the
  budget test's 32 KB, probable, against the hook's 10 s timeout, past which the
  hook's whole output for that call is lost). `tests/test_redos.py`'s sweep reads
  unbounded dot-quantifiers only, so the pattern takes a hand-added budget pin and
  a linear re-spelling with the same matches (one flag run, then a check that the
  run holds `r`, `R` or `f`).
- **Failure:** a read, decode or parse failure is silent with a
  `# fail-open: ok <kind> <reason>` marker (`tests/test_failopen_voice.py`).
  `ast.parse` raises `RecursionError`, not `SyntaxError`, on a valid deep
  expression (about 400 KB, measured at review on 3.14), so wrap the whole
  advisory in `except Exception` with the marker: it runs before the harness-file
  checks, and an error that escapes costs that write's checks.
- **What the hook's description owes** (the dispatcher's note
  `20261107T024104Z-air-69142c` and the review): six surfaces. The module
  docstring and `docs/HOOKS.md` (with its asset twin `espalier/assets/docs/HOOKS.md`:
  `python3 scripts/sync_asset_docs.py`,
  `tests/test_deploy_doc_parity.py::TestSourceAssetDocByteParity`) say it reads
  harness files; the root `CLAUDE.md` hook row says it validates each written file
  for JSON validity and path consistency. Three describe adopter trees: the hook
  table `espalier/cli.py` writes, `espalier/harness_config.py`'s reason for this
  hook, and `examples/CLAUDE.template.md`'s hook row; they leave the advisory out
  or say it runs on the harness's own tree only. Then
  `python3 scripts/sync_vendor_cc.py`.

### 1-B The calibration, pinned *(rows to write; each written to a temp folder and driven through the hook, never executed)*

Fire rows: the incident's shape written by the Write tool; the same file reached
by an Edit whose `new_string` carries the delete row alone (the payload-only
case, the load-bearing one); a literal shell head (`"bash"`); `subprocess.Popen`;
the `shell=True` form with a variable command; `${V}` braces; `$V/*` unquoted.

Silent rows: the same driver with a literal command (`"ls"` as the third item);
the delete literal with no shell call (the `tests/test_write_guard.py` shape:
fixture strings and `powershell=True` keywords, which the regex reading takes for
`shell=True`); a shell call with no delete literal; the shape in a file that is
not `.py`; a file that does not parse; a deep expression that raises
`RecursionError`; the shape on a tree that is not self-host.

The tree: a test that runs the detector over every tracked `.py` file and asserts
zero fires, so the next file that trips it is seen at its commit. It walks the
whole tree, so run the tree-walk ratchets beside it:
`tests/test_utf8_text_io.py::TestLiveTreeWalkRatchet` and
`tests/test_derived_population_census.py::TestSegmentHelper` and `::TestCensusHealth`.

Earn the red, one named mutation per predicate: drop the file read (the
payload-only row reds); drop the non-literal test (the literal-command row reds);
read the regex instead of the syntax tree (the fixture row reds); accept a bare
name only as the head (the literal-head row reds); drop the self-host gate (the
adopter row reds).

### 1-C The incident record

`docs/incidents/2026-09-17-real-shell-fixture-wipe.md` is a closed record: its
sentences stay as written. Append a dated note at its end naming the advisory as
the mechanism that speaks on rule 2's glob shape in a Python file Claude writes on
the harness's own tree; rules 3 and 4 unchanged. (Not a declared record surface:
`tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS` does not list it; the
appended note is this pack's proposal for keeping it true.)

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
| `DEF-841` | **CLOSES** with 1-A, Task 0 green | its probe drives this hook on Edits of three files outside an isolated project root, each Edit's payload carrying the delete row: the incident's driver (a shell call on non-literal text and the row), a twin holding the row with no shell call, and a third holding the shell call with no row; it prints `open` while the hook is silent on the driver or speaks on either other file, and exits without printing when the hook fails. The isolated root is self-host-shaped (the folders, a `pyproject.toml` naming the project, a copy of `write_guard.py` for the prefix pin), so an advisory gated to the self-host tree, as *Task 0*, *The tree scope* proposes, can close it. At `140d937`: `open=True`. Earned on three scratch copies of the hook: a file-reading advisory on both predicates reads `open=False` ungated and gated on the self-host test alike; a payload-only rule keyed on the row reads `open=True`, so it cannot close the row |
| The incident's cause: a scratch driver written by Write or Edit | **REACHED** by 1-A (advisory) | populations 1 and 3 |
| A driver written by a shell or a notebook tool | **NOT REACHED** | *Scope (out)* |
| `DEF-5085` (the two condition copies) | **NOT CLAIMED** | its own row |
| Rules 3 and 4 | **NOT CLAIMED** | *Scope (out)* |

---

## Pass criteria

- Task 0's populations are counted and each fire listed, items 4 and 6 read, and
  item 5 measured or named unmeasured in *Landing*.
- `DEF-841`'s probe reads `open=False` at the head and `open=True` at the base, and
  the row is struck with the fix through
  `tools/cc/ledger_row.py strike --guard <a 1-B node red at the base by assertion>`.
- Every 1-B row passes, and each mutation above was shown red before the fix.
- No existing assertion on `tools/cc/hooks/post_write_check.py`'s outputs is
  weakened, and its outputs for harness files are unchanged.
- The advisory never blocks and never raises (the `except Exception` umbrella with
  its marker); its strings are 7-bit ASCII; predicate 2's regex carries a
  hand-added `tests/test_redos.py` budget pin and runs in linear time.
- The six description surfaces say what the hook now does, the three adopter-facing
  ones claiming nothing on adopter trees; the asset-doc and vendor syncs ran.
- `python3 scripts/proof_tier.py --base origin/main --run` at the tier the diff
  earns (a hook edit earns the full tier).

---

## Files touched

- **New:** none declared (see *Added-paths*).
- **Modified:** `tools/cc/hooks/post_write_check.py` and its vendored twin under
  `espalier/_vendor/cc/hooks/`, `tests/test_hooks.py` (or a test file of its own
  beside it), `docs/incidents/2026-09-17-real-shell-fixture-wipe.md` (an appended
  note), the six description surfaces of 1-A (`CLAUDE.md`, `espalier/cli.py`,
  `espalier/harness_config.py`, `examples/CLAUDE.template.md`, `docs/HOOKS.md` and
  `espalier/assets/docs/HOOKS.md`), a `changelog.d/` entry, and `DEF-841`'s row and
  probe at the strike.
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
| Task 0 | 45 min (the appendix's predicates and oracle item 1's reconstruction) |
| 1-B | 60 min |
| 1-A | 60 min |
| 1-C | 15 min |
| Red-team | 40 min |
| **Total** | **about 3 h 40 min** |

---

## Appendix — the re-scope's census predicates

The code that measured the 2026-11-06 figures, copied from the re-scope's
scratchpad script (`ast_census.py`; the reconstruction around it is oracle item 1's
prose). Quoted here so the build lane runs the frozen reading, not a rewrite. It
reads text and executes nothing.

```python
import ast, re

DANGER = re.compile(r'\brm\s+-[A-Za-z]*[rRf][A-Za-z]*\s+[^\n]{0,20}?["\']?\$\{?\w+\}?["\']?/?\*')
SHELLS = {"bash", "sh", "zsh", "pwsh", "powershell", "/bin/bash", "/bin/sh", "/bin/zsh"}
FUNCS = {"run", "Popen", "call", "check_output", "check_call"}

def _const_str(n):
    return isinstance(n, ast.Constant) and isinstance(n.value, str)

def ast_exec(tree):
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if not (isinstance(f, ast.Attribute) and f.attr in FUNCS
                and isinstance(f.value, ast.Name) and f.value.id == "subprocess"):
            continue
        if not n.args:
            continue
        a0 = n.args[0]
        if isinstance(a0, (ast.List, ast.Tuple)) and len(a0.elts) >= 3:
            head, flag, text = a0.elts[0], a0.elts[1], a0.elts[2]
            head_ok = isinstance(head, ast.Name) or (_const_str(head) and head.value in SHELLS)
            if head_ok and _const_str(flag) and flag.value in ("-c", "-Command") and not _const_str(text):
                return True
        for k in n.keywords:
            if k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True and not _const_str(a0):
                return True
    return False

def ast_danger(tree):
    return any(_const_str(n) and DANGER.search(n.value) for n in ast.walk(tree))

def fires(src):
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return False
    return ast_exec(tree) and ast_danger(tree)
```

The `DANGER` pattern is the census's own (`census2.py`, the fact-check's
scratchpad) and carries the quadratic flag class 1-A re-spells; `fires` catches the
two parse errors the census caught, and 1-A widens that to `except Exception`.
---

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
