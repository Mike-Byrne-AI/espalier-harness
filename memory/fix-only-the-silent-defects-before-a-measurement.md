# Before a measurement, fix only the silent defects

**Status:** active
**Linked from:** `docs/STANDING_PRINCIPLES.md` §1 (make it prove it) and §7 (fast
earns scrutiny); sibling of
[`docs/sharp-edges/source-tree-is-not-an-artifact-oracle.md`](../docs/sharp-edges/source-tree-is-not-an-artifact-oracle.md)
and [`the-measuring-instrument-is-a-claim-too`](../docs/sharp-edges/the-measuring-instrument-is-a-claim-too.md)

**What it is.** When a real measurement is about to run — an install rehearsal, an
adopter walk, a dynamic-execution round — the question *"which known defects should
I fix first?"* has a much narrower answer than it feels like it has. A walkthrough
observes **what happens**. It is structurally blind to **what did not happen**. So:

> Fix the defects whose signature is **absence or a false all-clear**.
> Leave every defect that produces visible wrong output, friction, or a crash —
> that is what the measurement is *for*, and pre-fixing it swaps measured
> evidence for an unrehearsed edit in the artifact under test.

A real defect is not automatically a pre-req. Conflating the two is the default
error, and it is expensive in both directions: it delays the measurement *and* it
ships untested changes into the thing being measured.

## The trap inside the rule

The rule sorts by *consequence*, and consequence is not readable from the code that
produces it. Attested 2026-08-16d, in the same hour the rule was written:

`DEF-427` — `merge-settings` on a repo with no harness deployed wires ten hook
events at twelve nonexistent script paths, exits 0, and prints **"Enforcement is now
active."** That reads as a textbook false all-clear, and it was nominated as the
single strongest fix-first candidate on exactly that basis.

Driven, the consequence is **inverted**. A missing script exits 2; per the hook
protocol, exit 2 on PreToolUse *blocks*; the `*` matcher points at `write_guard`. So
the next session in that repo hard-blocks **every tool call**, naming the missing
file. It fails **closed and maximally loud** — `doctor` flags it, re-running `init`
repairs it, and `docs/known-findings.md` already recorded the correct consequence.
No wrong belief can survive to become a conclusion.

The nomination came from reading the **print statement** and inferring the
operator's belief from it. The oracle answered *"what does the CLI say?"* when the
question was *"what does the operator end up believing?"* — the proxy-oracle shape,
applied to a message instead of an artifact.

## How to classify one

Do not ask whether the message is wrong. Ask:

> **Drive the next step. Can a wrong belief survive it?**

If the very next thing the operator does detonates loudly, the defect is loud
regardless of how misleading its message reads in isolation. Only when the wrong
belief *persists* — nothing contradicts it, no gate fires, the tree looks fine — is
it the silent class that earns a fix before the measurement.

Two shapes that reliably do qualify, because absence is unobservable:

- **A nudge that never fires.** `doctor`'s `/analyze` grounding prompt is
  unreachable on both sides of `init` — pre-init the status gate skips the block,
  post-init the seeded `docs/CONVENTIONS.md` exceeds the threshold. A rehearsal
  cannot notice a prompt that was never shown.
- **A guard satisfied by an impostor.** See `docs/FAILURE_MODES.md` §9.8: a
  resolvability probe that returns true for a stub answers a different question than
  the identity one it is standing in for.

## Receipt

2026-08-16d, pre-Windows-rehearsal readiness review. Nineteen findings were argued
as material across five driven lanes; **two** survived adversarial refutation, and
exactly one was fix-first (a 21-commit push, so the second machine would clone the
harness actually under test). Of the seventeen that fell, most fell to this
distinction rather than to being wrong on the facts — `/preflight` really does
hard-fail with `ruff` on a Go repo, the fingerprint really does count Espalier's own
seeded docs as the adopter's. Both reproduce. Neither gates the trip.
