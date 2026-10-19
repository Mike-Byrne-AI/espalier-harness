# TP-703e — The assign shrinks and the seat proceeds: the dispatcher sends what only it knows, and a fork no longer stops a seat

## Status

- Version target: adopter-facing where it touches `tools/cc/mail.py` and `tools/cc/seat.py`
  (both deploy through `espalier init` via the vendored byte-copy, `espalier/_vendor/cc/`);
  self-host where it touches `memory/parallel-work-protocol.md` and `tests/`.
- Type: process (the assign's shape and the seat's authority, written into the protocol) plus
  one soft check in the mail driver and one clause in the dispatcher's brief.
- **Kind: PACK.** One lane, `lane/the-assign-shrinks`. Its Task 0 can end it.
- Parent: `TP-703` (`task-packs/TP-703-multi-seat-discipline.md`), Wave 1, item 3; the
  roadmap's Task 0 item 3 is this pack's first gate and is restated below.
- Authored 2026-10-18 (local) by the dispatcher seat `air` on the operator's word ("good, lets
  make task packs for fixing these issues"), from the `/reflect` of the same evening.
- Ledger: no row. The cost is process (a seat waiting, a dispatcher trimming), not a defect in
  shipped code; the measurement is in Motivation.
- **Two decisions inside this pack are the operator's, not the lane's:** the change to the
  protocol's *Assign authority* paragraph (decided by the operator on 2026-10-15; 1-C amends
  it), and the sentence for the worker tick (`tools/cc/seat.py::WORKER_TICK`, the operator's
  paste, pinned verbatim by `tests/test_seat.py::_OPERATOR_TICK`). The lane writes the first on
  the operator's yes at its start and proposes the second; it edits neither without the word.

## Motivation

**What the assign carries today.** Read 2026-10-18 (local evening) over the four mail refs
(`refs/remotes/origin/mail/*` and this clone's `refs/heads/mail/air`, the same message counted
once by its id), every `assign` from `air`:

| Population | Count | Text length, median | At or over 1,950 of the 2,000 cap | Under 900 | Naming a tier or reviewer word |
|---|---|---|---|---|---|
| assigns on 2026-10-18 | 25 | 1,957 | 17 | 0 | 24 |
| every assign on the ref | 125 | 1,685 | 32 | (not read) | 115 |

The word list matched, case-insensitive: `contract slice`, `contract tier`, `recall tier`,
`full tier`, `code-reviewer`, `failure-mode`, `both reviewers`, `the tier`, ` tier `. Nearly
every assign reached the cap after two to four trim rounds (the dispatcher's tick notes; the
rounds are unmeasured beyond the notes). What the dispatcher was trimming to fit: the tier the
lane earns and the reviewers it must run, both of which `scripts/proof_tier.py --base origin/main`
prints from the diff (`scripts/proof_tier.py::tier` and `::review`; the protocol's item 9 says
so), and a prescribed fix shape.

**What the assign got wrong.** Hand-classified by the dispatcher from its own acks and the
seats' Task 0 notes, 2026-10-17 to 10-18 (tag: hand-classified, re-read by a second reader at
Task 0): of 18 assigns sent 06:00 to 19:04Z on 10-18, 10 were re-aimed by the seat's Task 0 or
a review, and 7 of the 10 corrections were findable by reading the row, the pack or the tree
first; the stated tier or review set was wrong 3 times in 25; 19 of 20 rulings the dispatcher
gave at a seat's fork matched the recommendation the seat sent with the request; 0 assigns were
vetoed by the operator under the assign authority.

**What the stop costs.** The worker tick says, on a choice the assign does not settle or a red
the seat cannot fix in two attempts, "STOP and send air one request, then only re-read mail
until it is answered" (`tools/cc/seat.py::WORKER_TICK`). Request-to-ack ran a median of 6 to 9
minutes since 10-14 (`python3 scripts/mail_latency_census.py --since 2026-10-14`), and the seat
then reads the ack and resumes, so each fork costs the seat the latency plus a read: the
dispatcher's notes put it at 10 to 30 minutes a fork (unmeasured beyond the notes). With 19 of
20 rulings going the seat's way, the stop bought one changed outcome in twenty. And a seat
stopped on a red it cannot fix stays stopped: the tick has no "shelve this lane and take the
next" arm, so a queue of two jobs behind a stuck lane is a queue of none.

