### Fixed

- **The merge recovery the `/ship` body prints works on Apple Git.** The
  record-finish refusal `staged with a conflict marker: <path>` told the
  operator to run `git update-index --unresolve -- <path>`, and Apple Git
  2.39.5 (the git Xcode ships on macOS) reads that `--` as a path named `--`,
  exits 1 (`error: --: not in our branch`) and unresolves nothing, so the
  merge stayed refused and the operator had no second path; on this box the
  test that drives the recipe was red on every run, and 37 of the last 100
  merged pull-request bodies explained it by hand. The body now prints
  `git update-index --unresolve <path>`, which recreates the index stages on
  2.39.5 and, driven after `git add -A` on CI's git (the version the runner
  prints), there too; after `--unresolve` Apple Git 2.39.5 takes every word
  as a path, so the separator cannot be used there, and no record file's path
  begins with `-`, so no git needs it for these paths. The refusal names each
  staged path separated by spaces (a comma-joined paste failed the same way).
  The test reads the recipe out of the body and drives it, and pins the body
  to exactly one bare recipe, so the two cannot drift apart again.
