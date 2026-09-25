"""Harness configuration — agent selection, proof hints, and build plan construction."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from espalier import hook_contract, surface_contract
from espalier.analyze import _BASE_ACTIONS
from espalier.models import (
    AgentSpec, HarnessConfig, BuildPlan, HookSpec, RepoFingerprint,
)
from espalier.profiles import classify_repo


# ── Canonical hook wiring ────────────────────────────────────────────
# One source of truth for which event each canonical hook is wired to.
# Names are validated against surface_contract.get_canonical_hook_scripts().
CANONICAL_HOOK_WIRING: dict[str, dict] = {
    "session_start.py": {
        "event": "SessionStart", "matcher": "", "timeout": 15,
        "reason": "Loads blueprint chain at session start",
    },
    "task_router.py": {
        "event": "UserPromptSubmit", "matcher": "", "timeout": 5,
        "reason": "Classifies prompt scope and routes toward /implement-task or /implement-task --multi",
    },
    "plan_guard.py": {
        "event": "PreToolUse",
        "matcher": "Write|Edit|NotebookEdit",
        "timeout": 5,
        "reason": (
            "Blocks Write/Edit/NotebookEdit on source files without an "
            "active execution plan. Bash and MCP writes are not plan-gated "
            "— write_guard covers protected-zone defense for those."
        ),
    },
    "write_guard.py": {
        "event": "PreToolUse", "matcher": "*", "timeout": 5,
        "reason": "Blocks writes to protected harness zones and dangerous bash patterns",
    },
    "config_guard.py": {
        "event": "ConfigChange", "matcher": "", "timeout": 5,
        "reason": "Blocks unsafe project/local/user settings changes; audits managed policy_settings",
    },
    "post_write_check.py": {
        "event": "PostToolUse",
        "matcher": "Write|Edit|NotebookEdit|Bash|PowerShell|mcp__.*",
        "timeout": 10,
        "reason": "Validates each written file for JSON validity and path consistency",
    },
    "reflect_trigger.py": {
        "event": "PostToolUse", "matcher": "*", "timeout": 45,
        "reason": "Runs reflect protocol every 10th source write",
    },
    "stop_gate.py": {
        "event": "Stop", "matcher": "", "timeout": hook_contract.STOP_OUTER_TIMEOUT,
        "reason": "Lightweight Stop checks by default; full core pytest gate opt-in via ESPALIER_STOP_GATE=full",
    },
    "subagent_stop.py": {
        "event": "SubagentStop", "matcher": "", "timeout": 10,
        "reason": "Appends subagent reasoning to the active blueprint (Gate 4 only); never blocks the subagent",
    },
    "post_compact.py": {
        "event": "PostCompact", "matcher": "", "timeout": 10,
        "reason": "Records compaction summary and prepares next-session continuity",
    },
    # Recall-engine substrate. Two non-blocking reporters.
    "subagent_start.py": {
        "event": "SubagentStart", "matcher": "", "timeout": 10,
        "reason": "Cold-subagent orientation (host facts + fan-out finding-schema pointer)",
    },
    "context_reinject_failure.py": {
        "event": "PostToolUseFailure", "matcher": "Write|Edit|NotebookEdit", "timeout": 5,
        "reason": "On a failed Edit/Write (old_string-not-found), injects untrusted-oracle re-derivation (Rule A)",
    },
}


# Derived from CANONICAL_HOOK_WIRING so the SoT is the dict.
# Adding a new hook with a new event auto-extends the set; no separate
# constant to forget to update.
HOOK_EVENTS: frozenset[str] = frozenset(
    spec["event"] for spec in CANONICAL_HOOK_WIRING.values()
)


# The subset of canonical hooks whose deletion from
# .claude/settings.json silently removes a DENY/blocking gate while the hook
# *file* stays on disk — the "deleted event key" fail-open. Maps each blocking
# script to the event it MUST be wired under. These are exactly the
# "Can block? Yes" hooks in the CLAUDE.md hooks table:
#   write_guard + plan_guard  → PreToolUse  (protected-zone / plan-gate deny)
#   config_guard              → ConfigChange (unsafe-settings deny)
#   stop_gate                 → Stop         (blocking Stop gate)
# SoT for the completeness oracle in espalier.doctor; tools/cc/ci_guard.py
# mirrors this literal inline (zero-imports rule). Both legs are pinned:
# each (script -> event) here must equal CANONICAL_HOOK_WIRING's event for that
# script, and ci_guard's mirror must equal this dict — see
# tests/test_hook_event_contracts.py + tests/test_ci_guard.py.
GOVERNANCE_BLOCKING_HOOKS: dict[str, str] = {
    "write_guard.py": "PreToolUse",
    "plan_guard.py": "PreToolUse",
    "config_guard.py": "ConfigChange",
    "stop_gate.py": "Stop",
}

#: The rest of the canonical roster: hooks that inject, record or advise and
#: never block. DERIVED, not typed -- the two tiers partition
#: CANONICAL_HOOK_WIRING (pinned in tests/test_hook_event_contracts.py), so a
#: new hook lands in a tier the moment it is declared. A dead reporter fails
#: nothing visibly -- subagents start cold, a failed edit gets no re-derivation
#: nudge, compaction loses its re-injection -- which is exactly why the wiring
#: oracle has to see them (DEF-619): with the two recall-engine hooks deleted
#: or neutered, every surface still said "armed". ``doctor`` reports these as
#: WARNINGS, never failures, so the blocking-gate failure count stays
#: parity-locked with tools/cc/ci_guard.py, which knows only the gates.
GOVERNANCE_REPORTER_HOOKS: dict[str, str] = {
    script: spec["event"]
    for script, spec in CANONICAL_HOOK_WIRING.items()
    if script not in GOVERNANCE_BLOCKING_HOOKS
}


# Canonical token ORDER (tuple, not frozenset) preserved so
# matcher_token_string output is deterministic and byte-equal to the
# live CHW matcher strings — which are NOT alphabetical. Dual-witness
# with tools/cc/hooks/_hook_utils.py::MUTATION_TOOLS (an unordered
# frozenset declared independently per the zero-imports rule); set
# equality `frozenset(MUTATION_TOOLS_TOKENS) == MUTATION_TOOLS` is
# contract-pinned in tests/test_hook_matcher_precision.py::
# test_mutation_tools_dual_witness. The tuple form here is the ORDER
# source for the matcher string; the frozenset form there is the
# MEMBERSHIP source for matcher precision checks.
MUTATION_TOOLS_TOKENS: tuple[str, ...] = (
    "Write", "Edit", "NotebookEdit", "Bash", "PowerShell",
)


def matcher_token_string(
    tokens: tuple[str, ...] | None = None,
    extras: tuple[str, ...] = (),
) -> str:
    """Render mutation-tool tokens as a `|`-separated matcher string.

    Tokens are joined in the order given — no sort. The ``extras``
    parameter appends additional matcher fragments AFTER the token
    set (e.g., ``mcp__.*`` wildcard); extras are preserved in the
    order given. Order-preservation matches the live CHW matcher
    strings which are NOT alphabetical.

    Has no production caller: ``espalier.cli._build_settings_json``
    derives every matcher from ``CANONICAL_HOOK_WIRING`` via
    ``_matcher_for``. This is the order-preserving derivation oracle
    that ``tests/test_hook_matcher_precision.py`` pins the live CHW
    matcher literals against.

    Example:
        >>> matcher_token_string()
        'Write|Edit|NotebookEdit|Bash|PowerShell'
        >>> matcher_token_string(extras=("mcp__.*",))
        'Write|Edit|NotebookEdit|Bash|PowerShell|mcp__.*'
    """
    if tokens is None:
        tokens = MUTATION_TOOLS_TOKENS
    return "|".join([*tokens, *extras])

# Docs that `init` materializes on every target repo. Kept aligned with
# espalier.render_surface.write_required_surface + surface_contract.get_required_init_files
# so that audit (proofs.run_cc_surface_gate) doesn't report missing artifacts
# immediately after a fresh init.
CORE_GENERATED_DOCS = [
    "cc/LIVE_SURFACE.md",
    "cc/COMMANDS.md",
    "cc/PACK_MANIFEST.txt",
]

# Conditional docs that a future harness version would create.
# Commented out because no current code path creates these files.
# They feed into generated_docs → harness_config.json → proofs.py,
# so listing them here = audit failures for files that don't exist.
# Uncomment when the code that creates them is implemented.

EXTENDED_GENERATED_DOCS = [
    # "cc/CODEMAP.md",
    # "cc/PROOF_HINTS.md",
]

# ── Agent catalog ────────────────────────────────────────────────────

DEFAULT_AGENT_ORDER = [
    ("code-reviewer", "Reviews code for bugs, style issues, and project-specific pitfalls", False, "review", "sonnet"),
    ("test-writer", "Generates tests matching the project's test patterns and conventions", True, "validation", "sonnet"),
    ("architecture-analyst", "Understands module connections, reviews changes for architectural consistency", False, "architecture", "opus"),
]

OPTIONAL_AGENTS = [
    ("api-reviewer", lambda fp: fp.api_surface, "Reviews API endpoints for consistency and error handling", False, "api", "sonnet"),
    ("experiment-analyst", lambda fp: fp.ml_surface, "Interprets ML experiment results against success criteria", False, "ml", "opus"),
    ("data-engineer", lambda fp: fp.ml_surface, "Designs and audits training data pipelines and datasets", True, "ml", "sonnet"),
    ("component-reviewer", lambda fp: fp.ui_surface, "Reviews UI components for accessibility and state management", False, "ui", "sonnet"),
    ("content-reviewer", lambda fp: fp.ops_surface, "Reviews drafts and outputs against brand voice, strategy docs, and content guidelines", False, "ops_content", "sonnet"),
    ("strategy-analyst", lambda fp: fp.ops_surface, "Evaluates whether outputs advance strategic goals and identifies pattern shifts in performance data", False, "ops_strategy", "opus"),
    ("engagement-analyst", lambda fp: fp.ops_surface, "Analyzes audience signals and feedback data to surface actionable adjustments", False, "ops_analytics", "sonnet"),
]


# ── Agent selection ──────────────────────────────────────────────────

def _scope_paths(scope: str, fp: RepoFingerprint) -> list[str]:
    pkg = [r for r in fp.package_roots if r not in {"/", "."}]
    by_scope = {
        "review": fp.docs_surface[:4] + fp.runtime_surface[:4] + pkg,
        "validation": (["tests"] if fp.test_commands else []) + fp.entrypoints[:4] + fp.runtime_surface[:4],
        "architecture": pkg + fp.docs_surface[:4] + fp.runtime_surface[:4],
        "api": fp.entrypoints[:4] + fp.runtime_surface[:4] + pkg,
        "ml": fp.runtime_surface[:4] + pkg + ["models", "notebooks"],
        "ui": fp.runtime_surface[:4] + fp.entrypoints[:4] + fp.docs_surface[:4],
        "ops_content": fp.ops_directories[:4] + fp.docs_surface[:4],
        "ops_strategy": fp.ops_directories[:4] + fp.docs_surface[:4] + fp.runtime_surface[:4],
        "ops_analytics": fp.ops_directories[:4] + fp.runtime_surface[:4] + pkg,
    }
    items = by_scope.get(scope, fp.runtime_surface[:4] + pkg)
    seen: set[str] = set()
    result: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            result.append(x)
    return result


def choose_agents(fp: RepoFingerprint) -> list[AgentSpec]:
    agents: list[AgentSpec] = []
    for name, desc, write, scope, model in DEFAULT_AGENT_ORDER:
        if scope == "validation" and not fp.test_commands:
            continue
        agents.append(AgentSpec(
            name=name, description=desc, write_access=write, scope=scope,
            model=model, primary_paths=_scope_paths(scope, fp),
            test_commands=fp.test_commands[:2],
        ))
    for name, pred, desc, write, scope, model in OPTIONAL_AGENTS:
        if pred(fp):
            agents.append(AgentSpec(
                name=name, description=desc, write_access=write, scope=scope,
                model=model, primary_paths=_scope_paths(scope, fp),
                test_commands=fp.test_commands[:2],
            ))
    return agents


# ── Build harness config ────────────────────────────────────────────

def _detect_actions(fp: RepoFingerprint) -> dict[str, list[str]]:
    actions: dict[str, list[str]] = {k: list(v) for k, v in _BASE_ACTIONS.items()}
    if fp.test_commands:
        actions["test"] = [fp.test_commands[0]]
    if "python" in fp.languages:
        actions["scan"] = ["espalier scan ."]
    return actions


def _detect_formatter_section(pyproject_path: Path) -> str | None:
    """Return ``"ruff"`` | ``"black"`` | ``None`` via structural TOML parse.

    Replaces an earlier substring scan. ``.lower()`` substring matching
    false-fired on commented-out sections (``# [tool.ruff.format]``),
    docstring-embedded TOML, and any prose mention of the header text
    inside the file. Structural ``tomllib`` parsing collapses those to
    "the section structurally exists / does not exist."

    Returns ``None`` on read error, parse error, or absence of the
    relevant ``[tool.<name>]`` block — caller falls through to "no
    formatter hook needed," matching the prior fail-safe behavior.
    """
    try:
        from espalier._compat import tomllib
    except ImportError:
        return None
    if tomllib is None:
        return None
    try:
        data = tomllib.loads(pyproject_path.read_bytes().decode("utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None
    tool = data.get("tool", {})
    if isinstance(tool, dict):
        ruff = tool.get("ruff")
        if isinstance(ruff, dict) and isinstance(ruff.get("format"), dict):
            return "ruff"
        black = tool.get("black")
        if isinstance(black, dict):
            return "black"
    return None


def _build_hooks(fp: RepoFingerprint, repo_root: Path | None = None) -> list[HookSpec]:
    """Build the hook inventory for the repo.

    Emits only the canonical hooks from `surface_contract.get_canonical_hook_scripts()`
    — every `script` field refers to a real file that will be deployed by `init`.
    Formatter hooks (ruff/black) are added when detected in the toolchain; those
    are shell commands, not script paths, so the existing-file guarantee doesn't
    apply to them.
    """
    hooks: list[HookSpec] = []

    # -- Formatter hooks (shell commands, not script paths) --
    # The user opts in to format-on-write by configuring ruff format or
    # black explicitly. A `[tool.ruff]` block alone is not opt-in — it's
    # commonly present for lint config only. The heuristic keys on the
    # format-section presence via structural TOML parse, so commented
    # headers and docstring-embedded TOML do not false-fire.
    root = repo_root or Path(fp.repo_root)
    pyproject = root / "pyproject.toml"
    formatter = _detect_formatter_section(pyproject) if pyproject.exists() else None
    if formatter == "ruff":
        hooks.append(HookSpec(
            event="PostToolUse", script="ruff format --quiet",
            reason="Auto-format with ruff after writes",
        ))
    elif formatter == "black":
        hooks.append(HookSpec(
            event="PostToolUse", script="black --quiet",
            reason="Auto-format with black after writes",
        ))

    # -- Canonical hooks (one source of truth: surface_contract) --
    for name in surface_contract.get_canonical_hook_scripts():
        wiring = CANONICAL_HOOK_WIRING.get(name)
        if wiring is None:
            continue
        hooks.append(HookSpec(
            event=wiring["event"],
            script=f"tools/cc/hooks/{name}",
            matcher=wiring["matcher"],
            timeout=wiring["timeout"],
            reason=wiring["reason"],
        ))

    return hooks


def build_harness_config(fp: RepoFingerprint, config: HarnessConfig | None = None) -> BuildPlan:
    config = config or HarnessConfig()
    profiles, _ = classify_repo(fp, config)
    agents = choose_agents(fp)
    actions = _detect_actions(fp)
    # Merge extra/suppress from config
    for name, cmds in config.extra_actions.items():
        actions[name] = list(cmds)
    for name in config.suppress_actions:
        actions.pop(name, None)

    unresolved: list[str] = []
    if not fp.test_commands:
        unresolved.append("No test command detected automatically.")
    if not fp.entrypoints:
        unresolved.append("No obvious runtime entrypoint detected.")

    # Build generated_docs — conditional docs only when they'll actually be written
    gen_docs = list(CORE_GENERATED_DOCS)
    if config.surface_mode == "extended":
        gen_docs.extend(EXTENDED_GENERATED_DOCS)

    return BuildPlan(
        repo_name=fp.repo_name,
        profiles=profiles,
        agents=agents,
        stable_actions=actions,
        generated_docs=gen_docs,
        read_only_zones=sorted(set(fp.generated_zones + config.generated_paths)),
        mutable_zones=sorted(set(fp.risky_mutable_zones + config.protected_paths)),
        unresolved_questions=unresolved,
        notes=fp.notes,
        config=config,
        hooks=_build_hooks(fp),
    )


def unwired_governance_gates(repo_root: Path) -> list[str]:
    """Blocking gates DEPLOYED on disk that are not *executably* wired.

    Returns their script basenames, sorted, so callers that need per-gate prose
    (doctor) and callers that need a path set (cli's enforcement-claim check)
    read the same population instead of each deriving it. Hoisted here rather
    than left inline in ``doctor`` because a second engine-side caller appeared:
    two copies of this loop in ``espalier/*.py`` would be a fresh
    ``sister_site_probe`` clique needing an opt-out marker, and the opt-out
    budget is a declared, shrinking resource (``tests/_surface_expected.py``
    says "chip down, don't grow"). One home, two callers, no marker.

    "Executably wired" is ``discover_executable_hook_wirings``' definition: an
    entry that runs the script through a python interpreter (not
    ``true``/``:``/``echo``/a ``#``-commented or wrong-``type`` entry that
    leaves the path as bait), points at the canonical
    ``tools/cc/hooks/<script>`` path rather than a stale copy sharing the
    basename, and -- for PreToolUse -- carries a matcher that actually fires on
    Write/Edit/NotebookEdit.

    ⚠ Gates whose file is ABSENT are skipped by design: keying on file-on-disk
    models the real disarm mechanism (the scripts stay put, the wiring rots)
    and avoids flagging a repo that never installed the harness. That skip is
    exactly why this predicate is NOT a superset of the path-existence check
    ``cli._missing_wired_hook_scripts`` performs -- on a tree with no
    ``tools/cc/`` at all this returns ``[]`` while that one returns every wired
    path. The two are COMPLEMENTARY; a caller asserting enforcement needs BOTH,
    and substituting either for the other silently reopens the half it is blind
    to (measured 2026-08-27; see
    ``tests/test_merge_settings.py::TestEnforcementClaimBlockersComposeThreeOracles``).

    Empty when ``.claude/settings.json`` is absent -- the presence check owns
    "settings missing". A DANGLING symlink is present-but-unreadable, not
    absent, so it falls through and flags the deployed gates (fail-closed).
    """
    return _unwired_hooks(repo_root, GOVERNANCE_BLOCKING_HOOKS)


def unwired_reporter_hooks(repo_root: Path) -> list[str]:
    """Reporter-tier hooks on disk that are not executably wired (DEF-619).

    The same predicate as :func:`unwired_governance_gates` over
    :data:`GOVERNANCE_REPORTER_HOOKS`. Kept as a separate function rather than
    a flag because the two populations mean different things to every caller:
    a dead gate is a failure and an enforcement-claim blocker; a dead reporter
    is a warning and a banner line. ``tools/cc/ci_guard.py`` has no twin of
    this on purpose -- CI gates merges on the deny path only.
    """
    return _unwired_hooks(repo_root, GOVERNANCE_REPORTER_HOOKS)


def _unwired_hooks(repo_root: Path, tier: dict[str, str]) -> list[str]:
    """The scripts in ``tier`` (``script -> canonical event``) that are on disk
    under ``tools/cc/hooks/`` but not executably wired under that event.

    A matcher is checked wherever the canonical wiring declares one (every
    PreToolUse gate, and the PostToolUse / PostToolUseFailure reporters); an
    event whose canonical matcher is empty has nothing to cover. For the
    blocking tier this is the same test the ``event != "PreToolUse"`` spelling
    made, since only its PreToolUse gates carry a matcher.
    """
    settings_path = repo_root / ".claude" / "settings.json"
    # `lexists` is `exists() or is_symlink()` with one difference: it answers
    # a `.claude` that denies traversal the same on every interpreter
    # (DEF-763), where pathlib raised on 3.10-3.13.
    if not os.path.lexists(settings_path):
        return []
    wirings = surface_contract.discover_executable_hook_wirings(repo_root)
    hooks_dir = repo_root / "tools" / "cc" / "hooks"
    unwired: list[str] = []
    for script, event in sorted(tier.items()):
        if not (hooks_dir / script).is_file():
            continue  # not deployed -> out of scope for the wiring oracle
        canonical = f"tools/cc/hooks/{script}"
        canonical_matcher = (
            CANONICAL_HOOK_WIRING.get(script, {}).get("matcher", "")
        )
        live = any(
            w["script"] == canonical
            and w["event"] == event
            and (not canonical_matcher
                 or surface_contract.matcher_covers_canonical(
                     w["matcher"], canonical_matcher))
            for w in wirings
        )
        if not live:
            unwired.append(script)
    return unwired


#: How a governance gate came to be unwired. The remedy differs per shape and
#: the plain ``merge-settings`` repairs only ``GATE_ABSENT``; ``merge-settings
#: --repair`` (the opt-in) rewrites the rest, voided excepted -- see
#: :func:`classify_unwired_gate`. The count is deliberately not written here:
#: it drifted twice ("two of the three" survived the fourth and fifth shapes),
#: which is the narration-count defect this module keeps fixing elsewhere.
GATE_ABSENT = "absent"
GATE_ORPHANED = "orphaned"
GATE_INERT = "inert"
GATE_LEGACY_FORM = "legacy_form"
#: An exec-form entry this oracle CAN read names the script with an
#: interpreter -- but under the wrong event, or with a matcher that excludes
#: tools the hook must see. Readable, so verifiably dead: the enforcement
#: claim must NOT forgive it the way it forgives ``GATE_LEGACY_FORM``. Split
#: out of that shape on 2026-09-07 (DEF-619's review): a plan_guard narrowed
#: to ``Write`` classified legacy_form, the claim abstained, and ``init``
#: printed "Hooks now intercept" over a gate that never fires on Edit.
GATE_MISWIRED = "miswired"
#: Not a property of THIS gate at all: some hook entry somewhere in
#: settings.json has a ``type`` other than ``"command"``, so Claude Code loads
#: no hooks from the file and every deployed gate is dead at once. Highest
#: precedence, because it is a whole-FILE fact that overrides whatever this
#: gate's own entry happens to look like -- and the offending entry is often
#: one the adopter wrote, not one espalier manages. See
#: :func:`surface_contract.hooks_config_voided_by` for the driven evidence.
GATE_VOIDED_SETTINGS = "voided_settings"

#: The complete roster, so the narrators do not each keep a hand-maintained
#: copy. There were THREE such copies for about an hour (``cli``'s ``known``,
#: ``doctor``'s ``known``, and these constants); a review pass pointed out that
#: adding a fifth shape and updating only one of them would give a gate BOTH its
#: proper clause AND the "shape this banner cannot name" fallback, with nothing
#: red. ``tests/test_hook_event_contracts.py::TestGateShapeRoster`` pins this set
#: against the live ``GATE_*`` constants, so a new shape reds at the moment it is
#: BORN rather than when someone happens to build a tree carrying one.
#:
#: A NEW narrator of an unwired gate -- another banner, remedy line or check
#: -- routes through one of the two that exist: ``cli._unwired_gate_diagnosis``
#: (the shape-by-shape clauses every armed claim prints) or the doctor arm in
#: ``doctor.run_doctor_check`` (the same tree in doctor's own words, legacy_form
#: included); a new SHAPE is also filed on one side of the ``--repair`` dispatch
#: (``cli._REPAIR_HANDLED_SHAPES`` / ``cli._REPAIR_SKIPPED_SHAPES``), which is
#: why ``TestGateShapeRoster`` counts five edits, not one. Reporters likewise:
#: ``cli._dead_reporters_line`` (one home, four callers) or
#: ``doctor._check_reporter_hook_wiring``. Another NARRATOR reading
#: ``group_unwired_gates_by_shape`` directly is the three-copies drift above, one
#: layer up. Every dotted name in this comment is resolved by
#: ``tests/test_hook_event_contracts.py``, so a move reds instead of staling it.
GATE_SHAPES = frozenset({
    GATE_ABSENT, GATE_ORPHANED, GATE_INERT, GATE_LEGACY_FORM,
    GATE_MISWIRED, GATE_VOIDED_SETTINGS,
})


def GATE_EVENT_OF(script: str) -> str:
    """The canonical event a hook belongs under -- blocking gate or reporter.

    Read from ``CANONICAL_HOOK_WIRING`` (the SoT both tiers derive from), so
    the shape classifier and the narrators answer for a reporter too.
    """
    return CANONICAL_HOOK_WIRING.get(script, {}).get("event", "?")


def _gate_command_blobs(repo_root: Path, script: str) -> list[str]:
    """Every ``command + args`` blob in settings.json that names ``script``."""
    settings_path = repo_root / ".claude" / "settings.json"
    try:
        data = json.loads(
            surface_contract.decode_bom(settings_path.read_bytes())
        )
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    hooks_cfg = data.get("hooks")
    if hooks_cfg is None:
        hooks_cfg = {}
    if not isinstance(hooks_cfg, dict):
        return []
    blobs: list[str] = []
    for entries in hooks_cfg.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            hooks_list = entry.get("hooks")
            if not isinstance(hooks_list, list):
                continue
            for hook in hooks_list:
                if not isinstance(hook, dict):
                    continue
                # Depth 2. The docstring above says "`or {}` is not a guard: a
                # truthy non-dict sails through it" -- and then the first
                # draft applied that only at depth 1. `args` is any JSON
                # type in a hand-edited file; a scalar made `init` exit 1
                # with a traceback and a PARTIAL DEPLOY, on the first
                # command a new adopter runs.
                args = hook.get("args")
                blob = " ".join(
                    str(x) for x in
                    [hook.get("command"), *(args if isinstance(args, list) else [])]
                    if isinstance(x, str)
                )
                if blob_names_script(blob, script):
                    blobs.append(blob)
    return blobs


_BLOB_TOKEN_SPLIT = re.compile(r"[\s\"';|&()]+")


def blob_names_script(blob: str, script: str) -> bool:
    """Does a ``command + args`` blob carry ``script`` as a whole path token?

    Tokenised on the same punctuation :func:`names_a_python_interpreter`
    splits on, then BASENAME EQUALITY per token -- never a substring test.
    The substring version (``script in blob``) read an operator's
    ``my_plan_guard.py`` as a copy of ``plan_guard.py``: the classifier filed
    the gate as legacy-form and ``merge-settings --repair`` deleted the
    operator's entry while reporting it preserved (both found by review,
    driven). One predicate, both readers.
    """
    for raw in _BLOB_TOKEN_SPLIT.split(blob):
        if not raw:
            continue
        if raw.replace("\\", "/").rsplit("/", 1)[-1] == script:
            return True
    return False


def names_a_python_interpreter(blob: str) -> bool:
    """Does this command+args blob invoke a python interpreter anywhere?

    Tokenised rather than regexed, on purpose: the first draft was a
    character-class regex that went through two layers of shell quoting and
    came out matching a bare letter. Splitting on whitespace and shell
    punctuation and comparing whole tokens cannot fail that way.
    """
    for raw in re.split(r"[\s\"';|&()]+", blob):
        token = raw.replace("\\", "/").rsplit("/", 1)[-1]
        if token.lower().endswith(".exe"):
            token = token[:-4]
        stem = token.rstrip("0123456789.")
        if stem.lower() in ("python", "py", "pythonw"):
            return True
    return False


def classify_unwired_gate(repo_root: Path, script: str) -> str:
    """WHY this gate is not executably wired -- and therefore what fixes it.

    Each shape needs a different answer; the plain merge repairs only
    ``GATE_ABSENT`` and ``merge-settings --repair`` (the opt-in,
    ``cli.repair_hook_wiring_in_settings``) rewrites every other shape but
    ``GATE_VOIDED_SETTINGS``. In the plain merge's terms only ``GATE_ABSENT`` is repaired
    by a command. All were driven -- the first four on 2026-08-27, the
    whole-file one on 2026-08-27 against real Claude Code 2.1.247:

    * ``GATE_VOIDED_SETTINGS`` -- checked FIRST and not a fact about this
      gate's entry at all: some hook object anywhere in the file has a
      ``type`` other than ``"command"``, so CC loads NO hooks and this gate
      is dead however well it is wired. See
      :func:`surface_contract.hooks_config_voided_by`.

    * ``GATE_ABSENT`` -- the gate's canonical EVENT KEY is missing from
      settings.json. ``merge-settings`` tops up the event and the gate comes
      back (verified: 0 governance failures afterwards). This is the shape
      whose remedy a prior session recorded as "dead"; that record was produced
      by driving the *inert* tree and generalising.
    * ``GATE_ORPHANED`` -- the event key EXISTS but carries no entry for this
      script. ⚠ ``merge-settings`` is a NO-OP here and still reports success:
      the merge core's unit is the event, not the entry. Driven on a tree with
      one gate of each shape, it repaired the absent one and left the orphaned
      one dead. Offering it as the remedy would hand the operator a false
      finish, which is worse than offering nothing.
    * ``GATE_INERT`` -- an entry names the script but runs no interpreter
      (``echo``, ``true``, ``:``, a wrong ``type``). ⚠ NO PLAIN COMMAND
      REPAIRS THIS; ``merge-settings --repair`` replaces the entry.
      ``merge-settings`` returns MERGE_ALREADY and writes nothing, ``init``
      renders ``settings.json.new`` and preserves the file, ``upgrade
      --execute`` declines. The honest answer is a hand edit.
    * ``GATE_LEGACY_FORM`` -- an interpreter IS named but in the pre-v0.6.5
      shell form the exec-form extractor deliberately fails closed on. The gate
      most likely fires; what is broken is our ability to prove it.
    * ``GATE_MISWIRED`` -- an exec-form entry the extractor CAN read names the
      script, but under the wrong event or with a matcher that excludes tools
      the hook must see (a plan_guard narrowed to ``Write``; a config_guard
      moved onto PostToolUse). Verifiably dead, unlike legacy_form; the remedy
      is ``merge-settings --repair`` (or a hand edit), and
      :func:`miswiring_detail` says which half is wrong.

    Pure classification, no policy. ``cli`` uses it to decide whether the
    enforcement claim must abstain; ``doctor`` uses it to pick a remedy. Neither
    decision belongs in here, and keeping it that way is what lets ``doctor``
    stay count-parity-locked with ``tools/cc/ci_guard.py`` while the claim is
    free to be more forgiving.
    """
    # FIRST, because it is not a fact about this gate's entry at all. When any
    # hook object in the file carries a `type` other than "command", Claude Code
    # loads NOTHING, so this gate's own wiring can be flawless and still dead.
    # Asking the entry-shape questions below would produce a true sentence about
    # the entry and a false remedy for the operator -- who must fix somebody
    # else's hook, possibly under a different event.
    if surface_contract.hooks_config_voided_by(
        surface_contract._load_settings_hooks_cfg(repo_root)
    ) is not None:
        return GATE_VOIDED_SETTINGS
    blobs = _gate_command_blobs(repo_root, script)
    if not blobs:
        # Not named anywhere -- but "merge-settings fixes it" depends on WHY.
        # The merge core tops up a missing EVENT; it treats an event that
        # already exists as wired and adds nothing inside it. Driven
        # 2026-08-27 on one tree carrying both shapes: deleting the whole
        # ConfigChange key was repaired, while deleting plan_guard's entry from
        # a surviving PreToolUse was NOT -- merge-settings ran, reported
        # success, and left that gate dead. Distinguishing them is the
        # difference between an action and a false finish.
        event = GATE_EVENT_OF(script)
        settings_path = repo_root / ".claude" / "settings.json"
        try:
            data = json.loads(
                surface_contract.decode_bom(settings_path.read_bytes())
            )
        except (OSError, ValueError):
            return GATE_ABSENT
        hooks_cfg = data.get("hooks") if isinstance(data, dict) else None
        if isinstance(hooks_cfg, dict) and event in hooks_cfg:
            return GATE_ORPHANED
        return GATE_ABSENT
    if _readable_wirings_of(repo_root, script):
        # The exec-form extractor READ an entry for this script and it is still
        # unwired, so the entry sits under the wrong event or carries a matcher
        # that excludes tools it must see. Checked BEFORE the interpreter test
        # below: such an entry names an interpreter too, and used to fall into
        # legacy_form -- the one shape the enforcement claim forgives.
        return GATE_MISWIRED
    if any(names_a_python_interpreter(b) for b in blobs):
        return GATE_LEGACY_FORM
    return GATE_INERT


def _readable_wirings_of(repo_root: Path, script: str) -> list[dict]:
    """The exec-form wirings ``discover_executable_hook_wirings`` can read for
    ``script`` (canonical path), under ANY event."""
    canonical = f"tools/cc/hooks/{script}"
    return [
        w for w in surface_contract.discover_executable_hook_wirings(repo_root)
        if w["script"] == canonical
    ]


def miswiring_detail(repo_root: Path, script: str) -> str:
    """Why a ``GATE_MISWIRED`` entry does not fire, in the operator's terms:
    the wrong event, or a matcher that does not cover the canonical one. Pure
    description -- both narrators print it; neither decides anything on it.
    """
    event = GATE_EVENT_OF(script)
    canonical_matcher = CANONICAL_HOOK_WIRING.get(script, {}).get("matcher", "")
    wirings = _readable_wirings_of(repo_root, script)
    under_event = [w for w in wirings if w["event"] == event]
    if not under_event:
        seen = sorted({str(w["event"]) for w in wirings}) or ["?"]
        return (
            f"wired under {', '.join(repr(e) for e in seen)} instead of "
            f"{event!r}"
        )
    deployed = sorted({str(w.get("matcher", "")) for w in under_event})
    return (
        f"wired under {event!r} with matcher "
        f"{', '.join(repr(m) for m in deployed)}, which does not cover the "
        f"canonical {canonical_matcher!r}"
        + ("" if canonical_matcher else " (no matcher)")
    )


def group_unwired_gates_by_shape(repo_root: Path) -> dict[str, list[str]]:
    """Every unwired blocking gate on this tree, keyed by WHY it is unwired.

    ``{shape: sorted script names}`` over :func:`unwired_governance_gates`,
    carrying only the shapes actually present. This is the composition of the
    two predicates above, hoisted for the same reason
    ``unwired_governance_gates`` itself was: ``doctor`` and ``cli`` both need
    it, and a second copy of the bucketing in ``espalier/*.py`` would be a
    fresh ``sister_site_probe`` clique costing one of the last opt-out slots to
    say nothing new. One home, two callers, no marker.

    ⚠ Pure classification -- ``GATE_LEGACY_FORM`` is INCLUDED, and the caller
    filters it. The two callers want OPPOSITE things from that shape and
    neither answer belongs in here: ``doctor`` reports it, because a shape the
    exec-form oracle cannot verify should be loud, while the enforcement claim
    ABSTAINS on it, because telling a pre-v0.6.5 adopter whose gates genuinely
    fire that they are dead is the false negative ``b517a72`` closed. Pushing
    either policy down here would silently impose it on the other caller.

    ⚠ Callers must not read a missing key as "that shape is impossible" -- it
    means "no gate on THIS tree has it". Use ``.get(SHAPE, [])``.
    """
    return _group_by_shape(repo_root, unwired_governance_gates(repo_root))


def group_unwired_reporters_by_shape(repo_root: Path) -> dict[str, list[str]]:
    """Every unwired reporter hook on this tree, keyed by WHY (DEF-619).

    The reporter-tier twin of :func:`group_unwired_gates_by_shape`, over the
    same shape roster and the same classifier -- a reporter goes absent,
    orphaned, inert or legacy-form by exactly the mechanisms a gate does. Only
    the consequence differs, and that is the caller's sentence to write.
    """
    return _group_by_shape(repo_root, unwired_reporter_hooks(repo_root))


def _group_by_shape(repo_root: Path, scripts: list[str]) -> dict[str, list[str]]:
    shapes: dict[str, list[str]] = {}
    for script in scripts:
        shapes.setdefault(
            classify_unwired_gate(repo_root, script), []
        ).append(script)
    return {shape: sorted(scripts) for shape, scripts in shapes.items()}
