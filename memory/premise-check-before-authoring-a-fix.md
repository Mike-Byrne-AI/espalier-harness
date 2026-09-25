# Premise check before authoring a fix

**Status:** active
**Linked from:** memory/ cool-store — reached on demand via the `memory/CLAUDE.md`
                 folder router and sibling cross-links ([[sister-site-compression]],
                 [[orientation-lever-experiment]]); its original
                 "2026-06-30 SessionStart BANNER REDESIGN" row has since aged
                 out of the 120-line `ESPALIER_MEMORY.md` hot index.

Every fix rests on a **load-bearing premise** — an assumption about how the
system actually works that, if false, makes the fix wrong (or void) no matter how
clean the code is. **Verify that premise FIRST, against an independent oracle —
before you design the fix, not after you've built on it.** This is
make-it-prove-it (STANDING_PRINCIPLES §1) pushed *upstream* into the **design
phase**: the make-it-prove-it discipline most people apply to *verification* (does
the change work?) applies equally to *premises* (is the thing I'm fixing even the
thing that's broken?). A premise is a claim — and a claim is untrusted until
grep-verified (§3) against the real system, not the repo's pinned description of it.

## Why (the cost it prevents)

A wrong premise doesn't fail loudly — it sends you building a correct fix for the
wrong problem. You can pass every test, ship green, and still have changed nothing
(or the wrong thing), because the test certified the *fix*, not the *premise*. The
premise lives one layer up from where the tests look (§5: separate the layers — the
trigger vs the mechanism, "it" vs "the fix"). So the failure is silent and the
wasted work is total.

## How to apply

1. Before authoring, write the premise down as one sentence: *"This fix works
   because <X is true>."*
2. Verify X against an **independent mechanical oracle** — the live behavior, the
   live external docs, a grep against HEAD — NOT the repo's own description of
   itself, and NOT your memory of it. (The repo's pinned copy of an external fact
   can be stale; read the source.)
3. If X is unverifiable on this host, label the fix's magnitude *unverified* and
   say so — don't let a sound mechanism smuggle in an assumed effect (§6).

## The evidence (one session, four recurrences — 2026-06-30)

The banner-redesign session flipped its approach **four times**, each time because
the premise-check ran and the load-bearing premise turned out false:

1. **PostCompact priming was VOID.** Premise: "a PostCompact hook can inject
   orientation into the model." Checked vs the *live* CC docs (not the repo's
   pinned copy): PostCompact reaches only the USER via stderr; the model's
   post-compaction re-orient is **SessionStart re-firing with `source=="compact"`**.
   The whole fix relocated (→ TP-240 source-aware `session_start.py`).
2. **"Skip gitignored" was the WRONG AXIS.** Premise: "the release builders ship
   what isn't gitignored." Checked: the bespoke builders *disk-walk* and exclude via
   `is_internal`, so gitignore is not the ship-axis at all. The real bug was
   `matches_export_ignore`'s dead trailing-`/` directory-pattern arm (→ TP-239).
3. **A false claim got BLOCKed at the gate.** The 0-A pack-artifact review BLOCKed
   my justification "`EXPORT_IGNORED_INTERNAL_DOCS` already lists session-archive" —
   it doesn't; the file is in `MUST_NOT_BE_IN_ARCHIVE` and is untracked. Premise
   corrected; the fix itself was fine, but the *stated reason* was false.
4. **A green test FALSELY CERTIFIED a mid-word leak.** `_truncate_on_boundary` (the
   honesty primitive) leaked a mid-word fragment on whitespace-less input — and its
   OWN green test gave false assurance by only ever feeding whitespace. The premise
   "this is tested" was true in letter, false in coverage. A [[complacent-oracle]]:
   the test certified the happy path and called it proof. Caught only by the
   16-agent adversarial pass.

## Relation to the rest of the discipline

This is the *design-phase* face of the verification machinery: where
[[untrusted-oracle-protocol]] says "verify tool OUTPUT through an independent
oracle" and [[forensically-audit-the-workflow-not-just-output]] says "audit the
EXECUTION, not just the end-state," this says "verify the PREMISE before you author
the fix at all." The [[complacent-oracle]] note is the specific trap it most often
catches: a check that passes because it never tested the thing that breaks.

From the 2026-06-30 SessionStart banner/orientation redesign session.

---

## The gate that cannot ask this question (added 2026-09-01)

The pack-execution gates are an **execution-readiness** suite, not a premise suite.
All twelve checks take the pack's goal as given and audit the plan against it; none
can return *"do not do this at all."*

`0-A`'s checklist, compressed — line numbers resolve · cited symbols exist ·
cross-pack collisions · test naming · `BC-NNN` contiguity · no conflicting
prescription · effort sane **"for the scope listed"** · pass criteria testable ·
surface additions declared. Then `0-B` reference graph, `0-C` compression probe,
`0-D` surface impact. Item 7 comes closest, then fences itself: *for the scope
listed*.

Two occurrences, different endings:

- **`TP-443` (2026-08-20)** — driven, **landed**, reverted the same session
  (`00554bb`, `a198289`). The gates passed a pack whose objective was wrong.
- **`TP-449` (2026-08-31)** — 350 lines authored, gates returned REQUEST-CHANGES,
  never executed. The gates held; the waste was authoring plus a full gate review.

Neither time did a gate raise the premise. What killed it both times was the
operator asking a question. **The only premise gate in this system is the operator.**

Two structural reasons it stays invisible: a pack's `## Goal` arrives as
*structure* rather than as a claim, so it escapes the scrutiny a claim gets; and the
gates run at **execution** time, by which point the expensive artifact already
exists — the gate sits *after* the cost it could have prevented.

**Unbuilt — proposal, not a mechanism.** The natural mechanical home is
`tools/cc/hooks/task_router.py` (`UserPromptSubmit`), which already classifies prompt
scope and already fires the `/implement-task --multi` advisory. A hint fired at
*authoring* time costs nothing and lands where the choice is made; a checklist item
added to `0-A` would not, because `0-A` runs after the pack exists. Same surface the
operator's deferred pack-vs-plan discriminator wants.

See [[a-retraction-does-not-propagate-itself]] for the sibling failure: a premise
that was *correctly* retracted, and reconstructed anyway from copies the retraction
never reached.

**Instance, 2026-09-16 (DEF-832, the interpreter write leg).** A ledger row's
stated MECHANISM is a load-bearing premise too. The row was filed on the joined
argv line of an interpreter's shell-out; the first drive of the row's own probe
spelling at the hook denied on the working tree and on a pre-lane extraction
alike. The honest next move was one hypothesis from reading the reader the row
named, written as one must-deny row -- not a walk of quoting shapes through the
extractor, which is what the lane did first and what tripped the classifier (the
tenth trip). The real mechanism sat in a helper's own docstring: the shell
concatenates adjacent quoted and bare segments into one argument, and every
program-operand reader took the first quoted span. The fix that the row
prescribed (route the joined line through the nested-shell descent) would have
changed nothing. The hook-specific record is in [[hook-authoring]] under the
2026-09-16 program-operand section.
