# TP-471 — The proof chain reads the fingerprint's test command

## Status

- Version target: unscheduled (after `0.8.0b2`).
- Change type: one hook (Gate 1's resolver and runner in `tools/cc/hooks/stop_gate.py`, with
  `tools/cc/hooks/_denial_reasons.py`; vendor mirror by `python3 scripts/sync_vendor_cc.py`, the
  `vendor-cc` row of `espalier/mirror_registry.py`), the engine sentences that describe the gate,
  five shipped bodies plus two sister bodies (`.claude/` is the SoT; the `claude-asset` and
  `claude-dogfooding` rows, by `python3 scripts/sync_claude_mirrors.py`), the deployed docs that
  state the gate's posture or spell pytest (`docs/` is the SoT; the `asset-docs` row, by
  `python3 scripts/sync_asset_docs.py`), one new contract test. Optional on Decision D2: the
  fingerprint's Python runner on a `uv.lock` / `poetry.lock` tree.
- **Kind: PACK.** Task 0 can end it; its measurement at authoring says build.
- Gate: **operator decisions pending** — D1 (the `DEC-35` fork, recommended default below) and D2
  (`DEF-1157` in or out). Nothing in 1-A to 3-D waits on D2.
- Ledger: the unit of work for `DEF-949` step 4 (steps 1 to 3 landed 2026-10-01); decides `DEC-35`;
  reaches `DEF-1157` only on D2; does not reach `DEF-985` (its §C52 sibling, an engine-side
  chokepoint with its own oracle). The body sites are `DEF-1182` to `DEF-1184`, and `DEF-1185` is the
  sentence 1-A makes true; all four under Reach.
- Provenance: a real `espalier init` on a throwaway Node tree (`fresh-init/REPORT.md` §3, §4, §9
  findings 2 and 4) and this pack's own drive on a second Node tree, both 2026-10-07.

## Motivation

Every surface that proves a change assumes pytest, while the fingerprint already names the adopter's
runner. Measured 2026-10-07 on an init'd Node tree whose `test` script is `npm test` (Task 0):

1. `reports/repo_fingerprint.json::test_commands` is `["npm test"]`; `inferred_actions` carries
   `npm run lint`, `npm run build`, `npm test`. Right, and table-derived already:
   `espalier/analyze.py::detect_tests` projects `tools/cc/_stack_table.py::STACKS`, so this pack adds
   no hand list of commands.
