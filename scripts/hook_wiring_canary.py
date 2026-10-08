#!/usr/bin/env python3
"""Say so when a session on an Espalier tree starts without the tree's own hooks.

A user-scope SessionStart hook, installed in the operator's ``~/.claude/settings.json``
rather than in any repository: user hooks load in every session, whatever the
project's settings say, so this is the one place a missing project hook can be
noticed. A missing hook cannot report its own absence.

Why it exists (measured 2026-10-08, Windows clone): two sessions launched in a
Claude Code worktree of this repo ran with no hooks at all. Claude Code reads the
shared ``.claude/settings.json`` from the session's primary working directory
(code.claude.com/docs/en/settings), the file is gitignored, and a worktree checks
out tracked files only. ``/hooks`` listed none; no banner, guard or stop gate ran.
The same holds for a session launched in a subdirectory of the repository.

What it does: reads the SessionStart payload, finds the session's directory
(``CLAUDE_PROJECT_DIR``, else the payload's ``cwd``), and walks up to the nearest
directory holding ``tools/cc/hooks/session_start.py`` -- an Espalier tree. Outside
one it prints nothing. Inside one it checks the settings file Claude Code reads
(the session directory's ``.claude/settings.json``) for a SessionStart entry that
runs ``tools/cc/hooks/session_start.py``. When that is missing it tells the
operator (``systemMessage``, shown in the interface) and Claude
(``additionalContext``). It always exits 0: SessionStart cannot block.

It checks the banner's wiring only. The landing check's wiring arm
(``scripts/check_handoff_landing.py::check_hook_wiring_arm``) judges every
blocking gate before a push.

Install, per machine (the operator's call; nothing installs it):

1. Copy this file to ``~/.claude/hooks/espalier_hook_wiring_canary.py``.
2. Add to ``~/.claude/settings.json``, merging into any ``hooks`` block already
   there, with the interpreter this machine answers to (``python`` on the Windows
   clone, ``python3`` on macOS) and the absolute path::

       {"hooks": {"SessionStart": [{"hooks": [{"type": "command",
           "command": "python",
           "args": ["C:/Users/<you>/.claude/hooks/espalier_hook_wiring_canary.py"]}]}]}}

3. Check it in a fresh session in a worktree that lacks the settings file: the
   interface shows the warning.

Stdlib only, by design: it runs in every project on the machine.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SESSION_START_SCRIPT = "tools/cc/hooks/session_start.py"
SETTINGS_REL = ".claude/settings.json"


def espalier_root(start: Path) -> Path | None:
    """The nearest directory at or above ``start`` that holds the banner's script."""
    for candidate in (start, *start.parents):
        if (candidate / SESSION_START_SCRIPT).is_file():
            return candidate
    return None


def _runs_session_start(hook: object) -> bool:
    """One hook entry that executes the banner's script by path, as ``init`` writes
    it (``command`` the interpreter, the script in ``args``) or in one command
    string. A path that only appears in an ``echo`` still matches here; the
    landing check's arm reads the exec form strictly."""
    if not isinstance(hook, dict) or hook.get("type") != "command":
        return False
    words: list[str] = []
    if isinstance(hook.get("command"), str):
        words.append(hook["command"])
    args = hook.get("args")
    if isinstance(args, list):
        words.extend(a for a in args if isinstance(a, str))
    return any(w.replace("\\", "/").rstrip("'\" ").endswith(SESSION_START_SCRIPT)
               for w in words)


def missing_wiring(session_dir: Path) -> str | None:
    """Why the banner will not fire for a session started in ``session_dir``, or
    None when it is wired or the directory is not in an Espalier tree."""
    root = espalier_root(session_dir)
    if root is None:
        return None
    settings = session_dir / SETTINGS_REL
    where = (f"{session_dir}" if session_dir == root
             else f"{session_dir}, a subdirectory of the Espalier tree at {root}")
    if not settings.is_file():
        return (f"no {SETTINGS_REL} in {where}. Claude Code reads that file from the "
                "directory the session started in; a worktree checks out tracked files "
                "only, and the file is gitignored")
    try:
        data = json.loads(settings.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        return f"{settings} could not be read ({type(exc).__name__})"
    hooks = data.get("hooks") if isinstance(data, dict) else None
    groups = hooks.get("SessionStart") if isinstance(hooks, dict) else None
    if isinstance(groups, list):
        for group in groups:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if isinstance(inner, list) and any(_runs_session_start(h) for h in inner):
                return None
    return f"{settings} has no SessionStart entry that runs {SESSION_START_SCRIPT}"


def _session_dir(stdin_text: str, environ: "dict[str, str]") -> Path:
    project = environ.get("CLAUDE_PROJECT_DIR")
    if project:
        return Path(project)
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
    except ValueError:
        payload = {}
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    return Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()


def main(stdin_text: str | None = None, environ: "dict[str, str] | None" = None) -> int:
    text = sys.stdin.read() if stdin_text is None else stdin_text
    env = dict(os.environ) if environ is None else environ
    try:
        session_dir = _session_dir(text, env)
        in_tree = espalier_root(session_dir) is not None
    except Exception:  # noqa: BLE001 -- cannot even tell it is an Espalier tree: stay quiet,
        return 0       # since this hook runs in every project on the machine
    if not in_tree:
        return 0
    try:
        reason = missing_wiring(session_dir)
    except Exception as exc:  # noqa: BLE001 -- inside a tree, a canary that cannot tell says so
        reason = f"the hook-wiring canary could not check ({type(exc).__name__}: {exc})"
    if reason is None:
        return 0
    message = (f"Espalier's hooks did NOT load for this session: {reason}. "
               "No banner, guard or stop gate is running. `/hooks` lists what loaded.")
    print(json.dumps({
        "systemMessage": message,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (message + " Say so in your first reply and make no "
                                  "edits until the operator answers."),
        },
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
