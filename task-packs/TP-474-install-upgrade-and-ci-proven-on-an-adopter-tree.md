# TP-474 — Install, upgrade and CI proven on a tree that is not this one

## Status

- Version target: unscheduled (after `0.8.0b2`).
- Change type: tests (one lifecycle Walk, extended; one hook-start contract; one `doctor` class;
  one `tests/conftest.py::_MARKER_RULES` row), hooks (the three deny hooks' import block and two
  helper modules' name imports; `python3 scripts/sync_vendor_cc.py` after), the CI guard
  (`tools/cc/ci_guard.py`; the same sync), the engine (`espalier/cli.py`'s `upgrade` and
  `install-ci`, `espalier/managed_paths.py`, `espalier/doctor.py` -- the uninstall predicate and a
  hook-start check -- `espalier/models.py`, `espalier/fuse.py`), four shipped agent bodies
  (`python3 scripts/sync_claude_mirrors.py` after), two docs with a packaged mirror
  (`python3 scripts/sync_asset_docs.py` after) and one test module the selfcheck mirror carries
  (`python3 scripts/sync_selfcheck_tests.py` after).
- **Kind: PACK**. Task 0 can end it, or end one step of the lifecycle (partial closure is licensed).
- Gate: **operator decision pending** on the six questions under *Decisions*, each with a
  recommended default.
- Ledger: no class header owns the lifecycle. Its members are §C0 rows that each describe one step
  misbehaving on an adopter tree (`DEF-1176`, `DEF-1061`, `DEF-1063`, `DEF-1064`, `DEF-1104`,
  `DEF-1126`, `DEF-1188`), the §C68 class (`DEF-1050`, `DEF-1051`, `DEF-1052`), the §C64 class (`DEF-1032`,
  `DEF-1033`, `DEF-1034`), `DEF-1077` (§C72) and the fork `DEC-39` (§4A). Reach lists each.
- Cross-pack: `task-packs/TP-468-adopter-axes.md` 2-D parametrises the same Walk by stack and gives
  it a bare `upgrade`; its 2-C drives `upgrade` inside a session chain. Neither lane has landed
  (`git branch -r | grep adopter-axes` lists only the merged foundation lane). Decision 2 is the seam.
- Authored 2026-10-07 at `febfcd4e` on the Air (`python3` only). Every measured sentence names its
  command; the drive is re-stated whole as Task 0.

## Motivation

Every install-path check so far ran on a tree shaped like this one, one verb at a time. An adopter
runs the sequence: `init`, a first commit, `install-ci`, a later `upgrade --execute` on a tree they
have touched, `doctor`, one day `clean-generated --execute`. Each verb has unit pins; no test runs
the sequence, so each step's defect is hidden by the next step reading the state it left as normal.
The sharpest instance: an adopter keeps a local patch to `tools/cc/hooks/_hook_utils.py` by dropping
its marker, as `upgrade`'s own text says to (`espalier/cli.py::_kept_user_files_lines`), then
upgrades. `espalier/cli.py::_deploy_managed_py` keeps the unmarked helper and regenerates its
siblings, which import names the kept copy predates; `write_guard.py` dies at import with exit 1, and
under `docs/external/cc-hook-protocol.md` an exit 1 with no JSON on stdout is a non-blocking error,
so every tool call proceeds with no guard, and `doctor` calls the tree healthy (`DEF-1176`). The
ledger grades it minor for the narrow trigger; the harm when it fires is the whole guard, which is
why it leads this pack.

**Measured at authoring (2026-10-07, `febfcd4e`)** by the Task 0 drive on a Node adopter tree from
`tests/_adopter_tree.py::build_adopter_tree(stack="node", tree="git")` plus the adopter's own
`.github/workflows/ci.yml`, every `ESPALIER_*` variable stripped, 9.0 s wall for the sequence
(`/usr/bin/time -p`):

| Step | What came back | Row |
|---|---|---|
| `install-ci` | stdout names `tools/cc/ci_guard.py`, never the approval marker; `ci_guard.py` lands unmarked | `DEF-1050`, `DEC-10` |
| the commit after it, replayed through the deployed `ci_guard.py` as a `push` | exit 2, `protected paths changed without approval marker` | `DEF-1050` |
| the adopter edits their own `ci.yml`; a `pull_request` replay | exit 2; the text calls their file "the harness's own enforcement layer" | `DEC-39` |
| goal written under `## Goal`; the ONB-1 code from `espalier/cli.py::_ONBOARDING_ROWS` run in the tree | `True` (open) | `DEF-1032` |
| `goal_snapshot = false` set, skeleton kept | `False` (closed) | `DEF-1033` |
| helper unmarked and missing the two budget names; `write_guard.py` on a Read input | exit 1, `ImportError` at `import _speedbump`, empty stdout | `DEF-1176` |
| `upgrade` dry run: twelve hooks staled, `code-reviewer.md` edited with its marker kept, one retired key in `reports/repo_fingerprint.json` | `13 managed files ... (+3 more)`, the body unnamed; `kept as yours: _hook_utils.py`; the report called `absent or unreadable` | `DEF-1064`, `DEF-1126` |
| `upgrade --execute` | the body overwritten and unnamed; no marker clause; helper still unmarked and skewed | `DEF-1077`, `DEF-1052` |
| the hooks after it | `write_guard.py` exit 1; `session_start.py` exit 1 (`import _reinject`); `plan_guard.py` denies; `stop_gate.py` 0; `doctor` **pass** | `DEF-1176`; `DEF-1188` |
| `cc/PACK_MANIFEST.txt` stamped `99.0.0`; `upgrade` dry run | `deployed 99.0.0 -> engine 0.8.0b2`, would re-deploy | `DEF-1104` |
| a clone (no gitignored `reports/`): `doctor` 0, `upgrade --execute`, `doctor` | exit 1, `missing required managed surface: reports/...`; `cc/COMMANDS.md` bytes changed | `DEF-1063` |
| helper re-marked, `clean-generated --execute`, `doctor` | exit 1, `missing required managed surface: cc/COMMANDS.md ...`, next step `init`; `ci_guard.py` still on disk | `DEF-1061` |

The ten rows above with ledger probes all re-derived `STILL_OPEN` the same day
(`python3 tools/cc/check_ledger_probes.py --id <id>`; the ids are in Reach).

**Who is hurt** (`docs/STANDING_PRINCIPLES.md` §16): the operator installing this harness on their
own repositories this month, who will run every one of these verbs on two machines with CI on; and
the first outside adopter, whose first red check, first lost edit and first "re-run init" after a
clean uninstall are each a step this Walk would have caught.

## Scope (in)

Each item maps to a task and to *Files touched*.

1. **1-A** The lifecycle Walk: `tests/test_adopter_lifecycle_diagnostics.py` runs on
   `build_adopter_tree(stack=..., tree="git")` and gains `install-ci`, the first-commit and
   own-workflow replays through the deployed guard, the two ONB-1 reads, the skewed `upgrade` (dry
   run and `--execute`), a hook-start check after `init`, `install-ci` and the upgrade, the
   newer-stamp dry run, the clone upgrade, then the uninstall it already has.
2. **2-A** The deny hooks start or refuse: `tools/cc/hooks/write_guard.py`, `tools/cc/hooks/plan_guard.py`
   and `tools/cc/hooks/config_guard.py` import their helpers -- the sibling modules and the
   `_hook_utils` names alike -- under a guard that turns an import failure into the structured
   deny; the name imports in `tools/cc/hooks/_speedbump.py` and `tools/cc/hooks/_reinject.py`
   degrade. Plus the contract `tests/test_hooks_start_on_a_kept_helper.py`, with its
   `# slow-exempt:` line and its one-row `tests/conftest.py::_MARKER_RULES` entry.
3. **2-B** `upgrade` and `init` name the skew a kept unmarked `_hook_utils.py` leaves beside
   regenerated siblings (`espalier/cli.py`, the kept-files line).
4. **2-C** The uninstall predicate in `espalier/managed_paths.py` and `espalier/doctor.py`: a path
   under a harness-owned root counts only when it carries the marker; the uninstalled report names
   the install-ci files still on disk.
5. **2-D** `doctor` starts the wired hooks: `espalier/doctor.py` imports each hook
   `.claude/settings.json` wires in one bounded child interpreter and reports a module that cannot
   start as FAIL naming the hook and the remedy; `tests/test_doctor.py` gains the class (`DEF-1188`).
6. **3-A** `upgrade` refuses `--execute` when the saved plan is absent and redirects to `init .`.
7. **3-B** `upgrade` names every file it overwrites and says once what the marker does; the four
   `Adapting me` sections in `.claude/agents/code-reviewer.md`, `.claude/agents/test-writer.md`,
   `.claude/agents/architecture-analyst.md` and `.claude/agents/docs-maintainer.md` say the same.
8. **3-C** `upgrade` and `init` order the deployed stamp against the engine and refuse a managed
   overwrite when the deployed side is newer.
9. **3-D** `espalier/models.py` filters the saved fingerprint by declared fields; `upgrade` says
   "older" where it said "unreadable"; `tests/test_models.py` is byte-mirrored, so
   `python3 scripts/sync_selfcheck_tests.py` follows.
10. **4-A** The §C68 helper in `espalier/cli.py`, called from `install-ci`, `upgrade --execute`, a
   re-run `init` and `espalier/fuse.py`'s epilogue (`espalier/fusion_manifest.py`'s re-point step
   too); `docs/INSTALL-CI.md` sections 1 and 2 and `docs/QUICKSTART.md`'s CI and upgrade sections
   carry the clause.
