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
- **Amended 2026-10-08, third session,** after the pack was assessed against its purpose: the guard that gets the best that can be done for shell commands, and ends the chase of one spelling after another. The operator approved the amendments.
  - **Wave A-0 is new and comes first:** a check that the hook wiring is still present, in the settings-change hook (`config_guard.py`, on ConfigChange). That layer sees every settings edit whatever wrote it, and can block it. The kill-switch scan it calls today lists ways to turn hooks off, so a removed `hooks` key or a deleted file reads as clean.
  - **Task 0-E is new:** one drive in a throwaway repo settles whether removing the `hooks` key mid-session also removes wave A's own hook, and whether ConfigChange sees and can stop it.
  - **Wave A-1 tells the operator, not only Claude** (the operator's decision, 2026-10-08). The advisory keeps `additionalContext`, which reaches Claude, and adds `systemMessage`, which Claude Code shows the user. A2 is unchanged: tell only.
  - **Wave A-1's zone set leaves out bytecode caches,** and its cost is restated on the real zone set.
  - **The named user is restated** with the measured case: whole-tree writes, such as a formatter, that name no protected path.
  - **Wave B's reach is wider than first drafted:** the sandbox's default write boundary refuses deletes outside the project. But the sandbox is off by default.
  - **Decision C3 is new:** the residual parser's coverage contract. Moving the location jobs does not stop the chase on the jobs that must stay predictive (catastrophic deletes, speed bumps, secret reads on native Windows). A contract saying which spellings are work does.
- **Amended 2026-10-09, the A-1 lane:** A-1 was built, with the design changes listed in its "Amended at landing" block: `cc/` unwatched, path 3 a pinned hook-side table, path 4 a record per writer, the removal rule tightened. Its pass criteria are restated under "Pass criteria". The Mac's latency (0-D) is owed.

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

**Why it cannot be finished.** Predicting a program's writes from its text is undecidable in general: a path computed at run time, or a program inside a string, has no reading. `docs/HOOKS.md` §4 already lists it among `write_guard`'s documented limits, under "What this does NOT catch": runtime path construction, two-step bypasses, and "Anything requiring actual execution to determine the target path". (Corrected 2026-10-08: earlier drafts quoted a phrase, "the indirection class", that the doc does not use.) So every reader fix adds a finite slice of an unbounded space. Across the four guard lanes merged up to 2026-10-07, each fix lane's reviewers found one to three neighbouring spellings, filed as new rows at about 1:1 (`TP-475`'s Motivation carries the series). Security engineering calls this design "enumerating badness": listing the bad inputs instead of controlling the resource they act on.

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
  - No hook emits `systemMessage` today: `grep -rn systemMessage tools/cc --include=*.py` finds only a docstring in `post_compact.py`, 2026-10-08.
  - Claude Code's hooks reference (code.claude.com/docs/en/hooks, read 2026-10-08) lists `systemMessage` among the fields every hook can return, as a "Warning message shown to the user". An advisory in `additionalContext` alone reaches Claude, and the operator only if they read the transcript.

**What a shell call writes that its text never names (measured 2026-10-08, third session).**
- `ruff format .` and `black .`, each driven through `write_guard.py` as a Bash PreToolUse payload on this tree, are allowed: exit 0, no decision printed. That verdict is right; refusing a formatter would be friction on every lane.
- On an adopter tree they rewrite the vendored hooks under `tools/cc/`, unless the adopter added the formatter exclude that `init` prints and never writes. `espalier/cli.py::_print_formatter_ignore_snippet` prints it, and `espalier ignore-snippet --format ruff` reprints it.
- No reader of command text can see that write, because no zone path appears in the text. The same holds for a repo-wide `sed`, a codemod, or a checkout.

This is the strongest case for an after-check, stronger than an unusual spelling of a write the parser was meant to read.

**Settings changes have a layer that sees the effect (read 2026-10-08).**
- Claude Code's hooks guide says the `ConfigChange` event "fires when an external process or editor modifies a configuration file", and that a hook blocks a change "from taking effect" by exiting 2 or returning a block decision.
- It also says direct edits to hooks in settings files "are normally picked up automatically by the file watcher". So a settings file whose `hooks` key is removed may stop the hooks within the session, wave A's own `post_write_check` among them. 0-E measures whether it does.
- `tools/cc/hooks/config_guard.py::_scan_payload` judges a settings change with `_integrity._find_kill_switches`, the same predicate as the SessionStart scan. That predicate lists the shapes that turn hooks off: `disableAllHooks`, an emptied event list, empty inner lists, all-no-op commands.
  - A file whose `hooks` key is gone matches none of them, and `_scan_payload` skips a file that does not exist. Both are allowed.
- The layer is right; the predicate enumerates the ways to switch hooks off instead of checking that the wiring is there. Wave A-0 changes the predicate.

**Cost (measured on this Windows box):**
- Canonical-hashing all 28 files the main checkout's manifest lists: 6.1 ms median, 7.0 ms max.
- The real `_integrity.verify_integrity` on the main checkout, lock and manifest read included (second session, a scratch timer over 30 in-process calls and 10 fresh interpreters):
  - 7.2 ms median warm in-process;
  - 12.9 ms median in a fresh process, the way a hook runs it;
  - one cold first call took 261 ms (file cache).
- A stat pass over the 58 tracked files under the zones: 0.8 ms.
- **Restated on the zone set wave A-1 would walk (2026-10-08, third session).**
  - `_hook_utils.harness_protected_prefixes(root)` on this self-host worktree names `tools/cc/`, `cc/`, `.github/workflows/` and `espalier/`. They hold 369 files on disk, untracked and bytecode included; `espalier/` alone holds 265.
  - A directory walk plus a stat of each file took 10.5 ms, the mean of 5 passes, warm, one run.
  - The 58-file figure above did not cover that set. Driver: a scratch script that imports `_hook_utils` and `_protected_zones` and walks each prefix; re-derive it.
  - The main checkout's `cc/` holds the blueprint chain and is larger. Prune the allowlisted subtrees in the walk, not after it.
  - 77 of the files are `.pyc` bytecode under `tools/cc/` and `espalier/` (`find tools/cc espalier -name '*.pyc' | wc -l`). Wave A-1 excludes them.
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
- **Read 2026-10-08, third session, from the same page:**
  - Writes by default: "The working directory, a per-user temp directory, and directories you've added". So a delete aimed at the home directory or the filesystem root fails at the OS level when the sandbox is on. A delete of the project itself, inside the working directory, does not.
  - "The sandbox is off by default." Wave B's coverage holds only where someone turned it on.
  - "The sandbox covers shell commands only. Claude's file tools, MCP servers, and hooks run outside it." So `Write` and `Edit` stay with `write_guard`'s path check.

**The earlier rejection to reread.** `docs/sharp-edges/chmod-444-decision.md` rejected OS-level protection against an *attacker* ("chmod 444 is itself bypassable ... friction (one extra command), not a guarantee"). `docs/STANDING_PRINCIPLES.md` §2 says the threat model is "operator/AI mistakes, not malice". Under that model, a check that fires on every spelling is better friction than a parser that catches some spellings.

**The named users (§16):**
- An adopter whose agent runs a formatter, a repo-wide edit or a checkout over the whole tree. It rewrites the vendored hooks, and no command text named them, so no parser could have seen it (measured above).
- An adopter whose agent, hurried or drifting, rewrites a hook script or `settings.json` through a shell spelling the parser does not read.

Either way the hooks can go quiet for the rest of the session, and nothing tells the operator until CI. On an adopter tree, `settings.json` is gitignored, so CI never sees it.

## Scope (in) — the waves

- **Task 0** (this pack's, before any wave): re-triage by job, manifest coverage, the Mac sandbox measurements, the Mac cost, and (0-E) what a mid-session settings edit does to the hooks.
- **Wave A-0 — the hook wiring is present, checked where settings change, every host.**
  - The settings-change hook, the SessionStart scan and `doctor` ask one positive question, beside the kill-switch shapes: is Espalier's hook wiring still present?
  - On ConfigChange a missing wiring is denied, so the change does not take effect. That prevents rather than tells, on native Windows too, and needs no parser.
  - It comes first: a few hours of work, and it covers the case 0-E may show wave A cannot. No live claim held its files on 2026-10-08. Two adopter-readiness packs will edit two of them later (Sub-task ordering, "Coordination").
- **Wave A — a spelling-independent after-check, every host.**
  - After every Bash and PowerShell call, compare the protected zones with the session's previous check, and report what changed, appeared or disappeared since then, whatever the command's spelling.
  - The comparison is against a per-session baseline, not the manifest (see "The manifest is also stale" above). So drift that was already there when the session started is never reported as this call's.
  - On a change, tell Claude through the advisory collector's `additionalContext`, tell the operator through `systemMessage` (the operator's decision, 2026-10-08), and write an audit row.
  - **Tell only, by the operator's decision (A2): nothing is restored.**
  - The zone set leaves out bytecode caches (`__pycache__`), which any Python run after a source edit rewrites inside the zones.
  - Because the baseline is per session and needs no manifest, the worktree gap (A-3) is closed for wave A by construction.
