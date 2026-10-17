### Fixed

- **A large protected file brought back to its committed content, and a stash
  pop of an edit made before the session, no longer read as unaccounted
  changes.** The check after each shell call never reads a file of 4 MiB or
  more, so it could never match one against git and reported every pull or
  checkout of a model or data file; git now hashes such a file through the
  checkout's own filters (up to 1 GiB of them in one call) and the check
  compares the result with the committed one, without reading the file or its
  committed copy itself. A path git accounted for now also remembers the
  content it moved from, so the pop of a stash that took an edit back to the
  committed state is quiet, as the documentation already said.
