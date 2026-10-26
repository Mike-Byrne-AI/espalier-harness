# TP-704 — The threshold handoff: a seat hands off at a context size, not at the window's end

## Status

- Version target: shipped runtime (`tools/cc/statusline.py`, `tools/cc/hooks/task_router.py`,
  `tools/cc/hooks/_hook_utils.py`, `tools/cc/seat.py` all deploy to adopters), plus one dev-only
  measurement script under `scripts/`. The full tier.
- Type: workflow infrastructure, wave 1 of the usage work the operator chose on 2026-10-26 ("in a
  perfect world, handoff replaces compact, so lets try the threshold handoff"; then "approved, the
  other worker is off for now, lets do the work here").
- **Kind: PACK.** One lane, from the dispatcher seat `air`, in this checkout, with air-work off.
- Authored 2026-10-26 by the dispatcher seat `air`. Id from the seat's block (`espalier.toml`
  `[id_blocks]`, `air = TP 700-799`; `TP-703` is the block's last filed pack, `TP-704` the next free,
  checked by `ls task-packs task-packs/Done task-packs/Deferred task-packs/Scrapped | grep TP-70`).
- Reasoning review at authoring (the `failure-mode-reviewer`, fresh context, 2026-10-26): REQUEST
  CHANGES, 2 regressions, 4 gaps, 5 rough edges, every one folded below. The two regressions
  changed the design: the trigger now reads the session transcript's tail instead of a status-line
  side file (whose `.json` suffix the marker readers' glob would have read as a live session), and
  a threshold handoff never ships an unfinished lane. The measurement was re-derived with the
  review's dedup fix (one transcript line per content block carries the same usage).
- Waves 2 and 3 of the same work are NOT this pack: the anchor-and-subagent model (a trial, no code)
  and the self-relaunch probe (a W0-style probe before any build). See Scope (out).

## Motivation

**The measurement (2026-10-26, this box, the `air` and `air-work` transcript directories under
`~/.claude/projects/`; re-derive with `python3 scripts/usage_tail.py <dir>...`, which this pack
lands).** Per-message token usage read from every session transcript with twenty or more
assistant turns, one record per `(message.id, requestId)` (the review found Claude Code writes one
line per content block, each carrying the same usage; the first derivation counted 41,704 lines for
14,154 messages, and its shares held while its restart overhead did not), weighted by the published
API price ratios: uncached input 1, cache read 0.1, output 5, cache write 1.25 (the five-minute
cache) or 2.0 (the one-hour cache the payload's `prompt_cache` field names on this account).

| | dispatcher seat, 83 sessions | worker seat, 7 sessions |
|---|---|---|
| share of main-thread weighted spend from turns at 150k+ context | 0.94 | 0.97 |
| share from turns at 300k+ | 0.76 | 0.85 |
| estimated spend had every session been cut at 200k, net of restarts (write 1.25 / 2.0) | 0.51 / 0.55 | 0.34 / 0.37 |
| same at 300k | 0.59 / 0.62 | 0.45 / 0.46 |
| restart overhead at 200k (first five turns of a session per restart) | 0.04 / 0.05 | 0.01 / 0.01 |
| subagent spend relative to the main thread (both sides deduplicated, write 2.0) | 0.49 | 0.36 |

Sessions here reach about 960k of a 1M window, so auto-compact fires only at the very end. The
long-context tail is the biggest single lever on this box, larger than subagent dispatch. Four
caveats the pack carries, not hides: the meter behind a subscription limit is not public, so the
price ratios are a proxy (the raw-token shares show the same shape, more extreme); the counterfactual
is a crude model (the cached prefix averaged at half the cap, and the handoff turns themselves are
not modelled, which the review put at roughly another 0.05 to 0.1 on the dispatcher); the subagent
figures are from the first derivation; the Windows seats are unmeasured.

**What the platform gives (Claude Code docs read 2026-10-26, `https://code.claude.com/docs/en/statusline.md`
and `.../hooks.md`, and the live payload captured in Task 0-1).** No hook payload carries context
size, but every hook payload carries `transcript_path` (a common field in the protocol pin,
`docs/external/cc-hook-protocol.md`), and the session transcript's last assistant record carries the
`usage` of the most recent API response, whose input plus cache-creation plus cache-read tokens IS
the context size the status line's `context_window.total_input_tokens` reports (Task 0-1 measured
the two equal on this session). The status line command receives JSON on stdin with the same figure,
the window size, and the account's rate-limit percentages. No hook can trigger `/clear` or
`/compact`; a Stop hook blocks a stop but cannot end the session. So the trigger half is a transcript
tail read in the prompt router, the ask rides the router's plain stdout, the status line shows the
figures, and the reset stays a `/clear`, which the seat's `/loop` survives (measured 2026-10-24/25,
`memory/parallel-work-protocol.md`).

