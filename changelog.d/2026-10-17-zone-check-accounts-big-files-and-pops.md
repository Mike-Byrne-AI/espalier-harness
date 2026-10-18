### Fixed

- **A large protected file brought back to its committed content, and the
  pop of a stash of an edit made before the session, no longer read as
  unaccounted changes.** The check after each shell call never reads a file of
  4 MiB or more, so it could never match one against git and reported every
  pull or checkout of a model or data file; git now hashes such a file through
  the checkout's own filters (up to 1 GiB of them in one call, within the 5 s
  that one call's git asks share) and the check compares the result with the
  committed one, without reading the file or its committed copy itself. The
  content a stash takes from a protected file during the session is now known,
  so the pop of a stashed edit to a file under 4 MiB is quiet; the pop of a
  larger file, a stashed new file or deletion, and a stash made before the
  session still report, as the check's limits say.
