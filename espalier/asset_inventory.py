"""Inventory of bundled package assets — counts and relative paths.

Used by tests, docs, and the audit/doctor surface to assert wheel-installed
parity. Stdlib-only on purpose: importable in environments without optional
dev dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from espalier.assets import (
    AssetNotFound,
    github_workflow_asset,
    iter_claude_asset_files,
)

__all__ = ["AssetGroup", "PackagedSurface", "get_packaged_surface", "packaged_agent_names"]


_BUNDLED_WORKFLOWS: tuple[str, ...] = ("harness-guard.yml",)

_HOOK_DIR_PREFIX = "tools/cc/hooks/"


def _strip_hook_prefix(paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        p[len(_HOOK_DIR_PREFIX):] if p.startswith(_HOOK_DIR_PREFIX) else p
        for p in paths
    )


def _hook_entry_basenames() -> tuple[str, ...]:
    """Bare hook-entry script names, derived from the canonical SoT
    (``surface_contract.get_canonical_hook_scripts``) — never a third
    hand-maintained copy. ``surface_contract`` does not import
    ``asset_inventory``, so a module-level import would be safe; this stays a
    function so both hook getters share one cycle-free shape."""
    from espalier import surface_contract

    return surface_contract.get_canonical_hook_scripts()


def _hook_helper_basenames() -> tuple[str, ...]:
    """Bare hook-helper module names, derived from the ``managed_inventory``
    SoT. The import is LAZY because ``managed_inventory``
    imports ``asset_inventory.get_packaged_surface`` at module load — a
    top-level import here would be a circular import."""
    from espalier import managed_inventory

    return _strip_hook_prefix(managed_inventory.get_hook_helper_files())


@dataclass(frozen=True, slots=True)
class AssetGroup:
    """A named group of packaged asset paths."""

    name: str
    paths: tuple[str, ...]

    @property
    def count(self) -> int:
        return len(self.paths)


@dataclass(frozen=True, slots=True)
class PackagedSurface:
    """Inventory of every asset shipped in the wheel."""

    commands: AssetGroup
    skills: AssetGroup
    agents: AssetGroup
    workflows: AssetGroup
    hook_entries: AssetGroup
    hook_helpers: AssetGroup

    def as_dict(self) -> dict[str, dict[str, object]]:
        """Plain-dict serialization for tests, docs, and JSON output."""
        return {
            g.name: {"count": g.count, "paths": list(g.paths)}
            for g in (
                self.commands,
                self.skills,
                self.agents,
                self.workflows,
                self.hook_entries,
                self.hook_helpers,
            )
        }


def _claude_paths(subdir: str) -> tuple[str, ...]:
    try:
        files = iter_claude_asset_files(subdir)
    except AssetNotFound:
        # assets moved to examples/dogfooding/.claude/; nothing to deploy.
        return ()

    rels: list[str] = []
    for f in files:
        # f.name is just the leaf; build a stable relative path from the subdir
        # by walking from the subdir root.
        parts: list[str] = [f.name]
        parent = f
        while True:
            parent = parent.parent  # type: ignore[attr-defined]
            if parent.name == subdir:
                break
            parts.append(parent.name)
        parts.reverse()
        rels.append("/".join(parts))
    return tuple(sorted(rels))


def _workflow_paths(names: Sequence[str]) -> tuple[str, ...]:
    out: list[str] = []
    for name in names:
        try:
            github_workflow_asset(name)
        except AssetNotFound:
            continue
        out.append(name)
    return tuple(sorted(out))


def get_packaged_surface() -> PackagedSurface:
    """Return a snapshot of the wheel-installed harness surface."""
    return PackagedSurface(
        commands=AssetGroup("commands", _claude_paths("commands")),
        skills=AssetGroup("skills", _claude_paths("skills")),
        agents=AssetGroup("agents", _claude_paths("agents")),
        workflows=AssetGroup("workflows", _workflow_paths(_BUNDLED_WORKFLOWS)),
        hook_entries=AssetGroup("hook_entries", _hook_entry_basenames()),
        hook_helpers=AssetGroup("hook_helpers", _hook_helper_basenames()),
    )


def packaged_agent_names() -> frozenset[str]:
    """The agent names this engine ships a body for (``<name>.md`` under the
    packaged ``agents/``). A plan may RECOMMEND more (``harness_config.
    OPTIONAL_AGENTS``): those are claims, not deploys, and every consumer that
    tells the two apart reads this one set -- doctor's ownership view
    (DEF-756), the surface gate's LIVE_SURFACE check and init's summary
    (DEF-766).
    """
    names = set()
    for rel in get_packaged_surface().agents.paths:
        leaf = rel.replace("\\", "/").rsplit("/", 1)[-1]
        if leaf.endswith(".md"):   # an agent body is a .md leaf; anything else is not one
            names.add(leaf[:-3])
    return frozenset(names)
