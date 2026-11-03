### Fixed

- **A read of the remote's default branch that did not answer says so,
  instead of naming `main` or no default branch.** On a loaded box a
  ledger strike took a killed `origin/HEAD` read as a stale `origin/main`
  and drove the row's probe and guards at the wrong commit, or said the
  clone had no remote and, with no `--guard`, struck the row without the
  base drive; it now refuses and says to run it again. A filing's export
  drive said the root was not a checkout where git had not answered, and
  now names the git command. The Stop hook's block for a lane a
  fix-forward ruling names said `NoDefaultBranch` where git could not be
  asked, and now says that.
