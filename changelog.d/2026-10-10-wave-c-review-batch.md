### Fixed

- **The per-change records hold up on a real adopter tree and under
  parallel merges.**
  - **A kept older loader** no longer takes the whole post-write check down:
    the Session Log prune catches what such a loader raises and says why it
    did not run, and a missing loader beside a written row is said.
  - **The Session Log cap binds the merged tree.** Each lane prunes its own
    checkout and GitHub's merge runs no resolver, so seats handing off
    together could land one over the cap and turn the main branch red on a
    change that touched nothing; the bound is now the cap plus the other
    seats' lanes in flight, and the next row written prunes back.
  - **`/handoff` reads a row by its git status:** an edited earlier row is no
    longer taken as this session's new one.
  - **The landing check** takes a row as the lane's own only when no merge
    base has it, so a row that came in through the other side of a
    criss-cross merge no longer stands in for the lane's.
  - **Another tool's `changelog.d/`** (scriv, towncrier) is no longer read as
    this harness's records: its setext underlines are not called conflict
    markers, and a conflict on one of its files is the merge's, not refused.
  - **Pointers** in the cheat sheet, the command tables, the resume index,
    two agent bodies and the reflect skill name the Session Log's own files.

### Changed

- **Changelog fragments are an opt-in:** a lane's changelog file under
  `changelog.d/` is named only where `espalier.toml` sets
  `changelog_fragments = true`; elsewhere the entry goes under
  `[Unreleased]` in `CHANGELOG.md`, as before.
- **This repository's Session Log table is folded into its files** under
  `memory/session-log.d/`, and the section is a pointer. The record merge no
  longer evicts a row of the frozen table to keep the file under its cap,
  and `espalier memory prune` on a folded section names the fragment prune
  instead of failing on a missing table.
