### Fixed

- **The post-shell protected-file check no longer reports what Claude Code
  generates beside a mod.** Claude Code rewrites the type declarations under
  `tools/cc/mods/<mod>/.claude-plugin/types/` at a launch, and the check
  reported them as protected files changed between calls that no session had
  edited (10 of the 12 records on the two Mac checkouts since 2026-10-27, eight
  of them that rewrite alone). A directory whose own `.gitignore` is one bare
  `*` -- the form pytest, ruff, mypy, uv, `venv` and Claude Code's plugin
  loader write into what they generate -- now reads as generated and is pruned
  wherever it sits below a watched directory's top, in the hook's walk, in its
  file-tool refresh and in the engine's writer records alike. The top itself
  is never read that way, a `.gitignore` holding anything else is a rule set
  that prunes nothing, and a bare `*` dropped into a watched directory
  mid-session reports every file there as removed. The `tsconfig.json` beside
  the mod, written once at its first load in a checkout, still reports that
  once.
