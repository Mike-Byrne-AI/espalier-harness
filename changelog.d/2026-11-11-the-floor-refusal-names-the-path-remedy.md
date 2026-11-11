### Changed

- **The below-3.11 refusal also names the PATH remedy.** When every Python that
  `init` tries is older than 3.11, `init` (and `upgrade`, `merge-settings` and
  `fuse`) still refuses before it writes any file and still says first that the
  harness does not run on the version it found. It now adds: "or put a Python
  3.11 or newer on PATH as python3 or python". That is the fix for a host whose
  engine already runs on a newer Python (installed through pipx or uv) while
  PATH `python3` is older, because the hooks are wired to the PATH name `init`
  finds.

### Fixed

- **`doctor` no longer calls a below-3.11 `python3` working.** On a tree wired to
  an interpreter `doctor` flags, and with PATH `python3` older than 3.11, it
  said "a WORKING `python3` IS on PATH" and named a re-wire that then found
  nothing to wire. It now names the interpreter the re-wire would pick, or says
  that nothing it tries on PATH clears the floor yet.
