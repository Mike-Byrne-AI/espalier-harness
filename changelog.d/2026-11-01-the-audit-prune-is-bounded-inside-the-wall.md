### Fixed

- **A large audit store no longer cuts the SessionStart banner.** Every start
  demotes audit logs older than 30 days, and to judge a log's age it read the
  first line of up to 5,000 logs, in name order, with no time bound of its
  own. On a Windows box with 5,695 logs those reads took 11.7 s, so the
  banner was cut at its 13 s wall inside the prune, and nothing after it ran.
  The prune now reads the oldest name date first (`<slug>-<YYYYMMDD>.log`),
  stops at a 1.0 s bound inside the hook's own budget, and adds a NOTES line
  when it stopped with logs named before the window still unread; the next
  start goes on. The ledger probe checker (`tools/cc/check_ledger_probes.py`)
  handed every probe the launching shell's audit store, so a probe that
  drove a hook wrote its record into your home store under a temporary
  tree's name; each run's probes now share a temporary store of their own.
  (`DEF-3022`)
