# Espalier-Harness — Task Recipes

## Starting a New Session

The SessionStart hook already loads state. Typing `/context-load`
at session begin is no longer needed; reserve it for explicit mid-session
re-orient, post-PostCompact recovery, or DEGRADED-surface recovery.

```
/status              — 10-line view: branch, dirty files, blueprint, fingerprint
/context-load        — explicit re-orient (mid-session, post-compact, DEGRADED recovery)
```

## Making a Change

Focused change (one bounded edit, one proof path):
```
/implement-task <description>
  → presents plan, waits for approval
  → creates one-step execution plan
  → implements
  → runs pytest tests/test_{module}.py -q
  → reports results
```

Coordinated change (3+ files, migrations, refactors, release hardening):
```
/implement-task --multi <description>
  → multi-phase with per-step gates and final integration check
```

Legacy alias (retained for existing users):
```
/accomplish <description>
  → same as /implement-task --multi
```

## Before Pushing
```
/preflight           — full gate: lint + tests + surface audit + reflect
/commit              — review uncommitted changes, run risk check, stage and commit
```

> **Interpreter note.** The commands below spell `python`. A stock macOS ships only
> `python3` (and it is 3.9; Espalier requires 3.10+), while many Windows installs ship
> only `python`. Use whichever both resolves AND reports 3.10+
> (`<name> --version`); on a stock macOS `python3` resolves but is 3.9.
> `espalier doctor .` checks this for you.

For a release commit, run the three-tier ladder (see `docs/RELEASE_CHECKLIST.md` — self-host only;
`scripts/` and the release checklist are not deployed by `init`):
```bash
# Espalier source repo only -- not deployed by init
python scripts/release_check.py                  # Tier 1 — fast signal (seconds; 19 passed, 3 skipped)
espalier pre-release .                           # Tier 2 — local readiness gate (about 45 min serial with tests on: 2,711 s measured 2026-09-23, bounded at twice that)
python scripts/final_release_matrix.py           # Tier 3 — publish proof (6 stages; 55:39 measured 2026-09-23, stage 02 alone 45:14; the matrix strips the opt-in flags from every child that would act on them, so none are set here)
python scripts/release_check.py --validate-archive "$(ls dist/final-release-matrix/source_archive_work/archive_out/*.zip)"   # the archive the matrix built, inside stage 02's work dir
```
Inspect `reports/final_release_candidate_report.json` (written by the matrix; Espalier source repo only) for `ready_to_tag: true` before `git tag`.

## Grounding / Re-analyzing the Repo

First session after `init` (no saved fingerprint): `/analyze` **grounds**
the harness — repo-analyst establishes the baseline and docs-maintainer
populates docs/CONVENTIONS.md from your code. Later runs detect drift:
```
/analyze
  → runs repo-analyst agent
  → first run: establishes the baseline (grounding)
  → later runs: detects drift vs reports/repo_fingerprint.json
  → reports changed signals
  → run `espalier fingerprint .` to save new baseline
```

## Checking Harness Health
```
/smoke               — structural check + espalier audit . (JSON report, exits non-zero on failures)
/design              — full harness config review: agents, commands, hooks, docs freshness
```

## After Finding a New Footgun
```
# Add entry to docs/SHARP_EDGES.md
# Format:
## {Edge Name}
**What it is:** {description}
**How you hit it:** {triggering scenario}
**How to avoid it:** {fix or prevention}
```

## Authoring a Task Pack

Before implementing a pack, run the scope pre-flight to surface reference gaps:
```bash
espalier scope-check "task-packs/TP-<N>-<name>.md"
```

Three exit codes:
- 0 — pack has no scope gap, or operator accepted with `--accept-scope-gap "<reason>"`
- 1 — nothing parsed: no `## Affected symbols` / `## Affected literals` section, or every bullet declares nothing on purpose (a clean skip); or a declared one that parsed to zero entries, marked by a `scope-check: DECLARED_BUT_EMPTY --` line (the cause is printed; fix the pack before proceeding)
- 2 — scope gap present and unacknowledged

If exit 2: either expand `Scope (in)` to cover the gap, or accept it with a reason:
```bash
espalier scope-check <pack> --accept-scope-gap "test-driven discovery on small pack"
```

See `docs/PACK_AUTHORING.md` for the required `Affected symbols` section format.

