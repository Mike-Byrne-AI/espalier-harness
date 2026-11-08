"""One spawn for the rows that run write_guard, or the statusline, as a real
child (DEF-2014).

The windows-latest portability cell stalls now and then. Before DEF-979's
split, a third of its cells redded on a ``write_guard`` hook-through row the
change never touched, a different row each time: seven of ten at the rows'
15 s spawn bound and three at the hook's own judgment budget
(``tools/cc/hooks/write_guard.py::JUDGMENT_BUDGET_S``), whose refusal a
verdict row reads as a wrong answer. A stall is transient; a regression is
not. So a miss (a timeout, or the budget's refusal) is retried once under the
SAME bound: a stalled runner answers the second time, while a hook that hangs,
or is slow every time, misses both and reds on every runner, naming both
elapsed times. Any other answer, a wrong verdict included, is the first
attempt's.

Three limits keep the retry honest:

- one retry per test row, so a row that spawns several times waits at most
  one bound longer than it did, and a second miss fails at once;
- the retry starts from the state the first attempt began with (DEF-2030):
  a timed-out attempt's whole process group is ended (a budget refusal has
  already exited), then the files under the
  project's ``.espalier-state`` and under the test's own audit directory
  (bytes and mtimes) are put back as they were saved before the first
  attempt, what the attempt added removed, so a speed bump's one-shot flag
  the miss wrote is never read as a re-issue, and a row that counts audit
  records never counts the missed attempt's. Anything else under the
  project (resolved as the hook resolves it: ``CLAUDE_PROJECT_DIR`` from the
  env given, else the working directory) that the attempt changed, an
  interpreter's ``__pycache__`` apart, means no retry: session_start's blueprint chain and reflect_trigger's marker under
  ``cc/``, a marker at the project's root, and in the suite's own checkout,
  whose ``.espalier-state`` a live session writes too and which is never put
  back, everything. The real home audit log, which live sessions share, is
  never put back; no hook decision reads it (driven 2026-11-07 over every
  spawn through here: 4975 spawns, 3743 rows);
- the statusline keeps its own 5 s bound, its prompt-delay check.

A retry that answers is a ``HookSpawnRetried`` warning, which the run's summary
counts (``tests/conftest.py::pytest_terminal_summary``). The budget itself is
the hook's and is not touched here: it fails closed by design.

A write_guard spawn that keeps a bound past ``HOOK_S`` does not come here: a
retry of a timeout under that bound would carry its row past the suite's
per-test ceiling. The budget refuses within the parent's 4.0 s deadline
whatever the bound, and its refusal is a deny on the decision channel, so such
a spawn is written inside ``retry_a_budget_miss``, which retries that refusal
alone, once, from the state the first attempt began with (it costs one more
spawn, never a second long wait), and fails the row as the miss it is when the
retry is refused too: never an ALLOW row redded as a wrong answer, nor a
must-deny row passed on a judgment that never finished (DEF-5066). Until
DEF-2057 such spawns failed on the first refusal through
``not_a_budget_miss``, which stays as the reader for a result the row cannot
spawn again. ``tests/test_hook_spawn_routing.py`` derives both populations
from the tree.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
import warnings
from collections.abc import Callable
from pathlib import Path

import pytest

#: The text of write_guard's refusal when its judgment outran its budget
#: (``tools/cc/hooks/_denial_reasons.py::WRITE_GUARD_TIME_BUDGET``).
BUDGET_REFUSAL = "could not finish judging"
#: Each attempt's bound for a hook: the 15 s every hook row ran under before.
HOOK_S = 15.0
#: Each attempt's bound for the statusline: its prompt-delay check (BC-027).
STATUSLINE_S = 5.0
#: The bound on ending a missed attempt's process group and draining its pipes.
KILL_S = 5.0

#: The test rows that have spent their one retry, by PYTEST_CURRENT_TEST.
_RETRIED: set[str] = set()
#: The checkout this suite runs from: nothing under it is ever put back, since
#: a live session's hooks write its ``.espalier-state`` too.
SUITE_CHECKOUT = Path(__file__).resolve().parent.parent
#: The project tree a miss's restore puts back.
STATE_DIR = ".espalier-state"


class HookSpawnRetried(UserWarning):
    """A hook row's first attempt missed and its retry answered."""


