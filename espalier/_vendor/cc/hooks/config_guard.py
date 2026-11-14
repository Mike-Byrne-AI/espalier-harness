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
settings ``env`` map, which reaches every hook process -- is refused the same
way and told at the next PostToolUse (``_gate_switch_findings``, DEF-3081). It is
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


#: The variables that switch a gate when set: write_guard's harness roster
#: (``write_guard._HARNESS_ENV_NAMES``, which refuses an in-session assignment
#: of each; tests/test_hook_constant_parity.py pins the two equal). The stop
#: gate's two are literals for write_guard's reason (that roster's comment).
_GATE_ENV_NAMES: tuple[str, ...] = (
    _maintenance_mode.ENV_VAR,
    "ESPALIER_STOP_GATE",
    "ESPALIER_STOP_GATE_TEST_CMD",
)
_USER_SOURCE = "user_settings"
#: The two project files, highest precedence first: Claude Code reads
#: ``disableAllHooks`` and each ``env`` variable from the highest-precedence
#: file that sets it -- local, then project, then user (the settings reference).
_PROJECT_FILES = (
    ("local_settings", ".claude/settings.local.json"),
    ("project_settings", _integrity.PROJECT_SETTINGS_REL),
)


def _user_settings_label() -> str:
    """How a finding names the user settings file: never by its absolute path,
    so the audit log carries no home directory. ``CLAUDE_CONFIG_DIR`` moves the
    file (the settings reference), and a hook inherits it from the session."""
    if os.environ.get("CLAUDE_CONFIG_DIR", "").strip():
        return "$CLAUDE_CONFIG_DIR/settings.json"
    return "~/.claude/settings.json"


def _user_settings_path() -> Path:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return (Path(config_dir).expanduser() if config_dir else Path.home() / ".claude") / "settings.json"


def _changed_settings(file_path: str | None, source: str, root: Path) -> tuple[int, str, Path] | None:
    """The settings file Claude Code says changed, as (its rank among the
    three, highest precedence 0; its label; its path), or None for a change no
    settings file of the three is (a skill, managed policy, a path elsewhere).

    The user file is named by the source: Claude Code gives its absolute path
    (``source: user_settings``, the hooks reference), which no root bound can
    hold, so the path is taken as given where it names a ``settings.json``, and
    looked up where the payload has none. A project file is matched by
    location inside the root, as ``_names_project_settings`` matches it, so a
    path outside the tree opens nothing."""
    if source == _USER_SOURCE:
        if file_path and Path(file_path).name != "settings.json":
            return None
        return len(_PROJECT_FILES), _user_settings_label(), Path(file_path) if file_path else _user_settings_path()
    for rank, (name, rel) in enumerate(_PROJECT_FILES):
        if file_path:
            path = Path(file_path)
            if not path.is_absolute():
                path = root / path
            if path.parent.resolve() / path.name == (root / rel).parent.resolve() / Path(rel).name:
                return rank, rel, root / rel
        elif source == name:
            return rank, rel, root / rel
    return None


def _read_settings(path: Path) -> object:
    """The file's JSON, or None where it is absent or cannot be read."""
    try:
        return json.loads(decode_bom(path.read_bytes()))
    except FileNotFoundError:  # fail-open: ok deliberate -- an absent file sets nothing
        return None


def _read_higher(path: Path) -> object:
    """A higher-precedence file's JSON, or None: one that cannot be read is
    taken to set nothing, so the changed file's value is judged (the refusal
    side); ``_scan_payload`` says an unreadable project file once already."""
    try:
        return _read_settings(path)
    except (OSError, ValueError):  # fail-open: ok deliberate -- an unreadable higher file overrides nothing; the changed file is still judged
        return None


def _env_text(value: object) -> str | None:
    """An ``env`` value as the string a subprocess receives; None for a value
    that is not a string or a number."""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _loosens(name: str, value: str, live: str | None) -> bool:
    """``value`` would loosen the gate ``name`` switches, against the value
    this hook process runs with (``live``), each read by its gate's own
    grammar: the maintenance switch turned on, the stop gate moved off
    ``full`` (``light`` is the default floor, so turning it on tightens), and
    the suite command the stop gate runs replaced at all, as write_guard
    refuses every in-session assignment of it."""
    if name == _maintenance_mode.ENV_VAR:
        active = _maintenance_mode._maintenance_mode_active
        return active(value) and not active(live)
    if name == "ESPALIER_STOP_GATE":
        full = "full"
        return _hook_utils.stop_gate_mode(live) == full and _hook_utils.stop_gate_mode(value) != full
    return value != (live or "")


