### Fixed

- **A freshness bound that names a nested symbol drifts with the symbol's own
  lines.** A bound such as `<test file>::TestClass::test_method` (or
  `TestClass.test_method`), the form the fragment template in
  `docs/FRESHNESS.md` uses, was never placed: the scanner placed top-level
  names only, so the fragment counted every commit to its file and went stale
  or critical on edits that never touched the method, with nothing in `check`
  saying so. A nested symbol is now placed one segment per scope, its span
  the innermost definition's own lines with its decorators, for the commit
  count and for the uncommitted-change check alike. A symbol the scanner still
  cannot place (renamed away, or in a file that is not Python) keeps the
  file's count, and `check`'s message names it and why. `espalier freshness
  pin` refuses such a bound, naming it (`--force` records it anyway), and
  `pin --all` refuses before pinning anything.
