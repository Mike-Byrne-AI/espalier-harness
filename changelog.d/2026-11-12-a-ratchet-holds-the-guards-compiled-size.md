### Added

- **A test holds what `write_guard`'s pattern path compiles under a ceiling
  (self-host).** `tests/test_guard_compile_ratchet.py` reads the path through
  the cost census's compile reader in a fresh interpreter and reds where the
  compiled characters pass 228,000 or the shared command-position fragment
  passes 1,750 characters: the figures at the head it was cut from plus 10%. It
  catches a growth the size of the one that never merged (4,301 characters of
  fragment, 387,130 compiled), not a single 100-character alternation or a
  second copy of the fragment in one pattern. It also reds where the reader
  read no pattern at all, so a loader that loads nothing cannot pass.
- **`docs/HOOK_ASSUMPTIONS.md` gains `write_guard`'s per-call figures**: each
  call kind's median and interquartile range on a macOS laptop, the load
  beside them, and the compiled size that tracks the cost.
