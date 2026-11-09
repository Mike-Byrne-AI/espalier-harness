### Fixed

- **A job the dispatcher parks on an operator call stays on the board until
  it is re-sent.** Once the dispatcher released a job an open operator call
  parked and acked the worker's stop, nothing on the board linked the job to
  the call, so at the ruling, often hours later, nothing named the job to
  re-send. The board's `stopped:` line now prints the release ready to paste,
  `python tools/cc/mail.py send --type release --ack <assign id> --text
  "parked: <job> on operator call <call id>"`, and a job closed by such a
  release gets a line under the `stopped:` lines: `parked: <seat>: <job>
  (assign <id>; released <id>) on operator call <id>, open` while the call is
  open, then `re-send: ...: operator call <id> ruled by <ack id>: re-send the
  job, or where the ruling drops it: <send>` once the call's sender acks it,
  with the drop ready to paste. An assign of the same job stamped after the
  release, or the drop (a release acking the parked release's full id),
  clears it. Only the machine that assigned the job or the seat holding it
  parks it, and the ruling is read from the call's sender's own ack, the rule
  that closes the call on the `asks:` line. (`DEF-2067`)
