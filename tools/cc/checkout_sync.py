#!/usr/bin/env python3
"""Keep this machine's checkout current and its leftover worktrees gone.

Why this exists
---------------
A lane ships with auto-merge armed and the session ends; the pull request
merges later, while nobody is watching. The next session then opens on the
finished branch, behind ``main`` by everything that merged since, and the
hooks it runs are the old ones. Measured 2026-10-08 on the Windows clone: the
main checkout sat on a merged branch 348 commits behind, so the banner, the
memory digest and the hooks themselves were the 10-04 build; and 24 worktrees
under ``.claude/worktrees/`` were left behind by lane agents and background
sessions, younger than Claude Code's own ``cleanupPeriodDays`` sweep. The
operator's words: the checkout "should be as up to date as possible
automatically", and a session should not leave old worktrees behind.

Two jobs, each touching nothing unless every safety condition holds:

* :func:`catch_up` -- one bounded ``git fetch --prune``; then it moves only
  the default branch itself (fast-forward) or a branch whose upstream is
  ``[gone]`` (GitHub deleted it at the merge) and whose every commit is in
  ``origin/<default>``, and only with no tracked edits, no merge, rebase,
  cherry-pick, revert, sequence or bisect in progress, no plan in progress,
  no other live session in this checkout, and a local default branch origin
  already contains. The move is one git command (``switch -C <default>
  --track origin/<default>``, which git itself refuses over a local change),
  started only with time left for it and never killed: a move still running
  at its wait is left to finish and named. A detached HEAD, a lane with work
  of its own, or a branch whose remote still exists is named, never moved.
* :func:`reap_worktrees` -- a registered worktree under ``.claude/worktrees/``
  is removed only when it is clean, its HEAD is in ``origin/<default>``, any
  lock names a dead pid, no plan in it is in progress, every ignored file in
  it is a cache, a byte-identical copy of the root's, or session state saved
  first, and **no live session is in it**. Liveness reads Claude Code's own
  session registry (``~/.claude/sessions/<pid>.json``, and the same under
  ``$CLAUDE_CONFIG_DIR``), whose entries carry each running session's
  ``cwd``: an idle session leaves no file-write trace, so a recency scan
  cannot see it (the 2026-10-08 one-off cleanup removed the worktree an idle
  background session sat in for exactly that reason). A registry that cannot
  be read in full, or (in the hook) one that does not list the session
  asking, reaps nothing. On Windows a folder a process holds open is kept.
  While another session is live in the root checkout nothing is reaped.

Network and read-only git calls take their timeouts from one deadline, so
the SessionStart hook stays inside its budget; a call that changes the tree
(the move, a removal) is started only with time left and is never killed.
Nothing here raises to the caller for a git or filesystem failure: it comes
back as a held outcome with the reason.

Verbs::

    python tools/cc/checkout_sync.py            # what a session start would do (dry run)
    python tools/cc/checkout_sync.py --apply    # do it now
    python tools/cc/checkout_sync.py --json     # the same, as JSON

Stdlib-only (``tools/cc/`` runs standalone, zero espalier imports).
Operator-facing text is 7-bit ASCII. Exit 0 on success (a held outcome
included), 2 on a usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import IO, Callable

# Sibling import via this script's own directory (session_summary.py's
# pattern): it resolves the same way when the hooks load this file by path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _json_safe import os_error_text  # noqa: E402

REMOTE = "origin"
WORKTREES_REL = (".claude", "worktrees")
FETCH_CAP_S = 3.0       # one fetch, killed at this (its output goes to files, so the kill returns)
GIT_CAP_S = 2.0         # one local, read-only git question
MOVE_FLOOR_S = 2.0      # never START the move with less than this left
MOVE_WAIT_S = 6.0       # wait this long for the move, then leave it running (measured 0.43-0.52 s for 430 files)
REMOVE_FLOOR_S = 1.0    # never START a removal with less than this left
REMOVE_WAIT_S = 6.0     # wait this long for a removal, then leave it running (measured 0.33 s for 1,183 files)
MIN_SPAWN_S = 0.2       # less than this left: do not spawn at all
NAMES_SHOWN = 3         # per banner clause, then "and N more"

# Paths under the git dir that mean an operation is half done. A switch in the
# middle of any of them would strand the operator's work.
_MID_OPERATION = (
    ("MERGE_HEAD", "a merge"), ("rebase-merge", "a rebase"), ("rebase-apply", "a rebase"),
    ("CHERRY_PICK_HEAD", "a cherry-pick"), ("REVERT_HEAD", "a revert"),
    ("sequencer", "a cherry-pick or revert sequence"), ("BISECT_LOG", "a bisect"),
)
_GIT_ENV_OVERRIDES = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES",
)
# Claude Code's lock reason names the holder: "claude agent agent-a3cc... (pid 25468)".
_LOCK_PID_RE = re.compile(r"\(pid (\d+)\)")

# Ignored content a removal may take with it. Anything ignored and not named
# here keeps the worktree: a `TP-*.md` draft, an `espalier_*.md` note, a
# `.env`, a session-archive copy (all ignored on this tree).
# Tool caches and per-session state the stack table does not carry; each
# stack's dependency and build-output directories come from the table itself.
# stack-table: ok purpose-scoped -- tool caches, virtualenvs and per-session state a removal may take;
# none is a stack's dependency or output directory, which come from the table below
_TOOL_CACHE_DIR_NAMES = frozenset({
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis",
    ".tox", ".nox", ".venv", "venv", "htmlcov", ".eggs", ".espalier-state",
})
try:
    import _stack_table  # noqa: E402 -- the deployed sibling; absent, nothing more is disposable (keeps more)

    _DISPOSABLE_DIR_NAMES = _TOOL_CACHE_DIR_NAMES | _stack_table.dependency_dirs() | _stack_table.output_dirs()
except ImportError:  # fail-open: ok deliberate -- without the table a dependency dir keeps the worktree, the safe side
    _DISPOSABLE_DIR_NAMES = _TOOL_CACHE_DIR_NAMES
_DISPOSABLE_TOPS = frozenset({".espalier", "reports", "dist"})   # regenerable machine-local state and outputs
_DISPOSABLE_SUFFIXES = (".pyc", ".pyo", ".egg-info", ".coverage")
# Files `.worktreeinclude` copies in: disposable when byte-identical to the root's.
_COPIED_FROM_ROOT = (".claude/settings.json", ".claude/settings.local.json", ".local-codenames.txt")
_PLAN_REL = ("cc", "execution_plan.json")
_ARCHIVE_REL = ("cc", "blueprints", "compact_summaries")
_SAVED_REL = ("cc", "blueprints", "from-worktrees")

Runner = Callable[..., "subprocess.CompletedProcess[str] | None"]


# -- the outcomes ------------------------------------------------------------

@dataclass
class CatchUp:
    """What :func:`catch_up` did. ``state`` is one of ``current`` (nothing to
    do), ``caught_up``, ``would_catch_up`` (dry run), ``moving`` (the move is
    still running; ``reason`` names its pid), ``held`` (unsafe or failed;
    ``reason`` and ``remedy`` say why and what to run), ``lane`` (named, left
    as is) or ``skipped`` (no origin, no default branch: nothing to say)."""
    state: str
    branch: str = ""
    base: str = ""
    behind: int = 0
    ahead: int = 0
    head: str = ""
    reason: str = ""
    remedy: str = ""
    deleted_branch: str = ""
    detached: bool = False
    fetched: bool = True
    changed: list[str] = field(default_factory=list)


@dataclass
class Reap:
    """What :func:`reap_worktrees` did: ``removed`` names, ``kept`` as
    (name, reason) with ``kept_paths`` beside them, ``deferred`` (not reached
    this session, out of time), ``saved`` (paths written into the root),
    ``would_remove`` (dry run) and a ``note`` for a reason that kept every
    worktree."""
    removed: list[str] = field(default_factory=list)
    kept: list[tuple[str, str]] = field(default_factory=list)
    kept_paths: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    saved: list[str] = field(default_factory=list)
    would_remove: list[str] = field(default_factory=list)
    note: str = ""

    def keep(self, path: Path, reason: str) -> None:
        self.kept.append((path.name, reason))
        self.kept_paths.append(str(path))


# -- processes -----------------------------------------------------------------

def git_env() -> dict[str, str]:
    """This process's environment minus the repo-selecting overrides, with
    every credential prompt off: ``GIT_TERMINAL_PROMPT=0`` for git's own and
    ``GCM_INTERACTIVE=never`` for Git Credential Manager, whose sign-in
    window would otherwise hold a fetch (and the hook) open."""
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_OVERRIDES}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    return env


def _left(deadline: float | None, cap: float) -> float:
    return cap if deadline is None else min(cap, deadline - time.monotonic())


def run(argv: list[str], *, cwd: Path, timeout: float) -> "subprocess.CompletedProcess[str] | None":
    """One short read-only subprocess, killed at ``timeout``, or None when it
    could not start or ran out of time. Through :func:`spawn`, so its output
    goes to files and a kill on Windows never waits on a pipe a helper holds."""
    done = spawn(argv, cwd=cwd, wait=timeout, kill=True)
    if done is None or not done.done:
        return None
    return subprocess.CompletedProcess(argv, done.returncode, done.stdout, done.stderr)


@dataclass
class Spawned:
    """A process run through :func:`spawn`: ``done`` False means it was still
    running at the wait and was left to finish (``pid`` names it)."""
    done: bool
    returncode: int = -1
    stdout: str = ""
    stderr: str = ""
    pid: int = 0


def spawn(argv: list[str], *, cwd: Path, wait: float | None, kill: bool) -> Spawned | None:
    """Run ``argv`` with its output in temporary files, not pipes, and wait up
    to ``wait`` seconds (None: until it ends). At the wait, ``kill`` decides:
    a fetch is killed (and, with no pipe to drain, the kill returns at once,
    where ``subprocess.run`` would wait on a credential helper still holding
    its pipe); a command that changes the tree is NEVER killed -- a switch cut
    off mid-write leaves ``index.lock`` and a half-moved tree -- and comes back
    ``done=False`` to be named. None when it could not start."""
    try:
        out = tempfile.TemporaryFile()
        err = tempfile.TemporaryFile()
    except OSError:  # fail-open: ok deliberate -- no temp file means no spawn; the caller holds
        return None
    with out, err:
        try:
            # subprocess-contract: ok the argv is the caller's by design (every read-only git question, the fetch, the move, a removal); each is pinned by tests/test_checkout_sync.py's real-git cases, the kill policy through the injectable spawner
            proc = subprocess.Popen(  # spawn: ok output to files; a fetch is killed at its cap, a tree change never is
                argv, cwd=str(cwd), stdout=out, stderr=err, stdin=subprocess.DEVNULL, env=git_env(),
            )
        except OSError:  # fail-open: ok deliberate -- a git that cannot start comes back as a held outcome
            return None
        try:
            code = proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            if not kill:
                return Spawned(done=False, pid=proc.pid)
            proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- a process that outlives its kill is the OS's now
                pass
            return None

        def _read(handle: IO[bytes]) -> str:
            handle.seek(0)
            return handle.read().decode("utf-8", "replace")

        return Spawned(done=True, returncode=code, stdout=_read(out), stderr=_read(err), pid=proc.pid)


class _Git:
    """git at one directory under one deadline. ``ask`` returns the completed
    process or None (no budget left, or git could not run)."""

    def __init__(self, cwd: Path, deadline: float | None, runner: Runner = run,
                 spawner: Callable[..., Spawned | None] = spawn):
        self.cwd, self.deadline, self.runner, self.spawner = cwd, deadline, runner, spawner

    def ask(self, *args: str, cap: float = GIT_CAP_S) -> "subprocess.CompletedProcess[str] | None":
        timeout = _left(self.deadline, cap)
        if timeout < MIN_SPAWN_S:
            return None
        return self.runner(["git", *args], cwd=self.cwd, timeout=timeout)

    def out(self, *args: str, cap: float = GIT_CAP_S) -> str | None:
        """stdout stripped on rc 0, else None."""
        r = self.ask(*args, cap=cap)
        return r.stdout.strip() if r is not None and r.returncode == 0 else None

    def yes(self, *args: str) -> bool | None:
        """rc 0 -> True, rc 1 -> False, anything else (or no answer) -> None."""
        r = self.ask(*args)
        if r is None:
            return None
        return True if r.returncode == 0 else False if r.returncode == 1 else None

    def fetch(self, remote: str) -> bool:
        """One ``fetch --prune``, killed at its cap; True when it landed.
        ``--prune`` drops the remote-tracking ref of a branch GitHub deleted at
        the merge, which is what lets a merged lane read as ``[gone]``. A
        fetch cut off while it writes refs can leave a ``.lock`` under
        ``.git/refs`` (docs/HOOK_ASSUMPTIONS.md, Assumption 6)."""
        wait = _left(self.deadline, FETCH_CAP_S)
        if wait < MIN_SPAWN_S:
            return False
        done = self.spawner(["git", "-c", "credential.interactive=never", "fetch", "--quiet", "--prune",
                             "--no-tags", remote], cwd=self.cwd, wait=wait, kill=True)
        return done is not None and done.done and done.returncode == 0

    def change(self, *args: str, wait: float) -> Spawned | None:
        """A command that changes the tree: waited on, never killed."""
        return self.spawner(["git", *args], cwd=self.cwd, wait=wait, kill=False)


def _err(r: "subprocess.CompletedProcess[str] | Spawned | None") -> str:
    if r is None:
        return "git did not answer in time"
    text = (r.stderr.strip() or r.stdout.strip()).splitlines()
    return _ascii(text[-1][:160]) if text else f"git exited {r.returncode}"


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


# -- paths and processes ---------------------------------------------------------

def _norm(path: str | Path) -> str:
    """A comparable spelling: absolute, symlinks resolved, forward slashes,
    case folded (``normcase`` folds nothing on macOS, whose default APFS
    volume is case-insensitive; folding there too errs toward a match, which
    only ever keeps more)."""
    try:
        real = os.path.realpath(str(path))
    except (OSError, ValueError):  # fail-open: ok deliberate -- an unresolvable path compares by its own spelling
        real = os.path.abspath(str(path))
    return os.path.normcase(real).replace("\\", "/").rstrip("/").casefold()


def within(child: str | Path, parent: str | Path) -> bool:
    """Is ``child`` ``parent`` or inside it? A ``...``-prefixed ``child`` is
    a tail-capped path (the session markers record one): it matches when the
    parent's own folder name is one of its components."""
    text = str(child)
    if not text:
        return False
    if text.startswith("..."):
        leaf = _norm(parent).rsplit("/", 1)[-1]
        return f"/{leaf}/" in text.replace("\\", "/").casefold().rstrip("/") + "/"
    c, p = _norm(text), _norm(parent)
    return c == p or c.startswith(p + "/")


