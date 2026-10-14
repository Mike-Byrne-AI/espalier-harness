### Fixed

- **A plain re-run of `init` over an existing install now names a retired deny
  rule its `.claude/settings.json` still carries.** `upgrade`, `doctor`,
  `merge-settings` and `init --wire-hooks` each said so, but the re-run that
  QUICKSTART lists beside `upgrade --execute` printed about fifty lines and none
  of them named it. The rule in question, `Bash(rm -rf /*)`, which `init` wrote
  through 0.8.0b2, refuses every recursive delete of an absolute path in every
  permission mode. The re-run now gives the same read-only report `upgrade`
  gives, on stderr with an `init:` prefix: the rule, why it was retired, and the
  line to delete by hand (in the project, local and user settings files).
  Profile allow rules the file lacks are listed too, with the `merge-settings
  --add-allows` line that appends them. Nothing is removed or appended. A
  settings.json that wires no Espalier hooks is the adopter's own, so a rule
  there is never called retired, and `upgrade --execute` still says it once.
