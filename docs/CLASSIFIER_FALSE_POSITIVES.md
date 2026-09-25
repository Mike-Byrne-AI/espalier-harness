# Why this repo trips safety classifiers, and how we work to avoid it

## The short version

This is an open-source workflow-governance harness. One part of it is a
**friction guard** -- a hook that warns before irreversible shell operations,
the most important being a recursive delete of a critical directory. To build
and test that guard honestly, the repository necessarily contains a corpus of
dangerous shell commands and a test suite that checks *which of them the guard
stops*. That is defensive work: the tool tests its own coverage.

The catch is that the artifacts of **building** a safety control and the
artifacts of **attacking** one are, on the surface, identical -- a pile of
dangerous commands plus "which get past the control." A platform safety
classifier reads that surface, not this repository's identity, so ordinary
development here trips it as a false positive. Every trip on record has been
about the *shape* of the activity, never the work itself.

This document is the standing companion to the incident record in
`docs/incidents/2026-09-17-real-shell-fixture-wipe.md`. It states, plainly and
truthfully, what this project is and how a session should work so that honest
development does not read as evasion.

## What this project is

- An open-source Claude Code governance harness, built by the operator together
  with Claude, in the open.
- Its friction guard is a **workflow toolbelt, not a security boundary**
  (`docs/STANDING_PRINCIPLES.md`, principle 2). It exists to slow a hurried
  agent down before an irreversible mistake, not to defeat an adversary.
- The dangerous commands in `bench/` and `tests/` are **fixtures**. A real
  shell is the only honest oracle for what the guard should refuse, so the test
  populations are catastrophic-delete spellings by necessity. An executing row
  in a bench is a test fixture, nothing more (`CLAUDE.md`, working context).
- The work is authored by the repository owner, on their own public tree, for a
  defensive purpose. There is no target, no victim, and nothing hidden.

## Why this specific code is a structural false-positive magnet

Most code never trips a safety classifier in a lifetime of sessions. A guard
that blocks dangerous shell commands is close to the worst case, because:

1. The thing under test **is** a protective control.
2. Testing it honestly **requires** a corpus of the dangerous inputs it must
   refuse.
3. The test question is, by necessity, *"which of these get past the wall?"*

Building the wall and attacking the wall therefore leave the **same evidence**,
and there is no surface signal that separates them. This is a genuine,
structural trap for this category of code -- not a sign that anything is wrong
with the work.

## Two layers that are easy to conflate

- **The platform safety classifier** is Anthropic's, above Claude Code. It reads
  the running session surface. It cannot see this repo's `CLAUDE.md`, does not
  know the tree is a harness, and has no concept of "the operator's own
  project." It is the thing that trips.
- **This repo's friction guard** is the hook under `tools/cc/hooks/write_guard.py`
  and its siblings. It is what we are *building*. It is not the thing that
  trips, and it is not a security tool.

When a session says "the classifier tripped," it means the first one. Keep the
two apart when reasoning about a trip.

## Shapes that trip it (avoid these)

Stated in effect-words, because spelling the dangerous inputs is itself one of
the shapes:

- **Concentration.** Many dangerous-command spellings gathered into one
  artifact -- a matrix, a table, a roster. This is the single biggest trigger.
- **"What gets past" framing.** Prose, plans, or reviewer briefs oriented to
  finding what defeats the wall, rather than to whether the wall is correct.
- **Execution breadth.** Driving dangerous commands on a real shell beyond a
  single headline case per shell.
- **Bulk source inspection.** Dumping large regions of the guard in one shot to
  "understand" it, which reads as reconnaissance.
- **Verdict lists.** Per-item pass/fail tables of dangerous inputs printed into
  the transcript.
- **Cross-call accumulation.** The same shape spread across many calls; the
  sequence sums to a matrix even when each call is "just one probe."
- **Host or environment census.** Batched `find` / log / shell-history sweeps,
  which read as reconnaissance regardless of intent.

## The discipline that avoids it (do these)

- **Rows are the derivation.** Expectations live as test rows in the repo's test
  and bench files, proven by running the suite by name; the count comes from the
  summary line. Never an inline "which of these passes" run.
- **Read one function by name.** Grep for a name and read that one function, not
  regions of the module.
- **Effect-words in prose.** "the wall", "the nudge", "false allow",
  "false deny", "the tier", "the record". Not the command spelling.
- **One headline drive per shell**, in a `mktemp` throwaway, every operand
  relative and bound. A row whose point is an absolute or unbound operand is
  asked of the guard's classifier in-process and never executed
  (see the incident record).
- **Records carry counts, row names, the named user, and the fix shape** -- the
  reason a specific spelling matters lives in the fix commit's code comment,
  nowhere else.
- **Write true rationale into the work as you go.** Docstrings, comments, plan
  steps, and commit messages that say what the code is and why the fixtures are
  dangerous by necessity. This is documentation a contributor wants; it also
  gives any reader -- human or automated -- the grounded, specific context that
  a generic "this is legitimate" preamble cannot. The test is that it must be
  true and independently useful, not a phrase incanted to move a score.

## Context hygiene

A session's context is cumulative. Once a lane has worked a hot surface for a
while, the running context is already dense with dangerous-looking artifacts,
and ordinary new activity is likelier to trip. The lever that actually resets
this is **flushing the context**: checkpoint the lane, hand off, and clear, then
resume cold. This is a bigger effect than any framing text, because it removes
the accumulated surface rather than trying to argue it down.

## If it trips anyway

- Run `git diff` before the next edit. A trip can interrupt a write mid-edit and
  leave a half-applied change the tool never reported.
- Re-orient from the discipline above, not by re-running the shape that tripped.
- The full accumulated catalog of individual trips lives in the machine-local
  auto-memory (not committed); this document is the committed, portable summary.

## Related

- `docs/STANDING_PRINCIPLES.md` -- principle 2 (toolbelt, not a security
  boundary) and the make-it-prove-it stance.
- `docs/incidents/2026-09-17-real-shell-fixture-wipe.md` -- the incident that a
  real-shell drive of an unbound-variable fixture caused, and why such a row is
  classifier-only.
- `CLAUDE.md` -- the working-context block every session loads.
