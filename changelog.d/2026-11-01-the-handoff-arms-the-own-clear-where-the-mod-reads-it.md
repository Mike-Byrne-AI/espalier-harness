### Fixed

- **A handoff run from another checkout of the clone arms the own-clear where
  the window's mod reads it.** `tools/cc/ship.py` armed the own-clear marker in
  the checkout the verb ran in, while the own-clear mod reads it in the
  checkout the session was started in and holds the clear while that
  checkout's HEAD is not the marker's; so a lane handed off from a linked
  worktree armed a marker nothing read, and the window was never cleared (the
  dispatcher's, on 2026-11-01). The handoff, `ship.py arm` and the catch-up's
  re-arm now find that checkout the way the mod does
  (`ESPALIER_OWN_CLEAR_ROOT`, else the session's entry in Claude Code's
  session registry, by its id or its window pid, when it is a checkout of the
  same clone) and arm it at its own HEAD with its own seat's brief, the
  lane's checkout named in a held brief. A session checkout holding commits
  no remote has, a tracked edit or a plan in progress is not armed from
  another checkout, and the line says why: a marker there would read to the
  Stop hook's handoff gate as that checkout's own lane handed off. A session
  the registry cannot place is armed where the verb runs, as before, and the
  line says so.
