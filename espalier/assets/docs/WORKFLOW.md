# Workflow Guide

How to use Espalier-Harness day-to-day. This guide walks through the
lifecycle of a working session: starting up, making changes, checking
your work, committing, and handing off to the next session.

For what the hooks do and how to configure them, see
[`HOOKS.md`](HOOKS.md).

---

## Starting a session

When you launch Claude Code in a harnessed repo, `session_start` fires
automatically. It loads repo context (branch, dirty files, blueprint
state) into Claude's working memory and runs health checks. You'll see
a block like:

```
=== Espalier-Harness === Session Start ===
Host: OS=Darwin; python3=yes python=no (python3 only)
Repo:      your-project
Branch:    main
Status:    8 uncommitted changes
Memory:    **Repo:** your-project | **Stack:** python
Blueprint: Auto-started new blueprint session
Surface:   healthy
Integrity: ok
Commands: /status /implement-task /smoke /preflight /commit /handoff
Run /status to verify harness state.
```

The `Host:` line reports your machine (this capture is from a Mac); on a
returning session the `Blueprint:` line carries the prior session's
context instead of the auto-start notice.

The SessionStart hook auto-orients Claude on every new session — it
injects a one-line `/recall` pointer to whichever footgun catalogs your
repo actually has, a MEMORY digest once `ESPALIER_MEMORY.md` carries
dated Session Log rows, and orientation instructions. Each section is
gated on its own artifact, so the banner describes your tree rather than
the harness's. Claude OPENS with a provisional first-thoughts read of
the handoff (pulling full MEMORY/footgun detail on demand via `/recall`)
without operator prompting. For an explicit re-orient mid-session —
after a long discussion drifts, after PostCompact, or to recover from a
degraded surface state — run:

```
/context-load
```

This reads the cognitive blueprint chain (decisions, rejected
alternatives, discovered patterns from prior sessions) and ESPALIER_MEMORY.md,
then orients Claude with what happened last and what's next. If the
surface is degraded (missing files, broken settings), it prints recovery
guidance instead.

For a quick glance at where things stand without loading full context:

```
/status
```

This gives you branch, recent commits, blueprint state, and harness
health in about 10 lines. It never starts a new blueprint session — safe
to run anytime.

---

## Making a change

### The basic loop

Every source-file change goes through the same pattern: plan, then
write, then prove. The harness enforces this — if you try to use
Write or Edit on a source file without a plan, `plan_guard` blocks
the write.

For a focused change (one file, one proof path):

```
/implement-task Fix the off-by-one error in pagination.py
```

Claude will restate the task, identify affected files, present a plan,
and wait for your approval. After you approve, it creates an execution
plan (`cc/execution_plan.json`), makes the change, runs the targeted
test, and reports results.

For coordinated changes across multiple files or subsystems:

```
/implement-task --multi Migrate auth from session tokens to JWT
```

This decomposes the task into numbered steps, each with its own proof
and rollback path. Claude executes them in order with a gate between
each step — if step 3 fails, it stops and asks how to proceed rather
than pressing forward into a broken state.

`/accomplish` is an alias for `/implement-task --multi`. It does the
same thing.

Both operate on a task you describe *now*, in chat. The next tier up —
task packs — is for work worth specifying and reviewing as a document
*before* any code executes.

### Task packs — planned work as a durable artifact

A **task pack** is a `TP-<N>-<name>.md` file that specifies one change
set completely: its motivation, `Scope (in)` / `Scope (out)`, an
`Affected symbols` list, implementation notes, the `Verify` greps and
tests that prove it, pass criteria, and a `Landing` stanza it stamps
when it ships. You author it ahead of time — by hand, from an earlier
session's findings, or with the `blueprint-authoring` skill — and then
run it:

```
/implement-pack TP-<N>-<name>.md          # one pack
/implement-pack task-packs/               # every TP-*.md in the folder, in order
/implement-pack --resume                  # continue an interrupted chain
```

`/implement-pack` is **not** a "just do what the file says" runner. It
wraps the pack in the same plan → prove → land discipline as
`/implement-task`, plus four pre-flight gates and a post-execution
review that a from-chat task doesn't get. Why reach for a pack instead
of describing the change in chat:

- **The plan is a reviewable file, not scrollback.** It survives
  compaction, a different session can pick it up mid-flight (`--resume`
  reads the on-disk execution plan), and the pack itself is reviewed as
  a *document* before a single edit runs.
