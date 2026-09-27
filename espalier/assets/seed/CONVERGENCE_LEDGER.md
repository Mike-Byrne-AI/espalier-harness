# Convergence ledger

**Status:** active · **Appended by:** the convergence-critic (final stage of every
review) · **Read with:** `memory/convergence-review-protocol.md`

One curated row per convergence-review **round**. This is the cross-round sight the
fan-out review system otherwise lacks: the yield trend, premature "converged" calls,
findings refuted in one round and confirmed later, and slow-drip *classes* only visible
with the whole series in view. It exists because reconstructing that view from memory each
round is exactly the unreliable self-report the review method warns against.

## Where this sits (not a rival to the other two stores)

Three stores, three altitudes; the convergence-critic reads all three:

| Store | Granularity | Written by | Tracked? | Holds |
|---|---|---|---|---|
| `reports/<scaffold>-findings.md` | per **finding** | persist stage | no (local) | dedup corpus (SURVIVED + REFUTED) |
| the per-run ledger (written under cc/ by the persist step) | per **run** | `finding_ledger.append_summary` | no (local) | structured raw: scalars + survivors |
| **`memory/CONVERGENCE_LEDGER.md`** (this) | per **round** | convergence-critic | yes | curated narrative: coverage map, open leads, convergence read |

This file is the interpretive layer; it does NOT duplicate the other two. It **references**
the corpus and reads the per-run JSONL (`espalier.finding_ledger.read_ledger`) for the
yield/recurrence numbers so those are *computed*, not recalled.

## Rules

- **Append-only.** The critic adds a new row; it never rewrites a prior row (history is
  evidence: a "converged" call that a later round overturns is a signal worth keeping).
- **Read by trend, not count.** Blocker/major yield and the severity trend across
  *independent* rounds is the signal; the raw count never reaches zero.
- **Gate the word "converged."** Permitted ONLY when a corpus-blind pass produced the null
  AND the coverage map has no high-value never-covered surface. Otherwise the honest label
  is **"coverage-null, not convergence-null."**
- **Append-only includes CORRECTIONS. Read the whole row before quoting any field.** A row
  may end with a `⚠ CORRECTED <date>` bullet that supersedes the fields it names; the wrong
  field is left standing so the record shows what each round actually reported.
- **A `file.js:NN` in a row is a PRE-FIX line number.** Rows cite the code as it stood when
  the round ran.

## Row schema

```markdown
### Round <N> — <date> — <lens/tangent> — `<workflow id>`
- **Instrument:** <lane count · scoring frame · harness revision / known harness defects · saved-workflow file or "ad-hoc">
- **Lanes/modalities:** <list>
- **Surfaces covered:** <list>
- **Surfaces NOT covered (carried forward):** <list>
- **Yield:** blocker <n> / major <n> / minor <n> / nit <n> / refuted <n>
- **Refutation-recurrences:** <findings re-refuted from a prior round → attractor or corpus gap>
- **Cross-round classes:** <a pattern that only appears when aggregating rounds>
- **Open leads (→ next round):** <the critic's highest-value un-run probes>
- **Convergence read:** converged-within-frame? / out-of-frame gaps? / coverage-null vs convergence-null
- **⚠ CORRECTED <date>:** <optional, appended later: names the fields above it supersedes and the oracle it was re-derived from. The superseded text stays.>
```

> **Why `Instrument:` is mandatory.** A round-over-round yield comparison is only meaningful
> across a FIXED instrument. Record the instrument, or a later reader will attribute an
> instrument delta to the code.

## Rounds

_No rounds yet. The convergence-critic appends the first row below this line._
