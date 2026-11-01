### Fixed

- **The ship driver refuses a push that deletes files the driver did not
  delete.** `tools/cc/ship.py` read a lane's diff with its base only for the
  approval marker's paths, so a lane head moved onto a newer base with an
  older tree, deleting what other lanes had added since and putting merged
  code back, was pushed and opened like any other lane. `preflight` now
  prints the lane's shape (how many files it adds, modifies and deletes), and
  `open`, and `handoff`'s push onto an open pull request, refuse a deletion
  the driver did not make itself unless `--allow-deletions "<why>"` says why;
  `open` records the reason in the pull request body. The driver's own
  deletions pass: the Session Log prune (read back by its commit subject) and
  a struck ledger row's probe. A `revert/` lane goes through with its
  deletions named. A rename reads as a deletion here, and a release's fold of
  the changelog fragments names its deletions with the flag. Where the box is
  a named seat, modified paths that no claim it sent on the lane names are
  listed, never refused. (`DEF-4064`)
