# TP-476 — Guard by location: move the protected-zone and secret-read jobs to the layer that owns location

## Status

- Version target: after `0.8.0b2`. Each wave is its own lane with its own Task 0.
- Type: assessment (this document) + feature (waves A and B) + process (wave C).
- **Kind: ROADMAP.**
  - Wave A's Implementation is close to copy-ready, because its premise was measured on 2026-10-07.
  - Waves B to D carry fix shapes marked untested, and each earns its own Task 0 before a lane touches it.
  - This pack must not enter an unattended chain: wave B changes what `init` writes into an adopter's settings, which is an operator decision.
- Ledger: one §3 row names this pack (filed 2026-10-07). Wave C re-routes the live guard rows whose job is location (members derived in Task 0, never listed here).
- Gate, the operator's words on 2026-10-07: "we need to make the changes to the location and method of guarding bash and other like commands", and "I dont think there is a reason to undo any of the guards as of now". So **no parser guard is removed or weakened by this pack**; wave D is a decision to re-raise with data, not a change.
- Sibling: `TP-475` (the ledger learns when work is worth doing). This pack is the instance that motivated it.
- Provenance: measured on the Windows clone on 2026-10-07; the sandbox facts were read from the Claude Code docs the same day. Each claim names its source.

## Motivation — the assessment

**What the guard does today.** `tools/cc/hooks/write_guard.py` is a PreToolUse hook on every tool call. Its dispatch, read 2026-10-07, routes each tool to its own check:
- `Write`, `Edit` and `NotebookEdit` go to `::check_write_edit`, which compares one `file_path` field with the zones;
- `Bash` goes to `::check_bash_for_protected_mutations`;
- `PowerShell` goes to `::check_powershell_for_protected_mutations`;
- MCP tools go to `::check_mcp`.

For the two shell tools the guard gets one `command` string, a whole program. It has to work out, from text alone and without running anything, what the program would write, delete or read, in three shell languages (Bash, PowerShell, and cmd.exe reached from either).

The readers that do this sit in `tools/cc/hooks/_bash_patterns.py`. Measured by AST name prefix (so the split is approximate):

| | Total | Bash or shared | PowerShell | cmd |
|---|---|---|---|---|
| top-level functions | 279 | 196 | 72 | 11 |
| module-level patterns | 177 | 113 | 56 | 8 |

Between the 09-24 cut and 2026-10-07 the module grew from 12,404 to 13,609 lines, and `write_guard.py` from 2,240 to 2,877.

