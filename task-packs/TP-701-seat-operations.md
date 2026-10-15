# TP-701 — Seat operations: the board sees seats and asks, a seat is launched by a driver, and the metrics are instruments

## Status

- Version target: adopter-facing where it touches `tools/cc/` (the board, the mail driver,
  the new seat driver and the SessionStart hook all deploy through `espalier init` via the
  vendored byte-copy, `espalier/_vendor/cc/`); self-host only where it touches `scripts/`
  (the two census instruments) and `memory/` (the protocol). An adopter that runs seats gets
  the same board, launcher and gates this repository runs on; the protocol prose stays here
  (`espalier/assets/memory/` seeds no protocol file, read 2026-10-14).
- Type: workflow infrastructure. It extends the dispatch system `TP-479` built (mail, board,
  assigns, claims, minted ids, worktree seats) with what five days of running it showed missing.
- **Kind: PACK.** Four waves, each a lane a seat can ship on its own (one open pull request per
  seat); Wave D is read-only and the dispatcher runs it. Every wave opens with its own Task 0,
  and any Task 0 can end its wave. No RUNBOOK: the repository's packs carry none (one pre-cut
  runbook exists, 2026-09-20), and each wave's Implementation is its ordered procedure.
- Authored 2026-10-14 (EDT; 2026-10-15 UTC) by the dispatcher seat `air` on the operator's
  word: "lets make a task pack to build those improvements to this system. We also want to fold
  in an automated worktree launching system if possible." The improvements are the five the
  dispatcher listed the same evening after measuring the system; the fifth (mail hygiene) is
  folded into Wave A.
