# Known-positive freshness scanner fixtures

This file is the earn-the-gate fixture for the `freshness` scanner.
The contract test at
`tests/test_scanner_freshness.py::test_earn_the_gate_detects_every_fixture_shape`
calls `parse_fragment_markers` directly with this file's content and
asserts at least one Fragment per documented policy
(`verify-on-touch`, `weekly`, `numeric-contract` — from
`freshness._ALLOWED_POLICIES`). TP-105 / TP-143 / FM-7 §1.7 close.

The `freshness` scanner's `discover_fragments` walks
`FRAGMENT_SURFACE_ALLOWLIST` only (README.md, CHANGELOG.md, ESPALIER_MEMORY.md,
CLAUDE.md, `docs/**/*.md`, `.claude/**/*.md`). `tests/fixtures/*.md`
is NOT in the allowlist, so this fixture is structurally invisible to
`scan_repo` — no `EXEMPT_PREFIXES` addition is needed for the freshness
scanner.

## Fragments

<!-- espalier:fragment id=fixture-verify-on-touch
     bound=tests/fixtures/test_freshness_positives.md
     policy=verify-on-touch -->

The first fragment exercises the `verify-on-touch` policy shape.

<!-- espalier:fragment id=fixture-weekly
     bound=tests/fixtures/test_freshness_positives.md
     policy=weekly -->

The second fragment exercises the `weekly` policy shape.

<!-- espalier:fragment id=fixture-numeric-contract
     bound=tests/fixtures/test_freshness_positives.md
     policy=numeric-contract -->

The third fragment exercises the `numeric-contract` policy shape.
