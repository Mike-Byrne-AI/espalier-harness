### Fixed

- **A worktree with no integrity manifest is told to refresh it, not to re-run
  `init`.** A linked worktree checks out tracked files only, so it has no
  `.espalier/integrity.json` even where the main checkout does, and the banner's
  `Integrity:` line said `run espalier init .`, which would redeploy the harness
  into the worktree. It now says to run `<python> -m espalier integrity refresh .`
  from the worktree's root (a module run, so that tree's own engine hashes its
  hooks). A submodule, whose `.git` is a file too, keeps the init advice.

### Added

- **SessionStart names a checkout whose test interpreter imports another
  engine.** In a checkout holding the engine source, an `Engine:` line appears
  when `python3` (else `python`) imports `espalier` from an installed copy or
  another checkout, so a test tier there would exercise that engine instead of
  this tree's (measured 2026-10-12: a worktree seat's full tier ran the main
  checkout's engine in every CLI test). One bounded probe, about 20 ms, after
  the network reads; silent on an adopter tree and when the two agree. The
  test session itself now stops before any test runs on the same mismatch,
  naming a `.venv` of the checkout's own as the fix.
