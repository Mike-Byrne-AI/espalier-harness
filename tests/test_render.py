"""Tests for the user-facing ``render_*`` helpers across
``espalier.recovery``, ``espalier.reflection``, ``espalier.worktree``,
and the blueprint renderers.

Pins each renderer's defensive contract: non-empty output for the
happy path, graceful handling of hand-built reports with missing
fields, and inclusion of identifying tokens (e.g., ``RECOVERY``,
filenames). Without this guard a refactor that drops a defensive
``.get(..., default)`` would silently make a rendered report crash
mid-output, leaving the operator with a half-printed status that
hides the actual state of the harness.
"""
from __future__ import annotations




class TestRenderRecoveryReport:
    def test_render_recovery_report(self, harness_repo):
        """render_recovery_report returns a non-empty string."""
        from espalier.recovery import assess_repo_state, render_recovery_report

        report = assess_repo_state(harness_repo)
        text = render_recovery_report(report)
        assert isinstance(text, str)
        assert len(text) > 50
        assert "RECOVERY" in text

    def test_render_recovery_with_missing_files(self):
        """render_recovery_report handles a hand-built report with missing files."""
        from espalier.recovery import render_recovery_report

        report = {
            "repo_root": "/tmp/fake",
            "present": [],
            "missing": ["foo.md", "bar.json"],
            "plan_missing_docs": [],
            "manifest_missing_docs": [],
            "git": {"status": "unknown"},
            "mtimes": {},
            "recommendations": ["fix missing files"],
        }
        text = render_recovery_report(report)
        assert isinstance(text, str)
        assert len(text) > 0
        assert "foo.md" in text


class TestRenderReflectionReport:
    def test_render_reflection_report(self, harness_repo):
        """render_reflection_report returns a non-empty string."""
        from espalier.reflection import reflect_repo, render_reflection_report

        report = reflect_repo(harness_repo)
        text = render_reflection_report(report)
        assert isinstance(text, str)
        assert len(text) > 0
        assert "REFLECTION" in text


class TestRenderWorktreePlan:
    def test_render_worktree_plan(self, harness_repo):
        """render_worktree_plan returns a non-empty string with branch info."""
        from espalier.worktree import build_worktree_plan, render_worktree_plan

        plan = build_worktree_plan(harness_repo)
        text = render_worktree_plan(plan)
        assert isinstance(text, str)
        assert len(text) > 0
        assert "WORKTREE" in text


class TestRenderBlueprintMd:
    def test_render_blueprint_md(self, harness_repo):
        """render_blueprint_md returns a non-empty string mentioning session."""
        from espalier.cognitive_blueprint import render_blueprint_md, start_session

        bp = start_session(harness_repo)
        text = render_blueprint_md(bp)
        assert isinstance(text, str)
        assert len(text) > 0
        assert "session" in text.lower()


class TestRenderSurfaceHandoff:
    def test_render_surface_handoff(self, harness_repo):
        """render_surface_handoff returns a non-empty string."""
        from espalier.handoff import build_surface_handoff, render_surface_handoff

        report = build_surface_handoff(harness_repo)
        text = render_surface_handoff(report)
        assert isinstance(text, str)
        assert len(text) > 0
        assert "SURFACE HANDOFF" in text

    def test_write_surface_handoff_creates_file(self, harness_repo):
        """write_surface_handoff writes a non-empty file."""
        from espalier.handoff import write_surface_handoff

        path = write_surface_handoff(harness_repo)
        assert path.exists()
        assert len(path.read_text(encoding="utf-8")) > 0


class TestRenderReflectPass:
    def test_render_reflect_pass(self, harness_repo):
        """render_reflect_pass returns a non-empty string."""
        from espalier.reflect_protocol import render_reflect_pass, run_reflect_pass

        rp = run_reflect_pass(harness_repo)
        text = render_reflect_pass(rp)
        assert isinstance(text, str)
        assert len(text) > 0
        assert "REFLECT PASS" in text