## A mechanical `/goal` for pack execution

`/goal` is judged by a separate tool-less model that can only see what the
session surfaced — so the condition must be provable by **visible artifacts**,
never "the work was good" (see `docs/CC_AUTOMATION.md`, Espalier source repo — not deployed by `init`).
A copy-ready condition
for driving one pack to landing:

```
/goal Land task-packs/TP-<N>-<name>.md: scope-check printed, the pack's edits
applied, earn-the-red shown in the transcript (mutate -> RED -> revert), the full
pytest suite green (pytest output present), `espalier audit .` clean, and exactly
one atomic commit visible in `git log`. Run every gate synchronously in the
foreground and read its result in the same turn. Stop after 40 turns if not done.
```

Why each clause: every requirement is a *visible proof a tool-less judge can
read* (a printed report, pytest output, a `git log` line) — not a quality
judgment. Never accept "red-team ran" as proof (FAILURE_MODES §1.1 / §11.12);
keep depth-judgment + adversarial refuters in the work-turn. The `or stop after N`
clause bounds an unsatisfiable goal. For unattended multi-pack runs this is what
the loop-over-`claude -p` driver issues per pack
(`docs/AUTONOMOUS_EXECUTION.md`, Espalier source repo — not deployed by `init`).

## Adding a Test
```
/test-this <path/to/module.py>
  → test-writer agent reads module, checks existing tests/
  → generates test_module.py matching project patterns
  → runs pytest tests/<test_module>.py -v before presenting
```

## Archiving Claude Code session transcripts

`~/.claude/projects/` is auto-pruned by Claude Code on a retention timer. Set
`cleanupPeriodDays` in `~/.claude/settings.json` to stop the clock — but that
only prevents *pruning*, it does not create a second copy.

```
# Espalier source repo only -- not deployed by init
python3 scripts/archive_transcripts.py --check     # report only, writes nothing
python3 scripts/archive_transcripts.py             # archive if grown past the threshold
python3 scripts/archive_transcripts.py --force     # archive regardless
python3 scripts/archive_transcripts.py --print-plist   # launchd job, absolute paths filled in
```

The threshold is **growth since the last archive**, not absolute size — with
retention pinned the source only grows, so an absolute threshold would re-archive
the whole tree on every run once crossed.

Exit codes are distinct so a scheduler can tell the cases apart:
`0` archived and verified · `1` script error or refused · `2` verification failed
(the partial archive is discarded) · `3` below threshold, nothing written ·
`4` archived, **and the source had shrunk since the last run** — investigate.

Verification is three gates, all required: `tarfile` completed and skipped
nothing, the gzip stream decompresses end to end, and the archive's member count
equals `len(snapshot)` — the list taken *before* writing, never the count of what
tar managed to write. The file only takes its final name after all three pass.

It refuses rather than guesses in four cases, each earned from a demonstrated
failure: a source with zero files, a source the walk could not fully read, a
target filename that already exists (pass `--force`), and a `--dest` whose parent
is missing (an unmounted volume). It prunes only archives recorded in its own
manifest, never the one it just wrote, and never below one.

Pipe `--print-plist` to a file under `~/Library/LaunchAgents/` and `launchctl
load` it if you want it scheduled; the script never installs itself.

## Updating Docs After Code Changes
```
# Spawn docs-maintainer agent:
# "Update docs/CONVENTIONS.md — we added X pattern to espalier/Y.py"
# "docs/SHARP_EDGES.md — we fixed the Z footgun, remove that entry"
# "ESPALIER_MEMORY.md session log — record today's changes"
```

## Good Prompts

### For /implement-task
- "Add return type hint to all public functions in espalier/doctor.py"
- "Fix the bare except in espalier/scanners/imports.py line 42"
- "Add test coverage for the happy path in espalier/diffing.py"

### For /design (harness config review)
- "Review the harness setup — we added a new espalier/migrations.py module"
- "Check if any commands reference paths that no longer exist"
- "Is the test-writer agent up to date with our new fixture patterns?"

### For agents
- "Use the architecture-analyst to check if this PR violates layer boundaries"
- "Use the code-reviewer to review tools/cc/hooks/write_guard.py"
- "Use the docs-maintainer to check if docs/CONVENTIONS.md still matches the code"
