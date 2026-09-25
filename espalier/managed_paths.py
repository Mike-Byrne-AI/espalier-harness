"""Explicit managed-path inventory — prevents the harness from stomping user files.

Two modes:

- **Generic-plan ownership** — for target repos with a saved `BuildPlan`. The
  harness declares what it creates there; the list is derived from the plan
  plus the canonical hook scripts from `surface_contract`.
- **Self-host ownership** — for the Espalier-Harness repo itself. Derived entirely
  from `surface_contract.discover_self_host_surface(repo_root)`, so the
  ownership inventory tracks disk reality.

Both modes return sorted, deduped, forward-slash-normalized paths.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from espalier import surface_contract
from espalier.models import BuildPlan

# Single source of truth for the committed project-memory filename — routed
# through one constant so a future rename is a value flip, not scattered edits.
_MEMORY_FILENAME = "ESPALIER_MEMORY.md"

# Files in .claude/
STANDARD_MANAGED_SETTINGS = [
    ".claude/settings.json",
]

# Files in cc/ — generic-plan baseline (self-host mode reads the contract)
STANDARD_MANAGED_CC_DOCS = [
    "cc/LIVE_SURFACE.md",
    "cc/COMMANDS.md",
    "cc/PACK_MANIFEST.txt",
]

#: The statusline script ``init`` wires into ``settings.json``'s ``statusLine``
#: (``cli._statusline_command``) and, on Windows, the batch shim wired as the
#: command's HEAD that runs the script with the interpreter it is handed and
#: prints the fallback line neither Windows shell can carry itself (DEF-729).
#: One spelling each, read by the render, doctor's notes and cleanup's unwire.
STATUSLINE_SCRIPT = "tools/cc/statusline.py"
STATUSLINE_SHIM = "tools/cc/statusline.cmd"

#: The suffixes a deployed script under ``tools/cc/`` can carry. Read by the
#: retired-file scan in ``cli._scan_managed_orphans``; pinned equal to the
#: ``vendor-cc`` mirror row's brace set and the sync script's constant by
#: ``tests/test_vendor_cc_parity.py`` (the script is stdlib-only and cannot
#: import this).
DEPLOYED_SCRIPT_SUFFIXES: tuple[str, ...] = (".py", ".cmd")

# Files in tools/cc/ (non-hook tools). SINGLE OWNER of the non-hook tool-script
# set: cli.INIT_TOOL_SCRIPTS derives from this list, so init deployment and the
# managed inventory agree by construction (formerly two hand-maintained copies
# bound by a parity test).
STANDARD_MANAGED_TOOLS = [
    "tools/cc/cognitive_blueprint.py",
    "tools/cc/execution_plan.py",
    "tools/cc/reflect_protocol.py",
    "tools/cc/session_resume.py",
    # invoked by Claude Code via the /read-summary command body.
    "tools/cc/read_summary.py",
    # invoked by Claude Code via the /handoff command body.
    "tools/cc/session_summary.py",
    # statusline invoked by Claude Code per settings.json::statusLine.
    STATUSLINE_SCRIPT,
    # The Windows statusline shim: the head of statusLine.command on an nt
    # render, the only deployed non-.py file. Deployed everywhere so a tracked
    # settings.json rendered on Windows (DEF-11) finds it on every checkout.
    STATUSLINE_SHIM,
    # invoked by Claude Code via /implement-pack step 0-C (compression probe);
    # deployed so the shipped common-tier command references a real file on a
    # fresh adopter.
    "tools/cc/sister_site_probe.py",
    # Sibling-module mirror of espalier/_blueprint_limits.py. Imported by
    # cognitive_blueprint.py AND tools/cc/hooks/post_compact.py; both raise
    # ModuleNotFoundError on a fresh init if it is not deployed alongside.
    "tools/cc/_blueprint_limits.py",
    # Shared state-cache reader imported by statusline.py (sibling) and
    # hooks/session_start.py (parent-dir sys.path). Both raise
    # ModuleNotFoundError on a fresh init if it is not deployed.
    "tools/cc/_freshness_cache.py",
    # SoT for cc/ path strings (LIVE_SURFACE_REL, COMMANDS_INDEX_REL,
    # PACK_MANIFEST_REL, BLUEPRINTS_DIR_REL, ...). Imported by session_resume.py
    # + hooks (_protected_zones.py, post_write_check.py) via sys.path shim.
    "tools/cc/_paths.py",
    # Malformed/non-dict JSON chokepoint (load_json_dict_safe). Imported by
    # cognitive_blueprint.py + execution_plan.py (siblings) and by hooks
    # reflect_trigger.py / stop_gate.py / _integrity.py via sys.path shim. All
    # raise ModuleNotFoundError on a fresh init if absent.
    "tools/cc/_json_safe.py",
]

# Root-level docs
STANDARD_MANAGED_ROOT_DOCS = [
    "CLAUDE.md",
    _MEMORY_FILENAME,
    "docs/CONVENTIONS.md",
    "docs/SHARP_EDGES.md",
    "docs/CHEAT-SHEET.md",
    "docs/TASK_RECIPES.md",
    ".claudeignore",
]

# Reports
STANDARD_MANAGED_REPORTS = [
    "reports/harness_config.json",
    "reports/repo_fingerprint.json",
]

# Coarse top-level roots the harness governs — the audit/report ownership SUMMARY
# view (NOT the fine-grained public-deploy surface in
# managed_inventory._PUBLIC_PREFIXES). Single owner: espalier.doctor's fallback
# ownership dict derives its harness_owned_roots from THIS constant so the two can
# never drift. ownership_summary appends "espalier" in self-host mode; the doctor
# fallback is reached only in the NON-self-host case, so it uses the base tuple.
HARNESS_OWNED_ROOTS: tuple[str, ...] = (".claude", "cc", "tools/cc")


def _canonical_hook_paths() -> list[str]:
    """Tools/cc/hooks/* paths derived from the contract — one source of truth."""
    return [f"tools/cc/hooks/{name}" for name in surface_contract.get_canonical_hook_scripts()]


def _as_mapping(plan_or_dict: BuildPlan | dict[str, Any]) -> dict[str, Any]:
    if isinstance(plan_or_dict, BuildPlan):
        return plan_or_dict.to_dict()
    return dict(plan_or_dict)


def managed_paths_from_plan(plan_or_dict: BuildPlan | dict[str, Any]) -> list[str]:
    """Derive the full managed-path inventory from a build plan (generic mode)."""
    plan_data = _as_mapping(plan_or_dict)
    agents = plan_data.get("agents") if isinstance(plan_data.get("agents"), list) else []
    generated_docs = plan_data.get("generated_docs") if isinstance(plan_data.get("generated_docs"), list) else []

    paths: list[str] = [
        *STANDARD_MANAGED_SETTINGS,
        *STANDARD_MANAGED_CC_DOCS,
        *STANDARD_MANAGED_TOOLS,
        *_canonical_hook_paths(),
        *STANDARD_MANAGED_ROOT_DOCS,
        *STANDARD_MANAGED_REPORTS,
    ]

    for agent in agents:
        if isinstance(agent, dict) and agent.get("name"):
            paths.append(f".claude/agents/{agent['name']}.md")

    for doc in generated_docs:
        doc_str = str(doc)
        if doc_str.startswith(".claude/commands/"):
            paths.append(doc_str)

    return sorted(set(paths))


def self_host_managed_paths(repo_root: Path) -> list[str]:
    """Derive self-host ownership from the discovered surface (disk reality)."""
    surface = surface_contract.discover_self_host_surface(repo_root)

    paths: set[str] = set()
    paths.update(STANDARD_MANAGED_SETTINGS)
    paths.update(STANDARD_MANAGED_CC_DOCS)
    paths.update(STANDARD_MANAGED_TOOLS)
    paths.update(STANDARD_MANAGED_ROOT_DOCS)
    paths.update(_canonical_hook_paths())
    paths.update(surface_contract.get_managed_report_paths())

    # Every .claude/ kind the deploy writes, from the contract's one owner: a
    # kind listed by hand here left the deployed skills out of the ownership
    # report while clean-generated removed them (driven 2026-09-11). The
    # kinds are indexed, not .get(): the composite is built from the same
    # owner, so a missing key is a contract break that must raise.
    for kind in surface_contract.CLAUDE_SURFACE_KINDS:
        paths.update(surface[kind])
    paths.update(surface.get("hooks", []))
    paths.update(surface.get("managed_reports", []))

    return sorted(p.replace("\\", "/") for p in paths)


def managed_paths_for_repo(
    repo_root: Path,
    plan: BuildPlan | dict[str, Any] | None = None,
) -> list[str]:
    """Dispatch to self-host or generic-plan ownership based on repo identity.

    The generic-plan branch is the PLAN's view: it names the plan's agents and
    the ``.claude/commands/`` entries of ``generated_docs`` and nothing else
    under ``.claude/`` (a saved plan carries no skills source). A caller who
    wants what is on disk -- every deployed agent, command and skill -- reads
    ``ownership_summary`` or ``fallback_managed_paths``, as ``doctor`` does.
    """
    if surface_contract.is_self_host_repo(repo_root):
        return self_host_managed_paths(repo_root)
    if plan is not None:
        return managed_paths_from_plan(plan)
    return fallback_managed_paths(repo_root)


def fallback_managed_paths(repo_root: Path) -> list[str]:
    """Discover managed paths by scanning known directories when no plan exists."""
    paths: set[str] = set()

    for rel_path in [
        *STANDARD_MANAGED_SETTINGS,
        *STANDARD_MANAGED_CC_DOCS,
        *STANDARD_MANAGED_TOOLS,
        *_canonical_hook_paths(),
        *STANDARD_MANAGED_ROOT_DOCS,
        *STANDARD_MANAGED_REPORTS,
    ]:
        if (repo_root / rel_path).exists():
            paths.add(rel_path)

    # The .claude/ kinds and their per-kind globs are the contract's one
    # owner -- what the self-host view reads too -- so the two disk-reality
    # views cannot disagree on what init deploys under .claude/ (two
    # hand-written globs here saw agents and commands and never skills).
    for found in surface_contract.discover_claude_surface(repo_root).values():
        paths.update(found)

    cc_dir = repo_root / "cc"
    if cc_dir.exists():
        for path in cc_dir.glob("*.md"):
            paths.add(str(path.relative_to(repo_root)).replace("\\", "/"))
        for path in cc_dir.glob("*.txt"):
            paths.add(str(path.relative_to(repo_root)).replace("\\", "/"))

    tools_dir = repo_root / "tools" / "cc"
    if tools_dir.exists():
        for path in tools_dir.glob("*.py"):
            paths.add(str(path.relative_to(repo_root)).replace("\\", "/"))

    return sorted(paths)


def ownership_summary(
    plan_or_dict: BuildPlan | dict[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Summarize what the harness owns vs what the user owns.

    In self-host mode (repo_root points at the Espalier-Harness repo itself) the
    summary reflects discovered on-disk reality; the plan-derived list is
    included separately so callers can compare the two without collapsing
    them into a single blob.
    """
    self_host = bool(repo_root and surface_contract.is_self_host_repo(repo_root))
    plan_paths = managed_paths_from_plan(plan_or_dict) if plan_or_dict else []
    # current_paths = DISK REALITY, so an adopter's ownership report
    # matches what init actually deployed: self-host derives from the discovered
    # surface; a plan-bearing adopter derives from a disk scan (fallback globs
    # every deployed agent and gates root docs on existence) instead of the plan,
    # which under-claims tier-deployed agents and over-claims not-yet-generated
    # docs. The plan view stays available as ``plan_derived_managed_paths``.
    if self_host and repo_root:
        current_paths = self_host_managed_paths(repo_root)
    elif repo_root is not None:
        current_paths = fallback_managed_paths(repo_root)
    else:
        current_paths = plan_paths

    # Coarse ownership SUMMARY (top-level roots) for the audit/report view — NOT the
    # fine-grained public-deploy surface managed_inventory._PUBLIC_PREFIXES (which lists
    # `.claude/agents/` etc.). The two answer different questions; merging them would
    # either leak settings.local.json as "public" or drop `espalier/` from the summary.
    owned_roots = list(HARNESS_OWNED_ROOTS)
    if self_host:
        owned_roots.append("espalier")

    return {
        "mode": "self_host" if self_host else "plan",
        "harness_owned_roots": owned_roots,
        "managed_paths": current_paths,
        "plan_derived_managed_paths": plan_paths,
        "managed_settings": [p for p in current_paths if p.startswith(".claude/")],
        "managed_cc_docs": [p for p in current_paths if p.startswith("cc/")],
        "managed_tools": [p for p in current_paths if p.startswith("tools/cc/")],
        "managed_reports": [p for p in current_paths if p.startswith("reports/")],
        "managed_root_docs": [
            p for p in current_paths
            if "/" not in p or p.startswith("docs/")
        ],
        "user_owned_by_default": "anything outside the explicit managed-path inventory",
    }
