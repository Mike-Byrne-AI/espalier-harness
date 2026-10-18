"""The protected zones compared after every shell call.

A shell call can change a protected file without naming it -- a formatter run
over the whole tree, a script, a copy -- so write_guard's path check, which
reads the command's words, never sees it. This module keeps one snapshot of
the watched files per session (size, modification time and a hash of the
line-ending-independent content) and answers which of them changed since the
session's previous check, which of those changes a legitimate path accounts
for, and whether each unaccounted one landed during the shell call or before
it began.

The watched set is derived, never copied: the operative protected prefixes
(``_hook_utils.harness_protected_prefixes``) less ``cc/``, the exact protected
files (``_protected_zones.PROTECTED_FILES``) less the two settings files, and
the adopter's ``protected_paths``. ``cc/`` is left out because everything under
it that no existing exclusion covers is harness state its own tools rewrite
through shell calls (measured 2026-10-09: six of six), and write_guard still
guards it by path. The settings files are left to config_guard, which sees
every settings change on ConfigChange, Claude Code's own permission writes
included; this check would report a "don't ask again" click as a slip.
Dependency, cache and tool directories are pruned during the walk, and editor
and OS clutter is skipped by name.

Shared helper: it returns data and speaks to no one. post_write_check renders
what it finds (a shared helper never collects advisories; tests/test_failopen_voice.py).
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat
import sys
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

# The loader contract: this module is imported bare and as tools.cc.hooks.*,
# so it puts its own directory (and tools/cc/ for _json_safe) on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _hook_utils  # noqa: E402
import _integrity  # noqa: E402
import _protected_zones  # noqa: E402
from _json_safe import load_json_dict_safe  # noqa: E402

#: The protected prefixes this check leaves to write_guard alone (see the
#: module docstring for the measurement).
UNWATCHED_PREFIXES = ("cc/",)
#: The protected files this check leaves to config_guard (module docstring).
UNWATCHED_FILES = frozenset({".claude/settings.json", ".claude/settings.local.json"})
#: Cache, tool and version-control directories pruned wherever they appear,
#: beside the stack table's dependency directories and the adopter's declared
#: ``dependency_dirs``. Twin of ``espalier.zone_writes.CACHE_DIR_NAMES``.
# stack-table: ok purpose-scoped -- tool caches, virtualenvs and version-control dirs a zone walk skips;
# none is a stack's dependency directory, which pruned_dir_names joins from the table
CACHE_DIR_NAMES = frozenset({
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".nox",
    ".venv", "venv", ".git", ".hg", ".svn",
})
#: File names an editor or the OS writes beside real files. Twin of
#: ``espalier.zone_writes.CLUTTER_NAMES``.
CLUTTER_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})
#: A file this large is identified by its size and modification time, never
#: read: a model or data file in a protected path must not cost a hook its
#: timeout. Twin of ``espalier.zone_writes.BIG_FILE_BYTES``.
BIG_FILE_BYTES = 4 * 1024 * 1024
#: A walk that passes either budget turns the check off for the session, and
#: says so: a hook that times out reports nothing and costs every later call.
WALK_FILE_BUDGET = 20_000
WALK_TIME_BUDGET_S = 3.0
#: The baseline's schema version; a record with any other is no baseline.
BASELINE_VERSION = 2
#: A file whose modification time falls this close to the snapshot that read
#: it is hashed again at the next check even when its stat has not moved: a
#: write landing in the same timestamp tick as the snapshot leaves the stat
#: equal (git's "racy" entries; a coarse-clock filesystem widens the tick).
RACY_WINDOW_NS = 2_000_000_000
#: A change is the shell call's (or a parallel call's) when it landed after
#: the call began, less this much: the hook starts after the command ends,
#: so ``now - duration_ms`` lands late by the hook's own start-up, and a file
#: clock can round down. Wider errs toward "stop", the loud direction.
CALL_WINDOW_SLACK_NS = 5_000_000_000
#: A harness writer that has run longer than this is taken to have died
#: (``espalier.zone_writes.RUNNING_MAX_S``); its running marker stops holding
#: the check back.
WRITER_RUNNING_MAX_S = 600
#: Paths under the git dir that mean a git operation is half done; while one
#: exists the check holds its baseline and judges the result once git is done.
#: Twin of ``tools/cc/checkout_sync.py::_MID_OPERATION``'s names, pinned.
MID_OPERATION = ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD",
                 "REVERT_HEAD", "sequencer", "BISECT_LOG")
_SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")

Entry = list  # [size, mtime_ns, digest-or-None]


class WatchSetTooLarge(Exception):
    """The watched set passed a walk budget."""


def watched_prefixes(root: Path) -> list[str]:
    """The directory prefixes this check walks, each ending in ``/``."""
    prefixes = [p for p in _hook_utils.harness_protected_prefixes(root)
                if p not in UNWATCHED_PREFIXES]
    for prefix, kind in _hook_utils.adopter_protected_prefixes(root):
        if kind == "protected" and prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


def watched_files() -> list[str]:
    return sorted(set(_protected_zones.PROTECTED_FILES) - UNWATCHED_FILES)


#: The stack table's dependency directories, pruned when the deployed table
#: cannot be imported.
# stack-table: ok purpose-scoped -- the import fallback, held equal to the table by test
_DEPENDENCY_DIRS_FALLBACK: frozenset[str] = frozenset({
    "node_modules", "bower_components", "jspm_packages", ".yarn", ".pnpm-store",
})

_PRUNE_MEMO: dict[str, tuple[tuple[int, int] | None, frozenset[str]]] = {}


def pruned_dir_names(root: Path) -> frozenset[str]:
    """Every directory name the walk prunes: the cache names, the stack
    table's dependency directories and the adopter's ``dependency_dirs``
    (memoised on espalier.toml's stat: this runs on every shell call)."""
    config = root / "espalier.toml"
    try:
        st = config.stat()
        stamp: tuple[int, int] | None = (st.st_mtime_ns, st.st_size)
    except OSError:  # fail-open: ok deliberate -- no espalier.toml declares nothing; the table's names still prune
        stamp = None
    hit = _PRUNE_MEMO.get(str(config))
    if hit is not None and hit[0] == stamp:
        return hit[1]
    names = set(CACHE_DIR_NAMES)
    try:
        import _stack_table  # noqa: E402 -- tools/cc/, on the path above
        names |= set(_stack_table.dependency_dirs())
    except Exception:  # noqa: BLE001 -- fail-open: ok deliberate -- a missing or stale table prunes its pinned names below
        names |= _DEPENDENCY_DIRS_FALLBACK
    if stamp is not None:
        names |= set(_hook_utils.declared_dependency_dirs(root, hook="post_write_check"))
    result = frozenset(names)
    _PRUNE_MEMO[str(config)] = (stamp, result)
    return result


def is_clutter(name: str) -> bool:
    """An editor's or the OS's file beside a real one: a Finder or Explorer
    index, a swap or backup file, an emacs lock, or the tempfile an atomic
    write leaves for a moment (``.<name>.<hex>.tmp``)."""
    return (name in CLUTTER_NAMES or name.endswith((".swp", ".swo", "~"))
            or name.startswith(".#") or (name.startswith(".") and name.endswith(".tmp")))


def is_watched(root: Path, rel: str) -> bool:
    """Whether the repo-relative posix path ``rel`` is in the watched set."""
    if rel in watched_files():
        return True
    parts = rel.split("/")
    pruned = pruned_dir_names(root)
    if any(part in pruned for part in parts[:-1]) or is_clutter(parts[-1]):
        return False
    return any(rel.startswith(prefix) for prefix in watched_prefixes(root))


def bytes_digest(raw: bytes) -> str:
    """sha256 of the canonical text bytes (a BOM stripped, CRLF and CR
    folded), the integrity manifest's own canon: for a blob, a mirror's
    source, or a file already in hand."""
    return hashlib.sha256(_integrity.canonical_text_bytes(raw)).hexdigest()


def content_digest(path: Path, st: os.stat_result | None = None) -> str | None:
    """The file's identity: its canonical digest, or ``stat:<size>:<mtime>``
    for a file of BIG_FILE_BYTES or more (never read); None when it cannot
    be read."""
    try:
        st = st or path.stat()
        if st.st_size >= BIG_FILE_BYTES:
            return f"stat:{st.st_size}:{st.st_mtime_ns}"
        raw = path.read_bytes()
    except OSError:  # fail-open: ok deliberate -- an unreadable file hashes as None, which differs from any content and so reads as changed
        return None
    return bytes_digest(raw)


def snapshot(root: Path, prior: dict[str, Entry] | None = None,
             prior_taken_ns: int | None = None) -> dict[str, Entry]:
    """``{rel: [size, mtime_ns, digest]}`` for every watched file under ``root``.

    A file whose size and modification time equal ``prior``'s keeps the prior
    digest without a read, so a call that changed nothing costs one stat pass;
    a file whose prior modification time fell within RACY_WINDOW_NS of
    ``prior_taken_ns`` is hashed again regardless. A file that vanishes
    between the listing and the stat is absent, as it is on disk. Raises
    WatchSetTooLarge past WALK_FILE_BUDGET files or WALK_TIME_BUDGET_S."""
    prior = prior or {}
    racy_from = None if prior_taken_ns is None else prior_taken_ns - RACY_WINDOW_NS
    deadline = time.monotonic() + WALK_TIME_BUDGET_S
    pruned = pruned_dir_names(root)
    out: dict[str, Entry] = {}

    def take(rel: str, full: str) -> None:
        try:
            st = os.stat(full)
        except OSError:  # fail-open: ok deliberate -- gone between the listing and the stat: absent, as on disk
            return
        if not stat.S_ISREG(st.st_mode):
            return
        if len(out) >= WALK_FILE_BUDGET or time.monotonic() > deadline:
            raise WatchSetTooLarge(f"more than {WALK_FILE_BUDGET} files or {WALK_TIME_BUDGET_S:g} s to walk")
        old = prior.get(rel)
        if (old is not None and old[0] == st.st_size and old[1] == st.st_mtime_ns
                and (racy_from is None or old[1] < racy_from)):
            out[rel] = old
            return
        out[rel] = [st.st_size, st.st_mtime_ns, content_digest(Path(full), st)]

    for prefix in watched_prefixes(root):
        top = root / prefix
        # os.walk reports a missing or unreadable directory to no one (its
        # onerror is None), which is the answer here: nothing to watch.
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = sorted(d for d in dirnames if d not in pruned)
            base = Path(dirpath).relative_to(root).as_posix()
            for name in sorted(filenames):
                if not is_clutter(name):
                    take(f"{base}/{name}", os.path.join(dirpath, name))
    for rel in watched_files():
        if rel not in out:
            take(rel, str(root / rel))
    return out


def diff(before: dict[str, Entry], after: dict[str, Entry]) -> dict[str, list[str]]:
    """The watched paths whose content changed, appeared or disappeared."""
    return {
        "changed": sorted(r for r in after if r in before and after[r][2] != before[r][2]),
        "added": sorted(r for r in after if r not in before),
        "removed": sorted(r for r in before if r not in after),
    }


# -- git, read from its own files -------------------------------------------


def head_commit(root: Path) -> str | None:
    """The commit HEAD names, read from the git dir's own files (HEAD, the
    loose ref, packed-refs) without a spawn: it is asked on every shell call.
    None for an unborn branch, a reftable repository, or anything unreadable;
    a removal is then never git's (it reports)."""
    git_dir = _hook_utils._git_dir_of(root)
    if git_dir is None:
        return None
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head if _SHA_RE.fullmatch(head) else None
        return _ref_commit(git_dir, head[len("ref: "):].strip())
    # fail-open: ok deliberate -- an unreadable ref is no HEAD; a removal is then never git's, so it reports
    except (OSError, ValueError):  # strict decode: a structured answer (DEF-821)
        return None


def _common_dir(git_dir: Path) -> Path:
    """The directory holding the refs a checkout shares (a linked worktree's
    main git dir); raises OSError or ValueError on one git cannot read."""
    if (git_dir / "commondir").is_file():
        return (git_dir / (git_dir / "commondir").read_text(encoding="utf-8").strip()).resolve()
    return git_dir


def _ref_commit(git_dir: Path, ref: str) -> str | None:
    """The commit ``ref`` names: loose in the git dir, then in the common dir,
    then packed; raises OSError or ValueError on files git cannot read."""
    common = _common_dir(git_dir)
    for base in (git_dir, common):
        loose = base / ref
        if loose.is_file():
            value = loose.read_text(encoding="utf-8").strip()
            return value if _SHA_RE.fullmatch(value) else None
    packed = common / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            sha, _, name = line.partition(" ")
            if name == ref and _SHA_RE.fullmatch(sha):
                return sha
    return None


def stash_written_since(root: Path, since_ns: int) -> str | None:
    """The commit this checkout's stash names, when its ref or its reflog
    (which every push, pop and drop rewrites) was written at or after
    ``since_ns``; read from git's own files, no spawn. None otherwise, or
    when they cannot be read: what a stash took away is then not remembered,
    and its pop reports."""
    git_dir = _hook_utils._git_dir_of(root)
    if git_dir is None:
        return None
    try:
        common = _common_dir(git_dir)
        stamps = [p.stat().st_mtime_ns for p in (common / "refs" / "stash", common / "logs" / "refs" / "stash")
                  if p.is_file()]
        if not stamps or max(stamps) < since_ns:
            return None
        return _ref_commit(git_dir, "refs/stash")
    # fail-open: ok deliberate -- an unreadable stash names nothing; its pop then reports
    except (OSError, ValueError):  # strict decode: a structured answer (DEF-821)
        return None


def mid_operation(root: Path) -> str | None:
    """The git operation half done in this checkout, or None."""
    git_dir = _hook_utils._git_dir_of(root)
    if git_dir is None:
        return None
    for name in MID_OPERATION:
        if (git_dir / name).exists():
            return name
    return None


# -- Nested checkouts --------------------------------------------------------
#
# A clone, a submodule or a worktree under an adopter's protected path is
# walked like the rest of the zone (only its ``.git`` directory is pruned),
# and the outer HEAD never holds its files, so a pull inside it is judged by
# its own git (DEF-4012) -- but only a checkout the previous check already
# knew. One that appears during a call (a clone, a copy carrying its ``.git``,
# a submodule's first update) reports its files once, as a copy into a
# protected path should, and its later moves are its own git's. A path in the
# harness's own zones is never asked of a nested git, even under an adopter
# prefix that encloses one: a checkout planted there would account for
# whatever its own commit holds.

#: How long path 2 may spend asking nested checkouts in one call. Past it the
#: rest are named in a note and their paths stay unaccounted (the loud side):
#: a call over many clones must not cost the hook its timeout.
NESTED_ASK_BUDGET_S = 2.0
#: How long path 2's git spawns may take in one call, every checkout's
#: together: each spawn's timeout is what is left of it, and a hash with
#: nothing left is not started (its files are named and report), so path 2
#: never costs the hook its own timeout (10 s, beside a walk of up to 3 s).
GIT_ASK_BUDGET_S = 5.0
#: The git variables that would point a nested ``cat-file`` at a repository
#: other than the checkout it runs in.
_GIT_LOCATION_VARS = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"})

#: (the adopter's protected prefixes, the harness's protected prefixes, the
#: exact protected files): where a path may be judged by a nested git.
NestScope = tuple[tuple[str, ...], tuple[str, ...], frozenset[str]]


def _nest_scope(root: Path) -> NestScope:
    tops = tuple(p for p, kind in _hook_utils.adopter_protected_prefixes(root) if kind == "protected")
    return tops, tuple(_hook_utils.harness_protected_prefixes(root)), frozenset(watched_files())


def _nestable(rel: str, scope: NestScope) -> bool:
    """Whether ``rel`` may be judged by a nested checkout's git: under an
    adopter's protected prefix and in none of the harness's own zones, judged
    on the path itself, so a prefix enclosing a harness zone gives it none."""
    tops, harness, exact = scope
    return bool(tops) and rel.startswith(tops) and not rel.startswith(harness) and rel not in exact


def _ancestors(rel: str) -> Iterator[str]:
    """``rel``'s directories, nearest first (``a/b/c.txt``: ``a/b``, then ``a``)."""
    parts = rel.split("/")[:-1]
    for depth in range(len(parts), 0, -1):
        yield "/".join(parts[:depth])


def _checkout_of(rel: str, scope: NestScope, known: dict[str, str]) -> str:
    """The nearest of the ``known`` checkouts holding ``rel``, at, under or
    above its protected prefix, or ``""`` for the outer checkout."""
    if known and _nestable(rel, scope):
        for top in _ancestors(rel):
            if top in known:
                return top
    return ""


def nested_heads(root: Path, rels: Iterable[str]) -> dict[str, str]:
    """``{checkout: HEAD}`` for the nested checkout nearest each of ``rels``
    that may be judged by one: a directory whose ``.git`` names a git dir (a
    clone's directory, a submodule's or a worktree's gitlink file) with a
    HEAD read from git's own files, no spawn. A ``.git`` with no commit, or
    none git can read, is no checkout: nothing it holds is git's."""
    scope = _nest_scope(root)
    if not scope[0]:
        return {}
    heads: dict[str, str | None] = {}
    out: dict[str, str] = {}
    for rel in rels:
        if not _nestable(rel, scope):
            continue
        for top in _ancestors(rel):
            if top not in heads:
                heads[top] = head_commit(root / top)
            head = heads[top]
            if head is not None:
                out[top] = head
                break
    return out


def _nested_env(cwd: Path | None) -> dict[str, str] | None:
    """The environment for a git run in ``cwd``: a nested checkout's git is
    found from its own directory, never sent to another repository by an
    inherited GIT_DIR (None: the outer checkout keeps the hook's own)."""
    return None if cwd is None else {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_VARS}


def _git_objects(root: Path, requests: list[str], *, cwd: Path | None = None,
                 check_only: bool = False, timeout: float = 5.0) -> list[bytes | None] | None:
    """One ``git cat-file --batch`` for every request (``<rev>:./<path>``,
    resolved from ``cwd``, by default ``root``): each blob's bytes, or None
    for a request git has no blob for; with ``check_only``, one
    ``--batch-check`` and each blob's object id instead, so no blob reaches
    the hook (a big file's, or a removed file's, whose presence is all that
    is asked). None when git cannot answer at all (not installed, not a
    repository, past ``timeout``, an answer it cannot parse). Every request
    names a commit id (or its first parent) or HEAD, never a reflog entry, so
    one missing object is a ``missing`` line and never ends the batch. Bytes
    throughout: a blob is never decoded, only hashed."""
    import subprocess

    if any("\n" in r for r in requests):
        return None  # a path git's batch protocol cannot carry
    try:
        result = _hook_utils.spawn_checked(
            ["git", "cat-file", "--batch-check" if check_only else "--batch"], root=root,
            input=b"".join(os.fsencode(r) + b"\n" for r in requests),
            capture_output=True, timeout=timeout, cwd=str(cwd or root), env=_nested_env(cwd),
        )
    except (subprocess.SubprocessError, OSError):  # fail-open: ok deliberate -- None makes the caller report the change and say git could not answer
        return None
    if isinstance(result, _hook_utils.SpawnFailure) or result.returncode != 0:
        return None
    out: bytes = result.stdout
    answers: list[bytes | None] = []
    pos = 0
    for _request in requests:
        end = out.find(b"\n", pos)
        if end < 0:
            return None
        header = out[pos:end].split(b" ")
        pos = end + 1
        if header[-1] in (b"missing", b"ambiguous"):
            answers.append(None)
            continue
        if len(header) != 3 or not header[2].isdigit():
            return None
        if check_only:
            answers.append(header[0] if header[1] == b"blob" else None)
            continue
        size = int(header[2])
        answers.append(out[pos:pos + size] if header[1] == b"blob" else None)
        pos += size + 1
    return answers


#: How many bytes of files of BIG_FILE_BYTES or more one call may have git
#: hash: past it the rest are named in a note and report, so a pull of many
#: model files never costs the hook its timeout. Measured on an 8 GB laptop:
#: about 0.5 ms per MiB with a warm cache (100 MB in 58 ms, the whole budget
#: in 0.47 s), several times that cold (the whole budget in 2.65 to 2.86 s).
BIG_HASH_BUDGET_BYTES = 1 << 30
#: Past git's own ``core.bigFileThreshold`` (512 MiB by default, lower where a
#: repository sets it) hash-object streams the file and compresses what it
#: never writes: 513 MiB took 9.3 s against 233 ms at 511 MiB (measured). The
#: hash runs with the threshold past the budget, so no file it may hash
#: reaches that path.
_HASH_THRESHOLD = f"core.bigFileThreshold={BIG_HASH_BUDGET_BYTES + 1}"


def _hash_objects(root: Path, paths: list[str], *, cwd: Path | None = None,
                  timeout: float = 5.0) -> tuple[list[bytes] | None, bool]:
    """``(ids, timed_out)``: ``git hash-object`` of each path (relative to
    ``cwd``), through the checkout's own filters (a big LFS file hashes to
    its pointer, as committed), the object id each file would have, or None
    when git gives none, with whether it ran past ``timeout``. The paths go
    on stdin, so no count of them meets a command-line limit. Git reads the
    files; the hook never does."""
    import subprocess

    if any("\n" in p for p in paths):
        return None, False  # a path stdin cannot carry; such a checkout is never asked this far
    try:
        result = _hook_utils.spawn_checked(
            ["git", "-c", _HASH_THRESHOLD, "hash-object", "--stdin-paths"], root=root,
            input=b"".join(os.fsencode(p) + b"\n" for p in paths),
            capture_output=True, timeout=timeout, cwd=str(cwd or root), env=_nested_env(cwd),
        )
    except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- None leaves the big files unaccounted; the caller names them and says git did not finish
        return None, True
    except (subprocess.SubprocessError, OSError):  # fail-open: ok deliberate -- None leaves the big files unaccounted; the caller names them and says git could not hash them
        return None, False
    if isinstance(result, _hook_utils.SpawnFailure) or result.returncode != 0:
        return None, False
    oids: list[bytes] = result.stdout.split()
    return (oids if len(oids) == len(paths) else None), False


def _identified_by_stat(digest: str | None) -> bool:
    """A file of BIG_FILE_BYTES or more, never read: its identity is its stat."""
    return digest is not None and digest.startswith("stat:")


# -- The per-session baseline ------------------------------------------------
#
# One file per session beside the session's marker, named by the same
# sanitised id with a suffix the marker readers' ``*.json`` glob does not
# match; the marker's sweeps retire it (_hook_utils.SESSION_SIDE_SUFFIXES).
# Only this session's hooks write it (Core Rule 14): SessionStart takes it,
# post_write_check replaces it under the lock beside it, and a sibling session
# only reads its ``known`` map.


def baseline_path(root: Path, sid: object) -> Path | None:
    """``sid``'s baseline path, or None for an id nothing survives of."""
    safe = _hook_utils.safe_session_id(sid)
    if not safe:
        return None
    return _hook_utils.sessions_dir(root) / f"{safe}{_hook_utils.ZONE_BASELINE_SUFFIX}"


def new_baseline(root: Path, files: dict[str, Entry], taken_ns: int, *,
                 disabled: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "v": BASELINE_VERSION, "taken_ns": taken_ns, "files": files, "known": {},
        "told": [], "head": head_commit(root), "watched": watched_prefixes(root),
        "nested": nested_heads(root, files),
    }
    if disabled:
        record["disabled"] = disabled
    return record


def _valid_entry(entry: object) -> bool:
    return (isinstance(entry, list) and len(entry) == 3
            and all(isinstance(n, int) and not isinstance(n, bool) for n in entry[:2])
            and (entry[2] is None or isinstance(entry[2], str)))


def read_baseline(path: Path) -> dict[str, Any] | None:
    """The baseline at ``path``, or None when there is no usable one (absent,
    unreadable, another schema, a malformed entry): the caller takes a new one.
    ``nested`` (each nested checkout's HEAD) is optional, so a baseline written
    before it reads as one with none known."""
    try:
        raw = path.read_bytes()
    except OSError:  # fail-open: ok deliberate -- no readable baseline: the caller takes one and says the call was unchecked
        return None
    record = load_json_dict_safe(raw, default=None)
    if not isinstance(record, dict) or record.get("v") != BASELINE_VERSION:
        return None
    files, known, told = record.get("files"), record.get("known"), record.get("told")
    taken, head, watched = record.get("taken_ns"), record.get("head"), record.get("watched")
    nested = record.setdefault("nested", {})
    if not (isinstance(files, dict) and all(_valid_entry(e) for e in files.values())
            and isinstance(known, dict)
            and all(isinstance(v, list) and all(isinstance(d, str) for d in v) for v in known.values())
            and isinstance(told, list) and all(isinstance(t, str) for t in told)
            and isinstance(taken, int) and not isinstance(taken, bool)
            and (head is None or isinstance(head, str))
            and isinstance(watched, list) and all(isinstance(p, str) for p in watched)
            and isinstance(nested, dict) and all(isinstance(v, str) for v in nested.values())
            and isinstance(record.get("disabled", ""), str)):
        return None
    return record


def write_baseline(path: Path, record: dict[str, Any]) -> None:
    """Replace the baseline atomically. Raises OSError; the caller decides."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _hook_utils.atomic_write_text(
        path, json.dumps(record, separators=(",", ":"), ensure_ascii=True, sort_keys=True) + "\n")


@contextlib.contextmanager
def baseline_lock(path: Path) -> Iterator[bool]:
    """Hold the cross-process lock beside ``path`` for a read-diff-write, so
    two parallel calls in one session report a change once, never twice.
    Yields whether the lock is held: where the lock cannot be taken the body
    runs unlocked and the caller accepts a possible duplicate report, which
    costs less than saying nothing."""
    lock_path = path.with_name(path.name + ".lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(lock_path, "a+", encoding="utf-8")
    except OSError:  # fail-open: ok deliberate -- no lock file: the body runs unlocked and a duplicate report is the cost
        yield False
        return
    try:
        try:
            _hook_utils.lock_file(fh)
        except OSError:  # fail-open: ok deliberate -- a filesystem that cannot lock: unlocked, and a duplicate report is the cost
            yield False
            return
        try:
            yield True
        finally:
            with contextlib.suppress(OSError):
                _hook_utils.unlock_file(fh)
    finally:
        fh.close()


# -- Accounting --------------------------------------------------------------

#: Accounting path 3, on the harness's own source tree only: the byte and
#: normalized rows of espalier/mirror_registry.py whose copy sits in the watched
#: set, as (mirror, source) path prefixes -- a whole path for a one-file row.
#: Written here because a hook imports nothing from espalier/;
#: tests/test_zone_watch.py holds it equal to the registry both ways. A row that
#: transforms its source cannot be judged by equality: its sync script records
#: what it wrote instead (path 4). Off the source tree no row exists, and an
#: adopter's harness-guard workflow, deleted, must not read as a pruned mirror.
MIRROR_PAIRS: tuple[tuple[str, str], ...] = (
    ("espalier/_vendor/cc/", "tools/cc/"),
    ("espalier/assets/claude/", ".claude/"),
    ("espalier/assets/docs/", "docs/"),
    ("espalier/assets/task-packs/CLAUDE.md", "task-packs/CLAUDE.md"),
    ("espalier/_stack_table.py", "tools/cc/_stack_table.py"),
    (".github/workflows/harness-guard.yml", "espalier/assets/github/workflows/harness-guard.yml"),
)


def mirror_source(rel: str) -> str | None:
    """The source path whose copy ``rel`` is, or None when it is no mirror."""
    for mirror, source in MIRROR_PAIRS:
        if mirror.endswith("/"):
            if rel.startswith(mirror):
                return source + rel[len(mirror):]
        elif rel == mirror:
            return source
    return None


def _mirrors_its_source(root: Path, rel: str, digest: str | None) -> bool:
    """A mirror whose content equals its source's, or a removed mirror whose
    source is gone too (``digest`` None for a removal): what a sync leaves."""
    source = mirror_source(rel)
    if source is None:
        return False
    if digest is None:
        return not (root / source).exists()
    return content_digest(root / source) == digest


#: Accounting path 4: where a harness writer records what it wrote during its
#: own run (espalier/zone_writes.py), one file per writer, and which writers'
#: records count: the espalier commands that rewrite protected files (the CLI
#: brackets each one) and the sync scripts whose mirror transforms its source.
#: A writer still running leaves ``<record>.running`` beside its record. Twin
#: of espalier/zone_writes.py, pinned by tests/test_zone_writes.py.
WRITE_RECORD_DIR = "zone_writes"
RUNNING_SUFFIX = ".running"
ENGINE_WRITER_PREFIX = "espalier "
SCRIPT_WRITERS = frozenset({"scripts/sync_selfcheck_tests.py"})


def record_name(writer: str) -> str:
    """The one file a writer's records live in (espalier.zone_writes.record_name)."""
    return re.sub(r"[^A-Za-z0-9]+", "-", writer).strip("-") + ".json"


def writer_running(root: Path) -> str | None:
    """The name of a harness writer's record whose run has not ended (its
    running marker younger than WRITER_RUNNING_MAX_S), or None."""
    directory = root / _hook_utils.STATE_DIR / WRITE_RECORD_DIR
    try:
        markers = list(directory.glob("*" + RUNNING_SUFFIX))
    except OSError:  # fail-open: ok deliberate -- no records directory: no writer is running
        return None
    now = time.time()
    for marker in markers:
        try:
            if now - marker.stat().st_mtime < WRITER_RUNNING_MAX_S:
                return marker.name[: -len(RUNNING_SUFFIX)]
        except OSError:  # fail-open: ok deliberate -- a marker removed as it was read: that writer has ended
            continue
    return None


def _recorded_writes(root: Path, since_ns: int) -> dict[str, set[str | None]]:
    """``{rel: {digest, ...}}`` that a rostered writer recorded writing after
    ``since_ns`` (None for a removal). A record from before the previous check
    accounts for nothing now: the change it explains was seen then."""
    directory = root / _hook_utils.STATE_DIR / WRITE_RECORD_DIR
    try:
        entries = sorted(directory.glob("*.json"))
    except OSError:  # fail-open: ok deliberate -- no records: path 4 accounts for nothing and the change reports
        return {}
    out: dict[str, set[str | None]] = {}
    for path in entries:
        try:
            raw = path.read_bytes()
        except OSError:  # fail-open: ok deliberate -- an unreadable record accounts for nothing; its change reports
            continue
        record = load_json_dict_safe(raw, default=None)
        writer = record.get("writer") if isinstance(record, dict) else None
        files = record.get("files") if isinstance(record, dict) else None
        if not (isinstance(writer, str) and isinstance(files, dict)
                and (writer.startswith(ENGINE_WRITER_PREFIX) or writer in SCRIPT_WRITERS)
                and path.name == record_name(writer)):
            continue
        for rel, entry in files.items():
            if (isinstance(rel, str) and isinstance(entry, list) and len(entry) == 2
                    and (entry[0] is None or isinstance(entry[0], str))
                    and isinstance(entry[1], int) and entry[1] >= since_ns):
                out.setdefault(rel, set()).add(entry[0])
    return out


#: How many recent known contents a baseline keeps per path: what a file tool
#: wrote, and what any path accounted for or this check reported. Enough for a
#: stash and its pop, or a return to an earlier state, to read as known.
KNOWN_KEPT_PER_PATH = 8


def _known(root: Path, sid: object, own: dict[str, list[str]]) -> dict[str, set[str]]:
    """``{rel: {digest, ...}}`` known for each path: this session's own, and
    every live sibling session's in this checkout, read from the sibling's
    baseline (read only: each baseline has one writer, its session)."""
    known: dict[str, set[str]] = {rel: set(digests) for rel, digests in own.items()}
    for row in _hook_utils.other_live_sessions(root, sid):
        path = baseline_path(root, row.get("session_id"))
        record = read_baseline(path) if path is not None else None
        if record is None:
            continue
        for rel, digests in record["known"].items():
            known.setdefault(rel, set()).update(digests)
    return known


def _remember(known: dict[str, list[str]], rel: str, digest: str | None) -> None:
    if digest is None:
        return
    kept = [d for d in known.get(rel, []) if d != digest]
    known[rel] = (kept + [digest])[-KNOWN_KEPT_PER_PATH:]


def _blob_holds(blob: bytes | None, digest: str | None) -> bool:
    """Whether a blob git answered holds content with this digest."""
    return blob is not None and digest is not None and bytes_digest(blob) == digest


def account(root: Path, sid: object, moved: dict[str, list[str]],
            before: dict[str, Entry], after: dict[str, Entry],
            own_known: dict[str, list[str]], since_ns: int,
            base_head: str | None,
            base_nested: dict[str, str] | None = None,
            ) -> tuple[dict[str, list[str]], list[str], dict[str, str | None]]:
    """The moved paths no legitimate path accounts for, by kind; notes on any
    path that could not be asked; and ``{path: digest}``, the content a stash
    took from each changed path git accounted for, so the caller keeps it as
    known (the pop of a stash of an edit there before the session). Checked
    only for what moved, so a call that changed nothing never reaches here;
    accounting is an OR, so the cheap paths run first and git's spawns, all
    within GIT_ASK_BUDGET_S, run last:

    1. known content: a file tool wrote it (judged by path before it ran), or
       a path accounted for it, or this check reported it -- in this session
       or a live sibling's in this checkout; a removed file whose last content
       was known and that HEAD does not hold (a stash of a new file) is known;
    3. on the harness's own source tree, a mirror row's copy now equal to its
       source (MIRROR_PAIRS);
    4. a harness writer recorded this content (or this removal) during a run
       that ended after ``since_ns``, the previous check;
    2. git: the file now holds its content at HEAD; a removed file is absent
       at HEAD and was present at ``base_head``, the HEAD of the previous
       check, through any number of moves in one call. A file in a nested
       checkout under an adopter's protected path, one the previous check
       knew (``base_nested``, from ``nested_heads``), is asked of that
       checkout's own git, a removal against its HEAD then; the nested asks
       start within NESTED_ASK_BUDGET_S. A file of BIG_FILE_BYTES or more, now
       or at the previous check, never read here, is hashed by git through the
       checkout's filters and matched with its blob id at HEAD, within
       BIG_HASH_BUDGET_BYTES a call and after every checkout's asks, so a slow
       hash never costs a nested checkout its turn; a removal is judged by
       presence alone, so no big blob is read into the hook. A changed file
       git accounted for has its earlier content kept as known only when the
       checkout's stash, written since the previous check, holds that content
       at the path and the stash's parent commit does not: what the stash took.
    """
    remaining = {kind: list(paths) for kind, paths in moved.items()}
    notes: list[str] = []
    moved_from: dict[str, str | None] = {}

    def present(r: str) -> str | None:
        return after[r][2]

    known = _known(root, sid, own_known)
    for kind in ("changed", "added"):
        remaining[kind] = [r for r in remaining[kind]
                           if present(r) is None or present(r) not in known.get(r, ())]

    if _hook_utils.is_self_host_repo(root):
        for kind in ("changed", "added"):
            remaining[kind] = [r for r in remaining[kind]
                               if present(r) is None or not _mirrors_its_source(root, r, present(r))]
        remaining["removed"] = [r for r in remaining["removed"] if not _mirrors_its_source(root, r, None)]

    if any(remaining.values()):
        recorded = _recorded_writes(root, since_ns)
        for kind in ("changed", "added"):
            remaining[kind] = [r for r in remaining[kind]
                               if present(r) is None or present(r) not in recorded.get(r, ())]
        remaining["removed"] = [r for r in remaining["removed"] if None not in recorded.get(r, ())]

    if any(remaining.values()):
        kept = remaining["changed"] + remaining["added"]
        gone = remaining["removed"]
        scope = _nest_scope(root)
        # Only a checkout the previous check knew, and still a checkout now:
        # one that appeared since vouches for nothing (its files report once),
        # and one gone since leaves its paths to the outer git.
        known_heads = {t: h for t, h in (base_nested or {}).items() if head_commit(root / t) is not None}
        by_checkout: dict[str, list[str]] = {}
        for r in kept + gone:
            by_checkout.setdefault(_checkout_of(r, scope, known_heads), []).append(r)
        gone_set = set(gone)
        asked: set[str] = set()
        inside: dict[str, str] = {}             # each path as its checkout names it
        top_of: dict[str, str] = {}             # and that checkout ("" for the outer one)
        at_head: dict[str, bytes | None] = {}   # a small kept file's blob at HEAD
        head_oid: dict[str, bytes | None] = {}  # a big kept file's blob id at HEAD
        clean: set[str] = set()                 # a big kept file git hashes to that id
        head_has: dict[str, bool] = {}          # a removed file's presence at HEAD
        base_has: dict[str, bool] = {}          # and at the HEAD of the previous check
        hash_left = BIG_HASH_BUDGET_BYTES
        to_hash: list[tuple[str, list[str]]] = []
        unhashed: list[str] = []
        late: list[str] = []
        start = time.monotonic()

        def left() -> float:
            return GIT_ASK_BUDGET_S - (time.monotonic() - start)

        def big(r: str) -> bool:
            # Never read: big now, or at the previous check (a model cut short
            # by hand still has a big blob at HEAD, which can never match it).
            return _identified_by_stat(present(r)) or (r in before and _identified_by_stat(before[r][2]))

        for top, rels in sorted(by_checkout.items()):   # the outer checkout ("") first, always asked
            if top and time.monotonic() - start > NESTED_ASK_BUDGET_S:
                late.append(top)
                continue
            for r in rels:
                inside[r], top_of[r] = (r[len(top) + 1:] if top else r), top
            base = base_head if not top else known_heads[top]
            cwd = root / top if top else None
            # A big file and a removed one are asked for presence alone: no blob
            # of theirs is read into the hook.
            small = [r for r in rels if r not in gone_set and not big(r)]
            bigs = [r for r in rels if r not in gone_set and big(r)]
            gone_here = [r for r in rels if r in gone_set]
            checks = [f"HEAD:./{inside[r]}" for r in bigs + gone_here]
            if base is not None:
                checks += [f"{base}:./{inside[r]}" for r in gone_here]
            blobs = (_git_objects(root, [f"HEAD:./{inside[r]}" for r in small], cwd=cwd, timeout=left())
                     if small else [])
            oids = _git_objects(root, checks, cwd=cwd, check_only=True, timeout=left()) if checks else []
            if blobs is None or oids is None:
                notes.append("git could not be asked, so committed content was not checked" if not top else
                             f"the git of {top.encode('unicode_escape').decode('ascii')}/ could not be asked, "
                             "so its committed content was not checked")
                continue
            asked.update(rels)
            at_head.update(zip(small, blobs))
            head_oid.update(zip(bigs, oids[:len(bigs)]))
            n = len(bigs) + len(gone_here)
            head_has.update((r, o is not None) for r, o in zip(gone_here, oids[len(bigs):n]))
            base_has.update((r, o is not None) for r, o in zip(gone_here, oids[n:]))
            hashable = []
            for r in bigs:
                if head_oid.get(r) is None:
                    continue   # not at HEAD: there is nothing for its content to match
                if after[r][0] > hash_left:
                    unhashed.append(r)
                    continue
                hash_left -= after[r][0]
                hashable.append(r)
            if hashable:
                to_hash.append((top, hashable))
        # Hashed last, after every checkout's asks: a slow hash (a file of
        # hundreds of MiB, a clean filter) never costs a nested checkout its turn.
        for top, hashable in to_hash:
            budget = left()
            hashes, timed_out = (_hash_objects(root, [inside[r] for r in hashable], cwd=root / top if top else None,
                                               timeout=budget)
                                 if budget > 0 else (None, True))
            if hashes is None:
                notes.append(f"git {'did not finish hashing' if timed_out else 'could not hash'} {len(hashable)} "
                             f"file(s) of {BIG_FILE_BYTES >> 20} MiB or more ({_names(hashable)})"
                             f"{f' within {GIT_ASK_BUDGET_S:g} s' if timed_out else ''}, "
                             "so their committed content was not checked")
            else:
                clean.update(r for r, h in zip(hashable, hashes) if h == head_oid[r])
        if late:
            names = ", ".join(t.encode("unicode_escape").decode("ascii") + "/" for t in late)
            notes.append(f"{len(late)} nested checkout(s) were not asked within {NESTED_ASK_BUDGET_S:g} s ({names}), "
                         "so their committed content was not checked")
        if unhashed:
            notes.append(f"{len(unhashed)} file(s) of {BIG_FILE_BYTES >> 20} MiB or more were past the "
                         f"{BIG_HASH_BUDGET_BYTES >> 20} MiB one call may hash ({_names(unhashed)}), "
                         "so their committed content was not checked")
        stashed: dict[str, list[str]] = {}   # per checkout: changed paths git accounted for, small before and now
        for kind in ("changed", "added"):
            still: list[str] = []
            for r in remaining[kind]:
                if r in asked and (r in clean or _blob_holds(at_head.get(r), present(r))):
                    if kind == "changed" and not big(r):
                        stashed.setdefault(top_of[r], []).append(r)
                else:
                    still.append(r)
            remaining[kind] = still
        remaining["removed"] = [
            r for r in gone
            if not (r in asked and not head_has.get(r, False)
                    and (base_has.get(r, False) or before[r][2] in known.get(r, ())))]
        # What a stash took: the content before, held by the stash at the path
        # and not by its parent (HEAD when it was made), so a file the stash
        # merely carried unchanged beside a pull is not one. A stash written
        # within the racy window before the previous check counts: a coarse
        # file system clock can stamp a write just after a check before it.
        for top, rels in sorted(stashed.items()):
            stash = stash_written_since(root / top if top else root, since_ns - RACY_WINDOW_NS)
            budget = left()
            if stash is None or budget <= 0:
                continue   # its pop reports, the loud side
            held = _git_objects(root, [f"{stash}:./{inside[r]}" for r in rels]
                                + [f"{stash}^1:./{inside[r]}" for r in rels],
                                cwd=root / top if top else None, timeout=budget)
            if held is None:
                continue   # its pop reports, the loud side
            for r, mine, parent in zip(rels, held[:len(rels)], held[len(rels):]):
                if _blob_holds(mine, before[r][2]) and not _blob_holds(parent, before[r][2]):
                    moved_from[r] = before[r][2]
    return remaining, notes, moved_from


def _names(rels: list[str]) -> str:
    """Up to three paths for a note, escaped to ASCII, then ``...``."""
    return ", ".join(r.encode("unicode_escape").decode("ascii") for r in rels[:3]) + (", ..." if len(rels) > 3 else "")


def _change_time(root: Path, rel: str, after: dict[str, Entry]) -> int | None:
    """When ``rel`` changed: its modification time, or for a removed file the
    modification time of the nearest directory above it that still exists
    (a removal updates its directory). None when nothing can be read."""
    if rel in after:
        return after[rel][1]
    parent = (root / rel).parent
    while True:
        try:
            return parent.stat().st_mtime_ns
        except OSError:  # fail-open: ok deliberate -- the directory went too: try the one above
            if parent == root or parent.parent == parent:
                return None
            parent = parent.parent


def split_by_call(root: Path, unaccounted: dict[str, list[str]], after: dict[str, Entry],
                  call_start_ns: int | None) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """``(during, between)``: what landed after the shell call began (it or a
    parallel call may have made it), and what landed before (a person's
    editor, another session, a background job). With no call start, or no
    time for a change, everything is ``during``: the loud side."""
    during: dict[str, list[str]] = {k: [] for k in unaccounted}
    between: dict[str, list[str]] = {k: [] for k in unaccounted}
    for kind, rels in unaccounted.items():
        for rel in rels:
            when = _change_time(root, rel, after)
            if call_start_ns is None or when is None or when >= call_start_ns - CALL_WINDOW_SLACK_NS:
                during[kind].append(rel)
            else:
                between[kind].append(rel)
    return during, between


def _restrict(files: dict[str, Entry], keep: list[str]) -> dict[str, Entry]:
    """``files`` limited to paths under the prefixes in ``keep`` or watched exactly."""
    exact = set(watched_files())
    return {r: e for r, e in files.items() if r in exact or r.startswith(tuple(keep))}


def _tell_key(rel: str, after: dict[str, Entry]) -> str:
    digest = after[rel][2] if rel in after else None
    return f"{rel}@{digest or '-'}"


def after_shell_call(root: Path, sid: object, duration_ms: object = None) -> dict[str, Any] | None:
    """Compare the zones with the session's previous check and replace the
    baseline, under the lock beside it. Returns None when there is nothing to
    say, else one of:

    - ``{"status": "unchecked", "reason": ...}``: no baseline to compare
      against; this call's state becomes the baseline;
    - ``{"status": "off", "reason": ...}``: the watched set passed a walk
      budget; the check is off for this session;
    - ``{"status": "changed", "during": {...}, "between": {...},
      "operator": [...], "notes": [...], "watched_changed": bool}``: what moved
      that nothing accounts for, split by whether it landed during the call,
      and which of those changes the operator has not been told about.

    The common call changed nothing and writes nothing: it peeks without the
    lock (a few milliseconds on Windows) and returns. A call that sees
    something move while git is half way through an operation, or while a
    harness writer is still running, holds the baseline and returns: the
    result is judged once they are done. An operation half done in a known
    nested checkout holds that checkout's paths alone."""
    path = baseline_path(root, sid)
    if path is None:
        return {"status": "unchecked", "reason": "the payload carried no session id"}
    call_start = None
    if isinstance(duration_ms, (int, float)) and not isinstance(duration_ms, bool) and duration_ms >= 0:
        call_start = time.time_ns() - int(duration_ms * 1_000_000)
    peek = read_baseline(path)
    if peek is not None and peek.get("disabled"):
        return {"status": "off", "reason": peek["disabled"]}
    head = head_commit(root)
    if peek is not None:
        try:
            # The nested heads too, so a checkout that moved, or a directory
            # that became one, with no file moving is recorded for the next
            # call's removals (one directory read per watched one under an
            # adopter prefix; nothing without one).
            snap = snapshot(root, peek["files"], peek["taken_ns"])
            unmoved = (snap == peek["files"] and head == peek["head"] and watched_prefixes(root) == peek["watched"]
                       and nested_heads(root, snap) == peek["nested"])
        except WatchSetTooLarge:  # fail-open: ok deliberate -- too large to peek: the locked pass below turns the check off and says so
            unmoved = False
        if unmoved:
            return None
        if mid_operation(root) or writer_running(root):
            return None
    with baseline_lock(path):
        record = read_baseline(path)
        taken = time.time_ns()
        if record is None or record.get("disabled"):
            try:
                write_baseline(path, new_baseline(root, snapshot(root), taken))
                return {"status": "unchecked", "reason": "this session had no zone baseline"}
            except WatchSetTooLarge as exc:
                with contextlib.suppress(OSError):
                    write_baseline(path, new_baseline(root, {}, taken, disabled=str(exc)))
                return {"status": "off", "reason": str(exc)}
            except OSError:  # fail-open: ok deliberate -- the caller says the call was unchecked; the next call tries again
                return {"status": "unchecked", "reason": "the zone baseline could not be written"}
        watched_now = watched_prefixes(root)
        watched_changed = watched_now != record["watched"]
        before = record["files"]
        # Read before the snapshot, as the outer HEAD is: a head stored with
        # files newer than it would judge the next call's removals against
        # the wrong commit. A checkout found only in the snapshot is read after.
        nested_now = nested_heads(root, before)
        # A git operation half done in a known nested checkout holds that
        # checkout's paths alone: their entries and its head stay as they were,
        # judged once git is done there, and everything else is judged now.
        held = tuple(t + "/" for t in sorted(record["nested"]) if mid_operation(root / t))
        try:
            after = snapshot(root, before, record["taken_ns"])
        except WatchSetTooLarge as exc:
            with contextlib.suppress(OSError):
                write_baseline(path, new_baseline(root, {}, taken, disabled=str(exc)))
            return {"status": "off", "reason": str(exc)}
        for top, sha in nested_heads(root, [r for r in after if r not in before]).items():
            nested_now.setdefault(top, sha)
        if held:
            kept_files = {r: e for r, e in before.items() if r.startswith(held)}
            before = {r: e for r, e in before.items() if not r.startswith(held)}
            after = {r: e for r, e in after.items() if not r.startswith(held)}
            for top in (t[:-1] for t in held):
                nested_now[top] = record["nested"][top]
        else:
            kept_files = {}
        if watched_changed:
            # A path that left the watched set did not disappear, and one that
            # joined it did not appear: compare only what both sets watch.
            common = [p for p in watched_now if p in record["watched"]]
            before = _restrict(before, common)
            compare_after = _restrict(after, common)
        else:
            compare_after = after
        moved = diff(before, compare_after)
        unaccounted, notes, moved_from = (account(root, sid, moved, before, compare_after, record["known"],
                                                  record["taken_ns"], record["head"], record["nested"])
                                          if any(moved.values()) else ({k: [] for k in moved}, [], {}))
        for rel, digest in moved_from.items():
            _remember(record["known"], rel, digest)
        for rel in moved["changed"] + moved["added"]:
            _remember(record["known"], rel, compare_after[rel][2])
        during, between = split_by_call(root, unaccounted, compare_after, call_start)
        told = set(record["told"])
        keys = [_tell_key(r, compare_after) for kind in ("changed", "added", "removed")
                for r in unaccounted[kind]]
        operator = [k.rsplit("@", 1)[0] for k in keys if k not in told]
        record.update(files={**after, **kept_files}, taken_ns=taken, head=head, watched=watched_now,
                      nested=nested_now, told=sorted(told | set(keys)))
        try:
            write_baseline(path, record)
        except OSError:  # fail-open: ok deliberate -- the finding still reports; the note says the next call may repeat it
            notes.append("the zone baseline could not be replaced, so the next call may report this again")
    if not keys:
        return None
    return {"status": "changed", "during": during, "between": between, "operator": operator,
            "notes": notes, "watched_changed": watched_changed}


def after_file_tool(root: Path, sid: object, rels: list[str]) -> None:
    """A file tool's write was judged by path before it ran: refresh its
    entry, so the next shell call does not report it, and record its content
    as known, so a sibling session in this checkout does not either. A
    session with no baseline yet is left to its next shell call. Raises
    OSError when the baseline cannot be replaced; the caller says so."""
    path = baseline_path(root, sid)
    watched = [rel for rel in rels if is_watched(root, rel)]
    if path is None or not watched:
        return
    with baseline_lock(path):
        record = read_baseline(path)
        if record is None or record.get("disabled"):
            return
        for rel in watched:
            full = root / rel
            try:
                st = full.stat()
            except OSError:  # fail-open: ok deliberate -- gone again: the next shell call sees it as removed and judges it
                record["files"].pop(rel, None)
                continue
            digest = content_digest(full, st)
            record["files"][rel] = [st.st_size, st.st_mtime_ns, digest]
            _remember(record["known"], rel, digest)
        write_baseline(path, record)


def take_baseline(root: Path, sid: object, *, keep_valid: bool = False) -> bool:
    """Write a fresh baseline for ``sid`` (SessionStart). ``keep_valid`` keeps
    a usable one instead: a compaction continues the same process, so its
    known contents and what the operator was told stay, and a change since the
    last check is still this session's to report. Returns whether a usable
    baseline is on disk; never raises an OSError (a session without one has
    its first shell call taken as it, and says so)."""
    path = baseline_path(root, sid)
    if path is None:
        return False
    with baseline_lock(path):
        if keep_valid:
            kept = read_baseline(path)
            if kept is not None and not kept.get("disabled"):
                return True
        taken = time.time_ns()
        try:
            try:
                write_baseline(path, new_baseline(root, snapshot(root), taken))
            except WatchSetTooLarge as exc:
                write_baseline(path, new_baseline(root, {}, taken, disabled=str(exc)))
        except OSError:  # fail-open: ok deliberate -- the next shell call finds no baseline, takes one and says so
            return False
    return True
