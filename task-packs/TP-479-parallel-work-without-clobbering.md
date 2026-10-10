# TP-479 — Parallel work without clobbering: the anti-clobber system's second generation

## Status

- Version target: after `0.8.0b2`. Built in this checkout (`win`, `lane/parallel-work`) before other lanes start, on the operator's word: "We should do this here, with this context and reasoning. The lanes can start after we build this system."
- Type: workflow infrastructure (record layout, id minting, a board, two banner and preflight checks) + process (a Core Rule and its memory note).
- **Kind: ROADMAP.** Wave A is executable now. Waves B and C carry fix shapes marked untested and wait on win-2's `TP-478` 2-B landing. Wave D is the pre-registered re-measure that decides what comes after. Each wave states its own refutation.
- **Generation 1** is the two-machine anti-clobber system of 2026-10-05: the mail channel with one ref per machine (`tools/cc/mail.py`), claims carrying row ids that the ledger verbs read (`tools/cc/ledger_row.py::_claims_in_the_way`), the record merge (`tools/cc/record_merge.py`), the conflict-marker gate, and `TP-467`'s same-machine assessment. It **detects and reconciles**. This generation **prevents by layout, ids and ownership**, and keeps generation 1 as the fallback for what is left.
- Ledger: one §3 row names this pack. It takes over `TP-478`'s 2-C, 2-D, 2-E and Wave 3 (2-A and 2-B stay win-2's, built and waiting to ship), and `TP-467` wave B. It reaches `DEF-981` (Reach).
- **The operator's decisions, 2026-10-09** (each in the operator's words where a word was given):
  - **Loader, not a committed view.** Records become per-change files read through one loader; nothing regenerates a view on `main`.
  - **Per-seat id blocks:** "Per machine id blocks, approved." The table lives in `memory/parallel-work-protocol.md` until Wave B moves it into the file the minting code reads.
  - **The up-to-date rule stays off** "if the system we are building protects from the same issues, or mitigates them, or they are made very rare." Wave D's second line decides.
  - **Own jobs, not paths:** "Own jobs, not paths approved". Task 0-D refuted path areas.
  - **TP-467 wave B pulled in:** "Pull TP-467 wave B into this build approved".
  - **The Mac (`air`) is the dispatcher,** "and take that into account when assigining its lane of work": the dispatcher carries a lighter lane.
  - **L1 to L8, all of them:** "L1-L8 lets solve them all".
- Provenance: measured on the Windows clone on 2026-10-09, alongside air's design note (`docs/design/PARALLEL_RECORDS.md` on `origin/design/parallel-records-air`, no PR), whose load-bearing claims Task 0-F checked. Every measured claim names its command.

## Motivation

The operator, 2026-10-09: "It kind of seems like this isnt working, and we are spending more time on cleanup than the extra agent is adding... All 3 agents are confused and asking to ask the other agents what to do, and each thinks a different branch is merging. There must be a better way to do this. How did old fassioned pre AI teams do it?"

**What was measured** (Task 0 has the commands):
- **Merges cost catch-ups.** 20 of the last 30 merged pull requests needed a catch-up merge of `main`, at 1.73 test runs per pull request. Replayed as GitHub merges them, 24 of 30 catch-ups conflicted (`TP-478` Task 0).
- **The conflicts are bookkeeping, not work.** Of the 93 pull requests merged from 2026-10-02 to 2026-10-09, 70 touched `task-packs/FORWARD_LEDGER.md`, 65 `task-packs/LEDGER_PROBES.json`, 53 `ESPALIER_MEMORY.md` and 52 `CHANGELOG.md`. Most conflict blocks were stored totals, and only 1 of 30 catch-ups conflicted on a source file (`TP-478` Task 0).
- **Ids collided.** `DEF-1197` was minted on two machines: the id lived only in an open pull request's diff, which no claim showed.
- **Coordination grew with each seat.** Mail between seats went from 9 messages on 10-08 to 30 on 10-09, the first full day with a third seat; 24 of the 30 were claims or releases.
- **Written rules disagreed with live settings.** Root `CLAUDE.md` Rule 10 said the up-to-date rule was on, after it was turned off that morning (live `strict=false`). The first post-merge proof run went red, and no seat owned it.
- **Throughput did not fall.** Changed lines outside record and mirror files ran 3k to 9k a day before 10-06 and 15k to 19k on 10-06 to 10-08, so "net negative" is not shown. But changed lines include cleanup, and seat time spent confused was not measurable.

**The diagnosis.** Teams of hundreds avoided this, and nothing in the measurement says agents need more than they had:
- the bug tracker was a database, not a file every change rewrites;
- changelogs were per-change fragments;
- teams owned work and did not negotiate it;
- a board, not a colleague's memory, said what was merging;
- a merge queue or a build sheriff kept trunk green.

Generation 1 grew the opposite way, adding reconciliation machinery to a shared layout. The defects kept arriving at that machinery: a merge driver GitHub never runs, a criss-cross base carrying markers nobody wrote, a `_count` field a clean merge left stale, and a refusal naming a verb that does not exist. That is `TP-475`'s question 5: the control was moved once, by consolidation, and the next move is re-targeting.

**The named user (§16).** The operator, running three seats on two machines, who saw each seat confused about what was merging and spent turns relaying between them. And every seat that lands a lane: today it pays a catch-up, a re-run and a marker re-bind for totals it never meant to change.

## Scope (in) — the waves

- **Task 0** — measured 2026-10-09 (below). Its refutation of path areas changed L4.
- **Wave A (PR-A) — rules, the live merge-rules line, the board.** Executable now; none of it touches win-2's files.
  - A-1: root `CLAUDE.md` Rule 10 corrected, with its sibling sites (`.github/workflows/test.yml`'s header and `docs/RELEASE_CHECKLIST.md`'s settings list). A new Core Rule 15, whose sole home is `memory/parallel-work-protocol.md`.
  - A-2 (L7): the SessionStart banner prints the merge rules live.
  - A-3 (L5, L4): a read-only board (`tools/cc/board.py`, read through `/inbox board`); an `assign` message type for the dispatcher; the plan pre-flight warns on a job assigned to another seat.
