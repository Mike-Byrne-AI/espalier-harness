"""Shared fixtures for Espalier-Harness test suite."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Registers the hook by name: every test report is formed under the host's
# real `os.name`, so a failing Windows-emulated row is a failure and not a
# session INTERNALERROR on the 3.10/3.11 floor (the module says why).
from tests._report_os_name_guard import pytest_runtest_makereport  # noqa: F401

# The stack fixtures below write rows of the one stack table. Imported bare,
# the way the selfcheck mirror's conftest imports its byte copy.
from _stack_trees import write_stack

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _reset_speedbump_snapshot_record():
    """`_speedbump._last_snapshot` is the per-process record the two snapshot
    promises read (DEF-802: CP-RMRF and CP-DISCARD name a snapshot only when
    `snapshot_discard` recorded one for the command in the checkout). Under
    pytest one process spans the suite, so a test that snapshotted
    `rm -rf src` would lend a later test's fire on the same text a stale
    promise. Reset every loaded copy of the module -- the hooks are loaded
    under more than one name by `spec_from_file_location` -- before each
    test."""
    for mod in list(sys.modules.values()):
        path = getattr(mod, "__file__", None) or ""
        if path.endswith("_speedbump.py") and hasattr(mod, "_last_snapshot"):
            mod._last_snapshot = None
    yield


@pytest.fixture(autouse=True)
def _restore_interpreter_warn_flag():
    """Keep ``cli._INTERPRETER_WARNING_EMITTED`` from leaking between tests.

    It is a once-per-PROCESS flag: the first unvalidated-interpreter warning
    sets it so the rest of a real run stays quiet. Under pytest the "process"
    spans the whole suite, so one test that drives ``_detect_python_command``
    into its warn path silences it for every test after — and
    ``test_cli_commands.py::TestDetectPythonCommand::test_warn_once_flag_ships_unset``
    exists precisely because a permanently-set flag retires the resolver's
    fail-open warning while the suite stays green.

    Surfaced by TP-448 Class 3: raising the predicate from
    ``startswith("Python 3.")`` to the >=3.10 floor made ``_detect_python_command``
    reach the warn path in configurations it used to exit early from, so three
    ``test_doctor.py`` tests that fabricate ``shutil.which`` began setting it.
    The leak was always possible; the floor just made it reachable. Restoring
    around every test makes the shipped-value assertion order-independent
    instead of dependent on what ran before it.
    """
    from espalier import cli as _cli
    original = _cli._INTERPRETER_WARNING_EMITTED
    try:
        yield
    finally:
        _cli._INTERPRETER_WARNING_EMITTED = original


@pytest.fixture(autouse=True)
def _isolate_maintenance_mode(monkeypatch):
    # Subprocess helpers across the suite build env via os.environ.copy() and
    # would otherwise inherit ESPALIER_MAINTENANCE_MODE from the launching
    # shell, silently bypassing the protections under test. Tests that
    # exercise maintenance mode set the var explicitly in their own env dict.
    monkeypatch.delenv("ESPALIER_MAINTENANCE_MODE", raising=False)


@pytest.fixture(autouse=True, scope="session")
def _isolate_claude_code_session():
    """Claude Code exports ``CLAUDECODE=1`` into its shell, and ``clean-generated
    --execute`` reads it as "a session may be running these hooks" and unwires
    only (DEF-1060). A suite launched from a session would take that path in
    every uninstall it drives while CI took the other; tests that exercise the
    live-session path set it themselves. Session-scoped for the reason
    ``_isolate_forced_colour`` gives: ``test_adopter_lifecycle_diagnostics.walked``
    is module-scoped and spawns its uninstall before any function-scoped
    fixture runs (the failure-mode review of the DEF-1060 lane found the
    function-scoped first draft missed it)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("CLAUDECODE", raising=False)
        yield


@pytest.fixture(autouse=True, scope="session")
def _isolate_forced_colour():
    """A child's colour must follow the pipe it writes to, not the launching
    shell's terminal. Claude Code's tool shell exports ``FORCE_COLOR=3``
    (measured 2026-09-28), the subprocess helpers inherit or copy
    ``os.environ``, and a child whose stdout is a captured pipe then colours
    it anyway: four tests that parse child output -- an argparse help listing,
    a nested pytest's node ids and its verdict line -- were red at HEAD under
    the variable and green without it, from a fresh clone, so the tier run
    from a session showed four false reds. ``scripts/verify_pins.py`` had
    popped the variable for its own children with the same diagnosis; this is
    the suite-wide home. Session-scoped, because a module-scoped fixture
    (``test_adopter_lifecycle_diagnostics.walked``) spawns its child before
    any function-scoped fixture runs. ``NO_COLOR`` is left alone (a test that
    sets it is testing something), and pytest's own reporter decided its
    markup before any fixture ran."""
    with pytest.MonkeyPatch.context() as mp:
        for name in ("FORCE_COLOR", "CLICOLOR_FORCE", "PY_COLORS"):
            mp.delenv(name, raising=False)
        yield

@pytest.fixture(autouse=True)
def _isolate_interpreter_identity_memo():
    """`_hook_utils._INTERPRETER_IDENTITY_MEMO` is a process-global cache, so a
    test that drives the real (unmocked) identity probe leaves a verdict behind
    for every test after it in the same worker.

    Until now the contract was "always clear it around a real probe", enforced
    by four hand-written try/finally blocks and author memory. A future test
    that probes under a patched `shutil.which` and forgets the finally would
    poison a neighbouring assertion -- deterministically today (pytest-randomly
    is not installed), intermittently the day it is. Make it a fixture instead
    of a convention.

    The same shape covers the sibling-checkout memos DEF-743 added
    (`_SIBLING_CHECKOUTS_MEMO`, `_CHECKOUT_BASES_MEMO`): every hook copy binds
    the one `_hook_utils` module object, so a worktree registered on a root
    after a first read of it would otherwise stay invisible to every later test
    in the worker (the failure-mode review drove a registered worktree reported
    as a foreign clone that way).
    """
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_hook_utils_memo_fixture",
            REPO_ROOT / "tools" / "cc" / "hooks" / "_hook_utils.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # The module object under test is whichever copy the test imports, so
        # reach the live one through sys.modules when it is already loaded.
        import sys as _sys
        _clear_hook_utils_memos(_sys.modules.get("_hook_utils"))
    except Exception:  # noqa: BLE001, S110 - a missing hook module must not break collection
        pass
    yield
    _clear_hook_utils_memos(__import__("sys").modules.get("_hook_utils"))


def _clear_hook_utils_memos(live) -> None:
    """Clear every process-global memo the live `_hook_utils` keeps; a missing
    module or attribute is a no-op."""
    identity = getattr(live, "_INTERPRETER_IDENTITY_MEMO", None)
    if identity is not None:
        identity.clear()
    checkouts = getattr(live, "_SIBLING_CHECKOUTS_MEMO", None)
    if checkouts is not None:
        checkouts.clear()
    bases = getattr(live, "_CHECKOUT_BASES_MEMO", None)
    if bases is not None:
        bases.clear()
    # espalier.toml's source_extensions, keyed on the file's mtime and size: a
    # test that rewrites one tree's file within the clock's resolution at the
    # same size would otherwise read the previous test's parse.
    source_ext = getattr(live, "_SOURCE_EXT_MEMO", None)
    if source_ext is not None:
        source_ext.clear()
    # The hook run's advisory collector (`advise` keeps a line for the hook's
    # one JSON object) and say_once's in-process once-set: both are per hook
    # PROCESS in production, and one pytest process spans the suite, so a line
    # one test kept would render in the next test's banner, and a key one test
    # said would silence the next test's record.
    advisories = getattr(live, "_ADVISORIES", None)
    if advisories is not None:
        advisories.clear()
    said = getattr(live, "_SAID_THIS_PROCESS", None)
    if said is not None:
        said.clear()


@pytest.fixture(autouse=True)
def _no_live_once_flags():
    """A test that drives a ``say_once`` site in-process with no scratch root
    -- ``CLAUDE_PROJECT_DIR`` unset, or a ``Path(".")`` root -- writes the
    ``once_<key>`` flag into THIS checkout's ``.espalier-state/``, and the live
    session's next real fault of that key then goes unrecorded until the next
    startup (the voice lane's first test run did exactly that, 2026-10-06).
    The live tree guard below does not watch ``.espalier-state/`` (the
    operator's own hooks churn it), so this one is attributed instead: a new
    flag whose key this test's process said (``_SAID_THIS_PROCESS``, read
    before the memo fixture above clears it -- autouse fixtures tear down in
    reverse definition order) is this test's leak. It is deleted and the test
    fails."""
    state = REPO_ROOT / ".espalier-state"

    def _flags() -> set[str]:
        try:
            return {f.name for f in state.glob("once_*")}
        except OSError:
            return set()

    before = _flags()
    yield
    new = _flags() - before
    if not new:
        return
    live = sys.modules.get("_hook_utils")
    said = set(getattr(live, "_SAID_THIS_PROCESS", ()) or ())
    leaked = sorted(n for n in new if n[len("once_"):] in said)
    for name in leaked:
        try:
            (state / name).unlink()
        except OSError:
            pass
    if leaked:
        pytest.fail(
            f"this test wrote say_once flag(s) {leaked} into the live checkout's .espalier-state/ "
            "(deleted). Point CLAUDE_PROJECT_DIR, or the root it passes, at tmp_path.",
            pytrace=False,
        )


@pytest.fixture(autouse=True)
def _isolate_audit_dir(monkeypatch, tmp_path):
    # Redirect audit logs to a per-test tmp dir so pytest runs never write
    # into ~/.espalier/audit/ and leave test slugs on the developer's machine.
    audit_tmp = tmp_path / "audit"
    audit_tmp.mkdir()
    monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(audit_tmp))


# ── Live-tree write guard ───────────────────────────────────────────────────
# A test that writes into the working tree makes the SUITE order-dependent:
# sibling tests that scan the live repo then see a tree whose contents depend on
# what has run so far, and two identical suite runs can disagree. That was
# observed — 12 failures then 3 on an unchanged tree, with the nine that
# vanished all in files that scan the live repo and all passing in isolation.
#
# Watched by ENTRY COUNT, deliberately — not by mtime and not by full listing.
#
#   * NOT a full walk: `bench/results/` alone holds thousands of entries, and
#     walking it per test is what made the first instrumented pass time out.
#   * NOT mtime: several production helpers write their report ATOMICALLY
#     (temp file + rename), which moves the directory mtime while leaving the
#     content byte-identical. Measured: `run_self_host_check` rewrites
#     `reports/cc_surface_gate.json` on every call with identical bytes. An
#     mtime guard flagged 22 tests for a rewrite that changes nothing a
#     scanner can observe — a false positive, and the reason this watches
#     ADD/REMOVE instead.
#
# Entry count is what changes what a live-tree scanner SEES. It is one listdir
# per watched dir per test (~microseconds), and it cannot be fooled by a
# same-name rewrite.
#
# NOT watched: `.espalier-state/` — the operator's own Claude Code hooks churn
# it on every tool call, concurrently with the suite, so a change there is not
# attributable to the running test.
#
# Same reasoning, measured 2026-08-05 on a fresh clone: `espalier_harness.egg-info`
# is created by `pip install -e .[dev]` (so it appears mid-suite on any tree that
# installs during the run) and `cc/blueprints` is written by a concurrent Claude
# Code SessionStart. Neither is attributable to the test that happens to straddle
# it — both produced `None -> N entries` ERRORs pinned on arbitrary tests. A guard
# that fires on churn it cannot attribute is noise, and noise gets silenced.
#
# SCOPE, stated because it is not obvious and a review had to measure it: this guard
# is DEV-TREE-ONLY. Both remaining entries are gitignored with zero tracked files, so
# on a fresh clone neither directory exists, every fingerprint is None, and the
# fixture passes without observing anything. That is not a defect to fix by re-adding
# a watched path — it is what watching *output* directories means. The guard earns
# its keep on the maintainer's tree, where it caught a real order-dependence bug; it
# is not, and cannot be, a clone-side check. Non-emptiness is pinned by
# tests/test_test_suite_contract.py::test_live_tree_watch_is_not_whittled_to_nothing,
# so the list cannot be quietly emptied to clear a red.
#
# KNOWN COVERAGE LOSS, accepted deliberately: dropping `cc/blueprints` removes the
# one watcher for a bug class this repo HAS hit — a leaked CLAUDE_PROJECT_DIR making
# a test subprocess write into the real blueprint tree (docs/SHARP_EDGES.md,
# "Subprocesses Inheriting CLAUDE_PROJECT_DIR"). No test leaks it today: both
# cognitive_blueprint subprocess callers pin CLAUDE_PROJECT_DIR to tmp_path. The
# better long-term fix is to watch it again and allowlist the specific straddling
# tests via _LIVE_TREE_ALLOWED, not to leave it unwatched — recorded here so the
# trade stays visible instead of being silently made.
_LIVE_TREE_WATCH = (
    "bench/results",
    "reports",
)

# Tests that add or remove live-tree entries BY DESIGN. Empty on purpose: the
# calibration pass found no test that genuinely needs to, once the one real
# offender was redirected to tmp. A new entry here is a deliberate, reviewed
# exception with a stated reason — never a way to silence a red.
_LIVE_TREE_ALLOWED: set[str] = set()


def _live_tree_fingerprint(root: Path = REPO_ROOT, watch=_LIVE_TREE_WATCH):
    """The entry SET per watched dir. A set, not a count: a test that adds one
    entry while another entry goes away (its own doing, or -- under xdist -- a
    sibling worker's) leaves the count unchanged and would pass, a false green
    in the one guard the parallel default leans on (2026-09-06)."""
    out = {}
    for rel in watch:
        d = root / rel
        try:
            out[rel] = frozenset(os.listdir(d))
        except OSError:
            out[rel] = None
    return out


def _live_tree_moves(before, after):
    """One line per watched dir whose entry set changed, naming what came and
    went, so the failure is self-diagnosing."""
    moved = []
    for k in before:
        if before[k] != after[k]:
            b = before[k] or frozenset()
            a = after[k] or frozenset()
            moved.append(f"{k} (added: {sorted(a - b) or '-'}; removed: {sorted(b - a) or '-'})")
    return sorted(moved)


