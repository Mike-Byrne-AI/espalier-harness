### Fixed

- **A leftover Claude Code worktree folder is no longer read as your
  project's files.** When a worktree removal is interrupted (on Windows it
  stops at the first locked file), the folder under `.claude/worktrees/` can
  lose its `.git` link. Espalier's scanners, its freshness check, build
  staging, and the reflect and file-list walks then read it as
  part of your tree, and the freshness check could fail on a fragment id the
  leftover folder repeated. They now leave `.claude/worktrees/` out by name as
  well as by its link, as the test suite already did.
