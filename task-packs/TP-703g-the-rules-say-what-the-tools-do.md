# TP-703g — The rules say what the tools do: six documented drifts, the reflect link check's record rule, and the operator-tree marker's window

## Status

- Version target: self-host where it touches `memory/`, `scripts/` and the command bodies'
  self-host paragraphs; adopter-facing where it touches `tools/cc/` (the reflect protocol, the
  mail driver's one comment, the seat driver's brief text deploy through `espalier init` via the
  vendored byte-copy, `espalier/_vendor/cc/`).
- Type: documentation plus one rule (the reflect link check reads record surfaces as aging) and
  one window (the operator-tree marker read two ways until a date).
- **Kind: PACK.** One lane, `lane/the-rules-say-what-the-tools-do`, the dispatcher's own lighter
  lane (`memory/parallel-work-protocol.md`, the dispatcher table: "Carries a lighter lane of its
  own"). The tier is what `python3 scripts/proof_tier.py --base origin/main` prints: words alone
  earn the contract slice; the `tools/cc/` edits here lift the lane to the full tier
  (`scripts/proof_tier.py::is_runtime`, whose full prefixes are `tools/cc/`), and the workflow
  header is a CI definition, which earns both reviewers (`::review`). The executor may split the
  words from the code into two pushes to keep the first cheap; say so in Landing.
- Parent: `TP-703` (`task-packs/TP-703-multi-seat-discipline.md`), Wave 2, item 7. Authored
  2026-10-18 (local) by the dispatcher seat `air` on the operator's word ("good, lets make task
  packs for fixing these issues").
- Ledger: no row minted at authoring (protocol item 8). Not a class pack; Reach is one line.
- Protected zones: `.github/workflows/portability.yml` and every `tools/cc/` file are edited with
  the file tools, never a heredoc (the operator's rule for protected-zone files).

## Motivation

The `/reflect` of 2026-10-18 ran a docs-against-practice reviewer over the coordination layer's
prose and found six sentences that say what a tool does not do, each read at HEAD 397799c
(`grep -n`, the command beside each in Task 0). A rule that disagrees with its tool is `TP-479`'s
L7 ("a written rule that disagrees with the live setting"), and every one of these cost a read:
the dispatcher queued one job where the protocol asked for two or three; the worker tick's stop
sentence held a seat idle for the minutes a request took; the portability header told a reader
the Windows verdict lands before the merge, where on 2026-10-18 the leg finished 13:57Z on a
merge of 13:26Z; the ship driver's post-merge reader claims the banner's rule and lacks its
ownership clause; the reflect pass printed two "gaps" that are one gitignored record's aging
pointer; the mail cap is stated in two places with a reason in neither; and no first message a
seat gets names the handoff that writes its row.

The marker is the seventh: #321 (`DEF-1119`) moved the operator-tree tell from the goal doc to
the empty, gitignored `cc/OPERATOR_TREE` (`scripts/record_snapshot.py::OPERATOR_MARKER`) in one
lane, with no window in which both tells were read. Measured 2026-10-18 on the dispatcher's main
checkout: `python3 scripts/check_handoff_landing.py --skip-tests --skip-trailer --skip-shape
--skip-keys` read the tree as not the operator's until the file was created by hand at 21:59Z,
whereupon it printed `note: operator tree: <root>; seat: air`. Protocol item 6 says a record's
format changes by expand, then contract; a tell is a record of one bit, and it changed by flag
day.

Who is hurt (`STANDING_PRINCIPLES` §16): a seat reading the protocol to decide how deep its queue
should be, and getting two answers; a contributor reading the workflow header and trusting a
Windows verdict that has not arrived; the operator reading a reflect report that counts aging as
gaps on every pass (two on 2026-10-18, `python3 tools/cc/reflect_protocol.py --json`); and the
operator's second clone, which reads as not the operator's the morning after a tell moves.

## Scope (in)

Each drift with its file, the sentence as it reads at HEAD, and the sentence that replaces it or
the pack that owns the change:

1. **(a) The queue depth.** `memory/parallel-work-protocol.md` item 1 reads "keep two or three
   queued"; the dispatcher table's row reads "Keeps at least one job with clear gates on every
   seat's queue". Reconcile both to two queued jobs per seat (the protocol's own reason, "so the
   dispatcher's absence does not stall you", holds at two; one is what ran, and one stalls on the
   first fork). The authority change that makes two cheap is `TP-703e`'s; this pack changes the
   number and names that pack.
2. **(b) The tick's stop sentence.** `tools/cc/seat.py::WORKER_TICK` reads "STOP and send
   {dispatcher} one request, then only re-read mail until it is answered". The sentence is the
   operator's paste (`tests/test_seat.py::_OPERATOR_TICK`) and `TP-703e` proposes its
   replacement; this pack edits nothing of it and adds one clause to protocol item 1 saying a
   seat with a queued job moves to it while a request is open, as that pack lands it.
3. **(c) The portability header.** `.github/workflows/portability.yml`'s comment reads "Pull
   requests and dispatch only: the signal is read before the merge, on the PR's merge result,
   and main never re-runs it (not a required check)". Replace "the signal is read before the
   merge" with the measured truth: the legs run on the pull request's merge result and the
   Windows leg often finishes after auto-merge has landed the lane; `TP-703a`'s reader is what
   names such a red. Only if `TP-703a` has not already changed the sentence (its Task 0 reads the
   header), else this item is struck in Landing.
4. **(d) The post-merge reader's docstring.** `tools/cc/ship.py::post_merge_reds` reads "the
   banner's `Merged:` rule, restated for a tool that cannot import the hook", and the function
   names every merged pull request among `POST_MERGE_ROWS` whose latest run of a check is red,
   where `tools/cc/hooks/session_start.py::_post_merge_verdicts` owns each check name by the
   newest merge whose run reached a verdict, so an older red a later merge went green on is
   printed by one and not the other. `TP-703a` merges the two readers; until it does, the
   docstring says "without the banner's ownership rule". Struck in Landing if `TP-703a` lands
   first.
5. **(e) The reflect link check on record surfaces.** `tools/cc/reflect_protocol.py`'s link
   loop reports a broken link on any surface as a `gap` of severity `high`;
   `RESIDUE_EXEMPT_SURFACES` in the same module names the append-only records (its comment:
   "They stay link-checked exactly as before; only the quality scan skips them"), and Core Rule
   13 says a stale pointer on a record surface is aging, never a defect. The two gaps the pass
   printed on 2026-10-18 were `docs/session-archive.md` (gitignored, `.gitignore` names it; a
   record, both in `RESIDUE_EXEMPT_SURFACES` and in
   `tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS`) linking
   `memory/publish-from-a-generated-public-repo.md`, which no longer exists. The rule: a broken
   link on a surface in `RESIDUE_EXEMPT_SURFACES` is a finding of kind `aging`, severity `low`,
   described as "Aging pointer on a record surface", counted in a new `aging_count` and never in
   `gap_count`. The set's one home stays `espalier/claim_extractor.py::RECORD_SURFACES`, whose
   tools-side twin `RESIDUE_EXEMPT_SURFACES` is held equal minus `docs/FAILURE_MODES.md` by
   `tests/test_reflect_protocol.py::TestReflectTwinParity`; no third copy is made here. The engine
   twin, `espalier/reflect_protocol.py`, carries the same loop and derives its
   `RESIDUE_EXEMPT_SURFACES` from `RECORD_SURFACES` directly, so the rule lands on both twins in
   this lane and the parity test holds them equal; Task 0 item 5 reads whether the doctor's
   lighter scan (`espalier/reflection.py`, its `broken_markdown_links` list) needs it too.
6. **(f) The mail cap's reason.** `.claude/commands/inbox.md` Step 3 reads "The cap is the same
   2,000 characters" and `tools/cc/mail.py::MAX_TEXT` is a bare `2000`; `git log -S'MAX_TEXT =
   2000' -- tools/cc/mail.py` reaches the channel's first commit (c461b705), whose message gives
   no reason, and `TP-479`, `TP-478` and `TP-701` state the cap without one (`grep -n '2,000'`
   over the three packs: one hit, `TP-701`, the dry run's count). The reason is written once, as
   the constant's comment, and the command body points at it; Task 0 item 6 decides the reason's
   words (measured or declared).
7. **(g) The briefs and the handoff.** `tools/cc/seat.py::WORKER_BRIEF` and `::DISPATCHER_BRIEF`
   name the reads, the jobs and the loop and never the handoff that writes the seat's row
   (`.claude/commands/handoff.md`). One clause each, proposed as text below; the briefs are
   pinned by `tests/test_seat.py::TestBrief`'s `startswith` and `endswith` assertions, which a
   clause inside the text leaves standing and a clause at the end does not, so the clause goes
   before the last sentence. The brief is the tool's text, not the operator's paste (the tick
   is), so this pack lands it with its pins.
8. **The marker's window.** `memory/local-codename-arm.md` "## Marking the operator's tree"
   gains the rule that a tell moves by expand, then contract: both tells read for a dated window,
   the old tell's reader printing the new tell's path. `scripts/record_snapshot.py::operator_root`
   reads both until the date (fix shape below), and `scripts/check_handoff_landing.py::_operator_root`
   and `scripts/handoff_mechanics.py::operator_root` need no change (both call it).

## Scope (out)

- **The tick's sentence itself** ((b) above): `TP-703e` proposes it; the operator pastes it.
- **Unifying the two post-merge readers** ((d)): `TP-703a`. This pack changes a docstring.
- **The portability leg's mechanism** ((c)): `TP-703a` and `TP-703b`. This pack changes a
  comment.
- **Reducing the three record-surface sets to one import.** `tools/cc/` imports nothing from
  `espalier/` (Architecture Rules), and `tests/` is not importable from a tool, so the twin stays
  a pinned copy; the test's two-member `_RECORD_SURFACE_DOCS` is a deliberate subset (the
  record surfaces that carry source citations) and Core Rule 13 names it for that test's
  purpose. Task 0 item 5 reads whether the subset is by design; a finding there is a note in
  Landing, not work here.
- **Raising or removing the mail cap.** `TP-703e` shrinks the assign to fit well under it; the cap's
  value is not this pack's question.
- **The memory candidates the lessons reviewer raised.** Memory promotions are the operator's
  approval, never a pack's (`TP-703` Scope out).
- **`docs/WORKFLOW.md` "Parallel seats".** `grep -n -E 'two or three|at least one job|before the
  merge|2,000' docs/WORKFLOW.md` finds none of the six sentences restated there (read
  2026-10-18), so the asset mirror under `espalier/assets/docs/` is untouched.

## Task 0 — Verify (try to kill this pack)

Each drift's oracle is the grep that shows the sentence still reads that way at the lane's HEAD;
the refuting result is "already corrected", and the exit is to strike that item in Landing and
go on, since the items are independent. Two items carry a decision.

1. *(a)* `grep -n -E 'two or three queued|at least one job with clear gates' memory/parallel-work-protocol.md`:
   two lines, item 1 and the table (read 2026-10-18). *Refuting:* one spelling. *Exit:* strike.
2. *(c)* `grep -n 'read before the merge' .github/workflows/portability.yml`: one line (read
   2026-10-18). *Refuting:* none, `TP-703a` corrected it. *Exit:* strike.
3. *(d)* `grep -n "restated for a tool that cannot import the hook" tools/cc/ship.py`: one line in
   `post_merge_reds`'s docstring (read 2026-10-18). *Refuting:* none, or the function is gone
   into `TP-703a`'s shared reader. *Exit:* strike.
4. *(e)* `python3 tools/cc/reflect_protocol.py --json | python3 -c "import json,sys; r=json.load(sys.stdin); print(r['gap_count'], [f['description'] for f in r['findings'] if f['kind']=='gap'])"`:
   2 and the two archive links (read 2026-10-18). *Refuting:* 0 gaps and no record surface among
   them, because the archive's pointer was edited (which falsifies the record, Core Rule 13) or
   the loop already skips records. *Exit:* if the loop already skips, strike; if the record was
   edited, the rule is still built and the edit is noted as the thing the rule prevents.
5. *(e), the sister sites.* `grep -n -E 'Broken link in|RESIDUE_EXEMPT_SURFACES' espalier/reflect_protocol.py`:
   the engine twin carries the same loop and the same set (read 2026-10-18), so the rule lands
   on both and `tests/test_reflect_protocol.py::TestReflectTwinParity` keeps them equal; that is
   measured, not a decision. The decision is the third site: `grep -n -i 'broken'
   espalier/reflection.py` shows the doctor's lighter scan building `broken_markdown_links` with
   no record set. If that scan reaches a record surface on this tree (drive `espalier doctor` and
   read the WARN), the same rule lands there through `espalier/claim_extractor.py::RECORD_SURFACES`,
   which the engine may import; if it does not reach one, it is left alone and Landing says why.
6. *(f)* `git show c461b705 --format=%B -s | grep -i -E 'cap|2000|character'` (nothing, read
   2026-10-18) and `grep -rn -E '2,000|MAX_TEXT' memory/*.md docs/*.md task-packs/TP-4*.md
   task-packs/TP-7*.md`. *Decision:* a reason found in the record is quoted; none found, the
   comment declares the cap's purpose as the author's (a message points at a row, a pack or a
   lane and never carries one; the dispatcher's assigns at the cap on 2026-10-18, 19 of 96 at or
   over 1,950 characters, were the symptom `TP-703e` treats) and says it was undocumented at
   c461b705.
7. *(g)* `grep -n -E 'handoff' tools/cc/seat.py`: no hit inside the two brief templates (read
   2026-10-18: the word appears in the module's comments only, if at all). *Refuting:* a brief
   names `/handoff`. *Exit:* strike.
8. *The marker.* `ls cc/OPERATOR_TREE` in every checkout the operator works from (this main
   checkout, created 2026-10-18 21:59Z; the second Air clone and the Windows box's clone are
   the operator's to read). *Refuting:* every operator checkout already carries the marker, so a
   window now protects nothing. *Exit:* the rule still goes into the memory note (the next tell
   that moves is the case), and the two-tell read in `operator_root` is dropped, said in Landing.

## Relevant memory

Recent pattern, measured: the six sentences were each written when they were true (the queue
rule before the dispatcher ran one job, the header when the legs were quick, the reader's
docstring when it matched the banner) and none had a test that reads the tool; the one surface
with a test, the briefs, is pinned on the parts that did not drift. Prose that restates a tool
rots at the tool's pace.

| Entry | Where |
|---|---|
| Classify the surface before you measure it | `memory/classify-the-surface-before-measuring-it.md` |
| Ladder CLAUDE.md design: pointer, not restatement | `memory/ladder-claudemd-design.md` |
| Parallel work protocol | `memory/parallel-work-protocol.md` |
| Folder CLAUDE.md ladder is instruction-layer, not hook-layer | `docs/SHARP_EDGES.md` (section of that title) |
| The local codename arm (the marker paragraph) | `memory/local-codename-arm.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "documentation drifts from the
tool it describes; a record surface's stale pointer is aging not a gap"` and `... "the operator
tree marker moved with no window expand then contract"`; re-run them rather than trusting this
list if the pack has been sitting. The second query returned hook-authoring and recall-engine
entries, lexical proximity and not an answer; the codename note is the row that bears, found by
its path.

## Implementation

Every fix below is a **fix shape (untested)** unless marked measured; its refutation is named.
Items (a), (b), (c), (d), (f) and (g) prescribe prose and carry no code fence; the rule (e) and
the window (8) carry one fence each.

### (a) and (b): the protocol's queue depth *(measured: the two lines; the new words untested)*

Item 1 becomes "keep two queued, so the dispatcher's absence does not stall you, and move to the
next while a request is open (`TP-703e` lands the tick's words)"; the table row becomes "Keeps
two jobs with clear gates on every seat's queue, and re-reads the gates when a lane merges".
Refuted if `TP-703e`'s Task 0 finds two queued jobs cost more assign text than the shrunken
assign saves; then both lines read "at least one, two where the gates are clear" and say why.

### (c): the portability header *(prose; conditional on `TP-703a`)*

The two comment lines become: "Pull requests and dispatch only: the legs run on the PR's merge
result, and a leg may finish after auto-merge has landed the lane (the Windows leg ran 66 to 81
minutes against a 47-minute median open-to-merge, 2026-10-16 to 10-18); main never re-runs it
(not a required check), and a red that lands after the merge is named by the post-merge
reader." Edited with the file tools. Refuted if `TP-703b`'s slim leg on `main` lands first and
the last clause is wrong; then the clause names that leg.

### (d): the reader's docstring *(prose; conditional on `TP-703a`)*

In `post_merge_reds`'s docstring, "the banner's `Merged:` rule, restated for a tool that cannot
import the hook" becomes "the banner's `Merged:` rule without its ownership clause: every red
among the newest `POST_MERGE_ROWS` prints, an older red a later merge went green on included,
until `TP-703a`'s shared reader replaces both". Refuted only by `TP-703a` landing first.

### (e): the link check's record rule *(fix shape, untested)*

In `tools/cc/reflect_protocol.py`'s link loop (the `for path in surface` block that appends
`Broken link in ...`), the surface's relative path decides the kind:

```python target=tools/cc/reflect_protocol.py
            c = (path.parent / t).resolve() if not t.startswith("/") else (root / t.lstrip("/"))
            if not c.exists():
                if rel in RESIDUE_EXEMPT_SURFACES:
                    # Core Rule 13: a record's stale pointer is aging, and editing
                    # it would falsify the record. Reported apart, never a gap.
                    findings.append({"kind": "aging", "severity": "low",
                                     "description": f"Aging pointer on a record surface {rel}: {t}"})
                else:
                    findings.append({"kind": "gap", "severity": "high",
                                     "description": f"Broken link in {rel}: {t}"})
                continue
```

The report gains `"aging_count": sum(1 for f in findings if f["kind"] == "aging")` beside
`gap_count`, and the reflect skill's Phase 3 report line reads it. The broken-anchor arm below
it takes the same split. The engine twin's loop in `espalier/reflect_protocol.py` takes the same branch, so
`tests/test_reflect_protocol.py::TestReflectTwinParity` and `tests/test_reflect_link_guards.py`'s
twin-agreement test (`test_reference_implementation_still_agrees`) keep holding. Refuted if the
reference implementation that agreement test reads is a third copy with no record rule; then it
gains the rule in the same lane, or its fixture surface names no record and the agreement
stands. Mutation the test dies to: the membership test
dropped (a record's broken link counted as a gap again), and the kind spelled `gap` with the new
description (the count moves, the kind does not).

### (f): the cap's reason *(prose, after Task 0 item 6)*

Above `MAX_TEXT` in `tools/cc/mail.py`, a comment of three lines: the reason (quoted or
declared), the commit it dates from, and that a body over it is split into a message and notes
(the machine-local memory's rule, now in the tool's own text). `.claude/commands/inbox.md` Step 3
reads "The cap is `MAX_TEXT`'s, and why is the comment above it" in place of "the same 2,000
characters", so the number has one home. The mirrors follow by `scripts/sync_claude_mirrors.py`.

### (g): the briefs name the handoff *(text proposed; the pins move with it)*

- `WORKER_BRIEF`, before its last sentence: "When the operator ends your session, run /handoff:
  it writes your Session Log row and ships it on your open lane or parks it."
- `DISPATCHER_BRIEF`, before its last sentence: "At the operator's word, run /handoff; your row is
  derived from the mail and the merges (TP-703d)."

Both 7-bit ASCII, no double quote, no `%` (the template's three pins in `tests/test_seat.py`).
The `startswith` assertions stand; the `endswith` assertion on the worker brief stands because
the clause precedes the last sentence. Refuted if a clause pushes the first message past what
Claude Code's prompt takes on Windows PowerShell 5.1 (`tools/cc/seat.py`'s own comment on the
argument split); Task 0 drives `seat.py brief <seat>` on the win box once.

### 8: the marker's window *(fix shape, untested; after Task 0 item 8)*

```python target=scripts/record_snapshot.py
import datetime  # joins the module's imports; record_snapshot.py imports no datetime today

OPERATOR_MARKER = "cc/OPERATOR_TREE"
#: The tell this one replaced on 2026-10-18 (#321, DEF-1119), read beside it
#: until the window ends so a checkout not yet marked still reads as the
#: operator's and is told to mark itself (expand, then contract: protocol item 6).
OLD_OPERATOR_TELL = "cc/GOAL.md"
MARKER_WINDOW_ENDS = "2026-11-01"


def operator_root(repo_root: Path) -> Path | None:
    try:
        main = linked_worktree_main(repo_root)
    except RecordError:
        main = None
    home = main if main is not None else repo_root
    if (home / OPERATOR_MARKER).is_file():
        return home
    if (home / OLD_OPERATOR_TELL).is_file() and datetime.date.today().isoformat() < MARKER_WINDOW_ENDS:
        print(f"note: this tree carries {OLD_OPERATOR_TELL} and not {OPERATOR_MARKER}; the tell moved on "
              f"2026-10-18 and both are read until {MARKER_WINDOW_ENDS}: create {OPERATOR_MARKER} (empty) "
              "in the main checkout", file=sys.stderr)
        return home
    return None
```

The memory note's paragraph gains the rule in two sentences: a tell moves by expand, then
contract; the window's end is a date in the reader, and the old tell's reader prints the new
tell's path. Refuted by Task 0 item 8 (every operator checkout marked): then the fence is not
landed and the note alone changes. Mutation the test dies to: the date comparison inverted (the
old tell read after the window), and the note printed to stdout, where
`scripts/check_handoff_landing.py` reads the snapshot's output.

## Affected symbols

`/scope-check` keys on bare names; `operator_root` has three homes by design (`scripts/record_snapshot.py`,
`scripts/handoff_mechanics.py`, `scripts/check_handoff_landing.py::_operator_root`), and only the
first changes. Re-run it at the lane's start.

### Changed-semantics
- `tools/cc/reflect_protocol.py::RESIDUE_EXEMPT_SURFACES` (read by the link loop too: its members' broken links are aging)
- `espalier/reflect_protocol.py::RESIDUE_EXEMPT_SURFACES` (the engine twin, the same reading)
- `tools/cc/ship.py::post_merge_reds` (docstring only; conditional on `TP-703a`)
- `tools/cc/mail.py::MAX_TEXT` (a comment; the value is unchanged)
- `tools/cc/seat.py::WORKER_BRIEF` (one clause)
- `tools/cc/seat.py::DISPATCHER_BRIEF` (one clause)
- `scripts/record_snapshot.py::operator_root` (two tells until the window ends; conditional on Task 0 item 8)

### Renamed
- None.

### Added-paths
- `scripts/record_snapshot.py::OLD_OPERATOR_TELL`
- `scripts/record_snapshot.py::MARKER_WINDOW_ENDS`

### Removed-paths
- None.

## Reach

Not a class pack: it closes no ledger class, mints no row and claims no reach; the six drifts are
the docs reviewer's list, re-read at Task 0, not a census of every drift in the layer.

## Pass criteria

- Each of the eight items is either landed with its grep reading the new sentence at the lane's
  head, or struck in Landing with the grep that showed it already corrected; no item is silently
  dropped.
- `python3 tools/cc/reflect_protocol.py --json` on this repository reports `gap_count` 0 for the
  archive's two links and `aging_count` 2 (or the count the record holds that day), and a fixture
  tree with one broken link on a record surface and one on a plain doc reports one of each kind;
  no assertion in `tests/test_reflect_protocol.py` or `tests/test_reflect_link_guards.py` is
  weakened and no fixture removed.
- Earn-the-red recorded per fix against the mutation named in its Implementation; a test that
  only ever passed does not count.
- `python3 tools/cc/seat.py brief <worker seat>` and `brief <dispatcher seat>` print the clause,
  and `tests/test_seat.py::TestBrief` passes with its pins moved only where the text moved; the
  loop line is byte-identical to `_OPERATOR_TICK`.
- `scripts/check_handoff_landing.py` on a scratch tree with the old tell and no marker prints the
  note and reads the tree as the operator's before `MARKER_WINDOW_ENDS`, and as not the operator's
  after it (the date stubbed); with the marker it prints nothing new.
- `python3 scripts/sync_vendor_cc.py` and `python3 scripts/sync_claude_mirrors.py` report clean
  after the lane; the tier `scripts/proof_tier.py --base origin/main` prints is the one run, with
  the receipt in the pull request body.
- No criterion here licenses shipping a defect in the rule the pack delivers: a record rule that
  hides a broken link on a non-record surface because the membership test matched a prefix
  rather than the path is a defect of this pack, not a scope-out.

## Files touched

**New:** none.

**Modified:** `memory/parallel-work-protocol.md`; `.github/workflows/portability.yml` (two comment
lines, file tools, conditional); `tools/cc/ship.py` (one docstring, conditional);
`tools/cc/reflect_protocol.py`; `tools/cc/mail.py` (one comment); `tools/cc/seat.py` (two
clauses); `espalier/_vendor/cc/` (by `sync_vendor_cc.py` only); `.claude/commands/inbox.md` and
its mirrors under `espalier/assets/claude/commands/` and `examples/dogfooding/.claude/commands/`
(by `sync_claude_mirrors.py` only); `.claude/skills/reflect/SKILL.md` (the Phase 3 report's
`STRUCTURAL GAPS` line reads the two counts) and its mirrors (by the same sync);
`memory/local-codename-arm.md`; `scripts/record_snapshot.py` (conditional);
`tests/test_reflect_protocol.py`; `tests/test_reflect_link_guards.py`; `tests/test_seat.py`;
`tests/test_check_handoff_landing.py` (the marker's window, beside
`TestTheLocalCodenameArmMustExist`); `espalier/reflect_protocol.py` (the engine twin of the
rule); `espalier/reflection.py` only if Task 0 item 5 decides so.

**Deleted:** none.

**Unmodified on purpose:** `tools/cc/seat.py::WORKER_TICK` (the operator's paste; `TP-703e`);
`tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS` (a deliberate subset, Scope out);
`docs/WORKFLOW.md` and `espalier/assets/docs/WORKFLOW.md` (no restatement found, Scope out);
`scripts/check_handoff_landing.py` and `scripts/handoff_mechanics.py` (both call
`record_snapshot.operator_root`, which carries the window).

## Sub-task ordering

1. **Task 0**, the eight items, at the lane's start; items 5, 6 and 8 carry decisions, written
   into Landing before the edits. Checkpoint: the eight results.
2. **(a), (b), (f)'s body, (g)** (the words), then the syncs. Checkpoint: the greps read the new
   sentences; `tests/test_seat.py` green with its pins moved.
3. **(e)** (the rule), its tests red first against the unchanged loop, then green. Checkpoint:
   the two counts on this repository.
4. **8** (the window), if item 8 says build. Checkpoint: the scratch-tree drive on both sides of
   the date.
5. **(c), (d)** last, each only if its grep still reads the old sentence after `TP-703a`'s state
   is read from the board. Checkpoint: the greps.
6. **Red-team** before the tier: the reviewers the tier script names, on a snapshot clone with
   edits frozen. What this pack most likely got wrong, for the pass to bite on: (e)'s membership
   test matching `rel` against a set that holds paths without a trailing slash while the loop's
   `rel` may carry a Windows separator (`_rel` normalises; read it); and 8's note going to a
   stream the landing check parses.
7. **Landing** in this file's stanza, each item's disposition on its own line.

## Estimated effort

Pack budgets on this repository have run about 2.7 times over on one measured pack (`TP-459`);
read these as the author's guess, not a schedule.

| Item | Build | Red-team and tier | Notes |
|---|---|---|---|
| Task 0 | 0.5 to 1 h | none | eight greps and two drives |
| (a), (b), (c), (d), (f), (g) | 1 to 1.5 h | 0.5 h | words; two syncs; the brief's pins |
| (e) | 1 h | 0.5 h plus the full tier | one branch, one count, a fixture tree |
| 8 | 0.5 to 1 h | 0.5 h plus the contract slice | conditional |
| Total | 3 to 4.5 h | 1.5 h plus the tier | expect the measured overrun |

## Landing
- State: DRAFT
- Commits:
- Suite:
- Earn-the-red: (e) and 8 against the mutations their Implementation names; the words by their greps
- Red-team: authoring review not yet run
- Reach: none claimed
- Task 0: not yet run; items 5, 6 and 8 carry the decisions
- Items struck as already corrected: (none yet)
- Date: 2026-10-18 (authored, local)
