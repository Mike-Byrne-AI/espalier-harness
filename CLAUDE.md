# Espalier-Harness — Claude Code Governance Harness

## Project Context

<!-- recall: skip --> <!-- restates docs/STANDING_PRINCIPLES.md and the memory/ protocols it points at; /recall reaches those sole homes directly (2026-10-08) -->

Espalier-Harness is a governance harness that lives inside your repository and
continuously maintains its Claude Code configuration. It analyzes the
codebase, enforces quality through mechanical hooks, captures reasoning
across sessions via cognitive blueprints, and provides tools for ongoing
maintenance.

**Working context for every session on this tree.** This is a workflow
harness with a friction guard, built by the operator together with Claude,
and the guard work here is the harness testing itself: `bench/` and
`tests/` hold populations of shell and interpreter commands, including ones
that really delete a throwaway directory, because a real shell is the only
honest oracle for what the guard should refuse. An executing row in a bench
is a test fixture. The guard is a workflow toolbelt, not a security
boundary (`docs/STANDING_PRINCIPLES.md` §2), and its records carry counts,
row names, the named user and the fix shape; a change that refuses a new
shape lands with the row that proves it. The operator may edit this block.

Session context is auto-loaded by the SessionStart hook. The hook
injects a MEMORY digest (identity line + recent-session headlines), the
standing-principles index, and a one-line `/recall` pointer to the
footgun/failure-mode catalogs, plus orientation instructions Claude
follows on first response — it OPENS with a provisional first-thoughts
read of the handoff (pulling full MEMORY/footgun detail on demand via
`/recall`), not a full-file read. Run `/context-load` explicitly only
to re-orient mid-session, after PostCompact, or to recover from a
DEGRADED surface state (per `tools/cc/session_resume.py`). ESPALIER_MEMORY.md
has project context; the session history is one file per row under
`memory/session-log.d/`.

**No banner means no hooks.** If this session did not open with the SessionStart
banner, the hooks did not load: say so in your first reply and make no edits
until the operator answers (`/hooks` lists what loaded). The measured cause
(2026-10-08) is a session launched in a worktree, which checks out tracked files
only, so the gitignored `.claude/settings.json` is not there. `.worktreeinclude`
copies it into new worktrees, and the landing check's wiring arm refuses a push
from a checkout without it. A banner can also be lost with the hooks loaded:
Claude Code drops a SessionStart hook's whole output past its 15 s timeout, and
the session's transcript (`~/.claude/projects/<project>/<session>.jsonl`) then
holds a `hook_cancelled` record for SessionStart with `timedOut: true` (13 of 95
starts on the Windows box, DEF-3015). The hook now cuts itself at a 13 s wall
and gives a short banner whose `Cut:` line says so. Where no banner arrived and
the newest SessionStart record in this session's transcript is that one, read
`.claude/settings.json`: `PreToolUse` wiring `write_guard.py` and
`plan_guard.py`, with no settings file setting `disableAllHooks`, means the hooks
loaded, so say so in your first reply and proceed.

The live working-summary doc `cc/_working_summary.md` is a pull-only,
always-current mirror of the last boundary's summary (rewritten at every
compaction and `/handoff`) plus the espalier resume index — never injected.
Pull it (or `/read-summary`) when you need the full
pick-up-where-we-left-off picture; the per-session archive under
`cc/blueprints/compact_summaries/` is the after-the-fact record
(`/read-summary --session`).

## Priority Order (when instructions conflict)

1. Mechanical enforcement (hooks) over instruction-layer suggestions
<!-- canon: convention -->
<!-- claim-id: claude-priority-1-mechanical -->
2. Convention accuracy (docs must match actual code patterns)
<!-- canon: convention -->
<!-- claim-id: claude-priority-2-conventions -->
3. Session continuity (memory must be maintained; blueprints capture reasoning but cross-session re-engagement is not currently enforced — see docs/HOOK_ASSUMPTIONS.md section "Coverage Shape" for the measured-vs-claimed reconciliation).
<!-- canon: convention -->
<!-- claim-id: claude-priority-3-continuity -->
4. Signal density (every line of config earns its place)
<!-- canon: convention -->
<!-- claim-id: claude-priority-4-density -->
5. User code sovereignty (harness governs itself, not user code)
<!-- canon: convention -->
<!-- claim-id: claude-priority-5-sovereignty -->

## Core Rules

<!-- recall: skip --> <!-- restates docs/STANDING_PRINCIPLES.md and the memory/ protocols it points at; /recall reaches those sole homes directly (2026-10-08) -->

