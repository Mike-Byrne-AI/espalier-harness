# Windows walk output routing — where the walk's findings live

**Status:** active
**Linked from:** `.gitignore` (the "Windows install-rehearsal field notes" block) ·
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

**Walk 4 (2026-09-26, the Windows host) — the publish leftovers, driven; both lanes spent
and the fold landed the same day (TP-458).** Its record is an orphan branch of the private
archive, `archive/walk4/windows-2026-09-26` (one commit, `66489edf`; history-free, so it
cannot merge by accident): `walk4/WINDOWS_WALK4_RECORD.md` is the digest, and one leg folder
per item (`twins/`, `def11/`, `def11-verify/`, `onexc/`, `guardmatrix/`, `walk2reread/`,
`selfhost/`, `statusline/`, `def12/`; 300 files) holds the exact commands, raw output and
scripts. Read it with `git fetch archive` and then
`git show "archive/walk4/windows-2026-09-26:walk4/WINDOWS_WALK4_RECORD.md"` (brace a variable
before the colon: a bare `$B:path` is a zsh modifier). The digest is appended to
`WINDOWS_FUSE_NOTES.md` as `# ★ WALK 4`, and its triage is `# ★ WALK 4 FILING MANIFEST` at
the tail of that file: the W4 → ledger id map (`DEF-927`..`DEF-937`), the `DEF-736` append,
the `DEF-12` → `DEF-935` re-key, the `LG-2` and `LG-14` strikes, and every NOT-a-row with its
reason. The two lanes' tables are `reports/task0-2026-09-26/lane1-head-redrive.md` and
`lane2-dedup.md` (gitignored, record-rooted). The leg folders stay on the branch: copying
two megabytes of JSON here would add a `RECORD_ROOTS` entry and a gitignore row for no reader.

**A Windows-only red is driven on the runner, not on a second walk (2026-09-24).** The local
tier structurally cannot read a host-relative row, and a walk costs the operator's own host and
a day of it. `.github/workflows/portability.yml` takes two dispatch inputs -- one runner and a
pytest selection -- so a `windows-latest` cycle over a narrowed set of node ids costs one leg,
about seven metered minutes: six narrowed cycles and then the whole suite as the oracle closed
sixty-one Windows rows without a host. Keep the walk for what a runner cannot be -- a dirty
machine, a real install, a live session -- and send everything else to the runner.


**Vocabulary:** the word is **walk**, never *rehearsal* — `grep -ri rehearsal` finds
`bench/`'s guard rehearsal, an unrelated thing. Take the worktree path from
`git worktree list`, never from a doc.

**`LG-2` was never the pointer, and it is struck (2026-09-26: walk 4 discharged its six owed
legs).** It sat in ledger §5 "Cannot be closed locally", whose preamble says "do not count
these toward the backlog", and `scripts/ledger_row.py repin` refused it (measured 2026-09-09):
three-cell shape, no probe, by design, since nothing local can measure a Windows host. This
file is the pointer. Two things that row carried and no walk discharged were re-homed at the
strike: the dirty-machine install fixture is `DEF-937`, and the walk-1 overclaim warning is
the paragraph below.

**Walk 1 (2026-08-18) overclaims; read its verification pass, not its findings.** The first
walk's own findings section in `WINDOWS_FUSE_NOTES.md` overclaims in fourteen enumerated
places; read the `# VERIFICATION PASS` appendix instead, and note that its `doctor` em-dash
item was itself downgraded there from "Proven" to mechanism-confirmed-not-driven. The
meta-finding is not Windows: five of the thirteen findings are platform-independent and
surfaced only because that was the first install driven on a dirty machine (a prior espalier
on `PATH`, a `master` default branch, a pre-existing `.claude/`, spaces everywhere, an
operator who pastes verbatim); the CI-shaped generalisation, a dirty-machine install fixture,
does not exist and is `DEF-937`.

**A walk record's tags are as of its walk date.** `WINDOWS_FUSE_NOTES.md` and the `WALK3_*` sheets
mark a row fixed or unfixed when the walk ran, and nothing re-reads them afterwards: on 2026-09-26
eight rows were relayed as still open that the landed changelog archive shows fixed and the live
ledger no longer carries. Before relaying anything from a sheet as open, ask both questions -- is it
a live row in `task-packs/FORWARD_LEDGER.md`, and does the archived changelog carry its fix line.
The sheets record what a walk saw; the ledger is the list of what is still owed.


**Both files are ignored on purpose.** `classify_release_path` calls these paths
`public` and `.gitignore` doubles as the release-exclusion boundary, so un-ignoring one
would ship field notes to adopters on the next `git add -A`. Durability comes from
`RECORD_ROOTS` instead. A new artifact needs **both** edits; the snapshot test uses a
synthetic fixture and will not catch a miss.
