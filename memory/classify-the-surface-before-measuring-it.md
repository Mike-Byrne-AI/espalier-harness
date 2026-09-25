# Classify the surface before you measure it

**Status:** active
**Linked from:** `tests/test_catalog_self_consistency.py::_ANCHOR_SCAN_EXCLUDE_DOCS` ·
                 `task-packs/FORWARD_LEDGER.md` §C4 ·
                 [[fix-the-class-not-the-instance]] · [[a-review-workflow-needs-two-classifications]]

A count of broken pointers on a **record** is not a defect count. Before measuring how
broken a surface is, establish what the surface is *for* — because the measurement
does not need that answer to produce a number, and the number will look identical
either way.

## The failure it names

Five passes over two months flagged the same population as citation rot. Each pass
measured accurately. Each was wrong, and each was wrong for a **new reason**, which is
the tell (below). The population was `docs/known-findings.md`, an append-only findings
corpus: every entry means *"on this date a review round found a problem here."* A
location is the line as it stood **when that round ran**. The fix that followed moves
it. So an anchor pointing at unrelated code is the **expected steady state** and is
evidence the finding was fixed — and re-anchoring it unbinds the entry from the report
that still cites the old line, making the "correction" strictly destructive.

The corpus header said all of this. It had said it for two days before the next session
re-flagged the anchors as an open defect and nominated fixing them as the best next
move. Depth of search was never the problem.

## Why a warning inside the surface does not work

**Whoever raises the alarm has usually not opened the file.** They read a scanner count,
a tracker row, or a handoff note. A caveat written *inside* the artifact is guarded by
the one act the flagger skipped.

So the record has to sit at the **doorway** — wherever the number is produced and
wherever the row is read:

- the exclusion set that decides what gets scanned, with the *true* reason (this one
  had stated an unrelated, scanner-domain reason, which read as an admission of a gap);
- the predicate whose docstring explains what it skips (this one conceded the entries
  were "tracked as owed work", certifying the false backlog in its own next breath);
- the tracker row (which asserted the defect, while its own collapsed detail already
  carried the refutation and the answer).

Quote no count at a doorway you want people to leave alone. **A number invites someone
to drive it to zero.**

## The tell: novelty in the failure mode

Six attempts here, and not one failed because its fix did not work — each failed
because the problem was framed wrong, and each for a fresh reason. That pattern is the
general diagnostic and its sole home is **`docs/STANDING_PRINCIPLES.md` §15** (*"Many
attempts, a different failure each time — the problem is mis-specified"*), which
carries the full case and the corollary about searching harder. Not restated here.

## The distinction to apply

| | **Claim surface** | **Record surface** |
|---|---|---|
| A pointer asserts | this is true **now** | this was true **then** |
| Pointer stops resolving | rot — fix it | expected aging — leave it |
| Editing an entry | corrects the doc | **falsifies the record** |

`tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS` is the declared set. Membership
there is the answer to "is this rot?" — check it *before* measuring, not after.

## The one licensed edit: term redaction

A record may be edited for exactly one reason: to remove a term that must not ship —
the names the codename gate's local arm enforces ([[local-codename-arm]]). The
redaction replaces the term with its effect on the same line and touches no count,
anchor, date or verdict; it is not a re-anchor and not a re-count, and "the change is
immaterial" is not the license — materiality is the judgement this note exists to keep
out of a record. First instance: 2026-09-21, three phrases in
`memory/CONVERGENCE_LEDGER.md` (TP-452 1-G; the failure-mode lane judged it the licensed
exception and asked for this clause so the precedent cannot be cited for anything
wider). The pre-redaction text stays in this tree's history; the redaction holds because
publish is a generated fresh-history repository ([[publish-from-a-generated-public-repo]]).

Beware the split registry: a surface can be declared a record in one module and be absent
from the exclusion set of another, surviving only by accident of what the second module's
regex happens to match. Reconcile the two rather than trusting either alone. Nor is that
set the only home — `tests/test_documented_claims.py::_NOT_CAP_SURFACES` independently
declares `CHANGELOG.md` a record, with the reason stated in full: entries *"stay CORRECT
AS HISTORY once the value moves. Binding it would force edits to a log."* Search for the
declaration before concluding there isn't one.

## When one file is both — the granularity trap

The declared set is keyed on **file paths**, which works only where a file is wholly one
thing. `task-packs/FORWARD_LEDGER.md` is not. Its `§C` member tables are a claim surface —
a row asserts an open defect *now* — while its `<details>` carried-forward blocks are a
record, each stanza stating what an investigation found on its `_Source:` date. One file,
both kinds, adjacent. Membership in a path-keyed set cannot express that, so the file is
absent from it: **the guard built to prevent this error is structurally incapable of
covering the file where the error keeps recurring.** When a classification keeps failing
on one surface, check whether the classifier's granularity matches the surface's before
writing another rule.

Two properties make a mixed file worse than an undeclared one:

- **The status word comes first; the date comes last.** A stanza opens with `open (low).`
  and carries its `_Source:` stamp eight lines below. A reader scanning meets a
  live-status word on a historical note and stops there — the one token that would
  reclassify it is the last thing on the entry.
- **A struck row leaves its stanza behind, correctly.** Measured 2026-08-09: **104
  stanzas across 21 blocks, 8 with no live row** — heading removed from the table, body
  retained on purpose. Each reads as an open defect whose row someone forgot to write,
  which is the most inviting possible false lead.

The fix is neither per-entry nor another guard: **label the container.** All 21 block
summaries now open `RECORD — … was true THEN … leave as written`, which is the doorway a
reader passes before reaching any stanza. No stanza was edited — editing one would have
falsified an accurate dated measurement, which is the failure this note exists to stop.

## Not the same as the proxy-oracle rule

Resist collapsing this into [[a-review-workflow-needs-two-classifications]] or the
proxy-oracle discipline. There, an oracle answers a *neighbouring* question. Here the
oracle answered **its own question correctly** — the anchors really do not resolve — and
the error was inferring a defect from a true measurement. The missing step is not a
better oracle. It is a classification that must happen **before** measurement means
anything.

## Counter-case — do not over-apply

"It is a record" is not a general excuse for stale pointers. It holds only where the
artifact is genuinely append-only and something *else* depends on the entry staying
byte-stable. Line numbers a **program** reads are the opposite case and were a real
defect: two allowlists keyed on source line numbers un-keyed themselves on any edit
above the entry (ledger `DEF-417i`/`DEF-417j`, closed 2026-08-09 by retiring both keys).
Same shape from a distance, opposite verdict. Ask who reads the pointer — a person
reading history, or a program matching a key.
