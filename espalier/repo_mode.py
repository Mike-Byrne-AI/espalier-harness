"""Shared repo-mode detection.

Promoted from espalier/doctor.py so multiple commands (doctor,
self-host, release_check) can detect the repo's install state
consistently.

The four modes describe what the repo looks like on disk:

- **uninitialized**: no committed harness surface AND no runtime
  markers. A fresh repo. ``espalier init`` is the next step.
- **source-checkout**: committed harness surface present (a git
  clone of the Espalier-Harness repo, or an unpacked source
  archive) but no runtime markers. CI and release-archive smoke
  tests should pass without demanding init-generated artifacts.
- **initialized_self_host**: runtime markers present in the
  Espalier-Harness repo itself.
- **initialized_consumer_repo**: runtime markers present in a user
  repo that has run ``espalier init``.

CLI-facing mode names use hyphens (``source-checkout``); internal
constants use underscores. Translation happens at the parser
boundary via :func:`resolve_mode`.

One report-only value sits beside the four: ``DOCTOR_MODE_UNREADABLE``,
which ``doctor`` writes when ``.claude`` cannot be searched or listed and
detection therefore cannot run. It is never detected or resolved.
"""
from __future__ import annotations

import os
from pathlib import Path

from espalier import surface_contract
from espalier._safe_walk import has_git_entry


# Repo mode classifier. The four modes have different validation
# semantics: an uninitialized repo should not fail loudly just because
# runtime files haven't been generated, but an initialized repo must
# still gate-check those files.
REPO_MODE_UNINITIALIZED = "uninitialized"
REPO_MODE_SOURCE_CHECKOUT = "source_checkout"
REPO_MODE_INITIALIZED_SELF_HOST = "initialized_self_host"
REPO_MODE_INITIALIZED_CONSUMER = "initialized_consumer_repo"

# A fifth value, REPORT-ONLY: ``doctor`` writes it when ``.claude`` cannot be
# searched or listed (DEF-763), because detection reads ``.claude`` and so
# cannot run. ``detect_repo_mode`` never returns it and ``resolve_mode``
# never accepts it; it lives here so the mode vocabulary has one home.
DOCTOR_MODE_UNREADABLE = "unreadable"


# Markers that, when present, indicate ``espalier init`` has been run. Each
# must be a per-install artifact that NO project commits (gitignored), bound to
# a specific file — never a directory. ``.claude/settings.json`` and
# ``reports/repo_fingerprint.json`` are written by init and committed by no
# project. The bare ``reports/`` dir is too weak — adopters keep their own
# ``reports/`` — so it binds to ``reports/repo_fingerprint.json``. The bare
# ``.espalier`` DIRECTORY is the same trap: ``.espalier/freshness.json`` is
# git-tracked, so the directory exists in every fresh ``git clone`` of the
# self-host repo (and any adopter who commits ``.espalier/``), which would flip
# a source-checkout to ``initialized_*`` and make ``doctor``/``self-host-check``
# ``mode=auto`` false-fail. Bind instead to ``.espalier/integrity.json`` —
# gitignored (.gitignore), written by ``integrity refresh`` on each install,
# committed by no project.
_RUNTIME_MARKERS: tuple[str, ...] = (
    ".espalier/integrity.json",
    "reports/repo_fingerprint.json",
    ".claude/settings.json",
)


def runtime_marker_paths() -> tuple[str, ...]:
    """The repo-relative files whose presence makes a tree read as
    initialized (``detect_repo_mode``). Public so a consumer that names the
    markers an uninstall leaves behind (``doctor``, DEF-770) reads the same
    tuple the detector does rather than a copy."""
    return _RUNTIME_MARKERS


def detect_repo_mode(repo_root: Path) -> str:
    """Classify ``repo_root`` into one of the four modes.

    - **uninitialized**: no committed surface AND no runtime markers.
      A fresh, never-touched repo. ``espalier init`` is the next step.
    - **source_checkout**: committed surface present (cc/COMMANDS.md,
      etc.) but no runtime markers — a fresh ``git clone`` of a repo
      that ships its harness surface as source. CI should accept this
      without demanding generated runtime artifacts.
    - **initialized_self_host**: runtime markers present in the
      Espalier-Harness repo itself.
    - **initialized_consumer_repo**: runtime markers present in a user
      repo that has run ``espalier init``.
    """
    required = list(surface_contract.get_required_init_files())
    # `os.path.exists`, never `Path.exists()`: `.claude/settings.json` is a
    # marker, and pathlib answered a `.claude` that denies traversal per
    # interpreter (DEF-763). Uniform yes/no is the right answer here -- the
    # command layer refuses such a tree before mode detection is asked.
    has_runtime = any(
        os.path.exists(repo_root / marker) for marker in _RUNTIME_MARKERS
    )
    has_committed_surface = any(
        os.path.exists(repo_root / rel) for rel in required
    )

    if not has_runtime and not has_committed_surface:
        return REPO_MODE_UNINITIALIZED
    if not has_runtime and has_committed_surface:
        return REPO_MODE_SOURCE_CHECKOUT
    if surface_contract.is_self_host_repo(repo_root):
        return REPO_MODE_INITIALIZED_SELF_HOST
    return REPO_MODE_INITIALIZED_CONSUMER


def resolve_mode(cli_mode: str | None, repo_root: Path) -> str:
    """Translate a CLI ``--mode`` argument to a concrete repo mode.

    - ``cli_mode="auto"`` (or None) runs :func:`detect_repo_mode` against
      the repo root.
    - ``cli_mode="source-checkout"`` returns ``REPO_MODE_SOURCE_CHECKOUT``
      regardless of disk state.
    - ``cli_mode="initialized"`` returns the appropriate initialized mode
      based on whether ``repo_root`` is the self-host repo
      (``REPO_MODE_INITIALIZED_SELF_HOST``) or a consumer repo
      (``REPO_MODE_INITIALIZED_CONSUMER``). Mirrors ``cmd_doctor`` in
      ``cli.py`` which uses the same is_self_host_repo dispatch.

    Returns one of the ``REPO_MODE_*`` constants.
    """
    if cli_mode == "auto" or cli_mode is None:
        return detect_repo_mode(repo_root)
    if cli_mode == "source-checkout":
        return REPO_MODE_SOURCE_CHECKOUT
    if cli_mode == "initialized":
        if surface_contract.is_self_host_repo(repo_root):
            return REPO_MODE_INITIALIZED_SELF_HOST
        return REPO_MODE_INITIALIZED_CONSUMER
    raise ValueError(
        f"Unknown CLI mode {cli_mode!r}. "
        f"Valid: ['auto', 'initialized', 'source-checkout']"
    )


# ---------------------------------------------------------------------------
# filesystem-walk fallback for non-git contexts
# ---------------------------------------------------------------------------

# Filesystem-walk denylist: directories the walk should not descend into.
# Intentionally smaller than any transient-pattern list — we want to skip
# cost (don't walk into __pycache__) but still walk into legitimate
# directories that happen to be ignored by git (e.g., `dist/` when the
# user builds locally — those entries should still get checked if present).
_WALK_SKIP_DIRS: frozenset[str] = frozenset({
    ".git",
    ".espalier",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    ".idea",
    ".vscode",
    "node_modules",
})


def _walk_skip(name: str) -> bool:
    """Return True if a directory name should be pruned from the walk.

    Matches both literal entries in ``_WALK_SKIP_DIRS`` (.git, etc.) and
    pattern-suffix entries — currently any ``*.egg-info`` directory,
    which ``pip install -e`` writes into the source tree as generated
    metadata. Without pruning ``.egg-info`` directories, downstream
    walkers (e.g., the no-tracked-release-noise check) flag the
    generated files as forbidden surface even though they're transient.
    """
    return name in _WALK_SKIP_DIRS or name.endswith(".egg-info")


