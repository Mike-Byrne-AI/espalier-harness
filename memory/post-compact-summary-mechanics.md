# Post-compact / native-CC-summary mechanics

**Status:** active
**Linked from:** TP-214/215/216 (the continuity packs), CLAUDE.md (`post_compact` hook)

How Claude Code's conversation compaction actually works, and what the harness
can and cannot do around it. Established by direct investigation (2026-06-23),
cross-checked with the claude-code-guide agent against official docs. Underpins
the three continuity packs.

## What compaction records on disk (verified)

- Each compaction writes a **`user`-type entry** into the session transcript
  `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` with
  `"isCompactSummary": true` and `"isVisibleInTranscriptOnly": true`.
- `<encoded-cwd>` = the absolute cwd with every non-alphanumeric run replaced by
  `-` (`/Users/x/My.Repo` → `-Users-x-My-Repo`).
- The summary text is `message.content` (str, or a list of `{text}` parts). It
  follows a **native 9-section template** (Primary Request & Intent → Key
  Technical Concepts → Files & Code → Errors & Fixes → Problem Solving → All
  User Messages → Pending Tasks → Current Work → Optional Next Step) and **ends
  with a native pointer**: "read the full transcript at: `<abs path to the
  prior .jsonl>`" + a "continue without asking" instruction.
- **That transcript pointer is NATIVE Claude Code, not a harness feature** — it
  is inside the model-generated summary, before any hook runs. (Undocumented in
  official docs, but present in this repo's own transcripts.)

## How to read the exact summary here

```bash
PROJ=~/.claude/projects/$(pwd | sed 's/[^a-zA-Z0-9]/-/g')   # CC encodes the repo's abs path: each non-alphanumeric -> '-'
SESSION=$(ls -t "$PROJ"/*.jsonl | head -1)   # most-recent = current session
python3 - "$SESSION" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
s = [r for r in rows if r.get("isCompactSummary")]
if not s: print("(no compaction yet)"); raise SystemExit
c = s[-1]["message"]["content"]
print(c if isinstance(c, str) else "".join(p.get("text","") for p in c))
PY
```

Official viewing paths: `/export <file>` (whole conversation incl. summary),
`/resume` (preview with Space/Ctrl+V). The UI "expand" box is undocumented and
not reliably re-openable — reading the `.jsonl` is the dependable way.

## The hard constraints (verified, doc-grounded)

- **Nothing but the user can trigger compaction.** The agent cannot self-`/compact`;
  no hook, no `settings.json` "compact on Stop", no CLI flag, no Agent-SDK call.
  Auto-compaction fires only on the context-size threshold.
- **No dry-run.** `/compact` is destructive (summary *replaces* context); there
  is no preview that emits the summary while leaving the conversation intact,
  and no headless way to fetch it as data.
- **The PostCompact hook stdin carries `transcript_path` (and `trigger`) but NOT
  the summary text.** A hook must read the `.jsonl` itself to get the summary.
  This repo's `post_compact.py` currently discards its stdin (TP-215 changes
  that).
- `/compact [instructions]` accepts **focus hints** (`/compact focus on the
  unresolved blockers`) — a free lever to steer the native summary.

## Three layers at a post-compact moment (separate them — §5 of the stance)

1. **Native CC summary** — the 9-section text + transcript pointer. Identical in
   every repo (lite, full, bespoke, zero-harness). NOT Espalier.
2. **The PostCompact hook injection** — `post_compact.py`'s `=== POST-COMPACTION
   CONTEXT ===` block (Repo/Branch/Surface/`Blueprint: bp=<hex>/d<depth>`/RESUME),
   appended as additionalContext. This IS Espalier. **BC-033 firewall**: only
   typed-integer state reaches this priming channel — free disk text never does.
3. **The blueprint / handoff / memory continuity system** — cross-*session*
   accumulation (the depth chain), the decisions-not-to-relitigate ledger. The
   real Espalier contribution; additive to, not the same as, the compaction
   summary.

## Design implication (why the continuity packs are shaped as they are)

Because compaction can't be triggered on demand and has no dry-run, the durable
"resume" artifact is better **generated at handoff** (agent applies the template
to the session/`.jsonl`) than **harvested** from a compaction you can't fire —
TP-216. TP-215 separately *captures* the native summary when auto-compact does
fire, written to a side artifact, **never** re-injected into the priming
channel (BC-033). TP-214 reads either. Authority hierarchy across all three:
ESPALIER_MEMORY.md + blueprint = curated truth; the summary docs = regenerated recall
aids.
