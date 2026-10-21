# TP-703d — The records say what happened: a row per seat per day as a debt the driver reads, the dispatcher's row derived, a justification on every assign, and a goal file that holds priorities

## Status

- Version target: adopter-facing where it touches `tools/cc/` (the ship driver, the board, the
  mail driver and the fragments loader deploy through `espalier init` via the vendored
  byte-copy, `espalier/_vendor/cc/`); self-host where it touches `memory/` and the handoff
  command's self-host paragraphs.
- Type: workflow infrastructure (the record layer's writer and its readers) plus process (the
  protocol's item 6 and the dispatcher's duties).
- **Kind: PACK.** One lane, `lane/the-records-say-what-happened`, in four sub-tasks; sub-task 1
  lands in two pushes by expand-then-contract (the board's reader first, the driver's refusal
  after a dated window). Sub-task 2 consumes `TP-703f`'s census script, so this pack is assigned
  after `TP-703f` merges; sub-tasks 1, 3 and 4 depend on nothing.
- Parent: `TP-703` (`task-packs/TP-703-multi-seat-discipline.md`), Wave 2, item 6. Authored
  2026-10-18 (local) by the dispatcher seat `air` on the operator's word ("good, lets make task
  packs for fixing these issues").
- Ledger: no row minted at authoring (protocol item 8: the assigned seat files or strikes
  in-lane). Rows reached are under Reach.
- The operator's call inside this pack: none. The debt cap below is pre-registered by the author
  and the executor may move it on Task 0's measurement, saying so in Landing.

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
  "Queues:" and "STATE" paragraphs name lanes and pull requests merged days before. Every seat's
  banner carries it only on this checkout: a worktree seat has no gitignored files
  (`memory/local-codename-arm.md`, the marker paragraph, says the same of the marker).
- **Parked rows are unseen.** `DEF-5007`'s closure text and the protocol's item 6: a handoff
  whose lane already merged parks its row on `refs/heads/records/<seat>`, and the banner's recent
  rows read the tree, so the row reaches no seat until some lane's push folds it. Nothing prints
  how many rows are parked.

Who is hurt (`STANDING_PRINCIPLES` §16): the operator, who on 2026-10-18 reconstructed what three
seats did over three days from pull-request bodies and 1,066 mail messages because the record
that exists for the purpose held one seat's rows; the next session on any seat, which opens on a
memory digest (`session_start.py`, three headlines from the newest rows) that names one seat's
work three times; and the dispatcher's own next session, which has no row to open on and a goal
file that names a state three days gone.

## Scope (in)

1. **A row per active seat per day, as a debt the driver reads (sub-task 1, two pushes).** A
   counting helper in `tools/cc/_record_fragments.py` (the newest row's date per seat, from the
   fragment names `SESSION_LOG_NAME_RE` already parses); a reader in `tools/cc/ship.py` of the
   seat's merged lanes since that date (`tools/cc/mail.py::lane_seats` names whose lane each
   merged pull request was); the board's new `records:` line, one entry per seat with a checkout
   or a live claim, "`<seat>`: N merges since its last row (`<date>`)", plus the rows parked on
   the seat's records ref and not yet folded ("2 rows parked, unseen until the next fold", from
   `tools/cc/mail.py::fetch_records` and `::pending`); then, in the second push after the window,
   `open_pr`'s `--early` arm refuses once the debt reaches the cap, naming the count, the last
   row's date and the way out (a row committed on this lane, which `lane_carries_memory_row`
   then reads as carried).
2. **The dispatcher's day row, derived (sub-task 2).** `scripts/seat_day_census.py` (built by
   `TP-703f`) prints a seat's day as a Session Log row body; the dispatcher's handoff files it
   through `python3 tools/cc/_record_fragments.py new session-log --seat <seat>` and edits the
   rulings in. One paragraph in `.claude/commands/handoff.md` "## 2. Write the session row"
   names the path; the protocol's dispatcher table gains the row as a duty.
3. **A justification on every assign (sub-task 3).** The `send` verb's assign arm in
   `tools/cc/mail.py` (beside `assign_refusal`) records a `cognitive_blueprint.py justify`
   entry after the send lands, with the assign's id as the content hash's input; where no
   blueprint node is open the verb says so in one line and the send stands.
