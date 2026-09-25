# Ask whether the RULE is wrong, not just the detector

**Status:** active
**Linked from:** `task-packs/FORWARD_LEDGER.md` §C5 · §C7 ·
                 `scripts/release_check.py::check_version_consistent` ·
                 [[classify-the-surface-before-measuring-it]] ·
                 [[fix-the-class-not-the-instance]] ·
                 [[a-live-artifact-test-must-not-pin-its-contents]]

A detector keyed on a shape the artifact does not have can be hiding a **mis-specified
invariant**, not merely a stale regex. Before repointing the matcher at the shape the
file actually uses, ask what the gate would *say* if it could see — on the tree in
front of you. If the honest answer is *"it would fail on a legitimate tree"*, the
specification is the defect and repointing the detector ships a false alarm.

## The failure it names

§C7's prescribed fix is an **engagement floor**: every pattern that governs a named
artifact carries a test asserting it matches ≥1 member, so a matcher can never again
sit green over a corpus it does not engage. That prescription is right most of the
time. `DEF-591` is the case where it is wrong, and following it would have broken the
trunk.

The release gate asked whether `[Unreleased]` held anything substantive and decided by
counting `### ` subheadings. `CHANGELOG.md` labelled its groups `**Bold**` and had never
contained an h3, so the check matched nothing on every tree that has ever existed. The
measured population was zero — textbook §C7, and the obvious repair is to count what the
file actually uses.

Driving it first is what saved it. That check runs on **every push to the trunk**
(`release.yml`'s `release-check` job carries no `if:`, and the workflow triggers on
`push:[main]` and `pull_request:[main]`), while `[Unreleased]` holds the development
record between releases **by design** — the live dated section says so in as many words:
*"See [Unreleased] for the headline 0.8 feature set staged since 0.7."* A sighted
emptiness check reds the trunk for the entire pre-release period. The gate was not weak;
it was asserting something that was never true of this artifact.

## Why the blindness is what let the wrong rule survive

**Nobody notices a rule that never fires.** A mis-specified invariant behind a working
detector gets caught the first time it fails on a legitimate tree — someone argues with
it and the spec gets fixed. Behind a *blind* detector it is invisible, indefinitely: the
gate reports success, the docs keep citing it, and the specification is never tested
against reality even once. So shape-blindness and spec-error are not independent
defects that happened to coincide; the first is the mechanism that preserves the second.

Expect this pairing. When you find a detector that has matched nothing for a long time,
the rule behind it has been unexamined for exactly as long.

## The diagnostic

After measuring the trigger token's population at zero, do **not** go straight to the
fix. One extra question:

> If this gate could see, what would it say about the tree in front of me — and would
> that be right?

Three outcomes:

1. **It would correctly pass.** The rule is fine. Repoint the detector, add the
   engagement floor. This is the common case and §C7's prescription applies.
2. **It would correctly fail.** You have found a live defect the gate was meant to
   catch. Fix both.
3. **It would fail on a legitimate tree.** The specification is the defect. Do not
   repoint the detector — you would be shipping a false alarm into a gate people trust.

For (3), look for the invariant that is **true on every tree** and catches the same slip
from the other side. Here, *"the backlog must be empty"* — only owed at the release cut,
and the cut is not detectable from the tree — became *"the section you just dated must
not be empty"*, which holds on every tree, catches the same operator mistake (version
bumped, header minted, notes never moved), and guards the half that actually reaches
users: a published `## [0.9.0]` with nothing under it tells a reader nothing changed.

## What the re-specification costs, and saying so

Asserting from the other side is rarely a perfect substitute. The re-specified gate does
**not** verify the fold is *complete* — that remains owed and is filed rather than
silently dropped (`DEF-594`). Name the residue explicitly, in the code comment and in
the tracker, or the next reader will assume the new invariant covers everything the old
one claimed. A doc citing the old guarantee needs correcting in the same commit;
`CONTRIBUTING.md` claimed this gate "enforces all four" surfaces and had to be narrowed
to two.

## When NOT to reach for this

This is not licence to re-specify any gate you find inconvenient. The trigger is
narrow: a detector with a **measured** population of zero, plus a driven demonstration
that the sighted form fails on a tree that is legitimately fine. Absent that
demonstration, the engagement floor is still the right fix and this note does not apply.
