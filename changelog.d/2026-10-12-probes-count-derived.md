### Fixed

- **Two lanes that each change the ledger's probe roster no longer conflict on a
  stored total.** `task-packs/LEDGER_PROBES.json` carried a `_count` that every
  ledger verb re-derived on every write, and GitHub's merge, which honours no
  merge driver, read the two re-derivations as a conflict: replayed per
  catch-up, 4 of the 8 conflicted catch-ups over #180-#192 conflicted on that
  line alone (measured 2026-10-12). The roster stores no total now:
  `tools/cc/ledger_row.py`'s verbs drop the key, `tools/cc/record_merge.py`'s
  union and its after-merge settle step drop one a merge brings back, and
  every reader takes the list's length; a test pins the live file free of it.
  `--reconcile-count` is still accepted and says it does nothing.
  `tools/cc/check_ledger_probes.py` loses its count refusal and gains a note
  naming every live ledger id with no roster entry, the trace a hand edit
  leaves (a note, never a refusal). A record merge that fast-forwards onto a
  merged pull request commits its settle on its own instead of amending the
  base's merge commit.

### Added

- **`scripts/merge_cost_census.py --per-pr`** lists each conflicted catch-up's
  own blocks and counts the ones made of the probes count line alone, the
  question the aggregate block count could not answer.
