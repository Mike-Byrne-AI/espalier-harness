### Fixed

- **A venv's interpreter wired over a non-Python outside the venv is said,
  not wired in silence.** Inside an activated virtualenv whose name, once the
  venv is off PATH, resolves to something that runs no Python 3.11+ (the
  Windows Store alias, a Python 2, an install that cannot start), with no
  other Python 3.11+ on PATH, `init` still wires the venv's name: the
  documented fallback for a host with no Python 3 outside the venv. It said
  nothing, so a session started from another shell, an IDE or the desktop app
  hit that name on every hook, and every blocking guard failed open while
  `init` had reported success. `init`, `upgrade`, `merge-settings` and `fuse`
  (their dry runs included) now say it once a run, before their first write,
  in a `[<verb>] WARNING:` paragraph naming the venv, what the name resolves
  to outside it and what that answered, any candidate whose `--version` never
  answered on a loaded host, and the remedy: a Python 3.11+ on PATH outside
  the virtualenv, then `<that interpreter> -m espalier init .
  --rewire-interpreter`. The command still goes ahead, and a settings file
  that already names another interpreter keeps it. A host where the name
  resolves to nothing outside the venv is told nothing, as before, and
  `doctor`, which already names a wired interpreter that runs only inside a
  venv, does not say it twice. The sentence comes from readings the
  interpreter check already made, so it adds no probe of its own.
