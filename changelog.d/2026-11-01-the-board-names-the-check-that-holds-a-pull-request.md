### Fixed

- **The board names the required check that holds a blocked pull request.**
  For every pull request GitHub reports as blocked, `/inbox board` printed
  one fixed phrase, `blocked: a required check or a review holds it`: its
  pull-request list asks GitHub for no check status. So the dispatcher could
  not tell a red required cell from ten still running, while `ship.py status`
  and the SessionStart banner already named the red. The `gh pr checks <n>
  --required` read now has one home, `tools/cc/_post_merge.py::read_required`,
  and the board, the ship driver and the banner all read through it. The
  board reads each blocked row through it, bounded like the banner's read
  (the first `REQUIRED_READ_ROWS` rows within `REQUIRED_BUDGET_SECONDS`; a row
  past either bound says it was not read). It prints the required reds by
  name, with a pointer to `ship.py status`; else `waiting on N running` of the
  required checks; else that nothing required is red or running, so a review
  or an unreported required check holds it. A read that fails names the
  command. (`DEF-4063`)
