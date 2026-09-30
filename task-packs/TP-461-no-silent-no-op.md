# TP-461 — No silent no-op: a setting the user wrote, a gate the user armed, and a fault inside a guard each say so where the user looks

## Status

- Version target: `0.8.0b3`
- Change type: hooks (blocking and advisory), the engine config loader and doctor, tests, one
  bench corpus row. Hook edits need the approval marker in the PR title (`/ship` step 3).
- **Kind: PACK**
- Ledger rows: closes the remaining half of `DEF-950` (unknown `espalier.toml` keys dropped
  without a word), `DEF-951` (`protected_paths` / `generated_paths` documented as write
  protection and read by no hook), and the remaining half of `DEF-948` (the stop-time override's
  first token is not resolved through `shutil.which`, and the banner does not warn about an
  override that will not start). The 32 silent fail-open sites in `tools/cc/hooks/` have no row;
  this pack is their record and its gate is their close. Second of the four detection-system
  packs (alarm → **silent** → axes → registry; operator, 2026-09-30).
- The rule this pack lands, decided with the operator on 2026-09-30: **fail-open stays allowed
  (a toolbelt, not a security boundary, `docs/STANDING_PRINCIPLES.md` §2); silent fail-open does
  not.** The umbrella crash guards of the four blocking hooks stay fail-closed (that is the
  `DEF-803` class, and it cost one wedged day in a month against zero crash-denies in about
  12,000 guard records on this checkout since the cut); everything *below* the umbrella is
  fail-open **with voice**, and this pack adds no new hard deny except the two adopter zones
  the operator asked for.
- Cross-pack: `TP-460` touches `tools/cc/hooks/session_start.py::_merged_prs_line`; this pack
  touches the same file for the override warning. The adopter-axes pack (`DEF-975`) will promote the hook runner and
  should adopt this pack's voice channels rather than predate them; land this one first.
- Authored 2026-09-30 on the public tree at `4eef108b`. Every "measured" sentence names its
  command; execution re-runs it.

---

## Motivation

The 2026-09-30 review of the 46 post-cut findings found that six of them are one shape: the
harness accepts an input and quietly does nothing with it, and the suite certified the
silence. Measured at authoring:

- **A config typo is invisible.** `espalier/config.py::load_config` derives its accepted keys
  from `dataclasses.fields(HarnessConfig)` and drops the complement. Driven 2026-09-30: an
  `espalier.toml` carrying `protcted_paths = ["typo/"]` and an unknown `[stack]` table loads
  with **zero warnings** (`warnings.catch_warnings(record=True)` around `load_config`), while
  `examples/espalier.toml` promises the opposite (`DEF-950`'s text quotes it). The pin,
  `tests/test_config.py::TestLoadConfig::test_ignores_unknown_keys`, asserts only that the load
  does not crash; its docstring is the only place the silence is called a contract.
- **A documented protection protects nothing.** `command grep -rn "protected_paths\|generated_paths"
  tools/cc/hooks/` prints nothing. The two fields flow into `BuildPlan.mutable_zones` /
  `read_only_zones` and stop at the drift comparison (`DEF-951`). `examples/espalier.toml`
  sells them as "Paths the harness should never touch" and "generated and should be treated
  as read-only".
- **A fault inside a guard reads as "nothing found".** One reading pass over every `except`
  handler in `tools/cc/hooks/*.py` outside `_bash_patterns.py` (236 handlers; the record is
  `reports/detection-review-2026-09-30/G2_census.md`, gitignored) classified **44 as fail-open,
  32 of them silent and 12 speaking, and none writing an audit record**, so `/status --log`
  sees none of them. Those numbers are one reader's classification (PROBABLE); 0-A derives the
  population mechanically and the derived number replaces them. Four sites were re-read by a
  second reader and hold (VERIFIED): a kill-switch scan exception becomes "no findings"
  (`write_guard.py`, the `except` around the integrity scan); a speed-bump exception becomes
  "did not fire" (`write_guard.py`, the `except` around the checkpoint dispatch); unreadable or
  unparseable stdin becomes `{}` and the blocking hooks allow (`_hook_utils.py::read_stdin_safely`);
  `stop_gate.py` returns 0 with no message when it resolves no test files (`if not test_args:
  return 0`).
- **The suite pinned the silence.** `tests/test_hooks.py::test_malformed_stdin_exits_zero` (the
  `plan_guard` case), `tests/test_edge_cases.py` (the `stop_gate` malformed- and empty-stdin
  cases) and six more hand-confirmed pins assert exit 0 and nothing about a message. The
  removed `test_oserror_spawn_failure_allows` ("a spawn failure must fail OPEN (allow)") was
  the same shape and certified the Windows `npm test` gate that was green while never running
  (`8db4ec38`).
- **A side bug in the arming counter.** `_hook_utils.py::_locked_increment(state_dir, name)`'s
  read-only-state-dir branch returns `_read_counter(state_dir)` without `name`, so a caller
  counting anything but the default file reads the default file's count (VERIFIED by reading
  both signatures; no row).

The precedent for the fix shape is `docs/sharp-edges/malformed-json-fail-open.md`: **one
chokepoint plus one gate, never N point patches**, with an `ok <reason>` pragma for the
conscious exemption. This pack has two chokepoints (the once-a-session voice, the spawn) and
two gates (the fail-open census, the config-field census).

---

## Scope (in)

- **0-A** the oracles: the config drive; the field-consumer census; the mechanical fail-open
  census with its predicate stated and its refuting result; the `shutil.which` shim check.
