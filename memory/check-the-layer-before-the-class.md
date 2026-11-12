# Check the layer before the class

**Status:** active
**Linked from:** root `CLAUDE.md` Core Rule 12 · `docs/STANDING_PRINCIPLES.md` §20 ·
                 [[fix-the-class-not-the-instance]], which this note precedes; not rowed in
                 `ESPALIER_MEMORY.md` (at its cap).
**About:** `tools/cc/ledger_row.py::FIVE_QUESTIONS`, the questions' deployed text, which
           `tests/test_ledger_lineage.py::TestTheFiveQuestions` pins to the list below.

**The class.** A fix whose layer cannot reach its goal passes every gate. The row states
the cause at the reader; the class question answers with a bigger fix in the same layer;
the reviewer finds the next sibling; the plan builds what it is handed; §16 names the user
truthfully. None asks if the layer can reach the job at all.

**Two kinds of move.** *Consolidation* turns many sites into one chokepoint or one derived
list (§14, §18): it stops siblings spreading, and defects keep arriving at the new site.
*Re-targeting* changes what is checked: the effect instead of a prediction of it, the
producer instead of every shape at the consumer, behaviour instead of a name. It is rarer
here. The instances, and the caveat that their class titles were written once the fix
shape was known, are in `task-packs/TP-475-know-when-work-is-worth-doing.md`'s Motivation.

## The five questions, asked before the class question

1. **State the job without naming the mechanism.** If the job can only be written in the
   mechanism's own words (spellings, shapes, anchors, row forms), the fix is aimed at the
   mechanism, not the job. "Harness files do not change mid-session without the operator
   knowing", not "the reader must handle form X".
2. **Does the fix observe the effect, or predict it from a representation?**
3. **Is the input closed and ours, or open and someone else's?** Open input plus prediction
   is enumerating badness: move the check. Closed input we own: own the producer and make
   the consumer strict. Except where the effect cannot be undone (a delete, a push, a
   release, a secret read): no later layer can help there, so the prediction stays, and
   question 4, asked once for the whole job, decides which forms are work. The exception
   is the operator's wording (2026-10-08): without it the questions said "move the check"
   for jobs no layer can take.
4. **Would a slip plausibly produce this instance?** If not, it is a declared limit, not
   work. Where a whole job must stay in a predicting layer, ask this once for the job, not
   once per row. That answer is a coverage contract (§16; `TP-476` decision C3 writes the
   guard's).
5. **Was this already moved once, and are defects arriving at the new site?** Then the move
   was consolidation, and the next one is re-targeting.

## The tells, and where the questions are printed

A chain of siblings on one job, a cluster of standalone rows on one site family, and a
defect recurring at a site already consolidated. `tools/cc/ledger_row.py` prints the
questions at each: the chain and cluster advisories at filing, `lineage <id>` at plan time
(`/implement-task` step 1, `/implement-pack` step 0-A), and the `class` verb when it opens
a class. The two reviewer bodies ask the layer question of every fix. None of it refuses:
a gate on a count teaches the filer to suppress ([[gating-on-count-manufactures-findings]]).

**Counter-warning.** A move can relocate a defect rather than close it
([[a-fixed-fail-open-can-move-rather-than-close]]): re-run the whole oracle after a
re-targeting, as after any fix.

**Worked instance:** `TP-476` (guard by location) is the move these questions propose for
the guard's parser rows. It is proposed, not proven, until its wave C has struck rows and
no new stream follows at wave A's layer. The blind back-test (`TP-475` Task 0-C) showed
only that the questions do not route everything away.

**Origin: the operator, 2026-10-07**, asking how to tell work "worth doing" from "banging
against a brick wall", then naming the tell: patchwork mode, where sibling sites keep
popping up or many fixes chase the same issue, because "sometimes we are targeting 'the
symptom' not 'the real issue'".
