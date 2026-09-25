# Espalier-Harness — Quick Reference

> **On macOS, type `python3`.** Stock macOS ships only `python3`, not a bare
> `python`, so the `python ...` commands below fail with `command not found`
> unless you substitute `python3`. (`espalier init` pins the detected
> interpreter in `.claude/settings.json`, so the hooks themselves are
> unaffected either way.) Stock macOS `python3` is 3.9, BELOW the 3.10 Espalier
> needs: init wires it so the blocking guards keep working, but blueprints and
> Gate 4 stay dead until you install 3.10+ and run
> `espalier init . --rewire-interpreter`.

## Harness Lifecycle
```
SessionStart hook → auto-orients Claude (injects TOC + recency marks + orientation instructions)
  ↓ work ↓
reflect          — Consolidate context (runs automatically every 10th source write)
  ↓ done ↓
/handoff         — Save state, update ESPALIER_MEMORY.md session log
```

`/context-load` is the explicit re-orient verb — useful mid-session,
after PostCompact, or to recover from a DEGRADED surface state. Not
needed at session start.

## Commands by Category

### Session Management
```
/context-load        Explicit re-orient (mid-session, post-compact, DEGRADED-surface recovery). Auto-equivalent runs at SessionStart -- no need to type it at session begin.
/read-summary        Dump the live working-summary doc (cc/_working_summary.md) -- always-current session-resume picture; --session/--list read the per-session archive
/recall <topic>      Recall the most relevant accumulated project judgment for a topic (up to four candidates, two rankers alternating, caller picks; suppresses only out-of-vocabulary queries)
/status              Harness state in 10 lines
/handoff             End-of-session: update ESPALIER_MEMORY.md, save blueprint
```

### Analysis & Design (skills — trigger-phrase activated, not slash commands)
```
analyze              Ground the harness (first-run baseline) + detect drift from saved fingerprint (delegates to repo-analyst + docs-maintainer)
design               Harness config review: agents, commands, hooks, docs (delegates to harness-config-advisor)
review               Code review of branch / diff (delegates to code-reviewer)
arch-check           Layer-boundary + import-direction review (delegates to architecture-analyst)
adversarial          Failure-mode pass (delegates to failure-mode-reviewer)
```

### Authoring (skills — trigger-phrase activated)
```
blueprint-authoring  When composing or refining a task pack
hook-authoring       When writing or extending a hook in tools/cc/hooks/
```

### Task Execution
```
/implement-task <description>          Focused change: plan, approve, implement, prove
/implement-task --multi <description>  Multi-phase: execution plan, per-step gates, integration check
/implement-pack <pack-or-folder>       Execute TP-*.md task packs end-to-end; auto-continues unless stopped
/scope-check <pack-path>               Pre-flight 0-B: walk affected-symbol refs before pack execution
python tools/cc/sister_site_probe.py   Pre-flight 0-C: near-duplicate function bodies in YOUR source (--roots narrows); deployed-hook debt is advisory
/accomplish <description>              Compatibility alias for /implement-task --multi
debug                Trace an error and suggest a fix (skill — trigger-phrase activated)
```

### Quality Gates
```
/smoke               Fast structural integrity check (runs `espalier audit .` as final Step 7)
/preflight           Full pre-PR gate: lint + tests + surface audit + reflect
/commit              Review changes, run risk check, then stage and commit
reflect              Force engineered context consolidation pass (skill — trigger-phrase activated)
```

### Testing
```
/test-this           Generate tests for a file matching project patterns
```

### Code Scanning
```
/scan                Run all code quality scanners (sub-modes: exceptions, prints, godfiles, perf_smells, test_loosening, convergence_theater, subprocess_contracts, filesystem_contracts, magic_depth, retired_vocab, encoding_contracts)
/strengthen          Risk-rank untested public symbols (advisory test-gap report)
```

### Integrity
```
/integrity           Verify or refresh the Espalier-Harness integrity manifest
/audit-accuracy      Verify documented claims against live repo + pinned externals
```

### Contract opt-out marker
```
# contract: ok <rule-id> <reason>   One-line opt-out for a cross-source
                                    parity contract. rule-id is the
                                    kebab-case key in
                                    tests/_surface_expected.py::CONTRACT_CEILINGS;
                                    chip-down via the ceiling row.
```

Hidden harness-developer subcommand (not in operator flow):
```
espalier _refresh-self-host-pin   Refresh write_guard.py content pin (self-host fingerprint)
```

### Reasoning & Blueprints
```
/handoff             Captures reasoning (decisions, alternatives, patterns) and finalizes
```

## Agents

