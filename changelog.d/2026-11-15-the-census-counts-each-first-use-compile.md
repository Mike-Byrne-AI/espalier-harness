### Changed

- **`scripts/guard_cost_census.py --compile` counts the patterns compiled on
  first use (self-host).** A pattern moved behind a cached zero-argument
  accessor is still compiled by every call that opens its check, so the census
  now calls each accessor of the guard's pattern modules after the loader and
  prints `first_use_patterns`, `first_use_chars` and the distinct sum of the
  path plus first use (`summed_patterns`, `summed_chars`). The compile ratchet's
  ceiling reads that sum; its floor still reads the import figure.
- **The guard-pattern classify advisory reads first-use accessors (self-host).**
  An edit of a guard module that adds an accessor, or changes a source string
  one compiles, is judged against the command-position anchoring contract as
  an edit of a module-level pattern is, the accessor named as its call.
