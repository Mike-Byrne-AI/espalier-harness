"""Tests for ``espalier.reflect_protocol`` validators —
``validate_command_tools`` and the end-to-end ``run_reflect_pass`` /
``render_reflect_pass`` pair that ``reflect_trigger`` invokes.

Pins the gap-detection rules: a command referencing a non-existent
script emits a HIGH ``ReflectFinding``; a command whose scripts all
exist does not. Without this contract a validator regression could
silently suppress real broken-path findings (the reflect pass
appears clean while documented command tool references rot), and
adopter onboarding fails on commands pointing at long-gone scripts.
"""
from __future__ import annotations



from espalier.reflect_protocol import (
    find_expected_ref_gaps,
    build_reference_matrix,
    render_reflect_pass,
    run_reflect_pass,
    validate_command_tools,
)


class TestValidateCommandTools:
    def test_no_findings_when_script_exists(self, harness_repo):
        """Command referencing an existing script has no findings."""
        cmds_dir = harness_repo / ".claude" / "commands"
        cmds_dir.mkdir(parents=True, exist_ok=True)
        # tools/cc/cognitive_blueprint.py exists in harness_repo fixture
        (cmds_dir / "test-cmd.md").write_text(
            "# Test Cmd\n\nRun: python tools/cc/cognitive_blueprint.py\n",
            encoding="utf-8",
        )
        findings = validate_command_tools(harness_repo)
        cmd_findings = [f for f in findings if "test-cmd" in " ".join(f.files)]
        assert len(cmd_findings) == 0

    def test_catches_missing_script(self, harness_repo):
        """Command referencing a missing script produces a high-severity finding."""
        cmds_dir = harness_repo / ".claude" / "commands"
        cmds_dir.mkdir(parents=True, exist_ok=True)
        (cmds_dir / "broken-cmd.md").write_text(
            "# Broken Cmd\n\nRun: python tools/cc/gone.py\n",
            encoding="utf-8",
        )
        findings = validate_command_tools(harness_repo)
        broken = [f for f in findings if "broken-cmd" in " ".join(f.files)]
        assert len(broken) > 0
        assert broken[0].severity == "high"


class TestFindExpectedRefGaps:
    def test_no_gaps_when_refs_present(self, harness_repo):
        """CLAUDE.md mentioning ESPALIER_MEMORY.md and docs/SHARP_EDGES.md produces no gaps."""
        (harness_repo / "CLAUDE.md").write_text(
            "# Harness\n\nSee ESPALIER_MEMORY.md and docs/SHARP_EDGES.md.\n", encoding="utf-8"
        )
        docs_dir = harness_repo / "docs"
        docs_dir.mkdir(exist_ok=True)
        (docs_dir / "SHARP_EDGES.md").write_text(
            "# Sharp Edges\n", encoding="utf-8"
        )
        matrix = build_reference_matrix(harness_repo)
        gaps = find_expected_ref_gaps(harness_repo, matrix)
        # No gap for CLAUDE.md → ESPALIER_MEMORY.md or CLAUDE.md → docs/SHARP_EDGES.md
        claude_gaps = [g for g in gaps if g[0] == "CLAUDE.md"]
        assert len(claude_gaps) == 0

    def test_returns_list_of_tuples(self, harness_repo):
        """find_expected_ref_gaps always returns a list of (source, target) tuples."""
        matrix = build_reference_matrix(harness_repo)
        gaps = find_expected_ref_gaps(harness_repo, matrix)
        assert isinstance(gaps, list)
        for item in gaps:
            assert len(item) == 2


class TestRunReflectPass:
    def test_returns_reflect_pass_object(self, harness_repo):
        """run_reflect_pass returns a ReflectPass with pass_number == 1."""
        rp = run_reflect_pass(harness_repo)
        assert rp.pass_number == 1
        assert hasattr(rp, "findings")
        assert hasattr(rp, "gap_count")

    def test_render_returns_string(self, harness_repo):
        """render_reflect_pass produces a non-empty string."""
        rp = run_reflect_pass(harness_repo)
        text = render_reflect_pass(rp)
        assert isinstance(text, str)
        assert len(text) > 10

    def test_reflect_deep_returns_dict(self, harness_repo):
        """reflect_deep combines legacy and structured pass into one dict."""
        from espalier.reflection import reflect_deep

        result = reflect_deep(harness_repo)
        assert isinstance(result, dict)
        # Must have at least one of the legacy keys or the new reflect_pass key
        assert "broken_markdown_links" in result or "reflect_pass" in result
