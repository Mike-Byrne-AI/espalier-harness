# TP-462 — Ship the forward ledger to adopters as a working system, seeded with their onboarding

## Status

- Version target: next beta (no release dependency; lands behind nothing)
- Change type: feature (adopter surface) + relocation
- **Kind: PACK**
- Ledger row: `DEF-978` (§C0, `minor` / LOGIC_BUG / ADOPTER; its probe reads False
  until the seed asset `espalier/assets/seed/FORWARD_LEDGER.md` exists). The pack is
  the operator's 2026-09-30 decision, recorded in the blueprint chain (session
  `20260930-051346-2a3840`); file a `DEC-` row only if a fork below is re-raised and
  decided differently.
- Sibling lane: the GOAL default-on lane (2026-09-30, same session) must land
  FIRST -- onboarding row `ONB-1` probes the `cc/GOAL.md` skeleton that lane seeds.

---

## Motivation

The first Windows adopter install (2026-09-29, a small Python repository) went
cleanly, and the operator noticed the ledger was
not there. It never is: `espalier/managed_inventory.py::_SEED_DOC_REL_PATHS` seeds
`task-packs/CLAUDE.md` and no ledger, and every ledger verb lives in `scripts/`,
which `init` does not deploy. The deployed review workflows already grep
`task-packs/FORWARD_LEDGER.md` "if the repository keeps one", so on every adopter
tree their dedup step reads nothing.

The operator's reason for shipping it (2026-09-30): the ledger has grown past
finding-tracking -- it categorises by population, audience and severity, carries a
driven probe per row, is the dedup surface every review workflow reads, and fits
the sibling-site discipline. Decided, not to be re-argued here:

1. The verbs move into `tools/cc/` as their ONE home (no copy; the grammar's own
   docstring forbids a second home -- `scripts/generate_ledger_regions.py` module
   docstring).
2. `ledger_row`'s dependency on `scripts/check_pack_landing.py` shrinks to the
   helpers it uses, extracted into a small shared module.
