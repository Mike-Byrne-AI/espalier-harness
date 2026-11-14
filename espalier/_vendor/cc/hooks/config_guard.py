#!/usr/bin/env python3
"""ConfigChange hook — blocks unsafe project/local/user settings changes.

Why this hook exists (its one reason): stop a slip — or the agent under
load — from writing a kill-switch (`disableAllHooks`, an emptied or no-op
governed hook list) into a settings file to turn the workflow off. A
`bypassPermissions` default is not a kill-switch and is not judged here
(DEF-1108): the hooks still run and deny in bypass mode, a ConfigChange block
is shown to no one and does not revert the file, and the mode is chosen at
launch. What keeps a session from granting itself bypass is write_guard's deny
on writes to both settings files; SessionStart and doctor name the posture, and
ci_guard fails a committed one. Its second reason: a change
to the project settings file that unwires a governance gate the session runs
-- a removed `hooks` key, a deleted file -- switches those hooks off at once,
mid-session, and refusing the change keeps them (``_unwiring_findings``). Its
third: a change to any of the three settings files that switches a gate off
beyond the kill-switch shapes -- ``disableAllHooks`` written to the user file,
which Claude Code names by a path outside the repo, or a gate variable in a
settings ``env`` map, which reaches the hook processes -- judged against the
values SessionStart recorded, is refused the same way and told at the next
PostToolUse (``_judge_gate_switch``, DEF-3081). It is
the ConfigChange twin
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
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tools/cc for _json_safe
# The start refusal first and alone, then the guard over every other sibling,
# the floor included: write_guard.py's import block is the sister site and says
# why (DEF-1176, DEF-3008). This hook's event shape is the Stop-style block,
# which the refusal emits for ConfigChange.
try:
    import _start_refusal  # noqa: E402
except Exception as _floor:  # noqa: BLE001 -- the start refusal itself cannot import (DEF-3008)
    if __name__ != "__main__":
        raise
    sys.stdout.write(json.dumps({"decision": "block", "reason": (
        "config_guard cannot start: tools/cc/hooks/_start_refusal.py raised " + type(_floor).__name__
        + "; it is the start refusal every deny hook imports first. Restore it to HEAD:"
        " `git restore --source=HEAD -- :/tools/cc/hooks/_start_refusal.py`, as one Bash command"
        " (write_guard, wedged by the same file, lets that one call through) or from a terminal;"
        " if HEAD has no such file (an upgrade that did not finish), run"
        " `espalier upgrade --execute .` from a terminal instead. Every call this hook judges"
        " is refused until then.")}) + "\n")
    sys.stdout.flush()
    raise SystemExit(0) from None
# Below the supported Python floor, say the floor first (write_guard.py says
# why); then a raise that escapes this module's body is the start refusal.
if __name__ == "__main__":
    _start_refusal.refuse_below_floor("config_guard", "ConfigChange")
    _start_refusal.refuse_on_body_raise("config_guard", "ConfigChange")
try:
    import _hook_utils  # noqa: E402
    import _denial_reasons  # noqa: E402
    import _integrity  # noqa: E402
    import _maintenance_mode  # noqa: E402
    from _hook_utils import os_error_text  # noqa: E402
    from _json_safe import decode_bom  # noqa: E402
    # Every helper name this hook's import graph takes (write_guard.py says why).
    _CONFIG_GUARD_HELPER_NAMES = (
        "STATE_DIR", "atomic_write_text", "lock_file", "os_error_text", "plural", "read_stdin_safely",
        "resolve_project_root", "say_bad_stdin", "say_once", "stop_gate_mode", "unlock_file", "warn",
        "warn_exc",
    )
    for _name in _CONFIG_GUARD_HELPER_NAMES:
        getattr(_hook_utils, _name)
except Exception as _skew:  # noqa: BLE001 -- a kept helper that predates its siblings (DEF-1176)
    if __name__ != "__main__":
        raise
    _start_refusal.refuse_on_helper_skew("config_guard", "ConfigChange", _skew)


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


def _names_project_settings(file_path: str | None, source: str, root: Path) -> bool:
    """The change is to the project ``.claude/settings.json``: by the payload's
    path, compared by LOCATION (the directory resolved, the file name not, so a
    settings file symlinked out of the repo still counts), or, with no path,
    by the source Claude Code names. Path equality folds case on Windows."""
    try:
        project = (root / ".claude").resolve() / "settings.json"
        if file_path:
            path = Path(file_path)
            if not path.is_absolute():
                path = root / path
            return path.parent.resolve() / path.name == project
    except OSError:  # fail-open: ok deliberate -- an unresolvable path is not judged as the project file; the kill-switch scan still runs
        return False
    return source == "project_settings"


def _unwiring_findings(root: Path) -> list[str]:
    """The findings for a change to the project settings file
    that unwires a governance gate this session was running, unless a harness
    writer recorded writing exactly this content (the in-session uninstall's
    unwire, DEF-1060).

    Why here: removing the ``hooks`` key or deleting the file switches every
    hook off at once, mid-session, and a ConfigChange refusal keeps them (0-E,
    7/7 runs; driven again on this code, 7/7). A CHANGE is judged, not the
    file's state: the gates lost are those in the session's snapshot
    (``_integrity.WIRED_GATES_SNAPSHOT``) the changed file no longer wires, so
    a tree already partly unwired, or in the shell form the reader cannot
    prove, keeps its edits. No snapshot judges every deployed gate
    (fail-closed). Only the PROJECT file is judged: a local file normally wires
    nothing and keeps today's kill-switch shapes only. The refusal is silent by
    protocol and leaves the file as written, so the change is noted for the
    next PostToolUse to tell Claude, with the restore route."""
    # A file that is gone, empty or not JSON wires nothing: Claude Code drops
    # every hook for each (driven 2026-10-08: emptied and syntax-broken files
    # alike). Refusing such a change blocks no later edit -- each ConfigChange
    # is judged on its own content, so the repair is let through -- which is
    # why the kill-switch scan's leave-it-editable fail-open is not borrowed.
    state, data = _integrity.read_project_settings(root)
    live = set(_integrity.live_governance_gates(data, root))
    deployed = set(_integrity.deployed_governance_gates(root))
    before = _integrity.read_wired_gates(root)
    lost = sorted((deployed if before is None else set(before) & deployed) - live)
    if not lost or _integrity.recorded_settings_writer(root, data):
        # Let through: Claude Code now runs this file, so it is the session's.
        _integrity.write_wired_gates(root, sorted(live))
        if not lost:
            _integrity.clear_unwired_pending(root)
        return []
    _integrity.record_unwired_pending(
        root, lost, kind={"absent": "deleted", "unreadable": "unreadable"}.get(state, "unwired"))
    return [
        finding
        for finding in _integrity.unwired_governance_gates(_integrity.PROJECT_SETTINGS_REL, data, root)
        if "loads NO hooks" in finding or any(f" {gate} " in finding for gate in lost)
    ]


#: The variables that switch a gate when set: ``_integrity``'s roster, which
#: tests/test_hook_constant_parity.py pins equal to write_guard's
#: ``_HARNESS_ENV_NAMES`` (the roster an in-session assignment may not set).
_GATE_ENV_NAMES: tuple[str, ...] = _integrity.SETTINGS_GATE_ENV_NAMES
_USER_SOURCE = "user_settings"
_SOURCE_RANK = {"local_settings": 0, "project_settings": 1, _USER_SOURCE: 2}


def _changed_settings_label(file_path: str | None, source: str, root: Path) -> str | None:
    """The label of the settings file Claude Code says changed, or None for a
    change no settings file of the three is (a skill, managed policy, a path
    elsewhere).

    The user file is named by its source or its location: Claude Code gives
    its absolute path (``source: user_settings``, the hooks reference), which
    no root bound can hold. A project file is matched by location (the
    directory resolved, as ``_names_project_settings`` matches it), so a path
    elsewhere opens nothing. With no path, the source names the file. Raises
    OSError or RuntimeError where a path cannot be resolved or no home found."""
    files = _integrity.settings_files(root)
    if not file_path:
        rank = _SOURCE_RANK.get(source)
        return None if rank is None else files[rank][0]
    path = Path(file_path)
    if not path.is_absolute():
        path = root / path
    if source == _USER_SOURCE and path.name == "settings.json":
        return files[_SOURCE_RANK[_USER_SOURCE]][0]
    where = path.parent.resolve() / path.name
    for label, candidate in files:
        if where == candidate.parent.resolve() / candidate.name:
            return label
    return None


def _loosens(name: str, before: str | None, after: str | None, mode: str) -> bool:
    """``after`` loosens the gate ``name`` switches against ``before``, each
    read by its gate's own grammar (None is unset): the maintenance switch
    turned on; the stop gate moved off ``full`` (``light`` is the default
    floor, so turning it on tightens); the suite command changed where Gate 1
    runs one -- the stop gate full (``mode``) and a command already in effect.
    Under light the gate runs nothing, and a full gate with none is the
    SessionStart dormancy note's advice to set one: both are tightenings."""
    if name == _maintenance_mode.ENV_VAR:
        active = _maintenance_mode._maintenance_mode_active
        return active(after) and not active(before)
    if name == "ESPALIER_STOP_GATE":
        full = "full"
        return _hook_utils.stop_gate_mode(before) == full and _hook_utils.stop_gate_mode(after) != full
    return mode == "full" and bool((before or "").strip()) and (after or "") != before


