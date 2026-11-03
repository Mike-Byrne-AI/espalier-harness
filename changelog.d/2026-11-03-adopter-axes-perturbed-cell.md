### Added

- **Each pull request's tests also run on a host whose `python3` is a
  Microsoft Store alias.** A new CI job, `perturbed` (not a required check),
  puts a stand-in for the alias ahead of PATH: asked to run, it prints the
  alias's "Python was not found" text and exits 49, while `python` answers.
  The job checks the stand-in is in force, then runs the parallel leg of the
  proof tier the pull request earns (on the full tier, every test file but
  the serial ones), so a test or a script that spells `python3` reds on the
  pull request instead of on the first adopter machine shaped that way.
  `scripts/proof_tier.py --basetemp DIR` gives each pytest line that base
  temporary directory on its own command line, never through
  `PYTEST_ADDOPTS`: a pytest child that a test launches inherits that
  variable, and pytest empties an explicit base temporary directory before
  using it, so the child would delete every parallel worker's directories
  under it. An empty value, or a directory inside the checkout, is refused.

### Fixed

- **The pack-chain driver's python steps run where `python3` is a Store
  alias stub and `python` answers.** `scripts/run_pack_chain.sh` spelled
  `python3` at six steps, so on such a host every scope gate, receipt check,
  install gate and landing step failed. It now picks its interpreter once,
  after its argument checks, with the shared resolver line: the first of
  `python3`, `python` and `py -3` that answers a Python 3.10 or later.
  Measured on macOS with the stand-in; its install gate still reads a
  POSIX virtual environment's layout.
- **The reachability bench skips a row whose interpreter only resolves.** A
  Store alias resolves as `python3` or `python`, so a row that needed one ran
  and read as a row that never reaches its target; the bench now asks those
  two names to run a no-op program first.
