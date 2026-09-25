# Adapter Boundary

Espalier-Harness is the Claude Code adapter for a provider-agnostic governance
harness model. This document defines what is core (provider-independent) and
what is Claude-specific.

## Core model

The following concepts are provider-independent:

- **Cognitive blueprint chain** — reasoning serialization across sessions
- **Hook-event-driven enforcement** — PreToolUse/PostToolUse/SessionStart/Stop lifecycle gates
- **Execution plan discipline** — multi-step task tracking with per-step verification
- **Surface contract** — which files are public, internal, or local-only
- **Managed-path protection** — block mutations (a write, a delete, a move) of harness-critical files
- **Scanner architecture** — stdlib-only, zero-dep code quality passes
- **Integrity manifest** — hash-drift detection for protected files

## Claude Code adapter

Claude Code-specific surfaces (not portable as-is):

- `.claude/settings.json` hook wiring format
- `CLAUDE.md` system prompt injection
- Claude Code slash commands (`.claude/commands/*.md`)
- Claude Code agent definitions (`.claude/agents/*.md`)
- `hookSpecificOutput` JSON protocol for SessionStart/Stop/PreToolUse context
- `$CLAUDE_PROJECT_DIR` environment variable in hook commands

## Do not duplicate

The right path for any future provider port is one core library with
provider-specific adapter layers on top, not a forked harness with vendor
names swapped. Forking creates two diverging codebases with no shared test
surface.

## Migration path (if a future port is undertaken)

1. Extract the provider-independent logic listed under "Core model" into a
   shared library.
2. Keep the current `espalier` package as the Claude Code reference adapter.
3. Implement any new provider as a thin adapter layer over the shared core.
4. Shared tests live with the core library; adapter-specific tests live with
   each adapter.

This is documented architecture, not a committed roadmap.