def pid_alive(pid: object) -> bool | None:
    """True when the process runs, False when it is gone, None when this host
    cannot tell (callers read None as alive: a deletion fails closed). Never
    ``os.kill(pid, 0)`` on Windows, where signal 0 is CTRL_C_EVENT and would
    interrupt the process instead of asking about it."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists; it is someone else's
    except OSError:  # fail-open: ok deliberate -- an answer we cannot read is "cannot tell", which callers treat as alive
        return None
    return True


def _pid_alive_windows(pid: int) -> bool | None:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_invalid_parameter = 87  # no process has this id
    error_access_denied = 5       # one does; we may not open it
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            err = ctypes.get_last_error()  # type: ignore[attr-defined]
            if err == error_invalid_parameter:
                return False
            return True if err == error_access_denied else None
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, AttributeError, ValueError):  # fail-open: ok deliberate -- no answer is "cannot tell", read as alive
        return None


def _parent_map() -> dict[int, int]:
    """pid -> parent pid for every process on the host, in one read; {} when
    the table cannot be read. Windows: a Toolhelp32 snapshot (no spawn);
    elsewhere: one ``ps``."""
    if os.name == "nt":
        return _parent_map_windows()
    r = run(["ps", "-A", "-o", "pid=,ppid="], cwd=Path.cwd(), timeout=GIT_CAP_S)
    table: dict[int, int] = {}
    if r is None or r.returncode != 0:
        return table
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = int(parts[1])
    return table


def _parent_map_windows() -> dict[int, int]:
    return {pid: ppid for pid, (ppid, _name) in _process_table_windows().items()}


def _process_table_windows() -> dict[int, tuple[int, str]]:
    """pid -> (parent pid, executable name) for every process, from one
    Toolhelp32 snapshot (no spawn); {} when the table cannot be read."""
    import ctypes
    from ctypes import wintypes

    class _Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    table: dict[int, tuple[int, str]] = {}
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
        kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Entry))
        kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Entry))
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if not snapshot or snapshot == wintypes.HANDLE(-1).value:
            return table
        try:
            entry = _Entry()
            entry.dwSize = ctypes.sizeof(_Entry)
            more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                table[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), str(entry.szExeFile))
                more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
    except (OSError, AttributeError, ValueError):  # fail-open: ok deliberate -- no table: no ancestor is recognised, which holds rather than moves
        return {}
    return table


def ancestor_pids(depth: int = 8) -> list[int]:
    """This process's ancestors, nearest first, up to ``depth`` levels."""
    table = _parent_map()
    found: list[int] = []
    pid = os.getpid()
    for _ in range(depth):
        parent = table.get(pid) if table else (os.getppid() if pid == os.getpid() else None)
        if not parent or parent in found or parent == pid:
            break
        found.append(parent)
        pid = parent
    return found


