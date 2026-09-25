"""Tests for ``tools/cc/session_resume.py`` — the canonical
session-resume engine the SessionStart hook delegates to (and the
``/context-load`` slash command re-triggers mid-session).

Pins ``assess_repo_state`` against the minimum-valid harness
scaffold and the three render-paths (``render_context_report``,
``render_recovery_report``, ``render_status_report``) it dispatches
to based on detected surface state. Without this contract a regression
in the surface-state classifier could silently route a healthy repo
through the DEGRADED path (or vice-versa), producing the wrong
6-line orientation report and leaving the operator confused about
what state the harness is actually in.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.cc.session_resume import (
    REQUIRED_PATHS,
    assess_repo_state,
    render_context_report,
    render_recovery_report,
    render_status_report,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _scaffold_minimal_harness(tmp_path: Path) -> None:
    """Create the minimum set of files to make assess_repo_state return pass."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "cc").mkdir()
    (tmp_path / "cc" / "LIVE_SURFACE.md").write_text("# Live\n", encoding="utf-8")
    (tmp_path / "cc" / "COMMANDS.md").write_text("# Commands\n", encoding="utf-8")
    (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text("", encoding="utf-8")
    (tmp_path / "tools" / "cc").mkdir(parents=True)
    (tmp_path / "tools" / "cc" / "cognitive_blueprint.py").write_text("# stub\n", encoding="utf-8")
    (tmp_path / "tools" / "cc" / "session_resume.py").write_text("# stub\n", encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "repo_fingerprint.json").write_text('{"repo_name": "test"}', encoding="utf-8")
    (reports / "harness_config.json").write_text("{}", encoding="utf-8")
    (reports / "cc_surface_gate.json").write_text('{"status": "pass"}', encoding="utf-8")


# ── assess_repo_state ──────────────────────────────────────────────────────


class TestAssessRepoState:
    def test_returns_dict(self, tmp_path):
        result = assess_repo_state(tmp_path)
        assert isinstance(result, dict)

    def test_has_status_key(self, tmp_path):
        result = assess_repo_state(tmp_path)
        assert "status" in result

    def test_empty_repo_status_is_fail(self, tmp_path):
        result = assess_repo_state(tmp_path)
        assert result["status"] == "fail"

    def test_empty_repo_lists_all_missing_paths(self, tmp_path):
        result = assess_repo_state(tmp_path)
        assert set(result["missing"]) == set(REQUIRED_PATHS)

    def test_minimal_harness_status_is_pass(self, tmp_path):
        _scaffold_minimal_harness(tmp_path)
        result = assess_repo_state(tmp_path)
        assert result["status"] == "pass"

    def test_minimal_harness_surface_is_healthy(self, tmp_path):
        _scaffold_minimal_harness(tmp_path)
        result = assess_repo_state(tmp_path)
        assert result["surface"] == "healthy"

    def test_empty_repo_surface_is_degraded(self, tmp_path):
        result = assess_repo_state(tmp_path)
        assert result["surface"] == "DEGRADED"

    def test_failing_surface_gate_makes_status_fail(self, tmp_path):
        _scaffold_minimal_harness(tmp_path)
        (tmp_path / "reports" / "cc_surface_gate.json").write_text(
            '{"status": "fail"}', encoding="utf-8"
        )
        result = assess_repo_state(tmp_path)
        assert result["status"] == "fail"

    def test_missing_promised_docs_make_status_fail(self, tmp_path):
        _scaffold_minimal_harness(tmp_path)
        (tmp_path / "reports" / "harness_config.json").write_text(
            '{"generated_docs": ["cc/MISSING_DOC.md"]}', encoding="utf-8"
        )
        result = assess_repo_state(tmp_path)
        assert result["status"] == "fail"
        assert "cc/MISSING_DOC.md" in result["plan_missing_docs"]

    def test_missing_manifest_entries_make_status_fail(self, tmp_path):
        _scaffold_minimal_harness(tmp_path)
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text(
            "cc/MISSING_MANIFEST_ENTRY.md\n", encoding="utf-8"
        )
        result = assess_repo_state(tmp_path)
        assert result["status"] == "fail"
        assert "cc/MISSING_MANIFEST_ENTRY.md" in result["manifest_missing_docs"]

    def test_corrupt_required_report_fails_closed(self, tmp_path):
        # F7 (CV2): a present-but-unparseable required report must fail CLOSED
        # (surface=DEGRADED), not report healthy — parity with the cc_surface_gate
        # branch, which repo_fingerprint/harness_config previously lacked.
        _scaffold_minimal_harness(tmp_path)
        (tmp_path / "reports" / "harness_config.json").write_text(
            "{ not valid json", encoding="utf-8"
        )
        result = assess_repo_state(tmp_path)
        assert result["status"] == "fail"
        assert result["surface"] == "DEGRADED"

    def test_null_languages_field_does_not_crash(self, tmp_path):
        # F6 (CV2): repo_fingerprint.languages = null (valid JSON, wrong field type)
        # must not raise an uncaught TypeError via _fingerprint_summary.
        _scaffold_minimal_harness(tmp_path)
        (tmp_path / "reports" / "repo_fingerprint.json").write_text(
            '{"repo_name": "t", "languages": null}', encoding="utf-8"
        )
        result = assess_repo_state(tmp_path)  # must not raise
        assert result["fingerprint"]["languages"] == []

    def test_null_generated_docs_field_does_not_crash(self, tmp_path):
        # F6 (CV2): harness_config.generated_docs = null must not crash _plan_missing_docs.
        _scaffold_minimal_harness(tmp_path)
        (tmp_path / "reports" / "harness_config.json").write_text(
            '{"generated_docs": null}', encoding="utf-8"
        )
        result = assess_repo_state(tmp_path)  # must not raise
        assert result["plan_missing_docs"] == []

    def test_dirty_git_does_not_make_status_fail(self, tmp_path):
        _scaffold_minimal_harness(tmp_path)
        result = assess_repo_state(tmp_path)
        # The tmp_path has no .git, so git status is "unknown", but status is still pass
        assert result["status"] == "pass"

    @pytest.mark.parametrize("subreport", ["blueprint", "fingerprint", "memory", "git"])
    def test_result_subreport_present_with_status(self, tmp_path, subreport):
        """Each homogeneous sub-report dict carries a 'status' key."""
        result = assess_repo_state(tmp_path)
        assert subreport in result, f"missing sub-report {subreport!r}"
        assert "status" in result[subreport], (
            f"sub-report {subreport!r} missing required 'status' field"
        )

    def test_result_has_sharp_edges_key(self, tmp_path):
        result = assess_repo_state(tmp_path)
        assert "sharp_edges" in result

    def test_result_has_counts_key(self, tmp_path):
        result = assess_repo_state(tmp_path)
        assert "counts" in result
        assert "agents" in result["counts"]
        assert "commands" in result["counts"]

    def test_result_has_recommendations(self, tmp_path):
        result = assess_repo_state(tmp_path)
        assert "recommendations" in result
        assert len(result["recommendations"]) > 0


# ── render_recovery_report ────────────────────────────────────────────────


class TestRenderRecoveryReport:
    def test_returns_string(self, tmp_path):
        report = assess_repo_state(tmp_path)
        assert isinstance(render_recovery_report(report), str)

    def test_starts_with_recovery_report(self, tmp_path):
        report = assess_repo_state(tmp_path)
        text = render_recovery_report(report)
        assert text.startswith("RECOVERY REPORT")

    def test_ascii_only_no_box_drawing(self, tmp_path):
        report = assess_repo_state(tmp_path)
        text = render_recovery_report(report)
        for char in text:
            assert ord(char) < 128, f"Non-ASCII character found: {char!r} (U+{ord(char):04X})"

    def test_separator_is_ascii_equals(self, tmp_path):
        report = assess_repo_state(tmp_path)
        text = render_recovery_report(report)
        assert "===============" in text

    def test_lists_missing_paths_when_degraded(self, tmp_path):
        report = assess_repo_state(tmp_path)
        text = render_recovery_report(report)
        assert "Missing required paths:" in text

    def test_no_missing_paths_section_on_healthy_repo(self, tmp_path):
        _scaffold_minimal_harness(tmp_path)
        report = assess_repo_state(tmp_path)
        text = render_recovery_report(report)
        assert "Missing required paths:" not in text

    def test_includes_surface_field(self, tmp_path):
        report = assess_repo_state(tmp_path)
        text = render_recovery_report(report)
        assert "Surface:" in text

    def test_includes_recommendations(self, tmp_path):
        report = assess_repo_state(tmp_path)
        text = render_recovery_report(report)
        assert "Recommended next steps:" in text

    def test_no_worktree_lanes_in_recommendations(self, tmp_path):
        _scaffold_minimal_harness(tmp_path)
        report = assess_repo_state(tmp_path)
        text = render_recovery_report(report)
        assert "WORKTREE_LANES" not in text

    def test_no_worktree_lanes_in_degraded_recommendations(self, tmp_path):
        report = assess_repo_state(tmp_path)
        text = render_recovery_report(report)
        assert "WORKTREE_LANES" not in text


# ── render_status_report ──────────────────────────────────────────────────


class TestRenderStatusReport:
    def test_returns_string(self, tmp_path):
        report = assess_repo_state(tmp_path)
        assert isinstance(render_status_report(report), str)

    def test_contains_repo_field(self, tmp_path):
        report = assess_repo_state(tmp_path)
        text = render_status_report(report)
        assert "REPO:" in text

    def test_contains_surface_field(self, tmp_path):
        report = assess_repo_state(tmp_path)
        text = render_status_report(report)
        assert "SURFACE:" in text

    def test_ascii_only(self, tmp_path):
        report = assess_repo_state(tmp_path)
        text = render_status_report(report)
        for char in text:
            assert ord(char) < 128


# ── render_context_report ─────────────────────────────────────────────────


class TestRenderContextReport:
    def test_returns_string(self, tmp_path):
        report = assess_repo_state(tmp_path)
        assert isinstance(render_context_report(report), str)

    def test_has_six_lines(self, tmp_path):
        report = assess_repo_state(tmp_path)
        text = render_context_report(report)
        lines = [ln for ln in text.strip().splitlines() if ln]
        assert len(lines) == 6

    def test_contains_repo_field(self, tmp_path):
        report = assess_repo_state(tmp_path)
        text = render_context_report(report)
        assert "REPO:" in text

    def test_contains_next_field(self, tmp_path):
        report = assess_repo_state(tmp_path)
        text = render_context_report(report)
        assert "NEXT:" in text


# ── CLI entry point ───────────────────────────────────────────────────────


class TestCLIStatusMode:
    def test_mode_status_exits_zero_on_empty_repo(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "cc" / "session_resume.py"),
             "--mode", "status", str(tmp_path)],
            capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0

    def test_mode_status_prints_compact_output(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "cc" / "session_resume.py"),
             "--mode", "status", str(tmp_path)],
            capture_output=True, text=True, encoding="utf-8",
        )
        assert "REPO:" in result.stdout
        assert "SURFACE:" in result.stdout


