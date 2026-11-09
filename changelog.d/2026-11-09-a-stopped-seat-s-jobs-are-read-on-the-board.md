### Fixed

- **The board's `under two:` tail names each stopped seat with its live jobs,
  and the worker tick says the dispatcher's release.** A seat stopped on one
  job's open operator call idled its other job too, and the tail still read
  the seat full (`none of 1 seat`), so neither job moved and no third was
  given. The dispatcher's approved shape is to release the parked job at the
  stop and re-send it at the ruling. That release is now read from the board
  every tick instead of remembered: where a seat has a `stopped:` request
  open, the tail goes on with `; stopped: <seat> (stop <id>) holds <job>
  (assign <id>), ...` (`holds no job` where it holds none), every id the full
  one a release names, and, where a stopped seat holds a job, `release the job
  a stop parks on an operator call, and re-send it at the ruling`. The count
  is left as it is, since a stopped seat counted short would be sent a job
  while it only reads mail. The clause sits on the tail line rather than the
  `asks:` rows, which cap at six. This repository's worker tick
  (`tools/cc/seat.py::SELF_HOST_PROCEED`) and the protocol's stop paragraph
  say that the release ends the stop, so the seat acks its own stop and goes
  on with its other job. The inbox command body carries the clause. A seat
  already looping keeps its old tick until it is re-primed. (`DEF-3038`)
