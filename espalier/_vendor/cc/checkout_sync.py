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
  is removed only when it is clean, every commit of its HEAD is in
  ``origin/<default>`` (by ancestry, or, on a branch, which the removal
  keeps, as the same patch under another sha: a cherry-pick), any
  lock names a dead pid, every ignored file in it is a cache, a
  byte-identical copy of the root's, or session state saved first, no seat
  named for the worktree alone still holds a live claim on the mail channel
  (only that name can release it) or a live job from the dispatcher (only
  that seat works it), no process works in it, and **no live
  session is in it**. A plan still open in it keeps a worktree with work in
  it, never a clean, merged one: that lane finished, and the removal names
  the plan that was never closed (DEF-4047). Liveness reads Claude Code's own
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
back as a held outcome with the reason. A read that did not answer (killed
at its cap, or not started for want of time) is never read as a no: an act
resting on it holds, and the outcome counts it (``unanswered``) for the line.

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
import math
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

# A kept, older sibling is named with its repair, never a traceback that names
# an attribute: an uncaught exception loads hooks/_start_refusal.py by path and
# hands it to that module's refuse_kept_siblings. The one text of this block,
# and why each line is there, is tests/test_kept_sibling.py's ARM_BLOCK.
if __name__ == "__main__":
    from types import TracebackType as _KeptTraceback

    _KEPT_FROM = Path(__file__).resolve().parent
    _KEPT_SCRIPT = Path(__file__).name
    _KEPT_BEFORE = sys.excepthook

    def _name_a_kept_sibling(kind: type[BaseException], exc: BaseException, tb: _KeptTraceback | None) -> None:
        sys.excepthook = _KEPT_BEFORE
        try:
            import importlib.util
            at = (_KEPT_FROM if _KEPT_FROM.name == "hooks" else _KEPT_FROM / "hooks") / "_start_refusal.py"
            spec = importlib.util.spec_from_file_location("_start_refusal_by_path", at)
            if spec is not None and spec.loader is not None:
                reader = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = reader
                spec.loader.exec_module(reader)
                refuse = getattr(reader, "refuse_kept_siblings", None)
                if callable(refuse):
                    reconfigure = getattr(sys.stderr, "reconfigure", None)
                    if callable(reconfigure):
                        reconfigure(encoding="utf-8", errors="replace")
                    refuse(_KEPT_SCRIPT)
        # fail-open: ok deliberate without the reader a kept sibling keeps its traceback, as before
        except Exception:  # noqa: BLE001, S110
            pass
        sys.excepthook(kind, exc, tb)

    sys.excepthook = _name_a_kept_sibling

# Sibling import via this script's own directory (session_summary.py's
# pattern): it resolves the same way when the hooks load this file by path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _json_safe import PS_TABLE_ARGV, os_error_text, parse_process_table  # noqa: E402

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
# What _mid_operation answers when git did not list the paths: a hold, never a no.
_UNRULED_OPERATION = "an operation git could not rule out"
_GIT_ENV_OVERRIDES = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES",
)
# Claude Code's lock reason names the holder in one of two forms: "claude agent
# agent-a3cc... (pid 25468)", or with the holder's start time, "claude agent
# agent-aa54... (pid 8671 start Sat Nov  7 02:17:28 2026)" (read 2026-11-10 on
# macOS). Either shape anywhere in a reason names a holder; a reason with
# neither (no pid, or a pid in any other shape) is someone's choice. The start
# tail stops at either parenthesis, so a search stays linear on any reason.
_LOCK_PID_RE = re.compile(r"\(pid (\d+)(?: start [^()]*)?\)")

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
# The one copy of an edit a wedge restore discarded (DEF-3009): the guard's
# start refusal saves it here before it lets the restore through
# (`hooks/_start_refusal.py::_save_before_restore`, under the helper's
# STATE_DIR), inside the state directory that is otherwise a cache to the
# reaper. A worktree holding one is kept, named, until it is read.
_KEPT_STATE_REL = ".espalier-state/wedge-restore"
# The words of the reason a saved edit keeps a worktree with, which the
# Worktrees: line reads to name every such worktree first.
_SAVED_EDIT_WORDS = "a wedge restore discarded"

Runner = Callable[..., "subprocess.CompletedProcess[str] | None"]


# -- the outcomes ------------------------------------------------------------

@dataclass
class CatchUp:
    """What :func:`catch_up` did. ``state`` is one of ``current`` (nothing to
    do), ``caught_up``, ``would_catch_up`` (dry run), ``moving`` (the move is
    still running; ``reason`` names its pid), ``held`` (unsafe or failed;
    ``reason`` and ``remedy`` say why and what to run), ``lane`` (named, left
    as is) or ``skipped`` (no origin, no default branch: nothing to say).
    ``unanswered`` counts the git reads that did not answer (DEF-2046), and
    ``changed_unread`` says what a move changed could not be read."""
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
    unanswered: int = 0
    changed_unread: bool = False


