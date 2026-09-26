# Windows walk output routing — where the walk's findings live

**Status:** active
**Linked from:** `task-packs/FORWARD_LEDGER.md` `LG-2` · `.gitignore` (the "Windows install-rehearsal field notes" block) ·
                 `scripts/record_snapshot.py` `RECORD_ROOTS`

The Windows install **walk** writes two large local-only files at the checkout root
(`~/Developer/espalier/`, the archive tree, until the 2026-09-25 cut; since the seed,
`~/Developer/espalier-harness/`, the public checkout, where all five were copied), and no
committed surface named them until this entry.

- **`WINDOWS_FUSE_NOTES.md`** — the field record, append-only.
- **`WALK2_FINDINGS.md`** — a partial distillate plus the de-dup and filing analysis.

**Read in this order; never start at line 1.** `WINDOWS_FUSE_NOTES.md`
`# ★ WALK 2 FINAL INDEX`, then `# ★ POST-INDEX ADDENDUM` (which overrides it), then
`WALK2_FINDINGS.md` — whose `# ★ ROUTING` block maps each journal finding number to its
`W2-*` id and lists three older instructions that are now dead.

**Walk 3 (2026-09-14) — ALL LEGS 0-5 DRIVEN, and it has NO second file.** Its
whole record is inside `WINDOWS_FUSE_NOTES.md`: start at `# ★ WALK 3`, then read
sections **E–L** at the end. The instrument itself is now durable in its own
right: **`WALK3_RUN_SHEET.md`** (the corrected Leg 5 and every pre-registered
oracle), **`WALK3_BRIEFING.md`** and **`WALK3_PREFLIGHT_FINDINGS.md`** were
mirrored out of the walk worktree on 2026-09-14 and given BOTH durability edits
(`.gitignore` lines 235-242, `RECORD_ROOTS`); verified by `git check-ignore` and
by `record_snapshot.walk_roots()` returning all three. They had lived ONLY as
untracked files in the worktree (`git worktree list`), one `git worktree remove`
from gone. Section `L` of the field record keeps a verbatim copy of the sheet and
briefing as belt-and-braces redundancy — it is a MIRROR, not the source. The walk's candidates were filed on 2026-09-14: **`# ★ WALK 3 FILING MANIFEST`** at the
tail of the field record is the triage (class, who sees it, severity, and every
NOT-a-row with its reason) and carries the `W3 → ledger id` map — nineteen rows
`DEF-794`..`DEF-812` (one new class, §C52), three repins (`DEF-664`, `DEF-623`,
`DEF-755`), three strikes (`DEF-729`, `DEF-734`, `DEF-748`) and the `LG-2` update.
Read the manifest before re-deriving anything from sections E–K. `K.5` records two
findings raised and RETRACTED against the source — do not re-file those.

**The manifest's triage was two read-only lanes over the same candidate sheet,
and both earned their cost.** One re-drove every candidate at HEAD with its own
probe: it refuted `W3-P9` outright (both fixtures read HARD; the zone check is
a prefix test), corrected two mechanisms the record's own single-issue tables
had misread, and widened three censuses. The other asked only *who already owns
this* and found the one shipped sentence that was false plus a finding nothing
had owned across two walks (`F-10`). Spend both on walk 4: a HEAD lane cannot
see an unowned finding, and a dedup lane cannot see a wrong mechanism.

**Vocabulary:** the word is **walk**, never *rehearsal* — `grep -ri rehearsal` finds
`bench/`'s guard rehearsal, an unrelated thing. Take the worktree path from
`git worktree list`, never from a doc.

**`LG-2` cannot serve as the pointer.** It sits in ledger §5 "Cannot be closed locally",
whose preamble says "do not count these toward the backlog", and `scripts/ledger_row.py repin` refuses it
(measured 2026-09-09): three-cell shape, no probe — and by design, since nothing local
can measure a Windows host.

**Both files are ignored on purpose.** `classify_release_path` calls these paths
`public` and `.gitignore` doubles as the release-exclusion boundary, so un-ignoring one
would ship field notes to adopters on the next `git add -A`. Durability comes from
`RECORD_ROOTS` instead. A new artifact needs **both** edits; the snapshot test uses a
synthetic fixture and will not catch a miss.
