### Fixed

- **The nested-repo warning no longer tells you to remove another session's
  worktree.** A worktree under `.claude/worktrees/` that the session catch-up
  did not judge at this start (a resumed or compacted session, every start
  with the catch-up off, which is the default outside this repository, or a
  worktree it had no time left for) was told to run `git worktree remove
  <path>`. Claude Code does not lock the worktree of a session started with
  `claude --worktree`, and git removes a clean worktree, so following the
  line could pull a running session's checkout out from under it; it took a
  worktree stopped in the middle of a rebase the same way. Such a worktree is
  now pointed at the catch-up's own dry run, `tools/cc/checkout_sync.py` with
  no flag, run from the session's own shell, which says which worktrees may
  go and why each other one stays (a live session in it, a lock, an
  operation in progress, commits not in `main`, ignored files); run from
  another terminal while that session is open, it judges none and says so.
  Where that script is not deployed, the line names
  `espalier upgrade --execute` first. A worktree that a recent session marker places a
  session in, its own or one the main checkout's session moved into, is not
  named at all, the same rule the catch-up keeps it by. A worktree elsewhere
  in the working tree keeps the plain removal. The catch-up's own warning
  for a missing `tools/cc/checkout_sync.py` now names `espalier upgrade
  --execute` too: a plain `espalier upgrade` only previews.
