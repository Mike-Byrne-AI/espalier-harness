### Fixed

- **The guard no longer calls `exclude_paths` a misspelled zone, and it
  names a misspelled zone key beside a correct one.** The write guard checks
  `espalier.toml`'s top-level key names for a near miss of `protected_paths`
  or `generated_paths`, the same close-match the engine's loader uses. That
  check compared every key, so `exclude_paths`, a setting the engine reads
  (shown in the example config to keep a folder out of fingerprinting),
  scored close to `protected_paths`: on a tree that set it and no zone, every
  session printed "did you mean `protected_paths`?" and wrote a
  `config_zone_ignored` record that `/status --log` counts as a fault inside
  a guard. The check now passes over every key the engine knows, and names a
  zone key only where it is the nearest key the engine reads, so
  `excluded_paths` is left to the loader, which suggests `exclude_paths` for
  it. The check also ran only when no zone was set, so a misspelled
  `protect_paths` written beside a correct `generated_paths` protected
  nothing without a word; it now runs whether or not a zone is set. It still
  runs in every hook process, so it leaves the matcher unloaded unless a key
  the engine does not know could be a near miss and has not been named yet
  this session. The hooks guide now says the check reaches past one letter
  (`protect_paths`, `generated_path`), not that it catches a name one letter
  off.