**The named user (§16).** A seat that sat ten to thirty minutes at a fork whose answer it had
already written into its request; and the dispatcher, who spent its tick trimming a tier line a
tool prints, and whose 2,000 characters then had no room for the one thing only it knew (which
other lane this one must wait for, and why now).

## Scope (in)

1. **1-A The assign's shape**, written into `memory/parallel-work-protocol.md` (the *How
   assignments behave* list and the dispatcher table): the row id or lane; why now; sequencing
   against other seats' lanes, by lane name; the operator's constraints; any edge the dispatcher
   read, with its citation. Nothing the row or `scripts/proof_tier.py` already says: no tier, no
   reviewer set, no restated row text. A prescribed fix shape only with the citation the
   dispatcher read to arrive at it. Under 900 characters, pre-registered from the figures above
   (every assign of 10-18 was over it; the shape above fits in a third of the cap).
2. **1-B A soft shape check** in `tools/cc/mail.py`: a note on stderr, never a refusal, when an
   assign's text is over the shape cap or names a tier or reviewer word; the note names the
   phrase. On `--dry-run` too. `MAX_TEXT` stays 2,000.
3. **1-C The seat's authority** in the protocol's *Assign authority* paragraph, item 1 and the
   dispatcher table: on a fork the assign does not settle, the seat sends its request with its
   Task 0 recommendation and the citation behind it, and proceeds on that recommendation after
   one tick (ten minutes) with no answer; it stops only for an operator-class item (a new row, a
   scope change, a platform safety stop, a revert that is not the red-`main` revert); a red it
   cannot fix in two attempts shelves the lane (claims kept, one note sent) and the seat takes its
   next queued job. Item 1's "two or three queued" and the table's "at least one job" are
   reconciled to two. The tick's sentence is proposed (1-C-2), never edited.
4. **1-D The dispatcher's brief**: in `tools/cc/seat.py`, `SELF_HOST_ASSIGN` gains the shape clause,
   so a dispatcher launched by `seat.py launch` reads the shape in its first message.
5. **1-E The words**: `.claude/commands/inbox.md`'s assign paragraph (Step 2b) and
   `docs/WORKFLOW.md`'s *Parallel seats* section, one sentence each; their mirrors, and the
   vendored byte-copy under `espalier/_vendor/cc/`, by the sync scripts only.

## Scope (out)

- **The mail cap itself** (`tools/cc/mail.py::MAX_TEXT`). It stays 2,000; the reason it is
  2,000 is `TP-703g`'s to write where `/inbox` says "the same 2,000" with no reason. A larger
  cap would carry more prescription, which is the opposite of this pack.
- **A refusal on shape.** An assign that must name a tier (the operator asked for a tier
  override on one lane) would be blocked; a note names the phrase and lets the dispatcher decide.
  If Task 0 item 3 finds overrides are common, the word list shrinks to the reviewer words.
- **Editing the worker tick.** `tools/cc/seat.py::WORKER_TICK` is the operator's paste
  (`tests/test_seat.py::_OPERATOR_TICK`); 1-C-2 proposes its sentence with the guard `TP-702`
  3-A used, and a loop already running keeps its text until the operator restarts it.
- **The dispatcher's instruments** (section counts, the day census, `--require-fresh`):
  `TP-703f`. **The record of assigns** (a blueprint justification per assign): `TP-703d`.
- **A deeper queue by mechanism** (the dispatcher auto-assigning the next row of a class). Item
  1 says two queued; keeping two is the dispatcher's duty, not a tool's, until the re-measure
  says the duty is missed.
- **`--text-file`** and the assign's transport: unchanged.

## Task 0 — Verify (try to kill this pack)

Each item names the oracle, the result that ends or narrows the pack, and the exit. The default
exit is stop and re-raise to the operator, never adjust and continue.