**What the repo already holds.** `TP-700` is the fresh-session-per-lane runner (ROADMAP, W0 measured,
`TP-700a` to `TP-700d` unwritten); its line 42-44 records as an unmeasured hypothesis that a session
cannot clear itself, which the docs now confirm. Nothing in the tree measures context (survey
2026-10-26: `stop_gate.py::_advise_session_signals` counts tool calls, `cognitive_blueprint`'s
`accumulated_depth` counts chained sessions). `post_compact.py::_capture_compact_summary` already
reads `transcript_path` from a hook payload, so the transcript's record format is an assumption the
tree already carries.

**Who is hurt (STANDING_PRINCIPLES §16).** The operator, whose three accounts freeze one box whole at
a limit (the 2026-10-15 incidents, auto memory), and who today is the context watcher by hand
("operator watches context (handoff/compact as needed)", `worker-seats-run-a-fail-safe-loop`).
The live payload at authoring read the seven-day limit at 83 percent on this account.

## Scope (in)

1. **The router reads the context and asks at the threshold.** `tools/cc/hooks/task_router.py::_run_main`
   calls a new `_context_advisory(root, data)` on every prompt (loop ticks included), placed after
   the cold-open block and BEFORE the active-plan early return. When the threshold setting is on
   (Scope 3), the advisory reads the payload's `transcript_path` through a new
   `_hook_utils.read_context_from_transcript(path) -> int | None`: a bounded tail read (the last
   256 KiB, then the last 1 MiB when no record is in it) of a regular file opened the way the
   marker reader opens its state files (fd-level `O_NOFOLLOW`, `S_ISREG`), the last line whose
   `type` is `assistant` and whose `message.usage` holds the three input counts as integers; `None`
   on any other shape. When `tokens >= threshold_eff`, the advisory prints on the router's plain
   stdout channel. The first time it asks, it writes `.espalier-state/sessions/<sid>.handoff-asked`
   (`at`, `tokens`, JSON inside, a suffix the marker readers' `*.json` glob never matches) through
   `_hook_utils.atomic_write_text`, and every later advisory quotes that first ask.
2. **The ask never ships an unfinished lane.** The advisory's text (7-bit ASCII, one paragraph,
   under 700 characters): the context figure against the threshold and the window; the first ask's
   stamp; then: if a lane is in hand, finish it through its own landing (its tier and its push) and
   start no new job; when no lane is in hand, run `/handoff` now; after the handoff take no new work,
   answer a loop tick in one line, and tell the operator this window needs a `/clear` (the loop
   survives it). The sentence "it writes your row and pushes the lane" rides only where
   `handoff_push = true`; elsewhere "it writes your row". The review's regression: on this tree
   `/handoff` ends in `ship.py handoff`, which refuses a dirty tree, a marked record and a shared
   checkout and nothing else, so a committed half-lane would open as a pull request with auto-merge
   armed. The ask therefore never says "commit and hand off" mid-lane.
3. **The threshold is an opt-in setting.** Top-level `handoff_context_tokens = <int>` in
   `espalier.toml`, read by a new `_hook_utils.read_toml_scalar(root, key) -> tuple[str | None, str]`
   (a hand scan in `ship.py::handoff_push_setting`'s shape, since the 3.10 floor has no `tomllib`:
   only a bare top-level value counts; a quoted key is the same key; a table key, a near spelling
   and a missing file are named in `how`), wrapped by `handoff_context_threshold(root) ->
   tuple[int, str]`: absent, `0`, or anything but a non-negative integer literal reads as off
   (`0`) and is named. **Default off**, like the sibling `handoff_push`: an adopter opts in. This
   tree sets `handoff_context_tokens = 200000`. Clamp: `threshold_eff = min(setting,
   int(window * 0.75))` when the status line's window is known to the router (it is not, in wave 1:
   the transcript carries no window), so wave 1 clamps nothing and says so in the docs; the
   200k-window case is the adopter's to set lower.
4. **The sweeps know the side file.** `_hook_utils.SESSION_SIDE_SUFFIXES` gains `.handoff-asked`,
   so `prune_session_markers` and `_retire_session_side_files` remove it with the marker, and a test
   pins that no suffix in the roster ends in `.json`.
5. **The status line shows the figures, and writes nothing.** `tools/cc/statusline.py::main` reads
   its stdin through a new `_read_statusline_payload()` (`{}` on a tty, an empty or unreadable
   stream, bad JSON or a non-object) and prints two more segments through a new
   `_context_segments(payload) -> list[str]`: `ctx=<tokens>k/<window>k` from `context_window`, and
   `limits=<five_hour>%/<seven_day>%` from `rate_limits` when present (an absent window prints `-`).
   Non-numeric values drop their segment; the line always prints; exit 0.
