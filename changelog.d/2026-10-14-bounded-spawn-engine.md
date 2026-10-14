### Fixed

- **The engine's timeouts are a bound on Windows too.** `espalier init`,
  `doctor`, `pre-release`, `freshness`, `fuse` and the other engine commands
  probe interpreters and read git with a timeout, and on Windows
  `subprocess.run` kills only the program it started when the timeout passes,
  then waits for any program that one started if it still holds the output:
  the interpreter a `.bat` shim launches (pyenv-win), and git itself, which
  Git for Windows runs behind a launcher. A 3 s cap on `pre-release`'s
  command runner took 20.3 s through such a shim (driven 2026-10-14). Every
  timed spawn in the engine now goes through its own copy of the bounded
  spawn `tools/cc` has used since 2026-10-13, which ends the whole process
  tree at the timeout, and the same call returns at its cap. The stdlib-only
  freshness scanner carries a third copy, and a test holds the three equal.
  The maintainer scripts under `scripts/`, `bench/` and `tools/` take the
  `tools/cc` copy, loaded from their own checkout. One bench runner keeps its
  own spawn: it sends every stream to the null device, so no program holds a
  pipe, and on POSIX it ends the whole process group itself.
- **The fresh-clone gate's leg bound and the archive probe's suite bound end
  the whole tier.** Both stream their child's output under a watchdog that
  killed only the child, so the read went on while pytest, or the real
  interpreter behind a Windows venv's `python.exe`, held the pipe: a 3 s leg
  bound returned at 20.1 s and a 9 s suite bound at 20.5 s (driven
  2026-10-14). The fresh-clone gate now runs the tier in its own process
  group and ends the group (POSIX) or the tree (Windows) at the bound and on
  Ctrl-C; the archive probe, which already ended the group on POSIX, ends the
  tree on Windows too.
