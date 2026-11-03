### Fixed

- **The shipped bodies tell a python-only host to run `python`.** The
  blueprint-authoring skill's `_recall.py` and `sister_site_probe.py` lines,
  and eight lines in the packaged troubleshooting, freshness, task-recipe and
  environment-catalog docs, spelled `python3`, the name a Windows box with only
  `python` on PATH does not answer. They spell `python` now, and the
  portability contract reads the skills, the packaged docs and the review
  workflows, which it never read: a `python3` followed by a harness script or
  the engine anywhere in a shipped body, and a bare `python3` at a command
  position in a fenced block, red the suite.
- **No spawn and no Windows-reachable workflow step names a bare
  interpreter.** Five scope-check runs in the pack-chain tests spawned
  `python3` by name; they spawn `sys.executable`. A contract now reads every
  `subprocess` spawn in the engine, the tools, the scripts and the suite for an
  argv opening with a bare `python` or `python3`, and every workflow step whose
  runner can be Windows (a matrix it cannot expand counts as Windows) for a
  bare `python3`.

### Added

- **The release notes carry a blind-axis disclosure.** `python
  tests/_axis_registry.py` prints the adopter-axes cells and then the release
  instruments with the stack, host, root and session value each runs the
  harness at; an axis every instrument ran at one value reads "a blind axis".
  `docs/RELEASE_CHECKLIST.md` gains the step before Tier 3: whoever cuts the
  tag pastes the report into the notes, and a blind axis ships named.
