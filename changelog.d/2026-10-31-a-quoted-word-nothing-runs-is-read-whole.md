### Fixed

- **A test run's quoted path, and a PowerShell string nothing runs, are no
  longer refused.** The write guard's nested-launch check read every quoted
  word one blank-separated fragment at a time, so running the stop-time tests
  with the harness variable inline (`ESPALIER_STOP_GATE=full pytest "<path>"`,
  the form the deny message calls allowed) was refused whenever the path
  crossed a `Claude Code` folder or a quoted `-k` expression opened with
  `claude`, on Bash and PowerShell alike, with a message saying the prefix
  reached nothing; and the PowerShell secret-read leg took a quoted string's
  first word as a command, so `$hint = 'gc .env'` or `Write-Host ("type
  .env")` was refused as a read of the dotenv it only names. Both reliefs are
  positive gates rather than lists of what to refuse: a quoted word is read
  whole only as an operand of a test run (`pytest`, `python -m pytest`) or as
  a python interpreter's script path, before any pipe or redirect, in a
  command with no subshell, group or substitution; and a statement that opens
  with a quoted string is read as a mention only when it is the right-hand
  side of an assignment that is the command's last statement, to a plain
  variable the command names nowhere else, in a command with no pipe, call
  operator, group or script block, or the one literal in `Write-Host (...)`
  with nothing after it. Everything else keeps the old reading, so a launch
  or a read handed to any carrier inside a quoted string stays refused
  without a roster of the carriers, and a form outside the gates costs a
  refusal, as before, never a launch or read let through. A chain of inline
  prefixes heading one test run reads the run once. (`DEF-1044`, `DEF-1045`)
