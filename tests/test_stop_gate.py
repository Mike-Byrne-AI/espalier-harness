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
    ``_run_env_override_gate`` could be neutered to ``return 0`` and the suite
    stayed green. Pin every branch: a failing cmd BLOCKS, a passing cmd ALLOWS,
    a timeout BLOCKS, and an empty-after-shlex value or an OSError spawn failure
    fail OPEN (allow). ``block()`` returns the truthy sentinel ``1``; a clean run
    returns ``0``. Determinism: ``subprocess.run`` is monkeypatched (no real
    shell, no wall-clock timing) per the concurrency-test-must-be-deterministic
    lesson; one end-to-end case drives the real Stop hook to prove the wiring."""

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
        monkeypatch.setattr(
            mod.subprocess, "run",
            lambda *a, **k: types.SimpleNamespace(
                returncode=1, stdout="boom-out", stderr="boom-err"),
        )
        rc = mod._run_env_override_gate(tmp_path, "adopter test --fails")
        assert rc == 1, "a non-zero override cmd must block (block() sentinel 1)"

    def test_passing_env_cmd_allows(self, monkeypatch, tmp_path):
        import types
        mod = self._load()
        monkeypatch.setattr(
            mod.subprocess, "run",
            lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="", stderr=""),
        )
        assert mod._run_env_override_gate(tmp_path, "adopter test --passes") == 0

    def test_timeout_blocks(self, monkeypatch, tmp_path):
        mod = self._load()

        def _timeout(*a, **k):
            raise mod.subprocess.TimeoutExpired(cmd="slow", timeout=1)

        monkeypatch.setattr(mod.subprocess, "run", _timeout)
        assert mod._run_env_override_gate(tmp_path, "slow-cmd") == 1, "timeout must block"

    def test_oserror_spawn_failure_allows(self, monkeypatch, tmp_path):
        mod = self._load()

        def _boom(*a, **k):
            raise OSError("cannot spawn")

        monkeypatch.setattr(mod.subprocess, "run", _boom)
        assert mod._run_env_override_gate(tmp_path, "no-such-binary") == 0, (
            "a spawn failure must fail OPEN (allow), not block"
        )

    def test_empty_after_shlex_returns_clean(self, monkeypatch, tmp_path):
        mod = self._load()

        def _spy(*a, **k):
            raise AssertionError("subprocess.run must not run on an empty cmd")

        monkeypatch.setattr(mod.subprocess, "run", _spy)
        assert mod._run_env_override_gate(tmp_path, "   ") == 0

    def test_end_to_end_failing_override_blocks_under_full(self, tmp_path, monkeypatch):
        """The audit's exact gap: a failing override cmd under STOP_GATE=full
        drives the REAL Stop hook to a block decision (JSON on stdout, exit 0)."""
        _init_dirty_repo(tmp_path)
        monkeypatch.setenv(
            "ESPALIER_STOP_GATE_TEST_CMD",
            f'{sys.executable} -c "import sys; sys.exit(1)"',
        )
        result = _run(tmp_path, mode=None, stop_gate="full")
        assert result.returncode == 0, result.stderr
        output = json.loads(result.stdout)
        assert output["decision"] == "block"
        assert "env override" in output["reason"], (
            f"expected the env-override Gate 1 block, got {output!r}"
        )


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
        assert result.status == "ok", (
            f"expected ok for fingerprinted repo; got {result.status!r}: "
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
        assert result.status == "ok", (
            f"expected ok for self-host pre-analyze; got "
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
        assert result.status == "ok"
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
        assert result.status == "ok"
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