class TestCLIRecoverMode:
    def test_mode_recover_json_exits_one_for_degraded_repo(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "cc" / "session_resume.py"),
             "--mode", "recover", "--json", str(tmp_path)],
            capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 1

    def test_mode_recover_json_is_valid_json(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "cc" / "session_resume.py"),
             "--mode", "recover", "--json", str(tmp_path)],
            capture_output=True, text=True, encoding="utf-8",
        )
        data = json.loads(result.stdout)
        assert "status" in data

    def test_mode_recover_json_exits_zero_for_healthy_repo(self, tmp_path):
        _scaffold_minimal_harness(tmp_path)
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "cc" / "session_resume.py"),
             "--mode", "recover", "--json", str(tmp_path)],
            capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0


class TestCLINormalMode:
    def test_mode_normal_does_not_claim_session_start_when_blueprint_missing(self, tmp_path):
        _scaffold_minimal_harness(tmp_path)
        # cognitive_blueprint.py stub doesn't output valid JSON for "start"
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "cc" / "session_resume.py"),
             "--mode", "normal", str(tmp_path)],
            capture_output=True, text=True, encoding="utf-8",
        )
        # Should not crash and should print context report
        assert "REPO:" in result.stdout
        assert result.returncode == 0


def _scaffold_healthy_with_real_blueprint(tmp_path: Path) -> None:
    """A minimal *healthy* surface, but with the REAL cognitive_blueprint.py
    (+ stdlib deps) so ``_start_session`` can actually create a node — the
    minimal scaffold stubs it."""
    _scaffold_minimal_harness(tmp_path)
    tools_cc = tmp_path / "tools" / "cc"
    src = REPO_ROOT / "tools" / "cc"
    for fname in ("cognitive_blueprint.py", "_blueprint_limits.py", "_json_safe.py", "_paths.py"):
        (tools_cc / fname).write_bytes((src / fname).read_bytes())
    (tmp_path / "cc" / "blueprints").mkdir(parents=True, exist_ok=True)


