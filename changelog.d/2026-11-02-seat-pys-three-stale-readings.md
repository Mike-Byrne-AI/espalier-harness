### Fixed

- **`seat.py retire` refuses when it cannot fetch the mail.** A failed fetch
  at its first read, or at the read confirming its releases, used to leave
  the retire working from the refs as last fetched, so a job the dispatcher
  gave the seat since was never seen and the seat's worktree went with the
  job still live. Both reads now refuse and keep everything; `--no-fetch`
  retires on the refs here and fetches at neither read.
- **A cleared or compacted seat is not told to start a second loop.** The
  SessionStart banner's `Orders:` line ended "then start the worker loop" on
  every start, while a seat's interval `/loop` lives as long as the session's
  process and so keeps ticking through a `/clear` and a compaction. On those
  two sources the line now says the loop survives and to start no second one
  where `CronList` lists it; a
  fresh start or a resume still names the loop to start.
- **The box lock's default path no longer depends on `TMPDIR`.** The launcher
  sets `~/.espalier/espalier-box.lock` (the temp directory's only where no
  home can be told), so two seats launched from contexts whose temp
  directories differ lock one file. The suite's plugin makes that folder when
  it is missing, and `<lock path>.log` now records every gated run (taken,
  waited, inside its holder, or unguarded, with why), so an empty log means no
  gated run came. A seat launched before the move still has the temp
  directory's path in its environment; the plugin reads that one path as the
  new default and says so, so it locks what a relaunched sibling locks.
