# TP-475 — Know when work is worth doing: a per-surface replacement alarm and a layer check before the class question

## Status

- Version target: after `0.8.0b2`, on its own lane. Execution waits on Task 0.
- Type: feature (ledger flow tooling) + process (the discipline the tooling feeds).
- **Kind: PACK.**
- Ledger: one §3 row names this pack (filed 2026-10-07). Task 1 closes an unfiled candidate: `scripts/ledger_trend.py` prints an unchecked per-step identity on a merge-heavy ref.
- Gate: on 2026-10-07 the operator approved the direction ("the guards you just outlined sound like a solid levelup for espalier, especially the ledger system ... We want to know when something is 'worth doing' and when something is 'banging against a brick wall'") and asked that the next session build it. Sibling pack: `TP-476` (guard by location), the instance that motivated this one.
- Provenance: measured on the Windows clone, 2026-10-07. Each measured claim names its command; the scratch drivers lived in the session's job directory and are not committed, and Task 0 rebuilds what it needs inside the tool.

## Motivation

**The operator's question:** when the ledger shows more rows filed than closed, is the work converging, or are we banging against a brick wall? Nothing in the tree answers it per surface.

**What the ledger-wide number said (measured).** Command: `python scripts/ledger_trend.py --ref origin/main --since 2026-10-04`, window lines only (see Task 1 for why the per-step table is unreliable).
- Live rows went 323 -> 315.
- 46 backlog rows were struck and 38 replacements filed, so 0.83 replacements per row drained. Contract rule 5 calls anything below 1.0 convergent.

**What it hid (measured).** The source was a first-parent, end-of-day series over `origin/main`, reusing `ledger_trend`'s parsers.
- One surface, the guard's command parser (`tools/cc/hooks/_bash_patterns.py`, `tools/cc/hooks/write_guard.py`, the guard benches), replaced itself at about 1:1 over the same days.
- Each guard fix lane's reviewers filed one to three sibling spellings:
  - #126 -> `DEF-1161`, `DEF-1162`
  - #132 -> `DEF-1173`, `DEF-1174`, `DEF-1175`
  - #131 -> `DEF-1176`
  - #136 -> `DEF-1170`, `DEF-1171`
- Nine of the ten live majors sat on that surface, and 31 of its rows sat in the standalone class `§C0`.

**Why it was a brick wall.** The rows were protected-zone and secret-read jobs, both questions of *location*. They were being chased spelling by spelling in a command-text parser that can never be complete, while a location layer covers every spelling at once (`TP-476`).

**Why every gate let it through.** Each gate checks a fix *inside the frame it is handed*:
- the ledger row states the root cause at the reader level;
- the class question (root `CLAUDE.md` Core Rule 12) asks "is this one site of a class?" and answers with a bigger fix in the same layer;
- reviewers find the next sibling spelling;
- `/implement-task` plans the fix as given;
- `docs/STANDING_PRINCIPLES.md` §16 names the user truthfully.

None asks whether the layer can reach the goal. The detectors already existed and nothing fired them:
- §2 says false positives "outrank closing bypass classes";
- §15 says that a different failure each time means the problem is mis-specified, not hard;
- the operator's global rule asks "which layer is 'it', which is the fix?"

**The named user (§16):**
- the operator deciding which ledger work to fund, who saw filings outpace closes and could not tell a converging stream from a wall;
- every lane agent who files a sibling-spelling row as one more parser fix.

## Scope (in)