def _node_count(tmp_path: Path) -> int:
    """Blueprint nodes on disk (excludes the latest.json pointer)."""
    bp = tmp_path / "cc" / "blueprints"
    if not bp.exists():
        return 0
    return len([p for p in bp.glob("*.json") if p.name != "latest.json"])


class TestNormalModeChainAdvancement:
    """``--mode normal`` (the /context-load engine) no longer routinely
    advances the blueprint chain — the SessionStart hook owns that. It
    bootstraps a node ONLY when none exists; with a blueprint present it is a
    pure, side-effect-free reorient.

    Earn-the-red: under the old unconditional ``_start_session`` call, the
    first test below would see node_count grow by one (a fresh node every
    /context-load run), failing the equality assertion.
    """

    def test_does_not_advance_chain_when_blueprint_exists(self, tmp_path):
        _scaffold_healthy_with_real_blueprint(tmp_path)
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
        # Seed an existing blueprint node.
        subprocess.run(
            [sys.executable, str(tmp_path / "tools" / "cc" / "cognitive_blueprint.py"),
             "start"],
            cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=15, encoding="utf-8",
        )
        before = _node_count(tmp_path)
        assert before >= 1, "precondition: a blueprint node exists"

        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "cc" / "session_resume.py"),
             "--mode", "normal", str(tmp_path)],
            cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=15, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        assert "REPO:" in result.stdout
        assert _node_count(tmp_path) == before, (
            "context-load must NOT start a new node when one already exists"
        )

    def test_bootstraps_a_node_when_blueprint_missing(self, tmp_path):
        _scaffold_healthy_with_real_blueprint(tmp_path)
        assert _node_count(tmp_path) == 0, "precondition: no blueprint yet"
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}

        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "cc" / "session_resume.py"),
             "--mode", "normal", str(tmp_path)],
            cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=15, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        assert _node_count(tmp_path) == 1, (
            "context-load must bootstrap exactly one node when none exists"
        )

    def test_does_not_clobber_present_but_unreadable_blueprint(self, tmp_path):
        """A present-but-UNREADABLE latest.json (oversize → reported "missing")
        must NOT be bootstrapped over. The bootstrap keys on the file's
        PRESENCE, matching session_start._blueprint_present.

        Earn-the-red: under the prior `status == "missing"` gate, the oversize
        file reported missing and _start_session clobbered it.
        """
        _scaffold_healthy_with_real_blueprint(tmp_path)
        latest = tmp_path / "cc" / "blueprints" / "latest.json"
        sentinel = '{"session_id": "deadbeef", "x": "' + ("z" * 200_000) + '"}'
        latest.write_text(sentinel, encoding="utf-8")
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}

        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "cc" / "session_resume.py"),
             "--mode", "normal", str(tmp_path)],
            cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=15, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        assert latest.read_text(encoding="utf-8") == sentinel, (
            "context-load clobbered a present-but-unreadable latest.json"
        )
        assert _node_count(tmp_path) == 0


