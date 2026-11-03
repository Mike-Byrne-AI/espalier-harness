### Fixed

- **A cmd.exe started by its full path or with its name in quotes no
  longer slips past the check on a harness variable set inside it.** The
  guard refuses a cmd program that sets a harness variable and then starts
  `claude`, a nested session with the protected-zone check off; it read
  only a bare `cmd` (and a path from Bash), so a full-path `cmd.exe` on
  PowerShell, a quoted `"cmd"` from either tool, the call operator on a
  quoted name or path, or `Start-Process` given a quoted or full-path cmd
  started that session unrefused. The check now reads cmd the way the
  recursive-delete reader does: by name, with `.exe`, in any case, by path
  and quoted. A `set` before any other program, such as `pytest`, is still
  allowed.
