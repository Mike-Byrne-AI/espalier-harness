#!/usr/bin/env python3
"""ConfigChange hook — blocks unsafe project/local/user settings changes.

Why this hook exists (its one reason): stop a slip — or the agent under
load — from writing a kill-switch (`disableAllHooks`, `bypassPermissions`)
into a settings file to turn the workflow off. It is the ConfigChange twin
of write_guard's anti-self-disable protected-zone block: together they keep
the hooks from being trivially silenced mid-session, so the path of least
resistance stays "follow the workflow," not "disable the safety and go."
This is friction against drift, not a defense against an attacker.

Per Claude Code hook protocol (see docs/external/cc-hook-protocol.md):
- ConfigChange can block project, local, and user settings changes.
- ConfigChange CANNOT block managed `policy_settings`. For policy_settings
  this hook only audits.
- SessionStart cannot block anything.

Channel: exit 0 + JSON decision (the project standard). On a deny we
emit `{"decision": "block", "reason": "..."}` matching the Stop-style schema
expected by ConfigChange.

Stdlib-only. Zero espalier imports. Co-located helper imports go through
sys.path injection.

If Claude Code disables all hooks before invoking this process, no local
hook can run. This check only blocks while the ConfigChange hook remains
active. CI (ci_guard.py) is the merge-time guarantee.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tools/cc for _json_safe
import _denial_reasons  # noqa: E402
import _integrity  # noqa: E402
import _hook_utils  # noqa: E402
from _hook_utils import os_error_text  # noqa: E402
from _hook_utils import warn_exc  # noqa: E402
from _json_safe import decode_bom  # noqa: E402


# Sources Claude Code may pass on the ConfigChange event. We block changes
# in the first three; the fourth is audit-only because policy_settings are
# explicitly non-blockable per the hook protocol.
BLOCKING_SOURCES = frozenset({"project", "local", "user"})
AUDIT_ONLY_SOURCES = frozenset({"policy_settings"})


_resolve_project_root = _hook_utils.resolve_project_root


def block(reason: str) -> int:
    """Print ConfigChange block JSON and return exit 0.

    Schema mirrors the Stop event: top-level `decision` and `reason`.
    """
    output = {"decision": "block", "reason": reason}
    print(json.dumps(output))
    return 0


def _scan_payload(file_path: str | None, root: Path) -> list[str]:
    """Scan the candidate settings file for kill-switch findings.

    Falls back to scanning the active settings inventory if the payload's
    `file_path` is missing, unreadable, or points outside the repo root.
    We never crash — best-effort scan, silent on failure.

    Path-traversal guard: stdin-supplied ``file_path`` is bounded to
    ``root`` via ``relative_to``. A traversal payload (``../../etc/passwd``)
    is dropped here so the scanner never opens files outside the repo.
    """
    candidate: Path | None = None
    if file_path:
        try:
            # No Git Bash drive-prefix translation here ON PURPOSE (DEF-731's
            # helper is `_hook_utils._msys_drive_to_windows`): a `/c/...`
            # spelling of a settings file fabricates an out-of-root path,
            # `relative_to` raises, and the scan falls back to the settings
            # inventory below -- fail-safe, nothing skipped.
            resolved = (root / file_path).resolve()
            resolved.relative_to(root)  # raises ValueError if outside root
            candidate = resolved
        except (OSError, ValueError):
            candidate = None

    findings: list[str] = []
    if candidate is not None and candidate.exists():
        try:
            # decode_bom (UTF-8/16/32 BOM-tolerant) — runtime kill-switch
            # reader; a BOM'd settings.json (incl. PowerShell UTF-16) must not
            # evade the live DENY gate.
            data = json.loads(decode_bom(candidate.read_bytes()))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            data = None
        if isinstance(data, dict):
            # candidate is bounded above; relative_to() is now guaranteed
            # to succeed without the ValueError fallback that previously
            # leaked absolute paths into the audit log.
            # Normalize the display label so a Windows audit log shows forward
            # slashes (the rel is display-only, never compared, but the harness
            # convention is `.replace("\\", "/")` everywhere).
            rel = str(candidate.relative_to(root)).replace("\\", "/")
            findings.extend(_integrity._find_kill_switches(rel, data))

    # Fall back to scanning the standard settings inventory so we still catch
    # findings even if the payload doesn't name a path or names a file we
    # can't reach.
    if not findings:
        try:
            findings = _integrity.scan_for_kill_switches(root)
        except Exception as e:  # noqa: BLE001 — bounded warn
            warn_exc("config_guard: scan failed", e)
            findings = []
    return findings


def main() -> int:
    """Public entry-point. Umbrella try/except catches any uncaught
    exception in _run_main and converts it to a block() — the Claude
    Code hook protocol treats exit 1 as a non-blocking script error,
    so we MUST fail-closed inside the hook process itself.

    Sister-pattern of write_guard.main and plan_guard.main.
    """
    try:
        return _run_main()
    except BaseException as exc:  # noqa: BLE001 — fail-closed crash guard
        # BaseException at hook entrypoints is exempt from
        # check_exception_policy.py; this noqa is documentary.
        error_type = type(exc).__name__
        print(
            f"[ERROR] config_guard crashed: {error_type}: {os_error_text(exc)}",
            file=sys.stderr,
        )
        # Recorded before the block (DEF-803, the class): a wedged guard
        # blocks every settings change, and the day it did was invisible in
        # ``/status --log``. Written inline, the way this hook's kill-switch
        # record is -- it has no funnel. The root is resolved best-effort
        # (the crash may have been in resolving it); the record carries the
        # exception's class, never its message (a message can quote a path
        # or a file's contents); ``quiet`` so a record that cannot be
        # written puts nothing on stderr beside the block JSON.
        #
        # INVARIANT: nothing between this ``except`` and the emit may prevent
        # the emit. The root fallback and the record write both swallow what
        # they can; a KeyboardInterrupt inside them is the one thing that
        # escapes, and the hook then exits non-zero, which the protocol reads
        # as allow -- which is also why an interrupt inside ``_run_main`` is
        # blocked here rather than re-raised. Add nothing here that can raise
        # past those handlers.
        try:
            root = _resolve_project_root()
        except BaseException:  # noqa: BLE001 — best-effort; never mask the block
            root = Path(".")
        try:
            _integrity.append_audit(
                root,
                {"event_type": "configchange_blocked_internal_error",
                 "details": {"hook": "config_guard", "error": error_type}},
                quiet=True,
            )
        except Exception:  # noqa: BLE001, S110 -- audit best-effort; hook protocol forbids stderr noise
            pass
        return block(_denial_reasons.CONFIG_GUARD_INTERNAL_ERROR)


def _run_main() -> int:
    from _hook_utils import read_stdin_safely  # noqa: E402

    data = read_stdin_safely()

    source = data.get("source") or data.get("settings_source") or ""
    file_path = data.get("file_path")
    root = _resolve_project_root()

    findings = _scan_payload(file_path, root)

    if not findings:
        return 0

    # BLOCKING_SOURCES and AUDIT_ONLY_SOURCES are disjoint, so a
    # `source in BLOCKING_SOURCES` disjunct would be redundant: any source in
    # the former is already `not in` the latter. This clause fail-closes: any
    # unknown/unlisted source is labeled blocked, only the explicit
    # policy_settings audit-only source gets the softer label.
    audit_event = (
        "configchange_blocked_kill_switch"
        if source not in AUDIT_ONLY_SOURCES
        else "configchange_policy_settings_kill_switch_detected"
    )
    try:
        _integrity.append_audit(
            root,
            {"event_type": audit_event,
             "details": {
                 "source": source,
                 "file_path": file_path,
                 "findings": findings,
             }},
        )
    except Exception:  # noqa: BLE001, S110 -- audit best-effort; hook protocol forbids stderr noise
        pass

    if source in AUDIT_ONLY_SOURCES:
        # ConfigChange cannot block managed policy_settings. Surface a stderr
        # warning for visibility; exit 0 with no JSON so Claude Code does not
        # interpret this as a structured block.
        print(
            f"[WARN] Espalier-Harness "
            f"{_hook_utils.plural(len(findings), 'kill-switch finding')} in policy_settings: "
            f"{findings}. ConfigChange cannot block managed policy settings; "
            "this is audit-only. Reconcile via your policy authority.",
            file=sys.stderr,
        )
        return 0

    return block(_denial_reasons.KILL_SWITCH_DETECTED.format(
        context=f" in {source or 'settings'} change",
        findings=findings,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