def claude_config_dirs() -> list[Path]:
    """Where Claude Code keeps per-user state: ``$CLAUDE_CONFIG_DIR`` when set,
    and ``~/.claude`` (a nested session launched with ``CLAUDE_*`` stripped
    registers under the default even when its parent does not)."""
    dirs: list[Path] = []
    configured = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if configured:
        dirs.append(Path(configured))
    default = Path.home() / ".claude"
    if not any(_norm(d) == _norm(default) for d in dirs):
        dirs.append(default)
    return dirs


def claude_config_dir() -> Path:
    """The primary one of :func:`claude_config_dirs`."""
    return claude_config_dirs()[0]


def live_sessions(config_dir: Path | None = None) -> list[dict[str, object]] | None:
    """The running Claude Code sessions, from Claude Code's own registry: one
    ``{"pid", "session_id", "cwd"}`` per entry whose process is alive (or whose
    liveness this host cannot tell). None when the registry cannot be read in
    full -- the primary directory missing, an entry that does not parse (unless
    its file name is a pid that has exited: a crash's half-written leftover),
    an entry with no ``cwd``, or one whose ``pid`` is not a positive integer --
    because a reader that cannot place every session must not delete
    anything. Undocumented upstream (observed on 2.1.290 and 2.1.294); see
    ``docs/HOOK_ASSUMPTIONS.md`` Assumption 6."""
    bases = [config_dir] if config_dir is not None else claude_config_dirs()
    rows: list[dict[str, object]] = []
    for index, base in enumerate(bases):
        sessions_dir = base / "sessions"
        try:
            if not sessions_dir.is_dir():
                if index == 0:
                    return None
                continue  # the secondary location simply unused
            entries = sorted(sessions_dir.glob("*.json"))
        except OSError:  # fail-open: ok deliberate -- an unreadable registry returns None, which reaps nothing
            return None
        for path in entries:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):  # fail-open: ok deliberate -- judged just below: a dead pid in the name skips it, else "cannot tell"
                stem = path.name.split(".", 1)[0]
                if stem.isdigit() and pid_alive(int(stem)) is False:
                    continue
                return None
            if not isinstance(record, dict):
                return None
            cwd, pid = record.get("cwd"), record.get("pid")
            if not isinstance(cwd, str) or not cwd:
                return None
            if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
                return None  # a shape we do not know is "cannot tell", never "gone"
            if pid_alive(pid) is False:
                continue  # a crashed session's leftover entry
            sid = record.get("sessionId")
            row = {"pid": pid, "session_id": sid if isinstance(sid, str) else "", "cwd": cwd}
            if row not in rows:
                rows.append(row)
    return rows


