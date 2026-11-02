### Added

- **A box-lock waiter can bound its wait.** `ESPALIER_BOX_LOCK_WAIT_S` (seconds,
  unset by default and never set by the seat launcher) ends a waiting run
  before any test once the bound passes: `box lock: did not run` on stderr,
  exit status 75 (sysexits' EX_TEMPFAIL, outside pytest's 0 to 5) and a
  `gave_up` line in the lock's log. An agent's run under a Bash call's cap,
  or a mutant runner's, killed at the cap read as the run's verdict, and a
  mutant whose pytest never ran read as a survivor. pytest's `Exit` subclasses
  `Exception`, so the plugin's configure lets it through its catch-all, which
  would otherwise have swallowed it and run unguarded. `scripts/proof_tier.py`
  reads 75 as its own verdict, `DID NOT RUN`, skips its later pytest lines
  (each would wait the bound out again), and lets a red on any other line
  outrank it; the fresh-clone gate reads the new receipt. The seat launcher
  drops an inherited bound, so a seat never runs every tier under one.
  (`DEF-4056`)

### Fixed

- **The box lock's waiting line no longer hands a waiter the kill of a live
  seat's tier.** Past sixty minutes the line named `kill -9 <pid>`
  (`taskkill /T /F /PID <pid>` on Windows) for any holder, and a seat's full
  tier on a loaded box is often past sixty minutes. On 2026-10-31 a window
  ended a live seat's leg by pid as a stray. The holder's record now names its
  checkout, and a waiter past the ceiling reads Claude Code's session registry
  for that checkout. Only a live holder whose checkout holds no live session
  is offered the stop command. A seat with a session, or one whose sessions
  cannot be read, is to be asked on the mail. A holder that names no seat (a
  fresh-clone gate leg, a scratch clone's run) is to be traced through its
  parents first. A dead pid gets no command at all. The record's start is now stamped when
  the lock is taken, not at configure, so time spent queued behind another
  seat's tier no longer counts towards the ceiling. (`DEF-4077`)
- **Every named clone hears that its box lock is off.** The banner's off-note
  rode the dispatcher's `Mail:` line and a worker's `Orders:` line only, so a
  worker between assigns, or a plain `claude` in a second named clone, ran its
  tier unlocked and was never told. Such a session now gets the note as one
  `[INFO]` line under the banner's NOTES header, with no second copy where a
  line already carried it. (`DEF-4054`)
- **The census of pytest spawners reads the whole checkout and the key by its
  constant.** It walked five named roots and skipped a file that did not spell
  the key's literal. A spawner under any other root, or one that names the key
  through `LOCK_KEY` or the launcher's `BOX_LOCK_KEY` and drops the holder, now
  reds it. (`DEF-2034`)
