### Fixed

- **The prompt router's handoff-hold line says when the hold was last read,
  and says so when that read is stale.** While the Stop hook holds a lane
  behind another of the seat's open pull requests, the router names the hold
  on every prompt; only a Stop reads gh again, so prompts that came with no
  Stop between them were told a pull request that had merged hours before
  still held the lane, with nothing to do. The line now gives the last read's
  age beside the hold's, and past the gate's five-minute re-check, or after a
  re-check that could not read gh, it says the record is stale and that the
  next Stop with nothing in flight, or `/handoff`, reads it again. A Stop now
  removes a hold left on an older commit, which had stayed on every prompt for
  the rest of the session after the lane was handed off. The prompt path still
  makes no gh read of its own.