```
repo-analyst          Opus   — Ground the harness (first-run baseline) + detect drift
harness-config-advisor Opus  — Evaluate agent/command/hook setup vs repo needs
docs-maintainer       Sonnet — Keep ESPALIER_MEMORY.md, docs/CONVENTIONS.md, docs/SHARP_EDGES.md, docs/CHEAT-SHEET.md, docs/TASK_RECIPES.md fresh
architecture-analyst  Opus   — Review changes for layer violations and import direction
code-reviewer         Sonnet — Review code for bugs, style, Espalier-Harness pitfalls
test-writer           Sonnet — Generate tests matching this project's patterns
failure-mode-reviewer Opus   — Find self-inflicted failure modes (future-you forgets a step, AI collaborator drifts, refactor misses sister-site)
```

## Key Bash Commands

```bash
# Test suite (the four-file core slice is the Espalier source repo's -- not deployed by init)
pytest tests/test_fingerprint.py tests/test_hooks.py tests/test_scanners.py tests/test_scanner_magic_depth.py -q
pytest -q                           # full suite
pytest -m security                  # security marker slice
pytest -m "not slow"               # skip slow tests
pytest -m release                   # release/packaging tests only

# Setup and verify (day-1 path)
espalier init <repo>              # first-time harness setup
espalier fuse <host> --out <dir>  # build a NEW fusion repo: host copy + harness overlay (originals untouched)
espalier merge-settings <repo>    # wire hooks into an existing .claude/settings.json, adding espalier's statusLine when that key is absent (preserves your keys; keeps a .bak of them)
espalier merge-settings <repo> --add-allows   # also append the profile's allow rules your file lacks (append-only; reported without the flag)
espalier merge-settings <repo> --repair       # also rewrite espalier's OWN hook entries doctor finds dead (no interpreter, missing from its event, wrong event, narrowed matcher, shell form); entries that do not name espalier's scripts are untouched and every removal is listed; keeps a .bak of the file
espalier init <repo> --wire-hooks # one-shot: arm hooks even when a settings.json already exists (opt-in; same flag on `fuse`)
espalier init . --rewire-interpreter # swap a below-floor Python (needs 3.10+) in an existing settings.json; changes only the interpreter name, keeps a .bak of the file
espalier upgrade .                # re-deploy a stale harness in place (dry-run by default; --execute to apply)
espalier doctor <repo>            # pre-flight health check; works on uninitialized repos

# Common maintenance
espalier audit <repo>             # run proof gates on existing surface
espalier integrity verify <repo>  # check for hook drift or kill-switches
espalier reflect <repo>           # scan for broken links and drift
espalier scan <repo>              # run all code quality scanners
espalier strengthen <repo>        # risk-rank untested public symbols (advisory test-gap report)
espalier selfcheck <repo>         # run bundled engine-integrity tests against the installed espalier
espalier selfcheck --contracts <repo>  # the three deployed-tree contracts: live deny-path, upstream parity, live kill-switch
espalier fingerprint <repo>       # detect languages, frameworks, patterns

# Drift detection / recovery
espalier diff <repo>              # compare saved fingerprint vs current state
espalier recover <repo>           # assess surface coherence for resumption
espalier reflect-deep <repo>      # full structured reflect protocol
espalier audit-accuracy <repo>    # verify documented claims against evidence

# Cognitive blueprints — `espalier blueprint <repo> <action>` accepts:
#   start | record | finalize | load | chain
espalier blueprint <repo> <action>
# record-reflect and show-recent are cognitive_blueprint.py actions (not the espalier CLI):
# show-recent: print the N most recent reasoning entries (newest first); --kind decision filters
python tools/cc/cognitive_blueprint.py show-recent --n 5 --kind decision

# Pack scope pre-flight
espalier scope-check <pack-path>  # walk references for a pack's Affected symbols
espalier surface-impact <pack-path>  # 0-D: shipped-surface obligations a pack's added or removed files imply

# Pack landing check (advisory): are a pack's claimed files LANDED/DRIFTED/OWED?
espalier verify-landing <pack-path> --repo .   # [--json]

# Scaffolding-quality canon: 3 independent signals from raw cc/blueprints/*.json
espalier scaffolding-bench --last 20 --json  # continuity, human density, reflect coverage

# Document freshness: check / pin / unpin doc-vs-code fragments
espalier freshness check <repo>   # report fresh/stale/critical/unpinned per fragment
espalier freshness pin <id> <repo> --expected-value <v>  # record HEAD as verified
espalier freshness pin <id> <repo> --force               # consent to bound rebind (bypass safety check)
espalier freshness pin --all <repo>                      # bulk-seed; skips bound-drift
espalier freshness unpin <id> <repo>                     # remove the manifest entry

# Release / packaging: the three Espalier-only verbs (pre-release, release-pack,
# provenance) are under "Release Artifacts" below -- each stands down on your repo
espalier integrity refresh <repo> # update integrity manifest after legitimate edits

# Operational
espalier install-ci <repo>        # install Harness Guard CI workflow
espalier worktree-plan <repo>     # print multi-lane worktree commands
espalier refresh-externals <repo> # rebind external pins to latest sources
espalier surface-handoff <repo>   # write a surface handoff report
espalier self-host <repo>         # prove the harness works against itself
espalier clean-generated <repo>   # remove harness-managed files (dry-run by default)

# Templates / preview
espalier render-template claude    # preview CLAUDE.md template `init` deploys
espalier render-template memory    # preview ESPALIER_MEMORY.md template `init` deploys
espalier render-template changelog # print a clean Keep-a-Changelog skeleton

# ESPALIER_MEMORY.md upkeep
espalier memory prune              # archive oldest Session Log row to docs/session-archive.md
espalier memory prune --rows 2     # archive the two oldest rows
espalier memory prune --rows 0     # smoke check (no-op exits 0)

# Bypass benchmark (`bench/` is not deployed by `init`; a `fuse`-derived repo carries it) — canonical results in bench/RESULTS.md
python bench/run_benchmark.py                    # full run, all baselines
python bench/run_benchmark.py --update-canonical # rewrite bench/RESULTS.md

# Hook check
python -c "import json; [print(e, *h.get('args', [h['command']])) for e,es in json.load(open('.claude/settings.json'))['hooks'].items() for entry in es for h in entry['hooks']]"
```

