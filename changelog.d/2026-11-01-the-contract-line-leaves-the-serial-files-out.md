### Fixed

- **The contract and recall tiers no longer run a serial file beside the
  parallel pool.** Their contract line, `pytest -n auto -m contract -q`, names
  no file, so it collected the contract rows of a file the tiers keep off the
  pool by measured placement: all 13 rows of the nested cited-pin run in
  `tests/test_declared_limits_contract.py`, whose child redded a windows-latest
  leg beside the pool. The line now leaves out the serial files that hold a
  contract row (`SERIAL_CONTRACT_FILES` in `scripts/proof_tier.py`) and a
  second contract line runs them at one worker; it rides the parallel leg, so
  a cheaper tier's serial leg stays empty. Two pins drive a collection: no
  `-n auto` line that names no test file (or names only a directory) collects
  a serial file's row, and the list equals the serial files with a contract
  row, both ways. Measured on four workers: the contract lines went from 268 s
  and 280 s to 299 s and 312 s (the parallel line about 23 s faster, the
  one-worker line 55 s), about 32 s a run, the price of the nested run having
  the box to itself; no red on a cheaper tier had been seen, so this closes an
  exposure, not a measured failure rate.
