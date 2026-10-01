# TP-465 — What a first-week adopter meets: the effective CLAUDE.md, ownership by marker, the files the harness leaves in the tree, a test gate that says when it runs nothing, and two guard false denies

## Status

- Kind: PACK
- Version target: 0.8.0b3
- Type: adopter-facing defect classes (engine CLI, deployed hooks, deployed
  command body, shipped docs)
- Authored: 2026-10-01, the session after TP-464 merged, at the operator's
  confirmation of the plan ("plan confirmed"): with three adopter trees now
  running the harness from clone installs, the ledger's adopter-audience rows
  are the lens, and the GIF and the b3 cut are the operator's steps around
  this lane. Executes on a lane branched from `main` at or after PR #55.

## Motivation

Three trees outside the self-host run the harness as of 2026-10-01: a tester's
small Python repository (2026-09-30) and two of the operator's own (2026-10-01),
all installed from a clone at HEAD. The forward ledger's §2 index counts 56 live
rows whose audience is the adopter who ran `pip install`; a ranking of those by
the likelihood that a small Python repository meets them in its first week
(derived from the row texts on 2026-10-01, not re-driven) put the members of
four small classes and two standalone guard rows at the top, and none of them
has a drafted pack:

| Unit | Rows | What the adopter meets |
|---|---|---|
| §C56 | `DEF-959`, `DEF-960` | an adopter who keeps their own `CLAUDE.md` as an `@`-import shell gets a NOTE at every `init` and a permanent FAIL on `/smoke` |
| §C55 | `DEF-957`, `DEF-958` | one own file under `.claude/` makes doctor call a clean uninstall a broken install; a Prettier gate reds on 56 deployed files with no snippet to exclude them |
| §C54 | `DEF-954`, `DEF-955`, `DEF-956` | the tree holds `.claude/settings.json.bak`, a working summary with the user's home path, and fourteen managed comment lines a home-path scan flags |
| §C52 | `DEF-949` | the stop-time test gate runs nothing, or a partial suite, and no default surface says so |
| §C0 | `DEF-966`, `DEF-967` | a read-only `sed`-and-`grep` chain is refused as an in-place edit; a note quoting a guarded command draws a checkpoint or a hard refusal |

Each class carries one oracle and one fix shape in its ledger section, so a
pack scoped to the four classes plus the two rows can honestly report what it
closed. The two rows the ranking put above these (`DEF-908`, `DEF-894`) were
checked against the tree before authoring and read as already addressed (the
demo document's deny text matches the live hook byte for byte; the README
carries the dev-extras install); they are not in this pack and are noted for a
re-verify sweep in Scope (out).

## Scope (in)

- **1-A §C56** One reader of the effective `CLAUDE.md`: `_print_claude_md_nudge`
  resolves `@path` lines one level deep, repository-relative, and treats a
  heading found there as present; `/smoke` checks 1, 2 and 4 take their
  inventory from `cc/COMMANDS.md` and the deployed agent files by membership,
  print `[SKIP]` with the reason on an adopter-owned `CLAUDE.md` that carries
  no table, and keep the table check for the self-host tree only; the report
  template gains a SKIPPED state and the agent-files slot.
- **1-B §C55** `_deployed_surface_remains` counts a `.claude/` path only when it
  carries the managed marker; `ownership_summary` splits by the same predicate;
  `.claudeignore` leaves the adopter plan view; a doctor-equals-clean-generated
  parity test on one tree. `init` and `upgrade --execute` print a
  formatter-ignore snippet derived from what they wrote when a formatter
  configuration is found, and `python -m espalier ignore-snippet --format prettier`
  reprints it; the adopter's own file is never written.
