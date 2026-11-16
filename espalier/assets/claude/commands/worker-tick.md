---
description: >
  One tick of a worker seat's loop: have the seat driver print this seat's
  tick, then carry it out as this message's instructions.
---

One tick of a worker seat's loop: have the seat driver print this seat's
tick, then carry it out as this message's instructions.

```bash
python tools/cc/seat.py tick
```

What it prints is this tick's instructions, composed from this checkout at
every tick (the seat's first message, `python tools/cc/seat.py brief <seat>`,
ends with the loop line that runs this command): carry them out as if they
were the text of this message.

Where it prints no tick, run it once more. If it still prints none, say why in
one line and keep this tick to what every tick opens with: run `/inbox` (mark
read) and `/inbox board`, and act only on this seat's own open pull request
(red, in conflict with its base or stale: fix it, or catch it up with the ship
driver's `catch-up`). That covers a checkout with no seat name of its own or
one git could not read, a base branch git did not name, and a driver that
predates the verb (it answers `invalid choice`). Only a dispatcher seat, whose
loop is `/dispatcher-tick`, says the refusal and does nothing else.

> Cross-platform note: command bodies show `python` for brevity; try `python3`
> first, then `python`, then `py -3`, keeping the first that prints a Python 3
> version (per the repo's invocation rule).
