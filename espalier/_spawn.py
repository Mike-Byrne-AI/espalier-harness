"""The bounded spawn for the engine: ``subprocess.run`` whose ``timeout``
holds on Windows too (DEF-3004).

Twin of ``tools/cc/_json_safe.py::run_bounded`` because ``espalier/`` cannot
import from ``tools/cc/`` (the isolation rule). The stdlib-only scanners
cannot import this module either, so ``espalier/scanners/freshness.py`` keeps
a third copy inline. The three bodies -- ``run_bounded``, ``_is_stdlib_run``
and ``_end_tree`` -- and the grace constant are held equal by
``tests/test_contracts.py::TestTheBoundedSpawnTwins``: change one copy and
the others in the same commit, and never dedup them. The same test holds
:func:`run_tree_bounded` and everything it reaches equal to the ``tools/cc``
copy (DEF-5090): the engine's timed pytests take it, so their timeout ends
the whole tree on POSIX too, where ``run_bounded``'s kills the child alone.

Every timed spawn in the production code outside ``tools/cc`` -- the engine,
``scripts/``, ``bench/``, the top-level ``tools/`` -- calls one of the copies
(the engine through :func:`run_no_stdin`, or :func:`run_tree_bounded` for a
child that is itself a tree; ``scripts/``, ``bench/`` and
``tools/`` load the ``tools/cc`` one by path from their own checkout), or is a
call that holds no pipe, marked ``# spawn: ok <reason>``. ``tests/test_contracts.py::
TestEveryTimedSpawnOutsideToolsCcIsBounded`` refuses any other raw
``subprocess.*`` call with a ``timeout``;
``tests/test_spawn_chokepoint.py::TestEveryTimedSpawnIsBounded`` holds
``tools/cc`` the same way. Test code is out of scope.

Every spawn in the engine's own source, timed or not, goes through
:func:`run_no_stdin`, which hands the child a closed standard input unless the
caller feeds it (DEF-928), or, for a child that is itself a tree (a pytest),
through :func:`run_tree_bounded` with ``stdin=subprocess.DEVNULL`` given at the
call; ``tests/test_contracts.py::TestEveryEngineSpawnClosesItsChildsStdin``
refuses one that goes around both, and a tree run that hands on stdin.

A caller that answers in place of a program that never started -- git
missing, or a shim that is not on PATH -- calls :func:`spawn_checked`, the
hooks' contract (DEF-985): argv[0] resolved first (a bare name on PATH alone,
never in the current directory) and a
:class:`SpawnFailure` handed back, which the caller says with
:func:`say_unstarted` (once per program per process) before it answers.
``tests/test_contracts.py::TestNoEngineSpawnFailsToStartInSilence`` refuses
an ``except`` arm that catches a start failure around a spawn and says
nothing, and a ``SpawnFailure`` branch that says nothing; an arm whose silence
is the right answer (an optional program whose fallback answers the same)
says why on its line, ``# fail-open: ok <kind> <reason>``. The ``tools/cc``
modules the engine loads into its own process (``session_resume``
for ``doctor`` and ``recover``, ``_record_fragments`` for the changelog) spawn
through the ``tools/cc`` copy and still hand on stdin.
"""
from __future__ import annotations

import os
import sys
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # the annotation only; subprocess stays a lazy import, as in the tools/cc copy
    import subprocess
    from collections.abc import Sequence

#: What :func:`run_bounded` adds to a timeout on Windows, and
#: :func:`run_tree_bounded` on every OS: one deadline for the tree kill, the
#: drain of what was written and the reap of the child.
SPAWN_KILL_GRACE_SECONDS = 2.0


