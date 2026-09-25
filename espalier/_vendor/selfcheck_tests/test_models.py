"""Tests for the dataclasses in ``espalier.models`` — the schema
layer that ``reports/repo_fingerprint.json``,
``reports/harness_config.json``, and the blueprint chain all
serialize through.

Pins each dataclass's required-vs-optional field shape and default
values so a schema drift between the dataclass and its JSON
on-disk representation surfaces immediately. Without this contract,
adding a required field without a default would silently break
every prior session's saved reports (no migration, just a
load-time crash) — the failure mode is invisible until the next
``espalier`` invocation in a previously-initialized repo.
"""
from __future__ import annotations



from espalier.models import (
    AgentSpec,
    BuildPlan,
    HarnessConfig,
    CognitiveBlueprint,
    HookSpec,
    LargeFile,
    ReasoningEntry,
    ReflectFinding,
    ReflectPass,
    RepoFingerprint,
    Signal,
)


class TestLargeFile:
    def test_required_fields_set(self):
        lf = LargeFile(path="espalier/foo.py", size_bytes=10000)
        assert lf.path == "espalier/foo.py"
        assert lf.size_bytes == 10000

    def test_optional_fields_default_zero(self):
        lf = LargeFile(path="x.py", size_bytes=1)
        assert lf.loc == 0
        assert lf.top_level_functions == 0
        assert lf.top_level_classes == 0

    def test_all_fields_settable(self):
        lf = LargeFile(path="big.py", size_bytes=50000, loc=900, top_level_functions=12, top_level_classes=3)
        assert lf.loc == 900
        assert lf.top_level_functions == 12
        assert lf.top_level_classes == 3


class TestSignal:
    def test_required_name_field(self):
        s = Signal(name="api_surface")
        assert s.name == "api_surface"

    def test_evidence_defaults_to_empty_list(self):
        s = Signal(name="ml_surface")
        assert s.evidence == []

    def test_confidence_defaults_to_half(self):
        s = Signal(name="test")
        assert s.confidence == 0.5

    def test_evidence_list_is_not_shared_across_instances(self):
        a = Signal(name="a")
        b = Signal(name="b")
        a.evidence.append("x")
        assert b.evidence == []


class TestRepoFingerprint:
    def test_required_fields_only(self):
        fp = RepoFingerprint(repo_name="myrepo", repo_root="/tmp/myrepo")
        assert fp.repo_name == "myrepo"
        assert fp.repo_root == "/tmp/myrepo"

    def test_all_list_fields_default_empty(self):
        fp = RepoFingerprint(repo_name="r", repo_root=".")
        assert fp.languages == []
        assert fp.package_systems == []
        assert fp.entrypoints == []
        assert fp.test_commands == []
        assert fp.signals == []

    def test_bool_surfaces_default_false(self):
        fp = RepoFingerprint(repo_name="r", repo_root=".")
        assert fp.api_surface is False
        assert fp.ui_surface is False
        assert fp.ml_surface is False
        assert fp.ops_surface is False
        assert fp.monorepo is False

    def test_to_dict_normalizes_repo_root(self):
        fp = RepoFingerprint(repo_name="r", repo_root="/absolute/path")
        d = fp.to_dict()
        assert d["repo_root"] == "."

    def test_to_dict_contains_all_scalar_fields(self):
        fp = RepoFingerprint(repo_name="myrepo", repo_root="/x", api_surface=True)
        d = fp.to_dict()
        assert d["repo_name"] == "myrepo"
        assert d["api_surface"] is True

    def test_from_dict_round_trip(self):
        fp = RepoFingerprint(
            repo_name="r",
            repo_root=".",
            languages=["python"],
            large_files=[LargeFile(path="x.py", size_bytes=1000, loc=100)],
            signals=[Signal(name="api_surface", evidence=["fastapi"], confidence=0.9)],
        )
        d = fp.to_dict()
        restored = RepoFingerprint.from_dict(d)
        assert restored.repo_name == "r"
        assert restored.languages == ["python"]
        assert len(restored.large_files) == 1
        assert isinstance(restored.large_files[0], LargeFile)
        assert restored.large_files[0].path == "x.py"
        assert len(restored.signals) == 1
        assert isinstance(restored.signals[0], Signal)
        assert restored.signals[0].name == "api_surface"

    def test_from_dict_missing_large_files_ok(self):
        d = {"repo_name": "r", "repo_root": ".", "large_files": [], "signals": []}
        fp = RepoFingerprint.from_dict(d)
        assert fp.large_files == []
        assert fp.signals == []

    def test_lists_are_independent_across_instances(self):
        a = RepoFingerprint(repo_name="a", repo_root=".")
        b = RepoFingerprint(repo_name="b", repo_root=".")
        a.languages.append("python")
        assert b.languages == []


class TestHarnessConfig:
    def test_defaults(self):
        cfg = HarnessConfig()
        assert cfg.lane_count == 3
        assert cfg.surface_mode == "core"

    def test_to_dict_returns_dict(self):
        cfg = HarnessConfig(surface_mode="extended")
        d = cfg.to_dict()
        assert isinstance(d, dict)
        assert d["surface_mode"] == "extended"

    def test_to_dict_includes_all_list_fields(self):
        cfg = HarnessConfig(preferred_profiles=["python_api"], suppress_actions=["scan"])
        d = cfg.to_dict()
        assert d["preferred_profiles"] == ["python_api"]
        assert d["suppress_actions"] == ["scan"]