def _judge_gate_switch(file_path: str | None, source: str,
                       root: Path) -> tuple[list[str], dict | None, str | None]:
    """(the findings for a change to one of the three settings files that
    switches a gate off, the snapshot to record if it is let through, the
    changed file's label) -- ``([], None, None)`` for a change no settings
    file is (DEF-3081).

    Why apart from ``_scan_payload``: hook lists merge across the files (the
    hooks reference), so an emptied hook list in the user file removes no
    project hook and ``_find_kill_switches``' hook arms would be false findings
    there; and no reader judged an ``env`` map, though one reaches the hook
    processes and a user-settings ``env`` change is applied to the running
    session (the settings reference).

    A CHANGE is judged, not the files' state: the values the three files
    supply after it (each key from the highest-precedence file that sets it)
    are compared with SessionStart's snapshot (``_integrity.SETTINGS_GATES_SNAPSHOT``),
    at two layers. The files' layer catches a switch written for every later
    session, even where this session's launch already carries it; the
    session's layer reads a variable no file sets as the launch environment's
    value, so a file value that outranks a stricter launch value is caught. A
    variable a source above the three files owns is not the change's to move.
    No snapshot (a session older than this hook, or a SessionStart cut short)
    takes the values this process runs with as the start. Raises nothing: a
    file it cannot locate judges nothing, said once."""
    try:
        label = _changed_settings_label(file_path, source, root)
        if label is None:
            return [], None, None
        after_values = _integrity.effective_settings_values(root)
    except (OSError, RuntimeError, ValueError) as exc:
        _hook_utils.say_once(
            root, "settings-gate-unreadable", "config_guard", "configchange_failed_open_settings_read",
            f"a settings file could not be located or read ({type(exc).__name__}); "
            "the gate-switch check is skipped",
            fault=type(exc).__name__,
        )
        return [], None, None
    snapshot = _integrity.read_settings_gate_values(root)
    if snapshot is None:
        before: dict = {"env." + n: os.environ[n] for n in _GATE_ENV_NAMES if n in os.environ}
        launch: dict = {}
        owned: list = []
    else:
        before, launch, owned = snapshot["files"], snapshot["launch"], snapshot["owned"]
    after = {key: value for key, (value, _label) in after_values.items()}

    def text(values: dict, key: str) -> str | None:
        value = values.get(key)
        return value if isinstance(value, str) else None

    def session(values: dict, name: str) -> str | None:
        key = "env." + name
        return text(values, key) if key in values else text(launch, name)

    findings: list[str] = []
    dah = _integrity.DISABLE_ALL_HOOKS
    if after.get(dah) is True and before.get(dah) is not True:
        findings.append(f"{after_values[dah][1]}: disableAllHooks: true")
    mode = _hook_utils.stop_gate_mode(session(after, "ESPALIER_STOP_GATE"))
    for name in _GATE_ENV_NAMES:
        if name in owned:
            continue
        key = "env." + name
        if not (_loosens(name, text(before, key), text(after, key), mode)
                or _loosens(name, session(before, name), session(after, name), mode)):
            continue
        where = after_values[key][1] if key in after_values else f"{label} (removed)"
        now, was = text(after, key), session(before, name)
        findings.append(
            f"{where}: env.{name}: {json.dumps(now[:80]) if now is not None else 'unset'} "
            f"(the session runs {json.dumps(was[:80]) if was is not None else 'unset'})"
        )
    return findings, {"files": after, "launch": launch, "owned": owned}, label


