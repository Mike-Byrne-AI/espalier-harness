### Added

- **The release smoke installs into a Node project under a spaced root.**
  `scripts/wheel_smoke.py` takes `--stack {none,python,node,go,rust}`, which
  writes that adopter project's files into the target before its `git init`,
  and `--spaced-root`, which puts the venv and the target under a directory
  whose name holds a space. The release workflow's smoke matrix runs it a
  second time on every cell with `--stack node --spaced-root`, so a release is
  checked on the tree and the root an adopter brings and not only on an empty
  repository. A stack whose files the script cannot read fails the run by
  name; it never falls back to the empty tree.