- **1-C §C54** The settings backup rung moves to
  `.espalier/settings-backups/settings.json.<n>.json` (fork (a) of `DEF-954`,
  the pack's choice, stated with its refutation below); the resume index's
  transcript pointer becomes a session stem plus the command that resolves it;
  the fourteen home-path-shaped comment lines are reworded; a test content-scans
  every deployed asset against a small home-path shape set.
- **1-D §C52** `DEF-949` steps 1 to 3: a distinct `ok_harness_defaults` status
  with a note so a partial Gate 1 is never silent; a `doctor` info row and a
  warning when `full` resolves dormant; one `init` summary line naming the
  detected command and both variables; dormancy notes that name the override;
  the override added to the HOOKS.md configuration table and Gate 1 row, the
  README section, the cheat sheet, the generated `CLAUDE.md` row and the
  env-catalog purpose; the parity test re-described and the FAILURE_MODES
  example corrected.
- **1-E `DEF-966`** `_SED_INPLACE_RE`'s option run stops at a statement
  separator; the chain joins the inert corpus beside a must-deny twin; the
  deployed-doc advisory gains a changed-since-the-call filter.
- **1-F `DEF-967`** `_close_double_quote` steps over a command substitution, a
  parameter expansion and a backtick span with their own quotes, after the
  seven call sites are read for which close they want; inert rows and must-deny
  twins; the reachability differential green.
- **2-A** Red-team (code-reviewer and failure-mode-reviewer on a snapshot
  clone), one fold, then one full tier (hooks change: the tier the diff earns
  is `full`), the strikes, `/commit`, `/handoff`, the lane's one push.

- Files this scope covers: `espalier/cli.py`, `espalier/doctor.py`,
`espalier/managed_paths.py`, `espalier/cleanup.py` (read),
`espalier/managed_markers.py` (read), `.claude/commands/smoke.md` (and its
mirrors through `scripts/sync_claude_mirrors.py`), `tools/cc/session_summary.py`,
`tools/cc/read_summary.py`, `tools/cc/hooks/_hook_utils.py`,
`tools/cc/hooks/_bash_patterns.py`, `tools/cc/hooks/stop_gate.py`,
`tools/cc/hooks/session_start.py`, `tools/cc/hooks/_reinject.py` (and their
vendor mirror through `scripts/sync_vendor_cc.py`), `docs/HOOKS.md`,
`docs/CHEAT-SHEET.md`, `docs/ENV_CATALOG.md`, `docs/FAILURE_MODES.md`,
`docs/TROUBLESHOOTING.md`, `README.md`, the tests named per task, the ledger
and its probes file.

## Scope (out)

- **`DEF-949` step 4, the behaviour fork** (run the fingerprint's detected
  command as an argv at the root, or take the command only from a committed
  table): the class's design gate, decided with `DEC-35`, which this pack does
  not decide. Steps 1 to 3 do not wait for it (the row says so).
- **`DEC-38`** (where the init seeds land) and **`DEC-9`** (whether
  `clean-generated` reports or deletes residue): placement decisions §C55 and
  §C54 both name as out of their reach; this pack works with the namespace as
  it is.
- **`DEC-40`** (which file the two runtime denials cite, and the `src/`
  advice): §C56 names it as not reached; the nudge's wording once it reads the
  right document is a follow-up.
- **`DEF-943`** (where the audit log lives) and **`DEF-940`** (the gitignore
  block's omissions): §C54's own "does not reach".
- **`DEF-947`** (a dev container reading the host's settings): H impact for a
  narrow population; its oracle is a bind-mounted container, which this lane
  does not build.
- **§C57 and `DEF-976`** (the Node adopter defaults and the stack registry):
  all three adopter trees are Python; the stack knowledge is hand-written in
  more than twenty disagreeing places, which is its own pack.
- **A re-verify sweep of the 56 adopter rows**: two of the top-ranked rows
  (`DEF-908`, `DEF-894`) read as already addressed on this tree; the sweep that
  strikes or re-pins them is cheap and separate, and its oracle is each row's
  probe, not this pack's.
- **Shipping the packaged Markdown Prettier-clean** (`DEF-958`'s
  maintainer-side complement): a formatting pass over 56 deployed files that
  the seed-refresh rule would then read as upstream changes; a follow-up once
  the snippet exists.

## Cross-pack coordination

Two drafted packs name files this pack edits: `TP-450` (`State: DRAFT`, the
incident-remedy pack) names `tools/cc/hooks/_bash_patterns.py` only under its
"Unmodified on purpose" list (the guard is not its defect), so Fix 9 and Fix 10
collide with nothing of its; `TP-449` (`ROADMAP`) names `tools/cc/hooks/session_start.py`
and `tools/cc/hooks/_hook_utils.py`, both in this pack's Modified list. Neither
has executed. This pack lands first; each of them re-reads its premise against
the merged file at its own Task 0; no prescription of either is reversed here.

## Task 0 — Verify (may end this pack)

Each member's oracle is the one its row drove at `550314e`; every one is
re-run here at HEAD before any edit, from the repository root, with
`ESPALIER_MAINTENANCE_MODE` unset for the hook drives. A member whose oracle
refutes is struck from this pack's Reach with the reason and the pack
continues (partial closure is the licensed outcome); if every member refutes,
stop and re-raise. The scratch roots live under the session scratchpad, never
under `/tmp` by hand and never inside this tree.

### 0-A §C56: the nudge and `/smoke` read the literal file (measured at 550314e; re-run)

```bash
T=$(mktemp -d "${TMPDIR:-/tmp}/tp465-c56.XXXX") && cd "$T" && git init -q && git branch -M main
printf '@AGENTS.md\n' > CLAUDE.md
printf '# Agents\n\n## Plan Guard\n\n## Maintenance mode\n\n## Hooks\n' > AGENTS.md
printf 'def f():\n    return 1\n' > app.py && git add -A && git commit -qm seed
python3 -m espalier init . 2>&1 | grep -n -i -E 'NOTE|CLAUDE.md' | head -5
```

Premise holds when a NOTE names missing sections although the headings sit one
import away (the exact three section names are `espalier/cli.py::REQUIRED_CLAUDE_MD_SECTIONS`;
read them first and seed `AGENTS.md` with those). Then, in the same tree, run
check 4's block from the deployed `.claude/commands/smoke.md` verbatim:
`CLAUDE.md: 0, Files: N` followed by `[FAIL] MISMATCH` holds the `/smoke` half.

Refuting results: no NOTE means `DEF-960` closed since the row (strike it,
drop the nudge half of 1-A); `[OK] Match` or a `[SKIP]` line means `DEF-959`
closed (drop the `/smoke` half).

### 0-B §C55: ownership by path, and no snippet (measured; re-run)

```bash
T=$(mktemp -d "${TMPDIR:-/tmp}/tp465-c55.XXXX") && cd "$T" && git init -q && git branch -M main
printf 'def f():\n    return 1\n' > app.py && printf '{}\n' > .prettierrc && git add -A && git commit -qm seed
python3 -m espalier init . > init.log 2>&1; grep -c -i -E 'prettier|ignore-snippet' init.log
mkdir -p .claude/skills/mine && printf '# mine\n' > .claude/skills/mine/SKILL.md
python3 -m espalier doctor --json . | python3 -c 'import json,sys; d=json.load(sys.stdin); print([p for p in str(d).split() if "skills/mine" in p][:1])'
python3 -m espalier clean-generated --execute . > /dev/null 2>&1; python3 -m espalier doctor . > doctor.log 2>&1; echo "doctor rc=$?"; grep -n -i 'missing required managed surface' doctor.log
```

Premise holds when the init log mentions no snippet (count 0), doctor's
ownership names the unmarked skill, and doctor after the uninstall exits 1
naming a missing managed surface. Refuting results: a snippet line in the init
log closes `DEF-958`; doctor exit 0 reporting the tree uninstalled closes
`DEF-957`. (The doctor JSON shape is read at execution time; the one-liner above
is a presence probe, not a schema claim.)

### 0-C §C54: three writers leave the shapes (measured; re-run)

```bash
T=$(mktemp -d "${TMPDIR:-/tmp}/tp465-c54.XXXX") && cd "$T" && git init -q && git branch -M main
mkdir -p .claude && printf '{"permissions": {"allow": ["Bash(ls *)"]}}\n' > .claude/settings.json
printf 'def f():\n    return 1\n' > app.py && git add -A && git commit -qm seed
python3 -m espalier init --wire-hooks . > /dev/null 2>&1; ls .claude | grep -c 'settings.json.bak'
python3 tools/cc/session_summary.py | grep -c -E "$HOME|/Users/|C:\\\\Users"
cd - > /dev/null
grep -n -c -E '/Users/[A-Za-z]|C:\\\\Users\\\\|/home/[a-z]|USERPROFILE' tools/cc/hooks/_hook_utils.py tools/cc/hooks/_bash_patterns.py tools/cc/read_summary.py
```

Premise holds when the `.bak` count is 1, the summary's home-path count is at
least 1, and the three files' per-file counts sum to about fourteen (the row's
seven-shape rule set is wider than this grep; the count is a floor). Refuting
results per member: no `.bak` (`DEF-954` closed), a path-free summary
(`DEF-955` closed), zero lines in all three files (`DEF-956` closed).

### 0-D `DEF-949`: case D is a silent partial gate (measured; re-run)

```bash
T=$(mktemp -d "${TMPDIR:-/tmp}/tp465-c52.XXXX") && mkdir -p "$T/tests" "$T/reports"
printf 'def test_x():\n    assert 1\n' > "$T/tests/test_hooks.py"
printf '{"test_commands": ["pytest -q"]}\n' > "$T/reports/repo_fingerprint.json"
env -u ESPALIER_STOP_GATE_TEST_CMD python3 -c "
import sys, pathlib; sys.path.insert(0, 'tools/cc/hooks')
import stop_gate; r = stop_gate._resolve_core_tests(pathlib.Path('$T')); print(r.status, r.paths, repr(r.note))"
grep -c -E 'dormant|stop_gate|test_commands' espalier/doctor.py
```

Premise holds when the status is `ok` with `paths` naming only
`tests/test_hooks.py` and an empty note, and doctor's grep count is 0.
Refuting result: a status other than `ok`, or a non-empty note naming the
defaults, means case D already speaks; keep only the surfaces half of 1-D.

### 0-E `DEF-966`: the option run walks through a separator (measured; re-run)

```bash
python3 -c "
import sys; sys.path.insert(0, 'tools/cc/hooks')
from _bash_patterns import _candidate_paths_from_bash as c
print(c('sed -n 1,5p README.md && grep -n -i toml tools/cc/hooks/plan_guard.py'))
print(c('sed -n 1,5p README.md; grep -n -i toml tools/cc/hooks/plan_guard.py'))
print(c('sed -i s/a/b/ tools/cc/hooks/plan_guard.py'))"
```

Premise holds when the first two print a list naming the hook file and the
third does too (the calibration). Refuting result: empty lists for the first
two means the run is already bounded; strike `DEF-966`, drop 1-E.

### 0-F `DEF-967`: the masker returns the raw text on a nested quote (measured; re-run)

```bash
python3 -c "
import sys; sys.path.insert(0, 'tools/cc/hooks')
from _bash_patterns import mask_inert_syntax as m
s = 'echo \"n: \$(printf \"x\")\"'; print(m(s) == s)
t = 'echo \"a|b\"'; print(m(t) == t)"
```

Premise holds when the first prints `True` (identity: the walker gave up) and
the second prints `False` (a quoted span holding an inert separator is masked;
a span with no inertable character is identity by design, so a plain word is
not a control -- the 0-A review drove it). **Measured at execution
(2026-10-01): the first input is identity before AND after the fix**, because
its span holds nothing inertable outside the substitution, so this oracle
never discriminated; the discriminating form is
`echo "a|b $(printf "x")"`, identity at HEAD (the walker gave up, the bar
stayed live) and masked to `a b` after Fix 10. The behavioural oracle that
decided the member is the corpus: three inert rows red at HEAD, green after. Refuting result:
`False` on the first means the closer already tracks nesting; strike
`DEF-967`, drop 1-F. A second refutation shape is found in 1-F's own first
step (a call site that wants the inner close): then 1-F is re-raised as its
own pack and `DEF-967` is NOT REACHED here.

## Relevant memory

Recent pattern, measured: on the last three lanes the defects were in the
repair, not the original code (TP-462's bytecode litter after four green
tiers; TP-463's seven contract classes found by the tier after two reviews;
TP-464's shared regression, a filter missing from one of three pytest lines,
found by both red-team lanes). On the guard surface specifically, the
`DEF-967` row warns that relieving a mention and opening a fail-open are one
edit seen from two sides.

| Entry | Where |
|---|---|
| Hook authoring | `memory/hook-authoring.md` |
| write_guard Blocks Inline Python Mentioning Dangerous Patterns | `docs/SHARP_EDGES.md` |
| Stop-gate dormancy on non-pytest fingerprints | `docs/SHARP_EDGES.md` |
| Stop Gate Mode (Light vs Full) | `docs/SHARP_EDGES.md` |
| Substring Markers Are Forgeable — Anchor to Line Start | `docs/SHARP_EDGES.md` |
| Five-Surface Command Sync | `docs/SHARP_EDGES.md` |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |

Resolved at authoring time by `python3 tools/cc/hooks/_recall.py "bash masker
nested double quote inside command substitution false deny"`, `... "stop gate
dormant adopter test suite never runs"`, `... "doctor managed paths marker
ownership uninstall verdict"`; the two CLAUDE.md and settings-backup queries
returned nothing that answers them. Re-run rather than trust this list if the
pack has been sitting.

## Implementation

Every prescribed fence below is a **fix shape, untested** unless its heading
says otherwise; each carries the measurement that would show it is the wrong
shape. Hooks and vendored copies: edit under `tools/cc/` and run
`python3 scripts/sync_vendor_cc.py`; command bodies: edit under `.claude/` and
run `python3 scripts/sync_claude_mirrors.py`. Maintenance-mode relaunch for the
hook edits.

### 1-A §C56 — one reader of the effective CLAUDE.md

**Fix 1 — resolve `@` imports one level deep in the nudge** *(fix shape,
untested — refuted if Claude Code's import grammar differs from a line that is
`@` followed by a relative path, which 0-A's seeded shape decides; the import
rules are in `docs/external/` if a pin is needed):*

```python target=espalier/cli.py
def _effective_claude_md_text(claude_md: Path) -> str:
    """The text Claude Code composes from ``claude_md``: its own lines plus,
    one level deep, the body of every ``@<relative path>`` line that resolves
    under the same directory. A missing import target contributes nothing, so
    the sections it would have carried still read as missing."""
    try:
        text = claude_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    parts = [text]
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("@") or stripped.startswith("@@"):
            continue
        target = (claude_md.parent / stripped[1:].strip()).resolve()
        try:
            target.relative_to(claude_md.parent.resolve())
            parts.append(target.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
    return "\n".join(parts)
```

Then `_print_claude_md_nudge` reads `text = _effective_claude_md_text(claude_md)`
in place of its own `read_text`, and returns when the text is empty (the
unreadable case it returns on today). Pin beside
`tests/test_init.py::test_adopter_claude_md_that_covers_the_sections_is_left_alone`:
a `CLAUDE.md` of `@AGENTS.md` plus `@.claude/x.md`, with the three headings in
`x.md`, draws no NOTE; the same with `x.md` absent still draws it. Mutation the
pin must die to: the helper returning only the file's own text.

**Fix 2 — `/smoke` checks 1, 2 and 4 by membership against an inventory the
harness owns** *(fix shape, untested — refuted if `cc/COMMANDS.md` is not
regenerated on every `init` on an adopter tree, which 0-A's tree decides by
`ls cc/COMMANDS.md` after init):* check 1 iterates the command names
`cc/COMMANDS.md` lists (the backticked `/name` cells, the same cell shape the
banner reads) and tests each `.claude/commands/<name>.md`; check 2 iterates the
deployed `.claude/agents/*.md` and tests each name against the agents table
only when `CLAUDE.md` carries one, else prints `[SKIP] agents table: CLAUDE.md
is adopter-owned`; check 4 asserts every `cc/COMMANDS.md` row has a file and
every file has a row (membership both ways), and keeps the `CLAUDE.md` table
count equality only under the self-host stand-down the body already uses for
its engine-side checks. The report template gains `SKIPPED` as a state and an
`Agent files:` line. Extend `tests/test_adopter_lifecycle_diagnostics.py` (it
already executes a rendered `/smoke` check) with the three shapes from the
row: import-only, skeleton, skeleton plus one adopter command, asserting no
FAIL on each and still a FAIL naming a deleted managed command. Mutation:
deleting `.claude/commands/smoke.md`'s own file must red check 4.

Checkpoint: `pytest -q tests/test_init.py tests/test_adopter_lifecycle_diagnostics.py`
and `python3 scripts/sync_claude_mirrors.py` leaving the tree converged.

### 1-B §C55 — ownership by the marker, and the ignore snippet

**Fix 3 — count a `.claude/` path as deployed surface only when it carries the
marker** *(fix shape, untested — refuted if a real deploy under `.claude/`
ships without the marker, which `grep -L 'espalier:managed' .claude/agents/*.md
.claude/commands/*.md .claude/skills/*/SKILL.md` on a fresh scratch init
decides: any file listed is a deploy this predicate would miss; the packaged
sources under `espalier/assets/claude/` carry no marker, it is injected at
deploy by `_deploy_asset_md`, so a grep over the asset tree is the wrong oracle
and would refute for no reason -- the 0-A review drove it, 35 of 36 unmarked
there):*

```python target=espalier/doctor.py
    from espalier.cli import _settings_has_espalier_hooks  # lazy: cli imports doctor at top level
    from espalier.managed_markers import file_carries_marker
    candidates = set(managed_paths_from_plan(plan or {})) | set(fallback_managed_paths(repo_root))
    for rel in sorted(candidates):
        if rel in STANDARD_MANAGED_SETTINGS:
            continue
        under_owned_root = any(
            rel == root or rel.startswith(root + "/") for root in HARNESS_OWNED_ROOTS
        )
        if not under_owned_root or not (repo_root / rel).exists():
            continue
        # A real leftover is marked, because the uninstall deletes marked files
        # and spares the adopter's own; an unmarked file under .claude/ is theirs.
        if rel.startswith(".claude/") and not file_carries_marker(repo_root / rel):
            continue
        return True
    hooks_cfg = surface_contract._load_settings_hooks_cfg(repo_root)
    return hooks_cfg is not None and _settings_has_espalier_hooks({"hooks": hooks_cfg})
```

Then `ownership_summary` (`espalier/managed_paths.py`) splits its `.claude/`
members by the same predicate into marker-bearing files and a bucket for files
`init` wrote that the adopter now owns, persisting the answer
`_CLAUDE_MD_SKIPPED_MARKER` gives so `CLAUDE.md` is listed only when generated;
`.claudeignore` leaves `STANDARD_MANAGED_ROOT_DOCS` for the adopter plan view
(nothing writes or reads it; confirm with `grep -rn claudeignore espalier/
tools/cc/` first, and keep it if a reader turns up). Re-target
`tests/test_doctor.py::TestDoctorUninstalledTree::test_one_leftover_skill_file_keeps_the_broken_install_verdict`
so its leftover carries the marker (a deploy's shape) and add its twin: an
unmarked leftover reads as uninstalled. Add the parity test the row names: on
one scratch tree, the set doctor calls deployed surface equals the set
`clean-generated --dry-run` would delete. Mutation: the predicate inverted.

**Fix 4 — the formatter-ignore snippet** *(fix shape, untested — refuted if
`init`'s result object does not carry the written paths, which
`espalier/cli.py::_print_init_summary`'s parameters decide at execution time):*
a helper `_formatter_configs_present(repo_root)` returns the formatter names
whose configuration is found (`.prettierrc*`, `prettier.config.*`, a
`prettier` key or devDependency in `package.json`; `.markdownlint*`,
`.mdformat.toml`, `dprint.json` optional); when non-empty, `_print_init_summary`
prints one block, `Formatter ignore (prettier) — paste into .prettierignore:`,
listing the seed docs (`get_seed_docs()`), the managed `.claude/` files by exact
path, `cc/`, `tools/cc/`, `memory/` and `ESPALIER_MEMORY.md`; a new subcommand
`ignore-snippet --format prettier` prints the same list from the saved plan
so it is reprintable after an upgrade. Never write the adopter's file. The
verb's obligations, named by the 0-A review: register it with a `help=` line (a
verb without one must join `tests/test_cli_commands.py::TestArgparseErrorCuration::HIDDEN`);
add its row to `docs/CHEAT-SHEET.md` (`tests/test_documented_claims.py::TestCheatSheetCliParity`
derives the verb set from the parser); re-derive any CLI-verb count claim in
`CLAUDE.md` or the README (`grep -n -i -E 'verbs|subcommands' CLAUDE.md README.md`);
and spell the verb `python -m espalier ignore-snippet` in every printed string
(`tests/test_no_bare_espalier_hints.py` fails a bare `espalier <verb>` literal
in `espalier/cli.py`). Pin: a
scratch init with `.prettierrc` prints the block naming every seed and no
adopter path; without it prints nothing; `python -m espalier ignore-snippet --format prettier` on the initialized tree prints the same list. Mutation: the
`.claude/` entries widened to the directory (the adopter's own files there must
stay formatted).

Checkpoint: `pytest -q tests/test_doctor.py tests/test_cleanup.py tests/test_init.py tests/test_cli_deploy.py`.

### 1-C §C54 — the shapes the harness leaves in the tree

**Fix 5 — relocate the settings backup rung** *(fix shape, untested; the
pack's choice between the row's forks is (a), because (b) leaves the archive
name in place and makes every adopter scanner carry a carve-out — refuted if
the operator prefers (b), which is the one question this pack asks before
1-C runs):*

```python target=espalier/cli.py
def _settings_backup_rung(settings_path: Path, n: int) -> Path:
    """Rung ``n`` of the backup ladder: ``.espalier/settings-backups/settings.json.0.json``
    beside the repository root, then ``.1.json``, ``.2.json``, ... A non-archive
    name under a harness-namespaced, gitignored directory, so a disk-walking
    hygiene scan that bans archive-class extensions never sees it."""
    backups = settings_path.parent.parent / ".espalier" / "settings-backups"
    return backups / f"{settings_path.name}.{n}.json"
```

`_back_up_settings` creates the directory before the first write;
`_settings_backup_rungs_on_disk` reads the new location and the legacy `.bak`
rungs beside the file (dedup and `cleanup`'s `settings_backups_kept` keep
recognising them); every print of `.bak` names the new relative path;
`REQUIRED_GITIGNORE` carries `.espalier/settings-backups/` and
`docs/TROUBLESHOOTING.md` stops calling the collision intended. Move
`tests/test_merge_settings.py::test_merge_writes_bak_backup`,
`::test_core_b6_existing_bak_not_clobbered` and
`tests/test_init_rewire_interpreter.py::test_a_backup_is_written_before_the_change`
to the new path; add a walk of the scratch tree after a wire that finds no
`.bak`; add a `tests/test_cleanup.py` case where a legacy rung and a
new-location rung coexist in ladder order. Mutation: the old name restored.

**Fix 6 — the transcript pointer as a session reference** *(fix shape,
untested — refuted if `read_summary.py --session <stem>` does not resolve a
stem, which `python3 tools/cc/read_summary.py --help` decides first):*

```python target=tools/cc/session_summary.py
def _transcript_ref(cwd: Path) -> str:
    """The newest transcript as a session reference, never a path: its stem plus
    the command that resolves it from the working directory at read time."""
    proj = _project_dir(cwd)
    if not proj.is_dir():
        return "(no local transcript dir)"
    jsonls = [p for p in proj.glob("*.jsonl") if p.is_file() and not p.is_symlink()]
    if not jsonls:
        return "(no transcript yet)"
    stem = max(jsonls, key=_safe_mtime).stem
    return f"session {stem} (python tools/cc/read_summary.py --session {stem})"
```

`build_resume_index` renders `_transcript_ref` in place of `_transcript_path`;
`_transcript_path` stays as is so
`tests/test_session_summary.py::test_resolves_jsonl_via_per_char_encoding` holds;
`::test_no_jsonl_reports_dir` and the three `/x/t.jsonl` stubs in
`TestBuildResumeIndex` assert the stem; add to
`tests/test_post_compact_capture.py::TestCaptureWritesLiveDoc` that the live doc
carries neither the home nor the repository path. Mutation: the path rendered
again.

**Fix 7 — reword the fourteen lines, then pin the deployed assets against a
shape set** *(fix shape, untested — the durable half is the test; refuted if a
shape in the set is one a deployed asset must spell literally, which the
test's first run names):* reword with a non-letter drive token and a `<home>`
token where the prefix is not the point, and words where the MSYS form is the
point; keep the literal spellings in the test suite and `docs/SHARP_EDGES.md`.
Then `tests/test_deployed_assets_home_path_shapes.py`: content-scan
`espalier/_vendor/cc/**` and `espalier/assets/**` against a small shape set
(`/Users/<letter>`, `/home/<letter>`, `C:\Users\`, `USERPROFILE` spliced into a
path, the per-character project-directory encoding) and fail naming file and
line. Mutation: one reworded line restored.

Checkpoint: `pytest -q tests/test_merge_settings.py tests/test_init_rewire_interpreter.py tests/test_cleanup.py tests/test_session_summary.py tests/test_post_compact_capture.py tests/test_deployed_assets_home_path_shapes.py`
and `python3 scripts/sync_vendor_cc.py`.

### 1-D §C52 — a test gate that says when it runs nothing

**Fix 8 — a partial gate is never silent** *(fix shape, untested — refuted if
`espalier/analyze.py::detect_tests` can emit a pytest string with positional
args on an adopter tree, which `grep -n 'pytest' espalier/analyze.py` decides:
if it can, case D is narrower than the row says and the note still lands):*

```python target=tools/cc/hooks/stop_gate.py
    defaults = [str(p) for p in _HARNESS_DEFAULT_TESTS]
    defaults_present = [
        p for p in defaults if (repo_root / p).exists()
    ]
    if not defaults_present:
        return ResolvedTests(
            paths=[],
            status="dormant_no_paths",
            note=(
                "Gate 1 dormant: no positional args from fingerprint and the "
                "harness default test files are not in this repository. Set "
                "ESPALIER_STOP_GATE_TEST_CMD=<your test command> in the shell "
                "that launches Claude Code."
            ),
        )
    return ResolvedTests(
        paths=defaults_present,
        status="ok_harness_defaults",
        note=(
            "Gate 1 runs only the harness default test files present here "
            f"({', '.join(defaults_present)}), not your suite. Set "
            "ESPALIER_STOP_GATE_TEST_CMD=<your test command> to run it."
        ),
    )
```

Gate 1's caller prints a non-empty note on the `ok_harness_defaults` status as
it does on the dormant ones; the `dormant_non_pytest` note names the override
and not the fingerprint. Then the surfaces: `_stop_gate_dormancy_note` in
`session_start.py` warns on `ok_harness_defaults` too (its `startswith("dormant_")`
widened to a tuple that names both); `espalier doctor` gains a Gate 1 info row
(loading `stop_gate.py` by path as `session_start.py` does, through the
module's existing by-path import helper) that is a warning when
`ESPALIER_STOP_GATE=full` and the status is dormant or defaults-only;
`_print_init_summary` prints one line naming the detected test command and both
variables; `docs/HOOKS.md` gains the override in its configuration table and
Gate 1 row; the README section, `docs/CHEAT-SHEET.md`, the generated
`CLAUDE.md` hooks row and `docs/ENV_CATALOG.md`'s purpose name it beside
`ESPALIER_STOP_GATE=full`; `tests/test_stop_gate.py::test_resolves_from_real_fingerprint_output`
is re-described as the self-host check; the `docs/FAILURE_MODES.md` example
that credits it is corrected. Pins: an adopter-shaped `detect_tests` feed with
no seeding asserting the documented outcome; a doctor JSON Gate 1 row on an
npm fingerprint (a warning under `full` with no override); an init summary
contract; a documented-claims contract that the HOOKS.md configuration table
names the override. Mutation: the status string `ok` restored.

Checkpoint: `pytest -q tests/test_stop_gate.py tests/test_stop_gate_dormancy.py tests/test_session_banner.py tests/test_doctor.py tests/test_documented_claims.py`.

### 1-E `DEF-966` — the option run ends at a statement separator

**Fix 9** *(fix shape, untested — refuted if a retained capture in
`tests/test_write_guard_sed_grammar.py::TestTheRetainedRegexIsWitnessed` places
`-i` after a separator, which that class's first run after the edit decides):*

```python target=tools/cc/hooks/_bash_patterns.py
_SED_INPLACE_RE = re.compile(
    _CMD_POS + r"""sed""" + _QUOTED_VERB_TAIL
    + r"""[ \t]+(?:(?:'[^']*'|"[^"]*"|[^\s;&|'"])+[ \t]+){0,64}(?:-i|--in-place)"""  # the run stops at a separator, spaced or not; a quoted expression may hold one; the char class excludes the quotes
    r"""(?:[ \t]+(?:''|"")|[ \t]+\S+)?"""   # optional backup extension (incl. macOS '' form)
    r"""(?:[ \t]+'[^']*'|[ \t]+"[^"]*"){0,64}"""  # skip quoted sed expressions ({0,64}: bound)
    r"""[ \t]+([^\s'"]+)"""               # capture target file
)
```

The bar- and semicolon-delimited spellings the comment above the regex keeps
place `-i` directly after the verb, so a run that stops at a separator keeps
them (the row drove this); a quoted expression holding a separator
(`sed -e 's|a|b|' -i <path>`) is kept by the quoted alternatives. The first
form of this fix stopped only at a spaced separator, and the 0-A review drove
the unspaced chain (`README.md|grep`, `README.md&&grep`) straight through it,
so the run excludes separator characters from every token; both unspaced
spellings join the inert corpus beside the spaced ones. The macOS `''` form
captures the expression token rather than the file today and still does after
the edit; both tokens reach the extractor, so that deny lands either way. The
re-read named one narrowing: the permuted ordering with an unquoted
expression before the flag (`sed s|a|b| -i <path>`, `sed s;a;b; -i <path>`)
matched the old regex and not the new run. Driven through a real `/bin/bash`
on 2026-10-01: both are pipelines or command lists that never write (rc 127,
the victim unchanged), the same finding the retained-regex class records
for the `-i`-first spellings, and the quoted permuted form
(`sed 's|a|b|' -i <path>`, a real GNU write) is captured by both. So the
grammar corpus gains the quoted permuted form as a must-deny row and the two
unquoted permuted forms as witnessed never-write rows, and the narrowing
loses no write. **Measured at 2-A (2026-10-01):** the run as first written
admitted the quote characters to its char-class arm, so a quoted token had
two parses and the bounded outer repeat explored 2^k of them: a benign
`sed -e 's/a/b/' x17 README.md` took seven seconds in the PreToolUse path,
and the regex timing roster, which floods single characters, could not see
the shape. The arm excludes the quotes now (0.03 ms at k=17), and
`tests/test_redos.py` gains a quoted-token flood. Add the chain to `INERT_BASH` in
`tests/test_guard_false_positives.py` beside a must-deny twin whose second
command is a real `sed -i` on the hook file; `tests/test_redos.py` still
imports the name. The advisory's changed-since-the-call filter
(`_reinject._render_docs_asset_sync`) is its own step: compare the path's
digest before and after the call, and render only on a change. Mutation: the
old run restored.

Checkpoint: `pytest -q tests/test_write_guard_sed_grammar.py tests/test_guard_false_positives.py tests/test_redos.py`.

### 1-F `DEF-967` — the closer steps over nested substitutions

First step, before any edit, measured: read the seven call sites of
`_close_double_quote` (`step_over_assignment`, `_walk_shell_roles`,
`_binding_scope_events`, `_stdin_program_bodies`, `_read_shell_word`,
`_pipe_scan`, `_shell_word_spans`) for whether each wants the outer close. A
site that wants the inner close is the refutation that re-raises 1-F as its
own pack.

**Fix 10** *(fix shape, untested — refuted by the step above, and by the
reachability differential if a substitution that itself runs a guarded
command stops bumping):*

```python target=tools/cc/hooks/_bash_patterns.py
def _close_double_quote(s: str, start: int) -> int:
    """Index of the double quote that closes the one at ``start``, stepping over
    a command substitution, a parameter expansion and a backtick span with
    their own quotes, so the outer close is returned (the PowerShell twin
    tracks subexpression nesting the same way)."""
    i, n = start + 1, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            return i
        if c == "`":
            j = s.find("`", i + 1)
            if j < 0:
                raise _UnresolvedShellSyntax("unterminated backtick substitution")
            i = j + 1
            continue
        if c == "$" and i + 1 < n and s[i + 1] in "({":
            closer = ")" if s[i + 1] == "(" else "}"
            i = _match_delimiter(s, i + 1, n, s[i + 1], closer) + 1
            continue
        i += 1
    raise _UnresolvedShellSyntax("unterminated double quote")
```

`_match_delimiter` raises `_UnresolvedShellSyntax` on an unbalanced delimiter,
a raise path the closer did not have before; the call-site read covers whether
each site tolerates it (the walker's fail-closed rule says it must).

Inert rows in `tests/test_guard_false_positives.py`: the row's three-ingredient
command (a single-quoted mention of a guarded command, a command-position
character before it, a nested-quote substitution anywhere) stays ALLOW for the
discard, force-push and clean predicates and for `_bash_dangerous_reason`.
Must-deny twins: a substitution that itself runs the guarded command still
bumps; an exec-quote body holding the nested construct still denies. The
differential (`tests/test_powershell_reachability_differential.py`, in the
serial leg) green. Mutation: the closer's nesting removed.

Checkpoint: `pytest -q tests/test_guard_false_positives.py tests/test_write_guard.py`
and the serial-leg files by node id where a single file is slow.

### 2-A Red-team

Both reviewers on a snapshot clone built from the diff against HEAD (file
counts asserted equal), briefed with the harness frame and the ALLOW list for
running slow-file tests by node id. Ask each for the mutation that survives.
Most likely wrong, by the author: Fix 3's predicate on a deploy that ships
unmarked; Fix 9's lookbehind on a token that ends in a separator; Fix 10
changing a call site that wanted the inner close; the smoke template's new
state read by a test that pins the old one. One fold, then the full tier.

## Affected symbols

### Changed-semantics

- `espalier/cli.py::_print_claude_md_nudge`
- `espalier/cli.py::_settings_backup_rung`
- `espalier/cli.py::_back_up_settings`
- `espalier/cli.py::_settings_backup_rungs_on_disk`
- `espalier/cli.py::_print_init_summary`
- `espalier/cli.py::REQUIRED_GITIGNORE`
- `espalier/doctor.py::_deployed_surface_remains`
- `espalier/managed_paths.py::ownership_summary`
- `espalier/managed_paths.py::STANDARD_MANAGED_ROOT_DOCS`
- `tools/cc/session_summary.py::build_resume_index`
- `tools/cc/hooks/stop_gate.py::_resolve_core_tests`
- `tools/cc/hooks/session_start.py::_stop_gate_dormancy_note`
- `tools/cc/hooks/_bash_patterns.py::_SED_INPLACE_RE`
- `tools/cc/hooks/_bash_patterns.py::_close_double_quote`
- `tools/cc/hooks/_reinject.py::_render_docs_asset_sync`

### Renamed

- (none -- no symbol changes name)

### Added-paths

- `espalier/cli.py::_effective_claude_md_text`
- `espalier/cli.py::_formatter_configs_present`
- `espalier/cli.py::cmd_ignore_snippet` (the `ignore-snippet` subcommand, registered in the existing parser)
- `tools/cc/session_summary.py::_transcript_ref`
- `tests/test_deployed_assets_home_path_shapes.py`

### Removed-paths

- (none -- the legacy `.bak` rungs stay recognised)

## Reach

Members derived by: the four class sections and the two rows in
`task-packs/FORWARD_LEDGER.md` (`grep -n -E '^\| `(DEF-9(49|5[4-9]|6[067]))`' task-packs/FORWARD_LEDGER.md`),
each re-driven by Task 0 before the verdict. A clean grep is not an absence
proof: §C0 holds 101 live standalone rows and the ranking that chose these two
is derived from row text.

| Item | Status | Evidence |
|---|---|---|
| `DEF-959` | **CLOSED** by 1-A Fix 2 | the three shapes print no FAIL; a deleted managed command still FAILs |
| `DEF-960` | **CLOSED** by 1-A Fix 1 | the `@`-import shape draws no NOTE; a missing target still does |
| `DEF-957` | **CLOSED** by 1-B Fix 3 | doctor after a clean uninstall with one own skill exits 0; parity test |
| `DEF-958` | **CLOSED** by 1-B Fix 4 | the snippet prints on a `.prettierrc` tree and reprints by command |
| `DEF-954` | **CLOSED** by 1-C Fix 5 | a wire over an existing settings file leaves no `.bak`; legacy rungs recognised |
| `DEF-955` | **CLOSED** by 1-C Fix 6 | both writers render a stem; the live doc carries no home path |
| `DEF-956` | **CLOSED** by 1-C Fix 7 | the deployed-asset scan passes and reds on one restored line |
| `DEF-949` | **PARTIAL** by 1-D (steps 1 to 3) | case D speaks; six surfaces name the override; step 4 waits on `DEC-35` and the row is re-pinned, not struck |
| `DEF-966` | **CLOSED** by 1-E Fix 9 | the chain yields nothing; the `sed -i` twin still denies |
| `DEF-967` | **CLOSED** by 1-F Fix 10, or **NOT REACHED** if a call site wants the inner close | the three-ingredient command stays ALLOW; the twins deny; the differential green |
| `DEC-35`, `DEC-38`, `DEC-40`, `DEC-9` | **NOT REACHED** | decisions this pack does not make |
| `DEF-943`, `DEF-940`, `DEF-947` | **NOT REACHED** | the classes' own "does not reach", and a container oracle this lane does not build |

## Pass criteria

- No assertion is weakened and no row leaves `INERT_BASH` or the retained-regex
  class; every new pin was red against the unfixed code first (the mutation
  named per fix), and the Landing says which.
- Task 0's six oracles were re-run at HEAD before any edit and their outcome
  per member is written into the Landing; a refuted member is struck from Reach
  with the reason, never carried as closed.
- On a scratch adopter tree after the lane: `init` with an `@`-import
  `CLAUDE.md` prints no NOTE; the deployed `/smoke` prints no FAIL; doctor after
  `clean-generated --execute` with one own skill exits 0; a wire over an
  existing settings file leaves no file ending in `.bak` under `.claude/`;
  the working summary written by a driven compaction carries no absolute home
  path; the deployed-asset shape scan passes.
- `_resolve_core_tests` never returns an empty note with a status other than
  `ok` from positional args; `espalier doctor --json` carries a Gate 1 row.
- The two guard chains from `DEF-966` and `DEF-967` are ALLOW in
  `tests/test_guard_false_positives.py` and their must-deny twins deny; the
  reachability differential is green in the serial leg.
- Every mirror row of `espalier/mirror_registry.py` whose source this lane
  touched is converged (`python3 scripts/sync_vendor_cc.py`,
  `python3 scripts/sync_claude_mirrors.py`, `python3 scripts/sync_asset_docs.py`
  for the deployed docs; the registry is the census, never a typed pair --
  the first cut typed two of nine rows and the asset-docs mirror shipped the
  pre-fix text until the red-team read the registry); `python -m espalier
  provenance .` clean.
- One full tier green on the lane (`python3 scripts/proof_tier.py --run`; the
  diff touches hooks); the lane's pull request green on the thirteen required
  checks (the five `test-serial` cells joined branch protection on 2026-10-01;
  the read-back lists thirteen).
- Each closed row struck through `tools/cc/ledger_row.py strike` with its
  closing text; `DEF-949` re-pinned through `repin` with the steps that landed.

## Files touched

- Modified: `espalier/cli.py`, `espalier/doctor.py`, `espalier/managed_paths.py`,
  `.claude/commands/smoke.md` (+ mirrors), `tools/cc/session_summary.py`,
  `tools/cc/read_summary.py` (comments), `tools/cc/hooks/_hook_utils.py`
  (comments), `tools/cc/hooks/_bash_patterns.py`, `tools/cc/hooks/stop_gate.py`,
  `tools/cc/hooks/session_start.py`, `tools/cc/hooks/_reinject.py` (+ vendor
  mirror), `docs/HOOKS.md`, `docs/CHEAT-SHEET.md`, `docs/ENV_CATALOG.md`,
  `docs/FAILURE_MODES.md`, `docs/TROUBLESHOOTING.md`, `README.md`,
  `tests/test_init.py`, `tests/test_adopter_lifecycle_diagnostics.py`,
  `tests/test_doctor.py`, `tests/test_cleanup.py`, `tests/test_merge_settings.py`,
  `tests/test_init_rewire_interpreter.py`, `tests/test_session_summary.py`,
  `tests/test_post_compact_capture.py`, `tests/test_stop_gate.py`,
  `tests/test_stop_gate_dormancy.py`, `tests/test_session_banner.py`,
  `tests/test_documented_claims.py`, `tests/test_guard_false_positives.py`,
  `tests/test_write_guard_sed_grammar.py` (re-run), `task-packs/FORWARD_LEDGER.md`
  and `task-packs/LEDGER_PROBES.json` (the strikes and the repin),
  `ESPALIER_MEMORY.md` (the handoff's row), `CHANGELOG.md` (Unreleased),
  `.espalier/integrity.json` (the refresh), `tests/test_cli_commands.py` (the
  `HIDDEN` roster if the verb ships without help; re-run),
  `tests/test_no_bare_espalier_hints.py` (re-run), `CLAUDE.md` (Core Rule 10's
  required-check count, thirteen since 2026-10-01, with the `DEF-984` strike),
  `docs/QUICKSTART.md` (the one other `settings.json.bak` pointer),
  `espalier/assets/docs/*` (the asset-docs mirror of every edited doc),
  `tests/test_redos.py` (the quoted-token flood), `examples/CLAUDE.template.md`
  (regenerated: the hooks row changed).
- New: `tests/test_deployed_assets_home_path_shapes.py`.
- Deleted: none.
- Unmodified on purpose: `espalier/cleanup.py` and `espalier/managed_markers.py`
  (the predicate's owners; 1-B reads them), `tools/cc/hooks/write_guard.py`
  (its re-export of the regex stands), `tests/test_redos.py` (imports the name;
  re-run), `docs/CONVENTIONS.md`.

## Sub-task ordering

1. Task 0 (0-A to 0-F); strike refuted members from Reach; stop if all refute.
2. The one question for the operator: `DEF-954` fork (a) relocate or (b) name
   and exclude. Default (a); 1-C waits for the answer only if it is (b).
3. 1-A Fix 1, earn its red, then Fix 2; checkpoint.
4. 1-B Fix 3 then Fix 4; checkpoint.
5. 1-C Fix 5, Fix 6, Fix 7; checkpoint; vendor sync.
6. 1-D Fix 8 then the surfaces; checkpoint.
7. 1-E Fix 9; checkpoint.
8. 1-F's call-site read, then Fix 10 or the re-raise; checkpoint including the
   differential by node id.
9. 2-A red-team; one fold.
10. The three syncs (`sync_vendor_cc.py`, `sync_claude_mirrors.py`,
    `sync_asset_docs.py`), then `python -m espalier integrity refresh .` and
    `python -m espalier integrity verify .` (five modified hook files are in
    the manifest); one full tier; the strikes
    (the rows Reach closes, and `DEF-984`, the protection update done
    2026-10-01) and the repin; `/commit`; `/handoff` and the lane's one push
    (hooks changed: the driver binds the approval marker).

## Estimated effort

Budgets, not forecasts (TP-459's ran about 2.7 times over actual; TP-464's
7.5 h budget ran close): Task 0 1 h; 1-A 1.5 h; 1-B 2.5 h; 1-C 2.5 h; 1-D
2.5 h; 1-E 1 h; 1-F 3 h; 2-A 1.5 h; tier, strikes and landing 1.5 h.
Total 17 h, across more than one session; each task lands as its own commit
on the lane so the Landing can record a partial close honestly.

## Landing

- State: LANDED
- Commits: the lane's one execution commit, which carries this stanza's move to Done (the lane's HEAD after it lands; authored and executed in one session on 2026-10-01, after PR #55 merged)
- Suite: the full tier twice on the working tree (4 workers, the heavy stages out). First: 9 failed / 16,494 passed in 13:06 parallel and 1,829 passed in 3:26 serial -- the nine were tree-wide contracts the targeted checkpoints could not see (a `.claude/`-prefixed pointer, an aliased subprocess import, the census re-pin, the env-catalog line cite, two more legacy backup pins, the live surface, a NAME=value spelling in an operator string, a rationale docstring), folded. Second: 1 failed, 1 error / 16,502 passed in 13:19 parallel and 1,829 passed in 3:17 serial -- the error a live-tree xdist race (a sibling worker's reports temp file; the discard class serially 16 passed, logged in tests/README.md), the failure the census total the re-pin owed (405 to 410); that delta, a dev-script constant and a README line, re-proven by the census file and the contract slice.
- Earn-the-red: Fix 1 the import-away pin red (NOTE printed) then green, 8 in the class; Fix 2 the MISMATCH measured in Task 0 (CLAUDE.md 0, Files 17) then no FAIL on four shapes; Fix 3 two pins red then green, the parity test on an init-only tree (the install-ci file is DEC-10's), the deployed-skill fixture marked; Fix 4 the absent snippet measured in Task 0, four pins with the fix; Fix 5 the .bak beside the file measured in Task 0, eleven legacy pins re-targeted, the beside-the-file guard pinned after the review; Fix 6 the home path in the summary measured in Task 0, three pins; Fix 7 the scan green on its first run after the rewording (ten lines by Task 0's narrow grep; the review found two the first rule set could not see, the arms widened and a per-root floor added); Fix 8 case D measured in Task 0 (ok, empty note), the dormancy pin and four self-host fallback pins moved to the new status, the vocabulary pinned by AST; Fix 9 the chain yielding the hook measured in Task 0, then the review's quoted-token flood: 7.5 s at seventeen tokens red, 0.03 ms after the char class lost the quotes; Fix 10 three inert rows red at HEAD then green, the discriminating masker input identity at HEAD and masked after (the pack's own 0-F control was non-discriminating and the text says so)
- Red-team: 0-A code-reviewer APPROVE WITH CHANGES (3 BLOCK, 4 WARN, 2 NIT; the 0-F control, the verb's three pins, the integrity refresh, the regex's unspaced separator, the asset-tree grep as a wrong oracle) folded, re-read APPROVE WITH CHANGES (one WARN, the permuted ordering, folded with a bash drive). 2-A code-reviewer REQUEST CHANGES (3 BLOCK: the asset-docs mirror unsynced, the regex ambiguity, the in-process hook load; 3 WARN, 3 NIT) and failure-mode-reviewer REQUEST CHANGES (1 REGRESSION, 4 GAP, 5 ROUGH-EDGE), folded as one batch: sync_asset_docs run and the registry named as the census, the char class excludes quotes with a flood row, doctor probes the deployed hook in a child process with a hygiene pin, the status vocabulary pinned, the shape scan widened with a per-root floor, the backup helper guarded outside .claude, the hand-off batched to one git query with its limit stated, fenced and home imports in the nudge, settings.json in the snippet, two unbalanced-span rows witnessed, the smoke self-host tell tightened, QUICKSTART's pointer. Declined with the reason: a before/after digest in the advisory (a PostToolUse hook has no before state; a dirty file does need the sync it names).
- Reach: DEF-959, DEF-960, DEF-957, DEF-958, DEF-954, DEF-955, DEF-956, DEF-966, DEF-967 CLOSED (struck through the verb on 2026-10-01, each probe at its closed value; DEF-958 despite this pack's own Scope (out) deferral, which the closing text names as the complement that stays a follow-up); DEF-949 PARTIAL (re-pinned: steps 1 to 3 landed, step 4 waits on DEC-35; the live row names the lane, not this id); DEF-984 CLOSED (the operator step, done this session). NOT REACHED: DEC-35, DEC-38, DEC-40, DEC-9, DEF-943, DEF-940, DEF-947, DEC-10 (the install-ci file ships unmarked by decision; the parity test runs on an init-only tree because of it).
- Date: 2026-10-01
