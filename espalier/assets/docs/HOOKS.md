# Hooks Guide

Espalier-Harness enforces governance through twelve hook scripts that run
automatically on Claude Code events. You don't invoke them — they fire
on every tool call, every session start, every stop. This guide explains
what each one does, what it looks like when it fires, and how to
configure the system for your workflow.

If you just got blocked and want to understand why, skip to the hook
that matches your situation.

Source paths in this document name files in the Espalier source repo
(`tests/…`): every limit this guide declares cites the test row that pins
it, so the day a reader closes the limit the row reds and the sentence is
rewritten on purpose. `init` does not deploy those files.

---

## How hooks work

Claude Code supports lifecycle events — moments where external scripts
can inspect or intervene on what the agent is about to do. Espalier
wires twelve scripts to ten of these events:

- **SessionStart** — fires once when Claude Code launches. Cannot block.
- **UserPromptSubmit** — fires when you send a message. Cannot block.
- **PreToolUse** — fires before every tool call (Write, Edit, Bash, etc.). **Can block.**
- **PostToolUse** — fires after every tool call. Cannot block (tool already ran).
- **PostToolUseFailure** — fires after a tool call fails (Write/Edit/NotebookEdit). Cannot block (reporter).
- **ConfigChange** — fires when settings are modified. **Can block** project/local/user changes.
- **Stop** — fires when Claude tries to end a turn. **Can block.**
- **SubagentStart** — fires when a spawned subagent starts. Cannot block (reporter).
- **SubagentStop** — fires when a spawned subagent finishes. Cannot block (would deadlock parent).
- **PostCompact** — fires after context window compaction. Cannot block.

When a hook blocks, it returns a JSON message explaining why. Claude
sees this message and adjusts. When a hook allows, it exits silently and
you never know it ran.

**Exit code contract:** Hooks communicate on exactly one channel per
invocation (Channel-XOR — see
[`docs/sharp-edges/hook-exit-codes-channel-xor.md`](sharp-edges/hook-exit-codes-channel-xor.md),
which `init` does deploy in full).
The two valid shapes are:

- **Structured (what every Espalier-Harness hook uses):** exit 0 with
  the event-specific decision JSON on stdout. Exit 0 with no output
  means "I have nothing to say, proceed."
- **Simple:** exit 2 with a plain reason on stderr, no stdout JSON.
  Espalier doesn't use this shape, but it's a valid hook protocol path
  if you write your own hooks.

Mixing the channels fails, and the two mixtures fail differently.
**Exit 2 *and* JSON on stdout:** the block still fires and your JSON reason
is what shows — Claude Code reads stdout JSON on every exit code and takes
the blocking message from "the reason from your JSON's blocking decision
when it makes one, and your stderr text otherwise" — so the stderr line you
wrote goes unused. **Exit 0 *and* a reason on stderr without JSON:** nothing
blocks at all, and the reason reaches only the debug log (a record, but nothing
the session shows), because that is where the stderr of a hook that exits 0
goes. One channel per deny means the
wording you wrote is the wording that shows. Exit 1 is reserved for script
bugs, never for governance decisions — and with no decision JSON on stdout
it does not block either.

---

## The hooks, in session order

### 1. `session_start.py` — Context loader

**Event:** SessionStart · **Can block:** No

Fires once at the start of every Claude Code session. Loads repo context
into Claude's working memory: repo name, git branch, dirty-file count,
ESPALIER_MEMORY.md summary, active blueprint, and harness health status. Also
scans for kill-switch settings (`disableAllHooks`, empty hook lists) and
integrity drift, and names anything that looks wrong in the banner's
`--- WARNINGS ---` block at the top of its body -- the boot checks' lines and
any section whose file could not be read, each cut to its head so one long
line cannot push the others out; an `[INFO]` line (which worktree the
session's directory sits in) reads under a `--- NOTES ---` header after it. Each line also goes to stderr, which
for a hook that exits 0 reaches Claude Code's debug log only, never Claude or
your terminal.
A `bypassPermissions` default is not a kill-switch -- the hooks still run and
still deny in bypass mode -- so it gets its own `Permissions:` line naming the
settings file.

Three more states it reads. On POSIX it reads the process table and, when a
process reparented to PID 1 is a `python*` or `yes` command with ten or more
CPU-minutes -- the orphan a fan-out or background probe leaves when its shell
parent dies, invisible to a memory reading -- the header carries, after
`Status:`, a `Loose:` line naming each by PID and CPU time with a one-paste
`kill` (`Loose:     PID 4242 python 2685:01.10 CPU -- parent is PID 1: a
fan-out's orphan, a run you detached on purpose (nohup ... & disown, e.g. the
proof tier), or any process in a container; reporter only, nothing was killed.
Check before you paste: kill 4242`); the sample below omits it because it is
conditional, and Windows reports nothing. On every platform it writes this
session's marker under `.espalier-state/sessions/<session_id>.json` (the
payload's `session_id`, sanitised to `[A-Za-z0-9_-]` before it names a file;
`task_router.py` touches it on every prompt as a heartbeat) and, when another
marker in the same tree was touched within the last four hours, the header
carries a `Sessions:` line after `Loose:` naming each such session by its id
prefix, when it started and when it last prompted, what the two share (`cc/`
and `.espalier-state/`, so the plan, the blueprint head and the working summary
are last-writer-wins) and the sharp edge to read; markers untouched for seven
days are swept at start. The sibling's recorded `cwd` is shown when it differs
from this root (the same checkout, or a worktree entered mid-session). A
`clear` source retires the sibling markers that record this hook's parent pid:
a clear mints a new session id, the previous session in this window is gone,
and where the hook's parent is the Claude Code process itself (measured on
macOS, 2026-10-05: no shell in between) that pid names the window, so the
handoff-then-clear loop is not told about itself; where the parent is a
per-spawn shell the recorded number is a dead shell's and nothing matches (a
recycled number landing on a dead shell's is the one way a live sibling's
marker could be retired; the pid is a window identity, never a liveness
oracle). The heartbeat writes the same pid: a marker `task_router.py` has to
write itself (none on disk) records it, and one that records none -- the stub
an earlier build's heartbeat wrote -- is repaired the next time its session
prompts, so a predecessor from before the pid landed is retired too once it
has prompted again; one already closed is never repaired and ages out of the
four-hour window instead. Both writers read the `cwd` they record through one
resolver, so the same-tree comparison meets one spelling. Reporter only,
omitted when nothing qualifies, and a window closed without `/handoff` keeps
its marker until it ages out, which the line says (a `SessionEnd` hook,
planned, is the full answer). And a fresh session (source
`startup` or `clear`) that finds `cc/execution_plan.json` still `in_progress`
opens the body with an `OPEN PLAN` section -- the task, the current step by
its index (as `mark <index>` takes it), how long since the file changed, and
the `status` / `reset` verbs spelled with the host's interpreter (`<python>` in
the example below stands for whichever name resolved) -- because `plan_guard` reads that record as an open
mutation window on source files, and a task that ended without its `/handoff`
leaves it open for every later session.
And it asks GitHub, through one bounded `gh pr list` call, for your recent
pull requests on this repo, and the header carries two lines from the answer,
after `Status:` (and `Loose:`). `Open PRs:` names each one still open --
number, head branch, the check tally with red checks named, a conflict or
behind-base note, and what auto-merge will do (`Open PRs:  #<n>
lane/<name> -- 15 of 21 checks green, 6 running;
auto-merge armed: it merges on its own, so pull main after`; a row GitHub
reports as blocked says what holds it: `... 1 running; auto-merge armed;
waiting on 1 running` while checks run, and with a red `... 1 red (verify);
auto-merge armed but held: required check red (verify); tools/cc/ship.py status
tells a test red (fix, push, re-bind) from a lost runner (rerun)` (a cancelled
required cell counts red, as a failed one does)
-- the listing carries no is-required flag, so a row with a red earns one
more bounded read, `gh pr checks <n> --required`, and the tail names the
required reds it answers with, `... but GitHub is holding it (blocked): no red is required, so a review or a
required check that has not reported` when the read answered that none of
the reds is required, `... GitHub is holding it (blocked): gh pr checks <n>
--required says which` when nothing is red and nothing runs, or `could not
read which reds are required` when the read could not be made (the read is
spent only on the three rows the line renders, and only while the block can
still afford the `Merged:` read after it);
a red on a check that is not required does not hold the merge; a conflict
does). `Merged:` names each recently merged one whose
merge commit your local base branch does not reach yet, with the pull that
catches up (`Merged:    #<n> lane/<name> -- merged into
main <date>, not in your local main; pull it: git switch main &&
git pull --ff-only origin main`), answered by a read-only `git merge-base`
per merged row, the five most recent -- and each whose latest run of a check
is red (`; red after merge: portability (windows-latest)`), because a check
that is not required finishes after the merge and otherwise reports to
nobody. Each check name is owned by the newest merge whose run of it reached
a verdict, so a later green run clears an older red, while a run still
pending, cancelled or stale supersedes nothing (the last two read
`no verdict:`). A lane shipped with auto-merge armed lands while nobody is watching,
so the next session opens on a local `main` behind it -- or, when a check
went red or the branch fell behind a base that must be up to date, on a PR
that sits armed and unmerged (the behind row and the conflict row each name the
catch-up; the conflict row says the record files resolve by shape); the two
lines say which before the session commits anything. Reporter only, and it fails open: a host
without `gh`, a sign-in or a GitHub remote loses the lines, never the banner;
the open and merged reads are separate calls (one shared recency window let
ten merges hide the one open PR), each line shows three rows then a count,
and the whole question is capped at eight seconds under the hook's fifteen.
The sample below omits both, as it omits `Loose:` and `Sessions:`, because all four are
conditional.

And where `git config espalier.machine` names this box, it reads the mail
channel between the machines that share the repository (`tools/cc/mail.py`:
one append-only ref per machine on origin, typed messages, claims as a fold)
and carries a third line, `Mail:`, after `Merged:`: the unread messages the
other machines left, newest first, one headline per row (`Mail:      win:
request re lane/x (1 path) -- "please look at the fixture hang"`), three rows
then a count, and a tail that says whose text it is and where the bodies are
(`/inbox`). One fetch, then local reads, every one of them taking what is
left of the pull-request block's eight-second budget (the two blocks share one
deadline under the hook's fifteen, so a slow `gh` costs the mail line and never
the banner); a fetch that could not be made is said in the line beside what
was fetched before. No name, no fetch and no line -- except that a clone which
names no machine but already holds another machine's mail ref (a plain `git
fetch origin` brings them in) gets one line saying how to opt in, so the box
that was never opted in is the one told the channel exists. Reporter only,
like the two lines above it. The compaction re-orient carries an unread count
from the local refs with no fetch.

And in a linked worktree of a clone that names a machine, before the mail is
read, it gives the worktree a name of its own when it still answers the
clone's (a linked worktree reads its clone's config, so two sessions would
otherwise share one mail ref, one set of claims and one id block). The name is
`<clone>-<worktree directory>`, set with `git config --worktree
espalier.machine` after turning on `extensions.worktreeConfig`, and read back.
A `Seat:` line before `Mail:` says so. Until `espalier.toml [id_blocks]` gives
the new name a line of its own, the worktree mints ids from its clone's
block, through the reservation record every worktree of the clone shares.
Only a fresh session (`startup` or `clear`) is named. A resumed or compacted
session keeps the name its claims were made under.

It does not name the worktree when the derived name is another worktree's, or
when the clone's config sets `core.worktree` or `core.bare`, which git says to
move first. The line then says why and gives the two commands.

- **Where it runs no git:** a main checkout (its `.git` is a directory), a
  clone that names no machine, and a worktree that already has a name.
- **What it writes:** git config only. That is `extensions.worktreeConfig` in
  the clone's shared config (written once, when it is off) and the
  worktree's own name. Besides the checkout catch-up below, it is the only
  SessionStart job that writes git config.
- **Its time limit:** each git call takes a slice of the banner's budget.
- **What it depends on:** the hooks must load in the worktree. Claude Code
  copies `.claude/settings.json` into each worktree it makes through
  `.worktreeinclude`, which `init` writes.

And on a fresh session (source `startup` or `clear`) it first catches the
checkout up and clears the leftover worktrees beside it
(`tools/cc/checkout_sync.py`), before anything above is read, so the branch,
the memory digest and the hooks themselves describe the tree the session works
in. A lane shipped with auto-merge armed lands while nobody is watching, and
the next session used to open on the finished branch, behind `main` by
everything merged since (measured 2026-10-08: 348 commits, so the banner was a
four-day-old build). One bounded `git fetch --prune`; then it moves only
`main` itself (a fast-forward) or a branch GitHub deleted at the merge (its
upstream reads `[gone]`) whose every commit is in `origin/main`, and only when
there are no uncommitted changes to tracked files, no merge, rebase,
cherry-pick, revert, sequence or bisect in progress, no plan in progress, no
other live Claude Code session in this checkout, and nothing on local `main`
that origin lacks. The move is a single `git switch -C main --track
origin/main` (which git itself refuses over a local change; in a linked
worktree where `main` is checked out elsewhere it detaches at `origin/main`),
started only with time left and never killed: a move still running at its
wait is left to finish and the line says so. A checkout that is not behind is
never moved, so a lane branch created a moment ago stays put; a detached HEAD,
a lane with commits of its own, or a branch whose remote still exists is named
and left as is. The header carries, after `Status:`, a `Checkout:` line saying
what moved (`Checkout:  caught up -- left lane/x (merged, branch deleted);
main fast-forwarded, 348 commits, now fd49288`, with a note to `/clear` when
the pull changed the hooks or `CLAUDE.md`) or why not, with the command that
finishes the job by hand (`Checkout:  NOT caught up (12 commits behind
origin/main, 2 uncommitted changes to tracked files) -- finish or stash that,
then: git switch main && git pull --ff-only origin main`; when another session
holds it, the remedy is to end that session first). Then each registered
worktree under `.claude/worktrees/` is removed only when it is clean, merged
into `origin/main`, holds no lock or a lock whose holder process has exited,
has no plan in progress, no live session is in it, and every ignored file in
it is a cache or build output, a byte-identical copy of the root's (what
`.worktreeinclude` copied in), or `cc/` session state, which is copied into
the root first (compaction legs and the working summary into
`cc/blueprints/compact_summaries/`, the rest under
`cc/blueprints/from-worktrees/<name>/`, never over a file). Any other ignored
file -- an ignored draft or notes file, a `.env` -- keeps the
worktree, because `git worktree remove` deletes ignored files without asking.
On Windows a folder a process holds open (a terminal or an editor in it)
cannot be renamed, and the reaper keeps any folder that refuses a rename. A
merged branch a removed worktree held is deleted. A `Worktrees:` line names
what was removed, what was kept and why (`2 commit(s) not in main (lane/y)`,
`a live Claude session is in it (pid 4242)`, `locked by hand`, `1 ignored file
git status cannot see (notes.md)`). "A live session" is read from Claude
Code's own session registry (`~/.claude/sessions/<pid>.json`, and the same
under `$CLAUDE_CONFIG_DIR`), because an idle session writes nothing a file
scan can see, plus this tree's session markers for a session that entered a
worktree mid-session. The registry is trusted only when it lists the session
asking and every entry in it parses with a numeric pid; otherwise nothing is
removed and the line says so. While another session is live in this checkout,
nothing is removed either (it may be working in one of them). The catch-up
has its own six-second budget, so the pull-request block keeps its eight, and
the two together stay under twelve of the hook's fifteen; a backlog of
removals clears over a few sessions. A resume or a compaction never moves the
tree. On by
default in the Espalier-Harness source repository; elsewhere off until
`session_catch_up = true` sits at the top level of `espalier.toml`, because
moving someone's branch unasked is a surprise. `ESPALIER_SESSION_CATCH_UP=0`
or `1` in the launching shell overrides both. `python tools/cc/checkout_sync.py`
says what it would do; `--apply` does it now.

**Auto-orient block.** The context output also carries the harness's
continuity surface -- each section gated on the artifact it describes,
never on repo identity: a one-line `/recall` pointer to whichever
footgun/failure-mode catalogs the tree actually has, a MEMORY digest
(identity line + recent-session headlines) once `ESPALIER_MEMORY.md`
carries dated Session Log rows, and the standing-principles index on the
self-host repo. The full
`docs/SHARP_EDGES.md` TOC is no longer injected -- pull sections on
demand with `/recall <topic>`. The orientation instructions tell Claude
to OPEN with a provisional first-thoughts read of whatever continuity the
banner injected -- the blueprint always, plus the GOAL snapshot and its
Notes-to-next-session when the repo keeps one -- give the operator a
one-glance state line, and end with a proposed next move -- not a passive
status report.
This replaces the typed `/context-load` invocation that operators
previously ran at every session begin. The slash command remains for
explicit mid-session re-orient, PostCompact recovery, and
DEGRADED-surface recovery (a degraded Surface line names the recovery
command).

**What Claude receives** (not drawn on your terminal -- a hook that exits 0 sends its plain stdout to the model's context window and Claude Code's debug log, never your terminal):

```
=== Espalier-Harness === Session Start ===
Host: OS=Darwin; python3=yes python=no (python3 only)
Repo:      my-project
Branch:    main
Status:    3 uncommitted changes
Memory:    **Repo:** my-project | **Stack:** python | ...
Blueprint: Auto-started new blueprint session
Surface:   healthy
Integrity: ok
Commands: /status /implement-task /smoke /preflight /commit /handoff /ship
Run /status to verify harness state.

