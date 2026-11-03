### Fixed

- **The shipped bodies tell a python-only host to run `python`.** The
  blueprint-authoring skill's `_recall.py` and `sister_site_probe.py` lines,
  and eight lines in the packaged troubleshooting, freshness, task-recipe and
  environment-catalog docs, spelled `python3`, the name a Windows box with only
  `python` on PATH does not answer. They spell `python` now, and the
  portability contract reads the skills, the packaged docs and the review
  workflows, which it never read. A `python3` (with any interpreter flags)
  followed by a `tools/` or `scripts/` path or `-m espalier` on a line of a
  shipped body, and a bare `python3` at a command position in a fenced block,
  red the suite.
- **Spawns and Windows-reachable workflow steps name the interpreter that
  answers.** Five scope-check runs in the pack-chain tests spawned `python3` by
  name; they spawn `sys.executable`. A contract now reads the spawns in the
  engine, the tools, the scripts, the suite and the bench (`subprocess` under
  any alias, and the harness's bounded spawns) for a literal argv opening with
  a bare `python` or `python3`. It also reads every workflow step whose runner
  can be Windows for a bare `python3`; a runner it cannot expand counts as
  Windows.

### Added

- **The release notes carry a blind-axis disclosure.** `python
  tests/_axis_registry.py` prints the adopter-axes cells and then the release
  instruments with the stack, host, root and session value each instrument's
  own run is at; an axis every instrument's own run is at one value reads "a
  blind axis". `docs/RELEASE_CHECKLIST.md` gains the step before Tier 3, with
  the commands that append the report to the release body once the release
  exists; a blind axis ships named.
