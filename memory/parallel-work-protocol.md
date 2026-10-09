# Parallel work protocol

**Status:** active — the sole home of root `CLAUDE.md` Core Rule 15; adopted
2026-10-09 on the operator's decisions, built by `TP-479` (the anti-clobber
system's second generation).

**Linked from:** root `CLAUDE.md` Core Rule 15 and Rule 10;
`task-packs/TP-479-parallel-work-without-clobbering.md`. Kin:
[[one-writer-per-shared-state]] (Core Rule 14: isolation inside one tool's
run; this note is the same rule between seats), `TP-467` (sessions in one
tree), [[fix-the-class-not-the-instance]].

## The rule

Parallel work is safe by construction, not by negotiation. Each seat works the
jobs the dispatcher assigns it. Shared records never store what two lanes would
both recompute. Ids come from the seat's own block. State is read live, never
remembered. A red `main` is reverted before anything lands on it.

## Terms

- **Seat.** One Claude Code session in its own checkout or worktree, with its
  own name: `git config espalier.machine`, set per worktree with `--worktree`
  (`docs/SHARP_EDGES.md`, "The worktrees of one clone share its machine name").
  Two seats on one box are two seats. Two sessions in one checkout are one seat
  and must not happen; the SessionStart `Sessions:` line reports it.
- **Job.** A pack, a wave of a pack, or a ledger class: the unit the dispatcher
  assigns. Never a path. Measured 2026-10-09 over the 93 pull requests merged
  since 10-02: of the 65 that touched code, 47 crossed two or more areas of a
  three-way path split, and 49 to 50 crossed top-level directories. Work here is
  feature-shaped: a hook, its engine twin, a script and a command body move
  together.
- **Dispatcher.** The seat the operator names, recorded as `dispatcher` in
  `espalier.toml` (a team setting, so tracked; `air` since 2026-10-09). Only
  its `assign` messages count (`python tools/cc/mail.py assignments`).

## What a worker seat does

1. **Work the jobs assigned to you**, and keep two or three queued, so the
   dispatcher's absence does not stall you. For a new job or a decision that
   crosses jobs, send the dispatcher one request. Never negotiate with another
   worker seat.
2. **Claim the files a lane edits** on the mail channel, as before. Assignments
   are for jobs; claims are for files.
3. **Read live state in the same turn before you state it**: which pull request
   is open, merging, blocked or red. The banner, the mail, a handoff note and
   your own context are snapshots, and with three seats pushing they go stale
   within the hour (2026-10-09: this session's banner named a pull request as
   blocked that merged before the first reply was written). Read the board:
   `/inbox board`, or `python tools/cc/board.py`.
4. **One open pull request per seat.** A second lane waits until the first
   merges: fewer open pull requests, fewer pairs to conflict.
5. **Ids: the blocks start when the tool mints them.** The operator approved
   one block per seat (below), and `TP-479` Wave B makes `ledger_row.py file`
   mint from it. Until then, keep filing from the shared range as before and
   put the id on your claim (`--id`), which the ledger verbs read before they
   write. Do not hand-pick from a block early: the habit everywhere else is
   "highest id plus one", so the first hand-picked block id would put the next
   seat's max+1 inside your block (the Wave A review, 2026-10-09). Wave B moves
   this table into the one tracked file the minting code reads.

   | Kind | win | win-2 | air | A seat with no name |
   |---|---|---|---|---|
   | `DEF` | 2000–2999 | 3000–3999 | 4000–4999 | 1199–1999 |
   | `INV` | 100–199 | 200–299 | 300–399 | 32–99 |
   | `TP` | 500–599 | 600–699 | 700–799 | 479–499 |

   A new seat gets the next free block from the dispatcher.
6. **Change a record's format by expand, then contract.** Readers learn the new
   form while still reading the old; then writers switch; then the old form
   goes. Never a flag day while other lanes are open. win-2's derived-totals
   change (`TP-478` 2-B) is the model: every parser reads both forms, and the
   next verb heals an old file.
