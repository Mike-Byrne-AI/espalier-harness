### Fixed

- **A secret read cmd runs past a separator word is refused on the PowerShell
  tool.** The secret-path check read cmd's program the way PowerShell reads
  it, so a dotenv read behind a quoted separator word PowerShell hands cmd
  bare (`cmd /c echo a '&' type .env`, `'&&'`, `'|'`, `"&"`), behind the
  stop-parsing token after the switch (`cmd /c --% type .env`, `--%,`), or
  behind a quoted program word (`cmd /c "type" .env`), through an input
  redirection (`cmd /c "more < .env"`) or in a cmd that cmd starts with its
  switch glued to a quoted program was allowed while
  `cmd /c type .env` was refused. The check now also reads the line cmd
  receives, through the same reading the recursive-delete wall uses, and
  refuses a read either reading finds; every form it refused before is still
  refused. On the Bash tool the same check read no program handed to cmd at
  all (`cmd //c type .env`); it now reads it the same way. Calls that start
  no cmd pay nothing for it on either tool.

### Changed

- **A word before cmd's switch is a declared limit.** cmd skips a word before
  its `/c` that is not a switch, and a word the switch is glued to
  (`cmd foo /c rd /s /q .`, `cmd x/c rd /s /q .`), then runs the program after
  it. The recursive-delete readers stop at that word and read no program, and
  the secret-path check reads none behind a glued word (`cmd x/c type .env`).
  `docs/HOOKS.md` now says so among cmd's declared limits.
