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
from pathlib import Path
from typing import Any

from espalier import surface_contract
from espalier._report_io import load_report_json
from espalier.analyze import fingerprint_repo
from espalier.config import load_config
from espalier.harness_config import build_harness_config


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


def _normalize_fingerprint(data: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(data))  # json-dict-safe: ok -- json.dumps round-trip of an in-memory dict (loader guards non-dict)
    if 'repo_root' in normalized:
        normalized['repo_root'] = '<repo_root>'
    if isinstance(normalized.get('generated_zones'), list):
        normalized['generated_zones'] = _filter_zones(normalized['generated_zones'])
    if isinstance(normalized.get('risky_mutable_zones'), list):
        normalized['risky_mutable_zones'] = _filter_zones(normalized['risky_mutable_zones'])
    conventions = normalized.get('conventions')
    if isinstance(conventions, dict) and isinstance(conventions.get('guardrails'), list):
        conventions['guardrails'] = _filter_guardrails(conventions['guardrails'])
        if not conventions['guardrails']:
            conventions.pop('guardrails', None)
    return normalized


def _normalize_plan(data: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(data))  # json-dict-safe: ok -- json.dumps round-trip of an in-memory dict (loader guards non-dict)
    # `settings_profile` is a RECORD init writes (which profile rendered this
    # install's settings.json -- DEF-715), not an inference a rebuild reproduces;
    # comparing it would report every recorded install as drifted.
    normalized.pop('settings_profile', None)
    if isinstance(normalized.get('read_only_zones'), list):
        normalized['read_only_zones'] = _filter_zones(normalized['read_only_zones'])
    if isinstance(normalized.get('mutable_zones'), list):
        normalized['mutable_zones'] = _filter_zones(normalized['mutable_zones'])
    agents = normalized.get('agents')
    if isinstance(agents, list):
        for agent in agents:
            if isinstance(agent, dict) and isinstance(agent.get('generated_paths'), list):
                agent['generated_paths'] = _filter_zones(agent['generated_paths'])
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
        "ignored_local_only_keys": [
            "repo_root",
            "generated_zones",
            "risky_mutable_zones",
            "settings_profile",
        ],
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
        'ignored_local_only_keys': [
            'repo_root',
            'generated_zones',
            'risky_mutable_zones',
            'settings_profile',
            'read_only_zones',
            'mutable_zones',
            'agents[].generated_paths',
            'conventions.guardrails(ephemeral-only)',
        ],
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
