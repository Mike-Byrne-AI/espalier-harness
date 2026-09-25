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

    def test_pytest_q_with_harness_defaults_returns_ok(
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
        assert rt.status == "ok"
        assert all((tmp_path / p).exists() for p in rt.paths)


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
