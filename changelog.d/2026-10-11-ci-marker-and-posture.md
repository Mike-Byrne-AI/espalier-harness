### Changed

- **The Harness Guard no longer gates an adopter's own workflows.** On your
  repository a change under `.github/workflows/` needs the approval marker
  only for `harness-guard.yml`, the guard's own workflow; your other
  workflows are yours, under your own branch protection, as the in-session
  guard already treated them. On the Espalier-Harness source repository
  every workflow stays gated. `harness-guard.yml`, `tools/cc/ci_guard.py`,
  the hooks and the settings and integrity files stay gated everywhere. A
  pull request that edited your own `ci.yml` used to fail the check and call
  your file the harness's enforcement layer. `install-ci` says so once when
  it replaces a guard that gated every workflow.

### Fixed

- **Every command that writes a file the Harness Guard protects says the
  commit needs the approval marker.** `install-ci`, `upgrade --execute`, a
  re-run `init`, `merge-settings`, `clean-generated --execute`, `integrity
  refresh` and `fuse` print both forms -- `HARNESS-UPDATE-APPROVED` in the
  HEAD commit message (the last commit you push) for a direct push,
  `HARNESS-UPDATE-APPROVED@<sha>` in the pull request's title, `<sha>` the
  head under review -- when they changed a protected path git will commit. They say nothing when the guard is not installed, when every
  protected file they wrote is ignored by git, or where git cannot answer.
  The first commit after `install-ci` used to fail the check it had just
  installed, and nothing on that path named the marker. `docs/INSTALL-CI.md`
  and the Quickstart's CI, upgrade and fusion sections say the same.
