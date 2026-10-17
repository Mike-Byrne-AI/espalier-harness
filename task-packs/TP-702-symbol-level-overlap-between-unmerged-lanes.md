# TP-702 — Symbol-level overlap between unmerged lanes: derived symbols on claims, the board's overlaps section, the ship notice

## Status

- Version target: the next beta after `0.8.0b2`.
- Type: workflow infrastructure (the mail channel's claim schema, the plan pre-flight, the board, the ship driver, the worker tick) plus one new standard-library module under `tools/cc/`.
- **Kind: PACK.** Three waves, each its own lane and pull request; the first wave is assigned with this pack.
- Authored 2026-10-16 (local) by `air`, the dispatcher, on the operator's word ("yes, author the pack and assign wave one") after the design was put on the table and the anti-clobber system's own re-measure came back the same evening: `TP-479` Wave D line 1 (the figures are in that pack's Landing now) failed on its pre-registered window, 12 of 18 catch-ups conflicted against a pass line of 5 or fewer, which is what `TP-479a` was written for, and reads 0 of 17 over the last 30 merges since `TP-479a` landed. This pack is the next rung of that system, not a repair of it.
- Reviewed at authoring by the failure-mode reviewer on the first draft: REQUEST CHANGES, 2 regressions, 8 gaps, 5 rough edges, every one folded here before the first push (Landing records them). Its two load-bearing finds: the oracle printed "different functions" exactly where its mapper knew nothing, because it dropped the lines it could not place; and the prescribed port diffed a lane against a base that had moved, which reports other lanes' symbols as the lane's own.
- Ledger: no row. The gap is a process cost, the dispatcher reading two lanes' hunks by hand, not a defect in shipped code; the measurement is in Motivation.
- Parent: `TP-479` (`task-packs/TP-479-parallel-work-without-clobbering.md`), which reads two lanes at the file level and leaves the function level to a later pack.

## Motivation

The anti-clobber system reads two lanes at the file level before a merge and at the file-plus-imports level after one. Claims carry paths (`tools/cc/mail.py::RE_KEYS`: lane, classes, paths, ids); the plan pre-flight matches a step's `files:` and `classes:` against live claims (`tools/cc/execution_plan.py::_claim_overlaps`); the board's `stale:` line fires only after a merge moves the base near a pull request's files (`tools/cc/_merge_rules.py::stale_base`: a path both changed, or an import between changed files). Nothing says "same function" for two lanes that are both still open.

Measured, 2026-10-16: the dispatcher answered that question by hand three times, reading diff hunks in a worktree on this Mac: `tests/conftest.py` for #269 against #270, `espalier/cli.py` for air-work's lane against win-2's one deploy-list line, and the three lanes now editing `tools/cc/hooks/_bash_patterns.py` and `write_guard.py` at once (win's `DEF-1171`, win-2's `DEF-3008`, air-work's `DEF-1131`). Every answer was "different functions, safe".

Measured, 2026-10-16 (local), by this pack's oracle over a pinned window (`python3 scripts/lane_overlap_census.py --window 246-276`; the script lands with this pack): 30 pull requests read, none unread; 25 pairs were open at the same time; 5 of them changed a file in common. Of those five: one shared a symbol (#271 and #272 both appended to `scripts/derived_population_census.py::ADJUDICATED`, which merged clean); one is certified "different functions" with every changed line placed on both sides (#261 and #263 in the hooks, their vendored twins folded onto the source); two are **unplaced**, where a side changed lines no definition holds and the mapper refuses to certify (#269 and #270 in `tests/conftest.py`, the dispatcher's own hand read, which the mapper will not vouch for; #261 and #262 in a test file); one is prose, a path tier (#255 and #256 in the protocol memory). Over the window, 476 of 17,500 changed Python lines were unplaced (2.7%; blank lines are neutral and not counted), the worst pull request at 15% (#270: 58 of 395). The window's one number that is not a merged pull request (#276, open at the time) is reported as such, not dropped.

So the first draft's claim that the oracle "reproduces the hand reads" was wrong in the dangerous direction: it reproduced them by dropping what it could not place. The honest reading is that one of the two hand-read pairs in the window is certifiable and one is not, and the mapper says which.

What the pack buys: the "different functions" certificate printed by a tool, to every seat, before its first edit, only where every changed line on both sides is placed; an explicit "unplaced" where it is not, which is a path hit and nothing more; and a flag on a shared symbol, which today arrives as a conflict at catch-up or as nothing. Who is hurt without it: a seat that builds for hours in a function another seat is rewriting, learning at catch-up; and the dispatcher, whose hand reads are the one judgment in the system that no tool makes and no test pins.

## Scope (in) — the waves

1. **Wave 1 — the symbol, derived; claims carry it; the plan and the matcher read it; the roster homes.** A new `tools/cc/_symbols.py` (standard library `ast`; the mapper now in `scripts/lane_overlap_census.py`, moved), reading a lane against the merge-base of its base and head, working tree and untracked files included, rename detection off; the claim verb derives a lane's symbols and sends them under an optional key outside `RE_KEYS` (the `ASSIGN_SEAT_KEY` precedent: written only when present, so an unflagged claim is byte-identical to today's and the two key-set pins in `tests/test_mail.py` stand); the derived symbols' paths fill `paths` too, so a reader that knows only paths still meets the lane; `mail.py::overlapping_claims` gains a symbol hit; `mail.py::secret_hits` scans symbol paths; a `MAX_SYMBOLS` cap; `mail.py claims` prints them; `execution_plan.py::_claim_overlaps` gains a `symbols:` step field checked against the current file's definitions; the census imports the module; the four roster homes a new `tools/cc/` module has, in this wave, because `tests/test_deploy_set_import_closure.py` reds without them.
2. **Wave 2 — the readers.** The board's `overlaps:` section over every pair among live claims and open pull requests, pull-request symbols derived from heads fetched by object id in one bounded call, with an explicit "symbols not read" state where a head is not here, prose files as a path tier, mirror twins folded; the `stale:` line's `near` entries gain "in the same function `X`", "different functions" or "unplaced" for a Python path both changed, only where the pull request's head is here; `ship.py open` and `handoff` print the same overlaps for the lane being pushed, as a notice.
3. **Wave 3 — the refresh and the words.** A `mail.py refresh` verb (the lane from the branch, the base derived as the ship driver derives it, a delta claim only while a live claim of this seat names the lane, exit 0 and a line when there is nothing to send); the one sentence for the worker tick proposed to the operator, whose paste it is (`tools/cc/seat.py::WORKER_TICK`, pinned verbatim by `tests/test_seat.py::_OPERATOR_TICK`); `.claude/commands/inbox.md` and its two mirrors; `memory/parallel-work-protocol.md`.

## Scope (out)

- **A call-edge reading within one file** (two lanes in different functions where one calls the other). Needs a call graph; the import rule covers the cross-file case. The next rung, after Wave D here says whether the symbol is too coarse or too fine.
- **A refusal** at `open`, `handoff` or merge on a shared symbol. Two lanes touching one function in sequence is legitimate; the mechanical consequence already exists at catch-up (a textual collision conflicts, a semantic one meets CI). This pack is advisory by design. Refuted, and a refusal re-proposed, only if Wave D's second line shows flagged pairs going red in combination after clean catch-ups.
- **Lane snapshot refs** (a per-seat `refs/heads/lanes/<seat>` the seat pushes on each commit, so the board reads unopened lanes without self-report). Deferred until Wave D's lag line fails; the refresh verb bounds the lag at one worker tick for less.
- **Section-level symbols for prose files.** A Markdown heading mapper is cheap, but a prose conflict is git's to resolve and the window's one prose pair was expected (the protocol memory, two lanes each adding a line). Prose stays a path tier, reported apart, never as a shared symbol.
- **Placing every line.** Blank lines, comments and imports outside any definition stay unplaced; the oracle attaches a comment block or a decorator to the definition below it and finds definitions under module-level `if` and `try` blocks, which brought the window's unplaced rate to 2.7%. Lower than that needs a line-level reading that is a diff, not a symbol.
- `DEF-981` (three open lanes livelock under the up-to-date rule): moot while the rule is off; not touched.
- The dispatcher's assign text naming overlaps in prose: stays; the board's section is the record.

## Task 0 — Verify (try to kill this pack)

**0-A The gap is real in the current window.** Oracle: `python3 scripts/lane_overlap_census.py --prs 30`. Refuting result: zero concurrent pairs sharing a file. Exit: stop and re-raise; the gap was one day's shape. (Authoring-time reading over `--window 246-276`: 5 of 25.)

**0-B The certificate agrees with the hand reads, on enough of them.** Oracle: the census over the pairs the dispatcher certified by hand (named in Motivation; the window holds #269 and #270 now, and holds #275 against #276 and the guard-file lanes once two of each have merged). Refuting result: the mapper prints "different functions" for a pair the hand read found meeting in one function, or "shared symbol" where the hand read found none; an "unplaced" verdict refutes nothing, it declines. Exit below three certified pairs in the window: wait, and re-run when the lanes merge. Exit on a disagreement: the mapper is wrong; stop, with the pair and the symbol, before anything reads it. The mapper's known errors all lean toward "different functions", so Wave D line 5 keeps watching after the pack lands.

**0-C The derivation places the lines it is given.** Oracle: `python3 scripts/lane_overlap_census.py --prs 30 --json`, reading `unplaced_lines` against `changed_lines` for the window and `per_pr` for the worst pull request. Refuting result: more than one in ten of the window's changed Python lines unplaced (authoring: 2.7%, the worst pull request 15%). The output also lists `missing`, the window's numbers that are not merged pull requests, so a window that shrinks under the listing is seen, never read as a smaller population. Exit: Wave 1 ships the unplaced state as it is (a path hit, never a certificate) and the pack's Scope (out) line on placing every line is re-opened; stop if the rate is above one in four, since the certificate would then be rare enough to be no tool.

**0-D The key is tolerated by every reader.** Oracle: `git grep -n 're_\.get\|\.get("re")' -- tools/cc` (every reader of a message's `re` block, derived, wherever it sits: at authoring, seven files, `tools/cc/checkout_sync.py`, `tools/cc/hooks/session_start.py` and `tools/cc/seat.py` among them) and `git grep -n RE_KEYS -- tests` (through `git grep`, which reads the tree on every host; a bare `grep` of a directory refuses on GNU and BSD grep and passes with no evidence). Refuting result: a reader that iterates `RE_KEYS` strictly over a message's `re` block, or a test asserting the key set, that Wave 1's optional-key shape (outside `RE_KEYS`, as `ASSIGN_SEAT_KEY` is) would still break. Exit: stop and re-raise; the key waits behind a reader release on every seat. (Authoring-time reading: every reader takes keys by `.get`; the two set pins at `tests/test_mail.py` assert `RE_KEYS` and stand under the optional-key shape; Wave 1 adds a test that feeds the readers a message with an unknown key.)

A Task 0 whose every outcome is "build" is a warm-up. 0-A, 0-B and 0-D each end the pack; 0-C ends it above one in four.

## Relevant memory

Recent pattern: the first draft of this pack certified two pairs the mapper could not place, and a review caught it; the verification read then found blank lines attaching to a neighbouring definition, so an edit flagged a function it never touched. The risk in this work is not the mapper but every place a verdict is printed as if it were measured, and every second rule for one question (the claims matcher and the board's verdict must share `symbols_meet`). A board section that fires on prose trains seats to ignore it.

| Entry | Where |
|---|---|
| Parallel work protocol (the seats, the claims, the dispatcher) | `memory/parallel-work-protocol.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| 4. Verify tool output through an independent oracle | `docs/STANDING_PRINCIPLES.md` |
| 5. The null result is the signal | `docs/STANDING_PRINCIPLES.md` |
| 14. Derive the list, don't test a hand-written copy of it | `docs/STANDING_PRINCIPLES.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "parallel lanes overlapping in one file: claims, the stale base line, catch-up"`; re-run it rather than trusting this list if the pack has been sitting.

## Implementation

### Wave 1 — the symbol, derived; claims carry it *(fix shape; the mapper driven as the census over 30 merged pull requests, the rest untested)*

**1-A `tools/cc/_symbols.py`.** The pure functions now in `scripts/lane_overlap_census.py` move here unchanged in meaning: `spans(source)` (every function, async function and class at any depth, qualified by the definitions above it, a span starting at its first decorator; every module-level assignment by each target it binds, through `if` and `try` blocks; a class-body assignment is the class's), `innermost(nodes, line)`, `enclosing(nodes, line)`, `placed(nodes, lines, line)` (a blank line is neutral and names nothing, so a deletion's trailing blanks and the blank between two methods never flag a neighbour; an unbroken run of comments touching a definition is the definition's, and a blank breaks the run), `changed_symbols(path, old_source, new_source, unified_diff)` (both sides of every hunk placed; blanks skipped; the unplaced count beside the symbols; a file that is not Python is a path tier), `concurrent(a, b)`, `symbols_meet(one, two)` (the one rule for what two symbol sets share: an equal name, or a class on one side with a member of it on the other, never the module; the claims matcher, the board's verdict and the ship notice all call it), `pair_verdict(one, two)`, `canonical(path)` and `symbols_between(base, head)`; plus one new `symbols_of_lane(root, base_ref)` that reads the lane against `git merge-base <base_ref> HEAD` with no second revision, so the working tree counts, adds the untracked files `git ls-files --others --exclude-standard` names, and passes `--no-renames` to every diff as `DIFF_ARGS` does. Standard library and `git` only (`tests/test_contracts.py::TestToolsCcNoEspalierImports`), so `canonical` here folds the one mirror pair the deployed tools own, `espalier/_vendor/cc/` onto `tools/cc/`, and a test pins that pair against `espalier/mirror_registry.py::row("vendor-cc")`; the census keeps the full registry fold, importing the engine as a script may. The census imports the module from `tools/cc/` by path and keeps no copy. Refuted if a symbol derived from the working tree differs from the one derived from HEAD on a clean tree (a test), or if a lane whose base moved after its branch point reports a symbol it never touched (a test: the base gains a commit editing `g`, the lane edits `f`, the lane reports `f` alone).

**1-B The claim carries symbols.** `tools/cc/mail.py` gains `SYMBOLS_KEY = "symbols"` beside `ASSIGN_SEAT_KEY`, written into `re` only when symbols are given, so `RE_KEYS` and the two pins at `tests/test_mail.py` that assert its set are untouched; `::new_message` takes `symbols`; `::build_parser`'s `send` gains `--symbols-from <base>` (derive from the lane's diff against the merge-base with it; default the base branch as `ship.py` reads it) and `--delta` (send only the symbols no live claim of this seat on this lane already names; print `no new symbols` and exit 0 when there are none; print `no live claim on this lane` and exit 0 when the lane's claims were released, so a lane fixing CI after its push never re-opens the claim the push closed); the derived symbols' paths join `paths`, so `_touches`, the ledger verbs and an older seat meet the lane by path as today; `::secret_hits` scans the symbols' paths beside the text and `paths`; `MAX_SYMBOLS` caps the key (the rest a count, the paths still whole); `::overlapping_claims` gains `symbols=` and a hit reads `symbol path::name`, by `_symbols.symbols_meet` and no rule of its own (a class symbol covers its methods there, `path::C` meets `path::C.m`), and a claim without the key matches by path exactly as today; `::_print_message` prints a claim's symbols on their own line, at most eight then a count.

**1-C The plan pre-flight.** `tools/cc/execution_plan.py::_STEP_FIELD_RE` admits `symbols:`; `::_step_fields` returns them, each checked against `spans()` of the file it names at the working tree, with a `WARN` naming a symbol that resolves to nothing (a typed symbol is the one thing here a seat spells by hand); `::_claim_overlaps` passes them to the matcher and words the line "claims `path::name`" beside the path line. A plan that names only `files:` gets the path warning it gets today.

**1-D The roster homes.** A new `tools/cc/` module has four: `espalier/managed_paths.py`; `cc/PACK_MANIFEST.txt` by its generator, never by hand; the standalone-tools count pinned by `tests/test_managed_inventory.py::test_init_tool_scripts_is_the_eighteen_standalone_tools`; and the generated files region in `README.md` and `docs/QUICKSTART.md` by `scripts/generate_doc_regions.py`. `python3 -m espalier surface-impact task-packs/TP-702-symbol-level-overlap-between-unmerged-lanes.md` names the zero-imports, vendor-mirror and provenance demands and none of these four, so this list is the pack's and `tests/test_deploy_set_import_closure.py` is the gate that reds without them. The vendored twin by `python3 scripts/sync_vendor_cc.py`.

**1-E Earn the red.** `tests/test_symbols.py` takes over the census test's cases (each docstring names its mutation) and adds: working tree and HEAD agree on a clean tree; a moved base reports the lane's symbols alone; the vendor pair matches the registry row. `tests/test_mail.py`: a claim with symbols round-trips and its paths fill `paths`; an unflagged claim is byte-identical in its `re` block to today's; two claims sharing a symbol hit; same file and different symbols give a path hit only, worded so; a class covers its method; a claim without the key still hits by path; a message with an unknown `re` key is read; `--delta` sends nothing twice and nothing after the lane's release; a symbol path that the guard reads as secret-bearing is refused; the cap holds. `tests/test_execution_plan.py`: a `symbols:` step meets a live claim; a typed symbol that resolves to nothing warns. Mutations named per test: the innermost-span rule inverted, the old side of a hunk dropped, the class-covers-method prefix dropped, the delta filter removed, the release check removed, `paths` not filled, the secret scan skipping symbols.

**Checkpoint:** `python3 scripts/proof_tier.py --run` (the contract tier), `ruff check .`, `mypy tools/cc/hooks/`, `python3 scripts/sync_vendor_cc.py` clean, `pytest tests/test_deploy_set_import_closure.py tests/test_managed_inventory.py -q` green.

### Wave 2 — the readers *(fix shape, untested)*

**2-A The board's `overlaps:` section.** `tools/cc/board.py` gains `read_overlaps_section(root, claims, prs)`: the heads of every open pull request fetched by object id in one bounded call (`git fetch origin <oid> <oid> ...`, which lands objects and moves no ref, so the board's contract that it moves only the mail and the base holds); for each pull request whose head is here, `_symbols.symbols_between(merge_base, head)`; for each pair among live claims from different seats and open pull requests, claim with claim, claim with pull request, pull request with pull request, `pair_verdict`; a pull request whose head could not be fetched gets `(symbols not read: head not here)` and a path-level reading only. `::render` prints one line per pair: `win (lane/x, DEF-1171) and air-work (lane/y, DEF-1131) meet in tools/cc/hooks/_bash_patterns.py::_strip_span_tail`; `... both changed <path>: different functions`; `... both changed <path>: unplaced lines on <seat>'s side`; `... both changed <path> (not Python)`. Mirror twins folded by `canonical`. Nothing when there are no pairs: `overlaps: none`.

**2-B The `stale:` clause.** `tools/cc/_merge_rules.py::stale_base` takes `pr_rev` already; where `pr_rev` is the pull request's head and a `(both changed)` path is Python, the entry gains the symbol reading between the pull request's diff and the base's moves since `tested`: `(both changed, in the same function _mutated_zone)`, `(both changed, different functions)` or `(both changed, unplaced lines)`; where `pr_rev` fell back to the base because the head is not here, the entry says `(both changed; symbols not read: head not here)` and never a function verdict, since the base compared with itself is no comparison. The verdict is unchanged; the clause tells the seat what its catch-up will meet.

**2-C The ship notice.** `tools/cc/ship.py::open_pr` and `::handoff` print, after the push, the overlaps the lane's symbols have with every live claim of another seat and every open pull request, in the board's words, and nothing else changes: the rule stays "the second to merge runs catch-up".

**2-D Earn the red.** `tests/test_board.py`: two claims sharing a symbol print one line; same file and different symbols print the certificate; a side with unplaced lines prints unplaced, never the certificate; an open pull request's symbols come from its head, not the claim; a head not here prints the not-read state; two pull requests with no claim between them are compared. `tests/test_stale_base.py`: the three clauses and the not-read state. `tests/test_ship_driver.py`: the notice on a scratch repository. Mutations: the pair loop skipping same-seat pairs removed (a seat meets itself), the certificate inverted, the pull request's symbols read from the claim, the fallback-to-base clause printing a verdict.

**Checkpoint:** the full tier in CI (the ship driver and the board are the workflow's own gates), both reviewers on a snapshot, the vendored twins synced.

### Wave 3 — the refresh and the words *(fix shape, untested)*

**3-A The refresh verb.** `tools/cc/mail.py` gains `refresh`: the lane from `git branch --show-current` (never typed, the lane-spelling footgun `release_lane` records), the base as `ship.py` derives it, then `send --type claim --delta --symbols-from <base>` with the three exits 1-B gives it (sent; `no new symbols`, 0; `no live claim on this lane`, 0). The seat's own mail ref is written by compare-and-swap (`::_push_ref`), so a refresh racing the seat's own claim is refused and retried next tick; a test drives two sends back to back. The one sentence for the worker tick, `run python tools/cc/mail.py refresh once; it writes nothing when nothing is new`, is proposed to the operator, whose paste `tools/cc/seat.py::WORKER_TICK` is (`tests/test_seat.py::_OPERATOR_TICK` pins it verbatim); the lane does not edit it, and a loop already running keeps its text until the operator restarts it. The verb must exist on every seat's checkout before the sentence is pasted, or an older seat's tick fails argument parsing: the sentence goes out after Wave 3 merges and every seat has caught up.

**3-B The words.** `.claude/commands/inbox.md`: the claim's symbols, `--symbols-from`, `--delta`, `refresh`, the board's `overlaps:` section and its three readings; `python3 scripts/sync_claude_mirrors.py` for its two mirrors. `memory/parallel-work-protocol.md`: the dispatcher no longer certifies hunks by hand; a seat reads the board's `overlaps:` line and the plan's warning, and an `unplaced` reading is a path hit, not a certificate. `docs/HOOKS.md` is not touched (no hook changes).

**Checkpoint:** the contract tier and the mirror parity tests, `python3 scripts/sync_claude_mirrors.py` clean.

### Wave D — the re-measure *(pre-registered 2026-10-16, before any wave lands)*

The board prints and records nothing, so every line below is read after the fact from the census replayed over the window (`python3 scripts/lane_overlap_census.py --window <first>-<last>`), a proxy for what the board printed at the time; the dispatcher's handoff rows hold the hand reads.

Over the first 30 merges after Wave 2 lands (lines 1, 2, 3 and 5) and after Wave 3 lands (line 4):

1. **Hand reads.** The dispatcher's hand certifications of two lanes' hunks, counted from its handoff rows. Pass: 0, against 3 on 2026-10-16. The author-dispatcher's own count, declared.
2. **Predictive value.** Pairs the census reads as sharing a symbol that conflicted at catch-up or went red in combination. Reported, not a gate; two or more re-open the refusal question in Scope (out).
3. **Noise.** Pairs read as sharing a symbol where both lanes merged with a clean catch-up and no red. Baseline from the authoring window: 1 of 1 (the dict literal). If more than two thirds of such pairs are this over the 30, the symbol is too coarse and the next rung is call edges. Prose pairs are a path tier and do not count here.
4. **Lag.** Minutes from a seat's first commit touching a new symbol to the claim naming it, from the mail refs. Pass: median under one worker tick (10 minutes).
5. **Certificates.** Pairs the census reads as "different functions" that conflicted at catch-up. Pass: 0; one re-opens 0-B and the mapper.

## Affected symbols

The walk is name-keyed: `handoff`, `render`, `collect`, `build_parser` and the mapper's short names (`spans`, `placed`, `enclosing`, `concurrent`, `canonical`) are common words across the command bodies, the docs and the tests, so `scope-check` lists files outside Scope (in) that merely say them. The module-qualified bullets below are the scope; the executor accepts that gap at 0-B with this reason, and `main` is not cited at all (4,993 references, the branch name among them).

### Changed-semantics

- `tools/cc/mail.py::new_message` (takes `symbols`; writes `SYMBOLS_KEY` only when given; fills `paths` from them)
- `tools/cc/mail.py::overlapping_claims` (a symbol hit; a class covers its methods)
- `tools/cc/mail.py::secret_hits` (scans the symbols' paths)
- `tools/cc/mail.py::_print_message` (a claim's symbols on their own line)
- `tools/cc/mail.py::build_parser` (the `send` sub-parser: `--symbols-from`, `--delta`; the `refresh` verb)
- `tools/cc/execution_plan.py::_STEP_FIELD_RE`
- `tools/cc/execution_plan.py::_step_fields` (a typed symbol checked against the file's definitions)
- `tools/cc/execution_plan.py::_claim_overlaps`
- `tools/cc/board.py::collect` (fetches the open heads by object id; reads the overlaps)
- `tools/cc/board.py::render` (the `overlaps:` section)
- `tools/cc/_merge_rules.py::stale_base` (the function clause on `near`, only with the head here)
- `tools/cc/ship.py::open_pr` (the notice)
- `tools/cc/ship.py::handoff` (the notice)
- `scripts/lane_overlap_census.py` (imports the mapper from `tools/cc/_symbols.py`; keeps no copy)

### Renamed

- `scripts/lane_overlap_census.py::spans` → `tools/cc/_symbols.py::spans`
- `scripts/lane_overlap_census.py::innermost` → `tools/cc/_symbols.py::innermost`
- `scripts/lane_overlap_census.py::enclosing` → `tools/cc/_symbols.py::enclosing`
- `scripts/lane_overlap_census.py::placed` → `tools/cc/_symbols.py::placed`
- `scripts/lane_overlap_census.py::changed_symbols` → `tools/cc/_symbols.py::changed_symbols`
- `scripts/lane_overlap_census.py::concurrent` → `tools/cc/_symbols.py::concurrent`
- `scripts/lane_overlap_census.py::pair_verdict` → `tools/cc/_symbols.py::pair_verdict`
- `scripts/lane_overlap_census.py::symbols_between` → `tools/cc/_symbols.py::symbols_between`
- `scripts/lane_overlap_census.py::symbols_meet` → `tools/cc/_symbols.py::symbols_meet`

### Added-paths

- `tools/cc/_symbols.py`
- `tools/cc/_symbols.py::symbols_of_lane`
- `tools/cc/_symbols.py::canonical` (the vendor pair only; the census's registry fold stays in the script)
- `tools/cc/_symbols.py::DIFF_ARGS`
- `tools/cc/mail.py::SYMBOLS_KEY`
- `tools/cc/mail.py::MAX_SYMBOLS`
- `tools/cc/board.py::read_overlaps_section`
- `espalier/_vendor/cc/_symbols.py`
- `tests/test_symbols.py`

### Removed-paths

- None.

## Pass criteria

- Every test this pack adds was red against the mutation its docstring names before the fix and is green after; no assertion in `tests/test_mail.py`, `tests/test_board.py`, `tests/test_stale_base.py`, `tests/test_execution_plan.py`, `tests/test_ship_driver.py` or `tests/test_seat.py` is weakened, and none is held unmodified: a defect found in a gate this pack delivers is this pack's.
- A claim sent without `--symbols-from` is byte-identical in its `re` block to one sent today, pinned by a test; the two `RE_KEYS` set pins in `tests/test_mail.py` stand as written.
- A pair's "different functions" reading is printed only where every changed line on both sides was placed; a side with an unplaced line reads `unplaced`, pinned in `pair_verdict`'s tests and in the board's.
- `python3 tools/cc/board.py --no-fetch` on a checkout with no live claims and no open pull request prints `overlaps: none` and nothing else new.
- `python3 scripts/lane_overlap_census.py --window 246-276` run from the module prints the window's figures as this pack's Motivation states them (the window is pinned, so the population does not move; a changed figure is a changed mapper, and the pack says which).
- `tests/test_contracts.py::TestToolsCcNoEspalierImports`, `tests/test_deploy_set_import_closure.py`, `tests/test_managed_inventory.py` and the vendor parity tests stay green: the new module imports the standard library only and sits in every roster.
- The contract tier green on every wave; the full tier green in CI on Wave 2.

## Files touched

- New: `tools/cc/_symbols.py`, `espalier/_vendor/cc/_symbols.py` (by `sync_vendor_cc.py`), `tests/test_symbols.py`.
- Modified: `tools/cc/mail.py`, `tools/cc/execution_plan.py`, `tools/cc/board.py`, `tools/cc/_merge_rules.py`, `tools/cc/ship.py` and their vendored twins; `scripts/lane_overlap_census.py`; `tests/test_mail.py`, `tests/test_execution_plan.py`, `tests/test_board.py`, `tests/test_stale_base.py`, `tests/test_ship_driver.py`, `tests/test_lane_overlap_census.py`, `tests/test_managed_inventory.py`; `espalier/managed_paths.py`; `cc/PACK_MANIFEST.txt`, `README.md` and `docs/QUICKSTART.md` (by their generators); `.claude/commands/inbox.md` and its mirrors `espalier/assets/claude/commands/inbox.md`, `examples/dogfooding/.claude/commands/inbox.md` (by `sync_claude_mirrors.py`); `memory/parallel-work-protocol.md`.
- Deleted: none.
- Unmodified on purpose: `tools/cc/seat.py` (`WORKER_TICK` is the operator's paste; 3-A proposes its sentence); `tools/cc/hooks/*` (no hook changes, so no marker and no `docs/HOOKS.md` edit); `tools/cc/ledger_row.py` (the ledger verbs' claim read stays on ids); `.github/workflows/*`.

## Sub-task ordering

1. Task 0 (0-A to 0-D), which may end the pack.
2. Wave 1 (1-A the module and its test first, the smallest change; 1-D the roster homes next, so the import-closure gate is green before the readers; then 1-B, 1-C; 1-E's reds before each fix). Checkpoint: the contract tier and the two inventory gates.
3. Wave 2 (2-A, 2-B, 2-C; 2-D). Checkpoint: the full tier in CI; both reviewers.
4. Wave 3 (3-A, 3-B). Checkpoint: the contract tier and the mirror parity tests; the tick sentence goes to the operator after every seat has caught up.
5. Wave D's windows open at Wave 2's merge (lines 1, 2, 3, 5) and Wave 3's (line 4); the figures go to Landing.

## Estimated effort

- Task 0: half an hour (the census runs in about two minutes over 30 pull requests).
- Wave 1: a day, the roster homes and the reviews included.
- Wave 2: half a day, plus the full tier's wall clock.
- Wave 3: two hours, plus the operator's paste.
- Red-team: one review pass per wave, both reviewers on Wave 2; budget an hour each.
- Total: about two days of one seat, over three lanes. Tagged estimated.

## Landing

- State: DRAFT (authored 2026-10-16 local; Wave 1 assigned to `air-work` with this pack, to follow its current guard lane).
- Commits: this pack, the census oracle, its test, the scripts-roster line and `TP-479`'s Wave D line, one records lane from `air` (the pull request carries the SHA).
- Suite: `python3 scripts/proof_tier.py --run` on the authoring lane. CI ran the full tier (the scripts-roster line in `tests/_surface_expected.py` is suite config), and its five parallel cells found six tree-wide contract gates red on the lane's own new files, none covered by the local contract run: the script's docstring naming its pack (provenance, two tests), a spawn wrapper building its argv from parameters (subprocess contract), the script loaded inside a fixture (derived-population census), a test docstring with no rationale anchor, and no forward-ledger row. All six fixed in the second push; the oracle's behaviour, its tests and a window drive read the same.
- Earn-the-red: the census test's cases drive the mapper and the pair verdict in-process, each docstring naming the mutation it dies to; the authoring-time census over the pinned window is in Motivation.
- Red-team: the failure-mode reviewer on the first draft, REQUEST CHANGES (2 regressions, 8 gaps, 5 rough edges), every finding folded in one batch: both sides of every hunk placed and unplaced lines never certified; the port reads the merge-base, the working tree and untracked files with rename detection off; Task 0's four items each able to end or hold the pack; the key outside `RE_KEYS`; the roster homes in Wave 1; the readers' not-read state and pull-request pairs; symbols filling `paths`, scanned for secrets, capped; prose as a path tier and twins folded; Wave D read from the census; the tick's sentence proposed, not edited. The verification read on the folded draft: every finding confirmed closed by code, tests and seven named mutations; REQUEST CHANGES narrowly on three new gaps the fold exposed (blank lines attaching to a neighbouring definition, a pinned window that truncated as merges accumulated above it, two class-coverage rules for one question) and three wording slips, all folded in a second batch: blanks are neutral, the window lists from the newest number down to its floor and reports what it did not find, and `symbols_meet` is the one rule. No third round: the oracle is pinned by its tests, and the pack's executor runs Task 0 and a review per wave.
- Reach: not a class closure; no reach claimed.
- Date: 2026-10-16.
