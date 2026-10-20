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
- **A worktree seat's interpreter.** A linked worktree checks out the source,
  not an interpreter: an editable install of `espalier` names one checkout, so
  in every other seat a tier's child processes import that checkout's engine
  (measured 2026-10-12: a worktree seat's full tier ran the main checkout's
  engine in every CLI test). Give each seat its own, in the checkout itself:
  `uv venv .venv`, then `uv pip install --python .venv/bin/python -e '.[dev]'`
  (`.venv\Scripts\python.exe` on Windows), and run every tier with `.venv/bin`
  (`.venv\Scripts`) first on PATH, launching Claude Code that way too so the
  banner agrees (`scripts/proof_tier.py` launches pytest, ruff and mypy by
  name). `.venv` is gitignored, reaped as disposable, and `uv run`'s default.
  Never a global `PYTHONPATH`: the wheel and fresh-clone tests build venvs of
  their own and would inherit it. A test session on the wrong engine stops
  before any test runs (`tests/_engine_check.py`); the SessionStart `Engine:`
  line names the mismatch earlier, from the launch PATH.
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

**Start a seat with one command, from a terminal of the operator's own**
(never from inside a session): `python tools/cc/seat.py launch <seat>`. It
resolves the seat's checkout (creating a worktree seat from `origin` when it is
absent), refuses one a live session is in, and starts `claude` there with the
seat's first message as its prompt, so nothing is pasted. `seat.py brief
<seat>` prints that message: the worker form names the dispatcher, the two
reads to start with and the jobs, and ends with the worker loop (`/loop 10m`,
the tick this repository's workers have run since 2026-10-15); the dispatcher
form names its duties and ends with `/loop 15m /inbox board`. `espalier.toml`'s
`dispatcher` line picks the form, and `--no-brief` launches without one. The
banner check: a worker seat holding live assigns opens on an `Orders:` line
with its jobs and the same short form, which a session started by hand reads
there. Driven on Claude Code 2.1.301 (2026-10-15, win-2, a scratch worktree):
a first message whose last line is a `/loop` line starts that loop with no
second message, whether the session was launched with the checkout as its cwd
or with `claude --worktree`, and the loop survives `/clear` (the same
process); a relaunch is a new process and gets its loop from the brief, so
it needs no second paste either. `claude --worktree` locks the worktree, in an
interactive session as under `-p`; a killed session leaves the lock behind.

1. **Work the jobs assigned to you**, in order, and keep two queued (the
   dispatcher's duty to keep them there, the table below), so the
   dispatcher's absence does not stall you. For a new job or a decision that
   crosses jobs, send the dispatcher one request. Never negotiate with another
   worker seat.
2. **Claim the files a lane edits** on the mail channel, as before. Assignments
   are for jobs; claims are for files. A claim can name the functions too:
   `send --type claim --symbols-from` derives them from the lane's diff, and
   `mail.py refresh` re-claims what the diff has added since. The lane is the
   branch: create it before the first claim and claim under its exact name,
   since `refresh` and the ship driver's release read only the branch.

   A claimed file is not always a blocked lane: when the claimed site already
   calls an unclaimed shared helper, the fix can go in the helper and reach
   the site with no edit there. Read the claimed site's call graph before
   calling the lane blocked. On 2026-10-07 the `DEF-935` fold went inside
   `_hook_utils._msys_drive_to_windows`, which `_bash_patterns._posix` in
   Windows's claimed file calls, so the delete tier read the drive form
   untouched, and a test pinned it.
3. **Read live state in the same turn before you state it**: which pull request
   is open, merging, blocked or red. The banner, the mail, a handoff note and
   your own context are snapshots, and with three seats pushing they go stale
   within the hour (2026-10-09: this session's banner named a pull request as
   blocked that merged before the first reply was written). Read the board:
   `/inbox board`, or `python tools/cc/board.py`.
4. **One open pull request per seat. It caps pull requests, not work.** When
   a lane ships, start the seat's next job at once on a new branch from
   `origin/main`, and open its pull request when the first merges (`ship.py
   open` notes a second open one; it does not refuse). Fewer open pull
   requests, fewer pairs to conflict, and the seat never idles on its own CI.
   A job waits only on a named file overlap with another seat's open lane.
   Measured 2026-10-11 over the 40 merges #144 to #184 (76 hours): open to
   merge took a median of 36 minutes, and two or more pull requests were open
   only 32% of the time, so the seats were not queued behind each other; each
   idled on its own pull request because this item read as "do not start".
   Building on your own open lane's head when the next job shares its files
   (a stacked lane: merge `origin/main` in after the first merges, then open)
   is untested here, and enters this item only after one lane proves it.

   Whether two lanes that share a file overlap is read, never certified by
   hand. The board's `overlaps:` line names what both lanes change, and only
   one of its readings is a certificate:
   - `meet at` is an overlap;
   - `different functions` is the certificate, and both lanes go on;
   - `unplaced lines`, `no symbols` and `symbols not read` are a path hit,
     not a certificate, so the job waits as it would on any shared file.

   `overlaps: unread` and `none among what was read` certify nothing: what
   was not read is read by path, as before. The plan's claim warning has
   words of its own, and neither is a certificate: `symbol <name>` is an
   overlap, and `path <P> (their <Q>)` is a path hit, `no symbol in common`
   included (an import or a moved line is not a symbol).

   The dispatcher no longer reads two lanes' hunks to certify them
   (TP-702 Wave 3, 2026-10-17).
5. **Ids are minted, never hand-picked.** Each seat owns one block per kind
   (`DEF`, `INV`, `TP`), and the table lives in the tracked `espalier.toml`
   under `[id_blocks]`. Read the blocks there; this note does not copy them.
   - **To file a row, leave the id out.** `ledger_row.py file` with no id takes
     the lowest free number of your block. The number is reserved before the
     row is written, and given back if the filing refuses.
   - **To reserve an id or pack number first** (to put it on a claim, or to
     name a pack), run `ledger_row.py mint --kind DEF|INV|TP`. It prints the
     number and reserves it.
   - **Reservations are per clone.** They live in the clone's git directory
     (`.git/espalier/minted_ids.json`), shared by every worktree of the clone
     under one lock, with the seat that took each number.
   - **A worktree seat** (SessionStart names it `<clone>-<directory>`) mints
     from its clone's block until the table gives it a line of its own. Two
     worktrees of one clone cannot collide, because they share the record.
   - **Taken means:** in the ledger or the probe file, on any live claim, in
     the clone's reservations, or (for `TP`) a pack file.
   - **Refusals:**
     - A linked worktree still answering its clone's name is refused, for a
       mint and for an explicit id. SessionStart names Claude Code's
       worktrees. On a bare clone, or one whose shared config sets
       `core.worktree`, the one change is `core.bare` (or `core.worktree`)
       moved into the main worktree's `config.worktree` (the refusal prints
       its path), after which a fresh session names the worktree. Elsewhere,
       name one by
       hand with `git config extensions.worktreeConfig true`, then
       `git config --worktree espalier.machine <name>`, run in it. The
       refusals print `mail.naming_steps`, the one owner of these steps.
     - A seat whose machine name git could not read is refused a mint and an
       explicit id alike; `--override` files the explicit id anyway.
     - An explicit new id outside the block you mint from is refused, and
       `--override` files it anyway. That covers an id in another seat's
       block, and a hand-picked "safe" number outside every block.
     - A clone with no name mints from `_unnamed` and says so. It is refused
       once the mail refs show another machine on the repository, because
       each clone keeps its own record.
   - **Why "highest id plus one" is gone:** read on two branches, it gives one
     answer, which is how `DEF-1197` was minted twice.
   - **A new long-lived seat** gets the next free block from the dispatcher,
     as one line in `espalier.toml`.
   - **Closed by `seat.py retire <seat>`** (`TP-701` B-2, 2026-10-15): a
     worktree's seat name outlives the worktree, its unreleased claims stay
     live, and only that name can release them. `retire` sends the releases
     from inside the worktree under its own name before it removes the
     worktree, and refuses to remove one whose claims it cannot release
     (printing the by-hand release for a worktree already gone). The
     SessionStart clean-up releases nothing: it keeps a worktree whose seat
     still holds a live claim.
6. **Change a record's format by expand, then contract.** Readers learn the new
   form while still reading the old; then writers switch; then the old form
   goes. Never a flag day while other lanes are open. win-2's derived-totals
   change (`TP-478` 2-B) is the model: every parser reads both forms, and the
   next verb heals an old file. The ledger's rows and probes as one file each
   (`TP-479a` Wave B) followed it: the loader's view and every reader took both
   forms (a census test holds each reader to the view), and only then did the
   writers switch, on a repository that sets `ledger_fragments = true`; the
   legacy rows stay in the file until the fold.
   - **The Session Log's transport (2026-10-16, `DEF-5007`).** A count is a
     record too: every lane held the Session Log's cap in its own tree, so two
     lanes each at 30 merged to 31 on `main`, and a handoff whose lane had
     already merged opened a pull request for its row alone (seven in two
     days). The Session Log is now pruned in one place: the fold a lane's push
     runs (`tools/cc/ship.py`, and its `fold` verb before a direct push)
     brings in every row the seats parked on their records refs
     (`refs/heads/records/<seat>`, each written by its seat alone) and, once
     the files run past 35, prunes back to 30, in commits carrying
     `Espalier-Fold: session-log`. The slack is what ends the prune commit
     per lane; an exact cap kept one on every lane carrying a row, and two
     lanes off one base can still land a row past the slack, which the next
     fold prunes (a count two lanes recompute, bounded rather than removed).
     A handoff with no open pull request and only rows it added parks them
     and moves its branch back to the base, so its checkout catches up.
     Readers learned the pending rows (the landing check) before the writers
     moved, and the hook and the handoff stopped pruning in the same lane.
     **Another seat sees a parked row only after the next fold:** the
     banner's recent rows read the tree, so until some lane's push lands the
     row reaches no banner, the parking seat's next session included.
7. **A red `main` is reverted first and diagnosed second.** The post-merge
   proof (`.github/workflows/post-merge.yml`) runs after merges, and the ship
   preflight and the board name a red one. Each push's run goes to the end,
   beside the next one, so a red run's suspects are the merges since the last
   green run before it, more than one when a run between them is red or still
   going: the board prints the revert only when exactly one pull request merged
   in between, and otherwise names the suspects to read. The seat whose merge turned it red
   opens the revert pull request. If that seat is not running, whoever sees the
   red first claims a `revert/<sha>` lane and does it. The dispatcher is the
   backstop. Nothing lands on a red `main`: disarm the auto-merge the board
   lists (`gh pr merge --disable-auto <n>`).
   - **Re-landing reverted work.** After a revert, a fix pushed from the old
     branch re-merges only its new commits, and the reverted change stays
     out of `main` without anyone seeing it go. Re-land on a fresh branch from
     `main`: `git revert <the revert's sha>`, then the fix on top.

