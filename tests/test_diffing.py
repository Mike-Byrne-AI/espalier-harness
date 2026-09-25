"""Tests for ``espalier.diffing.diff_repo`` — the drift-detection
helper invoked by ``espalier analyze`` to compare current fingerprint
against the saved ``reports/repo_fingerprint.json``.

Pins three invariants: no crash when ``reports/`` is absent (fresh
repo), fingerprint changes surface as ``fingerprint_changed=True``,
and ``fingerprint_changed_keys`` populates with the specific drifted
attributes. Without this guard a renamed key in the fingerprint
schema could silently report no-change on a clearly-drifted repo,
defeating analyze's whole purpose.
"""
from __future__ import annotations

import json
from pathlib import Path


from espalier.diffing import current_surface_report, diff_repo

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestDiffRepo:
    def test_no_crash_when_no_saved_reports(self, python_repo):
        """diff_repo on a repo with no reports/ dir returns a result dict."""
        result = diff_repo(python_repo)
        assert isinstance(result, dict)
        assert "fingerprint_changed" in result
        assert "build_plan_changed" in result

    def test_detects_fingerprint_change(self, harness_repo):
        """Adding a new Python file after saving reports → fingerprint_changed=True."""
        (harness_repo / "new_module.py").write_text(
            "def new_func(): pass\n", encoding="utf-8"
        )
        result = diff_repo(harness_repo)
        assert result["fingerprint_changed"] is True

    def test_changed_keys_list_is_populated(self, harness_repo):
        """When reports differ from fresh inference, changed_keys is non-empty."""
        (harness_repo / "extra.py").write_text("x = 1\n", encoding="utf-8")
        result = diff_repo(harness_repo)
        if result["fingerprint_changed"]:
            assert len(result["fingerprint_changed_keys"]) > 0

    def test_no_change_on_clean_repo(self, harness_repo):
        """Fingerprint saved after all files are written; re-running diff finds no fp change."""
        result = diff_repo(harness_repo)
        assert result["fingerprint_changed"] is False

    def test_generic_mode_label_on_non_self_host(self, python_repo):
        result = diff_repo(python_repo)
        assert result["mode"] == "generic"


class TestCurrentSurfaceReport:
    def test_auto_mode_detects_self_host(self):
        report = current_surface_report(REPO_ROOT, mode="auto")
        assert report["mode"] == "self_host"

    def test_auto_mode_detects_generic(self, tmp_path):
        report = current_surface_report(tmp_path, mode="auto")
        assert report["mode"] == "generic"

    def test_forced_mode_overrides_detection(self, tmp_path):
        report = current_surface_report(tmp_path, mode="self_host")
        assert report["mode"] == "self_host"

    def test_self_host_report_populated(self, initialized_repo_root):
        from tests._surface_expected import (
            EXPECTED_AGENT_COUNT_MIN,
            EXPECTED_COMMAND_COUNT,
            EXPECTED_HOOK_COUNT,
        )
        report = current_surface_report(initialized_repo_root, mode="self_host")
        assert len(report["agents"]) >= EXPECTED_AGENT_COUNT_MIN
        assert len(report["commands"]) == EXPECTED_COMMAND_COUNT
        assert len(report["hooks"]) == EXPECTED_HOOK_COUNT


class TestSelfHostDiff:
    """Pack 2-E — self-host diff uses discovered surface, not generic generator."""

    def test_self_host_diff_returns_self_host_mode(self):
        result = diff_repo(REPO_ROOT)
        assert result["mode"] == "self_host"

    def test_self_host_diff_has_added_removed_keys(self):
        result = diff_repo(REPO_ROOT)
        assert "self_host_added" in result
        assert "self_host_removed" in result

    def test_self_host_diff_detects_missing_agent(self, tmp_path, monkeypatch):
        """Seed a self-host-like repo and assert removing an agent surfaces in drift."""
        from espalier import surface_contract
        # Pretend the tmp_path IS the self-host repo for this test
        monkeypatch.setattr(surface_contract, "is_self_host_repo", lambda p: True)

        # Build a minimal self-host-looking tree
        (tmp_path / ".claude" / "agents").mkdir(parents=True)
        (tmp_path / ".claude" / "commands").mkdir(parents=True)
        (tmp_path / "tools" / "cc" / "hooks").mkdir(parents=True)
        (tmp_path / "espalier").mkdir()
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "espalier-harness"\n', encoding="utf-8")
        (tmp_path / "reports").mkdir()

        # Saved plan says agent "phantom" exists
        (tmp_path / "reports" / "harness_config.json").write_text(json.dumps({
            "repo_name": "espalier",
            "agents": [{"name": "phantom", "description": "", "write_access": False,
                         "scope": "test", "model": "sonnet"}],
            "hooks": [],
            "generated_docs": [],
        }), encoding="utf-8")
        # Minimal fingerprint
        (tmp_path / "reports" / "repo_fingerprint.json").write_text(json.dumps({
            "repo_name": "espalier", "repo_root": ".",
            "language_counts": {}, "languages": [], "package_systems": [],
            "package_roots": [], "ci_providers": [], "entrypoints": [],
            "test_commands": [], "inferred_actions": {},
            "docs_surface": [], "runtime_surface": [],
            "api_surface": False, "ui_surface": False, "ml_surface": False,
            "ops_surface": False, "ops_directories": [], "monorepo": False,
            "generated_zones": [], "risky_mutable_zones": [],
            "large_files": [], "garbage_files": [], "conventions": {},
            "git_conventions": {}, "notes": [], "signals": [], "confidence": {},
        }), encoding="utf-8")
        # Disk has no agents .md — phantom is stale / missing
        (tmp_path / ".claude" / "settings.json").write_text(
            '{"hooks": {}}', encoding="utf-8"
        )

        result = diff_repo(tmp_path)
        assert result["mode"] == "self_host"
        assert "agents" in result["build_plan_changed_keys"]
        assert ".claude/agents/phantom.md" in result["self_host_removed"]["agents"]


class TestDiffBackwardCompat:
    def test_result_has_mode_key(self, python_repo):
        result = diff_repo(python_repo)
        assert "mode" in result

    def test_result_has_fingerprint_keys(self, python_repo):
        result = diff_repo(python_repo)
        assert "fingerprint_changed" in result
        assert "build_plan_changed" in result


class TestLoadJsonRobustness:
    """TP-191 W2: a present-but-malformed/non-UTF-8 reports/*.json must degrade
    to {} (so doctor/diff keep working), not traceback."""

    def test_malformed_json_degrades_to_empty(self, tmp_path):
        from espalier.diffing import _load_json
        p = tmp_path / "repo_fingerprint.json"
        p.write_text("{ this is not valid json", encoding="utf-8")
        assert _load_json(p) == {}

    def test_non_utf8_bytes_degrade_to_empty(self, tmp_path):
        from espalier.diffing import _load_json
        p = tmp_path / "repo_fingerprint.json"
        p.write_bytes(b"\xff\xfe\x00not utf-8")
        assert _load_json(p) == {}
