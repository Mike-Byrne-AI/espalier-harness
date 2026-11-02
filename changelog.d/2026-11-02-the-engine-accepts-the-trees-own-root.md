### Fixed

- **The delete helper removes a locked tree that holds a directory.** On
  POSIX a directory without its write bit refuses the removal of every entry
  in it, and `espalier/_rmtree.py::remove_tree` cleared a refusing entry's
  parent only when that parent was strictly inside the tree, so a refusal
  whose parent was the tree's own root went unanswered: a `build/` at 0o500
  holding `lib/` raised `PermissionError` on every
  interpreter from 3.10 to 3.14, where the release smoke's own stdlib copy
  removed it. The root is now part of what was asked to delete, as its copy
  always read it; the root's parent is still never touched, so a tree under
  a read-only directory is reported, not reached through.
- **The release smoke reports a tree under a locked parent.**
  `scripts/wheel_smoke.py`'s delete helper read the refused path as a
  string, and `rmtree` hands a refusal of the tree's own root back as the
  `Path` it was given, so the smoke stopped on an `AttributeError` where the
  engine's helper raises `PermissionError`. Both now raise the refusal, and
  the parity tests drive both over a locked `build/` holding a directory and
  a `build/` under a locked repository root.
