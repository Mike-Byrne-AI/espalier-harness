### Fixed

- **On a slow machine, `init` and `doctor` no longer read a Python that is
  slow to print its version as no Python at all.** Before trusting an
  interpreter, both ask it for `--version`, with a 2-second limit. When that
  ran out of time, which a loaded machine or a busy CI runner can do to a
  working Python, the answer was read as "not a Python 3". Then:
  - `init` passed over the working interpreter. On a machine with only
    `python3`, it wired the hooks to `python`, which is not there, so no hook
    could run, and said every guard was failing open.
  - `doctor` said the same, called a working Python 3 "older than 3.10" when
    it was the very interpreter running `doctor`, and told you to install
    Python.

  Now:
  - The version check is asked twice, and its answer is kept for the run, so
    every part of `init` and `doctor` reads the same answer. The interpreter
    running `espalier` is not asked at all: it knows its own version.
    Measured with every version check forced to run out of time, on a
    machine with both `python` and `python3`, `init` spawned 42 version
    checks of 2 seconds each (53 when the interpreter running it was slow
    too); it now spawns 4.
  - An interpreter whose version check never answered is neither trusted nor
    refused on it: `init` wires it, the Windows `py -3` launcher included,
    only when nothing on PATH answered, ahead of the `python` name it used to
    fall back to, and says so, including that one which hangs instead makes
    every hook wait out its timeout.
  - `init` does not claim the hooks are active on it: it says the
    interpreter was not confirmed and tells you to run `doctor`.
  - `doctor` gives such an interpreter the 5 seconds a blocking hook gets.
    If it answers then, `doctor` still checks it against the 3.10 floor and
    asks it to start, and warns that it is slow. If it does not answer,
    `doctor` says every blocking guard runs out of time before it decides,
    and what to do.
  - No message tells you to install Python, or put one on PATH, while the
    one on PATH merely did not answer in time: each says to run `doctor`
    again when the machine is less loaded first.
  - `--rewire-interpreter` treats such an interpreter as unconfirmed: it
    moves the hooks to one that answered and started, and otherwise says
    what it left.

  An interpreter that answers its version check as a Python 2, or as
  anything other than Python, is still refused, as before.