11. **4-B** `DEC-39` as decided (Decision 1): under (b), `tools/cc/ci_guard.py` applies the
    `.github/workflows/` prefix only on the self-host repository, `espalier/surface_contract.py`
    moves in step, and the pins in `tests/test_ci_guard.py`, `tests/test_surface_contract.py` and
    `tests/test_protected_path_contract_parity.py` pin the posture instead of the prefix;
    `docs/INSTALL-CI.md` section 3 is reworded.
12. **5-A** §C64: the ONB-1, ONB-6 and ONB-7 codes in `espalier/cli.py` read their files the way the
    harness's readers do; the truth table in `tests/test_cli_deploy.py` gains the missing states.
13. **6-A** Red-team, per lane.

Paths, for the scope walk:

- `tests/`
- `tools/cc/hooks/`, `tools/cc/ci_guard.py`, `espalier/_vendor/cc/` (by the vendor sync)
- `espalier/cli.py`, `espalier/fuse.py`, `espalier/fusion_manifest.py`, `espalier/managed_paths.py`,
  `espalier/doctor.py`, `espalier/models.py`, `espalier/surface_contract.py`
- `.claude/agents/`, `espalier/assets/claude/agents/`, `examples/dogfooding/.claude/agents/` (the two
  mirrors, by the sync)
- `docs/INSTALL-CI.md`, `espalier/assets/docs/INSTALL-CI.md` (by the sync), `docs/QUICKSTART.md`
- `task-packs/FORWARD_LEDGER.md`, `task-packs/LEDGER_PROBES.json`

## Scope (out)

- **`TP-473`'s audience work on the same deployer.** `TP-473` (what init ships is addressed to
  the adopter) scopes `DEF-1077` out to this pack, since the overwrite of an adopter-edited
  marked body is upgrade mechanics and the walk pins it, and its 1-C render step waits on this
  pack where `DEF-1063`'s re-render defect sits on the same seam; this pack strips no
  maintainer text from a body, which stays `TP-473`'s.
- **TP-468's 2-D and 2-C.** 2-D's stack parametrisation of the Walk and its bare `upgrade` verbs
  are the fixture this pack extends; 2-C's `upgrade` step asserts the state the next SessionStart
  reads, a different thing. Decision 2 picks the seam; nothing here re-plans 2-C.
- **`DEF-1051`'s fusion walk.** The Walk does not run `fuse`. The §C68 helper's call site in
  `espalier/fuse.py::cmd_fuse` lands in 4-A because a class is never patched one instance at a time
  (root `CLAUDE.md` Core Rule 12); its proof is the row's own probe, not the Walk.
- **`DEF-1077`'s overlay and relief roster.** An unmanaged `.claude/agents/<name>.local.md` the body
  reads first is a feature with its own design; `tools/cc/hooks/_hook_utils.py::RELIEF_FLAGS` is a
  Stop-gate design. 3-B lands the row's "short term" clause only.
- **`DEF-1104`'s build-identity digest.** Ordering two version strings is stdlib work (3-C); a
  digest stamped beside the version is a packaging decision. Risk 4 names the probe hazard.
- **`DEF-1057`'s init and doctor WARN on tracked `cc/` and `tools/cc/` paths.** The Walk's tree has
  none before `init`. Its marker-predicate half is 2-C's; the WARN half stays with the row.
- **`DEF-945`** (trigger choice, `fuse --no-ci`): a working tree cannot see the repository's Actions
  policy, so the Walk cannot prove the symptom; the fix is a CLI option set with its own fork.
- **`DEF-989`** (`--add-allows` widens a path-scoped `Write`): needs an adopter settings file with
  path-scoped rules, not on this lifecycle; its probe is in-process and exact.
- **`DEF-928`, `DEF-929`, `DEF-1062`**: Windows-only symptoms (closed stdin at `init`, the PowerShell
  statusline render, CRLF round-trip of a tracked `settings.json`); the Windows box is their home.
- **`DEF-1134`, `DEF-1150`, `DEF-1023`, `DEF-1142`**: diagnostic-verb rows (link readers, the selfcheck
  child's `PYTEST_ADDOPTS`, `integrity verify` on an unparseable settings file, the scanners'
  dangling-`.git` walk). None is a lifecycle step; each has its own exact probe.
- **`DEC-10`** (should `ci_guard.py` and `harness-guard.yml` carry the marker). 2-C discloses them
  in the uninstalled report; whether the uninstall deletes them stays the fork.
