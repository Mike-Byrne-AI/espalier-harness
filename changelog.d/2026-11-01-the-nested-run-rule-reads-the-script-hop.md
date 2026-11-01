### Fixed

- **A test that reaches pytest through a script is placed too.** The
  nested-run rule in `tests/test_proof_tier.py` read a pytest command written
  in a test's own launch, so `tests/test_verify_pins.py`, whose
  `scripts/verify_pins.py` clones the repository and runs a pytest child twice
  per control, rode the parallel pool unplaced. The rule now reads one script
  hop: a launch whose argv's head, or the word after the interpreter, is a
  path ending `scripts/<name>.py` (a constant, a `/` chain, an
  `os.path.join`, a `str()` of one) counts when that script launches a pytest
  child as the rule reads it, with rows that must trip and rows that must stay
  quiet (a script outside the set, a script path read and never launched, a
  script named as data). The hop found four launches: the verify-pins file's
  three, and `tests/test_demo_end_to_end.py`'s run of
  `scripts/release_check.py`, whose pytest leg is off outside the release job
  (enrolled, 11 s, no child). The verify-pins file joins
  `NESTED_RUN_SERIAL_FILES` and, holding a contract row,
  `SERIAL_CONTRACT_FILES`: 495.7 s at one worker on the Windows seat, 65 s of
  it waiting on the box lock beside another seat's tier. Its 1800 s module
  mark raises the floor `tests/test_ci_job_bounds.py` derives for the two jobs
  that run the serial files, so the `test-serial` cells and the post-merge
  Windows leg are bounded at 40 minutes (were 30 and 25), the mark plus the
  contract's ten; the Windows leg's shallow checkout skips the file's history
  rows by its own guard. Still not read, and named in the rule's comment:
  a second hop (a script that reaches pytest through another script), a
  script launched past interpreter flags or as a module.
