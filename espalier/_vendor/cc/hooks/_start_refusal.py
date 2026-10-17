"""The refusal a deny hook emits when it cannot start (DEF-1176, DEF-2010,
DEF-4025, DEF-3008).

Each of the four deny hooks (``write_guard``, ``plan_guard``, ``config_guard``
and ``stop_gate``) imports this module first and alone, then every other
sibling under one guard whose handler calls :func:`refuse_on_helper_skew`. Until
DEF-3008 the floor -- ``_hook_utils``, with ``tools/cc/_json_safe.py`` under
it, and ``_denial_reasons``, with ``_maintenance_mode`` under it -- imported
outside that guard, so a floor module that raised was an exit 1, which the hook
protocol reads as a NON-BLOCKING error: all four guards off and every call let
through unjudged (driven 2026-10-16, 16 of 16). The refusal lived in
``_denial_reasons``, itself on that floor; here none of them is on its path.

So this module imports only the standard library at its top: any sibling may be
the one that failed. It reads ``_hook_utils`` from ``sys.modules`` when that
imported, and imports ``_json_safe`` and ``_integrity`` lazily under
catch-alls. If this module itself cannot import, each hook's own last resort
refuses in its place, naming this file, and ``write_guard``'s lets through the
one restore of it to HEAD.

Stdlib-only. Zero ``espalier`` imports -- runs standalone alongside the rest of
``tools/cc/hooks/``.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import NoReturn


# ── a deny hook that cannot start (DEF-1176, DEF-2010, DEF-4025) ─────
#: The structured refusals a deny hook emits when a sibling import fails at its
#: module top. Under the hook protocol an uncaught exit 1 is a NON-BLOCKING
#: error, so a guard that dies at import judges nothing (measured 2026-10-07
#: and 2026-10-10: every call proceeded unguarded); these are the fail-closed
#: shape instead. Two causes read differently (DEF-2010). A KEPT OLD HELPER: an
#: upgrade kept the tree's ``tools/cc/hooks/_hook_utils.py`` as the adopter's
#: (no managed marker) and regenerated the rest, which import a name the kept
#: copy lacks -- or, on a tree being edited, an edit removed the name or added
#: its import first. ANY OTHER RAISE: the file that raised is named, with its
#: line, and the upgrade is not offered, since it would regenerate the file
#: under edit (the 2026-10-14 and 10-16 lock-outs, each a sibling that raised
#: at import and a refusal that blamed the helper). Composed by
#: :func:`refuse_on_helper_skew` from this module and the standard library
#: alone, since any other sibling may be the one that failed. ``{hook}`` is
#: the hook's stem, ``{error}`` the exception's class and text, ``{restore}``
#: the repair (:func:`_restore_clause`).
HELPER_SKEW = (
    "{hook} cannot start: {taker} takes `{name}` from tools/cc/hooks/_hook_utils.py,"
    " which lacks it ({error}). If an upgrade kept _hook_utils.py as yours (no managed"
    " marker) and regenerated the rest: from a terminal, restore its `# espalier:managed`"
    " marker line and run `espalier upgrade --execute .`. If an edit in progress removed"
    " the name or added its import, restore the edited file to HEAD: {restore}. Every"
    " call this hook judges is refused until then."
)
SIBLING_RAISED = (
    "{hook} cannot start: {file} raised {error} at line {line} while the hook imported"
    " its siblings. No name is missing from tools/cc/hooks/_hook_utils.py, so this is"
    " not a kept old helper and `espalier upgrade` would not repair it. Restore the file"
    " to HEAD: {restore}. Every call this hook judges is refused until then."
)
#: The import failed in a file outside ``tools/cc/`` (never seen: the hook's
#: own frame is under it), so nothing is named to restore.
SIBLING_RAISED_UNPLACED = (
    "{hook} cannot start: a sibling import failed ({error}) and no file under"
    " tools/cc/ is on its traceback. Read the error from a terminal and repair the"
    " file it names. Every call this hook judges is refused until then."
)
#: The context of the one call a wedged PreToolUse hook lets through (DEF-4025):
#: a Bash call that is one command, a restore to HEAD of a file the refusal
#: names. No ``permissionDecision`` goes with it, so the operator's permission
#: mode decides the call as it would any other; the text reaches Claude.
WEDGE_RESTORE_CONTEXT = (
    "{hook} is wedged ({cause}), so it refuses every call but one: a restore to"
    " HEAD of a file its refusal names. This call restores {file}, so it was let"
    " through. {copy} The next call is judged by the restored hook; if it still"
    " cannot start, its refusal names what raised next."
)

#: The module's operator-facing templates. Declaring the registry puts every
#: string constant here under the portability contract's rule (e), as
#: ``_denial_reasons``'s does; unlike that module's, these carry no Don't/Do
#: pair, which only its registry asks.
_OPERATOR_FACING_TEMPLATES: tuple[str, ...] = (
    "HELPER_SKEW", "SIBLING_RAISED", "SIBLING_RAISED_UNPLACED", "WEDGE_RESTORE_CONTEXT",
)

#: The Bash command words a restore may not contain: a separator, a pipe, a
#: redirect, an expansion, a substitution, a glob, a group or a comment (a
#: second command, or an operand the shell would rewrite). Quotes and the
#: backslash are read as the shell reads them (``shlex``).
_RESTORE_SHELL_CHARS = frozenset(";&|<>$`(){}*?[]~!#\n\r\x00")
#: The longest restore command read; past it the call is refused unread.
_RESTORE_COMMAND_CAP = 4096
#: The deny hooks a Bash call reaches: ``write_guard`` is wired for every
#: tool; ``plan_guard`` matches Write, Edit and NotebookEdit, and the
#: ConfigChange and Stop hooks judge no tool call. Only these let a restore
#: through, and only their refusals offer one; the others name the terminal.
_LETS_A_RESTORE_THROUGH = frozenset({"write_guard"})


class _SkewReading:
    """What a failed start can say about itself: the file that raised (an
    absolute path under ``tools/cc/``) and its line, the helper name a sibling
    takes and ``_hook_utils`` lacks (the kept-old-helper test), and the files
    whose restore to HEAD the refusal names and lets through: the raising file
    first, then (on the kept-helper test) ``_hook_utils.py``, then every other
    ``tools/cc/`` file on the traceback, inner to outer."""

    def __init__(self, file: Path | None, line: int | None, missing: str | None,
                 restorable: list[Path], cc_dir: Path) -> None:
        self.file = file
        self.line = line
        self.missing = missing
        self.restorable = restorable
        self.cc_dir = cc_dir

    def rel(self, path: Path) -> str:
        """``path`` as the repository spells it, ``tools/cc/...``."""
        return "tools/cc/" + path.relative_to(self.cc_dir).as_posix()


def _under(path: Path, cc_dir: Path) -> bool:
    try:
        path.relative_to(cc_dir)
    # fail-open: ok deliberate a path outside tools/cc is an answer, not a fault
    except ValueError:
        return False
    return True


def _missing_helper_name(exc: BaseException) -> str | None:
    """The kept-old-helper test: the name a sibling takes from ``_hook_utils``
    that the loaded ``_hook_utils`` lacks, or None. Read from the exception's
    own fields (an ``ImportError`` from ``from _hook_utils import <name>``, an
    ``AttributeError`` on the ``_hook_utils`` module object), then checked
    against the module, so an error raised for any other reason never reads as
    a kept helper."""
    helper = sys.modules.get("_hook_utils")
    if helper is None:
        return None
    name: object = None
    if isinstance(exc, ImportError) and exc.name == "_hook_utils":
        name = getattr(exc, "name_from", None)
        if not isinstance(name, str):
            text = str(exc)
            if text.startswith("cannot import name '"):
                name = text[len("cannot import name '"):].split("'", 1)[0]
    elif isinstance(exc, AttributeError) and getattr(exc, "obj", None) is helper:
        name = exc.name
    if isinstance(name, str) and name and not hasattr(helper, name):
        return name
    return None


def _module_the_error_names(exc: BaseException, cc_dir: Path) -> Path | None:
    """The file of the ``tools/cc/`` module an import-time error names, when it
    is not where the error was raised: the module an ``AttributeError`` was
    read on, or the one a ``from <module> import <name>`` failed on. A name
    renamed or removed in one floor module raises in the module that reads it,
    so the file the edit is in is this one, not the raiser's (DEF-3008, the
    failure-mode review: a rename in ``_maintenance_mode.py`` named only
    ``_denial_reasons.py``). Never raises: None when nothing is named."""
    try:
        module: object = None
        if isinstance(exc, AttributeError):
            module = getattr(exc, "obj", None)
        elif isinstance(exc, ImportError) and isinstance(exc.name, str):
            module = sys.modules.get(exc.name)
        source = getattr(module, "__file__", None) if isinstance(module, types.ModuleType) else None
        if not isinstance(source, str):
            return None
        path = Path(source).resolve()
        return path if _under(path, cc_dir) else None
    # fail-open: ok deliberate an error that cannot be read names no further file
    except Exception:  # noqa: BLE001
        return None


def wedge_reading(exc: BaseException) -> _SkewReading | None:
    """Read a failed start (or, for the crash guard, a fault after it): the
    innermost traceback frame in a file under ``tools/cc/`` -- or, for a
    ``SyntaxError``, which has no frame in the file it names, that file -- and
    the kept-old-helper test. The file that raised is often not the file that
    was edited (a circular import raises in the module it re-enters, a bad
    argument in the helper it was handed to, a new module's import in the new
    module), so every ``tools/cc/`` file on the traceback may be restored, and
    ``_hook_utils.py`` too when the test holds; a restore to HEAD of any of
    them re-enables the committed guard and can disable nothing. It reads
    the exception's class, traceback, ``filename`` and the name a sibling
    takes, never renders its text, so the crash guard may hand it a caught
    OSError (the portability roster's argued entry). Never raises: None when
    nothing can be read."""
    try:
        cc_dir = Path(__file__).resolve().parent.parent
        file: Path | None = None
        line: int | None = None
        if isinstance(exc, SyntaxError) and exc.filename:
            named = Path(exc.filename).resolve()
            if _under(named, cc_dir):
                file, line = named, exc.lineno
        chain: list[tuple[Path, int]] = []
        tb = exc.__traceback__
        while tb is not None:
            frame_file = Path(tb.tb_frame.f_code.co_filename)
            if frame_file.is_absolute() or frame_file.exists():
                resolved = frame_file.resolve()
                if _under(resolved, cc_dir):
                    chain.append((resolved, tb.tb_lineno))
            tb = tb.tb_next
        if file is None and chain:
            file, line = chain[-1]
        missing = _missing_helper_name(exc)
        restorable: list[Path] = [file] if file is not None else []
        if missing is not None:
            restorable.append(cc_dir / "hooks" / "_hook_utils.py")
        read_on = _module_the_error_names(exc, cc_dir)
        if read_on is not None and read_on not in restorable:
            restorable.append(read_on)
        for outer, _line in reversed(chain):
            if outer not in restorable:
                restorable.append(outer)
        return _SkewReading(file, line, missing, restorable, cc_dir)
    # fail-open: ok text-fallback the refusal goes out unplaced
    except Exception:  # noqa: BLE001
        return None


def _restore_clause(reading: _SkewReading, lets_through: bool) -> str:
    """The repair a refusal names: a restore to HEAD of the file that raised
    (``--source=HEAD``: a bare ``git restore`` reads the index, which keeps a
    staged break and refuses an unmerged path), and of the file you edited
    when it is another one on the traceback. ``lets_through`` says the hook
    passes one such Bash command; otherwise the terminal is the route (a Bash
    call meets ``write_guard``, which judges it as any other call)."""
    first, *others = [reading.rel(p) for p in reading.restorable]
    clause = f"`git restore --source=HEAD -- {first}`"
    if others:
        clause += (" (or the same command for the file you edited, if it is "
                   + " or ".join(others) + ")")
    if lets_through:
        return (clause + ", as one Bash command, is the one call this hook lets through"
                " while it is wedged, and it saves the file's bytes under"
                " .espalier-state/wedge-restore/ first; or run it from a terminal")
    return clause + ", run from a terminal (a Bash call meets write_guard, which judges it as any other)"


def _restore_operand(words: list[str]) -> str | None:
    """The one path a restore to HEAD names, or None for any other command:
    ``git restore [--source=HEAD | -s HEAD | --worktree | -W] [--] <path>``,
    ``git checkout -- <path>`` or ``git checkout HEAD -- <path>``. Any other
    option (``--staged`` restores the index, not the file), ref or operand
    count is refused."""
    if len(words) < 3 or words[0] != "git":
        return None
    verb, rest = words[1], words[2:]
    operands: list[str] = []
    if verb == "restore":
        ended = False
        i = 0
        while i < len(rest):
            word = rest[i]
            if ended or not word.startswith("-"):
                operands.append(word)
            elif word == "--":
                ended = True
            elif word in ("--source=HEAD", "--worktree", "-W"):
                pass
            elif word in ("--source", "-s") and rest[i + 1:i + 2] == ["HEAD"]:
                i += 1
            else:
                return None
            i += 1
    elif verb == "checkout":
        if rest[:1] == ["--"]:
            operands = rest[1:]
        elif rest[:2] == ["HEAD", "--"]:
            operands = rest[2:]
        else:
            return None
    else:
        return None
    return operands[0] if len(operands) == 1 else None


def _restore_target(payload: object, reading: _SkewReading) -> Path | None:
    """The restorable file this call restores to HEAD, or None (DEF-4025):
    a Bash call whose command is one ``git restore`` or ``git checkout --`` of
    exactly one file the refusal names. A relative operand resolves against the
    payload's ``cwd``; forward and back slashes both read. Standard library
    only: ``_bash_patterns`` may be the module that raised."""
    import os
    import shlex

    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or len(command) > _RESTORE_COMMAND_CAP:
        return None
    if _RESTORE_SHELL_CHARS & set(command):
        return None
    try:
        words = shlex.split(command, posix=True)
    # fail-open: ok deliberate an unbalanced quote is no restore, and is refused
    except ValueError:
        return None
    operand = _restore_operand(words)
    # A trailing space or dot is dropped by the Windows path layer, so the
    # path would read equal to a named file while git reads another one.
    if not operand or operand != operand.strip() or operand.endswith("."):
        return None
    cwd = payload.get("cwd")
    base = Path(cwd) if isinstance(cwd, str) and cwd else Path(os.getcwd())
    target = Path(operand.replace("\\", "/"))
    if not target.is_absolute():
        target = base / target
    wanted = os.path.normcase(str(target.resolve()))
    for path in reading.restorable:
        if os.path.normcase(str(path.resolve())) == wanted:
            return path
    return None


def _read_payload() -> dict | None:
    """The hook's stdin as a JSON object, or None (anything else, unreadable
    included). The floor helper's reader is not used: the kept helper may
    lack it."""
    import json

    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    # fail-open: ok deliberate an unread payload lets nothing through
    except Exception:  # noqa: BLE001
        return None
    return payload if isinstance(payload, dict) else None


def wedge_restore(hook: str, reading: _SkewReading | None, error: str,
                  payload: object) -> tuple[str, dict] | None:
    """The one call a wedged PreToolUse hook lets through (DEF-4025): when
    ``payload`` restores to HEAD a file ``reading`` (:func:`wedge_reading`)
    names, save the file's bytes under ``.espalier-state/wedge-restore/`` and
    return the context to send and the record's details; else None. ``error``
    is the exception's class name. A failed copy never blocks the restore, and
    the context says so. Never raises."""
    try:
        if reading is None or not reading.restorable:
            return None
        target = _restore_target(payload, reading)
        if target is None:
            return None
        rel = reading.rel(target)
        raiser = reading.rel(reading.file) if reading.file is not None else "a sibling"
        if reading.missing is not None:
            cause = f"{raiser} takes `{reading.missing}`, which tools/cc/hooks/_hook_utils.py lacks"
        else:
            cause = f"{raiser} raised {error}"
        copy = _save_before_restore(target, reading.cc_dir)
        context = WEDGE_RESTORE_CONTEXT.format(hook=hook, cause=cause, file=rel, copy=copy)
        return context, {"hook": hook, "file": rel, "error": error}
    # fail-open: ok deliberate a reading that faults lets nothing through
    except Exception:  # noqa: BLE001
        return None


def _state_dir_from_source(cc_dir: Path) -> str | None:
    """The helper's ``STATE_DIR``, read from its source when the helper itself
    cannot import (DEF-3008), so the copy is still saved and the spelling keeps
    its one home there. None unless the line is one plain assignment of a
    name that stays inside the checkout."""
    import re

    try:
        text = (cc_dir / "hooks" / "_hook_utils.py").read_text(encoding="utf-8", errors="replace")
    # fail-open: ok deliberate an unreadable helper names no state directory; the restore goes through uncopied
    except OSError:
        return None
    found = re.search(r'^STATE_DIR = "([A-Za-z0-9._-]+)"$', text, re.MULTILINE)
    if found is None or ".." in found.group(1):
        return None
    return found.group(1)


def _save_before_restore(target: Path, cc_dir: Path) -> str:
    """Copy ``target``'s bytes to ``<root>/<state dir>/wedge-restore/`` and say
    where; the discard speed bump's snapshot cannot run while the hook is
    wedged, and the restore discards the file's uncommitted edit."""
    import datetime

    try:
        # The state directory's one spelling is the helper's. A helper that
        # did not import (DEF-3008: the file under edit, likeliest of all)
        # still gets its copy, its spelling read from its source; a kept
        # helper that names none gets no copy, and the restore still goes
        # through.
        helper = sys.modules.get("_hook_utils")
        state = _state_dir_from_source(cc_dir) if helper is None else getattr(helper, "STATE_DIR", None)
        if not isinstance(state, str) or not state:
            return "No copy was saved first (the helper names no state directory)."
        if not target.is_file():
            return "There was no file to copy first."
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest_dir = cc_dir.parent.parent / state / "wedge-restore"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{target.stem}-{stamp}.py.txt"
        dest.write_bytes(target.read_bytes())
        return f"Its bytes as they were are saved at {dest.relative_to(cc_dir.parent.parent).as_posix()}."
    except Exception as err:  # noqa: BLE001 -- fail-open: ok copy-failed the restore still goes through, and says so
        return f"No copy was saved first ({type(err).__name__})."


