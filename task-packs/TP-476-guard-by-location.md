# TP-476 — Guard by location: move the protected-zone and secret-read jobs to the layer that owns location

## Status

- Version target: after `0.8.0b2`. Each wave is its own lane with its own Task 0.
- Type: assessment (this document) + feature (waves A and B) + process (wave C).
- **Kind: ROADMAP.**
  - Wave A's premise is measured (2026-10-07, both sessions). Its design is a fix shape, untested, with pre-registered refutations; the first design was refuted by measurement before any code was written.
  - Waves B to D carry fix shapes marked untested, and each earns its own Task 0 before a lane touches it.
  - This pack must not enter an unattended chain: wave B changes what `init` writes into an adopter's settings, which is an operator decision.
- Ledger: one §3 row names this pack (filed 2026-10-07). Wave C re-routes the live guard rows whose job is location (members derived in Task 0, never listed here).
- Gate, the operator's words on 2026-10-07: "we need to make the changes to the location and method of guarding bash and other like commands", and "I dont think there is a reason to undo any of the guards as of now". So **no parser guard is removed or weakened by this pack**; wave D is a decision to re-raise with data, not a change.
- Sibling: `TP-475` (the ledger learns when work is worth doing). This pack is the instance that motivated it.
- Provenance: measured on the Windows clone on 2026-10-07; the sandbox facts were read from the Claude Code docs the same day. Each claim names its source.
- **Amended 2026-10-07, second session, before any wave ran:**
  - Task 0-B ran (result under 0-B).
  - Wave A's premise was corrected: the shell tools never reach the integrity check at all.
  - Wave A's design changed after measurement: the main checkout's manifest was stale, so a check against it would report drift on every shell call. Wave A now compares each call with the session's previous check.
  - The operator decided A2: **tell only** ("A2-tell only", 2026-10-07).
  - The secret-read rows were taken out of wave A's reach.

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
- **There is no shell trigger at all** (read 2026-10-07, second session; this corrects the first draft, which called the trigger spelling-dependent).
  - In `tools/cc/hooks/post_write_check.py::_check`, a Bash or PowerShell call feeds only `::_bash_derived_payloads`. That function builds reinject pointers from the guard's extractors and never calls `::_integrity_spot_check`.
  - `_check` then returns at its `_is_write_tool` gate, which admits `Write`, `Edit`, `NotebookEdit` and MCP write tools only.
  - So no shell write, however it is spelled, reaches the spelling-independent check. The per-path spot check runs for a write tool's root write only (`base == root`).
- `_integrity_spot_check` never blocks; it warns through the advisory collector, whose `additionalContext` reaches Claude next to the tool result (`docs/external/cc-hook-protocol.md`; Espalier uses `additionalContext` only).

**Cost (measured on this Windows box):**
- Canonical-hashing all 28 files the main checkout's manifest lists: 6.1 ms median, 7.0 ms max.
- The real `_integrity.verify_integrity` on the main checkout, lock and manifest read included (second session, a scratch timer over 30 in-process calls and 10 fresh interpreters):
  - 7.2 ms median warm in-process;
  - 12.9 ms median in a fresh process, the way a hook runs it;
  - one cold first call took 261 ms (file cache).
- A stat pass over the 58 tracked files under the zones: 0.8 ms.
- `post_write_check.py` already runs after every Bash and PowerShell call, so no new process is needed.

**The manifest gap (verified 2026-10-07).** `.espalier/integrity.json` is gitignored and machine-local, so it is **absent in a linked worktree**, where background jobs and lane agents run. There, `verify_integrity` reports `MANIFEST_ABSENT`, which the spot check suppresses on purpose.

