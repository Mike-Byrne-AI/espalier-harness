### Fixed

- **`espalier pre-release` and `espalier refresh-externals --apply` end the
  whole test run at their timeout.** When the release gate's test leg or the
  pins' bound tests reached their bound on macOS or Linux, only the pytest
  process was killed, and whatever the suite had started (a test's server or
  sleeper, git, the hooks) kept running beside the next command until it was
  ended by hand. The run is now ended whole, on every OS. On Windows the run
  also sits in a job that closes when the command exits, so a daemon a test
  leaves running on purpose is ended then too.
