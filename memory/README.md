# Categorized Memory

This folder holds long-form memory entries that don't fit in the
120-line `ESPALIER_MEMORY.md` index.  `ESPALIER_MEMORY.md` is the *hot* surface loaded
into every session by `tools/cc/hooks/session_start.py`;
this folder is the *cool* surface, consulted on demand.

This is the repo's **committed** memory — distinct from Claude Code's
machine-local **auto memory**, which is also indexed by a file named
`MEMORY.md` (`~/.claude/projects/<project>/memory/`, created by Claude
Code itself if one exists). For the full model of
both systems and the rule for which owns what, see
`docs/MEMORY_SYSTEMS.md` (Espalier source repo — not deployed by `init`).

## When to add a file here

- A `ESPALIER_MEMORY.md` Patterns Learned or Decisions row's Notes field would
  exceed ~3 lines of prose — cut the body here, keep a one-line
  summary + link in the index row.
- A research note worth preserving but not load-bearing for the next
  session ("what we learned reading other harnesses on GitHub",
  "spike notes from the X experiment").
- A roadmap thread ("where we are going") that lives across multiple
  sprints — too forward-looking for Session Log, too narrative for
  the Decisions table.

## Filename convention

`<kebab-case-slug>.md` — must match the H1 title of the file, whichever
  slug you choose
(`hook-architecture.md` -> `# Hook architecture`).  The convention
test (`tests/test_categorized_memory_layout.py`, Espalier source repo) checks the H1
presence; the slug-vs-H1 match is enforced by reviewer eye, not test.

## Required structure

Every file in this folder starts with:

    # <Title>

    **Status:** active | historical | experimental
    **Linked from:** ESPALIER_MEMORY.md row "<row label>" (or "(unlinked)" for
                     standalone research notes)

    <body>

`Status:`
- **active** — currently load-bearing; index row links here for the
  long version.
- **historical** — describes a past state for context (e.g., "the
  v0.6 hook protocol"); no longer enforced.
- **experimental** — sketches an idea that isn't a decision yet.

## Cross-links

The ESPALIER_MEMORY.md row that summarizes this topic should link here:

```
| Hook architecture (summary) | See `memory/hook-architecture.md` (an
illustrative row; whichever entries your repo keeps go here). 12 hooks across 10 events; channel-XOR contract; ... |
```

The reverse link in this file's "Linked from:" header keeps both
sides discoverable.

## Not here

- Footguns and class-of-bug entries -> [docs/sharp-edges/](../docs/sharp-edges/).
  This folder is for state / decisions / research; sharp-edges is
  for "things to avoid."
- Per-session context -> cognitive blueprints (`cc/blueprints/`).
- External pinned truth -> `docs/external/`.
