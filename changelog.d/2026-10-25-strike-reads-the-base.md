### Changed

- **A ledger strike drives the row's probe on both sides, and its guard too,
  before it writes.** `tools/cc/ledger_row.py strike` was the one ledger verb
  that drove nothing: `file` and `repin` run the row's probe through the
  checker's runner before they write, and the strike wrote the author's closing
  sentence unread. Now the strike checks out the base (the merge-base of HEAD
  and `origin/<default branch>`, read offline from `origin/HEAD`, else `main`,
  else `master`, never `gh`) through a temp index into a scratch directory
  outside the checkout (no shared worktree state, no `export-ignore`), drives
  every retiring id's probe there inside the runner's new `rooted(tree,
  pristine=True)` block (the verdict must be STILL_OPEN: the defect was there)
  and then at the head inside `rooted(root)` (it must be STRIKE_CANDIDATE: it
  is gone); any other pair is its own refusal, nothing written, exit 2. A side
  the runner cannot drive (UNRESOLVED, NO_ORACLE) is one printed line by
  default and a refusal under an explicit `--base <ref>`; `--no-base` skips the
  base and says so; a tree with no base to read prints one line and proceeds.
  `--guard <node id>` (repeatable) runs a pytest node at the head (green
  required) and at the base with the head's `tests/` laid over it (red
  required), with the tree first on the child's `PYTHONPATH` on both runs so
  `espalier` resolves to that tree's own package, the box lock's variables and
  the session marker stripped, no bytecode written, and the strike's own
  one-file pytest plugin recording each test's exception (the junit report
  carries no type): an earned red fails by `AssertionError` or `pytest.fail`;
  an `ImportError`, `AttributeError` or `NameError` at the base proves only
  that the symbol is new, any other exception means the test never reached
  its assertion, green on both sides cannot tell the two trees apart, and a
  collection error, the engine check, a skip or a run past its 300 s bound is
  a refusal by name. The dry run drives too, so it shows the refusal. Replayed
  on five rows struck 2026-10-16 to 10-18 from their recovered probes: every
  probe read open at the base and two still read open at the lane head, which
  only the head drive refuses. Necessary, not sufficient: a probe that reads
  an adjacent question passes both sides.
- **The probe runner roots itself for a block.**
  `tools/cc/check_ledger_probes.py::rooted(root, *, pristine=False)` is the one
  swap of the runner's four module globals, restored after the block whatever it
  did; `main`'s `--root` goes through it. `pristine=True` records that the
  caller built the tree from a ref, so the contamination memo is an empty map
  for the block instead of a `git ls-files` derivation, which in a plain
  directory reads git-unavailable and every tree-walking probe UNRESOLVED
  (19 of the live commands; 7 of 222 commands stay undrivable at a pristine
  checkout of `origin/main`, the measured figure). The vendored copies follow
  by the sync; `memory/parallel-work-protocol.md` item 8 says the strike reads
  both sides.
