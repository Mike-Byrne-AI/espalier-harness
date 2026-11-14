### Fixed

- **A program a carrier runs is now read however its switch is spelled.** The
  secret check read a program handed to `su -c`, `script -c`, `eval`, `pwsh
  -Command` and `cmd /c` only when it stood as its own word after the switch.
  It now also reads a program glued to its switch (`su -c'...'`, `script
  -qc'...'`, with flags of either case before the `c`), su's
  `--session-command` and any prefix of a long switch that getopt accepts
  (`su --comm '...'`), every `-c` program on the line (su runs the last), and
  an `eval` behind `builtin` or `command`, each word quoted or followed by
  `--`, and BSD `script`'s command, the words after its file word. On
  PowerShell it reads a program switch bound by a colon on `iex`,
  `Invoke-Expression` and `powershell`, from either tool (Windows PowerShell
  5.1 runs a colon-bound word as command text, so a statement after the first
  runs; `pwsh` runs nothing there, so none is read), powershell's program with
  no `-Command` before it from either tool, and cmd's `/r`, which cmd runs as
  `/c`, glued to the program or to a run of switches. A switch value glued on
  ahead of the program switch
  (`script -ttrace.log -c '...'`) no longer hides the program after it. Still
  unread: a glued switch run inside a cmd that another cmd starts,
  `-EncodedCommand`, and `builtin exec` or `builtin command` before a protected
  write.
