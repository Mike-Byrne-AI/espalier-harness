# Read the neighbours before adding a sibling

**Status:** active
**Linked from:** `docs/STANDING_PRINCIPLES.md` §13 ·
                 [[fix-the-class-not-the-instance]] · [[a-packs-prescribed-fix-code-is-a-claim]] ·
                 [[untrusted-oracle-protocol]]

Before adding a **new instance of an existing kind** — an emitted hint string, a path
helper, a guard predicate, a warning message, a fixture — read how the file already
does that thing, and copy it. The answer is almost always already sitting a few lines
away, written correctly, by someone who hit the footgun you are about to hit.

This is the *authoring-side* twin of [[fix-the-class-not-the-instance]]. That entry asks
"is this defect one site of a class?" before you **fix**. This one asks "is this addition
one site of a class?" before you **write**. Same class-shaped thinking, opposite
direction: one looks backward at a bug, the other forward at a new line of code.

## Why it earns a rule

Measured on `TP-421` (2026-08-07): across five review rounds, **every headline diagnosis
survived and a prescription broke each time**. Three of those broken prescriptions were
this exact shape — new code written next to correct code, without reading it:

| what was added | what the neighbours already did | how it would have failed |
|---|---|---|
| `Path(resolved).resolve()` for venv containment | the sibling fix's own docstring forbade it **in bold, 180 lines earlier** | guard inert on every POSIX venv — the whole fix a no-op |
| a second containment helper (`_path_is_under` beside `_under`) | one already existed in the same package, importable | two names, two *different* bodies, silent wrong verdict at a third call site |
| a bare `` `espalier init .` `` hint | ~12 hints in the same file used `` `{_detect_python_command()} -m espalier …` `` | reds `tests/test_no_bare_espalier_hints.py`; command-not-found in a fusion |

None was a hard problem. Each was a **local convention that was never read.**

## The tell

You are about to trip this when you can say: *"I need a X here"* — where X is a hint, a
predicate, a helper, a message, a marker — and you reach for a fresh one instead of
asking *"how does this file already spell X?"*

The risk is highest exactly where it feels lowest: adding one more of something the file
is already full of feels mechanical, so it skips review. A brand-new mechanism gets
scrutiny; the fourteenth hint string does not.

## The habit

Before writing the line, grep the target file — not the tree — for how its neighbours do it:

```bash
grep -n "espalier " espalier/doctor.py | head        # how are hints spelled here?
grep -rn "def _.*under\|is_relative_to" espalier/    # does this helper already exist?
```

Two questions, in order:

1. **Does this already exist?** If yes, import it — do not write a twin. A twin with a
   *different body* is worse than a duplicate, because it reads as intentional.
2. **If it must be new, what shape do its neighbours have?** Match it. A new shape beside
   twelve old ones is a claim that the twelve are wrong; make that claim explicitly or
   not at all.

## What this does NOT say

It does not say "always copy the neighbour." Sometimes the neighbours are the defect —
that is what [[fix-the-class-not-the-instance]] is for. The rule is that you must have
**read** them and made a choice, not that the choice is always "conform." Deviating with
a stated reason is fine; deviating without noticing is the failure.

## Why an agent will not catch this for you

A reviewing agent reads the diff, not the file. A new hint string looks locally correct in
isolation — it is only wrong *relative to its neighbours*, and only a reader holding the
whole file sees that. In the `TP-421` rounds the bare-hint defect survived a review pass
and was caught by grepping the target file directly. The habit belongs to the author,
before the diff exists; the mechanical backstop belongs to a gate. Where a gate already
exists (`tests/test_no_bare_espalier_hints.py` for hints), it will catch you — at full
price, after the write.