## Release Artifacts
> **Self-host only** — but for two different reasons, and only one of them is about deployment.
> The `python scripts/…` lines need files `espalier init` does not deploy (and the wheel does not
> carry), so a plain `init` adopter repo will not have them. The two `espalier` verbs below DO
> ship and will dispatch on any repo; they are self-host-only by applicability, and stand down
> rather than act — `pre-release` exits 0 reporting `skipped`, `release-pack` refuses at exit 2.
```bash
# release tooling: Espalier source repo only -- not deployed by init
python scripts/build_release_archive.py    # deterministic .zip
python scripts/fresh_clone_gate.py --python 3.10 --python "$(command -v python3)"  # Tier 3 step 0: the full tier in a fresh clone of HEAD, per interpreter; alone on the box; exit 70 = the gate refused
python scripts/final_release_matrix.py     # pre-tag proof matrix — 6 stages, every stage must PASS
python scripts/release_check.py --validate-archive <path/to.zip>  # dual-witness on external ZIP
espalier pre-release . --output dist/espalier.zip   # gate + clean zip
espalier release-pack . --output dist/espalier.zip  # zip only
espalier provenance .                               # census for Espalier's own build tags (exit 0, stands down, on your repo)
```

## Stop Gate Mode
```bash
# Default: light (skips pytest gate)
# Opt in to full pytest gate for ONE Claude Code invocation (inline prefix
# scopes the var to that single command — does not leak to other shells):
ESPALIER_STOP_GATE=full claude
# PowerShell:  $env:ESPALIER_STOP_GATE="full"; claude
# Or export for the whole shell session (caution: runs pytest on every turn
# — exporting it runs pytest on EVERY Claude Code turn, not just this one):
export ESPALIER_STOP_GATE=full
```

## Layer Rules (memorize these)
```
espalier/      → imports from espalier/ only
tools/cc/     → ZERO espalier imports (runs standalone)
scanners/     → stdlib only (no third-party deps)
hooks/        → structured: exit 0 + stdout JSON (PreToolUse uses
                hookSpecificOutput.permissionDecision); simple block:
                exit 2 + stderr (no stdout JSON); never 1
              → 12 hooks across 10 events (SessionStart, UserPromptSubmit,
                PreToolUse, PostToolUse, PostToolUseFailure, ConfigChange, Stop,
                SubagentStart, SubagentStop, PostCompact)
              → PreToolUse mostly narrow; `write_guard` keeps `*` (kill-switch
                reach + Bash/MCP coverage that narrow Write/Edit matcher would miss);
                `reflect_trigger` (PostToolUse) keeps `*` (cadence counting across all writes)
task_router   → UserPromptSubmit: soft routing nudge (no DENY)
plan_guard    → PreToolUse: DENY source writes without execution plan
write_guard   → PreToolUse: DENY protected zone mutations (write/delete/move) + dangerous commands
stop_gate     → Stop: lightweight (docs→review→finalize); pytest gate opt-in via ESPALIER_STOP_GATE=full
```
