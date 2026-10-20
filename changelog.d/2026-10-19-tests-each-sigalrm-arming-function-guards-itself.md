### Added

- **A read of an alarm name Windows lacks sits under a guard, checked on every host.**
  `tests/test_test_suite_contract.py::test_every_sigalrm_arming_function_guards_itself`
  reads every scope under `tests/` (each def at any depth, and a module's own
  statements with its defs' decorators and defaults) and reds on a read of
  `SIGALRM`, `setitimer`, `alarm`, `ITIMER_REAL` or their kin, as a `signal`
  attribute or a `from signal import`, that no guard covers. A guard covers a
  read when the read sits in a branch that runs only with the alarm
  (`if hasattr(signal, "SIGALRM"):`, a name assigned from that test, or an
  `and` holding one), or after a statement of the same block that leaves
  quietly without it (`if not hasattr(signal, "SIGALRM"): pytest.skip(...)` or
  `return`). A mark, an assert, a raise, a guard in a caller or one after the
  read does not count, so a helper answers for itself. Windows has no SIGALRM
  while the required cells and the macOS leg do, so an unguarded read used to
  pass every cheap gate and red only the Windows portability leg, about 80
  minutes after the merge: two helpers in `tests/test_redos.py` did on
  2026-10-18 (DEF-5024), and the detector names exactly those two in that
  file's text before the fix.

### Changed

- **The thread-method contract also reads a test that deletes a signal name,
  and follows imports through helpers.**
  `tests/test_test_suite_contract.py::test_every_module_that_arms_sigalrm_declares_the_thread_method`
  now asks the thread timeout method of a test module whose code deletes a name
  pytest-timeout's signal method reads from `signal` (derived from the installed
  plugin's source: `SIGALRM`, `setitimer`, `ITIMER_REAL`, `SIG_DFL` and `signal`
  at 2.4.0), through `monkeypatch.delattr`, the builtin, a `"signal.<name>"`
  target or a `del` statement, a non-constant name counted; and of every module
  that imports such a function by name, followed from module to module. Under the signal
  method, a failing test with such a name deleted ends the whole session in an
  INTERNALERROR, since the plugin's `cancel()` reads the name before teardown
  restores it, and the offender's line now says so. A `tests/_*.py` helper is
  no longer asked for a `pytestmark` of its own, since a mark there applies to
  no test (the modules that import it are asked instead); one that arms
  outside a module-level function, where its importers cannot be followed, is
  reported, and `tests/conftest.py` is told that no mark in it reaches a test.
