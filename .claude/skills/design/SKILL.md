---
name: design
description: Harness configuration review. Use when reviewing harness configuration, auditing the agent roster, evaluating the command set, checking hook coverage, or assessing docs freshness — also when the user asks to review setup, audit harness, check for stale agents, or when significant project changes warrant a configuration review. Delegates to the harness-config-advisor agent.
---

# Design — Harness Configuration Review

Delegate the full review to the **harness-config-advisor** agent. The agent
holds the merged context for agent-roster and command-set design and runs in
its own context window. Present its recommendations and wait for approval
before applying changes.

## What to ask the agent

Hand the agent the four review axes below and request a single consolidated
report. Do not duplicate `espalier audit .` — that command already verifies
manifest integrity, broken refs, and JSON validity. The skill body covers
judgment calls the audit cannot make.

### 1. Agent roster

- Each agent's name, model tier, and current role
- Coverage gaps (frameworks/layers no agent owns)
- Stale agents (added for features that no longer exist)
- Model tier fit (Opus for reasoning-heavy, Sonnet for mechanical)
- Count discipline: 3–6 agents is a soft default, not a rule — flag count only alongside observed dysfunction (overlap, unused agents, coverage gaps). 7 tightly-scoped agents beats 4 bloated ones.

### 2. Command set

- One-line purpose per command
- Universal commands present (`/context-load`, `/handoff`, `/status`, `/smoke`)
- Commands reference real paths in this repo
- Workflows the developer hits weekly that lack a command
- Count discipline: 10–17 commands (more = developer forgets they exist)

### 3. Hook coverage

Standard 12 hooks (verify all active in `.claude/settings.json`):

- `session_start.py` (SessionStart) — load blueprint chain
- `task_router.py` (UserPromptSubmit) — route to `/implement-task` or `--multi`
- `plan_guard.py` (PreToolUse) — block source writes without active plan
- `write_guard.py` (PreToolUse) — block mutations of protected zones (a write, a delete, a move)
- `config_guard.py` (ConfigChange) — block unsafe project/local/user settings changes
- `post_write_check.py` (PostToolUse) — validate writes
- `reflect_trigger.py` (PostToolUse) — trigger reflect every 10th write
- `stop_gate.py` (Stop) — lightweight session hygiene; full pytest gate via `ESPALIER_STOP_GATE=full`
- `subagent_stop.py` (SubagentStop) — append subagent reasoning to active blueprint
- `post_compact.py` (PostCompact) — re-inject critical context
- `subagent_start.py` (SubagentStart) — inject cold-subagent orientation
- `context_reinject_failure.py` (PostToolUseFailure) — re-derive after a failed Edit/Write

Flag hooks referencing paths that no longer exist.

### 4. Documentation freshness

- ESPALIER_MEMORY.md lean and current (the harness caps it at 120 lines)
- docs/CONVENTIONS.md matches actual code patterns (run `/analyze` if uncertain)
- docs/SHARP_EDGES.md covers real footguns (not generic advice)
- Session log current (last 5 rows)

```bash
for f in ESPALIER_MEMORY.md docs/CONVENTIONS.md docs/SHARP_EDGES.md docs/CHEAT-SHEET.md docs/TASK_RECIPES.md; do
  [ -f "$f" ] && echo "$f: $(git log -1 --format='%ar' -- $f 2>/dev/null)" || echo "$f: MISSING"
done
wc -l ESPALIER_MEMORY.md 2>/dev/null
```

## Expected output

```
HARNESS CONFIGURATION REVIEW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Agents ({N}):   {list}
Commands ({N}): {list}
Hooks:          {list}

Recommended changes:
  ADD:    {list or NONE}
  REMOVE: {list or NONE}
  MODIFY: {list or NONE}
```

Per-finding format:

```
COMPONENT: {name}
ACTION:    KEEP | ADD | REMOVE | MODIFY
REASON:    {concrete evidence}
DETAILS:   {for ADD/MODIFY — exactly what to change}
PRIORITY:  ESSENTIAL | RECOMMENDED | NICE-TO-HAVE
```

## After approval

Apply approved changes directly, then run `python -m espalier audit .` to verify
surface integrity.
