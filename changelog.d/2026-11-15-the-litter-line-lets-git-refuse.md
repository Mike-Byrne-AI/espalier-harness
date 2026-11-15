### Fixed

- **The nested-repo warning no longer tells you to force a worktree's
  removal.** SessionStart's warning about a nested git repo in the working
  tree gave every one the same remedy, `git worktree remove --force <path>`
  or deleting the folder. Claude Code leaves an agent's worktree behind only
  when it holds changes, so with the session catch-up off (the default
  outside this repository) the worktree the warning named was the one whose
  uncommitted work the flag throws away. A worktree of your repository is
  now told to run the plain `git worktree remove <path>`, which git refuses
  while the worktree holds uncommitted changes or untracked files; the line
  says its ignored files go with it, and for a worktree on a detached HEAD
  it says to branch that HEAD's commits first, since no branch keeps them.
  Any other nested repo is told to move it out of the working tree (another
  repository's worktree with that repository's `git worktree move`) or add
  it to `.gitignore`. Each kind gets its own line, sorted by reading git's
  worktree registry on disk, so the start runs no extra command, and each
  line puts its remedy before the paths, so a long list in the banner cuts
  paths rather than the remedy. The session catch-up's `Worktrees:` line, for
  a worktree it kept because it holds ignored files, now names the plain
  removal too: git takes such a worktree without the flag, and the flag
  would also have dropped anything written into it after the line was
  printed. Its line for a worktree whose `.git` link is missing now names
  `git worktree repair` alone, not removing the folder by hand.
