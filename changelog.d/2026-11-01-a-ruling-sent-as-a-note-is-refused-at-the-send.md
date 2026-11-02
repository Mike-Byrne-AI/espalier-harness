### Fixed

- **The mail send refuses a fix-forward ruling that would rule nothing.**
  A fix-forward ruling counts only as the dispatcher's ack whose text opens
  with `gridlock: fix forward run <id>` (the red post-merge run's id in
  digits) and whose `--lane` names the fix lane. The send verb took any other
  message under that head and sent it: a note, request, claim, release or
  assign; an ack with `<4123>`, `#4123` or no id after the head; an ack with
  no `--lane`; one from a worker under a named dispatcher. Each landed on the
  channel and ruled nothing, and the held seat learned so only at `ship.py
  open --base-red-ruled`. `tools/cc/mail.py` now refuses each of these at the
  send, on `--dry-run` alike, and names the shape to take. A worker is told
  to send the dispatcher a request under another head; a non-ack is told
  `--type ack --ack <the held seat's last message> --lane <the fix lane>` and
  where the full id is printed. While the dispatcher setting cannot be used,
  no ack rules. A `gridlock:` note under any other head still sends.
  (`DEF-4074`)
