### Added

- **The suite's adopter-axes registry has a platform axis, and the platform
  stand-ins the seats improvised are its cells.** `tests/_axis_registry.py`
  gains `target_os` (`linux`, `macos`, `windows`; not `os`, which a proving
  node's parameter would shadow inside the test): the operating system a test
  makes the harness read, on whatever host runs it, through one shared
  stand-in, `tests/_platform_standin.py`. `as_os` sets the platform the
  harness reads (`os.name` only when the call says so, the half that makes a
  bare `Path(...)` raise on 3.10 and 3.11); `without_the_alarm` deletes the
  `signal` names Windows lacks, a function of its own so the suite's alarm
  contract asks only its importer for pytest-timeout's thread method. One new
  bounded-spawn node, parametrised over `linux` and `windows` with the
  standard library's `run` left in place, proves both cells: read as Linux the
  call is `run`'s and the child alone is killed; read as Windows the tree
  ends, the pipes drain and the child is reaped. The alarm test of
  `tests/test_redos.py` takes the alarm away through the same stand-in; its
  timers are the suite's own, so it proves no cell. `macos` is a declared gap:
  the harness reads `darwin` nowhere, and its one Mac-differing read, the
  hooks' `platform.system()` host line, comes from `uname`, beyond any
  stand-in; a pin holds that every platform comparison in the harness is to
  `win32` or `nt`/`posix`, so the gap text cannot go stale silently.
  `PROVEN_FLOOR` rises from 6 to 8. The registry's contract gains two rules: a
  proving function is collected at two or more values of its axis (a one-value
  parameter never varies), and a `skipif` on this axis's node is refused at
  collection, because an operating-system cell is proven on every host or not
  at all.
