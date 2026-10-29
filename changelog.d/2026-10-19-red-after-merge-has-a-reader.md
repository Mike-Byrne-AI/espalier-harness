### Added

- **The post-merge check verdicts have one home, and the board reads them every
  tick.** `tools/cc/_post_merge.py` (standard library, loaded by the SessionStart
  hook by path and imported by the ship driver and the board as a sibling) holds
  the check-state sets, the outcome of one rollup row, the latest run per check,
  the banner's per-pull-request ownership rule, and a per-check transition rule
  that walks the merges in merge order and names the merge each verdict has held
  since: a newer merge's green run takes a check name from an older merge's red
  only when it started after that merge landed, else it is printed beside the
  red; a cancelled or stale run is no verdict; a skipped leg supersedes nothing;
  replayed at an instant, a run started after it is dropped and one finished
  after it reads as still running. The board gains a `checks:` line after
  `main:` (`portability (windows-latest): red since #313 (merged 2026-10-18
  13:26Z, the leg finished 13:57Z), green on #312`; `new:` on a first mention;
  a check with no verdict on any merge named, never green) and appends each red
  transition's first mention to `.espalier-state/board-checks.jsonl`, so
  red-to-first-mention is derived from a record; a red older than the window is
  never a first mention. `scripts/red_after_merge_census.py` replays the module
  at an instant (`--at`) and buckets red legs by the ledger rows naming their
  failing files (`--classify`), the ledger's file base rate printed beside the
  share.

### Changed

- **The ship preflight and the banner read the one home.** `ship.py`'s four
  check-state sets are aliases of the module's and `post_merge_reds` delegates:
  its lines keep `red after merge: #N <check>` and gain the since and green-on
  clauses, with no author filter (the base's state is every merged lane's). The
  SessionStart hook keeps no copy of the rule; without the module beside the
  hooks its pull-request block is one voiced line, `pull requests unread
  (tools/cc/_post_merge.py is not beside the hooks)`, and a module that will not
  load is caught, never the banner's crash. The banner's five-row `Merged:` line
  keeps the per-pull-request rule its pins carry (no run start times), and the
  difference from the board's start gate is pinned, not drift. The portability
  workflow's header says its verdict is read after the merge, and by whom.
