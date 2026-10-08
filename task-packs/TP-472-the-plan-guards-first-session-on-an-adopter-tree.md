# TP-472 — The plan guard's first session on an adopter tree

## Status

- Version target: unscheduled (after `0.8.0b2`).
- Change type: one hook (`tools/cc/hooks/plan_guard.py`: two remedy strings, one advisory, one
  reader note), three hook helpers (`tools/cc/hooks/_hook_utils.py`, `_denial_reasons.py`,
  `_explain_path.py`), the stack table (one field, one projection), the engine's `init` (one new
  root file), one dependency floor, three shipped docs (one new heading), and the tests that prove
  each. Every `tools/cc/` edit ends with `python3 scripts/sync_vendor_cc.py` (the vendor mirror and
  the `stack-table` engine copy); every `docs/` edit to a seeded doc ends with
  `python3 scripts/sync_asset_docs.py` (`espalier/mirror_registry.py` is the census of both rows).
  No `.claude/` edits.
- **Kind: PACK**. Task 0 can end it, or end one fix of it (partial closure is licensed; see Reach).
- Gate: **not yet approved.** Three operator decisions under *Decisions needed*, each with the
  default the pack is written to.
- Ledger: the unit of work for `DEC-40` fork (a), `DEF-871`, `DEF-1022` and the fingerprint half
  of `DEF-1088`. Of the §C53 class (every `espalier.toml` key takes effect or is named) three
  members are struck (`DEF-950`, `DEF-951`, `DEF-953`) and one is a new knob (`DEF-952`, not
  taken); this pack takes the hook-side silence `DEF-950` left (`DEF-1022`). Two rows filed from
  this pack's drive, `DEF-1190` and `DEF-1191`, are closed here.
- Authored 2026-10-07 at `febfcd4e` on the Air (`python3` only). The drive and its tree are under
  the author's scratch directory (`pack-TP-472/drive.py`, `02-drive.txt`); Task 0 rebuilds them.

## Motivation

A fresh adopter runs `espalier init .` on a repository that is not this one, opens Claude Code,
and the first thing the harness says is a deny. **Measured 2026-10-07** on a throwaway Node tree:
`tests/_adopter_tree.py::build_adopter_tree(stack="node", tree="git")`, an adopter-owned
`CLAUDE.md` and `.github/workflows/ci.yml` added before `init`, then `python3 -m espalier.cli
init .` (exit 0; `NOTE: kept your existing CLAUDE.md ... It has no "Plan Guard" ... sections`).
The deployed `plan_guard.py` was driven with a minimal PreToolUse `Edit` event on stdin per path,
no plan active, every `ESPALIER_*` variable stripped. The rehearsal tree gave the same table the
same day (`fresh-init/REPORT.md` §4, logs `04-3f-*`).

| Path class | Path | Verdict | Why (`tools/cc/hooks/plan_guard.py::_is_exempt`) |
|---|---|---|---|
| source file | `src/index.mjs` | deny | non-root, non-exempt — **by design** (`docs/RELEASE_DECISIONS.md` 2026-06-10) |
| the stack's test dir | `test/index.test.mjs` | **deny** | not in `_hook_utils.EXEMPT_UNIVERSAL_PREFIXES` |
| the Python-named test dir, same tree | `tests/x.test.mjs` | **allow** | `tests/` is a universal prefix (the file does not exist) |
| README | `README.md` | deny | `::PLAN_REQUIRED_ROOT_FILES`, by design |
| manifest | `package.json` | deny | `_hook_utils.STACK_ROOT_FILES`, by design |
| the adopter's own CLAUDE.md | `CLAUDE.md` | deny | `::PLAN_REQUIRED_ROOT_FILES`, by design |
| the adopter's CI workflow | `.github/workflows/ci.yml` | deny | non-root, non-exempt, by design |
| seeded harness doc / memory | `docs/CONVENTIONS.md`, `memory/README.md` | allow | universal prefixes (§C23) |

