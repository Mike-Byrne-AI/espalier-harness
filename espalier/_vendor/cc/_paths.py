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

import importlib.util
import os
import sys
import time
from pathlib import Path
from types import ModuleType

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


#: The Windows wait for a refused replace, the count and backoff of
#: ``generate_ledger_regions._atomic_write``, which keeps its own loop: that
#: verb is stdlib-only and a fixture copies it alone, so it loads no sibling.
#: ``tests/test_atomic_io.py`` holds the two loops equal.
_REPLACE_ATTEMPTS = 20 if sys.platform == "win32" else 1
_REPLACE_BACKOFF_S = 0.005


def replace_retrying(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
    """``os.replace(src, dst)``, waiting out the one refusal that clears. On
    Windows a reader holding ``dst`` open fails a replace at once with
    ``PermissionError`` (WinError 5), and so does one holding ``src`` for a move
    (WinError 32); the move lands once the handle closes, so it is tried again,
    about a second in all (DEF-5021, driven 2026-10-18: a 300 ms holder cleared
    on the twelfth try, at about 340 ms). A refusal that cannot clear -- a
    directory at the target, a read-only file -- raises at once, and POSIX
    tries once. For a move whose failure would leave its caller half-done; a
    housekeeping move that already fails open and retries on its next run
    stays a single try (``tests/test_atomic_io.py`` rosters those)."""
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(src, dst)
            break
        except PermissionError:
            if (attempt + 1 >= _REPLACE_ATTEMPTS or os.path.isdir(dst)
                    or (os.path.exists(dst) and not os.access(dst, os.W_OK))):
                raise
            time.sleep(_REPLACE_BACKOFF_S * (attempt + 1))


def hooks_module(name: str) -> ModuleType | None:
    """``tools/cc/hooks/<name>.py`` loaded by path under a private alias,
    cached in ``sys.modules`` (registered before exec, as a dataclass or a
    3.14 import resolves its module by name); None when the file is not beside
    this script or cannot be loaded.

    For a top-level tool that wants one hook-side reader without a bare
    ``import`` from ``hooks/``, which a fixture copying a subset of
    ``tools/cc`` could not satisfy (``execution_plan._atomic_write_text`` says
    why it is inlined for that reason). ``mail.py`` and ``checkout_sync.py``
    carry their own loaders of this shape with their own absent-file answers
    (a refusal, a None); the next one comes here. The hook modules put their
    own directory on ``sys.path`` at import, so their sibling imports resolve.
    """
    alias = f"_paths_hooks_{name}"
    module = sys.modules.get(alias)
    if module is not None:
        return module
    path = Path(__file__).resolve().parent / "hooks" / f"{name}.py"
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(alias, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[alias] = module
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 -- fail-open: ok deliberate -- an optional reader behind a reporter; the caller stands down
        sys.modules.pop(alias, None)
        return None
    return module
