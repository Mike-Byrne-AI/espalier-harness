### Fixed

- **A refusal for your own `protected_paths` zone says it is yours on every
  channel.** These were refused with the harness's own text ("protected
  harness zone", "harness file"):
  - a write, move or delete through Bash;
  - an MCP write, move or delete;
  - a symlink created by any of the three tools;
  - a hardlink of a file in the zone;
  - a move or delete of a directory that holds the zone.

  Most of those told you to relaunch in maintenance mode, which is for
  editing the harness and turns your zone's check off for the session. Each
  now gives the zone's own template. It names the `protected_paths` entry in
  `espalier.toml` behind the refusal and says not to relaunch for this:
  - for a moved or deleted directory, the zone it holds;
  - for a build directory under `generated_paths` that holds a protected
    zone, that protected zone, not the generated one.

  What is refused is unchanged. Your zones are matched the way the refusal
  matches them: case-insensitively, and through a Windows spelling of the
  same directory (a trailing dot or blank).

  A harness zone or protected file keeps the harness text wherever your zones
  overlap it, on the Write and PowerShell refusals too. A harness settings
  file inside a `.claude/` you list was told it was yours. One case is still
  open: a zone of yours that holds harness ground, such as `tools/` holding
  `tools/cc/`, gets the harness text when you move or delete it, so it names
  the relaunch.
- **Every refusal in a harness zone names the relocate remedy.** If your
  repository has its own top-level `cc/`, the harness's reserved name, a Bash,
  MCP, symlink or hardlink refusal there now says what the Write and
  PowerShell refusals already said: relocate the directory from your own
  terminal, because maintenance mode is not the remedy for a name collision.
