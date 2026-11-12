### Fixed

- **A file read inside a PowerShell array subexpression is now refused when the
  file is a secret.** PowerShell runs the program inside `@( )` wherever it
  stands, the same as a `$( )`. So `$a = @(Get-Content .env)`, the usual way to
  load a file's lines into an array, reads the file. The secret-read check
  read the program inside `$( )` but treated `@(` as an argument's
  parenthesis. That let `@(gc .env)`, `$a = @(Get-Content .env)` and
  `Write-Output @(Get-Content .env)` through on the PowerShell tool, while
  `$(gc .env)` was refused. It now reads the program inside `@( )` too.
  `Get-Content @('.env')` is still refused. A mention in a string stays
  allowed: PowerShell never runs `@( )` inside quotes.
