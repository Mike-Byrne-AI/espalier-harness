### Fixed

- **The own-clear's re-prime no longer tells a window whose lane merged that
  HEAD moved.** On the clear's SessionStart the mod read the marker before
  handing the event on but read what the old window left in flight after it,
  and the project's SessionStart hook beneath catches the checkout up (a lane
  branch GitHub deleted at the merge moves onto the base), so every re-primed
  seat whose lane had merged was told `HEAD moved since the handoff -- work in
  the old window after its handoff` and spent its first turn on a clean tree
  (the dispatcher window, 2026-10-30). `tools/cc/mods/own-clear/hooks/register.ts`
  reads in-flight beside the marker, before the hand-on, only for a marker armed
  by the session this process was last in, and the brief carries that read
  after the hooks beneath have run. The kit gains a case whose hooks beneath
  move HEAD; `tests/test_own_clear.py` pins the handler's read order with the
  line comments stripped (red on the read moved below the hand-on, on a second
  read after it, and on a read awaited after it) and runs the kit wherever
  `claude` is on PATH with the pass count derived from the kit file, since no
  CI cell installs `claude`.
