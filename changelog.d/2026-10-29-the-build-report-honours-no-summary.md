### Fixed

- **The suite's terminal-summary hooks write nothing under `--no-summary` on
  pytest 9.2.0.** pytest 9.2.0 calls every plugin's `pytest_terminal_summary`
  under `--no-summary` and leaves the gating to the plugin (its changelog
  #14724; 9.1.1 never called it there), so `tests/conftest.py`'s hook wrote the
  build report, the counts and the slow list, `tests/_never_ran.py`'s wrapper
  wrote the never-ran line and `tests/_box_lock.py`'s two hooks wrote the
  lock's line where none was asked for; #352's Ubuntu and macOS portability
  legs and main's post-merge proof red on the crashed-controller row's
  `--no-summary` case the day the dev extra floated to 9.2.0. Each hook now
  returns before it writes when `terminalreporter.no_summary` is set, marking
  that it ran all the same so its session-finish fallback stays in step (the
  fallbacks read the option for themselves, as before); no pin. Unit tests
  drive each hook and each fallback with a reporter asked for no summary, a
  contract test derives every terminal-summary hook under `tests/` and
  requires the read before any write, and the e2e case is green under pytest
  9.2.0.