- Boundary with `TP-700`: that roadmap's W1 (`TP-700a`, the headless runner) needs an occupancy
  oracle and a seat-to-worktree resolver before it launches anything (its W1 sketch, item 2).
  Wave B here builds both as `tools/cc/seat.py`, which `TP-700a` consumes. `TP-700d` (the
  mechanical completion audit of the runner's own lanes) is the forward twin of Wave D's
  retrospective one; neither replaces the other.
- Ledger: one row, `DEF-4020` (§C0, filed 2026-10-14 from the dispatcher's block at authoring),
  for the liveness defect Wave B-4 fixes; it names this pack as its fix home, and the pack is
  ledger-tracked through it (the completeness contract requires every active pack to be cited by
  a row). Wave A closes one dispatcher-book item in place (the board's `UNSTABLE` wording, note
  `5f2ef0`); Wave B closes the protocol's one open item (a worktree seat's name outlives its
  worktree). Rows this pack touches but does not close are listed under Reach.

## Motivation

The seat system was built and measured over 2026-10-10 to 10-14 by the dispatcher seat. The
measurements that prompt this pack, all taken 2026-10-14 evening EDT and re-runnable by the
commands named (see Wave C for the two that have no instrument yet):

- **What the merges were for.** Of the 53 pull requests merged 2026-10-10 to 10-14 (derive:
  `gh pr list --state merged --limit 60 --json number,headRefName,mergedAt`, classified by lane
  name), 23 built the seat system and its records, 15 were record-only rows and folds, 15 were
  harness fixes for users. Ledger strikes per day fell from about 22 (10-06 to 10-10, from the
  rows' `CLOSED` dates) to 7, 3 and 6 on 10-12 to 10-14; live rows went 274 to 281 across
  10-14. The operator's reading: "the fact the ledger has only slightly gone up is very good".
- **The dispatcher split met its pre-registered metric** (worker request to first ack under an
  hour): 21 requests before 2026-10-12 19Z, median 268 min, p75 722 min; 19 since, median 6
  min, p75 8 min, max 16 min. Measured by an ad-hoc script over every mail ref; the operator
  was present throughout, and no overnight has run under the worker loop. There is no
  instrument for this figure (Wave C).
- **The channel carried 143 messages on 10-14** against 50 to 70 a day before. Most of the
  dispatcher's day is mail, and two of its reads tonight were done by hand: which seats are
  alive, and which requests are unanswered.
- **Launching a seat is a hand procedure and it failed twice in two days.** 2026-10-13: the
  Mac launch line lost both `$` signs in transit and zsh ran `work` as a command. 2026-10-15
  02:00Z: the `win-2` relaunch landed in the Windows main checkout beside `win`'s session (win's
  request `01a529`); two sessions shared one tree, index and inbox cursor for six minutes, and
  only a seat reading its banner's `Sessions:` line before its first edit caught it. Core Rule 15
  forbids the state; nothing refuses it.
- **The banner's own liveness is age, not life.** `tools/cc/hooks/_hook_utils.py::other_live_sessions`
  counts a marker touched within `SESSION_MARKER_LIVE_S` (4 h) as live. Tonight's dispatcher
  banner named "1 other session" whose recorded pid (96794) was dead, and win-2's banner did the
  same in its worktree at 02:32Z (its previous window, pid 32168, gone; note `e07a7b`): two
  hosts, one night. The stronger oracle, Claude Code's own session registry read by
  `tools/cc/checkout_sync.py::live_sessions` with `pid_alive`, already exists for worktree
  removal and is used by nothing else.
- **Two instruments are stale or missing.** `scripts/ledger_trend.py` printed its last step for
  2026-09-21 while the `record` ref's last snapshot is 2026-10-14 17:50 (measured tonight); the
  request-to-ack latency has no script at all. `scripts/merge_cost_census.py` works and is
  `TP-479a` Wave D's instrument; 6 of its 30 post-fold merges have landed.
- **The channel's cap bit the dispatcher.** An assign of 2,083 characters was refused by the
  2,000 cap at the dry run (`tools/cc/mail.py::MAX_TEXT`), costing a round trip; every long
  body goes through a shell string today.
- **Nothing has audited the merged work against the manual standard.** The 2026-10-13 decision
  record (auto-memory, "worker seats run a fail-safe loop") names a completion audit of merged
  pull requests as the precondition for going unattended; 53 have merged since without one.

## Scope (in)

- **Wave A — the board sees seats and asks; mail takes a body from a file.** Two board lines
  (`seats:`, `asks:`), the `Mail:` banner line's unanswered-asks count on the dispatcher's clone,
  the `UNSTABLE` wording fixed in place, `mail.py send --text-file`. Files: `tools/cc/board.py`,
  `tools/cc/mail.py`, `tools/cc/hooks/session_start.py`, `.claude/commands/inbox.md`,
  `tests/test_board.py`, `tests/test_mail.py`, `tests/test_session_banner.py`.
- **Wave B — the seat driver and one liveness oracle.** `tools/cc/seat.py` (`list`, `launch`,
  `retire`), the occupancy refusal in `ship.py preflight`, pid liveness in the `Sessions:` line,
  an `Orders:` banner line for a worker seat, the protocol's open item closed. Files:
  `tools/cc/seat.py`, `tools/cc/checkout_sync.py`, `tools/cc/ship.py`,
  `tools/cc/hooks/_hook_utils.py`, `tools/cc/hooks/session_start.py`, `tests/test_seat.py`,
  `tests/test_checkout_sync.py`, `tests/test_ship_driver.py`, `tests/test_session_banner.py`,
  `tests/test_hooks_worktree_checkouts.py`, `memory/parallel-work-protocol.md`,
  `docs/HOOK_ASSUMPTIONS.md`, `docs/HOOKS.md`, `CLAUDE.md`.
- **Wave C — the metrics as instruments.** `scripts/mail_latency_census.py` new;
  `scripts/ledger_trend.py` repinned to the folded records; the merge-cost census left as it is
  and its Wave D date recorded. Files: `scripts/mail_latency_census.py`,
  `tests/test_mail_latency_census.py`, `scripts/ledger_trend.py`.
- **Wave D — the retrospective completion audit.** Read-only: every code-touching pull request
  merged since the seat system's first lane, graded against the manual standard by a
  pre-registered rubric; a report and rows for the gaps nobody is assigned to fix. Files:
  `reports/completion-audit-2026-10.md`.

## Scope (out)

- **The headless runner** (`TP-700`'s W1). Wave B hands it `seat.py`'s occupancy oracle and
  resolver; the runner itself, its `after:` field and night board (W4), follow-through (W2) and
  mechanical completion audit (W3) stay in `TP-700`, whose lettered child packs do not exist yet
  and so are not named here.
- **Windows retire-on-clear** (`TP-479` Wave B-4) and **generated files in parity under the
  contract tier** (Wave B-5). Separate mechanisms with their own Task 0s already written.
- **A `/seat` slash command.** A launch starts a new Claude Code window, which no slash command
  can do; the in-session verbs (`list`, `retire`) are documented in the `/inbox` body instead,
  which also keeps `EXPECTED_COMMAND_COUNT` and the command-count fan-out
  (`espalier/surface_impact.py`) untouched.
- **Retiring `scripts/launch.sh`.** It serves a lone self-host operator with no seats and asks
  the three posture questions; `seat.py launch` passes posture through rather than asking.
  Revisit after Wave B's pilot has run a week; a second launcher is cheaper than a wrong merge.
- **`DEF-861`** (a second SessionStart in one checkout demotes the running session's blueprint
  node). Wave B prevents the second session when the launch goes through the driver; a hand
  launch still reaches the defect, and the hook-side fix is that row's.
- **The worktree-goal row** (a worktree seat reads the main checkout's goal; its id is in
  Reach, not here, because a row named in this section cannot be struck while the pack is
  active and Wave B may strike it). Adjacent; the driver does not create a seat's `cc/GOAL.md`.
  Re-read the row at Wave B's Task 0: air-work runs with its own gitignored goal today.
- **The two live-tree-walk rows** (tests and engine walks reading a sibling seat's worktree;
  ids in Reach for the same reason). The class is win's `lane/contract-walk-tracked-set`
  (assign `1ed9bb`) and the engine walks' own rows; this pack must not hold their strikes.
- **Changing `SESSION_MARKER_LIVE_S`.** Wave B adds pid liveness beside the age window; it does
  not shorten the window, which also covers a sibling whose marker is a different host's file.
- **Shipping the protocol prose to adopters.** `memory/parallel-work-protocol.md` stays
  self-host; what adopters need to run seats goes in the seeded carriers Wave A's Task 0 names
  (the `/inbox` and `/ship` bodies, `docs/WORKFLOW.md`), under the deployed-text audience gate.

## Task 0 — Verify (per wave; each can end its wave)

The pack has four Task 0s because the four waves can be killed separately. Each names the
oracle, the refuting result and the exit. The default exit is stop and re-raise to the
dispatcher, never adjust and continue.

**A-0 (board).**
1. *Oracle:* `grep -nE 'def (live_requests|unanswered|read_seats|read_asks)' tools/cc/*.py`.
   *Refuting result:* a reader of unanswered requests or of seat liveness already exists (read
   2026-10-14: `tools/cc/mail.py` defines `live_claims`, `lane_seats`, `live_assignments` and no
   request reader). *Exit:* wire the board to it and drop the duplicate from this wave.
2. *Oracle:* over every mail ref, each `type == "ack"` message's `ack` field names a `request`.
   `python - <<'EOF'` reading `git show refs/remotes/origin/mail/<m>:mail.jsonl` for each ref
   and `refs/heads/mail/<own>`, counting acks whose target is not a request. *Refuting result:*
   acks also answer notes or claims in the live record, so "a request with no ack" is not the
   pairing. *Exit:* pair on `ack` plus the target's type, and say so on the line.
3. *Oracle:* `gh pr view <n> --json mergeStateStatus,statusCheckRollup` on a pull request whose
   only non-green check is still running. *Refuting result:* GitHub reports a state other than
   `UNSTABLE`. *Exit:* keep `_pr_line`'s wording and strike the book item as refuted. (The book
   row `5f2ef0`, 2026-10-14, read `UNSTABLE` with a pending optional cell; re-measure, do not
   trust it.)
4. *Oracle:* `grep -rn 'board\.py --json\|"jobs"\|"claims"' tests/test_board.py tools/cc/ scripts/ task-packs/TP-700*.md`.
   *Refuting result:* a reader pins the JSON's key set exactly. *Exit:* extend that pin in the
   same lane before adding keys.
5. *Oracle:* which seeded carriers tell an adopter about seats: `grep -rln 'seat\|dispatcher\|/inbox' espalier/assets/docs/ espalier/assets/claude/commands/`.
   *Refuting result:* none does. *Exit:* that is the finding, not a stop: Wave A adds the
   seats section to the carrier the grep shows nearest (expected `docs/WORKFLOW.md` and the
   `/inbox` body), under the audience gate.

**B-0 (seat driver).**
1. *Oracle:* `claude --help | grep -A2 -- '--worktree'` on this box's CLI, then one drive in a
   scratch clone: `claude --worktree tp701-probe -p 'reply with the single word PONG'` followed
   by `git worktree list`, and a second drive with the same name. *Refuting result:* `--worktree`
   does not enter an existing worktree by name, or does not create one under
   `.claude/worktrees/`. *Exit:* the driver resolves and creates the worktree itself with `git
   worktree add` and runs `claude` with the worktree as cwd; `--worktree` is not used.
2. *Oracle:* `python -c "import sys; sys.path.insert(0,'tools/cc'); import checkout_sync as c; print(c.live_sessions())"`
   from this checkout while this session runs. *Refuting result:* `None` (the registry cannot be
   read in full; `docs/HOOK_ASSUMPTIONS.md` Assumption 6 says it is undocumented upstream) or a
   list that omits this session. *Exit:* the occupancy check cannot tell, and the driver gains
   the fallback (the target's `.espalier-state/sessions/*.json` markers with `pid_alive`); if
   neither oracle places this session, stop: a launcher that cannot see occupancy is the hand
   procedure with a new name.
3. *Oracle:* on this Mac, `/loop 1m echo tick` then `/clear` in a scratch session; does the tick
   fire after the clear. *Refuting result:* it does. *Exit:* none; the result decides whether the
   relaunch procedure keeps the second paste. (The 2026-10-13 record calls this unverified.)
4. *Oracle:* `python tools/cc/mail.py claims --no-fetch` from a worktree seat and from its clone;
   does a release sent from the clone close a claim the worktree seat made. *Refuting result:*
   it does already. *Exit:* `retire` needs no `--as`; drop B-3's mail change.

**C-0 (instruments).**
1. *Oracle:* `python scripts/ledger_trend.py --since 2026-10-01` on this repository.
   *Refuting result:* it prints steps through 2026-10-14. *Exit:* the trend half of Wave C is
   dropped; only the latency census is built. (Measured 2026-10-14: the default run's last step
   is 2026-09-21; `git log -1 record` is 2026-10-14 17:50.)
2. *Oracle:* the ad-hoc latency figures above re-derived by the new script on the same refs.
   *Refuting result:* the script cannot reproduce n=21 / 268 / 722 and n=19 / 6 / 8 from the
   refs as of 2026-10-15 02:20Z (a fixture of those refs is frozen at Wave C's start). *Exit:*
   the pairing rule is wrong; fix the script, never the figures.

**D-0 (audit).**
1. *Oracle:* `gh pr view <n> --json body` for three merged pull requests, one per seat.
   *Refuting result:* the bodies carry no procedure evidence (reviewers, the red, the tier) and
   the evidence lives only in mail notes. *Exit:* the audit reads the mail refs beside the
   bodies, and the finding "the evidence has no readable home in the pull request" is the
   first row.
2. *Oracle:* the rubric's five terms resolve to the procedure that names them:
   `.claude/commands/implement-task.md` steps 6 and 7 (the review before the one run, the proof
   tier once), the ship driver's landing check, the worker tick (both reviewers on a snapshot
   clone, the red named). *Refuting result:* a term has no home. *Exit:* drop that term; the
   rubric measures only what the standard states.

## Relevant memory

Recent pattern, measured: every incident that motivates this pack was caught by a person or a
seat reading text, not by a gate. The stale board count was found by diffing ids by hand; the
two-sessions state by a seat reading its banner; the dead-marker sibling by the dispatcher
checking pids; the unanswered request by an ad-hoc census. Four reads, zero refusals.

| Entry | Where |
|---|---|
| Parallel work protocol | `memory/parallel-work-protocol.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| The worktrees of one clone share its machine name, so the claims pre-flight hides a sibling's claims | `docs/SHARP_EDGES.md` (section of that title) |
| Spawned agents share one worktree + index — isolate mutate-capable fan-outs | `docs/SHARP_EDGES.md` (section of that title) |
| The live working-summary doc is last-writer-wins under parallel sessions | `docs/SHARP_EDGES.md` (section of that title) |
| Hook Assumptions, Assumption 6 (the session registry is undocumented upstream) | `docs/HOOK_ASSUMPTIONS.md` |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |

Resolved at authoring time by `python tools/cc/hooks/_recall.py "worktree seat launch and one
session per checkout"` and `... "board and mail channel dispatcher assignments claims"`; re-run
them rather than trusting this list if the pack has been sitting.

## Implementation

Every fix below is a **fix shape (untested)** unless marked driven; its refutation is named.

### Wave A — the board sees seats and asks (`lane/board-seats-and-asks`)

**A-1 `asks:`.** `tools/cc/mail.py` gains `live_requests(by_machine)`: every `request` from any
machine with no `ack` message whose `ack` field names its id, oldest first, each with its age.
`tools/cc/board.py::collect` adds the list under an `asks` key and `::render` prints one line:
count, then each as `<id suffix> <from> <lane or ->: <age>`, capped like the jobs section with
"and N more". The dispatcher's clone (`espalier.toml` `dispatcher`, read by
`mail.py::dispatcher_setting`) also gets the count on the banner's `Mail:` line
(`tools/cc/hooks/session_start.py::_mail_line`): "N unanswered asks, oldest <age>".
*Refuted if* A-0 item 2 shows acks answer non-requests; then the pairing reads the target's type.
*Earn the red:* a `by_machine` fixture (the `_stub_channel` shape in `tests/test_board.py`) with
one request and no ack must list it; the same with an ack naming it must not. *Mutation to die
to:* drop the ack pairing and the answered request appears.

**A-2 `seats:`.** `board.py::collect` adds a `seats` list: one row per machine that has a mail
ref (`mail.py::local_mail_machines`), with its last message's type and age, and for this clone
and its worktrees the live sessions from `checkout_sync.live_sessions()` grouped by cwd, each
cwd named as its seat (`mail.py::worktree_seat_name` for a worktree directory; the clone's name
for the main checkout). A cwd holding two or more live sessions is flagged on the line as the
Core Rule 15 state. A remote seat's row says "last mail <age>", never live or dead: the channel
is the only thing the board can read about another machine. *Refuted if* B-0 item 2 shows the
registry unreadable here; then the local half reads the session markers with `pid_alive` and
says "by markers". *Earn the red:* a fake registry directory (two entries, one cwd, both pids
this process's) must flag; one entry must not. *Mutation:* drop the cwd grouping and two
sessions in one checkout read as two seats.

**A-3 the `UNSTABLE` wording.** `board.py::_pr_line` renders `mergeStateStatus == "UNSTABLE"`
through the `MERGE_STATES` table as "ready; an optional check is red". If A-0 item 3 holds, the
entry reads as below; the test that pins the mapping changes with it. *Fix (one string; driven
only once A-0 item 3 has measured the state):*

```python target=tools/cc/board.py
MERGE_STATES: dict[str, str] = {
    "CLEAN": "ready",
    "HAS_HOOKS": "ready",
    "UNSTABLE": "ready; an optional check is red or still running",
    "BEHIND": "behind the base (holds only under the up-to-date rule)",
    "BLOCKED": "blocked: a required check or a review holds it",
    "DIRTY": "CONFLICTS with the base: its seat runs `python tools/cc/ship.py catch-up`",
    "DRAFT": "draft",
}
```

**A-4 `--text-file`.** `mail.py::build_parser`'s `send` takes `--text-file PATH` (UTF-8, the
whole file, mutually exclusive with `--text`); the dry run prints the body's character count
beside the line it would send. The cap and its refusal are unchanged.

**A-5 the carriers.** The `/inbox` body (`.claude/commands/inbox.md`, Step 2c) documents both
lines; `python scripts/sync_claude_mirrors.py` after. The seeded carrier A-0 item 5 names gains
a short seats section (what a seat is, the board, the two lines), worded under the audience gate
(no self-host path, no dated measurement). `python scripts/sync_vendor_cc.py` after the
`tools/cc` edits. `memory/parallel-work-protocol.md` "What the dispatcher does" gains the two
lines as the dispatcher's first read.

*Checkpoint:* `python tools/cc/board.py --json | python -c "import json,sys; d=json.load(sys.stdin); print(sorted(d))"`
lists `asks` and `seats`; `pytest -q tests/test_board.py tests/test_mail.py tests/test_session_banner.py`;
the two sync scripts report clean; `python scripts/proof_tier.py --base origin/main` names the
tier (a hook edit earns the full tier).

### Wave B — the seat driver and one liveness oracle (`lane/seat-driver`)

**B-1 one oracle for "is a session live here".** A helper in `tools/cc/checkout_sync.py` (beside
`live_sessions` and `own_entry`): `sessions_in(path)` returns the registry's live entries whose
cwd is under `path`, or `None` when the registry cannot be read in full. Used by B-2, B-4 and
B-5, and offered to `TP-700a`'s W1 item 2. *Refuted if* B-0 item 2 shows the registry does not
list this session on this host; then the helper also reads the target's session markers with
`pid_alive`, and reports which oracle answered.

**B-2 `tools/cc/seat.py`** (deployed; stdlib and git; imports its siblings `mail` and
`checkout_sync` by path as `board.py` does). Three verbs:

- `list`: the clone's name (`mail.py::clone_machine`), then each `.claude/worktrees/<dir>`: its
  seat name from the per-worktree config, its branch and head, its live sessions (B-1), its live
  claims and jobs from the local mail refs (`mail.py::live_claims`, `::live_assignments`), and
  whether `checkout_sync`'s removal rules would let it go.
- `launch <seat> [--maintenance] [--print] [-- <claude args>]`: resolve `<seat>` to the clone
  (its own name) or to `.claude/worktrees/<dir>` where `worktree_seat_name(clone, dir)` equals
  it; create the worktree from `origin/<base>` when absent (the git form, or `--worktree` per
  B-0 item 1); name it before launch (`mail.py::name_this_worktree`); refuse when B-1 finds a
  live session in the target, naming its pid and start time, and when B-1 cannot tell, refuse
  unless `--unchecked`; set `ESPALIER_MAINTENANCE_MODE=1` only with `--maintenance`; put the
  seat's own interpreter first on `PATH` when `<worktree>/.venv` exists and otherwise print the
  Engine line's warning (a worktree's children import the main checkout's engine, measured
  2026-10-12); then run `claude` with the target as cwd and the operator's args after `--`
  passed through unchanged, or with `--print` print the one command line and exit. The driver
  adds no permission flag of its own.