**The manifest is also stale wherever it exists (measured 2026-10-07, second session).**
- The main checkout's manifest was generated 2026-10-05. `verify_integrity` reported 4 of its 28 files mismatched: `_bash_patterns.py`, `_denial_reasons.py`, `_speedbump.py`, `write_guard.py`.
- Each of those is a legitimate merge since that date, and the manifest is refreshed only by hand (`/integrity`).
- So a check that reports drift against the manifest after every shell call would report those four files on every call, for drift no call caused. On this tree that is the normal state, not an edge case: guard lanes merge hook changes several times a week.
- **The manifest answers "what changed since the operator last refreshed"; wave A needs "what did this call change".** Those are different questions, and the redesign below asks the second one.

**What the manifest and the kill-switch scan both miss (0-B, read, not driven).**
- `_integrity.MANIFEST_FILES` pins the 25 hook scripts, `tools/cc/_json_safe.py`, `tools/cc/ci_guard.py` and the CI guard workflow.
- It does not pin `.claude/settings.json`. `::scan_for_kill_switches` covers that file only for the shapes `::_find_kill_switches` names: `disableAllHooks`, an emptied event list, empty inner lists, and all-no-op commands.
- A settings file whose `hooks` key is removed reads as no finding (`data.get("hooks")` is not a dict), and so does a deleted file (`os.stat` raises `FileNotFoundError`, and the scan skips it). Either one silences every hook.
- Also outside the manifest:
  - `.claude/settings.local.json`;
  - `.espalier/*.json`;
  - the `cc/` tree;
  - the other `tools/cc/*.py` scripts;
  - an adopter's `protected_paths`.

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
- **Wave A — a spelling-independent after-check, every host.**
  - After every Bash and PowerShell call, compare the protected zones with the session's previous check, and report what changed, appeared or disappeared since then, whatever the command's spelling.
  - The comparison is against a per-session baseline, not the manifest (see "The manifest is also stale" above). So drift that was already there when the session started is never reported as this call's.
  - On a change, tell Claude through the advisory collector's `additionalContext` and write an audit row.
  - **Tell only, by the operator's decision (A2): nothing is restored.**
  - Because the baseline is per session and needs no manifest, the worktree gap (A-3) is closed for wave A by construction.
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
- **Result, 2026-10-07 (second session): not refuted as stated, and wave A was re-scoped anyway.**
  - The manifest's 28 keys equal `_integrity.MANIFEST_FILES` exactly, and they include every hook script.
  - The gaps are the ones listed under "What the manifest and the kill-switch scan both miss".
  - The decisive finding was a different one: the manifest is stale (4 of 28) in the normal course of merging. Wave A therefore takes a per-session snapshot of its own, the re-scope this refutation names, for a reason it did not foresee.
  - Driver: a scratch script that loads `tools/cc/hooks/_integrity.py`, compares the main checkout's `.espalier/integrity.json` `files` keys with `MANIFEST_FILES`, and calls `verify_integrity` on the main checkout and on this worktree. Re-derive it rather than trusting the four names, which change with every merge and refresh.

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
| A fixed fail-open can move rather than close | `memory/a-fixed-fail-open-can-move-rather-than-close.md` |

Resolved at authoring time with `python tools/cc/hooks/_recall.py "integrity manifest drift detection of protected hook files"` and `python tools/cc/hooks/_recall.py "derive a guard from its calibrated sibling"`. The last three entries were named by hand. Re-run the queries if the pack has been sitting.

## Implementation

### Wave A-1 Compare the zones after every shell call with the session's previous check *(fix shape, untested; replaces the first draft's manifest check, which the stale manifest refuted)*

**The first draft and why it was replaced.** The first draft called `_integrity.verify_integrity(root)` after every shell call. On the main checkout on 2026-10-07 that function reported 4 drifted files that no call had touched, so the check would have spoken on every shell call (Motivation, "The manifest is also stale"). It also needed a manifest that a linked worktree does not have.

**The zone set.** Derive it, never copy it:
- `_hook_utils.harness_protected_prefixes(root)`, the operative prefix list (it adds `espalier/` on self-host only);
- `_protected_zones.PROTECTED_FILES`;
- the adopter's `protected_paths` (`_hook_utils.adopter_protected_prefixes`).

