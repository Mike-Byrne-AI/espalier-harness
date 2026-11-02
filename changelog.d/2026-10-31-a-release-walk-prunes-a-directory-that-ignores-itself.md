### Fixed

- **A release archive built from a tree with no git index leaves out a
  directory that ignores itself.** Both archive builders (`espalier
  release-pack` and `scripts/build_release_archive.py`) ship from the git
  index, and fall back to walking the files on disk where the root has none
  (an exported tree, an extracted archive, a plain copy). That walk shipped a
  directory whose own `.gitignore` is one bare `*` with everything in it,
  though no index ever holds such a directory: Claude Code's plugin loader
  writes the own-clear mod's `.claude-plugin/types/` that way, so its
  TypeScript declarations reached the public archive. Both walks now leave
  such a directory out, by the same reading of the declaration that the zone
  check uses, and `espalier pre-release`'s internal-leak check walks the same
  set, so it no longer fails on a file the archive never carries; the root
  itself, and a `.gitignore` that is a rule set rather than the lone `*`, are
  walked as before. (`DEF-4072`)
