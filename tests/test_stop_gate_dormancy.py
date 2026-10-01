"""TP-120b: Gate 1 dormancy is visible, not silent.

Catches the BC-041-sister class: a non-pytest fingerprint should
NOT silently no-op the stop gate; it should report dormancy with a
clear note + opt-in escape hatch.

Sister-shape: tests/test_stop_gate.py — same hook-import pattern,
same class-wrap convention (TestX per CONVENTIONS.md §122).
"""
from __future__ import annotations

import importlib.util
import json
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

    def test_go_fingerprint_returns_dormant_non_pytest(
        self, adopter_repo, monkeypatch
    ):
        monkeypatch.delenv(
            "ESPALIER_STOP_GATE_TEST_CMD", raising=False
        )
        _write_fp(adopter_repo, ["go test ./..."])
        mod = _load_stop_gate()
        rt = mod._resolve_core_tests(adopter_repo)
        assert rt.status == "dormant_non_pytest"
        assert "ESPALIER_STOP_GATE_TEST_CMD" in rt.note

    def test_canonical_pytest_q_no_defaults_returns_dormant_no_paths(
        self, adopter_repo, monkeypatch
    ):
        """Adopter has ``pytest -q`` (no positional args) and no
        tests/test_fingerprint.py — harness defaults not present, so
        dormant_no_paths is the right status (not silently green)."""
        monkeypatch.delenv(
            "ESPALIER_STOP_GATE_TEST_CMD", raising=False
        )
        _write_fp(adopter_repo, ["pytest -q"])
        mod = _load_stop_gate()
        rt = mod._resolve_core_tests(adopter_repo)
        assert rt.status == "dormant_no_paths"

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

    def test_a_real_pytest_feed_with_no_harness_files_is_dormant_and_names_the_override(self, tmp_path, monkeypatch):
        from espalier.analyze import detect_tests
        monkeypatch.delenv("ESPALIER_STOP_GATE_TEST_CMD", raising=False)
        self._pytest_tree(tmp_path)
        commands = detect_tests(tmp_path)
        assert "pytest -q" in commands, commands
        (tmp_path / "reports").mkdir()
        _write_fp(tmp_path, commands)
        rt = _load_stop_gate()._resolve_core_tests(tmp_path)
        assert rt.status == "dormant_no_paths", rt
        assert "ESPALIER_STOP_GATE_TEST_CMD" in rt.note, rt.note
        assert "fingerprint" not in rt.note.lower(), "the remedy must not point at a file init regenerates"

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
        assert rt.status == "dormant_non_pytest", rt
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
        assert statuses >= {"ok", "ok_env_override", "ok_harness_defaults", "dormant_non_pytest", "dormant_no_paths"}, statuses
        doc = mod.ResolvedTests.__doc__ or ""
        gate = inspect.getsource(mod._gate_pytest)
        for status in statuses:
            assert f'"{status}"' in doc, f"{status} is returned but not declared in ResolvedTests"
            if status != "ok":
                assert status in gate, f"{status} is returned but _gate_pytest never names it"
