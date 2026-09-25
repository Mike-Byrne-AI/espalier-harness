# tools/cc/hooks/

**Doing:** Claude Code hook scripts. Each script handles one event (PreToolUse, PostToolUse, SessionStart, etc.) and returns via the channel-XOR protocol.
**Don't break:** Zero `espalier` imports — hooks run standalone. Exit codes follow channel-XOR (0 + JSON OR 2 + stderr, never both). Path comparisons use `.replace("\\", "/")` for Windows. Derive shared constants and helpers from their `_hook_utils` single owners (`SOURCE_LANGUAGE_EXTENSIONS`, `EXEMPT_UNIVERSAL_PREFIXES`, `MCP_WRITE_VERB_SUBSTRINGS`, `PROJECT_MANIFEST_NAMES`, `has_active_plan`) — don't re-inline; the concept-overlap probe flags divergent copies. The `hook-authoring` skill is the source of truth for the authoring contract; `memory/hook-authoring.md` (read first, below) carries the accumulated patterns and gotchas.

## Before writing or editing in this folder:

1. Read [`memory/hook-authoring.md`](../../../memory/hook-authoring.md) — accumulated hook patterns and gotchas.
2. Confirm `docs/external/cc-hook-protocol.md` reflects the current Claude Code hook protocol (pinned external truth).
3. A new hook/detector WILL self-collide (deny-token data in a non-`_` hook, line-pins, state files) — run the sweep in `docs/SHARP_EDGES.md` "A new pattern-detector trips the harness's own defenses".
4. After edits, run `pytest tests/test_hooks.py tests/test_hook_protocol.py` before any commit.

**Read first:** [`memory/hook-authoring.md`](../../../memory/hook-authoring.md)
