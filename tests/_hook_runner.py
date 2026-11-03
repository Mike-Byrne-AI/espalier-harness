"""The suite's shared hook runners: the source script under ``HOOK_PYTHON``, and
the entry an adopter's ``.claude/settings.json`` wires, launched as Claude Code
launches it.

``run_hook`` is the one most hook tests use: it spawns ``tools/cc/hooks/<name>``
from this checkout with ``HOOK_PYTHON``, so a test reads the hook's verdict on
any host. It says nothing about whether the hook starts on an adopter's
machine: the interpreter Claude Code runs there is the name ``init`` wired,
resolved on that machine's PATH, and a name that resolves to something that
cannot run a hook (a Store alias, a launcher with no Python behind it) leaves
every guard open while the source-script runs stay green.

``run_hook_as_wired`` is the other half. It reads the wired entry for the
hook, resolves its ``command`` on the PATH it is given (``shutil.which``, as a
spawn by name does), passes its ``args`` verbatim with ``${CLAUDE_PROJECT_DIR}``
expanded, and runs it rooted in the tree. A missing entry, a shell-form entry
and a command that does not resolve each raise: a wiring that cannot launch is
the finding, never a skip. ``tests/test_hooks_as_wired.py`` runs every wired
entry this way on each adopter stack and interpreter host shape.

A wired launch is never a parent-pid oracle: on a Windows venv the wired
``python`` resolves through PATH to the venv's redirector, which starts the
interpreter as its own child, so the hook's parent is not this process. A test
asserting on ``os.getppid()`` spawns through ``run_hook``
(``tests/test_test_suite_contract.py`` pins the form).

``iter_hooks`` and ``script_arg`` read the exec-form entries, shared with
``tests/test_hook_exec_form.py``; ``NOOP_INPUT`` is one event's input that
judges nothing, shared with the lifecycle Walk.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from tests._hook_spawn import not_a_budget_miss, run_hook_through
from tests._interpreter_hosts import HOOK_PYTHON

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"

#: One wired launch's bound: past ``tests/_hook_spawn.py::HOOK_S``, so the
#: result goes through ``not_a_budget_miss`` (a write_guard budget refusal is a
#: miss, never a verdict), and under the 60 s per-test ceiling.
WIRED_S = 45

#: The launcher's version flag ``init`` writes ahead of the hook script when
#: only the Windows launcher answers (``py -3 <hook>``).
LAUNCHER_FLAG = re.compile(r"-3(\.\d+)?(-(32|64|arm64))?")

#: A no-op input per event, for launching a wired hook once: enough fields for
#: the hook to parse and judge nothing, never a write. A ConfigChange launch
#: also names the tree's own settings file as its ``file_path``.
NOOP_INPUT: dict[str, dict] = {
    "PreToolUse": {"tool_name": "Read", "tool_input": {"file_path": "notes.txt"}},
    "PostToolUse": {"tool_name": "Read", "tool_input": {"file_path": "notes.txt"}, "tool_response": {}},
    "PostToolUseFailure": {"tool_name": "Read", "tool_input": {"file_path": "notes.txt"}, "error": "x"},
    "UserPromptSubmit": {"prompt": "hello"},
    "Stop": {"stop_hook_active": False},
    "SessionStart": {"source": "startup"},
    "PostCompact": {"trigger": "manual"},
    "SubagentStart": {"agent_id": "a"},
    "SubagentStop": {"agent_id": "a"},
    "ConfigChange": {"source": "project_settings"},
}


def run_hook(script_name: str, input_data: dict, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    """Run a hook script with JSON piped to stdin.

    ``env_overrides`` values: str sets the var; ``None`` deletes it. The
    deletion semantics let tests assert "no env var set" even when the
    operator's parent shell exports a harness var globally (see
    `docs/SHARP_EDGES.md` "ESPALIER_STOP_GATE=full Exported in Shell RC").

    Spawned through ``HOOK_PYTHON`` (the base interpreter), so the hook's
    parent is this process on every host, a Windows venv included: the
    session-marker rows assert on it.
    """
    script = HOOKS_DIR / script_name
    env = os.environ.copy()
    if env_overrides:
        for k, v in env_overrides.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
    return run_hook_through(
        [HOOK_PYTHON, str(script)],
        input=json.dumps(input_data),
        env=env,
    )


def script_arg(hook: dict) -> str:
    """The program slot of an exec-form hook: ``args[0]``, or ``args[1]``
    behind the launcher's version flag (``py -3 <hook>``)."""
    args = hook.get("args", [])
    if hook.get("command") == "py" and args and LAUNCHER_FLAG.fullmatch(args[0]):
        return args[1] if len(args) > 1 else ""
    return args[0] if args else ""


def iter_hooks(settings: dict):
    """``(event, hook)`` for every hook entry a settings document wires."""
    for event, entries in settings.get("hooks", {}).items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                yield event, hook


def run_hook_as_wired(
    tree: Path, script_name: str, payload: dict, *, path: str | None = None,
    env_overrides: dict | None = None,
) -> subprocess.CompletedProcess:
    """Launch the entry ``tree/.claude/settings.json`` wires for ``script_name``,
    the way Claude Code does: ``command`` resolved on ``path`` (this process's
    PATH when ``None``), ``args`` verbatim with ``${CLAUDE_PROJECT_DIR}``
    expanded, the child's cwd, ``PATH`` and ``CLAUDE_PROJECT_DIR`` the tree's.
    ``env_overrides`` works as ``run_hook``'s. The payload's
    ``hook_event_name`` picks the entry where the script is wired under more
    than one event, and is filled in where it is wired under one.

    Raises when the entry is missing, is not exec form, or its ``command``
    does not resolve: a missing wiring is a finding, never a skip."""
    settings = json.loads((tree / ".claude" / "settings.json").read_text(encoding="utf-8"))
    wired = [(event, hook) for event, hook in iter_hooks(settings)
             if script_arg(hook).replace("\\", "/").endswith(f"/tools/cc/hooks/{script_name}")]
    if "hook_event_name" in payload:
        wired = [(event, hook) for event, hook in wired if event == payload["hook_event_name"]]
    if len(wired) != 1:
        raise AssertionError(
            f"{tree / '.claude' / 'settings.json'} wires {script_name} {len(wired)} times"
            f" for {payload.get('hook_event_name', 'any event')}; one entry launches, so"
            " this is the finding")
    event, hook = wired[0]
    if not isinstance(hook.get("args"), list):
        raise AssertionError(f"the {event} entry for {script_name} is not exec form: {hook!r}")
    search = os.environ.get("PATH", "") if path is None else path
    command = shutil.which(hook.get("command", ""), path=search)
    if command is None:
        raise AssertionError(
            f"the {event} entry for {script_name} wires {hook.get('command')!r}, which does"
            " not resolve on the PATH it was launched with, so Claude Code could not start it")
    root = str(tree)
    env = os.environ.copy()
    env["PATH"] = search
    env["CLAUDE_PROJECT_DIR"] = root
    for key, value in (env_overrides or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return not_a_budget_miss(subprocess.run(
        [command, *(a.replace("${CLAUDE_PROJECT_DIR}", root) for a in hook["args"])],
        input=json.dumps({"hook_event_name": event, "cwd": root, **payload}),
        cwd=root, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=WIRED_S,
    ))
