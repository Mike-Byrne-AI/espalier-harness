# TP-705 — The banner splits at the ceiling: the lines a session acts on ride, the rest is one pull-only file

## Status

- Version target: next minor after the seats' mechanics lanes (TP-703b, TP-703e) land.
- Type: feature (one pull-only file beside the banner) + instrument (a transcript census).
- Kind: PACK
- State: DRAFT — authored by the dispatcher seat `air` on the operator's word of
  2026-11-01 local ("approved to author the banner pack", ack 20261102T020035Z-air-71ea1a
  on request 20261102T015900Z-air-aebe92). Assigns nothing until the operator approves the
  pack itself.
- Reasoning review at authoring (the `failure-mode-reviewer`, fresh context, 2026-11-01
  local): REQUEST CHANGES, 9 gaps, 3 rough edges, 0 regressions, every one folded below.
  The two that changed the pack: the first census counted the host's spill previews as
  banners (108 of 148), and the draft's second refuter was met by construction, so the
  pack's question became which lever gives the blueprint back, not whether a tenant yields.

## Motivation

The SessionStart banner is one hook context string under a host cap the pinned protocol
fixes at 10,000 characters per string, measured whole, with the overflow saved to a file
and replaced by a path and a 2,000-character preview Claude is not asked to read, and no
setting to raise it (`docs/external/cc-hook-protocol.md`, "Large-payload spill"). DEF-674
closed on 2026-10-29 by fitting the banner under `_MAX_CONTEXT_CHARS` (95 percent of
`_HOST_CONTEXT_CAP_CHARS`, counted by `tools/cc/hooks/session_start.py::_units` in
UTF-16 units): `::_fit_banner` sizes the blueprint to what the rest leaves, down to
`_BLUEPRINT_MIN_CHARS` and then to its header line, and only then clips the body (ack
20261018T203143Z-air-70c411, option (i)). That is the right order of last resort. It is
now the order of every start on the dispatcher seat, and what yields is the one content
tenant, the prior session's reasoning.

**Measured** (the census over this box's transcripts, `~/.claude/projects/<project>/*.jsonl`,
`attachment.type == hook_additional_context` records whose content opens the Session Start
banner, UTF-16 units; the one-file script is in this pack's Task 0, and the figures below
are from its prototype runs and the reasoning review's re-derivation on 2026-11-01, the
local day, about 02:05Z to 02:30Z on the 2nd):

- On the dispatcher clone (the main checkout's project directory) 148 SessionStart
  attachments carry the opening line; 108 are the host's spill previews
  (`<persisted-output>`: a banner past the 10,000-character cap, replaced by a path and a
  preview, every one before the ceiling landed, the newest 2026-10-31T06:45Z) and 40 are
  whole banners. Of the 40, 38 carry a GOAL section and the blueprint yielded on 22, which
  are every start since the ceiling landed (22 of 22, from 2026-10-31T07:47Z; 8,451 to
  9,465 units). On the newest 14 (2026-10-31T17:30Z to 2026-11-02T00:59Z) its share
  (`_MAX_BLUEPRINT_CONTEXT_BYTES`) was cut to between 73 and 1,687 units, a loss of 1,153
  to 2,695 units against what the loader handed in, while the goal file rode whole at
  2,887 to 4,493 bytes against `_SOFT_BUDGETS["goal"]` (2,000; `_GOAL_HARD_CAP` 4,500), as
  the health ledger's own `goal N of 2000 bytes` line says. The banner sat at 9,436 units,
  the ceiling less `_BANNER_MARGIN`, on 9 of those 14, and one start clipped the body
  (2026-11-01T18:22Z, goal 4,493 bytes, blueprint 2,747 cut to 73). On the three starts
  that kept 305 units, the health line's own `headroom` figure left 350 to 776 units
  unspent: `::_bound_blueprint_context` drops whole lines, so the blueprint keeps less
  than it is given.
- On the worker worktree (`.claude/worktrees/work`, its own project directory) 34 whole
  banners and 13 spill previews (the newest 2026-10-30T19:55Z); the 22 whole banners since
  the ceiling landed ran 7,455 to 8,849 units with no GOAL section and no yield: the goal
  file is gitignored and per checkout, so a worker's banner never carries one
  (`DEF-1136`). The orientation block is 1,594 units on every one of them.
- Per section, the prototype's ranges mixed the spill previews in, so they are not quoted;
  the whole-banner figures that stand are the GOAL section at 2,783 to 4,474 units on the
  38 dispatcher starts that carried one, the health block at 99 to 632, the orientation
  block at 1,557 to 1,594 (1,594 on every worker start), the FOOTGUNS pointer at 256 and
  the STANDING index at 123 on this tree. Task 0's script prints every section's spread
  over the whole banners alone.
- Neither prototype run separated the spill previews (the first, which globbed every
  project directory whose name carries the repository's, read 75; the second, over one
  explicit directory per seat, read 148 attachments and called them banners). The reasoning
  review's re-derivation is what the figures above quote; Task 0's script takes
  `--project`, never globs a name, and counts whole banners, spill previews and compact
  banners apart.
- Whole banners over the ceiling (between `_MAX_CONTEXT_CHARS` and the host cap): five on
  the dispatcher clone, all before DEF-674's lane merged (the newest 2026-10-29T07:28Z,
  9,612 units), and three on the worker worktree on 2026-10-30 (9,519 to 9,885 units),
  whose HEAD the prototype did not read; Task 0 keys each to the banner's own `Checkout:`
  line, and one on a HEAD past the merge is a row.