def _end_the_group(proc: subprocess.Popen) -> None:
    """End a timed-out attempt's whole process group, not the child alone: a
    grandchild left running (reflect_trigger's 25 s reflect spawn, a git a
    judgment started) could write state after the restore, and the retry would
    read it. POSIX: the child leads its own session, so its group is one
    signal. Windows: ``taskkill /T`` walks the tree from the child while it
    still lives. Then the pipes are drained under a bound, since a grandchild
    the kill missed would hold them open."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, timeout=KILL_S)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass   # the child is gone already, or the kill could not run: proc.kill() below still runs
    proc.kill()
    try:
        proc.communicate(timeout=KILL_S)
    except subprocess.TimeoutExpired:
        pass   # a holder the kill missed keeps its pipe; the miss is the row's either way


def _attempt(argv: list[str], *, statusline: bool, binary: bool, input: str | bytes | None = None,
             **kwargs) -> subprocess.CompletedProcess:
    # One wait per bound, each bound a module constant written at its call: the
    # suite contract holding every wait under its test's ceiling reads only that
    # (tests/test_test_suite_contract.py); a bound passed in would be unread.
    # POSIX: the child leads its own session, so its group is one signal.
    # Windows needs no flag: ``taskkill /T`` walks the parent-pid tree.
    group = {} if os.name == "nt" else {"start_new_session": True}
    decoding = {} if binary else {"text": True, "encoding": "utf-8"}
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE if input is not None else None,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **decoding, **group, **kwargs)
    try:
        if statusline:
            out, err = proc.communicate(input, timeout=STATUSLINE_S)
        else:
            out, err = proc.communicate(input, timeout=HOOK_S)
    except BaseException:
        # A timeout, and anything else that leaves the wait (an interrupt, the
        # per-test ceiling's signal): the child and its group never outlive it,
        # as subprocess.run's child never did.
        _end_the_group(proc)
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def _is_suite_checkout(path: Path) -> bool:
    try:
        here = path.resolve()
    except (OSError, RuntimeError):
        return True   # unreadable: never put back, the old rule holds
    return here == SUITE_CHECKOUT or SUITE_CHECKOUT in here.parents


def _audit_dir(env: dict | None) -> Path | None:
    """The child's audit directory where it is this test's own (the
    ``ESPALIER_AUDIT_DIR`` conftest sets, or the one under a home the row
    moved), never the real home's, which live sessions write too."""
    source = env if env is not None else os.environ
    override = source.get("ESPALIER_AUDIT_DIR")
    if override:
        tree = Path(override)
    else:
        home = source.get("USERPROFILE" if os.name == "nt" else "HOME")
        if not home:
            return None
        tree = Path(home) / ".espalier" / "audit"
    try:
        here, shared = tree.resolve(), (Path.home() / ".espalier").resolve()
    except (OSError, RuntimeError):
        return None
    if here == shared or shared in here.parents or _is_suite_checkout(here):
        return None
    return tree


#: A tree's contents: None when it does not exist, else its directories and
#: each file's (bytes, mtime_ns), by path relative to the tree. The mtime is
#: kept and put back, so a flag a hook ages by its mtime reads as it was.
_Tree = tuple[frozenset[str], dict[str, tuple[bytes, int]]] | None


def _save(tree: Path) -> _Tree:
    """What lies under ``tree``, bytes and all, for a restore to put back.
    Raises OSError on a file it cannot read: such a save cannot be put back,
    and the caller keeps the old rule for it."""
    if not tree.is_dir():
        return None
    dirs: set[str] = set()
    files: dict[str, tuple[bytes, int]] = {}
    for p in sorted(tree.rglob("*")):
        rel = p.relative_to(tree).as_posix()
        if p.is_dir():
            dirs.add(rel)
        else:
            files[rel] = (p.read_bytes(), p.stat().st_mtime_ns)
    return frozenset(dirs), files


