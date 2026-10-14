### Fixed

- **A plain re-run of `init` over an existing install now names a retired deny
  rule its `.claude/settings.json` still carries.** `upgrade`, `doctor`,
  `merge-settings` and `init --wire-hooks` each said so, but the re-run that
  TROUBLESHOOTING gives as the repair for a broken install printed about fifty
  lines and none of them named it. The rules in question are ones `init` used
  to write: `Bash(rm -rf /*)` (through 0.8.0b2), which refuses every recursive
  delete of an absolute path in every permission mode, and five `Read()` rules
  (through 0.8.0a13). The re-run now prints the same WARN `upgrade` prints, on
  stderr with an `[init]` prefix: the rule, why it was retired, and the line to
  delete by hand, in the project, local and user settings files. Nothing is
  removed. It names the retired rules only: a plain re-run records the default
  settings profile over the one the file was rendered from, so it does not list
  profile allow rules. `upgrade --execute`, which deploys through the same
  path, still says it once.
- **No command tells the operator to delete a retired deny rule while the
  hooks do not run.** The hook layer is what stands in for every retired rule
  (write_guard's root-wipe wall, its secret-path read check), so on a
  settings.json that wires no Espalier hooks, or wires them to an interpreter
  the host lacks, "delete that line" took away the only guard left. `init`,
  `init --wire-hooks`, `merge-settings`, `upgrade` (preview, version-current
  and `--execute`) and `doctor` now name the rule only where the hooks run;
  elsewhere each names the hooks that do not run (the `upgrade` preview and
  an `--execute` that adds a hook event now say so too, where they said
  nothing), and the run after the repair names the rule. The warning, the
  sentence that points at it and "nothing to do" share one read of the hooks,
  so they cannot disagree.
- **The retired-rule WARN no longer says `init` wrote a rule it may never have
  written.** The list matches by rule text, so a line the operator wrote by
  hand read the same as one an old `init` wrote, and `doctor`,
  `merge-settings`, `upgrade` and the re-run all said "the init command wrote
  it". They now say the line matches a deny rule `init` wrote through that
  version.
- **`merge-settings` no longer says "Nothing to do." above a retired-rule
  warning or above the warning that the hooks do not run.** On a file whose
  hook events were already current it printed the sentence above both;
  `upgrade` stopped doing so on 2026-09-29, and now `merge-settings` has too.
- **`upgrade --execute` reads the hooks back after it wires new events.** It
  said it had wired them and nothing more, even where the hooks cannot run
  (an interpreter the host lacks); like `init --wire-hooks` after the same
  merge, it now names that state and the repair.
