Verify structural integrity of the harness surface. Fast, no external tools needed.

## Checks

### 1. All command files referenced in CLAUDE.md exist
```bash
echo "=== Command files ==="
# Extract the FIRST backticked /command on each row (non-greedy). A row like
# `| `/accomplish` | Compatibility alias for `/implement-task --multi` |` must
# count once as /accomplish -- the old greedy `sed "s/.*`\///"` grabbed the LAST
# /token, double-counting /implement-task and never checking /accomplish.
grep "^| \`/" CLAUDE.md 2>/dev/null | sed -E 's#^\| `/([^`]+)`.*#\1#' | while read cmd; do
  test -f ".claude/commands/$cmd.md" && echo "[OK] /$cmd" || echo "[FAIL] /$cmd - MISSING FILE"
done
```

### 2. All agent files referenced in CLAUDE.md exist
```bash
echo "=== Agent files ==="
# Match agent-table rows (a name in backticks followed by a model column),
# not the literal word "agents" -- that word never appears in those rows, so
# the old `grep "agents"` matched nothing (a silent no-op). Each agent the
# CLAUDE.md roster names must have a deployed file.
grep -E "^\| \`[A-Za-z0-9_-]+\` \| (Opus|Sonnet|Haiku)" CLAUDE.md 2>/dev/null | sed -E 's#^\| `([^`]+)`.*#\1#' | while read agent; do
  test -f ".claude/agents/$agent.md" && echo "[OK] $agent" || echo "[FAIL] $agent - MISSING FILE"
done
```

### 3. JSON validity
```bash
echo "=== JSON validity ==="
find .claude/ reports/ -name "*.json" 2>/dev/null | while read f; do
  python -c "
import json, sys
try:
    json.load(open(sys.argv[1]))
    print(f'[OK] {sys.argv[1]}')
except Exception as e:
    print(f'[FAIL] {sys.argv[1]}: {e}')
" "$f"
done
```

### 4. CLAUDE.md command count matches files
```bash
echo "=== Command count ==="
table_count=$(grep "^| \`/" CLAUDE.md 2>/dev/null | wc -l)
file_count=$(ls .claude/commands/*.md 2>/dev/null | wc -l)
echo "CLAUDE.md: $table_count, Files: $file_count"
[ "$table_count" -eq "$file_count" ] && echo "[OK] Match" || echo "[FAIL] MISMATCH"
```

### 5. No template placeholders left
```bash
echo "=== Placeholders ==="
grep -rn "{TODO\|{FILL\|{REPLACE\|{INSERT\|{YOUR\|{PROJECT" .claude/ CLAUDE.md 2>/dev/null | grep -v ".git/" && echo "[FAIL] found" || echo "[OK] none"
```

### 6. Hook scripts exist and are wired
```bash
echo "=== Hook wiring ==="
python -c "
import json, os, re
data = json.load(open('.claude/settings.json'))
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
python -m espalier provenance . 2>&1 | tail -20
```

Catches internal build-history tags (task-pack ids, review-round ids, workflow
run ids) that leaked into a shipping-surface comment/doc — the same source of
truth as the full-suite de-provenance gate, run here in the fast loop so a stray
tag is caught before the pre-PR suite. Exit 2 on a hit.

On any repo other than the Espalier-Harness source tree this stands down and
exits 0 with a one-line reason: the tags it hunts are Espalier's own, and its
pattern collides with ordinary ticket prefixes like `TP-`/`TQ-`.

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
Command files:    {OK | FAIL — N missing}
JSON validity:    {OK | FAIL — N invalid}
No placeholders:  {OK | FAIL — N found}
Command count:    {OK | FAIL — table vs files}
Hook wiring:      {OK | FAIL — N missing}
espalier audit:   {OK | FAIL — N findings}
Provenance:       {OK | FAIL — N build-history tags on shipping surfaces}

Status: {CLEAN | ISSUES — describe}
```
