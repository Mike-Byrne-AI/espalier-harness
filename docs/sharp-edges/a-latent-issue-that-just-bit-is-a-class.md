# A long-latent issue that "just now bites" is a class, not an instance

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "A Long-Latent Issue That Just-Now Bites Is a Class"

**What it is:** When something that has "been around a while and just now bites
us" surfaces, it is a **new class of errors, not a single error**. The root cause
is a gap that was never foreseen or scoped — so it was never asked about, and the
objective was never scoped well enough to surface it. The thing that bit is
merely the **first sibling of the class to reach the light**.

**Why it matters:** The natural reflex on finding "a bug" is to fix that bug. But
a latent-then-biting issue is evidence of a *systemic blind spot*, and its
siblings are still latent — they will bite one at a time unless the whole class
is hunted now.

**How to avoid it:**

1. **Name the spirit** of the issue abstractly — not "this doc has an internal
   ID" but "the pre-flight gates are blind to shipped-surface content contracts."
2. **Hunt the siblings mechanically.** Enumerate where that spirit is replicated;
   the instance count is a **floor**, so AST/grep the real surface
   (`docs/STANDING_PRINCIPLES.md` §8).
3. **If it is a class, fix the class with a task pack**, not the one symptom.
4. **Resist "it only happened once, don't over-build."** That reflex *is* the
   under-scoping this entry names. A once-*surfaced* class is not a
   once-*occurring* one.

**Worked example:** A doc-content collision looked like "two docs carry internal
IDs." The actual class was: *the `/implement-pack` pre-flight (artifact review,
scope-check, compression) validates the pack artifact and its symbol graph but is
blind to the whole family of shipped-surface contracts — content hygiene,
registration/count pins, byte-mirror parity, broken links, honesty, provenance —
that only fire in the full suite.* One change tripped roughly six of them. Fixing
"doc content" alone would have left the class intact.

**Class signature:** duration of latency mistaken for rarity of occurrence.
