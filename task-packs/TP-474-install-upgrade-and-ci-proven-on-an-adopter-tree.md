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
- Gate: the six questions under *Decisions* were **decided 2026-10-10 at their recommended
  defaults** (the operator, on the dispatcher's read). Decision 6's first lane, Walk and
  guard, runs as `lane/walk-and-guard` from the Air; its pre-flight gates are under *Landing*.
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
   re-run `init`, `merge-settings` on a tracked settings file and `espalier/fuse.py`'s epilogue
   (`espalier/fusion_manifest.py`'s re-point step and fuse's unwired-host warning too);
   `docs/INSTALL-CI.md` sections 1 and 2 and `docs/QUICKSTART.md`'s CI, upgrade and fusion sections
   carry the clause (lane 4's amendment, 2026-10-11).
11. **4-B** `DEC-39` as decided (Decision 1): under (b), `tools/cc/ci_guard.py` applies the
    `.github/workflows/` prefix only on the self-host repository, `espalier/surface_contract.py`
    moves in step, and the pins in `tests/test_ci_guard.py` (the posture class and
    `TestDependabotActionBumpAllowance`), `tests/test_surface_contract.py`,
    `tests/test_protected_path_contract_parity.py` and `tests/test_ship_driver.py` pin the posture
    instead of the prefix; the generated `ci-gated-paths` block is re-rendered in its carriers
    (`CONTRIBUTING.md`, `.claude/agents/code-reviewer.md` and its mirrors); `docs/INSTALL-CI.md`
    section 3 is reworded, its Dependabot paragraph included.
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
  marked body is upgrade mechanics and the walk pins it, and its 1-C render step waited on this
  pack's 3-A, the clone's re-render defect on the same seam (landed in lane 2, 2026-10-10); this
  pack strips no maintainer text from a body, which stays `TP-473`'s.
- **TP-468's 2-D and 2-C.** 2-D's stack parametrisation of the Walk and its bare `upgrade` verbs
  are the fixture this pack extends; 2-C's `upgrade` step asserts the state the next SessionStart
  reads, a different thing. Decision 2 picks the seam; nothing here re-plans 2-C.
- **A fusion walk.** The Walk does not run `fuse`. The §C68 helper's call site in
  `espalier/fuse.py::cmd_fuse` landed in 4-A (lane 4, 2026-10-11) because a class is never patched
  one instance at a time (root `CLAUDE.md` Core Rule 12); its proof is the fuse row's own probe and
  `tests/test_fuse.py`, not the Walk.
- **`DEF-1077`'s overlay and relief roster.** An unmanaged `.claude/agents/<name>.local.md` the body
  reads first is a feature with its own design; `tools/cc/hooks/_hook_utils.py::RELIEF_FLAGS` is a
  Stop-gate design. 3-B lands the row's "short term" clause only.
- **`DEF-1104`'s build-identity digest.** Ordering two version strings is stdlib work (3-C); a
  digest stamped beside the version is a packaging decision. Risk 4 names the probe hazard.
- **`DEF-1057`'s init and doctor WARN on tracked `cc/` and `tools/cc/` paths.** The Walk's tree has
  none before `init`. Its marker-predicate half is 2-C's; the WARN half stays with the row.
- **`DEF-945`** (trigger choice, `fuse --no-ci`): a working tree cannot see the repository's Actions
  policy, so the Walk cannot prove the symptom; the fix is a CLI option set with its own fork.
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
  skewed tree, `write_guard.py` emits a deny (`DEF-1176`). *Amended 2026-10-10 at build: the
  measured skew (the two budget names) is JUDGED, since those names degrade in `_speedbump.py`
  and `_reinject.py` (Decision 3's carve-out); the Walk adds a deep skew, the helper also
  lacking `payload_cwd` and `hook_cwd` (two newer names a September copy predates), and asserts
  the refusal naming the repair there, with `doctor` naming the dead hooks on the same state.*
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
import json
import sys
from pathlib import Path


def _refuse_helper_skew(exc: BaseException) -> None:
    """A sibling import failed under __main__: the tree's helper predates its
    siblings (an upgrade kept an unmarked _hook_utils.py). The protocol reads
    an uncaught exit 1 as non-blocking, so the failure becomes the structured
    deny instead of a traceback. Standard library and literals only: any
    sibling, _denial_reasons and _integrity included, may be the one that
    failed. The record is best-effort; stderr stays empty (channel XOR)."""
    reason = (
        "write_guard cannot start: a sibling helper import failed "
        f"({type(exc).__name__}: {exc}). The tree's tools/cc/hooks/_hook_utils.py "
        "predates its siblings (an upgrade kept it as yours). From a terminal, restore "
        "its managed marker and run: espalier upgrade --execute . -- every tool call is "
        "refused until then."
    )
    try:
        import _integrity  # noqa: E402 -- may be the module that failed
        _integrity.append_audit(Path.cwd(), {
            "event_type": "pretooluse_blocked_internal_error",
            "details": {"hook": "write_guard", "error": type(exc).__name__,
                        "skew": "sibling import"},
        })
    except Exception:  # noqa: BLE001, S110 -- no record is not a reason to let the call through
        pass
    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason}}) + "\n")
    raise SystemExit(0)


sys.path.insert(0, str(Path(__file__).parent))
import _hook_utils  # noqa: E402 -- the floor: a helper that cannot import at all is not this pack's skew
try:
    from _hook_utils import os_error_text  # noqa: E402
    import _integrity  # noqa: E402
    import _maintenance_mode  # noqa: E402
    import _bash_patterns  # noqa: E402
    import _denial_reasons  # noqa: E402
    import _protected_zones  # noqa: E402
    import _speedbump  # noqa: E402
    import _reinject  # noqa: E402
except Exception as _skew:  # noqa: BLE001 -- a kept helper that predates its siblings
    if __name__ != "__main__":
        raise  # an in-process importer (the tests) sees the real error
    _refuse_helper_skew(_skew)
