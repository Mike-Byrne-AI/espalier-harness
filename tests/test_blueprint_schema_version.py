"""C3 / TP-48 — CognitiveBlueprint.schema_version forward/back compat.

Pre-fix shape: a v0.6 reader receiving a v0.7 payload with a new field
raised TypeError inside ``cls(**payload)``. The catch in
``load_latest_blueprint`` swallowed it, returned None, and the next
``cmd_start`` invocation reset ``accumulated_depth=1`` — silently
dropping the entire session chain.

Post-fix shape: ``from_dict`` drops unknown keys with a stderr warn,
defaults missing ``schema_version`` to 1, and otherwise reconstructs
normally. The hook-side ``cmd_start`` writes ``schema_version: 1`` so
both implementations agree on the on-disk shape.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


from espalier.cognitive_blueprint import (
    load_latest_blueprint,
    save_blueprint,
)
from espalier.models import CognitiveBlueprint

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_SIDE_SCRIPT = REPO_ROOT / "tools" / "cc" / "cognitive_blueprint.py"


def _make_marker_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "tools" / "cc").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'fake'\nversion = '0.0.0'\n", encoding="utf-8",
    )
    reports = repo / "reports"
    reports.mkdir()
    (reports / "repo_fingerprint.json").write_text(
        '{"repo_name": "fake"}', encoding="utf-8",
    )
    (reports / "harness_config.json").write_text("{}", encoding="utf-8")
    (reports / "cc_surface_gate.json").write_text(
        '{"status": "pass"}', encoding="utf-8",
    )
    return repo


class TestSchemaVersionDefault:
    def test_default_constructor_sets_schema_version_to_one(self):
        bp = CognitiveBlueprint(
            session_id="s1", repo_name="r", timestamp="t",
        )
        assert bp.schema_version == 1

    def test_to_dict_includes_schema_version(self):
        bp = CognitiveBlueprint(
            session_id="s1", repo_name="r", timestamp="t",
        )
        assert bp.to_dict()["schema_version"] == 1


class TestFromDictBackwardCompat:
    """v0.6 payloads (no schema_version) must load cleanly with default=1."""

    def test_payload_missing_schema_version_defaults_to_one(self):
        legacy_payload = {
            "session_id": "s1",
            "repo_name": "r",
            "timestamp": "t",
        }
        bp = CognitiveBlueprint.from_dict(legacy_payload)
        assert bp.schema_version == 1

    def test_payload_with_schema_version_preserves_value(self):
        payload = {
            "session_id": "s1",
            "repo_name": "r",
            "timestamp": "t",
            "schema_version": 1,
        }
        bp = CognitiveBlueprint.from_dict(payload)
        assert bp.schema_version == 1


class TestFromDictForwardCompat:
    """v0.7 payloads with future fields must be tolerated (drop + warn)."""

    def test_unknown_keys_dropped_with_stderr_warn(self, capfd):
        future_payload = {
            "session_id": "s1",
            "repo_name": "r",
            "timestamp": "t",
            "future_field_x": "added in v0.8",
            "future_field_y": ["whatever"],
        }
        bp = CognitiveBlueprint.from_dict(future_payload)
        captured = capfd.readouterr()
        assert "future_field_x" in captured.err
        assert "future_field_y" in captured.err
        assert "dropping unknown keys" in captured.err
        # And the known fields still round-trip
        assert bp.session_id == "s1"

    def test_no_warn_when_payload_has_only_known_keys(self, capfd):
        payload = {
            "session_id": "s1",
            "repo_name": "r",
            "timestamp": "t",
            "schema_version": 1,
        }
        CognitiveBlueprint.from_dict(payload)
        captured = capfd.readouterr()
        assert "dropping unknown keys" not in captured.err


class TestSaveLoadRoundTrip:
    def test_round_trip_preserves_schema_version(self, tmp_path):
        bp = CognitiveBlueprint(
            session_id="s1", repo_name="r", timestamp="t",
            schema_version=1,
        )
        save_blueprint(tmp_path, bp)
        loaded = load_latest_blueprint(tmp_path)
        assert loaded is not None
        assert loaded.schema_version == 1

    def test_load_legacy_on_disk_blueprint_defaults_to_schema_version_one(self, tmp_path):
        """A legacy v0.6 blueprint on disk (no schema_version key) loads
        with schema_version=1, not None."""
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        legacy = {
            "session_id": "old-session",
            "repo_name": "r",
            "timestamp": "2026-04-01T00:00:00Z",
        }
        (bp_dir / "latest.json").write_text(json.dumps(legacy), encoding="utf-8")
        loaded = load_latest_blueprint(tmp_path)
        assert loaded is not None
        assert loaded.schema_version == 1
        assert loaded.session_id == "old-session"


class TestHooksideWritesSchemaVersion:
    """Hook-side ``cmd_start`` must write ``schema_version: 1`` to the
    on-disk blueprint so library/standalone agree on the schema."""

    def test_cmd_start_includes_schema_version_one(self, tmp_path):
        repo = _make_marker_repo(tmp_path)
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(repo)
        result = subprocess.run(
            [sys.executable, str(HOOK_SIDE_SCRIPT), "start"],
            cwd=str(repo), env=env,
            capture_output=True, text=True, timeout=15, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        latest = repo / "cc" / "blueprints" / "latest.json"
        data = json.loads(latest.read_text(encoding="utf-8"))
        assert data["schema_version"] == 1

    def test_hookside_written_blueprint_loads_via_library_with_schema_version(
        self, tmp_path,
    ):
        repo = _make_marker_repo(tmp_path)
        env = os.environ.copy()
        env["CLAUDE_PROJECT_DIR"] = str(repo)
        result = subprocess.run(
            [sys.executable, str(HOOK_SIDE_SCRIPT), "start"],
            cwd=str(repo), env=env,
            capture_output=True, text=True, timeout=15, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        bp = load_latest_blueprint(repo)
        assert bp is not None
        assert bp.schema_version == 1