def _restore(tree: Path, saved: _Tree) -> None:
    """Put ``tree`` back as ``saved`` holds it: what the attempt added is
    removed, what it changed or removed is written back with its mtime."""
    now = _save(tree)
    if now is not None:
        keep_files = saved[1] if saved is not None else {}
        keep_dirs = saved[0] if saved is not None else frozenset()
        for rel in now[1]:
            if rel not in keep_files:
                (tree / rel).unlink()
        for rel in sorted(now[0], key=lambda r: r.count("/"), reverse=True):
            if rel not in keep_dirs:
                (tree / rel).rmdir()
        if saved is None:
            tree.rmdir()
            return
    if saved is None:
        return
    tree.mkdir(parents=True, exist_ok=True)
    for rel in sorted(saved[0]):
        (tree / rel).mkdir(parents=True, exist_ok=True)
    for rel, (data, mtime) in saved[1].items():
        path = tree / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if now is None or now[1].get(rel) != (data, mtime):
            path.write_bytes(data)
            os.utime(path, ns=(mtime, mtime))


def _project(env: dict | None, cwd: str | None) -> Path:
    """The project the hook resolves: ``CLAUDE_PROJECT_DIR`` from the env it
    is given, else its working directory
    (``tools/cc/hooks/_hook_utils.py::resolve_project_root``)."""
    named = (env if env is not None else os.environ).get("CLAUDE_PROJECT_DIR")
    return Path(named or cwd or os.getcwd())


class _Before:
    """What a miss is judged against: the trees the restore puts back, as
    saved, and the names in each folder on the way down to one of them, whose
    own mtime moves when the attempt adds that tree."""

    def __init__(self, env: dict | None, cwd: str | None) -> None:
        self.project = _project(env, cwd)
        self.saved: dict[Path, _Tree] = {}
        if not _is_suite_checkout(self.project):
            try:
                self.saved[self.project / STATE_DIR] = _save(self.project / STATE_DIR)
            except OSError:
                pass   # not put back: the walk then reads it as any other change
        audit = _audit_dir(env)
        if audit is not None:
            try:
                self.saved[audit] = _save(audit)
            except OSError:
                pass   # a log it cannot read is left as it was: no hook decision reads it
        self.on_the_way: dict[str, set[str]] = {}
        self.toward: dict[str, set[str]] = {}
        root = os.path.normcase(os.path.abspath(self.project))
        for tree in self.saved:
            here = os.path.normcase(os.path.abspath(tree))
            if not here.replace("\\", "/").startswith(root.replace("\\", "/").rstrip("/") + "/"):
                continue   # outside the project: the walk never reaches it
            while here != root:
                parent = os.path.dirname(here)
                self.toward.setdefault(parent, set()).add(os.path.basename(here))
                here = parent
        for folder, names in self.toward.items():
            try:
                self.on_the_way[folder] = {os.path.normcase(n) for n in os.listdir(folder)} - names
            except OSError:
                self.on_the_way[folder] = set()
        self.began_ns = time.time_ns()

    def changed_outside(self) -> str | None:
        """The first path under the project, outside the trees put back, that
        the attempt changed: an mtime after the attempt began (a folder's
        catches an add or a removal), or a folder on the way down to a tree
        put back whose other names moved; None when there is none. After, not
        at: on Windows the clock and the file stamps tick together, so a
        folder the row made in the start's tick reads equal (driven
        2026-11-07), and no hook writes within the tick its spawn began in."""
        skip = {os.path.normcase(os.path.abspath(t)) for t in self.saved}
        for dirpath, dirnames, filenames in os.walk(self.project):
            # __pycache__ is the interpreter's own cache of a hook it imported,
            # which no hook decision reads; .git stays walked (a checkout's
            # git switch or index refresh is a change a retry would read).
            dirnames[:] = [d for d in dirnames if d != "__pycache__"
                           and os.path.normcase(os.path.abspath(os.path.join(dirpath, d))) not in skip]
            here = os.path.normcase(os.path.abspath(dirpath))
            if here in self.toward:
                try:
                    names = {os.path.normcase(n) for n in os.listdir(dirpath)} - self.toward[here]
                except OSError:
                    names = set()
                if names != self.on_the_way[here]:
                    return dirpath
            else:
                try:
                    if (os.lstat(dirpath).st_mtime_ns > self.began_ns
                            and not self._a_new_cache_in(dirpath)):
                        return dirpath
                except OSError:
                    pass
            for f in filenames:
                path = os.path.join(dirpath, f)
                try:
                    if os.lstat(path).st_mtime_ns > self.began_ns:
                        return path
                except OSError:
                    continue
        return None


    def _a_new_cache_in(self, folder: str) -> bool:
        """Whether a ``__pycache__`` the attempt wrote explains the folder's
        moved mtime (adding it moves its parent's)."""
        try:
            return os.lstat(os.path.join(folder, "__pycache__")).st_mtime_ns > self.began_ns
        except OSError:
            return False


