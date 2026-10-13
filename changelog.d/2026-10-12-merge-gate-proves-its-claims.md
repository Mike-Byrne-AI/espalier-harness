### Fixed

- **`install-ci` re-run on a repository that tracks its integrity manifest
  names the approval marker.** It re-seeds `.espalier/integrity.json` on every
  run (the manifest is stamped with the time it was written), and it printed
  the Harness Guard clause before that re-seed and without it, so a re-run
  whose guard files were unchanged left a gated path for the next commit and
  said nothing about the marker that commit needs. The clause now prints after
  the re-seed and names the manifest with the files written. Found by a census
  that runs every `espalier` command and switch on a tree with the guard
  installed and checks that each run changing a gated path names the marker,
  so a new command is held to the rule without anyone adding it to a list
  (`DEF-3002`).
- **The `verify_pins` discriminator's tests run in CI.** Their control commits
  existed only in a private history, so the whole test module skipped in
  every public CI cell and every fresh clone while the workflow said the `test`
  job ran it. Each control now names a commit on `main`; a shallow checkout
  skips the history-reading tests by name, and a full checkout missing one
  fails at collection. The workflow comments now say what each job runs
  (`DEF-938`, its verify-pins half).
