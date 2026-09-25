# A new guard is blind the way it claims to see

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "A New Guard Is Blind The Way It Claims To See"

**Read this when you are about to write or widen a guard, test, gate, scanner,
check, assertion, pin or contract** — especially when you are writing it to
catch a defect you just found.

**What it is:** The artifact built to catch defect-class X is itself an instance
of X. Its **population** or its **predicate** structurally excludes **its own
subject**. It ships green, it will stay green, and it can never fire on the
thing it names.

**The strict test.** Apply the artifact's own stated purpose to the artifact. If
its purpose would have caught it, this is that. Ask out loud, before moving on:

> **"What mutation leaves this green while the defect it names is live?"**

Then drive that mutation. If the answer is *"delete a row from the population it
iterates"*, you already have it. A check that cannot fail is not evidence; a
test that passes but proves nothing about the property is the normal outcome
here, not a surprise.

**Why it recurs even when you know.** The defect form is the **shorter** form.
Every time:

| correct | what actually gets written |
|---|---|
| derive the population from the source of truth | iterate the thing under test |
| set-equality, both directions | `assert len(x) >= N` |
| derive the receiver set | name the receivers you thought of |
| spawn it and read what it says | ask only whether the name resolves |
| pin the shipped default | reset it in every test first |

So this is **not carelessness and not forgetting**. Writing the fix is the same
authoring task that produced the defect, and the cheap road is still the cheap
road. Being primed on the class raises vigilance; it does not change the cost
gradient, and vigilance loses to a gradient over enough repetitions. Expect to
reach for the same shape *while fixing it* — that is the normal case. The fix
has the same bug it is fixing, and it will feel reasonable at the time.

**How to avoid it:**

1. **Make sure the new check can actually fail.** Drive the mutation before you
   move on. Not "does the suite pass" — does this assertion engage its subject?
2. **Derive the population; never enumerate it.** If you must hand-keep a list,
   say so in the comment and pin its membership against a derived source.
3. **Assert absence, not presence.** `>= 1` and bare truthiness cannot tell
   6-of-189 from 189-of-189.
4. **Put the instrument inside its own population** where that is meaningful.
5. **Budget an adversarial pass after it is green.** Measured in this repo: this
   is not caught at authoring time; it is caught by attacking the finished,
   green fix. A green suite is not evidence about it.

**Known faces** — each names one; go read the one matching your artifact.

- `docs/sharp-edges/closed-loop-verification-trap.md` — escaping a closed loop
  while blind on the escape axis.
- `memory/a-gate-can-be-blind-along-a-whole-dimension.md` — the corpus has no
  variation on the axis under test. Tell: *the adjective the probe names is the
  axis it is blind along.*
- `memory/completeness-gate-must-discover-its-population.md` — a member missing
  from a hand-kept list.
- `memory/classify-the-surface-before-measuring-it.md` — counting on a surface
  where the count means something else.
- `docs/FAILURE_MODES.md` §1.13 (autoimmune vs born-blind: firing on your own
  defining material vs never firing at all), §5.10, §13.23, §18.1–18.5.
- `docs/SHARP_EDGES.md` — *"A Parity Contract That Pins Presence, Not Absence"*.

⚠ Most of `docs/FAILURE_MODES.md` is **not** in the `/recall` corpus (§1
coinages only, a measured ranking decision), so open those section pointers by
hand rather than expecting recall to surface them.

**Prior art, and why this entry exists at all.** The general form was written
down once, in full, at `docs/session-archive.md:284` (2026-05-27) — *"pack drafts
are themselves subject to the failure modes they claim to prevent… Generative-
defense packs require self-application as part of design review"* — and the same
row records the promotion being skipped to hold a cap. It stayed unpromoted while
the shape kept recurring, which is the whole argument for a single spine rather
than a twentieth face.