--- OPEN PLAN (cc/execution_plan.json is in_progress; last touched 2d 3h ago) ---
Add the export verb
  [.] step index 2 of 4 (1 passed): wire the parser
plan_guard reads this as an open mutation window on source files.
  Yours? Continue it: `<python> tools/cc/execution_plan.py status`
  A finished task's? Clear it: `<python> tools/cc/execution_plan.py reset` (the record is demoted beside the blueprint cold store)

--- MEMORY (recent sessions -- headlines only; read ESPALIER_MEMORY.md for full rows) ---
- <date> <your last session's headline> ...

--- STANDING PRINCIPLES (hold these; bodies in docs/STANDING_PRINCIPLES.md) ---
- 1. Make it prove it
- 2. Toolbelt, not security boundary
...

--- FOOTGUNS & FAILURE MODES (pull, don't scan) ---
docs/SHARP_EDGES.md (concrete footguns) + docs/FAILURE_MODES.md (failure classes)
Retrieve the relevant one with /recall <topic>; per-surface footguns also fire
via the folder CLAUDE.md ladder on entry.

Orientation (on first response -- this REPLACES the old terse status report):
- Open with your genuine, PROVISIONAL first-thoughts read of the continuity
  above (blueprint + Notes to next session + GOAL). Reason about it; don't
  just restate it. Keep it a hypothesis to confirm, not a plan.
- Give the operator a one-glance state line (Working on / Next / Owed) and
  END with a proposed next move + "confirm or redirect?".
- For footguns/failure-modes, pull the relevant entry with /recall <topic>.

(**Every section above is conditional on its own artifact, not on repo
identity.** The footgun pointer ships wherever a real catalog exists --
`init` seeds `docs/FAILURE_MODES.md` in full, so an adopter gets it too,
while a seeded-but-unfilled `docs/SHARP_EDGES.md` is deliberately NOT
named: presence is not content. **Naming a catalog and being able to
`/recall` it are separate facts**, and the line says which it is: the pointer
asks the retriever whether it indexes `docs/FAILURE_MODES.md` on this tree (it
does only on the self-host repo, so an adopter is told to read that one directly
rather than sent to a retrieval that returns nothing), and the orientation
bullet that teaches `/recall` names the source families the corpus actually
yielded on this tree -- read off the corpus it just built, never a prose list
(`_recall.indexed_sources`), so an adopter who writes their own
`docs/STANDING_PRINCIPLES.md` sees it named the moment it is indexed and a
family whose gate is closed on their tree is never advertised; the list leads
with the adopter's own text: the root `CLAUDE.md`'s `## ` sections and every
`.claude/rules/**/*.md`, indexed without configuration wherever the files
exist, then the documents `recall_sources` declares in `espalier.toml`. The MEMORY digest renders once the
Session Log has dated rows, so an adopter sees their OWN recent sessions
from their first `/handoff` on; until then the orientation carries a
"Consult ESPALIER_MEMORY.md" fallback line instead. STANDING PRINCIPLES
renders wherever `docs/STANDING_PRINCIPLES.md` has sections, which `init`
never seeds, so an adopter sees it from the session after they write the
file -- the illustrative block above is the self-host banner, whose tree
has one.)

**Every GOAL clause above is conditional.** `cc/GOAL.md` is a local,
gitignored snapshot: `init` seeds a skeleton when it is absent, `/handoff` step 7
refreshes it, and `goal_snapshot = false` in espalier.toml stops the seed. A tree
that opted out and deleted the file, or predates the seed, carries no GOAL
section. The orientation is rendered to match what
was actually injected -- with no GOAL section the continuity list drops
`+ GOAL` and the state line reads "read from the continuity above"; with one it
reads "from GOAL". The illustrative block above shows the with-GOAL wording.
Gated on the **section**, never on self-host -- presence varies in both
directions, since the file is gitignored and can be missing here too.
(/context-load remains available for explicit mid-session re-orient.)
```

The `Host:` line reports the machine the hook ran on (this capture is
from a Mac).

If a kill-switch is detected, the banner's `Integrity:` line reads
`KILL-SWITCH (1 setting)  ->  remove it; enforcement is disabled` and its
Warnings block carries the finding (the debug log gets the same text on
stderr):

```
--- WARNINGS ---
[WARN] Espalier-Harness detected 1 kill-switch setting during
SessionStart. SessionStart cannot block Claude Code execution. If hooks
are still active, PreToolUse/ConfigChange guards will deny unsafe
actions; tracked protected changes are enforced by CI.
  Findings:
  disableAllHooks: true in .claude/settings.json
```

**Key detail:** SessionStart cannot block Claude Code from running — the
hook protocol forbids it. This hook reports. The actual blocking, if
hooks are still active, happens in `write_guard` (PreToolUse) and
`config_guard` (ConfigChange). If hooks have already been disabled before
Claude Code launches, nothing in this project can stop the session
locally. That's why CI exists.

**Configuration:** None. This hook is lightweight and always beneficial.

---

### 2. `task_router.py` — Prompt classifier

**Event:** UserPromptSubmit · **Can block:** No

Reads your prompt and decides whether it looks like a multi-step task
(keywords like "refactor", "implement", "migrate", "build a"). If it does,
Claude sees a gentle nudge suggesting `/implement-task --multi`. If your
prompt looks like a question, a read-only request ("check ...",
"summarize ...") or a quick fix, nothing happens, and a command you name
(`npm run build`) is not read as the task.

**What you see (when it fires):**

```
[HARNESS] Multi-step task detected. Use /implement-task --multi to
create an execution plan with verification gates before writing source
files. For a single focused change with one clear deliverable, use
/implement-task.
```

**What you see (most of the time):** Nothing. Questions, short prompts,
and quick fixes pass through silently.

**Key detail:** This is advisory only. Claude sees the routing guidance
as additional context alongside your prompt, but nothing prevents it
from proceeding differently. The hook never rejects a prompt.

**Configuration:** None needed. The hook is silent for most interactions.

---

### 3. `plan_guard.py` — Execution plan gate

**Event:** PreToolUse · **Can block:** Yes

Requires an active execution plan before Claude can write to project
source files. If Claude tries to write `src/app.py` without first
creating a plan via `/implement-task`, the write is denied.

**What you see when blocked:**

> No active execution plan (status='complete'). Mutation requires
> status='in_progress'; a completed, planned, or cancelled plan does
> NOT authorize new writes. Run /implement-task <description> to open
> a new plan. (attempted: src/app.py)

The parenthetical state label (`status='complete'`, `missing`,
`malformed`, `no-steps`, …) tells you which closed state the plan is
in so you can decide whether to open a new one or fix the existing
file.

#### Plan status and the mutation window

The gate has strict semantics. **Only `status='in_progress'` opens the
mutation window.** Every other state is closed — including
`status='complete'`. A finished task does not authorize new writes.

| Plan state | Mutation window | Notes |
|---|---|---|
| `status='in_progress'` (with ≥1 step) | **OPEN** | The only state that allows Write/Edit/Bash mutations |
| `status='planned'` | closed | Plan exists but execution hasn't started |
| `status='complete'` | closed | Task finished; window must be reopened for new work |
| `status='cancelled'` | closed | Plan aborted |
| `status='in_progress'` with empty `steps` | closed | Treated as `no-steps` |
| Other / empty / unknown status string | closed | Fail-closed default |
| Missing `cc/execution_plan.json` | closed | Fail-closed default |
| Malformed JSON or non-object root | closed | Fail-closed default |

To open the window: run `/implement-task <description>` (writes
`status='in_progress'` to `cc/execution_plan.json`).
To close it: finish the task (the runner writes `status='complete'`)
or cancel it.

This is workflow governance, not a security sandbox. The plan_guard
adds friction at the hook layer; a determined process with local
filesystem control can still bypass via `disableAllHooks`. CI +
`tools/cc/ci_guard.py` is the only enforcement that doesn't depend on
local hook code.

**What's exempt (doesn't need a plan):**

- Tests (`tests/`)
- Your stack's own test roots when its manifest sits at the repo root,
  read from the stack table (`tools/cc/_stack_table.py`): `test/`,
  `tests/`, `__tests__/` and `spec/` beside a `package.json`; `tests/`
  and `test/` beside a Python manifest; `tests/` beside `Cargo.toml`;
  nothing for Go, whose `_test.go` files sit beside source and have no
  root to exempt
- Harness infrastructure (`tools/cc/`, `.claude/`, `cc/`, `reports/`)
- Surfaces the harness's own instructions route you into (`memory/`,
  `docs/`, `task-packs/`) — see the §C23 note in `plan_guard.py`
- Root-level non-source files (`ESPALIER_MEMORY.md`, scratch notes)
- All Bash and MCP tool calls (plan_guard no longer fires on
  these — see note below)

A path is read relative to the checkout that contains it. Inside a
registered git worktree of the repository — the `.claude/worktrees/<name>`
a worktree session or agent works in, or a worktree beside the root —
`src/app.py` is `src/app.py`, not the plan-exempt
`.claude/worktrees/<name>/src/app.py`, so a worktree session keeps plan
discipline. The exempt prefixes, built-in and from `espalier.toml`, and the
plan file itself are read from the root whichever checkout the path is in.
A nested clone or a submodule is not a checkout of this repository and is
not governed.

**What requires a plan:**

- Any source file outside the exempt prefixes (`.py`, `.js`, `.ts`,
  `.go`, `.rs`, `.java`, `.toml`, `.yaml`, `.json`, etc.) when
  written via `Write`, `Edit`, or `NotebookEdit`.
- Root-level project files (`README.md`, `pyproject.toml`, `Dockerfile`,
  `Makefile`, `setup.py`, etc.) written via the same tools.

**Bash and MCP writes are not plan-gated.** The
PreToolUse matcher is `"Write|Edit|NotebookEdit"`, not `"*"`, so
Claude Code does not dispatch Bash or MCP tool calls to plan_guard at
all. Two motivations:
(1) the matcher fired on every tool call — `Read`, `Grep`,
`Glob`, every Bash invocation — and spawned a Python subprocess
(~50–100 ms cold-start) even though the hook's internal filter
early-returned on non-mutation tools; (2) the Bash write-intent
detector regularly tripped on routine diagnostic commands
(`time foo > /dev/null`, `echo … > /tmp/scratch`) that don't
touch source files. `write_guard` still enforces protected-zone
defense on Bash mutations, and the `bash_has_write_intent` and
`_mcp_tool_is_write` helpers stay in `plan_guard.py` as
importable classifiers (`main()`'s Bash/MCP branches are also
retained as defense-in-depth if a future operator re-widens the
matcher).

**How to satisfy it:** Run `/implement-task <description>` before
making changes. This creates `cc/execution_plan.json` with status
`in_progress`, which plan_guard checks on every subsequent tool call.

**Configuration:**

| Control | Effect |
|---------|--------|
| `ESPALIER_MAINTENANCE_MODE=1` (set before launch) | Bypasses the plan check entirely. For legitimate harness self-edits. One advisory audit record per session says so (`pretooluse_bypassed_maintenance_mode`; `/status --log` counts it). |
| `plan_exempt_prefixes` in `espalier.toml` (flat, top-level) | Adopter-customizable path-prefix carve-outs (e.g., `src/myapp/`). Adds to the built-in exempt list; doesn't bypass anything else. Every entry must end with `/`: a bare filename such as `README.md`, an absolute path or a `..` step invalidates the WHOLE list, which falls back to strict mode — and the deny says so, naming the entry and why (a `[plan_guard]` say-once record, counted by `/status --log`, is the other trace); the deny likewise says when the key is misspelled, sits under a table, or is set and does not cover the path — so a list that worked stops working the moment one bad entry joins it, and the deny tells you which. The root files the guard always gates (the roster is `tools/cc/hooks/plan_guard.py::PLAN_REQUIRED_ROOT_FILES`: the README, AGENTS, CLAUDE, changelog and contributing files and the build manifests) cannot be exempted by any prefix; an edit to one of them opens a plan first. NOT `[plan_guard] exempt_prefixes` — that spelling was taught by earlier docs, is not read, and the hook emits an advisory when it sees it. |

**Denial-hint surface.** Plan-required denials append a
discoverability hint pointing at both escape mechanisms above —
`_PLAN_EXEMPT_HINT` at `tools/cc/hooks/plan_guard.py::_PLAN_EXEMPT_HINT`. The
hint names `plan_exempt_prefixes` (the customization path) and
`ESPALIER_MAINTENANCE_MODE=1` (the harness-self-edit bypass) so
adopters who hit unfamiliar friction land on a configuration path,
not a bypass path. The hint cites this section by its heading
("Execution plan gate") because `init` always deploys this file; a
CLAUDE.md you already owned is kept as it is, so a pointer into it
would dead-end on exactly the trees that keep their own.

#### Maintenance mode

The relaunch recipe, for the deny that names this heading. What the mode
bypasses and what it does not is the table under "Friction bypass" in the
configuration summary below.

To use maintenance mode, quit Claude Code and relaunch (`--continue`
keeps the session you were denied in):
```text
POSIX / Git Bash / WSL:  ESPALIER_MAINTENANCE_MODE=1 claude --continue
PowerShell:              $env:ESPALIER_MAINTENANCE_MODE="1"; claude --continue
cmd.exe:                 set "ESPALIER_MAINTENANCE_MODE=1" && claude --continue
```
Setting the variable mid-session via a Bash tool call does not work —
the hook subprocess inherits env from the Claude Code process, which
was already running.

---

### 4. `write_guard.py` — Protected-zone enforcement

**Event:** PreToolUse · **Can block:** Yes

The anti-self-disable floor of the advisory → friction → protected-zone
model. Its headline job is to keep the hooks from being trivially turned
off mid-session — you can't edit `.claude/settings.json` to set
`disableAllHooks`, or overwrite a hook script, to silence friction that
feels "in the way." That keeps the path of least resistance "follow the
workflow," not "disable the safety and go." This is friction against a
slip or an agent drifting under load, not a defense against a motivated
attacker — a self-user won't attack their own work.

It blocks three categories of tool calls (kill-switch and protected-zone
first; the dangerous-command catch is a secondary slip-catcher):

1. **Kill-switch gate.** If any settings file contains `disableAllHooks:
   true` or empty/no-op hook lists, *every* tool call is denied until the
   setting is removed. This fires before anything else. A
   `bypassPermissions` default is not in this set: it turns off Claude
   Code's permission prompts, not Espalier's hooks, which keep running and
   denying, so a session started with one works normally.

2. **Protected-zone mutations.** The mutations the guard can read of a
   harness infrastructure path are denied -- a write into it, a delete of
   it, a move of it out of the zone, a permission change on it, and, for a
   delete or a move, of a directory that encloses it -- by the verb rosters
   and the declared limits pinned in the guard's remove/relocate test class,
   `tests/test_write_guard.py::TestRemovedOrRelocatedOperandIsAMutation::test_zone_row_under_the_plain_root`
   and
   `tests/test_write_guard.py::TestRemovedOrRelocatedOperandIsAMutation::test_every_consumed_arm_has_a_deny_row_and_every_row_names_a_consumed_arm`
   (the operand a verb removes or relocates is classified beside the one it
   writes, on both shells, since 2026-09-14):
   - `tools/cc/` (hook scripts and tools) — the whole tree, not just
     `hooks/`
   - `cc/` (governance surface — except allowed files like
     `execution_plan.json`, `GOAL.md` and blueprints: runtime state that
     appears as you work, not deployed by `init`. The three that `init` DOES
     write — `cc/LIVE_SURFACE.md`, `cc/COMMANDS.md` and `cc/PACK_MANIFEST.txt`
     — are allowed for the same reason: harness-managed, not yours to protect.)
   - `espalier/` and `.github/workflows/` — self-host repo only; on an
     adopter repo you own your engine source and your CI, so neither is
     blocked
   - `.claude/settings.json` and `.claude/settings.local.json` — these
     exact files only. `.claude/commands/`, `skills/`, `agents/`, and
     `workflows/` are NOT protected and stay freely editable.
   - `.github/workflows/harness-guard.yml` (protected on every repo,
     including adopters)
   - `.espalier/integrity.json` and `.espalier/freshness.json`
   - **your own zones**, read from `espalier.toml` on every call: a
     `protected_paths` prefix ("never touch") is denied on every channel --
     the mutations the guard can read, as for the harness zones: a Write or
     Edit, a shell redirect, a copy, move, delete, archive extraction or
     in-place edit naming the path; a program that writes there on its own
     (a training script, a build) is not seen -- matched at a path boundary
     (a prefix covers its contents and the bare directory, never a sibling
     whose name merely starts with it). A restore of a file there (a checkout
     of one path) is a write into the zone and is refused too: "never touch"
     is read literally, and the remedy is the setting. A `generated_paths`
     prefix ("regenerate; do not hand-edit") is refused on Write / Edit /
     NotebookEdit only, so a build's own recursive delete or regeneration step
     through Bash is never blocked. The deny names the key and the zone ("This
     zone is YOURS, not the harness's: your espalier.toml names it under
     `protected_paths`") and its Don't / Do pair is the zone's own, never the
     maintenance-mode relaunch, which would be the wrong remedy for your own
     tree. An entry that is not a list of strings, is absolute, or would cover
     the whole tree protects nothing and SAYS so, once a session (a stderr
     line and a `config_zone_ignored` audit record); so does a key name one
     letter off, and a zone read by the no-parser fallback on an old
     interpreter. `/status --explain <path>` reports both zones.

   The prefixes are read relative to the checkout that contains the path.
   Inside a registered git worktree of the repository — the checkout a
   worktree session or agent works in, nested under the root or beside it —
   the same file is denied the way it is at the root, on every channel
   (Write, Bash, MCP), the denial names the worktree, and a hardlink alias
   planted there is stat-ed there. The worktree list is git's own registry
   read off the disk, never a subprocess. A nested clone or a submodule is
   not a checkout of this repository and is not governed.

   A relative Bash or PowerShell spelling is read from the directory the
   command runs in, not from the root: the hook payload's `cwd` (the
   directory Claude is in, which Claude Code moves when an earlier call ran
   `cd`) is the start, and a `cd`, `pushd` or `popd` (`Set-Location`,
   `Push-Location`, `Pop-Location` and their aliases) inside the command
   moves it for the statements after it, a subshell's `cd` ending at its
   `)`. So `cd tools/cc && echo x > hooks/f.py` is denied and `cd /tmp &&
   echo x > tools/cc/hooks/f.py` is not; until 2026-09-13 both read against
   the root and both verdicts were wrong. A `cd` the shell would not perform
   moves nothing: one whose directory is not there (the walk asks the disk,
   and credits a directory an earlier statement of the same command makes,
   so `mkdir -p sandbox && cd sandbox` reads as entered), one in a pipeline
   stage or backgrounded with `&`, one inside a function body; a `cd` after
   `&&` or `||`, or inside an `if`, `case` or loop body, is conditional and
   the statements after it are judged in both directories. A target the walk cannot read -- a
   variable, a substitution, `cd -` -- leaves the directory unknown, and an
   unknown directory resolves against the root as before (the indirection
   class, declared; pinned by
   `tests/test_write_guard.py::TestTheDirectoryAWriteRunsIn::test_bash`). A delete reads it more strictly (item 3): the unknown
   directory joins the start, so a bare glob or `$PWD` after it is
   refused, and so is one anywhere in a command that is not plain. On
   PowerShell the .NET file API (`[IO.File]`,
   `[IO.FileInfo]::new(...)` and the rest) reads the process directory,
   which `Set-Location` never moves, so those paths resolve against the
   start alone.

3. **Dangerous commands.** Bash patterns like `rm -rf /`, `rm -rf *`
   -- and the same recursive delete without `-f` (`rm -r /`, `rm -r ~`,
   `rm -r .` from the checkout), since `rm` prompts only for an unwritable
   file and only on a terminal --
   an un-narrowed `find` with a delete action rooted at the repo, your
   home or the filesystem root (`find . -delete` from the checkout; a
   `-name`/`-path`/`-regex` predicate placed BEFORE the action narrows
   it, while `-type`, an attribute test such as `-size` or `-mtime`, a
   negation or an `-o` does not), and unscoped `git reset --hard` are
   blocked.

   A bare `*` glob or `$PWD` is judged as the directory the
   delete runs in -- the wall where that is the checkout, the home or the
   root, the nudge inside a build directory -- but only in a PLAIN
   command: statements joined by `;`, `&&`, `||` or newlines, with no
   pipe, group, subshell, substitution, heredoc, loop, background job or
   program handed to another shell (on PowerShell: no pipe, block,
   subexpression, call or dot operator or script), and no `cd` it cannot
   read.

   On the Bash tool every command in it must also be one the guard
   knows hands nothing to a shell -- the read-only and file tools on the
   masker's roster, the interpreters whose shell-outs it reads, and `rm`
   -- so a build tool such as `make` or `cmake` makes the command not
   plain: put the clean in its own command. On the PowerShell tool the
   check refuses the heads it knows run code in this session (`iex`, a
   dot-source, a script) and the re-parsing openers; a function or module
   command that changes the location is not seen -- the walk's standing
   limit, a declared limit pinned as the nudge it keeps by
   `tests/test_write_guard.py::TestCatastrophicRmFlagOrderIndependent::test_the_declared_cross_shell_limits_draw_exactly_the_verdict_they_declare`
   (a profile function that moves up and clears `*` draws the nudge where
   `Set-Location ..` before the same clear draws the wall). On the
   PowerShell tool the relief reaches the unforced `Remove-Item -Recurse`,
   the sweeps and the forced `Remove-Item -Recurse -Force` alike, so the
   same `*/build` clean is one nudge on both tools, forced or not
   (`tests/test_guard_false_positives.py::TestThePowerShellTierMatchesBash::test_the_glob_relief_reaches_the_forced_powershell_remove`;
   until 2026-10-07 the forced form's bare leading glob walled wherever it
   ran).

   In any
   other command a bare glob or `$PWD` is refused wherever it runs, as it
   was before the relief -- the relief is an allowlist of plain commands
   (2026-09-19), not a list of the places the walk cannot follow; a `find`
   is never plain on the Bash tool, since it can hand a program to a
   shell.

   PowerShell equivalents (`Remove-Item -Recurse -Force`; and
   `Remove-Item -Recurse` without `-Force`, which still removes every item
   that is not hidden or read-only with no prompt, walled on a catastrophic
   target -- the filesystem or a drive root, your home directory by path or
   by `$HOME` / `$env:USERPROFILE`, the repo or a parent of either, a
   shallow system path such as `/etc`, a path two or fewer levels below a
   drive root outside the repo, your home directory and the temp roots
   (`C:\Windows\System32`, `C:\work\old`; a path inside the repo or the home
   is judged by containment first, so `C:\myapp\build` with the repo at
   `C:\myapp` is the nudge's, and the Bash tool reads a drive path one level
   deeper, the drive letter counted as a component, both pinned by
   `tests/test_denial_reasons.py::TestDangerousBashPlainEnglish::test_the_claims_hold_against_the_classifier`),
   an absolute path with a `..` step -- and one nudge on any other path or
   variable) are
   also caught, by every switch spelling that runs -- the unambiguous
   prefixes PowerShell binds (`ri -r -fo`, `-rec -forc`) and the `/bin/rm`
   clusters (`rm -rf`), because pwsh's alias table is per platform: on
   macOS and Linux `rm`, `rmdir` and `find` are the native binaries. The
   forced remove of an absolute target is walled unless every target is a
   literal path strictly below a scratch root -- the temp directory `TEMP`,
   `TMP` or `TMPDIR` names, a drive-root `tmp` or `temp`, a POSIX temp
   root -- which steps off the wall (2026-10-04: a removed worktree's
   read-only object files need `-Force`, and no tier answered yes), and the
   unforced remove reads the same path the same way. The temp root itself
   (a `.` step, or a trailing dot or space Windows strips, names it too),
   this project's checkout or the home directory under it, a link that
   resolves onto one, a variable, a glob and a `..` step stay the wall,
   pinned by
   `tests/test_write_guard.py::TestPowerShellScratchRootRung::test_everything_else_absolute_is_still_the_wall`.

   Scratch below a temp root passes without the nudge on both tools,
   forced or not (2026-10-07; until then every scratch cleanup drew it): a
   literal path strictly below the temp directory `TEMP`, `TMP` or `TMPDIR`
   names, a drive-root `tmp` or `temp` or a POSIX temp root, read for a
   remove verb from the directory the command runs in and through its
   literal bindings, and on
   the Bash tool a `mktemp` binding that makes its directory there (`T=$(mktemp
   -d)` then `rm -rf "$T"`; a `-p` directory or a bare template is
   elsewhere). It keeps the nudge when it is, or sits inside, a git checkout
   (a clone or a worktree may hold work), this project's checkout, or a
   home directory that lies below a temp root, and when it carries a
   variable, a wildcard or a `..` step -- pinned by
   `tests/test_speedbump_irreversible.py::TestCpRmrfTempRoots`. The
   environment's temp directory nested below a POSIX temp root (macOS's
   `/var/folders/<x>/T`) and every parent of it keep the nudge too, while a
   sibling of it there is scratch to the rule, a declared limit
   (`tests/test_speedbump_irreversible.py::TestCpRmrfTempRoots::test_a_temp_directory_nested_below_a_temp_root_keeps_the_nudge`).
   A checkout deeper inside the target is not looked for, a declared limit
   (`tests/test_speedbump_irreversible.py::TestCpRmrfTempRoots::test_a_checkout_deeper_inside_the_target_is_a_declared_limit`).
   The forced PowerShell remove reads a relative target where the command
   starts, so after a location change into scratch it keeps the nudge the
   unforced form no longer draws, a declared limit
   (`tests/test_speedbump_irreversible.py::TestCpRmrfTempRoots::test_a_forced_relative_remove_after_a_location_change_is_a_declared_difference`).
   The sweeps and cmd's deletes read no binding and no location change, so
   only an absolute target of theirs can be scratch, a declared limit
   (`tests/test_speedbump_irreversible.py::TestCpRmrfTempRoots::test_a_sweep_or_a_cmd_delete_reads_only_an_absolute_target`).

   Two more launch forms of the same recursive delete meet the plain
   form's tiers: on the PowerShell tool the native remove binary by its
   file name or a path (`rm.exe -r`, a path ending in `rm`, `rmdir` or
   their `.exe`, bare or quoted behind the call operator), and on both
   tools cmd.exe's own recursive deletes (`rd /s`, `rmdir /s`, `del /s` or
   `erase /s` in a program `cmd /c` runs, cmd's `%USERPROFILE%` read as
   your home directory) -- the wall on a catastrophic target, nothing on a
   roster build directory, one nudge on any other. On both tools the zone
   check reads every delete cmd runs, so a protected directory removed
   through cmd meets the nudge and then the zone wall on the re-issue, the
   plain form's order. Declared limits: a `cd` inside cmd's own program is
   not followed (the target is judged from where cmd starts and from an
   unknown directory;
   `tests/test_write_guard.py::TestEveryLaunchFormMeetsTheRecursiveDeleteWall::test_a_cd_inside_cmds_program_is_a_declared_limit`),
   a `del /s` with a narrowing pattern (`*.pyc`) is the zone check's
   alone, as a narrowed `find` is
   (`tests/test_write_guard.py::TestTheCmdDeleteReaderReadsEachBranch::test_the_bash_launch`),
   and a bare path longer than 256 characters before the native binary's
   name is read by no reader
   (`tests/test_write_guard.py::TestEveryLaunchFormMeetsTheRecursiveDeleteWall::test_the_native_path_cap_is_a_declared_limit`).
   Every form the readers declare is crossed with the hard-tier texts'
   target claims by
   `tests/test_write_guard.py::TestEveryLaunchFormMeetsTheRecursiveDeleteWall`.

   The
   same sweeps as the Bash tool's are walled on the PowerShell tool: an
   un-narrowed `find` with a delete action, and an enumerator piped into
   a remove verb that recurses or a files-only enumeration
   (`Get-ChildItem -Recurse | Remove-Item -Recurse -Force`, by any alias
   or prefix, across a line break after the pipe; `-Include`, `-Filter`,
   a positional filter or a wildcard root narrows it only by a value that
   excludes something -- a catch-all such as `*` narrows nothing, and a
   root whose leaf is a bare `*` is its directory), and the recursive .NET
   directory delete (`[IO.Directory]::Delete(<path>, $true)`, read from
   the process directory), each judged from its root -- the current
   location when the enumerator names none -- after the command's own
   `Set-Location`; a variable in the root is refused there, as the
   Remove-Item tier refuses it. The native single-file deletes (`unlink`,
   `shred`), `truncate` and `git clean` reach the zone check on the
   PowerShell tool as they do on Bash. Any stage between the enumerator
   and the remove verb (a `Where-Object`, a `ForEach-Object`, a
   `Sort-Object`) is a declared limit, pinned by
   `tests/test_write_guard.py::TestCatastrophicEnumeratorCarrier::test_powershell_classifier_matrix_carrier`.

   A command the shell DISCOVERED and
   invoked is read as the command it names on every head of both tools:
   the call operator or the dot-source operator on a `Get-Command` object
   (`& (Get-Command find) . -delete`, `& (gcm ri) -Recurse -Force .`, a
   switch such as `-Name` or `-CommandType Application` on either side of
   the verb, a doubled paren, the object's `.Source`, `[0]` or a member
   call) and the Bash command substitution (`$(which find) . -delete`,
   `"$(command -v rm)" -rf .`, `$(type -P find 2>/dev/null)`, a path to
   `which`, `--`, the backtick form, behind a wrapper word; and under zsh
   -- the Bash tool runs the operator's login shell, zsh on a macOS host
   -- `$(whence find)`, `$(where find)` and the equals expansion `=find`)
   -- each resolved once on the scan text before any head reads it, with
   the verb kept at its offset, so a discovered head meets the same wall,
   nudge and zone check as the bare one. What the resolution does not
   read is a declared limit, pinned by a matrix row that fails the day it
   closes (`tests/test_write_guard.py::TestCatastrophicFindDelete::test_classifier_matrix`
   on Bash, `tests/test_write_guard.py::TestCatastrophicFindDelete::test_powershell_classifier_matrix`
   on PowerShell): the discovered path held in a variable (`$f = Get-Command find;
   & $f`; `x=$(which
   find); $x`), a pipeline or a list inside the sub-expression or the
   substitution (`(Get-Command find | Select-Object -First 1)`, `$(which -a
   find | head -1)`), a parameter as the discovery verb (`${WHICH:-which}`),
   and a discovery that is not `Get-Command` or a `which` family verb
   (`(Get-Item /usr/bin/find)`, a `[System.IO.FileInfo]` literal).

   On both
   tools the enumerator
   may hand its paths to the remove verb through `xargs` -- a `find` with
   no action, `ls`, or the version-control listing `git ls-files` -- and
   is read the same way: the enumerator's roots are the remove verb's
   operands, a files-only walk, a recursing remove or any walk into a
   native remove verb behind the carrier (`/bin/rm` takes every file a walk
   hands it, where a cmdlet prompts and aborts) is the wipe, and a
   narrowing predicate narrows by its value; the verbs behind the carrier
   are the find arm's `-exec` roster on both tools.

   The version-control
   listing walks the index whole under the current location and prints
   files only, so the tracked population (and the ignored one) is the wipe
   from the checkout root; its untracked-only population with the standard
   excludes applied is `git clean`'s untracked form and draws the nudge
   instead; a bounded pathspec or wildcard narrows, an exclude pathspec
   narrows nothing, a redirection in the span is not a pathspec, and a
   global option before the subcommand (`git -C <dir> ls-files`, the value
   bare or quoted) makes `<dir>` the root -- read as the root because the
   guard asks where the listed names can point, not where they were listed
   (the remove verb runs in the shell's directory, not the listing's). On
   the PowerShell tool the listing piped straight into the cmdlet
   (`git ls-files | Remove-Item`) is the same wipe: the cmdlet binds a
   path from the pipeline by value. A stage between the enumerator and
   `xargs`, a single path echoed into it, and a shell opened behind the
   carrier (`xargs sh -c`, the reader roster's standing limit) stay
   declared limits, pinned by
   `tests/test_write_guard.py::TestCatastrophicEnumeratorCarrier::test_classifier_matrix_carrier`
   and, through the hook,
   `tests/test_write_guard.py::TestCatastrophicEnumeratorCarrier::test_through_the_hook_carrier`.

   The loop carrier -- the enumerator's output bound to
   a loop variable and removed in the loop's body, on the Bash tool -- is
   read too (DEF-830): the pipe into a read loop, the for loop over a
   command substitution and the read loop fed at its tail each hand the
   remove verb every path the enumerator lists, so they are judged by the
   enumerator's root through the same tiers as the carrier (until
   2026-09-17 the variable operand drew only the soft tier's nudge). A
   body that removes a fixed operand instead of the variable is the rm
   tier's own.

   A for loop over a bare word list is read as well
   (DEF-837): it has no enumerator, so each listed word is judged as the
   direct remove of that word is -- `for f in *; do rm -rf "$f"; done`
   draws the wall `rm -rf *` draws where that directory is the checkout,
   the home or the root, and inside a build directory too, since a loop
   is not a plain command (the bare-glob rule above), while a narrowed word (`build/*`) or a
   body that does not recurse keeps the verdict its direct twin draws
   (until 2026-09-18 the bare glob drew only the nudge, and behind a body
   that pipes each item into `xargs rm -rf`, nothing). Like the other
   loop heads it walls a recursing body whether or not it forces: `rm`
   prompts only for an unwritable file and only on a terminal, so `rm -r`
   in an agent's shell is the same wipe -- and since 2026-09-18 the direct
   `rm -r *` meets the same wall (the direct remove read recursive AND
   forced until then). A word list naming a protected path meets
   the protected-zone check as the direct remove does.

   Declared limits,
   each pinned as a row
   (`tests/test_write_guard.py::TestCatastrophicLoopCarrier::test_classifier_matrix_loop`;
   the wrapped body and the trailing slash by
   `tests/test_write_guard.py::TestCatastrophicLoopCarrier::test_a_for_loop_over_a_word_list_meets_its_twins_verdict_loop`):
   a stage between the enumerator and the loop, a
   pipeline inside the body before the remove, a stage inside the
   substitution, the pipe on the line after the enumerator, a loop fed
   from a file, a glued value on the read builtin's switch, more than four
   statements before the remove, a word list beside a command
   substitution, a body that WRAPS its remove in a subshell, a brace group
   or a case arm, and an item operand carrying a trailing slash. The last
   two are the shape of the whole list: the reader looks for the remove
   verb at a statement start of the body's own run and for an operand that
   is exactly the loop variable, so a body or an operand spelled any other
   way is read by no loop head. Each draws the variable operand's nudge
   behind a plain
   recursing remove -- so a catastrophic word beside a substitution draws
   that nudge where its direct twin walls -- and behind a body that pipes
   each item into `xargs rm -rf`, a stage between and a word list beside a
   substitution draw nothing at all: declared limits too, each pinned as
   the verdict it draws by
   `tests/test_write_guard.py::TestCatastrophicLoopCarrier::test_through_the_hook_loop`.

   The PowerShell statement-form loop over a listing
   is the remove cmdlet's variable-operand wall already; the item piped
   INTO the cmdlet inside a loop body (`foreach (...) { $f | Remove-Item
   -Recurse -Force }`) draws that tool's nudge instead -- the listing in
   the loop header is read as the pipe's source across the block brace --
   a declared limit pinned by a strict expected-failure row
   (`tests/test_write_guard.py::TestCatastrophicLoopCarrier::test_the_powershell_carrier_in_the_loop_body_walls_loop`),
   so the day a reader closes it the row reds. The same Bash text is inert under pwsh.

Additionally, Bash commands that write to protected paths via redirects
(`> file`), `tee`, `sed -i`, `cp`/`mv`, `git checkout`/`restore` (the `--`
separator bare or quoted, a global option such as `-C <dir>` between `git`
and the subcommand; the same three arms on the PowerShell tool), or
inline interpreter source (`python -c`, `node -e`, `ruby -e`, `perl -e`,
and the same interpreters fed their program on stdin -- `python3 - <<'PY'
... PY`, `python3 <<EOF`, `python3 - <<< "..."` -- or by a pipe: `echo
'...' | python3 -`, `cat <<'PY' | python3 -`, where the program is the stage
before the pipe, its last quoted literal or its heredoc body) are caught:
the literal write paths inside the program body are read, computed ones
are not, and a body that is data to a script or module operand (`python3
script.py <<EOF`, `... | python3 -m json.tool`) is not a program. A
program operand is read as the one shell word it is -- adjacent quoted
and bare segments concatenated with the shell's quote removal -- so a
path quoted inside a single-quoted program (spelled by ending the outer
quote, spliced or naively, which the shell accepts and strips) reaches
the reader as the shell hands it on; the same word reading serves a
POSIX shell's `-c` body and the `powershell -Command` operand, and a
redirect or copy target spelled as adjacent segments is read whole. The hook
expands simple `VAR=value; ... > $VAR` patterns before checking, on both
shells (`$p = '<hook>'; Set-Content -Path $p` on PowerShell), each
reference taking the most recent binding before it, so single-variable
indirection doesn't bypass protection. On Bash the binding may use any case
of name, sit behind `export`, `local`, `declare`, `typeset` or `readonly`,
follow any statement separator or open a group, or head an `eval` or `-c`
program. A binding inside a quoted argument or a comment is a mention and
binds nothing, and one made in a child scope (a subshell, a command
substitution, a shell's `-c` program) ends where the scope ends. A value
stored in a variable is the shell's data -- a message variable that quotes a
delete or a protected write is not refused -- until the shell runs it
(`eval "$MSG"`, `bash -c "$msg"`, `$CMD`, an interpreter program it is
expanded into), which is read where it runs. One exception, a declared limit
in the friction direction (pinned by
`tests/test_write_guard_command_position.py::TestAnAssignmentValueIsReadAsTheShellReadsIt::test_a_declaration_builtins_value_keeps_its_separator_live`):
a value given to `export`, `local`, `declare`,
`typeset` or `readonly` is an argument of that builtin, and a separator inside
it is still read as a statement boundary -- so a message variable DECLARED
with one of those, quoting a delete with a separator in it, is refused where
the same message stored by a bare assignment is data. Not a simple oversight:
under an array or an integer attribute (`-a`, `-i`) bash evaluates such a
value and a substitution inside it runs (measured on bash 3.2, 2026-09-19), so
the relief a bare assignment gets cannot be handed to these builtins by name
alone. A name given an evaluating attribute EARLIER in the command has the
same effect on a later bare assignment to it, and is relieved today: the
accepted cost of reading an assignment's value as the shell's data. Declared limit (pinned by
`tests/test_write_guard_command_position.py::TestAnAssignmentValueIsReadAsTheShellReadsIt::test_the_declared_limit_stays_a_limit`):
a value the expansion cannot read -- a command substitution or a `$` reference
inside it, a parameter expansion, an array, a second assignment in one
statement, a value that runs on past its quotes -- that the shell later runs
through `eval` or `-c` is not refused unless its own text puts the verb at a
command position. The operand a verb
REMOVES or RELOCATES is read beside the written one, on both shells and
through an interpreter literal: a delete of it, a move of it out of the
zone, a rename within it, a `find` that removes under it, a `git clean`
that takes it, and a delete or a move of a directory that encloses it. The
verb rosters and the declared limits are one table, driven by name, in the
guard's test class, at
`tests/test_write_guard.py::TestRemovedOrRelocatedOperandIsAMutation::test_every_consumed_arm_has_a_deny_row_and_every_row_names_a_consumed_arm`
(Espalier
source repo -- not deployed by `init`).

A program under an interpreter head is also read for what it HANDS TO A
SHELL, and that text meets the Bash dangerous records, the write extractor,
the secret-read roster and the speed-bump checkpoints as a program of its
own, one level down: the literal given to Python's `os.system`, `os.popen`
or the `subprocess` family (a string, an argv list, a `shlex.split` or
`.split()` literal), Perl's `system`, `exec`, backticks, `qx` or a piped
`open`, node's `child_process` family, Ruby's `system`, `exec`, `spawn`,
backticks, `%x`, `IO.popen` or `Open3`, awk's `system`, a `print` into a
command or a command into `getline`, GNU sed's `e`, and git's shell doors:
an alias or credential helper behind `!`, an exec-valued config value
(`core.pager`, `core.editor`, `core.sshCommand`, `core.fsmonitor`,
`core.askpass`, `diff.external`, `sequence.editor`, `gpg.program`, the
`filter.*.clean` / `smudge` / `process`, `diff.*.textconv` / `command` and
`difftool.*.cmd` / `mergetool.*.cmd` shapes) given with `-c` or written by
`git config`, and the arguments of `submodule foreach`, the `filter-branch`
filters, `rebase --exec` / `-x`, `bisect run` and `difftool --extcmd`.

An
awk or sed program that executes its input (`system` on a non-literal, a
bare `e`, `s///e`, a variable printed into a shell) makes the input stream
live -- a here-string, a heredoc body or the stage piped in -- and awk's
`-v` values with it; an awk or sed program's own file writes (`print >
"path"`, `>>`, sed's `w path` command and flag) meet the write extractor. A
program on a POSIX shell's stdin by here-string or pipe (`bash <<< "..."`,
`sh<<<'...'`, `echo "..." | sh`, `printf '%s' '...' 2>/dev/null | bash`) is
read the same way.

Because the program is read, the rest of it is data: a
string that only quotes a command, a commit message, a `git grep` pattern, a
stream to a sed program that does not execute it -- mentions, not
invocations -- so `python`, `perl`, `node`, `ruby`, `awk`, `sed` and `git`
sit on the non-re-parsing side of the mask.

Declared limits, pinned by
`tests/test_write_guard.py::TestShellOutReader::test_the_declared_limits_of_the_shell_out_reader_are_pinned`:
a shell-out whose argument is not a literal (a variable, an argv element;
an f-string is read as its literal text, a name inside it left unresolved),
a program read from a file (`python3 x.py`, `awk -f`, `sed -f`, a git
hook), a git config key or subcommand outside the sets above (`mergetool`,
`send-email`), program arguments after a piped `-`, a heredoc body line that
spells a pipe into a consumer (read as one: the over-read direction), and a
shell-out spelled inside another string of the same program, which is read
as the call it spells.

The same interpreter programs are caught on the PowerShell tool: `python -c`,
`node -e`, `ruby -e`, `perl -e` and the `py` launcher, the head given as a
bare or `&`-called quoted executable path, valued switches before `-c` (on
both shells: `python3 -W ignore -c "..."` denies on Bash too), and a
program piped to the interpreter (`@'...'@ | python -`, `'...' | node`) or
to a PowerShell reading stdin (`| pwsh -Command -`), whose program -- the
last here-string or quoted literal before the pipe -- is scanned as
PowerShell; a `-File <script>` there means the pipe is data. A variable
holding the program, a program read from a file, `Start-Process python
-ArgumentList "-c ..."`, a here-string as the `-c` argument and a quoted
switch value before `-c` are declared limits, pinned by
`tests/test_write_guard.py::TestPowerShellInterpreterProgram::test_the_documented_limits_are_pinned`.

A program handed to the OTHER shell is judged by that shell's grammar, not
by the tool it arrived on: `powershell -Command "..."` / `pwsh -c '...'` on
the Bash tool (the quoted program in any of bash's quote kinds, the bare
rest-of-line program, the switchless positional program Windows PowerShell
reads as `-Command`, a `/`-led switch, and a heredoc or here-string fed to
the shell on stdin) is read by the PowerShell extractor, read-verb roster
and dangerous records, and `bash -c "..."` / `sh -c '...'` on the
PowerShell tool (the head bare or given by path, the `-c` bare or clustered
as `-lc`) by the Bash ones -- one level down, and a program that re-enters
the first shell one level further, no more. A program piped to `-Command -`
on the Bash tool (`echo '...' | pwsh -Command -`, `cat <<'EOF' | pwsh
-Command -`) is read as the stage before the pipe, like an interpreter's;
`-File <script>` there means the pipe is data. `-EncodedCommand`, `-File
<script>`, a program held in an unbound variable (a literal binding earlier in the command
is inlined first) and `wsl bash -c` are declared
limits, pinned by `tests/test_write_guard.py::TestCrossShellRouting::test_bash_tool_declared_limits_are_pinned`
and `tests/test_write_guard.py::TestCrossShellRouting::test_powershell_tool_declared_limits_are_pinned`;
`cmd /c` is a third grammar the hook has no extractor for
(`tests/test_write_guard.py::TestCrossShellRouting::test_cmd_c_verdicts_are_pinned_not_claimed`).

Two more declared limits sit on this reading, each pinned as the exact verdict
it draws by
`tests/test_write_guard.py::TestCatastrophicRmFlagOrderIndependent::test_the_declared_cross_shell_limits_draw_exactly_the_verdict_they_declare`
and, on the reader side, by
`tests/test_write_guard.py::TestCatastrophicRmFlagOrderIndependent::test_no_reader_hands_the_nudge_a_program_given_to_ssh_or_the_other_shell`.

**Another host.** A program handed to a shell over `ssh` as an argument is not
read at all -- not as that shell's program and not as text: the verb is an
argument of `ssh`, never at a command position, so `ssh host 'rm -rf /'` and
`ssh host rm -rf /` are allowed (until 2026-09-22 this sentence said the text
still met the Bash records; driven, it does not). A program fed to `ssh` on
stdin -- a heredoc or a here-string -- is a shell program on stdin and IS read,
so the same wipe spelled that way walls. What the guard protects is this
checkout and this machine's home; a tree on another host is neither, and no
reader claims otherwise.

**The nudge reads one shell.** The confirm-once
checkpoints read the Bash command and the Bash programs nested in it; a program
the Bash tool hands to PowerShell (and one the PowerShell tool hands to `bash`)
is read by the hard tier only, so such a program meets the wall or nothing,
never the one-re-issue nudge.

**The nested program's directory** was declared a
third limit on 2026-09-19 ("judged from the payload's directory, not from a
directory the outer statement moved to") and is not one: read at the site and
never driven then, it was driven on 2026-09-22 and the outer statement's
placement reaches the nested program in both directions --
`cd .. && bash -c 'rm -rf <checkout>'` walls where the same program from the
root nudges, and `cd sub && bash -c 'rm -rf .'` nudges where the same program
from the root walls (the same rows pin it:
`tests/test_write_guard.py::TestCatastrophicRmFlagOrderIndependent::test_the_declared_cross_shell_limits_draw_exactly_the_verdict_they_declare`).

What the nested reading still
cannot see is the receiving shell's own location change inside the program --
a declared limit, pinned by
`tests/test_write_guard.py::TestCatastrophicRmFlagOrderIndependent::test_a_statement_handed_to_another_shell_withholds_the_glob_relief`:
the unknown directory joins the bases, so a bare glob there walls.

A permission, ownership, attribute or ACL change on a protected path is
caught as a write too, because it silences a hook as surely as one: on
Bash `chmod`, `chown`, `chgrp`, `chflags`, `chattr` and `setfacl`; on the
PowerShell tool `icacls`/`cacls` (under any switch that is not a read),
`takeown`, `attrib` (with an attribute token), `cipher` (under `/e` or
`/d`), `Set-Acl`, `Set-ItemProperty`, the property-assignment form
`(Get-Item <path>).IsReadOnly = $true` (either direction, `Attributes` too)
and the .NET static file API -- `[IO.File]::SetAttributes`, `::WriteAllText`,
`::AppendAllText`, `::Copy` and `::Move` (by destination), `::Replace` (by
destination and backup), `::Delete`, `[IO.Directory]::Delete` and every
other method not on the read list (`Exists`, `ReadAllText`,
`GetAttributes`, ...), and its object spelling -- `[IO.FileInfo]::new(<path>).Delete()`,
the `DirectoryInfo` twin, the `([IO.FileInfo]'<path>')` cast, `.MoveTo` and
`.Replace` (the object and the destination), `.CopyTo` (the destination),
`.IsReadOnly` or `.Attributes` assigned on such an object, and every other
method not on its read list (`Refresh`, `OpenRead`, `GetFiles`, ...; a bare
constructor and a property with no call are reads); a path built by an
expression or held in a variable with no literal binding earlier in the command (a bound
one is inlined first), a call continued on the next
line and a comma inside the path literal are declared limits there, pinned by
`tests/test_write_guard.py::TestPowerShellDotNetFileApi::test_dotnet_declared_limits_are_pinned`. The
PowerShell write forms themselves (`Set-Content`,
`Out-File`, `Add-Content`, `Tee-Object`, `New-Item`, the `>` redirect,
`Copy-Item`/`Move-Item` and their aliases) are caught on that tool as the
Bash forms are on Bash; a bare `icacls PATH` or `attrib PATH` displays and
is a read, and a bare or `&`-called quoted executable path before any of
these heads (`& "C:\Windows\System32\icacls.exe" <hook> /deny ...`) is the
head, behind either wrapper quote kind -- and since DEF-791 (2026-09-13) the
call operator with a quoted command name (`& 'Set-Content' <hook> x`, `&
"git" reset --hard`, `& 'C:\Program Files\Git\cmd\git.exe' reset --hard`) is
read by every PowerShell verb arm and by the git discard bump, not only by
the executable heads: the quote opens a command position behind `&` alone,
never behind `=`, so a string assigned or printed stays data. A double-quoted program handed to a
re-parser (`powershell -Command "cd x; <write>"`, `iex "...; ..."`, the
`@"..."@` here-string behind either) keeps its separators, its pipes, its
call operator and its redirects live, because real PowerShell runs the
second statement of such a program whether or not the first is an
interpolated token; the one character masked inside it is the `=` that would
make an interpolated token the left side of an assignment, which never
happens (so `iex "$env:<var>=1; claude"` stays ordinary). Until 2026-09-10
every expandable span was masked wholesale and the double-quoted twin of a
refused single-quoted program was allowed. A
re-parsing wrapper on the PowerShell tool (`Invoke-Expression`,
`powershell -Command`, `pwsh -c`, `cmd /c`, `Start-Process powershell
-ArgumentList`, and a script block built from a string,
`[scriptblock]::Create("...")`, whether or not the same statement invokes
it) is read through to its quoted payload, and a switch's bare
value between the two (`-Verb RunAs`, `-ExecutionPolicy Bypass`,
`-WindowStyle Hidden`) is crossed, so an elevated or policy-bypassed write
is caught like the bare one. A value that is itself a quoted string
(`-Verb "RunAs"`), an `=`-bound value (`-ArgumentList="..."`) or the array
spelling (`-ArgumentList "-Command","..."`) ends the run before the payload,
which then stays inert -- a declared limit, pinned by
`tests/test_write_guard_command_position.py::TestPowerShellReparsingWrapperCarriesASwitchValue::test_the_declared_limits_are_pinned`.

Reads of secret-bearing paths -- dotenv files (a dotenv TEMPLATE, the
`.env.example`, `.env.sample`, `.env.template` or `.env.dist` a repo commits
so a newcomer can copy it, is not one, and a copier's destination is a
write, so `cp .env.example .env` runs), a `secrets/` directory, AWS
and JSON credential files -- are denied on the `Read` tool and, when a
read verb names the path in the same statement, on Bash (`cat`, `head`,
`cp`, `source`, ...) and on the PowerShell tool (`Get-Content`, `gc`,
`type`, `Format-Hex`, `Copy-Item`, the dot-source, ...), each shell read
with its own statement grammar and roster; the two rosters are pinned to
each other class for class, and a program handed to the other shell
(`powershell -Command "Get-Content .env"` on Bash, `sh -c 'cat .env'` on
PowerShell) is read with that shell's roster. A grep-shaped search of the
file is not a read verb on either shell, and a mention inside a string or
comment is inert.
This is the hook-layer replacement for the `Read()` deny rules `init` no
longer emits (see `CLAUDE.md`'s hook table for why).

**The time budget.** Claude Code cancels a hook at its wired `timeout` (5 s
for this one), and a cancelled PreToolUse command hook does not block: the
call goes on through the normal permission flow
(`docs/external/cc-hook-protocol.md`, "Timeouts"). So `write_guard` judges
every call, on every tool and under maintenance mode too, within its own
budget of 3.5 s from the hook's start (`JUDGMENT_BUDGET_S` in
`tools/cc/hooks/write_guard.py`). An ordinary call finishes in a small
fraction of that and sees no change. A judgment still running when the
budget runs out -- a long generated list of paths is the shape that gets
there -- is denied the way the guard denies any call, one deny decision on
stdout whose reason tells the agent the guard could not finish judging the
command in time and to split it into shorter commands (batches of a hundred
or two paths), and it writes one `pretooluse_blocked_time_budget` record
that `/status --log` counts. A git the judgment asks (the discard snapshot, a dirty-tree check)
is given only the budget that is left, so on a large repo or a cold cache a
slow git costs its snapshot, said once, and the call is still judged. A
state write the judgment has in flight finishes before the hook
exits, so a refusal never leaves a torn line in a log; a write that hangs
holds the refusal with it until the timeout lets the call through, a
declared limit, pinned by
`tests/test_write_guard_time_budget.py::TestASlowJudgmentIsRefused::test_the_refusal_waits_for_a_state_write_in_flight`.

**What you see when blocked:**

> Write to protected harness zone blocked: tools/cc/execution_plan.py.
> Harness self-edits: exit and relaunch with maintenance mode on ...
>
> (followed by the `Don't:` / `Do:` pair, which spells the maintenance-mode
> relaunch for your shell -- see docs/HOOKS.md "Maintenance mode")

or:

> Dangerous command blocked: a recursive delete of the filesystem
> root itself ('rm -rf /'). If this was a deliberate, scoped cleanup,
> narrow the target to the directory you mean: a path inside the repo or
> inside your home directory, or under a temp root, is not refused here
> (scratch below a temp root that is no git checkout, and a relative
> build/ or dist/, pass without a nudge; the rest draw one
> confirm-by-re-issue nudge); the filesystem root, your home directory or
> the repo itself (a bare '*' glob or $PWD counts as the directory the
> delete runs in when the command is plain, and is refused when it is
> not), a shallow system path such as /etc or /usr/local, and an absolute path
> with a '..' step are refused in every flag order -- then re-run.

or (kill-switch):

> Espalier-Harness kill-switch setting detected: ['disableAllHooks:
> true in .claude/settings.json']. Remove the setting and run
> `espalier integrity verify .` before continuing.

**What this does NOT catch :**

- Two-step bypass: write a script to `/tmp/`, then execute it. The
  subprocess does the actual write and write_guard can't see inside it.
- Multi-step variable indirection across separate commands, and a variable
  with no literal binding earlier in the command (a bound one is inlined first, on both
  shells).
- Runtime path construction, `$(...)` command substitution, `${VAR:-default}`.
- Anything requiring actual execution to determine the target path.

These are documented limits, not bugs. The full bypass scope is catalogued in
the Espalier source repo's own `docs/SHARP_EDGES.md` — read it there if you have
the harness cloned. Your `docs/SHARP_EDGES.md` is a stub `init` seeded for you to
grow; `/analyze` and `/debug` fill it with your repo's footguns, not these.

**Configuration:**

| Control | Effect |
|---------|--------|
| `ESPALIER_MAINTENANCE_MODE=1` | Bypasses the protected-zone check. Kill-switch gate, dangerous-command blocking and the speed-bump checkpoints (`CP-*`, which dispatch before the maintenance gate is read) still run. One advisory audit record per session says so (`pretooluse_bypassed_maintenance_mode`; `/status --log` counts it). |

**Denial-hint surface.** Protected-zone denials append a
discoverability hint pointing at the maintenance-mode escape:
the `_PROTECTED_ZONE_HINT` constant in `tools/cc/hooks/write_guard.py`.
The hint names the relaunch command for the host's shell --
`ESPALIER_MAINTENANCE_MODE=1 claude --continue` on POSIX;
`$env:ESPALIER_MAINTENANCE_MODE="1"; claude --continue` (PowerShell), plus the
cmd.exe and Git Bash forms, on Windows -- spelled once by
`_maintenance_mode.relaunch_hint()` -- and notes the
parent-shell-launch gotcha (env read at launch; mid-session export is
ignored; `--continue` keeps the session the deny happened in). The hint is
attached only to protected-zone denials — kill-switch and
dangerous-command denials use their own reason channels.

---

### 5. `config_guard.py` — Settings change protection

**Event:** ConfigChange · **Can block:** Yes (project/local/user settings)

Fires when Claude Code modifies settings. Scans the incoming settings
for kill-switch patterns. If found in project, local, or user settings,
the change is blocked. If found in managed `policy_settings` (which the
hook protocol says cannot be blocked), the hook writes an audit record
(`configchange_policy_settings_kill_switch_detected`); its `[WARN]` line goes
to stderr, which reaches only the debug log -- ConfigChange has no channel to
Claude or to your terminal. A `bypassPermissions` default is not judged here: it is
not a kill-switch, a ConfigChange block is shown to no one and does not revert
the file, and the mode is chosen at launch. What stops a session writing one is
`write_guard`'s protected-zone deny on the writes it reads to both settings
files; under `ESPALIER_MAINTENANCE_MODE` that zone check is off, so such a
write is not refused, and the posture is named at the next SessionStart.
SessionStart's `Permissions:` line and `doctor` name it, and `ci_guard` fails a
committed one.

**A change that unwires the gates.** Removing the project
`.claude/settings.json`'s `hooks` key, deleting the file, or dropping a blocking
gate's entry switches those hooks off for the session, mid-session (driven on
Claude Code 2.1.294: every hook at once). So a change to the PROJECT file that
leaves a governance gate (`write_guard`, `plan_guard`, `config_guard`,
`stop_gate`) without executable, correctly-matched wiring is refused
(`configchange_blocked_unwired`), and the session keeps its hooks. It judges
the CHANGE: the gates lost are those the session was running -- recorded at
SessionStart in `.espalier-state/wired_gates.json`, and again whenever a
change is let through -- so a tree already missing a gate, or wired in the
pre-v0.6.5 shell form the exec-form reader cannot prove, keeps its other edits.
A deleted, emptied or syntax-broken project file wires nothing -- Claude Code
loads no hooks from any of them (driven) -- and is judged so; refusing it
blocks no repair, since the next change is judged on its own content.
The local file keeps the kill-switch check only; it normally wires nothing. A
hook entry of type `http` or `mcp_tool` runs no gate and is set aside rather
than read as voiding the file. `espalier clean-generated`'s in-session
uninstall records its own unwire first
(`.espalier-state/settings_write_intent.json`), and that one write is let
through, so its two-run flow still works.

The refusal is silent by protocol and the file on disk keeps the change, so the
NEXT session would start without those gates. `config_guard` notes it, and the
next PostToolUse tells Claude once, with the restore:
`espalier merge-settings --repair` (or `espalier init .` when the file was
deleted), then `espalier doctor`.

**What you see when blocked:**

> Espalier-Harness kill-switch setting detected in project change:
> ['disableAllHooks: true ...']. Remove the setting and run
> `espalier integrity verify .` before continuing.

**Configuration:** None. This hook is simple and important — it prevents
the agent from disabling its own governance mid-session.

---

### 6. `post_write_check.py` — Post-write validation

**Event:** PostToolUse · **Can block:** No

After every Write/Edit to harness infrastructure files, this hook
validates the result:

- `.claude/settings.json` → checks JSON parses cleanly
- `.claude/agents/*.md`, `.claude/commands/*.md`, `.claude/skills/*/SKILL.md`
  → scans for placeholder values (`<repo>`, `<fill>`, `INSERT HERE`,
  `TEMPLATE_ONLY`); all three kinds are harness files, so a write to any
  of them also runs the integrity spot-check below
- `tools/cc/**/*.py` → runs `compile()` to catch syntax errors
- Root governance docs (`CLAUDE.md`, `ESPALIER_MEMORY.md`, etc.) → placeholder scan
- Any non-allowlisted write in a protected zone → integrity drift check
- The record files (`ESPALIER_MEMORY.md`, `task-packs/FORWARD_LEDGER.md`,
  `task-packs/LEDGER_PROBES.json`) → scans the written file for a leftover
  merge-conflict marker (a line opening with git's seven-character head and
  a space, or nothing). The finding names the file and the lines on the tool
  result, like every finding of this hook (below), and the catch belongs at
  the write; the merge gate (`tools/cc/ci_guard.py`) refuses the same lines at
  the pull request, unconditionally, and the ship driver refuses to open a
  pull request on a lane that carries one. The rule is column zero, so a
  line that only quotes a marker is read as one too: indent the quote by one
  space. The same rule guards the SessionStart banner's memory digest, which
  skips the marker lines and names them instead of reading them as the
  memory's first lines (a hand merge through Bash reaches no write hook)
- After every Bash or PowerShell call → compares the protected files with
  the session's previous check (below)

**The protected files after a shell call.** A shell call can change a
protected file without naming it -- a formatter run over the whole tree, a
script, a copy -- and `write_guard` judges a command by the paths it names.
So SessionStart takes a snapshot of the protected files for every session
(size, modification time and a hash of the line-ending-independent content,
kept beside the session's marker under `.espalier-state/sessions/`; taken
after the checkout catch-up, and kept across a compaction), and after each
Bash or PowerShell call this hook compares the files with it and takes the
new state as the next one to compare with.

- **What it watches:** `tools/cc/`, the protected files
  `.github/workflows/harness-guard.yml`, `.espalier/integrity.json` and
  `.espalier/freshness.json`, and the `protected_paths` in `espalier.toml`; on
  the harness's own source tree, `espalier/` and `.github/workflows/` as well.
  Not `cc/`, whose files the harness's own tools rewrite (the blueprint chain,
  the plan and its archive), and which `write_guard` still guards by path. Not
  the two settings files: `config_guard` sees every settings change, Claude
  Code's own writes included (a "don't ask again" answer writes
  `.claude/settings.local.json`), and judges the ones that matter. Not
  `generated_paths`. The walk skips dependency, cache and tool directories
  (the stack's `node_modules` and its siblings, `__pycache__`, `.mypy_cache`,
  a virtualenv, and your `dependency_dirs`) and editor and OS clutter (swap
  and backup files, `.DS_Store`). A file of 4 MiB or more is identified by its
  size and modification time and never read.
- **What it stays quiet about**, because a legitimate path accounts for it:
  1. content a file tool wrote (Write, Edit, NotebookEdit, an MCP write) --
     in this session or in another live session in the same checkout -- or
     content this check already accounted for or reported, so a stash and its
     pop, or a return to an earlier state, stay quiet;
  2. committed history: a file that now holds its content at `HEAD` (a pull,
     a merge, a checkout, the session catch-up), or a removed file that is
     absent at `HEAD` and was present at the `HEAD` of the previous check (a
     branch switch or a rebase that drops it, however many moves the call
     made). A deleted untracked file is never git's;
  3. on the harness's own source tree only, a byte mirror that now equals its
     source (the vendored hook copies, the packaged docs and `.claude` assets);
  4. an `espalier` command that rewrites protected files (`init`, `upgrade`,
     `merge-settings`, `clean-generated`, `integrity`, `install-ci`, the
     freshness pins), which records what changed during its own run under
     `.espalier-state/zone_writes/`, read only when the run ended after the
     session's previous check. A change made before the command started, in
     the same shell call, is not in its record and still reports.
- **What it holds back:** while git is half way through an operation (a merge
  or rebase stopped on a conflict, a cherry-pick, a bisect) or an `espalier`
  writer is still running, a change is not judged and the snapshot is kept;
  the result is judged once they are done.
- **What it reports** is a protected file whose content none of these
  accounts for, split by when it landed. A change that landed **during** the
  shell call (this call or a parallel one; the call began `duration_ms`
  before the hook ran) is told to Claude beside the tool result, which is
  asked to stop and tell you, and a subagent to pass it on. A change that
  landed **before** the call began -- your editor, another session, a
  background job -- is told to you only, so Claude is not asked to stop for
  what it did not do. Either way the hook's `systemMessage` names the files
  for you, once per file and content per session (the line has been seen in
  a session transcript; how a terminal shows it is not yet recorded), and one
  audit record, `post_shell_zone_change`, names them by kind. It never says
  the command wrote them. Maintenance mode does not switch it off; with
  `write_guard`'s zone check off, it is the one zone signal left.
- **A session with no snapshot** (one that started before this check
  existed, or a state directory that would not take one) has its first shell
  call taken as the snapshot, unchecked, and says so to Claude once
  (`posttooluse_failed_open_zone_unchecked`). A watched set too large to walk
  inside the budget (20,000 files or 3 s) turns the check off for the session
  and says so once (`posttooluse_failed_open_zone_off`): narrow
  `protected_paths`, or name the large directories in `dependency_dirs`.
- **Limits.**
  - A bad edit committed in the same shell call (`python fix.py && git commit
    -am wip`) is silent: the file then holds its content at `HEAD`. The
    commit still reaches `main` only through the pull request and CI.
  - A rewrite that keeps the file's size and modification time (`cp -p`,
    `touch -r`, an archive extracted with its times) is not seen; nor is a
    same-size rewrite within one timestamp tick of the previous write on a
    filesystem with a coarse clock (the snapshot re-hashes a file written
    within two seconds of it, which covers the usual case). A preserved time
    from before the call also reads as "before the call".
  - A change another process makes to a protected file while an `espalier`
    writer runs is recorded as the writer's.
  - The records under `.espalier-state/zone_writes/` are a toolbelt, not a
    lock: a shell call can write one that names its own change.
  - A commit made through git plumbing without touching the working tree,
    then checked out, reads as committed history.

**What Claude receives** (beside the tool result, as the `additionalContext`
of the ONE JSON object the hook prints at the end of its run -- every finding
of the run in one object, since two stdout JSON lines fail the whole parse;
each line also goes to stderr, which for a hook that exits 0 reaches only the
debug log, never Claude or your terminal):

```
[WARN] espalier: .claude/settings.json contains invalid JSON: ...
[WARN] espalier: tools/cc/hooks/my_hook.py has a Python syntax error: ...
[post_write_check] ESPALIER_MEMORY.md autoprune: 131 -> 119 lines (archived to docs/session-archive.md; requested 12 rows -- ...)
[WARN] espalier: protected files changed during this shell call, and nothing accounts for the change (...): changed tools/cc/hooks/write_guard.py. ... Stop and tell the operator what changed before going on (a subagent: put this in your final reply).
```

and, for a half-merged record file:

```
[post_write_check] ESPALIER_MEMORY.md: merge-conflict marker at line 3, 5, 7 (...). Resolve the hunk and write the file whole: ...
```

The autoprune line names the dates of the Session Log rows it archived; the
archive is gitignored, so this line is the only place they are named. The
action-justification nudge is the one finding that stays on stderr: it fires
on every unjustified mutation by design, and its audit record
(`action_justification_missing`) is its copy in the raw audit log; `/status --log`
does not count that type.

**Configuration:** None needed. Advisory only, low overhead.

---

### 7. `reflect_trigger.py` — Automatic quality reflection

**Event:** PostToolUse · **Can block:** No

Counts source-file writes during a session. Every 10th write, it runs
the reflect protocol — a structured scan for broken cross-references,
orphaned files, placeholder residue, and documentation gaps. Config file
changes (`pyproject.toml`, `package.json`, etc.) trigger an immediate
reflect regardless of count.

**What Claude receives** (beside the tool result, on a pass that found
drift -- the `additionalContext` of the hook's one JSON object):

```
Reflect pass flagged surface drift: 2 gaps, 0 orphans, 2 findings across 24 files. Review before continuing. First: [GAP] docs/CONVENTIONS.md references deleted file; [QUALITY_SIGNAL] 3 placeholder patterns in CLAUDE.md.
```

The same object names a reflect pipeline gone dark (`tools/cc/reflect_protocol.py`
or `tools/cc/cognitive_blueprint.py` missing), once a session. A clean pass
injects nothing.

**What the debug log gets** (stderr, which for a hook that exits 0 reaches
Claude Code's debug log only -- not Claude, not your terminal): the full
block, or `[reflect] clean -- 24 files, surface coherent` on a clean pass:

```
=== REFLECT TRIGGER (auto) ===
  Files analyzed:    24
  Cross-ref density: 1.3 refs/file
  Gaps:              2
  Orphans:           0
  [GAP] [medium] docs/CONVENTIONS.md references deleted file
  [QUALITY_SIGNAL] 3 placeholder patterns in CLAUDE.md
