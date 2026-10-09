---
description: Verify structural integrity of the harness surface. Fast, no external tools needed.
---

Verify structural integrity of the harness surface. Fast, no external tools needed.

## Checks

### 1. Every command the harness inventory lists has a file
```bash
echo "=== Command files ==="
# The inventory is cc/COMMANDS.md, which init regenerates on every run -- not
# the root CLAUDE.md: an adopter who keeps their own CLAUDE.md (an @-import
# shell, say) carries no command table there, and a grep over it iterated zero
# rows and printed nothing, a vacuous pass. Extract the FIRST backticked
# /command on each row (non-greedy), so a row whose purpose mentions another
# command counts once.
if [ ! -f cc/COMMANDS.md ]; then
  echo "[SKIP] cc/COMMANDS.md is absent (run python -m espalier init); nothing to check"
else
  grep "^| \`/" cc/COMMANDS.md 2>/dev/null | sed -E 's#^\| `/([^`]+)`.*#\1#' | while read cmd; do
    test -f ".claude/commands/$cmd.md" && echo "[OK] /$cmd" || echo "[FAIL] /$cmd - MISSING FILE"
  done
fi
```

### 2. All agent files referenced in CLAUDE.md exist
```bash
echo "=== Agent files ==="
# Match agent-table rows (a name in backticks followed by a model column),
# not the literal word "agents" -- that word never appears in those rows, so
# the old `grep "agents"` matched nothing (a silent no-op). The root CLAUDE.md
# carries that table only when init generated it; an adopter-owned file has
# none, and zero rows must say so rather than print nothing.
rows=$(grep -E "^\| \`[A-Za-z0-9_-]+\` \| (Opus|Sonnet|Haiku)" CLAUDE.md 2>/dev/null | sed -E 's#^\| `([^`]+)`.*#\1#')
if [ -z "$rows" ]; then
  echo "[SKIP] no agent table in CLAUDE.md (adopter-owned file); deployed agent files: $(ls .claude/agents/*.md 2>/dev/null | wc -l | tr -d ' ')"
else
  echo "$rows" | while read agent; do
    test -f ".claude/agents/$agent.md" && echo "[OK] $agent" || echo "[FAIL] $agent - MISSING FILE"
  done
fi
```

### 3. JSON validity
```bash
echo "=== JSON validity ==="
# Only the JSON the harness owns: the two settings files by path, and the
# reports/ it writes. A foreign tool's state under .claude/ (a retired hook's
# .claude/.session-state/*.json, say) is not ours to grade -- on one adopter it
# made this check FAIL on every run, and a red that is always red is a red
# nobody reads.
{
  for f in .claude/settings.json .claude/settings.local.json; do [ -f "$f" ] && echo "$f"; done
  find reports/ -name "*.json" 2>/dev/null
} | while read f; do
  python -c "
import json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
try:
    json.load(open(sys.argv[1], encoding='utf-8'))
    print(f'[OK] {sys.argv[1]}')
except Exception as e:
    print(f'[FAIL] {sys.argv[1]}: {e}')
" "$f"
done
```

### 4. Command census: inventory rows against files
```bash
echo "=== Command count ==="
# A census, not an equality: check 1 already gates every inventory row on its
# file. A command file of your own with no row is yours to keep (named here as
# information), and an adopter-owned CLAUDE.md with no table is not a mismatch.
# The old check compared the root CLAUDE.md's table count to the file count,
# which an adopter-owned CLAUDE.md failed forever (0 rows) and an adopter's own
# command file failed too.
if [ ! -f cc/COMMANDS.md ]; then
  echo "[SKIP] cc/COMMANDS.md is absent (run python -m espalier init)"
else
  rows=$(grep -c "^| \`/" cc/COMMANDS.md 2>/dev/null | tr -d ' ')
  files=$(ls .claude/commands/*.md 2>/dev/null | wc -l | tr -d ' ')
  echo "cc/COMMANDS.md: $rows rows, .claude/commands: $files files"
  for f in .claude/commands/*.md; do
    [ -f "$f" ] || continue
    name=$(basename "$f" .md)
    grep -q "^| \`/$name\`" cc/COMMANDS.md 2>/dev/null || echo "[INFO] /$name has a file and no inventory row (your own command; kept)"
  done
  echo "[OK] census printed"
  # On the harness's own source tree the root CLAUDE.md table is a shipped
  # surface kept equal to the files (Five-Surface Command Sync); hold it there.
  # Three of the five signals surface_contract.is_self_host_repo reads; a tree
  # that carries all three is the harness or a full clone of it, where the
  # same invariant holds.
  if [ -f espalier/surface_contract.py ] && [ -f espalier/mirror_registry.py ] && [ -d bench ]; then
    table_count=$(grep "^| \`/" CLAUDE.md 2>/dev/null | wc -l | tr -d ' ')
    [ "$table_count" -eq "$files" ] && echo "[OK] self-host CLAUDE.md table matches the files ($table_count)" || echo "[FAIL] self-host CLAUDE.md table $table_count vs files $files"
  fi
fi
```

### 5. No template placeholders left
```bash
echo "=== Placeholders ==="
# Only the bodies espalier manages (the marker is the ownership predicate) and
# the root CLAUDE.md: a foreign tool's .md under .claude/ is not graded. An ERE,
# because the alternation reads the same under BSD, GNU and ugrep; the BRE
# `\|` this used was GNU-only (vacuous on a stock macOS grep, and on GNU it
# matched this very line, so the check failed on itself). -H names the file
# even when only one body carries the marker.
{
  # /dev/null first, so grep always has an operand: BSD xargs runs nothing on
  # an empty list and the && would read that as a find.
  echo /dev/null
  grep -rl --exclude-dir=worktrees "espalier:managed" .claude/ 2>/dev/null
  # The harness's own source tree carries no marker on its bodies (init stamps
  # them on deploy), so there the four source kinds are graded as well.
  if [ -f espalier/surface_contract.py ] && [ -f espalier/mirror_registry.py ] && [ -d bench ]; then
    find .claude/commands .claude/agents .claude/skills .claude/workflows -name "*.md" 2>/dev/null
  fi
  [ -f CLAUDE.md ] && echo CLAUDE.md
} | sort -u | xargs grep -nHE "\{(TODO|FILL|REPLACE|INSERT|YOUR|PROJECT)" 2>/dev/null && echo "[FAIL] found" || echo "[OK] none"
```

### 6. Hook scripts exist and are wired
```bash
echo "=== Hook wiring ==="
python -c "
import json, os, re, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
data = json.load(open('.claude/settings.json', encoding='utf-8'))
hooks = data.get('hooks', {})
seen = 0
for event, entries in hooks.items():
    for entry in entries:
        for h in entry.get('hooks', []):
            # Exec-form (current): the script path is an entry in args[]; the
            # command is the interpreter ('python3'). Legacy shell-form put
            # the path in command. Scan both so the check actually validates.
            candidates = list(h.get('args', []))
            candidates.append(h.get('command', ''))
            for p in candidates:
                if not (isinstance(p, str) and p.endswith('.py') and 'hooks/' in p):
                    continue
                # Strip the project-dir prefix by its tail. init writes the
                # path under the project-dir variable, and the loader rewrites
                # that variable's spelling in this body before the shell sees
                # it, so a literal of it here can never match settings.json;
                # the tail alone is not a substitution target and survives.
                script = re.sub(r'^.*?PROJECT_DIR}?/', '', p)
                status = '[OK]' if os.path.exists(script) else '[FAIL] MISSING'
                print(f'  {status} {event}: {script}')
                seen += 1
if seen == 0:
    print('  [FAIL] no hook scripts parsed from settings.json (shape mismatch?)')
" 2>/dev/null || echo "settings.json not found"
```

### 7. Engine-side audit
```bash
echo "=== espalier audit ==="
python -m espalier audit . 2>&1 | tail -20
```

### 8. De-provenance census
```bash
echo "=== espalier provenance ==="
out=$(python -m espalier provenance . 2>&1); rc=$?
printf '%s\n' "$out" | tail -20
case "$out" in
  *"skipping (adopter repo)"*) echo "[SKIP] provenance census stands down off the Espalier-Harness source tree (exit $rc)" ;;
esac
```

Catches internal build-history tags (task-pack ids, review-round ids, workflow
run ids) that leaked into a shipping-surface comment/doc — the same source of
truth as the full-suite de-provenance gate, run here in the fast loop so a stray
tag is caught before the pre-PR suite. Exit 2 on a hit.

On any repo other than the Espalier-Harness source tree this stands down and
exits 0 with a one-line reason: the tags it hunts are Espalier's own, and its
pattern collides with ordinary ticket prefixes like `TP-`/`TQ-`. The block then
prints a `[SKIP]` line and the report's line reads `SKIPPED`, not `OK`: exit 0
there means the census did not run, not that it ran clean.

Checks: required files exist, JSON parses cleanly, no placeholder text,
no suspicious terminal junk (pasted `less` output, diff fragments, etc.).
For doc-claim verification — agent counts, hook lists, schema fields —
the `/audit-accuracy` command covers the "is X actually true?" surface.
Every `espalier init` deploys it (and `espalier fuse` ships the full
command set too).

## Report

```
SMOKE CHECK
━━━━━━━━━━━
Command files:    {OK | SKIPPED — no inventory yet | FAIL — N missing}
Agent files:      {OK | SKIPPED — no agent table (adopter-owned CLAUDE.md) | FAIL — N missing}
JSON validity:    {OK | FAIL — N invalid}
No placeholders:  {OK | FAIL — N found}
Command count:    {OK | SKIPPED — no inventory yet | FAIL — self-host table vs files}
Hook wiring:      {OK | FAIL — N missing}
espalier audit:   {OK | FAIL — N findings}
Provenance:       {OK | SKIPPED — adopter repo (the census stands down) | FAIL — N build-history tags on shipping surfaces}

Status: {CLEAN | ISSUES — describe}
```
