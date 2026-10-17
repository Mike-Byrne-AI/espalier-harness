### Fixed

- **A paused write_guard keeps its retired deny rule, and the run says why.**
  Every surface that names a retired deny rule (`init`, `--wire-hooks`,
  `merge-settings`, `doctor`, `upgrade`) says to delete it, because
  write_guard stands in for that rule. The check that the hooks run lets an
  old shell-form entry through on purpose, and a commented-out one passed
  with it. It never read `disableAllHooks`, and it counted a `write_guard.py`
  that was not on disk as wired. So a tree whose write_guard had been paused
  in any of those ways was told to delete the one rule still guarding it.
- **The advice now needs write_guard to run.** It must be wired the strict
  way, with its file deployed and no kill switch set. Where the rule is
  kept, each command says so, says why, and says what will name it:
  `merge-settings --repair`, or the run after the kill switch is off. It no
  longer says "nothing to do" over it. Where the advice is given, it now
  says it is given only because write_guard runs.
- **The cost.** An install still on the old shell form, or wiring its hooks
  with interpreter flags, hears of the rule only after
  `merge-settings --repair`.
