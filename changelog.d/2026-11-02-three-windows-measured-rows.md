### Fixed

- **Wiring and unwiring the hooks keeps your `.claude/settings.json` in the
  line endings it had, and keeps its non-ASCII characters as written.**
  `init --wire-hooks`, `merge-settings` (with or without `--repair`),
  `init --rewire-interpreter` and the uninstall's unwire each rewrote the
  file with LF line endings, and all but the rewire wrote a non-ASCII
  character such as the `ö` in a path as the escape `\u00f6`. On a Windows checkout
  with `core.autocrlf=true` that tracks its own settings file, an install
  then an uninstall left `git status` reporting the file modified while
  `git diff` showed nothing, and on any OS a rule naming a non-ASCII path
  came back escaped. All four now write the line ending the file already
  uses and leave non-ASCII characters alone, so an install then an
  uninstall gives back the bytes you committed, for a UTF-8 file with no
  byte-order mark. A file laid out other than
  at two-space indents still comes back at two spaces.