def _gate_switch_findings(file_path: str | None, source: str, root: Path) -> list[str]:
    """The findings for a change to one of the three settings files that
    switches a gate off (DEF-3081), naming only what the CHANGED file
    supplies: ``disableAllHooks: true`` from the user file, and a gate
    variable in any file's ``env`` map that loosens its gate.

    Why apart from ``_scan_payload``: hook lists merge across the files (the
    hooks reference), so an emptied hook list in the user file removes no
    project hook and ``_find_kill_switches``' hook arms would be false findings
    there; and no reader judged an ``env`` map, though one reaches every hook
    process (driven 2026-11-14) and a user-settings ``env`` change is applied
    to the running session (the settings reference).

    A value a higher-precedence file sets for the same key is not this file's
    to supply, and a gate variable is judged against this hook process's own
    value, so a switch already in effect when the session started (the
    operator's launch) refuses nothing. Raises nothing: a path or file it
    cannot read judges nothing, said once for the user file (a project file's
    unreadable read is ``_scan_payload``'s to say)."""
    try:
        changed = _changed_settings(file_path, source, root)
        if changed is None:
            return []
        rank, label, path = changed
        data = _read_settings(path)
        higher = [_read_higher(root / rel) for _name, rel in _PROJECT_FILES[:rank]]
    except (OSError, RuntimeError, ValueError) as exc:
        if source == _USER_SOURCE:
            _hook_utils.say_once(
                root, "user-settings-unreadable", "config_guard", "configchange_failed_open_user_settings_read",
                f"the user settings file could not be read or parsed ({type(exc).__name__}); "
                "its gate-switch check is skipped",
                fault=type(exc).__name__,
            )
        return []
    if not isinstance(data, dict):
        return []
    higher_dicts = [d for d in higher if isinstance(d, dict)]

    def set_above(key: str, env_name: str | None = None) -> bool:
        for d in higher_dicts:
            holder = d.get("env") if env_name else d
            if isinstance(holder, dict) and (env_name or key) in holder:
                return True
        return False

    findings: list[str] = []
    if rank == len(_PROJECT_FILES) and data.get("disableAllHooks") is True and not set_above("disableAllHooks"):
        findings.append(f"{label}: disableAllHooks: true")
    env = data.get("env")
    if isinstance(env, dict):
        for name in _GATE_ENV_NAMES:
            value = _env_text(env.get(name))
            if value is None or set_above("env", name):
                continue
            live = os.environ.get(name)
            if _loosens(name, value, live):
                now = json.dumps(live[:80]) if live is not None else "unset"
                findings.append(f"{label}: env.{name}: {json.dumps(value[:80])} (this session: {now})")
    return findings


def _scan_payload(file_path: str | None, root: Path) -> list[str]:
    """Scan the candidate settings file for kill-switch findings.

    Falls back to scanning the active settings inventory if the payload's
    `file_path` is missing, unreadable, or points outside the repo root.
    We never crash — best-effort scan, silent on failure.

    Path-traversal guard: stdin-supplied ``file_path`` is bounded to
    ``root`` via ``relative_to``. A traversal payload (``../../etc/passwd``)
    is dropped here so the scanner never opens files outside the repo. The
    user settings file, which Claude Code names by its absolute path, is
    therefore not read here: ``_gate_switch_findings`` reads it by its
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
    # The gate switches a settings file can carry beyond the kill-switch scan
    # (DEF-3081): the user file's disableAllHooks, and a gate variable in any
    # file's env map. Refused like a kill-switch, and noted for the next
    # PostToolUse, since nothing else tells Claude the file still holds it.
    switched: list[str] = []
    if not findings and source not in AUDIT_ONLY_SOURCES:
        switched = findings = _gate_switch_findings(file_path, source, root)

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
        _integrity.record_switch_pending(root, switched)
    return block(_denial_reasons.KILL_SWITCH_DETECTED.format(
        context=f" in {source or 'settings'} change",
        findings=findings,
        # read with a fallback, as write_guard's twin says
        ci_clause=getattr(_denial_reasons, "kill_switch_ci_clause", lambda _root: "")(root),
    ))


if __name__ == "__main__":
    _start_refusal.body_done()  # the module body ends here: a raise past it is main's crash guard's
    raise SystemExit(main())
