# TP-703f — Jobs close when the seat's own claim ships, and the dispatcher counts by tool: every board header carries its count, a census owns the day's figures

## Status

- Version target: adopter-facing where it touches `tools/cc/mail.py`, `tools/cc/board.py`,
  `tools/cc/seat.py` and `tools/cc/checkout_sync.py` (all deploy through `espalier init` via the vendored byte-copy,
  `espalier/_vendor/cc/`); `tools/cc/ship.py` is unchanged, and its push notice prints the
  board's overlap lines; self-host where it touches `scripts/` (the census), `tests/` and
  `memory/`.
- Type: workflow infrastructure (the assignments fold, the board's rendering, the dispatcher's
  brief) plus one instrument; the mail schema is unchanged.
- **Kind: PACK.** One lane, on the operator's ruling of 2026-10-20 at this pack's 0-A (authored as
  two): the census, the fold, the counts and the brief's sentence, under the name the ship driver
  derives from its commit subject. Its Task 0 can end it.
- Parent: `TP-703` (`task-packs/TP-703-multi-seat-discipline.md`), Wave 1, item 4; the
  roadmap's Task 0 item 5 is this pack's first gate and is restated below.
- Authored 2026-10-18 (local) by the dispatcher seat `air` on the operator's word ("good, lets
  make task packs for fixing these issues"), from the `/reflect` of the same evening.
- Ledger: no row filed at authoring. The defects are in a deployed tool (a job that only a hand
  can close; a board whose sections carry no count; a read that passes stale) and the lane
  files or strikes in-lane what its Task 0 shows needs its own oracle (protocol item 8). At the
  0-A: one row is filed in-lane, the stale read W3's drop leaves with a user (Scope out); at the
  reviews, six more (Reach).
- **One sentence inside this pack was the operator's:** the three rules for the dispatcher's
  brief (`tools/cc/seat.py::DISPATCHER_BRIEF`, whose duties the operator approved with
  `TP-701` B-7). Given 2026-10-20: yes, through a self-host slot, so an adopter's brief is
  unchanged; the brief is pinned by substrings, not byte for byte (Task 0 item 4).

## Motivation

**Jobs close by hand.** Read 2026-10-18 (local evening) over the four mail refs
(`refs/remotes/origin/mail/*` and this clone's `refs/heads/mail/air`, each message counted once
by its id): of the 25 assigns `air` sent on 2026-10-18, 24 named ids only and 1 named a lane;
of the 125 assigns on the ref, 64 named a lane. The ship driver's lane release
(`tools/cc/ship.py::_release_claims` through `tools/cc/mail.py::release_lane`) closes a job only
when the release's lane is the assign's lane (`tools/cc/mail.py::live_assignments`: a release
closes a job whose `ack` names the assign, or, with no `ack`, whose lane names the assign's
lane), so an assign that named ids closes only when a hand sends `send --type release --ack
<assign id>`. Closure of the 25 assigns of 10-18, read the same way: 22 by the dispatcher's
own release naming the assign, 1 by a worker's lane release, 2 still live at the read. The
dispatcher sent 28 releases naming an assign that day (re-sends and retractions among them).
Five jobs were owed a release when the dispatcher's loop stopped at 20:36Z (its tick notes).

**The board's sections carry no count.** On 2026-10-18 the dispatcher read the board through
a line filter (`sed -n '1,10p;/^asks:/,/^ledger:/p'`) that cut the `jobs:` section from six
rows to two, and reported a board defect that was its own filter; `python3 tools/cc/mail.py
assignments --json` showed all six (the tick notes, recorded as an instrument error). A header
that said `jobs: 6` would have shown the under-read on the one line the filter kept.

**A stale read passed as fresh.** The seats' improvised one-tier-at-a-time gate on the shared
win box read the mail refs and let a tier start when its fetch had failed, exit 0 (the
failure-mode reviewer's finding from the seats' notes of 10-18; the gate was a script on the
box, not in this tree, and is replaced by `TP-703c`). The driver's own reads say "reading what
is here" on a failed fetch (`tools/cc/mail.py::fetch_mail` returns `(ok, problem)`, and the
`inbox`, `claims` and `assignments` verbs print a note and continue; the board writes
`mail_note` and renders every section). Nothing lets a gate ask for a fresh read or nothing.

**The dispatcher's figures were hand-carried.** Nineteen statements corrected by the workers
in two days (the tick notes; unmeasured beyond them), of four kinds: a mechanism stated from
memory (8), a measurement narrower than its claim (5), a tool-computed setting restated (3), a
figure carried past a compaction (3). The standing rule "cite the grep or the measurement"
catches the first kind. The other three need a tool that prints the day's figures, so that no
tick report carries a number a hand typed, and a brief that says so.

**The named user (§16).** The dispatcher, whose every assign of the day cost it a release by
hand and whose board read was wrong by its own filter; the seat whose finished job stayed on
the board as live and kept warning every other seat's plan; and a gate's user on the win box,
who started a tier on a read the fetch had not refreshed.

