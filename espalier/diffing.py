"""Compare saved fingerprint and build plan against fresh inference to detect drift.

Two modes:

- **Generic target-repo mode** — saved fingerprint vs fresh fingerprint, and
  saved plan vs `build_harness_config(fresh_fingerprint)`. Used for repos that
  install Espalier-Harness but aren't Espalier-Harness themselves.
- **Self-host mode** — saved self-host state in `reports/harness_config.json`
  vs current surface from `surface_contract.discover_self_host_surface(repo_root)`.
  The generic generator is never the authority when the repo IS Espalier-Harness.
"""
from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from espalier import surface_contract
from espalier._report_io import load_report_json
from espalier.analyze import DOCS_CUES_PREFIX, fingerprint_repo
from espalier.config import load_config
from espalier.harness_config import build_harness_config
from espalier.models import AgentSpec, BuildPlan, HarnessConfig, HookSpec, RepoFingerprint

#: The keys the current schema declares, top level and nested. A saved report
#: written by an older release can carry a key the dataclass has since retired
#: (`BuildPlan` lost `proof_gates` and `profile_scores`); the fresh side never
#: has it, so the union in `_changed_keys` read every such key as drift and
#: `espalier diff` exited 1 over a key the adopter never set. Both normalizers
#: drop undeclared keys from either side, the plan's nested agents, hooks and
#: config included; `espalier upgrade --execute` re-baselines anyway.
_FINGERPRINT_KEYS = frozenset(f.name for f in fields(RepoFingerprint))
_PLAN_KEYS = frozenset(f.name for f in fields(BuildPlan))
_AGENT_KEYS = frozenset(f.name for f in fields(AgentSpec))
_HOOK_KEYS = frozenset(f.name for f in fields(HookSpec))
_CONFIG_KEYS = frozenset(f.name for f in fields(HarnessConfig))
#: The registry entry for that drop; `<` marks it as not a field name.
_UNDECLARED = '<undeclared keys>(retired from the schema; dropped, nested too)'


EPHEMERAL_ZONES = {
    '.pytest_cache',
    '__pycache__',
    'coverage',
    'htmlcov',
    'node_modules',
    'dist',
    'build',
    '.mypy_cache',
    '.ruff_cache',
    '.tox',
    '.next',
    'target',
}


def _load_json(path: Path) -> dict:
    return load_report_json(path)


def _filter_zones(items: list[str]) -> list[str]:
    return [item for item in items if item not in EPHEMERAL_ZONES]


