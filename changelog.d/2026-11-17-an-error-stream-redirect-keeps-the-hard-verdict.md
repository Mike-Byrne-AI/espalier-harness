### Fixed

- **An error-stream redirect among a command's words no longer lowers the
  write guard's hard verdict.** Five readers took an operand by its place and
  lost it when a `2>/dev/null` or a `2>&1` sat among the words, so a command
  the guard refuses without the redirect was allowed or only nudged with it:
  a directory chain (`cd cc 2>&1 && rm notes.md`, whose merge `&` read as a
  background `&`), a symlink written into a protected folder (`ln 2>/dev/null
  -s x cc/z.json`), the program `Start-Process` carries, the command `iex`
  and `pwsh -Command` run, and `find`'s catastrophic delete from the root
  (`find / -exec 2>/dev/null rm -rf {} +`). Each hard check is now judged a
  second time, where the first reading allowed, on the command with each
  error-stream redirect blanked (Bash's `2>`; PowerShell's `2>` to `6>`), and
  a refusal on either reading is the check's. A redirect of any other stream
  stays in both readings, since it changes what a shell runs or what a pipe
  carries. The guard's metamorphic bench now writes the merge spelling beside
  the file spelling, judges the find classifier's wall rows and the five
  shapes, and proves the merge's place null on a twin bash prints otherwise,
  since bash prints `2>&1` as written.
