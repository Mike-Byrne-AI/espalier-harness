### Fixed

- **A session in a worktree nested in the main checkout's folder no longer
  holds the main checkout's SessionStart catch-up.** The catch-up's check for
  another live session in the checkout placed a session by folder, so one in
  a worktree kept anywhere in the main checkout's folder other than
  `.claude/worktrees/` read as a second session there, and the main checkout
  never caught up while it lived. It now places each session in the deepest
  checkout holding its cwd, read from git's worktree registry on disk with no
  extra process; where that registry cannot be read, the old folder rule
  stands, which only ever holds more. A worktree folder whose `.git` file is
  gone is no checkout, and a session marker's shortened cwd is kept where the
  folder rule keeps it.
- **The SessionStart note names the main checkout as the main checkout.** A
  session in a worktree whose working directory moved into the main checkout
  read "session cwd is inside worktree <the main checkout>"; it now reads
  "inside the main checkout", and a linked worktree is still named a worktree.
