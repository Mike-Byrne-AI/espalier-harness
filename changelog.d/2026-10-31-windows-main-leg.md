### Added

- **An advisory Windows leg runs the serial test files on `main` after each
  merge, and the board names its red.** No check ran on Windows after a merge:
  the only Windows leg is the pull request's path-filtered portability job, 66
  to 81 minutes against a 47-minute median merge, so a red the merge
  combination makes had no Windows reader at all.
  `.github/workflows/post-merge-windows.yml` (this repository's own; `init`
  installs none) runs `scripts/proof_tier.py`'s serial leg on `windows-latest`
  on each push to `main` (measured 2 min 16 s and 3 min 59 s on two dispatched
  runs before it was written; `timeout-minutes` 25, the serial files' longest own mark plus ten; no concurrency group, on a
  0.2-minute median queue), a sibling of the post-merge proof and never a job
  in it, since the proof's readers read a run's conclusion and a flake there
  would ask for a revert. `tools/cc/_post_merge.py` holds the base-run rule
  (the newest verdict among a workflow's push runs, walked back to the
  streak's first red and the green before it; a cancelled, stale, skipped or
  neutral run reads no verdict) and its words, and the board's `_RED` is that
  module's set; `tools/cc/board.py` reads the leg beside the `checks:` line's
  merged read, under its own budget and its own try/except, and prints
  `post-merge-windows (main, advisory): red since <sha> (run <id>)` there, in
  the legs' shape and never on the `main:` line, whose revert rule it cannot
  trip; runs without a verdict newer than a green are named above it; a green leg, a checkout
  without the workflow file (no spawn) and a leg with no completed run print nothing, and a
  failed read is the leg's own line, never the section's `unread`. The inbox
  body's `checks:` bullet says so. (`DEF-977` repinned: the leg gates nothing,
  so the row stays open.)
