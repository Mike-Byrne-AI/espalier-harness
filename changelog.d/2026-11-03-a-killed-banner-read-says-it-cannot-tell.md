### Fixed

- **A session-start banner line whose read was cut off says so, instead of
  answering as if the read had succeeded.** On a loaded box a read killed at
  its cap, or never started because the start's time was spent, printed the
  same as a clean answer: no `Open PRs:` or `Merged:` line (as if nothing
  were open or merged), no `Loose:` line (as if nothing were loose), no
  `Engine:` line (as if the engine were this checkout's), no `Merging:` line
  (as if the branch had no rules this reader could see), and no recent
  commits. Each line now says the read did not answer, a merge whose pull
  git could not check is counted rather than read as pulled, and a nested
  repository scan that did not finish warns. A killed read of the remote's
  default branch no longer stands in as `main` for the merge rules, and the
  board says so when its base is a guess.
- **`seat.py` no longer guesses `main` when git does not say which branch is
  origin's default.** Creating or retiring a seat, and composing its first
  message, refuse with a retry; the recipe for a seat whose worktree is gone
  names `origin/HEAD`. A killed ignore check, worktree list or branch
  deletion during seat creation is said, never read as an answer.
