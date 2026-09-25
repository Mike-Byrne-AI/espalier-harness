"""TP-104 + TP-105: hook-helper consolidation contracts.

Pins:
  1. No inline `_resolve_project_root` def lives in any hook script.
  2. Every hook script warns on empty CLAUDE_PROJECT_DIR (i.e. they
     all route through `_hook_utils.resolve_project_root`, not a
     local copy).
  3. TP-105 generalization: no hook script defines its own FunctionDef
     with a name exported by `_hook_utils.py` (catches future shadow
     bugs like `read_stdin_safely` redefined locally with drift).

Failure shape: a future contributor copy-pasting the old 2-line def
into a new hook fails (1); a contributor who imports but bypasses
the warning by reading os.environ directly fails (2); a contributor
shadowing any other `_hook_utils` export with subtly different
semantics fails (3).
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).parent.parent / "tools" / "cc" / "hooks"


class TestHookHelperConsolidation:
    def test_no_inline_project_root_def(self):
        """No hook script defines its own _resolve_project_root (alias is OK)."""
        violations = []
        for hook_file in HOOKS_DIR.glob("*.py"):
            if hook_file.name == "_hook_utils.py":
                continue
            source = hook_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(hook_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "_resolve_project_root":
                    violations.append(f"{hook_file.name}:{node.lineno}")
        assert not violations, (
            "Inline `_resolve_project_root` def found. Use the alias shape:\n"
            "  _resolve_project_root = _hook_utils.resolve_project_root\n"
            "Sites:\n  " + "\n  ".join(violations)
        )

    @pytest.mark.parametrize(
        "hook_name",
        [
            "config_guard",
            "plan_guard",
            "post_compact",
            "post_write_check",
            "reflect_trigger",
            "session_start",
            "stop_gate",
            "subagent_stop",
            "task_router",
            "write_guard",
        ],
    )
    def test_empty_env_warns_via_helper(self, hook_name):
        """Every hook routes its root resolution through the empty-env warner.

        Imports the hook in a subprocess with `CLAUDE_PROJECT_DIR=""` and
        calls the path-resolving entry point. Hooks defining
        `_resolve_project_root` as the alias call `resolve_project_root()`
        directly; `task_router` uses the imported `resolve_project_root`
        inside `_has_active_plan`, so we invoke it via the module's
        helper directly. Either way, the empty-env branch emits
        `[WARN] espalier` on stderr.
        """
        if hook_name == "task_router":
            invocation = (
                f"import {hook_name}; "
                f"{hook_name}.resolve_project_root()"
            )
        else:
            invocation = (
                f"import {hook_name}; "
                f"{hook_name}._resolve_project_root()"
            )
        script = (
            "import sys; sys.path.insert(0, 'tools/cc/hooks'); "
            + invocation
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            env={"CLAUDE_PROJECT_DIR": "", "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            timeout=10, encoding="utf-8",
        )
        assert "[WARN] espalier" in result.stderr, (
            f"Hook `{hook_name}` did not emit empty-env warning; it likely "
            f"bypasses _hook_utils.resolve_project_root. "
            f"stderr={result.stderr!r}"
        )


def _hook_utils_public_names() -> list[str]:
    """Return top-level FunctionDef public-API names exported by _hook_utils.py.

    Filters out dunders AND single-leading-underscore private helpers
    (e.g. `_project_name_from_pyproject`, `_write_guard_prefix_matches_pin`)
    — those are implementation-detail and unlikely to be shadowed by hooks.
    The sister_site_probe (TP-105) catches body-match canon-misses for
    them via the body-hash path.
    """
    tree = ast.parse((HOOKS_DIR / "_hook_utils.py").read_text(encoding="utf-8"))
    return [
        node.name for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and not node.name.startswith("_")
    ]


class TestHelperShadow:
    @pytest.mark.parametrize("helper_name", _hook_utils_public_names())
    def test_no_shadow_def(self, helper_name):
        """No hook script re-defines a name exported by _hook_utils.py."""
        violations = []
        for hook_file in HOOKS_DIR.glob("*.py"):
            if hook_file.name == "_hook_utils.py":
                continue
            tree = ast.parse(hook_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == helper_name:
                    violations.append(f"{hook_file.name}:{node.lineno}")
        assert not violations, (
            f"Hook re-defines `_hook_utils.{helper_name}` locally:\n  "
            + "\n  ".join(violations)
            + f"\nUse alias shape: `{helper_name} = _hook_utils.{helper_name}`"
        )
