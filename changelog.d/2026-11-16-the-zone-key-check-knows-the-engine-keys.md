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
- **`session_catch_up` is a key the engine knows.** The SessionStart catch-up
  reads `session_catch_up = true` from `espalier.toml`, and the hooks guide
  tells adopters to set it, but the engine's loader did not declare it, so
  `espalier doctor` and every command that loads the config called it an
  unknown key and said it was ignored, and deleting it would have turned the
  catch-up off. It is declared now, with the hook as its reader, and the
  config skeleton documents it. A test now checks that each key a hook reads
  through a named constant is one the engine declares.
- **The config skeleton keeps its plain keys above its tables.** TOML reads
  every key below a `[table]` header as that table's, and the skeleton put
  `ledger_fragments` below `[id_blocks]`, so uncommenting both put it inside
  the id blocks. Table-form keys now render last, and the skeleton's header
  says the keys under "Other readers" are read by the script each one names.
  A kept `espalier.toml` is never rewritten: move such a line above
  `[id_blocks]` by hand.
