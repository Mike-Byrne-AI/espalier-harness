### Fixed

- **A hook's or a `tools/cc` script's timeout is a bound on Windows.**
  `subprocess.run` kills only the program it started when the timeout
  passes, and on Windows it then waits for any program that one started
  if it still holds the output: the interpreter a `.bat` shim launches
  (pyenv-win), and git itself, which Git for Windows runs behind a
  launcher. A 2 s cap took 20.1 s through such a shim, and a 1 s cap on a
  git network read took 21.1 s, so the SessionStart banner's mail fetch and
  its git reads could run past their caps and past the hook's own time
  limit. Every timed spawn under `tools/cc` now goes through one
  bounded spawn that ends the whole process tree at the timeout; the
  banner's mail read against a stalled origin returns in 3.6 s on a 3 s cap
  where it took 20.2 s. The same defect in the engine's own spawns is
  recorded as `DEF-3004`.
