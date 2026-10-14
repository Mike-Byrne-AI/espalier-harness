### Fixed

- **The board's ledger line counts the base branch, not this checkout.**
  `tools/cc/board.py` (`/inbox board`) counted the live ledger rows in the
  working tree. A checkout that stopped moving, such as one left on a merged
  branch, kept reporting its own count while every other line read GitHub or
  the base live.

  It now counts at `origin/<base>` with the base's own ledger tools and names
  the commit it read (`ledger:   279 live rows at origin/main (3107474)`), so
  a checkout running older ledger tools still counts a newer base the way the
  base reads itself. The line adds `as last fetched` when the fetch failed or
  `--no-fetch` skipped it, and says `no ledger` when the base keeps none.

  The board counts the working tree, and says why, in two cases: a clone
  without that remote-tracking ref, or a base whose `git archive` leaves the
  ledger out (an `export-ignore` attribute). A base that keeps its ledger
  somewhere this checkout does not look reads as unread, naming both places,
  until the checkout catches up.

### Changed

- **The board refreshes the base branch's remote-tracking ref on every read**,
  not only when a pull request's auto-merge is armed. The fetch never opens a
  credential prompt or a Git Credential Manager window. `--no-fetch` still
  skips it.
