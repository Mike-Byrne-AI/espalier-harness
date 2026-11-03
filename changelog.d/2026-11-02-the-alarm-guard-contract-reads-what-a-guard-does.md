### Fixed

- **The suite contract that keeps an alarm read off Windows reads what a
  guard does where it runs, not how it is spelled.**
  `tests/test_test_suite_contract.py::test_every_sigalrm_arming_function_guards_itself`
  read seven shapes as guarded that red on Windows: a name a guarded
  `from signal import` bound, used bare in a helper (`NameError`); a
  module-level `pytest.skip` without `allow_module_level=True` (a collection
  error); a context manager's or a yield fixture's `return` before its first
  `yield` ("didn't yield"); a statement `pytest.mark.skip(...)`; a guard name
  assigned `not hasattr(...)`; and a guard name bound in one function counted
  in another. A name such an import binds is now read where it is used, a
  quiet exit is judged by its scope's kind, and a name guards only in its own
  scope and the functions it encloses, where every value it is given holds
  only with the alarm; a walrus is read through to its value. The calibration
  gains a row for each shape and for each `and` and `or` polarity, which no
  row pinned before.
