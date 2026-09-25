<!-- espalier:managed -->
# Live Surface

Canonical index for the Espalier-Harness governance harness. Rendered from the
discovered surface; edit `espalier init` rendering logic, not this file.

## Session bootstrap
1. SessionStart hook loads blueprint chain, cleans per-session flags, writes timestamp.
2. Run `/status` to verify harness state.
3. Run `/smoke` to verify surface integrity (folds the former `/audit`'s `espalier audit .` invocation as Step 7).

## Hook semantics
SessionStart loads context and reports integrity state. ConfigChange and PreToolUse are the blocking local hook surfaces. CI is the merge-time guarantee. SessionStart cannot block Claude Code execution per the official hook protocol (docs/external/cc-hook-protocol.md).

## Hook architecture (12 hooks across canonical events)
- `ConfigChange` -> `config_guard.py` -- Blocks unsafe project/local/user settings changes; audits managed policy_settings
- `PostToolUseFailure ("Write|Edit|NotebookEdit")` -> `context_reinject_failure.py` -- On a failed Edit/Write (old_string-not-found), injects untrusted-oracle re-derivation (Rule A)
- `PreToolUse ("Write|Edit|NotebookEdit")` -> `plan_guard.py` -- Blocks Write/Edit/NotebookEdit on source files without an active execution plan. Bash and MCP writes are not plan-gated — write_guard covers protected-zone defense for those.
- `PostCompact` -> `post_compact.py` -- Records compaction summary and prepares next-session continuity
- `PostToolUse ("Write|Edit|NotebookEdit|Bash|PowerShell|mcp__.*")` -> `post_write_check.py` -- Validates each written file for JSON validity and path consistency
- `PostToolUse ("*")` -> `reflect_trigger.py` -- Runs reflect protocol every 10th source write
- `SessionStart` -> `session_start.py` -- Loads blueprint chain at session start
- `Stop` -> `stop_gate.py` -- Lightweight Stop checks by default; full core pytest gate opt-in via ESPALIER_STOP_GATE=full
- `SubagentStart` -> `subagent_start.py` -- Cold-subagent orientation (host facts + fan-out finding-schema pointer)
- `SubagentStop` -> `subagent_stop.py` -- Appends subagent reasoning to the active blueprint (Gate 4 only); never blocks the subagent
- `UserPromptSubmit` -> `task_router.py` -- Classifies prompt scope and routes toward /implement-task or /implement-task --multi
- `PreToolUse ("*")` -> `write_guard.py` -- Blocks writes to protected harness zones and dangerous bash patterns

## Stable actions
- `audit` -> `espalier audit .`
- `execution-plan` -> `python tools/cc/execution_plan.py status`
- `reflect` -> `espalier reflect .`
- `reflect-deep` -> `espalier reflect-deep .`
- `scan` -> `espalier scan .`
- `test` -> `pytest -q`

## Agent roster (7 agents)
- `architecture-analyst` -- Understands how the project's modules connect and reviews changes for architectural consistency. Flags layer boundary violations, circular dependencies, hook exit code errors, and isolation-layer violations. Runs in its own context.
- `code-reviewer` -- Reviews code changes for correctness, style, and project-specific pitfalls. Also monitors convention drift: detects patterns in use vs the project's conventions doc (e.g. `docs/CONVENTIONS.md` if present), flags undocumented patterns and documented patterns no longer in use. The agent body ships with examples drawn from Espalier-Harness (hook exit codes channel-XOR rule — exit 0 with stdout JSON XOR exit 2 with stderr — `tools/cc/` isolation, scanner stdlib constraint, path normalization, test naming) — adopters should treat those as starting examples and adapt to their project. Runs in its own context.
- `docs-maintainer` -- Maintains harness documentation: ESPALIER_MEMORY.md, docs/CONVENTIONS.md, docs/SHARP_EDGES.md, docs/CHEAT-SHEET.md, docs/TASK_RECIPES.md. Audits docs for freshness, flags stale content, and updates them when the repo drifts from what's documented. Runs in its own context.
- `failure-mode-reviewer` -- Finds self-inflicted failure modes the implementation missed — the ways future-you, an AI collaborator, or a hurried session will trip over this code despite passing review. Distinct cognitive mode from code-reviewer; runs in its own context.
- `harness-config-advisor` -- Evaluates whether this repo's current agent/command/hook setup matches its actual needs. Advises on additions, removals, and adjustments to agents, commands, and hooks. Merges agent roster design and command set design in one context. Runs in its own context window.
- `repo-analyst` -- Analyzes this repo to ground or re-ground the harness's understanding of it. Runs in two modes: first-run baseline (no saved fingerprint) and drift detection (fingerprint exists). Checks language, frameworks, architecture, test patterns, CI/CD, and workflow. The foundation for harness update decisions. Runs in its own context window.
- `test-writer` -- Generates tests matching the host project's existing test style exactly. Pattern-discovery phase inspects the project's `tests/` tree to learn the fixture patterns, test file naming, function naming, and class-per-feature grouping in use; then writes tests that match. The agent body's audit shell uses Espalier-Harness's own structure as a reference example (`espalier/<module>.py` ↔ `tests/test_<module>.py`) — adapt the loop to your project's source tree. Runs in its own context.

## Commands (17 commands)
- `/accomplish` -- Compatibility alias for `/implement-task --multi`.
- `/audit-accuracy` -- Run the accuracy audit and walk through any failures.
- `/commit` -- Review uncommitted changes, then stage and commit with a generated message.
- `/context-load` -- Session resume and degraded-state recovery guidance.
- `/handoff` -- End the session cleanly and leave the next Claude Code session with usable continuity.
- `/implement-pack` -- Execute one or more task packs (`TP-*.md`) end-to-end with the established single-atomic-commit-per-pack workflow. Auto-continues to the next pack unless a defined stop condition fires.
- `/implement-task` -- Canonical repo-change command. Use for focused changes or coordinated multi-phase work.
- `/integrity` -- Verify or refresh the Espalier-Harness integrity manifest.
- `/preflight` -- Comprehensive pre-PR gate — run everything before pushing.
- `/read-summary` -- Dump the live working-summary doc for this repo — `cc/_working_summary.md`, the always-current "pick up where we left off" picture (an exact mirror of Claude Code's post-compaction summary plus the espalier resume index), rewritten at every session boundary so it is never stale.
- `/recall` -- Recall accumulated project judgment on a topic: up to four candidates, two rankers, you pick. Each is a `memory/` protocol, a `docs/SHARP_EDGES.md` entry, a `docs/STANDING_PRINCIPLES.md` principle (if one exists — that file is indexed wherever it is present, so your own standing principles are recallable too), or a pull-only canonical-shape pointer, presented alternating — each ranker's winner first where the two disagree, then the runners-up. This is the **pull** side of the recall engine (`tools/cc/hooks/_reinject.py` is the push side); `/recall` answers when you *ask*, instead of waiting for the harness to detect a trigger.
- `/scan` -- Run code quality scanners against this repo.
- `/scope-check` -- Pre-flight scope analysis for a task pack.
- `/smoke` -- Verify structural integrity of the harness surface. Fast, no external tools needed.
- `/status` -- Quick progress check — harness state in 10 lines. Never starts a new blueprint session.
- `/strengthen` -- Surface where a repo's test rails are missing: enumerate the public Python surface mechanically, cross-reference it against the test tree, and risk-rank the untested gaps.
- `/test-this` -- Generate tests for a specific file matching project patterns. Delegates to the test-writer agent for orthogonal-context generation.

## Skills (9 skills)
- `/adversarial` -- Failure-mode discovery — the ways future-me forgets a step, an AI collaborator drifts, or a refactor misses a sister-site. Use when shipping a hook, gate, or governance change; before a release; when you want a pre-mortem before the implementation lands. Distinct from /review (per-file correctness) and /reflect (cross-artifact gap surfacing). Delegates to the failure-mode-reviewer agent.
- `/analyze` -- Ground or re-ground the harness on this repo. On first run (no saved fingerprint) it establishes the baseline — what this codebase is, its stack, architecture, and test posture; thereafter it detects drift. Use when grounding the harness on a new repo, when project structure has shifted significantly, when returning to the project after time away, when docs/CONVENTIONS.md or docs/SHARP_EDGES.md feels stale, or when the user asks to analyze, fingerprint, ground, or check for changes. Delegates the heavy lifting to the repo-analyst and docs-maintainer agents.
- `/arch-check` -- Review changes for layer boundary violations, import direction, circular dependencies, and hook-exit-code errors. Use when refactoring across modules, when adding a new module, when a hook script imports espalier (forbidden), or when the user asks about architectural consistency. Delegates to the architecture-analyst agent.
- `/blueprint-authoring` -- Task-pack authoring conventions. Use when composing or refining a TP-N task pack, scoping a pack to a defect class, drafting code-fix instructions, structuring scope-in vs scope-out, or naming tasks within a pack — also when the user mentions task pack format, blueprint structure, RUNBOOK, or pack execution. Encodes Espalier-Harness's blueprint-authoring discipline.
- `/debug` -- Trace an error and suggest a fix. Use when an error has been encountered, a traceback or stack trace appears, behavior is unexpected, a tool call fails, or a regression is being investigated. First action — consult docs/SHARP_EDGES.md for known footguns matching the symptom before reading source. For cross-module traces (hook ↔ espalier, scanner ↔ engine), delegates the cross-module trace analysis to the architecture-analyst agent.
- `/design` -- Harness configuration review. Use when reviewing harness configuration, auditing the agent roster, evaluating the command set, checking hook coverage, or assessing docs freshness — also when the user asks to review setup, audit harness, check for stale agents, or when significant project changes warrant a configuration review. Delegates to the harness-config-advisor agent.
- `/hook-authoring` -- Hook script authoring conventions for tools/cc/hooks/. Use when writing or extending a hook, adding a bash extraction pattern to write_guard, modifying _normalize_path or path-handling helpers, reasoning about hook event ordering, or when the user mentions hook authoring, hook contract, hook regression, or path traversal in the harness. Codifies the contract every hook script must satisfy.
- `/reflect` -- Cross-artifact gap surfacing after a substantial implementation pass — looks across the files just changed for structural drift, missing connections, and inconsistencies the file-by-file review pass cannot see. Use when the user asks to reflect, after generating 3+ interconnected files, when the user senses something was missed, or before /handoff on significant sessions. Distinct from /review (single-file correctness lens) and /adversarial (failure-mode discovery). For non-trivial sessions, delegates the cross-artifact review to the code-reviewer agent for orthogonal context.
- `/review` -- Per-file correctness review of the current diff — bugs, style drift, project-specific pitfalls, one file at a time. Use when the user asks to review code, audit a diff, check changes before commit, or run a second-opinion pass. Distinct from /reflect (cross-artifact gaps) and /adversarial (failure-mode discovery). Delegates to the code-reviewer agent for orthogonal-context analysis.
