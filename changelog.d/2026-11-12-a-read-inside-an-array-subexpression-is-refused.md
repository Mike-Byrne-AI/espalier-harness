### Fixed

- **A file read inside a PowerShell array subexpression is now refused when the
  file is a secret.** PowerShell runs the program inside `@( )` as it runs a
  `$( )`'s. So `$a = @(Get-Content .env)`, the usual way to load a file's lines
  into an array, reads the file. The secret-read check read the program inside
  `$( )` but treated `@(` as an argument's parenthesis. That let `@(gc .env)`,
  `$a = @(Get-Content .env)` and `Write-Output @(Get-Content .env)` through on
  the PowerShell tool, and `pwsh -Command '@(gc .env)'` through on the Bash
  tool, while `$(gc .env)` was refused. It now reads the program inside `@( )`
  too, and a nest of `@( )` costs none of the levels a nest of `$( )` reads to.
  `Get-Content @('.env')` is still refused. Some forms stay allowed. One is an
  `@( )` inside a string, even one that `iex` or `pwsh -Command` runs, since
  PowerShell expands only `$( )` there. Another is an array of strings, such as
  `@('gc .env', 'ls')`.
