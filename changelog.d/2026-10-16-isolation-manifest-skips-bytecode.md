### Fixed

- **The live-tree isolation test no longer reads another worker's bytecode as
  the tool's mutation.** The test that proves `scripts/verify_pins.py` leaves
  the checkout untouched snapshots every file before and after a run. A test
  worker's first import of a module compiled a `.pyc` inside that window, and
  the snapshot read it as a change, reddening required cells on files no test
  wrote on purpose (twice on 2026-10-16). `__pycache__` directories are now
  skipped at any depth by the one rule every walk and copy of the live
  checkout shares; a source file beside one is still seen.
- **The recall-eval tests no longer error together on a loaded cell.** Their
  shared fixtures are paid by whichever test asks first, and on a busy runner
  that test's 60-second ceiling ran out during setup, so every test sharing
  the fixture errored at once. The module now gives each of its tests the
  ceiling the shared setup needs. It keeps them out of the `slow` mark, so
  they still run in every not-slow slice.
- **Two mail-channel tests pass on a Windows host.** One expected only the
  read-back's refusal wording, where Windows git refuses the bad file name
  itself first; it now accepts either refusal and checks that nothing was
  pushed. The other compared a checked-out file that `core.autocrlf` rewrites
  with CRLF line endings; it now compares the committed file.
