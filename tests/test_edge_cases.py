"""Edge-case and robustness tests (Task 11-A) — pins the core
pipeline's defensive behavior across the ugly-input surface.

Covers empty repos, binary files, non-UTF-8 files, deep nesting,
malformed hook stdin, and counter corruption. Each test guards
against a specific class of failure where the harness would
otherwise crash on an adopter repo that contains unusual content
the test fixtures don't anticipate. Without this contract a code
path that assumes UTF-8 or a non-empty repo could silently break
``espalier`` for any adopter touching the wrong file shape, and
the failure would surface as an unhandled exception rather than a
diagnostic message.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tests._hook_assertions import assert_hook_allowed


HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"


def run_hook(script_name: str, input_data, env_overrides=None):
    """Run a hook script with JSON (or raw string) piped to stdin."""
    script = HOOKS_DIR / script_name
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    raw = json.dumps(input_data) if not isinstance(input_data, str) else input_data
    return subprocess.run(
        [sys.executable, str(script)],
        input=raw,
        capture_output=True,
        text=True,
        timeout=15,
        env=env, encoding="utf-8",
    )


# ── Fingerprinting edge cases ────────────────────────────────────────────────


class TestFingerprintEdgeCases:
    def test_empty_repo_fingerprints_without_crash(self, tmp_path):
        """fingerprint_repo on an empty directory returns languages=[]."""
        from espalier.analyze import fingerprint_repo
        from espalier.config import load_config

        fp = fingerprint_repo(tmp_path, load_config(tmp_path))
        assert fp.languages == []

    def test_readme_only_repo(self, tmp_path):
        """Repo with only a README.md fingerprints without crash."""
        from espalier.analyze import fingerprint_repo
        from espalier.config import load_config

        (tmp_path / "README.md").write_text("# Docs Only\n", encoding="utf-8")
        fp = fingerprint_repo(tmp_path, load_config(tmp_path))
        assert isinstance(fp.languages, list)

    def test_binary_only_repo(self, tmp_path):
        """Repo with a .png file (random bytes) fingerprints without crash."""
        from espalier.analyze import fingerprint_repo
        from espalier.config import load_config

        (tmp_path / "image.png").write_bytes(bytes(range(256)) * 10)
        fp = fingerprint_repo(tmp_path, load_config(tmp_path))
        assert fp.languages == [] or "python" not in fp.languages

    def test_non_utf8_file_handled(self, tmp_path):
        """Latin-1 bytes in a .py file don't crash fingerprinting."""
        from espalier.analyze import fingerprint_repo
        from espalier.config import load_config

        (tmp_path / "latin.py").write_bytes(b"# coding: latin-1\nx = \x80\xff\n")
        fp = fingerprint_repo(tmp_path, load_config(tmp_path))
        assert isinstance(fp, object)  # no crash

    def test_deeply_nested_repo(self, tmp_path):
        """Deeply nested src/a/b/c/d/e/main.py fingerprints without crash."""
        from espalier.analyze import fingerprint_repo
        from espalier.config import load_config

        deep = tmp_path / "src" / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "main.py").write_text("def main(): pass\n", encoding="utf-8")
        fp = fingerprint_repo(tmp_path, load_config(tmp_path))
        assert "python" in fp.languages

    def test_harness_config_without_crash(self, tmp_path):
        """build_harness_config on empty repo returns a BuildPlan without crash."""
        from espalier.analyze import fingerprint_repo
        from espalier.config import load_config
        from espalier.harness_config import build_harness_config
        from espalier.models import BuildPlan

        fp = fingerprint_repo(tmp_path, load_config(tmp_path))
        harness = build_harness_config(fp, load_config(tmp_path))
        assert isinstance(harness, BuildPlan)


# ── Hook robustness ──────────────────────────────────────────────────────────


class TestHookRobustness:
    def test_hook_receives_malformed_stdin(self, tmp_path):
        """stop_gate.py exits 0 when stdin is not valid JSON."""
        result = run_hook(
            "stop_gate.py",
            "not json at all",
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0

    def test_hook_receives_empty_stdin(self, tmp_path):
        """stop_gate.py exits 0 when stdin is empty."""
        result = run_hook(
            "stop_gate.py",
            "",
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0

    def test_hooks_without_claude_project_dir(self, tmp_path):
        """session_start.py exits 0 even when CLAUDE_PROJECT_DIR is not set."""
        env = os.environ.copy()
        env.pop("CLAUDE_PROJECT_DIR", None)
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "session_start.py")],
            input="{}",
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
            cwd=str(tmp_path), encoding="utf-8",  # isolate from live settings.json
        )
        assert result.returncode == 0

    def test_write_guard_denies_protected_zone(self, tmp_path):
        """Write to tools/cc/ zone → exit 2 (DENY, hard block since v3)."""
        import json as _json
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "tools/cc/hooks/foo.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = _json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_write_guard_blocks_dangerous_bash(self, tmp_path):
        """rm -rf / is denied — exit 0 + permissionDecision=deny under the channel-XOR
        protocol (the deny is signalled on stdout, not via exit 2)."""
        import json as _json
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = _json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_write_guard_allows_safe_bash(self, tmp_path):
        """ls -la is allowed with exit 0."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert_hook_allowed(result)

    def test_reflect_trigger_counter_corruption(self, tmp_path):
        """reflect_trigger.py resets gracefully when write_count is not a number."""
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        (state_dir / "write_count").write_text("not_a_number", encoding="utf-8")
        result = run_hook(
            "reflect_trigger.py",
            {"tool_name": "Write", "tool_input": {"file_path": "src/app.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0


# ── Existing .claude dir not overwritten by cmd_init ────────────────────────


class TestInitIdempotency:
    def test_existing_claude_dir_not_overwritten(self, tmp_path):
        """cmd_init skips .claude/settings.json if it already exists."""
        import argparse
        from espalier.cli import cmd_init

        (tmp_path / "README.md").write_text("# Repo\n", encoding="utf-8")
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        custom_settings = '{"custom": true}\n'
        (claude_dir / "settings.json").write_text(custom_settings, encoding="utf-8")

        cmd_init(argparse.Namespace(repo=str(tmp_path), config=None))

        # Custom settings should be preserved
        assert (claude_dir / "settings.json").read_text(encoding="utf-8") == custom_settings
