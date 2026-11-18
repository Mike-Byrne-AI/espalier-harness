### Changed

- **A hook gate no longer starts a script your project folder holds in place
  of the program it names.** The gates' spawns (the Stop gate's test command
  and its git and gh reads, the zone watch's git reads, `post_write_check`'s
  git status and its memory autoprune's `espalier`) looked a bare program
  name up with Python's `shutil.which`, which on Windows searches the current
  folder first, so a `git.cmd` a cloned tree held at its root ran in git's
  place at every one of those reads. The lookup now reads absolute PATH
  entries alone, as the engine's has since its own fix, and skips an empty,
  `.` or relative entry (`./bin`, `node_modules/.bin`) too. If your stop-time
  test command (`ESPALIER_STOP_GATE_TEST_CMD`, or the `test` entry under
  `[extra_actions]`) names a script in your project folder by its bare name,
  name it by its path from the root instead, with its extension on Windows:
  `./run_tests.cmd`, or `./run_tests.sh` elsewhere. The Stop's block and the
  SessionStart warning now say so. A child whose output does not decode is
  also no longer reported as a program that never started.
