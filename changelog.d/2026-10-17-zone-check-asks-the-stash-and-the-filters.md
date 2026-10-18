### Fixed

- **A stash pop, and a clean file git brings back under the checkout's own
  filters, no longer read as unaccounted changes.** The check after each
  shell call asked only `HEAD` and the `HEAD` of its previous check, never
  the stash, so the pop of a stash made before the session, of a file of 4 MiB
  or more, of a new file (and its stash), or of a stashed deletion told Claude
  to stop. It now records each checkout's newest stash and asks it for what a
  pop or an apply brought back, a deletion it recorded and what a new stash
  took, wherever the stash changed the path; a stash that merely carries a
  file unchanged vouches for nothing. A file whose working copy is not its
  committed form under the checkout's filters (a small git-lfs file, a big
  CRLF text under `core.autocrlf`) matched one way only; on the report path it
  is now hashed the other way too, and a match either way is committed
  content.
