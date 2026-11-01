### Fixed

- **The cited-pin run no longer shares the runner with the parallel test
  leg.** `tests/test_declared_limits_contract.py` runs the docs' cited test
  rows in one nested pytest child, among them write-guard rows whose hook
  judgment writes a speed bump's state, which the hook-spawn helper does not
  retry after a miss that left state, and rows of a wall-clock file the tier
  already kept off the load. Beside the parallel leg on windows-latest one
  such judgment outran the guard's budget and redded the portability leg for
  a merge that touched no hook. The file now runs on the full tier's serial
  leg (`scripts/proof_tier.py::NESTED_RUN_SERIAL_FILES`, read by every
  workflow that reads `SERIAL_FILES`), and the prose that counted five serial
  files names the list instead. The same rows in their own modules still run
  on the parallel leg with no retry (`DEF-2030`, for a ruling). (`DEF-4062`)
