### Fixed

- **The ship driver takes the dispatcher's ruling on a red base.** `open` and
  `handoff` refused every lane but a `revert/` one while the base's newest
  post-merge proof was red, so a red no revert could clear (pytest 9.2.0
  redded `main` on 2026-10-29 outside every suspect's diff, and reproduced at
  the last green base) held every seat about eleven hours until a pull request
  was opened by hand, outside the driver. Both verbs now take
  `--base-red-ruled <ack id>`: the lane lands when an `ack` with that id is on
  the local mail refs, from the seat `dispatcher` names in `espalier.toml`
  (any seat where none is named; the ref an ack rides is its sender, never its
  `from` field), and its text names the red post-merge run by its id, whole;
  no such ack, one on another seat's ref, one naming another run, a dispatcher
  setting that cannot be read, or no mail channel beside the driver refuses by
  name, and a ruling that holds is said at the open and written into the pull
  request body. The refusal and `preflight`'s note name the flag and the run
  id the ack must name; a handoff onto an open pull request names the ruling
  in place of the disarm, and one whose ruling does not hold names both. The
  revert stays the default, and a `revert/` lane needs no flag. Core Rule 15
  and the parallel-work protocol's item 7 carry the fix-forward sentence.
  (`DEF-5035`)