- **A `_SLOW_FILES` move for the Walk.** 1-A keeps the module's `# slow-exempt:` line (9.0 s for
  the whole drive, under the 60 s ceiling), so the Walk needs no `_SLOW_FILES` row; the one
  `tests/conftest.py` edit this pack makes is the `_MARKER_RULES` row for the new module (Files
  touched; the other machine's claim on the file was released 2026-10-07). If the re-measure puts
  the Walk over the ceiling, its `_SLOW_FILES` row is a second line in the same file, not a wait.

## Task 0 — Verify (may end this pack, or one step of it)

**Oracle:** the drive, re-run at execution from the repository root with the suite's interpreter,
every `ESPALIER_*` and `CLAUDE*` variable stripped, on `build_adopter_tree(<scratch>, stack="node",
tree="git")` plus the adopter's own `.github/workflows/ci.yml`, in this order, each step's stdout,
stderr and exit code kept: `init .`; the ONB-1 code with the goal written, then with
`goal_snapshot = false` and the skeleton kept; commit; `install-ci .`; commit; the deployed
`tools/cc/ci_guard.py` with `GITHUB_EVENT_NAME=push` and `BASE_SHA=<the init commit>`; the adopter's
`ci.yml` edited and committed, the guard with `GITHUB_EVENT_NAME=pull_request`, a `PR_TITLE`
without the marker and `PR_HEAD_SHA=<head>`; `doctor .`; the helper's marker line removed and
`del spawn_timeout, STATE_WRITE_LOCK` appended, twelve other hooks staled by a comment,
`.claude/agents/code-reviewer.md` appended to with its marker kept, one retired key written into
`reports/repo_fingerprint.json`; `write_guard.py` on `{"tool_name": "Read", "tool_input":
{"file_path": "notes.txt"}}` with `CLAUDE_PROJECT_DIR` the tree; `upgrade .`; `upgrade . --execute`;
every hook `.claude/settings.json` wires, once each, on a no-op input for its event; `doctor .`;
the manifest stamp rewritten to `99.0.0`, `upgrade .`, restored; commit, `git clone`, in the clone
`doctor .`, `upgrade . --execute`, `doctor .`; on the tree, the helper's marker restored,
`clean-generated --execute .`, `doctor .`.

**Refuting results, each with its exit:**

- The Walk already drives `install-ci` or `upgrade`
  (`grep -n "install-ci\|upgrade" tests/test_adopter_lifecycle_diagnostics.py`). Measured: neither
  word appears; its tree is `README.md` plus `app.py` on a bare `git init`. If a landed 2-D has
  added `upgrade`, 1-A shrinks to the steps 2-D did not add, and says so.
- `_deploy_managed_py` refreshes an unmarked helper. Measured: `skipped_user_file`; the upgrade
  printed `kept as yours: tools/cc/hooks/_hook_utils.py`. If it refreshes, 2-A and 2-B have no
  trigger: **stop and re-raise** `DEF-1176`.
- `write_guard.py` on the skewed tree exits 0 or 2 with a decision. Measured: exit 1, a traceback,
  empty stdout, before and after the upgrade. If it emits a decision, 2-A is inert: re-raise.
- The first-commit replay exits 0, or `install-ci`'s stdout names the marker. Measured: 2, and no
  marker. If either flips, drop 4-A's install-ci site and keep the rest.
- The own-`ci.yml` pull-request replay exits 0. Measured: 2. If 0, `DEC-39` is decided and 4-B drops.
- `doctor` in the clone passes after `upgrade --execute` and `cc/COMMANDS.md` is byte-unchanged.
  Measured: exit 1 and changed. If both hold, 3-A drops.
- `doctor` after the uninstall reads `harness not on disk`. Measured: exit 1, `missing required
  managed surface`, next step `init`. If it reads uninstalled, 2-C drops.
- `doctor` on the skewed tree after `upgrade --execute` fails naming a hook. Measured: exit 0,
  `pass`, with `write_guard.py` and `session_start.py` exiting 1 at import. If it already names
  them, 2-D drops.
- The ONB-1 code prints `False` with the goal written and `True` with the key set and the skeleton
  kept. Measured: `True` and `False`. If both are right, run the `DEF-1034` probe alone; `False`
  drops 5-A.
- The `99.0.0` dry run refuses or names the deployed side as newer. Measured: proceeds. Else 3-C drops.
- The retired key is reported as older, not unreadable. Measured: `absent or unreadable`. Else 3-D
  drops.

**Also measure:** the drive's wall time (9.0 s at authoring; the module's new `# slow-exempt:`
figure) and the count of hooks `settings.json` wires (derived from the file, never a literal).
Record every value in Landing. Any refutation not listed here is **stop and re-raise**.

## Relevant memory

Recent pattern: the defects reviewers find on this tree sit in the repair and in the tests that
prove it, not in the original code (`task-packs/TP-468-adopter-axes.md`: both reviewers returned
REQUEST CHANGES on a green foundation lane). This pack's likeliest repair defect is a Walk assertion
that passes on the pre-fix tree because the step before it restored the state (the helper re-marked
too early; the clone made before the skew), which is the very shape the pack exists to end. Earn
each red against today's `main`, where the drive's values are known.

| Entry | Where |
|---|---|
| A skip-if-exists deploy helper has no upgrade-drift path — an untouched template silently keeps stale bytes across versions | `docs/SHARP_EDGES.md` (the entry of that title) |
| CI Approval Marker — Trust the Trigger, Not the OR | `docs/SHARP_EDGES.md :: CI Approval Marker — Trust the Trigger, Not the OR` |
| The Install Path Can Break While Every Test Is Green | `docs/SHARP_EDGES.md :: The Install Path Can Break While Every Test Is Green` |
| Fix the class, not the instance | `memory/fix-the-class-not-the-instance.md` |
| Read the neighbours before adding a sibling | `memory/read-the-neighbours-before-adding-a-sibling.md` |
| One writer per shared state | `memory/one-writer-per-shared-state.md` |

Resolved 2026-10-07 by `python3 tools/cc/hooks/_recall.py "<topic>"` with the topics `upgrade keeps
a hand-owned helper and the hook dies at import`, `first commit after install-ci fails the harness
guard approval marker` and `doctor after uninstall reads the tree as a broken install marker
predicate`. The topic `the next lifecycle step hides the defect the previous step left` returned
nothing that fits, which is the gap this pack fills. Re-run rather than trust this list if the pack
has been sitting. Folders touched, so the folder-`CLAUDE.md` ladder fires on entry: `tests/` (a new
`test_*.py` is classified in `tests/conftest.py::_MARKER_RULES`; `git add` it before gating),
`tools/cc/` (zero espalier imports; the vendor sync), `.claude/` (the mirror sync), `espalier/_vendor/`
(never hand-edited).

## Implementation

Every fix below is a **fix shape, untested**, unless it says *driven*. Each names the mutation its
test must die to; Landing records that it did.

### 1-A The Walk — `tests/test_adopter_lifecycle_diagnostics.py`

`walked` builds from `build_adopter_tree(tmp, stack=<param>, tree="git")` and, before the first
commit, writes the two extra files the existing assertions need: `app.py` with the `print` that
`TestScanNamesItsReports` counts, and the adopter's own `.github/workflows/ci.yml`. The verbs land
in the Task 0 order, each output kept under a name; `TestTheWalkRan` names every new verb with its
documented exit. New classes, one per step, each docstring naming its row:

- `TestInstallCiNamesTheMarker` (`DEF-1050`): the stdout names the approval marker in both
  channel forms; the push replay still exits 2 (no first-install exemption, by the row's own
  choice) and its text names the same remedy.
- `TestAnAdoptersOwnWorkflowIsTheirs` (`DEC-39`): under (b) the pull-request replay exits 0; under
  (a) the deny text names the file as the adopter's.
- `TestOnbOneReadsTheGoal` (`DEF-1032`, `DEF-1033`): `False` with the goal written; `True` with the
  key set and the skeleton kept.
- `TestEveryWiredHookStarts`: after `init`, after `install-ci` and after `upgrade --execute`, each
  entry `settings.json` wires is launched once on a no-op input for its event and exits 0 or 2 with
  the channel rule (through TP-468 2-B's launch-as-wired runner if it has landed, else a local
  launcher reading the file the way `_rendered_hook_wiring_check` in this module does); on the
  skewed tree, `write_guard.py` emits a deny (`DEF-1176`).
- `TestUpgradeNamesWhatItReplaces` (`DEF-1064`, `DEF-1077`): the dry run and the execute report name
  `.claude/agents/code-reviewer.md`; the edit is gone (the documented contract) and the report says
  what the marker would have done.
- `TestUpgradeSaysOlderNotUnreadable` (`DEF-1126`).
- `TestUpgradeRefusesADowngrade` (`DEF-1104`): the `99.0.0` dry run names the deployed side as newer
  and would overwrite nothing.
- `TestUpgradeRefusesWithoutTheSavedPlan` (`DEF-1063`): in the clone, `--execute` exits non-zero
  naming `init .`, `doctor` still passes, `cc/COMMANDS.md` is byte-unchanged.
- `TestDoctorAfterUninstall` (existing, `DEF-770`) gains `DEF-1061`: with `ci_guard.py` on disk,
  `doctor` reads `harness not on disk` and names `tools/cc/ci_guard.py` and
  `.github/workflows/harness-guard.yml` as install-ci's files still here.

Stack-conditional assertions key on the parameter (`scan` prints `skipped_no_python_files` on
Node). The helper is re-marked before the uninstall so the uninstall takes it; the test that the
hooks directory is gone keeps holding.

**Mutation:** today's `main` is the pre-fix state for every class above; the Motivation table is
the expected red. Each class lands red first, then its fix. **Refutation:** a class green on `main`
was built on restored state; find the restoring step and move the assertion before it.

### 2-A The deny hooks start or refuse — `tools/cc/hooks/` *(the skew driven; the shape untested)*

