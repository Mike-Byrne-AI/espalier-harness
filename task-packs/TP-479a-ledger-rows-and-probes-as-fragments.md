# TP-479a — The ledger's rows and probes as fragments: the record that still conflicts

## Status

- Version target: the next beta after Wave D's window closes; the first wave ships before it.
- Type: cleanup (a record's storage shape), with one derived-count fix.
- **Kind: PACK** — the lettered child `TP-479` Scope (out) names for the case its Wave D
  first line fails. Authored 2026-10-12 by air, the dispatcher, after the operator asked
  for it; the parent stays `ROADMAP` and this child carries the work.
- Takes over `TP-478` 2-A (the probes roster's stored `_count`), which that pack lists as
  open and which no lane has shipped. The parent's line 9 kept 2-A on win-2's seat; the
  dispatcher reassigns it with this pack, since it is this pack's first wave and the
  cheapest half of the measured cost. The operator confirms the reassignment with the
  pack's first assign.
- Corrected 2026-10-12 by air-work at execution: the pack-artifact review returned REQUEST
  CHANGES with one BLOCK (the owed-list `_count` read as the probes file's), each finding
  verified against the tree; the operator chose the correction on this lane and the
  hand-edit witness's new home (0-F).
- Wave A landed 2026-10-12 as #195 (`dc267e96`, merged `lane/probes-count-derived`).
- Corrected 2026-10-13 by air-work at Wave B's execution: the pack-artifact review
  (checklist v2) returned REQUEST CHANGES with one BLOCK: `ledger_row.py::file_row` writes
  an Appendix B index row as well as the member row, and Wave B moved only the member
  row. The operator chose: each row's file carries its index line; the rows show through
  the loader only, never written into the big file; the verbs write row files only where
  a repository opts in (`ledger_fragments`); the correction rides this lane. 0-G then
  drove the collision and corrected the review's mechanism: an index row lands after its
  anchor's index row, not at Appendix B's tail, so it collides exactly where its member
  row does, and the roster's tail collides on every pair of filings (the choice stands,
  for the reason 0-G gives). A re-review of the correction returned one more BLOCK, the
  generator and the convergence step reading the files directly; it and the rest of both
  reviews' findings are folded into Wave B and Wave C below.
- Wave B built 2026-10-13 by air-work on `lane/ledger-fragments-expand`: the loader, the
  verbs writing row and probe files on an opted-in tree, every reader on the view, and this
  repository opted in (`ledger_fragments = true`). Three review rounds each returned
  REQUEST CHANGES (round 1 both reviewers on the first three commits, round 2 both on the
  fix batch, round 3 the failure-mode lane on the refusal change alone, at the operator's
  call); every finding was fixed in the lane or filed: `DEF-4018` (readers no mechanical
  check holds: English instructions, multi-hop helpers) and `DEF-4019` (a filing that dies
  between its row and its probe, which no verb finishes). The operator decided three forks
  on the way: a verb notes a problem it did not cause instead of refusing only where the
  tree keeps rows as files; the prose check and the reader census hold the shapes they can
  decide and say so; the recovery verb is filed, not built. Earn-the-red: 62 named
  mutations over the three fix batches, each red alone.

## Motivation

Wave C of `TP-479` moved two records to per-change files behind one loader
(`tools/cc/_record_fragments.py`): the Session Log rows and the changelog. The ledger and
its probes file stayed single files on `TP-478` Task 0's measurement that rows were 3 of
87 ledger conflict blocks and the derived counts were the rest; 2-B then derived the
ledger's counts out of the file, and `tools/cc/record_merge.py` resolves what remains by
shape at a catch-up. The parent pre-registered the decision: Wave D's first line runs the
merge-cost census over the first 30 pull requests merged after Wave C, passes at 5 or
fewer conflicted catch-ups, and on failure moves the rows behind the loader "in a
lettered child of this pack".

**Measured 2026-10-12, 13 of the 30 merges in** (`python scripts/merge_cost_census.py
--prs 13 catch-ups conflicts blocks`): 13 merged; 9 with a catch-up; 12 catch-ups; 8
conflicted when replayed as GitHub merges them (drivers off), all 8 on the record files
alone: `task-packs/LEDGER_PROBES.json` 8, `task-packs/FORWARD_LEDGER.md` 1. The 11
conflict blocks: `probes: _count` 6, `probes: entries` 4, `ledger: member rows` 1. The
line's threshold is 5 of 30 and the count cannot fall, so the direction is decided at 13;
the remaining 17 merges size it. The culprit is more precise than "the ledger": the
probes file, and within it the stored total first.

What it costs today is a catch-up per lane, not a hand merge: `tools/cc/ship.py` merges
the base in first and `record_merge` resolves the probes file by shape (this pack's own
author watched #192 do exactly that at its push). GitHub's server-side merge honours no
driver, so every such lane reads CONFLICTING until a seat runs the catch-up, and the
census above counts 1.38 test runs per pull request over the window. Core Rule 15 states
the rule the stored total breaks: shared records never store what two lanes both
recompute.

## Scope (in) — the waves

- **Wave A — derive the probes count** (`TP-478` 2-A, taken over). `LEDGER_PROBES.json`
  loses its `_count` key; every reader takes `len(probes)`; the writer never writes it; a
  test keeps it out. Ships as its own pull request, first, because Task 0-A may show it
  alone clears the parent's line.
- **Wave B — rows and probes as fragments, behind the loader (expand).** One file per
  ledger row under `task-packs/ledger.d/` (the member row and its Appendix B index
  lines), one file per probe under `task-packs/probes.d/`; the loader renders, in memory
  only, the view today's readers parse; the readers move to the loader; where a
  repository sets `ledger_fragments = true` the writers (`ledger_row.py file`, `strike`,
  `repin`) write fragments, and everywhere else they write the big file as today; the
  legacy rows in the big file are read beside the fragments.
- **Wave C — the fold (contract).** The legacy rows become fragments, the big file keeps
  its prose and its table headers, the probes file becomes its README (on this tree;
  an adopter's stays a file). Gated on the
  board showing no open pull request that touches either file; same day as Wave B where
  the gate allows, since the fold is what ends the row-adjacency conflicts.
- **Wave D — the re-measure**, the parent's own line re-run over the 30 merges after the
  fold.

## Scope (out)

- **The ledger's prose and generated regions as fragments.** The contract section, the
  class headings and the derived tables conflict 0 times in the measured window (the one
  ledger block was member rows); they stay in the file. Re-raised only if the re-measure
  shows them.
- **`scripts/derived_population_census.py`.** 3 of 27 conflicts in `TP-479` C0-A's window,
  0 in this one; its totals left under the parent's decision 2(a). Not this pack's record.
- **`docs/SHARP_EDGES.md` fragments** and **GitHub's merge queue**: the parent's Scope
  (out) holds for both.
- **Turning the up-to-date rule back on.** The parent's Wave D second line, unchanged.
- **An adopter's ledger as fragments by default.** `init` seeds one file
  (`espalier/assets/seed/FORWARD_LEDGER.md`); the loader reads both forms, so an adopter
  tree keeps its file until its own verbs write a fragment. A seeded directory is a later
  decision with its own measurement (an adopter with one seat has no conflict to cure).
- **`DEF-4010`**, the census's regeneration tripwire: its own row, its own oracle.

## Cross-pack coordination

Read live at each wave's start (`python3 tools/cc/board.py`, `python3 tools/cc/mail.py
claims`); the lines below are 2026-10-13's reading, not the population.

- win-2's `lane/bounded-probe-spawn` routes every timed spawn under `tools/cc` through one
  bounded helper. Its claim names call-site edits in `record_merge.py`,
  `check_ledger_probes.py`, `_record_fragments.py`, `ci_guard.py` and `ship.py`, among
  others, which Wave B also edits by function. Whichever merges second runs `python3
  tools/cc/ship.py catch-up`. A spawn Wave B adds goes through that helper once it has
  landed, since its chokepoint test reds a bypass by name.
- `tests/test_deployed_text_audience.py` (merged in #199) holds the seeded docs to a
  ceiling that `origin/main` met exactly on 2026-10-13 (266 of 266, measured). Any text
  Wave B adds to `docs/HOOKS.md` or `docs/QUICKSTART.md` is worded for the adopter: no
  self-host `.py` path, no dated measurement, no ledger id.
- This seat's `lane/worktree-seat-resume` follows Wave B and edits
  `tools/cc/session_resume.py`, which Wave B does not touch.
- The parent `TP-479` owns the record-merge rules Wave B extends and Wave D's line;
  `TP-478`'s 2-A is Wave A's, taken over.

## Task 0 — Verify (may end this pack, or Wave B of it)

Each oracle is a command; each refuting result names the exit.

- **0-A Which catch-ups the stored count alone explains.** The census reports blocks in
  aggregate (6 `_count`, 4 entries, 1 rows over 8 conflicted catch-ups) and not per
  catch-up, so the question Wave D's line asks is unanswered: how many of the 8 would have
  merged clean with `_count` gone. Oracle: extend `scripts/merge_cost_census.py` with a
  per-pull-request block listing (`--per-pr`, printed under `blocks`), or by hand replay
  each catch-up with `git merge-tree --write-tree <base> <head>` and read each conflicted
  file's hunks. Refuting result (rate-scaled, the operator's ruling of 2026-10-12): **if
  the catch-ups whose only blocks are `_count` number at least 6 of the 8** (a leftover of
  2 or fewer at 13 merges, the parent's 5-of-30 line scaled to the window), Wave A alone
  passes Wave D as pre-registered, and **Wave B is not built**: this pack ends after Wave A
  and its Landing says so; the fragments question returns to the parent's re-measure at 30.
  Exit otherwise: build Wave B. The first draft's exit, at least 3 of the 8, could not
  fail: the 5 blocks that are not `_count` sit in at most 5 catch-ups, so at least 3 were
  `_count`-only before the oracle ran, and it set a 13-merge count against a 30-merge line.
  **Result, 2026-10-12, two oracles agreeing:** `python scripts/merge_cost_census.py --prs
  14 --per-pr conflicts` (the listing this pack added) and a counterfactual `git
  merge-file` of each conflicted probes file with the `_count` line stripped from base and
  both parents: **4 of the 8** are `_count`-only (#180, #182 one of its four, #184, #192);
  the other 4 each keep one entries block (#186, #187, #188, #191), #188 a ledger
  member-row block beside it. 4 is under 6 (4 leftovers per 13 merges projects to about
  9.2 per 30): **Wave B is built**, as a lane of its own on its own assign, after Wave A.
- **0-B Who reads the two files, and in what shape.** Oracle, the deriving command (the
  lists are its output on one day, not the population):
  `grep -rlE "FORWARD_LEDGER|LEDGER_PROBES" tools/cc scripts espalier --include='*.py' |
  grep -v _vendor` (20 modules today) and the same over `tests` (38 files today). Each
  reader is classed: **rows** (parses member or probe entries: the generator, the probe
  runner, the verbs, the merge, the board, the landing check, the trend, the census, the
  symbol census, the reinject hint), **path** (names the file as a path: the record lists,
  the gitignore re-includes, the inventory, the surface classification, the provenance
  seed), or **whole text at a commit** (`scripts/ledger_trend.py` through `git show`, the
  two rebuild tools). Refuting result: a **rows** reader that needs one file's text and
  cannot take the loader's rendered view. Exit: that reader's record stays a file and the
  pack says which; the parent's Wave C carried the same clause. The filename grep finds a
  reader that names the file; it cannot find one that reaches it through an imported
  constant or a loaded verb module, which is the parent's own blocker shape
  (`ship.lane_carries_memory_row`). So the census also classes every importer of the
  verbs, the generator, the probe runner and the merge (`grep -lE
  'record_merge|ledger_row|generate_ledger_regions|check_ledger_probes' tools/cc/*.py
  tools/cc/hooks/*.py scripts/*.py`, which adds `ship.py`, `mail.py`, `_pack_scope.py`
  and `scripts/check_pack_landing.py` on 2026-10-13), and `espalier/cleanup.py`'s preserved-files loop, which derives its list
  from `cli.REINCLUDED_PATHS` and keeps only `is_file()` entries, so a directory
  re-include reaches it.
- **0-C The loader's time on the hot paths.** The board's `read_ledger_live`, the landing
  check's ledger arms and `check_ledger_probes` read the file on every run; nothing on a
  hook path reads it (`_hook_utils.RECORD_FILES` names the path only). Oracle: a scratch
  script, 50 runs warm, rendering one file against a directory of as many fragments as
  the board counts live rows plus the probes. Refuting result: more than 50 ms added at
  the median to any of the three. Exit: a cached rendered view is out (it would store
  what two lanes recompute); the reader batches through `git cat-file --batch` or the pack
  re-scopes the hot reader. **Result, 2026-10-13:** a prototype render over the post-fold
  worst case (500 member-row fragments with their index lines and 281 probe fragments,
  built from the live ledger at `aa9e745a`) adds 20.6 ms at the median to today's 1.2 ms
  read of the two files, 50 warm runs on the 8 GB self-host box. Under the line: no
  batching needed.
- **0-D The per-commit read.** `scripts/ledger_trend.py::snapshots` lists the
  first-parent commits that touched the file (`git log -- <path>`) and
  `scripts/ledger_trend.py::ledger_at` reads the file at each with `git show
  <commit>:<path>` (snapshots on `origin/main` since 2026-10-04: 75 on 2026-10-12, 83 on
  2026-10-13; a dated reading that grows). Two seams, not one:
  the commit selection must also take a commit that touched only a fragment (a `git log
  -- <path>` walk drops it), and the per-commit read must render the view. Oracle: time
  `git ls-tree -r <commit> -- task-packs/ledger.d` plus one `git cat-file --batch` over
  its blobs, per snapshot, against today's one `show`. Refuting result: the walk over the
  window exceeds 60 s. Exit: the trend reads the legacy file for commits before the fold
  and the directory after, and its header says where the seam is. **Result,
  2026-10-13:** 83 snapshots of a scratch commit holding those 781 fragments, each read
  with `git ls-tree -r`, one `git cat-file --batch` and the file's `git show`, took 10.1 s
  against 1.6 s for today's walk of one `show` each. Under the line: the trend reads both
  forms at every commit, with no seam needed for time (the commit-selection seam stands).
- **0-E The writer conflict that is real.** Two lanes striking or re-pinning one row is
  two writers on one name; `record_merge` refuses a fragment conflict by name (its Wave C
  rule). Oracle: the two-lane test with that shape. Expected: refusal naming the id. This
  is not a refuting result; it is the behaviour to pin.
- **0-F The hand-edit witness's new home.** `TP-478` 2-A's refutation fired there on
  2026-10-09: `ledger_row._load_probes` and `check_ledger_probes` refuse a roster whose
  `_count` disagrees with its list, "a hand edit's only trace". Oracle: `grep -n 'def
  test_every_live_row_is_probed_or_declared' tests/test_forward_ledger_completeness.py` and
  `check_ledger_probes.py::_empty_roster_verdict`. Found 2026-10-12: the full suite already
  derives the live ids against the roster's ids (a hand-deleted entry for a live row reds
  it), and the runner already refuses a roster emptied or renamed while the ledger has live
  rows. What the stored count alone covered: a careless partial loss at run time, and any
  trace on an adopter tree (the completeness test does not ship). Exit, the operator's
  choice 2026-10-12: the runner derives the same comparison on every run and prints a note
  naming each live row with no entry, never a refusal; Wave A builds it.
- **0-G Where two filings collide today.** Read in the code by the 2026-10-13 artifact
  review, not yet driven: `ledger_row.py::file_row` writes three things, the member row
  (after `--after`'s row), an Appendix B index row per id (`::_appendix_b_slot`, after the
  index table's last row) and a roster entry (the list's tail). Oracle: in a scratch
  repository, two branches from one base each `file` a row into one class with the real
  verbs and different `--after` anchors, merged with `git merge-tree --write-tree` and
  every merge driver off; list the conflicted files and each hunk's lines. Expected: a
  conflict at Appendix B's tail and the roster's tail whatever the anchors. Refuting
  result: no Appendix B hunk, in which case the index line is not a collision point and
  the fragment need not carry it; the pack then says which. Neither result ends Wave B:
  this is the red the two-lane test starts from.
  **Result, 2026-10-13** (a scratch clone of `aa9e745a` with no merge-driver config, the
  real verb, rows `DEF-4998` and `DEF-4999` into §C0): after `DEF-4013` and `DEF-4016`,
  two rows apart, `FORWARD_LEDGER.md` merges clean and `LEDGER_PROBES.json` conflicts in
  2 hunks at the roster's tail (the entry's `id` and `row_sha` lines); both after
  `DEF-4016`, the ledger conflicts in 2 hunks, the member row and its Appendix B index
  row, beside the roster's 2. So the expectation was half wrong: `file_row`'s `--after`
  branch inserts the index row after the anchor's own index row, and only a section's
  first row (no `--after`) goes to Appendix B's tail. The index row collides exactly
  where its member row does; the roster collides every time. The fragment still carries
  its index line: on an opted-in tree `--after` places nothing, so an index line left in
  the big file would go to the tail on every filing.

## Relevant memory

Recent pattern, measured: every ledger-record conflict in the last 13 merges was on a
stored total or an adjacent entry, never on a row's prose, and each was resolved by the
ship driver's catch-up rather than by hand. The last two record-shape changes here (Wave
C and its fold) each found their blocker in the sweep of readers, not in the loader:
`ship.lane_carries_memory_row` read only the old file and refused every handoff.

| Entry | Where |
|---|---|
| Parallel work is safe by construction, not by negotiation | `memory/parallel-work-protocol.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| A fixed fail-open can move rather than close | `memory/a-fixed-fail-open-can-move-rather-than-close.md` |
| Derive the list, don't test a hand-written copy of it | `docs/STANDING_PRINCIPLES.md` §14 |
| A hand-written count that moves on ordinary growth is tax | `memory/a-hand-written-count-that-moves-on-ordinary-growth-is-tax.md` |
| GitHub's merge honours no merge driver, so a `.gitattributes` `merge=` row cannot keep a pull request mergeable | `docs/SHARP_EDGES.md`, that section |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| Gates the targeted proofs never show (a new census test is a derived-population row) | `memory/four-gates-the-targeted-proofs-never-show.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "two machines lanes
conflict on the record files merged by shape"` and its two sibling queries (the
hand-written-copy rule, one writer per shared state); re-run them rather than trusting
this list if the pack has been sitting. The last row was added at Wave B's execution by
`python3 tools/cc/hooks/_recall.py "a record moved behind a loader: a reader sweep missed
one reader that still parses the old file"`.

## Implementation

Every fix below is a **fix shape, untested**, built after Task 0, with the refutation
that would show it the wrong shape. Each file named here fires the folder `CLAUDE.md`
ladder and the edit-time advisories at the edit.

### Wave A — `_count` derived *(after Task 0-A has run; its exit decides whether A is the pack)*

- `tools/cc/ledger_row.py::_load_probes` stops reading `_count` as a declared total, stops
  refusing a mismatch (there is nothing to mismatch) and seeds an empty roster without the
  key; `::strike`, `::repin` and `::file_row` (the three writers; `::_commit_both` only
  serializes) write no `_count`, and the key is dropped wherever a load finds it, so the
  first write after the change removes it from the tree. `--reconcile-count` stays
  accepted as a no-op for one release, its help text saying so; its three tests in
  `tests/test_ledger_row.py` (the `strike` refusal with its reconcile, the `file` twin, the
  dry run) are re-aimed at the new contract: a roster carrying a stale `_count` loads, and
  the key is gone after the write. `tests/test_check_ledger_probes.py` loses its count limb
  the same way: `test_a_renamed_probes_key_is_refused` keeps its refusal and re-aims its
  assertion at the empty-roster limb the renamed key now reaches, and the fixtures seeded
  with `"_count": 0` beside live rows are re-checked, their refusal coming from
  `_empty_roster_verdict` as before (re-review, 2026-10-12).
- `tools/cc/check_ledger_probes.py` (the `declared` read), `tools/cc/record_merge.py`
  (`resolve_probes` and the settle step after any merge), `scripts/ledger_rebuild_assemble.py`
  (`load_probes`' refusal and the rebuild's own write) and `scripts/ledger_structural_cut.py`
  (which reaches that refusal through `load_probes`: its docstring sentence, which spells
  `_count` unquoted so the grep below misses it, and its test's `_count` arm) take `len(probes)` where they read or wrote the key. Deriving command for
  the sites: `grep -rnE '"_count"' tools/cc/*.py scripts/*.py espalier/*.py tests/*.py |
  grep -v _vendor` (14 production sites in 6 modules and 7 test files on 2026-10-12). Two of
  the hits stay: `scripts/merge_cost_census.py`'s classifier (below), and
  `scripts/check_handoff_landing.py::check_owed`, which reads the `_count` of `cc/GOAL_OWED.json`,
  the session's owed list: a different record, gitignored, one writer, never conflicted
  (pack-artifact review, 2026-10-12), with `tests/test_check_handoff_landing.py`.
- `scripts/merge_cost_census.py` keeps its `probes: _count` block class so the history
  stays readable, and classifies a block with no `_count` text as entries.
- The probes file's `_README` and `_note` carry no sentence about the count (checked
  2026-10-12), so the file loses the key alone; the generator's stored-count rule
  (`tools/cc/generate_ledger_regions.py`'s "Rows, not totals") gains the probes file as a
  second record it holds to that rule.
- **The hand-edit witness moves** (0-F): `tools/cc/check_ledger_probes.py::_run` derives the
  ledger's live ids (`live_cell_ids`, the generator's one home: every id a live row
  carries, since a co-id owns its own probe) against the roster's ids on every run and
  prints a note naming each live id with no entry. A note, never a refusal: an adopter who
  files a row by hand without a probe gets no new blocker. The total-loss refusal
  (`_empty_roster_verdict`) stays; the full suite's `test_every_live_row_is_probed_or_declared`
  moves to the same cell-id population (keyed on first ids, a co-id's lost entry passed it
  once the count no longer caught it: failure-mode review, driven 2026-10-12).
- **The transition, expand and contract in one pull request.** Old code reads the key
  with `.get()` beside an `isinstance` check, so a file without it breaks no reader; old
  writers write it back, including a lane's own catch-up (the ship driver imports the
  lane's sibling `record_merge.py`, whose settle step read a missing key as drift), and
  GitHub merges that lane in with no settle step. So the live file is pinned:
  `tests/test_forward_ledger_completeness.py::test_the_live_roster_stores_no_total` reds
  such a lane's own CI before the key lands (and a repeated key), naming the one-line
  repair; the dispatcher tells the seats whose lanes were branched before this one.
- **Earn the red:** a test writes a roster with `_count` present and asserts every writer
  removes it and every reader ignores it; mutation: a writer that re-adds the key. The
  two-lane test for this wave: one branch `file`s a row and the other `strike`s a row two
  entries away, merged with drivers off; they must merge clean (today they conflict on the
  count line alone: red against HEAD). Two `file`s still conflict after this wave, on the
  roster's tail and the ledger's adjacent rows (driven 2026-10-12 with the real verbs, a
  correction of this line's first draft, which named that shape): Wave B's shape, pinned
  here as the negative control, with no block on a count. The witness
  note: a roster missing one live row's entry prints the note naming it; mutation: the
  comparison removed. Homes: a `TestProbesCountDerived` class in `tests/test_ledger_row.py`
  for the writers and the two-lane test, `tests/test_check_ledger_probes.py` for the note.
- **Refuted if** a reader needs the count as a declared claim rather than a derivation
  (0-B names it): then that reader derives and compares, and the key still goes. The one
  such reader `TP-478` measured (the hand-edit witness) is answered by 0-F and the bullet
  above.
- Ships as its own pull request with the approval marker (`tools/cc/` changes), the
  `espalier/_vendor/cc/` twins re-synced (`python3 scripts/sync_vendor_cc.py`), the full
  tier, and both reviewers on a snapshot clone.

### Wave B — fragments behind the loader (expand) *(built: 0-A decided it; corrected 2026-10-13)*

Every bullet below is a **fix shape, untested**, except where a measurement is cited.

- **The opt-in** (operator, 2026-10-13). A top-level `ledger_fragments = true` in
  `espalier.toml` turns the writers to fragments. It is read by the same line scan as
  `tools/cc/_record_fragments.py::changelog_fragments_setting`, one reader for both keys,
  since the 3.10 floor has no `tomllib`. The key joins
  `espalier/config.py::FOREIGN_KEYS` (its reader, for the census) and
  `espalier/cli.py::_FOREIGN_KEY_SENTENCES`, or every config load on an opted-in tree
  warns of an unknown key; `tests/test_config_fields_consumed.py` and
  `tests/test_cli_deploy.py` pin that registry. This repository sets it in this wave. Off, the
  default and every adopter tree's state, the verbs write the big file as they do today.
  The loader reads both directories wherever they exist, setting or not, so a fragment
  written before the setting went off never leaves the view. Precedent: changelog
  fragments became a repository's opt-in after the review of #179 (`464edc23`, merged
  in #182); Scope (out)'s one-seat adopter has no conflict to cure.
- **A fragment.** `task-packs/ledger.d/<id>.md`, where `<id>` is the row's FIRST id as the
  verb minted it, never typed:
  - line 1 is `<!-- class: §C0 -->`, the class as a field, since the directory is flat;
  - line 2 is the member row in today's grammar
    (`| `DEF-n` | site | text | severity | population | audience |`). A co-id row carries
    every id; a struck row carries its `~~` and its CLOSED text.
  - then one Appendix B index line per id the row carries (`| `DEF-n` | §C0 | site |`,
    struck with the row) (operator, 2026-10-13).

  `task-packs/probes.d/<id>.json` holds one probe object per file, one file per id (a
  co-id owns its own probe, `generate_ledger_regions.py::live_cell_ids`), and the object's
  `id` equals the name. A file under either directory whose name is not `<id>.md` or
  `<id>.json` for an id-shaped `<id>` (`generate_ledger_regions.py::_ID_SHAPE`) is not
  read, and the loader says it skipped it.
- **The view, in memory only** (operator, 2026-10-13; Core Rule 15).
  `tools/cc/_record_fragments.py` gains two functions:
  - `ledger_text(root)` returns the big file's text with each fragment's member row
    appended to its class's member table (after the table's last row; under the header
    rule when the class has none) and each fragment's index lines appended to Appendix B's
    table. Fragments go in id order (kind, number, suffix), after the legacy rows in file
    order.
  - `probe_roster(root)` returns the big roster's object with `probes` set to the legacy
    list followed by each `probes.d` object in id order.

  Pure cores taking texts (`ledger_text_from_texts`, `probe_roster_from_texts`, the shape
  `rows_from_texts` set) serve a reader of another commit and the pending view a writer
  converges against. `fragment_for(root, id)` names the fragment whose member row
  carries `id` in its id cell, whatever its position there (a scan of each fragment's
  member line through `generate_ledger_regions.py::cell_ids`), so `strike`, `repin` and
  `_index_line` address a co-id row by any of its ids, as they do a legacy row, and the
  second-home refusal below asks the same question. Today's readers parse the view
  unchanged; that is the design. They keep `generate_ledger_regions.py`'s grammar and take
  a different text. Nothing writes the view. `generate_ledger_regions.py --write` writes
  the regions it writes today and never puts a fragment's row into the file, while
  `--check` and `--print` derive from the view. A fragment naming a class the file has no
  section for is a `--check` problem, never dropped silently. A `ledger` verb on the
  loader's CLI prints the view for a person. The big file's contract section ("How this
  file defends itself") names the two directories and that verb, since someone reading
  the file on GitHub sees the legacy rows only.
- **Writers, on an opted-in tree.** `file` writes `ledger.d/<id>.md` and
  `probes.d/<id>.json` and touches neither the big file nor the roster. A fragment has
  no position, because the view orders by id, so `--after` places nothing there: the
  verb accepts it and says so, rather than refusing a scripted call. `strike` and `repin`
  rewrite a fragment row's own files (member line, index lines, probe); for a legacy row
  they edit the big file and the roster as today, since legacy rows move only at the
  fold. `class` (`ledger_row.py::new_class`) still writes the big file: a heading and its
  class-index row are prose the fold keeps (two `class` calls in one window conflict as
  today, not measured in the census window). The verbs refuse a second home for one id,
  naming both: a fragment whose id also stands in the legacy table, or two fragments
  carrying one id. `ledger_row.py::_commit_both` writes the fragment pair under the
  ledger lock as it writes the two files today.
- **The generator and the convergence step** (re-review, 2026-10-13: the BLOCK the first
  correction left). `generate_ledger_regions.py::find_drift` reads probe ids through
  `::_probe_ids`, which opens the module global `_PROBES` as a file, and
  `::_run_unlocked` reads `_LEDGER` directly; `ledger_row.py::_converge` (inside
  `::_commit_both`) and `record_merge.py::regenerate_ledger` point `_PROBES` at a roster
  path and call `find_drift`. None of them would see a fragment. Fix shape, untested:
  - `find_drift` takes its probe ids as an argument (callers pass `probe_roster`'s ids,
    or a pending roster's).
  - `_run_unlocked` reads the view for `--check` and `--print`, and its anti-vacuity
    floors (`declared_floors` against the counted sections and rows) read the view too,
    or they red once the fold empties the big file's tables.
  - `_commit_both` builds the PENDING view through the `*_from_texts` cores with the new
    or rewritten fragment pair added, converges against it, and writes the fragment pair
    (or the big file and roster, for a legacy row or a tree that has not opted in) only
    when it converges.
  - `regenerate_ledger` works on the merge's own texts (the temporary merged ledger and
    roster it is handed, plus the merged tree's fragments) through the same cores, never
    a root-based read, which would read the wrong tree mid-merge.
  - The repair step: `apply_writable` (verified 2026-10-13) ignores each drift item's
    `line` and only strips stored totals from the text it is handed, by regex over
    prose, headers and the class index. So drift is taken from the view and read by
    `region` only, `apply_writable` runs on the big file's own text, the pending view is
    rebuilt from the rewritten big file plus the fragments, and `find_drift` runs again;
    a residual `stored-count` item is the refusal. A drift item's `line` is
    view-relative, for display only.

  Refuted if a writable region the generator still writes is derived from member rows
  in a way the big file alone cannot hold (then the region moves to the view's
  `--print`, as the totals did on 2026-10-09).
- **Readers move to the loader**, one at a time, each with its row in the reader census:
  - the probe runner: `check_ledger_probes.py::_run`, `::unprobed_live_ids` and
    `::_empty_roster_verdict` take the roster from `probe_roster`. `::run_probe` takes a
    probe and reads no roster.
  - the verbs: `ledger_row.py` reads rows and probes through the loader.
  - `record_merge`'s ledger and probes arms keep the legacy forms and gain the by-name
    refusal for a fragment conflict (0-E). The legacy arms stay for good: the deployed
    `record_merge.py` and `ledger_row.py` serve adopter trees, which keep one file by
    Scope (out); on this tree they become unreachable after the fold. Only
    `record_merge.py::settle_probes_count`, Wave A's one-release shim for lanes branched
    before it, retires (at Wave C).
  - the board's `read_ledger_live` (it returns None when the file is absent; the file
    stays after the fold, holding prose and headers) and the landing check's
    `scripts/check_handoff_landing.py::ledger_prefixes`, which reads the ledger's lead
    cells directly.
  - `scripts/ledger_trend.py`: `::snapshots` selects commits that touched the file or
    either directory, and `::ledger_at` renders the view at a commit through the pure core
    (0-D's two seams).
  - `scripts/symbol_census.py` and `scripts/derived_population_census.py`, where they read
    row ids.
  - `tools/cc/hooks/_reinject.py::_render_ledger_parser`: its hint names the directory
    beside the file.
  - `tests/test_forward_ledger_completeness.py`: a pack is pinned when any fragment or
    legacy row names it.

  Each importer 0-B adds is either moved or given its reason. The two rebuild tools are
  one-off and read the legacy file by design; they carry a reason, not a move.
- **The record lists and the name predicates.** `ci_guard._RECORD_FILES`,
  `_hook_utils.RECORD_FILES`, `record_merge.ROSTER` and the loader's `FRAGMENT_DIRS` gain
  `task-packs/ledger.d/` and `task-packs/probes.d/`, and the parity pins compare them.
  The fragment-name test is per directory from this wave on. Today the date-led `.md`
  pattern is hand-copied in `ci_guard.py::_FRAGMENT_NAME_RE`,
  `_hook_utils.py::_FRAGMENT_NAME_RE` and `record_merge.py::_FRAGMENT_NAME_RE`, beside
  `_record_fragments`' own two name patterns, and `tests/test_ci_guard.py::TestRecordFileMarkers`
  pins the copies equal. That becomes a directory-to-pattern map, and the pin compares
  the maps. `ci_guard`'s conflict-marker scan, which reads fragment `*.md` files only,
  reads the `.json` fragments too.
- **Tracking and shipping.**
  - The self-host `.gitignore` re-includes the two directories, with its hand copy in
    `docs/QUICKSTART.md`. Its `task-packs/*` block re-includes by name, so without this a
    fragment is silently untracked while `file` reports success: measured 2026-10-13 with
    `git check-ignore -v`, which matched `task-packs/*` for both shapes.
  - `espalier/cli.py::GITIGNORE_REINCLUDES` gains them for an adopter who opts in;
    `tests/test_init_gitignore_default.py` pins the block's last entry, so that pin moves.
    `upgrade --execute` delivers the block to an installed tree.
  - `espalier/surface_contract.py::SHIPPED_TASK_PACK_FILES` is a file allow-list. The two
    directories join the ship set by prefix, since the ledger they complete ships
    (`is_local_only("task-packs/ledger.d/DEF-1.md")` returned True at `aa9e745a`,
    measured 2026-10-13).
  - `espalier/cleanup.py`'s preserved-files loop is told about directories.
  - The engine's other path sites (the export loop beside `cli.py::get_seed_docs`, and
    `managed_inventory`'s lists) take the two directories where 0-B classes them as path
    readers, or carry the reason they do not. The adopter seed stays one file (Scope
    (out)).
- **The class census, the gate this wave adds.** `tests/test_ledger_fragments.py` holds
  every module that applies a row regex or `json.loads` to either file, or reaches it
  through an imported constant or verb module, to calling the loader or carrying a
  declared reason. The census is derived by AST over `tools/cc`, `scripts`, `espalier`
  and `tests`; a new reader that opens the file for rows reds. Its loop over a source
  population is a `scripts/derived_population_census.py` row (the adjudicated entry is
  printed by `--print-adjudicated-entry`).
- **Earn the red, each mutation named before its test.** Before the fold no live row is a
  fragment, so the two-lane tests build their fragments with the real verbs in a scratch
  repository that opts in. The tests and their mutations:
  - The two-lane tests, two branches from one base: two `file`s into one class, and a
    `strike` of each of two adjacent fragment rows. `git merge-tree --write-tree` with
    every driver off merges each pair clean, and the view equals both writes applied in
    either order. Red against HEAD at 0-G's hunks.
  - The negative control: two `strike`s of adjacent LEGACY rows still conflict until
    Wave C.
  - Loader mutations, each red: dropping the legacy rows; dropping the fragments;
    dropping a fragment's index line from Appendix B's view; reading a stray file as a
    row; misreading a struck fragment as live.
  - Writer mutations, each red: a writer on an opted-in tree writing the big file; a
    writer on a tree that has not opted in writing a fragment; the verbs writing a second
    home for one id.
  - The rest: a directory missing from one of the record lists; a `.json` fragment
    skipped by the marker scan; a reader module that regexes the file directly (the
    census); the probe runner counting a probe whose row fragment is struck as live
    coverage.
- **Ships as** its own pull request with the approval marker in the title
  (`tools/cc/hooks/_hook_utils.py`, `tools/cc/hooks/_reinject.py` and `tools/cc/ci_guard.py`
  are gated paths). It carries the `espalier/_vendor/cc/` twins re-synced (`python3
  scripts/sync_vendor_cc.py`) and the asset docs re-synced after `docs/HOOKS.md` or
  `docs/QUICKSTART.md` changes (`python3 scripts/sync_asset_docs.py`). Proof is the full
  tier, with both reviewers on a snapshot clone.
- **Refuted if** 0-B names a rows reader that cannot take the view, or 0-C's time line is
  crossed on a hot reader with no batching available.

### Wave C — the fold (contract)

- Every legacy member row becomes `ledger.d/<id>.md` with its class field and its
  Appendix B index lines; every legacy probe becomes `probes.d/<id>.json`; the class
  tables and Appendix B in the big file keep their headers and lose their rows, which the
  loader's view supplies (never written back: Wave B's in-memory rule, operator
  2026-10-13); `LEDGER_PROBES.json` becomes `task-packs/probes.d/README.md` carrying the
  roster's `_README` and `_note` prose. The rows read the same before and after through
  the loader (a test compares the two views byte for byte at the fold commit). Whether a
  person reading the file on GitHub needs more than the contract section's pointer is
  re-raised at the fold, not decided here.
- Gated on `python tools/cc/board.py` showing no open pull request whose files include
  either record; the fold is one commit by one seat. The record merge's legacy arms
  stay (adopter trees keep one file, Scope (out)); only Wave A's
  `record_merge.py::settle_probes_count` shim retires here.
- The roster's removal is this tree's alone: an adopter keeps `LEDGER_PROBES.json`, so the
  engine's and `tools/cc`'s references to it stay (`grep -rn LEDGER_PROBES espalier
  tools/cc --include='*.py'` derives them: `cli.py::GITIGNORE_REINCLUDES`,
  `surface_contract.py::SHIPPED_TASK_PACK_FILES`, the record lists, the generator's
  `_PROBES`, among others), and the loader, `ledger_row.py::_load_probes` and the probe
  runner read a missing roster as an empty legacy list beside `probes.d/`. The fold
  sweeps this tree's own references (the docs that name the file, the self-host
  `.gitignore`) and records the self-host-only removal as `surface-impact`'s accepted gap,
  with that reason.
- **Refuted if** the gate never opens within a day of Wave B merging: then the fold ships
  behind a catch-up of the one open lane, by that lane's seat, as Wave C's review batch did.

### Wave D — the re-measure

- `python scripts/merge_cost_census.py --prs 30 catch-ups conflicts blocks` over the first
  30 pull requests merged after the fold, with 0-A's per-pull-request listing. Pass: 5 or
  fewer conflicted catch-ups. Reported beside the parent's own Wave D reading at its 30.

## Affected symbols

### Changed-semantics

- `tools/cc/ledger_row.py::_load_probes` (no declared total; both forms read)
- `tools/cc/ledger_row.py::_commit_both` (Wave B: writes a fragment per touched row)
- `tools/cc/ledger_row.py::strike`
- `tools/cc/ledger_row.py::repin`
- `tools/cc/ledger_row.py::file_row`
- `tools/cc/ledger_row.py::new_class` (Wave B: unchanged writer of the big file, named so the census sees it)
- `tools/cc/ledger_row.py::_appendix_b_slot` (Wave B: a fragment row's index lines live in its file)
- `tools/cc/ledger_row.py::_index_line` (Wave B: finds a fragment's index line as well as a legacy one)
- `tools/cc/check_ledger_probes.py::_empty_roster_verdict` (its roster comes from the loader)
- `tools/cc/check_ledger_probes.py::unprobed_live_ids` (its roster comes from the loader)
- `tools/cc/record_merge.py::resolve_probes` (no `_count`; legacy form only)
- `tools/cc/record_merge.py::settle_probes_count` (Wave A's shim; retires at Wave C, while the legacy arms stay)
- `tools/cc/record_merge.py::regenerate_ledger` (a pending view from the merge's own texts; repairs the big file's own text only)
- `tools/cc/generate_ledger_regions.py::apply_writable` (unchanged; run on the big file's text, never the view)
- `tools/cc/ledger_row.py::_converge` (converges against the pending view)
- `tools/cc/generate_ledger_regions.py::find_drift` (probe ids as an argument)
- `tools/cc/generate_ledger_regions.py::_probe_ids` (the roster comes from the loader)
- `tools/cc/generate_ledger_regions.py::_run_unlocked` (checks the view)
- `scripts/check_handoff_landing.py::ledger_prefixes` (reads the view)
- `espalier/config.py::FOREIGN_KEYS` (`ledger_fragments` declared)
- `espalier/cli.py::_FOREIGN_KEY_SENTENCES` (`ledger_fragments` named)
- `tools/cc/record_merge.py::resolve_ledger_hunk`
- `tools/cc/record_merge.py::ROSTER`
- `tools/cc/record_merge.py::_FRAGMENT_NAME_RE` (one pattern per directory)
- `tools/cc/generate_ledger_regions.py::live_member_ids` (reads the view)
- `tools/cc/generate_ledger_regions.py::appendix_b_strike_state` (reads the view)
- `tools/cc/board.py::read_ledger_live`
- `tools/cc/ci_guard.py::_RECORD_FILES`
- `tools/cc/ci_guard.py::_FRAGMENT_NAME_RE` (one pattern per directory; the marker scan reads `.json`)
- `tools/cc/hooks/_hook_utils.py::RECORD_FILES`
- `tools/cc/hooks/_hook_utils.py::_FRAGMENT_NAME_RE` (one pattern per directory)
- `tools/cc/hooks/_reinject.py::_render_ledger_parser`
- `tools/cc/_record_fragments.py::FRAGMENT_DIRS`
- `tools/cc/_record_fragments.py::changelog_fragments_setting` (one top-level-key reader for both settings)
- `scripts/ledger_trend.py::snapshots` (selects commits that touched the file or either directory)
- `scripts/ledger_trend.py::ledger_at` (renders the view at a commit)
- `espalier/surface_contract.py::SHIPPED_TASK_PACK_FILES` (the two directories ship by prefix)
- `espalier/cleanup.py::clean_generated_surface` (the preserved-files loop takes a directory re-include)
- `scripts/ledger_rebuild_assemble.py::load_probes` (Wave A: no mismatch refusal)
- `tools/cc/check_ledger_probes.py::_run` (Wave A: no `declared` read; the witness note)
- `scripts/merge_cost_census.py::classify_block` (an entries block with no `_count` text)
- `scripts/merge_cost_census.py::replay_all` (the per-pull-request block listing 0-A adds)
- `espalier/cli.py::GITIGNORE_REINCLUDES`

### Renamed

- (none)

### Added-paths

- `tools/cc/_record_fragments.py::ledger_text`
- `tools/cc/_record_fragments.py::ledger_text_from_texts`
- `tools/cc/_record_fragments.py::probe_roster`
- `tools/cc/_record_fragments.py::probe_roster_from_texts`
- `tools/cc/_record_fragments.py::ledger_fragments_setting`
- `tools/cc/_record_fragments.py::fragment_for`
- `tests/test_ledger_fragments.py`
- `task-packs/ledger.d/` (Wave B; populated by the fold)
- `task-packs/probes.d/` (Wave B; populated by the fold)

### Removed-paths

- `task-packs/LEDGER_PROBES.json` (Wave C; its prose moves to `task-packs/probes.d/README.md`)

## Reach

Members derived by: `python scripts/merge_cost_census.py --prs 13 blocks` (the conflict
block classes on the two records since Wave C; the roster is the census's output on the
day, not this table).

| Item | Status | Evidence owed |
|---|---|---|
| `probes: _count` (6 of 11 blocks) | **CLOSED by Wave A** | the two-lane `file`/`strike` test merges clean with drivers off; no reader or writer names the key (the grep above returns the census classifier and the owed-list check of `cc/GOAL_OWED.json`, a different record) |
| `probes: entries` (4 of 11) | **CLOSED by Wave B + C** | the two-lane `file`/`strike` test merges clean; an entry lives in one file |
| `ledger: member rows` (1 of 11) | **CLOSED by Wave B + C** | the same test over two rows in one class |
| ledger prose and generated regions (0 of 11) | **NOT REACHED** | no member in the window; stays in the file by Scope (out) |
| two writers on one row | **NOT REACHED, by design** | a real conflict; `record_merge` refuses it by name (0-E pins the refusal) |
| `scripts/derived_population_census.py` (0 of 11 here, 3 of 27 in the parent's window) | **NOT REACHED** | the parent's decision 2(a); its own row `DEF-4010` |

## Pass criteria

- **The two-lane test** passes on the real writers: for Wave A, a `file` on one branch
  and a `strike` of a row two entries away on the other; for Wave B, on a scratch
  repository that sets `ledger_fragments = true`, two `file`s into one class and a
  `strike` of each of two adjacent fragment rows; `git merge-tree --write-tree` with
  every driver off merges clean (Appendix B and the roster included) and the loader's
  view equals both writes applied in either order. It is red against the tree before
  each wave (0-G's hunks for Wave B). The negative control stays pinned: two `strike`s of
  adjacent legacy rows still conflict until Wave C.
- **The opt-in holds both ways:** on a tree without `ledger_fragments = true` the verbs
  write the big file and the roster byte-for-byte as before Wave B; on a tree with it,
  they write only fragments; the loader reads both forms on either.
- **Nothing writes the view:** after any verb and after `generate_ledger_regions.py
  --write`, no fragment's member or index line appears in `FORWARD_LEDGER.md`.
- **The fragments are tracked and ship:** `git check-ignore` matches neither directory on
  this tree, and `surface_contract.is_local_only` is False for a fragment path.
- **No stored total in either record:** no `_count` key anywhere a writer writes, and
  `generate_ledger_regions.py --check` reports no stored count in the ledger; a test keeps
  both.
- **Every reader in the census** (0-B's command) calls the loader or carries a declared
  reason, pinned by `tests/test_ledger_fragments.py`; a reader that applies a row regex to
  the file directly reds.
- **No assertion weakened, no sample removed:** the probe runner's verdict classes, the
  completeness test's population, the structural pins of `tests/test_check_ledger_probes.py`
  and `tests/test_ledger_row.py` keep their strength; a fixture may change shape, never
  what it refuses.
- **The fold is byte-faithful:** the loader's view before and after the fold commit is
  equal row for row, pinned at that commit.
- **The three lists agree:** the parity pins over `_RECORD_FILES`, `RECORD_FILES` and
  `ROSTER` pass with the two directories.
- **Wave D:** 5 or fewer conflicted catch-ups over the 30 merges after the fold, by the
  census, reported beside the parent's reading.
- The repository's test command (`python scripts/proof_tier.py --run`, the full tier) is
  green on each wave's pull request; the mirrors byte-equal (`python scripts/sync_vendor_cc.py
  --check`); `python -m espalier provenance .` clean.

## Files touched

- **New:** `tests/test_ledger_fragments.py`; `task-packs/ledger.d/` and `task-packs/probes.d/`
  (Wave B creates them, Wave C populates them); `task-packs/probes.d/README.md` (Wave C).
- **Modified:** `tools/cc/_record_fragments.py`, `tools/cc/ledger_row.py`,
  `tools/cc/check_ledger_probes.py`, `tools/cc/generate_ledger_regions.py`,
  `tools/cc/record_merge.py`, `tools/cc/board.py`, `tools/cc/ci_guard.py`,
  `tools/cc/hooks/_hook_utils.py`, `tools/cc/hooks/_reinject.py` and their
  `espalier/_vendor/cc/` twins; `scripts/ledger_trend.py`, `scripts/merge_cost_census.py`,
  `scripts/ledger_rebuild_assemble.py` (Wave A's read and write; a reason for its legacy
  read), `scripts/ledger_structural_cut.py` (Wave A's docstring and test; a reason),
  `scripts/symbol_census.py`, `scripts/derived_population_census.py`,
  `scripts/check_handoff_landing.py` (Wave B: its ledger arms read the view; the `_count`
  `::check_owed` reads is `cc/GOAL_OWED.json`'s and stays); `espalier/cli.py`,
  `espalier/surface_contract.py`, `espalier/managed_inventory.py`, `espalier/cleanup.py`,
  `espalier/config.py` (the `ledger_fragments` key; `tests/test_config_fields_consumed.py`
  and `tests/test_cli_deploy.py` pin the registry),
  `espalier/scanners/subprocess_contracts.py` (its comment);
  `task-packs/FORWARD_LEDGER.md` (the contract section "How this file defends itself" names
  the fragments and the view's verb; Wave C folds the rows), `task-packs/LEDGER_PROBES.json`
  (Wave A drops the key; Wave C retires the file); `espalier.toml` (Wave B: `ledger_fragments
  = true`); `.gitignore` and `docs/QUICKSTART.md` (Wave B: the two re-includes, then
  `python3 scripts/sync_asset_docs.py`); `memory/parallel-work-protocol.md` (the record
  list); `docs/HOOKS.md` where it names the record files; `tests/test_ci_guard.py` (the
  per-directory name-pattern pin), `tests/test_init_gitignore_default.py` (the block's
  last entry), and the test files 0-B's command lists, each by its own row.
- **Deleted:** `task-packs/LEDGER_PROBES.json` at Wave C.
- **Unmodified on purpose:** `espalier/assets/seed/FORWARD_LEDGER.md` (the adopter's seed
  stays a file; Scope (out)); `memory/session-log.d/` and `changelog.d/` (Wave C's records,
  untouched); `tests/test_record_fragments.py`'s Session Log rows (the ledger census is its
  own file, so the two gates stay readable); `espalier/provenance_census.py` (its one
  ledger entry is the adopter seed, which stays a file: artifact review, 2026-10-13).

## Sub-task ordering

0. **Task 0** (0-A to 0-G), half a day; 0-A's exit may end the pack after Wave A; 0-B to
   0-D and 0-G run again at Wave B's start, on the tree Wave B is built on.
   Checkpoint: the per-pull-request block listing committed with the census change, and
   the reader census pasted into this pack's Landing as the day's output.
1. **Wave A**, the smallest change: the key goes, the readers derive, the two-lane probe
   test lands red then green. Checkpoint: the full tier, both reviewers, one pull request.
2. **Wave B**, in this order: 0-G's red first (the two-lane tests, red at HEAD); the
   setting and the loader's view with its own tests; the writers behind the setting; the
   record lists, name predicates, tracking and shipping; the reader sweep, one reader per
   commit where that helps the review; the census test last, so it reds on any reader the
   sweep left. Checkpoint: the census test green, the two-lane tests green, the full
   tier, the marker in the title.
3. **Wave C**, the fold, gated on the board; same day where the gate allows.
   Checkpoint: the byte-faithful view test at the fold commit, the full tier.
4. **Red-team** both reviewers on a snapshot clone at each pull request; the failure-mode
   lens goes first to the reader sweep (the parent's own blocker was there).
5. **Wave D**, the re-measure, over the following 30 merges; written into this pack's
   Landing and the parent's.

## Estimated effort

- Task 0: half a day (0-A is the unknown: the census extension or 12 hand replays).
- Wave A: half a day (the key, the no-op flag, the witness note, seven test files), plus a
  full tier and two reviews.
- Wave B: 2.5 days (the loader and its index lines in half a day; the writers behind the
  setting half a day; the sweep is the modules and test files 0-B's commands list, most of
  them a changed import and a fixture; the per-directory name patterns, tracking and
  shipping a few hours). Raised from 2 at the 2026-10-13 correction, which added Appendix
  B, the opt-in and the registrations.
- Wave C: half a day, plus the tier.
- Red-team: half a day across the three pull requests.
- Wave D: calendar time, no seat.
- Total: 4 to 4.5 seat-days, of which Task 0 and Wave A (about 1) are spent.

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
