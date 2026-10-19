# TP-703a — The red after the merge has a reader: one post-merge verdict module for the board, the banner and the ship preflight

## Status

- Version target: adopter-facing where it touches `tools/cc/` (the board, the ship driver and the
  SessionStart hook deploy through `espalier init` via the vendored byte-copy,
  `espalier/_vendor/cc/`); self-host where it touches `scripts/` (the census instrument) and the
  workflow header it corrects.
- Type: workflow infrastructure. One new standard-library module under `tools/cc/` that three
  readers share, and one instrument.
- **Kind: PACK.** One lane, `lane/red-after-merge-has-a-reader`. Task 0 can end it (below).
- Parent: `TP-703` (`task-packs/TP-703-multi-seat-discipline.md`), Wave 1, item 1. The
  roadmap's own Task 0 item 1 (the known-noise share) runs before this pack is assigned, and
  its refuting result re-sequences this pack behind `TP-703b` W3 and `TP-703h`.
- Authored 2026-10-18 (local) by the dispatcher seat `air` on the operator's word ("good, lets
  make task packs for fixing these issues"), from the `/reflect` of the same evening.
- Ledger: no row filed at authoring. The defect is the roadmap's table row "the null result is
  the signal"; the lane that builds this files a row only if its Task 0 finds a defect that
  needs its own oracle (`memory/parallel-work-protocol.md` item 8). It mints nothing. Two
  documented drifts are corrected in-lane: the header of `.github/workflows/portability.yml`
  ("the signal is read before the merge") and the docstring of `tools/cc/ship.py::post_merge_reds`.
- **The gap this pack leaves, stated once here and on the board's own line:** it reads
  pull-request runs. A red that the merge combination itself makes, which no pull request's
  rollup carries, is read only by the base's post-merge proof (`tools/cc/board.py::read_post_merge`,
  one interpreter, Linux) until `TP-703b` W2 adds a Windows leg on `main`.

## Motivation