@pytest.fixture(autouse=True)
def _no_live_tree_writes(request):
    """Fail a test that adds or removes entries in a watched live-tree dir.

    Mechanical replacement for "remember to use tmp_path". The failure names the
    directory, so the fix (redirect the module constant at the call site) is
    immediate rather than a bisect.
    """
    if request.node.nodeid.split("::")[0] in _LIVE_TREE_ALLOWED:
        yield
        return
    before = _live_tree_fingerprint()
    yield
    after = _live_tree_fingerprint()
    moved = _live_tree_moves(before, after)
    xdist_note = (
        "\nTHIS RUN IS UNDER xdist (PYTEST_XDIST_WORKER is set): a sibling worker "
        "can move these entries while this test runs, so this test may be "
        "innocent. Rerun the failing file serially before acting on this "
        "message, record the date and test on the races line in tests/README.md, "
        "and never add to _LIVE_TREE_ALLOWED from a parallel run."
        if os.environ.get("PYTEST_XDIST_WORKER") else ""
    )
    assert not moved, (
        "test added or removed entries in the LIVE repo tree: "
        + ", ".join(moved)
        + ".\nThis makes the suite order-dependent — a sibling that scans the "
        "live repo will see different state depending on whether this test ran "
        "first. Redirect the writer to tmp_path (monkeypatch the module-level "
        "output constant), or add this file to _LIVE_TREE_ALLOWED with the "
        "reason it genuinely cannot be isolated."
        + xdist_note
    )


# ── Live-session-marker guard ───────────────────────────────────────────────
# `.espalier-state/` is unwatched above because the operator's own hooks churn
# it and a change there cannot be attributed to the running test. One write
# there CAN be: a session marker under `.espalier-state/sessions/` carries the
# writing hook's parent pid, and a hook a test spawns directly has THIS process
# as its parent (through `HOOK_PYTHON`, `tests/_interpreter_hosts.py`: a Windows
# venv's `python.exe` is a redirector that would make the hook a grandchild, and
# a hook spawned through `sys.executable` on such a host is invisible to this
# guard -- a named limit, 2026-10-06). So a marker written during a test with `pid == os.getpid()`
# came from a SessionStart this test ran against the live tree -- and the
# operator's next banner names it as a live sibling session for four hours
# (measured 2026-10-05: test_session_start_toc_gating.py drove the hook on
# REPO_ROOT with session id `test` at two sites, and the banner read "2 other
# sessions ... test (started 23 min ago)"). The same run rewrites
# `session_started` and clears the running session's gate counters; those are
# not attributable and stay unwatched, so this guard covers the marker and the
# fix (drive `self_host_tree_copy`, defined beside `initialized_repo_root`)
# covers both.
#
# Attribution is by the marker's pid AND a write inside this test's window (a
# new entry, or an mtime that moved): a marker with another pid (the operator's
# `claude` process), with none, or left by an earlier run whose worker happened
# to hold this pid number is not this test's and is left alone. The litter is
# removed with the failure, so one red does not keep naming a phantom session.
# No allowlist, by design: a test that must observe the self-host banner drives
# a copy of the tree (`self_host_tree_copy`), never the live one.
#
# What this guard does NOT see, named so nobody reads it as the whole class:
#   * a SessionStart sent without a `session_id` writes no marker but still
#     rewrites `session_started` and clears the counters -- not attributable;
#     the two helpers that drive the hook on the self-host surface refuse
#     REPO_ROOT outright instead and send an id, so a re-root there IS seen
#     here (test_session_start_toc_gating.py, test_session_start_maintenance_warn.py);
#   * (closed 2026-10-05) `task_router.py` driven on the live tree with an id
#     self-healed a marker with `pid: null`, the same phantom through the other
#     hook and unattributable; the heartbeat stub now records the hook's parent
#     pid, so that run is seen here like a SessionStart's;
#   * a hook spawned through a shell list or pipe (`sh -c 'a; b'`) records the
#     shell's pid, not this one; a plain `sh -c '<hook>'` execs and is seen;
#   * two workers writing one sid at once: the last writer's pid is on disk, so
#     only that worker reds -- rerun a single red serially before trusting it,
#     as `_no_live_tree_writes`'s xdist note says.
_LIVE_SESSIONS_DIR = REPO_ROOT / ".espalier-state" / "sessions"


def _live_session_markers(d: Path = _LIVE_SESSIONS_DIR) -> dict[str, int]:
    """name -> mtime_ns for every entry under the live sessions dir; empty where
    the directory is absent (every clone and CI)."""
    out: dict[str, int] = {}
    try:
        with os.scandir(d) as it:
            for entry in it:
                try:
                    out[entry.name] = entry.stat().st_mtime_ns
                except OSError:
                    continue
    except OSError:
        pass
    return out


def _session_marker_pid(path: Path):
    """The `pid` a session marker records, or None where it cannot be read."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record.get("pid") if isinstance(record, dict) else None


def _attributable_session_markers(
    before: dict[str, int], after: dict[str, int], me: int, d: Path = _LIVE_SESSIONS_DIR,
) -> list[str]:
    """The markers written during the window ``before`` -> ``after`` by a hook
    whose parent was process ``me``: new or rewritten (mtime moved) AND carrying
    ``me`` as their pid. Every other marker is someone else's."""
    return sorted(
        name for name, mtime in after.items()
        if before.get(name) != mtime and _session_marker_pid(d / name) == me
    )


@pytest.fixture(autouse=True)
def _no_live_session_markers():
    """Fail a test whose spawned hook wrote a session marker into the LIVE tree."""
    before = _live_session_markers()
    yield
    me = os.getpid()
    mine = _attributable_session_markers(before, _live_session_markers(), me)
    kept: list[str] = []
    for name in mine:
        try:
            (_LIVE_SESSIONS_DIR / name).unlink()
        except OSError:
            kept.append(name)
    assert not mine, (
        "test ran a SessionStart hook against the LIVE tree: it wrote "
        + ", ".join(f".espalier-state/sessions/{n}" for n in mine)
        + f" with this pytest process ({me}) as the hook's parent. The operator's "
        "next banner would name that marker as a live sibling session for four "
        "hours, and the same run rewrote session_started and cleared the running "
        "session's gate counters. Drive the hook on the `self_host_tree_copy` "
        "fixture (a private copy of the initialized clone) or on tmp_path, never "
        "on REPO_ROOT. "
        + ("The marker has been removed." if not kept
           else "Could not remove " + ", ".join(kept) + "; delete it by hand.")
    )


