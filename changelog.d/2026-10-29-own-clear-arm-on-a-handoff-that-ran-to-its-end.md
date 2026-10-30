### Fixed

- **The own-clear arms on every handoff that ran to its end, and a queued clear
  is given its turn.** `ship.py handoff` armed the own-clear marker only after
  its push step returned 0, so a handoff refused on a red base, a push whose
  follow-up refused, or a lane opened by hand left a window past the threshold
  ask with no clear (win, win-2 and air-work for 17.5 h on 2026-10-29). The
  handoff now arms on a refusal the window is done with -- the base red, the
  lane whole and unpushed here; or a step after a landed push -- with the
  refusal in the marker (`landed`, `outcome`) and the lane to land first
  appended to the re-prime brief, and still refuses (exit 1); a refusal the
  window must fix first (a dirty tree, a lane behind its remote, a shared
  checkout) arms nothing; `ship.py arm [--why ...]` arms by hand after a
  hand-open, over a lane that is on origin and no marker already armed. The
  Stop hook's handoff gate lets a Stop through over a marker armed at HEAD,
  so a held handoff is not asked for twice. The mod writes `clear_asked_at`
  into the marker at the ask and, measured 2026-10-30 (a loop tick queued as
  the handoff's turn ended ran first, and the engine ran the queued clear
  after it), never asks again while the session stands: it names the queued
  clear and what each later turn left in flight on the status line, lets a
  compaction through once two turns have passed, and tells the new window on
  the clear's SessionStart what the old one left in flight. The threshold ask
  names `ship.py arm` for a lane opened by hand. `seat.py launch
  --own-clear-log [PATH]` sets the mod's log for the session (bare:
  `.espalier-state/own_clear.log` under the seat's checkout; a relative path
  is resolved where it was typed).