```python target=tools/cc/hooks/write_guard.py
def _import_siblings() -> None:
    """Import everything this hook judges with that a kept helper can break:
    the sibling modules and the names taken from _hook_utils by name. A
    failure here is a tree whose helper predates its siblings (an upgrade
    kept an unmarked _hook_utils.py); the protocol reads an uncaught exit 1
    as non-blocking, so the failure becomes the structured deny instead of a
    traceback. `import _hook_utils` itself stays at module top: it is the
    floor (a helper that cannot import at all is not this pack's skew)."""
    global os_error_text, _integrity, _maintenance_mode, _bash_patterns, _denial_reasons, _protected_zones, _speedbump, _reinject
    from _hook_utils import os_error_text  # noqa: E402
    import _integrity, _maintenance_mode, _bash_patterns, _denial_reasons, _protected_zones, _speedbump, _reinject  # noqa: E401,E402
```

The module-top `from _hook_utils import os_error_text` (`write_guard.py`, `plan_guard.py` and
`config_guard.py` each carry one; `config_guard.py` also `from _json_safe import decode_bom`) moves
inside the guard, or the per-name contract's `os_error_text` cell exits 1 by construction. `__main__`
calls `_import_siblings()` first, under a catch that prints the `deny` shape this file already
emits (`hookSpecificOutput.permissionDecision: deny`, built from literals -- `_denial_reasons` may
be the module that failed) naming the failing module or name as `type(exc).__name__: exc` (never
through `os_error_text`, which may be the name missing) and the remedy (restore the helper's marker
and run `espalier upgrade --execute` from a terminal), then exits 0; only after a clean
`_import_siblings()` does `main` run, so its crash guard's own `os_error_text` call is bound.
`plan_guard.py` and `config_guard.py` get the same `_import_siblings` for their own imports
(`_integrity`, `_maintenance_mode`, `_denial_reasons`, and the name imports), each printing the
deny shape its event already uses. In `_speedbump.py` and `_reinject.py`, `spawn_timeout` and
`STATE_WRITE_LOCK` are read as attributes with the degrade
`tools/cc/hooks/_integrity.py::_STATE_WRITE_LOCK` already uses. Then `python3 scripts/sync_vendor_cc.py`.

**The contract,** `tests/test_hooks_start_on_a_kept_helper.py`: the names each deny hook's import
graph takes from `_hook_utils` are derived by AST over the whole module (`ast.walk`, not the
top-level body: after the fence the name imports sit inside a function, and a body-only walk drops
them -- measured 2026-10-07: the body walk prints `12 35`, the whole-module walk `13 40`):
`python3 -c "import ast,pathlib;per={p.name:{a.name for n in ast.walk(ast.parse(p.read_text(encoding='utf-8'))) if isinstance(n,ast.ImportFrom) and n.module=='_hook_utils' for a in n.names} for p in pathlib.Path('tools/cc/hooks').glob('*.py')};per={k:v for k,v in per.items() if v};print(len(per),len(set().union(*per.values())))"`.
For each deny hook and each name it reaches, run it from a copy of the hooks directory whose
`_hook_utils.py` lacks that name: the exit is 0 with a deny object or 2, never 1. The floor is the
module `_hook_utils` itself importing: no cell removes the file or breaks its syntax (a helper that
cannot import at all is not the measured skew; a row of its own if one is ever found). Reporters
are asserted on the realistic skew only (the two budget names): exit 0. The module spawns hooks, so
its docstring carries `# slow-exempt: <n> hook children, measured <t>` (the idiom
`tests/test_test_suite_contract.py::test_every_subprocess_test_is_slow_or_exempt` reads), and its
stem carries `hook`, so `tests/conftest.py::_MARKER_RULES` gets its one security-tuple row
(`tests/test_documented_claims.py::TestSecurityMarkerCoverage` requires the literal stem).

**Mutation:** revert `_import_siblings` to the bare imports; the `write_guard` cells red with exit 1
-- the `os_error_text` cell among them, which is why that import moves. **Refutation:** a name a
hook needs to *judge* cannot degrade without changing the verdict; that name goes on a floor set
the contract declares beside its derivation and 2-B's comparison names first. **Cost:** the deny
tree refuses every call until the helper is repaired, the kill-switch posture, said in the deny;
Decision 3 confirms it.

### 2-B `upgrade` names the skew it leaves — `espalier/cli.py::cmd_upgrade`

Where the kept-files line prints (`_kept_user_files_lines`) and the kept file is
`tools/cc/hooks/_hook_utils.py`: compare the names the packaged hook sources import from it (the
same AST walk over `_deploy_source_path("tools/cc/hooks")`) with the names the kept copy defines,
and name the missing ones with the remedy. Both arms. **Mutation:** the Walk's skewed dry run lacks
the line. **Refutation:** an unparsable kept copy cannot be compared; say that, never fall silent.

### 2-C The uninstall predicate — `espalier/managed_paths.py`, `espalier/doctor.py`

`fallback_managed_paths` asks `espalier/managed_markers.py::file_carries_marker` on its `cc/` and
`tools/cc/` globs, and `_deployed_surface_remains` applies the marker skip it has for `.claude/` to
every `HARNESS_OWNED_ROOTS` entry (one predicate, the one `espalier/cleanup.py::_file_is_managed`
deletes by). `_uninstall_leftovers` adds the present entries of
`espalier/managed_inventory.py::get_install_ci_artifacts` under a line saying they are install-ci's
and the gate keeps running until they are removed. **Mutation:** revert the skip; the Walk's
after-uninstall `doctor` reds with exit 1. **Refutation:** a fresh `init` plus `install-ci` tree must
still pass `doctor` (the row says it does under this rule); if not, the predicate is wrong, not the Walk.

### 2-D `doctor` starts the wired hooks — `espalier/doctor.py` *(the blindness driven; the shape untested)*

The Motivation table's post-upgrade `doctor` read `pass` on a tree where two wired hooks exited 1
at import (`DEF-1188`). `run_doctor_check` gains one check, `_check_wired_hooks_start`, over a child
`_probe_wired_hooks_start` spawns in the shape `_probe_deployed_stop_gate` already has: one bounded
child interpreter (`timeout=20`, the hooks directory first on its `sys.path`, `cwd` the tree) runs
a `-c` source, `_HOOK_START_PROBE`, that imports each wired hook module by name
(`importlib.import_module`) inside its own `try`, catching `BaseException` per module (a
`SystemExit` with code 0 or `None` counts as a start -- `tests/conftest.py::harness_repo`'s stub
hooks exit 0 at import), and prints one JSON line `{script: {"ok": bool, "error": "<type>: <first
line>"}}`. The engine imports no `tools/cc` module (the architecture rule, and the sibling pin
`tests/test_doctor.py::test_doctor_leaves_sys_path_and_sys_modules_as_it_found_them`). The hooks to
try are the canonical scripts `espalier/harness_config.py::_readable_wirings_of` finds wired (both
the `command` and the `args` spelling; this box wires through `args`); when `settings.json` does not
reach a read or wires none, the check returns nothing (presence and `_check_governance_event_wiring`
own those trees, and the parity lock `tests/test_ci_guard.py::test_doctor_ci_scan_parity_on_malformed_settings`
counts governance lines alone, so a new FAIL kind must not appear on its seven shapes). Each not-ok
module is one FAIL: `hook cannot start: tools/cc/hooks/<script> -- <error>` plus a next step naming
the kept helper's marker and `espalier upgrade --execute`. A child that does not answer within the
budget is one WARN naming the budget, never a crash.

Why an import, not a start on an empty input: the hooks' import-time statements are `sys.path`
inserts and two guarded imports (measured 2026-10-07 by AST over
`surface_contract.get_canonical_hook_scripts()`), while a start of `session_start.py` writes a
session marker and a start of `stop_gate.py` can run a gate -- a diagnostic must not mutate the tree
it reads. A hook that dies after import and before judging is the Walk's `TestEveryWiredHookStarts`
to catch (1-A), not this check's.

