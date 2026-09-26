# Espalier-Harness Surface Support Matrix

Last updated: 2026-09-25

This matrix declares what Claude Code surfaces espalier governs, what it
documents, what it defers, and what it considers out of scope. The matrix
is normative: public docs must not claim coverage of any surface marked
`deferred` or `unsupported`.

## Status vocabulary

Five values. Closed vocabulary — `tests/test_surface_support_matrix.py`
fails on any status outside this set.

- **guarded**: espalier actively enforces this surface via hooks,
  settings, or runtime checks. The surface has a tested behavior
  contract.
- **supported**: espalier reads, interacts with, or ships content for
  this surface but does not enforce constraints on third-party usage
  (e.g., bundled skills are audited not to use inline `!` shell
  preprocessing, but user-added skills are not vetted).
- **documented-only**: espalier acknowledges this surface in docs but
  provides no implementation. Operators can wire their own hooks.
- **deferred**: known future work. Deliberately not implemented yet. Will be
  considered for a future release if user demand surfaces.
- **unsupported**: outside espalier's scope. Operators must handle via
  other tooling.

## Release guarantee

- **yes**: the surface has a documented behavior contract that espalier
  maintains across patches.
- **partial**: some aspects are guaranteed, others are best-effort or
  version-specific. Notes column explains.
- **no**: no espalier-side guarantee. Operators rely on Claude Code
  upstream behavior.

## Matrix

| Surface | Status | Guarding mechanism | Release guarantee | Notes |
|---|---|---|---|---|
| Main session Write/Edit/NotebookEdit | guarded | PreToolUse + plan_guard + write_guard | yes | Requires active execution plan via `/implement-task`; protected zones — the `tools/cc/` and `cc/` trees (plus `espalier/` and `.github/workflows/` on the self-host repo) and the exact files `.claude/settings.json`, `.claude/settings.local.json`, `.github/workflows/harness-guard.yml`, `.espalier/integrity.json`, `.espalier/freshness.json` — hard-blocked unless `ESPALIER_MAINTENANCE_MODE=1` |
| Main session Bash | guarded | PreToolUse + write_guard (protected-zone mutations, dangerous tier, secret-read leg) | partial | Profile-specific allow list (minimal/workflow/full); a write into, a delete of or a move out of a protected zone is denied from the operands the guard can read; the dangerous tier intercepts a catastrophic delete such as `rm -rf /`, `curl <pipe> sh` (pipe-to-shell) and kill-switch commits; a read of a secret-bearing path is denied |
| Main session PowerShell (Windows) | guarded | PreToolUse + write_guard PowerShell legs (protected-zone mutations, dangerous tier, secret-read leg); PostToolUse post_write_check | partial | The PowerShell tool is separate from Bash in Claude Code, so `Bash(...)` permission rules do not apply to it; on a Windows host `init` writes a `PowerShell(...)` twin of every `Bash(...)` allow rule, and `doctor` names the twins an older file lacks. It must be on for the legs to see a call (`CLAUDE_CODE_USE_POWERSHELL_TOOL=1` at launch where an account does not have it by default); until then PowerShell dispatches do not exist, so the legs are idle, not bypassed. The two POSIX fetch-pipe deny literals are not twinned by design (the class is the `CP-FETCHEXEC` speed-bump on both shells). Driven on a Windows 11 host (walks 2 and 3, 2026-09) and on the `windows-latest` CI leg; the `PowerShell(...)` allow twins are rendered and tested but not yet witnessed in a live Windows session, and the statusline shim under PowerShell without Git Bash is unwitnessed. |
| Skills (built-in) | supported | bundled content audited; no inline `!` preprocessing | partial | Espalier-shipped skills are reviewed for shell-preprocessing safety. No Claude Code setting disables skill shell execution — see SHARP_EDGES `disableSkillShellExecution`. `allowed-tools` is pre-approval, not a sandbox. |
| Skills (user-added) | unsupported | n/a | no | User-installed skills run with their declared tools; espalier does not vet content or `allowed-tools` |
| Slash commands | supported | bundled commands shipped via `espalier init`; no runtime enforcement | partial | Espalier ships `/implement-task`, `/preflight`, `/commit`, etc. User-added commands not vetted |
| Subagents (built-in) | guarded | frontmatter capability tier + `test_agent_frontmatter_contract.py` | yes | Read-only reviewers (code-reviewer, architecture-analyst, repo-analyst, harness-config-advisor) pinned no-Write; docs-maintainer and test-writer pinned tier-appropriate Write |
| Subagents (user-added) | unsupported | n/a | no | User-installed agents declare their own tools; espalier does not vet |
| Agent teams | deferred | docs only | no | Experimental Claude Code surface; espalier does not implement v0.6.x |
| Worktrees / forks | deferred | docs only | no | `espalier worktree-plan` exists for plan generation; worktree-creation governance is v0.7 work |
| MCP tools (external) | documented-only | PreToolUse `*` matcher catches mcp__ tool calls in `full` profile | partial | MCP servers are a trust boundary; espalier does not vet servers, prompts, or elicitation responses |
| MCP elicitation | unsupported | n/a | no | External-server prompt surface; espalier does not intercept |
| Settings changes | guarded | ConfigChange + config_guard | yes | Blocks unsafe project/local/user settings (`disableAllHooks`, `bypassPermissions` defaults); managed `policy_settings` are audit-only and non-blocking |
| Compaction | guarded | PostCompact + post_compact.py | partial | PostCompact wired (re-injects critical context). PreCompact is documented-only — Claude Code surface exists but espalier does not register a hook |
| ExitPlanMode bridge | deferred | docs only | no | Claude Code's `ExitPlanMode` tool finalizes plan-mode output. `write_guard`'s `*` matcher technically receives `ExitPlanMode` tool calls but applies no plan-gating; `plan_guard` (whose matcher is limited to `Write`, `Edit`, and `NotebookEdit`) does NOT observe `ExitPlanMode`. Either way, espalier does NOT auto-open an execution plan from the plan-mode output. Auto-bridging is deferred. Operators wanting the bridge can write a custom hook that consumes the plan-mode output and writes `cc/execution_plan.json` |
| File watcher (FileChanged) | documented-only | docs only | no | Espalier does not register FileChanged hooks |
| Cwd changes (CwdChanged) | documented-only | docs only | no | Espalier does not register CwdChanged hooks |
| Hook failures | supported | fail-closed parse-error handling; pinned by `tests/test_hook_protocol.py` | partial | Espalier-shipped hooks fail-closed on parse errors and obey the channel-XOR exit-code rule; user-added hooks are operator's responsibility |
| Notification surface | unsupported | n/a | no | Notification routing is Claude Code internal |
| Plugin marketplace | unsupported | n/a | no | Espalier removed plugin manifest support in v0.6.x (see CHANGELOG) |