1. *Oracle (the roadmap's item 3):* the ten re-aimed assigns of 2026-10-18 06:00 to 19:04Z
   (the dispatcher's ref, `git show refs/heads/mail/air:mail.jsonl`, type `assign`; the seats'
   Task 0 notes and review notes on the other refs that answer them), each read by a second
   reader against the row, the pack and the tree as they stood at the assign's stamp, and
   classified findable or not. *Refuting result:* fewer than half findable. *Exit:* the
   assign's content is not the cause of the re-aims, the shape rule is wrong, and 1-A and 1-B are
   dropped; re-raise with the classification. (Run at authoring, 2026-10-18, by a second reader in
   its own context over all 18 assigns: 14 re-aimed, 3 of them review-only on the one restated
   `bench/` rule; 12 of 14 findable, 1 partial, 1 not, 1 undecided; the dispatcher's own count had
   been 10 and 7. Not refuted: build. The reader's caveat stands in the roadmap's Landing: findable
   means a sentence stated it, not that a pre-send read would have reached it.)
2. *Oracle:* the word match above re-run over the assigns of the last three days by a reader
   that is not the dispatcher (a one-line script over the refs; the fixture `TP-703f` W4 freezes
   serves too). *Refuting result:* under a third of them name a tier or reviewer word. *Exit:*
   1-B buys little; 1-A alone lands. (Read 2026-10-18: 24 of 25 on the day, 115 of 125 on the
   ref.)
3. *Oracle:* `grep -n -i -E 'tier' ` over the dispatcher's assigns, each hit read for whether the
   tier named differs from what `scripts/proof_tier.py --base origin/main` would print for that
   lane's diff and was named on purpose (an operator's override). *Refuting result:* three or
   more deliberate overrides in the 125. *Exit:* the word list drops the tier words and keeps
   the reviewer words; the shape cap stays.
4. *Oracle:* `grep -n -E 'SELF_HOST_ASSIGN|on your own|Assign authority paragraph'
   tests/test_seat.py`. *Refuting result:* a byte-for-byte pin of the dispatcher's brief, as
   `_OPERATOR_TICK` pins the worker's. *Exit:* the brief is then the operator's paste too, and
   1-D becomes a proposal like 1-C-2. (Read 2026-10-18: substrings only, in
   `TestBrief::test_this_repositorys_dispatcher_assigns_and_an_adopters_proposes`, which 1-D
   keeps true.)
5. *Oracle:* the operator's yes on 1-C's change to the *Assign authority* paragraph, asked at
   the lane's start with the figures above. *Refuting result:* no. *Exit:* 1-C lands the queue
   depth (item 1 and the table) and the shelve arm only; the proceed-after-one-tick clause is
   recorded as declined in Landing, and the stop stays.

## Relevant memory

Recent pattern, measured: the two re-aims the dispatcher's notes record as costing most
(`DEF-985` named as closed by a census it did not close; the pool read as empty from a snapshot)
were both statements the dispatcher made from memory where a read was available. An assign that
restates what a tool prints inherits that failure mode by construction.

| Entry | Where |
|---|---|
| Parallel work protocol | `memory/parallel-work-protocol.md` |
| Sister-site compression | `memory/sister-site-compression.md` |
| Convergence Is a Property of the Angle Set, Not the Implementation | `docs/SHARP_EDGES.md` (section of that title) |
| 1. Make it prove it | `docs/STANDING_PRINCIPLES.md` |
| 14. Derive the list, don't test a hand-written copy of it | `docs/STANDING_PRINCIPLES.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "the dispatcher's assign
prescribes the tier and the review the tool computes; the seat stops at every fork"`; re-run it
rather than trusting this list if the pack has been sitting. The protocol was its first line;
the sister-site and convergence entries are lexical neighbours, kept because the assign's
restated tier is a copy of a derived value, which is the sister-site note's subject.

## Implementation

Every fix below is a **fix shape (untested)** unless marked measured; its refutation is named.

### 1-A The assign's shape *(prose; the protocol)*

In `memory/parallel-work-protocol.md`, the *How assignments behave* list gains one entry and
the dispatcher table's first row gains a clause. The entry, as prose to land:

> **What an assign says.** The job (a row id, a class, or a lane for a pack's wave); why now;
> what it waits for, by the other seat's lane name and the file both touch; the operator's
> constraints on it; and any edge the dispatcher read, with the citation it read. Nothing the
> row or the tier script already says: `scripts/proof_tier.py --base origin/main` prints the
> tier and the reviewers from the diff, and an assign that restates them has been wrong 3 times
> in 25. A fix shape only with the citation behind it. Under 900 characters: every assign of
> 2026-10-18 ran past that, and what filled the rest was the tool's output retyped.

*Refutation:* an assign class that needs more than 900 characters on its own terms (a wave
split across two seats with three gates each). Then the cap moves, in this file, with the
measurement.

### 1-B The soft shape check *(fix shape, untested)*

```python target=tools/cc/mail.py
#: The assign's shape (memory/parallel-work-protocol.md, "What an assign says"): a note,
#: never a refusal, past this many characters or on a phrase the tier script prints.
ASSIGN_SHAPE_CHARS = 900
ASSIGN_SHAPE_WORDS: tuple[str, ...] = (
    "contract slice", "contract tier", "recall tier", "full tier",
    "code-reviewer", "failure-mode-reviewer", "both reviewers",
)


def assign_shape_notes(text: str) -> list[str]:
    """What an assign's text carries that the shape says it should not: its
    length past ASSIGN_SHAPE_CHARS, and each phrase of ASSIGN_SHAPE_WORDS it
    names (case-insensitive), since the tier script prints those from the
    diff. Notes, never a refusal: an operator's tier override is a reason to
    name one, and the dispatcher decides. 7-bit ASCII, one line each."""
    notes: list[str] = []
    if len(text) > ASSIGN_SHAPE_CHARS:
        notes.append(f"note: the assign is {len(text)} characters; the shape is under {ASSIGN_SHAPE_CHARS} "
                     "(the row id, why now, what it waits for, the operator's constraints, an edge with its citation)")
    low = text.lower()
    for phrase in ASSIGN_SHAPE_WORDS:
        if phrase in low:
            notes.append(f"note: the assign names '{phrase}', which scripts/proof_tier.py --base prints from the diff")
    return notes
```

In `tools/cc/mail.py::main`, the `send` arm, after `assign_refusal` and before the `--dry-run`
branch: `for line in (assign_shape_notes(text) if args.type == "assign" else []): print(line,
file=sys.stderr)`, so the notes print on a dry run and on a send alike. The word list is a
literal here, not read from `scripts/proof_tier.py::TIERS` and `::REVIEWS`: the mail driver
deploys to adopter trees and the tier script is self-host, and `tools/cc/` imports nothing
outside itself. A test pins the list against those two tuples on this tree so a renamed tier
reds here.

*Refutation:* Task 0 item 3 (deliberate overrides common): the tier words leave the list.
*Mutations the tests die to:* a text of 901 characters with no phrase yields one note and a text
of 899 yields none; a text naming `full tier` yields a note that names `full tier`; the check
raising instead of returning reds the never-refuses test; a `--dry-run` send prints the notes
beside the `body:` count.

### 1-C The seat's authority *(prose; the protocol; one sentence proposed)*

**1-C-1 The protocol.** The *Assign authority* paragraph gains, on the operator's yes (Task 0
item 5):

> **The seat's side of it.** On a fork the assign does not settle, the seat sends one request
> carrying its Task 0 recommendation and the citation behind it, and after one tick with no
> answer proceeds on that recommendation; the ack can still redirect it, and a redirect after
> the fact is recorded in the Session Log row as rework. The seat stops, and only re-reads mail,
> for an operator-class item: a new row, a change to an approved pack's scope, a platform safety
> stop, a revert that is not the red-`main` revert. A red the seat cannot fix in two attempts
> shelves the lane (its claims stay, one note says what was tried) and the seat takes its next
> queued job; the dispatcher re-sequences the shelved lane at its next tick. Measured before
> this clause: 19 of 20 rulings matched the recommendation the request carried (10-17 to
> 10-18, hand-classified), and the stop cost the seat the ack latency plus a read each time. What
> falsifies it: an override after the fact that forces rework, twice in twenty.

Item 1's "two or three queued" and the dispatcher table's "Keeps at least one job" become "two
queued" in both places, with the dispatcher's duty to keep them (the table row) and the seat's
to work them in order (item 1).

**1-C-2 The tick's sentence, proposed.** The sentence replacing the worker tick's STOP clause,
for the operator's paste after the lane merges, carrying its own guard as `TP-702` 3-A's did:
`On a choice the assign does not settle, send air one request with your Task 0 recommendation
and its citation, then proceed on it after one tick with no answer; a request with no
recommendation keeps the stop. STOP and only re-read mail for an operator-class item (a new
row, a scope change, a platform stop, a revert that is not the red-main revert). A red you
cannot fix in two attempts: shelve the lane (claims kept, one note), take your next assigned
job.` A seat on the older tick keeps stopping, which costs time and nothing else, so the
sentence needs no checkout to hold anything new before it is pasted.