- **Wave B — the sandbox posture where the OS has one.**
  - `init` and `upgrade` offer `sandbox.filesystem.denyWrite` entries for the harness zones and the adopter's `protected_paths`, plus `denyRead` entries for the secret paths. The secret roster is derived from `tools/cc/hooks/write_guard.py::_SECRET_PATH_LABEL`, never copied.
  - `doctor` reports the sandbox state, the deny entries, and the user-scope `allowUnsandboxedCommands`.
  - Where the sandbox is on, its default write boundary also refuses deletes outside the project, such as the home directory and the filesystem root. That is the one catastrophic-delete case an OS layer reaches; the parser keeps the project root, and every case on native Windows. Because the sandbox is off by default, `doctor` saying "off" is the state that matters most.
- **Wave C — route the work.**
  - Guard rows whose job is location and which wave A (and B, where the host has it) covers are struck as covered, with the location layer's own test as the oracle. That test is spelling-independent by construction, so no census of spellings is needed.
  - The `hook-authoring` skill's "Test pattern" section learns that location jobs are proven at the location layer.
  - **Decision C3, the residual parser's coverage contract (owed; the operator's).** Some jobs must stay predictive: catastrophic deletes, speed bumps, and secret reads on native Windows. The contract says which spellings of those are work.
    - A row outside it is closed as a declared limit (`ledger_row.py strike` with the contract as its reason) rather than fixed.
    - This, not the location move, is what stops the chase on the jobs the location layer cannot take. It removes no guard: it decides which new rows are work.
    - Written beside `write_guard`'s documented limits ("What this does NOT catch", `docs/HOOKS.md` §4), and taught in the hook-authoring skill. Wave C-2 carries the draft.
  - The guard-lane brief gains a sibling-spelling step for the parser tiers that remain, **limited to forms inside the contract.** An unlimited sibling hunt is the patchwork this pack exists to end.
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
- **One reading of a command consumed by every parser tier.** The 2026-10-07 finding points to it for the residual jobs. It is consolidation, with that move's counter-warning, and it is worth building only if in-contract rows keep arriving once decision C3 holds. `TP-475`'s lineage measures that. Wave C-2 says when to raise it as its own pack.
- **Effect layers for the speed bumps** (a client-side push hook, or server rules on the remote). On this repository, branch protection probably already refuses a force push to `main` on the remote. Root `CLAUDE.md` Core Rule 10 says `main` requires a pull request, enforced on admins; that was read, not driven. So the residual parser's speed bumps mostly cover the other refs and adopters' remotes. C3's contract governs them until a speed-bump row shows a slip that got through.

## Task 0 — Verify (try to kill the redesign)

**0-A Re-triage the live guard rows by job.**
- Oracle: the live member rows of `task-packs/FORWARD_LEDGER.md` whose site cell names any of `tools/cc/hooks/_bash_patterns.py`, `tools/cc/hooks/write_guard.py`, `tools/cc/hooks/_speedbump.py`, `tools/cc/hooks/_protected_zones.py`, `bench/guard_metamorphic.py`, `bench/guard_row_probe.py`, `bench/powershell_guard_rehearsal.py`, or a `bench/*reachability*` script. Parse them with `tools/cc/generate_ledger_regions.py`.
- Classify each row by its **headline sentence only** into one of: zone, secret read, catastrophic delete outside the project, catastrophic delete of the project root (or where the row does not say), speed bump, false deny, instrument, other. The delete split was added 2026-10-08, before any row was read, because a sandbox reaches only the first.
- Pre-registered:
  - the reach of waves A and B is the zone rows, the secret-read rows, the outside-the-project delete rows (wave B, where the sandbox is on), and the false-deny rows whose cause is zone over-reading;
  - write the count and the ids into this pack's Reach table before any wave starts;
  - also count the rows left with the parser (both delete classes on native Windows, the project-root deletes, speed bumps). That count is the population decision C3's contract governs, and the operator decides C3 with it in hand.
