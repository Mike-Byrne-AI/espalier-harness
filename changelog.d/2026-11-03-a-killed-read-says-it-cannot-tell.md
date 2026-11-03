### Fixed

- **A git read the session-start catch-up or the worktree reaper had to cut
  off no longer answers as if it had succeeded.** On a loaded box a read
  killed at its cap read as a no: a fetch that never landed printed nothing,
  as if the checkout were current; a killed read of origin's branches let
  the catch-up switch away from, and delete, a lane whose remote branch still
  existed; a killed worktree list let it move `main` under another checkout
  that held it (git before 2.43 does not refuse that); and a killed list
  after a removal that worked reported the worktree as not removed. A read
  that does not answer is now counted apart from a git that answered with a
  failure, the move or removal resting on it holds, and the `Checkout:` and
  `Worktrees:` lines say how many reads did not answer and when origin was
  not reached, whatever the state (`Checkout:  current (origin not reached;
  compared with the last fetch)`).
- **The worktree reaper removes a worktree whose commits are already on
  `main` as cherry-picks.** It asked only whether the worktree's HEAD was an
  ancestor of `main`, so a fan-out agent's worktree whose change a lane took
  as a cherry-pick was kept, as `<n> commit(s) not in main`, on every
  session's banner. It now reads which commits `main` lacks by patch; a
  worktree on a branch with none goes and its branch stays, a merge commit
  always counts as one `main` lacks, and a detached HEAD still goes only by
  ancestry, since nothing keeps its commits after the removal.
