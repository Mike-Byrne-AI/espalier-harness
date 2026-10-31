### Fixed

- **The Windows statusline runs on a host without Git for Windows.** Claude
  Code runs the statusline under Git Bash when it finds one and under
  PowerShell when it does not, and PowerShell read the quoted shim path `init`
  wrote as an expression: the statusline was blank on a healthy install, and
  so was the line that reports a missing interpreter. `init` now looks for Git
  Bash where Claude Code does (`CLAUDE_CODE_GIT_BASH_PATH`, read from the
  environment and from the settings files' `env`, the two Program Files paths,
  then every `git` on `PATH`) and, only where it finds no trace of one, writes
  `& "<shim>" <interpreter>`, PowerShell's call operator, which Git Bash
  cannot parse; anywhere else the line is as before. Both forms were driven in
  their shells on Windows 11, statusline and fallback line alike. `doctor`
  names a line written for the other shell (Git for Windows installed or
  removed since `init`), `upgrade` no longer calls such a tree current with
  nothing to say, and `--rewire-interpreter` swaps the interpreter behind
  either form.
