#!/usr/bin/env python3
"""Canonical session resume and recovery engine for Espalier-Harness.

Stdlib-only -- zero espalier imports. Deployed to target repos by espalier init.

Usage:
    python tools/cc/session_resume.py --mode status
    python tools/cc/session_resume.py --mode normal
    python tools/cc/session_resume.py --mode recover
    python tools/cc/session_resume.py --mode recover --json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# SoT for cc/ path strings (LIVE_SURFACE_REL, COMMANDS_INDEX_REL,
# PACK_MANIFEST_REL). Co-located helper module — same zero-espalier-import
# pattern as the hooks.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _paths  # noqa: E402
from _json_safe import os_error_text  # noqa: E402

# Committed project-memory filename, routed through one per-file constant so a
# future rename is a value flip. Per-file (not a shared import) — tools/cc scripts
# run standalone; adding a sibling import risks the copy-subset footgun.
_MEMORY_FILENAME = "ESPALIER_MEMORY.md"


REQUIRED_PATHS: tuple[str, ...] = (
    ".claude/settings.json",
    _paths.LIVE_SURFACE_REL,
    _paths.COMMANDS_INDEX_REL,
    _paths.PACK_MANIFEST_REL,
    "tools/cc/cognitive_blueprint.py",
    "tools/cc/session_resume.py",
    "reports/repo_fingerprint.json",
    "reports/harness_config.json",
    "reports/cc_surface_gate.json",
)


# Runtime markers: the gitignored artifacts ``espalier init`` generates. Their
# ABSENCE on a fresh ``git clone`` is the expected source-checkout state, not a
# degraded surface. This mirrors the classification in
# espalier.repo_mode.detect_repo_mode locally — this module keeps its
# zero-espalier-import contract, so it cannot import repo_mode.
_RUNTIME_MARKERS: tuple[str, ...] = (
    ".claude/settings.json",
    "reports/repo_fingerprint.json",
    ".espalier/integrity.json",
)
# Committed harness surface (cc/ docs + the blueprint engine). Present in a fresh
# clone; ``any()`` so a single survivor distinguishes a source checkout from a
# bare uninitialized repo.
_COMMITTED_SURFACE: tuple[str, ...] = (
    _paths.LIVE_SURFACE_REL,
    _paths.COMMANDS_INDEX_REL,
    _paths.PACK_MANIFEST_REL,
    "tools/cc/cognitive_blueprint.py",
)


def _load_json_safe(path: Path) -> "dict[str, Any] | None":
    try:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        if lines and "espalier:managed" in lines[0]:
            lines = lines[1:]
        data = json.loads("\n".join(lines))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _git_summary(repo_root: Path) -> "dict[str, Any]":
    if not (repo_root / ".git").exists():
        return {"status": "unknown", "branch": "", "changed_count": 0, "preview": []}
    try:
        branch_proc = subprocess.run(
            ["git", "-C", str(repo_root), "branch", "--show-current"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=5,
        )
        branch = branch_proc.stdout.strip() or "detached"
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {"status": "unknown", "branch": "", "changed_count": 0, "preview": [],
                "warning": f"git probe failed: {os_error_text(exc)}"}
    try:
        status_proc = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--short"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=5,
        )
        changed = [ln for ln in status_proc.stdout.splitlines() if ln.strip()]
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {"status": "unknown", "branch": branch, "changed_count": 0, "preview": [],
                "warning": f"git status failed: {os_error_text(exc)}"}
    if changed:
        status = "untracked" if all(ln.startswith("?") for ln in changed) else "dirty"
    else:
        status = "clean"
    return {
        "status": status,
        "branch": branch,
        "changed_count": len(changed),
        "preview": changed[:10],
    }


def _blueprint_summary(repo_root: Path) -> "dict[str, Any]":
    bp_script = repo_root / "tools" / "cc" / "cognitive_blueprint.py"
    if not bp_script.exists():
        return {"status": "missing", "session_id": "", "accumulated_depth": None}
    try:
        # ``--json`` is required: without it, ``cognitive_blueprint.py load``
        # prints a human-readable markdown banner that fails ``json.loads``
        # below, causing this helper to report ``status="invalid"`` on EVERY
        # invocation (the operator-facing ``LAST: blueprint invalid`` would be
        # permanently wrong).
        #
        # ``env=`` pins CLAUDE_PROJECT_DIR to repo_root explicitly:
        # cognitive_blueprint._repo_root() prefers the env var over cwd, so
        # an inherited CLAUDE_PROJECT_DIR (always set under CC) would
        # silently route the lookup to a different repo. See
        # docs/SHARP_EDGES.md "Subprocesses Inheriting CLAUDE_PROJECT_DIR".
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo_root)}
        proc = subprocess.run(
            [sys.executable, str(bp_script), "load", "--json"],
            capture_output=True, text=True, encoding="utf-8", check=False, timeout=10,
            cwd=str(repo_root), env=env,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return {"status": "missing", "session_id": "", "accumulated_depth": None}
        data = json.loads(proc.stdout)
        if not isinstance(data, dict):
            return {"status": "invalid", "session_id": "", "accumulated_depth": None}
        return {
            "status": "found",
            "session_id": str(data.get("session_id", "")),
            "accumulated_depth": data.get("accumulated_depth"),
        }
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError) as exc:
        return {"status": "invalid", "session_id": "", "accumulated_depth": None,
                "warning": os_error_text(exc)}


def _fingerprint_summary(repo_root: Path) -> "dict[str, Any]":
    fp_path = repo_root / "reports" / "repo_fingerprint.json"
    if not fp_path.exists():
        return {"status": "missing", "repo_name": "", "languages": []}
    data = _load_json_safe(fp_path)
    if data is None:
        return {"status": "invalid", "repo_name": "", "languages": []}
    langs = data.get("languages", [])
    return {
        "status": "saved",
        "repo_name": str(data.get("repo_name", "")),
        # F6 (CV2): a null/scalar `languages` (valid JSON, wrong field type) would
        # make list(...) raise an uncaught TypeError. Type-guard it.
        "languages": list(langs) if isinstance(langs, list) else [],
    }


def _count_surface(repo_root: Path) -> "dict[str, int]":
    agents_dir = repo_root / ".claude" / "agents"
    commands_dir = repo_root / ".claude" / "commands"
    agents = len(list(agents_dir.glob("*.md"))) if agents_dir.exists() else 0
    commands = len(list(commands_dir.glob("*.md"))) if commands_dir.exists() else 0
    return {"agents": agents, "commands": commands}


def _plan_missing_docs(repo_root: Path) -> "list[str]":
    plan_path = repo_root / "reports" / "harness_config.json"
    if not plan_path.exists():
        return []
    data = _load_json_safe(plan_path)
    if not data:
        return []
    # F6 (CV2): a null/scalar `generated_docs` would make `for rel in ...` raise
    # (the {} default only applies to an ABSENT key, not a null value). Guard it.
    docs = data.get("generated_docs", [])
    if not isinstance(docs, list):
        return []
    missing: list[str] = []
    for rel in docs:
        if not (repo_root / str(rel)).exists():
            missing.append(str(rel))
    return missing


def _manifest_missing_docs(repo_root: Path) -> "list[str]":
    manifest_path = repo_root / "cc" / "PACK_MANIFEST.txt"
    if not manifest_path.exists():
        return []
    missing: list[str] = []
    # Names, read with a replacement character: a code-page re-save of the
    # manifest must not crash /status (a strict read raised UnicodeDecodeError
    # out of a function with no handler at all; DEF-829).
    for raw in manifest_path.read_text(encoding="utf-8", errors="replace").splitlines():
        rel = raw.strip()
        if rel and not rel.startswith("#") and not (repo_root / rel).exists():
            missing.append(rel)
    return missing


def assess_repo_state(repo_root: Path) -> "dict[str, Any]":
    """Assess whether the CC surface is coherent enough to resume work."""
    repo_root = repo_root.resolve()

    present = [p for p in REQUIRED_PATHS if (repo_root / p).exists()]
    missing = [p for p in REQUIRED_PATHS if not (repo_root / p).exists()]

    plan_missing = _plan_missing_docs(repo_root)
    manifest_missing = _manifest_missing_docs(repo_root)

    # A fresh source checkout ships the committed surface (cc/*, tools/cc/*) but
    # NOT the gitignored init artifacts (settings.json, reports/*.json). Missing
    # those is the expected pre-init state, not degradation — mirror
    # repo_mode.detect_repo_mode's source_checkout branch. An *uninitialized*
    # repo (no committed surface either) is NOT a source checkout and still
    # DEGRADEs, preserving test_empty_repo_surface_is_degraded.
    has_runtime = any((repo_root / m).exists() for m in _RUNTIME_MARKERS)
    has_committed = any((repo_root / s).exists() for s in _COMMITTED_SURFACE)
    is_source_checkout = has_committed and not has_runtime

    # F7 (CV2): a present-but-corrupt required JSON report (repo_fingerprint /
    # harness_config / settings) is counted in `present`, not `missing`, and — unlike
    # cc_surface_gate.json below, which grew a gate_unreadable branch — had NO
    # unreadable check, so an unparseable report still reported surface=healthy.
    # Fail CLOSED, mirroring that branch. (cc_surface_gate.json is excluded here
    # because it has its own dedicated branch.)
    report_unreadable = [
        p for p in REQUIRED_PATHS
        if p.endswith(".json")
        and p != "reports/cc_surface_gate.json"
        and (repo_root / p).exists()
        and _load_json_safe(repo_root / p) is None
    ]

    surface_gate_status = ""
    gate_unreadable = False
    gate_path = repo_root / "reports" / "cc_surface_gate.json"
    if gate_path.exists():
        gate_data = _load_json_safe(gate_path)
        if gate_data is not None:
            surface_gate_status = str(gate_data.get("status", ""))
        else:
            # File EXISTS but is corrupt / non-dict, so it is NOT
            # counted in ``missing`` above. Without this branch the surface
            # would report "healthy" despite an unreadable proof gate — the
            # exact case the degraded-recovery path exists to catch.
            gate_unreadable = True

    fail_reasons: list[str] = []
    if missing and not is_source_checkout:
        fail_reasons.append(f"{len(missing)} required paths missing")
    if gate_unreadable:
        fail_reasons.append("surface gate unreadable / malformed")
    if report_unreadable:
        fail_reasons.append(
            f"{len(report_unreadable)} required "
            f"report{'' if len(report_unreadable) == 1 else 's'} unreadable / malformed"
        )
    if surface_gate_status and surface_gate_status.lower() != "pass":
        fail_reasons.append(f"surface gate status: {surface_gate_status}")
    if plan_missing:
        fail_reasons.append(f"{len(plan_missing)} promised docs missing")
    # Gate on `not is_source_checkout` (mirror the REQUIRED_PATHS `missing`
    # branch above): cc/PACK_MANIFEST.txt is COMMITTED, so on a source checkout
    # or an extracted release export it lists init-generated entries
    # (reports/*.json, .claude/settings.json) that are absent pre-init — the
    # expected state, not degradation. `plan_missing` above needs no such gate:
    # it derives from reports/harness_config.json, which is itself absent here.
    if manifest_missing and not is_source_checkout:
        fail_reasons.append(f"{len(manifest_missing)} manifest entries missing")

    status = "fail" if fail_reasons else "pass"
    surface = "healthy" if status == "pass" else "DEGRADED"

    recommendations: list[str] = []
    if is_source_checkout:
        recommendations.append(
            "fresh source checkout -- run `espalier init .` to generate the "
            "runtime surface (.claude/settings.json, reports/*.json). This is "
            "the expected pre-init state, not a degraded surface."
        )
    elif missing:
        recommendations.append("rebuild or re-audit the CC surface before continuing")
    if plan_missing:
        recommendations.append("regenerate docs promised by reports/harness_config.json")
    if manifest_missing:
        recommendations.append("refresh cc/PACK_MANIFEST.txt after file recovery or rebuild")
    if gate_unreadable:
        recommendations.append(
            "regenerate reports/cc_surface_gate.json (unreadable / malformed)"
        )
    if surface_gate_status and surface_gate_status.lower() != "pass":
        recommendations.append("fix proof-gate failures before new work")
    if not recommendations:
        recommendations.append(
            "surface looks coherent; read ESPALIER_MEMORY.md, cc/LIVE_SURFACE.md, "
            "cc/COMMANDS.md, and cc/SURFACE_HANDOFF.md if present before resuming"
        )

    return {
        "status": status,
        "surface": surface,
        "repo_root": str(repo_root),
        "present": present,
        "missing": missing,
        "plan_missing_docs": plan_missing,
        "manifest_missing_docs": manifest_missing,
        "surface_gate_status": surface_gate_status,
        # The reasons behind a `fail`, and the reports that could not be
        # read, as data: `doctor` composes its own recovery line from these
        # (DEF-786) instead of guessing from the lists above, so a fail for
        # a path-less reason (an unreadable report, a non-pass gate status)
        # is never withheld as if the audit had already named it.
        "fail_reasons": fail_reasons,
        "unreadable_reports": (
            report_unreadable
            + (["reports/cc_surface_gate.json"] if gate_unreadable else [])
        ),
        "git": _git_summary(repo_root),
        "blueprint": _blueprint_summary(repo_root),
        "fingerprint": _fingerprint_summary(repo_root),
        "memory": {
            "status": "present" if (repo_root / _MEMORY_FILENAME).exists() else "missing"
        },
        "sharp_edges": {
            "status": "present" if (repo_root / "docs" / "SHARP_EDGES.md").exists() else "missing"
        },
        "counts": _count_surface(repo_root),
        "recommendations": recommendations,
    }


def render_status_report(report: "dict[str, Any]") -> str:
    """Compact one-block status report."""
    git = report.get("git", {})
    branch = git.get("branch", "?")
    changed = git.get("changed_count", 0)
    branch_str = f"{branch} ({changed} changed)" if changed else branch

    fp = report.get("fingerprint", {})
    bp = report.get("blueprint", {})
    counts = report.get("counts", {})

    lines = [
        f"REPO:     {fp.get('repo_name') or report.get('repo_root', '?')}",
        f"SURFACE:  {report.get('surface', '?')}",
        f"BRANCH:   {branch_str}",
        f"STATUS:   fingerprint={fp.get('status','?')} blueprint={bp.get('status','?')}",
        f"AGENTS:   {counts.get('agents', '?')}  COMMANDS: {counts.get('commands', '?')}",
    ]
    missing = report.get("missing", [])
    if missing:
        lines.append(f"MISSING:  {', '.join(missing[:3])}{'...' if len(missing) > 3 else ''}")
    return "\n".join(lines) + "\n"


def render_context_report(report: "dict[str, Any]") -> str:
    """Full context-load report for session start."""
    git = report.get("git", {})
    branch = git.get("branch", "?")
    changed = git.get("changed_count", 0)
    branch_str = f"{branch} (+{changed} uncommitted)" if changed else branch

    fp = report.get("fingerprint", {})
    bp = report.get("blueprint", {})
    memory = report.get("memory", {})
    recs = report.get("recommendations", [])

    if bp.get("status") == "found":
        session_id = bp.get("session_id", "")
        depth = bp.get("accumulated_depth")
        last_session = session_id
        if depth is not None:
            last_session += f" (depth={depth})"
    elif bp.get("status") == "missing":
        last_session = "no prior blueprint -- starting fresh"
    else:
        last_session = f"blueprint {bp.get('status','?')}"

    lines = [
        f"REPO:    {fp.get('repo_name') or report.get('repo_root', '?')}",
        f"SURFACE: {report.get('surface', '?')}",
        f"LAST:    {last_session}",
        f"BRANCH:  {branch_str}",
        f"STATUS:  fingerprint={fp.get('status','?')}  memory={memory.get('status','?')}",
        f"NEXT:    {recs[0] if recs else 'none'}",
    ]
    return "\n".join(lines) + "\n"


def render_recovery_report(report: "dict[str, Any]") -> str:
    """Recovery-focused report for degraded surfaces."""
    git = report.get("git", {})
    bp = report.get("blueprint", {})
    fp = report.get("fingerprint", {})
    memory = report.get("memory", {})
    counts = report.get("counts", {})

    bp_str = (
        f"found ({bp.get('session_id', '')})"
        if bp.get("status") == "found"
        else bp.get("status", "?")
    )

    lines = [
        "RECOVERY REPORT",
        "===============",
        f"Surface:     {report.get('surface', '?')}",
        f"Blueprint:   {bp_str}",
        f"Fingerprint: {fp.get('status', '?')}",
        f"ESPALIER_MEMORY.md:   {memory.get('status', '?')}",
        f"Agents:      {counts.get('agents', '?')}",
        f"Commands:    {counts.get('commands', '?')}",
        "",
    ]

    missing = report.get("missing", [])
    if missing:
        lines.append("Missing required paths:")
        lines.extend(f"  - {p}" for p in missing)
        lines.append("")

    plan_missing = report.get("plan_missing_docs", [])
    if plan_missing:
        lines.append("Build-plan docs missing on disk:")
        lines.extend(f"  - {p}" for p in plan_missing)
        lines.append("")

    manifest_missing = report.get("manifest_missing_docs", [])
    if manifest_missing:
        lines.append("Manifest entries missing on disk:")
        lines.extend(f"  - {p}" for p in manifest_missing)
        lines.append("")

    git_preview = git.get("preview", [])
    if git_preview:
        lines.append(f"Git ({git.get('status','?')}, {git.get('changed_count',0)} changed):")
        lines.extend(f"  {ln}" for ln in git_preview[:5])
        lines.append("")

    lines.append("Recommended next steps:")
    for rec in report.get("recommendations", []):
        lines.append(f"  - {rec}")

    return "\n".join(lines).strip() + "\n"


def _start_session(repo_root: Path) -> bool:
    """Bootstrap a blueprint node when none exists (the last-resort fallback
    for ``--mode normal``; routine per-session chain-advancement lives in the
    SessionStart hook). Returns True on a successful start."""
    bp_script = repo_root / "tools" / "cc" / "cognitive_blueprint.py"
    if not bp_script.exists():
        return False
    try:
        # See _blueprint_summary for env= rationale. Without this, a
        # leaked CLAUDE_PROJECT_DIR would route a new blueprint into a
        # different repo — far worse than the lookup-routing variant in
        # _blueprint_summary because it produces a *write* in the wrong
        # place.
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo_root)}
        proc = subprocess.run(
            [sys.executable, str(bp_script), "start"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=15,
            cwd=str(repo_root), env=env,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False


def _count_by_type(lines: "list[str]") -> "dict[str, int]":
    """``event_type -> count`` over audit-log lines (an unparsable line counts
    under ``?`` -- ``tail_audit`` returns attributable records, never drops)."""
    counts: dict[str, int] = {}
    for line in lines:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            parsed = None
        kind = str(parsed.get("event_type", "?")) if isinstance(parsed, dict) else "?"
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def _format_counts(counts: "dict[str, int]") -> str:
    """``type N, type N`` -- most frequent first, then by name."""
    return ", ".join(
        f"{kind} {count}"
        for kind, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    )


#: What each hook switches off under maintenance mode, for the bypass line.
_BYPASSED_CHECK = {
    "write_guard": "protected-zone check",
    "plan_guard": "plan requirement",
    "stop_gate": "Gates 2 and 3",
}


def _bypass_summary(lines: list[str]) -> str:
    """``hook (what it skipped) N`` per hook, from the records' ``details.hook``;
    a record with no hook is counted under its event type. 7-bit ASCII."""
    counts: dict[str, int] = {}
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        details = rec.get("details") if isinstance(rec, dict) else None
        hook = details.get("hook") if isinstance(details, dict) else None
        key = str(hook or rec.get("event_type", "?"))
        counts[key] = counts.get(key, 0) + 1
    return ", ".join(
        f"{k} ({_BYPASSED_CHECK[k]}) {v}" if k in _BYPASSED_CHECK else f"{k} {v}"
        for k, v in sorted(counts.items())
    )


def _print_audit_tail(repo_root: Path, n: int, *, include_pauses: bool = False) -> int:
    """Print the last ``n`` governance audit-log records for ``repo_root``
    today (read-only): the refusals, or every block under ``include_pauses``.
    Lazy-imports ``_integrity`` (the audit-log owner) inside
    the handler — a module-level import would drag the hook internals into
    session_resume's standalone graph and fire on every
    ``spec_from_file_location`` load in the test suite. A read-only convenience
    must never crash ``/status``, so every failure degrades to a message."""
    inserted = False
    hooks_dir = Path(__file__).resolve().parent / "hooks"
    if str(hooks_dir) not in sys.path:
        sys.path.insert(0, str(hooks_dir))
        inserted = True
    try:
        import _integrity  # noqa: E402  (lazy sibling import; see docstring)
    except Exception:  # noqa: BLE001 -- read-only convenience must not crash /status
        print("governance audit log unavailable (audit reader failed to load)",
              file=sys.stderr)
        return 0
    finally:
        # Pop our own insert (the module is cached now; attribute access below
        # needs no path). Matches the try/finally sibling-import pattern used in
        # tests/test_hook_audit_noqa_annotations.py.
        if inserted:
            try:
                sys.path.remove(str(hooks_dir))
            except ValueError:
                pass
    path = _integrity.audit_path(repo_root)
    # Filter to enforcement BLOCKS -- the log also carries advisory records
    # (action_justification_missing fires on every un-justified write) that
    # would otherwise bury the blocks this view is meant to surface. Two
    # tiers: the tail shows the REFUSALS (a call that did not run) unless
    # ``include_pauses``; the PAUSES (a speed-bump fire the re-issued command
    # walks through, a Stop-gate block the next Stop passes) are counted for
    # the day on their own line, because on a busy day they outnumber the
    # rare refusal inside a window of twenty.
    # Attribute reads sit under the same never-crash contract as the import:
    # a half-applied upgrade (this file new, ``_integrity`` still HEAD's) has
    # no tiers yet, and ``/status`` then shows the one tier it has.
    refusals = _integrity.DENIAL_EVENT_TYPES
    pause_types = getattr(_integrity, "PAUSE_EVENT_TYPES", frozenset())
    blocked = getattr(_integrity, "BLOCKED_EVENT_TYPES", refusals)
    shown = blocked if include_pauses else refusals
    noun = "blocked" if include_pauses else "denial"
    lines = _integrity.tail_audit(repo_root, n, event_types=shown)
    # Every matching record for the DAY, counted by type, above the tail: a
    # window of N cannot say what it left out. 7-bit ASCII (Windows stdout).
    today = _integrity.tail_audit(repo_root, None, event_types=shown)
    pauses_today = (
        [] if include_pauses or not pause_types
        else _integrity.tail_audit(repo_root, None, event_types=pause_types)
    )
    pause_counts = _count_by_type(pauses_today)
    # The maintenance-bypass records are advisory (nothing was blocked) and in
    # neither tier, so they never enter the tail; they are counted on their own
    # line, per hook, so a day on which the anti-self-disable floor or the
    # hygiene gates were switched off cannot read as a clean one (DEF-789). The
    # soft attribute read keeps the never-crash contract on a half-upgraded
    # tree, and says so instead of reading as a clean day.
    bypass_types = getattr(_integrity, "MAINTENANCE_BYPASS_EVENT_TYPES", None)
    bypasses_today = (
        _integrity.tail_audit(repo_root, None, event_types=bypass_types)
        if bypass_types else []
    )
    bypass_line = _bypass_summary(bypasses_today)
    skew_note = (
        "# maintenance-bypass reporting unavailable: the deployed hooks predate it "
        "(redeploy the hook tree)"
        if bypass_types is None else ""
    )
    if not lines:
        suffix = ""
        if pauses_today:
            suffix = (
                f"; {len(pauses_today)} pause record{'' if len(pauses_today) == 1 else 's'} today -- "
                f"{_format_counts(pause_counts)} -- `--log N --all` shows them"
            )
        if bypasses_today:
            suffix += (
                f"; {len(bypasses_today)} maintenance-bypass record"
                f"{'' if len(bypasses_today) == 1 else 's'} today -- {bypass_line} "
                "-- a check switched off under ESPALIER_MAINTENANCE_MODE"
            )
        kind = "blocks" if include_pauses else "denials"
        print(f"(no governance {kind} recorded for this repo today: {path}{suffix})")
        if skew_note:
            print(skew_note)
        return 0
    print(
        f"# governance audit log -- last {len(lines)} of {len(today)} {noun} "
        f"record{'' if len(today) == 1 else 's'} for this repo today: {path}"
    )
    print("# by type: " + _format_counts(_count_by_type(today)))
    if pauses_today:
        print(
            f"# pauses today: {_format_counts(pause_counts)} (once-then-continue; "
            f"not in this tail -- `--log N --all` shows them)"
        )
    if bypasses_today:
        print(
            f"# maintenance bypass today: {bypass_line} -- a check switched off under "
            "ESPALIER_MAINTENANCE_MODE (advisory; not a block)"
        )
    if skew_note:
        print(skew_note)
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            print(line)  # tail_audit returns attributable records; never drop one
            continue
        if not isinstance(rec, dict):
            print(line)
            continue
        ts = rec.get("timestamp", "?")
        event = rec.get("event_type", "?")
        details = json.dumps(rec.get("details", {}))
        print(f"{ts}  {event}  {details}")
    return 0


def _print_path_explanation(repo_root: Path, path: str) -> int:
    """Print the per-path enforcement read-out for ``path`` (read-only). Lazy-
    imports the ``_explain_path`` resolver from the hooks dir inside the handler
    — a module-level import would drag the hook internals into session_resume's
    standalone graph and fire on every ``spec_from_file_location`` load in the
    test suite. Same cross-dir sibling-import shape as ``_print_audit_tail``. A
    read-only convenience must never crash ``/status``, so failure degrades to a
    message."""
    inserted = False
    hooks_dir = Path(__file__).resolve().parent / "hooks"
    if str(hooks_dir) not in sys.path:
        sys.path.insert(0, str(hooks_dir))
        inserted = True
    try:
        import _explain_path  # noqa: E402  (lazy sibling import; see docstring)
    except Exception:  # noqa: BLE001 -- read-only convenience must not crash /status
        print("path explanation unavailable (resolver failed to load)", file=sys.stderr)
        return 0
    finally:
        if inserted:
            try:
                sys.path.remove(str(hooks_dir))
            except ValueError:
                pass
    # The "never crash /status" contract covers the render too, not just the
    # import: a future predicate enrichment that touches the FS could raise, and
    # a read-only convenience must still degrade to a message, not a traceback.
    try:
        print(_explain_path.render(_explain_path.explain(path, repo_root)))
    except Exception:  # noqa: BLE001 -- read-only convenience must not crash /status
        print(f"path explanation unavailable (resolver failed for {path})", file=sys.stderr)
    return 0


#: ``--log`` with no count: the last N denial records ``/status --log`` shows.
_LOG_TAIL_DEFAULT = 20


def _split_log_value(value: str) -> "tuple[int, str | None]":
    """``(count, swallowed_root)`` for the token argparse handed ``--log``.

    An integer is the count and nothing was swallowed. A directory that exists
    is the ``repo_root`` positional the optional-count option consumed,
    returned so ``main`` can put it back; the count falls to the default.
    Anything else -- ``2O`` typed for ``20``, a path that is not there --
    raises ``ValueError`` with the message ``main`` hands to ``parser.error``:
    the old ``type=int`` at least failed loudly on a typo, and a confident
    "(no governance denials ...)" for a root that does not exist is a wrong
    answer, not a lenient one. Pure apart from the ``is_dir`` probe, so the
    rule is testable without a subprocess.
    """
    try:
        return int(value), None
    except ValueError:
        pass
    if Path(value).is_dir():
        return _LOG_TAIL_DEFAULT, value
    raise ValueError(
        f"argument --log: expected a count N (an integer) or an existing repo "
        f"root, got {value!r}"
    )


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assess CC harness state and produce session resume output."
    )
    parser.add_argument(
        "--mode",
        choices=["status", "normal", "recover"],
        default="normal",
        help="Output mode: status (compact), normal (context-load), recover (recovery report)",
    )
    parser.add_argument("--json", action="store_true", help="Print full assessment as JSON")
    parser.add_argument(
        "--log",
        nargs="?",
        const=str(_LOG_TAIL_DEFAULT),
        default=None,
        metavar="N",
        help="Print the last N (default 20) governance audit-log records for "
             "this repo today, then exit (read-only). An existing directory in "
             "place of N is read as the repo_root positional "
             "(`--log path/to/repo`).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="With --log: widen the tail to the pause records too (a speed-bump "
             "fire, a Stop-gate block -- once-then-continue), which the default "
             "tail only counts.",
    )
    parser.add_argument(
        "--explain",
        default=None,
        metavar="PATH",
        help="Explain what the path-conditioned hooks (plan_guard, write_guard) "
             "would do on PATH and why, then exit (read-only). Takes a required "
             "value, so it never swallows the repo_root positional.",
    )
    parser.add_argument(
        "repo_root",
        nargs="?",
        default=".",
        help="Path to repository root (default: current directory)",
    )
    args = parser.parse_args(argv)

    log_n: int | None = None
    if args.log is not None:
        # ``--log`` takes an OPTIONAL count, so argparse hands it whatever
        # token follows -- including the repo_root positional (``--log
        # /path/to/repo`` used to die with ``invalid int value``). A count is
        # an integer; anything else is the root the option swallowed. Two
        # roots is the operator's error, said in argparse's own voice (exit 2,
        # no traceback) rather than the coercion message.
        try:
            log_n, swallowed_root = _split_log_value(args.log)
        except ValueError as exc:
            parser.error(str(exc))
        if log_n <= 0:
            parser.error(f"argument --log: N must be a positive count, got {log_n}")
        if swallowed_root is not None:
            if args.repo_root != ".":
                parser.error(
                    f"argument --log: takes an optional count N, got {args.log!r} "
                    f"and a repo root {args.repo_root!r} -- pass the count as "
                    "`--log N` or the repo root once"
                )
            args.repo_root = swallowed_root

    if args.all and log_n is None:
        parser.error("argument --all: requires --log (it widens the tail to the pause records)")

    repo_root = Path(args.repo_root).resolve()

    if log_n is not None:
        return _print_audit_tail(repo_root, log_n, include_pauses=args.all)

    if args.explain is not None:
        return _print_path_explanation(repo_root, args.explain)

    report = assess_repo_state(repo_root)

    if getattr(args, "json"):
        print(json.dumps(report, indent=2))
        if args.mode == "recover":
            return 0 if report["status"] == "pass" else 1
        return 0

    if args.mode == "status":
        print(render_status_report(report), end="")
        return 0

    if args.mode == "recover":
        print(render_recovery_report(report), end="")
        return 0 if report["status"] == "pass" else 1

    # --mode normal (context-load behavior)
    print(render_context_report(report), end="")

    if report["status"] == "pass":
        # Chain-advancement now lives in the SessionStart hook
        # (session_start.py starts a node on source startup/clear). context-load
        # is a pure, idempotent reorient EXCEPT as a last-resort bootstrap: if
        # NO blueprint FILE exists at all (the hook never ran, or a fresh tree),
        # start one so this session's reasoning has a node to land in. When a
        # blueprint already exists, do NOT start — running context-load
        # mid-session must not fragment the chain into shallow empty nodes.
        #
        # Key the decision on the FILE's presence (matching
        # session_start._blueprint_present), NOT on the report's "missing"
        # status: a present-but-unreadable latest.json (symlink/oversize/
        # corrupt) reports "missing" yet must NOT be clobbered by a reorient.
        bp_pointer = repo_root / "cc" / "blueprints" / "latest.json"
        try:
            bp_present = bp_pointer.exists() or bp_pointer.is_symlink()
        except OSError:
            bp_present = False
        if not bp_present:
            started = _start_session(repo_root)
            if not started:
                print(
                    "\nWARN: Could not start cognitive blueprint session "
                    "(tools/cc/cognitive_blueprint.py unavailable or failed).",
                    file=sys.stderr,
                )
    else:
        print("\n--- DEGRADED SURFACE DETECTED ---", file=sys.stderr)
        print(render_recovery_report(report), end="", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