def own_entry(sessions: list[dict[str, object]], own_session_id: str = "",
              ancestors: list[int] | None = None) -> dict[str, object] | None:
    """The caller's own registry entry: the one whose session id is
    ``own_session_id``, else the one whose pid is the NEAREST of the caller's
    ancestors to appear (a session launched from another session has both as
    ancestors; only the nearer is the caller). None when neither is there --
    in the hook, the sign that this registry does not track this session."""
    if own_session_id:
        for row in sessions:
            if row.get("session_id") == own_session_id:
                return row
    for pid in ancestors if ancestors is not None else ancestor_pids():
        for row in sessions:
            if row.get("pid") == pid:
                return row
    return None


def _is_launcher(name: str) -> bool:
    """A Windows interpreter launcher a hook can run under: a venv's
    ``python.exe`` (a redirector that starts the base interpreter as its
    child, as uv's trampoline does) or the ``py`` launcher."""
    lowered = name.lower()
    return lowered.startswith("python") or lowered in ("py.exe", "pyw.exe")


def window_pid(table: dict[int, tuple[int, str]] | None = None) -> int | None:
    """The pid of the Claude Code process a hook runs under: a window's
    identity, which a ``/clear`` keeps while it mints a new session id, and
    the key the session markers retire a predecessor by. A pid counts when
    Claude Code's session registry has an entry for it
    (``<config>/sessions/<pid>.json``): keyed on the file, not on a process
    name, so an install that runs as ``node`` is placed too, and not on the
    entry's session id, which a clear rewrites on its own schedule.

    The hook's parent counts first: on macOS it is Claude Code itself. On
    Windows a venv's ``python.exe`` is a redirector, so the hook's parent is
    a launcher that exits with it (measured 2026-10-10: a headless session's
    marker recorded 15904 under claude.exe 61444), and that launcher's
    parent counts instead. Exactly one launcher is stepped over, never a
    walk to the nearest registered ancestor. A hook a test suite spawns sits
    under pytest and a shell, so a walk would reach the session running the
    suite and key the test's markers to it. None when neither counts;
    ``table`` is the caller's process table (pid -> (parent, name))."""
    dirs = [base / "sessions" for base in claude_config_dirs()]

    def registered(pid: int) -> bool:
        return pid > 0 and any((directory / f"{pid}.json").is_file() for directory in dirs)

    parent = os.getppid()
    if registered(parent):
        return parent
    if table is None:
        if os.name != "nt":
            return None   # unmeasured off Windows; the caller keeps the parent, the key it had
        table = _process_table_windows()
    grandparent, name = table.get(parent, (0, ""))
    return grandparent if _is_launcher(name) and registered(grandparent) else None


def sessions_in_checkout(sessions: list[dict[str, object]], root: Path) -> list[dict[str, object]]:
    """The sessions working in the checkout at ``root`` itself: their ``cwd``
    is inside it, and not inside a worktree under ``.claude/worktrees/``
    (a session there shares no file with this checkout)."""
    home = root.joinpath(*WORKTREES_REL)
    return [s for s in sessions
            if within(str(s.get("cwd", "")), root) and not within(str(s.get("cwd", "")), home)]


def other_sessions_in_checkout(sessions: list[dict[str, object]], root: Path,
                               own_session_id: str = "") -> list[dict[str, object]]:
    """The live sessions sharing the checkout at ``root`` with the caller:
    :func:`sessions_in_checkout` minus the caller's own entry
    (:func:`own_entry`) and nothing else."""
    mine = own_entry(sessions, own_session_id)
    return [s for s in sessions_in_checkout(sessions, root) if s is not mine]


def lock_holder_dead(reason: str) -> bool:
    """True when a worktree lock's reason names its holder the way Claude Code
    writes it (``claude agent <id> (pid N)``) and process N has exited. A lock
    with no pid (one you set yourself) is never dead: it is someone's choice."""
    held = _LOCK_PID_RE.search(reason or "")
    return held is not None and pid_alive(int(held.group(1))) is False


def plan_in_progress(tree: Path) -> bool:
    """``cc/execution_plan.json`` in ``tree`` reads ``in_progress``; an
    unreadable one counts as in progress (keep, never guess)."""
    path = tree.joinpath(*_PLAN_REL)
    if not path.is_file():
        return False
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # fail-open: ok deliberate -- an unreadable plan is treated as open
        return True
    return not isinstance(record, dict) or record.get("status") == "in_progress"


# -- catch-up ----------------------------------------------------------------------

def default_branch(git: _Git, remote: str = REMOTE) -> str | None:
    """The remote's default branch name (``main``), from ``<remote>/HEAD``
    when the clone recorded it AND its target still exists, else ``main`` or
    ``master`` when the remote-tracking ref exists. None when neither is
    there. ``<remote>/HEAD`` dangles more often than it looks: a clone taken
    from a checkout that was on a lane branch points it at that lane, and a
    ``--prune`` fetch drops the lane but not the symref (driven 2026-10-08)."""
    head = git.out("symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD")
    if head and head.startswith(f"{remote}/") and git.yes(
            "show-ref", "--verify", "--quiet", f"refs/remotes/{head}"):
        return head[len(remote) + 1:]
    for name in ("main", "master"):
        if git.yes("show-ref", "--verify", "--quiet", f"refs/remotes/{remote}/{name}"):
            return name
    return None


