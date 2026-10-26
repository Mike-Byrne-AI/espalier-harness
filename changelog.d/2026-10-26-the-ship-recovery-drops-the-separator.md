### Fixed

- **The merge recovery the `/ship` body prints works on Apple Git.** The
  record-finish refusal `staged with a conflict marker: <path>` told the
  operator to run `git update-index --unresolve -- <path>`, and Apple Git
  2.39.5 (the git Xcode ships on macOS) reads that `--` as a path named `--`,
  exits 1 (`error: --: not in our branch`) and unresolves nothing, so the
  merge stayed refused and the operator had no second path; on this box the
  test that drives the recipe was red on every run, and 37 of the last 100
  merged pull-request bodies explained it by hand. The body now prints
  `git update-index --unresolve <path>`, which recreates the three stages on
  2.39.5 and on git 2.40 and later (CI's git, where the test proves it); a
  record file's path never begins with `-`, the one case the separator
  guarded, and the body says so. The test drives the bare spelling and pins
  the body to the spelling it drives, so the two cannot drift apart again.