8. **A finding's row, its probe and its fix are one job**, filed by the seat
   assigned the fix, or not filed at all when the fix lands in the same lane
   (`STANDING_PRINCIPLES` §18: file only what needs its own oracle). The
   dispatcher files only what nobody is assigned to fix. A row filed before
   the fix was assigned is struck by the assignee and never re-filed from
   another block: ids are cheap, a second writer on one row is not. Asked for
   by win at the #179 review batch (2026-10-11): the dispatcher had filed nine
   rows from its own review and landed a strict-xfail bridge in a test file
   the fix lane would then have had to edit to delete the mark. The bridge
   went; the rows stayed for the fix lane to strike.

9. **Run the reviewers your lane's surface earns**: `python scripts/proof_tier.py
   --base origin/main` prints them on its `review:` line (`none`, `code-reviewer`
   or `both`: `/implement-task` step 6's rule computed from the diff, since
   2026-10-16), each on a snapshot clone with your edits frozen, and a reviewer
   the line does not name was not earned, so leaving it out is not a skipped step.

## What the dispatcher does, and does not

| Does | Does not |
|---|---|
| Turns the operator's priorities into assignments (`mail.py send --type assign --seat <seat> ...`): which seat works which job, and since 2026-10-15 sends them without a per-assign yes when the job is inside an approved pack or a live ledger row (the paragraph below) | Set the priorities: the operator does, by approving packs and naming the classes to drain; a new pack, a scope change, a release, or a call `cc/GOAL.md` lists as the operator's still goes to the operator |
| Sequences jobs that would collide: two jobs on one hot file, a record-format change while lanes are open | Gate changes: seats ship their own lanes |
| Keeps two jobs with clear gates on every seat's queue, each assign in its shape (*What an assign says*, under *How assignments behave*), and re-reads the gates when a lane merges; a gate names another seat's open lane and the file both touch | Gate a seat on its own open pull request (item 4: the cap is on pull requests, not work) |
| Answers worker requests at its next prompt (the operator prompts "dispatch", or a `/loop` does) | Review all code, or act as the merge queue |
| Backs up a red `main` that nobody else has reverted | Hold knowledge only in its own context: what it decides is written where every seat can read it |
| Carries a lighter lane of its own | Run the heaviest lanes, which compete with dispatching |
| Files the rows nobody is assigned to fix, and the ones its own measurements find | File rows for a job it has assigned: the finding, its probe and its fix are the assignee's one job (rule 8) |
| Reports counts that name their population, settings quoted from the tool that computes them, and the day's figures from `scripts/seat_day_census.py` | Carry a figure by hand, past a compaction or from memory |

**Assign authority (decided by the operator 2026-10-15, after two days'
measurement).** The dispatcher assigns, re-sequences and releases jobs on its
own when the job is a wave of a pack the operator has approved (its `Status`
not waiting on an operator decision) or a live ledger row or class; it does not
wait for a yes per assign. Outside that set the operator decides: a new pack,
a change to an approved pack's scope, a release or tag, a revert that is not
the Core Rule 15 red-`main` revert, and every item `cc/GOAL.md` lists under the
operator's open calls. Each assign is reported at the dispatcher's next tick
with the job and the reason, so the operator can veto it, and the day's
assigns go in the Session Log row. Why: the per-assign yes was the queue's
single point of failure. Measured on 2026-10-14 and 10-15, assign-to-first-claim
ran 0.4 to 1.6 hours with the operator present and 7.2 to 10.9 hours overnight
(three lanes assigned 02:00 to 04:11Z, claimed 12:00 to 15:00Z), while every
worker ask was answered within ten minutes; the dispatcher's recommendations
had been taken 13 of 13 times since 2026-10-14. The data point that falsifies
this: an assign the operator vetoes after the fact; two in a week re-opens the
rule.

**The seat's side of it** (the operator's yes, 2026-10-19; `TP-703e`). On a fork
the assign does not settle, the seat sends one request carrying its Task 0
recommendation and the citation behind it, and proceeds on that recommendation
after the dispatcher's tick interval with no answer: 15 minutes, the `/loop` in
`tools/cc/seat.py::DISPATCHER_TICK`, which a test holds this paragraph to
(`tests/test_seat.py::TestBrief`); the ack can still redirect it. The seat
stops, and only re-reads mail, for what the assign authority above reserves
for the operator (a new pack, a change to an approved pack's scope, a release
or tag, a revert that is not the red-`main` revert, an open call the goal file
lists), for a platform safety stop, for a refusal it cannot resolve, and for a
conflict outside its own files; a finding's row is the seat's own to file
(item 8), never a stop. A red the seat cannot fix in two attempts shelves the
lane (its claims stay, unless its push already released them; one note
beginning `shelved:` says what was tried and names any job that lane's push
closed) and the seat takes its next queued job; the dispatcher re-sequences
the shelved lane at its next tick and re-sends the assign of each job the note
names (the third closing rule closes a job at the push its claims cover,
before CI has run, and no read lists such jobs yet: `DEF-4037`). A redirect after the fact is an ack beginning
`redirect:`, and the Session Log row counts it as rework; `TP-703f`'s census
counts both words from the refs, so the falsifier below is read, never
recalled. Until the operator pastes the tick's new sentence (`TP-703e` 1-C-2),
a running loop's `STOP` governs that loop, and this paragraph is the rule the
paste carries. Measured before this clause: 19 of 20 rulings matched the
recommendation the request carried (10-17 to 10-18, hand-classified by the
dispatcher from its tick notes, not second-read), and the stop cost the seat
the ack latency (111 of 111 requests since 10-14 answered, median 8
minutes, p75 12, max 23, `scripts/mail_latency_census.py --since 2026-10-14`
read 2026-10-19) plus a read each time. What falsifies it: an
override after the fact that forces rework, twice in twenty.

A Claude session acts only when prompted. The design tolerates a dispatcher
that is away: a seat with a queue does not need it in real time.

**The dispatcher's first read is the board's `seats:` and `asks:` lines**
(`python3 tools/cc/board.py`, `TP-701` Wave A). `asks:` is every request no
`ack` names, from every seat (the dispatcher's own outgoing ones included: a
request names no addressee), oldest first with its full id and age; on the
dispatcher seat the banner's `Mail:` line carries the count and the oldest
age. A request that went moot is closed with an ack naming its full id and
saying so, or it stays on the line. `seats:` is each seat name's last mail
and, for this clone's checkouts, the live sessions Claude Code's registry
lists under the name each checkout answers: two in one checkout are flagged
and named by pid (the state the `win-2` relaunch reached at 2026-10-15 02:00Z,
caught then only by a seat reading its banner). A row with no checkout here
is its last mail only, and may be another machine, another clone or a
worktree since removed; so a quiet seat is asked, never presumed dead or
alive. Where its worktree is gone, the dispatcher releases its jobs (a
release naming the assign, as the assigner); its claims stay live until that
seat name releases them (item 5: a release from any other name is accepted
and closes nothing), which `seat.py retire` (`TP-701` B-2) does while the
worktree is still there; a worktree already gone needs the release by hand,
which `retire` prints. Both
were read by hand before (an ad-hoc census over every mail ref; the pids
checked one by one).

**Compare a job's functions, not only its files, before assigning it.** Grep
the pack task for the functions it edits and set them against what each seat's
live and queued lanes edit: many lanes touch a shared module such as
`espalier/cli.py`, so a file match says little and a function match is the
collision. On 2026-10-11 TP-476 B-1 edited `cmd_init`, `cmd_upgrade` and
`cmd_doctor`, which win-2's lanes 2 and 4 held, so B-1 went to win-2 after
lane 5 rather than to win. Sequence colliding jobs on one seat; do not write a
cross-seat gate.

**How assignments behave** (`tools/cc/mail.py`):
- Only the dispatcher may send an `assign`. The send refuses any other seat,
  a setting it cannot use, and a linked worktree whose name it inherited from
  its clone (that worktree would assign as the seat owning the name).
- **What an assign says.** The job (a row id, a class, or a lane for a pack's
  wave); why now; what it waits for, by the other seat's lane name and the file
  both touch; the operator's constraints on it; and any edge the dispatcher
  read, with the citation it read. Nothing the row or the tier script already
  says: `scripts/proof_tier.py --base origin/main` prints the tier and the
  reviewers from the diff, and an assign that restated them was wrong 3 times
  in 25 on 2026-10-18. A fix shape only with the citation behind it. Under 900
  characters: every assign of 2026-10-18 ran past that (median 1,957, 17 of 25
  at the 2,000 cap), and what filled the rest was the tool's output retyped.
  The send prints a note, never a refusal, past 900 characters or on a tier or
  reviewer phrase (`mail.py::assign_shape_notes`): an operator's tier override
  is a reason to name one, and the dispatcher decides.
- A job is its lane, classes and ids together, and the latest assign of a job
  wins. An assign that names the same lane with a different id set is a NEW
  job, not a replacement: the earlier one stays live until it is released by
  its id (three guard-majors jobs sat live on the board for nine hours on
  2026-10-11 until the seat asked). To reassign, release the old assign
  first (`mail.py send --type release --ack <assign id>`, the id the board and
  `assignments` print beside the job), then send the new one. To split one pack's waves across
  seats, name each wave by its lane alone: a pack id on two wave assigns makes
  each seat's plan warn about the other.
- A job closes when the assigner or the assigned seat releases it, by the
  assign's id or by its lane. The ship driver's lane release closes a job
  assigned by that lane, and a job naming no lane when the seat's own live
  claims on the released lane named every id it names and the seat began that
  lane (its first claim there) after the job was given, so a finished job stops
  warning without a release by hand (of the 25 jobs given on 2026-10-18, UTC,
  22 were closed by a hand release, and for 21 of them the seat's claims had
  named every id before that release). A claim's ids name what a lane touches,
  not what it fixed, so a lane whose claims were live when the job came does
  not close it: a row the current lane touches, queued as the seat's next job,
  stays live until a lane begun for it ships. A push releases its lane's
  claims, so a follow-up claim on that lane after the job came begins it again
  (no such case is on the refs yet: `DEF-4042`). A re-send of a live job starts
  its clock again. A seat releases its own claims by hand by their ids, never
  by lane: a lane release reads as the lane shipped (`DEF-4041`). A job assigned by its ids closes at the first push of a lane whose
  claims name them all, so a pack of several waves, or a row fixed across
  several lanes, is assigned wave by wave by lane, or its id is re-sent after
  each lane ships (the seat-day census names each such re-send, rows apart from
  packs).
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
