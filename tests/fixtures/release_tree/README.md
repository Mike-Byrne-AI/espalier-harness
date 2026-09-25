Release-surface parity fixture (Pack 6 Task 6-D).

The test `tests/test_release_surface_parity.py` seeds a canonical synthetic
repo tree into a pytest `tmp_path` and runs both `release_pack.create_release_zip`
and `pre_release.run_cleanliness_gate` against it. The seed manifest lives
inside the test file — Python is more expressive than a parallel directory
tree, and avoids polluting this repo with problematic names like `.git/HEAD`
or `__pycache__/foo.pyc`.

The parity invariant locked by the test: both consumers classify every
sample path identically. `pre_release` and `release_pack` share
`surface_contract` as their source of truth and cannot silently drift.

This file exists so the fixtures directory is tracked in git and the
README is discoverable if the test fails and a contributor asks "what is
this fixture for?".