- `retire <seat>`: from the clone, release every live claim and job the seat holds on the
  channel, then remove its worktree by `checkout_sync`'s rules (clean, merged, no live session,
  no live claim). The release is the protocol's open item: a worktree seat's name outlives its
  worktree and only that name can release its claims today. *Fix shape (untested), two options
  B-0 item 4 decides between:* (a) `retire` sends the release from inside the worktree before
  removing it, and refuses to remove a worktree whose seat still holds a claim it cannot send
  from; (b) `mail.py send` gains `--as <seat>` accepted only for a `release` and only when
  `<seat>` is `<this clone>-<dir>`, a name this clone minted. *Refuted if* the channel's
  one-writer rule (compare-and-swap per machine ref) cannot hold for a name whose worktree is
  gone; then (a) only, and a gone worktree's claims are released by hand with the recipe written
  into the `/inbox` body.

*Earn the red, per verb:* `launch` with a fake registry whose entry's cwd is the target and pid
is this process must refuse; with a dead pid it must proceed to the print. `retire` on a scratch
channel (the `tests/test_mail.py` origin fixture) must close the seat's claim so `claims` no
longer lists it. *Mutation:* remove the cwd comparison in B-1 and `launch` proceeds into an
occupied checkout.

**B-3 the push refuses the Core Rule 15 state.** `tools/cc/ship.py::preflight` (the gate `open`
and `handoff` run first) adds B-1's read of the current checkout: two or more live sessions in
it is a refusal that names them; a registry that cannot tell is a warning, not a refusal (the
push is reversible; a false refusal under an unreadable registry would stop every seat at once).
*Refuted if* `preflight` runs where the registry never lists the caller (a `-p` run under
`TP-700a`); then the runner passes `--occupancy-checked` after its own B-1 read.

