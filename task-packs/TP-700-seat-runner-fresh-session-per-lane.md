# TP-700 — The seat runner: one fresh session per lane, gated by checks the session cannot write

## Status

- Version target: self-host tooling, no adopter release. The runner is dev-only like
  `scripts/run_pack_chain.sh` (`docs/AUTONOMOUS_EXECUTION.md` §1), never packaged.
- Type: workflow infrastructure. It joins the overnight driver's per-unit `claude -p` loop to the
  dispatch system's jobs, board and ship driver.
- **Kind: ROADMAP.** W0 is specified in full and can end the pack. W1 to W4 are sketches with
  their refutations; each becomes a lettered child pack written after W0 has measured, because
  W0's results decide W1's shape (just-in-time, not batch). Children in execution order:
  `TP-700a` (W1, runner core), `TP-700b` (W4, `after:` and the night board), `TP-700c` (W2,
  pull-request follow-through), `TP-700d` (W3, completion audit).
- Authored 2026-10-13 by the dispatcher seat `air` on the operator's word: "yes, draft the task
  pack", after the operator chose option C of three in the same conversation. Revised the same day
  on an independent cold review (request changes: five high, seven medium), every finding folded in.
- Ledger: `DEF-645` cites this pack as related (it re-checks dispatch in its own runner; the
  driver's single sentinel is left as it is). A row of this pack's own, if one is needed, is filed
  after `#207` merges, in the fragment format it introduces; no DEF id is minted from the `air`
  block until then.

## Motivation

**The operator's rule, verbatim (2026-10-13):** "starting the pipeline off completally fail safe,
so like 'active on total green, defer to pause and wait, no matter how long, if there is a real
issue'... If the pipeline gets to a stuck point, it just stops until i come back."

**The last unattended run, as the operator described it (2026-10-13):** "the pipeline ran, the
tasks were done in external context, but many instructions were not run... [it] ran the red team
on a few of the first issues, but then stopped running it altogther, skipping steps in implement
pack, skipping steps in packs altogther, and it just kept going, all through a massive prebuilt
task pack backlog". That is `docs/FAILURE_MODES.md` §11.14 (green but incomplete) and §11.15 (a
paraphrased command-goal skips the command's non-named steps).

**What was measured on 2026-10-13** (re-derive with
`python3 tools/cc/mail.py inbox --all --json`, filtered by `from`, `type` and `at`):
- Seats sat idle with work they could have done: win from 08:17Z (note `49fe4b`, its next job) to
  23:04Z (its claim on that job); air-work from 12:34Z (`#207`'s red, note `c89f72`) to 21:45Z;
  win-2 had no job until the 21:31Z assigns. Nothing woke a seat between jobs.
- The operator's interim fix (Stage 1) is a `/loop 10m` worker tick in each seat with a
  stop-and-ask rule. It keeps one long interactive session per seat, so every lane adds to one
  context. *Hypothesis, not measured:* a session cannot `/clear` itself from a scheduled prompt
  (`/clear` is a built-in command, not a skill), and long sessions drift in step-keeping as they
  compact, the §11.14 shape again.

**What exists to build from** (each re-derivable):
- `scripts/run_pack_chain.sh` (`wc -l`): one fresh `claude -p` per pack with
  `CLAUDE_BASE=( claude -p --permission-mode auto )`; gates in `preflight_chain`,
  `verify_dispatch_sentinel`, `verify_pack_receipt`, `verify_install_green`,
  `post_commit_verify_and_finalize`, and a resume ledger with a committed-but-ungated marker
  (`grep -n -E '^[a-z_]+\(\) *\{' scripts/run_pack_chain.sh`). It commits locally and never
  pushes: it predates pull requests and seats. Its known gaps are live rows: `DEF-644` (its
  durable state records a commit, not a landing) and `DEF-645` (one dispatch sentinel, then trust
  in the session's receipt).
- `tools/cc/mail.py::live_assignments` (jobs as data: `python3 tools/cc/mail.py assignments
  --json`, each with `re.lane`, `re.ids`, `re.seat`; a job's identity is `mail.py::_job_key`),
  `tools/cc/board.py::collect` (live state as data: `python3 tools/cc/board.py --json`, keys
  include `open_prs`, `post_merge`, `assignments`, `claims`), and `tools/cc/ship.py` (`open`,
  `rebind`, `catch-up`, `status`, `rerun`: `python3 tools/cc/ship.py --help`).
- **Missing:** an assign carries its prerequisite only in prose ("queued after #207 merges"), and
  a note can re-order or hold a job, which `live_assignments` never reads. Verified at review
  (`python3 tools/cc/mail.py assignments --no-fetch --json`): win's oldest live job was `DEF-4017`,
  held by note `49fe4b`, and win-2's oldest was `lane/sandbox-posture`, gated on an operator call.
  An oldest-first runner would have started both.

**The named user (§16):** the operator, who runs four seats on two machines and wants them busy
while present, then overnight once proven, without a lane landing that skipped the steps no test
checks.

## Scope (in)

- **W0 — Channel probes on both machines (Task 0, below).** Can end the pack.
- **W1 — Runner core** (`TP-700a`). One job at a time per seat, only jobs explicitly marked for the
  runner (W4); one fresh `claude -p` per lane; every check outside the session, read from events
  the CLI writes, never from text the model prints; the stop protocol on any miss. Portable
  Python, because two seats are Windows.
- **W4 — Dispatcher side** (`TP-700b`). An `after:` field on `assign` (a lane, `#N`, or `none`); the
  runner takes only a job carrying `after:` or listed on an operator-approved night board; the
  board shows runnable versus held. Lands before the runner runs any real lane.
- **W2 — Pull-request follow-through** (`TP-700c`). The runner, not a session, polls `ship.py
  status`; CONFLICTING runs `catch-up`; a red required check starts one fresh fix session, at most
  two per pull request, then the stop protocol. No session waits on CI (§7.9).
- **W3 — Completion audit** (`TP-700d`). Mechanical checks of the steps no suite runs, read from
  the session's event stream and from runs the runner itself makes. No real lane goes through the
  runner until W3 lands.
- **Stop protocol (all waves).** On a failed check, a second red, an unread board section, a red
  `post_merge`, a choice the assign does not settle, a refusal, or a conflict outside the lane's
  files: **first** write the stop file (in the clone's git directory, keyed by seat name, so no
  worktree cleanup can remove it), **then** send one `request` to the dispatcher with the facts.
  Only the operator clears a stop file. Waiting forever is a correct outcome.

## Scope (out)

- **Unattended overnight running.** Out until the supervised pilot (Pass criteria, last line)
  passes; the operator's word: "We dont need to run overnight untill its proven itself with me
  here."
- **Cross-machine live messaging, Remote Control, a watcher agent.** A session messages only
  sessions on its own machine (`ListAgents`, measured 2026-10-13: the Windows seats were not
  listed from the Mac); each seat's own runner or `/loop` already wakes it. Re-open only if W0 or
  the pilot shows a need.
- **Usage-window management.** The subscription window is not governable from here
  (`run_pack_chain.sh`'s comment on `--max-budget-usd`); a session cut short is a failed check and
  a stop.
- **Answering decisions.** Any choice an assign does not settle is the operator's; the runner
  never resolves one, and never stands in for an approval a command waits for (W0-H).
- **Adopter deployment.** Self-host only, like the driver it extends.
- **Changing `scripts/run_pack_chain.sh`.** It stays as the pack-chain tool, and `DEF-644` and
  `DEF-645` stay its rows; the runner avoids their shapes rather than fixing the driver.

## Task 0 — W0, channel probes (can end the pack)

**Why first:** everything rests on headless sessions behaving on both machines as they do
interactively, and on the runner being able to observe what a session did without trusting what
it says. `docs/AUTONOMOUS_EXECUTION.md` §2's verified facts come from the driver's own runs and the
document records no run on a Windows seat; §4 already names "emission ≠ dispatch"; §7 lists what
is still unverified.

**Where and how:** in a throwaway worktree of each machine's clone, never a seat's working tree (a
live seat session plus a probe session in one checkout is two sessions in one seat, Core Rule 15).
Every `claude -p` runs with `--output-format stream-json --verbose`, its stream saved to a file,
and is bounded by a wall clock that kills the **whole process tree**: on Windows the repo's
`tools/cc/_json_safe.py::run_bounded`, because `subprocess.run(timeout=...)` there waits for a
grandchild that holds the pipe (`docs/SHARP_EDGES.md`); on POSIX a new process group ended with
`os.killpg`, since a plain timeout kills only the direct child. The stream is decoded as UTF-8
explicitly, never in the OS locale (`docs/SHARP_EDGES.md`). `claude` is resolved with
`shutil.which` (on Windows it may be a `.cmd` shim). Record each child's environment: whether
`ESPALIER_MAINTENANCE_MODE` is set (§11.16), and that `CLAUDECODE` and `CLAUDE_PROJECT_DIR` are
stripped (`docs/SHARP_EDGES.md`, "Subprocesses Inheriting CLAUDE_PROJECT_DIR Mis-Route Harness
Scripts").

| Probe | Oracle (read from the saved stream or the filesystem, never a model-printed token) | Refuting result |
|---|---|---|
| **W0-A** headless session runs | `claude -p "reply with the single word PONG"` ends with a `result` event, exit 0, inside the bound | non-zero exit, a kill at the bound, or an interactive prompt |
| **W0-B** SessionStart fires in `-p` | the session marker under `.espalier-state/sessions/` and the blueprint store's mtime move during the run | neither moves (no hooks load: "No banner means no hooks") |
| **W0-C** slash commands dispatch | the stream shows `/status` expanded into its command body (the expansion event), not only `SURFACE:` in the output, which a session that never dispatched can still print (§4) | no expansion event |
| **W0-D** foreground subagents run | the stream shows an `Agent` tool call with the requested subagent type and its returned result | no such call; note `subagent_stop.py` returns early under maintenance mode, so the hook layer is no witness |
| **W0-E** the dispatch tools work inside `-p` | `python3 tools/cc/mail.py assignments --no-fetch --json` and `python3 tools/cc/board.py --no-fetch --json` run as tool calls in the stream and their JSON parses | either fails |
| **W0-F** what blocks under `--permission-mode auto` | a `-p` goal that edits a file under `tools/cc/` and commits on a scratch branch of the throwaway worktree, and runs `gh pr list`; record every prompt or refusal from the stream | any step stalls waiting for input (record which) |
| **W0-G** a session cut short | kill a running `-p` at the bound | the call does not return within bound plus a stated grace, or any process from the session's tree survives, or the worktree is left in a state the next session cannot detect |
| **W0-H** an approval-waiting command, headless | run the real `/implement-task` on a trivial assign; record what the session does at its step 2 ("Present plan and wait for approval") and at an `AskUserQuestion` | the session proceeds past either without a recorded approval (it approved itself: a skipped step no later check can see) |
| **W0-I** a full test tier inside `-p` | run `python3 scripts/proof_tier.py --run --tier full` as one tool call in a `-p` goal on each machine | it cannot complete in the foreground (the Bash tool caps a call at 600 s; *probable*, since the full tier takes far longer); then the runner, not the session, runs the tier |

**Exit.** A refutation of W0-A, W0-B, W0-C, W0-D or W0-G on a machine means the runner cannot keep
§11.15's promise there: stop, record the result in this table, and re-raise to the operator before
any W1 work, naming the machine. Whether the runner then proceeds on the other machine alone is the
operator's call, not this pack's. A refutation of W0-H decides `TP-700a`'s shape (see W1) rather
than ending the pack, unless no headless form of the lane procedure keeps its approval steps; then
stop and re-raise. W0-F and W0-I are design input for `TP-700a`.

**Record** each probe's command, machine, Claude Code version (`claude --version`), the saved
stream's path and the result here before closing W0.

## Relevant memory

Recent pattern: the unattended failures here were never crashes. They were runs that reported
success while skipping steps: the nine-pack chain (§11.14), the paraphrased goal (§11.15), a
one-shot session that backgrounded its gate and exited clean (§7.9), and a sentinel that read a
printed token as proof of dispatch (`DEF-645`). The runner's checks must sit outside the session
and read what the CLI recorded, not what the model wrote.

| Entry | Where |
|---|---|
| Unattended landing is mechanically green but incomplete | `docs/FAILURE_MODES.md` §11.14 |
| A paraphrased command-goal skips the command's non-named steps | `docs/FAILURE_MODES.md` §11.15 |
| Deferred work silently lost in a one-shot `claude -p` | `docs/FAILURE_MODES.md` §7.9 |
| Maintenance mode bypasses the enforcing hooks — goal-text completeness becomes load-bearing | `docs/FAILURE_MODES.md` §11.16 |
| A one-shot `claude -p` has no loop to resume into — never background a gate | `docs/SHARP_EDGES.md` |
| On Windows, `subprocess.run(timeout=...)` waits for a grandchild that holds the pipe | `docs/SHARP_EDGES.md` (and `DEF-3004`, the open class of unbounded spawns outside `tools/cc`) |
| A text-mode subprocess decode uses the OS locale, not UTF-8 | `docs/SHARP_EDGES.md` |
| Subprocesses Inheriting CLAUDE_PROJECT_DIR Mis-Route Harness Scripts | `docs/SHARP_EDGES.md` |
| An autonomous gate's green is env-relative — pin the install env | `docs/SHARP_EDGES.md` |
| A pre-registered witness must be able to fail | `docs/SHARP_EDGES.md` |
| Parallel work protocol | `memory/parallel-work-protocol.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "<topic>"` with the topics
"unattended pack chain lands green but incomplete", "headless claude -p one-shot session deferred
gate stall" and "worker seat parallel work protocol dispatcher assign", plus header greps of
`docs/FAILURE_MODES.md` (§11.14 to §11.16) and `docs/SHARP_EDGES.md`, and the review's findings.
Re-run them if this pack has been sitting.

## Implementation — sketches for W1 to W4 (each a child pack after W0)

Every fix below is a **fix shape (untested)**; its refutation is named with it.

**W1 — runner core (`TP-700a`).** A Python script beside the driver it extends. Per seat:
1. If the stop file exists, print why and exit 0.
2. If `checkout_sync.live_sessions` lists a live session in this seat's worktree, refuse: the
   runner and an interactive session would be two writers in one checkout.
3. Read jobs (`mail.py assignments --json`) and the board (`board.py --json`). Stop on any section
   the board could not read and on a red `post_merge`: an unread read is never treated as clean
   (`ship.py status` and `ship.seat_open_prs` are lenient on a failed read by design).
4. Take the oldest job **marked for the runner**: carrying `after:` with its prerequisite merged,
   or `after: none`, or listed on the operator-approved night board (W4). An assign without the
   field belongs to interactive seats. Refuse if this seat already has an open pull request.
5. Skip a job already landed, keyed by `mail.py::_job_key` (not the assign id, which changes when a
   job is re-sent), and record landing, not committing, unlike the driver (`DEF-644`).
6. Run one `claude -p` with `--output-format stream-json --verbose`, the stream saved, a
   process-tree wall clock as in W0, the environment stated (maintenance mode recorded,
   `CLAUDECODE` and `CLAUDE_PROJECT_DIR` stripped). The goal names the full command chain by name
   (`/implement-task`, then `/commit`, then `/handoff`) with the assign text as the brief. What
   stands in for `/implement-task`'s step-2 approval is decided from W0-H, and is never the
   session approving itself.
7. Check from the stream and the filesystem: the command expansions happened (dispatch, per lane;
   `DEF-645`'s gap is a check made once and read from printed text), the lane branch advanced, and
   the push happened. Then the runner itself runs `python3 scripts/proof_tier.py --run` on the
   lane outside the session if W0-I shows the session cannot. Any miss: the stop protocol.

*Refuted if* W0-F shows a step the lane procedure needs (pushing, `gh`, a protected-zone edit)
cannot run headless; then the runner does that step itself after the session, or that lane kind is
out of the runner's scope.

**W4 — `after:` and the night board (`TP-700b`).** `after` as an optional `re` field built in
`mail.py::new_message`, taken from a new `--after` flag in `mail.py::build_parser`, carried through
`mail.py::live_assignments`, and shown by `board.py::render` as runnable or held. A message with no
`after:` reads as not-for-the-runner, so every old message stays with the interactive seats.
*Refuted if* it breaks reading of older messages (the channel is append-only).

**W2 — follow-through (`TP-700c`).** Poll `ship.py status` on a bounded interval and parse it
strictly; a read it cannot make is a stop. *Refuted if* its output cannot tell a lost runner from a
real red in parseable form (its help names "a lost runner's apart"; `TP-700c`'s Task 0 checks).

**W3 — completion audit (`TP-700d`).** Earn-the-red: run the head's test files over the merge
base's source (the lane's source reverted, its tests kept); only a FAILED node (pytest exit 1)
counts as red, since a test file new to the lane has no node at the base (exit 4 or 5 is not a
red). Reviewers: the stream shows two `Agent` calls of the reviewer subagent types with returned
results, before the last commit. The tier: the runner's own `proof_tier.py` exit code. *Refuted
if* a lane's red cannot be expressed as test files over reverted source (a gate in CI only), in
which case that lane kind needs a human check and the runner stops on it.

## Affected symbols

### Changed-semantics
- `tools/cc/mail.py::new_message` (W4: an optional `after` in the message's `re`)
- `tools/cc/mail.py::build_parser` (W4: the `--after` flag)
- `tools/cc/mail.py::live_assignments` (W4: carries `after` through)
- `tools/cc/board.py::render` (W4: runnable versus held)

### Renamed
- (none -- nothing is renamed)

### Added-paths
- `scripts/seat_runner.py` (W1 to W3; name provisional, decided in `TP-700a`)
- `tests/test_seat_runner.py` (W1 to W3; `claude` mocked by a Python fake, not the driver's
  `#!/bin/bash` one, so the tests run on Windows)

### Removed-paths
- (none -- `scripts/run_pack_chain.sh` stays; see Scope (out))

## Pass criteria

- **W0:** every probe in the Task 0 table has a recorded command, machine, Claude Code version,
  saved stream path and result on both machines, or a recorded refutation that was re-raised to
  the operator.
- **W1:** with `claude` mocked, the runner (a) runs nothing while the stop file exists, and a stop
  writes the file before its mail, so a refused send still leaves it; (b) refuses a second open pull
  request for the seat and a live interactive session in the worktree; (c) takes no job without
  `after:` or a night-board listing; (d) stops when the session made no commit, when the stream
  lacks the command expansions, when the push is missing, and when a board section is unread, each
  with a test that goes red when that check is removed; (e) a session past its bound leaves no
  surviving process. No check may be weakened to pass a test.
- **W4:** an old message without `after:` reads as not-for-the-runner; a job whose `after:` is
  unmerged reads as held on the board.
- **W2:** a red required check produces at most two fix sessions, then the stop protocol; a
  CONFLICTING pull request runs `catch-up`, not a session; an unreadable status is a stop.
- **W3:** a lane whose new test passes at the merge base fails the audit (the mutation: a test that
  never earned its red); a lane whose stream lacks either reviewer call fails it.
- **Pilot (closes the roadmap):** one seat, with the operator present, after W3 has landed. The
  threshold, set now: every merged lane passes the runner's audit **and** an independent hand audit
  of the full completion surface (plan, red, both reviewers, tier, sibling sites, changelog, ledger),
  with zero lanes missing a required step, over at least five lanes. Only then does unattended
  running come up for decision.

## Files touched

- **New:** `scripts/seat_runner.py`, `tests/test_seat_runner.py` (W1 to W3).
- **Modified:** `tools/cc/mail.py`, `tools/cc/board.py` and their `espalier/_vendor/cc/` mirrors
  (W4, via `python3 scripts/sync_vendor_cc.py`); `docs/AUTONOMOUS_EXECUTION.md` (W0 results, the
  runner's section); `memory/parallel-work-protocol.md` (the stop protocol and `after:`).
- **Unmodified on purpose:** `scripts/run_pack_chain.sh`; the interactive `/loop` worker tick.

## Sub-task ordering

1. **W0** in a throwaway worktree on the Mac, then on Windows. Checkpoint: the Task 0 table
   filled. Stop and re-raise on any refutation of W0-A, W0-B, W0-C, W0-D or W0-G.
2. **`TP-700a` (W1)** written from W0's results, then built. Checkpoint: the W1 pass criteria.
3. **`TP-700b` (W4)**, before the runner takes any real job. Checkpoint: the W4 pass criteria.
4. **`TP-700c` (W2)**, then **`TP-700d` (W3)**. Checkpoint: each wave's pass criteria and a
   red-team pass that names the mutation that survives. No real lane goes through the runner
   before W3 lands.
5. **Pilot** with the operator present. Checkpoint: the pilot line of Pass criteria.

## Estimated effort

| Wave | Budget |
|---|---|
| W0 probes, both machines | 3-4 h |
| W1 runner core, with tests and red-team | 8-10 h |
| W4 `after:` and the board | 2-3 h |
| W2 follow-through | 3-4 h |
| W3 completion audit | 5-7 h |
| Pilot, supervised | five or more lanes over several days |
| **Total** | **21-28 h** of seat time, spread over the waves |

Budgets on packs here have run high before (one pack's budget was about 2.7 times its actual
time); treat these as an upper order of magnitude.

## Landing
- State: ROADMAP
- Commits:
- Suite:
- Earn-the-red: per wave, in each child pack's Landing
- Red-team: authoring review 2026-10-13, request changes (five high, seven medium, five low), all folded; per wave after
- Reach: not a class pack; it closes no ledger class
- Date:
