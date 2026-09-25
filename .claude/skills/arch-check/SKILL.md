---
name: arch-check
description: Review changes for layer boundary violations, import direction, circular dependencies, and hook-exit-code errors. Use when refactoring across modules, when adding a new module, when a hook script imports espalier (forbidden), or when the user asks about architectural consistency. Delegates to the architecture-analyst agent.
---

# Arch-check — architecture-analyst delegation

Layer boundary work delegates to the **architecture-analyst** agent so
cross-module reasoning happens in its own context.

## Step 1 — Frame the scope

Identify the architectural question:

- "is this layer-clean?" → diff or files in scope
- "does this respect the import rules?" → changed imports
- "where should X live?" → proposed change + neighboring modules

If the user did not specify, ask what they're checking. The
architecture-analyst is too expensive to invoke on an undirected scan.

## Step 2 — Delegate to architecture-analyst

Dispatch the **architecture-analyst** subagent (`subagent_type='architecture-analyst'`). The
analyst sources the project's layer model and invariants from
`CLAUDE.md` / `docs/ARCHITECTURE.md` / `docs/CONVENTIONS.md` — whichever
of those your project keeps; brief
it on anything not yet captured in the project's docs that you want
checked.

Example invariants (the harness this skill originated in):

- `espalier/` imports from `espalier/` only.
- `tools/cc/` has zero `espalier` imports (standalone scripts).
- `espalier/scanners/` is stdlib-only.
- Hook scripts exit 0 only (channel-XOR rule; exit 0 pairs with stdout
  JSON, exit 2 with stderr text, never both).
- Path comparisons normalize via `.replace("\\\\", "/")`.

Your project's invariants will look different — the analyst handles
that adapter logic when it reads the project's docs.

The agent returns a structured architectural verdict — direction
violations, scanner-isolation breaches, and hook-exit-code errors are
common load-bearing failure modes.

## Step 3 — Report

Pass the agent's verdict back. If it flagged a layer violation,
quote the offending import line and propose where the affected
function should move instead.
