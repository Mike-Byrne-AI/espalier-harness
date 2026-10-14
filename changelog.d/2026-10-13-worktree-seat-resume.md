### Fixed

- **A fresh worktree session reads healthy in `/status` and `/context-load`.**
  A worktree checks out tracked files only, and Claude Code copies in what
  `.worktreeinclude` lists; the surface gate's result
  (`reports/cc_surface_gate.json`) is never among them, because it is a verdict
  about the tree it was written on. `tools/cc/session_resume.py` read its
  absence as damage, so every fresh worktree session's `/status` said
  `SURFACE: DEGRADED` and "rebuild or re-audit the CC surface", while the
  SessionStart banner in the same session said healthy (driven 2026-10-13 on a
  real worktree of this repository). A worktree is now judged against its main
  checkout: the gate result reads "not generated in this worktree yet", naming
  `/smoke` as what writes it (`/status` prints it on a `PENDING:` line), and an
  include entry the worktree lacks while its main checkout has it reads "copy
  `<main checkout>/<path>` here" rather than "rebuild". A tracked file missing
  in a worktree is still damage ("rebuild or re-audit"), never a copy. A
  worktree with no copied settings file, which read as a fresh clone and was
  told to run `espalier init .` (redeploying the harness into it), is now
  degraded and told to copy the main checkout's, since a session there loads
  none of the hooks. `espalier recover` and `doctor` read the same assessment.
- **`espalier integrity verify` passes in a fresh worktree.** The integrity
  manifest is per checkout and gitignored, so a worktree has none until it
  writes one; verify, which `/preflight` runs, exited 1 there as though the
  manifest had been removed, and a worktree without its settings copy was told
  to run `init`. It now prints the banner's own note (no manifest in this
  worktree, and the `-m espalier integrity refresh .` that writes one), adds
  the settings copy when that file is missing too, and exits 0. A main checkout
  whose manifest is gone still exits 1. `/preflight` Step 3 says so.

### Changed

- **The banner, `/status` and `integrity verify` read one worktree one way.**
  The three places that ask "is this a linked worktree, and of which main
  checkout" now share one rule, held to each other by a test that drives all
  three on every shape git writes: a relative gitdir is read against the
  worktree, and a gitlink whose admin directory is gone (an export that carried
  it, a worktree whose main checkout moved) is not a worktree, so the banner's
  `Integrity:` line gives that tree the main-checkout reading the other two
  give it. A worktree of a bare repository has no main checkout to judge
  against and reads as it did before.

The fix copies neither record into a worktree: a copied gate result or manifest
would show the main checkout's verdict as the worktree's own.