- Windows seats' transcripts are not on this box. Task 0 has each seat run the census
  where it sits and send the printed lines by mail.

So the dispatcher's banner loses its blueprint every start to a goal-proper that does
not change between handoffs. That is by construction: the blueprint is the only tenant
`::_fit_banner` can shrink (its `sized` closure), every other tenant having been bounded
before the call (`::_load_blueprint` through `::_bound_blueprint_context` to its 3,000
bytes, the goal through `::_bounded`, the run lines through `::_fit_run_lines`), so the
question this pack puts is which lever gives the reasoning back, not whether a tenant
yields. The banner's only pointer to what it dropped is the yield line's `the rest is in
cc/blueprints (/read-summary)`, which names the blueprint archive and not the banner that
was built. Nothing the harness writes today holds the banner as it stood before the fit.

## Scope (in)

1. **An instrument**: `scripts/banner_census.py`, stdlib only, over one project's
   transcripts: per banner the start time, source, total units and per-section units; the
   yield and clip counts; the goal bytes from the health ledger; `--project <dir>`,
   `--last N`, `--json`. The Task 0 oracle and the pass criteria's instrument.
2. **The full banner on disk**: when the blueprint yielded or the body clipped, the start
   writes the banner as it stood before the ceiling fit (the blueprint at the loader's
   full output, before `::_bound_blueprint_context`; the body unclipped; the health block
   in place), stamped with the session id and the time, to one pull-only file under the
   state directory (`_hook_utils.STATE_DIR`, `.espalier-state/banner_full.txt`, per
   checkout, gitignored by the existing `.espalier-state/` rule), removed at the top of
   every start and written again only on a yield or a clip, so a start cut at the wall
   leaves no older banner behind; the health block's pointer line names the file and the
   verb that prints it, and only on a build that was given a writer.
3. **The verb**: `tools/cc/read_summary.py --banner` prints that file, or one sentence when
   there is none; `.claude/commands/read-summary.md` documents it; mirrors by the sync
   scripts.
4. **The levers, put to the operator with measured cost** (Implementation 4): which of
   them gives the blueprint back, with Task 0's per-start table: the ranking order (the
   goal's excess past its soft budget yields before the blueprint), filling the blueprint
   to its allowance, the goal file shortened, or none beyond the file of item 2. The pack
   lands items 1 to 3 under any of them; the ranking order is one named constant.
5. **A measurement, no change**: how much of the orientation block's 1,594 units repeats
   text already in the root `CLAUDE.md` and the shipped `docs/HOOKS.md` and `WORKFLOW.md`
   (Implementation 4).

## Scope (out)

- **Raising the cap.** None exists: the pinned protocol says the 10,000-character cap has
  no setting or environment variable, and the overflow is a file Claude is not asked to
  read. Everything here stays under `_MAX_CONTEXT_CHARS`.
- **The compact (post-compaction) banner.** `::_build_compact_context` calls the same
  `::_fit_banner` with `_COMPACT_BLUEPRINT_MAX_CHARS`; its attachment opens
  `=== ... POST-COMPACTION RE-ORIENT`, 22 on the dispatcher clone and 20 on the worker
  worktree, none since the ceiling landed (the threshold handoff replaced compaction), so
  no yield is measured there and the compact builder passes no writer. The census reads
  them apart; a follow-up touches that path if one ever yields.