`tests/test_doctor.py::TestDoctorNamesAHookThatCannotStart`, on a tree `cmd_init` builds under
`tmp_path` (the `TestDoctorNamesTheStopGatePosture._init_tree` shape; never the session-scoped
`adopter_tree`, one writer per tree): the fresh tree adds no line; the helper appended with
`del spawn_timeout, STATE_WRITE_LOCK` reads `fail` with lines naming `write_guard.py` and
`session_start.py`; a syntax error written into one wired hook names that hook. **Mutation:** drop
the `run_doctor_check` call; the two fail cases read `pass`. **Refutation:** a hook that imports
clean in the child but dies at `main` on the real event (none measured) means the import probe is
the weaker oracle; then the check gains the per-event no-op input the Walk's launcher uses, and
Landing says so. **Cost:** one interpreter start per `doctor` (the stop-gate probe is already one);
measure it and record the figure in Landing.

### 3-A Refuse `--execute` without the saved plan — `cmd_upgrade`

When `plan is None` on the execute arm: print the `not compared` item, say that `--execute` would
re-render `cc/COMMANDS.md` and `cc/LIVE_SURFACE.md` from an empty table, name `init .` as the verb
that restores a clone, exit 2. The dry run keeps reporting. **Mutation:** the clone step's `doctor`
reds. **Refutation:** `init .` on the clone must leave `git diff` empty (the row measured it does);
if a later change makes `init` rewrite something, the redirect is wrong and the row is re-raised.

### 3-B Name every overwritten file — `cmd_upgrade`, `_surface_drift_lines`, four bodies

`_surface_drift_lines` and the execute arm's `re-deployed` line call `_name_paths` with
`limit=len(...)` as `espalier/cli.py::_print_init_summary` does; the version-bump dry run lists
the files instead of its generic sentence; one sentence follows the list: a marked file you edited
is replaced on `--execute`; drop its marker to keep it, and it stops receiving upstream fixes. The
four `Adapting me` sections say the same in one sentence each and stop saying `Edit this file
directly` without it. `python3 scripts/sync_claude_mirrors.py`. **Body-lane order** (four packs edit
the shared command and agent bodies): this sub-task lands after `TP-470` 3-A and `TP-471` 3-A to
3-C (`TP-471` 3-B and 3-C edit `test-writer.md`'s `Run:` fence and `docs-maintainer.md`'s runner
sentence, different regions of two of these four files) and before `TP-473` 1-B, whose audience
gate reads the final text; a hand resolve happens in the `.claude/` source of truth, then the
mirror sync. **Mutation:** restore the default limit; the twelve-stale-hooks dry run no longer
names the body.

### 3-C Order the stamps — `cmd_upgrade`, `cmd_init`

A stdlib compare of the deployed stamp against `__version__` (split on `.`, numeric where it
parses, a pre-release tag below its release); when the deployed side is newer, both verbs say so
and refuse the managed overwrite, naming the files they would have rewritten. **Mutation:** the
`99.0.0` dry run proceeds. **Refutation:** two builds of one pre-release string still compare equal;
that is `DEF-1104`'s digest half, scoped out.

### 3-D Filter the saved report by declared fields — `espalier/models.py::RepoFingerprint.from_dict`

`{k: v for k, v in data.items() if k in {f.name for f in fields(cls)}}` before the constructor, the
nested constructors the same way; `cmd_upgrade`'s message says "saved by an older release,
re-baselined on --execute" when the file parsed but carried undeclared keys. **Mutation:** the
retired-key step prints `unreadable`.

### 4-A The §C68 helper — `espalier/cli.py::_approval_marker_lines`

`_approval_marker_lines(repo_root, written: list[str]) -> list[str]`: empty unless
`tools/cc/ci_guard.py` is on disk and some written path passes
`espalier/surface_contract.py::is_protected_from_ci` and is not ignored (the `check-ignore
--no-index` reader `cmd_init` already uses); otherwise two lines, the marker in the HEAD commit
message for a push and the marker with the head's hash in the title for a pull request. Called
after `cmd_install_ci`'s `Wrote:` block, after `cmd_upgrade`'s `re-deployed` line (the written list
plus a rewritten tracked settings file), after `cmd_init`'s summary when `updated_managed` holds a
gated path, and in `cmd_fuse`'s epilogue; `FINISH_UP_STEPS`'s re-point step names the marker beside
maintenance mode. `INSTALL_CI_INSTRUCTIONS` gains the clause; `docs/INSTALL-CI.md` sections 1 and 2
and `docs/QUICKSTART.md`'s CI and upgrade sections carry it; `python3 scripts/sync_asset_docs.py`.
**Mutation:** remove the install-ci call; `TestInstallCiNamesTheMarker` reds and the `DEF-1050`
probe prints `True False` again. **Refutation:** on the self-host tree the helper stays silent for a
push (`tests/test_ci_guard.py::TestApprovalMarkerRepoPosture` is the posture pin).

### 4-B `DEC-39` — `tools/cc/ci_guard.py` (under (b))

`is_protected` keeps its one-argument shape (`tools/cc/ship.py::guard_predicate` loads it by path
and calls `is_protected(rel)`): the posture is a module value `run()` sets from `cwd` through
`_ci_is_self_host_repo`, adopter by default; the `.github/workflows/` prefix applies only under the
self-host posture; `PROTECTED_FILES` keeps `harness-guard.yml` and `ci_guard.py` everywhere.
`espalier/surface_contract.py::is_protected_from_ci` gains the same posture so
`tests/test_surface_contract.py`'s parity holds. The pins that assert the prefix on every repo
(`tests/test_protected_path_contract_parity.py`'s `test_ci_guard_protects_workflows_prefix` and its
surface-contract twin) assert it under the self-host posture and its absence under the adopter
one. `tests/test_ci_guard.py::_touch_protected` commits a hook path instead of
`.github/workflows/test.yml`, so `TestApprovalMarkerRepoPosture` keeps its three axes. The deny text
stops calling an adopter file the harness's; `docs/INSTALL-CI.md` section 3 lists the prefix as
self-host. `python3 scripts/sync_vendor_cc.py`. **Mutation:** restore the unconditional prefix; the
Walk's own-`ci.yml` replay reds with exit 2. **Refutation:** the self-host repository's own
`release.yml` and siblings must still require the marker on a pull request there
(`approval_marker_required` is True for every non-push event; assert it stays so).

### 5-A §C64 — `espalier/cli.py::_ONBOARDING_ROWS`

ONB-1's code: read `cc/GOAL.md` through a BOM-aware decode (`tools/cc/_json_safe.py::decode_bom`'s
rule); while the file exists, open iff the `## Goal` body (to the next `## ` or end of file)
carries `(not set`, whatever the key; once the file is gone, open iff the key is unset; a decode
error or a NUL keeps it open. ONB-6 and ONB-7 read `espalier.toml` and the stubs the same way, an
undecodable stub counting as edited. The truth table in
`tests/test_cli_deploy.py::TestOnboardingProbesDoNotWalk` gains the goal-written, the
opted-out-and-kept (open), the opted-out-and-deleted (closed) and the UTF-16 states; its
key-under-a-table ONB-1 leg deletes the file, as the `DEF-1033` row says it must. **Mutations:**
the three rows' probes (`True`, `False`, `True` today) flip only all together under the section fix;
rewording the second placeholder flips none. **Refutation:** a GOAL.md seeded before the fix still
carries the old second placeholder; the section rule reads it right, a placeholder rewrite does not.

### 6-A Red-team (budgeted; see Risks)

`code-reviewer` and `failure-mode-reviewer` on a snapshot clone of each lane's diff, edits frozen,
asked for the mutation that survives: a Walk step green on `main`; a deny hook whose guard swallows
a judgment error as an import error; a posture read from the wrong root in CI; an ONB-1 state the
truth table does not hold. One fix batch per lane.

## Affected symbols

The Walk's module fixture `walked` is declared through `TestTheWalkRan`, the test that names its
verbs (its bare name is a common word). `_reinject.py`'s `spawn_timeout` alias is an import, not a
definition, so the function that spawns through it is declared instead.

### Changed-semantics

