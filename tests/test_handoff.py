"""Tests for ``espalier.handoff`` — the surface-handoff builder that
writes ``cc/SURFACE_HANDOFF.md`` on first ``espalier init`` so the
adopter has a deployed-surface inventory to read.

Pins the ``MANAGED_MARKER`` wrapping rule: ``.md`` files get an HTML
comment marker so ``espalier.cleanup`` can later identify them on
uninstall. Without this guard a future marker-format change in
``cleanup`` (or vice-versa) would let handoff-written files escape
cleanup detection, silently leaking managed artifacts into the
adopter repo permanently.
"""
from __future__ import annotations

import json
from pathlib import Path

from espalier.managed_markers import MANAGED_MARKER
from espalier.handoff import (
    _load_json,
    build_surface_handoff,
    render_surface_handoff,
    write_surface_handoff,
)


def _write_reports(
    root: Path,
    plan: dict | None = None,
    fingerprint: dict | None = None,
    gate: dict | None = None,
) -> None:
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    if plan is not None:
        (reports / "harness_config.json").write_text(json.dumps(plan), encoding="utf-8")
    if fingerprint is not None:
        (reports / "repo_fingerprint.json").write_text(json.dumps(fingerprint), encoding="utf-8")
    if gate is not None:
        (reports / "cc_surface_gate.json").write_text(json.dumps(gate), encoding="utf-8")


