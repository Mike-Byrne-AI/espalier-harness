### Fixed

- **An `http`, `mcp_tool` or `agent` hook no longer reads as switching every
  gate off.** Claude Code refuses a settings file's whole hooks block when one
  hook entry is malformed, and espalier's reading of that rule knew only the
  `command` and `prompt` types. So an adopter who added their own `http`,
  `mcp_tool` or `agent` hook was told by `espalier doctor` that Claude Code
  loads no hooks at all, and `ci_guard` failed a commit of that file, though
  every hook ran. All five types are now accepted with the field each one
  requires (`url`; `server` and `tool`; `prompt`), as driven on Claude Code
  2.1.319. An entry missing that field still reads as voiding the file,
  because Claude Code voids it, and the in-session settings check now refuses
  such a change instead of setting the entry aside. A type espalier does not
  know is named with a note that espalier may predate it.