def _ready_for_the_retry(name: str, miss: str, before: _Before) -> list[str]:
    """Make the retry start from the state the missed attempt began with, or
    fail the row saying why it cannot (DEF-2030). Answers the names of the
    trees it put back."""
    changed = before.changed_outside()
    if changed is not None:
        pytest.fail(f"{name} missed ({miss}) after changing {changed}, outside what the restore puts "
                    f"back ({STATE_DIR} and the test's own audit directory, never in the suite's own "
                    "checkout); a retry would read it, so it is not retried.")
    put_back = []
    for tree, as_saved in before.saved.items():
        try:
            if _save(tree) == as_saved:
                continue
            _restore(tree, as_saved)
            back = _save(tree)
        except OSError as exc:
            pytest.fail(f"{name} missed ({miss}) after changing {tree} in a way that could not be "
                        f"put back ({type(exc).__name__}: {exc}); so it is not retried.")
        if back != as_saved:
            pytest.fail(f"{name} missed ({miss}) after changing {tree}, and putting it back did not "
                        "give the state it began with; so it is not retried.")
        put_back.append(tree.name)
    return put_back


def _budget_refused(result: subprocess.CompletedProcess) -> bool:
    out = result.stdout if isinstance(result.stdout, str) else (result.stdout or b"").decode("utf-8", "replace")
    return BUDGET_REFUSAL in (out or "")


def _script(result: subprocess.CompletedProcess) -> str:
    return next((str(a) for a in reversed(result.args) if str(a).endswith(".py")), str(result.args))


def not_a_budget_miss(result: subprocess.CompletedProcess) -> subprocess.CompletedProcess:
    """``result`` as it came, unless write_guard's budget refused the call:
    then the row fails as a miss, never read as the verdict it looks like.
    For a spawn whose bound is past ``HOOK_S`` (the module docstring); it
    spawns nothing and reads the finished result only."""
    if _budget_refused(result):
        script = _script(result)
        pytest.fail(
            f"{script} answered with write_guard's budget refusal ({BUDGET_REFUSAL!r}): a miss, not a "
            f"verdict. This spawn keeps a bound past the helper's {HOOK_S:.0f} s, where a retry would "
            "overrun the per-test ceiling, so it is not retried: a stalled runner misses now and "
            "then, a judgment slow every time misses on every runner.")
    return result


#: The (row, project) pairs that have spent their one budget retry.
_BUDGET_RETRIED: set[tuple[str, str]] = set()