- **The goal file's content and budget.** `cc/GOAL.md` is the operator's hand; its soft
  budget and hard cap stay. `DEF-1136` (a worktree reads the main checkout's goal and
  cannot write its own) is its own row.
- **The seat brief re-prime** (`DEF-4052`): what a cleared window is told is the own-clear
  mod's, not the banner's.
- **The orientation block's length.** Shortening it changes every adopter's first response
  and the three phrases two test files pin, `tests/test_hooks.py` and
  `tests/test_session_banner.py` (`Orientation (on first response`, `first-thoughts`,
  `confirm or redirect`); it is measured here (Implementation 4) and
  proposed as a follow-up with its own before-and-after, not cut in this pack.
- **The `Mail:` line's operator-call count** (`DEF-4043`): a header line's content, not
  its size.

## Task 0 — Verify

**The oracle.** From the checkout root, after sub-task 1 lands the script:

```bash
python3 scripts/banner_census.py --project ~/.claude/projects/<this project dir> --last 20
```

On the Air, run it for the main checkout's directory and the `work` worktree's; on the
Windows box, for `win` and `win-2`'s (the transcript roots are `%USERPROFILE%\.claude\projects`
there). Each worker seat sends the script's summary lines as a note naming this pack.

**The refuting result.** If on the dispatcher seat's last 20 whole banners the blueprint
rode whole and no section was cut, and the same holds on every worker seat, the split is
not built: the goal-file discipline (its soft budget and the `Notes to next session`
head) is the whole fix, and this pack ends at Task 0. What is NOT a refuter: that the
blueprint is the only tenant that yields, and only while the goal is past
`_SOFT_BUDGETS["goal"]`; that is true by construction (Motivation) and on all 22 yields
(the lowest goal 2,783 bytes). What Task 0 decides beyond the kill condition is the
per-start table for Implementation 4 (`--ranking`): for each of the dispatcher seat's
yields, the blueprint's loss, the goal's excess past its soft budget, the headroom the
health line reports, and whether excess plus headroom covers the loss. The review's
arithmetic on the newest 14: the alternative order covers the loss on 1 start, about 5
counting the health lines that would drop, so the ranking alone does not give the
reasoning back, and the operator's letter chooses among the levers with that table.

**The exit.** Stop and re-raise to the operator with the census lines; the approval was
given against the measured yields above, and a census that does not reproduce them
takes the approval with it.

**What was already driven.** The prototype census (two runs on 2026-11-01 local, neither
separating the spill previews) and the reasoning review's re-derivation (which did) are
what the Motivation quotes; neither is the script this pack lands. The first thing
sub-task 1 proves is that the script's population line for each seat's directory matches
the review's (40 whole banners and 108 previews on the dispatcher clone; 34 and 13 on the
worker worktree), and that every banner over
`_MAX_CONTEXT_CHARS` it finds is keyed to the HEAD its `Checkout:` line names: one on a
HEAD at or past DEF-674's merge is not a refutation but a row, filed in-lane before
anything is built (the backstop `::_fit_to_ceiling` let it through).

## Relevant memory

What has been biting lately: the last two lanes on this surface each landed with a
follow-up correction. DEF-674's closing lane (2026-10-29) was followed by the per-run line
pool and the blueprint's header-line floor under two dispatcher rulings (70c411, 126ea0);
DEF-3015's wall (2026-10-31) was followed by `DEF-5051`, the mail block read after the
pull-request block under what it leaves of one deadline, the banner's own time-share
accounting. Budget the red-team for the repair, not the defect.

| Entry | Where |
|---|---|
| Hook authoring | `memory/hook-authoring.md` |
| Hooks (Mechanical Enforcement) | root `CLAUDE.md` :: Hooks (Mechanical Enforcement) |
| Statusline reads blueprints with fd-level bounds | `docs/SHARP_EDGES.md` :: Statusline reads blueprints with fd-level bounds |
| Gates the targeted proofs never show | `memory/four-gates-the-targeted-proofs-never-show.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "banner ceiling"` and
`python3 tools/cc/hooks/_recall.py "session start banner size"` (2026-11-01 local); neither
query surfaced a banner-specific entry, so the two rulings that shaped `::_fit_banner`
are cited by id above (acks 20261018T203143Z-air-70c411 and 20261018T210745Z-air-126ea0,
on the `air` mail ref). Re-run the queries rather than trusting this list if the pack
has been sitting.

## Implementation

### 1 — The census script *(the instrument; its own test is the proof)*

