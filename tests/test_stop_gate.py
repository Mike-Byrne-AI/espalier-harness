"""Tests for tools/cc/hooks/stop_gate.py — selective gate bypass.

Covers the MAINTENANCE_MODE contract:
  - Gate 1 (pytest, opt-in via STOP_GATE=full) STILL runs under the flag.
  - Gates 2 (docs) and 3 (review) are SKIPPED under the flag.
  - Gate 4 (auto-finalize blueprint) is silent and harmless; left running.

(Pre-TP-70 there was a Gate 5 "session state saved" that this file
exercised under TestGate5DirtyTree. Gate removed; class deleted.)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"


def _init_dirty_repo(tmp_path: Path) -> None:
    """Init a git repo with an untracked file. Used by tests that need
    a non-clean working tree (e.g., maintenance-mode bypass coverage)."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "stray.txt").write_text("x", encoding="utf-8")


def _run(tmp_path: Path, *, mode: str | None = None, stop_gate: str | None = None):
    script = HOOKS_DIR / "stop_gate.py"
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    for k, v in (("ESPALIER_MAINTENANCE_MODE", mode), ("ESPALIER_STOP_GATE", stop_gate)):
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps({}),
        capture_output=True,
        text=True,
        timeout=15,
        env=env, encoding="utf-8",
    )