def _mid_operation(git: _Git) -> str | None:
    """The half-done operation in this checkout, by name, or None. A git that
    cannot answer reads as one in progress (hold, never guess). One spawn:
    ``rev-parse`` prints one line per ``--git-path``."""
    args: list[str] = []
    for name, _what in _MID_OPERATION:
        args += ["--git-path", name]
    listing = git.out("rev-parse", *args)
    lines = listing.splitlines() if listing is not None else []
    if len(lines) != len(_MID_OPERATION):
        return "an operation git could not rule out"
    for rel, (_name, what) in zip(lines, _MID_OPERATION):
        target = Path(rel) if Path(rel).is_absolute() else git.cwd / rel
        if target.exists():
            return what
    return None


def _checked_out_elsewhere(git: _Git, branch: str) -> str | None:
    """The path of another worktree that has ``branch`` checked out, or None."""
    listing = git.out("worktree", "list", "--porcelain")
    if listing is None:
        return None
    here = _norm(git.cwd)
    for block in parse_worktrees(listing):
        if block.get("branch") == f"refs/heads/{branch}" and _norm(block.get("worktree", "")) != here:
            return block.get("worktree")
    return None


def _upstream_gone(git: _Git, branch: str) -> bool:
    track = git.out("for-each-ref", "--format=%(upstream:track)", f"refs/heads/{branch}")
    return track == "[gone]"


def catch_up(root: Path, *, deadline: float | None = None, other_session: str = "",
             plan_open: bool = False, dry_run: bool = False, remote: str = REMOTE,
             runner: Runner = run, spawner: Callable[..., Spawned | None] = spawn) -> CatchUp:
    """Bring the checkout at ``root`` up to ``<remote>/<default>`` when, and
    only when, nothing can be lost (the module docstring has the rules).
    ``other_session`` names a live session sharing this checkout ('' for
    none) and ``plan_open`` says a plan is in progress; either holds. Never
    raises."""
    git = _Git(root, deadline, runner, spawner)
    has_remote = git.ask("remote", "get-url", remote)
    if has_remote is None:
        return CatchUp("held", reason="git did not answer in time", fetched=False,
                       remedy=f"git pull --ff-only {remote}")
    if has_remote.returncode != 0:
        return CatchUp("skipped", reason=f"no {remote} remote")
    fetched = git.fetch(remote)
    base = default_branch(git, remote)
    if base is None:
        return CatchUp("skipped", reason=f"no default branch on {remote}", fetched=fetched)
    upstream = f"{remote}/{base}"
    remedy = f"git switch {base} && git pull --ff-only {remote} {base}"
    branch = git.out("symbolic-ref", "--quiet", "--short", "HEAD") or ""
    behind_text = git.out("rev-list", "--count", f"HEAD..{upstream}")
    ahead_text = git.out("rev-list", "--count", f"{upstream}..HEAD")
    if behind_text is None or ahead_text is None:
        return CatchUp("held", branch=branch, base=base, reason=f"git could not compare with {upstream}",
                       remedy=remedy, fetched=fetched)
    behind, ahead = int(behind_text), int(ahead_text)
    result = CatchUp("current", branch=branch, base=base, behind=behind, ahead=ahead, fetched=fetched)
    if behind == 0:
        return result  # nothing to gain: a lane created a moment ago stays put
    if branch != base:
        gone = bool(branch) and ahead == 0 and _upstream_gone(git, branch)
        if not gone:
            # Work of its own, a remote branch that still exists, no upstream
            # at all, or a detached HEAD: someone's choice. Named, never moved.
            result.state = "lane"
            if branch and ahead == 0:
                result.reason = "its remote branch still exists" if git.out(
                    "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}") else "nothing of its own yet"
            return result
    elif ahead:
        result.state = "lane"
        result.reason = f"local {base} has {_plural(ahead, 'commit')} {upstream} does not"
        return result
    holds = []
    if other_session:
        holds.append(f"another live session is in this checkout ({other_session})")
    if plan_open:
        holds.append("a plan is in progress (cc/execution_plan.json)")
    operation = _mid_operation(git)
    if operation:
        holds.append(f"{operation} is in progress")
    edits = git.out("status", "--porcelain", "--untracked-files=no")
    if edits is None:
        holds.append("git could not read the working tree")
    elif edits:
        holds.append(f"{_plural(len(edits.splitlines()), 'uncommitted change')} to tracked files")
    has_local = git.yes("show-ref", "--verify", "--quiet", f"refs/heads/{base}")
    if has_local is None:
        holds.append(f"git could not say whether a local {base} exists")
    elif has_local and git.yes("merge-base", "--is-ancestor", f"refs/heads/{base}", upstream) is not True:
        holds.append(f"local {base} has commits {upstream} does not")
    if holds:
        result.state = "held"
        result.reason = "; ".join(holds)
        if other_session:
            result.remedy = (f"end the other session first ({other_session}; `claude daemon stop` ends a "
                             f"background one), then: {remedy}")
        elif operation or edits:
            result.remedy = "finish or stash that, then: " + remedy
        else:
            result.remedy = remedy
        return result
    if dry_run:
        result.state = "would_catch_up"
        return result
    if _left(deadline, MOVE_FLOOR_S) < MOVE_FLOOR_S:
        result.state = "held"
        result.reason = "out of time this session"
        result.remedy = f"the next session does it, or: {remedy}"
        return result
    old = git.out("rev-parse", "HEAD") or ""
    elsewhere = _checked_out_elsewhere(git, base) if branch != base else None
    if elsewhere:
        result.detached = True
        moved = git.change("switch", "--quiet", "--detach", upstream, wait=MOVE_WAIT_S)
    else:
        # One command, so there is no half-way state between a switch and a
        # merge; -C is safe because local <base> is in upstream (checked above).
        moved = git.change("switch", "--quiet", "-C", base, "--track", upstream, wait=MOVE_WAIT_S)
    if moved is not None and not moved.done:
        result.state = "moving"
        result.reason = (f"the move to {upstream} is still running (git pid {moved.pid}); it finishes on "
                         "its own -- the lines below may describe the tree before it")
        return result
    if moved is None or moved.returncode != 0:
        result.state = "held"
        result.reason = f"the move failed: {_err(moved)}"
        result.remedy = remedy
        return result
    tip = git.out("rev-parse", "--short", "HEAD") or ""
    if (git.out("rev-parse", "HEAD") or "x") != (git.out("rev-parse", upstream) or "y"):
        result.state = "held"
        result.reason = f"after the move HEAD is {tip or 'unknown'}, not {upstream}"
        result.remedy = remedy
        return result
    result.state, result.head = "caught_up", tip
    if old:
        changed = git.out("diff", "--name-only", old, "HEAD")
        result.changed = changed.splitlines() if changed else []
    if branch and branch != base:
        dropped = git.ask("branch", "--quiet", "-d", branch)
        if dropped is not None and dropped.returncode == 0:
            result.deleted_branch = branch
    return result


