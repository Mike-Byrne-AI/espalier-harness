### Fixed

- **A refusal for your own `protected_paths` zone says it is yours on every
  channel.** A write, move or delete through Bash, an MCP write or move, a
  symlink created by any of the three tools, a hardlink of a file in the zone,
  or a move of a directory that holds the zone was refused with the harness's
  own text ("protected harness zone", "harness file"). Most of those told you
  to relaunch in maintenance mode, which is for editing the harness and turns
  your zone's check off for the session. Each now gives the zone's own
  template: it names the `protected_paths` entry in `espalier.toml` that
  covers the path (for a moved directory, the zone it holds) and says not to
  relaunch for this. What is refused is unchanged. A harness zone or file
  keeps the harness text wherever your zones overlap it, compared
  case-insensitively as the refusal itself is.
- **Every refusal in a harness zone names the relocate remedy.** If your
  repository has its own top-level `cc/`, the harness's reserved name, a Bash,
  MCP, symlink or hardlink refusal there now says what the Write and
  PowerShell refusals already said: relocate the directory from your own
  terminal, because maintenance mode is not the remedy for a name collision.
