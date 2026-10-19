# Forward Ledger — Open Fixes, New Features & Future Investigations

_The single forward-work tracker. **Rebuilt 2026-09-20** to forward work only (the ledger-ships pack's §1-D, landed 2026-09-22): every
live row re-verified at HEAD by the 2026-09-20 adjudication; struck rows, session notes and the
closed history moved off this file. The pre-rebuild file -- every struck row and every session
note, verbatim -- is `task-packs/FORWARD_LEDGER_PRE_REBUILD_2026-09-20.md`, a RECORD SURFACE kept
on the maintainers' `record` branch and not shipped (the 2026-08-20 rebuild's record sits beside
it). Read it for WHY a row existed; read this file for WHAT IS TRUE NOW._

**Counts are derived, never stored here:** `python tools/cc/generate_ledger_regions.py --print` prints the live total, its split by population and by audience (counted apart on purpose, never as one number), and each class's live and closed members.

The file stores no count. Every total -- the live count and its split by population and by audience, each class's live and closed members, each numbered section's rows -- is derived from the member rows by `tools/cc/generate_ledger_regions.py --print` (a classed row inherits its class-index population and audience; a row in a class the index marks MIXED on an axis carries its own cell on that axis and repeats the class tag on the other -- §C0 is MIXED on both, and ten classes were MIXED on one as of 2026-09-20; `ledger_row.py` enforces the shape per axis), and `tests/test_generate_ledger_regions.py::TestTheLiveLedgerConverges` reds on a total written back in. Derived is not verified: the tool checks that every live row carries a token it knows and counts each once; whether the token is the RIGHT one is the judgement the row's author made, contestable with `tools/cc/ledger_row.py repin <id> --audience ... --reason ...`. Stored, the totals were the lines every two lanes in flight both rewrote: 82 of this file's 97 conflict blocks in the catch-up merges of the last 30 merged pull requests (2026-10-09). Typed by hand before 2026-09-08, the audience figure read 62 through 63 closures.

⚠ **This file is tracked since 2026-09-21: `git status` shows your edit and `git checkout` undoes it; the snapshots from its gitignored months are on the `record` branch.**
`scripts/record_snapshot.py` writes it to the orphan `record` branch at every handoff; restore a
lost version with `git show record:task-packs/FORWARD_LEDGER.md`. Verified 2026-09-02: the `record`
copy was byte-identical to the working file. **This corrects a warning that said "there is no git
undo", which stopped being true on 2026-08-31 when `record` landed.**
Edit by content anchor, never by replaying a line number — that rule stands on its own merit
(nine writers, shifting line numbers), not on the absent-undo claim that used to justify it.
Back it up before any structural change anyway: `record` is written at handoff, not per edit.

<!-- ledger-floors: sections=26 rows=74 -->

---

## The contract — what belongs in this file

- **All forward work lives here.** Do not spawn a rival tracker; update this file.
- **A row states a root cause, not a symptom.** If you are writing a row that fixes one site of a
  pattern, find its `§C` class and add it there — or open a new class. A hand-edited bandaid filed
  as its own row is how this file grew to fourteen topic buckets and 2,597 lines.
- **Stable ids are the citation handle.** `DEF-*`, `LG-*`, `INV-*`, `DEC-*`, `CLO-*` never change or
  get reused — 402 distinct (file, id) citations across `task-packs/` resolve by id. **Section numbers are not stable**;
  cite the id.
- **`§C` numbers are a fresh namespace.** The retired `§2.x`/`§3.x` numbers are mapped in Appendix A.
- **Strike a row when it lands** — the pack's own `## Landing` stanza is authoritative.
- **PRIOR TEXT is edited only to remove never-ship material** — a personal path, a
  private backup arrangement, a billing detail, a quoted person — never to change a
  claim; the verbatim original stays on the record branch, and the date and the rows go
  here. 2026-09-24 (Round 12, before the 0.8.0b1 seed): `DEF-840` and `DEF-856`.

### Carried forward verbatim from the pre-rebuild contract

_These four rules were rewritten away in the 2026-08-05 rebuild and restored after an audit found_
_the measurement missing. Rule 5 is the only thing in this file that says what its own row count_
_does and does not mean._

2. **Unlanded packs belong here.** ⚠ **This REVERSES a previous standing instruction,
   and the reversal is dated deliberately.** The operator had prohibited packs in the
   ledger; that prohibition was **withdrawn by the operator on 2026-07-30**. A
   drafted-but-unlanded pack *is* owed work, so `drafted-pack (TP-N)` and `owned: TP-N`
   rows are correct. `tests/test_forward_ledger_completeness.py::test_every_active_pack_is_ledger_tracked`,
   which reds on an active pack (the root or `Deferred/`) with no row, is therefore
   enforcing the right thing; `::TestOrphanDetection` is its earn-the-red on synthetic
   trees. (Corrected 2026-10-08: this line named the synthetic class as the gate.)
   **Sessions carrying the old instruction in memory will otherwise strike valid rows** —
   if you are about to remove a `drafted-pack` row because "packs don't belong here",
   this line is why you should not.

3. **`LANDED` is a transitional sweep marker, never a record.** It means *"this work is
   done — remove this row on the next pass."* The permanent record lives in
   `CHANGELOG.md` and the pack's own `## Landing` stanza. `TestLandedRowLingering`
   reddening on a `LANDED` row is the sweep signal firing correctly, not a defect to
   silence.

4. **Settled decisions do not belong here.** They live in `docs/RELEASE_DECISIONS.md`,
   whose format (*Decision / Why / explicit revisit trigger*) already carries reopen
   conditions. So *"it has a reopen condition, therefore it is forward work"* does **not**
   justify a ledger row — that reasoning would re-import every decision ever made.

5. **A non-zero count is health, not backlog — but the rate below is NOT the reassurance
   it reads as.** Every landed pack emits deferrals, so draining N packs *feeds* this file
   rather than emptying it. Calibrate against the dated baseline below, not against a
   feeling about the number.

   ⚠ **CORRECTED 2026-08-05 — the "~0.75 deferrals per pack" figure was a stock/flow error
   and is withdrawn.** It was computed as 41 standing rows ÷ ~55 packs. But this file holds
   only **open** rows — rule 3 removes struck ones — so rows ÷ packs measures the *residual
   after drain*, not emission. A stock divided by a flow cannot be a spawn rate.

   **Measured emission, hand-classified across all 159 packs in `Done/` (2026-08-05): 1.33
   new owed items per pack** — 77% above the withdrawn figure, and **above 1.0 in every
   era** (1.09 → 1.01 → 2.28 by chronological third). The id-counting method is confounded
   by a convention that only begins with the packs of early August 2026, so the hand-classified rubric is primary.
   Corroboration needing no classification at all: this file's own dated baseline moved
   **41 → ~137 definition sites over the 21 packs touched since 2026-07-31** — net growth
   *after* all drains.

   **What follows from a rate above 1.0:** the backlog is a divergent series and cannot be
   closed by working it. That is arithmetic, not pessimism — and it means **the count in
   this file can never be the signal that says "ready."** Two better instruments, both used
   in the 2026-08-05 assessment: (a) **adopter-facing defects fixed vs. introduced** per
   milestone — measured at roughly **6:1** over 2026-07-28 → 08-05, which is convergent;
   (b) the **blocker yield of the logic-bug population** specifically, kept separate from
   doc/registry hygiene. Reading three populations as one number is what made "we are
   nearly ready" unfalsifiable. **Both are computable now, not read from 2026-08-05:**
   `python3 scripts/ledger_trend.py` diffs this file's snapshots on the record ref
   (filed, struck, churn, net, split by audience and population, since every row
   carries both tags as of 2026-09-08), so the ratio is re-measured per window and
   the figures are deliberately NOT typed here. First run 2026-09-08: the whole
   08-31 -> 09-08 window is dominated by the 09-02 sweep that filed forty-odd
   already-owed rows in a day; read from the snapshot after it (`--from <that
   snapshot>`), replacement ran well under one row per backlog row drained.
   Re-run to re-measure. The rate itself is attacked at source by two landed packs of August 2026: one over
   pack authoring (the largest single emitter, ~33 line anchors/pack, ~1% guarded) and one
   over the codebase's hand-maintained surface.

**Baseline — measured 2026-07-31 at `4e8c809`.** An undated count becomes a false pin the
moment the file moves, so this one is dated and its method is stated: rows are counted at
their **definition site** (`- **DEF-n · …**`), not by id occurrences, because ids are
cross-referenced across sections and occurrence-counting inflates them.

