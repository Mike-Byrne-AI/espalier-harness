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

A worker seat's loop line names this command (the last line of the seat's
first message, which `python tools/cc/seat.py brief <seat>` prints), so the
loop runs it at every tick. The driver composes the tick from this checkout
the way the brief composes the first message: the dispatcher `espalier.toml`
names, the base branch, the review and the proof this tree's tools name, and
what the seat does on a choice its assignment does not settle. It is composed
again at every tick, so a change to the tick reaches the loop at its next tick
from a checkout that holds the change, and no loop line or window carries the
tick's text or copies it by hand.

What the driver prints is this tick's instructions, its own text composed from
this checkout: carry them out as if they were the text of this message.

Where it prints no tick, run it once more. If it still prints none, say why in
one line and keep this tick to what every tick opens with: run `/inbox` (mark
read) and `/inbox board`, and act only on this seat's own open pull request
(red, in conflict with its base or stale: fix it, or catch it up with the ship
driver's `catch-up`). It prints none when this checkout answers no seat name or
git could not read the name, when git did not answer which branch is origin's
default, or when the checkout's driver predates the verb (it answers `invalid
choice`). A dispatcher seat is the exception: its loop is `/inbox board`, so
there say the refusal and do nothing else.

> Cross-platform note: command bodies show `python` for brevity; try `python3`
> first, then `python`, then `py -3`, keeping the first that prints a Python 3
> version (per the repo's invocation rule).