# -- worktrees -------------------------------------------------------------------

def parse_worktrees(porcelain: str) -> list[dict[str, str]]:
    """``git worktree list --porcelain`` as one dict per block: ``worktree``,
    ``HEAD``, ``branch``, ``locked`` (the reason, or '' for a bare lock),
    ``detached``, ``prunable``. The first block is the main worktree."""
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in porcelain.splitlines() + [""]:
        if not line.strip():
            if current:
                blocks.append(current)
            current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    return blocks


def _disposable(rel: str) -> bool:
    """A cache, a regenerable output, or ``cc/`` session state (saved first)."""
    parts = rel.split("/")
    if parts[0] == "cc" or parts[0] in _DISPOSABLE_TOPS or parts[0].startswith("build"):
        return True
    return any(p in _DISPOSABLE_DIR_NAMES for p in parts) or rel.endswith(_DISPOSABLE_SUFFIXES)


def _ignored_entries(git: _Git) -> list[str] | None:
    """The worktree's ignored entries; None when git cannot list them. A
    directory git collapses (every file in it ignored) is listed by its files
    unless it is disposable as a whole, so a ``.worktreeinclude`` copy inside a
    fully-ignored ``.claude/`` is still compared, not lost unread."""
    listing = git.out("ls-files", "--others", "--ignored", "--exclude-standard", "--directory")
    if listing is None:
        return None
    entries: list[str] = []
    for line in (line for line in listing.splitlines() if line):
        if line.endswith("/") and not _disposable(line.rstrip("/")):
            inside = git.out("ls-files", "--others", "--ignored", "--exclude-standard", "--", line)
            if inside is None:
                return None
            entries += [f for f in inside.splitlines() if f] or [line]
        else:
            entries.append(line)
    return entries


def unsaved_ignored(entries: list[str], worktree: Path, root: Path) -> list[str]:
    """The ignored entries a removal would lose: everything but caches and
    regenerable outputs, ``cc/`` (saved by :func:`save_cc_state` first), and a
    ``.worktreeinclude`` copy byte-identical to the root's."""
    lost: list[str] = []
    for entry in entries:
        rel = entry.rstrip("/")
        if _disposable(rel):
            continue
        if rel in _COPIED_FROM_ROOT:
            try:
                if (worktree / rel).read_bytes() == (root / rel).read_bytes():
                    continue
            except OSError:  # fail-open: ok deliberate -- unreadable means "not the same": keep it
                pass
        lost.append(entry)
    return lost


def _copy_new(src: Path, target: Path) -> Path | None:
    """Copy ``src`` to ``target``, or beside it with a numeric suffix when a
    different file has that name; None when an identical copy is there."""
    if target.exists():
        try:
            if target.read_bytes() == src.read_bytes():
                return None
        except OSError:  # fail-open: ok deliberate -- unreadable means "not the same": write beside it
            pass
        stem, suffix, n = target.stem, target.suffix, 2
        while target.exists():
            target = target.with_name(f"{stem}.{n}{suffix}")
            n += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    return target


def save_cc_state(root: Path, worktree: Path, files: list[str]) -> list[str]:
    """Copy the worktree's ignored ``cc/`` session state (``files``, paths
    relative to the worktree, as ``git ls-files --others --ignored`` lists
    them; tracked files are in git already) into the root, never over a file:
    its compaction legs into the root's archive by their own names, its
    working summary there as ``<worktree>.working-summary.md``, and the rest
    (the blueprint chain, handoff files, plan) under
    ``cc/blueprints/from-worktrees/<worktree>/``. Returns the repo-relative
    paths written. Raises OSError when a copy fails (the caller keeps the
    worktree)."""
    src = worktree / "cc"
    archive = root.joinpath(*_ARCHIVE_REL)
    saved_home = root.joinpath(*_SAVED_REL) / worktree.name
    written: list[str] = []
    for name in sorted(files):
        path = worktree / name
        if not name.startswith("cc/") or not path.is_file():
            continue
        rel = path.relative_to(src)
        if rel.name.endswith(".lock"):
            continue
        if rel.parts[:2] == ("blueprints", "compact_summaries") and len(rel.parts) == 3:
            target = archive / rel.name
        elif rel.as_posix() == "_working_summary.md":
            target = archive / f"{worktree.name}.working-summary.md"
        else:
            target = saved_home / rel
        landed = _copy_new(path, target)
        if landed is not None:
            written.append(landed.relative_to(root).as_posix())
    return written


def held_open(path: Path) -> str:
    """'' when no process holds the folder; else why it stays. Windows only:
    a folder that is some process's cwd (a terminal, an editor's watcher)
    cannot be renamed, so a rename there and back is the probe; elsewhere a
    rename succeeds under an open cwd and proves nothing, so '' (the registry
    and markers are the only liveness there)."""
    if os.name != "nt":
        return ""
    probe = path.with_name(path.name + ".in-use-probe")
    try:
        os.rename(path, probe)
    except OSError:
        return "a process has it open (Windows refused to rename it)"
    try:
        os.rename(probe, path)
    except OSError as e:
        return (f"the in-use probe renamed it to {probe.name} and could not rename it back "
                f"({_ascii(os_error_text(e))[:120]}): rename it back by hand")
    return ""


def _live_marker(path: Path, marker_live: Callable[[Path], bool] | None) -> bool:
    if marker_live is None:
        return False
    try:
        return bool(marker_live(path))
    except Exception:  # noqa: BLE001 -- fail-open: ok deliberate -- a marker check that breaks reads as live (keep the worktree)
        return True