**Measured on 2026-10-18** (`gh pr view 313 --json mergedAt,statusCheckRollup` and the same for
312; re-run them): #313 merged at 13:26:32Z. Its `portability (windows-latest)` row completed at
13:57:44Z with `FAILURE`, 31 minutes after the merge; its `portability (macos-latest)` row
completed at 13:15:03Z with `FAILURE` (`DEF-2025`'s known shape). #312, merged 13:01:07Z, has
`portability (windows-latest)` `SUCCESS` completed 14:10:49Z and `portability (macos-latest)`
`FAILURE`. So at 14:00Z the record said: Windows red on #313, #312's leg still running; by
14:15Z it said green on #312 and red on #313; and nothing printed either reading. Both runs
started before the other merge landed (#313's run started 12:36:26Z, before #312 merged at
13:01:07Z; #312's run started 12:45:40Z, before #313 merged at 13:26:32Z; measured 2026-10-18
from the same two reads), so merge order alone cannot say which verdict stands (1-A's rule).
The first mention of the Windows red is in the dispatcher's tick notes at 19:39Z
(unmeasured beyond the notes). Its cause was a test helper that armed `SIGALRM` with no guard,
fixed forward by #320 six hours after the record could have named it.

**Three readers today, two codebases, one board that reads none of it:**

- `tools/cc/ship.py::post_merge_reds` reads 20 merged pull requests by `--author @me` and prints
  `red after merge: #N <checks>` per pull request, in listing order, with no ownership rule: a
  check red on #313 and green on #314 prints as red. `ship.py::preflight` prints these lines.
- `tools/cc/hooks/session_start.py::_post_merge_verdicts` reads 5 merged rows
  (`::_MERGED_PR_ROWS`), applies an ownership rule (the newest merged pull request whose latest
  run of a check name reached a verdict owns that name) and names a cancelled or stale latest run
  as `no verdict`. `::_merged_prs_line` renders it. It fires at SessionStart, `clear` and
  compaction, which is why the Windows red reached no seat for six hours: no seat started.
- `tools/cc/board.py::read_post_merge` reads the base branch's `post-merge.yml` runs, never a
  pull request's rollup. The board, the one live read every seat and the dispatcher make each
  tick, has no line for a check that went red on a merge.

The two codebases are held equal by text: `tests/test_hook_constant_parity.py::TestCheckStateSetsAreOneRule::test_the_driver_and_the_banner_share_the_check_state_sets`
compares four frozensets between `ship.py` and `session_start.py`, and `ship.py` marks its copies
`sister-site: ok` because a hook cannot be imported from `tools/cc/`. The reverse import is the
one the tree already uses: `session_start.py::_load_merge_rules` loads `tools/cc/_merge_rules.py`
by path under a private alias, and `board.py` and `ship.py` import the same module as a sibling,
so the three `Merging:` readers cannot drift. This pack gives the post-merge verdicts the same
one home.

**The named user (`STANDING_PRINCIPLES` §16).** The operator, who learned of a Windows red that
had sat in GitHub's record for six hours by reading a job log by hand on the analysis evening;
the seat whose lane merged red on a leg that reports to nobody; and every seat that merged after
it onto a base no reader had called red on Windows.

## Scope (in)

1. **`tools/cc/_post_merge.py`** (new; standard library; zero `espalier` imports): the four
   check-state sets; `check_outcome(row)`; `latest_run_per_check(rows)`; `verdicts(merged)`, the
   ownership rule as `session_start.py::_post_merge_verdicts` states it; `transitions(merged)`,
   which walks the merged rows in merge order and, per check name, names the merge at which the
   owned verdict changed and the `completedAt` of the run that set it, where a green run takes
   ownership over an older merge's red only when it started after that merge's `mergedAt` (the
   run contained the red change); `read_merged(cwd, limit, gh, author)`, the one `gh pr list
   --state merged` read, its author filter the caller's (the banner keeps `--author @me`, since
   the root `CLAUDE.md` says its line names your pull requests; the board and the preflight pass
   none); and the words each surface prints. The three surfaces share the rule and the words,
   not the author scope, and the pack says so here once.
2. **`tools/cc/ship.py`**: `post_merge_reds` becomes a call into the module (the lines gain the
   ownership rule and the since/green-on clause); its four restated sets go; `preflight` prints
   the module's lines. `base_red_after_merge` and `red_base_refusal`, which read the base's runs,
   are untouched.
3. **`tools/cc/hooks/session_start.py`**: `_post_merge_verdicts`, `_latest_run_per_check` and
   `_check_outcome` become thin calls through a by-path loader shaped as `_load_merge_rules`;
   where the module is not beside the hooks, the `Merged:` line's red clause reads
   `post-merge verdicts unread (tools/cc/_post_merge.py is not beside the hooks)`, the shape the
   `Merging:` line already takes without `_merge_rules.py`. The hook keeps no copy of the rule.
4. **`tools/cc/board.py`**: `collect` gains a `post_merge_checks` key and `render` a `checks:`
   line: one entry per check name whose owned verdict is red among the merged rows read, with
   change detection, e.g. `checks:   portability (windows-latest): red since #313 (merged
   2026-10-18 13:26Z, the leg finished 13:57Z), green on #312; portability (macos-latest): red
   since #297, 9 merges` and `checks:   none red among the last 20 merges` otherwise. A red
   older than the window prints `red since before #<oldest read>`, never a false origin; a newer
   merge whose latest run of the check reached no verdict is named beside the red (`#320 no
   verdict (cancelled)`), so a cancelled fix run is visible; a green on a run that started before
   the red's merge is printed beside the red, not over it (`#314 green on a run that started
   before #313 merged`). A check whose latest runs reached no verdict on every row read is named
   `no verdict`, never green. The section is read on its own and says `unread` with the reason
   when `gh` fails, as the others do. The read appends one JSON line per transition it prints
   for the first time (the check name, the merge, the red's `completedAt`, the read time) to
   `.espalier-state/board-checks.jsonl`, so the roadmap's re-measure line 1 (red to first
   mention) is derived from a record and not from notes; the path is under `.gitignore`'s
   `.espalier-state/` line and `espalier/surface_contract.py::classify_release_path` reads it
   `transient`, as it reads `.espalier-state/sessions/` (measured 2026-10-18), so no roster entry
   is owed; a failed append is a note on the line.
5. **`scripts/red_after_merge_census.py`** (new; self-host): the Task 0 instrument. It reads the
   merged pull requests of a window (`--since`, `--limit`), replays `transitions` as of a
   wall-clock instant (`--at`: only runs whose `completedAt` is at or before it count) and prints,
   per check name, each transition with the merge, its time and the leg's finish; `--classify`
   reads each red run's failing node ids (`gh run view <id> --log-failed`) and buckets them by the
   ledger rows that name them, so the roadmap's known-noise share is a figure, not a reading.
   `--json` gives the same as data. It imports the module by path, as
   `scripts/lane_overlap_census.py` imports `tools/cc/_symbols.py`.
6. **The roster homes** a new `tools/cc/` module and a new script have on this tree (the import
   closure gate reds without them): `espalier/managed_paths.py`; `cc/PACK_MANIFEST.txt` by its
   generator, never by hand; the standalone-tools count pinned by
   `tests/test_managed_inventory.py::test_init_tool_scripts_is_the_eighteen_standalone_tools`
   (the name carries a count; re-read it, since `TP-702` added one module after it was named);
   the generated-files region of `README.md` and `docs/QUICKSTART.md` by
   `scripts/generate_doc_regions.py`; and, for the script,
   `tests/_surface_expected.py::EXPECTED_SCRIPT_NAMES` with its dated comment.
7. **Tests**: `tests/test_post_merge.py` (new) for the module, each test naming the mutation it
   dies to; the three test files that pin the readers today keep every assertion
   (`tests/test_session_banner.py::TestMergedRedReceiver::test_a_cancelled_latest_run_is_no_verdict_not_red`,
   `::test_a_stale_run_is_no_verdict_too`,
   `tests/test_ship_driver.py::test_a_red_post_merge_run_on_the_base_is_named`,
   `::test_a_skipped_or_neutral_run_is_no_verdict`,
   `tests/test_board.py::TestPostMergeVerdict::test_a_skipped_or_neutral_run_is_no_verdict`,
   `::test_a_repository_without_the_post_merge_proof_says_so`); `tests/test_board.py` gains the
   `checks:` line's tests; the key pin that reads `{"asks", "seats", "open_prs", "post_merge",
   "assignments", "claims"} <= set(collected)` is widened, never narrowed;
   `tests/test_hook_constant_parity.py::TestCheckStateSetsAreOneRule` is retired with a test in
   its place pinning that `session_start.py` defines none of the four sets (the reason the parity
   test existed is gone, and a test holding two copies equal would hide a third copy returning);
   `tests/test_red_after_merge_census.py` (new) over a frozen rollup fixture of #312 and #313.
8. **Words**: `.github/workflows/portability.yml`'s header; `tools/cc/ship.py::post_merge_reds`'s
   docstring (`TP-703g` carries the same two sentences as its items (c) and (d) for the case where
   this lane has not landed; whichever lane lands first corrects them and the other strikes its
   item in Landing); `docs/HOOKS.md`'s `Merged:` paragraph (the `; red after merge: ...` example gains
   the since clause); `.claude/commands/inbox.md`'s board section gains the `checks:` bullet, and
   `python3 scripts/sync_claude_mirrors.py` regenerates its two mirrors; the root `CLAUDE.md`
   SessionStart row only if the `Merged:` line's wording changes; `python3 scripts/sync_vendor_cc.py`
   after every `tools/cc/` edit.

## Scope (out)

- **A Windows or macOS leg on `main`.** The combination gap named in Status is `TP-703b` W2's.
  A push run attaches to the merge commit and never appears in a merged pull request's
  `statusCheckRollup`, so a leg on `main` needs the base-run read (`gh run list --workflow
  <file> --branch main --event push`, with `tools/cc/board.py::read_post_merge`'s no-verdict
  rule), which `TP-703b` W2 builds in its own Scope (in); this module exposes nothing for it
  beyond the words, and this pack's `checks:` line reads pull-request runs only.
- **Making any portability leg required** (`DEF-977`). Policy, the operator's, decided after
  `TP-703b` measures the slim leg.
- **Classifying a red on the board.** The census classifies by reading job logs; the board never
  does: a board read is bounded by one `gh pr list` call, and a log read per red run is not.
- **The banner's row budget.** `session_start.py::_MERGED_PR_ROWS` stays 5 (the block has a
  deadline); the board reads 20 (`ship.py::POST_MERGE_ROWS`'s window), and the two windows are
  the module's two callers' choice, not two rules.
- **`tools/cc/board.py::read_post_merge` and `read_suspects`.** The base-run reader and its
  revert logic are a different question (which merge turned `main` red) and stay as they are.
- **Disarming auto-merge or proposing a revert on a non-required red.** The leg is advisory by
  the repository's own choice; what a seat does with a `checks:` red is the protocol's, and
  `TP-703e` carries the seat's authority. This pack prints; it does not act.
- **`DEF-2025`'s skip and `DEF-5024`'s contract**, which make the legs' reds mean something
  (`TP-703b`); this pack reads what the legs say, noise included, and the roadmap's Task 0 item
  1 decides the order.

## Task 0 — Verify (try to kill this pack)

Each item names the oracle, the result that ends or holds the pack, and the exit, which is stop
and re-raise to the dispatcher, never adjust and continue.

1. *Oracle:* the census, built first as the smallest sub-task: `python3
   scripts/red_after_merge_census.py --since 2026-10-18 --at 2026-10-18T14:15:00Z` must name
   `portability (windows-latest)` red since #313 with #312 green on, and the same replay `--at
   2026-10-18T14:00:00Z` must name #313 red with #312's leg running (its run finished 14:10:49Z);
   a row whose `startedAt` is after `--at` is dropped before the latest-run choice, and one whose
   `completedAt` is after it reads as running. *Refuting result:* either replay reads otherwise,
   given that `gh pr view 313 --json statusCheckRollup` shows the rows above. *Exit:* the
   ownership or the transition rule is wrong; fix the instrument, never the figure, and if the
   rule cannot be made to name it, stop: a board line built on it would print the wrong merge.
2. *Oracle:* the same read's rows for a `StatusContext` (a row with `state` and no
   `completedAt`; `grep -n 'StatusContext' tools/cc/hooks/session_start.py` names the shape).
   *Measured 2026-10-18:* every `CheckRun` row on #312 and #313 carries `completedAt`, so the
   since clause can be dated for the three legs. *Refuting result:* a repository whose checks are
   contexts only. *Exit:* not a stop: such a check is dated by its merge and the line says
   `undated`; the module's test pins both shapes.
3. *Oracle:* `time gh pr list --state merged --limit 20 --json number,mergedAt,statusCheckRollup`
   on this repository, five runs. *Refuting result:* a median over 8 seconds (the banner's
   pull-request block budget, `docs/HOOKS.md`'s `Merged:` paragraph). *Exit:* the board reads 10
   rows, the banner keeps 5, and the module takes the limit from its caller; past 8 seconds at 10
   rows, the `checks:` line is read behind the board's `--no-fetch` flag only.
4. *Oracle:* `grep -n 'author' tools/cc/ship.py tools/cc/hooks/session_start.py` and the same
   `gh pr list` with and without `--author @me`. *Measured 2026-10-18:* identical on this
   repository (one account); on a team adopter's repository they differ, and the banner's line
   is documented as naming your pull requests. *Refuting result:* none here; the filter is the
   caller's argument (the banner passes `@me`, the board and the preflight none), and the test
   fixture carries a two-author listing so both forms are pinned.
5. *Oracle:* the roadmap's Task 0 item 1, run with `--classify` over 10-10 to 10-18. *Refuting
   result:* 80% or more of red legs are known classes. *Exit:* this pack waits for `TP-703b` W3
   and `TP-703h`; the census stays, since it is what measured the share.
6. *Oracle:* `grep -n 'def _load_' tools/cc/hooks/session_start.py` (read 2026-10-18:
   `_load_merge_rules`, `_load_mail`, `_load_seat`). *Refuting result:* the loaders are being
   unified by another open lane (the board's `overlaps:` line names the file). *Exit:* this lane
   waits for that merge, then adds the fourth loader in its shape.

## Relevant memory

Recent pattern, measured: the Windows red of 10-18 is the third fix-forward in two days that
came through a surface no required check covers (`DEF-977`'s text), and each was found by a
person reading GitHub, not by a line a tool printed. The readers that exist disagree in their
windows, their ownership rule and their words.

| Entry | Where |
|---|---|
| Parallel work protocol (item 7, a red `main`; the dispatcher's table) | `memory/parallel-work-protocol.md` |
| CI Approval Marker — Trust the Trigger, Not the OR | `docs/SHARP_EDGES.md` (section of that title) |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| 5. The null result is the signal | `docs/STANDING_PRINCIPLES.md` |
| Hook authoring (the by-path loader; fail-open with voice) | `memory/hook-authoring.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "a non-required check red
after auto-merge the banner Merged line and the board"` (the protocol first, then three root
`CLAUDE.md` sections, lexical neighbours rather than answers) and `... "a check that is not
required goes red after the merge and nobody reads it"`; re-run them rather than trusting this
list if the pack has been sitting.