- `tests/test_adopter_lifecycle_diagnostics.py::TestTheWalkRan` (the Walk runs on `build_adopter_tree`, gains the lifecycle verbs; this test names them)
- `tests/test_adopter_lifecycle_diagnostics.py::TestDoctorAfterUninstall` (gains the `ci_guard.py`-on-disk case)
- `tools/cc/hooks/_reinject.py::_is_tracked` (its spawn timeout reads the degraded alias)
- `espalier/cli.py::cmd_upgrade` (refuses `--execute` without the saved plan; orders the stamps; names every file and the skew; the marker lines)
- `espalier/cli.py::cmd_init` (orders the stamps; the marker lines on a re-run)
- `espalier/cli.py::cmd_install_ci` (names the marker)
- `espalier/cli.py::INSTALL_CI_INSTRUCTIONS` (the marker clause)
- `espalier/cli.py::_surface_drift_lines` (uncapped)
- `espalier/cli.py::_ONBOARDING_ROWS` (ONB-1, ONB-6, ONB-7 codes)
- `espalier/fuse.py::cmd_fuse` (the epilogue names the marker)
- `espalier/fusion_manifest.py::FINISH_UP_STEPS` (the re-point step names the marker)
- `espalier/managed_paths.py::fallback_managed_paths` (marker check on the `cc/` and `tools/cc/` globs)
- `espalier/doctor.py::_deployed_surface_remains` (the marker skip under every owned root)
- `espalier/doctor.py::_uninstall_leftovers` (names the install-ci files)
- `espalier/doctor.py::run_doctor_check` (calls the hook-start check; one FAIL per wired hook whose module cannot start)
- `espalier/models.py::RepoFingerprint.from_dict` (declared-field filter)
- `espalier/surface_contract.py::is_protected_from_ci` (the workflows prefix by posture; only under Decision 1 (b))
- `tools/cc/ci_guard.py::is_protected` (the same, one-argument shape kept; only under (b))
- `tools/cc/ci_guard.py::PROTECTED_PREFIXES` (its comment and reading; only under (b))
- `tests/test_ci_guard.py::_touch_protected` (commits a hook path)
- `tests/test_cli_deploy.py::TestOnboardingProbesDoNotWalk` (the truth table)
- `tests/test_doctor.py::TestDoctorUninstalledTree` (an install-ci tree with an adopter file)

### Renamed

- (none -- every symbol keeps its name.)

### Added-paths

- `tools/cc/hooks/write_guard.py::_import_siblings`
- `tools/cc/hooks/plan_guard.py::_import_siblings`
- `tools/cc/hooks/config_guard.py::_import_siblings`
- `tools/cc/hooks/_speedbump.py::_spawn_timeout`
- `tools/cc/hooks/_speedbump.py::_STATE_WRITE_LOCK`
- `espalier/cli.py::_approval_marker_lines`
- `espalier/doctor.py::_HOOK_START_PROBE`
- `espalier/doctor.py::_probe_wired_hooks_start`
- `espalier/doctor.py::_check_wired_hooks_start`
- `tests/test_doctor.py::TestDoctorNamesAHookThatCannotStart`
- `tests/test_hooks_start_on_a_kept_helper.py`
- `task-packs/TP-474-install-upgrade-and-ci-proven-on-an-adopter-tree.md`

### Removed-paths

- None.

## Reach

Members derived by: the rows the coordinating brief named for this lifecycle, each read whole
(`grep -nE '^\| \`DEF-NNN\` ' task-packs/FORWARD_LEDGER.md`), the §C68 and §C64 class sections
(`grep -n '^### §C68\|^### §C64' task-packs/FORWARD_LEDGER.md`), and `DEC-39`'s fork text. This is
not an absence proof: another §C0 row may describe a lifecycle step in words none of these greps
read. Probes re-derived 2026-10-07 with `python3 tools/cc/check_ledger_probes.py --id <id>`: all ten
that existed at the drive read `STILL_OPEN`; `DEF-1188`'s, filed the same day, read `STILL_OPEN`
under the same command at the fold.

