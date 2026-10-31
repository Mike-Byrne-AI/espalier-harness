### Fixed

- **On the PowerShell tool, the guard now reads the write spellings Windows
  PowerShell 5.1 accepts.** A write to a hook or the settings file went through
  with no deny when it used a 5.1 alias (`sc`, `ac`, `clc`, `tee`, `ni`), a
  shortened or aliased path parameter (`-Pat`, `-FileP`, `-PSPath`, and `-Fi`
  on `Out-File` and `Tee-Object`), a colon-bound one (`-Path:<file>`), a comma
  list of paths (only the first was read), a `New-Item` or `tee` path given
  without its flag, or a value whose parentheses hold a pipe or another
  command's path flag before the real one. A comma list of copy or move
  sources, and a `-PSPath` source, are now read the same way. A write inside a
  block never borrows the path of the command after it, and a flag glued to a
  closing quote or bracket still denies as it did before. The guard may now
  also deny a command that names a protected file in one of these spellings
  without ever running, such as an ambiguous parameter prefix PowerShell
  refuses.
