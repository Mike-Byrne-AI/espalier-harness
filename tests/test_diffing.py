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
        """A NEW LANGUAGE after saving reports -> fingerprint_changed=True.

        Until 2026-10-04 this row planted a second Python file, which is
        census (a file count) and no longer flips: see
        ``TestDriftIsSignalNotCensus``. A language the tree did not have is
        the kind of change the fingerprint exists to see."""
        (harness_repo / "new_module.ts").write_text(
            "export const n = 1;\n", encoding="utf-8"
        )
        result = diff_repo(harness_repo)
        assert result["fingerprint_changed"] is True

    def test_changed_keys_list_is_populated(self, harness_repo):
        """When reports differ from fresh inference, changed_keys names the
        drifted attribute -- asserted unconditionally. The earlier form sat
        under ``if result["fingerprint_changed"]:`` and would have passed
        vacuously once the census keys stopped flipping."""
        (harness_repo / "extra.ts").write_text("export const x = 1;\n", encoding="utf-8")
        result = diff_repo(harness_repo)
        assert result["fingerprint_changed"] is True
        assert "languages" in result["fingerprint_changed_keys"]

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


class TestReductionsAreNamed:
    """The registry and the normalizers are pinned apart in BOTH directions:
    every top-level key a normalizer changes on a fully census-valued input is
    named in the registry, and every registry entry names a key the normalizer
    did change. Two hand-kept copies of the ignored-keys list drifted from the
    normalizers before (docs/SHARP_EDGES.md, the hand-maintained enumeration
    footgun); now the diff results print the registry itself."""

    def test_every_fingerprint_reduction_is_named_and_every_name_reduces(self):
        from dataclasses import fields

        from espalier.diffing import (
            FINGERPRINT_REDUCTIONS,
            FINGERPRINT_SIGNAL_FIELDS,
            _normalize_fingerprint,
        )
        from espalier.models import RepoFingerprint

        normalized = _normalize_fingerprint(_FINGERPRINT_CENSUS)
        # the input covers EVERY declared field, so a field added to the
        # dataclass reds here until it is given a census value below
        declared = {f.name for f in fields(RepoFingerprint)}
        assert set(_FINGERPRINT_CENSUS) - {"retired_field"} == declared, (
            sorted((set(_FINGERPRINT_CENSUS) - {"retired_field"}) ^ declared)
        )
        changed = {
            k for k in set(_FINGERPRINT_CENSUS) | set(normalized)
            if _FINGERPRINT_CENSUS.get(k) != normalized.get(k)
        }
        named = {e.split("(")[0].split(".")[0] for e in FINGERPRINT_REDUCTIONS if not e.startswith("<")}
        assert changed - {"retired_field"} == named, sorted(changed ^ named)
        assert "retired_field" not in normalized
        assert any(e.startswith("<undeclared keys>") for e in FINGERPRINT_REDUCTIONS)
        for sub in ("guardrails", "git", "docs"):
            assert f"conventions.{sub}" in {e.split("(")[0] for e in FINGERPRINT_REDUCTIONS}
            assert _FINGERPRINT_CENSUS["conventions"].get(sub) != normalized["conventions"].get(sub), sub
        assert normalized["conventions"]["layout"] == ["src/ layout is present."]
        # every signal field comes through untouched
        for name in FINGERPRINT_SIGNAL_FIELDS:
            assert normalized[name] == _FINGERPRINT_CENSUS[name], name
        # the reductions keep the signal each field carries
        assert normalized["repo_name"] == "<repo_name>"
        assert normalized["git_conventions"] == {"format": "conventional"}
        assert normalized["languages"] == {"primary": "typescript", "names": ["go", "typescript"]}
        assert normalized["language_counts"] == ["go", "typescript"]
        assert normalized["large_files"] == ["uv.lock"]
        assert normalized["docs_surface"] == ["README.md", "docs"]
        assert normalized["signals"] == ["languages"]
        assert normalized["architecture"] == {
            "pattern": "src_layout", "layer_rules": {"src/app": "no_io"},
        }
        assert "notes" not in normalized and "garbage_files" not in normalized

    def test_fifty_large_files_compare_as_presence(self):
        """`detect_large_files` keeps the fifty largest, so at the cut the path
        set churns as files trade places with none crossing the threshold."""
        from espalier.diffing import _normalize_fingerprint

        forty_nine = [{"path": f"big{i:02d}.bin", "size_bytes": 300_000} for i in range(49)]
        assert len(_normalize_fingerprint({"large_files": forty_nine})["large_files"]) == 49
        fifty = forty_nine + [{"path": "big49.bin", "size_bytes": 300_000}]
        at_cut = _normalize_fingerprint({"large_files": fifty})["large_files"]
        traded = forty_nine + [{"path": "other.bin", "size_bytes": 300_000}]
        assert at_cut == _normalize_fingerprint({"large_files": traded})["large_files"]
        assert len(at_cut) == 1 and at_cut[0].startswith("<")

    def test_every_plan_reduction_is_named_and_every_name_reduces(self):
        from dataclasses import fields

        from espalier.diffing import PLAN_REDUCTIONS, PLAN_SIGNAL_FIELDS, _normalize_plan
        from espalier.models import BuildPlan

        census = _PLAN_CENSUS
        normalized = _normalize_plan(census)
        declared = {f.name for f in fields(BuildPlan)}
        # `settings_profile` is the record init writes beside the plan, not a field
        covered = set(census) - {"proof_gates", "settings_profile"}
        assert covered == declared, sorted(covered ^ declared)
        changed = {k for k in set(census) | set(normalized) if census.get(k) != normalized.get(k)}
        named = {
            e.split("(")[0].split(".")[0].replace("[]", "")
            for e in PLAN_REDUCTIONS if not e.startswith("<")
        }
        assert changed - {"proof_gates"} == named, sorted(changed ^ named)
        assert "proof_gates" not in normalized
        assert any(e.startswith("<undeclared keys>") for e in PLAN_REDUCTIONS)
        agent = normalized["agents"][0]
        # each agents[] sub-key the registry names did change
        assert agent["generated_paths"] == ["out"]
        assert agent["primary_paths"] == ["docs", "docs/site", "src"], "a docs/ package root is not a page"
        assert normalized["repo_name"] == "<repo_name>"
        assert normalized["suggested_agents"] == ["component-reviewer"]
        assert "notes" not in normalized and "settings_profile" not in normalized
        for name in PLAN_SIGNAL_FIELDS:
            assert normalized[name] == census[name], name

    def test_the_generic_diff_prints_the_registry(self, python_repo):
        from espalier.diffing import FINGERPRINT_REDUCTIONS, PLAN_REDUCTIONS

        result = diff_repo(python_repo)
        expected = list(dict.fromkeys([*FINGERPRINT_REDUCTIONS, *PLAN_REDUCTIONS]))
        assert result["ignored_local_only_keys"] == expected