**Read at this pack's 0-A (2026-10-20): the claims already name the jobs.** For each of the 22
jobs of 10-18 closed by a hand release, the assigned seat had sent a claim whose ids covered
the job's and then a lane release of that claim's lane (an independent replay of the refs; the
reviewer's stricter timing read 21). A fold that reads the claims closes them with no hand, no
new key and no new habit, which is what W1 now builds.

## Scope (in)

One lane (the operator's ruling of 2026-10-20, at this pack's 0-A): the census first, the fold
and the counts, the brief's sentence last. Its name is the one the ship driver derives from the
lane's commit subject.

1. **W4 The census** (built first, since the fold's attribution and the brief's sentence both
   name it). `scripts/seat_day_census.py` and `tests/test_seat_day_census.py`, with its fixture
   under `tests/fixtures/seat_day/`: per receiving seat per UTC day, from the mail refs and `gh
   pr list`: lanes merged; assigns received; jobs closed, by the rule that closed each
   (`live_assignments`' own record of it, W1-B: a release naming the assign, the assign's lane
   released, the seat's own claim shipped), and live at the window's end; requests sent and their
   ack latency (through `scripts/mail_latency_census.py`'s pairing); Session Log rows written;
   messages mentioning `START`, `redirect:` and `shelved:` (the protocol's sentence from
   `TP-703e` says this census counts the last two). `--json`; `--fixture` on a frozen copy of the
   refs; `--seat <seat> --date <day> --as-row` prints a Session Log row body for one seat and day,
   which `TP-703d` reads. Added at the review: per day, the releases the dispatcher sent naming
   an assign (the pre-registered measure below), the jobs re-sent after the claim rule closed
   them, and a dispatcher row that is what that seat sent; at the second review, every sender's
   releases naming an assign on its own row, the new jobs apart from re-sends, and the re-sent
   jobs split into rows and packs. Its test, its fixture, its roster line
   in `tests/_surface_expected.py`.
2. **W1 A job closes when its seat's own claim ships** (`tools/cc/mail.py`). `live_assignments`
   reads the claims in its ordered pass and closes a job on a third rule beside today's two: for a
   job that names no lane, a release from the seat the job was given to, naming a lane, closes the
   job when that seat's live claims on that lane together named every id the job names and the
   seat began that lane after the job's latest assign (both conditions added at the reviews,
   W1-A). No new key, no new flag, no
   change to the ship driver: the claims already carry the ids (measured below), and the driver's
   lane release at a push already names the lane. The fold also records, when asked, which
   release closed which job and by which rule, so the census reads the rules from their one home.
3. **W2 Section counts.** In `tools/cc/board.py`, every list section's header names its count:
   `open PRs: N`, `seats: N`, `jobs: N live`, `claims: N live`, `overlaps: N pairs`; `asks:`
   already does. `checks:` is left as it reads (below).
4. **The brief's sentence**, on the operator's ruling: the three rules (every count names its
   population; every setting a tool computes is quoted from the tool; the day's figures come from
   the census, never carried by hand) go into the dispatcher brief through a self-host slot in
   `tools/cc/seat.py`, so an adopter's brief is byte-for-byte today's, and into the protocol's
   dispatcher table as one row.
5. **The tests, the mirrors and the words.** `tests/test_mail.py`, `tests/test_board.py` and
   `tests/test_seat.py` gain the rows named under Implementation, and the board pins W2 moves are
   edited, not deleted. The closing-rule sentences the third rule outdates are updated in the same
   lane: `tools/cc/mail.py::live_assignments`' docstring, `.claude/commands/inbox.md` Step 2b and
   `memory/parallel-work-protocol.md` (*How assignments behave*, and the dispatcher table's row).
   The vendored byte-copy under `espalier/_vendor/cc/` is refreshed by `python3
   scripts/sync_vendor_cc.py` only, and `.claude/commands/inbox.md`'s two mirrors by `python3
   scripts/sync_claude_mirrors.py` only.

## Scope (out)

- **`--require-fresh` (W3 at authoring), dropped** on the operator's ruling of 2026-10-20 at this
  pack's 0-A: its only named user, the win box's off-tree tier gate, is retired by `TP-703c`, and
  no in-tree gate reads the mail verbs (`git grep` over the workflows, scripts and hooks); it was
  also the one item that changed `tools/cc/board.py::collect`, which `TP-703b` W2 and `TP-703d`
  edit, and its refusal as written would have run after `collect` logged the board's first
  mentions. The one stale read with a user, `tools/cc/seat.py`'s `retire` reading claims and jobs
  as last fetched after a failed fetch, is its own ledger row, filed in this lane.
- **A claim key naming the assign, and struck ids on the release** (W1 at authoring): not built.
  The claims already name the job's ids (22 of the 22 hand-closed jobs of 10-18, read at the 0-A; 21
  of them before their hand release, read at the second review), so the third
  rule needs neither, and the driver's derivation of a lane's strikes had five unsettled points.
  A job closed while its row stays live (the `DEF-985` shape, 1 in 25 on 10-18) is the
  dispatcher's to re-assign; the census counts it, and a rule keyed on strikes is pre-registered
  below for the day it is measured to matter.
- **What an assign says and when a seat proceeds**: `TP-703e`.
- **Writing the Session Log row** from the census, and the dispatcher's day row: `TP-703d`, which
  reads `--as-row`; this pack prints the body and writes no fragment.
- **The box gate itself**: `TP-703c`.
- **Closing a job on the operator's word** (a job retired because the row was struck by another
  seat, or the pack scrapped): the dispatcher's release by hand stays the way, and the census
  counts it, so the figure says how often it is still needed.
- **A redesign of the `assignments` verb or the job key** (`tools/cc/mail.py::_job_key`): the
  latest-assign-wins rule and the "a different id set is a new job" rule stand.
- **A count on `checks:`**: its lines are one verdict per check (a red, or a check never
  judged), its none-form already names the window it read, and a count would need the never-judged
  list the post-merge read does not carry; `TP-703b` W2 changes the section's read.
- **The mail cap** (`MAX_TEXT`) and **the assign's shape**: `TP-703e` and `TP-703g`.
- **Counting on the banner's lines** (`Mail:`, `Orders:`): the board is the live read.

## Cross-pack coordination

Added at this pack's 0-A (2026-10-20). Single-seat lanes make each a catch-up, never a conflict;
the board's `overlaps:` section is the oracle when seats run again.

- **`TP-703d`** reads the census's row (`--seat <seat> --date <day> --as-row`: this pack takes
  `TP-703d`'s spelling, so its Task 0 finds the flag; on the dispatcher's seat the row is what it
  sent: its assigns and how many were new jobs, the releases naming an assign it sent by hand, the
  day's worker requests it answered). Read at the second review: `TP-703d`'s dispatcher row also
  expects the jobs closed and the latency figures, which this row leaves to the report; its Task 0
  carries the field list. The row carries one UTC day's figures only, and says `UTC day` (a writer's local day
  can differ); the rulings quoted from acks stay the hand's, as `TP-703d` already allows. Shared files:
  `tools/cc/board.py::render`, `tools/cc/mail.py`, `.claude/commands/inbox.md`, the protocol;
  this pack first, as the roadmap orders.
- **`TP-703g`** inserts a clause into `tools/cc/seat.py::DISPATCHER_BRIEF` before `Start the
  loop`; this pack's slot sits before `Decisions stay the operator's.`. Adjacent, not shared; the
  second to land re-reads `tests/test_seat.py::TestBrief`'s pins.
- **`TP-703b`** W2 changes `tools/cc/board.py::collect` and the `checks:` section's read; this pack
  leaves the `checks:` read alone (W3 dropped, `checks:` uncounted) and changes `collect` in one
  place, the overlaps' note when the open pull requests are read to the read's limit.
- **`TP-703e`**'s protocol sentence names this census as the counter of `redirect:` and
  `shelved:`; W4 counts both.
- **`TP-703c`** retires W3's named user and edits `tools/cc/seat.py` (`child_env`, the launch;
  this pack's second review changed `by_hand_release` and `cmd_retire`'s claim ids);
  no symbol shared with the brief's slot.
- **`TP-703j`** edits `tools/cc/board.py` and the protocol; no symbol shared.

## Task 0 — Verify (try to kill this pack)

Each item names the oracle, the result that ends or narrows the pack, and the exit. The default
exit is stop and re-raise to the operator, never adjust and continue.

1. *Oracle (the roadmap's item 5):* over the four mail refs, for each assign of a UTC day, the
   first release after it from the dispatcher or the assigned seat that names its id or its lane,
   classified: a release naming the assign (a hand), the assign's lane released (the driver),
   none (live). *Refuting result:* the driver closes most. *Exit:* W1 is dropped; the rest lands.
   (Read 2026-10-18 over the 25 assigns of that UTC day: 22 by hand, 1 by the driver, 2 live;
   re-derived 2026-10-20 at the 0-A, twice, by the reviewer and by an independent replay.)
2. *Oracle (added at the 0-A):* for the same 25 assigns, whether the assigned seat sent a claim
   whose ids cover the assign's, then a lane release of that claim's lane. *Refuting result:* few
   do, so the third rule closes little. *Exit:* re-raise with the count; the authoring design (a
   claim key naming the assign) returns. (Read 2026-10-20: 22 of 25, and 22 of the 22 closed by
   hand; the reviewer's stricter timing read 21. Build.)
3. *Oracle:* `grep -n -E 'set\(collected\)|<= set|== set\(' tests/test_board.py`. *Refuting
   result:* an exact pin of the board JSON's key set. *Exit:* extend the pin before adding keys.
   (Read 2026-10-20: the pin is a subset, `tests/test_board.py::TestSeats` at about :1068, seven
   keys since #326; W2 adds no keys.)
4. *Oracle:* `grep -n -E 'DISPATCHER_BRIEF|Decisions stay|revert first on a red' tests/test_seat.py`.
   *Refuting result:* a byte-for-byte pin of the dispatcher's brief. *Exit:* the sentence becomes
   a proposal. (Pinned by substrings; the slot keeps every pin, and the adopter's brief is
   unchanged byte for byte.)
5. *Oracle:* the operator's word on the brief's sentence. (Given 2026-10-20: yes, in a self-host
   slot, with the protocol's dispatcher table.)
6. *Oracle:* `scripts/mail_latency_census.py::read_fixture`'s and `::read_refs`' shapes against
   what the census needs. *Refuting result:* none; a design reading. *Exit:* the census's fixture
   is its own shape (below), and it reuses `read_refs` (a flat, deduplicated list, regrouped by
   sender for the fold) and `pair` (which skips the dispatcher's own requests, so its requests-sent
   figure is the workers'). (Built: the census reads the refs through
   `tools/cc/mail.py::read_mail`, the fold's own reader, not `read_refs`; W4.)
7. *Oracle:* the six tree-wide gates `TP-702`'s Landing records red on a new `scripts/` file, each
   grepped for its current form before the script is written (its docstring naming no pack id; a
   literal argv for `gh`; `scripts/derived_population_census.py::ADJUDICATED` only if a fixture
   loads it; test docstrings with their rationale; the roster line; the ledger). *Exit:* W4 is
   written to them; `scripts/red_after_merge_census.py` (#326) is the freshest precedent.

## Relevant memory

Recent pattern, measured: the two instruments `TP-701` Wave C built (`scripts/ledger_trend.py`
repinned, `scripts/mail_latency_census.py` new) each replaced a figure that had been read once
by hand and could not be read again; three days later the dispatcher was again carrying by hand
the figures neither prints (jobs owed, hand releases, rows per seat). An instrument that prints
one figure leaves the others to the hand.

| Entry | Where |
|---|---|
| Parallel work protocol | `memory/parallel-work-protocol.md` |
| 4. Verify tool output through an independent oracle | `docs/STANDING_PRINCIPLES.md` |
| 14. Derive the list, don't test a hand-written copy of it | `docs/STANDING_PRINCIPLES.md` |
| A state-file allowed-set must glob dynamic flag families | `docs/SHARP_EDGES.md` (section of that title) |
| Untrusted oracle protocol | `memory/untrusted-oracle-protocol.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "a job assigned by id is
released by hand; derive the list, never a hand-carried count"`; re-run it rather than trusting
this list if the pack has been sitting. The protocol and §4 answered; the state-file entry is a
lexical neighbour kept for its rule (a hand-kept roster drifts), and the hook-authoring entry
the retriever also returned does not bear.

## Implementation

Every fix below is a **fix shape (untested)** unless marked measured; its refutation is named.
Rewritten at this pack's 0-A (2026-10-20) to the operator's four rulings; the authoring text's W1
(a claim key and struck ids on the release) and W3 (`--require-fresh`) are in Scope (out).

### W1 A job closes when its seat's own claim ships *(fix shape, untested)*

**W1-A The third rule, in the fold.** `tools/cc/mail.py::live_assignments` already orders the
assigns and releases of every ref by the stamp, the machine and the position in its file; claims
join that one pass. The fold keeps the live claims per (seat, lane): a claim with a lane adds its
ids under its sender and lane; a release whose `ack` names a claim removes that claim; a release
naming a lane, with no `ack`, is read for the jobs it closes first and then removes its sender's
claims on that lane, as `release_lane` releases them. Where the fold tests today's two rules
after its `who` check, a third joins them: with no `ack`, a lane, and `who` the seat the job was
given to (`ASSIGN_SEAT_KEY`), the job closes when its ids are not empty and every one is among
the ids of that seat's live claims on that lane, together. The job is the `_job_key`'s, so a
re-sent assign of the same job closes too. The docstring says the three rules in words, and that
a claim released by its id before the lane release no longer counts. Added at the first review
(the failure-mode reviewer's blocking finding, a refinement of the operator's ruling): a claim
counts only when the fold read it after the job's latest assign, and the rule reads only a job
that names no lane, which is the lane rule's. Over the fixture's two days the first moved one
closure of 44 (`DEF-2025`'s job, closed three hours before the lane that fixed it shipped) and
the second none of the 37 claim closures (each was of a job naming no lane). Changed at the
second review, on the operator's ruling of 2026-10-20: a claim's ids name what its lane touches,
not what it fixed, so a seat that claimed a queued row on its current lane, after the job was
given, still closed the job at that lane's push (`DEF-5003`/`DEF-5004`'s job on 10-15, kept live
only by a re-send). The fold now keeps, per seat and lane, where the seat's live claims there
began (its first live claim since its claims there last emptied), and the rule counts a lane's
claims only when the lane began after the job's latest assign. Over all 129 assigns on the refs
it moved one closure of 125 (`DEF-2021`, whose lane the seat began before the assign that
formalised it, to the dispatcher's hand release); the 10-15 job closes on the lane that fixed it
with or without the re-send; the 10-18 cohort is unchanged.

**W1-B The record of what closed.** `live_assignments` gains a keyword-only `closed: list | None =
None`; when a list is given, the fold appends one `(assign, release, rule)` per job it closes,
`rule` one of `ack`, `lane`, `claim`. Its five callers pass nothing and read the list the fold
now computes (`tools/cc/board.py::collect`, `tools/cc/execution_plan.py`, `tools/cc/mail.py::main`,
`tools/cc/seat.py::_read_channel`, and `tools/cc/hooks/session_start.py`'s `Orders:` line, the
fifth, named at the review: its code is unchanged and its output reads the new fold). The census
reads the rules through it, so the rules have one home.

*Refutations and the mutations the tests die to* (`tests/test_mail.py::TestAssignments`): an
assign naming ids only, the seat's claim on `lane/y` covering them, and its lane release of
`lane/y` close the job, and the record says `claim`; the same release from another seat leaves it
live (mutation: drop the `who` test); a claim short by one id leaves it live (mutation: any id in
common for every id); two claims on the lane that cover the ids together close it (mutation: the
first claim's ids only); a claim released by its id before the lane release leaves the job live
(mutation: no removal on a claim's release); the dispatcher's own lane release of `lane/y` closes
nothing by this rule (mutation: the assigner admitted); a release of another lane closes nothing
(mutation: any lane of the seat); a re-sent assign of the same job closes with it. Added at the
review: a claim sent before the job was given leaves it live (mutation: every claim counted); a
job naming a lane is not closed by a claim on another lane (mutation: the rule read for it); a job
naming no ids never closes by a claim (mutation: the empty-ids guard dropped); a release that names
an id is not read by the rule (mutation: the rule read on it); another seat's claims are neither
pooled into the cover nor released (two mutations); a malformed `ids` or `classes` field costs its
own message (mutations: either read raw, in the cover or in `_job_key`). Added at the second
review: a lane begun before the job leaves it live even when a claim after the assign names its
ids (mutation: a claim counted by when it was sent); a lane emptied, by a lane release or by
each claim's id, and begun again after the job closes it (mutation: a lane's start kept across
the release that emptied it); a re-send of a live job starts its clock again (mutation: the
job's first assign read); the job's ids read safely where its own seat releases, and no claim
rule on a release naming no lane (two mutations).

**Checkpoint:** `tests/test_mail.py::TestAssignments` at one worker; the five callers' tests
unchanged.

### W2 Section counts *(fix shape, untested)*

In `tools/cc/board.py::render`: `open PRs: N` on the first pull-request line (the `none` and
`unread` forms unchanged); `seats: N` before the first seat row, counting the rows printed and the
folded quiet ones; `jobs: N live` after the dispatcher parenthesis; `claims: N live` on the first
claim row; `overlap_lines` prints `overlaps: N pairs` before the first pair (the `none`, `none
among what was read` and `unread` forms unchanged). `overlap_lines` is shared with the ship
driver's push notice (`tools/cc/ship.py`), which therefore prints the count too. Each count is
`len()` of the list the section renders, computed where it renders and never stored on the board
dict, so `--json` carries the lists and the text their lengths. The board pins this moves are
edited in the same lane, by name: the `overlaps:` lines in `tests/test_board.py`, the `jobs:` line
and the `seats:` lines (the 0-A counted about twenty-two `overlaps:` pins and four others; the
ship driver's notice test stubs the board's `lane_overlap_lines`, so no pin there moved). Added at the review: a
count on a partial read says `N pairs among what was read`, as the empty form does, and a
pull-request list at its read limit says `N+ open (the first N)`; at the third review, the overlaps
over such a list count as partial on the board and in the ship notice (`OPEN_PR_CUT_NOTE`). *Mutation the tests die to:* a count
read from a stored field; a count that leaves out the folded quiet seats.

### The brief's sentence *(the operator's ruling: a self-host slot)*

`tools/cc/seat.py::DISPATCHER_BRIEF` gains a `{figures}` slot before `Decisions stay the
operator's.`; a new `SELF_HOST_FIGURES` is `Every count you state names its population, every
setting a tool computes is quoted from the tool, and the day's figures come from
scripts/seat_day_census.py, never carried by hand. ` (7-bit ASCII, no double quote, no `%`, no
brace), and `compose_brief` fills the slot with it on the self-host form and with nothing
otherwise, as `SELF_HOST_ASSIGN` is chosen. `tests/test_seat.py::TestBrief` keeps every pin and
gains two: the self-host dispatcher brief carries the sentence, and the adopter's names no
`seat_day_census` (the precedent pins `SELF_HOST_ASSIGN`'s absence). The three rules go into the
protocol's dispatcher table as one row as well.

### W4 The census *(fix shape, untested)*

`scripts/seat_day_census.py`, modelled on `scripts/mail_latency_census.py` (`--repo`,
`--fixture`, `--no-fetch`, `--since`, `--until`, `--json`; its `pair` and `parse_stamp` loaded by
path, and `tools/cc/mail.py` loaded by path for `read_mail`, `live_assignments` and `lane_seats`). It prints
the fetch's state and each ref's newest stamp first, as the latency census does. Per receiving
seat per UTC day in the window, one row: lanes merged (`gh pr list --state merged --limit 200
--json number,headRefName,mergedAt`, a literal argv, lanes to seats by `lane_seats` over the
refs; a branch no claim names is counted as unattributed, and a list at the limit says so);
assigns received; jobs closed, by rule (the fold's own record, W1-B), and live at the window's end;
requests sent and their median ack latency (`pair`, which leaves out the dispatcher's own
requests); Session Log rows (`tools/cc/_record_fragments.py::SESSION_LOG_NAME_RE`, the date and
seat groups; the file's date is its writer's local day, and a row parked on a records ref is not
in the tree, both said in the output); messages mentioning `START`, `redirect:` or `shelved:`;
and a totals row, the dispatcher's sends. `--seat <seat> --date <day> --as-row` prints one Session
Log row body in the fragments' shape with the day's figures and nothing a hand typed; it writes
no file.

The fixture, `tests/fixtures/seat_day/refs-2026-10-18.json`: the messages of the four refs from
2026-10-17T00:00Z to the freeze, with the fields the census reads (`id`, `type`, `from`, `at`,
`ack`, `re`'s lane, seat and ids) and a boolean each for the `START`, `redirect:` and `shelved:`
matches, no prose; and the merged pull requests of 10-18 as `gh` listed them (the requests,
acks and Session Log names of 10-18 too). Added at the review: the dispatcher's sends per day
(its assigns; the releases it sent naming an assign, and of those the ones that closed a live
job; the day's worker requests it answered), the jobs re-sent after the claim rule closed them,
each named; a failed fetch or `gh` read said in every form; `--date` a calendar day alone; a seat
no message names refused; the day so far, and the Session Log's archive horizon, said. Added at
the third review: `--jobs N` ends the window where the next new job after the Nth is given (the
JSON lists the new jobs' stamps), and each count of releases naming an assign prints both halves,
the ones that closed a live job and the ones that named a job already closed. The test
drives the fixture to the figures the fold this lane ships reads (pinned when built and recorded
in Landing: the 25 assigns of 10-18 to the three worker seats, how many each rule closes, the 2
live), and dies to a pairing that counts a release from the wrong seat and to an attribution that
re-states the rules instead of reading the fold's record.

*Refutation:* `pair`'s signature or `read_refs`' return shape changes under this lane's feet
(both are `scripts/`); the test pins the import, and the census then carries its own copy and
says so.

### Pre-registered (TP-703's re-measure, lines 6 and 7)

From the stamp of this lane's merge until the dispatcher has given 25 new jobs
(`scripts/seat_day_census.py --since <the merge's stamp> --jobs 25`; a re-send of a live job is
not a new job): the releases naming a job already closed that any seat sends in that window, from
26 on 2026-10-18 (all the dispatcher's, against 25 new jobs given that UTC day; read by the
census from the fixture) to at most 2; read by the census's totals line, every sender's on its
own row, never by the notes. These are the hand work the third rule makes needless, a hand
release of a job a seat's claim already closed, which the first-closer reading (22 of 25 in Task
0 item 1) cannot show. The releases that closed a live job are the dispatcher's own decisions (a
re-assign, which inbox Step 2b prescribes, a void, a hand-back), which no closing rule removes:
they are printed beside the figure and never judged (2 of the 28 on 10-18; a median of 3 per 25
new jobs over every ref on 2026-10-20, 1 to 6, the third review's floor, recounted). TP-703's
line 6 says the same; both were amended at this pack's reviews, before any window opened. The prediction, recorded in Landing, is the fold's reading
of 10-18's 25 assigns as a cohort: 21 close by the seat's own claim, 1 by the assign's lane, 1
by a release naming the assign, 2 live, where the old rules read 22 by hand. Over the ten days after the brief's sentence lands:
dispatcher statements corrected by a worker of the three later kinds, at most 2 a day, classified
by hand from the refs (corrections are prose; the census does not count them). If a job the
third rule closed is re-sent because its row stayed live, the census's `re-assigned after a
close` counts it under `rows` (a job naming a ledger row, by `tools/cc/ledger_row.py`'s own id
pattern), apart from `packs` (a pack's next-wave re-send); more than 2 rows in 25 new jobs opens
the strike-keyed rule Scope (out) names (on the fixture's two days: 0 rows, 1 pack, `TP-702`'s
next wave on 10-17). And on every board read, `jobs: N
live` equals the length of `python3 tools/cc/mail.py assignments --json` at the same fetch, which
a test pins.

## Affected symbols

`/scope-check` keys on bare names, so the board's `render` (a count on every header; the word is
everywhere) and the brief's `compose_brief` are named here and not below. Re-run the check at the
lane's start rather than trusting this list.

### Changed-semantics
- `tools/cc/mail.py::live_assignments` (reads the claims; the third closing rule; the `closed`
  record)
- `tools/cc/board.py::overlap_lines` (`N pairs` on the first line, in the board and the ship
  driver's notice)
- `tools/cc/seat.py::DISPATCHER_BRIEF` (the `{figures}` slot)

### Renamed
- None.

### Added-paths
- `tools/cc/seat.py::SELF_HOST_FIGURES`
- `scripts/seat_day_census.py`
- `tests/test_seat_day_census.py`
- `tests/fixtures/seat_day/`

### Removed-paths
- None.

## Reach

Not a class pack: it closes no ledger class. It files seven rows in-lane: at the 0-A, `DEF-4036`,
`tools/cc/seat.py`'s `retire` reading claims and jobs as last fetched after a failed fetch, at
both of its reads (the stale read W3's drop leaves with a user); and from the review, `DEF-4037`
(a job the claim rule closes at a push stays closed when the lane is then shelved: the board
listing such jobs is the operator's call), `DEF-4038` (whether a claim is live is decided in two
places) and `DEF-4039` (a board list added later need not carry its count; `TP-703d` adds the
next one); and from the second review, `DEF-4040` (a job given by its ids closes at the first lane
whose claims name them, so a row fixed across lanes closes early; probable, two rows on the refs);
and from the third, `DEF-4041` (a lane release a seat sends by hand closes its job as if shipped,
with no note) and `DEF-4042` (a lane a push emptied begins again at the next claim, so a follow-up
push can close a queued job; no case on the refs). `DEF-985`'s re-pin is the shape the pre-registered strike rule would catch,
not a member.

## Pass criteria

- On a fixture of two seats: an assign naming ids only, the assigned seat's claim on `lane/y`
  covering them, and its lane release of `lane/y`: `live_assignments` is empty and its record says
  `claim`; the same release from the other seat, a claim short by an id, a claim released by its
  id first, the dispatcher's own lane release and a release of another lane each leave it live;
  two claims covering the ids together close it; a re-sent assign of the job closes with it; a
  claim sent before the job was given, and a claim on another lane for a job naming a lane, leave
  it live; a claim on a lane the seat began before the job leaves it live even when sent after the
  job, and a lane whose claims emptied and began again after the job closes it. No
  `tests/test_mail.py` assertion is weakened and no fixture removed.
- `python3 tools/cc/board.py --no-fetch` on this repository prints `jobs: N live`, `claims: N
  live`, `open PRs: N` and, where a pair exists, `overlaps: N pairs`, each `N` the length of the
  matching `--json` list; a test pins each count against its list, the `none` forms and `asks:`
  unchanged; `checks:` reads as before.
- The self-host dispatcher brief carries the sentence; the adopter's brief is byte-for-byte what
  it was and names no `seat_day_census`; every `TestBrief` pin holds.
- `python3 scripts/seat_day_census.py --fixture tests/fixtures/seat_day/refs-2026-10-18.json
  --since 2026-10-18 --until 2026-10-19 --json` prints the pinned figures (recorded in Landing);
  `--seat air --date 2026-10-18 --as-row` prints the dispatcher's row, what it sent, in the
  fragments' shape and writes nothing.
- Earn-the-red recorded per fix against the mutations named in W1, W2, the brief and W4; a test
  that only ever passed does not count.
- The syncs report clean; the tier `scripts/proof_tier.py --base origin/main` prints is the one
  run, its receipt in the pull request body.
- No criterion here licenses shipping a defect in the fold this pack delivers: a release that
  closes a job its seat's claims did not cover, or a count that can disagree with its list, is a
  defect of this pack, never a scope-out.

## Files touched

**New:** `scripts/seat_day_census.py`; `tests/test_seat_day_census.py`;
`tests/fixtures/seat_day/refs-2026-10-18.json`; a changelog fragment; the seven rows' files under
`task-packs/ledger.d/` and their probe files (`DEF-4036` to `DEF-4042`).

**Modified:** `tools/cc/mail.py` (the fold, its docstring, `_job_key`'s reads, `_lane_of`);
`tools/cc/board.py` (the counts, and the overlaps' note at the open pull requests' read limit, on
the board and in the ship notice);
`tools/cc/seat.py` (the slot, and `retire`'s recipe releasing by claim id);
`tools/cc/checkout_sync.py` (the reaper's reason, releasing by claim id); `tests/test_mail.py`;
`tests/test_board.py`; `tests/test_seat.py`; `tests/test_checkout_sync.py`;
`tests/_surface_expected.py` (the roster line); `memory/parallel-work-protocol.md`;
`.claude/commands/inbox.md` and its two mirrors (by `sync_claude_mirrors.py` only);
`espalier/_vendor/cc/` (by `sync_vendor_cc.py` only); `task-packs/TP-703-multi-seat-discipline.md`
(the baseline sentences, 22 of 25, line 6 of the re-measure, and the Children line);
`task-packs/TP-703d-the-records-say-what-happened.md` (one Task 0 item: the census row's fields).

**Deleted:** none.

**Unmodified on purpose:** `tools/cc/ship.py` (its lane release already names the lane the third
rule reads); `tools/cc/mail.py::new_message` and `::MAX_TEXT` (`_job_key` changed at the
review: its reads of `classes` and `ids` go through `_str_list`, the job the same for every
well-formed message); `tests/test_ship_driver.py` (its notice test stubs the board's `lane_overlap_lines`);
`tools/cc/seat.py::WORKER_TICK` (the operator's paste); `scripts/mail_latency_census.py` (reused,
not changed); `tools/cc/hooks/*` (no hook change, so no `docs/HOOKS.md` edit and no marker in the
title).

## Sub-task ordering

1. **Task 0** items 1 to 7 (item 5 given). Checkpoint: the results in Landing.
2. **W4** (the census, its fixture and test, the roster line), then **W1** (the third rule and the
   record; the census's attribution switches to the record when it lands, in this lane), then
   **W2**, then **the brief's sentence**. Checkpoint per step: the touched test file at one
   worker.
3. **The ledger row** for `retire`'s stale read, by the verb.
4. **Red-team**, both reviewers on a snapshot clone as the tier line names, one fix batch. What
   this pack most likely got wrong, for the pass to bite on: a claim released by its id and then
   re-made on the same lane name (the fold must read the live claims at the release, not every
   claim ever made); a re-sent assign whose ids differ (a new job, which the third rule closes on
   its own ids); a count on `seats:` that disagrees with the folded line's `and N more`; the census
   reading a day in UTC while the Session Log names a local day.
5. **The tier** the lane earns, `--base origin/main`; the syncs; the ship.

## Estimated effort

Pack budgets on this repository have run about 2.7 times over on one measured pack (`TP-459`);
read these as the author's guess, not a schedule. Re-estimated at the 0-A for the rulings.

| Wave | Build | Red-team and tier | Notes |
|---|---|---|---|
| Task 0 | done at the 0-A | | the replay of the claims |
| W1 | 1.5 to 2 h | 0.5 h | one rule and a record in one fold, its rows |
| W2 | 1 to 1.5 h | 0.5 h | the counts and the pins they move |
| The brief | 0.5 h | the pins | one slot, two assertions |
| W4 | 3 to 4 h | 0.5 h | a script, a fixture, a test, the roster |
| Total | 6 to 8 h | 1.5 h plus one full tier | expect the measured overrun |

## Landing
- State: LANDED
- Landed: 2026-10-20 (local), single-seat, one lane, `lane/mail-jobs-close-when-the-seat-s-own-claim-ships`.
- Commits: the lane's commit (its pull request names it).
- Suite: the full tier, `python3 scripts/proof_tier.py --run`, after the last code edit: mypy clean
  (28 files), ruff clean, the parallel leg 24865 passed and 1 failed (the known box-local
  `tests/test_record_merge.py` red, Apple git 2.39.5's `update-index --unresolve`), the serial
  leg 2134 passed. After the records edit, the contract slice and the touched test files in an
  extracted release archive (the pull request carries both receipts).
- Earn-the-red: 22 named mutants at the build, 58 after the first review's batch, 86 of 86 on the
  final code, each killed by the test it names, in a scratch copy of the snapshot clone; the
  shipped fold matched an independent implementation of the lane-begun rule on all 129 assigns on
  the mail refs.
- Red-team: code-reviewer and failure-mode-reviewer on a snapshot clone, three rounds.
  - Round 1: both REQUEST CHANGES (code: 1 BLOCK, the census naming the Session Log folder by
    hand; 7 WARN, 6 NIT. Failure-mode: 7 GAP, the blocker a queued job closed at the push of the
    lane before its own; 8 ROUGH-EDGE). One fix batch.
  - Round 2: both REQUEST CHANGES (code: 1 BLOCK, the batch's own `gh` argv made dynamic to the
    subprocess-contract gate; 5 WARN, 7 NIT. Failure-mode: 1 REGRESSION, `retire`'s gone-worktree
    recipe released by lane; 2 GAP; 3 ROUGH-EDGE). To the operator, who ruled 2026-10-20: the
    lane-begun rule (one closure of 125 moved on the refs), the must-fixes with the cheap items,
    and a narrow third round.
  - Round 3, narrow: both REQUEST CHANGES (code: 0 BLOCK, 1 WARN, 4 NIT, "no further full round
    is warranted". Failure-mode: 1 REGRESSION, inbox Step 3's shrink recipe by lane; 3 GAP, line
    6's target on the decision floor, its window end, the "never closes it" wording; 3
    ROUGH-EDGE). To the operator, who ruled: line 6 on the releases naming a job already closed,
    and the final batch shipped on proof with no fourth round.
- Reach: not a class pack; seven rows filed in-lane (`DEF-4036` to `DEF-4042`)
- The census's figures, pinned by `tests/test_seat_day_census.py` on the fixture: the UTC day of
  2026-10-18 holds 25 assigns sent, all new jobs, to the three worker seats; 27 closures stamped
  that day (24 by the seat's own claim, 1 by an assign's lane, 2 by a release naming the assign;
  4 of them of jobs given on 10-17); 2 jobs live at the day's end; 28 releases naming an assign,
  all the dispatcher's, 2 closing a live job and 26 naming a job already closed; 28 merges, none
  unattributed.
- Prediction (the pre-registered lines): the 25 assigns of 10-18, read as a cohort, close 21 by
  the seat's own claim, 1 by the assign's lane, 1 by a release naming the assign, 2 live (the old
  rules: 22 by hand, 1 by lane, 2 live). TP-703's line 6, from this lane's merge stamp with
  `--jobs 25`: the releases naming a job already closed, 26 on 10-18, to at most 2, the ones that
  closed a live job printed beside (median 3 per 25 new jobs, 1 to 6, over every ref on
  2026-10-20).
- 0-A (2026-10-20, `main` at 96b75fe2): code-reviewer, Pack-artifact review checklist v2, REQUEST
  CHANGES (3 BLOCK: the release-carries-assigns plumbing would fail the driver's release, W3's
  refusal ran after `collect` logged first mentions, the brief's sentence would reach adopters
  naming a self-host script; 14 WARN; 8 NIT). The operator ruled, 2026-10-20: jobs close when the
  seat's own claim covers them; W3 dropped, its stale read with a user filed as a row; the
  sentence in a self-host slot; one lane. Folded before any code: the Cross-pack section, the
  `TP-703d` flag spelling, the census's attribution through the fold, `redirect:` and `shelved:`,
  the fixture's trim, the pins W2 moves, the `checks:` exclusion, the roadmap's baseline. Fence
  check: 2 python, 2 checked, clean.
- Task 0: item 1 22 by hand, 1 by the driver, 2 live (25 assigns, UTC 10-18); item 2 the claims
  covered 22 of the 22 closed by hand: build.
- Date: 2026-10-18 (authored, local)