**B-4 the `Sessions:` line reads life, not age alone** (row `DEF-4020`). `_hook_utils.other_live_sessions`
keeps the age window and adds `alive`: `checkout_sync.pid_alive` on the recorded pid when the
marker's cwd is this host's (None when it cannot tell). `session_start._sessions_line` leaves
out a row whose `alive is False` and says "(pid gone)" for it only under a debug flag. *Earn the
red:* a marker with a dead pid touched a minute ago must not be named; the row's probe is that
marker (it prints 1 while open), so strike `DEF-4020` in-lane when the probe reads 0.
*Mutation:* ignore `alive` and tonight's banner reappears.

**B-5 the `Orders:` banner line.** On a clone whose `espalier.toml` names a dispatcher that is
not this seat, and whose local mail refs hold live assigns for this seat, SessionStart prints
one line: the seat name, the count of its jobs with the first lane, its unread mail count, and
the two commands to run first (`/inbox`, `/inbox board`), then "worker tick: see the protocol"
(self-host) or the seeded carrier's section (adopter). Reporter only, bounded under the existing
mail budget (`_mail_line`'s deadline). *Hypothesis, to be driven in the pilot:* with this line the
operator's first paste shrinks to one word, and if B-0 item 3 shows `/loop` survives `/clear`
the second paste goes too.

**B-6 the records.** `memory/parallel-work-protocol.md`: "What a worker seat does" gains the
launch procedure (one command, the banner check), item 5's open bullet is rewritten as closed by
`retire`; `docs/HOOK_ASSUMPTIONS.md` Assumption 6 names the driver as a second reader of the
registry; `docs/HOOKS.md` and the root `CLAUDE.md` hooks table gain the `Orders:` line in the
SessionStart row; `task-packs/TP-700-seat-runner-fresh-session-per-lane.md` W1 item 2 gains one
sentence naming `seat.py`'s oracle. Both sync scripts after.

*Checkpoint:* `python tools/cc/seat.py list` names this clone and its worktrees;
`python tools/cc/seat.py launch <this seat> --print` refuses (this session occupies it);
`pytest -q tests/test_seat.py tests/test_checkout_sync.py tests/test_ship_driver.py tests/test_session_banner.py tests/test_hooks_worktree_checkouts.py`;
the full tier (a hook edit).

### Wave C — the metrics as instruments (`lane/seat-metrics`, self-host)

**C-1 `scripts/mail_latency_census.py`.** Reads every `refs/remotes/origin/mail/*` and this
clone's own ref, pairs each worker `request` with the first `ack` naming it, and prints per
window (`--since`, `--until`, or the dispatcher split's date as a named preset) the count,
median, p75, max and the unanswered list with ages; `--json` the same as data. The authoring
figures above are its first fixture (`tests/fixtures/mail_latency/`, frozen from the refs at
Wave C's start), and the test pins them. *Mutation:* pair on the ack's own time order instead of
the `ack` field and the figures move.

**C-2 `scripts/ledger_trend.py` reads the fold.** C-0 item 1 decides the cause; the expected
shape (untested): the default `--path` names the pre-fold ledger file, and `snapshots` stops at
the first snapshot where the rows live under `task-packs/ledger.d/` instead. The fix reads
`_row_files_at` for that directory when the file is absent, so one run prints the window from
the first snapshot to the last, with the fold as one step. *Pass:* the run reproduces the
per-day strikes above for 10-12 to 10-14 (7, 3, 6) within the snapshot cadence.

**C-3 `TP-479a` Wave D's date.** No code. The pack records that the 30-merge window after `#215`
is 6 merges in at authoring, and that the dispatcher runs
`python scripts/merge_cost_census.py --prs 30 catch-ups conflicts` when `gh pr list --state merged`
shows 30 merged after it; the result goes to `TP-479a`'s Landing, not here.

*Checkpoint:* `pytest -q tests/test_mail_latency_census.py tests/test_ledger_trend.py` (the
second exists if a test file for the trend script does; else the census test alone and one
driven run recorded in Landing); the contract slice.

### Wave D — the retrospective completion audit (`lane/completion-audit-2026-10`, read-only)

**D-1 the population.** `gh pr list --state merged --limit 100 --json number,headRefName,mergedAt,body --search "merged:>=2026-10-10"`,
less the record-only lanes (a lane whose diff touches only `memory/`, `cc/`, `task-packs/` and
`docs/`: derive by `gh pr view <n> --json files`, never by title).

**D-2 the rubric, pre-registered here.** For each pull request: (1) both reviewers named with a
verdict each (the code reviewer and the failure-mode reviewer, on a snapshot clone); (2) a red
earned and the mutation named; (3) the tier receipt with `--base`; (4) the landing check's
result; (5) a claim and its release on the channel for the lane. Each criterion is met, not met,
or not applicable with a reason (a docs row has no red to earn). The figure reported is the
share met per criterion over the population, by seat, with the pull requests missing each
listed by number. No threshold is set here: the operator reads the figure and decides `TP-700`
W1's gate.

**D-3 the method.** Agent fan-out by the dispatcher (read-only; the memory on fan-out mechanics
applies: a snapshot, no git writes), one agent per seat's pull requests, a refute pass on every
"not met" by reading the mail refs for the same lane (the evidence may live in a note). The
report lands as `reports/completion-audit-2026-10.md` with the deriving commands at its head.
Rows are filed only for gaps no seat is assigned to fix (protocol item 8); a gap in the ship
driver's body template is one row, not fifty.

*Checkpoint:* the report exists, every "not met" carries the refute pass's verdict, and the
numbers in it come from the commands at its head.

## Affected symbols

`/scope-check` keys on bare names. `collect`, `render`, `build_parser`, `preflight`,
`release_lane` and `snapshots` collide across the tree (the agents' and commands' bodies name
`/preflight`; every CLI has a `build_parser`), so its gap list at authoring was collisions, not
files this pack misses; re-run it at each wave's start rather than trusting this list, and
accept the collision gap by name. No `main` is declared: it has thousands of references.

### Changed-semantics
- `tools/cc/board.py::collect` (two new keys, `asks` and `seats`)
- `tools/cc/board.py::render` (two new lines)
- `tools/cc/board.py::_pr_line` (the `UNSTABLE` wording, if A-0 item 3 holds)
- `tools/cc/mail.py::build_parser` (`send --text-file`; `--as` only if B-0 item 4 takes option b)
- `tools/cc/mail.py::release_lane` (called by `seat.py retire`)
- `tools/cc/checkout_sync.py::live_sessions` (unchanged body; a new sibling helper reads it)
- `tools/cc/hooks/_hook_utils.py::other_live_sessions` (an `alive` field)
- `tools/cc/hooks/session_start.py::_sessions_line` (reads `alive`)
- `tools/cc/hooks/session_start.py::_mail_line` (the unanswered-asks count on the dispatcher's clone)
- `tools/cc/ship.py::preflight` (the occupancy refusal)
- `scripts/ledger_trend.py::snapshots` (reads the folded row directory; the default path
  covers both layouts)

### Renamed
- None.

### Added-paths
- `tools/cc/seat.py`
- `tests/test_seat.py`
- `scripts/mail_latency_census.py`
- `tests/test_mail_latency_census.py`
- `tests/fixtures/mail_latency/`
- `reports/completion-audit-2026-10.md`

### Removed-paths
- None.

## Reach

Not a class pack: it closes no ledger class and mints no row. The rows and items it touches,
so no later pass reads them as shut:

Members derived by: `grep -lE 'seat|worktree|board\.py|mail\.py|Sessions' task-packs/ledger.d/*.md`
over live rows (112 rows name one of these surfaces, read 2026-10-14; the five below are the
ones whose mechanism this pack's waves touch).

| Item | Status | Evidence |
|---|---|---|
| `DEF-4020` (the `Sessions:` line names a dead window live) | **CLOSED by B-4** when the `alive` field lands and the row is struck in-lane | its probe reads 0 |
| Protocol item 5, "a worktree's seat name outlives the worktree" | **CLOSED by B-2** when `retire` lands and its test shows the claim gone | the `claims` read after `retire` |
| Dispatcher-book item `5f2ef0` (board reads `UNSTABLE` as red) | **CLOSED by A-3** if A-0 item 3 holds, else **REFUTED and struck** | the `gh pr view` read |
| `DEF-861` | **NOT REACHED** | prevented only when the launch goes through `seat.py`; the hook-side demotion is untouched |
| `DEF-1136` | **NOT REACHED** | adjacent; re-read at B-0 for a strike |
| `DEF-2005`, `DEF-3000` | **NOT REACHED** | the walk class is win's `lane/contract-walk-tracked-set` and the engine rows |
| `DEF-645` | **NOT REACHED** | `TP-700`'s row; Wave D audits merged work, not the driver's sentinel |

## Pass criteria

- `python tools/cc/board.py --json` carries `asks` and `seats`; `python tools/cc/board.py`
  prints both lines; no existing board test's assertion is weakened and no fixture removed.
- Earn-the-red recorded per fix against the mutation named in its wave; a test that only ever
  passed does not count.
- `python tools/cc/seat.py launch <occupied seat> --print` refuses and names the session;
  `python tools/cc/seat.py retire <seat>` on a scratch channel leaves `mail.py claims` empty for
  that seat.
- A session marker whose recorded pid is dead on this host is not named on the `Sessions:` line.
- `ship.py preflight` refuses from a checkout with two live sessions in the test with a fake
  registry, and warns, never refuses, when the registry returns `None`.
- `python scripts/sync_claude_mirrors.py` and `python scripts/sync_vendor_cc.py` report clean
  after each wave that touches their sources; the audience gate passes on every deployed body
  the pack edits.
- `python scripts/mail_latency_census.py --json` reproduces the frozen fixture's figures;
  `python scripts/ledger_trend.py` prints a step dated after 2026-10-01 on this repository.
- Wave D's report exists with the deriving commands at its head and a refute verdict on every
  "not met".
- The tier each lane earns is run with `--base origin/main` and its receipt is in the pull
  request body; a hook edit (Waves A and B) earns the full tier.
- No criterion here licenses shipping a defect in the gate the pack delivers: a refusal in
  `seat.py launch` or `ship.py preflight` that can be passed by an unreadable registry is a
  defect of this pack, not a scope-out.

## Files touched

**New:** `tools/cc/seat.py`; `tests/test_seat.py`; `scripts/mail_latency_census.py`;
`tests/test_mail_latency_census.py`; `tests/fixtures/mail_latency/` (frozen refs);
`reports/completion-audit-2026-10.md`.

**Modified:** `tools/cc/board.py`; `tools/cc/mail.py`; `tools/cc/checkout_sync.py`;
`tools/cc/ship.py`; `tools/cc/hooks/_hook_utils.py`; `tools/cc/hooks/session_start.py`;
`espalier/_vendor/cc/` (by `sync_vendor_cc.py` only); `.claude/commands/inbox.md` and its two
mirrors (by `sync_claude_mirrors.py` only); `docs/WORKFLOW.md` or the carrier A-0 item 5 names;
`docs/HOOKS.md`; `docs/HOOK_ASSUMPTIONS.md`; `CLAUDE.md` (the SessionStart row);
`memory/parallel-work-protocol.md`; `scripts/ledger_trend.py`;
`task-packs/TP-700-seat-runner-fresh-session-per-lane.md` (one sentence);
`tests/test_board.py`; `tests/test_mail.py`; `tests/test_checkout_sync.py`;
`tests/test_ship_driver.py`; `tests/test_session_banner.py`; `tests/test_hooks_worktree_checkouts.py`.

**Deleted:** none.

**Unmodified on purpose:** `scripts/launch.sh` (Scope out); `scripts/merge_cost_census.py`
(C-3); `tools/cc/hooks/_hook_utils.py::SESSION_MARKER_LIVE_S` (Scope out);
`tests/_surface_expected.py` (no new command); `scripts/run_pack_chain.sh` (`TP-700`'s).

## Sub-task ordering

1. **A-0, then Wave A** (smallest; the dispatcher's daily instrument). Checkpoint: the board's
   two lines on this repository, the tests, the syncs, the tier.
2. **B-0, then Wave B** (the heavy wave; after Wave A merges, since B-5 reads A-1's reader).
   B-1 first, then B-2 `list`, `launch`, `retire`, then B-3, B-4, B-5, B-6. Checkpoint per verb.
3. **C-0, then Wave C**, by whichever seat is idle or the dispatcher; it depends on nothing.
4. **D-0, then Wave D**, by the dispatcher, at any time; its report is read before `TP-700a` is
   assigned.
5. **Red-team each wave** before its tier: both reviewers on a snapshot clone, one fix batch.
   What this pack most likely got wrong, for the pass to bite on: B-1's two oracles disagreeing
   on a host where the registry lists a session the markers do not (a `-p` run), and A-2 naming a
   remote seat's state in words the channel cannot support.
6. **Landing** per wave in this file's stanza; Wave D's figure also goes to the operator's
   decision on `TP-700` W1.

## Estimated effort

Pack budgets on this repository have run about 2.7 times over on one measured pack
(`TP-459`); read these as the author's guess, not a schedule.

| Wave | Build | Red-team and tier | Notes |
|---|---|---|---|
| A | 3 to 4 h | 1 h plus the full tier | five small edits across three files and two carriers |
| B | 6 to 8 h | 2 h plus the full tier | three verbs, two gates, one banner line, the records |
| C | 2 to 3 h | 0.5 h plus the contract slice | one script new, one repinned |
| D | 2 to 3 h agent time, 1 h dispatcher | the refute pass is the red-team | read-only |
| Total | 13 to 18 h | 4 h | expect the measured overrun |

## Landing
- State: DRAFT
- Commits:
- Suite:
- Earn-the-red: per wave, against the mutation its Implementation names
- Red-team: per wave; authoring review not yet run
- Reach: see Reach; no row closed at authoring
- Wave D: DONE 2026-10-15 (01:50 EDT), read-only, by the dispatcher seat with eight Opus agents (one
  finder per seat on the pull request bodies, one refuter per seat on the mail refs). Report
  `reports/completion-audit-2026-10.md` on the dispatcher's box (`reports/` is gitignored on this
  tree) with the deriving commands at its head. Population: 46 code pull requests of the 56 merged
  since 2026-10-10. Figure, the five terms in rubric order: the cohort merged from 2026-10-14 (the
  step-template bodies) 12/13, 13/13, 5/13, 11/13, 13/13; the cohort before it 4/31, 5/28, 2/33,
  0/33, 32/33; the mail refuted 1 of 127 "not met". Rows filed for the gaps no seat is assigned to:
  `DEF-4021` (the ship driver's default body is the commit subjects), `DEF-4022` (implement-task step
  7 shows no `--base` and no earned red), `DEF-4023` (no contract on a `tests/` import from the
  shipped roots). The figure goes to the operator's `TP-700` W1 decision.
- Date:
