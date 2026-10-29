### Added

- **A known red on one host is counted, not ignored: the platform roster.**
  `tests/conftest.py::PLATFORM_EXPECTED_FAILURES` names the tests a host is
  expected to red on, for a cause a live ledger row tracks (a node id or a test
  class's node-id prefix, the platform, the row, the reason, the date). On a host
  where the entry's platform holds, the collection hook marks each covered test
  as a non-strict expected failure bounded to the cause's own failure type, the
  row id leading the reason; every other host runs the tests unmarked. The first
  entries cover the six rows of `tests/test_xdist_never_ran.py` whose nested
  child kills its xdist workers inside the build: on GitHub's macOS runners the
  child's own controller dies inside execnet before the row can read what it
  asserts, and the portability workflow's macOS leg had been red on that alone
  since the retry fix of 2026-10-18 (the anchor row red on 8 of the ten
  completed legs read on 2026-10-19). The retry driver now fails such a row with
  `NestedControllerRaceLost` (`tests/_nested_race.py`) only where every attempt
  ended in execnet's refusal to send, and the mark absorbs that failure alone: a
  timeout, another internal error or an assertion over a child that completed
  still reds the leg. The rows still run there, so the nested-controller-crash
  count keeps counting the race, now under the successor row's id, and on the
  runners the summary prints one line per roster row, zeros included: how many
  rows lost to the cause, how many completed, and the entry's age. Contract tests
  in `tests/test_test_suite_contract.py` hold each entry to a test its file
  holds, a row that is live in the assembled ledger view, a platform that holds
  on some host, a date, and the roster's own mark (non-strict, bounded, run); read
  the class from the source and hold the roster to it; check the predicate's
  table, the hook on every host and the summary line; and keep the roster's
  builder the only non-strict expected failure under `tests/`.

### Changed

- **`xfail_strict = true` has one declared exception.** The roster's mark is
  non-strict on purpose, on the operator's word: each of the six rows completes
  on the runners on some runs, so a strict mark would have redded 9 of the ten
  legs read. Any other `strict=False`, or a `**` splat whose `strict` cannot be
  read, reds the suite.
- **The changelog's fragments are swept for citations.** Both doc-citation gates
  now read `changelog.d/` beside `CHANGELOG.md`, which the release fold folds the
  fragments into; until now a fragment's test citation passed only when a
  negation word sat beside it.
