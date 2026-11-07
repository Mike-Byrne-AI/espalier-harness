# TP-706 — The floor moves to 3.11: the end-of-life interpreter leaves, and the TOML tax it levied stops

## Status

- Version target: the first release after Wave 1 lands. Its metadata says `Requires-Python
  >=3.11`, so `pip` on a 3.10 host resolves to the last release that allowed 3.10 on its own
  (the tree's version today is `0.8.0b2`, read from `pyproject.toml`; the release step names
  the actual last one in the README, never this pack).
- Type: modernization (the interpreter floor) + cleanup (the code that exists only for the
  old floor) + CI (two cells leave the required set).
- **Kind: PACK, at conceptual depth.** Each wave names its oracle, the class of edits by the
  command that derives its members, and the gate that reds until every member moved. No
  copy-ready fence is prescribed: every member is enumerated by a command and the same
  change lands at each, so the executing seat's plan carries the per-file edits
  (`blueprint-authoring`: be exact about how to measure, provisional about what to write).
- State: DRAFT — authored 2026-11-04 local by the dispatcher seat `air` on the operator's
  word of the same evening ("ok, lets make a conseptual level task pack for raising the
  floor to 3.11"), after the census and the measurements the Motivation quotes. Assigns
  nothing until the operator approves the pack itself.
- Reasoning review at authoring (the `failure-mode-reviewer`, fresh context, 2026-11-04
  local): REQUEST CHANGES, 1 regression, 8 gaps, 5 rough edges, every one verified against
  the tree and folded below. The two that changed the pack: `init` wires a below-floor
  interpreter on purpose today ("Wiring it anyway so the blocking guards keep working",
  `espalier/cli.py`, the operator's decision of 2026-09-03, pinned in
  `tests/test_python_floor.py`), which at a floor the hooks cannot run under becomes a
  lockout of every tool call, so the decision is re-opened in Task 0; and `ruff` takes its
  syntax target from `requires-python`, so `ruff check .` is today's tree-wide 3.10 syntax
  gate and Wave 1 would have switched it off (driven by the reviewer with ruff 0.16.8:
  `except*` and `*Ts` reported at `>=3.10`, nothing at `>=3.11`), so Wave 1 keeps it
  per-file for `tools/cc/` and 2-D is built on it rather than on `ast.parse`.
- **Operator decisions this pack records as made** (2026-11-04): Python 3.10 leaves the
  supported set; the floor becomes 3.11 (the operator's word above, given against the
  2026-11-04 census and the recommendation that followed it).
- **Operator decisions this pack asks for**, each a line below: the Task 0 threshold on the
  download share (pre-registered by the author, movable); **what `init` does when the only
  interpreter it finds is below the floor** (Task 0: refuse to wire and name the remedy, the
  author's recommendation, or wire and say "lockout"; the 2026-09-03 decision to wire
  anyway rested on hooks that could still run on 3.10, which after Wave 2 they cannot); the
  branch-protection edit, which is GitHub-side and the operator's hand (0-B); whether Wave
  2 rides the same release as Wave 1 or the one after (Sub-task ordering).
- Executed by the seat `air-work`: Wave 1 on `lane/build-the-floor-moves-to-3-11` (#504,
  merged 2026-11-07 as `8dd10c01`); Waves 2 and 3 on
  `lane/build-the-shims-go-the-hooks-speak-the-floor` (the dispatcher's assign
  `20261107T113820Z-air-bcfd9d`). Wave 2's 0-A review (code-reviewer: no BLOCK, four WARNs)
  was folded in just in time, each marked *(0-A, 2026-11-07)* below; the dispatcher's rulings
  on that lane are `20261107T131309Z-air-b4bfb8` (the banner's floor warning survives, 2-C)
  and `20261107T183723Z-air-2a3cad` (§C59 stays in place, empty, 3-A).

## Motivation

**The version is dead upstream.** Python's own release-cycle data lists 3.10 as
`end-of-life` on `2026-10-01` (measured 2026-11-04:
`curl -s https://peps.python.org/api/release-cycle.json`, the `3.10` entry; 3.11 is
`security` to `2027-10`, 3.12 to `2028-10`).

**Nobody observed runs the harness on it.** Three reads, each with its command:

- PyPI downloads by interpreter minor for `espalier-harness` over the service's window
  (measured 2026-11-04: `curl -s "https://pypistats.org/api/packages/espalier-harness/python_minor?mirrors=false"`,
  the `data` rows summed by `category`): 284 downloads, 240 of them reporting no version;
  of the 44 that did, 3.11 19, 3.14 10, 3.12 8, 3.10 5, 3.9 2.
- In the repository's own record (the 2026-11-04 census, an `Explore` agent's read at
  `707a222f`): the only Python 3.10 interpreters anywhere in it are the CI cells and a
  `uv` build on the Air (`DEF-915`, `DEF-4024`: "the floor interpreter on this host (uv's
  3.10.21)"). The "Python 3.10 teammate" of `DEF-1008` and the "Python 3.10 installer" of
  `DEF-1007` are hypotheticals the rows imagined, not users anyone saw. No adopter tree
  under `examples/` pins an interpreter.
- The one population that still runs 3.10 by default is stock Ubuntu 22.04, whose
  `python3` is 3.10 and whose standard support runs to 2027-04 (external, secondary sources,
  read 2026-11-04; the authoritative check is Ubuntu's release page). Task 0's second
  oracle reads the operator's own adopter trees for it.

**The CI case is compute, not wall time.** Over the 42 full-tier runs among the newest 45
green `test.yml` runs since 2026-10-30 (measured 2026-11-04:
`gh run list --workflow=test.yml --created ">=2026-10-30" --status completed --limit 200
--json databaseId,conclusion,createdAt`, then `gh run view <id> --json jobs` per run,
reading the five `test (3.x)` jobs' `startedAt`/`completedAt`; a full-tier run is one with
a cell past 20 min):

| Measure | Figure |
|---|---|
| Wall (the slowest of the five parallel cells), median | 49.1 min |
| Wall without the 3.10 cell, median | 47.4 min |
| Saving if the 3.10 cells left: median / p75 / max | 0.4 / 2.5 / 9.6 min |
| Runs where 3.10 was the slowest cell | 22 of 42 (3.14 in 10, 3.12 in 8) |
| `clean-checkout (3.10)`, the floor cell, on the last four green runs | 60 to 98 min |

So the saving is two of ten test cells' minutes per run, one release-gate leg (about 25 min
alone on the box, root `CLAUDE.md` "Build & Test") and the 3.10 column of the release
matrix. The floor cell of `clean-checkout.yml` moves to 3.11 and costs the same. A pack
that promised wall time here would be refuted by its own table.

**The maintenance case is the real one, and it is structural.** The hooks and the
standalone tools under `tools/cc/` run under the adopter's system interpreter with no
dependencies installed, and 3.10 has no `tomllib`. So every configuration key a hook or a
tool reads from `espalier.toml` or `pyproject.toml` carries, beside the real parser, a
hand-rolled line scan or regex arm for the interpreter that has none, and the tests for
that arm. The census of 2026-11-04 (the agent's read by file and line at `707a222f`,
re-derived mechanically by the Reach oracle below) found:

- **24 code sites** that exist only because 3.10 lacks `tomllib`, `importlib.resources.abc`,
  or a newer `venv`/`fromisoformat`: `espalier/_compat.py` and the `is None` arms of its
  five callers; `tools/cc/hooks/_hook_utils.py::_toml_parser`, `::read_toml_table`'s
  `tomli` retry, `::_regex_extract_string_list`, `::_read_toml_flat`'s no-parser arm,
  `::adopter_protected_prefixes`' degraded-reader message and
  `::_project_name_from_pyproject`; `tools/cc/ci_guard.py::_ci_project_name_from_pyproject`;
  `tools/cc/hooks/plan_guard.py::_read_adopter_exempt_config`;
  `tools/cc/hooks/stop_gate.py::_declared_test_commands`;
  `tools/cc/ship.py::handoff_push_setting`; `tools/cc/ledger_row.py::read_id_blocks`; a
  dispatcher-name scan in `tools/cc/mail.py` and a fragments scan in
  `tools/cc/_record_fragments.py`; `scripts/record_snapshot.py`,
  `scripts/wheel_smoke.py::_read_pyproject_version`, three scripts' `tomli` fallbacks,
  `scripts/fresh_clone_gate.py::default_interpreter` and `::make_venv`'s 3.10 branch,
  `espalier/assets.py`'s `Traversable` fallback, `espalier/cli.py`'s no-parser probe arm,
  `bench/end_to_end/assertions.py`'s fraction padding.
- **19 test sites** that exist only for 3.10: the whole of
  `tests/test_tomllib_import_contract.py` (registered in `tests/conftest.py`), five
  `tomllib`-version forks, and fourteen no-parser or `tomli`-stub arms across the suite.
- **About 75 hand edits** to raise the floor, 40 of them gated or declared (two
  `MIN_PYTHON` copies, `pyproject.toml`, four workflow matrices, fifteen resolver lines in
  shipped `.claude/` bodies, nine pinned test literals, the front-door "Python 3.10+"
  sentences, the checklist's gate lines and its required-checks list, and branch
  protection on GitHub) and 35 prose, comments and strings that would read false.

The tax is still accruing: the newest line scan was written in `TP-704`'s lane "since the
3.10 floor has no tomllib" (`task-packs/TP-704-the-threshold-handoff.md`), and
`espalier.toml`'s `[id_blocks]` comment pins that table to one inline row per seat because
its reader is a line scan for the same reason. `docs/CONVENTIONS.md`'s section "`tomllib`
import goes through `espalier._compat`" says dropping 3.10 "is a one-line edit in
`_compat.py`"; the census says 75. And the path the arms exist for, a real 3.10 install
with `tomli` absent, is one `memory/CONVERGENCE_LEDGER.md` has carried as never executed
for eight to twelve review rounds: code kept alive, untested, for a user nobody has seen.

**Where the 3.10 floor is pinned today** (the places a change must move together, each
with the test that reds when they disagree): `espalier/_python_floor.py::MIN_PYTHON` and
`tools/cc/hooks/_hook_utils.py::MIN_PYTHON`
(`tests/test_python_floor.py::TestTwoCopyParity`); `pyproject.toml`'s `requires-python`
(`tests/test_python_floor.py::TestPythonFloor::test_min_python_matches_requires_python`),
its `tomli` marker and its `[tool.mypy] python_version`
(`tests/test_mypy_config_stays_near_strict.py::test_mypy_config_keeps_near_strict_flags`);
the matrices of `.github/workflows/test.yml` (both jobs), `clean-checkout.yml` and
`release.yml`, the first two held as literals by
`tests/test_required_status_checks.py::test_the_parallel_and_serial_cells_run_their_own_leg`
and `::test_the_gated_sibling_is_not_a_required_check`; the resolver line in fifteen
shipped `.claude/` bodies, derived from the floor by
`tests/_interpreter_hosts.py::shell_resolver_line` and held by
`tests/test_interpreter_hosts.py::TestShellResolverLine`; the front door's "Python 3.10+"
(`tests/test_front_door_numbers.py`); the release checklist's `fresh_clone_gate.py
--python 3.10` lines and its required-checks list (`docs/RELEASE_CHECKLIST.md`; the
Tier-3 `--python <floor>` line is bound to `pyproject.toml`'s floor by
`tests/test_release_checklist_contract.py`, so it reds until the checklist moves; the
required-checks list is bound by
`tests/test_required_status_checks.py::test_every_instructed_check_can_actually_report`,
and no test pins its count); root `CLAUDE.md`'s "Build & Test" gate line; the sixteenth
resolver line in `scripts/run_pack_chain.sh`, which no test holds; the sentence `init`,
`doctor`, the SessionStart banner, `docs/CHEAT-SHEET.md` and `docs/HOOKS.md` share about
wiring a below-floor interpreter anyway (`espalier/cli.py`, `espalier/doctor.py`,
`tools/cc/hooks/session_start.py`), which interpolate the floor and so never red; and
the required status checks on `main` (measured 2026-11-04:
`gh api repos/Mike-Byrne-AI/espalier-harness/branches/main/protection/required_status_checks
--jq '.strict, .contexts'`: `strict` false, 13 contexts, `test (3.10)` and
`test-serial (3.10)` among them).

## Scope (in)

1. **Wave 1 — the floor.** Both `MIN_PYTHON` copies (`espalier/_python_floor.py`,
   `tools/cc/hooks/_hook_utils.py`) to `(3, 11)`; in `pyproject.toml`, `requires-python =
   ">=3.11"`, the `3.10` classifier gone, the `tomli` marker gone, `[tool.mypy]
   python_version = "3.11"`; four-cell literal matrices in `.github/workflows/test.yml`
   (both jobs) and `.github/workflows/release.yml`; `.github/workflows/clean-checkout.yml`'s
   one cell `["3.11"]` with its "floor interpreter" comment kept true; the resolver line in
   the fifteen shipped bodies, regenerated from `tests/_interpreter_hosts.py::shell_resolver_line`
   and synced to the mirrors; every current-promise doc site (classified, Implementation
   1-D) to 3.11; root `CLAUDE.md`'s gate line and `docs/RELEASE_CHECKLIST.md`'s gate lines
   to `--python 3.11`; the checklist's required-checks list to its eleven names; the nine
   pinned test literals (`tests/test_required_status_checks.py`,
   `tests/test_mypy_config_stays_near_strict.py`, `tests/test_python_floor.py`, including
   its negative literal "Install Python 3.10 or newer first", which goes vacuous at a new
   floor unless it is derived from `floor_text()`;
   `tests/test_session_start_interpreter_warn.py`, `tests/test_sync_github_workflow_asset.py`);
   **the syntax gate kept**: `[tool.ruff] per-file-target-version` pinning the five files
   the update deny runs through to `py310` (the 2026-11-07 ruling, 1-G) so `ruff check .`
   keeps refusing 3.11-only syntax where the floor's voice must still parse (1-G); **`init`'s below-floor arm** in `espalier/cli.py` changed
   to the operator's Task 0 ruling, with its pinned test and the four surfaces that repeat
   the sentence (1-H); **the engine's own floor message** as the first statement of
   `espalier/__init__.py` (amended 2026-11-07 by air's ack `7128b9` on request `79c59b`:
   a 3.10 host compiles a whole module before it runs a line, so a check inside
   `cli.py` never prints once `cli.py` takes 3.11 syntax), so a 3.10 host running a `git
   pull`'d clone reads the floor and not a traceback (1-H); a changelog fragment; one
   `README.md` sentence saying the harness needs Python 3.11 or newer (ruling `320c24`:
   no pointer to the last release that allowed 3.10).
2. **Wave 2 — the shims.** The Reach roster to zero: `espalier/_compat.py` imports
   `tomllib` alone (the name stays as the one import site, so `docs/CONVENTIONS.md`'s rule
   stays true); the five callers' `is None` arms go (`espalier/config.py`,
   `espalier/proofs.py`, `espalier/surface_contract.py`, `espalier/analyze.py`,
   `espalier/harness_config.py`); `tools/cc/hooks/_hook_utils.py::_toml_parser` returns
   the stdlib module and the regex arms, the `tomli` retry and the degraded-reader message
   go; each line scan named in the Motivation becomes a `tomllib` read behind the fail-open
   voice rule (`tools/cc/hooks/CLAUDE.md`): `tools/cc/hooks/plan_guard.py`,
   `tools/cc/hooks/stop_gate.py`, `tools/cc/ship.py`, `tools/cc/ledger_row.py`,
   `tools/cc/mail.py`, `tools/cc/_record_fragments.py`, `tools/cc/ci_guard.py`;
   `espalier/assets.py` imports `Traversable` directly; `espalier/cli.py`'s probe loses its
   no-parser arm; `scripts/record_snapshot.py`, `scripts/wheel_smoke.py`,
   `scripts/final_release_matrix.py`, `scripts/proof_tier.py`, `scripts/verify_pins.py` and
   `scripts/fresh_clone_gate.py` lose their fallbacks; `bench/end_to_end/assertions.py`
   its fraction padding; `tests/test_tomllib_import_contract.py` and its `tests/conftest.py`
   row go, replaced by the inverted contract (2-E) in `tests/test_python_floor.py`; the 19
   test-side arms go with the code they tested, or stay where the shape they test survives
   (`tests/test_config.py`'s arm reaches `espalier/_vendor/selfcheck_tests/` through
   `scripts/sync_selfcheck_tests.py`, the `selfcheck-tests` mirror row).
3. **Wave 2 also gives the floor a voice in the hooks** (2-C, 2-D, in
   `tools/cc/hooks/_start_refusal.py` and `tests/test_python_floor.py`): a below-floor
   interpreter running a deny hook is told the floor and a remedy it can act on, by a call
   each deny hook makes right after its first import (never at module load: `_denial_reasons.py`
   and through it `session_start.py` import the same module, and a load-time check would
   put a PreToolUse deny inside a SessionStart); no module under `tools/cc/` imports
   `tomllib` at its top (the import stays inside the reading function), so every hook and
   tool still imports on 3.10 and can speak; and two contracts keep that reachable: ruff's
   per-file syntax target (1-G) and an allowlist of `_start_refusal.py`'s top-level imports.
   This is the pack's one design risk, and the red-team's target.
4. **Wave 3 — the records.** `DEF-1007` and `DEF-1008` struck (their subject, the `tomli`
   dependency, no longer exists) and §C59 retired with them; a note on `DEF-900` (the
   safe-path flag `-P` is a route at 3.11, so its "no route at >=3.10" clause is re-read,
   not closed); the `docs/CONVENTIONS.md` sentence corrected to the measured count and this
   pack's id.
5. **0-B, the GitHub side, the operator's hand:** `test (3.10)` and `test-serial (3.10)`
   leave the required set BEFORE Wave 1's pull request is opened. Order matters: a matrix
   that no longer produces a required check-run parks the pull request on "Expected --
   waiting for status to be reported" with no route to merge but deleting the rule
   (`test.yml`'s own comment above its matrix). Between 0-B and Wave 1's merge the two cells
   still run on `main`'s unchanged matrix and are simply not required, which loses nothing.

## Scope (out)

- **The shims that need 3.12 or later, not 3.11.** `rglob` following directory symlinks
  (3.10 to 3.12), `Path.exists` re-raising EACCES (3.10 to 3.13, the class `DEF-579`
  names), `shutil.rmtree(onexc=)`, `tarfile`'s `data_filter`, the f-string backslash rule,
  the `ast` per-character splitter on 3.10 and 3.11, the NUL-byte `ValueError` on 3.10 and
  3.11: a 3.11 floor removes none of them. They stay, and `DEF-579` stays open.
- **The eleven `.replace("Z", "+00:00")` lines before `fromisoformat`** (3.11 accepts `Z`):
  harmless, uncommented, and a sweep nobody asked for. Named so a later pass can find them:
  `git grep -n 'replace("Z", "+00:00")'`.
- **`espalier.toml`'s `[id_blocks]` shape.** The reader changes in Wave 2; the file keeps
  one inline table per seat. Expand, then contract (Core Rule 15): a later row may relax
  the format once every checkout reads it with a parser.
- **A 3.10 interpreter kept in CI for the syntax-floor check.** None: `ast.parse(source,
  feature_version=(3, 10))` makes the check on any interpreter (driven 2026-11-04 on the
  Air's 3.14.7: an `except*` fixture is rejected with "Exception groups are only supported
  in Python 3.11 and greater").
- **`scripts/fresh_clone_gate.py::default_interpreter`'s venv-of-venv rule.** Its 3.11+
  branch is the one that stays right; whether its 3.10 branch is deleted in Wave 2 is the
  executing seat's call against the gate's own tests, not a requirement here.
- **The record surfaces.** `CHANGELOG.md`'s history, `docs/session-archive.md`,
  `memory/CONVERGENCE_LEDGER.md`, the ledger rows' prior text (`DEF-4032` names the
  `clean-checkout (3.10)` leg; `TP-704`'s sentence), the session-log rows: records, not
  edited (Core Rule 13; classify against
  `tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS` before counting a stale
  "3.10" as a defect). The convergence ledger's never-executed 3.10 path closes at its next
  round's row, written by that round.
- **`.github/workflows/harness-guard.yml` and its asset copy.** Already pinned to 3.11.
- **Raising the floor past 3.11.** 3.11 is the lowest interpreter with `tomllib`, is
  supported upstream to 2027-10, and is the stock `python3` of Debian 12 (external,
  probable). A further move is its own decision with its own census.
- **`DEF-1147`.** Its subject is what `doctor` and three docs say about a wired interpreter
  that answers and cannot start; the floor figure in those docs changes with the floor, the
  row does not close.

## Task 0 — Verify

Three oracles; the first two can end the pack.

**Oracle A, the users (measured at execution, not read from this pack):**

```bash
curl -s "https://pypistats.org/api/packages/espalier-harness/python_minor?mirrors=false" \
  | python3 -c "import json,sys,collections; c=collections.Counter(); [c.update({r['category']: r['downloads']}) for r in json.load(sys.stdin)['data']]; print(sorted(c.items(), key=lambda kv: -kv[1]))"
```

The refuting result: 3.10 at or above one fifth of the version-reporting downloads (every
category but `null`). The authoring read was 5 of 44. The threshold is the author's
pre-registration and the operator may move it; what it may not do is move after the read.

**Oracle B, the operator's own adopter trees.** The author's record (machine-local
auto-memory, dated 2026-10-01, not the tree: unverified) says three adopter trees run from
clone installs, one of them a tester's the operator cannot read; the harness's hooks run
under whatever interpreter their `.claude/settings.json` names, in the exec form the
harness writes (`command` is the bare interpreter, `args` holds any launcher flag and the
script). On each box, in each tree the operator can reach:

```bash
python3 -c "import json,subprocess; h=json.load(open('.claude/settings.json'))['hooks']['PreToolUse'][0]['hooks'][0]; argv=[h['command']]+[a for a in h.get('args',[]) if a.startswith('-')]; print(argv, subprocess.run(argv+['--version'],capture_output=True,text=True).stdout.strip())"
```

*(fix shape, untested: the layout is the one this checkout's settings file holds, read
2026-11-04 by the reviewer; `command` is a raw path, never split, so a Windows path with a
space survives; a launcher's `-3` rides `args`.)* The refuting result: a tree whose hook
interpreter is 3.10 and which the operator says will not move. The pack then stops; a tree
that moves is a line in the operator's hand, not this pack's work. A tree the operator
cannot read is named in Landing as unread, never counted as clear. An editable clone kept
current by `git pull` never re-reads `Requires-Python`, which is why Wave 1 gives the
engine its own floor sentence (1-H).

**A decision Task 0 carries to the operator, before Wave 1.** Today `init` wires an
interpreter below the floor on purpose ("Wiring it anyway so the blocking guards keep
working", `espalier/cli.py`; the operator's decision of 2026-09-03, pinned by
`tests/test_python_floor.py`; repeated by `doctor`, the SessionStart banner,
`docs/CHEAT-SHEET.md` and `docs/HOOKS.md`). That was right while a 3.10 interpreter could
still run the hooks. After Wave 2 it cannot: a wired 3.10 means every deny hook refuses
every call, which is a lockout, not working guards. The trigger is the pack's own named
population: Ubuntu 22.04 with the engine installed on 3.11 through `pipx` or `uv` and
`python3` on PATH still 3.10. Two shapes, the operator's to pick: **refuse to wire** a
below-floor interpreter and print the remedy (install 3.11 or newer, or `--python <path>`),
the author's recommendation, since a floor the hooks cannot run under is a hard floor; or
**wire and say "lockout"** in the same sentence, keeping the 2026-09-03 shape with its
reason gone. Nothing today reds on the wrong choice: the messages interpolate
`floor_text()`, so 1-H adds a row whose below-floor stub asserts the new wording.

**Oracle C, the size of the tax (cannot end the pack, said so the executing seat does not
invent a reason):** the Reach command below, at the lane's base. A roster smaller than the
census's 34 files is a smaller Wave 2, never a reason to keep an end-of-life interpreter.

**The exit.** Stop and re-raise to the operator with the three reads. The approval was
given against "no observed user" and "a tax still accruing"; a read that shows a user
takes the approval with it.

**What was already driven** (2026-11-04, the dispatcher seat): the release-cycle read, the
PyPI read, the CI measurement, the required-checks read, the `feature_version` probe, and
the Reach grep (34 files, 66 lines at `707a222f`). The agent's census by file and line is
the one read this pack does not itself re-derive; the Reach oracle is what stands in for
it, and Oracle C is where the two are compared.

## Relevant memory

What has been biting lately: on this surface the defects were in how the floor is
*spoken*, not what it is. The deny hooks' own start refusal was found to be a non-blocking
exit 1 on 16 of 16 drives on 2026-10-16 (`DEF-3008`, recorded in
`tools/cc/hooks/_start_refusal.py`'s docstring); the rewire verb and both `doctor` readers
read a quoted interpreter path as two words until 2026-11-04 (`DEF-4094`). Budget the
red-team for the voice (Wave 2's 2-C and 2-D), not for the number.

| Entry | Where |
|---|---|
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| Classify the surface before measuring it | `memory/classify-the-surface-before-measuring-it.md` |
| Cross-platform Python invocation | root `CLAUDE.md` :: Cross-platform Python invocation |
| Public-facing claims drift when no external witness binds them | `docs/SHARP_EDGES.md` :: Public-facing claims drift when no external witness binds them |
| The mirror whose SoT is the packaged copy | `docs/SHARP_EDGES.md` :: The mirror whose SoT is the packaged copy |
| De-provenancing edits go to the SoT, never the mirror | `docs/SHARP_EDGES.md` :: De-provenancing edits go to the SoT, never the mirror |
| The Measuring Instrument Is a Claim Too | `docs/SHARP_EDGES.md` :: The Measuring Instrument Is a Claim Too |
| Hook authoring | `memory/hook-authoring.md` |

Resolved at authoring time (2026-11-04) by `python3 tools/cc/hooks/_recall.py` with the
queries "python floor minimum interpreter", "tomllib tomli no parser toml reader",
"required status checks branch protection", "mirror sync vendor assets byte parity",
"front door numbers readme quickstart" and "measuring instrument is a claim". No query
surfaced a floor-specific entry; the two rows named above are cited by id instead. Re-run
the queries rather than trusting this list if the pack has been sitting.

## Implementation

Conceptual depth throughout: for each sub-task, the command that derives its members, the
move, and the gate that reds until every member moved. Where a fix shape is offered it is
labelled, and its refuter is named.

### Wave 1 — the floor (one lane; the full tier, since `_hook_utils.py` changes)

**1-A The two constants and the package metadata.** `espalier/_python_floor.py::MIN_PYTHON`
and `tools/cc/hooks/_hook_utils.py::MIN_PYTHON` to `(3, 11)`; in `pyproject.toml`,
`requires-python = ">=3.11"`, the `Programming Language :: Python :: 3.10` classifier
removed, the `tomli>=2.0; python_version < '3.11'` dependency removed, `[tool.mypy]
python_version = "3.11"`. Gate: `pytest tests/test_python_floor.py
tests/test_mypy_config_stays_near_strict.py -q`. Earn the red: run the gate after the
constants move and before `pyproject.toml` does; `test_min_python_matches_requires_python`
must red.

**1-B The matrices.** Members: `grep -nE "['\"]3\.10['\"]" .github/workflows/*.yml` (at
authoring: `test.yml` twice, `clean-checkout.yml` once, `release.yml` once; `release.yml`
quotes its cells with single quotes, and no test holds that file, so a grep for the double
quote alone misses it and a 3.10 cell fails on release day). The move: four-cell
literal lists in `test.yml` (both jobs; the comment above the first names the checklist's
required cells, so it names `test (3.11)` to `test (3.14)`), `["3.11"]` in
`clean-checkout.yml` with its floor-interpreter comment still true, four cells in
`release.yml`. The literal matrices in `tests/test_required_status_checks.py` follow.
Gate: `pytest tests/test_required_status_checks.py tests/test_sync_github_workflow_asset.py -q`.

**1-C The resolver lines.** Members: `git grep -l "(3, 10)" -- .claude/` (eight files
holding fifteen sites at authoring: four command bodies, one skill, three workflows, with
`preflight.md` carrying five). Never a filesystem walk of `.claude/`: it holds other
seats' worktrees under `.claude/worktrees/`, and `grep -rln` read 64 files there on
2026-11-04, every one past the first eight another seat's lane. The move: the line
`tests/_interpreter_hosts.py::shell_resolver_line` derives from `MIN_PYTHON` after 1-A,
pasted at each site; then `python3 scripts/sync_claude_mirrors.py` (the thirty mirror
copies) and `python3 scripts/sync_vendor_cc.py` (for `_hook_utils.py`).
`scripts/run_pack_chain.sh`'s resolver line, the sixteenth, follows by hand, since no test
holds it. Gate: `pytest
tests/test_interpreter_hosts.py tests/test_vendor_cc_parity.py -q` and the `.claude`
mirror-parity tests `sync_claude_mirrors.py` names.

**1-D The docs.** Members: `git grep -n -E '3\.10' -- README.md CLAUDE.md docs examples/README.md bench scripts`,
each hit classified before it is touched: a current promise ("Python 3.10+", "the floor is
3.10", "needs Python 3.11+ or `tomli`", the badge) moves to 3.11 or loses its `tomli`
clause; a record (`docs/session-archive.md`, `CHANGELOG.md`'s history, a dated measurement)
is left, per `tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS`. A doc with an
assets twin goes through `python3 scripts/sync_asset_docs.py`. The front door is gated by
`tests/test_front_door_numbers.py`; the rest by reading. Root `CLAUDE.md`'s "Build & Test"
gate line and `docs/RELEASE_CHECKLIST.md`'s two gate lines read `--python 3.11` (the Air
holds `cpython-3.11.16` under `uv`: `uv python list --only-installed`).

**1-E The checklist's required set.** `docs/RELEASE_CHECKLIST.md`'s required-status-checks
list to its eleven names; root `CLAUDE.md` Core Rule 10's "thirteen" clause gains the date
the count became eleven (the rule's own convention: the count, the date, the lane). Gate:
`pytest tests/test_required_status_checks.py::test_every_instructed_check_can_actually_report
tests/test_release_checklist_contract.py -q` (the first binds the list's names to the
matrices, the second binds the Tier-3 `--python <floor>` line to `pyproject.toml`; no test
pins the count), and after 0-B the live read
(`gh api .../protection/required_status_checks --jq '.contexts | length'`) equals the
checklist's count.

**1-G The syntax gate kept** *(amended to the operator's ruling of 2026-11-07, ack
`2d7cd1` on request `92e8d7`: option A, the five paths the "update Python" deny runs
through, nothing wider; the rest of `tools/cc/` may use 3.11 syntax):* in
`pyproject.toml`, `[tool.ruff] per-file-target-version` holds
`tools/cc/hooks/_start_refusal.py`, `write_guard.py`, `plan_guard.py`, `config_guard.py`
and `stop_gate.py` at `py310`, so `ruff check .` keeps refusing 3.11-only syntax in
those files while the rest of the tree may use it. Pinned by
`tests/test_ruff_config_includes_security_rules.py::test_the_update_deny_files_keep_a_py310_syntax_target`,
which reads the table and asserts each entry at `py310` and its file present: strength,
not text, so an entry may join and none may leave. Driven at the Wave 1 lane
(2026-11-07, ruff 0.17.3, a scratch copy of the layout): with no table both planted
errors (`except*`, `def f(*a: *Ts)`) pass everywhere at `>=3.11`; with the table each
reds at all five paths and at none outside them; the row reds with one entry removed.
The engine's floor sentence (1-H) adds a sixth entry, `espalier/__init__.py` at `py39`
(air's ack `7128b9`), pinned in the same row. Why not `ast.parse(feature_version=(3, 10))`: driven on 3.14.7 it rejects `except*` but
accepts `def f(*a: *Ts)` and `a[*b]`, both 3.11 syntax, and it is syntax-only.

**1-H `init`'s below-floor arm and the engine's floor sentence** *(fix shape, untested;
the operator's Task 0 ruling decides the arm):* `espalier/cli.py`'s "Wiring it anyway"
branch becomes the ruled shape, its pinned test in `tests/test_python_floor.py` moves with
it, and a new row asserts the new wording from a below-floor stub (nothing reds on the old
wording, since it interpolates the floor); `doctor`, `tools/cc/hooks/session_start.py`,
`docs/CHEAT-SHEET.md` and `docs/HOOKS.md` say the same sentence. *(amended 2026-11-07,
air's ack `7128b9` on request `79c59b`, driven by a fresh verifier on uv 3.10.21 and
3.11.16:)* the first statement of `espalier/__init__.py` after its docstring and
`__future__` import compares `sys.version_info` with a literal floor (pinned to
`MIN_PYTHON` by the parity row) and raises `SystemExit` with the sentence, so every entry
that imports the package (`-m espalier`, `-m espalier.cli`, the console script) prints it
with rc 1 and no traceback; `espalier/__init__.py` holds a `py39` ruff target (stock macOS
`python3` is 3.9.6, which a `match` statement would kill silently), a statement-order row
keeps the check first, and a CI row stubs `sys.version_info` in a subprocess so the
sentence is proved in every cell; refuted if `"$(uv python find 3.10)" -m espalier
--version` in a checkout prints a traceback instead.

**1-F The fragment and the last-3.10 sentence.** A `changelog.d/` fragment (the
`_record_fragments.py` convention); one README sentence under Requirements: "the last
release that installs on Python 3.10 is `<version>`", with the version the release step
fills in. `pip` enforces it from `Requires-Python` without the sentence; the sentence is
for the reader who asks why `pip` gave them an older one.

Gate for the wave: `python3 scripts/proof_tier.py --base origin/main` prints the tier the
diff earns and its lines (full, for a hook change); the scoped freshness gate over the
lane's diff before the ship; `git grep -n "(3, 10)\|3\.10" -- ':!CHANGELOG.md'
':!docs/session-archive.md' ':!task-packs/Done' ':!task-packs/ledger.d' ':!memory'` as the
sweep for a copy of the floor the parity tests do not know (`tools/cc/sister_site_probe.py`
is name-keyed over functions and cannot see a copied constant).

### Wave 2 — the shims (one lane; the full tier; the provenance census after the `tools/cc/` edits)

**2-A The engine.** `espalier/_compat.py` reads `import tomllib` and exports it, nothing
else; the `tomllib is None` and `is not None` arms in its callers (the census names them:
`config.py`, `proofs.py`, `surface_contract.py`, `analyze.py`, `harness_config.py`) go;
`espalier/assets.py` imports `importlib.resources.abc.Traversable` directly;
`espalier/cli.py`'s configuration probe loses its no-parser arm. Gate: the callers' own
test modules, and `pytest tests/test_assets.py tests/test_config.py -q`.

**2-B The hooks and the tools.** One rule over the wave: **no module under `tools/cc/`
imports `tomllib` at its top.** The import stays inside `_hook_utils::_toml_parser` (its
docstring keeps it off the per-call path) and inside each tool's reading function, so
every hook and tool still imports on a 3.10 interpreter and can speak the floor; a
module-top `import tomllib` in `_hook_utils` would make it fail to import on 3.10 and
silence the SessionStart banner's own below-floor warning, and `plan_guard.py`'s inline
`tomllib`/`tomli`/`None` import at its module top, which sits outside the guarded block,
is removed in favour of the shared reader rather than made unconditional (made
unconditional it is an exit 1 the protocol reads as non-blocking: 4-A(d)).
`_hook_utils::_toml_parser` returns `tomllib`;
`::_regex_extract_string_list` and its twin `::_regex_extract_scalar` *(0-A, 2026-11-07:
the twin this list missed)*, `::_read_toml_flat`'s no-parser arm, `::read_toml_table`'s
`tomli` retry and `::adopter_protected_prefixes`' degraded-reader message go;
`::_project_name_from_pyproject` and `ci_guard::_ci_project_name_from_pyproject` become
one `tomllib` read of `[project].name` or keep their text read with the 3.10 comment gone
(the executing seat decides on the tests that pin them); `plan_guard::_read_adopter_exempt_config`,
`stop_gate::_declared_test_commands`, `ship.py::handoff_push_setting`,
`ledger_row::read_id_blocks`, the `mail.py` dispatcher scan and the `_record_fragments.py`
fragments scan each become a `tomllib` read, each behind the fail-open voice rule
(`tools/cc/hooks/CLAUDE.md`: a new `except` speaks where it is seen), each gated by its
existing tests. `scripts/record_snapshot.py`, `scripts/wheel_smoke.py::_read_pyproject_version`,
`scripts/final_release_matrix.py`, `scripts/proof_tier.py` and `scripts/verify_pins.py`
lose their fallbacks. Then `python3 scripts/sync_vendor_cc.py`, and
`python3 scripts/sync_selfcheck_tests.py` where a test under `tests/` with a selfcheck twin
changed (the mirror census is `espalier/mirror_registry.py`; a PostToolUse advisory names
the sync for whichever row was touched). Gate: `pytest tests/test_hooks.py
tests/test_hook_protocol.py tests/test_failopen_voice.py tests/test_spawn_chokepoint.py
tests/test_vendor_cc_parity.py -q`, then the full tier.

**2-C The floor's voice in the deny hooks** *(fix shape, untested; refuted by the drive
below):* `tools/cc/hooks/_start_refusal.py` is the module each of the four deny hooks
imports first and alone, stdlib-only by contract. What stands today, from its docstring
and the reviewer's read: when `_hook_utils` fails to import on a 3.10 host, the deny hooks
already answer with a structured deny, not an exit 1, and the deny's remedy is wrong for
this case ("restore `_hook_utils.py` to HEAD", which does nothing). So the gain here is
the right sentence, not reachability. The shape: a function the four deny hooks call right
after importing `_start_refusal` (the deny's form depends on the hook and the event, as
`refuse_on_helper_skew(hook, event, exc)`'s does), never a check at module load, since
`_denial_reasons.py` imports `_start_refusal` and `session_start.py` imports
`_denial_reasons`, and a load-time check would answer a SessionStart with a PreToolUse
deny. Below the floor it emits the structured deny naming the running version, the floor
and a remedy the host can run: per `DEF-805` (`tests/test_python_floor.py`), a remedy is
spelled with an interpreter that can run it, and a 3.10-only host has none, so the text
says "install Python 3.11 or newer, then `espalier init . --rewire-interpreter`" (the
verb as `docs/CHEAT-SHEET.md` spells it, with its `.`). The floor it compares against is a
third literal copy, pinned to the other two by `tests/test_python_floor.py::TestTwoCopyParity`
(which becomes a four-copy parity with Wave 1's `espalier/__init__.py` literal; the repo's own pattern is
`test_launcher_version_flag_four_copy_parity`), since `_hook_utils` is exactly the module
that may not import. The drive: `uv python install 3.10`, then

```bash
"$(uv python find 3.10)" tools/cc/hooks/write_guard.py < <a Write payload>
```

never `uv run --python 3.10`, which refuses under the project's `requires-python` and,
without `--no-project`, builds a `.venv` at the checkout root, shared state (Core Rule 14).
A deny that names an import rather than the floor, or an exit 1, refutes the shape. Each of
the four hooks is driven; `write_guard`'s one restore-to-HEAD let-through stays. A 3.10
host that gets here copied the hooks by hand, runs a clone without installing it, or kept
an editable install current by `git pull`, since `pip` refuses the package on 3.10 from
`Requires-Python` (driven once in Wave 2 and recorded in Landing); the voice is for that
host.

*(0-A, 2026-11-07, and the ruling `b4bfb8`):* the SessionStart banner's own below-floor
warning had no such call. Driven under a real Python 3.10.21 on a copy of the checkout with
`espalier.toml` and a `.claude/settings.json` wired to it, `session_start` computed the
warning, then crashed at `import tomllib` on the path from `_recall.indexed_sources` to
`_toml_parser` and delivered no banner (stdout empty, the crash on stderr). `session_start`
now imports `_start_refusal` under `__main__` before any sibling and calls
`banner_below_floor`, whose banner is the floor's warning alone; a row in
`tests/test_python_floor.py` pins the block's place and the standard-library names above it.
No gate catches a run-time import of a 3.11-only name on the banner's path, nor 3.11-only
syntax in `session_start.py` itself, which is outside ruff's five-file py310 table.

**2-D The import allowlist** *(fix shape, untested; its own fixture is the refuter):* the
syntax half of "the voice stays reachable" is 1-G's ruff target. The other half is
imports: `ast.parse` and ruff both pass `import tomllib`, `from datetime import UTC` or
`from typing import Self` at the top of `_start_refusal.py`, and any of them kills the
voice on 3.10. So a row in `tests/test_python_floor.py` reads `_start_refusal.py`'s
module-level `import` nodes and asserts each against an allowlist of standard-library
names that exist on 3.10 (today, from the file: `sys`, `types`, `pathlib`, and whatever
else its top carries at the lane); an import added there is added to the list knowingly.
Earn the red: a scratch copy with `import tomllib` at its top must red the row. The
population is the one file; the row is written in Python `re`/`ast`, not a shell grep,
since the Windows leg runs it too.

**2-E The contract inverted.** `tests/test_tomllib_import_contract.py` is deleted with its
`tests/conftest.py::_MARKER_RULES` row (its reason, an unguarded `import tomllib` breaking
3.10 collection, no longer exists). In its place a row in `tests/test_python_floor.py`
walks `git ls-files '*.py'` (the three regenerated mirror trees left out) and asserts no
line matches `import tomli\b|tomli as tomllib|tomllib = None|tomllib is None|tomllib is
not None` -- the fallback spellings alone, never `_toml_parser`, which 2-B keeps and
`stop_gate.py` imports by name (the Reach command's first draft carried it and would have
been red forever). Written in Python `re` over the file list, not `grep`/`xargs`, since
the Windows leg runs it; and driven once on an extracted release archive before the
matrix does (`python3 scripts/archive_probe.py -- tests/test_python_floor.py -q -p
no:cacheprovider`, `tests/CLAUDE.md` item 5), since it reads the tree. *(0-A, 2026-11-07:
the count.)* At the lane's base (`8dd10c01`) the spellings match 29 lines in 24 files, not
one fixture string: 8 in the engine, 3 in `scripts/`, 4 in two hooks and 14 in 13 test
files, each an arm 2-A, 2-B or 2-F removes (`tests/test_test_suite_contract.py`'s is an
`assert tomllib is not None`, not a quoted example). The pattern also matches its own
spelling, so the row assembles it from fragments and its source never matches. Earn the red: a scratch file carrying
`import tomli` under `try`, `git add -N`'d, must red the row (the population is the index,
so an untracked file is invisible to it). The no-parser arms themselves are gone by their
own tests, not by this row: it pins the spellings, the tests pin the behaviour.

**2-F The 19 test-side arms.** Each goes with the arm it tested; one that tests a shape
surviving the floor (a venv built from a venv, a text read of `pyproject.toml`) stays with
its 3.10 wording removed. `pytest -q -m contract tests/test_marker_taxonomy.py` style
checks and `test_marker_taxonomy` itself stay green.

**2-G The module-top row** *(0-A, 2026-11-07: 2-B's rule had no row)*: 2-B's one rule, no
module under `tools/cc/` imports `tomllib` at its top, is pinned in
`tests/test_python_floor.py::TestTheFloorHasNoParserShims` by an AST walk over every
`tools/cc/` module: the module body, through its top-level `if`, `try` and `with` blocks and
class bodies, never a function body. At the base it names `plan_guard.py:96` and `:99`, the
inline import 2-B removes. Earn the red: a scratch `tools/cc/` module with a module-top
`import tomllib` reds it by name.

### Wave 3 — the records (rides Wave 2's lane, or its own)

**3-A The ledger.** Neither strike runs as the rows stand (the reviewer's read of
`task-packs/probes.d/`): `DEF-1007`'s probe is `cmd: null`, and `DEF-1008`'s reads whether
any `FINISH_UP_STEPS` entry mentions `tomli` (open value `False`), which the floor does not
move, so `ledger_row.py strike` refuses both at the head. So the lane first `repin`s each
with a probe that moves with the fix -- reads `pyproject.toml`'s `[project].dependencies`
for the `tomli` marker from a subject other than the probe's own file, under the verb's
rules (`memory/parallel-work-protocol.md` item 8 puts the row, the probe and the fix in one
lane) -- and strikes them after Wave 1 lands the removal. §C59 retires with its two rows
*(the ruling `2a3cad`: retired by its strikes, its index row and section left in place with
an empty Members table, as §C58 sits, since `tests/test_forward_ledger_completeness.py` pins
the index and the sections to one key set and the struck rows keep their class tag)*.
`DEF-900`'s row gets the note that `python -P` (3.11+) is now a route for the parity gates'
`cwd` problem, re-read, not closed, through `repin --reason`: the row's text hash is its
claim (`TestTextShaIsTheClaim`), so a note written any other way reads as a stale row. The
pack's own §3 row in `task-packs/FORWARD_LEDGER.md` is struck closed with the merge, in the
form the file's other closed packs take (`~~TP-706~~`, CLOSED and the date) *(corrected
2026-11-07: this said "moves to LANDED wording", which the ledger's rule 3 forbids, since
`LANDED` there is a sweep marker; the row stays because a root pack needs a reference, and
it is the one reference to `TP-704`; the record is this pack's Landing)*.

**3-B The convention.** `docs/CONVENTIONS.md`'s "`tomllib` import goes through
`espalier._compat`" section keeps its rule (one import site) and replaces "dropping 3.10
support later is a one-line edit in `_compat.py`" with the measured count and this pack's
id, so the next floor move is budgeted from a record and not a hope.

## Affected symbols

### Changed-semantics
- `espalier/_python_floor.py::MIN_PYTHON`
- `tools/cc/hooks/_hook_utils.py::MIN_PYTHON`
- `tools/cc/hooks/_hook_utils.py::_toml_parser`
- `tools/cc/hooks/_hook_utils.py::read_toml_table`
- `tools/cc/hooks/_hook_utils.py::_read_toml_flat`
- `tools/cc/hooks/_hook_utils.py::adopter_protected_prefixes`
- `tools/cc/hooks/_hook_utils.py::_project_name_from_pyproject`
- `tools/cc/ci_guard.py::_ci_project_name_from_pyproject`
- `tools/cc/hooks/plan_guard.py::_read_adopter_exempt_config`
- `tools/cc/hooks/stop_gate.py::_declared_test_commands`
- `tools/cc/hooks/_start_refusal.py::refuse_on_helper_skew`
- `tools/cc/ship.py::handoff_push_setting`
- `tools/cc/ledger_row.py::read_id_blocks`
- `espalier/_compat.py::tomllib`
- `scripts/wheel_smoke.py::_read_pyproject_version`
- `scripts/fresh_clone_gate.py::default_interpreter`
- `tests/_interpreter_hosts.py::shell_resolver_line`

The remaining members of Wave 2 are the Reach oracle's output at the lane's base, not a
roster this section carries (`blueprint-authoring`: the pack names the oracle that
enumerates members).

Scope-check at authoring (2026-11-04, `python3 -m espalier scope-check <pack> .`): the gap
it reports is of three kinds the executing seat accepts by name rather than widens Scope
(in) for: the record surfaces (`docs/session-archive.md`, `CHANGELOG.md`, the archived
packs under `task-packs/Done/`, the blueprints under `cc/blueprints/`,
`memory/CONVERGENCE_LEDGER.md`), which Core Rule 13 leaves as they are; the vendor and
asset mirrors under `espalier/_vendor/` and `espalier/assets/`, which the sync scripts
regenerate; and the readers of `tomllib` as a bare token, a name common enough that the
walk reaches every doc that mentions it.

### Renamed
- None.

### Added-paths
- (none -- the lane's changelog fragment is named by the fragment convention at the lane,
  so its path is not known at authoring; a walk of a directory token here read every
  reader of that directory as in scope, which it is not)

### Removed-paths
- `tests/test_tomllib_import_contract.py`

## Reach

This pack closes one ledger class and moves the premise of two rows. Members derived by:

```bash
git ls-files '*.py' | grep -v -E '^espalier/_vendor/|^espalier/assets/|^examples/dogfooding/' \
  | xargs grep -lE 'import tomli\b|tomli as tomllib|tomllib = None|tomllib is None|tomllib is not None|no tomllib|has no tomllib|without tomli|version_info < \(3, 11\)|version_info >= \(3, 11\)'
```

(scope: tracked Python files with the three regenerated mirror trees left out; at
`707a222f` on 2026-11-04 the pattern above, less `_toml_parser` and plus `tomllib is not
None` -- the form 2-E pins -- printed 32 files; the first draft, with `_toml_parser` and
without `is not None`, printed 34 files and 66 lines, 6 under `espalier/`, 7 under
`tools/`, 3 under `scripts/`, 18 under `tests/`. The roster is a lower bound, never the
census: the reviewer's read found one false positive, a quoted example in
`tests/test_test_suite_contract.py`, and shims the pattern cannot see, among them
`espalier/assets.py`'s `Traversable` fallback, `tools/cc/ci_guard.py`'s and
`scripts/wheel_smoke.py`'s text reads, `scripts/record_snapshot.py`'s scan,
`espalier/fusion_manifest.py`'s comment, `tests/test_git_archive_parity.py` and
`tests/test_assets.py`. A clean exit after Wave 2 is 2-E's assertion over the spellings
it names, never an absence proof of a shim spelled another way; the census and the
executing seat's read are for those.)

| Item | Status | Evidence |
|---|---|---|
| `DEF-1007` (§C59) | **CLOSED** by Wave 3 | QUICKSTART's "zero third-party deps" becomes true as written once the `tomli` marker is gone; the row's probe reads the marker |
| `DEF-1008` (§C59) | **CLOSED** by Wave 3 | the fuse handoff needs no `tomli` step once no interpreter the package allows lacks `tomllib` |
| §C59 | **RETIRED** | both members closed; the class verb's rules |
| `DEF-900` | **NOT CLOSED, premise moved** | its "a safe-path interpreter flag is no route at `>=3.10`" clause is false at a 3.11 floor; the row is re-read by its owner, a note at 3-A |
| `DEF-1147` | **NOT REACHED** | its subject is `doctor`'s reporting of an interpreter that answers and cannot start; only the floor figure in its docs moves |
| `DEF-579` | **NOT REACHED** | the EACCES class spans 3.10 to 3.13; a 3.11 floor leaves it |
| `DEF-4032` | **NOT REACHED** | a record of the `clean-checkout (3.10)` leg's red; the leg's name changes, the record does not |

## Pass criteria

- Every assertion in `tests/test_python_floor.py`, `tests/test_required_status_checks.py`,
  `tests/test_front_door_numbers.py`, `tests/test_interpreter_hosts.py` and
  `tests/test_mypy_config_stays_near_strict.py` keeps its strength: a pinned literal moves
  to the new floor, none is deleted, none is loosened to a range, and the two-copy parity
  becomes a four-copy parity (Wave 1's `espalier/__init__.py` literal, then 2-C) rather than a weaker one.
- After Wave 1: the four workflow files hold four-cell literal matrices (`clean-checkout.yml`
  one `3.11` cell); the live required set on `main` (the `gh api` read in the Motivation)
  holds exactly the eleven names `docs/RELEASE_CHECKLIST.md` lists; `pip install .` under a
  3.10 interpreter refuses on `Requires-Python` (driven once, the line in Landing); the
  resolver line at all fifteen sites equals `shell_resolver_line()`'s output; the three
  mirror syncs leave no diff (`tests/test_vendor_cc_parity.py` and the `.claude` parity
  tests green).
- After Wave 1: `ruff check .` with a scratch `except*` in one of the five ruled files (1-G)
  reds, a scratch `match` in `espalier/__init__.py` reds (its `py39` target), and the same
  constructs elsewhere under `tools/cc/` or `espalier/` do not (the per-file target holds
  where it must and nowhere else); the row pinning the `[tool.ruff]` entry reds when the entry is removed; `init`
  under a below-floor stub prints the ruled wording and its row reds on the old sentence;
  `"$(uv python find 3.10)" -m espalier --version` in a checkout prints the floor sentence,
  not a traceback; the negative literal in `tests/test_python_floor.py` reads the floor
  from `floor_text()`.
- After Wave 2: the 2-E row prints nothing at the lane's head and reds on a `git add -N`'d
  `import tomli` fixture (earn the red recorded), and it has been driven on an extracted
  release archive; `tests/test_tomllib_import_contract.py` is gone and `test_marker_taxonomy`
  is green; `_start_refusal.py`'s import allowlist row reds on a scratch copy with `import
  tomllib` at its top; no module under `tools/cc/` imports `tomllib` at its top (a row, or
  the 2-E row's sibling, asserts it); each of the four deny hooks driven under a 3.10
  interpreter exits with the structured deny naming the floor and the install-then-rewire
  remedy, never exit 1 and never a deny naming a sibling's import (the drive's four outputs
  quoted in Landing); with the version check removed, the same drive names the import or
  exits 1 (the mutation); `tools/cc/hooks/session_start.py` driven under 3.10 still prints
  its below-floor warning (the banner's own voice survives the wave).
- After Wave 3: `DEF-1007` and `DEF-1008` read struck with their prior text kept; §C59's
  index row reads retired; `DEF-900` carries the note; `docs/CONVENTIONS.md` no longer
  says "one-line edit".
- Each lane runs the tier its diff earns (`python3 scripts/proof_tier.py --base origin/main`,
  the full tier for both waves), the scoped freshness gate before the ship, and, after the
  `tools/cc/` edits, the provenance census (`memory/` note "after a tools/cc edit, run the
  provenance census").

## Files touched

- New: the `changelog.d/` fragment.
- Modified, Wave 1: `pyproject.toml` (the floor, the classifiers, the dependency, mypy's
  target, the `[tool.ruff]` per-file target); `espalier/_python_floor.py`; `espalier/cli.py`
  (the below-floor wiring arm, the entry's floor sentence); `espalier/doctor.py` and
  `tools/cc/hooks/session_start.py` (the shared "wiring it anyway" sentence);
  `tools/cc/hooks/_hook_utils.py` (and the `espalier/_vendor/cc/` copies by sync);
  `.github/workflows/test.yml`, `clean-checkout.yml`, `release.yml`; the eight `.claude/`
  bodies `git grep -l "(3, 10)" -- .claude/` names (and their mirror copies by sync);
  `scripts/run_pack_chain.sh`; `tests/_interpreter_hosts.py` only if the derived
  line's wording changes; `tests/test_required_status_checks.py`,
  `tests/test_mypy_config_stays_near_strict.py`, `tests/test_python_floor.py`, the two
  literal `(3, 10)` test sites the census names (`tests/test_session_start_interpreter_warn.py`,
  `tests/test_sync_github_workflow_asset.py`); the docs 1-D classifies as current promises
  (`README.md`, `docs/QUICKSTART.md`, `docs/ENV_CATALOG.md`, `docs/INSTALL-CI.md`,
  `docs/WORKFLOW.md`, `docs/TASK_RECIPES.md`, `docs/CHEAT-SHEET.md`, `docs/HOOKS.md`,
  `docs/SHARP_EDGES.md`'s two current clauses, `docs/CONVENTIONS.md`'s "supports 3.10+",
  `docs/FAILURE_MODES.md`'s supported-runtimes clause if it is not a record,
  `docs/RELEASE_CHECKLIST.md`, root `CLAUDE.md`, `examples/README.md`, the bench "Works on
  3.10+" lines) and their assets twins by sync; `tools/cc/hooks/session_start.py`'s one
  operator message carrying a literal "3.10".
- Modified, Wave 2: the Reach oracle's roster at the lane's base (34 files at authoring),
  `tools/cc/hooks/_start_refusal.py`, `tests/conftest.py` (`_MARKER_RULES`),
  `tests/test_python_floor.py` (the two new rows), `espalier.toml` (the `[id_blocks]`
  comment's reason, not its shape), `espalier/fusion_manifest.py` (its `tomli` comment),
  and the test modules `scope-check` names as readers of the changed symbols, each read
  and changed only where it pins a 3.10 arm (at authoring: `tests/test_hook_utils.py`,
  `tests/test_ship_driver.py`, `tests/test_marker_parity.py`,
  `tests/test_bench_results_parity.py`, `tests/test_plan_guard_adopter_config.py`,
  `tests/test_stop_gate_dormancy.py`, `tests/test_contracts.py`, `tests/test_cli_deploy.py`,
  `tests/test_fresh_clone_gate.py`, `tests/test_wheel_smoke.py`, `tests/test_utf8_text_io.py`,
  `tests/test_publish_workflow.py`, `tests/test_benchmark_release_hygiene.py`,
  `tests/test_documented_claims.py`, `tests/test_external_tool_contract.py`,
  `tests/test_ruff_config_includes_security_rules.py`, `tests/test_ledger_row.py`,
  `tests/test_record_fragments.py`, `tests/test_hooks_start_on_a_kept_helper.py`,
  `tests/test_run_pack_chain.py`, `tests/test_assets.py`, `tests/test_config.py`,
  `tests/test_fuse.py`, `tests/test_hook_exec_form.py`, `tests/test_e2e_bench.py`,
  `tests/test_site_path.py`, `tests/test_test_suite_contract.py`).
- Modified, Wave 3: `task-packs/ledger.d/DEF-1007.md`, `DEF-1008.md`, `DEF-900.md`,
  `task-packs/FORWARD_LEDGER.md` (§C59's index row, this pack's §3 row),
  `docs/CONVENTIONS.md`.
- Deleted: `tests/test_tomllib_import_contract.py` (Wave 2).
- Unmodified on purpose: `.github/workflows/harness-guard.yml` and its asset copy (3.11
  already); `espalier.toml`'s `[id_blocks]` rows; `CHANGELOG.md`'s history,
  `docs/session-archive.md`, `memory/CONVERGENCE_LEDGER.md`, `memory/session-log.d/`, the
  ledger rows' prior text; the eleven `.replace("Z", "+00:00")` lines; the 3.12+ shims
  Scope (out) names.

## Sub-task ordering

1. **0-A Task 0** — Oracles A and B (the operator runs B on each box and sends the lines);
   Oracle C at the lane's base. Decide: build, or stop and re-raise. Checkpoint: the three
   reads in the pack's Landing.
2. **0-B The required set** (the operator, GitHub-side, before Wave 1's pull request):
   remove `test (3.10)` and `test-serial (3.10)` from the required contexts, then read them
   back. *(fix shape, untested; the endpoint is GitHub's "Remove status check contexts",
   real at high confidence; the body's shape is the current docs' `{"contexts": [...]}`,
   probable; the read-back is required either way, since the `test-serial` checks are
   pinned to an app id and a removal that half-landed would show there):*

   ```bash
   gh api -X DELETE repos/Mike-Byrne-AI/espalier-harness/branches/main/protection/required_status_checks/contexts \
     --input - <<'JSON'
   {"contexts": ["test (3.10)", "test-serial (3.10)"]}
   JSON
   gh api repos/Mike-Byrne-AI/espalier-harness/branches/main/protection/required_status_checks --jq '.contexts | length'
   ```

   Checkpoint: the read prints 11 and the board's `merging:` line says so.
3. **1-A to 1-H Wave 1** in the order written, 1-G (the ruff target) right after 1-A so
   the syntax gate never lapses between the floor's move and the end of the lane; the
   smallest change (1-A, two constants) first so the gates red and then green in sight.
   1-H's arm follows the Task 0 ruling. Checkpoint per step as written; for the lane, the
   full tier, the freshness gate, the ship.
4. **2-A to 2-F Wave 2** — 2-C and 2-D before 2-B, so the voice and its contract exist
   before the hooks lose their fallbacks; then 2-A, 2-B, 2-E, 2-F. Checkpoint: the four
   hook drives under 3.10, the two earn-the-red mutations, the full tier.
5. **3-A, 3-B Wave 3** — on Wave 2's lane after its proofs, or a lane of its own.
   Checkpoint: `pytest tests/test_forward_ledger_completeness.py
   tests/test_cross_pack_assertions.py -q` and the probe-shape and bare-anchor ratchets
   after the strikes.
6. **4-A Red-team** — the `adversarial` skill over Wave 2's hook diff, with the pack's
   likeliest errors named: (a) a below-floor interpreter denied by a sibling import's name
   instead of the floor's, because something imported before the check; (b) a hook file
   that no longer parses on 3.10, so no voice fires at all and the protocol reads an exit 1
   as non-blocking; (c) a line scan replaced by a `tomllib` read that changes what a
   malformed `espalier.toml` does (a scan tolerated, a parser raises: the fail-open voice
   rule must hold at each); (d) `plan_guard.py`'s module-top `tomllib` import made
   unconditional, an exit 1 outside the guarded block; (e) a version check placed at
   `_start_refusal`'s module load, which `session_start.py` reaches through
   `_denial_reasons.py` and would answer a SessionStart with a PreToolUse deny; (f) the
   `init` arm's new wording asserted only in the surface that changed, while `doctor`, the
   banner, `docs/CHEAT-SHEET.md` or `docs/HOOKS.md` still say "wiring it anyway". Ask for
   the mutation that survives.
7. **5-A Release** — at the next release: the README's last-3.10 version filled in, the
   release gate run with `--python 3.11` as its floor leg, the matrix's four columns read.

Whether Wave 2 ships in the same release as Wave 1 is the operator's: the same release
gives adopters one floor move and one set of notes; the one after lets Wave 1 soak on the
seats first. The author's recommendation is the same release, since Wave 1 alone leaves
the shims as dead code a reader still has to read.

## Estimated effort

| Sub-task | Budget |
|---|---|
| 0-A Task 0 (two reads here, the adopter-tree read on each box, the operator's round trip) | 1 h |
| 0-B the required set (the operator's hand, read back) | 0.25 h |
| 1-A to 1-H Wave 1 (about 75 edits, the ruff target, the `init` arm and the engine's floor sentence with their rows, three syncs, the docs classification, the full tier) | 5 h |
| 2-A to 2-F Wave 2 (34 files, the voice, two contracts, four drives under 3.10, the full tier) | 6 h |
| 3-A, 3-B Wave 3 (two strikes, a class retired, a note, a paragraph) | 1 h |
| 4-A red-team | 1.5 h |
| 5-A release step | 0.5 h |
| **Total** | **15.25 h** |

## Sharp-edge entry to add (optional, if the red-team confirms the shape)

"A dead interpreter's missing stdlib module is a tax on every reader": a floor one minor
below a stdlib module's arrival costs a parser-free arm at every reader of a config key,
and the arms outlive the users they were written for. Measured here as 24 code sites and
19 test sites for one module, with the newest written the week the interpreter went
end-of-life.

## Landing
- State: LANDED
- Commits: Wave 1, `lane/build-the-floor-moves-to-3-11`: `b25951e0` (the floor) and `5061bf38`
  (the census through git, the tier's carve-out fix), merged as `8dd10c01` (#504). Waves 2 and 3,
  `lane/build-the-shims-go-the-hooks-speak-the-floor`: `16f64535` (2-B/2-C hooks), `ff924ae8`
  (2-A engine), `152aca48` (the tools' readers), `a0309429` (the banner says the floor),
  `d6d0e55b` (Wave 3 records), `9a68e64e` (the suite contracts' spawn budgets), `1eea1a47` (the
  0-A corrections), the review batch and this stamp; the alive SHA is the merge commit on `main`.
- Suite: Wave 1: the full tier at `b87dd13d`, 28,041 passed and 4 failed, all the lane's own,
  fixed comment- and test-only; then the contract slice, 6,207 passed; post-merge proof run
  42371595240 green on `8dd10c01`. Waves 2 and 3: SUITE_PENDING
- Earn-the-red: 2-C's stubbed-version row per hook red on the base hooks, and four drives under
  a real Python 3.10.21 gave the structured deny at rc 0 (a continued Stop passes); with each
  floor call removed under 3.10, `write_guard` and `plan_guard` deny as an internal error and
  `config_guard` and `stop_gate` let the call through. 2-D's rows red on their scratch
  mutations (a module-top `import tomllib`, the call moved below the siblings, `typing.Self`).
  2-E red on a `git add -N` shim fixture, 2-G on a scratch module-top import. The banner: a real
  3.10.21 on a copy of the checkout with `espalier.toml` and `.claude/settings.json` wired to it
  crashed at `152aca48` (stdout empty, `ModuleNotFoundError: No module named 'tomllib'`), and
  with the fix said only: "[WARN] session_start cannot run here. The harness does not run on
  Python 3.10.21 (at <path>). Update to Python 3.11 or newer to install and use it. Then re-wire
  the hooks to it: `espalier doctor .` names the wired interpreter. Until then every deny hook
  refuses the calls it judges, and this banner reads nothing else." `goal_snapshot_off`'s three
  parity rows red on the old line scan. The review batch's rows each carry their planted red.
- Red-team: Wave 1: code-reviewer APPROVE; failure-mode-reviewer's one BLOCKER (a below-floor
  `py -3` behind two Store aliases wired the literal `python`) fixed in one batch. Waves 2 and 3:
  the 0-A review's four WARNs folded (marked above); code-reviewer APPROVE (3 MINOR, 2 NIT);
  failure-mode-reviewer REQUEST CHANGES (1 MAJOR, 5 MINOR, 3 NIT), every 4-A error holding in the
  tree, one fix batch: the refusal's function-body imports pinned, the floor call required as an
  unconditional statement with a maintenance-mode behaviour row, any `tools/cc` module counted as a
  sibling, the deny hooks read from the canonical roster and tied to ruff's py310 table,
  `session_start.py` parsed as 3.10, stale no-parser prose corrected, `record_snapshot` reading
  `utf-8-sig`.
- Reach: Oracle A 5 of 44 version-reporting downloads on 3.10 (11.4%, under the one-fifth stop);
  Oracle B unread on every tree but the Air, named unread, never clear; the fallback spellings 29
  lines in 24 files at `8dd10c01`, zero at the head (2-E's row); 0-B: 11 required checks read
  back (ack `445e93`).
- Date: 2026-11-07
