### Fixed

- **A worker's stop is a request opening with `stopped:`, and the board's
  `asks:` line counts the stops apart.** The worker tick's STOP clause on this
  repository (`tools/cc/seat.py::SELF_HOST_PROCEED`) said only to re-read mail
  on a refusal the seat cannot resolve, a conflict outside its files or a
  decision reserved for the operator, and sent nothing; an adopter's clause
  sent a plain request the board could not tell from a question. So a stopped
  seat showed nowhere: the board's `seats:` line reads a seat's last mail and
  its age, and the dispatcher's past-the-hour gridlock read (Core Rule 15)
  found a stopped seat only by noticing its silence. Both clauses now send one
  request whose text opens with `stopped:` (`tools/cc/mail.py::STOPPED_PREFIX`,
  the sibling of `OPERATOR CALL:`, read by `is_stop` the same way: a request
  alone, at the text's opening, as spelled), which the board's `asks:` line
  already carries with its age; the header counts the stops apart beside the
  operator calls (`asks:     3 open, 1 stopped, 1 operator call ...`) and the
  row ends with `(stopped)`; any ack naming the stop closes it, as a plain
  request closes. The seat-day census counts `stopped:` on a request alone, on
  the sender's row, and the day row's words line gains `stopped: n`. The
  protocol's seat's-side and first-read paragraphs, the inbox body and the
  workflow guide carry the word, and a test holds both tick clauses and the
  census table to the mail driver's constant. (`DEF-5030`)
