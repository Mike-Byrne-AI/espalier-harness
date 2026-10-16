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

  Now:
  - A start check that never answered says nothing against the interpreter,
    so `init` wires the same name it would wire on a fast machine.
  - Neither `init` nor `doctor` claims the hooks are active on a start they
    never saw: each says the start was not confirmed, names the slow machine,
    and tells you to run `doctor` again on a less loaded machine.
  - Each interpreter is asked once per run. Measured with every check forced
    to run out of time, `init` ran 80 of them, 2 seconds each; it now runs 2.

  An interpreter that starts and exits with an error is still reported as
  unable to start, as before.
