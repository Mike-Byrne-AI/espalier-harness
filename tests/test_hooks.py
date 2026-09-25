"""Tests for the Espalier-Harness hook scripts under
``tools/cc/hooks/`` — the canonical exec-form contract.

Each hook reads JSON from stdin. Tests pipe sample JSON via
subprocess and verify exit codes plus stdout/stderr content
against the channel-XOR rule (exit 0 + JSON on stdout, OR exit 2 +
plain stderr, never both — per ``docs/external/cc-hook-protocol.md``).

Pins the mechanical-enforcement layer: hooks are not instructions,
they're processes Claude Code spawns on every matching event. A
regression in any hook's stdin parsing, exit-code emission, or
stdout JSON shape silently disables enforcement for that event
without producing a visible error — the user only finds out when
something they expected to block doesn't. Without this contract,
the entire governance layer could degrade to advisory-only without
any test catching it.
"""
from __future__ import annotations

import codecs
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Reached THROUGH write_guard, not imported directly: _denial_reasons uses flat
# sibling imports (`import _maintenance_mode`) that need tools/cc/hooks on
# sys.path, and write_guard inserts it as an import side effect. Importing
# _denial_reasons directly works only if something else already imported a hook
# first — an ordering dependency that breaks under -p no:randomly or a changed
# collection order.
from tools.cc.hooks.write_guard import _denial_reasons

import pytest

from tests._hook_assertions import assert_hook_allowed, assert_hook_denied
from tests._symlink_support import requires_symlink

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"

# This file's one wall-clock row (`test_env_prefix_regex_redos_safe`) follows
# the rule `tests/test_redos.py` states at its constants block (DEF-922): the
# asserted ceiling is a named constant no less than ten times a named, dated
# floor, and `tests/test_proof_tier.py::test_every_wall_clock_ceiling_is_ten_times_a_dated_floor`
# derives every bound in the serial timing files and reds on a literal one.
# Floor: the env-prefix anchor on a 50k-newline body, 9.2 ms (2026-09-24, the
# minimum of three on the 8 GB self-host Air at load 1.8-2.1); the naive draft
# took about 26 s, which is all the ceiling has to catch.
_ENV_PREFIX_FLOOR_MS = 10
_ENV_PREFIX_CEILING_MS = 1000
_WALL_CLOCK_FLOORS: dict[str, tuple[str, str, int]] = {
    "_ENV_PREFIX_CEILING_MS": ("_ENV_PREFIX_FLOOR_MS", "2026-09-24", 10),
}


def _make_self_host_layout(tmp_path: Path, name: str = "espalier-harness") -> None:
    """Lay down the 5 signals required by ``is_self_host_repo`` (TP-76):
    ``espalier/``, ``tools/cc/``, ``bench/``, ``pyproject.toml`` with the
    given name, and a SHA-pinned copy of ``write_guard.py``.
    """
    (tmp_path / "espalier").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tools" / "cc" / "hooks").mkdir(parents=True, exist_ok=True)
    (tmp_path / "bench").mkdir(parents=True, exist_ok=True)
    shutil.copy2(HOOKS_DIR / "write_guard.py", tmp_path / "tools" / "cc" / "hooks" / "write_guard.py")
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n', encoding="utf-8")


def run_hook(script_name: str, input_data: dict, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    """Run a hook script with JSON piped to stdin.

    ``env_overrides`` values: str sets the var; ``None`` deletes it. The
    deletion semantics let tests assert "no env var set" even when the
    operator's parent shell exports a harness var globally (see
    `docs/SHARP_EDGES.md` "ESPALIER_STOP_GATE=full Exported in Shell RC").
    """
    script = HOOKS_DIR / script_name
    env = os.environ.copy()
    if env_overrides:
        for k, v in env_overrides.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        timeout=15,
        env=env, encoding="utf-8",
    )


# ─── stop_gate.py ───────────────────────────────────────────────────────────


