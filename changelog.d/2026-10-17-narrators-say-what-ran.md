### Fixed

- **`merge-settings` and `upgrade` no longer say "nothing to do" above a
  warning that names something to do.** When `.claude/settings.json`'s
  `permissions.allow` is not a list, no merge compares or appends the
  profile's rules, and both commands warned "Fix the block by hand" while
  their last line said "Nothing to do." on an already-wired tree, or
  "harness is current; nothing to do." on a current one. `merge-settings`
  now drops the claim. `upgrade` names the state: "your
  .claude/settings.json's permissions.allow needs fixing by hand (the WARN
  above)".
- **A run that added only espalier's statusLine no longer says "The settings
  were wired anyway."** On a tree whose hooks do not run, `merge-settings`
  and `init --wire-hooks` said so after any write, though no hook event was
  wired. They now say it only when one was, as `upgrade --execute` already
  did.
- **`init --wire-hooks` labels its "could not re-read" warning with its own
  flag**, not `merge-settings:`, a command the operator had not run.
