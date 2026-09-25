# A retraction does not propagate itself

**Status:** active — named 2026-09-01 from a live reconstruction of a retracted belief
**Linked from:** `memory/publish-from-a-generated-public-repo.md` (`DEC-25`, the retraction
                 that failed to propagate) · `task-packs/FORWARD_LEDGER.md` §4 ·
                 [[classify-the-surface-before-measuring-it]] ·
                 [[premise-check-before-authoring-a-fix]] ·
                 `docs/sharp-edges/citation-rot-verify-fix-target-tree-wide.md`

Writing a decision down retracts nothing. The superseded claim keeps its own copies, and
those copies keep being read — so the retracted belief is **reconstructable from the repo
at any later date**, by a reader who has done nothing wrong.

## The failure it names

`DEC-25` (2026-08-20) decided this tree is **never published**: it renames to
`espalier_harness_dev_private` and stays private forever, while a *generated* repo inherits
the public slug. That decision landed correctly in `memory/`.

On 2026-09-01 a session asserted, to the operator, that this repo was "scheduled to flip
public" — and built a *new open question* on top of it ("option D's flip-exposure is
unmeasured"), aimed at a decision the handoff had marked settled. The operator caught it.

The session had not searched for the retracted belief. It arrived unbidden, from three
places, in this order:

| Source | Kind | Verdict |
|---|---|---|
| `.claude/workflows/_oss_launch_review_2026_08_05.js` `meta.description` — *"the repo as a stranger sees it on the day it goes public"* | **injected into every session's context at startup** | live, wrong |
| `task-packs/FORWARD_LEDGER.md:587` — *"PRE-FLIP GATE … before the repo goes public"* | the live forward tracker | live, wrong noun (a public repo *is* created — not this one) |
| `task-packs/FORWARD_LEDGER.md:765`, `:2360` — `LG-14`/`LG-3`, *"private-vulnerability-reporting is an owed **pre-flip operator action**"* | the live forward tracker | live, wrong **action** — `DEC-25` says enabling it *here* accomplishes nothing |
| `task-packs/TP-443…md` `Version target: 0.8.0b1 (pre-flip)` | record surface | **correctly stale** — expected aging, do not edit |

## Why it is hard to see

1. **The retraction is quiet; the retracted claim is loud.** `DEC-25` is one file that must be
   pulled. The superseded framing sits in an *always-injected* `meta.description` — it is
   read every session, for free, by a reader who never chose to read it.
2. **Retractions are written where the reasoning is, not where the claims are.** The natural
   home for "we decided X instead" is `memory/`. The copies live in trackers, workflow
   metadata, and command bodies — surfaces the retraction's author is not editing.
3. **Record surfaces are indistinguishable from live ones at the grep.** ~15 of the ~20 hits
   here are `Done/` / `Deferred/` / `ARCHIVE_*`, where staleness is *correct*. Counting
   before classifying (Core Rule 13) reports a 20-defect crisis instead of a 5-row fix.
4. **A retracted premise gets rebuilt into new work.** The failure is not "held a wrong fact."
   It is that the wrong fact generated a fresh open question against a settled decision —
   the retraction was re-litigated by a reader who never saw it.

## What to do

- **When a decision retracts a prior framing, the unit of work is the retraction's
  vocabulary, tree-wide — not the decision file.** Grep the retired phrase (`pre-flip`,
  `goes public`) at the moment of deciding, classify each hit record-vs-live, and fix the
  live ones in the same commit. This is `docs/sharp-edges/citation-rot-verify-fix-target-tree-wide.md`
  applied to *vocabulary* rather than to paths.
- **Rank hits by readership, not by count.** An always-injected `meta.description` outranks
  a hundred archived pack lines. But check coverage per-directory before claiming a gap:
  `retired_vocab`'s `DOC_SURFACES` **already sweeps** `.claude/agents/`, `.claude/skills/`,
  `.claude/commands/` and `espalier/assets/claude/`. The hole is **`.claude/workflows/`** —
  absent from `DOC_SURFACES` *and* unreachable anyway, because `_doc_files` globs `*.md`
  while workflow bodies are `*.js`. Two independent misses stacked on the one directory
  whose `meta.description` is injected verbatim into every session.
- **A retired phrase is mechanically checkable.** Unlike a stale *fact*, a retired *word*
  can be pinned: a `retired_vocab` scanner already exists (`/scan retired_vocab`) — it is the
  natural mechanical home, and `pre-flip` is exactly its shape.
- **Suspect the belief you did not go looking for.** A claim that arrives unbidden, matching
  something you already half-believe, has skipped the scrutiny a claim you sought would get.
  A claim that arrives as *context* is as exempting as one that arrives as *structure*.

## The gap, closed 2026-09-21

`task-packs/FORWARD_LEDGER.md` was **gitignored** and sat outside `_swept_docs`
(`docs/` + `memory/` + repo root), so no citation or consistency test read the live
tracker at all -- the repo's most-edited forward surface had the least mechanical
coverage. The ledger is tracked now and `_swept_docs` sweeps it; the packs beside it
are dated plans and stay out by one predicate (`surface_contract.is_shipped_pack`).