def _filter_guardrails(items: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in items:
        if not any(zone in item for zone in EPHEMERAL_ZONES):
            cleaned.append(item)
    return cleaned


#: The fingerprint fields the comparison reduces, and to what. The fingerprint
#: is signal, not census (docs/SHARP_EDGES.md "Fingerprint Is Signal-Based,
#: Not Census-Based"): a saved report keeps every field, but `espalier diff`
#: and doctor's drift check compare only the KIND of repo each field reads --
#: a format, a presence, a set of names -- never a size, a count or a sample.
#: Before this registry the normalizers compared commit subjects, a ratio,
#: per-language file counts, byte sizes and a per-page docs listing verbatim,
#: so an ordinary commit, a lock-file bump or a new docs page turned doctor
#: yellow (2026-10-04; `tests/test_diffing.py::TestDriftIsSignalNotCensus` is
#: the matrix). Each entry names the key and, in parentheses, what the
#: comparison keeps. This tuple IS the `ignored_local_only_keys` list the diff
#: results print, so a reduction added to `_normalize_fingerprint` is named
#: there by construction; `tests/test_diffing.py::TestReductionsAreNamed`
#: pins the two apart in both directions, and `::TestEveryFieldIsClassified`
#: requires every dataclass field to sit in this tuple or in the signal roster
#: below it, so a field added later cannot compare verbatim unnoticed.
FINGERPRINT_REDUCTIONS: tuple[str, ...] = (
    'repo_name',
    'repo_root',
    'generated_zones',
    'risky_mutable_zones',
    'conventions.guardrails(ephemeral-only)',
    'conventions.git(format kept in git_conventions)',
    'conventions.docs(cues line dropped; docs_surface cues kept)',
    'git_conventions(format kept)',
    'language_counts(names kept)',
    'languages(primary and name set kept)',
    'large_files(paths kept; presence only at the 50-file cut)',
    'docs_surface(cues kept; per-page entries dropped)',
    'signals(names kept)',
    'architecture(pattern and layer rules kept; layers dropped)',
    'notes(restate fields compared elsewhere; dropped)',
    'garbage_files',
    _UNDECLARED,
)

#: The fingerprint fields compared as they are: each reads the kind of repo
#: (a provider, a framework, a command, a presence, a profile). A field added
#: to `RepoFingerprint` must join this roster or the registry above.
FINGERPRINT_SIGNAL_FIELDS: frozenset[str] = frozenset({
    'package_systems', 'package_roots', 'package_manager', 'ci_providers', 'entrypoints',
    'test_commands', 'inferred_actions', 'runtime_surface', 'api_surface',
    'ui_surface', 'ml_surface', 'ops_surface', 'ops_directories', 'monorepo',
    'profiles', 'confidence',
})

#: The plan fields the comparison reduces. `settings_profile` is a RECORD init
#: writes (which profile rendered this install's settings.json -- DEF-715), not
#: an inference a rebuild reproduces; the zones are the ephemeral filter; the
#: per-page docs entries `harness_config._scope_paths` copies into an agent's
#: primary paths are census (a page that sorts early would flip the plan); the
#: plan's notes are the fingerprint's. Entries shared with the fingerprint
#: registry carry the same text, so the printed union holds each once.
PLAN_REDUCTIONS: tuple[str, ...] = (
    'repo_name',
    'settings_profile',
    'read_only_zones',
    'mutable_zones',
    'agents[].generated_paths',
    'agents[].primary_paths(docs/ pages dropped)',
    'suggested_agents(names kept)',
    'notes(restate fields compared elsewhere; dropped)',
    _UNDECLARED,
)

#: The plan fields compared as they are.
PLAN_SIGNAL_FIELDS: frozenset[str] = frozenset({
    'profiles', 'stable_actions', 'generated_docs', 'unresolved_questions',
    'hooks', 'config',
})

#: `detect_large_files` keeps the fifty largest, so at fifty the path set
#: churns as files trade places under the cut without any crossing the
#: threshold; from there the comparison reads presence alone.
_LARGE_FILES_CUT = 50
_LARGE_FILES_AT_CUT = '<fifty or more files over the threshold>'


def _drop_undeclared(normalized: dict[str, Any], declared: frozenset[str]) -> None:
    for key in [k for k in normalized if k not in declared]:
        normalized.pop(key, None)


def _is_docs_page(entry: Any) -> bool:
    """A per-page docs entry (`docs/<page>.md`, as `detect_docs_surface` lists
    an owned page) as opposed to a cue (`README.md`, `CONTRIBUTING.md`,
    `ARCHITECTURE.md`, `docs`) or a package root that happens to live under
    `docs/` (`docs/site`)."""
    return (
        isinstance(entry, str)
        and entry.startswith('docs/')
        and entry.lower().endswith('.md')
    )


def _normalize_fingerprint(data: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(data))  # json-dict-safe: ok -- json.dumps round-trip of an in-memory dict (loader guards non-dict)
    # Both name the directory the clone sits in: machine-local.
    if 'repo_root' in normalized:
        normalized['repo_root'] = '<repo_root>'
    if 'repo_name' in normalized:
        normalized['repo_name'] = '<repo_name>'
    if isinstance(normalized.get('generated_zones'), list):
        normalized['generated_zones'] = _filter_zones(normalized['generated_zones'])
    if isinstance(normalized.get('risky_mutable_zones'), list):
        normalized['risky_mutable_zones'] = _filter_zones(normalized['risky_mutable_zones'])
    conventions = normalized.get('conventions')
    if isinstance(conventions, dict):
        if isinstance(conventions.get('guardrails'), list):
            conventions['guardrails'] = _filter_guardrails(conventions['guardrails'])
            if not conventions['guardrails']:
                conventions.pop('guardrails', None)
        # The git line restates the format with a ratio and three sample
        # subjects; the format is kept below, the samples move every commit.
        conventions.pop('git', None)
        # The cues line restates docs_surface, per-page entries included.
        if isinstance(conventions.get('docs'), list):
            conventions['docs'] = [
                line for line in conventions['docs']
                if not (isinstance(line, str) and line.startswith(DOCS_CUES_PREFIX))
            ]
            if not conventions['docs']:
                conventions.pop('docs', None)
    git_conventions = normalized.get('git_conventions')
    if isinstance(git_conventions, dict):
        # evidence is the five newest subjects; confidence is a ratio over
        # the last thirty commits -- both move on any commit.
        normalized['git_conventions'] = {'format': git_conventions.get('format')}
    if isinstance(normalized.get('language_counts'), dict):
        normalized['language_counts'] = sorted(normalized['language_counts'])
    if isinstance(normalized.get('languages'), list):
        languages = normalized['languages']
        # `languages[0]` is the primary language the CLI keys on, so a swap at
        # the top is a signal; the order below it is file-count census.
        normalized['languages'] = {
            'primary': languages[0] if languages else None,
            'names': sorted(str(name) for name in languages),
        }
    if isinstance(normalized.get('large_files'), list):
        # A file crossing the threshold is a fact about the tree; its size and
        # line count growing (a lock file on a dependency bump) is not.
        paths = sorted(
            item.get('path') for item in normalized['large_files']
            if isinstance(item, dict) and isinstance(item.get('path'), str)
        )
        normalized['large_files'] = (
            [_LARGE_FILES_AT_CUT] if len(paths) >= _LARGE_FILES_CUT else paths
        )
    if isinstance(normalized.get('docs_surface'), list):
        normalized['docs_surface'] = [
            entry for entry in normalized['docs_surface'] if not _is_docs_page(entry)
        ]
    if isinstance(normalized.get('signals'), list):
        # A signal appearing or disappearing is the kind change; its evidence
        # list echoes the census fields above.
        normalized['signals'] = sorted(
            item.get('name') for item in normalized['signals']
            if isinstance(item, dict) and isinstance(item.get('name'), str)
        )
    architecture = normalized.get('architecture')
    if isinstance(architecture, dict):
        # `layers` lists every directory under `src/` (or the mvc set), so a
        # new component folder read as an architecture change; the pattern and
        # the layer rules are the kind of tree.
        normalized['architecture'] = {
            k: v for k, v in architecture.items() if k in ('pattern', 'layer_rules')
        }
    # Every risk note restates a field compared on its own (large files, test
    # commands, package roots) or one dropped on purpose (root debris).
    normalized.pop('notes', None)
    # Root debris is machine-local; doctor's own root-garbage check reports it live.
    normalized.pop('garbage_files', None)
    _drop_undeclared(normalized, _FINGERPRINT_KEYS)
    return normalized


def _normalize_plan(data: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(data))  # json-dict-safe: ok -- json.dumps round-trip of an in-memory dict (loader guards non-dict)
    normalized.pop('settings_profile', None)
    if 'repo_name' in normalized:
        normalized['repo_name'] = '<repo_name>'
    normalized.pop('notes', None)
    if isinstance(normalized.get('read_only_zones'), list):
        normalized['read_only_zones'] = _filter_zones(normalized['read_only_zones'])
    if isinstance(normalized.get('mutable_zones'), list):
        normalized['mutable_zones'] = _filter_zones(normalized['mutable_zones'])
    agents = normalized.get('agents')
    if isinstance(agents, list):
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            if isinstance(agent.get('generated_paths'), list):
                agent['generated_paths'] = _filter_zones(agent['generated_paths'])
            if isinstance(agent.get('primary_paths'), list):
                agent['primary_paths'] = [
                    p for p in agent['primary_paths'] if not _is_docs_page(p)
                ]
            _drop_undeclared(agent, _AGENT_KEYS)
    # Suggestions are advice init prints, built from surface flags the
    # fingerprint half already compares: their names say which, and their
    # primary paths are the same census the agents' are.
    suggested = normalized.get('suggested_agents')
    if isinstance(suggested, list):
        normalized['suggested_agents'] = sorted(
            str(a.get('name')) for a in suggested if isinstance(a, dict) and a.get('name')
        )
    hooks = normalized.get('hooks')
    if isinstance(hooks, list):
        for hook in hooks:
            if isinstance(hook, dict):
                _drop_undeclared(hook, _HOOK_KEYS)
    if isinstance(normalized.get('config'), dict):
        _drop_undeclared(normalized['config'], _CONFIG_KEYS)
    _drop_undeclared(normalized, _PLAN_KEYS)
    return normalized


def _changed_keys(fresh: dict, saved: dict) -> list[str]:
    keys = sorted(set(fresh) | set(saved))
    return [key for key in keys if fresh.get(key) != saved.get(key)]


def _saved_plan_surface_view(plan: dict[str, Any]) -> dict[str, list[str]]:
    """Normalize a saved plan to the same shape discover_self_host_surface returns."""
    agents = sorted({
        f".claude/agents/{a.get('name')}.md"
        for a in plan.get("agents", []) or []
        if isinstance(a, dict) and a.get("name")
    })
    hooks = sorted({
        h.get("script", "")
        for h in plan.get("hooks", []) or []
        if isinstance(h, dict)
        and isinstance(h.get("script"), str)
        and h.get("script", "").startswith("tools/cc/hooks/")
    })
    generated_docs = sorted({
        d for d in plan.get("generated_docs", []) or [] if isinstance(d, str)
    })
    commands = sorted({d for d in generated_docs if d.startswith(".claude/commands/")})
    return {
        "agents": agents,
        "commands": commands,
        "hooks": hooks,
        "generated_docs": generated_docs,
    }


def current_surface_report(repo_root: Path, mode: str = "auto") -> dict[str, Any]:
    """Describe the repo's current managed surface in a comparison-ready shape.

    `mode="auto"` dispatches on `surface_contract.is_self_host_repo(repo_root)`.
    Forcing `mode="self_host"` or `mode="generic"` bypasses detection.
    """
    repo_root = repo_root.resolve()
    detected = "self_host" if surface_contract.is_self_host_repo(repo_root) else "generic"
    resolved = detected if mode == "auto" else mode

    surface = surface_contract.discover_self_host_surface(repo_root)
    return {
        "mode": resolved,
        "repo_root": str(repo_root),
        "agents": surface.get("agents", []),
        "commands": surface.get("commands", []),
        "hooks": surface.get("hooks", []),
        "managed_reports": surface.get("managed_reports", []),
        "required_init_files": surface.get("required_init_files", []),
    }


def _diff_self_host(repo_root: Path) -> dict:
    """Self-host comparison: discovered surface vs saved harness_config.json."""
    saved_plan = _load_json(repo_root / "reports" / "harness_config.json")
    saved_view = _saved_plan_surface_view(saved_plan) if saved_plan else {
        "agents": [], "commands": [], "hooks": [], "generated_docs": [],
    }
    current = current_surface_report(repo_root, mode="self_host")

    changed_keys: list[str] = []
    added: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}
    for key in ("agents", "commands", "hooks"):
        current_set = set(current.get(key, []))
        saved_set = set(saved_view.get(key, []))
        if current_set != saved_set:
            changed_keys.append(key)
            added[key] = sorted(current_set - saved_set)
            removed[key] = sorted(saved_set - current_set)

    saved_fingerprint = _normalize_fingerprint(
        _load_json(repo_root / "reports" / "repo_fingerprint.json")
    )
    fresh_fp_obj = fingerprint_repo(repo_root, load_config(repo_root))
    fresh_fingerprint = _normalize_fingerprint(fresh_fp_obj.to_dict())
    fingerprint_changed = fresh_fingerprint != saved_fingerprint

    return {
        "repo": repo_root.name,
        "mode": "self_host",
        "fingerprint_changed": fingerprint_changed,
        "build_plan_changed": bool(changed_keys),
        "fingerprint_changed_keys": _changed_keys(fresh_fingerprint, saved_fingerprint),
        "build_plan_changed_keys": changed_keys,
        "self_host_added": added,
        "self_host_removed": removed,
        "fresh_fingerprint": fresh_fingerprint,
        "saved_fingerprint": saved_fingerprint,
        "fresh_build_plan": current,
        "saved_build_plan": saved_view,
        # The plan half above is set-valued by name, so only the fingerprint
        # reductions and the plan's recorded profile apply here.
        "ignored_local_only_keys": [*FINGERPRINT_REDUCTIONS, "settings_profile"],
    }


def _diff_generic(repo_root: Path, config_path: Path | None) -> dict:
    config = load_config(repo_root, config_path)
    fresh_fingerprint_obj = fingerprint_repo(repo_root, config)
    fresh_fingerprint = _normalize_fingerprint(fresh_fingerprint_obj.to_dict())
    fresh_plan = _normalize_plan(build_harness_config(fresh_fingerprint_obj, config).to_dict())
    saved_fingerprint = _normalize_fingerprint(_load_json(repo_root / 'reports' / 'repo_fingerprint.json'))
    saved_plan = _normalize_plan(_load_json(repo_root / 'reports' / 'harness_config.json'))
    fingerprint_changed = fresh_fingerprint != saved_fingerprint
    build_plan_changed = fresh_plan != saved_plan
    return {
        'repo': repo_root.name,
        'mode': 'generic',
        'fingerprint_changed': fingerprint_changed,
        'build_plan_changed': build_plan_changed,
        'fingerprint_changed_keys': _changed_keys(fresh_fingerprint, saved_fingerprint),
        'build_plan_changed_keys': _changed_keys(fresh_plan, saved_plan),
        'ignored_local_only_keys': list(dict.fromkeys([*FINGERPRINT_REDUCTIONS, *PLAN_REDUCTIONS])),
        'fresh_fingerprint': fresh_fingerprint,
        'saved_fingerprint': saved_fingerprint,
        'fresh_build_plan': fresh_plan,
        'saved_build_plan': saved_plan,
    }


def diff_repo(repo_root: Path, config_path: Path | None = None) -> dict:
    """Diff a repo's saved reports against its current state.

    Dispatches on `surface_contract.is_self_host_repo(repo_root)`.
    """
    repo_root = repo_root.resolve()
    if surface_contract.is_self_host_repo(repo_root):
        return _diff_self_host(repo_root)
    return _diff_generic(repo_root, config_path)
