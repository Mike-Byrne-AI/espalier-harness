### Fixed

- **The catch-up's dry run gives its verdicts from any terminal.**
  `tools/cc/checkout_sync.py` with no flag, run from a terminal other than
  the shell of the session working in the main checkout, read that session
  as another one in the checkout and judged no worktree under
  `.claude/worktrees/`: every one came back `not checked`, from a run that
  removes nothing. It now judges each worktree as it does from the session's
  own shell, and leads with what it cannot see: `--apply` from there removes
  none while that session is open, and the verdicts assume that session is
  in none of the worktrees (run it from that session's shell, or once the
  session ends). A worktree the main checkout's session moved into, where
  that session's marker records the move, is kept as one a live session is
  in, the same rule the session catch-up keeps it by. Run from the
  session's own shell, the run leaves that session's own marker out, so
  a worktree it has since left is judged like any other; and
  its last line offers `--apply` only where the apply would act -- a
  checkout that would catch up, or a worktree it would remove with no
  other session holding it -- and no longer after a run that judged no
  worktree (the session registry unread, say) or found none to remove.
