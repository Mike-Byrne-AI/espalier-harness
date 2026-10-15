### Added

- **`init` and `upgrade` print Claude Code's sandbox posture for the harness,
  and write it on `--sandbox-posture`.** Where the Bash sandbox is on (macOS,
  Linux, WSL2), `sandbox.filesystem.denyWrite` entries put the harness zones
  (`tools/cc/`, `.github/workflows/`, the integrity and freshness manifests,
  the two settings files, and your `protected_paths` from `espalier.toml`)
  behind the operating system's boundary for every shell command, and
  `denyRead` entries do the same for the secret paths `write_guard` refuses to
  read (`.env` and `.env.*`, `secrets/`, `.aws/credentials`,
  `credentials.json`), each at the project root and anywhere below it, as the
  guard matches them. Both lists are derived, never copied: the write list
  from the engine's protected-zone roster, the read list parsed out of the
  deployed guard's own roster, so a roster that moves moves the lists. The
  flag appends the entries under your keys through the same merge that wires
  the hooks (a backup first, a malformed file refused) and never writes
  `sandbox.enabled`: turning the sandbox on is yours (`/sandbox` in a
  session). Without the flag both commands print what they would write.
  `cc/` stays with `write_guard`, whose carve-outs the harness's own shell
  commands write into. Measured on macOS: `denyWrite` holds for shell writes
  and `git checkout` and not for the `Write` tool, so the posture is a shell
  layer beside `write_guard`, never a replacement for its path check on
  `Write`, `Edit` and `NotebookEdit`.
- **`doctor` reports the sandbox in three states.** On native Windows, that
  there is no sandbox and the location layer is the after-check and the
  guard's path check; otherwise whether the sandbox is off (the default) or
  on and from which settings file, which of the derived entries are present
  and missing (a warning when the sandbox is on and some are missing), and
  whether your user settings set `allowUnsandboxedCommands` to `false`, which
  holds against a project's `true` and stops the unsandboxed retry; printed
  advice, never a write to the user scope. A deployed guard whose roster
  cannot be read is named, never read as "no secret paths".