| Item | Status | Evidence |
|---|---|---|
| `DEF-1176` | **CLOSED by 2-A and 2-B** | the Walk's skewed tree: `write_guard.py` emits a deny; the probe's `0 1` reads `0 0`; the per-name contract reds on the bare imports |
| `DEF-1050` | **CLOSED by 4-A** | `install-ci` stdout names the marker; probe `True False` flips |
| `DEF-1052` | **CLOSED by 4-A** | the execute report names it; probe flips |
| `DEF-1051` | **CLOSED by 4-A** (sibling site, not driven by the Walk) | its own probe: the epilogue after `CI gate:` names the marker |
| `DEC-39` | **DECIDED by the operator; (b) lands in 4-B** | the own-`ci.yml` pull-request replay exits 0 under (b); under (a) the deny text stops misnaming the file |
| `DEF-1061` | **CLOSED by 2-C** | `doctor` after the uninstall exits 0 and reads `harness not on disk`; probe `1` flips |
| `DEF-1057` | **NOT CLOSED** | its predicate half lands in 2-C (the probe's third and fourth values flip); its init and doctor WARN half is not driven here and keeps the row open |
| `DEF-1063` | **CLOSED by 3-A** | the clone step; probe `False` flips |
| `DEF-1064` | **CLOSED by 3-B** | all three reports name the edited body; probe flips |
| `DEF-1077` | **NOT CLOSED** (the row's short-term clause lands in 3-B) | the Walk proves the overwrite; the overlay and `RELIEF_FLAGS` stay with the row |
| `DEF-1104` | **NOT CLOSED** (the ordering half lands in 3-C) | the `99.0.0` dry run refuses; the digest half is out, and the probe would flip anyway (Risk 4) |
| `DEF-1126` | **CLOSED by 3-D** | the retired-key step says older; probe `TypeError` flips |
| `DEF-1032` | **CLOSED by 5-A** | the goal-written step prints `False`; probe flips |
| `DEF-1033` | **CLOSED by 5-A** | the opt-out-and-kept step prints `True`; probe flips |
| `DEF-1034` | **CLOSED by 5-A** (sibling in the same tuple; its own probe) | the UTF-16 and cp1252 states print `False` |
| `DEC-10` | **NOT DECIDED** | 2-C discloses the two files; marking them is the fork |
| `DEF-945`, `DEF-989`, `DEF-928`, `DEF-929`, `DEF-1062`, `DEF-1134`, `DEF-1150`, `DEF-1023`, `DEF-1142` | **NOT REACHED** | Scope (out), each with its reason |
| `DEF-1188` | **CLOSED by 2-D** | the Walk's post-upgrade `doctor` reads `fail` naming `write_guard.py` and `session_start.py`; the filed probe reads doctor's source for a compile or import keyword (`False` while open) and flips on the child source's `import_module`, which is text, so the lane re-pins it to the behaviour before the strike: the Task 0 skew on a scratch init tree, then `doctor .`, open value `0` (Risk 4's treatment, same lane) |

## Pass criteria

- Every class 1-A adds was seen red on `main` with the Motivation table's value and green with its
  fix; Landing records each pair.
- `TestTheWalkRan` names every new verb with its exit; the module's `# slow-exempt:` figure is
  re-measured and written, under the per-test ceiling in `pyproject.toml`.
- No assertion in an existing test is weakened; `tests/test_doctor.py::TestDoctorUninstalledTree`'s
  one-hook-left and one-wired-hook controls keep their fail verdict. Strengthening is allowed and
  recorded.
- `tests/test_hooks_start_on_a_kept_helper.py`: every cell for the three deny hooks exits 0 with a
  deny object or 2; none exits 1.
- The new module carries its `# slow-exempt:` figure and its `_MARKER_RULES` row:
  `tests/test_test_suite_contract.py::test_every_subprocess_test_is_slow_or_exempt` and
  `tests/test_documented_claims.py::TestSecurityMarkerCoverage` are green with it collected.
- `doctor` on the Walk's skewed tree exits 1 with one failure per hook that cannot start, each
  naming the hook; on the tree as `init` left it the check adds no line;
  `tests/test_ci_guard.py::test_doctor_ci_scan_parity_on_malformed_settings` and
  `tests/test_doctor.py::test_doctor_leaves_sys_path_and_sys_modules_as_it_found_them` keep passing.
- The probes of every row Reach marks CLOSED flip; `DEF-1057`'s and `DEF-1077`'s do not; `DEF-1104`'s
  is re-pinned or its row split before the lane strikes anything (Risk 4).
- The four sync scripts (`sync_vendor_cc.py`, `sync_claude_mirrors.py`, `sync_asset_docs.py`,
  `sync_selfcheck_tests.py`) leave no diff; `tests/test_surface_contract.py` and
  `tests/test_protected_path_contract_parity.py` are green under 4-B;
  `tests/test_ci_guard.py::TestApprovalMarkerRepoPosture` keeps three passing axes on a hook path;
  `tools/cc/ship.py::guard_predicate` still loads and calls the guard.
- `mypy tools/cc/hooks/` and `ruff check .` clean; `python3 scripts/proof_tier.py --base origin/main`
  names the tier (expect `full`: hooks and engine change) and it is green, under `nohup` with
  `EXIT=$?` appended, never `-n auto` on an 8 GB box.

## Risks — what this pack most likely got wrong

1. **A Walk step green on restored state.** The helper is re-marked before the uninstall and the
   clone is made after the skew; move either and an assertion passes for the wrong reason.
2. **The import guard swallows a judgment error.** `_import_siblings` wraps the imports only;
   `main`'s crash guard owns the judgment. If the two overlap, a judgment crash reads as a helper
   skew and names the wrong remedy.
3. **Fail-closed locks the adopter out of the repair.** The helper is repaired from a terminal,
   which the deny says, and 2-B's line at upgrade time is the earlier exit. If the operator rejects
   the lockout (Decision 3), the deny hooks degrade instead and the contract asserts exit 0 with the
   judgment still made.
4. **`DEF-1104`'s probe flips on the half this pack lands.** It counts ordered compares on
   `deployed_version` in `cmd_upgrade`; 3-C adds one while the digest clause stays open. Re-pin it
   to the digest (or split the row) before any strike, or a half-closed row reads `STRIKE_CANDIDATE`.
5. **`DEC-39` (b)'s posture read.** `is_protected` is a pure path predicate with two out-of-tree
   consumers (`tools/cc/ship.py::guard_predicate` and the parity test), so the posture is module
   state, adopter by default, set once by `run()`. A consumer that never calls `run()` gets the
   adopter answer, which is the tighter one.
6. **The §C68 helper's gitignore read.** A path ignored on an adopter tree never reaches a commit,
   so it must not trigger the lines; reuse `cmd_init`'s `check-ignore --no-index` reader, and stay
   silent on a tree with no git.
7. **Two writers on one tree.** 1-A builds its own module-scoped tree and never takes the
   session-scoped `adopter_tree` fixture (`memory/one-writer-per-shared-state.md`); 2-D's class
   builds its own under `tmp_path` for the same reason.
8. **Seams with the sibling packs** (one line per shared production symbol this pack edits, with
   the landing order):
   - `tools/cc/hooks/plan_guard.py`: `TP-472` 1-B edits `_check_rel`, `_load_adopter_exempt_prefixes`
     and the hint constants; 2-A here wraps the import block at the file's top. Different regions;
     `TP-472` lands first and 2-A rebases (its hunk is the smaller).
   - `tools/cc/hooks/_reinject.py`: `TP-470` 1-A gives `ReinjectRule` a `scope` and derives two
     tuples from `REINJECTS`; 2-A here makes `_is_tracked`'s `spawn_timeout` read degrade.
     Different regions; `TP-470` lands first.
   - `tools/cc/hooks/session_start.py`: **not edited here.** Its exit 1 on the skewed tree
     (`import _reinject`) is cured through `_reinject.py`'s degrade, and the Walk only launches it.
     `TP-470` 1-B and `TP-473` 1-E edit it; this pack adds no order constraint beyond the vendor
     sync each lane runs.
   - `espalier/doctor.py`: `TP-466b` 1-D adds `_probe_recall_corpus` and an info line in
     `run_doctor_check`; `TP-471` 2-A edits `_check_stop_gate_posture`; 2-D here adds
     `_check_wired_hooks_start` and its call. Three additive hunks; any order, and a hand resolve
     keeps all three calls.
   - `espalier/cli.py::_ONBOARDING_ROWS`: `TP-471` 2-A rewrites ONB-3's text (a different row);
     `TP-472` 2-B makes `init` write the `espalier.toml` ONB-6's code reads, so `TP-472` 2-B lands
     before 5-A here and 5-A's ONB-6 rule is written against a file that always exists (edited iff
     an uncommented key, the reading `TP-472` says the probe already needs).
9. **The body-lane order is a four-pack chain.** 3-B's four agent bodies sit third (`TP-470` 3-A,
   `TP-471` 3-A to 3-C, this 3-B, `TP-473` 1-B); a lane that lands out of order reds `TP-473`'s
   audience gate or re-edits a sentence `TP-471` just wrote. The sync is `sync_claude_mirrors.py`
   (`espalier/mirror_registry.py` names it for `.claude/agents/`).
10. **The new module's classification.** Its stem carries `hook`, so without the `_MARKER_RULES`
    row `TestSecurityMarkerCoverage` reds, and without the `# slow-exempt:` line the subprocess
    contract reds; both are one-line edits (the conftest claim was released 2026-10-07; re-check
    the mail channel at pre-flight, since a released claim does not prove the file free -- read
    `git diff --stat origin/main...origin/<lane> -- tests/conftest.py` for every open lane).
11. **The doctor check reads imports, not starts.** A hook that imports clean and dies at `main`
    passes 2-D and fails only the Walk's start class; and `import_module` in the child's source is
    a keyword the filed `DEF-1188` probe reads, so that probe flips on text -- the behavioural
    re-pin in Reach is the honest oracle.
12. **The four-lane split and the Walk's reds.** 1-A holds every class and three lanes own the
    fixes; without the strict-xfail bridge in Decision 6 the Walk lane cannot land green on `main`
    or loosens a class to do so. A lane that fixes a row without deleting its xfail mark reds
    (`strict=True`) -- that is the bridge's point.

## Decisions (questions for the operator, each with a recommended default)