# ── Marker taxonomy ─────────────────────────────────────────────────────────
# Filename pattern → marker assignment. Order matters: first match wins, so
# more specific patterns come first. Files not matching any rule default to
# `unit`. The `slow` marker is additive (added on top of the primary marker
# for the files in _SLOW_FILES). The taxonomy itself is declared in
# pyproject.toml [tool.pytest.ini_options].markers; see tests/README.md for
# the operator-facing description and how slices are run.
_MARKER_RULES: list[tuple[tuple[str, ...], str]] = [
    # security: write-guard, plan-guard, kill-switch, integrity, hook regression
    (
        (
            "test_write_guard",
            "test_write_guard_pattern_message_coupling",
            # Listed explicitly even though the `test_write_guard` prefix rule
            # above already classifies it (verified: collects under -m security,
            # deselects under -m unit). TestSecurityMarkerCoverage requires
            # explicit membership regardless of prefix inheritance.
            "test_write_guard_command_position",
            "test_write_guard_env_prefix_polarity",
            "test_write_guard_long_flags",
            # In-place sed/perl option-grammar tokenizer: drives the
            # protected-zone extractor over a DERIVED spelling population.
            "test_write_guard_sed_grammar",
            # The time budget: a judgment that outruns it is refused, never let
            # through when Claude Code's timeout cancels the hook.
            "test_write_guard_time_budget",
            # The role-map gate: anti-regression rows drive the catastrophic-rm
            # hard-deny and the protected-zone guard, so this belongs in the
            # security slice rather than the fast unit one.
            "test_bash_inert_syntax_mask",
            # Confinement contract for bench/reachability_differential.py, which
            # hands genuine recursive deletes to a real shell.
            "test_reachability_differential",
            # Liveness contract for bench/guard_metamorphic.py. Drives the guard
            # through `guard_tier` on both channels, so it belongs in the
            # enforcement slice beside its sibling gate.
            "test_guard_metamorphic",
            # Confinement + stand-down contract for the PowerShell differential.
            "test_powershell_reachability_differential",
            # The inert corpus -- the mirror of bench/corpus/. It drives the
            # hard-deny tier and the speed bump, so it belongs in the same slice
            # as the rest of the enforcement regression set.
            "test_guard_false_positives",
            "test_plan_guard",
            "test_plan_guard_branch_pinned",
            "test_plan_guard_adopter_config",
            "test_stop_gate",
            # The fail-open voice gate: every deciding except-handler in the hooks
            # speaks or declares its kind (an enforcement-slice sibling of the
            # guards it walks).
            "test_failopen_voice",
            # Its witnesses: each repaired hook driven in a scratch tree, the
            # advisory found inside the one stdout JSON object or as a record.
            "test_hook_voice_reaches_claude",
            # The spawn chokepoint: every spawn in the hooks is the chokepoint,
            # routed through it, or declared (the stop gate's spawns route).
            "test_spawn_chokepoint",
            "test_security_regression",
            "test_integrity",
            "test_hook_regression",
            "test_hooks",
            # DEF-743: both blocking guards driven inside a git worktree of the
            # repository (the prefix rule above classifies it too; the coverage
            # contract wants explicit membership).
            "test_hooks_worktree_checkouts",
            # TP-215 — post_compact BC-033 capture lock (hook regression).
            "test_post_compact_capture",
            "test_hook_contracts",
            "test_hook_protocol",
            "test_hook_utils",
            "test_json_dict_safe",
            "test_selfcheck",
            "test_hook_assertions_helpers",
            "test_hook_exec_form",
            "test_hook_matcher_precision",
            "test_hook_unicode_stdin",
            "test_reporter_hook_umbrella",
            "test_atomic_io",
            "test_audit_dir_home_unset",
            "test_reflect_trigger_concurrency",
            # The lock primitive's cross-process semantics and the three log
            # appends that rely on it, driven by concurrent child processes.
            "test_file_lock",
            "test_reflect_trigger_path_normalization",
            # TP-189-A — reflect drift -> agent additionalContext + blueprint inject
            "test_reflect_trigger_additionalcontext",
            "test_session_start_blueprint_inject",
            # source-aware blueprint-chain advancement (startup/clear vs resume/compact)
            "test_session_start_source_aware",
            # TP-157 157-F/G — tool-call + trajectory session signals
            # (hook regression: reflect_trigger counter + stop_gate reads).
            "test_session_signals",
            "test_subagent_stop",
            "test_subprocess_env_isolation",
            "test_task_router",
            "test_redos",
            "test_kill_switch_blocking_surfaces",
            # TP-330 — the three everyday enforcement denials append an audit record.
            "test_governance_audit_log",
            # TP-332 — /status --explain resolver, pinned to the enforcement predicates.
            "test_explain_path",
            "test_ci_guard",
            # red_team_guard — anti-theater re-execution guard for red-team blockers.
            "test_red_team_guard",
            "test_integrity_contract_parity",
            "test_protected_path_contract_parity",
            # forced cross-boundary constant parity (hook<->engine, scanner<->engine)
            "test_forced_copy_parity",
            "test_library_hook_parity",
            "test_self_host_detection_survives_write_guard_refactor",
            "test_hook_helper_consolidation",
            "test_hook_event_contracts",
            # TP-328 — hook-authoring SKILL.md <-> CANONICAL_HOOK_WIRING parity
            # (guards the doc hook authors read before wiring an enforcement hook).
            "test_hook_authoring_skill_parity",
            "test_sister_site_probe_regression",
            "test_sister_site_probe_synthetic",
            "test_sister_site_probe_unit",
            "test_sister_site_probe_ceilings",
            "test_sister_site_probe_scope",
            # DEF-673 -- the deployed probe driven on a real `init` tree: the
            # gate keys on the adopter's own duplicates, never the hooks'.
            "test_sister_site_probe_adopter_tree",
            "test_ci_yaml_hook_count",
            "test_stop_gate_dormancy",
            # TP-146 146-C — URL-scheme allowlist regression
            "test_external_fetch_scheme_validation",
            # TP-146 146-D — hook audit-swallow noqa annotation contract
            "test_hook_audit_noqa_annotations",
            # TP-175 R2 — review_agent_audit __main__-shim print exclusion
            "test_review_agent_audit",
            # TP-146 146-G — ruff HIGH-severity rule set pinning
            "test_ruff_config_includes_security_rules",
            # TP-321a — [tool.mypy] near-strict flag pinning (hook-gate fail-open guard)
            "test_mypy_config_stays_near_strict",
            # TP-147 147-A — canonical noqa template SoT
            "test_noqa_template_parity",
            # TP-147 147-F — MAINTENANCE_MODE constant adoption + WARN banner
            "test_maintenance_mode_constant_parity",
            "test_session_start_maintenance_warn",
            # TP-177 W6-3 — SessionStart WARN on an unresolved hook interpreter
            "test_session_start_interpreter_warn",
            # TP-345 — SessionStart ruff-banner self-host gate (adopter-friction parity)
            "test_session_start_ruff_gate",
            # TP-147 147-B — external-tool availability triple
            "test_external_tool_contract",
            # TP-149 149-B — cross-hook predicate parity (plan_guard /
            # task_router _has_active_plan) + bare-literal hook constant SoT.
            "test_hook_constant_parity",
            # TP-221 — archive-safety behavioral suite (ZIP-slip / tarbomb
            # extraction-guard regression; @pytest.mark.security).
            "test_archive_safety",
        ),
        "security",
    ),
    # release: packaging, artifact parity, version, benchmark, archive
    (
        (
            "test_release_pack",
            "test_release_archive_clean",
            "test_release_check",
            "test_no_tracked_release_noise",
            "test_artifact_parity",
            "test_release_surface_parity",
            "test_pre_release",
            "test_version_truth",
            "test_bench_parity",
            "test_benchmark_release_hygiene",
            "test_wheel_smoke",
            "test_wheel_install_surface_parity",
            "test_package_resource_parity",
            "test_release_archive_filtering",
            "test_final_release_matrix",
            "test_release_noise_parity",
            "test_release_archive_class_regression",
            "test_release_denylist",
            "test_release_check_tp37_semantics",
            "test_release_checklist_contract",
            "test_wheel_payload",
            "test_bench_results_parity",
            "test_bench_corpus_wiring_parity",
            "test_bench_attempt_env_honoured",
            "test_version_surfaces_parity",
            # TP-178 — tools/ vendor-move: byte-parity of the wheel-vendored
            # deploy source (espalier/_vendor/cc) against tools/cc.
            "test_vendor_cc_parity",
        ),
        "release",
    ),
    # contract: self-hosting, docs, surface-truth, generated-surface, public-claim
    (
        (
            "test_self_hosting",
            "test_managed_inventory",
            "test_manifest_truth",
            "test_clean_checkout_semantics",
            "test_public_surface_truth_docs",
            "test_operator_docs",
            "test_surface_contract",
            "test_command_surface_truth",
            "test_command_merge_contract",
            "test_contract_consumers",
            "test_contract_infrastructure",
            "test_contracts",
            # TP-453 2-B: every "declared limit" sentence in the shipped guard
            # docs cites a pytest node id that resolves and collects.
            "test_declared_limits_contract",
            # TP-448 Class 3: pins the >=3.10 interpreter floor, its two-copy
            # parity across the no-import boundary, and its derivation from
            # pyproject's requires-python.
            "test_python_floor",
            # The stubbed-PATH interpreter hosts (a Store-alias python3; a
            # launcher-only host) behave like the machines they stand for:
            # the shared oracle every interpreter-choosing surface is driven
            # under.
            "test_interpreter_hosts",
            # TP-448 Class 3: pins that --rewire-interpreter changes ONLY
            # argv[0] of a hook command and refuses rather than clobbers.
            "test_init_rewire_interpreter",
            "test_closed_loop_contract",
            # The adopter-axes registry: every (axis, value) cell names a
            # collecting node parametrised over its value, or declares its gap.
            "test_axis_registry",
            "test_state_transitions",
            "test_state_predicate_truth_tables",
            "test_maintenance_mode",
            "test_denial_reasons",
            "test_denial_reason_actionability",
            "test_adopter_message_hints",
            "test_marker_parity",
            # §C21 — the shared git oracle (tests/_git_oracle.py) plus the raw
            # platform behaviour it defends against, pinned as facts so the
            # guard cannot decay into ceremony.
            "test_git_oracle",
            # DEF-670 — the per-arm export guard (tests/_export_guard.py),
            # witnessed on a synthesized export because it is inert here.
            "test_export_guard",
            "test_severity_scales",
            "test_paths_consolidation",
            "test_paths_parity",
            "test_portability_contract",
            "test_render_surface",
            "test_render",
            "test_deploy_set_import_closure",
            "test_documented_claims",
            "test_agent_contracts",
            "test_handoff_truth",
            "test_test_suite_contract",
            "test_test_quality",
            "test_count_claims",
            "test_corpus_count_parity",
            "test_bench_corpus_schema",
            "test_audit_accuracy",
            "test_e2e_bench",
            "test_deny_markers",
            "test_lifecycle_parity",
            "test_cognitive_blueprint_schema_parity",
            "test_surface_support_matrix",
            "test_agent_frontmatter_contract",
            "test_surface_matrix_module",
            "test_pack_manifest",
            "test_scope_walker",
            "test_surface_impact",
            "test_surface_hygiene_parity",
            "test_cheat_sheet_no_internal_ids",
            "test_common_tier_agent_adopter_handoff",
            "test_common_tier_asset_availability",
            "test_shipped_commands_ascii_runtime",
            "test_settings_profile_fingerprint",
            "test_test_loosening_skip_precision",
            "test_session_start_toc_gating",
            "test_session_banner",
            "test_quickstart_doctor_example",
            "test_scaffolding_canon",
            "test_action_justifications",
            "test_deploy_doc_parity",
            # Every pointer in a deployed doc resolves on a DRIVEN init tree —
            # the deploy-context obligation four other gates scope out by name.
            "test_adopter_pointer_resolution",
            # Espalier's own standards must not be applied to adopter content:
            # drives the hidden CLI verbs on a foreign init tree.
            "test_adopter_verb_stand_down",
            # TP-137 §B/§C/§D — convergence-theater + stealth-contract +
            # canon-vs-claim pins.
            "test_surface_expected_witness_contract",
            "test_env_catalog",
            "test_execution_plan_schema_parity",
            "test_state_file_flag_parity",
            "test_state_dir_single_source",
            "test_subprocess_cli_contract",
            "test_canon_substantiates_claim",
            "test_scanner_convergence_theater",
            # TP-139 — generative stealth-contracts scanner trilogy
            "test_scanner_subprocess_contracts",
            "test_scanner_filesystem_contracts",
            "test_scanner_magic_depth",
            # DEF-792 — the whole-tree locale-following text I/O net
            "test_scanner_encoding_contracts",
            # TP-140 — generative doc-propagation closed-vocab scanner
            "test_scanner_retired_vocab",
            # TP-157 157-A/C/D — self-gov scanner telemetry/credibility/composition
            # (espalier-layer generated-surface contracts).
            "test_scan_telemetry",
            "test_scan_credibility",
            "test_scan_composition",
            # TP-203a A1 — run-boundaried fan-out finding ledger (espalier-layer
            # generated-surface contract; sibling of test_scan_telemetry).
            "test_finding_ledger",
            # TP-287 — scope-breaker + convergence-critic stage-presence contract
            # over committed .claude/workflows/*.js scaffolds (also full_tree below).
            "test_convergence_workflow_stages",
            # the launch conventions every committed scaffold shares: one model per
            # run (args.model through opts()), the finder-time refuter-field strip,
            # the lane-identity stamp (sibling of the stage-presence contract above).
            "test_workflow_launch_conventions",
            # phantom-citation contract — scans authoritative docs for backtick
            # tests/test_*.py citations, resolves each vs git ls-files (also full_tree).
            "test_doc_test_citations",
            # TP-328 — audit-excluded-doc partition completeness (pure constant
            # check) + the production-source citation contract for live-state maps.
            # The two are NOT symmetric, and the difference is load-bearing:
            # test_doc_source_citations spawns git ls-files and reads the
            # export-pruned registry, so it is in BOTH _SLOW_FILES and
            # _FULL_TREE_NODEIDS. test_doc_maintenance_classes is in NEITHER by
            # inheritance — its absence from _SLOW_FILES is exactly why it ran in
            # stage 02 and needed its own _FULL_TREE_NODEIDS entry (2026-08-14).
            "test_doc_maintenance_classes",
            "test_doc_source_citations",
            # the recall engine's pointer referents (pure file reads; a reworded
            # SHARP_EDGES heading must red in the docs-only tier)
            "test_reinject_pin_referents",
            "test_proof_tier",
            # TP-141 — canon-vs-claim verifier (env-gated)
            "test_canon_verifier_contract",
            # Core Rule #4 claim↔canon completeness pin (sibling of the verifier
            # contract — asserts the SessionStart-digest canon stays PINNED + the
            # handoff clause stays marked convention).
            "test_core_rule_4_canon_completeness",
            # TP-143 — scanner earn-the-gate fixtures (close FM-7)
            "test_scanner_exceptions",
            "test_scanner_prints",
            "test_scanner_test_loosening",
            "test_scanner_godfiles",
            "test_scanner_perf_smells",
            "test_scanner_freshness",
            "test_scanner_earn_the_gate_parity",
            # TP-156 — cross-scanner must-NOT-trip negative-corpus parity
            "test_scanner_negative_corpus_parity",
            # TP-144 — cross-scanner exempt-files disk-resolve contract
            "test_scanner_exempt_files_resolve",
            # TP-145 — cross-scanner PRAGMA_RE start-of-line anchoring
            "test_scanner_pragma_anchoring",
            # TP-146 — ruff HIGH-severity gate + lint-gate-as-regression-test
            # (`test_hook_audit_noqa_annotations` and
            # `test_ruff_config_includes_security_rules` live under
            # `security` per the filename-token classifier.)
            "test_cli_type_hints_resolve",
            "test_no_unsafe_tarfile_extractall",
            # TP-147 147-E — structural TOML parse contract
            "test_no_substring_on_structured_configs",
            # TP-147 147-G Part 2 — ESPALIER_MEMORY.md tag-parity gate
            "test_check_memory_md_tag_parity",
            # TP-148 148-C — shipped harness-guard.yml self-host gating
            "test_shipped_ci_asset_self_contained",
            # TP-149 149-F — FAILURE_MODES.md catalog self-consistency
            # (count word / TOC / coinage enumeration pins).
            "test_catalog_self_consistency",
            # fan-out finding schema-shape parity + coinage-vocab parser
            # (sibling canon to test_catalog_self_consistency).
            "test_fan_out_findings",
            "test_canon_vocab",
            "test_memory_anchor_freshness",
            "test_mcp_path_fields_parity",
            # TP-184 — no bare `espalier <verb>` in fusion-reachable runtime hints
            "test_no_bare_espalier_hints",
            # selfcheck mirror == curated tests/ subset (generated-surface parity)
            "test_selfcheck_tests_parity",
            # seed of the selfcheck host-agnostic engine-integrity truth set
            "test_engine_imports",
            # no bare module-level `import tomllib` (breaks Python 3.10 collection)
            "test_tomllib_import_contract",
            # TP-364 — every task-packs/Deferred/ pack is pinned to a
            # FORWARD_LEDGER.md row (folder<->ledger completeness contract;
            # self-host-gated, sibling of test_doc_test_citations).
            "test_forward_ledger_completeness",
            # folder CLAUDE.md pointer/anchor freshness net (link half + reused
            # line-anchor resolver; git ls-files population, fail-closed skip —
            # complements the router-shape contract in test_folder_claude_md_routers).
            "test_ladder_claudemd_pointers",
            # TP-416 — an in-flight pack asserting a state change about another
            # in-flight pack must be referenced back (pack<->pack reciprocity;
            # folder population, self-host-gated skip — the pack-side sibling of
            # test_forward_ledger_completeness, which binds ledger<->folder).
            "test_cross_pack_assertions",
            # every required status check a doc instructs resolves to a check-run
            # name GitHub can actually report (workflow-name / file-slug / bare
            # matrix-id are the three spellings that park a PR forever).
            "test_required_status_checks",
            # the record/claim axis agrees with every registry that declares a
            # record, so Core Rule 13's answer does not depend on which module
            # happened to ask it.
            "test_record_axis_reconciliation",
            # Classified 2026-08-24. Its `# pytest-marker: default-unit` sat
            # INSIDE the module docstring, so it was never a comment and never
            # a real opt-out -- test_marker_taxonomy's substring check forgave
            # it on the strength of prose. `contract` is what it always was:
            # the census polices test populations derived from the source they
            # police, which is a self-hosting truth test, and it is `slow`
            # besides.
            "test_derived_population_census",
            # Polices a property of the SOURCE tree (every settings.json reader
            # decodes BOM-tolerantly) rather than any one behaviour, which is
            # what makes it a contract rather than a unit test. Fast (~1.2s),
            # so deliberately NOT in _SLOW_FILES.
            "test_settings_reader_bom_contract",
            # The ledger's derived regions (headline, class index, Members(N),
            # Appendix B, probe roster) against its member rows. A generated-
            # surface truth test: it runs the generator's --check inside the
            # suite, which is what stops the generator from being an eighth
            # summary nobody runs.
            "test_generate_ledger_regions",
            # No shipped doc may claim a schedule its workflow lacks. A public-
            # claim truth test -- the class decayed twice in one day.
            "test_workflow_schedule_claims",
            # The bench surface carries no internal vocabulary (DEF-410k's
            # narrow arm): a tree-wide truth test over bench/**/*.md.
            "test_bench_surface_hygiene",
            # The two files that assert on the LIVE freshness manifest: the
            # hook-count literal at HEAD against the live wiring (plus the
            # drift probe behind it), and the seeded semantic fragments'
            # pins and bounds. A re-pin touches only the manifest and earns
            # the contract tier, so its readers live here or a re-pin lands
            # blind to them -- ff9eaff (2026-09-19) dropped the hook-count
            # literal and the file that reds on it sat in the security
            # roster (so `-m contract` never collected it) and in
            # _SLOW_FILES (so the fast slice never ran it): the pre-cut
            # review's D1.
            # Moved 2026-09-20 from the security roster and the TP-105 unit
            # grandfather; tests/test_proof_tier.py derives the population
            # and pins that every member is classified here.
            "test_freshness_hook_count_migration",
            "test_freshness_semantic_fragments",
            # Every HarnessConfig field has a consumer or a declared reason: a
            # census over the engine and hook sources from the repo root, plus
            # the live-tree pin that the self-host espalier.toml loads with no
            # unknown-key warning (DEF-950 / DEF-951).
            "test_config_fields_consumed",
            # The stack table: the engine copy's byte-mirror pin, the census of
            # hand lists that spell stack vocabulary across the shipped roots
            # (each derived, marked, or a dated baseline site), and the floor pin
            # that keeps the table's seed names.
            "test_stack_table",
        ),
        "contract",
    ),
    # integration: CLI, init, doctor, recovery, scanners, session-resume, worktree
    (
        (
            "test_cli",
            "test_cli_commands",
            # TP-149 149-G — `python -m espalier` entry-point smoke
            "test_main_module",
            "test_memory_autoprune",
            "test_init",
            "test_init_fresh_hooks",
            "test_init_managed_markers",
            "test_init_gitignore_protection",
            # DEF-410f: drives a real `init` on a scratch repo (git child processes);
            # redundant under the prefix-open `test_init` rule above, kept as an
            # explicit anchor that survives a later narrowing of that rule
            "test_init_fingerprint_differential",
            # Drives init, the handoff CLIs and the shipped Dead-Config pass as
            # children on a forced cp1252 pipe; its two static contracts carry
            # their own class-level contract marks.
            "test_utf8_text_io",
            "test_managed_cleanup_parity",
            "test_doctor",
            "test_recovery",
            "test_scanners",
            "test_session_resume",
            "test_worktree",
            "test_handoff",
            "test_reflect_protocol",
            "test_reflect_memory_candidates",
            "test_reflect_validators",
            "test_reflection",
            "test_reflect_link_guards",         # builds a temp surface repo + runs the standalone CLI
            "test_execution_plan",
            "test_execution_plan_cli",
            "test_execution_plan_auto_justification",
            "test_managed_paths",
            "test_cleanup",
            "test_diffing",
            "test_diffing_matrix",             # the drift matrix: real git in throwaway trees (also in _SLOW_FILES)
            "test_demo_end_to_end",
            "test_refresh_externals",
            "test_settings_profiles",
            "test_init_gitignore_default",
            # TP-189-A — non-Python init scanner-scope notice
            "test_init_nonpython_notice",
            "test_scanner_flat_out_path",
            "test_fuse",                       # TP-179 espalier fuse (real overlay + init)
            "test_merge_settings",             # B-1 merge-settings (subprocess CLI + real settings.json)
            "test_init_interactive_arming",    # in-process case-(b) interactive arming over _reconcile_existing_settings (real hook merge)
            "test_verify_landing",             # TP-185 W3 verify-landing (real git repo + subprocess CLI)
            "test_selfcheck_channel",          # selfcheck CLI + subprocess pytest against the bundled mirror
            "test_run_pack_chain",             # pack-chain driver: shells scripts/run_pack_chain.sh --dry-run with fixtures
            # ── Reclassified 2026-08-24: these spawn child processes ──
            # `unit` is declared as "pure function/model tests; no
            # subprocess", and each of these shells out, so `integration`
            # -- "subprocess, CLI, hook, filesystem, or rendered-surface
            # integration tests" -- is what they always were. Derived, not
            # hand-picked: the population is whatever
            # test_no_unit_module_spawns_a_child_process names. ONE
            # DIRECTION ONLY -- that contract reds if a spawning module is
            # left in `unit`; nothing asserts the converse, so a module here
            # that later stops spawning sits in this tuple until a human
            # notices. This comment claimed both directions until an
            # adversarial pass checked it.
            # NOTE the primary marker says what KIND of test this is; the
            # additive `slow` overlay says what it COSTS. SIX of these are
            # genuinely fast and stay in the `not slow` slice, so moving them
            # costs no coverage -- five carry a `# slow-exempt:` reason and
            # test_recall_calibration is simply absent from _SLOW_FILES.
            #
            # One SIDE EFFECT, checked and kept: matching here is prefix-open
            # (`stem.startswith(p + "_")`), so "test_recall" also captures
            # test_recall_calibration. That capture is CORRECT for its own
            # reason -- that module loads the live corpus off REPO_ROOT and
            # runs 246 queries against it, which is the "filesystem" arm of
            # `integration`, not "pure function/model". It was verified rather
            # than assumed; a prefix capture is not self-justifying, and the
            # complete before/after assignment map is how the rest were
            # checked for exactly this.
            "test_asset_shipping",
            "test_benchmark_pass_conditions",
            "test_blueprint_cold_demotion",
            "test_blueprint_schema_version",
            "test_cognitive",
            "test_cognitive_blueprint",
            "test_doc_regions",
            "test_edge_cases",
            "test_folder_claude_md_routers",
            "test_freshness_bound_invalidation",
            "test_freshness_ci_gate",
            "test_freshness_cli",
            "test_freshness_scanner",
            "test_freshness_state_cache",
            "test_freshness_unknown_policy",
            "test_git_archive_parity",
            "test_git_conventions_encoding",
            "test_golden_examples",
            "test_md_heading_anchors",
            "test_memory_sort_audit",
            "test_nested_repo_litter",
            "test_nested_repo_skip",
            "test_publish_workflow",
            "test_recall",
            # Named EXPLICITLY rather than left to the "test_recall" prefix
            # above: test_marker_taxonomy requires deliberate membership,
            # and an accidental capture is not a decision. It belongs here
            # on its own merits -- it loads the live corpus off REPO_ROOT.
            "test_recall_calibration",
            # Same explicitness: loads the live corpus off REPO_ROOT to hold the
            # three pasted recall counts to it (~1s; the handoff gate's
            # conditional member for corpus-root edits, 2026-09-09).
            "test_recall_pasted_counts",
            # Same reason, same explicitness: loads the live corpus off
            # REPO_ROOT and runs ~550 queries through both ranking paths via
            # scripts/recall_eval.py (exec_module, in-process, no direct
            # subprocess; the DEF-615 wording gate takes its tracked set from
            # tests/_git_oracle.py).
            # Measured 2026-09-04 (after the alpha sweep landed): the fast
            # slice is 54 tests in ~38s, three of them a full evaluate() at
            # ~6.5s each; the three `slow`-marked tests share ONE module-scoped
            # LENGTH_NORM_ALPHA sweep (~30s, timeout widened to 300s) and take
            # the module to ~72s. Comparable to test_recall_calibration on the
            # fast slice, so deliberately NOT in _SLOW_FILES.
            "test_recall_eval",
            "test_reinject",
            "test_reinject_sync",
            "test_reinject_pins",
            "test_session_start_freshness_banner",
            "test_speedbump_discard_snapshot",
            "test_speedbump_metacognitive",
            "test_speedbump_v1_1",
            "test_statusline",
            "test_statusline_freshness_segment",
            "test_sync_github_workflow_asset",
            "test_verify_pins",
            # Drives scripts/archive_transcripts.py through its real CLI
            # (subprocess) over a tmp_path tree, so it cannot be `unit` --
            # pyproject.toml's `unit` description says "no subprocess". Full stem,
            # NOT a "test_archive" prefix: matching is prefix-open and the
            # sibling test_archive_safety is deliberately `security`.
            "test_archive_transcripts",
            # Drives real `git init`/`clone`/`commit-tree`/`gc` against tmp_path
            # worktrees to pin the record-branch construction. Full stem, not a
            # "test_record" prefix: matching is prefix-open and would capture
            # any future test_record_* sibling that wants a different bucket.
            "test_record_snapshot",
            # Drives real `git init`/`commit` against tmp_path repos to pin the
            # co-author trailer check. Full stem, NOT a "test_check" prefix:
            # matching is prefix-open and would capture test_check_pack_landing,
            # which is correctly `unit`. (This comment also named
            # test_check_ledger_probes as `unit` until 2026-09-02; it now drives
            # git itself and is listed below on its own merits, so the prefix
            # warning stands but that half of its evidence does not.)
            "test_check_handoff_landing",
            # the three scripts landed together on 2026-09-06; each drives its
            # script by path against a scratch tree (a git repo, a fixture
            # ledger, a copied checkout), which is integration by this file's
            # own definition
            "test_handoff_mechanics",
            "test_ledger_row",
            # Drives tools/cc/record_merge.py through real `git merge` in a
            # bare-origin-plus-two-clones scratch repo (two machines' handoffs
            # colliding on the record files) and replays the live PR 88 x main
            # witness from this checkout's objects: real git is the oracle for
            # what a merge conflicts on, so no mock stands in for it.
            "test_record_merge",
            # Drives tools/cc/mail.py through real git in a bare-origin-plus-
            # clones scratch repo (a send under a scratch index, the push, the
            # other machine's fetch and read, the same-name refusal): the ref
            # mechanics are the thing under test, so no mock stands in.
            "test_mail",
            "test_symbol_census",
            # Seven cases in TestTheContaminationPopulationIsActuallyDerived
            # build throwaway `git init` repos and plant duplicate files in
            # them, to pin the contamination detector's DERIVATION half. Mocking
            # git hid both bugs that half actually shipped with -- a 3-segment
            # key that never matched a real staging layout, and a root-level
            # basename that matched `.pytest_cache/README.md` -- so the real
            # repos are the point. Full stem, not a "test_check" prefix, for the
            # reason given just above.
            "test_check_ledger_probes",
            # Builds a scratch repo with an orphan `record` ref carrying three
            # ledger snapshots and drives the trend script over it; the real
            # ref is the operator's session state and never in CI.
            "test_ledger_trend",
            # Drives the host-check runner's publish/read round trip on two
            # scratch clones of a bare local remote: the property under test
            # (the publishing checkout's branch, tree and index untouched;
            # the report under the same path on the other side) is git's
            # own behaviour, observable no other way.
            "test_host_check",
            # One scratch adopter tree driven through init, a hand edit and
            # re-init, scan, clean-generated --execute and doctor as real
            # subprocesses, the output read as an adopter reads it (the §C6
            # class: run the verb, read the output). The unit pins build the
            # same states by hand; this earns them through the verbs.
            "test_adopter_lifecycle_diagnostics",
            # The stack table, the fixtures that write its rows, and
            # build_adopter_tree at each depth: a real `git init` + commit, and
            # `init` + `install-ci` once per adopter stack.
            "test_stack_trees",
            # Drives scripts/fresh_clone_gate.py end to end on a scratch
            # repository: a real `git clone`, a real venv, a stub tier that
            # records the environment it saw -- the gate's own controls are
            # subprocess facts and cannot be pinned in-process.
            "test_fresh_clone_gate",
            # Drives scripts/archive_probe.py end to end on THIS checkout: a
            # real release archive, the DEF-670 seed, a real venv, one shipped
            # module run inside the extracted tree -- whether the work dir is
            # a seeded export is a subprocess fact (TP-455).
            "test_archive_probe",
            # One init'd tree per stack (Node and its Python control), then
            # the deployed /preflight fences under a real POSIX bash with
            # stub linters and runners first on PATH: which command a fence
            # runs is a subprocess fact.
            "test_node_adopter_defaults",
        ),
        "integration",
    ),
    # TP-105 grandfather: pre-existing test files frozen as `unit` at the
    # ship of TP-105. New tests should be deliberately classified above;
    # this list should chip down over time, not grow. The implicit
    # fallthrough below (line ~211) still works for forgotten additions —
    # tests/test_marker_taxonomy.py::TestMarkerTaxonomyMembership catches
    # those before they ship.
    (
        (
            "test_analyze",
            "test_analyze_user_tools_not_ignored",
            "test_audit_accuracy_freshness",
            "test_build_claude_md_uses_fingerprint",
            "test_categorized_memory_layout",
            "test_changelog_footer",
            "test_cli_deploy",
            "test_config",
            "test_corpus_documented_in_resolves",
            "test_detect_ml_surface_false_positives",
            "test_detect_ml_surface_true_positives",
            "test_exception_policy",
            "test_fingerprint",
            "test_freshness_cache_reader_parity",
            "test_freshness_marker_parser",
            "test_freshness_windows_compat",
            "test_harness_config",
            "test_implement_pack_step_zero",
            "test_init_summary_matches_filesystem",
            "test_deployed_assets_home_path_shapes",
            "test_init_tier_split",
            "test_init_upgrade_paths",
            "test_managed_markers",
            "test_memory_md_consistency",
            "test_memory_prune_cli",
            "test_models",
            "test_no_internal_codenames",
            "test_no_stale_gate_five_references",
            "test_non_python_consumer_init",
            "test_profiles",
            "test_proofs",
            "test_quickstart_tier_counts",
            "test_reflect_reasoning",
            "test_render_template",
            "test_repo_mode",
            "test_self_host_fingerprint_parity",
            "test_skill_delegation_parity",
            "test_skill_frontmatter",
            "test_skill_tier_contract",
            "test_marker_taxonomy",
            "test_rmtree",
        ),
        "unit",
    ),
    # everything else under tests/ defaults to unit (silent — caught by
    # test_marker_taxonomy.py before commit)
]


