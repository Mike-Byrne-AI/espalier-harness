### Added

- **The board's `records:` line: a row per active seat per day, read as a
  debt.** For each seat with a checkout here, a live claim or a job, the board
  prints its lanes merged since its newest Session Log row on the base
  (`win: 9 merges since its last row (2026-10-15)`; `no row on origin/main`
  where it has none), counted in the writer's local day over the last 100
  merges through the one merged read's lane fields (`_post_merge.read_merged`
  takes a field list; `LANE_FIELDS` sits beside `MERGED_FIELDS`, which is
  unchanged). The count is the record loader's `lanes_since_row`, which the
  ship driver's new `seat_row_debt` shares, so the board and the driver never
  disagree; a row parked on the seat's records ref counts and is said to be
  parked (the board now fetches the records refs beside the mail); a count
  the read stopped short of is a floor and says so; lanes no claim names are
  counted apart; a lane's seat is the machine whose latest claim or release
  names it, a release counting only from a machine that claimed it (a
  dispatcher's lane release no longer moves the lane); a read that fails is
  unread, never zero. Over 2026-10-16 and 10-17
  three seats merged 2 to 11 lanes a day with no row from any of them, and
  29 of 48 early ships since 10-16 were followed by the seat's row within a
  day. The driver's `open --early` refusal at a cap lands in a later lane,
  after a window of board lines.
- **Operator calls ride the mail channel.** A request whose text opens with
  `OPERATOR CALL:` (`mail.OPERATOR_CALL_PREFIX`, `mail.is_operator_call`) is
  the dispatcher's question to the operator; the board's asks header counts
  them apart (`asks:     3 open, 2 operator calls ...`), every seat sees them
  with an age, each row tagged `(operator call)`, and the ruling is the
  dispatcher's ack naming the request's full id, on origin; an ack from any
  other seat leaves the call open.
  The seat brief and the parallel-work protocol's assign-authority paragraph
  send the dispatcher there instead of to the open calls in `cc/GOAL.md`,
  which keeps the goal, the priorities and what is owed.
- **The census's dispatcher row names the jobs live at the day's end**, per
  seat (`scripts/seat_day_census.py --seat <seat> --date <day> --as-row`): the
  releases it owes, which the row lacked while the JSON carried them.

### Changed

- `/handoff` step 2 says the dispatcher derives its row's body from the census
  first and files it under its seat; step 7 says what `cc/GOAL.md` keeps on a
  repository with several seats. `/inbox` Step 4 and the board-line notes, and
  `docs/WORKFLOW.md`'s parallel-seats bullets, describe the `records:` line and
  the operator-call count.