def retry_a_budget_miss(
    spawn: Callable[[], subprocess.CompletedProcess], *, env: dict | None = None, cwd: str | None = None,
) -> subprocess.CompletedProcess:
    """``spawn()``'s result, with one retry when write_guard's budget refused
    the call, for a spawn whose bound is past ``HOOK_S``. A timeout is not
    retried and raises as before: under a bound that long a second wait could
    run past the per-test ceiling. A budget refusal comes back within the
    parent's ``HARD_DEADLINE_S`` (``tools/cc/hooks/write_guard.py``, 4.0 s),
    so a retry costs that and one more spawn. ``env`` and ``cwd`` are the
    spawn's own, which name the project the restore reads (DEF-2030), and the
    retry starts from the state the first attempt began with, or the row fails
    saying why it cannot. Any other answer, a deny included, is the first
    attempt's. A second refusal fails the row naming both.

    One retry for each test row and project tree. A row that spawns in one
    project several times waits at most one more spawn. A module fixture that
    spawns on a thread pool, one fresh copy of the tree for each job,
    gets one retry per copy, so one stalled job does not error every test
    that requests the fixture (``tests/test_hooks_start_on_a_kept_helper.py``,
    whose classes carry a ceiling for it)."""
    before = _Before(env, cwd)
    began = time.monotonic()
    first = spawn()
    if not _budget_refused(first):
        return first
    name = Path(_script(first)).name
    miss = f"the budget's refusal after {time.monotonic() - began:.1f} s"
    key = (_row(), os.path.normcase(os.path.abspath(before.project)))
    if key in _BUDGET_RETRIED:
        pytest.fail(f"{name} missed ({miss}) and this row has spent its one retry in {before.project}.")
    put_back = _ready_for_the_retry(name, miss, before)
    _BUDGET_RETRIED.add(key)
    began = time.monotonic()
    second = spawn()
    if _budget_refused(second):
        pytest.fail(
            f"{name} answered with write_guard's budget refusal on both attempts: {miss}, then after "
            f"{time.monotonic() - began:.1f} s. A stalled runner misses once; a judgment slow every "
            "time misses every time, on every runner.")
    began_with = f", from the {' and '.join(put_back)} it began with" if put_back else ""
    warnings.warn(HookSpawnRetried(
        f"{name}: the first attempt missed ({miss}); the retry answered in "
        f"{time.monotonic() - began:.1f} s{began_with}"), stacklevel=2)
    return second


def _row() -> str:
    return os.environ.get("PYTEST_CURRENT_TEST", "").rsplit(" (", 1)[0]


def run_hook_through(
    argv: list[str], *, env: dict | None = None, input: str | bytes | None = None,
    cwd: str | None = None, statusline: bool = False,
) -> subprocess.CompletedProcess:
    """Run a hook as Claude Code does, text in and out (or bytes, when the
    input is bytes), with one retry on a miss under the same bound."""
    name = Path(argv[1]).name if len(argv) > 1 else str(argv[0])
    bound = STATUSLINE_S if statusline else HOOK_S
    before = _Before(env, cwd)
    put_back: list[str] = []
    misses: list[str] = []
    for _attempt_no in range(2):
        began = time.monotonic()
        try:
            result = _attempt(argv, statusline=statusline, binary=isinstance(input, bytes),
                              input=input, cwd=cwd, env=env)
        except subprocess.TimeoutExpired:
            misses.append(f"no answer in {time.monotonic() - began:.1f} s")
        else:
            out = result.stdout if isinstance(result.stdout, str) else (result.stdout or b"").decode("utf-8", "replace")
            if BUDGET_REFUSAL not in (out or ""):
                if misses:
                    began_with = f", from the {' and '.join(put_back)} it began with" if put_back else ""
                    warnings.warn(HookSpawnRetried(
                        f"{name}: the first attempt missed ({misses[0]}); "
                        f"the retry answered in {time.monotonic() - began:.1f} s{began_with}"), stacklevel=2)
                return result
            misses.append(f"the budget's refusal after {time.monotonic() - began:.1f} s")
        if len(misses) == 2:
            break
        row = _row()
        if row and row in _RETRIED:
            pytest.fail(f"{name} missed ({misses[0]}) and this row has spent its one retry "
                        f"(each attempt bounded at {bound:.0f} s).")
        put_back = _ready_for_the_retry(name, misses[0], before)
        _RETRIED.add(row)
    pytest.fail(
        f"{name} missed on both attempts: {misses[0]}, then {misses[1]} (each bounded at "
        f"{bound:.0f} s). A stalled runner misses once; a hook that hangs, or is slow "
        "every time, misses every time, on every runner.")