class TestStopGate:
    def test_stop_hook_active_bypass(self, tmp_path):
        """stop_hook_active=true → exit 0 even when a gate would otherwise
        block (R08 loop guard).

        Claude Code re-fires Stop after a block with stop_hook_active=True; a
        persistently-failing gate (docs-refresh / code-review on a long
        session) would otherwise re-block forever. This test is
        discriminating: it sets up the long-session block state (write_count
        >= 10, no docs_refreshed flag), proves the block path is live via a
        control run, then asserts the loop signal short-circuits it. The prior
        version passed via the clean-tree exit-0 path regardless of
        stop_hook_active, so it could not catch a missing loop guard.

        ESPALIER_MAINTENANCE_MODE is deleted from the child env (the host may
        run with MAINTENANCE=on, which bypasses Gates 2/3 and would un-earn
        the red).
        """
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        (state_dir / "write_count").write_text("12", encoding="utf-8")  # >= 10 → Gate 2 fires
        # No docs_refreshed flag → Gate 2 blocks absent the loop guard.

        # Control: WITHOUT stop_hook_active the same state blocks — proving the
        # block path is reachable, so the bypass assertion below is non-vacuous.
        blocked = run_hook(
            "stop_gate.py",
            {"hook_event_name": "Stop"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path),
             "ESPALIER_MAINTENANCE_MODE": None},
        )
        assert blocked.returncode == 0  # block is exit-0 + stdout JSON (XOR)
        assert json.loads(blocked.stdout)["decision"] == "block"

        # Loop guard: WITH stop_hook_active the gate is short-circuited.
        result = run_hook(
            "stop_gate.py",
            {"hook_event_name": "Stop", "stop_hook_active": True},
            {"CLAUDE_PROJECT_DIR": str(tmp_path),
             "ESPALIER_MAINTENANCE_MODE": None},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""  # no block JSON emitted

    def test_clean_working_tree_allows_stop(self, tmp_path):
        """No git repo (or clean working tree) → exit 0."""
        result = run_hook(
            "stop_gate.py",
            {"hook_event_name": "Stop"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert_hook_allowed(result)

    def test_block_output_is_json_with_reason(self, tmp_path):
        """When blocked, stdout is valid JSON with top-level decision/reason."""
        # tmp_path is not a git repo, so no changes → always exit 0 in test.
        # We verify the block() helper produces correct JSON by calling it directly.
        stop_gate = HOOKS_DIR / "stop_gate.py"
        import importlib.util
        spec = importlib.util.spec_from_file_location("stop_gate", stop_gate)
        mod = importlib.util.module_from_spec(spec)
        # TP-120b: register in sys.modules so Python 3.14's @dataclass
        # decorator on ResolvedTests can resolve forward refs via
        # sys.modules[cls.__module__].
        sys.modules["stop_gate"] = mod
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = spec.loader.get_code(mod.__name__)
            exec(compile(open(stop_gate, encoding="utf-8").read(), stop_gate, "exec"), vars(mod))
            mod.block("test reason")
        output = json.loads(buf.getvalue())
        assert output["decision"] == "block"
        assert output["reason"] == "test reason"


# ─── write_guard.py ─────────────────────────────────────────────────────────


class TestWriteGuard:
    def test_write_to_target_advisory_only(self, tmp_path):
        """Write to target/foo.py → exit 0 (advisory warning, not a hard block)."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "target/foo.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0

    def test_write_to_protected_zone_denied(self, tmp_path):
        """Write to tools/cc/foo.py → exit 2 (DENY, protected zone)."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "tools/cc/hooks/foo.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_write_to_output_allowed(self, tmp_path):
        """Write to output/CLAUDE.md → exit 0, no warning."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "output/CLAUDE.md"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "WARNING" not in result.stderr

    def test_write_to_memory_allowed(self, tmp_path):
        """Write to ESPALIER_MEMORY.md → exit 0, no warning (root-level managed doc)."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "ESPALIER_MEMORY.md"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "WARNING" not in result.stderr

    def test_write_outside_project_allowed(self, tmp_path):
        """Write to /etc/passwd → exit 0 (harness warns, doesn't cage)."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "/etc/passwd"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert_hook_allowed(result)

    def test_bash_rm_rf_slash_blocked(self, tmp_path):
        """Bash rm -rf / → exit 2 (hard block)."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_bash_rm_rf_star_blocked(self, tmp_path):
        """Bash rm -rf * → DENY (exit 0 + permissionDecision='deny').

        write_guard denies via the PreToolUse structured channel, NOT exit 2
        (channel-XOR). The prior ``returncode == 0``-only assertion was vacuous
        — true for allow AND deny — and the "exit 2" docstring was wrong; assert
        the decision itself via assert_hook_denied (C-5)."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf *"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert_hook_denied(result, contains_reason="recursive delete")

    def test_bash_rm_rf_target_speed_bumped(self, tmp_path):
        """Bash `rm -rf <relative target>` → CP-RMRF soft speed-bump (deny that
        asks for re-issue). A relative source dir / ~ / $VAR path is easy to get
        wrong and has no recovery, so write_guard speed-bumps it. (A bare
        `returncode == 0` masked this deny — the operation is not a clean allow.)"""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf target"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert_hook_denied(result, contains_reason="recursive delete")

    def test_bash_rm_rf_of_a_dirty_tracked_dir_is_snapshotted_and_the_nudge_says_so(self, tmp_path):
        """DEF-802, end to end through the hook: a recursive-force delete of a
        directory holding a dirty tracked file takes a `git stash create`
        snapshot BEFORE the nudge, the nudge names it, the re-issue passes and
        is snapshotted again (the re-issue is the run that deletes), and the
        dirty line is recoverable from the sha the log holds. An untracked
        target draws the honest text and no snapshot -- the promise is exactly
        as wide as the net."""
        def git(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run(["git", "-C", str(tmp_path), *args], capture_output=True,
                                  text=True, check=True, encoding="utf-8")
        git("init", "-q", ".")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("committed\n", encoding="utf-8")
        git("add", ".")
        git("commit", "-qm", "init")
        (tmp_path / "src" / "app.py").write_text("DIRTY\n", encoding="utf-8")
        (tmp_path / "scratch").mkdir()
        (tmp_path / "scratch" / "x").write_text("x\n", encoding="utf-8")
        assert git("status", "--porcelain").stdout.startswith(" M src/app.py")   # the stressor exists
        env = {"CLAUDE_PROJECT_DIR": str(tmp_path)}
        log_path = tmp_path / "cc" / "discard_snapshots.log"

        def log_lines() -> list[str]:
            return log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []

        payload = {"tool_name": "Bash", "tool_input": {"command": "rm -rf src"}}
        first = run_hook("write_guard.py", payload, env)
        assert_hook_denied(first, contains_reason="snapshot just taken")
        assert len(log_lines()) == 1
        sha = log_lines()[0].split("\t")[1]
        assert git("show", f"{sha}:src/app.py").stdout == "DIRTY\n"
        second = run_hook("write_guard.py", payload, env)
        assert_hook_allowed(second)
        assert len(log_lines()) == 2, "the re-issue -- the run that deletes -- is snapshotted too"
        untracked = run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf scratch"}}, env,
        )
        assert_hook_denied(untracked, contains_reason="has no recovery;")
        assert "snapshot" not in untracked.stdout
        assert len(log_lines()) == 2, "an untracked target takes no snapshot"

    def test_bash_pytest_allowed(self, tmp_path):
        """Bash pytest → exit 0."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "pytest tests/"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert_hook_allowed(result)

    def test_edit_to_builder_denied(self, tmp_path):
        """Edit to espalier/managed_paths.py → DENY on self-host repo.

        Per TP-13 Task 13-A, `espalier/` is context-driven: protected on the
        self-host repo (where it's our package source), NOT protected on
        user repos. tmp_path is marked self-host via the 5-signal layout
        (TP-76).
        """
        _make_self_host_layout(tmp_path)
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Edit", "tool_input": {"file_path": "espalier/managed_paths.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_edit_to_user_espalier_dir_allowed(self, tmp_path):
        """User repo with its own espalier/ dir: edits NOT denied (TP-13 13-A).

        Critical regression — the original hardcoded list denied edits to
        any `espalier/` path unconditionally, which would have blocked a
        user repo that happened to have its own `espalier/` directory.
        """
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "user-app"\n', encoding="utf-8")
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Edit", "tool_input": {"file_path": "espalier/foo.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        # Allow path: empty stdout, no deny payload.
        assert not result.stdout.strip()

    def test_write_to_reports_allowed(self, tmp_path):
        """Write to reports/analysis.json → exit 0, no warning."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "reports/analysis.json"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "WARNING" not in result.stderr

    def test_write_to_tests_allowed(self, tmp_path):
        """Write to tests/test_hooks.py → exit 0, no warning."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "tests/test_hooks.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "WARNING" not in result.stderr


class TestWriteGuardBashPatterns:
    """TP-55 BC-028: Bash tool inline-assignment of harness env vars
    is denied so operators learn the parent-shell discipline. The
    single `_HARNESS_ENV_PREFIX_RE` covers BOTH `ESPALIER_MAINTENANCE_MODE`
    and `ESPALIER_STOP_GATE` — the running-hook-inheritance contract is
    identical for both vars, so distinguishing them is incoherent.
    """

    def test_maintenance_env_prefix_denied(self, tmp_path):
        """BC-028: ESPALIER_MAINTENANCE_MODE=1 prefix in Bash tool denied."""
        result = run_hook(
            "write_guard.py",
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "ESPALIER_MAINTENANCE_MODE=1",
                },
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        body = json.loads(result.stdout)
        decision = body["hookSpecificOutput"]["permissionDecision"]
        reason = body["hookSpecificOutput"]["permissionDecisionReason"]
        assert decision == "deny", f"expected deny; got {decision!r} / {reason!r}"
        # Must surface the harness-env-prefix message, not the auto-generated
        # "matches pattern '...'" fallback. Compared against the template rather
        # than a copied literal (§14 derive, don't hand-copy): the previous
        # substring assertion pinned wording, so rewording the message reddened
        # this test for no behavioural reason.
        assert reason == _denial_reasons.HARNESS_ENV_PREFIX_INLINE

    def test_env_prefix_form_denied(self, tmp_path):
        """`env VAR=val ...` form is also denied (the regex catches
        the ESPALIER_* token regardless of the leading `env` word)."""
        result = run_hook(
            "write_guard.py",
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "env ESPALIER_MAINTENANCE_MODE=1",
                },
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        body = json.loads(result.stdout)
        assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert (
            body["hookSpecificOutput"]["permissionDecisionReason"]
            == _denial_reasons.HARNESS_ENV_PREFIX_INLINE
        )

    def test_stop_gate_env_prefix_denied(self, tmp_path):
        """BC-028b: ESPALIER_STOP_GATE inline assignment is also denied.

        Reasoning: the parent-shell-before-launch contract applies
        identically to STOP_GATE; the single regex covers both vars.
        """
        result = run_hook(
            "write_guard.py",
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "ESPALIER_STOP_GATE=full",
                },
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        body = json.loads(result.stdout)
        reason = body["hookSpecificOutput"]["permissionDecisionReason"]
        assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "ESPALIER_STOP_GATE" in reason

    def test_unrelated_env_prefix_allowed(self, tmp_path):
        """Non-harness env vars (e.g., LANG=, PATH=, PYTHONPATH=) must
        pass through — the regex must not over-match.
        """
        result = run_hook(
            "write_guard.py",
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "LANG=C python3 -c 'pass'",
                },
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        # No deny payload on stdout for an allowed command.
        assert not result.stdout.strip()

    # ─── TP-154: command-position anchor (quoted-arg over-match) ─────────
    #
    # The deny must require COMMAND POSITION, not mere presence of the
    # token. An env literal sitting inside a quoted argument (a commit
    # message, a `--description "..."`) is DATA, not a command prefix, and
    # must NOT be denied — while every real command-position prefix stays
    # denied. The must-ALLOW tests below are the earn-the-red (they fail
    # against the pre-fix bare-`\b` regex); the must-DENY tests guard the
    # narrowing against widening a bypass.

    def _command(self, command: str, tmp_path) -> subprocess.CompletedProcess:
        return run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": command}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )

    def test_env_literal_in_commit_message_allowed(self, tmp_path):
        """TP-154: harness env literal inside a quoted commit message is
        argument data, not a command-position prefix — must NOT be denied."""
        result = self._command(
            'git commit -m "set ESPALIER_MAINTENANCE_MODE=1 before launch"',
            tmp_path,
        )
        assert result.returncode == 0
        assert not result.stdout.strip(), result.stdout

    def test_env_literal_in_description_arg_allowed(self, tmp_path):
        """TP-154: the canonical TP-151 false positive — the literal inside
        a `--description "..."` quoted argument must NOT be denied."""
        result = self._command(
            "python3 tools/cc/cognitive_blueprint.py record "
            '--description "... inline ESPALIER_MAINTENANCE_MODE=1 is blocked ..."',
            tmp_path,
        )
        assert result.returncode == 0
        assert not result.stdout.strip(), result.stdout

    def test_stop_gate_literal_in_quoted_arg_allowed(self, tmp_path):
        """TP-154: ESPALIER_STOP_GATE literal as quoted-argument data is allowed."""
        result = self._command('git commit -m "see docs: ESPALIER_STOP_GATE=full"', tmp_path)
        assert result.returncode == 0
        assert not result.stdout.strip(), result.stdout

    def test_usr_bin_env_prefix_still_denied(self, tmp_path):
        """TP-154 (adversarial): the absolute-path `/usr/bin/env VAR=1` form
        is a real command-position prefix — must stay denied after the
        anchor narrowing (a freestanding `\\b(?:env|sudo)` branch)."""
        result = self._command("/usr/bin/env ESPALIER_MAINTENANCE_MODE=1", tmp_path)
        body = json.loads(result.stdout)
        assert body["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_sudo_env_prefix_still_denied(self, tmp_path):
        """TP-154 (adversarial): `sudo VAR=1 cmd` puts the env-prefix in
        command position behind sudo — must stay denied."""
        result = self._command("sudo ESPALIER_MAINTENANCE_MODE=1", tmp_path)
        body = json.loads(result.stdout)
        assert body["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_env_dash_flag_prefix_still_denied(self, tmp_path):
        """TP-154 (adversarial): `env -i VAR=1` — a flag between `env` and
        the var must not slip the prefix past the anchor."""
        result = self._command("env -i ESPALIER_MAINTENANCE_MODE=1", tmp_path)
        body = json.loads(result.stdout)
        assert body["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_chained_assignment_prefix_still_denied(self, tmp_path):
        """TP-154 (adversarial): a benign leading assignment followed by the
        real harness prefix (`ENV=x VAR=1 cmd`) is still command position."""
        result = self._command("ENV=x ESPALIER_MAINTENANCE_MODE=1", tmp_path)
        body = json.loads(result.stdout)
        assert body["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_command_substitution_prefix_still_denied(self, tmp_path):
        """TP-154: the env-prefix inside `$(...)` runs in command position —
        must stay denied (the case the rejected quote-blanker would widen)."""
        result = self._command('echo "$(ESPALIER_STOP_GATE=full)"', tmp_path)
        body = json.loads(result.stdout)
        assert body["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_separator_prefix_still_denied(self, tmp_path):
        """TP-154: a real prefix after a `;` separator stays denied."""
        result = self._command("foo; ESPALIER_MAINTENANCE_MODE=1", tmp_path)
        body = json.loads(result.stdout)
        assert body["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_env_prefix_regex_redos_safe(self):
        """TP-154: the command-position anchor must not reintroduce
        catastrophic backtracking. Newline lives in the separator class, so
        a 50k-newline body that overlapped a trailing `\\s*` took ~26s in the
        naive draft; the horizontal-only `[ \\t]` anchors keep it linear."""
        import time

        sys.path.insert(0, str(HOOKS_DIR))
        import write_guard  # noqa: E402  (sibling import via HOOKS_DIR on sys.path)

        pathological = "\n" * 50000
        start = time.perf_counter()
        write_guard._HARNESS_ENV_PREFIX_RE.search(pathological)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < _ENV_PREFIX_CEILING_MS, (
            f"possible ReDoS: regex took {elapsed_ms:.1f}ms on 50k newlines "
            f"(ceiling {_ENV_PREFIX_CEILING_MS}ms, floor {_ENV_PREFIX_FLOOR_MS}ms)"
        )


class TestWriteGuardTypeCoercion:
    """C1 / BC-023 — non-str ``file_path`` payloads must fail-closed.

    Pre-fix shape: ``os.path.expanduser(int)`` raised TypeError, bubbled
    to ``SystemExit(main())``, exit 1 — which the Claude Code hook
    protocol treats as a non-blocking script error (the tool call
    proceeds). Live exploit reproduced in TP-48 audit, 2026-05-15.

    Post-fix shape: ``check_write_edit`` type-checks ``file_path`` and
    returns ``deny()`` (exit 0 + JSON deny). The ``main()`` umbrella
    catches anything that slips past (e.g. non-str ``command`` to Bash)
    and also returns ``deny()``.
    """

    def test_int_file_path_denied(self, tmp_path):
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": 42, "content": "x"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "int" in output["hookSpecificOutput"]["permissionDecisionReason"]

    def test_null_file_path_denied(self, tmp_path):
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": None, "content": "x"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "NoneType" in output["hookSpecificOutput"]["permissionDecisionReason"]

    def test_list_file_path_denied(self, tmp_path):
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": ["a", "b"], "content": "x"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "list" in output["hookSpecificOutput"]["permissionDecisionReason"]

    def test_dict_file_path_denied(self, tmp_path):
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Edit", "tool_input": {"file_path": {"k": "v"}, "content": "x"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "dict" in output["hookSpecificOutput"]["permissionDecisionReason"]

    def test_bool_file_path_denied(self, tmp_path):
        result = run_hook(
            "write_guard.py",
            {"tool_name": "NotebookEdit", "tool_input": {"file_path": True}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "bool" in output["hookSpecificOutput"]["permissionDecisionReason"]

    def test_empty_string_file_path_allowed(self, tmp_path):
        """Empty string preserves v0.6.x permissive behavior — no path to check."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "", "content": "x"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert not result.stdout.strip()

    def test_missing_file_path_allowed(self, tmp_path):
        """Field absent from payload — no path to check, allow."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"content": "x"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert not result.stdout.strip()

    def test_main_umbrella_fails_closed_on_bash_non_str_command(self, tmp_path):
        """BaseException umbrella catches non-Write crashes too.

        Bash with non-str ``command`` would otherwise raise inside
        ``check_bash_dangerous_patterns`` (re.search against int).
        Umbrella catches it → deny + stderr trace.
        """
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": 42}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "internal error" in output["hookSpecificOutput"]["permissionDecisionReason"]
        assert "write_guard crashed" in result.stderr

    def test_mcp_non_str_path_field_denied(self, tmp_path):
        """MCP loop now denies on truthy non-str path-shaped fields (parity
        with check_write_edit). Pre-fix: ``continue`` silently skipped the
        field, leaving the protected-zone gate dormant on malformed MCP
        payloads. Post-fix: deny with type name in the reason."""
        result = run_hook(
            "write_guard.py",
            {
                "tool_name": "mcp__filesystem__write_file",
                "tool_input": {"path": 42, "content": "x"},
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        assert "Malformed MCP payload" in reason
        assert "int" in reason

    def test_mcp_empty_path_field_still_skipped(self, tmp_path):
        """Empty / missing MCP fields stay on the ``continue`` path; only
        truthy non-str triggers deny. Sanity guard so we didn't widen the
        deny to legitimate "field not present" cases."""
        result = run_hook(
            "write_guard.py",
            {
                "tool_name": "mcp__filesystem__write_file",
                "tool_input": {"path": "", "content": "x"},
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        # No deny — empty path field means no path to check.
        assert not result.stdout.strip()


class TestPreToolUseMatcherCoverage:
    """C2 (TP-48) — PreToolUse matcher widened to ``"*"`` so non-mutation
    tool dispatches (Agent -- Task on older Claude Code -- TodoWrite,
    SlashCommand, BashOutput) reach write_guard's kill-switch gate.

    Pre-fix the matcher was narrowed to
    ``"Write|Edit|NotebookEdit|Bash|PowerShell|ExitPlanMode|mcp__.*"``
    and Claude Code filtered the hook out before subprocess spawn — the
    kill-switch never saw a subagent dispatch. This class asserts
    that write_guard.main(), when invoked with these tool names, both
    short-circuits the read-only path AND honors the kill-switch.
    """

    # `Agent` is the subagent tool since Claude Code 2.1.63; `Task` stays for
    # adopters on an older Claude Code (the contract pins coverage of both).
    NON_MUTATION_TOOLS = ("Agent", "Task", "TodoWrite", "SlashCommand", "BashOutput")

    def test_non_mutation_tools_pass_through_without_kill_switch(self, tmp_path):
        """write_guard returns 0 for non-mutation tools (no protected-zone
        check needed) — the MUTATION_TOOLS filter takes the read-only
        fast-path (after the always-on kill-switch scan, which finds nothing
        here). Line pin dropped: it drifts with surface edits."""
        for tool_name in self.NON_MUTATION_TOOLS:
            result = run_hook(
                "write_guard.py",
                {"tool_name": tool_name, "tool_input": {}},
                {"CLAUDE_PROJECT_DIR": str(tmp_path)},
            )
            assert result.returncode == 0, (
                f"{tool_name}: expected exit 0, got rc={result.returncode} "
                f"stderr={result.stderr!r}"
            )
            assert not result.stdout.strip(), (
                f"{tool_name}: read-only fast-path must not emit JSON deny; "
                f"got {result.stdout!r}"
            )

    def test_kill_switch_fires_for_task_dispatch(self, tmp_path):
        """Plant a kill-switch settings.json, dispatch each non-mutation
        tool, and assert write_guard returns a deny payload. Pre-TP-48
        Claude Code filtered Task out before write_guard saw it — kill-
        switch effectively didn't apply to subagent dispatches."""
        # Plant kill-switch.
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "settings.json").write_text(
            json.dumps({"disableAllHooks": True}), encoding="utf-8",
        )
        for tool_name in self.NON_MUTATION_TOOLS:
            result = run_hook(
                "write_guard.py",
                {"tool_name": tool_name, "tool_input": {}},
                {"CLAUDE_PROJECT_DIR": str(tmp_path)},
            )
            assert result.returncode == 0, (
                f"{tool_name}: kill-switch path must exit 0 with JSON deny; "
                f"got rc={result.returncode} stderr={result.stderr!r}"
            )
            output = json.loads(result.stdout)
            assert output["hookSpecificOutput"]["permissionDecision"] == "deny", (
                f"{tool_name}: expected deny, got {output!r}"
            )
            assert "kill-switch" in output["hookSpecificOutput"][
                "permissionDecisionReason"
            ].lower()


class TestBashCommandCapTrailing:
    """M2 (TP-49) — bash/PowerShell command cap was front-only (``[:32_768]``),
    so a 33KB padded prefix hid trailing redirects to protected zones from
    the path-extraction regexes. Post-fix scans head + tail (16KB each)
    with a ``\\n`` separator that prevents matches across the split.
    """

    def test_trailing_redirect_after_33kb_pad_blocked(self, tmp_path):
        """Pad the front with 33KB of harmless ``A`` chars, then a trailing
        protected-path redirect. The pre-fix cap dropped everything past
        byte 32768 so the regex never saw the redirect; post-fix the tail
        slice catches it."""
        pad = "A" * 33_000
        command = f"echo {pad}; echo evil >> tools/cc/hooks/session_start.py"
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": command}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny", (
            f"trailing redirect past front-cap must be blocked; got {output!r}"
        )

    def test_short_command_still_works(self, tmp_path):
        """Sanity: a normal short command goes through the unchanged path
        (no split). Regression guard."""
        result = run_hook(
            "write_guard.py",
            {
                "tool_name": "Bash",
                "tool_input": {"command": "echo x > tools/cc/hooks/x.py"},
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_powershell_trailing_redirect_after_33kb_pad_blocked(self, tmp_path):
        """PowerShell extractor uses the same _cap_for_scan helper."""
        pad = "A" * 33_000
        command = f"Write-Host {pad}; Set-Content -Path tools/cc/hooks/x.py -Value evil"
        result = run_hook(
            "write_guard.py",
            {"tool_name": "PowerShell", "tool_input": {"command": command}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


class TestUnicodeNormalization:
    """H1 (TP-49) / BC-025 — Unicode-equivalent codepoints must be folded
    against PROTECTED_*/ALLOWED_*/EXEMPT_* prefix lists.

    Pre-fix the comparison used ``.lower()`` which is ASCII-only.
    Fullwidth Latin (U+FF21..U+FF5A), Turkish dotted I (U+0130), German
    ß (U+00DF), and other Unicode equivalents fold to the ASCII form on
    case-insensitive APFS via the filesystem's Unicode case-folding tables
    — the file would land in the protected zone but ``startswith`` on
    the lowercased string missed it.

    Post-fix uses ``unicodedata.normalize("NFKC", path).casefold()``.
    NFKC collapses compatibility variants (fullwidth → ASCII); casefold
    handles ß → ss and Turkish I → i.
    """

    @pytest.mark.parametrize("file_path,description", [
        ("tＯＯls/cc/hooks/x.py", "fullwidth O (U+FF2F) in tools/"),
        ("ｔｏｏｌｓ/cc/hooks/x.py", "fully-fullwidth tools/"),
        ("TOOLS/cc/hooks/x.py", "uppercase Latin tools/"),
        ("Tools/CC/Hooks/x.py", "mixed case tools/cc/hooks/"),
        (".CLAUDE/settings.json", "uppercase .claude/"),
    ])
    def test_unicode_variants_of_protected_blocked(
        self, tmp_path, file_path, description,
    ):
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": file_path}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0, description
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny", (
            f"{description}: expected deny for {file_path!r}, got {output!r}"
        )

    def test_ascii_baseline_still_blocks(self, tmp_path):
        """Sanity: the unchanged ASCII path still blocks (no regression)."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "tools/cc/hooks/x.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_root_file_still_allowed(self, tmp_path):
        """README.md is root-level and never protected. Normalization
        must not accidentally widen the protected set."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "README.md"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert not result.stdout.strip()

    def test_unicode_allowed_path_still_allowed(self, tmp_path):
        """Fullwidth path matching the allowlist (cc/blueprints/*.json) is
        a protected-AND-allowed write — the harness lets it through.
        Without _is_allowed's NFKC update this would spuriously deny."""
        result = run_hook(
            "write_guard.py",
            {
                "tool_name": "Write",
                "tool_input": {"file_path": "ＣＣ/blueprints/test.json"},
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        # cc/blueprints/*.json is in ALLOWED_IN_PROTECTED — exit 0 allow.
        assert result.returncode == 0
        assert not result.stdout.strip(), (
            f"unicode allowed path must not be denied; got {result.stdout!r}"
        )


class TestConfigGuard:
    """H7 (TP-48) — config_guard is the only ConfigChange security gate
    and had zero direct test coverage before this class. The hook blocks
    kill-switch settings on project/local/user sources and audits-only on
    `policy_settings` (which Claude Code's protocol declares non-blockable).
    """

    @staticmethod
    def _plant_kill_switch(tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        settings = claude_dir / "settings.json"
        settings.write_text(
            json.dumps({"disableAllHooks": True}), encoding="utf-8",
        )
        return settings

    @staticmethod
    def _assert_block_with_kill_switch(result):
        assert result.returncode == 0, (
            f"config_guard must exit 0 with JSON block; got rc={result.returncode} "
            f"stderr={result.stderr!r}"
        )
        data = json.loads(result.stdout)
        assert data.get("decision") == "block", (
            f"expected decision=block, got {data!r}"
        )
        assert "kill-switch" in data.get("reason", "").lower()

    def test_kill_switch_in_project_source_blocks(self, tmp_path):
        self._plant_kill_switch(tmp_path)
        result = run_hook(
            "config_guard.py",
            {"source": "project", "file_path": ".claude/settings.json"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        self._assert_block_with_kill_switch(result)

    def test_kill_switch_in_local_source_blocks(self, tmp_path):
        self._plant_kill_switch(tmp_path)
        result = run_hook(
            "config_guard.py",
            {"source": "local", "file_path": ".claude/settings.json"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        self._assert_block_with_kill_switch(result)

    def test_kill_switch_in_user_source_blocks(self, tmp_path):
        self._plant_kill_switch(tmp_path)
        result = run_hook(
            "config_guard.py",
            {"source": "user", "file_path": ".claude/settings.json"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        self._assert_block_with_kill_switch(result)

    def test_policy_settings_source_audits_only(self, tmp_path):
        """ConfigChange CANNOT block managed `policy_settings` per protocol.
        Hook emits a stderr advisory and exits 0 with no JSON block."""
        self._plant_kill_switch(tmp_path)
        result = run_hook(
            "config_guard.py",
            {"source": "policy_settings", "file_path": ".claude/settings.json"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        # No JSON block on stdout.
        if result.stdout.strip():
            data = json.loads(result.stdout)
            assert data.get("decision") != "block", (
                f"policy_settings source must NOT emit block; got {data!r}"
            )
        # Stderr advisory is the documented signal.
        assert "policy_settings" in result.stderr or "[WARN]" in result.stderr, (
            f"expected stderr advisory; got {result.stderr!r}"
        )

    def test_empty_source_still_blocks_when_kill_switch_present(self, tmp_path):
        """Source omitted from payload defaults to "" — per main() line 115
        the condition ``source in BLOCKING_SOURCES or source not in
        AUDIT_ONLY_SOURCES`` evaluates True for empty string, so the block
        path runs (defense-in-depth — bare findings are treated as blocking
        unless explicitly tagged audit-only)."""
        self._plant_kill_switch(tmp_path)
        result = run_hook(
            "config_guard.py",
            {"file_path": ".claude/settings.json"},  # no `source`
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        self._assert_block_with_kill_switch(result)

    def test_unknown_nonempty_source_still_blocks_when_kill_switch_present(self, tmp_path):
        """Fail-closed on an UNKNOWN NON-EMPTY source: a source Claude Code never
        emits today (e.g. a future ``'enterprise'`` tier) is not in
        AUDIT_ONLY_SOURCES, so per _run_main line 172 it falls through to the
        block path — an unknown source must never silently allow a kill-switch.

        Distinct from test_empty_source_still_blocks_when_kill_switch_present: the
        empty '' leg is falsy, so a regression that special-cases truthy-unknown
        sources to fail-OPEN would slip past the empty-source test but is caught
        here (B-3 — the audit's fail-closed unknown-source gap)."""
        self._plant_kill_switch(tmp_path)
        result = run_hook(
            "config_guard.py",
            {"source": "enterprise", "file_path": ".claude/settings.json"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        self._assert_block_with_kill_switch(result)

    def test_malformed_json_in_settings_does_not_crash(self, tmp_path):
        """A malformed settings.json must not crash the hook. _scan_payload
        catches JSONDecodeError and the fall-back inventory scan handles
        the file via the same lenient loader; no findings → allow."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "settings.json").write_text(
            "{ not valid json", encoding="utf-8",
        )
        result = run_hook(
            "config_guard.py",
            {"source": "project", "file_path": ".claude/settings.json"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0, (
            f"malformed JSON must not crash config_guard; "
            f"rc={result.returncode} stderr={result.stderr!r}"
        )
        # No findings → no block emitted.
        if result.stdout.strip():
            data = json.loads(result.stdout)
            assert data.get("decision") != "block"

    def test_path_traversal_file_path_does_not_escape_root(self, tmp_path):
        """A traversal ``file_path`` (``../../etc/passwd``) must be dropped
        by the ``relative_to(root)`` guard at config_guard.py:69. The hook
        falls back to the inventory scan but does not open files outside
        the repo. No crash; exit 0 (no findings in fresh tmp repo)."""
        result = run_hook(
            "config_guard.py",
            {
                "source": "project",
                "file_path": "../../../../../../etc/passwd",
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        # Either empty stdout (no findings) or a block — never a crash.
        if result.stdout.strip():
            data = json.loads(result.stdout)
            # If somehow blocked, ensure it's not based on a leaked /etc/passwd path.
            assert "/etc/passwd" not in data.get("reason", "")


# ─── TP-142 (FM-2 §10.4): config_guard fail-closed umbrella ───────────


class TestConfigGuardFailClosed:
    """FM-2 §10.4 close: config_guard.main MUST fail-closed on internal exception.

    Sister-site contract of write_guard's and plan_guard's umbrellas.
    Negative proof: inject a function that raises inside _run_main;
    assert the wrapper exits 0 with a block() payload on stdout
    (channel-XOR), NOT exit 1 (which Claude Code would treat as
    "non-blocking script error" and the settings change would proceed).
    """

    @staticmethod
    def _import_config_guard():
        import importlib
        sys.path.insert(0, str(HOOKS_DIR))
        try:
            if "config_guard" in sys.modules:
                return importlib.reload(sys.modules["config_guard"])
            return importlib.import_module("config_guard")
        finally:
            sys.path.remove(str(HOOKS_DIR))

    def test_fail_closed_on_runtime_error(self, monkeypatch, capsys):
        config_guard = self._import_config_guard()

        def boom():
            raise RuntimeError("simulated internal failure")

        monkeypatch.setattr(config_guard, "_scan_payload",
                            lambda *_args, **_kw: (_ for _ in ()).throw(
                                RuntimeError("simulated internal failure")))
        # read_stdin_safely still works; the boom comes from _scan_payload.
        monkeypatch.setattr(config_guard, "read_stdin_safely",
                            lambda: {"source": "project",
                                     "file_path": ".claude/settings.json"},
                            raising=False)
        # The _hook_utils.read_stdin_safely is imported inside _run_main
        # via `from _hook_utils import read_stdin_safely`. Patch the
        # symbol on the _hook_utils module so the late binding picks
        # the patched function up.
        monkeypatch.setattr(config_guard._hook_utils, "read_stdin_safely",
                            lambda: {"source": "project",
                                     "file_path": ".claude/settings.json"})

        rc = config_guard.main()
        captured = capsys.readouterr()
        assert rc == 0
        assert "[ERROR] config_guard crashed: RuntimeError" in captured.err
        assert captured.out.strip(), "expected block envelope on stdout"
        data = json.loads(captured.out)
        assert data.get("decision") == "block"
        assert "config_guard internal error" in data.get("reason", "")

    def test_fail_closed_on_attribute_error(self, monkeypatch, capsys):
        """ConfigChange payload shape changes (future-CC API drift) would
        surface as AttributeError. Same fail-closed contract applies."""
        config_guard = self._import_config_guard()

        def boom(*_args, **_kw):
            raise AttributeError("'NoneType' object has no attribute 'get'")

        monkeypatch.setattr(config_guard._hook_utils, "read_stdin_safely", boom)

        rc = config_guard.main()
        captured = capsys.readouterr()
        assert rc == 0
        assert "[ERROR] config_guard crashed: AttributeError" in captured.err
        data = json.loads(captured.out)
        assert data.get("decision") == "block"


# ─── post_write_check.py ────────────────────────────────────────────────────


class TestPostWriteCheck:
    def test_valid_settings_json_no_warnings(self, tmp_path):
        """Write valid JSON to .claude/settings.json → exit 0, no warnings."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text('{"valid": true}', encoding="utf-8")
        result = run_hook(
            "post_write_check.py",
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(claude_dir / "settings.json")},
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "\u26a0" not in result.stderr

    def test_invalid_settings_json_warns(self, tmp_path):
        """Write bad JSON to .claude/settings.json → exit 0, stderr has warning."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text("{bad json", encoding="utf-8")
        result = run_hook(
            "post_write_check.py",
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(claude_dir / "settings.json")},
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "invalid JSON" in result.stderr

    def test_non_harness_path_no_action(self, tmp_path):
        """Write to user project file → exit 0, no action."""
        result = run_hook(
            "post_write_check.py",
            {
                "tool_name": "Write",
                "tool_input": {"file_path": "src/main.py"},
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert result.stderr.strip() == ""

    def test_agent_placeholder_detection(self, tmp_path):
        """Agent md with placeholders → stderr warning."""
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "my-agent.md").write_text("# Agent\n\nUses <fill> framework.\n", encoding="utf-8")
        result = run_hook(
            "post_write_check.py",
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(agents_dir / "my-agent.md")},
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "<fill>" in result.stderr

    def test_skill_placeholder_detection(self, tmp_path):
        """DEF-782: a skill body with a placeholder warns at the write, the
        way an agent body does -- the third .claude/ kind reached the hook."""
        skill_dir = tmp_path / ".claude" / "skills" / "reflect"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Skill\n\nUses <fill> framework.\n", encoding="utf-8")
        result = run_hook(
            "post_write_check.py",
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(skill_dir / "SKILL.md")},
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "<fill>" in result.stderr

    def test_root_md_placeholder_detection(self, tmp_path):
        """Root CLAUDE.md with placeholders → stderr warning."""
        (tmp_path / "CLAUDE.md").write_text("# Project\n\nThis is a <repo> project.\n", encoding="utf-8")
        result = run_hook(
            "post_write_check.py",
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(tmp_path / "CLAUDE.md")},
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "<repo>" in result.stderr

    def test_tools_cc_python_syntax_check(self, tmp_path):
        """Write Python file with syntax error to tools/cc/ → stderr warning."""
        tools_dir = tmp_path / "tools" / "cc"
        tools_dir.mkdir(parents=True)
        (tools_dir / "my_tool.py").write_text("def foo(:\n    pass\n", encoding="utf-8")
        result = run_hook(
            "post_write_check.py",
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(tools_dir / "my_tool.py")},
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "syntax error" in result.stderr.lower()


# ─── session_start.py ───────────────────────────────────────────────────────


class TestSessionStart:
    def _context(self, result) -> str:
        """Extract additionalContext from stdout structured JSON."""
        data = json.loads(result.stdout)
        return data["hookSpecificOutput"]["additionalContext"]

    def test_always_exits_zero(self, tmp_path):
        """SessionStart hook always exits 0 regardless of state."""
        result = run_hook(
            "session_start.py",
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0

    def test_clean_state_flags_tolerates_concurrent_unlink(self, tmp_path, monkeypatch):
        """TP-192 W2-3: a concurrent SessionStart unlinking a named flag in the
        exists()->unlink() window must NOT crash ``_clean_state_flags``. Pre-fix
        the FileNotFoundError propagated out of ``main()`` (the lone unguarded
        helper call), exited 1, and suppressed the entire orientation injection.
        Fix is ``unlink(missing_ok=True)``."""
        import importlib.util
        import os as _os

        spec = importlib.util.spec_from_file_location(
            "_tp192_session_start", HOOKS_DIR / "session_start.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        state = tmp_path / ".espalier-state"
        state.mkdir(parents=True)
        (state / "code_reviewed").write_text("1", encoding="utf-8")

        real_unlink = _os.unlink

        def racing_unlink(path, *a, **k):
            # Simulate the file vanishing between exists() and unlink() — only for
            # the flag, so the atomic session_started write is unaffected.
            if "code_reviewed" in str(path):
                raise FileNotFoundError(path)
            return real_unlink(path, *a, **k)

        monkeypatch.setattr(_os, "unlink", racing_unlink)
        # Must not raise (pre-fix: bare unlink() re-raised FileNotFoundError).
        mod._clean_state_flags(tmp_path)

    def test_stdout_is_structured_json(self, tmp_path):
        """stdout must be valid hookSpecificOutput JSON."""
        result = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        data = json.loads(result.stdout)
        assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "additionalContext" in data["hookSpecificOutput"]

    def test_banner_format(self, tmp_path):
        """additionalContext contains the expected harness banner markers."""
        result = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        ctx = self._context(result)
        assert "Espalier-Harness ===" in ctx
        assert "Repo:" in ctx
        assert "Branch:" in ctx
        assert "Surface:" in ctx

    @staticmethod
    def _load_session_start():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_ss_commands_footer", HOOKS_DIR / "session_start.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_commands_footer_bound_to_commands_md(self):
        """The curated core-loop footer names only commands that exist in the
        cc/COMMANDS.md source of truth, and ALL curated names are present (no
        silent drop). Binds the banner to the SoT so it cannot drift to a
        removed/renamed command — the failure mode of the prior hardcoded
        literal (which led with the /accomplish alias and omitted /smoke,
        /preflight)."""
        mod = self._load_session_start()
        repo_root = HOOKS_DIR.parent.parent.parent
        commands_md = (repo_root / "cc" / "COMMANDS.md").read_text(encoding="utf-8")
        present = set(mod._COMMANDS_MD_CELL_RE.findall(commands_md))
        for cmd in mod._CORE_FLOW_COMMANDS:
            assert cmd in present, f"core-flow command {cmd} absent from cc/COMMANDS.md"
        footer = mod._commands_footer(repo_root)
        for token in footer.split()[1:]:  # drop the "Commands:" label
            assert token in present, f"footer names {token!r} absent from cc/COMMANDS.md"

    def test_commands_footer_reads_core_flow_section_else_fallback(self, tmp_path):
        """TP-241: the footer reads cc/COMMANDS.md's rendered `## Core flow`
        section (the source of truth). A COMMANDS.md without that section, or a
        missing file, falls back to the full curated tuple rather than emitting
        an empty banner line."""
        mod = self._load_session_start()
        cc = tmp_path / "cc"
        cc.mkdir()
        # With a Core-flow section: footer = exactly those names (table rows above
        # it are not scanned; a name not in the section does not appear).
        (cc / "COMMANDS.md").write_text(
            "# Commands\n\n| `/status` | x |\n| `/implement-task` | y |\n\n"
            "## Core flow\n\n`/status` `/commit`\n",
            encoding="utf-8",
        )
        footer = mod._commands_footer(tmp_path)
        assert "/status" in footer and "/commit" in footer
        assert "/implement-task" not in footer  # not listed in the Core flow section
        # No Core-flow section -> full curated fallback (never an empty line).
        (cc / "COMMANDS.md").write_text("# Commands\n\n| `/status` | x |\n", encoding="utf-8")
        fb = mod._commands_footer(tmp_path)
        assert "/implement-task" in fb and "/handoff" in fb
        # Missing COMMANDS.md -> same fallback.
        fb2 = mod._commands_footer(tmp_path / "nope")
        assert "/implement-task" in fb2 and "/handoff" in fb2

    def test_commands_footer_reads_a_latin1_commands_md(self, tmp_path):
        """Ledger DEF-829: an adopter's editor re-saved cc/COMMANDS.md in a
        Windows code page. ``UnicodeDecodeError`` is a ``ValueError``, not an
        ``OSError``, so the ``except OSError`` around the strict read let it
        past and the SessionStart crash guard dropped the whole banner, every
        session. The names are ASCII: a replacement character lands in a
        cell and the Core-flow names still parse."""
        mod = self._load_session_start()
        cc = tmp_path / "cc"
        cc.mkdir()
        (cc / "COMMANDS.md").write_bytes(
            b"# Commands\n\n| `/status` | caf\xe9 |\n\n## Core flow\n\n`/status` `/commit`\n"
        )
        footer = mod._commands_footer(tmp_path)
        assert "/status" in footer and "/commit" in footer

    def test_banner_survives_a_latin1_commands_md_through_the_hook(self, tmp_path):
        """The same file through the real hook: the banner is kept (exit 0,
        structured stdout, the Commands line present) and the fail-open crash
        guard never fires. Before the fix stderr carried
        ``session_start crashed: UnicodeDecodeError`` and stdout was empty."""
        cc = tmp_path / "cc"
        cc.mkdir()
        (cc / "COMMANDS.md").write_bytes(
            b"# Commands\n\n| `/status` | caf\xe9 |\n\n## Core flow\n\n`/status` `/commit`\n"
        )
        result = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "session_start crashed" not in result.stderr
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "Commands:" in ctx and "/commit" in ctx

    def test_goal_section_renders_when_present(self, tmp_path):
        """cc/GOAL.md present -> a 'GOAL / PROGRESS' section with the Updated
        line (the staleness signal) appears."""
        mod = self._load_session_start()
        cc = tmp_path / "cc"
        cc.mkdir()
        (cc / "GOAL.md").write_text(
            "## At a glance\nshipping soon\n\n_Updated: 2026-06-29_\n", encoding="utf-8"
        )
        section = mod._goal_section(tmp_path)
        assert "GOAL / PROGRESS" in section
        assert "shipping soon" in section
        assert "Updated:" in section

    def test_goal_section_omitted_when_absent_or_empty(self, tmp_path):
        """No cc/GOAL.md (adopter / fresh clone) or an empty one -> '' so the
        section drops out of the banner entirely (presence IS the gate)."""
        mod = self._load_session_start()
        assert mod._goal_section(tmp_path) == ""
        cc = tmp_path / "cc"
        cc.mkdir()
        (cc / "GOAL.md").write_text("   \n", encoding="utf-8")
        assert mod._goal_section(tmp_path) == ""

    def test_goal_section_reads_a_byte_order_marked_file(self, tmp_path):
        """DEF-797: cc/GOAL.md is hand-written (the /handoff step invites it), and
        Windows PowerShell 5.1's `>` / `Out-File` write UTF-16LE with a
        byte-order mark; an editor adds a UTF-8 one. Both read as text with the
        mark stripped, where the strict read raised into the banner's umbrella
        and the section vanished."""
        mod = self._load_session_start()
        cc = tmp_path / "cc"
        cc.mkdir()
        goal = "## At a glance\nshipping soon\n\n_Updated: 2026-06-29_\n"
        for label, data in (
            ("utf-16le with a byte-order mark", codecs.BOM_UTF16_LE + goal.encode("utf-16-le")),
            ("utf-8 with a byte-order mark", codecs.BOM_UTF8 + goal.encode("utf-8")),
        ):
            (cc / "GOAL.md").write_bytes(data)
            section = mod._goal_section(tmp_path)
            assert "shipping soon" in section and "Updated:" in section, label
            assert "\ufeff" not in section and "\x00" not in section, label

    def test_goal_section_names_a_file_it_cannot_decode(self, tmp_path):
        """A UTF-16 file with no byte-order mark (NUL after every character once
        decoded) or bytes that are not UTF-8 render the header plus one line
        naming the encoding to re-save in -- the section says so instead of
        dropping out."""
        mod = self._load_session_start()
        cc = tmp_path / "cc"
        cc.mkdir()
        goal = "## At a glance\nshipping soon\n"
        for label, data, detail in (
            ("utf-16le, no byte-order mark", goal.encode("utf-16-le"),
             "NUL bytes -- UTF-16 without a byte-order mark?"),
            ("cp1252 with an accent", "caf\xe9\n".encode("cp1252"), "at byte 3"),
        ):
            (cc / "GOAL.md").write_bytes(data)
            section = mod._goal_section(tmp_path)
            assert "GOAL / PROGRESS" in section, label
            assert "this goal snapshot is not UTF-8 text" in section and detail in section, (label, section)
            assert "re-save it as UTF-8" in section, label
            assert "shipping soon" not in section, label

    def test_safe_read_decodes_a_byte_order_marked_memory_file(self, tmp_path, capsys):
        """The memory digest and summary read ESPALIER_MEMORY.md through
        `_safe_read`; a UTF-16 file used to render as every other byte NUL
        through the replacing decode (DEF-797). Marked files read clean. Bytes
        that are neither, or a mark-less UTF-16 file, are named ONCE per file
        on stderr with the encoding to re-save in, and the reporter still
        renders what it can: the replacing decode, with the NULs dropped (which
        recovers the ASCII of a mark-less UTF-16 file) -- it never raises."""
        mod = self._load_session_start()
        memory = tmp_path / "ESPALIER_MEMORY.md"
        text = "# Memory\n\n**Repo:** demo\n"
        memory.write_bytes(codecs.BOM_UTF16_LE + text.encode("utf-16-le"))
        assert mod._safe_read(memory) == text
        memory.write_bytes(codecs.BOM_UTF8 + text.encode("utf-8"))
        assert mod._safe_read(memory) == text
        assert capsys.readouterr().err == ""
        memory.write_bytes(text.encode("utf-16-le"))
        assert mod._safe_read(memory) == text
        assert mod._safe_read(memory) == text
        err = capsys.readouterr().err
        assert err.count("ESPALIER_MEMORY.md is not UTF-8 text (NUL bytes") == 1, err
        assert "re-save it as UTF-8" in err
        other = tmp_path / "docs" / "STANDING_PRINCIPLES.md"
        other.parent.mkdir()
        other.write_bytes(b"caf\xe9\n")
        assert mod._safe_read(other) == "caf\ufffd\n"
        assert "STANDING_PRINCIPLES.md is not UTF-8 text (invalid continuation byte" in capsys.readouterr().err

    def test_goal_section_bounded_and_flagged_when_oversize(self, tmp_path):
        """An oversize GOAL.md is bounded via _bounded('goal') -- honest soft-budget
        truncation + a VISIBLE bloat flag -- rather than silently swallowed."""
        mod = self._load_session_start()
        cc = tmp_path / "cc"
        cc.mkdir()
        (cc / "GOAL.md").write_text("word " * 1000, encoding="utf-8")  # well over the 2KB soft budget
        flags: list[str] = []
        bounded = mod._bounded("goal", mod._goal_section(tmp_path), flags)
        assert "trimmed to fit" in bounded and "cc/GOAL.md" in bounded
        assert len(bounded.encode("utf-8")) <= mod._SOFT_BUDGETS["goal"] + 80
        assert flags and "goal" in flags[0] and "is large" in flags[0]
        assert "cc/GOAL.md" in flags[0]

    def test_context_within_size_budget(self, tmp_path):
        """additionalContext must not exceed the 16000-byte outer ceiling. The
        redesigned banner stays ~5.5KB (digest + standing principles + footgun
        pointer + orientation), so this ceiling is a backstop, not the governor
        (per-section soft budgets bound individual tenants)."""
        result = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        ctx = self._context(result)
        assert len(ctx.encode("utf-8")) <= 16_000, "context exceeds 16000-byte budget"

    def test_orientation_tail_survives_and_catalog_stays_pointer(self, tmp_path):
        """TP-234 (migrated): the orientation tail must always survive within
        budget. The SHARP_EDGES TOC that once threatened overflow is now a
        one-line /recall pointer, so a huge catalog must NOT bloat the banner --
        this doubles as a regression guard that the TOC wall stays retired.

        Calls _build_context with self_host=True against a seeded root (the
        footgun pointer + orientation footgun line are self-host-gated)."""
        mod = self._load_session_start()
        docs = tmp_path / "docs"
        docs.mkdir()
        # ~400 headings: as a TOC this was >16KB; as a pointer it must not matter.
        big_catalog = "\n".join(
            f"## Footgun number {i} with a reasonably long descriptive heading line"
            for i in range(400)
        )
        (docs / "SHARP_EDGES.md").write_text(big_catalog, encoding="utf-8")
        banner = mod._build_context(tmp_path, True, False)
        nbytes = len(banner.encode("utf-8"))
        assert nbytes <= mod._MAX_CONTEXT_BYTES
        assert nbytes < 9_000, "the 400-heading catalog leaked back into the banner"
        assert "## Footgun number 200" not in banner, "catalog headings dumped into the banner"
        # The orientation tail's load-bearing markers must survive:
        assert "first-thoughts" in banner, "first-thoughts orientation truncated"
        assert "confirm or redirect" in banner, "proposed-next instruction truncated"
        assert "REPO/SURFACE/LAST" not in banner, "stale 6-line report instruction lingered"

    def test_summarize_memory_skips_html_comment(self, tmp_path):
        """TP-236: a MULTI-LINE <!-- ... --> block at the top of ESPALIER_MEMORY.md must not
        bury the **Repo:**/**Stack:** identity in the Memory: summary. RED on HEAD
        (only `#` lines were filtered, so the 3-line comment leaks -- including the
        continuation lines that don't start with `<!--`)."""
        mod = self._load_session_start()
        (tmp_path / "ESPALIER_MEMORY.md").write_text(
            "<!-- self-hosted memory log. Adopters get the\n"
            "template shape from examples/ESPALIER_MEMORY.template.md; tracked\n"
            "in the public repo but excluded from the package. -->\n"
            "**Repo:** demo-repo\n"
            "**Stack:** Python CLI\n",
            encoding="utf-8",
        )
        summary = mod._summarize_memory(tmp_path)
        assert "self-hosted memory log" not in summary        # opening line skipped
        assert "excluded from the package" not in summary     # continuation/closing lines too
        assert "**Repo:** demo-repo" in summary               # identity surfaced

    def test_summarize_memory_filters_template_boilerplate(self, tmp_path):
        """A fresh adopter's ESPALIER_MEMORY.md is the init template; its Categorized-memory /
        Pruning-policy prose must NOT leak into the Memory: digest -- only the **Repo:**/**Stack:**
        identity should surface. RED on HEAD (only #/|/<!-- lines are filtered, so the boilerplate
        prose leaks)."""
        mod = self._load_session_start()
        (tmp_path / "ESPALIER_MEMORY.md").write_text(
            "# demo-repo — Project Memory\n\n## Repo Context\n\n"
            "**Repo:** demo-repo\n**Stack:** Python\n\n## Session Log\n\n"
            "**Pruning policy:** Keep the 5 most recent entries; keep this file short.\n\n"
            "## Categorized memory\n\n"
            "For long-form entries that don't fit in the index above, see\n"
            "[`memory/`](memory/).  `espalier init .` creates an empty `memory/`\n"
            "folder with a README explaining the convention.\n",
            encoding="utf-8",
        )
        summary = mod._summarize_memory(tmp_path)
        assert "**Repo:** demo-repo" in summary          # identity surfaced
        assert "Pruning policy" not in summary           # boilerplate filtered
        assert "long-form entries" not in summary
        assert "README explaining the convention" not in summary

    def test_summarize_memory_keeps_an_adopters_own_line_that_opens_like_the_template(self, tmp_path):
        """DEF-382a leg a: the filter matches WHOLE template lines, not their
        opening phrases. An adopter who rewrote the pruning policy, or opened a
        sentence of their own with a template phrase, keeps that line in the
        digest; the template's own lines stay filtered even re-spaced. RED on
        the prefix filter: both adopter lines vanished from the digest."""
        mod = self._load_session_start()
        (tmp_path / "ESPALIER_MEMORY.md").write_text(
            "# demo-repo\n\n**Repo:** demo-repo\n**Stack:** Python\n\n## Session Log\n\n"
            "**Pruning policy:** keep 12 rows; older go to docs/archive.md.\n\n"
            "## Categorized memory\n\n"
            "For long-form entries that don't fit here, see docs/ARCHITECTURE.md.\n"
            "For long-form entries that don't fit in the index above, see\n"
            "[`memory/`](memory/). `espalier init .` creates an empty `memory/`\n"  # re-spaced
            "folder with a README explaining the convention.\n",
            encoding="utf-8",
        )
        summary = mod._summarize_memory(tmp_path)
        assert "**Pruning policy:** keep 12 rows; older go to docs/archive.md." in summary
        assert "For long-form entries that don't fit here, see docs/ARCHITECTURE.md." in summary
        assert "in the index above" not in summary          # the template's own line
        assert "creates an empty" not in summary            # re-spaced, still the template
        assert "README explaining the convention" not in summary

    def test_summarize_memory_filters_the_real_build_memory_md_template(self, tmp_path):
        """Cross-module drift-pin binding the `_MEMORY_TEMPLATE_LINES` filter to its CANON,
        `cli._build_memory_md` -- the template those four lines were hand-copied from. The hook
        is zero-import and cannot reference the template directly, so the copy can silently rot: edit
        the template's prose in cli.py and the filter no-ops, leaking scaffolding into every fresh
        adopter's first SessionStart digest, while the sibling earn-red test (which hardcodes its
        OWN frozen copy) stays green. This feeds the REAL template through the REAL filter and pins
        the digest to the identity block by exact equality, so a wording drift that moves prose out
        from under a prefix leaks a line in here and reds immediately."""
        from unittest.mock import MagicMock
        from espalier.cli import _build_memory_md
        fp = MagicMock()
        fp.repo_name = "demo-repo"
        fp.languages = ["Python"]
        (tmp_path / "ESPALIER_MEMORY.md").write_text(_build_memory_md(fp), encoding="utf-8")
        mod = self._load_session_start()
        summary = mod._summarize_memory(tmp_path)
        # EXACT identity block -- every Session-Log / Categorized-memory boilerplate line is filtered.
        # Exact-equality is the drift catch: prose that escapes a stale prefix leaks in and breaks this.
        assert summary == "**Repo:** demo-repo | **Stack:** Python", summary

    def test_memory_digest_newest_first(self, tmp_path):
        """The digest selects the newest Session Log rows by DATE, newest-first.

        Seeded DESCENDING and with MORE rows than `_MEMORY_DIGEST_ROWS`, because
        the original fixture was neither and was therefore vacuous. It seeded
        exactly three rows ASCENDING and its docstring called that "non-trivial";
        driven, both the correct and the broken implementation emit the same
        three lines for it -- with exactly N rows a tail-slice is a no-op and the
        reverse accidentally does the right thing. The live artifact is
        newest-FIRST, so the fixture modelled the opposite of the file and the
        guard passed for ~10 days while the banner served the three OLDEST rows.
        """
        mod = self._load_session_start()
        # SHUFFLED on purpose: position and date must disagree in BOTH
        # directions or the fixture cannot tell a date sort from a slice. My
        # first rewrite seeded perfect DESCENDING order, which kills a tail-slice
        # but leaves a plain `rows[:N]` head-slice green -- DEF-587 in mirror
        # image, and measured invisible to all 8236 passing tests. Here the
        # oldest row sits at position 2 and the newest at position 3, so a slice
        # from either end drags `oldest entry` into the digest.
        (tmp_path / "ESPALIER_MEMORY.md").write_text(
            "## Session Log\n"
            "| 2026-06-15 second entry | note |\n"
            "| 2026-06-01 oldest entry | note |\n"
            "| 2026-06-28 newest entry | note |\n"
            "| 2026-06-08 third entry | note |\n",
            encoding="utf-8",
        )
        digest = mod._memory_toc(tmp_path)
        assert "MEMORY (recent sessions" in digest          # self-describing headline label
        assert "headlines only" in digest                    # advertises it is NOT the full row
        assert "/recall" in digest                           # pull pointer for the full reasoning
        assert digest.index("2026-06-28") < digest.index("2026-06-08"), "not newest-first"
        assert "newest entry" in digest
        assert "oldest entry" not in digest, (
            "the oldest row reached a digest headed 'recent sessions' -- this is "
            "the live defect, and a tail-slice reproduces it"
        )

    def test_memory_digest_ignores_a_stray_out_of_order_row(self, tmp_path):
        """An older row appended at the BOTTOM must not enter the digest.

        Models the live artifact exactly: `ESPALIER_MEMORY.md` is newest-first
        for 37 rows and then carries one 2026-08-07 row at the very end, because
        `handoff.md` said "append" while practice prepends. Any position-derived
        selection picks that stray row up; keying on the date cannot.
        """
        mod = self._load_session_start()
        (tmp_path / "ESPALIER_MEMORY.md").write_text(
            "## Session Log\n"
            "| 2026-06-28 newest entry | note |\n"
            "| 2026-06-15 second entry | note |\n"
            "| 2026-06-08 third entry | note |\n"
            "| 2026-06-01 stray appended row | note |\n",
            encoding="utf-8",
        )
        digest = mod._memory_toc(tmp_path)
        assert "stray appended row" not in digest, "a positional slice caught the stray row"
        assert "newest entry" in digest and "second entry" in digest

    def test_memory_digest_ties_break_by_file_position(self, tmp_path):
        """Same-day rows keep FILE order, so the topmost wins under prepend.

        Same-day handoffs are the normal case here (five rows share 2026-08-13
        on the live file), so the tie-break encodes the insertion convention and
        is not an edge case. This is the assertion that dies to a
        `key=(date, index), reverse=True` tuple -- which looks more careful than
        keying on the date alone, and is wrong, because `reverse=True` reverses
        the index too and returns same-day rows oldest-line-first.
        """
        mod = self._load_session_start()
        (tmp_path / "ESPALIER_MEMORY.md").write_text(
            "## Session Log\n"
            "| 2026-06-28 same day first | note |\n"
            "| 2026-06-28 same day second | note |\n"
            "| 2026-06-01 older row | note |\n",
            encoding="utf-8",
        )
        digest = mod._memory_toc(tmp_path)
        assert digest.index("same day first") < digest.index("same day second"), (
            "same-date rows must keep file order (topmost = newest under prepend)"
        )

    def test_memory_digest_survives_a_malformed_date_cell(self, tmp_path):
        """`| 2026-13-45 |` satisfies the date regex; the hook must still render.

        A `date()`/`strptime` sort key raises INSIDE the sort and tracebacks
        SessionStart, whose entire contract is to report and never block. A
        lexicographic compare on the matched string degrades instead: the
        impossible date simply sorts high.
        """
        mod = self._load_session_start()
        (tmp_path / "ESPALIER_MEMORY.md").write_text(
            "## Session Log\n"
            "| 2026-13-45 impossible date | note |\n"
            "| 2026-06-28 real row | note |\n",
            encoding="utf-8",
        )
        digest = mod._memory_toc(tmp_path)
        assert "MEMORY (recent sessions" in digest, "the hook failed to render"
        assert "real row" in digest

    def test_memory_digest_byte_bounded(self, tmp_path):
        """TP-236: a multi-KB Session Log row is clipped to the per-row cap, never
        leaked whole into the banner."""
        mod = self._load_session_start()
        (tmp_path / "ESPALIER_MEMORY.md").write_text(
            "## Session Log\n| 2026-06-28 " + "x" * 3000 + " | note |\n",
            encoding="utf-8",
        )
        digest = mod._memory_toc(tmp_path)
        assert "2026-06-28" in digest
        assert len(digest.encode("utf-8")) < 1000, "multi-KB row leaked past the cap"

    def test_memory_digest_omitted_when_no_rows(self, tmp_path):
        """TP-236: no ESPALIER_MEMORY.md, or a Session Log with no dated rows (adopter
        template / post-archive empty log), yields '' so the section is omitted."""
        mod = self._load_session_start()
        assert mod._memory_toc(tmp_path) == ""                # no ESPALIER_MEMORY.md
        (tmp_path / "ESPALIER_MEMORY.md").write_text(
            "## Session Log\n_Keep only recent rows._\n", encoding="utf-8"
        )
        assert mod._memory_toc(tmp_path) == ""                # no dated rows

    def test_orientation_survives_with_memory_digest(self, tmp_path):
        """TP-236: the worst-case body WITH a MEMORY digest present (TP-236 adds
        bytes to the body, on top of TP-234's worst case) must still keep the
        orientation tail and stay within budget. Seeds a large SHARP_EDGES AND a
        ESPALIER_MEMORY.md with Session Log rows so the digest renders into the body."""
        mod = self._load_session_start()
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "SHARP_EDGES.md").write_text(
            "\n".join(f"## Footgun {i} with a reasonably long heading line" for i in range(400)),
            encoding="utf-8",
        )
        (tmp_path / "ESPALIER_MEMORY.md").write_text(
            "## Session Log\n"
            + "\n".join(f"| 2026-06-{(i % 28) + 1:02d} entry {i} " + "z" * 120 + " | n |" for i in range(40)),
            encoding="utf-8",
        )
        banner = mod._build_context(tmp_path, True, False)
        assert len(banner.encode("utf-8")) <= mod._MAX_CONTEXT_BYTES
        assert "MEMORY (recent sessions" in banner            # digest renders
        assert "first-thoughts" in banner                        # orientation survives
        assert "confirm or redirect" in banner

    def test_surface_degraded_when_missing_files(self, tmp_path):
        """Missing CLAUDE.md and .claude/ → additionalContext shows DEGRADED."""
        result = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "DEGRADED" in self._context(result)

    def test_surface_healthy_when_files_present(self, tmp_path):
        """CLAUDE.md, .claude/settings.json, tools/cc/ present → additionalContext shows healthy."""
        (tmp_path / "CLAUDE.md").write_text("# Project", encoding="utf-8")
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text("{}", encoding="utf-8")
        tools_cc = tmp_path / "tools" / "cc"
        tools_cc.mkdir(parents=True)
        result = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "healthy" in self._context(result)

    def test_repo_name_from_dirname(self, tmp_path):
        """No config files → repo name falls back to directory name."""
        result = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert tmp_path.name in self._context(result)

    def test_warnings_go_to_stderr_not_stdout(self, tmp_path):
        """Non-fatal diagnostics appear on stderr, not mixed into stdout JSON.

        TP-324: a warning is DRIVEN, not assumed. Pre-fix this ran against a
        clean tmp_path that emits no warning at all, so `json.loads(stdout)`
        succeeded no matter where `_hook_utils.warn` printed -- rerouting warn
        to stdout left the test green. A malformed package.json makes
        `repo_name(..., warn_label="session_start")` emit a real
        `[WARN] espalier: session_start: malformed package.json` via warn_exc,
        so the routing itself is now what's under test.

        BOTH emitters are driven, deliberately: `_hook_utils` exposes sister
        functions `warn` and `warn_exc`, and a fixture that trips only one
        leaves the other free to be rerouted to stdout undetected -- the same
        unobserved-effect shape this test is being fixed for.
        """
        # (a) Malformed JSON -> json.JSONDecodeError -> warn_exc on stderr.
        (tmp_path / "package.json").write_text("{not json", encoding="utf-8")
        # (b) ESPALIER_MEMORY.md present but unreadable (a directory) -> _safe_read's
        #     OSError branch -> plain warn() on stderr.
        (tmp_path / "ESPALIER_MEMORY.md").mkdir()
        result = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        # Fixture invariant: both warnings actually fired (otherwise the
        # routing asserts below are vacuous again).
        assert "malformed package.json" in result.stderr, (
            f"fixture invariant: warn_exc path did not fire; {result.stderr!r}"
        )
        assert "could not read ESPALIER_MEMORY.md" in result.stderr, (
            f"fixture invariant: warn path did not fire; {result.stderr!r}"
        )
        # THE named effect: the warning routed to stderr and NOT into stdout.
        assert "[WARN]" not in result.stdout, (
            f"warning text leaked into the stdout JSON channel: {result.stdout!r}"
        )
        # stdout must still be parseable JSON — no stray warning text
        json.loads(result.stdout)

    # ─── TP-71: auto-orient + SHARP_EDGES TOC ──────────────────────────────

    def test_session_start_includes_orientation_instructions(self, tmp_path):
        """The SessionStart context block must carry the orientation
        instructions Claude follows in place of typing /context-load
        at session begin (TP-71)."""
        result = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        ctx = self._context(result)
        assert "Orientation (on first response" in ctx
        assert "first-thoughts" in ctx                       # the first-thoughts open
        assert "confirm or redirect" in ctx               # the proposed-next ending
        assert "ESPALIER_MEMORY.md" in ctx                          # adopter fallback line
        assert "REPO/SURFACE/LAST" not in ctx              # old 6-line report retired

    def test_session_start_includes_footgun_pointer_not_toc(self, tmp_path):
        """The SHARP_EDGES TOC wall is replaced by a one-line /recall pointer
        (self-host). The catalog headings/bodies must NOT be dumped into the
        banner -- pull-on-demand beats a 100-heading wall."""
        _make_self_host_layout(tmp_path)
        sharp_dir = tmp_path / "docs"
        sharp_dir.mkdir()
        (sharp_dir / "SHARP_EDGES.md").write_text(
            "# Title\n"
            "Intro paragraph.\n\n"
            "## First Edge\n\nBody one.\n\n"
            "## Second Edge\n\nBody two.\n",
            encoding="utf-8",
        )
        result = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        ctx = self._context(result)
        assert "FOOTGUNS & FAILURE MODES" in ctx          # the pointer ships
        assert "/recall" in ctx
        assert "SHARP_EDGES.md" in ctx                     # named in the pointer
        assert "--- SHARP_EDGES TOC" not in ctx            # the TOC wall is gone
        assert "## First Edge" not in ctx                  # no heading dump
        assert "Body one" not in ctx                       # no body leak
        assert "[recent:" not in ctx                       # the broken recency mark is gone

    def test_session_start_footgun_pointer_absent_when_catalogs_missing(self, tmp_path):
        """A self-host tree with no footgun docs deployed omits the pointer
        cleanly, and orientation still ships."""
        _make_self_host_layout(tmp_path)
        result = run_hook(
            "session_start.py",
            {"hook_event_name": "SessionStart"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        ctx = self._context(result)
        assert "--- SHARP_EDGES TOC" not in ctx
        assert "Orientation (on first response" in ctx


# ─── post_compact.py ────────────────────────────────────────────────────────


class TestPostCompact:
    def test_always_exits_zero(self, tmp_path):
        """PostCompact hook always exits 0."""
        result = run_hook(
            "post_compact.py",
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0

    def test_read_blueprint_safe_tolerates_non_utf8(self, tmp_path):
        """TP-192 W3-2: a non-UTF-8 / BOM-corrupted latest.json must degrade to
        None, not raise UnicodeDecodeError (a ValueError, not OSError) out of
        ``_read_blueprint_safe`` — which would crash _run_main and drop the whole
        post-compaction re-orientation. Mirror of the TP-174b R22 hardening the
        cognitive_blueprint twin already has."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_tp192_post_compact", HOOKS_DIR / "post_compact.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        # Invalid UTF-8: a UTF-16 BOM + interleaved NULs — read_text(utf-8) raises.
        (bp_dir / "latest.json").write_bytes(b"\xff\xfe{\x00}\x00")
        assert mod._read_blueprint_safe(tmp_path) is None

    def test_banner_format(self, tmp_path):
        """Output contains expected harness banner markers."""
        result = run_hook(
            "post_compact.py",
            {"hook_event_name": "PostCompact"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "POST-COMPACTION CONTEXT" in result.stderr
        assert "Repo:" in result.stderr
        assert "Branch:" in result.stderr
        assert "Surface:" in result.stderr

    def test_output_under_20_lines(self, tmp_path):
        """Output stays under 20 lines."""
        result = run_hook(
            "post_compact.py",
            {"hook_event_name": "PostCompact"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        lines = result.stderr.strip().splitlines()
        assert len(lines) <= 20

    def test_includes_harness_rules(self, tmp_path):
        """Output includes the workflow re-anchor + harness-managed reminder.

        TP-172 3-B re-narrated the prohibition-style ``RULES:`` line into a
        ``RESUME:`` workflow re-anchor (run /status, continue the plan, finish
        via /handoff); the harness-managed reminder is preserved as the tail.
        """
        result = run_hook(
            "post_compact.py",
            {"hook_event_name": "PostCompact"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert "RESUME" in result.stderr
        assert "harness-managed" in result.stderr
        assert "tools/cc/" in result.stderr
        # W6-1: a non-self-host (adopter) repo has no espalier/ source tree;
        # the resume reminder must not name it. tmp_path is not self-host.
        assert "espalier/" not in result.stderr, (
            "post_compact leaked self-host vocab 'espalier/' into a "
            f"non-self-host repo:\n{result.stderr}"
        )


# ─── reflect_trigger.py ─────────────────────────────────────────────────────


class TestReflectTrigger:
    def test_excluded_zone_no_increment(self, tmp_path):
        """Write to espalier/ (excluded zone) → exit 0, no counter change."""
        result = run_hook(
            "reflect_trigger.py",
            {"tool_name": "Write", "tool_input": {"file_path": "espalier/foo.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        counter_file = tmp_path / ".espalier-state" / "write_count"
        assert not counter_file.exists()

    def test_source_write_increments_counter(self, tmp_path):
        """Write to source file → counter increments."""
        run_hook(
            "reflect_trigger.py",
            {"tool_name": "Write", "tool_input": {"file_path": "src/main.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        counter_file = tmp_path / ".espalier-state" / "write_count"
        assert counter_file.exists()
        assert int(counter_file.read_text(encoding="utf-8").strip()) == 1

    def test_tenth_write_triggers_reflect(self, tmp_path):
        """10th source file write → reflect runs (counter at 10)."""
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        (state_dir / "write_count").write_text("9", encoding="utf-8")

        result = run_hook(
            "reflect_trigger.py",
            {"tool_name": "Write", "tool_input": {"file_path": "src/app.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert int((state_dir / "write_count").read_text(encoding="utf-8").strip()) == 10

    def test_counter_file_creation(self, tmp_path):
        """Counter file and state dir are created on first source write."""
        state_dir = tmp_path / ".espalier-state"
        assert not state_dir.exists()

        run_hook(
            "reflect_trigger.py",
            {"tool_name": "Write", "tool_input": {"file_path": "src/test.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )

        assert state_dir.exists()
        assert (state_dir / "write_count").exists()

    def test_config_file_triggers_immediately(self, tmp_path):
        """Write to pyproject.toml triggers reflect regardless of counter.

        TP-324: the reflect invocation is OBSERVED, not inferred. Pre-fix this
        test asserted only rc==0 and an unchanged write_count -- neither depends
        on whether ``_run_reflect`` fired, so deleting the ``_run_reflect(root)``
        call from reflect_trigger's config branch left it green. A stub
        ``tools/cc/reflect_protocol.py`` drops a marker when spawned, so the
        marker's existence IS the named effect.
        """
        # Counter at 1 (not a multiple of 10), so the source-write path cannot
        # fire -- a marker can only come from the config branch.
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        (state_dir / "write_count").write_text("1", encoding="utf-8")

        # _run_reflect spawns `tools/cc/reflect_protocol.py --pass 1 --json`
        # with cwd=root and CLAUDE_PROJECT_DIR pinned to root. Empty stdout
        # makes it return early, so the marker is the whole observable.
        marker = tmp_path / "reflect_ran.marker"
        tools_dir = tmp_path / "tools" / "cc"
        tools_dir.mkdir(parents=True)
        (tools_dir / "reflect_protocol.py").write_text(
            "import pathlib, os\n"
            "pathlib.Path(os.environ['CLAUDE_PROJECT_DIR'],"
            " 'reflect_ran.marker').write_text('fired')\n",
            encoding="utf-8",
        )
        assert not marker.exists(), "fixture invariant: marker must start absent"

        result = run_hook(
            "reflect_trigger.py",
            {"tool_name": "Write", "tool_input": {"file_path": "pyproject.toml"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        # THE named effect: the config write ran reflect immediately.
        assert marker.exists(), (
            "config-file write must trigger reflect immediately; the "
            "reflect_protocol stub was never spawned. "
            f"stderr={result.stderr!r}"
        )
        # Config files don't increment the source counter
        assert int((state_dir / "write_count").read_text(encoding="utf-8").strip()) == 1

    def test_non_write_tool_ignored(self, tmp_path):
        """Read tool → exit 0, no counter."""
        result = run_hook(
            "reflect_trigger.py",
            {"tool_name": "Read", "tool_input": {"file_path": "src/main.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert not (tmp_path / ".espalier-state" / "write_count").exists()

    def test_tests_dir_excluded(self, tmp_path):
        """Write to tests/ → not counted as source file."""
        run_hook(
            "reflect_trigger.py",
            {"tool_name": "Write", "tool_input": {"file_path": "tests/test_foo.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        counter_file = tmp_path / ".espalier-state" / "write_count"
        assert not counter_file.exists()

    def test_reflect_trigger_records_to_blueprint(self, tmp_path):
        """10th write triggers reflect which records pass into blueprint."""
        tools_dir = tmp_path / "tools" / "cc"
        tools_dir.mkdir(parents=True)
        shutil.copy("tools/cc/cognitive_blueprint.py", tools_dir)
        shutil.copy("tools/cc/_blueprint_limits.py", tools_dir)
        shutil.copy("tools/cc/_json_safe.py", tools_dir)  # TP-169 §13 #7 dep
        shutil.copy("tools/cc/_paths.py", tools_dir)  # _repo_root canon dep
        shutil.copy("tools/cc/reflect_protocol.py", tools_dir)
        (tmp_path / "cc" / "blueprints").mkdir(parents=True)
        # Pre-start a blueprint. CLAUDE_PROJECT_DIR is set explicitly:
        # cognitive_blueprint._repo_root() prefers the env var over cwd,
        # so a leaked CLAUDE_PROJECT_DIR from the parent shell would
        # cause `start` to write into the real repo, leaving tmp_path
        # empty and tripping the latest.json assertion below.
        subprocess.run(
            [sys.executable, str(tools_dir / "cognitive_blueprint.py"), "start"],
            cwd=tmp_path, capture_output=True,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        # Set counter to 9 so the next write triggers reflect
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        (state_dir / "write_count").write_text("9", encoding="utf-8")

        result = run_hook(
            "reflect_trigger.py",
            {"tool_name": "Write", "tool_input": {"file_path": "src/app.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        # Blueprint should have at least one reflect pass recorded
        import json as _json
        bp = _json.loads((tmp_path / "cc" / "blueprints" / "latest.json").read_text(encoding="utf-8"))
        assert len(bp["reflect_passes"]) == 1
        assert "gap_count" in bp["reflect_passes"][0]


# ─── TP-142 (FM-4 §1.9 + §5.6): missing reflect-pipeline scripts ──────


class TestReflectTriggerMissingScripts:
    """FM-4 close: missing reflect_protocol.py / cognitive_blueprint.py
    must emit one-shot stderr WARN per session.

    Pre-fix the trigger silently no-oped when either script was absent;
    operator never learned drift-detection had gone dark. The one-shot
    flag is at .espalier-state/reflect_trigger_warned and is cleared
    by session_start._clean_state_flags every SessionStart so the WARN
    re-fires once per session.
    """

    def _trigger_tenth_write(self, tmp_path):
        """Pre-stage write_count=9 so the next Write fires _run_reflect."""
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "write_count").write_text("9", encoding="utf-8")
        return run_hook(
            "reflect_trigger.py",
            {"tool_name": "Write", "tool_input": {"file_path": "src/app.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )

    def test_warns_once_when_reflect_script_missing(self, tmp_path):
        """tmp_path has no tools/cc/reflect_protocol.py → WARN emits the
        first time and the flag is created. Second 10th-write trigger
        in the same session is silent."""
        result = self._trigger_tenth_write(tmp_path)
        assert result.returncode == 0
        assert "reflect_protocol.py not found" in result.stderr, (
            f"expected reflect-script WARN; got stderr={result.stderr!r}"
        )
        assert "drift detection" in result.stderr
        assert "DISABLED" in result.stderr
        flag = tmp_path / ".espalier-state" / "reflect_trigger_warned"
        assert flag.exists(), "flag file must be created to suppress repeats"

        # Re-stage counter at 9 and trigger again — flag suppresses the WARN.
        (tmp_path / ".espalier-state" / "write_count").write_text("9", encoding="utf-8")
        result2 = run_hook(
            "reflect_trigger.py",
            {"tool_name": "Write", "tool_input": {"file_path": "src/two.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result2.returncode == 0
        assert "reflect_protocol.py not found" not in result2.stderr, (
            f"WARN must be suppressed by flag on second fire; "
            f"stderr={result2.stderr!r}"
        )

    def test_warns_when_blueprint_script_missing(self, tmp_path):
        """tmp_path has reflect_protocol.py BUT NOT cognitive_blueprint.py;
        the blueprint-write else-branch must WARN with the blueprint
        path named."""
        # Stub reflect_protocol.py — prints valid empty JSON report
        # (so _run_reflect parses it cleanly and reaches the
        # blueprint_script.exists() branch).
        tools_dir = tmp_path / "tools" / "cc"
        tools_dir.mkdir(parents=True, exist_ok=True)
        stub = tools_dir / "reflect_protocol.py"
        stub.write_text(
            '#!/usr/bin/env python3\n'
            'import json, sys\n'
            'print(json.dumps({"findings": [], "gap_count": 0, '
            '"orphan_count": 0, "files_analyzed": 0}))\n'
            'sys.exit(0)\n',
            encoding="utf-8",
        )

        result = self._trigger_tenth_write(tmp_path)
        assert result.returncode == 0
        # Reflect's own clean summary should fire.
        assert "[reflect] clean" in result.stderr or "REFLECT TRIGGER" in result.stderr
        # And the blueprint-script WARN must surface.
        assert "cognitive_blueprint.py not found" in result.stderr, (
            f"expected blueprint-script WARN; got stderr={result.stderr!r}"
        )


# ─── blueprint auto-lifecycle ────────────────────────────────────────────────


class TestBlueprintAutoLifecycle:
    """Verify hooks auto-manage blueprint sessions."""

    def test_session_start_auto_creates_blueprint(self, tmp_path):
        """SessionStart creates a blueprint if none exists."""
        tools_dir = tmp_path / "tools" / "cc"
        tools_dir.mkdir(parents=True)
        shutil.copy("tools/cc/cognitive_blueprint.py", tools_dir)
        shutil.copy("tools/cc/_blueprint_limits.py", tools_dir)
        shutil.copy("tools/cc/_json_safe.py", tools_dir)  # TP-169 §13 #7 dep
        shutil.copy("tools/cc/_paths.py", tools_dir)  # _repo_root canon dep
        (tmp_path / "CLAUDE.md").write_text("# Test\n", encoding="utf-8")
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        (tmp_path / "cc" / "blueprints").mkdir(parents=True)

        result = run_hook(
            "session_start.py",
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "Auto-started" in ctx
        assert (tmp_path / "cc" / "blueprints" / "latest.json").exists()

    def test_stop_gate_auto_finalizes_blueprint(self, tmp_path):
        """Stop gate auto-finalizes blueprint instead of blocking.

        TP-324: the finalize is OBSERVED. Pre-fix the sole assert was rc==0 --
        but Gate 4 is silent and always-passes, so `return`-ing out of
        `_gate_finalize_blueprint` left the hook at rc 0 and this test green
        while no blueprint was ever finalized. `cognitive_blueprint finalize`
        derives `continuation_fragments` from the recorded reasoning entries,
        so the "[decision] test decision" fragment appearing in latest.json is
        a state only the finalize call can produce.
        """
        tools_dir = tmp_path / "tools" / "cc"
        tools_dir.mkdir(parents=True)
        shutil.copy("tools/cc/cognitive_blueprint.py", tools_dir)
        shutil.copy("tools/cc/_blueprint_limits.py", tools_dir)
        shutil.copy("tools/cc/_json_safe.py", tools_dir)  # TP-169 §13 #7 dep
        shutil.copy("tools/cc/_paths.py", tools_dir)  # _repo_root canon dep
        (tmp_path / "cc" / "blueprints").mkdir(parents=True)

        # Init git repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        git_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        (tmp_path / "README.md").write_text("init\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path, capture_output=True, env=git_env,
        )

        # Start a blueprint, record an entry, then commit. CLAUDE_PROJECT_DIR
        # is pinned explicitly so this test stays isolated under any CC
        # session (which always exports the var to the real repo root).
        # See docs/SHARP_EDGES.md "Subprocesses Inheriting CLAUDE_PROJECT_DIR".
        bp_env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
        subprocess.run(
            [sys.executable, str(tools_dir / "cognitive_blueprint.py"), "start"],
            cwd=tmp_path, capture_output=True, env=bp_env,
        )
        subprocess.run(
            [sys.executable, str(tools_dir / "cognitive_blueprint.py"),
             "record", "--kind", "decision", "--description", "test decision"],
            cwd=tmp_path, capture_output=True, env=bp_env,
        )
        subprocess.run(["git", "add", "cc/blueprints/"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "blueprint"],
            cwd=tmp_path, capture_output=True, env=git_env,
        )

        # Make an uncommitted change — stop gate should auto-finalize
        (tmp_path / "bar.py").write_text("y = 2\n", encoding="utf-8")

        # Fixture invariant: pre-hook, finalize has not run, so the derived
        # continuation_fragments are still empty. Without this the post-hook
        # assert could pass on a state that predates the hook.
        latest = tmp_path / "cc" / "blueprints" / "latest.json"
        assert json.loads(latest.read_text(encoding="utf-8")).get(
            "continuation_fragments"
        ) in (None, []), "fixture invariant: blueprint must start un-finalized"

        result = run_hook(
            "stop_gate.py",
            {},
            # Delete the two harness vars the operator's shell may export
            # (docs/SHARP_EDGES.md "ESPALIER_STOP_GATE=full Exported in Shell
            # RC"): ESPALIER_STOP_GATE=full would run Gate 1's pytest inside
            # this subprocess, and MAINTENANCE_MODE changes which gates run.
            # Gate 4 fires under every mode; pinning them keeps the RED honest.
            {
                "CLAUDE_PROJECT_DIR": str(tmp_path),
                "ESPALIER_STOP_GATE": None,
                "ESPALIER_MAINTENANCE_MODE": None,
            },
        )
        # Should allow (exit 0) because auto-finalize modified the blueprint
        assert result.returncode == 0
        # ...and NOT via a block decision on the structured channel.
        if result.stdout.strip():
            assert json.loads(result.stdout).get("decision") != "block", (
                f"stop_gate must allow here, not block: {result.stdout!r}"
            )
        # THE named effect: Gate 4 ran cognitive_blueprint finalize, which
        # derives continuation_fragments from the recorded decision entries.
        blueprint = json.loads(latest.read_text(encoding="utf-8"))
        assert "[decision] test decision" in blueprint.get(
            "continuation_fragments", []
        ), (
            "Gate 4 did not finalize the blueprint; continuation_fragments="
            f"{blueprint.get('continuation_fragments')!r} stderr={result.stderr!r}"
        )


# ─── task_router.py ─────────────────────────────────────────────────────────


class TestTaskRouter:
    def test_multi_step_prompt_injects_guidance(self, tmp_path):
        """Prompt with 'refactor' → stdout contains routing guidance with /implement-task --multi."""
        result = run_hook(
            "task_router.py",
            {"prompt": "refactor the auth module to use JWT tokens"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "HARNESS" in result.stdout
        assert "/implement-task --multi" in result.stdout

    def test_multi_step_prompt_does_not_present_accomplish_as_primary(self, tmp_path):
        """Router output must not advertise /accomplish as the primary command."""
        result = run_hook(
            "task_router.py",
            {"prompt": "implement the new payment integration"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "Use /accomplish to create" not in result.stdout

    def test_quick_fix_prompt_no_injection(self, tmp_path):
        """Prompt with 'fix this typo' → no stdout."""
        result = run_hook(
            "task_router.py",
            {"prompt": "fix the typo in README"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_question_prompt_no_injection(self, tmp_path):
        """Question prompt → no stdout."""
        result = run_hook(
            "task_router.py",
            {"prompt": "what does the write_guard do"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_empty_prompt_no_injection(self, tmp_path):
        """Empty prompt → no stdout, exit 0."""
        result = run_hook(
            "task_router.py",
            {"prompt": ""},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_malformed_stdin_exits_zero(self, tmp_path):
        """Invalid JSON on stdin → exit 0, never crash."""
        script = HOOKS_DIR / "task_router.py"
        import subprocess as _sub
        result = _sub.run(
            [sys.executable, str(script)],
            input="not valid json {{{",
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
        assert result.returncode == 0


# ─── TP-125: decision-shape advisory ────────────────────────────────────────

import importlib.util as _importlib_util  # noqa: E402


def _load_task_router_module():
    """Import tools/cc/hooks/task_router.py directly so we can test its
    module-level regex set and helpers without spawning a subprocess.

    Sister-shape to test_cognitive_blueprint::_load_hookside_module — same
    importlib.util.spec_from_file_location pattern.
    """
    path = HOOKS_DIR / "task_router.py"
    spec = _importlib_util.spec_from_file_location("_task_router_mod", path)
    mod = _importlib_util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # Py 3.14 dataclass+exec_module safety
    spec.loader.exec_module(mod)
    return mod


def _write_blueprint_with_decisions(tmp_path: Path, n_decisions: int,
                                    extra_kinds: list[str] | None = None) -> Path:
    bp_dir = tmp_path / "cc" / "blueprints"
    bp_dir.mkdir(parents=True, exist_ok=True)
    entries = [
        {"kind": "decision", "description": f"d{i}", "timestamp": f"t{i}"}
        for i in range(n_decisions)
    ]
    for k in extra_kinds or []:
        entries.append({"kind": k, "description": f"x-{k}", "timestamp": "tx"})
    bp = {"session_id": "test-tp125", "reasoning_entries": entries}
    path = bp_dir / "latest.json"
    path.write_text(json.dumps(bp, indent=2) + "\n", encoding="utf-8")
    return path


class TestDecisionShapeDetector:
    """TP-125: the _DECISION_SHAPE_PATTERNS regex set against representative
    prompt phrasings. Regex behavior — no subprocess, no blueprint."""

    @pytest.mark.parametrize("prompt", [
        "should I refactor this module?",
        "should we use postgres or sqlite here?",
        "let's choose between option A and option B",
        "we need to decide on the auth strategy",
        "this is a deciding moment",
        "the decision was already made",
        "what about using a queue instead?",
        "we should reconsider that approach",
        "let's switch to a different library",
        "it'd be better to use uv here",
        "tabs vs spaces",
        "actor model vs CSP",  # X vs Y shape
    ])
    def test_matches_decision_shape(self, prompt):
        mod = _load_task_router_module()
        assert any(p.search(prompt) for p in mod._DECISION_SHAPE_PATTERNS), (
            f"expected decision-shape match for: {prompt!r}"
        )

    @pytest.mark.parametrize("prompt", [
        "what does foo.py do?",
        "run the tests please",
        "fix the typo in README",
        "list all files in tools/cc/hooks/",
        "explain the write_guard semantics",
    ])
    def test_does_not_match_non_decision_shape(self, prompt):
        mod = _load_task_router_module()
        assert not any(p.search(prompt) for p in mod._DECISION_SHAPE_PATTERNS), (
            f"expected NO decision-shape match for: {prompt!r}"
        )

    def test_pattern_set_size_floor(self):
        """At least 8 distinct shapes covered — pack permits additions but
        the floor protects against silent removal during refactors."""
        mod = _load_task_router_module()
        assert len(mod._DECISION_SHAPE_PATTERNS) >= 8


class TestAdvisoryGating:
    """TP-125 two-condition gate, end-to-end via subprocess. Both conditions
    must hold for the advisory to fire; if either is absent, stdout stays
    silent (no advisory text)."""

    _ADVISORY_NEEDLE = "Decision-shape prompt detected"

    def test_fires_when_both_conditions_met(self, tmp_path):
        _write_blueprint_with_decisions(tmp_path, n_decisions=2)
        result = run_hook(
            "task_router.py",
            {"prompt": "should we use X or Y here?"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert self._ADVISORY_NEEDLE in result.stdout

    def test_silent_when_no_decisions_recorded(self, tmp_path):
        """LOAD-BEARING GATE. If this fails, the advisory channel
        degrades to noise — firing on every decision-shape prompt
        regardless of whether there's anything to surface.

        Sister-shape: TestDecisionShapeDetector tests the regex in
        isolation; this one tests the count-gate composition.
        """
        # Fixture has 0 decisions but a non-decision entry — count-gate
        # must still hold the advisory silent.
        _write_blueprint_with_decisions(
            tmp_path, n_decisions=0, extra_kinds=["pattern_discovered"]
        )
        result = run_hook(
            "task_router.py",
            {"prompt": "should we use X or Y here?"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert self._ADVISORY_NEEDLE not in result.stdout

    def test_silent_when_no_blueprint_at_all(self, tmp_path):
        # No cc/blueprints/latest.json — count helper returns 0; advisory
        # must stay silent. Distinct from "blueprint with no decisions"
        # — both should silence the advisory.
        result = run_hook(
            "task_router.py",
            {"prompt": "should we use X or Y here?"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert self._ADVISORY_NEEDLE not in result.stdout

    def test_silent_when_prompt_not_decision_shape(self, tmp_path):
        _write_blueprint_with_decisions(tmp_path, n_decisions=3)
        result = run_hook(
            "task_router.py",
            {"prompt": "what does foo.py do?"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert self._ADVISORY_NEEDLE not in result.stdout

    def test_count_in_advisory_matches_blueprint(self, tmp_path):
        _write_blueprint_with_decisions(tmp_path, n_decisions=3)
        result = run_hook(
            "task_router.py",
            {"prompt": "should we switch to a different approach?"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        # Literal "3 prior decision" substring — pluralized.
        assert "3 prior decisions" in result.stdout

    def test_singular_when_one_decision(self, tmp_path):
        _write_blueprint_with_decisions(tmp_path, n_decisions=1)
        result = run_hook(
            "task_router.py",
            {"prompt": "should we use X or Y here?"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        # Singular: "1 prior decision" (no trailing s)
        assert "1 prior decision " in result.stdout or "1 prior decision\n" in result.stdout
        assert "1 prior decisions" not in result.stdout


class TestAdvisoryIntegration:
    """TP-125 full subprocess + plain-text stdout channel contract.

    Pins the channel-XOR rule incidentally: UserPromptSubmit's advisory
    rides plain-text stdout (the same channel as ROUTING_GUIDANCE), never
    JSON. If a refactor tries to "promote" the advisory to a JSON envelope,
    json.loads(result.stdout) would succeed but consumers (Claude Code's
    additional-context injection per docs/external/cc-hook-protocol.md)
    would no longer see the advisory text.
    """

    def test_full_subprocess_run_emits_plain_text(self, tmp_path):
        _write_blueprint_with_decisions(tmp_path, n_decisions=2)
        result = run_hook(
            "task_router.py",
            {"prompt": "should we reconsider approach X?"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        # Plain text — substring match, NOT json.loads.
        assert "Decision-shape prompt detected" in result.stdout
        assert "show-recent --n 5 --kind decision" in result.stdout
        # Verify it is NOT a JSON envelope: stdout should not start with `{`.
        assert not result.stdout.lstrip().startswith("{")

    def test_advisory_composes_with_routing_guidance(self, tmp_path):
        """When the prompt is both multi-step (refactor/build/etc.) AND
        decision-shape, both messages print — separated by blank line."""
        _write_blueprint_with_decisions(tmp_path, n_decisions=1)
        result = run_hook(
            "task_router.py",
            {"prompt": "should we refactor the auth module to use JWT?"},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "HARNESS" in result.stdout  # ROUTING_GUIDANCE marker
        assert "Decision-shape prompt detected" in result.stdout
        # ROUTING_GUIDANCE prints first per main()'s ordering.
        assert result.stdout.index("HARNESS") < result.stdout.index(
            "Decision-shape prompt detected"
        )


class TestMemorySlugExists:
    """TP-125 + TP-88: the mid-session continuity protocol must be present
    in memory/ with the canonical headers, so the CLAUDE.md pointer
    resolves to a real document and the protocol body is part of the
    repo."""

    def test_protocol_doc_present(self):
        repo_root = Path(__file__).resolve().parent.parent
        path = repo_root / "memory" / "mid-session-continuity-protocol.md"
        assert path.is_file(), f"memory slug missing: {path}"
        body = path.read_text(encoding="utf-8")
        assert "**Status:** active" in body
        assert "**Linked from:**" in body
        assert "## When the advisory fires" in body


class TestCLAUDEMDPointer:
    """TP-125 + TP-89 folder-router pattern: CLAUDE.md must contain a
    substring path-reference to the memory slug so Claude pulls it into
    context on demand."""

    def test_pointer_to_memory_slug(self):
        repo_root = Path(__file__).resolve().parent.parent
        body = (repo_root / "CLAUDE.md").read_text(encoding="utf-8")
        assert "memory/mid-session-continuity-protocol.md" in body


# ─── plan_guard.py ──────────────────────────────────────────────────────────


class TestPlanGuard:
    def _write_plan(self, tmp_path, status="in_progress"):
        cc_dir = tmp_path / "cc"
        cc_dir.mkdir(exist_ok=True)
        plan = {"task": "test", "status": status, "steps": [{"description": "test step"}]}
        (cc_dir / "execution_plan.json").write_text(json.dumps(plan), encoding="utf-8")

    def test_allows_read_tools(self, tmp_path):
        """Read, Glob, Grep → exit 0 (not mutation tools)."""
        for tool in ("Read", "Glob", "Grep"):
            result = run_hook(
                "plan_guard.py",
                {"tool_name": tool, "tool_input": {"file_path": "src/app.py"}},
                {"CLAUDE_PROJECT_DIR": str(tmp_path)},
            )
            assert_hook_allowed(result)

    def test_blocks_source_write_no_plan(self, tmp_path):
        """Write to src/app.py with no execution_plan.json → exit 2."""
        result = run_hook(
            "plan_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "src/app.py", "content": "x"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_allows_source_write_with_plan(self, tmp_path):
        """Write to src/app.py with valid execution_plan.json → exit 0."""
        self._write_plan(tmp_path)
        result = run_hook(
            "plan_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "src/app.py", "content": "x"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert_hook_allowed(result)

    def test_allows_test_write_no_plan(self, tmp_path):
        """Write to tests/test_foo.py → exit 0 (exempt)."""
        result = run_hook(
            "plan_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "tests/test_foo.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert_hook_allowed(result)

    def test_allows_doc_write_no_plan(self, tmp_path):
        """Write to ESPALIER_MEMORY.md → exit 0 (root-level, exempt)."""
        result = run_hook(
            "plan_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "ESPALIER_MEMORY.md"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert_hook_allowed(result)

    def test_blocks_notebook_edit_source_no_plan(self, tmp_path):
        """NotebookEdit carries its target as `notebook_path` (CC Agent SDK
        reference), not `file_path`; a source-tree notebook edit with no plan
        must still be plan-gated. Pre-fix the file_path-only read skipped every
        NotebookEdit (TP-169 A4 re-attack sibling)."""
        result = run_hook(
            "plan_guard.py",
            {"tool_name": "NotebookEdit",
             "tool_input": {"notebook_path": "src/app.ipynb", "new_source": "x"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_allows_notebook_edit_source_with_plan(self, tmp_path):
        """With an ACTIVE plan (status=in_progress + non-empty steps), the
        NotebookEdit notebook_path source edit is allowed -- it routes through
        the same _check_path as Write, so the fix doesn't over-block. (A
        steps:[] plan is 'no-steps' -> inactive, so write an active one here.)"""
        cc = tmp_path / "cc"
        cc.mkdir(exist_ok=True)
        (cc / "execution_plan.json").write_text(json.dumps(
            {"task": "t", "status": "in_progress",
             "steps": [{"description": "s1", "status": "in_progress"}]}), encoding="utf-8")
        result = run_hook(
            "plan_guard.py",
            {"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "src/app.ipynb"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        if result.stdout.strip():
            out = json.loads(result.stdout)
            assert out.get("hookSpecificOutput", {}).get("permissionDecision") != "deny", out

    def test_allows_harness_write_no_plan(self, tmp_path):
        """Write to tools/cc/hooks/foo.py → exit 0 (harness zone, exempt)."""
        result = run_hook(
            "plan_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "tools/cc/hooks/foo.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert_hook_allowed(result)

    def test_allows_readonly_bash_no_plan(self, tmp_path):
        """Bash grep command → exit 0 (read-only)."""
        result = run_hook(
            "plan_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "grep -rn foo src/"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert_hook_allowed(result)

    def test_blocks_mcp_tool_no_plan(self, tmp_path):
        """``mcp__fs__write_file`` to a source path with no active plan must
        emit a deny JSON. R11 B3: pre-fix this test asserted only
        ``returncode == 0`` which is always true (decision is in JSON),
        so a regression to "always allow" would not have been caught.
        """
        result = run_hook(
            "plan_guard.py",
            {"tool_name": "mcp__fs__write_file", "tool_input": {"path": "src/app.py", "content": "x"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny", (
            f"plan_guard must deny MCP write tool when no plan is active. "
            f"Got: {output}"
        )

    @pytest.mark.parametrize("tool_input", [
        {"files": [{"path": "src/app.py", "content": "x"}]},          # N6 one-level
        {"batch": {"files": [{"path": "src/app.py"}]}},               # M1 two-level
        {"edits": [{"file": {"file_path": "src/app.py"}}]},           # M1 deep, file_path key
    ])
    def test_blocks_nested_mcp_write_no_plan(self, tmp_path, tool_input):
        """TP-169 Class-A2: a plan-gated source write NESTED in the MCP payload
        must require a plan. Pre-fix plan_guard read only the first top-level
        MCP_PATH_FIELDS value, so every nested shape here ALLOWED with no plan
        (earn-the-red). MAINTENANCE popped so the plan check runs."""
        result = run_hook(
            "plan_guard.py",
            {"tool_name": "mcp__fs__write_file", "tool_input": tool_input},
            {"CLAUDE_PROJECT_DIR": str(tmp_path), "ESPALIER_MAINTENANCE_MODE": None},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny", (
            f"plan_guard must deny a nested MCP source write with no plan. Got: {output}"
        )

    def test_nested_mcp_non_path_key_does_not_require_plan(self, tmp_path):
        """plan_guard gates only on path-shaped governing keys, so a prose
        field carrying a path-like string (key not in MCP_PATH_FIELDS) must NOT
        spuriously demand a plan (avoids the over-fire a key-agnostic walk would
        cause for plan_guard's broad 'any non-exempt path' predicate)."""
        result = run_hook(
            "plan_guard.py",
            {"tool_name": "mcp__fs__write_file",
             "tool_input": {"description": "refactor src/app.py and tests/foo.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path), "ESPALIER_MAINTENANCE_MODE": None},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "", (
            f"plan_guard must not demand a plan for a non-path-key prose field. "
            f"Got stdout: {result.stdout!r}"
        )

    @requires_symlink
    def test_symlinked_plan_does_not_open_mutation_gate(self, tmp_path):
        """TP-169 N3 (Class-A3, FREEZE-BLOCKER): a forged SYMLINK at
        cc/execution_plan.json pointing at attacker JSON (status=in_progress)
        must NOT open the PreToolUse mutation gate. _plan_state_label reads with
        O_NOFOLLOW, so a symlinked plan is refused -> gate stays CLOSED ->
        the unplanned source write is DENIED (require a plan)."""
        (tmp_path / "cc").mkdir()
        evil = tmp_path / "evil_plan.json"
        evil.write_text('{"status":"in_progress","steps":[1]}', encoding="utf-8")
        (tmp_path / "cc" / "execution_plan.json").symlink_to(evil)
        result = run_hook(
            "plan_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "src/app.py", "content": "x"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path), "ESPALIER_MAINTENANCE_MODE": None},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny", (
            f"a symlinked plan must not open the mutation gate. Got: {output}"
        )

    @requires_symlink
    def test_symlinked_plan_parent_dir_does_not_open_gate(self, tmp_path):
        """TP-169 N3-EXT: O_NOFOLLOW guards only the FINAL component, so a
        symlinked cc/ PARENT directory (cc -> attacker dir holding an
        in_progress plan) would still be followed. read_text_nofollow(within=
        root) refuses a symlinked ancestor -> gate stays CLOSED."""
        realcc = tmp_path / "realcc"
        realcc.mkdir()
        (realcc / "execution_plan.json").write_text(
            '{"status":"in_progress","steps":[1]}', encoding="utf-8")
        (tmp_path / "cc").symlink_to(realcc, target_is_directory=True)
        result = run_hook(
            "plan_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "src/app.py", "content": "x"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path), "ESPALIER_MAINTENANCE_MODE": None},
        )
        assert result.returncode == 0
        assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny", (
            f"a symlinked cc/ parent must not open the mutation gate. Got: {result.stdout!r}"
        )

    def test_two_plan_gated_leaves_emit_single_decision(self, tmp_path):
        """TP-169 169-T: an MCP payload with TWO plan-gated leaves and no active
        plan must emit exactly ONE deny JSON. Pre-fix deny() returned a falsy 0
        so the per-leaf ``if rc: return rc`` did not short-circuit and a second
        leaf double-printed a second decision (channel-XOR corruption)."""
        result = run_hook(
            "plan_guard.py",
            {"tool_name": "mcp__fs__write_file",
             "tool_input": {"files": [{"path": "src/a.py"}, {"path": "lib/b.py"}]}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path), "ESPALIER_MAINTENANCE_MODE": None},
        )
        assert result.returncode == 0
        decisions = [ln for ln in result.stdout.splitlines() if ln.strip()]
        assert len(decisions) == 1, (
            f"expected exactly one decision JSON, got {len(decisions)}: {result.stdout!r}"
        )
        assert json.loads(decisions[0])["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_real_in_progress_plan_still_opens_gate(self, tmp_path):
        """N3 negative: a REAL (non-symlink) in_progress plan must still allow
        source writes (no over-block regression from the O_NOFOLLOW read)."""
        (tmp_path / "cc").mkdir()
        (tmp_path / "cc" / "execution_plan.json").write_text(
            '{"status":"in_progress","steps":[1]}', encoding="utf-8")
        result = run_hook(
            "plan_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "src/app.py", "content": "x"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path), "ESPALIER_MAINTENANCE_MODE": None},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "", (
            f"a real in_progress plan must allow the write. Got: {result.stdout!r}"
        )

    def test_malformed_stdin_exits_zero(self, tmp_path):
        """Invalid JSON → exit 0, never crash."""
        script = HOOKS_DIR / "plan_guard.py"
        import subprocess as _sub
        result = _sub.run(
            [sys.executable, str(script)],
            input="{{broken",
            capture_output=True, text=True, encoding="utf-8", timeout=5,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0

    @pytest.mark.parametrize("traversal_path", [
        "tests/../src/app.py",
        "tools/cc/../../src/app.py",
        "./tests/../src/app.py",
    ])
    def test_traversal_through_exempt_prefix_blocked(self, tmp_path, traversal_path):
        """`tests/../src/app.py` must canonicalize to `src/app.py` and require
        a plan. Without `..` resolution the path appeared to start with `tests/`
        and was wrongly exempted."""
        result = run_hook(
            "plan_guard.py",
            {"tool_name": "Write", "tool_input": {
                "file_path": traversal_path, "content": "x"
            }},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


# ─── write_guard.py v3 additions ────────────────────────────────────────────


class TestWriteGuardV3:
    def test_denies_protected_write(self, tmp_path):
        """Write to espalier/foo.py → DENY on self-host repo (TP-13 13-A; TP-76 5-signal)."""
        _make_self_host_layout(tmp_path)
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "espalier/foo.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_allows_blueprint_write(self, tmp_path):
        """Write to cc/blueprints/123.json → exit 0 (allowlisted)."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "cc/blueprints/123.json"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert_hook_allowed(result)

    def test_allows_execution_plan(self, tmp_path):
        """Write to cc/execution_plan.json → exit 0 (allowlisted)."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "cc/execution_plan.json"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert_hook_allowed(result)

    def test_allows_non_protected_write(self, tmp_path):
        """Write to src/app.py → exit 0."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Write", "tool_input": {"file_path": "src/app.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert_hook_allowed(result)

    def test_ignores_read_tools(self, tmp_path):
        """Read, Glob, Grep → exit 0 (not mutation tools)."""
        for tool in ("Read", "Glob", "Grep"):
            result = run_hook(
                "write_guard.py",
                {"tool_name": tool, "tool_input": {"file_path": "espalier/foo.py"}},
                {"CLAUDE_PROJECT_DIR": str(tmp_path)},
            )
            assert result.returncode == 0, f"{tool} should pass"

    def test_blocks_notebook_edit_protected(self, tmp_path):
        """``NotebookEdit`` on a universally-protected path must emit a
        deny JSON. R11 B3 fixup: pre-fix the assertion only checked
        ``returncode == 0`` (always true) AND used ``espalier/notebook.ipynb``
        which is only protected on self-host repos — the test would
        false-pass in either dimension. Switched to ``tools/cc/`` which is
        in ``PROTECTED_PREFIXES`` for every repo.
        """
        result = run_hook(
            "write_guard.py",
            {"tool_name": "NotebookEdit", "tool_input": {"file_path": "tools/cc/hooks/notebook.ipynb"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_blocks_powershell_rm(self, tmp_path):
        """PowerShell Remove-Item -Recurse -Force → DENY (exit 0 + JSON).

        Denies via the PreToolUse structured channel, NOT exit 2. The prior
        ``returncode == 0``-only assertion was vacuous and the "exit 2"
        docstring was wrong; assert the decision via assert_hook_denied (C-5)."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "PowerShell", "tool_input": {"command": "Remove-Item -Recurse -Force /"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert_hook_denied(result, contains_reason="Remove-Item")

    def test_blocks_mcp_write_to_protected(self, tmp_path):
        """An MCP tool writing to a protected harness path must emit a deny
        JSON. R11 B3: pre-fix this asserted only ``returncode == 0`` which
        is always true regardless of decision; vacuous coverage of the
        MCP protected-zone branch.
        """
        result = run_hook(
            "write_guard.py",
            {"tool_name": "mcp__filesystem__write_file", "tool_input": {"path": "tools/cc/hooks/write_guard.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny", (
            f"write_guard must deny MCP write to protected zone. Got: {output}"
        )
        # The MCP-branch deny reason names the tool + field for diagnostics.
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        assert "tools/cc/hooks/write_guard.py" in reason

    def test_blocks_mcp_move_via_destination_field(self, tmp_path):
        """R11 W: MCP move/rename via ``destination`` field must also fire.
        Pre-fix, write_guard checked only ``path`` and ``file_path``, so a
        ``mcp__filesystem__move_file`` with source/destination args bypassed
        the protected-zone check entirely.
        """
        result = run_hook(
            "write_guard.py",
            {
                "tool_name": "mcp__filesystem__move_file",
                "tool_input": {
                    "source": "/tmp/whatever",
                    "destination": "tools/cc/hooks/write_guard.py",
                },
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "destination" in output["hookSpecificOutput"]["permissionDecisionReason"]

    def test_allows_mcp_read_without_plan(self, tmp_path):
        """R11 B4: pure-read MCP tools must NOT be denied when no plan is
        active. Pre-fix, plan_guard treated every mcp__ tool name as a
        mutation and denied normal reads under MCP.
        """
        result = run_hook(
            "plan_guard.py",
            {
                "tool_name": "mcp__filesystem__read_file",
                "tool_input": {"path": "src/app.py"},
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        # Allow = empty stdout (no JSON decision emitted)
        assert result.stdout.strip() == "", (
            f"plan_guard must allow MCP read tools without a plan. Got stdout: {result.stdout!r}"
        )

    def test_blocks_macos_sed_inplace(self, tmp_path):
        """macOS ``sed -i '' 'expr' <protected_file>`` must emit deny JSON.

        R11 B3 fixup: decision now asserted on stdout JSON.
        """
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "sed -i '' 's/foo/bar/' tools/cc/hooks/write_guard.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_blocks_traversal_bash_write(self, tmp_path):
        """Bash redirect via ../.. traversal to protected path → deny."""
        result = run_hook(
            "write_guard.py",
            {"tool_name": "Bash", "tool_input": {"command": "echo x > tools/cc/../../.claude/settings.json"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


# ─── post_write_check.py v3 additions ───────────────────────────────────────


class TestPostWriteCheckV3:
    def test_ignores_read_tools(self, tmp_path):
        """Glob tool → exit 0, no warnings."""
        result = run_hook(
            "post_write_check.py",
            {"tool_name": "Glob", "tool_input": {"pattern": "*.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert result.stderr.strip() == ""


# ─── reflect_trigger.py v3 additions ────────────────────────────────────────


class TestReflectTriggerV3:
    def test_ignores_read_tools(self, tmp_path):
        """Read tool → exit 0, no counter increment."""
        result = run_hook(
            "reflect_trigger.py",
            {"tool_name": "Read", "tool_input": {"file_path": "src/main.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert not (tmp_path / ".espalier-state" / "write_count").exists()


# ─── session_start.py v3 additions ──────────────────────────────────────────


class TestSessionStartV3:
    def test_writes_session_timestamp(self, tmp_path):
        """After session_start, .espalier-state/session_started exists with ISO timestamp."""
        run_hook("session_start.py", {}, {"CLAUDE_PROJECT_DIR": str(tmp_path)})
        ts_file = tmp_path / ".espalier-state" / "session_started"
        assert ts_file.exists()
        content = ts_file.read_text(encoding="utf-8").strip()
        # Should parse as ISO datetime
        from datetime import datetime
        dt = datetime.fromisoformat(content)
        assert dt.year >= 2024

    def test_cleans_state_flags(self, tmp_path):
        """Every relief record subagent_stop can write (read off the shared
        table, so a new reviewer mapping is swept without an edit here) and the
        legacy `review_requested` a pre-DEF-608 stop_gate wrote are deleted by
        session_start."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_hook_utils_for_flags", HOOKS_DIR / "_hook_utils.py"
        )
        hook_utils = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook_utils)
        flags = [*hook_utils.RELIEF_FLAGS.values(), "review_requested"]
        assert len(flags) >= 3  # docs_refreshed, code_reviewed, the legacy name
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        for flag in flags:
            (state_dir / flag).write_text("", encoding="utf-8")
        run_hook("session_start.py", {}, {"CLAUDE_PROJECT_DIR": str(tmp_path)})
        left = [flag for flag in flags if (state_dir / flag).exists()]
        assert not left, f"session_start left relief flags behind: {left}"

    def test_resets_write_counter(self, tmp_path):
        """Pre-existing write_count is deleted by session_start."""
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        (state_dir / "write_count").write_text("15", encoding="utf-8")
        run_hook("session_start.py", {}, {"CLAUDE_PROJECT_DIR": str(tmp_path)})
        assert not (state_dir / "write_count").exists()


class TestColdOpenProducer:
    """TP-242: SessionStart drops a one-shot ``cold_open_pending`` flag on a
    new-session source (startup/clear) and REMOVES it on a continuation source
    (resume/compact/unknown), so task_router can enforce an un-preemptible
    orientation readout on the session's first prompt. Producer half of the baton.
    """

    @staticmethod
    def _load():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_ss_cold_open", HOOKS_DIR / "session_start.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @staticmethod
    def _flag(root):
        return root / ".espalier-state" / "cold_open_pending"

    def test_helper_writes_flag_on_new_session_sources(self, tmp_path):
        """startup/clear -> the flag exists, content is an ISO timestamp (the
        session_started convention)."""
        from datetime import datetime
        mod = self._load()
        for src in ("startup", "clear"):
            self._flag(tmp_path).unlink(missing_ok=True)
            mod._set_cold_open_flag(tmp_path, src)
            flag = self._flag(tmp_path)
            assert flag.is_file(), f"expected cold-open flag for source={src!r}"
            datetime.fromisoformat(flag.read_text(encoding="utf-8").strip())  # parses or raises

    def test_helper_removes_flag_on_continuation_sources(self, tmp_path):
        """resume/compact/unknown -> a pre-existing flag is removed (no stale
        cold-open leaks into a continued session)."""
        mod = self._load()
        for src in ("resume", "compact", ""):
            flag = self._flag(tmp_path)
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text("stale", encoding="utf-8")
            mod._set_cold_open_flag(tmp_path, src)
            assert not flag.exists(), f"expected no cold-open flag for source={src!r}"

    def test_main_writes_flag_on_clear(self, tmp_path):
        """End-to-end: session_start main() with source=clear leaves the flag."""
        run_hook("session_start.py", {"source": "clear"},
                 {"CLAUDE_PROJECT_DIR": str(tmp_path)})
        assert self._flag(tmp_path).is_file()

    def test_main_removes_stale_flag_on_resume(self, tmp_path):
        """End-to-end: a stale flag is cleared when main() runs on source=resume
        (the cleaner does not touch it; the dedicated source-aware setter does)."""
        flag = self._flag(tmp_path)
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("stale", encoding="utf-8")
        run_hook("session_start.py", {"source": "resume"},
                 {"CLAUDE_PROJECT_DIR": str(tmp_path)})
        assert not flag.exists()


# ─── stop_gate.py v3 additions ──────────────────────────────────────────────


class TestStopGateV3:
    def _make_git_repo(self, tmp_path):
        """Initialize a git repo with an initial commit (state dir ignored)."""
        git_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t",
        }
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / "README.md").write_text("init\n", encoding="utf-8")
        (tmp_path / ".gitignore").write_text(".espalier-state/\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path,
                       capture_output=True, env=git_env)
        return git_env

    def test_allows_clean_tree(self, tmp_path):
        """No uncommitted changes → exit 0 (after pytest gate passes)."""
        self._make_git_repo(tmp_path)
        # Provide a tests/ dir that's empty so pytest skips gracefully
        result = run_hook(
            "stop_gate.py",
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        # Clean tree — passes all gates (gate 5 was removed in TP-70).
        assert_hook_allowed(result)

    def test_skips_docs_short_session(self, tmp_path):
        """write_count < 10 → gate 2 skipped (docs not required)."""
        self._make_git_repo(tmp_path)
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        (state_dir / "write_count").write_text("3", encoding="utf-8")
        # No docs_refreshed flag, but count is low — should not block on gate 2
        result = run_hook(
            "stop_gate.py",
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        # Gate 2 skipped; clean tree → exit 0
        assert result.returncode == 0

    def test_blocks_no_docs_refresh_long_session(self, tmp_path):
        """write_count >= 10, no docs_refreshed flag → block JSON on stdout."""
        self._make_git_repo(tmp_path)
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        (state_dir / "write_count").write_text("12", encoding="utf-8")
        result = run_hook(
            "stop_gate.py",
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["decision"] == "block"
        assert "docs-maintainer" in output["reason"]
        # Channel-XOR: block() writes JSON to stdout only; the stderr mirror
        # was dropped in round 8 to preserve forward compatibility with the
        # protocol (stderr-on-exit-0 may become advisory context in future
        # Claude Code versions).
        assert "docs-maintainer" not in result.stderr

    def test_passes_docs_when_flag_exists(self, tmp_path):
        """docs_refreshed flag present → gate 2 passes."""
        self._make_git_repo(tmp_path)
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        (state_dir / "write_count").write_text("12", encoding="utf-8")
        (state_dir / "docs_refreshed").write_text(
            '{"agent": "docs-maintainer", "changed_docs": ["docs/CONVENTIONS.md"]}', encoding="utf-8"
        )  # DEF-495: Gate 2 relieves on recorded evidence, not on mere existence
        # Gate 3 will fire instead — but we're just verifying gate 2 passes
        result = run_hook(
            "stop_gate.py",
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        # Either gate 3 blocks (review), or everything passes (clean tree)
        if result.returncode == 0 and result.stdout.strip():
            output = json.loads(result.stdout)
            # Should be gate 3 (code-reviewer), not gate 2 (docs-maintainer)
            assert "code-reviewer" in output.get("reason", "")

    def test_blocks_no_code_review_long_session(self, tmp_path):
        """write_count >= 10, docs_refreshed set, no code_reviewed record → block with the code-reviewer dispatch."""
        self._make_git_repo(tmp_path)
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        (state_dir / "write_count").write_text("12", encoding="utf-8")
        (state_dir / "docs_refreshed").write_text(
            '{"agent": "docs-maintainer", "changed_docs": ["docs/CONVENTIONS.md"]}', encoding="utf-8"
        )  # DEF-495: Gate 2 relieves on recorded evidence, not on mere existence
        result = run_hook(
            "stop_gate.py",
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["decision"] == "block"
        assert "code-reviewer" in output["reason"]

    def test_passes_review_when_flag_exists(self, tmp_path):
        """code_reviewed record naming the reviewer + docs_refreshed → both gates 2/3 pass."""
        self._make_git_repo(tmp_path)
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        (state_dir / "write_count").write_text("12", encoding="utf-8")
        (state_dir / "docs_refreshed").write_text(
            '{"agent": "docs-maintainer", "changed_docs": ["docs/CONVENTIONS.md"]}', encoding="utf-8"
        )  # DEF-495: Gate 2 relieves on recorded evidence, not on mere existence
        (state_dir / "code_reviewed").write_text(
            '{"agent": "code-reviewer", "last_message_chars": 12, "excerpt": "No findings."}', encoding="utf-8"
        )  # DEF-608: Gate 3 relieves on the reviewer having RUN, recorded by subagent_stop
        result = run_hook(
            "stop_gate.py",
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        # Gates 2+3 pass; clean tree → exit 0
        assert result.returncode == 0

    def _long_session_with_docs_evidence(self, tmp_path):
        """A tree past the write threshold with Gate 2 satisfied, so only Gate 3 speaks."""
        self._make_git_repo(tmp_path)
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        (state_dir / "write_count").write_text("12", encoding="utf-8")
        (state_dir / "docs_refreshed").write_text(
            '{"agent": "docs-maintainer", "changed_docs": ["docs/CONVENTIONS.md"]}', encoding="utf-8"
        )
        return state_dir

    def _stop(self, tmp_path):
        return run_hook(
            "stop_gate.py",
            {},
            {
                "CLAUDE_PROJECT_DIR": str(tmp_path),
                "ESPALIER_MAINTENANCE_MODE": None,  # delete: bypass would skip Gate 3
            },
        )

    def test_gate3_re_arms_on_every_turn_until_a_review_runs(self, tmp_path):
        """DEF-608: the gate used to write `review_requested` itself on its
        first block, so the SECOND Stop of the session passed with no review
        run -- satisfied by having asked. It now writes nothing and a later
        turn's Stop blocks again. The directory listing is the proof it only
        reads. (The continuation's own Stop is a different case -- the next
        test.)
        """
        state_dir = self._long_session_with_docs_evidence(tmp_path)
        before = sorted(p.name for p in state_dir.iterdir())
        first = self._stop(tmp_path)
        second = self._stop(tmp_path)
        for result in (first, second):
            assert result.returncode == 0
            output = json.loads(result.stdout)
            assert output["decision"] == "block"
            assert "code-reviewer" in output["reason"]
        after = sorted(p.name for p in state_dir.iterdir())
        assert after == before, f"Gate 3 wrote into the state dir: {after}"

    def test_the_continuation_stop_passes_by_the_loop_guard(self, tmp_path):
        """What the block actually buys, pinned so the docs cannot overclaim it:
        Claude Code re-fires Stop with `stop_hook_active: true` after a block,
        and `_run_main`'s loop guard allows that Stop ahead of every gate. So
        Gate 3 fires on the FIRST Stop of each turn until a review has run --
        not on every Stop (failure-mode review, 2026-09-07).
        """
        self._long_session_with_docs_evidence(tmp_path)
        result = run_hook(
            "stop_gate.py",
            {"stop_hook_active": True},
            {"CLAUDE_PROJECT_DIR": str(tmp_path), "ESPALIER_MAINTENANCE_MODE": None},
        )
        assert result.returncode == 0
        assert '"block"' not in result.stdout, result.stdout

    def test_a_code_reviewer_subagent_stop_relieves_gate3(self, tmp_path):
        """End to end across the two hooks: subagent_stop records the review
        when the code-reviewer subagent finishes, and the next Stop reads it."""
        self._long_session_with_docs_evidence(tmp_path)
        sub = run_hook(
            "subagent_stop.py",
            {
                "agent_type": "code-reviewer",
                "stop_hook_active": False,
                "last_assistant_message": "Reviewed the diff. No BLOCK findings.",
            },
            {"CLAUDE_PROJECT_DIR": str(tmp_path), "ESPALIER_MAINTENANCE_MODE": None},
        )
        assert sub.returncode == 0, sub.stderr
        record = json.loads(
            (tmp_path / ".espalier-state" / "code_reviewed").read_text(encoding="utf-8")
        )
        assert record["agent"] == "code-reviewer"
        assert "No BLOCK findings" in record["excerpt"]
        result = self._stop(tmp_path)
        assert result.returncode == 0
        assert '"block"' not in result.stdout, result.stdout

    def test_a_touched_flag_is_not_review_evidence(self, tmp_path):
        """`touch .espalier-state/code_reviewed` is a file, not a record -- and
        the message says THAT, rather than describing a run that never was."""
        state_dir = self._long_session_with_docs_evidence(tmp_path)
        (state_dir / "code_reviewed").write_text("", encoding="utf-8")
        output = json.loads(self._stop(tmp_path).stdout)
        assert output["decision"] == "block"
        assert "is not a relief record: empty" in output["reason"]

    def test_a_record_naming_a_non_reviewer_does_not_relieve_gate3(self, tmp_path):
        state_dir = self._long_session_with_docs_evidence(tmp_path)
        (state_dir / "code_reviewed").write_text(
            '{"agent": "test-writer", "last_message_chars": 0, "excerpt": ""}', encoding="utf-8"
        )
        output = json.loads(self._stop(tmp_path).stdout)
        assert output["decision"] == "block"
        assert "is not a relief record" in output["reason"]
        assert "test-writer" in output["reason"]

    def test_hand_recorded_judgement_relieves_gate3_only_with_a_real_note(self, tmp_path):
        """The escape the deny message names: agent "operator" plus a note that
        says why. A blank note is not a judgement; neither is a punctuation
        mark (failure-mode review: `"note": "."` used to pass, silently). The
        relief is announced on stderr so the transcript shows it.
        """
        state_dir = self._long_session_with_docs_evidence(tmp_path)
        (state_dir / "code_reviewed").write_text('{"agent": "operator", "note": "   "}', encoding="utf-8")
        output = json.loads(self._stop(tmp_path).stdout)
        assert output["decision"] == "block"
        assert "the operator note is blank" in output["reason"]
        (state_dir / "code_reviewed").write_text('{"agent": "operator", "note": "."}', encoding="utf-8")
        output = json.loads(self._stop(tmp_path).stdout)
        assert output["decision"] == "block"
        assert "the operator note is 1 characters" in output["reason"]
        (state_dir / "code_reviewed").write_text(
            '{"agent": "operator", "note": "reviewed in the PR thread by hand"}', encoding="utf-8"
        )
        result = self._stop(tmp_path)
        assert result.returncode == 0
        assert '"block"' not in result.stdout, result.stdout
        assert "[stop_gate] code_reviewed: relieved by a hand-recorded judgement" in result.stderr
        assert "reviewed in the PR thread by hand" in result.stderr

    def test_a_relief_record_written_from_powershell_is_read(self, tmp_path):
        """DEF-797: Windows PowerShell 5.1's `>` and `Out-File` write UTF-16LE
        with a byte-order mark, and docs/TROUBLESHOOTING.md invites a blocked
        operator to write the record. The strict read raised on the mark, a
        UnicodeDecodeError is a ValueError the JSON handler never saw, and the
        crash guard re-blocked with an internal error: the documented escape
        hatch bricked the Stop (driven on the Windows host 2026-09-14). The
        mark is pinned little-endian explicitly, as that shell writes it; an
        editor's UTF-8 mark is read too."""
        state_dir = self._long_session_with_docs_evidence(tmp_path)
        record = '{"agent": "operator", "note": "reviewed in the PR thread by hand"}'
        for label, data in (
            ("utf-16le with a byte-order mark", codecs.BOM_UTF16_LE + record.encode("utf-16-le")),
            ("utf-8 with a byte-order mark", codecs.BOM_UTF8 + record.encode("utf-8")),
        ):
            (state_dir / "code_reviewed").write_bytes(data)
            result = self._stop(tmp_path)
            assert result.returncode == 0, label
            assert '"block"' not in result.stdout, (label, result.stdout)
            assert "internal error" not in result.stdout, (label, result.stdout)
            assert "[stop_gate] code_reviewed: relieved by a hand-recorded judgement" in result.stderr, label

    def test_a_relief_record_the_gate_cannot_decode_is_named_not_crashed_on(self, tmp_path):
        """Bytes that are neither UTF-8 nor byte-order-marked UTF-16/32, and a
        UTF-16 file with no mark (NUL after every character once decoded), get
        this gate's own reason naming the encoding to re-save in -- never the
        crash guard's internal error, and never merely "not JSON"."""
        state_dir = self._long_session_with_docs_evidence(tmp_path)
        for label, data, detail in (
            (
                "utf-16le, no byte-order mark",
                '{"agent": "operator", "note": "reviewed in the PR thread by hand"}'.encode("utf-16-le"),
                "NUL bytes -- UTF-16 without a byte-order mark?",
            ),
            (
                "cp1252 with an accent",
                '{"agent": "operator", "note": "revu \xe0 la main dans le fil de la PR"}'.encode("cp1252"),
                "invalid continuation byte",
            ),
        ):
            (state_dir / "code_reviewed").write_bytes(data)
            output = json.loads(self._stop(tmp_path).stdout)
            assert output["decision"] == "block", label
            assert "is not a relief record: not UTF-8 text (" in output["reason"], (label, output["reason"])
            assert detail in output["reason"], (label, output["reason"])
            assert "re-save it as UTF-8" in output["reason"], label
            assert "internal error" not in output["reason"], label

    def test_a_malformed_docs_record_is_named_not_mistaken_for_a_run(self, tmp_path):
        """Gate 2's no-changes message describes an agent run. Garbage, an
        empty file and a blank-note operator record are not runs (code review,
        2026-09-07): each is named for what it is."""
        self._make_git_repo(tmp_path)
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        (state_dir / "write_count").write_text("12", encoding="utf-8")
        for content, why in (
            ("garbage", "not JSON"),
            ("", "empty"),
            ("[1, 2]", "not a JSON object"),
            ('{"agent": "operator", "note": ""}', "the operator note is blank"),
        ):
            (state_dir / "docs_refreshed").write_text(content, encoding="utf-8")
            output = json.loads(self._stop(tmp_path).stdout)
            assert output["decision"] == "block", content
            assert f"is not a relief record: {why}" in output["reason"], (content, output["reason"])
            assert "ran but changed no documentation" not in output["reason"], content
        # ... and a genuine ran-and-changed-nothing record still gets that message.
        (state_dir / "docs_refreshed").write_text(
            '{"agent": "docs-maintainer", "changed_docs": [], "last_message_chars": 0, "excerpt": ""}', encoding="utf-8"
        )
        output = json.loads(self._stop(tmp_path).stdout)
        assert "ran but changed no documentation" in output["reason"]

    def test_hand_recorded_judgement_relieves_gate2(self, tmp_path):
        """Gate 2 honours the same record. Its message used to say "clear the
        flag deliberately", and clearing it re-blocked with the OTHER docs
        message (driven 2026-09-07): the escape it named was not an escape.
        """
        self._make_git_repo(tmp_path)
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        (state_dir / "write_count").write_text("12", encoding="utf-8")
        (state_dir / "docs_refreshed").write_text(
            '{"agent": "operator", "note": "no public surface changed this session"}', encoding="utf-8"
        )
        (state_dir / "code_reviewed").write_text(
            '{"agent": "operator", "note": "reviewed by hand in the PR thread"}', encoding="utf-8"
        )
        result = self._stop(tmp_path)
        assert result.returncode == 0
        assert '"block"' not in result.stdout, result.stdout
        assert "[stop_gate] docs_refreshed: relieved by a hand-recorded judgement" in result.stderr

    # (TestStopGateV3.test_blocks_unsaved_state / test_allows_saved_state
    # deleted in TP-70 -- they covered Gate 5 behavior which the gate's
    # removal eliminates. The MAINTENANCE_MODE bypass for Gate 5 is also
    # gone; bypass coverage now lives in TestStopGate at the class above.)


# ─── Pack 4: silent-failure observability ───────────────────────────────────


class TestStopGateMode:
    """ESPALIER_STOP_GATE: light (default) skips pytest; full opts in."""

    def _make_git_repo(self, tmp_path):
        """Initialize a git repo with an initial commit (state dir ignored)."""
        git_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t",
        }
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / "README.md").write_text("init\n", encoding="utf-8")
        # __pycache__/.pyc kept ignored so the working tree stays clean
        # under pytest-in-full-mode bytecode writes (Gate 5 was removed in TP-70 —
        # a clean tree is still polite for any future
        # dirty-tree-sensitive checks).
        (tmp_path / ".gitignore").write_text(
            ".espalier-state/\n__pycache__/\n*.pyc\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path,
                       capture_output=True, env=git_env)
        return git_env

    def _commit_test_file(self, tmp_path, contents, git_env):
        """Write tests/test_hooks.py with given contents and commit it."""
        (tmp_path / "tests").mkdir(exist_ok=True)
        (tmp_path / "tests" / "test_hooks.py").write_text(contents, encoding="utf-8")
        subprocess.run(["git", "add", "tests"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "test"], cwd=tmp_path,
                       capture_output=True, env=git_env)

    def test_default_mode_skips_pytest(self, tmp_path):
        """Test A: with no env var, a failing test file does not block Stop."""
        git_env = self._make_git_repo(tmp_path)
        self._commit_test_file(
            tmp_path,
            "def test_fails():\n    assert False\n",
            git_env,
        )
        result = run_hook(
            "stop_gate.py",
            {},
            # None deletes the inherited var so this test models a clean
            # shell even when the operator exports ESPALIER_STOP_GATE=full
            # in their shell rc (the SHARP_EDGES footgun).
            {"CLAUDE_PROJECT_DIR": str(tmp_path), "ESPALIER_STOP_GATE": None},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_full_mode_blocks_on_failing_tests(self, tmp_path):
        """Test B: full mode runs pytest; failing tests → block JSON on stdout."""
        git_env = self._make_git_repo(tmp_path)
        self._commit_test_file(
            tmp_path,
            "def test_fails():\n    assert False\n",
            git_env,
        )
        result = run_hook(
            "stop_gate.py",
            {},
            {
                "CLAUDE_PROJECT_DIR": str(tmp_path),
                "ESPALIER_STOP_GATE": "full",
            },
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["decision"] == "block"
        assert "Tests are failing" in output["reason"]
        # Channel-XOR (round-8 W4): block() writes JSON to stdout only.
        assert "Tests are failing" not in result.stderr

    def test_full_mode_passes_on_passing_tests(self, tmp_path):
        """Test C: full mode + passing tests + clean tree → allow stop."""
        git_env = self._make_git_repo(tmp_path)
        self._commit_test_file(
            tmp_path,
            "def test_passes():\n    assert True\n",
            git_env,
        )
        result = run_hook(
            "stop_gate.py",
            {},
            {
                "CLAUDE_PROJECT_DIR": str(tmp_path),
                "ESPALIER_STOP_GATE": "full",
            },
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_unknown_mode_warns_and_falls_back(self, tmp_path):
        """Test D: unknown mode value warns to stderr, behaves as light."""
        git_env = self._make_git_repo(tmp_path)
        self._commit_test_file(
            tmp_path,
            "def test_fails():\n    assert False\n",
            git_env,
        )
        result = run_hook(
            "stop_gate.py",
            {},
            {
                "CLAUDE_PROJECT_DIR": str(tmp_path),
                "ESPALIER_STOP_GATE": "expensive",
            },
        )
        assert result.returncode == 0
        assert "unknown ESPALIER_STOP_GATE" in result.stderr

    def test_full_mode_case_insensitive(self, tmp_path):
        """Mode parsing is case-insensitive and whitespace-trimmed."""
        git_env = self._make_git_repo(tmp_path)
        self._commit_test_file(
            tmp_path,
            "def test_fails():\n    assert False\n",
            git_env,
        )
        result = run_hook(
            "stop_gate.py",
            {},
            {
                "CLAUDE_PROJECT_DIR": str(tmp_path),
                "ESPALIER_STOP_GATE": "  FULL  ",
            },
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["decision"] == "block"


class TestHookUtils:
    """_hook_utils.py — warn helper format is stable and testable."""

    def test_warn_format(self, tmp_path):
        utils = HOOKS_DIR / "_hook_utils.py"
        result = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, r'{HOOKS_DIR}'); "
             "from _hook_utils import warn; warn('test message')"],
            capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0
        assert "[WARN] espalier: test message" in result.stderr

    def test_warn_exc_format(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, r'{HOOKS_DIR}'); "
             "from _hook_utils import warn_exc; "
             "warn_exc('op failed', ValueError('bad value'))"],
            capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0
        assert "[WARN] espalier: op failed: ValueError: bad value" in result.stderr

    def test_host_orientation_parenthetical_never_contradicts(self, monkeypatch):
        """The trailing parenthetical is derived from the same has_py3/has_py booleans
        as the python3=/python= fields, so it can never contradict them (a fixed literal
        used to claim `both present` even on a single-interpreter host). Witnesses all
        FOUR interpreter states so a future refactor of the elif chain can't re-accrete a
        contradiction on an un-asserted branch."""
        # syspath_prepend puts HOOKS_DIR on sys.path and auto-reverts after the test (no
        # lingering pollution); a per-test insert is this suite's convention.
        monkeypatch.syspath_prepend(str(HOOKS_DIR))
        import _hook_utils
        render = _hook_utils.host_orientation_line

        # Patch the IDENTITY SEAM, not `shutil.which`. The fields now mean
        # "answers as Python 3", not "something answers to this name", so a
        # which-only fixture that hands back a fabricated path silently depends
        # on that path being a real interpreter on the machine running the suite
        # -- `/usr/bin/python` is absent here and present elsewhere, so the same
        # fixture asserted different things in different places. Driven: before
        # this change the `both present` case below reported `python=no` on this
        # host. Patching the seam also bypasses the per-process memo, which would
        # otherwise pin the first state for the rest of the test.
        def _state(*, py3: bool, py: bool):
            monkeypatch.setattr(
                _hook_utils, "interpreter_is_python3",
                lambda name: {"python3": py3, "python": py}.get(name, False),
            )

        # py3-only host (stock macOS, the majority platform) — the original contradiction.
        _state(py3=True, py=False)
        line = render()
        assert "python3=yes python=no" in line and "both present" not in line  # earn-red
        # both present — "both present" is legitimate here (suffix derived, not deleted).
        _state(py3=True, py=True)
        both = render()
        assert "python3=yes python=yes" in both and "both present" in both
        # python-only host — must not claim both present, must not contradict python3=no.
        _state(py3=False, py=True)
        py_only = render()
        assert "python3=no python=yes" in py_only and "both present" not in py_only
        # neither interpreter present.
        _state(py3=False, py=False)
        neither = render()
        assert "python3=no python=no" in neither and "both present" not in neither

    def test_interpreter_identity_two_copy_parity(self, monkeypatch, tmp_path):
        """2-D: the identity probe has two isolation-domain copies --
        `_hook_utils.interpreter_is_python3` and
        `espalier.doctor._interpreter_is_python3` -- because `tools/cc/` may not
        import espalier. They must agree, or the boot-time detector and the
        opt-in detector disagree about the same host.

        Follows this repo's `decode_bom` three-copy precedent
        (`tests/test_surface_contract.py::test_decode_bom_three_copy_parity`).
        ⚠ The pack originally claimed that precedent carried NO parity test and
        used it to argue a parity test was unnecessary here; that was false, and
        the real precedent argues the opposite -- duplicated identity logic in
        this repo gets pinned rather than noted.
        """
        import shutil
        import stat
        monkeypatch.syspath_prepend(str(HOOKS_DIR))
        import _hook_utils
        from espalier import doctor as doctor_module

        # A stale Python-2 symlink is named as a motivating case in BOTH
        # docstrings and was tested by neither: none of the original four cases
        # emits Python-2 output, so both copies agreed on all four even with the
        # version discriminator deleted. Driven -- relaxing `startswith("Python
        # 3.")` to `startswith("Python")` in either copy survived the whole
        # suite. A stub that reports Python 2 is the only case that separates
        # them, so it is the one the parity test most needs.
        py2 = tmp_path / "python2stub"
        py2.write_text("#!/bin/sh\necho 'Python 2.7.18' >&2\n", encoding="utf-8")
        py2.chmod(py2.stat().st_mode | stat.S_IEXEC)

        cases = [
            ("a real python3", shutil.which("python3")),
            ("a python 2 report", str(py2)),
            ("a resolving non-interpreter", "/bin/ls"),
            ("an absent path", "/nonexistent/python3"),
            ("empty", ""),
        ]
        for label, candidate in cases:
            if candidate is None:
                continue
            _hook_utils._INTERPRETER_IDENTITY_MEMO.clear()
            try:
                hook_side = _hook_utils.interpreter_is_python3(candidate)
            finally:
                _hook_utils._INTERPRETER_IDENTITY_MEMO.clear()
            engine_side = doctor_module._interpreter_is_python3(
                shutil.which(candidate) or candidate or None
            )
            assert hook_side == engine_side, (
                f"identity probes disagree on {label} ({candidate!r}): "
                f"hook={hook_side} engine={engine_side}"
            )

    def test_host_orientation_reports_a_resolving_non_python_as_no(self, monkeypatch):
        """2-D: the CLASS C discrimination the old presence test could not make.
        A name that RESOLVES but is not Python 3 must report `no`, not `yes` --
        reporting `yes` put a false host fact into every subagent's orientation
        line on exactly the host where the guards were failing open."""
        import shutil
        monkeypatch.syspath_prepend(str(HOOKS_DIR))
        import _hook_utils
        # The memo is process-scoped and this test deliberately drives the real
        # probe, so clear it on both sides or a neighbouring test's verdict wins.
        _hook_utils._INTERPRETER_IDENTITY_MEMO.clear()
        # `/bin/ls` resolves and executes, and is not an interpreter -- the
        # cheapest real stand-in for a Store App Execution Alias.
        monkeypatch.setattr(shutil, "which", lambda n: "/bin/ls")
        try:
            line = _hook_utils.host_orientation_line()
        finally:
            _hook_utils._INTERPRETER_IDENTITY_MEMO.clear()
        assert "python3=no python=no" in line, (
            f"a resolving non-interpreter must read as `no`: {line}"
        )


class TestSessionStartSilentFailure:
    """session_start.py — absent files are silent; malformed files warn."""

    def test_absent_memory_md_no_warning(self, tmp_path):
        """No ESPALIER_MEMORY.md → exit 0, no WARN in stderr."""
        result = run_hook(
            "session_start.py",
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "[WARN] espalier" not in result.stderr

    def test_malformed_package_json_warns(self, tmp_path):
        """Present but malformed package.json → exit 0, stderr has WARN."""
        (tmp_path / "package.json").write_text("not valid json {{{", encoding="utf-8")
        result = run_hook(
            "session_start.py",
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "[WARN] espalier" in result.stderr
        assert "package.json" in result.stderr


class TestPostCompactSilentFailure:
    """post_compact.py — absent files are silent; malformed files warn."""

    def test_absent_optional_files_no_warning(self, tmp_path):
        """No config files → exit 0, no WARN in stderr."""
        result = run_hook(
            "post_compact.py",
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "[WARN] espalier" not in result.stderr

    def test_malformed_package_json_warns(self, tmp_path):
        """Present but malformed package.json → exit 0, stderr has WARN."""
        (tmp_path / "package.json").write_text("{invalid}", encoding="utf-8")
        result = run_hook(
            "post_compact.py",
            {},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "[WARN] espalier" in result.stderr
        assert "package.json" in result.stderr


class TestReflectTriggerBlueprintWarn:
    """reflect_trigger.py — blueprint record failure emits visible warning."""

    def test_blueprint_record_failure_warns_not_fatal(self, tmp_path):
        """10th write with non-existent blueprint script → exit 0, may warn."""
        state_dir = tmp_path / ".espalier-state"
        state_dir.mkdir()
        (state_dir / "write_count").write_text("9", encoding="utf-8")

        result = run_hook(
            "reflect_trigger.py",
            {"tool_name": "Write", "tool_input": {"file_path": "src/main.py"}},
            {"CLAUDE_PROJECT_DIR": str(tmp_path)},
        )
        assert result.returncode == 0


# ─── TP-151 E-2: reflect_trigger / post_write_check fail-OPEN umbrellas ──────


def _load_hook_module(filename: str, alias: str):
    """Load a hook script as a fresh module for in-process umbrella tests."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(alias, str(HOOKS_DIR / filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


class TestReflectTriggerFailOpenUmbrella:
    """TP-151 E-2: reflect_trigger is an advisory PostToolUse hook — it must
    never spew a traceback (exit 1) on producer schema drift. main() fails
    OPEN (exit 0 + a single [ERROR] line), mirroring task_router's umbrella.
    The render loop additionally uses observable .get() sentinels so a finding
    missing kind/severity/description renders (UNKNOWN / <missing description>)
    instead of crashing."""

    def test_main_fails_open_on_internal_crash(self, monkeypatch, capsys):
        mod = _load_hook_module("reflect_trigger.py", "reflect_trigger_umbrella")
        monkeypatch.setattr(
            mod._hook_utils, "read_stdin_safely",
            lambda: {"tool_name": "Write", "tool_input": {"file_path": "src/x.py"}},
        )

        def _boom(*a, **k):
            raise AttributeError("simulated crash")

        monkeypatch.setattr(mod, "_resolve_project_root", _boom)
        rc = mod.main()
        captured = capsys.readouterr()
        assert rc == 0, "advisory hook must fail OPEN (exit 0)"
        assert "[ERROR] reflect_trigger crashed: AttributeError" in captured.err

    def test_render_loop_uses_sentinels_for_missing_keys(
        self, tmp_path, monkeypatch, capsys,
    ):
        mod = _load_hook_module("reflect_trigger.py", "reflect_trigger_sentinel")
        # reflect_protocol must exist so _run_reflect proceeds past the guard.
        (tmp_path / "tools" / "cc").mkdir(parents=True)
        (tmp_path / "tools" / "cc" / "reflect_protocol.py").write_text("", encoding="utf-8")
        monkeypatch.setattr(mod, "_resolve_project_root", lambda: tmp_path)
        # A config-file write triggers _run_reflect immediately.
        monkeypatch.setattr(
            mod._hook_utils, "read_stdin_safely",
            lambda: {"tool_name": "Write",
                     "tool_input": {"file_path": "pyproject.toml"}},
        )
        # reflect_protocol returns findings that are (a) missing every key and
        # (b) present-but-null — pre-fix the bare f['severity'] subscript
        # crashed on the missing case, and `.get(k, default)` would still leave
        # None for the null case (crashing kind.upper() / rendering "[None]").
        report = {
            "findings": [
                {},
                {"kind": None, "severity": None, "description": None},
            ],
            "gap_count": 1,
            "orphan_count": 0,
            "files_analyzed": 3,
        }
        fake = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(report), stderr="",
        )
        monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: fake)

        rc = mod.main()
        captured = capsys.readouterr()
        assert rc == 0
        # Observable sentinels rendered, not a KeyError crash.
        assert "UNKNOWN" in captured.err
        assert "<missing description>" in captured.err


class TestPostWriteCheckFailOpenUmbrella:
    """TP-151 E-2: post_write_check is an advisory PostToolUse hook. A crash in
    any check helper must degrade to exit 0 + a single [ERROR] line, not a
    per-write traceback. (No bare finding subscripts exist in its body at HEAD;
    the umbrella is the whole fix.)"""

    def test_main_fails_open_on_internal_crash(self, monkeypatch, capsys):
        mod = _load_hook_module("post_write_check.py", "post_write_check_umbrella")

        def _boom(*a, **k):
            raise AttributeError("simulated crash")

        # main() does `from _hook_utils import read_stdin_safely` then calls it;
        # patch the source attr so the late binding picks up the raiser.
        monkeypatch.setattr(mod._hook_utils, "read_stdin_safely", _boom)
        rc = mod.main()
        captured = capsys.readouterr()
        assert rc == 0, "advisory hook must fail OPEN (exit 0)"
        assert "[ERROR] post_write_check crashed: AttributeError" in captured.err
