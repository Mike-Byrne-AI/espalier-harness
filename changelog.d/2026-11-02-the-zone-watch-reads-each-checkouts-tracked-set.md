### Fixed

- **The protected-file check keeps watching a generated-but-tracked
  directory wherever its git is, whenever its path was declared, and
  however the disk spells it.** A directory under a protected path whose
  own `.gitignore` is a bare `*` is skipped as generated unless git tracks a
  file in it, and that read asked only the outer checkout's index, only at
  the session's first snapshot, and matched names byte for byte. So such a
  directory went unwatched, and a slip write into it unreported, in three
  cases: when only a clone or submodule inside a `protected_paths` entry
  tracks it (every session, not just the first); for the rest of the
  session in which you add the protected path to `espalier.toml`; and on
  Windows or macOS when the directory was renamed in case alone, or its
  name is non-ASCII and git keeps it in the other Unicode form. The check
  now asks each checkout once, the nested one's own git included (never
  inside the harness's own protected directories), asks again at the first
  shell call after a protected path is added, and matches a name to the
  directory the filesystem says it is. The same reads apply when an
  `espalier` command records what it wrote into those paths. The time
  limits are unchanged: one snapshot's git reads share the 2 s they had.