| measure | value | method |
|---|---|---|
| `DEF-*` rows | **41** | definition sites; 61 raw occurrences — the difference is cross-references |
| `DEC-*` rows | **8** | `DEC-1`…`DEC-7`, `DEC-9`. `DEC-8` is **prose-only** — it is cited but has no row |
| `drafted-pack` | **24** | raw occurrences |
| `owned: TP-N` | **1** | at `DEF-398a` |
| `LANDED` **rows** | **0** | the mechanical definition (`_LANDED_TAG_RE`'s LANDED arm). 7 raw `LANDED` strings exist — all prose, a table cell, and the feature name `LANDED-nostamp` |
| rows carrying a strike marker | **0** | `~~` / `STRUCK` / `RESOLVED` all grep to zero — **nothing in this file is marked struck** |
| status-tag mix | `open` 17 · `idea-only` 8 · `drafted-pack` 3 · `dropped-but-deferred` 1 · untagged 11 | first code-span on the row |

**Second baseline — measured 2026-08-05 at `bb9726e`, same method.** The 07-31 table above is
**kept, not overwritten**: the delta between the two *is* the evidence for rule 5's corrected
emission rate, and overwriting it would destroy the only dated pin this file has.

| measure | 07-31 | 08-05 | note |
|---|---|---|---|
| `DEF-*` definition sites | 41 | **138** | 135 unique ids; 3 lines are duplicate definitions (`DEF-20` at least) |
| raw `DEF-` occurrences | 61 | **200** | site/raw ratio 0.67 → 0.69, i.e. **the method matches** — this is real growth, not a counting change |
| `DEC-*` definition sites | 8 | **15** | |
| `drafted-pack` | 24 | **29** | raw occurrences |
| all bolded-id definition sites | — | **225** | every family (`DEF/DEC/INV/CLO/LG/TP/EXP/…`) |
| packs in `Done/` | ~55 | **159** | `ls task-packs/Done/TP-*.md \| wc -l` |

⚠ **Roughly 33 of the 225 rows are already closed and still physically present** — all 21
`CLO-*` rows (§6 is a deliberate do-not-rediscover record, an *anti*-backlog), plus a handful of
`EXP-*` verdicts and discharged `LG-*`/`DEF-*` rows. **Any naive count of this file overstates
live work by ~15% before triage.** A 2026-08-05 falsification pass over 50 rows found **~12% of
checkable rows dead** (already fixed or premise falsified) and **~46% carrying at least one wrong
line number or count** — mechanisms held up far better than the numbers attached to them, which
is the same finding rule 5 records at the file level.

> **⚠ Two consequences of that last row, both learned the expensive way.** *(a)* Any
> instruction to *"remove the rows already marked struck"* has **no population** — and
> the rows that fit such a description by set-difference carry `open` / `in-progress`
> tags, i.e. **live work**. Executing it would delete live work from a file that had **no git
> undo** at the time (`task-packs/` was gitignored until 2026-09-21). *(b)* "30 live" is a **reading**, not a mechanical
> count; the tag mix above is what is actually measurable. Reclassify a row only against
> a mechanical check — the row's own claim re-run, never a re-reading of it.

**Editing rules.** This file is **tracked since 2026-09-21 (`git log -p` holds every committed state; the `record` branch holds the snapshots from before)** (see the
header — the "no git undo" this line used to assert has been false since 2026-08-31). Apply every
edit by **content anchor against the live file**, never by replaying a cited line number. Do not
run a parallel session that edits it. Nine packs currently write to it, so ordering
matters: this contract lands first, everyone else appends and strikes per it, and any
structural consolidation lands last — after every append — or it restructures a file that
is then appended to again.


- **Governing frame:** Espalier is a *workshop toolbelt, not a security boundary* — the threat model
  is operator/AI *mistakes*, and false-positives / workflow friction outrank closing bypass classes.
  And *direction ≠ magnitude*: a sound mechanism is not a measured effect until it is measured.

### How this file defends itself

_Three mechanisms, added by the 2026-08-20 rebuild, and a fourth on 2026-10-13. Each exists
because the corresponding failure was **measured** on this file, not anticipated._

**1. Derived counts — computed on read, never stored.** Every total this file used to carry
-- the live count and its split, the §2 heading's figures, each class's members, each numbered
section's rows -- is derived from the member rows when it is asked for, and none is written here.
Typed, they drifted: three sections once mis-stated their own member count at once (§C1 said "20
open, 9 closed" over 30 rows; §C2 "Members (19)" over 20; §C18 "Members (4)" over 6). Generated
into the file, they were the lines every two lanes in flight both rewrote, so they conflicted in
nearly every catch-up merge and neither side's number was right after it. Appendix B's strike
markers and the probe roster are still checked against the member rows. Strike, file and re-pin
rows with `tools/cc/ledger_row.py strike|file|repin`, never by hand: every verb drives the row's
probe first, writes both files atomically or neither, and converges the file.
**Never type a count here:**

```bash
python3 tools/cc/generate_ledger_regions.py --print   # every total, derived from the rows
python3 tools/cc/generate_ledger_regions.py --check   # anything disagreeing with the rows, a stored total included
python3 tools/cc/generate_ledger_regions.py --write   # remove a stored total
```


**2. Probes — every row can re-derive its own claim.** Each row's probe, one file per probe
under `task-packs/probes.d/` (`task-packs/LEDGER_PROBES.json` held them all until the fold of
2026-10-14, and still does on a tree that keeps one), holds a read-only one-liner plus the
value it prints *while the defect is open*.
Run them:

```bash
python3 tools/cc/check_ledger_probes.py
```

A row whose probe stops printing its `open_value` is a **STRIKE CANDIDATE** — re-verify by
hand, then strike. This replaces the nine-agent census that found 41 dead rows; the same
answer is now one command. ⚠ **The verdict is three-way on purpose.** A probe whose
`subject` file is missing reports UNRESOLVED, never STRIKE: an early cut of the runner read
"the probe stopped saying True" as "the defect is fixed" when the truth was "the probe lost
its subject". A wrong strike is expensive rather than fatal — the file was gitignored until 2026-09-21, but
`record` carries it (see the header) — and the three-way verdict stands regardless: re-discovering
a strike you cannot see is work, and UNRESOLVED is the honest answer when the probe lost its
subject. ⚠ **A struck row must also LOSE its probe.** The gate only required every live row to
HAVE one, so retired probes accumulated: on 2026-09-02, 14 of 198 pointed at struck rows and 10 of
11 "strike candidates" were that noise. `tools/cc/generate_ledger_regions.py` now reports the other
direction too.

**3. Symbol anchors over line numbers.** ~70% of the pre-rebuild `file:line` anchors no
longer landed on their mechanism (the 2026-08-05 pass measured 46% — the rot accelerates).
Anchors are now `file::symbol` or `file#heading` wherever one exists: forms this repo can
already validate, since `tests/test_doc_source_citations.py` AST-resolves the first and
`tests/test_md_heading_anchors.py` the second. **A bare line number is a last resort, not
the convention** — and it is the one anchor form nothing here can check.

**4. Rows as files — read through the view.** This repository sets `ledger_fragments = true`
in `espalier.toml`, so `tools/cc/ledger_row.py file` writes a new row as
`task-packs/ledger.d/<id>.md` (its class, its member row and its Appendix B index lines) and
its probe as `task-packs/probes.d/<id>.json`, and `strike` and `repin` edit a row where it
lives. Two lanes filing into one class, or striking two neighbouring rows, then touch
different files and merge clean; they used to meet on neighbouring lines of this file and on
the roster's tail, and GitHub read every such pair as conflicting until a catch-up (measured on
the real verbs: two filings after one anchor conflicted on the member row, its index row and
the roster). Since the fold of 2026-10-14 every §C class row and every probe lives in a file
of its own: the class tables below keep their header and rule and hold no row, Appendix B
holds no class row's index line, and the probes' former roster's prose is
`task-packs/probes.d/README.md`. A row file names its §C class on its first line, so the rows
outside the classes -- §1 and §3 to §6 -- stay in this file, and so do the Appendix B index
lines that remain (§4A's).
The ledger's tools read its **view** -- this file with the row files placed in it, built on
each read and never written back -- so this file alone shows no class row. A reader in prose
is held to the view only where it spells a record's file
(`tests/test_documented_claims.py::TestEveryDocNamingAFoldedRecordNamesItsFolder`), and a
reader in code more than one helper away by no check:

```bash
python3 tools/cc/_record_fragments.py ledger   # the whole ledger, as every tool reads it
python3 tools/cc/_record_fragments.py probes   # every probe, task-packs/probes.d/ as one roster
```

Here a verb refuses only on a problem its own write would leave, or one about a row it
touches; a problem the tree already carried about another row (a stray file beside the rows,
a second probe for one id) is printed as a note and the write goes ahead, and
`generate_ledger_regions.py --check` and this repository's CI gate hold the tree to every
problem. Files an operating system or an editor leaves (`.DS_Store`, a swap file, a `~`
backup) and a directory's README or CLAUDE.md are never read as rows. A tree that has not
opted in refuses on every problem, as the verbs always did.


## How to read a status tag

| Tag | Meaning |
|---|---|
| `owed` | Must happen before a confident OSS launch. |
| `drafted-pack` | A `TP-*` pack is written and execution-ready but has not run. |
| `idea-only` | Named and reasoned-about; no pack drafted yet. |
| `in-progress` | Partially built — one wave landed, the rest deferred. |
| `parked` | Deliberately held behind a named revisit trigger (stated in the row). |
| `open` | An identified defect with no pack yet (the default state of a §C member). |

---

## §1 — Launch gates

**The public cut happened on 2026-09-25 (`v0.8.0b1`); every block below is closed, §1B's step 6 last (the demo GIF, struck 2026-10-05); §1A's last row, the day-one defect, closed 2026-09-26 when walk 4 measured the setting on.** They are different work: §1A is code
and docs a stranger trips over on day one; §1B is the operator ritual that has to happen in order.

### §1A — a stranger hits these on day one

Each was verified to break someone who clones, `pip install`s, runs `fuse`, or follows the README.
`○` marks a row no local check can close.

| # | id | issue | site | root cause |
|---|---|---|---|---|
| 5 ○ | ~~`LG-14`~~ ~~`LG-3`~~ | ✅ **CLOSED 2026-09-26 — measured on 2026-09-26 (walk 4, `EVIDENCE-lead.md`): `gh api repos/Mike-Byrne-AI/espalier-harness/private-vulnerability-reporting` reads `{"enabled":true}`, and the advisory link in `SECURITY.md` and `config.yml` redirects an anonymous reader to GitHub login instead of a 404, so both halves of the row's condition are answered; struck at both copies (§1A and §5) by TP-458, and, this being the last §1A row, §1's heading and lead sentence were edited by hand because no generator owns them.** PRIOR TEXT: GitHub's private-vulnerability-reporting setting is an owed pre-flip operator action; until it is on, SECURITY.md's preferred `Report a vulnerability` link and config.yml's contact_link both 404. | `SECURITY.md:15` | — |

### §1B — the operator launch sequence (do in this order)

No code fix exists for any of these. **Order matters:** branch protection must follow the
check-run rehearsal (§C8) or every PR wedges on a status check that never reports; and the flip
must precede the PyPI publish, because `espalier init` prints a `blob/main` CHEAT-SHEET URL that
404s for every adopter while the repo is private.

⚠ **The stated order above is wrong until step 0 clears, and that is why this note lives here rather than
only in the row.** Measured 2026-08-15 (`DEF-582`/`LG-18`): every job of all five push-triggered workflows
at `42c8d83` failed in 2-4s with `steps=0` while Actions was unavailable, so CI is a no-op. That removes the
precondition of step 5 (§C8's rehearsal cannot establish a check-run name when no job starts), of step 4
(`refresh-externals` cannot run at all), and of the publish leg that steps 1 and 3 exist to reach
(`publish.yml`'s tag-push trigger fires into nothing). **Steps 2 and 6 — flip the repo public, record the
demo GIF — are the only two that do not depend on it,** together with the local half of step 1 (version
bump plus CHANGELOG fold). Do not read "4 of 6" as "mostly fine": step 5 done in this state wedges every
PR on main with certainty rather than as a `DEF-455` hazard.



⚠ **`DEC-31`, 2026-09-07 — the seed is unchanged; what happens after it is not: the public repo
becomes the development tree, and the forward work ships in it.** Decided after measuring the
alternative DEC-25 left open, a private layer for the untracked work: the record branch already
exists and the handoff already writes it, yet 31 of its 49 snapshots were unpushed on 2026-09-07
because the push is a separate step, so a second system had already failed silently. Under
DEC-31: (1) `scripts/build_release_archive.py` still emits the seed, and the fresh-repo reasons
in `memory/publish-from-a-generated-public-repo.md` stand unchanged, since they are about
history; (2) after the seed, development moves into the public repo, and this tree, renamed,
becomes a read-only private archive and the host of the record branch through a second remote;
(3) the forward ledger, its probes file and the active top-level packs are tracked and public,
rebuilt first to forward work only (`DEF-705`), while Done, Deferred, Merged, Scrapped, the
archive files, blueprints and reports stay untracked as regenerable history; (4)
`docs/known-findings.md` folds into the ledger (`DEF-706`); (5) the shipping boundary and the
codename gate move with it (`DEF-707`, `DEF-708`) and the DEC-25 texts are rewritten
(`DEF-709`). What must never ship is a short list, mostly mechanical: the dropped-disclosure
name (under Done only), the CI-outage story (two shipping docs carry it today), personal
paths, and any row written as a war story instead of a claim. The ongoing discipline is one the
memory directory and the failure-mode catalog already ship under: every row is written for a
stranger. Order: the adopter-facing lanes not gated on the Windows walk, the walk re-anchor
(`DEF-711`) and the walk, the §C5 trio, then §C51 and `DEF-709` at the start of the
release-repo phase, then the runbook.

| # | id | do this | site |
|---|---|---|---|
| 1 | ~~`DEF-536`~~ ~~`LG-1`~~ | cut `0.8.0b1` (pyproject is still `0.8.0a13`) | `pyproject.toml:7` |
| 2 | ~~`DEF-537`~~ `DEC-25` | ⚠ **re-shaped 2026-08-20** — not "flip this repo": generate the public tree and push it as the initial commit of a NEW repo (the DEC-25 decision: `memory/publish-from-a-generated-public-repo.md`) | `memory/publish-from-a-generated-public-repo.md` (decision) + `docs/RELEASE_CHECKLIST.md` §"First publish" (the executable steps, written 2026-09-02 — `DEF-632`) |
| 3 | ~~`DEF-459`~~ ~~`LG-4`~~ | claim the PyPI slug + configure the `pypi` environment | `task-packs/FORWARD_LEDGER.md:253` |
| 4 | ~~`DEF-530`~~ ~~`LG-13`~~ | grant the Actions PR-create permission | `task-packs/FORWARD_LEDGER.md:264` |
| 5 | ~~`DEF-538`~~ ~~`LG-5`~~ | set branch protection (AFTER the check-run names are rehearsed) | `—` |
| 6 | ~~`DEF-539`~~ ~~`LG-6`~~ | record the demo GIF | `README.md:38` |

✅ **Steps 1 to 5 were driven at the 2026-09-25 cut** (`DEF-536`, `DEF-537`, `DEF-459` and `DEF-530` struck 2026-09-26; `DEF-538` struck before the seed: branch protection on `main` reads eight required checks, a pull request required, admins enforced). Step 6, the demo GIF, closed 2026-10-05 (recorded in `5ecb712`, embedded by the README lane), so no launch step is open, and the ordering warnings above are history.

✅ **The fresh-clone cluster closed while this rebuild ran.** `14f834e` *(fix(tests): unpin four
guards from the maintainer's working tree)* landed concurrently and closed **three** of the
original eleven §1 rows — the census-prose, record-surface and session-banner reds — plus three
further archive-path rows that had been demoted. Re-verified by execution, not relayed: a fresh
`git clone --no-hardlinks` runs **0 failed** on the affected modules, and an extracted `git
archive` under stage-02's own `-m "not slow and not full_tree"` selection runs **0 failed**.
Struck rows are on the `record` branch, in the pre-rebuild file the header names, with that evidence.

⚠ **`14f834e` also made a deliberate coverage trade that no row yet carries.** It dropped
`cc/blueprints` from `_LIVE_TREE_WATCH` — removing the *detector*, not the write. The live-tree
bootstrap at `tests/test_session_banner.py::test_keep_tail_last_section_alone_over_budget_keeps_that_section` still runs, and `tests/conftest.py::_isolate_interpreter_identity_memo` records the
trade as *"KNOWN COVERAGE LOSS, accepted deliberately"* with a named follow-up. Tracked below.

---

## §2 — Open fixes, by unit of work

_Rebuilt 2026-08-20 from a **full census**: every live row re-verified at HEAD by nine
independent agents, then re-classified twice independently (98.5% pairwise agreement).
**Classes are units of WORK, not diagnoses** — members share one provable acceptance rule (one oracle, one method), not always one edit (several classes' own "Why one class" paragraphs say the repairs differ per member), so a pack scoped to a
class can honestly report it closed. The previous structure grouped by symptom; eight of its
nine stated "one fix"es were falsified when driven._


**The three populations are counted apart — never as one number.** Merging them is what
made "we are nearly ready" unfalsifiable (contract rule 5).


| population | what it means |
|---|---|
| LOGIC_BUG | code behaves wrongly |
| HYGIENE | docs / comments / registries / test scaffolding |
| OPERATOR_ACTION | no code fix exists |

| audience |
|---|
| **ADOPTER** — someone who ran `pip install espalier` |
| MAINTAINER |
| OPERATOR |

### Class index

| § | class | population | audience | effort |
|---|---|---|---|---|
| [§C0](#c0--standalone--no-shared-unit-of-work) | Standalone — no shared unit of work | MIXED | MIXED | — |
| [§C1](#c1--do-the-five-console-actions-that-are-the-only-reason-nothing-has-shipped) | Do the five console actions that are the only reason nothing has shipped | OPERATOR_ACTION | MIXED | — |
| [§C2](#c2--walk-the-documented-release-and-contribution-procedures-step-by-step-against-the-live-workflow-and-correct-every-step-that-fails) | Walk the documented release and contribution procedures step by step against the live workflow and correct every step that fails | HYGIENE | MAINTAINER | ~112 LOC |
| [§C13](#c13--build-the-release-archive-from-the-git-index-and-give-the-transient-predicate-one-owner) | Build the release archive from the git index and give the transient predicate one owner | HYGIENE (re-derived 2026-09-20; was LOGIC_BUG) | MIXED (re-derived 2026-09-08; was ADOPTER) | ~45 LOC |
| [§C14](#c14--make-two-gates-key-on-the-event-they-care-about-instead-of-on-the-request-for-it) | Make two gates key on the event they care about instead of on the request for it | LOGIC_BUG | MIXED (re-derived 2026-09-08; was ADOPTER) | ~65 LOC |
| [§C15](#c15--make-sister_site_probe-read-the-tree-core-rule-12-tells-you-it-reads) | Make sister_site_probe read the tree Core Rule 12 tells you it reads | LOGIC_BUG | MIXED | ~55 LOC |
| [§C18](#c18--resolve-every-reference-in-shipped-text-against-the-deploy-inventory-then-require-or-delete-each-target) | Resolve every reference in shipped text against the deploy inventory, then require or delete each target | HYGIENE | MIXED (re-derived 2026-09-08; was ADOPTER) | ~241 LOC |
| [§C20](#c20--drive-each-described-command-then-rewrite-the-shipped-sentence-to-say-what-it-does---at-every-copy) | Drive each described command, then rewrite the shipped sentence to say what it does - at every copy | HYGIENE | MIXED (re-derived 2026-09-08; was ADOPTER) | ~44 LOC |
| [§C23](#c23--make-the-class-oracles-silence-mean-something-name-the-opt-out-suppression-and-give-the-ratchets-a-tighten-me-leg) | Make the class oracle's silence mean something: name the opt-out suppression and give the ratchets a tighten-me leg | HYGIENE | MAINTAINER (re-derived 2026-09-05; was ADOPTER) | ~42 LOC |
| [§C24](#c24--make-each-packaging-and-fusion-assertion-check-the-artifact-that-ships) | Make each packaging and fusion assertion check the artifact that ships | HYGIENE | MIXED | ~50 LOC |
| [§C25](#c25--bring-the-workflow-asset-install-ci-copies-into-every-adopter-repo-under-the-same-governance-as-the-source-workflow) | Bring the workflow asset install-ci copies into every adopter repo under the same governance as the source workflow | HYGIENE | MAINTAINER (re-derived 2026-09-05; was ADOPTER) | ~26 LOC |
| [§C26](#c26--make-the-three-release-gates-fail-closed-right-artifact-all-stages-content-floor) | Make the three release gates fail closed: right artifact, all stages, content floor | LOGIC_BUG | MAINTAINER | ~42 LOC |
| [§C27](#c27--make-every-sync-command-leave-the-tree-converged-and-warn-on-both-sides-of-a-mirror) | Make every sync command leave the tree converged and warn on both sides of a mirror | LOGIC_BUG | MAINTAINER | ~35 LOC |
| [§C28](#c28--make-every-test-tree-enumeration-predicate-match-a-real-developer-working-tree) | Make every test-tree enumeration predicate match a real developer working tree | HYGIENE (re-derived 2026-09-20; was LOGIC_BUG) | MAINTAINER | ~30 LOC |
| [§C29](#c29--hoist-two-pieces-of-repeated-work-out-of-their-loops) | Hoist two pieces of repeated work out of their loops | MIXED | MAINTAINER | ~25 LOC |
| [§C30](#c30--derive-every-pack-pre-flight-obligation-from-the-enforcer-that-would-actually-red) | Derive every pack pre-flight obligation from the enforcer that would actually red | HYGIENE | MAINTAINER | ~150 LOC |
| [§C31](#c31--teach-the-citation-resolvers-every-anchor-shape-the-repo-actually-writes-and-promote-skipped-anchors-to-problems) | Teach the citation resolvers every anchor shape the repo actually writes, and promote skipped anchors to problems | MIXED | MAINTAINER | ~165 LOC |
| [§C32](#c32--make-the-ledgers-own-enforcement-parse-every-row-shape-the-ledger-actually-uses) | Make the ledger's own enforcement parse every row shape the ledger actually uses | HYGIENE | MAINTAINER | ~182 LOC |
| [§C33](#c33--resolve-every-bench-corpus-reference-field-and-combo-segment-then-repoint-the-one-that-fails) | Resolve every bench-corpus reference field and combo segment, then repoint the one that fails | HYGIENE | MAINTAINER | ~48 LOC |
| [§C34](#c34--derive-mirror-families-from-the-byte-parity-assertions-so-a-row-without-a-sync-script-is-visible) | Derive mirror families from the byte-parity assertions so a row without a sync script is visible | HYGIENE | MAINTAINER | ~57 LOC |
| [§C35](#c35--derive-the-cross-boundary-duplicate-register-then-collapse-what-can-collapse-and-pin-what-cannot) | Derive the cross-boundary duplicate register, then collapse what can collapse and pin what cannot | MIXED | MIXED | ~150 LOC |
| [§C36](#c36--for-each-named-assertion-write-the-mutation-it-claims-to-catch-watch-it-pass-then-tighten-until-it-reds) | For each named assertion, write the mutation it claims to catch, watch it pass, then tighten until it reds | HYGIENE | MIXED | ~128 LOC |
| [§C37](#c37--replace-four-hand-kept-gate-populations-with-a-derivation-from-the-live-source) | Replace four hand-kept gate populations with a derivation from the live source | HYGIENE | MAINTAINER | ~115 LOC |
| [§C38](#c38--give-the-two-test-tree-only-rules-a-product-code-arm-and-an-enforcer) | Give the two test-tree-only rules a product-code arm and an enforcer | HYGIENE | MAINTAINER | ~130 LOC |
| [§C39](#c39--correct-each-cited-comment-against-the-code-beside-it-and-delete-every-restated-number) | Correct each cited comment against the code beside it, and delete every restated number | HYGIENE | MAINTAINER | ~49 LOC |
| [§C40](#c40--add-the-three-catalog-entries-whose-absence-makes-each-review-round-re-derive-the-same-lesson) | Add the three catalog entries whose absence makes each review round re-derive the same lesson | HYGIENE | MAINTAINER | ~65 LOC |
| [§C41](#c41--generate-a-complete-index-into-both-catalog-docs) | Generate a complete index into both catalog docs | HYGIENE | MAINTAINER | ~31 LOC |
| [§C42](#c42--make-the-conftest-escape-hatches-behave-the-way-the-files-own-idiom-says-they-do) | Make the conftest escape hatches behave the way the file's own idiom says they do | HYGIENE | MAINTAINER | ~19 LOC |
| [§C43](#c43--prune-the-compiled-python-noise-from-the-release-walk-and-report-what-was-pruned) | Prune the compiled-Python noise from the release walk and report what was pruned | LOGIC_BUG (re-derived 2026-09-20; was HYGIENE) | MAINTAINER | ~18 LOC |
| [§C44](#c44--add-safe_read_text-and-a-scanner-rule-pinning-the-accepted-unguarded-read-population) | Add safe_read_text and a scanner rule pinning the accepted unguarded-read population | HYGIENE | MAINTAINER | ~60 LOC |
| [§C46](#c46--work-the-four-owed-chores-that-no-code-change-can-close) | Work the four owed chores that no code change can close | MIXED | MIXED | ~25 LOC |
| [§C48](#c48--propagate-dec-25-to-every-live-site-still-keyed-on-this-tree-going-public) | Propagate DEC-25 to every live site still keyed on this tree going public | HYGIENE (re-derived 2026-09-20; was LOGIC_BUG) | OPERATOR | ~40 LOC |
| [§C51](#c51--make-the-forward-work-a-shipped-surface-rebuild-the-ledger-to-forward-work-only-fold-the-findings-corpus-into-it-and-move-the-shipping-boundary-and-the-codename-gate-with-it) | Make the forward work a shipped surface: rebuild the ledger to forward work only, fold the findings corpus into it, and move the shipping boundary and the codename gate with it | MIXED | MIXED | ~1 pack |
| [§C52](#c52--make-the-adopter-stop-time-test-gate-real-run-the-override-at-the-root-and-fail-closed-on-a-spawn-it-cannot-make-give-the-command-a-committed-home-and-say-on-every-default-surface-when-gate-1-is-off) | Make the adopter stop-time test gate real: run the override at the root and fail closed on a spawn it cannot make, give the command a committed home, and say on every default surface when Gate 1 is off | MIXED | ADOPTER | — |
| [§C53](#c53--make-every-espaliertoml-key-either-take-effect-or-be-named-warn-on-unknown-and-misplaced-keys-enforce-or-retire-the-two-zone-keys-add-the-required-prefix-knob-and-make-upgrade-see-a-config-edit) | Make every espalier.toml key either take effect or be named: warn on unknown and misplaced keys, enforce or retire the two zone keys, add the required-prefix knob, and make upgrade see a config edit | MIXED | ADOPTER | — |
| [§C54](#c54--stop-the-harness-leaving-home-path-shaped-or-archive-named-files-in-an-adopters-working-tree-then-pin-every-deployed-asset-and-runtime-writer-against-one-small-shape-set) | Stop the harness leaving home-path-shaped or archive-named files in an adopter's working tree, then pin every deployed asset and runtime writer against one small shape set | MIXED | ADOPTER | — |
| [§C55](#c55--key-every-ownership-reader-on-the-predicate-the-uninstall-deletes-by-doctors-inventory-and-its-uninstalled-verdict-stop-claiming-unmarked-adopter-files-and-init-prints-a-formatter-ignore-snippet-derived-from-what-it-wrote) | Key every ownership reader on the predicate the uninstall deletes by: doctor's inventory and its uninstalled verdict stop claiming unmarked adopter files, and init prints a formatter-ignore snippet derived from what it wrote | MIXED | ADOPTER | — |
| [§C56](#c56--read-the-effective-claudemd-through-one-helper-that-follows--imports-so-an-adopter-owned-claudemd-draws-no-false-note-from-init-and-no-false-fail-from-smoke) | Read the effective CLAUDE.md through one helper that follows @ imports, so an adopter-owned CLAUDE.md draws no false NOTE from init and no false FAIL from /smoke | MIXED | ADOPTER | — |
| [§C57](#c57--replace-the-python-shaped-defaults-a-node-adopter-inherits-a-path-first-preflight-hand-copied-source-extension-lists-name-keyed-gate-relief-bare-binary-allow-rules-and-a-bodiless-optional-roster-with-ones-derived-from-the-fingerprint-and-espaliertoml-proven-on-one-throwaway-node-tree) | Replace the Python-shaped defaults a Node adopter inherits (a PATH-first /preflight, hand-copied source-extension lists, name-keyed gate relief, bare-binary allow rules and a bodiless optional roster) with ones derived from the fingerprint and espalier.toml, proven on one throwaway Node tree | MIXED | ADOPTER | — |
| [§C58](#c58--make-every-shipped-first-contact-diagnostic-report-the-adopters-tree-not-the-harnesss-own-source-stand-down-or-re-root-the-espalier-coverage-loops-in-analyze-and-test-writer-guard-code-reviewers-phase-1-reads-make-the-advisors-dead-config-pass-skip-managed-bodies-and-say-what-it-checked-and-pin-each-fence-on-an-initd-temp-tree-so-an-unguarded-self-host-path-cannot-re-enter) | Make every shipped first-contact diagnostic report the adopter's tree, not the harness's own source: stand down or re-root the espalier/ coverage loops in /analyze and test-writer, guard code-reviewer's Phase 1 reads, make the advisor's dead-config pass skip managed bodies and say what it checked, and pin each fence on an init'd temp tree so an unguarded self-host path cannot re-enter | LOGIC_BUG | ADOPTER | ~120 LOC |
| [§C59](#c59--state-the-python-310-tomli-dependency-on-every-install-path-derived-from-pyprojects-dependencies-change-quickstarts-install-line-to-readmes-wording-and-add-a-tomli-step-to-the-fuse-handoffs-finish_up_steps-amending-the-fuse-test-that-forbids-that-line-pinned-by-one-contract-test) | State the Python 3.10 tomli dependency on every install path, derived from pyproject's dependencies: change QUICKSTART's install line to README's wording and add a tomli step to the fuse handoff's FINISH_UP_STEPS, amending the fuse test that forbids that line, pinned by one contract test. | HYGIENE | ADOPTER | ~50 LOC |
| [§C60](#c60--pin-every-shipped-python-entry-points-text-io-to-utf-8-so-it-runs-to-completion-on-a-default-code-page-windows-interpreter-espalier-init-the-handoff-and-read-summary-clis-in-toolscc-and-the-agent-body-heredocs) | Pin every shipped Python entry point's text I/O to UTF-8 so it runs to completion on a default-code-page Windows interpreter: espalier init, the /handoff and /read-summary CLIs in tools/cc, and the agent-body heredocs | LOGIC_BUG | ADOPTER | ~170 LOC |
| [§C61](#c61--make-the-bash-protected-zone-reader-deny-only-what-a-real-shell-would-write-under-a-zone-relieve-quoted-mentions-after-an-earlier-substitution-inside-a-quoted-substitution-behind-gh-text-flags-and-inside-compound-commands-and-place-a-cd-target-bound-in-the-same-command) | Make the Bash protected-zone reader deny only what a real shell would write under a zone: relieve quoted mentions after an earlier substitution, inside a quoted substitution, behind gh text flags and inside compound commands, and place a cd target bound in the same command | LOGIC_BUG | ADOPTER | ~250 LOC |
| [§C62](#c62--make-the-harnesss-own-reflect-oracles-report-nothing-a-fresh-adopter-did-not-cause-take-init-seeded-and-loader-reached-surfaces-out-of-the-orphan-check-on-both-twins-parse-headings-by-commonmark-in-the-sparse-section-check-and-name-the-flagged-files-in-the-reflect_trigger-advisory) | Make the harness's own reflect oracles report nothing a fresh adopter did not cause: take init-seeded and loader-reached surfaces out of the orphan check on both twins, parse headings by CommonMark in the sparse-section check, and name the flagged files in the reflect_trigger advisory | LOGIC_BUG | ADOPTER | ~110 LOC |
| [§C63](#c63--route-every-exit-0-hook-advisory-to-a-channel-the-pinned-protocol-says-reaches-claude-the-sessionstart-banner-or-posttooluse-additionalcontext-or-to-a-say_once-record-and-stop-the-voice-gate-counting-debug-log-stderr-as-speech) | Route every exit-0 hook advisory to a channel the pinned protocol says reaches Claude (the SessionStart banner or PostToolUse additionalContext) or to a say_once record, and stop the voice gate counting debug-log stderr as speech | LOGIC_BUG | ADOPTER | ~480 LOC |
| [§C64](#c64--make-the-onboarding-probes-re-derive-their-own-rows-onb-1-closes-once-the-goal-is-written-and-stays-open-while-an-opted-out-tree-keeps-an-unset-ccgoalmd-and-onb-1-onb-6-and-onb-7-decode-their-files-the-way-the-harnesss-own-readers-do) | Make the onboarding probes re-derive their own rows: ONB-1 closes once the goal is written and stays open while an opted-out tree keeps an unset cc/GOAL.md, and ONB-1, ONB-6 and ONB-7 decode their files the way the harness's own readers do | LOGIC_BUG | ADOPTER | ~80 LOC |
| [§C65](#c65--make-the-recursive-remove-verdicts-agree-with-the-deny-texts-that-predict-them-before-the-drive-depth-wall-compare-a-drive-path-as-typed-against-the-repo-and-home-and-let-a-match-lift-only-that-wall-read-a-drive-paths-depth-one-way-on-bash-and-powershell-and-have-the-drop--force-remedy-and-the-hooksmd-sentence-name-what-the-unforced-tier-refuses-pinned-by-drive-rows-added-to-the-driven-claims-table-in-teststest_denial_reasonspy) | Make the recursive-remove verdicts agree with the deny texts that predict them: before the drive-depth wall, compare a drive path as typed against the repo and home and let a match lift only that wall, read a drive path's depth one way on Bash and PowerShell, and have the drop -Force remedy and the HOOKS.md sentence name what the unforced tier refuses, pinned by drive rows added to the driven claims table in tests/test_denial_reasons.py | MIXED | ADOPTER | ~90 LOC |
| [§C66](#c66--make-write_guards-three-quote-blind-word-cutters-honour-quotes-so-the-secret-read-legs-and-the-env-prefix-claude-scan-see-a-quoted-spaced-path-or-string-as-one-word-and-never-read-a-strings-first-word-as-a-verb) | Make write_guard's three quote-blind word cutters honour quotes, so the secret-read legs and the env-prefix claude scan see a quoted spaced path or string as one word, and never read a string's first word as a verb | LOGIC_BUG | ADOPTER | ~80 LOC |
| [§C67](#c67--make-the-drift-check-compare-signals-not-census-reduce-every-census-valued-field-in-espalierdiffingpys-two-normalizers-to-the-signal-it-carries-so-doctor-stays-green-after-an-ordinary-commit-a-lock-file-bump-or-a-new-docs-page-and-still-flips-on-a-new-ci-provider-framework-or-language) | Make the drift check compare signals, not census: reduce every census-valued field in espalier/diffing.py's two normalizers to the signal it carries, so doctor stays green after an ordinary commit, a lock-file bump or a new docs page and still flips on a new CI provider, framework or language | LOGIC_BUG | ADOPTER | ~120 LOC |
| [§C68](#c68--name-the-approval-marker-wherever-the-harness-writes-a-harness-guard-protected-path-git-will-commit-install-ci-fuse-upgrade---execute-a-re-run-init-and-merge-settings-on-a-tracked-settings-file-tell-the-adopter-that-the-commit-carrying-those-files-needs-harness-update-approved) | Name the approval marker wherever the harness writes a Harness-Guard-protected path git will commit: install-ci, fuse, upgrade --execute, a re-run init and merge-settings on a tracked settings file tell the adopter that the commit carrying those files needs HARNESS-UPDATE-APPROVED | HYGIENE | ADOPTER | ~100 LOC |
| [§C69](#c69--pick-and-recognise-the-python-interpreter-by-what-it-answers-not-by-its-name-at-every-site-that-chooses-one-so-a-windows-host-whose-python3-or-python-is-the-store-alias-or-that-has-only-the-py-launcher-gets-wired-passes-doctor-and-runs) | Pick and recognise the Python interpreter by what it answers, not by its name, at every site that chooses one, so a Windows host whose python3 or python is the Store alias, or that has only the py launcher, gets wired, passes doctor and runs | MIXED | ADOPTER | ~500 LOC over about 20 hand-edited files plus two mirror syncs (estimate, not measured) |
| [§C70](#c70--make-the-demo-takes-two-unverified-assumptions-measurable-and-give-its-one-load-bearing-number-a-receipt-so-the-hero-can-be-recorded-without-discovering-a-dead-beat-on-take-day) | Make the demo take's two unverified assumptions measurable and give its one load-bearing number a receipt, so the hero can be recorded without discovering a dead beat on take day | MIXED | MIXED | one lane plus one 30-second check |
| [§C71](#c71--keep-maintainer-addressed-content-out-of-what-init-ships-an-audience-test-for-shipped-text-ids-and-verbatim-captures) | Keep maintainer-addressed content out of what init ships: an audience test for shipped text, ids and verbatim captures | MIXED | ADOPTER | — |
| [§C72](#c72--render-the-shipped-instruction-surface-against-the-adopter-instead-of-shipping-the-maintainers-own-espalier-shaped-bodies) | Render the shipped instruction surface against the adopter instead of shipping the maintainer's own Espalier-shaped bodies | MIXED | ADOPTER | — |
| [§C73](#c73--fold-the-adopters-existing-knowledge-in-route-index-and-surface-it-where-the-adopter-keeps-it) | Fold the adopter's existing knowledge in: route, index and surface it where the adopter keeps it | MIXED | ADOPTER | — |
| [§C74](#c74--reconcile-an-adopters-prior-harness-assets-that-already-do-a-shipped-assets-job-under-another-name-or-path) | Reconcile an adopter's prior harness: assets that already do a shipped asset's job under another name or path | MIXED | ADOPTER | — |
| [§C75](#c75--make-every-adopter-side-stand-down-skip-and-failure-say-so-no-silent-misbehaviour-off-the-self-host-repo) | Make every adopter-side stand-down, skip and failure say so: no silent misbehaviour off the self-host repo | MIXED | ADOPTER | — |
| [§C76](#c76--make-the-recursive-remove-tiers-read-every-launch-form-a-shell-runs-and-stay-coupled-by-property-a-native-rm-reached-by-its-file-name-or-path-on-the-powershell-tool-and-cmds-own-deletes-on-both-tools-meet-the-plain-forms-wall-and-every-step-aside-of-the-powershell-wall-is-asked-by-the-speed-bump) | Make the recursive-remove tiers read every launch form a shell runs and stay coupled by property: a native rm reached by its file name or path on the PowerShell tool and cmd's own deletes on both tools meet the plain form's wall, and every step-aside of the PowerShell wall is asked by the speed bump | MIXED | MIXED | — |

<a id="c0"></a>

### §C0 — Standalone — no shared unit of work

**Unit of work.** Each row is its own fix. Grouping them would be a false class.


**Members**


| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|


<a id="c1"></a>

### §C1 — Do the five console actions that are the only reason nothing has shipped

**Unit of work.** Sit at the GitHub/PyPI consoles and do them in this order: claim the espalier-harness PyPI slug and add environment protection rules to the pypi environment; enable 'Actions may create and approve pull requests' so the weekly externals-drift job can open its PR (three months of unreviewed hook-protocol drift is sitting on branches nobody sees); fold the [Unreleased] CHANGELOG section (thousands of lines -- derive the count, it drifts) and bump pyproject to 0.8.0b1; seed the NEW public repository from the generated tree (DEC-25/DEC-31 -- `docs/RELEASE_CHECKLIST.md` §First publish; this tree is never flipped public: its releases carried private working material, since removed, `DEF-840`); record the demo GIF. Zero lines of code. (Rewritten 2026-09-20: until then this sentence still read "flip repo visibility to public", the event `DEC-25`/`DEC-31` foreclose -- the sibling site `memory/a-retraction-does-not-propagate-itself.md` did not list.)


**What this does NOT reach.** It does not make the release CORRECT - the documented tag-push sequence is still wrong (see drive-the-release-and-contribution-procedures-literally, which must land first or the tag push silently publishes nothing).


**Why one class.** No code change exists for any member; the census population is OPERATOR_ACTION for all five. They are one class because they are one sitting at two web consoles plus one screen recording, and because every other class in this ledger is unshippable until they are done.


✅ **The 2026-08 CI outage is discharged (2026-09-01).** DEF-582 (GitHub Actions unavailable) is closed — Actions ran again — so the trusted-publisher smoke leg of DEF-459/DEF-536 and the CI-green clause of DEF-539 are reachable in principle, alongside the slug claim, the environment rules, the fresh-repo seed, the local bump+fold and the GIF that were always actionable. ⚠ **Actions was disabled at the repo level from 2026-09-10 to 2026-09-23** (the struck `DEF-856` row records the re-enable and the dispatch): no job executed in that interval, so treat its green as local-only; the first real runs after the switch found six host-relative defects the local tier could not see, each fixed and named by commit in that row. (Amended 2026-09-20: until then this note read "jobs execute again", a present-tense claim the live API contradicted for ten days; amended again 2026-09-24 when the switch was back on.)

✅ **Four of the five console actions were driven at the 2026-09-25 cut (struck 2026-09-26):** `DEF-537` (the public repository seeded from the generated tree and `v0.8.0b1` released to PyPI), `DEF-536`/`LG-1` (the bump and the fold), `DEF-459`/`LG-4` (the PyPI slug and the `pypi` environment's reviewer, wait timer and branch policy) and `DEF-530`/`LG-13` (the Actions PR permission). `DEF-539`/`LG-6`, the demo GIF, is the class's one live member; the title's "nothing has shipped" is history, kept because the class index anchors on it.


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c2"></a>

### §C2 — Walk the documented release and contribution procedures step by step against the live workflow and correct every step that fails

**Unit of work.** Open docs/RELEASE_CHECKLIST.md, CONTRIBUTING.md and .github/workflows/publish.yml side by side and execute the sequence on paper: replace the three bulk-tag-push sites with a single-tag push (and move tests/test_release_checklist_contract.py:56, which currently REQUIRES the defective command); move the namespace/environment step above the tag push and fix the attribution sentence naming a trigger the workflow does not listen for; add a Recovery subsection (or a workflow_dispatch with a tag input) so a swallowed release has a route back; re-base the dry-run rehearsal on the current pyproject version so it can reach the handshake it exists to exercise; correct the digest recipe to resolve the COMMIT sha rather than the annotated tag object's, and re-pin the four v1.14.0 prose sites to the live v1.14.2; name pre-pack-TP-104 as a keep in the delete-every-lightweight-tag step (that tag is what keeps a security test from silently skipping); and in CONTRIBUTING add the approval marker to the Hook Rules section and the PR template, add the missing tag-push step with a cross-reference to the checklist, and change both plain-tag sites to annotated tags.


**What this does NOT reach.** It does not publish anything (ship-blockers-only-the-operator-can-clear) and it does not touch publish.yml's own version-guard logic beyond adding a recovery entry point.


**Why one class.** Every member is found and closed by the SAME act: reading one documented instruction and asking whether following it literally produces the stated result. Three members (DEF-448, DEF-452, DEF-460) are a single causal chain - the bulk tag push swallows the release, the namespace does not exist yet, and there is no way back - so a pack that fixes one and not the others leaves the trap armed. The two CONTRIBUTING release steps are the same sequence written in a second file.


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c3"></a>

### §C13 — Build the release archive from the git index and give the transient predicate one owner

**Unit of work.** In espalier/release_pack.create_release_zip enumerate the git index instead of safe_rglob, so an untracked-but-not-gitignored file that classifies public cannot ship; add a bare .git FILE entry to release_noise.TRANSIENT_FILES - in a worktree or submodule checkout .git is a text file holding a local absolute gitdir path and the contract currently classifies it as shippable; and make pre_release._find_transient_noise call surface_contract.is_transient as its sibling already does, so the two halves of one gate stop disagreeing.


**What this does NOT reach.** It does not change the release REPORT's accounting (count-what-the-release-walk-pruned) and it does not validate the built artifact (make-each-release-gate-fail-closed-on-what-it-validates).


**Why one class.** All three are the same walk-and-classify path disagreeing with itself: two enumerators, two transient predicates. One oracle closes all three - build the zip from a git worktree checkout that contains an untracked public file, and diff the archive members against the git index.


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c14"></a>

### §C14 — Make two gates key on the event they care about instead of on the request for it

**Unit of work.** Pass tool_name into the speed-bump's flag_key so CP-MCP-SIDEEFFECT keys per tool rather than once for all MCP tools together - today the second and third different side-effecting tool go unchallenged; and add a code_reviewed evidence flag written by subagent_stop so stop_gate's code-review gate is satisfied by a review HAPPENING, not by one having been asked for.


**What this does NOT reach.** It does not change what either gate demands - only what counts as having satisfied it.


**Why one class.** Two gates, one defect shape, one acceptance test each: trigger the gate twice with different events and require it to fire twice. Two files, two small independent edits, one sitting.


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c15"></a>

### §C15 — Make sister_site_probe read the tree Core Rule 12 tells you it reads

**Unit of work.** Widen _default_scan_targets to tools/cc root modules and espalier subpackages, or state each scope-out in the file - an rc=0 covers roughly half the tree today; and walk the whole AST instead of tree.body in _collect_constant_sites so a constant defined inside a loop or comprehension is visible. Then re-run scripts/sync_vendor_cc.py for the byte-mirror.


**What this does NOT reach.** It does not remove the opt-out suppression that also makes rc=0 untrustworthy (stop-a-clean-probe-run-reading-as-evidence-of-no-class) - a pack must land both before rc=0 means anything.


**Why one class.** One file, one claim: Core Rule 12 names this probe as THE class oracle. Both members are proved closed by the same probe run against a known duplicated constant defined inside a loop in a tools/cc root module.


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c16"></a>

### §C18 — Resolve every reference in shipped text against the deploy inventory, then require or delete each target

**Unit of work.** Build one resolver that takes a reference out of shipped text - a path, a section, a test node-id, a symbol - and answers whether the adopter's tree receives it; run it over the deployed docs, the CLI help/report strings, .claude/commands/, tools/cc/session_summary.py and _reinject.py, and for each of the 65 dead test-path cites and 6 live help/report cites either ship the target or delete the cite; wire the same resolver into scripts/sync_asset_docs.py so no wikilink and no reference to an unshipped doc can re-enter; and fix the one shipped module docstring that names a class that does not exist (the nearest real symbol is ReflectFinding).


**What this does NOT reach.** It does not fix a shipped SENTENCE that misdescribes behaviour (drive-each-verb-and-rewrite-the-sentence-that-describes-it) - only references to targets the adopter's tree never receives.


**Why one class.** One resolver, three consumers. DEF-553 is 86 sister sites of exactly the thing DEF-412i's gate would have stopped, and DEF-392a is the same population at symbol granularity. The census records that DEF-553's count GREW rather than shrank, which is the evidence that per-site fixing does not close it.


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c19"></a>

### §C20 — Drive each described command, then rewrite the shipped sentence to say what it does - at every copy

**Unit of work.** Independent corrections (the enumeration below carries the count; no number word to rot), each verified by running the thing described: FRESHNESS section 6 names the audit-accuracy verb, not the plain audit verb, which emits no freshness verdict at any cache state; delete the expected_value-verifier sentence from FRESHNESS section 4 and LEAVE the correct '7 migrated' count beside it alone; reword the seed header to 'refreshed only while operator-untouched', since re-init does overwrite an untouched seeded doc; add help= to the provenance subparser (a working verb invisible in --help) and fix the freshness scanner docstring that describes a design the code stopped using; state 'up to four candidates' at the 7 source-of-truth /recall sites and run the 3 syncs; drop the model version from the trailer convention at all four sites, two of which ship. Added 2026-09-26 from walk 4, three more under the same rule: rewrite the three sentences that say `doctor` names the twins a file lacks to what the slice prints, or widen the slice (`DEF-931`); gate the init epilogue's SessionStart line on the armed branch (`DEF-932`); rewrite the 8.3 known-limit to the measured result (`DEF-933`).


**What this does NOT reach.** It does not resolve references (make-every-deployed-doc-reference-resolve-in-the-adopter-tree) and it does not regenerate quoted output samples (regenerate-every-quoted-sample-from-one-driven-capture).


**Why one class.** Independent corrections sharing ONE acceptance rule: run the verb, then make the sentence match. Two members are multi-site and must run the mirror syncs, which is why they belong here rather than being fixed in passing. DEF-615 carries the exact warning this class exists to prevent: the /recall command BODY already says 'one to four candidates' and is byte-correct in both mirrors - only the always-loaded frontmatter line was missed, so a fix landed one surface short and the wrong claim is what every session loads.


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c21"></a>

### §C23 — Make the class oracle's silence mean something: name the opt-out suppression and give the ratchets a tighten-me leg

**Unit of work.** Name opt-out suppression in Core Rule 12 - the probe quietly switches off 8 of its 9 findings via opt-out comments, so a clean run is not evidence there is no class - and pin one marker load-bearing so the suppression itself is guarded; in tests/test_sister_site_probe_ceilings.py assert equality, or add a live tighten-me leg, so a genuine drop tightens the pin instead of leaving unnoticed slack.


**What this does NOT reach.** It does not widen the probe's SCOPE (make-the-class-detection-probe-cover-the-tree-rule-12-claims). Both must land before an rc=0 is evidence of anything - and a pack must not report either one as 'the oracle is now trustworthy'.


**Why one class.** Both members are the same claim being overstated by the same instrument: a clean run of sister_site_probe or its ceilings reads as 'no class', and neither the suppression nor the never-tightening ratchet is visible at the point of reading. One sitting over the probe, its ceilings test, and the rule that cites it.


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c24"></a>

### §C24 — Make each packaging and fusion assertion check the artifact that ships

**Unit of work.** Write one clean-derived-build-state helper and call it at every build site - one test clears stale state today, four other build paths still reuse a cached file list; assert the LICENSE body matches the pyproject SPDX id, not merely that a LICENSE file exists; assert the built wheel's dist-info licence file and METADATA agree, which they do today only by luck of the packaging defaults; assert the fusion marker is in fuse's COMMITTED tree that fresh-clone CI reads, not just seeded on disk.


**What this does NOT reach.** It does not make any release gate fail closed on a missing STAGE (make-each-release-gate-fail-closed-on-what-it-validates) - this class is about what the assertion looks at, that one is about whether the gate ran at all.


**Why one class.** Every member stops one step short of the shipped artifact and is closed by moving the assertion onto it. One oracle: build the wheel and the fusion, then assert against the product. CONV-3 is the adopter-facing member and is what keeps the class in the adopter band.


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c25"></a>

### §C25 — Bring the workflow asset install-ci copies into every adopter repo under the same governance as the source workflow

**Unit of work.** Parametrize the SHA-pin assertion in tests/test_publish_workflow.py over every workflow INCLUDING the deployed asset - only the source workflow is checked today, and the 11 uses: steps in the copy that lands in every adopter repo are gated by nothing; and name the packaged asset as the re-apply target in .github/dependabot.yml so a bot bump does not silently break byte-parity.


**What this does NOT reach.** Dependabot's github-actions ecosystem only scans .github/workflows/, so no directory: entry can make the bot edit the asset - the fix is a documented re-apply target, not automation. The asset sync script's own refusal bug lives in make-every-sync-command-leave-the-tree-converged.


**Why one class.** One asset, two governance gaps, both proved by the same act: bump an action in the source workflow and check that the assertion covers the copy and that the bot PR names the re-apply step.


⚠ **Blocked on:** Dependabot's github-actions ecosystem cannot reach the packaged asset; a documented re-apply target is the fix


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c26"></a>

### §C26 — Make the three release gates fail closed: right artifact, all stages, content floor

**Unit of work.** In scripts/wheel_smoke.py select the wheel by PEP-440 version rather than lexicographically - a 0.8.0a13 build silently loses to a leftover 0.8.0a9 and the test validates the stale artifact; in scripts/final_release_matrix.py record skipped stages and require all six ran before reporting 'ready to tag'; in scripts/release_check.py hoist the required-content floor and apply it at both call sites, so archive validation stops blessing a near-empty release ZIP because it only ever looks for bad files.


**What this does NOT reach.** It does not change what any gate checks FOR - only that it checked, and checked the right artifact.


**Why one class.** All three return PASS without having examined the thing they exist to examine. One oracle for the class: run each gate against a deliberately-bad artifact - a stale wheel, a run with stages skipped, an empty zip - and require red. Three scripts, one sitting, one acceptance criterion.


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c27"></a>

### §C27 — Make every sync command leave the tree converged and warn on both sides of a mirror

**Unit of work.** Run scripts/sync_vendor_cc.py FROM cmd_refresh_self_host_pin instead of printing an instruction - it updates 3 of the 5 files holding the pin and leaves the tree divergent between two commands; stamp the digest scripts/sync_github_workflow_asset.py itself wrote, so a matching dirty root is recognised as safe and syncing twice in a row is not refused because the first sync's own output looks hand-edited; add an espalier/_vendor/cc/ mirror-side branch to _reinject._render_vendor_sync so hand-editing the vendored copy of a hook warns like every other mirror in the repo.


**What this does NOT reach.** It does not reconcile the mirror ADVISORY text or the census guards - those are HYGIENE and are counted in make-every-surface-impact-obligation-name-a-real-enforcer and make-the-mirror-census-see-a-row-that-has-no-sync-script.


**Why one class.** One subsystem, one oracle: run each sync twice and edit each side of each mirror row. All three are the sync machinery either refusing a legitimate run or leaving a divergence, and each is separately provable in that one drive.


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c28"></a>

### §C28 — Make every test-tree enumeration predicate match a real developer working tree

**Unit of work.** Skip leading-dot names in the agent/command/skill globs - a macOS sidecar file counts as an extra agent and reds count contracts across six modules with no message naming the cause; filter dotfiles in the mirror-parity rglob sets AND in the sync enumerator, since a gitignored .DS_Store reds the parity contract and the remedy the failure message gives copies it into both mirrors; split the slashed entries in tests/test_clean_checkout_semantics.py into a relpath set like conftest's _excluded_subtrees, so the 'clean source checkout' fixture stops copying the live blueprint chain and the 240 MB bench-results tree into the fixture it calls clean.


**What this does NOT reach.** It does not touch the conftest escape hatches (make-the-conftest-escape-hatches-work-as-documented) - those are about allowlists, these are about the enumeration itself.


**Why one class.** One acceptance run closes all three: run the suite on a tree carrying a .DS_Store, a dot-underscore sidecar, a populated cc/blueprints and a bench/results tree, and require green plus a fixture that is actually clean. DEF-479's five sister sites and DEF-489's three are the same predicate missing in different globs.


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c29"></a>

### §C29 — Hoist two pieces of repeated work out of their loops

**Unit of work.** Prune the _RESOLVE_SKIP directories DURING the walk in scripts/check_pack_fences.py instead of filtering after, so suite runtime stops scaling with whatever is sitting in dist/; compute the interpreter name once before the loop in espalier/doctor.py instead of re-running the same probe per broken entry.


**What this does NOT reach.** Neither changes any output; both are measured by wall-clock before and after, and neither should be graded by correctness.


**Why one class.** Two independent hoists sharing one acceptance criterion - measure the loop before and after. This is the only class in the ledger whose value is speed, which is exactly why it is kept apart from the correctness classes rather than tucked into one.


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c30"></a>

### §C30 — Derive every pack pre-flight obligation from the enforcer that would actually red

**Unit of work.** One pass over espalier/surface_impact.py: import espalier/mirror_registry.py and render every mirror advisory from its rows - VERIFIED, the registry is imported by tests only, so a row can declare the wrong direction and every guard stays green; give classify_surface an optional repo_root and consult mirror_registry.covers() so editing a curated mirror's SOURCE side names the sync script that must run; add docs/QUICKSTART.md to _hook_demands' hook-count site list, since QUICKSTART's 'twelve entry scripts' is the one hook-count claim no test pins; add a top-level tools/ branch plus an EXPECTED_ count and scan-root entry, since that tree is governed by none of the five surface mechanisms yet carries a CI job; pin the advisory's prefix set and verb demand to their enforcers' actual preconditions; and rewrite the advisory that contradicts _reinject's about the same sync script so both name its two refusal arms.


**What this does NOT reach.** It cannot fix the tools/cc side of any advisory by import - tools/cc/ may not import espalier, so the same repair lands twice and the mirror syncs must run. It also does not emit obligations for DELETED paths (emit-obligations-for-what-a-pack-deletes-or-renames), which is a LOGIC_BUG and counted separately.


**Why one class.** One file and one acceptance rule that closes every member: for each obligation the report emits, break the named thing and require the named enforcer to red; for each enforcer, require the report to name it. DEF-607's false demand has already propagated into authored pack text, which is the evidence that the emitter - not any single obligation - is the unit of work.


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c31"></a>

### §C31 — Teach the citation resolvers every anchor shape the repo actually writes, and promote skipped anchors to problems

**Unit of work.** Widen both anchor regexes in tests/test_catalog_self_consistency.py past the py-colon-line shape and promote silently-skipped anchors - drifted onto another content line, missing file, ambiguous basename - to reported problems; add a --collect-only sweep over docs/ node-ids requiring class-qualified ids, since ten cited node-ids collect zero tests, all unqualified class methods, and the AST resolver cannot see it because it flattens classes; validate the path half of self-repo blob/main URLs in tests/_artifact_links.py, where 26 deep-links in the README, pyproject and CLI resolve against nothing; add a rev-parse sweep over backticked commit hashes with a dead-by-design exclusion, the live rot being three dead hashes in the release checklist's hotfix lineage. Added 2026-09-26 (`DEF-936`): name the referent in the two `tests/test_rmtree.py` skip reasons that cite 'the sibling row above', a pointer no resolver reads.


**What this does NOT reach.** It covers references INSIDE this repo's tree. It does not resolve references in shipped text against the ADOPTER's tree - that is make-every-deployed-doc-reference-resolve-in-the-adopter-tree, a different inventory.


**Why one class.** Four citation shapes, one resolver surface, one acceptance test: seed one broken instance of each shape and require red. One member (`DEF-936`, added 2026-09-26) is a pointer no resolver reads, a `skipif` reason string; it is fixed by naming its referent and is outside the four-shape acceptance test. The class exists because each shape was added to the sweep separately and each new shape re-opened the same rot; the unit of work is 'every shape the repo writes', not any one regex.


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c32"></a>

### §C32 — Make the ledger's own enforcement parse every row shape the ledger actually uses

**Unit of work.** In tests/test_forward_ledger_completeness.py: count id-leading Appendix B rows that fail the index regex and assert zero - one malformed row is sitting there right now with the whole suite green; scan pack Scope-outs for TP ids and require a file or a ledger row, so work deferred into a pack nobody creates has a reader; parse a tracking table's status column so a bare drafted-pack cell with no pack id is visible; gate a strike on no open pack citing that section's number, which is the exact way section 2.3 was lost; add a DEF-id-in-tests vs open-row cross-reference probe run at /handoff; add an existence arm to test_cross_pack_assertions._is_enforceable_target, exempting archival folders; and name test_every_active_pack_is_ledger_tracked in the ledger's contract point 2 instead of the class that only drives synthetic temp trees.


**What this does NOT reach.** Three members currently catch NOTHING live - DEF-378a's ten bare drafted-pack lines are all vocabulary and census rows, DEF-416b's population is almost entirely archival, DEF-424a's gap catches nothing today. A pack must land them as recurrence guards and SAY SO, not claim it fixed live instances.


**Why one class.** One gate module, one ledger, one acceptance rule: introduce one instance of each shape into a fixture ledger and require red. This class is the reason a REBUILT ledger stays honest - land it WITH the rebuild, or the new file rots exactly the way the old one did.


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c33"></a>

### §C33 — Resolve every bench-corpus reference field and combo segment, then repoint the one that fails

**Unit of work.** In tests/test_corpus_documented_in_resolves.py resolve every ref field and every combo segment INCLUDING the out-of-scope rows - the gate skips 9 of 53 rows, reads 2 of 9 fields, and green-lights a multi-part reference on its first resolving fragment; then repoint the one bench corpus row whose documented_in names documentation that does not exist, and drop the out-of-scope exclusion.


**What this does NOT reach.** It is the bench corpus only; it does not resolve doc citations (teach-the-citation-resolvers-every-anchor-shape-the-repo-writes).


**Why one class.** The widening EXPOSES the instance: DEF-418b's excluded out-of-scope class is exactly where DEF-526's dead documented_in lives. Landing them apart means either landing the gate red or fixing an instance no gate protects. One pack, one red-then-green.


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c34"></a>

### §C34 — Derive mirror families from the byte-parity assertions so a row without a sync script is visible

**Unit of work.** Derive candidate mirror families in tests/test_reinject_sync.py from tests/ byte-parity assertions rather than from sync scripts - a family that arrives without one, as harness-guard did, is invisible to every census check; guard the unguarded split with has_sync and reword the misdescribing assertion message, so adding a sync-less row reports the real problem instead of crashing with a confusing error; assert every curated mirror name is slash-free in the parity test, so a subdirectory cannot silence the edit warning for every file inside it.


**What this does NOT reach.** It does not fix the sync scripts themselves (make-every-sync-command-leave-the-tree-converged) or the advisory text (make-every-surface-impact-obligation-name-a-real-enforcer).


**Why one class.** One test module, one acceptance test: add a synthetic sync-less mirror row with a subdirectory and require the census to see it and report the real problem. All three members are the same blind spot at three depths of the same guard.


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c35"></a>

### §C35 — Derive the cross-boundary duplicate register, then collapse what can collapse and pin what cannot

**Unit of work.** AST-derive the equal-valued pair set across the tools/cc <-> espalier no-import boundary and force each pair into _PINNED or a marker - the hand-kept register misses 8 of 26 duplicated names; then take the two collapses it exposes: delete _recall._split_sections and call _hook_utils.iter_doc_sections (two copies of one markdown section-splitter feeding one 'single owner' claim, and neither ignores headings inside fenced code blocks), and hoist the subagent-marker literal into _blueprint_limits.py in both trees, where four definitions exist and only two are forced by the boundary.


**What this does NOT reach.** It cannot collapse the pairs the import boundary FORCES - those must end up pinned, not merged. Census caveat to carry: the row's own example _AJ_MAX_FIELD_CHARS is now pinned, and CONVENTIONS' parity table holds 5 rows, not the 7 the row cites.


**Why one class.** Derive the population first, then act on it - that is one unit of work, and doing the two collapses without the register is exactly how the register came to miss 8 names. One acceptance criterion: every equal-valued cross-boundary pair is either collapsed or pinned, with no third state.


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c36"></a>

### §C36 — For each named assertion, write the mutation it claims to catch, watch it pass, then tighten until it reds

**Unit of work.** Seven guards, each closed the same way: assert set EQUALITY not membership in the rc=0 gate-status derivation, so an extra status cannot silently widen two CLI exit codes; probe every verb regex in test_write_guard, not only the ones that already carry the guard, so a new pattern that forgets it is visible; compare leaf CONTAINER TYPE per path in tests/_json_key_paths.py so a documented sample cannot collapse a whole dict into a single word; allowlist real commands and require a target-shaped subject field in the denial-actionability check, which any stray file path currently satisfies; seed the autoprune fixture DESCENDING and assert archived rows by date, since 'oldest' and 'first' are the same row today; assert the smaller deny-token list is a subset of the larger, pinning the three-token delta - by asserting, NEVER by widening the smaller list; and add a golden-string test over _explain_path.render() so a silent reword of what /status --explain prints is noticed.


**What this does NOT reach.** It closes only the SEVEN named guards. It does not enumerate the population - no scanner finds weak assertions - so the member list is the whole claim, and a pack must not report 'the class of weak assertions is closed'.


**Why one class.** The repairs differ per member but the ACCEPTANCE CRITERION is identical and mechanical: introduce the defect the guard claims to catch, confirm it passes today, tighten until it reds. That shared, per-member-provable criterion is what lets one pack honestly report every member closed - it is one method applied seven times, explicitly not one fix.


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c37"></a>

### §C37 — Replace four hand-kept gate populations with a derivation from the live source

**Unit of work.** Add a numeric-contract site enumerator reading the freshness cache plus the MIGRATIONS tuple, so re-pinning any count has a findable second site instead of reddening the suite with no pointer; derive tests/README.md's local-runs/CI-skips list from live skip reasons, since it names 4 files when at least 8 are gated that way and the majority of the class sits inside the blind spot the section exists to expose; derive the QUICKSTART banner test's LIVE_LABELS from the driven session_start output, since a hand-kept tuple reads a genuinely-new label as 'not emitted' and blocks a correct doc update; widen test_self_hosting's _reads_the_status predicate to the second spelling that status is written under, so a fifth copy cannot be added without reddening anything.


**What this does NOT reach.** It does not derive the record-surface registries (point-the-remaining-record-surface-registries-at-the-canon) or the mirror families (make-the-mirror-census-see-a-row-that-has-no-sync-script) - those have their own canons and their own packs.


**Why one class.** One repair verb with one acceptance criterion per member: add a real member to the live population and require the derived list to pick it up without an edit. Four gates, four sources, one sitting.


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c38"></a>

### §C38 — Give the two test-tree-only rules a product-code arm and an enforcer

**Unit of work.** Add a product-code arm to the EACCES-probe guard, keyed on probes whose caller swallows OSError, so the same defect outside tests/ stops being invisible; migrate the five test files that import a hook the way the test tree's own rules forbid to spec_from_file_location, and add the AST contract test that pins the rule nothing currently checks.


**What this does NOT reach.** The census warns that the obvious widening of the EACCES guard would produce a gate that matches nothing - a pack must key it on the caller-swallows-OSError shape, or ledger it, and must not ship a vacuous gate to claim the row.


**Why one class.** Both are rules the test tree obeys and the product tree is not checked against, and both are closed by the same act: state the rule once, and give it an enforcer that reads both trees.


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c39"></a>

### §C39 — Correct each cited comment against the code beside it, and delete every restated number

**Unit of work.** Ten independent one-to-ten-line corrections, each verified by reading the code the text sits on: delete the two stale sentences in surface_contract naming an export-ignore gap and an import cycle that are both closed, so they stop reading as owed work; correct the comment naming MANIFEST.in as the guard on the wheel-leak vector, since MANIFEST.in has no channel into a wheel and the real guard is package layout; capture the short SHA before the comparison in run_pack_chain.sh, or correct the claim that the commit-marker window contains no subprocess; annotate the false clause inside the 2026-08-05 release-decisions entry; delete the four count restatements in the reinject test comments, which say five/seven/ten rows when it holds fifteen; reword the rules-versus-rows comment to 'four rules covering five rows'; drop the counts from post_write_check's two self-host-gating rationale comments, which cite a registry size three times smaller than the live one; re-derive pack_manifest's 59-pack survey figure to 210, or drop it; drop the closed bypass bullet from the FAILURE_MODES open-residuals list and mark the surviving one WATCH; normalise the revisit-trigger label to one spelling and add it to the three bare entries that omit it.


**What this does NOT reach.** Two members sit on RECORD surfaces (the release-decisions log, the failure-modes catalog) - Core Rule 13 says classify the surface BEFORE editing; the repair there is to annotate or mark, never to rewrite the record. The class also does not add any missing index (give-both-catalog-docs-a-complete-generated-index).


**Why one class.** Ten independent edits sharing one rule that makes each provable: a comment may not restate a fact a reader can derive from the code beside it - so every member is closed by deleting the restatement or correcting it in place, and none needs a test. It is one SITTING under one rule, explicitly not one fix. That the DEF-478 ledger row's own numbers (12/14) are themselves now stale is the evidence that the rule, not any comment, is the unit.


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c40"></a>

### §C40 — Add the three catalog entries whose absence makes each review round re-derive the same lesson

**Unit of work.** Add a label-versus-fact entry to docs/SHARP_EDGES.md beside its two sibling oracle entries - the class has five attested instances and no canon entry, so each new review round re-derives it; add the shared-errno probe-table instance to the failure-modes section that tells a reader to 'pick the version-agnostic spelling', by POINTING at that section and never by restating the mechanism elsewhere; add a .git/info/exclude detector-blind-spot entry to SHARP_EDGES, since the lesson lives in four code comments and the changelog but not in the doc anyone reads.


**What this does NOT reach.** It buys re-derivation cost, not correctness: tests/_git_oracle.py already encodes the exclude blind spot mechanically, and DEF-415f's strongest instance is already fixed. A pack must not claim it closed any defect.


**Why one class.** Three entries, one catalog pair, one rule that keeps them honest: each entry points at its existing attested instances rather than restating the mechanism a second time. One sitting.


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c41"></a>

### §C41 — Generate a complete index into both catalog docs

**Unit of work.** Generate a table of contents into docs/SHARP_EDGES.md the way its two siblings built the same way already have one - it is 176 flat sections deep today; add the missing Part-II section to docs/CONVENTIONS.md's Contents index, which is the doc that documents this repo's index convention.


**What this does NOT reach.** Navigation only - neither changes any documented claim.


**Why one class.** Two catalog docs, one generator, one acceptance check: every section heading appears in the index. Kept apart from the claim-correction class because the repair is generation, not correction.


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c42"></a>

### §C42 — Make the conftest escape hatches behave the way the file's own idiom says they do

**Unit of work.** Re-watch cc/blueprints and allowlist the specific straddling tests, instead of the current state where the detector was removed rather than the write path - on a tree with no blueprint file the bootstrap still fires and nothing would see it; key _LIVE_TREE_ALLOWED on the bare module stem like its neighbouring sets, so a maintainer copying the file's own local idiom does not write an escape-hatch entry that silently does nothing.


**What this does NOT reach.** It does not fix any test's WRITE path - only the detector and the allowlist that are supposed to govern it.


**Why one class.** One file, one idiom, one acceptance check: write an allowlist entry the local idiom's way and require it to take effect; run a test that writes into the live blueprint chain and require the detector to catch it.


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c43"></a>

### §C43 — Prune the compiled-Python noise from the release walk and report what was pruned

**Unit of work.** Add a __pycache__ arm to release_pack._is_pruned_from_walk matching parts[:-1] like the venv arm - 615 compiled files are one seventh of the whole release report today; and add pruned-entry counts plus a skipped_self bucket to ReleasePackSummary.to_dict, because silencing the build-workspace noise also removed the only way to notice the workspace was stale.


**What this does NOT reach.** It does not change what SHIPS (build-the-release-zip-from-the-git-index-through-one-transient-predicate) - only what the report says it walked.


**Why one class.** The two members are two halves of one edit: DEF-417h exists BECAUSE silencing noise the DEF-417c way removes the signal. Landing the prune without the accounting reintroduces the defect the accounting exists to prevent.


_Both independent reclassification passes grouped these members._


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c44"></a>

### §C44 — Add safe_read_text and a scanner rule pinning the accepted unguarded-read population

**Unit of work.** Add a safe_read_text helper plus a scanner rule that pins the ACCEPTED population - 73 calls across 32 files in espalier/.


**What this does NOT reach.** The 70-site sweep itself is a settled accept-the-crash decision and must NOT be re-litigated - a pack that converts sites has misread the row. Fix the ceiling, not the sites.


**Why one class.** A class of one with 30 sister sites, kept single precisely because its unit of work is the CEILING: the accepted population silently grew by three because no helper and no ceiling exist. This is the clearest class-not-instance row in the ledger and the easiest to execute wrongly.


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c45"></a>

### §C46 — Work the four owed chores that no code change can close

**Unit of work.** Append a superseding god-file deferral decision citing HEAD's 1,748 LOC - the existing decision had already met its own 'revisit at 1,500 lines' trigger before it was written; fold the 2,640-line unreleased CHANGELOG section at the 0.8.0b1 cut; triage the 5 roadmap drains and 2 incomplete Landing stanzas that scripts/check_pack_landing.py prints on every run; and run the goalie workflow authored a fortnight ago to cover four parts of the codebase that have never been reviewed, and still has not been run.


**What this does NOT reach.** None of these is a code fix, so none can be verified by a test - each is closed by doing it and recording that it was done. PR-3/PR-5's other two clauses no longer describe anything real.


**Why one class.** Four chores sharing one property that must be counted separately from every code class: a green suite says nothing about them. The census graded all four population OPERATOR_ACTION, which is the instrument that keeps 'we are nearly ready' falsifiable.


⚠ **Blocked on:** PR-3/PR-5 is gated on DEF-536 (the 0.8.0b1 cut has not happened); the other three are actionable today


**Members**


| id | site | what | sev |
|---|---|---|---|


<a id="c48"></a>

### §C48 — Propagate DEC-25 to every live site still keyed on this tree going public

**Unit of work.** The release checklist's flip sequence models the world DEC-25 retracted. §"Pre-OSS first publish" tells the operator to `git remote add origin` and `git push -u origin main` on THIS tree at the moment it "becomes public" — but this tree already carries `origin`, `main` and 32 `v*` tags, and DEC-25 (2026-08-20) settled that it is NEVER published: the artifact is a NEW repo seeded from the generated


**Why one class.** Filed 2026-09-02 from the unledgered-owed sweep; both members share one root cause and one repair site, so fixing either alone leaves the other reachable.


**Members**


| id | site | what | sev |
|---|---|---|---|

<a id="c49"></a>

### §C51 — Make the forward work a shipped surface: rebuild the ledger to forward work only, fold the findings corpus into it, and move the shipping boundary and the codename gate with it

**Unit of work.** `DEC-31`'s pack: the forward work becomes a tracked, public surface of the
repo that hosts development, and everything that only made sense while it was private moves
with it in one pass — the ledger is rebuilt to forward work only (`DEF-705`), the findings
corpus folds into it (`DEF-706`), the shipping boundary flips for the ledger, its probes file
and the active packs (`DEF-707`), and the codename gate grows the arm that enforces a sensitive
name without shipping it (`DEF-708`). One pack can honestly report the class closed because the
seed is the acceptance test: the built archive carries the rebuilt ledger and nothing from the
internal set.

**What this does NOT reach.** The DEC-25 texts that describe the old plan are §C48's
(`DEF-709`); the record branch's push is a one-line chore in §C0 (`DEF-710`); Done, Deferred,
Merged, Scrapped, blueprints and reports stay untracked, regenerable history on the record
branch, by the operator's call on 2026-09-07.

**Why one class.** Four edits, one acceptance test, one moment: all four must land before the
seed and none is useful alone — a rebuilt ledger that still classifies `local_only` never
ships, a public ledger that still carries §7 ships the war stories, a fold without the gate
ships the scrub list. Sequenced at the start of the release-repo phase, after the
adopter-facing lanes, with the cut mechanical enough to re-run at seed time.

**Members**

| id | site | what | sev |
|---|---|---|---|

<a id="c52"></a>

<a id="c52"></a>

### §C52 — Make the adopter stop-time test gate real: run the override at the root and fail closed on a spawn it cannot make, give the command a committed home, and say on every default surface when Gate 1 is off

**Unit of work.** The stop-time test gate an adopter can switch on is an env-only override (`ESPALIER_STOP_GATE_TEST_CMD`) that `stop_gate.py` spawns from the hook's working directory rather than the repository root and reads as green when the spawn raises `OSError` (the `.cmd` spelling on Windows, a relative path from a drifted cwd), so a command that never started passes the gate; without the override the adopter has no stop-time test gate at all and nothing on the default surfaces says so; and the gate's mode and command have no committed home, so every clone and every teammate re-derives them (`DEC-35` in 4A decides the shape). One pack: run at the root, fail closed with an audit record, replace the test that pins the fail-open, print the gate's state where init and doctor already print the interpreter, and land the committed home once decided.

**What this does NOT reach.** The per-step proof the plan tracker records is self-attested (`espalier-issues/EI-03`, `DEF-645`'s maintainer twin); that is the plan layer, docs-only for now, not this gate. The pack-chain driver's own gates are `§C14`.

**Why one class.** One function family (`stop_gate.py`'s Gate 1 resolvers and its override runner), one byte-mirror, one oracle: a scratch adopter tree with a pinned test and an override that cannot spawn, driven through the deployed hook. The two members cannot land apart: fail-closed without a default-surface notice moves the silence one step, and a notice without fail-closed announces a gate that lies.

**Members**

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|

<a id="c53"></a>

### §C53 — Make every espalier.toml key either take effect or be named: warn on unknown and misplaced keys, enforce or retire the two zone keys, add the required-prefix knob, and make upgrade see a config edit

**Unit of work.** `load_config` accepts an unknown or misplaced `espalier.toml` key without a word, and `tests/test_config.py` pins that silence, so three keys an adopter reasonably writes do nothing and say nothing: `protected_paths` is read by no hook, a plan-required prefix knob does not exist (the exempt list is first-match with no required tier), and `upgrade` reports nothing to do after a config edit because it keys on the deployed version alone. The enabler is a warning on unknown and misplaced keys; once it exists the other three become loud instead of silent. Then enforce or retire the two zone keys, add the required-prefix knob as a deny tier of plan_guard, and make upgrade re-read the config.

**What this does NOT reach.** The audit log's location outside the repository (`DEF-943`) is a disclosure defect, not a config key; the workflow profile's allow rules (`§C57`) are derived from the fingerprint, not from the toml.

**Why one class.** One loader, one key vocabulary, one oracle: a scratch toml carrying a bogus key, a protected path and a required prefix, driven through init, doctor, upgrade and the two hooks that should read it. The enabler decides the shape of every other fix, so they land in one order and one pack.

**Members**

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|

<a id="c54"></a>

### §C54 — Stop the harness leaving home-path-shaped or archive-named files in an adopter's working tree, then pin every deployed asset and runtime writer against one small shape set

**Unit of work.** Three of the harness's own writers leave home-path-shaped or archive-named files in an adopter's working tree: the settings backup lands as `.claude/settings.json.bak` beside the tracked file (documented as intended in `docs/TROUBLESHOOTING.md`; the fork is relocate versus an exclude-this-path rule), the working summary carries the absolute path of the session transcript, and fourteen comment lines across three managed modules show home-path-shaped examples that an adopter's hygiene scan flags as leaked paths. Fix each writer, then pin every deployed asset and runtime writer against one small shape set so the class cannot regrow.

**What this does NOT reach.** Where the audit log lives (`DEF-943`) and where the init seeds land (`DEC-38`) are placement decisions, not shapes on disk. The gitignore block's omissions and line endings are `DEF-940`.

**Why one class.** One oracle: a disk-walking hygiene scan of a scratch adopter after a wire and after a driven compaction. One fix shape: a shape set the deploy inventory is pinned against, so a new writer is caught the day it lands rather than by the next adopter's scanner.

**Members**

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|

<a id="c55"></a>

### §C55 — Key every ownership reader on the predicate the uninstall deletes by: doctor's inventory and its uninstalled verdict stop claiming unmarked adopter files, and init prints a formatter-ignore snippet derived from what it wrote

**Unit of work.** Doctor's inventory and its uninstalled verdict are keyed on paths while `clean-generated` deletes by the managed marker, so an unmarked adopter file at a managed path is claimed by doctor and spared by the uninstall (extends the closed `DEF-770`, whose fixture pins the misread); and init writes twenty seeds and nine marked files into the adopter's namespace with no formatter-ignore snippet, so a Prettier-configured tree fails on every one of them. Key every ownership reader on the predicate the uninstall deletes by, and derive the ignore snippet from the same inventory of what init wrote.

**What this does NOT reach.** Whether the seeds move into a harness-owned namespace (`DEC-38`) and whether `clean-generated` reports or deletes its residue (`DEC-9`); this class works with the namespace as it is.

**Why one class.** One inventory of what init wrote and three readers of it; one oracle, a scratch init with an unmarked file at a managed path and a `.prettierrc` beside it.

**Members**

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|

<a id="c56"></a>

### §C56 — Read the effective CLAUDE.md through one helper that follows @ imports, so an adopter-owned CLAUDE.md draws no false NOTE from init and no false FAIL from /smoke

**Unit of work.** Two readers open `CLAUDE.md` as a literal file, init's section nudge and `/smoke`'s check 4, so an adopter whose `CLAUDE.md` is an `@`-import shell (the shape Claude Code documents) draws a false NOTE at init and a false FAIL at `/smoke` about sections and counts that are present one import away. One helper reads the effective document, following `@` imports the way Claude Code does, and both readers go through it or through the harness-owned inventory.

**What this does NOT reach.** Which file the two runtime denials should cite and the `src/` advice (`DEC-40`); the nudge's wording once it reads the right document.

**Why one class.** One helper, two call sites, one oracle: a scratch tree whose `CLAUDE.md` is a one-line `@` import of a file holding the sections, driven through init and the deployed `/smoke` fence.

**Members**

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|

<a id="c57"></a>

### §C57 — Replace the Python-shaped defaults a Node adopter inherits (a PATH-first /preflight, hand-copied source-extension lists, name-keyed gate relief, bare-binary allow rules and a bodiless optional roster) with ones derived from the fingerprint and espalier.toml, proven on one throwaway Node tree

**Unit of work.** Make a Node adopter a first-class reader of the defaults a Python-shaped harness ships: `/preflight` runs the repository's declared commands (`espalier.toml` `[extra_actions]`, then the fingerprint's inferred lint, test and build) before any PATH probe and never lints the vendored `tools/cc/` as adopter code; the three source-extension declarations name the ESM, TypeScript-module and component formats and take an additive `source_extensions` knob; stop-gate relief accepts adopter-declared reviewer and docs agents from `espalier.toml`, and the shipped reviewer and test-writer `tools:` lines carry a narrowed, fingerprint-derived runner; the workflow profile narrows every derived binary the way `DEF-714` narrowed `python` and ships its Python formatter rules only to a Python fingerprint; and the optional-agent roster either ships bodies or stops recommending them (`DEC-36` decides which).

**What this does NOT reach.** The `git add -A` staging in `/commit` (`DEF-944`), the `_handle_gitignore` omissions and line endings (`DEF-940`), the reflection walker (`DEF-942`) and the task_router keyword (`DEF-941`) were found on the same Node tree but are not Node-shaped; they are standalone rows. It does not decide the allow-list pack's intent (`DEC-37`) or the roster fork (`DEC-36`); it lands whichever way those are called.

**Why one class.** One oracle: `espalier init` into a throwaway Node tree, then drive the deployed `/preflight` fences, the hook predicates, the fingerprint, the rendered `settings.json` and `doctor` against it, with stub `ruff` and `pytest` first on PATH. Every member is a Python default read as universal, every member is measured on that one tree, and the extension lists and the gate relief cannot land apart: the lists arm the gates on about 5.4 times the files and the relief is who may pass them.

**Members**

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|

### §C58 — Make every shipped first-contact diagnostic report the adopter's tree, not the harness's own source: stand down or re-root the espalier/ coverage loops in /analyze and test-writer, guard code-reviewer's Phase 1 reads, make the advisor's dead-config pass skip managed bodies and say what it checked, and pin each fence on an init'd temp tree so an unguarded self-host path cannot re-enter

**Unit of work.** Three diagnostic fences shipped to every adopter read the harness's self-host layout as if it were the adopter's: the `/analyze` Step 3 coverage loop and TODO grep, the test-writer discovery loop, and the harness-config-advisor's dead-config pass. On a fresh `espalier init` tree with no `espalier/` they report a phantom module named `*`, list the vendored `tools/cc/` lines as the adopter's TODOs, and call 17 harness self-citations dead. Guard both loops on `espalier/`: without it, stand down or re-root to the adopter's roots and keep `tools/cc/` out of the TODO grep. Code-reviewer's Phase 1 fence, which prints a stand-down banner and then runs eight unguarded `espalier/` greps, takes the same guard. Make the dead-config pass skip managed bodies and placeholder names, report how many bodies and which prefixes it checked, drop its edit-the-regex comments, and read with an explicit encoding. Sync the two mirrors. Land one test that runs each deployed fence verbatim on two trees. On an init'd temp tree each must name the adopter's state or print a stand-down line; a stand-down line followed by more `espalier/` output (code-reviewer's `0` counts) fails, and the dead-config pass runs with UTF-8 mode off. On the harness tree the guarded fences print what they print today, and the advisor reads CLEAN while a cited module renamed in a copy is still flagged. That test pins the `[ -d espalier/ ]` convention, which nothing checks today.

**What this does NOT reach.** Whether the self-host-only citations should ship in adopter bodies at all is §C18's call (resolve shipped references against the deploy inventory); this class stops the diagnostics reporting them and deletes none. `/preflight` linting the vendored `tools/cc/` as adopter code belongs to §C57. Test-writer's `tools:` line and its Python-shaped test discovery belong to `DEF-963`. Docs-maintainer and architecture-analyst, which guard every `espalier/` read, change only if the new pin finds a gap in them.

**Why one class.** One acceptance rule and one oracle cover all three: `espalier init` into a throwaway tree holding `src/pkg/mod.py` and no `espalier/`, then run each deployed fence verbatim. Every member fails it the same way, by presenting a harness self-host path as an adopter finding. No test catches any of them today: none checks the `[ -d espalier/ ]` guard and none drives the dead-config pass. The edits differ: the loops need a guard or a new root, while the advisor needs managed-body, placeholder and reporting changes. But fixing one site leaves the convention unpinned for the others, and that is how three bodies drifted and code-reviewer kept only a banner while two siblings guard every read.

**Members**

| id | site | what | sev |
|---|---|---|---|

### §C59 — State the Python 3.10 tomli dependency on every install path, derived from pyproject's dependencies: change QUICKSTART's install line to README's wording and add a tomli step to the fuse handoff's FINISH_UP_STEPS, amending the fuse test that forbids that line, pinned by one contract test.

**Unit of work.** The engine has one runtime dependency, `tomli>=1.0` below Python 3.11. `pyproject.toml` declares it and the published wheel carries it, but two install surfaces a 3.10 user reads never say so. QUICKSTART's install section still claims zero third-party dependencies next to a 3.10 floor: README's copy was corrected on 2026-09-28 (current wording from 2026-09-29) and QUICKSTART's was not. The fusion is the one install path with no pyproject to declare anything, and its handoff never names tomli, although its manifest comment says it does. Read the marker-gated requirement from pyproject's `[project].dependencies` and check one install-surface roster against it: the `_FRONT_DOOR` docs in `tests/test_front_door_numbers.py` plus the `FINISH_UP_STEPS` strings. The work is one doc sentence, one tuple entry, an amendment to `tests/test_fuse.py::TestFuseStartHereAnchor::test_no_unconditional_tomli_advice` (which forbids the handoff line today), and one contract test. The test also pins README's correction, which nothing pins today. New prose and fixtures use README's 'from 3.11 on' form: the floor check reads 'Python 3.11+' as a second floor.

**What this does NOT reach.** Two follow-ups stay out, as separate rows if wanted: doctor reporting the configuration fallback in its warnings array instead of only on stderr, and the published 0.8.0b2 PyPI README that still says zero dependencies (fixed in-tree, so the next release ships the correct text). The scanner docs' stdlib-only claim is true and is not touched. README's Requirements list (Python 3.10+ alone) makes no dependency claim and is not edited. The plan_guard crash under tomli below 2.0 is the live `DEF-871`, a different defect.

**Why one class.** One rule covers both members: every install path a 3.10 user can take carries the tomli requirement. The wheel carries it in its metadata, so no front-door doc may contradict it with a zero-dependency claim beside a floor the marker covers; the fusion overlays no pyproject and so has no metadata, and its handoff must name it instead. One oracle (the marker read from pyproject), one roster and one contract test check both. The fuse test's contrary rule rests on 'pip install espalier pulls it', which holds for the doc path and misses the in-tree fusion, so the class test supersedes that assertion instead of coexisting with it. Fixing either member alone leaves the other 3.10 user uninformed.

**Members**

| id | site | what | sev |
|---|---|---|---|

### §C60 — Pin every shipped Python entry point's text I/O to UTF-8 so it runs to completion on a default-code-page Windows interpreter: espalier init, the /handoff and /read-summary CLIs in tools/cc, and the agent-body heredocs

**Unit of work.** Three layers of shipped Python move text through the default code page (cp1252 on Windows without UTF-8 mode): `espalier init`'s report in `espalier/cli.py`; the `/handoff`, `/read-summary` and `/reflect` CLIs in `tools/cc/` (`session_summary.py`, `read_summary.py`, `reflect_protocol.py --candidates`); and the heredocs in shipped agent bodies (the `harness-config-advisor` Dead-Config pass). Pin stdout and stderr to `encoding='utf-8'` at every entry, through one helper in `espalier/` and one in `tools/cc/` (neither may import the other; a fence pins inline), and pass `encoding='utf-8'` on every text read. Catch `UnicodeEncodeError` ahead of `ValueError` in `espalier/cli.py::main` and name it. Land env-stripped subprocess tests and two contracts. Streams: every top-level `tools/cc/*.py` module with a `__main__` (14) and every such `espalier/` module outside `_vendor` (13, none pinned) calls its layer's helper or is on a named allowlist, hooks excluded; of the 14, `execution_plan.py` pins UTF-8; `check_ledger_probes.py`, `generate_ledger_regions.py` and `ledger_row.py` set `errors=` only, and each moves to the helper or is allowlisted with a reason; ten are unpinned, six not yet driven (`ship.py`, `session_resume.py`, `statusline.py`, `sister_site_probe.py`, `memory_sort_audit.py`, `ci_guard.py`). Reads: a collector pulls every heredoc body and `python -c` string from every fence under `.claude/**/*.md`, whatever its tag, shell comments skipped; a body that does not parse fails, and every `read_text` and text-mode `open(` in one passes `encoding=`, checked by `ast`. Widen `tests/test_portability_contract.py::TestNoNonAsciiInRuntimePrints`, whose net misses the list-literal em-dash constants `tools/cc/session_summary.py` prints; the stream pin stays the acceptance rule. Run `scripts/sync_vendor_cc.py` and `scripts/sync_claude_mirrors.py` last.

**What this does NOT reach.** Hook stdout is out of scope: it is `json.dumps` with `ensure_ascii` on, and the review read it clean. So are the hook-side `.py` read sites `CLO-15` declines behind their `BaseException` guard, and the decode-guard census and file-less catch in `espalier/cli.py::main` that `DEF-835` owns; this class adds only the `UnicodeEncodeError` arm ahead of that catch. It leaves alone the three entry points the closed `DEF-921` already pinned, and a real console, whose writes go through the wide-character API and should be unaffected (probable, not driven). The bare JSON reads in `.claude/agents/repo-analyst.md` and `.claude/commands/smoke.md` are ASCII on a fresh tree, so they are not members; the read contract reaches them and the fix pins them as hygiene. Live `DEF-975`'s fix shape carries collectors in `tests/test_portability_contract.py` (command-body code blocks among them), a `newline=` rule in `espalier/scanners/encoding_contracts.py`, and an axis registry under `tests/` over stack, host and session path. Of those surfaces this class lands only a fence collector, used here by the `encoding=` contract, which `DEF-975`'s code-block collector can reuse; this draft also proposes adding to that registry the interpreter-environment axis (`PYTHONUTF8`, the locale) that hid this class. It does not wait on PEP 686: UTF-8 mode becomes the default only in Python 3.15, and the floor is 3.10.

**Why one class.** One defect and one method cover all three: text crosses the default code page, and the fix is the same pin at every entry, one helper per layer. The runtime oracle is an env-stripped subprocess over each shipped entry point: every `PYTHON*` variable removed, stdout piped, `PYTHONIOENCODING=cp1252`, and fixture content outside cp1252 (a repository name, a tracked path, a commit subject, summary text, a shipped body). That reproduces the stream half on any host. The read half decodes through the locale, which `PYTHONIOENCODING` does not touch, so on a UTF-8 locale the subprocess oracle passes a stdout-only fix; every required CI cell is ubuntu, and the per-pull-request Windows leg (`portability.yml`) is advisory. The read half's acceptance rule is therefore the static `ast` contract over the fences, which the probe of the row on `.claude/agents/harness-config-advisor.md` also checks. `DEF-921` pinned three entry points one at a time; this class is what was left, and `STANDING_PRINCIPLES` §18 says a class is fixed in place, not one site at a time. On the operator's hosts `PYTHONUTF8=1` (Windows) or a UTF-8 locale (macOS; probable, not driven) hides every member, which is why the class surfaced only when a review stripped the environment.

**Members**

| id | site | what | sev |
|---|---|---|---|

### §C61 — Make the Bash protected-zone reader deny only what a real shell would write under a zone: relieve quoted mentions after an earlier substitution, inside a quoted substitution, behind gh text flags and inside compound commands, and place a cd target bound in the same command

**Unit of work.** The Bash protected-zone check in `tools/cc/hooks/write_guard.py::check_bash_for_protected_mutations` hard-denies five shapes in which a real shell writes nothing under a zone: a heredoc body after an earlier unquoted substitution, a heredoc inside a double-quoted substitution (Claude Code's own commit form), a quoted text flag of `gh`, a quoted mention inside an if, for, while or until body, a group, a subshell or a function, and a relative write after `cd` into a variable bound in the same command or into the parent of a `mkdir -p` operand. Each deny carries a maintenance relaunch as its only stated remedy, on the shipped hook (the vendored copy is byte-identical). The unit is the reader, `tools/cc/hooks/_bash_patterns.py` (the masker, the role walker and the directory chain), fixed per mechanism; every relief lands with ALLOW rows in `tests/test_guard_false_positives.py` driven by `_tier`, each paired with a must-deny twin that really writes, cross-checked against a real shell or through `bench/reachability_differential.py`, and with `scripts/sync_vendor_cc.py` run after. The cd fix also lands one new deny, a variable bound into a zone (`S=.claude; cd "$S"` then a relative write, a real write allowed today), with its must-deny row, and corrects `docs/HOOKS.md` where it describes the directory chain, then runs `scripts/sync_asset_docs.py` for its `espalier/assets/docs/` mirror.

**What this does NOT reach.** A write target that is itself a variable the walk cannot read, `cd "$UNBOUND"` or `cat` into `"$TMPDIR/x"` after `cd tools/cc`: the declared indirection tier keeps its HARD verdict. The deny's remedy wording, which names only the maintenance relaunch (the neighbour of `DEF-910`). The PowerShell reader, where the matching `if ($true) { ... }` shape is already allowed. The fail-open neighbour `DEF-884` (a redirect target keeping its closer) and evasion shapes such as `CLO-46`.

**Why one class.** One acceptance rule, one oracle, one method: a Bash protected-zone HARD deny fires only when a real shell running the command writes under a zone, and each misread is proven by an ALLOW row driven through `_tier` beside a must-deny twin that a real shell shows writing. All five live in one reader and fail the same tier the same way; the edits differ per mechanism, so the rows are split by site and a partial landing strikes only the row it fixed.

**Members**

| id | site | what | sev |
|---|---|---|---|

### §C62 — Make the harness's own reflect oracles report nothing a fresh adopter did not cause: take init-seeded and loader-reached surfaces out of the orphan check on both twins, parse headings by CommonMark in the sparse-section check, and name the flagged files in the reflect_trigger advisory

**Unit of work.** Both halves of reflect read a freshly initialised tree as drifted. The hook twin that `reflect_trigger` runs and the engine twin that `/preflight` Step 5 runs each report six orphans that are init's own seeds; the engine twin adds 46 empty sections that are its heading parser misreading the markdown init writes; and an unlinked `.claude/rules/` file, which Claude Code's own loader reads at launch or on a path match, adds one phantom orphan apiece. The advisory that carries this to the model gives counts and no file names. Take init-seeded surfaces and `.claude/rules/` out of the orphan kind on both forced twins (through the orphan exemption, not the discovery dirs, so the residue and quality checks still run on them), make `_section_density` fence-, indent- and level-aware, and put the flagged files' names in the `additionalContext`.

**What this does NOT reach.** Which docs init seeds at all (`DEC-30`) and whether the seeds move into a harness-owned namespace (`DEC-38`); either could change the seeded-orphan count, and an exemption keyed on what init wrote holds whichever way they go. Record-surface docs on the self-host tree read as link rot (`DEF-765`) are a different population under a different exemption. The harness adopting `.claude/rules/` for its own instructions is a separate, deferred feature; this class only stops reflect misreporting an adopter's rules.

**Why one class.** One acceptance rule and one oracle. Init into `tmp_path`, then add two unlinked rule files, a rules file testing.md and a nested one sub/scoped.md under .claude/rules/ (with `paths` frontmatter), an unlinked `docs/mine-control.md`, and a `docs/heading-control.md` holding one real same-level empty heading, linked from `CLAUDE.md` so it is no orphan. Give every added file at least three content lines, so the short-doc and empty-section signals the fix keeps stay quiet, and a name no seed's text contains, since both twins' basename fallback is a substring match. Drive the hook twin's `--json`, `espalier reflect-deep` and `reflect_trigger` over it. Fixed means the hook twin's only finding is the orphan control and the advisory names it, while reflect-deep shows that orphan plus the one empty section and nothing else. The advisory never carries the empty section, because the hook twin has no sparse-section check. Driven 2026-10-01, it is red today: both twins list the six seed orphans, both rule files and the control, and reflect-deep counts 47 empty sections, 46 of them in nine files init writes. Each member is the harness's own oracle reporting on what the harness or Claude Code put on disk rather than on what the adopter changed, and the four edits are proven by that one fixture.

**Members**

| id | site | what | sev |
|---|---|---|---|

### §C63 — Route every exit-0 hook advisory to a channel the pinned protocol says reaches Claude (the SessionStart banner or PostToolUse additionalContext) or to a say_once record, and stop the voice gate counting debug-log stderr as speech

**Unit of work.** Exit-0 hooks speak on stderr, which the repo's protocol pin (`docs/external/cc-hook-protocol.md`) sends to the debug log only. One gated rule: no stderr write on an exit-0 hook path is a hook's only voice. Each pairs with additionalContext in the hook's ONE stdout JSON object (the pin's channel to Claude; not systemMessage, which it gives no audience), or a `say_once` record `/status --log` counts, or declares the debug log on purpose. Declarations include the sinks' own bodies (`tools/cc/hooks/_hook_utils.py::warn`, `::warn_exc`), `tools/cc/hooks/_integrity.py::append_audit` (say_once calls it) and `::tail_audit` (read only by the `/status` CLI), the bypass line in `tools/cc/hooks/_maintenance_mode.py::is_active` (debug log by design per root CLAUDE.md), post_compact's re-orientation block (see not_reach), exit-2 paths, and the DEF-949 dormancy notes the banner already twins. Repairs: session_start's reporter and builder warnings join the banner; post_write_check and reflect_trigger fold theirs into their JSON object; the eight reporter crash guards, config_guard's scan arm, post_compact's four, stop_gate's fingerprint read and both Gate 1 skips go through `say_once`; the call-site census finds the rest; `scripts/sync_vendor_cc.py` and `scripts/sync_asset_docs.py` refresh the mirrors. In-lane old-belief consumers: two unreleased CHANGELOG.md sentences; both `docs/HOOKS.md` copies; the root CLAUDE.md hooks row (post_compact's re-injection claim), its adopter template in `espalier/cli.py::_build_claude_md` and the rendered `examples/CLAUDE.template.md`; post_compact's re-injection claim at every other copy (the design skill, the implement-pack command, the HOOKS.md section-8 'What you see' block, relabelled as debug-log output, three places in `docs/HOOK_ASSUMPTIONS.md`, FAILURE_MODES 11.3 and 11.4, the hook's own docstrings, comments and warn string, and the undeployed SECURITY_TAXONOMY, SURFACE_SUPPORT_MATRIX and post-compact memory note), with `tests/test_operator_docs.py::TestPostCompactDocsTruth` widened from two named files to a derived sweep of tracked Markdown and the rendered CLAUDE.md that excludes the forward ledger, the record surfaces, CHANGELOG.md and ESPALIER_MEMORY.md, the surfaces a fix writes prose on; the reporter rule in `docs/CONVENTIONS.md` and `memory/hook-authoring.md`; the docstrings that promise visibility; the boot-warning test that pins stderr; a correction appended to the closed `DEF-948`'s closure; a note on the open `DEF-722`, whose fix prints to the same stderr; and the demo pair, `bench/demo/STORYBOARD.md` (the channel table in its no-banner section) and `bench/demo/RECORDING.md` (steps 7 and 8), whose channel table is the operator-facing rendering of the same rule and must agree with whatever wording the relabel lands on (`DEF-1069`).

**What this does NOT reach.** The fail-open decisions themselves: fail-open stays allowed (`docs/STANDING_PRINCIPLES.md` §2) and the four blocking hooks' umbrella crash guards stay fail-closed; only the voice changes. Exit-1 and exit-2 paths, the PreToolUse deny and the Stop block, which the pin calls seen. Nor ConfigChange's block, though the pin says a blocked change surfaces no message to anyone and `tools/cc/hooks/config_guard.py` blocks through exactly that channel: that silent block is a separate defect with no row yet, named here so it is not read as covered. post_compact's re-orientation block itself: PostCompact has no channel to Claude under the pin (no additionalContext row, systemMessage discarded, exit 2 reaches the user only), and the pin's `compact` source re-fires SessionStart, whose banner re-orients the session (probable; the two outputs were not compared), so the block is declared and only its doc claims are in-lane. post_write_check's action-justification nudge, which pairs its stderr line with its own audit record (the call-site census accepts that) and fires per write by design; whether Claude should see it on every write is a rate call this class does not make. The detected-command fork in `DEF-949` step 4, the interpreter first-word extractor (`DEF-968`), and the non-UTF-8 read sweep §6 declines (`CLO-15`). It does not observe a live session: the pin is the oracle, and an upstream change reopens the pin, not this class.

**Why one class.** One false belief, that exit-0 stderr is seen, written into the SessionStart reporters, the PostToolUse hooks, the crash guards, a test gate and the docs; the 2026-10-01 re-excerpt of the pin corrected the pin and five maintenance-bypass claims and none of these consumers. One rule, a derived gate in two parts and a witness per row. The gate: split the voice gate's handler census into recorded and stderr-only speakers so an undeclared stderr-only handler reds; and, because that census walks only deciding except handlers while most SessionStart reporter lines and PostToolUse warnings sit outside one, add a derived AST census of every warn, warn_exc, print(file=sys.stderr) and sys.stderr.write call in `tools/cc/hooks/`, each paired within its enclosing statement block or branch with a seen speaker (a collector the hook renders into its JSON object, or a record) or declared, so a new stderr-only reporter line reds (function scope is too wide: `tools/cc/hooks/stop_gate.py::_gate_pytest` records on other branches beside both Gate 1 skips). The witnesses drive each row's hook in a scratch tree and assert the text sits inside one stdout JSON object or an audit row exists under `ESPALIER_AUDIT_DIR`. Fixing one hook leaves the gate certifying the rest, and fixing the gate alone moves no line to a seen channel. Five findings make three rows: two pairs reported one defect each (the boot warnings, the gate).

**Members**

| id | site | what | sev |
|---|---|---|---|

### §C64 — Make the onboarding probes re-derive their own rows: ONB-1 closes once the goal is written and stays open while an opted-out tree keeps an unset cc/GOAL.md, and ONB-1, ONB-6 and ONB-7 decode their files the way the harness's own readers do

**Unit of work.** The onboarding rows `espalier init` files into an adopter's forward ledger carry probes meant to re-derive each row's claim, and they misread it three ways. ONB-1 asks whether a placeholder the skeleton seeds twice appears anywhere in `cc/GOAL.md`, so writing the goal does not close it. ONB-1 closes on the opt-out key alone while the skeleton the row says to delete is still shown at every session start. And ONB-1, ONB-6 and ONB-7 decode strict UTF-8 where the harness's own readers of the same files read a UTF-8, UTF-16 or UTF-32 byte-order mark and refuse text carrying a NUL (`tools/cc/_json_safe.py::decode_text_or_problem`, for the goal), treat an undecodable stub as edited (`espalier/cli.py::_seed_redeploy_decision`), or treat an undecodable `espalier.toml` as setting no key (`espalier/config.py::load_config`). Make each probe in `espalier/cli.py::_ONBOARDING_ROWS` answer what its row's text asks, decoding each file the way its harness reader does, and pin it with one truth table that drives every probe through the checker's argv split over the states its row names: untouched, done as asked, goal written with the key set, opted out with the skeleton kept, opted out and deleted, a goal or stub hand-saved as UTF-16 with and without a byte-order mark, UTF-32 or cp1252, and an `espalier.toml` saved as UTF-16. The fix edits `espalier/cli.py`, which no row of `espalier/mirror_registry.py::MIRROR_ROWS` mirrors, and `tests/test_cli_deploy.py`, which is outside the selfcheck subset (`scripts/sync_selfcheck_tests.py::BYTE_MIRRORED`), so no sync script runs.

**What this does NOT reach.** The rows that declare why nothing on disk can tell (ONB-2 to ONB-5), and the top-level key test ONB-1 and ONB-6 share, apart from its decode: an `espalier.toml` saved as UTF-8 with a byte-order mark decodes cleanly while the readers' TOML parse rejects it and treats every key as unset, so the probes' line match can find a key the readers ignore; a stdlib-only line probe cannot reproduce a TOML parser's rejection in general on a 3.10 host without tomli, and plan_guard announces the malformed file on each gated write, so that case stays out. Not the checker's verdict on an erroring probe (`tools/cc/check_ledger_probes.py::run_probe` is right to call a broken probe UNRESOLVED), not the shared decoder's choice to reject cp1252, not `espalier/config.py::load_config`'s choice to read the config as UTF-8 only, and not the census of unguarded engine reads (§C44), whose population of `espalier/` call nodes these string-literal probes, run inside the adopter's tree, sit outside.

**Why one class.** One tuple, three probe expressions, one acceptance rule (a probe's verdict equals what its row's text and the harness's reader of the same file say) and one oracle: the verdict truth table this class lands in `tests/test_cli_deploy.py::TestOnboardingProbesDoNotWalk`, which today pins walk markers, the argv split, row shape and a key-placement verdict pair for each key probe (ONB-1 and ONB-6), but no verdict over the goal file's states or any file's encoding. The goal-section and opt-out fixes are one edit to the ONB-1 expression, and the decode fix rides the same edit plus ONB-6's and ONB-7's, so filing them apart would land the same lines three times; if the operator prefers one standalone row, the same edit holds.

**Members**

| id | site | what | sev |
|---|---|---|---|

### §C65 — Make the recursive-remove verdicts agree with the deny texts that predict them: before the drive-depth wall, compare a drive path as typed against the repo and home and let a match lift only that wall, read a drive path's depth one way on Bash and PowerShell, and have the drop -Force remedy and the HOOKS.md sentence name what the unforced tier refuses, pinned by drive rows added to the driven claims table in tests/test_denial_reasons.py

**Unit of work.** On the PowerShell tool, `tools/cc/hooks/_bash_patterns.py::_ps_sweep_root_is_catastrophic` walls every drive path two or fewer levels under its drive root before `::_target_is_catastrophic` asks whether the path sits inside the repo or the home directory. So the unforced recursive remove and the piped sweep refuse a direct child of a repo checked out one level under a drive root, on the tier maintenance mode cannot bypass, while the deny text says such a path is not refused. The Bash tool reads the same path through `_target_is_catastrophic` alone and counts the drive letter as a component, so the two tools disagree on drive paths. And the forced-form deny `tools/cc/hooks/_denial_reasons.py::DANGEROUS_PS_PATTERN_FALLBACK` tells the operator that without `-Force` any path other than a drive root, the home directory and the repo draws one nudge, which the unforced tier contradicts on every shallow drive path. Before the drive-depth rule, compare a drive path as typed against the repo and the home directory. A match only lifts the drive-depth rule: the path still goes to `_target_is_catastrophic`, whose identity, ancestor and `..` rules still apply, so `C:\myapp\..` stays walled. Do not move the rule into step (c) of `_target_is_catastrophic`: its containment goes through `_posix`, which on a POSIX host resolves `C:/...` against the process directory, so the drive wall would fall to the nudge there. That is why the PowerShell judge runs its drive leg first. Decide the drive-depth reading once for both tools. Make every deny text that predicts a verdict name the classes that verdict draws, with the deny texts and `docs/HOOKS.md` built from one phrase where they can. That covers the drop -Force clause, the two PowerShell wall texts, and the CP-RMRF nudge tail `tools/cc/hooks/_speedbump.py::_RMRF_TAIL`. That tail tells a nudged Bash `rm -rf C:/Windows/System32` that write_guard hard-blocks shallow system paths, and no test drives that claim against a drive path. Mirrors: run scripts/sync_vendor_cc.py for the vendored copies of `_bash_patterns.py`, `_denial_reasons.py` and `_speedbump.py` under espalier/_vendor/cc/hooks/, and scripts/sync_asset_docs.py for espalier/assets/docs/HOOKS.md.

**What this does NOT reach.** The wall on shallow drive paths outside the repo, the home directory and the temp roots stays. `C:\Windows\System32`, `C:\Users` and `C:\work` remain refused on PowerShell, as `tests/test_guard_false_positives.py::PS_TIERS` pins by an earlier code-review decision; this class makes the texts describe that wall and does not remove it. Each of these is its own unit and stays out: the forced form's deliberately wider wall on every absolute or variable target, the glob relief missing from the forced reader (`DEF-859`), the ephemeral roster (`DEF-899`), UNC and device prefixes (`DEF-935`), and the 8.3 short-name evasion recorded closed as `CLO-46`.

**Why one class.** The two members need different repairs, one in code and one in text, and neither repair makes the other's claim true. Running containment first still leaves every shallow drive path outside the repo walled, so the drop -Force remedy stays false. No rewrite of the remedy can honestly promise in-repo relief until containment runs first. They share one oracle, and it already exists: the driven claims table in tests/test_denial_reasons.py, which drives each claim of the wall texts through Bash `rm -rf` and `rm -r`, unforced `Remove-Item -Recurse` and the PowerShell sweep spellings. It asks only POSIX targets with a deep repo, so it never reaches this defect. The class adds its rows there, not to a second table that would drift from it: a repo one level under a drive root as the root, a direct child of that repo, `<repo>\..`, `C:/Temp/x`, `C:/Windows/System32`, and the forced spelling. With those pins kept, parity has one direction: Bash adopts the PowerShell reading, which adds a refusal (`rm -rf C:/work/old` becomes a wall), the false-positive direction the toolbelt frame ranks first, so it lands only with the row that proves it, or the pack documents the difference instead.

**Members**

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|

### §C66 — Make write_guard's three quote-blind word cutters honour quotes, so the secret-read legs and the env-prefix claude scan see a quoted spaced path or string as one word, and never read a string's first word as a verb

**Status, 2026-10-05.** One member landed: the two secret-read legs cut their operands quote-aware (`tools/cc/hooks/write_guard.py::_quote_aware_words`, plainly written statements only; `DEF-1043` struck). The other two wait on the carrier reader `DEF-1131`, both on a measurement: a quote-aware nested-launch scan allowed six launches HEAD refuses (`DEF-1044`), and a quote-aware PowerShell head allowed strings a later statement runs (`DEF-1045`). The paragraphs below are the class as filed.

**Unit of work.** Three call sites in `tools/cc/hooks/write_guard.py` cut a shell command into words with a separator class that ignores quotes: the nested-launch scan `_statement_launches_claude` and the Bash secret leg `_secret_read_targets_one` through `_TOKEN_SPLIT_RE` (blanks plus `;|&()` and the backtick), and the PowerShell secret leg `_ps_secret_read_targets` through `_PS_SECRET_TOKEN_SPLIT_RE` (blanks plus the comma). A quoted word with a blank inside is judged one fragment at a time, and three different users are refused for something they did not do: a spaced path read as a secret or named by a fragment, a documented-allowed test run read as a nested agent launch, and a string read as a command. The fix changes where a word ends only inside quotes: one cut, parameterised by each site's own separator class, in which a quoted span glues and every separator still cuts outside quotes, so `Get-Content a.txt,.env`, `(cat .env)` and PowerShell's `$(which claude)` keep their cuts. It is built from the quote arms of `_QUOTED_OR_BARE_OPERAND` in `_bash_patterns`, which keep backslashes literal as a Windows path needs, with the bare arm's excluded set widened to the site's separators and adjacent spans glued into one word; not from `_shell_word_spans`, which reads a backslash as an escape and so would read a path ending in a backslash before its closing quote as an unterminated quote. It falls back to today's split on an unterminated quote and unquotes each word after the cut, so a quoted head is folded exactly as a bare one is today; that newly refuses three dotenv reads HEAD allows, listed with the oracle's must-deny rows. The nested-launch scan keeps its reach into quoted program text by re-running on the bodies `_posix_shell_c_bodies`, `_shell_program_bodies` and `_ps_shell_program_bodies` return, read from the assignment's start. It lands under maintenance mode, since `tools/cc/` is a protected zone, with `scripts/sync_vendor_cc.py` run for the vendored mirror.

**What this does NOT reach.** The delete-operand separator classes in `_bash_patterns` that cut a path at `&` or `;` (`DEF-927`: a different reader and a different character class), the redirect capture that keeps a closing bracket (`DEF-884`), the env-variable roster (`DEF-972`) and the hook's spawn cost (`DEF-946`). Shell-expansion name-hiding stays out of scope with `bench/corpus/BC-OOS-004`. The Bash leg reads masked text, so after the fix `cat "a;b/.env"` is still denied but named `a b/.env`. The class leaves the verb roster, the variable roster and the cuts outside quotes as they are, but it does change which shapes are refused: unquoting a head before the fold newly denies Bash `"cat" .env`, Bash `"/c/Program Files/Git/usr/bin/cat" .env` and PowerShell `& 'C:\Program Files\Git\usr\bin\cat.exe' .env`, all three allowed at HEAD and all three reads of a dotenv; they land as must-deny rows.

**Why one class.** One defect shape, quote-blind word cutting, at three call sites in one file, fixed by one helper and proven by one oracle: the real hook driven over a population of quoted spaced operands on both shells. Must-allow rows: a spaced non-secret path, a spaced `Claude Code` path behind an env prefix, a string in an assignment or in parentheses. Must-deny rows held today: a spaced dotenv (denied today under a partial name; named whole once fixed), `Get-Content a.txt,.env`, `(cat .env)`, the bare backtick statement `` `cat .env` ``, Bash `ESPALIER_MAINTENANCE_MODE=1 $(which claude) -p x`, the PowerShell `$env:ESPALIER_MAINTENANCE_MODE=1; $(which claude) -p x` and `$env:ESPALIER_MAINTENANCE_MODE=1; (claude) -p x`, `sh -c 'claude -p x'` behind a prefix, `$x = Get-Content .env` and `& 'Get-Content' .env`. Must-deny rows the class gains, each allowed at HEAD: Bash `"cat" .env`, Bash `"/c/Program Files/Git/usr/bin/cat" .env` and PowerShell `& 'C:\Program Files\Git\usr\bin\cat.exe' .env`. Driven in-process at HEAD with the two regexes and the scan patched in memory, the class's cut plus the body read allowed every must-allow row and denied every must-deny row. A quote-aware cut on blanks alone, measured the same way, reopened `Get-Content a.txt,.env`, `(cat .env)`, the bare backtick statement and both PowerShell `$(which claude)` and `(claude)` rows; the Bash `$(which claude)` row stayed denied, because the Bash masker blanks `$(which ` before the scan while the PowerShell scan text keeps it. The members stay separate rows because each hurts a different user and a fix can close one while leaving another: unquoting operands alone leaves the PowerShell head open, and a quote-aware scan without the body read closes the nested-launch false positive while opening `sh -c 'claude -p x'`.

**Members**

| id | site | what | sev |
|---|---|---|---|

### §C67 — Make the drift check compare signals, not census: reduce every census-valued field in espalier/diffing.py's two normalizers to the signal it carries, so doctor stays green after an ordinary commit, a lock-file bump or a new docs page and still flips on a new CI provider, framework or language

**Unit of work.** `espalier/diffing.py::_normalize_fingerprint` and `espalier/diffing.py::_normalize_plan` compare census-valued fields verbatim: recent commit subjects and a running confidence ratio, per-language file counts, the byte sizes and line counts of large files, a per-page docs listing echoed into signals, conventions and agent scopes, and a count-ordered language list. Each one turns `espalier doctor` yellow and makes `espalier diff` exit 1 on ordinary work the docs say the fingerprint ignores. Classify every `espalier/models.py::RepoFingerprint` field as signal or census (the three members are the measured ones; `garbage_files`, `confidence`, `notes`, `architecture` and the entrypoint and runtime listings are unclassified candidates), then reduce each census field in the two normalizers to the signal it carries: a format, a set, a presence, or a set of names. Name every dropped field in the `ignored_local_only_keys` lists of `espalier/diffing.py::_diff_generic` and `espalier/diffing.py::_diff_self_host` so the report stays honest. The saved fingerprint keeps its fields; only the comparison changes. Neither `espalier/diffing.py` nor `tests/test_diffing.py` has a mirror (the selfcheck test subset under `espalier/_vendor/selfcheck_tests/` leaves `tests/test_diffing.py` out). In the same lane, rewrite `tests/test_diffing.py::TestDiffRepo`'s `test_detects_fingerprint_change`, which pins census drift (a new `.py` file must flip), to a signal change, and its sibling `test_changed_keys_list_is_populated`, whose assertion sits under `if result["fingerprint_changed"]:` and would pass vacuously after the fix. Three operator calls sit inside the unit: whether `languages[0]` (the primary language, read by `espalier/cli.py`) stays a signal, in which case a swap at the top flips by design; whether `large_files` reduces to a bool or to a path set; and whether crossing `espalier/profiles.py::classify_repo`'s `docs_heavy` threshold, scored on the raw docs list, stays a signal.

**What this does NOT reach.** Retired schema keys read as drift (`DEF-911`) sit in the same two normalizers with a different cause; land beside it, not inside it. The walk scope of the same detectors (`DEF-971`) and the walk's cost (`CLO-32`) are their own records. It does not change what the fingerprint saves, how doctor grades a drift warning or its exit code, or the self-host surface comparison of agents, commands and hooks, which is already set-valued. Census questions (how many tests, modules or lines) stay answered where the docs' fingerprint section already sends them: a grep of the live tree and `tests/test_documented_claims.py::TestNoStaleNumericContracts`.

**Why one class.** One acceptance rule and one oracle cover every member: re-baseline a throwaway repo, then each ordinary-work mutation (an empty commit, a commit with a non-matching subject, a commit adding a source file in an existing language, a one-line append to a file of 200 KB or more, a new docs page that sorts first on a tree already past the `docs_heavy` threshold, a language-rank swap below first place, since a swap at the top follows the `languages[0]` call) must leave `fingerprint_changed` and `build_plan_changed` False and doctor's diff check `pass`, while each signal mutation (a new CI provider or framework, a new language, the first docs page, the first large file) must still flip. The per-field reductions differ, which is one acceptance rule, not always one edit. Patching one field at a time leaves doctor yellow on the next: the large-file probe tree changes only `large_files`, a key the commit member's fix never touches.

**Members**

| id | site | what | sev |
|---|---|---|---|

### §C68 — Name the approval marker wherever the harness writes a Harness-Guard-protected path git will commit: install-ci, fuse, upgrade --execute, a re-run init and merge-settings on a tracked settings file tell the adopter that the commit carrying those files needs HARNESS-UPDATE-APPROVED

**Unit of work.** Five commands write files the CI gate protects, and the adopter's next step is to commit and push them: `install-ci` (the guard script and workflow, beside the hook files `init` wrote), `fuse` (the whole overlay), `upgrade --execute` (every drifted hook), `init` re-run over an install-ci tree (it regenerates every drifted hook and lists the paths; driven, the commit carrying one exits 2 on push and on pull request with no marker in init's output) and `espalier/cli.py::cmd_merge_settings` on a repository that already tracked `.claude/settings.json`, where init withholds that ignore entry (driven: the wiring commit exits 2 on push over that one path with no marker in the output; on a default install the file is ignored and nothing is committed). `tools/cc/ci_guard.py` refuses that commit without `HARNESS-UPDATE-APPROVED`, and neither the commands nor the doc paragraphs that lead to them say so. One engine helper names the marker in both forms (in the commit message for a direct push, `HARNESS-UPDATE-APPROVED@<head-sha>` in the title for a pull request, which `/ship` binds) whenever a command has just written a path that is gated per `espalier/surface_contract.py::is_protected_from_ci` and not ignored by git (index-aware `git check-ignore`, which skips tracked paths, so a tracked settings file still counts), and only when `tools/cc/ci_guard.py` is present; every writer calls it with the paths it wrote. `espalier/cli.py::deploy_harness` has exactly two callers, `cmd_init` and `cmd_upgrade`, so a call keyed on its result reaches both. The Quickstart's CI, upgrade and fusion paragraphs, `docs/INSTALL-CI.md` sections 1 and 2 (its packaged copy under `espalier/assets/docs/` follows through `scripts/sync_asset_docs.py`), the fusion checklist's re-point step and fuse's unwired-host 'Before you push' warning (it names wiring alone, and the merge-settings run it prescribes rewrites the host's preserved settings file, tracked when the host tracked it; read in code, not driven in a fusion) carry the same clause.

**What this does NOT reach.** Which events the installed workflow triggers on and what it costs in Actions minutes (`DEF-945`, which shares the install-ci banner and `espalier/fuse.py::_orchestrate_bootstrap`; schedule the two together so the banner is edited once), and whether adopter-owned workflows under `.github/workflows/` stay gated at all (`DEC-39`, no horn of which retires this: the guard script, the workflow file and the hook prefix stay gated either way). It does not change `ci_guard.py`'s refusal or its remedy text, both correct, adds no first-install exemption to the gate, and leaves init's ignore entries as they are (a tracked settings file stays tracked).

**Why one class.** One predicate, one helper and one oracle: in a scratch repository with `tools/cc/ci_guard.py`, run each writer, commit what it wrote, and replay the workflow's push and pull-request environments against the gate (exit 2 today; a marker commit exits 0). Every member has the same acceptance rule: the writer's own output names the marker in both forms when it wrote a gated path git will commit, and the line is absent in two negative arms, when the gate is not installed and when every gated path it wrote is ignored by git. The second arm is load-bearing: `.claude/settings.json` and `.espalier/integrity.json` are gated, are ignored on a default install through `espalier/cli.py::REQUIRED_GITIGNORE` (its `.claude/settings.json` and `.espalier/` entries), and are written by init, merge-settings, install-ci's integrity re-seed and upgrade, so a helper keyed on the gate alone would demand the marker for a commit that carries no gated path. One test parametrized over the five writers (init's re-deploy and merge-settings included, though neither has a row of its own) pins the class, with tracked-settings arms where merge-settings and upgrade must name the marker and default arms where they must not, and a future writer of a gated path inherits the sentence instead of becoming the next unwarned site.

**Members**

| id | site | what | sev |
|---|---|---|---|

### §C69 — Pick and recognise the Python interpreter by what it answers, not by its name, at every site that chooses one, so a Windows host whose python3 or python is the Store alias, or that has only the py launcher, gets wired, passes doctor and runs

**Unit of work.** Four sites choose or recognise a Python interpreter by its name. `init`'s resolver probes only `python` and `python3`, and when both are Store aliases it falls back to a literal that does not run. The exec-form oracle behind doctor and `merge-settings --repair`, and its `ci_guard` twin, read the `py -3` wiring that doctor itself recommends as unwired. Six shipped `PY=python3; command -v` shell lines treat a name that resolves as a name that runs. The rendered invocation rule sends the model to `python3` first, with a fallback that never fires. The fix is to pick every interpreter by running it and reading its answer, and to accept the launcher's `py -3` wherever the harness recommends it. Each site is proven under one stubbed-PATH fixture with two host shapes: a Store-stub `python3` beside a working `python`, and both names stubbed beside a working `py`. In the same lane: the pins that freeze today's shell line, the `py` refusal in `espalier/cli.py::_is_rewirable_interpreter`, doctor's hint text, `tools/cc/hooks/_hook_utils.py::host_orientation_line` (it probes only the two names, so on the second shape every SessionStart and SubagentStart orientation says no interpreter exists), and `docs/HOOKS.md`'s claim that the python.org installer adds `python.exe` to PATH by default. That claim is false for the full installer, whose documented `PrependPath` default is 0.

**What this does NOT reach.** Adjacent rows keep their own owners: the blueprint-authoring skill's two bare `python3` lines and the portability contract's missing skills check (the standalone row on `.claude/skills/blueprint-authoring/SKILL.md`), the resolver's missing start-up probe (`DEF-915`), the dev-container interpreter (`DEF-947`), spaced interpreter paths in the exec-form extractor (`DEF-968`), how /preflight picks its linter and test runner (`DEF-962`), and the agents' Bash declarations (`DEF-651`). `DEF-975` owns the CI cell with a PATH shim without `python3` and the portability collectors over workflow bodies and command-body code blocks; this class's stubbed-PATH fixture lands as a test helper that cell can reuse, not as a competing cell. This class does not decide whether the harness should prefer the newer Python install manager's commands. Nor does it decide how much weight the launcher-only shape deserves; how many adopters are on it has not been measured. Hook scripts are not made to run under any interpreter other than a 3.10+ one.

**Why one class.** One fixture, one method. The fixture is a stubbed PATH in the two host shapes, and every interpreter-choosing surface is driven under it until it lands on a working 3.10+. Init's settings must spawn, and the write_guard deny must fire. Doctor must exit 0 on a `py -3` tree, and `--repair` must keep that wiring. Every extracted shell resolver line must print 3.x. The rendered rule must name what settings.json runs, and the orientation line must name the working interpreter. The members land together. If init writes `py -3` without the oracle change, doctor fails that wiring and `--repair` reverts it. The shell fix the finding proposed (`for c in python3 python`) passes the first host shape and fails the second, so a standalone row would ship that hole. The fix differs at each site; the oracle is shared.

**Members**

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|

### §C70 — Make the demo take's two unverified assumptions measurable and give its one load-bearing number a receipt, so the hero can be recorded without discovering a dead beat on take day

**Members**

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|

### §C71 — Keep maintainer-addressed content out of what init ships: an audience test for shipped text, ids and verbatim captures

**Source.** Findings A1-1 to A1-3 of the 2026-10-03 adoption audit (`espalier-issues/audits/2026-10-03-adoption/public_report.md`: 50 findings against 0.8.0b2 at `2cb371b`), each re-read at `08ab2db` before filing (`espalier-issues/audits/2026-10-03-adoption/RECHECK_at_08ab2db.md`). The audit's magnitudes come from one adopter whose repository already had a harness; its mechanisms were re-read in code at HEAD, and each row's probe was driven there. Not this class: §C18 owns references in shipped text to targets the adopter's tree never receives; this class owns shipped content that is addressed to the maintainer.

**Members**

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|

### §C72 — Render the shipped instruction surface against the adopter instead of shipping the maintainer's own Espalier-shaped bodies

**Source.** Findings A2-2 to A2-8 of the 2026-10-03 adoption audit (`espalier-issues/audits/2026-10-03-adoption/public_report.md`: 50 findings against 0.8.0b2 at `2cb371b`), each re-read at `08ab2db` before filing (`espalier-issues/audits/2026-10-03-adoption/RECHECK_at_08ab2db.md`). The audit's magnitudes come from one adopter whose repository already had a harness; its mechanisms were re-read in code at HEAD, and each row's probe was driven there. Covered by existing rows and not repeated here: A2-1 (no render stage between the packaged bodies and the adopter; `LG-7`, `DEC-36`, `DEC-32`) and A2-10 (install-ci guards every workflow file; `DEC-39`, `DEF-945`). Not filed: A2-9 (the SubagentStart schema pointer reaches every subagent; no user is harmed beyond its token cost).

**Members**

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|

### §C73 — Fold the adopter's existing knowledge in: route, index and surface it where the adopter keeps it

**Source.** Findings A3-1 to A3-8 of the 2026-10-03 adoption audit (`espalier-issues/audits/2026-10-03-adoption/public_report.md`: 50 findings against 0.8.0b2 at `2cb371b`), each re-read at `08ab2db` before filing (`espalier-issues/audits/2026-10-03-adoption/RECHECK_at_08ab2db.md`). The audit's magnitudes come from one adopter whose repository already had a harness; its mechanisms were re-read in code at HEAD, and each row's probe was driven there.

**Members**

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|

### §C74 — Reconcile an adopter's prior harness: assets that already do a shipped asset's job under another name or path

**Source.** Findings B-1 to B-4 of the 2026-10-03 adoption audit (`espalier-issues/audits/2026-10-03-adoption/public_report.md`: 50 findings against 0.8.0b2 at `2cb371b`), each re-read at `08ab2db` before filing (`espalier-issues/audits/2026-10-03-adoption/RECHECK_at_08ab2db.md`). The audit's magnitudes come from one adopter whose repository already had a harness; its mechanisms were re-read in code at HEAD, and each row's probe was driven there. The audit found no row, pack, fork or walk note for an adopter whose repository already had a harness of its own; this class is that owner.

**Members**

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|

### §C75 — Make every adopter-side stand-down, skip and failure say so: no silent misbehaviour off the self-host repo

**Source.** The 22 open C findings of the 2026-10-03 adoption audit (`espalier-issues/audits/2026-10-03-adoption/public_report.md`: 50 findings against 0.8.0b2 at `2cb371b`), each re-read at `08ab2db` before filing (`espalier-issues/audits/2026-10-03-adoption/RECHECK_at_08ab2db.md`). The audit's magnitudes come from one adopter whose repository already had a harness; its mechanisms were re-read in code at HEAD, and each row's probe was driven there. Covered by existing rows and not repeated here: C-7 (the post-write validators speak only to stderr; `DEF-1030`) and C-23 (a plan-guard deny cites a CLAUDE.md section the adopter owns; `DEC-40`). Not filed: C-21 (fixed by `7a0d9d3`).

**Members**

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|

### §C76 — Make the recursive-remove tiers read every launch form a shell runs and stay coupled by property: a native rm reached by its file name or path on the PowerShell tool and cmd's own deletes on both tools meet the plain form's wall, and every step-aside of the PowerShell wall is asked by the speed bump

**Members**

| id | site | what | sev | pop | aud |
|---|---|---|---|---|---|

## §3 — New features & product bets

_Proposed capability with no defect behind it. None gates the flip._

| id | site | what |
|---|---|---|
| ~~`TP-430`~~ | `task-packs/Scrapped/TP-430-instructions-loaded-payload-probe.md` (gitignored, local; the stamped stanza is in git history at the parent of the commit that removed the root copy) | ✅ **CLOSED 2026-10-02 — SCRAPPED, never executed. Its premise -- the `InstructionsLoaded` input schema is unpublished, so `INV-6` cannot be scoped until a probe records it -- was falsified by the upstream hooks page: the raw page (`https://code.claude.com/docs/en/hooks.md`, fetched 2026-10-02) documents the input (`file_path`, `memory_type`, `load_reason` with its five values, `globs`, `trigger_file_path`, `parent_file_path`), a matcher on `load_reason`, and no decision control. The pack's Landing stanza carries the verbatim field list and the installed build (2.1.287). Not observed: that the event fires with those fields on that build -- a ten-minute machine-local check owed by whatever governed hook is built on it, not a pack. `INV-6` is unchanged and can now be scoped from the page. Struck by hand: the strike verb refuses a three-cell row and says so.** PRIOR TEXT: TP-430 (drafted 2026-08-06, not executed): the `InstructionsLoaded` payload schema is undocumented, so `INV-6` cannot be scoped until someone records what the event actually carries. A throwaway probe, wired machine-locally for one session, with a mandatory stop condition; a NEGATIVE result passes the pack, an UNRECORDED one fails it. Must live outside `tools/cc/` and `espalier/` — a probe file under `tools/cc/hooks/` reds 13 tests and the vendor-parity remedy would copy the throwaway into the shipped wheel. |
| `TP-466` | `task-packs/TP-466-migrate-an-adopters-memory-at-setup.md` | TP-466 (ROADMAP, drafted 2026-10-02, not scheduled): `init` moves none of an adopter's pre-existing knowledge into recall. On a field-trial adopter, `/recall` answered 0 of 15 pre-registered questions the day after install, and indexing the adopter's own text in place, with nothing moved, reached 7 to 8 of its 9 pitfall questions. Five waves: a setup migration step, in-place markers with a records scope, temporary recall markers, temporary rules as probed against Claude Code, and an observer as the only writer of temporary things. Task 0 re-derives the evidence on `main`; the operator decides which waves to schedule. |
| `TP-467` | `task-packs/TP-467-sessions-in-one-tree.md` | TP-467 (ROADMAP, authored 2026-10-05; wave A on `lane/sessions-in-one-tree`): the anti-clobber system coordinates two machines and protects data on one, and coordinates nothing between two sessions on one machine -- the claims key on the machine name, every current-X file (the plan, the blueprint head, the working summary, the per-session flags) is a singleton with no session key, and a worktree entered mid-session writes its state into the main tree. Wave A: a per-session marker and the banner's `Sessions:` line; B: a name per worktree through `WorktreeCreate`/`WorktreeRemove`; C: the singletons keyed by session (`DEF-861`'s fix); D: release at `SessionEnd`. Supersedes `TP-248`; `INV-7` routes to wave B. |
| ~~`TP-466b`~~ | `task-packs/TP-466b-index-adopter-knowledge-in-place.md` | ✅ **CLOSED 2026-10-08 — landed 2026-10-08 on lane/recall-indexes-adopter-knowledge (the pack in `Done/`; the lane commit is named in ESPALIER_MEMORY.md's row). `/recall` indexes the adopter's own knowledge where it lives: the default roster (the root `CLAUDE.md` per `## ` section, every `.claude/rules/**/*.md`) and the two flat keys `recall_sources` / `recall_records`, the skip marker on every sectioned source, the records scope under `/recall --records`, `corpus_summary` + `--facts`, the doctor's `recall corpus:` row, `HarnessConfig`'s two fields and the skeleton's Recall block, the bodies and docs, the handoff triggers. Task 0 re-run said build (0 of 4 before, 4 of 4 after on the fixture; default-on moved no pre-registered arm; the records scope kept on a measured tail); D1-D4 as recommended; two restating sections of the self-host root CLAUDE.md marked by the operator's call after three pins moved; `init` now marks every section it generates (a gap found in-lane: a bare tree's ten harness sections were indexed as the adopter's own). 26 reds earned; a two-lane red-team (1 BLOCK / 2 WARN / 4 NIT; 0 REGRESSION / 6 GAP / 6 ROUGH-EDGE) folded in one batch, the corpus ceiling left as a follow-up. `DEF-1087` closed; `TP-466` Wave B row written, the parent stays ROADMAP.** TP-466b (PACK, drafted 2026-10-07; TP-466's Wave B child, TP-466 stays ROADMAP): the recall corpus is a hard-coded list of Espalier paths, so an adopter's root CLAUDE.md, `.claude/rules/*.md` and their own docs are never indexed; measured on an init'd fixture, 4 documents and 0 adopter-authored, 0 of 4 generic questions answered, 4 of 4 with the same text indexed in place. Indexes the adopter's instruction files and a records scope where they live, keeps pointer sections out by marker, and adds the doctor corpus line. Closes `DEF-1087`; names `DEF-1189` (the seeded reference docs have no recall home) as not reached; `DEF-1088`'s fingerprint half landed with the plan guard's first-session lane (2026-10-08; its CLAUDE.md-reading half stands) and `DEF-1090` landed 2026-10-08 on lane/generic-systems-fire-off-self-host. |
| ~~`TP-470`~~ | `task-packs/TP-470-every-generic-system-fires-off-the-self-host-repo.md` | ✅ **CLOSED 2026-10-08 — landed 2026-10-08 on lane/generic-systems-fire-off-self-host: a scope per PostToolUse advisory row (the test-loosening nudge and the `git archive` proxy note declare `scope="any"`; one registry call with the tree's tuple; the Bash bridge keeps its gate, its synthesized input carrying no content), the standing-principles banner index gated on the file at both sites, `encoding_contracts` out of the self-host-only tuple and bounded through `cmd_scan`'s gate with the fingerprint's harness-output prefixes, the step-6 review surface with two branches by tree in the three ship-boundary bodies, and the class test on an init'd Node tree through the deployed hooks; the adopter-pointer arm reads an any-scope render as ungated and excuses an artifact-gated renderer, each with a twin. Struck with it: DEF-1080, DEF-1090, DEF-1115, DEF-1180; DEF-1181 and DEF-1122 named as not reached. Red-teamed by code-reviewer and failure-mode-reviewer on a snapshot clone (both REQUEST CHANGES: one BLOCK, the overrides-corpus walk left unbounded; two WARN; seven GAP; three ROUGH-EDGE; one fix batch, every new pin driven red); the contract slice then the full tier, green but for the recall eval's strip table, re-pasted from a fresh sweep. The pack is in task-packs/Done/ with its Landing stanza.** PRIOR TEXT: TP-470 (PACK, drafted 2026-10-07): systems built for every tree are gated behind the self-host check or behind harness-only path lists, so an adopter never gets them and nothing says so; a census of the gate sites classifies each as harness-only, generic-withheld or harness-content, and an init'd Node tree is where each un-gated feature is driven. Closes `DEF-1080`, `DEF-1090`, `DEF-1115` and `DEF-1180` (the review step dispatches reviewers only on harness paths); names `DEF-1181`, `DEF-1122`, `DEF-1091` and `DEF-1087` as not reached, with reasons. |
| ~~`TP-471`~~ | `task-packs/TP-471-the-proof-chain-reads-the-fingerprints-test-command.md` | ✅ **CLOSED 2026-10-08 — landed 2026-10-08 in two lanes. The hook lane (1-A, 1-B, 2-A; #148, lane/gate1-runs-the-detected-command) made Gate 1 run the environment's command, else `[extra_actions] test`, else the fingerprint's detected command, and every shipped sentence say so. The body lane (3-A to 3-D; lane/proof-fences-derive-the-runner) made the shipped proof fences derive the runner as `/preflight` does -- `implement-task.md` steps 5 and 7 and Phase 3, `implement-pack.md`'s integration fence, `debug/SKILL.md` step 7, `/test-this` and `test-writer` -- or carry the `# Espalier-Harness tree:` label where a self-host example stays (`docs/CHEAT-SHEET.md`), with `docs-maintainer.md` and `docs/TASK_RECIPES.md` naming the repository's command and `tests/test_portability_contract.py::TestShippedProofFencesNameTheRepositorysRunner` holding the shape. `DEF-949` step 4, `DEC-35` (D1), `DEF-1185`, `DEF-1182`, `DEF-1183` (its layout sibling re-filed as `DEF-1193`) and `DEF-1184` closed; 4-A (the uv/poetry runner, `DEF-1157`) unbuilt -- D2 had no answer at landing, and a yes raises it as its own pack; `DEF-985`, `DEF-1107`, `DEF-1002`, `DEF-1152` NOT REACHED as the Reach table says. The pack is in `Done/`.** PRIOR TEXT: TP-471 (PACK, drafted 2026-10-07): every surface that proves a change spells pytest while the fingerprint already names the adopter's runner, and the Stop gate's Gate 1 reads the fingerprint only to go dormant on a non-pytest command; on an init'd Node tree the fingerprint says `npm test` and seven proof fences say pytest. Renders the proof fences, the test writers' layout and the docs-maintainer sentence from the fingerprint, and makes Gate 1 run the detected command under the operator's `DEC-35` answer. Closes `DEF-949` step 4, `DEF-1182`, `DEF-1183`, `DEF-1184`, `DEF-1185`; `DEF-1157` conditional on a second decision; `DEF-985` not reached. Hook lane landed 2026-10-08 on `lane/gate1-runs-the-detected-command` (Task 0 reproduced; 1-A, 1-B, 2-A; `DEF-949` step 4 and `DEF-1185` struck, `DEC-35` decided with D1's default); the body lane (3-A to 3-D) follows the self-host-gates pack's 3-A, and 4-A the operator's D2. |
| ~~`TP-472`~~ | `task-packs/TP-472-the-plan-guards-first-session-on-an-adopter-tree.md` | ✅ **CLOSED 2026-10-08 — landed 2026-10-08 on lane/plan-guard-first-session under the operator's three defaults (DEC-40 fork (a); fork (b) not reopened; the stack's test roots exempted): the tomli floor and a text-handle retry; the two plan hints, the misplaced-key advisory and the env-prefix deny cite docs/HOOKS.md headings; the stack table's test roots exempted beside the manifest at the root through a fourth hook projection; the deny and the explainer say what the hook did with the adopter's `plan_exempt_prefixes`; `init` writes the `espalier.toml` skeleton (every key commented out, never rewritten, pinned as examples/espalier.toml, in both root-doc rosters, named by the summary and the upgrade preview; a kept file is told which keys it lacks). Struck with it: DEF-871, DEF-1022, DEF-1190, DEF-1191, DEC-40; DEF-1088's fingerprint half noted on its row. Red-teamed by both reviewers on a snapshot clone, one fix batch, the full tier green; the pack is in task-packs/Done/ with its Landing stanza.** PRIOR TEXT: TP-472 (PACK, drafted 2026-10-07): the plan guard's first contact with an adopter who is not this repo denies the stack's test directory and sends the adopter to a config file and a CLAUDE.md section that do not exist on a tree whose CLAUDE.md they kept; a nine-path verdict table on an init'd Node tree is the oracle. Derives the test-root exemption from the stack table, repoints both remedies at `docs/HOOKS.md` under `DEC-40` fork (a), writes an `espalier.toml` skeleton from the fingerprint at init, and fixes the tomli text-mode read. Closes `DEF-871`, `DEF-1022`, `DEF-1088` (the fingerprint half), `DEF-1190`, `DEF-1191`; `INV-8` and five zone-key rows named as not reached. |
| `TP-473` | `task-packs/TP-473-what-init-ships-is-addressed-to-the-adopter.md` | TP-473 (PACK, drafted 2026-10-07): the bodies, docs and headers init deploys are byte-copies of the maintainer's tree, addressed to Espalier's maintainer; a marker pass over an init'd Node tree on 2026-10-07 counted 1175 maintainer-marker hits against 100 adopter hits across 66 bodies, and 23 seeds land in a three-file repo. Builds the audience scanner `DEF-1074` describes as a ratchet over the deploy inventory, strips or re-renders the maintainer passages, and presents `DEC-30` and `DEC-38` at its Task 0 checkpoint. Closes `DEF-1074` (the fence-and-strip fork), `DEF-1075`, `DEF-1076`, `DEF-1082`, `DEF-988`, `DEF-1005`, `DEF-1006`, `DEF-1028`, `DEF-1186` (the summary directory before the handoff's first append, 1-F) and `DEF-1187` (the render against the saved fingerprint, 1-E); instruments `DEF-987`; fifteen further rows named as not reached or routed. |
| ~~`TP-474`~~ | `task-packs/TP-474-install-upgrade-and-ci-proven-on-an-adopter-tree.md` | ✅ **CLOSED 2026-10-11 — landed in four lanes: Walk and guard (the Air, #177, 2026-10-10), upgrade (win-2, #184), CI (win-2, #186) and onboarding (win-2, `lane/onboarding`, 2026-10-11). Struck with it: `DEF-1176`, `DEF-1188`, `DEF-1061` (Walk and guard); `DEF-1063`, `DEF-1064`, `DEF-1126` (upgrade); `DEF-1050`, `DEF-1051`, `DEF-1052`, `DEC-39` (CI); `DEF-1032`, `DEF-1033`, `DEF-1034` (onboarding). Not closed, each with its remaining half in its own row: `DEF-1057` (the init and doctor WARN), `DEF-1077` (the overlay and `RELIEF_FLAGS`), `DEF-1104` (the explicit override). Filed at the lanes: `DEF-3002` (the marker-writer census), `DEF-938` raised, `DEF-3003` (an adopter's stored onboarding probes never re-pinned by upgrade). Each lane red-teamed by both reviewers on a snapshot clone with one fix batch, then the tier its diff earned; the pack is in task-packs/Done/ with its Landing stanza.** PRIOR TEXT: TP-474 (PACK, drafted 2026-10-07): the install, upgrade, CI-install and uninstall lifecycle was only ever walked on this repo's own shape, so each step misbehaves on an adopter tree and the next hides it; one lifecycle walk on an init'd Node tree reproduced every pre-registered symptom, `doctor` passing over two hooks dead at import among them. Extends `tests/test_adopter_lifecycle_diagnostics.py::Walk` by stack and lands the fixes in four lanes. Closes `DEF-1176`, `DEF-1050`, `DEF-1051`, `DEF-1052`, `DEF-1061`, `DEF-1063`, `DEF-1064`, `DEF-1126`, `DEF-1032`, `DEF-1033`, `DEF-1034`, `DEF-1188`; half-lands `DEF-1057`, `DEF-1077`, `DEF-1104`; decides `DEC-39`; nine rows named as not reached. |
| `TP-475` | `task-packs/TP-475-know-when-work-is-worth-doing.md` | TP-475 (PACK, draft 3 of 2026-10-08, not scheduled): the ledger cannot tell a converging stream from a brick wall, nor a fix aimed at the symptom from one aimed at the job. Draft 1's per-surface net-flow alarm was refuted by its own pre-registered back-test (filing bursts swamp flow; a wall drains too little to reach the floor; class collapses to the catch-all and file splits one job). Lineage is recorded at filing (`ledger_row.py file --sibling-of`, kept in a store a strike does not prune), carried from the reviewer's finding through the handoff's note to the filer, and read at plan time (`ledger_row.py lineage <id>`, run by `/implement-task` and `/implement-pack` for each row the work names); advisories -- never refusals -- fire on a chain of siblings or a standalone cluster on one site family; five layer questions come before the class question (a memory note, a Core Rule 12 clause, a reviewer question, the class verb, and a principle §20 earned by a blind out-of-sample back-test). `ledger_trend.py` also reads a merge-heavy ref first-parent. The merge-level lineage back-test was not run: on this tree a fix lane's siblings land in a later filing merge, so its proxy cannot see them. |
| `TP-476` | `task-packs/TP-476-guard-by-location.md` | TP-476 (ROADMAP, drafted 2026-10-07, amended 2026-10-08, not scheduled): the guard's protected-zone and secret-read jobs are questions of location, chased spelling by spelling in a command-text parser that cannot be complete. Wave A-0 checks, on every settings change, that the hook wiring is still present (the settings-change hook derives from `ci_guard`'s positive check instead of listing ways to switch hooks off, which reads a removed `hooks` key or a deleted file as clean). Wave A compares the protected zones after every shell call with the session's previous check (a per-session baseline; the manifest is stale in the normal course and absent in a worktree) and tells Claude and the operator what changed, never restoring it; it sees whole-tree writes such as a formatter, which no command text names. Wave B offers sandbox write and read denies where the OS has one; decision C3 writes a coverage contract for the parser's residual jobs (catastrophic deletes, speed bumps, secret reads on native Windows), so a spelling a slip would not produce is a declared limit rather than the next fix; wave C strikes the zone rows as covered; wave D re-raises relaxing any parser guard, which the operator ruled out for now. |
| `TP-477` | `task-packs/TP-477-re-target-the-check.md` | TP-477 (ROADMAP, drafted 2026-10-07, not scheduled): four live surfaces fix themselves by teaching one reader every shape, a consolidation that stalls where the input is open -- the ledger completeness detectors per malformed row shape (`§C32`), the citation resolvers per anchor shape (`§C31`), a hand mutation per named assertion (`§C36`), and the committed byte-copy mirrors. Each candidate names the target that would see every shape at once (the row formatter as the definition with one round-trip check; citations resolved by their reader's own mechanism; a mutation-testing tool as the missing weak-assertion scanner; mirrors placed by the build step) and a Task 0 that can kill it; a survivor becomes a lettered child pack that claims deleted code only by measurement. |
| `TP-478` | `task-packs/TP-478-converge-concurrent-writes.md` | TP-478 (ROADMAP, drafted 2026-10-09 on the operator's approval, not scheduled): two lanes merged in turn conflict on what both recompute -- over the last 30 merged pull requests 24 of 30 catch-ups conflicted as GitHub sees them (the ledger 20, the probes roster 17, the changelog 10, the memory file 9), and 73 of the ledger's 87 conflict blocks were derived counts. Task 0 lands `scripts/merge_cost_census.py` and may end the pack; Wave 1 widens the live-tree guard to the packaging dirs; Wave 2 stops committing aggregates two lanes rewrite (fragments for the changelog and the memory rows); Wave 3 turns on a merge queue once merges commute and the approval marker can bind in a merge_group run. |
| `TP-479` | `task-packs/TP-479-parallel-work-without-clobbering.md` | TP-479 (ROADMAP, drafted 2026-10-09 on the operator's decisions; Wave A on `lane/parallel-work`): three seats on two machines conflicted on stored totals and appended rows, minted one id twice, and each believed a different branch was merging. The anti-clobber system's second generation prevents what the first reconciles: totals derived on read and records as per-change files behind one loader, per-seat id blocks, jobs assigned by a dispatcher (path areas refuted: 47 of 65 code-touching pull requests crossed them), a live board, the merge rules printed live, and a red main reverted first. It takes TP-478's 2-C, 2-D, 2-E and Wave 3, and TP-467 wave B; Wave D is a pre-registered re-measure. |
| `TP-702` | `task-packs/TP-702-symbol-level-overlap-between-unmerged-lanes.md` | TP-702 (PACK, authored 2026-10-17 on the operator's word; Wave 1 on `lane/claims-carry-derived-symbols`): the one judgment the anti-clobber system still leaves to a hand read, whether two lanes that are both still open edit the same function. A claim gains an optional `symbols` key (`path::qualname`, derived from the lane's diff by `ast` on both sides of every hunk; a changed line no definition holds is unplaced and never a certificate), the plan pre-flight and the matcher read it, the board gains an `overlaps:` section and a same-function clause on `stale:`, the ship driver prints the notice at `open` and `handoff`, and a `refresh` verb keeps a claim current. Advisory by design: the second to merge runs catch-up, unchanged. Task 0 can end or hold the pack; Wave D is pre-registered. Its Task 0 oracle, `scripts/lane_overlap_census.py`, landed with the pack. |
| `TP-703` | `task-packs/TP-703-multi-seat-discipline.md` | TP-703 (ROADMAP, authored 2026-10-18 on the operator's word, "good, lets make task packs for fixing these issues"; children `TP-703a` to `TP-703j`, each `Kind: PACK` with its own Task 0): the multi-seat layer was built with the harness's mechanisms and not all of its disciplines; five days of running four seats (10-14 to 10-18) showed six of them held by prose, memory or mail. The children make each a mechanism with a probe: one reader of post-merge check verdicts with change detection (`TP-703a`); the platform legs earning their red, `DEF-5024`'s contract, a slim Windows leg on main and `DEF-2025`'s counted skip (`TP-703b`); one tier per box by a kernel lock the holder's death releases (`TP-703c`); the records saying what happened, a row per seat per day with the debt named on the board and the dispatcher's row derived (`TP-703d`); the assign shrinking to what only the dispatcher knows and the seat proceeding on its Task 0 after a veto window (`TP-703e`); jobs closing from the claim and the strike, counts on every board header, a census script owning the day's figures (`TP-703f`); the documented drifts and the marker's window (`TP-703g`); host expectations in one registry (`TP-703h`); the suite's platform axis (`TP-703i`); a strike reading the base and the guard (`TP-703j`). Eight re-measure lines pre-registered in the roadmap; the scaling question answered from the measured throughput (a fifth seat is line 8's experiment). |
| `INV-23` | `task-packs/FORWARD_LEDGER.md:1442` | two deliberately-parked ledger rows: the ~32 R0-tail advisory residuals and the internal-exhaust hygiene pass over dev ledgers plus workflow scaffolds |
| `DEF-321e` | `pyproject.toml:123` | widening mypy beyond tools/cc/hooks is a deliberate, config-baked deferral with pack-recorded and unverified counts |
| `DEF-416c` | `task-packs/FORWARD_LEDGER.md:1846` | DEF-416c: a declared `## Cross-pack coordination` schema with tagged facts, replacing both prose regexes |
| `DEF-417a` | `espalier/release_pack.py::ReleasePackSummary` | DEF-417a: replace the release report's full skipped-entry enumeration with counts + first N |
| `INV-29` | `—` | INV-29: a mechanical audit of a nested `claude -p` run's own transcript (assert the claimed RED appeared; assert the plan tracker stepped 0/N -> N/N) is proposed and not built. |
| `DEF-19` | `espalier/scan_credibility.py` | A generator that writes folder-level CLAUDE.md guides into an adopter's repo (DEF-19), bundled with the declined exceptions/prints adopter carve-out |
| `DEF-16` | `docs/known-findings.md:1` | DEF-16: nothing re-verifies a sample of docs/known-findings.md entries against HEAD before a convergence round dedups against them. |
| `DEF-327f` | `docs/CONVENTIONS.md:9` | DEF-327f: proposed content-freshness read of docs/CONVENTIONS.md's un-pinned Part-II prose; no stale section has been demonstrated by anyone. |
| `DEF-4` | `espalier/finding_ledger.py` | DEF-4 A2 (propose_rules) is unbuilt while the trigger it was parked behind is satisfied -- two categories now clear the >=3-runs / >=0.6-survival gate. |
| ~~`INV-8`~~ | `tests/test_surface_matrix_module.py::test_classifies_known_surface_from_live` | ✅ **CLOSED 2026-10-09 — landed 2026-10-09 on lane/plan-mode-bridge: `tools/cc/hooks/reflect_trigger.py` (PostToolUse, matcher `*`, the hook that already received the call) opens `cc/execution_plan.json` from an APPROVED `ExitPlanMode` through the new `execution_plan.build_plan` / `save_plan` (the CLI's `create` uses the same builder): the steps are the plan's top-level numbered items outside fenced code and framing headings, else its headings, else one step; an `in_progress` plan is replaced and named; a subagent's approval and any payload that is not success-shaped open nothing and say so. No settings change, so installed trees get it at `upgrade`. `docs/SURFACE_SUPPORT_MATRIX.md` row `deferred` -> `supported` and this probe test asserts it; pinned by `tests/test_reflect_trigger_plan_bridge.py`. Driven 2026-10-09 on this tree: a rejected `ExitPlanMode` left the hook untouched (the success-only rule holds for this tool); HEAD's hook wrote nothing on the approval payload; and one live approval wrote the plan (two steps, the plan file in `goal`, the Out of scope line in `not_doing`), put the hook's line beside the tool result, and left `last_tool` on `ExitPlanMode`. The stale-window class the bridge widens is `DEF-1198`.** PRIOR TEXT: INV-8: no ExitPlanMode -> cc/execution_plan.json auto-bridge exists; plan_guard still requires a manual /implement-task. |
| `TP-259` | `cc/GOAL.md:15` | TP-259 (deferred): its Fix 2 targets a '## Standing owed' heading that no longer exists in cc/GOAL.md, so executing as drafted yields an empty digest and suppresses the advisory for everyone. |
| `INV-30` | `docs/FAILURE_MODES.md:5123` | INV-30: a mid-execution kill-switch pre-write gate at the /implement-pack trust perimeter -- proposed capability, never scoped |
| `DEF-18` | `.espalier/freshness.json:73` | DEF-18: align the ESPALIER_MEMORY.md 120-line hard auto-archive to the banner's soft-flag-under-a-generous-hard-cap model |
| `DEF-382c` `DEF-410h` | `tests/test_adopter_pointer_resolution.py::_NOT_DEPLOYED_MARKERS` | DEF-410h: the guard on 'not deployed by init' notes pins two specific mentions, so a NEW ungated self-host scripts//bench/ mention would ship silently. |
| `INV-15` | `espalier/audit_accuracy.py` | INV-15: audit_accuracy's external-pin cross-check is scaffolded but the LLM-dispatch callable is not registered, so those claims report unverifiable by design. |
| `DEF-867` | `.claude/CLAUDE.md:6` | No test pins the sync-script paths hard-coded in router prose to the real MIRRORS declaration, so a rename drifts the prose silently (follow-up #12 of a landed 2026-07 pack). |
| `TP-361` | `task-packs/Deferred/TP-361-new-dev-tooling.md` | TP-361: a drafted-and-deferred pack for a pack-doc declaration linter plus a red_team_guard CLI. |
| `DEF-342` | `task-packs/Deferred/TP-342-mine-userpromptexpansion-setup-events.md` | DEF-342: two live context-injecting CC hook events are unwired; a drafted pack exists and is deferred. |
| `DEF-14a` | `tools/cc/hooks/subagent_start.py` | The TP-248 A/D cold-subagent shared-tree advisory is deliberately unbuilt, held on signal density. |
| `INV-1` | `espalier/strengthen.py` | strengthen cross-references test coverage textually; a coverage.py-backed mode is proposed and unbuilt. |
| `INV-14` | `—` | Productizing the /goal-driven autonomous pack-chain driver is idea-only, with the /goal x stop_gate interaction unverified. |
| ~~`TP-319`~~ | `task-packs/Scrapped/TP-319-oss-landscape-gap-roadmap.md` (export-ignored; carried by the record branch) | ✅ **CLOSED 2026-09-24 — retired at the 0.8.0b1 cut, 2026-09-24, by the pre-door review. The roadmap named about twenty-five third-party projects with figures its own opening declared stale and not to be published, so the file left the shipped tree (it lives under `task-packs/Scrapped/` on the maintainers' tree, export-ignored and gitignored, and reaches the record branch at the next handoff snapshot). Its buildable content had already landed; the one parked remainder, a hierarchical `espalier.toml` config half triggered by a real monorepo adopter, is carried in this text as record and re-files as its own row the day that adopter appears. The method lesson the file taught, read a competitor's source and never its README before claiming a gap, is kept in the maintainers' memory.** PRIOR TEXT: The OSS-landscape roadmap's buildable content is landed; the parked remainder is the hierarchical espalier.toml config half, triggered by a real monorepo adopter. |
| `LG-7` | `README.md:585` | Language-aware agent templates are an unbuilt optional feature; the overclaim half that made it a gate is already de-pinned. |
| `TP-357` | `task-packs/Deferred/TP-357-selfhost-driver-devtool-features.md:313` | TP-357 self-host driver & dev-tool features is a drafted feature pack deferred post-flip. |
| `INV-17` | `task-packs/FORWARD_LEDGER.md:826` | The CLI-coherence pass a landed 2026-06 pack scoped as its third unit (CLI-1..5 / DEAD-1/2 / CAPGAP-2 delete-vs-rewire judgment calls) was never drafted; several of its named items landed under a different pack. |
| `INV-27` | `.github/workflows/test.yml:74` | Generalizing the CI `clean-checkout` job into a curated adversarial condition matrix (maintenance-mode off, tagless clone, degraded surface, per-OS) is unbuilt. |
| `INV-13` | `tools/cc/hooks/post_write_check.py` | No write-time (PostToolUse) de-provenance lint exists; the contract is enforced only by the test suite and the /smoke fast loop. |
| `DEF-9` | `espalier/fuse.py` | The `espalier fuse` single-file fetcher / PyPI shim convenience was deferred and is unbuilt. |
| `DEF-1` | `task-packs/FORWARD_LEDGER.md:1650` | Super-prompting pipeline (plain-prompt -> blueprint -> pack -> execute) is an unbuilt product bet. |
| `DEF-2` | `task-packs/FORWARD_LEDGER.md:1653` | Vibe Guide consumer-app fork is an unbuilt post-release product bet. |
| `DEF-3` | `task-packs/FORWARD_LEDGER.md:1659` | `strengthen --suggest` (AI test-scaffold layer behind a suggest-don't-auto-trust guardrail) is unbuilt. |
| `DEF-347a` `DEF-347b` | `tools/cc/reflect_protocol.py` | The reflect skipped-candidate log is write-only from the tool's side: it neither cross-checks a row's `key` against its `candidate` nor exposes which candidates it suppressed. |
| `DEF-5` | `task-packs/FORWARD_LEDGER.md:1691` | The generative injection PUSH side (EXEMPLAR_MAP auto-push) ships switched off -- every exemplar is push_eligible=False. |
| `DEF-7` | `task-packs/FORWARD_LEDGER.md:1697` | The five v1.1 speed-bump checkpoints (HOOKWIRING / COMMIT / FRESHNESS / CLEANREVIEW / TASKFANOUT) are all unshipped. |
| `INV-11` `INV-12` | `task-packs/FORWARD_LEDGER.md:1839` | Prose-claim honesty mechanisms (INV-11/INV-12) and an opt-in secret-guard are all parked and unbuilt. |
| `INV-2` | `task-packs/FORWARD_LEDGER.md:1664` | `strengthen` multi-language, nested/method-level, and caching expansion axes are unbuilt. |
| `INV-3` `INV-4` | `tools/cc/hooks/_reinject.py::_log_recall_event` (the push-side append) + `tools/cc/hooks/_recall.py` (the pull-side append) + `espalier/cli.py` (no `recall-stats` subcommand) | TP-203b's effect measurement has its instrument and no reader: since `f8fd9a9` (2026-08-06) both recall sides append one row per event to the gitignored `recall_events.jsonl` under the state directory -- push: the rule, the event and whether it was emitted, per-turn-capped or session-capped; pull: the query and whether the corpus answered -- but nothing reads the log back: no `espalier recall-stats`, no false-fire counter, and the injection ceilings the log exists to check are still the judgement values they were set at. (Narrowed 2026-09-20 at TP-452 1-C: the former text said logging was unbuilt on both halves; the strike critic's tracked oracle shows the push and pull appends live at HEAD.) Read by hand on 2026-09-23 (the reader still unbuilt; the operator deferred this whole item to alpha, after the cut, once the usage-panel worry that raised it was resolved: the panel's per-skill percentage counts requests carrying the skill's result, not the skill's cost, per the Claude Code costs doc). The log holds 3,688 events over 48 days and 203 sessions. Pull side: 820 queries, 609 distinct, all through the `/recall` command, 814 reporting a match, which is the nearest-neighbour leak and not a hit rate; six queries issued five or more times account for 156 of the 820, one plan-step text 112 times across 60 sessions during the 09-06 to 09-13 ledger lanes (the pre-hazard-query discipline; it returned the ledger-verbs entry 36 times). Push side: 2,868 events, 939 emitted, 1,903 session-capped, 26 once-suppressed, across 17 rules; the vendor-sync pointer fired 1,591 times and was emitted 273, so the ceilings now have two months of data to be set from. No record on either side says whether a delivered pointer or hit was used, and the layer above delivery, whether a recalled entry changed a diff or prevented a row, has no instrument at all (the recall-engine roadmap pack's W2 pre-registered false-fire and catch rates for the push side only). The task arm of `scripts/recall_eval.py` (53 rows; union@any 11 percent, first-hit 2 percent; flat between 10 and 15 percent since 2026-09-12 and unmoved by every ranker lever tried on 09-13) has answered its question and needs no further rows as a measurement: the engine retrieves by hazard vocabulary and never by task text, and implement-task step 1 already asks that way. Fix shape when taken up: `espalier recall-stats` or a script printing the tallies above over a window, the push ceilings set from them, and for the effect layer a hand-recorded yes-or-no in each lane's landing line (did the review cite an entry the session's recall had already delivered), since no mechanical join exists between the recall log and review findings. |
| `INV-31` | `task-packs/FORWARD_LEDGER.md:1834` | Both docs-hygiene deferrals of a landed 2026-06 pack are still live: docs-maintainer's charter excludes the behavior-coupled orphan docs, and the 'Adapting me to YOUR' block is still duplicated across 5 agent bodies. |
| `INV-5` | `task-packs/FORWARD_LEDGER.md:1718` | INV-5 is a pure reference pointer (how to extend the pull-recall corpus), not a work item; its target doc exists. |
| `INV-6` `INV-7` | `task-packs/FORWARD_LEDGER.md:1747` | The planned CC hook events (PreCompact, InstructionsLoaded, WorktreeCreate/Remove) are unwired; INV-7 worktree governance is a subset of INV-6 and should be merged into it. `INV-7`'s worktree half routes to `TP-467` wave B (the `WorktreeCreate`/`WorktreeRemove` hooks that give a worktree its own claim identity), 2026-10-05. |
| `INV-9` | `task-packs/FORWARD_LEDGER.md:1760` | Agent-teams governance (waiting on the CC feature) and the opt-in G5 notification hook are both unbuilt. |
| `TP-260` | `task-packs/FORWARD_LEDGER.md:1738` | Goal-anchor G2 (plan-scope divergence advisory) is a deferred drafted pack, unbuilt. |
| `TP-261` | `task-packs/FORWARD_LEDGER.md:1740` | Footgun-shape -> memory surface (M1) is a deferred drafted pack, unbuilt. |
| `TP-321d` | `task-packs/FORWARD_LEDGER.md:1812` | `espalier hook-profile` (a repeatable per-hook injection-tax profiler) is unbuilt. |
| `TP-333` | `task-packs/FORWARD_LEDGER.md:1773` | The agent-driven adversarial probe-harness PoC (generalize bench/ to a discovery engine) stays parked as self-predicted null. |
| — | `task-packs/FORWARD_LEDGER.md:77` | The adopter-facing fixed-vs-introduced instrument (measured ~6:1) is a recorded proposal that nothing builds, and the coverage map cites it to ledger §5 where it does not live. |
| `EXP-3` `EXP-5` | `docs/DEEP-WORK.md:14` | Two shipped/adopted protocols (SessionStart first-thoughts open, Deep-Work) carry direction-only claims with no pre-registered metric; EXP-5 names the measurement as owed and it has not been run. |

---

## §4 — Open decisions

_An operator choice, not a defect. Decide these; do not 'fix' them._

⚠ **Adjudicated 2026-08-10 against live code, row by row.** Eleven of the 26 rows are not open
choices at all — four already settled, three owed work with no decision content, three packs
held in `Deferred/` and already tracked in Appendix A, one defect. **They are partitioned into
§4B rather than moved or removed: each of the eleven ids appears nowhere else in this file, so
relocating one would delete the record rather than move it** — and this file is gitignored, so
there is no git undo. Every row below is physically unchanged apart from a `kind` cell.
Read **§4A as the decision queue**; §4B is holding, not a queue.

### §4A — Open operator forks

_These are live: nobody but the operator can call them._

| id | site | what |
|---|---|---|
| `DEC-26` | `tools/cc/hooks/task_router.py` + `.claude/commands/implement-{task,pack}.md` | **Where the pack-vs-plan discriminator lives.** Today it is in `.claude/skills/blueprint-authoring/SKILL.md` — which loads only once you are ALREADY authoring a pack, i.e. structurally unreachable at the moment of the choice. Fork: **(a) instruction layer** — a routing question in the two command bodies. VERIFIED CHEAP: `.claude/` is not in write_guard's `PROTECTED_PREFIXES` (`tools/cc/`, `cc/`, `espalier/`, `.github/workflows/`; only the exact `settings*.json` files are guarded) and `plan_guard` exempts `.claude/`, so no maintenance-mode relaunch and no plan is needed; requires `scripts/sync_claude_mirrors.py` after. **(b) mechanical** — extend `task_router.py`, which already classifies prompt scope on `UserPromptSubmit` and already fires the `/implement-task --multi` advisory; fires automatically instead of depending on a body being read at the right moment (CLAUDE.md Priority Order 1). (b) needs maintenance mode plus `scripts/sync_vendor_cc.py`. ⚠ **Trap either way: restatement.** `memory/ladder-claudemd-loadbearing-and-can-stale` records that copying a SoT into a ladder file staled and produced a duplicate-work reflex. One sole home plus one-line pointers, never three copies. Related: the same surface is the proposed home for the missing premise gate — see `memory/premise-check-before-authoring-a-fix.md` "The gate that cannot ask this question". |
| `DEC-27` | `espalier/scanners/retired_vocab.py::RETIRED_TERMS` | **Whether `retired_vocab` becomes a general retired-vocabulary engine or stays a severity-label linter.** All **7** registered terms today are severity labels (`WRONG`, `CONFLICTING`, `VAGUE`, `CORRECT`, `BLOCKER`, `MAJOR`, `MINOR`), all matched by `_severity_label_pattern`. Registering a retired *phrase* (`pre-flip`) is a new pattern shape, not a new row, and it breaks the `test_all_seven_tp114_terms_registered` count-pin. **Why it matters now, measured 2026-09-01:** a framing `DEC-25` retired on 2026-08-20 was reconstructed and asserted to the operator, sourced partly from `.claude/workflows/_oss_launch_review_2026_08_05.js` `meta.description` — text injected into **every** session at startup. `DOC_SURFACES` already sweeps `.claude/agents|skills|commands` and `espalier/assets/claude/`, but **not `.claude/workflows/`**, and `_doc_files` globs `*.md` only, so `*.js` workflow bodies are unreachable on two independent axes. Five live rows carry the retired framing (`task-packs/FORWARD_LEDGER.md:587`, `:765`, `:2360` + two workflow descriptions); they are deliberately left in place as the earn-the-red fixture — `test_scanner_returns_clean_against_live_repo` already pins the scanner clean and will red on them the moment the term lands. Sole home for the class: `memory/a-retraction-does-not-propagate-itself.md`. ⚠ **The earn-the-red test is WRITTEN and PARKED, not in the tree** — `<scratchpad>/B_scope_test_for_retired_vocab.py.txt`, append verbatim to `tests/test_scanner_retired_vocab.py` **as part of** the fix. Landing it alone reds three contracts, two of them non-obvious: it adds a 5th census row over `rv.DOC_SURFACES` against a pinned 4-row digest (`7c15759b75ac`) in `tests/test_derived_population_census.py`, and its new nodeids need registering in `tests/conftest.py::_FULL_TREE_NODEIDS`. Both were measured on 2026-09-01 by landing it and running the full suite. |
| `DEC-23` | `.claude/commands/commit.md` + `CLAUDE.md` | **Commit messages as a declared RECORD SURFACE.** Measured 2026-08-12: of 953 commits, ~138 (14.5%) carry forward-directive language and ~65 (6.8%) carry settled/finality language (crude regex — treat as an upper bound of the right order). A pushed message is frozen, so constraining future messages cannot touch them. Proposal: extend the Core Rule 13 record-surface concept to commit messages — *evidence about the past, never an instruction for the present* — retroactive across all 953 without rewriting anything, plus a `/commit` body change to stop emitting directives. Rejected alternative: a blanket "never use commit messages in reasoning" (forfeits legitimate archaeology; the boundary is too fuzzy to follow evenly). ⚠ The same class bit harder from MUTABLE surfaces this session: the handoff note asserted `DEF-503` closed when it was not, and `cc/GOAL.md` called it "small, well-shaped … probably an hour". Fixing only commit messages closes the leak that has not cost anything yet and leaves the two that have. |
| `DEC-24` | `tools/cc/hooks/post_write_check.py` | **Mechanical bare-anchor check at the moment of the write.** `/handoff` step 2 writes `ESPALIER_MEMORY.md` and step 5 commits, with **no test run anywhere in the handoff body**; the last suite ran at `/preflight`, before the row existed; `stop_gate` Gate 1 is opt-in (`ESPALIER_STOP_GATE=full`) so Stop does not catch it either. Last handoff wrote 4 bare `path:NN` anchors into `ESPALIER_MEMORY.md`, pushing the tree past `_MAX_BARE_ANCHORS=7` and leaving `main` RED at `9960fab` — confirmed on a pristine HEAD worktree, 3 `test_catalog_self_consistency` failures, fixed 2026-08-12. **Structural, not an accident: a handoff row is exactly the prose that cites line numbers, so it will recur.** `post_write_check` already validates each written file and already special-cases `ESPALIER_MEMORY.md` (autoprune); adding the check there catches it in-session when it is a one-line fix. |
| `DEC-14` | `docs/REDEFINED_INFORMATION_REGISTRY.md:70` | C-F02 / C-F03 remain Needs-decision in the registry with a written but unratified recommendation; the C-F03 scope estimate is a material undercount. |
| `DEC-10` | `tools/cc/ci_guard.py` | DEC-10: ci_guard.py and harness-guard.yml ship without the espalier:managed marker, so clean-generated preserves rather than deletes them, and a stale harness-guard.yml keeps running in an adopter's CI after 'removal'. |
| `DEF-347c` | `tools/cc/reflect_protocol.py` | DEF-347c: the reflect-candidate un-suppress/expiry policy is parked behind a skip-rate trigger that is already shipped and mechanical, so the candidate's stated blocker is false at HEAD. ⚠ Note 2026-09-05 (DEF-685): `held` rows now leave the skip-rate denominator, so the mechanical trigger this row defers to cannot fire on a held pile; the pass prints `HELD: N` with a hint past 5 instead — an expiry policy still has no mechanism. |
| `DEC-13` | `espalier/provenance_census.py::_ALLOWLISTED_FILES` | ESPALIER_MEMORY.md remains inside the provenance census allowlist while accreting pack-id residue; keep-or-de-allowlist is an open operator call. 2026-09-21: the same question asked of the tracked task-packs/ set went the other way -- the forward ledger, its probes file and the packs are MADE of pack ids, so `task-packs/` joined `_EXCLUDED_PREFIXES` as a whole rather than the per-file allowlist; the ESPALIER_MEMORY.md call stays open |
| `DEC-15` | `ESPALIER_MEMORY.md:0` | ESPALIER_MEMORY.md's [[wikilinks]] render as literal brackets on GitHub, but 35 tracked docs use the convention and memory/CLAUDE.md prescribes it |
| `DEF-412c` | `CLAUDE.md:0` | Root CLAUDE.md's command/agent/skill tables restate the auto-rendered cc/ docs; only the Skills table is paid twice in one context window |
| `DEC-17` | `memory/action-justification-protocol.md:51` | DEC-17: whether action_justification capture becomes mandatory is an unresolved operator call whose stated trigger ('observed signal value') has no producer, so it can never surface on its own. |
| `DEF-344` | `tests/test_portability_contract.py` | DEF-344: the no-non-ASCII runtime-output net is allowlist-bounded and does not see join-then-print sites, argparse help strings, or non-leading .sh emit |
| `DEF-865` | `task-packs/FORWARD_LEDGER.md:309` | Community-contribution outreach (drafted in a 2026-07 pack that landed without it) is deferred to release; its former ledger row also mislocated the pack |
| `DEC-5` | `tools/cc/hooks/session_start.py::_SECTION_SOURCE` | DEC-5: whether to shrink GOAL.md or lower the SessionStart goal cap is an optional operator lever. |
| `DEC-9` | `task-packs/FORWARD_LEDGER.md:1984` | Two unratified operator forks: whether the CC plugin listing front-doors a pipx install, and whether clean-generated reports or deletes its residue. |
| `DEF-866` | `task-packs/FORWARD_LEDGER.md:610` | The five Wave-2 corrections of a landed 2026-07 conventions pack are conditional on a CONVENTIONS.md -> docs/INVARIANTS.md split that was never built. |
| `DEF-279a` | `task-packs/FORWARD_LEDGER.md:780` | The three deferred folder routers (scripts/, bench/corpus/, cc/) are an open build-or-decline call, not a defect. |
| `DEC-16` | `task-packs/FORWARD_LEDGER.md:2058` | Whether the anti-malice hook machinery is moat or scope creep is an unresolved operator call, and the report that names it declines to resolve it. |
| `DEC-7` | `CHANGELOG.md:11` | The [Unreleased] CHANGELOG omits the advisory `espalier scan` telemetry/credibility surface; adding it reverses a prior deliberate curation. |
| `DEC-28` | cc/GOAL.md:18-23 (the fork); tools/cc/hooks/session_start.py::_goal_section (:1462-1478) is the surface it would change; task-packs/FORWARD_LEDGER.md §4A (:2335) is the home | A live operator fork exists only in a gitignored snapshot doc that `/handoff` rewrites. `cc/GOAL.md:18-23` carries both halves of a SessionStart injection-shape decision — the operator's own proposal ("inject Notes + essentials, point at the rest") and the counter-proposal ("cut by KIND, not section: derivable state COMPUTED or omitted and never quoted; judgement stays but hedged; reference becomes pointers") — and neither appears anywhere in FORWARD_LEDGER.md. The carrier is rewritten at every `/handoff` and its surrounding premise is already falsified at HEAD, so the fork dies with the next boundary. Secondarily a future session, which currently inherits a START-HERE block asserting a defect that 1381421 fixed and a line citation resolving to unrelated banner-assembly code — the exact "injected text reads as settled fact" failure the block is about. File as a new `DEC-` row in §4A (19 rows today). Adjacent but distinct from DEC-5 (:2354), which is the SIZE lever — whether to shrink GOAL.md or lower the SessionStart goal cap — not the injection SHAPE. |
| `DEC-29` | tools/cc/hooks/task_router.py (absence); owned today by task-packs/FORWARD_LEDGER.md:2341 (DEC-26, trailing 'Related:' sentence) | Every mechanical gate that could catch a pack built on a false premise sits AFTER the expensive artifact exists. `task_router.py`'s UserPromptSubmit classifier has nothing premise-shaped (`command grep -ci premise` → 0), and `memory/premise-check-before-authoring-a-fix.md:95-120` names that hook as the natural home while labelling itself "Unbuilt — proposal, not a mechanism" and explaining why a `0-A` checklist item would not do (0-A runs after the pack exists). Twice the gates passed or reviewed a pack whose `## Goal` was false: a pack since scrapped after it had already landed and had to be reverted, the adopter-minors roadmap (2026-09-08) after 350 lines of authoring plus a full REQUEST-CHANGES review. Both times the only thing that caught it was the operator asking a question. The decision — fire a premise-check hint at pack-authoring time, or record the decline — is the operator's alone, so promote it out of DEC-26's trailing "Related:" footnote into its own §4A row; it shares DEC-26's surface and should be decided in the same edit. |
| `DEC-30` | `espalier/managed_inventory.py::_SEED_DOC_REL_PATHS` (20 seeds, ~1.09 MB on this tree); `memory/publish-from-a-generated-public-repo.md` (DEC-25, the release-repo plan) | **Which seeded docs ship — and whether the exclusion happens at the public-repo boundary rather than in the seed list.** A corpus-blind wheel walk (2026-09-05) found the seed payload is the stranger's largest first-impression cost: 20 docs into a three-file repo, with self-host content inside — `CHEAT-SHEET.md` 'Key Bash Commands' is this repo's pytest suite, `ENV_CATALOG.md` is wholly self-host, `/handoff` (406 lines) and `/implement-pack` (458 lines) carry inline 'self-host step, skip' blocks citing eleven scripts an adopter never receives. **Operator stance, 2026-09-05:** `FAILURE_MODES.md` and `SHARP_EDGES.md` SHIP — knowledge is an Espalier asset (organise it after the alpha). The other seeds are candidates to leave out of the PUBLIC repo itself, so they cannot be seeded, rather than to trim in the seed list. Not decided: which of the remaining 18 go, and whether §C18/§C20's self-host-content sweep runs over what stays. Depends on DEC-25's method being detailed. |
| `DEC-32` | `espalier/mirror_registry.py::MIRROR_ROWS` (nine rows, five of them tracked byte-copies of a source tree: vendor-cc, claude-asset, asset-docs, task-packs-router, selfcheck-tests); the vendored-byte-copy rule in the root CLAUDE.md architecture section (shipped as package-data) | **Whether the packaged assets stay tracked byte-mirrors or are generated at build time.** Five of the nine rows exist because a wheel cannot carry top-level tools/ or .claude/, so the deploy source is a tracked copy under espalier/, each with a sync script, a parity test and an advisory. Generating them in the build (a setuptools build step, or a pre-build script the release workflow runs) would retire those five rows, their sync scripts and parity tests, and the eight open mirror-tooling defects (DEF-419b, DEF-489, DEF-419d, DEF-441, DEF-682, DEF-419c, DEF-477, DEF-419e), and would show a public reader one copy of each file instead of two. Costs, unmeasured: an editable or checkout install needs the build step to have run; the self-host tree runs its hooks from the source side already, so the mirrors would still need generating locally for the deploy-source tests; and the vendoring rule chose tracked byte-copies deliberately. Not a decision the release plan forces: DEC-31 changes nothing about the wheel, and the dogfooding row is the only one the public repo makes redundant. Measure before deciding: count the tests and scripts that read the five mirror paths, and drive a wheel build from a tree with the mirrors deleted. Filed 2026-09-07. |
| ~~`DEC-35`~~ | espalier/models.py::HarnessConfig | ✅ **CLOSED 2026-10-08 — decided by the operator on 2026-10-08 (the proof-chain pack's D1, its recommended default): the stop-time test command lives in the environment first (`ESPALIER_STOP_GATE_TEST_CMD`), then in `espalier.toml` as `[extra_actions] test` -- the committed home, the key `/preflight` already runs, read hook-side by `tools/cc/hooks/stop_gate.py::_declared_test_commands` through `_hook_utils.read_toml_table` (a value that is not a list of command strings is said once; the empty list reads as not declared, as the engine reads it) -- then the fingerprint's detected command; the mode stays environment-only; the detected arm blocks on timeout as the override arm does. Not taken: (a) a `[stop_gate]` table (one more key for one hook when the declared test command exists already), (b) the hash-gated command (the guard is a toolbelt, not a security boundary, `docs/STANDING_PRINCIPLES.md` §2, and gating one reader of a key makes two readers disagree), (c) the shell-string reuse (the hook spawns without a shell), (d) env-only (a gate that announces itself off). The row's "silently dropped" clause was refuted at HEAD on 2026-10-07 (`espalier/config.py::load_config` warns on an unknown key; the pack's Task 0-C). Landed on `lane/gate1-runs-the-detected-command`; `DEF-949` step 4 struck beside it.** PRIOR TEXT: **Whether the stop-time test gate gets a committed home, and in what shape.** Every input Gate 1 reads is per machine: `tools/cc/hooks/stop_gate.py::_stop_gate_mode` and `::_resolve_core_tests` read only `ESPALIER_STOP_GATE` and `ESPALIER_STOP_GATE_TEST_CMD` from the environment; the fingerprint's `test_commands` lives under gitignored `reports/` and is rewritten by `espalier/analyze.py::detect_tests` on every `init`; and `.claude/settings.json`, the `env` home `docs/CONVENTIONS.md` and `docs/SHARP_EDGES.md` recommend for the mode, is in `espalier/cli.py::REQUIRED_GITIGNORE` because it records the machine's interpreter name (an `env` block there survives a re-run of `init`, which renders `settings.json.new` beside it, but never leaves the machine). `espalier/models.py::HarnessConfig` has no stop-gate field and `espalier/config.py::load_config` filters unknown keys against the dataclass's field names silently, so a `[stop_gate]` table in `espalier.toml` is dropped without a warning: driven, `init` exits 0 with no mention of the table, `reports/harness_config.json` carries no such key, and the Stop hook allows with a planted failing test. A fresh clone, a fork, a teammate or a second workstation therefore falls back to `light` after `init`, and a repository meant to be forked cannot ship its proof command. Who: the adopter who armed the gate on one machine and finds every other checkout ungated with nothing saying so. Options: (a) an optional `[stop_gate]` table (`mode`; `argv` as a list, which also sidesteps the Windows-vs-POSIX `shlex` split the override manages; `cwd` relative to the root and refused outside it) read by the hook the way `tools/cc/hooks/plan_guard.py::_load_adopter_exempt_prefixes` reads `plan_exempt_prefixes` (inline `tomllib` or `tomli`, regex fallback on 3.10 that recovers only flat keys), environment first, table second, default last, validated on the espalier side and surfaced in `harness_config.json`, `doctor` and the banner as `STOP=full (espalier.toml)` against `(env)`; (b) the same table honoured only after `init` records its hash in `.espalier/integrity.json` on each machine, with a SessionStart warning when it changes since -- the `direnv allow` shape -- because a committed command is repository content that a pull request or an agent can rewrite and `plan_guard` is not wired for Bash, so a shell write reaches `espalier.toml` without a plan (adding the file to `write_guard`'s protected set, matcher `*`, is the alternative mitigation); (c) reuse an `[extra_actions]` entry as the command, which brings back shell-string spawning; (d) keep the gate env-only and say in the docs that it does not travel. Whichever wins, the runtime budget stays 60 s and a timeout on the override path blocks, so the docs should recommend a fast source-layer command. Not deciding leaves the CONVENTIONS and SHARP_EDGES recommendation pointing at a gitignored file, a docs fix that can land now. The class rows for the override's root and spawn and for the dormancy surfaces apply to whichever shape wins. Evidence: espalier-issues/EI-02. Related: §C52 lands the gate either way. |
| ~~`DEC-36`~~ | espalier/harness_config.py::OPTIONAL_AGENTS + espalier/doctor.py::_three_way_ownership (the DEF-756 `unshipped_saved_agents` arm) + README.md (the roadmap's language-aware templating promise) | ✅ **CLOSED 2026-10-06 — decided (b), demote, by the operator on 2026-10-06 and landed the same day by the Node-defaults lane (§C57): an `OPTIONAL_AGENTS` row joins the plan's agents only when this release ships its body; otherwise `harness_config.suggest_agents` saves it as the plan's `suggested_agents`, which `init` prints once and nothing deploys, owns or reports; `doctor._primary_reason` ranks the next step above information, so a healthy run never headlines one; `test_component_reviewer_included_for_ui_surface` and its api and ml siblings inverted by design. The fact row `DEF-964` is struck with it. Revisit trigger unchanged: the language-aware templating layer README promises would make (a) its natural home.** PRIOR TEXT: **Ship a body for what the plan recommends, or stop recommending it.** `OPTIONAL_AGENTS` recommends seven agents (`api-reviewer`, `experiment-analyst`, `data-engineer`, `component-reviewer`, `content-reviewer`, `strategy-analyst`, `engagement-analyst`) and the package ships a body for none; DEF-756 chose to keep the recommendation visible as doctor `info` rather than delete it, and README's roadmap promises a language-aware templating layer. Fork: **(a) ship** -- a language-neutral body per recommended agent under `espalier/assets/claude/agents/`, marker-managed like the others, deciding at the same time whether each joins the Gate 3 or Gate 2 relief table (EI-17), since a shipped `component-reviewer` that cannot relieve the gate is half a promise; cost: seven bodies to author and keep honest across stacks, the SHARP_EDGES rule that a dogfooding artifact cannot double as a deployment template applies to each, and `TIER_CONTRACT` gains seven rows. **(b) demote** -- move bodiless names out of `agents` into a `suggested_agents` list that `init` prints once and doctor never headlines; cost: the fingerprint's surface detection stops producing anything an adopter can act on, and `test_component_reviewer_included_for_ui_surface` inverts. **(c) hold DEF-756 as is** and only reorder `_primary_reason` so info never headlines a healthy install; cheapest, leaves the recommendation cosmetic. Revisit trigger: the language-aware templating layer README promises lands, which makes (a) its natural home. No probe: an operator choice; the fact row EI-18 carries the measurable half (bodiless names, 7 of 7). Evidence: espalier-issues/EI-18. |
| ~~`DEC-37`~~ | espalier/settings_profiles.py::_workflow_fingerprint_allows + tests/test_settings_profile_fingerprint.py (the allow-list-reflects-fingerprint pack's docstring and its `typescript_npm` row) + docs/SHARP_EDGES.md (Generated Settings With Zero Deny Rules Read As Trusts Everything) | ✅ **CLOSED 2026-10-06 — decided (a), narrow everywhere, by the operator on 2026-10-06 and landed the same day by the Node-defaults lane (§C57): `settings_profiles.narrowed_rules` keeps each derived command's subcommand and a script runner's script name, in both the exact and the wildcard form, and never derives a bare `Bash(<binary> *)`; lint, test and build derive from the fingerprint's inferred actions and from `espalier.toml` `[extra_actions]`, so the repository's own gate does not prompt; the pytest, ruff and black rules render for a Python fingerprint only. On the rule semantics the row asked to check: no excerpt pinned under `docs/external/` settled whether `Bash(npm test *)` matches a bare `npm test`, so both forms ship; the live permissions page read the same day says a trailing ` *` also matches the bare command, which makes the exact form redundant but harmless until an excerpt is pinned. The fact row `DEF-965` is struck with it.** PRIOR TEXT: **Does the allow-list-reflects-fingerprint pack's prompt-flood relief license a bare-binary allow, or was it always a narrow-command promise?** the allow-list-reflects-fingerprint pack introduced `_workflow_fingerprint_allows` so that TypeScript, Go and Rust adopters following QUICKSTART do not hit a permission prompt on every `npm test` or `cargo build`, and its contract test pins `Bash(npm *)`, `Bash(go *)`, `Bash(cargo *)` and `Bash(make *)` as the rendered rules; DEF-714 then narrowed the Python case only, on the ground that `Bash(python *)` is the rule the self-host profile forbids; and the SHARP_EDGES entry on generated settings records a v0.6 allow list carrying `Bash(python *)` and `Bash(pip *)` as the anti-pattern the workflow profile replaced with narrow test commands. On an npm repository `Bash(npm *)` is that anti-pattern under another binary: npm is a package installer and a script runner, not a test command. Fork: **(a) narrow everywhere** (EI-19's pack): the fingerprinted command plus its wildcard form, `Bash(npm test *)`, `Bash(npm run build *)`, at the cost of one prompt per other script (`npm run lint`, the adopter's own gate) unless those are derived from `inferred_actions[lint]` and `[extra_actions]` too, which is the natural offset, and needs a check of Claude Code's current rule semantics that `Bash(npm test *)` also matches a bare `npm test`. **(b) keep the bare binary for script runners** and document it: honours the allow-list-reflects-fingerprint pack's letter, contradicts the docstring, the SHARP_EDGES prior art and DEF-714's reasoning, and leaves `npm exec --yes` and `npm install` pre-approved. **(c) narrow the default and widen only under the opt-in `full` profile**, where broad bash already lives. Whichever is chosen also settles whether the static Python formatter rules are conditioned on the fingerprint; their rewrite of `tools/cc/` is EI-19's second half and not a the allow-list-reflects-fingerprint pack question. Revisit trigger: an adopter measurement of prompt frequency under (a). No probe: an operator choice about the allow-list-reflects-fingerprint pack's intent; the rendered rules are EI-19's probe. Evidence: espalier-issues/EI-19. |
| `DEC-38` | espalier/managed_inventory.py::_SEED_DOC_REL_PATHS | **Where the init seeds land: the adopter's namespace, or a harness-owned one.** Whether the twenty init seeds keep landing directly in the adopter's `docs/`, `memory/` and `task-packs/` (18 of them beside the adopter's own documents, reading as the project's own: `docs/CONVENTIONS.md`, `docs/WORKFLOW.md`) or move under one harness namespace such as `docs/espalier/`, and whether `clean-generated --execute` deletes a seed it can prove untouched. Measured at 550314e: right after init every one of the 20 seeds satisfies the predicate `espalier/cli.py::_seed_redeploy_decision` already computes (stamp present, body hash matching), and the dry-run uninstall still lists all 20 plus `ESPALIER_MEMORY.md` under `preserved_user_files`; a fixed-string grep for the 20 seed paths finds 283 occurrences in 58 files under `espalier/assets/` and `espalier/_vendor/`, and 28 engine modules name at least one (an upper bound, some are self-host references), so a move is a migration with changed link depths, not a rename. Options: (a) namespace new installs and migrate stamped, untouched copies, leaving edited copies in place and reported, which makes a formatter-ignore snippet one line and the uninstall one directory but pays the 283-site sweep and re-anchors `tests/test_deploy_doc_parity.py::test_seeded_doc_links_resolve_to_deployed_targets`; (b) keep the placement and take the long ignore list; (c) independently of either, uninstall the provably untouched seeds and list the edited ones, which is one answer to DEC-9's second fork. Interacts with DEC-30 (a seed excluded at the public-repo boundary needs no namespace) and keeps plan_guard's universal `docs/` exemption only while the namespace stays under `docs/`. Evidence: espalier-issues/EI-24. |
| ~~`DEC-39`~~ | tools/cc/ci_guard.py::PROTECTED_PREFIXES (the `.github/workflows/` entry and its self-host-workflow comment), ::is_protected (applied on every repo) and ::approval_marker_required (False only for a self-host push); tools/cc/hooks/_hook_utils.py::harness_protected_prefixes (the local layer's opposite policy); tests/test_ci_guard.py::TestApprovalMarkerRepoPosture.test_adopter_push_without_marker_is_denied and ::_touch_protected (the 2026-08-02 ruling's pin); docs/INSTALL-CI.md#3-approving-legitimate-harness-updates ('every workflow') | ✅ **CLOSED 2026-10-11 — decided (b) by the operator on 2026-10-10 (TP-474 Decision 1) and landed on lane/ci-marker-and-posture: `tools/cc/ci_guard.py::is_protected` gates `.github/workflows/` under the self-host posture alone (`SELF_HOST_PROTECTED_PREFIXES`; the one-argument call, the ship driver's, is the self-host answer), `run()` judges that posture on the tree under review OR its base so a change can tighten its own gate but never loosen it, `espalier/surface_contract.py::is_protected_from_ci` mirrors it, and `harness-guard.yml` and `ci_guard.py` stay exact-file rows gated everywhere. The Walk's own-`ci.yml` pull-request replay exits 0 with its bridge deleted; `docs/INSTALL-CI.md` section 3 and the generated ci-gated-paths block scope the row, and `install-ci` says so once when it replaces a guard that gated every workflow.** PRIOR TEXT: **Whether `ci_guard` keeps gating every adopter workflow behind the approval marker, or aligns with `write_guard` and gates only the harness's own files on an adopter repository.** The two layers apply opposite policies to one path: `tools/cc/hooks/_hook_utils.py::harness_protected_prefixes` makes `.github/workflows/` a self-host-only prefix for the local guard, its docstring calling an adopter-wide prefix 'the governing-frame cardinal sin: a false-positive on user-owned code' and the CI layer 'a separate, deliberate layer'; `tools/cc/ci_guard.py::PROTECTED_PREFIXES` lists `.github/workflows/` on every repository, justified in its comment by espalier's own `release.yml`, `refresh-externals.yml`, `end-to-end-bench.yml` and `benchmark.yml`, `::is_protected` applies it everywhere, and `::approval_marker_required` returns False only for a push on the self-host repo. Driven in the write-up on two fresh clones (the three sites re-read at HEAD, v0.8.0b2): an adopter-only `ci.yml` edit (`echo hi` to `echo hello`) exits 2 for both `push` and `pull_request`, the denial calling that file 'the harness's own enforcement layer: settings, hooks, the integrity manifest and this guard', while `write_guard` allows the same edit and denies `harness-guard.yml`. The status quo is a ruling, not an accident: `tests/test_ci_guard.py::TestApprovalMarkerRepoPosture::test_adopter_push_without_marker_is_denied` pins exit 2 for a marker-less adopter push touching `.github/workflows/test.yml` (operator ruling 2026-08-02, the marker scoped by repo posture), `ci_guard.py`'s rejected Horn B refuses to drop the prefix for pull requests as 'removes HUMAN protection on the same path', and `docs/INSTALL-CI.md#3-approving-legitimate-harness-updates` documents 'every workflow, not only harness-guard.yml'. Both were reasoned for espalier's own workflows on its own public repository; for an adopter the open question is whether the harness should own review of workflows it did not write, and the local layer has already answered no. Fork: (a) keep the ruling and disclose the cost at install time (the DEF row filed beside this one); (b) make the prefix self-host-only in `ci_guard` (it already has `::_ci_is_self_host_repo`), keep `harness-guard.yml` and `ci_guard.py` exact-match protected everywhere through `PROTECTED_FILES`, and re-point `::_touch_protected` at a harness path so the posture test keeps its three axes without pinning the old policy; (c) adopter opt-in to whole-tree protection through configuration (once EI-22 warns on unknown keys). Trade under (b): an agent can weaken an adopter's other workflows without a marker, subject to the adopter's own branch protection and review, which is the same trade the local layer already made. Who is hurt today: an adopter who edits their own `ci.yml` after `install-ci` and reds their merge gate until they learn the marker, reading a message that misnames their file. `DEC-10` is the sibling question on the same file (removal), not this one. Evidence: espalier-issues/EI-27. |
| ~~`DEC-40`~~ | tools/cc/hooks/plan_guard.py::_PLAN_EXEMPT_HINT | ✅ **CLOSED 2026-10-08 — fork (a) taken by the operator on 2026-10-08: the two runtime denials cite `docs/HOOKS.md` by heading ("Execution plan gate" for the plan hints and the misplaced-key advisory, a new "Maintenance mode" heading for the env-prefix deny), a doc `init` always deploys whole, so the pointer resolves on a tree whose CLAUDE.md `init` kept. `REQUIRED_CLAUDE_MD_SECTIONS` and the init nudge stay (the sections still earn their place in a CLAUDE.md `init` writes; the tuple is a subset ratchet). Fork (b) stays closed: the hint keeps the literal `src/`, with its revisit trigger unchanged (first-session drop-off in adopter feedback; the pack's drive was a rehearsal, not that feedback). Gated by `tests/test_denial_reasons.py::TestHookCitationsPointAtDeployedHeadings` (no hook cites a CLAUDE.md section; every whole-seed citation resolves in the packaged copy) and `tests/test_plan_guard.py::TestFirstSessionDenyPointsAtWhatExists`.** PRIOR TEXT: **Which file the two runtime denials should cite.** Two runtime denials send an adopter into a file the harness does not own, and the section one of them cites prescribes exempting the adopter's main source root. `tools/cc/hooks/plan_guard.py::_PLAN_EXEMPT_HINT` ends every plan-required deny with `see CLAUDE.md Plan Guard section` and `tools/cc/hooks/_denial_reasons.py::HARNESS_ENV_PREFIX_INLINE` ends the harness env-var deny with `See CLAUDE.md Maintenance mode section` (the seeded `docs/ENV_CATALOG.md` repeats it); `tests/test_denial_reasons.py::_cited_claude_md_sections` derives exactly those two, which is why `REQUIRED_CLAUDE_MD_SECTIONS` exists and why the nudge asks an adopter to paste them. The section the hint cites, as `espalier/cli.py::_build_claude_md` renders it for a `src_layout` fingerprint, reads `Your source lives under src/` and prescribes `plan_exempt_prefixes = ["src/"]`; the hint carries the same literal and the Maintenance mode section closes with the same advice, so the onboarding text recommends turning the plan gate off for nearly all of the source it was installed to gate, without stating that cost. Driven at 550314e: a `plan_guard` deny for a `src/` file and a `write_guard` deny for a shell export of the maintenance-mode switch both carried the citations quoted. Fork (a), the citation target: keep citing `CLAUDE.md` sections and requiring them, or point both denials and the ENV_CATALOG row at a document `init` always deploys (`docs/HOOKS.md` or `cc/LIVE_SURFACE.md` anchors), after which the ratchet derives zero `CLAUDE.md` citations and the required-sections tuple becomes advisory for adopter-owned files (a class C18 member if taken). Fork (b), the advice: keep the literal `src/` (docs/RELEASE_DECISIONS.md 2026-06-10, Fusion plan-gates the adopter's source, keeps the hint as the at-friction discoverability path, and docs/sharp-edges/plan-guard-adopter-source-roots.md presents `["src/", "lib/"]` as the right relief), or lead with `/implement-task`, name the knob without a value, and say that exempting a source root turns plan discipline off for it, keeping the maintenance-mode warning. That decision names adopter feedback on first-session friction as its revisit trigger, and this is the first such feedback. Evidence: espalier-issues/EI-28. Fork (b), the src/ advice, is settled by docs/RELEASE_DECISIONS.md (2026-06-10) with its own revisit trigger and is not reopened here; only fork (a) is open. |
| `DEC-41` | espalier/harness_config.py::CANONICAL_HOOK_WIRING (no entry carries `onFailure`, so every wired hook keeps the default `"continue"`); docs/external/cc-hook-protocol.md#Block the action when a hook fails (new 2026-10-10, not wired); docs/SHARP_EDGES.md#A missing `write_guard.py` wedges the whole session, and the fix is not reachable from inside it | **Whether espalier writes `"onFailure": "block"` on its blocking gates, so that a guard which cannot start, crashes past its umbrella or times out blocks the call instead of letting it through.** Upstream added the field on 2026-10-10 (Claude Code v2.1.295 or later; pinned in `docs/external/cc-hook-protocol.md`), and win-2 raised it the same day (mail note `20261010T181256Z-win-2-3a5dd0`, re-raised in `20261010T221004Z-win-2-9a3b62`). Until now the only record is two sentences saying espalier does not set it: the protocol pin's "Not asserted" paragraph and the first entry of `docs/SHARP_EDGES.md`. Today the rendered settings carry no `onFailure` on any hook (`espalier/cli.py::fresh_settings` on an empty tree, 2026-10-12: every entry is `continue`). Fork: **(a) block on the gates** (`write_guard` and `plan_guard` on PreToolUse, `config_guard` on ConfigChange). A gate that cannot run then stops the action instead of failing open, which closes the case `docs/SHARP_EDGES.md` names: a moved or deleted interpreter (exit 127, empty stdout) that leaves every tool call unguarded. Cost: the same failure then refuses EVERY tool call, because `write_guard`'s matcher is `*`, and that entry says the wedge cannot be repaired from inside the session. A guard that overruns its 5-second timeout on a loaded machine refuses the call instead of passing it. The field needs v2.1.295, and the pin does not say what an older client does with it. `merge-settings` and `upgrade` append missing events and preserve existing entries, so an installed base gets the field only through a re-render or a hand edit (probable, from the contract of `espalier/cli.py::merge_hooks_into_settings`). It must not go on the reporters: a failure "does what exit code 2 does on that event", which on UserPromptSubmit blocks the prompt, and it has no effect on Stop and SubagentStop. **(b) keep the default `continue`**, which follows the toolbelt-not-boundary frame (`docs/STANDING_PRINCIPLES.md` §2) and the rule that friction outranks closing a bypass. A broken gate stays visible only through the non-blocking `hook error` notice and doctor's report of a wired hook that cannot start. Cost: inside the session the fail-open stays silent, and the BaseException umbrellas remain the only defence. A middle path, **(c) opt-in per tree** through an `espalier.toml` key that renders the field on the gates, adds one key to the surface §C53 governs. Affected: every adopter whose settings `init` renders, and the self-host operator, whose session would wedge under (a) the first time a gate cannot start. Revisit trigger: a recorded session where a gate failed open and a call it would have denied went through (none recorded as of 2026-10-12); the supported Claude Code floor reaching v2.1.295; or a pinned upstream statement of what an older client does with the field. |
| ~~`DEC-33`~~ | `.gitattributes` (the five sentinel rows `export_sentinels` derives, out of seven plain-file `export-ignore` rows with two forgiven, and the `.claude/workflows/` row) + `reports/seed-carry-2026-09-25/` (the parked copies, gitignored) + the frozen archive tree `espalier_harness_dev_private` | ✅ **CLOSED 2026-09-26 — decided 2026-09-26 by the operator, branch (a) plus the full sweep, and landed by TP-457 the same day: the two release docs are tracked and read on GitHub (still `internal`, out of every shipped artifact); the thirteen never-returning names (the registry, the findings ledger, the publish memo, the three atlases, the seven dated round scripts) left every roster, floor, registration and live pointer, each surviving mention naming the archive `Mike-Byrne-AI/espalier_harness_dev_private`; the three standing review scaffolds came back; `is_release_export` reads False here and its docstring carries the clone-versus-export model and the `.git` refutation; the `full_tree` registry is 48 rows, 0 red here and red on the extracted export except the vacuous four; `DEF-923` and `DEF-924` struck, `DEF-625` and `SUP-2` closed with the dated scripts, the six UNRESOLVED probes re-pinned as STILL_OPEN. The parked copies under `reports/seed-carry-2026-09-25/` are redundant for the two docs and remain the only local copies of the rest.** PRIOR TEXT: **Where the maintainers' withheld files live now that this tree does the releasing.** The 2026-09-25 seed dropped nineteen tracked-but-export-ignored files: `docs/RELEASE_CHECKLIST.md`, `docs/RELEASE_DECISIONS.md`, `docs/RELEASE_FINDINGS_LEDGER.md`, `docs/REDEFINED_INFORMATION_REGISTRY.md`, `memory/publish-from-a-generated-public-repo.md`, the three `memory/*-atlas.md` files, `ESPALIER_MEMORY.md` (adopted since, PR #3) and the ten one-shot `.claude/workflows/*.js` review scaffolds. The eighteen still out live in the frozen archive and in the gitignored `reports/seed-carry-2026-09-25/` of this checkout, so the tree that runs the next release carries neither its runbook nor its decision log, and every oracle written against the full development tree dangles: eight ledger probes read UNRESOLVED (`DEF-393a`, `DEF-874`, `DEF-885` on the checklist; `DEF-450` and `DEC-28` on the decisions log, the latter crashing rc=1 because its input was never declared and the verbs cannot address a three-cell §4 row; `DEF-324c`, `DEF-625`, `SUP-2` on the workflows), 61 `full_tree` test rows auto-skip everywhere (`DEF-923`), six reader-facing pointers name an absent runbook (`DEF-924`), and `CONTRIBUTING.md` (:180) tells a contributor the runbook is in a private archive. Fork: **(a) adopt the two release docs here** as tracked files after a read for account and settings names (the seed-carry scans of 2026-09-25 found zero codename hits and no machine-local path in either), keep the findings ledger out (its line 114 carries a machine-local path), the registry and the atlases out (zero adopter value, retire their rows), and the workflows out (one-shot scaffolds, re-anchor their three rows to the archive or retire them), then re-key each remaining oracle onto the adopted file; **(b) keep everything in the archive**, update the runbook there for `0.8.0b2`, and re-anchor every row and pointer to say so; **(c) a third, private maintainers' repository** holding the eighteen, named by every pointer. Measured: (a) is the only branch under which `tests/test_release_checklist_contract.py`'s six rows run again on any tree and CONTRIBUTING's sentence becomes true as written; (b) freezes the runbook in a tree nobody develops on; (c) adds a third remote to every release sitting. Recommended (a); the operator decides, since the docs name the operator's own accounts. Until decided, `DEF-450` stays UNRESOLVED by design and the landing check's dangling-input test excludes an absent export-ignore sentinel by derivation (2026-09-26). A cost the PR #8 review predicted for (a), that adopting the docs would red `tests/test_operator_docs.py`'s linked-or-exempt gates, was refuted by driving it on 2026-09-26: `classify_release_path` reads both docs `internal`, that module's population is `public` only, and it stayed green with the docs present; what does red is the never-returning set's floors and rosters (28 `full_tree` rows in four groups), which is the sweep. DECIDED 2026-09-26 by the operator: branch (a) plus the full sweep, drafted as `TP-457` (`task-packs/TP-457-adopt-the-release-docs-and-sweep-the-withheld-set.md`); the row stays live until that pack lands. When decided and landed: strike this id by hand, double tildes around the id cell, because `strike` refuses a three-cell row (`DEF-869`); the owed-item probe `dec33-withheld-files` in `cc/GOAL_OWED.json` keys on this row's unstruck id cell and reads DONE only then. |
| ~~`DEC-34`~~ | `espalier/fusion_manifest.py::HARNESS_EXCLUDE` + `espalier/surface_contract.py::_LOCAL_ONLY_PREFIXES` + `.gitattributes` (the `.claude/workflows/ export-ignore` row) + `espalier/cli.py::_packaged_md_assets` (the deploy set, three kinds) | ✅ **CLOSED 2026-09-27 — decided (a) by the operator on 2026-09-27 and landed by the pack *Decide whether the three standing review scaffolds deploy to adopters through init, and land the branch the operator picks*: the three deploy, parametrized, as a fourth `.claude` kind (`surface_contract.CLAUDE_KIND_GLOBS` gains `workflows`), each with `// espalier:managed` on line 1 ahead of `export const meta`, and the review memory is seeded beside them (`memory/CONVERGENCE_LEDGER.md` as a skeleton, `memory/convergence-review-protocol.md` adopter-neutral under the adapt header, both stubs under `espalier/assets/seed/` routed by `managed_inventory._SEED_ASSET_SOURCES`). The four sites this row named now read the other way: `fusion_manifest.HARNESS_EXCLUDE` and `surface_contract._LOCAL_ONLY_PREFIXES` carry no `.claude/workflows/` entry, `.gitattributes` has no export-ignore row for it, and `cli._packaged_md_assets` reads the owner's kinds. Two amendments recorded at the decision: the `Workflow(<name>)` allow twins are not written (the first run of each scaffold asks under the manual and accept-edits modes), and the Claude Code docs were re-read the same day (autoload and paid-plan gating hold; the approval prompt is per permission mode, not per run). Measured at execution: both censuses (twenty-four production modules) swept, every earned red driven, three 0-A rounds and a two-lane red-team folded, the benchmark regenerated at 373 of 373.** PRIOR TEXT: **Whether the three standing review scaffolds deploy to adopters through `init`.** Left open by the adopt-the-release-docs pack's 0-C (2026-09-26; the operator: good tools ship unless they are only useful to us; the three returned to the repository and deploying them was named its own pack). Today three shipped surfaces answer no and record one premise, "each carries espalier refs". MEASURED 2026-09-27 at the authoring of the pack *Decide whether the three standing review scaffolds deploy to adopters through init, and land the branch the operator picks*: the coupling census classifies the references as runtime (the two engine modules, the `reports/` outputs, and the template's `memory/CONVERGENCE_LEDGER.md` default, which `init` does not seed), prompt (two sentences describing this tree as the adopter's) and comment; each scaffold's persist hop, extracted from its `persistCmd`, exits 0 on a fresh adopter tree built by `tests/_adopter_tree.py::build_adopter_tree` and writes only under `reports/` and `cc/`. So a verbatim deploy is refuted and the live fork is: **(a)** deploy all three, parametrized, with the deploy-inventory footprint (the kinds roster at its owner `CLAUDE_KIND_GLOBS`, a `.js` managed marker, three classification flips with two pins re-derived, a package-data glob, a count constant, two mirrors); **(b)** deploy `_fanout_audit.js` only; **(c)** no, recorded at the three surfaces with a copy-from-the-repository sentence for adopters. Authoring read: (c) unless an adopter asks, since the method ships as the engine and the schema and the footprint is carried by every later release; the operator decides. That pack (landed, in Done/) carries the measurement and lands the branch picked; the row stays live until it lands. When decided and landed: strike this id by hand, double tildes around the id cell, because `strike` refuses a three-cell row (`DEF-869`). |

### §4B — Filed in §4 but adjudicated not a decision

_Do not read these as pending choices. `kind` states what each actually is; the ground for each
verdict is listed under the table. A row here is kept for its id, not for its status._

| id | kind | site | what |
|---|---|---|---|
| `LG-15` | OWED WORK | `.github/workflows/end-to-end-bench.yml:18` | The end-to-end-bench weekly `schedule:` block is still commented out pending the ANTHROPIC_API_KEY_E2E_BENCH repo secret, leaving the only real-Claude-Code regression signal dark. |
| — | SETTLED | `memory/hook-authoring.md:1` | HD-1: memory/hook-authoring.md and .claude/skills/hook-authoring/SKILL.md both carry hook-authoring content with overlapping sections; which is content SoT is undecided. |
| `EXP-4` | SETTLED | `tools/cc/hooks/_born_weak.py` | EXP-4's verdict record: the blocking born-weak guard was abandoned, the observe-only observer shipped, promotion gated on a measured base rate. |
| `TP-359` | PACK — held in Deferred/ | `task-packs/FORWARD_LEDGER.md:199` | TP-359 is a deferred review-campaign ROADMAP pack (spawns fix children only on a survivor), not a defect. |
| `FM-21` | SETTLED | `task-packs/Deferred/TP-355-scanner-detector-v2-hardening.md:385` | TP-355 scanner/detector v2 hardening is a drafted pack the operator deliberately deferred past the flip. |
| `TP-356` | PACK — held in Deferred/ | `task-packs/Deferred/TP-356-selfhost-tooling-correctness-deadcode.md:370` | TP-356 self-host tooling correctness & dead-code is a drafted pack deferred post-flip. |
| `TP-358` | PACK — held in Deferred/ | `task-packs/Deferred/TP-358-bench-testability-engine-test-debt.md:255` | TP-358 bench-testability & engine test-debt is a drafted test-only pack deferred post-flip. |
| `TP-360` | OWED WORK | `task-packs/Deferred/TP-360-performance-levers.md:349` | TP-360's measured AST-cache performance lever is drafted and unlanded; scanners still re-parse every file per scanner. |
| `EA-1` | OWED WORK | `task-packs/FORWARD_LEDGER.md:1220` | The six cross-cutting espalier/ mechanical audit lanes are still owed — the executed round-9 workflow covers one of them. |
| `DEC-6` | SETTLED | `.claude/agents/harness-config-advisor.md:266` | The config-advisor's Universal command catalog lists 8 entries and omits 8 shipped commands -- an open menu-vs-inventory fork that the catalog's own disclaimer arguably already answers. |

**Grounds (2026-08-10, each verified against live code):**

- `DEF-414f` — **DEFECT**: its two sibling sites of the same tier are already filed as defects in §C9.
- `LG-15` — **OWED WORK**: an action (set the repo secret), not a choice; the cost posture is already fixed in the workflow file.
- `HD-1` — **SETTLED**: the SoT split is declared in tracked prose at `tools/cc/hooks/CLAUDE.md`; the residual is content non-conformance, not an undecided fork.
- `EXP-4` — **SETTLED**: a past-tense verdict record: the observe-only observer ships and the blocking form is absent at HEAD.
- `TP-359` — **PACK — held in Deferred/**: a classification note (Kind=ROADMAP), arguing it is not a defect — not a choice.
- `FM-21` — **SETTLED**: the operator deferred the whole pack on 2026-07-27; recorded in the pack's own stanza at `:391`.
- `TP-356` — **PACK — held in Deferred/**: restates the Appendix A entry; no fork in the sentence.
- `TP-358` — **PACK — held in Deferred/**: restates the Appendix A entry; no fork in the sentence.
- `TP-360` — **OWED WORK**: asserts a live technical fact, verified true — no AST cache exists anywhere in `espalier/scanners/`.
- `EA-1` — **OWED WORK**: states no fork — five of six audit lanes are simply owed.
- `DEC-6` — **SETTLED**: the advisor's own disclaimer answers it — `.claude/agents/harness-config-advisor.md:259-266` says *"never as an inventory of what exists"*.

## §5 — Cannot be closed locally

_Needs Windows, PyPI, CI or a GitHub repo setting. Not remaining *work* in the local sense — do not count these toward the backlog._

| id | site | what |
|---|---|---|
| ~~`LG-14`~~ ~~`LG-3`~~ | `SECURITY.md:15` | ✅ **CLOSED 2026-09-26 — measured on 2026-09-26 (walk 4, `EVIDENCE-lead.md`): `gh api repos/Mike-Byrne-AI/espalier-harness/private-vulnerability-reporting` reads `{"enabled":true}`, and the advisory link in `SECURITY.md` and `config.yml` redirects an anonymous reader to GitHub login instead of a 404, so both halves of the row's condition are answered; struck at both copies (§1A and §5) by TP-458, and, this being the last §1A row, §1's heading and lead sentence were edited by hand because no generator owns them.** PRIOR TEXT: GitHub's private-vulnerability-reporting setting is an owed pre-flip operator action; until it is on, SECURITY.md's preferred `Report a vulnerability` link and config.yml's contact_link both 404. |
| ~~`LG-2`~~ | `memory/windows-walk-output-routing.md` | ✅ **CLOSED 2026-09-26 — struck by TP-458 after walk 4 (2026-09-26, the Windows host; record on the private archive's orphan branch `walk4/windows-2026-09-26`, digest `walk4/WINDOWS_WALK4_RECORD.md`, folded into `WINDOWS_FUSE_NOTES.md` `# ★ WALK 4` with its filing manifest) discharged the six owed legs: the `DEF-11` tracked-settings case (PASS on pip plus `init --wire-hooks`); leg 1-I (FALSIFIED, blank under PowerShell without Git Bash, replaced by `DEF-929`); the 3.12+ `onexc` arm (PASS on 3.12, 3.13 and 3.14; the CI witness it now permits is `DEF-934`); `DEF-756`'s exclusion (not exercisable on self-host by design, since every plan writer rebuilds agents from the files on disk, and PASS on a consumer tree with a conditional-agent surface, the corrected description); the PowerShell guard matrix under a paren-bearing root (263 of 264 per shape, 0 MISMATCH, the one non-ok the declared `KNOWN_GAP`); the walk-2 absolute-path re-read (nothing falsified; the premise was wrong: 53 of 55 live guard calls ran under an unspaced root). The two carries no leg discharged are re-homed: the dirty-machine install fixture is `DEF-937`, and the walk-1 overclaim warning (fourteen enumerated places; the `doctor` em-dash item downgraded) is written in full into `memory/windows-walk-output-routing.md`, which is the pointer to where every walk's output lives and whose `Linked from` line no longer names this row. Walk 2's original 94 rehearsal rows are unrecoverable (the host overwrote `bench/rehearsal-results.json` on 2026-09-14): recorded, not owed.** PRIOR TEXT: ⚠ Where the walks' output lives (the two ignored files, the read order, the `record` ref): `memory/windows-walk-output-routing.md`. **PARTIALLY DISCHARGED 2026-08-18 -- the first Windows adopter-lifecycle round in the project's history was DRIVEN by hand** (Windows 11 / py3.11 / PowerShell, both repo paths containing spaces; the workaround for the `DEF-582` Actions outage). **CLOSED legs:** `fuse` end-to-end incl. paths with spaces (234 host files, exact `git ls-files` match); a valid Windows settings.json (all 10 hook events, exec form, `_detect_python_command` correctly wrote `python`); and **hooks actually firing in a live CC session** -- every documented in-scope vector denied on real NTFS, including the load-bearing `disableAllHooks` self-disable and `_fs_equiv` case/trailing-dot folding. **STILL OWED:** `fuse`/`init` over a repo that ALREADY tracks `.claude/settings.json` (the `DEF-11` case, where the gitignore foreclosure is withheld by design and CI becomes the primary gate); `espalier init .` in place on Windows; a second checkout of a fused repo (to fire or refute the integrity CRLF prediction); and `espalier upgrade` on Windows. Raw notes + an 8-lane verification pass in `WINDOWS_FUSE_NOTES.md` (untracked); fixes scoped in a landed 2026-08 pack. ⚠ The walk's own findings section overclaims in 14 enumerated places -- read the `# VERIFICATION PASS` appendix, not the findings, and note its `doctor` em-dash item was itself downgraded from "Proven" to mechanism-confirmed-not-driven. ⚠ The meta-finding is NOT Windows: five of the thirteen findings are platform-independent and surfaced only because this was the first install driven on a **dirty machine** (prior espalier on PATH, `master` default branch, pre-existing `.claude/`, spaces everywhere, an operator who pastes verbatim). A dirty-machine install fixture is the CI-shaped generalisation and does not exist. **WALK 2 (2026-09-08/09) and WALK 3 (2026-09-14) DISCHARGED FURTHER LEGS:** `espalier init .` in place on Windows (walk 2); `upgrade` on a drifted tree and on a fresh fusion, `doctor`/`audit`/`upgrade` under an ACL-denied `.claude`, the CRLF second checkout against a genuinely-CRLF file built by a git round-trip (the integrity prediction settled by `DEF-725`'s fold), both Stop gates blocking in sequence through the real write counter, the uninstall accounting against a filesystem walk, the Python 2 shim through a real `.bat`, the Windows statusline shim end to end, and the guard rows on both tools in a clean-room repo and a spaced one (walk 3, all legs 0-5; record at `WINDOWS_FUSE_NOTES.md` `# ★ WALK 3` and its filing manifest; instrument mirrored as `WALK3_RUN_SHEET.md`, `WALK3_BRIEFING.md`, `WALK3_PREFLIGHT_FINDINGS.md`). **STILL OWED after walk 3:** the `DEF-11` tracked-settings case; leg 1-I (the statusline shim under PowerShell without Git Bash); the 3.12+ `onexc` arm of the read-only-delete helper on Windows (only the pre-3.12 arm was witnessed); `DEF-756`'s exclusion on the self-host clone; the PowerShell guard matrix under a paren-bearing root; and a re-read of walk 2's absolute-path ALLOWs under the spaced-root condition walk 3 found. **WALK 4 (2026-09-26, the Windows host) DISCHARGED every owed leg above** (`DEF-11` on pip + `init --wire-hooks`; the 3.12+ `onexc` arm on 3.12/3.13/3.14; the paren-root guard matrix, 0 MISMATCH; the walk-2 re-read, premise refuted; `DEF-756` driven on a consumer substitute) and FALSIFIED leg 1-I (blank under PowerShell without Git Bash); the twins were witnessed by a single-variable control. Its record is an orphan branch on the private archive, `walk4/windows-2026-09-26`; the fold, the nine new candidates and this row's fate are drafted as `TP-458` (`task-packs/TP-458-fold-windows-walk-4-into-the-ledger.md`). |
| `DEF-312a` `LG-16` | `tests/test_post_compact_capture.py` | A live post-compaction re-injection observation is still owed; its calibration (a secondary limb, 17 existing tests) is accurate. |
| `BS-1` | `.github/workflows/test.yml:6` | No one has ever forked the repo and opened a PR to see what a newcomer's first check run actually does. |
| ~~`DEF-12`~~ | `tools/cc/hooks/_hook_utils.py::normalize_path` | ✅ **CLOSED 2026-09-26 — re-keyed to `DEF-935` (§C0, major, ADOPTER) by TP-458: walk 4 measured the mechanism on the Windows host on 2026-09-26 (nine of eleven UNC and `\\?\` spellings pass every hook and reach the file; the chokepoint shape reproduced on this host), so the row is no longer unverifiable and left §5 for a measured member row with a fix shape, under the operator's 2026-09-26 reading of the spellings as a mistake scenario, not an evasion (`CLO-46` stays declined and now points at `DEF-935`); Appendix A4 carries the crosswalk.** PRIOR TEXT: UNC and `\\?\` device-path prefixes may defeat the protected-zone check; unverifiable on Darwin. |
| `INV-25` | `docs/AUTONOMOUS_EXECUTION.md:260` | Three `claude -p` driver behaviors remain unverified: Stop-event firing, the fabricated-blocker halt end-to-end, and whether permission-mode auto + budget cap bound every stall surface. |

---

## §6 — Dropped / do-not-rediscover

**These rows exist to stop a future review paying to re-find a settled call.** Deleting one causes
the rediscovery it prevents. Every premise below was re-derived at HEAD this rebuild and still holds.

| id | what | why it stays declined |
|---|---|---|
| `DEF-412f` | espalier/cli.py imports ~28 submodules at module top so --version/status/audit pay for all of them. | DEF-412f at :1879-1891 (§3.8), status `parked (measured, deliberately not built)` — 'Recorded with the number so a fourth efficiency lens stops re-finding it'; not on a hot path, sub-25ms realizable win. This lane is the fourth. Re-measured anyway: `python3 -X importtime -c 'import espalier.cli'` x3 -> 48.3-49.4ms vs the ledger's recorded 45.7-46.0ms (same order, drifted up); AST count 29 module-level espalier imports vs the ledger's '~12'. The decline still holds on its own reasoning; only the recorded number wants a refresh if anyone touches the row. |
| `CLO-17` | Tier-0 (hookless distribution) — scrapped out-of-band, kept in §6 so it is not rediscovered a fourth time. | §6 by construction: task-packs/FORWARD_LEDGER.md:2093-2102, status `scrapped (decided out-of-band)`, with a named reopen trigger (post-launch funnel evidence of hook-friction drop-off) and a DEC-21 cross-reference. This is the THIRD orphaning of the same idea — the row exists to stop a fourth. Footnote (b) still holds: espalier/settings_profiles.py's hooks-are-profile-independent rule means Tier-0 cannot be a 5th profile. |
| `CLO-18` `DEC-22` | The 26 unreferenced CHANGELOG link definitions: a settled keep-decision, not an open defect. | Recorded twice by design: §5 DEC-22 at :2081-2087 ('settled 2026-08-05, recorded as CLO-18') and §6 CLO-18 at :2105-2109 ('keep — decided 2026-08-05'). Rationale re-verified sound: 28 link definitions parsed, 26 unreferenced, and Markdown silently drops unreferenced link-defs, so reader-visible impact is zero. This is the third raise. |
| `CLO-19` | CLO-19: a tests-wide 'no exact-count pin' contract -- declined as partly self-defeating, and the rationale still holds | §6 CLO-19 at :2110-2117, `declined.` as partly self-defeating. Rationale re-verified at HEAD: tests/test_release_check.py:142 `assert len(results) == 22` still exists and is regex-sourced as a numeric SoT by tests/test_documented_claims.py:1128 and referenced by tests/test_freshness_migrations.py:337/377. A tests-wide ban would have to carve out the very literal another contract requires. |
| `CLO-24` | The 'optional positive scrub test' for adopter-fit narration was struck as not-buildable-as-worded, with the mechanizable negative axis already shipping in two contracts. | §6 CLO-24 at :2135, `struck 2026-08-05`. Both named negative-axis backstops exist at HEAD: tests/test_init_tier_split.py:121 TestCommonTierAssetHygiene and tests/test_common_tier_asset_availability.py. espalier/scanners/retired_vocab.py:122 RETIRED_TERMS holds only severity labels, confirming the scanner could never have surfaced the stale 'common-tier' wording. |
| `DEF-308a` | DEF-308a: the mechanical half of the auto-memory pointer-row audit is done and null; the residual 'pointer names a file holding a different lesson' axis was measured as un-mechanizable and the sweep declined. | Ledger :755-762 marks DEF-308a 'idea-only (measurement recorded; sweep declined)'. The load-bearing number verified in-source: tools/cc/memory_sort_audit.py:16-21 docstring reads 'measured against the 39 auto entries already collapsed to pointers ... the slug matcher alone re-identifies 10 of 39 (~26%) ... and no filename heuristic closes that.' Recorded so a future sweep inherits the null rather than re-opening it as unknown-base-rate. |
| `CLO-16` | Promoting a 2026-07 pack's pack-id-reuse observation to docs/SHARP_EDGES.md was declined at n=1 and stayed declined | §6 CLO-16 at :2145-2150, `declined 2026-08-04` at n=1 (canonizing would INVENT a convention rather than document one). Re-derived: `grep -rn -i 'pack.id.reuse\|pack id reuse\|reusing a pack id' docs/` -> zero hits, so the declined promotion was not quietly re-landed. |
| `CLO-14` | CLO-14: tree-wide PROVENANCE_RE widening for internal review-round vocabulary -- deliberately dropped in ledger sec6. | §6 CLO-14 at :2182, DROPPED as colliding with standing canon (memory/craft-surface-is-not-converged-unlike-correctness.md, 'false positives outrank leak-closing on a toolbelt' = STANDING_PRINCIPLES §2, the project frame governing this consolidation). Only the narrow bench-scoped hygiene arm survives, tracked as DEF-410k(c). |
| `EA-2` `CLO-15` | CLO-15: the 25 remaining tools/cc non-UTF-8 read sites were deliberately dropped after the motivating blast-radius claim inverted. | §6 CLO-15 at :2183. Load-bearing premise spot-checked at HEAD: `grep -rln 'except BaseException' tools/cc/hooks/*.py` -> 14 files carry the top-level crash guard, so a UnicodeDecodeError degrades to one bounded stderr line rather than a traceback. Boundary the lane drew correctly: this drops the tools/cc/ half only; the _integrity.py site (L12-scripts-assets-2/integrity-manifest-decode-error-escapes) is separately open because its consumer is espalier/doctor.py, which has NO umbrella. |
| `DEF-10` | DEF-10: the mechanical confirm_test_failure.py escape hatch was cut and its lesson folded into the untrusted-oracle doctrine. | DEF-10, `dropped-but-deferred` (an earlier pack was cut). `find . -name 'confirm_test_failure*' -not -path './.git/*'` -> 0 results tree-wide, consistent with the row. Its lesson was folded into the untrusted-oracle doctrine (CLAUDE.md Core Rule 8); no evidence at HEAD that the instruction layer proved insufficient. |
| `CLO-22` | The folder-guide fill of a 2026-06 pack was deliberately dropped and is recorded so the next sweep stops rediscovering it. | §6 CLO-22 at :2131-2133, `dropped.` — 'Recorded so the next sweep stops paying to rediscover a settled call.' The row is functioning as intended. Its live remainder is correctly tracked elsewhere as DEF-279a (:780), which is a separate issue-set entry (L12-scripts-assets-2/wave2-folder-guides-build-or-decline), so no rediscovery occurred here. |
| `CLO-13` | CLO-13's borrows from a 2026-07 pack: U3 scrapped clean and verified absent, U4b/U4c parked with named reopen triggers, U4d/U4e scope-gated. | §6 CLO-13 at :2173-2179. U3's load-bearing claim re-derived: `grep -rn 'uncontested' --include=*.md --include=*.py .` -> exactly 2 hits, both test names in tests/test_fan_out_findings.py about survival_rate, unrelated sense — zero occurrences in any doc, README or shipped asset. U3 confirmed dead. NOTE: U4b/U4c are PARKED with explicit conditional reopen triggers ('if the Stop-gate grows / the write_guard tokenizer is next touched'); neither has fired, and this row is their only reader — do not drain it. |
| `CLO-20` | `_extract_pins_slug` still scans 10 lines above then 10 below with no block-boundary stop -- the asymmetry a 2026-07 pack fixed in its sibling and deliberately declined here on a measured zero-defect basis. | §6 CLO-20 at :2118-2126, `declined — measured, zero live defects` (18 pin-binding declarations, 6 heuristic flags, 0 mis-binds). Code construct verified present at espalier/scanners/canon_verifier.py:660-686 exactly as described, and the containment argument reads at HEAD: is_stub comes from the annotation's own regex group, so the worst case is a duplicate bind of the same (slug, is_stub) pair, never a false PINNED verdict. Reopen trigger ('a real mis-bind observed') has not fired. |
| `EXP-2` `INV-19` | EXP-2's orientation-lever disconfirmation and its INV-19 VOLUME residual are closed verdicts with no owed build. | 749a70e 'docs(memory): cheap orientation levers DISCONFIRMED -- double null at normal scale' is real and reachable at HEAD; memory/orientation-lever-experiment.md:69 carries the measurement (5/5 every arm, both effects 0.00, 0% re-litigation). `grep -rn 'INV-19' task-packs/ memory/ docs/` -> 2 hits, both inside FORWARD_LEDGER.md — nothing is waiting on it. Self-described as 'shelved as a cost-amplifier (1M/session unaffordable). Honest residual, not a planned build.' |
| `CLO-1` `CLO-10` `CLO-11` `CLO-12` `CLO-2` `CLO-21` `CLO-23` `CLO-4` `CLO-5` `CLO-6` `CLO-9` `DEC-3` | Eleven §6 rows are explicit prior declines whose premises still hold at HEAD; none is open work and each exists to stop a re-raise. | Eleven §6 rows (CLO-1/2/4/5/6/9/10/11/12/21/23) whose premises were each re-derived at HEAD and all still hold. Spot-checks: CLO-1's cross-ref resolves to DEF-5 at :1691; CLO-2's PostToolBatch is a real CC event (docs/external/cc-hook-protocol.md:145,190) wired by nothing — `grep -rn 'PostToolBatch' espalier/settings_profiles.py espalier/assets/claude/` -> zero hook wiring; CLO-4's `espalier onboard` was never built (no add_parser('onboard') among ~30 subcommands). Zero of the eleven falsified. Only cosmetic wobble: CLO-6's 'Contradicts DEC-3' points at an id with no §5 body (traceable via the documented relocation). |
| `CLO-25` | `espalier/cli.py` is itself the largest file in the tree (11,060 lines at HEAD against the god-file scanner's 750-line heuristic) and the scanner does not enforce against its own front-end. | Refuted 2026-07-16 (the self-hosting register-bleed pass; record branch commit `b3e36ae`, findings corpus entry 418) and kept declined at the 2026-09-21 corpus fold: the god-file scanner is advisory by design, a large CLI front-end in a CLI tool is in place, and docs/CONVENTIONS.md records the decomposition as a deferred decision; `DEF-412f` above parks the import-time half with its number. Re-derived 2026-09-21: `wc -l espalier/cli.py` reads 11,060 and no adopter-facing effect is named. Reopen only with a measured cost to an adopter, never with a line count. |
| `CLO-26` | The adversarial benchmark, its per-PR CI and the guard apparatus outweigh the engine several-fold for a tool that disclaims being a security boundary. | Refuted 2026-07-16 (the self-hosting register-bleed pass; record branch commit `b3e36ae`, findings corpus entry 419) and kept at the 2026-09-21 fold: the verification mass is the product thesis (STANDING_PRINCIPLES §1, make it prove it) and the README's "regression corpus, not a proof of safety" framing is the calibrated claim, not a retreat. A size ratio names no user; recorded so a fourth proportion lens stops paying to re-find it. |
| `CLO-27` | `.claude/settings.json` is gitignored, so a second clone looks governed but runs no hooks until `espalier init` runs there. | Refuted 2026-07-16 (the self-hosting register-bleed pass; record branch commit `b3e36ae`, findings corpus entry 420) and kept at the 2026-09-21 fold: the gitignore is forced (the file records a machine-detected interpreter name; committing it breaks every other machine, the same shape as Claude Code's own settings.local.json), the source-checkout state is nudged by code (`espalier/cli.py::_maybe_nudge_source_checkout`, present at HEAD, plus doctor's source-checkout detection), and the distribution model is `espalier init` per clone. The one real exception, a repo that already tracks the file, is the documented DEF-11 path in CLAUDE.md. Reopen only with an adopter who ran `init` and still had no hooks. |
| `CLO-28` | The README demo runs `python scripts/release_check.py`, a maintainer script an adopter's own repo never carries. | Refuted 2026-07-16 (the self-hosting register-bleed pass; record branch commit `b3e36ae`, findings corpus entry 422) and kept at the 2026-09-21 fold: both demos document their run context as the espalier-harness clone (README's "Try it" block does `cd espalier-harness`; DEMO.md's setup clones it), where the script exists and runs (README:98 at HEAD). The fused-adopter scenario the finding assumed is one the docs never route into. Residual is a one-line label nit, not a 404. |
| `CLO-29` | `espalier/managed_paths.py::managed_paths_for_repo` is a supplanted, deletable dead seam. | Refuted twice (the second and third passes of the supplanted-infrastructure cleanup, 2026-07-16; record branch commit `b3e36ae`, findings corpus entry 458) and kept at the 2026-09-21 fold: a tested public contract seam (tests/test_managed_paths.py, tests/test_contract_consumers.py) whose single-list return cannot express the report-versus-drift two-view split that doctor and ownership_summary need; defined and tested at HEAD. Reopen only with a genuinely unused two-view consumer. |
| `CLO-30` | `tools/cc/hooks/_speedbump.py::check_fired` runs its one-shot flag probe, its cap consume and its flag write as three statements under no single lock, so two concurrent tool calls on the same checkpoint can each burn a session-cap slot. | Declined 2026-09-21 at the corpus fold (entry 51; mechanism confirmed by an Opus critic at HEAD). The harm is a session cap consumed faster under a concurrent fan-out, which is friction on a toolbelt (STANDING_PRINCIPLES §2), never a wrong deny and never a missed wall; the cap consume itself is flock-atomic and the flag write is idempotent. Reopen with a measured double-fire that changed a verdict. |
| `CLO-31` | `tools/cc/check_ledger_probes.py::run_probe` executes each probe's argv from the gitignored probe file with no read-only allowlist, so the docstring's read-only contract is enforced nowhere in code. | Declined 2026-09-21 at the corpus fold (entry 309; mechanism confirmed at HEAD). The author of a probe and the only person its side effect could hurt are the same maintainer on the same checkout; the argv runs with no shell; the file lives on the record branch and every probe is driven at filing by the verb that writes it. An allowlist adds friction for no second person. Reopen if a probe ever mutates the tree. |
| `CLO-32` | `espalier/analyze.py::fingerprint_repo` walks the tree four times, `espalier/strengthen.py::build_strengthen_report` parses every module twice, and `espalier/cli.py::cmd_scan` counts pragmas it then collects. | Declined 2026-09-21 at the corpus fold (entries 622, 699 and 618; the first two confirmed, the third refuted by its critic on STANDING_PRINCIPLES §16). Direction without magnitude: the four walks measured 0.16 s against 0.03 s for one on this tree, the double parse is sub-second, and no user has named a wait. The scanner-side cache is `TP-360`'s live §4 row. Reopen with a measured wait on an adopter tree, which would move it into TP-360, not into a new row. |
| `CLO-33` | `espalier/models.py::RepoFingerprint.from_dict` raises on an unknown key while `CognitiveBlueprint.from_dict` drops one. | Declined 2026-09-21 at the corpus fold's second pass (entry 424, re-derived at HEAD): the asymmetry is real and the constructor has no production caller; every reader of reports/repo_fingerprint.json consumes the parsed dict directly, so no newer-schema file ever reaches it. Reopen when `grep -rn "RepoFingerprint.from_dict" espalier/` finds a caller outside the class. |
| `CLO-34` | `tests/test_audit_accuracy.py::_scaffold_repo`'s five default counts are stale against the live surface while its docstring says they track it. | Declined twice 2026-09-21 (entries 426 and 433, both on STANDING_PRINCIPLES §16): the fixture is module-private, every count-sensitive test passes explicit values, the bare-default call sites need only the repo shape, and the file is 50 passed at HEAD. A stale docstring sentence, not a failure; correct the sentence when the file is next touched. Reopen only if a test starts asserting against a bare default. |
| `CLO-35` | `tools/cc/hooks/subagent_stop.py` returns under maintenance mode before reading stdin. | Declined (entry 430): the early return is the designed twin of stop_gate's Gates 2 and 3 bypass, the adjoining comment says so, and CLAUDE.md's maintenance-mode table lists it. Reopen only if the hook grows a reporter duty that must run under maintenance mode. |
| `CLO-36` | `tests/test_scanner_prints.py`'s fixture test asserts at least three findings over a fixture of exactly three shapes. | Declined (entry 434): scan_file is scoped to the one fixture file with three distinct shapes, so a scanner that dropped a shape yields two and reds; the bound misses only over-counting, which the claim never alleged. Reopen with an over-count failure mode. |
| `CLO-37` | `tests/test_hooks.py`'s MCP plan-guard test invokes the hook script directly, "bypassing" a dispatcher. | Declined (entry 439): there is no dispatcher; the settings emitter in espalier/cli.py wires PreToolUse to the same script path the test's run_hook invokes as a subprocess. Reopen only if a dispatch layer is added between settings and the scripts. |
| `CLO-38` | `tools/cc/cognitive_blueprint.py` checks `is_symlink()` before reading latest.json, which a swap between check and read defeats. | Declined (entry 440): the swap needs an actor with write access to the repo, outside the toolbelt threat model (STANDING_PRINCIPLES §2); the check exists for the mistake case, a stray or hand-made symlink, which it handles. The same scope call as CLO-46. |
| `CLO-39` | The benchmark gates no ReDoS timing property; its only ReDoS class is out of scope. | Declined (entry 442): the corpus entry's own description says the block/allow verifier cannot represent a linear-time property and names tests/test_redos.py as the timing gate, which exists at HEAD. Re-finding this takes re-reading the file that states its rationale. |
| `CLO-40` | `plan_guard._is_exempt` returns True for an absolute path, extending the env-var doubled-separator class to a new consumer. | Declined (entry 444): the check runs on a path already through the shared `_hook_utils.normalize_path` chokepoint, which strips the doubled-separator residual, so the class cannot reach it (driven: such an input normalizes relative); the absolute-path exemption itself is intentional, tested design for out-of-repo writes. Reopen only if plan_guard stops sharing write_guard's normalizer. |
| `CLO-41` | The resolve fallback in `_hook_utils` returns an uncollapsed traversal string on an OS-level failure. | Declined (entry 445): the fallback is reachable only on the failure (a symlink loop) that also makes the literal path fail when the write is attempted; driven with a self-referencing loop, open() on the same path raised rather than wrote. Reopen with a fallback input that a write API accepts. |
| `CLO-42` | An embedded NUL byte in a path defeats the guard's resolution. | Declined (entry 446): no filesystem write API accepts a NUL byte in a path (Python raises ValueError before any syscall; Node's fs likewise), so the spelling can never reach a guarded write. Driven. |
| `CLO-43` | The closed `MCP_PATH_FIELDS` set has no completeness pin. | Declined (entry 447): the closed set is an intentional, tested trade-off (tests/test_hooks.py::test_nested_mcp_non_path_key_does_not_require_plan pins that plan_guard must not fire on a non-canonical key) and write_guard's key-agnostic leaf walk is the backstop for the protected-zone check. Reopen only with a canonical path key the set misses. |
| `CLO-44` | `session_resume._manifest_missing_docs` reads the pack manifest without a symlink guard. | Declined (entry 449): a committed local manifest read under the toolbelt frame (STANDING_PRINCIPLES §2); a dangling symlink reads as absent and returns an empty list, and a symlink to a directory is a self-inflicted local footgun. No person is hurt. |
| `CLO-45` | `espalier/cognitive_blueprint.py::add_action_justification` does a read-modify-write with no lock. | Declined (entry 450): the library function has no runtime caller; execution_plan.py records justifications through the locked tools/cc CLI path (cmd_justify), and only its own test exercises it. Reopen when `grep -rln add_action_justification` finds a caller. |
| `CLO-46` | A DOS 8.3 short name evades the protected-zone deny on Windows. | Declined (entry 451): an evasion technique, not a mistake scenario, outside the guard's threat model (STANDING_PRINCIPLES §2); the Windows path-equivalence residuals that ARE tracked sit under `DEF-935` in §C0 (re-keyed 2026-09-26 from `DEF-12` when walk 4 measured them on the host). Reopen only if the model changes. |
| `CLO-47` | write_guard's MCP branch path-checks every MCP tool while plan_guard's MCP branch verb-gates. | Declined (entry 453): write_guard skips verb-gating deliberately because an arbitrary MCP tool name cannot be classified read-versus-write, and plan_guard's verb-gated branch is documented dead code at runtime (the hook matches Write, Edit and NotebookEdit only). Both are stated in the code beside the branches. |

⚠ **`s6-do-not-rediscover-register` collapses 11 distinct `CLO-*` declines** (CLO-1/2/4/5/6/9/10/11/
12/21/23) into one row. A critic flagged this: the ids are the recall handle and should be carried
individually. Named here so they are not lost.

---

## Appendix A — drafted packs held in `Deferred/`

_Every pack in `task-packs/Deferred/` must be named here — a pack nobody tracks is work that_
_silently leaves the plan. Pinned by `test_every_active_pack_is_ledger_tracked`._

| pack | status |
|---|---|
| `TP-203a` — learning loop finding ledger | drafted-pack (deferred) |
| `TP-203b` — effect measurement false fire counter | drafted-pack (deferred) |
| `TP-233b` — strengthen suggest | drafted-pack (deferred) |
| `TP-248` — multiagent worktree isolation | superseded by `TP-467` (2026-10-05) |
| `TP-258` — self learning injection backbone | drafted-pack (deferred) |
| `TP-259` — goal anchor opportunistic scope | drafted-pack (deferred) |
| `TP-260` — goal anchor plan scope divergence | drafted-pack (deferred) |
| `TP-261` — footgun memory surface | drafted-pack (deferred) |
| `TP-321d` — hook profiler | drafted-pack (deferred) |
| `TP-333` — adversarial probe harness poc | drafted-pack (deferred) |
| `TP-338` — ci guard post approval forcepush window | drafted-pack (deferred) |
| `TP-342` — mine userpromptexpansion setup events | drafted-pack (deferred) |
| `TP-355` — scanner detector v2 hardening | drafted-pack (deferred) |
| `TP-356` — selfhost tooling correctness deadcode | drafted-pack (deferred) |
| `TP-357` — selfhost driver devtool features | drafted-pack (deferred) |
| `TP-358` — bench testability engine test debt | drafted-pack (deferred) |
| `TP-359` — least attacked subsystem review | drafted-pack (deferred) |
| `TP-360` — performance levers | drafted-pack (deferred) |
| `TP-361` — new dev tooling | drafted-pack (deferred) |
| `TP-362` — recall and surface fixes | drafted-pack (deferred) |

---

## Appendix A2 — crosswalk from the retired section numbers

The old `§2.x` / `§3.x` numbers are **retired, not reused**, so an archival citation in a `Done/`
pack fails to resolve rather than silently resolving to a different topic. 70 of the 75 section
citations in `task-packs/` are in `Done/` (records of landed work); one live pack — `TP-355` — cites
`§2.2`/`§2.15`, and should be re-pointed when it is next opened.

| retired | was | now |
|---|---|---|
| `§2.1` | Pack-chain driver fail-open residuals | §C-by-member — see Appendix B |
| `§2.2` | Test-honesty scanner coverage completion | §C7 / §C5 |
| `§2.3` | Read-robustness / encoding | §C23 |
| `§2.4` | `pack_manifest` parser robustness | §C17 |
| `§2.5` | Citation-rot / doc-drift | §C4 |
| `§2.6` | Folder-router coverage | §C6 |
| `§2.7` | Fusion / deploy seam | §C22 |
| `§2.8` | CLI-surface coherence | §C0 / §C13 |
| `§2.10` | Review-gate completeness | §C15 |
| `§2.11` | Recurrence guards / trigger-gated-defect prevention | §C5 |
| `§2.12` | Un-swept convergence surfaces | §C15 |
| `§2.13` | Smaller single fixes & at-cut doc hygiene | distributed across §C1–§C25 |
| `§2.14` | Enumeration-integrity follow-ons | §C1 |
| `§2.15` | Sister-site probe reach | §C1 / §C9 |
| `§3.1–§3.10` | features, recall engine, hook-surface, measurement | §3 (flat) |
| `§4 (old)` | Experiments & spikes (verdicts recorded) | folded into §3 / §4 |
| `§5 (old)` | Open decisions with revisit triggers | **now §4** — the number was REUSED |
| `§6 (old)` | Dropped / do-not-rediscover | §6 (unchanged) |

## Appendix A3 — retired ids (no row; recorded so a citation does not dead-end)

_These ids appear in `task-packs/` citations but had **no row** in the pre-rebuild ledger either —_
_they were prose-only, or explicitly removed as moot. Recorded so a reader following a pack citation_
_learns that, instead of finding nothing. Not open work._

| id | disposition |
|---|---|
| `DEC-8` | prose-only by the old ledger's own admission (cited but has no row) |
| `DEC-1, DEC-2, DEC-3` | relocated and removed 2026-07-31 |
| `PR-1` | removed as moot — a 2026-07 pack relocated the freshness cache off the tracked tree |
| `INV-28` | landed 2026-07 (scanner nested-repo parity) |
| `INV-18, INV-22, CONV-1` | named in a 2026-07-28 goalie-sweep draft list; never became rows |
| `DEF-327a–e` | closed with the 2026-07 memory-migration cohort (two landed packs) |
| `DEF-14, DEF-353a, DEF-398a, CLO-3, DEC-11, DEC-18, DEC-19, DEC-20` | prose-only cross-references |
| `DEF-484` | **closed** — the cap is now bound by POPULATION per file (`tests/_surface_expected.py::EXPECTED_MEMORY_CAP_SITES` + `tests/test_documented_claims.py::TestMemoryCapPopulation`), whose census derives every tracked `.md` stating the value from `git ls-files`. Driven 2026-08-09: 10 census rows, 9 documented exclusions, 24 assertions green. |
| `DEF-314a` | **closed** — `tests/test_folder_claude_md_routers.py::_discover_routers` derives `EXPECTED_ROUTERS` from `git ls-files` minus `_NOT_ROUTERS`, and `::test_router_population_is_the_whole_tracked_tree` IS the discovery test this row said was absent. Driven 2026-08-09: 10 routers enrolled, 52 assertions green. |
| `DEF-399a` | **closed on its premise** — `espalier/fuse.py::_require_source_checkout` refuses a fusion under a wheel install, so the assets/wheel comparison this row asks for would assert something the design deliberately makes false. Driven 2026-08-09: `missing_source_entries(REPO_ROOT)` returns `[]`. |
| `DEF-373b` | **closed** — Mode 3 was built: `tests/test_catalog_self_consistency.py::_BARE_LINE_ANCHOR_RE` + `::_check_bare_line_anchors_resolve` + `::test_tree_wide_bare_line_anchors_resolve`, with a `_MIN_BARE_ANCHORS` collapse floor. Driven 2026-08-09. Residue (three stated blind spots) transplanted to `DEF-392d`. |

_The suite cannot catch a dropped id of this shape: `_dangling_id_references` in_
_`tests/test_forward_ledger_completeness.py` matches TP- ids only, so every DEF-/DEC-/INV-/CLO-/PR-/CONV-_
_id is outside its population._

---

## Appendix A4 — re-keyed ids (the citation resolves to a DIFFERENT row, not to nothing)

_Two ids were each assigned to **two** substantive rows. Appendix A2 already states the rule for
section numbers — *"retired, **not reused**, so an archival citation fails to resolve rather than
silently resolving to a different topic"* — and ids were simply never held to it. They are now._

_Resolution rule: **the first claimant by discovery date keeps the id**; the later row is re-keyed.
Recorded here because these citations are worse than dead — they resolve, to the wrong row._

_**Records were left untouched; live pointers were updated.** `ESPALIER_MEMORY.md`, the session
blueprints and the compaction summaries under `cc/blueprints/` are append-only records of what a
session actually did, and editing one to satisfy a checker falsifies the thing it exists to preserve.
The two always-current pointers — `cc/GOAL.md` and `cc/_working_summary.md` — WERE updated; root
`CLAUDE.md` draws exactly that line, calling the working summary "always-current" and the compaction
archive "the after-the-fact record". ⚠ The single home for which surfaces are records is
`espalier.claim_extractor.RECORD_SURFACES` (mechanically reconciled by
`tests/test_record_axis_reconciliation.py`) — **not**
`tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS`, which root `CLAUDE.md` Core Rule 13
currently names as "the declared set". That set is narrower and different-purpose: it omits
`ESPALIER_MEMORY.md`, which `_swept_docs` actively includes, so following Core Rule 13 literally
returns the WRONG answer here. Re-pointing Core Rule 13 is owed._

| citation as written | what it meant | reads today |
|---|---|---|
| `DEF-583` (§C14) — `ESPALIER_MEMORY.md:43`, the 08-16 blueprint, `cc/GOAL.md`, `cc/_working_summary.md` | maintenance mode / `tools/cc/hooks/subagent_stop.py::_changed_markdown` | **`DEF-584`** |
| `DEF-583` (§C2) | commit-trailer identity, `memory/task-packs.md:176` | unchanged — first claimant, measured 2026-08-15 |
| `DEF-556` (§C17) — `ESPALIER_MEMORY.md:50`, `cc/blueprints/compact_summaries/25df37a0-*.md` | scalar-collapse false green, `tests/_json_key_paths.py` | **`DEF-585`** |
| `DEF-556` (§C0) | `_PACKAGED_ROOT_DOCS` / `README.md`, found 2026-08-12 | unchanged — first claimant |
| `DEF-703` (§C33) -- folded 2026-09-20 in the third rebuild | its substance is carried by the owning row | **`DEF-653`** |
| `DEF-666` (§C46) -- folded 2026-09-20 in the third rebuild | its substance is carried by the owning row | **`DEF-706`** |
| `INV-26` (§3) -- folded 2026-09-20 at TP-452 1-C | its substance is carried by the owning row (the strike critic's ten zero-trace files and the null caveat; the critic overturned the extra lane's strike, the operator chose the fold) | **`SUP-2`** |
| `DEF-12` (§5) -- re-keyed 2026-09-26 at TP-458 2-A; the one live pointer, `CLO-46` (§6), updated on the id and the section; `ESPALIER_MEMORY.md`'s 2026-09-26 rows are a record and stay as written | UNC and `\\?\` device-path prefixes defeat the protected-zone check, unverifiable on Darwin until walk 4 measured nine of eleven spellings reaching the file on the Windows host | **`DEF-935`** |

_Removed as landed (2026-09-20): four rows keyed by a landed pack's own id were re-keyed at the third rebuild's cut, because the pack is not shipped and the residue it left is -- TP-320 via DEF-865, TP-327 via DEF-866, TP-332 via DEF-864, TP-336 via DEF-867._

⚠ **The collision cost the §C0 row its index entry.** Appendix B is keyed by id, so it could hold
only one of the two `DEF-556` rows: it listed §C17 (the *later* find) and silently dropped §C0 —
which is why §C0 declared 26 members against 25 indexed. Re-keying restored it. A count contract
cannot see this: a duplicate id does not change a row count, so §C14 read 5 rows / 5 declared while
carrying two rows under one key.

---

## Appendix A5 — crosswalk from the pre-rebuild §C numbers

_The 2026-08-20 rebuild re-cut classes by unit of work, so the old §C numbers do not
map one-to-one. **Cite the id, never the section number** (contract rule 3)._

| pre-rebuild § | its rows now live in |
|---|---|
| §C0 | §C0, §C6, §C8, §C9, §C14, §C18, §C21, §C26, §C35, §C36, §C37, §C39, §C41, §C47 |
| §C1 | §C0, §C11, §C12, §C15, §C16, §C19, §C25, §C27, §C30, §C31, §C33, §C34, §C37, §C38, §C47 |
| §C2 | §C0, §C2, §C20, §C35, §C39, §C41, §C47 |
| §C3 | §C0, §C12, §C13, §C24, §C28, §C29, §C42, §C47 |
| §C4 | §C0, §C18, §C31, §C32, §C33, §C39, §C45, §C47 |
| §C5 | §C2, §C9, §C10, §C14, §C23, §C24, §C26, §C32, §C36, §C39, §C47 |
| §C6 | §C0, §C47 |
| §C7 | §C7, §C10, §C13, §C15, §C32, §C47 |
| §C8 | §C2, §C47 |
| §C9 | §C0, §C3, §C4, §C5 |
| §C10 | §C25, §C27, §C30, §C34, §C47 |
| §C11 | §C0, §C17, §C32, §C46, §C47 |
| §C12 | §C11, §C16, §C19, §C29, §C47 |
| §C13 | §C0, §C8, §C13, §C43, §C47 |
| §C14 | §C0, §C46, §C47 |
| §C15 | §C0, §C6, §C7, §C47 |
| §C16 | §C1, §C47 |
| §C17 | §C21, §C36, §C47 |
| §C18 | §C0, §C32, §C36, §C38, §C47 |
| §C19 | §C10, §C12, §C47 |
| §C20 | §C22 |
| §C21 | §C47 |
| §C22 | §C47 |
| §C23 | §C47 |
| §C24 | §C0, §C44 |
| §C25 | §C40 |


_Retired 2026-09-20 at the third rebuild's cut -- every row of each had closed, the number is not reused, and a citation of one resolves here and nowhere else (cite the id):_

| retired § | its unit of work |
|---|---|
| §C3 | Introduce a deny-once speed-bump tier and move the three records that dispatch ahead of the maintenance gate into it |
| §C4 | Route every target-extraction regex through one flag-, quote- and delimiter-aware positional helper |
| §C5 | Decide which spans of a command are live before the guard scans them |
| §C6 | Make the read-only diagnostics report the real state and hand back a usable next step |
| §C7 | Make the pack parser honour the pack's own markup and report the heading it really matched |
| §C8 | Derive one inventory of harness-owned files and make write, claim and uninstall all read it |
| §C9 | Make the recall and orientation stack say nothing it has not verified |
| §C10 | For each shipped scanner rule, build the instance it claims to catch, confirm it is missed, and fix the predicate |
| §C11 | Make the two session-start warnings that cannot correctly fire actually fire |
| §C12 | Align the two halves of /reflect on one surface set, one placeholder stripper and one timestamp |
| §C16 | Widen two scanners to the tree their motivating defect actually lives in, and fix what they then flag |
| §C17 | Close all three shipped bugs the deferred pack DEF-532/TP-362 bundles |
| §C19 | Derive _ONBOARDING_DOCS from get_seed_docs(), then fix every doc the widened gate reds |
| §C21 | Capture the real hook and init output once, then regenerate every quoted sample and in-code list from it |
| §C22 | Delete the re-derived copies in README and CONTRIBUTING and link the canonical doc instead |
| §C45 | Close the two rows whose defect is in the ledger row itself |
| §C49 | Judge a command by the shell that will execute it — its real write verbs, and the grammar that will parse a nested payload — not by the tool name it arrived on |
| §C50 | Point the ASCII contract at the union net, widen it to the join-accumulator shape, and repair the 42 characters that reach a terminal |
| §C52 | Classify the operand a verb removes or relocates, on both shells, beside the operands it writes and reads — and make every shipped sentence about that scope say what the code does |
| §C47 | Closed — its rows left at the 2026-09-20 cut |

## Appendix B — id index

**Every id and the section that now holds it. This is the lookup that replaces section-number
navigation** — and its strike markers are now pinned to the member rows by
`tests/test_generate_ledger_regions.py`, so it cannot drift from them.

⚠ **That sentence used to say "it is GENERATED from the member rows, so it cannot drift" and it
was false.** Nothing generated it and nothing compared the two strike markers, so on 2026-09-02
twelve ids were struck in their `§C` section and still unstruck here — DEF-414c, 427, 433, 497,
498, 499, 500, 551, 596, 597, 617, 624. A reader resolving any of them through this index was told
closed work was open. A claim that a thing *cannot* drift is worth exactly the gate behind it.

A ~~struck~~ row is CLOSED but kept addressable, so a citation resolves to its home rather
than dead-ending. Read struck as "closed — go read the row", never as "still open".

| id | § | site |
|---|---|---|
| `DEC-28` | §4A | cc/GOAL.md:18-23 (the fork); tools/cc/hooks/session_start.py::_goal_section (:1462-1478) is the surface it wou |
| `DEC-29` | §4A | tools/cc/hooks/task_router.py (absence); owned today by task-packs/FORWARD_LEDGER.md:2341 (DEC-26, trailing 'R |
| `DEC-30` | §4A | espalier/managed_inventory.py::_SEED_DOC_REL_PATHS (20 seeds); memory/publish-from-a-generated-public-repo.md |
| `DEC-32` | §4A | `espalier/mirror_registry.py::MIRROR_ROWS` (nine rows, five of them tracked byte-copies of a source tree: vendor-cc, claude-asset, asset-docs, task-packs-router, selfcheck-tests); the vendored-byte-copy rule in the root CLAUDE.md architecture section (shipped as package-data) |
| `DEC-33` | §4A | `.gitattributes` (the five sentinel rows `export_sentinels` derives, out of seven plain-file `export-ignore` rows with two forgiven, and the `.claude/workflows/` row) + `reports/seed-carry-2026-09-25/` (the parked copies, gitignored) + the frozen archive tree `espalier_harness_dev_private` |
| `DEC-34` | §4A | `espalier/fusion_manifest.py::HARNESS_EXCLUDE` + `espalier/surface_contract.py::_LOCAL_ONLY_PREFIXES` + `.gitattributes` (the `.claude/workflows/ export-ignore` row) + `espalier/cli.py::_packaged_md_assets` (the deploy set, three kinds) |
| `DEC-35` | §4A | espalier/models.py::HarnessConfig |
| `DEC-36` | §4A | espalier/harness_config.py::OPTIONAL_AGENTS + espalier/doctor.py::_three_way_ownership (the DEF-756 `unshipped_saved_agents` arm) + README.md (the roadmap's language-aware templating promise) |
| `DEC-37` | §4A | espalier/settings_profiles.py::_workflow_fingerprint_allows + tests/test_settings_profile_fingerprint.py (the allow-list-reflects-fingerprint pack's docstring and its `typescript_npm` row) + docs/SHARP_EDGES.md (Generated Settings With Zero Deny Rules Read As Trusts Everything) |
| `DEC-38` | §4A | espalier/managed_inventory.py::_SEED_DOC_REL_PATHS |
| `DEC-39` | §4A | tools/cc/ci_guard.py::PROTECTED_PREFIXES (the `.github/workflows/` entry and its self-host-workflow comment), ::is_protected (applied on every repo) and ::approval_marker_required (False only for a self-host push); tools/cc/hooks/_hook_utils.py::harness_protected_prefixes (the local layer's opposite policy); tests/test_ci_guard.py::TestApprovalMarkerRepoPosture.test_adopter_push_without_marker_is_denied and ::_touch_protected (the 2026-08-02 ruling's pin); docs/INSTALL-CI.md#3-approving-legitimate-harness-updates ('every workflow') |
| `DEC-40` | §4A | tools/cc/hooks/plan_guard.py::_PLAN_EXEMPT_HINT |
| `DEC-41` | §4A | espalier/harness_config.py::CANONICAL_HOOK_WIRING (no entry carries `onFailure`, so every wired hook keeps the default `"continue"`); docs/external/cc-hook-protocol.md#Block the action when a hook fails (new 2026-10-10, not wired); docs/SHARP_EDGES.md#A missing `write_guard.py` wedges the whole session, and the fix is not reachable from inside it |
| `DEC-26` | §4A | `tools/cc/hooks/task_router.py` + `.claude/commands/implement-{task,pack}.md` |
| `DEC-27` | §4A | `espalier/scanners/retired_vocab.py::RETIRED_TERMS` |
| `DEC-23` | §4A | `.claude/commands/commit.md` + `CLAUDE.md` |
| `DEC-24` | §4A | `tools/cc/hooks/post_write_check.py` |
| `DEC-14` | §4A | `docs/REDEFINED_INFORMATION_REGISTRY.md:70` |
| `DEC-10` | §4A | `tools/cc/ci_guard.py` |
| `DEF-347c` | §4A | `tools/cc/reflect_protocol.py` |
| `DEC-13` | §4A | `espalier/provenance_census.py::_ALLOWLISTED_FILES` |
| `DEC-15` | §4A | `ESPALIER_MEMORY.md:0` |
| `DEF-412c` | §4A | `CLAUDE.md:0` |
| `DEC-17` | §4A | `memory/action-justification-protocol.md:51` |
| `DEF-344` | §4A | `tests/test_portability_contract.py` |
| `DEF-865` | §4A | `task-packs/FORWARD_LEDGER.md:309` |
| `DEC-5` | §4A | `tools/cc/hooks/session_start.py::_SECTION_SOURCE` |
| `DEC-9` | §4A | `task-packs/FORWARD_LEDGER.md:1984` |
| `DEF-866` | §4A | `task-packs/FORWARD_LEDGER.md:610` |
| `DEF-279a` | §4A | `task-packs/FORWARD_LEDGER.md:780` |
| `DEC-16` | §4A | `task-packs/FORWARD_LEDGER.md:2058` |
| `DEC-7` | §4A | `CHANGELOG.md:11` |

