### Fixed

- **The own-clear mod's kit runs green on a Windows seat.** On Windows the
  engine hands each `fs.*` hook the path as it resolved it on the host (the
  kit's `/scratch/.espalier-state/own_clear.json` arrives as
  `C:\scratch\.espalier-state\own_clear.json`), and the kit's in-memory world
  keyed its files by the POSIX literal the test chose, so every lookup missed,
  the mod read no marker, and 27 of the kit's 32 cases red on main's own tree
  (2.1.311, 2.1.312 and 2.1.314 alike; the five that passed expect nothing to
  happen). Every Windows seat's full tier carried the red through
  `tests/test_own_clear.py`, and a lane editing the mod from one had no kit
  oracle. The world's files are now one store whose `get`, `set`, `has` and
  `delete` each key the path one way (separators read as `/`, a leading drive
  letter dropped), so the engine's spellings and the test's literals meet in
  it; no case changed, and on a POSIX host the key is the path. The mod itself
  was never affected: its real clear consumed the marker and submitted the
  brief on the same box. (`DEF-3016`)