```

The module-top `from _hook_utils import os_error_text` (`write_guard.py`, `plan_guard.py` and
`config_guard.py` each carry one; `config_guard.py` also `from _json_safe import decode_bom`) moves
inside the `try`, or the per-name contract's `os_error_text` cell exits 1 by construction.
*Amended 2026-10-10 at execution:* the drafted `_import_siblings()` function with `global`
re-exports is replaced by the module-top `try`/`except` above. win's 2026-10-08 review measured
why: a function-scope wrap unbinds the module globals for in-process importers such as the tests,
and the function needed some forty module-level re-exports. The `try` keeps the imports at module
top, so every name stays bound where it was; the handler runs only under `__main__`, so an
importer sees the real `ImportError`. The handler, `_refuse_helper_skew`, is defined above the
`try` from the standard library and literals alone: it writes a best-effort
`pretooluse_blocked_internal_error` record when `_integrity` imports (it may be the module that
failed; then no record, and nothing on stderr), prints the `deny` shape this file already emits
(`hookSpecificOutput.permissionDecision: deny`) naming the failing module or name as
`type(exc).__name__: exc` (never through `os_error_text`, which may be the name missing) and the
remedy (restore the helper's marker and run `espalier upgrade --execute` from a terminal), then
exits 0; `main` and its crash guard run only after a clean import, so the guard's own
`os_error_text` call is bound. `plan_guard.py` and `config_guard.py` carry the same `try` around
their own imports (`_integrity`, `_maintenance_mode`, `_denial_reasons`, the name imports, and
`config_guard.py`'s `from _json_safe import decode_bom`), each printing the deny shape its event
already uses (`config_guard.py`'s is `{"decision": "block", "reason": ...}`). The record type
is the crash guard's, with `details.skew` naming the cause, so no roster or documented table
changes; the bench parser's deny-marker tuple gains the phrase. In `_speedbump.py` and
`_reinject.py`, `spawn_timeout` and
`STATE_WRITE_LOCK` are read as attributes with the degrade
`tools/cc/hooks/_integrity.py::_STATE_WRITE_LOCK` already uses. Then `python3 scripts/sync_vendor_cc.py`.
*Built 2026-10-10:* the guard also reads, once, every helper name the hook's import graph takes
(24 for `write_guard`, 7 for `plan_guard`, 5 for `config_guard`), from a per-hook roster the
contract pins to the AST derivation -- a function-level import failed at call time inside the
crash guard with the re-issue remedy (measured on `config_guard`'s `read_stdin_safely`), so
import-time coverage of the whole graph is the honest net. The handler lives once in
`_denial_reasons.py` as `refuse_on_helper_skew` (it imports no helper name and every upgrade
regenerates it): three copies would have been a sister-site clique with no opt-out slot left
(ceiling 22, live 22). The bench parser's deny-marker tuple gained the phrase.
*Red-teamed 2026-10-10:* both reviews found `stop_gate.py` left with the same shape (a blocking
hook excluded by event name; reproduced: `del STATE_DIR` and the Stop hook exits 1, the four gates
run nothing), and the failure-mode review found the roster covering one of two spellings -- a
`_hook_utils.<name>` read in a function body, the dominant spelling, failed at call time inside the
crash guard with the re-issue remedy. So the guard is on the four blocking hooks the engine's own
roster names (`GOVERNANCE_BLOCKING_HOOKS`), each roster is every helper name the graph reads
anywhere (write_guard 39, plan_guard 27, config_guard 12, stop_gate 25 -- the contract pins each),
and the degraded set is pinned as a union of five (the two budget names, the deadline setter and the
lock in `write_guard`'s own budget paths, now read through the degraded forms -- its `finally` reset
of the deadline used to raise into the crash guard on a pre-budget helper -- and two launcher names
in `_integrity`). `doctor`'s start probe lost its WARN: a batch that does not answer re-probes each
hook alone and a hook that still does not answer within the budget is a FAIL by name, since it could
not run under Claude Code's wired timeout either.

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

**Mutation:** revert the `try`/`except` to the bare imports; the `write_guard` cells red with exit 1
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
`del payload_cwd, hook_cwd` (*amended 2026-10-10:* the two budget names degrade after 2-A, so
the skew that still kills a hook at import is a floor name) reads `fail` with lines naming `write_guard.py` and
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
*Built 2026-10-10 (lane 2, win-2):* the refusal sits before the version arms, not in the
same-version arm alone (the 0-A review: the plan was loaded only there, and an older-stamped clone
re-renders the same two docs from the same missing table), so every `--execute` that would reach
the deploy refuses alike, on stderr, before any write. The dry run keeps reporting what differs,
sets `cc/COMMANDS.md` and `cc/LIVE_SURFACE.md` aside as not compared (their "renders differently"
was the empty table talking, the row's own second sentence) and ends on the redirect instead of
previewing stages the execute refuses; it exits 0. The 3-C refusal is asked first, so a lagging
engine is never sent to `init`. The refutation re-measured: `init .` on a plain clone and on the
Walk-shaped skewed clone left `git status` empty and `doctor` 0. *Red-teamed:* where a
`.claude/settings.json` is already present, plain `init` leaves it unmerged, so the redirect names
`init . --wire-hooks` there (`_plan_restore_command`; `doctor .` on the self-host tree), and every
plan-less line names that command in place of `--execute`.

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
names the body. *Built 2026-10-10 (lane 2):* the sentence rides the naming line after the list
(`_MARKED_EDIT_SENTENCE`), since the Walk reads the lines that name the body and the existing
`re-deployed 1 file: <path>` pins keep their prefix; the version-bump dry run lists through
`_surface_drift_lines` over the deploy's own preview, on the arm that has not named the files
(`kept_named`), so the two previews read alike; the four bodies keep `Edit this file directly`
and gain the marker sentence beside it.

### 3-C Order the stamps — `cmd_upgrade`, `cmd_init`

A stdlib compare of the deployed stamp against `__version__` (split on `.`, numeric where it
parses, a pre-release tag below its release); when the deployed side is newer, both verbs say so
and refuse the managed overwrite, naming the files they would have rewritten. **Mutation:** the
`99.0.0` dry run proceeds. **Refutation:** two builds of one pre-release string still compare equal;
that is `DEF-1104`'s digest half, scoped out. *Built 2026-10-10 (lane 2):* "split on `.`" cannot
read `0.8.0b2` (its third part is `0b2`), so the key is a regex, `X.Y.Z[aN|bN|rcN]`, `a < b < rc`
below the release, and any other shape never refuses (`_version_key`, `_deployed_is_newer`). One
helper, `_refuse_newer_deployment`, serves both verbs in both modes: the version line on stdout
says newer, the refusal and every file a deploy would roll back on stderr, exit 2, before any
write; `cmd_init` reads the stamp before its dry-run branch. Risk 4 measured: the filed probe read
`2` against its open `0` once the call landed, so it is re-pinned to the build identity first.
*Red-teamed:* `install-ci` (the merge gate) and `fingerprint` (the plan readers and runner bodies)
wrote over a newer deployment too; both refuse the same way, and the refusal names the deliberate
rollback (delete the stamp line). The row keeps the explicit override open beside the digest.

### 3-D Filter the saved report by declared fields — `espalier/models.py::RepoFingerprint.from_dict`

`{k: v for k, v in data.items() if k in {f.name for f in fields(cls)}}` before the constructor, the
nested constructors the same way; `cmd_upgrade`'s message says "saved by an older release,
re-baselined on --execute" when the file parsed but carried undeclared keys. **Mutation:** the
retired-key step prints `unreadable`. *Built 2026-10-10 (lane 2):* `RepoFingerprint.undeclared_keys`
names what `from_dict` drops (nested as `large_files[].<key>`); on the same-version arm the line
is drift ("saved by an older release (or another build of this one)"), so `--execute` rewrites the
file once and the next run is clean -- a line that said "re-baselined on --execute" on a tree the
arm calls current would be a promise nothing keeps. The Walk's assertion is the phrase, not the
word (`"older"` also matches `folder`).

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
probe prints `True False` again. **Refutation:** on the self-host tree the helper omits the push
form and keeps the pull-request form, which every PR event still needs there
(`tests/test_ci_guard.py::TestApprovalMarkerRepoPosture` is the posture pin).
*Amended 2026-10-11 (lane 4, win-2, from the 0-A review; operator-approved):* the writers are the
five §C68's unit of work names, not four: `cmd_merge_settings` on a repository that tracks
`.claude/settings.json` joins `install-ci`, `upgrade --execute`, a re-run `init` and `fuse`, and
fuse's unwired-host "Before you push" warning (`espalier/fuse.py`, the `merge-settings` step it
prescribes) and the Quickstart's fusion paragraph carry the clause beside the re-point step (Core
Rule 12: sibling sites ride the lane). The git read is index-aware `check-ignore` (a tracked path is
never reported ignored, so a tracked settings file counts), not `_git_covered_entries`
(root-`.gitignore` patterns under `--no-index`, blind to the index). *Built:* as
`espalier/cli.py::_git_ignored`, one batched `check-ignore --stdin -z` per writer, which answers
None where git cannot (no `.git` of the tree's own, exit 128, a timeout), so the helper is silent
on a tree with no git (Risk 6); `_git_hides` answers False ("not ignored") there and would have
emitted the lines. The unit class carries the no-git arms. The gated
read is `is_protected_from_ci(rel, self_host=surface_contract.is_self_host_repo(repo_root))` (4-B).
The class is pinned by one test parametrized over the five writers with the two negative arms the
§C68 text names (no guard on disk; every gated path written is ignored), tracked-settings arms where
`merge-settings` and `upgrade` must name the marker and default arms where they must not. The Walk
gains a plain (unbridged) assertion that `upgrade --execute` names the marker, the `DEF-1052`
witness the bridge never carried. The clause is 7-bit ASCII and any command it names takes the
interpreter-aware form (`tests/test_no_bare_espalier_hints.py`, `tests/test_portability_contract.py`
read `INSTALL_CI_INSTRUCTIONS` and `FINISH_UP_STEPS`). `DEF-1052` and `DEF-1051` strike on their
probes; `DEF-1050` on its probe and the Walk.

### 4-B `DEC-39` — `tools/cc/ci_guard.py` (under (b))

`is_protected` keeps its one-argument call (`tools/cc/ship.py::guard_predicate` loads it by path
and calls `is_protected(rel)`); the posture reaches it as a keyword argument, never module state
(the amendment below; the authored "module value, adopter by default" is withdrawn); the
`.github/workflows/` prefix applies only under the self-host posture; `PROTECTED_FILES` keeps
`harness-guard.yml` and `ci_guard.py` everywhere.
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
*Amended 2026-10-11 (lane 4, win-2, from the 0-A review; operator-approved):* no module posture.
Under (b) the adopter answer is the LOOSER one for `is_protected` (the workflows prefix drops out),
so a module value defaulting to adopter would have `tools/cc/ship.py::guard_predicate` -- which
loads the guard by path and calls `is_protected(rel)` without `run()` -- stop binding the marker
for a workflow change on this repository, and the required check reds. Instead
`is_protected(rel_path, self_host=True)`: the one-argument call keeps working and gets the tight
answer (on an adopter, `/ship` over-binds the marker for their own workflow change; a marker nobody
needed costs nothing, `guard_predicate`'s own rule), and `run()` passes
`_ci_is_self_host_repo(root)` on every call, so `bench/run_benchmark.py`'s in-process runs over
several temp repositories share no state. `SELF_HOST_PROTECTED_PREFIXES = (".github/workflows/",)`
names the posture-scoped subset; `PROTECTED_PREFIXES` keeps its full tuple (the
`get_protected_ci_prefixes` equality pin, `tests/test_protected_path_contract_parity.py`).
`is_protected_from_ci(rel_path, *, self_host=True)` mirrors it, with the parity pins asserting both
postures. The generated `ci-gated-paths` block (`render_ci_gated_block` in
`tests/test_protected_path_contract_parity.py`, derived from `PROTECTED_PREFIXES` with
`is_protected` as its runtime-only oracle) renders the self-host-only row with its scope, since
`.claude/agents/code-reviewer.md` ships it to adopters, where "every path under it" would be false.
The renderer has no write mode (its failure text says re-render and paste), and its prefix row text
is fixed, so `render_ci_gated_block` gains a branch for the self-host-only rows; its output is
pasted into `CONTRIBUTING.md` and the agent body, then `sync_claude_mirrors.py`. That edit beside a
changed carrier arms `tests/test_verify_pins.py`'s live controls (a clone and two pytest runs),
which the checkpoint runs and expects active, not skipped. `_RUNTIME_ONLY_REPRESENTATIVES` and the
over-claim twins read the default posture and stay green. The two subset constants
(`ci_guard.SELF_HOST_PROTECTED_PREFIXES`, `surface_contract._PROTECTED_CI_SELF_HOST_PREFIXES`) get
an equality pin beside the full-tuple one. `docs/INSTALL-CI.md` section 3 keeps the bare
`` `.github/workflows/` `` token its under-claim arm reads, scopes that bullet ("every workflow") to
the Espalier-Harness source repository, and rewords the Dependabot paragraph, which on an adopter
now concerns `harness-guard.yml` alone; then `sync_asset_docs.py`.
`tests/test_ci_guard.py::TestDependabotActionBumpAllowance` commits `.github/workflows/test.yml`
into an adopter-shaped `fresh_repo`, so it moves to `_make_self_host`; one adopter case on
`harness-guard.yml` (exact-file, gated everywhere) keeps the human-PR deny direction there.
`_touch_protected`'s move to a hook path also keeps the posture class's four-signal and encoding
cases on a gated path. `tests/test_ship_driver.py` gains a real-guard source case (its fixtures
write the guard's source through `_write_guard`): the real `ci_guard.py` binds the marker for a
`.github/workflows/` path through the one-argument call. `DEC-39` has no probe: it closes by its
ledger text.

### 5-A §C64 — `espalier/cli.py::_ONBOARDING_ROWS`

ONB-1's code: read `cc/GOAL.md` through a BOM-aware decode (`tools/cc/_json_safe.py::decode_bom`'s
rule); while the file exists and is not blank, open iff the `## Goal` (or `## Goals`) body, to the
next `## ` heading, CRLF, CR or LF, or the whole file where it has no such heading, is empty or
carries the placeholder (`(not set` as a word, so a goal saying "not settled" is a goal), whatever the
key; once the file is gone or blank (the banner shows nothing for either), open iff the key is unset;
a decode error or a NUL keeps it open. Each file is read the way its harness reader reads it, which
is not one rule: `espalier.toml` through the harness's own parser (`tomllib`, else `tomli`, the
order `tools/cc/hooks/_hook_utils.py::_toml_parser` binds), so a file that does not decode or parse
-- a leading byte-order mark, a cp1252 byte, a syntax error -- reads as no key at all, as
`espalier/config.py::load_config` and `_hook_utils.read_toml_table` read it (the `DEF-1034` probe's
UTF-16 `espalier.toml` leaves ONB-6 open), and ONB-6 stays open until the key holds a list, as the
plan gate requires; where the probe's interpreter has neither parser, the rows read the key as the
hooks' own no-parser arm (`_hook_utils._regex_extract_string_list`) does. The ONB-7 stubs read as
strict UTF-8, an undecodable stub counting as edited, as `espalier/cli.py::_seed_redeploy_decision`
and doctor's `_needs_grounding` read it, with one leading mark and CRLF line ends not edits, as
`espalier/managed_markers.py::seed_is_untouched` reads them (the redeploy decision reads a mark as an
edit; the row follows doctor). The truth table in
`tests/test_cli_deploy.py::TestOnboardingProbesDoNotWalk` gains the goal-written, the
opted-out-and-kept (open), the opted-out-and-deleted (closed), the blank, the headingless, the heading
and the encoding states, and a second test holds every verdict against those readers, so a reader that
changes reds beside the probe; its key-under-a-table ONB-1 leg deletes the file, as the `DEF-1033`
row says it must. The lane deletes the `_bridge("DEF-1032", ...)` mark on
`tests/test_adopter_lifecycle_diagnostics.py::TestOnbOneReadsTheGoal` (Decision 6). The fix reaches
a ledger `init` seeds from here on; a ledger that already stores the old probes keeps them through
`upgrade`, filed as its own row at the lane's landing. **Mutations:**
each row's probe (`True`, `False`, `True` today) flips on its own edit: `DEF-1032` on the section
rule, `DEF-1033` on the file-before-key rule, `DEF-1034` on the decode rules; rewording the second
placeholder flips none. **Refutation:** a GOAL.md seeded before the fix still carries the old second
placeholder; the section rule reads it right, a placeholder rewrite does not.

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
- `tests/test_ci_guard.py::TestDependabotActionBumpAllowance` (runs on the self-host fixture; lane 4)
- `espalier/cli.py::cmd_merge_settings` (the marker lines on a tracked settings file; lane 4)
- `espalier/cli.py::cmd_clean_generated` (the marker lines on stderr for the uninstall commit; lane 4, the red-team batch)
- `espalier/cli.py::cmd_integrity` (`refresh` names the marker for a tracked manifest; lane 4, the red-team batch)
- `tests/test_protected_path_contract_parity.py::render_ci_gated_block` (the self-host-only row's scope; lane 4)
- `tests/test_cli_deploy.py::TestOnboardingProbesDoNotWalk` (the truth table)
- `tests/test_doctor.py::TestDoctorUninstalledTree` (an install-ci tree with an adopter file)

### Renamed

- (none -- every symbol keeps its name.)

### Added-paths

- `tools/cc/hooks/write_guard.py::_refuse_helper_skew` *(amended 2026-10-10: the module-top
  `try`/`except` and its handler replace the drafted `_import_siblings`)*
- `tools/cc/hooks/plan_guard.py::_refuse_helper_skew`
- `tools/cc/hooks/config_guard.py::_refuse_helper_skew`
- `espalier/cli.py::_version_key` *(lane 2, with the six below)*
- `espalier/cli.py::_deployed_is_newer`
- `espalier/cli.py::_refuse_newer_deployment`
- `espalier/cli.py::_plan_restore_command`
- `espalier/cli.py::_no_saved_plan_sentence`
- `espalier/cli.py::_retired_fingerprint_keys`
- `espalier/models.py::RepoFingerprint.undeclared_keys`
- `tools/cc/hooks/_speedbump.py::_spawn_timeout`
- `tools/cc/hooks/_speedbump.py::_STATE_WRITE_LOCK`
- `espalier/cli.py::_approval_marker_lines`
- `tools/cc/ci_guard.py::SELF_HOST_PROTECTED_PREFIXES` *(lane 4, the 0-A review)*
- `espalier/surface_contract.py::_PROTECTED_CI_SELF_HOST_PREFIXES` *(lane 4)*
- `tools/cc/ci_guard.py::_ci_base_is_self_host` *(lane 4, the red-team batch)*
- `tools/cc/ci_guard.py::_ci_self_host_posture` *(lane 4, the red-team batch)*
- `espalier/cli.py::_git_ignored` *(lane 4)*
- `espalier/cli.py::_APPROVAL_MARKER` *(lane 4)*
- `espalier/fuse.py::_fusion_marker_lines` *(lane 4)*
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
2. **The import guard swallows a judgment error.** The module-top `try` wraps the imports only;
   `main`'s crash guard owns the judgment. If the two overlap, a judgment crash reads as a helper
   skew and names the wrong remedy.
3. **Fail-closed locks the adopter out of the repair.** The helper is repaired from a terminal,
   which the deny says, and 2-B's line at upgrade time is the earlier exit. If the operator rejects
   the lockout (Decision 3), the deny hooks degrade instead and the contract asserts exit 0 with the
   judgment still made.
4. **`DEF-1104`'s probe flips on the half this pack lands.** It counts ordered compares on
   `deployed_version` in `cmd_upgrade`; 3-C adds one while the digest clause stays open. Re-pin it
   to the digest (or split the row) before any strike, or a half-closed row reads `STRIKE_CANDIDATE`.
5. **`DEC-39` (b)'s posture read.** `is_protected` is a pure path predicate with out-of-tree
   consumers (`tools/cc/ship.py::guard_predicate`, the parity tests, the generated
   `ci-gated-paths` block, `bench/run_benchmark.py`'s in-process `run()`). *Corrected 2026-10-11
   (lane 4, the 0-A review):* the authored text made the posture module state, adopter by default,
   and called the adopter answer the tighter one; under (b) it is the looser one for
   `is_protected`, so a consumer that never calls `run()` would under-protect. The posture is a
   keyword argument defaulting to self-host (the prefix applies), passed by `run()` per call; see
   4-B's amendment.
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
     `TP-472` 2-B makes `init` write the `espalier.toml` ONB-6's code reads; it landed 2026-10-08,
     before 5-A here, so 5-A's ONB-6 rule is written against a file that always exists (edited iff
     an uncommented key, the reading `TP-472` says the probe already needs).
   - `docs/INSTALL-CI.md` and the writers in `espalier/cli.py` (lane 4, added 2026-10-11):
     `TP-473` 1-E edits `_build_claude_md` and `_denial_reasons.py`, no lane-4 hunk; `TP-473` 1-A's
     audience gate counts `docs/INSTALL-CI.md` (23 hits at its census), so lane 4's section 3
     wording addresses the adopter ("the Espalier-Harness source repository", never "self-host" or
     a ledger id). `TP-476` B-1 edits `cmd_init`, `cmd_upgrade` and `cmd_doctor` after this lane on
     the same seat; the marker lines are additive at each summary's tail.
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

**Decided 2026-10-10, all six at their recommended defaults** (the operator, on the
dispatcher's read): 1 is (b); 2, this pack absorbs 2-D's Walk half and `TP-468` 2-D carries
the pointer; 3, deny; 4, refuse and name the files; 5, refuse with exit 2 and the `init .`
redirect; 6, the four lanes with the strict-xfail bridge. The questions stay below as the
record of what was asked.

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
  Lane 4 adds (2026-10-11, the 0-A review): `CONTRIBUTING.md` and `.claude/agents/code-reviewer.md`
  with its two mirrors (the re-rendered `ci-gated-paths` block, then `sync_claude_mirrors.py`);
  `tests/test_ship_driver.py` (a self-host workflow lane binds the marker); `espalier/fuse.py`'s
  unwired-host warning and `cmd_merge_settings` in `espalier/cli.py` (the fifth §C68 writer).
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
   `pytest -q -m 'not heavy_e2e' tests/test_ci_guard.py tests/test_surface_contract.py tests/test_protected_path_contract_parity.py tests/test_fuse.py tests/test_ship_driver.py`,
   plus (lane 4, the 0-A review) `tests/test_vendor_cc_parity.py tests/test_deploy_doc_parity.py
   tests/test_portability_contract.py tests/test_no_bare_espalier_hints.py
   tests/test_documented_claims.py tests/test_package_resource_parity.py tests/test_verify_pins.py`
   (the last with its live controls active).
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
| 4-A | 3 h (re-estimated 2026-10-11: 6 h, five writers and the parametrized class) |
| 4-B | 3 h, plus the parity and posture pins (re-estimated 2026-10-11: 6 h, the generated block, the Dependabot class and `ship`) |
| 5-A | 3-4 h (re-estimated at the lane-5 0-A review: three quote-free one-line probes and the truth table) |
| Red-team and fix batches (four lanes) | 1 day |

About four and a half days of lane time. Pack budgets here ran about 2.7 times over on the one pack measured;
read this as a floor.

## Landing

- State: LANDED
- Lanes: 1 (Walk and guard, the Air, #177) and 2 (upgrade, win-2, #184) landed 2026-10-10/11,
  lane 4 (CI, win-2, #186) and lane 5 (onboarding, win-2, `lane/onboarding`) 2026-10-11.
  Lane 1's record follows, then lane 2's, then lane 4's, then lane 5's.
  The Walk-and-guard lane (Decision 6, lane 1) ran from 2026-10-10 on
  `lane/walk-and-guard` (the Air). Pre-flight at execution: 0-A `code-reviewer` with the
  checklist, APPROVE (0 BLOCK, 2 WARN: the `_import_siblings` rows and block, amended above; the
  AST census figure, live `13 42` against the authored `13 40`); 0-B scope-check exit 2 with the
  gap in the same prose-and-records categories as at authoring, accepted; 0-C sister-site probe
  0 findings (10 suppressed by marker); 0-D surface-impact names the new test module and this
  pack, accepted (no CLI verb is added in this lane).
- Task 0 at execution (2026-10-10, main `0063c2ed`, the Air, Python 3.14.7): the drive re-run as a
  scratch script on `build_adopter_tree(stack="node", tree="git")` plus the adopter's own `ci.yml`,
  `ESPALIER_*` and `CLAUDE*` stripped, 9.7 s wall (9.0 s at authoring), 12 hooks wired by
  `settings.json` (derived from the file). Every refuting result re-derived as the Motivation
  table has it: `install-ci` names `tools/cc/ci_guard.py` and never the marker, the guard lands
  unmarked; the push replay exits 2; the own-`ci.yml` pull-request replay exits 2 naming the
  enforcement layer; ONB-1 `True` with the goal written, `False` with the key set; `doctor` 0 on the
  clean tree; `write_guard.py` on the skewed tree exit 1, `ImportError` at `import _speedbump`
  (`STATE_WRITE_LOCK`), empty stdout; the dry run says `kept as yours: tools/cc/hooks/_hook_utils.py`
  and `absent or unreadable`, the body unnamed; after `--execute` the helper is still unmarked and
  skewed; `doctor` on that tree exit 0, `pass`; the `99.0.0` dry run proceeds; the clone's `doctor`
  0, then 1 after `upgrade --execute` naming `reports/`, `cc/COMMANDS.md` bytes changed; after the
  uninstall `doctor` 1, `missing required managed surface: cc/COMMANDS.md`, next step `init`,
  `ci_guard.py` still on disk. **Beyond the table:** on the skewed tree five wired hooks exit 1,
  not two: `session_start.py`, `post_write_check.py`, `context_reinject_failure.py` and
  `task_router.py` all through `import _reinject` (`from _hook_utils import spawn_timeout`), and
  `write_guard.py` through `_speedbump`; so 2-A's attribute degrade in those two modules cures all
  five on the measured skew, and the three deny hooks' `try` is the class net. `plan_guard.py` on a
  Read no-op exits 0 with nothing on stdout (it judges file writes), where the authoring table said
  it denied; the Walk's start class asserts the channel rule, which both satisfy. No refutation,
  so the lane proceeds to 1-A.
- Commits (the Walk-and-guard lane, `lane/walk-and-guard`, plus the Landing commit): `3083e21f` fix(hooks): reach the seam through the shim; sync and cite the pins; `0bc701d9` fix(hooks): the blocking hooks start or refuse on a kept, older helper.
- Suite: the full tier against `origin/main` on the Air, 2026-10-10 (`python3 scripts/proof_tier.py --run
  --base origin/main`, under nohup): mypy clean, ruff clean, the parallel leg 20531 passed, 79 skipped,
  22 xfailed (the 20 bridged classes and two older) in 21:27, the serial leg 1903 passed in 3:59. The
  first full run showed eight tree-wide contracts the targeted proofs never show (provenance tags in
  shipped code, a bare `espalier` verb in an engine string, a doc sentence read as a partial
  maintenance-mode roster, an event-name emitter outside the contracts table, an exception rendered
  raw, locale-following subprocess runs, two new derived populations unadjudicated); each fixed and
  the tier re-run green on the tree merged with `main` (#173, #175). The release-archive probe over
  the five touched test modules: 432 passed, 20 xfailed before the review batch; re-driven after.
- Earn-the-red (2026-10-10, the Walk-and-guard lane): 1-A red on `main` on exactly this lane's ten
  tests per stack -- `TestEveryWiredHookStarts` (3), `TestUpgradeNamesTheKeptHelperSkew` (2),
  `TestTheWalkRan` and three `TestDoctorAfterUninstall` tests (2-C), `TestDoctorOnTheSkewedTree
  NamesTheDeadHooks` (1) -- with the seven bridged classes `xfail(strict)` and no `XPASS`; each
  went green with its step. The start contract's control disarms the guard on a copy and sees
  exit 1; the doctor class sees the skewed tree read as healthy with the check's call dropped.
  2-C's oracle: on a real init + install-ci tree the only unmarked files under the owned roots
  are `cc/GOAL.md`, `tools/cc/ci_guard.py` and `.claude/settings.json`, so five doctor fixtures
  that stood unmarked files in for deployed surface were marked to the deploy's shape, their
  assertions unchanged (the one-hook-left control keeps its fail verdict on a marked hook).
  Figures: the Walk 43 s for both stacks and the api walk; the start contract 6.9 s, 3.8 s of it
  the cells; the doctor start probe 182 ms median of a 698 ms `doctor`, 12 hooks imported.
- Red-team: `code-reviewer` REQUEST CHANGES (1 BLOCK: `stop_gate.py` kept the shape, reproduced; 1
  NIT: Landing's blank fields) and `failure-mode-reviewer` REQUEST CHANGES (0 regressions, 4 gaps, 3
  rough edges: function-level helper reads outside the roster, `stop_gate.py`, the probe's fail-open
  WARN, the blocking population keyed on emitter names, the Walk's bare restore, the marker rule
  living in five comments, maintenance mode not lifting the refusal undocumented), both on a snapshot
  clone of the diff against HEAD. One fix batch landed every finding: the Stop gate guarded, the
  rosters widened and pinned, the blocking population derived from `GOVERNANCE_BLOCKING_HOOKS`, the
  probe's per-hook fallback, the restore asserted, `tests/_deployed_stub.py::write_deployed` as the
  marker rule's one home, the maintenance-mode sentence in `docs/HOOKS.md`; the two derivations
  (engine and contract) agree that a two-argument `getattr` is a floor read; the install-ci sentence
  has one home in `doctor.py`. The archive probe over the five touched test modules: 432 passed, 20
  xfailed, one red (the advisory-site ratchet on the WARN site), gone with the WARN.
- Reach: `DEF-1176`, `DEF-1188` and `DEF-1061` struck (probes driven to their closed values first);
  `DEF-1050`, `DEC-39`, `DEF-1032`, `DEF-1033`, `DEF-1064`, `DEF-1077`, `DEF-1126`, `DEF-1104` and
  `DEF-1063` carried as strict-xfail bridges in the Walk for the upgrade, CI and onboarding lanes;
  `DEF-1052`, `DEF-1057` untouched.
- Date: 2026-10-10 (lane 1 of four).
- **Lane 2, upgrade** (3-A to 3-D, `lane/upgrade`, win-2, assigned `20261010T225709Z-air-95186b`,
  first edit after #177 merged at `b9005ee`). Pre-flight on the tree it executes: 0-A
  `code-reviewer` with the checklist on #177's head, APPROVE (0 BLOCK, 7 WARN, 4 NIT; the two
  load-bearing WARNs verified in source and folded into the build notes above: a no-plan execute
  test in `tests/test_cli_deploy.py`, and the plan loaded only on the same-version arm); 0-B
  scope-check exit 2, the gap in the authoring categories (comments naming the verbs, the selfcheck
  mirror its sync writes, prose, lane 4's install-ci mirrors), accepted; 0-C sister-site probe exit
  0 (103 files, 10 hidden by markers); 0-D surface-impact exit 2 with no lane-2 path (the CLI hit is
  the existing verbs the pack names), accepted.
- Task 0, lane 2 (2026-10-10, #177's head `641974e`, Windows, Python 3.11.9): the four bridged
  classes run with `--runxfail` red with the Motivation values -- the body unnamed in both reports
  (`26 files ... (+16 more)`: the Walk stales every hook, not twelve), `absent or unreadable`,
  `deployed 99.0.0 -> engine 0.8.0b2` then `would re-deploy`, the clone's execute exit 0. 3-A's
  refutation re-measured on a plain and a Walk-shaped skewed clone: `init .` left `git status`
  empty and `doctor` 0. The Walk's fixture took 142 s and 123 s per stack here against the 60 s
  ceiling (43 s for all on the Air; CI's windows-latest cell ran the module green), so local runs of
  the module on this box take `--timeout=900`.
- Earn-the-red, lane 2: every new or changed test red on the tree without the fix (the #177 snapshot
  for the first pass, the pre-red-team snapshot for the batch) and green with it -- 15 at the build
  (the stamp-order table by absence, the four behaviour tests and the models test on their
  assertions), 6 at the red-team batch (the four-verb refusal, the restore command, the no-plan
  preview with a settings file present, the unreadable plan, the older-stamped clone naming the
  body, the fifth-body pin). The Walk: the four classes green with their bridges deleted, 8 xfailed
  left (lanes 4 and 5), no XPASS; `TestTheWalkRan` re-pinned the two refusals at exit 2 (lane 1
  had listed them at 0, their pre-fix value, against its own docstring).
- Red-team, lane 2 (both reviewers on a frozen snapshot of the diff against `b9005ee`):
  `code-reviewer` REQUEST CHANGES (0 BLOCK, 2 MAJOR: the plan-less dry run's drift lines still
  credited `--execute`, and the test that would have caught it asserted too little; 3 MINOR: an
  unreadable plan called absent, the never-deployed ordering unpinned, `fuse` meeting init's
  refusal; 1 NIT: no override) and `failure-mode-reviewer` REQUEST CHANGES (1 BLOCK: the Walk's
  exit-0 pins, already fixed in the tree; 2 MAJOR, both driven: `init .` without `--wire-hooks`
  leaves a present settings file's new hook events unwired, and `install-ci` and `fingerprint` roll
  a newer deployment back; 6 MINOR, 4 NIT). One fix batch: one restore command (`init .`,
  `init . --wire-hooks` with a settings file present, `doctor .` on the self-host tree) through the
  refusal, the drift lines, the not-compared item, the re-run hints, the kept-helper line and the
  preview's last line; absent and unreadable told apart; the plan-less preview names what the
  restore command would replace and `init --dry-run` names what it overwrites; the newer-stamp
  refusal on `install-ci` and `fingerprint` with the deliberate-rollback route named; the fifth
  agent body and a derived pin over every body with the section; whole-tree digests for "nothing
  written"; the Walk's refusals pinned `== 2`; one declared-field filter in `espalier/models.py`.
  Not changed, with the reason: `fuse` already fails naming init's output when init refuses; the
  DEF-1104 probe keys on any `# espalier-` header line beside the version (a stamp line added for
  another purpose would read it closed, so a strike re-reads the row first); no override flag (the
  row keeps that half open).
- Suite, lane 2 (2026-10-10/11, win-2, Windows, Python 3.11.9): the full tier `proof_tier.py`
  names for the working tree (`full`: `espalier/cli.py`, `espalier/models.py`), run gently because
  Claude Code reaped a 6-worker run at 16% for box memory (another seat's tier was running): its
  parallel leg as ten interleaved chunks at 2 workers then 1, each recorded and resumed on its own
  record, a 3 GB free-memory floor before each, `--timeout=300`; then the serial leg. ruff clean.
  21338 passed, 10 xfailed (the bridges lanes 4 and 5 still carry; 22 before this lane, its 12
  cells gone), 2 red, neither this lane's: the `test_merge_settings` python3 row (this host's
  baseline, red on the unfixed snapshot too) and `TestNoMachineLocalPaths` in a linked worktree
  (`espalier/repo_mode.py::list_tracked_or_walked_files` asks `.git` for `is_dir()`, so a worktree's
  gitlink file reads as no checkout, the tree is walked and a gitignored session log is scanned as
  tracked; a CI checkout is never a linked worktree). The tier's one red of this lane's own -- a
  settings-path existence check asked of pathlib (`TestSettingsPresenceNeverAsksPathlib`) -- went
  to `os.path.isfile`, and its chunk re-ran green. The release-archive probe over the four touched
  test modules (`scripts/archive_probe.py`, in-process): 233 passed, 8 xfailed, 0 red.
- Reach, lane 2: `DEF-1063`, `DEF-1064` and `DEF-1126` struck, each probe driven to its closed value
  on the final tree first; `DEF-1104` NOT CLOSED, re-pinned to the build identity (open `False`)
  with the ordering half and the two sister verbs recorded in its text and the explicit override
  kept open; `DEF-1077` NOT CLOSED (no probe; the short-term clause landed in five bodies, the
  overlay and `RELIEF_FLAGS` stay with the row). This pack's Scope (out) sentence on `TP-473` 1-C
  re-pointed to 3-A, which the strike's deferral check named.
- **Lane 4, CI** (4-A, 4-B, `lane/ci-marker-and-posture`, win-2, assigned
  `20261011T024203Z-air-e0fb64`, first edit after #184 merged at `0a6335b`, caught up to `eebe9b6`
  before it). Pre-flight: 0-A `code-reviewer` with checklist v2, REQUEST CHANGES, 3 BLOCK verified
  in source (Risk 5 inverted -- under (b) the adopter answer is the looser one for `is_protected`,
  and `tools/cc/ship.py::guard_predicate` calls it with one argument and no `run()`; the generated
  `ci-gated-paths` block, which ships in the code-reviewer body; `TestDependabotActionBumpAllowance`
  on an adopter-shaped tree) and WARNs (the fifth §C68 writer, the git reader, no Walk witness for
  `DEF-1052`); the amendments above, operator-approved, and a second 0-A pass that cleared the
  BLOCKs, its WARNs folded and acknowledged. 0-B exit 2, the authoring categories, accepted; 0-C
  exit 0 (103 files, 10 hidden by markers); 0-D no lane-4 path.
- Task 0, lane 4 (2026-10-11, `0a6335b`, Windows, Python 3.11.9): the two bridged classes with
  `--runxfail` red on both stacks with the Motivation values (install-ci's stdout never names the
  marker; the own-`ci.yml` pull-request replay exits 2); the `DEF-1050`, `DEF-1051` and `DEF-1052`
  probes `STILL_OPEN`; `DEC-39` has no probe. No refutation.
- Earn-the-red, lane 4: 11 tests red on the unfixed guard (the adopter's own-workflow pull request
  and push, the subset pin, seven posture rows, the prefix-by-posture pin) and the four writer arms
  that must name the marker red before the call sites were wired; each green with its fix.
  Mutants killed: `self_host=False` as the default (the ship real-guard case and the parity
  posture pin), `run()` ignoring the posture, each of six `espalier/cli.py` call sites (each by its
  own arm), the ignore filter, both fuse sites; at the red-team batch, a head-only posture (three
  signal-breakage rows), a posture read from the process cwd, the upgrade manifest append, the
  clean-generated, integrity-refresh and rewire sites, the push form's HEAD wording and the fuse
  inline fallback. `DEF-1051`'s probe reads open again with the fuse call removed (the checklist
  no longer spells the marker). `tests/test_verify_pins.py` skips at module level on every public
  clone (its control commits predate the cut; this clone is full, 821 commits), so the amendment's
  "live controls active" could not be met here.
- Red-team, lane 4 (both reviewers on a snapshot clone of the diff against `eebe9b6`):
  `code-reviewer` REQUEST CHANGES (2 MAJOR: a pull request's own tree decides the posture, so a
  self-host change that breaks a detector signal ungates its own workflows; `init` re-run naming
  the marker for the manifest -- truthful, the manifest stamps `generated_at`, so a tracked one
  changes on every write; 3 MINOR, 3 NIT) and `failure-mode-reviewer` REQUEST CHANGES (1
  REGRESSION, the detector's fail-closed claim no longer held on the workflows axis; 1 GAP,
  `clean-generated --execute`, `init --rewire-interpreter` and upgrade's manifest refresh write
  gated paths silently, and the Quickstart overclaimed; 5 ROUGH-EDGE: HEAD wording, witnesses that
  stay green on a regression, no adopter notice of the policy change, a posture-blind doc check,
  drift traps). One fix batch: `_ci_self_host_posture` judges the tree under review OR its base
  (`_ci_base_is_self_host` materialises the base's signals for the one detector), `is_protected`
  keyword-only, the detector docstring and `docs/CONVENTIONS.md` corrected; `clean-generated`
  (stderr, stdout stays one JSON document), `integrity refresh`, the rewire and upgrade's manifest
  join the writers; the push form names the HEAD commit message; `FINISH_UP_STEPS` and
  `INSTALL_CI_INSTRUCTIONS` never spell the marker (a comment and a pin say why); the fuse pointer
  prints only where the forms printed; `install-ci` says once when it replaces a guard that gated
  every workflow; the Quickstart's uninstall clause; a parity pin on the engine's copy of the
  marker. Not changed, with the reason: the doc over-claim check stays posture-blind (a token scan
  cannot read the scope prose beside `.github/workflows/`; section 3 is hand-written and reviewed);
  `/ship` keeps over-binding the marker for an adopter's own workflow change (the one-argument
  call is the tight answer by design; a marker nobody needed costs nothing); a derived census of
  every verb that writes a gated path needs its own oracle and is proposed as a row.
- Suite, lane 4 (2026-10-11, win-2, Windows, Python 3.11.9, maintenance mode unset for the run):
  the full tier `proof_tier.py` names for the working tree (`full`: `espalier/cli.py`,
  `espalier/fuse.py`, `espalier/fusion_manifest.py`, `espalier/surface_contract.py`,
  `tools/cc/ci_guard.py`); mypy (`--platform linux`) and ruff clean; the parallel leg at 6 workers
  with `--timeout=900` (the Walk), 20382 passed, 394 skipped, 6 xfailed (lane 5's four bridges and
  two older) in 34:48; the serial leg 1070 passed in 3:21. Two reds, neither this lane's: the
  `test_merge_settings` python3 row (this host's baseline) and `TestNoMachineLocalPaths` on
  `cc/discard_snapshots.log` in a linked worktree (the same red lane 2 recorded). The checkpoint
  before the review, 1690 passed; after the batch, 1284 passed over the affected modules.
- Reach, lane 4: `DEF-1050`, `DEF-1051` and `DEF-1052` struck, each probe driven to its closed
  value on the final tree first (`DEF-1051` after this pack's Scope (out) citation was re-pointed
  to 4-A, which the strike's deferral check named); `DEC-39` struck by hand (a three-cell row the
  verb refuses) as decided (b) and landed. The §C68 class is closed with them; its writer roster
  is the eight verbs `tests/test_cli_deploy.py::TestEveryWriterOfAGatedPathNamesTheMarker` and
  `tests/test_fuse.py` pin, a hand list (the derived census above is the proposed row).
- Date: 2026-10-11 (the third of the four lanes to land; the onboarding lane, 5-A, remains).
- Pre-flight, lane 5 (`lane/onboarding` from `1c8586b`, win-2): 0-A the checklist v2, REQUEST
  CHANGES with 0 BLOCK and 4 WARN (the "same way" sentence read `espalier.toml` as the goal is read,
  which the `DEF-1034` probe and both TOML readers contradict; no rule for a headingless goal; the
  bridge deletion unstated; "flip only all together" false) and 2 NIT; 5-A amended above,
  operator-approved, and a reach row approved. 0-B and 0-D exit 2 on the landed lanes' symbols and
  surfaces, accepted; 0-C exit 0 (103 files).
- Task 0, lane 5 (2026-10-11, `1c8586b`, Windows, Python 3.11.9): the `DEF-1032`, `DEF-1033` and
  `DEF-1034` probes `STILL_OPEN`; the bridged `TestOnbOneReadsTheGoal` red on both stacks with
  `--runxfail` with the Motivation values (`goal_written` `True`, `key_set_skeleton_kept` `False`).
  No refutation.
- Earn-the-red, lane 5: the truth table's first 27 states 16 red on the unfixed codes, exactly the
  predicted set; it caught a BOM off-by-one in a first ONB-7 draft. Mutants, round one: the section
  rule, the file-before-key rule, the goal decode, the config and stub read, the NUL rule each
  reopen only their own row's probe; a BOM-led config read as keys is caught by the table alone.
  Round two, on the fix batch: 14 of 15 killed (the replace-decoded stub is equivalent: it never
  hashes to its stamp), and the reader-drift mutant (`load_config` reading `utf-8-sig`) reds the
  reader-agreement test.
- Red-team, lane 5 (both reviewers on a snapshot clone of the diff against `1c8586b`):
  `code-reviewer` APPROVE (4 MINOR, 3 NIT); `failure-mode-reviewer` REQUEST CHANGES (0 REGRESSION;
  3 GAP: the table pinned literals, not the readers; a blank goal read closed; a malformed config's
  key read as set; 6 ROUGH-EDGE). One fix batch: `espalier.toml` parsed with the harness's own
  parser (the hooks' regex arm where the probe has none); a blank goal file is no file and an empty
  Goal body is open; `## Goals`; the placeholder as a word; the ONB-1 anchor; no `!` in a code; the
  table at 49 states with a reader-agreement test, a no-parser test, an id-coverage test. Not
  changed, recorded: a deleted stub closes its half of ONB-7 while doctor reads a missing
  `docs/CONVENTIONS.md` as ungrounded (outside the three rows); a bare-CR `espalier.toml`.
- Suite, lane 5 (2026-10-11/12, win-2, Windows, Python 3.11.9, maintenance mode unset for the run):
  the full tier `proof_tier.py` names (`full`: `espalier/cli.py`), on the final tree with the pack's
  closure applied; mypy (`--platform linux`) and ruff clean; the contract slice at 8 workers, 4660
  passed (its first run redded this pack's closure while the pack was still in `Done/` locally --
  corrected below -- and two xdist teardown ERRORs that pass alone); the parallel leg as seven
  foreground file groups at 4 workers with `--timeout=900`, 20676 passed; the serial leg 1070 passed
  in 1:59. Two reds, neither this lane's: `TestNoMachineLocalPaths` on `cc/discard_snapshots.log`
  in a linked worktree and the `test_merge_settings` python3 row (this host's baseline).
  `pre-release` and `audit` fail only for the gitignored `reports/` this worktree never generated.
- Commits, lane 5: two on `lane/onboarding` -- the lane (this text), then the closure (this pack
  untracked, its id in the dangling-id baseline, `TP-473`'s Scope (out) citation re-keyed). This
  Windows clone keeps no `Done/` archive, so the record lives here, in history; creating a local
  `Done/` with one pack turns on the population tests a clone without it skips.
- Reach, lane 5: `DEF-1032`, `DEF-1033` and `DEF-1034` struck, each probe driven to its closed value
  first; `DEF-3003` filed (an adopter's stored onboarding probes are never re-pinned by `upgrade`,
  driven open). The pack closes with this lane: its §3 row struck by hand, its three live citing
  rows re-keyed through the verb, the id added to the dangling-id baseline.
- Date: 2026-10-11 (lane 5, the last of four).
