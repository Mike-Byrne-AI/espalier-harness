### Fixed

- **A seat holding a job keeps its worktree.** SessionStart's worktree
  clean-up kept a worktree under `.claude/worktrees/` only while the seat
  named for it held a live claim on the mail channel. A seat between lanes
  (its lane's push released its claims, and the dispatcher had given it the
  next job) was removed at the next start, with the job still live and no
  seat to work it. A live job from the dispatcher now keeps the worktree too,
  and the `Worktrees:` line names the jobs and
  `seat.py retire <seat> --return-jobs`. A `dispatcher` setting in
  `espalier.toml` that does not read keeps it as well, and `seat.py retire`
  refuses then; `seat.py list` says no seat's jobs are counted. A worktree
  holding an ignored file is no longer told to `git worktree remove --force`
  while its seat holds claims or jobs.
