# TP-457 — Adopt the two release docs and sweep the withheld set out of the tree's model of itself

## Status

- Version target: before the `0.8.0b2` cut (the runbook must be in the tree that runs it)
- Change type: cleanup / test-infrastructure / docs
- **Kind: PACK**
- Ledger rows: `DEC-33` (§4A, the fork; decided 2026-09-26 by the operator: branch (a) plus
  the full sweep), `DEF-923` (§C28), `DEF-924` (§C18), and the eight probes the checker
  reports UNRESOLVED on this tree (`DEF-450`, `DEF-393a`, `DEF-874`, `DEF-885`, `DEC-28`,
  `DEF-324c`, `DEF-625`, `SUP-2`).
- Authored 2026-09-26 on the public tree at `550314e`, after the first post-cut ledger pack
  (PR #8) filed the fork.

---

## Motivation

The 2026-09-25 seed was built like a source export, so every `.gitattributes` row marked
`export-ignore` dropped its file. Nineteen tracked files went; one, `ESPALIER_MEMORY.md`,
came back in PR #3. The public tree is now the only development tree, and the eighteen
still out live in the frozen archive and in a gitignored parking directory here
(`reports/seed-carry-2026-09-25/`, one machine).

Two problems wear the one fork row, and only the first is closed by copying files back.

**The runbook problem** is content: the tree that releases carries neither its runbook nor
its decision log. Adopting `docs/RELEASE_CHECKLIST.md` and `docs/RELEASE_DECISIONS.md`
closes that for good.

**The model problem** is that the repo still describes itself as "a private dev tree that
carries internal files, plus exports that lack them". The sentinel discriminator, the
`full_tree` registry, the archive-parity floors, the manifest excludes, the
internal-filename patterns and the claim-extractor rosters all encode that model. Most of
the old internal set is never coming back, so every one of those sites now names a ghost.
Adopting the two docs flips the discriminator back on as a side effect, which is why it
looks like a fix; it leaves three dead sentinel rows and every roster still naming files
that do not exist.

**Measured 2026-09-26, all on this tree, each with its command:**

- Eight ledger probes read UNRESOLVED: `python3 scripts/check_ledger_probes.py --json`,
  filter `verdict == "UNRESOLVED"`. Three name the checklist as subject, one reads the
  decisions log as a declared input, one reads it undeclared and crashes rc=1, three name
  the withheld `.claude/workflows/`.
- The discriminator reads this tree as an export and 61 `full_tree` rows auto-skip in every
  run and every CI cell: `python3 -m pytest -m full_tree --collect-only -q | tail -1`. Forced
  on (`ESPALIER_FULL_TREE_AUDIT=1 python3 -m pytest -m full_tree -q`): 42 failed, 19 passed,
  1 skipped.
- Six reader-facing files name the runbook and none names a place the reader can reach
  (`DEF-924`'s probe prints True).
- The never-returning names are enumerated by:

  ```bash
  git grep -c -E "REDEFINED_INFORMATION_REGISTRY|RELEASE_FINDINGS_LEDGER|publish-from-a-generated-public-repo|-atlas\.md|\.claude/workflows" -- espalier tests scripts tools/cc MANIFEST.in .gitattributes .gitignore docs/*.md CLAUDE.md .claude/commands .claude/skills
  ```

  On 2026-09-26, without the `tools/cc` root, that read 35 files, the top five being
  `tests/test_git_archive_parity.py` (16 hits), `espalier/surface_contract.py` (12),
  `tests/test_pre_release.py` (11), `MANIFEST.in` (9) and `tests/conftest.py` (8); the
  pack's own scope check then surfaced `tools/cc/reflect_protocol.py` (a roster) and
  `tools/cc/hooks/_born_weak.py` (a pointer), which the root above now covers. A `tools/cc`
  edit is mirrored into `espalier/_vendor/cc/` by `scripts/sync_vendor_cc.py`, never by hand.
  The command is the roster; the counts are a snapshot.

**One design option is already refuted.** A `.git`-presence discriminator (an export has no
`.git`, a clone always does) fails by construction: `scripts/archive_probe.py::extract`
refuses an extracted archive that carries `.git`, and the probe then *seeds one in*
(`DEF-670`), so the exports this repo tests do carry `.git`. The content-sentinel mechanism
stays; its story changes.

**One reviewer claim is already refuted.** The failure-mode review of PR #8 reasoned that
adopting the two docs would red `tests/test_operator_docs.py`'s linked-or-exempt gates.
Driven 2026-09-26 in a `--shared` clone with both docs copied in and `git add -N`'d:
`classify_release_path` reads both `internal`, that module's population is `public` only, and
it stayed green. `DEC-33`'s row text carried that claim and is corrected by this pack's
authoring commit.

---

## Scope (in)

- **0** — Task 0: the disclosure read of the two docs, the adoption drive re-run after a
  real `git add`, and the one open sub-decision (the review scaffolds). Licensed to end the
  pack.
- **1** — Adopt the two release docs as tracked files at their real paths
  (`docs/RELEASE_CHECKLIST.md`, `docs/RELEASE_DECISIONS.md`); keep them `internal`,
  export-ignored and sdist-excluded; rewrite the two absent-claim pointer sentences
  (`CONTRIBUTING.md`, `docs/README.md`) and read the four true ones (`docs/FRESHNESS.md`,
  `docs/TASK_RECIPES.md`, `.claude/commands/preflight.md`, `.github/workflows/release.yml`);
  let the documented-claims audit re-engage on the checklist's counts.
- **2** — Sweep the never-returning names out of every roster, and rewrite or drop every
  live pointer to them, leaving record surfaces alone. Derived by the command above; the
  rosters measured on 2026-09-26 sit in `.gitattributes`, `MANIFEST.in`,
  `espalier/surface_contract.py`, `espalier/claim_extractor.py`, `espalier/fusion_manifest.py`,
  `tests/test_git_archive_parity.py`, `tests/test_documented_claims.py`,
  `tests/test_surface_contract.py`, `tests/test_self_hosting.py`, `tools/cc/reflect_protocol.py`
  (mirrored by `scripts/sync_vendor_cc.py`); the live pointers in `docs/CONVENTIONS.md`,
  `docs/FAILURE_MODES.md` (mirrored to `espalier/assets/docs/FAILURE_MODES.md`),
  `tests/test_pre_release.py`, `tools/cc/hooks/_born_weak.py`; the fixture in
  `tests/test_reflect_protocol.py` is read and classified at execution.
- **3** — Triage the `full_tree` registry (`tests/conftest.py`) by its three registration
  reasons against the new reality; rewrite the discriminator's docstring
  (`espalier/surface_contract.py`, pinned by `tests/test_export_guard.py`); retire the tests
  that can never pass on the development tree again, the atlas pins in `tests/test_recall.py`
  and `tests/test_recall_eval.py` among them.
- **4** — Re-key the eight probes and strike what its own probe closes
  (`task-packs/FORWARD_LEDGER.md`, `task-packs/LEDGER_PROBES.json`,
  `tests/test_check_ledger_probes.py`); strike `DEC-33` by hand; clear its owed item
  (`cc/GOAL_OWED.json`, `cc/GOAL.md`).
- **5** — Red-team, then the one tier and the landing.

## Scope (out)

| Deferred | Reason |
|---|---|
| The three `memory/*-atlas.md` files | Branch (a) as decided keeps them out. Their five recall pins (`tests/test_recall.py` three, `tests/test_recall_eval.py` two) retire in sub-task 3 with the reason written beside each. Their absence is the probable cause of the recall headline moving from 9 to 7 at the seed (PR #2 registered both readings); adopting them later re-opens those pins, and nothing in this pack forecloses it. |
| `docs/RELEASE_FINDINGS_LEDGER.md` | Stays out: its line 114 carries a machine-local path, which `tests/test_no_internal_codenames.py`'s machine-path arm reds on the self-host machine. Its roster entries are swept. |
| `memory/publish-from-a-generated-public-repo.md` | Stays out by `DEC-25` and the operator's 2026-09-25 re-decision (the seed-carry README's Status). |
| `docs/REDEFINED_INFORMATION_REGISTRY.md` | Stays out: internal contract shorthand. Its six dependents (three source-citation rows, two numeric-contract surfaces, one maintenance-roster row) are swept or retired. |
| The content defects inside the checklist: `DEF-393a`, `DEF-874`, `DEF-885` | This pack makes their subject resolve again; fixing the hotfix lineage, the push-step headline and the tag-count gate is each row's own work. |
| `DEF-450`'s superseding decision | This pack makes its input resolve; writing the decision is the row's own work. |
| `DEF-623` (make the self-host `.gitignore` match what the harness prescribes) | Its own row; touching `.gitignore` here would confound the sentinel story. |
| The `0.8.0b2` cut | Runs from the adopted runbook after this pack lands. |
| The reflect gap in `docs/session-archive.md` | Gitignored local state linking the withheld memo; not a tracked surface. |

⚠ **Scope-out is a claim.** The first row asserts the atlases' absence is what moved the
recall headline; that is probable, not measured. If sub-task 3's retirement of the five pins
turns out to need the atlases for any other test, re-raise rather than adopt them silently.

---

## Task 0 — Verify (may end this pack)

Three questions. Any refuting answer ends the pack before a file moves.

### 0-A The disclosure read (operator)

**The question:** may `docs/RELEASE_CHECKLIST.md` and `docs/RELEASE_DECISIONS.md` be public?

**Oracle:** read both files in `reports/seed-carry-2026-09-25/docs/` in full. Beside you,
the seed-carry README's scan table (codename arm: 0 hits over all nine; record-exclusion
vocabulary: 0 hits; machine-local path: 0 in these two). Then:

```bash
python3 -m pytest tests/test_no_internal_codenames.py -q -p no:cacheprovider
```

with both files copied to `docs/` and `git add`ed, on the self-host machine (the
machine-path arm derives from `$HOME` and only tells the truth there).

**Refuting result:** a sentence that names something that should not be public and cannot
be rewritten without changing a claim, or a red from the codename gate.

**Exit:** stop and re-raise. The fork re-opens at branch (b); do not scrub and continue.

### 0-B The adoption drive, re-run after a real add

**The question:** does the red set after adoption match the measured one, or does it grow a
group the sweep does not name?

**Oracle** (driven at authoring in a `--shared` clone with the docs `git add -N`'d; re-run
with a real `git add`, because `_tracked_paths_at_head` reads HEAD and intent-to-add is not
HEAD):

```bash
git clone --shared -q . "$S/adopt-clone"
cp reports/seed-carry-2026-09-25/docs/RELEASE_CHECKLIST.md reports/seed-carry-2026-09-25/docs/RELEASE_DECISIONS.md "$S/adopt-clone/docs/"
cp .local-codenames.txt "$S/adopt-clone/"
git -C "$S/adopt-clone" add docs/RELEASE_CHECKLIST.md docs/RELEASE_DECISIONS.md
git -C "$S/adopt-clone" -c user.name=probe -c user.email=probe@localhost commit -q -m "probe: adopt"
( cd "$S/adopt-clone" && python3 -c "from pathlib import Path; from espalier.surface_contract import is_release_export as e; print(e(Path('.')))" )
( cd "$S/adopt-clone" && python3 -m pytest -m full_tree -q -rfE -p no:cacheprovider --timeout=600 )
```

**Measured at authoring (intent-to-add, not a commit):** `is_release_export` False; the
registry ran normally: **28 failed, 33 passed, 1 skipped**. The 28 group by the withheld set
each asserts:

| Group | Rows | Modules |
|---|---|---|
| the review scaffolds | 16 | `test_contracts` 3, `test_convergence_workflow_stages` 2, `test_finding_ledger` 7, `test_fuse` 1, `test_git_archive_parity` 3 |
| the registry | 6 | `test_doc_source_citations` 3, `test_documented_claims` 2, `test_maintenance_mode` 1 |
| the atlases | 5 | `test_recall` 3, `test_recall_eval` 2 |
| the findings ledger | 1 | `test_required_status_checks` 1 |

The archive-parity trio red on non-vacuity floors (`>= 7` internal, `>= 5` local-only, the
scaffold floor), not on a leak. The `test_maintenance_mode` assignment is inferred from its
registration comment, not from its assertion text; read it at execution.

**Refuting result:** a red outside these four groups after the real add, or a green among
the 33 that the export run (0-C) shows is stale for a reason other than "the docs are back".

**Exit:** re-scope sub-task 3's roster to what the run shows; if a fifth group appears, stop
and re-raise.

### 0-C The scaffolds sub-decision (operator)

**The question:** do the two generic review scaffolds come back?

`memory/convergence-review-protocol.md` names `.claude/workflows/_convergence_review_template.js`
and `.claude/workflows/_fanout_audit.js` as the start-from-complete base for a convergence
round, and `tests/test_convergence_workflow_stages.py` is the contract over them. Both are
one-shot in spelling and reusable in fact. The eight dated round scripts are one-shot in
both.

**Default (recommended): adopt the two generic scaffolds, retire the eight dated ones.**
Then the `.claude/workflows/ export-ignore` row, `_LOCAL_ONLY_PREFIXES`'s entry and
`fusion_manifest.HARNESS_EXCLUDE`'s entry all stay; the archive-parity local-only floor
re-calibrates to 2 with its reason rewritten; the sixteen scaffold rows are re-floored
against a two-file population rather than retired; `DEF-324c` and `DEF-625` re-anchor to the
two files; `SUP-2` (the goalie round's per-lane trace) retires, its scaffold gone.

**Alternative: none come back.** Every `.claude/workflows/` site is swept, the sixteen rows
retire, the three probes retire, and the protocol memo says the scaffolds live in the archive.

**Refuting result for the default:** the two scaffolds carry an account detail, a private
path or a quoted person (read them in the archive tree first: they are one-shot review
prompts and may quote findings).

**Exit:** the alternative, recorded as the operator's call in the Landing stanza.

---

## Relevant memory

Recent pattern, measured this session: both majors the two reviews of PR #8 found were in
the repair, not the original defect. A gate limb read green on nine of twelve mutations
because its clean state was inferred from an absence, and a filed row's claim was falsified
by the very function it cited. The reviewer's own reasoned cost claim for this branch was
then refuted by driving it. Expect the red-team to bite on the sweep's floors and on the
registry triage, not on the copy step.

| Entry | Where |
|---|---|
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| A tracked internal doc needs a sister-site footprint, and part of it is conditional | `docs/SHARP_EDGES.md` |
| Converting a self-detecting skipif to a marker drops every filter-less consumer | `docs/sharp-edges/skipif-to-marker-drops-filterless-consumers.md` |
| Premise check before authoring a fix | `memory/premise-check-before-authoring-a-fix.md` |
| Classify the surface before measuring it | `memory/classify-the-surface-before-measuring-it.md` |
| Find all the reds, a masking failure hides the ones behind it | `memory/find-all-the-reds.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "<topic>"` with the topics
`release export sentinel discriminator`, `class sweep sister sites enumeration roster`,
`stale test registration retire export archive probe` and `adopt a withheld doc classify
before you track`; re-run them rather than trusting this list if the pack has been sitting.
The folder ladder fires on entry to `espalier/`, `tests/` and `docs/`; this pack names every
file it touches so that layer fires.

---

## Implementation

### 1-A Copy the two docs to their real paths *(driven in the scratch clone; the commit is the only untested step)*

```bash
cp reports/seed-carry-2026-09-25/docs/RELEASE_CHECKLIST.md docs/RELEASE_CHECKLIST.md
cp reports/seed-carry-2026-09-25/docs/RELEASE_DECISIONS.md docs/RELEASE_DECISIONS.md
git add docs/RELEASE_CHECKLIST.md docs/RELEASE_DECISIONS.md
python3 -c "from pathlib import Path; from espalier.surface_contract import classify_release_path as c, is_release_export as e; print(c('docs/RELEASE_CHECKLIST.md'), c('docs/RELEASE_DECISIONS.md'), e(Path('.')))"
```

Expected: `internal internal False`. Byte copies, nothing edited yet. Their `.gitattributes`
rows, `MANIFEST.in` excludes, `_INTERNAL_FILENAME_PATTERNS` entries, `claim_extractor`
classifications and `EXPORT_IGNORED_INTERNAL_DOCS` entries all stay: the docs are tracked,
public on GitHub, and still kept out of the sdist and the Download ZIP. Checkpoint:

```bash
python3 -m pytest tests/test_operator_docs.py tests/test_git_archive_parity.py tests/test_wheel_payload.py::TestSdistPayload::test_sdist_excludes_internal_classified_files -q -p no:cacheprovider
```

The archive-parity module reds on its floors until 2-A; every other row here is expected
green (measured for `test_operator_docs`; hypothesised for the sdist row, which builds the
package and takes a minute).

### 1-B The checklist's live counts *(fix shape, untested)*

The checklist is AUDITED (`claim_extractor.AUDITED_INTERNAL_DOCS`) on purpose: its numbers
must keep drifting red. The archive's copy is dated 2026-09-24 and the code moved. Run:

```bash
python3 -m pytest tests/test_documented_claims.py tests/test_count_claims.py tests/test_release_checklist_contract.py -q -p no:cacheprovider
```

and correct every count in the doc to the deriving expression the failure names. Refuted if
a red here is about the registry rather than the checklist: that red belongs to 2-A and must
not be closed by editing the checklist.

### 1-C The six pointer sentences *(fix shape, untested; the probe decides)*

Each sentence becomes true as written once the file is tracked, except two that assert its
absence. Rewrite those two; leave the four "self-host only" sentences, which are true.

- `CONTRIBUTING.md`, the release section (the sentence beginning "the maintainer release
  runbook"): it is kept in this repository, export-ignored, and read on GitHub.
- `docs/README.md`, the paragraph above the two-row table that says the files are "kept in
  the maintainers' private archive": they are tracked here and excluded from every shipped
  artifact.

Checkpoint: `python3 scripts/check_ledger_probes.py --id DEF-924` reads STRIKE_CANDIDATE.

### 2-A The sweep *(fix shape per site; the deriving command is the roster)*

Run the enumeration command from *Motivation* and classify every hit into one of three
kinds before editing anything (`memory/classify-the-surface-before-measuring-it.md`):

| Kind | Rule | Examples measured 2026-09-26 |
|---|---|---|
| **Roster** | remove the member; if the roster has a non-vacuity floor, re-derive the floor from the surviving population and rewrite its reason beside it | `.gitattributes` (five plain-file rows and the `.claude/workflows/` row per 0-C); `MANIFEST.in` exact excludes; `espalier/surface_contract.py::_INTERNAL_FILENAME_PATTERNS`; `tests/test_git_archive_parity.py::EXPORT_IGNORED_INTERNAL_DOCS` and its two floors; `espalier/claim_extractor.py::AUDITED_INTERNAL_DOCS`, `::FROZEN_RECORD_DOCS`, `::RECORD_SURFACES`, `::EXCLUDED_DOC_GLOBS`; the two `NumericContract` surfaces in `tests/test_documented_claims.py` naming the registry; `tests/test_self_hosting.py`'s ignore patterns where hand-listed |
| **Live pointer** | rewrite to say where the file lives (the archive tree, by its slug) or drop the pointer | `docs/CONVENTIONS.md` ("lives at `docs/REDEFINED_INFORMATION_REGISTRY.md`"); `docs/FAILURE_MODES.md`'s three "see the registry / the findings ledger" sentences; `tests/test_pre_release.py`'s eleven mentions, each to be read |
| **Record** | leave it | dated Session Log rows in `ESPALIER_MEMORY.md`; `memory/CONVERGENCE_LEDGER.md`; the footprint entry in `docs/SHARP_EDGES.md` that narrates the 2026-08-13 reclassification; any struck ledger row |

Floors that must move, with the surviving population that sets them:

- `test_no_internal_classified_tracked_file_ships_in_the_archive`: `>= 7` internal tracked
  files, found 0 in the clone (HEAD has none; after 1-A's commit, 2). Re-derive from
  `classify_release_path` over `git ls-files` and write the reason.
- `test_no_local_only_classified_tracked_file_ships_in_the_archive`: `>= 5`, the scaffolds.
  Per 0-C: 2, or the test's premise ("non-vacuous today: the ten review scaffolds") is gone
  and the test retires with the floor, never a `>= 0`.

**Refutation for the whole sub-task:** if after the sweep the derived gates
`test_sdist_excludes_internal_classified_files` and
`test_no_internal_classified_tracked_file_ships_in_the_archive` pass on a population of
fewer than two, the sweep removed a member the gate still needed and the floor was widened
to hide it. A pass criterion below forbids that shape.

### 3-A Triage the `full_tree` registry *(fix shape; 0-B's run is the roster)*

`tests/conftest.py::_FULL_TREE_NODEIDS` registers rows for three reasons, written beside
each entry: the content an export prunes, git needing a worktree, export-detected behaviour.
For each of the 61 collected rows, after 1-A:

1. **Red after adoption (the 28):** the row asserts content the development tree no longer
   has. It can never pass here again, so `full_tree` no longer describes it. Retire the test,
   or rewrite it to drive a fixture (the 2026-09-23 sweep narrowed several modules that way
   and left fifteen fixture-driven siblings green). Delete its registration with the test.
2. **Green after adoption AND red on the export run (0-C's `archive_probe.py --audit`):**
   the registration's reason holds (the docs are export-ignored, so an export still lacks
   them). Keep it. Expected for the fourteen that flipped.
3. **Green after adoption AND green on the export run:** a stale registration. Delete it,
   after reading whether the export presents a non-degenerate population (the conftest's own
   fence, premise 8 of `TP-455`). Expected for the nineteen that passed even before adoption.

The export run that decides case 2 from case 3:

```bash
python3 scripts/archive_probe.py --audit -- -q -rA -m full_tree
```

This must run on a tree where 1-A has landed, because the archive is built from the
checkout. Never widen a registration to keep a red row skipping.

### 3-B The discriminator's story *(docstring and comment only; semantics unchanged)*

`espalier/surface_contract.py::export_sentinels` and `::is_release_export` keep their
mechanism. Rewrite the docstrings' model: the public clone is the development tree; the
sentinels are the plain-file export-ignore rows that survive 2-A (the two release docs);
the memory file stays forgiven. Record the `.git` refutation from *Motivation* in
`is_release_export`'s docstring so it is not proposed again. `tests/test_export_guard.py::
TestIsReleaseExport` pins the mechanism and must keep its strength; its fixture names may
need the new sentinel set.

### 4-A The probes and the strikes *(each by the ledger verbs; sequential, unpiped)*

- `DEF-923`: its probe prints `False 60` after 1-A and the registry count after 3-A; strike
  with the measured before/after counts.
- `DEF-924`: strike when its probe prints False after 1-C.
- `DEF-450`, `DEF-393a`, `DEF-874`, `DEF-885`: `python3 scripts/check_ledger_probes.py --id`
  reads STILL_OPEN once the file is tracked; `repin` with the reason. Then
  `tests/test_check_ledger_probes.py`'s tolerated roster, currently exactly
  `{("DEF-450", "docs/RELEASE_DECISIONS.md")}`, becomes empty: tighten the assertion to the
  empty set, do not delete it.
- `DEC-28`: the verbs cannot address a three-cell §4A row (`DEF-869`). Declare its input by
  hand in `task-packs/LEDGER_PROBES.json`, then `python3 scripts/check_ledger_probes.py --id DEC-28`
  must read STILL_OPEN, never rc=1.
- `DEF-324c`, `DEF-625`, `SUP-2`: per 0-C.
- `DEC-33`: strike by hand, double tildes around the id cell (the verbs refuse it); the
  owed-item probe `dec33-withheld-files` in `cc/GOAL_OWED.json` then reads DONE; remove its
  bullet and entry, or replace them with this pack's landing as the next owed item.

### 5-A Red-team

Dispatch `code-reviewer` and `failure-mode-reviewer` in snapshot clones, one message, edits
frozen. What this pack is most likely to have gotten wrong, in order: a floor lowered to the
surviving count without asking whether the gate still catches its mutation; a registration
deleted on this tree's green without the export run; a pointer sentence rewritten to a claim
the archive no longer supports; a retired test whose fixture-driven sibling would have kept
the coverage. Ask each lane for the mutation that survives, not for approval.

---

## Affected symbols

### Changed-semantics

- `espalier/surface_contract.py::_INTERNAL_FILENAME_PATTERNS` — loses the three never-returning docs; keeps the two release docs
- `espalier/surface_contract.py::export_sentinels` — mechanism unchanged; docstring's model rewritten (the public clone is the dev tree)
- `espalier/surface_contract.py::is_release_export` — mechanism unchanged; docstring records the `.git` refutation
- `espalier/surface_contract.py::_LOCAL_ONLY_PREFIXES` — the `.claude/workflows/` entry stays or goes per 0-C
- `espalier/claim_extractor.py::AUDITED_INTERNAL_DOCS` — loses the registry
- `espalier/claim_extractor.py::FROZEN_RECORD_DOCS` — loses the registry and the findings ledger where named
- `espalier/claim_extractor.py::RECORD_SURFACES` — loses the findings ledger
- `espalier/claim_extractor.py::EXCLUDED_DOC_GLOBS` — loses the never-returning globs
- `espalier/fusion_manifest.py::HARNESS_EXCLUDE` — the `.claude/workflows/` entry per 0-C
- `tests/conftest.py::_FULL_TREE_NODEIDS` — triaged per 3-A
- `tests/test_git_archive_parity.py::EXPORT_IGNORED_INTERNAL_DOCS` — loses the three never-returning docs
- `tests/test_git_archive_parity.py::test_no_internal_classified_tracked_file_ships_in_the_archive` — floor re-derived
- `tests/test_git_archive_parity.py::test_no_local_only_classified_tracked_file_ships_in_the_archive` — floor re-derived or retired per 0-C
- `tests/test_documented_claims.py::TestNoStaleNumericContracts` — the two registry surfaces leave their contracts
- `tests/test_check_ledger_probes.py::TestTheLiveProbeFile::test_every_declared_input_resolves_on_the_development_tree` — tolerated roster tightened to the empty set

### Renamed

- (none -- nothing is renamed)

### Added-paths

- `docs/RELEASE_CHECKLIST.md` — adopted from the parking directory, byte copy then counts corrected
- `docs/RELEASE_DECISIONS.md` — adopted from the parking directory, byte copy

### Removed-paths

- (none -- the swept files were never on this tree; their names leave rosters, not the tree)

## Affected literals

- `REDEFINED_INFORMATION_REGISTRY.md`
- `RELEASE_FINDINGS_LEDGER.md`
- `publish-from-a-generated-public-repo.md`
- `-atlas.md`
- `.claude/workflows/`

---

## Reach

Members derived by: `python3 scripts/check_ledger_probes.py --json` (every `UNRESOLVED`
verdict on this tree) plus the two rows PR #8 filed against the same cause, plus the fork.
The forced `full_tree` run is the roster for sub-task 3, not a ledger reach.

| Item | Status | Evidence |
|---|---|---|
| `DEC-33` | **CLOSED** | struck by hand at landing; the owed probe reads DONE |
| `DEF-923` | **CLOSED** | its probe prints False once the sentinels return; the registry drains by 3-A |
| `DEF-924` | **CLOSED** | its probe prints False once the file is tracked and the two absent-claim sentences are rewritten |
| `DEF-450` | **RE-KEYED, not closed** | its input resolves; writing the superseding decision is the row's own work |
| `DEF-393a` | **RE-KEYED, not closed** | its subject resolves; the dead hashes are the row's own work |
| `DEF-874` | **RE-KEYED, not closed** | its subject resolves; the push-step headline is the row's own work |
| `DEF-885` | **RE-KEYED, not closed** | its subject resolves; the tag-count gate is the row's own work |
| `DEC-28` | **RE-KEYED, not closed** | input declared by hand; its claim about the goal doc stands |
| `DEF-324c` | **CLOSED or RE-ANCHORED** | per 0-C: retired with the scaffolds, or re-anchored to the two adopted ones |
| `DEF-625` | **CLOSED or RE-ANCHORED** | per 0-C: the injected-description cost falls with the eight dated scripts either way |
| `SUP-2` | **CLOSED as retired** | the goalie scaffold does not return under either 0-C outcome |
| `DEF-623` | **NOT REACHED** | the self-host `.gitignore` row; its own unit of work |

---

## Pass criteria

- `python3 -c "from pathlib import Path; from espalier.surface_contract import is_release_export as e; print(e(Path('.')))"` prints `False` on this tree, and
  `python3 scripts/archive_probe.py --audit -- -q -rA -m full_tree` shows the extracted export
  read as an export (its own refusal arm proves it).
- The enumeration command in *Motivation* returns only record surfaces, and each surviving
  hit is one the Landing stanza names with its kind.
- `python3 -m pytest -m full_tree -q` on this tree: 0 failed, and every surviving
  registration's comment names the export-pruned content it reads.
- The export run above: every surviving registration FAILS on the export, except the vacuous
  four the 2026-09-23 sweep kept with their reasons. A PASS is a stale registration and
  fails this criterion.
- `python3 scripts/check_ledger_probes.py --strikes` exits 0 with zero `UNRESOLVED`
  verdicts, or each remaining one is named in Landing with its reason.
- **Strength, not text:** no assertion is weakened; every floor that moves is re-derived
  from the surviving population with its reason rewritten beside it and never set to zero;
  `test_sdist_excludes_internal_classified_files` and
  `test_no_internal_classified_tracked_file_ships_in_the_archive` keep their derivation from
  `classify_release_path`; `tests/test_export_guard.py::TestIsReleaseExport` keeps every
  arm. A defect found in any gate this pack edits is this pack's to fix.
- `python3 scripts/check_handoff_landing.py` reads clean; `python3 scripts/proof_tier.py --run`
  reads the full tier (the diff touches `espalier/` and `tests/conftest.py`) and passes;
  `python3 -m espalier audit .` passes.

---

## Files touched

- **New:** `docs/RELEASE_CHECKLIST.md`, `docs/RELEASE_DECISIONS.md`; per 0-C,
  `.claude/workflows/_convergence_review_template.js` and `.claude/workflows/_fanout_audit.js`.
- **Modified:** `.gitattributes`, `MANIFEST.in`, `espalier/surface_contract.py`,
  `tools/cc/reflect_protocol.py`, `tools/cc/hooks/_born_weak.py` (both re-mirrored into
  `espalier/_vendor/cc/` by `scripts/sync_vendor_cc.py`), `tests/test_surface_contract.py`,
  `tests/test_recall.py`, `tests/test_recall_eval.py`, `.github/workflows/release.yml` (two
  pointer comments; a workflow path puts `HARNESS-UPDATE-APPROVED@<head7>` in the PR title,
  root `CLAUDE.md` Core Rule 10), `.claude/commands/preflight.md` (read; mirrored by
  `scripts/sync_claude_mirrors.py`),
  `espalier/claim_extractor.py`, `espalier/fusion_manifest.py`, `tests/conftest.py`,
  `tests/test_git_archive_parity.py`, `tests/test_documented_claims.py`,
  `tests/test_check_ledger_probes.py`, `tests/test_export_guard.py`,
  `tests/test_self_hosting.py`, `tests/test_pre_release.py`, `CONTRIBUTING.md`,
  `docs/README.md`, `docs/CONVENTIONS.md`, `docs/FAILURE_MODES.md` (and its asset mirror
  through `scripts/sync_claude_mirrors.py` / the asset-docs row), `task-packs/FORWARD_LEDGER.md`,
  `task-packs/LEDGER_PROBES.json`, `cc/GOAL_OWED.json`, `cc/GOAL.md`, and every test module
  a retired row leaves.
- **Deleted:** none.
- **Unmodified on purpose:** `tests/test_operator_docs.py::INDEX_EXEMPT` (measured: no red);
  `.gitignore` (`DEF-623`); the archive tree; the record surfaces the scope check lists
  as gaps (`cc/blueprints/*.json`, `ESPALIER_MEMORY.md`, `CHANGELOG.md`,
  `WINDOWS_FUSE_NOTES.md`, `memory/CONVERGENCE_LEDGER.md`, `docs/session-archive.md`, the
  working summaries, and `docs/SHARP_EDGES.md`'s narrative entries), which name the withheld
  files as history; the engine consumers of `is_release_export` and of the two docs' paths
  (`espalier/fuse.py`, `espalier/self_hosting.py`, `espalier/audit_accuracy.py`,
  `espalier/managed_inventory.py`, `espalier/surface_impact.py`), whose behaviour this pack
  does not change; the vendored and asset mirrors, regenerated by their sync scripts.

---

## Sub-task ordering

1. **0-A, 0-B, 0-C** — the read, the drive after a real add, the scaffolds call. Checkpoint:
   the operator's written go on 0-A and 0-C, and 0-B's red set within the four groups.
2. **1-A, 1-B, 1-C** — adopt, correct the counts, rewrite the two sentences. Checkpoint:
   `check_ledger_probes.py --id DEF-924` reads STRIKE_CANDIDATE;
   `pytest tests/test_documented_claims.py tests/test_release_checklist_contract.py -q` green
   except the registry rows.
3. **2-A** — the sweep, one site class at a time, rosters first. Checkpoint: the enumeration
   command returns only record surfaces; the archive-parity module green on re-derived floors.
4. **3-A, 3-B** — the registry triage with the export run, then the docstrings. Checkpoint:
   `pytest -m full_tree -q` 0 failed here; the export run shows every survivor red there.
5. **4-A** — probes and strikes, sequential. Checkpoint: `check_ledger_probes.py --strikes`
   exit 0; `generate_ledger_regions.py --check` converged; `check_handoff_landing.py` clean.
6. **5-A** — red-team, one fix batch, the full tier once, the commit flow (branch, PR,
   auto-merge). Checkpoint: the tier receipt.

## Estimated effort

| Sub-task | Budget |
|---|---|
| 0-A | 30 min of the operator's reading; the pack may end here |
| 0-B | 15 min (the drive is scripted above) |
| 0-C | 20 min, including reading the two scaffolds in the archive |
| 1-A to 1-C | 45 min; 1-B dominates if the counts drifted far |
| 2-A | 2 h; the eleven `test_pre_release.py` mentions and the three `FAILURE_MODES.md` sentences are reading, the rosters are mechanical |
| 3-A, 3-B | 2 h; the export run alone is about fifteen minutes |
| 4-A | 40 min |
| Red-team + one fix batch + the full tier | 1.5 h |
| **Total** | **about 7.5 h if Task 0 passes; under an hour if it ends the pack** |

---

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
