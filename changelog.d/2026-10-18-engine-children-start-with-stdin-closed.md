### Fixed

- **`espalier init` no longer dies on Windows when whatever ran it closed its
  standard input** (DEF-928). Every child the engine starts is handed a closed
  stdin unless it is fed one, so an installer, a CI step or a wrapper that
  closes stdin before `init` no longer meets `[WinError 6] The handle is
  invalid` at the first `git` read. An `init` that does fail at its
  fingerprint removes the seed docs it had just created, and says so, instead
  of leaving a half-written tree.
  - One cost on Windows: a command the engine runs that streams its output to
    the terminal now fails to start when the terminal's own output handle is
    dead, where it used to start.
  - The shipped `subprocess_contracts` and `encoding_contracts` scanners read a
    function named `run_no_stdin` as a spawn wrapper, as they read
    `run_bounded`.