Every deny ends with the same remedy (`::_PLAN_EXEMPT_HINT`): set `plan_exempt_prefixes = ["src/"]`
in `espalier.toml`, *see CLAUDE.md "Plan Guard" section*. On that tree **`espalier.toml` does not
exist** (`init` writes none; `espalier/cli.py`'s own comments say so) and **CLAUDE.md has no
"Plan Guard" heading**: `espalier/cli.py::_build_claude_md` renders one into every CLAUDE.md `init`
*writes*, but `::deploy_harness` keeps an adopter's existing file untouched — so the section is
absent exactly when the adopter already had a CLAUDE.md, the normal case.

Same drive: with `plan_exempt_prefix = ["src/"]` (one letter short), `espalier doctor .` **names
it** (`config_unknown_keys: ... did you mean `plan_exempt_prefixes`?`, `DEF-950`'s closure) while
the deny reason is **byte-identical** to the no-config one and `.espalier-state/` holds no
said-once record (`DEF-1022`, confirmed). With the correct key, `src/index.mjs` is allowed and
`test/index.test.mjs` is still denied — with a remedy saying *set `plan_exempt_prefixes =
["src/"]`*, the setting they just made. The fingerprint reads `src_layout`, `['javascript',
'astro']`, `['npm test']` and has no test-root field; nor does `tools/cc/_stack_table.py`.

Not driven here, the row's measurement: `DEF-871`. `_hook_utils.read_toml_table` opens the file
`"rb"` and catches `(OSError, ValueError)`; tomli below 2.0 types `load()` for a text handle and
raises `TypeError` on a binary one. Under `pyproject.toml`'s `tomli>=1.0` floor on CPython 3.10,
any `espalier.toml` rides that error to `plan_guard.main`'s crash handler: **every source write
becomes `PLAN_GUARD_INTERNAL_ERROR`**. The probe prints `True` today. This pack makes `init` write
an `espalier.toml`, which would hand that defect to every 3.10 adopter — so the tomli fix lands first.

**Who is hurt** (`docs/STANDING_PRINCIPLES.md` §16): the Node adopter editing `test/fetch.test.js`
in their first session, denied where a Python adopter's `tests/` is not, and sent to a file and a
section that do not exist; the 3.10 adopter who follows the remedy, creates the file, and loses
every source write; the adopter who mistypes the key and is told on every edit to set it.

**Not reopened:** whether the adopter's source is plan-gated at all — settled by
`docs/RELEASE_DECISIONS.md` 2026-06-10 and `DEC-40` fork (b), whose revisit trigger is drop-off
data this pack does not have. The class here is narrower: **the gate's first contact speaks the
self-host's layout** — its exemption roster, its remedy pointers, its silence about the adopter's
own config.

## Scope (in)

1. **1-A** `DEF-871`: the `tomli>=2.0` floor; `_hook_utils.read_toml_table` retries a `TypeError`
   from `parser.load` with a text handle.
2. **1-B** `DEC-40` fork (a), `DEF-1191`: the plan guard's remedy text and
   `_denial_reasons.HARNESS_ENV_PREFIX_INLINE` cite headings in `docs/HOOKS.md` (always deployed;
   mirrored at `espalier/assets/docs/HOOKS.md`), not a CLAUDE.md section; the doc gains the one
   heading it lacks (`Maintenance mode`); the hint keeps the literal `src/` (fork (b), settled —
   Decision 2 asks before the derived root is written).
3. **2-A** `DEF-1190`: the stack table gains `test_dirs`; `_hook_utils`'s stack-table projection
   gains the manifest-to-test-roots map (with its pinned fallback); `harness_exempt_prefixes` adds
   the test roots of the stack whose manifest is at the root; `_explain_path` names the rule.
4. **2-B** `DEF-1088` (fingerprint half), `DEF-1191`: `init` writes `espalier.toml` when absent and
   never rewrites it — every `HarnessConfig` key commented, the fingerprint's candidates in the
   comments; `render-template toml`; `examples/espalier.toml` becomes the pinned snapshot; the
   three "set it" sentences (the hint, `docs/TROUBLESHOOTING.md`, ONB-6) say "uncomment it".
5. **2-C** `DEF-1022`: a deny says what the guard did with the adopter's `plan_exempt_prefixes`
   before telling them to set it; `_explain_path` says the same.
6. **3-A** Red-team, one fix batch, the syncs, the tier.

Paths, for the scope walk:

- `tools/cc/hooks/plan_guard.py`, `tools/cc/hooks/_hook_utils.py`, `tools/cc/hooks/_denial_reasons.py`,
  `tools/cc/hooks/_explain_path.py`, `tools/cc/_stack_table.py`; their mirrors by `scripts/sync_vendor_cc.py`:
  `espalier/_vendor/cc/hooks/plan_guard.py`, `espalier/_vendor/cc/hooks/_hook_utils.py`,
  `espalier/_vendor/cc/hooks/_denial_reasons.py`, `espalier/_vendor/cc/hooks/_explain_path.py`,
  `espalier/_vendor/cc/_stack_table.py`, `espalier/_stack_table.py`
- `espalier/cli.py`, `espalier/managed_inventory.py`, `pyproject.toml`, `examples/espalier.toml`
- adopter-facing docs and their mirrors by `scripts/sync_asset_docs.py`: `docs/HOOKS.md`,
  `docs/ENV_CATALOG.md`, `docs/TROUBLESHOOTING.md`, `espalier/assets/docs/HOOKS.md`,
  `espalier/assets/docs/ENV_CATALOG.md`, `espalier/assets/docs/TROUBLESHOOTING.md`; self-host-only
  (the adopter gets a seed stub): `docs/SHARP_EDGES.md`, `docs/sharp-edges/plan-guard-adopter-source-roots.md`
- `tests/test_plan_guard.py`, `tests/test_plan_guard_adopter_config.py`, `tests/test_hook_utils.py`,
  `tests/test_explain_path.py`, `tests/test_denial_reasons.py`, `tests/test_contracts.py`,
  `tests/test_stack_table.py`, `tests/test_cli_deploy.py`, `tests/test_documented_claims.py`,
  `tests/test_init_gitignore_default.py`, and the three whose deploy-set expectations a new root
  file changes: `tests/test_lifecycle_parity.py`, `tests/test_init_managed_markers.py`,
  `tests/test_node_adopter_defaults.py`
- `task-packs/FORWARD_LEDGER.md`, `task-packs/LEDGER_PROBES.json`,
  `task-packs/TP-472-the-plan-guards-first-session-on-an-adopter-tree.md`

## Scope (out)

- **Whether the adopter's source is plan-gated** (`plan_guard.PLAN_REQUIRED_ROOT_FILES`,
  `_hook_utils.STACK_ROOT_FILES`, non-root source): settled with its own revisit trigger; `DEC-40`
  says fork (b) is not reopened. The hint keeps the `/implement-task` lead and the knob.
- **`DEF-952`**, the `plan_required_prefixes` knob: its own precedence design; not first-session.
- **The universal `tests/` exemption** (the over-reach `DEF-952` records as accepted): Decision 3
  names the stricter alternative and why it is refused — `/test-this` is a prescribed write to
  `tests/` (`tests/test_contracts.py::TestPlanGuardExemptsPrescribedWrites` derives it).
- **`DEF-991`** (`_hook_utils.adopter_protected_prefixes` reports `exclude_paths` as a guard fault):
  `write_guard`'s reader, a user who has set an engine key, its own five-fixture oracle.
- **`DEF-995`, `DEF-910`** (the adopter-zone deny on the Bash, PowerShell and MCP channels):
  `write_guard`'s templates for a configured zone — a later session, ten channel shapes, their own
  oracle, and the brief's caution against driving many spellings in one pack.
- **`DEF-1004`** (the surface index renders an adopter's hook as event `?`): the engine's render.
- **`INV-8`**, an ExitPlanMode-to-plan bridge: `deferred` in `docs/SURFACE_SUPPORT_MATRIX.md`; no
  row names a user it hurts.
- **`DEF-1082`** (§C72) and the shipped-body audience rows (`render-template claude`'s
  `**Languages:** python`, pytest lines in command bodies): `TP-473` (what `init` ships is
  addressed to the adopter) and `TP-474` (install, upgrade and CI on an adopter tree).
- **`DEC-40` fork (b)** (the hint's literal `src/`): settled with its own revisit trigger — adopter
  feedback that the first-session plan requirement is a material drop-off
  (`docs/RELEASE_DECISIONS.md` 2026-06-10). This pack's drive is a rehearsal, not that feedback.
  Decision 2 carries the reopening as a question; the default does not take it.
- **`DEF-1088`'s CLAUDE.md-reading arm** ("do not edit X" to `protected_paths`): a judgement per
  line, and a wrong entry hard-denies on every channel — a reviewed diff, never a write.
- **`cli.REQUIRED_CLAUDE_MD_SECTIONS` and the init nudge** stay: a subset ratchet (its comment: a
  deleted citation is green), and the sections still earn their place in a CLAUDE.md `init` writes.
- **Another machine's claim** (`bench/guard_equivalence.py`, `tests/test_guard_equivalence.py`,
  `bench/guard_metamorphic.py`, `bench/README.md`, `CHANGELOG.md`): no fix edits them; new tests
  build their trees in-module. (`tests/conftest.py` left the claim today; this pack still needs no
  row in it — Files touched says why.)

## Task 0 — Verify (may end this pack, or one fix of it)

Outcomes: **build**; **partial** (a refuted fix is dropped with its measurement in Landing); **do
not build**. On a refutation the exit is **stop and re-raise with the measurement**. Run from the
repository root on `main` at execution; never the full tier; nothing launches `claude`.

### 0-A The first-session table (the oracle for 1-B, 2-A, 2-C)

**Oracle** (stdlib plus the suite's builder, against a scratch tree only):

1. `build_adopter_tree(<scratch>, stack="node", tree="git")`; write an adopter-owned `CLAUDE.md`
   (no "Plan Guard" heading) and `.github/workflows/ci.yml`; commit; `python3 -m espalier.cli init .`
   with every `ESPALIER_*` variable stripped.
2. Per row of the Motivation table, pipe a minimal PreToolUse `Edit` event to
   `python3 tools/cc/hooks/plan_guard.py` (cwd and `CLAUDE_PROJECT_DIR` the tree, `ESPALIER_*`
   stripped, 30 s timeout); record `permissionDecision` and the reason.
3. For every path-shaped token in a deny reason, `Path.exists()` on the tree; for every
   `(file, section)` pair `tests/_doc_pointers.py::section_citations` reads from it, the file on
   the tree and the heading regex `(?mi)^#{1,6}\s.*X` (the rule `espalier/cli.py`'s CLAUDE.md
   nudge applies) over that file.
4. Write `plan_exempt_prefix = ["src/"]` to `espalier.toml`; `python3 -m espalier.cli doctor .`;
   drive `src/index.mjs`. Then the correct key; drive `src/index.mjs` and `test/index.test.mjs`.

**Refuting results:** 1-B — every token and every pair the reason names resolves (the pointers
were fixed on `main`);
2-A — `test/index.test.mjs` allowed with no config, or `tests/x.test.mjs` denied (the roster already
derives from the stack); 2-C — the deny under the misspelled key names the key or a did-you-mean.
Each drops its fix and re-raises. **Doctor:** already names the misspelled key — **measured
2026-10-07: it does**; that half of the brief's oracle is met on `main` and this pack adds nothing
to `doctor`.

**Measured 2026-10-07** (`pack-TP-472/02-drive.txt`): the table above; `espalier.toml exists: False`;
`CLAUDE.md has a 'Plan Guard' heading: False`; misspelled key: deny unchanged, doctor names it;
correct key: `src/` allowed, `test/` denied with the `src/` remedy. **Build 1-B, 2-A, 2-C.**

### 0-B The skeleton (the oracle for 2-B)

**Oracle:** on the 0-A tree after `init`, `ls espalier.toml`; `python3 -m espalier.cli render-template --help`
(the `subject` choices). **Refuting result:** the file exists, or `toml` is a choice — 2-B landed;
drop and re-raise. **Measured 2026-10-07:** no file; choices `claude`, `memory`, `changelog`. **Build.**

### 0-C The tomli floor (the oracle for 1-A)

**Oracle:** `python3 tools/cc/check_ledger_probes.py --id DEF-871`; `grep -n "tomli>=" pyproject.toml`;
the `except` arms of `_hook_utils.read_toml_table`. **Refuting result:** `STRIKE_CANDIDATE`, or a
`>=2.0` floor, or a `TypeError` arm — 1-A landed; drop and re-raise. **Measured 2026-10-07:**
`STILL_OPEN 1`; `tomli>=1.0; python_version < '3.11'`; `(OSError, ValueError)`. **Build.** The probe
keys on a `TypeError` handler inside `plan_guard._load_adopter_exempt_prefixes`, which opened the
file when the row was written; the open now lives in `read_toml_table`. The floor half alone flips
it; 1-A re-pins it to the function that opens the file.

### 0-D Cost

Time `build_adopter_tree(stack="node", tree="adopter")` three times and record the spread in
Landing. No refutation and no exit: every module a new test of this pack joins is already in
`tests/conftest.py::_SLOW_FILES` or carries the `# slow-exempt:` idiom — derive it with
`python3 -c "import sys; sys.path.insert(0, 'tests'); from conftest import _SLOW_FILES; print(sorted(_SLOW_FILES & {'test_plan_guard', 'test_plan_guard_adopter_config', 'test_cli_deploy', 'test_documented_claims', 'test_init_gitignore_default', 'test_init_managed_markers', 'test_node_adopter_defaults'}))"`
(from the repository root; the conftest imports `_stack_trees` bare, so `tests/` goes on the path —
measured 2026-10-07: all seven) and `grep -l 'slow-exempt' tests/test_stack_table.py`. A test that
lands in a module outside both sets carries the idiom in that module's docstring; never a
`_SLOW_FILES` row for it (over-marking drops the module from the pull-request slice —
`tests/conftest.py`'s note on `test_archive_transcripts`).

## Relevant memory

Recent pattern: the defects reviewers find on this tree sit in the repair and in the tests that
prove it (TP-468's Relevant memory; the voice pack's three-of-six). Here the likeliest repair defect
is a fixture that agrees with the implementation by accident: a Node tree whose `test/` is exempt
proves nothing unless a Python tree's `__tests__/` is denied in the same test.

| Entry | Where |
|---|---|
| plan_guard adopter source roots — config knob, not MAINTENANCE_MODE | `docs/sharp-edges/plan-guard-adopter-source-roots.md` |
| Plan Guard Exemption Prefix Matching | `docs/SHARP_EDGES.md :: Plan Guard Exemption Prefix Matching` |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| Prefer deleting a cross-citation to tracking it | `memory/prefer-deleting-a-cross-citation-to-tracking-it.md` |
| Asset mirroring (3-way SoT) | `memory/asset-mirroring.md` |
| The Install Path Can Break While Every Test Is Green | `docs/SHARP_EDGES.md :: The Install Path Can Break While Every Test Is Green` |

Resolved at authoring by `python3 tools/cc/hooks/_recall.py "<topic>"` with `adopter source roots
plan_exempt_prefixes`, `plan guard exempts the adopter's test directory`, `deny message points at
a file that does not exist on an adopter tree`, `hook edit needs the vendor sync`. Re-run rather
than trust this list if the pack has sat. Folders touched, so the folder-`CLAUDE.md` ladder fires:
`tools/cc/`, `espalier/_vendor/` (a mirror, never hand-edited), `tests/` (no new module), `docs/`.

## Implementation

Every fix is a **fix shape, untested**. Each names the mutation its test must die to.

### 1-A `DEF-871`: a tomli below 2.0

```toml target=pyproject.toml
    "tomli>=2.0; python_version < '3.11'",
```

```python target=tools/cc/hooks/_hook_utils.py
    try:
        with open(root / "espalier.toml", "rb") as fh:
            data = parser.load(fh)
    except TypeError:
        # tomli below 2.0 types load() for a text handle (DEF-871): read it that
        # way rather than let the error reach the caller's crash handler.
        with open(root / "espalier.toml", encoding="utf-8") as fh:
            data = parser.load(fh)
    except FileNotFoundError:  # fail-open: ok deliberate -- an absent espalier.toml is not a fault
        return None
```

Nest the retry so its `OSError`/`ValueError` reach the existing handler (the fence shows the first
two arms). **Proof:** in `tests/test_plan_guard_adopter_config.py` beside
`TestNoTomlParserRegexFallback`, bind `plan_guard._tomllib` to a stub whose `load(fh)` raises
`TypeError` when `"b" in fh.mode` and otherwise returns `tomllib.loads(fh.read())`;
`_load_adopter_exempt_prefixes` returns `("src/",)`, and `main` on `src/x.py` through `run_hook`
allows rather than `PLAN_GUARD_INTERNAL_ERROR`. Re-pin the probe to `read_toml_table`; if the Air's
3.10 interpreter is at hand, `pip install 'tomli<2'` into a scratch venv and drive the hook once.
**Mutation:** delete the `except TypeError` arm — both tests red. **Refutation:** a `TypeError` for
another reason is retried once and then escapes; if 0-C finds such a path, catch it on the retry
too and route it to `on_error`.

### 1-B `DEC-40` fork (a), `DEF-1191`: the remedy points at what exists

The two plan hints, the misplaced-key advisory and the env-prefix deny cite `docs/HOOKS.md` by
heading. The headings, as the doc writes them: `### 3. \`plan_guard.py\` — Execution plan gate`
(the knob is a row of that section's configuration table) and — new in this pack —
`#### Maintenance mode`, placed above the relaunch paragraph already in that section ("To use
maintenance mode, quit Claude Code and relaunch"): no seeded doc carries a maintenance-mode heading
today (`grep -nE '^#{1,6} .*[Mm]aintenance' docs/HOOKS.md docs/ENV_CATALOG.md` prints nothing).
The cited phrase is the heading's tail, which the heading regex reaches through the number and the
backticks; `Execution plan gate` occurs once in the doc (`grep -c 'Execution plan gate' docs/HOOKS.md`).

```python target=tools/cc/hooks/plan_guard.py
_PLAN_EXEMPT_HINT = (
    " Adopter source roots: set `plan_exempt_prefixes = [\"src/\"]` in "
    "espalier.toml at the repo root (see docs/HOOKS.md \"Execution plan gate\"). "
    f"Do NOT use {_maintenance_mode.ENV_VAR} for this — that scope is harness self-edits."
)
```

The literal `src/` stays: that is `DEC-40` fork (b)'s settled text (Decision 2). `_ROOT_SOURCE_HINT`
keeps the `./` sentinel and gains the same pointer; the module comment above the constant and the
misplaced-key advisory in `_load_adopter_exempt_prefixes` cite the same heading;
`_denial_reasons.HARNESS_ENV_PREFIX_INLINE` (DEC-40's second citation) ends
`See docs/HOOKS.md "Maintenance mode".`, and the two deployed docs that repeat the CLAUDE.md
pointer follow it — the `ESPALIER_MAINTENANCE_MODE` row of `docs/ENV_CATALOG.md` and the
write_guard section of `docs/HOOKS.md`
(`grep -n 'section "Maintenance mode"\|"Maintenance mode" in' docs/ENV_CATALOG.md docs/HOOKS.md`,
two hits). `docs/HOOKS.md`'s "Denial-hint surface" paragraph says what the hint now says. The
spelling `docs/HOOKS.md "X"` is form 3a of `tests/_doc_pointers.py::section_citations`, so the
deployed-doc gate reads it. **Proof**, three legs:

1. `tests/test_plan_guard.py::test_reason_names_plan_exempt_prefixes_escape` keeps both tokens. A
   new test in the same module (in `_SLOW_FILES`) builds the 0-A shape (`tree="git"`, an
   adopter-owned CLAUDE.md with no harness heading, then `init`), drives `lib/index.mjs` (denied
   before and after 2-A), and asserts every `(file, section)` pair `section_citations` reads from
   the reason resolves on that tree: the file exists and the heading regex matches in it.
2. `tests/test_denial_reasons.py` gains a sibling of `_cited_claude_md_sections` that keeps every
   `(file, section)` pair from the hook tree's string constants (the same `ast.Constant` walk,
   without the filename filter) and asserts each resolves against the seeded copy's headings
   (`espalier/assets/docs/<file>`, byte-equal to `docs/<file>` by `tests/test_deploy_doc_parity.py`),
   and that the CLAUDE.md filter yields no `.py` citer. `REQUIRED_CLAUDE_MD_SECTIONS` is a subset
   ratchet and stays green (`test_every_required_section_is_rendered` falls back to its
   "no live citation" label). `tests/test_maintenance_mode.py` keeps asserting `relaunch_hint()`
   inside the env-prefix text, which this edit keeps.
3. The two doc-side pointers are gated already:
   `tests/test_adopter_pointer_resolution.py::TestAdopterPointerResolution::test_every_section_citation_resolves`
   reds on the re-pointed rows until the `Maintenance mode` heading exists.

**Mutation:** restore `(see CLAUDE.md "Plan Guard" section)` — leg 1 reds on the kept CLAUDE.md
and leg 2's zero-citer assertion reds; rename the `Execution plan gate` heading, or cite
`"Plan Guard"` against `docs/HOOKS.md` — legs 1 and 2 red; drop the new heading — leg 3 red.
**Refutation:** a heading in a seeded doc is a contract the adopter's own edits can break; if the
red-team shows an adopter edit of `docs/HOOKS.md` is the common case, the pointer names the file
alone and the remedy stays inline, as the deny already states it.

**Decision 2's alternative** (not the default) — the derived root and the cost clause:

```python target=tools/cc/hooks/plan_guard.py
def _plan_exempt_hint(rel_path: str) -> str:
    """The knob, named with the denied path's own root; its cost in one clause;
    a pointer to a doc init always deploys (DEC-40 fork (a); fork (b) reopened
    by the operator under Decision 2, never by this pack)."""
    root = rel_path.replace("\\", "/").split("/", 1)[0] + "/"
    return (
        f" To take `{root}` out of the plan requirement for good, set "
        f"`plan_exempt_prefixes = [\"{root}\"]` in espalier.toml at the repo root "
        "-- plan discipline is then off for every file under it. See docs/HOOKS.md "
        f"\"Execution plan gate\". Do NOT use {_maintenance_mode.ENV_VAR} for this "
        "-- that scope is harness self-edits."
    )


_PLAN_EXEMPT_HINT = _plan_exempt_hint("src/")
```

Under it `_check_rel` calls the function with `rel_path`; the constant stays for the dead Bash and
MCP branches and its external readers (`tests/test_demo_end_to_end.py` formats it); leg 1 also
asserts the `lib/index.mjs` reason names `lib/` and not `src/` (mutation: restore the literal). Its
refutation: a depth-one path (`.github/workflows/ci.yml`) names `.github/`, a true statement of the
knob's granularity and a poor suggestion; if the red-team reads it as advice, drop the root to the
bare knob name and keep the cost clause.

### 2-A `DEF-1190`: the stack's test roots

The row class `tools/cc/_stack_table.py::Stack` gains a field (declared under Affected symbols
through `STACKS` and the projection, since `Stack` draws every `**Stack:**` line in the tree):

```python target=tools/cc/_stack_table.py
    manifests: tuple[str, ...] = ()                     # go.mod, Gemfile, package.json
    test_dirs: tuple[str, ...] = ()                     # the stack's test roots, each ending "/"
```

Rows: `python` `("tests/", "test/")`; `node` `("test/", "tests/", "__tests__/", "spec/")`; `rust`
`("tests/",)`; `go` none, with a comment (`_test.go` sits beside source; a prefix cannot express
it). `test_dirs_by_manifest()` returns `{manifest name: the row's test_dirs}` over every row, the
shape of `manifest_owners()` beside it.

The hook layer reads it through the projection it already has, not a second table reader:
`_hook_utils._StackProjections` gains a fourth member, `_read_stack_table` fills it from
`test_dirs_by_manifest()` inside the same guarded import (its empty-set check covers it), a fourth
pinned fallback `_TEST_DIRS_FALLBACK` sits beside `_STACK_ROOT_FALLBACK` under the same
`# stack-table: ok purpose-scoped` marker, and `STACK_TEST_DIRS` (`_STACK_TABLE[3]` or the fallback)
is the constant `stack_test_roots` reads. A deployed table older than this file lacks the projection
and raises at the call — the degrade the seam's comment documents: the hook layer runs on the pinned
copies and `say_stack_table_fault` says so once (`plan_guard.main` already calls it).

```python target=tools/cc/hooks/_hook_utils.py
def harness_exempt_prefixes(root: Path) -> list[str]:
    universal = list(EXEMPT_UNIVERSAL_PREFIXES)
    if is_self_host_repo(root):
        return universal + ["espalier/"]
    return universal + stack_test_roots(root)
```

`stack_test_roots(root)` lists the root directory once (the `_root_file_names` shape in
`espalier/analyze.py`; an `OSError` is an empty list) and returns, sorted, the `STACK_TEST_DIRS`
entries of the manifests present, minus the universal set.
`_explain_path._plan_rule_label` labels a hit `exempt -- your stack's test root `test/``.
`docs/HOOKS.md` "What's exempt" gains the row (the adopter's doc); `docs/SHARP_EDGES.md` "Plan Guard
Exemption Prefix Matching" and `docs/sharp-edges/plan-guard-adopter-source-roots.md` gain the
conditional clause in the `espalier/` shape — `tests/test_contracts.py::TestPlanGuardExemptPrefixes`
reads that clause by regex, so its wording is part of the fix. **Proof:** one test in
`tests/test_plan_guard.py`, two trees built to disagree: `build_adopter_tree(stack="node")` allows
`test/a.test.mjs` and `__tests__/a.test.mjs`; `build_adopter_tree(stack="python")` denies
`__tests__/a.py` and allows `test/a.py`.
`tests/test_stack_table.py::TestTheTableKeepsItsSeedNames` gains a pin for the field's seed names;
`::TestTheSourceAndManifestListsAreProjections` holds `_TEST_DIRS_FALLBACK == table.test_dirs_by_manifest()`
and non-empty, as it holds the three fallbacks beside it; `::TestTheHookLayerSurvivesAnUnreadableTable`
keeps its verdict with the fourth projection on its fallback.
`tests/test_forced_copy_parity.py`'s `EXEMPT_PREFIXES == EXEMPT_UNIVERSAL_PREFIXES` pin is untouched:
the roots are conditional and enter neither tuple. **Mutation:** delete `node`'s `test_dirs` — the
Node arm reds; return the projection unconditionally — the Python tree's `__tests__/` arm reds;
drop the fallback's marker — `::TestEveryHandListIsDerivedOrMarked` reds (the ratchet, not the fix).
**Refutation:** `tests/test_stack_table.py::TestEveryHandListIsDerivedOrMarked` reads any
`("test/", "tests/")` literal outside the table as a hand list; the lists live in the table and in
the one marked fallback. `TP-471` 4-A edits the same table's Python row and lands after this (Risks).

### 2-B `DEF-1088` (fingerprint half), `DEF-1191`: init writes the config file

`espalier/cli.py::_build_espalier_toml(fp)` renders every `HarnessConfig` field (`espalier/models.py`)
as a commented key with its `examples/espalier.toml` sentence, the fingerprint's candidates in the
comment: `plan_exempt_prefixes` from `architecture.pattern == "src_layout"` (`["src/"]`) else the
generic root; the stack's `test_dirs` named as already exempt (2-A); `generated_paths` from
`fp.generated_zones`. `deploy_harness` writes it beside step 3 (CLAUDE.md) under the same rule —
created when absent, never rewritten — and `preview_managed_surface` classifies it the same way
(its "three root files" become four). `render-template` gains the subject `toml`;
`tests/test_documented_claims.py::TestDeployTemplateSnapshots` pins `examples/espalier.toml` to the
render — from here on the example is regenerated through `render-template toml`, never by hand.
`cmd_upgrade` seeds it on an older tree through the same `created` path. `_print_init_summary`
names the file in one line. The three sentences that say "set `plan_exempt_prefixes` in
espalier.toml" say "uncomment it" now that the file exists: `_PLAN_EXEMPT_HINT` (1-B's text),
`docs/TROUBLESHOOTING.md`'s "add the prefix to `espalier.toml`", and the ONB-6 `text` in
`espalier/cli.py::_ONBOARDING_ROWS` (its `code` is untouched: the regex
`^\s*plan_exempt_prefixes\s*=` skips a commented line, so ONB-6 stays open until the adopter
uncomments the key — the row's intent). **Proof:** `tests/test_cli_deploy.py`: after `init` the
file exists, `load_config` on it warns of nothing, a second `init` and an `upgrade` leave an
adopter's edit byte-for-byte, and a `HarnessConfig` field with no commented line reds a new pin —
derived from `dataclasses.fields(HarnessConfig)`, so `TP-466b` 2-A's `recall_sources` and
`recall_records` are in it the day they land: whichever pack lands second adds the two sentences to
the renderer (or finds them there) and regenerates the example through the subject, never by hand
(the coordinator's decision 6; `TP-466b` states the same side).
`tests/test_lifecycle_parity.py` (the `_PACKAGED_ROOT_DOCS` roster), `tests/test_init_managed_markers.py`
(the deploy tally) and `tests/test_node_adopter_defaults.py` (the preview) update their expected
sets, never loosen them. `tests/test_init_gitignore_default.py::test_init_honours_a_decline_kept_in_its_config_file`
asserts no root `espalier.toml` after a `--config` init: re-spell it to "the root file declares no
`gitignore_declined`", the intent it had. **Mutation:** drop a field from the renderer — the
every-field pin reds; rewrite on second `init` — the bytes pin reds. **Refutation:**
`managed_inventory._PACKAGED_ROOT_DOCS` is read by the manifest, `clean-generated` and `doctor`'s
ownership; if a `.toml` breaks a reader that assumes markdown, list it in a sibling tuple with the
same "init writes it" rule and have `get_managed_public_files` read both.

### 2-C `DEF-1022`: the deny says what it did with the key

A sibling of the loader, `_adopter_exempt_note(root) -> str`, returns the one line the loader
otherwise says only through `say_once`: the rejected entry and why; `malformed`; the
`[plan_guard]`/bare `exempt_prefixes` misplacement; an unknown top-level key within difflib 0.6 of
`plan_exempt_prefixes` (did-you-mean); `plan_required_prefixes` answered in place ("plan_guard has
no required-list setting; not read", until `DEF-952`); or, for a valid list, "`plan_exempt_prefixes`
is set to [...] and does not cover `test/index.test.mjs`". `_check_rel` puts it between
`(attempted: ...)` and the hint; `_plan_rule_label` appends it; the `say_once` records stay (what
`/status --log` counts). **Proof:** the row's probe (eight TOML shapes, each reason compared with
the no-config one) prints eight `False`; the invalid-entry and malformed tests in
`tests/test_plan_guard_adopter_config.py` assert the reason names the cause. **Mutation:** return
`""` — eight `True` again.

### 3-A Red-team

`code-reviewer` and `failure-mode-reviewer` on the lane's diff, edits frozen (root `CLAUDE.md` Core
Rule 11). Ask each for the mutation that survives and for a fixture that agrees with the
implementation by accident. One fix batch; then `python3 scripts/sync_vendor_cc.py`,
`python3 scripts/sync_asset_docs.py`, and the tier.

## Affected symbols

### Changed-semantics

- `tools/cc/hooks/_hook_utils.py::read_toml_table` (a `TypeError` from `parser.load` is retried with a text handle)
- `tools/cc/hooks/_hook_utils.py::_read_stack_table` (a fourth projection: the manifest-to-test-roots map, under the same guard and empty-set check)
- `tools/cc/hooks/_hook_utils.py::harness_exempt_prefixes` (adds the detected stack's test roots on an adopter tree)
- `tools/cc/hooks/plan_guard.py::_check_rel` (the loader's note precedes the hint; under Decision 2's alternative the hint is built from the denied path)
- `tools/cc/hooks/plan_guard.py::_load_adopter_exempt_prefixes` (its misplaced-key advisory cites `docs/HOOKS.md "Execution plan gate"`)
- `tools/cc/hooks/plan_guard.py::_PLAN_EXEMPT_HINT` (text: the literal `src/` kept, the doc pointer added, "uncomment" after 2-B; still a module constant)
- `tools/cc/hooks/plan_guard.py::_ROOT_SOURCE_HINT` (cites `docs/HOOKS.md "Execution plan gate"`)
- `tools/cc/hooks/_denial_reasons.py::HARNESS_ENV_PREFIX_INLINE` (cites `docs/HOOKS.md "Maintenance mode"`, not a CLAUDE.md section)
- `tools/cc/hooks/_explain_path.py::_plan_rule_label` (names the stack-root rule; appends the loader's note)
- `tools/cc/_stack_table.py::STACKS` (every row gains a `test_dirs` value; `TP-471` 4-A's Python-row `package_managers` edit lands after)
- `espalier/cli.py::deploy_harness` (writes `espalier.toml` when absent)
- `espalier/cli.py::cmd_upgrade` (seeds `espalier.toml` on an older tree through the same `created` path)
- `espalier/cli.py::_print_init_summary` (names the new root file in one line)
- `espalier/cli.py::_ONBOARDING_ROWS` (the ONB-6 `text` says "uncomment"; its `code` and every other row untouched — `TP-471` 2-A edits ONB-3's text, `TP-474` 5-A the ONB-1/6/7 codes)
- `espalier/cli.py::preview_managed_surface` (classifies the fourth root file)
- `espalier/cli.py::render_canonical_template` (gains the subject `toml`)
- `espalier/managed_inventory.py::_PACKAGED_ROOT_DOCS` (or a sibling tuple: the config file joins the "init writes it" roster)
- the test side of the shared stack-table file, for the walk: `tests/test_stack_table.py::TestTheTableKeepsItsSeedNames`
  (the `test_dirs` seed pin) and `tests/test_stack_table.py::TestTheSourceAndManifestListsAreProjections`
  (the fourth fallback pin); `TP-471` 4-A adds its case to `::TestTheCommandsRunUnderTheRepositorysManager` after

### Renamed

- (none -- `_PLAN_EXEMPT_HINT` keeps its name.)

### Added-paths

- `tools/cc/hooks/plan_guard.py::_plan_exempt_hint` (Decision 2's alternative only; absent under the default)
- `tools/cc/hooks/plan_guard.py::_adopter_exempt_note`
- `tools/cc/hooks/_hook_utils.py::stack_test_roots`
- `tools/cc/hooks/_hook_utils.py::STACK_TEST_DIRS`
- `tools/cc/hooks/_hook_utils.py::_TEST_DIRS_FALLBACK`
- `tools/cc/_stack_table.py::test_dirs_by_manifest` (the row field `test_dirs` is declared through it and `STACKS`)
- `espalier/cli.py::_build_espalier_toml`
- `task-packs/TP-472-the-plan-guards-first-session-on-an-adopter-tree.md`

(`docs/HOOKS.md` gains the heading `Maintenance mode`; a heading is not a path, so it is declared
here in prose and under Files touched.)

### Removed-paths

- (none -- `examples/espalier.toml` stays, as the pinned snapshot of the render.)

**Authoring scope-check** (2026-10-07 after the review fold, `python3 -m espalier scope-check` on
this file): exit 2, 43 files in scope, 26 symbols, 129 gap files. Derive the gap list with the
command rather than trusting this census; it falls into five groups, and the fifth is the one to
act on:

1. Records and prose: `cc/blueprints/`, `cc/execution_plan.json`, `task-packs/Done/`,
   `task-packs/Deferred/`, `task-packs/Merged/`, the two pre-rebuild ledgers,
   `task-packs/ARCHIVE_*`, `docs/session-archive.md`, `WALK2_FINDINGS.md`, `WINDOWS_FUSE_NOTES.md`,
   `memory/CONVERGENCE_LEDGER.md`, a bench corpus row; `docs/CONVENTIONS.md`,
   `docs/RELEASE_DECISIONS.md`, `memory/asset-mirroring.md`, `memory/hook-authoring.md`,
   `memory/task-packs.md`, `tools/cc/hooks/CLAUDE.md`, and the six sibling drafts.
2. A name collision, not a reader: `tests/_stack_trees.py::STACKS` (the fixture-row dict) and its
   readers `tests/test_stack_trees.py`, `espalier/_vendor/selfcheck_tests/_stack_trees.py`.
3. Readers of a changed constant whose format fields do not change: `tools/cc/hooks/write_guard.py`
   and its mirror, `tests/_denied_form.py`, `tests/test_hooks.py`, `tests/test_maintenance_mode.py`,
   `tests/test_denial_reason_actionability.py`, `tests/test_demo_end_to_end.py`,
   `tests/test_portability_contract.py`, `tests/test_redos.py`, `tests/test_hook_voice_reaches_claude.py`,
   `tests/test_adopter_pointer_resolution.py` (1-B's leg 3 runs it, no edit); and readers of the
   table's row tuple whose projections do not change (`espalier/analyze.py`; the field is additive).
4. Readers that mention a declared symbol without depending on the changed behaviour:
   `espalier/doctor.py`, `espalier/models.py`, `espalier/render_surface.py`,
   `espalier/surface_contract.py`, `scripts/derived_population_census.py` (counts
   `_ONBOARDING_ROWS`), `bench/run_benchmark.py` (reads `deploy_harness`'s iteration-invariant
   docstring sentence — keep that sentence).
5. **Callers of `cmd_upgrade`, `deploy_harness`, `render_canonical_template` and `_ONBOARDING_ROWS`
   that may pin what 2-B changes** — the root-file set after `init`/`upgrade`, or ONB-6's text:
   `tests/test_cli_commands.py`, `tests/test_merge_settings.py`, `tests/test_init.py`,
   `tests/test_fuse.py`, `tests/test_init_upgrade_paths.py`, `tests/test_init_interactive_arming.py`,
   `tests/test_onboarding_nudge.py`, `tests/test_onboarding_doc_honesty.py`,
   `tests/test_config_fields_consumed.py`, `tests/test_render_template.py`, `tests/test_operator_docs.py`,
   `tests/test_package_resource_parity.py`, `tests/test_fan_out_findings.py`, `tests/test_doctor.py`.
   2-B's checkpoint runs the six likeliest; any that reds joins Scope (in) with its expected set
   updated, never loosened.

0-A at execution re-runs it; accept the gap with these reasons only if a new file falls into
groups 1 to 4 and nothing new into group 5.

## Reach

**How the members were derived:**
`grep -nE '^\| \`(DEC-40|DEF-871|DEF-1088|DEF-995|DEF-910|DEF-991|DEF-1022|DEF-1004|INV-8|DEF-1082)\` ' task-packs/FORWARD_LEDGER.md`;
the §C53 table (`grep -n '^### §C53' task-packs/FORWARD_LEDGER.md`, four rows);
`python3 tools/cc/check_ledger_probes.py --id <id>` for each (2026-10-07: all `STILL_OPEN` except
`DEF-1088`, `NO_ORACLE`). Not an absence proof.

| Item | Status | Evidence |
|---|---|---|
| `DEC-40` fork (a) | **CLOSED by 1-B** if Decision 1 takes the default | the citation check reds on the restored pointer; `_cited_claude_md_sections` derives no hook citation |
| `DEC-40` fork (b) | **NOT REOPENED** | settled 2026-06-10 with its own revisit trigger (first-session drop-off in adopter feedback); the hint keeps the literal `src/`, the knob and the `/implement-task` lead; Decision 2 asks before the derived root or the cost clause is written |
| `DEF-871` | **CLOSED by 1-A** | the stub-parser tests red without the retry; the probe flips after its re-pin |
| `DEF-1022` | **CLOSED by 2-C** | the probe's eight comparisons print `False` |
| `DEF-1088` fingerprint half | **CLOSED by 2-B** | the file exists after `init` with the fingerprint's candidates commented in |
| `DEF-1088` CLAUDE.md-reading half | **NOT REACHED** | a judgement per line; a hard-deny on a wrong entry; its own reviewed-diff pack |
| `DEF-1190` | **CLOSED by 2-A** | the two-tree test reds on either mutation |
| `DEF-1191` | **CLOSED by 1-B and 2-B** | every token a deny names exists on the 0-A tree |
| `DEF-950`, `DEF-951`, `DEF-953` (§C53) | **CLOSED BEFORE** (2026-09-29/30) | `doctor` named the misspelled key in 0-A |
| `DEF-952` (§C53) | **NOT REACHED** | a new knob with its own precedence design |
| `DEF-991` | **NOT REACHED** | `write_guard`'s reader; its own five-fixture oracle |
| `DEF-995`, `DEF-910` | **NOT REACHED** | `write_guard`'s channel templates for a configured zone |
| `DEF-1004` | **NOT REACHED** | the engine's surface render |
| `INV-8` | **NOT REACHED** | deferred in `docs/SURFACE_SUPPORT_MATRIX.md`; no named user |
| `DEF-1082` | **NOT REACHED** | §C72; the shipped-body audience pack |

## Pass criteria

- 0-A's drive, re-run after the lane: `test/index.test.mjs` allowed with no config; every
  path-shaped token and section citation in every deny reason resolves on the tree; the deny under
  a misspelled key names the key; `espalier.toml` exists after `init` and `load_config` warns of nothing.
- Every test this pack adds was seen red against its named mutation, recorded in Landing.
- **No assertion in an existing test is weakened.** `test_reason_names_plan_exempt_prefixes_escape`
  keeps both tokens; the `tests/test_init_gitignore_default.py` assertion is re-spelled to its
  intent, not deleted; the three deploy-set tests update their expected sets;
  `REQUIRED_CLAUDE_MD_SECTIONS` loses no entry. Strengthening is allowed and recorded.
- The `DEF-871` probe (after its re-pin) and the `DEF-1022` probe print `STRIKE_CANDIDATE`.
- After the syncs, `python3 scripts/sync_vendor_cc.py --check` and
  `python3 scripts/sync_asset_docs.py --check` exit 0 (the `tools/cc`, `stack-table` and asset-docs
  rows of `espalier/mirror_registry.py`); `tests/test_stack_table.py::TestTheEngineCopyIsAByteMirror`
  and the forced-copy parity pins green.
- `tests/test_contracts.py` (both exempt-prefix doc directions), `tests/test_denial_reasons.py`
  (1-B's leg 2 included), `tests/test_explain_path.py`,
  `tests/test_documented_claims.py::TestDeployTemplateSnapshots`,
  `tests/test_adopter_pointer_resolution.py::TestAdopterPointerResolution::test_every_section_citation_resolves`
  green; `mypy tools/cc/hooks/` and `ruff check .` clean.
- `python3 scripts/proof_tier.py --base origin/main` names `full` (a hook changes), green under
  `nohup` with `EXIT=$?` appended; never `-n auto` on the 8 GB box.

## Risks — what this pack most likely got wrong

1. **2-A exempts something the operator wants gated.** The `DEF-952` user ("never weaken a check")
   loses plan discipline on `test/`, where before only `tests/` was open. Decision 3.
2. **Under Decision 2's alternative, the derived root reads as advice** (`.github/` for a CI edit):
   1-B's refutation clause. Under the default, a `lib/` deny that says `src/` is the misdirection
   `DEC-40` recorded and fork (b) keeps until its trigger fires.
3. **The skeleton changes hook behaviour on every tree.** A present `espalier.toml` makes
   `read_toml_table` parse on every mutating tool call where before it returned at `is_file()`; the
   zone and extension readers memoise on mtime and size, `plan_guard`'s own read does not. Time one
   PreToolUse fire before and after on the 0-A tree and record it. Also why 1-A lands first. Once
   `TP-466b` lands, its two `read_toml_string_list` reads (the SessionStart banner, `/recall`) parse
   the same file; the timing here covers the plan guard's fire only.
4. **A fixture that agrees by accident.** 2-A's test must build both trees.
5. **`_PACKAGED_ROOT_DOCS` has readers that assume markdown.** 2-B names the sibling-tuple exit.
6. **The DEF-871 test stubs the parser**, reproducing tomli 1.x's documented behaviour, not the
   library; drive the real one once if the 3.10 interpreter is at hand, and say which in Landing.
7. **Seams — one production symbol, two packs.** One line each, with the landing order:
   - `tools/cc/_stack_table.py::STACKS` and `tests/test_stack_table.py`: this pack's 2-A lands first
     (a defaulted field is additive); `TP-471` 4-A's Python-row `package_managers` edit rebases on
     it. Both run `sync_vendor_cc.py`, which also writes `espalier/_stack_table.py`, so a hand
     resolve on the Python row replays into two mirrors.
   - `tools/cc/hooks/plan_guard.py`: `TP-474` 2-A wraps the module's sibling imports in
     `_import_siblings`; this pack edits the hint constants, `_check_rel` and
     `_load_adopter_exempt_prefixes`. Disjoint regions, one hazard: the two hint constants read
     `_maintenance_mode.ENV_VAR` at import, so whichever lands second keeps that import at the top
     or makes the constants lazy. Either order; named in both lanes.
   - `tools/cc/hooks/_denial_reasons.py`: this pack's 1-B edits `HARNESS_ENV_PREFIX_INLINE` (text);
     `TP-473` 1-E gives `KILL_SWITCH_DETECTED` a `{ci_clause}` slot. Different constants; 1-B
     first, 1-E rebases a one-constant diff.
   - `espalier/cli.py::_ONBOARDING_ROWS`: `TP-471` 2-A (ONB-3's text), `TP-474` 5-A (the
     ONB-1/6/7 codes), this pack's 2-B (ONB-6's text). ONB-6 is shared with `TP-474` at adjacent
     keys of one dict; 2-B lands last of the three and rebases one string.
   - `espalier/models.py::HarnessConfig` and `examples/espalier.toml`: `TP-466b` 2-A adds two
     fields; 2-B's renderer reads every field and the example is the render's snapshot. Either
     order; the second regenerates the example through `render-template toml`.
   - `docs/HOOKS.md` and `docs/ENV_CATALOG.md`: `TP-466b` 2-B, `TP-470` 1-B and `TP-471` 2-A edit
     them too; every lane re-runs `sync_asset_docs.py`, and a hand resolve replays into
     `espalier/assets/docs/`.
8. **The conftest contract.** No new module, so no `_MARKER_RULES` row; every module a spawning
   test joins is in `_SLOW_FILES` already (0-D derives it). A test placed elsewhere takes the
   `# slow-exempt:` idiom in-module, never a `_SLOW_FILES` row.
9. **A heading as a contract.** 1-B makes two `docs/HOOKS.md` headings load-bearing for four deny
   strings and two doc rows; a rename needs 1-B's three legs green, and the adopter owns the seeded
   copy after `init` — 1-B's refutation names the exit.

## Decisions needed (the operator; each with the pack's default)

1. **`DEC-40` fork (a): where the two denials point.** Default: `docs/HOOKS.md` by heading (always
   deployed; the configuration table under `plan_guard.py — Execution plan gate` already documents
   the knob, and the doc gains a `Maintenance mode` heading for the second citation), with
   `REQUIRED_CLAUDE_MD_SECTIONS` and the nudge left as they are. Alternative: have `init` append
   the sections to a kept CLAUDE.md — refused because `init` never rewrites an adopter's file, by
   design.
2. **Reopen `DEC-40` fork (b)?** The hint's example root is the literal `src/`, settled by
   `docs/RELEASE_DECISIONS.md` 2026-06-10 ("the existing per-deny `_PLAN_EXEMPT_HINT` remains the
   at-friction discoverability path"); its revisit trigger is adopter feedback that the
   first-session plan requirement is a material drop-off, and `DEC-40` records EI-28 as the first
   such feedback while leaving the fork settled. This pack's 0-A drive is a rehearsal, not that
   feedback. **Default: no** — 1-B keeps the literal and adds the doc pointer (fork (a) alone).
   **If yes:** `_plan_exempt_hint(rel_path)` (the second fence under 1-B) derives the root from the
   denied path and adds the cost clause ("plan discipline is then off for every file under it");
   leg 1 also asserts a `lib/` deny names `lib/`, not `src/`; the operator records the reopening on
   the `DEC-40` row — this pack does not.
3. **The stack's test roots: exempt them (2-A), or stop exempting `tests/` on adopter trees.**
   Default: 2-A. The alternative is more principled (exempt only what the harness's own bodies write
   to) but `/test-this` is a prescribed write to `tests/`, so it costs a plan on every adopter
   `/test-this`, or an exemption the derivation cannot see.

## Files touched

- **New:** this pack. No new test module (the new tests join `tests/test_plan_guard.py`,
  `tests/test_plan_guard_adopter_config.py`, `tests/test_denial_reasons.py`,
  `tests/test_stack_table.py` and `tests/test_cli_deploy.py`).
- **Modified:** the paths under Scope (in); `docs/HOOKS.md` gains the `#### Maintenance mode`
  heading and its write_guard section's pointer moves to it; `docs/ENV_CATALOG.md`'s
  `ESPALIER_MAINTENANCE_MODE` row points at it; `docs/TROUBLESHOOTING.md`'s "add the prefix to
  `espalier.toml`" becomes "uncomment it in"; the ledger and probes (two strikes, one re-pin, the
  `DEF-1088` partial note).
- **`tests/conftest.py`: no edit, and here is why rather than a bare "unmodified".** No new module,
  so no `_MARKER_RULES` row; every module a spawning test joins is in `_SLOW_FILES` already or carries
  `# slow-exempt:` (0-D's deriving command). The other machine's claim on it was released today, so
  this is a finding about the pack, not a constraint on it.
- **Unmodified on purpose:** `plan_guard.EXEMPT_PREFIXES` and `_hook_utils.EXEMPT_UNIVERSAL_PREFIXES`
  (the stack roots are conditional; the parity pin stays whole); `plan_guard.PLAN_REQUIRED_ROOT_FILES`
  (the settled policy); `cli.REQUIRED_CLAUDE_MD_SECTIONS`, `::_print_claude_md_nudge`,
  `::_build_claude_md`; `deploy_harness` keeps its docstring's iteration-invariant sentence
  (`bench/run_benchmark.py` reads it); `CHANGELOG.md` (another machine's claim; the row is the
  coordinator's).

## Sub-task ordering

0. **Pre-flight**, the four gates in `memory/task-packs.md`: `code-reviewer` with
   `tools/cc/pack_artifact_checklist.md`; `python3 -m espalier scope-check <this pack>`;
   `python3 tools/cc/sister_site_probe.py --json`; `python3 -m espalier surface-impact <this pack>`.
   Then `python3 tools/cc/execution_plan.py create` (`pyproject.toml` is plan-gated) and the claims
   check (`python3 tools/cc/mail.py inbox`).
1. **Task 0** (0-A to 0-D). Checkpoint: the drive's output under `reports/tp472/` (gitignored).
   Stop on any refutation.
2. **1-A.** Checkpoint: `pytest -q -m 'not heavy_e2e' tests/test_plan_guard_adopter_config.py tests/test_hook_utils.py`;
   the `DEF-871` probe.
3. **1-B.** Checkpoint: `pytest -q -m 'not heavy_e2e' tests/test_plan_guard.py tests/test_denial_reasons.py tests/test_explain_path.py tests/test_maintenance_mode.py tests/test_demo_end_to_end.py tests/test_adopter_pointer_resolution.py`.
   Seams: `_denial_reasons.py` before `TP-473` 1-E; `plan_guard.py` beside `TP-474` 2-A in either
   order, the hint constants' `_maintenance_mode` read kept resolvable by whichever lands second
   (Risk 7).
4. **2-A.** Checkpoint: `pytest -q -m 'not heavy_e2e' tests/test_stack_table.py tests/test_contracts.py tests/test_forced_copy_parity.py tests/test_plan_guard.py`.
   Seam: 2-A lands before `TP-471` 4-A on `tools/cc/_stack_table.py` and `tests/test_stack_table.py`
   (the coordinator's order; 4-A rebases).
5. **2-C** (before 2-B, so the skeleton's first session already explains itself). Checkpoint: the
   `DEF-1022` probe.
6. **2-B.** Checkpoint: `pytest -q -m 'not heavy_e2e' tests/test_cli_deploy.py tests/test_documented_claims.py tests/test_init_gitignore_default.py tests/test_lifecycle_parity.py tests/test_init_managed_markers.py tests/test_node_adopter_defaults.py tests/test_doctor.py tests/test_cli_commands.py tests/test_merge_settings.py tests/test_init.py tests/test_fuse.py tests/test_init_upgrade_paths.py tests/test_render_template.py`
   (the last six are the `cmd_upgrade`, `deploy_harness` and `render_canonical_template` callers
   the scope walk surfaced; one that pins the root-file set after `init` or `upgrade` joins Scope
   (in) with its expected set updated, never loosened); 0-A's drive once more. Seams: after `TP-471` 2-A and `TP-474` 5-A on `_ONBOARDING_ROWS` (or
   rebase the one ONB-6 string); beside `TP-466b` 2-A on `HarnessConfig` in either order, the
   second regenerating `examples/espalier.toml` through `render-template toml`.
7. `python3 scripts/sync_vendor_cc.py`; `python3 scripts/sync_asset_docs.py`. Checkpoint: both
   `--check` runs exit 0; `TestTheEngineCopyIsAByteMirror`.
8. **3-A red-team**, one fix batch; repeat step 7.
9. The tier (`full`) under `nohup`; the strikes; the commit (no ledger id in the subject); `/handoff`,
   which ships.

## Estimated effort

| Step | Estimate |
|---|---|
| Task 0 | 1 h (the drive exists) |
| 1-A | 1.5 h (the 3.10 scratch venv included) |
| 1-B | 2.5 h (the heading, the three legs) |
| 2-A | 3 h |
| 2-C | 2 h |
| 2-B | half a day |
| Syncs and docs | 1 h |
| Red-team and fix batch | 3 h |

About two days of lane time; pack budgets here have run about 2.7 times over on the one pack
measured, so read it as a floor. 1-A and 1-B are a lane of their own if the operator wants the
first-session text fixed before the skeleton is decided.

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red: <per fix, the mutation named above, seen red>
- Red-team: <lanes run, verdicts, what they changed>
- Reach: <members closed / deferred, from the Reach table>
- Date:
