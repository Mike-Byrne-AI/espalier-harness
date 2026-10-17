### Fixed

- **A start whose catch-up moves a helper the hook has loaded keeps its
  banner lines.** SessionStart imports its helper modules before the
  checkout catch-up moves the tree to `origin/main`. When that move changed
  one of them, a module the hook first loaded after the move could import
  the new file against the old helper still in memory. That banner line
  (the mail, the seat, the merge rules or the memory index, among others)
  was then replaced by an import-error warning that named neither the move
  nor the cure. Now, when the move changes a helper the
  hook has loaded, the rest of the start runs in a fresh process that
  imports the moved tree whole, and the `Checkout:` line says so. That costs
  about a tenth of a second, and only on those starts. If the fresh process
  gives no banner in time, a short banner names the move. If it fails at
  once, the hook finishes the start itself and the `Checkout:` line names
  each line the move cost, so you know the next start reads it.
- **The worktree reaper keeps a worktree whose seat's claims it cannot
  read.** A seat named for its worktree alone keeps that worktree while it
  holds a live claim. When the mail driver was deployed but did not import,
  the reaper read that as no claims and could remove the worktree under
  the claim. It now keeps the worktree. Only a deploy without the mail
  driver reads as no claims.