**Why it cannot be finished.** Predicting a program's writes from its text is undecidable in general: a path computed at run time, or a program inside a string, has no reading. `docs/HOOKS.md` already declares that as "the indirection class". So every reader fix adds a finite slice of an unbounded space. Across the four guard lanes merged up to 2026-10-07, each fix lane's reviewers found one to three neighbouring spellings, filed as new rows at about 1:1 (`TP-475`'s Motivation carries the series). Security engineering calls this design "enumerating badness": listing the bad inputs instead of controlling the resource they act on.

**Which jobs are location jobs.** From `docs/HOOKS.md` §4 and the root `CLAUDE.md` hooks table:

| Job | About a location? | Layer that owns it |
|---|---|---|
| Keep the harness from being edited or removed (hook scripts, `.claude/settings.json`, the CI guard workflow, the integrity manifest, an adopter's `protected_paths`) | yes, entirely | the OS refusing the write (sandbox), or a check after the write |
| Secret reads (dotenv files, credentials) | yes | the sandbox's read deny |
| Catastrophic deletes (the project, home, the filesystem root) | yes, but undoing them after the fact is impossible | prediction stays, kept conservative |
| Speed bumps (force push, release tag) | no: an action on a remote | the parser (a short list of git and gh verbs) |
| Kill switch | the contents of a settings file | `config_guard.py` and `_integrity.py::scan_for_kill_switches` (unchanged) |

**What the location layer already has (read 2026-10-07, not driven):**
- `tools/cc/hooks/_integrity.py::verify_integrity` checks every file in the integrity manifest whatever wrote it, and `::canonical_text_bytes` already normalises CRLF before hashing.
- The trigger is spelling-dependent. `tools/cc/hooks/post_write_check.py::_integrity_spot_check` runs only per written path that `::_check` sees, and for Bash and PowerShell those paths come from `::_bash_derived_payloads`, which calls the guard's own extractors in `_bash_patterns`. So a write the parser cannot read never triggers the spelling-independent check.
- `_integrity_spot_check` never blocks; it warns.

**Cost (measured on this Windows box):**
- Canonical-hashing all 28 files the main checkout's manifest lists: 6.1 ms median, 7.0 ms max.
- A stat pass over the 58 tracked files under the zones: 0.8 ms.
- `post_write_check.py` already runs after every Bash and PowerShell call, so no new process is needed.

**The manifest gap (verified 2026-10-07).** `.espalier/integrity.json` is gitignored and machine-local, so it is **absent in a linked worktree**, where background jobs and lane agents run. There, `verify_integrity` reports `MANIFEST_ABSENT`, which the spot check suppresses on purpose.

**What Claude Code's sandbox gives.** Read 2026-10-07 from https://code.claude.com/docs/en/sandboxing:
- "The sandbox runs on macOS, Linux, and WSL2. On native Windows, Claude Code runs commands unsandboxed."
- The limits "apply to Bash, PowerShell, and Monitor commands and the processes they start", enforced by the operating system.
- It already denies writes to the `.claude` settings files, the `.claude/hooks`, `skills`, `agents` and `commands` directories, `.git/hooks` and more. "There is no way to exempt one of these paths."
- Configured limits use `sandbox.filesystem.denyWrite` and `denyRead`. While the sandbox is admin-required, "a repository's files: deny entries ... still apply", so a project can add its own deny paths.
- The unsandboxed retry is turned off with `allowUnsandboxedCommands: false`. "A `false` in your user settings, `--settings`, or managed settings holds even when a project's settings set `true`."
- `tools/cc/` and `cc/` are not on the built-in list.

**The earlier rejection to reread.** `docs/sharp-edges/chmod-444-decision.md` rejected OS-level protection against an *attacker* ("chmod 444 is itself bypassable ... friction (one extra command), not a guarantee"). `docs/STANDING_PRINCIPLES.md` §2 says the threat model is "operator/AI mistakes, not malice". Under that model, a check that fires on every spelling is better friction than a parser that catches some spellings.

**The named user (§16).** An adopter whose agent, hurried or drifting, rewrites a hook script or `settings.json` through a shell spelling the parser does not read. The hooks then go quiet for the rest of the session, and nothing tells them until CI.

## Scope (in) — the waves

- **Task 0** (this pack's, before any wave): re-triage by job, manifest coverage, the Mac sandbox measurements, and the Mac cost.
- **Wave A — a spelling-independent after-check, every host.** After every Bash and PowerShell call, run the integrity check and the kill-switch scan once, regardless of which paths the parser extracted. On drift: tell Claude through PostToolUse's top-level `decision` and `reason` (pinned in `docs/external/cc-hook-protocol.md`, the PostToolUse section), and write an audit row. Restoring is decision A2. Close the worktree manifest gap.
- **Wave B — the sandbox posture where the OS has one.**
  - `init` and `upgrade` offer `sandbox.filesystem.denyWrite` entries for the harness zones and the adopter's `protected_paths`, plus `denyRead` entries for the secret paths. The secret roster is derived from `tools/cc/hooks/write_guard.py::_SECRET_PATH_LABEL`, never copied.
  - `doctor` reports the sandbox state, the deny entries, and the user-scope `allowUnsandboxedCommands`.
- **Wave C — route the work.**
  - Guard rows whose job is location and which wave A (and B, where the host has it) covers are struck as covered, with the location layer's own test as the oracle. That test is spelling-independent by construction, so no census of spellings is needed.
  - The `hook-authoring` skill's "Test pattern" section learns that location jobs are proven at the location layer.
  - The guard-lane brief gains a sibling-spelling step for the parser tiers that remain.
  - Optional: measure the runtime of `bench/guard_row_probe.py` and `bench/powershell_guard_rehearsal.py` (both evaluator-only; only the hand-run `scripts/host_check.py` runs them today), and put them in a guard lane's proof if the runtime fits.
- **Wave D — re-raise, do not change.** With A to C landed and their data in hand, put to the operator:
  - whether the parser's zone deny becomes advisory on hosts with a location layer;
  - whether the false-deny rows of `§C61` close that way;
  - whether the catastrophic tier's "cannot read the target, so nudge" rule widens.

## Scope (out)

- **Removing or weakening any parser guard.** The operator's call on 2026-10-07; wave D re-raises it with data.
- **Bash-versus-PowerShell parity on one target** (`DEF-1041`). An open operator decision; this pack neither encodes nor closes it.
- **Sandbox network settings.** Not a guard job, and they change an adopter's workflow far more than file limits do.
- **Managed settings.** An organisation's layer, not the harness's.
- **A census or generator of command spellings.** Four lane agents building one were stopped by the platform classifier on 2026-10-07 (`docs/CLASSIFIER_FALSE_POSITIVES.md`, "Variant generation"), and this design makes one unnecessary: the location layer's coverage does not depend on spelling.

## Task 0 — Verify (try to kill the redesign)

**0-A Re-triage the live guard rows by job.**
- Oracle: the live member rows of `task-packs/FORWARD_LEDGER.md` whose site cell names any of `tools/cc/hooks/_bash_patterns.py`, `tools/cc/hooks/write_guard.py`, `tools/cc/hooks/_speedbump.py`, `tools/cc/hooks/_protected_zones.py`, `bench/guard_metamorphic.py`, `bench/guard_row_probe.py`, `bench/powershell_guard_rehearsal.py`, or a `bench/*reachability*` script. Parse them with `tools/cc/generate_ledger_regions.py`.
- Classify each row by its **headline sentence only** into one of: zone, secret read, catastrophic delete, speed bump, false deny, instrument, other.
- Pre-registered:
  - the reach of waves A and B is the zone rows, the secret-read rows, and the false-deny rows whose cause is zone over-reading;
  - write the count and the ids into this pack's Reach table before any wave starts.
- **Refuting result:** fewer than a quarter of the guard rows are location jobs. The ledger payoff is then small. Re-raise: wave A may still be worth it as robustness, and the operator decides.
- **Exit:** stop and re-raise.

**0-B Manifest coverage against the zone roster.**
- Derive the files the integrity manifest covers. Read the main checkout's `.espalier/integrity.json` `files` keys; it is absent in a linked worktree.
- Derive the zones the guard protects: `tools/cc/hooks/_protected_zones.py::PROTECTED_PREFIXES`, `::PROTECTED_FILES`, plus an adopter's `protected_paths`.
- Name which zones the manifest leaves out.
- **Refuting result for wave A as designed:** the manifest covers none of the hook scripts. Wave A then needs a snapshot of its own; re-scope it.

**0-C The sandbox, on the Mac** (this Windows box has none). In a throwaway repo, with the sandbox enabled and a project `sandbox.filesystem.denyWrite` naming one dummy directory:
- one harmless write into that directory through Bash, and one through PowerShell (pwsh): refused?
- a `git checkout` of a file under it: refused, with "unable to unlink old"? That decides whether `espalier upgrade`, run by an agent inside the sandbox, can work.
- under `bypassPermissions`, does the unsandboxed retry run without a prompt? Does a user-scope `allowUnsandboxedCommands: false` stop it?

**Refuting result for wave B:** a project `denyWrite` does not take effect. Wave B then reduces to `doctor` reporting plus documentation.

**0-D The Mac's cost** of wave A's per-call check, beside this box's 6.1 ms.

**Hygiene, binding on every task:**
- 0-A reads one row's first sentence at a time, in effect-words.
- 0-C uses one harmless write per tool into a dummy directory of a throwaway repo, and no delete commands.
- No spelling roster appears anywhere (`docs/CLASSIFIER_FALSE_POSITIVES.md`).

## Relevant memory

Recent pattern, measured 2026-10-07:
- The guard parser's fix lanes replaced their own rows at about 1:1.
- The after-the-fact check that would cover every spelling exists, but is triggered only by paths the parser extracts.
- Four lane agents asked to measure the spelling population were stopped by the platform classifier.

| Entry | Where |
|---|---|
| Derive a guard from its calibrated sibling, don't author it fresh | `memory/derive-a-guard-from-its-calibrated-sibling.md` |
| A Content-Hash Pin Over Raw Bytes Is CRLF-Sensitive | `docs/SHARP_EDGES.md` (that section) |
| Deleted-Governance-Event Fail-Open (N7) | `docs/sharp-edges/deleted-governance-event-fail-open.md` |
| A gate can be blind along a whole dimension of its input | `memory/a-gate-can-be-blind-along-a-whole-dimension.md` |
| chmod 444 on hook files — considered and rejected | `docs/sharp-edges/chmod-444-decision.md` |
| Why this repo trips safety classifiers | `docs/CLASSIFIER_FALSE_POSITIVES.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |

Resolved at authoring time with `python tools/cc/hooks/_recall.py "integrity manifest drift detection of protected hook files"` and `python tools/cc/hooks/_recall.py "derive a guard from its calibrated sibling"`. The last three entries were named by hand. Re-run the queries if the pack has been sitting.

## Implementation

### Wave A-1 Run the integrity check after every shell call *(fix shape, untested; premise read, not driven)*

In `tools/cc/hooks/post_write_check.py::_check`, for `tool_name` in `("Bash", "PowerShell")`:
1. Call `_integrity.verify_integrity(root)` once.
2. Call `_integrity.scan_for_kill_switches` once.
3. Do both regardless of what `::_bash_derived_payloads` returned.
4. Keep the per-path spot check for `Write`, `Edit` and `NotebookEdit` as it is.
5. Leave maintenance mode as it is. `post_write_check` is not bypassed by it (root `CLAUDE.md`, "Maintenance mode"), so on the self-host tree under maintenance mode the check reports drift as an advisory and never blocks; decision A3 settles the exact behaviour.

- **Refuted if:** `verify_integrity` reports drift after an ordinary `espalier upgrade` run through Bash, because upgrade rewrites the files before the manifest. Then compare after the call against the manifest as rewritten, or exempt the upgrade's own process. Driving one upgrade in a scratch tree decides it.
- **Earn the red:** in a temp repo with a manifest, a Bash call whose command text names nothing in the zone, but which writes a manifest file through a program the parser does not read (a small script file that writes the target, created and run in two plain calls). The drift must be reported. The test must be red against the current `_check`, where the derived payloads are empty.

### Wave A-2 Decide: restore, or tell only *(operator decision; the fix shape follows the answer)*

- **Restore.** Restore drifted tracked files from git with `git checkout -- <path>`, and restore `.claude/settings.json` (gitignored) from a copy the check keeps under `.espalier-state/`.
- **Tell only.** Block with a reason through PostToolUse, so Claude reads the reason, and write an audit row.

Under §2 either is sufficient friction. Restoring changes the tree behind the agent, and that should be the operator's call.

### Wave A-3 Close the worktree gap *(fix shape, untested)*

In a linked worktree, read the main checkout's manifest. Resolve it with `git rev-parse --git-common-dir`, the same rule as `scripts/record_snapshot.py::linked_worktree_main`, derived and not copied. Fall back to "absent, said once" (`docs/CONVENTIONS.md`, "Fail-open with voice").

**Where the resolution lives is a design decision.** `verify_integrity` has several production callers; derive them with `grep -rn 'verify_integrity(' tools/cc espalier scripts --include=*.py`. On 2026-10-07 they were:
- the post-write check;
- the SessionStart banner's drift report;
- `espalier doctor`;
- the `espalier integrity` command path;
- the module's own entry point.

Two options, each with a cost:
- **Resolve inside `verify_integrity`.** Every caller gains worktree coverage at once, including the banner, which today reports nothing in a worktree.
- **Resolve at the post-write call site only.** The readers stay as they are.

Name the choice in the lane's plan, and test every caller the choice reaches.
- **Refuted if:** the main checkout's manifest pins files whose worktree copies legitimately differ (a lane editing a hook). Then compare only files the lane has not committed. Decide by driving one worktree that edits a hook and commits it.

### Wave B-1 The sandbox posture *(fix shape, untested; waits on 0-C)*

- `espalier/cli.py::cmd_init` and `::cmd_upgrade` print, and on an opt-in flag write, into `.claude/settings.json`:
  - `sandbox.filesystem.denyWrite`: the harness zones (from `_protected_zones`) plus the adopter's `protected_paths`;
  - `sandbox.filesystem.denyRead`: the secret paths, derived from `write_guard.py::_SECRET_PATH_LABEL`.
- They never set `sandbox.enabled` without the flag, because enabling the sandbox changes the adopter's network and approval behaviour.
- `espalier/cli.py::cmd_doctor` reports the sandbox state, the entries present, and whether the user scope sets `allowUnsandboxedCommands: false`. That is printed advice, never written, because it is user scope.
- On native Windows, `doctor` says there is no sandbox and that wave A is the location layer.
- **Self-host:** `denyWrite` on `tools/cc/` blocks this repo's own daily hook edits, so the self-host tree needs its own profile. Decision B2.

### Wave C-1 Route the guard rows, and teach the skill *(process; waits on A and on 0-A)*

- For each row 0-A classed as a location job, strike it as covered by the location layer. Use wave A's spelling-independent test as the probe (`python tools/cc/ledger_row.py strike ...`; the probe is the test by name). Record that the parser's spelling gap remains a declared limit.
- In `.claude/skills/hook-authoring/SKILL.md`, "Test pattern": location jobs are proven at the location layer. The parser tiers that remain (catastrophic deletes, speed bumps) are proven by a composition over the code's own verb roster, as `tests/test_write_guard.py::TestPowerShellRecursiveRemoveTiersAgree` does. Then run `python scripts/sync_claude_mirrors.py`.
- In `TP-475`'s filing advisory, the guard surface's layer question names this pack.

## Affected symbols

`/scope-check` keys on bare names. At authoring it listed docs, bench fixtures and sharp-edge entries that merely mention `cmd_init` or `verify_integrity`, and those are not touched. The one real sibling it surfaced is the set of other `verify_integrity` callers, which wave A-3's design decision addresses.

### Changed-semantics
- `tools/cc/hooks/post_write_check.py::_check`
- `tools/cc/hooks/post_write_check.py::_integrity_spot_check`
- `tools/cc/hooks/_integrity.py::verify_integrity`
- `espalier/cli.py::cmd_init`
- `espalier/cli.py::cmd_upgrade`
- `espalier/cli.py::cmd_doctor`

### Renamed
- (none -- no symbol is renamed by any wave)

### Added-paths
- (none -- wave A's tests join the existing post-write-check test module, or a new one named by the lane)

### Removed-paths
- None.

## Reach

Members derived by Task 0-A's oracle (the live guard rows, classed by job from their headline). The roster is that oracle's output at execution time and is deliberately not listed here.

| Item | Status | Evidence |
|---|---|---|
| guard rows classed **zone** or **secret read** | **TO BE REACHED by waves A and B**, per row, in this table, after 0-A | wave A's spelling-independent test |
| guard rows classed **false deny** caused by zone over-reading | **NOT REACHED** by this pack | wave D re-raises: closing them means relaxing a parser guard, which the operator ruled out for now |
| guard rows classed **catastrophic delete** | **NOT REACHED** | after-the-fact cannot undo a delete; prediction stays |
| guard rows classed **speed bump** | **NOT REACHED** | an action on a remote, not a location |
| `DEF-1041` | **NOT REACHED** | an operator decision (scope out) |

## Pass criteria (per wave; each wave's own pack or lane restates its own)

- **Task 0:**
  - the 0-A counts and ids are in this pack's Reach table;
  - the 0-B coverage gap is named;
  - the 0-C answers are recorded with the Claude Code version they ran on;
  - any refuting result has stopped the affected wave, and the record says so.
- **Wave A:**
  - the earn-the-red test is red against the current `post_write_check.py::_check` and green after;
  - an ordinary `espalier upgrade` through Bash reports no drift;
  - a linked worktree is covered or says once that it is not;
  - the added latency per shell call is measured on both hosts and written down;
  - no existing post-write-check assertion is weakened.
- **Wave B:**
  - `init` without the flag writes no `sandbox` key;
  - with it, the entries match the zone and secret rosters by derivation (a test changes a roster and sees the entries follow);
  - `doctor` reports the three states.
- **Wave C:**
  - every struck row names wave A's test as its probe;
  - the skill and its mirrors are in sync;
  - no parser assertion is weakened.

## Files touched

- **Task 0:** none (measurements; results written into this pack).
- **Wave A:**
  - `tools/cc/hooks/post_write_check.py`;
  - `tools/cc/hooks/_integrity.py` (A-3);
  - their vendored mirrors via `python scripts/sync_vendor_cc.py`;
  - tests for the post-write check;
  - `docs/HOOKS.md` (the post-write-check section);
  - `CHANGELOG.md`.
- **Wave B:**
  - `espalier/cli.py`;
  - its tests;
  - `docs/HOOKS.md` or `docs/ADOPTING.md` (the posture);
  - `CHANGELOG.md`.
- **Wave C:**
  - `task-packs/FORWARD_LEDGER.md` and `task-packs/LEDGER_PROBES.json` (through `tools/cc/ledger_row.py` only);
  - `.claude/skills/hook-authoring/SKILL.md` and its mirrors.
- **Unmodified on purpose:**
  - `tools/cc/hooks/_bash_patterns.py`;
  - `tools/cc/hooks/write_guard.py`'s deny logic;
  - every parser guard (the operator's call).
- **Reread before wave B:** `docs/sharp-edges/chmod-444-decision.md`. Check whether it is a record surface (`tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS`) before editing it (root `CLAUDE.md` Core Rule 13). Supersede it with a slip-model note rather than rewrite a record.

## Sub-task ordering

1. Task 0: 0-A and 0-B on any host; 0-C and 0-D on the Mac. Checkpoint: results in this pack; stop where refuted.
2. Wave A: A-1, then A-3, then A-2 once the operator decides. Checkpoint: the earn-the-red test, the upgrade drive, the worktree drive.
3. Wave C: depends on A and 0-A. Checkpoint: the strikes through the ledger verb and the skill sync.
4. Wave B: depends on 0-C and decision B2. It may run beside C on the Mac. Checkpoint: the derivation test and `doctor`'s three states.
5. Red-team per wave: both reviewers. Ask for the write that lands and is never seen (a path outside the manifest, the worktree, a gitignored zone file) and for the legitimate update that trips the check.
6. Wave D: re-raise to the operator with A to C's data.

## Estimated effort

| Step | Budget |
|---|---|
| Task 0 | 2 h (half of it on the Mac) |
| Wave A | 5 h with red-team |
| Wave C | 3 h |
| Wave B | 5 h |
| **Total** | **about 15 h**, three or four lanes |

**Most likely to be wrong:**
- that the manifest covers the zones that matter (0-B decides);
- that a legitimate upgrade does not trip the check (A-1's refutation);
- that the self-host tree can live with any `denyWrite` posture.

## Landing

- State: ROADMAP
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