4. **The goal file holds priorities; operator calls ride the channel (sub-task 4).** The
   dispatcher sends an operator call as a `request` whose text opens with `OPERATOR CALL:`, so
   `tools/cc/board.py`'s `asks:` section lists it for every seat until the dispatcher's `ack`
   quotes the ruling; the asks header counts them apart ("asks: 3 open, 2 operator calls"); the
   handoff command's "## 7. Refresh cc/GOAL.md" step says what the file keeps (the goal proper,
   the priorities, the `## Still owed` section `scripts/check_handoff_landing.py::check_owed`
   reads) and what it no longer carries (lane and pull-request numbers, queues, a state block).

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

**1-B The seat's merged lanes since that date** *(fix shape, untested; refuted if
`lane_seats` cannot name a merged lane's seat because the lane's claims were sent under another
spelling than the branch, which protocol item 2 already forbids and `refresh` reads)*. In
`tools/cc/ship.py`, a reader beside `seat_open_prs`: the merged pull requests from one bounded
`_gh_json("pr", "list", "--state", "merged", "--limit", ...)` with `headRefName` and `mergedAt`,
kept where `mail.lane_seats(by_machine)` names this seat and `mergedAt` falls after the seat's
newest row date (1-A over `git ls-tree --name-only origin/<base> memory/session-log.d`). Returns
the count and the date, or `None` with a reason where git or `gh` cannot answer: no verdict is
never a refusal on a guess, the same rule `lane_carries_memory_row` keeps.

**1-C The board's `records:` line** *(fix shape, untested)*. `tools/cc/board.py::collect` gains
a `records` key, one entry per seat named in `seats` with a checkout here or a live claim or job,
each read on its own (an unreadable one says so on its line, as every section does); `::render`
prints them after `seats:` and before `jobs:`. The parked count comes from
`mail.fetch_records` (already called by the fold) then `mail.pending(root, SESSION_LOG_DIR,
[f"origin/{base}"])` grouped by machine. Rendering: `records:  win: 9 merges since its last row
(2026-10-15); 0 rows parked`. `--json` carries the same as data.

**1-D The refusal, after the window** *(fix shape, untested; the window is the expand)*. The
second push, no sooner than three days of board lines after 1-C lands on `main` (the date goes in
Landing), adds the cap, the reader and the refusal beside `seat_open_prs`; `open_pr`'s `--early`
arm then calls `_refuse_on_row_debt(root, base)` right after its `early_reason` is read and before
its "shipping before the handoff" note:

```python target=tools/cc/ship.py
#: How many lanes a seat may ship past its newest Session Log row before
#: `open --early` refuses (TP-703d, pre-registered 2026-10-18; the executor may
#: move it on Task 0's measurement and says so in the pack's Landing).
ROW_DEBT_CAP = 3


def seat_row_debt(root: Path, base: str) -> tuple[int, str] | None:
    """``(merged lanes since this seat's newest Session Log row, that row's
    date or '')``, or None where git, gh or the mail channel cannot answer: no
    verdict is never a refusal on a guess (the rule ``lane_carries_memory_row``
    keeps). Lanes are the merged pull requests whose branch the seat's latest
    claim or release names (``mail.lane_seats``); the rows are the fragments
    on ``origin/<base>``, read by name alone."""
    mail, fragments = _mail_module(), _fragments_module()
    if mail is None or fragments is None:
        return None
    machine, _how = mail.machine_setting(root)
    if not machine:
        return None
    rc, names, _ = _git("ls-tree", "--name-only", f"origin/{base}", "--", fragments.SESSION_LOG_DIR + "/",
                        cwd=str(root))
    if rc != 0:
        return None
    newest = fragments.newest_row_date_by_seat(names.split()).get(machine, "")
    merged = _gh_json("pr", "list", "--state", "merged", "--limit", str(POST_MERGE_ROWS),
                      "--json", "headRefName,mergedAt", cwd=str(root))
    if not isinstance(merged, list):
        return None
    try:
        by_machine, _skipped = mail.read_mail(root)
    except mail.Unresolvable:
        return None
    seat_of = mail.lane_seats(by_machine)
    count = sum(1 for pr in merged if isinstance(pr, dict)
                and seat_of.get(str(pr.get("headRefName") or "")) == machine
                and str(pr.get("mergedAt") or "")[:10] > newest)
    return count, newest


def _refuse_on_row_debt(root: Path, base: str) -> None:
    """The second-push arm's one refusal that --early does not pass."""
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
Refuted if a seat's lanes are mostly records lanes carrying other seats' folded rows: the fold's
commits carry `FOLD_TRAILER` and `lane_carries_memory_row` already excludes them, and 1-B counts
merged pull requests, not rows, so a records lane counts as a lane; Task 0 item 3 decides whether
that over-counts. Mutation the test dies to: the comparison flipped (`>` for `>=`), the debt read
from the working tree instead of the base, and a `None` debt refusing.

### Sub-task 2: the dispatcher's day row, derived *(fix shape, untested; after `TP-703f`)*

`scripts/seat_day_census.py --seat air --date <day> --as-row` (the flag is `TP-703f`'s to land;
this pack's Task 0 at its start reads the script's `--help` and stops if the flag is not there)
prints one Session Log row line: the day's merges by this seat, assigns sent and closed, releases
owed, requests answered with the latency figures, and the rulings quoted from the dispatcher's
own `ack` texts, each a sentence. The handoff command's "## 2. Write the session row" gains one
paragraph: on the dispatcher seat, derive the body first, then add what the mail does not carry
(the operator's words, a Lesson), and file it where `python3 tools/cc/_record_fragments.py new
session-log` says. The protocol's dispatcher table gains "Writes its own day row, derived from
the mail and the merges" in the Does column. Refuted if the census cannot pair the day's rulings
to their requests: then the row carries the counts and the dispatcher writes the rulings by hand,
which is still a row.

### Sub-task 3: a justification on every assign *(fix shape, untested; Task 0 item 4 decides
the home)*

In the `send` verb's assign arm (after `assign_refusal` and the send), a helper
`record_assign_justification(root, message)` runs `cognitive_blueprint.py` from the same
directory through `sys.executable` with `justify --tool mail-assign --goal <the text's first
sentence> --step-rationale <the text> --expected-outcome <the seat takes the job> --not-doing
<the rest of the board's jobs> --content-hash <sha256 of the encoded message>`. Exit 0 is
silent; any other exit is one note naming the verb's own line, and the send is never undone (the
ref moved). `memory/action-justification-protocol.md` names `mail-assign` as a tool. Mutation the
test dies to: the hash computed before `send` stamped the id, so two assigns share one hash.