- **1-A** config voice: unknown keys and unknown tables warn with the file, the key and the
  nearest known name; `doctor` reports them (the example file's promise); a census test that
  every `HarnessConfig` field has a behavioural consumer or a declared display-only reason.
- **1-B** the adopter zones: `protected_paths` and `generated_paths` read from `espalier.toml`
  by the hook side through one string-list reader shared with `plan_guard`, joined to the
  three zone iterations in `_protected_zones.py` (one edit covers all thirteen callers), the
  existing deny reason's text naming the two keys, a bench row, and a doc line.
- **1-C** the voice contract in hooks: a once-a-session speaking helper; the derived-population
  gate over fail-open sites (speak, or carry `# fail-open: ok <kind> <reason>`); the four
  verified silent sites made to speak; the crash-deny message gains its remedy line; the eight
  pins gain their message assertion; the counter side bug.
- **1-D** the spawn chokepoint in hooks: one helper that resolves the first token through
  `shutil.which` (PATHEXT on Windows), returns a typed failure instead of raising, and is the
  only spawn in `tools/cc/hooks/`, gated by the population `subprocess_contracts` already
  derives; the stop-time override and the plain pytest branch route through it; the banner
  warns about an override whose first token does not resolve.
- **2-A** the red-team.
- **Files this pack may write:** `espalier/config.py`, `espalier/doctor.py`, `espalier/models.py`
  (a docstring only), `tests/test_config.py`, `tests/test_config_fields_consumed.py`,
  `tools/cc/hooks/_hook_utils.py`, `tools/cc/hooks/write_guard.py`,
  `tools/cc/hooks/_denial_reasons.py`, `tools/cc/hooks/plan_guard.py`,
  `tools/cc/hooks/stop_gate.py`, `tools/cc/hooks/session_start.py`, `tools/cc/hooks/_speedbump.py`,
  `tools/cc/hooks/_integrity.py`, `tools/cc/hooks/_explain_path.py`, every other
  `tools/cc/hooks/*.py` the census names (pragmas or speech), their `espalier/_vendor/cc/hooks/`
  mirrors by `scripts/sync_vendor_cc.py`, `tests/test_failopen_voice.py`,
  `tests/test_spawn_chokepoint.py`, `tests/test_hooks.py`, `tests/test_edge_cases.py`,
  `tests/test_stop_gate.py`, `tests/test_write_guard.py`, `tests/test_denial_reasons.py`,
  `tests/test_subagent_stop.py`, `tests/test_session_start_source_aware.py`,
  `bench/corpus/BC-<next>-adopter-protected-path.json`, `examples/espalier.toml`,
  `docs/HOOKS.md`, `docs/CONVENTIONS.md` (the stdin-returns-`{}` convention gains its voice
  clause), `docs/sharp-edges/plan-guard-adopter-source-roots.md` (names the reader Fix 4 moves),
  `CLAUDE.md` (the write_guard row and the maintenance table), `CHANGELOG.md`,
  `espalier/_vendor/selfcheck_tests/test_config.py` (by `scripts/sync_selfcheck_tests.py`,
  never by hand; `tests/test_selfcheck_tests_parity.py` pins the copy), `espalier/cli.py` (only
  if the doctor finding's home is there; 1-A reads `espalier/doctor.py` first),
  `task-packs/FORWARD_LEDGER.md` and `task-packs/LEDGER_PROBES.json` (three strikes through the
  verb). The record surfaces scope-check lists as citing these symbols (`cc/blueprints/`, the
  walk sheets, `bench/demo/`, `docs/session-archive.md`, `memory/` entries, archived packs) are
  history, never edited; accept them with that reason at execution's scope-check.

## Scope (out)

- **A `silent_failopen` `/scan` sub-mode.** The population is `tools/cc/hooks/` on the self-host
  tree only; the census test in 1-C is the gate, and a scanner would be a second copy of the
  same AST behind about eleven registration sites (`cli.cmd_scan`, `scan_composition`,
  `fusion_manifest`, six test files, `scan.md`, the root `CLAUDE.md`) for no new reader. If an
  adopter ever ships hooks of their own, that is the day to lift the test into a scanner.
- **The engine's own spawns** (`espalier/cli.py`, `doctor.py`, `release_check.py` …): they speak
  through CLI output already, and the hook side cannot import an engine helper. The chokepoint
  in 1-D is for `tools/cc/hooks/`; an engine twin is a sibling row if a silent engine spawn is
  found (the `subprocess_contracts` scanner over `espalier/` is the oracle for that question,
  and 0-A runs it once to say whether the row is owed).
- **Flipping any sub-check to fail-closed.** The kill-switch scan and the speed-bump swallows
  are commented as deliberate anti-wedge choices; this pack makes them speak. A deny on a
  component fault is the 2026-09-08 wedge again.
- **The plan's naming of `protected_paths` as `mutable_zones`** (`DEF-951`'s second clause): the
  hook reads `espalier.toml` directly, as `plan_guard` does, so the plan field is not on the
  deny path. Renaming a plan field is schema churn across `diffing.py`, the saved plans and
  their tests; not taken here, and the row's Reach line says so.
- **`_bash_patterns.py`'s 25 silent handlers**: parser fallbacks that coarsen a match rather
  than disarm a decision; the file carries one file-level pragma with that reason, and the
  census test honours it.
- **`DEF-915` / `DEF-947`** (a wired interpreter that cannot start, so every hook is silent
  from the first call): the launch-as-wired hook runner is the adopter-axes pack's new
  machinery (`DEF-975`); the voice channels landed here are what it will assert on.
- **`DEF-968`** (the interpreter-unresolved warning's first-word extractor): its own row; 1-D's
  override warning uses `shlex` and `shutil.which` so as not to repeat that defect, and the red
  team is asked to check that it does not.
- **`lane_count`** (echoed into the handoff report, no behaviour): 1-A's census declares it
  display-only with that reason rather than removing a field an adopter may have set.

---

## Task 0 — Verify (may end this pack)

Outcomes: **build**; **partial** (a half already landed: drop it and continue); **do not
build** (the refuting results below; stop and re-raise). Records go to `reports/tp461/`
(gitignored, record-rooted).

### 0-A-1 The config drive (measured at authoring; re-run)

**Refuting result:** the drive prints a warning naming `protcted_paths` — 1-A's loader half is
already landed.

```bash
python3 - <<'EOF'
import warnings, tempfile, pathlib, sys
sys.path.insert(0, ".")
from espalier.config import load_config
d = pathlib.Path(tempfile.mkdtemp())
(d / "espalier.toml").write_text('protected_paths = ["src/core/"]\nprotcted_paths = ["typo/"]\n[stack]\nsource_extensions = [".astro"]\n', encoding="utf-8")
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    cfg = load_config(d)
print("warnings:", [str(x.message) for x in w]); print("protected_paths:", cfg.protected_paths)
EOF
```

Measured 2026-09-30: `warnings: []`, `protected_paths: ['src/core/']`. **Build.**

### 0-A-2 The field-consumer census (deriving command)

**Refuting result:** every field has a reader outside `models.py`, `config.py`, `diffing.py`
and the drift compare in `cli.py` — then 1-A's census test is written green and the pack's
claim about `protected_paths` is wrong; re-raise.

```bash
python3 - <<'EOF'
import dataclasses, subprocess, sys
sys.path.insert(0, ".")
from espalier.models import HarnessConfig
for f in dataclasses.fields(HarnessConfig):
    out = subprocess.run(["git", "grep", "-l", f.name, "--", "espalier/", "tools/cc/", ":!espalier/models.py", ":!espalier/config.py", ":!espalier/_vendor/"], capture_output=True, text=True).stdout.split()
    print(f.name, sorted(out))
EOF
```

Measured 2026-09-30 by the review lane (re-derive; PROBABLE until the command is re-run):
`protected_paths` and `generated_paths` reach only `harness_config.py`, `diffing.py` and
`cli.py`'s drift compare; `lane_count` reaches only `handoff.py` (display).

### 0-A-3 The fail-open census (the predicate, stated before the number)

**The predicate (hypothesised; 0-A tests it):** a *deciding handler* is an `except` clause in
`tools/cc/hooks/*.py` whose body (a) returns a value (`return 0`, `return None`, `return {}`,
`return []`, `return False`, `return ""`), or (b) assigns an empty or false default (`None`,
`[]`, `{}`, `0`, `False`, `""`) to a name the enclosing function reads afterwards — the two
verified `write_guard` sites are exactly that shape (`kill_switch_findings = []`,
`_sb_fire = None`), and a predicate that called assignment "telemetry" would have missed both
(the authoring failure-mode review) — or (c) whose enclosing function returns such a value on
the line after the `try`. Handlers whose body is `pass` or `continue` with no later read are
*telemetry-shaped* and outside the population. **The population is every deciding handler,
speaking or silent**, so it does not shrink as sites are fixed; the gate's floor is that
number, and the assertion is per member: it speaks (`raise`, or a call in the speaking set —
`warn`, `warn_exc`, `append_audit`, `_audit_deny`, `_audit_block`, `deny`, `block`,
`say_once`, a `print` with `file=sys.stderr`) or carries a `# fail-open:` pragma on the
`except` line or the line above.

```bash
python3 scripts/failopen_census.py --root tools/cc/hooks --json   # written by 0-A as the census's first form; 1-C moves the walk into the test
```

**Refuting results:** (a) the predicate yields fewer than **15** silent members of the
deciding population — the class is smaller than the reading pass said; land 1-A, 1-B and 1-D,
and 1-C shrinks to the four verified sites plus the pins; (b) on reading a sample of ten derived sites, more than five
are telemetry the predicate mis-classed — the predicate is wrong; re-raise it before writing
pragmas on a hundred sites (`STANDING_PRINCIPLES` §15: many attempts, a different failure each
time, is a mis-specification).

The reading pass's 44 / 32 / 12 is the prior. 0-A records the derived number, the sample read,
and the per-file table.

### 0-A-4 The shim check and the engine-spawn question

`shutil.which("npm")` on a Windows host returns `…\npm.cmd` (PATHEXT), which
`subprocess.run(["npm", "test"])` without `shell=True` cannot start — the `DEF-948` filing drove
this on Windows 11 on 2026-09-29; 0-A re-runs `python -c "import shutil; print(shutil.which('npm'))"`
on the Windows box and pastes the line. **Refuting result:** `which` returns `None` with npm on
PATH — then the chokepoint's resolution is not enough and the row's `.cmd` re-parse note is the
next question; re-raise.

The spawn population is an AST walk, not the `subprocess_contracts` scanner: that scanner
keeps only calls whose first token is an espalier CLI signature and drops `git`, `pytest`,
`gh` and every other binary (the authoring review read its filter), so it would enumerate
almost none of the sites. The deriving command, whose count is 1-D's floor:

```bash
python3 - <<'PY'
import ast, pathlib
n = 0
for f in sorted(pathlib.Path("tools/cc/hooks").glob("*.py")):
    for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
           and node.func.attr in {"run", "Popen", "call", "check_output", "check_call"} \
           and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
            n += 1; print(f"{f}:{node.lineno} {node.func.attr}")
print("sites:", n)
PY
```

Measured at authoring by `command grep -c` over the same names: 28 sites across ten files,
eleven of them in `session_start.py` (the reporter's `gh` and `git` reads). The walk above
is the number that counts. Then the engine question: run the walk over `espalier/` once and
read whether a silent spawn exists there, to say whether an engine-side row is owed (Scope
out).

---

## Relevant memory

Recent pattern: three of the six post-cut fixes that reached `tools/cc/hooks/` were reviewed
red on the *repair*: a once-a-session block that would have switched the later gates off on
every Stop (caught by the failure-mode review of `8db4ec38`), and two test pins written
against the macOS answer. The voice channels in 1-C are the same kind of repair; expect the
red-team to find the wedge, not the silence.

| Entry | Where |
|---|---|
| Malformed / Non-Dict JSON Fail-Open (Class-B) | `docs/sharp-edges/malformed-json-fail-open.md` |
| A friction fix and a fail-open are one edit seen from two sides | `memory/a-friction-fix-and-a-fail-open-are-one-edit.md` |
| Hook authoring | `memory/hook-authoring.md` |
| Complacent oracle | `memory/complacent-oracle.md` |
| Completeness gate must discover its population | `memory/completeness-gate-must-discover-its-population.md` |
| Renderers That Discard Fingerprint Data Fail Silently | `docs/SHARP_EDGES.md :: Renderers That Discard Fingerprint Data Fail Silently` |
| A hook-denied Bash call runs NONE of its commands | `docs/SHARP_EDGES.md :: A hook-denied Bash call runs NONE of its commands — a bundled git add is skipped` |

Resolved at authoring by `python3 tools/cc/hooks/_recall.py "fail-open gate silent allow user
not told"`, `"every relief needs a must-deny twin"` and `"speak once per session audit record
flag"`; re-run rather than trust this list if the pack has been sitting.

Files this pack touches, so the folder-`CLAUDE.md` ladder fires on entry: `tools/cc/hooks/`
(hook contract; exit-code channel rule; sync the vendor mirror), `bench/corpus/` (a new
refusal shape lands with the row that proves it), `espalier/` (engine only imports engine).

---

## Implementation

### 1-A Config voice

**Fix 1 — unknown keys and tables warn** *(prescribed; refuted if the loader's existing
type-mismatch warning path is not `warnings.warn` — 0-A-1's drive shows the channel):*

```python target=espalier/config.py
    fields = {f.name for f in dataclasses.fields(HarnessConfig)}
    unknown = sorted(set(data) - fields)
    for key in unknown:
        near = difflib.get_close_matches(key, sorted(fields), n=1, cutoff=0.6)
        hint = f" (did you mean `{near[0]}`?)" if near else ""
        warnings.warn(
            f"{candidate.name}: unknown key `{key}` is ignored{hint}; "
            f"known keys: {', '.join(sorted(fields))}",
            stacklevel=2,
        )
    filtered = {k: v for k, v in data.items() if k in fields}
```

A TOML table (`[stack]`) arrives as a dict-valued key and is caught by the same loop. `import
difflib` joins the imports (stdlib). **Keys other readers own are not unknown:** the self-host
`espalier.toml` carries `record_requires_exclusions` and `record_remote_required`, read by
`scripts/record_snapshot.py` and by nothing in `HarnessConfig` (the authoring failure-mode
review: the loop as first written would have warned on every load of this tree, and the
obvious response, deleting the key, removes the refusal that keeps excluded material out of a
pushed record). So `config.py` declares `FOREIGN_KEYS = {"record_requires_exclusions":
"scripts/record_snapshot.py", "record_remote_required": "scripts/record_snapshot.py"}` and the
loop skips them; a live-tree pin in `tests/test_config.py` loads the self-host `espalier.toml`
and asserts zero unknown-key warnings, so a reader that adds a key without declaring it reds
here, not in an adopter's terminal. `candidate` is the name the function already binds for
the file it read (`config_path or repo_root / CONFIG_NAME`); the ordinary call passes no
`config_path`, so a message built on `config_path.name` crashes on exactly 0-A-1's drive —
the authoring review caught that shape.

**Fix 2 — `doctor` reports them** *(prescribed):* a finding in `espalier/doctor.py` beside the
existing config checks, `config_unknown_keys`, WARN, listing the keys with the same hint; it
reads `load_config`'s warnings by running the load under `warnings.catch_warnings(record=True)`
rather than re-parsing the file, so the two cannot disagree. `examples/espalier.toml`'s
sentence about doctor is then true; keep it.

**Fix 3 — the field-consumer census test** *(prescribed; the authoring failure-mode review
refuted a grep-count shape: `harness_config.py` and `cli.py` already mention `protected_paths`,
so a count would be green before 1-B and stay green after the reader's use was deleted, held up
by its own docstring):* `tests/test_config_fields_consumed.py` derives
`dataclasses.fields(HarnessConfig)` and checks each against a **declared consumer map with a
witness**: field → the `path::symbol` that acts on it (`protected_paths` →
`tools/cc/hooks/_hook_utils.py::adopter_protected_prefixes`, `plan_exempt_prefixes` →
`tools/cc/hooks/plan_guard.py::_load_adopter_exempt_prefixes`, …), or a display-only reason
(`lane_count`: "echoed into the handoff report; no behaviour by design"). The test asserts the
symbol exists (AST, not grep) and that the field name appears inside that symbol's body. A
field with no map entry reds; a map entry whose symbol is gone reds. Floor: every field has an
entry. **Earn the red:** before 1-B lands, `adopter_protected_prefixes` does not exist and the
test reds on both zone fields; after 1-B it is green; the mutation is renaming the field inside
the reader.

**Checkpoint:** 0-A-1's drive prints two warnings (`protcted_paths` with the hint, `stack`);
`pytest -q tests/test_config.py tests/test_config_fields_consumed.py` with the field test red
until 1-B; `test_ignores_unknown_keys` is renamed to what it now asserts (the load survives
*and* warns), never deleted.

### 1-B The adopter zones in `write_guard`

**Fix 4 — one string-list reader on the hook side** *(prescribed; refuted if `plan_guard`'s
tests pin the reader's module of origin — then the shared function lives in `plan_guard` and
`_hook_utils` imports it, which is the wrong direction; 0-A reads the pins first):* extract
`plan_guard.py::_load_adopter_exempt_prefixes` and its regex fallback into
`_hook_utils.py::read_toml_string_list(root, key) -> tuple[str, ...] | None` (tomllib → tomli →
the regex fallback, the same three arms; malformed input speaks through `warn`, as today).
`plan_guard` calls it for `plan_exempt_prefixes`; nothing else about `plan_guard` changes, and
its existing tests are the safety net for the extraction.

**Fix 5 — the zones join the deny iteration** *(prescribed):*

```python target=tools/cc/hooks/_hook_utils.py
def adopter_protected_prefixes(root: Path) -> tuple[tuple[str, str], ...]:
    """(prefix, kind) pairs from espalier.toml: kind is "protected" for
    ``protected_paths`` ("never touch") and "generated" for ``generated_paths``
    ("read-only; regenerate, do not hand-edit"). Empty on a tree with neither
    key. Read on every call, like plan_exempt_prefixes: the adopter edits the
    file and expects the next write to see it. Never raises: this runs under
    a blocking hook's umbrella, and a raise here would deny every call."""
    out = []
    for key, kind in (("protected_paths", "protected"), ("generated_paths", "generated")):
        for raw in read_toml_string_list(root, key) or ():
            p = raw.replace("\\", "/").lstrip("./").rstrip("/")
            if not p or p in (".", ".."):
                say_once(root, f"zone-{key}", "write_guard", "config_zone_ignored",
                         f"espalier.toml: {key} entry {raw!r} would cover the whole tree; ignored")
                continue
            out.append((p + "/", kind))   # a directory prefix; `data` must not match data.py
    return tuple(out)
```

A prefix is matched at a path boundary (`rel == p.rstrip("/")` or `rel.startswith(p)`), never
by bare `startswith` on the raw string — the first draft's `p if p.endswith("/") else p` did
nothing, so `"data"` would have denied `database.py` (the authoring failure-mode review).
**The two kinds sit at two sites, deliberately:** `protected_paths` ("never touch") joins the
harness prefixes through `protected_prefixes` and so covers every tool, Bash deletes included;
`generated_paths` ("do not hand-edit") is checked in the Write / Edit / NotebookEdit branch of
`check_write_edit` only, so a build's own `rm -rf dist` or regeneration step is not refused —
a "read-only" zone that blocked the generator would be the friction the governing frame
ranks highest.

The join point is not in `write_guard.py`: its thirteen zone call sites all reach
`tools/cc/hooks/_protected_zones.py::_is_protected`, `::_encloses_protected` and
`::_protected_not_allowed_inodes`, and those three iterate
`_hook_utils.harness_protected_prefixes(root)` (the authoring review counted the sites). So
the one edit is a sibling `_hook_utils.protected_prefixes(root)` that returns the harness
prefixes followed by the adopter `protected_paths` ones, and the three iterations in
`_protected_zones.py` consume it — every Write, Edit, Bash and PowerShell write-intent caller
is covered without a touch, which is the shape Core Rule 12 asks for (`generated_paths` is the
one-site exception above). The deny keeps the one existing reason,
`_denial_reasons.PROTECTED_ZONE_WRITE`, whose text gains a clause: "a harness zone, or a path
your `espalier.toml` names under `protected_paths` (never touch) or `generated_paths`
(regenerate; do not hand-edit)". No new reason id; `tests/test_denial_reasons.py` re-pins the
text. **Placement:** `_is_protected` runs wherever it runs today; the maintenance-mode
early-return that skips the zone check therefore skips the adopter zones too. That is stated
in `CLAUDE.md`'s maintenance table as the deliberate reading (maintenance mode is a whole-hook
switch the operator sets on purpose), and the red team is asked whether an adopter's zones
should instead survive it — if so, the adopter arm moves before the gate as its own call.

**Fix 6 — the bench row and the doc line** *(prescribed):* one corpus file,
`bench/corpus/BC-<next>-adopter-protected-path.json`, in the shape its neighbours use: a Write
into `data/` on a tree whose `espalier.toml` names `protected_paths = ["data/"]` must deny; a
Write into `data2/` must allow (the prefix twin); an Edit under `dist/` with
`generated_paths = ["dist/"]` must deny. `docs/HOOKS.md`'s `write_guard` section gains the two
deny messages; `CLAUDE.md`'s hook table row says "and the adopter's `protected_paths` /
`generated_paths` from `espalier.toml`".

**Earn the red:** `tests/test_write_guard.py` gains the three cases; each reds when
`protected_prefixes` is made to return the harness prefixes alone. A fourth case: a malformed
`protected_paths = "data/"` (a string, not a list) warns and protects nothing — the same
degrade `plan_guard` has, and it now *speaks*.

**Checkpoint:** `python3 bench/run_benchmark.py` counts the new row; `pytest -q
tests/test_write_guard.py tests/test_hooks.py tests/test_denial_reasons.py
tests/test_config_fields_consumed.py` (the field test now green); `mypy tools/cc/hooks/`;
`python3 scripts/sync_asset_docs.py` after the `docs/HOOKS.md` edit (its byte mirror under
`espalier/assets/docs/` is pinned by `tests/test_deploy_doc_parity.py::TestSourceAssetDocByteParity`,
which is the test that catches the skipped sync).

### 1-C The voice contract in hooks

**Fix 7 — the once-a-session speaking helper** *(prescribed; the shape is
`stop_gate.py::GATE1_SPAWN_FAILURE_REPORTED_FLAG`, generalised):*

```python target=tools/cc/hooks/_hook_utils.py
_SAID_THIS_PROCESS: set[str] = set()

def say_once(root: Path, key: str, hook: str, event_type: str, message: str, **details: object) -> None:
    """Speak about a fail-open once per session: a stderr line every time it
    would fire is noise, silence is the defect this exists to end. Writes one
    audit record (so `/status --log` counts it) and one stderr line, then a
    flag `once_<key>` under STATE_DIR; a later call with the same key in the
    same session does nothing. NEVER RAISES: every step sits in its own
    try/except, because this runs inside blocking hooks whose umbrella turns a
    raise into a crash-deny (`Path.exists` propagates EACCES on an unreadable
    state dir below 3.14). When the flag cannot be written (a read-only state
    dir), the in-process set keeps it to once per hook process."""
```

The flag's `once_` prefix joins `session_start.py::_clean_state_flags` as a **glob** beside the
existing `speedbump_*` glob — that cleaner iterates a hand-kept list today, and a flag left off
the list turns "once a session" into "once ever" (the authoring failure-mode review). A test
writes a flag through `say_once`, runs a fresh-session clean, and asserts it is gone. Advisory
hooks may keep `warn` for one-off text; a *blocking* hook's fail-open uses `say_once` so the
record exists.

**Fix 8 — the four verified sites speak** *(prescribed, one each):* the kill-switch scan
exception (`say_once(root, "integrity-scan", "write_guard", "pretooluse_failed_open_integrity_scan", …)`);
the speed-bump dispatch exception (`"pretooluse_failed_open_speedbump"`); the bad-stdin case;
`stop_gate`'s `if not test_args: return 0` gains a stderr line naming the resolved paths it
looked for.

The bad-stdin case needs the reader to *distinguish* empty from unparseable, which today it
does not (both return `{}`), and the reader has no `root` to speak with. So the reader returns
an empty dict that remembers why, and the four blocking hooks ask it:

```python target=tools/cc/hooks/_hook_utils.py
class BadStdin(dict):
    """An empty payload that remembers why it is empty. Every existing caller
    treats it as ``{}`` (falsy, ``.get`` works); a blocking hook checks
    ``isinstance(data, BadStdin)`` and speaks once. ``fault`` is the failure's
    class name (``UnicodeDecodeError``, ``JSONDecodeError``, ``NotADict``),
    never the payload's text."""
    __slots__ = ("fault",)
    def __init__(self, fault: str) -> None:
        super().__init__()
        self.fault = fault
```

`read_stdin_safely` returns `BadStdin(...)` on a payload that is non-empty *after stripping
whitespace* and cannot be used, and a plain `{}` on an empty one (a healthy Claude Code sends
JSON on every event; empty stdin comes from hand-run hooks and tests, and a lone newline must
not speak). In each blocking hook's `_run_main`, after the
read: `if isinstance(data, BadStdin): say_once(root, "bad-stdin", <hook>,
"hook_failed_open_bad_stdin", ..., fault=data.fault)`, then the existing early return. The
reporters are left as they are. The
write-counter's I/O branch (`_locked_increment`'s read-only-state-dir path) speaks once and
**passes `name` through** (the side bug).

**Fix 9 — the crash-deny remedy line** *(prescribed):* `WRITE_GUARD_INTERNAL_ERROR` and its
three siblings gain one sentence: "re-issue once; if every call is denied the guard is wedged:
`/status --log` counts it, and the repair is made from a terminal outside this session."
`tests/test_denial_reasons.py` pins the text.

**Fix 10 — the gate** *(prescribed; the predicate is 0-A-3's and may have been re-raised
there):* `tests/test_failopen_voice.py::test_every_deciding_fail_open_speaks_or_declares`
walks `tools/cc/hooks/*.py` with 0-A-3's predicate, floors the *deciding population*
(speaking and silent together) at the number 0-A derived (declared, with the deriving command
in the docstring), and asserts each member calls a speaking name or carries
`# fail-open: ok <kind> <reason>` where `<kind>` is one of
`telemetry`, `cleanup`, `text-fallback`, `deliberate` (the two `_integrity.py` unparseable-settings
skips are `deliberate`, their rationale already pinned by
`tests/test_integrity.py::test_unparseable_settings_is_silent_for_blockers_by_default`).
`_bash_patterns.py` carries a file-level `# fail-open: ok text-fallback parser coarsens, never
disarms` on line 1 and the walk honours it. **Earn the red:** remove one `say_once` call from
Fix 8; the gate names the site.

**Fix 11 — the pins get their twin** *(prescribed):* each of the eight hand-confirmed pins
(`tests/test_hooks.py::test_malformed_stdin_exits_zero` ×2, `tests/test_edge_cases.py`'s two
`stop_gate` stdin cases, `tests/test_subagent_stop.py`'s two, `tests/test_session_start_source_aware.py`'s
reporter crash, `tests/test_config.py::test_ignores_unknown_keys`) keeps its exit-code
assertion and gains the message assertion (stderr contains the site's line, or the audit
record exists), so a future silence reds. The advisory ones assert stderr only. A pin whose
site is legitimately silent (an empty stdin) says so in its name.

**Checkpoint:** `pytest -q tests/test_failopen_voice.py` green with the floor met; the eight
pins green; `python3 tools/cc/hooks/write_guard.py` driven with a payload while
`.espalier/integrity.json` is unreadable prints one stderr line and writes one
`pretooluse_failed_open_integrity_scan` record, and a second call in the same session prints
nothing; `mypy tools/cc/hooks/`; `python3 scripts/sync_vendor_cc.py` leaves no diff.

### 1-D The spawn chokepoint

**Fix 12 — one spawn in the hooks** *(prescribed; refuted if any hook spawns with
`shell=True` for a reason a resolver cannot serve — 0-A's `subprocess_contracts` report over
`tools/cc/hooks/` names each site and its shape):*

```python target=tools/cc/hooks/_hook_utils.py
@dataclasses.dataclass(frozen=True)
class SpawnFailure:
    argv: tuple[str, ...]
    error: str          # the exception's class name; never its message (a message can quote a path)
    resolved: str | None  # what shutil.which returned for argv[0], or None

def spawn_checked(argv: Sequence[str], **kwargs) -> subprocess.CompletedProcess | SpawnFailure:
    """The only subprocess call in tools/cc/hooks/. Resolves argv[0] through
    shutil.which (PATHEXT on Windows, so `npm` finds npm.cmd -- DEF-948), and
    returns a SpawnFailure instead of raising when the program cannot start,
    so every caller must decide what to say. Timeouts propagate as today."""
```

Resolution rules (the authoring failure-mode review named each hole): a first token holding a
path separator resolves against `root`, never the hook's cwd (the relative-override fix of
`8db4ec38` must survive); a bare token resolves with `shutil.which`; a Windows resolution to a
`.cmd` or `.bat` is refused with a `SpawnFailure(error="CmdShimMetachar")` when any argument
carries a `cmd.exe` metacharacter (`&`, `|`, `<`, `>`, `^`, `%`), because the shim re-parses
its line and a different command could run — the caller speaks, the gate does not start it.
One splitter, `_hook_utils.split_command(text)` (`shlex.split(posix=os.name != "nt")`), is
used by the stop gate and by the banner's warning so the two never disagree on a quoted path.
Every `subprocess.run` / `Popen` in `tools/cc/hooks/` routes through it or carries
`# spawn: ok <reason>` (the `subprocess_contracts` pragma shape). The population test,
`tests/test_spawn_chokepoint.py`, derives the sites with 0-A-4's AST walk (its own copy, in
the test), floors at the count 0-A printed, and asserts each is the chokepoint, routed, or
pragma'd. The reporter's eleven `gh`/`git` reads in `session_start.py` are the likely pragma
population (a reporter that cannot spawn `gh` prints no `Open PRs:` line and that is its
contract); the gates' spawns route.

