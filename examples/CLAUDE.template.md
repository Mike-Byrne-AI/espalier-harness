# your-repo — Claude Code Governance Harness

## Project Context

your-repo uses Espalier-Harness for governance. Hooks enforce quality mechanically.
Session context is loaded by the SessionStart hook automatically.

> **First-response governance check (fresh clone / new machine).** Espalier's
> hooks are wired in `.claude/settings.json`, which is per-machine and
> gitignored — it does NOT travel with a clone. If you did **not** receive the
> Espalier `=== Session Start ===` context block at the start of this session,
> the governance hooks are **not active** on this machine: tell the user to run
> `python -m espalier init .` before relying on mechanical enforcement. (When
> unsure, run `python -m espalier doctor .`.)

- **Languages:** python
- **Profiles:** ci_cd

## Hooks (Mechanical Enforcement)

Espalier wires 12 hook scripts that run automatically on Claude Code events:

| Hook | Event | What It Does |
|---|---|---|
| `session_start.py` | SessionStart | Reports kill-switch findings + integrity drift; loads the blueprint chain (and advances it on a new session — source `startup`/`clear`); cleans flags. Cannot block (protocol). |
| `task_router.py` | UserPromptSubmit | Classifies prompt scope; routes toward /implement-task or /implement-task --multi |
| `plan_guard.py` | PreToolUse | Blocks source file writes without an active execution plan |
| `write_guard.py` | PreToolUse | Blocks tool calls when kill-switch is set; blocks mutations of protected zones (a write into, a delete of, a move out of); blocks dangerous bash patterns |
| `config_guard.py` | ConfigChange | Blocks unsafe project/local/user settings changes; audits managed policy_settings (non-blockable) |
| `post_write_check.py` | PostToolUse | Validates each written file for JSON validity and path consistency |
| `reflect_trigger.py` | PostToolUse | Runs reflect protocol every 10th source write |
| `stop_gate.py` | Stop | Lightweight session hygiene by default (docs, review, blueprint, state); full core pytest gate opt-in via `ESPALIER_STOP_GATE=full` |
| `subagent_stop.py` | SubagentStop | Appends subagent reasoning to the active blueprint (Gate 4 only); never blocks the subagent |
| `post_compact.py` | PostCompact | Re-injects critical context after conversation compaction |
| `subagent_start.py` | SubagentStart | Injects cold-subagent orientation (host facts + fan-out finding-schema pointer); never blocks (reporter) |
| `context_reinject_failure.py` | PostToolUseFailure | On a failed Edit/Write, injects the untrusted-oracle re-derivation discipline (Rule A); never blocks (reporter) |

**Hook semantics rule:** SessionStart reports. PreToolUse and ConfigChange deny. CI guarantees. SessionStart cannot block per the official Claude Code hook protocol.

## Slash Commands

| Command | Purpose |
|---|---|
| `/accomplish` | Compatibility alias for `/implement-task --multi`. |
| `/audit-accuracy` | Run the accuracy audit and walk through any failures. |
| `/commit` | Review uncommitted changes, then stage and commit with a generated message. |
| `/context-load` | Session resume and degraded-state recovery guidance. |
| `/handoff` | End the session cleanly and leave the next Claude Code session with usable continuity. |
| `/implement-pack` | Execute one or more task packs (`TP-*.md`) end-to-end with the established single-atomic-commit-per… |
| `/implement-task` | Canonical repo-change command. |
| `/integrity` | Verify or refresh the Espalier-Harness integrity manifest. |
| `/preflight` | Comprehensive pre-PR gate — run everything before pushing. |
| `/read-summary` | Dump the live working-summary doc for this repo — `cc/_working_summary.md`, the always-current "pic… |
| `/recall` | Recall accumulated project judgment on a topic: up to four candidates, two rankers, you pick. |
| `/scan` | Run code quality scanners against this repo. |
| `/scope-check` | Pre-flight scope analysis for a task pack. |
| `/smoke` | Verify structural integrity of the harness surface. |
| `/status` | Quick progress check — harness state in 10 lines. |
| `/strengthen` | Surface where a repo's test rails are missing: enumerate the public Python surface mechanically, cr… |
| `/test-this` | Generate tests for a specific file matching project patterns. |

## Skills

Skills auto-invoke on trigger-phrase detection and are also callable as `/name`. Bodies load on-demand.

| Skill | Trigger phrase |
|---|---|
| `adversarial` | Failure-mode discovery — the ways future-me forgets a step, an AI collaborator drifts, or a refacto… |
| `analyze` | Ground or re-ground the harness on this repo. |
| `arch-check` | Review changes for layer boundary violations, import direction, circular dependencies, and hook-exi… |
| `blueprint-authoring` | Task-pack authoring conventions. |
| `debug` | Trace an error and suggest a fix. |
| `design` | Harness configuration review. |
| `hook-authoring` | Hook script authoring conventions for tools/cc/hooks/. |
| `reflect` | Cross-artifact gap surfacing after a substantial implementation pass — looks across the files just… |
| `review` | Per-file correctness review of the current diff — bugs, style drift, project-specific pitfalls, one… |

## Agents

| Agent | Model | Role |
|---|---|---|
| `architecture-analyst` | Opus | Understands how the project's modules connect and reviews changes for architectural consistency. |
| `code-reviewer` | Sonnet | Reviews code changes for correctness, style, and project-specific pitfalls. |
| `docs-maintainer` | Sonnet | Maintains harness documentation: ESPALIER_MEMORY.md, docs/CONVENTIONS.md, docs/SHARP_EDGES.md, docs… |
| `failure-mode-reviewer` | Opus | Finds self-inflicted failure modes the implementation missed — the ways future-you, an AI collabora… |
| `harness-config-advisor` | Opus | Evaluates whether this repo's current agent/command/hook setup matches its actual needs. |
| `repo-analyst` | Opus | Analyzes this repo to ground or re-ground the harness's understanding of it. |
| `test-writer` | Sonnet | Generates tests matching the host project's existing test style exactly. |

## Plan Guard

If your source lives under a top-level directory other than the repo root (e.g. `src/`, `lib/`, `app/`, `cmd/`, `internal/`), routine edits there may hit plan-required denials. The plan guard requires an active execution plan before editing tracked source roots. Declare your source root(s) as plan-exempt in `espalier.toml` so routine edits aren't plan-gated:

```toml
plan_exempt_prefixes = ["your-source-root/"]
```

## Maintenance mode

`ESPALIER_MAINTENANCE_MODE=1` is a scoped, friction-only opt-out for editing the
harness's own files. Set it in the parent shell **before** launching Claude Code —
Claude Code inherits its environment at launch, so a mid-session `export` never
reaches hooks that are already running:

```
POSIX / Git Bash / WSL:  ESPALIER_MAINTENANCE_MODE=1 claude
PowerShell:              $env:ESPALIER_MAINTENANCE_MODE="1"; claude
cmd.exe:                 set ESPALIER_MAINTENANCE_MODE=1 && claude
```

Add `--continue` to any of these to resume the session you were denied in;
a bare `claude` starts a new conversation and a new blueprint node.

While it is active, `write_guard` skips its protected-zone path check,
`plan_guard` skips the plan-required check, `stop_gate` skips the docs-refresh
and code-review gates, and `subagent_stop` skips the blueprint append. Still
enforced: the kill-switch denial, dangerous-command patterns, the speed-bump
checkpoints, `config_guard`, `post_write_check`, and CI. Every bypass logs a
line to stderr, so the use is visible in the session transcript.

**Do not reach for this to edit your own source tree.** It disarms far more than
the plan gate. Declare your source roots in `plan_exempt_prefixes` in
`espalier.toml` instead — that knob is scoped to exactly the plan requirement.

## Cross-platform Python invocation

The command and skill bodies under `.claude/` show `python <script>` for
brevity. They are not host-specific, unlike `.claude/settings.json`, which
`espalier init` wrote with the interpreter it actually detected on this
machine. When following one of those bodies, try `python3` first and fall back
to `python` if the shell reports `command not found` — macOS typically ships
only `python3`, while some Windows installs ship only `python`.

## Architecture Rules

- `tools/cc/` scripts run standalone — zero project-specific imports
- Hook exit codes: `0` = allow OR structured channel (JSON on stdout for permission/decision); `2` = simple block (plain stderr, no stdout JSON); `1` = script error (bug).
- Path comparisons use `.replace("\\", "/")` for Windows compatibility

## Build & Test

```bash
# Run tests
# configure your test command (e.g. pytest -q, npm test, cargo test)

# Harness integrity check
espalier audit .
```