def _primary_marker(stem: str) -> str:
    """Resolve a test module stem to its ONE primary marker.

    The single implementation of the first-match-wins walk over
    ``_MARKER_RULES``. ``pytest_collection_modifyitems`` calls it, and so does
    ``tests/test_test_suite_contract.py``'s ``unit`` contract.

    It is a shared function rather than two copies on purpose. A contract that
    re-implements the walk is a copy of the dispatch, not a question put to it:
    the two agree on the day it is written and drift apart silently after --
    exactly the "derive the list, don't test a hand-written copy of it" shape
    this repo keeps paying for. Change the matching semantics here and every
    caller moves with it, or none does.
    """
    for patterns, marker in _MARKER_RULES:
        if any(stem == p or stem.startswith(p + "_") for p in patterns):
            return marker
    return "unit"

# slow is additive: any test that calls subprocess, builds a wheel, or runs
# git-heavy operations should also be marked slow on top of the primary marker.
_SLOW_FILES: set[str] = {
    # Drives SessionStart, the PostToolUse hooks, the Stop gate, post_compact
    # and subagent_stop as real children in scratch trees: the advisory has to
    # be found in the process's own stdout JSON or audit record.
    "test_hook_voice_reaches_claude",
    # Spawns eight appender children per site behind a start barrier, and a
    # locker child per primitive case: a real process tree on every OS.
    "test_file_lock",
    # The drift matrix drives real `git init` / `commit` in throwaway trees so
    # the commit-subject and ratio census is the detector's own reading, not a
    # string fixture. It lives in its own file so the pure normalizer rows in
    # test_diffing stay in the fast slice (2026-10-04).
    "test_diffing_matrix",
    # The git cases drive real `git init`/`commit` in tmp_path repos to pin the
    # co-author trailer check against actual commit objects rather than a
    # string fixture; the parser cases next to them are pure and fast.
    "test_check_handoff_landing",
    # Copies this checkout into tmp_path and drives `git init`/`add`/`commit`
    # plus the script's own git and probe subprocesses for the dry-run case;
    # ~1.3 s here, and a real process tree either way.
    "test_handoff_mechanics",
    # Builds a bare origin and two clones per case and drives real `git merge`
    # through them (plus `espalier memory prune` as a child for the cap step),
    # and clones this checkout once per live-witness replay.
    "test_record_merge",
    # Builds a bare origin and clones per case and drives real `git` through
    # them for every send and read (plus the CLI as a child process once).
    "test_mail",
    # Runs `git ls-files` per census and the census over the real tree once.
    "test_symbol_census",
    # Drives the real post_write_check hook once as a subprocess; the rest is
    # in-process against a tmp_path state dir.
    "test_reinject_pins",
    # Drives `git` in scratch repositories for every case.
    "test_proof_tier",
    # Spawns `espalier init`, three tools/cc CLIs and an agent-body heredoc as
    # children on a forced cp1252 pipe, each over a seeded scratch repository.
    "test_utf8_text_io",
    # Clones a scratch repository and builds a venv per end-to-end row.
    "test_fresh_clone_gate",
    # Builds the release archive from this checkout, seeds and installs it in
    # a venv, runs pytest inside it: one driven row, about a minute.
    "test_archive_probe",
    # Spawns the real hook once per corpus row, and TWICE for every tier row --
    # a soft speed-bump is deny-once-then-allow, so one invocation cannot tell a
    # bump from a wall. Mocking it would defeat the point: this file exists
    # because expectations, not the hook, were what was wrong.
    "test_guard_false_positives",
    # Drives `bench/reachability_differential.py` as a real subprocess, and its
    # oracle spawns `/bin/bash` per row to observe whether a victim directory was
    # genuinely deleted. Mocking the shell would defeat the entire purpose: the
    # gate exists precisely because expectations written by the author are what
    # failed to catch the defect it was built for.
    "test_reachability_differential",
    # Same shape: drives `write_guard` as a subprocess once per calibration
    # probe and runs the --quick matrix end to end.
    "test_guard_metamorphic",
    # Loads the PS differential and drives `guard_tier`; the end-to-end arm
    # additionally spawns a real `pwsh` where one exists.
    "test_powershell_reachability_differential",
    # §C21 — spawns real `git init`/`ls-files`/`check-ignore` against purpose-built
    # worktrees. A mock would only prove the helper branches on the rc I handed it;
    # the whole point is platform behaviour nobody predicts from the docs.
    "test_git_oracle",
    # Drives the real CLI in a subprocess against a driven adopter tree.
    "test_adopter_verb_stand_down",
    # TP-330 — invokes write_guard/plan_guard/session_resume as subprocesses to
    # assert each denial appends an audit record + tails it back.
    "test_governance_audit_log",
    # TP-332 — invokes session_resume.py --explain as a subprocess (submode test).
    "test_explain_path",
    # phantom-citation contract spawns `git ls-files` to resolve doc citations.
    "test_doc_test_citations",
    # TP-328 — source-citation sibling reuses the same git ls-files resolver.
    "test_doc_source_citations",
    # the ci-gated-paths block's carrier population is `git ls-files` (via
    # tests/_git_oracle.py), so this module spawns git the same way its two
    # citation-resolver siblings above do.
    "test_protected_path_contract_parity",
    # every control clones the repo and runs pytest twice in a child process --
    # the tool under test IS a subprocess driver.
    "test_verify_pins",
    # pack-chain driver tests shell scripts/run_pack_chain.sh (subprocess + a
    # repo-walking espalier scope-check per fixture).
    "test_run_pack_chain",
    # the inverted workflow mirror's sync: its dirty-file refusal is a real git
    # state, so each fixture inits and commits a throwaway repo.
    "test_sync_github_workflow_asset",
    "test_artifact_parity",
    "test_release_pack",
    "test_release_archive_clean",
    "test_release_check_tp37_semantics",
    "test_pre_release",
    "test_session_resume",
    "test_session_start_source_aware",
    "test_handoff",
    "test_init",
    "test_init_fresh_hooks",
    "test_init_managed_markers",
    "test_init_gitignore_protection",
    "test_managed_cleanup_parity",
    "test_clean_checkout_semantics",
    "test_demo_end_to_end",
    "test_wheel_install_surface_parity",
    "test_self_hosting",
    "test_memory_autoprune",
    "test_wheel_payload",
    "test_scanner_flat_out_path",
    "test_session_start_toc_gating",
    "test_quickstart_doctor_example",
    "test_stop_gate",  # TP-152 C-5: subprocess + heavy session fixture
    "test_git_conventions_encoding",  # TP-189 XPLAT-1: real git repos + child-process locale forcing
    # TP-189-B (PERF-2): every remaining child-process-spawning test module,
    # so `pytest -m "not slow"` is a fast in-process smoke slice. Pinned by
    # tests/test_test_suite_contract.py::test_every_subprocess_test_is_slow_or_exempt.
    "test_action_justifications",
    "test_asset_shipping",
    "test_audit_accuracy_freshness",
    "test_blueprint_schema_version",
    "test_ci_guard",
    "test_cli_commands",
    "test_cli_deploy",
    "test_init_fingerprint_differential",  # DEF-410f: real git + in-process init
    "test_cognitive",
    "test_cognitive_blueprint",
    "test_cognitive_blueprint_schema_parity",
    "test_contracts",
    # TP-448 Class 3: drives session_start.py and sh interpreter stubs
    # as child processes.
    "test_python_floor",
    # TP-448 Class 3: spawns sh interpreter stubs via --version probes.
    "test_init_rewire_interpreter",
    "test_documented_claims",
    "test_edge_cases",
    "test_execution_plan",
    "test_execution_plan_auto_justification",
    "test_execution_plan_cli",
    "test_execution_plan_schema_parity",
    "test_fan_out_findings",
    "test_freshness_bound_invalidation",
    "test_freshness_ci_gate",
    "test_freshness_cli",
    "test_freshness_hook_count_migration",
    "test_freshness_scanner",
    "test_freshness_state_cache",
    "test_freshness_unknown_policy",
    "test_fuse",
    "test_git_archive_parity",
    "test_golden_examples",  # TP-232: subprocess-drives `pytest examples/golden/`
    "test_hook_contracts",
    "test_hook_exec_form",
    "test_hook_helper_consolidation",
    "test_hook_matcher_precision",
    "test_hook_protocol",
    "test_hook_regression",
    "test_hook_unicode_stdin",
    "test_hooks",
    "test_post_compact_capture",
    "test_init_gitignore_default",
    "test_init_nonpython_notice",
    "test_init_summary_matches_filesystem",
    "test_init_tier_split",
    "test_init_upgrade_paths",
    "test_integrity",
    "test_kill_switch_blocking_surfaces",
    "test_main_module",
    "test_merge_settings",
    "test_nested_repo_skip",  # drives copytree + `git init`/`git add -A` on tmp trees
    "test_nested_repo_litter",  # spawns `git init` / `git worktree add` on tmp trees to plant nested-repo litter
    # DEF-743: `git worktree add` on tmp trees, then write_guard / plan_guard /
    # session_start / post_write_check driven as subprocesses inside the worktree.
    "test_hooks_worktree_checkouts",
    "test_plan_guard",
    "test_plan_guard_adopter_config",
    "test_recall",
    "test_reflect_memory_candidates",
    "test_reinject",
    "test_reinject_sync",
    "test_review_agent_audit",
    "test_scaffolding_canon",
    "test_scanner_exempt_files_resolve",
    "test_scope_walker",
    "test_security_regression",
    "test_session_signals",
    "test_session_start_freshness_banner",
    "test_session_start_interpreter_warn",
    "test_session_start_maintenance_warn",
    "test_settings_profiles",
    "test_sister_site_probe_regression",
    # One `git init` + `espalier init` per module, then the DEPLOYED probe as a
    # subprocess from the adopter's cwd -- the artifact, not the source tree.
    "test_sister_site_probe_adopter_tree",
    # `git init` + commit per depth case, and `init` + `install-ci` once per
    # adopter stack (five trees, about 5 s each on the Windows host).
    "test_stack_trees",
    # `init` on a Node tree and a Python one, then the deployed /preflight
    # fences under a real bash, a few interpreter starts each.
    "test_node_adopter_defaults",
    # Spawns real `git` against short-lived repos under tmp_path to prove the
    # bare-`checkout <path>` arm and the pre-discard snapshot round-trip.
    "test_speedbump_discard_snapshot",
    "test_speedbump_metacognitive",
    "test_speedbump_v1_1",
    "test_statusline",
    "test_statusline_freshness_segment",
    "test_subagent_stop",
    "test_subprocess_cli_contract",
    "test_subprocess_env_isolation",
    "test_task_router",
    "test_verify_landing",
    "test_wheel_smoke",
    "test_worktree",
    "test_write_guard",
    # TP-223 A — full-benchmark spawn via invoke_real_write_guard /
    # rb.main(["--update-canonical"]); 8.81s for
    # test_update_canonical_refuses_write_on_regression. Was leaking into
    # the `not slow` fast slice (classified `unit`, absent from _SLOW_FILES).
    "test_benchmark_pass_conditions",
    # Spawns nothing -- it `exec_module`s scripts/derived_population_census.py
    # and walks tests/**/*.py IN-PROCESS, once per earn-the-red arm. So the
    # AST subprocess detector was structurally blind to it while it sat in the
    # slice CI runs on every pull request, measured 2026-08-24 at ~46s, roughly
    # a quarter of that slice and ~70% of `-m "unit and not slow"`. Its own
    # `@pytest.mark.timeout(300)` had said so in the source all along; nothing
    # was reading that until
    # test_test_suite_contract.py::test_every_self_declared_slow_site_is_slow_or_exempt.
    "test_derived_population_census",
    # Every arm inits a throwaway repo and drives real `git` -- clone,
    # commit-tree, update-ref, archive, gc. The construction under test IS git
    # plumbing, so a mock would only prove the builder branches on the rc it
    # was handed; the properties worth pinning (a checkout staging onto the
    # working branch, a plain clone carrying an orphan ref) are git's own
    # behaviour, observable no other way.
    "test_record_snapshot",
}
# NOTE: test_archive_transcripts is deliberately NOT here. It spawns subprocesses
# and so needs the subprocess contract satisfied, but it does that with the
# `# slow-exempt:` idiom in its own module docstring rather than a _SLOW_FILES
# entry -- measured 1.2s for 30 cases. A red-team pass caught the first version
# in here: _SLOW_FILES deselects a module from `pytest -m "not slow"`, which is
# both the PR slice (.github/workflows/test.yml) and release_check.py's slice,
# so it would have removed the only mechanical coverage of a tool that DELETES
# files from every gate that runs before a merge. The contract only catches
# UNDER-marking; over-marking costs coverage silently.


