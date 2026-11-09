### Fixed

- **The board names each stopped seat with its live jobs and marks the job an
  operator call parks, and the worker tick names that job in its stop.** A
  seat stopped on one job's open operator call idled its other job too, and
  the `under two:` tail still read the seat full (`none of 1 seat`), so
  neither job moved and no third was given. The dispatcher's approved shape is
  to release the parked job at the stop and re-send it at the ruling. That
  release is now read from the board every tick instead of remembered: under
  the tail, each seat with a `stopped:` request open gets a line, `stopped:
  <seat> (stop <id>) holds <job> (assign <id>); ...` (`holds no job` where it
  holds none), every id the full one a release names. A job is marked `parked
  on <call id>` only where an open stop of its seat names an open operator
  call and the job (its assign id or the id's suffix, one of its ledger ids,
  or the stop's lane), and that seat's line ends `release the parked job, ack
  the stop, and re-send the job at the ruling`. The ack is what frees the
  seat, on either tree's worker tick, since a release names no stop. Nothing
  asks again once the job is released or the call is ruled, and a stop of
  another kind (a refusal, a conflict) names the seat and its jobs and asks
  nothing. The count is left as it is, since a stopped seat counted short
  would be sent a job while it only reads mail. This repository's worker tick
  (`tools/cc/seat.py::SELF_HOST_PROCEED`) now has a stop name the assign id
  of the job it parks and says the dispatcher's release, ack and re-send; the
  protocol's stop paragraph and the inbox command body say the same. A seat
  already looping keeps its old tick until it is re-primed, and its stops
  name no job, so nothing is marked for it. The re-send at the ruling is read
  from the board too, by the entry below. (`DEF-3038`)
