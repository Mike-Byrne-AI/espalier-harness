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
  profile allow rules. A settings.json that wires no Espalier hooks is never
  told a rule is retired, since it may be the adopter's own, and
  `upgrade --execute`, which deploys through the same path, still says it once.