class TestStopGateFailClosedUmbrella:
    """TP-151 E-1: stop_gate is a BLOCKING Stop hook. An uncaught crash in the
    gate sequence must RE-BLOCK (exit 0 + block JSON), not fail OPEN — the
    protocol treats exit 1 as a non-blocking script error, which would let the
    session Stop with the gates unrun. Sister to the plan_guard / write_guard /
    config_guard fail-closed umbrellas, adapted to stop_gate's block() sentinel
    (block() returns 1; the umbrella must still return exit 0, never propagate
    the sentinel)."""

    @staticmethod
    def _load():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "stop_gate_umbrella_under_test", str(HOOKS_DIR / "stop_gate.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["stop_gate_umbrella_under_test"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_crash_reblocks_with_exit_zero(self, monkeypatch, capsys):
        mod = self._load()
        monkeypatch.setattr(mod._hook_utils, "read_stdin_safely", lambda: {})
        # Best-effort Gate 4 must not touch the real blueprint chain.
        monkeypatch.setattr(mod, "_gate_finalize_blueprint", lambda *a, **k: None)

        def _boom(*a, **k):
            raise AttributeError("simulated internal crash")

        monkeypatch.setattr(mod, "_read_write_count", _boom)

        rc = mod.main()
        captured = capsys.readouterr()
        assert rc == 0, "fail-closed umbrella must return exit 0, not 1/2"
        data = json.loads(captured.out)
        assert data["decision"] == "block", (
            f"crash must re-block via block(); got {data!r}"
        )
        assert "stop_gate internal error" in data.get("reason", "")
        assert "[ERROR] stop_gate crashed: AttributeError" in captured.err


class TestGate1PytestStillRuns:
    """Gate 1 (pytest) is signal, not friction. Must still run under MAINTENANCE_MODE."""

    def _make_failing_core_test(self, tmp_path: Path) -> None:
        """Create a tests/test_hooks.py that fails — one of the harness-default
        test paths consulted by ``_resolve_core_tests`` when no fingerprint is
        present (TP-73)."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_hooks.py").write_text(
            "def test_intentionally_failing():\n    assert False\n", encoding="utf-8"
        )

    def test_failing_pytest_blocks_under_flag(self, tmp_path):
        _init_dirty_repo(tmp_path)
        self._make_failing_core_test(tmp_path)
        result = _run(tmp_path, mode="1", stop_gate="full")
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["decision"] == "block"
        assert "Tests are failing" in output["reason"], (
            f"expected pytest failure block, got {output!r}"
        )

    def test_passing_pytest_allows_under_flag(self, tmp_path):
        """Light mode (no STOP_GATE=full) skips Gate 1 entirely; the flag then
        skips gates 2/3 — exit clean even with a dirty tree."""
        _init_dirty_repo(tmp_path)
        result = _run(tmp_path, mode="1", stop_gate=None)
        assert result.returncode == 0
        assert result.stdout == ""


class TestEnvOverrideGate1:
    """B-1: ``ESPALIER_STOP_GATE_TEST_CMD`` is the ONLY real Gate 1 for
    non-pytest adopters (go/npm/cargo/make). Before this, no test fired it, so
    ``_run_command_gate`` (named for the override alone until 2026-10-08) could be neutered to ``return 0`` and the suite
    stayed green. Pin every branch: a failing cmd BLOCKS, a passing cmd ALLOWS,
    a timeout BLOCKS, a command that cannot be STARTED blocks, and an
    empty-after-shlex value allows. ``block()`` returns the truthy sentinel
    ``1``; a clean run returns ``0``. Determinism: ``subprocess.run`` is
    monkeypatched (no real shell, no wall-clock timing) per the
    concurrency-test-must-be-deterministic lesson; the end-to-end cases drive
    the real Stop hook to prove the wiring.

    The spawn failure allowed until 2026-09-29, by design and pinned here. The
    design was borrowed from the pytest branch, where a spawn failure is an
    infrastructure fault that may pass; the override is configuration the
    operator wrote, so its spawn failure recurs on every Stop. On Windows the
    plain spelling of a Node command (``npm test``) never starts without a
    shell, and the gate the operator armed was green on every Stop with a
    failing test in the tree and no audit record to say it had not run."""

    @staticmethod
    def _load():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "stop_gate_env_override_under_test", str(HOOKS_DIR / "stop_gate.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["stop_gate_env_override_under_test"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_failing_env_cmd_blocks(self, monkeypatch, tmp_path):
        import types
        mod = self._load()
        monkeypatch.setattr(shutil, "which", lambda tok, *a, **k: "/resolved/" + tok)  # the stub below is the spawn; resolution is the chokepoint's and is tested in test_spawn_chokepoint.py
        monkeypatch.setattr(
            mod.subprocess, "run",
            lambda *a, **k: types.SimpleNamespace(
                returncode=1, stdout="boom-out", stderr="boom-err"),
        )
        rc = mod._run_command_gate(tmp_path, ("adopter test --fails",), source="env")
        assert rc == 1, "a non-zero override cmd must block (block() sentinel 1)"

    def test_passing_env_cmd_allows(self, monkeypatch, tmp_path):
        import types
        mod = self._load()
        monkeypatch.setattr(shutil, "which", lambda tok, *a, **k: "/resolved/" + tok)  # the stub below is the spawn; resolution is the chokepoint's and is tested in test_spawn_chokepoint.py
        monkeypatch.setattr(
            mod.subprocess, "run",
            lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="", stderr=""),
        )
        assert mod._run_command_gate(tmp_path, ("adopter test --passes",), source="env") == 0

    def test_timeout_blocks(self, monkeypatch, tmp_path):
        mod = self._load()
        monkeypatch.setattr(shutil, "which", lambda tok, *a, **k: "/resolved/" + tok)  # the stub below is the spawn; resolution is the chokepoint's and is tested in test_spawn_chokepoint.py

        def _timeout(*a, **k):
            raise mod.subprocess.TimeoutExpired(cmd="slow", timeout=1)

        monkeypatch.setattr(mod.subprocess, "run", _timeout)
        assert mod._run_command_gate(tmp_path, ("slow-cmd",), source="env") == 1, "timeout must block"

    def test_a_spawn_failure_blocks_and_names_the_command_and_a_remedy(
        self, monkeypatch, tmp_path, capsys,
    ):
        mod = self._load()
        monkeypatch.setattr(shutil, "which", lambda tok, *a, **k: "/resolved/" + tok)  # the stub below is the spawn; resolution is the chokepoint's and is tested in test_spawn_chokepoint.py

        def _boom(*a, **k):
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(mod.subprocess, "run", _boom)
        capsys.readouterr()
        rc = mod._run_command_gate(tmp_path, ("no-such-binary --flag value",), source="env")
        assert rc == 1, "an override that cannot be started must block, not allow"
        decision = json.loads(capsys.readouterr().out)
        assert decision["decision"] == "block"
        reason = decision["reason"]
        assert "no-such-binary --flag value" in reason, "the command as the operator wrote it"
        assert "`no-such-binary`" in reason, "the token that did not resolve"
        assert "FileNotFoundError" in reason
        assert "ESPALIER_STOP_GATE_TEST_CMD" in reason, "where the fix is made"
        assert reason.isascii(), "operator text is 7-bit ASCII"
        # The reader of this reason is as often the agent as the operator, and
        # the only shell the agent can reach is its own tool: an export there
        # never reaches a hook, so the agent would report the gate fixed and
        # the next session would block again.
        dont = reason.split("Don't:", 1)[1].split("Do:", 1)[0]
        assert "this session" in dont and "launch" in dont
        assert "operator" in reason.split("Do:", 1)[1]

    def test_a_spawn_failure_blocks_once_a_session_and_then_stands_aside(
        self, monkeypatch, tmp_path, capsys,
    ):
        """The command is read when Claude Code launches, so nothing done in
        the session can repair it. Blocking every Stop would return at Gate 1
        every turn, and the docs, review and blueprint gates behind it would
        not run again until the next launch: a louder failure than the one
        being fixed. Told once, recorded once, then out of the way."""
        mod = self._load()

        def _boom(*a, **k):
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(mod.subprocess, "run", _boom)
        capsys.readouterr()
        assert mod._run_command_gate(tmp_path, ("npm test",), source="env") == 1
        assert json.loads(capsys.readouterr().out)["decision"] == "block"

        assert mod._run_command_gate(tmp_path, ("npm test",), source="env") == 0
        later = capsys.readouterr()
        assert later.out == "", "a second decision in one session"
        assert "npm test" in later.err and "reported" in later.err, later.err

    def test_a_new_session_reports_it_again(self, monkeypatch, tmp_path, capsys):
        mod = self._load()

        def _boom(*a, **k):
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(mod.subprocess, "run", _boom)
        assert mod._run_command_gate(tmp_path, ("npm test",), source="env") == 1
        assert mod._run_command_gate(tmp_path, ("npm test",), source="env") == 0

        hooks = str(HOOKS_DIR)
        if hooks not in sys.path:
            sys.path.insert(0, hooks)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "session_start_flag_sweep_under_test", str(HOOKS_DIR / "session_start.py"))
        session_start = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = session_start
        spec.loader.exec_module(session_start)
        session_start._clean_state_flags(tmp_path, source="startup")

        capsys.readouterr()
        assert mod._run_command_gate(tmp_path, ("npm test",), source="env") == 1
        assert json.loads(capsys.readouterr().out)["decision"] == "block"

    @pytest.mark.parametrize("platform,expected", [
        ("nt", "npm.cmd"),
        ("posix", "PATH"),
    ])
    def test_the_remedy_is_the_platforms_own(self, monkeypatch, tmp_path, capsys,
                                             platform, expected):
        """On Windows the cause is nearly always a script shim, which only a
        shell finds; naming `npm.cmd` there and PATH elsewhere is the
        difference between a remedy and a restatement."""
        mod = self._load()

        def _boom(*a, **k):
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(mod.subprocess, "run", _boom)
        monkeypatch.setattr(mod, "_spawn_remedy_platform", lambda: platform)
        capsys.readouterr()
        assert mod._run_command_gate(tmp_path, ("npm test",), source="env") == 1
        assert expected in json.loads(capsys.readouterr().out)["reason"]

    def test_the_override_runs_at_the_repo_root(self, monkeypatch, tmp_path):
        import types
        mod = self._load()
        monkeypatch.setattr(shutil, "which", lambda tok, *a, **k: "/resolved/" + tok)  # the stub below is the spawn; resolution is the chokepoint's and is tested in test_spawn_chokepoint.py
        seen: dict = {}

        def _capture(*a, **k):
            seen.update(k)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(mod.subprocess, "run", _capture)
        assert mod._run_command_gate(tmp_path, ("adopter test",), source="env") == 0
        assert seen.get("cwd") == str(tmp_path), (
            "the override ran in the hook process's directory, so a relative "
            "test path resolves against wherever the session last changed to"
        )

    def test_empty_after_shlex_returns_clean(self, monkeypatch, tmp_path):
        mod = self._load()

        def _spy(*a, **k):
            raise AssertionError("subprocess.run must not run on an empty cmd")

        monkeypatch.setattr(mod.subprocess, "run", _spy)
        assert mod._run_command_gate(tmp_path, ("   ",), source="env") == 0

    def test_end_to_end_failing_override_blocks_under_full(self, tmp_path, monkeypatch):
        """The audit's exact gap: a failing override cmd under STOP_GATE=full
        drives the REAL Stop hook to a block decision (JSON on stdout, exit 0)."""
        _init_dirty_repo(tmp_path)
        monkeypatch.setenv(
            "ESPALIER_STOP_GATE_TEST_CMD",
            f'"{sys.executable}" -c "import sys; sys.exit(1)"',
        )
        result = _run(tmp_path, mode=None, stop_gate="full")
        assert result.returncode == 0, result.stderr
        output = json.loads(result.stdout)
        assert output["decision"] == "block"
        assert "ESPALIER_STOP_GATE_TEST_CMD" in output["reason"], (
            f"expected the override-sourced Gate 1 block, got {output!r}"
        )

    @staticmethod
    def _run_from(root: Path, cwd: Path, override: str) -> subprocess.CompletedProcess:
        """The real Stop hook, started in ``cwd`` with the project at ``root``.
        Maintenance mode is on so the docs and review gates stand down and the
        verdict is the test gate's alone; that gate still runs under it."""
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(root)
        env["ESPALIER_MAINTENANCE_MODE"] = "1"
        env["ESPALIER_STOP_GATE"] = "full"
        env["ESPALIER_STOP_GATE_TEST_CMD"] = override
        return subprocess.run(
            [sys.executable, str(HOOKS_DIR / "stop_gate.py")],
            input=json.dumps({}), capture_output=True, text=True, timeout=30,
            env=env, encoding="utf-8", cwd=str(cwd),
        )

    @pytest.mark.parametrize("passes_at_root,blocked", [(False, True), (True, False)],
                             ids=["fails-at-the-root", "passes-at-the-root"])
    def test_end_to_end_the_override_reads_the_root_from_a_subdirectory(
        self, tmp_path, passes_at_root, blocked,
    ):
        """The hook is started from a subdirectory, as it is after the session
        changed into one. The override's verdict depends on a marker that
        exists only at the root, so it says where it ran: the pair is a block
        and its mirror image, and before the root was passed both answers
        were the wrong way round."""
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
        (tmp_path / "root-marker").write_text("x", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        at_root, elsewhere = (0, 1) if passes_at_root else (1, 0)
        program = (
            "import pathlib,sys; "
            f"sys.exit({at_root} if pathlib.Path('root-marker').exists() else {elsewhere})"
        )
        result = self._run_from(tmp_path, sub, f'"{sys.executable}" -c "{program}"')
        assert result.returncode == 0, result.stderr
        decided = json.loads(result.stdout).get("decision") if result.stdout.strip() else None
        assert (decided == "block") is blocked, (result.stdout, result.stderr)

    def test_end_to_end_an_override_that_cannot_start_blocks(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
        result = self._run_from(tmp_path, tmp_path, "espalier-no-such-command-xyz --run")
        assert result.returncode == 0, result.stderr
        output = json.loads(result.stdout)
        assert output["decision"] == "block"
        assert "espalier-no-such-command-xyz" in output["reason"]

    def test_end_to_end_the_gates_behind_it_run_on_the_next_stop(self, tmp_path):
        """Two Stops of one session, neither a continuation, on a tree with
        enough source writes to owe a docs refresh. The first is held by the
        override that cannot start; the second must be held by the DOCS gate,
        which is only reachable if the test gate stood aside."""
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
        state = tmp_path / ".espalier-state"
        state.mkdir()
        (state / "write_count").write_text("12", encoding="utf-8")
        env = os.environ.copy()
        env.update(CLAUDE_PROJECT_DIR=str(tmp_path), ESPALIER_STOP_GATE="full",
                   ESPALIER_STOP_GATE_TEST_CMD="espalier-no-such-command-xyz")
        env.pop("ESPALIER_MAINTENANCE_MODE", None)

        def stop() -> dict:
            result = subprocess.run(
                [sys.executable, str(HOOKS_DIR / "stop_gate.py")],
                input=json.dumps({}), capture_output=True, text=True, timeout=30,
                env=env, encoding="utf-8", cwd=str(tmp_path),
            )
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)

        first, second = stop(), stop()
        assert first["decision"] == "block"
        assert "espalier-no-such-command-xyz" in first["reason"]
        assert second["decision"] == "block"
        assert "espalier-no-such-command-xyz" not in second["reason"], second["reason"]
        assert "docs" in second["reason"].lower(), second["reason"]

    def test_the_continuation_stop_is_let_through(self, tmp_path):
        """The block cannot hold a session: Claude Code re-fires Stop with
        ``stop_hook_active`` after a block, and the loop guard lets that one
        through before any gate runs."""
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
        env = os.environ.copy()
        env.update(CLAUDE_PROJECT_DIR=str(tmp_path), ESPALIER_STOP_GATE="full",
                   ESPALIER_STOP_GATE_TEST_CMD="espalier-no-such-command-xyz")
        env.pop("ESPALIER_MAINTENANCE_MODE", None)
        result = subprocess.run(
            [sys.executable, str(HOOKS_DIR / "stop_gate.py")],
            input=json.dumps({"stop_hook_active": True}), capture_output=True, text=True,
            timeout=30, env=env, encoding="utf-8", cwd=str(tmp_path),
        )
        assert result.returncode == 0, result.stderr
        assert '"block"' not in result.stdout, result.stdout


class TestResolveCoreTestsFingerprintAware:
    """TP-73 — Gate 1's test list must come from the fingerprint when present
    so a host repo runs ITS OWN tests, not the harness's three test files
    (which won't exist on a stranger's repo)."""

    def _load_stop_gate(self):
        """Load stop_gate.py as a module without going through subprocess so
        we can call ``_resolve_core_tests`` directly. Re-loaded per test so
        each call sees a fresh module state.

        TP-120b: registers the module in ``sys.modules`` before
        ``exec_module`` so the new ``@dataclass(frozen=True)``
        decorator on ``ResolvedTests`` can resolve forward references
        via ``sys.modules[cls.__module__]`` (Python 3.14 dataclasses).
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "stop_gate_under_test",
            str(HOOKS_DIR / "stop_gate.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["stop_gate_under_test"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_resolves_from_real_fingerprint_output(
        self, initialized_repo_root: Path, tmp_path: Path,
    ) -> None:
        """Pipe real ``analyze.detect_tests`` output into ``_resolve_core_tests``.

        TP-74 parity test: the fingerprint format written by
        ``espalier.analyze.detect_tests`` MUST be readable by
        ``_resolve_core_tests`` and produce runnable input. NO
        author-invented ``test_commands`` values — that's the
        de-circularization trap this test exists to escape.

        The prior fabricated test asserted
        ``result == ["tests/test_foo.py", "tests/test_bar.py"]`` —
        producer never wrote that shape (it writes shell strings like
        ``"pytest -q"``).
        """
        from espalier.analyze import detect_tests
        real_test_commands = detect_tests(initialized_repo_root)
        assert real_test_commands, (
            "fixture repo must produce non-empty test_commands; "
            "fixture pollution suspected"
        )
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "repo_fingerprint.json").write_text(
            json.dumps({"test_commands": real_test_commands}),
            encoding="utf-8",
        )
        mod = self._load_stop_gate()
        # TP-120b: canonical fingerprint (`["pytest -q"]`) has no
        # positional args; seed the harness defaults so the fallback
        # branch returns ok rather than dormant_no_paths.
        for p in mod._HARNESS_DEFAULT_TESTS:
            target = tmp_path / p
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# stub\n", encoding="utf-8")
        result = mod._resolve_core_tests(tmp_path)
        # TP-120b: return type is ResolvedTests; paths attribute holds
        # the list. Empty paths with non-ok status is the silent no-op
        # TP-74/TP-120b together prevent.
        assert result.status == "ok_harness_defaults", (
            f"expected ok_harness_defaults for fingerprinted repo; got {result.status!r}: "
            f"{result.note!r}"
        )
        assert result.paths, (
            "_resolve_core_tests must return non-empty paths for "
            "fingerprinted repo"
        )
        for entry in result.paths:
            assert not entry.startswith("-"), (
                f"_resolve_core_tests leaked a flag-shaped entry: {entry!r}"
            )
            assert " " not in entry, (
                f"_resolve_core_tests leaked a shell-string entry: {entry!r}"
            )

    def test_resolves_positional_path_from_fingerprint(self, tmp_path: Path) -> None:
        """B-4: a fingerprint whose pytest invocation names a positional test
        path must be EXTRACTED through the ``if positional`` branch of
        _resolve_core_tests, not silently dropped to harness defaults. The
        'real producer' sibling above only feeds the canonical ``pytest -q``
        (which correctly parses to ``[]`` → fallback), so a ``return []`` neuter
        of ``_parse_pytest_positional_args`` survives it. This drives a real
        positional through and pins the extraction — no harness defaults are
        seeded, so the neuter degrades to ``dormant_no_paths`` and reds here."""
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "repo_fingerprint.json").write_text(
            json.dumps({"test_commands": ["pytest tests/test_specific.py -q"]}),
            encoding="utf-8",
        )
        mod = self._load_stop_gate()
        result = mod._resolve_core_tests(tmp_path)
        assert result.status == "ok", (
            f"positional fingerprint must resolve ok, got "
            f"{result.status!r}: {result.note!r}"
        )
        assert result.paths == ["tests/test_specific.py"], (
            f"expected the fingerprint's positional path extracted, "
            f"got {result.paths!r}"
        )

    def test_falls_back_to_harness_defaults_when_fingerprint_absent(
        self, tmp_path: Path,
    ) -> None:
        """Self-host pre-analyze case: no fingerprint → harness defaults.
        TP-120b: defaults must exist in repo for status=ok; seed the
        stubs so the fallback path returns ok (sister-test to the
        dormant_no_paths case in test_stop_gate_dormancy.py)."""
        mod = self._load_stop_gate()
        for p in mod._HARNESS_DEFAULT_TESTS:
            target = tmp_path / p
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# stub\n", encoding="utf-8")
        result = mod._resolve_core_tests(tmp_path)
        assert result.status == "ok_harness_defaults", (
            f"expected ok_harness_defaults for self-host pre-analyze; got "
            f"{result.status!r}: {result.note!r}"
        )
        assert "tests/test_fingerprint.py" in result.paths
        assert "tests/test_hooks.py" in result.paths
        assert "tests/test_scanners.py" in result.paths

    def test_falls_back_when_fingerprint_lacks_test_commands(
        self, tmp_path: Path,
    ) -> None:
        """Malformed fingerprint (missing ``test_commands`` key) → defaults.
        TP-120b: seed default stubs so the fallback returns ok."""
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "repo_fingerprint.json").write_text(
            json.dumps({"language": "python"}),
            encoding="utf-8",
        )
        mod = self._load_stop_gate()
        for p in mod._HARNESS_DEFAULT_TESTS:
            target = tmp_path / p
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# stub\n", encoding="utf-8")
        result = mod._resolve_core_tests(tmp_path)
        assert result.status == "ok_harness_defaults"
        assert "tests/test_fingerprint.py" in result.paths

    def test_reads_a_latin1_fingerprint_instead_of_crashing(self, tmp_path: Path) -> None:
        """Ledger DEF-829: the fingerprint re-saved in a Windows code page.
        ``UnicodeDecodeError`` is a ``ValueError``, so ``except OSError`` let
        it past and the Stop gate's fail-closed crash guard blocked every
        Stop under ``ESPALIER_STOP_GATE=full``. The bytes now go to
        ``load_json_dict_safe``, which decodes tolerantly."""
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "repo_fingerprint.json").write_bytes(
            b'{"test_commands": ["pytest -q"], "note": "caf\xe9"}'
        )
        mod = self._load_stop_gate()
        assert mod._read_fingerprint_test_commands(tmp_path) == ["pytest -q"]

    def test_scan_clean_advisory_reads_a_latin1_telemetry_line(
        self, tmp_path: Path, capsys,
    ) -> None:
        """The sibling reader in the same hook: a scan-telemetry line that is
        not UTF-8 is read with a replacement character, never a crash of the
        opt-in advisory (stderr-only, returns None)."""
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "scan_telemetry.jsonl").write_bytes(
            b'{"run_id": "a", "scanner": "x", "count": 1, "note": "caf\xe9"}\n'
            b'{"run_id": "b", "scanner": "x", "count": 2}\n'
        )
        mod = self._load_stop_gate()
        assert mod._gate_scan_clean(tmp_path) is None
        assert "Traceback" not in capsys.readouterr().err

    def test_falls_back_when_fingerprint_is_malformed_json(
        self, tmp_path: Path,
    ) -> None:
        """Corrupt fingerprint → harness defaults (no crash). TP-120b:
        seed default stubs so the fallback returns ok."""
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "repo_fingerprint.json").write_text(
            "{ not valid json ",
            encoding="utf-8",
        )
        mod = self._load_stop_gate()
        for p in mod._HARNESS_DEFAULT_TESTS:
            target = tmp_path / p
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# stub\n", encoding="utf-8")
        result = mod._resolve_core_tests(tmp_path)
        assert result.status == "ok_harness_defaults"
        assert result.paths == [
            "tests/test_fingerprint.py",
            "tests/test_hooks.py",
            "tests/test_scanners.py",
            "tests/test_scanner_magic_depth.py",
        ]

    @pytest.mark.parametrize("cmd,expected,leak_value", [
        # BC-041b: marker value `security` must not be kept as positional.
        # Pre-fix, the naive `not tok.startswith("-")` filter dropped `-m`
        # but kept `security`; Gate 1 then ran `pytest security tests/...`
        # which errored "file not found: security".
        (
            "pytest -m security --tb=short tests/test_security.py",
            ["tests/test_security.py"],
            "security",
        ),
        # `-k` keyword filter value must drop.
        (
            "pytest -k test_foo tests/integration/",
            ["tests/integration/"],
            "test_foo",
        ),
        # `-p` plugin name must drop. Note `no:cacheprovider` is a
        # PLUGIN spec, not a path -- pre-fix Gate 1 would have
        # interpreted it as a positional and pytest would have errored.
        (
            "pytest -p no:cacheprovider tests/test_freshness.py",
            ["tests/test_freshness.py"],
            "no:cacheprovider",
        ),
        # `-o` ini override + `--override-ini` long form (both shapes).
        (
            "pytest -o cache_dir=/tmp/c tests/test_x.py",
            ["tests/test_x.py"],
            "cache_dir=/tmp/c",
        ),
        (
            "pytest --override-ini foo=bar tests/test_y.py",
            ["tests/test_y.py"],
            "foo=bar",
        ),
        # `-W` warning filter value must drop.
        (
            "pytest -W error::DeprecationWarning tests/test_z.py",
            ["tests/test_z.py"],
            "error::DeprecationWarning",
        ),
        # The separated-arg family, measured LEAKING at HEAD. The module comment
        # framed these as a FUTURE risk mitigated by human review at a pytest
        # bump; they leak today. `-n` is the pointed one: pytest-xdist is a
        # declared dev dep and CLAUDE.md's own documented invocation is
        # `pytest -n auto`, which fed `auto` to pytest as a path.
        ("pytest -n auto -q tests/", ["tests/"], "auto"),
        ("pytest --basetemp /tmp/x tests/", ["tests/"], "/tmp/x"),
        ("pytest --junitxml out.xml tests/", ["tests/"], "out.xml"),
        ("pytest --maxfail 3 tests/", ["tests/"], "3"),
        ("pytest --rootdir /tmp tests/", ["tests/"], "/tmp"),
        ("pytest --tb short tests/", ["tests/"], "short"),
        # The sharpest: leaking a --deselect selector INVERTS deselect into
        # select. Every other miss degrades to a loud "file or directory not
        # found"; this one produces a WRONG RESULT quietly.
        ("pytest --deselect tests/a.py::t tests/", ["tests/"], "tests/a.py::t"),
    ])
    def test_pytest_flag_argument_not_leaked_as_positional(
        self, tmp_path: Path, cmd: str, expected: list[str], leak_value: str,
    ) -> None:
        """BC-041b: pytest flags that consume the NEXT token must not leak
        their argument as a positional path.

        Pre-fix shape (Shape 7 of v0.7.1 cluster review): `_parse_pytest_positional_args`
        used `tok for tok in rest if not tok.startswith('-')` -- correctly
        dropped the flag tokens but kept the values that followed them
        (`security` after `-m`, `test_foo` after `-k`, etc.). Gate 1 then
        ran pytest against those literal strings, producing
        `ERROR: file or directory not found: <value>`.

        This is the second de-circularization recipe walk at the same
        site (BC-041 was TP-74's shell-strings-as-paths; BC-041b is
        flag-values-as-paths). The parser must use a state machine that
        tracks which flags consume the next token.
        """
        (tmp_path / "reports").mkdir()
        (tmp_path / "reports" / "repo_fingerprint.json").write_text(
            json.dumps({"test_commands": [cmd]}),
            encoding="utf-8",
        )
        mod = self._load_stop_gate()
        result = mod._resolve_core_tests(tmp_path)
        # TP-120b: ResolvedTests.paths holds the parsed positional list.
        assert result.status == "ok"
        assert result.paths == expected, (
            f"flag-value leak: {leak_value!r} should NOT appear in "
            f"positional args. Parsed {result.paths!r} from {cmd!r}; "
            f"expected {expected!r}."
        )
        assert leak_value not in result.paths, (
            f"flag-value leak: {leak_value!r} appeared as a positional "
            f"arg. The parser must skip the token following "
            f"pytest flags in _PYTEST_FLAGS_WITH_ARG."
        )


class TestGate2ReliefRequiresEvidence:
    """DEF-495 (second half): Gate 2 must relieve on WORK, not on attendance.

    `subagent_stop` wrote the `docs_refreshed` flag on agent COMPLETION with no
    evidence check, and `_gate_docs_refresh` relieved on mere file existence. So
    a docs-maintainer that ran and wrote nothing — which is exactly what happened
    while `docs/` was PreToolUse-denied — cleared the gate on retry with zero docs
    written. The gate was green because it could not fail.
    """

    @staticmethod
    def _load():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "stop_gate_gate2_evidence_under_test", str(HOOKS_DIR / "stop_gate.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["stop_gate_gate2_evidence_under_test"] = mod
        spec.loader.exec_module(mod)
        return mod

    def _flag(self, repo: Path, payload: str) -> None:
        state = repo / ".espalier-state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "docs_refreshed").write_text(payload, encoding="utf-8")

    def test_flag_with_changed_docs_relieves(self, tmp_path):
        mod = self._load()
        self._flag(tmp_path, json.dumps({"changed_docs": ["docs/CONVENTIONS.md"]}))
        assert mod._gate_docs_refresh(tmp_path, write_count=25) == 0

    def test_flag_recording_zero_changes_does_not_relieve(self, tmp_path):
        """Earn-the-red: pre-fix this returned 0 (relieved) on an empty flag."""
        mod = self._load()
        self._flag(tmp_path, json.dumps({"changed_docs": []}))
        assert mod._gate_docs_refresh(tmp_path, write_count=25) != 0

    def test_legacy_empty_flag_does_not_relieve(self, tmp_path):
        """The pre-fix flag was a zero-byte file. It carries no evidence, so it
        must not relieve — per-session flags are cleaned at SessionStart, so no
        real session carries one across the change."""
        mod = self._load()
        self._flag(tmp_path, "")
        assert mod._gate_docs_refresh(tmp_path, write_count=25) != 0

    def test_below_threshold_still_passes_regardless_of_flag(self, tmp_path):
        mod = self._load()
        assert mod._gate_docs_refresh(tmp_path, write_count=3) == 0


class TestSpawnChokepointInTheStopGate:
    """The three gate spawns route through ``_hook_utils.spawn_checked`` (the
    remaining half of DEF-948): the override starts the RESOLVED program (so
    ``npm`` on Windows starts ``npm.cmd``), and the plain pytest branch allows
    a spawn failure with a record instead of a silent green."""

    @staticmethod
    def _load():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "stop_gate_chokepoint_under_test", str(HOOKS_DIR / "stop_gate.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["stop_gate_chokepoint_under_test"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_the_override_starts_the_resolved_shim_not_the_bare_token(self, monkeypatch, tmp_path):
        import types
        mod = self._load()
        seen: dict = {}

        def _capture(argv, **kw):
            seen["argv"] = list(argv)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(mod.subprocess, "run", _capture)
        monkeypatch.setattr(shutil, "which", lambda tok, *a, **k: r"C:\node\npm.cmd" if tok == "npm" else None)
        assert mod._run_command_gate(tmp_path, ("npm test",), source="env") == 0
        assert seen["argv"] == [r"C:\node\npm.cmd", "test"], (
            "mutation: a gate that bypasses the resolver starts the bare token and never finds the shim"
        )

    def test_an_unresolvable_override_says_it_did_not_resolve(self, monkeypatch, tmp_path, capsys):
        mod = self._load()
        monkeypatch.setattr(shutil, "which", lambda tok, *a, **k: None)
        capsys.readouterr()
        assert mod._run_command_gate(tmp_path, ("espalier-no-such-command-xyz --run",), source="env") == 1
        reason = json.loads(capsys.readouterr().out)["reason"]
        assert "`espalier-no-such-command-xyz` did not resolve to a program" in reason
        assert "Unresolved" in reason

    def test_the_plain_pytest_branch_allows_and_records_a_spawn_failure(self, monkeypatch, tmp_path, capsys):
        import types
        mod = self._load()
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_t.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
        monkeypatch.setattr(
            mod, "_resolve_core_tests",
            lambda root: types.SimpleNamespace(status="ok", note="", env_cmd=None, paths=["tests/test_t.py"]),
        )
        monkeypatch.setattr(mod._hook_utils, "resolve_program", lambda token, root=None: None)
        monkeypatch.setattr(mod._hook_utils, "_SAID_THIS_PROCESS", set())
        audit = tmp_path / "audit"
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(audit))
        capsys.readouterr()
        assert mod._gate_pytest(tmp_path) == 0, "an infrastructure fault allows the Stop"
        err = capsys.readouterr().err
        assert "[stop_gate] Gate 1 skipped: pytest could not start (Unresolved" in err, err
        lines = [ln for log in audit.glob("*.log") for ln in log.read_text(encoding="utf-8").splitlines()]
        assert sum(1 for ln in lines if '"stop_failed_open_pytest_spawn"' in ln) == 1, (
            "mutation: drop the say_once and the fault is a silent green"
        )


class TestAnInterpreterWithoutPytestIsAFaultNotAFailure:
    _load = staticmethod(TestSpawnChokepointInTheStopGate._load)

    def test_no_module_named_pytest_allows_and_records_once(self, monkeypatch, tmp_path, capsys):
        """`python -m pytest` with no pytest installed exits 1, the code a
        failing suite exits with, so Gate 1 blocked every Stop. Reachable when
        init wires the launcher's system Python (`py -3`) while the project's
        pytest lives in a virtualenv (the C69 lane prefers the launcher to a
        venv-only name)."""
        import subprocess as sp
        import types
        mod = self._load()
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_t.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
        monkeypatch.setattr(
            mod, "_resolve_core_tests",
            lambda root: types.SimpleNamespace(status="ok", note="", env_cmd=None, paths=["tests/test_t.py"]),
        )
        monkeypatch.setattr(
            mod._hook_utils, "spawn_checked",
            lambda argv, **kw: sp.CompletedProcess(argv, 1, "", "/usr/bin/python3: No module named pytest\n"),
        )
        monkeypatch.setattr(mod._hook_utils, "_SAID_THIS_PROCESS", set())
        audit = tmp_path / "audit"
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(audit))
        capsys.readouterr()
        assert mod._gate_pytest(tmp_path) == 0, "a missing pytest allows the Stop"
        captured = capsys.readouterr()
        assert "has no pytest" in captured.err, captured.err
        assert "decision" not in captured.out, captured.out
        lines = [ln for log in audit.glob("*.log") for ln in log.read_text(encoding="utf-8").splitlines()]
        assert sum(1 for ln in lines if '"stop_failed_open_pytest_missing"' in ln) == 1, (
            "mutation: drop the say_once and the fault is a silent green"
        )

    def test_a_real_failure_still_blocks(self, monkeypatch, tmp_path, capsys):
        import subprocess as sp
        import types
        mod = self._load()
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_t.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
        monkeypatch.setattr(
            mod, "_resolve_core_tests",
            lambda root: types.SimpleNamespace(status="ok", note="", env_cmd=None, paths=["tests/test_t.py"]),
        )
        monkeypatch.setattr(
            mod._hook_utils, "spawn_checked",
            lambda argv, **kw: sp.CompletedProcess(argv, 1, "1 failed\n", ""),
        )
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        assert mod._gate_pytest(tmp_path) != 0, "a failing suite still blocks"


class TestUnbalancedQuotesBlockOnce:
    def test_a_command_that_cannot_be_split_blocks_once_then_stands_aside(self, monkeypatch, tmp_path, capsys):
        """The 2-A review drove three Stops on `npm "unbalanced`: three blocks,
        no flag -- the gates behind Gate 1 would never have run again this
        session. It takes the spawn failure's once-a-session branch now, with
        the quoting remedy, not the PATH one."""
        mod = TestSpawnChokepointInTheStopGate._load()
        capsys.readouterr()
        assert mod._run_command_gate(tmp_path, ('npm "unbalanced',), source="env") == 1
        reason = json.loads(capsys.readouterr().out)["reason"]
        assert "could not be split (unbalanced quotes)" in reason
        assert "fix the quoting where the variable is set" in reason
        assert "on PATH" not in reason.split("Do:", 1)[1]
        assert (tmp_path / ".espalier-state" / mod.GATE1_SPAWN_FAILURE_REPORTED_FLAG).is_file()
        assert mod._run_command_gate(tmp_path, ('npm "unbalanced',), source="env") == 0
        assert "reported earlier this session" in capsys.readouterr().err


# ─── Gate 5: the handoff gate ─────────────────────────────────────────────────

def _git(cwd: Path, *args: str) -> str:
    from tests._git_oracle import _git_env

    result = subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
        encoding="utf-8", env=_git_env(),
    )
    return result.stdout.strip()


def _write_plan(root: Path, status: str, *, task: str = "TP-fixture: the lane",
                created: str = "2026-10-24T00:00:00+00:00") -> None:
    step_status = "passed" if status == "complete" else "running"
    (root / "cc" / "execution_plan.json").write_text(json.dumps({
        "task": task, "created": created, "status": status,
        "steps": [{"title": "the step", "status": step_status}],
    }), encoding="utf-8")


def _commit(root: Path, name: str) -> None:
    (root / f"{name}.txt").write_text(name, encoding="utf-8")
    _git(root, "add", f"{name}.txt")
    _git(root, "commit", "-q", "-m", name)


def _lane_repo(tmp_path: Path, *, ahead: int = 1, handoff_push: str | None = "true",
               plan_status: str | None = "complete", branch: str = "lane/the-fixture",
               push_lane: bool = False) -> Path:
    """A checkout with a bare origin beside it: ``main`` pushed with an
    upstream and ``origin/HEAD`` set, then ``branch`` holding ``ahead``
    commits origin does not. ``push_lane`` pushes the lane with an upstream
    before those commits, so the lane's own upstream is what the gate reads.
    ``plan_status`` None writes no plan."""
    from tests._git_oracle import _git_env
    from tests._quiet_git import NO_BACKGROUND_GIT

    origin = tmp_path / "origin.git"
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True,
                   capture_output=True, env=_git_env())
    _git(root, "init", "-q")
    for key, value in NO_BACKGROUND_GIT:
        _git(root, "config", key, value)
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "fixture")
    _git(root, "checkout", "-q", "-b", "main")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "remote", "add", "origin", str(origin))
    _git(root, "push", "-q", "-u", "origin", "main")
    _git(root, "remote", "set-head", "origin", "main")
    if branch != "main":
        _git(root, "checkout", "-q", "-b", branch)
    if push_lane:
        _git(root, "push", "-q", "-u", "origin", branch)
    for i in range(ahead):
        _commit(root, f"c{i}")
    if handoff_push is not None:
        (root / "espalier.toml").write_text(f"handoff_push = {handoff_push}\n", encoding="utf-8")
    (root / "cc").mkdir()
    if plan_status is not None:
        _write_plan(root, plan_status)
    return root


def _audit_rows(audit_dir: Path, event_type: str) -> list[dict]:
    return [
        json.loads(ln) for log in audit_dir.glob("*.log")
        for ln in log.read_text(encoding="utf-8").splitlines()
        if f'"{event_type}"' in ln
    ]


def _head(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD")


class TestTheHandoffGate:
    """Gate 5, the handoff gate (live since 2026-10-24; TP-70 retired an earlier,
    different fifth gate on 2026-05-18): nothing in flight -- no plan in
    progress, no tracked edit -- and the branch holds commits its upstream does
    not, made in this session, on a repository whose espalier.toml sets
    ``handoff_push = true``, blocks the Stop once per commit and names /handoff.
    "This session" is the flag SessionStart seeds with HEAD: a HEAD already
    judged, or already there when the session began, is passed over. The
    measured cause: a lane finished at 05:13 EDT and left for the operator's
    /handoff sat unpushed, unrowed and claimed for eleven hours, and the next
    session handed it off from a cold context (2026-10-24)."""

    @staticmethod
    def _load():
        import importlib.util

        if str(HOOKS_DIR) not in sys.path:
            sys.path.insert(0, str(HOOKS_DIR))
        name = "stop_gate_handoff_under_test"
        spec = importlib.util.spec_from_file_location(name, str(HOOKS_DIR / "stop_gate.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    @staticmethod
    def _fresh_voice(mod, root: Path) -> None:
        """``say_once`` speaks once per process and per session: reset both so a
        test owns its own voice."""
        mod._hook_utils._SAID_THIS_PROCESS.clear()
        for once in (root / ".espalier-state").glob("once_*"):
            once.unlink()

    def test_a_committed_unpushed_lane_blocks_once_and_names_the_handoff(
        self, tmp_path, monkeypatch, capsys,
    ):
        root = _lane_repo(tmp_path, ahead=2)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        mod = self._load()
        assert mod._gate_handoff(root) == 1
        out = capsys.readouterr()
        assert out.err == "", out.err
        reason = json.loads(out.out)["reason"]
        assert "/handoff" in reason
        assert "lane/the-fixture holds 2 commits that origin/main does not" in reason
        assert "must be handed off now" in reason
        assert "the plan `TP-fixture: the lane` is complete" in reason
        assert "opening the pull request with auto-merge armed" in reason
        assert "Don't:" in reason and "Do:" in reason
        flag = root / ".espalier-state" / mod.HANDOFF_GATE_FLAG
        assert flag.read_text(encoding="utf-8").strip() == _head(root)
        records = _audit_rows(tmp_path / "audit", "stop_blocked_handoff")
        assert len(records) == 1
        assert records[0]["details"] == {"gate": 5, "rule": "GATE_HANDOFF_OWED", "ahead": 2}
        assert "lane/the-fixture" not in json.dumps(records[0])
        # Once per commit: the next Stop of the session passes and writes nothing.
        assert mod._gate_handoff(root) == 0
        assert capsys.readouterr().out == ""
        assert len(_audit_rows(tmp_path / "audit", "stop_blocked_handoff")) == 1

    def test_a_new_commit_speaks_again(self, tmp_path, monkeypatch, capsys):
        """The handoff's own row commit moves HEAD: a push that then fails leaves
        a lane the gate speaks about again at the next Stop."""
        root = _lane_repo(tmp_path, ahead=1)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        mod = self._load()
        assert mod._gate_handoff(root) == 1
        assert mod._gate_handoff(root) == 0
        _commit(root, "the-row")
        assert mod._gate_handoff(root) == 1
        decisions = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert [d["decision"] for d in decisions] == ["block", "block"]
        assert "2 commits" in decisions[1]["reason"]

    def test_a_held_handoff_marker_at_head_lets_the_stop_through(self, tmp_path, monkeypatch, capsys):
        """DEF-4057 (both reviews, 2026-10-30): the handoff ran to its end and
        its push was held by a red base, so the ship driver armed the own-clear
        marker for this HEAD and told the next window to land the lane. A block
        here would ask for a handoff that only writes a second row and re-arms,
        and the clear waits on the very Stop it blocks. Dies to: a marker at
        another head letting the Stop through (an older handoff's), or a torn
        marker raising instead of reading as not armed."""
        root = _lane_repo(tmp_path, ahead=1)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        mod = self._load()
        state = root / ".espalier-state"
        state.mkdir(exist_ok=True)
        marker = state / mod.OWN_CLEAR_MARKER
        marker.write_text(json.dumps({"state": "armed", "head": "0" * 40, "landed": False}), encoding="utf-8")
        assert mod._gate_handoff(root) == 1   # another head's marker: this lane is still owed
        _commit(root, "the-row")
        marker.write_text(json.dumps({"state": "armed", "head": _head(root), "landed": False}), encoding="utf-8")
        assert mod._gate_handoff(root) == 0
        assert (state / mod.HANDOFF_GATE_FLAG).read_text(encoding="utf-8").strip() == _head(root)
        _commit(root, "another")
        marker.write_text("{not json", encoding="utf-8")
        assert mod._gate_handoff(root) == 1
        decisions = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert [d["decision"] for d in decisions] == ["block", "block"]

    def test_the_head_a_session_began_on_is_never_spoken_about(self, tmp_path, monkeypatch, capsys):
        """SessionStart seeds the flag with HEAD: a lane an earlier session left
        unpushed is the banner's to name, never a block into a cold context."""
        root = _lane_repo(tmp_path, ahead=1)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        mod = self._load()
        state = root / ".espalier-state"
        state.mkdir()
        (state / mod.HANDOFF_GATE_FLAG).write_text(_head(root) + "\n", encoding="utf-8")
        assert mod._gate_handoff(root) == 0
        out = capsys.readouterr()
        assert out.out == "" and out.err == ""
        assert not (tmp_path / "audit").exists() or not _audit_rows(tmp_path / "audit", "stop_blocked_handoff")

    def test_nothing_unpushed_passes_and_remembers_the_head(self, tmp_path, monkeypatch, capsys):
        root = _lane_repo(tmp_path, ahead=0)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        mod = self._load()
        assert mod._gate_handoff(root) == 0
        out = capsys.readouterr()
        assert out.out == "" and out.err == ""
        flag = root / ".espalier-state" / mod.HANDOFF_GATE_FLAG
        assert flag.read_text(encoding="utf-8").strip() == _head(root)
        assert not (tmp_path / "audit").exists() or not _audit_rows(tmp_path / "audit", "stop_blocked_handoff")

    def test_an_edit_in_flight_passes_and_writes_nothing(self, tmp_path, monkeypatch, capsys):
        """A modified tracked file, or one staged, is work in flight: the pack
        flow's reviewers and tier run on a dirty tree before the commit, and the
        gate must not send the collaborator to push mid-flow."""
        root = _lane_repo(tmp_path, ahead=1)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        mod = self._load()
        flag = root / ".espalier-state" / mod.HANDOFF_GATE_FLAG
        (root / "README.md").write_text("base\nedited\n", encoding="utf-8")
        assert mod._gate_handoff(root) == 0
        assert not flag.exists()
        (root / "README.md").write_text("base\n", encoding="utf-8")
        (root / "staged.txt").write_text("s", encoding="utf-8")
        _git(root, "add", "staged.txt")
        assert mod._gate_handoff(root) == 0
        assert not flag.exists()
        _git(root, "rm", "-q", "--cached", "staged.txt")
        (root / "staged.txt").unlink()
        assert capsys.readouterr().out == ""
        assert mod._gate_handoff(root) == 1

    def test_an_untracked_file_is_not_work_in_flight(self, tmp_path, monkeypatch, capsys):
        root = _lane_repo(tmp_path, ahead=1)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        (root / "scratch-note.md").write_text("beside the lane\n", encoding="utf-8")
        mod = self._load()
        assert mod._gate_handoff(root) == 1
        assert "1 commit" in json.loads(capsys.readouterr().out)["reason"]

    def test_a_plan_in_progress_passes_and_writes_nothing(self, tmp_path, monkeypatch, capsys):
        root = _lane_repo(tmp_path, ahead=1, plan_status="in_progress")
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        mod = self._load()
        assert mod._gate_handoff(root) == 0
        assert capsys.readouterr().out == ""
        assert not (root / ".espalier-state" / mod.HANDOFF_GATE_FLAG).exists()

    @pytest.mark.parametrize("status", ["planned", "cancelled", None])
    def test_no_plan_in_progress_still_speaks(self, tmp_path, monkeypatch, capsys, status):
        """A committed lane with no plan at all (a free-hand lane under
        maintenance mode) is as unpushed as one with a complete plan."""
        root = _lane_repo(tmp_path, ahead=1, plan_status=status)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        mod = self._load()
        assert mod._gate_handoff(root) == 1
        assert "no plan is in progress" in json.loads(capsys.readouterr().out)["reason"]

    @pytest.mark.parametrize("setting", ["false", None, "maybe"])
    def test_a_repository_whose_handoff_does_not_push_has_no_gate(
        self, tmp_path, monkeypatch, capsys, setting,
    ):
        root = _lane_repo(tmp_path, ahead=1, handoff_push=setting)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        mod = self._load()
        assert mod._gate_handoff(root) == 0
        assert capsys.readouterr().out == ""
        # Judged: the next Stop at this HEAD stops at the flag.
        flag = root / ".espalier-state" / mod.HANDOFF_GATE_FLAG
        assert flag.read_text(encoding="utf-8").strip() == _head(root)

    def test_a_pushed_lane_counts_only_what_its_upstream_lacks(self, tmp_path, monkeypatch, capsys):
        root = _lane_repo(tmp_path, ahead=1, push_lane=True)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        mod = self._load()
        assert mod._gate_handoff(root) == 1
        reason = json.loads(capsys.readouterr().out)["reason"]
        assert "lane/the-fixture holds 1 commit that origin/lane/the-fixture does not" in reason
        assert "onto its open pull request" in reason
        _git(root, "push", "-q", "origin", "lane/the-fixture")
        assert mod._gate_handoff(root) == 0            # the same HEAD, judged
        _commit(root, "c-after")
        _git(root, "push", "-q", "origin", "lane/the-fixture")
        assert mod._gate_handoff(root) == 0            # a new HEAD with nothing owed
        assert capsys.readouterr().out == ""
        flag = root / ".espalier-state" / mod.HANDOFF_GATE_FLAG
        assert flag.read_text(encoding="utf-8").strip() == _head(root)

    def test_the_default_branch_ahead_of_origin_blocks_too(self, tmp_path, monkeypatch, capsys):
        # The ship driver's `lane` verb moves these onto a lane at the push, so
        # work committed on main is as unpushed as a lane's.
        root = _lane_repo(tmp_path, ahead=1, branch="main")
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        mod = self._load()
        assert mod._gate_handoff(root) == 1
        assert "main holds 1 commit that origin/main does not" in json.loads(capsys.readouterr().out)["reason"]

    def test_a_detached_head_passes(self, tmp_path, monkeypatch, capsys):
        root = _lane_repo(tmp_path, ahead=1)
        _git(root, "checkout", "-q", "--detach")
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        mod = self._load()
        assert mod._gate_handoff(root) == 0
        assert capsys.readouterr().out == ""

    def test_no_origin_head_falls_back_to_the_default_branch_name(self, tmp_path, monkeypatch, capsys):
        """A clone made with `git remote add` and a push never sets origin/HEAD;
        the lane is then measured against origin/main."""
        root = _lane_repo(tmp_path, ahead=1)
        _git(root, "remote", "set-head", "origin", "-d")
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        mod = self._load()
        assert mod._gate_handoff(root) == 1
        assert "that origin/main does not" in json.loads(capsys.readouterr().out)["reason"]

    def test_a_checkout_with_nothing_to_compare_against_passes(self, tmp_path, monkeypatch, capsys):
        root = _lane_repo(tmp_path, ahead=1)
        _git(root, "remote", "remove", "origin")
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        mod = self._load()
        assert mod._gate_handoff(root) == 0
        out = capsys.readouterr()
        assert out.out == "" and out.err == ""

    def test_a_git_that_cannot_start_allows_and_speaks_once(self, tmp_path, monkeypatch, capsys):
        root = _lane_repo(tmp_path, ahead=1)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        mod = self._load()
        self._fresh_voice(mod, root)
        monkeypatch.setattr(
            mod._hook_utils, "spawn_checked",
            lambda argv, **kw: mod._hook_utils.SpawnFailure(tuple(argv), "Unresolved", None),
        )
        assert mod._gate_handoff(root) == 0
        out = capsys.readouterr()
        assert out.out == ""
        assert "[stop_gate]" in out.err and "handoff gate" in out.err
        assert len(_audit_rows(tmp_path / "audit", "stop_failed_open_handoff_git")) == 1
        assert mod._gate_handoff(root) == 0
        assert capsys.readouterr().err == ""

    def test_a_missing_driver_is_silent_and_a_faulty_one_speaks_once(self, tmp_path, monkeypatch, capsys):
        """Four driver states. No tools/cc/ship.py: no handoff push to owe, so no
        gate and nothing said. A driver importing a sibling the tree lacks, a
        module elsewhere answering to the name, and a driver predating the
        reader or failing its read: the gate stands down and says so once."""
        import types

        root = _lane_repo(tmp_path, ahead=1)
        monkeypatch.setenv("ESPALIER_AUDIT_DIR", str(tmp_path / "audit"))
        mod = self._load()
        flag = root / ".espalier-state" / mod.HANDOFF_GATE_FLAG
        real = str(HOOKS_DIR.parent / "ship.py")

        def arm(module) -> list[dict]:
            self._fresh_voice(mod, root)
            flag.unlink(missing_ok=True)
            monkeypatch.setitem(sys.modules, "ship", module)
            assert mod._gate_handoff(root) == 0
            assert capsys.readouterr().out == ""
            return _audit_rows(tmp_path / "audit", "stop_failed_open_handoff_driver")

        before = len(arm(None))                       # no driver: silent
        assert before == 0

        shadow = types.ModuleType("ship")             # another module answers
        assert len(arm(shadow)) == 1
        assert _audit_rows(tmp_path / "audit", "stop_failed_open_handoff_driver")[-1]["details"]["fault"] == "ShadowedDriver"

        old = types.ModuleType("ship")                # a driver before the reader
        old.__file__ = real
        assert len(arm(old)) == 2
        assert _audit_rows(tmp_path / "audit", "stop_failed_open_handoff_driver")[-1]["details"]["fault"] == "NoHandoffPushSetting"

        def _fails(root_):
            raise RuntimeError("the read failed")

        faulty = types.ModuleType("ship")             # a read that fails
        faulty.__file__ = real
        faulty.handoff_push_setting = _fails
        assert len(arm(faulty)) == 3
        assert _audit_rows(tmp_path / "audit", "stop_failed_open_handoff_driver")[-1]["details"]["fault"] == "RuntimeError"
        assert "[stop_gate]" not in capsys.readouterr().out

    def test_maintenance_mode_does_not_lift_it(self, tmp_path):
        """The one that would have caught the measured case: the overnight
        session ran under ESPALIER_MAINTENANCE_MODE=1. Gates 2 and 3 are the
        friction the flag lifts; continuity is not friction."""
        root = _lane_repo(tmp_path, ahead=1)
        env = os.environ.copy()
        env.update(CLAUDE_PROJECT_DIR=str(root), ESPALIER_MAINTENANCE_MODE="1",
                   ESPALIER_AUDIT_DIR=str(tmp_path / "audit"))
        env.pop("ESPALIER_STOP_GATE", None)

        def stop(payload: dict) -> str:
            result = subprocess.run(
                [sys.executable, str(HOOKS_DIR / "stop_gate.py")],
                input=json.dumps(payload), capture_output=True, text=True, timeout=30,
                env=env, encoding="utf-8", cwd=str(root),
            )
            assert result.returncode == 0, result.stderr
            return result.stdout

        first = json.loads(stop({}))
        assert first["decision"] == "block"
        assert "/handoff" in first["reason"] and "lane/the-fixture" in first["reason"]
        assert _audit_rows(tmp_path / "audit", "stop_blocked_handoff")
        assert '"block"' not in stop({}), "the same HEAD is not spoken about twice"

    def test_the_continuation_stop_runs_the_handoff_gate_alone(self, tmp_path):
        """Outside maintenance mode a long turn's first Stop is held by the docs
        gate; the continuation Stop carries the loop signal, which lets Gates 1
        to 4 go, and the handoff gate alone still speaks -- once -- so the lane
        is told in the same turn, not at the operator's next prompt."""
        root = _lane_repo(tmp_path, ahead=1)
        state = root / ".espalier-state"
        state.mkdir()
        (state / "write_count").write_text("12", encoding="utf-8")
        env = os.environ.copy()
        env.update(CLAUDE_PROJECT_DIR=str(root), ESPALIER_AUDIT_DIR=str(tmp_path / "audit"))
        env.pop("ESPALIER_MAINTENANCE_MODE", None)
        env.pop("ESPALIER_STOP_GATE", None)

        def stop(payload: dict) -> str:
            result = subprocess.run(
                [sys.executable, str(HOOKS_DIR / "stop_gate.py")],
                input=json.dumps(payload), capture_output=True, text=True, timeout=30,
                env=env, encoding="utf-8", cwd=str(root),
            )
            assert result.returncode == 0, result.stderr
            return result.stdout

        first = json.loads(stop({}))
        assert first["decision"] == "block" and "docs" in first["reason"].lower()
        second = json.loads(stop({"stop_hook_active": True}))
        assert second["decision"] == "block" and "/handoff" in second["reason"]
        assert '"block"' not in stop({"stop_hook_active": True})

    def test_session_start_seeds_the_flag_with_head_and_keeps_it_across_a_compaction(
        self, tmp_path,
    ):
        import importlib.util

        if str(HOOKS_DIR) not in sys.path:
            sys.path.insert(0, str(HOOKS_DIR))
        name = "session_start_handoff_flag_under_test"
        spec = importlib.util.spec_from_file_location(name, str(HOOKS_DIR / "session_start.py"))
        ss = importlib.util.module_from_spec(spec)
        sys.modules[name] = ss
        spec.loader.exec_module(ss)
        mod = self._load()
        root = _lane_repo(tmp_path, ahead=1)
        flag = root / ".espalier-state" / mod.HANDOFF_GATE_FLAG
        ss._clean_state_flags(root, "startup")
        assert flag.read_text(encoding="utf-8").strip() == _head(root), "a new session starts judged at HEAD"
        flag.write_text("judged-earlier", encoding="utf-8")
        ss._clean_state_flags(root, "compact")
        assert flag.read_text(encoding="utf-8") == "judged-earlier", "a compaction keeps the flag"
        ss._clean_state_flags(root, "clear")
        assert flag.read_text(encoding="utf-8").strip() == _head(root)
        # Seeded, the gate has nothing to say about the HEAD the session began on.
        assert mod._gate_handoff(root) == 0


class TestTheGateCountHasOneOwner:
    """The docs say how many gates the Stop hook runs ("a five-gate sequence",
    "Five gates fire in sequence"). The owner of that count is the hook's own
    module docstring, its ``Gate N:`` lines; every doc's number word is derived
    from it here, so a sixth gate cannot land with "five" standing in seven
    places (the hand-maintained enumeration, docs/SHARP_EDGES.md). Record
    surfaces, the mirrors and the archives are left out: a record keeps the
    count of its day."""

    _WORDS = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}
    _PHRASE = re.compile(r"\b(three|four|five|six|seven|eight)-gate\b", re.IGNORECASE)
    _FIRE = re.compile(r"\b(three|four|five|six|seven|eight) gates fire\b", re.IGNORECASE)
    _LEFT_OUT = (
        "docs/session-archive.md", "memory/CONVERGENCE_LEDGER.md", "memory/session-log.d/",
        "task-packs/", "changelog.d/", "CHANGELOG.md", "espalier/assets/", "espalier/_vendor/",
        "examples/", "cc/", "reports/",
    )

    @classmethod
    def _declared(cls) -> int:
        import ast

        doc = ast.get_docstring(ast.parse((HOOKS_DIR / "stop_gate.py").read_text(encoding="utf-8"))) or ""
        numbered = set(re.findall(r"^Gate (\d+):", doc, flags=re.M))
        assert len(numbered) >= 4, f"the hook's docstring declares {sorted(numbered)}"
        return len(numbered)

    def test_every_doc_names_the_count_the_hook_declares(self):
        from tests._live_tree import checkout_files

        # magic-depth: ok the repo root, three above tools/cc/hooks
        repo_root = HOOKS_DIR.parents[2]
        word = self._WORDS[self._declared()]
        wrong: list[str] = []
        seen = 0
        for path in checkout_files(repo_root):
            rel = path.relative_to(repo_root).as_posix()
            if path.suffix != ".md" or rel.startswith(self._LEFT_OUT):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for pattern in (self._PHRASE, self._FIRE):
                for match in pattern.finditer(text):
                    seen += 1
                    if match.group(1).lower() != word:
                        line = text.count("\n", 0, match.start()) + 1
                        wrong.append(f"{rel}:{line}: {match.group(0)!r} (the hook declares {word})")
        assert seen >= 3, "the docs no longer say how many gates the Stop hook runs; the pin reads nothing"
        assert not wrong, "\n".join(wrong)


class TestPlanCompletion:
    """``_hook_utils.plan_completion``: the handoff gate's plan read, failing
    closed to not-complete on everything unreadable (the same domain as
    ``has_active_plan``)."""

    @staticmethod
    def _utils():
        import importlib.util

        if str(HOOKS_DIR) not in sys.path:
            sys.path.insert(0, str(HOOKS_DIR))
        spec = importlib.util.spec_from_file_location(
            "_hook_utils_plan_completion_under_test", str(HOOKS_DIR / "_hook_utils.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_a_complete_plan_reads_complete_with_its_title(self, tmp_path):
        (tmp_path / "cc").mkdir()
        _write_plan(tmp_path, "complete")
        assert self._utils().plan_completion(tmp_path) == (True, "TP-fixture: the lane")

    @pytest.mark.parametrize("body", [
        "", "not json", "[]", json.dumps({"status": "complete"}),
        json.dumps({"status": "complete", "steps": []}),
        json.dumps({"status": "in_progress", "steps": [{"title": "s"}]}),
    ])
    def test_everything_else_reads_not_complete(self, tmp_path, body):
        (tmp_path / "cc").mkdir()
        (tmp_path / "cc" / "execution_plan.json").write_text(body, encoding="utf-8")
        assert self._utils().plan_completion(tmp_path) == (False, "")

    def test_a_missing_plan_reads_not_complete(self, tmp_path):
        assert self._utils().plan_completion(tmp_path) == (False, "")
