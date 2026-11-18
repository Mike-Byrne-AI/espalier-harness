### Fixed

- **The seat driver sees every checkout the board sees.** `seat.py` read only
  the worktrees under `.claude/worktrees/`, so a copy made by hand elsewhere
  (a reviewer's scratch worktree) that answered a seat's name was a twin on
  the board and nothing to `launch`, `brief`, `tick` or `retire`, which acted
  as if the name had one checkout. The board, `seat.py` and SessionStart's
  worktree naming now read one list: every checkout git lists, each by the
  name its mail is written under. A twin outside the folder is refused like
  one inside it, and a main checkout given a `--worktree` name is read by that
  name. The clone's own name is the main checkout's, so each other checkout
  answering it is given its own command (a rename, or the naming steps the
  board prints), after the words that a session in it releases its claims
  first, never left to the operator's guess. `seat.py launch` unsets a seat
  name `git worktree add`
  copied into a new worktree from a main checkout's own config. `seat.py
  list` shows a worktree outside the folder that answers a name of its own
  or holds a session, never offered for removal, and `retire` refuses one
  before anything is sent. The board's naming remedy gives its two commands
  one a line, which Windows PowerShell 5.1 runs (it does not parse `&&`).
