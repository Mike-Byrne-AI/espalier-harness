### Fixed

- **A new ruff or mypy release can no longer red every required cell with no
  change in this repository.** The dev extra took both finding gates as
  floating ranges (`ruff>=0.5,<1.0`, `mypy>=2.3,<3.0`), so each CI run
  installed the newest release the range admitted, and the Harness Guard
  `ruff-lint` and `mypy-hooks` cells installed their own copy of the same
  ranges. A release that added or changed a check would have redded all five
  required `test (3.x)` cells at once, reading as an ordinary finding while a
  maintainer's older local copy stayed green. CI had already moved to ruff
  0.17.0 (released 2026-10-09) and mypy 2.4.0 unannounced, newer than either
  maintainer box. The dev extra now pins `ruff==0.17.0` and `mypy==2.4.0`, the
  versions CI ran green; the two Harness Guard cells install the dev extra, so
  the pin has one home and a bump is one pull request whose CI runs the new
  version. The missing-ruff hints from `espalier doctor` and the SessionStart
  banner, both shown on the source tree only, install the dev extra instead of
  the old range, and dependabot bumps each gate in a pull request of its own.
  `tests/test_external_tool_contract.py` pins each gate exactly, finds no
  workflow step that installs, fetches or uses one by a spec of its own,
  requires every job that runs one to install the dev extra, keeps both gates
  out of dependabot's grouped pip update, and keeps the proof tier's runners a
  closed world (pinned, or named as ranged with a reason).

### Added

- **`scripts/proof_tier.py --run` prints each runner's version** before its
  commands, read from the binary the command spawns, and names a runner whose
  version is not the dev extra's pin with the line that installs the pinned
  version (`python -m pip install ruff==0.17.0`). The line is a diagnosis and
  never changes the verdict.
