### Fixed

- **The Windows statusline runs whether or not Git for Windows is installed.**
  Claude Code runs the statusline under Git Bash when it finds one and under
  PowerShell when it does not, and PowerShell read the quoted shim path `init`
  wrote as an expression: on a host without Git for Windows the statusline was
  blank on a healthy install, and so was the line that reports a missing
  interpreter. `init` now writes `. "<shim>" <interpreter>`. The dot is an
  operator in both shells: Git Bash sources the shim, whose new first line is
  written for it, and PowerShell runs it as a batch file. One line serves
  either shell, so installing or removing Git for Windows after `init` changes
  nothing. Driven in both shells on Windows 11, statusline and fallback line
  alike, at no added cost per refresh. `upgrade` deploys the new shim, under
  which an existing line keeps working in its own shell; `doctor` names a line
  an older install wrote for the shell the host does not run, `upgrade` no
  longer calls such a tree current with nothing to say, and
  `--rewire-interpreter` swaps the interpreter behind any of the three forms.
