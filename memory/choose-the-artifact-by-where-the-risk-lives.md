# Choose the artifact by where the risk lives — a pack cannot answer "does this mechanism work"

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "TP-438: four review rounds, zero source changed"

**Kin:** [a-packs-prescribed-fix-code-is-a-claim](a-packs-prescribed-fix-code-is-a-claim.md) — that note says a pack's snippet is untested intent. This one says *when not to write the pack at all*. **Sole home for the artifact-choice rule**; the severity gate that decides whether the work is warranted is `docs/STANDING_PRINCIPLES.md` §16, not restated here.

Before writing a pack, name where the risk lives:

| Risk | Right artifact |
|---|---|
| Scope, coordination, reversibility, an operator decision needed before code exists | **A pack.** It is a document because the question is a judgement. |
| "Does this mechanism work?" | **Code.** A pack can only *claim* a mechanism, and this repo's canon says a claim needs driving — so every claim buys a review round. |

## The arithmetic that makes this non-obvious

A pack whose risk is mechanism is not merely inefficient — it is **structurally
unable to resolve its own central question**, and the review rounds are the price
of that gap, not a sign of thoroughness.

`TP-438` (2026-08-11) was ~90% mechanism risk. Four review rounds, ~735k agent
tokens, four *genuine* corrections, one new defect class, four new gaps — and
**zero lines of changed source**. Every correction was cheaper to answer in code:

| Round | Correction | What would have caught it |
|---|---|---|
| 1 | Derived from the wrong canon (three record-surface sets exist) | `grep` |
| 2 | `espalier/scanners/` cannot import `espalier/` at all | adding the import, running the test — ~30s |
| 3 | The parity register it proposed already existed | `grep` |
| 4 | The lock had no named constant to compare against | writing the lock and finding nothing to compare |

Four assertions, four rounds. That is the artifact's price, not bad luck.

## What this does not say

**Not "packs are overhead."** A pack is right when the risk is a judgement — and
`TP-438` had exactly one such question (a Scope-(out) override needing the
operator's sign-off), which is one line, not a 500-line document.

**Not "skip the review."** The reviews were correct every round; three of them
found real defects in my own reasoning. The failure was pointing a document-review
instrument at a question only execution can answer. Review the **diff** instead —
an agent reading running code cannot be wrong about whether the mechanism works,
and it keeps the value the rounds did deliver without the prose tax.

## The tell

You are writing sentences of the form *"this mechanism will work because
`<precedent>` does it"*. That sentence is a claim, it will be reviewed, and the
review will be right to challenge it. Ten lines of code answer it permanently.
