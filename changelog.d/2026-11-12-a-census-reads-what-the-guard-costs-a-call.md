### Added

- **`scripts/guard_cost_census.py` reads what `write_guard` costs a call
  (self-host).** `--calls N` spawns the guard N times for each call kind (a
  bare interpreter start as the control, a Read, a Bash `ls -la`, an MCP read
  and an MCP write), shuffled, each spawn in its own temp project, and prints
  each kind's median, interquartile range, minimum and maximum beside the
  decisions it saw. `--compile` counts what the guard's pattern path compiles
  in a fresh interpreter: distinct patterns, compiled characters, the length of
  the shared command-position fragment, and how many patterns embed it.
  `--import-time --rounds N` times the two pattern modules' import with no
  bytecode cache. `--at <sha>` runs any of the three against that commit's
  `tools/cc`. The timed modes hold the box lock the test tiers take, name the
  holder they wait behind, pass through inside a holder, and say `unguarded`
  beside every figure where `ESPALIER_BOX_LOCK` is unset. It changes nothing
  the guard judges.
