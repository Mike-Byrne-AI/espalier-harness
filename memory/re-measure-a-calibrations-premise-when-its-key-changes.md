# Re-measure a calibration's premise when its key changes

**Status:** active
**Linked from:** memory/ cool-store via the folder router and kin cross-links; promoted
                 2026-09-04 from the reflect candidate pass (key `70a0f18b17b0`),
                 not rowed in the `ESPALIER_MEMORY.md` hot index.
**Kin:** [premise-check-before-authoring-a-fix](premise-check-before-authoring-a-fix.md)
— that one verifies the premise of the fix you are about to write; this one
re-verifies the premise of a calibration you are NOT touching, because the key
it was measured on just moved.
[an-exemption-outlives-its-own-premise](an-exemption-outlives-its-own-premise.md)
— an exemption's reason goes false and nothing notices; a calibration's reason
goes false the same way, but its number keeps producing the right answer for
the wrong reason, which is harder to see. See "Not the same failure".
**Canon:** `docs/STANDING_PRINCIPLES.md` §6 (direction ≠ magnitude) — the calibration
measured a real direction and attributed the magnitude to the wrong cause.

A tuned constant is calibrated against a **measured effect**. That effect was
produced by the whole ranking function at the time — the score, the tie-break,
the sort's fallback order — not by the constant alone. Change any other part of
the key and the calibration's premise may be gone while its value still looks
right: the arms it was tuned on still pass, because the new key now does the
work the constant was credited with. **When you change a ranker's key, re-measure
the PREMISE of every calibration that sits on the old key, not only the arms your
change targets.**

## Attested (DEF-532 tie-break leg, 2026-09-04)

`LENGTH_NORM_ALPHA` in `tools/cc/hooks/_recall.py` is the length-normalisation
exponent. Its table recorded that alpha 0 (no normalisation) loses **108 heading
queries "to a bigger doc"**, and the exponent was calibrated against that loss.

The tie-break leg changed the sort key (`_rank_key`: score → canonical footgun →
fewer tokens → source) to fix one live tie on the naming arm. Measuring the old
table's premise under the new key:

- Under no normalisation a heading query's named doc matches **all of its own
  terms** and can only *tie* — it cannot lose strictly. Driven at full depth:
  the 115 alpha-0 misses were **114 exact ties + 1 exemplar trigger bonus, zero
  strict losses**. The path name had been breaking the ties.
- Under the new key alpha 0 **ties the shipped 0.05 on heading@1 (84.8%)**. The
  exponent's surviving, real gain is **+2.4pp on the stripped arm** plus two
  residual ties — one a `docs/FAILURE_MODES.md` coinage taking the tie on the
  canonical key by design, one a larger-vocabulary doc.
- 0.05 stays (joint peak on heading, sole peak on stripped). The value was
  right; the story under it was not.

Three instrument files had encoded "alpha 0 collapses accuracy" and every one of
them needed the **pair** (alpha 0 **and** the old key, monkeypatched back
through `_rank_key`) to reproduce what shipped:
`tests/test_recall_eval.py::TestTheInstrumentSeesTheKnownRegression`,
`test_alpha_zero_shows_the_bias_the_exponent_corrects` in the same file, and
`tests/test_recall_calibration.py::TestTheGuardWouldCatchTheRegression`. A
fourth site, the alpha table's own annotation, now carries the old-key numbers
as a parenthetical a test protects.

## Not the same failure

| | premise check before a fix | exemption outlives its premise | calibration's key moved |
|---|---|---|---|
| when | before authoring | any time; nothing triggers it | **the moment a sibling part of the key changes** |
| what is false | the reason for the fix you are writing | the reason for a carve-out | the reason a constant has its value |
| symptom | correct fix for the wrong problem | a guard quietly stops guarding | **the constant still passes; its instruments no longer reproduce the regression alone** |
| fix | verify the premise first | pin the reason to a probe | re-run the calibration sweep under the new key and rewrite the table |

## The check

Before landing a change to any part of a ranking, scoring or sort key:

1. List every constant whose table or comment cites a measurement taken on the
   old key (grep the module for the number, not the name).
2. Re-run each calibration's own sweep under the new key. Compare the losing
   arm's *mechanism*, not only its rate: ties vs strict losses, bonus vs score.
3. Rewrite the table with the new numbers and keep the old ones as an annotated
   pair (constant + old key), so the instruments that pin the regression name
   both halves of what produced it.
4. Check whether any test reproduces the regression through the constant alone.
   If it does, it is now pinning a story, and it will red the day someone
   removes the constant for the right reason.

## Generalisation

Any tuned number whose evidence is "the arms got better when I set it" inherits
the rest of the function as an unstated co-author. Ranking keys, thresholds
with a fallback order, weights in a sum where another weight also changed: the
constant's credit is only as clean as the isolation of the measurement that
awarded it. Re-award the credit when the co-author changes.
