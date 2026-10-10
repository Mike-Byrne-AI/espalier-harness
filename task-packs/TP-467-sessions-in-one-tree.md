# TP-467 — Sessions in one tree: same-machine session isolation for the anti-clobber system

## Status

- Version target: wave A lands on `lane/sessions-in-one-tree` (after `0.8.0b2`); waves B to D are scheduled on their own, each as its own lane with its own Task 0 and reviewers.
- Type: assessment (this document) + feature (wave A, a reporter) + design (waves B to D).
- Ledger: one row in §3 names this pack; `INV-7` routes its worktree-governance half here (wave B); `DEF-861` is the row wave C closes; `TP-248` (multiagent worktree isolation, drafted and deferred, no file) is superseded by this pack. `DEF-1136` (the goal read and write from a linked worktree, filed 2026-10-06 from the Windows box's report) is routed to wave C; `DEF-1137` (the rest of the handoff chain from a linked worktree, filed the same day from the review) was wave B's precondition and landed 2026-10-06 on `lane/handoff-chain-from-a-worktree`.
- Gate: the operator approved the four-wave order on 2026-10-05 ("plan approved"). Wave A executes on this lane. Waves B to D each wait on their own Task 0.
- **Wave B moved to `TP-479`** (its Wave B-2) on 2026-10-09, on the operator's decision ("Pull TP-467 wave B into this build approved"). Per-seat id blocks there make the per-worktree name load-bearing. This pack's wave B text is that wave's design input, and its Task 0 reads `WorktreeCreate`'s contract first. Waves C and D stay here.
- **Kind: ROADMAP** — the deliverable is the assessment and the wave map. Wave A's Implementation is copy-ready because this lane lands it; waves B to D carry fix shapes marked untested, and each earns its own pack before an unattended chain touches it. This pack must not enter an unattended chain as a whole.
- Provenance: driven on the self-host tree on 2026-10-05, the day the two-machine half of the anti-clobber system finished (PRs #94, #96, #100, #101). Every measured claim below names its command.

## Motivation — the assessment

The anti-clobber system was built in four lanes for **two machines sharing one origin**: a mail channel with one append-only ref per machine (`tools/cc/mail.py`), claims that carry ledger row ids and are read by the ledger verbs before they take the lock (`tools/cc/ledger_row.py::_claims_in_the_way`), a record merge keyed on the row id (`tools/cc/record_merge.py`), a conflict-marker gate at four sites (`DEF-1127`), and a release of a lane's claims when it ships (`tools/cc/ship.py::_release_claims`). That half is complete by shape: the ref layout makes a cross-machine clobber of a record file structurally impossible, and the claim read turns the remaining collision (one id minted twice) into a refusal at the write.

The question this pack answers is the **other** half: many agents, or many Claude Code sessions, on **one machine**. Measured 2026-10-05:

1. **Data integrity on one machine holds.** Every read-modify-write site takes a cross-platform lock since `DEF-974` closed on 2026-10-02 (`tools/cc/_json_safe.py::lock_file`; the plan file, the blueprint records, the audit append, the counters, the speed-bump state, the freshness cache, the review corpus) and the ledger verbs take an exclusive lock beside the ledger (`tools/cc/generate_ledger_regions.py::ledger_lock`). Blueprint nodes are per-session files (`cc/blueprints/{session_id}.json`). Filing an id already in the ledger is refused (`ledger_row.py`: "already exists"), so two sessions in one checkout cannot mint one id twice. Measured: `command grep -n 'already exists' tools/cc/ledger_row.py`; `DEF-974`'s row at `task-packs/FORWARD_LEDGER.md` carries the ten-of-ten Windows figure.
2. **Coordination on one machine does not exist.** The claims key on the machine name, and both readers exclude this machine's own claims (`tools/cc/ledger_row.py::_claims_in_the_way` and `tools/cc/execution_plan.py`, the `exclude_machine=` argument), so two sessions on one box are one identity to the channel and never see each other. `docs/SHARP_EDGES.md` "The worktrees of one clone share its machine name, so the claims pre-flight hides a sibling's claims" documents it with a config hatch (`extensions.worktreeConfig`, a per-worktree `espalier.machine`); nothing detects the un-hatched state. Measured: `command grep -n 'exclude_machine' tools/cc/ledger_row.py tools/cc/execution_plan.py`.
3. **Every "current X" file is a singleton with no session key.** `cc/execution_plan.json` has the keys `created, goal, not_doing, status, steps, task` and no owner, so a second session's writes pass `plan_guard` under the first session's plan (measured: `python3 -c "import json; print(sorted(json.load(open('cc/execution_plan.json'))))"`). `cc/blueprints/latest.json` is the pointer `DEF-861` and `docs/FAILURE_MODES.md` §16.2 describe (46 pinned entries lost, 15.6 percent, measured there). `cc/_working_summary.md` is last-writer-wins by design (`docs/SHARP_EDGES.md`, the entry of that name). The per-session flags under `.espalier-state/` are keyed by name, not by session, and `session_start.py::_clean_state_flags` wipes them at every non-continuation SessionStart, the other session's included. The mail cursor `.espalier-state/mail_seen.json` is shared, so one session's `--mark-read` hides mail from the other.
4. **The worktree answer is undermined on two fronts.** The one-writer rule (`memory/one-writer-per-shared-state.md`, root `CLAUDE.md` Core Rule 14) says one session per worktree. (a) Claude Code's own worktrees (`isolation: "worktree"`, `EnterWorktree`, `--worktree`) are linked worktrees under `.claude/worktrees/<name>/` and share the clone's config, so every one of them answers the same machine name by default (`docs/external/cc-worktrees.md`; the sharp edge above, driven `one=air two=air`). (b) A session that **enters** a worktree mid-session keeps `CLAUDE_PROJECT_DIR` at the main checkout for its hooks (`docs/external/cc-worktrees.md` "The hook's `cwd` follows Claude into the worktree; `CLAUDE_PROJECT_DIR` stays put"), and `tools/cc/_paths._repo_root` prefers that variable, so its blueprints, plan and flags land in the **main** tree beside the first session's; meanwhile a `tools/cc` script run from the Bash tool resolves its root by walking up from the worktree's cwd (`CLAUDE_PROJECT_DIR` is unset in the Bash tool's environment, measured in-session: `echo ${CLAUDE_PROJECT_DIR:-unset}` prints `unset`), so the hook side and the tool side of one session may read **different** plan files. Hypothesised, not driven: `plan_guard` denies a worktree session's writes because the plan its `execution_plan.py create` wrote is not the one the hook reads. Wave C's Task 0 drives it. The two shipped sentences saying separate worktrees never collide (`docs/SHARP_EDGES.md` "The live working-summary doc is last-writer-wins under parallel sessions"; `docs/FAILURE_MODES.md` §16.2 mitigation (4)) are true for a session launched inside the worktree and false for one that entered it; wave A corrects both. **Corrected 2026-10-08:** "true for a session launched inside the worktree" holds for collisions only. Such a session reads the shared `.claude/settings.json` from its own directory, the file is gitignored, and a worktree checks out tracked files only, so it loads no hooks at all unless the file was copied in. Measured on the Windows clone: two background sessions in a Claude Code worktree with `/hooks` listing none. `DEF-1192` carries it; the repo-root `.worktreeinclude` and the landing check's wiring arm cover the self-host tree. Wave B's design inherits the fact: a worktree that `WorktreeCreate` makes needs the settings copied as well as a name.
5. **The git index and working tree have no mechanism**, only the discipline in Core Rule 14. A worktree per session is the answer, and nothing in the tree says so when it is not happening.
6. **What Claude Code gives us** (from the pinned excerpts under `docs/external/`, re-read 2026-10-05; the weekly refresh PR #95 carries the same roster): `WorktreeCreate` and `WorktreeRemove` hook events exist, with `session_id` and `worktree_path` in the payload, a non-zero exit refusing creation and a path on stdout overriding the location (`docs/external/cc-hook-protocol.md`, the per-event exit table). `SessionEnd` exists with a `reason` field. Every hook payload carries `session_id`; the Bash tool's environment carries `CLAUDE_CODE_SESSION_ID`, undocumented, and it equals the transcript stem under `~/.claude/projects/<slug>/` (measured in-session: `ls ~/.claude/projects/<slug>/ | grep -c "^$CLAUDE_CODE_SESSION_ID"` prints 2). `SubagentStop` carries `agent_id`, `agent_type` and `agent_transcript_path` beside the common fields, so its `session_id` is read as the parent session's — a reading, not a measurement, until wave C's Task 0 logs it. Claude Code documents no detection of two sessions in one project directory. Two more facts measured in-session on 2026-10-05 while wave A was reviewed: a `/clear` mints a **new** session id (the transcript stem under `~/.claude/projects/<slug>/` changed across one clear, and the `session_started` flag shows SessionStart fired at it), so the predecessor's marker is minutes old when the new session's banner reads it; and on this macOS box a hook's parent process is the `claude` process itself, with no shell in between (`ps -axo pid,ppid,comm` sampled during hook runs: four hook rows, every parent the one `claude` pid), so the hook's parent pid is a stable identity for the window across a clear. Wave A's retire-on-clear is built on the second fact and fails safe where it does not hold. **Corrected 2026-10-10:** `WorktreeCreate`'s payload carries `name`, not `worktree_path`; that field belongs to `WorktreeRemove`. The hook also replaces git's creation rather than adding to it. On the Windows box a hook's parent is the venv's `python.exe` launcher, not `claude`, so the parent-pid fact holds where `python` is no redirector. Both were measured in `TP-479` Wave B-2's Task 0 and B-4's first evidence.

**Does a session-id key accomplish "session state documents do not get clobbered"?** For the per-session class, yes, conditional on the two Task 0 measurements in wave C: the plan, the blueprint head, the per-session flags and the working-summary view each get a file named by the session, SessionStart clears only its own, and a reader resolves "mine" by the id in its payload. It does **not** address: the git index and tree (one worktree per session is the only answer; wave B makes Claude Code's worktrees usable for it); the tracked record files (claims, locks and the record merge already cover them; wave B gives sibling worktrees their own claim identity); `cc/GOAL.md` (a project record, not a session document; two handoffs at once conflict in git and the record merge does not take it, which is the right refusal); and the mail cursor (per box by nature, since it records what this operator has read).

**The named user** (`docs/STANDING_PRINCIPLES.md` §16): the operator running a second Claude Code session on the Air during ledger work, in a second tab or in a worktree entered mid-session. The Windows box cannot collide with them; the second Air session can mint their next DEF id, pass `plan_guard` under their plan, and inherit or demote their blueprint node, with nothing said.

## Scope (in)

- **Wave A — say it (this lane).** SessionStart writes one marker per session under `.espalier-state/sessions/<session_id>` (a JSON object: id, start time, the hook's parent pid, the payload's `cwd`, the source), the prompt hook touches it on every prompt as a heartbeat, and the banner gains a `Sessions:` line naming each other marker touched within the live window: its id prefix, when it started, when it last prompted, the sentence saying what is shared, and the pointer to the sharp edge. Reporter only, omitted when nothing qualifies, read once in `main` and threaded into both banner builders like `Loose:`. Markers older than the prune window are swept at SessionStart. The two worktree sentences gain the entered-mid-session caveat. `INV-7` routes to wave B. `TP-248`'s registry line points here.
- **Wave B — a name per worktree, by code.** A `WorktreeCreate` hook that sets the per-worktree machine name through git's per-worktree config (`extensions.worktreeConfig true` once; `git -C <worktree> config --worktree espalier.machine <name>-<short>`), so a Claude-made worktree has its own mail ref, its own claims and its own view of the siblings', and a `WorktreeRemove` hook that releases that name's live claims. Turns the sharp edge's config hatch into mechanism. Fix shape, untested: the hook must also seed the worktree's own state root (`.espalier-state/` is gitignored and `.worktreeinclude` governs what copies), or wave C's state-root rule must make the hook side and the tool side agree.
- **Wave C — key the singletons by session.** The execution plan, the blueprint head (`latest.json`'s "which node is mine" half), the per-session flags, and the working summary's live view each move under a session key; SessionStart clears only its own; a sweep prunes orphans; the chain's lineage pointer advances at finalize, not at start (`DEF-861`'s fix shape and §16.3's barren-node rule together). The state-root rule for a worktree entered mid-session: hooks read the payload's `cwd` and resolve the worktree root when the cwd is a worktree of the project, so the hook side and the tool side name one root. The goal read gets its own answer under that rule (`DEF-1136`): re-rooted on the worktree, a hook finds no goal at all rather than a stale one (the Windows box's reading of 2026-10-06, from the pack, not driven), so wave C's Task 0 gains the measurement below, and the one shape measured so far is a local, never-pushed ref (say `refs/espalier/goal`) written from a linked worktree and read back from the main checkout, with `update-ref` against the old value refusing a stale second writer (measured by the Windows box in a scratch repo, 2026-10-06).
- **Wave D — release at the end.** A `SessionEnd` hook that deletes the session's marker and releases this session's per-session state (within the 1.5 second budget the event gives). Without it wave A's marker outlives a closed window until it ages out, and the line says so.

## Scope (out)

- **Changing the two-machine half.** The mail channel, the claims, the record merge and the conflict-marker gate stand as landed; wave B adds a name per worktree through the key they already read.
- **Locking the git index or the working tree.** Two sessions in one checkout share one index by git's design; the answer is a worktree per session, and this pack makes the harness say so (A) and make Claude Code's worktrees fit (B), not serialise git.
- **`cc/GOAL.md` and the committed record files under a session key.** They are project records; a conflict between two handoffs belongs in git, where the record merge refuses it by shape. The same-machine shape is not covered by that answer and wave C must still give one: a session inside a linked worktree reads the main checkout's goal through the project-dir variable and cannot write it (the worktree has no gitignored `cc/GOAL.md`, and, as the Windows box reports, Claude Code's worktree isolation refuses writes to the main checkout), so the goal needs a location rule beside the plan and the flags -- `DEF-1136`, routed to wave C; the session key itself stays out of scope for it.
- **A per-session mail cursor.** What this operator has read is a fact about the box.
- **`DEF-663`'s churn roster.** Wave A's heartbeat is one more write under `.espalier-state/` per prompt, the class `DEF-663` already names (the pin-isolation control's roster lacks `.espalier-state/`); that row's fix adds the prefix once for every member, and this pack does not fix it one member at a time. Closed 2026-10-06 by lane `c28-test-tree-enumeration`: `DEF-663` struck, the roster gained `.espalier-state/` for every member, the heartbeat included.
- **Documenting the session-id environment variable as a contract.** `CLAUDE_CODE_SESSION_ID` is undocumented upstream; the harness reads the id from the hook payload, where it is documented, and the Bash side reads the variable only where a measurement (wave C's Task 0) shows the two agree.

## Task 0 — Verify

Each wave has its own. Wave A's ran on this lane.

**Wave A.**
- **Oracle:** `command grep -n -E 'Sessions:|sessions/' tools/cc/hooks/session_start.py tools/cc/hooks/_hook_utils.py` and `ls .espalier-state/` on a tree that has run two sessions.
- **Refuting result:** a `Sessions:` line, or a per-session marker, already exists; then wave A is a doc change only.
- **Measured 2026-10-05:** the grep prints nothing; `.espalier-state/` holds one `session_started` timestamp (the latest session's) and no per-session file. Build.

**Wave B.**
- **Oracle:** the `WorktreeCreate` payload as pinned in `docs/external/cc-hook-protocol.md` (fields, exit semantics), re-fetched; then a scratch clone with `extensions.worktreeConfig true`, a worktree added, and `python3 tools/cc/mail.py claims` run from both with `--dry-run` sends, to show two names and two views.
- **Refuting result:** the event does not carry `worktree_path`, or its stdout cannot name the path and a per-worktree config cannot be set before the session's first hook fires. Then the hatch stays config and this wave records why.
- **Exit:** stop and re-raise with the measurement.

**Wave C.** Two measurements, both required before any key is written.
- **Oracle 1 (parity):** a scratch hook on `PreToolUse` that logs the payload's `session_id`, beside `echo $CLAUDE_CODE_SESSION_ID` from the Bash tool in the same session.
- **Refuting result 1:** the two differ; then the Bash-side tools cannot find the hook side's file by that variable, and the state-root rule must pass the id another way (a marker the hook writes that the tool reads).
- **Oracle 2 (subagents):** the same scratch hook on `SubagentStart` and `SubagentStop` during one `Agent` dispatch.
- **Refuting result 2:** the subagent's events carry an id other than the parent's; then `subagent_stop`'s blueprint append must map `agent_id` to the parent's session, or the per-session blueprint head splits one session across two keys (§16.2's own caveat).
- **Oracle 3 (the entered-worktree shape):** a session that enters a Claude-made worktree, then `python3 tools/cc/execution_plan.py create` from the Bash tool and one `Write` under `plan_guard`.
- **Refuting result 3:** the write passes. Then the hook side and the tool side already agree and the state-root rule is unneeded; the keying still proceeds for the two-tabs shape.
- **Oracle 4 (the goal in a worktree):** a session in a Claude-made worktree, then what its banner's GOAL section shows and what `/handoff`'s goal step (`scripts/handoff_mechanics.py::after_goal`) reads and writes, beside the same two from the main checkout.
- **Refuting result 4:** the worktree session's banner shows a goal of its own and its handoff writes one the main checkout's next banner reads; then `DEF-1136` is struck as already answered and the location rule is unneeded.
- **Exit:** any refutation re-raises with the measurement before a key is written.

**Wave D.**
- **Oracle:** `SessionEnd` as pinned; a scratch hook that deletes a marker, timed.
- **Refuting result:** the event does not fire for the reasons that matter (`clear`, `prompt_input_exit`) or the budget is too short for a release send; then the marker ages out as wave A says and this wave is scrapped.

## Relevant memory

Recent pattern: the last two lanes on the anti-clobber system each grew under review to roughly twice the fix (the marker gate from two sites to four; the claims lane by a shared blocker, the loader outside its fail-open try). Both reviewers caught what the targeted proofs did not, and the enumerator pins caught a portability red the proofs missed. Expect the same here.

| Entry | Where |
|---|---|
| The live working-summary doc is last-writer-wins under parallel sessions | `docs/SHARP_EDGES.md` (entry of that name) |
| The worktrees of one clone share its machine name, so the claims pre-flight hides a sibling's claims | `docs/SHARP_EDGES.md` (entry of that name) |
| A per-clone identity cannot live in a tracked config file | `docs/SHARP_EDGES.md` (entry of that name) |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| Hook authoring | `memory/hook-authoring.md` |
| §16.2 Per-repo session state with no session identity; §16.3 An empty link terminates a lineage | `docs/FAILURE_MODES.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "two Claude Code sessions in one checkout clobber the blueprint pointer and the working summary"` and `... "worktrees of one clone share the machine name so claims hide a sibling"`; re-run them rather than trusting this list if the pack has been sitting.

Constraints each imposes on wave A, written before the first edit:
- *Last-writer-wins entry:* the line names the three singletons by name and points at this entry; it does not claim the marker fixes them.
- *Worktree machine-name entry:* the marker lives under the state root the hooks resolve, so a worktree entered mid-session writes its marker beside the first session's (the collision the line exists to name) and a worktree launched on its own has its own.
- *Per-clone identity entry:* nothing about a session is written to a tracked file; the markers sit under gitignored `.espalier-state/`.
- *One writer:* the marker is per session by construction (named by the payload's id); the only shared write is the prune, which deletes by age and swallows a vanished file.
- *Hook authoring:* reporter, fail-open at every step, stdlib only, zero espalier imports, ASCII in the banner, omitted when empty, read once in `main`, both builders, `scripts/sync_vendor_cc.py` after, `mypy tools/cc/hooks/`; the payload's `session_id` is untrusted text and is sanitised to `[A-Za-z0-9_-]` and capped before it names a file.
- *§16.2 / §16.3:* the sessions directory is not a flag, so `_clean_state_flags`' named list and prefix globs must never reach it, or the second session's start erases the first's marker (the exact clobber being reported).

## Implementation

### Wave A (this lane) — *Fix (driven on this lane; the tests below are the oracle)*

**A-1 `tools/cc/hooks/_hook_utils.py` — the single owner of the marker.** Constants `SESSIONS_DIR = "sessions"`, `SESSION_MARKER_LIVE_S`, `SESSION_MARKER_PRUNE_S`, `SESSION_ID_MAX_CHARS`; `safe_session_id(sid)`; `sessions_dir(root)`; `session_marker_path(root, sid)`; `write_session_marker(root, sid, *, pid, cwd, source, started, keep_started)` (atomic JSON, never raises; `keep_started` carries a prior marker's start across a `compact` or `resume`; `cwd` is tail-capped so the leaf survives); `touch_session_marker(root, sid)` (keyword `pid` and `cwd` since 2026-10-05; the self-heal records them and a pid-less marker is repaired on touch) (`os.utime`, writes a minimal marker when none exists so a session started before this landed still reads as live); `prune_session_markers(root, now)`; `other_live_sessions(root, sid, now)` returning the sibling markers touched within the live window, newest first, with the recorded `cwd` and `pid`; `retire_same_window_markers(root, sid, pid)` for the `clear` source. Placed beside `STATE_DIR` with the producer/consumer-parity comment the `COLD_OPEN_FLAG` block uses.

**A-2 `tools/cc/hooks/session_start.py`.** In `_run_main`, a third best-effort flag job writes the marker from the payload (`session_id`, `cwd`, `source`, `os.getppid()`) and raises into the loop's warn when the helper could not write it, so the failure is at least said; on `source == "clear"` the sibling markers recording this hook's parent pid are retired first (the previous session of this window); then `sessions_line = _sessions_line(root, sid)` is read beside `loose_line` under the same warn-and-continue shape. `_build_context` and `_build_compact_context` gain `sessions: str = ""` and render `Sessions:  {sessions}` after `Loose:` and before `Open PRs:`, omitted when empty. `_sessions_line` names up to three siblings (id prefix, started, last prompt, and the recorded `cwd` when it differs from this root), then `and N more`, then the shared-state sentence, the launched-worktree advice, the closed-window hedge and the sharp-edge title; ASCII; the start reads `start time unknown` when a marker's JSON cannot be read (its mtime is the fact that counts it).

**A-3 `tools/cc/hooks/task_router.py`.** In `_run_main`, right after `root` is resolved and before the prompt's shape is checked: `touch_session_marker(root, safe_session_id(data.get("session_id")))` (since 2026-10-05 with `pid=os.getppid()` and the payload's resolved cwd, so a marker the heartbeat writes or repairs carries the window a `clear` retires by: the heartbeat-pid lane), best-effort.

**A-4 Docs.** `docs/SHARP_EDGES.md` (the last-writer-wins entry's worktree sentence), `docs/FAILURE_MODES.md` §16.2 mitigation (4), `docs/HOOKS.md` (the `session_start.py` section, beside `Loose:`), root `CLAUDE.md` (the hook table's `session_start.py` row), `CHANGELOG.md` (Added). `scripts/sync_asset_docs.py` after `docs/HOOKS.md`.

**A-5 Ledger.** This pack's registry row after `TP-466`'s; `TP-248`'s line gains "superseded by TP-467"; the `INV-6` `INV-7` row gains the route to wave B. No `DEF` id is minted on this lane; the lane's claim on the mail channel names the paths.

### Waves B to D — *Fix shapes, untested*

Each is the paragraph under Scope (in), and each is refuted or confirmed by its Task 0 above before a child pack is written. **Most likely to be wrong, by the authors' own reading:** wave C's assumption that one id names a session on both the hook side and the Bash side; if Oracle 1 refutes it, the state-root rule carries the id through a file the hook writes and the tool reads, and the design cost roughly doubles.

## Affected symbols

### Changed-semantics
- `tools/cc/hooks/session_start.py::_run_main` (writes the session marker; reads the sibling markers; threads `sessions` into the builders)
- `tools/cc/hooks/session_start.py::_build_context` (new `sessions` parameter, rendered after `Loose:`)
- `tools/cc/hooks/session_start.py::_build_compact_context` (same)
- `tools/cc/hooks/task_router.py::_run_main` (touches the session marker on every prompt)

### Renamed
- (none -- no symbol moves.)

### Added-paths
- `tools/cc/hooks/_hook_utils.py::SESSIONS_DIR`
- `tools/cc/hooks/_hook_utils.py::SESSION_MARKER_LIVE_S`
- `tools/cc/hooks/_hook_utils.py::SESSION_MARKER_PRUNE_S`
- `tools/cc/hooks/_hook_utils.py::SESSION_ID_MAX_CHARS`
- `tools/cc/hooks/_hook_utils.py::safe_session_id`
- `tools/cc/hooks/_hook_utils.py::sessions_dir`
- `tools/cc/hooks/_hook_utils.py::session_marker_path`
- `tools/cc/hooks/_hook_utils.py::_read_marker`
- `tools/cc/hooks/_hook_utils.py::_marker_started`
- `tools/cc/hooks/_hook_utils.py::_marker_time_s`
- `tools/cc/hooks/_hook_utils.py::_tail_capped`
- `tools/cc/hooks/_hook_utils.py::write_session_marker`
- `tools/cc/hooks/_hook_utils.py::touch_session_marker`
- `tools/cc/hooks/_hook_utils.py::prune_session_markers`
- `tools/cc/hooks/_hook_utils.py::other_live_sessions`
- `tools/cc/hooks/_hook_utils.py::retire_same_window_markers`
- `tools/cc/hooks/session_start.py::_sessions_line`
- `tools/cc/hooks/session_start.py::_age_text`
- `task-packs/TP-467-sessions-in-one-tree.md`

### Removed-paths
- (none.)

## Reach

Members derived by: `command grep -n -E 'DEF-861|INV-7|TP-248|DEF-663|DEF-1136|DEF-1137' task-packs/FORWARD_LEDGER.md` plus the two `docs/SHARP_EDGES.md` entries named under Relevant memory (the same-machine case has no class row; it lives in those two entries, `DEF-861` and §16.2).

| Item | Status after wave A | Evidence |
|---|---|---|
| The second session is named at start | **CLOSED (A)** | `tests/test_session_banner.py::TestSessionsLine` drives a sibling marker and asserts the line |
| The handoff-then-clear loop names the operator's own previous window | **CLOSED (A) where the hook's parent is the Claude Code process** (measured on this macOS box); **NOT REACHED (D)** where it is a per-spawn shell or launcher (a Windows venv's `python.exe` redirector is this shape, measured on the Windows box 2026-10-06: the test's spawned hook recorded the redirector's pid; `py.exe`, a launcher that runs the interpreter as its child, reads as the same shape, not measured; the tests spawn past it through `tests/_interpreter_hosts.py::HOOK_PYTHON`, the base interpreter, which says nothing about a live Claude Code window there) | `retire_same_window_markers` on `source == "clear"`; `tests/test_hooks.py::TestSessionMarkerEndToEnd` drives a predecessor recording the test process's pid through a startup (kept, named) and a clear (retired, unnamed) |
| Two worktree sentences claiming no collision | **CLOSED (A)** | the two edits; the entered-mid-session shape is what `docs/external/cc-worktrees.md` pins |
| `INV-7` worktree governance | **ROUTED (B)** | the row's text names this pack's wave B |
| `TP-248` multiagent worktree isolation | **SUPERSEDED** | the registry line names this pack |
| Sibling worktrees share one claim identity | **NOT REACHED (B)** | a reporter cannot give a worktree a name; wave B's hook does |
| The record snapshot from a linked worktree | **CLOSED (lane record-merge-criss-cross, 2026-10-06)** | `scripts/record_snapshot.py::linked_worktree_main` refuses by name, every mode alike; `tests/test_record_snapshot.py::TestLinkedWorktreeIsRefused` |
| The rest of the handoff chain from a linked worktree | **CLOSED (B precondition, landed 2026-10-06)** | `DEF-1137`: `after_goal` refuses a linked worktree before its first append, and the landing check's operator-tree tell reads a linked worktree of the operator's tree as that tree (`_operator_root`); `tests/test_handoff_mechanics.py::TestAfterGoalRefusesALinkedWorktree` and `tests/test_check_handoff_landing.py::TestALinkedWorktreeOfTheOperatorsTreeIsTheOperators` drive both; what a worktree session's handoff still cannot do -- file its own archive leg, blueprint and record, and have the landing check grade its commit from the main checkout -- is wave B's, named in the refusal and in step 5's next line |
| The goal read and write from a linked worktree | **NOT REACHED (C)** | `DEF-1136`: the banner reads the main checkout's goal, the handoff cannot write it; wave C's location rule, measured first by Task 0's Oracle 4 |
| `DEF-861` second SessionStart demotes the running node | **NOT REACHED (C)** | the marker names the collision; it does not move the pointer |
| The plan singleton passes a second session's writes | **NOT REACHED (C)** | named in the line's shared-state sentence; keyed in wave C |
| The flag wipe at a second SessionStart | **NOT REACHED (C)** | the marker directory is exempt from the wipe by construction; the flags themselves are wave C |
| `DEF-663` churn roster lacks `.espalier-state/` | **NOT REACHED (out of scope)** | one more member of a class that row closes once |
| The marker outliving a closed window | **NOT REACHED (D)** | the line says a stale last-prompt time may be a closed window; wave D deletes at `SessionEnd` |

## Pass criteria (wave A)

- `tests/test_session_banner.py::TestSessionsLine` and `tests/test_task_router.py::TestSessionHeartbeat` pass, and each new test was seen red against the named mutation in Landing.
- `tests/test_state_file_flag_parity.py` pins the marker's shape (a JSON object under 1 KiB with the five keys) beside the four flags it already pins, its state-dir roster admits `sessions` and its predicate test rejects the near-miss `session`.
- A `clear` retires only a sibling marker recording this hook's parent pid; a `startup` retires nothing; the own marker is never retired (driven at the helper and through the real hook).
- No assertion in the existing banner tests is weakened; the shorter-arity callers of `_build_context` keep a byte-identical banner (the omit-when-empty contract).
- `_clean_state_flags` on a fresh source leaves a sibling session's marker in place (a test drives two markers through the clean and asserts both survive).
- `mypy tools/cc/hooks/` and `ruff check .` are clean; `python3 scripts/sync_vendor_cc.py` leaves no diff after the edits; `python3 scripts/proof_tier.py` prints `full` for this diff and `--run` is green.
- The two doc sentences name the entered-mid-session shape and cite `docs/external/cc-worktrees.md`.

## Files touched (wave A)

- New: `task-packs/TP-467-sessions-in-one-tree.md`.
- Modified: `tools/cc/hooks/_hook_utils.py`, `tools/cc/hooks/session_start.py`, `tools/cc/hooks/task_router.py`, their vendor mirrors under `espalier/_vendor/cc/hooks/`, `tests/test_session_banner.py`, `tests/test_task_router.py`, `tests/test_state_file_flag_parity.py`, `tests/test_hooks.py` (one end-to-end marker test in `TestSessionStartV3`), `docs/SHARP_EDGES.md`, `docs/FAILURE_MODES.md`, `docs/HOOKS.md` and its asset mirror, `CLAUDE.md`, `CHANGELOG.md`, `task-packs/FORWARD_LEDGER.md`.
- Unmodified on purpose: `tools/cc/mail.py`, `tools/cc/ledger_row.py`, `tools/cc/execution_plan.py`, `tools/cc/cognitive_blueprint.py` (waves B and C), `.claude/settings.json` and `espalier/cli.py`'s hook roster (no new event is wired in wave A).

## Sub-task ordering (wave A)

1. Task 0 (above; measured, build).
2. A-5 then this pack: the record and the plan artifact first, so a session that dies here leaves the assessment.
3. A-1, A-3, A-2 with their tests; checkpoint: the two targeted test files plus `tests/test_state_file_flag_parity.py`.
4. A-4; checkpoint: `python3 scripts/sync_asset_docs.py` leaves no diff, `python3 scripts/sync_vendor_cc.py` leaves no diff.
5. Enumerator pins (`tests/test_test_suite_contract.py tests/test_marker_taxonomy.py tests/test_portability_contract.py`), then the two reviewers on a snapshot clone built from the diff against HEAD, edits frozen; one fix batch.
6. The full tier under `nohup` with `EXIT=$?` appended; commit; `/handoff` ships.

## Estimated effort (wave A)

Authoring this pack 45 min; A-1 to A-3 with tests 90 min; A-4 and A-5 30 min; review round and fix batch 60 min; tier 15 min wall. Total about four hours. (Pack budgets on this tree have run over by about 2.7x on one measured pack; read this as a floor.)

## Landing

- State: ROADMAP (wave A landed on `lane/sessions-in-one-tree`, 2026-10-05; waves B to D unscheduled, each waiting on its own Task 0)
- Commits: the lane's one commit on `lane/sessions-in-one-tree` (its SHA is not known to the file it carries; `git log --grep TP-467 -- task-packs/TP-467-sessions-in-one-tree.md` derives it)
- Suite: `python3 scripts/proof_tier.py --run` at the tier the diff earns (`full`: the hook type gate, the lint line, the parallel leg, the five serial files), green on 2026-10-05; the receipt names the four lines
- Earn-the-red: fourteen named mutations, each run against only its test with the source restored after -- the flag cleaner reaching the sessions directory, the line silenced, the own marker counted as a sibling, the id used unsanitised, the heartbeat dropped, the live window ignoring mtime age, `keep_started` ignored, the retire ignoring the pid match, the retire never called on `clear`, the cwd never shown, the cwd cut from the head, the heartbeat below the prompt check, the roster without `sessions`, the tail regressing to the pre-review advice -- every one red
- Red-team: code-reviewer (no blocker, two nits: the heartbeat sat below the prompt's type check; an unreachable fallback branch) and failure-mode-reviewer (one blocker: the hand-kept state-dir roster in `tests/test_state_file_flag_parity.py` lacked `sessions`, proven red in a scratch copy with the directory present; three majors: the tail gave the advice the same diff corrects, a `clear` would name the operator's own previous window on every handoff-then-clear loop, the line said that but never which; two minors: the marker write's only failure report was unreachable, the heartbeat is one more unconditional per-prompt write under the live-tree snapshot `tests/test_verify_pins.py` watches, recorded not rostered; three nits: the HOOKS.md count of conditional lines, pack drift in Added-paths and the two-marker criterion, `pid` and `cwd` recorded with no consumer) -- landed as one batch on a snapshot clone with edits frozen: the roster entry and its negative twin, the launched-worktree wording, the retire on `clear` keyed on the hook's parent pid after measuring that a clear mints a new id and that the parent is the `claude` process here, the cwd shown when it differs (tail-capped), the write failure raised into the loop's warn, the heartbeat moved above the prompt check, the dead branch dropped, the two-marker drive, the pack and doc text; `pid` and `cwd` now each have a consumer
- Reach: see the table above; wave A closes three rows of it and routes two
- Date: 2026-10-05
