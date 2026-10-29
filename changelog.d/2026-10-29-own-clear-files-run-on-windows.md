### Fixed

- **The own-clear lane's two files run on Windows again.** `bench/own_clear/drive.py`
  guards its three POSIX-only imports (`fcntl`, `pty`, `termios`) so the module
  loads where there is no pty and `main()` refuses by name, exit 2, before it
  writes anything; the bounded-spawn census that imports every spawn-routing
  file outside the engine had read `ModuleNotFoundError` on windows-latest
  since #351. `tests/test_seat.py` expects the posix print line's quoted
  spelling of the mod directory (`shlex.quote`, which single-quotes a backslash
  path), with a sibling test pinning the quoting on a path the shell must
  quote, and the driver's load and refusal are pinned in
  `tests/test_own_clear.py` with the three names made unimportable on any host.
