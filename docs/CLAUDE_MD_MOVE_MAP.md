# Root CLAUDE.md move-map (assign 9587e7)

**Status: a proposal for the operator's ruling. Nothing in `CLAUDE.md` is cut on
this branch.** This file is the lane's working map; the commit that makes the
cut deletes it. Read at origin/main `caa80243`, where `CLAUDE.md` is 54,313
bytes and 430 lines.

The operator's constraint: nothing leaves unless a named destination already
holds it or the lane moves it there. The assign's targets: each hook-table row
to one line pointing at `docs/HOOKS.md`; Core Rules 10 and 15 to the rule plus a
pointer.

## What the cut buys

A draft of the whole cut was built in a scratch export of `caa80243` (never in
this tree): `CLAUDE.md` 54,313 -> 38,985 bytes, 15,328 fewer (28%).

| Passage | Now (bytes) | Draft (bytes) |
|---|---:|---:|
| Hook table, 12 rows | 14,576 | 3,097 |
| `session_start.py` row alone | 5,560 | 387 |
| Core Rule 10 | 3,460 | 833 |
| Core Rule 15 | 2,247 | 1,025 |

The one-line form is the shape `init` already writes into an adopter's
`CLAUDE.md` (`espalier/cli.py:3236-3249`).

## How "held" was decided

Each passage was split into clauses, one fact each (a banner line, a
condition, a figure, a file, an id), and each clause was looked up in its
destination: **held** (the destination states the same fact), **partial** (it
drops a sub-fact, named below) or **not held**. Each verdict cites the
destination line, read and tagged verified or probable. The clause reads were
four read-only dispatches under the assign's `anchors` allowance. A mechanical
check ran beside them: every backticked name, id, env var and figure in a
passage, searched for in its destination. Where the two disagreed (five tokens
in the `session_start.py` row), the lines were read by hand. `docs/HOOKS.md`
spells the figures out ("fifteen seconds", "two and a half seconds"), so the
clause reads were right.

| Passage | Clauses | Held | Partial | Not held |
|---|---:|---:|---:|---:|
| `session_start.py` | 82 | 71 | 3 | 8 |
| `task_router.py` | 34 | 29 | 1 | 4 |
| `write_guard.py` | 44 | 37 | 2 | 5 |
| `plan_guard.py` | 6 | 6 | 0 | 0 |
| The other eight rows | 74 | 70 | 3 | 1 |
| Core Rule 10 | 35 | 29 (3 only in code comments) | 3 | 3 |
| Core Rule 15 | 27 | 26 | 1 | 0 |

## Where each section is recalled from

- `/recall` indexes root `CLAUDE.md` one `## ` section at a time
  (`tools/cc/hooks/_recall.py:777`).
- **Core Rules** carries `<!-- recall: skip -->` (`CLAUDE.md:81`), so cutting
  Rules 10 and 15 moves nothing in recall. Rule 10's new home is a `memory/`
  note, which recall does index, so the cut adds recall reach there.
- **Hooks (Mechanical Enforcement)** is indexed, and its table is its body.
  `docs/HOOKS.md` is **not** indexed on this repository: it is gated off at
  `_recall.py:1087`, after a 2026-10-18 measurement in which indexing it moved
  14 recall pins. So hook detail that leaves `CLAUDE.md` for `docs/HOOKS.md`
  leaves `/recall` on this tree. An adopter tree indexes the seeded
  `docs/HOOKS.md`, so the loss is this repository's alone.

