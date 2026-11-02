### Fixed

- **A pytest child a test launches no longer deletes another session's temp
  dir inside the test's clock.** pytest deletes every unlocked numbered
  basetemp three below the newest when a session ends, so the first child to
  end after a big run paid that run's whole delete: on windows-latest the
  cited-pin child of `tests/test_declared_limits_contract.py`, first to end
  after the portability leg's parallel half, paid its 8.9 GB basetemp and ran
  past its 300 s bound on 15 of the 18 runs since the file moved to the serial
  half (alone on a fresh runner it takes 66 to 72 s). Each test session now
  exports its basetemp, and a child that shares its parent's temp root takes
  its basetemp inside the parent's (`tests/_nested_temp.py`), so its session
  end deletes nothing of another session's and the delete waits for a later
  top-level session's end; `scripts/verify_pins.py`, whose clone may predate
  that rule, gives its child a basetemp in its own work dir. The 300 s bound
  and the serial list stay.
