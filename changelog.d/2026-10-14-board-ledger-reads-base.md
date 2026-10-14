### Fixed

- **The board's ledger line counts the base branch, not this checkout.**
  `tools/cc/board.py` (`/inbox board`) counted the live ledger rows in the
  working tree, so a checkout that stopped moving, such as one left on a merged
  branch, kept reporting its own count while every other line read GitHub or
  the base live. It now counts at `origin/<base>` with the base's own ledger
  tools and names the commit it read (`ledger:   279 live rows at origin/main
  (3107474)`). A checkout running older ledger tools still counts a newer base
  correctly. A clone without that remote-tracking ref counts its working tree
  and says so on the line.

### Changed

- **The board refreshes the base branch's remote-tracking ref on every read**,
  not only when a pull request's auto-merge is armed, so the ledger count is
  the base's tip. `--no-fetch` still skips it.
