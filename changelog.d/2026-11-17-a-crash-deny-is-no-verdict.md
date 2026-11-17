### Fixed

- **The release bench no longer scores a crashed guard as a block.** When the
  write guard fails itself (its crash guard's `write_guard internal error`,
  a fault in the runner of its judging child, or its refusal to start or to
  run below the supported Python), it denies the call without judging it.
  The bypass benchmark and the suite's spawn helpers knew only the time
  budget's refusal as such a non-answer, so a guard that crashed on a bypass
  row passed that row as blocked, and the release gate could be green on a
  guard that judged nothing. The crash now reads as no verdict there: the run
  stops with exit 3 naming the row, or the test row fails as a miss (a fault
  in the runner of the guard's judging child is retried once first, as a
  second call can pass it). The one bench row whose expected block is the
  crash itself (BC-023-a6, the crash umbrella's row, by its
  `expected_block_reason`) keeps that crash as its block, and the suite's
  rows that drive a wedged guard say they expect it, each named with its
  reason in a roster the suite checks. The guard cost census labels such a
  call `deny (crash)`, not a judgment's cost, and `espalier selfcheck
  --contracts` no longer reports a deployed guard that crashes on every call
  as denying the core bypass classes: each probe reads as refused unjudged.
  Every bench verdict is unchanged: the bench at the change's base and head
  gives the same answer on all 1,592 rows across its four baselines.
