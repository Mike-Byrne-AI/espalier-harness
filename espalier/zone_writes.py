"""A harness writer records what it wrote into the protected zones (accounting path 4).

``post_write_check`` compares the protected zones after every shell call and
reports a change that no legitimate path accounts for. ``espalier upgrade``,
``init``, ``integrity refresh``, ``freshness-pin`` and every other command that
rewrites a protected file are such a path, and so is a sync script whose mirror
transforms its source. Rather than write into each session's baseline (a second
writer to a file each session owns, Core Rule 14), a writer brackets its own
run: a stat pass before, a pass after, and the paths that moved during the run
are recorded with their new content's digest in one file per writer under
``.espalier-state/zone_writes/``. The hook reads the records: a changed path
whose content equals what a writer recorded since the session's previous check
is accounted for. A change made before the writer started, in the same shell
call, is not in the record, so it still reports.

The CLI brackets every command that rewrites protected files (its parser sets
``zone_writer=True``) in ``espalier.cli.main``, named ``espalier <command>``; a
read-only command is never bracketed, so its run cannot file a parallel slip
as its own. A sync script brackets itself. A running marker beside the record
holds a watching session's check back until the run ends. Nothing is recorded
where no session is watching (no session baseline under
``.espalier-state/sessions/``), so a sessionless tree gains no state. A change
another process makes to a protected file during a writer's run is recorded
as the writer's: a declared limit, the window being the run.

Twin of ``tools/cc/hooks/_zone_watch`` (``WRITE_RECORD_DIR``, ``record_name``,
the digest and the watched set), pinned by ``tests/test_zone_writes.py``.
"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Iterator
from pathlib import Path

from espalier._atomic_io import atomic_write_text, lock_file, unlock_file
from espalier._text import os_error_text
from espalier.surface_contract import get_protected_mutation_paths, get_protected_mutation_prefixes

STATE_DIR = ".espalier-state"
RECORD_DIR = "zone_writes"
SESSIONS_DIR = "sessions"
#: The suffix of a session's zone baseline (``_hook_utils.ZONE_BASELINE_SUFFIX``).
BASELINE_SUFFIX = ".zones"
#: Beside a writer's record while its run has not ended; the hook holds its
#: baseline while one is younger than RUNNING_MAX_S (a killed run's marker
#: stops holding it then). ``_zone_watch.RUNNING_SUFFIX`` / ``WRITER_RUNNING_MAX_S``.
RUNNING_SUFFIX = ".running"
RUNNING_MAX_S = 600
#: The protected prefixes the hook leaves to write_guard (``_zone_watch.UNWATCHED_PREFIXES``).
UNWATCHED_PREFIXES = ("cc/",)
#: The walk's prunes and skips, and the size past which a file is identified
#: by its stat: ``_zone_watch.CACHE_DIR_NAMES`` / ``CLUTTER_NAMES`` /
#: ``BIG_FILE_BYTES``, beside the stack table's dependency directories and the
#: adopter's ``dependency_dirs``.
# stack-table: ok purpose-scoped -- tool caches, virtualenvs and version-control dirs a zone walk skips;
# none is a stack's dependency directory, which _watched joins from the table
CACHE_DIR_NAMES = frozenset({
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".nox",
    ".venv", "venv", ".git", ".hg", ".svn",
})
CLUTTER_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})
BIG_FILE_BYTES = 4 * 1024 * 1024
# Deliberately no "racy" window here, unlike the hook's snapshot: a file whose
# stat did not move during the run is not recorded, even one written moments
# before it. A window would record a slip made just before the writer in the
# same shell call as the writer's own, and hide it. The cost is the other way
# and loud: a writer's same-size rewrite inside one timestamp tick of a write
# just before its run is not recorded, and the next shell call reports it.


def record_name(writer: str) -> str:
    """The one file a writer's records live in."""
    return re.sub(r"[^A-Za-z0-9]+", "-", writer).strip("-") + ".json"


@functools.lru_cache(maxsize=1)
def _canonical_fn():
    """The hook layer's canon, loaded once per process: an init or upgrade
    run digests hundreds of files, and each load re-executes the module."""
    from espalier._integrity_bridge import load_integrity_module
    return load_integrity_module().canonical_text_bytes


def _canonical(raw: bytes) -> bytes:
    return _canonical_fn()(raw)


def content_digest(path: Path) -> str | None:
    """The hook's identity for a file: sha256 of the canonical text bytes, or
    ``stat:<size>:<mtime>`` at BIG_FILE_BYTES or more; None when unreadable."""
    try:
        st = path.stat()
        if st.st_size >= BIG_FILE_BYTES:
            return f"stat:{st.st_size}:{st.st_mtime_ns}"
        raw = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(_canonical(raw)).hexdigest()


def is_clutter(name: str) -> bool:
    """``_zone_watch.is_clutter``: an editor's, the OS's or an atomic write's file."""
    return (name in CLUTTER_NAMES or name.endswith((".swp", ".swo", "~"))
            or name.startswith(".#") or (name.startswith(".") and name.endswith(".tmp")))


