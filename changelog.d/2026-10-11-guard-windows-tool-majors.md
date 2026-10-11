### Changed

- **The Bash tool reads a drive path by its depth below the drive, as the
  PowerShell tool does.** A recursive delete of a drive-qualified path two or
  fewer levels below its drive root (`C:/Windows/System32`, `C:/work/old`),
  outside the repo, the home directory and a temp root, now meets the wall on
  the Bash tool where it drew a nudge one re-issue cleared; the PowerShell
  tool already walled it. The Git Bash spelling of the drive (`/c/...`) is
  read the same way on Windows and stays an ordinary path elsewhere. A path
  inside the repo or the home, or below a temp root, is unchanged.

### Fixed

- **A grouped listing piped into a remove on the PowerShell tool is judged by
  its root.** A recursive listing in parentheses, a subexpression or an array
  subexpression, with its directory the last word inside the group, kept the
  group's closing paren on the directory name: the checkout drew no wall, a
  protected harness directory no protected-zone deny, and a build directory a
  nudge the ungrouped spelling does not. The same closing paren on a grouped
  direct remove of the checkout hid it from the wall. Every PowerShell root
  reader now cuts it, and a native listing in a group (`git ls-files`, a
  `find` head) reads a directory with a trailing backslash before the paren.
- **An unquoted drive path bound to a variable on the Bash tool binds
  whole.** A binding such as `d=C:/x` (bash takes it as one word) read as an
  unbound variable to the wall and as the drive letter alone to the other
  checks, so a recursive delete through it fell from the wall or the
  protected-zone deny to the nudge, and scratch below a temp root drew a
  nudge the quoted binding does not.
