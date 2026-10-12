"""The canonical wiring of the blocking governance gates, written into a tree
for tests that need a checkout a session would launch in with the gates ON.

Derived from the engine's ``CANONICAL_HOOK_WIRING`` and
``GOVERNANCE_BLOCKING_HOOKS`` (the hook-side roster in
``tools/cc/hooks/_integrity.py`` is pinned equal to them by
``tests/test_ci_guard.py::TestHookSideWiringTwin``), never typed in a test
file: three test files each carried their own copy of the exec form on
2026-10-11 until the failure-mode review named the drift that would make a
"silent on a wired checkout" row pass vacuously (an ``init``-side change to
the ``type``/``command``/``args`` keys). One builder, three callers.
"""
from __future__ import annotations

import json
from pathlib import Path

from espalier.harness_config import CANONICAL_HOOK_WIRING, GOVERNANCE_BLOCKING_HOOKS

SETTINGS_REL = ".claude/settings.json"


def write_wired_settings(root: Path, *, drop: tuple[str, ...] = (), extra: dict | None = None,
                         deploy: bool = True, settings: bool = True) -> Path:
    """Under ``root``: a stub of every blocking hook on disk (``deploy``), and
    the project settings file wiring each of them but ``drop`` in the canonical
    exec form (``settings``), with ``extra``'s event groups appended as given.
    Returns the settings path, written or not."""
    hooks_dir = root / "tools" / "cc" / "hooks"
    wiring: dict[str, list] = {}
    for script in GOVERNANCE_BLOCKING_HOOKS:
        if deploy:
            hooks_dir.mkdir(parents=True, exist_ok=True)
            (hooks_dir / script).write_text("# stub\n", encoding="utf-8")
        if script in drop:
            continue
        canonical = CANONICAL_HOOK_WIRING[script]
        entry: dict = {"hooks": [{"type": "command", "command": "python3",
                                  "args": [f"${{CLAUDE_PROJECT_DIR}}/tools/cc/hooks/{script}"]}]}
        if canonical["matcher"]:
            entry["matcher"] = canonical["matcher"]
        wiring.setdefault(canonical["event"], []).append(entry)
    for event, groups in (extra or {}).items():
        wiring.setdefault(event, []).extend(groups)
    path = root / SETTINGS_REL
    if settings:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"hooks": wiring}), encoding="utf-8")
    return path
