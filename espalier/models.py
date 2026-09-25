"""Data models for fingerprints, build plans, agents, blueprints, and reflect passes."""
from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field, fields
from typing import Any


@dataclass(frozen=True, slots=True)
class LargeFile:
    path: str
    size_bytes: int
    loc: int = 0
    top_level_functions: int = 0
    top_level_classes: int = 0


@dataclass(frozen=True, slots=True)
class Signal:
    name: str
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.5


@dataclass(frozen=True, slots=True)
class RepoFingerprint:
    repo_name: str
    repo_root: str
    language_counts: dict[str, int] = field(default_factory=dict)
    languages: list[str] = field(default_factory=list)
    package_systems: list[str] = field(default_factory=list)
    package_roots: list[str] = field(default_factory=list)
    ci_providers: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)
    inferred_actions: dict[str, list[str]] = field(default_factory=dict)
    docs_surface: list[str] = field(default_factory=list)
    runtime_surface: list[str] = field(default_factory=list)
    api_surface: bool = False
    ui_surface: bool = False
    ml_surface: bool = False
    ops_surface: bool = False
    ops_directories: list[str] = field(default_factory=list)
    monorepo: bool = False
    generated_zones: list[str] = field(default_factory=list)
    risky_mutable_zones: list[str] = field(default_factory=list)
    large_files: list[LargeFile] = field(default_factory=list)
    garbage_files: list[str] = field(default_factory=list)
    conventions: dict[str, list[str]] = field(default_factory=dict)
    git_conventions: dict[str, Any] = field(default_factory=dict)
    architecture: dict[str, Any] = field(default_factory=dict)
    profiles: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    confidence: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["repo_root"] = "."
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoFingerprint:
        payload = dict(data)
        payload["large_files"] = [LargeFile(**item) for item in payload.get("large_files", [])]
        payload["signals"] = [Signal(**item) for item in payload.get("signals", [])]
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class HarnessConfig:
    preferred_profiles: list[str] = field(default_factory=list)
    suppress_profiles: list[str] = field(default_factory=list)
    extra_actions: dict[str, list[str]] = field(default_factory=dict)
    suppress_actions: list[str] = field(default_factory=list)
    include_paths: list[str] = field(default_factory=list)
    exclude_paths: list[str] = field(default_factory=list)
    protected_paths: list[str] = field(default_factory=list)
    generated_paths: list[str] = field(default_factory=list)
    lane_count: int = 3
    surface_mode: str = "core"
    # settings profile name. None means the harness default applies
    # (workflow). The CLI --profile flag overrides this; this field is the
    # per-project preference written into espalier.toml.
    default_profile: str | None = None
    # adopter-configurable plan_guard exempt prefixes. Empty default
    # preserves strict mode. Each entry must end with "/"; validation lives
    # in tools/cc/hooks/plan_guard.py::_load_adopter_exempt_prefixes (the
    # hook reads espalier.toml directly to honor the zero-espalier-imports
    # constraint on tools/cc/).
    plan_exempt_prefixes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: str
    description: str
    write_access: bool
    scope: str
    model: str = "sonnet"
    primary_paths: list[str] = field(default_factory=list)
    preferred_actions: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)
    protected_paths: list[str] = field(default_factory=list)
    generated_paths: list[str] = field(default_factory=list)
    not_responsible_for: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class HookSpec:
    """A hook to be wired into the repo's .claude/settings.json."""
    event: str              # SessionStart, UserPromptSubmit, PreToolUse, ConfigChange, PostToolUse, Stop, SubagentStop, PostCompact, SubagentStart, PostToolUseFailure
    script: str             # relative path, e.g. "tools/cc/hooks/commit_guard.py"
    timeout: int = 10
    matcher: str = ""       # e.g. "Write|Edit", "Bash", "compact"
    reason: str = ""        # human-readable description for CLAUDE.md table
    is_async: bool = False  # async hooks never block the agent


@dataclass(frozen=True, slots=True)
class BuildPlan:
    repo_name: str
    profiles: list[str] = field(default_factory=list)
    agents: list[AgentSpec] = field(default_factory=list)
    stable_actions: dict[str, list[str]] = field(default_factory=dict)
    generated_docs: list[str] = field(default_factory=list)
    read_only_zones: list[str] = field(default_factory=list)
    mutable_zones: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    hooks: list[HookSpec] = field(default_factory=list)
    config: HarnessConfig = field(default_factory=HarnessConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Cognitive System Models ───────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ReflectFinding:
    """A single finding from a structured reflect pass."""
    kind: str          # gap, orphan, cross_reference, quality_signal, terminology_drift
    severity: str      # high, medium, low
    description: str
    files: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ReflectPass:
    """One complete reflect pass with structured findings and metrics."""
    pass_number: int
    timestamp: str
    findings: list[ReflectFinding] = field(default_factory=list)
    files_analyzed: int = 0
    total_references: int = 0
    cross_ref_density: float = 0.0    # references / files_analyzed
    gap_count: int = 0
    orphan_count: int = 0
    placeholder_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReasoningEntry:
    """A captured reasoning artifact — decision, rejected alternative,
    discovered pattern, or reflect-derived insight."""
    kind: str          # decision, alternative_rejected, pattern_discovered, reflect_insight
    description: str
    evidence: list[str] = field(default_factory=list)
    session_id: str = ""
    timestamp: str = ""
    # carry_forward pins an entry so the reinjection selection prefers it over
    # pure recency (importance > recency, re-weighting away from "latest"); off
    # by default. Set at record time (--carry-forward) or via `pin <index>`.
    carry_forward: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ActionJustification:
    """Per-action rationale captured at tool-call grain.

    Recorded BEFORE a state-changing tool call (Write/Edit/Bash/etc.)
    via `cognitive_blueprint justify` or the execution-plan step
    `action_justification` field. Distinct from `ReasoningEntry`
    (session grain). Validated by `_validate_action_justification`
    in `espalier.cognitive_blueprint`.
    """
    goal: str
    step_rationale: str
    expected_outcome: str
    not_doing: str
    tool: str          # Write|Edit|NotebookEdit|Bash|PowerShell|mcp__*
    content_hash: str  # sha256:<64-hex>
    timestamp: str
    session_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CognitiveBlueprint:
    """Full reasoning-capture blueprint with session chain support.

    Extends the state-snapshot blueprint with:
    - Reasoning entries (decisions, alternatives, patterns, insights)
    - Reflect pass history with convergence tracking
    - Continuation fragments for next-session priming
    - Session chain metadata for accumulated context depth
    """
    # Session identity
    session_id: str
    repo_name: str
    timestamp: str
    schema_version: int = 1           # bumped when on-disk shape changes
    parent_session_id: str = ""
    accumulated_depth: int = 1        # how many sessions deep

    # Project state (carried from fingerprint/plan)
    languages: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)
    gate_status: str = "unknown"
    agents: list[dict[str, Any]] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)

    # Reasoning state
    reasoning_entries: list[ReasoningEntry] = field(default_factory=list)
    reflect_passes: list[ReflectPass] = field(default_factory=list)

    # Continuation fragments — top insights to seed the next session
    continuation_fragments: list[str] = field(default_factory=list)

    # Quality metrics across reflect passes
    gap_convergence: list[int] = field(default_factory=list)
    cross_ref_density_trend: list[float] = field(default_factory=list)

    # Action-grain rationale captured before state-changing tool calls
    action_justifications: list[ActionJustification] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CognitiveBlueprint:
        """Reconstruct from a serialised payload.

        Drop unknown keys with a stderr warn so an older reader can
        ingest a newer payload without raising TypeError (which
        `load_latest_blueprint` would swallow, silently resetting
        `accumulated_depth=1` on the next session). Missing
        `schema_version` on legacy payloads defaults to 1.
        """
        payload = dict(data)
        known = {f.name for f in fields(cls)}
        unknown = set(payload) - known
        if unknown:
            print(
                f"[WARN] CognitiveBlueprint.from_dict: dropping unknown keys: "
                f"{sorted(unknown)}",
                file=sys.stderr,
            )
            payload = {k: v for k, v in payload.items() if k in known}
        payload.setdefault("schema_version", 1)

        # Field-filter each nested reconstruction the way the top level
        # already strips unknown keys above. Without this, ONE extra key on any
        # nested entry raises TypeError, which load_latest_blueprint swallows to
        # None — silently voiding the whole accumulated session chain.
        def _only(dc_cls: type, d: dict[str, Any]) -> dict[str, Any]:
            names = {f.name for f in fields(dc_cls)}
            return {k: v for k, v in d.items() if k in names}

        payload["reasoning_entries"] = [
            ReasoningEntry(**_only(ReasoningEntry, e))
            for e in payload.get("reasoning_entries", [])
        ]
        # ReflectPass.findings is itself a list of nested ReflectFinding dicts —
        # a naive _only(ReflectPass, p) would keep `findings` as RAW DICTS and
        # corrupt the type. Filter the outer dict AND rebuild the findings list.
        payload["reflect_passes"] = [
            ReflectPass(**{
                **_only(ReflectPass, p),
                "findings": [
                    ReflectFinding(**_only(ReflectFinding, f))
                    for f in p.get("findings", [])
                ],
            })
            for p in payload.get("reflect_passes", [])
        ]
        payload["action_justifications"] = [
            ActionJustification(**_only(ActionJustification, e))
            for e in payload.get("action_justifications", [])
        ]
        return cls(**payload)