Measured on the scratch export with `scripts/recall_eval.py --root` (draft cut
plus the new Rule 10 note, against the unmodified export, which reproduces the
live tree's figures exactly):

- **Aggregate arms (by heading): unchanged.** heading@1 83.4% -> 83.5% (326 ->
  327 docs), stripped 81.5% -> 81.2%, paraphrase 37.5% both, task control@4
  4.0% -> 5.3%. The lines-delivered counts that `/recall`'s body quotes move by
  one document (2:60/3:221/4:45 -> 2:60/3:221/4:46).
- **Targeted queries (by content):** 11 queries written from the cut text. This
  is a worst-case pick, not a sample. Before the cut, the Hooks section answers
  7 of them first. After it:

| Query | Before (first) | After (first) |
|---|---|---|
| Loose line orphaned python processes by PID | Hooks | Getting Started (its step 0 holds it) |
| session start banner cut at the wall timeout | Hooks | `memory/hook-authoring.md` |
| reads of secret-bearing paths ... denied | Hooks | SHARP_EDGES `Read()` entry, then Hooks |
| stop hook handoff hold one open pull request per seat | Hooks | Hooks |
| leftover worktrees removed at session start | Hooks | SHARP_EDGES worktree entries |
| Engine line test interpreter imports espalier from elsewhere | Hooks | `memory/parallel-work-protocol.md` (wrong) |
| threshold handoff context tokens | Hooks | Hooks |
| required checks eleven since the floor moved | parallel-work-protocol | the new Rule 10 note |
| post-merge run suspects red still going or no verdict | parallel-work-protocol | the new Rule 10 note |

The rows keep the banner lines' names because those names are what people
query by. Even so, 4 of the 7 hook queries leave the Hooks section, one of
them for a wrong document. This is ruling R1 below.

## A. The hook table (`CLAUDE.md:171-182`)

**Destination:** `docs/HOOKS.md` sections 1-12, which the lane edits **before**
the cut (it is byte-mirrored to `espalier/assets/docs/HOOKS.md`, so the edit
runs that mirror's sync). Each new row ends by naming its HOOKS.md section.

**Moved into `docs/HOOKS.md` by the lane** (the not held and partial clauses,
verbatim from the row):

| Row | Clause | To |
|---|---|---|
| `session_start.py` | advances the blueprint chain (starts a new node) on source `startup`/`clear`; `resume`/`compact` load read-only, bootstrapping only if none exists | section 1 |
| `session_start.py` | the catch-up is the one SessionStart job that changes the tree | section 1 |
| `session_start.py` | cleans per-session flags | section 1 |
| `session_start.py` | `Orders:` is reporter only | section 1 |
| `session_start.py` | the wall is `_WALL_SECONDS`; the `Engine:` probe is `find_spec` | section 1 |
| `session_start.py` | a slow `gh` **or fetch** costs the pull-request lines first; the `Seat:` refusal prints **the commands** | section 1 |
| `task_router.py` | the hold's verbs include **restore**; for a lane left unfinished, the unfinished handoff again, never a commit | section 2 |
| `write_guard.py` | secret-path reads are denied for **read-only tools** as well as Bash and PowerShell; the set is enumerated in `write_guard.check_secret_path_access`; it is **not** a protected zone | section 4 |
| `write_guard.py` | why the `Read()` deny rules went: any `Read()` rule arms a permission prompt bypass mode cannot suppress | section 4, replacing the back-pointer at `docs/HOOKS.md:2250` |
| `write_guard.py` | the start-or-refuse rule covers the ship driver's imports | section 4 |
| `subagent_stop.py` | Gate 4 **only** | section 10 (the draft row keeps it too) |
| `post_write_check.py` | the `docs/incidents/2026-09-17-real-shell-fixture-wipe.md` citation, rules 1 and 2 | section 6 |

**Kept in `CLAUDE.md`'s one-line rows:** the ledger and pack ids (TP-467,
DEF-3015, DEF-4058, DEF-4083, DEF-946, DEF-5087) and "this tree: 200000".
`docs/HOOKS.md` is deployed to adopters and carries no internal id today
(count 0; `docs/CLAUDE.md`: "Keep internal pack IDs out of adopter-facing
docs"). Each id's own row file exists under `task-packs/`. Keeping them costs
about 70 bytes.

**Retired, not moved:** `post_write_check.py` "Validates each written file for
JSON validity and path consistency". The hook validates
`.claude/settings.json` as JSON and the `.claude/` bodies' placeholders and
frontmatter (`tools/cc/hooks/post_write_check.py:1523-1530`), and has no path
consistency check. `docs/HOOKS.md` section 6 states the true scope. The new row
says what the code does.

**A back-pointer the cut would break.** `docs/HOOKS.md:2250` says "(see
`CLAUDE.md`'s hook table for why)". The reason lives in
`docs/SHARP_EDGES.md:2581`, which is not deployed to adopters, and the
adopter's own `CLAUDE.md` hook table has no such reason (the template is at
`espalier/cli.py:3236-3249`). So the pointer already leads nowhere on every
adopter tree today. The lane writes the one-sentence reason in its place,
which fixes both trees.

**The draft rows** (from the scratch build; the lane's text may tighten):

```
| `session_start.py` | SessionStart | Loads the blueprint chain and prints the banner -- `OPEN PLAN`, `Loose:`, `Sessions:`, `Permissions:`, `Own-clear:`, `Checkout:` and `Worktrees:` (its one job that changes the tree), `Open PRs:`, `Merged:`, `Mail:`, `Orders:`, `Seat:`, `Engine:` -- cut short at a 13 s wall with a `Cut:` line (TP-467, DEF-3015); HOOKS.md section 1 | No (protocol) |
| `task_router.py` | UserPromptSubmit | Classifies prompt scope and injects routing guidance; past `handoff_context_tokens` (this tree: 200000) asks for the threshold handoff on every prompt; says the own-clear marker's refusal or hold and the Stop hook's handoff hold while they stand (DEF-4058, DEF-4083); HOOKS.md section 2 | No (advisory) |
| `write_guard.py` | PreToolUse (`*`) | Anti-self-disable floor: denies a set kill-switch, mutations of the protected zones (`tools/cc/`, `cc/`, the settings and integrity files; `espalier/` and `.github/workflows/` here) and of the adopter's `protected_paths`/`generated_paths`, dangerous shell patterns, and reads of secret-bearing paths; refuses naming the file and line when it cannot start (DEF-946, DEF-5087); HOOKS.md section 4 | **Yes** |
| `plan_guard.py` | PreToolUse (`Write\|Edit\|NotebookEdit`) | Blocks Write/Edit/NotebookEdit on source files without an active execution plan; HOOKS.md section 3 | **Yes** |
| `config_guard.py` | ConfigChange | Refuses a settings change that turns the hooks off, loosens a gate or unwires one, judged against what SessionStart recorded; audits managed `policy_settings`; HOOKS.md section 5 | **Yes** for project/local/user |
| `post_write_check.py` | PostToolUse (`Write\|Edit\|NotebookEdit\|Bash\|PowerShell\|mcp__.*`) | Checks what a write left: `.claude/settings.json` as JSON, the `.claude/` bodies' placeholders and frontmatter, and on this tree a `.py` file that hands built text to a shell beside a recursive delete of a variable and a glob; HOOKS.md section 6 | No (tool already ran) |
| `reflect_trigger.py` | PostToolUse (`*`) | Runs the reflect protocol every 10th source write; opens `cc/execution_plan.json` from an approved plan-mode plan; HOOKS.md section 7 | No |
| `stop_gate.py` | Stop | Five gates: pytest (opt-in, `ESPALIER_STOP_GATE=full`), docs refresh, code review, the handoff gate (Gate 5: once per unpushed commit where `handoff_push = true`, held while this seat has a pull request open), blueprint finalize; HOOKS.md section 9 | **Yes** |
| `subagent_stop.py` | SubagentStop | Appends subagent reasoning to the active blueprint (Gate 4 only); never blocks; HOOKS.md section 10 | No |
| `post_compact.py` | PostCompact | Captures the compaction summary (`cc/_working_summary.md`) and arms the post-compaction checkpoint; HOOKS.md section 8 | No |
| `subagent_start.py` | SubagentStart | Injects cold-subagent orientation; snapshots the dirty markdown for a docs-gate agent; HOOKS.md section 11 | No |
| `context_reinject_failure.py` | PostToolUseFailure (`Write\|Edit\|NotebookEdit`) | On a failed Edit/Write, injects the untrusted-oracle re-derivation discipline (Rule A); HOOKS.md section 12 | No |
```

**Not cut (outside the assign):** the paragraph after the table
(`CLAUDE.md:184-200`, the hook semantics rule and the kill-switch,
gitignore and CI-scan text). 14 of its 17 clauses are held, 7 of them only in
`docs/INSTALL-CI.md` and `docs/SHARP_EDGES.md`. It stays as it is.

## B. Core Rule 10 (`CLAUDE.md:111`)

**Destination: a new note, `memory/landing-through-a-pull-request.md`, holding
the rule's whole current text verbatim, moved by the lane.** No existing file
is the rule's sole home. Of its 35 clauses, 3 are held nowhere (the PR #3
timing; "a cell is suspect past that worst, or when `gh run view <id> --json
jobs` shows no step in progress"; the private archive tree's opposite rule
before the cut). 3 are partial, and 3 are held only in code comments
(`espalier/render_surface.py:43`, `.github/workflows/test.yml:50`,
`scripts/ci_job_bounds_census.py`). A verbatim move loses nothing by
construction and puts the history where `memory/CLAUDE.md` says provenance
belongs. The draft note is 3,693 bytes.

**Retired, not moved:** "so `/commit`'s branch-first and `gh pr create` steps
apply here". `.claude/commands/commit.md` has neither step now (it offers
`/ship`). The note says so in its header.

**DEF-4106's phrase** ("red, still going or ended with no verdict", air's note
80adaa) is in `caa80243`'s Rule 10 already, so it travels verbatim into the
note. It is also held at `memory/parallel-work-protocol.md:324-326` and
`.claude/commands/inbox.md:184-186`.

**Draft kept text:**

> 10. Self-host dev lands harness self-edits on `main` through a branch and a pull request whose required checks are green, enforced on admins: `/ship` (`tools/cc/ship.py`) opens it with auto-merge armed, once per lane as `/handoff`'s last step, and the turn that commits a lane's finished work runs `/handoff` itself (`stop_gate`'s Gate 5 holds the Stop until it does). A red `main` is reverted before anything lands on it (Core Rule 15). The live merge rules are the banner's `Merging:` line and a cell's time is `python3 scripts/ci_job_bounds_census.py`'s to print, never this file's; the rest (the required checks' history, the post-merge proof and its suspects, catch-up, the tier a pull request earns, the measured timings) is [`memory/landing-through-a-pull-request.md`](memory/landing-through-a-pull-request.md), the sole home.

It keeps the bounds census by name, because DEF-3034 was closed on Rule 10
naming it (`tests/_ledger_rules.py:332-335`).

## C. Core Rule 15 (`CLAUDE.md:126`)

**Destination: `memory/parallel-work-protocol.md`, already the named sole
home.** 26 of 27 clauses are held there. The one partial, "on any machine", is
kept in the rule. `tests/test_seat.py:810-812` and `:910-912` pin four of the
rule's phrases verbatim, and the draft keeps all four.

**Draft kept text:**

> 15. **Parallel work is safe by construction, not by negotiation.** Core Rule 14 between seats: a seat is one session in its own named worktree, on any machine (two sessions in one checkout are one seat, which must not happen); it works the jobs the dispatcher assigns, never a path, claims the files a lane edits, mints ids from its own block, reads live state in the same turn before stating it, keeps one open PR per seat, and asks the dispatcher, never another worker. A red `main` is reverted first and diagnosed second; a record's format changes by expand, then contract. A gridlock is resolved by the dispatcher seat, which rules, acts and reports the ruling as an ack opening with `gridlock:`, or as a note opening the same way where no request waits on the ruling, which the operator can reverse; a new pack, a scope change, a release or tag stay the operator's. [`memory/parallel-work-protocol.md`](memory/parallel-work-protocol.md) is the sole home (the dispatcher, the id blocks, the fix-forward ruling, `TP-479`).

The canon and claim-id comment pairs between the rules stay where they are
(`tests/test_canon_verifier_contract.py:316` counts them).

## D. Pins and consumers

Read by grep over `tests/`, `scripts/`, `espalier/*.py`, `tools/cc/*.py` and
`.claude/commands/smoke.md` at `caa80243`, plus a census dispatch under the
assign's `census` allowance (its first row was read by hand).

**One red the draft must fix before the cut:**
`tests/test_hook_utils.py::TestProtectedZoneDocParity` (6 tests, `:358-361`
and `:473-600`) reads the first `CLAUDE.md` line containing "protected harness
zones", which is the `write_guard.py` row. That line must keep the phrase, all
four zone prefixes and all five zone files in backticks, and "self-host"
beside `espalier/` and `.github/workflows/`. The draft row above shortens
these, so the lane's row keeps them (about 250 bytes more).

| Consumer | Reads | After the drafted cut |
|---|---|---|
| `tests/test_agent_contracts.py:459-475` | 12 pipe rows whose first cell is a backticked `.py` name, under `## Hooks` | kept: one row per hook |
| `tests/test_documented_claims.py:156-218` | "governs 10 of Claude Code's hook events" (`CLAUDE.md:167`) | the intro is not cut |
| `tests/test_recall.py:4198-4210` | the `recall: skip` markers at `CLAUDE.md:5` and `:81` | not cut |
| `tests/test_seat.py:810-812`, `:910-912` | four Rule 15 phrases, verbatim | kept by the draft |
| `tests/test_canon_verifier_contract.py:316` | 20 claim markers in `CLAUDE.md` | markers stay |
| `tests/_ledger_rules.py:332-335` | DEF-3034 closed on Rule 10 naming the bounds census | kept by the draft |
| `espalier/harness_config.py:95` | the "Can block? Yes" hooks of a hooks table | column and values unchanged (probable: the line was not read) |
| `tests/_recall_pins.py` bands | the lines-delivered counts `/recall`'s body quotes | move by one document; the cut lane's tier runs the recall files, since `CLAUDE.md` is a recall-indexed doc |
| `task-packs/FORWARD_LEDGER.md:1644` (a record) | "the documented DEF-11 path in CLAUDE.md" | that paragraph is not cut |

No test pins the text of root `CLAUDE.md`'s hook rows. The table hits
(`espalier/cli.py:3233-3249`, `tests/test_init.py:416`) are the adopter
template.

## E. Rulings asked for

- **R1, hook detail in `/recall`.** (a) Accept: the rows keep the banner lines'
  names and point at their HOOKS.md section, and 4 of the 7 measured hook
  queries leave the Hooks section, one to a wrong document. (b) Index
  `docs/HOOKS.md` on this repository too: its own lane, with its pins
  re-measured (14 moved in 2026-10-18's measurement). (c) Keep more vocabulary
  in the rows, which costs bytes. **Recommend (a)**, with (b) filed as a row if
  the operator wants hook behaviour recallable here. A Hooks-section hit before
  the cut was a 16 KB section to scan, and the row now names the HOOKS.md
  section to read, so for those queries the reading cost is about the same.
  Against (a): this box's local recall telemetry (gitignored
  `.espalier-state/recall_events.jsonl`) shows 6 of the 7 first answers that
  came from `CLAUDE.md`, out of 2,352 events, were this section. No pinned
  recall query expects it (0 hits for `CLAUDE.md ::` in the pins), and a
  proxy cut left every pinned arm unchanged.
- **R2, ids.** Keep them in the one-line rows (recommended; about 70 bytes), or
  drop them and leave the link from feature to id to their row files.
- **R3, Rule 10's home.** A new single-topic `memory/` note (recommended), or a
  "Landing" section in `memory/parallel-work-protocol.md`.
- **R4, beyond the assign.** Not mapped: the Maintenance mode section (3,179
  bytes; `docs/HOOKS.md` has its own), Project Context's no-banner paragraph,
  and Getting Started step 0 (the reap). Say if those should be mapped next.

## F. Found on the way (for air: rows or rulings)

1. **The `post_write_check.py` overclaim ships to adopters.** "Validates each
   written file for JSON validity and path consistency" is in `init`'s
   `CLAUDE.md` template (`espalier/cli.py:3244`) and in
   `espalier/harness_config.py:53` (rendered into `cc/LIVE_SURFACE.md:20`). The
   code checks `.claude/settings.json` alone for JSON, and nothing for path
   consistency. Who is hurt: an adopter who writes a malformed JSON config and
   trusts the table to catch it.
2. **`docs/HOOKS.md:2250` points adopters nowhere** (section A). The lane's
   HOOKS.md edit fixes it. It is named here because it is live on every
   adopter tree today, cut or no cut.
3. **Rule 10's "eleven since 2026-11-07"** may be the merge date of TP-706's
   Wave 1, not the date of the GitHub-side removal (`TP-706:794` puts the
   removal "before Wave 1's pull request"). Probable. The note carries the text
   verbatim, so a correction would be the note's.
