### Fixed

- **The board's `jobs:` section ends naming each seat under two live jobs,
  and the seat-day census counts the ticks a seat stood under two.** The
  section printed one row per live job, so a seat's depth was a count a
  reader made by hand and a seat holding none had no row at all; the
  dispatcher keeps each worker at two (Core Rule 15: one open pull request
  per seat, the next job built while the first is in CI) and held which seats
  were short in memory between ticks, which Core Rule 14 says never to do:
  air-work sat idle from 03:27Z to 06:38Z on 2026-10-30. The section now ends
  with `under two: <seat> (<n>), ..., of N seats (the seats line names A, the
  jobs B, the dispatcher D apart)` from the assigns it already folds, over the
  seats the `seats:` line names (its quiet fold left out) and the jobs' seats,
  the dispatcher apart; `none of N seats` when every one holds two or more;
  no line while the mail is unread or the dispatcher setting is unusable;
  computed where it renders, never stored. `scripts/seat_day_census.py`
  counts, per worker seat per UTC day, the ticks of the dispatcher's cadence
  (`tools/cc/seat.py::TICK_MINUTES`, read by path, sampled from 00:00Z) at
  which the seat held fewer than two live jobs, each job live from its assign
  to the release that closed it by the fold's own pairing, a re-send keeping
  it one and moving it where it names another seat, in the `under_two` table,
  a report line per day and `under two at n of m ticks` on the seat's day row.
  The inbox command body carries the line. (`DEF-5034`)