## Implementation

Every fix below is a **fix shape (untested)** unless marked measured; its refutation is named.
The pack prescribes prose shapes and one tagged fence; the module's own code is the lane's to
write against the tests named here.

**1-A `tools/cc/_post_merge.py`.** The sets `CHECK_GREEN`, `CHECK_RUNNING`, `NO_VERDICT`,
`RED_BUCKETS` (the four `tests/test_hook_constant_parity.py` holds equal today, moved, not
copied; in the hook they are underscore-prefixed, `_CHECK_GREEN` and its three siblings at
`tools/cc/hooks/session_start.py:618-625`, so grep for them with the underscore and name
them bare only in the new module). `check_outcome(row)`: `session_start.py::_check_outcome`'s body, unchanged in meaning
(an unknown shape reads as running, never as a pass). `latest_run_per_check(rows)`:
`session_start.py::_latest_run_per_check`'s body. `verdicts(merged)`:
`session_start.py::_post_merge_verdicts`'s body, keyed by pull request number, newest merge
first. `transitions(merged, *, at=None)`: the merged rows sorted by `mergedAt` ascending; for each
check name the owned verdict after each merge (`verdicts` applied to the prefix), and a
transition wherever it changes, carrying the merge number, `mergedAt`, the run's `startedAt` and
`completedAt` (or `None` for a context row) and the verdict; a newer merge's green run takes the
name from an older merge's red only when its `startedAt` is after the red merge's `mergedAt`,
else both are carried and the line prints the green beside the red; with `at`, a run whose
`startedAt` is after it is dropped before the latest-run choice and one whose `completedAt` is
after it reads as still running. `read_merged(cwd, limit, gh=None, author=None)`: `gh pr list
--state merged --limit <limit> --json number,mergedAt,statusCheckRollup`, `--author <author>`
only when given, rows that are not dicts with an integer `number` dropped
(`session_start.py::_prs`'s rule). `lines(transitions)`: the words, 7-bit ASCII, one entry per
red check name, newest red first.
*Refuted if:* the ownership rule ever lets a green run that started before a red merge's
`mergedAt` clear that red; `tests/test_post_merge.py` drives the #312/#313 fixture both ways: as
measured (the Windows leg red on the newer merge, green on the older, the older's run finishing
later) the line names #313 red and #312 green beside it; with the verdicts swapped (red on #312,
green on #313 from a run that started 12:36:26Z, before #312 merged at 13:01:07Z) the line keeps
#312's red and prints #313's green as one that predates it. The mutations the tests die to: the
`startedAt` test dropped (the swapped fixture clears the red), and the ownership swapped to
oldest-first (the measured fixture names #312).

**1-B `tools/cc/ship.py`** *(fix shape, untested)*: the module joins the sibling imports, in
their existing order, and `post_merge_reds` delegates; the restated sets go.

```python target=tools/cc/ship.py
from _json_safe import decode_text_or_problem, fold_newlines, os_error_text, run_bounded  # noqa: E402
import _merge_rules  # noqa: E402  the up-to-date rule and the stale-base read, shared with the board
import _post_merge  # noqa: E402  the post-merge check verdicts, shared with the board and the banner
import _paths  # noqa: E402  the hooks-module loader behind the checkout's wiring note
```

Then `post_merge_reds(cwd)` becomes two lines: `merged = _post_merge.read_merged(cwd,
POST_MERGE_ROWS, gh=...)` with `_gh_json` wrapped to carry `cwd`, and `return
_post_merge.lines(_post_merge.transitions(merged))`; its docstring says the lines carry the
ownership rule and the since clause and name the module as the one home. (Prose, not a
fence: the fence checker resolves a prescribed name against the module as it is, and the
import above is the binding it would need.)


*Refuted if:* `_gh_json`'s signature cannot be wrapped that way (read it first: it takes `*args`
and `cwd`); then the module takes a runner the way `board.py` passes `run_`.

**1-C `tools/cc/hooks/session_start.py`** *(fix shape, untested)*: a `_load_post_merge()` in the
shape of `_load_merge_rules` (path `Path(__file__).resolve().parent.parent / "_post_merge.py"`,
a private alias in `sys.modules`); `_post_merge_verdicts`, `_latest_run_per_check` and
`_check_outcome` call through it; the four set names are deleted from the hook; `_merged_prs_line`
prints the unread clause named in Scope (in) item 3 when the loader returns `None`. *Refuted if:*
a hook test loads `session_start.py` from a scratch directory without its siblings and asserts
the red clause (then the test's fixture copies the module beside the hook, as the `Merging:`
tests do for `_merge_rules.py`; grep `_merge_rules` in `tests/test_session_banner.py` first).

**1-D `tools/cc/board.py`** *(fix shape, untested)*: `collect` reads
`_post_merge.read_merged(root, RUN_WINDOW, ...)` through `_gh_json` in its own `try`, stores
`board["post_merge_checks"] = {"transitions": [...], "window": N}` or `{"unread": reason}`;
`render` prints the `checks:` line after `main:` and before `open PRs:`, the first entry on the
label line and the rest indented ten spaces, as the other sections do; `--json` carries the key.
*Refuted if:* the board's one-read-per-section rule (each section's failure is its own line)
cannot hold because the read shares `gh`'s rate budget with `read_open_prs`; then the two reads
are one `gh` call only when both are wanted, and Task 0 item 3's timing decides.