# heavy_e2e is additive on top of `slow`: multi-minute end-to-end stages whose
# cost is REPEATED once per matrix cell while the property they prove is the
# same in every cell. Spawning the suite as a child was the original member's
# reason; it is not the defining one. What makes a test belong here is that
# running it an eighth time buys nothing.
#
# Keyed by test function name so `pytest -m "slow and not heavy_e2e"` runs the
# slow lane minus these worst-case stages. Pinned non-empty by
# tests/test_marker_parity.py::_parse_conftest_taxonomy.
#
# ⚠ THE DESELECTION IS IN THE RECIPES, NOT HERE. `scripts/proof_tier.py` puts
# `-m "not heavy_e2e"` on BOTH pytest lines of the full tier (one member lives
# in a serial-leg file), so the `test` and `test-serial` cells of a pull request
# never run these; `--heavy` drops the filter, and exactly two homes pass it --
# the floor-version `clean-checkout` cell and the fresh-clone gate's first
# resolved leg, once per cut. `.github/workflows/portability.yml` drops them on
# all three OSes; the release matrix's archive and sdist children deselect them
# too. A cheaper tier never ran them, and nothing runs on main after the merge
# (retiered 2026-09-25; the stages left the per-pull-request tier 2026-09-30,
# when the stage-one smoke measured 848 s of a 992 s parallel leg in a cell).
# A member added here is deselected everywhere those recipes run and still
# runs under a bare `pytest -q`; a member removed from this set runs in every
# cell again.
_HEAVY_E2E_TESTS: set[str] = {
    # About twelve minutes (a 604 s child not-slow leg measured 2026-09-23, plus
    # release_check and self-host): stage_source_checkout() spawns the suite as
    # a child (tests/test_final_release_matrix.py).
    "test_stage_one_source_checkout_smoke",
    # ~59s locally and multiple minutes on a 2-core runner: drives 203 derived
    # rows, each spawning a real `pwsh` plus two hook runs. It proves a property
    # of the GUARD, which does not vary by Python version or by host OS, and it
    # was executing in all five `test` cells AND all three `portability` jobs --
    # eight times per cycle, once at the macOS 10x multiplier. Measured 2026-09-01.
    "test_the_gate_completes_against_head",
    # ~60-90s: builds the release archive from this checkout, seeds it, makes
    # a venv, installs the dev extra and runs one module inside the extracted
    # tree (tests/test_archive_probe.py, TP-455).
    "test_the_probe_drives_this_checkout_into_a_seeded_export",
}


# full_tree is additive on top of the primary marker: tests that assert
# invariants which hold only against the full self-host dev tree — the
# committed cc/PACK_MANIFEST.txt byte-matches the renderer, ESPALIER_MEMORY.md anchors
# resolve, task-packs/ content is present, docs have zero
# broken links. Each reads content a shipping EXPORT intentionally prunes
# (.gitattributes export-ignore paths + get_release_excluded_prefixes), so off
# the full dev tree the same assertion fails for a benign reason. The release
# matrix selects `-m "not full_tree"` against the extracted tree so these are
# verified only where they are meaningful (the dev tree / a fresh clone / CI).
#
# Keyed by an `item.nodeid` substring so a single set marks at any granularity —
# a bare `file.py::` fragment marks the whole module, `file.py::Class` a whole
# class, `file.py::Class::method` one test. This is orthogonal to `slow`
# (relying on `slow` for export-safety was the accidental fragility TP-280
# found). Pinned non-empty by
# tests/test_marker_parity.py::_parse_conftest_taxonomy.
_FULL_TREE_NODEIDS: set[str] = {
    # ── SWEPT 2026-09-23 (TP-455 1-G): the self-expiry audit run over the WHOLE
    #    suite on a freshly built, DEF-670-seeded release archive
    #    (`python3 scripts/archive_probe.py --audit -- -q -rA -m full_tree -n 4`)
    #    read 54 failed / 89 passed: twenty-five registered fragments passing
    #    outright and six whole-module or class fragments passing in part. Each
    #    passing row was read for the stressor it exists to catch and whether
    #    the archive can still present it over a floored or derived population
    #    (premise 8 of the pack's Task 0 -- the same fence a new entry gets).
    #    TWENTY-ONE fragments LEFT, each live on the seeded tree: six in
    #    test_git_archive_parity.py (the DEF-670 seed retired their reason, "a
    #    tree that has no .git"; a builder leak would be tracked by the seed and
    #    red the index and HEAD-archive denylists; the required surface, the
    #    dangling-link floor of ~190 and the allowlist's dead entries read the
    #    shipped tree itself; the matcher census walks all 1113 tracked paths),
    #    the recall_eval retired-wording census, the folder routers, the
    #    task-packs asset parity, the reflection broken-links sweep, the
    #    enumerating-doc discovery, the lock-sentinel gitignore claim, the fuse
    #    overlay leak gate, four mirror-registry rows, two scanner-exempt
    #    registries and the frozen-anchor floor. FOUR STAY as vacuous there,
    #    not stale, with the reason rewritten beside each (three in (a), one in
    #    (b)); one more, the bimodal recall calibration in (b), was struck on
    #    its single green and restored by the failure-mode review. SIX
    #    fragments NARROWED to their twenty failing tests (test_convergence_
    #    workflow_stages 2, test_doc_source_citations 3, test_doc_test_citations
    #    1, test_finding_ledger 7, test_memory_anchor_freshness 1,
    #    test_release_checklist_contract 6). Fifty-eight fragments after.
    # Reads a doc the export prunes (docs/RELEASE_DECISIONS.md is export-ignore):
    # the revisit-label pin (2026-09-14). The maintenance-roster sweep left
    # 2026-09-26: its two atlas exclusions were dead entries, and without them it
    # passes on the extracted export (TP-457 3-A).
    "test_documented_claims.py::TestReleaseDecisionsRevisitLabel",
    # ── The 7 seeds (were @requires_self_host). Re-measured 2026-09-23 under
    #    the whole-suite audit on a seeded export (TP-455 1-G): three LEFT --
    #    the routers (derived from the shipped tree's own `git ls-files`, all
    #    ten resolve there), the task-packs asset parity (task-packs/CLAUDE.md
    #    ships since 2026-09-21) and the broken-links sweep (the shipped docs
    #    resolve; the artifact-link allowlist did that work) -- and two
    #    NARROWED to their failing tests: memory_anchor_freshness (the
    #    rotating-host assertion is a constant and passes anywhere) and
    #    finding_ledger below (15 of the class's 22 drive fixtures). ──
    "test_memory_anchor_freshness.py::test_memory_line_anchors_fresh",   # reads ESPALIER_MEMORY.md
    # The record merge's cap parity pin reads ESPALIER_MEMORY.md's own policy
    # sentence beside the hook's constant; the rest of its module builds its
    # trees under tmp_path (2026-10-05).
    "test_record_merge.py::TestMemoryCap::test_the_cap_read_from_this_checkout_is_the_hooks_constant",
    "test_memory_md_consistency.py::TestSessionLogSprintClaimsCoherent",
    # Both classes in that module read the live ESPALIER_MEMORY.md, so both are
    # marked. It was the "sole test class" until 2026-08-16b -- the note is kept
    # as the reason a whole-module `test_memory_md_consistency.py::` entry would
    # ALSO be correct here, and is the safer shape if a third class ever lands.
    "test_memory_md_consistency.py::TestSessionLogDatesAreSane",
    # test_finding_ledger.py::TestStandingCallerLedgerWiring left 2026-09-27: its seven
    # registrations read the .claude/workflows/ scaffolds, which ship on every surface
    # since they became the fourth deployed kind (no export-ignore row), so the module
    # reads no export-pruned content and the dev-only-chain audit measures it at zero.
    "test_manifest_truth.py::TestCommittedManifestMatchesRenderer::test_committed_file_byte_equals_renderer",
    # DEF-615's retired-wording census (test_recall_eval.py::
    #    test_no_live_tracked_file_carries_a_retired_wording) was registered
    #    here until 2026-09-23: it reads the tracked set through the git
    #    oracle (floor 100), so on the seeded export it sweeps the shipped
    #    subset and PASSES -- a live check there, swept out (TP-455 1-G).
    # ── 4 slow-shielded test_contracts siblings (TP-280 LATENT-2): read
    #    export-pruned content unguarded, latent only because `slow` keeps them
    #    out of stage-02. Mark explicit so export-safety is orthogonal to `slow`. ──
    #    The three TestFanoutSchemaParity siblings left 2026-09-27: they read the
    #    .claude/workflows/ scaffolds, which ship on every surface since they became
    #    the fourth deployed kind, and the registry audit on the seeded export
    #    (`archive_probe.py --audit`) read all three PASSED over the shipped three.
    "test_contracts.py::TestMemoryMdLineLimit::test_memory_md_within_cap",
    # test_convergence_workflow_stages.py left 2026-09-27 for the same reason: the
    # scaffolds it reads ship on every surface, and the audit measures it at zero.
    # phantom-citation contract — was a whole-module entry on the belief that the
    # export prunes tests/ to a subset. It does not (the archive ships every
    # tracked tests/ path) and on a seeded export the resolver answers: eleven
    # of twelve passed under the 2026-09-23 audit; the one that red stays.
    "test_doc_test_citations.py::TestSymbolResolution::test_syntax_placeholder_dotted_citation_is_exempt",
    # TP-328's source-citation rows left 2026-09-26: the registry they scanned
    # stayed in the archive at the seed, the coverage witness that named it retired,
    # and the two phantom witnesses drive a synthetic fixture and pass on the
    # extracted export (TP-457 3-A).
    # ── 4 modules the 2026-08-05 clone oracle proved export-hostile: each contains
    #    tests that read dev-tree-only content, so each reds on a `git archive`
    #    extraction (measured: the index carries 383 `tests/` paths, so the archive
    #    DOES ship them).
    #
    #    NOT the sdist: `MANIFEST.in` prunes `tests/` and re-includes exactly one
    #    NON-test helper, so an sdist ships zero collectible test modules and
    #    `stage_sdist` skips pytest outright (see `_shipped_test_modules` in
    #    scripts/final_release_matrix.py). Keep these two artifacts distinct — they
    #    have opposite test payloads, and conflating them is how the sdist stage
    #    stayed misdiagnosed.
    #
    #    Registered at TEST granularity, and the granularity is MEASURED, not
    #    reasoned. A `git archive` extraction was built, these modules were run
    #    against it with their registration removed, and exactly six tests failed
    #    (138 passed, 3 skipped). Registering the four whole MODULES — the first
    #    draft — would have suppressed 147 collected tests to suppress 6, dropping
    #    ~140 export-safe tests from the archive stage, including the
    #    `test_earn_the_red_*` twins that prove other guards still fire.
    #
    #    Two review passes each proposed a different, larger set by reading the
    #    code; the artifact disagreed with both. Notably
    #    test_session_banner.py needs NO entry (all 41 pass on an export) and
    #    test_catalog_self_consistency.py needs ONE, not the whole module —
    #    docs/FAILURE_MODES.md ships, so the anchor tests resolve there fine.
    #    If you extend this list, extend the measurement: rebuild the export and
    #    re-run, do not infer from imports.
    #
    #    Re-measured 2026-09-23 on a seeded export (TP-455 1-G): the four
    #    test_reinject_sync.py entries (the three mirror-census rows and the
    #    witness-path arm) PASSED -- every path the registry and the witness
    #    sets name ships, and the arms floor their populations and ask git
    #    through the oracle -- so they left; only the memory-sort arm below,
    #    which reads the pruned ESPALIER_MEMORY.md, keeps its entry. ──
    "test_memory_sort_audit.py::TestSuppressOnClean::test_live_repo_committed_half_is_clean",
    # NB test_catalog_self_consistency had an entry here until 2026-08-14. Its
    # target (test_bare_anchor_floor_counts_evaluated_anchors_not_regex_matches)
    # was deleted by 595409b on 2026-08-09; the fragment then matched 0 of 8223
    # collected nodeids — a false coverage claim that also kept the whole module
    # inside test_test_suite_contract's file-granular `marked_files`, immunising
    # its other 28 tests from that detector. The module learned the fail-closed
    # idiom itself (test_catalog_self_consistency.py:651) and passes on an export.
    # test_marker_parity now pins every fragment to exactly one live target, so a
    # deleted or renamed test reds here instead of rotting.
    # 2026-08-13 — docs/RELEASE_CHECKLIST.md became export-ignored (maintainer
    # ritual; see surface_contract._INTERNAL_FILENAME_PATTERNS), so this module's
    # three unconditional reads of it FileNotFoundError on an extraction.
    #
    # Was MODULE granularity, measured 2026-08-13 when the module held exactly
    # 3 tests, all three reading the checklist. It has 14 today: the 2026-09-23
    # audit read 6 failed / 8 passed on a seeded export (the eight drive
    # fixtures), so the entry is narrowed to the six that read the pruned doc.
    "test_release_checklist_contract.py::test_release_checklist_pushes_tags_before_gh_release_create",
    "test_release_checklist_contract.py::test_release_creation_commands_are_fenced",
    "test_release_checklist_contract.py::test_release_checklist_has_recovery_subsection",
    "test_release_checklist_contract.py::test_release_checklist_has_hotfix_cadence_section",
    "test_release_checklist_contract.py::test_first_publish_ordering_check_is_a_diff_before_the_commit_and_a_porcelain_read_after_the_suite",
    "test_release_checklist_contract.py::test_tier_3_runs_the_fresh_clone_gate_before_the_matrix_on_the_floor",
    # 2026-08-14 — the SIBLINGS of the entry above. `f29211c` export-ignored
    # docs/RELEASE_CHECKLIST.md and registered test_release_checklist_contract
    # for it; three other modules read the same pruned content and were missed the
    # same day. `02_source_archive` had been FAIL since.
    #
    # MEASURED against the real extracted release archive (not a `git archive`
    # proxy — the two disagree, see the source-tree-is-not-an-artifact footgun),
    # AND at two extraction locations, because the location changes the result:
    #   inside a worktree (dist/, where stage 02 extracts):  5 failed / 39 passed
    #   outside any worktree (a downloaded zip in ~/Downloads): 6 failed
    # The 6th is test_doc_regions' second git-shelling test; measuring only the
    # first location hides it. Measure BOTH, or a fix for one reads as a fix for
    # the other.
    #
    # PER-TEST granularity, because whole-module would suppress 39 export-safe
    # tests: test_doc_maintenance_classes 1 of 3, test_required_status_checks
    # 3 of 9, test_doc_regions 2 of 32 (handled at source, see below).
    #
    # These entries cover mechanism (a) ONLY: the test reads a pruned doc.
    #
    # test_doc_regions is deliberately NOT registered here, though it fails on an
    # export too — its mechanism is (b), shelling to `git ls-files`, which has TWO
    # branches a marker cannot tell apart: rc 128 (raises) with no worktree
    # up-chain, and rc 0 with ZERO ROWS when the export sits inside one — which is
    # where stage 02 extracts, under the gitignored dist/. Marking the one test
    # that asserts on emptiness left its sibling asserting over an empty
    # population and PASSING, i.e. a green contract that scanned no files. That is
    # fixed at the source instead (test_doc_regions._tracked_text_files now skips
    # fail-closed on both branches), which also keeps the module visible to
    # test_test_suite_contract's detector: `marked_files` is FILE-granular, so any
    # entry here immunises every sibling in that module from it.
    "test_doc_maintenance_classes.py::TestDeliberatelyAuditedInternalDocs::test_deliberately_audited_docs_stay_audited",
    "test_required_status_checks.py::TestRequiredStatusCheckNamesResolve::test_extractor_is_not_vacuous",
    "test_required_status_checks.py::TestRequiredStatusCheckNamesResolve::test_each_instructing_surface_still_matches",
    "test_required_status_checks.py::TestPopulationIsDerived::test_the_record_boundary_is_load_bearing",
    # ── §C21/`DEF-571` (2026-08-14) ──
    # This one did NOT arrive by measurement. It was silent at BOTH extraction
    # locations -- it swept an empty tracked set and passed -- so the two-location
    # diff that surfaced its four siblings was structurally blind to it; a static
    # census found it. Giving it the floor its sibling at :771 already had turned
    # the vacuous pass into an honest failure on an export (measured: 1 failed at
    # both locations, identically), which is what earns it this entry. It sweeps
    # every tracked .md+.py for bare line anchors, so an export -- which had no
    # git to enumerate -- could not answer it, while a fresh clone can. The
    # DEF-670 seed gave the export git; the floored population is met there and
    # the arm PASSED under the 2026-09-23 audit, so its entry left (TP-455 1-G).
    # The static-census note above stays as the record.

    # ── The slow lane, triaged 2026-08-14 ──────────────────────────────────
    # Measured, not reasoned: one freshly built release archive driven at TWO
    # extraction locations (outside any worktree, and under this repo's `dist/`)
    # in a per-location venv, plus a fresh `git clone` as the discriminator.
    # 29 failed on the export; the clone failed exactly ONE of them, which is
    # therefore a real defect and is NOT registered here (it is
    # test_quickstart_doctor_example, red on any uninitialized tree including
    # CI's own checkout). The other 28 are below.
    #
    # Granularity is per-test and per-PARAM throughout, because the 29 sit inside
    # 440 collected tests across 9 modules -- module-wide marking would suppress
    # ~400 export-safe siblings.

    # (a) Was "shells `git` at a tree that has no `.git`" -- eleven rows. The
    #     DEF-670 seed (2026-09-13) gave the export git, the rows ran, and the
    #     2026-09-23 audit (TP-455 1-G) found nine of them PASSING. Six of those
    #     left: on the seeded tree each still asks a question the archive can
    #     answer in the negative (a builder leak is tracked by the seed and reds
    #     the denylists; the surface, link and allowlist arms read the shipped
    #     tree; the matcher census walks every tracked path). Three STAY, for a
    #     reason the old comment did not state: the stressor each exists to
    #     catch is pruned by the builder BEFORE the archive exists, so on the
    #     export the question cannot come out negative -- a green there is the
    #     absent stressor, not expiry (premise 8 of the pack's Task 0).
    #       - export_ignores_internal_docs: a leaked internal doc would be
    #         re-pruned by the shipped .gitattributes inside the test's own
    #         `git archive`, so the members never carry it.
    #       - unregistered_sentinel_hatch_is_untracked_only: the hatch entry is
    #         export-ignored, so it cannot be tracked on the export whatever the
    #         dev tree does.
    #       - git_archive_ships_every_packaged_asset: an over-reaching pattern
    #         drops the asset before the census that would miss it.
    #     internal_classified FAILS under the audit (it censuses the dev tree's
    #     own index) and stays for the original reason. Its sibling claude_workflows
    #     left 2026-09-27: once the scaffolds became the fourth deployed kind the
    #     test asks whether the three tracked workflows ship on every surface, the
    #     seeded export carries all three, and the audit read it PASSED over them.
    "test_git_archive_parity.py::test_git_archive_export_ignores_internal_docs",
    "test_git_archive_parity.py::test_unregistered_sentinel_hatch_is_untracked_only",
    "test_git_archive_parity.py::test_no_internal_classified_tracked_file_ships_in_the_archive",
    "test_git_archive_parity.py::test_git_archive_ships_every_packaged_asset",

    # (b) Reads content an export intentionally prunes. Param-granular where the
    #     pruned file is one row of a larger declared population: ESPALIER_MEMORY.md
    #     is 1 of 10 EXPECTED_MEMORY_CAP_SITES and the only pruned one, so marking
    #     the whole test would silence NINE export-SAFE per-file checks (x2 tests
    #     = 18). The first draft of this comment said "1 of 7" and "six" -- a
    #     measured-sounding number nobody measured; len() says 10.
    "test_documented_claims.py::TestMemoryCapPopulation::test_declared_files_state_it_the_expected_number_of_times[ESPALIER_MEMORY.md]",
    "test_documented_claims.py::TestMemoryCapPopulation::test_every_declared_file_states_the_current_cap[ESPALIER_MEMORY.md]",
    # test_exclusions_are_still_needed PASSED under the 2026-09-23 audit and
    # STAYS: its exclusion list is empty today, so the pass is vacuous on both
    # trees (an assertion over no rows) -- the entry guards the exclusion the
    # test's own docstring says is owed again, which reads the pruned
    # ESPALIER_MEMORY.md (premise 8 of TP-455's Task 0: vacuous, not stale).
    "test_documented_claims.py::TestMemoryCapPopulation::test_exclusions_are_still_needed",
    "test_documented_claims.py::TestNoStaleNumericContracts::test_all_surfaces_agree[ESPALIER_MEMORY.md line cap]",
    # The two pattern-count contracts left 2026-09-26: their registry surface
    # (docs/REDEFINED_INFORMATION_REGISTRY.md, in the archive since the seed) left
    # the contracts, and both pass on the extracted export (TP-457 3-A).
    # TestScanSubmodesConsistent::test_every_enumerating_doc_is_in_the_population
    # left 2026-09-23: the discovery arm derives its population from the seeded
    # export's own tracked .md set (floored) and PASSED under the audit.
    "test_fuse.py::TestFuseEndToEnd::test_no_espalier_content_leak",
    # TestFuseManifestOverlay::test_no_internal_content_leaks_into_overlay left
    # 2026-09-23: three of its four arms (memory/, task-packs/, cc/) exercise
    # the overlay predicate on files that ship, and PASSED under the audit.
    # TestFuseManifestOverlay::test_every_standing_scaffold_overlays left 2026-09-27:
    # the seeded export tracks the three .claude/workflows/*.js since they became the
    # fourth deployed kind, every one overlays, and the audit read it PASSED there.
    # The recall pins left 2026-09-26 (TP-457 3-A): the corpus reads 314 on the clone
    # and on the extracted export (the four export-ignored corpus files stayed in the
    # archive at the seed), so the dev-versus-export gap these entries recorded no
    # longer exists; every pin was re-derived on this corpus and runs, and passes,
    # on both trees.
    # Copies THIS checkout and force-adds ESPALIER_MEMORY.md in the copy before
    # driving after-memory-row on it; the file is an export-ignore sentinel, so
    # on an export the force-add itself raises CalledProcessError at the
    # fixture line. Whole-test dependency, not one arm (DEF-670, 2026-09-13).
    "test_handoff_mechanics.py::TestDryRunOnThisTree::test_after_memory_row_dry_run_plans_without_writing",
    # Asserts THIS checkout is not an export, so the export guard is inert
    # here; on an export the same guard is live by design and the arm's
    # premise is false. Its siblings drive a synthesized export and run
    # everywhere (DEF-670, 2026-09-13).
    "test_export_guard.py::TestPrunedFromThisTree::test_inert_on_the_dev_tree",
    "test_session_start_toc_gating.py::TestMemoryDigestGating::test_self_host_repo_includes_memory_digest",
    # test_scanner_exempt_files_resolve.py's canon_verifier and retired_vocab
    # params, and test_fan_out_findings.py's lock-sentinel gitignore claim, were
    # registered here because each reaches the git question and an export had
    # no git to answer it (§C21). The DEF-670 seed gave it one: every exempt
    # entry resolves or is gitignored on the seeded export, the sentinel's
    # gitignore claim reads true against the shipped .gitignore, and all three
    # PASSED under the 2026-09-23 audit, so they left (TP-455 1-G). The
    # convergence_theater note survives as a caution: an exempt entry that is
    # export-ignored but NOT gitignored would red the param on an export with
    # the oracle's own diagnostic, and that red is a re-registration.

    # (c) The export stand-down is CORRECT behaviour and this asserts the dev-tree
    #     one: `run_self_host_check` returns `skipped_release_export` and the test
    #     requires source-checkout mode to report `pass`, which is its whole point.
    #
    #     ⚠ TWO SIBLINGS WERE REGISTERED HERE AND SHOULD NOT HAVE BEEN (removed
    #     2026-08-14 by the adversarial pass). `test_main_zero_on_passing_gate`
    #     had forked a FIFTH accept-set narrower than `GATE_STATUS_NON_FAILURES`;
    #     the export was correctly detecting that, and marking it silenced a true
    #     positive. `test_surface_gate_status_not_unknown_on_live_repo` asserted
    #     `== "pass"` where its own docstring named the `unknown` fallback as the
    #     subject; the weaker assertion holds on an export too. Registration is
    #     for a question the artifact CANNOT answer -- not for one it answers
    #     differently because the test was wrong.
    "test_self_hosting.py::TestSelfHostModeAwareness::test_source_checkout_mode_does_not_require_runtime_files",
    # ── The six rows the release matrix's stage 02 red on 2026-09-23 (DEF-916,
    #    TP-455), and the seventh its re-run found: six registered here at TEST
    #    granularity, measured on an extracted archive (build_release_archive +
    #    the DEF-670 seed + a venv; the five modules alone read 6 failed / 267
    #    passed before and 268 passed after, and every entry below is RED under
    #    ESPALIER_FULL_TREE_AUDIT=1, so each earns its place). The sixth of the
    #    first six, the checklist reader in test_record_snapshot.py, is GUARDED
    #    in place through tests/_export_guard.py -- its handoff.md half ships
    #    and keeps running on the export -- so it is deliberately not here; the
    #    seventh, (f) below, is the one red in this class that the matrix's
    #    re-run on the fixed tree reported (2 failed / 17397 passed, none of the
    #    first six among them).
    #
    #    (c) again: the twin of the row above. The latin1 manifest entry can
    #        only be reported missing by a gate that runs, and on an export the
    #        source-checkout gate stands down by design.
    "test_self_hosting.py::TestSelfHostModeAwareness::test_a_latin1_manifest_is_read_not_a_traceback",
    #    (d) A census of the tracked index through `git archive HEAD` for a
    #        local_only-classified member. Vacuous on both trees since the review
    #        scaffolds became the fourth deployed kind (nothing tracked classifies
    #        local_only; the audit read it PASSED on the seeded export, 2026-09-27),
    #        with the classifier on a synthetic task-packs/Done/ path as its only
    #        teeth. STAYS, not stale: the entry guards the day a local_only member
    #        is tracked again, when the dev tree censuses it and the builder prunes
    #        it before the export can ask.
    "test_git_archive_parity.py::test_no_local_only_classified_tracked_file_ships_in_the_archive",
    #    (e) left 2026-09-26: the recall pins (see the note above; corpus 314 on
    #        both trees, every pin re-derived, none registered).
    #    (f) The seventh row of this cohort, found by stage 02 itself on 2026-09-23 -- the first
    #        bare whole-suite run on an archive after the five above landed --
    #        in the file the same pack ADDED: the probe's dev-tree calibration
    #        asserts that THIS checkout is not an export, so the refusal its
    #        driven row depends on is live on the tree the probe builds from.
    #        On an extracted archive the checkout IS an export and the refusal
    #        correctly stays silent (the driven row proves that arm on a real
    #        export), so the row is a question the artifact cannot answer. Its
    #        shape is an export-detected behaviour, not a pruned-path read: one
    #        the file-granular contract does not claim (the 2026-08-14 decision),
    #        which is why stage 02, not the contract, is the oracle for it.
    "test_archive_probe.py::TestRefusals::test_this_checkout_is_not_an_export_so_the_guard_is_live_here",
}


def pytest_make_parametrize_id(config, val, argname):
    """A parametrize value longer than 64 characters is named by its argname
    and length, never by its text. Pytest exports each node id as the
    ``PYTEST_CURRENT_TEST`` environment variable, and a flood payload used as
    an id -- 328 ids over a kilobyte in tests/test_redos.py alone, some 30 KB
    -- exceeds Windows' 32,767-character environment limit: fourteen
    setup/teardown ERRORs on the first Portability run to finish the suite on
    windows-latest (2026-09-23). The label beside the payload stays the id's
    readable half; a short string is left to pytest's own rule."""
    if isinstance(val, str) and len(val) > 64:
        return f"{argname}~{len(val)}c"
    return None


def pytest_collection_modifyitems(config, items):
    # Is this collection running against a shipping EXPORT (self-host layout,
    # dev content pruned) rather than the dev tree? The `full_tree` marker lets
    # a runner we control select `-m "not full_tree"` (the release matrix does),
    # but a runner we DON'T control — release_check.py's opt-in `tests_pass`, a
    # bare `pytest` on an extracted archive, a future export consumer — would
    # otherwise RUN the full_tree tests against pruned content and fail. So on a
    # detected export we also auto-skip them here, once, at collection.
    # is_release_export is the CORRECT discriminator (is_self_host_repo is True
    # for an export too — the S2 trap) and is conservative: any uncertainty
    # returns False, so the dev tree / a fresh clone keeps running them.
    from espalier import surface_contract
    repo_is_export = surface_contract.is_release_export(REPO_ROOT)

    # SELF-EXPIRY. `_FULL_TREE_NODEIDS` has three arms asserting every fragment
    # points at something REAL, and none asking whether it still EARNS its
    # suppression. A registration whose reason has lapsed -- the pruned doc
    # starts shipping, the test is rewritten to drive a fixture -- goes on
    # skipping on every export forever, and "everything the archive can answer,
    # it answers" degrades silently. That is the same born-weak shape this
    # module keeps paying for, one level up.
    #
    # This is the oracle, and it has to be opt-in because the honest question
    # ("would it pass on a real export?") can only be asked ON a real export:
    #
    #     ESPALIER_FULL_TREE_AUDIT=1 python -m pytest -m full_tree -q
    #
    # run inside an extracted archive -- `python3 scripts/archive_probe.py
    # --audit -- -q -rA -m full_tree` builds, seeds and drives one from this
    # checkout (TP-455: the whole suite in about fifteen minutes, a named
    # module in under four). Registered tests then RUN instead of
    # skipping; every one that PASSES is a stale entry to delete -- once you have
    # checked that it asserts over a non-degenerate population there. A pass
    # whose stressor the builder prunes before the question is asked (a denylist
    # over members that cannot ship; an exclusion list that is empty today) is
    # vacuous, not stale, and stays with that reason written beside it (the
    # 2026-09-23 sweep kept four that way; TP-455's Task 0 calls it premise 8).
    # Failures are the expected, healthy result. Costs nothing on any normal
    # run, and unlike a derived check it works for all three registration
    # reasons (git-needs-a-worktree, pruned content, export-detected behaviour)
    # rather than only the one that is statically inferable.
    #
    # OFF an export the switch REFUSES rather than doing nothing: registered
    # rows would run on their own dev content, every one would pass, and a bare
    # `ESPALIER_FULL_TREE_AUDIT=1 pytest -m full_tree` pasted at the repo root
    # would read the whole registry as stale while measuring nothing (the
    # 2026-09-23 failure-mode review, F3). The probe asserts the export before
    # pytest; this closes the class for the bare paste.
    if os.environ.get("ESPALIER_FULL_TREE_AUDIT"):
        if not repo_is_export:
            raise pytest.UsageError(
                "ESPALIER_FULL_TREE_AUDIT=1, but this tree is not a release export "
                "(surface_contract.is_release_export is False): the audit measures "
                "nothing here -- every registered row would run on its own dev "
                "content and read as stale. Drive it through `python3 "
                "scripts/archive_probe.py --audit -- -q -rA -m full_tree`."
            )
        repo_is_export = False

    _export_skip = pytest.mark.skip(
        reason=(
            "full_tree invariant: repo_root is a release export (dev content "
            "pruned); asserted on the dev tree / a fresh clone, not a shipping "
            "export"
        )
    )

    for item in items:
        stem = item.path.stem
        item.add_marker(_primary_marker(stem))
        if stem in _SLOW_FILES:
            item.add_marker("slow")
        if item.name in _HEAVY_E2E_TESTS:
            item.add_marker("heavy_e2e")
        if any(frag in item.nodeid for frag in _FULL_TREE_NODEIDS):
            item.add_marker("full_tree")
            if repo_is_export:
                item.add_marker(_export_skip)


@pytest.fixture
def python_repo(tmp_path):
    """Minimal Python project with known patterns. The `python` row of tests/_stack_trees.py."""
    write_stack(tmp_path, "python")
    # cmd_init pre-flight requires .git/. Mark as a git directory
    # (empty marker is sufficient — pre-flight only checks existence).
    (tmp_path / ".git").mkdir(exist_ok=True)
    return tmp_path


@pytest.fixture
def ml_repo(tmp_path):
    """Minimal ML project. The `ml` row of tests/_stack_trees.py."""
    write_stack(tmp_path, "ml")
    (tmp_path / ".git").mkdir(exist_ok=True)  # cmd_init pre-flight.
    return tmp_path


@pytest.fixture
def node_repo(tmp_path):
    """Minimal Node.js project. The `node` row of tests/_stack_trees.py."""
    write_stack(tmp_path, "node")
    (tmp_path / ".git").mkdir(exist_ok=True)  # cmd_init pre-flight.
    return tmp_path


@pytest.fixture
def typescript_repo(tmp_path):
    """Minimal TypeScript project (non-Python consumer fixture). The `typescript` row of tests/_stack_trees.py."""
    write_stack(tmp_path, "typescript")
    (tmp_path / ".git").mkdir(exist_ok=True)  # cmd_init pre-flight.
    return tmp_path


@pytest.fixture
def go_repo(tmp_path):
    """Minimal Go project (non-Python consumer fixture). The `go` row of tests/_stack_trees.py."""
    write_stack(tmp_path, "go")
    (tmp_path / ".git").mkdir(exist_ok=True)  # cmd_init pre-flight.
    return tmp_path


@pytest.fixture
def polyglot_repo(tmp_path):
    """Python-primary + TypeScript-secondary polyglot fixture. The `polyglot` row of tests/_stack_trees.py."""
    write_stack(tmp_path, "polyglot")
    (tmp_path / ".git").mkdir(exist_ok=True)  # cmd_init pre-flight.
    return tmp_path


