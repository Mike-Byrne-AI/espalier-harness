# Fix the surface the reader consumes, not the one the fact is authored on

**Status:** active
**Linked from:** memory/ cool-store — reached on demand via the `memory/CLAUDE.md`
                 folder router and sibling cross-links
                 ([[a-review-workflow-needs-two-classifications]],
                 [[sister-site-compression]]); recorded 2026-08-19 from a single
                 session's four instances, deliberately NOT promoted to
                 `docs/FAILURE_MODES.md` — see "Why this is not canon yet" below.

A correction landed **where the fact is written** and not **where the reader meets
it**. Every instance passed its own review, because each fix *was* correct at the
site it touched. The question none of them asked is: **what does the consumer
actually see?**

The gap opens whenever a rendering, projection, index or deploy step sits between the
authored artifact and the consumed one. The author edits upstream; the reader is
downstream; and the two look identical from inside the diff.

## The four instances, one session

| the fix landed on | the reader actually consumes |
|---|---|
| the **body** of a `docs/SHARP_EDGES.md` entry | `Hit.render()` prints the **title** — `/recall` kept reciting the retired claim |
| a hand-listed **four files** | `README.md`, the highest-traffic surface, absent from the list |
| a test asserting the winning **filename** | the defect is which **section within it** wins |
| the **engine**, correctly | `.claude/commands/recall.md`, the operator-facing description, still described the old behaviour |

A fifth, the same day, in the same subsystem: a claim was scoped correctly in the
module docstring while the canonical copy it *pointed at* kept the unscoped wording —
and that copy is inside the retrieval corpus, so the tool would have served the
falsified claim about itself.

## The check that would have caught all of them

Not "is this fix correct?" — every one was. Ask instead:

> **Name the surface the reader meets, and confirm the fix is on THAT one.**

Concretely: what does the *renderer* emit (title? body? snippet?); which file does the
*deploy* copy; which description does the *caller* read; is the population *derived*
or hand-listed. When authored and consumed differ, the fix belongs downstream — or on
both, with the upstream one carrying a pointer.

## Why this is not canon yet

Four instances is class-strength evidence *only if* they are independent. These are
not: all four are the same subsystem in one session, which makes them at least partly
one author's blind spot on one surface rather than a general shape. The repo has a
documented habit of promoting too eagerly, and
[[fix-the-class-not-the-instance]]'s own precondition (the one about identifying who
is actually harmed) is satisfied here, but the *generality* is not yet earned.

⚠ Wording note, and it is the point of this file in miniature: an earlier draft quoted
that precondition verbatim. Because `memory/` is in the recall corpus, the quote made
this note out-rank the principle it was citing for a query that IS that principle's
title — caught by `test_every_principle_is_retrievable_by_its_own_name` on the first
run after the file landed. A document inside a retrieval corpus competes with the
documents it cites. Paraphrase the citation; do not quote its title-bearing phrase.

**Promote to `docs/FAILURE_MODES.md` when it recurs in an unrelated subsystem.** Until
then this note is the ledger. If you are reading it because you just hit a sixth
instance somewhere else, that is the signal: add the row and promote.