def crash_refusal(reading: _SkewReading | None, error: str,
                  read_payload: bool) -> tuple[dict, dict] | None:
    """The crash guard's named refusal (DEF-4025's twin): the fields of
    ``_denial_reasons.WRITE_GUARD_CRASHED_AT`` naming the innermost ``tools/cc/`` frame of
    ``reading`` (:func:`wedge_reading`) by ``error``, the exception's class
    name, and its line, with the record's details; None when no frame is
    placed. The guard formats the template at its deny site, so the
    deny-marker contract reads the reason there. ``read_payload`` is whether
    the guard read the call before it crashed: a crash in the read lets
    nothing through, so its text offers the terminal alone. Never raises."""
    try:
        if reading is None or reading.file is None:
            return None
        rel = reading.rel(reading.file)
        fields = {"error": error, "file": rel, "line": reading.line,
                  "restore": _restore_clause(reading, read_payload)}
        return fields, {"file": rel, "line": reading.line}
    # fail-open: ok text-fallback today's unplaced text goes out
    except Exception:  # noqa: BLE001
        return None


def refuse_on_helper_skew(hook: str, event: str, exc: BaseException) -> NoReturn:
    """Emit the fail-closed refusal for a deny hook whose sibling import failed
    at module top, then exit 0: the structured channel, where an exit 1 would be
    read as non-blocking. ``event`` picks the decision shape -- ``PreToolUse``
    emits ``hookSpecificOutput.permissionDecision: deny``, ``ConfigChange`` and
    ``Stop`` the Stop-style ``{"decision": "block"}``. The text names the file
    that raised and its line, and offers the upgrade only on the kept-old-helper
    test (DEF-2010). On ``PreToolUse`` the payload is read first, and a Bash
    restore to HEAD of a file the refusal names is let through instead, with
    context and no decision (DEF-4025, :func:`wedge_restore`). On ``Stop`` the
    payload is read too, and the protocol's loop signal (``stop_hook_active``)
    exits 0 with nothing, so the block is a pause, never a lockout. Standard library
    and this module only: ``_hook_utils``, ``_denial_reasons`` and ``_integrity``
    may each be the module that failed (DEF-3008), so the helper is read from
    ``sys.modules`` when it imported, the audit record is best-effort, and the
    exception's text routes through ``_json_safe``'s
    ``os_error_text`` (never the helper's, which may be the name missing), with
    ``str`` as the floor. The record types are composed, never literals, so the
    crash-guard census does not read this module as a fifth blocking hook: the
    refusal's is the crash guard's, ``<event>_blocked_internal_error`` with
    ``details.skew`` naming the cause, and the let-through's is a fail-open
    record, ``<event>_failed_open_wedge_restore``, so no roster or documented
    table grows. One channel per decision: nothing on stderr. Pinned by
    ``tests/test_hooks_start_on_a_kept_helper.py``."""
    import json

    if event == "Stop":
        # The protocol's loop signal: this Stop is the one Claude Code continued
        # after the refusal blocked the last, so it goes through -- a pause,
        # never a lockout (docs/external/cc-hook-protocol.md).
        payload = _read_payload()
        if payload is not None and payload.get("stop_hook_active"):
            raise SystemExit(0)
    reading = wedge_reading(exc)
    lets_through = event == "PreToolUse" and hook in _LETS_A_RESTORE_THROUGH
    if lets_through:
        passed = wedge_restore(hook, reading, type(exc).__name__, _read_payload())
        if passed is not None:
            context, passed_details = passed
            _record(f"{event.lower()}_failed_open_wedge_restore", passed_details)
            sys.stdout.write(json.dumps({"hookSpecificOutput": {
                "hookEventName": event, "additionalContext": context}}) + "\n")
            sys.stdout.flush()
            raise SystemExit(0)
    # The seam renders an OSError's path as a path (a Windows path through
    # str() is its repr, backslashes doubled); it lives one directory up in
    # tools/cc, beside the hooks and regenerated with them, never in the kept
    # helper -- so the cross-directory shim the other hooks use goes first (a
    # fresh adopter's hook process has only the hooks directory on its path).
    # str is the floor if even that cannot import.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tools/cc for _json_safe
    try:
        from _json_safe import os_error_text  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 -- fail-open: ok text-fallback the refusal still goes out, with the plain text
        os_error_text = str  # type: ignore[assignment]
    details: dict = {"hook": hook, "error": type(exc).__name__, "skew": "sibling import"}
    # The text is composed under a catch-all: an escape here would be the
    # exit 1 this refusal exists to replace (DEF-1176), so a template that
    # cannot format falls back to plain words that cannot raise.
    try:
        error = f"{type(exc).__name__}: {os_error_text(exc)}"
        if reading is not None and reading.file is not None:
            details.update(file=reading.rel(reading.file), line=reading.line)
        if reading is not None and reading.missing is not None and reading.file is not None:
            reason = HELPER_SKEW.format(hook=hook, taker=reading.rel(reading.file), name=reading.missing,
                                        error=error, restore=_restore_clause(reading, lets_through))
            details["cause"] = "kept helper"
        elif reading is not None and reading.file is not None:
            details["cause"] = "raised"
            reason = SIBLING_RAISED.format(hook=hook, file=reading.rel(reading.file), error=error,
                                           line=reading.line, restore=_restore_clause(reading, lets_through))
        else:
            reason = SIBLING_RAISED_UNPLACED.format(hook=hook, error=error)
    # fail-open: ok text-fallback the refusal still goes out, in plain words
    except Exception:  # noqa: BLE001
        reason = (str(hook) + " cannot start: a sibling import failed (" + type(exc).__name__
                  + "), and its text could not be composed. Read the error from a terminal;"
                  " every call this hook judges is refused until then.")
    _record(f"{event.lower()}_blocked_internal_error", details)
    output: dict
    if event in ("ConfigChange", "Stop"):
        output = {"decision": "block", "reason": reason}
    else:
        output = {"hookSpecificOutput": {
            "hookEventName": event, "permissionDecision": "deny", "permissionDecisionReason": reason}}
    sys.stdout.write(json.dumps(output) + "\n")
    sys.stdout.flush()
    raise SystemExit(0)


def _record(event_type: str, details: dict) -> None:
    """A best-effort audit record for a hook that cannot start: ``_integrity``
    may be the module that failed."""
    try:
        import _hook_utils  # type: ignore[import-not-found]
        import _integrity  # type: ignore[import-not-found]
        _integrity.append_audit(
            _hook_utils.resolve_project_root(), {"event_type": event_type, "details": details}, quiet=True)
    except Exception:  # noqa: BLE001, S110 -- a best-effort record; the decision is the point
        pass
