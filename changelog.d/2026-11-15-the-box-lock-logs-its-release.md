### Changed

- **The box lock's log names each release and how long the hold lasted.** The
  log beside the lock file (`<lock path>.log`) named every gated run's acquire
  (`taken`, `waited`, `inside`, `gave_up`, `unguarded`) and no release, so how
  long a run held the lock, and so how full a box was, could not be read from
  it: only the waits behind a hold were there. A run that held the lock now
  appends a `released` line at its release, with the hold's length in
  `held_s` and its start at the take, written while it still holds, so each
  hold's two lines pair in file order. The guard cost census
  (`scripts/guard_cost_census.py`), which keeps its own copy of the holder and
  appends to the same log, writes the same line. A holder that is killed still writes no
  release line (the kernel frees the lock with the process), so its acquire
  line stands alone and its hold's end is bounded only by the next acquire.
