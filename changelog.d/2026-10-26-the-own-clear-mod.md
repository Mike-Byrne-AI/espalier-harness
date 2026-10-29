### Added

- **The own-clear: a seat's window clears itself once the handoff lands, refuses
  the compaction that would write the summary again, and re-primes from the seat
  brief.** A Claude Code mod (a plugin of function hooks) under
  `tools/cc/mods/own-clear/`, loaded by `tools/cc/seat.py launch` through
  `--plugin-dir` first in claude's arguments (`--no-mod` leaves it out; the
  launch line says which), which also exports `ESPALIER_OWN_CLEAR=1` to that
  session and never passes the own-clear's names in from its own environment.
  `tools/cc/ship.py handoff` gains a last act on every completing path: in a
  window that loaded the mod it arms `.espalier-state/own_clear.json` for the
  session id Claude Code exports to its tool shells, with HEAD, the seat and the
  re-prime brief (`seat.py::reprime_text`: the role brief with its loop line
  replaced by the note that a loop started there survived the clear, since it
  does); in any other window, or with no id in the environment, it arms nothing
  and says the window needs a `/clear` by hand; an arm that fails never fails
  the handoff whose push landed. At the end of the main loop's next turn, when
  the marker names the session, HEAD is still the marker's, no tracked edit is
  in flight and no plan is in progress, the mod runs the real `/clear` (a held
  clear names its wait on the status line; a refused one says so and is tried
  again); on the clear's SessionStart it reads the marker before handing the
  event on and, only when the marker names the session this process was in,
  marks it consumed and submits the brief as the first prompt of the new
  session (a marker another window armed is marked stale and re-primes
  nothing); a compaction asked for while the marker is armed and the clear can
  run is refused, and runs while the clear waits. Measured on 2.1.310
  (`bench/own_clear/drive.py`, a pty-driven session with the real writer:
  clear, re-prime and a refused compaction in 27 s; sixteen cases against the
  engine in `hooks/own-clear.test.ts`; the tool shell's session id tracks the
  session across a clear). No settings hook, skill or command body can clear
  or compact (`docs/SHARP_EDGES.md`). Self-host seats only this lane: the
  mod's files are outside the vendored deploy source, so an adopter tree's
  launch says it has no mod; the banner's `Orders:` line on a clear
  (DEF-4052's other half) and the Windows seats' measure are later lanes.
