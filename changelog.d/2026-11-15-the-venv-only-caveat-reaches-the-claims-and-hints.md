### Fixed

- **A venv-only interpreter name is said where enforcement is claimed and
  where a hand edit is prescribed.** On a host whose name, once the activated
  virtualenv is off PATH, resolves to something that runs no Python 3.11+
  (the Windows Store alias, a Python 2, an install that cannot start), `init`
  and `merge-settings` said the venv-only warning once and then still printed
  "Hooks now intercept Claude Code tool calls" and "Enforcement is now
  active." Each claim (init's summary, `init --wire-hooks`, and
  `merge-settings`' wired and already-wired lines) now says the hooks run
  only in a session started from that virtualenv, what the name finds from
  any other shell, and the remedy: a Python 3.11 or newer on PATH outside the
  virtualenv, then `<that interpreter> -m espalier init .
  --rewire-interpreter`; the already-wired line no longer says "Nothing to
  do." A settings file whose entries name another interpreter keeps its
  claim. Every hand-edit sentence that spells the name (doctor's remedies for
  an inert, orphaned or legacy-form gate or reporter, the disarmed narration
  of `init`, `merge-settings` and `upgrade`) and doctor's statusLine
  `--segments` note now open with that remedy and spell the interpreter to be
  put on PATH, where the same report or command has said the name runs only
  inside the virtualenv. A host whose name resolves to nothing outside the
  virtualenv is told nothing by the writing commands, as before. No new
  probe.