class TestRetiredSchemaKeysAreNotDrift:
    """A key an older release saved and the current schema no longer declares
    is not drift. ``BuildPlan`` lost ``proof_gates`` and ``profile_scores``,
    and every adopter on that release held a saved plan the next one read as
    changed: ``espalier diff`` exited 1 and doctor warned over keys nobody set.
    This lands beside the census reductions, not inside them: a different
    cause in the same two normalizers."""

    def test_a_retired_plan_key_is_not_a_changed_key(self):
        from espalier.diffing import _changed_keys, _normalize_plan

        fresh = _normalize_plan({"repo_name": "r", "agents": []})
        saved = _normalize_plan(
            {"repo_name": "r", "agents": [], "proof_gates": [], "profile_scores": {}}
        )
        assert _changed_keys(fresh, saved) == []

    def test_a_retired_fingerprint_key_is_not_a_changed_key(self):
        from espalier.diffing import _changed_keys, _normalize_fingerprint

        fresh = _normalize_fingerprint({"repo_name": "r", "languages": ["go"]})
        saved = _normalize_fingerprint(
            {"repo_name": "r", "languages": ["go"], "retired_field": 1}
        )
        assert _changed_keys(fresh, saved) == []

    def test_a_declared_key_still_compares(self):
        from espalier.diffing import _changed_keys, _normalize_fingerprint

        fresh = _normalize_fingerprint({"repo_name": "r", "ci_providers": ["github_actions"]})
        saved = _normalize_fingerprint({"repo_name": "r", "ci_providers": []})
        assert _changed_keys(fresh, saved) == ["ci_providers"]

    def test_retired_keys_nested_in_the_plan_are_not_drift(self):
        """`agents[]`, `hooks[]` and `config` are dataclasses too, and a field
        retired from any of them would otherwise read as drift one level down."""
        from espalier.diffing import _changed_keys, _normalize_plan

        fresh = _normalize_plan({
            "repo_name": "r",
            "agents": [{"name": "a", "scope": "review"}],
            "hooks": [{"event": "Stop", "script": "tools/cc/hooks/stop_gate.py"}],
            "config": {"preferred_profiles": []},
        })
        saved = _normalize_plan({
            "repo_name": "r",
            "agents": [{"name": "a", "scope": "review", "legacy_tier": 2}],
            "hooks": [{"event": "Stop", "script": "tools/cc/hooks/stop_gate.py", "retired": True}],
            "config": {"preferred_profiles": [], "old_knob": 1},
        })
        assert _changed_keys(fresh, saved) == []
        assert fresh == saved