def _accept_gate_values(root: Path, record: dict) -> None:
    """A settings change let through: Claude Code now runs the changed files,
    so their values are the start for the next change, and a refused switch
    noted earlier is no longer in them (each judgment reads every file)."""
    try:
        _integrity.write_settings_gate_values(root, record)
        _integrity.clear_switch_pending(root)
    except OSError as exc:
        _hook_utils.say_once(
            root, "settings-gate-snapshot-write", "config_guard", "configchange_failed_open_snapshot_write",
            f"the settings gate snapshot could not be written ({type(exc).__name__}); "
            "the next settings change is judged against the older one",
            fault=type(exc).__name__,
        )


def _scan_payload(file_path: str | None, root: Path) -> list[str]:
    """Scan the candidate settings file for kill-switch findings.

    Falls back to scanning the active settings inventory if the payload's
    `file_path` is missing, unreadable, or points outside the repo root.
    We never crash — best-effort scan, silent on failure.

    Path-traversal guard: stdin-supplied ``file_path`` is bounded to
    ``root`` via ``relative_to``. A traversal payload (``../../etc/passwd``)
    is dropped here so the scanner never opens files outside the repo. The
    user settings file, which Claude Code names by its absolute path, is
    therefore not read here: ``_judge_gate_switch`` reads it by its
    source, since only ``disableAllHooks`` among these shapes switches
    anything off from that file (hook lists merge across the files).
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
        except (OSError, ValueError):  # fail-open: ok deliberate -- an out-of-root or unresolvable spelling falls back to the full settings inventory below; nothing is skipped
            candidate = None

    findings: list[str] = []
    if candidate is not None and candidate.exists():
        try:
            # decode_bom (UTF-8/16/32 BOM-tolerant) — runtime kill-switch
            # reader; a BOM'd settings.json (incl. PowerShell UTF-16) must not
            # evade the live DENY gate.
            data = json.loads(decode_bom(candidate.read_bytes()))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            # Fail open (a settings file mid-edit must stay editable), with
            # voice: the scan of THIS file is skipped, and that is said once.
            data = None
            _hook_utils.say_once(
                root, "settings-unreadable", "config_guard", "configchange_failed_open_settings_read",
                f"{candidate.name} could not be read or parsed ({type(exc).__name__}); its kill-switch scan is skipped",
                fault=type(exc).__name__,
            )
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
        except Exception as e:  # noqa: BLE001 — fail open, with voice
            # A failed scan answers "nothing found" and the change is allowed:
            # said once a session as a record `/status --log` counts, since a
            # stderr line alone reaches the debug log only (exit 0; the pin).
            findings = []
            _hook_utils.say_once(
                root, f"config-scan-{type(e).__name__}", "config_guard",
                "configchange_failed_open_scan",
                f"the kill-switch scan of the settings inventory failed ({type(e).__name__}); "
                "this settings change was allowed unscanned",
                fault=type(e).__name__,
            )
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
    from _hook_utils import read_stdin_safely, say_bad_stdin  # noqa: E402

    data = read_stdin_safely()

    source = data.get("source") or data.get("settings_source") or ""
    file_path = data.get("file_path")
    root = _resolve_project_root()
    say_bad_stdin(root, "config_guard", "configchange_failed_open_bad_stdin", data)

    findings = _scan_payload(file_path, root)
    # The gate switches a settings change can make beyond the kill-switch scan
    # (DEF-3081): the user file's disableAllHooks, and a gate variable in any
    # file's env map, judged against SessionStart's snapshot. Refused like a
    # kill-switch, and noted for the next PostToolUse, since nothing else
    # tells Claude the file still holds it.
    switched: list[str] = []
    accepted: dict | None = None
    changed_label: str | None = None
    if not findings and source not in AUDIT_ONLY_SOURCES:
        switched, accepted, changed_label = _judge_gate_switch(file_path, source, root)
        findings = switched

    # Judged apart from the kill-switch scan (which refuses the
    # change on its own when it finds one): its own record, its own restore.
    if not findings and source not in AUDIT_ONLY_SOURCES and _names_project_settings(file_path, source, root):
        unwired = _unwiring_findings(root)
        if unwired:
            try:
                _integrity.append_audit(
                    root,
                    {"event_type": "configchange_blocked_unwired",
                     "details": {"source": source, "file_path": file_path, "findings": unwired}},
                )
            except Exception:  # noqa: BLE001, S110 -- audit best-effort; hook protocol forbids stderr noise
                pass
            return block(_denial_reasons.GOVERNANCE_GATES_UNWIRED.format(findings=unwired))

    if not findings:
        if accepted is not None:
            _accept_gate_values(root, accepted)
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
                 # A gate switch can name the user file, whose payload path
                 # carries the home directory: its findings name each file by
                 # label, and so does this field.
                 "file_path": changed_label if switched else file_path,
                 "kind": "gate_switch" if switched else "kill_switch",
                 "findings": findings,
             }},
        )
    except Exception:  # noqa: BLE001, S110 -- audit best-effort; hook protocol forbids stderr noise
        pass

    if source in AUDIT_ONLY_SOURCES:
        # ConfigChange cannot block managed policy_settings. The audit record
        # above carries the findings (in the raw log: `/status --log` counts no
        # such type); this stderr line reaches the debug log only (exit 0), and
        # ConfigChange has no channel to Claude at all. Exit 0 with no JSON so
        # Claude Code does not read a structured block.
        # voice: twin the configchange_policy_settings_kill_switch_detected record written above carries these findings in the raw audit log
        print(
            f"[WARN] Espalier-Harness "
            f"{_hook_utils.plural(len(findings), 'kill-switch finding')} in policy_settings: "
            f"{findings}. ConfigChange cannot block managed policy settings; "
            "this is audit-only. Reconcile via your policy authority.",
            file=sys.stderr,
        )
        return 0

    if switched:
        try:
            _integrity.record_switch_pending(root, switched)
        except OSError as exc:
            _hook_utils.say_once(
                root, "settings-switch-note-write", "config_guard", "configchange_failed_open_switch_note",
                f"the refused gate switch could not be noted ({type(exc).__name__}); "
                "the next tool result will not tell it",
                fault=type(exc).__name__,
            )
    return block(_denial_reasons.KILL_SWITCH_DETECTED.format(
        context=f" in {source or 'settings'} change",
        findings=findings,
        # read with a fallback, as write_guard's twin says
        ci_clause=getattr(_denial_reasons, "kill_switch_ci_clause", lambda _root: "")(root),
    ))


if __name__ == "__main__":
    _start_refusal.body_done()  # the module body ends here: a raise past it is main's crash guard's
    raise SystemExit(main())
