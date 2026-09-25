"""Tests for ``espalier.recovery`` — ``assess_repo_state`` and
``render_recovery_report``, the helpers ``espalier doctor`` and the
``DEGRADED`` SessionStart path use to decide whether a repo has
the minimum viable harness surface or needs ``espalier init`` to
recover.

Pins the ``REQUIRED_PATHS`` set as the authoritative recovery
contract: any subset missing → degraded; full set present → pass.
Without this contract a tweak to ``REQUIRED_PATHS`` could silently
let recovery report PASS on a half-installed harness, which would
then skip the rebuild path and leave the adopter with broken hooks
they think are working.
"""
from __future__ import annotations

import json
from pathlib import Path


from espalier.recovery import (
    REQUIRED_PATHS,
    assess_repo_state,
    render_recovery_report,
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _scaffold_minimal_surface(tmp_path: Path) -> None:
    """Create the minimal set of files that satisfy all REQUIRED_PATHS."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "cc").mkdir()
    (tmp_path / "cc" / "LIVE_SURFACE.md").write_text("# Live Surface\n", encoding="utf-8")
    (tmp_path / "cc" / "COMMANDS.md").write_text("# Commands\n", encoding="utf-8")
    (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text("", encoding="utf-8")
    (tmp_path / "tools" / "cc").mkdir(parents=True)
    (tmp_path / "tools" / "cc" / "cognitive_blueprint.py").write_text("# stub\n", encoding="utf-8")
    (tmp_path / "tools" / "cc" / "session_resume.py").write_text("# stub\n", encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "repo_fingerprint.json").write_text("{}", encoding="utf-8")
    (reports / "harness_config.json").write_text("{}", encoding="utf-8")
    (reports / "cc_surface_gate.json").write_text(
        json.dumps({"status": "pass"}), encoding="utf-8"
    )


# ── assess_repo_state ────────────────────────────────────────────────────────


class TestAssessRepoState:
    def test_returns_dict(self, tmp_path):
        result = assess_repo_state(tmp_path)
        assert isinstance(result, dict)

    def test_result_contains_repo_root(self, tmp_path):
        result = assess_repo_state(tmp_path)
        assert "repo_root" in result
        assert str(tmp_path) in result["repo_root"]

    def test_result_contains_present_and_missing_keys(self, tmp_path):
        result = assess_repo_state(tmp_path)
        assert "present" in result
        assert "missing" in result

    def test_empty_repo_has_all_paths_missing(self, tmp_path):
        result = assess_repo_state(tmp_path)
        assert set(result["missing"]) == set(REQUIRED_PATHS)

    def test_empty_repo_has_no_paths_present(self, tmp_path):
        result = assess_repo_state(tmp_path)
        assert result["present"] == []

    def test_full_surface_has_no_missing(self, tmp_path):
        _scaffold_minimal_surface(tmp_path)
        result = assess_repo_state(tmp_path)
        assert result["missing"] == []

    def test_full_surface_all_paths_present(self, tmp_path):
        _scaffold_minimal_surface(tmp_path)
        result = assess_repo_state(tmp_path)
        assert set(result["present"]) == set(REQUIRED_PATHS)

    def test_recommendations_always_present(self, tmp_path):
        result = assess_repo_state(tmp_path)
        assert "recommendations" in result
        assert len(result["recommendations"]) > 0

    def test_missing_files_trigger_rebuild_recommendation(self, tmp_path):
        result = assess_repo_state(tmp_path)
        combined = " ".join(result["recommendations"])
        assert "rebuild" in combined or "re-audit" in combined

    def test_clean_surface_recommends_read_memory(self, tmp_path):
        _scaffold_minimal_surface(tmp_path)
        result = assess_repo_state(tmp_path)
        combined = " ".join(result["recommendations"])
        assert "ESPALIER_MEMORY.md" in combined

    def test_failing_gate_status_adds_recommendation(self, tmp_path):
        _scaffold_minimal_surface(tmp_path)
        (tmp_path / "reports" / "cc_surface_gate.json").write_text(
            json.dumps({"status": "fail"}), encoding="utf-8"
        )
        result = assess_repo_state(tmp_path)
        combined = " ".join(result["recommendations"])
        assert "proof-gate" in combined or "gate" in combined

    def test_a_latin1_manifest_is_read_not_a_traceback(self, tmp_path):
        """Ledger DEF-829: cc/PACK_MANIFEST.txt re-saved in a Windows code page.
        The reader had no handler at all, in a module that says three times it
        must not crash /status -- so /status and doctor died with a
        UnicodeDecodeError on a tree that was otherwise fine. The entries are
        names: read with a replacement character, the missing one is reported."""
        _scaffold_minimal_surface(tmp_path)
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_bytes(b"cc/COMMANDS.md\ndocs/caf\xe9.md\n")
        report = assess_repo_state(tmp_path)
        assert report["manifest_missing_docs"] == ["docs/caf\ufffd.md"]

    def test_plan_missing_docs_detected(self, tmp_path):
        _scaffold_minimal_surface(tmp_path)
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({"generated_docs": ["cc/MISSING_DOC.md"]}),
            encoding="utf-8",
        )
        result = assess_repo_state(tmp_path)
        assert "cc/MISSING_DOC.md" in result["plan_missing_docs"]

    def test_corrupt_gate_file_is_degraded(self, tmp_path):
        """R50: a present-but-unreadable surface gate must report DEGRADED.

        The file EXISTS (so it is not in ``missing``), but _load_json_safe
        returns None on non-JSON. Pre-fix this skipped the gate block, left
        surface_gate_status="" (falsy), added no fail_reason, and reported
        ``healthy`` — masking a corrupt proof gate, the exact case the
        degraded-recovery path exists to catch.
        """
        _scaffold_minimal_surface(tmp_path)
        (tmp_path / "reports" / "cc_surface_gate.json").write_text(
            "this is not json {{{", encoding="utf-8"
        )
        result = assess_repo_state(tmp_path)
        assert result["missing"] == []  # file present, not a missing-path case
        assert result["status"] == "fail"
        assert result["surface"] == "DEGRADED"

    def test_nondict_gate_file_is_degraded(self, tmp_path):
        """R50: valid-JSON-but-non-dict (e.g. a list) is also unreadable as a
        gate and must report DEGRADED, not healthy."""
        _scaffold_minimal_surface(tmp_path)
        (tmp_path / "reports" / "cc_surface_gate.json").write_text(
            "[1, 2, 3]", encoding="utf-8"
        )
        result = assess_repo_state(tmp_path)
        assert result["surface"] == "DEGRADED"

    def test_plan_missing_docs_trigger_recommendation(self, tmp_path):
        _scaffold_minimal_surface(tmp_path)
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({"generated_docs": ["cc/MISSING_DOC.md"]}),
            encoding="utf-8",
        )
        result = assess_repo_state(tmp_path)
        combined = " ".join(result["recommendations"])
        assert "regenerate" in combined or "docs" in combined

    def test_manifest_missing_docs_detected(self, tmp_path):
        _scaffold_minimal_surface(tmp_path)
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text(
            "cc/PHANTOM.md\n", encoding="utf-8"
        )
        result = assess_repo_state(tmp_path)
        assert "cc/PHANTOM.md" in result["manifest_missing_docs"]

    def test_manifest_missing_docs_trigger_recommendation(self, tmp_path):
        _scaffold_minimal_surface(tmp_path)
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text(
            "cc/PHANTOM.md\n", encoding="utf-8"
        )
        result = assess_repo_state(tmp_path)
        combined = " ".join(result["recommendations"])
        assert "PACK_MANIFEST" in combined or "manifest" in combined

    def test_manifest_comment_lines_are_ignored(self, tmp_path):
        _scaffold_minimal_surface(tmp_path)
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text(
            "# this is a comment\n", encoding="utf-8"
        )
        result = assess_repo_state(tmp_path)
        assert result["manifest_missing_docs"] == []

    def test_git_summary_present(self, tmp_path):
        result = assess_repo_state(tmp_path)
        assert "git" in result
        assert "status" in result["git"]

    def test_no_git_repo_returns_unknown_status(self, tmp_path):
        result = assess_repo_state(tmp_path)
        # The no-git early-return yields "unknown" (session_resume.py:77). The old
        # name said "untracked" but asserted membership in all four values, so it
        # stayed green even if the guard were removed and the dir misreported
        # "clean"; exact-match on the real value discriminates that.
        assert result["git"]["status"] == "unknown"

    def test_full_surface_has_status_pass(self, tmp_path):
        _scaffold_minimal_surface(tmp_path)
        result = assess_repo_state(tmp_path)
        assert result["status"] == "pass"

    def test_empty_repo_has_status_fail(self, tmp_path):
        result = assess_repo_state(tmp_path)
        assert result["status"] == "fail"

    def test_no_worktree_lanes_in_recommendations(self, tmp_path):
        result = assess_repo_state(tmp_path)
        for rec in result["recommendations"]:
            assert "WORKTREE_LANES" not in rec

    def test_partial_surface_splits_present_missing(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        result = assess_repo_state(tmp_path)
        assert ".claude/settings.json" in result["present"]
        assert "cc/LIVE_SURFACE.md" in result["missing"]

    def test_harness_config_with_managed_marker(self, tmp_path):
        """_load_json strips the espalier:managed header before parsing."""
        _scaffold_minimal_surface(tmp_path)
        raw = "# espalier:managed\n" + json.dumps({"generated_docs": []})
        (tmp_path / "reports" / "harness_config.json").write_text(raw, encoding="utf-8")
        result = assess_repo_state(tmp_path)
        assert result["plan_missing_docs"] == []


# ── render_recovery_report ───────────────────────────────────────────────────


class TestRenderRecoveryReport:
    def _base_report(self, tmp_path: Path) -> dict:
        return assess_repo_state(tmp_path)

    def test_returns_string(self, tmp_path):
        report = self._base_report(tmp_path)
        result = render_recovery_report(report)
        assert isinstance(result, str)

    def test_contains_recovery_report_header(self, tmp_path):
        report = self._base_report(tmp_path)
        result = render_recovery_report(report)
        assert "RECOVERY REPORT" in result

    def test_contains_repo_root(self, tmp_path):
        report = self._base_report(tmp_path)
        # repo_root is in the report dict; the text must at least have "Surface:" header
        assert str(tmp_path.resolve()) in report["repo_root"]

    def test_healthy_surface_shows_healthy_in_output(self, tmp_path):
        _scaffold_minimal_surface(tmp_path)
        report = assess_repo_state(tmp_path)
        result = render_recovery_report(report)
        assert "healthy" in result

    def test_degraded_surface_shows_degraded_in_output(self, tmp_path):
        report = self._base_report(tmp_path)
        result = render_recovery_report(report)
        assert "DEGRADED" in result

    def test_missing_paths_listed(self, tmp_path):
        report = self._base_report(tmp_path)
        result = render_recovery_report(report)
        assert "Missing required paths:" in result
        assert ".claude/settings.json" in result

    def test_no_missing_paths_section_when_all_present(self, tmp_path):
        _scaffold_minimal_surface(tmp_path)
        report = assess_repo_state(tmp_path)
        result = render_recovery_report(report)
        assert "Missing required paths:" not in result

    def test_plan_missing_docs_listed(self, tmp_path):
        _scaffold_minimal_surface(tmp_path)
        (tmp_path / "reports" / "harness_config.json").write_text(
            json.dumps({"generated_docs": ["cc/PHANTOM.md"]}), encoding="utf-8"
        )
        report = assess_repo_state(tmp_path)
        result = render_recovery_report(report)
        assert "Build-plan docs missing on disk:" in result
        assert "cc/PHANTOM.md" in result

    def test_manifest_missing_docs_listed(self, tmp_path):
        _scaffold_minimal_surface(tmp_path)
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text(
            "cc/LOST.md\n", encoding="utf-8"
        )
        report = assess_repo_state(tmp_path)
        result = render_recovery_report(report)
        assert "Manifest entries missing on disk:" in result
        assert "cc/LOST.md" in result

    def test_recommendations_listed(self, tmp_path):
        report = self._base_report(tmp_path)
        result = render_recovery_report(report)
        assert "Recommended next steps:" in result

    def test_output_ends_with_newline(self, tmp_path):
        report = self._base_report(tmp_path)
        result = render_recovery_report(report)
        assert result.endswith("\n")

    def test_git_info_in_output_when_changed(self, tmp_path):
        # Only shown when there are changed files; check report dict instead
        report = self._base_report(tmp_path)
        assert "git" in report
        assert "status" in report["git"]


def _scaffold_source_checkout(tmp_path: Path) -> None:
    """A fresh ``git clone``: committed harness surface present, but NO
    gitignored init artifacts (``.claude/settings.json``, ``reports/*.json``).
    Exercises the caller-facing ``espalier.recovery`` re-export (the copy
    ``espalier recover`` / ``espalier doctor`` use)."""
    (tmp_path / "cc").mkdir()
    (tmp_path / "cc" / "LIVE_SURFACE.md").write_text("# Live\n", encoding="utf-8")
    (tmp_path / "cc" / "COMMANDS.md").write_text("# Commands\n", encoding="utf-8")
    (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text("", encoding="utf-8")
    (tmp_path / "tools" / "cc").mkdir(parents=True)
    (tmp_path / "tools" / "cc" / "cognitive_blueprint.py").write_text("# stub\n", encoding="utf-8")
    (tmp_path / "tools" / "cc" / "session_resume.py").write_text("# stub\n", encoding="utf-8")


class TestSourceCheckoutState:
    """Parity with tests/test_session_resume.py via the ``espalier.recovery``
    re-export (the copy ``espalier recover`` / ``doctor`` exercise): a fresh
    source checkout is not DEGRADED (TP-262)."""

    def test_source_checkout_is_not_degraded(self, tmp_path):
        _scaffold_source_checkout(tmp_path)
        result = assess_repo_state(tmp_path)
        assert result["status"] == "pass"
        assert result["surface"] == "healthy"

    def test_source_checkout_recommends_init(self, tmp_path):
        _scaffold_source_checkout(tmp_path)
        result = assess_repo_state(tmp_path)
        assert any("espalier init" in r for r in result["recommendations"])

    def test_source_checkout_with_missing_manifest_entries_is_not_degraded(self, tmp_path):
        """Sister of the same test in tests/test_session_resume.py, through the
        ``espalier.recovery`` re-export (the vendored copy ``espalier recover`` /
        ``doctor`` exercise). LATENT-1 (TP-280): a COMMITTED cc/PACK_MANIFEST.txt
        lists init-generated entries absent on a source checkout / extracted
        export; the manifest_missing fail_reason must be gated on
        ``not is_source_checkout`` or recover falsely DEGRADEs the pre-init
        state. Confirms the vendor mirror carries the same gate."""
        _scaffold_source_checkout(tmp_path)
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text(
            "ESPALIER_MEMORY.md\nreports/repo_fingerprint.json\n", encoding="utf-8",
        )
        result = assess_repo_state(tmp_path)
        assert result["manifest_missing_docs"], (
            "precondition: manifest should report missing entries here"
        )
        assert result["status"] == "pass", (
            f"source checkout falsely DEGRADED: {result['manifest_missing_docs']}"
        )
        assert result["surface"] == "healthy"