- **Four pre-flight gates catch pack defects before you touch code.**
  Step 0-A dispatches the `code-reviewer` agent against the pack text —
  wrong line numbers, symbols that don't exist, false prose claims,
  stdlib-rule violations in the example code. Then 0-B `scope-check`
  builds the reference graph for every symbol the pack changes and flags
  scope gaps; 0-C probes for duplicated code the change should compress
  rather than fork; 0-D `surface-impact` reads the pack's declared new
  and removed paths and prints the count-pins, mirrors, and contracts
  those files will owe once they land or leave — so the SoT edits get
  bundled up front instead of surfacing as a red suite later.
- **One atomic commit per pack.** Staging is exactly the files the pack
  touched plus the integrity manifest — a clean, revertable unit with a
  message that names the pack and carries its verification numbers.
- **The code the pack *wrote* gets an orthogonal review.** Before the
  full suite runs, step 6 dispatches `code-reviewer` (and, for a
  hook / gate / command / agent / skill change, `failure-mode-reviewer`)
  on the pack's own diff — both at once, with edits frozen until both
  reports are in, so their findings land as one fix batch and the suite
  then runs once. A green suite proves the tests pass; it does not prove
  the new code is correct — this is the net that catches the latent bug
  the suite didn't. (It runs here because the ambient stop-gate review
  is bypassed during pack execution.)
- **Packs chain unattended.** Point `/implement-pack` at a folder and it
  runs pack after pack, auto-continuing across each commit unless a
  defined stop condition fires — a test failure, a release-gate failure,
  an `audit` finding, unexpected integrity drift, an acceptance line it
  can't verify, an undocumented breaking change, or an explicit `STOP`
  marker in the pack. This is the basis for the dev-only overnight
  driver (`AUTONOMOUS_EXECUTION.md` in the source tree).
- **Every pack leaves an audit trail.** On landing it stamps a
  `Landing` stanza (`State: LANDED`, commit SHA, suite numbers, the reds
  it earned, date) and moves to `task-packs/Done/` — so "what shipped
  and how it was verified" is recorded per pack, not reconstructed from
  git later.

The per-pack lifecycle, end to end: **pre-flight gates** (0-A pack
review → 0-B scope-check → 0-C compression probe → 0-D surface-impact) →
**draft the execution plan** → **execute phase-by-phase** with targeted
proof at each phase → **orthogonal review** (both reviewers together, one
fix batch) → **integration check** (the one full-suite run + release gate +
audit) → **changelog + SoT mirrors** →
**one atomic commit** → **stamp Landing + move to `Done/`**. In folder
mode this repeats for each pack without asking permission between them.

To iterate on a pack's scope before committing to execution, run the
pre-flight standalone:

```
/scope-check TP-<N>-<name>.md
```

This walks the `## Affected symbols` section, classifies each symbol
against the surface support matrix, and exits non-zero if the scope is
gapped or the section is missing — the same gate `/implement-pack` runs
as its step 0-B. See [`PACK_AUTHORING.md`](PACK_AUTHORING.md) for the
required section format.

### What requires a plan

Source files (`.py`, `.js`, `.ts`, `.go`, `.rs`, etc.) and root-level
project files (`README.md`, `pyproject.toml`, `Dockerfile`) require an
active execution plan before Claude can write to them.

What doesn't require a plan: tests, harness infrastructure, scratch files, and
ESPALIER_MEMORY.md — plus the directories the harness seeds docs into and then
routes you toward (`memory/`, `docs/`, `task-packs/`), since pack authoring
precedes any plan by construction. These are exempt so you can iterate on
tests, harness config and your own packs without ceremony. The exact list is
`EXEMPT_PREFIXES` in `tools/cc/hooks/plan_guard.py`, and that constant is the
maintained enumeration. Prefixes are matched against the repo-relative path of
the file being edited, so a match means "no plan required for this path".

### When a plan is interrupted

If Claude's context fills up mid-task or you need to resume in a new
session, the execution plan persists on disk. Run `/status` or
`/context-load` in the new session — Claude picks up from the first
pending step.