- **Wave B (PR-B) — ids, worktree names, stale base, one PR per seat.** Waits on 2-B.
  - B-1 (L2): minted ids from the seat's block. A linked worktree whose name is inherited is refused.
  - B-2 (L6, `TP-467` wave B): every worktree Claude Code makes gets its own seat name by code, plus the settings copy it needs to load hooks.
  - B-3 (L3): a stale-base check in the ship preflight, and a one-PR-per-seat advisory when a lane opens.
  - B-4 (L6): the Windows retire-on-clear fix for `TP-467` wave A's markers.
- **Wave C (PR-C) — records as fragments behind one loader** (L1, L8). Waits on 2-B: Session Log rows and `CHANGELOG.md` `[Unreleased]` entries as per-change files; readers take both forms before writers switch; the record-file lists swept. Also `TP-478` 2-E, the census's adjudicated table.
- **Wave D — the re-measure,** with its lines pre-registered here.

## Scope (out)

- **Ledger rows as separate files.** Rows were 3 of the 87 ledger conflict blocks (`TP-478` Task 0). Wave D's first line decides; if it fails, the rows move behind the same loader, in a lettered child of this pack.
- **Turning the up-to-date rule back on.** Wave D's second line decides, and turning it back on needs `ci_guard` to accept a head whose only new commits are merges from `main`. Today the required `verify` check binds the approval marker to the exact head (`tools/cc/ci_guard.py::pr_head_sha`), so every server-side catch-up wakes a seat to re-bind.
- **Path areas.** Refuted by Task 0-D; replaced by jobs.
- **A database for the ledger.** Air's note §4 holds, and Task 0-E confirms it: the ledger's proof layer is bound to a commit (probes, strikes in the fixing commit, pinned row shas). The board is the read side; nothing it shows is stored.
- **`TP-467` waves C and D** (singletons keyed by session, release at `SessionEnd`). Until they land, "one session per worktree" is a rule plus the `Sessions:` report, not a mechanism. Re-raised after Wave D.
- **Fragments for `docs/SHARP_EDGES.md`.** 27 of the 93 pull requests touched it, but its conflict rate was not measured; `docs/sharp-edges/` already holds split entries.
- **GitHub's merge queue.** Not offered to a repository owned by a personal account ([GitHub docs](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-a-pull-request-with-a-merge-queue): organization-owned public repositories, or Enterprise Cloud). Moving the repository is the operator's call.
- **`TP-478` 2-A and 2-B,** which stay win-2's.

## Task 0 — Verify (try to kill this pack)

Each arm names its oracle, the result, and what it would have taken to refute.

**0-A The cost is in merges, and it is bookkeeping.** RAN 2026-10-09.
- Oracle: `python scripts/merge_cost_census.py --root . --prs 30 catch-ups`, run from a `git archive origin/main` snapshot, because the script loads `tools/cc/ship.py` relative to itself.
- Result: 30 merged; 20 with a catch-up; 29 catch-ups; 52 test runs (1.73 per pull request). `TP-478` Task 0 replayed the conflicts: 24 of 30 conflicted, mostly stored totals.
- Refuting result: the cost not concentrated in record files. **Did not fire:** 1 of 30 catch-ups conflicted on source.

**0-B Which files every lane touches.** RAN 2026-10-09.
- Oracle: `gh pr list --state merged --limit 200 --json number,mergedAt,additions,deletions,files`, counting the pull requests merged since 2026-10-02 that touch each path, mirrors excluded.
- Result: 93 pull requests. The record files: ledger 70, probes 65, memory 53, changelog 52, `scripts/derived_population_census.py` 24. Shared code and docs: `docs/SHARP_EDGES.md` 27, `docs/HOOKS.md` 25, `tests/conftest.py` 25, `espalier/cli.py` 19, `session_start.py` and `_hook_utils.py` 16 each, `CLAUDE.md` 14.

**0-C The live merge settings, and what a catch-up costs under the marker.** RAN 2026-10-09.
- Oracles:
  - `gh api repos/<owner>/<repo>/branches/main/protection/required_status_checks` read `strict=false`, with 13 contexts including `verify`;
  - `.../protection` read `enforce_admins=true`, pull request required, no force push;
  - `tools/cc/ci_guard.py::pr_head_sha` and the marker docstring: the sha bound in a pull request's approval-marker title must be a prefix of the head under review;
  - 18 of the last 30 merged pull request titles carry the marker.
- Consequences:
  - A view regenerated on `main` by a job is impossible without a pull request per merge, so the loader was chosen.
  - With the rule on, every server-side catch-up of a marked pull request turns `verify` red until a seat re-binds the marker. That is why the Scope (out) row on the rule names the marker fix as its precondition.

**0-D Path areas, the design draft: REFUTED 2026-10-09.**
- Oracle: for each of the 93 pull requests, the set of code areas its changed paths fall in. Excluded: `tests/`, `docs/`, `memory/`, `task-packs/`, the root record files and the mirrors. Areas are matched by longest prefix.
- Pre-registered at the draft: the areas are worth having only if most code-touching pull requests stay in one.
- Result, 65 code-touching pull requests:

  | Split | In one area | In two or more |
  |---|---|---|
  | The draft three-way map (guard and hooks / ledger, CI and scripts / engine, recall and `.claude`) | 18 | 47 (72%) |
  | Seven top-level directories | 15 | 50 (77%) |
  | Six top-level directories | 16 | 49 (75%) |

  The commonest pairs: `espalier/` with `tools/cc/hooks/` (22), `espalier/` with `scripts/` (20), `scripts/` with the hooks (18).
- **Exit taken:** path areas dropped. The operator approved jobs (packs, waves, classes) as the unit instead. Files keep per-lane claims, since source conflicts measured 1 of 30.

