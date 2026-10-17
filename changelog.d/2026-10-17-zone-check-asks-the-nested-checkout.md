### Fixed

- **A pull inside a nested checkout under a protected path no longer reads as
  an unaccounted change.** The check after each shell call asks a clone,
  submodule or worktree under an adopter's `protected_paths` for its own
  committed content once a check has seen that checkout, so a `git pull`,
  checkout or submodule update inside it is accounted for the way the outer
  repository's own git moves are. A checkout that appears during a call (a
  clone or a copy into a protected path) reports its files once, as before. A
  git operation half done inside a nested checkout holds that checkout's files
  alone until git is done there; every other protected file is still judged.
  New content beside such a pull still reports, as does an edit in a nested
  repository with no commits. The harness's own zones are never asked of a
  nested git, even under a protected path that encloses one.