def _watched(root: Path) -> tuple[list[str], list[str], frozenset[str]]:
    """``(prefixes, files, pruned)``: the protected set the hook watches, the
    adopter's ``protected_paths`` included (a writer that deploys into one,
    a seeded doc under a protected ``docs/``, must record it), and the
    directory names the walk prunes."""
    from espalier import _stack_table
    from espalier._safe_walk import declared_dependency_dirs
    from espalier.config import load_config

    prefixes = [p for p in get_protected_mutation_prefixes() if p not in UNWATCHED_PREFIXES]
    try:
        for entry in load_config(root).protected_paths:
            prefix = entry.strip().replace("\\", "/").rstrip("/") + "/"
            if prefix != "/" and not prefix.startswith(("/", "../")) and prefix not in prefixes:
                prefixes.append(prefix)
    except (OSError, ValueError):
        pass  # an unreadable config adds no prefix; a write there reports rather than hides
    files = [p for p in get_protected_mutation_paths() if not p.startswith(tuple(prefixes))]
    pruned = CACHE_DIR_NAMES | _stack_table.dependency_dirs() | declared_dependency_dirs(root)
    return prefixes, files, pruned


def _stats(root: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}

    def take(rel: str, full: str) -> None:
        try:
            st = os.stat(full)
        except OSError:
            return
        if os.path.isfile(full):
            out[rel] = (st.st_size, st.st_mtime_ns)

    prefixes, files, pruned = _watched(root)
    for prefix in prefixes:
        # nested-repo-ok the recorder must walk exactly the hook's set (_zone_watch.snapshot), which enters a nested checkout under a protected path
        for dirpath, dirnames, filenames in os.walk(root / prefix):
            dirnames[:] = [d for d in dirnames if d not in pruned]
            base = Path(dirpath).relative_to(root).as_posix()
            for name in filenames:
                if not is_clutter(name):
                    take(f"{base}/{name}", os.path.join(dirpath, name))
    for rel in files:
        take(rel, str(root / rel))
    return out


def session_watching(root: Path) -> bool:
    """Whether any session in this tree keeps a zone baseline to compare with."""
    try:
        return any(p.name.endswith(BASELINE_SUFFIX)
                   for p in (root / STATE_DIR / SESSIONS_DIR).iterdir())
    except OSError:
        return False


def _record(root: Path, writer: str, before: dict[str, tuple[int, int]]) -> None:
    after = _stats(root)
    moved: dict[str, str | None] = {}
    for rel, stat in after.items():
        if before.get(rel) != stat:
            moved[rel] = content_digest(root / rel)
    for rel in before:
        if rel not in after:
            moved[rel] = None
    if not moved:
        return
    now = time.time_ns()
    directory = root / STATE_DIR / RECORD_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / record_name(writer)
    with _record_write_lock(path):
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = None
        files = old.get("files") if isinstance(old, dict) and isinstance(old.get("files"), dict) else {}
        files = {rel: entry for rel, entry in files.items() if isinstance(rel, str)}
        files.update({rel: [digest, now] for rel, digest in moved.items()})
        atomic_write_text(path, json.dumps({"writer": writer, "files": files},
                                           sort_keys=True, separators=(",", ":")) + "\n")


@contextlib.contextmanager
def _record_write_lock(path: Path) -> Iterator[None]:
    """Serialise one writer's read-merge-write of its record across processes.
    Where the lock cannot be taken the merge runs unlocked: a concurrent run of
    the same writer may then lose an entry, which reports rather than hides."""
    with open(path.with_name(path.name + ".lock"), "a+", encoding="utf-8") as fh:
        try:
            lock_file(fh)
        except OSError:
            yield
            return
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                unlock_file(fh)


@contextlib.contextmanager
def recorded(repo_root: object, writer: str) -> Iterator[None]:
    """Bracket a writer's run: record the protected paths it changed. Never
    raises from the recording; a record that cannot be written is said on
    stderr, and the next shell call reports what it would have accounted for."""
    try:
        root = Path(str(repo_root)).resolve()
        watching = session_watching(root)
    except (OSError, ValueError):
        watching = False
    if not watching:
        yield
        return
    running = root / STATE_DIR / RECORD_DIR / (record_name(writer) + RUNNING_SUFFIX)
    try:
        # Written first: a check that runs while this writer is part way
        # through holds its baseline instead of reporting half a run.
        running.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(running, json.dumps({"writer": writer, "pid": os.getpid(),
                                               "started_ns": time.time_ns()}) + "\n")
    except OSError:
        pass  # no marker: a parallel check may report part of this run, which is loud, not hidden
    try:
        before = _stats(root)
        try:
            yield
        finally:
            try:
                _record(root, writer, before)
            except Exception as exc:  # noqa: BLE001 -- the record is advisory; the command's own outcome stands
                print(f"espalier: could not record what {writer} wrote into the protected files "
                      f"({type(exc).__name__}: {os_error_text(exc)}); a session's next shell call "
                      "will report those changes", file=sys.stderr)
    finally:
        with contextlib.suppress(OSError):
            running.unlink(missing_ok=True)
