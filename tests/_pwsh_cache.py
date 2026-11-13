"""A private pwsh startup cache for every PowerShell a test starts (DEF-4115).

pwsh keeps a startup cache in the user's profile
(``~/.cache/powershell/StartupProfileData-NonInteractive`` on POSIX), which a
start writes (measured 2026-11-13: one start under an empty private directory
left the file in it). Parallel xdist workers starting pwsh under the one file
can write it together: on 2026-11-12 a corrupt copy made
every pwsh start on the Air abort with ``Stack overflow`` until the file was
moved aside, and two concurrent differential runs did the same on 2026-09-10
(``memory/one-writer-per-shared-state.md``).

:func:`private_cache_env` is the environment a test hands a pwsh it starts:
``XDG_CACHE_HOME`` points at a directory this thread of this test process alone
owns, the shape ``bench/powershell_reachability_differential.py`` gives each run
(``_RUN_CACHE_DIR``). A thread waits on each pwsh it starts, so a directory per
thread gives each cache one writer: an xdist worker is a process of its own, a
forked child makes its own (the key holds the pid), and the host-binding test's
pool of four threads gets four. A test that keeps two pwsh running from one
thread (a ``Popen`` it does not wait on) would share one directory between
them; none does today. ``tests/test_test_suite_contract.py`` holds the pwsh
spawns under tests/ to this helper, and ``tests/test_pwsh_cache.py`` drives a
real pwsh to show the cache lands here and not in the user's profile.

Each directory carries this process's pid lock under a prefix on
``tests/_temp_sweep.py``'s ``OWNED_PREFIXES``, so a killed run's cache goes at
the suite's next session start; a run that ends removes it at exit.

Windows is not redirected, and this says why. pwsh there keeps the cache under
the user's ``LOCALAPPDATA`` known folder, which ``XDG_CACHE_HOME`` does not move
(the differential's docstring); whether setting ``LOCALAPPDATA`` in the child
moves it is not measured, and both recorded corruptions are the Air's. The
helper hands Windows the environment it was given: ``None`` (the child
inherits this process's, exactly) with no base, a copy of the base otherwise.
"""
from __future__ import annotations

import atexit
import os
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tests._temp_sweep import deleter, remove, write_lock

#: The prefix of each cache directory, on ``OWNED_PREFIXES``.
PREFIX = "test-pwsh-cache-"
#: Whether this host's pwsh reads its startup cache under ``XDG_CACHE_HOME``.
REDIRECTS = os.name != "nt"

_LOCK = threading.Lock()
#: (pid, thread ident) -> the cache directory that thread made. The pid is in
#: the key so a forked child, which inherits this mapping, makes its own rather
#: than sharing the parent's; the thread so a pool's threads get one each.
_OWNED: dict[tuple[int, int], Path] = {}


def _remove_if_ours(directory: Path, pid: int, rm: Any) -> None:
    """At exit, remove ``directory`` only in the process that made it: a forked
    child inherits the parent's exit handlers."""
    if os.getpid() == pid:
        remove(directory, rm)


def cache_dir() -> Path:
    """This thread's private pwsh cache directory, made on its first use."""
    key = (os.getpid(), threading.get_ident())
    with _LOCK:
        if key not in _OWNED:
            directory = Path(tempfile.mkdtemp(prefix=PREFIX))
            write_lock(directory)
            atexit.register(_remove_if_ours, directory, key[0], deleter())
            _OWNED[key] = directory
        return _OWNED[key]


def private_cache_env(base: Mapping[str, str] | None = None) -> dict[str, str] | None:
    """The environment for a pwsh a test starts, whose startup cache is this
    thread's own: on POSIX a copy of ``base`` (``os.environ`` when None) with
    ``XDG_CACHE_HOME`` set to :func:`cache_dir`; on Windows ``base`` copied, or
    None with no base, so the child inherits (the module docstring says why)."""
    if not REDIRECTS:
        return None if base is None else dict(base)
    env = dict(os.environ if base is None else base)
    env["XDG_CACHE_HOME"] = str(cache_dir())
    return env
