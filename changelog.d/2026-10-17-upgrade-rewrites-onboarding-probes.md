### Fixed

- **`upgrade` and `init` now bring an onboarding row's probe up to date.**
  The onboarding rows `init` files into the forward ledger kept the probe of
  the release that filed them, so a fix to how a row reads its file never
  reached an install made before it (an ONB-1 filed before 2026-10-11 kept
  reading the whole goal file). `upgrade` (even when the harness version is
  current) and `init` on an installed tree now re-pin each live row whose
  stored probe differs from this release's, through the ledger's own tool,
  and the dry run names each one first, along with any row another
  machine's claim would stop. A row this release's probe reads as already satisfied is
  named instead, on each run, with the command to strike it, and its stored
  probe is left as it was. A row you rewrote, or re-pinned with a probe of
  your own, is kept and named, with the re-pin that hands it back to this
  release's probe; a row you struck or deleted is left alone. Only the probe
  is refreshed, not a row's anchor or text.
- **`ledger_row.py repin` now names every field it changed.** Its stamp ends
  with `[changed: ...]` (for example `probe`, `open value`, `severity`), so a
  re-grade can be told from a new probe, and a second repin on one day keeps
  the first one's list.