6. **The brief and the tick name the ask.** `tools/cc/seat.py::WORKER_BRIEF`'s handoff sentence
   and `DISPATCHER_BRIEF`'s gain the clause "or when the prompt router reports the context past the
   handoff threshold"; `WORKER_TICK`'s "then your next assigned job" gains "unless the router has
   asked for the threshold handoff, in which case finish the lane in hand, hand off, and take no new
   job until the window is cleared". The tick is the operator's decision (`seat.py`'s comment above
   `WORKER_BRIEF`) and the operator's approval of this wave is that decision; the two exact-substring
   pins in `tests/test_seat.py` move with the text, and a seat already looping keeps its old tick
   until relaunched from a checkout that holds the change.
7. **The metric is pre-registered and re-runnable.** `scripts/usage_tail.py` (dev-only, like
   `scripts/proof_tier.py`; joins `tests/_surface_expected.py::EXPECTED_SCRIPT_NAMES`): one record
   per `(message.id, requestId)`, the per-session table, the bucket table (weighted and raw shares),
   the restart cost, the cap counterfactual with its restart overhead at both cache-write weights,
   and the subagent shape from the nested `subagents/` transcripts; `--json` for a machine read.
   `tests/test_usage_tail.py` drives it on a synthetic directory whose lines repeat a message across
   content blocks, so the dedup is the earned red. The pre-registered measure for this wave:
   weighted tokens per seat per calendar day (the script's per-day table; a session after a
   `/clear` is shorter by construction, so per-session figures do not compare across the change
   and a day's spend does), over at least five working days a side of 2026-10-26, reported as a
   spread, expected near 0.55 of before on the dispatcher and 0.37 on a worker at 200k (the table;
   direction verified, magnitude an estimate). Carried on the handoff's owed line in `cc/GOAL.md`
   and in the session row, the tree's own scheduling surfaces, so the read a week out is
   scheduled, not remembered.
8. **Docs.** `docs/HOOKS.md` §2 (`task_router.py`) gains the threshold advisory, its setting, its
   source and what it never does (ship mid-lane); the status line paragraph in the same doc gains
   the two segments; `docs/HOOK_ASSUMPTIONS.md` gains Assumption 7 (the transcript's last assistant
   record carries the context size; a `/loop` tick fires `UserPromptSubmit`; the loop survives
   `/clear`), each with its measured evidence; the root `CLAUDE.md` `task_router.py` row gains the
   clause; `docs/TROUBLESHOOTING.md` gains the "it asked again after my handoff" row (the ask is
   idempotent by text; a `/clear` ends it). The asset twins follow (`python3
   scripts/sync_asset_docs.py`: `espalier/assets/docs/HOOKS.md`, `espalier/assets/docs/HOOK_ASSUMPTIONS.md`,
   `espalier/assets/docs/TROUBLESHOOTING.md`), the vendor mirror follows (`python3
   scripts/sync_vendor_cc.py`: `espalier/_vendor/cc/statusline.py`, `espalier/_vendor/cc/seat.py`,
   `espalier/_vendor/cc/hooks/task_router.py`, `espalier/_vendor/cc/hooks/_hook_utils.py`), and the
   lane's changelog fragment is filed (`python3 tools/cc/_record_fragments.py new changelog`, under
   `changelog.d/`; `changelog_fragments = true` on this tree).

## Scope (out)

- **A mechanical "handoff done" signal.** The router could stop asking once the handoff has run.
  The universal product of `/handoff` is the row (step 2) and the working-summary rewrite (step
  6.1, which the review confirmed is universal; only the `handoff_mechanics.py` block is self-host
  only), but neither is keyed to a session id, `post_compact.py` also rewrites the summary, and a
  catch-up merge lands other seats' rows with fresh mtimes. The idempotent text plus the first-ask
  record is wave 1's answer; the wave-2 trial decides whether the double-handoff case happens. The
  review named the shape if it does: a `PostToolUse` hook sees the model's `ship.py handoff` call
  with the payload's `session_id`, universal and verb-free (probable).
- **A hard ceiling with a row that parks.** A lane that runs long past the threshold keeps growing
  until its landing. A second, higher figure at which the seat commits, writes its row and parks it
  without the push needs a handoff form that skips `ship.py handoff` on an unfinished lane, which is
  a change to the handoff command and the ship driver, decided on wave 1's measurement of how far
  past the threshold lanes run.
