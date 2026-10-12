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
  live ledger row under `task-packs/ledger.d/`, one file per probe under
  `task-packs/probes.d/`; the loader renders the view today's readers parse; the readers
  move to the loader; the writers (`ledger_row.py file`, `strike`, `repin`, `class`)
  write fragments; the legacy rows in the big file are read beside them.
- **Wave C — the fold (contract).** The legacy rows become fragments, the big file keeps
  its prose and its generated regions, the probes file becomes its README. Gated on the
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
  pack says which; the parent's Wave C carried the same clause.
- **0-C The loader's time on the hot paths.** The board's `read_ledger_live`, the landing
  check's ledger arms and `check_ledger_probes` read the file on every run; nothing on a
  hook path reads it (`_hook_utils.RECORD_FILES` names the path only). Oracle: a scratch
  script, 50 runs warm, rendering one file against a directory of as many fragments as
  the board counts live rows plus the probes. Refuting result: more than 50 ms added at
  the median to any of the three. Exit: a cached rendered view is out (it would store
  what two lanes recompute); the reader batches through `git cat-file --batch` or the pack
  re-scopes the hot reader.
- **0-D The per-commit read.** `scripts/ledger_trend.py::snapshots` reads the file at
  each first-parent commit with `git show <commit>:<path>` (75 snapshots on `origin/main`
  since 2026-10-04). Oracle: time `git ls-tree -r <commit> -- task-packs/ledger.d` plus
  one `git cat-file --batch` over its blobs, per snapshot, against today's one `show`.
  Refuting result: the walk over the window exceeds 60 s. Exit: the trend reads the
  legacy file for commits before the fold and the directory after, and its header says
  where the seam is.
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

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "two machines lanes
conflict on the record files merged by shape"` and its two sibling queries (the
hand-written-copy rule, one writer per shared state); re-run them rather than trusting
this list if the pack has been sitting.

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
  `scripts/check_handoff_landing.py:640`, which reads the `_count` of `cc/GOAL_OWED.json`,
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

### Wave B — fragments behind the loader (expand) *(built only if 0-A says so)*

- **The loader, `tools/cc/_record_fragments.py`,** gains `ledger_rows(root)`: the member
  rows of `task-packs/ledger.d/*.md`, one row line per file in today's grammar
  (`| `DEF-n` | site | text | severity | population | audience |`, struck rows with their
  `~~` and CLOSED text as today), then the legacy rows still in `FORWARD_LEDGER.md`'s
  class tables, each tagged with its class section; and `probe_entries(root)`: the
  objects of `task-packs/probes.d/*.json`, then the legacy list. `rows_from_texts`'s
  pure-core shape repeats for both, so a reader of another commit can hand in texts.
  Names: `ledger.d/<id>.md` and `probes.d/<id>.json`, the id the verb minted, never
  typed; the class a row belongs to is a field in the fragment's first line
  (`<!-- class: C0 -->`), since the directory is flat and the class table is rendered.
- **The rendered view.** `tools/cc/generate_ledger_regions.py` already derives every total
  from member rows; it gains the fragments as a row source and renders each class's member
  table from them, so the big file's class sections hold prose and a generated table.
  Nothing it renders is stored: `--write` writes the regions as today, and a stored copy
  of a fragment's row in the file is drift it removes.
- **Readers move to the loader**, one at a time, each with its row in the reader census:
  the probe runner; the verbs (`ledger_row.py` reads rows and probes through the loader
  and writes one fragment per touched row); `record_merge`'s ledger and probes arms
  shrink to the legacy forms plus the by-name refusal for a fragment conflict; the board's
  `read_ledger_live`; the landing check's ledger arms; `scripts/ledger_trend.py` (0-D's
  seam); `scripts/symbol_census.py` and `scripts/derived_population_census.py` where they
  read row ids; `tools/cc/hooks/_reinject.py::_render_ledger_parser` (its hint names the
  directory beside the file); `tests/test_forward_ledger_completeness.py` (a pack is
  pinned when any fragment or legacy row names it). The two rebuild tools are one-off and
  read the legacy file by design; they carry a reason, not a move.
- **The three record lists** (`ci_guard._RECORD_FILES`, `_hook_utils.RECORD_FILES`,
  `record_merge.ROSTER`) and the loader's `FRAGMENT_DIRS` gain `task-packs/ledger.d/` and
  `task-packs/probes.d/`, the parity pins compare them, and the fragment predicates take
  the two name shapes (`<id>.md`, `<id>.json`).
- **The engine's path sites** (`espalier/cli.py::GITIGNORE_REINCLUDES`, the export line
  loop beside `get_seed_docs`, `surface_contract`'s internal paths,
  `managed_inventory`'s seed map) take the two directories beside the two files.
- **The class census, the gate this wave adds.** `tests/test_ledger_fragments.py` holds
  every module that applies a row regex or `json.loads` to either file to calling the
  loader or carrying a declared reason, derived by AST over `tools/cc`, `scripts`,
  `espalier` and `tests`; a new reader that opens the file for rows reds.
