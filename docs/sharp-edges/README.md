# Categorized Sharp Edges

This folder holds long-form footgun documentation that doesn't fit
in the index monolith at `../SHARP_EDGES.md` (when present in
the host repo; adopters who haven't migrated content will not have
the monolith yet). The index file (when it exists) remains the
entry point — `tools/cc/hooks/session_start.py` surfaces a one-line `/recall`
pointer to it at session start (the full TOC is no longer injected).
Pull the relevant section on demand with `/recall <topic>`, which
indexes `SHARP_EDGES.md` per section.

## When to add a file here

- A SHARP_EDGES.md section would exceed ~30 lines of body — cut the
  body here, keep a one-line summary + link in the index.
- A footgun that warrants a worked example (multi-step reproduction,
  before/after code, contrast with a sister-site) — the monolith's
  prose density makes worked examples awkward.

## Filename convention

`<kebab-case-slug>.md` — the slug is the kebab-case form of the
footgun's title (`hook-exit-codes-channel-xor.md` for the footgun
"Hook Exit Codes — Channel XOR"). If you also keep a
`docs/SHARP_EDGES.md` index, the slug matches that section's H2 heading.

## Required structure

    # <Footgun title>

    **Status:** active | historical | retired
    **Linked from:** docs/SHARP_EDGES.md section "<exact heading>"  (if you maintain an index)

    <body>

`Status:`
- **active** — the footgun is still reachable in current code.
- **historical** — describes a past failure mode for context (e.g.,
  pre-migration channel confusion); the class-of-bug is closed.
- **retired** — closed by a contract; the entry is preserved as
  documentation of the discovery but the failure mode can no longer
  occur (e.g., a retired path-traversal enforcement).

## Not here

- State / decisions / research -> [`../../memory/`](../../memory/).
- Operational runbooks -> `docs/RUNBOOK*.md`.
- External pinned truth -> `docs/external/`.
