### Fixed

- **A settings file with one malformed hook entry no longer switches the
  settings guard off for the session.** Claude Code ignores a hook entry it
  cannot load (an unknown type, a missing `url`, a missing `type`) when it sits
  outside `PreToolUse` and `PermissionRequest`, and applies the rest of the
  file, gates included. The harness read any such entry as voiding the whole
  file, so SessionStart recorded no gate as running, and the settings guard then
  let any change through, a removed `hooks` key included, with nothing on the
  banner. A SessionStart that ran from the file proves Claude Code applied it,
  so the gates are now recorded as the file wires them with the entry set aside,
  and a later change is judged the same way: removing the gates is refused, an
  edit that keeps the entry passes, and any other malformed entry is still read
  as the void it may be. The banner says when the file reads as void, and says
  it cannot tell whether Claude Code applied it where another settings file also
  names the SessionStart hook; a gate dropped beside such an entry is named again.
