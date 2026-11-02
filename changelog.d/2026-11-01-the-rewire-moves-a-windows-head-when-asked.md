### Fixed

- **`init --rewire-interpreter` puts a Windows statusline written for one
  shell behind the dot both shells run.** An install whose `settings.json`
  predates the dot form carries the statusline shim bare, which only Git
  Bash runs, or behind PowerShell's `&`, which only PowerShell runs, so the
  statusline is blank in whichever shell Claude Code picks on that machine,
  and `doctor` and `upgrade` named a hand edit. On request the rewire now
  makes it: it puts that head behind the dot, keeps a backup of the file
  first, and prints the line before and after. It runs only when you pass
  the flag, only on Windows, and only over Espalier's own shim; a statusline
  of your own, a line already behind the dot, and a POSIX host are left as
  they are. Where the shim the command leaves is one Git Bash cannot run (a
  copy you keep as your own, or one it cannot write), it leaves the head and
  says what to take into that copy. `doctor` and `upgrade` now name the flag
  where it has something to move.
