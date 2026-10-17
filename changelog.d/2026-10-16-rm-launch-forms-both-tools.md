### Fixed

- **A delete spelled the way Windows spells it meets the same check.** On the
  Bash tool, `rm.exe -rf` and `RM -rf` (Git Bash runs both as `rm`) used to
  draw a nudge on a build directory that `rm -rf` passes, and no protected-zone
  deny on a harness directory. Every binary verb the guard reads (remove, copy,
  move, link, permission changes, git, the shells, the interpreters) is now
  read with or without `.exe` and in any case. The directory-change and loop
  readers stay case-sensitive, as bash runs them. On a case-sensitive Linux
  host an upper-case `RM -rf` is judged as `rm`: friction, where the shell
  would say command not found.
- **`sudo rm -rf` on the PowerShell tool meets the wall.** On macOS and Linux
  pwsh runs the native `rm`, and a wrapper word before it (`sudo`, `env`,
  `nice`, `timeout` and the rest of the Bash tool's list) hid the delete from
  every PowerShell reader: no wall on your home directory or the checkout, no
  nudge, no zone deny. The PowerShell readers now step over the Bash tool's
  wrapper words, spelled bare, except `xargs`, whose input the pipeline
  reader already judges.
- **cmd behind `--%` or started by `Start-Process` is read.** On the
  PowerShell tool, `cmd --% /c rd /s /q <dir>` and
  `Start-Process cmd -ArgumentList '/c rd /s /q <dir>'` met no tier at all.
  Both now meet the plain `cmd /c` launch's: the wall, the nudge and the zone
  deny, with any parameter before the list (`-ErrorAction Stop`, a
  colon-bound `-ArgumentList:`) read as PowerShell binds it. The maintenance-mode `set` check reads both shapes too. A
  `Start-Process` mentioned inside a double-quoted string is still a mention.
- **A forced PowerShell remove is judged target by target.** These used to
  meet an unbypassable wall, though each part passes alone and the unforced
  remove passes them:
  - `Remove-Item -Recurse -Force build, <your temp scratch>`;
  - `Remove-Item -Recurse -Force build/*`.
  Each target is now judged by the rule it meets. A wildcard after a relative
  directory on the build-output roster (`build`, `dist`, `node_modules` and
  the rest) reads as that directory. A wildcard below any other directory,
  in the first component, after an absolute or home prefix, or with `..`
  before or after it (`build/*/..`), is still the wall. Inside
  `if (Test-Path <dir>) { ... }`, a forced remove of temp scratch passes as it
  does on its own; it used to meet the wall there.
