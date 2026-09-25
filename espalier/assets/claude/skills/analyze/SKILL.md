---
name: analyze
description: Ground or re-ground the harness on this repo. On first run (no saved fingerprint) it establishes the baseline — what this codebase is, its stack, architecture, and test posture; thereafter it detects drift. Use when grounding the harness on a new repo, when project structure has shifted significantly, when returning to the project after time away, when docs/CONVENTIONS.md or docs/SHARP_EDGES.md feels stale, or when the user asks to analyze, fingerprint, ground, or check for changes. Delegates the heavy lifting to the repo-analyst and docs-maintainer agents.
---

# Analyze — Ground or re-ground the harness

Most of the work is delegated to two agents. The skill body is a reference
for what to ask each agent, plus the harness-specific signals to inspect
locally. On a first run (no saved fingerprint) this grounds the harness on a
new repo; thereafter it detects drift.

## Step 1 — Structural analysis (repo-analyst)

Ask the **repo-analyst** agent for its full protocol against the project
root. It produces a five-axis report:

1. Project identity (what is this?)
2. Stack detection (languages, frameworks, databases, tools)
3. Architecture analysis (structure, modules, entry points, config)
4. Testing & quality (framework, count, lint, CI)
5. Developer workflow (git style, scripts, env management, docs)

## Step 2 — Pattern detection (docs-maintainer)

Ask the **docs-maintainer** agent to verify docs/CONVENTIONS.md still matches
actual code patterns:

1. Code conventions (naming, imports, docstrings, types, error handling)
2. Git conventions (commit format, branch naming)
3. Testing patterns (naming, fixtures, mocks)
4. Architecture idioms (layer boundaries, import direction)

## Step 3 — Harness-specific signals

Inspect locally — these are not agent work:

```bash
echo "=== Large directories (claudeignore candidates) ==="
du -sh */ 2>/dev/null | sort -rh | head -10

echo "=== Test coverage gaps ==="
for f in espalier/*.py; do
  mod=$(basename "$f" .py)
  [ "$mod" = "__init__" ] && continue
  [ "$mod" = "_compat" ] && continue
  if find tests/ -maxdepth 1 \( -name "test_${mod}.py" -o -name "test_${mod}s.py" -o -name "test_${mod}_*.py" \) 2>/dev/null | grep -q .; then
    echo "  ✓ $mod"
  else
    echo "  ✗ $mod — no tests"
  fi
done

echo "=== TODOs/FIXMEs ==="
grep -rn "TODO\|FIXME\|HACK" espalier/ tools/ --include="*.py" 2>/dev/null | grep -v __pycache__ | head -15
```

## Step 4 — Drift diff

```bash
if [ -f reports/repo_fingerprint.json ]; then
  python -m espalier diff .
else
  echo "No saved fingerprint. Creating baseline."
  python -m espalier fingerprint .
fi
```

## Step 5 — Report

```
ANALYSIS COMPLETE
━━━━━━━━━━━━━━━━
{Project identity — one sentence}

Stack:        {languages} + {frameworks}
Architecture: {type} ({N} modules)
Tests:        {framework} ({N} test files, {N} gaps)
Hooks:        {N} wired in settings.json
Git style:    {commit convention}

Drift detected: {YES / NO}
  {list changed signals if YES}

Conventions documented: {N} in docs/CONVENTIONS.md
Sharp edges documented: {N} in docs/SHARP_EDGES.md
```

If drift detected, update docs/CONVENTIONS.md and docs/SHARP_EDGES.md, then run
`python -m espalier fingerprint .` to save the new baseline.
