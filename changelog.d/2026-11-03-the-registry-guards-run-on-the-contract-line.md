### Fixed

- **The two guards over the mirror registry's pinning tests run on the
  contract tier.** `tests/test_reinject_sync.py`'s check that every
  `espalier/mirror_registry.py` row's pinning test exists, and its check that
  a row's declared comparator is the comparison that test makes, carried no
  `contract` mark, so a diff renaming a parity test or changing how it
  compares earned the contract tier, which ran neither, and the full tier
  after the merge was the first to see it. Both are contract-marked now, and
  a pinning test whose module or node is gone is reported under the row's
  name, where the comparator check's walk raised a bare `StopIteration`. The
  `/implement-task` and `/implement-pack` bodies' description of the
  cheaper tiers' own line names the mirror-row parity test it brings.