*Refutation:* Task 0 item 5 (the operator declines the proceed clause): the shelve arm and the
queue depth land alone.

### 1-D The dispatcher's brief *(fix shape, untested)*

```python target=tools/cc/seat.py
SELF_HOST_ASSIGN = (
    "assign, re-sequence and release jobs within approved packs and live ledger rows on your own and "
    "report each at your next tick, each assign in its shape (the job, why now, what it waits for, the "
    "operator's constraints, an edge with its citation; never the tier or the reviewers, which the tier "
    "script prints; under 900 characters), propose the rest to the operator (a new pack, a scope change, a "
    "release or tag, a revert that is not the red-main revert, the open calls in cc/GOAL.md; the "
    "protocol's Assign authority paragraph)"
)
```

The pins in `tests/test_seat.py::TestBrief` (`"within approved packs and live ledger rows on
your own"`, `"Assign authority paragraph"`, `"send them on a yes" not in`) stay true; a new
assertion pins the shape clause in the self-host brief and its absence from
`ADOPTER_ASSIGN`. No double quote and no `%` in the template (the brief's own constraints,
pinned by the same class).

*Refutation:* Task 0 item 4 (a byte pin): 1-D becomes a proposal.

### 1-E The words *(prose)*

`.claude/commands/inbox.md`, Step 2b, after the assign command lines: one sentence giving the
shape and the note the driver prints; `python3 scripts/sync_claude_mirrors.py` for its two
mirrors. `docs/WORKFLOW.md`, *Parallel seats*, after "a dispatcher seat ... assigns the jobs":
one sentence that an assign names the job and the reasons, not the proof the seat's own tier
run prints; `python3 scripts/sync_asset_docs.py` for its asset twin. `python3
scripts/sync_vendor_cc.py` after the two `tools/cc/` edits.

**Checkpoint:** `python3 scripts/proof_tier.py --base origin/main` (any `tools/cc/` edit earns the
full tier, `scripts/proof_tier.py::is_runtime`'s full prefixes, and `mail.py` is loaded by the
SessionStart hook through `session_start.py::_load_mail`, so the line names both reviewers; the
receipt decides), the three syncs clean, the mirror parity tests green.

### Pre-registered (TP-703's re-measure, line 5)

Over the next 20 assigns after the lane merges: assigns a seat re-aimed whose correction was
findable by reading first, from 7 of 10 to at most 1 of 10; the assign's median length under
900 and none at the 1,950 mark, read by the same script as Motivation; tier or reviewer words in
0 of 20 except where an override is named as such; minutes a seat sat stopped per request
(request stamp to its first push after the ack, from the mail refs and the lane's reflog);
overrides after the fact that forced rework, at most 1 in 20. The dispatcher reads them at the
window's close and writes them into Landing.

## Affected symbols

`/scope-check` keys on bare names, so the mail driver's command-line entry point (its `main`,
whose `send` arm gains the shape notes) is not declared: `main` has thousands of references
across the tree. Re-run the check at the lane's start rather than trusting this list.

### Changed-semantics
- `tools/cc/seat.py::SELF_HOST_ASSIGN` (the shape clause)

### Renamed
- None.

### Added-paths
- `tools/cc/mail.py::ASSIGN_SHAPE_CHARS`
- `tools/cc/mail.py::ASSIGN_SHAPE_WORDS`
- `tools/cc/mail.py::assign_shape_notes`

### Removed-paths
- None.

## Reach

Not a class pack: it closes no ledger class and mints no row. It touches no live row's
mechanism; the rows it names (`DEF-985`, as the re-aim that cost most) are evidence, not
members.

## Pass criteria

- `python3 tools/cc/mail.py send --type assign --seat <s> --id DEF-1 --dry-run --text-file
  <901 characters naming "full tier">` prints two notes on stderr, naming the length and the
  phrase, and exits 0 with the line it would send; the same with 899 characters and no phrase
  prints none. No existing `tests/test_mail.py` assertion is weakened and no fixture removed.
- A test pins `ASSIGN_SHAPE_WORDS` against `scripts/proof_tier.py::TIERS` and `::REVIEWS` on
  this tree, so a renamed tier or reviewer reds the list.