Leave out the paths the harness's own hooks rewrite on their own schedule, through the existing predicate `post_write_check.py::_is_allowlisted` (the blueprint chain, `cc/execution_plan.json` and the rest of that allowlist) plus `_protected_zones.ALLOWED_IN_PROTECTED` and `::ALLOWED_PREFIXES_IN_PROTECTED` (the zone files agents legitimately rewrite, such as `cc/GOAL.md` and `cc/_working_summary.md`). Otherwise the check reports the harness to itself.

**The snapshot.** For each file under the zone set, take `(size, mtime_ns)`; take the canonical hash (`_integrity.canonical_text_bytes`) only for a file whose stat moved. A call that changed nothing then costs one stat pass. Directory listings are part of the snapshot, so an added file and a removed file both count.

**The flow:**
1. **SessionStart, every source,** takes the baseline. It is stored per session beside the session's marker under `_hook_utils.sessions_dir(root)`, with a suffix the marker readers do not match. Retire it in the same place and at the same time as its marker, so a session file's lifetime keeps one owner: `_hook_utils.prune_session_markers` and `::retire_same_window_markers` gain the baseline as a second file per session. Changes made while the session was closed, or before it began, are never reported as this session's.
2. **After every Bash and PowerShell call,** in `tools/cc/hooks/post_write_check.py::_check` and before the `_is_write_tool` return: re-snapshot, diff against the baseline, then replace the baseline (`_hook_utils.atomic_write_text`).
   - Hold a cross-process file lock across the read, diff and write, so two parallel calls in one session report a change once (to whichever finishes first) and never twice. Use `_hook_utils.lock_file` on a lock file beside the baseline; it is the primitive every hook lock site takes, from `tools/cc/_json_safe.py`.
   - **Not `_hook_utils.STATE_WRITE_LOCK`:** that is a `threading.RLock`, and it does not span two hook processes.
   - Where `lock_file` raises (its degrade path on a host without the primitive), report and accept a possible duplicate. Saying the same change twice is cheaper than saying nothing.
3. **After a write tool** (`Write`, `Edit`, `NotebookEdit`, MCP write): refresh the baseline entry for the written file only. That write was already judged by path before it ran, so the next shell call must not report it again.
4. **On a non-empty diff:**
   - one advisory through the collector (`_hook_utils.advise_warn`, which reaches Claude as `additionalContext`), naming the changed, added and removed zone paths, at most a handful by name and then a count;
   - one audit row (`post_shell_zone_change`, counted by `/status --log`);
   - when a settings file is among them, also run `_integrity.scan_for_kill_switches(root, include_unreadable=True)` and say whether the hook wiring is still present. A missing `hooks` key and a deleted settings file are named in their own words, because the kill-switch scan reads both as nothing (Motivation).
5. **The wording never claims the command wrote the file.** It says the zone changed since the previous check, which is this call, a parallel call, or another session in the same tree (the SessionStart `Sessions:` line names those).
6. **No baseline found** (a session that predates the change, a state directory that cannot be written): take one silently, check nothing for that call, and say once, by `say_once`, that the first call was unchecked.

**Legitimate rewrites through a shell call are reported, by design.** This includes a pull, merge or checkout that moves hook files, `espalier upgrade`, the ship driver's catch-up, and on self-host the vendor sync into `espalier/_vendor/`. Under tell-only that costs Claude one line. The refinement below softens the wording for the common case and stays optional.
- *Optional, untested:* store `HEAD` in the baseline. When a diff is found and `HEAD` moved, and every changed tracked file now equals its blob at the new `HEAD`, say "arrived with a checkout (HEAD a..b)". Run git only when the diff is non-empty, so the no-change path stays a stat pass.

**Maintenance mode (A3).** `post_write_check` is not bypassed by maintenance mode (root `CLAUDE.md`). Under it, `write_guard`'s zone check is off, so this check is the only zone signal; it stays on, and self-host sessions run under maintenance mode routinely (this session's own launch had it set). The lane decides the wording under maintenance mode. The proposed default is once per path per session, so a hook-editing lane is told once that its own files moved, not after every sync.

