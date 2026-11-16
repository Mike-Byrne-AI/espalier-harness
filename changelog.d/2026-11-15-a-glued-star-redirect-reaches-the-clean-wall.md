### Fixed

- **A `git clean` with its output silenced by a glued redirect is judged by
  what it cleans.** On the Bash tool, `git clean`'s operand reader read a
  redirect only where a word opens with one, so a word written against its
  redirect stayed whole: the glob in `git clean -fdx *>/dev/null` and the
  state directory in `git clean -fdx cc>/dev/null` named no protected zone,
  and `git clean -fdx>/dev/null` read the target's `n` as the dry-run flag.
  Each met the one-time confirm step, where the same clean without the
  redirect meets the zone wall. Bash ends a word at an unquoted `<` or `>`,
  and the reader now does the same, for `git clean` alone: the readers every
  Bash call passes through keep the glued word whole, so no call pays for it,
  and the PowerShell tool's reading is unchanged.
