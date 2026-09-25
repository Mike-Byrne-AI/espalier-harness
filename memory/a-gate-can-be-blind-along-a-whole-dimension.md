# A gate can be blind along a whole dimension of its input

**Status:** active
**Linked from:** [completeness-gate-must-discover-its-population](completeness-gate-must-discover-its-population.md) (kin cross-link); memory/ cool-store via the folder router.
**Kin:** [completeness-gate-must-discover-its-population](completeness-gate-must-discover-its-population.md)
— that one is *a member is missing from the list*; this one is *a whole axis is
missing from the corpus*, and derivation does not fix it. See "Not the same failure".

A gate can have a **complete, correct, fully-derived population** and still be
structurally incapable of observing the property you are about to change —
because every member of that population is identical along the axis that
matters. Nothing is missing. The corpus *is* the whole corpus. It simply has no
variation in the dimension under test, so the gate returns the same verdict
before and after, and that verdict is not evidence in either direction.

This is worse than an incomplete gate, because an incomplete gate at least has
a plausible fix ("derive the population"). Here the population is already
everything there is, and the number it produces looks exactly like a pass.

## Attested (TP-414, 2026-08-03)

`bench/run_benchmark.py` is this repo's **declared non-negotiable gate** for the
anti-self-disable floor — the pack's own words: *"any drop is a BLOCKER, not a
nit; a delta here is a bypass, not a papercut."*

Measured across the whole corpus — **53 files / 168 canonical attempts / 83 Bash
commands** — the number whose extraction signature changes under a
command-position anchor is **ZERO**. Every corpus payload is a *bare
string-start invocation* (`install /tmp/x <zone>/y`,
`ln -sf /tmp/forged.json cc/blueprints/…`). Not one uses a substitution, a
subshell, a brace group, `eval`, a wrapper, or a shell keyword.

Consequence, measured twice against two different implementations: the bench
reported an unchanged **153/153 + 15/15** while the change moved **90 verdicts**
— and would have reported the same number over a first-draft anchor that opened
**18 protected-zone bypasses**.

**The corpus is complete for the axis it was built for** (which *verb*, which
*zone*) and **empty along the axis of *where the verb sits in the command***.

## Not the same failure as an undiscovered population

| | undiscovered population | blind dimension |
|---|---|---|
| defect | a member exists that the list never enrolled | every member is identical along the axis under test |
| symptom | new sibling passes silently | **the number does not move at all**, before or after |
| fix | derive the population mechanically | **author new KINDS of input**; derivation changes nothing |
| tell | list literal in the test | a differential over the whole corpus yields **0 changed** |

Deriving `bench/corpus/*.json` mechanically would enrol all 53 files and change
nothing, because the gap is not membership.

## The check

Before citing a gate as evidence for a change, run the **differential over the
gate's own population**: apply the change and count how many population members
alter their verdict.

- **0 changed → the gate cannot see this class.** Its green is a *prediction*,
  not a verification. Say so out loud, in the commit and in the record, because
  the number is otherwise indistinguishable from a real pass.
- The fix is to add input *shapes*, not input *counts* — and to add them in a
  separate change from the one being gated, or the gate's number becomes
  un-attributable.

## Generalisation

Any corpus assembled to answer one question is liable to be uniform along
another. A fuzz corpus of long inputs may have no *short* ones; a permissions
corpus of authenticated requests may have no anonymous ones; a
verb-and-target corpus has no *positions*. **Ask what every member of the corpus
has in common — that shared property is the dimension the gate is blind to.**

## Sibling blindness: a differential is drawn from what exists, not from what an adversary builds

The same shape recurs one level up, across *instrument classes*. Closing the
command-position class ran three instruments over one change:

| instrument | population | found |
|---|---|---|
| 179-row shape matrix | wrappers around a known-good command | the 10 target false positives |
| 1182-command differential vs a pristine HEAD tree | commands that already exist in tests, corpus, and ordinary use | **0 regressions** |
| adversarial pass | routes constructed to defeat the new grammar | **12 genuine bypasses** |

The matrix and the differential were **both clean while twelve protected-zone
writes were allowed**. Neither population was wrong; both were drawn from
commands that *already existed*, and none of them exercised a carriage return, a
`case` arm, a leading redirection, `setsid`, or an alias-suppressing `\cp`.

**A clean differential over a large population is not evidence that a guard
change introduced no bypass.** It is evidence that nothing *already written*
broke. Only an adversary hunting new routes finds new routes — so an
enumeration-shaped guard needs an adversarial pass as a distinct step, and its
findings need encoding as rows or the enumeration silently loses them.

## A one-sided probe is the same blindness, authored into the probe function

The two attestations above are corpora that *happened* to have no variation on
the axis under test. The cheaper and more common version: a two-sided relation
whose probe resolves **one side by construction**, so the other side is not
merely absent from the corpus — it is unreachable by the guard, and the probe's
own docstring says so.

**Attested (2026-08-16).** A census guard exists to enforce *"no mirror row may
exist without an edit-time advisory."* Its probe helper is documented as
returning *"a real SOURCE-side file this row mirrors."* Every assertion in the
class therefore drove the source side of all nine rows, and the mirror side was
untestable by construction. Four separate advisory rules answered *"run the
sync"* on the generated side — the side that sync **overwrites** — so following
any of them deleted the edit and exited 0. The class survived five convergence
rounds with the census guard green throughout, and the three rules that were
*correct* were correct only because their individual authors happened to
hand-write a mirror-side negative case.

**The tell is a sentence, not a number.** Read the probe's own description. If it
names a side, a direction, a mode, or a role — *"a source file"*, *"a valid
request"*, *"the enabled path"* — that adjective is the dimension the whole guard
is blind along, and it is usually there because resolving the other side needed
one more line the author did not need at the time.

**The fix has two parts, and the second is the one that rots.**

1. Drive **both** sides: resolve the counterpart and assert the property there
   too.
2. Give the counterpart resolver **its own floor**. If it ever returns `None`, or
   returns the input unchanged, every row silently reverts to being driven on the
   side already covered — the original blindness, reintroduced inside the fix
   written to close it, with nothing red. Assert that the resolved side actually
   differs from the probe before using it.

## A two-arm derivation gates omission in one arm and contradiction in the other

**Attested 2026-09-08.** A derived audience count was closed-world on *spelling*
— it named every row carrying no token the tool recognised — and open-world on
*assignment*: a row that inherited one classification while its own cells
asserted another was counted by the class and printed by the row, so a single
edit to one class-index cell moved the headline figure from 55 to 80 with every
gate green. Both reviewers drove that second arm only after the first was
reported green. **Name which direction a derivation gated, and give the other
direction a witness — here the contradicting row's own cells — rather than
calling the number verified.** The arm that catches an *omission* is never the
arm that catches a *contradiction*, and a green on the first is silent about
the second.

Kin: the per-member floor in `docs/FAILURE_MODES.md` §13.34 — a global count
cannot see this either, because the rows still examined keep the total up.
