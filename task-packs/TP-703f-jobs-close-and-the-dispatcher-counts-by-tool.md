# TP-703f — Jobs close by construction, and the dispatcher counts by tool: the claim carries its assign, the release carries what it struck, every board header carries its count, a census owns the day's figures

## Status

- Version target: adopter-facing where it touches `tools/cc/mail.py`, `tools/cc/ship.py`,
  `tools/cc/board.py` and `tools/cc/seat.py` (all deploy through `espalier init` via the
  vendored byte-copy, `espalier/_vendor/cc/`); self-host where it touches `scripts/` (the
  census), `tests/` and `memory/`.
- Type: workflow infrastructure (the mail channel's claim and release schema, the assignments
  fold, the board's rendering, one flag on every mail read a gate consumes) plus one
  instrument.
- **Kind: PACK.** Two lanes. `lane/jobs-close-by-construction` carries Waves 1 to 3 and the
  brief's sentence (the deployed driver; one tier). `lane/the-dispatchers-instruments` carries
  Wave 4 (the census under `scripts/`, its test, its fixture and its roster line) and can land
  first: `TP-703d` reads its `--row` and the roadmap's Task 0 reads its figures, and it changes
  nothing a seat's tick runs. Each lane's Task 0 can end it.
- Parent: `TP-703` (`task-packs/TP-703-multi-seat-discipline.md`), Wave 1, item 4; the
  roadmap's Task 0 item 5 is this pack's first gate and is restated below.
- Authored 2026-10-18 (local) by the dispatcher seat `air` on the operator's word ("good, lets
  make task packs for fixing these issues"), from the `/reflect` of the same evening.
- Ledger: no row filed at authoring. The defects are in a deployed tool (a job that only a hand
  can close; a board whose sections carry no count; a read that passes stale) and the lane
  files or strikes in-lane what its Task 0 shows needs its own oracle (protocol item 8).
- **One sentence inside this pack is the operator's:** the three rules for the dispatcher's
  brief (`tools/cc/seat.py::DISPATCHER_BRIEF`, whose duties the operator approved with
  `TP-701` B-7). The lane writes it on the operator's yes at its start; the brief is composed
  by the tool and pinned by substrings, not byte for byte (Task 0 item 4).

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

## Scope (in)

**Lane `lane/jobs-close-by-construction`:**

1. **W1 Jobs close by construction** (`tools/cc/mail.py`, `tools/cc/ship.py`). A claim carries the assign it works: `send --type claim
   --assign <assign id>` writes it under a key outside `tools/cc/mail.py::RE_KEYS` (the
   `ASSIGN_SEAT_KEY` precedent: written only when given, so an unflagged claim is byte-identical
   to today's). A release carries the ids its lane struck under a second key outside `RE_KEYS`.
   `live_assignments` closes a job on two new rules beside today's two: a release from the
   assigned seat naming a lane whose live claim by that seat carried the assign's id; and a
   release from the assigned seat whose struck ids cover every id of the assign. The ship
   driver's lane release carries both: the assign ids this seat's live claims on the lane
   carried, and the ids the lane itself struck, derived from its own diff against the base
   (`tools/cc/ship.py`, the release the driver sends after a push).
2. **W2 Section counts.** In `tools/cc/board.py`, every board header names its count: `open PRs: N`, `seats: N`,
   `jobs: N live`, `claims: N live`, `overlaps: N pairs`; `asks:` already does.
3. **W3 `--require-fresh`.** On `tools/cc/mail.py`'s `inbox`, `claims` and `assignments` and
   on `tools/cc/board.py`: when the fetch failed, exit non-zero and say so, instead of reading
   what is here. A gate passes the flag; a person does not.
4. **The brief's sentence.** In `tools/cc/seat.py`, `DISPATCHER_BRIEF` gains the three rules (every
   count names its population; every setting a tool computes is quoted from the tool; the day's
   figures come from the census, never carried by hand), on the operator's yes.

5. **The tests and the mirrors.** `tests/test_mail.py`, `tests/test_ship_driver.py`,
   `tests/test_board.py` and `tests/test_seat.py` gain the rows named under Implementation; the
   vendored byte-copy under `espalier/_vendor/cc/` is refreshed by `python3
   scripts/sync_vendor_cc.py` only, never by hand; `.claude/commands/inbox.md` and its two
   mirrors by `python3 scripts/sync_claude_mirrors.py` only.

**Lane `lane/the-dispatchers-instruments`:**

6. **W4 The census.** `scripts/seat_day_census.py` and `tests/test_seat_day_census.py` with its fixture under `tests/fixtures/seat_day/`: per seat per day, from the mail refs and
   `gh pr list`: lanes merged; assigns received, closed (by the seat's lane release, by the
   dispatcher's release, by a hand release), live at the window's end; requests sent and their
   ack latency (through `scripts/mail_latency_census.py`'s pairing); Session Log rows written;
   messages mentioning `START`. `--json`; `--fixture` on a frozen copy of the refs; `--row`
   prints a Session Log row body for one seat and day, which `TP-703d` consumes. Its test, its
   fixture (the refs as they stood on 2026-10-18, the fields the census reads and no prose), its
   roster line in `tests/_surface_expected.py`.

## Scope (out)

- **What an assign says and when a seat proceeds**: `TP-703e`.
- **Writing the Session Log row** from the census, and the dispatcher's day row: `TP-703d`,
  which reads `--row`; this pack prints the body and writes no fragment.
- **The box gate itself**: `TP-703c`. W3 gives any gate a fresh-or-nothing read; it does not
  build one.
- **Closing a job on the operator's word** (a job retired because the row was struck by another
  seat, or the pack scrapped): the dispatcher's release by hand stays the way, and the census
  counts it as a hand release, so the figure says how often it is still needed.
- **A redesign of the `assignments` verb or the job key** (`tools/cc/mail.py::_job_key`): the
  latest-assign-wins rule and the "a different id set is a new job" rule stand; the 2026-10-11
  nine-hour case that shaped them is not re-opened.
- **The mail cap** (`MAX_TEXT`) and **the assign's shape**: `TP-703e` and `TP-703g`.
- **Counting on the banner's lines** (`Mail:`, `Orders:`): the banner is read at session start
  only; the board is the live read, and the counts go there.

## Task 0 — Verify (try to kill this pack; per lane)

Each item names the oracle, the result that ends or narrows the pack, and the exit. The
default exit is stop and re-raise to the operator, never adjust and continue.

**Lane 1 (W1 to W3, the brief).**

1. *Oracle (the roadmap's item 5):* over the four mail refs, for each assign of a day, the
   first release after it from the dispatcher or the assigned seat that names its id or its
   lane, classified: the dispatcher's release naming the assign (a hand), the seat's lane
   release (the driver), none (live). *Refuting result:* the driver closes most. *Exit:* W1 is
   dropped; W2 to W4 land. (Read 2026-10-18, the 25 assigns of the day: 22 by hand, 1 by the
   driver, 2 live.)
2. *Oracle:* `grep -n -E 're_?\.get\("ids"\)|_str_list\(.*"ids"' tools/cc/mail.py
   tools/cc/board.py tools/cc/ship.py tools/cc/ledger_row.py tools/cc/execution_plan.py`, each
   hit read for whether it gives a RELEASE's `re.ids` a meaning. *Refuting result:* a reader
   already does. *Exit:* the struck ids go under the new key regardless (the pack picks it for
   that reason), and the reader's meaning is written into W1's docstring so the two do not
   collide. (Read 2026-10-18: `live_assignments` reads a release's `ack` and `re.lane` only; the
   id readers are on claims and assigns: `overlapping_claims`, `_job_key`, the board's claims
   line, the ledger verbs' claim read.)
3. *Oracle:* `grep -n -E 'set\(collected\)|<= set|== set\(' tests/test_board.py`. *Refuting
   result:* an exact pin of the board JSON's key set. *Exit:* extend the pin in the same lane
   before adding keys (`TP-701` A-0 item 4 asked the same). (Read 2026-10-18:
   `TestDerivedNotRestated` asserts a subset, `{"asks", "seats", "open_prs", "post_merge",
   "assignments", "claims"} <= set(collected)`, so new keys pass.)
4. *Oracle:* `grep -n -E 'DISPATCHER_BRIEF|Decisions stay|revert first on a red' tests/test_seat.py`.
   *Refuting result:* a byte-for-byte pin of the dispatcher's brief. *Exit:* the sentence
   becomes a proposal to the operator, as `TP-703e` 1-C-2 proposes the worker's. (Read
   2026-10-18: `TestBrief::test_the_dispatcher_seat_gets_the_board_loop_and_its_duties` pins the
   first sentence with `startswith`, the phrases `revert first on a red main` and `Decisions
   stay the operator's.`, and `model` absent; the rules sentence goes before the last phrase
   and keeps every pin.)
5. *Oracle:* the operator's yes on the brief's sentence, asked at the lane's start with the
   nineteen corrections' four kinds. *Refuting result:* no. *Exit:* W1 to W3 land; the
   sentence is recorded as declined in Landing and the rules live in the protocol only.

**Lane 2 (W4).**

6. *Oracle:* `scripts/mail_latency_census.py::read_fixture`'s shape against what the census
   needs: the latency fixture carries `{frozen_at, dispatcher, messages: {machine: [{id, type,
   from, at, ack}]}}` and no `re` block and no text (its `about` line says no message prose).
   *Refuting result:* none; a design reading. *Exit:* the census's fixture is its own shape, with
   `re` (lane, seat, ids, the claim's assign key, the release's struck key) and a boolean for the
   `START` match in place of the text, under `tests/fixtures/seat_day/`, and reuses
   `read_refs` and `pair` from the latency census for the live read and the latency figure.
7. *Oracle:* the six tree-wide gates `TP-702`'s Landing records red on a new `scripts/` file
   (its docstring naming its pack, the provenance tests; a spawn argv built from parameters, the
   subprocess contract; a script loaded inside a fixture, the derived-population census; a test
   docstring with no rationale anchor; the scripts roster; a forward-ledger row), each grepped
   for its current form before the script is written. *Refuting result:* none; a reading that
   shapes W4. *Exit:* the script names no pack id in its docstring, spawns `gh` with a literal
   argv, joins `scripts/derived_population_census.py::ADJUDICATED` only if a fixture loads it,
   its test docstrings carry their rationale, its roster line is in `tests/_surface_expected.py`,
   and the roadmap's §3 row names this pack.

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

### W1 Jobs close by construction *(fix shape, untested)*

**W1-A The two keys and the closing rule.** In `tools/cc/mail.py`, beside `ASSIGN_SEAT_KEY`
and the assignments fold:

```python target=tools/cc/mail.py
#: A claim's optional ``re`` key naming the assign (its id) the lane works, so the
#: lane's release closes that job (``live_assignments``); written only when given,
#: outside RE_KEYS, as ASSIGN_SEAT_KEY is. A release's optional ``re`` key listing the
#: ledger row ids the lane struck at its head, derived by the ship driver from the
#: lane's own diff; a job whose every id is in it closes.
CLAIM_ASSIGN_KEY = "assign"
STRUCK_KEY = "struck"


def release_closes(release: dict, assign: dict, carried: set[str]) -> bool:
    """Whether ``release``, already known to come from the assign's seat or
    its assigner, closes ``assign``: its ``ack`` names the assign; or, with
    no ``ack``, its lane is the assign's lane, or a lane a live claim of that
    seat carried the assign's id on (``carried``, those lanes), or its struck
    ids cover every id the assign names. A release carrying nothing of the
    kind closes nothing, as before."""
    re_ = release.get("re") or {}
    a_re = assign.get("re") or {}
    ack = release.get("ack") or ""
    if ack:
        return assign.get("id") == ack
    lane = str(re_.get("lane") or "")
    if lane and (a_re.get("lane") == lane or lane in carried):
        return True
    a_ids = set(_str_list(a_re.get("ids")))
    return bool(a_ids) and a_ids <= set(_str_list(re_.get(STRUCK_KEY)))
```

`new_message` gains two keyword parameters, `assign: str | None = None` (a claim only; an
`Unresolvable` on any other type, as `seat` is for a non-assign) and `struck: Sequence[str] =
()` (a release only; each an id `_ROW_ID_RE` accepts), and writes `re_[CLAIM_ASSIGN_KEY]` and
`re_[STRUCK_KEY]` only when given, after `ASSIGN_SEAT_KEY`. `build_parser`'s `send` gains
`--assign <assign id>`; `--struck` is not a flag (the driver derives it; a hand that wants a
job closed sends `--ack <assign id>`, as today). `tests/test_mail.py`'s two key-set pins (an
unflagged message's `re` is exactly `RE_KEYS`; a flagged one's first four keys are `RE_KEYS`)
stand.

**W1-B The fold.** `live_assignments` reads the claims too: in the same ordered pass over
assigns, releases and now claims (the stamp, the machine, the position in its file, as the fold
orders everything), a claim whose `re` carries `CLAIM_ASSIGN_KEY` adds its lane to a map
`{(claimer, assign id): {lanes}}`; a claim after the release does not count. Where the fold
today tests `(ack and a.get("id") == ack) or (not ack and lane and a_re.get("lane") == lane)`
after its `who` check, it calls `release_closes(m, a, carried.get((who, str(a.get("id"))),
set()))` instead, the `who` check kept in front of it. The docstring says the four rules in
words.

*Refutations and the mutations the tests die to:* a lane release from a seat other than the
assigned one, naming the carried lane, closes nothing (mutation: drop the `who` check); a
release whose struck set lacks one of the assign's ids closes nothing (mutation: `&` for `<=`);
a claim on lane B carrying assign A's id, then a lane release of B by the same seat, closes A
even though A named ids only (the rule this wave exists for); a release carrying a struck id for
a row the lane did not strike (the guard case below) closes nothing because the driver never
wrote it, and the test seeds it to show the fold trusts the key, so the derivation is what is
guarded, in W1-C.

**W1-C The driver derives, never lists.** In `tools/cc/ship.py`, a new helper beside
`_release_claims`:

```python target=tools/cc/ship.py
def _struck_at_head(root: Path, base: str) -> list[str]:
    """The ledger row ids this lane struck: live in the base's view of the row
    files the lane changed and not live in HEAD's, read from the lane's OWN
    diff against origin/<base> and never from the ledger at large (a row
    another lane struck, or one a later lane re-pins open, is not this lane's
    to close). The views are built by the record-fragments loader; a tree
    without it, or a diff git cannot give, is an empty list and a note."""
```

Its body: `git diff --name-only origin/<base>...HEAD -- task-packs/ledger.d/` for the files,
each read at both sides (`git show origin/<base>:<file>`, the working tree at HEAD), the two
texts folded through `_fragments_module().ledger_view_from_texts` into the ledger view and the
live ids taken by `generate_ledger_regions.live_member_ids` (loaded by path as
`_fragments_module` loads its sibling); base minus head is the struck set. `_release_claims`
gains `struck` and `assigns` parameters and passes them to `release_lane`, which gains the same
and hands them to `new_message`; `open_pr` and `handoff` call `_struck_at_head` once each, after
the push lands, and read the assign ids off this seat's live claims on the lane
(`own_live_claims`, each claim's `CLAIM_ASSIGN_KEY`). A failure anywhere in the derivation is a
note and a release without the keys, never a failed push (the `_release_claims` contract).

*The guard case (§16's user is the dispatcher who re-assigned):* `DEF-985` was named closed by
a census that did not close it (the dispatcher's own re-aim, 2026-10-18), then re-pinned open
in #319. Under W1-C a lane that struck nothing writes no struck ids, whatever the ledger holds
elsewhere; a lane that struck a row and a later lane that re-pins it open are two jobs, and the
second is the dispatcher's to assign. *Mutation the test dies to:* `_struck_at_head` reading
`live_member_ids` over the whole ledger at base and head (every row any lane struck since the
base would then close jobs on this release); the test seeds a struck row outside the lane's
diff and asserts the release carries only the lane's own.

**Checkpoint:** `tests/test_mail.py::TestAssignments` and `::TestReleaseLane`,
`tests/test_ship_driver.py::TestAShippedLaneReleasesItsClaims`, at one worker.

### W2 Section counts *(fix shape, untested)*

In `tools/cc/board.py::render`: `open PRs: N` on the first pull-request line (the `none` and
`unread` forms unchanged); `seats: N` before the first seat row, counting the rows printed plus
the folded quiet ones; `jobs: N live` after the dispatcher parenthesis, `claims: N live` on the
first claim row; `overlap_lines` prints `overlaps: N pairs` before the first pair (the `none`,
`none among what was read` and `unread` forms unchanged). Each count is `len()` of the list the
section renders, computed in `render`, never stored on the board dict, so `--json` carries the
lists and the text carries their lengths and the two cannot disagree (`TestDerivedNotRestated`'s
rule). *Mutation the tests die to:* a count read from a stored field (`board["jobs_count"]`)
that a stale JSON leaves behind; a count that excludes the folded quiet seats.

### W3 `--require-fresh` *(fix shape, untested)*

`tools/cc/mail.py::build_parser`: the flag on `inbox`, `claims` and `assignments`, exclusive
with `--no-fetch`; in `main`, where a failed fetch prints `note: could not fetch ... reading
what is here`, the flag turns the note into an `Unresolvable` naming the problem and the flag,
so the exit is the driver's refusal code and nothing is read. `tools/cc/board.py`: the same
flag on its parser; `collect` already records `mail_note` and `base_fetch`, and with the flag
`main` prints the two lines and exits 2 before rendering. The protocol's *How assignments
behave* gains one sentence: a gate reads with `--require-fresh`, a person without it.
*Refutation:* a gate that must run offline (none today; the win box gate fetched). *Mutation the
tests die to:* the flag accepted and the stale read still rendered (exit 0).

### The brief's sentence *(prose; on the operator's yes)*

In `tools/cc/seat.py::DISPATCHER_BRIEF`, before `Decisions stay the operator's.`: `Every count
you state names its population, every setting a tool computes is quoted from the tool, and the
day's figures come from scripts/seat_day_census.py, never carried by hand.` 7-bit ASCII, no
double quote, no `%`. The pins in `tests/test_seat.py::TestBrief` stay true; a new assertion
pins the sentence in the self-host form. The same three rules go into the protocol's dispatcher
table as one row, whichever way the operator rules on the brief.

**Checkpoint (lane 1):** `python3 scripts/proof_tier.py --base origin/main` and the tier its
line prints; `python3 scripts/sync_vendor_cc.py` and `python3 scripts/sync_claude_mirrors.py`
clean (`.claude/commands/inbox.md` gains the `--assign` flag and the `--require-fresh` flag in
Steps 1 to 3).

### W4 The census *(fix shape, untested; the figures above are its first measured run, by hand)*

`scripts/seat_day_census.py`, modelled on `scripts/mail_latency_census.py` (`--repo`,
`--fixture`, `--no-fetch`, `--since`, `--until`, `--json`; its `read_refs` and `pair` reused
by loading the sibling by path, as that script's `_load` loads `tools/cc/mail.py`). Per seat
per UTC day in the window, one row: lanes merged (`gh pr list --state merged --limit 200 --json
number,headRefName,mergedAt`, a literal argv, lanes to seats by `tools/cc/mail.py::lane_seats`
over the refs); assigns received; jobs closed by the seat's lane release, by the dispatcher's
release naming the assign, by any other release (a hand); jobs live at the window's end
(`live_assignments` over the messages up to `--until`); requests sent and the median ack latency
(`pair`); Session Log rows (`memory/session-log.d/` names through
`tools/cc/_record_fragments.py::SESSION_LOG_NAME_RE`, the date and seat groups); messages
mentioning `START` as a word. `--row <seat> <date>` prints one Session Log row body in the
fragments' shape (`| YYYY-MM-DD | **<seat>: ...** | ... |`, as the rows under
`memory/session-log.d/` are written) with the day's figures and nothing a hand typed; it writes
no file. The fixture, `tests/fixtures/seat_day/refs-2026-10-18.json`: every message of the four
refs as they stood at the freeze, the fields the census reads (`id`, `type`, `from`, `at`,
`ack`, `re`'s lane, seat, ids and the two new keys) and a boolean `start` for the word match,
no prose; and the merged pull requests of 10-16 to 10-18 as `gh` listed them. The test drives
the fixture to the figures in Motivation (25 assigns on 10-18, 22 closed by hand, 1 by the
driver, 2 live; 24 ids-only) and dies to a pairing that counts a release from the wrong seat.

*Refutation:* `pair`'s signature or `read_refs`'s return shape changes under this lane's feet
(both are `scripts/` and self-host; the test pins the import); then the census carries its own
copy and says so.

**Checkpoint (lane 2):** `tests/test_seat_day_census.py` at one worker; the roster line;
`python3 scripts/proof_tier.py --base origin/main` (the roster line in
`tests/_surface_expected.py` is suite config and earns the full tier, as `TP-702`'s Landing
measured).

### Pre-registered (TP-703's re-measure, lines 6 and 7)

Over the next 25 jobs after lane 1 merges: releases sent by the dispatcher's hand to close a
job, from 22 of 25 to at most 2; read by the census, never by the notes. Over the ten days after
the brief's sentence lands: dispatcher statements corrected by a worker of the three later kinds
(a narrower measurement, a restated setting, a hand-carried figure), at most 2 a day, read from
the workers' corrections on the refs. And on every board read, `jobs: N live` equals the length
of `python3 tools/cc/mail.py assignments --json` at the same fetch, which a test pins.

## Affected symbols

`/scope-check` keys on bare names, so four changed symbols are not declared below and are named
here instead: the command-line entry points of the mail driver and the board (each a `main`; the
mail driver's gains `--assign` and `--require-fresh`, the board's `--require-fresh`), the two
parsers (`build_parser`, one per CLI), the board's `render` (a count on every header; the word is
everywhere) and the ship driver's `handoff` verb (the same derivation as `open_pr`, after the push
onto an open pull request; the word is in every command body). Declared at authoring they put
forty files in the gap list. Re-run the check at each lane's start rather than trusting this list.

### Changed-semantics
- `tools/cc/mail.py::new_message` (two optional keyword parameters, two optional `re` keys)
- `tools/cc/mail.py::live_assignments` (two closing rules added; reads the claims)
- `tools/cc/mail.py::release_lane` (carries the struck ids and the assign ids)
- `tools/cc/ship.py::_release_claims` (passes what the lane struck and carried)
- `tools/cc/ship.py::open_pr` (derives the struck ids after the push)
- `tools/cc/board.py::overlap_lines` (`N pairs` on the first line)
- `tools/cc/seat.py::DISPATCHER_BRIEF` (the three rules, on the operator's yes)

### Renamed
- None.

### Added-paths
- `tools/cc/mail.py::CLAIM_ASSIGN_KEY`
- `tools/cc/mail.py::STRUCK_KEY`
- `tools/cc/mail.py::release_closes`
- `tools/cc/ship.py::_struck_at_head`
- `scripts/seat_day_census.py`
- `tests/test_seat_day_census.py`
- `tests/fixtures/seat_day/`

### Removed-paths
- None.

## Reach

Not a class pack: it closes no ledger class and mints no row at authoring. `DEF-985`'s re-pin
(#319, after the dispatcher named it closed) is the guard case W1-C's test seeds, not a member;
the rows a lane strikes are closed by that lane, and this pack only lets the release say so.

## Pass criteria

- `python3 tools/cc/mail.py send --type claim --lane lane/x --path a.py --assign <id>
  --dry-run` prints a `re` whose first four keys are `RE_KEYS` and whose fifth is `assign`; a
  claim without the flag prints exactly `RE_KEYS`; `--assign` on a non-claim is refused by name.
  No `tests/test_mail.py` assertion is weakened and no fixture removed.
- On a fixture of two seats, an assign naming ids only, a claim carrying its id on `lane/y`,
  and a lane release of `lane/y` by the assigned seat: `live_assignments` is empty; the same
  release from the other seat leaves the job live; a release whose struck set covers the ids
  closes it and one short by an id does not.
- `_struck_at_head` on a scratch lane that strikes one row file and leaves a second struck row
  file in the base untouched returns the one id; a tree without the fragments loader returns
  `[]` with a note and the push's release still goes out.
- `python3 tools/cc/board.py --no-fetch` on this repository prints `jobs: N live`, `claims: N
  live`, `open PRs: N` and `overlaps: N pairs` where each `N` equals the length of the matching
  `--json` list; `asks:` keeps its count.
- `python3 tools/cc/mail.py claims --require-fresh` with the remote unreachable (a fixture
  remote path that does not exist) exits non-zero and names the flag and the problem;
  `python3 tools/cc/board.py --require-fresh` the same, before any section renders.
- `python3 scripts/seat_day_census.py --fixture tests/fixtures/seat_day/refs-2026-10-18.json
  --since 2026-10-18 --until 2026-10-19 --json` reproduces the figures in Motivation for `air`
  and the three worker seats; `--row air 2026-10-18` prints one row in the fragments' shape and
  writes nothing.
- Earn-the-red recorded per fix against the mutations named in W1 to W3 and W4; a test that
  only ever passed does not count.
- The syncs report clean; the tier each lane's `scripts/proof_tier.py --base origin/main` line
  prints is the one run, its receipt in the pull request body.
- No criterion here licenses shipping a defect in the fold this pack delivers: a release that
  closes a job whose ids the lane did not strike, or a count that can disagree with its list, is
  a defect of this pack, never a scope-out.

## Files touched

**New:** `scripts/seat_day_census.py`; `tests/test_seat_day_census.py`;
`tests/fixtures/seat_day/refs-2026-10-18.json`.

**Modified:** `tools/cc/mail.py`; `tools/cc/ship.py`; `tools/cc/board.py`; `tools/cc/seat.py`;
`tests/test_mail.py`; `tests/test_ship_driver.py`; `tests/test_board.py`; `tests/test_seat.py`;
`tests/_surface_expected.py` (the roster line); `memory/parallel-work-protocol.md` (one
sentence under *How assignments behave*, one row in the dispatcher table);
`.claude/commands/inbox.md` and its two mirrors (by `sync_claude_mirrors.py` only);
`espalier/_vendor/cc/` (by `sync_vendor_cc.py` only).

**Deleted:** none.

**Unmodified on purpose:** `tools/cc/mail.py::_job_key` and `::MAX_TEXT` (Scope out);
`tools/cc/seat.py::WORKER_TICK` (the operator's paste); `scripts/mail_latency_census.py`
(reused, not changed; its fixture untouched); `tools/cc/hooks/*` (no hook change, so no
`docs/HOOKS.md` edit and no marker in the title).

## Sub-task ordering

1. **Lane 2 first, or beside lane 1 on another seat:** Task 0 items 6 and 7, then W4.
   Checkpoint: the fixture reproduces Motivation's figures; the roster; the tier.
2. **Lane 1:** Task 0 items 1 to 5 (item 5 is the operator's yes, asked with the four kinds).
   Checkpoint: the results in Landing; item 1's refuting result drops W1.
3. **W1-A, W1-B, then W1-C** (smallest first: the keys, then the fold, then the derivation in
   the driver). Checkpoint per step: the touched test file at one worker.
4. **W2**, then **W3**, then the brief's sentence. Checkpoint: the board on this repository, the
   flag against a dead remote.
5. **Red-team**, both reviewers on a snapshot clone as the tier line names, one fix batch. What
   this pack most likely got wrong, for the pass to bite on: the fold's ordering of a claim that
   carries an assign id against the release that closes it when the two come from different
   refs with equal stamps; `_struck_at_head` on a lane that merged `main` in (the three-dot diff
   must not read `main`'s own strikes as the lane's); a count on `seats:` that disagrees with
   the folded line's `and N more`.
6. **The tier** each lane earns, `--base origin/main`; the syncs; `/handoff` with the row.

## Estimated effort

Pack budgets on this repository have run about 2.7 times over on one measured pack (`TP-459`);
read these as the author's guess, not a schedule.

| Wave | Build | Red-team and tier | Notes |
|---|---|---|---|
| Task 0 (both lanes) | 1 h | the second reader on item 1 | reads of the refs and the tests |
| W1 | 3 to 4 h | 1 h | two keys, two rules, one derivation, three callers |
| W2, W3 | 1.5 h | 0.5 h | counts and a flag on two tools |
| The brief | 0.5 h | the pins | one sentence, one assertion |
| W4 | 3 to 4 h | 0.5 h plus the full tier | a script, a fixture, a test, the roster |
| Total | 9 to 11 h | 2 h plus two tiers | expect the measured overrun |

## Landing
- State: DRAFT
- Commits:
- Suite: `python3 scripts/proof_tier.py --run --base origin/main` on each lane
- Earn-the-red: per fix, against the mutations named in W1 to W4
- Red-team: per the tier's `review:` line; authoring review not yet run
- Reach: not a class pack; no row closed; `DEF-985`'s re-pin is the guard case
- Task 0: not yet run (item 5 is the operator's yes on the brief's sentence)
- Date: 2026-10-18 (authored, local)
