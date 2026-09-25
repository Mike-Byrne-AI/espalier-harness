<!-- espalier:managed -->
# Commands

Rendered from `.claude/commands/` and saved stable_actions.

| Command | Purpose |
|---|---|
| `/accomplish` | Compatibility alias for `/implement-task --multi`. |
| `/audit-accuracy` | Run the accuracy audit and walk through any failures. |
| `/commit` | Review uncommitted changes, then stage and commit with a generated message. |
| `/context-load` | Session resume and degraded-state recovery guidance. |
| `/handoff` | End the session cleanly and leave the next Claude Code session with usable continuity. |
| `/implement-pack` | Execute one or more task packs (`TP-*.md`) end-to-end with the established single-atomic-commit-per-pack workflow. Auto-continues to the next pack unless a defined stop condition fires. |
| `/implement-task` | Canonical repo-change command. Use for focused changes or coordinated multi-phase work. |
| `/integrity` | Verify or refresh the Espalier-Harness integrity manifest. |
| `/preflight` | Comprehensive pre-PR gate — run everything before pushing. |
| `/read-summary` | Dump the live working-summary doc for this repo — `cc/_working_summary.md`, the always-current "pick up where we left off" picture (an exact mirror of Claude Code's post-compaction summary plus the espalier resume index), rewritten at every session boundary so it is never stale. |
| `/recall` | Recall accumulated project judgment on a topic: up to four candidates, two rankers, you pick. Each is a `memory/` protocol, a `docs/SHARP_EDGES.md` entry, a `docs/STANDING_PRINCIPLES.md` principle (if one exists — that file is indexed wherever it is present, so your own standing principles are recallable too), or a pull-only canonical-shape pointer, presented alternating — each ranker's winner first where the two disagree, then the runners-up. This is the **pull** side of the recall engine (`tools/cc/hooks/_reinject.py` is the push side); `/recall` answers when you *ask*, instead of waiting for the harness to detect a trigger. |
| `/scan` | Run code quality scanners against this repo. |
| `/scope-check` | Pre-flight scope analysis for a task pack. |
| `/smoke` | Verify structural integrity of the harness surface. Fast, no external tools needed. |
| `/status` | Quick progress check — harness state in 10 lines. Never starts a new blueprint session. |
| `/strengthen` | Surface where a repo's test rails are missing: enumerate the public Python surface mechanically, cross-reference it against the test tree, and risk-rank the untested gaps. |
| `/test-this` | Generate tests for a specific file matching project patterns. Delegates to the test-writer agent for orthogonal-context generation. |

## Core flow

`/status` `/implement-task` `/smoke` `/preflight` `/commit` `/handoff`

## Stable actions

| Action | Command |
|---|---|
| `audit` | `espalier audit .` |
| `execution-plan` | `python tools/cc/execution_plan.py status` |
| `reflect` | `espalier reflect .` |
| `reflect-deep` | `espalier reflect-deep .` |
| `scan` | `espalier scan .` |
| `test` | `pytest -q` |
