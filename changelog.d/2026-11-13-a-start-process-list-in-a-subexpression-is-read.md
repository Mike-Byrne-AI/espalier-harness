### Fixed

- **A `Start-Process` argument list built in a `$( )` subexpression is now
  read.** Windows PowerShell hands the started program a `$( )` list exactly as
  it hands an `@( )` one, so `Start-Process cmd -ArgumentList $('/c','<program>')`
  runs the program. The guard read the `@( )` and `( )` forms but not this one,
  and the hook reference (`docs/HOOKS.md`) listed it as a declared limit. So a recursive delete handed
  to cmd this way, a set of the harness's maintenance variable before a nested
  `claude`, or a program handed to `pwsh` or `bash` met no check. All three
  checks now read it. A subexpression that computes its list, such as
  `$(Get-Content args.txt)`, is still not read as words, and a list split by
  `;` or across lines is still unread, as it is for `@( )`.