def _walk_with_pruning(root: Path, skip_dirs: frozenset[str]):
    """os.walk variant that prunes named directories in-place.

    Yields (dirpath, dirnames, filenames) like os.walk, but modifies
    `dirnames` to exclude any name matching the skip rules (literal
    ``skip_dirs`` entries or the ``*.egg-info`` suffix pattern; see
    ``_walk_skip``).
    """
    import os
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune named cache/build dirs AND any embedded git repo (a nested
        # repo is a foreign project, not part of this repo's file list --
        # dangling .git included, per _safe_walk.has_git_entry).
        dirnames[:] = [
            d for d in dirnames
            if not _walk_skip(d) and not has_git_entry(Path(dirpath) / d)
        ]
        yield dirpath, dirnames, filenames


def list_repo_files_via_filesystem(repo_root: Path) -> list[str]:
    """Walk `repo_root` and return repo-relative POSIX paths of all files.

    Equivalent in intent to ``git ls-files`` but does not require a git
    checkout. Used by tracked-noise checks when ``git`` is unavailable or
    the directory is not a git checkout (source archive, sdist).

    Skips well-known cache and build directories (.git, __pycache__,
    .venv, etc.) so the walk completes in reasonable time. The returned
    paths use forward slashes regardless of platform.
    """
    paths: list[str] = []
    repo_root = repo_root.resolve()

    for dirpath, _dirnames, filenames in _walk_with_pruning(
        repo_root, _WALK_SKIP_DIRS
    ):
        for name in filenames:
            full = Path(dirpath) / name
            try:
                rel = full.relative_to(repo_root)
            except ValueError:
                continue
            paths.append(str(rel).replace("\\", "/"))

    paths.sort()
    return paths


def _walked_files_matching_git_tracked(repo_root: Path) -> list[str]:
    """Filesystem-walk file list, pruned to approximate ``git ls-files``.

    ``git ls-files`` never lists gitignored runtime state; a raw filesystem
    walk does. On a non-git tree (a source release archive, an sdist) an
    extract + ``pip install`` + test cycle creates release-excluded content
    in place — ``.espalier-state/``, ``*.egg-info/``, ``.pytest_cache/``,
    ``reports/`` — that the archive build itself never ships. Without this
    prune the walk mis-reports that runtime state as a tracked file, so the
    release-noise / provenance / codename callers fail on a fresh extract
    where the git branch (tracked-only) never would. Dropping
    ``is_release_excluded`` paths keeps the git and filesystem branches
    honest: both exclude non-shipped state, both keep tracked shipped files.
    """
    return [
        p for p in list_repo_files_via_filesystem(repo_root)
        if not surface_contract.is_release_excluded(p)
    ]


def list_tracked_or_walked_files(
    repo_root: Path,
    *,
    require_git: bool = False,
) -> tuple[list[str], str]:
    """Return (file_list, source) — file_list is repo-relative POSIX paths,
    source is one of "git" or "filesystem".

    Tries ``git ls-files`` first; falls back to a filesystem walk if git
    is unavailable, times out, or the directory is not a checkout. If
    ``require_git=True``, raises FileNotFoundError instead of falling
    back — useful for callers that need provenance certainty.

    Detects the "extracted under a parent git repo" case explicitly:
    when ``repo_root`` has no local ``.git/``, skip the git probe and
    walk the filesystem directly. Without this check, ``git ls-files``
    invoked from inside a gitignored extracted-archive subtree returns
    exit 0 + empty stdout (it walks up to the parent's ``.git/`` and
    reports zero tracked files for the cwd subtree), which misleads
    callers into thinking the repo legitimately has no files.
    """
    import subprocess

    if not (repo_root / ".git").is_dir():
        if require_git:
            raise FileNotFoundError(
                f"{repo_root} has no .git/ directory and require_git=True"
            )
        return (_walked_files_matching_git_tracked(repo_root), "filesystem")

    try:
        result = subprocess.run(
            # core.quotePath=false: non-ASCII paths come back as real UTF-8
            # (matching the filesystem-walk fallback in
            # list_repo_files_via_filesystem), not git's default octal-escaped,
            # double-quoted form — so the git and filesystem branches agree.
            ["git", "-c", "core.quotePath=false", "ls-files"],
            cwd=str(repo_root),
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            return (
                [line for line in result.stdout.splitlines() if line],
                "git",
            )
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        if require_git:
            raise

    if require_git:
        raise FileNotFoundError(
            "git ls-files unavailable or this is not a git checkout"
        )

    return _walked_files_matching_git_tracked(repo_root), "filesystem"