## What's not in this matrix

Surfaces too internal to Claude Code to make sense to govern:

- Permission mode (`default`, `auto`, `acceptEdits`, `plan`,
  `bypassPermissions`) — settable by user; espalier does not intercept
  the choice itself but `config_guard` can detect committed
  `bypassPermissions` defaults via the kill-switch check.
- Effort level (`low`/`medium`/`high`/`max`) — Claude Code internal.
- Background async hooks — espalier's hooks are synchronous.

## How this matrix changes

Adding a surface or moving an existing surface between categories
requires:

1. Updating this file with the new row or category.
2. Updating any tests that assert the matrix shape (see
   `tests/test_surface_support_matrix.py`).
3. Updating public docs (README, QUICKSTART, etc.) if the change
   affects a public claim.
4. A `ESPALIER_MEMORY.md` Harness Decisions entry explaining the change.

The matrix is the contract. New audit findings either reveal a row
needs to change category, or reveal a new surface that needs adding.

## Anti-overclaiming rule

Public docs (README, QUICKSTART, CHEAT-SHEET) must not assert coverage
of any surface marked `deferred` or `unsupported`. The test
`tests/test_surface_support_matrix.py::TestPublicDocsNoOverclaim`
enforces this.

Acceptable language for unsupported/deferred surfaces:

- "Espalier does not govern <surface>; <reason>"
- "<Surface> is on the v0.7 roadmap"
- "Operators wanting <surface> governance can wire their own hooks"

Unacceptable language:

- "Espalier governs all Claude Code surfaces" (overclaim)
- "Espalier protects against <X>" where X is unsupported
- "Comprehensive Claude Code governance" without qualification
