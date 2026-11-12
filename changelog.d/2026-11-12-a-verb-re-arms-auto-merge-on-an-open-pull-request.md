### Added

- **`ship.py auto-merge` arms auto-merge on the branch's open pull request.**
  It makes the same arm `open` makes at creation and reads it back. It is for a
  pull request whose auto-merge went off after it opened (disarmed on a red
  base, disabled by hand) or that was opened by hand. Before it writes, it
  refuses a red base the way `open` does (a `revert/` lane and
  `--base-red-ruled <ack id>` pass), and refuses the way `rebind` does when
  HEAD is not the pull request's head, when the lane holds an unfinished
  handoff's commit, or when the pull request is a draft. If auto-merge is
  already armed, it writes nothing. `rebind`, `catch-up` and `handoff` still
  never re-arm, so a deliberate disarm stays off. `status`, the SessionStart
  banner's `Open PRs:` line and the board's pull request row now name the
  verb where an open, non-draft pull request reads unarmed. Before this, they
  named no remedy, and the verb called `arm` arms the own-clear marker
  instead.

### Fixed

- **`ship.py open` no longer refuses a pull request that gh merged while
  arming it.** `gh pr merge --auto` merges a pull request that nothing holds
  at once, prints nothing, and leaves auto-merge reading off. `open` read only
  auto-merge back, so it refused that lane as "NOT armed". The read-back now
  takes the pull request's state first and says `merged at once`. Its two
  remedies for an arm that did not take now name `ship.py auto-merge` instead
  of a `gh` line typed by hand.
