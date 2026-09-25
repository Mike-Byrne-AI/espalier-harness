"""Smoke tests for ``espalier init`` hook deployment — every entry
script in ``INIT_HOOK_SCRIPTS`` and every helper module lands on
disk AND is subprocess-executable with the matching event payload.

Pins the end-to-end "init produces a runnable harness" invariant:
after ``cmd_init`` returns, each hook script can be invoked with the
minimum-valid JSON for its event without raising. Without this
contract an init regression could leave hooks deployed-but-broken
(import errors, missing helpers, wrong shebang) — settings.json
would still wire them but the hooks would silently fail-open on
the first real event, defeating mechanical enforcement entirely.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from espalier.cli import INIT_HOOK_SCRIPTS, INIT_TOOL_SCRIPTS, cmd_init

# R13: derive the exercised set from the deploy SoT (espalier.cli.INIT_*) so a
# newly added hook automatically enters coverage instead of silently shipping
# an import-time crash the guard claims to prevent. Entry hooks = basenames
# without a leading underscore (subprocess-executable on their event); helper
# modules = leading-underscore siblings imported by the entry hooks. Tool
# scripts deploy under tools/cc/ (not tools/cc/hooks/), so they are tracked
# separately for the presence check below.
HOOK_ENTRY_SCRIPTS = [
    Path(s).name for s in INIT_HOOK_SCRIPTS if not Path(s).name.startswith("_")
]

HOOK_HELPER_SCRIPTS = [
    Path(s).name for s in INIT_HOOK_SCRIPTS if Path(s).name.startswith("_")
]

TOOL_SCRIPTS = [Path(s).name for s in INIT_TOOL_SCRIPTS]

# Minimal valid JSON payloads for each hook event.
_HOOK_INPUTS = {
    "session_start.py": json.dumps({
        "hook_event_name": "SessionStart",
        "source": "startup",
        "cwd": "__TARGET__",
    }),
    "task_router.py": json.dumps({
        "hook_event_name": "UserPromptSubmit",
        "prompt": "test",
        "cwd": "__TARGET__",
    }),
    "plan_guard.py": json.dumps({
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "README.md"},
        "cwd": "__TARGET__",
    }),
    "write_guard.py": json.dumps({
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "README.md"},
        "cwd": "__TARGET__",
    }),
    "post_write_check.py": json.dumps({
        "hook_event_name": "PostToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "README.md"},
        "tool_response": {},
        "cwd": "__TARGET__",
    }),
    "reflect_trigger.py": json.dumps({
        "hook_event_name": "PostToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "README.md"},
        "tool_response": {},
        "cwd": "__TARGET__",
    }),
    "stop_gate.py": json.dumps({
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "last_assistant_message": "done",
        "cwd": "__TARGET__",
    }),
    "post_compact.py": json.dumps({
        "hook_event_name": "PostCompact",
        "trigger": "manual",
        "compact_summary": "summary",
        "cwd": "__TARGET__",
    }),
}

# Generic payload for entry hooks added to INIT_HOOK_SCRIPTS that don't yet
# have a bespoke event payload above (R13). read_stdin_safely tolerates extra
# keys, so a superset payload exercises the import path of any event without a
# KeyError on _HOOK_INPUTS. The smoke check only asserts no import error fires,
# not event-correct behavior, so a wrong-event payload is acceptable here.
_GENERIC_HOOK_INPUT = json.dumps({
    "hook_event_name": "PreToolUse",
    "tool_name": "Read",
    "tool_input": {"file_path": "README.md"},
    "tool_response": {},
    "source": "startup",
    "prompt": "x",
    "trigger": "manual",
    "stop_hook_active": False,
    "cwd": "__TARGET__",
})


def _make_repo(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-app"\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    return tmp_path


def _run_init(repo: Path) -> int:
    args = argparse.Namespace(repo=str(repo), config=None)
    return cmd_init(args)


class TestHelpersDeployed:
    """After init, all helper modules must exist alongside entry hooks."""

    def test_all_entry_hooks_present(self, tmp_path):
        repo = _make_repo(tmp_path)
        _run_init(repo)
        hooks_dir = repo / "tools" / "cc" / "hooks"
        for name in HOOK_ENTRY_SCRIPTS:
            assert (hooks_dir / name).exists(), f"Missing entry hook: {name}"

    def test_all_helper_modules_present(self, tmp_path):
        repo = _make_repo(tmp_path)
        _run_init(repo)
        hooks_dir = repo / "tools" / "cc" / "hooks"
        for name in HOOK_HELPER_SCRIPTS:
            assert (hooks_dir / name).exists(), f"Missing helper module: {name}"

    def test_all_tool_scripts_present(self, tmp_path):
        repo = _make_repo(tmp_path)
        _run_init(repo)
        tools_dir = repo / "tools" / "cc"
        for name in TOOL_SCRIPTS:
            assert (tools_dir / name).exists(), f"Missing tool script: {name}"

    def test_derived_sets_have_expected_shape(self):
        """R13: deriving from the SoT must cover the entry hooks the old
        hardcoded list omitted (config_guard / subagent_stop / subagent_start /
        context_reinject_failure) and partition cleanly on the underscore."""
        for name in (
            "config_guard.py", "subagent_stop.py",
            "subagent_start.py", "context_reinject_failure.py",
        ):
            assert name in HOOK_ENTRY_SCRIPTS, (
                f"{name} missing from derived entry set — import path unexercised"
            )
        assert all(not n.startswith("_") for n in HOOK_ENTRY_SCRIPTS)
        assert all(n.startswith("_") for n in HOOK_HELPER_SCRIPTS)
        assert HOOK_ENTRY_SCRIPTS and HOOK_HELPER_SCRIPTS and TOOL_SCRIPTS


class TestHookExecutionNoModuleError:
    """Every deployed entry hook must execute without ModuleNotFoundError."""

    def _run_hook(self, hook_path: Path, stdin_json: str, cwd: Path) -> subprocess.CompletedProcess:
        payload = stdin_json.replace("__TARGET__", str(cwd))
        return subprocess.run(
            [sys.executable, str(hook_path)],
            input=payload,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=15, encoding="utf-8",
        )

    def test_no_module_not_found_error_on_any_hook(self, tmp_path):
        repo = _make_repo(tmp_path)
        _run_init(repo)
        hooks_dir = repo / "tools" / "cc" / "hooks"

        failures = []
        for name in HOOK_ENTRY_SCRIPTS:
            hook_path = hooks_dir / name
            stdin_json = _HOOK_INPUTS.get(name, _GENERIC_HOOK_INPUT)
            result = self._run_hook(hook_path, stdin_json, repo)
            combined = result.stdout + result.stderr
            if "ModuleNotFoundError" in combined or "ImportError" in combined:
                failures.append(f"{name}: {combined[:300]}")

        assert not failures, "Hooks raised import errors:\n" + "\n---\n".join(failures)

    def test_broken_subagent_start_import_is_caught(self, tmp_path):
        """R13 earn-the-red: a broken import in an entry hook that the old
        hardcoded list omitted (subagent_start) must be caught by the
        no-import-error guard. Pre-fix HOOK_ENTRY_SCRIPTS lists only 8 names
        and never runs subagent_start, so the break is invisible."""
        repo = _make_repo(tmp_path)
        _run_init(repo)
        hook = repo / "tools" / "cc" / "hooks" / "subagent_start.py"
        text = hook.read_text(encoding="utf-8")
        marker = "from __future__ import annotations\n"
        assert marker in text
        hook.write_text(
            text.replace(
                marker, marker + "import _nonexistent_helper_xyz  # break\n", 1
            ), encoding="utf-8"
        )
        failures = []
        for name in HOOK_ENTRY_SCRIPTS:
            stdin_json = _HOOK_INPUTS.get(name, _GENERIC_HOOK_INPUT)
            result = self._run_hook(
                repo / "tools" / "cc" / "hooks" / name, stdin_json, repo
            )
            combined = result.stdout + result.stderr
            if "ModuleNotFoundError" in combined or "ImportError" in combined:
                failures.append(name)
        assert "subagent_start.py" in failures, (
            "broken subagent_start import not caught — entry-hook coverage is "
            "narrower than INIT_HOOK_SCRIPTS"
        )

    def test_session_start_exits_zero(self, tmp_path):
        repo = _make_repo(tmp_path)
        _run_init(repo)
        hook = repo / "tools" / "cc" / "hooks" / "session_start.py"
        result = self._run_hook(hook, _HOOK_INPUTS["session_start.py"], repo)
        assert result.returncode == 0, f"session_start exited {result.returncode}: {result.stderr[:200]}"

    def test_write_guard_exits_zero_for_read_tool(self, tmp_path):
        repo = _make_repo(tmp_path)
        _run_init(repo)
        hook = repo / "tools" / "cc" / "hooks" / "write_guard.py"
        result = self._run_hook(hook, _HOOK_INPUTS["write_guard.py"], repo)
        assert result.returncode == 0, f"write_guard exited {result.returncode}: {result.stderr[:200]}"


class TestHelperMissingBreaksIntegrity:
    """Deleting a helper must cause integrity verify to return a failing status."""

    def test_missing_hook_utils_fails_integrity(self, tmp_path):
        repo = _make_repo(tmp_path)
        _run_init(repo)

        helper = repo / "tools" / "cc" / "hooks" / "_hook_utils.py"
        assert helper.exists()
        helper.unlink()

        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "integrity", "verify", str(repo)],
            capture_output=True,
            text=True,
            timeout=30, encoding="utf-8",
        )
        assert result.returncode != 0, (
            "integrity verify returned 0 after _hook_utils.py was deleted — "
            "missing helpers must cause a non-zero exit"
        )

    def test_missing_integrity_helper_fails_integrity(self, tmp_path):
        repo = _make_repo(tmp_path)
        _run_init(repo)

        helper = repo / "tools" / "cc" / "hooks" / "_integrity.py"
        assert helper.exists()
        helper.unlink()

        result = subprocess.run(
            [sys.executable, "-m", "espalier.cli", "integrity", "verify", str(repo)],
            capture_output=True,
            text=True,
            timeout=30, encoding="utf-8",
        )
        assert result.returncode != 0, (
            "integrity verify returned 0 after _integrity.py was deleted — "
            "missing helpers must cause a non-zero exit"
        )
