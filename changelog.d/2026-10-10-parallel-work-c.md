### Added

- **Session Log rows and changelog entries are one file per change, so two
  lanes' handoffs no longer conflict at the merge.**
  - **Session Log:** `/handoff` writes its row to a new file under
    `memory/session-log.d/`, named by
    `python tools/cc/_record_fragments.py new session-log` from the clock and
    the seat (`<YYYY-MM-DD>-<HHMMSS>-<seat>.md`). The `## Session Log` table in
    `ESPALIER_MEMORY.md` is frozen: no writer adds to it and the fragment prune
    never touches it, until a later fold moves its rows into files.
  - **Changelog:** a lane writes its entries to its own file under
    `changelog.d/` (`new changelog` names it from the branch), read beside
    `[Unreleased]`; the release fold folds both.
  - **One loader:** `tools/cc/_record_fragments.py` reads each record in both
    forms, newest first by the date a row carries. The SessionStart digest,
    the handoff driver, the landing check, the tag-parity gate, the release
    check's stranded-entry count and the changelog's own gates read through
    it, and a census test holds every other reader of the two records to it
    or to a stated reason.
  - **Cap:** the newest 30 Session Log files are kept; a write past that
    archives the oldest to `docs/session-archive.md` and deletes their files,
    and the deletions ride the handoff's commit.
  - **Merge:** both directories join the record files the conflict-marker
    checks read. A conflict inside one is two writers on one name, and the
    record merge refuses it by name rather than guessing.
  - **Older deploys:** where the loader is not deployed, `/handoff` prepends
    to the table as before, and every reader still reads the table.
