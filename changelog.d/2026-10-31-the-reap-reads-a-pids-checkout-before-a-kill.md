### Fixed

- **The SessionStart `Loose:` line names the checkout each PID's working
  directory is in.** Sessions in two worktrees of one clone share one process
  table, and a run another session detached on purpose (`nohup ... & disown`,
  a proof tier) has PID 1 for its parent like any orphan. The line now reads
  the working directory of each PID it names, only when it names one (the
  `/proc/<pid>/cwd` link on Linux, one `lsof` elsewhere, capped at two
  seconds), and says which checkout of this clone it is in: this checkout,
  the main checkout, or a worktree by its path, or `cwd outside this clone's
  checkouts`, `cwd deleted` or `cwd unread`. A PID in another checkout is
  named and left out of the one-paste `kill`, and the line says to ask the
  session working there. `lsof` is taken from absolute `PATH` entries only.
  (`DEF-4070`)