**Fix 13 — the two stop-gate branches** *(prescribed):* `_run_env_override_gate` keeps its
once-a-session block on a `SpawnFailure` (the operator armed a command that cannot start) and
its reason now names `resolved` (so "npm resolved to npm.cmd and still failed" and "npm did
not resolve" read differently); the plain pytest branch, on a `SpawnFailure`, calls `say_once`
(`"stop_failed_open_pytest_spawn"`) and allows — a Stop that re-blocks on every fault is the
hostile shape the umbrella comment already names.

**Fix 14 — the banner warns about an override that will not start** *(prescribed; the sibling
`_warn_if_hook_interpreter_unresolved` has `DEF-968`'s first-word defect — do not copy it):*
`session_start.py` reads `ESPALIER_STOP_GATE_TEST_CMD`, splits it with
`_hook_utils.split_command`, resolves token 0 by the chokepoint's rules, and prints one
advisory line when it does not resolve, naming the token and the platform's spelling
(`npm.cmd`, or the full path). A reporter; exit 0 always.

**Earn the red:** `tests/test_stop_gate.py` gains a case where `shutil.which` is monkeypatched
to return a `.cmd` path and `subprocess.run` records the resolved argv (mutation: bypass the
resolver; the case reds); a case where the plain branch's spawn fails and an audit record
exists (mutation: drop `say_once`; reds); `tests/test_session_start*.py` gains the unresolved-
override line (mutation: the banner stays silent; reds).

**Checkpoint:** `pytest -q tests/test_spawn_chokepoint.py tests/test_stop_gate.py
tests/test_session_start*.py`; on the Windows box, a tree with `ESPALIER_STOP_GATE_TEST_CMD="npm
test"` and a green `package.json` script allows at Stop with no block and no respell advice
(the row's remaining half), recorded in Landing with the host.

### 2-A Red-team

What this pack is most likely to have gotten wrong, in the author's order:

1. **The predicate in 0-A-3** over-collects (telemetry handlers that return a value) or
   under-collects (a fail-open expressed as a bare `return` inside a `try` with no handler at
   all — the `if not test_args: return 0` shape has *no* `except`). Ask for the fail-open the
   gate cannot see, and whether the floor hides a deleted site.
2. **`say_once` as a new wedge**: the flag write itself can fail (read-only state dir); the
   helper must never raise and must not make the caller's decision. Ask for the mutation where
   `say_once` raising turns an allow into a crash-deny.
3. **The adopter zones under maintenance mode** (Fix 5): the zone check is skipped under
   `ESPALIER_MAINTENANCE_MODE=1`, adopter zones with it. Ask whether an adopter's `data/`
   should survive the switch (the self-host `espalier.toml` names no zones today, so nothing is
   locked out now), and whether a `generated_paths` entry that is also a build output the
   adopter edits by hand (a checked-in `dist/`) is friction the deny text must answer.
4. **The stdin voice** (Fix 8): Claude Code sends empty stdin for some events; a warning there
   is noise on every call. Ask which events, and whether "non-empty but unparseable" is the
   right line.
5. **`shutil.which` on a `.cmd` that re-parses its arguments** (`DEF-948`'s last note): a test
   command with quotes may still break after resolution. Ask for the spelling that resolves and
   still fails.
6. **The extraction of the toml reader** (Fix 4) changing `plan_guard`'s degraded-mode
   behaviour by one edge (duplicate keys, table-scoped keys).

Lanes: `code-reviewer` and `failure-mode-reviewer` on a snapshot clone of the diff. A clean
red-team is recorded as a result.

---

## Affected symbols

### Changed-semantics
- `espalier/config.py::load_config` (unknown keys and tables warn; nothing else changes)
- `espalier/doctor.py` (a `config_unknown_keys` finding; execution names the check function
  it joins)
- `tools/cc/hooks/_hook_utils.py::read_stdin_safely` (speaks once on a non-empty unparseable
  payload)
- `tools/cc/hooks/_hook_utils.py::_locked_increment` (the read-only branch passes `name`
  through and speaks once)
- `tools/cc/hooks/_protected_zones.py::_is_protected`, `::_encloses_protected`,
  `::_protected_not_allowed_inodes` (iterate `protected_prefixes`, harness then adopter)
- `tools/cc/hooks/_denial_reasons.py::PROTECTED_ZONE_WRITE` (the text names the two
  `espalier.toml` keys)
- `tools/cc/hooks/write_guard.py::check_write_edit` (the integrity scan and speed-bump faults
  speak; the zone iteration is untouched)
- `tools/cc/hooks/plan_guard.py::_load_adopter_exempt_prefixes` (delegates to the shared reader)
- `tools/cc/hooks/stop_gate.py::_run_env_override_gate` (resolves through the chokepoint; the
  reason names the resolution)
- `tools/cc/hooks/stop_gate.py::_gate_pytest` (the plain branch: a `SpawnFailure` speaks once
  and allows; the no-test-files return speaks)
- `tools/cc/hooks/session_start.py` (one advisory line for an unresolvable override)
- `tools/cc/hooks/session_start.py::_clean_state_flags` (the `once_*` glob joins the cleaner)
- `tools/cc/hooks/_denial_reasons.py::WRITE_GUARD_INTERNAL_ERROR` and its three siblings (the
  remedy sentence)

### Renamed
- `tests/test_config.py::TestLoadConfig::test_ignores_unknown_keys` → a name that says it
  warns (execution picks it; the old name is the removal)

### Added-paths
- `tools/cc/hooks/_hook_utils.py::read_toml_string_list`
- `tools/cc/hooks/_hook_utils.py::adopter_protected_prefixes`
- `tools/cc/hooks/_hook_utils.py::protected_prefixes` (harness prefixes followed by the adopter ones)
- `tools/cc/hooks/_hook_utils.py::say_once`
- `tools/cc/hooks/_hook_utils.py::BadStdin`
- `tools/cc/hooks/_hook_utils.py::split_command`
- `tools/cc/hooks/_hook_utils.py::spawn_checked`
- `espalier/config.py::FOREIGN_KEYS`
- `tools/cc/hooks/_hook_utils.py::SpawnFailure`
- `tests/test_config_fields_consumed.py`
- `tests/test_failopen_voice.py`
- `tests/test_spawn_chokepoint.py`
- `bench/corpus/BC-<next>-adopter-protected-path.json` (the next free id at execution:
  `ls bench/corpus | command grep -o '^BC-[0-9]\{3\}' | sort | tail -1` printed `BC-061` at authoring)

### Removed-paths
- None.

## Reach

Members derived by: 0-A-2 (fields), 0-A-3 (fail-open sites), 0-A-4 (spawn sites), and
`command grep -n "DEF-948\|DEF-950\|DEF-951\|silently\|fail.open" task-packs/FORWARD_LEDGER.md`
(scope: the live rows; a clean grep is not an absence proof).

| Item | Status | Evidence |
|---|---|---|
| `DEF-950` (remaining half: unknown keys silent; the example's doctor promise) | **CLOSED** by 1-A | 0-A-1's drive prints the warning; doctor reports the key |
| `DEF-951` (documented protection read by no hook) | **CLOSED** by 1-B for the deny; the plan-field naming clause **NOT REACHED** (Scope out) | the bench row denies; the field census is green |
| `DEF-948` (remaining half: `which` resolution; the banner warning) | **CLOSED** by 1-D | `npm test` allows on the Windows box; the banner names an unresolvable token |
| the silent deciding fail-open sites in `tools/cc/hooks/` (no row; 0-A-3's number) | **CLOSED** as a class by 1-C's gate: each speaks or declares its kind | the gate reds on a removed `say_once` |
| `_locked_increment`'s dropped `name` (no row) | **CLOSED** in-lane | a test counts a non-default file under a read-only state dir |
| the eight pins of silence | **CLOSED** by Fix 11 | each asserts the message |
| the engine's own spawns | **NOT REACHED** | 0-A-4's scanner run says whether a row is owed |
| `DEF-915`, `DEF-947` (a wired interpreter that cannot start) | **NOT REACHED** | the adopter-axes pack's launch-as-wired runner (`DEF-975`); this pack's channels are what it asserts on |
| `DEF-968` | **NOT REACHED** | its own row; Fix 14 avoids its shape |

---

## Pass criteria

- An `espalier.toml` with an unknown key loads with a warning naming the file, the key and the
  nearest known name, and `doctor` reports it; no key that loaded before fails to load now.
- Every `HarnessConfig` field has a behavioural consumer or a declared display-only reason;
  the census test reds on a field with neither. Floor declared.
- A Write, Edit, Bash or PowerShell write into an adopter's `protected_paths` or
  `generated_paths` prefix is denied with the reason naming `espalier.toml`, under maintenance
  mode too; the prefix twin allows; the bench counts the row; no existing bench row changes
  verdict.
- Every deciding fail-open site in `tools/cc/hooks/` speaks through `say_once` / `warn` /
  an audit record or carries a kind-tagged pragma; the gate's floor is the 0-A number; the
  gate reds when one speaking call is removed. **No assertion is weakened**; every pin keeps
  its exit-code check and gains the message check.
- `/status --log` shows a `*_failed_open_*` count after a driven fault, and one record per
  session for the same key.
- Every spawn in `tools/cc/hooks/` is the chokepoint, routed, or pragma'd; `npm test` as the
  stop-time override allows at Stop on the Windows box with no respell advice; the banner
  names an override whose first token does not resolve.
- The four `*_INTERNAL_ERROR` reasons carry the remedy sentence; the umbrella guards are
  unchanged (`tests/test_hooks.py::test_main_umbrella_fails_closed_on_bash_non_str_command`
  stays green).
- `ruff check .`, `mypy tools/cc/hooks/`, the full tier (hook changes earn it), the hook type
  gate on the Linux view, `python3 scripts/sync_vendor_cc.py` clean.

## Files touched

- **New:** `tests/test_config_fields_consumed.py`, `tests/test_failopen_voice.py`,
  `tests/test_spawn_chokepoint.py`, `bench/corpus/BC-<next>-adopter-protected-path.json`,
  `scripts/failopen_census.py` (0-A's first form; deleted or kept as the test's walker, execution
  decides and says).
- **Modified:** `espalier/config.py`, `espalier/doctor.py`, `espalier/models.py` (docstrings),
  `tools/cc/hooks/_hook_utils.py`, `tools/cc/hooks/write_guard.py`,
  `tools/cc/hooks/_denial_reasons.py`, `tools/cc/hooks/plan_guard.py`,
  `tools/cc/hooks/stop_gate.py`, `tools/cc/hooks/session_start.py`, `tools/cc/hooks/_speedbump.py`,
  `tools/cc/hooks/_integrity.py`, `tools/cc/hooks/_bash_patterns.py` (one pragma line), any
  other `tools/cc/hooks/*.py` the census names, `espalier/_vendor/cc/hooks/*` (by sync),
  `tests/test_config.py`, `tests/test_hooks.py`, `tests/test_edge_cases.py`,
  `tests/test_stop_gate.py`, `tests/test_write_guard.py`, `tests/test_denial_reasons.py`,
  `tests/test_subagent_stop.py`, `tests/test_session_start_source_aware.py`,
  `examples/espalier.toml`, `docs/HOOKS.md`, `docs/CONVENTIONS.md`,
  `docs/sharp-edges/plan-guard-adopter-source-roots.md`, `CLAUDE.md`, `CHANGELOG.md`,
  `espalier/_vendor/selfcheck_tests/test_config.py` (by sync), `espalier/assets/docs/HOOKS.md`
  (by `scripts/sync_asset_docs.py`), `.github/windows-slice.txt` (this pack's Windows-facing
  tests — the stop-gate resolution cases and the zone cases — join the required slice in the
  same change, rather than waiting for a post-merge red to admit them),
  `task-packs/FORWARD_LEDGER.md` + `task-packs/LEDGER_PROBES.json` (three strikes through the
  verb, `--dry-run` first; `DEF-951` may be a repin if its naming clause stays open).
- **Deleted:** none.
- **Unmodified on purpose:** `tools/cc/hooks/_protected_zones.py` (the harness roster is not
  the adopter's), the four umbrella crash guards (fail-closed stays), `espalier/scanners/`
  (no new scanner, Scope out).

## Sub-task ordering

1. **0-A** the four oracles (1 h) — may shrink or end the pack. Checkpoint: `reports/tp461/0-A.md`.
2. **1-A** config voice (1 h). Checkpoint: the drive prints two warnings; the field test red
   on two names.
3. **1-B** the adopter zones (2 h). Checkpoint: the bench row; the field test green.
4. **1-C** the voice contract (3 h; the gate first, then the sites, then the pins). Checkpoint:
   the gate green at the floor; a driven fault writes one record.
5. **1-D** the spawn chokepoint and the banner line (2 h). Checkpoint: the Windows box's
   `npm test` Stop.
6. **2-A** red-team (1.5 h). Checkpoint: verdicts folded; mutations named.
7. Landing: strikes through the verb; `/preflight` (full tier); `/commit`; `/ship` with the
   marker in the title.

## Estimated effort

Budgets, quoted as budgets (the last pack ran about 2.7× over): 0-A 1 h, 1-A 1 h, 1-B 2 h,
1-C 3 h, 1-D 2 h, 2-A 1.5 h, landing 1 h — **11.5 h**, plus one Windows-box drive for 1-D.

## Landing
- State: DRAFT
- Commits:
- Suite:
- Earn-the-red:
- Red-team:
- Reach:
- Date:
