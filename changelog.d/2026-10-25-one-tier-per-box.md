### Added

- **One pytest tier at a time on one machine, by construction.** `tests/_box_lock.py`,
  registered from the suite's conftest beside the never-ran count, takes a kernel lock on the
  file `ESPALIER_BOX_LOCK` names when the run is an xdist run that will run tests
  (`numprocesses` read from the config, so an addopts `-n` counts and `-n 0` takes none; every
  tier line is an xdist run, the contract slice included, and a tier's lines each take and
  release the lock, so two tiers interleave line by line; a run without `-n`, as a reviewer's or
  an agent's node-id or file run is, takes no lock and never waits past a Bash call's cap). While another run holds it the controller polls the primitive's
  new non-blocking `try_lock_file`, prints the holder (seat, lane, pid, how long, the argv head)
  on stderr at once and then once a report interval, with an inspect command and the stop command
  once the holder itself is past a 60-minute ceiling, and appends one JSON line per wait to
  `<lock path>.log`; the run's terminal summary says what the lock did (waited, passed through,
  unguarded). Once
  held it writes its record into the file and exports `ESPALIER_BOX_LOCK_HOLDER=<pid>` before any
  worker is spawned, so a nested run that inherits the pair and finds the record's pid alive
  passes through; a dead holder's pid is no pass, an empty record under a held lock is said and
  waited on, and the record is truncated at unconfigure. A plugin failure is one stderr line and
  the run proceeds unguarded. `tests/test_box_lock.py` drives real pytest children (eight named
  mutants, each killed by its test) and a census pins that no pytest spawner in the tree keeps
  the path and drops the holder. This replaces the START and END notes two seats improvised on
  the mail channel (87 of 240 worker messages on 2026-10-18).
- **`try_lock_file`** beside `lock_file` in both copies of the primitive (`tools/cc/_json_safe.py`,
  `espalier/_atomic_io.py`, held equal by the two-copy parity test): `LOCK_NB` on POSIX, the
  fail-immediately flag on Windows, where `_lock_byte` reads the lock-violation error as False
  under that flag alone and keeps raising for a blocking caller. The lock-site census allowlist
  names the two owners.

### Changed

- **The seat launcher sets the box lock.** `tools/cc/seat.py::child_env` sets `ESPALIER_BOX_LOCK`
  to the host's default (`espalier-box.lock` under the temp directory, per user on both OSes)
  unless the parent named one, and the printed launch line exports it in both shells, the
  terminal's own path winning where it names one. The release
  gate's whitelist passes the two lock names through, by name, so its legs run under the lock;
  `docs/ENV_CATALOG.md` carries both rows. On a named clone whose session has no
  `ESPALIER_BOX_LOCK` (a hand relaunch after a reap), the SessionStart banner says so and how to
  fix it, folded onto a worker's `Orders:` line and the dispatcher's `Mail:` clause so the
  banner's line count stands. `memory/parallel-work-protocol.md` item 1 and `docs/WORKFLOW.md`'s
  Parallel seats say the lock is what serialises two seats' tiers, and that a tool running pytest
  as a probe inside a holding run strips both variables from the child.