@pytest.fixture
def harness_repo(python_repo):
    """Python repo with a complete CC harness surface deployed for testing.

    Creates all required files so audit, doctor, recover, diff, cleanup, and
    render tests have a consistent baseline. Uses a minimal harness_config
    (empty agents / stable_actions) to avoid LIVE_SURFACE content-check failures
    while still satisfying every structural proof gate.
    """
    import json
    from espalier.analyze import fingerprint_repo
    from espalier.config import load_config

    # ── .claude/ ──────────────────────────────────────────────────────
    claude_dir = python_repo / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    # TP-169 §13 #8 (N7): wire the four blocking governance hooks under their
    # canonical events so the fixture is a *faithful* initialized harness — the
    # deleted-event completeness oracle (doctor._check_governance_event_wiring)
    # must see a valid baseline here, then fail only when a test deletes a key.
    from espalier.harness_config import CANONICAL_HOOK_WIRING as _chw

    def _gov_hook(script: str, matcher: str = "") -> dict:
        entry: dict = {"hooks": [{
            "type": "command",
            "command": "python3",
            "args": [f"${{CLAUDE_PROJECT_DIR}}/tools/cc/hooks/{script}"],
        }]}
        if matcher:
            entry["matcher"] = matcher
        return entry

    (claude_dir / "settings.json").write_text(
        json.dumps({
            "permissions": {"allow": ["Read", "Write"]},
            "hooks": {
                "SessionStart": [_gov_hook("session_start.py")],
                "PreToolUse": [
                    _gov_hook("write_guard.py", "*"),
                    _gov_hook("plan_guard.py", "Write|Edit|NotebookEdit"),
                ],
                "ConfigChange": [_gov_hook("config_guard.py")],
                "Stop": [_gov_hook("stop_gate.py")],
                # DEF-619: the reporter tier is in the wiring oracle now
                # (doctor WARNS on a deployed reporter with no executable
                # wiring), so the fixture wires every reporter it puts on disk
                # below -- session_start above, these three here; four of the
                # eight -- exactly as N7 made it wire the four gates. Add a
                # reporter script to the hooks-dir loop and it needs a wiring
                # here too, or every doctor test on this fixture warns. The
                # matchers are read from the SoT rather than typed.
                "PostToolUse": [
                    _gov_hook("post_write_check.py",
                              _chw["post_write_check.py"]["matcher"]),
                    _gov_hook("reflect_trigger.py",
                              _chw["reflect_trigger.py"]["matcher"]),
                ],
                "PostCompact": [_gov_hook("post_compact.py")],
            },
        }, indent=2) + "\n",
        encoding="utf-8",
    )

    # ── Root docs ─────────────────────────────────────────────────────
    (python_repo / "CLAUDE.md").write_text(
        "# Test — Governance Harness\n\nSession context loaded by hook.\n",
        encoding="utf-8",
    )
    (python_repo / "ESPALIER_MEMORY.md").write_text(
        "# Test — Project Memory\n\n## Session Log\n\n| Date | What |\n|------|------|\n",
        encoding="utf-8",
    )

    # ── cc/ ───────────────────────────────────────────────────────────
    cc_dir = python_repo / "cc"
    cc_dir.mkdir(parents=True, exist_ok=True)
    (cc_dir / "blueprints").mkdir(parents=True, exist_ok=True)
    for fname in [
        "LIVE_SURFACE.md", "COMMANDS.md",
    ]:
        (cc_dir / fname).write_text(
            f"<!-- espalier:managed -->\n# {fname.replace('.md', '')}\n",
            encoding="utf-8",
        )

    # ── tools/cc/ ─────────────────────────────────────────────────────
    tools_dir = python_repo / "tools" / "cc"
    tools_dir.mkdir(parents=True, exist_ok=True)
    # cognitive_blueprint.py carries the managed marker (matches real deploy behaviour)
    (tools_dir / "cognitive_blueprint.py").write_text(
        "#!/usr/bin/env python3\n# espalier:managed\n"
        "import sys\nsys.exit(0)\n",
        encoding="utf-8",
    )
    (tools_dir / "reflect_protocol.py").write_text(
        "#!/usr/bin/env python3\n# espalier:managed\nprint('OK')\n", encoding="utf-8"
    )
    (tools_dir / "execution_plan.py").write_text(
        "#!/usr/bin/env python3\n# espalier:managed\nprint('OK')\n", encoding="utf-8"
    )
    (tools_dir / "session_resume.py").write_text(
        "#!/usr/bin/env python3\n# espalier:managed\nprint('OK')\n", encoding="utf-8"
    )
    hooks_dir = tools_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    for hook in [
        "session_start.py", "write_guard.py", "post_write_check.py",
        "reflect_trigger.py", "stop_gate.py", "post_compact.py",
        # TP-169 §13 #8 (N7): the two remaining blocking governance hooks, so
        # the fixture is a faithful initialized harness — the deleted-event
        # oracle keys on "file on disk but event unwired".
        "plan_guard.py", "config_guard.py",
    ]:
        (hooks_dir / hook).write_text(
            "#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n", encoding="utf-8"
        )

    # ── Fingerprint AFTER all surface files are present ───────────────
    config = load_config(python_repo)
    fp = fingerprint_repo(python_repo, config)

    # ── reports/ ─────────────────────────────────────────────────────
    reports_dir = python_repo / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "repo_fingerprint.json").write_text(
        json.dumps(fp.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    # Minimal harness_config: empty agents / stable_actions / generated_docs
    # so audit's LIVE_SURFACE and generated-doc checks pass trivially.
    harness_data = {
        "repo_name": fp.repo_name,
        "profiles": list(fp.languages[:1]) if fp.languages else [],
        "agents": [],
        "stable_actions": {},
        "generated_docs": [],
        "read_only_zones": [],
        "mutable_zones": [],
        "unresolved_questions": [],
        "notes": [],
        "hooks": [],
        "config": config.to_dict(),
    }
    (reports_dir / "harness_config.json").write_text(
        json.dumps(harness_data, indent=2) + "\n", encoding="utf-8"
    )
    # Pre-populate cc_surface_gate.json so recover check sees it as present
    (reports_dir / "cc_surface_gate.json").write_text(
        json.dumps({"status": "pass", "summary": {"errors": 0, "warnings": 0}, "findings": []},
                   indent=2) + "\n",
        encoding="utf-8",
    )

    # ── PACK_MANIFEST (must list every managed file in control roots) ─
    (cc_dir / "PACK_MANIFEST.txt").write_text(
        "# espalier:managed\n"
        "CLAUDE.md\nESPALIER_MEMORY.md\n"
        ".claude/settings.json\n"
        "cc/LIVE_SURFACE.md\ncc/COMMANDS.md\ncc/PACK_MANIFEST.txt\n"
        "tools/cc/cognitive_blueprint.py\n"
        "tools/cc/execution_plan.py\n"
        "tools/cc/reflect_protocol.py\n"
        "tools/cc/session_resume.py\n"
        "tools/cc/hooks/session_start.py\n"
        "tools/cc/hooks/write_guard.py\n"
        "tools/cc/hooks/post_write_check.py\n"
        "tools/cc/hooks/reflect_trigger.py\n"
        "tools/cc/hooks/stop_gate.py\n"
        "tools/cc/hooks/post_compact.py\n"
        "reports/repo_fingerprint.json\nreports/harness_config.json\n"
        "reports/cc_surface_gate.json\n",
        encoding="utf-8",
    )

    return python_repo


@pytest.fixture(scope="session")
def initialized_repo_root(tmp_path_factory):
    """Session-scoped fresh-clone of REPO_ROOT with `espalier init` applied.

    The runtime artifacts the live self-host surface depends on
    (`.claude/settings.json`, `reports/repo_fingerprint.json`,
    `reports/harness_config.json`, `.espalier/integrity.json`) are
    gitignored — a fresh clone (and CI) lacks them. This fixture clones
    REPO_ROOT into a tmp directory and runs `init` against the copy so
    the artifacts exist.

    Use this fixture, not REPO_ROOT, for tests that exercise the
    self-host surface (doctor, release_check, surface_contract.discover_*,
    current_surface_report). Reserve REPO_ROOT for tests
    whose intent is "this must hold of the source tree as committed"
    (e.g. version-truth, no-tracked-release-noise).
    """
    import shutil

    from espalier._safe_walk import is_own_git_repo, visible
    src = Path(__file__).resolve().parent.parent
    dst = tmp_path_factory.mktemp("initialized_repo") / "tree"

    # Mirror the source tree's *working state* (not HEAD) so the fixture
    # works during in-flight renames where the working tree has changes
    # not yet committed. Excludes gitignored runtime artifacts so the
    # tree shape still matches a fresh clone.
    _excluded_top = {
        ".git", ".venv", "venv", "env", "dist", "build", "node_modules",
        "zDone", "Finished Tasks", "receiver-test",
    }
    # A cache directory is created beside every imported module, so its name
    # has to be checked at every depth; in the root-only set above it matched
    # nothing below the root and every nested cache rode into the fixture
    # (the DEF-481 shape, second site, 2026-09-13).
    _excluded_anywhere = {
        "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    }
    _excluded_paths = {
        ".claude/settings.json", ".claude/settings.local.json",
        "cc/BLUEPRINT_HANDOFF.md", "cc/execution_plan.json",
        "docs/session-archive.md",
    }
    _excluded_subtrees = {
        "reports", "cc/blueprints", ".espalier-state", ".espalier",
        "bench/results", "bench/end_to_end/runs",
    }

    def _ignore(path: str, names: list[str]) -> set[str]:
        rel = Path(path).resolve().relative_to(src.resolve())
        skip: set[str] = set()
        if rel == Path("."):
            skip |= _excluded_top
        for n in names:
            # `*.egg-info` at any depth too: a build in the live tree clears and
            # rewrites the top-level one, and on 2026-10-05 (Windows, 8 workers)
            # it vanished while this copy was listing the root -- eight ERRORs
            # on one worker. The suite's builds now stage a copy (DEF-1138);
            # the two hand-run builds still write the root, so the reader
            # skips the name rather than trusting the writers.
            if n in _excluded_anywhere or n.endswith(".egg-info"):
                skip.add(n)
                continue
            relfile = (rel / n).as_posix()
            if relfile in _excluded_paths or relfile in _excluded_subtrees:
                skip.add(n)
            # An embedded git repo is a foreign project: copying its `.git`
            # makes `git add -A` choke (an *empty* nested repo dies with exit
            # 128) and pollutes the fixture tree. Skip any subdir that is its
            # own repo. This generalizes the reactive one-name-at-a-time scratch
            # denylist above; the `zDone`/`Finished Tasks`/`receiver-test` entries
            # stay put — they are not verified to carry a `.git` marker (TP-277).
            if is_own_git_repo(Path(path) / n):
                skip.add(n)
        return skip

    shutil.copytree(src, dst, ignore=_ignore)
    # TP-88: bootstrap categorized-memory folders so the convention test
    # passes under the isolated-repo fixture even before content migrates.
    (dst / "memory").mkdir(exist_ok=True)
    (dst / "docs" / "sharp-edges").mkdir(parents=True, exist_ok=True)
    # Init a clean git repo so checks like `git ls-files` work.
    subprocess.run(["git", "init", "-q"], cwd=str(dst), check=True)
    # DEF-1168 (§C28, 2026-10-06): a fixture repo never runs a background git.
    # `commit` spawns `maintenance run --auto`, which detaches a repack when
    # it has work; a per-test copy of this tree (`self_host_tree_copy`) listed
    # `.git/objects/pack/` and found a `tmp_pack_*` gone before it could copy
    # it (#123's `test (3.14)` cell, the writer never reproduced locally). One
    # writer per shared state: the only process that writes this `.git` is the
    # fixture's own foreground command. Pinned by a GIT_TRACE of the build.
    for key, value in (("gc.auto", "0"), ("gc.autoDetach", "false"), ("maintenance.auto", "false")):
        subprocess.run(["git", "config", key, value], cwd=str(dst), check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=str(dst), check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "fixture-baseline"],
        cwd=str(dst), check=True, capture_output=True,
    )

    # Snapshot the agent set before init so we can prune profile-driven
    # additions. Init detects ml_repo / data profiles in the espalier
    # tree (bench fixtures import torch, etc.) and deploys
    # `data-engineer.md` + `experiment-analyst.md` on top of the canonical
    # six committed agents. The shape-invariant tests assert the live
    # canonical set; the fixture must end up with that set, not init's
    # superset.
    agents_dir = dst / ".claude" / "agents"
    agents_before = {p.name for p in visible(agents_dir.glob("*.md"), agents_dir)} if agents_dir.exists() else set()

    # Run init so the gitignored runtime artifacts are produced.
    result = subprocess.run(
        [sys.executable, "-m", "espalier.cli", "init", "."],
        cwd=str(dst), capture_output=True, text=True, timeout=120, encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"espalier init failed in initialized_repo_root fixture "
            f"(rc={result.returncode}):\nstdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    pruned_any = False
    for agent_md in visible(agents_dir.glob("*.md"), agents_dir):
        if agent_md.name not in agents_before:
            agent_md.unlink()
            pruned_any = True

    if pruned_any:
        # TP-03: write_required_surface now regenerates managed cc/ docs
        # (PACK_MANIFEST.txt etc.) on init, including any profile-driven
        # agents init deployed. Pruning them post-init leaves the manifest
        # promising files that no longer exist; re-render so the manifest
        # reflects the pruned state. Pre-TP-03 init skipped existing managed
        # files, hiding the issue — that was a bug per TP-03 §3.
        from espalier.render_surface import write_required_surface
        write_required_surface(dst)

    return dst


@pytest.fixture
def self_host_tree_copy(initialized_repo_root, tmp_path_factory) -> Path:
    """A private copy of ``initialized_repo_root``, one per test, for tests that
    DRIVE the deployed SessionStart hook on the self-host surface.

    A SessionStart writes session state wherever it is rooted -- the session
    marker the banner reads, the ``session_started`` stamp, the gate counters a
    non-continuation start clears, and on source ``startup`` a blueprint node --
    so it must run neither on the shared clone (every later test would see that
    state) nor on REPO_ROOT (the live tree: the operator's banner named the
    test's marker as a live sibling session, 2026-10-05; the
    ``_no_live_session_markers`` guard now reds that). Per test, not per module,
    so no test starts on the previous test's session state (one writer per
    shared state). Cost: about 48 MB and 2,300 files with its ``.git`` (kept, so
    the banner's git-backed lines take their real shape), a copy-on-write clone
    on APFS and a real copy on ext4 -- a read-only test takes the shared
    ``initialized_repo_root`` instead. The copy is made from the fixture, not
    from REPO_ROOT, so a build running beside the suite cannot false-red it
    (docs/SHARP_EDGES.md, the ``copytree(REPO_ROOT)`` entry). Same shape as
    ``driven_banner`` in test_quickstart_doctor_example.py, which points back here.
    """
    import shutil

    copy = tmp_path_factory.mktemp("driven_self_host") / "tree"
    # The copy is a READER of the fixture's `.git`: the fixture forecloses the
    # one background writer it spawns (`initialized_repo_root`, DEF-1168), and
    # git's own temp names (`tmp_pack_*`, `tmp_idx_*`) are skipped here so a
    # writer that trace could not see loses a transient, never the copy.
    shutil.copytree(initialized_repo_root, copy, symlinks=True,
                    ignore=shutil.ignore_patterns("tmp_pack_*", "tmp_idx_*"))
    return copy


@pytest.fixture(scope="session")
def adopter_tree(tmp_path_factory):
    """A FOREIGN repo with `espalier init` applied — the adopter's real tree.

    Deliberately not `initialized_repo_root` above, and the two are not
    interchangeable. That fixture clones *this* repo before running init;
    seeds are skip-if-exists, so the self-host `docs/SHARP_EDGES.md` (4,295
    lines) and `docs/CONVENTIONS.md` (1,999) survive and the Tier-3 stubs an
    adopter actually receives are never written. Use `initialized_repo_root`
    for "the self-host surface behaves"; use this for "what does a stranger
    get". `_adopter_tree.assert_is_adopter_tree` enforces the difference
    mechanically rather than by comment.

    Session-scoped: one `git init` + `cmd_init` for the whole run.
    """
    from _adopter_tree import build_adopter_tree

    return build_adopter_tree(tmp_path_factory.mktemp("adopter"))


@pytest.fixture
def as_self_host_tree(monkeypatch):
    """Make `is_self_host_repo` answer True for the duration of a test.

    Three CLI verbs (`provenance`, `pre-release`, `release-pack`) stand down
    off the Espalier-Harness source tree, because each was measured applying
    Espalier's own standards, vocabulary or branding to an adopter's content.
    That gate is correct, and it makes a synthetic `tmp_path` / `harness_repo`
    fixture an ADOPTER tree by construction — `is_self_host_repo` needs five
    signals including a content-hash pin on write_guard.py, which no fixture
    reproduces.

    So a test that means "the packaging/gate logic behaves" must SAY it is
    standing on the self-host tree, rather than passing because the stand-down
    did not exist. Use this only for that; a test asking "what does a stranger
    get" must use `adopter_tree` and must NOT patch this.

    Consequence worth knowing rather than rediscovering: with the stand-down in
    place, `cmd_release_pack`'s `files_written == 0` refusal is reachable only
    on a self-host tree, since every other input is refused earlier.
    """
    from espalier import surface_contract

    monkeypatch.setattr(surface_contract, "is_self_host_repo", lambda _root: True)
