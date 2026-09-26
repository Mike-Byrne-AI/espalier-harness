# Espalier-Harness

[![CI](https://github.com/Mike-Byrne-AI/espalier-harness/actions/workflows/harness-guard.yml/badge.svg?branch=main)](https://github.com/Mike-Byrne-AI/espalier-harness/actions/workflows/harness-guard.yml)
[![Status: pre-release](https://img.shields.io/badge/status-pre--release-orange.svg)](#quick-start)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue.svg)](#quick-start)

**A Claude Code workflow harness for solo founders and small teams — a
working partner that keeps your coding agent on the rails: plan-gated
changes, cross-session memory, per-step proof, and seatbelt hooks that
catch slips like the agent disabling its own safety. Drops into any
repo.**

*An [espalier](https://en.wikipedia.org/wiki/Espalier) is a fruit tree trained
to grow flat against a frame — shaped deliberately rather than left to sprawl.
Same idea, applied to a coding agent.*

## Why?

Claude Code can write code. Whether it writes the *right* code in the
right place, at the right time — following your workflow instead of
free-handing edits, and without silently taking off its own safety rails
when a hook feels like it's in the way — is a separate question. The
failure mode isn't an attacker; it's drift: you or the agent forgetting a
step, skipping the plan, or (the load-bearing case) the agent under load
deciding a hook is "in the way" and disabling it — which quietly loosens
everything downstream.

Espalier is a working partner that makes *following the workflow the path
of least resistance*. It loads your project context every session,
remembers decisions across sessions, gates source changes behind a plan
with per-step proof, and puts seatbelt hooks in the way of the slips that
matter — most of all the agent disabling its own safety mid-task. A CI
gate backstops the local layer at merge time, so drift can't quietly ride
to `main`.

## Try it

Install from PyPI (zero third-party deps on Python 3.10+), then `init`
inside the repo you want governed. macOS ships only `python3`, so type
`python3` for the `python -m …` lines:

```bash
python -m pip install espalier-harness
cd /path/to/your/repo
python -m espalier init . --wire-hooks   # deploys hooks, agents, commands, skills, seeded docs
python -m espalier doctor .              # pass / warn / fail, with the next step named
claude                                   # the SessionStart hook loads your context
```

`--wire-hooks` is for a repo that already has a `.claude/settings.json`: it
wires the hooks into that file in one step instead of asking (a bare `init`
asks, and inside a pasted block the next line answers for you). With no
settings file yet it changes nothing.

Prefer a governed *copy* that leaves your original untouched? That is
`fuse`, and it runs from a source checkout of this repo rather than the
wheel:

```bash
python -m espalier fuse /path/to/your/repo --out /path/to/your-repo-governed   # from a source checkout
```

Full walkthrough — the pip path, fusion from source, cloning a governed
repo, `doctor`, uninstalling, upgrading, the `python3` caveat in detail — is
[`docs/QUICKSTART.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/QUICKSTART.md).

## 30-second demo

The daily loop, then the seatbelt. The deny strings below are drawn from
the hook source (abbreviated where marked `…`); `tests/test_demo_end_to_end.py`
exercises these same behaviors — the protected-zone deny, `espalier doctor`,
and `release_check` — end-to-end so they stay honest.

**1. The workflow loop.** Source changes go through a plan, so the agent
follows the workflow instead of free-handing edits — and you get a plan →
write → per-step proof trail:

```text
# In Claude Code: edit a source file with no active plan
✗ PreToolUse:Edit hook blocked
  No active execution plan (missing). Mutation requires status='in_progress'; …
    Do: `/implement-task "<one-line description>"` then proceed.
```

**2. The seatbelt.** When the agent decides a hook is "in the way" and
reaches for the kill-switch under load, the seatbelt catches it and points
back at the workflow:

```text
# In Claude Code: "Edit .claude/settings.json to set disableAllHooks: true"
✗ PreToolUse:Edit hook blocked
  Write to protected harness zone blocked: .claude/settings.json. Harness
  self-edits: exit and relaunch with `ESPALIER_MAINTENANCE_MODE=1 claude --continue`
  (env read at launch; mid-session export is ignored; --continue keeps this
  session) … (reason continues with Don't/Do workflow guidance)
```

(On Windows the same hint spells the PowerShell form,
`$env:ESPALIER_MAINTENANCE_MODE="1"; claude --continue`, first.)

A repo-condition readout and the merge-time backstop, any time (on macOS type
`python3` here too — the caveat above covers the bare `python <script>` form as
well as `python -m …`):

```text
$ espalier doctor .
{ "status": "warn", "warnings": ["saved reports differ from fresh inference"] }
# (abridged — live JSON also carries checks / repo_root / next_steps / …; a summary line prints to stderr)

$ python scripts/release_check.py
release_check OK
```

For the full walkthrough, see [`docs/DEMO.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/DEMO.md).

## What you get day to day

The harness is the working partner around your daily coding loop:

- **`/implement-task`** — plan a change, execute it step by step, and prove
  each step. `/implement-task --multi` (alias `/accomplish`) coordinates
  multi-phase work. Source edits are gated behind the plan, so changes stay
  deliberate.
- **`/implement-pack`** — for larger work, the task-pack loop: author a
  `TP-N.md` (the `blueprint-authoring` skill teaches the format), pre-flight
  it with `/scope-check`, then execute it end-to-end. A pack is a durable,
  reviewable, resumable unit of agent work — the heart of coding with agents
  on a real codebase. See
  [`docs/WORKFLOW.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/WORKFLOW.md)
  and [`docs/PACK_AUTHORING.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/PACK_AUTHORING.md).
- **Cross-session memory + cognitive blueprints.** `ESPALIER_MEMORY.md` carries
  project context and decisions across sessions; per-session blueprints
  capture the reasoning behind a change so the next session re-engages
  instead of re-deriving. Context auto-loads at session start.
- **A governance roster.** Bundled agents, slash commands, and on-demand
  skills (`/review`, `/reflect`, `/adversarial`, `/scan`, and more)
  delegate review, analysis, and drift-detection to focused sub-agents.
- **`/recall`** — pulls the most relevant accumulated project judgment for
  whatever you're touching. It returns up to four candidates — the NEAREST matches
  from two rankers, alternating — for you to pick between, and goes quiet only when
  your query shares no vocabulary with the corpus; silence is not a relevance verdict.
- **`/handoff`** — ends a session cleanly: finalizes the blueprint, updates
  `ESPALIER_MEMORY.md`, and leaves the next session with usable continuity.
- **Code-quality scanners** (`/scan`, `/preflight`) — stdlib-only AST
  scanners that flag drift and smells, so the harness drops into any repo
  without extra dependencies.

The roster above is **our own working set, dogfooded on this repo and shipped
verbatim**: the deployed `code-reviewer.md` reads as Python-flavored because it
was written to review the harness's own Python code, and several command and
skill bodies reason about this repository's own files and defect ids. Treat them
as starting examples and budget a session to rewrite the bodies for your repo's
language and conventions. The docs `init` seeds are the same kind of thing: the
largest single file among them is `docs/FAILURE_MODES.md`, our own failure
catalog shipped verbatim, disclosed in its own header and there to be read when
a failure mode bites rather than up front.

For the day-to-day session lifecycle (start → change → check → commit →
hand off), see [`docs/WORKFLOW.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/WORKFLOW.md).

## Three layers

**Friction (hooks).** PreToolUse and PostToolUse hooks keep the agent on
the workflow: they require plan discipline before source changes, hold the
anti-self-disable floor (writes to harness files / `disableAllHooks` are
denied so the hooks can't be silenced mid-session), catch dangerous writes,
and validate file integrity after every write. Every slip the friction
layer is known to catch is pinned as a regression so a future change can't
silently re-open it.
Tested against 57 in-scope bypass classes (plus 8 documented
out-of-scope cases under `bench/corpus/BC-OOS-*`), all pinned as
regressions.

**Visibility (audit).** An integrity manifest hashes the enforcement scripts
and the CI workflow. A kill-switch scanner flags `settings.json` modifications
that would silently disable enforcement. Audit events append to a path outside
the repo tree — visibility, not a boundary (a session shell can still delete it;
the CI layer below is the only real guarantee).

**Guarantee (CI).** A GitHub Action gates merges on harness integrity. The
runner is outside the agent's reach. This is the only layer with a real
guarantee.

## What this is NOT

Not a sandbox. Not a security boundary. Not a comprehensive policy engine
for enterprise compliance. Not a turnkey "make my agent good" experience
with maximum agents and skills. It's a self-contained governance harness
for individual developers and small teams who want hook discipline without
pretending hooks are more than they are.

## What espalier governs (and what it doesn't)

See [`docs/SURFACE_SUPPORT_MATRIX.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/SURFACE_SUPPORT_MATRIX.md) for
the full declaration of which Claude Code surfaces espalier guards,
supports, defers, or considers out of scope. Quick summary:

- **Guards** (active enforcement with tested contract): main session
  Write/Edit, dangerous Bash patterns, settings changes, bundled
  subagent capability tiers, compaction (PostCompact).
- **Supports** (ships content / audits, doesn't enforce on third
  parties): bundled skills, bundled slash commands, hook-failure
  behavior of espalier-shipped hooks.
- **Documented-only** (acknowledged, no implementation): MCP tool
  calls, FileChanged, CwdChanged.
- **Deferred** (future): agent teams, worktree creation governance,
  ExitPlanMode → plan bridge.
- **Unsupported** (out of scope): user-added skills/agents, MCP
  elicitation, notification routing, plugin marketplace.

The matrix is normative — the front-door docs (this README,
`docs/QUICKSTART.md` and `docs/CHEAT-SHEET.md`) are tested against it for
overclaiming via
`tests/test_surface_support_matrix.py::TestPublicDocsNoOverclaim`; the rest
of the public set is not in that scan.

## Quick start

Espalier installs from PyPI and governs your repo **in place**: `pip install
espalier-harness`, then `init` deploys the harness into the repo you are
standing in. The alternative is **fusion**: a single command builds a *new*
repo that is your project + the harness overlaid at root, leaving your
original untouched — it runs from a source checkout of this repo, not the
wheel. The install guide is [`docs/QUICKSTART.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/QUICKSTART.md):
the pip path step by step, fusion from source, cloning a repo that already
uses Espalier (its hooks are per-machine and need one `init` on yours),
verifying with `doctor`, uninstalling, upgrading — and the `python3` caveat
for stock macOS. The five-command form is at the top of this README.

`fuse` does the *mechanical* bootstrap — copy your git-tracked files, overlay
the engine + hooks + reusable docs, reseed espalier-specific content empty,
then wire it via `init` + `install-ci` + a host-targeted `fingerprint`. What
it cannot mechanize is a **finish-up checklist it prints when done**, for your
first Claude session in the fusion — budget a focused session for it, not a
glance. After `init`, run `/analyze` in that first session to ground the
harness on your repo — see [`docs/ADOPTING.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/ADOPTING.md).

Init (run directly, or by `fuse`) deploys the mechanical enforcement layer:

- **12 hook entry scripts + 13 helper modules** in `tools/cc/hooks/`
- **`.claude/settings.json`** wiring those hooks into Claude Code
- **`tools/cc/statusline.py`** — prompt statusline surfacing MAINT /
  STOP gate / blueprint chain depth
- **`.claude/agents/*.md`** — 7 governance agents:
  `architecture-analyst`, `code-reviewer`, `docs-maintainer`,
  `failure-mode-reviewer`, `harness-config-advisor`, `repo-analyst`,
  `test-writer`.
- **`.claude/commands/*.md`** — 17 slash commands, including the
  task-pack workflow (`implement-pack`, `scope-check`,
  `audit-accuracy`) and `integrity`.
- **`.claude/skills/*/SKILL.md`** — 9 on-demand skills:
  `adversarial`, `analyze`, `arch-check`, `blueprint-authoring`,
  `debug`, `design`, `hook-authoring`, `reflect`, `review`.
- **`CLAUDE.md`** with detected language/profile context
- **`ESPALIER_MEMORY.md`** with a starter session log
- **`.espalier/integrity.json`** hash manifest for tamper detection
- Fingerprint and harness config in `reports/`

<!-- deploy-inventory: BEGIN generated region -- do not hand-edit. Regenerated by scripts/generate_doc_regions.py from espalier/managed_inventory.py + espalier/cli.py::INIT_TOOL_SCRIPTS. -->
`init` also creates the paths below. Every path and count here is
generated from the deploy inventory itself, so the list is complete
and cannot drift from what lands in your repo.

- **`docs/`** — 18 files, seeded, refreshed on re-init only while untouched, and yours to edit: `CHEAT-SHEET.md`, `CONVENTIONS.md`, `ENV_CATALOG.md`, `FAILURE_MODES.md`, `FRESHNESS.md`, `HOOKS.md`, `HOOK_ASSUMPTIONS.md`, `INSTALL-CI.md`, `PACK_AUTHORING.md`, `SHARP_EDGES.md`, `TASK_RECIPES.md`, `TROUBLESHOOTING.md`, `WORKFLOW.md`, `external/cc-hook-protocol.md`, `sharp-edges/README.md`, `sharp-edges/closed-loop-verification-trap.md`, `sharp-edges/convergence-is-an-angle-set-property.md`, `sharp-edges/hook-exit-codes-channel-xor.md`
- **`memory/`** — 1 file, seeded, refreshed on re-init only while untouched, and yours to edit: `README.md`
- **`task-packs/`** — 1 file, seeded, refreshed on re-init only while untouched, and yours to edit, but gitignored as local working state -- force-add if you want one in history: `CLAUDE.md`
- **`cc/`** — 3 files, generated surface docs: `COMMANDS.md`, `LIVE_SURFACE.md`, `PACK_MANIFEST.txt`
- **`tools/cc/`** — 13 files, standalone scripts alongside the hook tree: `_blueprint_limits.py`, `_freshness_cache.py`, `_json_safe.py`, `_paths.py`, `cognitive_blueprint.py`, `execution_plan.py`, `read_summary.py`, `reflect_protocol.py`, `session_resume.py`, `session_summary.py`, `sister_site_probe.py`, `statusline.cmd`, `statusline.py`
- **`.claude/`** — 1 file, generated per install, never committed: `settings.json`
- **`.espalier/`** — 1 file, generated per install, never committed: `integrity.json`
- **`reports/`** — 3 files, generated per install, never committed: `cc_surface_gate.json`, `harness_config.json`, `repo_fingerprint.json`
- **`.gitignore`** -- 13 entries appended, unless you pass `--no-write-gitignore`
<!-- deploy-inventory: END generated region -->

`espalier doctor` is repo-mode aware: a fresh `git clone` with no
`init` run is classified as `source_checkout` and passes cleanly.
Pass `--mode source-checkout` / `--mode initialized` to override
auto-detection.

Deployed content carries the `espalier:managed` marker — an explicit
ownership contract. Files carrying the marker are regenerated on the
next `init`; unmarked files in the same directory are preserved.
Use `espalier clean-generated` to remove managed surface.

The agent / command / skill set above is Espalier-Harness's own
dogfooding roster, shipped verbatim. Users with a curated roster can
hand-edit any file — once the `espalier:managed` marker is removed
the harness treats the file as user-owned and preserves it across
inits. A future release will introduce language-aware variants for
non-Python stacks; current releases ship these files as starting
examples (see "Honest scope" below). The harness config (`reports/harness_config.json`) is a
recommendation file showing which agents Espalier's analysis would
suggest for your repo's profile.

```bash
# See what was recommended
python -m json.tool reports/harness_config.json

# The harness is already active -- hooks run on every tool use
/status    # check harness state
```

## Release & CI gate

The [`docs/DEMO.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/DEMO.md) walkthrough (linked from the
30-Second Demo above) also shows the release/CI gate
(`scripts/release_check.py`) — with literal expected outputs that
`tests/test_demo_end_to_end.py` keeps honest.
<!-- espalier:fragment id=release-check-results
     bound=tests/test_release_check.py
     policy=verify-on-touch -->
The release check runs 22 individual gates (printing a "19 passed,
3 skipped" summary); `tests/test_release_check.py` pins the
exact result count.

## Seatbelts, not a sandbox

Espalier's hooks are **seatbelts for agent drift**, not a sandbox. They keep
the path of least resistance pointed at the workflow — and hold the
anti-self-disable floor so the agent can't quietly turn them off mid-task.
They are *not* a security boundary: an agent with arbitrary subprocess
access and unlimited attempts can work around any local hook (a two-step
subprocess write is a documented out-of-scope bypass under
`bench/corpus/BC-OOS-*`). True un-bypassability needs OS-level sandboxing or
containerization, which is out of scope here.

That's by design, not an apology. The honest claim: for solo founders and
small teams where the failures are inattention and drift — not adversarial
action — this stack catches almost everything, and the one layer with a
real guarantee (CI + branch protection, outside the agent's reach)
backstops the rest at merge time. You don't need to defend against
yourself; you need a partner that keeps the workflow the default.

The full layer breakdown — what each hook can and can't block, the
can-block matrix, and the protected-path CI inventory — lives in
[`docs/POSITIONING.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/POSITIONING.md).

## How we test

Espalier pins every slip it has ever seen as a regression, so a future
change can't silently re-open it. The pattern: when the friction layer
catches a new slip-class, it gets a named test class in
`tests/test_write_guard.py` (or `tests/test_integrity.py` for kill-switch
cases) with parametrized cases over canonical forms. The test must fail
before the fix lands, then pass after — regressions can't creep back in.
The same fail-first discipline runs across the stdlib-only code-quality
scanners (`/scan`), which flag drift and smells without adding
dependencies.

The current enumeration of slip-classes lives in
[`bench/RESULTS.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/bench/RESULTS.md), regenerated by
`bench/run_benchmark.py --update-canonical` so it can't drift from the
actual `bench/corpus/BC-*.json` rows. The corpus is a **regression corpus**
over known bypass classes — it pins what the friction layer catches and
what it deliberately doesn't. It is **not a proof of safety** and **does
not prove** the harness is a sandbox or a security boundary.

Plus a `TestBashDocumentedOutOfScopeBypasses` class that pins what the
friction layer deliberately *doesn't* catch (two-step subprocess, command
substitution variable forms). These cases must continue to pass-through;
they are documented limits, not defects.

Because the corpus and those tests quote, as fixtures, the shell operations
the guard exists to catch, the repository trips automated safety classifiers
from time to time.
[`docs/CLASSIFIER_FALSE_POSITIVES.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/CLASSIFIER_FALSE_POSITIVES.md)
explains why, and the wording discipline the fixtures follow.

Both commands below need a source checkout with the dev extra — clone this
repo, then `python -m pip install -e '.[dev]'` (quotes required for zsh) —
which brings in `pytest` and the test tooling. The `pip install
espalier-harness` at the top of this README installs the runtime only, and
the suite does not collect on it.

The suite is sliced by `pytest` markers — `unit`, `integration`,
`contract`, `security`, `release`, and additive `slow`. For a fast local
loop:

```bash
python -m pytest -m "not slow"
```

For release confidence:

```bash
python -m pytest -m "contract or release or security"
```

See [`tests/README.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/tests/README.md) for the full taxonomy and
contributor guidance. Exact test counts are intentionally not documented
because they drift with every parametrize edit; a contract test
(`tests/test_test_suite_contract.py`) enforces marker discipline and a
lower-bound on test files instead.

The same corpus runs as a benchmark against multiple governance baselines —
see [`bench/RESULTS.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/bench/RESULTS.md) for the comparison table. The
benchmark is a regression corpus over known bypass classes, not a proof of
safety: passing it means the documented historical bypasses remain covered,
not that no other bypass exists. We'd rather be calibrated than impressive.

## CLI

The day-1 path is three steps. Most users never need the rest.

> The install at the top of this README (`python -m pip install espalier-harness`)
> puts the `espalier` command on your PATH, which is how the examples below
> spell it; `python -m espalier <command>` is the same verb when pip's scripts
> directory is not on your PATH (common on Windows). Inside a fusion, run the
> verbs as `python -m espalier <command>` from the fusion root, so the engine
> the fusion vendors is the one that runs rather than your checkout's.

### Setup and verify

```bash
espalier init <repo>          # first-time harness setup
espalier upgrade .            # re-deploy a stale harness in place (dry-run by default)
espalier doctor <repo>        # pre-flight health check (pass/warn/fail)
```

(`espalier pre-release` is Espalier's own release gate. On your repo it stands
down at exit 0 reporting `skipped`, so it is not listed here or in `--help`.)

### Common maintenance

```bash
espalier audit <repo>             # run proof gates on existing surface
espalier integrity verify <repo>  # check for hook drift or kill-switches
espalier reflect <repo>           # scan for broken links and drift
espalier scan <repo>              # run all code quality scanners
espalier freshness check <repo>   # report fragment drift; CI gate
```

Exit codes follow a `0` ok / `1` findings / `2` usage-or-precondition
convention — see [docs/CLI_EXIT_CODES.md](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/CLI_EXIT_CODES.md).

Document-claim drift is tracked by **freshness fragments** — small
markers in docs that pin a claim to specific code paths and a
verification SHA. See [`docs/FRESHNESS.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/FRESHNESS.md) for
the operator workflow (add a fragment, re-pin after a verified
change, interpret a critical state).

### Advanced

```bash
espalier fingerprint <repo>       # detect languages, frameworks, patterns
espalier diff <repo>              # compare saved fingerprint vs current state
espalier recover <repo>           # assess surface coherence for resumption
espalier reflect-deep <repo>      # full structured reflect protocol
espalier blueprint <repo> ...     # cognitive blueprint state operations (5 subcommands)
espalier worktree-plan <repo>     # print multi-lane worktree commands
espalier integrity refresh <repo> # create/update integrity manifest
espalier install-ci <repo>        # install the Harness Guard CI workflow
```

The full slash-command and agent reference is in [`docs/CHEAT-SHEET.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/CHEAT-SHEET.md).
For the day-to-day session lifecycle (start, change, check, commit, hand off),
see [`docs/WORKFLOW.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/WORKFLOW.md). For what each hook does, when it
fires, and how to configure it, see [`docs/HOOKS.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/HOOKS.md).
For the full doc map — every guide and reference by audience and scope — see
[`docs/README.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/README.md).

> **Task execution commands:** `/implement-task` is the canonical command — use
> it for focused changes (`/implement-task <task>`) or coordinated multi-phase
> work (`/implement-task --multi <task>`); `/accomplish` is retained as a
> compatibility alias for `/implement-task --multi`. For larger, resumable
> units of work, `/implement-pack` runs a `TP-N.md` task pack end-to-end —
> pre-flight it with `/scope-check`.

## Project structure

```
espalier-harness/
├── CLAUDE.md              Main CC config (harness identity, commands, rules)
├── README.md              This file
├── ESPALIER_MEMORY.md     Persistent session state (at most 120 lines)
├── CONTRIBUTING.md        How to contribute
├── CHANGELOG.md           Version history
├── docs/                  User + contributor docs — QUICKSTART, WORKFLOW, HOOKS,
│                          TROUBLESHOOTING, ADOPTING, CONVENTIONS, SHARP_EDGES,
│                          CHEAT-SHEET (full map: docs/README.md) + pinned
│                          external contracts under docs/external/
├── espalier/               Harness engine (fingerprinting, analysis, cognitive)
│   ├── cli.py             Entry point + all CLI commands
│   ├── analyze.py         Codebase fingerprinting
│   ├── harness_config.py  Build harness config from fingerprint
│   ├── scanners/          stdlib-only AST scanners
│   └── ...
├── tools/cc/              Standalone hook scripts and tools (zero espalier imports)
│   └── hooks/             12 hook scripts: session_start, task_router,
│                          plan_guard, write_guard, config_guard,
│                          post_write_check, reflect_trigger, stop_gate,
│                          subagent_stop, post_compact, subagent_start,
│                          context_reinject_failure
├── .claude/
│   ├── settings.json      Hook wiring and permissions (gitignored; regenerate with init)
│   ├── agents/            7 governance agents
│   ├── commands/          17 slash commands
│   └── skills/            9 on-demand skills
├── bench/                 Friction-layer regression benchmark (gates releases)
├── examples/              Adopter templates (CLAUDE.md, ESPALIER_MEMORY.md, espalier.toml)
├── cc/                    Reference surface and session blueprint storage
├── reports/               Analysis output (JSON, created at runtime)
└── tests/                 pytest test suite
```

> **`cc/` is reserved by the harness** for blueprint + surface storage and is
> write-guarded. If your repo already uses a top-level `cc/` for something else,
> a write there will be denied as a "protected harness zone" — relocate your
> directory (the harness does not currently make this prefix configurable).

## Stop hook mode

By default `stop_gate.py` runs lightweight session hygiene only —
no pytest. To run the core pytest gate on every Stop event, set:

```bash
export ESPALIER_STOP_GATE=full
```

Heavy proof otherwise belongs in `espalier pre-release` and CI.

## Self-host setup

Espalier-Harness is self-hosted. After cloning, generate your local `.claude/settings.json`:

```bash
python -m espalier init .
```

The file is gitignored because it records the interpreter **name** `init` detected on your `PATH` (`python3` on most macOS installs, `python` on Windows and many Linux distros), which is specific to your machine.

## Portability

Espalier-Harness supports Windows, macOS, and Linux. Examples use `python -m ...` form. Bash-specific examples are marked as such.
The Windows host facts — bare `python`, the separate PowerShell tool and how to turn it on, the batch statusline shim, CRLF checkouts, the relief-record encoding — are one section:
[`docs/QUICKSTART.md#windows`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/QUICKSTART.md#windows).

## Settings profiles

`espalier init` writes a `.claude/settings.json` shaped by a chosen
profile. The deny list and hook wiring are profile-independent; only
the permissions allow list changes.

On a Windows host, a fresh `init` also writes a `PowerShell(...)` twin of
every `Bash(...)` allow rule, because Claude Code's PowerShell tool is a
separate tool and permission rules are tool-scoped — without the twins the
allow list is inert for every command the agent issues through PowerShell.
The deny literals are not twinned; that class is caught at the hook layer on
both shells. `init --wire-hooks` on a pre-existing settings file wires the
hooks only and never touches your allow rules; `doctor` and `upgrade` name
the rules and twins the file lacks, and
`python -m espalier merge-settings . --profile <profile> --add-allows`
appends them (`doctor` prints that command with your install's profile
filled in). The twins are rendered and tested, not yet witnessed in a live
Windows session.

> **Where the secret-path protection lives.** The generated `deny` list covers
> dangerous Bash shapes only — you will not find `.env`, `secrets/` or
> credentials rules there, and their absence is deliberate. Reads of those paths
> are denied by `write_guard.py` at the hook layer instead, for the `Read` tool
> as well as for Bash and PowerShell, and unlike a permission rule that check is not bypassed
> by maintenance mode. The rules were moved because configuring **any** `Read()`
> deny rule makes Claude Code require static proof of every Bash command's read
> set: a command whose read set it cannot resolve — one with a `cd`, a relative
> glob, or a glob over a directory it cannot enumerate — raises a permission
> prompt that neither an allow rule nor `bypassPermissions` can suppress,
> because deny outranks both. That turns long unattended sessions into a series
> of stalls. See `docs/SHARP_EDGES.md` → "A `Read()` deny rule silently disables
> bypass mode for every Bash command that reads a file".

| Profile | Allow shape | When |
|---|---|---|
| `minimal` | `Read`, `Grep`, `Glob` | read-only audit work; no Write, no Bash |
| `workflow` *(default)* | + `Write` + narrow test commands (`Bash(pytest *)`, `Bash(git status)`, …) | governed work with rails — writes require an active plan via `plan_guard.py` |
| `full` | + broad Bash (`Bash(python *)`, `Bash(pip *)`, `Bash(git *)`) | power-user posture; the permissive pre-profiles Bash default |

Pick one at init time:

```bash
python -m espalier init --profile minimal .
python -m espalier init --profile workflow .   # default
python -m espalier init --profile full .
```

Or set the per-project default in `espalier.toml` at the repo root:

```toml
default_profile = "minimal"
```

The CLI `--profile` flag overrides `espalier.toml`. Generated
`.claude/settings.json` includes a `$schema` link to
[schemastore.org](https://json.schemastore.org/claude-code-settings.json)
so editors with schema-aware completion validate the file. The shared
deny defaults are the dangerous Bash shapes (`rm -rf /`, piped
`curl | sh`); reads of `.env*` (a dotenv template such as `.env.example`
excepted), `secrets/**` and AWS / generic
credential files are refused by `write_guard.py` at the hook layer, as
the callout above explains — you will not find them in the file.

**Profiles are governance defaults, not a security sandbox.** A
determined operator can bypass via `--permission-mode bypassPermissions`
or by editing `settings.local.json`. The harness defends in depth (deny
rules at the permission layer, `write_guard.py` at the hook layer,
`ci_guard.py` at CI) — no single layer is a hard boundary. See
[`docs/SHARP_EDGES.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/SHARP_EDGES.md).

## Requirements

- Python 3.10+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (CLI)

## Security

Security vulnerabilities should be reported privately. See
[`SECURITY.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/SECURITY.md) — the preferred path is the GitHub Security
tab → `Report a vulnerability`. Do not include vulnerability details in
public issues, pull requests, or discussions.

## Honest scope

Espalier-Harness ships **full mechanical enforcement for any
repo**: hooks, governance gates, bypass corpus, integrity manifest,
freshness signal, init detection, statusline. These work identically
on Python, TypeScript, Go, Rust, or polyglot codebases.

The **agent and command roster** is dogfooded prose; "What you get day to
day" above says what that means for your repo. The forward-work tracker ships
with the source at
[`task-packs/FORWARD_LEDGER.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/task-packs/FORWARD_LEDGER.md):
a non-zero count there is disclosure, not backlog. Every defect we know of is a
row a stranger can act on, counted apart by population, and the file's own
contract says what its count does and does not mean.

A **language-aware templating layer** that renders generic versions
of those roster files based on detected language is planned for a future
release. The current cut intentionally defers that work to ship the
mechanical enforcement layer first.

The scanners behind `/scan` are Python-specific (AST-based). Run on a
non-Python repo they produce empty findings with a `[WARN]` stderr note
and a typed `skipped_no_python_files` result envelope — explicit about
not applying, not silently green. (`/preflight` and `/test-this` are
Python-oriented; the language-aware story for them is on the roadmap.)

## Roadmap

**Language-aware agent templates (planned).** The bundled agents at
[`examples/dogfooding/`](https://github.com/Mike-Byrne-AI/espalier-harness/tree/main/examples/dogfooding/) describe Espalier-Harness's
own use; they're not generic enough to deploy verbatim. A future release
will introduce a templating layer with placeholders for project name, primary
language, test command, and convention paths. Current releases ship the
dogfooded roster as starting examples (see "Honest scope" above) and the
fingerprint substrate the templating layer will validate against.
Subscribe to releases for the announcement.

**More of the Claude Code event surface (planned).** Espalier's
twelve hook scripts cover the ten event types currently wired
(SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure,
ConfigChange, Stop, SubagentStart, SubagentStop, PostCompact). PreCompact for
state preservation, InstructionsLoaded for CLAUDE.md drift tracking, and
WorktreeCreate/Remove for the worktree-plan command are the planned additions.

**Current — hooks + bypass benchmark + governance contract.** The
mechanical enforcement layer is the differentiator and works on any
repo language; the bundled agent / command roster ships as
Python-flavored starting examples pending the planned templating layer.

Espalier-Harness is the Claude Code adapter for a provider-agnostic governance
harness model. The architectural boundary between provider-independent core
and Claude-specific surfaces is documented in
[`docs/ADAPTER_BOUNDARY.md`](https://github.com/Mike-Byrne-AI/espalier-harness/blob/main/docs/ADAPTER_BOUNDARY.md).
