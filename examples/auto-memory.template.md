<!--
  Auto-memory MEMORY.md starter — for Claude Code's machine-local auto memory,
  NOT a repo file.

  Place this at:  ~/.claude/projects/<project>/memory/MEMORY.md
  (the <project> segment is derived from your git repo; run `/memory` in a
  session to open the folder). You — or your agent, once — drop it there.

  Claude Code auto-loads only the first 200 lines OR first 25 KB of this file
  (whichever comes first) at the start of every session, so keep it a short
  INDEX: operator/machine facts + pointers into the committed repo. Push detail
  into topic files (auto memory reads them on demand), or — for anything about
  the harness itself — into the repo's committed `memory/` (see the sorting
  rule below).

  Auto memory is machine-local and never committed; it does not travel to
  teammates or adopters. Only the repo's `ESPALIER_MEMORY.md` + `memory/` + `docs/` do.
-->

# Project auto memory — machine-local Claude auto-memory (NOT the repo's committed `ESPALIER_MEMORY.md`; see `docs/MEMORY_SYSTEMS.md`)

## Router — the source of truth is the repo

This project uses **Espalier-Harness**. The harness governance and its durable
lessons are the source of truth and live **in the cloned repo**, committed:
the repo-root `ESPALIER_MEMORY.md` index, the `memory/` cool-store, and `docs/`. Pull
them with **`/recall <topic>`** rather than re-deriving from scratch.

**Sorting rule — which memory owns a fact:**

> Operator / machine / collaboration → **here** (auto memory).
> Harness / its code / its discipline → the **repo** (`memory/`, `docs/`).

Full model: `docs/MEMORY_SYSTEMS.md` in the repo.

## Operator + machine

<!-- Replace these placeholders with your actual facts. -->

- **Interpreter:** e.g. `python3` (not `python`) on this machine.
- **How I want the agent to work:** e.g. plan before large edits; push only
  when I ask.
- **Commit conventions:** e.g. commit straight to `main`, no branch; trailer
  format your team uses.
- **Local setup quirks:** e.g. tests need a local Redis; sandbox URL is X.

## Load-bearing repo principles (names only — pull full text via `/recall`)

<!--
  Names as a jump-list, not copied content — the committed repo is canonical,
  and copying it here would drift and burn the 200-line budget. Recall the
  full text on demand.
-->

- Make it prove it — `/recall make it prove it`
- The null result is the signal — `/recall convergence`
- A finding is a claim until grep-verified — `/recall untrusted oracle`
- Class-fix scope = every shipped surface — `/recall class-fix scope`