==============================
```

**Configuration:** None directly. The 10-write interval is hardcoded.
The reflect findings are informational — they surface drift, they don't
block work.

**The plan-mode bridge (INV-8).** The same `*` matcher makes this the hook
that sees an APPROVED `ExitPlanMode`: Claude Code fires PostToolUse for that
tool only once the user approves the plan (a rejection fails the tool and
reaches PostToolUseFailure, never this hook). On an approval the hook writes
`cc/execution_plan.json` from the approved plan's Markdown through
`execution_plan.build_plan` -- the shape `execution_plan.py create` writes --
so `plan_guard` allows the edits just approved without a manual
`/implement-task`. The task is the plan's title; the steps are its top-level
numbered items outside fenced code and outside a framing heading (Context,
Decisions, Risks...), else its `##`/`###` headings minus the framing ones,
else one step naming the title; `goal` names the plan file and `not_doing`
the first line under a Non-goals or Out of scope heading. An `in_progress`
plan is replaced and named as superseded, its file demoted to `cc/_cold/`
as `reset` does, so its passed steps and notes survive. A subagent's
approval (`isAgent`, which the object-shaped result carries) opens nothing
and says so; any payload that is not success-shaped -- `tool_response` an
object with the plan, or the approval text with the plan in `tool_input` --
opens nothing, says so, and is recorded once a session as
`posttooluse_failed_open_plan_bridge_shape` (counted by `/status --log`), so a
Claude Code whose stdin JSON moved stays visible past the one turn. Nothing
closes the window but the plan's own verbs (`mark`, `reset`), as for a
CLI-created plan.

