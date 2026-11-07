### Changed

- **Python 3.10 is dropped: the harness needs Python 3.11 or newer.** Python
  3.10 reached end-of-life upstream on 2026-10-01. The package metadata now says
  `Requires-Python >=3.11`, so `pip` on a 3.10 host will not install this
  release. There is no reduced mode for 3.10. When the interpreter `init` would
  wire into your hooks is older than 3.11, `init` refuses before it writes any
  file, names the version it found and tells you to update to Python 3.11 or
  newer. `doctor` and the SessionStart banner say the same about a tree that is
  already wired to an older interpreter, and give the command that re-wires the
  hooks once you have updated. Run under an older interpreter (a clone kept
  current by `git pull`, say), the engine prints the same sentence instead of a
  traceback. CI tests 3.11 to 3.14.
