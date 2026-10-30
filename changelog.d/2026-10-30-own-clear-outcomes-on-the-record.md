### Fixed

- **The own-clear's outcomes are on the record, and a queued clear re-primes
  the window it clears.** The own-clear mod asked the engine for the clear at a
  turn's end and put a rejected ask on a status line alone, with its log off on
  every seat: the dispatcher window re-asked a refused clear 41 times over ten
  hours on 2026-10-30 and nobody saw it until the asks line's age gave it away.
  The same day a worker window's queued clear was dequeued 5 ms after the loop
  tick's turn ended, while that turn's `turn.complete` was still resolving the
  session id, so the mod took the new id as its last session, read its own
  marker as another window's at the clear's SessionStart, marked it stale and
  re-primed nothing. The mod now writes every outcome into the marker
  (`.espalier-state/own_clear.json`): a refusal's text, time and count (the
  state staying `armed`), the turns a queued clear has waited and when the
  engine took the ask with the session still standing (so a clear taken and
  never run reads apart from a queued one and a refused one), and the two ids
  a stale marking compared. Under a pending clear a turn's end, and a
  `session.start` should an engine raise one at a clear, move the last
  session only to the asked one; the clear's SessionStart reads the marker as
  its own when it is armed for the last session, for the session this process
  asked to clear, or, after a reload reset the module, when it carries its own
  ask; and it clears the pending ask once the marker is consumed or stale. The
  log's writes are chained and the file capped (past 256 KB the newest 500
  rows). The SessionStart banner gains an `Own-clear:` line over a marker
  armed for another session (the count and the engine's reason, a clear taken
  and never run, or one never asked), consumed into this session after
  refusals, or marked stale at the clear into this session (no brief was
  submitted; the ids compared), reporter only; the prompt router tells a
  window whose own asked clear was refused to say so in its reply's first line
  and that the window needs a `/clear` by hand, above an active plan too;
  `seat.py launch` logs the mod by default (`.espalier-state/own_clear.log`
  under the seat's checkout; `--own-clear-log PATH` moves it,
  `--no-own-clear-log` leaves it unset). Seven kit cases, each red first on
  the unchanged mod; the refusal's mechanism stays unmeasured (two
  single-factor reproductions on 2.1.314 -- a Bash call moved to the
  background at its timeout, a Stop the settings hooks blocked once -- each
  resolved the clear), so its row stays open as the record until a refusal is
  caught with the record on.
