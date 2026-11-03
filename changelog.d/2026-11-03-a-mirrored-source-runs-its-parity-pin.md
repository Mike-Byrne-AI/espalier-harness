### Fixed

- **A cheaper tier now runs the parity test of a mirror its diff touches.**
  `scripts/proof_tier.py`'s own line brings the pinning test file of every
  `espalier/mirror_registry.py` row that holds a changed path, on its source
  side (as `covers` decides) or under one of its mirrors, read from the
  registry's literals so the CI tier job still imports no engine. A
  tests-only edit of a test file `espalier selfcheck` curates, or of its
  vendored copy, and a hand edit under `espalier/_vendor/cc/`, earned the
  contract tier, and none of its lines ran the parity test that reds an
  unsynced mirror; each now does. The own line's skip of what the contract
  line already runs also reads a module-level `pytestmark`, so
  `tests/test_package_resource_parity.py` (marked `contract` module-wide, the
  pin of the two `.claude/` rows and the harness-guard row) is not run twice.
