### Added

- **A seat driver, `tools/cc/seat.py`, lists, launches and retires a clone's
  seats.** `list` names the clone and each worktree under `.claude/worktrees/`
  with its seat name, branch and head, the live sessions in it, its live claims
  and jobs on the mail channel, and whether the checkout-sync removal rules
  would let the worktree go. `launch <seat>` resolves the seat to the clone or
  to its worktree, creates a missing worktree from the base branch with the
  `.worktreeinclude` files copied in, names it, refuses a checkout another
  session occupies (naming the pid, its start and its entry point) and one
  whose occupancy cannot be told unless `--unchecked`, puts the seat's own
  `.venv` first on `PATH` where one exists, sets the maintenance switch only
  with `--maintenance`, and runs `claude` there with the operator's arguments
  passed through after `--`, or prints the one command line with `--print`.
  `retire <seat>` judges the removal first, then releases the seat's live
  claims from inside its worktree under its own name, refuses a seat still
  holding the dispatcher's jobs unless `--return-jobs` hands them back, and
  removes the worktree under the same rules the SessionStart reaper uses,
  unlocking the lock a headless run leaves behind and saying so. The driver
  joins the deployed tool set.
- **One occupancy oracle in `tools/cc/checkout_sync.py`.** `sessions_in` places
  each live entry of Claude Code's session registry in the deepest registered
  checkout that holds its working directory (paths compared case-folded, since
  the registry spells one drive two ways), carrying its kind, entry point and
  start time, and drops an entry whose pid was reused; `occupancy` answers from
  the registry, or from the session markers when the registry cannot be read,
  and never reads an empty marker list as an empty checkout.

### Changed

- **The ship driver refuses a push from a checkout two live sessions share.**
  `open`, `handoff` onto an open pull request, `lane` and `catch-up` stop
  before anything moves when the registry names two or more live sessions in
  the checkout, since both share one branch and one index and a push from
  either ships the other's commits; `preflight` says the same. Only the
  registry can refuse: an unreadable one, or the session markers alone, is a
  note and the push goes ahead, and `ESPALIER_SHARED_CHECKOUT_OK=<reason>` lets
  a push past an entry the registry got wrong and records the reason. The
  `/ship` body's refusal list names it.
