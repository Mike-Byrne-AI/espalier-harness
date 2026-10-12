### Fixed

- **The onboarding rows `init` files read their files the way the harness
  does.** The goal row (ONB-1) now closes once the `## Goal` section of
  `cc/GOAL.md` is written, instead of waiting for `/handoff` to fill the
  section below it; it reads the whole file only where there is no `## Goal`
  heading, and an empty Goal section, a blank file or a goal that does not
  decode stays open. While the goal file is there it decides the row whatever
  `goal_snapshot` says, since every session start still shows it; the key
  closes the row only once the file is deleted. A goal saved as UTF-16 or
  UTF-32 with a byte-order mark is read; one saved without a mark, or carrying
  a NUL, stays open rather than reading closed or failing. `espalier.toml` is
  read by the same TOML parser the engine and the hooks use, so a key in a file
  the harness cannot parse (a byte-order mark, a cp1252 byte, a syntax error)
  no longer closes the plan-folder row (ONB-6) or the goal row, and the
  plan-folder row closes only once the key holds a list. A conventions or
  sharp-edges stub saved in another encoding counts as edited instead of
  leaving the stub row (ONB-7) unresolved. These rows reach ledgers `init`
  seeds from this release; a ledger seeded earlier keeps the probes it stored.
