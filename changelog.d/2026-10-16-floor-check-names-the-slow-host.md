### Fixed

- **On a slow machine, `init` and `doctor` no longer read a slow Python as a
  broken one.** Before trusting an interpreter, both ask it to start, with a
  2-second limit and one retry. When both tries ran out of time, which a
  loaded machine or a busy CI runner does to a working Python, the answer was
  "cannot start". Then:
  - `init` passed over the working interpreter. On a machine with only
    `python3`, it wired the hooks to `python`, which is not there, so no hook
    could run.
  - `init` and `doctor` both said every guard was failing open, and that no
    Python on PATH could be used.

  Now, as long as the interpreter still answers `--version` within its 2
  seconds:
  - A start check that ran out of time says nothing against the
    interpreter, so `init` wires the same name it would on a fast machine.
    A later candidate whose start was seen is preferred over one whose
    start was not, and `--rewire-interpreter` moves the hooks from an
    interpreter whose start was never seen to one whose start was.
  - `init` does not claim the hooks are active on a start it never saw: it
    says the start was not confirmed and tells you to run `doctor`.
  - `doctor` gives such an interpreter the 5 seconds a blocking hook gets.
    If it starts, `doctor` still warns that it was slow to start, since a
    hook runs for several times as long as a bare start. If it does not,
    `doctor` says every blocking guard runs out of time before it decides,
    which is true whether the machine is that loaded or the interpreter
    hangs at start-up. Either way it says what to do.
  - Each interpreter is asked once per run. Measured with every start
    check forced to run out of time, on a machine with both `python` and
    `python3`, `init` spawned 80 start checks of 2 seconds each; it now
    spawns 4.

  An interpreter that starts and exits with an error is still reported as
  unable to start, as before. A `--version` check that runs out of time is
  not covered here (a ledger row of its own).

- **A write-guard test no longer fails on every Windows run.** The test that
  an adopter's protected folder keeps its own deny message under a folded
  spelling checked `data /y.txt` (a trailing blank) on Windows too. There,
  unlike a trailing dot, a trailing blank on a folder in the middle of a path
  is not the same folder: Python, Git Bash and PowerShell each refuse it and
  nothing is written, so the guard has nothing to deny. That case now runs on
  macOS and Linux only.
