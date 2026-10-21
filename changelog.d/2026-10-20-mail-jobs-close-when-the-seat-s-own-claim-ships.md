### Added

- **The seat-day census.** `scripts/seat_day_census.py` prints, per seat per
  UTC day, what the mail refs and the merged pull requests say a seat did: lanes
  merged, assigns received, jobs closed by the rule that closed each and those
  live at the window's end, jobs re-sent after the claim rule closed them (each
  named, rows apart from packs, so a pack's next wave is told apart from a row
  that stayed live), the releases the seat sent naming an assign (split into
  those that closed a live job, a dispatcher's decision, and those that named a
  job already closed, hand work the third rule makes needless), requests and
  the median minutes to their answer,
  Session Log rows, and the messages carrying START, `redirect:` or `shelved:`.
  The dispatcher's row adds what it sent: its assigns and how many were new
  jobs (a re-send of a live job is not one), and the day's worker requests it
  answered. A read that failed (the fetch, `gh`) is said in every form, never
  printed as a zero. `--seat S --date D --as-row` prints one seat's UTC day as a
  Session Log row body, the figures only, and writes nothing; `--since <stamp>
  --jobs N` ends the window where the dispatcher gives its next new job after
  the Nth, for a measure counted in jobs. It reads the
  closing rules from the fold's own record, so the rules keep one home. Read
  over the refs of 2026-10-18 (UTC): 25 assigns sent to the three worker seats,
  all new jobs; 27 closures that day (24 by the seat's own claim, 1 by an
  assign's lane, 2 by a release naming the assign; four of them of jobs given
  on 10-17); 2 jobs live at the day's end; and 28 releases the dispatcher sent
  by hand naming an assign, 26 of them naming a job already closed.

### Changed

- **A job closes when its seat's own claim ships.**
  `tools/cc/mail.py::live_assignments` closes a job on a third release beside a
  release naming the assign and the assign's own lane released: for a job that
  names no lane, a release from the seat the job was given to, naming a lane the
  seat began (its first claim there) after the job was given and on which its
  live claims together named every id the job names. The ship driver's lane
  release at a push already names the lane and a claim already names the rows,
  so a job assigned by its ids no longer needs a release by hand: of the 25 jobs
  given on 2026-10-18 (UTC), 22 were closed by a hand release, and the new fold
  reads 21 of the 25 closed by the seat's own claim (1 by an assign's lane, 1 by
  a hand release, 2 live). A claim's ids name what a lane touches, so a lane
  whose claims were live when the job came does not close it (a row the current
  lane touches, queued as the seat's next job, waits for a lane begun for it; a
  push releases a lane's claims, so a follow-up claim after it begins the lane
  again), and a re-send of a live job starts its clock again. When asked, the fold also
  records which release closed which job and by which rule. A malformed `ids`
  or `classes` field on another seat's message costs that message, never the
  fold.
- **`retire` and the worktree reaper release an abandoned seat's claims by
  id.** The recipe `tools/cc/seat.py`'s `retire` prints for a seat whose
  worktree is gone, and the reason `tools/cc/checkout_sync.py` gives for keeping
  a worktree whose seat holds claims (naming the ids), now release each claim
  by its id, as inbox Steps 3 and 5 now say: a lane release from the seat would
  read as its lane shipped and close the job it was given, so a retired seat's
  jobs would leave the board without being handed back.
- **Every board list says its size.** `tools/cc/board.py`'s `open PRs:`,
  `seats:`, `jobs:`, `claims:` and `overlaps:` headers name their count on their
  first line (`jobs:     (dispatcher air) 2 live: ...`), so a reader that keeps
  only that line still sees how many rows there are; each count is the length
  of the list the section renders, a count on a partial or capped read says so
  (`N pairs among what was read`, `30+ open (the first 30)`, and the overlaps of
  a pull-request list cut at its read limit count as partial, on the board and
  in the ship driver's push notice), and the empty forms are unchanged. The ship driver's push notice, which prints the board's
  overlap lines, carries the pair count too.
- **This repository's dispatcher brief carries the rules for its reports**: a
  count names its population, a setting a tool computes is quoted from the
  tool, and the day's figures come from the census, never carried by hand. They
  ride a self-host slot of `tools/cc/seat.py`'s brief, so an adopter's brief is
  unchanged byte for byte.