`scripts/banner_census.py`, modelled on `scripts/seat_day_census.py`: for each `*.jsonl`
under `--project` (one explicit directory; no glob over names), every record whose
`attachment.type` is `hook_additional_context`; its `content` is a list of strings, each
read on its own. A string is one of three kinds, counted apart: a whole banner (opens
`=== Espalier-Harness === Session Start ===`), a spill preview (the same opening inside
the host's `<persisted-output>` form, a banner the host saved past its cap), a compact
banner (opens `=== ... POST-COMPACTION RE-ORIENT`). No record names a source
(`hookName` is `SessionStart` on every one), so the kind is read from the text. Per whole
banner: the record timestamp, the HEAD its `Checkout:` line names when one does,
`len(text.encode("utf-16-le")) // 2` for the whole and for each section split on the
headers the hook renders: three are module constants (`_HEALTH_HEADER`, `_GOAL_HEADER`,
`_GOAL_HEADER_COMPACT`) and four are inline literals or f-strings in the hook (the
MEMORY, STANDING, FOOTGUNS and WARNINGS headers, plus `Orientation (on first response`),
so the script carries all of them as literals and its test pins the three constants equal
and greps the literal ones in the hook's source; the yield line's two figures, the
ledger's goal bytes and headroom, whether the body-cut marker is present. Summary lines:
the population by kind (whole, spill, compact; transcripts; directory), the whole banners
before and since the ceiling (by date against DEF-674's merge, by HEAD where read), total
units min/median/max, per-section min/median/max over the whole banners alone, yields and
clips, the goal bytes' spread; `--ranking` prints the per-start table of Task 0; `--last
N` keeps the newest N; `--json` gives the same as data. Stdlib only, 7-bit ASCII output,
no import from `tools/cc/`.

### 2 — The full banner on disk *(fix shape, untested — refuted if the loader's full blueprint cannot reach `_fit_banner` beside the bounded one without a second render of the slot, which sub-task 2's checkpoint decides)*

`tools/cc/hooks/session_start.py::_fit_banner` holds `header_parts`, `body_parts`, `tail`
and `blueprint`, but `blueprint` arrives already cut to `_MAX_BLUEPRINT_CONTEXT_BYTES` by
`::_load_blueprint` through `::_bound_blueprint_context` (8 of the newest 14 yield lines
start at exactly 3,000, that pre-cut), and the goal, memory, standing index, run lines,
reinject payloads and identity line are bounded before the call too. So the file is the
banner as it stood before the ceiling fit, not every tenant unbounded: `::_build_context`
passes the loader's full blueprint text beside the bounded one, and `_fit_banner` gains
two keywords, `full_blueprint: str` and `on_full: Callable[[str], None] | None`, calling
`on_full` once with the slot rendered from `full_blueprint`, the body unclipped and the
settled health block in place, only when `bp != blueprint` or `loss` is non-zero. The
first line of the text stamps the session id and the start time, so a reader can tell
whose banner it is. `::_run_main` builds the writer where the state directory is known:
it removes `.espalier-state/banner_full.txt` at the top of every start (a start cut at the
wall, a crash or a compact start then leaves no older banner for `--banner` to print as
current), and writes it through `_hook_utils.atomic_write_text` under
`_hook_utils.STATE_WRITE_LOCK`, the lock `::_cut` holds before `os._exit`; `_EMIT_LOCK` is
held only inside `::_emit` and is not the lock here. The atomic write (a temporary file,
then `os.replace`) makes a torn file impossible; what a cut at the wall can leave is an
orphan temporary file, named in the red-team. The health block's pointer line changes
from `the rest is in cc/blueprints (/read-summary)` to `the banner before the fit is in
.espalier-state/banner_full.txt (/read-summary --banner)`, printed only on a build that
was given a writer: `::_build_compact_context` calls the same `_fit_banner` and passes
none (Scope out).

Refutations to carry into the checkpoint: the file must never be read by the hook (a
pull-only file that the next start reads is a second tenant); the write sits inside the
hook's budget (one file of a few kilobytes) and before `::_fit_to_ceiling`; the sentinel
row drives the real loader with a blueprint past 3,000 bytes, not a monkeypatched
`_load_blueprint`, or it cannot see the pre-cut.

### 3 — The verb *(fix shape, untested — refuted if `read_summary.py::main`'s bare-call guard cannot take one more flag, which its shape says it can)*

`tools/cc/read_summary.py::main` treats any call without `list`, `session`, `path`, `all`
or `index` as bare and prints `cc/_working_summary.md`; `--banner` joins that guard, else
it prints the working summary with exit 0 and reads as working. It prints
`.espalier-state/banner_full.txt` from the checkout root, or the one sentence `no full
banner was saved: nothing yielded at the last start` with exit 0 when it is absent. The
script is not under `hooks/` and cannot import `_hook_utils.STATE_DIR`, so it carries the
`.espalier-state` literal and its test pins the literal to the hook's constant.
`.claude/commands/read-summary.md` gains the flag's line; `python3
scripts/sync_claude_mirrors.py` regenerates the mirrors; `python3 scripts/sync_vendor_cc.py`
the vendored copies of both scripts.

### 4 — The levers *(the operator's; stated with cost, not prescribed)*

Today the blueprint yields first (70c411 option (i)): on the newest 14 dispatcher starts it
lost between 1,153 and 2,695 units of what the loader handed in. The levers, each priced
by Task 0's per-start table:

- **The ranking order**: the goal's excess past `_SOFT_BUDGETS["goal"]` yields first, by
  `::_bounded`'s existing cut (which keeps the tail, so the `Notes to next session` head
  is what goes, as `cc/GOAL.md`'s own order note says; the orientation block's sources
  line then names a head that may be gone and follows the cut). On the same 14 starts the
  goal would have lost between 887 and 2,493 bytes, and the review's arithmetic says that
  excess plus the reported headroom covers the blueprint's loss on 1 of the 14 (about 5
  counting the health lines that would drop): the order alone does not give the reasoning
  back. Mechanically the goal reaches `_fit_banner` as an opaque string inside the body,
  so the order needs a goal slot in `_fit_banner`'s signature beside the blueprint's, one
  module constant `_GOAL_EXCESS_YIELDS_FIRST` (False keeps today's order), and
  `::_build_compact_context` listed under Changed-semantics since it calls the same
  function.
- **Filling the blueprint to its allowance**: on the three starts that kept 305 units,
  350 to 776 units were unspent (`headroom` on the health line), because
  `::_bound_blueprint_context` drops whole lines; a cutter that fills to the unit gives
  that back on every yield, costs no other tenant, and is the cheapest lever.
- **The goal file shortened**: the operator's hand; the table says how many bytes on each
  start would have let the blueprint ride whole.
- **Nothing beyond the file of sub-task 2**: the reasoning is on disk and one verb away.

A further option the table can price: the goal's excess yields first but `keep_tail`
flips, so the goal-proper goes and the Notes head rides; it changes `cc/GOAL.md`'s own
order rule and is a scope change for the operator. The pack lands sub-tasks 1 to 3 under
any lever; the operator's letter picks, and whichever tenant yields is in the file of
sub-task 2 as it stood before the fit.

### 5 — The orientation block, measured *(no change)*

Count the units of `::_orientation_common`'s text that repeat a sentence in the root
`CLAUDE.md` ("it OPENS with a provisional first-thoughts read"), the shipped
`espalier/assets/docs/HOOKS.md` (its orientation bullets) and `WORKFLOW.md` (its
first-thoughts sentence). Report the figure in Landing. Propose nothing here.

## Affected symbols

### Changed-semantics
- `tools/cc/hooks/session_start.py::_fit_banner`
- `tools/cc/hooks/session_start.py::_build_context`
- `tools/cc/hooks/session_start.py::_run_main`
- `tools/cc/hooks/session_start.py::_build_compact_context`
- `tools/cc/hooks/session_start.py::_load_blueprint`
- `tools/cc/read_summary.py::main`

### Renamed
- None.

### Added-paths
- `scripts/banner_census.py`
- `tests/test_banner_census.py`

### Removed-paths
- None.

## Reach

This pack claims no ledger class and closes no row by itself: DEF-674 is closed and its
contract (the banner under the ceiling) is kept, not reopened. Adjacent live rows it does
not reach, by id: `DEF-1136` (a worktree's goal is the main checkout's; this pack changes
what is kept of a goal, not whose), `DEF-4052` (the cleared window's re-prime is the mod's
text, not the banner's), `DEF-4043` (the `Mail:` line's count, content not size). A row
for the yield itself, if the operator wants one, is filed in-lane from the seat's block
with the census as its probe.

## Pass criteria

- Every assertion in `tests/test_session_banner.py` and `tests/test_hooks.py` that holds
  the banner under `_MAX_CONTEXT_CHARS` stays; none is weakened and no fixture is removed.
  A new assertion that strengthens one is welcome.
- New rows, node-driven: a start whose blueprint yields leaves `banner_full.txt` holding
  the loader's full blueprint (a sentinel sentence past the 3,000th byte of a fixture
  blueprint read through the real loader is in the file and not in the banner), stamped
  with the session id, and the pointer line in the banner; a start where only the body
  clips does the same; a start where nothing yields leaves no file, removes one an earlier
  start left, and prints no pointer; a start cut at the wall before the write leaves no
  file; the compact banner writes nothing and prints no pointer.
- `read_summary.py --banner` prints the file verbatim, or the no-file sentence with exit 0.
- `tests/test_banner_census.py`: a fixture transcript with three whole banners (one yielded,
  one clipped, one whole, one of them holding an astral character), one spill preview and
  one compact banner gives the counts by kind and the UTF-16 units the fixture was built
  to; the three header constants the script carries equal the hook's, and the literal
  headers are found in the hook's source.
- Earn-the-red, per fix: (2) skip the write when only the body clips; print the pointer
  with no file written; skip the removal at the top of the start; pass the bounded
  blueprint instead of the loader's full text; each must redden its row. (3) drop
  `args.banner` from the bare-call guard, so the working summary prints instead; print
  the clipped banner instead of the file; each reddens. (1) count with `len()` instead of
  UTF-16 units (the astral fixture reddens); count a spill preview as a whole banner (the
  population row reddens). Landing records each red.
- The hook's own gates: `pytest tests/test_hooks.py tests/test_hook_protocol.py
  tests/test_failopen_voice.py tests/test_spawn_chokepoint.py tests/test_vendor_cc_parity.py`
  green; the tier the diff earns (`python3 scripts/proof_tier.py --base origin/main`),
  which is the full tier for a hook change.

## Files touched

- New: `scripts/banner_census.py`, `tests/test_banner_census.py`, the pack's changelog
  fragment under `changelog.d/`.
- Modified: `tools/cc/hooks/session_start.py`, `tools/cc/read_summary.py`,
  `tests/conftest.py` (`_MARKER_RULES`, the new test file's row),
  `.claude/commands/read-summary.md` (and its two mirrors by sync), `espalier/_vendor/cc/`
  copies of both scripts by sync, `tests/test_session_banner.py` (new rows),
  `tests/test_read_summary.py` (the verb), `docs/HOOKS.md` (the SessionStart paragraph's
  pointer sentence) and its assets twin by the asset-doc sync.
- Deleted: none.
- Unmodified on purpose: `cc/GOAL.md` (the operator's), `::_build_compact_context`,
  `::_orientation_common`, `docs/external/cc-hook-protocol.md` (the pin stands).

## Sub-task ordering

1. **0-A Task 0** — land sub-task 1's script on the lane first, run the census on every
   seat, collect the notes; decide: build, or stop. Checkpoint: each seat's summary lines
   and the per-start table in the pack's Landing, and the kill condition not met.
2. **1-A The census script and its test** — the smallest change; checkpoint
   `pytest tests/test_banner_census.py`.
3. **2-A `_fit_banner`'s `on_full`, the writer, the pointer line** — checkpoint the new
   rows in `tests/test_session_banner.py` red before, green after, and the earn-the-red
   mutations recorded.
4. **3-A The verb and the docs** — checkpoint `pytest tests/test_read_summary.py`, both
   syncs run, `python3 scripts/sync_claude_mirrors.py --check` style parity green.
5. **4-A The lever the operator's letter names** — the ranking constant, the filling
   cutter, or neither; checkpoint the yield rows under each value built.
6. **5-A The orientation measurement** — a figure in Landing.
7. **6-A Red-team** — the `adversarial` skill over the hook diff, with the pack's likeliest
   error named: a stale file from an earlier start printed as current (the removal at the
   top of the start skipped or raced), and an orphan temporary file left by a cut at the
   wall. Ask for the mutation that survives.
8. **7-A Verification** — the tier, `/handoff`, the Landing stanza.

## Estimated effort

| Sub-task | Budget |
|---|---|
| 0-A Task 0 (the runs on two boxes, every seat the board names, and the mail round-trip) | 2 h |
| 1-A census script + test | 1.5 h |
| 2-A full file + pointer + rows | 3 h |
| 3-A verb + docs + syncs | 1 h |
| 4-A the lever ruled (if any) | 1 h |
| 5-A orientation measurement | 0.5 h |
| 6-A red-team | 1.5 h |
| 7-A verification (the full tier) | 1 h |
| **Total** | **11.5 h** |

## Landing
- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
