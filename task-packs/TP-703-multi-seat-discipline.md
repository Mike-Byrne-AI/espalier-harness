# TP-703 — Multi-seat discipline: the coordination layer's rules become mechanisms

## Status

- Version target: adopter-facing where the children touch `tools/cc/` (the board, the mail
  driver, the ship driver, the seat driver and the SessionStart hook all deploy through
  `espalier init` via the vendored byte-copy, `espalier/_vendor/cc/`); self-host where they
  touch `scripts/`, `memory/`, `tests/` and `.github/workflows/`.
- Type: workflow infrastructure plus process. The fourth rung of the anti-clobber system:
  `TP-479` laid out the records, the ids and the board; `TP-701` gave the board its seats and
  asks, the seats a launcher and the dispatcher two instruments; `TP-702` read overlaps at the
  function level. This rung carries the single-session harness's disciplines into the
  multi-seat layer, where five days of running it (2026-10-14 to 10-18) showed them held by
  prose, memory and mail instead of by a tool with a probe.
- **Kind: ROADMAP.** Ten lettered children, each `Kind: PACK` with its own Task 0 that can end
  it. This file's own Task 0 (below) can end a child before it is assigned. The roadmap carries
  the decisions, the wave map, the pre-registered re-measure and the scaling question; copy-ready
  Implementation and Pass criteria live in the children.
- Authored 2026-10-18 (local; 2026-10-19 UTC) by the dispatcher seat `air` on the operator's
  word: "good, lets make task packs for fixing these issues", after the operator's framing of the
  same evening: "The multi agent run was an experiment, and is a goal. It seemd to work better
  than it ever has before, so spending some time really addressing this is time well spent...
  bring espaliers disipline forward to the multi session aspects, and if more instances with
  less jobs works, or you find any improvements in the system, bring them up."
- Source: the `/reflect` of 2026-10-18 over the record of 10-14 to 10-18 (every message on the
  four mail refs, the merged pull requests, the post-merge and portability runs, the Session Log
  fragments, the dispatcher's tick notes), read by four reviewers in their own contexts
  (docs-against-practice, lessons, root cause, failure modes). The measurements file is local
  to the dispatcher's scratchpad (`reports/` is gitignored); every figure below names the
  command that re-derives it, and a figure with no command is tagged.
- Ledger: one §3 pack row names this pack and its ten children (the completeness contract,
  `tests/test_forward_ledger_completeness.py::test_every_active_pack_is_ledger_tracked`). No
  `DEF` row is filed at authoring: a finding's row, probe and fix are the assigned seat's one job
  (`memory/parallel-work-protocol.md` item 8), so each child files or strikes its own in-lane.
  Rows this roadmap reaches are under Reach.
- **Operator decisions this roadmap records as made** (2026-10-18, in the operator's words where
  one was given): the multi-seat run is "a goal", so the fixes are built, not the system retired;
  "bring espaliers disipline forward to the multi session aspects"; packs for the issues, now.
- **Operator decisions this roadmap asks for**, each a line under Scope (out) or in a child:
  `DEF-2025`'s counted per-platform skip and its row's re-open (`TP-703b`); `DEF-977`'s slim
  Windows leg on `main` (`TP-703b`); the worker tick's new sentence (`TP-703e`, the operator's
  paste); one seat per box or a third machine (Scope out); a fifth seat (the scaling line).

## Motivation

**One frame over six mechanisms.** The multi-seat layer was built with Espalier's mechanisms but not all of its
disciplines. (An organising frame laid over six mechanisms, not a measured single cause: the
reasoning review at authoring named it so, and what would refute it is a child whose Task 0 finds
its discipline was mechanical already, or a fix that lands and moves none of its re-measure line.) The refs, the compare-and-swap writes, the minted id blocks and the fold of
parked rows are mechanical, and they held: zero id collisions and zero reverts over the period,
every one of 148 requests answered (`python3 scripts/mail_latency_census.py --since 2026-10-14`),
request-to-ack median 6 to 9 minutes since 10-14. What broke was every place a discipline the
single-session harness enforces by code was carried into the multi-session world as a sentence:

| Discipline (single-session home) | Its multi-seat form on 2026-10-18 | What it cost, measured |
|---|---|---|
| One writer per shared state (Core Rule 14; `tools/cc/_json_safe.py::lock_file`) | the win box's one-tier-at-a-time rule, run over mail as `START` and `END` notes | 87 worker messages mentioning `START` on 10-18 (`python3 tools/cc/mail.py inbox --all --json`, text match), 3 crossed starts, 4 gate bugs, 15 holds for suites from the operator's other projects at a cost of at least 5 h of box time (the tick notes; unmeasured beyond them), which no mail protocol can see |
| Make it prove it; Task 0 (`STANDING_PRINCIPLES` §1; the blueprint-authoring skill) | assigns that prescribe a fix shape and restate the tier and reviewers the tool computes | 24 of 25 assigns on 10-18 stated a tier and 21 a review set, wrong 3 times; 14 of 18 assigns (06:00 to 19:04Z) re-aimed by the seat's Task 0 or its review (a second reader's count at authoring; the dispatcher's own was 10), 12 of them findable by a sentence that stood at the stamp in the row, the pack or the tree, 3 of the 14 the one restated review rule; 27 of 46 assigns at or over 1,950 of the 2,000-character cap (dispatcher ref, `git show refs/heads/mail/air:mail.jsonl`) |
| The null result is the signal (§5); earn the red (§7) | three non-required portability legs whose verdicts land after auto-merge, read by no board line | 65 failed, 67 passed, 45 cancelled runs since 10-10 (`gh run list --workflow portability.yml --limit 200 --json conclusion`); 12 Windows failures from #313 (merged 13:26Z 10-18) unread until 19:39Z, the leg finishing 13:57Z, after the merge and after the dispatcher's ruling |
| The record is mechanical (Core Rule 4; the handoff's row; `tools/cc/ship.py::_fold_session_log`) | the row is written by a handoff that looping seats never reach, and `open --early` takes any non-empty reason | 79 `lane/` merges in the UTC window 10-16 to 10-18 (`gh pr list --state merged --limit 200 --json mergedAt,headRefName`, re-derived by the reasoning reviewer 2026-10-18 evening; 69 of them have a first claim on the mail refs, the population the claim-to-ship figure below uses), 20 Session Log rows, 18 of them one seat's and the other two the operator-ordered handoffs of 10-18 (`ls memory/session-log.d`); the dispatcher ran one session from 10-15 23:30 through nine compactions with no row and a 371 KB scratchpad as its record |
| Read live state, derive the list (Core Rule 15 item 3; §14) | a dispatcher whose figures were hand-carried across compactions and whose board read was filtered by hand | 19 dispatcher statements corrected in two days, of four kinds: a mechanism stated from memory (8), a measurement narrower than its claim (5), a tool-computed setting restated (3), a figure carried past a compaction (3) (the tick notes; unmeasured beyond the notes) |
| Expand, then contract (Core Rule 15 item 6) | the operator-tree marker moved from `cc/GOAL.md` to `cc/OPERATOR_TREE` in one lane (#321) | no window; the dispatcher's own checkout read as not the operator's until the marker was created by hand at 21:59Z |

So the program is one sentence: for each of the six, find the place where the discipline is a
sentence and make it a mechanism with a probe. That is the harness's own method applied to its
coordination layer, and each child below is one such place.

**What the system did well, so the fix program does not undo it** (all derived by the commands
above unless tagged): merged pull requests per day went from 8 to 13 (10-10 to 10-14) to 23 to
27 (10-15 to 10-18) at a median open-to-merge of 44 to 47 minutes; post-merge proof green on
every latest attempt since 10-10 (two first-attempt reds on 10-17, a census race, re-run green);
the ledger from 283 live rows (10-15 23:30) to 248 (`python3 tools/cc/board.py`, 397799c);
assign-to-first-claim about 9 minutes on 10-18 against 7 to 11 hours overnight on 10-14/15; 19
of 20 dispatcher rulings matched the seat's own recommendation; 0 operator vetoes under the
assign authority. The seats were not idle on CI: lanes build longer than the 47-minute merge.

**The named user (§16).** The operator, who ran four seats for five days and spent the
analysis evening finding that a Windows red had sat unread for six hours, that one seat's
records were the only ones written, and that the box's lock was a conversation. And every seat:
the one that waited ten to thirty minutes at each fork for an answer the row already held, the
one that crossed another's tier on the shared box, the one whose lane merged red on a leg nobody
would read.

## Scope (in) — the children by wave

Each child is one lane a seat ships on its own, with its own Task 0; the roadmap's Task 0 below
can end one before it is assigned. The suited seat is a proposal to the dispatcher, not a rule.

**Wave 1** (now; sequenced, not file-disjoint. The authoring sentence "none shares a file with
another in this wave by design" was false: on 2026-10-19, before any assign, the dispatcher ran
`comm -12` over the backticked paths under each child's `## Files touched` and every pair
shares files -- `TP-703e`/`TP-703f` seven (`tools/cc/mail.py`, `tools/cc/seat.py`,
`tools/cc/board.py`, `tests/test_mail.py`, `tests/test_seat.py`, the protocol,
`.claude/commands/inbox.md`); `TP-703a`/`TP-703f` seven (`tools/cc/board.py`,
`tools/cc/ship.py`, `tests/test_board.py`, `tests/test_ship_driver.py`,
`tests/_surface_expected.py`, `docs/HOOKS.md`, `inbox.md`); `TP-703c`/`TP-703e` four
(`tools/cc/seat.py`, `tests/test_seat.py`, the protocol, `docs/WORKFLOW.md`);
`TP-703a`/`TP-703c` two (`tools/cc/hooks/session_start.py`, `tests/test_session_banner.py`).
A shared file is not a shared symbol (the board reads live claims at the function level,
`TP-702`), and the second to merge runs `catch-up`; the order here keeps those few. `TP-703e`
goes first, the smallest lane and the only one on `tools/cc/mail.py` and `tools/cc/seat.py`
until it merges; `TP-703a` and `TP-703c` start beside it, meeting only in the banner hook,
where `TP-703a` moves the check-state sets out and `TP-703c` adds one off-note line;
`TP-703f`'s census lane (`scripts/` and `tests/` only) starts anywhere now, and its driver
lane after `TP-703e` merges. Cross-seat: the win seats' parked lanes claim the banner hook
and its test (`DEF-674`) and `docs/HOOKS.md` (`DEF-4029`, `DEF-674`), which `TP-703a` and
`TP-703c` catch up on when those lanes ship. Each child's claim re-reads the live overlaps at
its start, and the board's `overlaps:` section is the oracle, not this paragraph):

1. **`TP-703a` — The red after the merge has a reader** (`lane/red-after-merge-has-a-reader`;
   a Mac seat). One shared reader of post-merge verdicts under `tools/cc/`, read by the board,
   the banner's `Merged:` line and the ship preflight, with change detection per check name
   ("red since #313, green on #312"); its Task 0 instrument replays 10-18's check rollups and must
   name #313 by 14:00Z. Closes the gap in the table's third row.
2. **`TP-703c` — One tier per box, by construction** (`lane/one-tier-per-box`; a win seat,
   where the contention is). A pytest plugin that takes a kernel lock on a box-wide file through
   `tools/cc/_json_safe.py::lock_file`, holder named inside it, nested runs let through by the
   holder's pid, opt-in by an environment variable the seat launcher sets so CI never sees it.
   Replaces the `START`/`END` protocol; cannot see foreign suites, and says so.
3. **`TP-703e` — The assign shrinks and the seat proceeds** (`lane/the-assign-shrinks`; any
   seat; the tick sentence is the operator's paste). The assign's shape (row id, why now,
   sequencing, operator constraints, an edge the dispatcher read; nothing the row or
   `scripts/proof_tier.py` already says; a prescribed fix only with its citation), a soft shape
   check at the send, and the seat's authority to proceed on its Task 0 recommendation after one
   tick's veto window, stopping only for an operator-class item.
4. **`TP-703f` — Jobs close by construction, and the dispatcher counts by tool**
   (`lane/jobs-close-by-construction`; any seat). A claim carries the assign it works and the
   lane release closes that job; a release names the ids its lane struck at its head, and a job
   whose ids are all struck closes; section counts on every board header; a `--require-fresh`
   flag on every mail read a gate consumes; a per-seat per-day census script whose figures are
   the only numbers a dispatcher tick report carries; the three dispatcher rules in the brief.

**Wave 2** (after the Wave 1 merge each one names):

5. **`TP-703b` — The platform legs earn their red** (`lane/alarm-guard-contract`,
   `lane/windows-main-leg`, `lane/macos-skip-counted`; a Mac seat for the first, the operator's
   call before the second and third). `DEF-5024`'s contract test on the required cells; a slim
   Windows leg on `main` after each merge, in a workflow of its own (the base-run readers read a
   run's conclusion, so a flaky job inside the proof would red `main`), sized by a dispatched
   portability run first; and
   `DEF-2025`'s counted per-platform skip with the row re-opened. Needs `TP-703a`'s reader so its
   own verdicts are read.
6. **`TP-703d` — The records say what happened** (`lane/the-records-say-what-happened`; any
   seat). A Session Log row per active seat per day, the early-ship debt named on the board per
   seat, the dispatcher's day row derived from the mail and GitHub by `TP-703f`'s census, a
   blueprint justification recorded on every assign, parked rows counted on the board, and
   `cc/GOAL.md` reduced to priorities with operator calls carried as requests the board lists.
7. **`TP-703g` — The rules say what the tools do** (`lane/the-rules-say-what-the-tools-do`;
   the dispatcher's own lighter lane). The six documented drifts the docs reviewer found; the
   operator-tree marker given its expand-then-contract window; the reflect link check reading
   record surfaces as aging, not gaps (Core Rule 13).

**Wave 3** (the unifications; each after Task 0 enumerates its members):

8. **`TP-703h` — Host expectations have one registry** (`lane/host-expectations-registry`).
   One pinned table of what each host is expected to red on, applied by the suite and counted, so
   "one known red" becomes "0 unexpected"; replaces the known-red explanations that live today in
   pull-request bodies (49 of the last 100, by `TP-703h`'s census; the docs, memory and bench
   carry none) and in gitignored local files; `TP-703b`'s skip moves into it (expand there,
   contract here). `tests/_axis_registry.py` (`TP-468`) is the sibling store it sits beside.
9. **`TP-703i` — The suite has a platform axis** (`lane/platform-stand-ins`). The stand-ins the
   seats improvised after the merges they would have prevented (a host without `SIGALRM`, among
   others its census enumerates: five across six files at authoring), registered as an `os` axis
   of `tests/_axis_registry.py` (`TP-468`'s registry, `DEF-975`) behind one shared stand-in, and
   proven on the required Linux cells.
10. **`TP-703j` — A strike reads the base and the guard** (`lane/strike-reads-the-base`).
    `tools/cc/ledger_row.py strike` gains `--base` and `--guard`: the row's probe driven at the
    base and at the head, the guard test red there and green here, refusing otherwise.
    Necessary, not sufficient: a proxy probe that answers an adjacent question still passes it.

## Scope (out)

- **A merge queue.** Not offered to a personal account's repository (`TP-479` Scope out); moving
  the repository is the operator's call and nothing here depends on it.
- **Making the Windows leg a required check** (`DEF-977`'s full form). Median open-to-merge
  would about double against the measured 66 to 81 minute leg, and every `DEF-2025`-class flake
  would block merges. Re-read after `TP-703b` lands the slim leg and `TP-703h` the registry, with
  the leg's measured green rate in hand.
- **One seat per box, a third machine, or a VM per win seat.** The only change that reaches the
  foreign holds (15 on 10-18, at least 5 h). The operator's environment call; the re-measure's
  line 3 reports the minutes `TP-703c` cannot move so the call is made on a figure.
- **A second dispatcher seat.** Only if the re-measure's line 8 fails on latency; a sixth worker
  before that is the wrong lever.
- **Stacked lanes within one seat** (protocol item 4, untested there); nothing here changes it.
- **The three memory candidates the lessons reviewer raised** (an amendment to
  `memory/task-packs.md`'s 09-18 note; rehearse-then-replay for multi-edit hook changes into
  `memory/hook-authoring.md`; platform stand-ins into `docs/FAILURE_MODES.md` §13.7). Memory
  promotions are the operator's approval, never a pack's; held in the dispatcher's candidate log.
- **The `cc/GOAL.md` hard cap value** (4,500 against a proposed 2,500). The question dissolves
  under `TP-703d`: a goal file that holds priorities alone is under either cap.
- **`DEF-4029`** (the PowerShell zone reader's four shapes), shelved after a platform safety
  stop; resumes on `win` under the neutral-wording rule, outside this roadmap.
- **`TP-700`'s headless runner.** A fresh session per lane changes the record layer's writer
  again; `TP-703d` is written so the runner can call the same row verb, and nothing here waits
  on it.

## Task 0 — Verify (the roadmap's; each child carries its own)

Each item names the oracle, the result that ends the child before it is assigned, and the exit,
which is stop and re-raise to the operator, never adjust and continue.

1. **`TP-703a`.** *Oracle:* over the portability runs since 10-10 (`gh run list --workflow
   portability.yml --limit 200 --json databaseId,conclusion,headSha`, each red run's failing
   files from `gh run view <id> --log-failed`), the share of red legs whose every failure is a
   ledgered known class (`DEF-2025`'s one test, `DEF-939`'s file, the walker alarm). *Refuting
   result:* 80% or more. *Exit:* a reader built first would print known noise on every merge;
   `TP-703b`'s counted skip and `TP-703h`'s registry go first, the reader after. (The dispatcher's
   read of 10-16 to 10-18, unmeasured as a share: `DEF-2025` on every post-fix macOS run and the
   12 walker rows on every Windows run since #313, so the result is close to the line.)
2. **`TP-703c`.** *Oracle:* on the mail record (`python3 tools/cc/mail.py inbox --all --json`),
   the minutes a win seat waited on the other win seat's `END` note against the minutes held by
   foreign suites, both read from the notes' stamps, 10-16 to 10-18. *Refuting result:*
   seat-on-seat waits under one hour a day. *Exit:* the lock buys little; the environment call
   is the fix and the child is held. (Expected to build: 87 `START` messages a day is the cost
   even when nobody waited.)
3. **`TP-703e`.** *Oracle:* the ten assigns of 10-18 06:00 to 19:04Z that a seat's Task 0 or
   review re-aimed, each read against the row, the pack and the tree as they stood at the assign's
   stamp, classified findable or not. *Refuting result:* fewer than half findable. *Exit:* the
   assign's content is not the cause and the shape rule is wrong; re-raise with the
   classification. (The dispatcher's own classification: 7 of 10; a second reader does it.)
4. **`TP-703d`.** *Oracle:* merged lanes per seat per day (`gh pr list --state merged --limit
   200 --json mergedAt,headRefName`, lanes to seats by `tools/cc/mail.py::lane_seats`) against
   Session Log rows per seat per day (`ls memory/session-log.d`) since 10-15. *Refuting result:*
   every active seat has one or more rows on every day it merged. *Exit:* the record layer is not
   broken; re-raise. (Read 10-18: four seats wrote rows on 10-15; on 10-16 and 10-17 one seat's
   rows against three seats' merges.)
5. **`TP-703f`.** *Oracle:* the dispatcher's releases on 10-18 (`git show
   refs/heads/mail/air:mail.jsonl`, `type == "release"` with `ack` naming an assign) against the
   lane releases the ship driver sent that closed a job. *Refuting result:* the driver already
   closed most. *Exit:* drop the closure wave; keep the instruments. (Read 10-18: 25 of 25 by
   hand, 1 worker lane release matched an assign's lane.)
6. **Waves 2 and 3.** Each child's Task 0 is its own; the roadmap asks only that none be
   assigned before the Wave 1 merge it names has landed (`TP-703b` after `TP-703a`; `TP-703d`
   after `TP-703f`), which the dispatcher reads from the board, not from this file.

## Relevant memory

Recent pattern, measured: every incident that motivates this roadmap was caught by a person or a
seat reading text, none by a gate, the same pattern `TP-701` recorded a week earlier; and the
dispatcher's 19 corrected statements fell into four kinds, of which the standing rule "cite the
grep" caught only the first. A rule that catches one kind of four is the kind of sentence this
roadmap replaces.

| Entry | Where |
|---|---|
| Parallel work protocol | `memory/parallel-work-protocol.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| Classify the surface before measuring it | `memory/classify-the-surface-before-measuring-it.md` |
| Untrusted oracle protocol | `memory/untrusted-oracle-protocol.md` |
| Action justification protocol | `memory/action-justification-protocol.md` |
| 7. Earn the red | `docs/STANDING_PRINCIPLES.md` |
| Atomic Write Is Not Atomic Update | `docs/SHARP_EDGES.md` (section of that title) |
| CI Approval Marker — Trust the Trigger, Not the OR | `docs/SHARP_EDGES.md` (section of that title) |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "parallel seats dispatcher
assigns the board and the mail channel"`, `... "a check that is not required goes red after the
merge and nobody reads it"` and `... "one writer per shared state a lock negotiated by
messages"`; re-run them rather than trusting this list if the roadmap has been sitting. The
retriever returned the protocol first on two of the three and a hook-authoring entry on the
third, which is lexical proximity, not an answer; the rows above are the ones that bear.

## Implementation — the wave map, the disciplines, the re-measure, the scaling question

Copy-ready changes are in the children. This section carries what the children share.

### How each discipline comes forward

| Discipline | Child | The mechanism (the pick) | The forks not taken, and why |
|---|---|---|---|
| The null result is the signal | `TP-703a`, `TP-703b` | one verdict reader with change detection, read by three surfaces; a slim leg on `main` | making Windows required (doubles merge time on a flaky leg); reading only pull-request runs (misses a red the merge combination makes) |
| One writer per shared state | `TP-703c` | a kernel lock the OS releases when the holder dies, holder named, nested by pid | hardening the mail protocol (still negotiation, still blind to foreign runs); one seat per box (the operator's) |
| Make it prove it | `TP-703e` | the assign carries what only the dispatcher knows; the seat proceeds on its Task 0 after a veto window | a longer cap (more prescription, not less); a per-fork yes (19 of 20 rulings went the seat's way) |
| Derive the list; read live state | `TP-703f` | jobs close from the claim and the strike; counts on every header; one census script owns the day's figures | a dispatcher rule to "release carefully" (a sentence) |
| The record is mechanical | `TP-703d` | a row per seat per day with the debt named by the board; the dispatcher's row derived | a row per lane push (25 rows a day against a 30-row hot set leaves a one-day window); deriving every seat's row (loses what a seat would have said off the mail) |
| Expand, then contract | `TP-703g`, `TP-703h` | the marker window written into the rule; the registry taking the skip the earlier child lands | a flag day (the one that happened) |
| Earn the red; the measuring instrument is a claim | `TP-703j`, `TP-703i` | the strike drives the probe on both sides and runs the guard; stand-ins run as an axis | trusting a green probe at the head (`DEF-985`'s proxy probe did) |

### The re-measure *(pre-registered 2026-10-18, before any child lands)*

Each line names its window and its deriving read; a line that fails re-opens the child it
names, never this roadmap's state.

1. **Red to first mention** (`TP-703a`): over the 50 merges after it lands, the minutes from a
   non-required leg's `completedAt` red to the first board read that printed it. Pass: median
   under 30. Read: the transitions log `TP-703a`'s board read appends under `.espalier-state/`
   (the red's `completedAt` and the read time per first-printed transition); without that log the
   line is not derivable, which is why the child writes it.
2. **The legs' green rate** (`TP-703b`): the portability workflow's `success` share over the 50
   runs after the counted skip and the alarm contract land, over COMPLETED runs (cancelled runs
   leave the denominator: 67 of 132 completed, 51%, over 10-10 to 10-18; 37% with the 45 cancelled
   counted). Pass: 90% or more, with the skip count the roster applies printed beside the rate so a
   green bought by skips is visible. Read: `gh run list --workflow portability.yml --json
   conclusion,status`.
3. **Box messages and waits** (`TP-703c`): worker messages mentioning `START` per day, 87 on
   10-18 to 0 (a secondary figure: it falls as soon as the sentence changes, lock or no lock);
   seat-on-seat wait minutes per day, the primary figure, read from the wait log `TP-703c`'s
   plugin appends beside the lock file (one line per wait with the holder and the waiter);
   foreign-hold minutes per day reported apart from the seats' notes (the lock cannot move them).
4. **Rows per active seat per day** (`TP-703d`): 4 of 4 on every day a seat merges; the debt the
   board names per seat never past the cap the child sets. Read: `ls memory/session-log.d` against
   `gh pr list --state merged`.
5. **Re-aims readable from the repo** (`TP-703e`): over the next 20 assigns, the share a seat
   re-aimed whose correction was findable by reading first, 7 of 10 to at most 1 of 10; minutes a
   seat sat stopped per request, from the request's stamp to its first edit after the ack;
   overrides that later forced rework, at most 1 in 20.
6. **Hand releases** (`TP-703f`): over the next 25 jobs, releases sent by the dispatcher's hand
   against jobs closed by the driver, 25 of 25 on 10-18 to at most 2.
7. **Dispatcher statements corrected** (`TP-703f`'s rules): the three later kinds (a narrower
   measurement, a restated setting, a hand-carried figure) at most 2 a day, read from the
   workers' corrections on the mail refs. The baseline (11 over two days) came from the tick
   notes, a different instrument, so the first ten days re-baseline on the refs before the line
   is judged.
8. **The scaling line** (after `TP-703c` and `TP-703e`): a fifth seat on a third machine adds 6
   or more merged lanes a day while the dispatcher's messages stay below 120 a day and request
   latency under 15 minutes median. Latency past that names the dispatcher as the bottleneck and
   a second dispatcher seat as the next question, not a sixth worker.

### The scaling question, read from the measurements

The operator asked whether more instances with fewer jobs each works. The data says the unit of
work is already right and the constraint is elsewhere.

| Measure, 2026-10-16 to 10-18 | Value | Read |
|---|---|---|
| Lanes shipped per seat per day | air-work 6 to 11, win 8 to 9, win-2 5 to 7 | merged pull requests by lane, lanes to seats by `mail.py::lane_seats` |
| First claim to lane shipped, median | 2.2 h over the 69 lanes with a first claim on the refs; 31 under 2 h, 4 over 6 h | claim stamp to the pull request's `createdAt` |
| Dispatcher messages per job | about 4 (an assign, an ack or two, a release) | the dispatcher's ref, 96 messages on 10-18 over 25 jobs |
| Dispatcher messages at the cap | 19 of 96 on 10-18 | text length at or over 1,950 |

A job is one ledger row, about two hours of build: the class-sized unit Core Rule 12 asks for;
smaller than that is a site, not a job. The seats do not idle on CI. So the levers are: the
dispatcher (four messages a job and a stop at every fork; `TP-703e` is what makes a fifth seat
affordable), the box (two seats on one box lost at least 5 h to foreign suites in a day and spent
87 messages coordinating; the Air cannot take a third seat on one pytest pool and 8 GB), the
account (one account for four seats makes a limit reset freeze all four; a deeper queue rides it
out, and `TP-703e`'s smaller assigns make depth cheap), and queue depth itself (the protocol asks
two or three queued jobs per seat and the dispatcher ran one; untested as a lever). The
pre-registered claim is line 8 above.

### What the children do not do

No child changes the merge rules, the required check set, the id blocks or the one-open-pull-
request-per-seat rule. No child edits `tools/cc/seat.py::WORKER_TICK` directly: the sentence is
proposed to the operator with its own guard, as `TP-702` Wave 3 did, and lands only on the
operator's paste (`tests/test_seat.py::_OPERATOR_TICK` pins the live one).

## Affected symbols

A roadmap: each child declares its own `## Affected symbols`, and `/scope-check` runs on the
child, not here. The four sub-sections declare nothing on purpose.

### Changed-semantics
- None.

### Renamed
- None.

### Added-paths
- None.

### Removed-paths
- None.

## Reach

Not a class pack: it closes no ledger class and mints no row. The rows it touches, so no later
pass reads them as shut:

Members derived by: `grep -lE 'portability|post-merge|SIGALRM|GOAL.md|session-log|assign' task-packs/ledger.d/*.md`
over live rows (re-run it; the five below are the ones a child's mechanism reaches).

| Item | Status | Evidence |
|---|---|---|
| `DEF-5024` (no contract that each `SIGALRM`-arming function guards itself) | **CLOSED by `TP-703b` W1** when the contract test lands and the row is struck in-lane | the census over `tests/*.py` reads 0 unguarded and the test reds on a seeded unguarded function |
| `DEF-2025` (struck 2026-10-18; red on every post-fix macOS run) | **RE-OPENED and CLOSED by `TP-703b` W3** only on the operator's word | the counted skip's roster names it; the leg's green rate |
| `DEF-977` (no Windows check gates a merge) | **NOT CLOSED**; `TP-703b` W2 is its first step | the slim leg's measured duration and green rate decide the required question |
| `DEF-674` (the banner's budget wrong at both ends) | **NOT REACHED**; `TP-703d` dissolves the goal-cap question it carries | win-2's parked lane |
| `DEF-5007` (closed 2026-10-16; the Session Log's transport) | **EXTENDED, not re-opened**, by `TP-703d` | the fold stays the one writer of the count |
| `DEF-4029` | **NOT REACHED** | outside this roadmap (Scope out) |

## Pass criteria

- Every child is `LANDED` or `SCRAPPED` in its own Landing stanza, with its Task 0's result
  recorded there, before this file's state leaves `ROADMAP`.
- The eight re-measure lines are closed with figures and their deriving reads, each in the
  Landing of the child it names; a failed line re-opens that child's Scope (out) item.
- `memory/parallel-work-protocol.md` names, for each of its nine items, the tool that enforces it
  or says "prose" in so many words; no item reads as a mechanism it is not.
- No criterion here licenses shipping a defect in a gate a child delivers: a lock a dead holder
  keeps, a reader that prints a red it cannot date, a release that closes a job whose ids a later
  lane re-pinned, each is a defect of that child, never a scope-out.

## Files touched

**New:** this file and the ten children, `task-packs/TP-703a-the-red-after-the-merge-has-a-reader.md`,
`task-packs/TP-703b-the-platform-legs-earn-their-red.md`,
`task-packs/TP-703c-one-tier-per-box-by-construction.md`,
`task-packs/TP-703d-the-records-say-what-happened.md`,
`task-packs/TP-703e-the-assign-shrinks-and-the-seat-proceeds.md`,
`task-packs/TP-703f-jobs-close-and-the-dispatcher-counts-by-tool.md`,
`task-packs/TP-703g-the-rules-say-what-the-tools-do.md`,
`task-packs/TP-703h-host-expectations-have-one-registry.md`,
`task-packs/TP-703i-the-suite-has-a-platform-axis.md`,
`task-packs/TP-703j-a-strike-reads-the-base-and-the-guard.md`.

**Modified:** `task-packs/FORWARD_LEDGER.md` (one §3 pack row naming the eleven ids).

**Deleted:** none. **Unmodified on purpose:** every source file; the children list theirs.

## Sub-task ordering

1. **The roadmap's Task 0 items 1 to 5**, by the dispatcher, before any assign; each can end its
   child; and each child's authoring-time reads (the `gh pr view` stamps, the mail counts) are
   re-run by a seat other than the dispatcher before that child is assigned, since one seat wrote
   every pack from one reflect and no figure was re-derived from GitHub until the reasoning review
   did it. Checkpoint: the five results and the second reads written into this file's Landing.
2. **Wave 1**, four lanes assigned in parallel: `TP-703a` (a Mac seat), `TP-703c` (a win seat),
   `TP-703e` and `TP-703f` (the remaining two). Checkpoint per lane: its own Landing.
3. **Wave 2** as each named Wave 1 merge lands: `TP-703b` after `TP-703a`; `TP-703d` after
   `TP-703f`; `TP-703g` at any time, the dispatcher's own lighter lane.
4. **Wave 3** after each child's Task 0 enumerates its members: `TP-703h` first (`TP-703b`'s
   skip contracts into it), then `TP-703i`, `TP-703j` at any time.
5. **The re-measure**, read by the dispatcher at each line's window close, written into the
   Landing of the child it names; line 8 is the operator's experiment to run or not.
6. **Red-team per child**, both reviewers on a snapshot clone as the tier's `review:` line names,
   and for every child the brief adds two angles the authoring lenses lacked: GitHub and Windows
   semantics (which runs attach to a rollup, the shared job pool, `LockFileEx` release on kill,
   stale parent pids) and whether each measurement the pack states can be re-derived by its read.
   What this roadmap most likely got wrong, for the passes to bite on: that a lock on one byte of a
   box-wide file is enough where two seats' worktrees share one clone (`TP-703c`); that a seat
   proceeding after one tick does not land a change the operator would have vetoed (`TP-703e`);
   that the struck-ids rule never closes a job whose row a later lane re-pinned open (`TP-703f`);
   that a reader of pull-request rollups is read as proof of `main` (`TP-703a`).

## Estimated effort

Pack budgets on this repository have run about 2.7 times over on one measured pack (`TP-459`);
read these as the author's guess, not a schedule.

| Child | Build | Red-team and tier | Notes |
|---|---|---|---|
| `TP-703a` | 4 to 6 h | 1 h plus the full tier | a shared module, three readers, one instrument |
| `TP-703b` | 3 to 5 h over three lanes | 1 h plus a dispatched portability run | two operator calls inside it |
| `TP-703c` | 4 to 6 h | 2 h plus the full tier | a plugin, the launcher's environment, two OSes |
| `TP-703d` | 5 to 7 h | 1.5 h plus the full tier | four surfaces, one record format |
| `TP-703e` | 3 to 4 h | 1 h plus the full tier | mostly words and one soft check in `tools/cc/mail.py` (any `tools/cc/` edit earns the full tier, `scripts/proof_tier.py::is_runtime`); the tick is the operator's |
| `TP-703f` | 5 to 7 h | 1.5 h plus the full tier | the mail schema, the board, a census script |
| `TP-703g` | 2 to 3 h | 0.5 h plus the tier the diff earns | docs, one reflect rule and two brief clauses; the `tools/cc/` edits lift it to the full tier unless split from the words |
| `TP-703h` | 5 to 7 h | 1.5 h plus the full tier | a registry the tier reads; a census of the prose it replaces |
| `TP-703i` | 4 to 6 h | 1 h plus the full tier | a census first; the axis after |
| `TP-703j` | 3 to 4 h | 1 h plus the full tier | two flags on one `tools/cc/` verb |
| Total | 38 to 55 h | 12 h | expect the measured overrun |

## Landing
- State: ROADMAP
- Commits:
- Suite: `python3 scripts/proof_tier.py --run --base origin/main` on the authoring lane (packs
  and one ledger row: the contract slice)
- Earn-the-red: per child, against the mutation its Implementation names
- Red-team: the reasoning review (the reflect skill's checklist v1, by the failure-mode reviewer
  in its own context, 2026-10-18) on this file and on `TP-703a`, `TP-703b`, `TP-703c` and
  `TP-703j`: REQUEST CHANGES (1 regression, 12 gaps, 8 rough edges; checklist 9 GAP, 3 BIAS, 6
  UNCHECKED). Folded before the first push: in this file, the frame tagged as organising, the
  figures re-stamped (79 lane merges, four seats' rows on 10-15), the note-only counts tagged,
  re-measure lines 1, 2, 3 and 7 given reads that exist (the children's two logs, the
  completed-run denominator, the re-baseline), a second seat's re-read of each child's figures
  before assign, and the two missing review angles added to every child's red-team; in the four
  children, each finding's disposition is in its own Landing. Acknowledged, not changed: the six
  UNCHECKED premises that live only in the dispatcher's tick notes (foreign holds, crossed starts,
  the 19 statements and their kinds, 7 of 10 findable, the reaper-killed seat, 19 of 20 rulings),
  each tagged where it is used; `TP-703e`'s Task 0 and the second reader's classification are
  what turn two of them into measurements. `TP-703d`, `TP-703e`, `TP-703f`, `TP-703g`, `TP-703h`
  and `TP-703i` were outside the review's brief and get theirs at their lanes' start.
- Reach: see Reach; no row closed at authoring
- Task 0 (the roadmap's five items), run 2026-10-18 at authoring over the saved record (the
  deriving reads are in the items): item 2, 89 `START` messages 10-16 to 10-18 (87 on 10-18), 37 of
  them phrased "after" the other seat's `END`, median 8.75 minutes from that `END` to the `START`
  (a handshake gap, the wait itself unmeasurable from the stamps): build `TP-703c`; item 4,
  merged lanes against rows per seat per day since 10-15: win 9/0, 8/0, 8/1; air-work 11/0, 5/0,
  11/1; air 2/0, 4/0; win-2 4/5, 6/6, 7/7: build `TP-703d`; item 5, 25 dispatcher releases naming
  an assign on 10-18 against 1 worker lane release whose lane matched an assign's lane; of the
  day's 25 assigns, 22 closed by the dispatcher's release, 1 by a worker's lane release, 2 still live
  at the read (the
  dispatcher's earlier "20 of 25" was an undercount; the items above carry the measured figure):
  build `TP-703f`; item 1, over the 78 red portability runs the 200-run listing reaches (10-09
  to 10-18), 92 red legs (Windows 65, macOS 23, ubuntu 4), of which 17, all macOS, failed only on
  a ledgered class (`DEF-2025`'s shape 18 legs, the walker alarm 8): an 18% known-noise share,
  far under the 80% line, and the Windows legs' reds spread over many files (node-id failures
  by file: `tests/test_redos.py` 40, `tests/test_mail.py` 30, `tests/test_write_guard.py` 24,
  `tests/test_seat.py` 17), so the reader is built first as planned; the classifier was a
  scratch script over `gh run view --json jobs` and each failed job's log, which `TP-703a`'s
  census replaces; item 3, a second reader in its own context over the 18 assigns of 10-18 06:00
  to 19:04Z, each read against the row, the pack and the tree at the assign's stamp (`git show
  <first-parent commit before the stamp>:<path>`): 14 of 18 re-aimed (3 of them review-only, all
  the same `scripts/proof_tier.py` rule that every `bench/` path earns both reviewers), 12 of the
  14 findable by a sentence that stood at the stamp, 1 partial (`DEF-674`, the structure readable
  and the size needing a render), 1 not (`DEF-1189`, withdrawn on a measurement), 1 undecided
  (`DEF-4029`, shelved by a safety stop before its review was acted on); of the 11 substantive
  re-aims, 9 findable; the reader's caveat: findable means a sentence stated the correction, not
  that a pre-send read would have reached it, and three assigns delegated exactly that check to
  Task 0 by choice; the refuting result (fewer than half findable) is not met, so `TP-703e`
  builds, and the dispatcher's own 10 of 18 and 7 of 10 were undercounts in both directions
- Children: `TP-703a` DRAFT; `TP-703b` DRAFT; `TP-703c` DRAFT; `TP-703d` DRAFT; `TP-703e` DRAFT;
  `TP-703f` DRAFT; `TP-703g` DRAFT; `TP-703h` DRAFT; `TP-703i` DRAFT; `TP-703j` DRAFT
- Date: 2026-10-18 (authored, local)