7. **A red `main` is reverted first and diagnosed second.** The post-merge
   proof (`.github/workflows/post-merge.yml`) runs after merges, and the ship
   preflight and the board name a red one. A newer push cancels an older run,
   so one red run can carry every merge since the last green one: the board
   prints the revert only when exactly one pull request merged in between, and
   otherwise names the suspects to read. The seat whose merge turned it red
   opens the revert pull request. If that seat is not running, whoever sees the
   red first claims a `revert/<sha>` lane and does it. The dispatcher is the
   backstop. Nothing lands on a red `main`: disarm the auto-merge the board
   lists (`gh pr merge --disable-auto <n>`).
   - **Re-landing reverted work.** After a revert, a fix pushed from the old
     branch re-merges only its new commits, and the reverted change stays
     out of `main` without anyone seeing it go. Re-land on a fresh branch from
     `main`: `git revert <the revert's sha>`, then the fix on top.

## What the dispatcher does, and does not

| Does | Does not |
|---|---|
| Turns the operator's priorities into assignments (`mail.py send --type assign --seat <seat> ...`): which seat works which job | Set the priorities: the operator does |
| Sequences jobs that would collide: two jobs on one hot file, a record-format change while lanes are open | Gate changes: seats ship their own lanes |
| Answers worker requests at its next prompt (the operator prompts "dispatch", or a `/loop` does) | Review all code, or act as the merge queue |
| Backs up a red `main` that nobody else has reverted | Hold knowledge only in its own context: what it decides is written where every seat can read it |
| Carries a lighter lane of its own | Run the heaviest lanes, which compete with dispatching |

A Claude session acts only when prompted. The design tolerates a dispatcher
that is away: a seat with a queue does not need it in real time.

**How assignments behave** (`tools/cc/mail.py`):
- Only the dispatcher may send an `assign`. The send refuses any other seat,
  a setting it cannot use, and a linked worktree whose name it inherited from
  its clone (that worktree would assign as the seat owning the name).
- A job is its lane, classes and ids together, and the latest assign of a job
  wins. To split one pack's waves across seats, name each wave by its lane
  alone: a pack id on two wave assigns makes each seat's plan warn about the
  other.
- A job closes when the assigner or the assigned seat releases it, by the
  assign's id or by its lane. The ship driver's lane release closes a job
  assigned by that lane, so a finished job stops warning.
- An unusable `dispatcher` setting (not a machine name, under a table, an
  unreadable file) counts no assign at all. It fails closed, and the board
  says why.

## The layers underneath (`TP-479`)

| Layer | What clobbers | Mechanism |
|---|---|---|
| L1 | Two lanes rewrite one record (stored totals, appended rows) | Totals derived on read; records as per-change files behind one loader |
| L2 | One id minted twice | Per-seat id blocks, minted by the tool |
| L3 | Two pull requests green alone, red together | PR CI tests the merge with `main` at push; jobs assigned apart; one open pull request per seat; a stale-base check before merge; the post-merge proof; revert first |
| L4 | Two seats working one job, or negotiating | Jobs assigned by the dispatcher |
| L5 | Seats believing different things | One live board; read before you state |
| L6 | Two sessions in one checkout | One seat per worktree; names given by code (`TP-467` wave B) |
| L7 | A written rule that disagrees with the live setting | Process facts printed live by the banner; docs point at it |
| L8 | A record-format change stops every open lane | Expand, then contract |

## What it cost to learn (measured 2026-10-09)

- 20 of the last 30 merged pull requests needed a catch-up merge of `main`, at
  1.73 test runs per pull request (`scripts/merge_cost_census.py --prs 30
  catch-ups`). Replayed as GitHub merges them, 24 of 30 catch-ups conflicted,
  and most conflict blocks were stored totals, not rows (`TP-478` Task 0).
- `DEF-1197` was minted on two machines: the ids lived only in open pull
  requests, which no claim showed.
- Mail between seats rose from 9 messages on 10-08 to 30 on 10-09, the first
  full day with a third seat; 24 of those 30 were claims or releases.
- Root `CLAUDE.md` Rule 10 still said the up-to-date rule was on after it had
  been turned off that morning, and the first post-merge proof run went red
  with no seat owning it.
- Three seats each believed a different branch was merging.

## Prior art (cited from memory, not re-checked)

Trunk-based development and merge queues (bors's "not rocket science rule");
changelog fragments (towncrier, CPython's `Misc/NEWS.d`); hi/lo id allocation;
Conway's law and feature teams over component teams (Larman and Vodde); the
build sheriff and revert-first (Chromium, Mozilla); Brooks's law; the theory of
constraints (adding workers in front of a bottleneck lengthens the queue).
