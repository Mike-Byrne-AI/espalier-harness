### Fixed

- **A loop over a command substitution now reads its enumerator however
  it is spelled.** A `for` over `$(...)` or backticks, and a read loop fed
  by `<(...)` or a here-string of one, read the enumerator inside the
  substitution only when it was spelled bare, so the same loop over a
  protected harness directory met the wall bare and nothing past the speed
  bump when the enumerator was quoted, given by its path, or behind a
  wrapper word or an assignment. The inner position is now read as the
  command position it is, the way the piped read loop already read its
  head.
- **The remove verb behind `find`'s exec action, behind `xargs` and in a
  loop body reads a quoted or escaped path.** An ANSI-C quote, a quoted
  path holding a blank, and an escaped blank went unread there, and on
  the PowerShell tool so did a quoted or msys path to `rm.exe` behind
  `xargs`, Git for Windows' own install path among them.
- **An enumerator spelled with `.exe` no longer makes the guard fail
  closed.** `find.exe` or `ls.exe` feeding `xargs` or a loop on the Bash
  tool raised inside the zone check, so the guard refused the command on
  every issue, a harmless build cleanup included, with a message saying it
  might be wedged.
