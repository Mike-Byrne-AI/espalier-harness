# TP-703d — The records say what happened: a row per seat per day as a debt the driver reads, the dispatcher's row derived, a justification on every assign, and a goal file that holds priorities

## Status

- Version target: adopter-facing where it touches `tools/cc/` (the ship driver, the board, the
  mail driver and the fragments loader deploy through `espalier init` via the vendored
  byte-copy, `espalier/_vendor/cc/`); self-host where it touches `memory/` and the handoff
  command's self-host paragraphs.
- Type: workflow infrastructure (the record layer's writer and its readers) plus process (the
  protocol's item 6 and the dispatcher's duties).
- **Kind: PACK.** Two lanes, by expand-then-contract: the first (the name the ship driver derives
  from its commit subject; authored as `lane/the-records-say-what-happened`) carries sub-task 1's
  readers (1-A to 1-C), sub-task 2 and sub-task 4; the second, no sooner than three days of board
  lines after the first is on `main`, carries the driver's refusal (1-D). Sub-task 2 consumes
  `TP-703f`'s census script, landed 2026-10-20 (#330). Sub-task 3 was struck on 2026-10-23 at this
  pack's 0-A, on the operator's ruling after Task 0 item 4 refuted it (Landing).
- Parent: `TP-703` (`task-packs/TP-703-multi-seat-discipline.md`), Wave 2, item 6. Authored
  2026-10-18 (local) by the dispatcher seat `air` on the operator's word ("good, lets make task
  packs for fixing these issues").
- Ledger: no row minted at authoring (protocol item 8: the assigned seat files or strikes
  in-lane). Rows reached are under Reach.
- The operator's calls inside this pack, both ruled 2026-10-23 at its 0-A: sub-task 3 dropped
  (the assign's text on origin is the justification; Task 0 item 4); sub-task 4 built whole, the
  seat brief and the protocol's two sentences re-pointed with it. The debt cap below is
  pre-registered by the author and the executor may move it on Task 0's measurement, saying so in
  Landing.

## Motivation

The Session Log row is the harness's cross-session record (Core Rule 4), and in the multi-seat
layer its writer is the handoff (`.claude/commands/handoff.md` "## 2. Write the session row"),
which a seat looping on `tools/cc/seat.py::WORKER_TICK` never reaches: the tick runs lanes, not
sessions. The one gate that asked for a row, `tools/cc/ship.py::open_pr`'s second-push question,
takes any non-empty `--early` reason, and `_second_push_message` tells the seat how to pass it.

Measured 2026-10-18 (local), each by the command named:

- **Rows against lanes.** `ls memory/session-log.d | sed -E 's/^([0-9-]{10})-[0-9]{6}-(.*)\.md$/\1 \2/' | sort | uniq -c`:
  10-16 win-2 5; 10-17 win-2 6; 10-18 air-work 1, win 1, win-2 7. Over 10-16 to 10-18 that is 20
  rows, 18 of them one seat's; the win and air-work rows of 10-18 are the handoffs the operator
  ordered that evening, not the loop's. The dispatcher seat `air` has no row since 10-15 (its last
  two are dated 10-15), across one session with nine compactions.
- **Early ships.** `gh pr list --state merged --limit 120 --json number,mergedAt,body` filtered
  to `mergedAt >= 2026-10-16`: 79 merged, 44 whose body carries `Shipped before the handoff`
  (the line `open_pr` writes), 26 whose body matches `row rides|rides a later|rides the next`.
  (`TP-703`'s Motivation read 77 and 15 at an earlier moment with a narrower phrase; this read
  supersedes it for this pack.)
- **The dispatcher's blueprint.** `cc/blueprints/latest.json` in this checkout, read by
  `python3 -c "import json; d=json.load(open('cc/blueprints/latest.json')); print(len(d['reasoning_entries']), len(d['action_justifications']))"`:
  0 and 0, after a day of 96 messages sent (25 of them assigns) from this seat; `python3
  tools/cc/cognitive_blueprint.py show-recent --n 5` prints nothing. Core Rule 7 asks every
  state-changing operation to carry a justification; an assign moves a ref on origin.
- **The goal file.** `cc/GOAL.md` (gitignored, this checkout only) read 4,186 bytes on this
  session's banner-health line against `tools/cc/hooks/session_start.py::_GOAL_HARD_CAP`
  (4,500) and the `goal` soft budget (2,000); its `_Updated:` line reads 2026-10-15 23:30; its
  "Queues:" and "STATE" paragraphs name lanes and pull requests merged days before (re-read
  2026-10-23: 3,529 bytes, updated 2026-10-20, its header already says queues and pull-request
  numbers are the board's, and its state section still names two pull requests, a commit and
  "the operator's open calls"). Every seat's
  banner carries it only on this checkout: a worktree seat has no gitignored files
  (`memory/local-codename-arm.md`, the marker paragraph, says the same of the marker).
- **Parked rows are unseen until a handoff.** `DEF-5007`'s closure text and the protocol's item 6:
  a handoff whose lane already merged parks its row on `refs/heads/records/<seat>`, and the
  banner's recent rows read the tree, so the row reaches no seat until some lane's push folds it.
  One reader prints the count: the landing check's session-log-cap note
  (`scripts/check_handoff_landing.py::check_session_log_cap`, "N pending on the records refs"),
  at a handoff, on the seat running it; the board prints nothing. (Authored as "nothing prints
  it"; corrected 2026-10-23, when Task 0 item 2 read the landing check as the reader its
  refuting result names and dropped the count from the board line.)

Who is hurt (`STANDING_PRINCIPLES` §16): the operator, who on 2026-10-18 reconstructed what three
seats did over three days from pull-request bodies and 1,066 mail messages because the record
that exists for the purpose held one seat's rows; the next session on any seat, which opens on a
memory digest (`session_start.py`, three headlines from the newest rows) that names one seat's
work three times; and the dispatcher's own next session, which has no row to open on and a goal
file that names a state three days gone.

## Scope (in)

1. **A row per active seat per day, as a debt the driver reads (sub-task 1, two lanes).** A
   counting helper in `tools/cc/_record_fragments.py` (the newest row's date per seat, from the
   fragment names `SESSION_LOG_NAME_RE` already parses); a reader in `tools/cc/ship.py` of the
   seat's merged lanes since that date, through the one merged-pull-request read
   (`tools/cc/_post_merge.py::read_merged`, which as built takes a field list, the lane fields
   `number,mergedAt,headRefName` beside the rollup ones; `tools/cc/mail.py::lane_seats` names whose
   lane each merged pull request was); the board's new
   `records:` line, one entry per seat with a checkout here or a live claim or job, "`<seat>`: N
   merges since its last row (`<date>`)"; then, in the second lane after the window, `open_pr`'s
   `--early` arm refuses once the debt reaches the cap, naming the count, the last row's date and
   the way out (a row committed on this lane, which `lane_carries_memory_row` then reads as
   carried). The parked rows' count stays off the line: Task 0 item 2 found the landing check
   already prints it.