- **Refuting result:** fewer than a quarter of the guard rows are location jobs. The ledger payoff is then small. Re-raise: wave A may still be worth it as robustness, and the operator decides.
- **Exit:** stop and re-raise.
- **Result, 2026-10-08 (one reader, a fresh agent, headline only and one row at a time; 44 live rows name a guard file): 14 of 44 (32%) are location jobs, so the refuting line as written does not fire. But only 9 of 44 (20%) are reachable by waves A and B, because this pack's own Reach table leaves the 5 zone-over-reading false denies NOT REACHED. Re-raised, not decided.**
  - By job: other 12; false deny 11, of which 5 were caused by zone over-reading; speed bump 5; zone 4; instrument 4; secret read 3; delete of the project root 3; delete outside the project 2. The ids are in the Reach table.
  - **The inconsistency for the operator.** The pre-registered reach above counts the zone-over-reading false denies. The Reach table says closing them means relaxing a parser guard, which wave D re-raises and the operator ruled out. Read by what this pack can reach, the share is under a quarter, so the refuting line's own words apply: "the ledger payoff is then small... wave A may still be worth it as robustness, and the operator decides". 0-E's result is that robustness case: the settings wiring has no other in-session layer.
  - Left with the parser (decision C3's population): 8, the 3 project-root deletes and the 5 speed bumps. Neither outside-the-project delete names native Windows. 8 headlines name a native Windows shell.
  - **Limits:** one reader, so there is no agreement measure; 12 rows read as "other", and a second reader may move some into a job; classes come from headlines alone, as pre-registered.
  - Driver: scratch scripts derive the population with `tools/cc/generate_ledger_regions.py` and give the reader the ids only; the reader runs a one-headline printer per id.

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

**Result, 2026-10-09 (the Mac, air's mail `20261009T222904Z-air-603acc`): the refuting result is refuted, so wave B stands.**

- **Setup:** Claude Code 2.1.274 on macOS 26.6.2 (Seatbelt), headless `-p` on claude-haiku-4-5 under `bypassPermissions`, one tool call per run, read from the stream-json tool payloads. A throwaway repo whose project `.claude/settings.json` sets `sandbox.enabled true` and `sandbox.filesystem.denyWrite [<abs>/denied]`. The strict arm adds `--settings {sandbox.allowUnsandboxedCommands:false}`, which the docs give user-scope precedence over a project `true`.
- **Control:** a write outside `denied/` succeeds, so the sandbox is on and is not blanket.
- **Bash** `printf > denied/bash.txt`: refused, exit 1, `operation not permitted`.
- **The PowerShell tool** (pwsh 7.6.5, `CLAUDE_CODE_USE_POWERSHELL_TOOL=1` at launch) `Set-Content`: refused, exit 1, `Access to the path ... is denied`.
- **`git checkout -- denied/kept.txt`** on a file dirtied outside the sandbox: `unable to unlink old`, rc 255, and the file stays dirty. So an agent inside the sandbox cannot run `espalier upgrade` over a denied path.
- **Default `allowUnsandboxedCommands` under `bypassPermissions`:** the first Bash write is refused. Claude then re-runs the same command with `dangerouslyDisableSandbox: true`, with no prompt, and the file is created.
- **Strict:** no `dangerouslyDisableSandbox` attempt, and the setting holds. But Claude reached for the `Write` tool and created the file under `denied/`. The sandbox covers shell commands only, so `denyWrite` is a shell boundary, not a write boundary. Under `bypassPermissions`, only a PreToolUse hook such as `write_guard` stands between `Write`/`Edit` and a denied path. This is the file-tool hole predicted by the quote above ("Claude's file tools, MCP servers, and hooks run outside it"), now driven.
- The raw streams sit in air's scratchpad only.

**0-D The Mac's cost** of wave A's per-call check, beside this box's 6.1 ms.

**Result, 2026-10-09 (the Mac, air's mail `20261009T222508Z-air-e11a7e`):** macOS 26.6.2, Python 3.14.7, APFS, load 1.6, measuring the after-check on a Bash call that changed nothing. Each call ran in a fresh process; n=25; 287 watched files.

| Part | Median | p10 | p90 |
|---|---|---|---|
| import + call | 15.0 ms | 14.6 | 15.4 |
| import alone | 10.4 ms | 10.1 | 10.7 |
| call alone | 4.6 ms | 4.5 | 4.8 |

That is under the 25 ms line, beside this box's 17.1 ms. APFS `mtime_ns` has nanosecond resolution: six writes 450 us apart were all distinct, so there is no coarse-clock risk there.

**0-E A settings edit mid-session, driven (new 2026-10-08; any host; before waves A-0 and A).**
- **Setup:** a throwaway repo with `espalier init`, so its `.claude/settings.json` wires the hooks.
- **Driver:** a nested headless session (`claude -p`, with `CLAUDE_*` stripped from the child's environment, one tool call per message).
  - Launch it with `ESPALIER_MAINTENANCE_MODE=1`, so `write_guard`'s zone check lets the deliberate edit through. Maintenance mode bypasses neither `config_guard` nor `post_write_check` (root `CLAUDE.md`, "Maintenance mode"), the two hooks under test.
  - The edit is a short Python rewrite of the JSON, never a spelling chosen to get past the parser.
  - It runs three Bash calls:
  1. a harmless call;
  2. a call that rewrites `.claude/settings.json` without its `hooks` key;
  3. a harmless call.
- **Repeat** with a call that deletes the file instead.
- **Read back** from the throwaway tree's audit log and the hooks' state files only, never from the session's own account of itself:
  - (i) did ConfigChange fire, with a `config_guard` record?
  - (ii) did `post_write_check` run after call 2, and after call 3?
  - (iii) on the deleted file, did ConfigChange fire?
  - (iv) with A-0's fix shape on a scratch copy of the hooks, did a ConfigChange deny keep the hooks running for call 3?
- Record the Claude Code version.
- **Refuting results:**
  - **for A-0 as a preventer:** (i) is no, so ConfigChange does not fire for a tool's edit. A-0 then reduces to the SessionStart and `doctor` report, and the settings case rests on wave A.
  - **for wave A's settings test** (earn-the-red 3 below): (ii) is no after call 2. Then the after-check is removed with the wiring it would report, and earn-the-red 3 tests a path the deployment never takes. Strike that claim from wave A; A-0 owns settings.
  - Both no: the settings case has no in-session layer. Re-raise.
- **Result, 2026-10-08 (Windows 11, Claude Code 2.1.294, headless `claude -p` on the smallest model): ConfigChange fires for a tool's edit and a deletion alike; the edit removes every hook at once; A-0's deny keeps them, for both edits, every run. The A-0 preventer stands; wave A's settings test is struck (A-0 owns settings).**
  - **Setup:** a throwaway repo per run with `espalier init --profile workflow`; one tracer line added at the top of `main()` in the throwaway repo's own copies of `post_write_check.py` and `config_guard.py`, appending the hook name and payload fields to a file outside `.claude/`. A tracer was needed: today's `config_guard` writes no audit record for either edit (it reads both as clean, the premise above), and `post_write_check` records nothing for a harmless call. The edits were plain Python scripts (rewrite the JSON without `hooks`; remove the file), each sleeping 6 s after the edit, run as call 2 of three Bash calls, one per message, with `ESPALIER_MAINTENANCE_MODE=1` and every `CLAUDE_*`/`ESPALIER_*` variable of the launching session removed.
  - **A-0's fix shape, on the scratch copy:** at the top of `config_guard._run_main`, a `project_settings`/`local_settings` change to `.claude/settings.json` that leaves the file without a `hooks` key, or removes it, exits 2.
  - **Results** (read from the tracer and from Claude Code's transcript; never from the session's own account):

    | edit | A-0 deny | runs | ConfigChange fired | `post_write_check` after call 2 and 3 | Stop hook at session end |
    |---|---|---|---|---|---|
    | `hooks` key removed | no | 3 | 3/3 | 0/3 | 0/3 |
    | file deleted | no | 3 | 3/3 | 0/3 | 0/3 |
    | `hooks` key removed | yes | 4 | 4/4 | 4/4 | 4/4 |
    | file deleted | yes | 3 | 3/3 | 3/3 | 3/3 |

    Transcripts confirm all three calls ran in every run. ConfigChange fired 2 to 3 s after the edit, inside call 2's sleep, so the removal took effect before call 2's own PostToolUse.
  - **Answers:** (i) yes, for both edits, though with no `config_guard` record today; (ii) no after call 2 and no after call 3; (iii) yes; (iv) yes for both edits.
  - **Refutations:** A-0 as a preventer is not refuted. The wave-A settings refutation fires: the after-check is removed with the wiring it would report, so earn-the-red 3 is struck from wave A and A-0 owns the settings case. "Both no" does not hold.
  - **Conditions not measured:** an interactive session (the headless child ran in an untrusted workspace: Claude Code ignored the settings file's `permissions.allow` entries and loaded its hooks); macOS; `settings.local.json`; a user-scope settings edit.
  - **A process note:** a first batch mislabelled three runs as A-0 runs that carried no deny (the setup applied the shape to one directory name only), which briefly read as "the deny fails for a deletion" and as a race. Each throwaway repo's `config_guard.py` was then checked for the deny before its run counted; the table above counts only checked runs.

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

### Wave A-0 The hook wiring is present, checked where settings change *(fix shape, untested; new 2026-10-08; 0-E decides how much of it prevents)*

**The predicate already exists; derive from it, never author a new one** (`memory/derive-a-guard-from-its-calibrated-sibling.md`). Read 2026-10-08:
- `tools/cc/ci_guard.py::_scan_settings_for_missing_governance_events` is the stdlib-only positive check: every deployed gate must be wired, by event, script and matcher. It reads each hook through `::_ci_hook_executes_script_path`, an exec-form extractor mirrored from `espalier/surface_contract.py::_hook_executes_script_path`, never a substring match.
  - It fails closed on a malformed file, or one with no `hooks` key, by flagging every deployed gate. Its comment says this mirrors `doctor`.
  - It runs only in CI. On an adopter tree `settings.json` is gitignored, so CI never sees the live file.
- `espalier/cli.py::_settings_has_espalier_hooks` is **not** the oracle. Its docstring says it answers only "is any Espalier hook present" for the upgrade path, and "must never be used as the basis of an enforcement claim".
- A-0 calls the `ci_guard` check from the hook layer, or moves it into a module both `ci_guard` and the hooks import. It is never copied. Which of the two is the lane's design decision, made by reading `ci_guard`'s callers and its tests.
  - **Amended at landing (2026-10-08): both options were refuted, so it is a pinned twin.** A fresh `init` tree holds no `ci_guard.py` (only `install-ci` deploys it; measured), so a hook cannot call it; and `ci_guard` imports no sibling by contract, so it cannot import a shared module. The repo's idiom for exactly this split is the one the kill-switch scan already uses: `tools/cc/hooks/_integrity.py::unwired_governance_gates` is the hook layer's twin, its messages byte-equal to `ci_guard`'s and its roster equal to the engine SoT, pinned three ways by `tests/test_ci_guard.py::TestHookSideWiringTwin`. Derived and checked, not authored fresh, which is what the rule protects.
- The one case it leaves out on purpose: a file that is absent ("Truly-absent → init/presence owns it"). A-0 adds that case for a mid-session deletion on an Espalier tree, meaning one where `tools/cc/hooks/` is present.
- **Refuted if** the check flags a settings file that `init` wrote on this host and nobody has edited (a false finding on the canonical wiring, such as an interpreter word it does not read). Drive it on a fresh `init` tree per host before wiring it into a deny.

**Where it fires:**
1. `tools/cc/hooks/config_guard.py::_scan_payload`, on a change to the **project** file `.claude/settings.json` only:
   - a change that leaves a deployed gate unwired is denied, on the existing deny path, naming the gates;
   - a deleted project settings file on an Espalier tree is judged as an empty one, not skipped.
   - **Not the local file.** `ci_guard`'s check scopes itself to the project file ("Only the project file -- settings.local is a gitignored local override, not the shipped governance contract", `tools/cc/ci_guard.py::scan_missing_governance_events`). A local file normally carries no `hooks` key at all, so judging it alone would deny nearly every local edit. A local-file change keeps today's kill-switch shapes only.
2. `tools/cc/hooks/session_start.py::_report_integrity_state` reports the same finding at the next start: the after-the-fact catch, for an edit made while no session ran.
3. `espalier doctor` reports it through its existing kill-switch line.

**The legitimate edits it must not refuse:**
- the operator reordering hooks, or adding their own, so the harness's commands stay present;
- `espalier upgrade` rewriting the file, run from a terminal, outside any session, where ConfigChange does not fire;
- `espalier uninstall`, which runs from a terminal too.

A session that means to unwire the hooks has the same route as a kill switch today: the operator edits from outside the session.

**Refuted if:**
- 0-E (i) is no. Then ConfigChange never sees a tool's edit, and A-0 is a report at SessionStart and in `doctor` only. Say so in this pack, and keep it: a report the next session reads still beats today's silence.
- A deny on ConfigChange leaves the on-disk file changed but the session's hooks intact (0-E (iv)). Then the operator still has to restore the file, and the deny reason names how:
  - `git checkout` cannot restore a gitignored file;
  - `espalier merge-settings` tops up a missing event, and `--repair` rewrites the harness's own dead entries (`espalier/cli.py::repair_hook_wiring_in_settings`);
  - for a deleted file, `init` deploys one when none exists (probable, not driven).

  Re-raise whether that is enough.

**Earn the red:**
1. A `config_guard` payload for a settings file with its `hooks` key removed is denied, naming the gates left unwired. Mutation: keep only the kill-switch shapes, today's predicate.
2. The same with the file deleted, on an Espalier tree. Mutation: skip a missing file, today's behaviour.
3. A settings file wired with an interpreter word other than the fixture's default passes. Use the Windows launcher form, `py` with one version flag, which `::_ci_hook_executes_script_path` consumes. A fresh `init` file on this host passes too. Mutation: match each hook against one hardcoded interpreter word instead of the exec-form extractor. The fixture must use the non-default word, or the mutation stays green.
4. A settings file with the harness's commands plus an adopter's own extra hook passes. Mutation: require an exact list.
5. A settings file whose gate entries only mention the hook path (an `echo` naming the script) is denied. Mutation: a substring match, which is the false green `_settings_has_espalier_hooks`'s docstring records.
6. A change to `.claude/settings.local.json` that carries no `hooks` key is not denied. Mutation: apply the wiring check to every settings file, not the project file only.

**Result, 2026-10-08 (lane/a0-hook-wiring-present; Windows 11, Claude Code 2.1.294-2.1.295, headless `claude -p` on the smallest model, the 0-E driver with a tracer in the throwaway tree's own hooks; read back from the tracer, the run's audit directory and the session transcript only).**
- **Built:** the six rows above, each seen red against its mutation and green after (re-seen after the review batch re-anchored them). `doctor` needed no change: on a fresh `init` tree it already fails a hooks-less file ("4 governance gates not effectively wired") and a deleted one ("missing required managed surface"), and passes the untouched file.
- **Design changes the review drove (both reviewers; REQUEST CHANGES, no blocker):**
  - *The change, not the state.* Judging the file refused every project-settings edit on a tree already missing a gate, or wired in the shell form `upgrade`'s plain merge leaves in place. SessionStart now records the gates the session runs (`.espalier-state/wired_gates.json`; rewritten where a process loads the file, kept across clear and compact), `config_guard` refuses only a change that loses one of them, and rewrites the record when it lets a change through. No record judges the state (fail-closed).
  - *The refusal is told.* It reaches no one by protocol and the file keeps the change, so the next session would start hookless. `config_guard` notes it (`.espalier-state/settings_unwired_pending.json`); `post_write_check` tells Claude once, beside the next tool result, with the restore (`merge-settings --repair`; `init .` for a deleted file, driven: `--repair` refuses a missing file, `init .` redeploys it wired and `doctor` passes).
  - *Its own record and reason:* `configchange_blocked_unwired` (in `DENIAL_EVENT_TYPES` and the HOOKS.md table), `_denial_reasons.GOVERNANCE_GATES_UNWIRED`.
  - *DEF-1060 kept working:* `espalier clean-generated` records its unwire first (`.espalier-state/settings_write_intent.json`, a canonical-JSON digest, one rostered writer, 600 s); written where a session may be watching (a live run, or a state directory present), so an uninstall on a sessionless tree still leaves no state directory.
  - *Read by location:* the project file is judged when the payload's path sits at `.claude/settings.json` (a symlink out of the repo included) or, with no path, when the source is `project_settings`.
- **Live results:**

  | edit | config_guard | runs | refused | hooks after the edit | note in Claude's context |
  |---|---|---|---|---|---|
  | `hooks` key removed | A-0 | 7 | 7 | kept 7/7 | 3/3 (measured on the batch's runs) |
  | file deleted | A-0 | 6 | 6 | kept 6/6 | 3/3 |
  | file emptied | A-0 | 1 | 1 | kept | -- |
  | syntax-broken file | A-0 | 2 | 2 | kept 2/2 | -- |
  | removed / deleted / emptied / syntax-broken | today's (`main`) | 1 each | 0 | **dropped** each time | -- |
  | permissions edit, tree already missing plan_guard | A-0 | 1 | 0 (let through) | kept | -- |
  | `http` hook added | A-0 | 1 | 0 (let through) | kept | -- |
  | in-session uninstall, run 1 then run 2 | A-0 | 3 | 0 (recorded) | dropped by design; run 2 deletes; call 3 runs | -- |
  | the same, record ignored | control | 1 | 1 | kept, then **call 3 refused: "can't open file"** | -- |

  "Note in context" is read from the session's own transcript on disk (a `hook_additional_context` attachment on PostToolUse); the stream-json output does not echo PostToolUse hook output.
- **Not measured:** an interactive session; macOS; a user-scope settings change; whether an accepted change to another settings file reloads the refused project file (the review's open question).
- **Filed:** `DEF-1195` (the shared voiding rule predates the `http` and `mcp_tool` hook types; the live readers set them aside meanwhile).

### Wave A-1 Compare the zones after every shell call with the session's previous check *(**DECIDED 2026-10-08: build it**, after A-0, firing only on unaccounted changes (the decision below the flow); fix shape, untested; replaces the first draft's manifest check, which the stale manifest refuted)*

**The first draft and why it was replaced.** The first draft called `_integrity.verify_integrity(root)` after every shell call. On the main checkout on 2026-10-07 that function reported 4 drifted files that no call had touched, so the check would have spoken on every shell call (Motivation, "The manifest is also stale"). It also needed a manifest that a linked worktree does not have.

**The zone set.** Derive it, never copy it:
- `_hook_utils.harness_protected_prefixes(root)`, the operative prefix list (it adds `espalier/` on self-host only);
- `_protected_zones.PROTECTED_FILES`;
- the adopter's `protected_paths` (`_hook_utils.adopter_protected_prefixes`).

Leave out the paths the harness's own hooks rewrite on their own schedule, through the existing predicate `post_write_check.py::_is_allowlisted` (the blueprint chain, `cc/execution_plan.json` and the rest of that allowlist) plus `_protected_zones.ALLOWED_IN_PROTECTED` and `::ALLOWED_PREFIXES_IN_PROTECTED` (the zone files agents legitimately rewrite, such as `cc/GOAL.md` and `cc/_working_summary.md`). Otherwise the check reports the harness to itself.

Also leave out bytecode caches: every `__pycache__` directory, pruned during the walk.
- The interpreter rewrites a module's `.pyc` under the zone the first time any process imports it after a source edit. Usually that is the next hook process, right after an `Edit` that wave A-1 step 3 has just refreshed.
- Measured 2026-10-08: no existing allowlist names them, and this worktree holds 77 under `tools/cc/` and `espalier/`.
- A `.pyc` change is never the harness being edited; its source file is what the check watches.

Prune the allowlisted subtrees during the walk too, rather than filtering after it. The walk's cost is set by what it enters (Motivation, the restated cost).

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
   - **the same report to the operator, as `systemMessage`** in the one JSON object `_hook_utils.emit_advisories` prints (the operator's decision, 2026-10-08). That function emits `additionalContext` only today; this adds an operator line beside it. Other hooks keep their output unchanged unless they opt in.
     - Once per path per session, so a lane that syncs its own hook edits is not told on every sync.
     - The wording follows step 5: it says the zone changed, never that the command wrote it.
   - one audit row (`post_shell_zone_change`, counted by `/status --log`);
   - when a settings file is among them, also run `_integrity.scan_for_kill_switches(root, include_unreadable=True)` and say whether the hook wiring is still present. A missing `hooks` key and a deleted settings file are named in their own words, because the kill-switch scan reads both as nothing (Motivation).
5. **The wording never claims the command wrote the file.** It says the zone changed since the previous check, which is this call, a parallel call, or another session in the same tree (the SessionStart `Sessions:` line names those).
6. **No baseline found** (a session that predates the change, a state directory that cannot be written): take one silently, check nothing for that call, and say once, by `say_once`, that the first call was unchecked.

**Superseded 2026-10-08 by the operator's decision below:** *"Legitimate rewrites through a shell call are reported, by design... Under tell-only that costs Claude one line."* A guard whose right answer is sometimes "ignore it" teaches that answer.

**DECIDED 2026-10-08 (the operator): build A-1, and it fires only on a change no legitimate path accounts for.** In the operator's words: "We dont want to set any precedent of 'the guard fires, and the right move is for the agent to ignore it' We want the guard to be selective enough to be a really big signal." So when it fires, the only right response is to stop and surface it to the operator. The fix shape, untested: a changed zone path is **accounted for**, and silent, when any of these holds, checked in this order and only when the stat diff is non-empty, so the no-change path stays a stat pass:
1. **It was judged before it ran:** a write tool's path, refreshed by flow step 3.
2. **Git explains it:** the file's new content equals its blob at the current `HEAD`, or the path is absent at `HEAD` and on disk alike. This covers a pull, merge, checkout or the session catch-up: committed history that branch protection and CI judge before it merges. Store `HEAD` in the baseline so the report can say which move it was. A commit made without touching the working tree (git plumbing), then checked out, is a declared limit under decision C3's reasoning: a slip does not produce it.
3. **The mirror registry explains it:** the path is a byte-mirror row's mirror (`espalier/mirror_registry.py`), and its content now equals its source of truth. This covers the self-host syncs into `espalier/_vendor/` and `espalier/assets/`.
4. **A harness writer recorded it:** the writers that legitimately rewrite a zone through a shell call update the baseline for the paths they wrote, as part of their own run. Those writers are `espalier integrity refresh`, `espalier upgrade`, `espalier init` and the catch-up. This is question 3's closed input: we own the producer, so the producer says what it wrote.
- **What fires:** a zone path whose content none of the four accounts for. That is a hook, setting, workflow or manifest that now holds content nobody committed, generated or judged. Under maintenance mode it still fires; it is the only zone signal then.
- **Its pre-registered refutation tightens accordingly**, replacing the one-in-ten line below: in an ordinary lane on this tree (vendor and doc syncs, a merge of `main`, a `git switch`), **any** report that is not a real unaccounted change is a design defect. Fix it by adding the missing accounting path, never by a threshold and never by telling the agent the report can be ignored.
- **Earn the red adds:** a zone file brought to its `HEAD` blob by a checkout is silent (mutation: drop path 2); a mirror synced to its source is silent (mutation: drop path 3); a zone file rewritten through a shell call to content no path accounts for reports (mutation: treat any `HEAD` move as accounting for every path).

**Maintenance mode (A3).** `post_write_check` is not bypassed by maintenance mode (root `CLAUDE.md`). Under it, `write_guard`'s zone check is off, so this check is the only zone signal; it stays on, and self-host sessions run under maintenance mode routinely (this session's own launch had it set). The lane decides the wording under maintenance mode. The proposed default is once per path per session, so a hook-editing lane is told once that its own files moved, not after every sync.

**Refuted if:**
- the added latency of a call that changed nothing exceeds 25 ms median on either host. Measure on both: this box and the Mac (0-D).
- ~~in one ordinary lane on this tree, under maintenance mode, more than one shell call in ten reports a change.~~ Superseded 2026-10-08 by the stricter line in the decision above: in an ordinary lane, any report that is not a real unaccounted change is a defect in the accounting paths. **Pre-registered before the lane runs.** Never raise the threshold.
- an ordinary `espalier upgrade` through Bash in a scratch adopter tree produces a report that the wording above would mislead Claude about. One drive decides it.

**Earn the red.** Each test names the mutation it must die to:
1. **Spelling independence.** In a temp repo, take a baseline, change a zone file outside the hook, then run `post_write_check` on a Bash payload whose command text names nothing in any zone. It must report. Red against the current `_check`, which returns at the `_is_write_tool` gate. Mutation: delete the shell branch.
2. **Drift already present is silent.** In a temp repo whose manifest already mismatches a zone file, take a baseline, then run on a Bash payload with no change in between. It must not report. Mutation: compare against `verify_integrity` instead of the baseline (the first draft's design), which must turn this red.
3. **A settings file without its hooks.** Rewrite `.claude/settings.json` without its `hooks` key between baseline and payload. It must report and name the missing wiring. Mutation: judge settings only by `scan_for_kill_switches`.
   - **Conditional on 0-E (ii).** If the hook does not run after the call that removed the wiring, this test proves a path the deployment never takes. Drop it from wave A's claims, and leave settings to A-0.
4. **A write tool refreshes, not reports.** An `Edit` payload for a zone file, then a no-op Bash payload. It must not report. Mutation: drop the refresh in step 3 of the flow.
5. **The harness's own writes are silent.** A blueprint file written under the blueprint directory between baseline and payload must not be reported. Mutation: drop the allowlist exclusion.
6. **The operator is told.** On a reported change, the hook's stdout JSON carries `systemMessage` naming the zone path; a second identical change in the same session does not repeat it. Mutation: drop the operator line, or drop its once-per-path throttle.
7. **Bytecode is silent.** A `.pyc` rewritten under a zone's `__pycache__` between baseline and payload is not reported. Mutation: drop the cache prune.
The measured named-user case, a whole-tree formatter, is test 1's shape: its command text names nothing in any zone. Write test 1's payload as that formatter rather than a separate test, since no mutation would separate the two.

**Amended at landing (2026-10-09, lane/a1-zone-after-check; the operator confirmed the first three before the lane and approved the plan carrying the fourth):**
- **Path 3 is a hook-side table pinned to the registry.** A hook imports nothing from `espalier/`, so `tools/cc/hooks/_zone_watch.py::MIRROR_PAIRS` copies the six byte and normalized rows whose mirror is watched, and `tests/test_zone_watch.py::TestTheMirrorTableIsTheRegistrys` holds it equal to `espalier/mirror_registry.py` both ways (the `_reinject.py` idiom). The one watched row that transforms its source (`selfcheck-tests`) is accounted by path 4 instead.
- **Path 4 is a record per writer, never a write into a session's baseline** (Core Rule 14). `espalier/zone_writes.py::recorded` brackets a run (a stat pass before and after) and records what moved during it, with the new content's digest and the time, under `.espalier-state/zone_writes/<writer>.json`. `espalier.cli.main` brackets every command that takes `args.repo`, as `espalier <command>`; that covers `freshness-pin` and `unpin`, which the first list missed. `scripts/sync_selfcheck_tests.py` brackets itself. An entry counts only when its run ended after the session's previous check, and only for content equal to what it recorded. Nothing is recorded on a tree where no session keeps a baseline.
- **The pass criteria are restated** below: the noise line is the decision's, and the earn-the-red list grew with the design.
- **`cc/` is not watched** (the plan's open choice, recommended and approved). Measured 2026-10-09 on this tree: after the pack's exclusions, everything left under `cc/` was harness state written through shell calls (six of six: the plan archive in `cc/_cold/`, the plan's `.lock`, the speed-bump log and the finding ledger). Watching it would have reported every `execution_plan.py create`. `write_guard` still guards `cc/` by path. With `cc/` gone, every existing exclusion fell away (all of them point into `cc/`), and the only prune left is `__pycache__`.
- **Path 2's removal rule was tightened** (and corrected in the review round below). "Absent at `HEAD` and on disk alike" would have accounted for a deleted untracked or ignored zone file. A removal is now git's only when the path is absent at `HEAD` and was present at the HEAD of the previous check, which the baseline stores (read from the git dir's own files, no spawn). The first cut asked for `HEAD@{1}`, which a one-entry reflog cannot answer (the whole batch fails) and which names only the last of several moves.
- **Path 1 widened to the shapes it must cover.** It now keeps the last eight contents a file tool wrote per path, so a stash and its pop read as judged, and it reads the judged writes of live sibling sessions in the same checkout.
- **Order and dropped items.** The paths run cheapest first (1, 3, 4, then git, the one spawn); since accounting is an OR, the order changes only cost. Two things were dropped: the settings wiring scan (0-E struck it; A-0 owns settings) and `HEAD` in the baseline (nothing reads it once git explains a change).
- **A call that changed nothing peeks without the lock.** Only a call that sees something move takes the lock, then reads and compares again, so parallel calls still report a change once.

**Review round (2026-10-09; both reviewers REQUEST CHANGES: code-reviewer 2 BLOCK, 4 WARN, 9 NIT; failure-mode-reviewer 5 BLOCK, 8 WARN, 5 NIT; one fix batch).**

Accepted and built:
- **Git.**
  - The baseline stores the HEAD of each check, and removals are judged against it. That fixes the one-entry-reflog batch failure (reproduced: `fatal: log for 'HEAD' only has 1 entries`, exit 128), a rebase or `pull --rebase` dropping a file, and a catch-up followed by `git switch -c`.
  - The SessionStart baseline is now taken after the catch-up.
  - While a merge, rebase, cherry-pick, revert, sequencer or bisect is half done, nothing is judged and the baseline is held. The marker names are a twin of `tools/cc/checkout_sync.py::_MID_OPERATION`, pinned.
- **Settings files.** `.claude/settings.json` and `.claude/settings.local.json` left A-1's watched set. Claude Code writes the local file itself on a "don't ask again" answer, and `config_guard` sees every settings change.
- **Mirrors.** Path 3 runs on the harness's own source tree only. On an adopter, a deleted `harness-guard.yml` had read as a pruned mirror (verified silent).
- **The walk.** It now prunes the stack table's dependency directories, cache and tool directories and the adopter's `dependency_dirs`. It skips editor and OS clutter, identifies a file of 4 MiB or more by its stat, and turns the check off for the session past 20,000 files or 3 s, said once. The seeded example `protected_paths = ["data/", "models/"]` was the case.
- **Path 4.**
  - Only the nine commands that rewrite protected files are bracketed (`zone_writer=True` on their parsers), so a read-only command's run cannot file a parallel slip as its own.
  - A running marker holds a watching session's check until the run ends; a marker older than 600 s holds nothing.
  - The recorder includes the adopter's `protected_paths`.
- **The session's memory and the operator line.**
  - A compaction keeps the baseline.
  - The operator line is keyed by path and content.
  - Content any path accounted for, or the check reported, is remembered per path (the last eight), and so is a session's own new file stashed away.
  - The unchecked and off notices reach Claude once a session, keyed by session.
  - A change to the watched set compares only what both sets watch.
- **Wording and hardening.**
  - Subagents are asked to pass the report on.
  - A finding survives a baseline that cannot be replaced.
  - A deploy without the helper says so once.
  - The operator lines are passed only when present.
  - A call that changed nothing peeks without the lock.

Decided by the operator (2026-10-09):
- **A change made before the shell call began goes to the operator's line only** ("Split by call window"). The call start is `duration_ms` before the hook ran. PostToolUse carries `duration_ms` and `tool_use_id` (driven: one headless call, both fields present on Claude Code 2.1.295), so `write_guard` was not touched. A change during the call, or with no duration, is Claude's, and Claude is asked to stop.
- **A bad edit committed in the same shell call is silent**, a declared limit ("Document as a limit"). It is in `docs/HOOKS.md` and filed as `DEF-1197`, whose probe prints `silent` while it stands.

Measured rather than built:
- The Edit-and-Bash race. One Edit to a watched file and one Bash call issued in the same message produced no report: here they ran one after the other (n=1).
- A sibling session or a background agent can still interleave. Each has its own PostToolUse before its changes are judged here, so the window is the hook's start-up.

Declined:
- An in-flight record written by `write_guard`. The call-window split made it unnecessary for one session, and `write_guard` is the riskiest file to touch for it.

**Result, 2026-10-09 (Windows 11, Claude Code 2.1.295; lane/a1-zone-after-check).**
- **Earn the red:** every A-1 test was seen red against its named mutation, then green. That is 36 mutations before the review and 24 for its batch, each re-runnable from the lane's mutation specs. The batch's are named in the review-round block above; the first 36 are:
  - the pack's tests 1, 2, 4, 5, 6 and 7;
  - the decision's three (a checkout to `HEAD` is silent; a synced mirror is silent; unaccounted content beside a `HEAD` move reports);
  - the design's additions: the previous-`HEAD` removal rule, a git failure reporting and saying why, a stash and its pop, a sibling's judged write, path 4's six rows (the writer's own run, the since-the-previous-check condition, the roster, the record name, a slip before the writer, no state on a sessionless tree), the CLI bracket, the census both ways, report-once under the lock, the no-change path taking no lock, the SessionStart job, the unchecked first call and the cache prune.
- **Latency of a call that changed nothing** (this box, 285 watched files, fresh processes so the lazy import is paid): median 17.1 ms (p10 16.0, p90 19.4, n=25) after the review batch, under the 25 ms line. It was 15.5 ms before the batch added the HEAD read and the prune names, and 20.8 ms before the unlocked peek (the lock's first use costs about 5 ms on Windows). The Mac's median is 15.0 ms (0-D, n=25, 287 files).
- **Live drive** (a throwaway `init --profile workflow` tree with `tools/cc/` untracked so git could account for nothing; a headless `claude -p` session on the smallest model, maintenance mode on, one tool call per message; read back from the tree's audit log, its state files and the transcript; n=2, once before the review batch and once after, the same result both times; after the batch the report read "during Claude's last shell call", the writer's running marker was gone after its run, and the baseline held HEAD):
  - `python scratch_format.py`, which rewrote a hook without naming it, produced exactly one `post_shell_zone_change` naming `tools/cc/hooks/_recall.py`;
  - `python -m espalier upgrade --execute .` restored it, and its record (`espalier-upgrade.json`: the hook and `.espalier/integrity.json`) kept the next check silent;
  - a subagent's Edit refreshed the MAIN session's baseline, so its PostToolUse payload carries the parent session id, and the following `git status` was silent;
  - the transcript carries the operator line as a `hook_system_message` attachment beside the `hook_additional_context`. That is the transcript's rendering; an interactive terminal's rendering is not yet seen.
- **Noise, measured on this lane's own session** (the hook went live mid-lane; its baseline was taken at the first shell call after the after-check landed). There was one report, and it is real: a hook edited through a Bash-run Python script rather than the Edit tool, surfaced to the operator, who said go on. No other report followed, across five vendor syncs, two asset-doc syncs, four mutation batches, every Edit-tool change and the drive. The plan's own merge of `main` and branch switch are still to come; the ship step adds them.
- **Not measured:** an interactive session; macOS (0-D's latency, and the coarse-clock limit); a second session in the same checkout live (the sibling rule is unit-tested only); a parallel Edit and Bash in one message (their PostToolUse order).
- **Open, to file once the Air's ledger claim is released (found 2026-10-09 at the CI fix; unfiled):** a nested checkout under a protected path (a clone, submodule or worktree under an adopter's `protected_paths`) is walked like the rest of the zone, and the outer `HEAD` cannot account for its own git's moves, so a checkout or pull inside it reports. Both walks enter it alike today, pinned by `tests/test_zone_writes.py::TestTheTwinsAgree::test_both_walks_enter_a_nested_checkout_alike`; the recorder's walk carries the `nested-repo-ok` pragma saying so. A prune was built and withdrawn in the same lane. Its two reviews found, in scratch trees:
  - planting a `.git` under `tools/cc/hooks/` reports once, then leaves that directory unwatched for every later session;
  - a watched directory that becomes a checkout (or stops being one) reports its files as removed (or added) while they sit on disk;
  - a protected top that is itself a checkout still reports its own git's moves, which a prune below the top cannot help.

  Two designs for the row's Task 0: (a) a prune below adopter prefixes only, with the pruned checkouts stored in the baseline so a directory entering or leaving the set restricts the comparison; (b) an accounting path that asks the nested checkout's own git for the blob at its `HEAD`, which needs no prune. No adopter has reported the case (§16: named, not seen).

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

### Wave B-1 The sandbox posture *(fix shape, untested; 0-C done 2026-10-09: `denyWrite` takes effect for shell writes and `git checkout`, and not for the file tools)*

- 0-C's strict arm shows `Write` creating a file under a `denyWrite` path, so the sandbox posture is a shell layer beside `write_guard`, never a replacement for its path check on `Write`, `Edit` and `NotebookEdit`. `doctor`'s advice says so in one line.

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

### Wave C-2 Decision C3: the residual parser's coverage contract *(**DECIDED 2026-10-08: the operator accepted the draft below as written**, after it was applied to the 13 residual rows; wave C writes it into `docs/HOOKS.md` §4, the hook-authoring skill and the guard-lane brief, and strikes `DEF-1173` with the contract as its reason)*

**Why it is needed.** Waves A and B take the location jobs. Three jobs cannot move:
- catastrophic deletes of the project root, and every catastrophic delete on native Windows (an after-check cannot undo a delete);
- speed bumps (an action on a remote);
- secret reads on native Windows (a read leaves nothing to compare).

For these the parser stays, and so does the open space of spellings. Nothing in waves A to C stops the next spelling row on those jobs from being filed and fixed, so the chase continues there unless something decides which spellings are work. `TP-475`'s question 4 ("would a slip plausibly produce this?") asked once for the whole job, instead of once per row, is that decision.

**What the contract states,** per residual job: the forms that are work; the forms that are declared limits; and what happens to a row outside.

**A draft, for the operator to accept, amend or reject:**
- **In the contract:**
  - a program named directly, in the shell's ordinary syntax, with operands written literally, quoted or not. That includes roots whose names hold shell metacharacters: a project named like `R&D` is a real root, not a trick.
  - one level of a literal launch wrapper: a program text handed to another shell as a literal string. Agents use that form in ordinary work (probable, not measured).
- **Declared limits,** extending `write_guard`'s documented limits list to the residual jobs by name:
  - operands computed at run time (a variable, a command substitution, a glob that expands onto the target);
  - a program assembled from pieces;
  - an encoded program;
  - a second level of wrapping.
- **A new row is work** when its form is in the contract, or when it records a slip seen in a real session (a transcript or an audit row names it). Otherwise it is recorded straight to the declared limits, with the contract as its reason, through `ledger_row.py`.
- **The live rows,** classed by 0-A, get one re-triage. A row outside the contract is struck with the contract as its reason. It is not fixed, and no guard changes.

**Refuted if (the draft, not the idea):**
- more than half the live residual rows fall outside it. Then the draft is too narrow to be the slip model: re-raise with the rows.
- none fall outside it. Then it changes nothing for today's rows. It still governs new filings, which is its point, but say so plainly rather than claim a reach.

**Applied to today's rows, 2026-10-08 (the operator asked "lets figure out all the spellings that are still necessary"; acceptance of the draft is still the operator's).** The population is every live row whose job stays with the parser on native Windows: 0-A's deletes (both classes), speed bumps and secret reads, 13 rows. A fresh agent sorted each by form from its headline alone, one row at a time; no spelling was written down.
- **In the contract, still work (8):**
  - direct form (7): `DEF-1025`, `DEF-1132` (secret reads); `DEF-1041`, `DEF-1175` (deletes outside the project); `DEF-1162`, `DEF-1170` (deletes of the project root); `DEF-1038` (speed bump);
  - one literal wrapper (1): `DEF-1131` (secret read).
- **Outside, a declared limit (1):** `DEF-1173`, a target computed at run time. If the draft is accepted, it is struck with the contract as its reason, not fixed.
- **Not a form question (4):** `DEF-876`, `DEF-980`, `DEF-986`, `DEF-1039` (speed bumps about what the pause covers, not which spelling is read). The contract does not decide these; they stay ordinary rows.
- **Refuting lines:** neither fires. 1 of the 9 form rows falls outside, not more than half, and not none. Said plainly, as the draft asks: the contract strikes one row today. Its reach is new filings, where it stops the next exotic spelling from being filed as work.
- No headline said a real session hit its case, so no row entered the contract by the "slip seen" door.

**What comes after, if the contract holds and in-contract rows keep arriving.** `TP-475`'s lineage, recorded at filing, measures that. The 2026-10-07 finding then applies: each parser tier cuts operands from raw text by its own rules, so a fix to one reader leaves its siblings.
- The next move is one reading of a command, consumed by every tier. That is the direction the titles of `§C65`, `§C66` and `§C76` already point.
- It is a separate pack, raised with that data. It is consolidation, so its own counter-warning applies: the one reading becomes the new site defects arrive at.

**Where it is written:**
- beside `write_guard`'s documented limits in `docs/HOOKS.md` §4 (check `tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS` first);
- in the hook-authoring skill's "Test pattern";
- in the guard-lane brief, whose sibling-spelling step it limits.

Then run `python scripts/sync_claude_mirrors.py`.

## Affected symbols

`/scope-check` keys on bare names. At authoring it listed docs, bench fixtures and sharp-edge entries that merely mention `cmd_init` or `verify_integrity`, and those are not touched. The one real sibling it surfaced is the set of other `verify_integrity` callers, which wave A-3's design decision addresses.

Amended 2026-10-07 (second session): wave A no longer calls the integrity check, so `_integrity_spot_check` is withdrawn from the walk. `verify_integrity` stays only for the optional A-3. Wave A adds the SessionStart baseline and its retirement beside the session markers.
- Re-run of `/scope-check` after the amendment: `_run_main` reads HIGH-RISK at 220 references. That is a name collision: every hook's entry point has that name, and wave A touches only `session_start.py`'s.
- `prune_session_markers` (10 references) and `retire_same_window_markers` (13) are real. Read their callers and tests before giving them a second file per session.

Amended 2026-10-08 (third session):
- Wave A-0 adds the settings-change hook's decision helper, the SessionStart integrity report, and the `ci_guard` wiring check it derives from.
- Wave A-1 adds the advisory printer, which gains the operator line.

Re-run `/scope-check` at the lane's start: these names were added by reading, not by the tool.

### Changed-semantics
- `tools/cc/hooks/config_guard.py::_scan_payload` (wave A-0)
- `tools/cc/ci_guard.py::_scan_settings_for_missing_governance_events` (wave A-0: called from the hook layer, or moved to a module both import; never copied)
- `tools/cc/hooks/session_start.py::_report_integrity_state` (wave A-0)
- `tools/cc/hooks/_hook_utils.py::emit_advisories` (wave A-1: the `systemMessage` line)
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

**0-A's output, 2026-10-08** (44 live rows naming a guard file; one reader; `*` = the headline names a native Windows shell; re-derive at each wave's execution, since rows are filed and struck between):
- zone (4): `DEF-910`, `DEF-995`, `DEF-1161`, `DEF-1171`*
- secret read (3): `DEF-1025`, `DEF-1131`, `DEF-1132`
- false deny caused by zone over-reading (5): `DEF-1012`, `DEF-1013`, `DEF-1014`, `DEF-1015`, `DEF-1016`
- catastrophic delete outside the project (2): `DEF-1041`, `DEF-1175`
- catastrophic delete of the project root (3): `DEF-1162`*, `DEF-1170`*, `DEF-1173`
- speed bump (5): `DEF-876`, `DEF-980`, `DEF-986`, `DEF-1038`*, `DEF-1039`
- false deny, other cause (6): `DEF-898`, `DEF-899`, `DEF-1044`, `DEF-1045`*, `DEF-1125`*, `DEF-1174`*
- instrument (4): `DEF-811`, `DEF-841`, `DEF-860`, `DEF-1153`
- other (12): `DEF-601`, `DEF-759`, `DEF-768`, `DEF-818`, `DEF-862`, `DEF-946`, `DEF-972`, `DEF-1071`*, `DEF-1075`, `DEF-1143`, `DEF-1176`, `DEF-1188`

| Item | Status | Evidence |
|---|---|---|
| guard rows classed **zone** | **TO BE REACHED by wave A** on every host (and by wave B where the OS has a sandbox), per row, in this table, after 0-A | wave A's spelling-independent test (earn-the-red 1) |
| guard rows classed **secret read** | **NOT REACHED by wave A** (a read leaves nothing on disk to compare). **TO BE REACHED by wave B** on macOS, Linux and WSL2 only. **NOT REACHED on native Windows**, where the parser stays the only layer | wave B's `denyRead` drive (0-C); no Windows layer exists |
| guard rows classed **false deny** caused by zone over-reading | **NOT REACHED** by this pack | wave D re-raises: closing them means relaxing a parser guard, which the operator ruled out for now |
| guard rows classed **catastrophic delete outside the project** | **TO BE REACHED by wave B** where the sandbox is on (its default write boundary). **NOT REACHED** on native Windows, or where the sandbox is off, which is the default; there decision C3's contract governs | wave B's drive (0-C), with one harmless write outside the working directory standing in for the delete |
| guard rows classed **catastrophic delete of the project root** | **NOT REACHED** by a location layer; decision C3's contract governs which spellings remain work | after-the-fact cannot undo a delete; prediction stays |
| guard rows classed **speed bump** | **NOT REACHED** by a location layer; decision C3's contract governs | an action on a remote, not a location |
| the settings file losing its hook wiring mid-session (the second session's unfiled candidate: a removed `hooks` key or a deleted file) | **REACHED by wave A-0 (lane/a0-hook-wiring-present, 2026-10-08)**: refused on ConfigChange, judged against the gates the session runs; a partial drop reported at SessionStart; `doctor` already failed both shapes (measured, no change). A deleted, emptied or syntax-broken file wires nothing (Claude Code drops every hook for each, driven) and is refused. Declared limits: a shell-form tree's gates (unprovable, so not recorded as live); an `http`/`mcp_tool` hook, set aside pending `DEF-1195` | A-0's earn-the-red 1 to 6 and the review batch's rows, each seen red; the live drives below |
| `DEF-1041` | **NOT REACHED** | an operator decision (scope out) |

## Pass criteria (per wave; each wave's own pack or lane restates its own)

- **Task 0:**
  - the 0-A counts and ids are in this pack's Reach table;
  - the 0-B coverage gap is named;
  - the 0-C answers are recorded with the Claude Code version they ran on;
  - 0-E's four answers are recorded with the Claude Code version, read back from the throwaway tree's files;
  - any refuting result has stopped the affected wave, and the record says so.
- **Wave A-0:**
  - each of its six earn-the-red tests was seen red against its named mutation, and is green after;
  - the check passes the settings file a fresh `init` writes, driven on this host and on the Mac;
  - the hook layer's check and `ci_guard`'s are one implementation: a test or an import shows they cannot drift.
- **Wave A** *(restated 2026-10-09 at the A-1 lane; the struck lines are the drafts the decision and the design replaced)*:
  - each of A-1's earn-the-red tests ~~(seven, or six if 0-E drops the third)~~ (the pack's six after 0-E, the decision's three, and those the design added; listed in A-1's result) was seen red against its named mutation, and is green after;
  - the operator line was seen in a real session's interface on one report: a screenshot, or the transcript's rendering, recorded with the version;
  - a linked worktree is covered with no manifest present. A-1 reads no manifest, so this holds by construction; the baseline lives in the checkout's own state directory;
  - ~~an ordinary `espalier upgrade` through Bash in a scratch adopter tree produces wording that names what changed and does not say the command wrote it~~ an ordinary `espalier upgrade` through Bash in a scratch adopter tree produces no report (path 4), and a shell edit to a deployed hook reports in wording that names what changed and never says the command wrote it;
  - the added latency of a call that changed nothing is measured on both hosts and written down, under the 25 ms refutation line;
  - ~~the noise rate of one ordinary lane on this tree is measured and written down, under the pre-registered one-in-ten line~~ every report in one ordinary lane on this tree is classified, and any that is not a real unaccounted change is a defect fixed by an accounting path, never a threshold;
  - no existing post-write-check assertion is weakened.
- **Wave B:**
  - `init` without the flag writes no `sandbox` key;
  - with it, the entries match the zone and secret rosters by derivation (a test changes a roster and sees the entries follow);
  - `doctor` reports the three states.
- **Wave C:**
  - every struck row names wave A's test as its probe;
  - decision C3 is recorded in this pack with the operator's words and the date, and the contract text is in `docs/HOOKS.md` §4;
  - every residual row the re-triage struck names the contract as its reason, and the count struck and kept is in this pack;
  - the skill and its mirrors are in sync;
  - no parser assertion is weakened.

## Files touched

- **Task 0:** none (measurements; results written into this pack).
- **Wave A-0:**
  - `tools/cc/hooks/config_guard.py`;
  - `tools/cc/hooks/session_start.py` (`_report_integrity_state`);
  - `tools/cc/ci_guard.py`, or a shared module both import;
  - `espalier/doctor.py`, only if its kill-switch line does not already pick the finding up;
  - their vendored mirrors via `python scripts/sync_vendor_cc.py`;
  - tests for the settings-change hook;
  - `docs/HOOKS.md` (the settings-change hook's section);
  - `CHANGELOG.md`.
- **Wave A:**
  - `tools/cc/hooks/post_write_check.py`;
  - `tools/cc/hooks/session_start.py` (the baseline);
  - `tools/cc/hooks/_hook_utils.py` (the baseline's retirement beside the markers, and the operator line in `emit_advisories`);
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
  - `.claude/skills/hook-authoring/SKILL.md` and its mirrors;
  - `docs/HOOKS.md` §4 (decision C3's contract, beside `write_guard`'s documented limits).
- **Unmodified on purpose:**
  - `tools/cc/hooks/_bash_patterns.py`;
  - `tools/cc/hooks/write_guard.py`'s deny logic;
  - every parser guard (the operator's call).
- **Reread before wave B:** `docs/sharp-edges/chmod-444-decision.md`. Check whether it is a record surface (`tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS`) before editing it (root `CLAUDE.md` Core Rule 13). Supersede it with a slip-model note rather than rewrite a record.

## Sub-task ordering

1. Task 0: 0-A, 0-B and 0-E on any host; 0-C and 0-D on the Mac. Checkpoint: results in this pack; stop where refuted.
2. Wave A-0: depends on 0-E. It is the smallest change and the one that prevents, so it goes first. Checkpoint: its six earn-the-red tests; the fresh-`init` drive on both hosts.
3. Wave A: A-1 (A-2 is decided: tell only); A-3 only if the manifest readers' worktree coverage is still wanted. Checkpoint: the earn-the-red tests, the operator line seen once in a real session, the upgrade drive, the latency and noise measurements.
4. Decision C3, with 0-A's counts. Then wave C: depends on A, 0-A and C3. Checkpoint: the strikes through the ledger verb, the contract in `docs/HOOKS.md`, the skill sync.
5. Wave B: depends on 0-C and decision B2. It may run beside C on the Mac. Checkpoint: the derivation test and `doctor`'s three states.
6. Red-team per wave: both reviewers. Ask for:
   - the write that lands and is never seen (a path outside the zone set, a zone file the exclusions wrongly cover, a change between the SessionStart baseline and the first call);
   - the legitimate update that trips the check on every call;
   - for A-0, the legitimate settings edit it refuses;
   - the defect the new layer brings with it (the counter-warning above).
7. Wave D: re-raise to the operator with A to C's data.

**Coordination, read 2026-10-08 from the mail channel's live claims and the adopter-readiness packs:**
- **Wave A** edits `tools/cc/hooks/_hook_utils.py`, which the Air's live `TP-472` claim holds. It starts after that lane merges.
- **Wave A** edits the shell branch of `post_write_check.py::_check`, before the `_is_write_tool` return. `TP-470` rewrites the same lines (its self-host gate around `_bash_derived_payloads`). Agree the order by claim before either starts; whichever lands second rebases onto the first's branch, never edits around it.
- **Wave A-0** edits `config_guard.py` and `session_start.py::_report_integrity_state`:
  - `TP-474` 2-A moves `config_guard.py`'s module-top imports;
  - `TP-473` 1-E rewords `_report_integrity_state`'s CI sentence.

  Land A-0 first, since it is small and needs neither, or say in the claim which function each lane holds.

## Estimated effort

| Step | Budget |
|---|---|
| Task 0 (0-E included) | 3 h (half of 0-C and 0-D on the Mac) |
| Wave A-0 | 3 h with red-team |
| Wave A | 5.5 h with red-team (the operator line added) |
| Decision C3 and its re-triage | 1.5 h, the decision itself the operator's |
| Wave C | 3 h |
| Wave B | 5 h |
| **Total** | **about 21 h**, four or five lanes |

**Most likely to be wrong:**
- that ConfigChange fires for an edit a tool call makes, and that its deny keeps the hooks running (0-E decides; A-0 shrinks to a report if not);
- that the operator line is read as signal rather than noise. Its once-per-path throttle is a guess; count how many lines one ordinary lane shows the operator, beside the one-in-ten line;
- that a coverage contract is enough to stop the chase on the residual jobs. If in-contract rows keep arriving, wave C-2 names the next move;
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