- **Blocking the loop tick after the ask.** `UserPromptSubmit` can block a prompt, but the router
  is advisory by contract (`task_router.py::main`'s docstring) and blocking the operator's own
  prompt is hostile. The cost of the pause is a tick at threshold context: about 20k weighted
  tokens per tick at the threshold (median weighted turn at 150-200k, first derivation), and it
  grows, because each `/inbox board` tick adds its command body (about 24 KB) to the parked
  context, so a dispatcher parked at 02:00 is roughly 200k larger by 08:00 and each later tick
  dearer (the failure-mode review's figure); measured by wave 2's trial, which decides whether the
  parked tick becomes a one-line read.
- **The reset's rough edges (`DEF-4052`, filed by this lane).** The reset is a `/clear`, and
  three things the review named go wrong on it today: the dispatcher's brief does not come back
  (the banner gives a dispatcher no `Orders:` line), a worker's `Orders:` line says "then start the
  worker loop" while the old interval loop is still running (a second loop), and a seat keeps the
  old tick text until relaunched. All three are pre-existing properties of `/clear` that this lane
  makes routine; the fix (the launcher relaunching the seat, or the banner's line after a `clear`
  dropping the loop sentence) is wave 3's, and the row keeps it from being lost.
- **What "no new job" leaves standing (decided here, the operator may reverse it).** After the
  ask, a seat's own open pull request going red or into conflict, and the dispatcher's red-main
  revert, are not new work: the ask says so, so a parked night does not leave `main` red or a
  landing lane stuck. Everything else waits for the clear.
- **The status line as the trigger's writer.** The first draft had the status line write a side
  file the router read. The review found its `.json` suffix would be read as a live session by
  `other_live_sessions` and `checkout_sync.marker_sessions`, and the transcript tail gives the same
  figure with no writer, no race and no sweep change. The status line keeps the display.
- **The window clamp.** The transcript carries no window size; wave 1 asks at the setting alone.
  A later wave can read the window from the status line's payload if a 200k-window adopter needs
  the clamp; until then the docs say to set the figure for the window.
- **An env override for the threshold.** `ESPALIER_HANDOFF_CONTEXT_TOKENS` would need a
  `docs/ENV_CATALOG.md` row and its completeness pins; the toml key serves every seat on a tree the
  same (Core Rule 15: a team setting, tracked).
- **The account meter as the trigger.** `rate_limits` says when the box freezes, not what a turn
  costs; the threshold is about context. The meter is shown, not acted on.
- **Lowering auto-compact (`autoCompactWindow`).** A compaction is not a handoff (no row, no
  blueprint advance, residue carries; `checkpoint-lane-groups-with-handoff-and-clear`). The operator
  chose handoff over compact.
- **The anchor-and-subagent model (wave 2)** and **the self-relaunch probe (wave 3)**: a trial and a
  probe, each decided on wave 1's measurement.
- **`TP-700`'s runner (its first child, unwritten at authoring):** the fresh `claude -p` per lane
  stays the overnight runner; this pack is the interactive seats' backstop and gives that child
  its threshold and restart figures.
- **`DEF-674`** (the banner's byte budget above the host cap) is adjacent, not this lane's.

## Cross-pack coordination

Added at the artifact review (checklist v2, WARN only, 2026-10-26). Three packs touch the same
sentences and pins. `TP-703g` (landed, #345-era) inserted the `WORKER_BRIEF` and `DISPATCHER_BRIEF`
clauses the two exact-substring pins in `tests/test_seat.py` now hold; this pack edits those
sentences AFTER it, on `main` as merged, and moves the pins with the text. `TP-703c/d/e/f` state
the tick is the operator's paste and otherwise untouched; this pack's tick clause is the
operator's decision for this wave (Scope (in) 6), and a seat already looping keeps its old tick
until relaunched. `TP-701` (DRAFT) edits `seat.py`, `_hook_utils.py`, `other_live_sessions`
(its B-4), `tests/test_seat.py` and `tests/test_session_banner.py`: whichever lands second
re-bases, and `TP-701` B-4's `other_live_sessions` change must keep this pack's
side-file-ignored test green. Open pull requests at authoring (#348, #327) touch only
`docs/external/*.candidate.md`: no file overlap.

Two execution notes from the same review. `tests/test_usage_tail.py` drives the script's
`main()` in-process, never as a child process, because the unit contract forbids a subprocess in
a `unit` module and the opt-out marker does not lift that. The transcript reader's internal
excepts each carry a `# fail-open: ok` marker, since `tests/test_failopen_voice.py` derives its
population from `_hook_utils`; the router is the one voice. Fix 1-C's scalar reader is not a
third hand scan: it rides `read_toml_table`'s parsed arms and adds only the regex fallback's
scalar twin, so the "named table key / near spelling" promise of the first draft is dropped (an
absent top-level key reads as off and says so; a malformed file is named by the parser's error).
Task 6 also refreshes the integrity manifest (`python3 -m espalier integrity refresh .`) and the
approval marker rides the pull-request title through the ship driver, as every hook change does.
The toml key lands in Task 6, before the tier; the live drive (Task 7) follows it. Task 0-2 is a
manual smoke on this seat's next loop, not a merge gate.

## Task 0 — Verify (can end the pack)

**0-1. The context figure has a source on this box: measured, HOLDS.** Two oracles, both run
2026-10-26 on this session (Claude Code 2.1.310 on PATH; the payload's own `version` field read
2.1.299, so the two can differ). (a) A three-line probe in the live `tools/cc/statusline.py` dumped
its stdin once (a status line is a UI element, so a headless `-p` run cannot stand in for it) and
was reverted with the file tools: the payload's top-level keys are `context_window`, `cost`, `cwd`,
`effort`, `exceeds_200k_tokens`, `fast_mode`, `model`, `output_style`, `prompt_cache`, `prompt_id`,
`rate_limits`, `scratchpad_dir`, `session_id`, `session_name`, `thinking`, `transcript_path`,
`version`, `workspace`; `context_window.total_input_tokens` read 270738, `context_window_size`
1000000, `used_percentage` 27; `rate_limits.five_hour.used_percentage` 38 and `seven_day` 83.
(b) The transcript at the payload's `transcript_path`, tail-read the way Scope (in) 1 reads it: the
assistant record stamped 09:19:37Z carries usage summing to 270738, the same figure. Refuting
result, had it come: no `transcript_path` in the router's payload, or no assistant record with
usage in the tail. Exit: stop and re-raise. The clause is kept so the next reader sees the kill
condition was real.

**0-2. The ask reaches the model on a loop tick.** Oracle: the router's plain stdout is injected
"alongside the submitted prompt" on `UserPromptSubmit` (`docs/external/cc-hook-protocol.md`), and a
`/loop` tick is a `UserPromptSubmit` (`task_router.py::_run_main` touches the session marker on every
prompt, which the banner's `Sessions:` line reads; looping seats' markers have stayed live since
2026-10-13). Refuting result: a tick does not fire the router (the marker's mtime does not move
across a tick on a quiet seat; read it on this seat's next loop). Exit: the ask moves to a different
event, a different pack; stop.

**0-3. The brief and tick sentences are as cited.** Oracle: `grep -n '/handoff\|next assigned job'
tools/cc/seat.py` and `tests/test_seat.py`'s two exact-substring brief pins (the review read them at
its :645 and :662). Measured at authoring: `WORKER_BRIEF`, `DISPATCHER_BRIEF`, `WORKER_TICK` and
`SELF_HOST_PROCEED` carry the sentences Scope (in) 6 changes.

## Relevant memory

Recent pattern: the last three defects on the session-marker surface were in a writer's edge case,
not a reader's (a polled marker read empty because `write_text` created it before it held the
answer, #345; a stub marker with no pid; a `clear` retiring the wrong window), and this pack's own
first draft added a writer whose suffix the readers' glob would have taken for a marker. The design
now has one small writer, through the helper every other marker write uses.

| Entry | Where |
|---|---|
| Hooks (Mechanical Enforcement) | `CLAUDE.md` :: Hooks (Mechanical Enforcement) |
| Parallel work protocol (the loop survives `/clear`; one writer per shared state) | `memory/parallel-work-protocol.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| A state file's reader and writer are a pair on symlinks | `memory/hook-authoring.md` (2026-09-12 entry) |
| Fail-open with voice | `memory/hook-authoring.md` (2026-09-30 entry) |
| A polled marker is written whole and renamed into place | `tests/CLAUDE.md` |
| Checkpoint lane groups with /handoff then /clear | auto memory `checkpoint-lane-groups-with-handoff-and-clear` |
| An autonomous driver is a disk-baton cycle | auto memory `autonomous-p-loop-is-disk-baton-cycle` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "task_router UserPromptSubmit
injection cap, statusline, session marker under .espalier-state/sessions, handoff gate"` (four
candidates; the first and third chosen) plus the hooks folder's `CLAUDE.md` read-first list.
Re-run it rather than trusting this list if the pack has been sitting.

## Implementation

Every fix below is a **fix shape (untested)** until its Task's checkpoint runs it; the oracle for
each is the test named beside it, red before the fix (the mutation it must die to is named).

### Task 1 — `_hook_utils`: the suffix, the transcript reader, the scalar reader

**Fix 1-A — the side-file roster** *(fix shape, untested; refuted if a sweep test shows the side
file surviving its marker's removal, or a `Sessions:` reader naming it):*

```python target=tools/cc/hooks/_hook_utils.py
HANDOFF_ASKED_SUFFIX = ".handoff-asked"
SESSION_SIDE_SUFFIXES = (ZONE_BASELINE_SUFFIX, ZONE_BASELINE_SUFFIX + ".lock", HANDOFF_ASKED_SUFFIX)
```

**Fix 1-B — the transcript reader** *(fix shape, untested; refuted by 0-1(b) if the tail holds no
such record on a live transcript):* `read_context_from_transcript(path: str | os.PathLike) -> int |
None`, `TRANSCRIPT_TAIL_BYTES = 262_144`, `TRANSCRIPT_TAIL_MAX_BYTES = 1_048_576`. Open with the
fd-level flags `_read_blueprint_safe` uses in `statusline.py` (`O_NOFOLLOW`, `O_NONBLOCK`,
`S_ISREG`); seek to `max(0, size - tail)`; split on `\n`; walk the lines from the end; the first
that parses as an object with `type == "assistant"` and `message.usage` holding integer
`input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` returns their sum; on
none, retry once with the larger tail; else `None`. Never raises; the router's advisory is its
voice when it matters (the setting is on and the read failed: one `say_once`, "the context could
not be read from the transcript", so a seat with the setting on never silently stops asking).

**Fix 1-C — the scalar reader and the threshold** *(fix shape, untested):* `read_toml_scalar(root,
key) -> tuple[str | None, str]`, `HANDOFF_CONTEXT_KEY = "handoff_context_tokens"`,
`handoff_context_threshold(root) -> tuple[int, str]` (`0` means off), and `handoff_push_on(root)
-> bool` reading `handoff_push` through the same scalar reader (the router must not import
`ship.py` for one bit; `ship.py::handoff_push_setting` keeps its own tested `how` strings, and a
comment on each names the other as its sibling).

Earn the red: the prune test in `tests/test_session_banner.py` extended with the new side file
(red: it survives before Fix 1-A); a roster test that no suffix ends in `.json` and that
`other_live_sessions` ignores a side file beside a marker (red against a `.json` suffix); a new
`TestContextFromTranscript` in `tests/test_task_router.py` (red: `AttributeError`; then the shapes:
a symlink, a FIFO on POSIX, an empty file, a last line that is a `user` record, a record whose usage
is strings, a transcript whose last assistant record sits past the first tail window, a line split
across the tail boundary); `TestHandoffContextThreshold` for the scalar reader (absent file, absent
key, `0`, `200000`, `abc`, a quoted key, a table key, a near spelling).

Checkpoint: `pytest tests/test_session_banner.py tests/test_task_router.py -q -n 1`.

### Task 2 — the router asks

**Fix 2-A** *(fix shape, untested):* `task_router.py::_context_advisory(root, data) -> str | None`:
`handoff_context_threshold`; `None` when off; `read_context_from_transcript(data.get("transcript_path"))`;
`None` when `None` or below; else, on the first ask, `atomic_write_text` the side file (`at`,
`tokens`), then render:

```text
[HARNESS] Context is <tokens>k, past the handoff threshold (<threshold>k, espalier.toml
handoff_context_tokens). First asked <at>Z at <tokens0>k. Handoff replaces compaction: if a
lane is in hand, finish it through its own landing and start no new job; with no lane in hand,
run /handoff now (it writes your row<, and pushes the lane>). After the handoff take no new
work, answer a loop tick in one line, and tell the operator this window needs a /clear (the
loop survives it).
```

The bracketed clause only where `handoff_push_on(root)`. Rendered 7-bit ASCII, one paragraph, under
700 characters, placed in `_run_main` after the cold-open block and BEFORE
`if _has_active_plan(root): return 0`, with the blank-line separator the other advisories use.

Earn the red: `tests/test_task_router.py` gains `TestContextThreshold`: a transcript past the
threshold prints the advisory with the figures (red: nothing printed before the fix); below prints
nothing; setting off prints nothing even past; active plan still prints it (red against a version
placed after the early return, the named mutation); the side file is written once and its `at` is
quoted on the second prompt; `handoff_push = true` adds the push clause and its absence drops it;
`abc` reads as off; the text encodes as ASCII and is under the cap.

Checkpoint: `pytest tests/test_task_router.py tests/test_hooks.py tests/test_hook_protocol.py
tests/test_failopen_voice.py tests/test_spawn_chokepoint.py -q -n 1`.

### Task 3 — the status line shows the figures

**Fix 3-A** *(fix shape, untested):* `_read_statusline_payload()` (tty-safe, bounded 64 KiB,
`utf-8-sig`, object or `{}`) and `_context_segments(payload)`; the segments join `main`'s indicator
tuple after the blueprint summary. The statusline writes nothing. Its excepts are outside
`tests/test_failopen_voice.py`'s population (hooks only), so each carries the stderr line `main`
already uses for a degraded indicator.

Earn the red: `tests/test_statusline.py` gains `TestContextSegments`: the docs' sample payload with
`context_window` prints `ctx=15k/200k` (red before); `rate_limits` prints `limits=38%/83%`; one
window absent prints `-`; a tty, empty stdin, bad JSON, a non-object, string values each print the
line without the segment and exit 0; the run writes no file under the sessions directory.

Checkpoint: `pytest tests/test_statusline.py tests/test_statusline_freshness_segment.py -q -n 1`.

### Task 4 — the brief and the tick

**Fix 4-A** *(fix shape, untested):* the three sentences per Scope (in) 6; the two exact-substring
pins in `tests/test_seat.py` move with them and one new assertion covers the tick clause.

Checkpoint: `pytest tests/test_seat.py -q -n 1`.

### Task 5 — the measurement script

**Fix 5-A** *(measured on this box 2026-10-26 as scratchpad scripts; the merge is untested):*
`scripts/usage_tail.py` per Scope (in) 7, `tests/test_usage_tail.py` with the opt-out marker
`# pytest-marker: default-unit`, and the name added to `EXPECTED_SCRIPT_NAMES`.

Checkpoint: `pytest tests/test_usage_tail.py tests/test_test_suite_contract.py -q -n 1 && ruff check scripts/usage_tail.py`.

### Task 6 — docs, mirrors, the tier

Docs per Scope (in) 8 (Assumption 7 in `docs/HOOK_ASSUMPTIONS.md` carries the three measured
facts and their dates); `espalier.toml` gains the key with its comment; then `python3
scripts/sync_asset_docs.py`, `python3 scripts/sync_vendor_cc.py`, `python3 scripts/check_pack_fences.py
task-packs/TP-704-the-threshold-handoff.md`, `python3 -m espalier scope-check
task-packs/TP-704-the-threshold-handoff.md`, `pytest tests/test_vendor_cc_parity.py
tests/test_doc_source_citations.py -q`, then the full tier (`python3 scripts/proof_tier.py --run
--tier full`; no other tier runs on this box with air-work off).

### Task 7 — red-team, then the live drive

Two passes over the diff, as the review asked: the failure-mode reviewer (the `adversarial` skill)
and the architecture analyst (the `arch-check` skill, for the hooks-to-`tools/cc` import direction
and the one-writer shape). Named as the most likely errors: a transcript whose last assistant record
is past the first tail window; a tool-result line larger than the tail; the router's read on the
first prompt of a session (no assistant record yet: no ask, correct); a worktree seat whose payload
`transcript_path` is another slug's file (it is the session's own; a test pins the path is taken
from the payload, never derived); the advisory firing on an adopter tree with no `espalier.toml`
(off by default: it does not); the `.handoff-asked` file left by a session the prune has not yet
swept, read by nothing.

Then the live drive on this seat, which is past the threshold already: with the setting at 200000
in this tree, the next prompt's router output carries the advisory with this session's figure, and
the side file appears under `.espalier-state/sessions/`. Record the output and the figure in
Landing. The pre-registered outcome measure runs over the following week's lanes.

## Affected symbols

### Changed-semantics
The two entry points that change are generic names the name-keyed walk cannot scope (`main`:
5,695 references tree-wide, `_run_main`: 328, read by `scope-check` at authoring), so they are
struck from the walk; the change in each is one call to an added symbol below, which the walk does
see (`_read_statusline_payload` and `_context_segments` joining `main`'s indicator tuple;
`_context_advisory` called in `_run_main` before the active-plan return).
- ~~`tools/cc/statusline.py::main`~~ (reads the payload, prints the segments)
- ~~`tools/cc/hooks/task_router.py::_run_main`~~ (the threshold advisory before the active-plan return)
- `tools/cc/hooks/_hook_utils.py::SESSION_SIDE_SUFFIXES` (one more suffix)
- `tools/cc/seat.py::WORKER_BRIEF` (the handoff sentence)
- `tools/cc/seat.py::DISPATCHER_BRIEF` (the handoff sentence)
- `tools/cc/seat.py::WORKER_TICK` (the next-job clause)

### Renamed
- (none -- no symbol changes name)

### Added-paths
- `tools/cc/hooks/_hook_utils.py::HANDOFF_ASKED_SUFFIX`
- `tools/cc/hooks/_hook_utils.py::HANDOFF_CONTEXT_KEY`
- `tools/cc/hooks/_hook_utils.py::TRANSCRIPT_TAIL_BYTES`
- `tools/cc/hooks/_hook_utils.py::TRANSCRIPT_TAIL_MAX_BYTES`
- `tools/cc/hooks/_hook_utils.py::read_context_from_transcript`
- `tools/cc/hooks/_hook_utils.py::read_toml_scalar`
- `tools/cc/hooks/_hook_utils.py::handoff_context_threshold`
- `tools/cc/hooks/_hook_utils.py::handoff_push_on`
- `tools/cc/hooks/task_router.py::_context_advisory`
- `tools/cc/statusline.py::_read_statusline_payload`
- `tools/cc/statusline.py::_context_segments`
- `scripts/usage_tail.py`
- `tests/test_usage_tail.py`

### Removed-paths
- (none -- nothing is removed)

## Pass criteria

- The router, with the setting on and a transcript whose last assistant usage is at or past the
  threshold, prints the advisory on every prompt, active plan or not, and writes the side file
  once; with the setting off, absent, or the figure below, it prints what it prints today. The
  advisory encodes as ASCII, is under 700 characters, never says "commit and hand off", and carries
  the push clause only where `handoff_push = true`.
- `handoff_context_tokens` is read from the top level of `espalier.toml` only; a table key, a near
  spelling, a non-integer or `0` reads as off and is named.
- The side file is swept with its marker; no suffix in `SESSION_SIDE_SUFFIXES` ends in `.json`;
  `other_live_sessions` names no side file.
- The status line, fed the docs' sample payload, prints the two segments; fed a tty, nothing, or bad
  JSON, it prints the line, exits 0, and writes nothing. No assertion in `tests/test_statusline.py`
  may be weakened.
- The script dedups by message id (the synthetic test's earned red) and its name is in the roster.
- `tests/test_vendor_cc_parity.py` green; the asset twins in parity; `check_pack_fences.py` and
  `scope-check` clean on this pack; the full tier green on this seat; both Task 7 passes ran and
  their findings are in Landing (none found is a result).
- The live drive on this seat is recorded in Landing with the router's output and the figure.

## Files touched

- Modified: `tools/cc/statusline.py`, `tools/cc/hooks/task_router.py`,
  `tools/cc/hooks/_hook_utils.py`, `tools/cc/seat.py`, `tests/test_statusline.py`,
  `tests/test_task_router.py`, `tests/test_session_banner.py`, `tests/test_seat.py`,
  `tests/_surface_expected.py`, `docs/HOOKS.md`, `docs/HOOK_ASSUMPTIONS.md`,
  `docs/TROUBLESHOOTING.md`, `CLAUDE.md`, `espalier.toml`, the vendor mirror under
  `espalier/_vendor/cc/` and the asset twins under `espalier/assets/docs/` by their sync scripts.
- New: `scripts/usage_tail.py`, `tests/test_usage_tail.py`, the lane's `changelog.d/` fragment,
  this pack.
- Unmodified on purpose: `tools/cc/hooks/stop_gate.py` (Gate 5 is untouched and makes no claim
  here), `tools/cc/hooks/session_start.py` (the banner does not read the side file in this wave),
  `tools/cc/ship.py` (its own toml reader stays; the hard ceiling is a later wave),
  `.claude/settings.json` (the status line is already wired), `docs/ENV_CATALOG.md` (no env var).

## Sub-task ordering

0. Task 0 (0-1 measured, holds; 0-2 read on this seat's next loop; 0-3 measured) -> 1. Task 1
(`_hook_utils`) -> 2. Task 2 (router) -> 3. Task 3 (status line) -> 4. Task 4 (brief and tick) ->
5. Task 5 (script) -> 6. Task 6 (docs, mirrors, the tier) -> 7. Task 7 (the two passes, the live
drive) -> commit, `/handoff`.

## Estimated effort

Task 1: 60 min. Task 2: 60 min. Task 3: 30 min. Task 4: 20 min. Task 5: 45 min. Task 6: 30 min
plus the tier (about 45 min wall clock on this box). Task 7: 60 min. Total about 5 hours plus the
tier. Pack budgets here ran about 2.7x over on one measured pack
(`pack-budgets-ran-far-over-actual-on-tp459`); read this as a floor.

## Landing
- State: LANDED
- Commits: the one commit of `lane/hooks-the-threshold-handoff` ("hooks: the threshold
  handoff"; this stamp rides it by an amend by path, so the alive SHA is the merge commit on
  `main`, which the session row records)
- Suite: the full tier on this seat, twice (the second after the review batch): mypy and ruff
  clean; parallel leg 25099 passed, 85 skipped, 3 xfailed, 1 failed (`DEF-5025`, the Apple Git
  2.39.5 red on `git update-index --unresolve --`, fixed by #347, not in this base); serial leg
  2134 passed, 9 skipped. The first run's six reds: that one plus five of this lane's, folded
  (a deployed doc's pointer to a maintainer-only file, the census's two new rows adjudicated,
  the two audit events renamed into the fail-open family, the instrument's listings filtered in
  the accepted form, the test file's rationale docstring).
- Earn-the-red: Task 1 against HEAD's `_hook_utils.py` loaded from `git show` (the six new names
  missing, the `.handoff-asked` side file surviving its marker's sweep); Task 2 against HEAD's
  `task_router.py` (no ask past the threshold on a 271k transcript); Task 3 against HEAD's
  `statusline.py` (no segment on the docs' payload); Task 4 by the moved pins (the old
  substrings red against the new text); Task 5 the dedup (fifty lines, twenty-five messages).
- Red-team: the reasoning review at authoring (failure-mode-reviewer: REQUEST CHANGES, 2
  regressions, folded into the design: the transcript tail as the trigger, no half-lane ship);
  the artifact review at 0-A (code-reviewer: WARN only; the coordination section, the in-process
  test rule); at Task 7 three passes on a snapshot clone: code-reviewer REQUEST CHANGES (no
  BLOCK: NUL/recursion/NaN arms, a tautological test, first-ask validation, zero-usage skip,
  O_BINARY), architecture-analyst REQUEST CHANGES (BLOCK: the key missing from the engine's
  foreign-key census; WARN: the push bit now reads as `ship.py` reads it), failure-mode-reviewer
  REQUEST CHANGES (the brief's sentence reopened the half-lane push; synthetic zero-usage
  records; the shelve clause; the parked duties; the `/clear` reset's gaps, `DEF-4052`; a silent
  setting fault; the per-lane measure without an instrument, now per day). Every finding folded
  in one batch; the tier re-run after it.
- Reach: not a class pack; it closes no ledger class. Filed `DEF-4052`.
- Live drive: this session (the dispatcher seat, 2026-10-26): the router's ask rode every prompt
  event from 491k on, quoting its first ask at 10:01Z, and the status bar read
  `ctx=366k/1000k | limits=38%/83%` at the first look.
- Date: 2026-10-26
