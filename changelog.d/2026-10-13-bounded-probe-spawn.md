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
  bounded spawn that ends the whole process tree at the timeout (the CI
  guard's local git reads aside, which import nothing a pull request could
  change); the banner's mail read against an origin that stalls for 20 s
  returns at its 3 s cap instead of after the stall. The same defect in the
  engine's own spawns is recorded as `DEF-3004`.
