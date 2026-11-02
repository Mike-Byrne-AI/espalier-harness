### Fixed

- **A lane pushed without `-u` reads as pushed, in the Stop hook and the
  ship driver alike.** A branch started from `origin/main` keeps
  `origin/main` as its upstream after a plain `git push origin HEAD`, so
  `ship.py open` held it again as a seat's second lane and `ship.py arm`
  refused it as never pushed, while origin held it all along. Whether a lane
  is on origin as its own is now one reading, shared by the handoff gate and
  the driver: origin's ref for the lane, listed by its exact name, whatever
  the branch tracks, with the lane's unpushed commits counted against it.
  Where that reading is not beside the driver (an older helper kept through
  an upgrade), `open` says the hold was not judged and opens, and `arm`
  refuses; both name `espalier upgrade --execute .`.
