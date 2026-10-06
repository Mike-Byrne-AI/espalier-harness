# TP-469 — Stack registry: one table of what each stack is, read by every list that spells one

## Status

- Version target: unscheduled (after `0.8.0b2`).
- Change type: refactor with behaviour changes. The pieces:
  - one new stdlib data module in `tools/cc/`, importable by every hook, and its byte copy in
    the engine (a new mirror row);
  - engine inference: the package manager, read from `package.json` and the lockfile;
  - the derived hand lists in the hooks, the engine and the six scanner walk lists;
  - one new `espalier.toml` key;
  - tests, and the stack-axis cells of the adopter-axes registry.

  No shipped command or agent body changes under the decided answers: Decision 9's pin leaves
  `/preflight` as it is, and Decision 13 leaves the test-writer line. No workflow changes.
- **Kind: PACK.** Task 0 can end it, or end one lane of it (partial closure is a licensed
  outcome; see Reach).
- Gate: **decided 2026-10-06.** The operator answered all thirteen authoring questions; the
  answers are recorded under *Decisions*. Two of them (5 and 6) carry a condition that Task 0
  measures. The three sequential lanes are kept.
- Ledger: the unit of work for `DEF-976`. Fourth of the four detection-system packs (alarm,
  voice, axes, then **stack registry**; operator, 2026-09-30). Authored after the adopter-axes
  pack, as the row asks, and proven on the Node trees that pack's foundation lane built
  (`task-packs/TP-468-adopter-axes.md`, *Downstream consumers*).
- **Tree.** Authored 2026-10-06 on the Windows box, on `lane/stack-registry-pack`, first at
  `main` `5f0b6ae`. The Node-defaults lane (pull request #121, at `7987961`) was open while the
  pack was drafted, and it rewrites several of this row's sites. So the citations were read
  from a scratch worktree of that branch. #121 then merged (`80e575b`, which adds one
  `espalier/cli.py` fix after `7987961`), and the lane was fast-forwarded onto it before this
  pack was committed.
  - **Re-verified on `main` `80e575b`:** Appendix A prints identically to #121's head; drives 1
    to 6 reproduce their recorded results; every `### Changed-semantics` symbol resolves; the
    scope-check gap list and the fence check are unchanged.
  - Six of those symbols did not exist on the pre-merge `main` `5f0b6ae`, because #121 added
    them: `settings_profiles.PYTHON_ONLY_ALLOWS`, `::_SCRIPT_RUNNERS`,
    `::is_python_fingerprint`, `harness_config.render_agent_tools`,
    `config._check_knob_values` and
    `tests/test_forced_copy_parity.py::TestFingerprintLanguagesAreHookSource`.
  - Task 0-A re-runs the same checks at execution.
- Authoring review: one `code-reviewer` pass with `tools/cc/pack_artifact_checklist.md`,
  against #121's tree, before the pack was committed. It re-ran Appendix A and drives 1, 2, 4
  and 5, and they reproduced. Its verdict was REQUEST CHANGES (3 BLOCK, 8 WARN, 7 NIT), and
  all of it is folded in:
  - three proofs that could not red their defect: a ratchet blind to a name deleted from the
    table, a manifest mutation read through the wrong fingerprint field, and an import
    fallback that `verify_pins` would read as empty;
  - the probe-witness contradiction;
  - fields the later tasks read;
  - the tenth mirror row's fourth obligation.

  Execution's own 0-A still runs.
- Host: Windows 11, Python 3.11.9 answering as `python` (no `python3`), main checkout under a
  spaced path. Commands below spell `python`; substitute `python3` where that is the name
  that answers. This box is short on memory: no step here assumes `-n auto`.
- **Execution, lane A** (2026-10-06, on `lane/stack-registry-package-manager` from `main`
  `cbc0a16`; the commits after `80e575b` touch only this pack, the ledger, its probes file and
  the memory file, so Appendix A printed identically and no citation moved):
  - Task 0 built on every leg; the verdicts are in `reports/tp469/TASK0_VERDICTS.txt` and
    summarised in Landing.
  - Execution's 0-A `code-reviewer` (checklist v2) returned REQUEST CHANGES: 2 BLOCK, 8 WARN,
    3 NIT. The two BLOCKs were full-suite obligations no sub-task named: five for the tenth
    mirror row and the deploy roster, four for the new fingerprint field. They are pack defects,
    not a refutation, so they are folded in below (`memory/fix-the-pack-and-proceed-on-a-pre-flight-defect.md`).
    Each folded line says "(execution 0-A)".
  - `DEF-976` was re-pinned before the first code edit, to the defect-site count (2-B's
    re-pin note).

## Motivation

`DEF-976`: "Language and stack knowledge is hand-written in more than twenty places that
disagree, no lockfile is read anywhere so the package manager is always npm, and an adopter
cannot tell the harness that `.astro` is source."

#121 closed four of the row's sites (below). What it left is the row's core: **no production
file reads a lockfile or `packageManager`**, and the dependency-directory, manifest and
command knowledge is still spelled by hand in the places the row named.

### What #121 closed, and what is left of the row