**0-E The ledger's jobs survive the loader.** RAN 2026-10-09.
- Oracle: `grep -rl -E "FORWARD_LEDGER|LEDGER_PROBES" tools/cc scripts espalier --include=*.py`, excluding `_vendor`, gives 19 modules, with each reference read. Test files: 37.
- Result: the readers fall into three kinds.
  - **Path lists:** `ci_guard._RECORD_FILES`, `_hook_utils.RECORD_FILES`, `record_merge.ROSTER`, the CLI's adopter `.gitignore` negations, the managed inventory, the surface contract, the symbol and provenance censuses.
  - **Row parsers:** the probe checker, the row verbs, the record merge, the landing check, the trend, the symbol census.
  - **Readers of the stored totals:** the generator alone.
- So the totals leave the file with no hidden consumer, and every commit-bound job (probes, strikes, pinned shas, completeness) is untouched, because rows stay in the file. What Wave C must add: each new fragment directory joins the three record-file lists, which `tests/test_hooks.py::TestPostWriteCheckRecordFileMarkers` and `tests/test_ci_guard.py::TestRecordFileMarkers` pin equal.

**0-F Air's design note, checked.** RAN 2026-10-09.
- 18 modules and 34 tests read the ledger: holds as 19 and 37 by the looser grep above.
- `record_merge`'s refusal names a renumber verb that `ledger_row.py` lacks: holds (its verbs are strike, class, file, repin). win-2's `4d6e307` fixes the text.
- The local maximum mints ids: **worse than stated.** `ledger_row.py file` takes the id as a typed positional argument (`tools/cc/ledger_row.py::main`), so nothing mints.
- With clean server merges the rule costs no hand step: **wrong for this repository,** because of the marker (0-C).
- A view committed by `main`: impossible without a pull request per merge (0-C).

**0-G Today's highest ids.** RAN 2026-10-09.
- Oracle: every `origin` head except `mail/`, `record` and `HEAD`, searched for ids in `task-packs/FORWARD_LEDGER.md` and for pack files in `task-packs/`.
- Result: `DEF-1198`, `INV-31`, `TP-478`. The blocks start above them, and the shared range continues from them.

**Exit for the whole pack:** if Wave D's lines show no improvement after Waves A to C, stop and re-raise with the numbers. Do not add machinery.

## Relevant memory

Recent pattern: the expensive failures here were in the converging machinery, not in the content (`TP-478`): a merge driver GitHub never runs, a criss-cross base, a stored count a clean merge left stale. The confusion was in what each seat believed, not in the code.

| Entry | Where |
|---|---|
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| The worktrees of one clone share its machine name | `docs/SHARP_EDGES.md` |
| A per-clone identity cannot live in a tracked config file | `docs/SHARP_EDGES.md` |
| A hand-maintained doc enumeration with no code-pinned parity test rots silently | `docs/SHARP_EDGES.md` |
| GitHub's merge honours no merge driver | `docs/SHARP_EDGES.md` |
| The live working-summary doc is last-writer-wins under parallel sessions | `docs/SHARP_EDGES.md` |
| Completeness gate must discover its population | `memory/completeness-gate-must-discover-its-population.md` |
| A fixed fail-open can move rather than close | `memory/a-fixed-fail-open-can-move-rather-than-close.md` |

Resolved at authoring time by `python tools/cc/hooks/_recall.py` with `"machine name git config espalier.machine"`, `"hand-maintained list copies pinned equal parity"`, `"SessionStart banner new line byte budget bounded gh call"` and `"new tools/cc script registration vendor mirror inventory counts"`. Re-run them if the pack has been sitting.

## Implementation

### Wave A-1 The rules *(prose; landed with this pack)*

- **Rule 10** now says the rule was on from 2026-09-27 to 2026-10-09, that the post-merge proof and revert-first replace it, and that the live setting is the banner's to print.
- **The siblings** found by `grep -rn -i -E "up-to-date rule|up to date with (its|the) base|require[sd]? .{0,30}up.to.date"`, record surfaces and conditional sentences excluded: `.github/workflows/test.yml`'s header and `docs/RELEASE_CHECKLIST.md`'s branch-protection list. `.claude/commands/ship.md`'s "Behind the base" step is conditional ("a repository whose branch protection requires...") and stays.
- **Core Rule 15** carries the rule in one paragraph, with `canon: convention` until Wave A-3's board and Wave B-1's mint make parts of it mechanical. `memory/parallel-work-protocol.md` is its sole home: seats, jobs, the dispatcher, the worker's seven duties, the interim id-block table, the layers.

### Wave A-2 The merge rules, printed live (L7) *(fix shape, untested)*

- In `tools/cc/hooks/session_start.py`, beside `::_open_prs_line`, one more bounded read inside the same deadline (`::_pr_deadline`): `gh api repos/{owner}/{repo}/branches/<base>/protection/required_status_checks --jq '[.strict, (.contexts|length)]'`.
- It prints one line: `Merge rules: up-to-date OFF; 13 required checks (live)`, or ON.
- On a read failure or a missing token it prints `Merge rules: unread (<reason>)`, once, and never a guess. That is fail-open with voice (`docs/CONVENTIONS.md`).
- **Refuted if** the read pushes the pull-request block past its deadline on this host. Measure the block's added time over 10 starts. If it does, read the setting once per day into a state cache, with the cache's date printed.
- **Earn the red:** three rows (on, off, unreadable) with an injected runner. Mutation: print a constant instead of the field read.

### Wave A-3 The board, assignments, and the plan's job pre-flight (L5, L4) *(fix shape, untested)*

