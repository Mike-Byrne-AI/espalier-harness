### Added

- **A test holds what `write_guard`'s pattern path compiles inside a band
  (self-host).** `tests/test_guard_compile_ratchet.py` reads the path through
  the cost census's compile reader in a fresh interpreter and reds where the
  compiled characters or the shared command-position fragment leave 10% either
  side of a pinned reading (206,695 characters and a 1,580-character fragment):
  past 228,000 or 1,750 a growth owes its per-call figure, and under 186,000 or
  1,400 the change that lowered it moves the band down. It catches a growth the
  size of the one that never merged (4,301 characters of fragment, 387,130
  compiled), not a single 100-character alternation or a second copy of the
  fragment in one pattern. It also reds where the loader compiles no pattern of
  its own, where no pattern read embeds the fragment, and where a new cached
  compile appears that the count cannot see. The pinned reading carries where,
  on what interpreter and against which per-call figure it was taken, and the
  limits follow from it.
- **The cost census reports the loader's own share**: `--compile` prints the
  patterns `write_guard`'s pattern-path loader compiles first (8 patterns and
  8,997 characters at the pinned reading; the imports compile the rest).
- **`docs/HOOK_ASSUMPTIONS.md` gains `write_guard`'s per-call figures**: each
  call kind's median and interquartile range on a macOS laptop and on Windows,
  the load beside them, and the compiled size that tracks the cost.

### Fixed

- **The cost census no longer says the hook wiring passes `-B`**: the wiring
  starts `write_guard.py` plainly, and the census adds `-B`, so after a pull a
  run whose modules read stale overstates a warm live call.