2. The deployed bodies spell pytest in **17 fenced command lines** and the fingerprint's command in
   **0**. `npm test` reaches the tree only on two agents' `tools:` lines, appended by
   `espalier/cli.py::_asset_transform` through `espalier/harness_config.py::agent_runner_rules`; body
   prose is copied verbatim (measured on the fold's scratch tree: `diff .claude/commands/implement-task.md
   <tree>/.claude/commands/implement-task.md` prints one changed line, the managed-marker comment). Step 5's only proof is `pytest tests/test_{affected_module}.py -q`; `/test-this` and
   `test-writer` write and run `tests/test_{module}.py`; `docs-maintainer` says "`pytest tests/ -q`
   for this project"; `docs/TASK_RECIPES.md` repeats it; `debug/SKILL.md` step 7 and
   `/implement-pack` carry the same fences.
3. Under `ESPALIER_STOP_GATE=full` the Stop hook resolves `dormant_non_pytest`
   (`tools/cc/hooks/stop_gate.py::_resolve_core_tests`), writes one stderr line and allows. With a
   planted failing test it emits **0 bytes on stdout, exit 0**. The same Stop with
   `ESPALIER_STOP_GATE_TEST_CMD='npm test'` blocks naming the test: the spawn path works; only the
   resolution withholds the command.
4. The dormant branch leaves **no audit record** (no `.espalier-state/` after three Stops).

The user hurt (`STANDING_PRINCIPLES` §16): the Node adopter told in week one to run pytest on a tree
with none; the one who read the README's opt-in, set `full`, and has a gate that announces itself off.

The surface already right is the model: `.claude/commands/preflight.md` asks the engine at run time
(`espalier/harness_config.py::preflight_command`, over `::declared_action`: `suppress_actions`, then
`[extra_actions]`, then the fingerprint), prints what it chose and where it was declared, and falls to
a guarded `pytest -q` only on a Python tree that declares nothing.

## Scope (in)

- **1-A** Gate 1 runs the detected command where today it is dormant: `tools/cc/hooks/stop_gate.py`,
  `tools/cc/hooks/_denial_reasons.py`; mirrors `espalier/_vendor/cc/hooks/stop_gate.py`,
  `espalier/_vendor/cc/hooks/_denial_reasons.py`, `espalier/_vendor/cc/hooks/session_start.py` by the
  sync. Tests: `tests/test_stop_gate_dormancy.py` (a Node end-to-end that spawns the deployed hook; the
  module takes the `# slow-exempt: <reason>` line — Files touched), `tests/test_stop_gate.py`,
  `tests/test_hook_voice_reaches_claude.py` (the renamed runner's callers),
  `tests/test_governance_audit_log.py` (the template), `tests/_closed_loop_registry.py` (re-described names).
- **1-B** The committed home (D1's default): `[extra_actions] test` read hook-side in
  `tools/cc/hooks/stop_gate.py` through `tools/cc/hooks/_hook_utils.py` (`read_toml_table`, unchanged).
- **2-A** Every shipped sentence saying the gate never runs the detected command: `espalier/cli.py`
  (`_stop_gate_summary_line`; the `ONB-3` row), `espalier/doctor.py`, `README.md`, `docs/HOOKS.md`,
  `docs/ENV_CATALOG.md`, `docs/CHEAT-SHEET.md`, `docs/CONVENTIONS.md`, `docs/SHARP_EDGES.md` (a dated
  erratum); pins `tests/test_doctor.py`, `tests/test_onboarding_doc_honesty.py`, `tests/test_cli_deploy.py`;
  `tools/cc/hooks/session_start.py` is driven (it reads the status), edited only if its note names the
  retired one.
- **3-A** `/implement-task`'s proof fences derive the runner as `/preflight` does:
  `.claude/commands/implement-task.md`, `.claude/commands/implement-pack.md`, `.claude/skills/debug/SKILL.md`.
- **3-B** `.claude/commands/test-this.md`, `.claude/agents/test-writer.md`: runner from the same
  derivation, layout from the tree; no `tests/test_*.py` spelling stays in either deployed body (the
  filed `DEF-1183` probe counts them all, labelled or not).
- **3-C** `.claude/agents/docs-maintainer.md`; `docs/TASK_RECIPES.md` and the five-line pytest block
  of `docs/CHEAT-SHEET.md` under `## Key Bash Commands` (both deployed from `espalier/assets/docs/`,
  the `asset-docs` row, by `python3 scripts/sync_asset_docs.py`).
- **3-D** `tests/test_portability_contract.py`: a contract over the deployed bodies' fenced `pytest` lines.
- **4-A** (D2 only; lands after `TP-472` 2-A) `espalier/analyze.py`, `tools/cc/_stack_table.py`, mirrors `espalier/_stack_table.py`,
  `espalier/_vendor/cc/_stack_table.py`; tests `tests/test_analyze.py`, `tests/test_stack_table.py`,
  `tests/_stack_trees.py`, `tests/test_stack_trees.py`, `tests/test_node_adopter_defaults.py`; the
  selfcheck mirror (`espalier/_vendor/selfcheck_tests/test_analyze.py`,
  `espalier/_vendor/selfcheck_tests/_stack_trees.py`) by `python3 scripts/sync_selfcheck_tests.py`;
  `task-packs/LEDGER_PROBES.json` (the probe re-declared). Driven, not edited: the `detect_tests`
  consumers `espalier/harness_config.py`, `espalier/settings_profiles.py`, `espalier/strengthen.py`,
  `bench/run_benchmark.py` (reads `detect_tests` on this repository's tree, which has no lockfile, so
  its feed does not change), `tests/test_settings_profile_fingerprint.py`,
  `tests/test_agent_frontmatter_contract.py`, `tests/test_closed_loop_contract.py`.
- **5-A** Red-team. Landing: `task-packs/FORWARD_LEDGER.md` by the ledger verbs. Driven, never edited:
  `tests/test_hooks.py`, `tests/test_failopen_voice.py`, `scripts/derived_population_census.py`.

## Scope (out)

- **`DEF-985`** — the engine's 49 raw `subprocess` sites: a population oracle over `espalier/`;
  nothing here spawns from the engine. Same §C52 heading, separate lane.
- **`DEC-35` option (b)**, the hash-gated committed command. The guard is a friction slip-catcher, not
  a security boundary (`docs/STANDING_PRINCIPLES.md` §2); `/preflight` already runs `[extra_actions]
  test` ungated, and gating one reader of a key makes two readers disagree.
- **A `[stop_gate]` table** (option (a)): one more key for one hook when `[extra_actions] test` is the
  repository's declared test command already. The mode stays environment-only.
- **Rendering body prose at deploy time** (a token `_asset_transform` substitutes): the `.claude/` SoT
  is also the self-host's live, unrendered surface. Run-time derivation (3-A) is `/preflight`'s shape.
- **`Bash(pytest *)` on `test-writer`'s `tools:` line** — `DEF-1107`'s shape.
- **`test-writer`'s unguarded `espalier/*.py` loop** — `DEF-1002`. One file, two packs: sequence them
  (`memory/one-writer-per-shared-state.md`).
- **The plan tracker's self-attested `proof:` field** (§C52's own "does NOT reach"; `EI-03`).
- **A `test_dirs` fingerprint field.** `espalier/harness_config.py::_scope_paths` hand-spells `"tests"`
  (the Node build plan names `tests`; the tree has `test/`, measured). Under Reach beside `DEF-1183`.
- **`docs/FAILURE_MODES.md`** — the failure-mode catalog, a record of what happened; 2-A's scan matches
  nothing in it (measured at the fold: no `FAILURE_MODES` line in the scan's output), so there is no
  sentence to fix. It is not in `tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS` (grep: that
  set holds `docs/session-archive.md` and `memory/CONVERGENCE_LEDGER.md`), so the reason is the
  measurement, not the classification.
- Another machine's claimed files (`bench/guard_equivalence.py`, `tests/test_guard_equivalence.py`,
  `bench/guard_metamorphic.py`, `bench/README.md`, `tests/conftest.py`, `CHANGELOG.md`): no fix edits
  one; the lane's CHANGELOG line waits for the claim's release.

## Task 0 — Verify (may end this pack)

A throwaway Node tree outside the repository, every `ESPALIER_*` unset, `CLAUDE_PROJECT_DIR` set to
it. `tests/_adopter_tree.py::build_adopter_tree(dest, stack="node")` builds one (the `adopter-node`
row of `tests/_stack_trees.py`); by hand, any `package.json` with a passing `test` script does.

**0-A The bodies.** From the tree root after `espalier init .`:

```bash
command grep -nE '^\s*(pytest|python3? -m pytest)( |$)' .claude/commands/*.md .claude/agents/*.md .claude/skills/*/SKILL.md docs/TASK_RECIPES.md docs/CHEAT-SHEET.md | wc -l
command grep -rn 'npm test' .claude/commands/*.md .claude/agents/*.md .claude/skills/*/SKILL.md docs/TASK_RECIPES.md
```

Refuting: the count is 0, or the second grep prints a line inside a proof fence (not a `tools:` line)
— the bodies already render; 3-A to 3-D are scrapped and re-raised. **Measured 2026-10-07:** 17, and
two `tools:` lines. Of the 17, one carries the `# Espalier-Harness tree:` label (Phase 3's `pytest -q`
in `implement-task.md`); two are `preflight.md`'s (its guarded fallback under a `preflight_command(`
assignment, and a prose line that happens to begin with the word); six are the deployed docs'
(`command grep -rnE '^\s*(pytest|python3? -m pytest)( |$)' espalier/assets/docs`: `CHEAT-SHEET.md` 5,
`TASK_RECIPES.md` 1). On the deployed three bodies the `DEF-1182` probe's regex finds 7, of which 6 are
unlabelled. Build.

**0-B The gate.** Plant a red, then pipe the protocol's Stop event JSON into the deployed hook:

```bash
printf 'import {test} from "node:test"; import assert from "node:assert/strict";\ntest("planted", () => assert.equal(1, 2));\n' > test/planted_red.test.js
npm test; echo "npm rc=$?"
printf '{"session_id":"t","transcript_path":"/dev/null","cwd":"%s","permission_mode":"default","hook_event_name":"Stop","stop_hook_active":false}' "$PWD" | ESPALIER_STOP_GATE=full python3 tools/cc/hooks/stop_gate.py; echo "rc=$?"
```

Refuting: stdout carries `"decision": "block"` — Gate 1 already runs the detected command; 1-A is
scrapped, 1-B and 2-A re-raised. **Control:** the same pipe with `ESPALIER_STOP_GATE_TEST_CMD='npm
test'` must block, else the spawn path is broken here and 1-A's premise is not established.
**Measured 2026-10-07:** `npm rc=1`; 298 B stderr (`Gate 1 dormant ... never runs the detected
command itself`), **0 B stdout, rc 0**; the control blocked naming `planted_red.test.js`. Build.

**0-C `DEC-35`'s premise.** The row says `espalier/config.py::load_config` drops a `[stop_gate]` table
"without a warning". Write one into a scratch `espalier.toml`; call `load_config` under
`warnings.catch_warnings(record=True)`. **Measured 2026-10-07:** one warning, `unknown key `stop_gate`
is ignored; known keys: ...`. The "silently" clause is **refuted at HEAD**; the decision stays open
(no field exists). The row is re-described when D1 lands.

**0-D Self-host blast radius.** This tree's fingerprint is `["pytest -q"]` and the harness default
files exist, so `_resolve_core_tests` returns `ok_harness_defaults`. 1-A's new arm sits after that
branch; this tree's Stop must not change (Pass criteria).

## Relevant memory

Recent pattern: the last three stop-gate changes each shipped a sentence untrue when written — the
banner "warn" that reached the debug log only (`DEF-948`'s 2026-10-06 correction), the tri-state
docstring with a fourth status, `DEC-35`'s "silently" (0-C). Pins caught none; drives did.

| Entry | Where |
|---|---|
| Stop-gate dormancy on non-pytest fingerprints | `docs/SHARP_EDGES.md` |
| Renderers That Discard Fingerprint Data Fail Silently | `docs/SHARP_EDGES.md` |
| 1.11 Gate credibility (authoritative gate green on a red tree) | `docs/FAILURE_MODES.md` |
| Fix the surface the reader consumes, not the one the fact is authored on | `memory/fix-the-surface-the-reader-consumes.md` |
| A gate can be blind along a whole dimension of its input | `memory/a-gate-can-be-blind-along-a-whole-dimension.md` |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| Asset mirroring (3-way SoT) | `memory/asset-mirroring.md` |
| Verify a pack's scope-out rationale, not just its prescriptions | `memory/verify-a-packs-scope-out-rationale.md` |

Resolved 2026-10-07 by `python3 tools/cc/hooks/_recall.py "<topic>"` with `stop gate runs the
fingerprint test command`, `shipped command body hardcodes pytest on an adopter tree`, `fix the class
not the instance`, `silent green gate dormant`. Re-run them if the pack has been sitting.

## Implementation

Every fix is a **fix shape, untested**, each with the mutation its test must die to. Commands spell
`python3`, the name that answers on the authoring host (root `CLAUDE.md`, "Cross-platform Python
invocation").

### 1-A Gate 1 runs the detected command (`DEF-949` step 4)

`_resolve_core_tests` gains one status, `ok_detected`; the record carries the commands and their
source. Environment first; the harness defaults **before** the fingerprint (0-D):

```python target=tools/cc/hooks/stop_gate.py
@dataclass(frozen=True)
class ResolvedTests:
    paths: list[str]
    status: str
    note: str
    env_cmd: str = ""                 # kept: doctor's child-process probe reads it on ok_env_override
    commands: tuple[str, ...] = ()    # what Gate 1 spawns, in order, on ok_env_override / ok_detected
    source: str = ""                  # "env" | "espalier.toml" | "fingerprint"
```

```python target=tools/cc/hooks/stop_gate.py
    positional = _parse_pytest_positional_args(raw_cmds)
    if positional:
        return ResolvedTests(paths=positional, status="ok", note="")
    declared = _declared_test_commands(repo_root)                       # 1-B
    if declared:
        return ResolvedTests(paths=[], status="ok_detected", source="espalier.toml", commands=declared,
                             note=f"Gate 1 runs the test command espalier.toml declares: {' && '.join(declared)!r}")
    has_pytest_shaped = any(_is_pytest_shaped(c) for c in raw_cmds)
    defaults_present = [p for p in _HARNESS_DEFAULT_TESTS if (repo_root / p).exists()]
    if defaults_present and (not raw_cmds or has_pytest_shaped):
        return ResolvedTests(paths=list(defaults_present), status="ok_harness_defaults", note=...)   # text unchanged
    detected = next((c.strip() for c in raw_cmds if isinstance(c, str) and c.strip()), "")
    if detected:
        return ResolvedTests(paths=[], status="ok_detected", source="fingerprint", commands=(detected,),
                             note=f"Gate 1 runs the detected test command {detected!r}; [extra_actions] test "
                                  "in espalier.toml or ESPALIER_STOP_GATE_TEST_CMD overrides it")
    return ResolvedTests(paths=[], status="dormant_no_paths", note="Gate 1 dormant: no test command detected "
                         "and the harness default test files are not here. Declare [extra_actions] test in "
                         "espalier.toml, or set ESPALIER_STOP_GATE_TEST_CMD before launch.")
```

`dormant_non_pytest` is no longer returned (a detected command is run, not announced); the fingerprint
arm takes the first command, as `declared_action` takes `tests[0]`. In `_gate_pytest`,
`ok_env_override` and `ok_detected` route through one runner, and `dormant_no_paths` goes through
`_hook_utils.say_once` (event `stop_failed_open_gate1_dormant`) so `/status --log` can count what is
stderr-only today. `_run_env_override_gate(root, cmd)` becomes `_run_command_gate(root, commands, *,
source)`: the same `split_command` → `spawn_checked` path at the root, each command in order, the
first non-zero exit blocks; the once-a-session spawn-failure block and its flag are shared (a command
from `package.json` recurs on every Stop as surely as one from the environment). The
`GATE_ENV_OVERRIDE_*` templates gain a `{source}` phrase ("your ESPALIER_STOP_GATE_TEST_CMD" / "the
`test` command espalier.toml declares" / "the test command detected from package.json") and the
`rule=` names the source. A timeout on the detected arm blocks, as the override arm's does, naming
`STOP_INNER_BUDGET` and both overrides (D1).

**Refutation:** `tests/test_stop_gate.py::TestEnvOverrideGate1` red on anything but the renamed runner
means the two arms differ in a way this shape hides — stop and look. The Node end-to-end green with
the runner unrenamed means the test is not reaching the new arm.

**Earn the red:** a new `tests/test_stop_gate_dormancy.py::TestAdopterShapedFeed` case drives the real
hook as a subprocess on `build_adopter_tree(stack="node")` with `full`, no override, and a stub `npm`
first on PATH — written the way `tests/_interpreter_hosts.py::_sh_stub` / `::_cmd_stub` write theirs
(an executable `sh` script, a `.cmd` on Windows) and prepended with `tests/_interpreter_hosts.py::path_with`
— that prints `planted_red.test.js` to stdout and exits 1 (a second stub exits 0 for the green
control). The case asserts `"decision": "block"` with `planted_red.test.js` in the reason; it dies to
reverting the `detected` arm and to an `ok_detected` with `commands=()`. The stub proves the hook
spawned the fingerprint's command and read its exit; that `npm test` itself runs is Task 0's hand
drive with the real `npm`, once (the suite's cells install no Node, so a real-`npm` test would red on
a box without it for a reason that is not the gate's). The module gains the `# slow-exempt: <reason>`
line the AST detector in `tests/test_test_suite_contract.py::test_every_subprocess_test_is_slow_or_exempt`
honours (one hook subprocess and one stub child per case; measure and write the time). The vocabulary pin
(`tests/test_stop_gate_dormancy.py::TestTheStatusVocabularyIsDeclaredWhereItIsRead`) reds until the
docstring and the gate name `ok_detected` and drop the retired status.
`test_go_fingerprint_returns_dormant_non_pytest` and
`test_a_non_pytest_feed_names_the_override_not_the_fingerprint` are re-described to assert
`ok_detected` **and** `commands == ("go test ./...",)` / `("npm test",)` — stronger, never dropped.
`DEF-949`'s probe (`python3 tools/cc/check_ledger_probes.py --id DEF-949`) flips its first field.

### 1-B `[extra_actions] test`, read hook-side (D1's default for `DEC-35`)

```python target=tools/cc/hooks/stop_gate.py
def _declared_test_commands(root: Path) -> tuple[str, ...]:
    """``[extra_actions] test`` from espalier.toml -- the declared test command /preflight already
    runs -- or ``()``. A present value that is not a non-empty list of non-empty strings is
    ignored and SAID once a session: a setting that does nothing is the defect."""
    table = _hook_utils.read_toml_table(root, on_error=lambda text: _hook_utils.say_once(
        root, "gate1-toml", "stop_gate", "stop_failed_open_toml_unreadable",
        f"espalier.toml could not be parsed ({text}); Gate 1 uses the detected command"))
    actions = (table or {}).get("extra_actions")
    declared = actions.get("test") if isinstance(actions, dict) else None
    if declared is None:
        return ()
    if isinstance(declared, list) and declared and all(isinstance(c, str) and c.strip() for c in declared):
        return tuple(c.strip() for c in declared)
    _hook_utils.say_once(root, "gate1-toml-shape", "stop_gate", "stop_failed_open_toml_test_shape",
                         "espalier.toml [extra_actions] test is not a list of command strings; Gate 1 uses the detected command")
    return ()
```

**Refutation:** `read_toml_table` returns `None` on a 3.10 host with neither `tomllib` nor `tomli` (the
regex arm `read_toml_string_list` recovers flat keys, not a table); if that host is in the census, 1-B's
docs say the key needs 3.11+ or `tomli`, and the fingerprint arm carries 3.10. **Earn the red:** `test =
["python3 -c 'import sys; sys.exit(3)'"]` beside a green fingerprint command blocks with `espalier.toml`
in the reason (dies to dropping the branch); `test = "npm test"` (a string) runs the fingerprint command
and lands one `stop_failed_open_toml_test_shape` record (dies to accepting the string).

### 2-A The sentences

Population, re-derived at execution — a multi-line-aware scan, because `cli.py`'s sentence wraps:

```bash
python3 - <<'PY'
import re, pathlib
pats = [r"never runs the (?:detected|fingerprint)", r"runs your suite only\s+through", r"Gate 1 never runs",
        r"is dormant \([^)]*\) and runs nothing", r"the only way Gate 1 runs", r"\(runs pytest\)"]
roots = ("espalier", "tools/cc/hooks", "docs", "README.md", ".claude", "tests")
for f in [p for r in roots for p in ([pathlib.Path(r)] if pathlib.Path(r).is_file() else pathlib.Path(r).rglob("*"))
          if p.suffix in (".py", ".md") and "_vendor" not in p.parts and "assets" not in p.parts]:
    n = sum(len(re.findall(x, f.read_text(encoding="utf-8", errors="replace"))) for x in pats)
    if n: print(n, f)
PY
```

Measured 2026-10-07, re-run at the fold (all six patterns): 11 matches in 8 files — `stop_gate.py` 3,
`ENV_CATALOG.md` 2, and one each in `cli.py`, `doctor.py`, `HOOKS.md`, `README.md`, `CHEAT-SHEET.md`
("the only way Gate 1 runs it") and `CONVENTIONS.md` ("`full` (runs pytest)") — plus the
`docs/SHARP_EDGES.md` entry's "To enable Gate 1 for non-pytest repos" paragraph, which no pattern
matches (read). `HOOKS.md`, `ENV_CATALOG.md` and `CHEAT-SHEET.md` are on the `asset-docs` row:
`python3 scripts/sync_asset_docs.py` after; `README.md`, `CONVENTIONS.md` and `SHARP_EDGES.md` have
no mirror (the registry's census; an adopter's `CONVENTIONS.md` and `SHARP_EDGES.md` are stubs `init`
writes). Each becomes: under `full`, Gate 1 runs
`ESPALIER_STOP_GATE_TEST_CMD`, else `[extra_actions] test`, else the detected command; a pytest tree
holding the harness default files runs only those (unchanged). `doctor`'s `_check_stop_gate_posture`
counts `ok_detected` as running the suite and names the source. `ONB-3` in `_ONBOARDING_ROWS`, which
already says the gate "runs `test_commands` from `reports/repo_fingerprint.json`", becomes true and
gains the toml key. `_stop_gate_summary_line` has no pin (measured: `grep -rn _stop_gate_summary_line
tests/` prints nothing); 2-A adds one asserting the line names the detected command and neither "only
through" nor "runs nothing" for `["npm test"]`. **Earn the red:** that pin dies to today's text.

### 3-A `/implement-task`'s proof fences

Step 5 and the suite fences (step 7, Phase 3) derive the runner as `/preflight` step 1 does:

```markdown target=.claude/commands/implement-task.md
5. **Run targeted proof** in the repository's own runner — `[extra_actions] test` in
   `espalier.toml`, else the fingerprint's detected command; the stderr line names which — on
   the one test file this step touched, in that runner's form (pytest takes the path; a
   `package.json` `test` script takes it after `--`):
   ```bash
   PY=; for c in 'python3' python 'py -3'; do $c -c 'import sys, espalier; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1 && { PY=$c; break; }; done; [ -n "$PY" ] || { echo 'no Python 3.10+ with espalier answered' >&2; exit 1; }
   TEST=$($PY -c "import sys; sys.stdout.reconfigure(encoding='utf-8', errors='replace'); from espalier.harness_config import preflight_command; print(preflight_command('test'))") || exit 1
   [ -n "$TEST" ] || echo 'no test command declared or detected - write one as [extra_actions] test in espalier.toml' >&2
   # Espalier-Harness tree: pytest tests/test_{affected_module}.py -q
   ```
```

The `pytest -m contract -q` / `pytest -q` pair under step 7's `# adopter tree:` comment (unlabelled
today) and Phase 3's `pytest -q` (which already carries the label) become `eval "$TEST"` behind the
same derivation; a self-host form that stays on a line carries the trailing `# Espalier-Harness tree:`
label 3-D defines, and the `python scripts/proof_tier.py --run` line keeps its own.
`.claude/commands/implement-pack.md`'s two lines (their trailing comments are not labels) and
`.claude/skills/debug/SKILL.md` step 7 take the same shape. `implement-pack.md` is also the mirror side
of the `pack-checklist` row: the two lines sit after its `END generated region` marker, so the edit is
outside the region and `python3 scripts/sync_checklist_regions.py --check` stays clean. Then
`python3 scripts/sync_claude_mirrors.py`.

**Refutation:** `preflight_command('test')` prints nothing on the Node fixture (`espalier` not
importable under the interpreter the loop finds) — honest but inert there; then 3-A adds `/preflight`'s
guarded fallback as an assignment, `[ -n "$TEST" ] || { [ -f pyproject.toml ] && TEST='pytest -q'; }`,
so the fallback is never a line whose first token is `pytest` (the `DEF-1182` probe would count it),
and says so. **Earn the red:** 3-D dies to the pre-fix fence; the filed `DEF-1182` probe reads 0.

### 3-B `/test-this` and `test-writer`

`.claude/commands/test-this.md` step 2 briefs the runner from the same `TEST` derivation and the test
tree the repository already has (`ls -d test tests spec __tests__ 2>/dev/null`, then the file pattern
of what is there; the directory the fingerprint's command names when it names one, `node --test test/`)
in place of `tests/test_{module}.py`; step 4 runs `"$TEST"` with the new file in the runner's form —
for pytest the derived line and the self-host line coincide (`pytest -q <file>`), so no self-host
example remains. `.claude/agents/test-writer.md`: the discovery shell's `REF_FILE=$(ls
tests/test_hooks.py tests/test_fingerprint.py tests/test_*.py ...)` lists the derived directory instead
(the coverage loop below it in the same shell is `DEF-1002`'s and is left to its row — Risk 5); the
"Scanner tests (FACT from tests/test_scanners.py)" heading names the reference project's scanner tests
without the path; the "Run:" fence takes the `"$TEST"` form; and the two sentences under `## Adapting
me to YOUR test patterns` that spell `tests/test_{module}.py` keep their meaning with the reference
tree spelled as a flat `tests/` directory holding one `test_<module>.py` per module. **Why the last
two:** the filed `DEF-1183` probe counts every `tests/test_<lowercase>.py` token in the two deployed
bodies, labelled or not — eight at filing (`python3 tools/cc/check_ledger_probes.py --id DEF-1183`;
`test-this.md` 2, `test-writer.md` 6, measured on the fold's scratch tree) — and was not re-declared to
the label rule its two siblings took, so the strike needs all eight gone, two of which already address
the adopter correctly. D3 gives the coordinator the other exit. **Earn the red:** the probe reads 0 and
dies to restoring any one spelling; 3-D covers the two run fences.

### 3-C `docs-maintainer` and `docs/TASK_RECIPES.md`

`docs-maintainer` CHEAT-SHEET step 3: "Keep build/test commands current: the fingerprint's
`test_commands` and `inferred_actions` (`/preflight` prints the test one and where it was declared)" —
the `pytest tests/ -q` literal goes; a line carrying `# Espalier-Harness tree:` would pass the
re-declared probe, but a prose step needs no self-host example. `TASK_RECIPES.md`'s two "runs pytest
tests/..." lines: "runs the repository's test command on the targeted file (`/preflight` prints
which)"; "pytest suite green (pytest output present)" becomes "the test suite green (the runner's
output present)". `docs/CHEAT-SHEET.md`'s five-line pytest block under `## Key Bash Commands` (the
four-file core slice, `-q`, three marker slices; its comment already ends "use yours instead"): each
line takes the trailing `# Espalier-Harness tree:` label 3-D defines — the lines are the harness
suite's own and stay as the example, labelled, not derived (Risk 10). Then `python3
scripts/sync_claude_mirrors.py` for the agent body and `python3 scripts/sync_asset_docs.py` for the
two docs (the `asset-docs` row; the pack's first draft named the wrong script here). **Earn the
red:** the filed `DEF-1184` probe (re-declared today: unlabelled lines in the two deployed files)
reads 0 and dies to restoring one sentence; 3-D dies to one CHEAT-SHEET label removed.

### 3-D The contract: a fenced `pytest` in a shipped body is labelled or derived

The label is one literal, `# Espalier-Harness tree:`, on the same line as the pytest token — trailing
the command (`pytest -q   # Espalier-Harness tree: ...`) or as the comment that quotes it
(`# Espalier-Harness tree: pytest tests/test_x.py -q`). One rule, three readers: this class; the
`DEF-1182` and `DEF-1184` probes, which count unlabelled lines only; `TP-473`'s audience scanner, which
allowlists a line carrying it. A label in a fence's first comment line, or any other spelling, is not
a label: a per-line probe cannot see it.

```python target=tests/test_portability_contract.py
class TestShippedProofFencesNameTheRepositorysRunner:
    """Every fenced line whose first token is ``pytest`` or ``python -m pytest``, in a file init
    deploys, either carries LABEL on that line or sits in a fence that assigned from
    ``preflight_command(`` on an earlier line (the /preflight guarded-fallback shape). A line behind
    the ``TEST`` derivation is ``eval "$TEST"`` and is not pytest-shaped. Population derived: every
    ``.md`` under ``.claude/{agents,commands,skills}`` and ``espalier/assets/docs`` (the deploy source;
    measured at authoring: CHEAT-SHEET.md 5 lines, TASK_RECIPES.md 1), minus
    ``tests/test_doc_source_citations.py::_RECORD_SURFACE_DOCS``. Fenced lines only: a prose line
    that begins with the word (preflight.md has one) is outside the rule."""
    LABEL = "# Espalier-Harness tree:"
    PYTEST_LINE = re.compile(r"^\s*(?:pytest|python3? -m pytest)(?: |$)")
```

**Earn the red:** remove the label from Phase 3's `pytest -q` in `implement-task.md`, or from one
CHEAT-SHEET line → red naming file and line; add a bare `pytest -q` fence to `test-this.md` → red. A
text pin, said plainly: it holds the shape 3-A to 3-C leave; 0-A's grep on an init'd tree and the
three filed probes are the behaviour oracle.

### 4-A (D2) The Python runner on a `uv.lock` / `poetry.lock` tree (`DEF-1157`)

The Python row of `tools/cc/_stack_table.py::STACKS` gains `package_managers` rows for `uv` (`uv.lock`)
and `poetry` (`poetry.lock`) whose `test` is the wrapped runner (`("uv", "run", "pytest", "-q")`);
`espalier/analyze.py::detect_tests` wraps `_PYTEST` through the one manager the lockfile names (two
lockfiles: none, the rule `detect_package_manager` keeps). `espalier/settings_profiles.py::narrowed_rules`
already derives a wrapper's `run` onto the wrapped command's rule (its docstring names `uv run pytest`).
4-A lands after `TP-472` 2-A, which gives `Stack` a defaulted `test_dirs` field and every row a value
and adds a pin to `tests/test_stack_table.py::TestTheTableKeepsItsSeedNames`: 4-A's two rows rebase
onto that table and take the default. Then `python3 scripts/sync_vendor_cc.py` (one run writes the
`vendor-cc` and `stack-table` rows, `espalier/_vendor/cc/_stack_table.py` and `espalier/_stack_table.py`)
and `python3 scripts/sync_selfcheck_tests.py`. **Refutation:**
`tests/test_stack_table.py` red for a reason other than the two rows (the `PackageManager` shape is
Node's: `start`, `script_runners()`) — 4-A needs its own shape; re-raise it alone. **Earn the red:**
`DEF-1157`'s probe flips from `uv=pytest -q poetry=pytest -q`; a new case in
`tests/test_stack_table.py::TestTheCommandsRunUnderTheRepositorysManager` dies to the wrap removed. The
probe is pinned to an earlier row text (`STALE_CLAIM`, measured 2026-10-07): re-declare it.

### 5-A Red-team

`code-reviewer` and `failure-mode-reviewer` on the lane's diff, edits frozen (root `CLAUDE.md` Core
Rule 11). Ask for: the fingerprint command `split_command` splits differently from the shell `/preflight`
uses; the Stop that blocks every turn under a slow detected suite; a `[extra_actions] test` entry with a
`cd` in it; the status the vocabulary pin cannot see.

## Affected symbols

### Changed-semantics

- `tools/cc/hooks/stop_gate.py::_resolve_core_tests` (as the 1-A fence: reads `[extra_actions] test` after the environment and before the fingerprint; returns `ok_detected` with `commands` and `source` where it returned `dormant_non_pytest`, and also for a pytest-shaped command with no positional paths on a tree without the harness default files — that tree now runs the command whole, Risk 1; `dormant_no_paths` only when the fingerprint names no command and no harness default file is present)
- `tools/cc/hooks/stop_gate.py::ResolvedTests` (gains `commands`, `source`)
- `tools/cc/hooks/stop_gate.py::_gate_pytest` (routes `ok_detected`; `dormant_no_paths` leaves a record)
- `tools/cc/hooks/_denial_reasons.py::GATE_ENV_OVERRIDE_FAILED` (and its `_TIMEOUT`, `_SPAWN_FAILED` siblings: a `{source}` phrase)
- `espalier/cli.py::_stop_gate_summary_line` (names the detected command as what runs)
- `espalier/cli.py::_ONBOARDING_ROWS` (the `ONB-3` text, now true, names `[extra_actions] test`)
- `espalier/doctor.py::_check_stop_gate_posture` (`ok_detected` runs the suite; names the source)
- `tests/test_stop_gate_dormancy.py::TestAdopterShapedFeed` (the Node end-to-end; two cases re-described)
- `tests/test_stop_gate_dormancy.py::TestTheStatusVocabularyIsDeclaredWhereItIsRead` (the declared set)
- `tests/test_doctor.py::TestEveryWarningCarriesANextStep` (its `_stop_gate_posture` stub names `dormant_no_paths`)
- `espalier/analyze.py::detect_tests` (4-A only: the wrapped runner)
- `tools/cc/_stack_table.py::STACKS` (4-A only: the Python row's package managers; after `TP-472` 2-A's `test_dirs` field)
- `tests/test_stack_table.py::TestTheCommandsRunUnderTheRepositorysManager` (4-A only: new cases; the module also gains `TP-472` 2-A's pin first)

### Renamed

- `tools/cc/hooks/stop_gate.py::_run_env_override_gate` — renamed to `_run_command_gate` (takes `commands` and `source`); callers: `_gate_pytest` and the tests that spell the old name (`grep -rln _run_env_override_gate tests/`)

### Added-paths

- `tools/cc/hooks/stop_gate.py::_declared_test_commands`
- `tests/test_portability_contract.py::TestShippedProofFencesNameTheRepositorysRunner`
- `task-packs/TP-471-the-proof-chain-reads-the-fingerprints-test-command.md`

### Removed-paths

- (none — `dormant_non_pytest` is a status literal, not a path; its retirement is under Changed-semantics)

## Reach

Members derived by: the brief's ids read in `task-packs/FORWARD_LEDGER.md` and the §C52 heading; the
probes (`python3 tools/cc/check_ledger_probes.py --id <id>`: `DEF-949` `STILL_OPEN`, `DEF-1157`
`STALE_CLAIM`, `DEF-985` `STILL_OPEN`; `DEF-1182` 7, `DEF-1183` 8, `DEF-1184` 3, `DEF-1185` `True True` — the body
rows' filed probes, each built on `tests/_adopter_tree.py::build_adopter_tree` over the deployed files);
the 0-A grep (17 lines, 8 files) as the census;
`python3 tools/cc/sister_site_probe.py --json` (rc 2; scope `tools/cc/hooks/*.py, espalier/*.py`, 101
files — `.claude/` bodies are outside it, so it is no evidence about them). The brief named `DEF-1000`
as the uv/poetry row; that row is `doctor`'s missing `Read()` line. The uv/poetry row is `DEF-1157`;
nothing here touches `DEF-1000`.

| Item | Status | Evidence |
|---|---|---|
| `DEF-949` step 4 | **CLOSED by 1-A and 1-B** | the Node end-to-end blocks on a planted red with no override; the probe's first field leaves `dormant_non_pytest` |
| `DEC-35` | **DECIDED by D1** (recommended: environment, then `[extra_actions] test`, then the fingerprint; mode environment-only) | 0-C refutes the row's "silently"; the row is re-described with the decision |
| `DEF-1157` | **CLOSED by 4-A if D2 is yes; else NOT REACHED** | the probe flips from `uv=pytest -q`; without 4-A every surface names, faithfully, a command the unactivated shell cannot find |
| `DEF-985` | **NOT REACHED** | engine-side chokepoint; its own population oracle; no engine spawn changes here |
| `DEF-1107` | **NOT REACHED** | the agents' `tools:` line shape; `Bash(pytest *)` stays on `test-writer` |
| `DEF-1002` | **NOT REACHED** | `test-writer`'s discovery guards; 3-B edits the brief and the run fence only |
| `DEF-1152` | **NOT REACHED**, one member moved | `dormant_no_paths` now lands a `say_once` record; that `/status --log` reads today's file only is that row's |
| `DEF-1182` | **CLOSED by 3-A** | the three deployed bodies' proof fences spell pytest where the fingerprint names the runner; the filed probe, re-declared today to unlabelled lines only (`python3 tools/cc/check_ledger_probes.py --id DEF-1182`): seven pytest-spelled fence lines across the three deployed bodies at filing, six of them unlabelled (Phase 3's already carries the label; measured on the fold's scratch tree); 3-A leaves 0 |
| `DEF-1183` | **CLOSED by 3-B** (D3 names the other exit); its layout sibling NOT REACHED | the two deployed bodies write, run and discover `tests/test_{module}.py`; the filed probe counts every `tests/test_*.py` spelling, labelled or not (`--id DEF-1183`): eight at filing, `test-this.md` 2 and `test-writer.md` 6; 3-B leaves 0; sibling: `espalier/harness_config.py::_scope_paths` names `tests` on a tree whose directory is `test/` |
| `DEF-1184` | **CLOSED by 3-C** | `docs-maintainer` and `TASK_RECIPES.md` state pytest as this project's command; the filed probe, re-declared today to unlabelled lines only (`--id DEF-1184`): three at filing, `docs-maintainer.md` 1 and `TASK_RECIPES.md` 2; by hand on the two deployed files, `grep -cE 'pytest tests/ -q|runs pytest tests/'` — one bare `|` under `-E`; BSD grep reads `\|` as a literal pipe and prints 0 — and 3-C leaves 0 |
| `DEF-1185` | **CLOSED by 2-A** (made true by 1-A) | `_ONBOARDING_ROWS` `ONB-3` tells the adopter the gate "runs `test_commands` from `reports/repo_fingerprint.json`", false today; the filed probe (`--id DEF-1185`) prints `True True` — the deployed hook resolves a `dormant*` status on the Node tree, and ONB-3 says "runs … `test_commands`"; 1-A flips the first field to `False` while the sentence stays and gains the toml key |

`DEF-1182` to `DEF-1184` are one class with three repair shapes, not three classes: the 0-A grep is the
census; each row is keyed on its own probe (the strike verb is per row). `DEF-1185` is the inverse
member — a sentence that promised what this pack builds.

## Pass criteria

- 0-B re-run after 1-A on the Node fixture: the planted red **blocks** with the test named and
  `fingerprint` in the source phrase; the green tree allows; `ESPALIER_STOP_GATE_TEST_CMD` wins and the
  reason says so; a declared `[extra_actions] test` wins over the fingerprint.
- 0-D holds: this tree under `full` resolves `ok_harness_defaults` with the same paths as before.
- No assertion in `tests/test_stop_gate.py`, `tests/test_stop_gate_dormancy.py`, `tests/test_doctor.py`
  is weakened; a re-described case asserts the new status **and** the command it carries; the
  vocabulary pin's set equals the statuses `_resolve_core_tests` returns.
- Every status `_gate_pytest` names leaves a decision, a stderr note or a `say_once` record.
- 2-A's scan prints 0 outside the `docs/SHARP_EDGES.md` erratum (which quotes the retired sentence, dated).
- 0-A's grep on a fresh Node tree prints only lines carrying `# Espalier-Harness tree:` or sitting under a
  `preflight_command(` assignment in their fence (the derived lines are `eval "$TEST"`, not pytest-shaped);
  the filed `DEF-1182`, `DEF-1183` and `DEF-1184` probes read 0 and `DEF-1185`'s first field reads
  `False`; 3-D green, having died to both mutations.
- `tests/test_stack_table.py::TestEveryHandListIsDerivedOrMarked` green: the hook spells no stack
  command of its own.
- `python3 scripts/sync_vendor_cc.py --check`, `python3 scripts/sync_claude_mirrors.py --check`,
  `python3 scripts/sync_asset_docs.py --check` and `python3 scripts/sync_checklist_regions.py --check`
  clean (the four rows this pack's edits sit on, read from `espalier/mirror_registry.py`; 4-A adds
  `python3 scripts/sync_selfcheck_tests.py --check`); `mypy tools/cc/hooks/` clean; `ruff check .` clean;
  `python3 scripts/proof_tier.py --run --base origin/main` (the tier is `full`: a hook changed).

## Risks — what this pack most likely got wrong

1. **A slow detected suite blocks every Stop.** A pytest adopter with no harness files now runs
   `pytest -q` whole under `full`; past `STOP_INNER_BUDGET` (60 s) the detected arm blocks each Stop, as
   the override arm does. D1 decides whether it should allow-and-record instead; recommended block (a
   gate green because it ran out of time is 1.11's shape).
2. **The toml key means two things.** `/preflight` runs `[extra_actions] test` through a shell (`eval`);
   the hook runs it without one (`split_command`). A pipe or a `cd` passes one and fails the other. The
   reason says "started without a shell"; the red-team is asked for the entry that diverges.
3. **The body derivation needs `espalier` importable.** From a shell where the install's venv is not
   active, `TEST` is empty. `/preflight` lives with this; 3-A must print the "none declared" line.
4. **The targeted form is prose.** No table projection yields "run one test file" per runner; a
   `test_file` argv on the stack table would retire step 5's two examples. Not built.
5. **Two packs on `test-writer.md`.** `DEF-1002` and 3-B edit one body; one lands first.
6. **The sentence census is a regex.** 2-A's scan found 11 matches in 8 files; a paraphrase is
   invisible to it. The red-team reads the eight files and the SHARP_EDGES entry whole.
7. **The body lane is shared by four packs.** Landing order: `TP-470` 3-A first (the step-6 review
   block of `implement-task.md`, `implement-pack.md`, `preflight.md`); then this pack's 3-A to 3-C (step
   5, step 7 and Phase 3 of `implement-task.md`, `implement-pack.md`'s run fence, `debug/SKILL.md`,
   `test-this.md`, `test-writer.md`, `docs-maintainer.md`); then `TP-474` 3-B (one sentence in each of
   the four `Adapting me` sections, `test-writer.md`'s and `docs-maintainer.md`'s among them); `TP-473`
   1-B last, because its gate reads the final text. A later pack rebases onto the earlier one's
   `.claude/` SoT and re-runs `sync_claude_mirrors.py`; a hand resolve happens in `.claude/`, never in
   a mirror.
8. **The stack table is shared with `TP-472`.** `TP-472` 2-A (the `test_dirs` field, every row, the
   seed-name pin in `tests/test_stack_table.py`) lands first; 4-A's two Python-row entries and its cases
   in the same test module land after and rebase onto it. One script writes both mirrors
   (`sync_vendor_cc.py`); a hand resolve on the Python row happens in `tools/cc/_stack_table.py` only.
9. **Three more seams, one line each.** `espalier/cli.py::_ONBOARDING_ROWS`: 2-A edits ONB-3's text;
   `TP-472` 2-B edits ONB-6's text and `TP-474` 5-A the ONB-1, ONB-6 and ONB-7 codes. Both partners
   state this pack's 2-A lands first on the tuple (a different row; a one-row hunk for whoever is
   second); the order between their two ONB-6 edits is theirs. `tools/cc/hooks/_denial_reasons.py`:
   1-A edits the `GATE_ENV_OVERRIDE_*` templates; `TP-472` edits `HARNESS_ENV_PREFIX_INLINE`, `TP-473`
   `KILL_SWITCH_DETECTED` — distinct constants, any order, `sync_vendor_cc.py` after each.
   `espalier/doctor.py`: 2-A edits `_check_stop_gate_posture`; `TP-466b` 1-D and `TP-474` 2-C edit
   other functions — distinct symbols, any order.
10. **Labelled is not derived.** The adopter on a Node tree still reads five pytest lines in the
    deployed `CHEAT-SHEET.md`, told they are the harness suite's own; rendering them from the
    fingerprint is Scope (out) with the rest of deploy-time rendering.
11. **The stub proves the spawn, not the suite.** 1-A's end-to-end shows Gate 1 ran the fingerprint's
    command and read its exit; whether `npm test` runs on a real Node tree is Task 0's one hand drive.
12. **A spawning test module.** The new case makes `tests/test_stop_gate_dormancy.py` spawn a child;
    it takes the `# slow-exempt: <reason>` idiom in its module docstring, not a `tests/conftest.py`
    `_SLOW_FILES` row, and it is already in `_MARKER_RULES`'s `security` tuple — so the claim released
    on `conftest.py` today is not used.

## Decisions (for the operator)

- **D1 — `DEC-35`.** Where does the stop-time test command live? Recommended: the environment
  (`ESPALIER_STOP_GATE_TEST_CMD`), then `espalier.toml` `[extra_actions] test` (already `/preflight`'s
  committed test command), then the fingerprint's detected command; the mode stays environment-only; the
  detected arm blocks on timeout like the override arm. Alternatives: (a) a `[stop_gate]` table (`mode`,
  `argv`, `cwd`); (b) the same, honoured only after `init` records its hash; (d) environment-only as
  today. 0-C: the row's "silently dropped" clause is no longer true, so (a)'s urgency is lower than it reads.
- **D2 — `DEF-1157`.** Build 4-A here? Recommended: yes, as the last sub-task on its own lane (a table
  row and a wrap; the oracle is the row's probe) — but it reverses the stack-registry pack's 2026-10-07
  decision and changes `/preflight`'s line and the allow rules for every uv/poetry adopter, so it needs
  an explicit yes. Absent one, 4-A does not run.
- **D3 — `DEF-1183`'s probe and the two reference sentences.** The filed probe counts every
  `tests/test_*.py` token in the two deployed bodies, and two of the eight are sentences under
  `test-writer.md`'s `## Adapting me to YOUR test patterns` that name Espalier-Harness as the worked
  example and tell the adopter to replace it. Recommended: 3-B re-spells those two (same meaning,
  the reference tree as a flat `tests/` directory of `test_<module>.py` files) and the probe flips.
  Alternative: re-declare `DEF-1183` to the label rule its siblings took — a line carrying
  `# Espalier-Harness tree:` or naming the reference project does not count — and 3-B leaves the two
  sentences as they are. Either way the write, run and discovery lines take the derived layout.

## Files touched

- New: one class in `tests/test_portability_contract.py`; this pack.
- Modified, by lane, as Scope (in) lists them: the hook lane (hook, reasons, their vendor copies by
  `sync_vendor_cc.py`; the tests 1-A and 2-A name — `grep -oE 'tests/[_a-z]+\.py'` over this pack lists
  them, and `tests/test_stop_gate_dormancy.py` also gains its `# slow-exempt: <reason>` module line;
  `cli.py`, `doctor.py`; the docs 2-A names, the three on the `asset-docs` row mirrored by
  `sync_asset_docs.py`; the ledger by its verbs); the body lane (seven bodies, mirrors under
  `espalier/assets/claude/` and `examples/dogfooding/.claude/` by `sync_claude_mirrors.py`;
  `docs/TASK_RECIPES.md` and `docs/CHEAT-SHEET.md`'s pytest block, mirrored by `sync_asset_docs.py`);
  the D2 lane (`analyze.py`, the stack table and its two mirrors by `sync_vendor_cc.py`, five tests,
  the selfcheck mirror by `sync_selfcheck_tests.py`, `LEDGER_PROBES.json`).
- `tests/conftest.py`: no row — no new test module, and the dormancy module takes the `# slow-exempt:`
  idiom in place of a `_SLOW_FILES` row (its claim was released today; this pack does not need it).
- Unmodified on purpose: `docs/FAILURE_MODES.md` (nothing in it matches 2-A's scan);
  `espalier/harness_config.py` (3-A reads it); every file under another machine's claim.

## Sub-task ordering

1. Task 0 (0-A to 0-D) — checkpoint: the four measurements in Landing.
2. 1-A, 1-B — checkpoint: `pytest -q -m 'not heavy_e2e' tests/test_stop_gate_dormancy.py tests/test_stop_gate.py`;
   the Node end-to-end red before, green after.
3. `python3 scripts/sync_vendor_cc.py` — checkpoint: the parity pin.
4. 2-A; `python3 scripts/sync_asset_docs.py` — checkpoint: the scan prints 0; `pytest -q -m 'not heavy_e2e' tests/test_doctor.py tests/test_cli_deploy.py tests/test_onboarding_doc_honesty.py`; the `asset-docs` pin.
5. 3-A, 3-B, 3-C — after `TP-470` 3-A has landed on `main`, before `TP-474` 3-B and `TP-473` 1-B (Risk 7);
   `python3 scripts/sync_claude_mirrors.py`; `python3 scripts/sync_asset_docs.py` — checkpoint: the four
   `--check` runs in Pass criteria clean; `python3 tools/cc/check_ledger_probes.py --id DEF-1182`, `--id DEF-1183`,
   `--id DEF-1184` each read 0.
6. 3-D — checkpoint: both mutations red, then green.
7. 4-A (D2, its own lane, after `TP-472` 2-A has landed on `main` — Risk 8); `python3 scripts/sync_vendor_cc.py`;
   `python3 scripts/sync_selfcheck_tests.py` — checkpoint: the probe flips.
8. 5-A red-team; one fix batch; re-run the touched proofs.
9. `python3 scripts/proof_tier.py --run`; the PR title carries the approval marker (a hook changed); `/handoff`.

## Estimated effort

| Step | Estimate |
|---|---|
| Task 0 | 1 h (run at authoring; a re-run is 20 min) |
| 1-A | 3 h |
| 1-B | 2 h |
| 2-A | 2 h |
| 3-A, 3-B, 3-C | 3.5 h (3-B clears eight spellings; 3-C labels five lines) |
| 3-D | 1.5 h |
| 4-A (D2) | 2 h |
| Red-team and fix batch | half a day |

About two and a half days of lane time. The one pack measured on this tree ran 2.7 times its budget;
read this as a floor.

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Task 0 (authoring, 2026-10-07): 0-A 17 fenced pytest lines (one labelled; the deployed three bodies hold
  7, 6 unlabelled), `npm test` on two `tools:` lines only;
  0-B planted red → 0 B stdout, rc 0, the override control blocked; 0-C `DEC-35`'s "silently" refuted
  (one warning); 0-D this tree resolves `ok_harness_defaults`.
- Date:
