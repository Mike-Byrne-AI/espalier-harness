### Added

- **A seat starts with a composed first message instead of a pasted one.**
  `python tools/cc/seat.py brief <seat>` prints the message a seat starts with:
  a worker's names its dispatcher, the two reads to start with (`/inbox`, then
  `/inbox board`) and its jobs, and ends with the worker loop; the dispatcher's
  names its duties and ends with the board loop. The `dispatcher` line of
  `espalier.toml` picks the form, and what the seat's checkout holds picks which
  guide it points at, so the message never names a file the checkout does not
  have. `seat.py launch <seat>` passes it to `claude` as the session's first
  prompt, after the arguments you give it; `--no-brief` launches without it,
  and `--print` shows it in the command line. Driven on Claude Code 2.1.301: a
  first message whose last line is a `/loop` line starts that loop with no
  second message, and the loop survives `/clear`.
- **The SessionStart banner names a worker seat's orders.** On a seat whose
  `espalier.toml` names another machine as the dispatcher, and whose local mail
  refs hold live assigns for it, an `Orders:` line after `Mail:` gives the
  seat's name, its jobs and the first one's lane, its unread count, and the
  short form of its first message with the `seat.py brief` command that prints
  the whole of it. It reads the refs the mail line already read and starts no
  process of its own.

### Fixed

- **The banner's `Sessions:` line no longer names a closed window as a live
  sibling.** It counted every session marker touched in the last four hours, so
  a window closed hours ago read as a second session sharing the checkout. A
  marker now records whether Claude Code's session registry named its pid when
  it was written, and the line leaves out a sibling whose registry-named pid is
  no longer running. A marker whose pid the registry did not name (on Windows,
  the hook's fallback is an interpreter launcher that exits with the hook while
  the session runs on) stays named, because its exit says nothing.
  `ESPALIER_SESSIONS_DEBUG=1` names the left-out siblings too, each marked
  `pid gone`. The seat driver's marker fallback reads the same field.
