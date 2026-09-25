# The ungated field is where a record drifts — and the suite is green while it does

**Status:** active
**Linked from:** `docs/session-archive.md` row 2026-09-18 "SEVERITY RE-AUDIT: `DEF-837` PROMOTED minor -> major" (the index row that first linked this file was archived there by the cap prune at `91577de`, 2026-09-22)
**Kin:** [a-hand-written-count-that-moves-on-ordinary-growth-is-tax](a-hand-written-count-that-moves-on-ordinary-growth-is-tax.md) —
that one is about a derived number kept by hand; this one is about a field that
is kept by hand *because nothing derives it at all*.
**Canon:** `docs/STANDING_PRINCIPLES.md` §1 (make it prove it) — the field that
proves nothing.

When a record carries several metadata fields and only some are derived and
gated, **the ungated one is where the drift accumulates, and it accumulates
invisibly** — every gate is green over it by construction, because no gate
reads it.

## Attested (2026-09-18, the forward-ledger severity re-audit)

The Forward Ledger's member rows carry three tags. Measured at HEAD:

| Field | Derived into the file? | Gated? | Repin verb? | Rubric? |
|---|---|---|---|---|
| population | yes — the §2 table and the headline split | `TestTheLiveLedgerConverges`; `--check` exits 1 on drift | yes | yes |
| audience | yes — the audience table and the "N reach an adopter" line | same gate, **plus** a contradiction advisory that flags a MAINTAINER row whose text names an adopter | yes | yes |
| **severity** | **no** — appears in no generated region | **no** — nothing compares it to anything | **none existed** | **none** |

`generate_ledger_regions.py` defines `POPULATIONS` and `AUDIENCES` and derives
every count from them. It never reads cell 4. Severity's only mechanical life
was as a *shape discriminator* — `_SEVERITIES` in `scripts/ledger_row.py` and
`_MEMBER_ROW_SEVERITIES` in `tests/test_forward_ledger_completeness.py` both
exist to answer "is this line a member row", never "is this grade right".

**The result was not chaos, and that is the interesting part.** An eight-lane
adversarial audit over 150 live rows produced 88 findings and exactly **two**
severity/audience corrections. With no gate at all, the field had drifted very
little. The failure is not volume — it is that **you cannot tell**, and the one
row that had drifted was the most consequential row in the ledger.

## The tell, when you go looking

Two sibling rows filed in the same hour. `DEF-836` states its grade's reason
("Minor because the spelling is contrived…"). `DEF-837` states **none** — its
text runs mechanism → "Fix:" with no "Minor because" anywhere. The ungraded one
was the *more ordinary* spelling, and it was the one mis-graded: `minor` where
its own direct twin walls, on an adopter-reachable path.

> **A field with no rubric produces rows with no rationale, and the row with no
> rationale is the one to re-read.** Grep the population for rows that assert a
> grade without arguing it; that set is small and it is where the errors are.

## How to apply

1. **Inventory the fields of any record the project keeps** — ledger rows,
   registry entries, corpus records — and ask of each: derived? gated?
   correctable through a verb? does a rubric exist? A field failing all four is
   a free-text token typed once and never re-examined.
2. **Give it a verb before you give it a policy.** `ledger_row.py repin
   --severity` landed 2026-09-18 with `--reason` already required on that verb,
   so a grade cannot move without its rationale attached. Until then a re-grade
   was a hand edit that *also* staled `row_sha`, flipping the row's own probe to
   `STALE_CLAIM` — so the only mechanical consequence of correcting the field
   was to make the row look unmaintained.
3. **Find the rubric and check where it lives.** This repo's only written
   severity rule sat inside a dated session note
   (`task-packs/FORWARD_LEDGER.md`, the 2026-08-12 session note: "a bypass
   leg is major only if a NON-ADVERSARIAL user reaches it by typing something
   ordinary"). It had been
   applied once, to demote three rows, and never promoted to the contract. Two
   independent audit lanes reached for it and both had to go find a session note
   to do it — which is §C21's lesson again: *a rule whose only home is a tracker
   is a rule that gets re-learned.*