The mutation window stays open only while the plan's `status` is
`in_progress`. A completed, planned, or cancelled plan does *not*
authorize new writes — run `/implement-task` again to open a fresh
plan. See [`HOOKS.md`](HOOKS.md#plan-status-and-the-mutation-window)
for the full plan-status table.

---

## Checking your work

### Quick scan

```
/scan
```

Runs the built-in code quality scanners — stdlib-only, fast, and
opinionated. Bare `/scan` runs every sub-mode; you can also narrow the
focus to one:

```
/scan exceptions     — swallowed exceptions only
/scan prints         — print() calls that should be logging
/scan godfiles       — large files with extraction hints
```

Three of eleven `/scan` sub-modes are shown above; see
[`docs/CHEAT-SHEET.md`](CHEAT-SHEET.md) for the full set.

### Structural integrity

```
/smoke
```

Checks that required files exist, JSON parses cleanly, no placeholder
text leaked into production files, and no terminal junk (pasted `less`
output, diff fragments) contaminated any file. It also confirms that
every command and agent named in `CLAUDE.md` has a file on disk, that
the skill files listed in `cc/PACK_MANIFEST.txt` are present, and that
the `settings.json` hook wiring points to scripts that exist.

This is mechanical — it checks structure, not meaning. No external
tools needed; run it after any harness configuration change to make
sure nothing is dangling.

For doc-accuracy checking — "CLAUDE.md says 17 commands, is that true?"
— use the deeper variant:

```
/audit-accuracy
```

This runs the accuracy audit, which cross-references documented claims
against the actual repo state: agent counts, hook lists, schema fields,
command references. It's the "does what we say match what exists?" check.

### Harness integrity

```
/integrity verify
```

Verifies that protected harness files haven't drifted from their
recorded hashes. If you've made legitimate changes to harness files
(hooks, settings, CI workflows), refresh the manifest:

```
/integrity refresh
```

### Pre-PR gate

```
/preflight
```

Runs everything, cheapest first: lint (if configured), the surface audit
and integrity check, the release gate and reflection pass (their failures
are edits), the diff review (both reviewers dispatched together, their
findings landed as one fix batch), and only then the full test suite and
pin check, once. Reports a GO/NO-GO verdict. Run this before pushing a PR
— it catches the things individual checks miss by running them together,
and it pays for the expensive tier only after every edit it will ask for
is in.

---

## Writing tests

```
/test-this path/to/module.py
```

Generates tests for a specific file, matching the project's existing
test style — import patterns, fixture usage, assertion conventions,
naming (`test_{module}_{behavior}`). Covers happy paths, edge cases,
and error paths.

---

## Committing

```
/commit
```

Reviews the uncommitted diff file-by-file, checking for debug
artifacts, secrets, unfinished work, and test coverage. Then stages and
commits with a generated message following conventional commit format.

If anything looks risky, Claude flags it before committing and asks
whether to proceed.

---

## Ending a session

```
/handoff
```

The clean shutdown sequence:

1. Records durable reasoning (decisions, rejected alternatives,
   discovered patterns) into the cognitive blueprint.
2. Updates ESPALIER_MEMORY.md with session-relevant operating knowledge.
3. Finalizes the blueprint so the next `/context-load` picks it up.
4. Emits a structured handoff summary: what changed, what's proven,
   what's next, what's risky.

If you skip `/handoff` and just close the terminal, the stop gate will
try to catch you. If you've made 10+ source writes, it blocks until
you've run a docs refresh and code review. If there are uncommitted
changes with no session state saved, it blocks until you update
ESPALIER_MEMORY.md or commit. This is friction by design — the most common way
to lose work across sessions is closing without capturing state.

---

## Agents

Agents are specialized reviewers that run in their own context window.
You invoke one with an `@agent-<name>` mention in chat (`@agent-code-reviewer`);
Claude dispatches the same agents by name (`subagent_type='code-reviewer'`).

### code-reviewer

Reviews code changes for correctness, style, and project-specific
pitfalls. Also monitors convention drift — patterns in use that aren't
documented, and documented patterns no longer in use. The stop gate
references this agent: after 10+ writes, it blocks the first Stop of each
turn until this agent has run (its SubagentStop writes the record the gate
reads).

### docs-maintainer

Audits and updates the documentation layer: ESPALIER_MEMORY.md,
CONVENTIONS.md, SHARP_EDGES.md, CHEAT-SHEET.md, TASK_RECIPES.md.
Doesn't generate docs from scratch — it keeps existing docs accurate as
the codebase evolves. The stop gate references this agent too: after
10+ writes, it blocks until docs have been refreshed.

### @architecture-analyst

Reviews changes for architectural consistency. Flags layer boundary
violations (e.g., `tools/cc/` importing from `espalier/`), circular
dependencies, hook exit code errors, and scanner isolation failures.
Scope is strictly architectural — it doesn't review correctness or
style.

### @test-writer

Generates tests matching the project's existing test style exactly.
Knows the fixture patterns, naming conventions, and class-per-feature
grouping used in `tests/`. More thorough than `/test-this` — it
discovers coverage gaps across the test suite and proposes targeted
additions.

### @repo-analyst

Grounds the harness on the repo. On the **first run** (no saved
fingerprint) it establishes the baseline — this is the post-`init`
grounding step; run it via `/analyze` as your first session. Thereafter it
detects structural drift from the last saved fingerprint (languages,
frameworks, architecture, test patterns, CI/CD) — useful after a major
refactor or when returning to a project after time away.

### @harness-config-advisor

Evaluates whether the current agent/command/hook setup matches the
repo's actual needs. Advises on additions, removals, and adjustments.
Run this after significant project changes — if you've added a new
language or framework, your harness config may need to evolve with it.

---

## Working across sessions

### Cognitive blueprints

The blueprint system serializes reasoning across sessions. When Claude
makes a design decision, rejects an alternative, or discovers a pattern,
it records that into the active blueprint. When the session ends
(`/handoff` or the stop gate's auto-finalize), the blueprint is
finalized and becomes input for the next session — the SessionStart
hook loads the active blueprint at session begin, and
`/context-load` re-loads it on explicit re-orient.

You don't interact with blueprints directly most of the time — the
commands handle it. But if you need to inspect the chain:

> **Interpreter note.** The commands below spell `python`. A stock macOS ships only
> `python3` (and it is 3.9; Espalier requires 3.10+), while many Windows installs ship
> only `python`. Use whichever both resolves AND reports 3.10+
> (`<name> --version`); on a stock macOS `python3` resolves but is 3.9.
> `espalier doctor .` checks this for you.

```bash
python tools/cc/cognitive_blueprint.py chain
```

### ESPALIER_MEMORY.md

A human-readable file of durable repo knowledge: harness decisions,
discovered footguns, current blockers, next-step constraints. Updated
during `/handoff`. Unlike blueprints (which are structured JSON for
machine consumption), ESPALIER_MEMORY.md is prose you can read and edit directly.

### Execution plans

Persist in `cc/execution_plan.json`. If a session is interrupted
mid-task, the plan survives. The next session's SessionStart hook
surfaces the active blueprint automatically; `/status` and
`/context-load` show pending steps explicitly.

---

## Advanced workflows

### Maintenance mode

When you need to edit the harness itself — hooks, settings, CI
workflows — the normal guards would block you. Set maintenance mode
before launching (`--continue` keeps the session you were denied in):

```text
POSIX / Git Bash / WSL:  ESPALIER_MAINTENANCE_MODE=1 claude --continue
PowerShell:              $env:ESPALIER_MAINTENANCE_MODE="1"; claude --continue
cmd.exe:                 set ESPALIER_MAINTENANCE_MODE=1 && claude --continue
```

This bypasses write_guard's protected-zone check, plan_guard's plan
requirement, stop_gate's hygiene gates, and subagent_stop's blueprint
append (subagent reasoning is not captured while it is on). It does not
bypass the kill-switch detector, dangerous-command blocking or the
speed-bump checkpoints.

Every bypass logs to stderr so the session transcript shows what was
skipped. See [`HOOKS.md`](HOOKS.md) for the full configuration
reference.

### Reflection

The reflect system runs automatically (every 10th source write via the
`reflect_trigger` hook), but you can trigger it manually:

```
/reflect
```

Invoking the reflect skill this way runs a deeper pass — Claude will
re-read all artifacts produced in the current session and look for
cross-file gaps, broken references, and emergent patterns that weren't
visible during sequential generation.

### Debugging

When you hit an error, Claude's first move should be checking
`SHARP_EDGES.md` for known footguns matching the
symptom. Many recurring issues are already cataloged with fix shapes.
The debug skill encodes this — it consults SHARP_EDGES before reading
source.