@dataclass
class Reap:
    """What :func:`reap_worktrees` did: ``removed`` names, ``kept`` as
    (name, reason) with ``kept_paths`` beside them, ``deferred`` (not reached
    this session, out of time), ``saved`` (paths written into the root),
    ``would_remove`` (dry run), ``unlocked`` (a dead holder's lock released
    before its removal, as ``name (pid N)``; not on the banner line), a
    ``note`` for a reason that kept every worktree and ``unanswered``, the git
    reads that did not answer (DEF-2046)."""
    removed: list[str] = field(default_factory=list)
    kept: list[tuple[str, str]] = field(default_factory=list)
    kept_paths: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    saved: list[str] = field(default_factory=list)
    would_remove: list[str] = field(default_factory=list)
    note: str = ""
    unlocked: list[str] = field(default_factory=list)
    unanswered: int = 0

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
    process or None (no budget left, or git could not run).

    A None is a read that did not answer, never a no: a read killed at its cap
    on a loaded box answered as its success would have, a killed fetch read
    ``current`` and a killed ref read let the catch-up switch a lane whose
    remote branch still exists (DEF-2046). Each one is counted, apart from a
    non-zero exit (git answered), in a tally :meth:`at` shares, so an act can
    wait on every read it rests on and a line can say what did not answer."""

    def __init__(self, cwd: Path, deadline: float | None, runner: Runner = run,
                 spawner: Callable[..., Spawned | None] = spawn, tally: list[int] | None = None):
        self.cwd, self.deadline, self.runner, self.spawner = cwd, deadline, runner, spawner
        self.tally = tally if tally is not None else [0]

    @property
    def unanswered(self) -> int:
        """The reads that did not answer, here and in every :meth:`at` of it."""
        return self.tally[0]

    def at(self, cwd: Path) -> "_Git":
        """git at ``cwd`` under the same deadline, counting into the same tally."""
        return _Git(cwd, self.deadline, self.runner, self.spawner, self.tally)

    def ask(self, *args: str, cap: float = GIT_CAP_S) -> "subprocess.CompletedProcess[str] | None":
        timeout = _left(self.deadline, cap)
        answer = self.runner(["git", *args], cwd=self.cwd, timeout=timeout) if timeout >= MIN_SPAWN_S else None
        if answer is None:
            self.tally[0] += 1
        return answer

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


def _parent_map(timeout: float = GIT_CAP_S) -> dict[int, int] | None:
    """pid -> parent pid for every process on the host, in one read; None
    when the table could not be read: a ``ps`` killed at ``timeout`` or
    failed, or a table with no rows, which no host has (the reader is in
    it). Never {}, which read as a host with no processes, so an ancestor
    walk stopped at the first hop and CP-KILL found no children (DEF-2046).
    Windows: a Toolhelp32 snapshot (no spawn); elsewhere: one ``ps``, in the
    spelling and through the parser the bounded spawn's tree walk reads
    (``_json_safe.PS_TABLE_ARGV``, ``parse_process_table``)."""
    if os.name == "nt":
        return _parent_map_windows()
    r = run(list(PS_TABLE_ARGV), cwd=Path(os.path.abspath("/")), timeout=timeout)
    if r is None or r.returncode != 0:
        return None
    table = parse_process_table(r.stdout)
    return {pid: ppid for pid, (ppid, _group) in table.items()} if table else None


def _parent_map_windows() -> dict[int, int] | None:
    return {pid: ppid for pid, (ppid, _name) in _process_table_windows().items()} or None


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


def ancestry(depth: int = 8) -> tuple[list[int], bool]:
    """This process's ancestors, nearest first, up to ``depth`` levels, and
    whether the process table answered. Where it did not, the parent alone
    is known (read without a spawn) and the walk stops there: a caller that
    finds no session among them cannot tell, never "none" (DEF-2046)."""
    table = _parent_map()
    found: list[int] = []
    pid = os.getpid()
    for _ in range(depth):
        parent = table.get(pid) if table is not None else (os.getppid() if pid == os.getpid() else None)
        if not parent or parent in found or parent == pid:
            break
        found.append(parent)
        pid = parent
    return found, table is not None


#: ancestors_of's default: read the table here. An explicit None is a table
#: the caller could not read, answered None with no second read: a caller
#: older than that hands the None it was given straight back (DEF-2046).
_READ_TABLE = object()


def ancestors_of(pid: int, table: dict[int, int] | None | object = _READ_TABLE,
                 depth: int = 8) -> list[int] | None:
    """``pid``'s ancestors, nearest first, up to ``depth`` levels, from one
    read of the process table (``table`` when the caller holds one, read as
    given); None when the table could not be read."""
    held = _parent_map() if table is _READ_TABLE else table
    if not isinstance(held, dict):
        return None
    table = held
    found: list[int] = []
    seen = {pid}
    for _ in range(depth):
        parent = table.get(pid)
        if not parent or parent in seen:
            break
        found.append(parent)
        seen.add(parent)
        pid = parent
    return found


# -- whose process is it (DEF-4070, DEF-4078, DEF-4079) ---------------------------
#
# Seats on one box share one process table, and a run a seat detached on
# purpose (a tier leg under nohup, the fresh-clone gate) is a process with no
# session in it: on 2026-10-31 one seat ended another's tier, read from the
# table as a stray of its own. This is the one reader of where a process
# works, for the SessionStart `Loose:` line, the CP-KILL speed bump and
# :func:`held_open`: the `/proc/<pid>/cwd` links where the host has them (no
# spawn), else one `lsof` (10 ms for a few pids, about 30 ms for every
# process on macOS, measured 2026-11-02; it exits 1 when any process cannot
# be read and still prints the rest, so its output is read whatever the exit
# code). Windows has neither, and nothing is read there.
_PROC_ROOT = Path("/proc")
CWD_PID_CAP = 32        # pids read by name in one call
CWD_READ_S = 2.0        # one lsof, killed at this
# `lsof` sits in an sbin directory on macOS, which a hook's PATH can leave out.
_LSOF_FALLBACK_DIRS = ("/usr/sbin", "/usr/bin", "/sbin")


def lsof_path() -> str | None:
    """`lsof` from the absolute PATH entries and the fallbacks alone: an empty
    or relative entry is the caller's cwd (a hook's is the checkout), where a
    file named `lsof` would otherwise run."""
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if os.path.isabs(d)]
    found = shutil.which("lsof", path=os.pathsep.join([*dirs, *_LSOF_FALLBACK_DIRS]))
    return found if found is not None and os.path.isabs(found) else None


def parse_lsof_cwds(text: str) -> dict[int, str]:
    """``{pid: cwd}`` from `lsof -Fn` output (``p<pid>``, ``fcwd``, ``n<path>``
    lines); a line of any other shape is skipped."""
    found: dict[int, str] = {}
    pid: int | None = None
    for line in text.splitlines():
        if line[:1] == "p" and line[1:].isascii() and line[1:].isdigit():
            pid = int(line[1:])
        elif line[:1] == "n" and pid is not None and pid not in found:
            found[pid] = line[1:]
    return found


def process_cwds(pids: list[int] | None = None, *, timeout: float = CWD_READ_S) -> dict[int, str] | None:
    """The working directory of each process that can be read, by pid: the
    first `CWD_PID_CAP` of ``pids``, or every process this user can read when
    ``pids`` is None. A pid missing from the result was not read (gone, or
    another user's). {} where nothing is asked or the host has no reader
    (Windows, or neither `/proc` cwd links nor `lsof`); None when the reader
    ran and could not answer (`lsof` did not start, or outran ``timeout``), so
    a caller that removes on an empty answer can tell "none" from "unread"."""
    if pids is not None:
        pids = pids[:CWD_PID_CAP]
        if not pids:
            return {}
    if os.name != "posix":
        return {}
    if (_PROC_ROOT / "self" / "cwd").exists():
        if pids is None:
            try:
                pids = [int(name) for name in os.listdir(_PROC_ROOT) if name.isascii() and name.isdigit()]
            except OSError:  # fail-open: ok deliberate -- a /proc that cannot be listed is a reader that could not answer, and the caller is told so
                return None
        found: dict[int, str] = {}
        for pid in pids:
            try:
                found[pid] = os.readlink(_PROC_ROOT / str(pid) / "cwd")
            except OSError:  # fail-open: ok deliberate -- a link that cannot be read (gone, another user's) leaves that pid unread
                continue
        return found
    lsof = lsof_path()
    if lsof is None:
        return {}
    named = ["-p", ",".join(str(pid) for pid in pids)] if pids is not None else []
    # From the filesystem root: lsof's own cwd is in the table it prints, and
    # the caller's folder may be the very one being asked about.
    result = run([lsof, "-w", "-a", "-d", "cwd", *named, "-Fn"], cwd=Path(os.path.abspath("/")), timeout=timeout)
    if result is None:
        return None
    found = parse_lsof_cwds(result.stdout or "")
    # An lsof that read nothing could not answer: a failed run prints nothing,
    # and a read of every process lists one at least (lsof itself).
    if not found and (result.returncode != 0 or pids is None):
        return None
    return found


def cwd_checkout(cwd: str, checkouts: list[Path]) -> Path | None:
    """The checkout of ``checkouts`` holding a process's working directory
    (the deepest, :func:`checkout_of`), or None: outside them all, or a folder
    since removed. Linux marks a removed folder's link ``(deleted)``; macOS
    `lsof` prints its old path unmarked (measured), which would read as the
    checkout around it, so a cwd that is no folder now is in none."""
    if cwd.endswith(" (deleted)") or not os.path.isdir(cwd):
        return None
    return checkout_of(cwd, checkouts)


def checkout_name(checkout: Path, checkouts: list[Path]) -> str:
    """A checkout spelled as the board spells one: the main checkout, a
    worktree's path under the main checkout's folder, or its own path."""
    main = next((c for c in checkouts if (c / ".git").is_dir()), None)
    if main is not None and (checkout / ".git").is_dir():
        return "the main checkout"
    try:
        return checkout.resolve().relative_to(main.resolve()).as_posix() if main is not None else checkout.as_posix()
    except (OSError, ValueError):   # a worktree outside the main checkout's folder: its own path
        return checkout.as_posix()


def pid_checkout(cwd: str, root: Path, checkouts: list[Path] | None = None) -> tuple[str, bool]:
    """The clause a process's working directory earns, and whether it is in
    ANOTHER checkout of this clone than ``root``: the deepest of
    ``checkouts`` (default :func:`registered_checkouts`) holding it, named by
    :func:`checkout_name` -- for ``root`` too, so a line naming it still reads
    right copied into another window."""
    if cwd.endswith(" (deleted)") or not os.path.isdir(cwd):
        return "cwd deleted", False
    found = list(checkouts) if checkouts is not None else registered_checkouts(root)
    # git did not list them: its registry read off the disk places the pid the
    # same way; where that cannot be read either, whose checkout it is cannot
    # be told, so it is kept out of a paste -- never read as this one (DEF-2046).
    found = found if found is not None else _sibling_places(root)
    if found is None:
        return "cwd's checkout unread: git did not list this clone's checkouts", True
    places = list(found)
    if not any(_norm(c) == _norm(root) for c in places):
        places.append(root)
    home = cwd_checkout(cwd, places)
    if home is None:
        return "cwd outside this clone's checkouts", False
    where = checkout_name(home, places)
    if _norm(home) == _norm(root):
        return f"cwd in this checkout, {where}", False
    return f"cwd in {where}, another checkout of this clone", True


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


def _started_at(value: object) -> float | None:
    """The registry's ``startedAt`` (epoch milliseconds) in epoch seconds, or
    None for any other shape (a non-finite or far-future number included, which
    ``time.gmtime`` would raise on): a courtesy for the words, never a
    liveness fact."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or not 0 < value < 4e12:
        return None
    return float(value) / 1000.0


def _proc_start_windows(pid: int) -> str | None:
    """The process's creation time as the decimal FILETIME Claude Code's
    registry records in ``procStart`` (equal for every live entry read
    2026-10-15 on 2.1.300), or None when it cannot be read."""
    import ctypes
    from ctypes import wintypes

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                return None
            return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, AttributeError, ValueError):  # fail-open: ok deliberate -- an unreadable creation time keeps the entry (read as alive)
        return None


def _pid_reused(pid: int, record: dict) -> bool:
    """True when the registry entry's ``procStart`` names a process other than
    the one now holding ``pid``: a crashed session's entry whose pid Windows
    handed to an unrelated process, which ``pid_alive`` alone reads as live
    for good. Windows only (the field is measured there); False wherever it
    cannot be compared."""
    recorded = record.get("procStart")
    if os.name != "nt" or not isinstance(recorded, str) or not recorded.isdigit():
        return False
    now = _proc_start_windows(pid)
    return now is not None and now != recorded


