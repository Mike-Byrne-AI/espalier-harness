---
name: debug
description: Trace an error and suggest a fix. Use when an error has been encountered, a traceback or stack trace appears, behavior is unexpected, a tool call fails, or a regression is being investigated. First action — consult docs/SHARP_EDGES.md for known footguns matching the symptom before reading source. For cross-module traces (hook ↔ espalier, scanner ↔ engine), delegates the cross-module trace analysis to the architecture-analyst agent.
---

# Debug — Trace and Fix

The user will paste an error message, traceback, or describe a failure.

## Step 1 — Consult docs/SHARP_EDGES.md FIRST

Before reading any source, scan `docs/SHARP_EDGES.md` for entries matching the
symptom. This repo documents real, recurring footguns (path-traversal in
hooks, write_guard self-edit, stop_gate state-dir gitignore, etc.) and the
issue is often already cataloged with a known fix shape. Ten seconds here
saves an hour of source spelunking.

If a sharp-edge entry matches, the fix is usually obvious from the entry —
apply it, verify, done.

## Step 2 — Parse the error

Identify the exception type, file, line number, and the call chain that led
to it.

## Step 3 — Read the source

Open the file at the indicated line. Read surrounding context (the full
function, not just the line).

## Step 4 — Check recent changes

```bash
git log --oneline -10
git diff HEAD~3 -- <affected_file>
```

Did a recent change introduce this?

## Step 5 — Diagnose

Explain what's happening and why. Be specific — reference exact variable
names, function signatures, type mismatches.

## Step 6 — Suggest a fix

Show the exact code change. Keep it minimal.

## Step 7 — Verify

Run the repository's own test command -- `[extra_actions] test` in `espalier.toml`,
else the fingerprint's detected command; the stderr line names which -- whole (the
targeted form is `/implement-task` step 5's `FILE` line):

```bash
PY=; for c in 'python3' python 'py -3'; do $c -c 'import sys, espalier; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1 && { PY=$c; break; }; done; [ -n "$PY" ] || { echo 'no Python 3.10+ with espalier answered to python3, python or py -3' >&2; exit 1; }
TEST=$($PY -c "import sys; sys.stdout.reconfigure(encoding='utf-8', errors='replace'); from espalier.harness_config import preflight_command; print(preflight_command('test'))") || exit 1
[ -n "$TEST" ] || { { [ -f pyproject.toml ] || [ -f setup.py ] || [ -f setup.cfg ]; } && command -v pytest >/dev/null 2>&1 && TEST='pytest -q' && echo 'test gate: pytest -q (the PATH fallback: nothing declared or detected)' >&2; }
if [ -n "$TEST" ]; then eval "$TEST" || exit 1; else echo 'NO TEST GATE RAN - declare [extra_actions] test in espalier.toml' >&2; exit 1; fi
# Espalier-Harness tree: pytest -q, or the tier the diff earns (python scripts/proof_tier.py --run)
```

Report pass/fail. If a new footgun was discovered, add it to docs/SHARP_EDGES.md
so the next debug session lands on Step 1 instead of Step 7.

## Cross-module trace delegation

If the trace crosses module boundaries in your project's layer model —
an enforcement script calling into an engine module, a scanner
discovering a violation in upstream code, a layer importing a symbol
its isolation rules forbid — delegate to the **architecture-analyst**
subagent (`subagent_type='architecture-analyst'`) with the full traceback + the
involved file paths.

The analyst owns the project's layer-direction rules (read from
`CLAUDE.md` / `docs/ARCHITECTURE.md` / `docs/CONVENTIONS.md` — whichever
of those your project keeps) and
places the bug at the correct layer faster than reading both sides
cold in this thread. A boundary cross usually shows up as an
`ImportError` at runtime or a circular-import hint in pytest
collection. Trace the call chain and identify which layer should own
the symbol; move it if needed.

Example layer rules (the harness this skill originated in):

- `espalier/` imports only from `espalier/`.
- `tools/cc/` scripts have zero `espalier` imports (they run
  standalone in environments where `espalier/` does not exist).
- `espalier/scanners/` are stdlib-only.

For your project, ask the analyst for the equivalent rule set; it
sources them from your project's documentation.

The presence-check pattern (`ls .claude/agents/architecture-analyst.md`)
is retained for fork resilience — harmless when the agent is present,
useful if a fork ever removes it.