class TestLoadJson:
    def test_returns_empty_dict_for_missing_file(self, tmp_path):
        result = _load_json(tmp_path / "nonexistent.json")
        assert result == {}

    def test_loads_plain_json_file(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps({"key": "value"}), encoding="utf-8")
        result = _load_json(f)
        assert result == {"key": "value"}

    def test_strips_managed_marker_line_before_parsing(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text("# espalier:managed\n" + json.dumps({"key": "value"}), encoding="utf-8")
        result = _load_json(f)
        assert result == {"key": "value"}

    def test_strips_html_comment_marker_before_parsing(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text("<!-- espalier:managed -->\n" + json.dumps({"x": 1}), encoding="utf-8")
        result = _load_json(f)
        assert result == {"x": 1}

    def test_non_dict_json_degrades_to_empty(self, tmp_path):
        """TP-174a: Class-B parity — a valid-JSON-but-non-dict report degrades
        to {} (matching diffing) instead of crashing /handoff."""
        f = tmp_path / "data.json"
        f.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        assert _load_json(f) == {}

    def test_degrades_on_invalid_json(self, tmp_path):
        # TP-204a: _load_json now routes through the guarded _report_io owner,
        # so malformed JSON degrades to {} instead of tracebacking /handoff.
        f = tmp_path / "bad.json"
        f.write_text("{not valid json", encoding="utf-8")
        assert _load_json(f) == {}


class TestBuildSurfaceHandoff:
    def test_returns_dict_with_required_keys(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert isinstance(result, dict)
        for key in ("repo_name", "profiles", "languages", "agents", "commands", "gate_status"):
            assert key in result

    def test_repo_name_from_plan(self, tmp_path):
        _write_reports(tmp_path, plan={"repo_name": "my-project"}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert result["repo_name"] == "my-project"

    def test_repo_name_falls_back_to_fingerprint(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={"repo_name": "fp-repo"}, gate={})
        result = build_surface_handoff(tmp_path)
        assert result["repo_name"] == "fp-repo"

    def test_repo_name_falls_back_to_dir_name(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert result["repo_name"] == tmp_path.name

    def test_languages_from_fingerprint(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={"languages": ["python", "javascript"]}, gate={})
        result = build_surface_handoff(tmp_path)
        assert result["languages"] == ["python", "javascript"]

    def test_gate_status_from_gate_report(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={"status": "pass"})
        result = build_surface_handoff(tmp_path)
        assert result["gate_status"] == "pass"

    def test_gate_status_unknown_when_missing(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert result["gate_status"] == "unknown"

    def test_gate_errors_from_gate_report_summary(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={"summary": {"errors": 3, "warnings": 1}})
        result = build_surface_handoff(tmp_path)
        assert result["gate_errors"] == 3
        assert result["gate_warnings"] == 1

    def test_agents_from_plan(self, tmp_path):
        plan = {
            "agents": [
                {"name": "code-reviewer", "scope": "review", "primary_paths": ["espalier/"]}
            ]
        }
        _write_reports(tmp_path, plan=plan, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert len(result["agents"]) == 1
        assert result["agents"][0]["name"] == "code-reviewer"
        assert result["agents"][0]["scope"] == "review"

    def test_commands_from_stable_actions(self, tmp_path):
        plan = {"stable_actions": {"test": ["pytest -q"], "audit": ["espalier audit ."]}}
        _write_reports(tmp_path, plan=plan, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        action_names = [c["action"] for c in result["commands"]]
        assert "test" in action_names
        assert "audit" in action_names

    def test_commands_empty_when_no_stable_actions(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert result["commands"] == []

    def test_profiles_from_plan(self, tmp_path):
        _write_reports(tmp_path, plan={"profiles": ["python_api"]}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert result["profiles"] == ["python_api"]

    def test_surface_mode_from_plan_config(self, tmp_path):
        _write_reports(tmp_path, plan={"config": {"surface_mode": "extended"}}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert result["surface_mode"] == "extended"

    def test_surface_mode_defaults_to_core(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert result["surface_mode"] == "core"

    def test_lane_count_from_plan_config(self, tmp_path):
        _write_reports(tmp_path, plan={"config": {"lane_count": 5}}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert result["lane_count"] == 5

    def test_lane_count_minimum_is_one(self, tmp_path):
        _write_reports(tmp_path, plan={"config": {"lane_count": 0}}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert result["lane_count"] >= 1

    def test_lane_count_defaults_to_3(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert result["lane_count"] == 3

    def test_owned_roots_always_present(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert ".claude/**" in result["owned_roots"]
        assert "cc/**" in result["owned_roots"]

    def test_non_destructive_rule_present(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert "non_destructive_rule" in result
        assert len(result["non_destructive_rule"]) > 0

    def test_agents_capped_at_ten(self, tmp_path):
        agents = [{"name": f"agent-{i}", "scope": "review", "primary_paths": []} for i in range(15)]
        _write_reports(tmp_path, plan={"agents": agents}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert len(result["agents"]) <= 10

    def test_agents_primary_paths_capped_at_five(self, tmp_path):
        agents = [{"name": "x", "scope": "review", "primary_paths": [f"path{i}/" for i in range(10)]}]
        _write_reports(tmp_path, plan={"agents": agents}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert len(result["agents"][0]["primary_paths"]) <= 5

    def test_missing_all_reports_still_returns_dict(self, tmp_path):
        result = build_surface_handoff(tmp_path)
        assert isinstance(result, dict)
        assert "repo_name" in result

    def test_unresolved_questions_from_plan(self, tmp_path):
        _write_reports(tmp_path, plan={"unresolved_questions": ["What is the test command?"]}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert "What is the test command?" in result["unresolved_questions"]

    def test_notes_from_plan(self, tmp_path):
        _write_reports(tmp_path, plan={"notes": ["Risk: large file"]}, fingerprint={}, gate={})
        result = build_surface_handoff(tmp_path)
        assert "Risk: large file" in result["notes"]


class TestRenderSurfaceHandoff:
    def _minimal_report(self, **kwargs) -> dict:
        base = {
            "repo_name": "test-repo",
            "surface_mode": "core",
            "gate_status": "pass",
            "gate_errors": 0,
            "gate_warnings": 0,
            "lane_count": 3,
            "languages": ["python"],
            "package_roots": ["espalier"],
            "entrypoints": ["espalier"],
            "profiles": ["python_api"],
            "owned_roots": [".claude/**", "cc/**"],
            "non_destructive_rule": "Preserve existing tooling.",
            "commands": [],
            "agents": [],
            "generated_docs": [],
            "unresolved_questions": [],
            "notes": [],
        }
        base.update(kwargs)
        return base

    def test_output_starts_with_surface_handoff_header(self):
        report = self._minimal_report()
        text = render_surface_handoff(report)
        assert text.startswith("# SURFACE HANDOFF")

    def test_output_includes_repo_name(self):
        report = self._minimal_report(repo_name="cool-project")
        text = render_surface_handoff(report)
        assert "cool-project" in text

    def test_output_includes_gate_status(self):
        report = self._minimal_report(gate_status="fail")
        text = render_surface_handoff(report)
        assert "fail" in text

    def test_output_includes_languages(self):
        report = self._minimal_report(languages=["python", "javascript"])
        text = render_surface_handoff(report)
        assert "python" in text
        assert "javascript" in text

    def test_output_includes_commands(self):
        report = self._minimal_report(commands=[{"action": "test", "command": "pytest -q"}])
        text = render_surface_handoff(report)
        assert "test" in text
        assert "pytest -q" in text

    def test_output_includes_agents(self):
        report = self._minimal_report(agents=[{
            "name": "code-reviewer",
            "scope": "review",
            "primary_paths": ["espalier/"],
        }])
        text = render_surface_handoff(report)
        assert "code-reviewer" in text
        assert "review" in text

    def test_none_listed_when_no_commands(self):
        report = self._minimal_report(commands=[])
        text = render_surface_handoff(report)
        assert "- none" in text

    def test_output_includes_owned_roots(self):
        report = self._minimal_report(owned_roots=[".claude/**", "tools/cc/**"])
        text = render_surface_handoff(report)
        assert ".claude/**" in text
        assert "tools/cc/**" in text

    def test_output_includes_unresolved_questions(self):
        report = self._minimal_report(unresolved_questions=["No test command found."])
        text = render_surface_handoff(report)
        assert "No test command found." in text

    def test_output_includes_ready_template(self):
        report = self._minimal_report()
        text = render_surface_handoff(report)
        assert "Ready-to-use handoff template" in text
        assert "Owned lane" in text

    def test_output_is_string(self):
        report = self._minimal_report()
        result = render_surface_handoff(report)
        assert isinstance(result, str)


class TestWriteSurfaceHandoff:
    def test_writes_to_default_location(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={})
        out = write_surface_handoff(tmp_path)
        assert out == tmp_path / "cc" / "SURFACE_HANDOFF.md"
        assert out.exists()

    def test_default_output_has_managed_marker(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={})
        out = write_surface_handoff(tmp_path)
        content = out.read_text(encoding="utf-8")
        assert MANAGED_MARKER in content

    def test_custom_output_path_used(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={})
        custom = tmp_path / "out" / "handoff.md"
        out = write_surface_handoff(tmp_path, output_path=custom)
        assert out == custom
        assert custom.exists()

    def test_custom_output_has_no_managed_marker(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={})
        custom = tmp_path / "handoff_custom.md"
        write_surface_handoff(tmp_path, output_path=custom)
        content = custom.read_text(encoding="utf-8")
        assert MANAGED_MARKER not in content

    def test_output_file_contains_surface_handoff_header(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={})
        out = write_surface_handoff(tmp_path)
        content = out.read_text(encoding="utf-8")
        assert "# SURFACE HANDOFF" in content

    def test_output_directory_created_if_missing(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={})
        custom = tmp_path / "deep" / "nested" / "out.md"
        assert not custom.parent.exists()
        write_surface_handoff(tmp_path, output_path=custom)
        assert custom.exists()

    def test_returns_path_object(self, tmp_path):
        _write_reports(tmp_path, plan={}, fingerprint={}, gate={})
        result = write_surface_handoff(tmp_path)
        assert isinstance(result, Path)


REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Slash command surface ──────────────────────────────────────────────────────


class TestSlashCommandSurface:
    def test_blueprint_command_does_not_exist(self):
        """.claude/commands/blueprint.md must not exist (merged into /handoff)."""
        assert not (REPO_ROOT / ".claude" / "commands" / "blueprint.md").exists()

    def test_handoff_command_exists(self):
        assert (REPO_ROOT / ".claude" / "commands" / "handoff.md").exists()

    def test_handoff_contains_record_decision(self):
        text = (REPO_ROOT / ".claude" / "commands" / "handoff.md").read_text(encoding="utf-8")
        assert "record --kind decision" in text

    def test_handoff_contains_record_alternative_rejected(self):
        text = (REPO_ROOT / ".claude" / "commands" / "handoff.md").read_text(encoding="utf-8")
        assert "record --kind alternative_rejected" in text

    def test_handoff_contains_record_pattern_discovered(self):
        text = (REPO_ROOT / ".claude" / "commands" / "handoff.md").read_text(encoding="utf-8")
        assert "record --kind pattern_discovered" in text

    def test_handoff_contains_finalize(self):
        text = (REPO_ROOT / ".claude" / "commands" / "handoff.md").read_text(encoding="utf-8")
        assert "cognitive_blueprint.py finalize" in text


# ── Rendered command docs ─────────────────────────────────────────────────────


class TestRenderedCommandDocs:
    def test_commands_md_does_not_list_blueprint(self):
        path = REPO_ROOT / "cc" / "COMMANDS.md"
        if path.exists():
            assert "/blueprint" not in path.read_text(encoding="utf-8")

    def test_pack_manifest_does_not_list_blueprint_md(self):
        path = REPO_ROOT / "cc" / "PACK_MANIFEST.txt"
        if path.exists():
            assert ".claude/commands/blueprint.md" not in path.read_text(encoding="utf-8")


# ── CLI parser ────────────────────────────────────────────────────────────────


class TestCliParserSurfaceHandoff:
    def test_surface_handoff_registered(self):
        from espalier.cli import build_parser
        parser = build_parser()
        # Should not raise
        args = parser.parse_args(["surface-handoff", ".", "--json"])
        assert hasattr(args, "func")

    def test_blueprint_handoff_not_in_parser_help(self):
        import io
        from espalier.cli import build_parser
        parser = build_parser()
        buf = io.StringIO()
        try:
            parser.parse_args(["--help"])
        except SystemExit:
            pass
        help_text = parser.format_help()
        assert "blueprint-handoff" not in help_text


# ── Release hygiene ───────────────────────────────────────────────────────────


class TestSurfaceHandoffReleaseHygiene:
    def test_surface_handoff_is_local_only(self):
        from espalier.surface_contract import is_local_only
        assert is_local_only("cc/SURFACE_HANDOFF.md")

    def test_surface_handoff_not_public_release_allowed(self):
        from espalier.surface_contract import is_public_release_allowed
        assert not is_public_release_allowed("cc/SURFACE_HANDOFF.md")
