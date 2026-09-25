"""Shared state-cache reader for session_start + statusline.

Stdlib-only mirror of ``espalier.freshness.read_state_cache_safe`` /
``is_state_cache_stale``. The two copies coexist because
``tools/cc/`` is required to be zero-espalier-import per the
architecture rule — scripts are copied verbatim and must run
standalone. ``tests/test_freshness_cache_reader_parity.py`` asserts
both readers agree on the same fixture manifest.

Mirrors the fd-level discipline (``O_NOFOLLOW`` + size cap +
``fstat`` regular-file check) so the freshness manifest read
inherits the symlink + size + non-regular-file defenses from
BC-027.
"""
from __future__ import annotations

import json
import os
import stat as _stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_FRESHNESS_MANIFEST_BYTES = 65_536  # 64 KB cap.
STATE_CACHE_MAX_AGE_HOURS = 24
_ANCESTOR_WINDOW_COMMITS = 50
_MANIFEST_REL_PATH = ".espalier/freshness.json"
# The derived state_cache lives in its OWN gitignored per-install file, NOT a
# block inside the committed manifest, so a ``freshness check`` never dirties the
# tracked tree. The manifest keeps only the committed fragments SoT.
_STATE_CACHE_REL_PATH = ".espalier/.freshness_state_cache.json"

# Windows CPython omits ``O_NOFOLLOW`` and ``O_NONBLOCK`` (POSIX-only);
# ``getattr(..., 0)`` degrades to a no-op OR so the constant resolves on
# every platform while preserving the cache-poisoning defenses on POSIX.
# Defined locally rather than imported from ``espalier.freshness`` per
# the tools/cc/ zero-espalier-import rule.
_CACHE_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def _read_manifest_json_safe(
    repo_root: Path, rel_path: str = _MANIFEST_REL_PATH
) -> dict | None:
    """Fd-safe read of a freshness JSON file, parsed to a dict (or None).

    Owns the fd-discipline invariant (O_NOFOLLOW open, regular-file + size
    guard, guaranteed os.close) in one place. Returns None on ANY failure
    (open / stat / oversize / decode / non-dict); callers map None to their
    own fallback and pull their own key. ``rel_path`` selects the file: the
    committed manifest (fragments) by default, or the gitignored per-install
    state_cache file for ``_read_state_cache_safe``.
    """
    path = repo_root / rel_path
    try:
        fd = os.open(str(path), _CACHE_OPEN_FLAGS)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not _stat.S_ISREG(st.st_mode):
            return None
        if st.st_size > MAX_FRESHNESS_MANIFEST_BYTES:
            return None
        raw = os.read(fd, MAX_FRESHNESS_MANIFEST_BYTES + 1)
        if len(raw) > MAX_FRESHNESS_MANIFEST_BYTES:
            return None
    except OSError:
        return None
    finally:
        os.close(fd)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _read_state_cache_safe(repo_root: Path) -> dict | None:
    data = _read_manifest_json_safe(repo_root, _STATE_CACHE_REL_PATH)
    if data is None:
        return None
    cache = data  # the whole per-install cache-file body IS the state_cache
    # Consumers (statusline._freshness_summary, session_start) dereference
    # cache["counts"].get(...). A present-but-non-dict 'counts' (hand-edit /
    # future schema) would raise AttributeError there; coerce it to {} so the
    # banner degrades to "no counts" instead of blanking entirely.
    if "counts" in cache and not isinstance(cache["counts"], dict):
        cache = {**cache, "counts": {}}
    return cache