**1-E `scripts/red_after_merge_census.py`** *(the Task 0 instrument; built first)*: flags
`--since`, `--limit`, `--at`, `--classify`, `--json`, `--repo`; the module loaded by path; the
classification buckets by the ledger rows whose anchor or text names the failing node id's file
(`task-packs/ledger.d/*.md`), with `unclassified` for the rest, and prints the known share. Its
docstring names no pack id (`tests/test_no_provenance_in_shipped_code.py` and
`tests/test_provenance_census.py` read `scripts/`). *Refuted if:* `gh run view --log-failed`
cannot be bounded on the 240-minute Windows jobs' logs; then `--classify` reads the run's job
summary annotations instead and says which.

**1-F The words and the rosters** (Scope (in) items 6 and 8), each a one-line change, with the
two syncs run and `python3 -m espalier scope-check` re-run at the end.

**Earn the red, per fix, against a named mutation:** 1-A against the ownership swap above and
against a `completedAt` after `--at` read as a verdict; 1-C against the hook keeping one set (the
replacement test reds); 1-D against the `checks:` line rendering a `no verdict` name as green
(the fixture's cancelled latest run); 1-E against the census naming #312 as the red's origin.

## Affected symbols

`/scope-check` keys on bare names. `collect`, `render` and `preflight` collide across the tree
(every CLI has a `render`; the agents' and commands' bodies name `/preflight`), so its gap list at
authoring was collisions, not files this pack misses; re-run it at the lane's start and accept
the collision gap by name.

### Changed-semantics
- `tools/cc/ship.py::post_merge_reds` (delegates; gains the ownership rule and the since clause)
- `tools/cc/ship.py::preflight` (prints the module's lines)
- `tools/cc/hooks/session_start.py::_post_merge_verdicts` (a call through the by-path loader)
- `tools/cc/hooks/session_start.py::_latest_run_per_check` (the same)
- `tools/cc/hooks/session_start.py::_check_outcome` (the same)
- `tools/cc/hooks/session_start.py::_merged_prs_line` (the unread clause)
- `tools/cc/board.py::collect` (the `post_merge_checks` key)
- `tools/cc/board.py::render` (the `checks:` line)
- `tests/test_hook_constant_parity.py::TestCheckStateSetsAreOneRule` (retired; its replacement
  pins the hook defines none of the sets)

### Renamed
- None.

### Added-paths
- `tools/cc/_post_merge.py`
- `tests/test_post_merge.py`
- `scripts/red_after_merge_census.py`
- `tests/test_red_after_merge_census.py`
- `tests/fixtures/post_merge/` (the frozen rollups of #312 and #313)

### Removed-paths
- None.

## Reach

Not a class pack: it closes no ledger class and mints no row. The rows it touches, so no later
pass reads them as shut:

Members derived by: `grep -lE 'post_merge|_merged_prs_line|portability' task-packs/ledger.d/*.md`
over live rows (re-run it; the three below are the ones whose anchor or mechanism this pack
changes).

| Item | Status | Evidence |
|---|---|---|
| `DEF-977` (no Windows check gates a merge; its anchor names `session_start.py::_merged_prs_line` as the only Windows net) | **NOT REACHED**; the net it names gains a second and third reader here, and the row's probe (Windows jobs in `test.yml`) does not move | the probe still prints 0 |
| `DEF-2025` (struck 2026-10-18; red on every post-fix macOS run) | **NOT REACHED**; this pack prints its reds, `TP-703b` W3 silences them by a counted skip | the `checks:` line names `portability (macos-latest)` until then |
| `DEF-5024` (no contract that each `SIGALRM`-arming function guards itself) | **NOT REACHED**; `TP-703b` W1 | the Windows red this pack would have named is that row's instance |

## Pass criteria

- `python3 tools/cc/board.py --json` carries `post_merge_checks`; `python3 tools/cc/board.py`
  prints the `checks:` line; no existing board, banner or ship test's assertion is weakened and
  no fixture removed; the key-set pin in `tests/test_board.py` is widened, never replaced.
- On the frozen #312/#313 fixture the module, the board line, the banner clause and the preflight
  line each name `portability (windows-latest)` red since #313 and green on #312, and
  `portability (macos-latest)` red with no green-on inside the window; replayed `--at
  2026-10-18T14:15:00Z` the census names the same, and `--at 2026-10-18T14:00:00Z` names #313
  red with #312's leg running; on the swapped fixture no surface clears #312's red.
- A board read that prints a transition for the first time appends one line to
  `.espalier-state/board-checks.jsonl`; a second read of the same state appends none; a failed
  append is a note on the `checks:` line and the section still renders.
- A check whose latest run is cancelled or stale on every row read is named `no verdict` on
  every surface, never green and never red (the two banner pins and the two ship pins stand).
- `grep -c 'frozenset' tools/cc/hooks/session_start.py` reads 5, four fewer than the 9 at
  `c8ad6d37` (the four check-state sets gone from the hook; the five other frozensets stay),
  and the replacement test reds when one returns.
- `python3 scripts/sync_vendor_cc.py` and `python3 scripts/sync_claude_mirrors.py` report clean;
  `python3 -m espalier scope-check task-packs/TP-703a-the-red-after-the-merge-has-a-reader.md`
  reports no gap but the named collisions.
- Earn-the-red recorded per fix against the mutation named in Implementation; a test that only
  ever passed does not count.
- The tier the lane earns is run with `--base origin/main` and its receipt is in the pull request
  body; a hook edit earns the full tier, both reviewers on a snapshot clone.
- No criterion here licenses shipping a defect in the reader the pack delivers: a line that names
  the wrong merge as a red's origin, or reads a `no verdict` as green, is a defect of this pack,
  not a scope-out.

## Files touched

**New:** `tools/cc/_post_merge.py`; `tests/test_post_merge.py`;
`scripts/red_after_merge_census.py`; `tests/test_red_after_merge_census.py`;
`tests/fixtures/post_merge/`.

**Modified:** `tools/cc/ship.py`; `tools/cc/hooks/session_start.py`; `tools/cc/board.py`;
`espalier/_vendor/cc/` (by `sync_vendor_cc.py` only); `espalier/managed_paths.py`;
`cc/PACK_MANIFEST.txt` (by its generator); `README.md` and `docs/QUICKSTART.md` (by
`scripts/generate_doc_regions.py`); `tests/_surface_expected.py`;
`tests/test_managed_inventory.py`; `tests/test_hook_constant_parity.py`; `tests/test_board.py`;
`tests/test_session_banner.py`; `tests/test_ship_driver.py`; `.github/workflows/portability.yml`
(the header comment only); `docs/HOOKS.md`; `.claude/commands/inbox.md` and its two mirrors (by
`sync_claude_mirrors.py` only); `CLAUDE.md` (the SessionStart row, only if the `Merged:` wording
changes).

**Deleted:** none.

**Unmodified on purpose:** `tools/cc/board.py::read_post_merge` and `::read_suspects` (Scope
out); `tools/cc/ship.py::base_red_after_merge` and `::red_base_refusal` (the base's own runs);
`.github/workflows/post-merge.yml` (`TP-703b`'s); `tools/cc/hooks/session_start.py::_MERGED_PR_ROWS`
(Scope out).

## Sub-task ordering

1. **1-E first**, the census, and Task 0 items 1 to 5 run with it (the smallest change, and the
   one that can end the pack). Before it, a seat other than the dispatcher re-runs the two `gh
   pr view` reads in Motivation and writes the stamps it gets into Landing (reasoning review
   checklist item 14, acknowledged: one seat authored the set and no figure was re-derived from
   GitHub by another). Checkpoint: the census names #313 red and #312 running at 14:00Z, and
   green on #312 at 14:15Z.
2. **1-A** the module and `tests/test_post_merge.py`, then the roster homes (1-F's first half),
   so the import-closure gate is green before any reader changes. Checkpoint: the module's tests
   and `pytest tests/test_deploy_set_import_closure.py tests/test_managed_inventory.py`.
3. **1-B**, **1-C**, **1-D** in that order (the driver, the hook, the board), each with its
   named red before its fix. Checkpoint per reader: its test file and the vendor sync.
4. **1-F**'s words and the mirror sync. Checkpoint: `pytest tests/test_operator_docs.py
   tests/test_deploy_doc_parity.py`.
5. **Red-team**, both reviewers on a snapshot clone (the hook edit earns both). What this pack
   most likely got wrong, for the pass to bite on: the transition rule reading a run that
   finished after a later merge as that later merge's verdict (the measured #312 Windows run
   finished after #313 merged); and the board's `checks:` line costing a second `gh` read that
   pushes the board past its budget on a slow link.
6. **The tier** with `--base origin/main`, then the lane ships; this file's Landing stanza.

## Estimated effort

Pack budgets on this repository have run about 2.7 times over on one measured pack (`TP-459`);
read these as the author's guess, not a schedule.

| Step | Build | Red-team and tier | Notes |
|---|---|---|---|
| 1-E census | 1.5 h | the Task 0 drive | the instrument, with its fixture |
| 1-A module and rosters | 1.5 h | 0.5 h | the bodies move; the tests are new |
| 1-B, 1-C, 1-D | 2 h | 1 h plus the full tier | three readers, one hook |
| 1-F words | 0.5 h | the doc contracts | six files, one sync each |
| Total | 5.5 h | 2 h | expect the measured overrun |

## Landing
- State: DRAFT
- Commits:
- Suite:
- Earn-the-red: per fix, against the mutation its Implementation names
- Red-team: reasoning review at authoring (the reflect skill's checklist v1, failure-mode-reviewer,
  2026-10-18): REQUEST CHANGES on the set; this file's findings: Part 2 items 1, 2, 3, 11, 13, 14
  addressed (the ownership rule keyed on the green run's start against the red's merge; the
  oracle at 14:15Z with 14:00Z pinned as running; the base-run read named as TP-703b W2's; the
  author filter from the caller; the since-before clause and the no-verdict merges; the
  transitions log for re-measure line 1); checklist item 14 acknowledged. The executor still runs
  both reviewers on a snapshot clone
- Reach: see Reach; no row closed at authoring
- Task 0: not yet run; items 2 and 4 carry authoring-time measurements (2026-10-18) that the
  executor re-runs
- Date: 2026-10-18 (authored, local)
