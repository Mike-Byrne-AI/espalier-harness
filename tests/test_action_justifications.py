"""TP-126: typed action_justification capture contracts.

Pins the library `add_action_justification` validator, the hook-side
`cmd_justify` CLI, the library/hook-side parity contract, and the
load-bearing guards against the two rejected mechanisms (kind enum
overload from rejected TP-118; PreToolUse capture hook from rejected
TP-121).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from espalier.cognitive_blueprint import (
    _validate_action_justification,
    add_action_justification,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_CLI = REPO_ROOT / "tools" / "cc" / "cognitive_blueprint.py"


def _valid_kwargs(**overrides):
    base = {
        "goal": "demonstrate validator",
        "step_rationale": "test path",
        "expected_outcome": "validator returns cleanly",
        "not_doing": "skipping fuzz coverage",
        "tool": "Write",
        "content_hash": "sha256:" + "a" * 64,
    }
    base.update(overrides)
    return base


class TestValidation:

    @pytest.mark.parametrize(
        "field", ["goal", "step_rationale", "expected_outcome", "not_doing"]
    )
    def test_missing_field_rejected(self, field):
        with pytest.raises(ValueError, match=f"action_justification.{field}"):
            _validate_action_justification(**_valid_kwargs(**{field: ""}))

    @pytest.mark.parametrize(
        "field", ["goal", "step_rationale", "expected_outcome", "not_doing"]
    )
    def test_oversize_field_rejected(self, field):
        with pytest.raises(ValueError, match="exceeds 500 chars"):
            _validate_action_justification(**_valid_kwargs(**{field: "x" * 501}))

    def test_unknown_tool_rejected(self):
        with pytest.raises(ValueError, match="MUTATION_TOOLS_TOKENS"):
            _validate_action_justification(**_valid_kwargs(tool="Smite"))

    def test_mcp_tool_accepted(self):
        # mcp__* is an open class; validator must accept by prefix.
        _validate_action_justification(**_valid_kwargs(tool="mcp__write_file"))

    def test_malformed_hash_rejected(self):
        with pytest.raises(ValueError, match="content_hash malformed"):
            _validate_action_justification(**_valid_kwargs(content_hash="nothex"))

    def test_canonical_tool_accepted(self):
        # Every literal in MUTATION_TOOLS_TOKENS must pass.
        from espalier.harness_config import MUTATION_TOOLS_TOKENS
        for tool in MUTATION_TOOLS_TOKENS:
            # mcp__* and PowerShell appear in MUTATION_TOOLS_TOKENS as
            # literal class members alongside Write/Edit/etc.; skip the
            # mcp__ wildcard string and exercise concrete tool names.
            if tool.startswith("mcp__"):
                continue
            _validate_action_justification(**_valid_kwargs(tool=tool))


class TestRoundTrip:

    def test_record_load_round_trip(self, tmp_path):
        bp = tmp_path / "bp.json"
        bp.write_text(json.dumps({"session_id": "sess-1",
                                   "action_justifications": []}), encoding="utf-8")
        add_action_justification(bp, **_valid_kwargs(goal="g1"))
        loaded = json.loads(bp.read_text(encoding="utf-8"))
        assert len(loaded["action_justifications"]) == 1
        entry = loaded["action_justifications"][0]
        for f in ("goal", "step_rationale", "expected_outcome", "not_doing",
                  "tool", "content_hash", "timestamp", "session_id"):
            assert f in entry, f"missing field: {f}"
        assert entry["session_id"] == "sess-1"
        assert entry["goal"] == "g1"


class TestAtomicWrite:

    def test_validation_failure_no_partial_write(self, tmp_path):
        bp = tmp_path / "bp.json"
        original = json.dumps({"session_id": "sess-1",
                                "action_justifications": []})
        bp.write_text(original, encoding="utf-8")
        with pytest.raises(ValueError):
            add_action_justification(bp, **_valid_kwargs(goal=""))
        assert bp.read_text(encoding="utf-8") == original


class TestParity:

    def test_hook_and_library_agree(self, tmp_path, monkeypatch):
        """Library and hook-side validators accept/reject identically.

        Walk a representative input matrix and assert both raise (or
        both succeed) on every row. Byte-equal disk state when both
        succeed via the equivalent write path is checked separately —
        the hook-side cmd_justify operates on the active session
        blueprint via _load_latest/_save (different access pattern than
        the library's blueprint_path argument), so the parity here is
        on validator decisions, not on the exact on-disk shape, which
        is independently fixed (timestamps differ; everything else
        matches).
        """
        # Probe the hook-side validator via subprocess to keep its
        # standalone-script discipline (no espalier import).
        env_setup = [
            "import sys",
            f"sys.path.insert(0, {str(HOOK_CLI.parent)!r})",
            "import cognitive_blueprint as cb",
        ]

        cases = [
            ("Write", "sha256:" + "a" * 64, True),
            ("Edit", "sha256:" + "b" * 64, True),
            ("Bash", "sha256:" + "c" * 64, True),
            ("PowerShell", "sha256:" + "d" * 64, True),
            ("mcp__write_file", "sha256:" + "e" * 64, True),
            ("Smite", "sha256:" + "a" * 64, False),
            ("Write", "badhash", False),
            ("Write", "sha256:NotHex" + "x" * 58, False),
        ]
        for tool, content_hash, should_pass in cases:
            kwargs = _valid_kwargs(tool=tool, content_hash=content_hash)
            # Library side
            lib_passed = True
            try:
                _validate_action_justification(**kwargs)
            except ValueError:
                lib_passed = False
            # Hook side
            hook_script = (
                ";".join(env_setup)
                + ";"
                + f"cb._validate_action_justification(**{kwargs!r})"
            )
            hook_proc = subprocess.run(
                [sys.executable, "-c", hook_script],
                capture_output=True, text=True, encoding="utf-8",
            )
            hook_passed = hook_proc.returncode == 0
            assert lib_passed == hook_passed == should_pass, (
                f"divergence at (tool={tool}, hash={content_hash}): "
                f"lib={lib_passed} hook={hook_passed} expected={should_pass}"
            )


class TestHookCountUnchanged:

    def test_canonical_hook_wiring_count(self):
        """Pin the canonical hook count. TP-126 does NOT add a hook (its
        mechanism is CLI-invoked, not hook-invoked); TP-163 set the baseline
        to 12 (SubagentStart + PostToolUseFailure)."""
        from espalier.harness_config import CANONICAL_HOOK_WIRING
        # Hook script names ARE the keys; value dicts only carry
        # {event, matcher, timeout, reason}.
        hook_names = set(CANONICAL_HOOK_WIRING.keys())
        assert len(hook_names) == 12, (
            f"hook count drifted to {len(hook_names)}; expected 12 (TP-163 "
            "baseline; TP-126 scope (out) still rejects a PreToolUse capture hook)"
        )


class TestExecutionPlanJustification:
    """126-G: planner trigger. On mark <i> running with
    --justification-fields, execution_plan subprocesses to
    cognitive_blueprint justify; without flags, an advisory fires."""

    EP = REPO_ROOT / "tools" / "cc" / "execution_plan.py"
    CB = REPO_ROOT / "tools" / "cc" / "cognitive_blueprint.py"

    def _setup_session(self, tmp_path):
        """Create a fake session in tmp_path's cc/blueprints/latest.json."""
        (tmp_path / "cc" / "blueprints").mkdir(parents=True)
        latest = tmp_path / "cc" / "blueprints" / "latest.json"
        latest.write_text(json.dumps({
            "session_id": "test-session",
            "reasoning_entries": [],
            "action_justifications": [],
        }), encoding="utf-8")
        return latest

    def _env(self, tmp_path):
        import os
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        return env

    def test_mark_running_with_justification_auto_records(self, tmp_path):
        latest = self._setup_session(tmp_path)
        env = self._env(tmp_path)
        subprocess.run(
            [sys.executable, str(self.EP), "create",
             "--task", "test", "--steps", "do-thing"],
            cwd=tmp_path, env=env, capture_output=True, text=True, check=True, encoding="utf-8",
        )
        fields = [
            "goal=demonstrate trigger",
            "step_rationale=verify auto-record path",
            "expected_outcome=blueprint gains entry",
            "not_doing=skipping ad-hoc Bash advisory",
            "tool=Write",
            f"content_hash=sha256:{'1' * 64}",
        ]
        proc = subprocess.run(
            [sys.executable, str(self.EP), "mark", "0", "running",
             "--justification-fields", *fields],
            cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8",
        )
        assert proc.returncode == 0, (
            f"mark returncode={proc.returncode}; stderr={proc.stderr}"
        )
        bp = json.loads(latest.read_text(encoding="utf-8"))
        assert len(bp["action_justifications"]) == 1, bp
        aj = bp["action_justifications"][0]
        assert aj["goal"] == "demonstrate trigger"
        assert aj["tool"] == "Write"

    def test_mark_running_without_justification_advises(self, tmp_path):
        latest = self._setup_session(tmp_path)
        env = self._env(tmp_path)
        subprocess.run(
            [sys.executable, str(self.EP), "create",
             "--task", "test", "--steps", "do-thing"],
            cwd=tmp_path, env=env, capture_output=True, text=True, check=True, encoding="utf-8",
        )
        proc = subprocess.run(
            [sys.executable, str(self.EP), "mark", "0", "running"],
            cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8",
        )
        assert proc.returncode == 0
        assert "starting without action_justification" in proc.stderr, (
            f"expected advisory, got stderr={proc.stderr!r}"
        )
        bp = json.loads(latest.read_text(encoding="utf-8"))
        assert bp["action_justifications"] == [], (
            f"blueprint gained entry despite missing justification: {bp}"
        )


class TestPostWriteAdvisory:
    """126-H: post_write_check fires an advisory + audit entry when no
    action_justification matches the mutation within the 60s window;
    silent when a match exists. Verifies the audit path is
    ~/.espalier/audit/{slug}-{YYYYMMDD}.log (TP-127 v1 sister-site
    correction)."""

    HOOK = REPO_ROOT / "tools" / "cc" / "hooks" / "post_write_check.py"

    def _run_hook(self, tmp_path, payload, audit_dir):
        import os
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        env["ESPALIER_AUDIT_DIR"] = str(audit_dir)
        proc = subprocess.run(
            [sys.executable, str(self.HOOK)],
            input=json.dumps(payload),
            cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8",
        )
        return proc

    def _setup(self, tmp_path):
        (tmp_path / "cc" / "blueprints").mkdir(parents=True)
        latest = tmp_path / "cc" / "blueprints" / "latest.json"
        return latest

    def test_silent_when_recent_justification_matches(self, tmp_path):
        latest = self._setup(tmp_path)
        target = tmp_path / "demo.txt"
        target.write_text("hello", encoding="utf-8")
        content_hash = "sha256:" + hashlib.sha256(b"hello").hexdigest()
        latest.write_text(json.dumps({
            "session_id": "s1",
            "action_justifications": [{
                "goal": "g", "step_rationale": "r", "expected_outcome": "o",
                "not_doing": "n", "tool": "Write",
                "content_hash": content_hash,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": "s1",
            }],
        }), encoding="utf-8")
        audit_dir = tmp_path / "audit"
        proc = self._run_hook(
            tmp_path,
            {"tool_name": "Write", "tool_input": {"file_path": "demo.txt"}},
            audit_dir=audit_dir,
        )
        assert "no action_justification recorded" not in proc.stderr, proc.stderr
        assert not audit_dir.exists() or not any(audit_dir.iterdir()), (
            f"unexpected audit log created: {list(audit_dir.iterdir()) if audit_dir.exists() else None}"
        )

    def test_advises_when_no_recent_match(self, tmp_path):
        # hashlib needed at module scope
        latest = self._setup(tmp_path)
        latest.write_text(json.dumps({
            "session_id": "s1",
            "action_justifications": [],
        }), encoding="utf-8")
        target = tmp_path / "demo.txt"
        target.write_text("hello", encoding="utf-8")
        audit_dir = tmp_path / "audit"
        proc = self._run_hook(
            tmp_path,
            {"tool_name": "Write", "tool_input": {"file_path": "demo.txt"}},
            audit_dir=audit_dir,
        )
        assert "no action_justification recorded" in proc.stderr, proc.stderr
        assert "demo.txt" in proc.stderr
        # Audit log written to <ESPALIER_AUDIT_DIR>/{slug}-{YYYYMMDD}.log
        # (production path is ~/.espalier/audit/...; test redirects via env var)
        assert audit_dir.exists(), "audit dir not created"
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        logs = list(audit_dir.glob(f"*-{today}.log"))
        assert logs, f"no audit log file found: {list(audit_dir.iterdir())}"
        log_content = logs[0].read_text(encoding="utf-8").strip().splitlines()
        assert log_content, "audit log empty"
        entry = json.loads(log_content[-1])
        assert entry["event_type"] == "action_justification_missing"
        assert entry["details"]["tool"] == "Write"

    def test_advises_for_bash_with_no_match(self, tmp_path):
        latest = self._setup(tmp_path)
        latest.write_text(json.dumps({
            "session_id": "s1",
            "action_justifications": [],
        }), encoding="utf-8")
        audit_dir = tmp_path / "audit"
        proc = self._run_hook(
            tmp_path,
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/foo"}},
            audit_dir=audit_dir,
        )
        # The Bash early-return widening means the advisory fires; the
        # JSON/path-consistency checks remain bounded to Write/Edit.
        assert "no action_justification recorded" in proc.stderr, proc.stderr
        assert "Bash" in proc.stderr


class TestMemorySlugExists:
    """126-I1: memory/action-justification-protocol.md exists with the
    Status + Linked-from headers per TP-88 convention."""

    SLUG = REPO_ROOT / "memory" / "action-justification-protocol.md"

    def test_slug_file_exists(self):
        assert self.SLUG.is_file(), f"memory slug missing at {self.SLUG}"

    def test_slug_has_status_header(self):
        body = self.SLUG.read_text(encoding="utf-8")
        assert "**Status:** active" in body, (
            "memory slug must declare Status: active per TP-88 convention"
        )

    def test_slug_has_linked_from_header(self):
        body = self.SLUG.read_text(encoding="utf-8")
        assert "**Linked from:**" in body, (
            "memory slug must declare Linked from: per TP-88 convention"
        )


class TestCLAUDEMDPointer:
    """126-I2: CLAUDE.md Core Rules contains a pointer at the new
    memory slug."""

    def test_claude_md_points_at_protocol_slug(self):
        body = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        assert "memory/action-justification-protocol.md" in body, (
            "CLAUDE.md must include a pointer to the protocol slug"
        )


class TestNoJSONInDescription:

    def test_no_kind_action_justification(self):
        """Pin that TP-126 does NOT overload the kind enum. The rejected
        New TP-118 would have added kind='action_justification' with a
        JSON-in-string payload; TP-126 uses a typed array instead.

        Scan the hook-side argparse --kind choices block specifically;
        substring grep would false-fire on the legitimate uses of
        'action_justification' (the new array name + cmd_justify
        function + AJ_* constants)."""
        src = HOOK_CLI.read_text(encoding="utf-8")
        # Find every --kind argparse block (record subcommand + show-recent)
        choices_blocks = re.findall(
            r"add_argument\(\s*['\"]--kind['\"][^)]*choices\s*=\s*\[([^\]]+)\]",
            src,
        )
        assert choices_blocks, "could not locate any --kind argparse block"
        for block in choices_blocks:
            assert "action_justification" not in block, (
                "kind='action_justification' resurrected in argparse choices; "
                "use the typed action_justifications: [] array instead"
            )
