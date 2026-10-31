### Fixed

- **A gridlock ruling no request waits on can ride a note, and the seat-day
  census counts it.** The census counted `gridlock:` on the dispatcher's acks
  alone, but a gridlock no seat asked about has no request open: on 2026-10-31
  the dispatcher re-armed a held window by a note opening with the word, and
  the day row read two rulings where three were made.
  `scripts/seat_day_census.py` now counts the marker on the dispatcher's ack
  or note (`RULING_KINDS`; every seat's where none is named), never on a
  worker's message, and names the note's id on the day row beside the acks'.
  The dispatcher brief (`tools/cc/seat.py::SELF_HOST_GRIDLOCK`), Core Rule 15,
  the parallel-work protocol, the `/inbox` body and the mail driver's marker
  comment say a note carries the ruling where no request waits on it. The
  brief now also says the marker is the message's first word, so a seat's name
  goes after it (37 of the dispatcher's 46 notes from 10-25 to 10-31 opened
  with a seat's name), and that a stopped worker and a fix-forward on a red
  base are always answered by an ack (`--ack` takes any message id; the ship
  driver reads the fix lane from an ack alone). Day rows already written are
  frozen and keep their figures. Self-host only: neither the census nor the
  gridlock rule reaches an adopter's tree. (`DEF-4060`)
