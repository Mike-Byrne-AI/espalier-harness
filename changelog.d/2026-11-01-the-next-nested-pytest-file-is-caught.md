### Fixed

- **A test that launches a pytest child itself is placed when it lands, not
  found by a red leg.** The tiers keep the nested cited-pin run off the parallel pool by
  a hand-kept list, and nothing read the suite for the next one: the axis
  registry's run of its proving nodes (`tests/test_axis_registry.py`, 64 s
  alone on the Windows seat) rode the pool. A rule in
  `tests/test_proof_tier.py` now reads every launch under `tests/` by the AST
  (a `subprocess` launcher whose argv is a pytest command, through a bound
  name, `+` or a starred name) and reds on one in a file on no serial list
  that its enrolment does not name; each of the eleven enrolled launches says
  what its child runs (a collection, a planted tree, a few in-process rows)
  and, where it runs on the Windows seat, its time alone, and the enrolment is
  exact both ways. The axis-registry
  file joins `NESTED_RUN_SERIAL_FILES` and, holding contract rows,
  `SERIAL_CONTRACT_FILES`, so the full tier's serial leg and the cheaper
  tiers' one-worker contract line run it: 72 s at one worker on the Windows
  seat, the price of the child having the box to itself. No red beside the
  pool had been seen since the test took its own timeout mark, so this closes
  an exposure, not a measured failure rate. Not read, and named in the rule's
  comment: a pytest reached through a script, which leaves
  `tests/test_verify_pins.py` (its script runs pytest in a clone, about 115 s
  for the file) on the parallel pool, filed as its own row; a shell string; an
  argv a helper returns or takes as a parameter.
