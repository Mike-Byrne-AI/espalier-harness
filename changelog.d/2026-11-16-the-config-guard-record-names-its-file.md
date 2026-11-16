### Fixed

- **A command or skill file change no longer reads as an unreadable settings
  file.** Claude Code reports a change to a `.claude/commands/` or
  `.claude/skills/` file as a configuration change naming that markdown file,
  and the settings guard parsed it as JSON, so each such change (a
  SessionStart catch-up that moves the commands folder, a lane editing a
  command) wrote a `configchange_failed_open_settings_read` record saying a
  scan was skipped when none was. The guard now reads the named file only
  where it is the project or the local settings file, and the record, kept
  for a settings file it cannot read or parse, names that file by its label,
  once a session for each file.
