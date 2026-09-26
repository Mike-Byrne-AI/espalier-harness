# Environment Variable Catalog

This document enumerates every `ESPALIER_*` and harness-significant
environment variable. Producer and consumer locations are pinned;
`tests/test_env_catalog.py` enforces that every read site is listed
here.

> Source paths in this document name files in the Espalier source repo
> (`tests/…`, `scripts/…`, `bench/…`, `espalier/…`): they say where a
> variable is read or set, and `init` does not deploy them.

> **Interpreter note.** The commands below spell `python`. A stock macOS ships only
> `python3` (and it is 3.9; Espalier requires 3.10+), while many Windows installs ship
> only `python`. Use whichever both resolves AND reports 3.10+
> (`<name> --version`); on a stock macOS `python3` resolves but is 3.9.
> `espalier doctor .` checks this for you.

| Variable | Producer | Consumer(s) | Default | Effect |
|---|---|---|---|---|
| `ESPALIER_MAINTENANCE_MODE` | Shell (`scripts/launch.sh` or operator) | `tools/cc/hooks/_maintenance_mode.py` | unset | `=1` bypasses `write_guard` protected-zone check, `plan_guard` short-circuit, `stop_gate` Gates 2/3, `subagent_stop` blueprint append. See `CLAUDE.md` section "Maintenance mode". |
| `ESPALIER_PWSH` | Shell / operator; `scripts/host_check.py` sets it for its Windows PowerShell 5.1 step | `bench/powershell_reachability_differential.py`, `scripts/host_check.py` | unset | Path to the PowerShell the differential drives; wins over the PATH lookup (`pwsh`, then `powershell`). Point it at a build unpacked outside PATH, or at Windows PowerShell 5.1 on a host where `pwsh` would otherwise win. |
| `ESPALIER_STOP_GATE` | Shell | `tools/cc/hooks/stop_gate.py`, `tools/cc/hooks/session_start.py`, `tools/cc/statusline.py` | `light` | `=full` runs Gate 1 (pytest) on every Stop. Default `light` skips pytest — tests are signal, not friction. |
| `ESPALIER_STOP_GATE_TEST_CMD` | Shell / CI | `tools/cc/hooks/stop_gate.py:257` | derived from fingerprint | Override the test command Gate 1 invokes. Set it when the fingerprint-derived command is too slow to finish inside the Stop gate's timeout. |
| `ESPALIER_TELEMETRY_UNDER_TEST` | pytest (`tests/test_reinject.py::telemetry_on`) | `tools/cc/hooks/_hook_utils.py` (`_telemetry_enabled`) | unset | `=1` re-enables recall-engine telemetry writes under pytest. Telemetry is suppressed whenever `PYTEST_CURRENT_TEST` is set, because a suite run is not an operator session and the suite would otherwise dominate the log it measures (~89% of rows, measured). Only the tests that exercise the telemetry path itself set this. |
| `ESPALIER_AUDIT_DIR` | Shell / tests | `tools/cc/hooks/_integrity.py:809` | `~/.espalier/audit` | Override audit-log destination (per-test isolation). |
| `ESPALIER_RELEASE_CHECK_WITH_TESTS` | CI | `scripts/release_check.py` | unset | When set, release_check runs the test suite in-process. |
| `ESPALIER_RELEASE_CHECK_WITH_WHEEL_SMOKE` | CI | `scripts/release_check.py` | unset | When set, release_check invokes wheel_smoke. |
| `ESPALIER_RELEASE_CHECK_WITH_URLS` | CI / publish | `scripts/release_check.py` | unset | When set, release_check visits the canonical Homepage + CI-badge SVG and FAILs on a resolved non-200 (offline → SKIP). Publish-time URL-reachability gate. |
| `ESPALIER_ALLOW_PARITY_SKIP` | Tests | `tests/test_wheel_install_surface_parity.py`, `tests/test_artifact_parity.py` | unset | Allows specific parity tests to skip when fixture preconditions (e.g. `python -m build` availability) aren't met. Test-only escape hatch. |
| `ESPALIER_FULL_TREE_AUDIT` | Operator, ON AN EXTRACTED EXPORT | `tests/conftest.py` (`pytest_collection_modifyitems`) | unset | `=1` stops `full_tree` tests auto-skipping on a detected release export, so they RUN there. The self-expiry oracle for `_FULL_TREE_NODEIDS`: three contracts assert every fragment points at something real, none asks whether it still EARNS its suppression, so a registration outlives its reason silently. Run `ESPALIER_FULL_TREE_AUDIT=1 python -m pytest -m full_tree -q` inside an extracted archive -- `python3 scripts/archive_probe.py --audit -- -q -rA -m full_tree` builds, seeds and drives one from this checkout (maintainer tooling, not deployed by `espalier init`); every test that PASSES is a stale entry to delete once you have checked it asserts over a non-degenerate population there (a pass whose stressor the builder prunes before the question is asked is vacuous, not stale, and keeps its entry with that reason written beside it), and failures are the healthy result. Also reaches `tests/_export_guard.py::pruned_from_this_tree`, the per-arm export guard: under the audit it forgives nothing, so a roster entry whose export-forgiveness has lapsed reds there instead of staying forgiven. Off an export the switch REFUSES to collect (`pytest.UsageError`) rather than doing nothing: registered rows would run on their own dev content and read as stale. |
| `ESPALIER_VERIFY_PINS_DEPTH` | Set by `scripts/verify_pins.py` into every child pytest env; never by an operator | `scripts/verify_pins.py`, `tests/test_verify_pins.py` | unset (treated as `0`) | Recursion fuse. `verify_pins` runs pytest inside a throwaway clone; when the change under test IS `scripts/verify_pins.py`, the selection contains `tests/test_verify_pins.py`, whose controls clone and run pytest again — measured 2026-08-21 as 17 live clones and a run that never terminated. The child reads this counter and skips only its CLONING controls at `>= 1`; the in-process ones still run, so the gate's verdict on its own change means more than "the file exists". |
| `ESPALIER_CANON_VERIFIER` | Shell / CI | `espalier/scanners/canon_verifier.py`, `tests/test_canon_verifier_contract.py` | unset | `=enforce` flips the canon-vs-claim contract test from advisory (smoke + stdlib-only) to enforcing (9/9 pass when bootstrap complete). Bootstrap discipline: default OFF until the canon set is complete. |
| `CLAUDE_PROJECT_DIR` | Claude Code | 8+ hooks/scripts | (always set by CC) | Project root path. Hook entry-point convention. |
| `PYTHONPATH` | Hook bridge | `tools/cc/hooks/post_write_check.py:188` | unset | Pushed/popped via `env.pop`/`env[]=` to make `espalier` importable from a source checkout when running hook subprocess. Not accessed via `os.environ.get`; documented here for completeness. |
| `TMPDIR` | OS / tests | `tools/cc/hooks/_integrity.py:861` | OS default | Override-validated: `tempfile.gettempdir()` returns `$TMPDIR` when that is set, so the destination is validated rather than trusted. |

