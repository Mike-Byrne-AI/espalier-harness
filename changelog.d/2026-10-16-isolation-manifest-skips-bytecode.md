### Fixed

- **The live-tree isolation test no longer reads another worker's bytecode as
  the tool's mutation.** The test that proves `scripts/verify_pins.py` leaves
  the checkout untouched snapshots every file before and after a run. A test
  worker's first import of a module compiled a `.pyc` inside that window, and
  the snapshot read it as a change, reddening required cells on files no test
  wrote on purpose (twice on 2026-10-16). `__pycache__` directories are now
  skipped at any depth by the one rule every walk and copy of the live
  checkout shares; a source file beside one is still seen.