### Sub-task 4: the goal file holds priorities; operator calls ride the channel *(fix shape,
untested)*

- The dispatcher sends an operator call as `python tools/cc/mail.py send --type request --text
  "OPERATOR CALL: <the question, the options, the recommendation>"`; the operator's ruling is the
  dispatcher's `ack` quoting it. `tools/cc/board.py::render`'s asks header counts the requests
  whose text opens with the prefix apart: `asks:     3 open, 2 operator calls`. The prefix is
  one constant in `tools/cc/mail.py` beside `MAX_TEXT`, read by the board.
- `.claude/commands/inbox.md` "## Step 4: What to do with a request" gains two sentences: the
  prefix, and that a worker never acks one. `.claude/commands/handoff.md` "## 7. Refresh
  cc/GOAL.md" says what the file keeps and that queues, lane numbers and a state block are the
  board's and the mail's, not the goal's.
- Refuted if the operator reads rulings only from the dispatcher's tick report and never from the
  board: then the prefix buys the seats a live view and the operator nothing, which is still the
  seats' gain; Task 0 item 5 reads whether the line exists.

## Affected symbols

`/scope-check` keys on bare names; `collect`, `render`, `send` and `pending` recur across the
tree, so its gap list at authoring is collisions, not files this pack misses. Re-run it at the
lane's start.

