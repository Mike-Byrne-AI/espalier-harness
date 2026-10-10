"""TP-120b: Gate 1 dormancy is visible, not silent.

Catches the BC-041-sister class: a non-pytest fingerprint should
NOT silently no-op the stop gate; it should report dormancy with a
clear note + opt-in escape hatch.

Sister-shape: tests/test_stop_gate.py — same hook-import pattern,
same class-wrap convention (TestX per CONVENTIONS.md §122).

Since 2026-10-08 the detected command RUNS (``ok_detected``): the end-to-end
cases below drive the deployed hook on an init'd Node tree with a stub ``npm``
first on PATH, so the suite proves the spawn and its exit are read without
installing Node; that the real ``npm test`` runs was the pack's one hand drive.
"""
# slow-exempt: one init'd Node tree per module (2.1 s, measured 2026-10-08) copied per case; one deployed-hook subprocess and one sh-stub child per case, about 0.4 s each over four cases
from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Hook scripts add their own directory to sys.path; mirror that here
# so the import path matches what stop_gate uses internally.
HOOKS_DIR = (
    Path(__file__).resolve().parent.parent / "tools" / "cc" / "hooks"
)
sys.path.insert(0, str(HOOKS_DIR))


def _load_stop_gate():
    """Re-load ``stop_gate.py`` as a fresh module per test so
    env-var changes in ``monkeypatch`` are picked up at function-entry
    rather than at first import. Mirrors the pattern in
    ``tests/test_stop_gate.py::TestResolveCoreTestsFingerprintAware``."""
    spec = importlib.util.spec_from_file_location(
        "stop_gate_dormancy_under_test",
        str(HOOKS_DIR / "stop_gate.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["stop_gate_dormancy_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def adopter_repo(tmp_path):
    (tmp_path / "reports").mkdir()
    return tmp_path


def _write_fp(root: Path, test_commands: list[str]) -> None:
    (root / "reports" / "repo_fingerprint.json").write_text(
        json.dumps({"test_commands": test_commands}), encoding="utf-8",
    )


def _records(event_type: str) -> list[str]:
    """The audit lines of one event type under the per-test ESPALIER_AUDIT_DIR."""
    audit = Path(os.environ["ESPALIER_AUDIT_DIR"])
    return [
        ln for log in audit.glob("*.log")
        for ln in log.read_text(encoding="utf-8").splitlines()
        if f'"{event_type}"' in ln
    ]


class TestResolveCoreTestsDormancy:
    """Tri-state dormancy detection for ``_resolve_core_tests``."""

    def test_pytest_fingerprint_with_positional_returns_ok(
        self, adopter_repo, monkeypatch
    ):
        monkeypatch.delenv(
            "ESPALIER_STOP_GATE_TEST_CMD", raising=False
        )
        _write_fp(adopter_repo, ["pytest tests/test_foo.py"])
        mod = _load_stop_gate()
        rt = mod._resolve_core_tests(adopter_repo)
        assert rt.status == "ok"
        assert rt.paths == ["tests/test_foo.py"]
        assert rt.env_cmd == ""

    def test_go_fingerprint_runs_the_detected_command(
        self, adopter_repo, monkeypatch
    ):
        """Until 2026-10-08 this feed resolved ``dormant_non_pytest``: the gate
        announced the command and allowed. It runs it now, and the note still
        names the override."""
        monkeypatch.delenv(
            "ESPALIER_STOP_GATE_TEST_CMD", raising=False
        )
        _write_fp(adopter_repo, ["go test ./..."])
        mod = _load_stop_gate()
        rt = mod._resolve_core_tests(adopter_repo)
        assert rt.status == "ok_detected", rt
        assert rt.commands == ("go test ./...",) and rt.source == "fingerprint", rt
        assert rt.paths == [] and rt.env_cmd == ""
        assert "ESPALIER_STOP_GATE_TEST_CMD" in rt.note

    def test_nothing_detected_and_no_defaults_is_dormant_and_names_both_remedies(
        self, adopter_repo, monkeypatch
    ):
        monkeypatch.delenv("ESPALIER_STOP_GATE_TEST_CMD", raising=False)
        _write_fp(adopter_repo, [])
        rt = _load_stop_gate()._resolve_core_tests(adopter_repo)
        assert rt.status == "dormant_no_paths", rt
        assert rt.commands == () and rt.source == ""
        assert "[extra_actions] test" in rt.note and "ESPALIER_STOP_GATE_TEST_CMD" in rt.note, rt.note
        assert "fingerprint" not in rt.note.lower(), "the remedy must not point at a file init regenerates"

    def test_canonical_pytest_q_with_no_defaults_runs_the_command_whole(
        self, adopter_repo, monkeypatch
    ):
        """Adopter has ``pytest -q`` (no positional args) and no
        tests/test_fingerprint.py -- harness defaults not present. Until
        2026-10-08 that was ``dormant_no_paths``; the detected command runs
        whole now (the whole suite, within the 60 s budget), so a Python
        adopter with no harness file names is gated too."""
        monkeypatch.delenv(
            "ESPALIER_STOP_GATE_TEST_CMD", raising=False
        )
        _write_fp(adopter_repo, ["pytest -q"])
        mod = _load_stop_gate()
        rt = mod._resolve_core_tests(adopter_repo)
        assert rt.status == "ok_detected", rt
        assert rt.commands == ("pytest -q",) and rt.source == "fingerprint", rt

    def test_pytest_q_with_harness_defaults_returns_ok_harness_defaults_with_a_note(
        self, tmp_path, monkeypatch
    ):
        """Self-host case: harness defaults ARE present, fall-back
        path. Reads ``_HARNESS_DEFAULT_TESTS`` at test time (not
        hardcoded) so additions to the tuple don't drift this fixture
        silently — sister to TP-74 BC-041 prevention."""
        monkeypatch.delenv(
            "ESPALIER_STOP_GATE_TEST_CMD", raising=False
        )
        (tmp_path / "reports").mkdir()
        mod = _load_stop_gate()
        for p in mod._HARNESS_DEFAULT_TESTS:
            target = tmp_path / p
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# stub\n", encoding="utf-8")
        _write_fp(tmp_path, ["pytest -q"])
        rt = mod._resolve_core_tests(tmp_path)
        assert rt.status == "ok_harness_defaults"
        assert all((tmp_path / p).exists() for p in rt.paths)
        # A partial gate is never silent: the note names what runs and the override.
        assert "harness default" in rt.note and "ESPALIER_STOP_GATE_TEST_CMD" in rt.note, rt.note


class TestEnvOverride:
    """``ESPALIER_STOP_GATE_TEST_CMD`` opt-in escape hatch."""

    def test_env_override_returns_ok_env_override(
        self, monkeypatch, adopter_repo
    ):
        monkeypatch.setenv(
            "ESPALIER_STOP_GATE_TEST_CMD", "go test ./..."
        )
        _write_fp(adopter_repo, ["go test ./..."])
        mod = _load_stop_gate()
        rt = mod._resolve_core_tests(adopter_repo)
        assert rt.status == "ok_env_override"
        assert rt.paths == []
        assert "go test" in rt.note
        assert rt.env_cmd == "go test ./..."


class TestAdopterShapedFeed:
    """DEF-949: the gate on the feeds ``espalier.analyze.detect_tests`` really
    produces for an adopter, with no seeding of the harness default files --
    the parity test in ``tests/test_stop_gate.py`` seeds them, which makes it
    the self-host check. Every outcome here speaks: the note names the
    override, never the fingerprint file ``init`` regenerates."""

    @staticmethod
    def _pytest_tree(root: Path) -> None:
        (root / "tests").mkdir(parents=True, exist_ok=True)
        (root / "tests" / "test_app.py").write_text("def test_x():\n    assert 1\n", encoding="utf-8")
        (root / "pyproject.toml").write_text('[project]\nname = "app"\n[tool.pytest.ini_options]\n', encoding="utf-8")

    def test_a_real_pytest_feed_with_no_harness_files_runs_the_command_whole_and_names_the_overrides(self, tmp_path, monkeypatch):
        from espalier.analyze import detect_tests
        monkeypatch.delenv("ESPALIER_STOP_GATE_TEST_CMD", raising=False)
        self._pytest_tree(tmp_path)
        commands = detect_tests(tmp_path)
        assert "pytest -q" in commands, commands
        (tmp_path / "reports").mkdir()
        _write_fp(tmp_path, commands)
        rt = _load_stop_gate()._resolve_core_tests(tmp_path)
        assert rt.status == "ok_detected", rt
        assert rt.commands == ("pytest -q",) and rt.source == "fingerprint", rt
        assert "ESPALIER_STOP_GATE_TEST_CMD" in rt.note and "[extra_actions] test" in rt.note, rt.note
        assert "fingerprint" not in rt.note.lower(), "the note must not point at a file init regenerates"

    def test_a_colliding_filename_runs_the_defaults_only_and_says_so(self, tmp_path, monkeypatch):
        """Case D of the measurement: one file named like a harness default
        made Gate 1 run that file alone, print nothing, and allow a Stop
        while the rest of the suite failed."""
        monkeypatch.delenv("ESPALIER_STOP_GATE_TEST_CMD", raising=False)
        self._pytest_tree(tmp_path)
        (tmp_path / "tests" / "test_hooks.py").write_text("def test_h():\n    assert 1\n", encoding="utf-8")
        (tmp_path / "reports").mkdir()
        _write_fp(tmp_path, ["pytest -q"])
        rt = _load_stop_gate()._resolve_core_tests(tmp_path)
        assert rt.status == "ok_harness_defaults", rt
        assert rt.paths == ["tests/test_hooks.py"], rt.paths
        assert rt.note and "tests/test_hooks.py" in rt.note and "ESPALIER_STOP_GATE_TEST_CMD" in rt.note, rt.note

    def test_a_non_pytest_feed_names_the_override_not_the_fingerprint(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ESPALIER_STOP_GATE_TEST_CMD", raising=False)
        (tmp_path / "reports").mkdir()
        _write_fp(tmp_path, ["npm test"])
        rt = _load_stop_gate()._resolve_core_tests(tmp_path)
        assert rt.status == "ok_detected", rt
        assert rt.commands == ("npm test",) and rt.source == "fingerprint", rt
        assert "ESPALIER_STOP_GATE_TEST_CMD" in rt.note and "change test_commands" not in rt.note, rt.note

    def test_the_banner_names_the_defaults_only_posture_under_full(self, tmp_path, monkeypatch):
        """The SessionStart banner warned on a dormant status and said nothing
        on the defaults-only one; both are a gate that does not run the suite."""
        monkeypatch.delenv("ESPALIER_STOP_GATE_TEST_CMD", raising=False)
        monkeypatch.setenv("ESPALIER_STOP_GATE", "full")
        self._pytest_tree(tmp_path)
        (tmp_path / "tests" / "test_hooks.py").write_text("def test_h():\n    assert 1\n", encoding="utf-8")
        (tmp_path / "reports").mkdir()
        _write_fp(tmp_path, ["pytest -q"])
        spec = importlib.util.spec_from_file_location("_ss_for_dormancy", str(HOOKS_DIR / "session_start.py"))
        ss = importlib.util.module_from_spec(spec)
        sys.modules["_ss_for_dormancy"] = ss
        spec.loader.exec_module(ss)
        note = ss._stop_gate_dormancy_note(tmp_path)
        assert note and "harness default" in note and "ESPALIER_STOP_GATE_TEST_CMD" in note, note


class TestTheStatusVocabularyIsDeclaredWhereItIsRead:
    """Every `status=` literal `_resolve_core_tests` returns must be listed in
    `ResolvedTests`'s docstring (the declared source of truth) and handled by
    name in `_gate_pytest`, so a sixth status cannot reach the gate's
    fallthrough and skip silently (the failure-mode review drove the gap:
    `ok_harness_defaults` shipped with the docstring still saying tri-state)."""

    @staticmethod
    def _status_literals(mod) -> set[str]:
        import ast, inspect
        tree = ast.parse(inspect.getsource(mod._resolve_core_tests))
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "status" and isinstance(node.value, ast.Constant):
                found.add(str(node.value.value))
        return found

    def test_every_returned_status_is_in_the_docstring_and_the_gate(self):
        import inspect
        mod = _load_stop_gate()
        statuses = self._status_literals(mod)
        assert statuses == {"ok", "ok_env_override", "ok_harness_defaults", "ok_detected", "dormant_no_paths"}, statuses
        assert mod._STATUSES == statuses, "the roster checked at construction differs from the resolver's literals"
        with pytest.raises(ValueError):
            mod.ResolvedTests(paths=[], status="ok_new", note="")
        assert "dormant_non_pytest" not in statuses, "retired 2026-10-08: a detected command is run, not announced"
        doc = mod.ResolvedTests.__doc__ or ""
        gate = inspect.getsource(mod._gate_pytest)
        for status in statuses:
            assert f'"{status}"' in doc, f"{status} is returned but not declared in ResolvedTests"
            if status != "ok":
                assert status in gate, f"{status} is returned but _gate_pytest never names it"
        # The reverse: a status the gate compares against is one the resolver
        # returns, so a retired literal cannot linger as a dead branch.
        named = {
            str(node.value) for node in ast.walk(ast.parse(gate))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value.startswith(("ok", "dormant"))
        }
        assert named <= statuses, f"_gate_pytest names a status the resolver never returns: {named - statuses}"


def _npm_stub(bin_dir: Path, *, red: bool) -> Path:
    """An ``npm`` first on PATH, written the way ``tests/_interpreter_hosts.py``
    writes its interpreter stubs (an executable ``sh`` script; a ``.cmd`` on
    Windows): the red one prints the planted test's name and exits 1, the
    green one exits 0. The stub proves the hook spawned the fingerprint's
    command and read its exit; the suite installs no Node."""
    from _interpreter_hosts import _write
    bin_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        body = ("@echo not ok 1 - planted test/planted_red.test.js\n@exit /b 1" if red
                else "@echo ok 1 - index\n@exit /b 0")
        return _write(bin_dir / "npm.cmd", body, crlf=True)
    body = ("#!/bin/sh\necho 'not ok 1 - planted test/planted_red.test.js'\nexit 1" if red
            else "#!/bin/sh\necho 'ok 1 - index'\nexit 0")
    return _write(bin_dir / "npm", body, crlf=False)


@pytest.fixture(scope="module")
def node_tree_template(tmp_path_factory):
    """One init'd Node tree for the module (``tests/_adopter_tree.py``, the
    ``adopter-node`` row): the end-to-end cases copy it."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _adopter_tree import build_adopter_tree
    return build_adopter_tree(tmp_path_factory.mktemp("node-template") / "t", stack="node")


def _toml_parser_available() -> bool:
    sys.path.insert(0, str(HOOKS_DIR))
    import _hook_utils
    return _hook_utils._toml_parser() is not None


class TestTheDetectedCommandRunsEndToEnd:
    """DEF-949 step 4, measured on an init'd Node tree (Task 0 of the lane's
    pack, 2026-10-07): under ``full`` with a planted red test the deployed
    hook wrote 0 bytes on stdout and exited 0 -- ``dormant_non_pytest``, the
    gate announcing itself off. These drive the DEPLOYED hook -- the vendored
    copy ``init`` writes from ``espalier/_vendor/cc/``, so a source edit without
    ``scripts/sync_vendor_cc.py`` would leave them green on the old code; the
    first case asserts the two files are bytes-equal so that run reds here --
    with a stub ``npm`` ahead of PATH. Each dies to reverting the detected arm (no
    decision is printed) and to an ``ok_detected`` carrying ``commands=()``
    (the runner has nothing to run and allows)."""

    @staticmethod
    def _node_tree(tmp_path: Path, template: Path) -> Path:
        """A copy of the module's one init'd Node tree, with the red test planted:
        the deploy (init plus install-ci) is paid once per module, the copy per
        case, and each case gets its own state directory."""
        tree = tmp_path / "t"
        shutil.copytree(template, tree, symlinks=True)
        (tree / "test" / "planted_red.test.js").write_text(
            'import {test} from "node:test"; import assert from "node:assert/strict";\n'
            'test("planted", () => assert.equal(1, 2));\n', encoding="utf-8",
        )
        return tree

    @staticmethod
    def _stop(tree: Path, bin_dir: Path, **env: str) -> subprocess.CompletedProcess:
        from _interpreter_hosts import path_with
        # PATH is replaced whole, dropped case-insensitively first (os.environ
        # upper-cases its keys on Windows, so there is one key either way).
        clean = {k: v for k, v in os.environ.items()
                 if k.upper() != "PATH" and not k.startswith(("CLAUDE_", "ESPALIER_"))}
        clean.update(
            CLAUDE_PROJECT_DIR=str(tree), ESPALIER_AUDIT_DIR=os.environ["ESPALIER_AUDIT_DIR"],
            ESPALIER_STOP_GATE="full", PATH=path_with(bin_dir), **env,
        )
        payload = {
            "session_id": "t", "transcript_path": os.devnull, "cwd": str(tree),
            "permission_mode": "default", "hook_event_name": "Stop", "stop_hook_active": False,
        }
        return subprocess.run(
            [sys.executable, str(tree / "tools" / "cc" / "hooks" / "stop_gate.py")],
            input=json.dumps(payload), capture_output=True, encoding="utf-8",
            env=clean, cwd=str(tree), timeout=45,
        )

    def test_the_deployed_hook_is_the_source_hook(self):
        """Byte parity, asserted where the operator runs this file alone."""
        root = Path(__file__).resolve().parent.parent
        source = (root / "tools" / "cc" / "hooks" / "stop_gate.py").read_bytes()
        vendored = (root / "espalier" / "_vendor" / "cc" / "hooks" / "stop_gate.py").read_bytes()
        assert source == vendored, "run python3 scripts/sync_vendor_cc.py: the cases below drive the vendored copy"

    def test_a_planted_red_blocks_the_stop_naming_the_test_and_the_source(self, tmp_path, node_tree_template):
        tree = self._node_tree(tmp_path, node_tree_template)
        _npm_stub(tmp_path / "bin", red=True)
        result = self._stop(tree, tmp_path / "bin")
        assert result.returncode == 0, result.stderr
        decision = json.loads(result.stdout)
        assert decision["decision"] == "block", result.stdout
        reason = decision["reason"]
        assert "planted_red.test.js" in reason, reason
        assert "npm test" in reason and "fingerprint" in reason, reason
        records = _records("stop_blocked_pytest")
        assert len(records) == 1 and '"source": "fingerprint"' in records[0], records

    def test_a_green_tree_allows(self, tmp_path, node_tree_template):
        tree = self._node_tree(tmp_path, node_tree_template)
        (tree / "test" / "planted_red.test.js").unlink()
        _npm_stub(tmp_path / "bin", red=False)
        result = self._stop(tree, tmp_path / "bin")
        assert result.returncode == 0, result.stderr
        assert '"block"' not in result.stdout, result.stdout
        assert not _records("stop_blocked_pytest")

    def test_the_override_still_wins_and_the_reason_says_so(self, tmp_path, node_tree_template):
        tree = self._node_tree(tmp_path, node_tree_template)
        _npm_stub(tmp_path / "bin", red=True)
        result = self._stop(
            tree, tmp_path / "bin",
            ESPALIER_STOP_GATE_TEST_CMD=f'"{sys.executable}" -c "import sys; sys.exit(3)"',
        )
        reason = json.loads(result.stdout)["reason"]
        assert "ESPALIER_STOP_GATE_TEST_CMD" in reason and "exited 3" in reason, reason
        assert "planted_red" not in reason, "the fingerprint's command ran where the override should have"

    def test_a_declared_extra_actions_test_wins_over_the_fingerprint(self, tmp_path, node_tree_template):
        if not _toml_parser_available():
            import pytest as _pytest
            _pytest.skip("no TOML parser for the hook interpreter (3.10 without tomli)")
        tree = self._node_tree(tmp_path, node_tree_template)
        _npm_stub(tmp_path / "bin", red=True)
        cmd = f'"{sys.executable}" -c "import sys; sys.exit(5)"'
        with (tree / "espalier.toml").open("a", encoding="utf-8") as fh:
            fh.write("\n[extra_actions]\ntest = [" + json.dumps(cmd) + "]\n")
        result = self._stop(tree, tmp_path / "bin")
        reason = json.loads(result.stdout)["reason"]
        assert "espalier.toml" in reason and "exited 5" in reason, reason
        assert "planted_red" not in reason, "the fingerprint's command ran where the declared one should have"


class TestTheDeclaredTestCommand:
    """1-B of the lane: ``[extra_actions] test`` read hook-side, the committed
    home for the stop-time test command (DEC-35, decided 2026-10-08: the
    environment first, then this key, then the fingerprint)."""

    @staticmethod
    def _tree(tmp_path: Path, toml: str | None) -> Path:
        (tmp_path / "reports").mkdir()
        _write_fp(tmp_path, ["npm test"])
        if toml is not None:
            (tmp_path / "espalier.toml").write_text(toml, encoding="utf-8")
        return tmp_path

    def test_a_declared_list_is_what_runs_and_where_it_came_from(self, tmp_path, monkeypatch):
        if not _toml_parser_available():
            import pytest as _pytest
            _pytest.skip("no TOML parser for the hook interpreter")
        monkeypatch.delenv("ESPALIER_STOP_GATE_TEST_CMD", raising=False)
        root = self._tree(tmp_path, '[extra_actions]\ntest = ["make check", "make lint"]\n')
        rt = _load_stop_gate()._resolve_core_tests(root)
        assert rt.status == "ok_detected" and rt.source == "espalier.toml", rt
        assert rt.commands == ("make check", "make lint"), rt
        assert "espalier.toml" in rt.note and "ESPALIER_STOP_GATE_TEST_CMD" in rt.note, rt.note

    def test_the_override_outranks_the_declared_command(self, tmp_path, monkeypatch):
        if not _toml_parser_available():
            import pytest as _pytest
            _pytest.skip("no TOML parser for the hook interpreter")
        monkeypatch.setenv("ESPALIER_STOP_GATE_TEST_CMD", "go test ./...")
        root = self._tree(tmp_path, '[extra_actions]\ntest = ["make check"]\n')
        rt = _load_stop_gate()._resolve_core_tests(root)
        assert rt.status == "ok_env_override" and rt.source == "env", rt
        assert rt.commands == ("go test ./...",) and rt.env_cmd == "go test ./..."

    def test_a_string_where_a_list_belongs_is_ignored_and_said_once(self, tmp_path, monkeypatch):
        if not _toml_parser_available():
            import pytest as _pytest
            _pytest.skip("no TOML parser for the hook interpreter")
        monkeypatch.delenv("ESPALIER_STOP_GATE_TEST_CMD", raising=False)
        root = self._tree(tmp_path, '[extra_actions]\ntest = "npm test"\n')
        mod = _load_stop_gate()
        mod._hook_utils._SAID_THIS_PROCESS.clear()
        rt = mod._resolve_core_tests(root)
        assert rt.status == "ok_detected" and rt.source == "fingerprint", rt
        assert rt.commands == ("npm test",), "the detected command runs where the key does nothing"
        assert len(_records("stop_failed_open_toml_test_shape")) == 1, _records("stop_failed_open_toml_test_shape")
        mod._resolve_core_tests(root)
        assert len(_records("stop_failed_open_toml_test_shape")) == 1, "once a session"

    def test_a_file_that_will_not_parse_is_said_once_and_the_detected_command_runs(self, tmp_path, monkeypatch):
        if not _toml_parser_available():
            import pytest as _pytest
            _pytest.skip("no TOML parser for the hook interpreter")
        monkeypatch.delenv("ESPALIER_STOP_GATE_TEST_CMD", raising=False)
        root = self._tree(tmp_path, "[extra_actions\ntest = [\n")
        mod = _load_stop_gate()
        mod._hook_utils._SAID_THIS_PROCESS.clear()
        rt = mod._resolve_core_tests(root)
        assert rt.status == "ok_detected" and rt.commands == ("npm test",), rt
        assert len(_records("stop_failed_open_toml_unreadable")) == 1

    def test_a_compound_entry_is_refused_before_the_spawn_naming_the_shape(self, tmp_path, monkeypatch, capsys):
        """`cd web && npm test` without a shell starts `cd` alone (macOS ships
        /usr/bin/cd), which exits 0 with the suite never run -- the review
        drove a green gate over a red suite. Refused before the spawn, once a
        session, with the shape and the one-program-per-entry remedy named."""
        monkeypatch.delenv("ESPALIER_STOP_GATE_TEST_CMD", raising=False)
        mod = _load_stop_gate()
        capsys.readouterr()
        assert mod._run_command_gate(tmp_path, ("cd packages/web && npm test",), source="espalier.toml") == 1
        reason = json.loads(capsys.readouterr().out)["reason"]
        assert "shell syntax" in reason and "&&" in reason and "one program per entry" in reason, reason
        assert "espalier.toml" in reason.split("Do:", 1)[1], reason
        records = _records("stop_blocked_pytest")
        assert len(records) == 1 and '"error": "ShellSyntax"' in records[0], records
        assert mod._run_command_gate(tmp_path, ("cd packages/web && npm test",), source="espalier.toml") == 0
        assert "reported earlier this session" in capsys.readouterr().err
        for shape in ("npm test | tee log", "npm run build; npm test", "pytest -q > out.txt", "npm test $(cat x)"):
            assert mod._shell_syntax_token(mod._hook_utils.split_command(shape)), shape
        assert not mod._shell_syntax_token(mod._hook_utils.split_command('node --test --test-name-pattern "a|b"'))

    def test_two_broken_entries_are_each_reported_once(self, tmp_path, monkeypatch, capsys):
        """A shared once-a-session flag waved the second entry through unreported:
        the first Stop blocked on entry one and never reached entry two, the
        next Stop saw the flag and allowed both. The report is per command."""
        import shutil as _shutil
        monkeypatch.delenv("ESPALIER_STOP_GATE_TEST_CMD", raising=False)
        monkeypatch.setattr(_shutil, "which", lambda tok, *a, **k: None)
        mod = _load_stop_gate()
        both = ("./setup-typo.sh", "./also-typo.sh")
        capsys.readouterr()
        assert mod._run_command_gate(tmp_path, both, source="espalier.toml") == 1
        assert "setup-typo" in json.loads(capsys.readouterr().out)["reason"]
        assert mod._run_command_gate(tmp_path, both, source="espalier.toml") == 1, "the second entry was never reported"
        assert "also-typo" in json.loads(capsys.readouterr().out)["reason"]
        assert mod._run_command_gate(tmp_path, both, source="espalier.toml") == 0
        assert len(_records("stop_blocked_pytest")) == 2

    def test_no_toml_parser_says_once_when_the_key_is_declared(self, tmp_path, monkeypatch):
        """Python 3.10 without tomli: the table cannot be read. A declared key
        is found by regex and said once; a skeleton with the key commented out
        says nothing. Either way the detected command runs."""
        monkeypatch.delenv("ESPALIER_STOP_GATE_TEST_CMD", raising=False)
        mod = _load_stop_gate()
        monkeypatch.setattr(mod._hook_utils, "_TOML_PARSER", None)
        mod._hook_utils._SAID_THIS_PROCESS.clear()
        root = self._tree(tmp_path, '# [extra_actions]\n# test = ["npm test"]\n')
        rt = mod._resolve_core_tests(root)
        assert rt.status == "ok_detected" and rt.source == "fingerprint", rt
        assert not _records("stop_failed_open_toml_no_parser")
        (root / "espalier.toml").write_text('[extra_actions]\ntest = ["make check"]\n', encoding="utf-8")
        rt = mod._resolve_core_tests(root)
        assert rt.status == "ok_detected" and rt.source == "fingerprint" and rt.commands == ("npm test",), rt
        assert len(_records("stop_failed_open_toml_no_parser")) == 1
        mod._resolve_core_tests(root)
        assert len(_records("stop_failed_open_toml_no_parser")) == 1, "once a session"

    def test_each_declared_command_runs_in_order_and_the_first_red_blocks(self, tmp_path, monkeypatch, capsys):
        """`test = ["npm run build", "npm test"]`: both run, in order; a red second
        entry blocks naming it; a red first entry blocks before the second is
        spawned. Dies to a loop that runs only the first entry (a mutation that
        survived the lane's first test set)."""
        import shutil as _shutil
        import types
        mod = _load_stop_gate()
        monkeypatch.setattr(_shutil, "which", lambda tok, *a, **k: "/resolved/" + tok)
        seen: list[list[str]] = []

        def _run(argv, **kw):
            seen.append(list(argv))
            rc = 1 if "red" in argv[0] else 0
            return types.SimpleNamespace(returncode=rc, stdout=f"ran {argv[0]}", stderr="")

        monkeypatch.setattr(mod.subprocess, "run", _run)
        capsys.readouterr()
        assert mod._run_command_gate(tmp_path, ("green-one", "green-two"), source="espalier.toml") == 0
        assert [a[0] for a in seen] == ["/resolved/green-one", "/resolved/green-two"], seen
        seen.clear()
        assert mod._run_command_gate(tmp_path, ("green-one", "red-two"), source="espalier.toml") == 1
        assert "red-two" in json.loads(capsys.readouterr().out)["reason"]
        seen.clear()
        assert mod._run_command_gate(tmp_path, ("red-one", "green-two"), source="espalier.toml") == 1
        assert [a[0] for a in seen] == ["/resolved/red-one"], "the first red short-circuits"

    def test_a_polyglot_fingerprint_runs_the_first_and_names_the_rest(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ESPALIER_STOP_GATE_TEST_CMD", raising=False)
        (tmp_path / "reports").mkdir()
        _write_fp(tmp_path, ["pytest -q", "npm test"])
        rt = _load_stop_gate()._resolve_core_tests(tmp_path)
        assert rt.status == "ok_detected" and rt.commands == ("pytest -q",), rt
        assert "npm test" in rt.note and "not run" in rt.note and "[extra_actions] test" in rt.note, rt.note

    def test_the_banner_names_the_detected_command_under_full(self, tmp_path, monkeypatch):
        """The boot line for the adopter who exported `full`: the command runs on
        every Stop now, and a run past the budget blocks."""
        monkeypatch.delenv("ESPALIER_STOP_GATE_TEST_CMD", raising=False)
        monkeypatch.setenv("ESPALIER_STOP_GATE", "full")
        (tmp_path / "reports").mkdir()
        _write_fp(tmp_path, ["npm test"])
        spec = importlib.util.spec_from_file_location("_ss_for_detected", str(HOOKS_DIR / "session_start.py"))
        ss = importlib.util.module_from_spec(spec)
        sys.modules["_ss_for_detected"] = ss
        spec.loader.exec_module(ss)
        note = ss._stop_gate_dormancy_note(tmp_path)
        assert note and "npm test" in note and "every Stop" in note and "blocks" in note, note

    def test_no_file_and_no_key_fall_through_to_the_fingerprint(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ESPALIER_STOP_GATE_TEST_CMD", raising=False)
        root = self._tree(tmp_path, None)
        assert _load_stop_gate()._declared_test_commands(root) == ()
        rt = _load_stop_gate()._resolve_core_tests(root)
        assert rt.status == "ok_detected" and rt.source == "fingerprint", rt


class TestTheDormantTreeLeavesARecord:
    """``dormant_no_paths`` was a stderr line alone, which a hook that exits 0
    sends to the debug log (the protocol pin): three Stops on the Node tree
    left no ``.espalier-state/`` and no record (Task 0, measurement 4). It is
    a ``say_once`` now, so ``/status --log`` can count it."""

    def test_the_gate_allows_and_records_once(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ESPALIER_STOP_GATE_TEST_CMD", raising=False)
        (tmp_path / "reports").mkdir()
        _write_fp(tmp_path, [])
        mod = _load_stop_gate()
        mod._hook_utils._SAID_THIS_PROCESS.clear()
        assert mod._gate_pytest(tmp_path) == 0
        assert len(_records("stop_failed_open_gate1_dormant")) == 1, _records("stop_failed_open_gate1_dormant")
        assert mod._gate_pytest(tmp_path) == 0
        assert len(_records("stop_failed_open_gate1_dormant")) == 1, "once a session"
