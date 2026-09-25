"""Shared path constants for tools/cc/ scripts.

Single source of truth for `cc/` and `cc/blueprints/` paths
referenced by hooks, the cognitive-blueprint module, the statusline,
and session-resume. Stdlib-only; no espalier imports.

The espalier-side mirror in ``espalier/surface_contract.py`` (the
``_REQUIRED_INIT_FILES`` + ``_LOCAL_ONLY_PATHS`` +
``_LOCAL_ONLY_PREFIXES`` tuples) cannot import from here due to the
zero-espalier-imports rule for ``tools/cc/``. Instead,
``tests/test_paths_parity.py`` asserts membership/equality per tuple:
two independent witnesses, contract-pinned.
"""
from __future__ import annotations

import os
from pathlib import Path

# String constants (for use in allowlists, prefix-match tests, etc.)
CC_DIR_REL: str = "cc"
BLUEPRINTS_DIR_REL: str = "cc/blueprints"
BLUEPRINT_LATEST_REL: str = "cc/blueprints/latest.json"
LIVE_SURFACE_REL: str = "cc/LIVE_SURFACE.md"
COMMANDS_INDEX_REL: str = "cc/COMMANDS.md"
PACK_MANIFEST_REL: str = "cc/PACK_MANIFEST.txt"
SURFACE_HANDOFF_REL: str = "cc/SURFACE_HANDOFF.md"

# Tuple of (str, str, str) for managed-files / surface-roots consumers
# that need a stable order. Mirrors espalier/surface_contract.py
# ``_REQUIRED_INIT_FILES`` (contract-pinned in
# tests/test_paths_parity.py).
CC_MANAGED_DOCS: tuple[str, ...] = (
    COMMANDS_INDEX_REL,
    LIVE_SURFACE_REL,
    PACK_MANIFEST_REL,
)


def _repo_root() -> Path:
    """Resolve the repo root for tools/cc storage operations.

    Priority:
      1. ``$CLAUDE_PROJECT_DIR`` — set by Claude Code (the same mechanism the
         hook scripts use).
      2. Walk up from cwd for the ``pyproject.toml`` + ``tools/cc/`` marker
         pair. This parent-ascend fallback is why callers use this rather than
         ``_hook_utils.resolve_project_root`` (which is env-only): a subdir
         launch with no ``CLAUDE_PROJECT_DIR`` still resolves correctly.
      3. ``Path.cwd()`` as last resort.

    Single owner for the byte-identical walk-up cognitive_blueprint._repo_root
    and execution_plan._plan_path previously duplicated. NOT the same heuristic
    as scripts/build_release_archive.py (that uses a pyproject.toml + espalier/
    marker pair — a deliberately separate offline-build resolver).
    """
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    cur = Path.cwd().resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "tools" / "cc").is_dir():
            return candidate
    return cur
