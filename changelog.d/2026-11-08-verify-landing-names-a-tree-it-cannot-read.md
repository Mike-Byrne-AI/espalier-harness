### Fixed

- **`espalier verify-landing` refuses a folder git cannot read instead of
  reporting every claim owed.** Pointed at a folder outside any work tree,
  or at a checkout whose branch has no commit, it printed every claimed path
  as `OWED` at exit 0, since a failed git read returned the same empty list
  as an empty `HEAD`. It now exits 2 with the reason, git's own message
  included, and no table. Pointed at a subdirectory, it read `git ls-tree`'s
  prefix-relative listing, which no repo-relative claim matched; it now
  reads the whole tree. A claimed path with a non-ASCII name, which git
  printed quoted, now matches its tracked file. An inherited `GIT_DIR` or
  `GIT_WORK_TREE` no longer points the read away from `--repo`. A bare
  repository is read against `HEAD` alone, as before.
