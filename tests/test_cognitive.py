"""Tests for ``tools/cc/cognitive_blueprint.py`` — the CLI invoked by
the ``stop_gate`` / ``subagent_stop`` / ``reflect_trigger`` hooks to
record session reasoning to the active blueprint.

Pins the record-reflect subcommand contract: reflect-pass JSON written
to the blueprint round-trips through subsequent reads. Without this
guard a regression in the CLI argument parser or JSON serializer
would silently drop reflect findings, breaking the cross-session
reasoning chain that ``post_compact`` relies on for context re-inject.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


BLUEPRINT_SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "cc" / "cognitive_blueprint.py"

SAMPLE_REFLECT_REPORT = {
    "pass_number": 1,
    "timestamp": "2026-04-16T00:00:00+00:00",
    "files_analyzed": 12,
    "total_references": 20,
    "cross_ref_density": 1.67,
    "gap_count": 2,
    "orphan_count": 1,
    "findings": [
        {"kind": "gap", "severity": "high", "description": "Broken link in CLAUDE.md: missing.md"},
        {"kind": "orphan", "severity": "medium", "description": "cc/ORPHAN.md is not referenced"},
    ],
}


def run_blueprint(args: list[str], cwd: Path, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BLUEPRINT_SCRIPT)] + args,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(cwd), encoding="utf-8",
    )


class TestRecordReflect:
    """Verify record-reflect subcommand stores reflect pass data in the blueprint."""

    def test_record_reflect_adds_to_reflect_passes(self, tmp_path):
        """record-reflect appends the report to bp['reflect_passes']."""
        (tmp_path / "cc" / "blueprints").mkdir(parents=True)
        run_blueprint(["start"], cwd=tmp_path)

        result = run_blueprint(
            ["record-reflect", "--data", json.dumps(SAMPLE_REFLECT_REPORT)],
            cwd=tmp_path,
        )
        assert result.returncode == 0
        assert "Recorded reflect pass 1" in result.stdout

        bp = json.loads((tmp_path / "cc" / "blueprints" / "latest.json").read_text(encoding="utf-8"))
        assert len(bp["reflect_passes"]) == 1
        assert bp["reflect_passes"][0]["gap_count"] == 2
        assert len(bp["reflect_passes"][0]["findings"]) == 2

    def test_record_reflect_projects_unknown_keys_off_pass_and_findings(self, tmp_path):
        """TP-151 C-3: the writer projects the report onto the known
        ReflectPass / ReflectFinding field sets, so a producer that adds an
        extra key cannot poison the on-disk blueprint (defense in depth with
        the library reader-side _only() filter in from_dict)."""
        (tmp_path / "cc" / "blueprints").mkdir(parents=True)
        run_blueprint(["start"], cwd=tmp_path)

        poisoned = {
            **SAMPLE_REFLECT_REPORT,
            "bogus_pass_key": "should be dropped",
            "findings": [
                {
                    "kind": "gap",
                    "severity": "high",
                    "description": "d",
                    "bogus_finding_key": "should be dropped",
                },
            ],
        }
        result = run_blueprint(
            ["record-reflect", "--data", json.dumps(poisoned)],
            cwd=tmp_path,
        )
        assert result.returncode == 0

        bp = json.loads((tmp_path / "cc" / "blueprints" / "latest.json").read_text(encoding="utf-8"))
        stored = bp["reflect_passes"][0]
        assert "bogus_pass_key" not in stored, (
            "writer must project unknown top-level keys off the reflect pass"
        )
        assert "bogus_finding_key" not in stored["findings"][0], (
            "writer must project unknown keys off each finding"
        )
        # Known data is preserved through the projection.
        assert stored["gap_count"] == 2
        assert stored["findings"][0]["kind"] == "gap"

    def test_record_reflect_updates_gap_convergence(self, tmp_path):
        """Each record-reflect call appends the gap count to gap_convergence."""
        (tmp_path / "cc" / "blueprints").mkdir(parents=True)
        run_blueprint(["start"], cwd=tmp_path)

        report1 = {**SAMPLE_REFLECT_REPORT, "gap_count": 3}
        report2 = {**SAMPLE_REFLECT_REPORT, "pass_number": 2, "gap_count": 1}
        run_blueprint(["record-reflect", "--data", json.dumps(report1)], cwd=tmp_path)
        run_blueprint(["record-reflect", "--data", json.dumps(report2)], cwd=tmp_path)

        bp = json.loads((tmp_path / "cc" / "blueprints" / "latest.json").read_text(encoding="utf-8"))
        assert bp["gap_convergence"] == [3, 1]

    def test_record_reflect_no_active_session_returns_error(self, tmp_path):
        """record-reflect with no active blueprint exits non-zero."""
        (tmp_path / "cc" / "blueprints").mkdir(parents=True)
        result = run_blueprint(
            ["record-reflect", "--data", json.dumps(SAMPLE_REFLECT_REPORT)],
            cwd=tmp_path,
        )
        assert result.returncode != 0
        assert "No active session" in result.stderr

    def test_record_reflect_invalid_json_returns_error(self, tmp_path):
        """record-reflect with malformed JSON exits non-zero."""
        (tmp_path / "cc" / "blueprints").mkdir(parents=True)
        run_blueprint(["start"], cwd=tmp_path)
        result = run_blueprint(["record-reflect", "--data", "{bad json"], cwd=tmp_path)
        assert result.returncode != 0
        assert "Invalid JSON" in result.stderr

    def test_finalize_surfaces_high_severity_findings_as_fragments(self, tmp_path):
        """After record-reflect, finalize generates continuation fragments from high findings."""
        (tmp_path / "cc" / "blueprints").mkdir(parents=True)
        run_blueprint(["start"], cwd=tmp_path)
        run_blueprint(
            ["record-reflect", "--data", json.dumps(SAMPLE_REFLECT_REPORT)],
            cwd=tmp_path,
        )
        run_blueprint(["finalize"], cwd=tmp_path)

        bp = json.loads((tmp_path / "cc" / "blueprints" / "latest.json").read_text(encoding="utf-8"))
        # High-severity gap should appear as [unresolved] fragment
        assert any("unresolved" in f for f in bp["continuation_fragments"])
        assert any("Broken link" in f for f in bp["continuation_fragments"])

    def test_record_reflect_via_stdin(self, tmp_path):
        """record-reflect reads JSON from stdin when --data is omitted."""
        (tmp_path / "cc" / "blueprints").mkdir(parents=True)
        run_blueprint(["start"], cwd=tmp_path)

        result = run_blueprint(
            ["record-reflect"],
            cwd=tmp_path,
            stdin=json.dumps(SAMPLE_REFLECT_REPORT),
        )
        assert result.returncode == 0
        bp = json.loads((tmp_path / "cc" / "blueprints" / "latest.json").read_text(encoding="utf-8"))
        assert len(bp["reflect_passes"]) == 1


class TestLoadMalformedTolerance:
    """``load`` priming must not crash on a hand-edited / older blueprint whose
    reasoning entries are missing fields (DR8 round-8: ``cmd_load`` used raw
    ``e["kind"]`` / ``d['description']`` subscripts that raised KeyError, killing
    session-start priming on the first malformed entry)."""

    def test_load_tolerates_reasoning_entries_missing_fields(self, tmp_path):
        bp_dir = tmp_path / "cc" / "blueprints"
        bp_dir.mkdir(parents=True)
        blueprint = {
            "session_id": "dr8-malformed",
            "timestamp": "2026-06-19T00:00:00+00:00",
            "accumulated_depth": 1,
            "continuation_fragments": [],
            "reasoning_entries": [
                "i am a bare string, not a dict",              # non-dict element
                None,                                          # null element
                {"description": "entry with no kind field"},   # missing 'kind'
                {"kind": "decision"},                          # decision missing 'description'
                {"kind": "decision", "description": "a real decision"},
            ],
        }
        (bp_dir / "latest.json").write_text(json.dumps(blueprint), encoding="utf-8")
        # Pin the repo root to the tmp tree so _load_latest reads our crafted
        # blueprint, not the host's real one (CLAUDE_PROJECT_DIR wins in _repo_root).
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
        result = subprocess.run(
            [sys.executable, str(BLUEPRINT_SCRIPT), "load"],
            capture_output=True, text=True, timeout=10, cwd=str(tmp_path), env=env, encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        assert "KeyError" not in result.stderr
        assert "Traceback" not in result.stderr
        assert "Session Context" in result.stdout
        # the well-formed decision still renders; the field-less ones are skipped
        assert "a real decision" in result.stdout


def _import_hook_cb():
    """Import ``tools/cc/cognitive_blueprint.py`` as a module for direct unit
    calls — the CLI reader refuses an oversized blueprint, so the writer-cap must
    be exercised in-process rather than via a pre-seeded file."""
    sys.path.insert(0, str(BLUEPRINT_SCRIPT.parent))
    sys.modules.pop("cognitive_blueprint", None)
    import cognitive_blueprint  # type: ignore[import-not-found]
    return cognitive_blueprint


class TestHookTruncateCapCoversAllLists:
    """D-2: the hook writer-cap truncates EVERY writable list, not just the first
    three — else a continuation_fragments-dominated blueprint writes >cap and the
    reader silently refuses it on next load (total continuity loss)."""

    def test_continuation_fragments_dominated_truncates_under_cap(self):
        cb = _import_hook_cb()
        bp = {
            "reasoning_entries": [], "reflect_passes": [], "action_justifications": [],
            "continuation_fragments": ["y" * 500 for _ in range(600)],
            "gap_convergence": [], "cross_ref_density_trend": [],
        }
        out = cb._truncate_to_cap(bp)
        size = len((json.dumps(out, indent=2) + "\n").encode("utf-8"))
        assert size <= cb._BLUEPRINT_MAX_SIZE
        assert len(out["continuation_fragments"]) < 600  # oldest dropped to fit


class TestRecordCarryForwardPromotion:
    """D-3: `record --carry-forward` on an existing entry PROMOTES the pin rather
    than silently skipping it as a content duplicate (the TP-243 idempotency guard
    excluded carry_forward from identity, so it never promoted)."""

    def _entries(self, tmp_path):
        latest = tmp_path / "cc" / "blueprints" / "latest.json"
        return json.loads(latest.read_text(encoding="utf-8"))["reasoning_entries"]

    def test_carry_forward_promotes_existing_unpinned_entry(self, tmp_path):
        (tmp_path / "cc" / "blueprints").mkdir(parents=True)
        run_blueprint(["start"], cwd=tmp_path)
        r1 = run_blueprint(["record", "--kind", "decision", "--description", "pin me"], cwd=tmp_path)
        assert r1.returncode == 0
        assert self._entries(tmp_path)[-1]["carry_forward"] is False
        r2 = run_blueprint(
            ["record", "--kind", "decision", "--description", "pin me", "--carry-forward"],
            cwd=tmp_path,
        )
        assert r2.returncode == 0
        assert "Promoted" in r2.stdout
        matches = [e for e in self._entries(tmp_path) if e["description"] == "pin me"]
        assert len(matches) == 1, "must not create a duplicate entry"
        assert matches[0]["carry_forward"] is True, "existing entry must be promoted to pinned"

    def test_plain_duplicate_without_carry_forward_still_skips(self, tmp_path):
        (tmp_path / "cc" / "blueprints").mkdir(parents=True)
        run_blueprint(["start"], cwd=tmp_path)
        run_blueprint(["record", "--kind", "decision", "--description", "dup"], cwd=tmp_path)
        r = run_blueprint(["record", "--kind", "decision", "--description", "dup"], cwd=tmp_path)
        assert r.returncode == 0
        assert "skipped" in r.stderr.lower()
        assert len([e for e in self._entries(tmp_path) if e["description"] == "dup"]) == 1
