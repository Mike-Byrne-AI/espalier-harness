### Fixed

- **A directory that ignores itself is generated, and the post-shell
  protected-file check no longer reports what a tool writes into it.** A
  directory whose own `.gitignore` is one bare `*` -- the form pytest, ruff,
  mypy, uv, `venv` since Python 3.13 and Claude Code's plugin loader write
  into what they generate -- is pruned wherever it sits below a watched
  directory's top (a harness zone or an adopter's `protected_paths`), in the
  hook's walk, in its file-tool refresh and in the engine's writer records
  alike. The case that filed it: Claude Code rewrites the type declarations
  under `tools/cc/mods/<mod>/.claude-plugin/types/` at a launch, and the check
  reported them as protected files changed between calls that no session had
  edited (10 of the 14 records on the two Mac checkouts since 2026-10-27, eight
  of them that rewrite alone). The top itself is never read that way, a
  `.gitignore` holding anything else is a rule set that prunes nothing, and a
  declaration that lands during a session over files the session already
  watches retires none of them: it is reported as the added file it is, and a
  later change to those files still reports. The `tsconfig.json` beside the
  mod, written once at its first load in a checkout, still reports that once.