class TestBlueprintSummaryParsesLoadJsonOutput:
    """Post-Round-3 regression: ``_blueprint_summary`` invokes
    ``cognitive_blueprint.py load`` to read the latest blueprint. Pre-fix
    the call was missing the ``--json`` flag, so the helper consumed the
    human-readable markdown banner and silently fell through to
    ``status="invalid"`` on EVERY invocation — the operator-visible
    ``LAST: blueprint invalid`` was a permanent false alarm.
    """

    def test_blueprint_summary_subprocess_argv_includes_json_flag(self):
        """Source-level contract: ``--json`` MUST appear next to ``load``
        in the session_resume subprocess invocation. Catches a future
        refactor that drops the flag at the source layer (cheap; no
        subprocess scaffolding required)."""
        src = (REPO_ROOT / "tools" / "cc" / "session_resume.py").read_text(
            encoding="utf-8"
        )
        assert '"load", "--json"' in src or "'load', '--json'" in src, (
            "session_resume._blueprint_summary's subprocess call must pass "
            "--json to cognitive_blueprint.py load; without it the parser "
            "consumes a markdown banner and reports status='invalid' "
            "permanently."
        )

    def test_blueprint_summary_returns_found_on_real_repo_with_active_blueprint(self):
        """Subprocess-level contract: against the real REPO_ROOT (which
        has a live cognitive_blueprint.py and at least one blueprint in
        cc/blueprints/), session_resume must NOT report
        ``blueprint invalid``.

        Skipped if the live repo has no blueprint at all (genuine empty
        state — not the bug this test pins)."""
        from tools.cc.session_resume import _blueprint_summary  # type: ignore

        # If no blueprint exists yet, the bug under test isn't reachable —
        # _blueprint_summary returns "missing", not "invalid".
        blueprints_dir = REPO_ROOT / "cc" / "blueprints"
        if not blueprints_dir.exists() or not any(blueprints_dir.glob("*.json")):
            pytest.skip("live repo has no blueprint; bug not reachable")

        result = _blueprint_summary(REPO_ROOT)
        assert result.get("status") != "invalid", (
            f"_blueprint_summary returned status='invalid' on a live repo "
            f"with an existing blueprint. Pre-Round-3 this was permanently "
            f"the case because the subprocess invocation was missing "
            f"--json. Full result: {result!r}"
        )