def reap_worktrees(root: Path, *, deadline: float | None = None,
                   sessions: list[dict[str, object]] | None = None,
                   own_cwd: Path | None = None,
                   marker_live: Callable[[Path], bool] | None = None,
                   held_by_other: str = "", unreadable_note: str = "",
                   dry_run: bool = False, remote: str = REMOTE,
                   runner: Runner = run, spawner: Callable[..., Spawned | None] = spawn) -> Reap:
    """Remove the leftover worktrees under ``<root>/.claude/worktrees/`` that
    hold nothing (the module docstring has the rules). ``sessions`` comes from
    :func:`live_sessions` (None: the registry could not be trusted, and then
    nothing is removed; ``unreadable_note`` says why); ``held_by_other`` names
    a live session in the root checkout, which also removes nothing, since
    that session may have entered one of them. Each worktree is named,
    removed or kept with its reason. Never raises."""
    report = Reap()
    git = _Git(root, deadline, runner, spawner)
    listing = git.out("worktree", "list", "--porcelain")
    if listing is None:
        report.note = "git could not list the worktrees"
        return report
    home = root.joinpath(*WORKTREES_REL)
    blocks = [b for b in parse_worktrees(listing)[1:] if b.get("worktree")]
    ours = [b for b in blocks if within(b["worktree"], home)]
    if not ours:
        return report
    blocked = ""
    if sessions is None:
        blocked = unreadable_note or "Claude Code's session registry could not be read"
    elif held_by_other:
        blocked = f"another live session is in this checkout ({held_by_other}) and may be using one"
    if blocked:
        report.note = f"{blocked}, so no worktree was removed"
        for b in ours:
            report.keep(Path(b["worktree"]), "not checked")
        return report
    assert sessions is not None
    base = default_branch(git, remote)
    upstream = f"{remote}/{base}" if base else None
    outside_prunable = any("prunable" in b for b in blocks if b not in ours)
    prune_these: list[str] = []
    for block in ours:
        path = Path(block["worktree"])
        if "prunable" in block and not path.exists() and "locked" not in block:
            if dry_run:
                report.would_remove.append(f"{path.name} (folder already gone)")
            elif outside_prunable:
                report.keep(path, "folder gone; `git worktree prune` clears it (not run: it would also drop "
                                  "a registration outside .claude/worktrees)")
            else:
                prune_these.append(path.name)
            continue
        if _left(deadline, REMOVE_FLOOR_S) < MIN_SPAWN_S * 3:
            report.deferred.append(path.name)
            continue
        reason = _why_kept(git, block, path, upstream, sessions, own_cwd, marker_live, root)
        if reason:
            report.keep(path, reason)
            continue
        if dry_run:
            report.would_remove.append(path.name)
            continue
        if _left(deadline, REMOVE_FLOOR_S) < REMOVE_FLOOR_S:
            report.deferred.append(path.name)
            continue
        busy = held_open(path)
        if busy:
            report.keep(path, busy)
            continue
        cc_files = _Git(path, deadline, runner, spawner).out(
            "ls-files", "--others", "--ignored", "--exclude-standard", "--", "cc")
        if cc_files is None:
            report.keep(path, "git could not list its session notes")
            continue
        try:
            report.saved += save_cc_state(root, path, cc_files.splitlines())
        except OSError as e:
            report.keep(path, f"its session notes could not be saved ({_ascii(os_error_text(e))[:120]})")
            continue
        if "locked" in block:
            git.ask("worktree", "unlock", str(path))
        removal = git.change("worktree", "remove", str(path), wait=REMOVE_WAIT_S)
        if removal is not None and not removal.done:
            report.keep(path, f"its removal is still running (git pid {removal.pid}); it finishes on its own")
            continue
        after = git.out("worktree", "list", "--porcelain")
        still_registered = after is None or any(
            _norm(b.get("worktree", "")) == _norm(path) for b in parse_worktrees(after))
        if still_registered:
            report.keep(path, f"git did not remove it: {_err(removal)}")
            continue
        if path.exists():
            # git dropped the registration but the folder stayed: on Windows a
            # process with the folder as its cwd holds it open.
            report.keep(path, "unregistered, but the folder could not be deleted (a process may have it open)")
            continue
        report.removed.append(path.name)
        branch = block.get("branch", "")
        if branch.startswith("refs/heads/") and upstream:
            short = branch[len("refs/heads/"):]
            if short != base and git.yes("merge-base", "--is-ancestor", branch, upstream):
                git.ask("branch", "--quiet", "-D", short)
    if prune_these:
        # Only when every prunable registration is one of ours: the prune is
        # repository-wide (and a removal above already dropped its own record).
        pruned = git.ask("worktree", "prune")
        if pruned is not None and pruned.returncode == 0:
            report.removed += [f"{name} (folder already gone)" for name in prune_these]
    return report


def _why_kept(git: _Git, block: dict[str, str], path: Path, upstream: str | None,
              sessions: list[dict[str, object]], own_cwd: Path | None,
              marker_live: Callable[[Path], bool] | None, root: Path) -> str:
    """'' when the worktree may go; else the reason it stays, in words."""
    if own_cwd is not None and within(own_cwd, path):
        return "this session is in it"
    for row in sessions:
        if within(str(row.get("cwd", "")), path):
            pid = row.get("pid")
            return "a live Claude session is in it" + (f" (pid {pid})" if pid else "")
    if _live_marker(path, marker_live):
        return "a session marker in it was touched recently"
    if "locked" in block:
        held = _LOCK_PID_RE.search(block.get("locked", ""))
        if not held:
            return "locked by hand (git worktree unlock releases it)"
        if not lock_holder_dead(block.get("locked", "")):
            return f"locked by a running process (pid {held.group(1)})"
    if not path.is_dir():
        return "its folder is missing (git worktree prune clears the record)"
    if not (path / ".git").exists():
        return "its .git link is missing (`git worktree repair`, or remove the folder by hand)"
    if upstream is None:
        return "no default branch on origin to compare with"
    if plan_in_progress(path):
        return "a plan in it is still in progress"
    here = _Git(path, git.deadline, git.runner, git.spawner)
    status = here.out("status", "--porcelain")
    if status is None:
        return "git could not read it"
    if status:
        return _plural(len(status.splitlines()), "uncommitted change")
    if _mid_operation(here):
        return "an operation is in progress in it"
    head = block.get("HEAD", "")
    merged = git.yes("merge-base", "--is-ancestor", head, upstream) if head else None
    if merged is None:
        return "git could not compare it with " + upstream
    if not merged:
        ahead = git.out("rev-list", "--count", f"{upstream}..{head}") or "some"
        branch = block.get("branch", "").replace("refs/heads/", "") or "detached"
        return f"{ahead} commit(s) not in main ({branch})"
    ignored = _ignored_entries(here)
    if ignored is None:
        return "git could not list its ignored files"
    lost = unsaved_ignored(ignored, path, root)
    if lost:
        return (f"{_plural(len(lost), 'ignored file')} git status cannot see ({_names(lost)}); move what you "
                "need, then `git worktree remove --force` it")
    return ""


