### Fixed

- **`espalier integrity verify` says when a settings file could not be read.**
  A `.claude/settings.json` or `settings.local.json` that exists but does not
  parse (a trailing comma after a hand edit) is not in the integrity manifest,
  so verify reported it as holding no kill switch and the run could come back
  clean with exit 0. It now lists the file under a new `unreadable_settings`
  key and exits 2 with a message of its own naming the file (fix its JSON and
  re-run; a project settings file that does not parse wires no hooks). The
  checkout wiring notice no longer offers `merge-settings --repair` for such a
  file, which the repair refuses. The session banner's `Integrity:` line
  no longer counts such a file as a kill switch ("remove it"): it reads
  `UNREADABLE SETTINGS` with a warning naming the file. The blocking hooks are
  unchanged, so the edit that repairs the file is never refused over it.
