### Added

- **The suite's adopter-axes registry has an `os` axis, and the platform
  stand-ins the seats improvised are its cells.** `tests/_axis_registry.py`
  gains `os` (`linux`, `macos`, `windows`): the operating system a test makes
  the harness read, on whatever host runs it, through one shared stand-in,
  `tests/_platform_standin.py`. `as_os` sets the platform the harness reads
  (`os.name` only when asked, the half that makes a bare `Path(...)` raise on
  3.10 and 3.11); `without_the_alarm` deletes the `signal` names Windows
  lacks, a function of its own so the suite's alarm contract asks only its
  importer for pytest-timeout's thread method. The alarm test of
  `tests/test_redos.py`, read as Windows, proves `windows`; a new bounded-spawn
  node parametrised over `linux` and `windows` proves `linux` (the call is
  `subprocess.run`'s and the child alone is killed) and is the second witness
  for `windows` (the tree ends, the pipes drain, the child is reaped); `macos`
  is a declared gap, since the harness reads `darwin` nowhere. `PROVEN_FLOOR`
  rises from 6 to 8, and a `skipif` on an `os` cell's node is refused at
  collection: an `os` cell is proven on every host or not at all, because the
  point of a stand-in is that the required Linux cells see the other host's
  shape.
