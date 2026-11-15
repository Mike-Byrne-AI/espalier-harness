### Fixed

- **An emptied or no-op hook list in `.claude/settings.local.json` no longer
  locks the session.** Claude Code merges hook lists across the user, project
  and local settings files, so such a list in the local file removes no hook
  the project file wires. The kill-switch scan still read it as a kill switch,
  so `write_guard` refused every tool call, a Read included, and `config_guard`
  refused the change, until the file was edited outside the session. The scan
  now reads the emptied, all-empty and all-no-op hook lists in the project
  `.claude/settings.json` alone, where `init` writes the wiring.
  `disableAllHooks: true` stays a kill switch in either file, since from either
  it turns every hook off. The CI gate (`ci_guard`) reads a committed settings
  file the same way.
