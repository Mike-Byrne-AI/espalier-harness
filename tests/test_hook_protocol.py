"""Hook protocol XOR contract.

Per Claude Code hook protocol (see docs/external/cc-hook-protocol.md):
- Exit 0: stdout is parsed as JSON for structured decisions.
- Exit 2: stdout is ignored; stderr is fed back as the reason.
- "You must choose one approach per hook, not both."

This test asserts every hook script obeys the channel XOR. It catches the
class of bug where exit 2 + stdout JSON (the wrong hybrid) appears correct
in unit tests but silently drops the structured reason in production.

This test exists because the codebase shipped that exact bug for months
and the existing 1,431-test suite missed it — every test verified the
emission, none verified the channel against the external contract.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "tools" / "cc" / "hooks"


def _run_hook(script_name: str, payload: dict, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / script_name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=15,
        env=env, encoding="utf-8",
    )


def _config_guard_setup(tmp: Path) -> dict:
    """Plant a kill-switch settings file under the tmp project root so
    config_guard's `_scan_payload` finds something to deny on. Returns
    env overrides like the other env_factory entries.
    """
    settings_dir = tmp / ".claude"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "settings.json").write_text(
        json.dumps({"disableAllHooks": True}), encoding="utf-8",
    )
    return {"CLAUDE_PROJECT_DIR": str(tmp)}


# Sample deny-triggering payloads for each governance hook.
# Each entry: (script, payload, env_overrides_factory). The env_factory may
# perform setup (file creation etc.) as a side effect before returning env.
DENY_FIXTURES = [
    (
        "write_guard.py",
        {"tool_name": "Write", "tool_input": {"file_path": "tools/cc/hooks/write_guard.py", "content": "x"}},
        lambda tmp: {"CLAUDE_PROJECT_DIR": str(tmp)},
    ),
    (
        "plan_guard.py",
        {"tool_name": "Edit", "tool_input": {"file_path": "src/app.py"}},
        lambda tmp: {"CLAUDE_PROJECT_DIR": str(tmp)},
    ),
    (
        "config_guard.py",
        {"source": "project", "file_path": ".claude/settings.json"},
        _config_guard_setup,
    ),
]


# TP-163: the two new hooks (subagent_start → SubagentStart,
# context_reinject_failure → PostToolUseFailure) are non-blocking REPORTERS.
# Channel-XOR for a reporter is the degenerate case — the ONLY legal channel is
# (exit 0 + optional additionalContext JSON). An exit 2, or a decision/block
# field, would be a contract violation (these events have no 'block' semantics;
# PostToolUseFailure fires AFTER the tool already failed). Each entry:
# (script, payload, must_emit, expected_event).
REPORTER_FIXTURES = [
    ("subagent_start.py", {}, True, "SubagentStart"),
    (
        "context_reinject_failure.py",
        {"tool_name": "Edit", "tool_response": "String to replace not found in file"},
        True, "PostToolUseFailure",
    ),
    (
        "context_reinject_failure.py",
        {"tool_name": "Write", "tool_response": "No such file or directory"},
        False, None,
    ),
    (
        "context_reinject_failure.py",
        {"tool_name": "Bash", "tool_response": "command not found"},
        False, None,
    ),
]


@pytest.mark.parametrize(
    "script,payload,must_emit,expected_event", REPORTER_FIXTURES
)
def test_reporter_hooks_exit_zero_never_block(
    tmp_path, script, payload, must_emit, expected_event
):
    """Reporter hooks: exit 0 always; additionalContext on fire; silent otherwise."""
    result = _run_hook(script, payload, {"CLAUDE_PROJECT_DIR": str(tmp_path)})
    assert result.returncode == 0, (
        f"{script}: reporter must exit 0, got {result.returncode}; "
        f"stderr={result.stderr!r}"
    )
    if must_emit:
        data = json.loads(result.stdout)
        hso = data["hookSpecificOutput"]
        assert hso["hookEventName"] == expected_event
        assert hso["additionalContext"].strip(), (
            f"{script}: fired but additionalContext is empty"
        )
        assert "decision" not in data and "block" not in data, (
            f"{script}: reporter must not emit a deny/block decision"
        )
    else:
        assert result.stdout.strip() == "", (
            f"{script}: expected SILENT (no stdout), got {result.stdout!r}"
        )


# pins: claim:hook-assumption-1-stderr-exit-2
class TestHookProtocolXOR:
    """Each hook script obeys exactly one channel: (exit 0 + JSON) XOR (exit 2 + stderr)."""

    @pytest.mark.parametrize("script,payload,env_factory", DENY_FIXTURES)
    def test_deny_uses_one_channel_only(self, tmp_path, script, payload, env_factory):
        result = _run_hook(script, payload, env_factory(tmp_path))
        if result.returncode == 0:
            assert result.stdout.strip(), (
                f"{script}: exit 0 deny path must emit JSON on stdout, got empty"
            )
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                pytest.fail(f"{script}: exit 0 stdout must be valid JSON; got {exc}")
            # PreToolUse schema check
            hso = data.get("hookSpecificOutput", {})
            assert hso.get("permissionDecision") == "deny" or data.get("decision") == "block", (
                f"{script}: exit 0 + JSON must include a deny/block decision; "
                f"got {data!r}"
            )
        elif result.returncode == 2:
            assert result.stderr.strip(), (
                f"{script}: exit 2 deny path must emit reason on stderr, got empty"
            )
            assert not result.stdout.strip() or not _looks_like_json(result.stdout), (
                f"{script}: exit 2 must not emit stdout JSON (Claude Code ignores it). "
                f"Pick one channel."
            )
        else:
            pytest.fail(
                f"{script}: deny returned rc={result.returncode}; "
                f"protocol allows only 0 (structured) or 2 (simple)"
            )


# pins: claim:hook-assumption-3-stop-fires
class TestStopGateBlockSchema:
    """Stop-event blocks use top-level decision/reason, not nested hookSpecificOutput."""

    def test_stop_block_uses_top_level_schema(self, tmp_path):
        # Deterministically DRIVE a Stop block: Gate 2 (docs refresh) blocks
        # when write_count >= 10 and no docs_refreshed flag is set. Seed the
        # counter directly rather than relying on tree state -- the old setup
        # created a dirty git tree, which never drives Gate 2, so the block
        # never fired, stdout stayed empty, and the schema assertions below sat
        # under an `if returncode == 0 and stdout.strip()` guard that was always
        # false: zero assertions ran and the test named a regression it could
        # never observe.
        #
        # Gates 2/3 are skipped under ESPALIER_MAINTENANCE_MODE, and _run_hook
        # inherits the parent env -- so force the mode OFF here (and pin the
        # stop-gate mode to light so Gate 1 pytest never pre-empts) to keep the
        # block deterministic regardless of the ambient session.
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        (state_dir / "write_count").write_text("10", encoding="utf-8")
        result = _run_hook(
            "stop_gate.py",
            {"stop_hook_active": False},
            {
                "CLAUDE_PROJECT_DIR": str(tmp_path),
                "ESPALIER_MAINTENANCE_MODE": "",
                "ESPALIER_STOP_GATE": "light",
            },
        )
        # The block MUST have fired -- unconditional, no guard.
        assert result.returncode == 0, (
            f"stop_gate must exit 0 (structured channel), got rc={result.returncode}; "
            f"stderr={result.stderr!r}"
        )
        assert result.stdout.strip(), (
            "Gate 2 (write_count>=10, no docs_refreshed) must emit a block on "
            f"stdout; got empty stdout, stderr={result.stderr!r}"
        )
        data = json.loads(result.stdout)
        # Stop blocks use the top-level decision/reason schema, NOT the nested
        # PreToolUse hookSpecificOutput shape.
        assert data.get("decision") == "block", (
            f"Stop block must set top-level decision='block', got {data!r}"
        )
        assert "reason" in data, "Stop block must include top-level reason"
        assert "hookSpecificOutput" not in data, (
            "Stop block must NOT nest under hookSpecificOutput "
            "(that's the PreToolUse schema)"
        )


def _looks_like_json(s: str) -> bool:
    s = s.strip()
    return s.startswith("{") or s.startswith("[")


def test_every_deny_hook_in_fixtures_or_exempt():
    """TP-151 H-2: completeness backstop (U ⊆ R). Every hook script that calls
    deny()/block() must be exercised by DENY_FIXTURES (channel-XOR coverage) or
    named in EXEMPT — else a new blocking hook ships with its channel untested
    (DENY_FIXTURES is the iteration domain; an unlisted deny hook is invisible).
    Self-contained AST walk — no import of a bench-gated module that could skip
    the contract on adopter repos. Sister to the TP-150 'registration-set as
    iteration domain' mode."""
    import ast

    fixtures = {script for script, _payload, _env in DENY_FIXTURES}
    # stop_gate is a BLOCKING Stop hook whose deny channel is exercised by
    # tests/test_stop_gate.py (incl. the TP-151 E-1 fail-closed umbrella), not
    # the PreToolUse-shaped DENY_FIXTURES.
    exempt = {"stop_gate.py"}
    deny_hooks: set[str] = set()
    for p in sorted(HOOKS_DIR.glob("*.py")):
        if p.name == "__init__.py":
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"deny", "block"}
            ):
                deny_hooks.add(p.name)
                break
    missing = deny_hooks - fixtures - exempt
    assert not missing, (
        f"hooks calling deny()/block() not in DENY_FIXTURES or exempt: "
        f"{sorted(missing)}. Add a deny fixture (channel-XOR coverage), or if "
        f"the hook's deny channel is tested elsewhere, add it to `exempt` with "
        f"a comment naming where."
    )