# -- the banner's words ------------------------------------------------------------

def _names(names: list[str]) -> str:
    shown = ", ".join(names[:NAMES_SHOWN])
    return shown + (f", and {len(names) - NAMES_SHOWN} more" if len(names) > NAMES_SHOWN else "")


def checkout_line(result: CatchUp) -> str:
    """The banner's ``Checkout:`` value, or '' when there is nothing to say."""
    stale = "" if result.fetched else " (origin not reached; compared with the last fetch)"
    if result.state == "caught_up":
        left = ""
        if result.branch and result.branch != result.base:
            dropped = ", branch deleted" if result.deleted_branch else ""
            left = f"left {result.branch} (merged{dropped}); "
        where = f"detached at {REMOTE}/{result.base}" if result.detached else f"{result.base} fast-forwarded"
        line = f"caught up -- {left}{where}, {_plural(result.behind, 'commit')}, now {result.head}{stale}"
        if any(p.startswith((".claude/", "tools/cc/hooks/")) or p == "CLAUDE.md" for p in result.changed):
            line += " (hooks or CLAUDE.md changed with it: /clear to load them in this session)"
        return _ascii(line)
    if result.state == "would_catch_up":
        return f"would catch up {_plural(result.behind, 'commit')} from {result.branch or 'HEAD'} to {result.base}"
    if result.state == "moving":
        return _ascii(f"catching up -- {result.reason}")
    if result.state == "held":
        behind = f"{_plural(result.behind, 'commit')} behind {REMOTE}/{result.base}, " if result.behind else ""
        tail = f" -- {result.remedy}" if result.remedy else ""
        return _ascii(f"NOT caught up ({behind}{result.reason}){stale}{tail}")
    if result.state == "lane" and result.behind:
        where = result.branch or "a detached HEAD"
        own = f"{_plural(result.ahead, 'commit')} not in {result.base}" if result.ahead else (
            result.reason or "nothing of its own")
        if result.branch == result.base:
            own = result.reason
        return _ascii(f"on {where} ({own}); {result.base} has {result.behind} newer -- left as is")
    return ""


def worktrees_line(report: Reap) -> str:
    """The banner's ``Worktrees:`` value, or '' when there is nothing to say."""
    parts = []
    if report.removed:
        parts.append(f"removed {_plural(len(report.removed), 'leftover')} (merged, clean): {_names(report.removed)}")
    if report.would_remove:
        parts.append(f"would remove {len(report.would_remove)}: {_names(report.would_remove)}")
    if report.deferred:
        parts.append(f"{len(report.deferred)} more next session (out of time): {_names(report.deferred)}")
    if report.note:
        parts.append(f"{report.note}: {_names([n for n, _ in report.kept])}")
    elif report.kept:
        kept = [f"{name} [{why}]" for name, why in report.kept]
        parts.append(f"kept {len(report.kept)}: {_names(kept)}")
    if report.saved:
        parts.append(f"their session notes saved under cc/blueprints/ ({_plural(len(report.saved), 'file')})")
    return _ascii("; ".join(parts))


# -- the CLI ---------------------------------------------------------------------

def _repo_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    # The main checkout, even when run from inside a linked worktree: the
    # common git dir's parent. `--path-format` needs git 2.31; older gits
    # fall back to this checkout's own top level.
    r = run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=Path.cwd(), timeout=10)
    if r is not None and r.returncode == 0 and Path(r.stdout.strip()).name == ".git":
        return Path(r.stdout.strip()).parent
    r = run(["git", "rev-parse", "--show-toplevel"], cwd=Path.cwd(), timeout=10)
    if r is None or r.returncode != 0:
        raise SystemExit("checkout_sync: not inside a git repository")
    return Path(r.stdout.strip())


def _hook_utils_by_path() -> object | None:
    """The deployed ``hooks/_hook_utils.py`` (the one source of the session
    markers' live window), loaded by path; None where it is not deployed."""
    import importlib.util

    alias = "_checkout_sync_hook_utils"
    module = sys.modules.get(alias)
    if module is not None:
        return module
    path = Path(__file__).resolve().parent / "hooks" / "_hook_utils.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:
        return None
    sys.path.insert(0, str(path.parent))
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module  # registered before exec: a dataclass resolves its module by name
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--apply", action="store_true", help="do it now (default: say what would happen)")
    parser.add_argument("--json", action="store_true", help="print the outcomes as JSON")
    parser.add_argument("--root", help="the main checkout (default: this repository's)")
    args = parser.parse_args(argv)
    root = _repo_root(args.root)
    hook_utils = _hook_utils_by_path()
    sessions = live_sessions()
    note = ""
    if sessions is not None and os.environ.get("CLAUDECODE") and own_entry(sessions) is None:
        # Run from inside a session, the registry must list that session, or it
        # is not the registry this session writes to.
        note = "this session is not in Claude Code's session registry"
        sessions = None
    if sessions is not None:
        others = other_sessions_in_checkout(sessions, root)
        other = f"pid {others[0]['pid']}" if others else ""
    else:
        rows: list[dict[str, object]] = (
            getattr(hook_utils, "other_live_sessions", lambda *_a: [])(root, "") if hook_utils else [])
        other = f"session {str(rows[0].get('session_id', ''))[:8]}" if rows else ""
    plan_open = plan_in_progress(root)
    result = catch_up(root, other_session=other, plan_open=plan_open, dry_run=not args.apply)
    marker_live = None
    if hook_utils is not None:
        marker_live = lambda tree: bool(hook_utils.other_live_sessions(tree, ""))  # type: ignore[attr-defined]  # noqa: E731
    reap = reap_worktrees(root, sessions=sessions, own_cwd=Path.cwd(), marker_live=marker_live,
                          held_by_other=other, unreadable_note=note, dry_run=not args.apply)
    if args.json:
        print(json.dumps({"checkout": asdict(result), "worktrees": asdict(reap)}, indent=2))
        return 0
    print(f"Checkout:  {checkout_line(result) or 'current'}")
    print(f"Worktrees: {worktrees_line(reap) or 'none left over'}")
    if not args.apply:
        print("(dry run; --apply does it)")
    return 0


if __name__ == "__main__":
    from _json_safe import pin_utf8_streams

    pin_utf8_streams()
    sys.exit(main())
