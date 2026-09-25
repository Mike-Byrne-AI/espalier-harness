# A new review workflow needs two classifications, and they fire at different times

**Status:** active
**Linked from:** ESPALIER_MEMORY.md row "A review workflow needs TWO classifications"

Adding a dated fan-out **review workflow** under `.claude/workflows/*.js` that
calls `append_findings_to_corpus` requires classifying it in **two** contracts,
not one — and the two fire at **different times**.

## The two contracts

1. **`tests/test_finding_ledger.py::TestStandingCallerLedgerWiring`** — add the
   filename to `DATED_ONEOFFS` (or `STANDING_PERSISTERS`). This reads the
   filesystem (`.glob("*.js")`), so it fires **immediately**, even while the file
   is still untracked.
2. **`tests/test_contracts.py::TestFanoutSchemaParity`** — add the filename to
   `LIVE_V2` (the current 13-field schema, single-quoted JS literal) or
   `FROZEN_V1`. This reads `git ls-files .claude/workflows/*.js`, so it stays
   **blind until the file is committed**.

## The trap

The `git ls-files` blindness is the whole problem: a first full-suite run over
the untracked workflow **greens contract #2** — it cannot see the file. You
commit. The *next* full-suite run reds, and it looks like an unrelated
regression.

**Classify both up front, when you add the workflow.**

## Deciding the schema bucket

If the inlined `FINDING` const is copied verbatim from a current `LIVE_V2`
sibling (e.g. `_oss_convergence_round4.js`), it is `LIVE_V2` — and
`test_live_copies_track_sot` will confirm its `required[]` matches the
`FINDING_SCHEMA` source of truth.

This is a concrete instance of the newly-created-file blindness documented in
`docs/SHARP_EDGES.md` ("A newly-created file is invisible to `git ls-files`-derived
gates until `git add`-ed") and of the sister-site discipline in
`docs/STANDING_PRINCIPLES.md` §8.