2. **The dispatcher's day row, derived (sub-task 2).** `scripts/seat_day_census.py` (built by
   `TP-703f`) prints a seat's day as a Session Log row body; the dispatcher's handoff files it
   through `python3 tools/cc/_record_fragments.py new session-log --seat <seat>` and edits the
   rulings in. One paragraph in `.claude/commands/handoff.md` "## 2. Write the session row"
   names the path; the protocol's dispatcher table gains the row as a duty.
3. **Struck 2026-10-23 (the operator's ruling at 0-A).** A justification on every assign was to
   be a `cognitive_blueprint.py justify` entry recorded by the `send` verb's assign arm. Task 0
   item 4 refuted the home: the verb's tool token set is the hook matcher's (a dual witness three
   tests pin), so `--tool mail-assign` exits 2 at validation, and with an accepted token the
   dispatcher's loop has no open node (exit 3). `TP-703e` (#325) had already made "why now" part
   of every assign's text, which is the justification, on origin where every seat reads it; a
   second home would store what the message carries (the protocol's L1).
4. **The goal file holds priorities; operator calls ride the channel (sub-task 4).** The
   dispatcher sends an operator call as a `request` whose text opens with `OPERATOR CALL:`, so
   `tools/cc/board.py`'s `asks:` section lists it for every seat until the dispatcher's `ack`
   naming the request's full id carries the ruling; the asks header counts them apart ("asks: 3 open, 2 operator calls"); the
   two texts that send the dispatcher to the calls in `cc/GOAL.md` are re-pointed to the channel
   (`tools/cc/seat.py::SELF_HOST_ASSIGN` and the protocol's *Assign authority* paragraph with its
   dispatcher-table row; the operator's 2026-10-15 ruling keeps its substance, what the operator
   decides is unchanged, only where the list lives); the handoff command's "## 7. Refresh
   cc/GOAL.md" step says what the file keeps (its four seeded sections: the notes, the `## Still
   owed` section `scripts/check_handoff_landing.py::check_owed` reads, the goal proper, and the
   next-gate section in prose) and what it no longer carries (lane and pull-request numbers,
   queues, a state block that restates the board, the operator's open calls).

## Scope (out)

- **A row per lane push.** Twenty-five lanes a day against `SESSION_LOG_CAP` (30) leaves the
  banner's digest a one-day window; the cap would have to move with it, and the cap is the fold's
  one count (`DEF-5007`). A row per seat per day keeps the hot set meaningful. Re-raised if the
  re-measure's line 4 fails.
- **Deriving every seat's row.** The dispatcher's decisions are on its mail ref already; a worker
  seat's Lessons are not, and a derived row loses them. Workers write theirs; the census helps.
- **Changing `SESSION_LOG_CAP` or `SESSION_LOG_SLACK`.** The fold stays the one writer of the
  count; this pack adds readers and one refusal.
- **A contract test over `cc/GOAL.md`.** The file is gitignored and local to one checkout; no CI
  cell can read it. The landing check's owed arm (`check_owed`) is the one mechanical reader and
  stays so; sub-task 4 changes the handoff's words, not the arm.
- **The goal cap's value** (`_GOAL_HARD_CAP`, 4,500, against a proposed 2,500): the file this
  pack leaves is under either; `DEF-674`'s banner-budget lane (win-2, parked) owns the caps.
- **The worker tick's words.** `tools/cc/seat.py::WORKER_TICK` is the operator's paste
  (`tests/test_seat.py::_OPERATOR_TICK`); the refusal in `open_pr` reaches a looping seat with no
  tick change, so none is proposed here. `TP-703e` carries the tick's sentence.
- **`TP-700`'s runner.** A fresh session per lane would reach the handoff's row step on its own;
  nothing here waits on it, and the debt reader counts its lanes the same way.

## Task 0 — Verify (try to kill this pack)

Each names the oracle, the result that ends or narrows the pack, and the exit: stop and
re-raise to the dispatcher, never adjust and continue.

1. *Oracle:* the rows-per-seat-per-day count above, re-run at the lane's start, against merged
   lanes per seat per day (`gh pr list --state merged --limit 200 --json mergedAt,headRefName`,
   lanes to seats by `tools/cc/mail.py::lane_seats` over `tools/cc/mail.py::read_mail`'s fold).
   *Refuting result:* every seat that merged on a day has one or more rows dated that day.
   *Exit:* the record layer is not broken; stop. (Read 2026-10-18: 10-16 and 10-17 have one
   seat's rows and three seats' merges.)
2. *Oracle:* `git for-each-ref refs/remotes/origin/records/` after `python3 tools/cc/mail.py
   inbox` (the fetch) and `tools/cc/mail.py::pending(root, "memory/session-log.d", ["origin/main"])`
   in-process; then `python3 tools/cc/_record_fragments.py rows` and the banner's digest.
   *Refuting result:* a parked, unfolded row is already named by some reader. *Exit:* drop the
   parked count from the `records:` line; keep the debt.
3. *Oracle:* for each of the 44 early-shipped pull requests since 10-16, the fragments from its
   seat dated within one day after its merge (`gh pr list ... --json mergedAt,headRefName,body`
   against `ls memory/session-log.d`). *Refuting result:* 80% or more were followed by a row
   within a day. *Exit:* the debt is self-clearing and the refusal buys nothing; land the board
   line alone and strike the second push from Scope (in). (Expected to build: 10-16 and 10-17
   show one seat's rows against three seats' early ships.)
4. *Oracle:* `python3 tools/cc/cognitive_blueprint.py justify --goal x --step-rationale x
   --expected-outcome x --not-doing x --tool mail-assign --content-hash <64 hex>` on this
   checkout, whose `latest.json` holds a node with no entries, and once more in a scratch tree
   with no `cc/blueprints/` at all; read the exit codes against the verb's own comment block
   (`_EXIT_JUSTIFICATION_REFUSED` is 2; the others are named beside it). *Refuting result:* the
   verb needs an open node the dispatcher's loop never has (its node is finalized at the handoff
   it never runs, or absent in a worktree), so the entry has no home. *Exit:* sub-task 3 records
   the assign's reasoning on the mail message itself (a `why` field outside `RE_KEYS`, as
   `ASSIGN_SEAT_KEY` is) and the blueprint call goes; re-raise the choice.
5. *Oracle:* `grep -n 'dispatcher.s own outgoing' tools/cc/mail.py` and the asks line on this
   repository's board after a dispatcher request. *Refuting result:* a request the dispatcher
   sends is not listed under `asks:`. *Exit:* sub-task 4 needs its own reader; re-scope.
   (Measured 2026-10-18: `tools/cc/mail.py::live_requests`'s docstring says the dispatcher's own
   requests are included, and the board printed one on 10-17.)
6. *Oracle (added at `TP-703f`'s second review, 2026-10-20):* `python3 scripts/seat_day_census.py
   --fixture tests/fixtures/seat_day/refs-2026-10-18.json --seat air --date 2026-10-18 --as-row`
   against sub-task 2's field list. Read then: the dispatcher's row prints its assigns sent and the
   new jobs among them, the releases naming an assign (how many closed a live job and how many
   named a job already closed), the day's worker requests it answered, lanes merged, Session Log
   rows and the counted words; the jobs closed that day and the jobs live at the day's end (the
   releases owed) are in the census's report and `--json`, not in that row; the minutes to an
   answer are per requesting seat (answers from any seat), and the dispatcher's own answer
   latency is printed nowhere. *Refuting result:* a field
   sub-task 2 needs that the census prints nowhere. *Exit:* add the field to the census's
   dispatcher row in this lane, or derive it from `--json`; re-raise if the census cannot say it.

## Relevant memory

Recent pattern, measured: the record layer's last three changes (`TP-479` Wave C's fragments,
`DEF-5007`'s fold and park, this pack) each moved the writer and left a reader behind, and each
reader gap was found by a person noticing a row was missing, not by a gate. The parked row's
invisibility was documented in the closure that created it.

| Entry | Where |
|---|---|
| Parallel work protocol (item 6, the Session Log's transport) | `memory/parallel-work-protocol.md` |
| ESPALIER_MEMORY.md Line Limit | `docs/SHARP_EDGES.md` (section of that title) |
| Classify the surface before you measure it | `memory/classify-the-surface-before-measuring-it.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| Action justification protocol | `memory/action-justification-protocol.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "a Session Log row per seat the
handoff's fold and the parked rows"` and `... "the goal file the banner injects and the
operator's open calls"`; re-run them rather than trusting this list if the pack has been sitting.
The second query returned the hooks table first, which is lexical proximity, not an answer; the
protocol and the justification note are the rows that bear.

## Implementation

Every fix below is a **fix shape (untested)** unless marked measured; its refutation is named.

### Sub-task 1: the debt, read then enforced

**1-A The newest row per seat** *(fix shape, untested; refuted if `SESSION_LOG_NAME_RE` does
not carry the seat, which it does, group 3, read 2026-10-18)*. A helper beside
`this_sessions_row`, reading the tracked fragments by name only (no file is opened), so the board
can call it against the base's tree as well as the working tree:

```python target=tools/cc/_record_fragments.py
def newest_row_date_by_seat(names: list[str]) -> dict[str, str]:
    """``{seat: YYYY-MM-DD}`` of each seat's newest Session Log fragment among
    ``names`` (fragment file names, as ``git ls-tree --name-only`` or a
    directory listing gives them). A name the pattern does not match is not a
    row and is skipped, as the loader skips it."""
    newest: dict[str, str] = {}
    for name in names:
        m = SESSION_LOG_NAME_RE.match(name.rsplit("/", 1)[-1])
        if m and m.group(1) > newest.get(m.group(3), ""):
            newest[m.group(3)] = m.group(1)
    return newest
```

As built (2026-10-23) the loader also holds the count's other half, so the board and the ship
driver never disagree: `local_day(stamp, tz=None)` (an ISO stamp's YYYY-MM-DD in this clock's
zone, `tz` for a test; '' for none or an unreadable one), `lanes_since_row(merged, seat_of, seat,
newest, tz=None)` (the rows of a merged listing that are the seat's lanes merged on a local day
after `newest`), `ROW_DEBT_WINDOW` (100, three days at the measured 25 lanes a day), and
`newest_row_by_seat(names, parked)` (`{seat: (date, parked)}`, the newest across the base's tree
and the rows parked on the records refs, which `tools/cc/mail.py::pending` lists for both
readers). The parked read is not the parked count Task 0 item 2 dropped: a seat that wrote its
row and parked it is not in debt (this checkout's own 10-20 row sat parked on 10-23 while the
base's newest was 10-19), and `open_pr`'s early arm runs before `_fold_session_log`, so the
second lane's refusal would refuse a seat that did write its row unless the parked rows count;
the line says `parked until the next fold` beside such a date. Tests:
`tests/test_record_fragments.py::TestNewestRowDateBySeat` and `::TestLanesSinceRow`, the UTC-day
mutation among them.

**1-B The seat's merged lanes since that date** *(fix shape, untested; refuted if
`lane_seats` cannot name a merged lane's seat because the lane's claims were sent under another
spelling than the branch, which protocol item 2 already forbids and `refresh` reads)*. In
`tools/cc/ship.py`, a reader beside `seat_open_prs` over the one merged-pull-request read,
`_post_merge.read_merged(cwd, ROW_DEBT_WINDOW, gh=..., fields=LANE_FIELDS)` (the module's
docstring names it "the one `gh pr list --state merged` read"; as built it takes a `fields` list,
and the debt reads pass `LANE_FIELDS`, `number,mergedAt,headRefName`, so a hundred rows cost no
rollups and `MERGED_FIELDS` is unchanged), with a `gh` runner that turns the driver's `Refused` (a
`gh` answering without JSON) into `None` and remembers that it did; the rows kept are those
`mail.lane_seats(by_machine)` names this seat's and whose merge day, read in this clock's zone
(the fragment names carry the writer's local day, `_record_fragments.py::session_log_name`, while
`mergedAt` is UTC), falls after the seat's newest row date (1-A over `git ls-tree --name-only
origin/<base> memory/session-log.d`). Returns the count and the date, or `None` where git or `gh`
cannot answer: no verdict is never a refusal on a guess, the same rule `lane_carries_memory_row`
keeps. The window is the loader's `ROW_DEBT_WINDOW` (100 merges), three days at the measured 25
lanes a day across the seats; `POST_MERGE_ROWS` (20) would cover under one. Tests:
`tests/test_ship_driver.py::TestSeatRowDebt`, `tests/test_post_merge.py::TestReadMerged`.

**1-C The board's `records:` line** *(fix shape, untested)*. `tools/cc/board.py::collect` gains
a `records` key, one entry per seat named in `seats` with a checkout here or a live claim or job,
each read on its own (an unreadable one says so on its line, as every section does); `::render`
prints them after `seats:` and before `jobs:` (the render order is `seats:`, `jobs:`, `asks:`,
`claims:`, read from `render` 2026-10-23; the 0-A review had it the other way round).
Rendering: `records:  3 seats: win: 9 merges since its last row (2026-10-15)`, one seat a line;
a seat with no row on the base: `win: 9 merges, no row on origin/main`; a seat whose newest row
is parked: `(2026-10-20, parked until the next fold)`; a count the read stopped short of (the
window full and its oldest merge newer than the row): `60+ merges ... (the last 100 read)`; the
lanes no claim names counted apart on a last line; a seat with a lane merged in the window
listed even with nothing live (the end-of-day seat that owes its row); an unnamed clone says so. `--json` carries the same as data, and
the module docstring's section list names it. (Authored with a parked-rows count beside it;
dropped 2026-10-23 at Task 0 item 2.)

**1-D The refusal, after the window** *(fix shape, untested; the window is the expand)*. The
second lane, no sooner than three days of board lines after 1-C lands on `main` (the date goes in
Landing), adds the cap, the reader and the refusal beside `seat_open_prs`; `open_pr`'s `--early`
arm then calls `_refuse_on_row_debt(root, base)` right after its `early_reason` is read and before
its "shipping before the handoff" note. The reader is 1-B's, built in the first lane so the board
line and the refusal count the same way (`seat_row_debt` below is quoted as landed, for the
fence check; the second lane adds the two definitions after it, never a second copy):

```python target=tools/cc/ship.py
#: How many lanes a seat may ship past its newest Session Log row before
#: `open --early` refuses (TP-703d, pre-registered 2026-10-18; the executor may
#: move it on Task 0's measurement and says so in the pack's Landing).
ROW_DEBT_CAP = 3


def seat_row_debt(root: Path, base: str) -> tuple[int, str, bool] | None:
    """Landed in the first lane (2026-10-23), beside seat_open_prs: ``(merged
    lanes since this seat's newest Session Log row, that row's date or '',
    whether that row is parked on the records ref and not yet folded)``, or
    None where git, gh or the mail channel cannot answer. The count is the
    loader's ``lanes_since_row`` over the one merged read's lane fields, the
    board's ``records:`` line's own; the parked rows count because the early
    arm below runs before the fold that brings them in."""
    mail, fragments = _mail_module(), _fragments_module()
    if mail is None or fragments is None:
        return None
    machine, _how = mail.machine_setting(root)
    if not machine:
        return None
    rc, names, _ = _git("ls-tree", "--name-only", f"origin/{base}", "--", SESSION_LOG_DIR, cwd=str(root))
    if rc != 0:
        return None
    try:
        parked = [path for _machine, path, _ref in mail.pending(root, fragments.SESSION_LOG_DIR, [f"origin/{base}"])]
    except Exception:  # noqa: BLE001 -- the channel's named stop, or a read that raised: unread, never a count
        return None
    newest, is_parked = fragments.newest_row_by_seat(names.split(), parked).get(machine, ("", False))
    failed: list[str] = []

    def gh(args: list[str]) -> object:
        try:
            return _gh_json(*args, cwd=str(root))
        except Refused as exc:
            failed.append(str(exc))
            return None

    merged = _post_merge.read_merged(str(root), fragments.ROW_DEBT_WINDOW, gh=gh, fields=_post_merge.LANE_FIELDS)
    if failed:
        return None
    try:
        by_machine, _skipped = mail.read_mail(root)
    except Exception:  # noqa: BLE001 -- the channel's named stop, or a read that raised: unread, never a count
        return None
    seat_of = mail.lane_seats(by_machine)
    return fragments.lanes_since_row(merged, seat_of, machine, newest), newest, is_parked


def _refuse_on_row_debt(root: Path, base: str) -> None:
    """The early arm's one refusal that --early does not pass."""
    debt = seat_row_debt(root, base)
    if debt is None:
        _note("this seat's Session Log debt is unread (git, gh or the mail channel did not answer), so "
              "--early is taken as given")
        return
    if debt[0] >= ROW_DEBT_CAP:
        raise Refused(f"this seat has shipped {debt[0]} lanes since its last Session Log row "
                      f"({debt[1] or 'none'}); the cap is {ROW_DEBT_CAP}. Write the row on this lane "
                      "(python tools/cc/_record_fragments.py new session-log names the file) and commit it; "
                      "--early does not pass this one")
```

A `None` from 1-B (git or `gh` unreadable) never refuses; the note says the debt was unread.
The way out works because the early arm is skipped when the lane carries a row
(`lane_carries_memory_row`), not because the count drops: the reader never reads HEAD's own
rows. **What the second lane must handle** (the failure-mode review of the first lane,
2026-10-23): fetch the base and the records refs before `_refuse_on_row_debt` (the early arm
runs before `open_pr`'s base fetch and the fold's records fetch, so a row merged forty minutes
ago is not in the local base); a row riding the seat's own open pull request (neither on the
base nor parked: read `origin/<branch>` for the pull requests `seat_open_prs` found); a
renamed or relaunched worktree seat whose rows sit under the old name (print the name read and
the nearest seat's newest row); lanes no claim names, which escape the cap (the seat stamped on
the pull request, `DEF-4044`); records lanes counted as lanes (Task 0 item 3); sibling
attributes read outside a guard against an older kept loader (an `AttributeError` must read as
unread); a row lost to a revert of the lane that folded it, which `ever_added` still sees as
added, so it is never pending again (`DEF-4045`). Filed beside them from the same review:
`DEF-4043` (the banner's `Mail:` line counts the asks without the operator calls apart, a hook
file) and `DEF-4046` (the census reads rows from the working-tree glob, so parked rows are
missed). Handled in the second lane (2026-10-30), each with a named test except the records-lane
item, which was measured and built nothing; the record is Landing's second-lane entry.
Refuted if a seat's lanes are mostly records lanes carrying other seats' folded rows: the fold's
commits carry `FOLD_TRAILER` and `lane_carries_memory_row` already excludes them, and 1-B counts
merged pull requests, not rows, so a records lane counts as a lane; Task 0 item 3 decides whether
that over-counts. Mutation the test dies to: the comparison flipped (`>` for `>=`), the debt read
from the working tree instead of the base, a `None` debt refusing, a `gh` refusal reaching the
caller, and the merge day read in UTC (a 21:00 EDT merge after the day's row counted as debt).

### Sub-task 2: the dispatcher's day row, derived *(fix shape, untested; after `TP-703f`)*

`scripts/seat_day_census.py --seat air --date <day> --as-row` (landed in #330 with those
flags; Task 0 item 6 read its dispatcher row on 2026-10-23) prints one Session Log row line: the
day's merges by this seat, assigns sent and the new jobs among them, the releases naming an assign
(closed a live job, named a closed one), the worker requests it answered, the Session Log rows and
the counted words. The one field sub-task 2's list named that the row lacked is the releases owed:
the dispatcher's row gains "jobs live at <the day's end> N" from the `live` map the census's JSON
already carries (`scripts/seat_day_census.py::as_row`, the dispatcher branch). The per-seat
answer latency stays in the report (it is per requesting seat, not the dispatcher's figure), and
the rulings are written by hand. The handoff command's "## 2. Write the session row" gains one
self-host paragraph: on the dispatcher seat, derive the body first, then add what the mail does
not carry (the operator's words, the rulings, a Lesson), and file it where `python3
tools/cc/_record_fragments.py new session-log --seat <seat>` says. The protocol's dispatcher
table gains "Writes its own day row, derived from the mail and the merges" in the Does column.
Refuted if the census cannot pair the day's rulings to their requests: it cannot (its row prints
counts), so the row carries the counts and the dispatcher writes the rulings by hand, which is
still a row.

### Sub-task 3: struck 2026-10-23 (Task 0 item 4 refuted it; the operator's ruling at 0-A)

As authored: a helper `record_assign_justification(root, message)` in the `send` verb's assign
arm running `cognitive_blueprint.py justify --tool mail-assign ...` after the send. Measured
2026-10-23 on this checkout (a node open) and in a bare scratch tree (no `cc/blueprints/`):
`--tool mail-assign` exits 2 at validation both times (`_validate_action_justification` accepts
`Write`, `Edit`, `NotebookEdit`, `Bash`, `PowerShell` or an `mcp__` prefix, the set
`tests/test_hook_matcher_precision.py::test_mutation_tools_dual_witness` pins against the hook
matcher's), and `--tool Bash` with no node exits 3 (`_EXIT_NO_ACTIVE_SESSION`), the dispatcher's
loop's case. The pack's own exit was taken: the reasoning lives on the message, and since `TP-703e`
(#325) every assign's text carries "why now" by shape, so no new field is added either. Nothing
in `memory/action-justification-protocol.md` changes (its tool set stays closed), and
`tools/cc/cognitive_blueprint.py` is untouched.

### Sub-task 4: the goal file holds priorities; operator calls ride the channel *(fix shape,
untested)*

- The dispatcher sends an operator call as `python tools/cc/mail.py send --type request --text
  "OPERATOR CALL: <the question, the options, the recommendation>"`; the operator's ruling is the
  dispatcher's `ack` naming the request's full id (an ack from any other seat leaves the call open,
  found at the first lane's review). `tools/cc/board.py::render`'s asks header counts the requests
  whose text opens with the prefix apart: `asks:     3 open, 2 operator calls`. The prefix is
  one constant in `tools/cc/mail.py` beside `MAX_TEXT`, read by the board.
- `.claude/commands/inbox.md` "## Step 4: What to do with a request" gains two sentences: the
  prefix, and that a worker never acks one. `.claude/commands/handoff.md` "## 7. Refresh
  cc/GOAL.md" gains a self-host paragraph: the file keeps its four seeded sections (the notes,
  `## Still owed`, `## Goal`, `## Where we are / next gate` in prose) and no longer carries lane
  or pull-request numbers, queues, a state block that restates the board, or the operator's open
  calls, which are `OPERATOR CALL:` requests on the channel; the adopter-facing words and the
  seeded template (`init`; pinned by `tests/test_cli_deploy.py`) stay.
- The two texts that still send the dispatcher to the calls in `cc/GOAL.md` are re-pointed to
  the channel in this lane (found at 0-A, 2026-10-23; the pack had listed `seat.py` as unmodified):
  `tools/cc/seat.py::SELF_HOST_ASSIGN`'s "the open calls in cc/GOAL.md" becomes "the open
  operator calls on the board's asks line (`OPERATOR CALL:` requests)", and
  `memory/parallel-work-protocol.md`'s *Assign authority* paragraph and its dispatcher-table row
  say the same. The operator's 2026-10-15 ruling keeps its substance: what the operator decides is
  unchanged, only where the list lives.
- Refuted if the operator reads rulings only from the dispatcher's tick report and never from the
  board: then the prefix buys the seats a live view and the operator nothing, which is still the
  seats' gain; Task 0 item 5 reads whether the line exists.

## Affected symbols

`/scope-check` keys on bare names; `collect`, `render`, `send` and `pending` recur across the
tree, so its gap list at authoring is collisions, not files this pack misses. Re-run it at the
lane's start.

### Changed-semantics
- `tools/cc/ship.py::open_pr` (the `--early` arm reads the seat's row debt; 1-D, the second lane)
- `tools/cc/ship.py::_second_push_message` (names the debt cap; 1-D, the second lane)
- `tools/cc/_post_merge.py::read_merged` (a `fields` parameter; `MERGED_FIELDS` unchanged; the one merged read)
- `tools/cc/board.py::collect` (a `records` key)
- `tools/cc/board.py::render` (the `records:` line; the asks header's operator-call count)
- `tools/cc/mail.py::live_requests` (an operator call closes on an ack from its sender alone,
  found at the first lane's review; a plain request closes on anyone's, as before)
- `tools/cc/mail.py::lane_seats` (a release names a lane only from a machine that claimed it:
  the pack's predicted defect, reproduced at the first lane's review)
- `tools/cc/seat.py::SELF_HOST_ASSIGN` (the open calls' home is the channel)
- `scripts/seat_day_census.py::as_row` (the dispatcher's row names the day's live jobs)

### Renamed
- None.

### Added-paths
- `tools/cc/_record_fragments.py::newest_row_date_by_seat`
- `tools/cc/_record_fragments.py::local_day`
- `tools/cc/_record_fragments.py::lanes_since_row`
- `tools/cc/_record_fragments.py::ROW_DEBT_WINDOW`
- `tools/cc/_post_merge.py::LANE_FIELDS`
- `tools/cc/ship.py::seat_row_debt`
- `tools/cc/ship.py::ROW_DEBT_CAP` (the second lane)
- `tools/cc/board.py::read_row_names`
- `tools/cc/board.py::read_records_section`
- `tools/cc/board.py::records_lines`
- `tools/cc/mail.py::OPERATOR_CALL_PREFIX`
- `tools/cc/mail.py::is_operator_call`

### Removed-paths
- None.

## Reach

Not a class pack: it closes no ledger class and mints no row. The rows it touches, so no later
pass reads them as shut:

Members derived by: `grep -lE 'session-log|GOAL.md|action_justification|handoff' task-packs/ledger.d/*.md`
over live rows (re-run it; the two below are the ones this pack's mechanism reaches).

| Item | Status | Evidence |
|---|---|---|
| `DEF-5007` (closed 2026-10-16; the Session Log pruned in one place) | **EXTENDED, not re-opened** | the fold stays the one writer of the count; this pack adds a reader of its parked rows and one refusal upstream of it |
| `DEF-674` (the banner's budget wrong at both ends) | **NOT REACHED** | the goal file this pack leaves is under either cap; the caps are win-2's parked lane |

## Pass criteria

- `python3 tools/cc/board.py --json` carries `records` with one entry per seat the `seats`
  section names with a checkout or a live claim or job; the printed line names the count and the
  date; no existing board test's assertion is weakened and no fixture removed
  (`tests/test_board.py::TestRecordsLine`).
- Earn-the-red recorded per fix against the mutation named in its sub-task; a test that only
  ever passed does not count. The tests, by name: `tests/test_record_fragments.py::
  TestNewestRowDateBySeat` (1-A); `tests/test_post_merge.py` gains the field assertion beside the
  argument-list test (`LANE_FIELDS` names `headRefName`; `MERGED_FIELDS` is unchanged); `tests/test_ship_driver.py::
  TestSeatRowDebt` (1-B: the count against a stubbed `gh` and mail, a `gh` refusal reads `None`,
  the local day, the base's tree not the working tree); in the second lane `tests/test_ship_driver.py::
  TestOpenRefusesOnRowDebt` drives `open_pr` through the existing `ship` fixture
  (`TestTheLaneCarriesItsMemoryRowWhenHandoffPushes` is the neighbour) with a stubbed debt at the
  cap, one under it, and `None`; `tests/test_board.py::TestAsks` gains the operator-call count;
  `tests/test_seat_day_census.py` gains the dispatcher row's live-jobs assertion;
  `tests/test_seat.py` reads the brief's new words where it pins the old.
- A `None` debt never refuses, and the note says the debt was unread; a seat whose newest row is
  today reads a debt of 0.
- `python3 scripts/seat_day_census.py --fixture tests/fixtures/seat_day/refs-2026-10-18.json
  --seat air --date 2026-10-18 --as-row` names the jobs live at the day's end (2 on that fixture).
- The asks header on a board with two prefixed requests and one plain one reads `3 open, 2
  operator calls`; with none prefixed it reads as today.
- `python3 scripts/sync_vendor_cc.py`, `python3 scripts/sync_claude_mirrors.py` and `python3
  scripts/sync_asset_docs.py` report clean after the lane; the tier each push earns is run with
  `--base origin/main` and its receipt is in the pull request body (any `tools/cc/` edit earns the
  full tier, `scripts/proof_tier.py::is_runtime`; the line prints which).
- No criterion here licenses shipping a defect in the gate the pack delivers: a refusal that can
  be passed by an unreadable `gh`, or a debt counted from the working tree a seat can edit, is a
  defect of this pack, not a scope-out.

## Files touched

**New:** none.

**Modified:** `tools/cc/ship.py`; `tools/cc/_post_merge.py`; `tools/cc/board.py`;
`tools/cc/mail.py`; `tools/cc/_record_fragments.py`; `tools/cc/seat.py` (the brief's open-calls
clause); `espalier/_vendor/cc/` (by `sync_vendor_cc.py` only); `scripts/seat_day_census.py` (the
dispatcher row's live jobs); `.claude/commands/handoff.md` and `.claude/commands/inbox.md` with
their mirrors under `espalier/assets/claude/commands/` and `examples/dogfooding/.claude/commands/`
(by `sync_claude_mirrors.py` only); `memory/parallel-work-protocol.md` (item 6 gains the debt;
the dispatcher table gains the day row and the calls' home; the *Assign authority* paragraph
names the channel); `docs/WORKFLOW.md` "Parallel seats" (one sentence on the `records:` line and
one on `OPERATOR CALL:`) and `espalier/assets/docs/WORKFLOW.md` (by `sync_asset_docs.py` only);
`tests/test_ship_driver.py`; `tests/test_post_merge.py`; `tests/test_board.py`;
`tests/test_record_fragments.py`; `tests/test_seat_day_census.py`; `tests/test_seat.py` where it
pins the brief's words; `tests/test_mail.py` only if the prefix constant earns a contract there.

**Deleted:** none.

**Unmodified on purpose:** `tools/cc/seat.py::WORKER_TICK` (the tick is the operator's paste;
the brief's one clause changes, the tick does not); `tools/cc/cognitive_blueprint.py` and
`memory/action-justification-protocol.md` (sub-task 3 struck; the token set stays the hook
matcher's dual witness, and win-2's live `DEF-674` claim holds the module);
`tools/cc/_record_fragments.py::SESSION_LOG_CAP` and `::SESSION_LOG_SLACK` (Scope out);
`tools/cc/hooks/session_start.py` (the digest reads the same rows; the goal cap is `DEF-674`'s);
`scripts/check_handoff_landing.py` (the owed arm stays the goal file's one reader; its pending
count is the parked rows' reader).

## Cross-pack coordination

Added 2026-10-23 at 0-A (the review's item 3). Every sibling below is `DRAFT` and unassigned;
each re-reads these files at its own 0-A, as this pack did.

- `TP-703b` W2-B: `tools/cc/board.py` (`render`, `collect`), `tests/test_board.py`,
  `tools/cc/_post_merge.py`. This lane adds a `records` section and one field to
  `MERGED_FIELDS`; W2-B's rendered line is a different section.
- `TP-703g`: `tools/cc/ship.py` (a docstring), `tools/cc/mail.py` (a comment), `tools/cc/seat.py`
  (two clauses), `.claude/commands/inbox.md`, `docs/WORKFLOW.md`, the protocol. This lane's
  `seat.py` edit is the `SELF_HOST_ASSIGN` open-calls clause; 703g's two clauses are elsewhere in
  the brief and re-read it.
- `TP-703c`: `docs/WORKFLOW.md`, the protocol, `tools/cc/seat.py`.
- `TP-703h`, `TP-703j`: the protocol (703j's authored `board.py` overlap is gone from its file).
- Live claims: win's `DEF-4029` (`_bash_patterns.py`, `write_guard.py`, `docs/HOOKS.md`) shares
  nothing; win-2's `DEF-674` (`session_start.py`, `cognitive_blueprint.py`, `docs/HOOKS.md`)
  shares nothing now that sub-task 3 is struck.

## Sub-task ordering

1. **Task 0**, all six items at the lane's start (run 2026-10-23; Landing has the results).
2. **Sub-task 1-A, 1-B, 1-C** (the readers, `MERGED_FIELDS`), the first lane. Checkpoint: the
   `records:` line on this repository's board, the tests, the syncs, the tier.
3. **Sub-task 4** (the prefix, the count, the brief, the protocol, the two command bodies), the
   same lane. Checkpoint: the asks header with a prefixed request on a scratch channel.
4. **Sub-task 2** (the census's live-jobs field, the handoff paragraph, the dispatcher table), the
   same lane. Checkpoint: the row body printed from the fixture names the live jobs.
5. **Red-team** before the lane's tier: the reviewers `scripts/proof_tier.py --base origin/main`
   names, on a snapshot clone with edits frozen. What this pack most likely got wrong, for the
   pass to bite on: 1-B naming the wrong seat for a lane whose claims were released by the
   dispatcher (`lane_seats` takes the latest claim or release, and a release from another seat
   closes nothing but is still a message naming the lane: confirmed by the failure-mode review on
   copies and fixed in `lane_seats`, a release counting only after a claim); 1-B's local-day conversion on a
   runner whose zone is UTC (CI), where it must still equal the authoring read; and 1-D refusing
   a records lane that exists only to fold other seats' rows.
6. **Sub-task 1-D** (the refusal), the second lane, no sooner than three days after 1-C is on
   `main`; its own red-team and tier. Checkpoint: the dated switch in Landing, and the pack's
   move to `Done/`.
7. **Landing** in this file's stanza, per lane.

## Estimated effort

Pack budgets on this repository have run about 2.7 times over on one measured pack (`TP-459`);
read these as the author's guess, not a schedule.

| Sub-task | Build | Red-team and tier | Notes |
|---|---|---|---|
| 1-A to 1-C | 2 to 3 h | 1 h plus the full tier | one helper, one reader, one field, one board section |
| 1-D | 1 h | 0.5 h plus the full tier | the second lane, after the window |
| 2 | 1 h | 0.5 h (the lane's tier covers it) | one census field, words, one filing |
| 3 | struck | struck | Task 0 item 4 refuted it (2026-10-23) |
| 4 | 1 to 2 h | 0.5 h (the lane's tier covers it) | a prefix, a count, the brief, the protocol, two command bodies |
| Total | 5 to 7 h | 2.5 h | expect the measured overrun |

## Landing
- State: LANDED
- The first lane landed 2026-10-24 (local), single-seat, on `lane/the-records-say-what-happened`:
  sub-task 1's readers (1-A to 1-C), sub-task 2 and sub-task 4, with the review batch above.
- Commits: the first lane's one commit (its pull request names it; the handoff's Session Log
  row names the pull request).
- Suite: the full tier, `python3 scripts/proof_tier.py --run`, after the last edit: mypy clean
  (28 files), ruff clean, the parallel leg 24898 passed and 1 failed (the known box-local
  `tests/test_record_merge.py` red, Apple git 2.39.5's `update-index --unresolve`; CI's cells
  are the proof), the serial leg 2134 passed. An earlier full tier on the batch's first cut
  read four reds, three of them this lane's and fixed (the name-reader contract wanted its
  silence marker on `seat_row_debt`'s read; the probe-shape ratchet refused three probes that
  counted vocabulary in their own subject, re-keyed to structural reads; the recall eval's two
  pasted tables regenerated from one tree after the protocol's edit moved the corpus to 337
  documents). `espalier pre-release --skip-tests --skip-parity` pass; `espalier audit` 0
  findings; integrity refreshed and verified; the provenance census clean; the vendor, Claude
  and asset-doc syncs clean.
- Earn-the-red (the first lane, 2026-10-23): every behavior change's test was run red against the
  unfixed code before the fix (seven new or changed tests at the first build, eight more at the
  review's batch; the three that passed outright pin behavior the code already had and were
  earned through mutants); 36 of 36 named mutants killed on the final code in a scratch clone
  with its own venv (`.venv`, since the suite refuses an interpreter whose engine is another
  checkout), each by the test it names, a fresh bytecode prefix per mutant: the comparison
  flipped, the merge day read in UTC, no zone read as UTC, the oldest row for the newest, the
  parked flag never set or ignored (both readers), the debt read from HEAD (both readers), a
  failed or non-list `gh` as zero, the refusal or a raising git escaping, the window as
  `POST_MERGE_ROWS`, the rollup fields, the floor from the count or ignoring the oldest merge,
  the quiet seat listed, the shipping seat dropped, unclaimed lanes uncounted, the header
  without its count, every ask a call, the prefix on a note or mid-text, any seat's ack closing
  a call, a release from any seat naming the lane, the brief sent back to the goal file, the
  census's live jobs without seats, the field list ignored, unread as none, the records refs
  never fetched, the ask rows untagged, the unnamed clone as a clone with no seats. The archive
  probe over the seven touched test files: 773 passed.
- Red-team (the first lane, 2026-10-23, both reviewers at once on a snapshot clone with edits
  frozen, read in the order code then failure-mode): the code-reviewer APPROVE WITH WARNINGS
  (the window-cut flag compared one seat's count with the cross-seat window and never fired; a
  git timeout escaped `seat_row_debt`'s None contract; "6 to 11" overstated the measured 2 to
  11; "the ack quotes the ruling" against the full-id rule; the refusal's way out explained);
  the failure-mode-reviewer REQUEST CHANGES, 0 regressions, 7 gaps, 9 rough edges (the board
  never fetched the records refs, so a days-long dispatcher loop read parked rows as of its
  start; the pack's predicted `lane_seats` defect reproduced on copies: a dispatcher's lane
  release moved the lane, its debt and its open pull request; any seat's ack closed an operator
  call; the protocol's worker stop list still named the goal file; the census's `--date` is a UTC
  day where the row's date is local; the banner's `Mail:` line, the census's row read, and an
  unclaimed lane's zero as sister sites). One fix batch landed every must-land item from both
  and most rough edges (the seats with lanes in the window listed, the unnamed and the
  unread-name clones told apart, a non-list answer unread, the ask rows tagged, the brief's
  wording); the rest became the rows `DEF-4043` to `DEF-4046` and the second lane's list under
  1-D. A second round was not needed: the batch re-ran every touched test file (773 passed) and
  the mutants (36 of 36).
- 0-A (2026-10-23, `main` c0a44d1d): the fence check 2 of 2 python fences
  resolved; the code-reviewer on the Pack-artifact review checklist v2 returned REQUEST CHANGES
  (4 BLOCK: the `justify` tool token, the hash's missing `sha256:` prefix, `_gh_json` raising
  `Refused` through "None never refuses", the justify pass criterion; WARNs: no Cross-pack
  section, `seat.py` and the protocol still naming `cc/GOAL.md` as the calls' home, a second
  merged read against `read_merged`'s one-read docstring, local day against UTC `mergedAt`, the
  `records:` placement, `POST_MERGE_ROWS`'s window, stale figures), folded the same day on the
  operator's two rulings (sub-task 3 dropped; sub-task 4 built whole). 0-B: scope gap accepted
  (bare-name collisions, as the pack's note predicts). 0-C: compression debt accepted (one
  pre-existing canon-miss, `espalier/doctor.py::_host_is_windows`, the GOAL's unowned "doctor
  canon-miss", outside this pack's files). 0-D: no surface additions.
- Reach: see Reach; no row closed at authoring
- Task 0 (run 2026-10-23, `main` c0a44d1d, 200 merged pull requests, the mail refs as fetched):
  item 1 NOT refuted, 6 seat-days with merges and no row on `main` or parked (10-16: air 4,
  air-work 11, win 9; 10-17: air 2, air-work 6, win 9; local days); item 2 REFUTED, the landing
  check prints the pending count, so the parked count left the board line; item 3 NOT refuted,
  29 of 48 mapped early ships since 10-16 were followed by the seat's row within a day, 60%
  against the 80% line (air 8/4, air-work 13/8, win 8/7; 49 early ships, 1 unmapped), so 1-D
  stays; item 4 REFUTED, `--tool mail-assign` exits 2 here and in a bare tree, `--tool Bash` with
  no node exits 3, so sub-task 3 was struck on the operator's ruling; item 5 holds, the docstring
  and the fold include the dispatcher's own requests; item 6: the dispatcher's row prints every
  field but the day's live jobs, which its JSON carries, so the field is added here. The cap stays
  at 3.
- The second lane landed 2026-10-30 (local), seat `air-work`, on
  `lane/the-early-arm-refuses-on-row-debt` (assign e4f2eb): 1-D's refusal at the cap of 3, and
  the list under 1-D handled -- the base and the records refs fetched before the reading; a row
  riding the seat's own open pull request read from its fetched head; a renamed worktree seat told
  the seat name read and the other seats' newest rows; lanes no claim names attributed by the
  `seat:<name>` label `open` stamps (`DEF-4044` struck, at every site a branch is turned into a
  seat: the two readers, the board's open-PR tags, the one-per-seat advisory, the census);
  records lanes measured, none fold-only among the last 100 merges on `main` at 0020da9 (15
  carried a fold beside other work), so nothing built; every sibling read under the guard (an
  older kept loader's `AttributeError` reads as unread); a reverted fold's row pending again at
  the fold and at the park (`DEF-4045` struck) -- plus the pruned-newest-row edge the assign
  named: #354's prune took win's and win-2's newest rows off the tree and the line read `24+
  merges, no row`; on the dispatcher's ruling (request 6b94e5, ack 19efca: option (c) with three
  conditions) the readers take a seat's newest row from the base's history too, the fold's
  trailered prunes alone, through one loader call, and say `pruned` beside such a date; a shallow
  clone's cut history reads as unread, never as no pruned rows.
- Commits (the second lane): one on the lane; its pull request names it, and the Session Log row
  names the pull request.
- Suite (the second lane): the full tier, `python3 scripts/proof_tier.py --run --tier full --base
  origin/main`, twice. At the lane's first commit (ead1b0d3): mypy clean (28 files), ruff clean,
  the parallel leg 25174 passed and 3 failed, all this lane's own (two pack ids on a shipping
  surface, the provenance census; two name readers that took an unread name for none, the
  name-reader contract), the serial leg 2134 passed. After the fix (f50d41e9, the words and the
  readers unpacking the reason against `MACHINE_UNREAD`): mypy clean, ruff clean, the parallel leg
  25177 passed / 100 skipped / 3 xfailed in 26:40, the serial leg 2134 passed / 9 skipped in 3:53,
  `proof: PASS`. The syncs clean (vendor 60, Claude mirrors 74, asset docs 18); the integrity
  manifest refreshed and verified.
- Earn-the-red (the second lane, 2026-10-30): the new and changed tests run at the base 0020da9
  in a scratch clone with the lane's test files laid over it, 31 failed / 21 passed; the three
  strike guards red by assertion there (`(2, '2026-10-18', False) == (3, '2026-10-18', 'base')`,
  `1 == 2`, `(0, 0) == (1, 0)`) and green at the head. The mutants agent (Sonnet, under the
  assign's allowance) drove 36 named mutants on its own clone: 32 killed, one equivalent (the
  prefix-alone label reads '' either way), one expected survivor (`--topo-order` on a repository
  whose clock order already agrees), one mis-applied then killed on re-run, one real gap (the
  older-loader test's stand-in lacked every new name, so the read failed before the line the test
  named) closed in the fix batch.
- Red-team (the second lane, both reviewers at once on a frozen snapshot clone, read code then
  failure-mode): the code-reviewer REQUEST CHANGES, 0 block / 3 warn / 4 nit (the park still
  dropped a reverted row by the ever-added rule; a vacuous order assertion; the trailer unpinned at
  the callers; the riding read wider on the board than in the driver; the none-line dropping the
  unread note); the failure-mode-reviewer REQUEST CHANGES, 0 regressions / 7 gaps / 12 rough
  edges (the park; a label create that times out stopping the open as Held; a shallow clone's
  empty history read as no pruned rows; the fold's TypeError beside an older mail driver; the
  unnamed box blamed on git; a base fetch timeout refusing; the records line's `no claim names`
  words; the loader docstring's false strip reason; the refusal's `shipped` words). One fix
  batch landed every gap and warning and those rough edges, with a named test each; left as said
  in docstrings: the label's `--force` resetting colour and description at each open, an
  adopter's own `seat:` labels read as seats, a hand-deleted row coming back while its ref holds
  it; the trailer pinned at the two readers' stubs and not at the landing check's real-git test;
  the pass criterion's `unreadable gh` sentence resolved by the dispatcher's condition 2 (an
  unread debt never refuses). A second round was not needed: the batch re-ran the seven touched
  test files (871 passed) and the live board read.
- The 1-D window: 1-C on `main` at the first lane's merge (#334, 2026-10-24 07:51Z); the refusal
  switched on 2026-10-30 (local), six days of board lines later, in the second lane. The cap
  stays at 3. The pack stays in `task-packs/` beside its landed siblings (`TP-703a`, `c`, `e`,
  `f`, `g`, `i`, `j`), the children's convention since 2026-10-20.
- Date: 2026-10-18 (authored, local); corrected 2026-10-23 at 0-A; the first lane landed
  2026-10-24; the second lane landed 2026-10-30
