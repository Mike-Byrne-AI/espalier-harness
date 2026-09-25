# Calibrate a new enforcement contract against the live population

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "Calibrate an enforcement contract against the live population"

Building an authoring-time enforcement contract **by analogy** to an existing one
has three traps. TP-283 hit all three in one session while mirroring
`test_every_subprocess_test_is_slow_or_exempt` to enforce a `full_tree` marker.

## 1. Mirror the model's data source, not just its shape

The subprocess model **imports** `_SLOW_FILES` from conftest — it does *not* scan
test source for a "slow" marker. The first draft planned to source-scan for
`full_tree`, but that marker is applied at **collection** time via
`_FULL_TREE_NODEIDS` and appears in **no** test file's source. A source scan
finds nothing and reds everything. The 0-A review caught the false premise.

> When copying a contract, copy *where it reads the enforced attribute from.*

## 2. Calibrate against the live population, not the spec

A throwaway probe running the candidate detector over all `tests/test_*.py` took
a naive version from **30 false positives → 0**. The distinguishing signal — a
dev-only path anchored at `REPO_ROOT` vs one under `tmp_path` — was **invisible
from the spec**; only the live run showed that tmp-fixture tests, which build
export-*shaped* paths, dominate the population.

Also: pick the **narrowest correct single-owner predicate**.
`export_ignore_patterns` (what `git archive` prunes — which is what the marker is
*about*) beat the broader `is_release_excluded`, which drags in gitignored
runtime state and added 4 more false positives.

## 3. "The pre-state is clean" is itself a claim

The probe flagged `test_fan_out_findings` — **genuinely export-fragile** (an
unguarded read of the export-ignored `docs/known-findings.md`). It was latent
only because it is marked `slow`, and the release matrix runs `-m "not slow"`, so
the matrix never exercised it. The contract earned its keep on its first run.
([[a-latent-issue-that-just-bit-is-a-class]])

## How to apply

For any new mechanical contract, **write a probe that runs the candidate detector
over the real target set before finalizing.** Require zero false positives on the
current tree, and treat every flagged item as a possible **real miss to
adjudicate**, not as noise.

**2026-09-11, the same measurement run on a widening (§C7).** The pack
parser's none-bullet rule was widened from `(none` to any bare `none`/`no`
first word so eight archived spellings would read as declaring nothing; both
reviewers drove the bare `no` swallowing `- No longer generated: `x.py`` and
`- No-op wrapper `a.py::f` removed`, with the diagnostic that names dropped
bullets silenced too. The narrowed twin (`none`, `no new`) was proven
behaviourally identical to the wide rule on all 262 packs before it landed: the
live population said the widening bought nothing and cost two silent drops.
Calibrate a widened predicate the way this note calibrates a guard, and prefer
the narrowest rule the population cannot tell apart from the wide one.

**2026-09-20, the same run on a new TOOL rather than a detector (`TP-452` 1-B).**
A transform calibrates the same way, and a hand-built fixture is not the live
population. All three code-review blockers on the ledger assembler were shapes the
real 1.4 MB `task-packs/FORWARD_LEDGER.md` carries and the fixture did not: nine
member rows whose id cell holds a second id (`live_member_ids` returned 140 against
`derive()`'s 149, so a keep would have deleted the co-id), four classes MIXED on one
axis whose rows carry six cells (the first cut stripped them — five unrepairable
drift entries), and section-one rows whose id cell is the *second* cell. A
two-verdict dry run over the real file had been driven and came back green, because
its verdicts touched none of those rows: **a smoke run over the live artifact proves
the parsers at scale, it does not prove the branches.** Drive one verdict of every
kind the tool can emit BEFORE the reviewers see it, then give the fixture every shape
that drive found — all three blockers were reachable from the author's own chair.

Related: [[skipif-to-marker-drops-filterless-consumers]] (the marker lives in
conftest, not source) · [[a-packs-prescribed-fix-code-is-a-claim]] ·
[[completeness-gate-must-discover-its-population]] (the coverage-gate dual: probe the
live population, then subtract only a *backed* residue so the discovery doesn't self-red)
