### Fixed

- **The write guard's secret-read legs read a program a carrier runs out of
  a string as a program.** The legs reached a quoted program through four
  body readers (`sh -c`, `pwsh -Command` from Bash, an interpreter's
  shell-out, `bash -c` from PowerShell) and nothing else, so Bash
  `eval "cat .env"`, PowerShell `iex "Get-Content .env"` and
  `pwsh -Command "Get-Content .env"` read a dotenv the Read tool's rule
  refuses. One carrier reader per shell now sits beside the four in
  `tools/cc/hooks/_bash_patterns.py`: Bash `eval`, `watch`, `script -c` and
  `su -c`; PowerShell `Invoke-Expression` / `iex`, `pwsh` / `powershell
  -Command`, `cmd /c` (a quoted program or the bare rest of the statement),
  `[scriptblock]::Create` and a `$(...)` subexpression. The opener is found
  on the masked text, so a carrier named inside quotes is a mention. The
  PowerShell leg derives one pair from the text its literal-binding
  pre-pass has inlined and hands it to both of its readers, so a bound
  path reaches the program it is interpolated into (`$c = '.env'; bash -c
  "cat $c"`). Declared limits, in `docs/HOOKS.md`: a `Start-Process`
  argument list, `-Command:'...'`, a glued `cmd /c"..."` and the words
  after a quoted program. The two reliefs that waited on this reader, a
  quote-aware nested-launch scan and a PowerShell head that reads a quoted
  string as one word, stay out: with the reader in place each still let
  through what the current reading refuses (a dozen carried launches; reads
  piped into `iex` or joined with `+`). (`DEF-1131`)
