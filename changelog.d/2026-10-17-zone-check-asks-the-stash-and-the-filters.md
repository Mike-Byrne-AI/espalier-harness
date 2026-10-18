### Fixed

- **A stash pop, and a clean file git brings back under the checkout's own
  filters, no longer read as unaccounted changes.** The check after each
  shell call asked only `HEAD` and the `HEAD` of its previous check, never
  the stash, so the pop of a stash made before the session, of a file of 4 MiB
  or more, of a new file (and its stash), or of a stashed deletion told Claude
  to stop. It now records each checkout's own newest stash -- one whose reflog
  line names the branch the checkout has, since `refs/stash` belongs to the
  whole repository and another worktree's stash vouches for nothing -- and
  asks it for what a pop or an apply brought back, a deletion it recorded and
  a new file a new stash took, wherever the stash changed the path. In the
  call that first sees a new stash, what it took that no check saw (a change
  written and stashed in one call) reports then. A small git-lfs file, whose
  committed form is its pointer, is now hashed through the checkout's filters,
  and a big CRLF text under `core.autocrlf` with none, on the report path only;
  a match either way is committed content.
