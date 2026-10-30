### Fixed

- **A mail send whose push outlives its timeout is read back before it is
  refused.** The channel's driver pushed this machine's ref under a bounded
  wait and, when the push outlived it, let the runner's timeout raise past the
  rollback: the refusal said nothing was sent, while the push may have landed
  (the dispatcher's assign did, 2026-10-30 14:25Z, a minute after a GitHub
  `Internal Server Error` had refused the first attempt) and the local ref was
  neither read back nor put back. A seat that trusted the refusal and sent
  again doubled the message (a re-sent assign restarts its job's clock), and a
  seat whose push had not landed was refused as a second writer at its next
  send. Now the runner tells a timeout apart from its other stops
  (`record_merge.TimedOut`, under `Unresolvable`), and after a push that
  outlived its wait the driver reads origin's tip for the ref back before it
  says anything: at the commit, the push landed, the send is counted and says
  so; unchanged, nothing landed, the ref is put back and the refusal says so;
  unreadable, the ref is put back (a local ref behind origin's is adopted at
  the next write) and the refusal names the commit to compare against
  `git ls-remote` before sending again. Any other failure of the push spawn
  puts the ref back too. A send and a park alike; the ship driver's pushes
  need no read-back, since a re-run re-pushes the same object.