def _scaffold_source_checkout(tmp_path: Path) -> None:
    """A fresh ``git clone``: committed harness surface present, but NO
    gitignored init artifacts (``.claude/settings.json``, ``reports/*.json``)."""
    (tmp_path / "cc").mkdir()
    (tmp_path / "cc" / "LIVE_SURFACE.md").write_text("# Live\n", encoding="utf-8")
    (tmp_path / "cc" / "COMMANDS.md").write_text("# Commands\n", encoding="utf-8")
    (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text("", encoding="utf-8")
    (tmp_path / "tools" / "cc").mkdir(parents=True)
    (tmp_path / "tools" / "cc" / "cognitive_blueprint.py").write_text("# stub\n", encoding="utf-8")
    (tmp_path / "tools" / "cc" / "session_resume.py").write_text("# stub\n", encoding="utf-8")


class TestSourceCheckoutState:
    """A fresh source checkout (committed surface present, no init artifacts) is
    the expected pre-init state — it must NOT report DEGRADED (TP-262)."""

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
        """LATENT-1 (TP-280): cc/PACK_MANIFEST.txt is COMMITTED, so on a source
        checkout / extracted release export it lists init-generated entries
        (reports/*.json, .claude/settings.json) that are absent pre-init. The
        manifest_missing fail_reason must be gated on ``not is_source_checkout``
        — mirroring the REQUIRED_PATHS ``missing`` branch — or recover falsely
        DEGRADEs the expected pre-init state (exit 1, strictly worse than the
        gated `missing` branch's exit 0).

        Earn-the-red: the manifest genuinely reports missing entries here
        (asserted below); reverting the ``and not is_source_checkout`` gate
        flips status to ``fail`` / DEGRADED.
        """
        _scaffold_source_checkout(tmp_path)
        # The committed manifest promises init-generated artifacts (the shape a
        # real release archive ships); none exist on the pre-init tree.
        (tmp_path / "cc" / "PACK_MANIFEST.txt").write_text(
            "ESPALIER_MEMORY.md\nreports/repo_fingerprint.json\n", encoding="utf-8",
        )
        result = assess_repo_state(tmp_path)
        # Precondition: the gate SUPPRESSES the fail_reason, it does not erase
        # the raw signal — so this assertion actually exercises the gate.
        assert result["manifest_missing_docs"], (
            "precondition: manifest should report missing entries here"
        )
        assert result["status"] == "pass", (
            f"source checkout falsely DEGRADED: {result['manifest_missing_docs']}"
        )
        assert result["surface"] == "healthy"