class TestEveryFieldIsClassified:
    """A field added to either dataclass must be classified: either the
    reduction registry names it or the signal roster carries it. Without this
    pin a new census field (a `test_count`, say) would compare verbatim with
    every test green and the class would return; both reviews of the
    2026-10-04 lane named the gap."""

    def test_every_fingerprint_field_is_reduced_or_a_signal(self):
        from dataclasses import fields

        from espalier.diffing import FINGERPRINT_REDUCTIONS, FINGERPRINT_SIGNAL_FIELDS
        from espalier.models import RepoFingerprint

        declared = {f.name for f in fields(RepoFingerprint)}
        reduced = {e.split("(")[0].split(".")[0] for e in FINGERPRINT_REDUCTIONS if not e.startswith("<")}
        assert reduced <= declared, sorted(reduced - declared)
        assert FINGERPRINT_SIGNAL_FIELDS <= declared, sorted(FINGERPRINT_SIGNAL_FIELDS - declared)
        assert not (reduced & FINGERPRINT_SIGNAL_FIELDS), sorted(reduced & FINGERPRINT_SIGNAL_FIELDS)
        unclassified = declared - reduced - FINGERPRINT_SIGNAL_FIELDS
        assert not unclassified, (
            f"RepoFingerprint field(s) {sorted(unclassified)} are neither reduced nor "
            "declared a signal: add each to FINGERPRINT_REDUCTIONS (and reduce it in "
            "_normalize_fingerprint) or to FINGERPRINT_SIGNAL_FIELDS."
        )

    def test_every_plan_field_is_reduced_or_a_signal(self):
        from dataclasses import fields

        from espalier.diffing import PLAN_REDUCTIONS, PLAN_SIGNAL_FIELDS
        from espalier.models import BuildPlan

        declared = {f.name for f in fields(BuildPlan)}
        reduced = {
            e.split("(")[0].split(".")[0].replace("[]", "")
            for e in PLAN_REDUCTIONS if not e.startswith("<")
        } - {"settings_profile"}  # a record init writes beside the plan, not a field
        assert reduced <= declared, sorted(reduced - declared)
        assert PLAN_SIGNAL_FIELDS <= declared, sorted(PLAN_SIGNAL_FIELDS - declared)
        assert not (reduced & PLAN_SIGNAL_FIELDS), sorted(reduced & PLAN_SIGNAL_FIELDS)
        unclassified = declared - reduced - PLAN_SIGNAL_FIELDS
        assert not unclassified, (
            f"BuildPlan field(s) {sorted(unclassified)} are neither reduced nor declared "
            "a signal: add each to PLAN_REDUCTIONS (and reduce it in _normalize_plan) "
            "or to PLAN_SIGNAL_FIELDS."
        )

    def test_the_self_host_diff_prints_the_fingerprint_registry(self):
        """The self-host plan half is set-valued by name, so its ignored list is
        the fingerprint registry plus the recorded profile, and nothing else."""
        from espalier.diffing import FINGERPRINT_REDUCTIONS, _diff_self_host

        result = _diff_self_host(REPO_ROOT)
        assert result["ignored_local_only_keys"] == [*FINGERPRINT_REDUCTIONS, "settings_profile"]


