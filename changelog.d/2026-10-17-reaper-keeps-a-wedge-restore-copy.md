### Fixed

- **A worktree holding the copy a wedge restore saved is no longer removed
  with it.** When the guard is wedged, the one restore it lets through first
  saves the file's bytes under `.espalier-state/wedge-restore/`. The
  session-start reaper read that folder as a cache, so a clean, merged
  worktree under `.claude/worktrees/` was removed at the next session with the
  only copy of the discarded edit inside it. The reaper now keeps such a
  worktree, and its `Worktrees:` line names the copy first, with its path from
  the repository root: read it, keep what you need, then delete it. A copy
  whose bytes its file still holds (the restore's prompt was declined, or the
  edit was put back) does not hold the worktree. Espalier never prunes the
  copies.
