### Fixed

- **`upgrade`, `merge-settings`, `init --wire-hooks` and an `init` re-run
  name a broad allow rule matching one an older init wrote, as `doctor`
  does.** Up to 0.8.0b2 the workflow and self-host profiles derived
  `Bash(<binary> *)` from a fingerprinted command (`Bash(npm *)` from `npm
  test`, which pre-approves `npm install`, `npm exec` and `npm publish`); the
  narrowing of 2026-10-06 reaches a fresh install only, because the merge
  never removes a rule. Only `doctor` said the broad rule was still there,
  and `merge-settings --add-allows` appended the narrow rules beside it.
  Every caller of the merge now prints doctor's warning and delete step, one
  sentence shared with `doctor`, and removes nothing. The rule is judged
  against the profile recorded for the file: `merge-settings --profile` does
  not change it, and an `init` re-run reads the record before it writes its
  own. (An `init --profile` re-run over a file it keeps still records the
  profile asked for, so the runs after it judge by that one.) The sentence says the rule matches one an older init wrote, since
  a settings file you brought holds the same text with no init behind it, and
  that every run names it while it is there.
- **The rules named are the ones matching what an older init wrote, in both
  shells.** A render on Windows from 0.8.0b2 on wrote the `PowerShell(...)`
  twin of each Bash rule, so `PowerShell(npm *)` is named beside `Bash(npm *)`,
  and still named once the Bash rule alone is deleted. On a pnpm, Yarn or Bun repository
  `Bash(npm *)` is named, since init read every Node repository as npm until
  2026-10-06; `Bash(pnpm *)` and its kin, and a rule matching a command init
  never derived from (a `lint` or `dev` script), are left as yours.