| Row clause (2026-09-30) | State on #121's tree | Status |
|---|---|---|
| four source-extension lists, three disagreeing pairs | Two literals remain, `tools/cc/hooks/_hook_utils.py::SOURCE_LANGUAGE_EXTENSIONS` (24) and `espalier/analyze.py::SUFFIX_TO_LANGUAGE` (21). `::WEB_SUFFIXES` is derived from the map (the `_web_exts` local is gone). The two are pinned subset-wise by `tests/test_forced_copy_parity.py::TestFingerprintLanguagesAreHookSource`; the one remaining difference is deliberate and documented (`.h`, `.scala`, `.swift` are hook source and not fingerprint languages). The `*.md` pathspec in `tools/cc/hooks/subagent_stop.py::_changed_markdown` now reads `*.md` and `*.mdx` | **closed by `DEF-961`** for the disagreement; the lists are still hand-written twins (verified: Appendix A line 2) |
| an adopter cannot say `.astro` is source | `.astro`, `.vue`, `.svelte`, `.mjs`, `.cjs`, `.mts`, `.cts` are shipped source, and the additive flat key `source_extensions` is read by `_hook_utils.source_extensions` | **closed by `DEF-961`** (verified: read on #121's tree) |
| `/preflight` ladders consult PATH before the fingerprint | Step 1 and Step 2 run `espalier.harness_config.preflight_command` first (`[extra_actions]`, then the fingerprint's inference); the PATH probes run only when nothing is declared, each guarded by a project file | **closed by `DEF-962`**. What is left: the fallback ladder is a four-stack table written in bash (Python, Node, Go, Rust guards and commands) |
| five Python permission rules to every repo in two profiles | `espalier/settings_profiles.py::PYTHON_ONLY_ALLOWS` renders only for a fingerprint that lists Python; `::narrowed_rules` derives no bare `Bash(<binary> *)` | **closed by `DEF-965`** (DEC-37 branch (a)) |
| `Bash(pytest *)` in `.claude/agents/test-writer.md` | Unchanged in the shipped body. The deploy appends the fingerprint's runner, so on a Node fingerprint the line reads `... Bash(pytest *), Bash(python *), Bash(git *), Bash(npm test), Bash(npm test *)` | **open** (verified: Appendix B drive 5) |
| command inference spells `npm`, never reads `pnpm-lock.yaml`, `yarn.lock`, `bun.lockb` | Zero lockfile or `packageManager` string constants in `espalier/`, `tools/cc/` or `scripts/`. Driven on six Node trees (no lockfile, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lockb`, `bun.lock`): every one infers `npm test`, `npm run lint`, `npm run build`, `/preflight` runs `npm test`, and the workflow profile derives only `Bash(npm …)` rules | **open** (verified: Appendix A line 4, Appendix B drive 1; the row's probe prints `npm` on `main` and on #121) |
| sixteen dependency-directory lists in eleven variants, fifteen lacking a `DEPENDENCY_TREE_DIRS` name, the five scanner copies identical | Unchanged on both trees. The row's method reproduces exactly at the filing commit `2891d7a`: set and list displays only. Read with tuples too it is **20 lists, 15 variants, 19 lacking a name**. The five `DEFAULT_EXCLUDE` copies are identical; a sixth scanner list (`espalier/scanners/encoding_contracts.py::PRUNE_DIRS`) differs | **open, population widened** (verified: Appendix A line 1, calibrated against the filing commit) |
| a Rust adopter's `target/` walked by thirteen of sixteen walkers | 13 of 16 lists lack `target` (17 of 20 with tuples). That is list membership, not a measured walk; the drive below measures four walkers | **open, restated** (verified as membership) |
| two manifest lists of six and four names | Holds: `espalier/analyze.py::MANIFEST_NAMES` (6), `tools/cc/hooks/_hook_utils.py::PROJECT_MANIFEST_NAMES` (4). Three more literals name two or more manifests (`analyze._has_python_signals`, the foreign-manifest tuple in `analyze.detect_tests`, `tools/cc/hooks/plan_guard.py::PLAN_REQUIRED_ROOT_FILES`), and `analyze.detect_package_systems` spells seven in an `if` chain no literal census sees | **open, population widened** (verified: Appendix A line 3; the `if` chain read) |
| `espalier/models.py::HarnessConfig` has no stack key | `source_extensions` landed (flat, additive). No dependency-directory key; no package-manager key | **partly closed** |

Counts moved between the filing commit (`2891d7a`, 2026-09-30) and `main` (`5f0b6ae`): **none**
(Appendix A prints identically). Between `main` and #121: line 2 (3 literals to 2), line 5
(`settings_profiles` gained the four package-manager names in `_SCRIPT_RUNNERS`, and `npx` in
`_EXACT_ONLY_BINARIES`),
line 6 (`/preflight` gained one `node_modules` guard).

### Measured at authoring, beyond the row (on #121's head `7987961`, reproduced on `main` `80e575b`)

- **The dependency directories are read, not only unlisted.** One file planted under each of
  `node_modules`, `bower_components`, `jspm_packages`, `.yarn`, `.pnpm-store` and `target`, with
  a control file at `src/app.py`. Calibrated: every walker read the control and none read
  `node_modules`. The fingerprint walk read the four names `DEPENDENCY_TREE_DIRS` gained in the
  `DEF-942` lane; `repo_mode.list_repo_files_via_filesystem` and the `prints` scanner (whose
  `DEFAULT_EXCLUDE` the other four scanners share) read those four and `target`; the router
  walk (`espalier/reflect_protocol.py::_walk_router_docs`) read `bower_components`,
  `jspm_packages` and `target`. (verified: Appendix B drive 2)
- **Root manifests are plan-gated by accident of their extension.** `_explain_path.py` on a
  scratch tree: `requirements.txt` requires a plan (listed), `package.json`, `Cargo.lock`,
  `pnpm-lock.yaml`, `yarn.lock`, `bun.lock` and `package-lock.json` require one (their
  extension is in `plan_guard.PLAN_REQUIRED_ROOT_EXTENSIONS`), and `go.mod`, `go.sum`,
  `Gemfile` and `bun.lockb` are exempt ("root-level non-listed non-source file").
  (verified: Appendix B drive 3)
- **The row's declared scope-out of `scope_walker` hides a stack-blind gate.**
  `espalier/scope_walker.py::walk_references` on a tree where `parseRoute` is defined in
  `src/index.mjs`, used in `src/app.ts`, and named in `README.md` and `src/mod.py` returns
  `README.md` and `src/mod.py` only: `::INCLUDED_EXTS` has no JavaScript or TypeScript suffix,
  so `/scope-check` on a Node adopter's own pack never sees a reference in their source.
  (verified: Appendix B drive 4)
- **A `[stack]` table is invisible to both readers.** With `[stack]` holding
  `source_extensions` and `dependency_dirs`, `_hook_utils.read_toml_string_list` returns `None`
  on its `tomllib` arm and its regex arm, and `espalier.config.load_config` warns
  ``unknown key `stack` is ignored``. The same keys written flat at the top are read by both
  hook arms, and the engine reads `source_extensions` (and warns `dependency_dirs` unknown,
  as expected today). (verified: Appendix B drive 6)
- **Bun's test command is not `bun test`.** Bun's docs (`bun.sh/docs/cli/run`, fetched
  2026-10-06): "If a built-in `bun` command has the same name, the built-in command takes
  precedence; use the explicit `bun run <script>` to run your package script instead", and
  `bun test` is Bun's own runner. `bun.sh/docs/install/lockfile`: "Bun v1.2 changed the
  default lockfile format to the text-based `bun.lock`" (`bun.lockb` before). pnpm's docs:
  `pnpm test` "Runs an arbitrary command specified in the package's `test` property of its
  `scripts` object". So a uniform `<pm> test` template is refuted for one of the four
  package managers. (verified against the docs; not driven with the binaries)
- **The scanners' self-containment rule has no production copier.** The scanner docstrings
  and `tests/test_scanners.py::TestScannerSelfContainment` say scanners are "copied into target
  repos via inspect.getsource()". No production file calls `getsource(`; `espalier scan`
  imports the scanners in process (`espalier/cli.py`, the `scan` command's imports).
  (verified by grep; Decision 4 leaves the rule to its own question, candidate row 3)

**Who is hurt** (`docs/STANDING_PRINCIPLES.md` §16):

- The pnpm, yarn or bun adopter. `cc/COMMANDS.md`, the generated `CLAUDE.md` and `/preflight`
  name `npm`. The rendered `settings.json` pre-approves `Bash(npm test)` while the session's
  `pnpm test` prompts every time. On a bun-only machine `npm` may not exist at all. How often
  `npm test` fails outright on a pnpm workspace is **not measured**; the wrong rule set and the
  wrong guidance are.
- The Node adopter with a `bower_components/`, `jspm_packages/`, `.yarn/` or `.pnpm-store/` in
  the tree, and the Rust adopter with `target/`. Their fingerprint, `espalier scan` findings
  and router walk read third-party code as theirs.
- The Go or Ruby adopter whose root `go.mod` or `Gemfile` edit needs no plan while a Python
  adopter's `requirements.txt` does.
- The maintainer, who adds a stack by editing more than twenty lists and is told by no test
  which one was missed.

## Scope (in)

Each item maps to a task and to *Files touched*. The lane each belongs to is under
*Lane split*.

1. **1-A** The table: `tools/cc/_stack_table.py`, importing nothing but the standard
   library, one row per stack (source extensions with their language, manifests, lockfiles,
   package managers with their lockfiles and argv templates, dependency and output
   directories, a fallback lint, stack-only static allow rules, an AST-scannable flag). Its byte copy `espalier/_stack_table.py` under a new
   `espalier/mirror_registry.py` row, written by `scripts/sync_vendor_cc.py`.
2. **1-B** The hand-list ratchet, `tests/test_stack_table.py`: every production collection
   literal that spells stack vocabulary is a projection of the table or carries a
   `stack-table: ok purpose-scoped` marker, with a dated baseline that only falls.
3. **2-A** Package-manager resolution, `espalier/analyze.py::detect_package_manager`:
   `package.json` `packageManager`, then the one lockfile present, then `npm`; two or more
   lockfiles name themselves.
4. **2-B** Command inference from the table: `analyze.detect_tests`, `analyze.detect_actions`.
5. **2-C** Permission rules from the table: `settings_profiles._SCRIPT_RUNNERS` and
   `::PYTHON_ONLY_ALLOWS` become projections; the narrowing function stays the one owner
   (DEC-37's closure).
6. **2-D** The bun adopter row (`tests/_stack_trees.py`), the Node defaults test widened to
   `node-pnpm` and `node-bun`, and the registry's `stack/node_pnpm` and `stack/node_bun` cells
   proven.
7. **2-E** `/preflight`'s fallback ladder pinned against the table, not read at runtime
   (Decision 9).
8. **3-A** Source extensions and the language map derived (equality first, then the measured
   widening Decision 5 licenses).
9. **3-B** Manifests derived: `analyze.MANIFEST_NAMES`, `analyze.detect_package_systems`,
   `analyze._has_python_signals`, the foreign-manifest tuple in `analyze.detect_tests`,
   `_hook_utils.PROJECT_MANIFEST_NAMES`.
10. **3-C** Root manifests and lockfiles plan-gated (`plan_guard.PLAN_REQUIRED_ROOT_FILES`;
    Decision 8).
11. **3-D** One AST-scannable predicate for the four sites that spell `"python"` for it.
12. **3-E** `scope_walker.INCLUDED_EXTS` unions the table's source extensions (Decision 10,
    which reverses the row's scope-out).
13. **3-F** The `go` and `rust` stack cells proven (Decision 6, if 0-H's cost check passes).
14. **4-A** `DEPENDENCY_TREE_DIRS` derived; the adopter-content walkers derive their
    dependency half (`analyze.DEFAULT_SKIP_PARTS`, both `_WALK_SKIP_DIRS` in
    `reflect_protocol`, `repo_mode._WALK_SKIP_DIRS`, `sister_site_probe._ADOPTER_PRUNE_NAMES`).
15. **4-B** The six scanner walk lists pinned to the table (Decision 4).
16. **4-C** The flat `dependency_dirs` key: engine loader, validation twin, hook-side reader.
17. **4-D** `DEF-971` folded in (Decision 7).
18. **4-E** Markers on the purpose-scoped lists; the ratchet reaches zero.
19. **5-A** Red-team, per lane.

The paths these touch, for the scope walk:

- `tools/cc/_stack_table.py`, `tools/cc/hooks/_hook_utils.py`, `tools/cc/hooks/plan_guard.py`,
  `tools/cc/reflect_protocol.py`, `tools/cc/sister_site_probe.py`, and their copies under
  `espalier/_vendor/cc/` (by the sync script)
- `espalier/_stack_table.py`, `espalier/analyze.py`, `espalier/_safe_walk.py`,
  `espalier/reflect_protocol.py`, `espalier/repo_mode.py`, `espalier/settings_profiles.py`,
  `espalier/harness_config.py`, `espalier/cli.py`, `espalier/config.py`, `espalier/models.py`,
  `espalier/mirror_registry.py`, `espalier/managed_paths.py`, `espalier/scope_walker.py`,
  `espalier/doctor.py`
- `espalier/scanners/` (the six walk lists)
- `scripts/sync_vendor_cc.py`
- the tenth mirror row's obligations: `tools/cc/hooks/_reinject.py`, `CLAUDE.md`,
  `.claude/CLAUDE.md`, `tools/cc/CLAUDE.md`, `docs/SHARP_EDGES.md`,
  `scripts/sync_github_workflow_asset.py`, `scripts/derived_population_census.py`,
  `memory/asset-mirroring.md`
- readers of the derived constants that keep their names and are re-proven, not edited:
  `tools/cc/hooks/reflect_trigger.py`, `tools/cc/hooks/_explain_path.py`,
  `espalier/reflection.py`, `espalier/strengthen.py`, `scripts/verify_pins.py`
- `tests/` and `espalier/_vendor/selfcheck_tests/` (the second by `scripts/sync_selfcheck_tests.py`)
- `examples/espalier.toml`, `README.md`, `docs/QUICKSTART.md`, `CHANGELOG.md`, `docs/HOOKS.md`
- `task-packs/FORWARD_LEDGER.md`, `task-packs/LEDGER_PROBES.json`, `task-packs/TP-469-stack-registry.md`

## Scope (out)

Each reason below was checked at authoring; the check is named.

- **Stop Gate 1 arming from the table.** The row asks for it. Gate 1 is a pytest gate by design
  (`tools/cc/hooks/stop_gate.py::_parse_pytest_positional_args`: "Gate 1 is semantically a
  pytest gate"), and whether it runs a non-pytest command, and from which committed home, is
  the open fork `DEF-949` (step 4) records and `DEC-35` decides. This pack cannot pre-empt
  that decision. What it gives the fork: the table's commands are argv tuples, the shape
  `DEC-35`'s option (a) asks for, and the fingerprint's `test_commands` name the right package
  manager after 2-B. Checked: both rows read on #121's tree; `DEF-948` (the spawn path such a
  command would use) is closed since 2026-09-30.
- **The agent roster and the scanners stay Python-flavoured; non-Python scanners are a
  separate investigation.** The row says so. Checked: every scanner is an `ast` walker of
  Python source; `espalier/cli.py` already tells a non-Python adopter so at `init` and at
  `scan`. 3-D only unifies the predicate those notices read.
- **Five of the six purpose-scoped suffix sets the row declares out.** Each read at authoring:
  - `espalier/proofs.py::TEXT_SUFFIXES`: gates which harness **control files** (`.claude`,
    `tools/cc`, `reports`) the placeholder scan reads as text. Not an adopter-source question.
  - `espalier/surface_impact.py::_PATH_SUFFIXES`: recognises a pack's `### Added-paths` token
    as a file. A token with a `/` is always a path, so `src/router.mjs` is read right; only a
    root-level `router.mjs` would read as a symbol. Purpose-scoped, with that narrow caveat
    recorded.
  - `espalier/scanners/filesystem_contracts.py::STRUCTURED_SUFFIXES`: data formats
    (`.json`, `.toml`, `.yaml`, `.yml`), not languages.
  - `espalier/managed_paths.py::DEPLOYED_SCRIPT_SUFFIXES`: what the harness deploys
    (`.py`, `.cmd`).
  - `tools/cc/hooks/write_guard.py::_LAUNCHER_SUFFIXES`: Windows launchers
    (`.exe`, `.cmd`, `.bat`, `.ps1`).
  - **Not out: `espalier/scope_walker.py::INCLUDED_EXTS`.** Its mechanism is purpose-scoped
    (a walk gate), but its purpose, finding references to a pack's symbols, is stack-shaped,
    and it was measured blind to `.mjs` and `.ts` (Motivation). Decision 10 brings it into
    scope, reversing the row's scope-out.
- **The `full` profile.** Python-broad by design (`Bash(python *)`, `Bash(pip *)`,
  `Bash(pytest *)`), opt-in, and DEC-37's closure left it unchanged. Checked: `_FULL` read.
- **Purpose-scoped dependency lists.** They keep their own lists, with the marker (4-E):
  - `tools/cc/hooks/_bash_patterns.py::SAFE_EPHEMERAL_DIRS`: what `rm -rf` may delete without
    a speed bump. That is a deletion-safety roster, not a prune list. Probable reason it must
    never derive from the table: yarn's modern layout keeps the project's own yarn release
    under `.yarn/releases/`, so a pruned name is not a deletable one.
  - `espalier/release_noise.py::TRANSIENT_DIRS`: the harness's own release archive.
  - `espalier/diffing.py::EPHEMERAL_ZONES`: drift-report noise.
  - `espalier/fuse.py::_NONGIT_SKIP_DIRS`: walks an espalier **source**, not an adopter tree.
  - `espalier/strengthen.py::_EXEMPT_PREFIXES`: root-anchored prefixes that deliberately leave
    package managers to the by-name prune (its comment says so).
  - `espalier/analyze.py::KNOWN_GENERATED`: a root-level "generated directory present" signal.
- **`scripts/`.** `scripts/check_pack_fences.py::_RESOLVE_SKIP` and
  `scripts/symbol_census.py::_SKIP_DIR_PARTS` run only on this repository and never ship. The
  ratchet scans `espalier/` and `tools/cc/` only, and says why.
- **Shell fences in agent bodies.** `.claude/agents/repo-analyst.md` hand-lists manifests and
  lockfiles (no `bun.lock`) and `node_modules` excludes in ten places (Appendix A line 6).
  Those are instructions an agent reads, not a gate. A parity check over markdown fences is
  its own question (candidate row).
- **Python package managers** (`uv.lock`, `poetry.lock`, `Pipfile.lock`). The row is about
  `npm`. Switching a Python adopter's inferred `pytest -q` to `uv run pytest -q` changes a
  working default for every Python adopter. The table carries no Python package manager until
  a consumer exists (candidate row). `settings_profiles._WRAPPERS` keeps its own set with the
  marker.
- **A `format` column.** The row lists one. No non-Python consumer exists: the only formatter
  wiring is `harness_config._build_hooks`, which keys on a structurally parsed
  `pyproject.toml`. A column with no reader is a population nothing checks (Decision 11).
- **The adopter gate slot and the cross-boundary register** belong to their own rows; see
  *Reach*.

## Task 0 — Verify (may end this pack, or one lane of it)

Outcomes:

- **build**;
- **partial**: a lane whose differential is zero is dropped, with its measurement recorded in
  Landing, and the rest continues;
- **do not build**: every differential is zero.

On a refutation the default exit is **stop and re-raise with the measurement**, not "adjust and
continue". Records go to `reports/tp469/` (gitignored). Never the full tier and never `-n auto`
for Task 0. Every drive is a slice run from the repository root. Appendix A and Appendix B are
saved outside the tree first.

### 0-A The base, and the census

**Oracle:**

1. `gh pr view 121 --json state` prints `MERGED`. Then `git merge origin/main` on the lane.
2. Appendix A, from the root, on the merged tree.
3. Every `path::symbol` under *Affected symbols* resolves (`git grep -n` on the symbol name in
   its file).

**Refuting result:**

- The lane's base does not contain #121's merge (`80e575b`). **Stop.** This pack's citations
  are #121's, and executing against an older base would re-do #121's work. At authoring, #121
  had merged and the lane was fast-forwarded onto it.
- Appendix A line 4 prints a lockfile constant. Someone else read the lockfile; re-scope 2-A.
- A cited symbol does not resolve. Fix the pack (`memory/fix-the-pack-and-proceed-on-a-pre-flight-defect.md`),
  then continue.

### 0-B The package-manager differential

**Oracle:** Appendix B drive 1 on the merged tree, plus the row's probe
(`python tools/cc/check_ledger_probes.py --id DEF-976`).

**Refuting result:** any lockfile variant already infers its own package manager. Then 2-A and
2-B shrink to the variants still wrong, and the row is re-pinned to them.

### 0-C The dependency-directory differential

**Oracle:** Appendix B drive 2, then the same plant under the six scanners (`espalier scan .`
on the planted tree, reading `reports/` for a finding under a planted directory) and
`sister_site_probe.py --json` in adopter mode. Calibrate both ends first: the control file is
read by every walker, and `node_modules` by none.

**Refuting result:** no walker reads a planted directory. Then lane C shrinks to the parity pin
(4-B) and the markers (4-E). The derivation buys no behaviour, so record that in Landing.

### 0-D The source and manifest differential

**Oracle:**

1. Appendix B drive 3 (the plan-gate verdicts on root manifests).
2. Appendix B drive 4 (the scope walk).
3. For Decision 5, a widened map. In a `git archive` export outside the tree, add `.h`,
   `.swift` and `.scala` to `SUFFIX_TO_LANGUAGE`. Then run
   `tests/test_fingerprint.py tests/test_analyze.py tests/test_stack_trees.py` serially and
   count the verdicts that move.

**Refuting result:** none of the three ends the pack. Each one decides Decision 5, 8 or 10;
record the counts.

### 0-E The reader shape

**Oracle:** Appendix B drive 6 on the floor interpreter (3.10) with no `tomli` installed, so
the hook reader takes its regex arm. Also on this host.

**Refuting result:** the regex arm does not read a flat list key on the floor interpreter.
Decision 1 (flat keys) rests on both arms reading one, so stop and re-raise with the output
before building 4-C.

On a host with no 3.10 (this one: `py -0` lists 3.11 only), drive the regex arm directly with
`parser=None`. That is the arm `_hook_utils._toml_parser()` selects on 3.10 without `tomli`,
and the selection is the only version-dependent step. The 3.10 run itself is CI's floor cell
(execution 0-A).

### 0-F The scanners' boundary

**Oracle:** `git grep -n "getsource(" -- espalier tools scripts` and
`git grep -n "espalier.scanners" -- espalier tools`.

**Refuting result:** a production copier of scanner source exists. Then candidate row 3's
premise is wrong, so record that in Landing. 4-B is a pin either way (Decision 4).

### 0-G The docs claims the table encodes

**Oracle:** fetch the four package managers' current docs and read four things:

- how each runs the manifest's `test` script;
- how each runs a named script;
- each one's lockfile names;
- the `packageManager` field's format (a Corepack convention, `<name>@<version>`; Node 26's
  packages doc no longer documents it, so read Corepack's README).

**Refuting result:** `bun test` runs the manifest script. Then bun's template override goes,
and the uniform template stands. Any other difference re-shapes the `PackageManager` rows.

### 0-H Cost

**Oracle:** time `tests/test_node_adopter_defaults.py` serially, before and after 2-D. With
Decision 6, also after 3-F. Measured at authoring: one adopter tree costs about 4.5 to 5.9 s
on this host (TP-468 0-F).

**Refuting result:** the module's serial wall time passes 180 s. Then the go and rust cells
stay install cells, the gap reasons say so, and the bun row's fence tests drop to the plan and
rules assertions.

## Relevant memory

Recent pattern: the defects reviewers find on this tree sit in the **repair** and in the
**tests that prove it**. In the adopter-axes foundation lane, both reviewers returned REQUEST
CHANGES on a green lane: the registry rule read `[node-pnpm]` as proving `node`, and a
strict-xfail parameter as proving its value. #121's own red-team findings landed as one fix
batch. In this pack the likeliest repair defect is a **parity test keyed on the table's own
vocabulary**: drop a name from the table and the enumerator stops looking for lists of it.
That is the born-blind shape, and 1-B names the independent witness.

| Entry | Where |
|---|---|
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| A dedup catalog's "collapse to canon" is a claim, not a prescription | `memory/dedup-collapse-suggestions-are-claims.md` |
| Sister-site compression | `memory/sister-site-compression.md` |
| Asset mirroring (3-way SoT) | `memory/asset-mirroring.md` |
| Grep for a sibling store before building a rival | `memory/grep-for-a-sibling-store-before-building-a-rival.md` |
| Verify a pack's scope-out rationale, not just its prescriptions | `memory/verify-a-packs-scope-out-rationale.md` |
| A gate can be blind along a whole dimension of its input | `memory/a-gate-can-be-blind-along-a-whole-dimension.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |
| Scanner constraints | `memory/scanner-constraints.md` |

Resolved at authoring by `python tools/cc/hooks/_recall.py "<topic>"` with these topics:

- `hand-written list of language extensions drifts across the no-import boundary`
- `forced twin parity test across tools/cc and espalier`
- `a scope-out rationale is a claim purpose-scoped list`

The topic `package manager lockfile detection npm pnpm` returned nothing that fits. Re-run
these rather than trust this list if the pack has been sitting.

The folders this pack touches, so the folder-`CLAUDE.md` ladder fires on entry:

- `tools/cc/` and `tools/cc/hooks/`: protected zones, so edits need `ESPALIER_MAINTENANCE_MODE=1`
  set in the parent shell before launch. Load the hook-authoring skill, and run
  `mypy tools/cc/hooks/` (on this host with `--platform linux`).
- `espalier/scanners/`: stdlib only; `tests/test_scanners.py` and
  `tests/test_contracts.py::TestScannersStdlibOnly` after an edit.
- `espalier/_vendor/`: mirrors; never hand-edited.
- `tests/`: a new `test_*.py` is classified in `tests/conftest.py::_MARKER_RULES`; `git add` a
  new file before gating.

## Implementation

Every fix below is a **fix shape, untested**, unless it says otherwise. Each sub-task names the
mutation its new test must die to, and Landing records that it did. Each lane lands
**equality first**: the first commit derives a list with no behaviour change, proven by an
equality test against today's literal. The second commit widens it, proven by its own
differential. A behaviour change hidden inside a refactor commit is the shape to refuse.

### 1-A The table — `tools/cc/_stack_table.py` and its engine copy

*Fix shape, untested.* Refuted if a consumer needs a fact the rows cannot express. The
likeliest case is `detect_tests`'s Python heuristics (`pytest.ini`, a `tests/` directory beside
a Python manifest). The table supplies the command; the heuristic deciding *whether* pytest
applies stays in `detect_tests`. If that split cannot be kept clean, re-raise.

**Where it lives, and why.** `tools/cc/`, beside `_json_safe.py`, not under `tools/cc/hooks/`.
Three reasons, each read at authoring:

- `tools/cc/hooks/_hook_utils.py` already puts `tools/cc/` on `sys.path` and imports
  `_json_safe` from there. A sibling there is reachable from every hook with no new path line.
- `scripts/verify_pins.py` loads `_hook_utils.py` by path and executes it. A table under
  `hooks/` would need a second path insert inside `_hook_utils` for that load to resolve.
- The precedent for one module on both sides of the boundary is `tools/cc/_blueprint_limits.py`
  and `espalier/_blueprint_limits.py`. That pair is two hand copies held equal by value
  (`tests/test_library_hook_parity.py::TestBlueprintLimitsParity`). This table is a byte copy
  written by the sync script instead, because it is edited whenever a stack is added, and one
  edit is safer than two.

```python target=tools/cc/_stack_table.py
"""What each stack an adopter brings is, in one table.

It imports nothing but the standard library, so the same bytes run on both
sides of the no-import boundary: the hooks import this file, the engine imports its byte
copy espalier/_stack_table.py (mirror row ``stack-table``), and
``python3 scripts/sync_vendor_cc.py`` writes both copies. Every other list
that spells a stack's extensions, manifests, lockfiles, dependency
directories or commands is a projection of this table, or carries a
``stack-table: ok purpose-scoped`` marker saying why it is not
(tests/test_stack_table.py holds both directions).

Commands are argv tuples, never shell strings. The settings renderer narrows
them through settings_profiles.narrowed_rules, so no row's command derives a
bare ``Bash(<binary> *)``, and an argv is the shape a committed stop-gate
command would need on Windows. The one place rule strings live is a row's
``static_allows``: rules rendered only when that stack is detected.
"""
from __future__ import annotations

from typing import NamedTuple


class PackageManager(NamedTuple):
    name: str                    # the binary on PATH: "pnpm"
    lockfiles: tuple[str, ...]   # the files whose presence names it
    test: tuple[str, ...]        # argv that runs the manifest's `test` script
    run: tuple[str, ...]         # argv prefix that runs a named script
    start: tuple[str, ...]       # argv that runs the manifest's `start` script


class Stack(NamedTuple):
    name: str
    languages: tuple[tuple[str, str], ...]          # (suffix, language)
    manifests: tuple[str, ...] = ()                 # go.mod, Gemfile, package.json
    lockfiles: tuple[str, ...] = ()                 # with no manager choice: go.sum, Cargo.lock
    package_managers: tuple[PackageManager, ...] = ()   # the first is the default
    test: tuple[str, ...] = ()                      # argv, for a stack with one runner
    dependency_dirs: tuple[str, ...] = ()           # third-party code, by name, at any depth
    output_dirs: tuple[str, ...] = ()               # build output: rust's target
    lint_fallback: tuple[str, ...] = ()             # argv /preflight runs when nothing is declared
    static_allows: tuple[str, ...] = ()             # rules rendered only for this stack
    ast_scannable: bool = False                     # the scanners can read its source


NPM = PackageManager(
    "npm", ("package-lock.json", "npm-shrinkwrap.json"),
    ("npm", "test"), ("npm", "run"), ("npm", "start"),
)
PNPM = PackageManager(
    "pnpm", ("pnpm-lock.yaml",),
    ("pnpm", "test"), ("pnpm", "run"), ("pnpm", "start"),
)
YARN = PackageManager(
    "yarn", ("yarn.lock",),
    ("yarn", "test"), ("yarn", "run"), ("yarn", "start"),
)
# `bun test` is Bun's own test runner: a built-in wins over a script of the
# same name, so the manifest's scripts run as `bun run <script>` (bun docs,
# "bun run"). bun.lock is the default since Bun 1.2; bun.lockb before it.
BUN = PackageManager(
    "bun", ("bun.lock", "bun.lockb"),
    ("bun", "run", "test"), ("bun", "run"), ("bun", "run", "start"),
)
```

Two shape changes at execution (execution 0-A, both built):

- **NamedTuple rows, not `@dataclass`.** From 3-A on, `_hook_utils` imports this module on every
  tool call. `dataclasses` imports `inspect` (about 4 ms; `tools/cc/hooks/_reinject.py` records
  the same reason). On Python 3.14, a dataclass with stringized annotations also breaks a
  path-based spec-load that does not register the module first (`_explain_path.py`'s note).
- **A `start` argv.** `detect_actions` derives `smoke` from `start` when there is no `dev`
  script. A per-manager argv keeps npm's `npm start` byte-equal (2-B's equality) and gives
  bun `bun run start` (`bun start` would be the same built-in hazard as `bun test`).

The rows (`STACKS: tuple[Stack, ...]`) carry every suffix today's two lists hold. That means a
`python`, `node`, `go` and `rust` row, plus language-only rows for the JVM, C and C++, C#, Ruby,
PHP and Swift suffixes, so that 3-A's equality commit holds. A language-only row may still
carry manifests and lockfiles (Ruby's `Gemfile` and `Gemfile.lock`), which 3-C reads. The
`node` row's `dependency_dirs` is today's `DEPENDENCY_TREE_DIRS`; the `rust` row's
`output_dirs` is `("target",)`; each `lint_fallback` is today's `/preflight` fallback for that
stack; the `python` row's `static_allows` is today's `PYTHON_ONLY_ALLOWS`, and
`ast_scannable` is true on it alone. Projections live
beside the rows as module-level functions (`source_extensions()`, `suffix_to_language()`,
`manifest_names()`, `lockfile_owners()`, `dependency_dirs()`, `script_runners()`), so a
consumer reads one name. Built beside them: `stack(name)`, `package_managers()`,
`package_manager(name)` and `output_dirs()`.

What lane A built that lane B must know:

- the row order reproduces `SUFFIX_TO_LANGUAGE`'s order once `.h`, `.scala` and `.swift` are
  left out (`python`, `node`, `go`, `rust`, `jvm`, `dotnet`, `c`, `php`, `ruby`, `swift`).
  No per-suffix fingerprint flag was built: 3-A's equality commit filters the three suffixes,
  and Decision 5's widening drops the filter;
- the `python` row's `manifests` are the five `_has_python_signals` names. `MANIFEST_NAMES` holds
  only `pyproject.toml` for Python, and `detect_package_systems` reads `pyproject.toml` or
  `requirements.txt`, so 3-B's projections are subsets, not the whole column;
- PHP and Swift carry no manifest (none is in today's lists); Ruby carries `Gemfile` and
  `Gemfile.lock`.

Wiring, each in the same commit:

- the engine copy `espalier/_stack_table.py`. `scripts/sync_vendor_cc.py` writes it beside the
  `_vendor` copy, so the step this repository already runs after a `tools/cc/` edit refreshes
  both;
- a `MirrorRow(name="stack-table", ...)` in `espalier/mirror_registry.py::MIRROR_ROWS`, with
  its pinning test in `tests/test_stack_table.py`. A tenth row carries four obligations, each
  read at authoring:
  - the edit-time advisory: `tools/cc/hooks/_reinject.py`'s census forces an advisory for every
    `MIRROR_ROWS` row, so the new row needs its "run the sync" rule and its fire/silent cases;
  - the number-word: `tests/test_reinject_sync.py` reds any "nine ... rows" left in its declared
    prose sites (`CLAUDE.md`, `.claude/CLAUDE.md`, `tools/cc/CLAUDE.md`, `docs/SHARP_EDGES.md`,
    `scripts/sync_github_workflow_asset.py`). Root `CLAUDE.md` is plan-gated;
  - the census note in `scripts/derived_population_census.py` that reads `MIRROR_ROWS`;
  - the per-row table in `memory/asset-mirroring.md`, which
    `tests/test_reinject_sync.py::test_asset_mirroring_table_names_every_row` requires to name
    every row.

  Five more, none named at authoring (execution 0-A; each driven, and green once built):
  - `espalier/surface_impact.py::classify_surface`:
    `tests/test_reinject_sync.py::test_every_row_has_a_surface_impact_obligation` requires the
    mirror side to name the row's own sync. Built as a rule for each side: the engine copy says
    an edit is overwritten, and the source names both mirrors;
  - the `docs/CONVENTIONS.md` *Library / hook parity* registry: the basename is now on both sides
    of the boundary, and
    `tests/test_library_hook_parity.py::test_every_engine_hook_twin_is_named_in_the_conventions_registry`
    requires a row;
  - `tests/test_managed_inventory.py`, which pins `INIT_TOOL_SCRIPTS` as an exact tuple in
    declaration order;
  - `cc/PACK_MANIFEST.txt`, re-rendered (`tests/test_manifest_truth.py`);
  - the advisory itself is an extension of `_reinject._render_vendor_sync`, not a new rule. The
    generated side says the edit is DISCARDED; the source side names the engine copy. A new
    `-SYNC` rule would have had to join the drop-order roster in `tests/test_reinject_sync.py`,
    so no test edit was needed.

  The cheaper alternative is to have the engine load the shipped `espalier/_vendor/cc/_stack_table.py`
  by path. It is refuted by the import contract's reading of `_vendor/` as deploy data, not as
  an engine module. Raise it at review only if the four obligations prove heavier than
  measured here;
- the deploy roster `espalier/managed_paths.py::STANDARD_MANAGED_TOOLS` (beside
  `tools/cc/_blueprint_limits.py`, the precedent; `espalier/cli.py::INIT_TOOL_SCRIPTS` is that
  list). `tests/test_deploy_set_import_closure.py` is the gate that a deployed module's imports
  are deployed too. The roster feeds the generated deploy-inventory regions in `README.md` and
  `docs/QUICKSTART.md`, so run `python scripts/generate_doc_regions.py`. Then the integrity
  manifest refresh a `tools/cc/` file needs.
- `espalier surface-impact` at authoring listed the zero-import contract, the vendor mirror and
  provenance for the new tool, but not the deploy roster. Read the roster from this list, not
  from that report.

**Proof:** `pytest -q tests/test_stack_table.py tests/test_vendor_cc_parity.py tests/test_surface_contract.py`
(run the surface module named by `espalier surface-impact` at pre-flight 0-D, whichever it is),
and the five obligations above: `tests/test_reinject_sync.py`, `tests/test_library_hook_parity.py`,
`tests/test_managed_inventory.py`, `tests/test_manifest_truth.py`, `tests/test_surface_impact.py`.

**Mutations:**

- Edit one byte of the engine copy, and the mirror pin reds.
- Drop the file from `STANDARD_MANAGED_TOOLS`, and
  `tests/test_deploy_set_import_closure.py::test_every_deployed_script_sibling_import_is_also_deployed`
  reds. It can red only from 3-A on, because no deployed module imports the table before
  `_hook_utils` does, so this mutation is run in lane B and recorded there. In lane A the
  entry is inert.

### 1-B The hand-list ratchet — `tests/test_stack_table.py`

The census instrument's lines 1 to 4, as a test. Walk `espalier/` (minus `espalier/_vendor/`
and the engine copy) and `tools/cc/` (minus the table). Find every collection literal that
holds a dependency directory, two or more source suffixes, two or more manifests, or a
lockfile name. Each must be either absent (derived) or carry the marker
`# stack-table: ok purpose-scoped -- <reason>` on its assignment's line or the line above. The
marker family follows the house shape (`fail-open: ok`, `sister-site: ok`). It is a new
family, not `sister-site: ok`, because that marker exempts a site from the clique probe, which
is a different question.

- **The vocabulary is the table's union with a fixed seed written in the test** (the five
  `DEPENDENCY_TREE_DIRS` names, `.venv`, `target`, the four lockfile names this pack adds, the
  Node and Python suffixes). The seed finds a hand list that spells a name the table lost.
- **A floor pin** in the same test: each seed name is a member of the table projection it
  belongs to (`node_modules` in `dependency_dirs()`, `pnpm-lock.yaml` in `lockfile_owners()`,
  `.mjs` in `source_extensions()`). Once the hand lists are projections no literal spells the
  name any more, so the ratchet alone cannot see a name deleted from the table. The floor pin
  is what reds then.
- **The baseline** is a dated set of `path::symbol` sites still pending lanes B and C. It may
  only shrink, like `tests/test_test_suite_contract.py`'s `_RAW_GIT_POPULATION_SITES` ratchet.
  It is empty when lane C lands.
- `scripts/` is out of the walk, with the reason in the test's docstring (self-host tooling,
  never shipped).

As built (execution):

- **Shapes read:** set, list and tuple displays; a dict display's keys; `frozenset(...)`,
  `set(...)`, `tuple(...)` and `list(...)` over one; `"a b".split()`; and a `+` of any of these.
  A literal nested in a reported one is the same site. This is wider than the re-pinned
  probe, which reads the census's shapes only, so the probe can only under-count a future
  `+` or `.split()` list, never invent one. Today both count the same 25 sites.
- **`target` is not a trigger on its own.** It is an output directory and an English word
  (`("source", "target")`). It sits in the floor pin, as `output_dirs()`. Every list that
  prunes it today also spells a dependency directory, so it adds no site (measured: 25 with
  it, 25 without).
- **The marker is a comment** (`#\s*stack-table: ok purpose-scoped`) and must carry
  `-- <reason>`. Prose naming the marker, such as this table's docstring or a surface-impact
  obligation string, marks nothing.
- **The baseline counts per owner** (`path::owner -> n`), so a second hand list added beside
  a baseline one still reds.

**Mutations:**

- Add `_X = {"node_modules", "dist"}` to a production module, and the ratchet reds.
- Remove `node_modules` from the table, and the floor pin reds. The ratchet stays green,
  because no literal spells it, which is why the floor pin exists.
- Mark a derived site, and an "a marker on a projection" check reds. A marker on a list that
  no longer spells the vocabulary is stale.

### 2-A Package-manager resolution — `espalier/analyze.py::detect_package_manager`

*Fix shape, untested.* Refuted if 0-G shows the `packageManager` field is not
`<name>@<version>`, or that one of the four package managers names its lockfile differently.

```python target=espalier/analyze.py
def detect_package_manager(repo_root: Path) -> tuple[str, str]:
    """``(name, source)``: the Node package manager this repository uses and
    what said so. ``package.json``'s ``packageManager`` (``"pnpm@9.12.0"``)
    first, when it names a package manager of the stack table; then the one
    table lockfile present at the root; then ``npm``. Two or more lockfiles
    of different managers are not guessed between: ``npm``, with ``source``
    naming the files, so ``doctor`` can say which to delete or how to declare
    one. ``source`` is ``"packageManager"``, the lockfile's name,
    ``"ambiguous: <files>"`` or ``"default"``."""
```

`analyze.fingerprint_repo` records the pair on the fingerprint (a new
`espalier/models.py::RepoFingerprint.package_manager` field), so `doctor`, the banner and
`cc/COMMANDS.md` can name it. `doctor` gains one warning for `ambiguous:`. Its next
step names `packageManager` in `package.json` and `[extra_actions]` in `espalier.toml`, the two
declarations that already exist (Decision 2).

Decided at execution (execution 0-A):

- **No root `package.json`, no answer:** `("", "")`. Without it, a Python or Go fingerprint
  would name `npm`. The unit table gains that row.
- **The field is `dict[str, str]`**, `{"name": ..., "source": ...}`, and `{}` without a root
  `package.json`. A tuple would read back from JSON as a list.
- **`packageManager` is read by name only:** the text before `@`, so `yarn@4.5.0+sha224.<hash>`
  reads `yarn`. A name the table does not hold falls through to the lockfiles. Corepack
  manages npm, pnpm and Yarn, not Bun (0-G), but a `bun@` value is still the adopter's own
  declaration.
- **Four more obligations of the new field:**
  - `espalier/diffing.py::FINGERPRINT_SIGNAL_FIELDS`, because
    `tests/test_diffing.py::test_every_fingerprint_field_is_reduced_or_a_signal` classifies every
    field. A changed package manager is drift worth reporting, so it is a signal;
  - the `_FINGERPRINT_CENSUS` input in `tests/test_diffing.py`;
  - `docs/schemas/repo_fingerprint.schema.json`, pinned field-for-field by
    `tests/test_documented_claims.py`;
  - that test itself.

**Proof:** a unit table in `tests/test_stack_table.py` over `write_stack(tmp, "adopter-node")`
plus each of:

- no lockfile;
- `package-lock.json`;
- `pnpm-lock.yaml`;
- `yarn.lock`;
- `bun.lock`;
- `bun.lockb`;
- `packageManager: "yarn@4.5.0"` beside a `pnpm-lock.yaml` (the field wins);
- `pnpm-lock.yaml` beside `package-lock.json` (ambiguous).

**Mutation:** make `detect_package_manager` return `("npm", "default")`, which is today's
behaviour reconstructed. Every non-npm row reds.

### 2-B Command inference from the table

`detect_tests` appends `" ".join(pm.test)` where it appends `"npm test"` today. `detect_actions`
builds `lint`, `build` and the `dev` form of `smoke` from `pm.run`, and the `start` form of
`smoke` from `pm.start` (execution 0-A: `npm start`, `pnpm start`, `yarn start`,
`bun run start`). Go's and Rust's runners come from their rows. `make` stays where it is: a
Makefile is not a stack.

**Equality first:** on a tree with no lockfile, every string `detect_tests` and
`detect_actions` return is byte-identical to today's. `npm start` stays `npm start`; the table
does not normalise it to `npm run start`. One self-host consumer reads `detect_tests` directly
(`bench/run_benchmark.py`, on this repository's own Python tree), so equality keeps it unmoved.

**Proof:**

- The row's original probe command, run by hand, prints `pnpm`. The row itself was re-pinned
  at lane A's start (below), so this is recorded in Landing as the package-manager leg's
  witness, not read from the ledger.
- `tests/test_node_adopter_defaults.py::TestThePlanCarriesTheRepositorysCommands` at
  `node-pnpm` reads `pnpm test` / `pnpm run lint` / `pnpm run build`, and at `node-bun` reads
  `bun run test` / `bun run lint` / `bun run build`.

**Mutation:** the bun row's `test` set to `("bun", "test")` reds the bun assertion (the
footgun, pinned).

**Re-pin before the first edit** (`memory/task-packs.md`, "Re-pin a row's probe BEFORE the
first edit"). The probe flips to `pnpm` at 2-B, but the row stays open for lanes B and C. So,
at the start of lane A, before any edit, re-pin `DEF-976` with
`python tools/cc/ledger_row.py repin DEF-976 --reason ... --probe-cmd ... --open-value ...` to a
probe that can run on today's tree. It should count the **defect sites**: the stack-vocabulary literals in
`espalier/` (minus `_vendor/`) and `tools/cc/` that are neither derived nor marked, which is
Appendix A's predicate on the ratchet's two roots. Today that is lines 1b, 2 and 3 less
`scripts/`. It falls as lanes A to C land, and it prints `0` when the row can be struck.

It must not count the ratchet's baseline, because that test does not exist before the first
edit, and the verb cannot re-pin after a fix. Drive it by hand first, and read why it prints
what it prints.

### 2-C Permission rules from the table — honouring DEC-37

- `settings_profiles._SCRIPT_RUNNERS` becomes the table's `script_runners()`. Adding a package
  manager to the table then narrows its `run` verb with no second edit.
- `settings_profiles.PYTHON_ONLY_ALLOWS` becomes the `python` row's `static_allows`.
  `is_python_fingerprint` keeps its name and reads "a stack with static allows is detected"
  (equality first: the same five rules on the same fingerprints). The rule strings also stay as
  literals in `_WORKFLOW.allow` and `_SELF_HOST.allow`, because `python_only` only filters the
  profile's allow tuple at render. So a pin holds each of those tuples as a superset of the
  `python` row's `static_allows`. Otherwise a rule added to the table would render nowhere.
- `narrowed_rules` stays the one narrowing function. The table carries no rule string for a
  command, only argv templates.
- `_EXECUTOR_VERBS`, `_EXACT_ONLY_BINARIES`, `_WRAPPERS` and `_INLINE_CODE_FLAGS` stay in
  `settings_profiles` with the marker. They are the narrowing function's security vocabulary,
  not stack identity.
- Test-writer's static `Bash(pytest *)`: left as it is (Decision 13). The shipped body is
  also this repository's own agent, and `harness_config.render_agent_tools` only appends, so
  moving the rule would change the Python line and this repository's test-writer for a rule
  that is harmless on a Node tree.

**Proof, in `tests/test_stack_table.py`:**

- For every table package manager and every template it owns, `narrowed_rules` derives no
  `Bash(<binary> *)`.
- `narrowed_rules(f"{pm} exec x")` and `narrowed_rules(f"{pm} dlx x")` derive the exact form
  only.

The Node defaults test at `node-pnpm` asserts `Bash(pnpm test)` and `Bash(pnpm test *)` and no
`Bash(npm test)`.

**Mutation:** remove `pnpm` from `_SCRIPT_RUNNERS`'s projection only (keep the
`PackageManager` row, so 2-A still detects pnpm). Then `narrowed_rules("pnpm run build")`
derives `Bash(pnpm run)` and `Bash(pnpm run *)`, which is every script, and the unit pin on
the `node-pnpm` rules reds. Deleting the whole row would red through 2-A's detection instead,
and would not isolate 2-C.

### 2-D The bun row and the proven stack cells

- `tests/_stack_trees.py` gains `adopter-node-bun`: `_ADOPTER_NODE` plus a `bun.lock` body
  shaped like Bun 1.2's text lockfile (0-G confirms the shape). Run
  `python scripts/sync_selfcheck_tests.py`.
- `tests/test_stack_trees.py::_LANGUAGE` gains `node-bun`.
- `tests/test_node_adopter_defaults.py::STACKS` becomes
  `("python", "node", "node-pnpm", "node-bun")`. Each parametrised test states its expected
  commands per stack: the plan's actions, the narrowed rules, the runner agents' `tools:`
  lines, and the two fences' calls. `_SOURCES` and `_LANGUAGE` gain the two variants (the
  `node` files). The fence runner stubs `pnpm` and `bun` beside `npm`.
- The module branches on `stack == "node"` in several places (the UI surface, the suggested
  agents, the lint fence), and its `bare` rule regex names no `bun`. A node-family predicate
  replaces the equality, and the regex gains `bun`; otherwise the two variants silently take
  the Python branch (execution 0-A).
- `tests/_axis_registry.py`: `stack/node_pnpm` and a new `stack/node_bun` name
  `tests/test_node_adopter_defaults.py::TestASessionOnTheTreeIsGoverned::test_the_hooks_govern_a_session_on_the_tree[node-pnpm]`
  and `[node-bun]`. `PROVEN_FLOOR` rises by two from whatever the base holds when the lane
  lands (it was 2 at authoring; the adopter-axes pack raises it too), dated.
- The registry rule cannot see whether a test body uses its parameter. So the session test
  also asserts, per stack, that the fingerprint's `package_manager` is the stack's. That is
  the second witness TP-468's Risk 1 asked for.

**Proof:** `python tests/_axis_registry.py` prints `stack` proven at four values.

**Mutation:** make `build_adopter_tree(stack="node-bun")` write the `adopter-node` row, and the
second witness reds.

### 2-E `/preflight`'s fallback ladder

The declared path already reads the fingerprint, so it arms from the table once 2-B lands. What
is left is the bash fallback ladder (ruff, eslint, golangci-lint, clippy, each behind a project
file).

**Pinned** (Decision 9). A contract test reads the deployed fence and asserts that
each table stack with a fallback lint has a branch guarded by one of the stack's manifests,
running that stack's fallback. Moving the probes into Python changes how `command -v` resolves
on Windows: `shutil.which` applies `PATHEXT`, and the extensionless stubs
`TestTheDeployedPreflightFences` puts on PATH may stop resolving (probable, not driven). That
risk buys nothing the pin does not.

**Mutation:** delete the `go.mod` branch from the fence (in a scratch copy of the body), and the
pin reds.

### 3-A Source extensions and the language map

1. **Equality commit:**
   - `_hook_utils.SOURCE_LANGUAGE_EXTENSIONS = _stack_table.source_extensions()`;
   - `analyze.SUFFIX_TO_LANGUAGE = _stack_table.suffix_to_language(fingerprint=True)`, whose
     flag excludes the three suffixes the fingerprint leaves out today (`.h`, `.scala`,
     `.swift`);
   - both equal to today's literals, pinned by a test holding the literal once (then deleted
     in the widening commit).
