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
from collections.abc import Callable
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


#: The deploy marker the walk-up looks for: the hooks directory every Espalier
#: tree carries, Python or not. It was the ``pyproject.toml`` + ``tools/cc``
#: pair, which a non-Python adopter's tree never matched, so a subdirectory
#: launch there resolved to the subdirectory (DEF-664).
_ROOT_MARKER: tuple[str, ...] = ("tools", "cc", "hooks")

#: The Windows gate on the drive translation: a name, so a POSIX test can set it.
_ON_WINDOWS: bool = os.name == "nt"


def _translate_drive(raw: str) -> str:
    """The hooks' Git Bash drive translation, for the top-level tools that
    cannot import from ``hooks/``: ``_hook_utils._msys_drive_to_windows``,
    reached only on Windows and only for a POSIX-spelled value (``/c/...``),
    so a native value never pays for loading the hook module. A hook process's
    own ``_hook_utils`` is reused when it is loaded; otherwise ``hooks_module``
    loads it (about 15 ms). The value comes back unchanged when it cannot be
    loaded: a top-level tool's root is no deny compare, and the hooks pass
    their own translator to ``project_root_spelling``."""
    if not _ON_WINDOWS or not raw.startswith("/"):
        return raw
    hook_utils = sys.modules.get("_hook_utils") or hooks_module("_hook_utils")
    if hook_utils is None or not callable(getattr(hook_utils, "_msys_drive_to_windows", None)):
        return raw
    return hook_utils._msys_drive_to_windows(raw)


def project_root_spelling(translate: Callable[[str], str] | None = None) -> str:
    """``CLAUDE_PROJECT_DIR`` as a string ``Path`` can resolve: the one
    repo-root resolver the hooks, the top-level tools and the statusline read
    (DEF-664; before it, three spellings disagreed on a Git Bash value and on
    an unset one).

      1. The variable, when non-empty, through ``translate``: the hooks pass
         their ``_msys_drive_to_windows``; the default is ``_translate_drive``.
      2. Unset or empty: walk up from the working directory to the nearest
         directory holding ``tools/cc/hooks`` (``_ROOT_MARKER``), so a
         subdirectory launch with no variable still finds its root.
      3. ``"."`` as the last resort.

    It warns on stderr when the value is empty (Claude Code always sets it,
    so an empty one is a hand-run launch whose env was ignored), and when an
    unset value finds no marker and falls to the bare working directory,
    where a hook's state would land somewhere nothing reads it. A plain
    print, never a recorded flag, which would write state under the very root
    it warns about. Silent when the walk-up finds the root: that is every hand
    run of a ``tools/cc`` script inside a tree, where the answer is right.
    On an exit-0 hook the line reaches Claude Code's debug log only.
    """
    raw = os.environ.get("CLAUDE_PROJECT_DIR")
    if raw:
        return (translate or _translate_drive)(raw)
    if raw == "":
        # voice: debug-log Claude Code always sets the variable; an empty one is a hand-run launch
        print(
            "[WARN] espalier: CLAUDE_PROJECT_DIR is empty; resolving the root "
            "from the current working directory. Set it explicitly to remove "
            "this warning.",
            file=sys.stderr,
        )
    try:
        cur = Path.cwd().resolve()
    except OSError:  # a working directory deleted under the process
        return "."
    for candidate in (cur, *cur.parents):
        if candidate.joinpath(*_ROOT_MARKER).is_dir():
            return str(candidate)
    if raw is None:
        # voice: debug-log a hand-run launch outside any tree; Claude Code always sets the variable
        print(
            "[WARN] espalier: CLAUDE_PROJECT_DIR is unset and no directory at or "
            "above the current one holds tools/cc/hooks; falling back to the "
            "current working directory. Set it explicitly to remove this warning.",
            file=sys.stderr,
        )
    return "."


def _repo_root() -> Path:
    """The repo root for tools/cc storage operations: ``project_root_spelling``
    resolved. The single owner for the walk-up ``cognitive_blueprint._repo_root``
    and ``execution_plan._plan_path`` once duplicated. NOT the same heuristic as
    scripts/build_release_archive.py (that uses a pyproject.toml + espalier/
    marker pair -- a deliberately separate offline-build resolver).
    """
    return Path(project_root_spelling()).resolve()


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
