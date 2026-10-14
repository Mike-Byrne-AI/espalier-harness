"""The bounded spawn for the engine: ``subprocess.run`` whose ``timeout``
holds on Windows too (DEF-3004).

Twin of ``tools/cc/_json_safe.py::run_bounded`` because ``espalier/`` cannot
import from ``tools/cc/`` (the isolation rule). The stdlib-only scanners
cannot import this module either, so ``espalier/scanners/freshness.py`` keeps
a third copy inline. The three bodies -- ``run_bounded``, ``_is_stdlib_run``
and ``_end_tree`` -- and the grace constant are held equal by
``tests/test_contracts.py::TestTheBoundedSpawnTwins``: change one copy and
the others in the same commit, and never dedup them.

Every timed spawn in ``espalier/``, ``scripts/``, ``bench/`` and ``tools/``
outside ``tools/cc`` calls one of the copies (``scripts/``, ``bench/`` and
``tools/`` load the ``tools/cc`` one by path from their own checkout), and
``tests/test_contracts.py::TestEveryTimedSpawnOutsideToolsCcIsBounded``
refuses a raw ``subprocess.*`` call with a ``timeout`` anywhere else;
``tests/test_spawn_chokepoint.py::TestEveryTimedSpawnIsBounded`` holds
``tools/cc`` the same way.
"""
from __future__ import annotations

import os
import sys
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # the annotation only; subprocess stays a lazy import, as in the tools/cc copy
    import subprocess

#: What :func:`run_bounded` adds to a timeout on Windows: one deadline for the
#: tree kill, the drain of what was written and the reap of the child.
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
