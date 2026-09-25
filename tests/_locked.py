"""Lock a path for the duration of a block, the way every permission test in
this suite should: the lock is asserted to have TAKEN (else the test skips,
rather than reds with an unrelated message, on a filesystem that does not
enforce the bits), the probes that assert it are EACCES-safe on every
supported interpreter, and the original bits come back in a ``finally``
however the block ends.

Why one helper. Five tests in one lane (DEF-763) locked a directory five
ways, each restoring in its own ``finally`` and none asserting the lock took;
and ``tests/test_test_suite_contract.py``'s EACCES guard recognises a literal
``chmod(0)`` and nothing else, so a variable mode or a nested context manager
hid those denial windows from the guard entirely. A function that calls
:func:`locked` IS a denial block to that guard (``_LOCKING_HELPERS`` there),
so its body is scanned for the version-gated probes like any other.

The probes here are ``os.stat`` / ``os.scandir`` / ``open``, never a pathlib
existence method: those raise through a locked parent on CPython 3.10-3.13
and swallow on 3.14 (``tests/_legacy_pathlib.py``), which is the very class
this helper serves. Root and Windows callers skip before any chmod.
"""
from __future__ import annotations

import contextlib
import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest


def _lock_is_enforced(path: Path, mode: int) -> bool:
    """True when the OS refuses at least one operation ``mode`` withholds.

    For a directory: without the search bit a child cannot be stat'ed;
    without the read bit the directory cannot be listed. For a file: without
    the read bit it cannot be opened. A mode that withholds nothing this
    function can probe reads as not enforced, which a caller should treat as
    "you did not lock anything".
    """
    try:
        info = os.stat(path)
    except OSError:
        return False
    if not stat.S_ISDIR(info.st_mode):
        if mode & stat.S_IRUSR:
            return False
        try:
            with open(path, "rb"):
                pass
        except PermissionError:
            return True
        except OSError:
            return False
        return False
    denied = False
    if not mode & stat.S_IWUSR:
        # Without the write bit a child cannot be created -- the refusal a
        # tree removal meets (DEF-734: unlink of a child is governed by the
        # PARENT's write bit on POSIX). A create that succeeds means the bits
        # are not enforced; take the probe back out so the caller's tree is
        # what it built.
        probe = os.path.join(path, "probe-write")
        try:
            fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except PermissionError:
            denied = True
        except OSError:
            pass
        else:
            # The probe must not become the unrelated red this helper exists
            # to prevent; a probe that cannot be removed is left for tmp_path.
            with contextlib.suppress(OSError):
                os.close(fd)
            with contextlib.suppress(OSError):
                os.unlink(probe)
    if not mode & stat.S_IXUSR:
        try:
            os.stat(os.path.join(path, "probe-child"))
        except PermissionError:
            denied = True
        except OSError:
            pass
    if not mode & stat.S_IRUSR:
        try:
            with os.scandir(path):
                pass
        except PermissionError:
            denied = True
        except OSError:
            pass
    return denied


@contextlib.contextmanager
def locked(path: Path, mode: int = 0) -> Iterator[Path]:
    """``chmod(path, mode)`` for the block; skip when the OS does not enforce
    it; restore the original bits in ``finally``.

    Keep the block around the call under test. The skip is raised INSIDE the
    ``try`` so the bits are restored before pytest sees it.
    """
    if os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0):
        pytest.skip("needs POSIX permission bits and a non-root user")
    original = stat.S_IMODE(os.stat(path).st_mode)
    os.chmod(path, mode)
    try:
        if not _lock_is_enforced(path, mode):
            pytest.skip("the filesystem does not enforce the permission bits")
        yield path
    finally:
        os.chmod(path, original)
