# Conventions

The patterns this repo actually uses — naming, structure, error handling,
test shape. Written so a new contributor (or a coding agent) adopts what is
already here instead of inventing a second way to do the same thing.

> Espalier seeded this file near-empty as a starting point. It is yours —
> unmarked, refreshed on re-init only while it still matches the copy it was
> deployed from, otherwise left exactly as you left it, and safe to rewrite
> completely.
> `/analyze` grounds the harness on your codebase and fills this in, then
> flags drift when the code and this file disagree.
>
> It ships near-empty on purpose: a convention is only worth documenting
> when it describes what *this* codebase really does. A borrowed style
> guide reads as authoritative while quietly contradicting the code.

## What belongs here

- **Naming** — modules, classes, functions, tests; the shape a reader
  should expect before opening a file.
- **Structure** — where a new module goes, which layer may import which.
- **Error handling** — exception types, what gets logged, what gets raised.
- **Tests** — file naming, fixture patterns, how cases are grouped.
- **Commits** — message format, what belongs in one commit.

Document the pattern that is already dominant in the code, and note the
exceptions rather than pretending they do not exist. If a documented
convention no longer matches what the code does, the file is wrong — fix
it here, or change the code and say so.

Delete these prompts as you replace them with real entries.
