# TP-478 — Converge concurrent writes: derive what two lanes recompute, then batch the merges

## Status

- Version target: unscheduled (self-host workflow; adopters inherit only Wave 1's guard and, if
  they opt in, the queue-aware ship driver)
- Type: workflow / CI infrastructure, plus one test-isolation guard
- Kind: ROADMAP — Task 0 and Wave 1 are executable here; Waves 2 and 3 are routed, and Wave 2's
  ledger half spawns a lettered child only if Task 0 earns it
- Drafted 2026-10-09 by win-2 on the operator's approval of the proposal "agents append their
  changes to a log that is auto-converged; batch the writes"

## Motivation

The operator asked whether every race between agents could be replaced by agents appending to a
log that is converged afterwards, and whether the writes could be batched. Two different races
were in play on 2026-10-08, and the log idea fits one of them:

1. **Concurrent edits to committed record files.** Two lanes merged one after the other conflict
   on files both rewrite. Measured over the last 30 merged pull requests (#128 to #159, read
   2026-10-09; method below): 20 of 30 needed at least one catch-up merge of main (30 catch-ups
   in all), and the `test.yml` workflow ran 54 times where 30 would have sufficed, plus 3 manual
   re-runs. Replaying those 30 catch-up merges with `git merge-tree` **as GitHub sees them**
   (the repository's `CHANGELOG.md merge=union` attribute overridden in a scratch clone, since
   GitHub's merge honours no driver): 24 of 30 conflicted. Conflicting files: the ledger 20,
   the probes roster 17, `CHANGELOG.md` 10, `ESPALIER_MEMORY.md` 9,
   `scripts/derived_population_census.py` 4, one test 1. **Measured.**
2. **Runtime interference over live state** (DEF-1169's `dist/`, DEF-973's `reports/`): nobody
   wants those writes kept, so logging them does not help; isolation does (Core Rule 14).

The measurement that decides the design: classifying every conflict block in those replays,
**73 of the ledger's 87 conflict blocks are derived counts** (the headline split, the class
index, section headings), **16 of the probes roster's 19 are its `_count` field**, and only
3 member rows, 3 probe entries and 2 Appendix B rows collided. **Measured, by a regex
classifier — probable, not exact; 9 ledger blocks classed "prose/other" are unread.** Rows two
lanes write rarely collide; the aggregates both lanes recompute almost always do.

So the operator's idea is right in its essence — append facts, derive the totals — and its
cheapest form is to **stop committing derived aggregates where two lanes rewrite them**. That
is also the prerequisite for batching: GitHub's merge queue performs GitHub's merge, which
cannot run `tools/cc/record_merge.py`, so with 24 of 30 catch-ups conflicting, a queue would
eject most pull requests today (**hypothesis — the queue's behaviour on a conflicting entry is
documented by GitHub, not driven here**).

Authoring-time method (scratch scripts, not in the tree; Task 0-A lands their replacement):
- catch-ups per PR: `gh pr list --state merged --limit 30 --json number,headRefName,commits`,
  counting commits whose headline matches `^Merge (remote-tracking )?branch '(origin/)?main'`;
  runs per PR: `gh run list --workflow test.yml --branch <head> --json conclusion,attempt`.
- conflicts: for each catch-up commit `C`, `git merge-tree --write-tree --name-only C^1 C^2` in a
  `git clone --shared` scratch clone whose `.git/info/attributes` reads `CHANGELOG.md merge=text`.
- blocks: the same replay without `--name-only`, `git cat-file -p <tree>:<path>`, each
  `<<<<<<<`..`>>>>>>>` block classified by the lines it spans.

## Scope (in)

- **Task 0** — land the measuring script, re-measure, decide which waves to build.
- **Wave 1** — runtime races: widen the suite's live-tree guard to the packaging dirs, and
  isolate every writer it finds.
- **Wave 2** — make record writes commute, per file, in the order Task 0 ranks them:
  - 2-A the probes roster's `_count`;
  - 2-B the ledger's derived regions (counts out of the committed conflict surface);
  - 2-C `CHANGELOG.md` `[Unreleased]` as fragment files folded at release;
  - 2-D `ESPALIER_MEMORY.md` Session Log rows as per-handoff fragments;
  - 2-E `scripts/derived_population_census.py::ADJUDICATED` as per-test-file entries.
- **Wave 3** — the merge queue: `merge_group` triggers, the approval marker in a queue, the ship
  driver's queue path. Gated on Wave 2 and on an operator settings change.

## Scope (out)

- **A full event log for ledger ROWS** (every verb appends an event file; the ledger is rendered).
  Deferred because Task 0's block census puts row collisions at 8 of 106 blocks; revisit if the
  re-measure after Wave 2 shows rows dominating (a lettered child of this pack would carry it).
- **The mail channel** — already an append-only per-machine log with claims as a fold; nothing
  to converge.
- **The per-checkout candidate log** that makes `scripts/check_handoff_landing.py`'s key arm red
  from a worktree on another checkout's held key (seen 2026-10-09) — a different defect; file it
  as its own row if it recurs.
- **Runtime races beyond the packaging dirs** (sys.modules double-loads, timing ratios) — their
  own classes with their own oracles.
- **Changing branch protection** — the operator's act, never this pack's; Wave 3 prepares the
  workflows and the driver and stops at the settings page.

## Task 0 — Verify (may end the pack)

**0-A Land the oracle.** Add `scripts/merge_cost_census.py` (self-host tooling, stdlib + `git` +
`gh`), three reports over the last `--prs N` merged pull requests:
`catch-ups` (per PR: catch-up merges, `test.yml` runs and attempts), `conflicts` (replay each
catch-up in a temporary `git clone --shared` with every `.gitattributes` merge driver overridden
to `merge=text` in its own `info/attributes`, never the shared repository's), and `blocks`
(per conflicted record file, conflict blocks classed derived-count / row / index / other).
Fix shape: the authoring-time scratch scripts' logic, above. Refuted if its numbers on the same
30 PRs differ from the Motivation's — then one of the two is wrong; find which before anything else.

**0-B Re-measure** with `python scripts/merge_cost_census.py --prs 30 catch-ups conflicts blocks`.

**0-C Drive the queue's marker.** `harness-guard.yml` says a `merge_group` run "carries no title,
so ... a merge-queue run on a protected change fails closed". In a scratch repository with a
merge queue (or GitHub's documented payload), establish whether the queued PR's number is
recoverable in a `merge_group` run (hypothesis: from `merge_group.head_ref`,
`gh-readonly-queue/<base>/pr-<N>-<sha>`) and its title readable by API, so `ci_guard` can bind
the marker to the PR head it already verified.

**Refuting results and exits (pre-registered):**
- Over the latest 30 merged PRs, test runs per merged PR at or below 1.2 (1.8 at authoring) **and**
  conflicted catch-ups at or below 5 of 30 (24 at authoring): the cascade no longer costs enough —
  **do not build Waves 2-3**; build Wave 1 alone and record the numbers.
- Derived-count blocks fall below half of all record conflict blocks: the cheap design does not
  reach the cost — **stop and re-raise** with the block census (the full event log is then the
  candidate, as a lettered child of this pack).
- 0-C finds no way for the marker check to pass in a `merge_group` run without weakening it:
  **Wave 3 is not built**; Waves 1-2 still stand on their own (fewer conflicts, fewer catch-ups).

## Relevant memory

Recent pattern: the expensive failures here were in the converging machinery, not the content —
a merge driver GitHub never runs, a criss-cross whose virtual base carried markers nobody wrote,
a `_count` field a clean text merge left stale.

| Entry | Where |
|---|---|
| GitHub's merge honours no merge driver, so a `.gitattributes` `merge=` row cannot keep a pull request mergeable | `docs/SHARP_EDGES.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| A pack's prescribed fix code is a claim — test it before you trust it | `memory/a-packs-prescribed-fix-code-is-a-claim.md` |
| Spawned agents share one worktree + index — isolate mutate-capable fan-outs | `docs/SHARP_EDGES.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "two lanes conflict on the ledger
and memory file at catch-up"` and `"isolate shared state a parallel test writes"`; re-run them
rather than trusting this list if the pack has been sitting.

## Implementation

### Wave 1 — the live-tree guard reads the packaging dirs

**1-A** *(fix shape, untested)*: add `dist` and `build` to `tests/conftest.py::_LIVE_TREE_WATCH`.
DEF-1169 escaped this guard because it watches `bench/results` and `reports` only; the wheel
fixture's litter witness caught it instead, as a red on whichever PR overlapped. **Refuted if** the
first full tier with the widened watch reds on more writers than can be isolated in this wave —
then land the watch with a dated, named baseline (the `_LIVE_TREE_ALLOWED` shape) and ledger the
remainder, never widen silently.

**1-B** For each writer 1-A names: isolate by construction (a per-call temporary directory, as
`scripts/release_check.py::check_release_archive_builds_and_clean` now does). Earn-the-red: the
watch reds on the writer before its fix, on a run that drives it beside the guard.

### Wave 2 — record writes that commute

The shared acceptance oracle for every 2-x: a synthetic two-lane test — two branches from one base,
each applying the real verb, merged by `git merge-tree` with all merge drivers off — merges
clean, and the rendered result equals the two verbs applied in either order.

- **2-A Probes roster `_count`** *(fix shape, untested)*: stop storing it; every reader derives
  `len(probes)`. Readers span `tools/cc/` (`check_ledger_probes`, `ledger_row`'s
  `--reconcile-count`, `record_merge`'s settle step), `scripts/` (the landing check, the rebuild
  assembler) and their tests — enumerate with `grep -rln '"_count"' tools scripts tests`, never
  from this list. **Refuted if** a reader uses the
  stored count as an independent witness against a hand edit (the `--reconcile-count` docstring
  says it is "a hand edit's only trace") — then the witness needs another home before the field
  can go.
- **2-B Ledger derived regions** *(design open; Task 0 picks)*: the counts
  `tools/cc/generate_ledger_regions.py::find_drift` maintains must leave the lines two lanes both
  rewrite. Candidates, cheapest first: (i) render them on read (a print mode added to
  `generate_ledger_regions.py`, whose modes today are `--check`, `--write` and `--json`) and
  commit only a pointer line; (ii) keep them in a separate generated file that is
  never hand-merged and is regenerated by `record_merge` and checked by CI. Either way the gate
  `tests/test_generate_ledger_regions.py::TestTheLiveLedgerConverges` keeps holding the counts to
  the rows. **Refuted if** the operator wants the counts readable on GitHub without a command —
  then (ii), with CI regenerating rather than lanes. Member rows inserted in id order rather than
  at a class's first slot is a cheap add-on if Task 0's row blocks are not noise.
- **2-C `CHANGELOG.md`** *(prior art: towncrier, changesets, reno; fix shape, untested)*: each
  lane adds `changelog.d/<date>-<lane-slug>.md`; a fragment reader added beside
  `espalier/changelog.py`'s section parsers concatenates them, and the release fold (today a
  manual step, `docs/RELEASE_CHECKLIST.md`'s "CHANGELOG fold") folds the result into the new
  version. The `merge=union` row stays for the folded section. **Refuted if** a reader or gate
  needs `[Unreleased]`'s live content between releases (the changelog tests, `/handoff`'s
  changelog arm) — enumerate them in Task 0 first.
- **2-D `ESPALIER_MEMORY.md` Session Log** *(fix shape, untested)*: `/handoff` writes
  `memory/session-log.d/<date>-<machine>-<stem>.md`; the table is rendered from those plus the
  cap. Touches `scripts/handoff_mechanics.py`, the `post_write_check` autoprune and
  `record_merge`'s memory arm. **Refuted if** the SessionStart digest must read the table
  directly and rendering adds measurable start-up time.
- **2-E `derived_population_census.py::ADJUDICATED`**: one entry per test file in a data
  directory, keyed by path.

### Wave 3 — the merge queue (after Wave 2, and after the operator enables it)

- **3-A** `merge_group:` triggers on every required workflow (`test.yml`, `harness-guard.yml`,
  `clean-checkout.yml`, and whatever `tests/test_required_status_checks.py` derives as required).
- **3-B** `tools/cc/ci_guard.py` binds the marker in a `merge_group` run by 0-C's recovered PR,
  replacing the fail-closed branch the workflow comment describes.
- **3-C** `tools/cc/ship.py`: `open` enqueues (`gh pr merge --auto` already does so when a queue is
  on); `catch_up` becomes the fallback for a lane the queue ejected; `status` reads queue
  position.

## Affected symbols

### Changed-semantics
- `tests/conftest.py::_LIVE_TREE_WATCH`
- `tools/cc/generate_ledger_regions.py::find_drift`
- `tools/cc/generate_ledger_regions.py::apply_writable`
- `tools/cc/record_merge.py::merge_ref_in`
- `tools/cc/ledger_row.py::strike`
- `tools/cc/ledger_row.py::file_row`
- `tools/cc/ledger_row.py::repin`
- `tools/cc/ship.py::open_pr`
- `tools/cc/ship.py::catch_up`
- `tools/cc/ship.py::_merge_base_first`
- `tools/cc/ci_guard.py`
- `scripts/derived_population_census.py::ADJUDICATED`
- `scripts/handoff_mechanics.py`
- `espalier/changelog.py`
- `docs/RELEASE_CHECKLIST.md`

### Renamed
- None.

### Added-paths
- `scripts/merge_cost_census.py`
- `changelog.d/`
- `memory/session-log.d/`

### Removed-paths
- None.

## Reach

Members derived by: `python scripts/merge_cost_census.py --prs 30 conflicts` (scope: catch-up
merges on the last 30 merged pull requests, replayed with merge drivers off; a file absent from
that window is not shown to be safe — re-run on a wider window before calling the class closed).

| Member (file both lanes write) | Conflicts / 30 at authoring | Wave | Status |
|---|---|---|---|
| `task-packs/FORWARD_LEDGER.md` | 20 | 2-B | open — counts only; rows go to a lettered child if they come to dominate |
| `task-packs/LEDGER_PROBES.json` | 17 | 2-A | open |
| `CHANGELOG.md` | 10 | 2-C | open |
| `ESPALIER_MEMORY.md` | 9 | 2-D | open |
| `scripts/derived_population_census.py` | 4 | 2-E | open |
| `tests/test_declared_limits_contract.py` | 1 | — | **NOT REACHED**: a one-off edit collision, not a shared record |

Runtime class (Wave 1): members derived by the first full tier with the widened watch; DEF-1169
(closed by #159) is the founding instance and DEF-973 (`reports/cc_surface_gate.json`) is a known
member under the existing watch.

## Pass criteria

- Task 0's three reports are reproducible from `scripts/merge_cost_census.py` alone.
- Wave 1: no live-tree writer is silenced; each named writer is isolated or baselined with a reason.
- Wave 2, per file: the two-lane synthetic merge is clean with drivers off, and
  `TestTheLiveLedgerConverges` (and each file's own gate) still binds the derived values to their
  sources — no gate weakened, no assertion removed.
- After Waves 2-3 land, re-run over the next 30 merged PRs (pre-registered): conflicted catch-ups on
  Wave 2's files at most 2 of 30, and test runs per merged PR at most 1.2.

## Files touched

- New: `scripts/merge_cost_census.py`; `changelog.d/` and `memory/session-log.d/` (Wave 2);
  tests beside each wave.
- Modified: `tests/conftest.py`; `tools/cc/generate_ledger_regions.py`; `tools/cc/record_merge.py`;
  `tools/cc/ledger_row.py`; `tools/cc/check_ledger_probes.py`; `tools/cc/ship.py`;
  `tools/cc/ci_guard.py`; `scripts/derived_population_census.py`; `scripts/handoff_mechanics.py`;
  `espalier/changelog.py`; `.github/workflows/*.yml` (Wave 3); their vendor mirrors.
- Unmodified on purpose: `tools/cc/mail.py` (already a log); branch-protection settings.

## Sub-task ordering

1. Task 0 (0-A, 0-B, 0-C) — checkpoint: the census prints; the exits above are applied.
2. Wave 1 — checkpoint: a full tier with the widened watch.
3. Wave 2 in Task 0's rank order (2-A first: smallest, measured second-largest) — checkpoint per
   file: its two-lane synthetic merge and its own gate.
4. Red-team (code-reviewer + failure-mode-reviewer) on Waves 1-2.
5. Wave 3, after the operator enables the queue — checkpoint: one real queued PR merges, one
   protected change verifies in its `merge_group` run.
6. The post-landing re-measure against the pass criteria.

## Estimated effort

Task 0: half a day (0-C is the unknown). Wave 1: 2-4 hours plus a full tier. Wave 2: 2-A an
hour; 2-B a day; 2-C half a day; 2-D a day; 2-E two hours. Red-team: half a day. Wave 3: a day
after the setting. Likely wrong first: 2-B's readers of the counts (the banner, tests, the record
snapshot) are more numerous than the generator's own tests show — enumerate them in Task 0.

## Landing
- State: ROADMAP
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