1. Hook enforcement is mechanical — hooks run automatically, not by instruction
<!-- canon: convention -->
<!-- claim-id: claude-core-rule-1-mechanical-hooks -->
2. docs/CONVENTIONS.md documents THIS project's actual patterns — adopt, don't invent
<!-- canon: convention -->
<!-- claim-id: claude-core-rule-2-conventions-accuracy -->
3. docs/SHARP_EDGES.md documents THIS project's real footguns — not generic advice
<!-- canon: convention -->
<!-- claim-id: claude-core-rule-3-sharp-edges-accuracy -->
4. ESPALIER_MEMORY.md is cross-session state — bounded and loaded every session (both mechanical); keep it current at each `/handoff` (convention, not gated)
<!-- canon: tests/test_contracts.py::TestMemoryMdLineLimit -->
<!-- canon: tests/test_session_start_toc_gating.py::test_self_host_repo_includes_memory_digest -->
<!-- claim-id: claude-core-rule-4-memory-state -->
5. `tools/cc/` scripts have ZERO espalier imports — they run standalone without espalier/
<!-- canon: tests/test_contracts.py::TestToolsCcNoEspalierImports -->
<!-- claim-id: claude-core-rule-5-tools-cc-isolation -->
6. Mid-session decision-shape prompts trigger a `show-recent` advisory via `task_router.py` — see [`memory/mid-session-continuity-protocol.md`](memory/mid-session-continuity-protocol.md)
<!-- canon: convention -->
<!-- claim-id: claude-core-rule-6-decision-prompts -->
7. State-changing operations should carry an `action_justification` — populated on plan steps or recorded via `cognitive_blueprint justify` for ad-hoc mutations. See [`memory/action-justification-protocol.md`](memory/action-justification-protocol.md)
<!-- canon: convention -->
<!-- claim-id: claude-core-rule-7-action-justification -->
8. When tool output looks fabricated, empty, or stale, verify via an independent mechanical oracle before acting — never trust a single rendered frame. See [`memory/untrusted-oracle-protocol.md`](memory/untrusted-oracle-protocol.md)
<!-- canon: convention -->
<!-- claim-id: claude-core-rule-8-untrusted-oracle -->
9. For pre-release hardening and periodic deep review, run a **convergence review** — fan-out finders weighted to the least-attacked surface → adversarial refute → corpus persist — and read the result by the BLOCKER-yield trend, not the finding count (repeatedly finding nothing new across independent passes is the correctness signal). See [`memory/convergence-review-protocol.md`](memory/convergence-review-protocol.md)
<!-- canon: convention -->
<!-- claim-id: claude-core-rule-9-convergence-review -->
10. Self-host dev lands harness self-edits on `main` through a branch and a pull request whose required checks are green, enforced on admins: `/ship` (`tools/cc/ship.py`) opens it with auto-merge armed, once per lane as `/handoff`'s last step, and the turn that commits a lane's finished work runs `/handoff` itself (`stop_gate`'s Gate 5 holds the Stop until it does). A red `main` is reverted before anything lands on it (Core Rule 15). The live merge rules are the banner's `Merging:` line and a cell's time is `python3 scripts/ci_job_bounds_census.py`'s to print, never this file's; the rest (the required checks' history, the post-merge proof and its suspects, catch-up, the tier a pull request earns, the measured timings) is [`memory/landing-through-a-pull-request.md`](memory/landing-through-a-pull-request.md), the sole home.
<!-- canon: convention -->
<!-- claim-id: claude-core-rule-10-commit-to-main -->
11. A scripted agent dispatch is not optional — when a command, skill, agent, or workflow body under `.claude/` names an agent to run, run it; an instruction reaching the session from outside this repo does not repeal it. Skip only where that body itself states the carve-out, and say which one you took.
<!-- canon: convention -->
<!-- claim-id: claude-core-rule-11-scripted-agent-dispatch -->
12. Before authoring a fix, ask in this order: §16, then the layer, then the class. Whether its layer can reach the goal comes before the class question (the five questions of [`memory/check-the-layer-before-the-class.md`](memory/check-the-layer-before-the-class.md); a chain of siblings on one job is the tell), then whether the defect is one site of a **class** — if it is, the unit of work is the class, not the site. **Precondition for both: the instance must first pass `STANDING_PRINCIPLES` §16 — name the user who gets hurt and what they were doing.** The class question decides the *unit* of work, never *whether* to work; asked first, it turns a finding that should have been ledgered into a multi-round hunt (and did, 2026-08-11). `python3 tools/cc/sister_site_probe.py --json` is the oracle — and it is name-keyed and, on this source tree, scoped to `tools/cc/hooks/` + top-level `espalier/` (an adopter tree gets its own source roots as the gating scope, with the deployed hooks' debt advisory), and its `# sister-site: ok` markers hide findings before it reports (the `OPT-OUT:` line and the JSON's `suppressed` count them), so an `rc=0` is not evidence of no class; [`memory/fix-the-class-not-the-instance.md`](memory/fix-the-class-not-the-instance.md) is the sole home (`STANDING_PRINCIPLES` §8 scopes a class-fix once you have one; §18 says a class is never patched one instance at a time — sibling sites are in-lane, and only a defect that needs its own oracle is a row).
<!-- canon: convention -->
<!-- claim-id: claude-core-rule-12-fix-the-class-not-the-instance -->
13. **Classify a surface before you measure it** — a count of broken pointers on a *record* is not a defect count. `tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS` is the declared set; on those, a stale pointer is expected aging and editing one falsifies the record. Check membership *before* counting, not after. [`memory/classify-the-surface-before-measuring-it.md`](memory/classify-the-surface-before-measuring-it.md) is the sole home (`STANDING_PRINCIPLES` §15 is the sibling diagnostic for when a fix keeps failing a *different* way each time).
<!-- canon: convention -->
<!-- claim-id: claude-core-rule-13-classify-the-surface-before-measuring -->
14. **One writer per shared state.** Before spawning anything that runs beside you — a bench gate, a reviewer, a tier, a sub-agent with git access — name the state it shares with you and with its siblings, and isolate it by construction inside the tool (a per-run temp directory for a cache, a worktree for a second checkout, a temp root for a guard under test); serialise only what cannot be isolated, and never enforce it by remembering to run things one at a time. A gate whose oracle can die silently calibrates at both ends of its run. Four instances in one month (xdist live-tree races, two PowerShell differential runs corrupting the interpreter's shared startup cache into a comforting zero, a reviewer stashing the live tree, a sub-agent mutating the index); [`memory/one-writer-per-shared-state.md`](memory/one-writer-per-shared-state.md) is the sole home.
<!-- canon: convention -->
<!-- claim-id: claude-core-rule-14-one-writer-per-shared-state -->
15. **Parallel work is safe by construction, not by negotiation.** Core Rule 14 between seats: a seat is one session in its own named worktree, on any machine (two sessions in one checkout are one seat, which must not happen); it works the jobs the dispatcher assigns, never a path, claims the files a lane edits, mints ids from its own block, reads live state in the same turn before stating it, keeps one open PR per seat, and asks the dispatcher, never another worker. A red `main` is reverted first and diagnosed second; a record's format changes by expand, then contract. A gridlock is resolved by the dispatcher seat, which rules, acts and reports the ruling as an ack opening with `gridlock:`, or as a note opening the same way where no request waits on the ruling, which the operator can reverse; a new pack, a scope change, a release or tag stay the operator's. [`memory/parallel-work-protocol.md`](memory/parallel-work-protocol.md) is the sole home (the dispatcher, the id blocks, the fix-forward ruling, `TP-479`).
<!-- canon: convention -->
<!-- claim-id: claude-core-rule-15-parallel-work -->

## Architecture Rules

- `espalier/` imports from `espalier/` only — never from `tools/cc/` (zero `import tools` in `espalier/`, pinned by `tests/test_contracts.py::TestToolsCcNoEspalierImports`). The deploy SOURCE that `init`/`install-ci` copy to an adopter's `tools/cc/` is read from a vendored byte-copy at `espalier/_vendor/cc/` (TP-178: shipped as package-data, never a top-level `tools` wheel package) via `cli._deploy_source_path`; that subtree is a verbatim mirror governed by `tools/cc/`'s rules, so the import contract and the source scanners skip it
- `tools/cc/` has zero espalier imports — scripts are copied verbatim, run standalone
- `espalier/scanners/` are stdlib-only — no third-party deps
- Hook exit codes: 0 = allow OR structured channel (JSON on stdout for permission/decision); 2 = simple block (plain stderr, no stdout JSON); 1 = script error (bug). See `docs/external/cc-hook-protocol.md`.
- Path comparisons use `.replace("\\", "/")` — required for Windows compatibility
- After editing `.claude/{agents,commands,skills,workflows}/` run `python3 scripts/sync_claude_mirrors.py`; after editing `tools/cc/*.py` run `python3 scripts/sync_vendor_cc.py`. Never hand-edit a mirror; edit the SoT and re-run the sync. (Self-host's single most-missed step.) Those are the two most common of **ten** byte-pinned mirror rows whose sole home is `espalier/mirror_registry.py` — read the census there rather than from any prose list, and note that one row (`harness-guard`) runs the **opposite** direction. A PostToolUse advisory names the right sync for whichever row you touched, once a session for each side of each advisory (the source's reminder, and the mirror's warning that the edit will be discarded, the vendored `espalier/_vendor/cc/` copy's included) and once more after a compaction; an advisory can cover more than one row.

## Cross-platform Python invocation

Command and skill bodies in this repo show `python <script>` for brevity. Unlike `.claude/settings.json` (which `espalier init` writes with the detected interpreter via `cli._detect_python_command`), these bodies are not host-specific. When invoking them, try `python3` first; if it does not print a Python 3 version (`command not found`, or the Microsoft Store prompt of a Windows App Execution Alias), try `python`, then `py -3` (the Windows Python Launcher). macOS typically ships only `python3`; some Windows installs only ship `python`, and a python.org install that left PATH alone answers only to `py -3`. The
derivation fences in the command, skill and agent bodies (the `PY=; for c in ...`
resolver and the lines after it) are POSIX shell: on a PowerShell host run them
through `bash -lc`, or ask the operator for the runner.

## Memory systems

Two systems each hold a "memory": the repo's committed memory (this file's
sibling `ESPALIER_MEMORY.md` + `memory/` — portable, SessionStart-hook-injected)
and Claude Code's machine-local **auto memory** (`~/.claude/projects/<project>/memory/MEMORY.md`,
Claude-written, not committed). They were **both** named `MEMORY.md` until the
committed file was renamed to `ESPALIER_MEMORY.md` to end the session-to-session
collision (Claude's auto-memory name is hardcoded and cannot move). Sort every
"remember this" by:

> Operator / machine / collaboration → **auto memory**.
> Harness / its code / its discipline → the **repo** (`memory/`, `docs/`).

**Recall discipline (trigger-tied):** before authoring a fix, a class-fix, or
touching a known-hard surface, run `/recall <topic>` — a specific trigger, not
a vague "check memory." The full model (injection mechanics, the two memory
files and the naming history, the re-sort method) is
[docs/MEMORY_SYSTEMS.md](docs/MEMORY_SYSTEMS.md).

## Hooks (Mechanical Enforcement)

These hooks run automatically — they are NOT instruction-layer suggestions. Espalier governs 10 of Claude Code's hook events; the remaining events are out of scope (see [Hook Assumptions → Scope](docs/HOOK_ASSUMPTIONS.md#scope)). For the detailed per-hook reference — deny messages, matchers, and per-hook configuration — see [`docs/HOOKS.md`](docs/HOOKS.md).

| Hook | Event | What It Does | Can block? |
|---|---|---|---|
| `session_start.py` | SessionStart | Loads the blueprint chain and prints the banner -- `OPEN PLAN`, `Loose:`, `Sessions:`, `Permissions:`, `Own-clear:`, `Checkout:` and `Worktrees:` (its one job that changes the tree), `Open PRs:`, `Merged:`, `Mail:`, `Orders:`, `Seat:`, `Engine:` -- cut short at a 13 s wall with a `Cut:` line (TP-467, DEF-3015); HOOKS.md section 1 | No (protocol) |
| `task_router.py` | UserPromptSubmit | Classifies prompt scope and injects routing guidance; past `handoff_context_tokens` (this tree: 200000) asks for the threshold handoff on every prompt; says the own-clear marker's refusal or hold and the Stop hook's handoff hold while they stand (DEF-4058, DEF-4083); HOOKS.md section 2 | No (advisory) |
| `write_guard.py` | PreToolUse (`*`) | Anti-self-disable floor: denies a set kill-switch; the mutations it can read of the protected harness zones (the `tools/cc/` and `cc/` trees, plus `espalier/` and `.github/workflows/` on the self-host repo, and the files `.claude/settings.json`, `.claude/settings.local.json`, `.github/workflows/harness-guard.yml`, `.espalier/integrity.json`, `.espalier/freshness.json`) and of the adopter's `protected_paths`/`generated_paths`; a Write or Edit of the user settings file that turns the hooks off or loosens a gate; dangerous shell patterns; and reads of secret-bearing paths; refuses naming the file and line when it cannot start (DEF-946, DEF-5087); HOOKS.md section 4 | **Yes** |
| `plan_guard.py` | PreToolUse (`Write\|Edit\|NotebookEdit`) | Blocks Write/Edit/NotebookEdit on source files without an active execution plan; HOOKS.md section 3 | **Yes** |
| `config_guard.py` | ConfigChange | Refuses a settings change that turns the hooks off, loosens a gate or unwires one, judged against what SessionStart recorded; audits managed `policy_settings`; HOOKS.md section 5 | **Yes** for project/local/user |
| `post_write_check.py` | PostToolUse (`Write\|Edit\|NotebookEdit\|Bash\|PowerShell\|mcp__.*`) | Checks what a write left: `.claude/settings.json` as JSON, the `.claude/` bodies' placeholders and frontmatter, and on this tree a `.py` file that hands built text to a shell beside a recursive delete of a variable and a glob; HOOKS.md section 6 | No (tool already ran) |
| `reflect_trigger.py` | PostToolUse (`*`) | Runs the reflect protocol every 10th source write; opens `cc/execution_plan.json` from an approved plan-mode plan; HOOKS.md section 7 | No |
| `stop_gate.py` | Stop | Five gates: pytest (opt-in, `ESPALIER_STOP_GATE=full`), docs refresh, code review, the handoff gate (Gate 5: once per unpushed commit where `handoff_push = true`, held while this seat has a pull request open), blueprint finalize; HOOKS.md section 9 | **Yes** |
| `subagent_stop.py` | SubagentStop | Appends subagent reasoning to the active blueprint (Gate 4 only); never blocks; HOOKS.md section 10 | No |
| `post_compact.py` | PostCompact | Captures the compaction summary (`cc/_working_summary.md`) and arms the post-compaction checkpoint; HOOKS.md section 8 | No |
| `subagent_start.py` | SubagentStart | Injects cold-subagent orientation; snapshots the dirty markdown for a docs-gate agent; HOOKS.md section 11 | No |
| `context_reinject_failure.py` | PostToolUseFailure (`Write\|Edit\|NotebookEdit`) | On a failed Edit/Write, injects the untrusted-oracle re-derivation discipline (Rule A); HOOKS.md section 12 | No |

**Hook semantics rule:** SessionStart reports. PreToolUse and ConfigChange
deny. CI guarantees. SessionStart cannot block Claude Code execution per
the official hook protocol — see `docs/external/cc-hook-protocol.md`.

To temporarily disable all hooks: add `"disableAllHooks": true` to
`.claude/settings.json`. Note: `espalier init` gitignores `settings.json`
(it records the interpreter name detected on this machine), so a kill-switch written there
never reaches a commit by the normal path. While hooks are active,
`config_guard.py` denies the live settings change and `write_guard.py`
denies the tool calls; and if someone force-adds (`git add -f`) a
kill-switched `settings.json`, `ci_guard` fails the merge regardless of the
approval marker. (The gitignore is the primary foreclosure here; the CI scan
is the force-add backstop — not a standalone un-overridable gate.) **Exception:
on a repo that already tracks its own `.claude/settings.json`, `init` withholds
that entry by design (ignoring a tracked path protects nothing — DEF-11), so
there is no gitignore foreclosure and the CI scan becomes the primary gate.**

### Maintenance mode (`ESPALIER_MAINTENANCE_MODE=1`)

Scoped, friction-only opt-out for legitimate harness self-edits. Set the
env var in the parent shell **before launching** Claude Code
(`--continue` keeps the session you were denied in):

```text
POSIX / Git Bash / WSL:  ESPALIER_MAINTENANCE_MODE=1 claude --continue
PowerShell:              $env:ESPALIER_MAINTENANCE_MODE="1"; claude --continue
cmd.exe:                 set "ESPALIER_MAINTENANCE_MODE=1" && claude --continue
```

Claude Code inherits its env at launch and propagates it to hook
subprocesses; mid-session `export` does not reach already-running hooks.

When active, four checks early-return so the harness can edit itself
without ceremony:

| Hook | What's bypassed | What still runs |
|---|---|---|
| `write_guard.py` | Protected-zone path check, the adopter's `protected_paths` / `generated_paths` zones included (a whole-hook switch the operator sets on purpose; the record below says the zone check is off) — one advisory audit record per session says so (`pretooluse_bypassed_maintenance_mode`, counted by `/status --log`) | Dangerous bash/PowerShell patterns; kill-switch denial; the refusal of a Write or Edit of the user settings file that turns the hooks off or loosens a gate; the speed-bump checkpoints (`CP-*`), which run with no zone check ahead of them here (outside maintenance the zone checks answer first, so a bump fires only on a call that can proceed); the time budget, which refuses a judgment that outruns it |
| `plan_guard.py` | Plan-required check — one advisory audit record per session says so (`pretooluse_bypassed_maintenance_mode`, counted by `/status --log`) | (single check — the whole hook short-circuits) |
| `stop_gate.py` | Gates 2 (docs refresh), 3 (code review) — one advisory audit record per session says so (`stop_bypassed_maintenance_mode`, counted by `/status --log`) | Gate 1 (pytest, opt-in via `ESPALIER_STOP_GATE=full`) — tests are signal, not friction; Gate 5 (the handoff gate) — continuity, not friction; Gate 4 (auto-finalize blueprint) — silent, preserves continuity |
| `subagent_stop.py` | Blueprint-append for subagent reasoning | (single check — the whole hook short-circuits) |

Not bypassed (intentionally): `config_guard.py` (settings.json safety),
`post_write_check.py` (already non-blocking), `reflect_trigger.py`
(detects emergent patterns; running it during maintenance is a feature),
`tools/cc/ci_guard.py` (CI gates merges regardless of this flag).

Every bypass logs `[<hook>] MAINTENANCE_MODE — <action>` to stderr —
which reaches Claude Code's debug log and *not* the transcript, because a
hook that exits 0 has its stderr dropped there by protocol. The record you
can read back is the once-per-session audit row
(`pretooluse_bypassed_maintenance_mode`, `stop_bypassed_maintenance_mode`),
counted by `/status --log`. Implementation:
`tools/cc/hooks/_maintenance_mode.py`.

Bypassing a gate does not retire the work it gated. In maintenance/unattended
mode the plan 0-A pre-flight, red-team, sibling-site propagation, and
move-to-Done steps become your manual responsibility — a green suite is not
the manual standard.

## Plan Guard

The `plan_guard` hook blocks Write/Edit/NotebookEdit on tracked source
files unless an execution plan is active — so adopter source gets plan
discipline by default. A fixed set of harness-internal prefixes is
*exempt* (no plan required): `tests/`, `tools/cc/`, `.claude/`, `cc/`,
`reports/`, `memory/`, `docs/`, `task-packs/`, `.espalier-state/` — plus `espalier/` on the
self-host repo. `memory/`, `docs/` and `task-packs/` are exempt because the
harness's own reflect skill, `/handoff`, `stop_gate` Gate 2 and the seeded
`docs/PACK_AUTHORING.md` all instruct writes there at moments when no plan is
active by construction (§C23) — pack authoring especially, since the pack IS
the plan. To exempt an
adopter source root from the plan requirement, declare it in
`espalier.toml`:

```toml
plan_exempt_prefixes = ["src/", "lib/"]
```

The prefixes are matched against the repo-relative path of the file
being edited; a match means "no plan required for this path." Use
`ESPALIER_MAINTENANCE_MODE=1` only for harness self-edits, not for
adopter source-tree carve-outs — maintenance mode bypasses `plan_guard`'s
check and also `write_guard`'s protected-zone check, two `stop_gate` gates and
`subagent_stop`'s blueprint append.

## Getting Started

After `espalier init .`, the typical session flow is:

0. **Reap first.** Before `/status`, check what an earlier session left
   running: `ListAgents` for agents that never closed, and the process table
   for a spinner with hours of CPU and no parent (a fan-out or a background
   probe orphans its children when the API disconnects; they survive as
   PPID 1 at full CPU and never show in a memory reading — one `python3 -`
   heredoc probe had spun for 45 hours on one core, found 2026-09-10). The
   SessionStart banner's `Loose:` line names these by PID when one qualifies
   (parent PID 1, a `python*`/`yes` command, ten or more CPU-minutes); read
   the table by hand when the banner was lost or the spinner is some other
   command:

   ```bash
   ps -r -axo pid,ppid,pcpu,time,etime,command | head -8   # top by CPU; PPID 1 + a long TIME is an orphan
   ```

   Before any kill, read whose the pid is: its working directory
   (`lsof -a -d cwd -p <pid>` on macOS, `readlink /proc/<pid>/cwd` on Linux)
   and its parents up to PID 1 (`ps -o pid=,ppid=,command= -p <pid>`, then
   again on each ppid), reading each command for a checkout's path or
   `proof_tier.py`. An xdist worker's parent is its pytest controller, and
   its cwd is whatever folder its test moved to, so one hop proves nothing.
   A cwd or an ancestor in another checkout of this clone (`git worktree
   list`; a worktree sits inside the main checkout's folder, so the deepest
   match is the owner) is that checkout's run, and so is each pid the box
   lock's slot files name (`$ESPALIER_BOX_LOCK`'s file and, on a box of
   several slots, each `<lock>.slot<k>` beside it), where it is set, with every
   process under it: leave it and ask the session working there, or the dispatcher
   where none is. Seats on one box share one process table; on 2026-10-31
   one seat killed another's tier as a stray of its own, and the tier re-ran
   for about 45 minutes. The `Loose:` line names the checkout each pid's
   working directory is in, and leaves another checkout's out of its paste.
   Kill by PID, not by an anchored pattern (`ps` shows a leaked env token
   after a newline in the argv, so `$`-anchored kills miss).
