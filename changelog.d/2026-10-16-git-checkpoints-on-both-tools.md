### Fixed

- **The release, force-push and clean speed bumps read the PowerShell tool
  as they read Bash.** From the PowerShell tool, `gh release create`, a tag
  push (`git push origin v1.2.3`, `--tags`, `--follow-tags`), `git push
  --force` and `git clean -f` now draw the nudge they draw from Bash; a
  PowerShell string that only mentions one stays silent, and, as before, a
  program that tool hands to `bash -c` is read by the discard speed bump alone.
  Before, the PowerShell tool read only the ship driver's `release` verb.
- **More spellings of a release and a force push bump.** A quoted ship driver
  path (`python "tools/cc/ship.py" release v1.2.3`, or a quoted absolute path
  with a space), an interpreter with its own path, a quoted tag, the release
  checklist's own `git push origin "v$VER"`, `gh.exe`, and a `+` refspec
  (`git push origin +HEAD:main`) now draw the nudge on both tools.
- **A rehearsal draws no nudge, and only a rehearsal does.** `git push
  --dry-run` or `-n` publishes nothing, so the release and force-push speed
  bumps now stand down on it, as the clean speed bump already did for `git
  clean -n`. The flag is read from the command's own options, split as its
  shell splits them: a comment, a substitution, a redirect target, an option's
  value, a PowerShell block after the command or a quoted word that only spells
  the flag is never taken for one, and a rehearsal beside a real push in one
  command still bumps. `gh release create --draft=false` publishes, so it
  bumps.
