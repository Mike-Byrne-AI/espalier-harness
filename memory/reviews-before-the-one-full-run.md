# Reviews before the one full run

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "Reviews before the one full run"

Order of proof for a change that touches a trigger surface: **targeted tests →
both reviewers dispatched in one message → edits frozen until both reports are
in → ONE fix batch → ONE full run → commit.** Never start the full suite "for
early signal" while the reviewers are out.

## Why

Measured on 2026-09-06, two lanes, one operator, an 8 GB machine:

- Every lane that week produced review findings. A full run started before the
  reviews return is therefore stale with high probability the moment they land.
  Two runs of about nineteen minutes each were started early and killed; neither
  had surfaced anything the targeted proof had not.
- Both times the code-reviewer's fixes were applied while the failure-mode
  reviewer was still reading, and it had to re-derive its findings against a
  tree that had moved under it. Parallel dispatch is worth keeping for
  wall-clock; the edits are what must wait.
- The stale runs also competed with the reviewers for the machine.

## How to apply

1. Run the targeted proof. Drive the adversarial inputs yourself first (the
   other spelling, the other platform, the remedy on the edited copy).
   Run this repo's enumerator pins here too, in their own batch rather than
   beside the dispatch (`tests/test_test_suite_contract.py
   tests/test_marker_taxonomy.py tests/test_portability_contract.py`, about
   seventeen seconds, plus the four in
   [[four-gates-the-targeted-proofs-never-show]]): a pin that reds after the
   dispatch cannot be fixed without breaking step 3's freeze -- two sat red
   under the frozen tree for a whole review on 2026-09-13, and
   `/implement-task` step 6 had said "before dispatching" since 2026-09-06.
2. Dispatch `code-reviewer` and, for a hook / gate / command / agent / skill
   change, `failure-mode-reviewer` in the same message. The failure-mode
   reviewer's "fires AFTER code-reviewer agrees" is a reading order, not a
   wall-clock one: read its report second. Brief both on the live population,
   not the fixture: ask each to census the real corpus the change will meet --
   every pack, every spelling a parser will see, every deployed copy of the
   file -- and to report how many members it examined. Every review on
   2026-09-11 reached a hole the diff could not show, and each did it by
   counting the real corpus rather than driving a scratch tree.
3. Do not edit while they run.
4. Land the accepted findings from both as one batch; re-run the targeted proof.
5. `git add -N` every new file (the `git ls-files` gates cannot see an
   untracked one: seven unpinned encodings shipped in a commit this way on
   2026-09-06, green in the full run before the commit and red in the first
   contract run after it). Then run the tier the surface earns, once --
   `python scripts/proof_tier.py` computes it and names the untracked files:
   no file under `tools/cc/` and no `.py` under `espalier/` outside its
   byte-mirrors → `pytest -m contract -q` (164 s serial, measured
   2026-09-06; every contract that caught that day's batch is in it, and all
   of them are also `slow`, which is why the fast slice never felt safe);
   a file the pull-recall corpus reads (`memory/`, the two catalogs,
   `docs/sharp-edges/`, the principles) → the contract slice and then the
   recall engine's own test files, the `recall` tier (added 2026-09-12 after
   a doc-only fold landed five recall pins red under the contract slice and
   nobody saw them until the next lane's full tier, `DEF-775`);
   engine or hook change, or the handoff's preflight → the full suite, as
   `python scripts/proof_tier.py --run` (`--tier full` at the handoff): one
   command, two halves -- `-n auto` with the three wall-clock-budget files
   left out, then those three serially -- and one receipt naming both (6:31
   and 6:12 on the two clean runs `tests/README.md` pre-registered as the
   count the flip needed, against about nineteen minutes serial; the default
   since 2026-09-06, a measured bet, not a cleared audit). The contract slice
   under `-n auto` raced on the live tree between those runs, so the slice
   stays serial. A parallel full run that errors on a live-tree race is a
   loud error, never a false green: rerun the failing file serially and add
   the date and test to the races line in `tests/README.md`.
   If the batch touched a shipped surface after that run, the run is stale
   again — re-run rather than reason about it.
   A comment-only edit to a `tools/cc/` file counts as that shipped surface:
   regenerating the `LENGTH_NORM_ALPHA` table in `_recall.py` after the run
   cost a second full tier on 2026-09-14 (12,325 + 984, thirteen minutes). A
   lane that folds memory or a calibration table beside code lands the fold
   before its one full run, or budgets two.
6. Commit. Pipeline the wait: the next lane's reads, plan and self-drive can
   run under this lane's suite; only its first edit waits.

A doc-only or test-only change skips step 2 and runs the suite after step 1.
The three bodies that state this order are `/implement-task` (focused step 6-7,
multi Phase 3), `/preflight` (the order note and steps 2, 6) and
`/implement-pack` step 6; `docs/WORKFLOW.md` says it for adopters.

Related: [[a-packs-prescribed-fix-code-is-a-claim]] (a review's findings are
edits, which is why the run must wait for them).
