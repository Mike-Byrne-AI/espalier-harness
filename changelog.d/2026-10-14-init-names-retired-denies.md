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
  profile allow rules. Over a settings.json that wires no Espalier hooks the
  re-run says nothing of retired rules: none of the hooks run there yet, so the
  hook that replaces a retired `Read()` rule is not there to take over. `upgrade --execute`, which
  deploys through the same path, still says it once.
- **The retired-rule WARN no longer says `init` wrote a rule it may never have
  written.** The list matches by rule text, so a line the operator wrote by
  hand read the same as one an old `init` wrote, and `doctor`,
  `merge-settings`, `upgrade` and the re-run all said "the init command wrote
  it". They now say the line matches a deny rule `init` wrote through that
  version.