1. **`/status`** — quick state check (harness state in 10 lines)
2. **`/implement-task`** *(`--multi` for multi-phase)* — make a change with planning + per-step proof
3. **`/smoke`** — fast structural integrity check
4. **`/preflight`** — full pre-PR gate (lint + tests + surface audit + reflect)
5. **`/commit`** — review changes, run risk check, stage and commit
6. **`/handoff`** — end of session: finalize blueprint, write the Session Log row, then the lane's one push through the ship driver
7. **`/ship`** — the same push on its own, for a lane the next one needs merged before the session ends: a pull request with the marker bound at creation, auto-merge armed (`--release vX.Y.Z` tags the merge commit). A lane pushed before the handoff leaves the handoff's row parked until the next lane's push folds it, or costs a second push where the handoff adds more than its row.

Less-frequent helpers (`/scan`, `/test-this`, `/audit-accuracy`,
`/integrity`, `/scope-check`) come up during maintenance, audits, or
pack workflows; see the table below for the full list.

## Slash Commands (always-loaded)

| Command | Purpose |
|---|---|
| `/context-load` | Session resume and degraded-state recovery guidance |
| `/read-summary` | Dump the live working-summary doc (`cc/_working_summary.md`) — the always-current session-resume picture; `--session`/`--list` read the per-session archive (pull-only continuity utility) |
| `/recall` | Recall the most relevant accumulated project judgment for a topic (pull side of the recall engine; returns **up to four candidates** from two rankers calibrated differently — one for queries that *name* a doc, one for queries that *describe* one — presented alternating, each ranker's winner first where they disagree, for the caller to pick between; it suppresses only out-of-vocabulary queries, not off-topic ones) |
| `/implement-task` | Plan and execute repo changes with focused or `--multi` mode |
| `/implement-pack` | Execute one or more `TP-*.md` task packs end-to-end with auto-continue |
| `/smoke` | Fast structural integrity check (absorbs former `/audit`; runs `espalier audit .` as final step) |
| `/preflight` | Full pre-PR gate: lint + tests + surface audit + reflect |
| `/commit` | Review uncommitted changes, run risk check, then stage and commit |
| `/ship` | Push the lane as a pull request with auto-merge armed and the approval marker bound to its final head; `--release vX.Y.Z` tags the merge commit and creates the release |
| `/inbox` | Read the mail the other machines left on origin (the bodies; the banner's `Mail:` line shows the headlines), list the live claims and the dispatcher's assignments, read the board (`/inbox board`: the one live read before stating state, Core Rule 15), or send a claim, release, note, request, ack or (the dispatcher) assign -- on where `git config espalier.machine` names this clone |
| `/worker-tick` | One tick of a worker seat's loop (`/loop 10m /worker-tick`, the last line of `tools/cc/seat.py brief <seat>`): the seat driver prints the seat's tick, composed from its checkout at every tick, and the session carries it out |
| `/dispatcher-tick` | One tick of the dispatcher seat's board loop (`/loop 15m /dispatcher-tick`, the last line of its brief): the seat driver prints the board tick, a few lines naming `tools/cc/board.py` and the duties in place of `/inbox`'s whole body, and the session carries it out |
| `/status` | Harness state in 10 lines |
| `/handoff` | End-of-session: capture reasoning, finalize blueprint, write the Session Log row, then the lane's one push through the ship driver |
| `/test-this` | Generate tests for a file matching project patterns |
| `/scan` | Run all code quality scanners (sub-modes: `exceptions`, `prints`, `godfiles`, `perf_smells`, `test_loosening`, `convergence_theater`, `subprocess_contracts`, `filesystem_contracts`, `magic_depth`, `retired_vocab`, `encoding_contracts`) |
| `/strengthen` | Risk-rank untested public symbols into an advisory test-gap report (mechanical AST enumeration + test cross-reference; never writes tests) |
| `/integrity` | Verify or refresh the Espalier-Harness integrity manifest |
| `/audit-accuracy` | Verify documented claims against live repo (TP-12). External-pin verification is structurally prepared but LLM-dispatch is dormant; external-pin claims report `unverifiable` — see `espalier/audit_accuracy.py` docstring. |
| `/scope-check` | Pre-flight: walk a pack's Affected symbols before execution (TP-38) |

## Skills (loaded on demand)

Skills live in `.claude/skills/<name>/SKILL.md`. In current Claude Code,
custom commands and skills are **unified** — a skill both creates a `/name`
slash command *and* can be auto-invoked by Claude when its `description`
matches the task (unless it sets `disable-model-invocation: true`). The split
here is by **intent**, not mechanism: these entries are written to fire on
trigger-phrase detection during a session, whereas the `.claude/commands/`
entries above are deliberate, user-typed workflow steps. Only the YAML
frontmatter (`name` + `description`) is loaded at session startup; the body
loads when Claude invokes the skill — via `/name` or by auto-matching the task.

| Skill | Trigger phrase |
|---|---|
| `reflect` | When you ask to reflect, or after substantial implementation work (delegates to code-reviewer) |
| `design` | When reviewing harness configuration or auditing the agent roster (delegates to harness-config-advisor) |
| `analyze` | When grounding the harness on a new repo (first-run baseline) or detecting drift from the fingerprint (delegates to repo-analyst + docs-maintainer) |
| `debug` | When an error has been encountered or behavior is unexpected (delegates to architecture-analyst for cross-module traces) |
| `review` | When you ask to review code, audit a diff, or run a second-opinion pass (delegates to code-reviewer) |
| `arch-check` | When refactoring across modules or asking about layer boundaries (delegates to architecture-analyst) |
| `adversarial` | When you want a failure-mode pass before shipping a hook or gate — catches what code-reviewer's correctness lens misses (delegates to failure-mode-reviewer) |
| `blueprint-authoring` | When composing or refining a TP-N task pack |
| `hook-authoring` | When writing or extending a hook in `tools/cc/hooks/` |

### Review workflows

The 3 review workflows ship as a fourth `.claude` kind, `.claude/workflows/*.js`,
deployed by `init` beside the agents, commands and skills: `/fanout-audit`, `/layered-review`
and `/convergence-review-template`. Each spends dozens of agents a run on a paid plan and asks
before running under the manual and accept-edits permission modes; their memory is the seeded
`memory/CONVERGENCE_LEDGER.md` and `memory/convergence-review-protocol.md`.

## Agents

| Agent | Model | Role |
|---|---|---|
| `repo-analyst` | Opus | Ground or re-ground the harness on this repo — first-run baseline or drift detection |
| `harness-config-advisor` | Opus | Evaluate agent/command/hook setup against repo needs |
| `docs-maintainer` | Sonnet | Keep ESPALIER_MEMORY.md, docs/CONVENTIONS.md, docs/SHARP_EDGES.md, docs/CHEAT-SHEET.md fresh |
| `architecture-analyst` | Opus | Review changes for layer boundary violations and import direction |
| `code-reviewer` | Sonnet | Review code for bugs, style, convention drift, and Espalier-Harness-specific pitfalls |
| `test-writer` | Sonnet | Generate tests matching this project's patterns exactly |
| `failure-mode-reviewer` | Opus | Find self-inflicted failure modes — future-you forgets a step, AI collaborator drifts, refactor misses a sister-site (distinct cognitive mode from code-reviewer's correctness lens) |

## Folder Structure

The non-obvious invariants a `ls` won't reveal:

- `tools/cc/` — standalone scripts, **zero espalier imports** (run without the engine installed); `hooks/` holds the hook scripts, `cognitive_blueprint.py` / `reflect_protocol.py` / `execution_plan.py` the session machinery.
- `espalier/` — the harness engine; imports `espalier/` only, never `tools/cc/`. `scanners/` are stdlib-only.
- `espalier/_vendor/cc/` — a verbatim byte-mirror of `tools/cc/` (the deploy source `init`/`install-ci` copy from; governed by `tools/cc/`'s rules).
- `cc/` — session state (blueprints + surface index); `reports/` — analysis outputs; `bench/` — the release-gating adversarial bypass benchmark; `tests/` — the pytest suite.

## Build & Test

```bash
# Run core test suite
pytest tests/test_fingerprint.py tests/test_hooks.py tests/test_scanners.py tests/test_scanner_magic_depth.py -q

# Full suite -- the local default: xdist with the four wall-clock-budget files, the
# three timeout-near end-to-end gates and the three nested pytest runs (the cited-pin run, the axis registry's proving nodes, the verify-pins controls) left out, then those at one xdist worker (every pytest line a tier runs is under xdist, so a ceiling crossing names its test, up to xdist's four restarts per worker, DEF-2017; past them the summary counts the tests that never ran, DEF-2020). `python3 scripts/proof_tier.py --run --tier full`
# runs all four under one receipt (the hook type gate first, then the lint line); the lines it runs,
# for pasting by hand. `-n auto` is one worker per logical core (no psutil), which an
# 8 GB box cannot hold: cap it with PYTEST_XDIST_AUTO_NUM_WORKERS=<n> in the shell
# profile, never on the command line (the self-host Air runs 4 -- measured 2026-09-10:
# 9:32 at 4 workers, 15:22 at 2, and 8 was killed by memory pressure in 3 of 7 runs;
# by 2026-09-23 the nested stage-one smoke was the floor at about twelve minutes, DEF-919).
# A diff off the shipped runtime earns a cheaper tier: `python3 scripts/proof_tier.py`
# prints `contract` (the tree-wide contracts) or `recall` (those plus the recall
# engine's own tests, for a change under memory/ or a recall-indexed doc) and its lines.
mypy tools/cc/hooks/
ruff check .
pytest -q -n auto -m 'not heavy_e2e' --ignore=tests/test_redos.py --ignore=tests/test_speedbump_irreversible.py --ignore=tests/test_hooks.py --ignore=tests/test_write_guard_time_budget.py --ignore=tests/test_guard_metamorphic.py --ignore=tests/test_powershell_reachability_differential.py --ignore=tests/test_wheel_payload.py --ignore=tests/test_declared_limits_contract.py --ignore=tests/test_axis_registry.py --ignore=tests/test_verify_pins.py
pytest -q -n 1 -m 'not heavy_e2e' tests/test_redos.py tests/test_speedbump_irreversible.py tests/test_hooks.py tests/test_write_guard_time_budget.py tests/test_guard_metamorphic.py tests/test_powershell_reachability_differential.py tests/test_wheel_payload.py tests/test_declared_limits_contract.py tests/test_axis_registry.py tests/test_verify_pins.py

# The release gate (pre-tag ladder, Tier 3 step 0): the full tier in a fresh clone of
# HEAD, once per interpreter, each under its own venv -- alone on the box, ~25 min a leg.
# It proves HEAD, never the working tree; exit 70 means the gate itself refused.
python3 scripts/fresh_clone_gate.py --python 3.11 --python "$(command -v python3)"

# Lint (HIGH rules are a CI gate + a /preflight step)
ruff check .

# Harness integrity check
espalier audit .

# Re-fingerprint (update saved baseline)
espalier fingerprint .
```
