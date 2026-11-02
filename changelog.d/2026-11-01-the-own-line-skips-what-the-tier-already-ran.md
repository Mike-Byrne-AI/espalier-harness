### Fixed

- **A cheaper tier's own-tests line no longer runs a file the tier has already
  run whole, and a changed body's line has a ceiling.** `scripts/proof_tier.py`
  put every test file that names a changed path on the own line, so a file the
  conftest classifies `contract` ran there a second time whole after the
  contract line had run every row of it, and on the recall tier a reader among
  the recall slice ran beside the slice line that runs it: 16 of the 56 files
  the tracked bodies brought, and `tests/test_recall.py` for 27 recall-tier
  paths. The classification is read from `tests/conftest.py::_MARKER_RULES`'s
  literal, never imported, because the CI tier job composes the line with no
  pytest installed; where the rules cannot be read nothing is left off. The
  reflect skill's line went from 14 files (8382 tests, 302 s on four workers)
  to 10 (7636 tests, 307 s): the files it drops were fast, and the line's time
  is `tests/test_write_guard.py`'s, which the skip does not touch. Each changed
  body's count now prints beside `OWN_LINE_CEILING` (10,
  the live maximum), which a test pins over every tracked body, so a test file
  that starts naming the bodies grows the line by a decision.
