### Fixed

- **A protected directory that ignores itself before the session starts stays
  watched over the files git tracks in it.** The zone check after each shell
  call prunes a directory whose own `.gitignore` is one bare `*` (what pytest,
  ruff, mypy, uv, `venv` and Claude Code's plugin loader write into what they
  generate), and already kept watching one that appeared mid-session over
  files it held. One already there when the session started was still pruned
  with every file in it, tracked ones included, so an edit to those files was
  never reported for the whole session. The session's first snapshot now asks
  git's index once, only when it meets such a directory, and walks one that
  holds a tracked file; the recorder that `espalier upgrade` and the other
  writers bracket themselves with walks the same set, so their changes there
  are accounted for. A tree with no git of its own, or a git that cannot
  answer, prunes as before. A file written by a file tool under a directory
  that stays watched this way is refreshed too, rather than reported as an
  unaccounted addition at the next shell call. (`DEF-4073`)
