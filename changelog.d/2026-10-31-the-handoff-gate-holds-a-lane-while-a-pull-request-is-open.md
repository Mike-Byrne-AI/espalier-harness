### Changed

- **The Stop hook's handoff gate holds a lane while this seat has another
  pull request open.** One open pull request per seat (the parallel-work
  protocol's item 4: the next job is built on a new branch while the first is
  in CI and opened when it merges) and `stop_gate` Gate 5 disagreed on the
  day's commonest shape: a worker committing its second lane while its first
  pull request was in CI was told, by a blocking gate, to hand off now -- a
  gate obeyed opened a second pull request whose CI never tested the first's
  merge, a gate disobeyed was a gate learned to disobey. Now, where the push
  would OPEN a pull request (the branch has no upstream of its own,
  `origin/<branch>`; a branch created from `origin/main` tracks it by git's
  default and is not its own, the very lane the protocol tells a seat to
  start), the gate reads this seat's other open pull requests at its decision
  point: the seat's name first, through the ship driver's new `seat_name`
  (the mail channel's `espalier.machine`; an unnamed checkout or a tree
  without the channel reads nothing, pays no spawn and blocks as before), then
  one bounded `gh pr list` read through its spawn chokepoint (five seconds at
  most, its one network read) in the driver's field set (`OPEN_PR_FIELDS`,
  the one home), the rows attributed by the driver's own `seat_open_prs` (the
  seat whose latest claim or release names each lane, else its `seat:` label;
  each git read now bounded through a `timeout` the gate passes), the
  driver's notes kept off the hook's decision channel. One open: the Stop
  passes without a block, one advisory record per held HEAD
  (`stop_held_handoff`, `details.ahead` and `details.open`, never the branch),
  and `.espalier-state/handoff_gate_hold` names the HEAD, the branch, the
  seat, the rows, the commit count, the first hold's stamp and the read's;
  while it names HEAD the gate asks gh again no more than every five minutes
  (the clock is `HOLD_CLOCK`, one name a test moves), and once none is open
  the hold clears and the block returns, so the gate is the reminder that the
  first lane merged. A re-check that cannot be made keeps the hold one more
  interval and says so once (`stop_failed_open_handoff_prs`). A Stop that
  passes has no channel to Claude, so the prompt router names the hold on
  every prompt while it stands (the branch, the count, the pull request, the
  age); and a new session keeps a hold that names its HEAD -- SessionStart's
  seed of the judged flag stands aside for it, so the gate judges the lane
  again instead of never -- and clears a stale one. The block's text now says
  what the gate read (this seat has no other open pull request; no other is
  open at all; the push lands on the lane's own; the checkout names no seat;
  or the read could not be made -- no `gh`, a timeout, not signed in, no
  GitHub remote, the seat's name unread -- with the wait named) and lists the
  fourth carve-out only then: a read made in this turn naming one of this
  seat's pull requests open, by number, never one remembered from earlier.