def run_bounded(
    args: Any, *, timeout: float | None = None, input: Any = None,
    capture_output: bool = False, check: bool = False, **kwargs: Any,
) -> "subprocess.CompletedProcess[Any]":
    """``subprocess.run``, whose ``timeout`` bounds the call on Windows too.

    On Windows, ``subprocess.run`` kills only the child at the timeout and then
    reads the pipes with no timeout (CPython's ``run``: ``process.kill()``,
    then ``process.communicate()``), so a grandchild that inherited a pipe sets
    the real bound: the program a ``.bat`` shim starts (pyenv-win's
    ``python.bat``), and git itself, because Git for Windows's
    ``cmd\\git.exe`` is a launcher that runs the real git as its child. So an
    adopter's ``init`` or ``doctor`` probing an interpreter through a shim, or
    any local git read, waited on that program rather than its cap.

    So on Windows with a ``timeout`` the child starts under ``Popen``; at the
    timeout ``taskkill /T /F`` ends its whole tree, and the drain and the reap
    share :data:`SPAWN_KILL_GRACE_SECONDS`. ``TimeoutExpired`` is raised as
    ``run`` raises it, carrying what was read. Everywhere else this IS
    ``subprocess.run``: on POSIX, with no ``timeout``, and where
    ``subprocess.run`` has been replaced (a test's fake: :func:`_is_stdlib_run`).
    A test that swaps a module's own ``subprocess`` name for a stand-in no
    longer reaches a call routed here: patch ``subprocess.run`` itself, or the
    module's ``run_bounded``. The edges are the ``tools/cc`` copy's, stated in
    its docstring.
    """
    import subprocess

    if timeout is None or sys.platform != "win32" or not _is_stdlib_run(subprocess.run, subprocess):
        return subprocess.run(args, timeout=timeout, input=input,  # spawn: ok the bounded spawn itself
                              capture_output=capture_output, check=check, **kwargs)
    if input is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used.")
        kwargs["stdin"] = subprocess.PIPE
    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("stdout and stderr arguments may not be used with capture_output.")
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    proc = subprocess.Popen(args, **kwargs)  # spawn: ok the bounded spawn itself -- Windows with a timeout
    try:
        stdout, stderr = proc.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        end = time.monotonic() + SPAWN_KILL_GRACE_SECONDS
        _end_tree(proc, end)
        try:
            exc.stdout, exc.stderr = proc.communicate(timeout=max(0.05, end - time.monotonic()))
        except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- a holder the tree kill missed keeps its pipe; the bound holds and the TimeoutExpired below says what happened
            pass
        try:
            proc.wait(timeout=max(0.05, end - time.monotonic()))
        except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- a child that outlives TerminateProcess is the OS's now
            pass
        raise
    except BaseException:  # noqa: BLE001 -- Ctrl-C or a write error mid-call: the tree ends under the grace and the error goes on, as run's own handler kills and re-raises
        _end_tree(proc, time.monotonic() + SPAWN_KILL_GRACE_SECONDS)
        try:
            proc.wait(timeout=SPAWN_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- a child that outlives TerminateProcess is the OS's now; the original error is the one to raise
            pass
        raise
    retcode = proc.wait()  # communicate() returned, so it reaped the child: this answers at once
    if check and retcode:
        raise subprocess.CalledProcessError(retcode, proc.args, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(proc.args, retcode, stdout, stderr)


def run_no_stdin(args: Any, *, input: Any = None, **kwargs: Any) -> "subprocess.CompletedProcess[Any]":
    """:func:`run_bounded` with the child's standard input closed unless the
    caller feeds it: ``stdin=subprocess.DEVNULL`` when neither ``input`` nor a
    ``stdin`` is given (a ``stdin`` of ``None`` counts as none). Every spawn in
    the engine's own source goes through here (DEF-928), but for the tree run's
    callers (:func:`run_tree_bounded`, DEF-5090), which pass that ``stdin``
    themselves. A caller that answers in place of a program that never started
    calls :func:`spawn_checked`, which resolves argv[0] first and hands the
    failure back to be said (DEF-985), rather than this.

    A child handed no stdin inherits the parent's, and on Windows a parent whose
    standard-input handle was closed -- by an installer, a CI step or a wrapper
    -- hands on a handle that is no longer valid, so the child never starts:
    ``[WinError 6] The handle is invalid``. ``init`` died that way at its first
    ``git`` read, after writing its seed docs. No engine child reads the
    operator's terminal, so closing it loses nothing. It costs one thing, on
    Windows: a child handed any one of its three handles has the other two
    duplicated from the parent (CPython's ``Popen._get_handles``; with all three
    left alone it duplicates none), so a child that streams to the parent's
    stdout or stderr now fails to start on a dead output handle, where it used to
    start (``tests/test_bounded_spawn.py`` holds the measured case). A caller
    that pipes data passes ``input`` (or a ``stdin`` of its own), which is left
    as given.

    The bounded spawn's own bodies are not touched: ``run_bounded`` is held
    equal to the ``tools/cc`` copy and the freshness scanner's
    (``tests/test_contracts.py::TestTheBoundedSpawnTwins``), and the callers of
    the ``tools/cc`` copy, the hooks among them, keep inheriting stdin. The
    scanner, which cannot import this module, hands each of its spawns a
    ``stdin`` itself. ``run_bounded`` is looked up when this is called, so a
    test that patches ``espalier._spawn.run_bounded`` still reaches every engine
    spawn but the tree run's two (``pre_release._run_command``,
    ``refresh_externals.run_bound_tests``): patch ``subprocess.run`` for those,
    which the tree run hands a stand-in's call to as it is.
    """
    import subprocess

    if input is None and kwargs.get("stdin") is None:
        kwargs["stdin"] = subprocess.DEVNULL
    return run_bounded(args, input=input, **kwargs)


#: The characters a Windows ``.cmd`` or ``.bat`` shim re-parses in its
#: arguments, so one there could run a different command: the hooks'
#: ``_CMD_SHIM_METACHARS``.
_CMD_SHIM_METACHARS = frozenset("&|<>^%")


class SpawnFailure:
    """A program that did not start: the engine's twin of
    ``tools/cc/hooks/_hook_utils.py::SpawnFailure`` (DEF-985), a copy because
    ``espalier/`` imports nothing from ``tools/cc/``. ``error`` is the
    exception's class name, or ``Unresolved`` (argv[0] names no program),
    ``EmptyCommand``, or ``CmdShimMetachar`` (a Windows .cmd/.bat shim re-parses
    its line, so an argument carrying ``&``, ``|``, ``<``, ``>``, ``^`` or ``%``
    could run a different command; refused before it starts). ``resolved`` is
    what argv[0] resolved to, or None; ``detail`` is the exception with its path
    spelled as a path (``espalier._text.os_error_text``), None where nothing was
    raised. A plain class, as the hooks' copy is, for the same reason: a test
    may load this module by path before it is registered."""

    __slots__ = ("argv", "error", "resolved", "detail")

    def __init__(
        self, argv: "tuple[str, ...]", error: str, resolved: "str | None", detail: "str | None" = None,
    ) -> None:
        self.argv = tuple(argv)
        self.error = error
        self.resolved = resolved
        self.detail = detail

    def __repr__(self) -> str:
        return (
            f"SpawnFailure(argv={self.argv!r}, error={self.error!r}, "
            f"resolved={self.resolved!r}, detail={self.detail!r})"
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SpawnFailure) and (
            (self.argv, self.error, self.resolved, self.detail)
            == (other.argv, other.error, other.resolved, other.detail)
        )

    __hash__ = None  # type: ignore[assignment]  # equal by value and mutable: no hash, as a dataclass(eq=True) has none

    @property
    def resolution(self) -> str:
        """The clause a sentence carries: whether argv[0] resolved at all, and
        to what -- "did not resolve" (install it, or put it on PATH) and
        "resolved to X and still could not start" (X is broken or not
        runnable here) are fixed differently."""
        token = self.argv[0] if self.argv else "(empty)"
        if self.error == "EmptyCommand":
            return "the command is empty"
        if self.error == "Unresolved":
            return f"`{token}` did not resolve to a program"
        if self.error == "CmdShimMetachar":
            return (
                f"`{token}` resolved to `{self.resolved}`, a script shim that re-parses its "
                "arguments, and an argument carries a shell metacharacter"
            )
        return f"`{token}` resolved to `{self.resolved}` and still could not start"


def resolve_program(token: str, *, cwd: "str | os.PathLike[str] | None" = None) -> "str | None":
    """argv[0] to the path that would start, or None: the hooks'
    ``resolve_program`` for the engine, a path token read against ``cwd`` where
    the hooks read it against the root they are handed. A bare
    token is looked up on PATH alone (:func:`_on_path`, one function in both
    trees since DEF-2102), honouring PATHEXT on
    Windows, so ``npm`` finds ``npm.cmd`` where ``subprocess`` alone looks only
    for ``npm.exe``; never in the current directory, which ``shutil.which``
    searches first on Windows, so a ``git.cmd`` a cloned tree carries is not
    run by ``espalier doctor .`` from inside it (the code review of 2026-11-17
    drove that shape; ``CreateProcess`` appends only ``.exe``, so before the
    contract only a ``git.exe`` there ran). A token holding a path separator
    resolves against ``cwd`` (the spawn's own, else this process's), and is
    kept when it names a file that is not marked runnable, so the start fails
    and says so."""
    import shutil

    if not token:
        return None
    if os.path.isabs(token) or "/" in token or (os.name == "nt" and "\\" in token):
        candidate = token if os.path.isabs(token) else os.path.join(
            os.fspath(cwd) if cwd is not None else os.getcwd(), token)
        found = shutil.which(candidate)
        if found:
            return found
        return candidate if os.path.isfile(candidate) else None
    return _on_path(token)


def _on_path(token: str) -> "str | None":
    """The first file ``token`` names in an absolute PATH entry that is not the
    current directory: on Windows the token as given when it carries a PATHEXT
    extension, else with each PATHEXT extension in turn (``shutil.which``'s
    order); elsewhere the token, when it is a runnable file. An empty, relative
    or ``.`` entry is skipped: each one is the current directory, or a place
    that moves with it. A current directory removed under this process skips
    no absolute entry, since none can name it, and the lookup goes on: the
    hooks read this before a gate's spawn, where a raise would end the gate.
    One function twice, here and in the other tree's spawn module, held equal
    by ``tests/test_bounded_spawn.py`` (DEF-2102)."""
    try:
        here = os.path.normcase(os.path.abspath(os.getcwd()))
    except OSError:  # fail-open: ok deliberate -- a current directory removed under this process is no absolute entry's place, so only the empty, relative and dot entries below are skipped
        here = ""
    if os.name == "nt":
        pathext = [ext for ext in (os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(os.pathsep) if ext]
        names = [token] if any(token.lower().endswith(ext.lower()) for ext in pathext) else [
            token + ext for ext in pathext]
    else:
        names = [token]
    for entry in os.environ.get("PATH", os.defpath).split(os.pathsep):
        entry = entry.strip('"')
        if not entry or not os.path.isabs(entry) or os.path.normcase(os.path.abspath(entry)) == here:
            continue
        for name in names:
            candidate = os.path.join(entry, name)
            if os.path.isfile(candidate) and (os.name == "nt" or os.access(candidate, os.X_OK)):
                return candidate
    return None


def spawn_checked(argv: "Sequence[Any]", *, input: Any = None, **kwargs: Any) -> "subprocess.CompletedProcess[Any] | SpawnFailure":
    """:func:`run_no_stdin` under the hooks' contract (DEF-985): argv[0] is
    resolved first (:func:`resolve_program`), a Windows script shim with a
    metacharacter argument is refused, and a program that does not start comes
    back as a :class:`SpawnFailure` instead of a raise, so the caller says so
    (:func:`say_unstarted`) where it answers in its place. What a child that
    started does stays the caller's, as before: ``TimeoutExpired``, a
    ``check=True`` exit (``CalledProcessError``) and output that does not
    decode (``UnicodeDecodeError``) propagate. Any other ``OSError`` or
    ``ValueError`` from the spawn is read as a start that failed: on POSIX
    ``Popen`` raises the child's ``exec`` error, on Windows ``CreateProcess``'s,
    and ``ValueError`` is an argument ``Popen`` refuses (a NUL). ``kwargs`` are
    ``subprocess.run``'s; ``run_no_stdin`` is looked up when this is called, so
    a test that patches ``espalier._spawn.run_no_stdin`` reaches it, past the
    resolution."""
    import subprocess

    # A caller's own keyword clash is the caller's bug, never a start that
    # failed: raised here, as subprocess.run raises it, before the try below
    # would read it as one (the failure-mode review of 2026-11-17).
    if input is not None and kwargs.get("stdin") is not None:
        raise ValueError("stdin and input arguments may not both be used.")
    if kwargs.get("capture_output") and (kwargs.get("stdout") is not None or kwargs.get("stderr") is not None):
        raise ValueError("stdout and stderr arguments may not be used with capture_output.")
    args = [str(a) for a in argv]
    if not args:
        return SpawnFailure((), "EmptyCommand", None)
    resolved = resolve_program(args[0], cwd=kwargs.get("cwd"))
    if resolved is None:
        return SpawnFailure(tuple(args), "Unresolved", None)
    if os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")) and any(
        ch in arg for arg in args[1:] for ch in _CMD_SHIM_METACHARS
    ):
        return SpawnFailure(tuple(args), "CmdShimMetachar", resolved)
    try:
        # subprocess-contract: ok the engine's checked chokepoint -- argv is the caller's, argv[0] resolved above; an espalier-signature spawn that routes here carries its own pin at its call site
        return run_no_stdin([resolved, *args[1:]], input=input, **kwargs)
    except (subprocess.SubprocessError, UnicodeDecodeError):
        raise  # the child started: what it did is the caller's, as it was before the contract
    except (OSError, ValueError) as exc:
        from espalier._text import os_error_text

        return SpawnFailure(tuple(args), type(exc).__name__, resolved, os_error_text(exc))


#: The programs :func:`say_unstarted` has named in this process.
_SAID_UNSTARTED: "set[str]" = set()


def say_unstarted(failure: SpawnFailure, consequence: str) -> None:
    """Say on stderr, once per program per process, that a spawn never started
    and what the caller answers in its place (DEF-985): ``consequence``
    completes "so ...". A later failure of the same program says nothing more,
    so a missing ``git`` is one line from the engine, not one per read; the
    line makes no promise about later reads, since the stdlib-only freshness
    scanner keeps its own memo and says its own line. The words are 7-bit
    ASCII; what the failure carries (a path, the OS's message) is written with
    backslash escapes where the stream cannot encode it, and a stream that
    cannot be written at all takes nothing: the caller's answer stands either
    way."""
    token = failure.argv[0] if failure.argv else ""
    if token in _SAID_UNSTARTED:
        return
    _SAID_UNSTARTED.add(token)
    detail = f" ({failure.detail})" if failure.detail else ""
    line = f"espalier: {failure.resolution}{detail}, so {consequence}\n"
    stream = sys.stderr
    if stream is None:
        return
    try:
        encoding = getattr(stream, "encoding", None) or "ascii"
        stream.write(line.encode(encoding, "backslashreplace").decode(encoding, "replace"))
        stream.flush()
    except (OSError, ValueError, LookupError):  # fail-open: ok deliberate -- a closed or unencodable stderr cannot carry the line, and the caller's answer stands without it
        pass


def _is_stdlib_run(run: Any, subprocess_module: Any) -> bool:
    """Whether ``run`` is the standard library's own ``subprocess.run``: its
    code was compiled from the ``subprocess`` module's own file. A stand-in
    defined anywhere else is not -- a lambda, a ``MagicMock`` (no code at all),
    or a ``functools.wraps`` spy, which copies the name and the module but not
    the code."""
    code = getattr(run, "__code__", None)
    origin = getattr(subprocess_module, "__file__", None)
    if code is None or not origin:
        return False
    return os.path.normcase(os.path.abspath(code.co_filename)) == os.path.normcase(os.path.abspath(origin))


def _end_tree(proc: "subprocess.Popen[Any]", end: float) -> None:
    """End ``proc`` and every process below it (Windows): ``taskkill /T /F``
    by pid, from System32 so no PATH entry can stand in for it, with no pipe
    of its own to wait on; then ``kill`` the child itself, which covers a
    ``taskkill`` that could not start or found the tree already gone."""
    import subprocess

    taskkill = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
    try:
        subprocess.run(  # spawn: ok the bounded spawn's tree kill -- no pipes, its own timeout
            [taskkill, "/T", "/F", "/PID", str(proc.pid)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=max(0.05, end - time.monotonic()),
        )
    except (OSError, subprocess.SubprocessError):  # fail-open: ok deliberate -- the kill below still ends the child, and the drain's deadline holds either way
        pass
    try:
        proc.kill()
    except OSError:  # fail-open: ok deliberate -- the child already ended
        pass


def run_tree_bounded(
    args: Any, *, timeout: float | None = None, input: Any = None,
    capture_output: bool = False, check: bool = False, **kwargs: Any,
) -> "subprocess.CompletedProcess[Any]":
    """:func:`run_bounded`, whose timeout ends the child's whole tree on every OS.

    The engine's twin of ``tools/cc/_json_safe.py::run_tree_bounded`` (DEF-5090),
    for an engine child that is itself a tree of work: the not-heavy suite
    ``espalier pre-release`` runs (``espalier/pre_release.py::_run_command``)
    and the pins' cited tests ``espalier refresh-externals --apply`` runs
    (``espalier/refresh_externals.py::run_bound_tests``). ``subprocess.run``'s
    timeout kills the child alone on POSIX, and the pytest's hooks, git and any
    server a test started ran on at parent 1. At the timeout, and on any
    exception while it waits, the child and every process below it are ended,
    and ``TimeoutExpired`` (or that exception) is raised; the kill, the drain
    and the reap share :data:`SPAWN_KILL_GRACE_SECONDS`.

    It does not close the child's stdin, as the ``tools/cc`` copy does not: an
    engine caller passes ``stdin=subprocess.DEVNULL`` itself (DEF-928), and
    ``tests/test_contracts.py::TestEveryEngineSpawnClosesItsChildsStdin``
    refuses an engine call here that does not. ``start_new_session``,
    ``process_group`` and ``preexec_fn`` are refused on POSIX; on Windows the
    child goes into a kill-on-close job object. The reasons and the three edges
    are the ``tools/cc`` copy's docstring; ``tests/test_contracts.py::
    TestTheBoundedSpawnTwins`` holds the code equal, so change both together.
    """
    import subprocess

    if sys.platform != "win32":
        held = [name for name, given in (("start_new_session", bool(kwargs.get("start_new_session"))),
                                         ("process_group", kwargs.get("process_group") is not None),
                                         ("preexec_fn", kwargs.get("preexec_fn") is not None)) if given]
        if held:
            raise ValueError(
                f"run_tree_bounded refuses {', '.join(held)}: its child starts in the caller's own "
                "process group so an ancestor's group kill (scripts/fresh_clone_gate.py's, "
                "scripts/archive_probe.py's) still reaches the tree, and its own kill walks the tree")
    if not _is_stdlib_run(subprocess.run, subprocess):
        return subprocess.run(args, timeout=timeout, input=input,  # spawn: ok a test's stand-in for run, which has no tree
                              capture_output=capture_output, check=check, **kwargs)
    if input is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used.")
        kwargs["stdin"] = subprocess.PIPE
    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("stdout and stderr arguments may not be used with capture_output.")
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    proc = subprocess.Popen(args, **kwargs)  # spawn: ok the tree-bounded run itself
    job = _kill_on_close_job(proc) if sys.platform == "win32" else None
    stdout, stderr = _communicate_or_end_the_tree(proc, input, timeout, job)
    retcode = proc.wait()  # communicate() returned, so it reaped the child: this answers at once
    if check and retcode:
        raise subprocess.CalledProcessError(retcode, proc.args, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(proc.args, retcode, stdout, stderr)


def _communicate_or_end_the_tree(proc: Any, input: Any, timeout: "float | None", job: Any) -> "tuple[Any, Any]":
    """``proc``'s output by ``timeout``; at the timeout, or on any exception
    while it waits, its whole tree ended (:func:`_end_the_whole_tree`), and
    the drain and the reap held to one grace from the kill."""
    import subprocess

    try:
        return proc.communicate(input, timeout=timeout)  # spawn: ok the tree-bounded wait itself
    except subprocess.TimeoutExpired as exc:
        end = time.monotonic() + SPAWN_KILL_GRACE_SECONDS
        _end_the_whole_tree(proc, end, job)
        try:
            exc.stdout, exc.stderr = proc.communicate(timeout=max(0.05, end - time.monotonic()))  # spawn: ok the drain after the tree kill
        except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- a holder the walk missed keeps its pipe; the bound holds and the TimeoutExpired below says what happened
            pass
        try:
            proc.wait(timeout=max(0.05, end - time.monotonic()))
        except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- a child that outlives SIGKILL is the OS's now
            pass
        raise
    except BaseException:  # noqa: BLE001 -- Ctrl-C or the per-test ceiling mid-wait: the tree ends under the grace and the error goes on, where run's own handler kills the child alone
        end = time.monotonic() + SPAWN_KILL_GRACE_SECONDS
        _end_the_whole_tree(proc, end, job)
        try:
            proc.wait(timeout=max(0.05, end - time.monotonic()))
        except subprocess.TimeoutExpired:  # fail-open: ok deliberate -- a child that outlives SIGKILL is the OS's now; the original error is the one to raise
            pass
        raise


def _end_the_whole_tree(proc: Any, end: float, job: Any = None) -> None:
    """End ``proc`` and every process below it by ``end``, from no group of
    its own: on Windows the ``taskkill /T`` walk then the job
    (:func:`_end_the_tree_now`), or the job alone once ``proc`` is reaped; on
    POSIX a walk of the process table that stops each process below the child
    until a read finds none new, then kills every one it stopped and the group
    of each that leads one other than the caller's. The order and its reasons
    are the ``tools/cc`` copy's docstring."""
    if sys.platform == "win32":
        if proc.returncode is None:
            _end_the_tree_now(proc, job, end)
        elif job is not None:
            _terminate_job(job)
        return
    import signal

    me, my_group = os.getpid(), os.getpgid(0)
    tried: set[int] = set()
    stopped: set[int] = set()
    leaders: set[int] = set()
    walked = unread = False
    try:
        while proc.returncode is None and time.monotonic() < end:
            read = _process_table(end)
            if read is None:
                unread = not walked
                break
            if read.get(proc.pid, (None, None))[0] != me:
                break
            walked = True
            new = _below(proc.pid, read) - tried - {me}
            if not new:
                break
            for pid in new:
                tried.add(pid)
                leads = read[pid][1] == pid
                # Recorded before the stop, so an interrupt landing just after
                # it still finds the pid in the set the kill below reads.
                stopped.add(pid)
                if leads:
                    leaders.add(pid)
                try:
                    os.kill(pid, signal.SIGSTOP)
                except OSError:  # fail-open: ok deliberate -- it ended between the read and the stop, or is not ours to stop; it leaves both sets
                    stopped.discard(pid)
                    leaders.discard(pid)
    finally:
        for pid in stopped:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:  # fail-open: ok deliberate -- it already ended
                pass
        if unread and proc.returncode is None:
            try:
                if os.getpgid(proc.pid) == proc.pid:
                    leaders.add(proc.pid)
            except OSError:  # fail-open: ok deliberate -- the child already ended
                pass
        for group in leaders - {my_group}:
            try:
                os.killpg(group, signal.SIGKILL)
            except OSError:  # fail-open: ok deliberate -- the group already ended
                pass
        try:
            proc.kill()
        except OSError:  # fail-open: ok deliberate -- the child already ended
            pass


#: The process-table read: every process's pid, parent pid and process group,
#: no header, each column its own ``-o`` (POSIX reads the text after ``=`` as
#: the header for the rest of its argument). The ``tools/cc`` copy's spelling.
PS_TABLE_ARGV = ("ps", "-A", "-o", "pid=", "-o", "ppid=", "-o", "pgid=")


def parse_process_table(text: str) -> "dict[int, tuple[int, int]] | None":
    """``ps`` output in the :data:`PS_TABLE_ARGV` shape as ``pid -> (ppid,
    pgid)``; ``None`` for a table with no rows, which no host has (the reader
    is in it), never ``{}``, which reads as a host with no processes."""
    table: "dict[int, tuple[int, int]]" = {}
    for line in text.splitlines():
        cells = line.split()
        if len(cells) == 3 and all(c.isdigit() for c in cells):
            table[int(cells[0])] = (int(cells[1]), int(cells[2]))
    return table or None


def _process_table(end: float) -> "dict[int, tuple[int, int]] | None":
    """Every process as ``pid -> (ppid, pgid)``, read from ``ps`` by ``end``
    (``/bin/ps`` first, so no PATH entry can stand in for it); ``None`` where
    it cannot be read."""
    import shutil
    import subprocess

    ps = "/bin/ps" if os.path.exists("/bin/ps") else shutil.which("ps")
    if not ps:
        return None
    try:
        # The shared spelling, its program name first; ``executable`` is the
        # program that runs.
        out = subprocess.run(  # spawn: ok the tree walk's table read -- no input, its own timeout
            ["ps", *PS_TABLE_ARGV[1:]], executable=ps,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=max(0.05, end - time.monotonic()),
        )
    except (OSError, subprocess.SubprocessError):  # fail-open: ok deliberate -- the kill of the child alone still runs
        return None
    if out.returncode != 0:
        return None
    return parse_process_table(out.stdout)


def _below(root: int, table: "dict[int, tuple[int, int]]") -> "set[int]":
    """``root`` and every process below it in ``table``, by parent pid."""
    children: "dict[int, list[int]]" = {}
    for pid, (ppid, _group) in table.items():
        children.setdefault(ppid, []).append(pid)
    tree, todo = {root}, [root]
    while todo:
        for child in children.get(todo.pop(), ()):
            if child not in tree:
                tree.add(child)
                todo.append(child)
    return tree


def _end_the_tree_now(proc: Any, job: Any, end: float) -> None:
    """Kill ``proc`` and every process below it, by ``end``: ``killpg`` of its
    own session on POSIX; on Windows the tree walk (``taskkill /T``, then the
    child itself) while every parent in the tree is alive, then
    ``TerminateJobObject`` for whatever the walk left in the job."""
    if os.name == "nt":
        _end_tree(proc, end)
        if job is not None:
            _terminate_job(job)
        return
    import signal

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:  # fail-open: ok deliberate -- the group is already gone; the kill below covers a child outside it
        pass
    try:
        proc.kill()
    except OSError:  # fail-open: ok deliberate -- the child already ended
        pass


def _terminate_job(job: Any) -> None:
    """End every process in the Windows job object ``job`` (a handle from
    :func:`_kill_on_close_job`); the handle stays open, as that function
    says."""
    import ctypes

    ctypes.WinDLL("kernel32", use_last_error=True).TerminateJobObject(ctypes.c_void_p(job), 1)


def _kill_on_close_job(proc: Any) -> "int | None":
    """A Windows job object holding ``proc``, set to kill every process in it
    when its last handle closes, as its handle; ``None`` where one cannot be
    made or assigned (the kill's ``taskkill /T`` walk still runs; only the
    close-time backstop is lost). The handle is never closed here: it closes
    with this process, which is the backstop that ends the tree when this
    process is ended from outside."""
    try:
        import ctypes
        from ctypes import wintypes

        class _Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", ctypes.c_ulonglong * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, wintypes.UINT]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        extended_limit_information = 9
        if (kernel32.SetInformationJobObject(job, extended_limit_information, ctypes.byref(info), ctypes.sizeof(info))
                and kernel32.AssignProcessToJobObject(job, int(proc._handle))):
            return int(job)
        kernel32.CloseHandle(job)
    except (ImportError, OSError, AttributeError, ValueError, TypeError):  # fail-open: ok deliberate -- no job object: the kill's taskkill /T walk still runs, and only the close-time backstop is lost
        pass
    return None