### Changed-semantics
- `tools/cc/ship.py::open_pr` (the `--early` arm reads the seat's row debt; 1-D)
- `tools/cc/ship.py::_second_push_message` (names the debt cap)
- `tools/cc/board.py::collect` (a `records` key)
- `tools/cc/board.py::render` (the `records:` line; the asks header's operator-call count)
- `tools/cc/mail.py::live_requests` (unchanged body; the board reads the prefix over its result)

### Renamed
- None.

### Added-paths
- `tools/cc/_record_fragments.py::newest_row_date_by_seat`
- `tools/cc/ship.py::seat_row_debt`
- `tools/cc/ship.py::ROW_DEBT_CAP`
- `tools/cc/mail.py::record_assign_justification`
- `tools/cc/mail.py::OPERATOR_CALL_PREFIX`

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
  section names with a checkout or a live claim or job; the printed line names the count, the
  date and the parked rows; no existing board test's assertion is weakened and no fixture
  removed.
- Earn-the-red recorded per fix against the mutation named in its sub-task; a test that only
  ever passed does not count. 1-D's test drives `open_pr` through the existing `ship` fixture
  (`tests/test_ship_driver.py::TestTheLaneCarriesItsMemoryRowWhenHandoffPushes` is the
  neighbour) with a stubbed debt at the cap, one under it, and `None`.
- A `None` debt never refuses, and the note says the debt was unread; a seat whose newest row is
  today reads a debt of 0.
- `python3 tools/cc/mail.py send --type assign --dry-run ...` runs no `justify`; a real send on
  a scratch channel with a scratch blueprint node records one entry, read back by
  `cognitive_blueprint.py show-recent --n 1`.
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

**Modified:** `tools/cc/ship.py`; `tools/cc/board.py`; `tools/cc/mail.py`;
`tools/cc/_record_fragments.py`; `espalier/_vendor/cc/` (by `sync_vendor_cc.py` only);
`.claude/commands/handoff.md` and `.claude/commands/inbox.md` with their mirrors under
`espalier/assets/claude/commands/` and `examples/dogfooding/.claude/commands/` (by
`sync_claude_mirrors.py` only); `memory/parallel-work-protocol.md` (item 6 gains the debt and
the parked count; the dispatcher table gains the day row); `memory/action-justification-protocol.md`
(one tool name); `docs/WORKFLOW.md` "Parallel seats" (one sentence on the `records:` line) and
`espalier/assets/docs/WORKFLOW.md` (by `sync_asset_docs.py` only); `tests/test_ship_driver.py`;
`tests/test_board.py`; `tests/test_mail.py`; `tests/test_record_fragments.py`.

**Deleted:** none.

**Unmodified on purpose:** `tools/cc/seat.py` (the tick is the operator's; the brief needs no
change for a refusal the driver prints); `tools/cc/_record_fragments.py::SESSION_LOG_CAP` and
`::SESSION_LOG_SLACK` (Scope out); `tools/cc/hooks/session_start.py` (the digest reads the same
rows; the goal cap is `DEF-674`'s); `scripts/check_handoff_landing.py` (the owed arm stays the
goal file's one reader).

## Sub-task ordering

1. **Task 0**, items 1 to 3 and 5 at the lane's start; item 4 before sub-task 3. Checkpoint: the
   five results in Landing.
2. **Sub-task 1-A, 1-B, 1-C** (the readers), one push. Checkpoint: the `records:` line on this
   repository's board, the tests, the syncs, the tier.
3. **Sub-task 4** (the prefix and the words), the same push or the next. Checkpoint: the asks
   header with a prefixed request on a scratch channel.
4. **Sub-task 3** after Task 0 item 4. Checkpoint: one entry read back.
5. **Sub-task 2** after `TP-703f` merges. Checkpoint: the dispatcher's own row for the day
   filed through the verb.
6. **Red-team** before each push's tier: the reviewers `scripts/proof_tier.py --base origin/main`
   names, on a snapshot clone with edits frozen. What this pack most likely got wrong, for the
   pass to bite on: 1-B naming the wrong seat for a lane whose claims were released by the
   dispatcher (`lane_seats` takes the latest claim or release, and a release from another seat
   closes nothing but is still a message naming the lane); and 1-D refusing a records lane that
   exists only to fold other seats' rows.
7. **Sub-task 1-D** (the refusal), a second push no sooner than three days after 1-C is on
   `main`; its own red-team and tier. Checkpoint: the dated switch in Landing.
8. **Landing** in this file's stanza.

## Estimated effort

Pack budgets on this repository have run about 2.7 times over on one measured pack (`TP-459`);
read these as the author's guess, not a schedule.

| Sub-task | Build | Red-team and tier | Notes |
|---|---|---|---|
| 1-A to 1-C | 2 to 3 h | 1 h plus the full tier | one helper, one reader, one board section |
| 1-D | 1 h | 0.5 h plus the full tier | a second push after the window |
| 2 | 1 h | 0.5 h plus the contract slice | words and one filing; after `TP-703f` |
| 3 | 1 to 2 h | 0.5 h plus the full tier | a subprocess and its exit codes |
| 4 | 1 h | 0.5 h plus the contract slice | a prefix, a count, two command bodies |
| Total | 6 to 8 h | 3 h | expect the measured overrun |

## Landing
- State: DRAFT
- Commits:
- Suite:
- Earn-the-red: per sub-task, against the mutation its Implementation names
- Red-team: per push; authoring review not yet run
- Reach: see Reach; no row closed at authoring
- Task 0: not yet run
- The 1-D window: 1-C on `main` at (date); the refusal switched on at (date)
- Date: 2026-10-18 (authored, local)