**What Claude receives** on an approval (the `additionalContext` of the
hook's one JSON object):

```
[INFO] plan-mode bridge: cc/execution_plan.json opened from the approved plan -- 3 steps; source writes are allowed; python tools/cc/execution_plan.py status, and mark <i> passed as you go
```

---

### 8. `post_compact.py` — Post-compaction context recovery

**Event:** PostCompact · **Can block:** No

When Claude Code compacts the conversation (discarding older context to
free up the context window), this hook captures the verbatim compaction
summary to `cc/blueprints/compact_summaries/` and the live
`cc/_working_summary.md` (pull-only, via `/read-summary`), and arms the
`CP-COMPACT` checkpoint for the first mutating call after it (a Bash read
whose only redirects fold stderr in or send output to the null device is not
a mutating call and leaves the window for the first real write). It re-injects
nothing: PostCompact has no channel to Claude (no `additionalContext`,
`systemMessage` discarded), so its re-orientation block below is a debug
record. What re-orients the session is `session_start.py`, which Claude Code
re-fires with source `compact` after every compaction: its
POST-COMPACTION RE-ORIENT banner carries the live plan step, the recent
commits and the pointer to the summary. A fault in the capture is recorded
once a session (`postcompact_failed_open_*`), since stderr alone reaches
nobody.

**What the debug log gets** (stderr, which for a hook that exits 0 reaches
Claude Code's debug log only -- not Claude, not your terminal):

```
=== POST-COMPACTION CONTEXT ===
Repo:    my-project
Branch:  main
Surface: healthy
Blueprint: bp=abc123/d3

RESUME: you were mid-task -- run /status to re-orient, continue the active plan, finish via /handoff. (tools/cc/ is harness-managed; change them via /implement-task, not by hand.)
===============================
```

**Configuration:** None. Fires only after compaction events, which are
infrequent.

---

### 9. `stop_gate.py` — Session-end hygiene

**Event:** Stop · **Can block:** Yes

Runs a four-gate sequence when Claude tries to finish a turn. By default
only the lightweight hygiene gates run. The full pytest gate is opt-in.

| Gate | What it checks | Blocks? | Default |
|------|---------------|---------|---------|
| **1. Pytest** | Runs core test suite | Yes, on failure | **Off** (opt-in via env var) |
| **2. Docs refresh** | ≥10 writes and no `docs-maintainer` subagent run that changed docs (`.espalier-state/docs_refreshed`)? | Yes, the first Stop of each turn until one has | On |
| **3. Code review** | ≥10 writes and no `code-reviewer` subagent run (`.espalier-state/code_reviewed`)? | Yes, the first Stop of each turn until one has | On |
| **4. Blueprint finalize** | Auto-finalizes the active blueprint | Never blocks | On |

Gates 2 and 3 only fire on sessions with 10+ source writes. Short
sessions pass through all gates silently. Session-state coverage falls
back to `/handoff`, `git status`, and IDE gutters.

A source write is one whose extension is in
`tools/cc/hooks/_hook_utils.py::SOURCE_LANGUAGE_EXTENSIONS`, a projection of
the stack table `tools/cc/_stack_table.py` (every row's suffixes: the
ES-module, TypeScript-module and component formats `.mjs`, `.cjs`, `.mts`,
`.cts`, `.astro`, `.vue` and `.svelte` included; `.mdx` and `.css`
deliberately not), plus any `espalier.toml` adds under the flat top-level
`source_extensions` key. A stack is taught in the table, never in a hook.
When the deployed table cannot be read (absent, hand-patched into a
`SyntaxError`, or older than the hooks), the hook layer runs on
`_hook_utils`'s pinned copy of the table's projections and says so once a
session (`hook_layer_failed_open_stack_table`, below): gates running on the
copy see no stack the table gained after it. The docs evidence Gate 2 reads is the `.md` and `.mdx` files the run
changed. Your own agents relieve the two gates beside the shipped ones when
`espalier.toml` names them: `code_review_agents = ["astro-reviewer"]` for
Gate 3 and `docs_refresh_agents = [...]` for Gate 2, each the agent's
frontmatter name. Both deny messages name the declared agents, and say when
no body was found under `.claude/agents/` or `~/.claude/agents/`; a value
that is not a list of names is ignored with a `config_zone_ignored` record.

Every gate block also lands one record in the governance audit log, typed
per gate (`stop_blocked_pytest`, `stop_blocked_docs_refresh`,
`stop_blocked_code_review` — see that section below), so `/status --log`
can say why a session was returned; a crash of the hook itself re-blocks
fail-closed and lands `stop_blocked_internal_error` with the exception's
class. A block is once per turn, so the
reader counts them as pauses and shows them under `--all`. Under
`ESPALIER_MAINTENANCE_MODE=1` Gates 2 and 3 are skipped instead, and the first
Stop of the session lands one advisory record (`stop_bypassed_maintenance_mode`,
in neither tier), so the reader counts the bypass on its own line rather than
reading a bypassed day as a clean one; `write_guard` and `plan_guard` do the
same for the checks the flag switches off in them
(`pretooluse_bypassed_maintenance_mode`, `details.hook` naming which).

**What you see when blocked (example — gate 3):**

> Code review needed before Claude Code stops: this session made 10 or
> more source writes and no code review has run -- the review must be
> dispatched, not merely asked for. Dispatch the `code-reviewer`
> subagent (subagent_type='code-reviewer') on the session's diff, then
> retry the Stop event; the gate relieves when that subagent finishes,
> and `.espalier-state/code_reviewed` records which agent ran and what
> it concluded.
> Don't: write `.espalier-state/code_reviewed` by hand to skip the
>   review -- you lose the second pair of eyes the harness was holding
>   for.
> Do: dispatch the `code-reviewer` subagent (subagent_type='code-
>   reviewer') on this session's diff, address any BLOCK findings, then
>   Stop again; a reviewer of this repository's own relieves the gate too
>   once espalier.toml names it in `code_review_agents`. If the diff was
>   reviewed another way, record that
>   judgement instead -- write `.espalier-state/code_reviewed` as
>   {"agent": "operator", "note": "<a sentence saying how it was
>   reviewed>"}; that is a judgement you are recording, not a gate you are
>   skipping, and the gate notes it in the debug log when it honours one.

**Configuration:**

| Control | Effect |
|---------|--------|
| `ESPALIER_STOP_GATE=light` (default) | Skip gate 1 (pytest). Run hygiene gates 2-3 only. |
| `ESPALIER_STOP_GATE=full` | Run gate 1 (the test gate; the row below says what it runs) before hygiene gates. **Caution:** Stop fires on every turn, not just end-of-session. If set permanently, the test command runs on every turn. A pytest file list runs under the hook interpreter, so pytest must be installed for that form: on a Windows host wired to the launcher (`py -3`, a system Python) while your pytest lives in a virtualenv, the gate skips with a note (`stop_failed_open_pytest_missing`) until you install pytest for that interpreter or set `ESPALIER_STOP_GATE_TEST_CMD`. |
| `ESPALIER_STOP_GATE_TEST_CMD=<command>` | The command gate 1 runs as *your* suite, as an argv at the repository root without a shell (a non-zero exit, a timeout or a command that cannot start blocks the Stop; an entry carrying shell syntax -- `&&`, `||`, a pipe, `;`, a redirection, `$(` -- is refused before the spawn, once a session per command, with the shape named: one program per entry, each started at the root, so `test = ["npm run build", "npm test"]` where a shell line would chain them). It is the first of three sources: without it, under `full`, gate 1 runs the `test` entry under `[extra_actions]` in `espalier.toml` (read on every Stop; the hook interpreter needs Python 3.11+ or `tomli` to read it), else the test command detected from the repository's own files (`npm test`, `go test ./...`, `cargo test`, a bare `pytest -q`), and a pytest tree holding the harness default test files runs only those. `doctor` and the SessionStart banner say which one runs here (gate 1's own stderr line is a debug-log copy). A Gate 1 that skips -- nothing declared or detected and no default file here, no fingerprint test path exists, pytest timed out or could not run, the override splits to nothing, the fingerprint is unreadable, the mode is misspelt -- records `stop_failed_open_*` once a session, so `/status --log` counts it. |
| `ESPALIER_MAINTENANCE_MODE=1` | Skip gates 2 and 3 (hygiene friction). Gate 1 (pytest, if opted in) and gate 4 (blueprint finalize) still run. One advisory audit record per session says so (`stop_bypassed_maintenance_mode`; `/status --log` counts it). |

Set the stop gate mode for a single session:
```text
POSIX / Git Bash / WSL:  ESPALIER_STOP_GATE=full claude
PowerShell:              $env:ESPALIER_STOP_GATE="full"; claude
cmd.exe:                 set "ESPALIER_STOP_GATE=full" && claude
```

Do not `export ESPALIER_STOP_GATE=full` in your shell rc unless you
want pytest on every turn. The gotcha, inline rather than by reference: Stop
fires at the end of **every turn**, not once at end-of-session, and the hook
re-reads the variable each time — so an `export` in `.zshrc` or `.bashrc` puts
a full test run behind every ordinary edit, which reads as the harness being
slow rather than as a setting you chose. Prefer the inline prefix form above,
which scopes the variable to a single invocation, or put it under `env` in
`.claude/settings.json` so it reaches Claude Code and not every terminal.

---

### 10. `subagent_stop.py` — Subagent reasoning capture

**Event:** SubagentStop · **Can block:** No

When a spawned subagent finishes, this hook appends the head of the
subagent's final message to the active cognitive blueprint (the Gate 4
finalize path) as a `[subagent:<type>]` entry, with the agent's transcript
path as its evidence, so cross-context reasoning survives into the next
session rather than only in a tool-result stream the next compaction
discards. The entry keeps the opening of the message, cut on a word
boundary; the transcript holds the whole report. A subagent that ends
with no message records `[subagent:<type>] completed` with no evidence.
When the payload carries a message but names no transcript, the evidence
is the literal `SubagentStop.last_assistant_message`: it says where the
lead came from, and there is no file to open. It never blocks the
subagent — a SubagentStop block would deadlock the parent turn.

**What you see:** Nothing in normal operation. The blueprint chain under
`cc/blueprints/` gains one entry per subagent stop. The next session's
SessionStart banner carries the two most recent entries that hold a
report (pinned ones first) after the session's own patterns, under "What
the prior session wants you to know", and `cognitive_blueprint.py
show-recent` lists them mid-session. Entries with no report reach
neither. An agent's report is never offered as a `/reflect` memory
candidate: it is a claim for you to distil, not a note.

**Configuration:** None needed. Skipped under `ESPALIER_MAINTENANCE_MODE=1`.

---

### 11. `subagent_start.py` — Cold-subagent orientation

**Event:** SubagentStart · **Can block:** No

When a subagent starts cold (no inherited context), this hook injects a
small orientation payload — host facts plus a pointer to the fan-out
finding-schema — so the subagent does not re-derive the host
environment. It is a reporter: it only injects context, never blocks.

**What you see:** Nothing directly; the subagent begins with the
orientation context already in hand.

**Configuration:** None needed. Advisory only.

---

### 12. `context_reinject_failure.py` — Failed-edit re-derivation discipline

**Event:** PostToolUseFailure · **Can block:** No

When a `Write`/`Edit`/`NotebookEdit` fails, this hook injects the
untrusted-oracle re-derivation discipline (Rule A): re-read the live
bytes before retrying, rather than trusting a stale rendered frame of
the file. It is a reporter — it fires after the failed tool call and
never blocks.

**What you see:** A short advisory after a failed edit reminding you to
re-derive the target from the current file state.

**Configuration:** None needed. Advisory only.

---

## Configuration summary

Espalier-Harness has three levels of configuration, from surgical to nuclear:

### Per-hook controls

| Control | What it affects | How to set |
|---------|----------------|------------|
| `ESPALIER_STOP_GATE=light\|full` | Gate 1 (pytest) in stop_gate only | Env var before launch |
| `ESPALIER_STOP_GATE_TEST_CMD=<command>` | Gate 1's command (your suite) in stop_gate only | Env var before launch |
| `session_catch_up = true\|false` | session_start's catch-up of the checkout and its leftover worktrees (on by default only in the Espalier-Harness source repository) | Top-level key in `espalier.toml` |
| `ESPALIER_SESSION_CATCH_UP=0\|1` | The same catch-up, overriding the key for one session | Env var before launch |

### Friction bypass

| Control | What it affects | How to set |
|---------|----------------|------------|
| `ESPALIER_MAINTENANCE_MODE=1` | write_guard (protected-zone check) but not its speed-bump checkpoints, plan_guard (plan requirement), stop_gate (gates 2/3), subagent_stop (blueprint append) | Env var before launch |

What maintenance mode does NOT bypass:
- write_guard's kill-switch gate and dangerous-command blocking
- write_guard's speed-bump checkpoints (`CP-*`), which dispatch before the maintenance gate is read
- config_guard (settings safety)
- post_write_check (advisory — already non-blocking)
- reflect_trigger (advisory — detecting drift during maintenance is a feature)
- CI (`ci_guard.py` — outside the agent's reach)

Every bypass logs `[hook_name] MAINTENANCE_MODE — action` to stderr. A hook
that exits 0 has its stderr routed to Claude Code's debug log and never the
transcript, so that line is readable only with debug logging on; what a later
session reads back is the once-per-session audit row
(`pretooluse_bypassed_maintenance_mode`, `stop_bypassed_maintenance_mode`),
counted by `/status --log`. `subagent_stop`'s bypass writes no row — its
whole effect is to skip the blueprint append.

### Nuclear option

| Control | What it affects | How to set |
|---------|----------------|------------|
| `disableAllHooks: true` in `.claude/settings.json` | Everything — no hook code runs at all | Edit settings before launch |

If you set this while hooks are still active, write_guard and
config_guard will immediately block all subsequent tool calls and
settings changes until you remove the flag. If you set it before
launching Claude Code, no hook runs — nothing in this project can
intervene. CI is the only remaining enforcement.

**There is no per-hook on/off toggle.** The hooks are wired as a
coordinated system — write_guard and plan_guard share the PreToolUse
event, reflect_trigger and post_write_check share PostToolUse. Disabling
one without disabling the other requires editing `.claude/settings.json`
to remove the specific hook entry from the `hooks` array. This is
supported by Claude Code but not exposed as an Espalier-Harness feature
because the hooks are designed to work together. If you find yourself
wanting to disable a specific hook permanently, open an issue — that's
signal about what the defaults should be.

---

## Hook command resolution and matcher rules

Espalier-Harness generates hook entries in **exec form** with narrow
**matchers** on tool-firing events. Both decisions improve portability
and avoid wasted process spawns.

### Exec form

Each hook entry has this shape:

```json
{
  "type": "command",
  "command": "python",
  "args": ["${CLAUDE_PROJECT_DIR}/tools/cc/hooks/write_guard.py"],
  "timeout": 5
}
```

Claude Code resolves `python` on the user's PATH and spawns it directly
with each `args` entry passed verbatim. No shell, no tokenization, no
platform-specific variable syntax.

**Resolver requirement.** A Python 3.10+ interpreter must answer to
`python` or `python3` on PATH, or to the Windows launcher as `py -3`.
`espalier.cli._detect_python_command` probes them in that order at init
time (the launcher only when neither name answers 3.10+) and writes the
first that answers into the generated `.claude/settings.json`; the
launcher is written as `command: py` with `-3` leading the `args`. No
operator setup is required on the typical distributions:

- **Windows** — the python.org full installer does NOT add
  `python.exe` to PATH by default (its `PrependPath` option defaults to
  0 and the "Add python.exe to PATH" box is unticked; see
  <https://docs.python.org/3/using/windows.html>), and Windows can carry
  `python`/`python3` App Execution Aliases that resolve but only print a
  Store prompt. The installer does install the `py` launcher by default,
  so on such a host init detects and wires `py -3`. With the box ticked,
  or through the newer Python install manager (which provides `python`
  and `py`), init detects `python`.
- **Linux** — most distributions ship `python` as a Python 3 symlink;
  some only `python3`. Init picks whichever is on PATH.
- **macOS** — system / Homebrew Python is `python3`. Init picks
  `python3`; no manual symlink needed. Note the STOCK `/usr/bin/python3` is
  3.9, below the 3.10 floor: init wires it (so the guards keep working) and
  warns that blueprints, Gate 4 and subagent capture will not run until you
  install a newer Python and re-run `espalier init . --rewire-interpreter`.

If none of `python`, `python3` or `py -3` answers, init still writes
`python` and warns. What you then see, on every hook fire, is Claude
Code's own notice — `SessionStart hook error` (or whichever event fired)
followed by `Executable not found in $PATH: "python"` (driven on Claude
Code 2.1.263) — and the session carries on with every guard failing
open. The same notice appears whenever the wired name stops resolving
later: an uninstalled interpreter, a `settings.json` copied from another
machine. The statusline reads
`espalier: statusline did not run -- see docs/TROUBLESHOOTING.md` on the
same condition instead of going blank — on installs `init` rendered
from this version on; an older `settings.json` keeps its statusline and
still goes blank, one wired by `merge-settings` or `--wire-hooks` before
the merge learned to add the key has no statusline at all, and
`espalier doctor .` says so in both cases (`merge-settings` adds
espalier's `statusLine` when the key is absent and never touches one of
yours). On macOS and Linux
the shell prints that line through a `||` clause in the statusline
command. On Windows neither shell can carry the clause (Windows
PowerShell 5.1 cannot parse `||`, and Git Bash rewrites a `cmd /c`
switch into a drive path), so `init` wires the statusline through a
deployed batch shim, `tools/cc/statusline.cmd`, which runs the script
with the wired interpreter and prints the same line when that
interpreter is gone.

Install a Python 3.10+ (or put it on PATH), then run
`espalier doctor .` — it names the wired interpreter and the exact
command — and `espalier init . --rewire-interpreter`, which swaps the
interpreter at every hook entry and the statusline, writing a backup
first. Plain `espalier init .` will not repair it: an existing
`settings.json` is never overwritten, so it renders `settings.json.new`
beside the broken file when the fresh render differs.

A manual symlink (`sudo ln -s "$(which python3)"
/usr/local/bin/python`) still works as an alternative — it gives every
tool on the machine a `python` name — but it is not required.
Run `espalier doctor .` to verify the resolver picks the right name.

### Why not absolute paths

Shell form with the host's absolute Python path
(`/usr/bin/python3 "$CLAUDE_PROJECT_DIR/tools/cc/hooks/X.py"`) works on
the host that ran `espalier init` but breaks on every other machine.
Exec form with a relative `python` makes the same generated file
portable to any host with a Python 3 on PATH.

### Matcher precision

`PreToolUse` uses `matcher: "*"` so Agent (Task on older Claude Code) /
TodoWrite / SlashCommand / BashOutput dispatches reach `write_guard`'s
kill-switch and protected-zone gates. A matcher narrowed to mutation
tool names would let the kill-switch miss a subagent dispatch, because
Claude Code filters the hook out before spawning the subprocess.

`PostToolUse` keeps the narrow matcher for `post_write_check`:

```
*                                                (PreToolUse)
Write|Edit|NotebookEdit|Bash|PowerShell|mcp__.*  (PostToolUse: post_write_check)
*                                                (PostToolUse: reflect_trigger)
```

The PreToolUse widening trades a small per-tool-call spawn cost for
the security guarantee that the kill-switch fires on every tool
dispatch. The two hooks short-circuit the read-only path differently
(do not flatten them into one shape): `plan_guard.py` returns 0
immediately for a non-mutation tool — it runs no kill-switch scan.
`write_guard.py` runs the always-on kill-switch scan on every dispatch
FIRST (that every-dispatch firing IS the guarantee), then returns 0
for tools not in `MUTATION_TOOLS` and not an MCP write. The behavior is the
contract; line numbers drift with surface edits, so none are pinned here.

Matcher strings are sourced from `espalier.harness_config.CANONICAL_HOOK_WIRING`
(engine-internal — it lives in the installed package, not in your tree).
`tests/test_hook_matcher_precision.py::ALLOWED_STAR_HOOKS` (Espalier source repo)
enumerates the hooks legitimately on `"*"`.

### Events that do not support a matcher

Per the Claude Code hooks reference (verified against the live docs on
2026-05-13), these events do **not** accept a `matcher` field — adding
one is silently ignored:

- `UserPromptSubmit`
- `Stop`
- `PostToolBatch`
- `TeammateIdle`
- `TaskCreated`
- `TaskCompleted`
- `CwdChanged`

Espalier omits `matcher` on entries for these events.

Other Espalier-wired events (`SessionStart`, `ConfigChange`,
`PostCompact`) do support a matcher per the docs, but Espalier does
not currently use one — those hooks govern at the event level, not at
a per-tool granularity.

### What stays the same

- The hook scripts themselves (`tools/cc/hooks/*.py`) are unchanged.
- Hook timeouts, the hook order within an event entry, and the
  semantic contract (exit-code conventions, channel-XOR rules, etc.)
  are unchanged.

---

## What hooks are NOT

The design goal is to make **following the workflow the path of least
resistance**. The local layer works as advisory → friction →
protected-zone:

- **Advisory** — project context and instructions injected so the right
  next step is the obvious one.
- **Friction (hooks)** — catches slips on the first attempt and reminds
  with *more than* advisory text.
- **Protected-zone block** — the floor: mutations of harness files (a write, a delete, a move) are denied
  so the hooks can't be trivially turned off mid-session, keeping the
  default "follow the workflow," not "disable the safety and go."

Two more layers sit behind the local one: **visibility** (the audit log
records what slipped past friction) and the **guarantee** — CI + branch
protection, the only layer that truly blocks, at merge time and outside
the agent's reach.

This defends against **slips and self-disable**, not a motivated attacker
— a self-user won't attack their own work.

> **Disclaimer (not the thesis).** Hooks are not a sandbox. An agent with
> arbitrary subprocess access and unlimited retries can work around any
> local hook. If you need enforcement that cannot be circumvented by local
> processes, you need containerization or Claude Code's managed
> `policy_settings` — both outside this project's scope.

The full list of documented bypass classes and why they exist is in the Espalier
source repo's own `docs/SHARP_EDGES.md` (not deployed by `init` — read it there if
you have the harness cloned).

## Governance audit log

Every enforcement *block* the hooks make — a PreToolUse or ConfigChange
refusal (`write_guard`, `plan_guard`, `config_guard`) and a Stop-gate block
(`stop_gate`) — is appended to a machine-local, append-only log — one JSON
line per event, serialized under a file lock.

```
~/.espalier/audit/<repo>-<YYYYMMDD>.log
```

Override the directory with `ESPALIER_AUDIT_DIR`; logs older than 30 days are
pruned automatically. The log is a **visibility layer, not a security
boundary** — a write failure is swallowed so it can never make a hook raise,
and nothing downstream depends on it. The **denial** records below carry
`details` that are metadata-only — the tool/channel, the repo-relative path,
and the matched rule, never file contents. (The same log also holds advisory
records the hooks write, e.g. `action_justification_missing`, whose `details`
include a truncated command string, and the maintenance-bypass records --
`pretooluse_bypassed_maintenance_mode` from `write_guard` and `plan_guard`,
`stop_bypassed_maintenance_mode` from `stop_gate` -- one per hook per session
when the flag switches a check off; `/status --log` filters those out of the
tail and shows the refusal tier of the table below by default, counting the
bypasses on their own line, per hook. The fail-open family -- `<hook>_failed_open_<what>`,
written once a session by `say_once` when a check fails open, a reporter hook
crashes, or a reporter's finding has no other channel (PostCompact, Stop,
SubagentStop, ConfigChange) -- is counted on a line of its own too: a hook
that exits 0 has its stderr routed to the debug log, so for those the record
is the voice.)

The records come in two tiers. A **refusal** is a call that did not run. A
**pause** is once-then-continue: a speed-bump fire lets the re-issued command
proceed, and a Stop-gate block is let through by the protocol's loop signal on
the next Stop — so on a busy day their records can outnumber the rare refusal
inside a window of twenty.

| `event_type` | Tier | Emitted when |
|---|---|---|
| `pretooluse_blocked_protected_zone` | refusal | a write to a protected harness zone is denied (Write/Edit, Bash, PowerShell, or MCP) |
| `pretooluse_blocked_dangerous_command` | refusal | a dangerous Bash/PowerShell pattern (`rm -rf /`, fork bomb, …) is denied |
| `pretooluse_blocked_no_active_plan` | refusal | `plan_guard` denies a source write with no active execution plan |
| `pretooluse_blocked_kill_switch` | refusal | a tool call is denied because a kill-switch is set |
| `pretooluse_blocked_secret_path` | refusal | a read of a secret-bearing path (a dotenv file, a `secrets/` directory, a credentials file) is denied — for Read/Edit/Grep, and for a Bash or PowerShell command that would print it |
| `pretooluse_blocked_internal_error` | refusal | `write_guard` or `plan_guard` crashed and denied the call fail-closed; `details.hook` names which, `details.error` the exception's class (never its message); one record per denied call while the hook stays wedged, so the tail fills with them and the by-type line above it is where every other type's count survives |
| `pretooluse_blocked_time_budget` | refusal | `write_guard`'s judgment was still running when its time budget ran out, and the call was denied rather than let through when Claude Code's timeout cancelled the hook; `details.tool` names the tool, `details.budget_s` the budget and `details.chars` the command's length, never its text |
| `configchange_blocked_kill_switch` | refusal | a settings change that would arm a kill-switch is denied |
| `configchange_blocked_unwired` | refusal | a project settings change that would unwire a governance gate the session runs is denied; `details.findings` names the gates |
| `configchange_blocked_internal_error` | refusal | `config_guard` crashed and blocked the settings change fail-closed; `details.hook`, `details.error` as above |
| `pretooluse_blocked_speed_bump` | pause | a speed-bump checkpoint fires once on a before-effect command (`git clean -f`, a force-push, a gate-weakening edit, a fetch piped straight into an interpreter on either shell); `details.checkpoint` names the checkpoint, and the re-issued command proceeds |
| `stop_blocked_pytest` | pause | Gate 1 blocked the Stop: the core test run, or the command Gate 1 runs as your suite (`ESPALIER_STOP_GATE_TEST_CMD`, the declared `[extra_actions] test`, or the detected command; `details.source` names which of the three: `env`, `espalier.toml`, `fingerprint`), failed, timed out or could not be started; `details.rule` names the case, `details.returncode` the exit code, and `details.error` the exception's class when the command never started |
| `stop_blocked_docs_refresh` | pause | Gate 2 blocked the Stop: ten or more source writes and no docs refresh recorded (or a relief record that is not one); `details.rule` names the case, `details.write_count` the count |
| `stop_blocked_code_review` | pause | Gate 3 blocked the Stop: ten or more source writes and no code review has run (or a relief record that is not one); `details.rule`, `details.write_count` as above |
| `post_shell_zone_change` | report | after a Bash or PowerShell call, protected files changed that nothing accounts for (`post_write_check`, "The protected files after a shell call"); `details` names them by kind (`changed`, `added`, `removed`, twenty each at most) with their `count`, the same kinds suffixed `_between_calls` for what landed before the call began, and the `tool` |
| `hook_layer_failed_open_stack_table` | fail-open | the hook layer could not read `tools/cc/_stack_table.py` (absent, a `SyntaxError`, or older than the hooks) and every gate runs on `_hook_utils`'s pinned copy of its projections; written once a session where a root is known, by the two source gates at their root and by the reporters' `repo_name`, with the fault in `details` |
| `stop_blocked_internal_error` | pause | the Stop hook crashed and re-blocked the Stop fail-closed (the loop signal lets the continuation's Stop through; a persistent crash re-blocks on the first Stop of every later turn until its cause is fixed); `details.rule` is the internal-error reason's name, `details.error` the exception's class |

Watch it live (all records), or read the current repo's tail:

```bash
tail -f ~/.espalier/audit/*.log                    # all records, live
python tools/cc/session_resume.py --log            # last 20 refusals, this repo, today
python tools/cc/session_resume.py --log 50         # last 50 refusals
python tools/cc/session_resume.py --log 50 --all   # last 50 blocks, pauses included
python tools/cc/session_resume.py --log <repo>     # another checkout's tail
```

The tail is scoped to the checkout it is asked about: the file is keyed by the
repo's basename, so two checkouts named alike share one, and the reader keeps
only the records whose `repo_path` is that root. A per-type count for the whole
day prints above the tail, and the day's pauses are counted on a line of their
own, so a window of 20 cannot silently hide what it left out — a busy day of
speed-bump fires or Stop-gate blocks does not bury a protected-zone denial
without a trace, and `--all` widens the tail to the pauses when you want them.

## See also

- `docs/HOOK_ASSUMPTIONS.md` — the five
  Claude-Code-protocol assumptions Espalier's hook enforcement rests on,
  each with an honest **Backed by:** line distinguishing assumptions
  pinned by tests from those that are convention-only.
- [`external/cc-hook-protocol.md`](external/cc-hook-protocol.md) — the
  pinned external truth for hook semantics that drives both this doc and
  `HOOK_ASSUMPTIONS.md`.
