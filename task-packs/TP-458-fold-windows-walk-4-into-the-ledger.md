# TP-458 — Fold Windows walk 4 into the ledger, the walk record and the two doc sentences it falsified

## Status

- Version target: before the `0.8.0b2` cut (the walk's major finding is a guard leak; its two
  doc sentences are shipped text that is now false)
- Change type: ledger / docs / record durability. **This pack changes no engine code**: it
  files the rows, strikes the legs the walk closed, and flips the four shipped sentences the
  witness decided. Every code fix it names is a row's own later work.
- **Kind: PACK**
- Ledger rows: `LG-2`, `LG-14`/`LG-3` and `DEF-12` (all §5, three-cell, hand-edited);
  `DEF-736` (a sibling site); nine candidates `W4-P1`..`W4-P9` to be filed as rows or recorded
  as not-rows (up to eleven ids, `DEF-927`..`DEF-937`, after the lanes' fold and splits);
  `CLO-46` (referenced, unchanged); `DEF-884`, `DEF-415f`, `DEF-911` (named as siblings,
  unchanged).
- Authored 2026-09-26 on the public tree at `9177a358`; the walk ran the engine at `550314e`,
  which differs from HEAD only by two ledger-and-pack merges (PR #8, PR #9). Corrected the
  same day at `0bb7cac5` after the pack-artifact review (0 BLOCK, 3 WARN, 2 NIT) and Task
  0-A's two lanes (records: `reports/task0-2026-09-26/lane1-head-redrive.md` and
  `lane2-dedup.md`, gitignored, record-rooted). Engine identity re-asserted at that HEAD:
  `git diff --stat 550314e 0bb7cac5 -- tools/cc/hooks espalier tools/cc/*.py` is empty, and
  the vendored deploy source is byte-identical to the source hooks across 41 files.

---

## Motivation

The Windows walk 4 record exists and the ledger does not know it. It lives on an orphan
branch of the private archive, `archive/walk4/windows-2026-09-26` (one commit, `66489edf`),
as `walk4/WINDOWS_WALK4_RECORD.md` (the digest, 17.6 KB) with one leg folder per item
holding the exact commands, raw output and scripts. Read it from this checkout with:

```bash
git fetch archive
git show "archive/walk4/windows-2026-09-26:walk4/WINDOWS_WALK4_RECORD.md"
```

(Brace a variable before the colon: a bare `$B:path` is a zsh modifier.)

The record's own instruction is that the Mac checkout folds it into `WINDOWS_FUSE_NOTES.md`,
the record branch and the ledger. Walk 3 was folded on 2026-09-14 through a **filing
manifest** built by two read-only lanes, one re-driving every candidate at HEAD and one
asking who already owns it, then filed through the ledger verbs; `memory/windows-walk-output-routing.md`
says to spend both lanes on walk 4, because a HEAD lane cannot see an unowned finding and a
dedup lane cannot see a wrong mechanism. This pack is that fold.

**What the walk decided, as its digest records it (DRIVEN on the host unless marked):**

| Item | Result |
|---|---|
| The PR #6 PowerShell allow twins in a live session | PASS, by a single-variable control (twins stripped: DENIED; restored: RAN) |
| The wheel path on the host, spaced path | PASS, attested |
| `DEF-11`, the tracked-settings case | PASS on `pip` + `init --wire-hooks` |
| The 3.12+ `onexc` arm of the read-only delete | PASS on 3.12, 3.13, 3.14 (MEASURED) |
| The PowerShell guard matrix under a paren-bearing root | PASS, matches macOS on every paren shape (MEASURED) |
| Walk 2's absolute-path ALLOWs under a spaced root | nothing falsified; the premise was wrong (53 of 55 calls ran under an unspaced root) |
| `DEF-756` on the self-host clone | not exercisable on self-host by design; PASS on a consumer substitute |
| Leg 1-I, the statusline shim under PowerShell without Git Bash | **FALSIFIED**: blank |
| `DEF-12`, UNC and `\\?\` prefixes | **CONFIRMED**: 9 of 11 spellings pass every hook and reach the file |
| `LG-14`, private vulnerability reporting | PASS (`{"enabled":true}`) |

**Two method findings the record names, and this pack carries into the catalog:** the
pre-registered witness (`git status` through the PowerShell tool, no prompt) passes with or
without the twins, because Claude Code auto-approves a read-only `git status`; it could not
fail. And a headless `claude -p` in an untrusted workspace silently drops every project
`permissions.allow` entry (stderr says so), and trust does not inherit from a trusted parent.

**Measured at authoring on this Mac, 2026-09-26, so the pack does not carry the walk's
beliefs about platform scope:**

- `W4-P2` is **not Windows-specific.** Through `tests/test_write_guard.py::run_bash_guard`
  under temp roots named `repo`, `R&D`, `a;b` and `repo (x86)` (the authoring drive, re-driven
  by lane 1 on 2026-09-26 with hard and soft separated): the zone find-delete and the xargs
  carrier are allowed under `R&D` and `a;b` and walled under the other two; the repo-root
  delete degrades from a wall to a nudge under the two metacharacter roots, so the walk's
  Windows observation is cross-platform; the controls wall everywhere. The reader cuts the
  quoted operand at the metacharacter. The PowerShell `cmd /c del` arm (`W4-P3`) is allowed
  under the same roots through `tests/test_write_guard.py::run_guard_tool`, the same cut in
  the second shell tool, so it folds into this row rather than filing as its own nit. The
  stop class the walk names appears at 14 sites:

  ```bash
  git grep -n -F '[^|;&\n]' -- tools/cc/hooks | cut -d: -f1 | sort | uniq -c
  ```

  (13 in `tools/cc/hooks/_bash_patterns.py`, 1 in `tools/cc/hooks/_speedbump.py`; the
  authoring spelling of this command escaped the pipe, matched nothing at HEAD, and its
  silence read as the class being gone), beside `_bash_patterns.py::iter_rm_invocations`
  and `::_FIND_DELETE_RE`. `DEF-884` (live, major, the same module) is the same shape, a
  capture class that does not match the real operand; it keeps a tail where this loses one,
  and whether the two are one class is the fix row's question, named in the text.
- `W4-P5` is **Windows-only in symptom.** `python3 -m espalier init . 0<&-` in a throwaway
  repo here exits 0 and deploys the full tree. The class is real everywhere: an `ast` walk
  over `espalier/*.py` finds 41 `subprocess` calls; 39 pass no `stdin=` (two pass `input=`,
  which pipes it), 83 of 85 across the shipped runtime (lane 1 reproduced the walk's number).
- The Windows statusline render on this host reads `"${CLAUDE_PROJECT_DIR}/tools/cc/statusline.cmd" python`
  (`espalier/cli.py::_statusline_command` with `posix=False`): the bare quoted head the walk
  showed PowerShell parsing as an expression.
- `DEF-798`, which the walk marks REFUTED at HEAD, has no live row here; nothing to strike.
- Three candidates the walk framed as Windows findings drove here on macOS (lane 1,
  2026-09-26): `W4-P6` (the bare-init epilogue's two sentences), `W4-P7` (a fresh self-host
  clone saves a plan with no hooks while settings wire ten events; day-zero doctor warns
  with exactly 12 missing, 2 of 2 clones) and both halves of `W4-P8` (a manufactured UI
  surface: init names the recommendation and the saved plan omits it; `upgrade --execute`
  emits the same 38 drift lines as init). `W4-P4` measured here: 24 rules render, the ten
  twins occupy the last ten slots, and the doctor line shows three names plus "+21 more".
- `§C4` ("route every target-extraction regex through one flag-, quote- and delimiter-aware
  positional helper"), the class `W4-P2` belongs to by charter, was retired at the 2026-09-20
  rebuild (Appendix A5). The walk's own sibling `DEF-794` is not live either.

**Cross-pack coordination.** `TP-457` (DRAFT, authored the same day) also edits
`task-packs/FORWARD_LEDGER.md`, `task-packs/LEDGER_PROBES.json` and
`tests/test_check_ledger_probes.py`, and adds its own `docs/SHARP_EDGES.md` entry. The ids
are disjoint (`TP-457`: `DEC-33`, `DEF-923`, `DEF-924`, `DEF-450`, `DEF-393a`, `DEF-874`,
`DEF-885`, `DEC-28`, `DEF-324c`, `DEF-625`, `SUP-2`; this pack: `LG-2`, `LG-14`/`LG-3`,
`DEF-12`, `DEF-736`, `DEF-927`..`DEF-937`). Order: `TP-457` lands first and regenerates the
ledger regions; this pack files on the regenerated ledger. Never run both packs'
`generate_ledger_regions.py --write` on one tree between commits (one writer per shared
state).

---

## Scope (in)

- **0** — Task 0: the two triage lanes over the digest, the two operator calls (`LG-2`'s fate,
  `DEF-12`'s scope), and the filing manifest they produce. Licensed to end the pack.
- **1** — Durability: append the digest to the local `WINDOWS_FUSE_NOTES.md` as `# ★ WALK 4`
  with the archive-branch pointer, and record walk 4's location and shape in
  `memory/windows-walk-output-routing.md`.
- **2** — The ledger, through the verbs where the row shape allows and by content anchor
  where it does not: file the manifest's rows into `task-packs/FORWARD_LEDGER.md` and
  `task-packs/LEDGER_PROBES.json`; strike `LG-14`/`LG-3` at both of its copies (the §1A row
  and the §5 row) and hand-edit the §1 heading's operator-action count, which no generator
  owns; strike or rewrite `LG-2` per 0-B, re-homing its two undischarged carries; re-key
  `DEF-12` to a measured member row; append the sibling site to `DEF-736`; amend the §C20
  preamble (a closed list of six corrections) for its three new members; baseline any
  text-keyed doc probe in `tests/test_check_ledger_probes.py` with its reason.
- **3** — The four shipped sentences the witness decided: two in `docs/QUICKSTART.md` (the
  twins are witnessed; the statusline under PowerShell without Git Bash is known blank, not
  unwitnessed); the read-only-delete entry in `docs/SHARP_EDGES.md` ("the Windows attribute
  itself is the walk's to witness": witnessed on 3.12 to 3.14); known-limit 1 of
  `docs/sharp-edges/protected-zone-path-equivalence.md` ("pending a scoped Windows-host
  follow-up": walk 4 is that follow-up, and `DEF-935` carries its result).
- **4** — The catalog: one entry in `docs/SHARP_EDGES.md` for the witness that cannot fail
  and the headless trust trap, written beside `DEF-415f`, whose §C40 text asks for exactly
  this sibling entry.
- **5** — Red-team, the recall tier (a corpus edit), the landing.

## Scope (out)

| Deferred | Reason |
|---|---|
| Every code fix the rows name: the quote-aware stop class, `stdin=` at 39 of 41 engine sites (83 of 85 runtime-wide), the statusline head and `_statusline_command`'s docstring (which still says the shell behaviour is "the walk's to witness": an engine file, so `DEF-929`'s fix corrects it), the `cmd_init` write order, `doctor`'s rule slice, the init epilogue, the UNC and `\\?\` normalisation, a Windows-only `rmtree` test | Each is its own row's work with its own earn-the-red; a fold pack that also fixes reads as landed when it is not. |
| `CLO-46` (8.3 short names declined as evasion) | Stays declined. `W4-P9` corrects the sharp-edge sentence that overstates the limit; it does not reopen the model question. |
| The `DEF-12` scope question's *answer* | The operator's call in 0-C; the pack carries the recommendation and files under whichever answer is given. |
| The walk's leg folders (2+ MB of JSON) | Durable on the archive's orphan branch; the digest names them. Copying them here adds a `RECORD_ROOTS` entry and a gitignore row for no reader. |
| Walk 2's original 94 rehearsal rows | Unrecoverable; the host overwrote `bench/rehearsal-results.json` on 2026-09-14. Recorded, not owed. |
| The three §5 non-Windows rows `DEF-312a`, `BS-1`, `INV-25` | Not Windows work; untouched. |

⚠ **Scope-out is a claim.** The first row asserts every code fix is separable from the fold.
`W4-P9`'s doc correction is the one that tempts, since the fix is one sentence; it stays a row
because the sentence's claim (the guard refuses 8.3 names) was measured on one host only.

---

## Task 0 — Verify (may end this pack)

### 0-A The two lanes (dispatched together, read-only, one message)

**Lane 1, HEAD re-drive:** for each of `W4-P1`..`W4-P9` and the `DEF-12` measurement,
re-derive the anchor at HEAD by symbol, drive what can be driven on this host (the two
drives above are the pattern; the guard candidates go through `run_bash_guard` and
`tests/test_write_guard.py::run_guard_tool` on fresh temp projects), draft a probe per row
that prints its `open_value` now, and grade severity with the ledger's vocabulary. Refute
where refutable. The walk's `W4-P3` is explicitly unverified; the lane says whether it can be
driven here or must carry `why_not`.

**Lane 2, dedup:** for each candidate, ask only *who already owns this*: every live row, every
struck row on the record branch, `§4`..`§7`, the not-rows of the walk-3 manifest (`K.5` records
two findings raised and retracted; do not re-file those). `W4-P2` against the retired `§C4`
and `DEF-794`; `W4-P4` and `W4-P6` against `§C20`; `W4-P7` against `W2-6` (same symptom,
different cause, per the digest); `W4-P8`'s second half against `DEF-736`.

**Oracle:** the two lanes' tables agree on a filing manifest with, per candidate: ledger id
or NOT-a-row, class, severity, who sees it, population, a one-line claim, the probe, and the
evidence pointer into the archive branch. Its shape is the walk-3 manifest's
(`WINDOWS_FUSE_NOTES.md` `# ★ WALK 3 FILING MANIFEST`).

**Refuting result:** a candidate that lane 1 refutes outright (as `W3-P9` was), or one lane 2
finds already owned, is recorded as NOT-a-row with the reason; that is the normal outcome for
some of the nine, not a failure. The pack ENDS if lane 1 cannot reach the archive branch or the
digest's leg folders are missing (the fold would then rest on prose), or if the engine under
test cannot be shown equal to HEAD's hook tree for the guard rows.

**Exit:** stop and re-raise with the lanes' tables.

**Measured 2026-09-26, both lanes ran** (tables at `reports/task0-2026-09-26/`). Lane 1:
11 of 11 confirmed at HEAD, 0 refuted; four carry a `why_not` for a Windows-only half
(`W4-P3`'s real-shell reach, `W4-P9`'s 8.3 walls, `DEF-12`'s file reach, `W4-P5`'s
`WinError 6` symptom, its class measured here); one severity moved (`W4-P3` up, into
`W4-P2`'s class); three candidates framed as Windows findings drove on macOS; the population
of the `onexc` citation nit is two sites, not one; two more shipped sentences are
witness-decided. Lane 2: 8 new, 1 append (`DEF-736`), 1 re-key (`DEF-12`), 2 folds
(`W4-P3`, `W4-P8`'s first half) and 3 not-rows (`W4-M1`, which `DEF-415f` asks to be written
beside; `W4-M2`; nothing collides with walk-3's `K.5` retractions), plus seven corrections to
the proposed filing, all folded into 2-A. Neither pack-ending condition fired: eight leg
folders (300 files) present, engine diff empty. **The pack predicted a refutation; none
arrived.** Every correction is to severity, scope or population, not existence, and that is
recorded here rather than manufactured.

### 0-B `LG-2`'s fate (operator)

Walk 4 discharged the six owed legs the row lists. Lane 2 read the row in full: it also
carries two things no leg discharged, the **dirty-machine install fixture** (an unbuilt
CI-shaped generalisation of the Windows install rehearsal, which the memory file does not
hold) and the walk-1 fourteen-places overclaim warning (only partly held in the memory
file). Its remaining role is the pointer to where the walks' output lives, and
`memory/windows-walk-output-routing.md` already holds that (the row's own text says it
cannot serve as the pointer), but that file opens with a `Linked from: ... LG-2` backlink no
gate reports (`DEF-649`), so any strike edits it too. **Default: strike it, with the two
carries re-homed first**: the fixture filed as its own row (`DEF-937`, §C0, MAINTAINER, nit)
and the overclaim warning written into the memory file in full; the closing text names the
six legs, the `DEF-756` reword, leg 1-I's replacement by `DEF-929`, the two re-homings and
the memory file as the pointer. Alternative: rewrite it in place as the pointer row, keeping
the two carries where they are.

### 0-C `DEF-12`'s scope (operator)

The walk confirms that nine of eleven UNC and `\\?\` spellings pass `write_guard` on Write,
Edit, Bash and PowerShell and reach a protected file, that `resolve()` keeps the prefix form
so the in-repo test fails and `_protected_zones._is_protected` sees the raw spelling, that no
audit record is written, and that `post_write_check` does not catch it downstream. The digest
attaches the scope question: `CLO-46` declined 8.3 short names as evasion outside the threat
model (`STANDING_PRINCIPLES` §2), and these spellings are the same shape of question.

**Recommendation: a mistake scenario, not an evasion.** A repository on a mapped network
share is presented to every tool as a UNC path, and Windows long-path support presents
ordinary deep paths with the `\\?\` prefix; an adopter there types nothing unusual and every
write into a protected zone is allowed. Under that reading `DEF-12` leaves §5 as a measured
member row (`DEF-935`, below) with a fix shape, and the §5 row is struck as re-keyed
(Appendix A4). Under the evasion reading it moves to §6 beside `CLO-46` with the walk's
measurement recorded. Lane 1 measured the chokepoint here: all eleven prefixed spellings
pass `_hook_utils.py::normalize_path` with the prefix intact and read unprotected, both
controls read protected; only the file reach is Windows-only. **Refuting result for the
recommendation:** none available on this host; it is a model call.

---

## Relevant memory

Recent pattern, measured this session: the last two packs' reviews found their majors in
the repair, not the finding, and one reviewer's reasoned platform claim was refuted by
driving it. For this fold, expect the lanes to move severities and to refute at least one
candidate; a manifest with nine rows filed as proposed would be the surprise. (Measured
2026-09-26: severities and populations moved, one candidate folded, one row split, none
refuted.)

| Entry | Where |
|---|---|
| Catastrophic `rm` hard-deny parses flags + target, it does not regex a fixed order | `docs/SHARP_EDGES.md` |
| A Long-Latent Issue That Just-Now Bites Is a Class | `docs/SHARP_EDGES.md` |
| Path Normalization on Windows | `docs/SHARP_EDGES.md` |
| Hook authoring | `memory/hook-authoring.md` |
| A probe's silence is not a null | `memory/a-probes-silence-is-not-a-null.md` |
| Gates the targeted proofs never show | `memory/four-gates-the-targeted-proofs-never-show.md` |
| Windows walk output routing (the fold method, the two lanes, the vocabulary) | `memory/windows-walk-output-routing.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "<topic>"` with the topics
`windows walk record fold into the ledger`, `a pre-registered witness that cannot fail
oracle`, `guard operand cut at a metacharacter root name` and `subprocess stdin closed handle
invalid`; re-run them rather than trusting this list if the pack has been sitting.

---

## Implementation

### 1-A Durability *(mechanical)*

```bash
git fetch archive
B=archive/walk4/windows-2026-09-26
{ printf '\n\n# ★ WALK 4 — 2026-09-26 (digest; the leg folders live on the archive branch %s, commit 66489edf)\n\n' "$B"; git show "${B}:walk4/WINDOWS_WALK4_RECORD.md"; } >> WINDOWS_FUSE_NOTES.md
python3 -c "import sys; sys.path.insert(0,'scripts'); import record_snapshot as r; print(r.walk_roots())"
```

`WINDOWS_FUSE_NOTES.md` is gitignored and already in `scripts/record_snapshot.py::RECORD_ROOTS`,
so the next handoff's snapshot carries the digest to the record branch; no new root and no
new gitignore row. Then add a walk-4 block to `memory/windows-walk-output-routing.md`: the
branch, the digest path, the orphan shape (history-free, cannot merge by accident), the
`git show` spelling, and the manifest's location once 2-A writes it.

### 2-A The manifest, then the verbs *(the manifest is Task 0's output; the verbs are mechanical)*

Write the manifest as `# ★ WALK 4 FILING MANIFEST` at the tail of `WINDOWS_FUSE_NOTES.md`,
walk-3 shape. Then, **sequentially, unpiped, texts through the Write tool with every pipe
escaped, `--dry-run` before each verb**:

- `ledger_row.py file` for each manifest row (class, severity, population and audience from
  the manifest; probe driven at filing).
- `ledger_row.py repin DEF-736 --text-file` appending the `upgrade --execute` sibling site.
- Hand edits by content anchor for the three-cell rows: strike `LG-14`/`LG-3` at both copies
  (the §1A `5 ○` row and the §5 row) and change the §1 heading's "1 operator action" and
  its lead sentence to the live count (the region generator covers the headline, the §2
  header, class counts, member lines, Appendix-B strikes, the probe roster and the two axis
  tables, never §1's prose); strike or rewrite `LG-2` per 0-B and edit the memory file's
  `Linked from` line; strike `DEF-12` as re-keyed to its member row and add the Appendix A4
  crosswalk line; amend the §C20 preamble's "six independent corrections" for the three
  members this pack adds (the generator fixes the member count, never the preamble).
- `generate_ledger_regions.py --write`, then `--check`.

**The filing, as the lanes left it** (ids are the next free, `DEF-927`..`DEF-937`, measured
free tree-wide on 2026-09-26; each row's evidence pointer is the leg folder the digest names
on `archive/walk4/windows-2026-09-26`):

| walk id | proposed | class | severity | who | claim, one line | authoring-time evidence |
|---|---|---|---|---|---|---|
| `W4-P2` + `W4-P3` (folded: the same cut in the PowerShell tool, driven here twice) | `DEF-927` | §C0, re-opening retired §C4's claim; names `DEF-884` (live, same module, same capture-class shape) as the sibling whose class question is the fix row's | **major** | ADOPTER, a root named like `R&D` | `&` or `;` in the project root name cuts the quoted operand at the metacharacter: the zone find-delete and the xargs carrier are allowed, the repo-root delete degrades from a wall to a nudge, on POSIX and Windows alike; 14 stop-class sites plus `iter_rm_invocations`; 26 to 27 of 222 deny rows on the host | DRIVEN here (POSIX) and on the host |
| `W4-P5` | `DEF-928` | §C0 | minor | ADOPTER on Windows | `init` with stdin closed dies at `analyze.py::detect_git_conventions`'s `git log` with `[WinError 6]` and a half-deployed tree; 39 of 41 engine `subprocess` sites pass no `stdin=` (83 of 85 runtime-wide); `cli.py` claims `0<&-` is safe | MEASURED here (POSIX exits 0; the census), DRIVEN on the host |
| `W4-P1` | `DEF-929` | §C0 | minor | ADOPTER on Windows without Git for Windows | `_statusline_command` renders a bare quoted head with no fallback (the POSIX render carries one); Claude Code's PowerShell branch reads it as an expression and blanks the line; the schema has no `shell`, so `init` must detect Git Bash the way Claude Code does and pick the form; the docstring's "the walk's to witness" goes with the fix | DRIVEN on the host via the live executor; the render form measured here |
| `W4-P7` + `W4-P8` first half, carrying `W2-6` | `DEF-930` | §C0; `DEF-911` shares the consumer | minor | MAINTAINER | `espalier/cli.py::cmd_init` writes `reports/harness_config.json` before `deploy_harness`, so a fresh self-host init saves `"hooks": []` and omits the recommendation it just printed; day-zero doctor warns with exactly 12 missing. Second cause of the symptom walk 2 called `W2-6` (verdicted new 2026-09-08, never filed): `_refresh_fingerprint_derivatives` is reached from `cmd_fingerprint`, `cmd_upgrade` and `cmd_install_ci`, never `cmd_init` | DRIVEN here (2 of 2 fresh clones, a manufactured UI surface) and on the host |
| `W4-P4` | `DEF-931` | §C20 (preamble amended) | nit | ADOPTER | the quickstart says doctor names the twins the file lacks; `run_doctor_check` prints three rules and "+N more", the ten twins occupy the last ten of 24 slots, so no `PowerShell(` rule is ever named | DRIVEN on the host; MEASURED here |
| `W4-P6` | `DEF-932` | §C20 (preamble amended) | nit | ADOPTER, every platform | on the unwired path the epilogue says hooks are not active, then that the SessionStart hook will load context automatically | DRIVEN here and on the host |
| `W4-P9` | `DEF-933` | §C20 (preamble amended) | nit | MAINTAINER | `docs/sharp-edges/protected-zone-path-equivalence.md` known-limit 3 says 8.3 names cannot be handled; the host refused them. **Claim narrowed at filing:** the sentence's claim is that the mapping cannot be computed statically, and a refusal that comes from path resolution on the host leaves that true; read `guardmatrix/evidence.md` §Aside for which side refused, and file the sentence's false *implication* (that an 8.3 spelling passes), or record NOT-a-row if the resolver did the work | MEASURED on the host; the sentence read here |
| the `onexc` proposal | `DEF-934` | §C0 | minor | MAINTAINER | the read-only-delete arm has no CI witness although `windows-latest` runs; `os.chmod` sets the real read-only attribute on 3.12 to 3.14, so a Windows-only test can pin it. Re-filed on a changed basis: walk 3 recorded it NOT-a-row (`W3-P22`) and `docs/SHARP_EDGES.md`'s read-only-delete entry carried the obligation; the attribute is now witnessed | MEASURED on the host |
| the `tests/test_rmtree.py` skip-reason nit | `DEF-936` | §C31 | nit | MAINTAINER | the skip reason cites "the sibling row above" at two sites, each first in its class, and no such row exists; baselined in `_TEXT_OVER_OWN_SUBJECT` | READ here, two sites |
| `DEF-12`, measured | `DEF-935` | §C0 | **major** | ADOPTER on a UNC share or a long-path prefix | nine of eleven UNC and `\\?\` spellings pass every hook and reach a protected file, no audit record; `_hook_utils.py::normalize_path` keeps the prefix form so the in-repo test fails (all eleven read unprotected here) | DRIVEN and MEASURED on the host, the chokepoint measured here; filed only under 0-C's mistake reading |
| `LG-2`'s dirty-machine install fixture | `DEF-937` | §C0 | nit | MAINTAINER | the CI-shaped generalisation of the Windows install rehearsal `LG-2` owed and no leg built; filed only under 0-B's strike | READ in the row |

Each row's probe is the lane's, driven before the verb; a doc-keyed probe that must read its
own subject (`DEF-931`, `DEF-933`, `DEF-936`) is baselined in
`tests/test_check_ledger_probes.py::_TEXT_OVER_OWN_SUBJECT` with the reason, the `DEF-874`
shape. Not-rows recorded in the manifest with their reasons: `W4-M1` (written beside
`DEF-415f` in 4-A), `W4-M2` (the catalog), `W4-P3` and `W4-P8`'s first half (folded).

### 3-A The four sentences *(the witness decides; fix shape, untested against the doc contracts)*

`docs/QUICKSTART.md`, the Windows section's lead sentence: replace "except the
`PowerShell(...)` allow twins below, which are rendered and tested but not yet witnessed in
a live Windows session" with the witnessed fact (2026-09-26, a single-variable control in a
live session). The statusline bullet: replace "under PowerShell with no Git Bash installed it
is unwitnessed — a blank statusline there is cosmetic, not a broken harness" with "known
blank there (`DEF-929`); cosmetic, hooks unaffected". `docs/SHARP_EDGES.md`, the
read-only-delete entry: "the Windows attribute itself is the walk's to witness" becomes
"witnessed 2026-09-26 on 3.12 to 3.14 (`DEF-934` owns the CI test)".
`docs/sharp-edges/protected-zone-path-equivalence.md`, known-limit 1: "low-priority, pending
a scoped Windows-host follow-up" becomes the measured result with the date and `DEF-935`
(known-limit 3 in the same file is `DEF-933`'s and is not touched here). Then:

```bash
python3 -m pytest tests/test_onboarding_doc_honesty.py tests/test_portability_contract.py tests/test_quickstart_tier_counts.py tests/test_quickstart_doctor_example.py tests/test_surface_support_matrix.py -q -p no:cacheprovider
```

Refuted if a content contract pins the old wording; then the contract moves with the fact,
never the other way.

### 4-A The catalog entry *(one entry; the recall corpus)*

`docs/SHARP_EDGES.md`: "A pre-registered witness must be able to fail". What it is: a
witness chosen for convenience (`git status`, no prompt) that the platform auto-approves,
so it passes with the feature absent; measured 2026-09-26, it passed with and without the
twins. How you hit it: any permission-rule witness that uses a read-only command. How to
avoid it: witness with a command the rule alone admits, and run the single-variable control
(rule stripped, then restored). Beside it, the headless trust trap: `claude -p` in an
untrusted workspace drops every project allow rule and says so only on stderr; trust is per
exact path and does not inherit. The entry sits beside the catalog gap `DEF-415f` names
(§C40: the three entries whose absence makes each review round re-derive the same lesson),
and its text cites that row so the two resolve to each other.

### 5-A Red-team

`code-reviewer` and `failure-mode-reviewer` in snapshot clones, one message, edits frozen.
Most likely wrong, in order: a severity carried from the walk's proposal without the lane's
grade; a probe that closes on the paperwork of its own fix; a strike text on a §5 row that
loses the pointer role `LG-2` carried; the `DEF-12` re-key leaving a citation that dead-ends.

---

## Affected symbols

### Changed-semantics

- (none -- this pack changes no engine or hook code, and its only test edit is baseline entries in `tests/test_check_ledger_probes.py::_TEXT_OVER_OWN_SUBJECT`, no assertion; the rows it files name the code their fixes will touch)

### Renamed

- (none -- nothing is renamed)

### Added-paths

- (none -- the digest is appended to a gitignored local file already in `RECORD_ROOTS`)

### Removed-paths

- (none -- nothing is removed)

## Affected literals

- `LG-2`
- `LG-14`
- `DEF-12`
- `DEF-736`
- `not yet witnessed`
- `unwitnessed`
- `the walk's to witness`
- `pending a scoped Windows-host follow-up`
- `W4-P`

---

## Reach

Members derived by: the digest's "Proposed ledger actions" and its `W4-P#` table, checked
against `python3 scripts/check_ledger_probes.py --json` and `grep -n '^| \`<id>\`' task-packs/FORWARD_LEDGER.md`
at HEAD (the three §5 rows are live three-cell rows with no probe).

| Item | Status | Evidence |
|---|---|---|
| `LG-14` `LG-3` | **CLOSED**, both copies | `{"enabled":true}` read back on the host; the advisory link redirects to login; the §1 heading count edited by hand |
| `LG-2` | **CLOSED** (default, carries re-homed to `DEF-937` and the memory file) or rewritten as the pointer | six owed legs discharged by walk 4; two carries no leg discharged; 0-B decides the shape |
| `DEF-12` | **RE-KEYED** to `DEF-935` under 0-C's mistake reading; **moved to §6** under the evasion reading | measured mechanism either way; the chokepoint measured here |
| `DEF-736` | **RE-PINNED**, not closed | the `upgrade --execute` sibling site appended (`cmd_upgrade --execute` calls the same `deploy_harness` narrator `cmd_init` does) |
| `W4-P1`, `W4-P2`, `W4-P4`..`W4-P7`, `W4-P9`, the `onexc` proposal, the `test_rmtree.py` citation | **FILED** as rows (lanes confirmed 2026-09-26) | ids above; `W4-P9`'s claim narrowed at filing |
| `W4-P3` | **FOLDED** into `DEF-927` | lane 1 drove it here twice: the same cut, the second shell tool |
| `W4-P8` | **SPLIT**: first half into `DEF-930`, second half into `DEF-736` | the digest's own sentence names both; both halves driven here |
| `W2-6` | **CARRIED** into `DEF-930` | verdicted new 2026-09-08 and never filed; its cause is live at HEAD |
| `DEF-884` | **NOT REACHED** | named in `DEF-927` as the sibling; whether the two are one class is the fix row's question |
| `DEF-415f` | **NOT REACHED** | 4-A's entry is the sibling its text asks for; the row stays open on its own oracle |
| `DEF-798` | **NOT REACHED** | refuted at HEAD by the walk; no live row |
| `CLO-46` | **NOT REACHED** | stays declined; `DEF-933` corrects the doc sentence only |
| The pre-registered witness (`W4-M1`), the headless trust trap (`W4-M2`) | **NOT A ROW** | method findings; they land in the catalog (4-A) and in the quickstart sentence (3-A) |

---

## Pass criteria

- The manifest exists at the tail of `WINDOWS_FUSE_NOTES.md`, every `W4-P#` appears in it
  exactly once with a ledger id or a NOT-a-row reason, and `python3 -c "import sys; sys.path.insert(0,'scripts'); import record_snapshot as r; print(r.walk_roots())"`
  still names the walk files.
- Every filed row: `python3 scripts/check_ledger_probes.py --id <id>` reads STILL_OPEN with a
  driven probe; no row is filed with a probe that was not driven.
- `python3 scripts/check_ledger_probes.py --strikes` exits 0; the struck rows' probes are
  gone; `python3 scripts/generate_ledger_regions.py --check` converges.
- The `DEF-12` citation resolves after the re-key: the Appendix A4 line names `DEF-935`, and
  `CLO-46`'s text still says the tracked residuals sit under the row it names, updated.
- The four sentences are true as written and the doc contracts listed in 3-A are green.
- `LG-14` appears in no live row, the §1 heading's operator-action count equals its live §1B
  rows, and `memory/windows-walk-output-routing.md`'s `Linked from` line names no struck row.
- **Strength, not text:** no severity below the walk's proposed grade without the manifest
  stating the lane's reason; no `_TEXT_OVER_OWN_SUBJECT` baseline entry without a reason
  beside it; no §5 row struck without its closing text naming where each of its owed items
  went.
- `python3 scripts/proof_tier.py --run` reads the recall tier (`docs/SHARP_EDGES.md` and
  `memory/` are corpus) and passes; `python3 scripts/check_handoff_landing.py` reads clean.

---

## Files touched

- **New:** none tracked. The manifest and the digest land in the gitignored `WINDOWS_FUSE_NOTES.md`.
- **Modified:** `task-packs/FORWARD_LEDGER.md`, `task-packs/LEDGER_PROBES.json`,
  `tests/test_check_ledger_probes.py` (baseline entries with reasons), `docs/QUICKSTART.md`
  (and its asset copy if the asset-docs row in `espalier/mirror_registry.py` carries it),
  `memory/windows-walk-output-routing.md`, `docs/SHARP_EDGES.md`, `WINDOWS_FUSE_NOTES.md`
  (local, gitignored, `RECORD_ROOTS`).
- **Deleted:** none.
- **Also modified:** `docs/sharp-edges/protected-zone-path-equivalence.md`, known-limit 1
  only (3-A; known-limit 3 stays `DEF-933`'s).
- **Unmodified on purpose:** every engine, hook and test file the rows name (`espalier/cli.py`,
  `espalier/doctor.py`, `espalier/analyze.py`, `tools/cc/hooks/_bash_patterns.py`,
  `tools/cc/hooks/_hook_utils.py`, `tests/test_rmtree.py`); `cc/GOAL_OWED.json` (the
  `DEC-33` item stays); the archive branch.

---

## Sub-task ordering

1. **0-A, 0-B, 0-C** — the two lanes (ran 2026-09-26; tables at `reports/task0-2026-09-26/`),
   then the two operator calls. Checkpoint: the manifest table complete, both lanes' reports
   read, the calls written into the manifest header.
2. **1-A** — durability. Checkpoint: `walk_roots()` names the file; the memory block reads
   the archive branch.
3. **2-A** — the verbs, sequential; the hand edits; the regions. Checkpoint: `--strikes` exit
   0, `--check` converged, each filed id STILL_OPEN.
4. **3-A, 4-A** — the sentences and the catalog entry. Checkpoint: the doc contracts green.
5. **5-A** — red-team, one fix batch, the recall tier, the landing check, the commit flow
   (branch, PR, auto-merge; no marker path is touched).

## Estimated effort

| Sub-task | Budget |
|---|---|
| 0-A | done 2026-09-26 (both lanes ran; their tables reconciled into 2-A) |
| 0-B, 0-C | 10 min of the operator's reading |
| 1-A | 15 min |
| 2-A | 2 h (up to eleven filings with driven probes, five hand edits, one repin) |
| 3-A, 4-A | 40 min |
| Red-team, fix batch, tier, landing | 1.5 h |
| **Total** | **about 4.5 h** (the line items sum to it; the authoring total understated its own items) |

---

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:

## Sharp-edge entry to add

Carried by 4-A: "A pre-registered witness must be able to fail" with the headless trust
trap beside it. The entry exists because the witness this repo pre-registered for PR #6 was
the one command the platform auto-approves, and it read PASS on the control engine that had
no twins at all.
