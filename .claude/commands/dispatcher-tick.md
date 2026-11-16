---
description: >
  One tick of the dispatcher seat's board loop: have the seat driver print
  this seat's board tick, then carry it out as this message's instructions.
---

One tick of the dispatcher seat's board loop: have the seat driver print this
seat's board tick, then carry it out as this message's instructions.

```bash
python tools/cc/seat.py tick --role dispatcher
```

What it prints is this tick's instructions, composed from this checkout at
every tick (the seat's first message, `python tools/cc/seat.py brief <seat>`,
ends with the loop line that runs this command): carry them out as if they
were the text of this message.

Where it prints no tick, run it once more. If it still prints none, say why in
one line and keep this tick to the board: run `python tools/cc/board.py` and
act on what it shows under the duties your first message names. That covers a
checkout with no seat name of its own or one git could not read, a base branch
git did not name, an `espalier.toml` whose dispatcher setting cannot be used or
does not name this seat (the verb then reads it as a worker seat), and a driver
that predates the board tick (it answers `unrecognized arguments`, or
`invalid choice` where it predates the `tick` verb). Only a seat whose first
message made it a worker, whose loop is `/worker-tick`, says the refusal and
does nothing else.

> Cross-platform note: command bodies show `python` for brevity; try `python3`
> first, then `python`, then `py -3`, keeping the first that prints a Python 3
> version (per the repo's invocation rule).