> The `ESPALIER_RELEASE_CHECK_WITH_*` variables and their consumer `scripts/release_check.py`
> are Espalier-Harness self-host release tooling; `espalier init` does not deploy `scripts/`, so
> those rows are reference-only in an adopter repo.

Claude Code *platform* vars that influence harness-composed workflows but are
read by Claude Code itself (not by harness code) are documented outside this
catalog, whose contract is that every listed var has a live harness reader.
`docs/CC_AUTOMATION.md` (Espalier source repo — not deployed by `init`) covers
`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` (raises the consecutive-Stop-block override;
affects `/goal` and `stop_gate.py`) and `CLAUDE_CODE_DISABLE_CRON` (`=1`
disables all cron + `/loop`). The Windows section of `docs/QUICKSTART.md`
(Espalier source repo — not deployed by `init`) covers
`CLAUDE_CODE_USE_POWERSHELL_TOOL` (`=1` at launch turns on the PowerShell tool
where an account does not have it by default; the guard's PowerShell legs and
any `PowerShell(...)` permission rule only see calls once it is on).

## Adding a new env variable

1. Add the row to the table above.
2. No manual reader registration is needed for a normal reader —
   `tests/test_env_catalog.py` auto-discovers any `os.environ.get` / `os.getenv`-shape
   read by AST walk (`_live_readers`). Only a var the walker can't see as a read — one
   injected via hook protocol (`CLAUDE_PROJECT_DIR`) or accessed write-shape
   (`PYTHONPATH`) — must be added to `tests/test_env_catalog.py::_IMPLICIT_READERS`.
3. Run `pytest tests/test_env_catalog.py -q` (Espalier source repo only) — green confirms catalog parity.
