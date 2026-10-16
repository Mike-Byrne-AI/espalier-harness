### Fixed

- **The release, force-push and clean speed bumps read the PowerShell tool
  as they read Bash.** From the PowerShell tool, `gh release create`, a tag
  push (`git push origin v1.2.3`, `--tags`, `--follow-tags`), `git push
  --force` and `git clean -f` now draw the nudge they draw from Bash, and so
  does any of them in a program that tool hands to `bash -c`; a PowerShell
  string that only mentions one stays silent. Before, the PowerShell tool
  read only the ship driver's `release` verb.
- **A quoted ship driver path bumps.** `python "tools/cc/ship.py" release
  v1.2.3`, and a quoted absolute path with a space in it, now draw the release
  nudge on both tools.
- **A rehearsal push draws no nudge.** `git push --dry-run` or an `-n` cluster
  publishes nothing, so the release and force-push speed bumps now stand down
  on it, as the clean speed bump already did for `git clean -n`; the rehearsal
  token is read from each push's own arguments and outside quotes, so a
  wrapper's `-n` or a quoted value is never taken for one, and a real push
  after a rehearsal in one command still bumps.
