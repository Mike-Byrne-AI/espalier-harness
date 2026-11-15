### Fixed

- **The nested-repo warning no longer tells you to force a worktree's
  removal.** SessionStart's warning about a nested git repo in the working
  tree gave every one the same remedy, `git worktree remove --force <path>`
  or deleting the folder. Claude Code leaves an agent's worktree behind only
  when it holds changes, so with the session catch-up off (the default
  outside this repository) the worktree the warning named was the one whose
  uncommitted work the flag throws away. A worktree of your repository is
  now told to run the plain `git worktree remove <path>`, which git refuses
  while the worktree holds uncommitted changes or untracked files, so the
  work is yours to commit or move first; the line says its ignored files go
  with it. A nested clone, which that command cannot remove and which may
  hold commits no other copy has, is told to move it out of the working tree
  or add it to `.gitignore`. Each kind gets its own line, sorted by reading
  git's worktree registry on disk, so the start runs no extra command. The
  session catch-up's `Worktrees:` line, for a worktree it kept because it
  holds ignored files, now names the plain removal too: git takes such a
  worktree without the flag, and the flag would also have dropped anything
  written into it after the line was printed.
