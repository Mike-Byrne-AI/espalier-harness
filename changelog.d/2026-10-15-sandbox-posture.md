### Added

- **`init` prints Claude Code's sandbox posture for the harness, `upgrade`
  prints it when asked, and `--sandbox-posture` writes it.** Where the Bash
  sandbox is on (macOS, Linux, WSL2), `sandbox.filesystem.denyWrite` entries
  put the zones `write_guard` denies on your tree (`tools/cc/`, the two
  settings files, `harness-guard.yml`; on the Espalier source tree also
  `.github/workflows/` and `espalier/`) and your `protected_paths` from
  `espalier.toml` behind the operating system's boundary for every sandboxed
  command and the processes it starts, and `denyRead` entries do the same for
  the secret paths the guard refuses to read (the dotenv file and its
  variants, `secrets/`, `.aws/credentials`, `credentials.json`), each at the
  project root and anywhere below it. Both lists are derived, never copied:
  the write list from the prefixes the hook applies at runtime (an adopter's
  own CI files are never denied), the read list parsed out of the deployed
  guard's own roster, so a roster that moves moves the lists, and a roster
  that stops being one is refused by name. The flag appends the entries under
  your keys through the same merge that wires the hooks (a backup first, a
  malformed file refused, a key that is not the shape the sandbox reads left
  alone and named) and never writes `sandbox.enabled`: turning the sandbox on
  is yours (`/sandbox` in a session). An entry of yours the sandbox could not
  honour (absolute, a home path, a wildcard, a climb) is left out and the
  print says why. `cc/` and the two `.espalier` manifests stay with
  `write_guard`: the harness's own shell commands write them. Measured on
  macOS: `denyWrite` holds for shell writes and `git checkout` and not for
  the `Write` tool, so the posture is a shell layer beside `write_guard`,
  never a replacement for its path check on `Write`, `Edit` and
  `NotebookEdit`; `denyRead` itself is not yet driven, and the dotenv
  template files the guard allows are refused by its glob. The deployed
  `docs/TROUBLESHOOTING.md` has what it refuses.
- **`doctor` reports the sandbox in three states.** On native Windows, that
  there is no sandbox and the location layer is the after-check and the
  guard's path check; otherwise whether the sandbox is off (the default) or
  on and from which of the project, local and user files (a managed file or
  `--settings` is not read), which of the derived entries the project and
  local files hold and miss (a `./` entry in the user file resolves under
  `~/.claude` and counts for nothing; a warning with its step when the
  sandbox is on and some are missing or a key is malformed), an entry an
  earlier engine wrote that this one no longer derives, and whether your
  user settings set `allowUnsandboxedCommands` to `false`, which holds
  against a project's `true` and stops the unsandboxed retry; printed
  advice, never a write to the user scope. A deployed guard whose roster
  cannot be read is a named warning with the managed-marker step, never read
  as "no secret paths".