- `python3 tools/cc/seat.py brief <dispatcher seat>` on this repository carries the shape clause;
  on an adopter tree (the `docs/WORKFLOW.md`-only fixture in `tests/test_seat.py::TestBrief`) it
  does not; `tests/test_seat.py::_OPERATOR_TICK` is byte-identical to before this lane.
- `memory/parallel-work-protocol.md` says "two queued" in item 1 and the table row, and carries
  *What an assign says*; the *Assign authority* paragraph carries *The seat's side of it* only
  where Landing records the operator's yes, and otherwise records the decline.
- Earn-the-red recorded per fix against the mutations named in 1-B and 1-D; a test that only
  ever passed does not count.
- The three syncs (`sync_vendor_cc.py`, `sync_claude_mirrors.py`, `sync_asset_docs.py`) report
  clean; the tier `scripts/proof_tier.py --base origin/main` prints is the one run, its receipt
  in the pull request body.
- No criterion here licenses a check that refuses: `assign_shape_notes` returning anything but
  a list of notes, or `main` raising on one, is a defect of this pack.

## Files touched

**New:** none.

**Modified:** `tools/cc/mail.py`; `tools/cc/seat.py`; `tests/test_mail.py`;
`tests/test_seat.py`; `memory/parallel-work-protocol.md`; `.claude/commands/inbox.md` and its
two mirrors (by `sync_claude_mirrors.py` only); `docs/WORKFLOW.md` and its asset twin (by
`sync_asset_docs.py` only); `espalier/_vendor/cc/mail.py` and `espalier/_vendor/cc/seat.py`
(by `sync_vendor_cc.py` only).

**Deleted:** none.

**Unmodified on purpose:** `tools/cc/seat.py::WORKER_TICK` (the operator's paste; 1-C-2
proposes); `tools/cc/mail.py::MAX_TEXT` (Scope out); `scripts/proof_tier.py` (the source of
the words, pinned, not changed); `tools/cc/board.py` (`TP-703f`).

## Sub-task ordering

1. **Task 0, items 1 to 5** (item 5 is the operator's yes, asked with the figures). Checkpoint:
   the results in Landing; a refuting result ends or narrows the pack as each item says.
2. **1-B** (smallest concrete change; surfaces the test fixtures), then **1-D**, then **1-A**
   and **1-C-1** (the words the code now points at), then **1-E**. Checkpoint per step: the
   touched test file at one worker.
3. **Red-team**, both reviewers on a snapshot clone if the tier line names them, one fix batch.
   What this pack most likely got wrong, for the pass to bite on: a phrase in the word list that
   an assign must legitimately carry (a lane whose job IS the tier script), and the proceed
   clause landing a change the operator would have vetoed during the ten minutes it did not
   read.
4. **The tier** the line prints, with `--base origin/main`; the syncs; `/handoff` with the row
   (this lane's row carries the day's assigns, as the authority paragraph asks).
5. **1-C-2** goes to the operator after the merge, with the guard sentence as written.

## Estimated effort

Pack budgets on this repository have run about 2.7 times over on one measured pack (`TP-459`);
read these as the author's guess, not a schedule.

| Step | Build | Red-team and tier | Notes |
|---|---|---|---|
| Task 0 | 1 h | the second reader's classification | items 1 to 3 are reads of the refs |
| 1-B, 1-D | 1 to 1.5 h | 0.5 h | one helper, two constants, one template clause, their tests |
| 1-A, 1-C-1, 1-E | 1 h | the mirror parity tests | prose in four files and three syncs |
| Total | 3 to 3.5 h | 1 h plus the tier | expect the measured overrun |

## Landing
- State: DRAFT
- Commits:
- Suite: `python3 scripts/proof_tier.py --run --base origin/main` on the lane
- Earn-the-red: per fix, against the mutations named in 1-B and 1-D
- Red-team: per the tier's `review:` line; authoring review not yet run
- Reach: not a class pack; no row closed
- Task 0: item 1 run at authoring by a second reader (14 of 18 re-aimed, 12 findable; not refuted); items 2 to 5 not yet run (item 5 is the operator's yes on the proceed clause)
- 1-C-2: the tick sentence not yet proposed
- Date: 2026-10-18 (authored, local)