**Refuted if:**
- the added latency of a call that changed nothing exceeds 25 ms median on either host. Measure on both: this box and the Mac (0-D).
- in one ordinary lane on this tree, under maintenance mode, more than one shell call in ten reports a change. **Pre-registered here, before the lane runs.** The zone set is then wrong (most likely a harness writer the allowlist misses); re-scope it, and never raise the threshold.
- an ordinary `espalier upgrade` through Bash in a scratch adopter tree produces a report that the wording above would mislead Claude about. One drive decides it.

**Earn the red.** Each test names the mutation it must die to:
1. **Spelling independence.** In a temp repo, take a baseline, change a zone file outside the hook, then run `post_write_check` on a Bash payload whose command text names nothing in any zone. It must report. Red against the current `_check`, which returns at the `_is_write_tool` gate. Mutation: delete the shell branch.
2. **Drift already present is silent.** In a temp repo whose manifest already mismatches a zone file, take a baseline, then run on a Bash payload with no change in between. It must not report. Mutation: compare against `verify_integrity` instead of the baseline (the first draft's design), which must turn this red.
3. **A settings file without its hooks.** Rewrite `.claude/settings.json` without its `hooks` key between baseline and payload. It must report and name the missing wiring. Mutation: judge settings only by `scan_for_kill_switches`.
4. **A write tool refreshes, not reports.** An `Edit` payload for a zone file, then a no-op Bash payload. It must not report. Mutation: drop the refresh in step 3 of the flow.
5. **The harness's own writes are silent.** A blueprint file written under the blueprint directory between baseline and payload must not be reported. Mutation: drop the allowlist exclusion.

### Wave A-2 Restore, or tell only — **decided: tell only** (the operator, 2026-10-07)

- **Tell only** is the A-1 flow above: an advisory and an audit row; nothing in the tree is changed behind the agent.
- **Restore was declined.** The legitimate rewrites a shell call makes (pull, checkout, upgrade, catch-up, vendor sync) and the changes another session in the same tree makes all land in the same diff. A restore would revert the operator's or the other session's work. Telling costs one line.

### Wave A-3 The manifest readers in a linked worktree *(optional now; fix shape, untested)*

Wave A no longer reads the manifest, so its worktree gap is closed by construction. What remains is narrower: the manifest's own readers (the SessionStart drift report, `espalier doctor`) still report nothing in a linked worktree. The rest of this section is that narrower question, kept as it was drafted and decoupled from wave A.

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

- For each row 0-A classed **zone**, strike it as covered by the location layer. Use wave A's spelling-independent test as the probe (`python tools/cc/ledger_row.py strike ...`; the probe is the test by name). Record that the parser's spelling gap remains a declared limit.
- **Rows classed secret read are not struck by wave A's test.** A read changes nothing on disk, so no after-check can see it; only wave B's `denyRead` reaches it, and only on a host with a sandbox.
  - On native Windows the parser stays the only layer for secret reads.
  - Such a row closes only where every host has a layer for it. Otherwise it stays live, re-scoped by `ledger_row.py repin` (its `--text-file` and `--reason`) to name native Windows as the remaining surface.
- In `.claude/skills/hook-authoring/SKILL.md`, "Test pattern": location jobs are proven at the location layer. The parser tiers that remain (catastrophic deletes, speed bumps) are proven by a composition over the code's own verb roster, as `tests/test_write_guard.py::TestPowerShellRecursiveRemoveTiersAgree` does. Then run `python scripts/sync_claude_mirrors.py`.
- In `TP-475`'s layer questions (its memory note), the guard's protected-zone stream is the worked instance and names this pack.

## Affected symbols

`/scope-check` keys on bare names. At authoring it listed docs, bench fixtures and sharp-edge entries that merely mention `cmd_init` or `verify_integrity`, and those are not touched. The one real sibling it surfaced is the set of other `verify_integrity` callers, which wave A-3's design decision addresses.

Amended 2026-10-07 (second session): wave A no longer calls the integrity check, so `_integrity_spot_check` is withdrawn from the walk. `verify_integrity` stays only for the optional A-3. Wave A adds the SessionStart baseline and its retirement beside the session markers.
- Re-run of `/scope-check` after the amendment: `_run_main` reads HIGH-RISK at 220 references. That is a name collision: every hook's entry point has that name, and wave A touches only `session_start.py`'s.
- `prune_session_markers` (10 references) and `retire_same_window_markers` (13) are real. Read their callers and tests before giving them a second file per session.

### Changed-semantics
- `tools/cc/hooks/post_write_check.py::_check`
- ~~`tools/cc/hooks/post_write_check.py::_integrity_spot_check`~~
- `tools/cc/hooks/session_start.py::_run_main`
- `tools/cc/hooks/_hook_utils.py::prune_session_markers`
- `tools/cc/hooks/_hook_utils.py::retire_same_window_markers`
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
| guard rows classed **zone** | **TO BE REACHED by wave A** on every host (and by wave B where the OS has a sandbox), per row, in this table, after 0-A | wave A's spelling-independent test (earn-the-red 1) |
| guard rows classed **secret read** | **NOT REACHED by wave A** (a read leaves nothing on disk to compare). **TO BE REACHED by wave B** on macOS, Linux and WSL2 only. **NOT REACHED on native Windows**, where the parser stays the only layer | wave B's `denyRead` drive (0-C); no Windows layer exists |
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
  - each of A-1's five earn-the-red tests was seen red against its named mutation, and is green after;
  - a linked worktree is covered with no manifest present (earn-the-red 1 run in a worktree fixture);
  - an ordinary `espalier upgrade` through Bash in a scratch adopter tree produces wording that names what changed and does not say the command wrote it;
  - the added latency of a call that changed nothing is measured on both hosts and written down, under the 25 ms refutation line;
  - the noise rate of one ordinary lane on this tree is measured and written down, under the pre-registered one-in-ten line;
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
  - `tools/cc/hooks/session_start.py` (the baseline);
  - `tools/cc/hooks/_hook_utils.py` (the baseline's retirement beside the markers);
  - `tools/cc/hooks/_integrity.py` (only if the optional A-3 runs);
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
2. Wave A: A-1 (A-2 is decided: tell only); A-3 only if the manifest readers' worktree coverage is still wanted. Checkpoint: the five earn-the-red tests, the upgrade drive, the latency and noise measurements.
3. Wave C: depends on A and 0-A. Checkpoint: the strikes through the ledger verb and the skill sync.
4. Wave B: depends on 0-C and decision B2. It may run beside C on the Mac. Checkpoint: the derivation test and `doctor`'s three states.
5. Red-team per wave: both reviewers. Ask for:
   - the write that lands and is never seen (a path outside the zone set, a zone file the exclusions wrongly cover, a change between the SessionStart baseline and the first call);
   - the legitimate update that trips the check on every call;
   - the defect the new layer brings with it (the counter-warning above).
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
- ~~that the manifest covers the zones that matter (0-B decides)~~. 0-B ran: it covers the hook scripts but is stale in the normal course, so wave A no longer uses it;
- that the zone set's exclusions catch every harness writer, so wave A does not report the harness to itself (A-1's noise refutation; the self-host tree under maintenance mode is the hard case);
- that the per-session baseline survives parallel calls and session retirement without a duplicate or a lost report (earn-the-red 4 and the lock);
- that the self-host tree can live with any `denyWrite` posture.

**The counter-warning this pack is exposed to:** a layer move can relocate a defect instead of closing it. Since the 09-24 history cut, the layers the repo moved controls into (the path chokepoint, the fail-open voice gate) each drew defects of their own. Wave A is a new layer and will have its own; its red-team asks for them by name (Sub-task ordering, step 5).

## Landing

- State: ROADMAP
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
