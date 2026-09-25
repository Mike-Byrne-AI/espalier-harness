# A friction fix and a fail-open are one edit seen from two sides

**Status:** ACTIVE — landed 2026-08-25 (`dbdd17c`); the corpus that enforces it is
`tests/test_guard_false_positives.py`.

**Linked from:** `ESPALIER_MEMORY.md` session log (2026-08-25 row).

## The rule

When you narrow a guard so it stops refusing harmless input, you have also
widened what it permits. Those are not two changes — they are one change
described from either end. So a corpus that can only report *"the false positive
is gone"* must never be trusted about *"and nothing else got through"*.

Every relief needs a must-deny twin, authored in the same edit, or the edit
cannot fail in the direction that matters.

## What it cost to learn

Measured 2026-08-24/25 while closing a 100% false-positive rate on the PowerShell
guards (16 of 16 ordinary shapes refused: a comment, a variable assignment
holding the text as data, a `Select-String` over the docs, a commit message
describing the guard).

The relief worked. It also opened **four fail-opens**, all in the same edit:

- **The corpus shipped the blind spot with the fix.** `$pattern = '<verb>'` went
  in as a must-ALLOW row. Its unquoted twin `$x = <verb> C:\` — which in
  PowerShell *runs* the command — went in as nothing at all. The row that proved
  the relief was the row that hid the hole.
- **A widened roster met a latent bug.** `cd` was added to the non-re-parsing
  head set, which was correct; the head-word walker just never re-armed on a
  newline, so one benign first line vouched for every line after it. Driven
  against a real shell: the victim directory was deleted, a guard file was
  overwritten, and `disableAllHooks` reached `.claude/settings.json`.
- **The oracle certified the safe variant of the broken shape.** Four wrappers
  were added to `bench/reachability_differential.py` specifically to prove that
  relief safe. All four used `cd /tmp && …`, and `&&` is in the separator class
  that *does* re-arm — so every one stayed correctly DENY. A gate whose rows all
  share the property under test cannot fail.

Nine thousand tests, a 154/154 release benchmark and a 279-shape shell
differential were green throughout. The adversarial pass found all four.

## How to apply

1. **Write the must-deny twin in the same commit as the relief.** If you cannot
   state the shape that must still be refused, you do not yet understand what
   you narrowed.
2. **Check your oracle's rows against the property you changed.** If they all
   share it, they are your assumption written twice. Vary the axis you touched —
   here, the statement separator.
3. **Diff against a CALIBRATED baseline, never a bare run.** Prove the baseline
   can report both verdicts first: an early probe read `rc=1` (an ImportError) as
   ALLOW and reported that `HEAD` permitted a catastrophic delete.
4. **A soft tier needs two drives to see.** Deny-once-then-allow is
   indistinguishable from a wall on a single invocation.
5. **Match the twin's granularity to the relief's.** A relief granted per HEAD
   but paid per DOOR needs a must-deny row per door: the differential's twin
   rule keys on the head, so one door's row vouches for nothing but itself, and
   a head enrolled on two of its doors silently lost the raw-scan catch on the
   other five. Enrol only when every door has a reader and either an executing
   row or a declared limit — and when a review finds a door unread, read the
   door rather than withdraw the relief, because the relief has a named user
   and the door set is finite.
6. **A new rule must not reach up to a shape another tier already owns, and a
   driven false deny outranks the fail-closed instinct that put it there.** The
   enclosing rule answered "this directory holds a protected path" for the repo
   root too, on the fail-closed reasoning that the catastrophic tier walls it
   first, which walled an everyday narrowed find from the root and a cached
   git rm of the tree: everyday commands refused harder than the whole-tree
   spelling they narrow. Let a narrowed operand judge its own root, leave the
   whole-tree shape to the tier that owns it (and check that the tier does:
   `DEF-815`), and land the everyday spellings as rows in
   `tests/test_guard_false_positives.py` in the same edit;
   `docs/STANDING_PRINCIPLES.md` §2 is the ordering, and the friction side wins
   (2026-09-14).

Sibling: [[convergence-review-protocol]] (adversarial refute as a standing step),
[[fix-the-class-not-the-instance]] (the unit of work), and
`docs/FAILURE_MODES.md` §12.8 (a workflow that writes after its own gate — the
same shape one layer up: the check and the thing checked drift apart).