2. **Widening commit, only under Decision 5:** drop the flag. The fingerprint reads all 24, and
   `TestFingerprintLanguagesAreHookSource` becomes equality. 0-D (3) states which verdicts move.

**The import must be guarded** (*fix shape, untested*). `_hook_utils` sits above every hook's
crash funnel, and it already guards its `_json_safe` import for this reason. A missing or stale
deployed table (an adopter's user-patched copy, which the next upgrade preserves) must not take
the whole hook layer down at import. Catch `ImportError` and `AttributeError`, and say it
once a session (`say_once`). Fall back to a **pinned literal**, today's 24-suffix set, carrying
the `stack-table: ok purpose-scoped -- import fallback` marker. `tests/test_stack_table.py`
pins it equal to `source_extensions()`.

The fallback must not be an empty set. An empty set would under-arm every source gate.
`scripts/verify_pins.py::source_language_extensions` also refuses to collapse an unavailable
owner into `frozenset()` (its docstring), and an empty table would hand it exactly that.

This shape is refuted if the red-team's drive (a deployed tree whose table is deleted) shows a
hook still crashing at import.

**Proof:**

- the equality pin;
- `scripts/verify_pins.py::source_language_extensions`, which loads `_hook_utils.py` by path,
  returns a set **equal** to `source_extensions()` from a scratch checkout. Not merely
  non-`None`: an empty set would pass that, and is the collapse the script forbids;
- a hook fired on an init'd tree with `tools/cc/_stack_table.py` deleted exits 0, and says so.

**Mutation:** delete `.mjs` from the `node` row, and
`TestASessionOnTheTreeIsGoverned[node]` reds at the root `index.mjs`.

### 3-B Manifests

- `analyze.MANIFEST_NAMES`, `_hook_utils.PROJECT_MANIFEST_NAMES`,
  `analyze._has_python_signals`'s tuple, `detect_tests`' foreign-manifest tuple and
  `analyze.detect_package_systems`' chain all become projections, equality first.
- `PROJECT_MANIFEST_NAMES` stays a four-name subset (it is `repo_name`'s read order, and
  `reflect_trigger.CONFIG_FILES`'). The projection takes the stack names in order.

**Mutation:** remove `go.mod` from the `go` row. `languages` does not move, because it comes
from `detect_languages`' suffix counts. So the proof is a new assertion in
`tests/test_stack_trees.py::TestEveryStackInstalls` that each adopter stack's fingerprint lists
its system in `package_systems` (`go` for `adopter-go`, `node` for the Node rows), and that
assertion reds.

### 3-C Root manifests and lockfiles plan-gated — Decision 8

`plan_guard.PLAN_REQUIRED_ROOT_FILES` keeps its non-stack members (Dockerfile, Makefile,
Procfile, the doc files). It gains every table manifest and lockfile.

**Proof:** `tests/test_plan_guard.py` drives `go.mod`, `go.sum`, `Gemfile` and `bun.lockb` to a
deny. The explainer prints "plan required" for each.

### 3-D One AST-scannable predicate

Four sites decide the same thing, and they spell it three ways:

- `analyze.detect_actions` offers `scan` on `_has_python_signals` (a manifest);
- `harness_config._detect_actions` offers it on `"python" in fp.languages`;
- `cli`'s init report and `cmd_scan`'s warning key on the primary language.

Each site keeps its own semantics (offer when any scannable language is present; warn when the
primary is not scannable). The literal `"python"` becomes a read of the table's flag.
Low leverage, because a second scannable language is not planned. The red-team may call it
ceremony. If so, drop it and record that in Landing.

### 3-E `scope_walker.INCLUDED_EXTS` — Decision 10

`INCLUDED_EXTS | _stack_table.source_extensions()`, so `/scope-check` reads the adopter's own
source.

**Proof:** Appendix B drive 4 returns `src/index.mjs` and `src/app.ts`.

**Mutation:** revert to the literal, and the drive's test reds.

The module's sibling comment names `surface_impact._PATH_SUFFIXES`, `proofs.TEXT_SUFFIXES`
and `pack_manifest`'s inline tuple. It is updated to say why this one alone joins the table.

### 3-F The go and rust cells — Decision 6

`tests/test_node_adopter_defaults.py::STACKS` gains `go` and `rust`. `_SOURCES` gains a root
file, a source file and a doc file for each. The fence runner stubs `go`, `cargo` and
`golangci-lint`. The registry cells move from gaps to proven, and `PROVEN_FLOOR` rises again.
This answers TP-468's open question ("whether `go` and `rust` count as proven by their install
cells") with a session proof instead of a ruling.

### 4-A Dependency directories

- `_safe_walk.DEPENDENCY_TREE_DIRS = frozenset(_stack_table.dependency_dirs())` (equality).
- The adopter-content walkers derive their dependency half: `analyze.DEFAULT_SKIP_PARTS`,
  `espalier/reflect_protocol.py::_WALK_SKIP_DIRS` and its hook twin,
  `repo_mode._WALK_SKIP_DIRS` and `sister_site_probe._ADOPTER_PRUNE_NAMES`.
- `tests/test_safe_walk.py::_walker_reads` gains each of them. Its planting test plants from
  `DEPENDENCY_TREE_DIRS`, which becomes a projection. It must also plant from 1-B's fixed seed,
  or a name deleted from the table is never planted, and the walkers' renewed reading of it goes
  unseen.
- `target`: the table's `rust` row carries it as an **output** directory, not a dependency
  one, read by the fingerprint and the scanners only. `DEPENDENCY_TREE_DIRS`'s docstring keeps
  its rule (Python environments and `vendor/` are not members). Whether `target` belongs in
  the router walk and the non-git fallback is decided by 0-C's measurement, not here.

**Mutation:** remove `bower_components` from the table. 1-B's floor pin reds, and so does
the planting test, which plants it from the seed and finds the fingerprint reading it again.

### 4-B The six scanner walk lists — Decision 4

Decided: **pin**, the forced-twin precedent (`memory/dedup-collapse-suggestions-are-claims.md`:
forced copies get a parity test). `tests/test_forced_copy_parity.py::TestScannerDefaultExcludeParity`
widens to assert that each of the five `DEFAULT_EXCLUDE` sets, and
`encoding_contracts.PRUNE_DIRS`, is a superset of the table's dependency directories and its
`rust` output directory. All six lack `target`, and the five `DEFAULT_EXCLUDE` copies also
lack the four `DEF-942` names. So the five gain five names, and `PRUNE_DIRS` gains the same
five (Appendix A line 1b). This is a behaviour change, proven by 0-C's scanner plant.

**Mutation:** drop `.yarn` from `prints.DEFAULT_EXCLUDE`, and the pin reds.

### 4-C The `dependency_dirs` key — Decision 1

- A flat, additive top-level key, like `source_extensions`.
- `espalier/models.py::HarnessConfig.dependency_dirs` and a shape twin in
  `espalier/config.py::_check_knob_values`: a directory name, no `/`, not `.` or `..`. The twin
  is pinned in `tests/test_forced_copy_parity.py::TestKnobShapeParity`.
- The hook side reads it through `_hook_utils.read_toml_string_list` for the two `tools/cc/`
  walkers.
- `examples/espalier.toml` documents it above the `[extra_actions]` table, which stays last.

**Proof:** `tests/test_config_fields_consumed.py` sees the field consumed. A planted `deps/`
named in the key is unread by every derived walker.

### 4-D `DEF-971` — Decision 7

Folded (Decision 7). It brings its own fix shape and its own test: the parent-name
differential, the prune during the walk, and `analyze._iter_files` added to `_walker_reads`. It
lands **after** 4-A, because 4-A changes the name set its test plants. Its probe moves when 4-A
adds the four names to `DEFAULT_SKIP_PARTS`. So drive it before 4-A and after 4-D, and strike
it with both values in the closing text.

### 4-E Markers, and the ratchet to zero

Mark the lists *Scope (out)* names as purpose-scoped, each with its reason. Empty the 1-B
baseline. `python tools/cc/check_ledger_probes.py --strikes` explains every probe the lane
moved.

### 5-A Red-team (budgeted; see Risks)

Two reviewers per lane, `code-reviewer` and `failure-mode-reviewer`, on the lane's own diff with
edits frozen. Ask each for the mutation that survives, not for approval. In particular:

- a ratchet that misses a literal shape (a comprehension, a `+` of two tuples, a `.split()`
  string);
- a projection that agrees with today's literal by accident of order;
- a lockfile precedence that a monorepo breaks (a lockfile one directory down);
- a pnpm or bun fence assertion that passes because the stub is never on PATH.

One fix batch per lane.

## Affected symbols

### Changed-semantics

- `tools/cc/hooks/_hook_utils.py::SOURCE_LANGUAGE_EXTENSIONS` (a projection of the table)
- `tools/cc/hooks/_hook_utils.py::PROJECT_MANIFEST_NAMES` (a projection)
- `tools/cc/hooks/plan_guard.py::PLAN_REQUIRED_ROOT_FILES` (gains the table's manifests and lockfiles; Decision 8)
- `tools/cc/reflect_protocol.py::_WALK_SKIP_DIRS` (dependency half derived)
- `tools/cc/sister_site_probe.py::_ADOPTER_PRUNE_NAMES` (dependency half derived)
- `espalier/analyze.py::SUFFIX_TO_LANGUAGE` (a projection)
- `espalier/analyze.py::MANIFEST_NAMES` (a projection)
- `espalier/analyze.py::DEFAULT_SKIP_PARTS` (dependency half derived)
- `espalier/analyze.py::detect_tests` (the package manager's template)
- `espalier/analyze.py::detect_actions` (the package manager's `run` prefix)
- `espalier/analyze.py::detect_package_systems` (manifests from the table)
- `espalier/analyze.py::_has_python_signals` (manifests from the table)
- `espalier/_safe_walk.py::DEPENDENCY_TREE_DIRS` (a projection)
- `espalier/reflect_protocol.py::_WALK_SKIP_DIRS` (dependency half derived)
- `espalier/repo_mode.py::_WALK_SKIP_DIRS` (dependency half derived)
- `espalier/scanners/godfiles.py::DEFAULT_EXCLUDE` (and its four twins and `encoding_contracts.PRUNE_DIRS`: held to the table)
- `espalier/settings_profiles.py::PYTHON_ONLY_ALLOWS` (the python row's static allows)
- `espalier/settings_profiles.py::_SCRIPT_RUNNERS` (a projection)
- `espalier/settings_profiles.py::is_python_fingerprint` (reads the table)
- `espalier/harness_config.py::_detect_actions` (the scan predicate)
- `espalier/scope_walker.py::INCLUDED_EXTS` (Decision 10)
- `espalier/models.py::HarnessConfig` (gains `dependency_dirs`)
- `espalier/models.py::RepoFingerprint` (gains `package_manager`)
- `espalier/analyze.py::fingerprint_repo` (records the package manager)
- `espalier/config.py::_check_knob_values` (the new key's shape)
- `espalier/mirror_registry.py::MIRROR_ROWS` (the `stack-table` row)
- `espalier/managed_paths.py::STANDARD_MANAGED_TOOLS` (deploys the table)
- `scripts/sync_vendor_cc.py::_mirrored_files` (the file set; `plan()` and `sync()` gain the engine copy. Declared through this helper because the bare names `sync` and `plan` grep hundreds of unrelated hits)
- `tests/_stack_trees.py::STACKS` (gains `adopter-node-bun`)
- `tests/_axis_registry.py::PROVEN_FLOOR` (rises)
- `tests/test_forced_copy_parity.py::TestScannerDefaultExcludeParity` (widened)
- `tests/test_forced_copy_parity.py::TestFingerprintLanguagesAreHookSource` (equality under Decision 5)
- `tests/test_safe_walk.py::_walker_reads` (gains the derived walkers)

### Renamed

- (none -- every derived constant keeps its name, so no reader moves.)

### Added-paths

- `tools/cc/_stack_table.py`
- `espalier/_stack_table.py`
- `espalier/_vendor/cc/_stack_table.py`
- `espalier/analyze.py::detect_package_manager`
- `tests/test_stack_table.py`
- `task-packs/TP-469-stack-registry.md`

### Removed-paths

- (none -- the literals become projections in place.)

## Reach

**How the members were derived:**

- the row's own clauses (`grep -n "^| \`DEF-976\`" task-packs/FORWARD_LEDGER.md`);
- the rows it names (`DEF-961`, `DEF-962`, `DEF-965`, `DEF-948`, `DEF-971`), read on #121's tree;
- `DEF-963` (the agent `tools:` lines, named by the row through `test-writer.md`);
- the Gate 1 rows the row's "Stop gate 1" clause lands on (`DEF-949`, `DEC-35`);
- Appendix A's six lines;
- the four authoring drives.

This is not an absence proof. Another row may name this shape in words none of these reads.

| Item | Status | Evidence |
|---|---|---|
| `DEF-976` package-manager leg | **CLOSED by 2-A and 2-B** if 0-B builds | the row's original probe command, run by hand, prints `pnpm` (the row is re-pinned to the site count at lane A's start); the reconstructed `("npm", "default")` reds the unit table |
| `DEF-976` permission leg | **CLOSED by 2-C** | the `node-pnpm` rules; no table template derives a bare rule |
| `DEF-976` test-writer `Bash(pytest *)` | **NOT REACHED** by Decision 13 (candidate row 9) | the body is also this repository's agent, and the render only appends |
| `DEF-976` `/preflight` ladder | **CLOSED by 2-E** (pin) | the deleted-branch mutation |
| `DEF-976` source-extension leg | **CLOSED by 3-A** (two hand twins become projections) | equality pins; the `.mjs` mutation |
| `DEF-976` manifest leg | **CLOSED by 3-B** | equality pins; the `go.mod` mutation |
| `DEF-976` dependency-directory leg | **CLOSED by 4-A, 4-B and 4-E** if 0-C builds | the widened planting test; the ratchet at zero |
| `DEF-976` the adopter's own declaration | **CLOSED by 4-C**, with `source_extensions` (#121) and `[extra_actions]` (#121) | the planted `deps/` |
| `DEF-976` Stop Gate 1 from the table | **NOT REACHED** | Gate 1's fork is `DEF-949` step 4 and `DEC-35`; the table supplies argv |
| `DEF-961`, `DEF-962`, `DEF-965` | **already CLOSED by #121** (consumed) | struck on #121's ledger |
| `DEF-963` | **already CLOSED by #121**; the residue is the test-writer row above | read on #121's tree |
| `DEF-948` | **already CLOSED** (2026-09-30) | its spawn path is what a table command would use under `DEC-35` |
| `DEF-971` | **CLOSED by 4-D** (Decision 7) | its own test; its probe, driven before 4-A and after 4-D |
| `DEF-949` step 4, `DEC-35` | **NOT REACHED** | operator decision; Scope (out) |
| `DEF-1094` (a gate slot per lifecycle point) | **NOT REACHED** | a different table (`[gates]`); this pack adds no command key, so it builds no rival |
| `DEF-549` (the cross-boundary register) | **NOT REACHED** | the table's byte mirror is a new equal-valued pair set across the boundary; its mirror pin should count as "pinned" in that register's derivation (Risk 6) |
| registry `stack/node_pnpm`, `stack/node_bun` | **proven by 2-D** | `python tests/_axis_registry.py` |
| registry `stack/go`, `stack/rust` | **proven by 3-F** (Decision 6) if 0-H passes; otherwise gaps whose reasons say so | as above |
| beyond the row: root manifests and lockfiles plan-gated | **CLOSED by 3-C** (Decision 8; candidate row 2 folded) | drive 3's four exempt names are denied |
| beyond the row: `/scope-check` blind to non-Python source | **CLOSED by 3-E** (Decision 10; candidate row 1 folded) | drive 4 returns the `.mjs` and `.ts` files |
| beyond the row: two `scan`-offer predicates | **CLOSED by 3-D** | one table flag read at all four sites |

## Pass criteria

Each criterion names the lane that can meet it (execution 0-A). Lane A cannot print the
closed value, empty the baseline or explain the strike: those wait for lane C.

- **(lane C)** The row's probe, or its re-pin at lane A, prints its closed value. The census
  (Appendix A) on the landed tree prints:
  - line 4: the table's lockfile names, in `tools/cc/_stack_table.py` and its two copies
    only;
  - lines 1 to 3: only projections and marked sites.
- **(lane C)** `tests/test_stack_table.py`'s ratchet baseline is empty, and its seed vocabulary
  is no smaller than at landing.
- **(every lane)** Every test this pack adds was seen red against its named mutation, recorded
  in Landing. Where
  a pre-fix state exists, the mutation reconstructs it.
- **(every lane) No assertion in an existing test is weakened, and no sample or stack is removed from a
  parametrisation.** Strengthening is allowed and recorded. The equality commits change no
  verdict of an existing test; a widening commit names each verdict it moves.
- **(lane A)** `python tests/_axis_registry.py` prints `stack` proven at four values or more,
  and `PROVEN_FLOOR` equals the proven count.
- **(every lane)** `python scripts/sync_vendor_cc.py`, `python scripts/sync_selfcheck_tests.py`
  and `python scripts/sync_claude_mirrors.py` leave no diff, and the `stack-table` row's pin is
  green.
- **(every lane)** `mypy tools/cc/hooks/` reports no issues (on this host `--platform linux`); `ruff check .` is
  clean.
- **(every lane)** `python scripts/proof_tier.py` names the tier the diff earns, and it is
  green. Expect `full`,
  because `tools/cc/` and `espalier/` change. Run it with `PYTEST_XDIST_AUTO_NUM_WORKERS`
  capped in the shell profile, or serially. No new test assumes `-n auto`. Each new or widened
  module builds its trees once per module.
- **(every lane)** `python tools/cc/check_ledger_probes.py --strikes` names every probe the
  lane moved, each explained.

## Risks — what this pack most likely got wrong

1. **The ratchet is born blind on its own vocabulary.** 1-B's seed is the witness. The
   red-team is asked for a list the enumerator misses: a comprehension, a concatenation, a
   string split into a list.
2. **The equality commits are not equal.** A projection built from a tuple of rows can reorder
   a `dict` (`SUFFIX_TO_LANGUAGE`) or a tuple (`PROJECT_MANIFEST_NAMES` is a read order). The
   equality pins compare order where order is read.
3. **Lockfile precedence is a hypothesis.** "One lockfile names the manager; several name
   themselves" was not measured on real repositories. A monorepo with a lockfile one directory
   down (a nested package) is not read at all. The red-team is asked for that tree.
4. **The bun and Corepack facts are the docs' word, fetched once.** 0-G re-reads them. Corepack
   was unbundled from Node, so the `packageManager` field's reach may be shrinking. That is a
   reason to keep it the first source, not to drop it, since pnpm and Yarn read it themselves.
   Probable, not measured.
5. **A new deployed module is a deploy obligation.** From 3-A on, `_hook_utils` imports the
   table. A tree deployed without it then takes 3-A's guarded fallback: the import does not
   crash, but the gates run on the pinned literal and say so. The gate that catches the missing
   roster entry is `tests/test_deploy_set_import_closure.py`. 1-A names the roster, and
   `espalier surface-impact` at pre-flight 0-D lists the rest. A second reader loads
   `_hook_utils.py` by path: `scripts/verify_pins.py::source_language_extensions` executes the
   file and reads `SOURCE_LANGUAGE_EXTENSIONS`. Driven at authoring, it returns the 24-suffix
   set; it returns `None` (and the report prints "unavailable") if the import 3-A adds cannot
   resolve. 3-A's proof includes that call.
6. **The new mirror pair meets the cross-boundary register.** `DEF-549`'s derivation of
   equal-valued pairs across `tools/cc/` and `espalier/` would see every constant in the table
   twice. Either that derivation treats a mirror-registry row as pinned, or this lane's
   reviewers say why it need not. It must not read the pair as unpinned debt.
7. **Two writers on one tree** (`memory/one-writer-per-shared-state.md`).
   `tests/test_node_adopter_defaults.py` shares its init'd trees read-only across tests, and
   the session test works on a copy. 2-D and 3-F keep that shape. A fence stub directory per
   test, never shared.
8. **Gate 1 expectations leak in.** A reviewer reading the row will ask why Stop does not run
   `pnpm test`. The answer is Scope (out), and the Landing line says so.
9. **The table becomes a single point of failure for the hook layer.** `_hook_utils` imports it,
   and every hook imports `_hook_utils`. An unguarded import turns a missing or stale deployed
   table into every hook crashing at import. 3-A prescribes the guard (`_json_safe`'s
   precedent) with a pinned-literal fallback, and the red-team drives a deployed tree with the
   table deleted. The cost is one hand literal kept on purpose, held equal to the table by a
   test, and a once-a-session line saying the table is missing.

## Decisions (the operator's answers to the authoring questions, 2026-10-06)

The operator answered all thirteen authoring questions on 2026-10-06. Each answer is recorded
with its reason so the executor does not re-ask. Re-open one only on a measurement that
falsifies its reason, and re-raise with that measurement.

Two answers carry a condition the executor measures: 5 (on 0-D) and 6 (on 0-H). The measured
condition decides them; it is not a new question. Answers 1, 3 and 10 were the operator's own
calls. The rest accept the authoring recommendation.

1. **One flat `dependency_dirs` key, no `[stack]` table.** The operator's call. Commands stay
   in `[extra_actions]`. Reasons:
   - *Measured:* a `[stack]` table is invisible to both hook-reader arms
     (`_hook_utils.read_toml_string_list`'s `tomllib` arm and its regex arm), and the engine
     warns that `stack` is an unknown key. The same keys written flat are read by both
     (Appendix B drive 6).
   - `source_extensions` already shipped flat in #121.
   - `test` and `lint` already have a home: `[extra_actions]`, which #121 made the first source
     for `/preflight` and the settings rules.
   - `examples/espalier.toml` keeps `[extra_actions]` last, because every key below a header
     belongs to that table.
   - `docs/CONVENTIONS.md` ("`espalier.toml` adopter customization") states the convention:
     "Schema is flat top-level keys."
   - A second command home is the rival-store shape
     (`memory/grep-for-a-sibling-store-before-building-a-rival.md`). With `DEF-1094`'s proposed
     `[gates]` and `DEC-35`'s proposed `[stop_gate]`, it would be the fourth.
2. **No `package_manager` key.** `package.json`'s `packageManager` is the declaration Node tools
   already read, and `[extra_actions]` overrides any single command. Two lockfiles of different
   managers resolve to `npm`, plus a `doctor` warning that names both remedies (2-A).
3. **Stop Gate 1 stays out of this pack, with `DEF-949` step 4 and `DEC-35`.** The operator's
   call. Gate 1 is a pytest gate by design. Whether it runs a non-pytest command, and from which
   committed home, is that fork's decision. This pack hands the fork argv templates and a
   correct `test_commands`.
4. **The six scanner walk lists are pinned now (4-B).** Each is pinned as a superset of the
   table's dependency and output directories, the forced-twin precedent. Retiring the
   scanners' no-`espalier`-import rule is **its own question and not in this pack's scope**:
   it is candidate row 3. Its stated reason (a `getsource` copy into target repositories) has
   no production caller (measured by grep), but it is an architecture rule, so it is decided
   apart from this unit of work.
5. **The fingerprint's languages equal the hooks' source set**, so `.h`, `.swift` and `.scala`
   join the fingerprint (3-A's widening commit). The condition: 0-D (3) shows no unexpected
   verdict moves, meaning none outside the tests that pin today's map. If it does, keep the
   per-suffix bit and re-raise with the count. Reason: one set is the simpler model, and a
   Swift repository reading as "no language" is the same defect `.mjs` was.
6. **The `go` and `rust` stack cells are proven in this pack (3-F).** The condition: 0-H's cost
   check passes (the module's serial wall time stays under 180 s). If it fails, they stay
   install cells and their gap reasons say so. Reason: it answers the adopter-axes pack's open
   question with a session proof instead of a ruling, at about 10 s more per module. It is
   also the friendliness-at-equal-cost case the standing preference names.
7. **`DEF-971` folds into lane C (4-D).** It edits the constant 4-A derives
   (`analyze.DEFAULT_SKIP_PARTS`) and the one function that reads it (`analyze._iter_files`). Its
   probe moves when 4-A lands either way, and two lanes on one constant is the
   shared-container hazard `memory/task-packs.md` records. It keeps its own oracle and lands
   after 4-A.
8. **Every table manifest and lockfile at the root is plan-gated (3-C):** `go.mod`, `go.sum`,
   `Gemfile` and `bun.lockb` among them. All four are exempt today while `requirements.txt` is
   listed (Appendix B drive 3). That is the parity the list already intends for Python. The cost
   is one more deny for a Go adopter, relieved by the plan they already need.
9. **`/preflight`'s fallback ladder is pinned against the table, not read at runtime (2-E).** A
   runtime read moves `command -v` into `shutil.which`, which resolves differently on Windows
   (`PATHEXT`; extensionless stubs), and it gains nothing the pin lacks.
10. **`scope_walker.INCLUDED_EXTS` joins the table (3-E).** The operator's call, and it
    **reverses the row's scope-out**. The row declared `scope_walker` one of six purpose-scoped
    suffix sets that stay out by declaration. Its mechanism is a walk gate, but its purpose,
    finding the references to a pack's symbols, is stack-shaped. Measured: on a Node tree,
    `/scope-check`'s walk does not see `.mjs` or `.ts` files at all (Appendix B drive 4).
    `/scope-check` ships to adopters. The other five suffix sets stay out, each verified under
    *Scope (out)*.
11. **The row's `format` column is dropped.** No non-Python consumer exists: the only formatter
    wiring is `harness_config._build_hooks`, which keys on a structurally parsed
    `pyproject.toml`. A column with no reader is a population nothing checks.
12. **`uv` and `poetry` (Python package managers) are out.** The row is about `npm`, and switching
    the inferred `pytest -q` to `uv run pytest -q` would change every Python adopter's default.
    It is candidate row 4.
13. **Test-writer's static `Bash(pytest *)` stays.** `.claude/agents/test-writer.md` is the source
    of truth **and** this repository's own agent, so removing the rule removes it here too.
    `harness_config.render_agent_tools` only appends, so the Python line could not stay as it
    is. On a Node tree the rule is harmless, and the line also keeps `Bash(python *)`, which
    the harness's own tools need. It is candidate row 9.

## Lane split (kept by the operator, 2026-10-06)

Three lanes, run one after another, each with its own Task 0 slice, pre-flight and red-team:

- **Lane A — package manager** (the user-visible leg): Task 0 in full, 1-A,
  1-B (seeded with today's population), 2-A to 2-E. The `DEF-976` re-pin happens before its
  first edit.
- **Lane B — source and manifests:** 3-A to 3-F.
- **Lane C — dependency directories:** 4-A to 4-E (with `DEF-971`, Decision 7). The
  ratchet reaches zero, and the row is struck.

Serial, not parallel. All three edit `espalier/analyze.py`, `tools/cc/hooks/_hook_utils.py`,
`tests/test_forced_copy_parity.py`, the ratchet's baseline and the ledger. Each later lane
re-reads those at the head it lands on (`memory/task-packs.md`, the section on why
"independently landable" is not "order-free").

## Cross-pack coordination

Added at execution (execution 0-A, checklist item 3).

- **The adopter-axes pack** (`task-packs/TP-468-adopter-axes.md`, in flight) edits
  `tests/_stack_trees.py`, `tests/_axis_registry.py`, `tests/test_axis_registry.py`,
  `tests/test_stack_trees.py` and the session test. It also raises `PROVEN_FLOOR`. Whichever
  lands second re-reads those files at its head and raises the floor from the value it finds
  (2-D says "by two", not "to 4").
- **`lane/ps-native-delete-spellings`** ran beside lane A on the same box. It edits
  `tools/cc/hooks/write_guard.py`, `_bash_patterns.py`, `_speedbump.py`, `_denial_reasons.py`,
  their tests and `docs/HOOKS.md`, and possibly one hunk of `docs/SHARP_EDGES.md`. Lane A
  touches none of those files except `docs/SHARP_EDGES.md`, where it changes three
  number-words of the mirror-row census only. Lane C's 4-E marker on
  `_bash_patterns.SAFE_EPHEMERAL_DIRS` is a one-line edit of a file that lane owns, so lane C
  re-reads it at its own head.

## Upstream consumed, downstream fed

- **Consumed from the adopter-axes pack:**
  - `tests/_stack_trees.py` (`adopter-node`, `adopter-node-pnpm`, `adopter-go`, `adopter-rust`);
  - `tests/_adopter_tree.py::build_adopter_tree(stack=..., tree=..., branch=...)`;
  - `tests/_axis_registry.py`'s stack cells.

  #121's `tests/test_node_adopter_defaults.py` is the oracle module this pack widens. The
  adopter-axes pack's 2-C session driver, if it lands first, may replace the session test as
  the proof. Neither weakens the other.
- **Fed to:**
  - `DEC-35` and `DEF-949` step 4: argv templates and a correct `test_commands`.
  - `DEF-1094`: the precedent that a command's committed home is `[extra_actions]` until that
    row decides otherwise.
  - `DEF-549`: the mirror-pinned pair (Risk 6).

## Files touched

- **New:**
  - `tools/cc/_stack_table.py`
  - `espalier/_stack_table.py` and `espalier/_vendor/cc/_stack_table.py` (by the sync
    script)
  - `tests/test_stack_table.py`
- **Added at execution** (execution 0-A; the obligations 1-A and 2-A name):
  - `espalier/surface_impact.py`, `docs/CONVENTIONS.md`, `cc/PACK_MANIFEST.txt`,
    `tests/test_managed_inventory.py`
  - `espalier/diffing.py`, `docs/schemas/repo_fingerprint.schema.json`, `tests/test_diffing.py`,
    `tests/test_documented_claims.py`
- **Modified:**
  - `tools/cc/hooks/_hook_utils.py`, `tools/cc/hooks/plan_guard.py`,
    `tools/cc/reflect_protocol.py`, `tools/cc/sister_site_probe.py`, with their vendored copies
  - `espalier/analyze.py`, `espalier/_safe_walk.py`, `espalier/reflect_protocol.py`,
    `espalier/repo_mode.py`, `espalier/settings_profiles.py`, `espalier/harness_config.py`,
    `espalier/cli.py`, `espalier/config.py`, `espalier/models.py`,
    `espalier/mirror_registry.py`, `espalier/managed_paths.py`, `espalier/scope_walker.py`
    (Decision 10), `espalier/doctor.py` (the ambiguous-lockfile warning)
  - `espalier/scanners/exceptions.py`, `godfiles.py`, `perf_smells.py`, `prints.py`,
    `test_loosening.py`, `encoding_contracts.py` (the five names)
  - `scripts/sync_vendor_cc.py`
  - `README.md` and `docs/QUICKSTART.md` deploy-inventory regions (by
    `scripts/generate_doc_regions.py`)
  - the tenth mirror row: `tools/cc/hooks/_reinject.py` (its advisory), the number-word in
    `CLAUDE.md`, `.claude/CLAUDE.md`, `tools/cc/CLAUDE.md`, `docs/SHARP_EDGES.md` and
    `scripts/sync_github_workflow_asset.py`, `scripts/derived_population_census.py`, and the
    per-row table in `memory/asset-mirroring.md`
  - `tests/_stack_trees.py`, `tests/_axis_registry.py`, `tests/test_stack_trees.py`,
    `tests/test_node_adopter_defaults.py`, `tests/test_forced_copy_parity.py`,
    `tests/test_safe_walk.py`, `tests/test_plan_guard.py`, `tests/test_config.py`,
    `tests/conftest.py` (`_MARKER_RULES`)
  - `espalier/_vendor/selfcheck_tests/` (by the sync script)
  - `examples/espalier.toml`, `README.md` ("Honest scope" and the profile row),
    `docs/HOOKS.md` (where it names the source-extension set), `CHANGELOG.md`
  - `task-packs/FORWARD_LEDGER.md`, `task-packs/LEDGER_PROBES.json`
- **Unmodified on purpose:**
  - `tools/cc/hooks/stop_gate.py` (Scope (out))
  - `tools/cc/hooks/_bash_patterns.py::SAFE_EPHEMERAL_DIRS` (purpose-scoped; marker only)
  - `.claude/commands/preflight.md` (pinned, not rewritten, under Decision 9)
  - `.claude/agents/repo-analyst.md` (agent instructions; a candidate row)
  - `.claude/agents/test-writer.md` (Decision 13)

**Authoring fence check** (`python scripts/check_pack_fences.py` on this file, from #121's
tree, and again on `main` `80e575b` with the same result): 5 python fences, 1 checked, 3 untagged (the appendix instruments), and one BLOCK,
`declared target is missing: tools/cc/_stack_table.py`. That target is the new file 1-A
creates. The adopter-axes pack carries the same new-file BLOCK for `tests/_hook_runner.py`.
The checker does not read `### Added-paths` (candidate row 8).

**Authoring scope-check** (2026-10-06, `python -m espalier.cli scope-check` on this file, run
from a scratch worktree of #121's head `7987961`, and again on `main` `80e575b` with the same
list): exit 2. The gap lines left are:

- prose and record mentions: `docs/`, `memory/`, `bench/` corpus and results, other packs,
  folder `CLAUDE.md` files;
- the `HarnessConfig` readers that pick up a new field by derivation (`espalier/diffing.py`'s
  `_CONFIG_KEYS`, `espalier/profiles.py`, `espalier/cleanup.py`, `espalier/managed_inventory.py`);
- the `fingerprint_repo` and `RepoFingerprint` readers, which an additive field leaves as they
  are (`espalier/self_hosting.py`, and prose in the code-reviewer and test-writer agent bodies
  and their mirrors);
- the purpose-scoped siblings' comments (`espalier/proofs.py`, `espalier/surface_impact.py`,
  `espalier/pack_manifest.py`);
- `bench/run_benchmark.py`, which reads `detect_tests` on this repository's Python tree
  (2-B's equality keeps it unmoved);
- `scripts/derived_population_census.py`, `scripts/symbol_census.py` and
  `scripts/handoff_mechanics.py` (self-host);
- `tools/cc/hooks/stop_gate.py` (a docstring naming `detect_tests`; Scope (out)).

Pre-flight 0-B re-runs it on the live tree. Accept the gap with this reason only if the list
is unchanged.

## Sub-task ordering

0. **Pre-flight**, the four gates in `memory/task-packs.md`, per lane immediately before it
   executes:
   - 0-A: `code-reviewer` with `tools/cc/pack_artifact_checklist.md`;
   - 0-B: `espalier scope-check task-packs/TP-469-stack-registry.md`;
   - 0-C: `python tools/cc/sister_site_probe.py --json`;
   - 0-D: `espalier surface-impact task-packs/TP-469-stack-registry.md`.

   Then `python tools/cc/execution_plan.py create`, and maintenance mode set in the parent shell
   for the `tools/cc/` and `espalier/` edits (both are protected zones on this repository).
1. **Task 0** (0-A to 0-H). Checkpoint: the verdicts in `reports/tp469/`. Stop on any
   refutation.
2. **Lane A:**
   - the re-pin;
   - 1-A, then 1-B (checkpoint: `pytest -q tests/test_stack_table.py tests/test_vendor_cc_parity.py`);
   - 2-A, then 2-B (checkpoint: the unit table and the probe);
   - 2-C, then 2-D (checkpoint:
     `pytest -q tests/test_node_adopter_defaults.py tests/test_stack_trees.py tests/test_axis_registry.py tests/test_selfcheck_tests_parity.py`,
     serially);
   - 2-E;
   - 5-A on the lane, one fix batch, the tier the diff earns, ship.
3. **Lane B:**
   - 3-A, 3-B and 3-D as equality commits first, then each widening (checkpoint per widening:
     its differential's files);
   - 3-C, 3-E, 3-F;
   - 5-A, fix batch, tier, ship.
4. **Lane C:**
   - 4-A, 4-B, 4-C (checkpoint: `pytest -q tests/test_safe_walk.py tests/test_forced_copy_parity.py tests/test_scanners.py tests/test_config.py`);
   - 4-D (Decision 7);
   - 4-E: the ratchet at zero, `--strikes`, the strike of `DEF-976`;
   - 5-A, fix batch, tier, `/handoff`.

## Estimated effort

| Step | Estimate |
|---|---|
| Task 0 | 3 h (0-G is reading; 0-C and 0-D are the drives in Appendix B) |
| 1-A and 1-B | half a day (the tenth mirror row's four obligations and the deploy roster are the slow part) |
| 2-A to 2-E | 1 day |
| 3-A to 3-F | 1 day (3-F adds trees and stubs) |
| 4-A to 4-E | 1 day (more with `DEF-971` folded) |
| Red-team and fix batches, three lanes | 1.5 days |

Total about five days of lane time. Pack budgets on this tree have run about 2.7 times over on
the one pack measured, so read this as a floor.

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date: 2026-10-06 (authored against #121's tree, re-verified on `main` `80e575b`; not executed)

## Appendix A — the census instrument

A measuring instrument, not a deliverable. Save it outside the tree (for instance
`<scratch>/tp469_census.py`) and run it from the repository root with any Python 3.10 or later.
It imports nothing from the tree.

Output, summary lines (the per-site lines are printed beneath 1b, 2 and 3):

| Line | `2891d7a` (row filed, 2026-09-30) | `5f0b6ae` (`main` before #121) | `7987961` (#121), and `80e575b` (`main` after it merged) |
|---|---|---|---|
| 1a dependency-dir lists, the row's method | 16 lists, 11 variants, 15 lack a name, 13 lack `target` | same | same |
| 1b the same, tuples too | 20, 15, 19, 17 | same | same |
| 1c scanner copies | 5 `DEFAULT_EXCLUDE`, identical; `encoding_contracts.PRUNE_DIRS` apart | same | same |
| 2 source-extension literals | 3 (`SUFFIX_TO_LANGUAGE` 14, `detect_ui_surface` 8, `SOURCE_LANGUAGE_EXTENSIONS` 17) | same | 2 (21, 24) |
| 3 manifest-name literals | 5 | same | same |
| 4 lockfile or `packageManager` constants | none | none | none |
| 5 command-template constants | 57 in 16 files | same | 62 in 17 files |
| 6 shipped `.claude/` bodies naming a dependency dir or a lockfile | `repo-analyst.md` 10 | same | `repo-analyst.md` 10, `preflight.md` 1 |

```python
"""Stack-registry census: re-derives every count the stack-registry pack cites.

Stdlib only; run from the repository root with any Python 3.10+. Reads source
and never imports the tree. Production roots: espalier/ (minus espalier/_vendor/,
the two mirrors), tools/cc/ and scripts/. A "literal" is a set, list or tuple
display, a frozenset()/set()/tuple()/list() call over one, or a dict display's
keys, whose elements are string constants.
"""
import ast
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOTS = ("espalier", "tools/cc", "scripts")
SKIP = ("espalier/_vendor/",)
DEP_KEYS = {"node_modules", ".venv"}
LANG_CORE = {".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".go", ".rs", ".java",
             ".rb", ".php", ".c", ".cpp", ".cs", ".kt", ".swift"}
MANIFESTS = {"pyproject.toml", "package.json", "Cargo.toml", "go.mod", "pom.xml",
             "build.gradle", "setup.py", "setup.cfg", "requirements.txt", "Pipfile",
             "Gemfile", "composer.json"}
LOCKS = {"package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock",
         "bun.lockb", "bun.lock", "Cargo.lock", "go.sum", "poetry.lock", "uv.lock",
         "Pipfile.lock", "packageManager"}
CMD_RE = re.compile(r"^(npm|pnpm|yarn|bun|npx|cargo|go|pytest|make)( |$)")


def parse(p):
    try:
        return ast.parse(p.read_text(encoding="utf-8-sig"))
    except (SyntaxError, UnicodeDecodeError):
        return None


def strs(node):
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("frozenset", "set", "tuple", "list") \
            and len(node.args) == 1:
        node = node.args[0]
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        elts = node.elts
    elif isinstance(node, ast.Dict):
        elts = [k for k in node.keys if k is not None]
    else:
        return None
    out = [e.value for e in elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return out or None


def owners(tree):
    names = {}

    def visit(node, label):
        for child in ast.iter_child_nodes(node):
            lab = label
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                lab = child.name if not label else f"{label}.{child.name}"
            elif isinstance(child, (ast.Assign, ast.AnnAssign)) and not label:
                lab = ast.unparse(child.targets[0] if isinstance(child, ast.Assign) else child.target)
            names[id(child)] = lab
            visit(child, lab)
    visit(tree, "")
    return names


dep, src, man = [], [], []
kind = {}
locks, cmds = defaultdict(Counter), defaultdict(list)
for r in ROOTS:
    for p in sorted(Path(r).rglob("*.py")):
        rel = p.as_posix()
        if rel.startswith(SKIP):
            continue
        tree = parse(p)
        if tree is None:
            continue
        own, seen = owners(tree), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in LOCKS:
                    locks[rel][node.value] += 1
                if CMD_RE.match(node.value) and len(node.value) < 40:
                    cmds[rel].append(node.value)
            s = strs(node)
            if not s:
                continue
            inner = node.args[0] if isinstance(node, ast.Call) else node
            if id(inner) in seen:
                continue
            seen.add(id(inner))
            norm = frozenset(x.rstrip("/") for x in s)
            site = f"{rel}::{own.get(id(node)) or '<module>'}"
            if norm & DEP_KEYS:
                dep.append((site, norm))
                kind[site] = type(inner).__name__
            dots = {x for x in norm if re.fullmatch(r"\.[a-z0-9+]+", x)}
            if len(dots & LANG_CORE) >= 2:
                src.append((site, len(dots)))
            if len(norm & MANIFESTS) >= 2:
                man.append((site, sorted(norm & MANIFESTS)))

dtd = set()
for n in ast.walk(parse(Path("espalier/_safe_walk.py"))):
    if isinstance(n, ast.AnnAssign) and ast.unparse(n.target) == "DEPENDENCY_TREE_DIRS":
        dtd = set(strs(n.value) or [])


def tally(rows):
    return (f"{len(rows)} lists | {len({m for _, m in rows})} variants | "
            f"{sum(1 for _, m in rows if not dtd <= m)} lack a DEPENDENCY_TREE_DIRS name | "
            f"{sum(1 for _, m in rows if 'target' not in m)} lack 'target'")


row_method = [(s, m) for s, m in dep if kind[s] in ("Set", "List", "Dict")]
print("1a dependency-dir lists, the row's method (set and list displays):", tally(row_method))
print("1b the same, tuples too:", tally(dep))
five = [m for s, m in dep if s.startswith("espalier/scanners/") and s.endswith("DEFAULT_EXCLUDE")]
other = [s for s, _ in dep if s.startswith("espalier/scanners/") and not s.endswith("DEFAULT_EXCLUDE")]
print(f"1c scanner copies: {len(five)} DEFAULT_EXCLUDE, identical={len(set(five)) == 1}; other scanner lists: {other}")
for s, m in dep:
    print(f"     {s} | {kind[s]} | n={len(m)} | target={'target' in m} | lacks {sorted(dtd - m)}")
print("2 source-extension literals (>=2 core language suffixes):", len(src))
for s, n in src:
    print(f"     {s} | {n} suffixes")
print("3 manifest-name literals (>=2 manifest names):", len(man))
for s, m in man:
    print(f"     {s} | {len(m)} {m}")
print("4 lockfile / packageManager string constants:", {f: dict(c) for f, c in sorted(locks.items())} or "none")
print("5 command-template string constants:", sum(len(v) for v in cmds.values()), "in", len(cmds), "files")
for f, v in sorted(cmds.items()):
    if f.startswith(("espalier/analyze", "espalier/settings", "espalier/harness", "tools/cc/hooks/stop")):
        print(f"     {f} {Counter(v).most_common()}")
md = Counter()
for p in sorted(Path(".claude").rglob("*.md")):
    t = p.read_text(encoding="utf-8")
    hits = sum(t.count(k) for k in ("node_modules", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "package-lock.json"))
    if hits:
        md[p.as_posix()] = hits
print("6 shipped .claude/ bodies naming a dependency dir or a lockfile:", dict(md))
```

Definitions, stated before the numbers:

- The **row's method** is line 1a, set and list displays. It reproduces the row's 16, 11, 15
  and 13 exactly at the filing commit. Line 1b adds tuples (four more sites:
  `release_noise.TRANSIENT_DIRS`, `strengthen._EXEMPT_PREFIXES`,
  `_bash_patterns.SAFE_EPHEMERAL_DIRS`, `check_pack_fences._RESOLVE_SKIP`).
- "Lacks `target`" is list membership, not a measured walk. Appendix B drive 2 measures walks.
- Line 3 floors the manifest population. `analyze.detect_package_systems`' `if` chain names
  seven manifests and is not a literal.

## Appendix B — the authoring drives

Each drive is saved outside the tree and run from the repository root. Each imports `espalier`
and the test helpers from the working directory. Results at #121's head `7987961` on this host,
reproduced on `main` `80e575b`,
are under each.

**Drive 1 — package manager by lockfile.**

```python
"""Engine inference on the adopter-node rows and their lockfile siblings."""
import io
import sys
import tempfile
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
from _stack_trees import STACKS, write_stack
from espalier import analyze
from espalier.settings_profiles import _workflow_fingerprint_allows
from espalier.harness_config import preflight_command

VARIANTS = {
    "no lockfile": ("adopter-node", {}),
    "package-lock.json": ("adopter-node", {"package-lock.json": '{"lockfileVersion": 3}\n'}),
    "pnpm-lock.yaml": ("adopter-node-pnpm", {}),
    "yarn.lock": ("adopter-node", {"yarn.lock": "# yarn lockfile v1\n"}),
    "bun.lockb": ("adopter-node", {"bun.lockb": "\x00bun"}),
    "bun.lock": ("adopter-node", {"bun.lock": '{"lockfileVersion": 1}\n'}),
}
for label, (row, extra) in VARIANTS.items():
    d = write_stack(Path(tempfile.mkdtemp()), row)
    for name, body in extra.items():
        (d / name).write_text(body, encoding="utf-8", newline="")
    tests = analyze.detect_tests(d)
    acts = analyze.detect_actions(d, tests)
    rules = _workflow_fingerprint_allows({"test_commands": tests, "inferred_actions": acts})
    with redirect_stderr(io.StringIO()):
        pf = preflight_command("test", d)
    print(label, tests, acts.get("lint"), acts.get("build"), repr(pf), list(rules))
```

Result: all six print `['npm test'] ['npm run lint'] ['npm run build'] 'npm test'` and the
six `Bash(npm …)` rules, never a `pnpm`, `yarn` or `bun` rule.

**Drive 2 — dependency directories, read or pruned.** Plant `<name>/pkg/mod.py` and
`<name>/pkg/CLAUDE.md` under `node_modules`, `bower_components`, `jspm_packages`, `.yarn`,
`.pnpm-store` and `target`, with a control `src/app.py` and a root `CLAUDE.md`. Then collect
what each of these reads:

- `analyze._iter_files(d)`;
- `repo_mode.list_repo_files_via_filesystem(d)`;
- `reflect_protocol._walk_router_docs(d)`;
- the paths in `scanners.prints.scan_repo(str(d))`.

Result:

| Walker | Control read | `node_modules` read | Planted directories read |
|---|---|---|---|
| fingerprint | yes | no | `.pnpm-store`, `.yarn`, `bower_components`, `jspm_packages` |
| non-git fallback | yes | no | those four and `target` |
| router walk | yes | no | `bower_components`, `jspm_packages`, `target` |
| `prints` scanner (`DEFAULT_EXCLUDE` shared by five) | yes | no | those four and `target` |

**Drive 3 — the plan gate on root manifests.** In a scratch directory, with
`CLAUDE_PROJECT_DIR` pointed at it:

```bash
python <checkout>/tools/cc/hooks/_explain_path.py <name>
```

Read the `plan_guard` line for each name. Result: `go.mod`, `go.sum`, `Gemfile` and `bun.lockb`
are exempt. `requirements.txt` is "listed root doc/config". `package.json`, `pnpm-lock.yaml`,
`yarn.lock`, `bun.lock`, `package-lock.json` and `Cargo.lock` are "root-level source" by
extension.

**Drive 4 — the scope walk.** `scope_walker.walk_references(d, "parseRoute")` on a tree holding
`src/index.mjs` (the definition), `src/app.ts` (a use), `src/mod.py` and `README.md`. Result:
`['README.md', 'src/mod.py']`.

**Drive 5 — test-writer's line on a Node fingerprint.**

```python
import sys
sys.path.insert(0, ".")  # this checkout's engine, not an installed one
from espalier.harness_config import agent_runner_rules, render_agent_tools
```

Run `render_agent_tools` on `.claude/agents/test-writer.md`'s body with
`agent_runner_rules(["npm test"])`. The `sys.path` line matters on a box where `espalier` is
installed editable from another checkout: without it the import reaches that checkout. Result:
`tools: Read, Grep, Glob, Write, Bash(pytest *), Bash(python *), Bash(git *), Bash(npm test), Bash(npm test *)`.

**Drive 6 — the two readers on a table and on flat keys.** Write `espalier.toml` once with a
`[stack]` table holding `source_extensions` and `dependency_dirs`, and once with the same keys
flat. Then call `_hook_utils.read_toml_string_list(d, key)` and the same with `parser=None` (the
regex arm), plus `espalier.config.load_config(d)` under `warnings.catch_warnings(record=True)`.
Result:

- the table: `None` on both hook arms, and the engine warns ``unknown key `stack` is ignored``;
- flat keys: both hook arms return the lists, and the engine reads `source_extensions` and warns
  ``unknown key `dependency_dirs` is ignored``. That is expected until 4-C.

## Candidate rows (reported, not filed)

Each would be filed by the operator or by the lane that meets it. None is filed by this pack's
authoring.

1. `/scope-check`'s reference walk is blind to non-Python source
   (`espalier/scope_walker.py::INCLUDED_EXTS`). Measured, drive 4. Folded into 3-E by
   Decision 10.
2. Root `go.mod`, `go.sum`, `Gemfile` and `bun.lockb` edits need no plan while
   `requirements.txt` does (`tools/cc/hooks/plan_guard.py::PLAN_REQUIRED_ROOT_FILES`). Measured,
   drive 3. Folded into 3-C by Decision 8.
3. The scanners' no-`espalier`-import rule rests on a `getsource` copy no production code makes
   (`tests/test_scanners.py::TestScannerSelfContainment`). Measured by grep. Not in scope:
   Decision 4 makes it its own question.
4. A Python adopter with `uv.lock` or `poetry.lock` is told `pytest -q`, which may not be on the
   session's PATH outside the environment. Not measured. Decision 12.
5. Gate 2's docs evidence reads `*.md` and `*.mdx` only, so a Sphinx project's `.rst` edits never
   relieve it (`tools/cc/hooks/subagent_stop.py::_changed_markdown`). Read, not driven.
6. `.claude/agents/repo-analyst.md`'s shell fences hand-list manifests and lockfiles (no
   `bun.lock`) and dependency excludes. Read.
7. `analyze.detect_actions` offers `scan` on a Python manifest, and
   `harness_config._detect_actions` offers it on a Python language. A repository with a
   `requirements.txt` and no `.py` file gets two answers. Read, not driven; folded by 3-D.
8. `scripts/check_pack_fences.py` reports a `target=` naming a file the pack declares under
   `### Added-paths` as a BLOCK ("declared target is missing"). It does so on this pack and on
   the adopter-axes pack. Measured.
9. Test-writer's shipped `tools:` line carries `Bash(pytest *)` on every stack. The deploy only
   appends the stack's runner (`harness_config.render_agent_tools`). Measured, drive 5;
   Decision 13.
