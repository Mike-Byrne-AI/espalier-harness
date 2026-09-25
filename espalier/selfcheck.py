"""Espalier self-check surfaces — two distinct, complementary gates.

``espalier/selfcheck.py`` carries two entry points that close different gaps the
presence-based checks (``audit``, ``doctor``, ``integrity``) leave open:

  * ``run_selfcheck(repo_root)`` — runs the BUNDLED host-agnostic
    engine-integrity tests against the INSTALLED engine. Catches an installed/
    fused engine *regressing* (a relaxed scanner rule, a broken language
    detector). The curated tests build synthetic ``tmp_path`` repos; they never
    read the adopter tree, so this stays green on a synthetic empty repo.

  * ``run_contracts(repo_root)`` — runs three DYNAMIC/PARITY contracts
    against the adopter's DEPLOYED harness (C-1/C-2/C-3 below). Unlike
    ``run_selfcheck`` these READ the adopter tree (the deployed ``write_guard``
    hook, the package-side vendor hooks, the live settings), so they only pass
    on a tree that actually carries a deployed harness — that is why they are a
    SEPARATE entry point and are NOT folded into ``run_selfcheck`` (folding them
    would red on a synthetic empty repo, breaking the selfcheck channel's
    contract). They are reached as ``espalier selfcheck --contracts <repo>``
    (wired 2026-09-12, DEF-735: for a year they shipped importable, tested and
    unreachable, and the first drive on an adopter tree found C-2 comparing raw
    bytes against a copy the deploy had marked).

The three contracts and the gap each closes:

  * C-1 LIVE DENY-PATH       — ``espalier audit`` checks file PRESENCE and
                               ``espalier doctor`` PARSES settings wiring; neither
                               RUNS write_guard to confirm it still DENIES.
  * C-2 UPSTREAM PARITY      — ``integrity verify`` hashes against a LOCALLY
                               sealed manifest (drift-from-init); this hashes the
                               deployed hooks against the INSTALLED PACKAGE
                               (drift-from-upstream).
  * C-3 LIVE KILL-SWITCH     — ``ci_guard`` scans COMMITTED settings only; a live
                               gitignored ``disableAllHooks: true`` is invisible
                               to it. This reads the LIVE file.

Architecture: espalier/ imports espalier/ only — it MUST NOT import the
tools/cc hook modules. C-1 SUBPROCESSES the deployed hook (it does not import
it); C-3 re-states the kill-switch marker set with a pinned-parity comment.
espalier+stdlib-only by self-discipline: pytest is shelled out as a subprocess,
never imported at module top, so this stays importable without a runtime pytest
dependency.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from importlib.resources import as_file, files
from pathlib import Path

from espalier._safe_walk import safe_rglob
from espalier.managed_markers import has_managed_marker


def run_selfcheck(repo_root: Path) -> int:
    """Run the bundled engine-integrity tests against the installed engine.

    Resolves the mirror from the installed package (source checkout or wheel),
    runs pytest against it in a throwaway working directory so the adopter repo
    is never the pytest rootdir, and returns pytest's exit code. The bundled
    tests construct their own synthetic repos; ``repo_root`` is accepted for a
    consistent command signature but is intentionally not read here.
    """
    # Hand the running espalier's import root to the subprocess. The bundled
    # tests `import espalier`, but the subprocess runs with cwd=work (a throwaway
    # dir, NOT the repo root), so it cannot pick espalier up off the cwd the way a
    # bare `python -m pytest` from a source checkout would. Without this the
    # channel works ONLY when espalier is pip-installed and fails with
    # ModuleNotFoundError on a source checkout — the env-relative-green trap.
    # Prepending the parent of THIS package dir makes the subprocess import the
    # same espalier the CLI runs as; it is a no-op when espalier is already
    # importable (installed). cwd stays the throwaway dir so the adopter tree is
    # still never the pytest rootdir.
    pkg_parent = str(Path(__file__).resolve().parents[1])
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = pkg_parent + os.pathsep + existing if existing else pkg_parent
    if importlib.util.find_spec("pytest") is None:
        # pytest ships as an optional [dev] extra, so a runtime-only install
        # can't run the bundled tests. Say so plainly rather than surfacing the
        # subprocess's bare "No module named pytest".
        print(
            "espalier selfcheck: pytest is required to run the bundled tests but "
            "is not installed.\n"
            "  Install it with:  pip install pytest   "
            "(or, once the package ships:  pip install 'espalier-harness[dev]')",
            file=sys.stderr,
        )
        return 1
    with as_file(files("espalier").joinpath("_vendor", "selfcheck_tests")) as mirror:
        with tempfile.TemporaryDirectory() as work:
            print(
                f"espalier selfcheck: running bundled engine-integrity tests "
                f"from {mirror} (adopter repo tree not read)"
            )
            proc = subprocess.run(  # decode-errors-ok: no pipe is captured; stdout and stderr are inherited, nothing is decoded
                [sys.executable, "-m", "pytest", str(mirror), "-q"],
                cwd=work, text=True, encoding="utf-8", env=env,
            )
    return proc.returncode


# ═══════════════════════════════════════════════════════════════════════════
# Adopter-side DYNAMIC + PARITY contracts (C-1 / C-2 / C-3).
# These READ the adopter tree; aggregate via run_contracts (NOT run_selfcheck).
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class CheckResult:
    """Structured pass/fail for one contract — NOT a pytest assertion."""
    name: str
    passed: bool
    detail: str = ""
    failures: list[str] = field(default_factory=list)


# ── C-1: live deny-path ──────────────────────────────────────────────────────

# Mirrors the deny contract in tools/cc/hooks/write_guard.py::deny (a deny is
# exit 0 + stdout JSON, permissionDecision == "deny") and the stdin shape
# asserted by tests/test_write_guard.py::run_bash_guard. PARITY-PINNED: if the
# hook's deny JSON schema changes, this reader and that test both move together.
def _run_deployed_write_guard(
    payload: dict, repo_root: Path, *,
    project_dir: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Subprocess the DEPLOYED write_guard.py with PreToolUse stdin JSON.

    Returns (returncode, stdout). The script is ALWAYS resolved from ``repo_root``
    (the adopter tree that carries the deployed hook). ``CLAUDE_PROJECT_DIR`` is
    ``project_dir`` when given, else ``repo_root`` — these MUST be separable: the
    kill-switch sub-probe runs the REAL deployed hook (``repo_root``) but points
    it at a throwaway project dir carrying a planted kill-switch (``project_dir``)
    so the gate trips without the real hook living in that temp tree.
    ESPALIER_MAINTENANCE_MODE is popped so the protected-zone check actually runs
    (maintenance mode bypasses it — see tools/cc/hooks/_maintenance_mode.py).
    """
    script = repo_root / "tools" / "cc" / "hooks" / "write_guard.py"
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir if project_dir is not None else repo_root)
    env.pop("ESPALIER_MAINTENANCE_MODE", None)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8", errors="replace",
        timeout=30,
        env=env,
    )
    return proc.returncode, proc.stdout