1. **`DEC-39`: (a) keep the ruling and disclose at install, (b) make the `.github/workflows/` prefix
   self-host-only in `ci_guard` with the two harness files exact-match protected everywhere, (c)
   adopter opt-in by config.** Recommended **(b)**: the local layer already made this call
   (`tools/cc/hooks/_hook_utils.py::harness_protected_prefixes`), the status quo misnames the adopter's
   file in its deny, and the trade (an agent can weaken an adopter's other workflows without a
   marker, under the adopter's own branch protection) is the one the local layer accepted. (c)
   waits on unknown-key warnings. Under (a), 4-B shrinks to the deny text.
2. **The TP-468 seam.** This pack and 2-D edit the same fixture. Recommended: this pack absorbs
   2-D's Walk half (the stack parameter and the bare `upgrade` verbs are in 1-A) and TP-468's
   session-and-stack lane drops 2-D, keeping 2-C. Alternative: sequence this pack after 2-D and
   rebase 1-A onto its fixture.
3. **Deny or degrade on a helper skew in the deny hooks.** Recommended: deny, with 2-B's line at
   upgrade time as the earlier exit; a degrade that still judges is possible only for names the
   judgment does not need, which the contract measures.
4. **Refuse or warn when the deployed stamp is newer (3-C).** Recommended: refuse and name the files;
   `--execute` on a downgrade is the audit's observed rollback.
5. **Refuse or warn on `--execute` without the saved plan (3-A).** Recommended: refuse with exit 2
   and the `init .` redirect; the row measured that `init .` leaves `git diff` empty on the clone.
6. **Lane split.** Recommended four lanes, each with its own Task 0 slice and red-team: **Walk and
   guard** (Task 0, 1-A, 2-A, 2-B, 2-C, 2-D); **upgrade** (3-A to 3-D); **CI** (4-A, 4-B);
   **onboarding** (5-A). The hook and `ci_guard` lanes carry the approval marker in the pull-request
   title (the ship driver binds it). **The bridge:** 1-A lands whole in the first lane; each class
   whose fix is another lane's carries `pytest.mark.xfail(strict=True, raises=AssertionError,
   reason="DEF-NNNN: <the row's claim>")` naming its row (`TP-468` Decision 5's shape), so the Walk
   lane is green on `main` with the reds recorded, and each later lane deletes the marks it flips
   -- a fix that lands without deleting its mark reds under `strict`. The alternative, each lane
   adding its own classes, splits the sequence the pack exists to prove; not recommended.

## Files touched

- **New:** `tests/test_hooks_start_on_a_kept_helper.py`; this pack.
- **Modified:** `tests/test_adopter_lifecycle_diagnostics.py`; `tests/conftest.py` (one
  `_MARKER_RULES` security-tuple row for `test_hooks_start_on_a_kept_helper`; the other machine's
  claim on it was released 2026-10-07; `_SLOW_FILES` untouched); `tools/cc/hooks/write_guard.py`,
  `plan_guard.py`, `config_guard.py`, `_speedbump.py`, `_reinject.py` and their `espalier/_vendor/cc/`
  mirrors (by the sync); `tools/cc/ci_guard.py` and its mirror (4-B); `espalier/cli.py`,
  `espalier/fuse.py`, `espalier/fusion_manifest.py`, `espalier/managed_paths.py`, `espalier/doctor.py`,
  `espalier/models.py`, `espalier/surface_contract.py`; the four agent bodies under `.claude/agents/`
  and their two mirrors (by the sync); `docs/INSTALL-CI.md` and `espalier/assets/docs/INSTALL-CI.md`
  (by the sync); `docs/QUICKSTART.md`; `tests/test_ci_guard.py`, `tests/test_cli_deploy.py`,
  `tests/test_doctor.py`, `tests/test_surface_contract.py`, `tests/test_protected_path_contract_parity.py`,
  and the readers whose output assertions move (`tests/test_cli_commands.py`, `tests/test_init.py`,
  `tests/test_init_upgrade_paths.py`, `tests/test_managed_paths.py`, `tests/test_models.py`,
  `tests/test_onboarding_nudge.py`, `tests/test_fuse.py`); `espalier/_vendor/selfcheck_tests/test_models.py`
  (by `python3 scripts/sync_selfcheck_tests.py`; `tests/test_models.py` is in its `BYTE_MIRRORED`);
  `task-packs/FORWARD_LEDGER.md`, `task-packs/LEDGER_PROBES.json` (the strikes and the `DEF-1104` re-pin).
- **Unmodified on purpose:** `tests/_adopter_tree.py` and `tests/_stack_trees.py` (the Walk adds its two files on
  top of the row, so no row changes a byte); `espalier/cli.py::_deploy_managed_py` (keeping an
  unmarked file is the documented contract; the skew is named, not prevented); `tools/cc/ship.py`
  (its `guard_predicate` keeps working because `is_protected` keeps its shape);
  `tools/cc/hooks/_protected_zones.py` (its `PROTECTED_PREFIXES` is the local layer's homonym);
  `espalier/assets/github/workflows/harness-guard.yml` (`DEF-945`'s).

**Authoring scope-check** (2026-10-07 at the fold, `python3 -m espalier scope-check` on this file):
exit 2, 41 files in scope, 34 symbols, 156 gap files. The gap is prose and records (`CONTRIBUTING.md`,
`WALK*.md`, `WINDOWS_FUSE_NOTES.md`, `memory/`, `docs/`, `docs/sharp-edges/`, `cc/` -- blueprints and
the live `cc/execution_plan.json` -- `bench/corpus/`, the other packs under `task-packs/` with their
`Done/` and `Deferred/` archives, and the asset mirror `espalier/assets/docs/FAILURE_MODES.md`), the
`PROTECTED_PREFIXES` homonym's one reader outside the hooks (`bench/powershell_guard_rehearsal.py`),
comments naming `cmd_init`, `cmd_install_ci` or `run_doctor_check` in `espalier/cleanup.py`,
`espalier/managed_inventory.py`, `espalier/analyze.py`, `espalier/settings_profiles.py`,
`espalier/harness_config.py`, `espalier/reflection.py`, `espalier/_integrity_bridge.py` and
`scripts/`, the selfcheck test mirror (`espalier/_vendor/selfcheck_tests/`, written by its sync), and
`tools/cc/ship.py`, which this pack keeps working. Accept that gap with this reason only if the
categories are the same at execution (the deriving command is the one above; the count will move).

## Sub-task ordering

0. **Pre-flight**, the four gates in `memory/task-packs.md`: `code-reviewer` with
   `tools/cc/pack_artifact_checklist.md`; `python3 -m espalier scope-check <this pack>`;
   `python3 tools/cc/sister_site_probe.py --json`; `python3 -m espalier surface-impact <this pack>`.
   Then `python3 tools/cc/execution_plan.py create`, and the claims pre-flight on the mail channel
   for `tools/cc/hooks/` and `tools/cc/ci_guard.py`.
1. **Task 0.** Checkpoint: every Motivation-table value re-derived and recorded. Stop on a refutation.
2. **1-A** red on `main`. Checkpoint: `pytest -q -m 'not heavy_e2e' tests/test_adopter_lifecycle_diagnostics.py`
   reds exactly on the new classes; then the classes the upgrade, CI and onboarding lanes own take
   their strict xfail marks (Decision 6) and the module is green with those xfails counted.
3. **2-A** (the module, its `# slow-exempt:` line, the `_MARKER_RULES` row), **2-B**, **2-C**, **2-D**;
   the vendor sync. Checkpoint: the guard, skew, uninstall and doctor classes green; the start
   contract green;
   `pytest -q -m 'not heavy_e2e' tests/test_write_guard.py tests/test_doctor.py tests/test_forced_copy_parity.py tests/test_ci_guard.py tests/test_documented_claims.py tests/test_test_suite_contract.py`.
4. **3-A** to **3-D**; the mirror sync (3-B after `TP-470` 3-A and `TP-471` 3-A to 3-C, before
   `TP-473` 1-B) and the selfcheck-tests sync. Checkpoint: the upgrade classes green;
   `pytest -q -m 'not heavy_e2e' tests/test_init_upgrade_paths.py tests/test_cli_deploy.py tests/test_models.py`.
5. **4-A**, **4-B**; the two syncs. Checkpoint: the two CI classes green;
   `pytest -q -m 'not heavy_e2e' tests/test_ci_guard.py tests/test_surface_contract.py tests/test_protected_path_contract_parity.py tests/test_fuse.py tests/test_ship_driver.py`.
6. **5-A.** Checkpoint: the ONB-1 class and the truth table green; the three §C64 probes flipped.
7. **6-A** per lane, one fix batch each.
8. The tier the diff earns, the probe re-pins and strikes, the commit, `/handoff`, which ships.

## Estimated effort

| Step | Estimate |
|---|---|
| Task 0 | 2 h (the drive exists; re-run and record) |
| 1-A | half a day |
| 2-A and the start contract | half a day |
| 2-B, 2-C | 3 h |
| 2-D and its class | 3 h |
| 3-A to 3-D | half a day |
| 4-A | 3 h |
| 4-B | 3 h, plus the parity and posture pins |
| 5-A | 2 h |
| Red-team and fix batches (four lanes) | 1 day |

About four and a half days of lane time. Pack budgets here ran about 2.7 times over on the one pack measured;
read this as a floor.

## Landing

- State: DRAFT
- Commits:
- Suite:
- Earn-the-red: <each 1-A class red on `main` with the Task 0 value, then green; the start contract red on the bare imports; the doctor class red with the check's call dropped>
- Red-team: <lanes run, verdicts, what they changed>
- Reach: <members closed / deferred, per the table above>
- Date:
