### Fixed

- **A pull inside a nested checkout under a protected path no longer reads as
  an unaccounted change.** The check after each shell call asks a clone,
  submodule or worktree under an adopter's `protected_paths` for its own
  committed content, so a `git pull`, checkout or submodule update inside it is
  accounted for the way the outer repository's own git moves are, and a git
  operation half done inside it holds the check until git is done. New content
  beside such a pull still reports, as does an edit in a nested repository with
  no commits. The harness's own zones are never asked of a nested git.