def _is_state_cache_stale(
    cache: dict,
    *,
    repo_root: Path | None = None,
    max_age_hours: int = STATE_CACHE_MAX_AGE_HOURS,
) -> bool:
    computed_at_str = cache.get("computed_at")
    if not isinstance(computed_at_str, str):
        return True
    try:
        computed_at = datetime.fromisoformat(
            computed_at_str.replace("Z", "+00:00")
        )
    except ValueError:
        return True
    if computed_at.tzinfo is None:
        return True  # naive timestamp: treat as stale rather than crash
    now = datetime.now(timezone.utc)
    if computed_at > now + timedelta(minutes=1):
        return True  # future-dated; clock-skew defense
    if (now - computed_at) > timedelta(hours=max_age_hours):
        return True
    if repo_root is None:
        return True
    cache_sha = cache.get("computed_at_sha")
    if not cache_sha:
        return True
    head = _git_head_sha_quiet(repo_root)
    if not head:
        return True
    if head == cache_sha:
        return False
    if _git_is_ancestor_within_n(
        cache_sha, "HEAD", n=_ANCESTOR_WINDOW_COMMITS, cwd=repo_root,
    ):
        # HEAD advanced but cache_sha is a recent ancestor — the cached scan is
        # still trusted UNLESS a commit since cache_sha touched a pinned
        # fragment's bound source (W17): a bound-change must read stale, else
        # consumers (audit-accuracy, statusline, session_start) serve the
        # pre-change critical/stale verdicts.
        if _pinned_bound_changed_since(repo_root, cache_sha):
            return True
        return False
    return True


def _git_head_sha_quiet(cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):  # strict decode: a structured answer (DEF-821)
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    # accept 40-char SHA-1 and 64-char SHA-256 HEADs; hex-validate either way
    return (
        sha
        if len(sha) in (40, 64) and all(c in "0123456789abcdef" for c in sha)
        else None
    )


def _git_is_ancestor_within_n(
    candidate_sha: str, ref: str, *, n: int, cwd: Path,
) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-list", f"-n{n}", ref],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):  # strict decode: a structured answer (DEF-821)
        return False
    if result.returncode != 0:
        return False
    return candidate_sha in result.stdout.split()


def _read_fragments_safe(repo_root: Path) -> dict:
    """Fd-safe read of the manifest's ``fragments`` block (mirrors
    ``_read_state_cache_safe``'s symlink / size / regular-file discipline)."""
    data = _read_manifest_json_safe(repo_root)
    if data is None:
        return {}
    frags = data.get("fragments")
    return frags if isinstance(frags, dict) else {}


def _pinned_bound_paths(repo_root: Path) -> list:
    """Repo-relative paths every pinned fragment's bound is derived from."""
    paths: set = set()
    for frag in _read_fragments_safe(repo_root).values():
        if not isinstance(frag, dict):
            continue
        bound = frag.get("bound")
        if not isinstance(bound, list):
            continue
        for entry in bound:
            if isinstance(entry, str) and entry:
                # A bound may be `path::symbol`. git treats `path::symbol` as a
                # pathspec matching NO file, so the W17 cache-invalidation guard
                # would report "not stale" for every commit touching a
                # ::symbol-bound source. Strip to the bare path; keep the
                # git-pathspec dash guard.
                path = entry.split("::", 1)[0]
                if path and not path.startswith("-"):
                    paths.add(path)
    return sorted(paths)


def _pinned_marker_paths(repo_root: Path) -> list:
    """Repo-relative marker-doc paths of every pinned fragment (the doc the
    fragment's marker lives in, persisted as ``marker_path`` at pin time).

    The W17 guard watches these alongside the bound sources: a claim doc can
    drift (its marker text edited, or the doc deleted) without any bound SOURCE
    changing, and a bound-only watch would silently report the cached scan
    'not stale'. Fragments pinned before ``marker_path`` was captured carry
    none and are simply skipped (re-pinning captures it)."""
    paths: set = set()
    for frag in _read_fragments_safe(repo_root).values():
        if not isinstance(frag, dict):
            continue
        marker = frag.get("marker_path")
        if isinstance(marker, str) and marker and not marker.startswith("-"):
            paths.add(marker)
    return sorted(paths)


def _pinned_bound_changed_since(repo_root: Path, cache_sha: str) -> bool:
    """True iff a commit since ``cache_sha`` touched any pinned fragment's
    bound source OR marker doc — the cached scan no longer reflects HEAD (W17)."""
    paths = sorted(
        set(_pinned_bound_paths(repo_root)) | set(_pinned_marker_paths(repo_root))
    )
    if not paths:
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--quiet",
             cache_sha, "HEAD", "--", *paths],
            capture_output=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True  # cannot compare -> conservatively stale
    return result.returncode != 0
