### Changed

- **The dispatcher's board loop runs its own command, `/dispatcher-tick`.**
  The dispatcher seat's first message ended with `/loop 15m /inbox board`, and
  a recurring command puts its whole body into the window at every fire:
  `/inbox`'s ran to about thirteen thousand tokens a tick. The loop line is now
  `/loop 15m /dispatcher-tick`, and that command has the seat driver print the
  board tick (`python tools/cc/seat.py tick --role dispatcher`): a few lines
  that name `tools/cc/board.py`, the dispatcher's duties and the board section
  of `/inbox` to read only for a line the reader cannot read. The tick is
  composed from the seat's checkout at each fire, so it names the seat and the
  base branch, and an adopter's dispatcher, which proposes assigns, releases
  and the revert to the operator, is told that rather than this repository's
  own duties. `/dispatcher-tick` asks the `tick` verb for the dispatcher's
  role and `/worker-tick` takes its default, the worker's; the verb refuses a
  seat of the other role, so neither loop runs the other's tick. A board loop
  started by hand is not matched by `/handoff`; re-create it from the new
  line. The command count is 20.
