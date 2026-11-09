### Fixed

- **A Stop whose test run outlives Gate 1's budget ends everything that run
  started.** With `ESPALIER_STOP_GATE=full`, the budget killed the test
  process alone on macOS and Linux, and whatever the suite had started (a
  test's server or sleeper, git, xdist workers) kept running beside the
  session, once for each Stop that reached the budget. The run is now ended
  whole, on every OS. On Windows the run also sits in a job that closes when
  the Stop hook exits, so a daemon your test command leaves running on
  purpose (Gradle's, an MSBuild or compiler server) starts cold at each Stop.
