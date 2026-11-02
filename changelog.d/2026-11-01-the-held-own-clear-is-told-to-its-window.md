### Fixed

- **A window whose own-clear is held now hears why, and what resolves it.**
  The own-clear mod holds a window's clear while something is in flight (a
  tracked edit, HEAD moved since the handoff, a plan in progress, a git read
  that failed) and said so on its status line alone, so the dispatcher's
  window sat held for nine hours and 36 loop ticks on 2026-11-01 and the
  banner elsewhere read its clear as never asked. The mod now writes the hold
  on its marker (the cause, since when, and the turn ends it has held, taken
  off at the ask); the prompt router tells the held window on every prompt,
  with the verb for its cause (an edit this window made is committed and
  handed off, any other is left to the operator; `ship.py arm` after a pull,
  `/handoff` after a commit of the lane's own; the plan finished or reset), a
  hand `/clear` ending it too; and the banner's `Own-clear:` line names a hold
  in a window elsewhere. Both own-clear advisories now say a pull request's
  red and a red main's revert are not new work.
