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
from collections.abc import Iterator
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
        ref = head[len("ref: "):].strip()
        common = git_dir
        if (git_dir / "commondir").is_file():
            common = (git_dir / (git_dir / "commondir").read_text(encoding="utf-8").strip()).resolve()
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
    # fail-open: ok deliberate -- an unreadable ref is no HEAD; a removal is then never git's, so it reports
    except (OSError, ValueError):  # strict decode: a structured answer (DEF-821)
        return None
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


def _git_objects(root: Path, requests: list[str]) -> list[bytes | None] | None:
    """One ``git cat-file --batch`` for every request (``<rev>:./<path>``,
    resolved from ``root``): each blob's bytes, or None for a request git has
    no blob for. None when git cannot answer at all (not installed, not a
    repository, a timeout, an answer it cannot parse). Every request names a
    commit id or HEAD, never a reflog entry, so one missing object is a
    ``missing`` line and never ends the batch. Bytes throughout: a blob is
    never decoded, only hashed."""
    import subprocess

    if any("\n" in r for r in requests):
        return None  # a path git's batch protocol cannot carry
    try:
        result = _hook_utils.spawn_checked(
            ["git", "cat-file", "--batch"], root=root,
            input=b"".join(os.fsencode(r) + b"\n" for r in requests),
            capture_output=True, timeout=5, cwd=str(root),
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
        size = int(header[2])
        answers.append(out[pos:pos + size] if header[1] == b"blob" else None)
        pos += size + 1
    return answers


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
    unreadable, another schema, a malformed entry): the caller takes a new one."""
    try:
        raw = path.read_bytes()
    except OSError:  # fail-open: ok deliberate -- no readable baseline: the caller takes one and says the call was unchecked
        return None
    record = load_json_dict_safe(raw, default=None)
    if not isinstance(record, dict) or record.get("v") != BASELINE_VERSION:
        return None
    files, known, told = record.get("files"), record.get("known"), record.get("told")
    taken, head, watched = record.get("taken_ns"), record.get("head"), record.get("watched")
    if not (isinstance(files, dict) and all(_valid_entry(e) for e in files.values())
            and isinstance(known, dict)
            and all(isinstance(v, list) and all(isinstance(d, str) for d in v) for v in known.values())
            and isinstance(told, list) and all(isinstance(t, str) for t in told)
            and isinstance(taken, int) and not isinstance(taken, bool)
            and (head is None or isinstance(head, str))
            and isinstance(watched, list) and all(isinstance(p, str) for p in watched)
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
            base_head: str | None) -> tuple[dict[str, list[str]], list[str]]:
    """The moved paths no legitimate path accounts for, by kind, and notes on
    any path that could not be asked. Checked only for what moved, so a call
    that changed nothing never reaches here; accounting is an OR, so the
    cheap paths run first and git, the one spawn, runs last:

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
       check, through any number of moves in one call.
    """
    remaining = {kind: list(paths) for kind, paths in moved.items()}
    notes: list[str] = []

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
        requests = [f"HEAD:./{r}" for r in kept + gone]
        if base_head is not None:
            requests += [f"{base_head}:./{r}" for r in gone]
        answers = _git_objects(root, requests)
        if answers is None:
            notes.append("git could not be asked, so committed content was not checked")
        else:
            at_head = dict(zip(kept + gone, answers[:len(kept) + len(gone)]))
            at_base = dict(zip(gone, answers[len(kept) + len(gone):])) if base_head is not None else {}
            for kind in ("changed", "added"):
                remaining[kind] = [r for r in remaining[kind] if not _blob_holds(at_head.get(r), present(r))]
            remaining["removed"] = [
                r for r in gone
                if not (at_head.get(r) is None
                        and (at_base.get(r) is not None or before[r][2] in known.get(r, ())))]
    return remaining, notes


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
    result is judged once they are done."""
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
            unmoved = (snapshot(root, peek["files"], peek["taken_ns"]) == peek["files"]
                       and head == peek["head"] and watched_prefixes(root) == peek["watched"])
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
        try:
            after = snapshot(root, before, record["taken_ns"])
        except WatchSetTooLarge as exc:
            with contextlib.suppress(OSError):
                write_baseline(path, new_baseline(root, {}, taken, disabled=str(exc)))
            return {"status": "off", "reason": str(exc)}
        if watched_changed:
            # A path that left the watched set did not disappear, and one that
            # joined it did not appear: compare only what both sets watch.
            common = [p for p in watched_now if p in record["watched"]]
            before = _restrict(before, common)
            compare_after = _restrict(after, common)
        else:
            compare_after = after
        moved = diff(before, compare_after)
        unaccounted, notes = (account(root, sid, moved, before, compare_after, record["known"],
                                      record["taken_ns"], record["head"])
                              if any(moved.values()) else ({k: [] for k in moved}, []))
        for rel in moved["changed"] + moved["added"]:
            _remember(record["known"], rel, compare_after[rel][2])
        during, between = split_by_call(root, unaccounted, compare_after, call_start)
        told = set(record["told"])
        keys = [_tell_key(r, compare_after) for kind in ("changed", "added", "removed")
                for r in unaccounted[kind]]
        operator = [k.rsplit("@", 1)[0] for k in keys if k not in told]
        record.update(files=after, taken_ns=taken, head=head, watched=watched_now,
                      told=sorted(told | set(keys)))
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