class TestAgentSpec:
    def test_required_fields(self):
        agent = AgentSpec(name="code-reviewer", description="Reviews code", write_access=False, scope="review")
        assert agent.name == "code-reviewer"
        assert agent.write_access is False
        assert agent.scope == "review"

    def test_model_defaults_to_sonnet(self):
        agent = AgentSpec(name="x", description="d", write_access=True, scope="review")
        assert agent.model == "sonnet"

    def test_optional_list_fields_default_empty(self):
        agent = AgentSpec(name="x", description="d", write_access=False, scope="review")
        assert agent.primary_paths == []
        assert agent.preferred_actions == []
        assert agent.test_commands == []
        assert agent.notes == []


class TestHookSpec:
    def test_required_fields(self):
        hs = HookSpec(event="PreToolUse", script="tools/cc/hooks/write_guard.py")
        assert hs.event == "PreToolUse"
        assert hs.script == "tools/cc/hooks/write_guard.py"

    def test_defaults(self):
        hs = HookSpec(event="Stop", script="tools/cc/hooks/stop_gate.py")
        assert hs.timeout == 10
        assert hs.matcher == ""
        assert hs.reason == ""
        assert hs.is_async is False


class TestBuildPlan:
    def test_required_field_only(self):
        plan = BuildPlan(repo_name="myrepo")
        assert plan.repo_name == "myrepo"
        assert plan.profiles == []
        assert plan.agents == []

    def test_config_defaults_to_builder_config(self):
        plan = BuildPlan(repo_name="r")
        assert isinstance(plan.config, HarnessConfig)

    def test_to_dict_is_serializable(self):
        import json
        plan = BuildPlan(repo_name="r", profiles=["python_api"])
        d = plan.to_dict()
        serialized = json.dumps(d)
        assert "python_api" in serialized

    def test_to_dict_includes_nested_config(self):
        cfg = HarnessConfig(lane_count=5)
        plan = BuildPlan(repo_name="r", config=cfg)
        d = plan.to_dict()
        assert d["config"]["lane_count"] == 5


class TestReflectFinding:
    def test_required_fields(self):
        rf = ReflectFinding(kind="gap", severity="high", description="Missing test coverage")
        assert rf.kind == "gap"
        assert rf.severity == "high"
        assert rf.files == []


class TestReflectPass:
    def test_required_fields(self):
        rp = ReflectPass(pass_number=1, timestamp="2026-04-18T12:00:00")
        assert rp.pass_number == 1
        assert rp.timestamp == "2026-04-18T12:00:00"
        assert rp.findings == []
        assert rp.files_analyzed == 0

    def test_to_dict_round_trip(self):
        rp = ReflectPass(pass_number=2, timestamp="2026-04-18T12:00:00", gap_count=3)
        d = rp.to_dict()
        assert d["pass_number"] == 2
        assert d["gap_count"] == 3


class TestReasoningEntry:
    def test_required_fields(self):
        re = ReasoningEntry(kind="decision", description="Use dataclasses for models")
        assert re.kind == "decision"
        assert re.description == "Use dataclasses for models"
        assert re.evidence == []
        assert re.session_id == ""

    def test_to_dict_round_trip(self):
        re = ReasoningEntry(kind="pattern_discovered", description="hooks use exit code 2 to block")
        d = re.to_dict()
        assert d["kind"] == "pattern_discovered"
        assert d["description"] == "hooks use exit code 2 to block"


class TestCognitiveBlueprint:
    def test_required_fields(self):
        cb = CognitiveBlueprint(session_id="abc123", repo_name="myrepo", timestamp="2026-04-18T12:00:00")
        assert cb.session_id == "abc123"
        assert cb.repo_name == "myrepo"
        assert cb.accumulated_depth == 1
        assert cb.parent_session_id == ""

    def test_optional_list_fields_default_empty(self):
        cb = CognitiveBlueprint(session_id="x", repo_name="r", timestamp="t")
        assert cb.languages == []
        assert cb.reasoning_entries == []
        assert cb.reflect_passes == []
        assert cb.continuation_fragments == []

    def test_to_dict_is_serializable(self):
        import json
        cb = CognitiveBlueprint(session_id="s1", repo_name="r", timestamp="2026-04-18T12:00:00")
        d = cb.to_dict()
        serialized = json.dumps(d)
        assert "s1" in serialized

    def test_from_dict_round_trip_with_nested_types(self):
        cb = CognitiveBlueprint(
            session_id="s1",
            repo_name="r",
            timestamp="2026-04-18T12:00:00",
            reasoning_entries=[
                ReasoningEntry(kind="decision", description="Use pytest")
            ],
            reflect_passes=[
                ReflectPass(
                    pass_number=1,
                    timestamp="2026-04-18T12:00:00",
                    findings=[ReflectFinding(kind="gap", severity="low", description="missing tests")],
                    gap_count=1,
                )
            ],
        )
        d = cb.to_dict()
        restored = CognitiveBlueprint.from_dict(d)
        assert restored.session_id == "s1"
        assert len(restored.reasoning_entries) == 1
        assert isinstance(restored.reasoning_entries[0], ReasoningEntry)
        assert restored.reasoning_entries[0].kind == "decision"
        assert len(restored.reflect_passes) == 1
        assert isinstance(restored.reflect_passes[0], ReflectPass)
        assert len(restored.reflect_passes[0].findings) == 1
        assert isinstance(restored.reflect_passes[0].findings[0], ReflectFinding)

    def test_from_dict_empty_nested_lists(self):
        d = {
            "session_id": "x",
            "repo_name": "r",
            "timestamp": "t",
            "parent_session_id": "",
            "accumulated_depth": 1,
            "languages": [],
            "profiles": [],
            "gate_status": "unknown",
            "agents": [],
            "commands": [],
            "reasoning_entries": [],
            "reflect_passes": [],
            "continuation_fragments": [],
            "gap_convergence": [],
            "cross_ref_density_trend": [],
        }
        cb = CognitiveBlueprint.from_dict(d)
        assert cb.reasoning_entries == []
        assert cb.reflect_passes == []
