# The stateful oracle consumes what it measures

**Status:** active
**Linked from:** [complacent-oracle](complacent-oracle.md) (kin cross-link); memory/ cool-store, reached via the `memory/CLAUDE.md` folder router — not rowed in the root `ESPALIER_MEMORY.md` session log.
**Kin:** [complacent-oracle](complacent-oracle.md) — the inverse case; see "Not the same failure" below.

An oracle that **mutates state as a side effect of being consulted** will lie to
any differential that consults it once per side. The first consultation changes
the world the second one measures, so the measurement records the *act of
measuring* rather than the difference under test.

The tell is not a wrong-looking number. It is that **the number changes when you
run the harness again** — which you only discover if you run it again.

## The mechanism

A differential asks: *does the population behave differently before and after
the change?* It drives OLD, then NEW, per item. If consulting OLD discharges a
one-shot piece of state, NEW sees an already-discharged world and reports a
difference that does not exist. Every phantom points the same way — toward
"the change did something" — because the *earlier* side is the one that pays
the state cost. **The artifacts are therefore biased toward confirming the
change worked**, which is the worst possible direction for them to lean.

## Attested (three independent instruments, one session, 2026-08-03)

`tools/cc/hooks/_speedbump.py` checkpoints are **deny-once-then-allow** and
persist to `.espalier-state/`.

1. A pack-review agent's first matrix pass was corrupted this way; it caught it
   and warned in its report.
2. A hand-built probe pre-empted it by driving each row twice.
3. A **whole-population differential harness** did not, and reported **111
   transitions on its first run and 80 on its second** — 31 phantoms, all
   pointing the same way. The warning had been *written down one step earlier by
   the same author* and still did not prevent it.

That is the durable part: writing the caveat down did not stop it. Re-running
the harness did.

## Not the same failure as the complacent oracle

They are opposites, and the responses differ:

| | complacent oracle | stateful oracle |
|---|---|---|
| symptom | **consistent**, plausible, wrong | **inconsistent** between identical runs |
| why it hides | consistency earns trust, trust suppresses the audit | you only ever ran it once |
| the check | compare against an **independent** landmark | compare the tool **against itself**, twice |

A stateful oracle is *detectable for free* — it disagrees with itself — but only
by someone who looks twice. Filed separately so the response is not blurred:
"find another oracle" does not fix it, and "run it twice" does not fix a
complacent one.

## The check

- **Any differential harness's number is not evidence until the harness has been
  run twice and agreed with itself.** Report the agreement, not just the number.
- Drive each item **twice per side** and take the **stable** verdict, rather than
  resetting state between items — resetting is easy to get half-right and hard
  to prove.
- Classify a verdict by its **reason**, not by a deny/allow bit: a one-shot
  checkpoint and a real deny are the same bit and different facts.
- Before building a differential, ask: *does consulting this thing change it?*
  Speed-bumps, rate limiters, caches, "first-run" banners, session flags,
  once-per-session advisories and anything writing to a state directory all
  qualify.

## Generalisation beyond this repo

The property is not "speed-bumps are awkward" — it is **consulting an oracle
that has a side effect on the thing measured**. Any once-per-session advisory,
cache warm-up, or first-invocation banner has the same shape. The fix is always
the same: measure the *stable* state on both sides, and prove stability by
re-running rather than by reasoning about it.