1. **Task 1** — `ledger_trend.py` reads a merge-heavy ref first-parent, and its per-step reconciliation checks itself (the smallest change; it makes Task 2's numbers trustworthy).
2. **Task 2** — a per-surface view: replacement per drained row for each surface, over the window and over a trailing window, with the window identity checked per surface.
3. **Task 3** — the alarm where the next member is born. `tools/cc/ledger_row.py::file_row` prints an advisory, never a refusal, when the row lands on a surface whose trailing replacement has stayed at 1.0 or above. The advisory names the layer questions.
4. **Task 4** — the layer check as discipline:
   - a `memory/` note;
   - a clause in Core Rule 12 that asks the layer question before the class question;
   - a principle (a new §20, or an extension of §15: the operator decides);
   - one question in the two reviewer agents' bodies.
5. **Task 5** — red-team. **Task 6** — verify and land.

## Scope (out)

- **Re-triaging the guard rows by job.** That is `TP-476`'s Task 0, which has its own oracle. This pack builds the instrument; that one applies it to the guard.
- **Making the alarm a gate.** A refusal at filing time is rejected up front: a count gate teaches the filer to fabricate or suppress (`memory/gating-on-count-manufactures-findings.md`). The alarm advises, and the filer still files.
- **Deciding a row's layer mechanically.** No oracle can. The layer check is a question for the filer and the reviewer, recorded in their words.
- **A SessionStart banner line for hot surfaces.** It is a candidate follow-up once Task 3 has been seen in use. One firing place first.
- **The `record` ref's behaviour.** It stays as it is (Task 1 verifies the flag is a no-op there).

## Task 0 — Verify (try to kill this pack)

**0-A Back-test the alarm.**
- Oracle: a first-parent, end-of-day snapshot series of `task-packs/FORWARD_LEDGER.md` over `origin/main` from 2026-09-24. Derive it with `git log --first-parent --format='%H %cd' --date=format-local:%Y-%m-%d origin/main -- task-packs/FORWARD_LEDGER.md`, keep the last commit per day, and parse with `tools/cc/generate_ledger_regions.py` the way `scripts/ledger_trend.py::state` does.
- Group the ids per surface under two candidate keys, and record which one is chosen:
  - **k1:** the row's class (`§C`).
  - **k2:** the first path family of its site cell (top-level directory plus module stem).
- **Pre-register before reading which surfaces fire:** the alarm fires for a surface when replacement per drained is 1.0 or above over a trailing window of W days with at least D rows drained. The proposal is W = 5 and D = 5. Set them once and write them in the Landing stanza.
- **Refuting result (do not build Tasks 2 and 3):** any one of these.
  - Under both keys, the guard surface does not fire anywhere in 2026-10-04..2026-10-07.
  - More than half of the surfaces that reach D drained fire, so the alarm does not discriminate.
  - It fires only under a key that cannot be computed from the row's own cells at filing time.
- **Exit:** stop and re-raise with the series. Do not tune W or D after reading.

**0-B Back-test the layer check.**
- Take the guard rows first seen 2026-10-02..2026-10-07: rows whose site cell names `tools/cc/hooks/_bash_patterns.py`, `tools/cc/hooks/write_guard.py` or `tools/cc/hooks/_speedbump.py`, with first-seen dates from the 0-A series.
- For each row, answer three questions from its **headline sentence only**:
  - (a) Is the job a *location* (a path that must not be written or read) or an *action* (a push, a tag)?
  - (b) Does a layer exist that enforces that job whatever the spelling?
  - (c) Would a slipping agent plausibly type this spelling?
- Count the rows the check would have routed away from a parser fix.
- **Refuting result (drop Task 3's layer wording and Task 4's reviewer and principle edits; keep only the memory note):** fewer than three rows would route differently.
- **Exit:** re-raise.

**0-C Hygiene.** 0-B reads headlines in effect-words, one row's first sentence at a time, never full rows in a run. Two lane agents were stopped by the platform classifier on 2026-10-07 while reading full guard-defect rows and bench files (`docs/CLASSIFIER_FALSE_POSITIVES.md`, "Variant generation" and the coordinator-brief bullet).

## Relevant memory

Recent pattern, measured 2026-10-07:
- The ledger-wide flow read convergent (0.83) while one surface replaced itself at about 1:1.
- The fix stream on that surface was built in a layer that cannot reach its goal.
- No gate asked about the layer.

| Entry | Where |
|---|---|
| Classify the surface before you measure it | `memory/classify-the-surface-before-measuring-it.md` |
| Gating on count manufactures findings | `memory/gating-on-count-manufactures-findings.md` |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| A gate can be blind along a whole dimension of its input | `memory/a-gate-can-be-blind-along-a-whole-dimension.md` |
| A New Guard Is Blind The Way It Claims To See | `docs/SHARP_EDGES.md` (that section) |
| Convergence review protocol | `memory/convergence-review-protocol.md` |

Resolved at authoring time with `python tools/cc/hooks/_recall.py "a fix whose layer cannot reach the goal; many attempts failing a new way"` and `python tools/cc/hooks/_recall.py "measure backlog flow replacement per drained row"`, plus the second and third rows named by hand. Re-run them if the pack has been sitting.

## Implementation

### Task 1-A `ledger_trend.py` walks a merge-heavy ref first-parent *(fix shape, untested)*

**Defect (measured 2026-10-07).** `python scripts/ledger_trend.py --ref origin/main --since 2026-10-04` printed "the steps' struck column sums to 199 = backlog 46 + churn struck in a later step 9" with no warning. `scripts/ledger_trend.py::snapshots` runs `git log <ref> -- <path>` without `--first-parent`, so consecutive snapshots alternate between parallel lanes and the same rows strike again and again. The window lines (first snapshot against last) are sound.

```python target=scripts/ledger_trend.py
    run = _git(repo, "log", "--first-parent", "--format=%H %ad", "--date=short", ref, "--", path)
```

Second part: `scripts/ledger_trend.py::render` checks the reconciliation identity it prints, and prints `WARN` when the identity fails, as the window identity already does.

- **Refuted if:** `git log --first-parent record -- task-packs/FORWARD_LEDGER.md` differs from the plain log on a machine holding the `record` ref (that ref is meant to be linear). Then gate the flag to refs other than the record ref.
- **Earn the red:** build a two-lane fixture repo in a test, where a row is struck on one lane and a later-dated commit on the other lane still carries it live. The per-step struck sum must equal backlog plus churn-struck-later. The test must be red against the current `snapshots`.

### Task 2-A A per-surface view *(fix shape, untested; the key comes from Task 0)*

- `ledger_trend.py --by-surface` groups ids by the chosen key.
- Per surface it prints filed, backlog struck, replacement and the ratio ("n/a" below D drained), over the window and over the trailing W days. It also prints the per-surface identity check.
- The JSON output gains the same per-surface table.
- **Where the computation lives.** `tools/cc/ledger_row.py` (deployed, standalone) must reach it for Task 3, and `tools/cc/` imports nothing from `scripts/`. So put the shared core in `tools/cc/`, and make `scripts/ledger_trend.py` a CLI over it. Today `state`, `diff` and `window` live in the script; a new module `tools/cc/_ledger_flow.py` is the fix shape. Then:
  - run `python scripts/sync_vendor_cc.py` after the edit;
  - check `espalier/mirror_registry.py` for the row this file joins.
- **Refuted if:** the chosen key leaves more than a fifth of live rows keyed as `UNTAGGED`. The key is wrong; re-raise.
- **Earn the red:** a fixture ledger history where one surface replaces 1:1 and another converges. The view must separate them, and must fail when the key function is reverted to the class key on a fixture whose classes cross surfaces.

### Task 3-A The alarm at filing time *(fix shape, untested)*

`tools/cc/ledger_row.py::file_row`, after a successful write (and under `--dry-run`), computes the filed row's surface and that surface's trailing replacement through `tools/cc/_ledger_flow.py`. When the surface fires (the W and D values from Task 0), it prints a short advisory to stderr:
- the surface;
- its trailing ratio;
- the three layer questions from 0-B;
- a pointer to the Task 4 memory note.

It exits 0 whatever it prints. On an adopter tree with no ledger history it stays silent and says why once (`docs/CONVENTIONS.md`, "Fail-open with voice").
- **Refuted if:** the computation adds more than about a second to `file_row` on this tree. Then read a cache written by `ledger_trend.py` instead.
- **Earn the red:** with a fixture history where the surface fires, the advisory appears; reverting the surface lookup makes the test red.

### Task 4-A The layer check as discipline *(prose; earned by 0-B)*

- **`memory/check-the-layer-before-the-class.md`.** The class this pack names: a fix whose layer cannot reach its goal passes every gate. Content:
  - the instance (protected-zone writes chased spelling by spelling; `TP-476`);
  - the three questions;
  - the tell (one surface replacing itself at 1:1 or worse across lanes; §15);
  - a cross-link to `memory/fix-the-class-not-the-instance.md`, which this note precedes.
- **Root `CLAUDE.md` Core Rule 12.** One clause before the class question: "first ask whether the layer can reach the goal; a surface replacing itself at 1:1 is the tell". Rule 12's sole home stays the memory note.
- **The principle:** a new `## 20.` in `docs/STANDING_PRINCIPLES.md`, or a paragraph under §15. The operator decides.
  - Check `docs/STANDING_PRINCIPLES.aliases.md` and the SessionStart standing-principles index first, because both pin the principle set.
  - Check the record-surface list (`tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS`) before editing any doc (root `CLAUDE.md` Core Rule 13).
- **`.claude/agents/failure-mode-reviewer.md` and `.claude/agents/code-reviewer.md`** gain one question: "is this fix in a layer that can reach its goal, or one more instance in a layer that cannot?" Then run `python scripts/sync_claude_mirrors.py`.

## Affected symbols

`/scope-check` keys on bare names. `main` and `render` match more than a thousand unrelated sites across the tree, so its gap list for this pack is name collisions, checked at authoring. The real referrers are derived by `grep -rln ledger_trend tests scripts tools espalier`. On 2026-10-07 that listed six files besides the script itself:
- its own tests;
- `tests/conftest.py`;
- a surface-expectation table under `tests/`;
- `scripts/ledger_rebuild_assemble.py`;
- `tools/cc/generate_ledger_regions.py` and its vendored twin.

Read each before moving the core into `tools/cc/_ledger_flow.py`. The grammar module referring back to the script is the one most likely to make the move circular.

### Changed-semantics
- `scripts/ledger_trend.py::snapshots`
- `scripts/ledger_trend.py::render`
- `scripts/ledger_trend.py::trend`
- `scripts/ledger_trend.py::main`
- `tools/cc/ledger_row.py::file_row`

### Renamed
- (none -- the core moves into a new module; the script's names stay as thin wrappers)

### Added-paths
- `tools/cc/_ledger_flow.py`
- `memory/check-the-layer-before-the-class.md`

### Removed-paths
- None.

## Reach

This pack builds an instrument and a question. It closes no defect class, so it claims no member closed. The one row-shaped item:

| Item | Status | Evidence |
|---|---|---|
| the unchecked per-step identity in `ledger_trend.py` (unfiled candidate) | **CLOSED by Task 1** | the two-lane fixture test, red before the fix |

## Pass criteria

- Task 0's two back-tests are recorded in the Landing stanza with W, D and the chosen key, set before reading. If either refuting result held, the pack stopped and the record says so.
- `python scripts/ledger_trend.py --ref origin/main --since 2026-10-04` prints no failed identity, and its window lines are unchanged in value from the pre-fix run.
- `python scripts/ledger_trend.py --ref origin/main --by-surface` separates the guard surface from the rest over 2026-10-04..2026-10-07 under the chosen key.
- `tools/cc/ledger_row.py file --dry-run` on a fixture whose surface fires prints the advisory and exits 0.
- No assertion in the ledger tool tests may be weakened to make room. The flow tests must each have been seen red against the named mutation.
- `python scripts/sync_vendor_cc.py --check` and `python scripts/sync_claude_mirrors.py --check` are clean (if the scripts take no `--check`, run them and confirm the tree is clean).
- The tier `python scripts/proof_tier.py --base origin/main` prints, run in batches as the lane conventions say.

## Files touched

- **New:**
  - `tools/cc/_ledger_flow.py` (and its vendored mirror via the sync);
  - `memory/check-the-layer-before-the-class.md`;
  - a test file for the flow core (the name follows `tests/` conventions).
- **Modified:**
  - `scripts/ledger_trend.py`;
  - `tools/cc/ledger_row.py` (and its mirror);
  - root `CLAUDE.md` (Core Rule 12);
  - `docs/STANDING_PRINCIPLES.md` (and its aliases and index pins if a §20);
  - `.claude/agents/failure-mode-reviewer.md` and `.claude/agents/code-reviewer.md` (and their mirrors);
  - `CHANGELOG.md`.
- **Unmodified on purpose:** `task-packs/FORWARD_LEDGER.md`'s grammar and `tools/cc/generate_ledger_regions.py` (read, not changed).

## Sub-task ordering

1. Task 0 (0-A, 0-B; checkpoint: the two back-tests written down; stop if refuted).
2. Task 1-A (checkpoint: the fixture test red, then green; the real run's identity clean).
3. Task 2-A, which depends on Task 0's key (checkpoint: the fixture separation test).
4. Task 3-A, which depends on Task 2-A's core (checkpoint: the dry-run advisory test).
5. Task 4-A, which depends on 0-B (checkpoint: the mirrors clean, the doc contracts green).
6. Task 5, red-team: both reviewers. Ask for the surface key's blind spot, the case where the advisory never fires, and the advisory that fires on every filing.
7. Task 6: proof tier, landing stanza, ledger strike of the pack's §3 row.

## Estimated effort

| Task | Budget |
|---|---|
| 0 | 1.5 h |
| 1 | 1 h |
| 2 | 2 h |
| 3 | 1.5 h |
| 4 | 1 h |
| Red-team | 1 h |
| Verify and land | 1 h |
| **Total** | **about 9 h**, one lane |

**Most likely to be wrong:**
- the surface key (row text may not carry a stable path family);
- W and D (the history is two weeks long);
- whether `file_row` can afford the history walk.

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