#: Every RepoFingerprint field with a census-valued payload where the field
#: carries one, a plain value where it is a signal, plus one retired key.
_FINGERPRINT_CENSUS = {
    "repo_name": "clone-dir-name",
    "repo_root": "/somewhere/else",
    "language_counts": {"typescript": 4, "go": 2},
    "languages": ["typescript", "go"],
    "package_systems": ["npm"],
    "package_roots": ["src"],
    "package_manager": {"name": "npm", "source": "package-lock.json"},
    "ci_providers": ["github_actions"],
    "entrypoints": ["src/index.ts"],
    "test_commands": ["npm test"],
    "inferred_actions": {"test": ["npm test"]},
    "docs_surface": ["README.md", "docs", "docs/a.md"],
    "runtime_surface": ["src"],
    "api_surface": False,
    "ui_surface": True,
    "ml_surface": False,
    "ops_surface": False,
    "ops_directories": [],
    "monorepo": False,
    "generated_zones": ["dist", "src/gen"],
    "risky_mutable_zones": ["node_modules", "data"],
    "large_files": [{"path": "uv.lock", "size_bytes": 250_000, "loc": 1}],
    "garbage_files": [".DS_Store"],
    "conventions": {
        "guardrails": ["Treat generated zones as read-only by default: dist"],
        "git": ["Conventional commits (83% of last 30 commits): a, b, c"],
        "docs": ["Docs surface cues: README.md, docs, docs/a.md",
                 "README.md is part of the operator surface."],
        "layout": ["src/ layout is present."],
    },
    "git_conventions": {"format": "conventional", "evidence": ["fix: a"], "confidence": 0.83},
    "architecture": {
        "pattern": "src_layout", "layers": ["src/app", "src/components"],
        "layer_rules": {"src/app": "no_io"},
    },
    "profiles": ["docs_heavy"],
    "notes": ["Large files detected; extraction and seam planning should be available."],
    "signals": [{"name": "languages", "evidence": ["typescript"], "confidence": 0.9}],
    "confidence": {"languages": 0.9},
    # a key no current RepoFingerprint field declares (an older release's)
    "retired_field": 1,
}

#: Every BuildPlan field, the record key init writes beside it, and one retired key.
_PLAN_CENSUS = {
    "repo_name": "clone-dir-name",
    "profiles": ["docs_heavy"],
    "agents": [{
        "name": "a", "scope": "review",
        "generated_paths": ["dist", "out"],
        "primary_paths": ["docs", "docs/a.md", "docs/site", "src"],
    }],
    # reduced to the names: the rest is the same census the agents' carry
    "suggested_agents": [{"name": "component-reviewer", "primary_paths": ["docs/a.md"]}],
    "stable_actions": {"test": ["npm test"]},
    "generated_docs": [".claude/commands/status.md"],
    "read_only_zones": ["dist", "vendor"],
    "mutable_zones": ["build", "src"],
    "unresolved_questions": ["which runner?"],
    "notes": ["Large files detected; extraction and seam planning should be available."],
    "hooks": [{"event": "Stop", "script": "tools/cc/hooks/stop_gate.py"}],
    "config": {"preferred_profiles": []},
    "settings_profile": "workflow",
    # a key BuildPlan retired (saved by an older release)
    "proof_gates": [],
}
