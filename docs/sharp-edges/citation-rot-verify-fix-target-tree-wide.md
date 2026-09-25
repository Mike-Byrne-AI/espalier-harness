# A rotted citation's fix target is itself a claim — grep tree-wide before rewording

**Status:** active
**Linked from:** docs/SHARP_EDGES.md section "A Rotted Citation's Fix Target Is Itself a Claim"

**What it is:** When a doc→test citation rots into a phantom (the cited symbol or
file no longer resolves), the tempting fix is "reword the claim so it matches the
lesser reality." That reflex is wrong roughly as often as it is right: the cited
class may be **alive in a sibling file**, and the only real defect is a wrong
path in the pointer. Rewording then deletes a valid citation to a working,
tested system and logs a fictional coverage gap.

**How you hit it:** `docs/CONVENTIONS.md` cited a test path that no longer existed.
The dead example — deliberately not repointed here, because it is the specimen —
was `tests/test_write_guard.py::TestUnicodeNormalization`. The nearly-shipped
fix was to drop the citation and qualify the doc down to "ASCII-only; exotic
unicode is OS-level, not unit-tested." Grep-verifying the *fix target* rather than
just the phantom showed the system was fully built and wired (NFKC +
`.casefold()` in `_hook_utils.py`) **and** fully tested — the class is live at
`tests/test_hooks.py::TestUnicodeNormalization` (8 tests), and the bypass
corpus's own `documented_in` field named that exact location. The correct fix was
a one-token file repoint.

**How to avoid it:** A rotted citation has three possible truths. Rule them out
**in this order**:

1. **Wrong pointer, system live elsewhere** → repoint. Grep the cited symbol
   across the whole tree (sibling test files included) and check the bypass
   corpus's `documented_in` field.
2. **Coverage genuinely lost** (system built, test deleted) → restore the test;
   do not delete the claim.
3. **Genuine over-claim** (system never built) → *only now* reword, and consider
   whether the right move is to build it.

"Make the claim honest" is the last resort, not the first. This extends the
finding-is-a-claim discipline (`docs/STANDING_PRINCIPLES.md` §3) to the fix
itself: **the fix target is a claim too.**

**Class signature:** treating the absence of a symbol at one cited path as
evidence of the absence of the system.

**Prevention (cite by anchor, not by line):** the cure above fires *after* a
citation rots; the way to stop minting rot is to never cite by line number. A
`file.py:NN` in a docstring or comment is rot-in-waiting — the number is right
for exactly one refactor. Cite cross-file test/symbol anchors **by name** (`per
TestX in tests/test_y.py`, not `tests/test_y.py:58`). This class was recently
drained from `espalier/`: the stale `TestScannerSelfContainment` line-citation was live
across **five** scanners, and a tree-wide sweep found further stale line-cites
the per-file finders missed (e.g. `scripts/release_check.py::check_docs_no_overclaim`, whose target
had since moved). A line number is shared-provenance rot the moment it is
committed.

**The repointing an oracle suggests is itself a claim (2026-08-09).** The prevention
above got mechanised — the tree-wide anchor scan now reports a broken citation *and*
names the nearest line carrying content. That second half is a blank-line proxy, not a
semantic resolver: it answers "which line has text on it", never "which line did the
author mean". Both repairs it proposed were wrong, and both would have passed review:

- test_hook_exec_form.py:80 → *"nearest content is 79"* (unbackticked here on
  purpose: this doc is under the anchor ceiling like every other, and quoting the form
  in backticks would mint the very thing it warns about). Line 79 is the closing paren
  of a **different test**; the sentence meant the method beginning at 81. Taking the
  suggestion would have silently repointed the citation at unrelated code and gone green.
- cli.py:1843 → *"nearest content is 1842"*. The sentence was a past-tense war-story
  **about** 1843 being stale. Repointing it would have falsified the record — and 1842
  was not the referent either; the phrase had moved to 1907.

The AST fails the same way for the same reason: asked for the symbol enclosing line 80,
it correctly returns the **class**, because 80 is the blank line between two methods. A
boundary line has no single right answer, and every automatic resolver will confidently
give you one.

**So: read the citing sentence before accepting any suggested target.** Tense is the
strongest tell — *"was"*, *"since moved"*, *"the pack named"* mark a citation that is
supposed to be historical, and repairing it destroys the thing it records. Those get
de-anchored, not repointed. And where the cited line turns out to hold a comment, an
import or a decorator, there is no symbol to convert to at all: drop the number and keep
the filename. Nine of the seventy citations retired in that pass were exactly this shape.