def live_sessions(config_dir: Path | None = None) -> list[dict[str, object]] | None:
    """The running Claude Code sessions, from Claude Code's own registry: one
    ``{"pid", "session_id", "cwd", "kind", "entrypoint", "started_at"}`` per
    entry whose process is alive (or whose liveness this host cannot tell).
    ``kind`` and ``entrypoint`` are the registry's words ('' when absent): a
    headless ``claude -p`` run registers as kind ``interactive`` with
    entrypoint ``sdk-cli`` (measured 2026-10-15 on 2.1.300, Windows), so the
    entrypoint, not the kind, tells a headless run from a window (``cli``) or
    an editor's (``claude-vscode``). ``started_at`` is epoch seconds or None.
    None when the registry cannot be read in
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
            if pid_alive(pid) is False or _pid_reused(pid, record):
                continue  # a crashed session's leftover entry
            sid, kind, entry = record.get("sessionId"), record.get("kind"), record.get("entrypoint")
            row = {"pid": pid, "session_id": sid if isinstance(sid, str) else "", "cwd": cwd,
                   "kind": kind if isinstance(kind, str) else "",
                   "entrypoint": entry if isinstance(entry, str) else "",
                   "started_at": _started_at(record.get("startedAt"))}
            if row not in rows:
                rows.append(row)
    return rows


#: Why the caller has no registry entry, in the words a line prints: a
#: registry that does not list the session asking is not the one it writes
#: to; a process table that could not be read matched none of the caller's
#: parents, which says nothing about the registry (DEF-2046). ``occupancy``
#: and ``main`` print both; the SessionStart catch-up, the board and the ship
#: driver print TABLE_UNREAD and keep a NOT_LISTED sentence of their own, which
#: a kept older copy of this file must still find in them.
NOT_LISTED = "this session is not in Claude Code's session registry"
TABLE_UNREAD = ("the process table could not be read, so this session could not be found in Claude Code's "
                "session registry")


def own_entry(sessions: list[dict[str, object]], own_session_id: str = "",
              ancestors: list[int] | None = None) -> dict[str, object] | None:
    """The caller's own registry entry: the one whose session id is
    ``own_session_id``, else the one whose pid is the NEAREST of the caller's
    ancestors to appear (a session launched from another session has both as
    ancestors; only the nearer is the caller). None when neither is there --
    in the hook, the sign that this registry does not track this session,
    unless the process table could not be read (:func:`find_own_entry`)."""
    return find_own_entry(sessions, own_session_id, ancestors)[0]


def find_own_entry(sessions: list[dict[str, object]], own_session_id: str = "",
                   ancestors: list[int] | None = None) -> tuple[dict[str, object] | None, bool]:
    """:func:`own_entry`, and whether the process table it walked answered:
    False only for no entry found among ancestors read here from a table
    that could not be read, which is no sign the registry does not track
    this session (:data:`TABLE_UNREAD`, never :data:`NOT_LISTED`)."""
    if own_session_id:
        for row in sessions:
            if row.get("session_id") == own_session_id:
                return row, True
    read = True
    if ancestors is None:
        ancestors, read = ancestry()
    for pid in ancestors:
        for row in sessions:
            if row.get("pid") == pid:
                return row, True
    return None, read


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
        # The entry must be this process's: a crashed session leaves its file
        # behind, and Windows hands the pid out again (an interpreter launcher
        # included). A marker records its window pid as one the registry
        # named, which the Sessions line then reads by its exit, so a stale
        # file must not count: the pid in it must match and its procStart
        # must name the process holding the pid now (``_pid_reused``). An
        # entry that does not read is no answer either.
        if pid <= 0:
            return False
        for directory in dirs:
            path = directory / f"{pid}.json"
            if not path.is_file():
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):  # fail-open: ok deliberate -- an unreadable entry names no window, so the marker's pid is not judged by its exit
                continue
            if isinstance(record, dict) and record.get("pid") == pid and not _pid_reused(pid, record):
                return True
        return False

    parent = os.getppid()
    if registered(parent):
        return parent
    if table is None:
        if os.name != "nt":
            return None   # unmeasured off Windows; the caller keeps the parent, the key it had
        table = _process_table_windows()
    grandparent, name = table.get(parent, (0, ""))
    return grandparent if _is_launcher(name) and registered(grandparent) else None


def _sibling_places(root: Path) -> list[Path] | None:
    """``root`` and every other checkout of its repository, read off the disk
    from git's own worktree registry by the deployed hooks' reader
    (``_hook_utils.sibling_checkouts``: a few small reads, no spawn), for a
    placement with no ``git worktree list`` of its own; None where that
    reader is not deployed beside this script or breaks. A registration
    whose ``.git`` is gone (git reads it prunable) is no checkout: a session
    in its folder counts for the checkout holding the folder."""
    try:
        hook_utils = _hook_utils_by_path()
        reader = getattr(hook_utils, "sibling_checkouts", None) if hook_utils is not None else None
        if not callable(reader):
            return None
        return [root, *(c for c in reader(root) if os.path.exists(os.path.join(c, ".git")))]
    except Exception:  # noqa: BLE001 -- fail-open: ok deliberate -- a reader that breaks leaves the folder rule, which only ever keeps more
        return None


def sessions_in_checkout(sessions: list[dict[str, object]], root: Path) -> list[dict[str, object]]:
    """The sessions working in the checkout at ``root`` itself: their ``cwd``
    is inside it, not inside a worktree under ``.claude/worktrees/`` (a
    session there shares no file with this checkout), and in no deeper
    checkout of the repository (:func:`checkout_of` over
    :func:`_sibling_places`: a worktree nested elsewhere in the folder is its
    own, DEF-3024). Where the siblings cannot be read the folder rule stands
    alone, which only ever keeps more. A ``...``-prefixed cwd (a session
    marker caps one past 120 characters) is kept on :func:`within` alone: its
    folder names cannot tell ``.claude/worktrees`` from any ``worktrees``
    folder, nor place it deeper."""
    home = root.joinpath(*WORKTREES_REL)
    places = _sibling_places(root)
    target = _norm(root)
    kept: list[dict[str, object]] = []
    for s in sessions:
        cwd = str(s.get("cwd", ""))
        if not within(cwd, root):
            continue
        if cwd.startswith("..."):
            kept.append(s)
            continue
        if within(cwd, home):
            continue
        deepest = checkout_of(cwd, places) if places is not None else root
        if deepest is not None and _norm(deepest) == target:
            kept.append(s)
    return kept


def other_sessions_in_checkout(sessions: list[dict[str, object]], root: Path,
                               own_session_id: str = "") -> list[dict[str, object]]:
    """The live sessions sharing the checkout at ``root`` with the caller:
    :func:`sessions_in_checkout` minus the caller's own entry
    (:func:`own_entry`) and nothing else."""
    mine = own_entry(sessions, own_session_id)
    return [s for s in sessions_in_checkout(sessions, root) if s is not mine]


def registered_checkouts(root: Path, *, deadline: float | None = None,
                         runner: Runner = run) -> list[Path] | None:
    """Every checkout git registers for the repository at ``root`` -- the main
    one and each linked worktree, wherever it sits -- or None when git cannot
    list them. A registration whose folder is gone is left out: no session
    can stand in it."""
    listing = _Git(root, deadline, runner).out("worktree", "list", "--porcelain")
    if listing is None:
        return None
    return [Path(b["worktree"]) for b in parse_worktrees(listing)
            if b.get("worktree") and "prunable" not in b]


def checkout_of(cwd: str, checkouts: list[Path]) -> Path | None:
    """The DEEPEST of ``checkouts`` that holds ``cwd`` (a worktree inside the
    main checkout's folder is its own checkout, wherever it sits), or None
    when none does. Paths compare by :func:`within`: normalised and case
    folded, so ``c:\\`` and ``C:\\`` (both spellings are in the registry on
    Windows, read 2026-10-15) name one folder."""
    best: Path | None = None
    depth = -1
    for checkout in checkouts:
        size = len(_norm(checkout))
        if size > depth and within(cwd, checkout):
            best, depth = checkout, size
    return best


def sessions_in(path: Path, *, sessions: list[dict[str, object]] | None = None,
                checkouts: list[Path] | None = None, deadline: float | None = None,
                runner: Runner = run) -> list[dict[str, object]] | None:
    """The live sessions working in the checkout at ``path``: each registry
    entry whose ``cwd`` lies in ``path`` and in no deeper registered checkout.
    ``sessions`` defaults to :func:`live_sessions`, ``checkouts`` to
    :func:`registered_checkouts`; where git cannot list them,
    :func:`sessions_in_checkout` places them (git's registry read off the
    disk, and the reaper's ``.claude/worktrees/`` rule). None
    when the registry cannot be read in full: the caller cannot tell."""
    if sessions is None:
        sessions = live_sessions()
        if sessions is None:
            return None
    if checkouts is None:
        checkouts = registered_checkouts(path, deadline=deadline, runner=runner)
    if checkouts is None:
        return sessions_in_checkout(sessions, path)
    target = _norm(path)
    places = list(checkouts) if any(_norm(c) == target for c in checkouts) else [*checkouts, path]
    found = []
    for row in sessions:
        home = checkout_of(str(row.get("cwd", "")), places)
        if home is not None and _norm(home) == target:
            found.append(row)
    return found


MarkerReader = Callable[[Path], list[dict[str, object]]]


def _default_marker_reader() -> MarkerReader | None:
    hook_utils = _hook_utils_by_path()
    reader = getattr(hook_utils, "other_live_sessions", None) if hook_utils is not None else None
    return (lambda tree: reader(tree, "")) if callable(reader) else None


def marker_sessions(tree: Path, reader: MarkerReader | None = None) -> list[dict[str, object]]:
    """The session markers under ``tree``'s own state directory that may still
    be live: touched within the hooks' window AND not read as exited by the
    hooks' own reader (its ``alive`` is False only for a pid Claude Code's
    registry named when the marker was written; a hook's fallback parent can
    exit while its session runs on, so any other pid counts: it cannot be
    ruled out). Rows in the registry's shape with ``source`` ``marker``; a
    marker that records no cwd stands for ``tree`` itself. [] when no reader
    is deployed or it breaks."""
    reader = reader if reader is not None else _default_marker_reader()
    if reader is None:
        return []
    try:
        found = list(reader(tree))
    except Exception:  # noqa: BLE001 -- fail-open: ok deliberate -- a marker read that breaks adds nobody; the registry still answers
        return []
    rows: list[dict[str, object]] = []
    for r in found:
        pid = r.get("pid")
        if r.get("alive") is False:
            continue
        rows.append({"pid": pid if isinstance(pid, int) else None, "session_id": str(r.get("session_id") or ""),
                     "cwd": str(r.get("cwd") or "") or str(tree), "kind": "", "entrypoint": "",
                     "started_at": None, "source": "marker"})
    return rows


@dataclass
class Occupancy:
    """Who is working in one checkout, and which oracle said so.
    ``sessions`` is None when no oracle could tell (then a caller that would
    delete or launch must refuse); each row's ``source`` is ``registry``
    (Claude Code's own, the one that places an idle session) or ``marker``
    (this harness's per-tree markers, which can only add a session, never
    rule one out). ``oracle`` is ``registry`` when the registry answered,
    ``markers`` when only the markers could, or ''; ``note`` says why the
    registry was not used; ``caller`` is the asking session's own registry
    entry, wherever it is placed (None outside a session or when unknown)."""
    sessions: list[dict[str, object]] | None
    oracle: str
    note: str = ""
    caller: dict[str, object] | None = None

    def from_registry(self) -> list[dict[str, object]]:
        return [r for r in self.sessions or [] if r.get("source") == "registry"]


def caller_entry(sessions: list[dict[str, object]], own_session_id: str = "") -> dict[str, object] | None:
    """The asking session's own registry entry: by the id and window pid a
    session exports to its children (``CLAUDE_CODE_SESSION_ID``,
    ``CLAUDE_PID``; both equal the registry's, read 2026-10-15), then by the
    nearest registered ancestor (:func:`own_entry`)."""
    return find_caller(sessions, own_session_id)[0]


def find_caller(sessions: list[dict[str, object]],
                own_session_id: str = "") -> tuple[dict[str, object] | None, bool]:
    """:func:`caller_entry`, and whether the process table answered, as
    :func:`find_own_entry` says it."""
    sid = own_session_id or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    pid_text = os.environ.get("CLAUDE_PID", "")
    chain, read = ancestry()
    entry, _ = find_own_entry(sessions, sid, ([int(pid_text)] if pid_text.isdigit() else []) + chain)
    return entry, entry is not None or read


def occupancy(path: Path, *, sessions: list[dict[str, object]] | None = None,
              own_session_id: str = "", checkouts: list[Path] | None = None,
              markers: MarkerReader | None = None,
              deadline: float | None = None, runner: Runner = run) -> Occupancy:
    """The one answer to "is a session live in this checkout":
    every session :func:`sessions_in` places at ``path``, the caller's own
    included, plus every live marker (:func:`marker_sessions`) -- in ``path``
    or in the clone's main checkout -- whose cwd is placed there: a session
    that moved into a worktree mid-session keeps its registry cwd and records
    the new one in its marker (SessionStart's reaper reads it the same way).
    The registry is trusted only when it is read in full and, run from inside
    a session (``CLAUDECODE`` set), lists that session. Otherwise the markers
    answer when one is live, and when none is, the answer is "cannot tell",
    never "empty": an idle session touches no marker."""
    note = ""
    if sessions is None:
        sessions = live_sessions()
        if sessions is None:
            note = "Claude Code's session registry could not be read in full"
    caller, read = find_caller(sessions, own_session_id) if sessions is not None else (None, True)
    if sessions is not None and os.environ.get("CLAUDECODE") and caller is None:
        note, sessions = NOT_LISTED if read else TABLE_UNREAD, None
    if checkouts is None:
        checkouts = registered_checkouts(path, deadline=deadline, runner=runner)
    target = _norm(path)
    places = list(checkouts or [])
    if not any(_norm(c) == target for c in places):
        places.append(path)
    if checkouts is not None:
        mains = [c for c in checkouts[:1] if _norm(c) != target]
    else:
        # git did not list them: the clone's main checkout read off the disk
        # (the place whose .git is a folder), whose marker records a session
        # that moved here; where that cannot be read, who is here cannot be told.
        on_disk = [] if os.path.isdir(os.path.join(path, ".git")) else _sibling_places(path)
        if on_disk is None:
            return Occupancy(None, "", "git did not list this clone's checkouts, and its registry could not be read "
                                       "off the disk, so the main checkout's session markers were not read")
        mains = [c for c in on_disk if os.path.isdir(os.path.join(c, ".git")) and _norm(c) != target][:1]
    trees = [path, *mains]
    marked: list[dict[str, object]] = []
    for tree in trees:
        for row in marker_sessions(tree, markers):
            home = checkout_of(str(row["cwd"]), places) if checkouts is not None else (
                path if sessions_in_checkout([row], path) else None)
            # One session once, whichever tree's marker names it.
            if home is not None and _norm(home) == target and not any(
                    (m["session_id"] or m["pid"]) == (row["session_id"] or row["pid"]) for m in marked):
                marked.append(row)
    if sessions is not None:
        # A list git did not give is placed by the folder reader that
        # sessions_in falls to, never asked a second time.
        placed = (sessions_in(path, sessions=sessions, checkouts=checkouts, deadline=deadline, runner=runner)
                  if checkouts is not None else sessions_in_checkout(sessions, path)) or []
        rows = [{**r, "source": "registry"} for r in placed]
        ids = {r["session_id"] for r in rows if r["session_id"]}
        pids = {r["pid"] for r in rows}
        rows += [m for m in marked if m["session_id"] not in ids and m["pid"] not in pids]
        return Occupancy(rows, "registry", note, caller)
    if marked:
        return Occupancy(marked, "markers", note)
    tail = "no session marker answers either, so who is in it cannot be told"
    return Occupancy(None, "", f"{note}; {tail}" if note else tail)


def describe_session(row: dict[str, object]) -> str:
    """One session in words, 7-bit ASCII: ``pid 4242 (cli, started 2026-10-15
    06:01Z)``, as much of it as the oracle knew; a kind other than a window's
    is said (``background`` is a session Claude Code's daemon resumed), and a
    marker's row says it is one."""
    pid = row.get("pid")
    head = f"pid {pid}" if pid else f"session {str(row.get('session_id') or '?')[:8]}"
    kind = str(row.get("kind") or "")
    bits = [str(row.get("entrypoint") or kind)]
    if kind and kind != "interactive" and row.get("entrypoint"):
        bits.append(kind)
    if row.get("source") == "marker":
        bits.append("a session marker")
    raw = row.get("started_at")
    started = (_started_at(raw * 1000)
               if isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw) else None)
    if started is not None:
        bits.append("started " + time.strftime("%Y-%m-%d %H:%MZ", time.gmtime(started)))
    bits = [b for b in bits if b]
    return _ascii(head + (f" ({', '.join(bits)})" if bits else ""))


def lock_holder_dead(reason: str) -> bool:
    """True when a worktree lock's reason names its holder the way Claude Code
    writes it (``claude agent <id> (pid N)``, or ``(pid N start <date>)``) and
    process N has exited. A lock with no pid in either form (one you set
    yourself) is never dead: it is someone's choice."""
    held = _LOCK_PID_RE.search(reason or "")
    return held is not None and pid_alive(int(held.group(1))) is False


def plan_in_progress(tree: Path, merged_and_clean: bool = False) -> bool:
    """``cc/execution_plan.json`` in ``tree`` reads ``in_progress``; an
    unreadable one counts as in progress (keep, never guess). With
    ``merged_and_clean`` (the reaper's reading of a worktree: nothing
    uncommitted, no operation running, its commits in the default branch, by
    ancestry or by patch) no plan
    is in progress: the lane merged, so a plan still open there was never
    closed, and the work is finished whatever it says (DEF-4047: one kept the
    work worktree for six days)."""
    if merged_and_clean:
        return False
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
        return _UNRULED_OPERATION
    for rel, (_name, what) in zip(lines, _MID_OPERATION):
        target = Path(rel) if Path(rel).is_absolute() else git.cwd / rel
        if target.exists():
            return what
    return None


def _checked_out_elsewhere(git: _Git, branch: str) -> str | None:
    """The path of another worktree that has ``branch`` checked out, '' when
    none does, None when git could not list them: git before 2.43 does not
    refuse a ``switch -C`` of a branch another worktree holds, so a list that
    did not answer must never read as nowhere (DEF-2046)."""
    listing = git.out("worktree", "list", "--porcelain")
    if listing is None:
        return None
    here = _norm(git.cwd)
    for block in parse_worktrees(listing):
        if block.get("branch") == f"refs/heads/{branch}" and _norm(block.get("worktree", "")) != here:
            return block.get("worktree", "")
    return ""


def _own_ref_listed(git: _Git, remote: str, branch: str) -> bool | None:
    """Whether ``remote`` lists a branch of the lane's exact name, as this
    clone last saw it (after the catch-up's pruning fetch): origin's refs,
    never ``@{u}``, which names what the branch tracks (DEF-2042). None when
    git could not say: a read that did not answer is never a no (DEF-2046)."""
    own = f"refs/remotes/{remote}/{branch}"
    listing = git.out("for-each-ref", "--format=%(refname)", own)
    return None if listing is None else own in listing.splitlines()


def _upstream_gone(git: _Git, branch: str, remote: str, upstream: str) -> bool:
    """Whether the lane ``branch``, every commit of it already on ``upstream``
    (the caller's count), is a merged lane whose remote branch is gone: no
    branch of its name listed on ``remote``, and either git reads its
    upstream as gone (pushed with ``-u``, merged and pruned) or its tip is off
    ``upstream``'s first-parent chain, where only a merge's second parent
    sits (pushed without ``-u``: its upstream is ``upstream`` itself, never
    gone, so the lane stayed behind main told its remote branch still
    existed, DEF-2042). The chain is read only for a branch that tracks
    ``upstream``, the shape such a lane keeps: a branch with no upstream at
    all, cut from a merged lane's tip before its first commit, is someone's
    choice and stays, as a lane started from ``upstream`` with nothing of its
    own does (its tip on the chain); a chain git cannot read keeps the lane
    in place, as an own-ref read that cannot say does."""
    if _own_ref_listed(git, remote, branch) is not False:
        return False
    if git.out("for-each-ref", "--format=%(upstream:track)", f"refs/heads/{branch}") == "[gone]":
        return True
    if git.out("rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{branch}@{{upstream}}") != upstream:
        return False
    tip = git.out("rev-parse", f"refs/heads/{branch}")
    chain = git.out("rev-list", "--first-parent", upstream)
    return bool(tip) and chain is not None and tip not in chain.splitlines()


def catch_up(root: Path, *, deadline: float | None = None, other_session: str = "",
             plan_open: bool = False, dry_run: bool = False, remote: str = REMOTE,
             runner: Runner = run, spawner: Callable[..., Spawned | None] = spawn) -> CatchUp:
    """Bring the checkout at ``root`` up to ``<remote>/<default>`` when, and
    only when, nothing can be lost (the module docstring has the rules).
    ``other_session`` names a live session sharing this checkout ('' for
    none) and ``plan_open`` says a plan is in progress; either holds. A read
    that did not answer holds an act it rests on and is counted on the
    outcome (``unanswered``). Never raises."""
    git = _Git(root, deadline, runner, spawner)
    result = _catch_up(git, other_session=other_session, plan_open=plan_open, dry_run=dry_run, remote=remote)
    result.unanswered = git.unanswered
    return result


def _catch_up(git: _Git, *, other_session: str, plan_open: bool, dry_run: bool, remote: str) -> CatchUp:
    has_remote = git.ask("remote", "get-url", remote)
    if has_remote is None:
        return CatchUp("held", reason="git did not answer in time", fetched=False,
                       remedy=f"git pull --ff-only {remote}")
    if has_remote.returncode != 0:
        return CatchUp("skipped", reason=f"no {remote} remote")
    fetched = git.fetch(remote)
    asked = git.unanswered
    base = default_branch(git, remote)
    if git.unanswered > asked:
        # A fallback guess past a read that did not answer is no base: a
        # repository whose default is not main would compare with main.
        return CatchUp("held", reason=f"git did not answer which branch is {remote}'s default",
                       remedy=f"git pull --ff-only {remote}", fetched=fetched)
    if base is None:
        return CatchUp("skipped", reason=f"no default branch on {remote}", fetched=fetched)
    upstream = f"{remote}/{base}"
    remedy = f"git switch {base} && git pull --ff-only {remote} {base}"
    head_ref = git.ask("symbolic-ref", "--quiet", "--short", "HEAD")
    if head_ref is None:
        # Exit 1 is a detached HEAD; no answer at all is not one (DEF-2046).
        return CatchUp("held", base=base, reason="git did not answer which branch is checked out",
                       remedy=f"`git status` first; on a merged lane: {remedy}", fetched=fetched)
    branch = head_ref.stdout.strip() if head_ref.returncode == 0 else ""
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
        asked = git.unanswered
        # A merge read from a read that did not answer is no merge: the lane
        # stays, worded as unread (DEF-2046).
        gone = (bool(branch) and ahead == 0 and _upstream_gone(git, branch, remote, upstream)
                and git.unanswered == asked)
        if not gone:
            # Work of its own, a remote branch that still exists, no upstream
            # at all, or a detached HEAD: someone's choice. Named, never moved.
            # The reason says what was read on origin, never @{u} (DEF-2042).
            result.state = "lane"
            if branch and ahead == 0:
                listed = _own_ref_listed(git, remote, branch) if git.unanswered == asked else None
                result.reason = ("its remote branch still exists" if listed
                                 else "whether it merged could not be read" if listed is None
                                 else "nothing of its own yet")
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
        holds.append("git could not rule out an operation in progress" if operation == _UNRULED_OPERATION
                     else f"{operation} is in progress")
    edits = git.out("status", "--porcelain", "--untracked-files=no")
    if edits is None:
        holds.append("git could not read the working tree")
    elif edits:
        holds.append(f"{_plural(len(edits.splitlines()), 'uncommitted change')} to tracked files")
    has_local = git.yes("show-ref", "--verify", "--quiet", f"refs/heads/{base}")
    contained = git.yes("merge-base", "--is-ancestor", f"refs/heads/{base}", upstream) if has_local else True
    if has_local is None:
        holds.append(f"git could not say whether a local {base} exists")
    elif contained is None:
        holds.append(f"git could not compare local {base} with {upstream}")
    elif not contained:
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
    if _left(git.deadline, MOVE_FLOOR_S) < MOVE_FLOOR_S:
        result.state = "held"
        result.reason = "out of time this session"
        result.remedy = f"the next session does it, or: {remedy}"
        return result
    old = git.out("rev-parse", "HEAD") or ""
    elsewhere = _checked_out_elsewhere(git, base) if branch != base else ""
    if elsewhere is None:
        # git before 2.43 moves a branch another worktree holds under it, so
        # an unread list holds the move (DEF-2046; measured on 2.39.5).
        result.state = "held"
        result.reason = f"git did not answer where {base} is checked out"
        result.remedy = f"the next session does it, or: {remedy}"
        return result
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
    now, wanted = git.out("rev-parse", "HEAD"), git.out("rev-parse", upstream)
    # Only two answers that differ are a move that missed: a read that did not
    # answer leaves the switch's own exit 0 standing, and the line counts it.
    if now is not None and wanted is not None and now != wanted:
        result.state = "held"
        result.reason = f"after the move HEAD is {tip or 'unknown'}, not {upstream}"
        result.remedy = remedy
        return result
    result.state, result.head = "caught_up", tip
    changed = git.out("diff", "--name-only", old, "HEAD") if old else None
    if changed is None:
        result.changed_unread = True
    else:
        result.changed = changed.splitlines()
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


def _saved_edit(rel: str) -> bool:
    """Whether ``rel`` is under :data:`_KEPT_STATE_REL` (or is it)."""
    return rel == _KEPT_STATE_REL or rel.startswith(_KEPT_STATE_REL + "/")


def _disposable(rel: str) -> bool:
    """A cache, a regenerable output, or ``cc/`` session state (saved first);
    never a saved edit, though it sits in the state directory (DEF-3009)."""
    if _saved_edit(rel):
        return False
    parts = rel.split("/")
    if parts[0] == "cc" or parts[0] in _DISPOSABLE_TOPS or parts[0].startswith("build"):
        return True
    return any(p in _DISPOSABLE_DIR_NAMES for p in parts) or rel.endswith(_DISPOSABLE_SUFFIXES)


def _ignored_entries(git: _Git) -> list[str] | None:
    """The worktree's ignored entries; None when git cannot list them. A
    directory git collapses (every file in it ignored) is listed by its files
    unless it is disposable as a whole, so a ``.worktreeinclude`` copy inside a
    fully-ignored ``.claude/`` is still compared, not lost unread. The state
    directory is listed by its files too, since it holds the saved edits
    (DEF-3009: collapsed, it hid them, and the worktree went with them)."""
    listing = git.out("ls-files", "--others", "--ignored", "--exclude-standard", "--directory")
    if listing is None:
        return None
    entries: list[str] = []
    for line in (line for line in listing.splitlines() if line):
        folder = line.rstrip("/")
        # The state directory is opened only when the saved-edit folder is in
        # it: otherwise the extra listing would cost a spawn for nothing.
        holds_saved = _KEPT_STATE_REL.startswith(folder + "/") and (git.cwd / _KEPT_STATE_REL).is_dir()
        if line.endswith("/") and (not _disposable(folder) or holds_saved):
            inside = git.out("ls-files", "--others", "--ignored", "--exclude-standard", "--", line)
            if inside is None:
                return None
            entries += [f for f in inside.splitlines() if f] or [line]
        else:
            entries.append(line)
    # A hand-written spelling (`.espalier-state/*`) lists the state directory
    # and the saved-edit folder both, and each is opened: one entry once.
    return list(dict.fromkeys(entries))


def unsaved_ignored(entries: list[str], worktree: Path, root: Path) -> list[str]:
    """The ignored entries a removal would lose: everything but caches and
    regenerable outputs, ``cc/`` (saved by :func:`save_cc_state` first), a
    ``.worktreeinclude`` copy byte-identical to the root's, and a saved edit
    whose bytes its file still holds (:func:`_held_by_its_file`)."""
    lost: list[str] = []
    for entry in entries:
        rel = entry.rstrip("/")
        if _disposable(rel):
            continue
        # A saved-edit folder listed as a folder has no file in it (git
        # lists an empty directory under --directory): it holds no edit.
        if _saved_edit(rel) and (entry.endswith("/") or _held_by_its_file(worktree, rel)):
            continue
        if rel in _COPIED_FROM_ROOT:
            try:
                if (worktree / rel).read_bytes() == (root / rel).read_bytes():
                    continue
            except OSError:  # fail-open: ok deliberate -- unreadable means "not the same": keep it
                pass
        lost.append(entry)
    return lost


def _held_by_its_file(worktree: Path, rel: str) -> bool:
    """Whether a saved edit's bytes are still those of a file of its name
    under ``tools/cc/`` in ``worktree``: the restore never ran (its permission
    prompt was declined) or the edit was put back, so in a clean, merged
    worktree the copy holds nothing the branch does not. The copy is named
    ``<stem>-<UTC>.py.txt``, and the files a restore can name sit in
    ``tools/cc/`` and ``tools/cc/hooks/``: those two are read, never walked
    (a walk follows a symlinked folder into a loop). Unreadable, or a name of
    another shape: False, so the worktree is kept."""
    name = rel.rsplit("/", 1)[-1]
    if not name.endswith(".py.txt") or "-" not in name:
        return False
    stem = name[: -len(".py.txt")].rsplit("-", 1)[0]
    cc = worktree / "tools" / "cc"
    try:
        saved = (worktree / rel).read_bytes()
        return any(p.is_file() and p.read_bytes() == saved for p in (cc / f"{stem}.py", cc / "hooks" / f"{stem}.py"))
    except OSError:  # fail-open: ok deliberate -- unreadable means "not held": keep the worktree
        return False


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


def held_open(path: Path, cwds: Callable[[], dict[int, str] | None] | None = None) -> str:
    """'' when no process holds the folder; else why it stays. On Windows a
    folder that is some process's cwd (a terminal, an editor's watcher)
    cannot be renamed, so a rename there and back is the probe. Elsewhere a
    rename succeeds under an open cwd and proves nothing, so the process table
    is read instead (``cwds``, the caller's one read, else
    :func:`process_cwds`): a process other than this one whose working
    directory is in the folder keeps it, named by pid -- a nohup'd run whose
    session ended is no Claude session and leaves no marker (DEF-4079). A
    table the reader could not read keeps it too; a host with no reader at
    all (neither `/proc` cwd links nor `lsof`) reads nothing and keeps
    nothing, as before."""
    if os.name != "nt":
        table = cwds() if cwds is not None else process_cwds(None)
        if table is None:
            return "the process table could not be read, so a run in it cannot be ruled out"
        mine = os.getpid()   # its own cwd is the caller's, judged by own_cwd
        held = sorted(pid for pid, cwd in table.items() if pid != mine and within(cwd, path))
        if not held:
            return ""
        if len(held) == 1:
            return f"a process works in it (pid {held[0]})"
        return f"{len(held)} processes work in it (pids {_names([str(pid) for pid in held])})"
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
                   dry_run: bool = False, remote: str = REMOTE, only: Path | None = None,
                   runner: Runner = run, spawner: Callable[..., Spawned | None] = spawn) -> Reap:
    """Remove the leftover worktrees under ``<root>/.claude/worktrees/`` that
    hold nothing (the module docstring has the rules); with ``only``, that one
    worktree alone, under the same rules (``seat.py retire``). ``sessions`` comes from
    :func:`live_sessions` (None: the registry could not be trusted, and then
    nothing is removed; ``unreadable_note`` says why); ``held_by_other`` names
    a live session in the root checkout, which also removes nothing, since
    that session may have entered one of them. Each worktree is named,
    removed or kept with its reason; ``unanswered`` counts every read that
    did not answer, in each worktree too. Never raises."""
    git = _Git(root, deadline, runner, spawner)
    report = _reap(git, root, sessions=sessions, own_cwd=own_cwd, marker_live=marker_live,
                   held_by_other=held_by_other, unreadable_note=unreadable_note, dry_run=dry_run,
                   remote=remote, only=only)
    report.unanswered = git.unanswered
    return report


def _reap(git: _Git, root: Path, *, sessions: list[dict[str, object]] | None, own_cwd: Path | None,
          marker_live: Callable[[Path], bool] | None, held_by_other: str, unreadable_note: str,
          dry_run: bool, remote: str, only: Path | None) -> Reap:
    report = Reap()
    deadline = git.deadline
    listing = git.out("worktree", "list", "--porcelain")
    if listing is None:
        report.note = "git could not list the worktrees"
        return report
    home = root.joinpath(*WORKTREES_REL)
    blocks = [b for b in parse_worktrees(listing)[1:] if b.get("worktree")]
    ours = [b for b in blocks if within(b["worktree"], home)]
    if only is not None:
        ours = [b for b in ours if _norm(b["worktree"]) == _norm(only)]
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
    asked = git.unanswered
    base = default_branch(git, remote)
    if git.unanswered > asked:
        # A fallback guess past a read that did not answer is no base.
        base, no_base = None, f"git did not answer which branch is {remote}'s default"
    else:
        no_base = f"no default branch on {remote} to compare with"
    upstream = f"{remote}/{base}" if base else None
    outside_prunable = any("prunable" in b for b in blocks if b not in ours)
    read: list[dict[int, str] | None] = []

    def table_once() -> dict[int, str] | None:
        # The process table, read at the first worktree that reaches its
        # removal and kept for the rest (held_open; never on Windows, whose
        # rename probe reads no table).
        if not read:
            read.append(process_cwds(None, timeout=max(MIN_SPAWN_S, _left(deadline, CWD_READ_S))))
        return read[0]

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
        reason = _why_kept(git, block, path, upstream, sessions, own_cwd, marker_live, root, no_base=no_base)
        if reason:
            report.keep(path, reason)
            continue
        # Named, since the banner said "a plan in it is still in progress" until now (DEF-4047).
        named = path.name + (" (its plan was never closed; the lane merged)" if plan_in_progress(path) else "")
        if dry_run:
            # Off Windows reading the table changes nothing, so a dry run reads
            # it too (seat.py's list and retire show this verdict); Windows's
            # probe renames the folder, which a dry run must not.
            busy = held_open(path, table_once) if os.name != "nt" else ""
            if busy:
                report.keep(path, busy)
            else:
                report.would_remove.append(named)
            continue
        if _left(deadline, REMOVE_FLOOR_S) < REMOVE_FLOOR_S:
            report.deferred.append(path.name)
            continue
        busy = held_open(path, table_once)
        if busy:
            report.keep(path, busy)
            continue
        cc_files = git.at(path).out("ls-files", "--others", "--ignored", "--exclude-standard", "--", "cc")
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
            held = _LOCK_PID_RE.search(block.get("locked", ""))
            report.unlocked.append(f"{path.name} (pid {held.group(1)})" if held else path.name)
        removal = git.change("worktree", "remove", str(path), wait=REMOVE_WAIT_S)
        if removal is not None and not removal.done:
            report.keep(path, f"its removal is still running (git pid {removal.pid}); it finishes on its own")
            continue
        after = git.out("worktree", "list", "--porcelain")
        if after is None:
            # The list did not read back: git's own exit answers, and the
            # folder check below still does (the line counts the read).
            still_registered = removal is None or removal.returncode != 0
        else:
            still_registered = any(_norm(b.get("worktree", "")) == _norm(path) for b in parse_worktrees(after))
        if still_registered:
            report.keep(path, f"git did not remove it: {_err(removal)}")
            continue
        if path.exists():
            # git dropped the registration but the folder stayed: on Windows a
            # process with the folder as its cwd holds it open.
            report.keep(path, "unregistered, but the folder could not be deleted (a process may have it open)")
            continue
        report.removed.append(named)
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
              marker_live: Callable[[Path], bool] | None, root: Path, *,
              no_base: str = f"no default branch on {REMOTE} to compare with") -> str:
    """'' when the worktree may go; else the reason it stays, in words.
    ``no_base`` is the reason when ``upstream`` is None."""
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
        # git's prune skips a locked record, so a lock whose holder exited is
        # released first (an unlock by the missing path still finds it).
        unlock = "git worktree unlock, then " if "locked" in block else ""
        return f"its folder is missing ({unlock}git worktree prune clears the record)"
    if not (path / ".git").exists():
        return "its .git link is missing (`git worktree repair`, or remove the folder by hand)"
    if upstream is None:
        return no_base
    here = git.at(path)
    status = here.out("status", "--porcelain")
    mid = _mid_operation(here) if status == "" else None
    head = block.get("HEAD", "")
    merged = git.yes("merge-base", "--is-ancestor", head, upstream) if head and status == "" and not mid else None
    unmerged: int | None = 0
    if merged is False:
        # By sha, a commit main holds by patch (a cherry-pick, an applied
        # diff) is still ahead; by patch it is not (DEF-5077). A merge commit
        # is never marked equivalent, so it counts as one main lacks. A patch
        # id ignores whitespace, so a match counts only where a branch keeps
        # the commits after the removal (its -D below stays on ancestry); a
        # detached HEAD's commits would be left unreachable, so each counts.
        marks = git.out("rev-list", "--cherry-mark", "--right-only", f"{upstream}...{head}")
        held = bool(block.get("branch"))
        unmerged = None if marks is None else sum(
            1 for line in marks.splitlines() if line.startswith("+") or (line and not held))
    # The plan is read beside the lane (DEF-4047): an open plan keeps a tree
    # with work in it, never a merged, clean one, whose plan was never closed.
    if plan_in_progress(path, merged_and_clean=merged is not None and unmerged == 0):
        return "a plan in it is still in progress"
    if status is None:
        return "git could not read it"
    if status:
        return _plural(len(status.splitlines()), "uncommitted change")
    if mid:
        return ("git could not rule out an operation in progress in it" if mid == _UNRULED_OPERATION
                else "an operation is in progress in it")
    if merged is None or unmerged is None:
        return "git could not compare it with " + upstream
    if unmerged:
        branch = block.get("branch", "").replace("refs/heads/", "") or "detached"
        return f"{unmerged} commit(s) not in main ({branch})"
    ignored = _ignored_entries(here)
    if ignored is None:
        return "git could not list its ignored files"
    lost = unsaved_ignored(ignored, path, root)
    saved = [entry for entry in lost if _saved_edit(entry.rstrip("/"))]
    if saved:
        # Named from the root, where the banner is read: the root has a
        # state directory of its own, and a path read there would miss.
        try:
            where = path.resolve().relative_to(root.resolve()).as_posix() + "/"
        except ValueError:  # fail-open: ok deliberate -- a worktree outside the root is named by its own path
            where = path.as_posix().rstrip("/") + "/"
        them = "it" if len(saved) == 1 else "them"
        others = len(lost) - len(saved)
        return (f"{_plural(len(saved), 'saved edit')} {_SAVED_EDIT_WORDS} ({_names([where + e for e in saved])}): "
                f"read {them}, "
                f"keep what you need, then delete {them}"
                + (f" ({_plural(others, 'other ignored file')} too)" if others else ""))
    if lost:
        files = f"{_plural(len(lost), 'ignored file')} git status cannot see ({_names(lost)}); move what you need"
        # A forced removal of a worktree whose seat holds claims or jobs
        # strands them as the reaper would (DEF-2043): the seat's reason
        # replaces the --force advice, so the banner never types the harm.
        held = _seat_claims_kept(here, root)
        return f"{files}, and {held}" if held else f"{files}, then `git worktree remove --force` it"
    return _seat_claims_kept(here, root)


class JobsUnread(Exception):
    """The dispatcher setting did not read, so the seat's jobs are not known;
    ``claims`` are the seat's live claims, read before it."""

    def __init__(self, how: str, claims: list[dict]):
        super().__init__(how)
        self.claims = claims


def seat_live_mail(root: Path, seat: str, timeout: float) -> tuple[list[dict], list[dict]]:
    """``(the live claims seat sent, the live jobs the dispatcher gave it)``,
    from one read of the mail channel's local refs (``mail.py``, a deployed
    sibling; nothing of either where it is not deployed). A dispatcher
    setting that does not read raises :class:`JobsUnread` carrying the claims:
    the channel counts no assign then (it fails closed for a worker), which
    would read here as no job and let the worktree go. So does a Python that
    cannot read ``espalier.toml`` at all (no ``tomllib`` below 3.11)."""
    try:
        import mail
    except ImportError:
        # Not deployed: no claims or jobs to strand. Deployed but not
        # importable (a SessionStart catch-up that moved a helper this process
        # had already imported, DEF-2003) is an unread list, which keeps the worktree.
        if (Path(__file__).resolve().parent / "mail.py").is_file():
            raise
        return [], []  # fail-open: ok deliberate -- a deploy set without the channel has nothing to strand
    by_machine, _ = mail.read_mail(root, timeout=timeout)
    claims = [c for c in mail.live_claims(by_machine) if str(c.get("from") or "") == seat]
    try:
        dispatcher, how = mail.dispatcher_setting(root)
    except ImportError as exc:
        raise JobsUnread(f"this Python cannot read espalier.toml ({exc}; it needs 3.11 or later)", claims) from exc
    if dispatcher == mail.DISPATCHER_UNUSABLE:
        raise JobsUnread(how, claims)
    jobs = [j for j in mail.live_assignments(by_machine, dispatcher)
            if str((j.get("re") or {}).get(mail.ASSIGN_SEAT_KEY) or "") == seat]
    return claims, jobs


def _words(value: object) -> str:
    """A message field's strings, space-joined; a malformed field (not a
    list of strings) reads as none, as the mail fold reads it."""
    return " ".join(v for v in value if isinstance(v, str)) if isinstance(value, (list, tuple)) else ""


def _job_name(job: dict) -> str:
    """A job as the board names it: its lane, else its ids, else its classes,
    else its message id's tail."""
    re_ = job.get("re")
    re_ = re_ if isinstance(re_, dict) else {}
    lane = re_.get("lane")
    return ((lane if isinstance(lane, str) else "") or _words(re_.get("ids")) or _words(re_.get("classes"))
            or str(job.get("id") or "")[-6:])


def _seat_claims_kept(here: _Git, root: Path) -> str:
    """'' unless the worktree names a seat of its own (git's per-worktree
    ``espalier.machine``, which SessionStart sets) that still holds live
    claims or live jobs from the dispatcher. Only that name can release the
    claims: removed with its worktree, they stay live and warn every other
    seat's plan, and no seat is left to close them. A seat between lanes holds
    jobs and no claim (a push releases its lane's claims), and removed, its
    jobs stay live on the board with no seat to work them (DEF-2043): kept,
    as ``seat.py retire`` refuses such a seat unless ``--return-jobs`` hands
    them back. A worktree that answers its clone's name is the clone's own seat,
    which can still release, so it is not asked. Kept when the seat's name or
    its claims cannot be read, as every other check here keeps what it cannot
    read. Without per-worktree config no worktree has a name of its own (git
    then refuses ``--worktree`` outright where a clone has several)."""
    # Read as git reads it: the repository's own config (git honours the
    # extension nowhere else) and as a boolean (yes, on and 1 are on).
    ext = here.ask("config", "--local", "--type=bool", "--get", "extensions.worktreeConfig")
    if ext is not None and (ext.returncode == 1 or (ext.returncode == 0 and ext.stdout.strip() != "true")):
        return ""
    asked = None
    if ext is not None and ext.returncode == 0:
        # unread-name: ok exit 1 alone is "not set"; no answer, or any other exit, keeps the worktree below
        asked = here.ask("config", "--worktree", "--get", "espalier.machine")
    if asked is None or asked.returncode not in (0, 1):
        # The read that failed: the name's, else the extension's own (asked
        # never ran), else neither answered in time.
        failed = asked if asked is not None else ext if ext is not None and ext.returncode != 0 else None
        lines = (failed.stderr or "").strip().splitlines() if failed is not None else []
        detail = ("git did not answer in time" if failed is None else
                  f"git exited {failed.returncode}" + (f": {_ascii(lines[-1])[:120]}" if lines else ""))
        return (f"its seat name could not be read ({detail}), so whether it holds claims only it can release "
                "is not known")
    seat = asked.stdout.strip() if asked.returncode == 0 else ""
    if not seat:
        return ""
    timeout = _left(here.deadline, GIT_CAP_S)
    if timeout < MIN_SPAWN_S:
        return f"its seat {seat}'s claims and jobs were not read in time"
    try:
        claims, jobs = seat_live_mail(root, seat, timeout)
    except JobsUnread as e:
        unread = f"its seat {seat}'s jobs could not be read ({_ascii(str(e))[:160]})"
        # The unread jobs lead, so retire (which goes on only past a reason
        # opening "its seat <seat> holds") refuses: its own read counts no job then.
        return unread + (f"; {_claims_words(seat, e.claims, '')}" if e.claims else "")
    except Exception as e:  # noqa: BLE001 -- fail-open: ok deliberate -- an unread claim list keeps the worktree, as an unread status does
        return f"its seat {seat}'s claims and jobs could not be read ({_ascii(os_error_text(e))[:120]})"
    if not claims and not jobs:
        return ""
    held = f"{_plural(len(jobs), 'job')} from the dispatcher ({_names([_job_name(j) for j in jobs])})"
    if not claims:
        return (f"its seat {seat} holds {held} and no claim: removed, nobody would work them. "
                f"From the main checkout, `python tools/cc/seat.py retire {seat} --return-jobs` hands them back "
                "and removes it, or once the dispatcher reassigns them it can go")
    return _claims_words(seat, claims, held)


def _claims_words(seat: str, claims: list[dict], held: str) -> str:
    """The kept reason for a seat holding live claims, and ``held`` (the
    jobs it also holds, worded) when it is not ''."""
    lanes = sorted({str((c.get("re") or {}).get("lane") or "no lane") for c in claims})
    ids = [str(c.get("id") or "") for c in claims if c.get("id")]
    retire = (f"`python tools/cc/seat.py retire {seat} --return-jobs` releases them, returns the jobs"
              if held else f"`python tools/cc/seat.py retire {seat}` releases them")
    return (f"its seat {seat} holds {_plural(len(claims), 'live claim')} ({_names(lanes)}) that only it can "
            f"release" + (f" and {held}" if held else "")
            + f": from the main checkout, {retire} and removes it, "
            "or in it, `python tools/cc/mail.py send --type release --ack <claim id>` for each"
            + (f" ({_names(ids)})" if ids else "")
            + " (by id: a lane release reads as its lane shipped), then "
            + ("the jobs still keep it until they go back" if held else "it can go"))


# -- the banner's words ------------------------------------------------------------

def _names(names: list[str]) -> str:
    shown = ", ".join(names[:NAMES_SHOWN])
    return shown + (f", and {len(names) - NAMES_SHOWN} more" if len(names) > NAMES_SHOWN else "")


def checkout_line(result: CatchUp) -> str:
    """The banner's ``Checkout:`` value, or '' when there is nothing to say.
    A fetch that did not land, and a read that did not answer, are said on
    every state that would otherwise read as fact, ``current`` included
    (DEF-2046); a hold and a move in flight say it in their reason."""
    stale = "" if result.fetched else " (origin not reached; compared with the last fetch)"
    unread = f" ({_plural(result.unanswered, 'git read')} did not answer in time)" if result.unanswered else ""
    if result.state == "caught_up":
        left = ""
        if result.branch and result.branch != result.base:
            dropped = ", branch deleted" if result.deleted_branch else ""
            left = f"left {result.branch} (merged{dropped}); "
        where = f"detached at {REMOTE}/{result.base}" if result.detached else f"{result.base} fast-forwarded"
        line = (f"caught up -- {left}{where}, {_plural(result.behind, 'commit')}, now {result.head or 'unread'}"
                f"{stale}{unread}")
        if result.changed_unread:
            line += " (what it changed did not read: /clear to load any new hooks in this session)"
        elif any(p.startswith((".claude/", "tools/cc/hooks/")) or p == "CLAUDE.md" for p in result.changed):
            line += " (hooks or CLAUDE.md changed with it: /clear to load them in this session)"
        return _ascii(line)
    if result.state == "would_catch_up":
        return _ascii(f"would catch up {_plural(result.behind, 'commit')} from {result.branch or 'HEAD'} "
                      f"to {result.base}{stale}{unread}")
    if result.state == "moving":
        return _ascii(f"catching up -- {result.reason}")
    if result.state == "held":
        behind = f"{_plural(result.behind, 'commit')} behind {REMOTE}/{result.base}, " if result.behind else ""
        tail = f" -- {result.remedy}" if result.remedy else ""
        if stale and not result.behind:
            stale = " (origin not reached)"   # held before any comparison: nothing was compared
        return _ascii(f"NOT caught up ({behind}{result.reason}){stale}{tail}")
    if result.state == "lane" and result.behind:
        where = result.branch or "a detached HEAD"
        own = f"{_plural(result.ahead, 'commit')} not in {result.base}" if result.ahead else (
            result.reason or "nothing of its own")
        if result.branch == result.base:
            own = result.reason
        return _ascii(f"on {where} ({own}); {result.base} has {result.behind} newer -- left as is{stale}{unread}")
    if result.state == "current" and (stale or unread):
        return _ascii(f"current{stale}{unread}")
    if result.state == "skipped" and (stale or unread):
        return _ascii(f"{result.reason or 'not compared'}{' (origin not reached)' if stale else ''}{unread}")
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
        kept = _names([n for n, _ in report.kept])
        parts.append(f"{report.note}: {kept}" if kept else report.note)
    elif report.kept:
        # A saved edit is the one copy of an edit (DEF-3009): every worktree
        # holding one is named, first, whatever the count.
        saved = [f"{name} [{why}]" for name, why in report.kept if _SAVED_EDIT_WORDS in why]
        rest = [f"{name} [{why}]" for name, why in report.kept if _SAVED_EDIT_WORDS not in why]
        parts.append(f"kept {len(report.kept)}: " + ", ".join(saved + ([_names(rest)] if rest else [])))
    if report.saved:
        parts.append(f"their session notes saved under cc/blueprints/ ({_plural(len(report.saved), 'file')})")
    if report.unanswered:
        parts.append(f"{_plural(report.unanswered, 'git read')} did not answer in time")
    return _ascii("; ".join(parts))


# -- the CLI ---------------------------------------------------------------------

def _repo_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    # The main checkout, even when run from inside a linked worktree: the
    # common git dir's parent. `--path-format` needs git 2.31; older gits
    # fall back to this checkout's own top level.
    # A read that did not answer is never the fallback's cue: inside a linked
    # worktree the fallback roots at the worktree (DEF-2046).
    unanswered = "checkout_sync: git did not answer in 10 s (git rev-parse); run it again, or pass --root"
    r = run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=Path.cwd(), timeout=10)
    if r is None:
        raise SystemExit(unanswered)
    if r.returncode == 0 and Path(r.stdout.strip()).name == ".git":
        return Path(r.stdout.strip()).parent
    r = run(["git", "rev-parse", "--show-toplevel"], cwd=Path.cwd(), timeout=10)
    if r is None:
        raise SystemExit(unanswered)
    if r.returncode != 0:
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
    mine, read = find_own_entry(sessions) if sessions is not None else (None, True)
    if sessions is not None and os.environ.get("CLAUDECODE") and mine is None:
        # Run from inside a session, the registry must list that session, or it
        # is not the registry this session writes to.
        note = NOT_LISTED if read else TABLE_UNREAD
        sessions = None
    if sessions is not None:
        # By the entry already found: a second walk of the table could miss it.
        others = [s for s in sessions_in_checkout(sessions, root) if s is not mine]
        other = f"pid {others[0]['pid']}" if others else ""
    else:
        rows: list[dict[str, object]] = (
            getattr(hook_utils, "other_live_sessions", lambda *_a: [])(root, "") if hook_utils else [])
        other = f"session {str(rows[0].get('session_id', ''))[:8]}" if rows else ""
    plan_open = plan_in_progress(root)
    result = catch_up(root, other_session=other, plan_open=plan_open, dry_run=not args.apply)
    marker_live = None
    if hook_utils is not None:
        # Counted by age, never by the rows' alive: a removal fails closed, so
        # any recent marker keeps its worktree (the Sessions line drops exited
        # windows; the reaper does not).
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
