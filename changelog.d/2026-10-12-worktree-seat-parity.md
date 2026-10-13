### Fixed

- **A session in a git worktree reads the tree the way a normal clone does.**
  A linked worktree's `.git` is a file, and the file lister read that as no
  checkout of its own: it walked the disk, listing gitignored files beside the
  tracked ones, so the machine-local-path gate redded in a worktree over an
  ignored log that a clone never lists (measured 2026-10-12). A `.git` file now
  counts as a checkout (`git ls-files`); a gitlink whose target is gone still
  falls back to the walk. `espalier provenance`, which `/commit` runs before
  staging, now also reads the files git neither tracks nor ignores, so a new
  file carrying a build-history tag is seen before it is staged, in a worktree
  or a main checkout.
- **A worktree session can run `espalier audit`.** `.worktreeinclude` now lists
  the two generated reports the audit reads (`reports/repo_fingerprint.json`,
  `reports/harness_config.json`) beside the settings file, so Claude Code
  copies them into each worktree it creates; without them `/smoke` and
  `/preflight` failed there on "missing generated file". `init` writes them,
  `upgrade --execute` appends them to an existing include, and `doctor` names
  what each missing entry costs (no hooks for the settings file, a failing
  audit for the reports). An entry the repo tracks, or one a
  `gitignore_declined` line leaves unignored, is left out and said; `doctor` and
  `upgrade` now reach the same verdict on a tracked report.

### Changed

- **`doctor` warns on an include written before this change** (settings file
  only) until `upgrade --execute` appends the two report lines; commit the
  file afterwards, as the first time.
