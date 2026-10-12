### Fixed

- **The ledger trend reads a merge-heavy ref as one line of history, and its
  struck column is checked.** `scripts/ledger_trend.py` walks the ref's
  first-parent line, so on `main` a lane's own commits no longer interleave
  with the merges that landed them (`--ref origin/main --since 2026-10-04`,
  measured 2026-10-11 at `bc2924fe`: on the plain walk one strike read as a
  reopen and a second strike, 196 snapshots, and the column summed to 365
  against 85 + 40 with no warning; first-parent, 75 snapshots and
  126 = 87 + 39). The report now places every
  strike in the column (standing at the last snapshot, undone by a later
  reopen, reopened and struck again, or pruned from the file after it),
  prints the terms that are there, carries them in the JSON as
  `struck_column`, and WARNs on a strike it cannot place. The header counts
  the commits off the first-parent line, and the `--from` refusal says when a
  hash sits on a lane. A linear ref reads the same either way (the `record`
  ref: 104 commits on both walks that day).