def _is_deny(returncode: int, stdout: str) -> bool:
    """True iff the hook emitted a protected-decision deny (exit 0 + JSON)."""
    if returncode != 0 or not stdout.strip():
        return False
    try:
        parsed = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(parsed, dict):
        return False
    hso = parsed.get("hookSpecificOutput", {})
    return isinstance(hso, dict) and hso.get("permissionDecision") == "deny"


def check_live_deny_path(repo_root: Path) -> CheckResult:
    """C-1: confirm the DEPLOYED write_guard still DENIES the three core
    bypass classes. Fills the gap left by `espalier audit` (presence-only)
    and `espalier doctor` (parses wiring, never runs the hook).

    Note (attribution): write_guard's kill-switch gate runs BEFORE the
    dangerous-bash and protected-zone checks (write_guard.py
    scan_for_kill_switches). If the adopter's LIVE .claude/settings.json carries
    a kill-switch, all three sub-probes deny via that gate rather than the layer
    each targets, and _is_deny() does not inspect the deny reason — so C-1 still
    passes (a deny is a deny), intentionally redundant with C-3, which separately
    catches the live kill-switch. This is the accepted residual (toolbelt frame);
    C-3 is the precise signal for a live kill-switch.
    """
    script = repo_root / "tools" / "cc" / "hooks" / "write_guard.py"
    if not script.is_file():
        return CheckResult(
            "C-1 live-deny-path", passed=False,
            detail=f"deployed hook not found: {script}",
            failures=[f"missing: tools/cc/hooks/write_guard.py under {repo_root}"],
        )

    failures: list[str] = []

    # (a) protected-zone write
    rc, out = _run_deployed_write_guard(
        {"tool_name": "Write",
         "tool_input": {"file_path": ".claude/settings.json", "content": "x"}},
        repo_root,
    )
    if not _is_deny(rc, out):
        failures.append("protected-zone write (.claude/settings.json) was NOT denied")

    # (b) dangerous bash
    rc, out = _run_deployed_write_guard(
        {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
        repo_root,
    )
    if not _is_deny(rc, out):
        failures.append("dangerous bash (rm -rf /) was NOT denied")

    # (c) set kill-switch — write a temp settings.json carrying disableAllHooks
    #     and point CLAUDE_PROJECT_DIR at it (project_dir=ks_root) while still
    #     running the REAL deployed hook from repo_root. The hook's kill-switch
    #     gate fires on ANY tool call (write_guard.py: scan_for_kill_switches →
    #     deny), so a benign Write to a non-protected path is enough to trip the
    #     gate. Using a temp project dir is deliberate: it earns the red WITHOUT
    #     mutating the adopter's real settings.
    with tempfile.TemporaryDirectory() as td:
        ks_root = Path(td)
        (ks_root / ".claude").mkdir()
        # Throwaway probe settings, deleted with the temp dir — NOT a
        # cross-module coordination contract, so it carries no schema-parity
        # pin. (Bound to a local so the write is not mis-read as a stealth
        # structured-file contract by the filesystem_contracts scanner, which
        # only traces inline path-literal write targets.)
        ks_settings = ks_root / ".claude" / "settings.json"
        ks_settings.write_text(
            json.dumps({"disableAllHooks": True}), encoding="utf-8",
        )
        rc, out = _run_deployed_write_guard(
            {"tool_name": "Write",
             "tool_input": {"file_path": "src/app.py", "content": "x"}},
            repo_root, project_dir=ks_root,
        )
        if not _is_deny(rc, out):
            failures.append("set kill-switch (disableAllHooks: true) was NOT denied")

    return CheckResult(
        "C-1 live-deny-path", passed=not failures,
        detail="deployed write_guard denies protected-write / dangerous-bash / kill-switch"
        if not failures else "deployed write_guard FAILED to deny a core bypass class",
        failures=failures,
    )


# ── C-2: upstream parity ──────────────────────────────────────────────────────

def _package_vendor_hooks_dir() -> Path | None:
    """Locate the installed-package espalier/_vendor/cc/hooks dir.

    Mirrors cli._deploy_source_path's wheel branch (tools/cc/<rest> →
    espalier/_vendor/cc/<rest>). selfcheck.py lives in espalier/, so the
    vendor tree is a sibling subtree under this package directory.

    Filesystem-path assumption: resolves via Path(__file__).parent, which is
    fine for a normal site-packages / editable / source-checkout install. A
    zipimport/zipapp install would not yield a real path — there the dir does
    not resolve and C-2 cleanly SKIPS (returns None → passed=True), rather than
    false-failing. Do not reach for importlib.resources unless a zipapp target
    is in scope (the contract fails-safe as written).
    """
    here = Path(__file__).resolve().parent  # espalier/
    vendor = here / "_vendor" / "cc" / "hooks"
    return vendor if vendor.is_dir() else None


def _hook_py_files(root: Path) -> dict[str, bytes]:
    """Map of relative .py path -> bytes under root, excluding __pycache__.

    Mirrors tests/test_vendor_cc_parity.py::_py_files (the self-host parity
    test) so the adopter contract matches the self-host one. Uses safe_rglob
    (not bare rglob) because this is a shipped surface that may walk an adopter's
    tools/cc/hooks tree — safe_rglob guards the dir-symlink-loop ELOOP class."""
    return {
        str(p.relative_to(root)).replace("\\", "/"): p.read_bytes()
        for p in safe_rglob(root, "*.py")
        if "__pycache__" not in p.parts
    }


def _decoded(raw: bytes) -> str:
    """The text of a hook file for the marker test; undecodable bytes survive
    the round trip (surrogateescape) so a non-UTF-8 file is judged, not skipped."""
    return raw.decode("utf-8", errors="surrogateescape")


def _without_deploy_marker(raw: bytes) -> bytes:
    """``raw`` minus the ``# espalier:managed`` line ``init`` prepends to every
    hook copy (on the line after a shebang when there is one). The test is the
    marker contract's ANCHORED one (``has_managed_marker`` on that one line),
    not a substring test, so a first line that merely mentions the token (a
    docstring about the contract) is kept. Applied to BOTH sides of the
    compare: idempotent, and a source hook that carries an anchored marker
    itself (init would not add a second) still matches its copy. A leading
    BOM is dropped so the shebang is seen, as the canon drops it anyway."""
    text = _decoded(raw)
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.splitlines(keepends=True)
    at = 1 if lines and lines[0].startswith("#!") else 0
    if len(lines) > at and has_managed_marker(lines[at]):
        del lines[at]
    return "".join(lines).encode("utf-8", errors="surrogateescape")


def _deployed_hook_basenames() -> frozenset[str]:
    """The hook files ``init`` ships, from the packaged surface's own owners
    (entry scripts and helpers), never a hand list here."""
    from espalier.asset_inventory import get_packaged_surface
    surface = get_packaged_surface()
    return frozenset(surface.hook_entries.paths) | frozenset(surface.hook_helpers.paths)


def check_upstream_parity(repo_root: Path) -> CheckResult:
    """C-2: deployed tools/cc/hooks/*.py must be identical to the
    installed-package espalier/_vendor/cc/hooks/*.py in the manifest's
    canonical text form (DEF-725: the deployed tree is git-tracked, so a
    checkout git re-ended to CRLF must not read as drift from a wheel pip
    never re-ends). Fills the gap left by `integrity verify` (hashes a
    LOCALLY sealed manifest, not the upstream package — a deployed hook
    edited AND re-sealed reads green there)."""
    # The canon has one owner, the hook module, reached through the bridge
    # (which backfills it on a pre-canon module); a function-level import
    # keeps this leaf module's import graph as it was.
    from espalier._integrity_bridge import load_integrity_module
    deployed_dir = repo_root / "tools" / "cc" / "hooks"
    if not deployed_dir.is_dir():
        return CheckResult(
            "C-2 upstream-parity", passed=False,
            detail=f"deployed hooks dir not found: {deployed_dir}",
            failures=[f"missing: tools/cc/hooks/ under {repo_root}"],
        )
    vendor_dir = _package_vendor_hooks_dir()
    if vendor_dir is None:
        # No installed package vendor tree (e.g. a zipapp install where the path
        # does not resolve). Skip rather than false-fail.
        return CheckResult(
            "C-2 upstream-parity", passed=True,
            detail="no installed-package _vendor/cc/hooks to compare against - skipped",
        )

    deployed = _hook_py_files(deployed_dir)
    vendor = _hook_py_files(vendor_dir)
    failures: list[str] = []

    # The compare is in the DEPLOYED form, not raw bytes. Until 2026-09-12
    # this contract had only ever run on the self-host tree, where the
    # deployed hooks ARE the package source; driven on a fresh adopter init
    # every hook read as drifted, because `init` prepends the managed marker
    # to each copy and the package carries an `__init__.py` the deploy never
    # ships (DEF-735). So: the marker the deploy added is stripped before
    # hashing; a package-only file is drift only when the deploy ships it;
    # a deployed-only file is drift only when it carries the marker (a
    # harness-written file the package no longer has) -- an unmarked one is
    # the adopter's own, as `clean-generated` reads ownership too. On the
    # self-host tree the deployed hooks ARE the package source and carry no
    # marker, so there every deployed-only file is drift: a hook added
    # without `scripts/sync_vendor_cc.py`.
    from espalier import surface_contract
    shipped = _deployed_hook_basenames()
    self_host = surface_contract.is_self_host_repo(repo_root)
    only_deployed = sorted(
        rel for rel in set(deployed) - set(vendor)
        if self_host or has_managed_marker(_decoded(deployed[rel]))
    )
    only_vendor = sorted(rel for rel in set(vendor) - set(deployed) if rel in shipped)
    if only_deployed:
        failures.append(f"deployed-only hook files (not in package): {only_deployed}")
    if only_vendor:
        failures.append(f"package-only hook files (not deployed): {only_vendor}")

    canon = load_integrity_module().canonical_text_bytes
    mismatched = sorted(
        rel for rel in (set(deployed) & set(vendor))
        if hashlib.sha256(canon(_without_deploy_marker(deployed[rel]))).digest()
        != hashlib.sha256(canon(_without_deploy_marker(vendor[rel]))).digest()
    )
    if mismatched:
        failures.append(f"deployed hooks drifted from the installed package: {mismatched}")

    return CheckResult(
        "C-2 upstream-parity", passed=not failures,
        detail="deployed hooks byte-match the installed package"
        if not failures else "deployed hooks drifted from the installed package",
        failures=failures,
    )


# ── C-3: live kill-switch absence ─────────────────────────────────────────────

# Settings files the LIVE kill-switch check reads. PARITY-PINNED with
# tools/cc/hooks/_integrity.py (espalier cannot import the hook module —
# restated here). C-3 reads the LIVE file (possibly gitignored), which
# ci_guard.scan_committed_kill_switches cannot see. C-3 deliberately covers the
# two VALUE-marker kill-switches (disableAllHooks / bypassPermissions); the
# structural empty/no-op-hooks markers _integrity._find_kill_switches also
# detects are committed-config tampering owned by ci_guard + integrity, not the
# live-absence check. The parity test (test_c3_marker_parity_with_integrity)
# pins the two-marker agreement.
_SETTINGS_CANDIDATES = (
    ".claude/settings.json",
    ".claude/settings.local.json",
)


def _find_kill_switch_markers(rel_path: str, data: dict) -> list[str]:
    """Re-states the value-marker subset of
    tools/cc/hooks/_integrity._find_kill_switches (disableAllHooks: true,
    permissions.defaultMode == bypassPermissions). PARITY-PINNED: if that source
    changes either value-marker, mirror it here (covered by a parity test in
    tests/test_selfcheck.py)."""
    findings: list[str] = []
    if data.get("disableAllHooks") is True:
        findings.append(f"{rel_path}: disableAllHooks: true")
    permissions = data.get("permissions")
    if isinstance(permissions, dict):
        mode = permissions.get("defaultMode")
        if isinstance(mode, str) and mode == "bypassPermissions":
            findings.append(f'{rel_path}: permissions.defaultMode: "bypassPermissions"')
    return findings


def check_live_kill_switch_absent(repo_root: Path) -> CheckResult:
    """C-3: assert no kill-switch in the LIVE settings files. Fills the gap
    left by `ci_guard.scan_committed_kill_switches` (committed-only — a live,
    gitignored settings.json is invisible to it)."""
    failures: list[str] = []
    for rel in _SETTINGS_CANDIDATES:
        path = repo_root / rel
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError):
            # Deliberately NOT a failure, and the reasoning is worth stating
            # because the bare "surfaces elsewhere" comment that used to sit
            # here was an unverified claim of exactly the kind this harness
            # distrusts. C-3 asks one narrow question: is a kill switch LIVE
            # right now? Claude Code cannot parse this file either, so
            # disableAllHooks is not in effect and the honest answer is no.
            #
            # The parse failure is not swallowed, and here is where it does
            # surface, so the claim is checkable rather than reassuring:
            #   - SessionStart reports it (_integrity.scan_for_kill_switches
            #     with include_unreadable=True), the first thing a session sees;
            #   - ci_guard.scan_unreadable_settings fails the merge on a
            #     COMMITTED one, even with the approval marker.
            continue
        if isinstance(data, dict):
            failures.extend(_find_kill_switch_markers(rel, data))
    return CheckResult(
        "C-3 live-kill-switch-absent", passed=not failures,
        detail="no kill-switch in live settings"
        if not failures else "live kill-switch detected",
        failures=failures,
    )


# ── aggregate ─────────────────────────────────────────────────────────────────

def run_contracts(repo_root: Path) -> int:
    """Run all three adopter-side contracts (C-1/C-2/C-3); print a structured
    report; return 0 (all pass) or 1 (any fail).

    Distinct from run_selfcheck: these READ the adopter tree (deployed hook,
    package vendor hooks, live settings), so this is green only on a tree
    carrying a deployed harness. run_selfcheck runs the bundled engine tests and
    is green on a synthetic empty repo. ``espalier selfcheck`` runs
    run_selfcheck; ``espalier selfcheck --contracts`` runs this.
    """
    repo_root = Path(repo_root).resolve()
    results = [
        check_live_deny_path(repo_root),
        check_upstream_parity(repo_root),
        check_live_kill_switch_absent(repo_root),
    ]
    report = {
        "status": "pass" if all(r.passed for r in results) else "fail",
        "checks": [
            {"name": r.name, "passed": r.passed, "detail": r.detail,
             "failures": r.failures}
            for r in results
        ],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1