3. The seeded sections are the adopter's **onboarding** -- Initialise / Test /
   Adapt -- as live `OPERATOR_ACTION` rows (the operator's idea). Closed rows stay
   in place and serve as `--after` anchors; a verb to create a new class is still
   needed for real defect classes.
4. The size floors apply to the self-host ledger only; an empty probe roster on an
   adopter tree passes with a note.
5. The adopter's ledger is TRACKED: `init`'s ignore rule for `task-packs/` becomes
   contents-only with re-includes for the ledger, its probes file and `CLAUDE.md`.
6. `ledger_row` creates a missing probes file instead of crashing.
7. A completeness `check` verb follows in a second pack (Scope (out)).

**What was measured before authoring** (2026-09-30, by a read-only survey
sub-agent driving copies in a scratch tree -- a self-report, so Task 0 re-derives
every line of it before anything is built):

- The core closure is four stdlib-only scripts with no `espalier` import:
  `scripts/ledger_row.py`, `scripts/generate_ledger_regions.py` (the grammar),
  `scripts/check_ledger_probes.py`, `scripts/check_pack_landing.py`. Derive:
  `grep -nE '^(from|import) |_load\(' scripts/ledger_row.py scripts/generate_ledger_regions.py scripts/check_ledger_probes.py scripts/check_pack_landing.py`.
- On an EMPTY skeleton the verbs cannot operate. Five blockers:
  (a) the generator's `--check` refuses below its snapshot floors
  (`_FLOOR_SECTIONS`, `_FLOOR_ROWS`); (b) `check_ledger_probes.py` exits 1 on an
  empty roster ("zero probes is indistinguishable from zero strikes"); (c) `file`
  requires `--after` to name an existing row in the target section, and no verb
  creates a section; (d) a missing probes file raises an uncaught
  `FileNotFoundError` in `ledger_row._load_probes`; (e) every script resolves the
  root as its own `parents[1]`, which is `tools/` once relocated.
- With ONE struck anchor row in a section, the round trip worked end to end:
  `file` -> probe driven STILL_OPEN -> `strike` -> probe retired.
- `init` writes `/task-packs/` into the adopter's `.gitignore`
  (`espalier/cli.py::REQUIRED_GITIGNORE`), so a seeded ledger would be untracked.
  `espalier/cli.py::_gitignore_key` records why appending a negation beneath
  `/task-packs/` is inert (a git rule: nothing under an excluded directory can be
  re-included).
- `python3` spellings in probe commands already work on a `python`-only host:
  `check_ledger_probes.py` rewrites a bare `python`/`python3` to the running
  interpreter.

**Why now:** the GOAL lane made one invisible-until-you-know feature default-on;
the ledger is the larger instance of the same shape, and the onboarding seed turns
the other features an adopter must discover (GOAL, the repository-category
override, `plan_exempt_prefixes`, the test command) into rows they meet on day one.

---

## Scope (in)

1. **Make the verbs work on an empty, non-self-host ledger -- in place, before any
   move** (the smallest concrete change; testable on synthetic trees):
   1-A root resolution by flag and by walk, not by script position;
   1-B floors declared by the ledger that wants them;
   1-C an empty roster over a ledger with no probed live row passes with a note;
   1-D `class` verb (create a section) and `file` into an empty section;
   1-E a missing probes file is created;
   1-F extract `ledger_row`'s pack-scope helpers into one shared module.
2. **Relocate** the three verb scripts plus the extracted module into `tools/cc/`;
   repoint every caller; `check_pack_landing.py` and the maintainer-only ledger
   scripts stay in `scripts/` and load from `tools/cc/` by path.
3. **Deploy + seed**: the moved scripts join the deployed tool set; a seed ledger
   (skeleton + onboarding sections) and its probes are created on `init`; the
   `task-packs/` ignore rule becomes contents-only with re-includes, rewritten in
   place inside init's own block on an existing tree.
4. **The onboarding rows** (the operator's design): Initialise / Test / Adapt, each
   row probe-backed or carrying a declared no-probe reason.
5. **Hedge sweep**: every deployed body that says "if the repository keeps one"
   about the ledger, or names `scripts/<ledger verb>`, is revisited -- the list is
   derived by command in Implementation 5, never typed here.
6. **Red-team**, then the full tier plus a driven fresh `init` on a throwaway repo.

---

## Scope (out)

- **The completeness `check` verb** ("every live row probed or declared", the
  portable half of `tests/test_forward_ledger_completeness.py`): its own pack
  (decision 7). Until it lands an adopter's ledger has the verbs and the probes but
  no completeness gate -- stated in the seed's header so no one reads it as gated.
- **`ledger_trend.py`, `ledger_structural_cut.py`, `ledger_rebuild_assemble.py`**:
  maintainer-only tools with no role in file/strike/repin/probe (measured by the
  survey; re-derive in Task 0). They stay in `scripts/`.
- **Porting the self-host ledger CONTENT contracts** (`tests/test_forward_ledger_completeness.py`'s
  live-roster classes, `tests/test_maintenance_mode.py::TestBypassRosterCarriers`,
  `TestMemoryCapPopulation`): they pin THIS repository's rows; an adopter has none
  of them. The synthetic-tree classes in those files move with the scripts.
- **Surfacing the adopter ledger in SessionStart** (an `Owed:` line from live
  `OPERATOR_ACTION` rows): attractive, and a hook change; a follow-up once an
  adopter has used the seed.
- **The `/handoff` owed-probe machinery** (`scripts/check_handoff_landing.py`):
  self-host; only its path to the moved scripts changes.

---

## Task 0 — Verify (may end the pack)

**Oracle 0-A (the closure and the blockers are as stated).** In a `git archive
HEAD` extract under a temp root (never the live tree -- `CLAUDE.md` Core Rule 14),
build a fake repo holding only the four scripts, a skeleton
`task-packs/FORWARD_LEDGER.md` (the minimum the survey found: headline line,
adopter line, the `## §2` header with its population and audience tables, one
`### §C1` section) and no probes file. Drive, in order:
`python scripts/generate_ledger_regions.py --check`,
`python scripts/check_ledger_probes.py`,
`python scripts/ledger_row.py file ONB-1 --section C1 --after X ...`.
Expected: the five blockers reproduce. Record each output verbatim in Landing.

**Oracle 0-B (the vocabulary is portable).** `generate_ledger_regions.POPULATIONS`
and `AUDIENCES` are fixed tuples, and the headline regex names "logic bugs ·
hygiene · operator actions" and "reach an adopter". Decide, by reading every
consumer of those tuples (`grep -n 'AUDIENCES\|POPULATIONS\|_HEADLINE' scripts/*.py tests/*.py`),
whether an adopter can use the SAME tokens with a seeded legend ("ADOPTER = a
person who uses what this repository ships; MAINTAINER = you; OPERATOR = whoever
runs it") without a grammar change.

**Refuting results -- do not build; stop and re-raise:**

- 0-B finds the vocabulary cannot be read in an adopter's context without forking
  the grammar (two grammars is the thing decision 1 forbids).
- 0-A finds a blocker the survey did not name that needs a verb redesign rather
  than a guard (e.g. the probe runner's `git` tree-walk assumes the self-host
  layout), AND fixing it would change the self-host ledger's behaviour.
- The relocation's caller census (Implementation 2's command) returns a caller
  that cannot load from `tools/cc/` without an `espalier` import.

**Exit on a refuting result:** stop, write the measurement into this pack's
Landing as `State: DRAFT (re-raised)`, and bring it to the operator. Do not adjust
the plan and continue -- the approval was given against the survey's picture.

---

## Relevant memory

Recent pattern: the last two adopter lanes (PR #46, the GOAL lane) each met a
pinned roster the change had to move -- a hand-kept list mirroring a canon, a
derived region in README/QUICKSTART, a liveness test on a marker list -- and every
one surfaced only when its test ran. This pack moves four scripts and adds a
deployed file set; expect more of the same, and run the enumerator pins early.

| Entry | Where |
|---|---|
| The ledger verbs are unlocked read-modify-writes -- never run two in parallel tool calls | `docs/SHARP_EDGES.md` (that heading) |
| `classify_release_path` local-only ≠ git-ignored | `docs/SHARP_EDGES.md` (that heading) |
| A path in the seed list is not the content an adopter receives | `docs/SHARP_EDGES.md` (that heading) |
| Advisory reinject rules need the same self-host gate as observers | `docs/SHARP_EDGES.md` (that heading) |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| Git artifact hygiene | `memory/git-artifact-hygiene.md` |

Plus the folder rule that bites a relocation hardest, from `tools/cc/CLAUDE.md`: a
script copied without its sibling dependencies crashes silently in its subprocess
-- the ledger scripts load siblings by file path, so every fixture and deploy list
that copies a subset must grow with them.

Resolved at authoring time by `python tools/cc/hooks/_recall.py "<topic>"` over
"forward ledger verbs probes grammar", "new script in tools/cc deployed vendored
mirror", "task-packs gitignore tracked adopter", "self-host only path deployed to
adopter hedge". Re-run rather than trusting this list if the pack has been sitting.

---

## Implementation

Every fix below is a **fix shape (untested)** unless marked otherwise.

### 1-A Root resolution

`_ROOT = _HERE.parents[1]` (and its siblings in the other three scripts) is correct
only while the script sits one level under the root. Shape: one helper, used by all
four, resolving in order `--root` (the flag `ledger_row` already has) -> the
nearest ancestor of the CWD holding `task-packs/FORWARD_LEDGER.md` -> the git
top-level -> the script-relative fallback. The generator's and checker's `main()`
gain `--root`. *Refuted if* a probe's relative `subject`/`inputs` paths resolve
against a different root than the verbs write to -- drive one probe with an
`inputs` path from a subdirectory CWD.

### 1-B Floors declared by the ledger

Do not sniff for self-host in a `tools/cc/` script. Shape: the floors move into the
ledger that wants them, as one machine-read line
(`<!-- ledger-floors: sections=N rows=M -->`); the generator enforces a floor only
when the line is present. The self-host ledger gains the line carrying today's
`_FLOOR_SECTIONS` / `_FLOOR_ROWS` values; the seed carries none. *Refuted if*
`tests/test_generate_ledger_regions.py`'s floor tests need the floor without a
ledger file (they then read it from a fixture ledger instead -- strengthen, never
drop them).

### 1-C The empty roster

The refusal exists because a LOST probes file reads as "nothing to strike". Keep
that: refuse when the ledger has live rows carrying a probe id and the roster is
empty; pass with `NOTE: no probes -- no live row declares one` when it has none.
*Refuted if* the probes file does not record which rows are probed independently
of the ledger (then the distinction must read the ledger's rows).

### 1-D `class` and `file` into an empty section

Shape: `ledger_row.py class C<n> --title "..." --population P --audience A`
appends a `### §C<n>` section and its class-index row; `file` without `--after`
into a section with no member rows places the row first. The onboarding sections
are seeded with live rows, so 1-D is what an adopter's FIRST real defect class
needs. *Refuted if* the grammar's section parser requires a member row per section
to converge (then `class` must write a struck placeholder, and the pack says so).

### 1-E Missing probes file

Create it in `ledger_row._load_probes`'s caller with the empty shape the checker
accepts (read the checker's loader for the exact keys; do not type them here).

### 1-F Extract the pack-scope helpers

`ledger_row` calls four `check_pack_landing` helpers for the strike-time Scope (out)
refusal (survey: `pack_files`, `active_pack_dirs`, `blank_fences`,
`scope_out_spans`). Derive the real set:
`grep -n '_CPL\.' scripts/ledger_row.py`. Move exactly that set into
`tools/cc/_pack_scope.py`; `check_pack_landing.py` imports it by path. The Done/
Scrapped/Deferred/Merged folder names travel with it -- on an adopter tree they
may not exist, and an absent folder must read as "no packs there", never as an
error.

### 2 Relocate

`git mv` the three verb scripts into `tools/cc/`. Caller census -- derive, do not
trust any list: `grep -rn 'ledger_row\|generate_ledger_regions\|check_ledger_probes\|check_pack_landing' --include=*.py --include=*.sh --include=*.md --include=*.json . | grep -v '^./task-packs/FORWARD_LEDGER.md'`.
Known today (re-derive): `scripts/check_handoff_landing.py`,
`scripts/run_pack_chain.sh`, the text in `tools/cc/hooks/_reinject.py`, the four
test files, `tests/_surface_expected.py::EXPECTED_SCRIPT_NAMES`. After the move:
`python scripts/sync_vendor_cc.py`; the portability contract
(`tests/test_portability_contract.py`) now covers these files, so their `python3`
docstring spellings follow the repository's cross-platform rule.

### 3 Deploy and seed

- Deployed tool set: `espalier/managed_paths.py::STANDARD_MANAGED_TOOLS` gains the
  moved files; `INIT_TOOL_SCRIPTS`' exact pin in `tests/test_managed_inventory.py`,
  `tests/test_lifecycle_parity.py` and the README/QUICKSTART deploy-inventory region
  (`python scripts/generate_doc_regions.py`) move with it.
  `tests/test_deploy_set_import_closure.py` probably cannot see a load by file path
  (survey, probable) -- check, and if so make it see one rather than excuse it.
- Seed ledger: `espalier/assets/seed/FORWARD_LEDGER.md` via
  `_SEED_ASSET_SOURCES` (the `memory/CONVERGENCE_LEDGER.md` precedent), holding the
  skeleton, the legend from Task 0-B, the onboarding sections, a `§6
  do-not-rediscover` section (the review workflows read it), Appendix B, and a
  header saying no completeness gate ships yet.
- **Fork -- how the probes file is born.** Its rows carry `row_sha`/`text_sha` pins
  computed by `check_ledger_probes`' own functions, and `espalier/` may not import
  `tools/cc/`. Recommended: `init` seeds the ledger markdown only, then runs the
  DEPLOYED `tools/cc/ledger_row.py` once per onboarding row (a `seed` sub-verb, or
  `repin`) so the pins come from the one hashing home and every onboarding probe
  is driven on the adopter's own tree at install. Alternative: seed a static JSON
  and accept a second hashing home -- rejected by decision 1's reasoning. The seed
  stamp (an HTML-comment first line) cannot go in a JSON file either way.
- Gitignore: `"/task-packs/"` in `REQUIRED_GITIGNORE` becomes `"/task-packs/*"`
  plus re-includes for `FORWARD_LEDGER.md`, `LEDGER_PROBES.json` and `CLAUDE.md`.
  On an existing tree the old line must be REWRITTEN inside init's own block
  (`GITIGNORE_BLOCK_HEADER`/`GITIGNORE_BLOCK_FOOTER`), because a negation appended
  below `/task-packs/` is inert. Oracle: `git check-ignore -v task-packs/FORWARD_LEDGER.md`
  and `git check-ignore -v task-packs/TP-1-x.md` on (i) a fresh init and (ii) a
  tree initialised at HEAD then re-initialised -- the ledger must be not-ignored and
  the pack draft ignored in both.

### 4 The onboarding rows

Population `OPERATOR_ACTION`, audience `MAINTAINER`, severity `minor`, id prefix
`ONB-` (the grammar's id shape accepts it -- survey; re-derive against
`generate_ledger_regions._ID_SHAPE`). Candidate rows -- the probe column is a
proposal, each one driven on a fresh init in Task 6 before it ships:

| Id | Section | Row | Check |
|---|---|---|---|
| `ONB-1` | Initialise | Set the goal in `cc/GOAL.md` | probe: open while `espalier.toml` does not set `goal_snapshot = false` AND the file is absent or still carries the skeleton's "(not set" placeholder; closed once the goal is written or the key opts out. It reads the KEY, never the file's absence alone -- an absent file can also mean deleted or pre-seed (2026-09-30 review). |
| `ONB-2` | Initialise | Confirm the hooks are armed (`espalier doctor .` reads pass) | declared: `doctor` is an engine command and an adopter may run it through `pipx`; the row says which command to run |
| `ONB-3` | Test | Confirm the detected test command (`reports/repo_fingerprint.json::test_commands`), or declare one in `espalier.toml` `[extra_actions]` | probe: `test_commands` empty and no `[extra_actions]` test -> open |
| `ONB-4` | Test | Run `/preflight` once and record that it ran the repository's own gate | declared: a run, not a file state |
| `ONB-5` | Adapt | Confirm the repository category `init` chose (`reports/harness_config.json::profiles`); correct it with `preferred_profiles` / `suppress_profiles` -- the category comes from presence heuristics and substring matches in `espalier/profiles.py::classify_repo` and `espalier/analyze.py`, so a folder of scripts reads as a library | declared: "right" is a judgement; the row closes when the operator says so |
| `ONB-6` | Adapt | Decide `plan_exempt_prefixes` for your source roots | probe: the key is absent from `espalier.toml` -> open |
| `ONB-7` | Adapt | Replace the `docs/CONVENTIONS.md` and `docs/SHARP_EDGES.md` stubs with this repository's patterns and footguns | probe: either file's seed stamp line is still its first line (untouched) -> open |

A closed onboarding row stays in its section (struck), which is what gives each
section an `--after` anchor for the adopter's later rows.

### 5 Hedge sweep

Derive the list; do not type it: `grep -rnE "if the repository keeps one|if one exists|if that file is absent|keeps no such ledger|scripts/(ledger_row|check_ledger_probes|generate_ledger_regions)" .claude/ espalier/assets/seed/ docs/PACK_AUTHORING.md docs/FAILURE_MODES.md tools/cc/`.
The survey's list (verify, then discard): `.claude/workflows/_layered_review.js`,
`.claude/workflows/_convergence_review_template.js`, `.claude/commands/preflight.md`,
`.claude/commands/implement-pack.md`, `.claude/skills/blueprint-authoring/SKILL.md`,
`docs/PACK_AUTHORING.md`, `docs/FAILURE_MODES.md`,
`espalier/assets/seed/convergence-review-protocol.md`, `tools/cc/hooks/_reinject.py`.
A hedge stays where the reader may have opted out or deleted the ledger; it goes
where it only ever meant "you are not the Espalier source repo". Then
`python scripts/sync_claude_mirrors.py`, `python scripts/sync_asset_docs.py`,
`python scripts/sync_vendor_cc.py`; `tests/test_adopter_pointer_resolution.py`
reds any stale "self-host only" note on a now-deployed path (its `_false_notes`).

---

## Affected symbols

### Changed-semantics
- `scripts/check_pack_landing.py` (loads the extracted helpers from `tools/cc/`)
- `espalier/cli.py::REQUIRED_GITIGNORE` (contents-only task-packs rule with re-includes)
- `espalier/cli.py::_handle_gitignore` (rewrites the old task-packs line inside its own block)
- `espalier/managed_paths.py::STANDARD_MANAGED_TOOLS`
- `espalier/managed_inventory.py::_SEED_DOC_REL_PATHS`
- `espalier/managed_inventory.py::_SEED_ASSET_SOURCES`
- `espalier/cli.py::deploy_harness` (seeds the ledger, drives the onboarding probes)

### Renamed
Each moves AND changes behaviour (whole-file entries: a `::main` bullet matched
every `main()` in the tree and buried the walk in noise):
- `scripts/ledger_row.py` -> `tools/cc/ledger_row.py` (`class` verb; `file` without `--after`; creates a missing probes file; `--root` resolution)
- `scripts/generate_ledger_regions.py` -> `tools/cc/generate_ledger_regions.py` (`--root`; floors read from the ledger's own line)
- `scripts/check_ledger_probes.py` -> `tools/cc/check_ledger_probes.py` (`--root`; the empty-roster rule)

### Added-paths
- `tools/cc/_pack_scope.py`
- `espalier/assets/seed/FORWARD_LEDGER.md`

### Removed-paths
- (none -- the three scripts are renamed, not removed)

---

## Reach

Not a class-closing pack: it ports a subsystem and fixes five named blockers
(Task 0-A reproduces them). Each blocker's close is its own pass criterion below.

---

## Pass criteria

1. On a fresh `init` of a throwaway git repo (the driver lives in the RUNBOOK):
   `task-packs/FORWARD_LEDGER.md` exists, is NOT git-ignored, and
   `python tools/cc/check_ledger_probes.py` exits 0 reporting the onboarding probes
   (each STILL_OPEN on a fresh tree except those the tree already satisfies).
2. On the same tree: `ledger_row.py class`, then `file` into the new empty class,
   then `strike` round-trips with `generate_ledger_regions.py --check` green after
   each verb. Closing `ONB-1` by filling `cc/GOAL.md` flips its probe.
3. A tree initialised at HEAD and re-initialised after this pack: the ledger is
   not ignored, a `task-packs/TP-*.md` draft still is.
4. The self-host ledger's behaviour is unchanged: `generate_ledger_regions.py
   --check` and `check_ledger_probes.py` on this repository report the same
   verdicts before and after (record both), floors enforced via the new line.
5. No assertion is weakened and no test deleted to clear a red; a synthetic-tree
   test that moves with a script keeps every case it had.
6. Every new behaviour (1-A..1-F, the seed, the gitignore rewrite) has a test that
   was RED against HEAD, recorded in Landing with the mutation it died to.
7. Full tier green against this host's recorded baseline; `/preflight` GO.

---

## Files touched

- Moved: the three verb scripts (see Renamed).
- New: `tools/cc/_pack_scope.py`, `espalier/assets/seed/FORWARD_LEDGER.md`, and
  their vendored/asset mirrors via the sync scripts.
- Modified: `scripts/check_pack_landing.py`, `scripts/check_handoff_landing.py`,
  `scripts/run_pack_chain.sh`, `tools/cc/hooks/_reinject.py`, `espalier/cli.py`,
  `espalier/managed_paths.py`, `espalier/managed_inventory.py`, the bodies Implementation 5
  derives, the four ledger test files, `tests/_surface_expected.py`,
  `tests/test_managed_inventory.py`, `tests/test_lifecycle_parity.py`,
  `tests/test_init_gitignore_default.py`, README.md / docs/QUICKSTART.md (generated regions),
  `task-packs/FORWARD_LEDGER.md` (the floors line only).
- Unmodified on purpose: `scripts/ledger_trend.py`, `scripts/ledger_structural_cut.py`,
  `scripts/ledger_rebuild_assemble.py` beyond their load path.

---

## Sub-task ordering

1. **Task 0** -- 0-A, 0-B. Checkpoint: the five blockers reproduced; vocabulary verdict written. May end the pack.
2. **1-E** missing probes file (smallest). Checkpoint: `pytest tests/test_ledger_row.py -q`.
3. **1-A, 1-B, 1-C** in `scripts/`. Checkpoint: the three ledger test files; self-host `--check` unchanged.
4. **1-D, 1-F**. Checkpoint: an empty-skeleton synthetic tree round-trips class -> file -> strike.
5. **2** relocate + callers + mirrors. Checkpoint: enumerator pins (`tests/test_test_suite_contract.py tests/test_marker_taxonomy.py tests/test_portability_contract.py`) + `tests/test_vendor_cc_parity.py`.
6. **3** deploy, seed, gitignore (depends on 5). Checkpoint: pass criteria 1 and 3 driven.
7. **4** onboarding rows, each probe driven on a fresh init (depends on 6). Checkpoint: pass criterion 2.
8. **5** hedge sweep + syncs. Checkpoint: `tests/test_adopter_pointer_resolution.py`, mirror parity.
9. **Red-team**: `code-reviewer` + `failure-mode-reviewer` in one message, edits frozen. Most likely to be wrong, for the reviewers to bite on: the gitignore rewrite on a tree whose operator hand-edited the block; the empty-roster rule reading a lost probes file as clean; an onboarding probe that is open forever on a legitimate tree (e.g. a repository with no tests).
10. **Full tier** once, after the fix batch; `/preflight`.

---

## Estimated effort

Task 0: 45 min. 1-A..1-F: 3 h. Relocation: 2 h (the pins). Deploy/seed/gitignore:
2.5 h. Onboarding rows: 1.5 h. Hedge sweep: 1 h. Red-team + fix batch: 1.5 h. Full
tier + preflight: 45 min on this host. **Total ~13 h, two to three sessions.**

---

## Landing
- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach: n/a (not a class pack)
- Date:
