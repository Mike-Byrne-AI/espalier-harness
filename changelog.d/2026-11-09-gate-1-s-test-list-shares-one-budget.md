### Fixed

- **A declared test list shares one Gate 1 budget.** With
  `ESPALIER_STOP_GATE=full` and a `test` list of two or more commands under
  `[extra_actions]` in `espalier.toml` (`test = ["npm run build", "npm test"]`),
  each command had its own 60 s budget, so a list whose commands each fit could
  together run past the Stop hook's own 90 s timeout. Claude Code then cancels
  the hook and drops its output, and the Stop passed with nothing blocked and
  nothing recorded. The list now shares the one budget: each command starts
  with what is left, and a command the list reaches with none left is not
  started and blocks the Stop naming the list. A list whose commands together
  take longer than the budget, which used to pass, now blocks on every Stop:
  narrow its entries to what proves a change.
