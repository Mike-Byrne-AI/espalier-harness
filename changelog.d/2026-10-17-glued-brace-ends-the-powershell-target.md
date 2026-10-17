### Fixed

- **A write at the end of a tight PowerShell scriptblock meets the zone
  deny.** On the PowerShell tool, a write that was the last thing inside a
  scriptblock with no blank before the closing brace kept the brace on its
  target: `& { Set-Content -Value x -Path .claude/settings.json}`. The same
  happened inside `Invoke-Command -ScriptBlock { ...}`,
  `1 | ForEach-Object { ...}` and an `if` body. The guard read a file named
  `settings.json}`, and the anti-self-disable deny the unwrapped write gets
  did not fire. PowerShell ends the word at the brace (on Windows PowerShell
  5.1 every such write landed on the file itself), and the guard now reads
  it the same way. This covers every write, copy, remove, rename, permission
  and symbolic-link reader on the PowerShell tool. A brace the operand opens and
  closes itself (a scriptblock argument, `${name}`) is still part of the
  operand, and so is a quoted or backtick-escaped brace. The Bash tool is
  unchanged: there a glued brace is part of the file name.
