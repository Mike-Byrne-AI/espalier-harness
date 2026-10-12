### Fixed

- **A lane shipped or a plan opened from a checkout with no wired hooks says
  so.** Every `tools/cc/ship.py` verb that pushes (`open`, `handoff`, `rebind`,
  `catch-up`; once per run) and `tools/cc/execution_plan.py create` print one
  line when the checkout they run in has no `.claude/settings.json` (a linked
  worktree checks out tracked files only, and the file is gitignored; the line
  names the main checkout's file to copy, read off the worktree's gitdir line,
  since `.worktreeinclude` reaches only the worktrees Claude Code creates),
  when the file cannot be read as JSON or holds no JSON object, when its hooks
  block is malformed (Claude Code then loads no hooks from it at all), or when
  it leaves a deployed blocking gate unwired, named; the unwired lines name
  `espalier merge-settings --repair`, the remedy SessionStart's own warning
  names. One reader, `hooks/_integrity.py::checkout_wiring_notice`, which sets
  `http` and `mcp_tool` hook entries aside as the live readers do, loaded by
  path through `tools/cc/_paths.py::hooks_module`, which stands down when the
  hooks directory is not beside the tool. A note, never a refusal: the push and
  the plan go ahead as before. Until now a session launched in such a worktree
  ran with every guard off and nothing in the push named it (measured
  2026-10-08 on two background sessions; `DEF-1192`).