- **`tools/cc/board.py`** is read-only and prints in one call, live:
  - each open pull request: number, branch, merge state (`CLEAN`, `BEHIND`, `DIRTY`, `BLOCKED`), the required red holding it, auto-merge;
  - the dispatcher's current assignments, by seat;
  - live claims;
  - the latest post-merge verdict on `main` (`tools/cc/ship.py::base_red_after_merge`), and on red, the pull request whose merge commit it ran on, with the revert command;
  - the ledger's live total (the generator's print mode once 2-B lands; `scripts/ledger_trend.py::state` before);
  - the merge rules (A-2's read).
- It imports nothing from `espalier/`. It loads `mail.py` and `ship.py` as siblings, the way `ship.py` loads its own helpers. Every `gh` and `git` call passes `encoding="utf-8"` and a timeout.
- **`/inbox board`** runs it, a verb of the existing coordination command. *Amended at build (2026-10-09):* the draft made it a new `/board` command, and `tests/test_command_merge_contract.py` refused a nineteenth command against the designed band of 10 to 18 ("retire one, or raise the band ... on purpose"). The band is a deliberate limit on command sprawl, and the board belongs beside the mail, claims and assignments it reads, so it became a step of `/inbox` rather than a reason to raise the band.
- **`tools/cc/_merge_rules.py`** holds the merge-rules read that A-2's banner line and the board share, so the two readers cannot drift. Both new modules join `espalier/managed_paths.py::STANDARD_MANAGED_TOOLS`. Without that entry, SessionStart raised `ModuleNotFoundError` on a fresh install: the contract slice caught it through every test that installs into a scratch repository.
- **`tools/cc/mail.py::TYPES`** gains `assign`. Fields: the target seat in `re`, the job in `lane`, `class` or `id`. Assignments fold like claims (an `assign` followed by a later one for the same job replaces it) and are read only from the dispatcher's ref, which the board names.
- **`tools/cc/execution_plan.py::_claim_overlaps`** gains the job arm: a plan whose steps name a pack id, a `classes:` entry or a row id assigned to another seat prints one `WARN:` line, advisory, never a refusal.
- **Refuted if** the board's pull-request states disagree with `gh pr list --json number,mergeStateStatus` read in the same second (a test on the parser with recorded payloads, plus one live comparison), or if the board takes more than 10 s on this host.
- **Earn the red:** a board test fed a `DIRTY` and a `BEHIND` payload. Mutation: read `state` instead of `mergeStateStatus`. An assignment fold test. Mutation: take the first `assign` rather than the latest. The plan-warning test. Mutation: exclude the warning seat's own assignments the way claims exclude their own machine.

### Wave A: built and reviewed (2026-10-09, `lane/parallel-work`)

**What changed from the draft at build:**
- **The `Merging:` line is omitted when the read fails** rather than printing `unread (<reason>)`. A host with no `gh`, no sign-in or no GitHub remote prints no `Open PRs:` line either; the same rule keeps an adopter's banner free of a line every session cannot read.
- **Measured:** the read takes 0.48 s median and 1.57 s maximum over 8 live reads on this host. It runs after the mail read on the shared deadline, so the cross-seat line takes the budget first. The 10-start whole-block measurement stays owed.
- `/inbox board` instead of `/board`, and `_merge_rules.py` registered, as above.

**Review round** (`code-reviewer`: no blocker, 2 major, 7 minor, 1 nit; `failure-mode-reviewer`: REQUEST CHANGES, 6 gaps and 4 rough edges, no regression). Taken in one fix batch:
- **The post-merge verdict.**
  - Only `FAILURE`, `TIMED_OUT` and `STARTUP_FAILURE` are red; a skipped, neutral or action-required run is no verdict. This is the same fix in `tools/cc/ship.py::base_red_after_merge`, its sister site, with the two sets pinned equal.
  - The workflow sets `cancel-in-progress`, so one red run can carry several merges. The board now reads the last green run in a window of 20, names every pull request merged in between (GitHub's compare, the merges' first lines), and prints the revert only for exactly one.
  - A failed suspects read keeps the red.
  - On red it lists the armed pull requests that would land on it.
- **The mail sections.** A failed fetch is said. A failed read prints "unread" on the jobs line and on every pull request's seat, never "no live assignments".
- **Assignments.**
  - A job closes when its assigner or its seat releases it, by the assign's id or by its lane. Before this, only the dispatcher's ack closed one, and every finished job warned forever.
  - An unusable `dispatcher` setting fails closed.
  - `send --type assign` refuses a non-dispatcher, an unusable setting, and a linked worktree whose name is inherited (driven on real git).
  - The plan warning names the assigner, not "the dispatcher".
  - The guidance assigns whole packs by id and waves by lane alone.
- **The banner.** `_merge_rules` loads by path, like the mail module, so an older deploy set costs the line and never the banner.
- **The rules.**
  - Rule 10 says one red run can carry several merges.
  - The memory note says how to re-land reverted work, how jobs close, and that the id blocks start with minting: hand-picking a block id early would put the next seat's max+1 inside that block.

**Moved to later waves, with their reasons:**
- **Refusing to open a pull request on a red base** (except a `revert/` lane) moves to B-3: it changes the ship driver's verbs. The board lists the armed pull requests meanwhile.
- **Reading `dispatcher` from `origin/<base>`** rather than the seat's working tree. Seats on different branches could disagree.
- **A "dispatcher last seen" line,** and unanswered requests counted.
- **A `docs/SHARP_EDGES.md` row for the re-land trap** (the note carries it now).
- **Not taken:** a multi-line array of arrays at the top level of `espalier.toml` can make the line scan misread `dispatcher` as under a table. It is unlikely in that file, and it would fail closed.

### Wave B-1 Minted ids (L2) *(fix shape, untested; after 2-B merges)*

- `tools/cc/ledger_row.py::file_row`: an omitted id, or `--mint`, takes the next free id inside the seat's block for the row's kind. Taken means: present in the ledger or the probes file at `HEAD`, or named by a live claim. It mints under the ledger's existing exclusive lock, so two sessions in one checkout cannot take the same id.
- Pack numbers come from the same table, through a small `ledger_row.py mint --kind TP` verb that prints the next free number in the seat's block and writes nothing.
- **The block table** moves from the memory note into one tracked file that the code reads (candidate: `espalier.toml [parallel.id_blocks]`). `tests/test_config_fields_consumed.py` will demand its consumer. The note's table becomes a pointer.
- **Identity.** The seat's name is `git config espalier.machine`. In a linked worktree, a name not set with `--worktree` (inherited from the clone) is refused, with the two commands that set one. An unnamed clone mints from the shared range and says so once.
- **Refuted if** two seats with distinct names can mint the same id (the collision test), or if minting reads anything but `HEAD` and the claims. A mint that fetches every lane head is the interim air proposed, and it narrows the race without closing it.
- **Earn the red:** two fixture seats, `win` and `win-2`, file one row each from the same base. Hand-picked "next" ids collide (red today); minted ids do not. Mutation: drop the seat lookup (both mint from the shared range). The inherited-name refusal. Mutation: read the name without `--worktree` scope.

### Wave B-2 Every worktree gets its own seat name (`TP-467` wave B, L6) *(Task 0 first)*

- **0: read before building.** `docs/external/cc-hook-protocol.md` and `docs/external/cc-worktrees.md` on `WorktreeCreate`: whether a configured hook **replaces** git's own worktree creation (it must then create the worktree itself and print the path), and what a non-zero exit does. Drive it in a throwaway repo with `claude --worktree`.
- If the hook replaces creation, the design reads `TP-467`'s wave B text again before any code. A hook that must reproduce `git worktree add` exactly is a larger surface than naming one.
- **Fix shape:** set `extensions.worktreeConfig true` once, then `git -C <worktree> config --worktree espalier.machine <seat>-<short>`, then copy `.claude/settings.json` in (the `.worktreeinclude` rule already covers `claude --worktree`, per root `CLAUDE.md` "No banner means no hooks"), from wherever the drive shows the worktree's first moment is: the `WorktreeCreate` hook, or SessionStart's first run inside an unnamed linked worktree. **Task 0 chose SessionStart** (below).
- **Refuted if** a Claude-made worktree still answers the clone's name after the change (read back with `git -C <worktree> config --worktree --get espalier.machine`).
- **Task 0, measured 2026-10-10 on the Windows box.** Setup: Claude Code 2.1.295 and git 2.52.0.windows.1. Each arm ran one headless `claude -p --worktree <name>` session on claude-haiku-4-5 in its own throwaway repo, with every `CLAUDE*` and `ESPALIER*` variable stripped from the child. Logging hooks covered SessionStart, UserPromptSubmit, Stop and WorktreeRemove, plus WorktreeCreate in the B arms. The drive scripts and each arm's `result.json` stayed in the session scratchpad and are not committed.
  - **Read** (the 2026-10-05 refresh on PR #95; the pinned excerpts in `docs/external/` hold 2 and 1 lines on the event, against 26 and 13 in the refresh):
    - A configured `WorktreeCreate` hook **replaces** git's creation entirely.
    - `.worktreeinclude` is then not processed.
    - The hook prints the path as its last stdout line.
    - Any non-zero exit fails creation.
    - Cleanup moves to a `WorktreeRemove` hook.
    - Its payload carries `name`, not `worktree_path`; that field belongs to `WorktreeRemove`. `TP-467` item 6 said otherwise, and is corrected there.
  - **A0, default creation, no `.worktreeinclude`:** the worktree is made on `worktree-<name>`, and no hook fires in it. This repeats `DEF-1192` headless.
  - **A1 and A2, default creation plus `.worktreeinclude`:**
    - SessionStart is the first hook in the worktree, and its payload `cwd` and `CLAUDE_PROJECT_DIR` both name the worktree.
    - Before it runs, `git config --worktree --get espalier.machine` exits 128 because the extension is off. The plain read answers the clone's name (`win` in A2).
    - The SessionStart hook set `extensions.worktreeConfig true` and `--worktree espalier.machine win-t0-a2`. UserPromptSubmit and Stop then read `win-t0-a2`, and the main checkout still reads `win`.
    - `tools/cc/mail.py` reads `[machine_setting, worktree_name_inherited]` as `['win', False]` in the main checkout and `['win-t0-a2', False]` in the worktree. A hand-made control worktree that no session ran in reads `['win', True]`.
    - The repo stays at `repositoryformatversion` 0, and git honours the extension there.
  - **B1, a `WorktreeCreate` hook running `git worktree add`, setting the name and copying the settings:** WorktreeCreate fires first, with the session's own `session_id`, and its `cwd` and `CLAUDE_PROJECT_DIR` both name the main checkout. SessionStart follows in the worktree with the name already set. Claude Code holds no lock on a worktree the hook made, though it does on the git-made ones in A0 to A2.
  - **B1n, the same hook without the settings copy:** no hook fires in the worktree, so `.worktreeinclude` is not processed.
  - **B2, the hook exits 1:** `Error creating worktree: WorktreeCreate hook failed: ...`, the child exits 1, and the session never starts.
  - **Headless incidentals:**
    - No `-p --worktree` session removed its worktree at exit, and `WorktreeRemove` never fired.
    - A git-made worktree keeps `locked claude session <name> (pid N)` after that pid has exited.
- **Decision: SessionStart, not `WorktreeCreate`.**
  - The hook route rebuilds creation (the branch, the base, the settings copy, the cleanup) and loses Claude Code's lock.
  - It fails closed. An error in it (a traceback, or a missing interpreter) stops every `--worktree` session, subagent worktree and background session from starting (B2).
  - SessionStart's first run inside a linked worktree whose name is inherited (`mail.worktree_name_inherited`) gives the worktree its own name before the first prompt (A2).
  - The settings copy is the `.worktreeinclude` that `init` already writes (`espalier/cli.py::WORKTREE_INCLUDE_FILE`).
  - **Refuted if** a session launched with `claude --worktree` still answers the clone's name after its banner. A2 is the green case, and the control worktree is the red one.
- **Not covered by this route, and not driven:**
  - A subagent's `isolation: "worktree"` gets no SessionStart. A seat is a session, so it gets no seat name either, and under B-1 it cannot mint.
  - A worktree entered mid-session keeps the main checkout's project dir (`TP-467` wave C).
  - Background sessions are expected to fire SessionStart in their worktree, but this was not measured.

### Wave B-3 Stale base and one PR per seat (L3) *(fix shape, untested)*

- `tools/cc/ship.py::preflight` (and the board) compares `main`'s head now with the base sha of the pull request's last CI run. When `main` moved, and the commits since touch a path this pull request touches, or a module one import away from one, it says so and runs `catch_up`, which re-binds. Otherwise it stays silent: the merge-tested CI result stands.
- `tools/cc/ship.py::open_pr` prints an advisory when this seat already has an open pull request, keyed by the lanes its live claims name.
- `tools/cc/ship.py::preflight` refuses to open a pull request on a red base, except from a `revert/` lane, and names the armed pull requests with `gh pr merge --disable-auto <n>` (moved here from Wave A's review).
- **Refuted if** the neighbourhood rule fires on most pull requests. It would then be the up-to-date rule by another name. Count it over the first 20 ships, and re-raise above half.
- **Earn the red:** recorded payloads where `main` moved in a neighbour, and where it moved elsewhere. Mutation: compare files only, dropping the import hop.

### Wave B-4 Windows retire-on-clear (L6) *(Task 0 first)*

`tools/cc/hooks/_hook_utils.py::retire_same_window_markers` never matches on Windows: the hook's parent pid is a shell's, not the window's (seen in the A-1 lane, not chased). Drive one `/clear` on this host and record what the payload and the process tree offer before choosing a key. **Refuted if** no stable window key exists on Windows; then say so in the `Sessions:` line and ledger the remainder.

**First evidence (2026-10-10, from B-2's drive and one interactive `/clear`):**

- **The parent is the venv launcher, not a shell.** On this box the hook's parent is the venv's `python.exe` launcher, which starts the base interpreter as a child, and `claude.exe` is the grandparent (chain `python.exe <- python.exe <- claude.exe`, read through a Toolhelp snapshot in the hook). So `os.getppid()` is a pid that lives no longer than the hook. `tests/CLAUDE.md` already names the redirector.
- **A `/clear` started this session.** The predecessor's marker recorded pid 3008 and this session's marker recorded 59716. Neither process is running.
- **The session registry has the window's pid.** `~/.claude/sessions/42348.json` lists this session's id under the live `claude.exe` pid 42348.
- **Candidate keys:** the registry's pid for the payload's `session_id`, or the nearest `claude*` ancestor. Choose whichever the red proves.

### Wave B-5 Generated files in parity under the contract tier *(added 2026-10-10 at the operator's request)*

**Why.** PR-A's five `test (3.x)` cells went red on two stale deploy-inventory regions in `README.md` and `docs/QUICKSTART.md`. Wave A had added `board.py` and `_merge_rules.py`, and nobody ran `scripts/generate_doc_regions.py`. The lane earned the full tier, but the only local run was the contract slice: there were 6 GB free and another pytest was on the box. The region pin is not in that slice.

**The class, measured by collecting `-m contract` (2026-10-10).** My first cut read each pinning file's primary marker and claimed that seven of the ten mirror rows sat outside the slice. That was wrong: several of those files carry `contract` tests of their own. The drift arm below refuted it.

- **Already in the slice:**
  - the `.claude` mirrors and `harness-guard` (`test_package_resource_parity`, 27 contract tests);
  - the asset docs and the task-packs router (`test_deploy_doc_parity`);
  - both checklists (`test_shipped_asset_matches_local`);
  - the stack table;
  - the ledger regions.
- **Outside it:** `test_vendor_cc_parity`, `test_selfcheck_tests_parity` and `test_doc_regions`, with 0 contract tests each.
  - Vendor-cc's source is `tools/cc/`, and the doc regions' inputs are engine and `tools/cc/` lists. Both are full-tier paths, so neither bites a contract-tier diff. They bite a full-tier lane whose local run was only the contract slice, which is PR-A's shape.
  - The self-check mirror's source is `tests/`. An edit to a mirrored test file earns only the contract tier, locally and in CI's required cells. That is the one true contract-tier gap: a forgotten `sync_selfcheck_tests.py` merges green and reds `main` after the merge.
- **Drift arm.** A scratch worktree at `c991a38`, with one line appended to `.claude/commands/inbox.md` and no sync. `sync_claude_mirrors.py --check` exited 1. `pytest -m contract -q` gave 2 failed and 4613 passed in 1272 s, both failures in `test_package_resource_parity`. The contract slice ran 21 minutes serially on this box, under memory pressure.

**The fix.** `tests/test_generators_in_parity.py` (contract and slow) runs each generator's read-only `--check` as a child:

- the sync script of every mirror row, derived from `MIRROR_ROWS`;
- `generate_doc_regions.py` and `generate_ledger_regions.py`.

A census holds every `--check` script under `scripts/` and `tools/cc/` to "covered" or "exempt with a reason". The one exemption is `archive_transcripts.py`, whose `--check` is a dry run. All seven take about four seconds together.

**Refuted for most rows, which is why the test stays.** It closes the self-check gap. It gives the contract slice, the run a memory-short box can afford, about four seconds that catch PR-A's shape. It repeats the rows already pinned, on purpose: coverage comes from the registry, not from a hand list of which pins count.

**Earn the red:** the drift worktree above with this file copied in. That gave two reds, not one. The expected red was `sync_claude_mirrors.py`. The second was `sync_selfcheck_tests.py`, red in a clean worktree at `main` too, which is a false drift.

**The false drift.** This host runs `core.autocrlf=true`. A fresh checkout writes `espalier/_vendor/selfcheck_tests/pytest.ini` as CRLF, 104 bytes, while the sync plans LF, 100 bytes, and compares bytes. `.gitattributes` pinned `eol=lf` per extension and had no `.ini` line. This was the one unpinned file among the 159 tracked under the registry's mirrors. Every new worktree on Windows would report it, and Wave B makes worktrees the normal way to run a seat.

**Fixed:**

- `*.ini text eol=lf` added to `.gitattributes`.
- `TestEveryMirrorFileIsCheckedOutLF` checks every tracked file under a mirror path for `eol=lf`. It is red with the line removed and green with it. In a fresh worktree, the line takes the file to 100 bytes and the check to green. *(fix shape, untested; after 2-B merges)*

- **The loader** is one helper, standalone like every `tools/cc` script. It reads a fragment directory, sorted by name, together with the legacy section still in the big file (expand), and renders the view the readers want.
- **The Session Log** (`TP-478` 2-D): `/handoff` writes `memory/session-log.d/<date>-<seat>-<stem>.md`. Readers move to the loader:
  - the SessionStart digest (`tools/cc/hooks/session_start.py::_memory_headline` and its caller);
  - the cap and autoprune (`scripts/handoff_mechanics.py::memory_cap`, `::rows_to_prune`, `post_write_check`'s prune);
  - `record_merge`'s memory arm.

  Then the writer switches. The legacy table is folded into fragments only when no lane that writes it is open (contract).
- **The changelog** (`TP-478` 2-C): `changelog.d/<date>-<lane>.md`, read beside `[Unreleased]` by `espalier/changelog.py`'s parsers and folded at release (`docs/RELEASE_CHECKLIST.md`'s fold step). `CHANGELOG.md`'s `merge=union` row stays for the folded sections.
- **The census table** (`TP-478` 2-E): one entry per test file in a data directory.
- **The sweep:** each new directory joins `ci_guard._RECORD_FILES`, `_hook_utils.RECORD_FILES` and `record_merge.ROSTER` in one commit, with their parity pins. Then the inventory and gitignore lists, each with a decision on what `init` seeds.
- **Refuted if:**
  - the two-lane test conflicts. Two branches from one base each run the real writer; `git merge-tree` with every merge driver off must merge them cleanly, and the rendered view must equal both writes applied in either order.
  - SessionStart's digest gains more than 50 ms median at the current row count. Measure it before and after.
- **Earn the red:** the two-lane test is red against today's writers, since both rewrite one table.

### Wave D The re-measure *(pre-registered 2026-10-09, before any wave landed)*

1. **Merge cost.** `python scripts/merge_cost_census.py --prs 30 catch-ups conflicts` over the first 30 pull requests merged after Wave C lands. Pass: 5 or fewer of 30 conflicted catch-ups (`TP-478`'s own line). Fail: ledger rows as files, behind the loader, in a lettered child.
2. **Combination reds.** Over the first 30 merges after Wave A lands: count post-merge proof reds caused by two pull requests combining. Each is classified by reading the failure; a flake or a one-pull-request break does not count. Two or more re-open the up-to-date rule, as the operator's decision, with the marker fix first.
3. **Ids.** Zero ids minted twice after Wave B: no `record_merge` "filed on both sides" refusal, and no duplicate id in the ledger.
4. **Coordination.** Claims and releases per merged pull request over the 30 after Wave A, against the 30 before it. Hypothesis: the dispatcher's assignments halve them. Reported, not a gate.

## Affected symbols

`/scope-check` keys on bare names. `main`, `send` and `open_pr` collide across the tree, so re-run it at each wave's start rather than trusting this list.

### Changed-semantics
- `tools/cc/hooks/session_start.py::_open_prs_line` (Wave A-2: the merge-rules line beside it)
- `tools/cc/hooks/session_start.py::_memory_headline` (Wave C: read through the loader)
- `tools/cc/mail.py::TYPES` (Wave A-3: `assign`)
- `tools/cc/mail.py::live_claims` (Wave A-3: the assignment fold beside it)
- `tools/cc/execution_plan.py::_claim_overlaps` (Wave A-3: the job arm)
- `tools/cc/ship.py::preflight` (Wave B-3)
- `tools/cc/ship.py::open_pr` (Wave B-3)
- `tools/cc/ledger_row.py::file_row` (Wave B-1)
- `tools/cc/ledger_row.py::main` (Wave B-1: `--mint`, `mint`)
- `tools/cc/hooks/_hook_utils.py::retire_same_window_markers` (Wave B-4)
- `tools/cc/hooks/_hook_utils.py::RECORD_FILES` (Wave C)
- `tools/cc/ci_guard.py::_RECORD_FILES` (Wave C)
- `tools/cc/record_merge.py::ROSTER` (Wave C)
- `scripts/handoff_mechanics.py::rows_to_prune` (Wave C)
- `espalier/changelog.py::section_body` (Wave C)

### Renamed
- (none -- no symbol is renamed by any wave)

### Added-paths
- `memory/parallel-work-protocol.md`
- `tools/cc/board.py`
- `tools/cc/_merge_rules.py`

### Removed-paths
- None.

## Reach

Members derived by: the live ledger rows whose headline names what this pack's layers change (merge settings, catch-ups, id collisions, record conflicts, session markers), read one headline at a time with `grep -n "^| \`<id>\`" task-packs/FORWARD_LEDGER.md`. Re-derive at each wave.

| Item | Status | Evidence |
|---|---|---|
| `DEF-981` (three lanes livelock under the up-to-date rule) | **REACHED by the rule's removal, 2026-10-09** (live `strict=false`); its strike is due at Wave A's landing, with Wave D's second line as the condition under which it could return | 0-C's protection read |
| `TP-478` 2-C, 2-D, 2-E and Wave 3 | **MOVED here** (Wave C; Wave 3's route (b) was already taken on 2026-10-09) | win-2 adds the pointer in `TP-478` when it ships 2-B, since its branch edits that file |
| `TP-467` wave B | **MOVED here** (Wave B-2) | `TP-467` carries a pointer line |
| The double-minted id (`DEF-1197` / `DEF-1198`, no row of its own) | **TO BE REACHED by Wave B-1** | the collision test |
| `TP-467` waves C and D | **NOT REACHED** | Scope (out); re-raised after Wave D |
| `DEF-1197` itself (a zone after-check limit) | **NOT REACHED** | unrelated to this pack, despite sharing the id story |

## Pass criteria

- **Task 0:** the arms above, with their commands; 0-D's refutation and the exit taken.
- **Wave A:**
  - Rule 10 and its two siblings no longer state the rule as on. `grep` (A-1's command) finds no present-tense claim outside the record surfaces.
  - Rule 15 carries its canon and claim-id markers (`tests/test_canon_verifier_contract.py` green).
  - The memory note passes `tests/test_categorized_memory_layout.py`.
  - The board's and the banner line's earn-the-red rows were each seen red against the named mutation, and are green after.
  - The enumerator pins, the deploy-set import closure and the mirror parity are green with `board.py` and `_merge_rules.py` registered, and the command count is unchanged.
  - No existing banner, mail or plan assertion is weakened.
- **Wave B:** the collision test red then green; a Claude-made worktree reads its own name back; the stale-base rows; no `ci_guard` assertion weakened.
- **Wave C:** the two-lane test red then green; the three record-file lists equal, with the new directories; the digest's time measured and under its line; no reader of `[Unreleased]` or the Session Log red.
- **Wave D:** the four numbers recorded here with their dates.

## Files touched

- **Wave A:**
  - `task-packs/TP-479-parallel-work-without-clobbering.md` (new);
  - `memory/parallel-work-protocol.md` (new);
  - `CLAUDE.md`;
  - `.github/workflows/test.yml` (header comment);
  - `docs/RELEASE_CHECKLIST.md`;
  - `task-packs/FORWARD_LEDGER.md` (one §3 row, by hand as the §3 rows are);
  - `task-packs/TP-467-sessions-in-one-tree.md` (a pointer line);
  - `tools/cc/hooks/session_start.py`, `tools/cc/board.py` (new), `tools/cc/_merge_rules.py` (new), `tools/cc/mail.py`, `tools/cc/execution_plan.py`, with their vendor twins via `python scripts/sync_vendor_cc.py`;
  - `espalier/managed_paths.py` (the two new modules deploy), `espalier/config.py` (`dispatcher` in `FOREIGN_KEYS`), `espalier.toml` (`dispatcher = "air"`), `examples/espalier.toml` (regenerated);
  - `.claude/commands/inbox.md` (the `assign` type, `assignments`, `board`), with its mirrors via `python scripts/sync_claude_mirrors.py`; `docs/CHEAT-SHEET.md` and its asset mirror;
  - the tests for each;
  - the surface counts and tables `espalier/surface_impact.py` names;
  - `CHANGELOG.md`.
- **Wave B:**
  - `tools/cc/ledger_row.py`, `tools/cc/ship.py`, `tools/cc/hooks/_hook_utils.py` and whatever B-2's Task 0 decides, with their vendor twins;
  - the block table's file;
  - tests;
  - `docs/HOOKS.md` (if a hook event is added).
- **Wave C:**
  - the loader;
  - `scripts/handoff_mechanics.py`, `tools/cc/hooks/session_start.py`, `tools/cc/hooks/post_write_check.py`, `tools/cc/record_merge.py`, `tools/cc/ci_guard.py`, `tools/cc/hooks/_hook_utils.py`, `espalier/changelog.py`;
  - `.claude/commands/handoff.md` and its mirrors;
  - the fragment directories;
  - tests.
- **Unmodified on purpose:**
  - `TP-478` (its branch is win-2's);
  - the ledger's row grammar;
  - every `ci_guard` assertion;
  - the record merge's refusals.

## Sub-task ordering

1. Task 0 (done, above). Checkpoint: its records in this pack.
2. Wave A-1, the rules: the smallest change. Checkpoint: the contract slice and the recall tests.
3. Wave A-2, then A-3. Checkpoint: their earn-the-red rows, the enumerator pins, the mirror parity.
4. Red-team Wave A (`code-reviewer`, and `failure-mode-reviewer` for the hook and the command body), one fix batch, the proof tier, **PR-A**.
5. Wait for 2-B to merge (win-2 ships it after the Mac lands #164 and #158). If it stalls, build Wave B on win-2's branch: it is in this clone, and the repository merges with merge commits.
6. Wave B-2's Task 0 first, then B-1, B-3, B-4. Red-team, proof tier, **PR-B**.
7. Wave C. Red-team, proof tier, **PR-C**.
8. Wave D, over the next 30 merges. Then re-raise with the numbers: `TP-467` C and D, rows as files, the rule.

**Coordination.** One open pull request from this seat at a time (Rule 15). The claim for Wave A was sent 2026-10-09 (`20261009T222058Z-win-0b79df`). Waves B and C touch files win-2's 2-B also touches (`ledger_row.py`, `record_merge.py`); they start only after it merges.

## Estimated effort

| Step | Budget |
|---|---|
| Task 0 | done (about 2 h, this session) |
| Wave A (rules, banner line, board, assign, plan arm, red-team) | 5 h |
| Wave B (mint, worktree names with its Task 0, stale base, retire-on-clear, red-team) | 6 h |
| Wave C (loader, two records, census table, sweep, red-team) | 6 h |
| Wave D | measurement over the next 30 merges; 1 h to read |
| **Total** | **about 18 h of build, three PRs** |

**Most likely to be wrong:**
- that seats use the board before stating state. A rule that relies on remembering is the failure mode Core Rule 14 names. Wave D's fourth number is the only witness, and it is indirect.
- that the dispatcher keeps up when it is prompted only now and then. Queues two or three deep are the hedge; watch for seats idling on requests.
- the stale-base neighbourhood. One import hop is a guess.
- `WorktreeCreate`'s contract (Wave B-2's Task 0 decides it).
- that a loader stays simple. It becomes the new place defects arrive (`memory/a-fixed-fail-open-can-move-rather-than-close.md`); its red-team asks for that by name.

## Landing

- State: ROADMAP
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
