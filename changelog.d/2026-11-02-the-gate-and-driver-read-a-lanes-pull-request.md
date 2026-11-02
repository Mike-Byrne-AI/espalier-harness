### Fixed

- **A lane's pull request is read from origin, not from what the branch
  tracks.** The Stop hook's handoff gate and the ship driver read a merged
  lane's leftover remote ref as a lane's own, so a lane started again under
  that name opened beside the seat's other pull request with no hold; an own
  ref whose tip the default branch already reaches is now a merged lane's. A
  lane the gate held and that was then pushed by hand, with no pull request
  opened, is asked for once the hold lifts, from the re-check's own listing.
  Whether a lane's work is on origin is one count of origin's refs, so the
  by-hand arm no longer calls a merged, pruned lane never pushed, the window
  check no longer counts another remote, and the SessionStart catch-up moves
  a merged lane pushed without `-u` (its tip off main's first-parent chain)
  and says a remote branch exists only where origin lists one.
- **A red base's clearing is never held.** The handoff gate held a `revert/`
  lane, and the fix forward the dispatcher ruled, behind the seat's other open
  pull request, while the ship driver opens both beside it. The gate now asks
  the driver's own predicate and rulings (the mail channel's local refs first,
  one capped `gh run list` only where a ruling names the lane), blocks with
  the ruling's `--base-red-ruled` id, and its hold's re-check reads the same
  exemption.
- **`ship.py preflight` forecasts every state refusal in the list `open`
  runs before its push.** Its forecasts were a hand-kept copy of `open`'s
  checks and missed five, the one-pull-request-per-seat hold among them.
  `open`'s state refusals are now one list, `PRE_PUSH_CHECKS`, which `open`
  runs and `preflight` forecasts in `open`'s own words; the refusals of the
  steps after it (the merge-first step, the deletion check, the marker) are
  said where they happen. A test follows `open_pr`'s calls down to its push,
  so a refusal added outside the list and its named allowlist fails.
