### Fixed

- **A word at a command position is read the same way behind every
  carrier.** A wrapper in another case or with `.exe` (`ENV`,
  `nohup.exe`, as Git for Windows' bash runs them), a verb behind `~/bin/`,
  the `xargs` word itself when quoted, path-qualified, behind PowerShell's
  call operator or after bash's `|&`, and a wrapper with its flags, its
  directory or an assignment run (`nice -n 19`, `/usr/bin/env`,
  `env LC_ALL=C`) behind `find`'s exec action, `xargs` or a loop body
  each drew no zone deny where the plain spelling met the wall. They now
  read as the plain word does, on both shell tools.
- **An `xargs` switch value that begins with a wrapper's name keeps the
  move behind it.** `xargs -a env.list mv ...` read `env` as a wrapper
  and lost the move, and `xargs -a rm.list mv ...` read a delete.