- **Earn the red, each mutation named before its test:** the two-lane test (two branches
  from one base: one `file`s a row, the other `strike`s a different row; `git merge-tree`
  with drivers off merges clean and the rendered view equals both writes in either order;
  red against today's single table); the loader dropping the legacy rows, dropping the
  fragments, reading a stray file as a row, mis-reading a struck fragment as live; the
  verbs writing a second file for one id; a directory missing from one of the three lists;
  a reader module that regexes the file directly (the census); the probe runner counting a
  probe whose row fragment is struck as live coverage.
- **Refuted if** 0-B names a rows reader that cannot take the view, or 0-C's time line is
  crossed on a hot reader with no batching available.

### Wave C — the fold (contract)

- Every legacy member row becomes `ledger.d/<id>.md` with its class field; every legacy
  probe becomes `probes.d/<id>.json`; the class tables in the big file become generated
  regions; `LEDGER_PROBES.json` becomes `task-packs/probes.d/README.md` carrying the
  roster's `_README` and `_note` prose. The rows read the same before and after through
  the loader (a test compares the two views byte for byte at the fold commit).
- Gated on `python tools/cc/board.py` showing no open pull request whose files include
  either record; the fold is one commit by one seat, and the record merge's legacy arms
  are retired in the same pull request or the next, never earlier.
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
- `tools/cc/check_ledger_probes.py::run_probe` (its roster comes from the loader)
- `tools/cc/record_merge.py::resolve_probes` (no `_count`; legacy form only)
- `tools/cc/record_merge.py::resolve_ledger_hunk`
- `tools/cc/record_merge.py::ROSTER`
- `tools/cc/generate_ledger_regions.py::live_member_ids` (fragments as a row source)
- `tools/cc/board.py::read_ledger_live`
- `tools/cc/ci_guard.py::_RECORD_FILES`
- `tools/cc/hooks/_hook_utils.py::RECORD_FILES`
- `tools/cc/hooks/_reinject.py::_render_ledger_parser`
- `tools/cc/_record_fragments.py::FRAGMENT_DIRS`
- `scripts/ledger_trend.py::snapshots` (the seam at the fold commit)
- `scripts/ledger_rebuild_assemble.py::load_probes` (Wave A: no mismatch refusal)
- `tools/cc/check_ledger_probes.py::_run` (Wave A: no `declared` read; the witness note)
- `scripts/merge_cost_census.py::classify_block` (an entries block with no `_count` text)
- `scripts/merge_cost_census.py::replay_all` (the per-pull-request block listing 0-A adds)
- `espalier/cli.py::GITIGNORE_REINCLUDES`

### Renamed

- (none)

### Added-paths

- `tools/cc/_record_fragments.py::ledger_rows`
- `tools/cc/_record_fragments.py::probe_entries`
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
  and a `strike` of a row two entries away on the other; for Wave B, two `file`s into one
  class and a `strike` of each of two adjacent rows; `git merge-tree --write-tree` with every driver off merges clean
  and the loader's rendered view equals both writes applied in either order. It is red
  against the tree before each wave (the earn-the-red line).
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
  `scripts/symbol_census.py`, `scripts/derived_population_census.py`; `espalier/cli.py`,
  `espalier/surface_contract.py`, `espalier/managed_inventory.py`,
  `espalier/provenance_census.py`, `espalier/scanners/subprocess_contracts.py` (its comment);
  `task-packs/FORWARD_LEDGER.md` (the contract section "How this file defends itself" names
  the fragments; Wave C folds the rows), `task-packs/LEDGER_PROBES.json` (Wave A drops the
  key; Wave C retires the file); `memory/parallel-work-protocol.md` (the record list);
  `docs/HOOKS.md` where it names the record files; the 38 test files 0-B lists, each by
  its own row.
- **Deleted:** `task-packs/LEDGER_PROBES.json` at Wave C.
- **Unmodified on purpose:** `espalier/assets/seed/FORWARD_LEDGER.md` (the adopter's seed
  stays a file; Scope (out)); `memory/session-log.d/` and `changelog.d/` (Wave C's records,
  untouched); `tests/test_record_fragments.py`'s Session Log rows (the ledger census is its
  own file, so the two gates stay readable); `scripts/check_handoff_landing.py` (the
  `_count` it reads is `cc/GOAL_OWED.json`'s).

## Sub-task ordering

0. **Task 0** (0-A to 0-E), half a day; 0-A's exit may end the pack after Wave A.
   Checkpoint: the per-pull-request block listing committed with the census change, and
   the reader census pasted into this pack's Landing as the day's output.
1. **Wave A**, the smallest change: the key goes, the readers derive, the two-lane probe
   test lands red then green. Checkpoint: the full tier, both reviewers, one pull request.
2. **Wave B**, the loader and the reader sweep, one reader per commit where that helps the
   review. Checkpoint: the census test green, the two-lane row test green, the full tier.
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
- Wave B: 2 days (the loader in half a day; the sweep is 20 modules and 38 test files,
  most of them a changed import and a fixture).
- Wave C: half a day, plus the tier.
- Red-team: half a day across the three pull requests.
- Wave D: calendar time, no seat.
- Total: 3.5 to 4 seat-days, less Wave B and C if 0-A ends the pack.

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
