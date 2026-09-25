"""Substitute CPython 3.10-era ``pathlib`` behaviour onto the running
interpreter, so a version-gated defect reproduces on a 3.14 dev host. Two
emulations live here: the 3.10--3.13 probe bodies (``legacy_pathlib_probes``,
the EACCES class the rest of this docstring is about) and the 3.10--3.11
construction-time refusal (``legacy_path_construction``, at the bottom: the
floor interpreter's session abort, D2, whose control is the inner-session row's
WITHOUT arm rather than the negative control below).

WHY THIS EXISTS. ``Path.exists``, ``is_file``, ``is_dir`` and ``is_symlink``
share one ``_ignore_error`` table. It admits ENOENT / ENOTDIR / EBADF / ELOOP
and does **not** admit EACCES, so on 3.10--3.13 all four RAISE on a path whose
parent cannot be traversed. CPython 3.14 rewrote them over ``os.path.*``, which
swallows every OSError. The same call therefore answers on the dev host and
raises on four of the five supported interpreters -- green locally, red in CI.

It has bitten twice. ``tests/test_integrity.py``'s own platform guard raised
from ``Path.exists()`` (CI run 31731067158, the 3.10 and 3.11 legs); fixing only
that moved the identical raise one frame down into
``_integrity._manifest_is_symlinked``, where a review caught it before it
shipped a second red.

THE METHOD POINT, which outlives this bug. ``docs/FAILURE_MODES.md`` 13.7 says
the earn-the-red has a platform ceiling: some reds cannot be earned on the dev
host. That is true of a ceiling you cannot emulate -- a Windows ACL, a root
bypass, a filesystem semantic. It is NOT true of a pure-Python stdlib body,
which is ~40 lines to transcribe. Reaching for the ceiling too early costs the
behavioural test, and a behavioural test RUNS THE PRODUCT CODE, which a static
lint over ``tests/`` structurally cannot. That is exactly what let the second
instance through. Before invoking 13.7, ask whether the divergent behaviour is
emulatable; if it is, emulate it.

Patch scope is deliberately narrow -- the context manager restores on exit, and
nothing here changes behaviour for paths the process can read, so a probe inside
the block that is not permission-denied answers exactly as it does outside.
It is process-safe but NOT thread-safe: these are globals on ``Path``.

KNOWN SUPERSET, recorded rather than papered over. ``follow_symlinks`` reached
``exists`` in 3.12 and ``is_file``/``is_dir`` in 3.13 only, while the bodies
below accept it on every emulated version. So a product call spelled
``p.is_file(follow_symlinks=False)`` would pass under this emulation and
``TypeError`` on a real 3.10--3.12 -- the emulation would mask the very class it
exists to catch. No product code passes the kwarg today; if one starts to, this
is the first place to tighten.
"""
from __future__ import annotations

import contextlib
import errno
import stat as _stat
from pathlib import Path

# CPython 3.10--3.13 ``Lib/pathlib.py::_IGNORED_ERRNOS`` (3.13: ``pathlib/_abc.py``;
# 3.10 spells it ``_IGNORED_ERROS``, CPython's own typo). EACCES is absent from
# it, and that omission IS the defect class -- do not "fix" this tuple, it is a
# transcription of upstream, not a policy of ours. That instruction is NOT
# self-enforcing prose: ``probes_raise_on_eacces`` below is asserted as a
# negative control by every test that uses the probe bodies, so adding EACCES
# here reds those tests instead of silently making them vacuous.
_IGNORED_ERRNOS = (errno.ENOENT, errno.ENOTDIR, errno.EBADF, errno.ELOOP)


def _ignore_error(exception: BaseException) -> bool:
    """Upstream ``_ignore_error``, minus its ``_IGNORED_WINERRORS`` clause.

    The omission is deliberate and inert: POSIX raises carry no ``winerror``,
    and Windows access-denied is winerror 5, which is not in upstream's
    ``(21, 123, 1921)`` -- so the EACCES path this module exists to reproduce
    re-raises identically either way.
    """
    return getattr(exception, "errno", None) in _IGNORED_ERRNOS


def _legacy_exists(self: Path, *, follow_symlinks: bool = True) -> bool:
    try:
        self.stat() if follow_symlinks else self.lstat()
    except OSError as exc:
        if not _ignore_error(exc):
            raise
        return False
    except ValueError:
        return False
    return True


def _legacy_is_symlink(self: Path) -> bool:
    try:
        return _stat.S_ISLNK(self.lstat().st_mode)
    except OSError as exc:
        if not _ignore_error(exc):
            raise
        return False
    except ValueError:
        return False


def _legacy_is_file(self: Path, *, follow_symlinks: bool = True) -> bool:
    try:
        st = self.stat() if follow_symlinks else self.lstat()
        return _stat.S_ISREG(st.st_mode)
    except OSError as exc:
        if not _ignore_error(exc):
            raise
        return False
    except ValueError:
        return False


def _legacy_is_dir(self: Path, *, follow_symlinks: bool = True) -> bool:
    try:
        st = self.stat() if follow_symlinks else self.lstat()
        return _stat.S_ISDIR(st.st_mode)
    except OSError as exc:
        if not _ignore_error(exc):
            raise
        return False
    except ValueError:
        return False


_REPLACEMENTS = {
    "exists": _legacy_exists,
    "is_symlink": _legacy_is_symlink,
    "is_file": _legacy_is_file,
    "is_dir": _legacy_is_dir,
}


#: The host's flavour, captured at import -- as upstream's ``_Flavour.is_supported``
#: was on 3.10--3.11 (``os.name == 'nt'`` evaluated once, at pathlib import).
_HOST_IS_NT = __import__("os").name == "nt"
_ORIGINAL_PATH_NEW = Path.__dict__["__new__"]


def _legacy_path_new(cls, *args, **kwargs):
    """CPython 3.10--3.11 ``Path.__new__``'s refusal, transcribed.

    Upstream: ``cls = WindowsPath if os.name == 'nt' else PosixPath``, build,
    then ``if not self._flavour.is_supported: raise NotImplementedError``. The
    flavour's ``is_supported`` was fixed at import, so under a patched
    ``os.name`` the chosen class and the host disagree and construction
    refuses. 3.12 dropped the check from ``Path.__new__`` (it calls
    ``object.__new__``) and moved the refusal onto the unsupported class's own
    ``__new__``, which ``Path(...)`` never reaches -- so on 3.12+ construction
    succeeds under the patch and only a DERIVED path refuses. This body puts
    the 3.10 refusal back at construction so a red that only 3.10/3.11 can
    show is earnable on the dev host.
    """
    import os
    from pathlib import PosixPath, WindowsPath
    if cls is Path:
        cls = WindowsPath if os.name == "nt" else PosixPath
    if (cls is WindowsPath) != _HOST_IS_NT:
        raise NotImplementedError("cannot instantiate %r on your system" % (cls.__name__,))
    return _ORIGINAL_PATH_NEW.__func__(cls, *args, **kwargs)


@contextlib.contextmanager
def legacy_path_construction():
    """Run the block with 3.10--3.11's construction-time refusal in force.

    Global on ``Path`` like the probe bodies above, and for the same reason:
    a path the host can build answers exactly as before, so only a bare
    ``Path`` built under a patched ``os.name`` sees any difference. Used by the
    inner-session row in ``tests/test_write_guard.py`` to make the floor
    interpreter's session abort (D2) reproduce on every interpreter.
    """
    try:
        Path.__new__ = staticmethod(_legacy_path_new)
        yield
    finally:
        Path.__new__ = _ORIGINAL_PATH_NEW


@contextlib.contextmanager
def legacy_pathlib_probes():
    """Run the block with the 3.10--3.13 probe bodies in force.

    Keep the block SHORT and around the call under test. These are global on
    ``Path``, so anything else executing inside -- pytest's own collection, a
    fixture teardown -- also sees them. That is harmless for readable paths (the
    bodies agree there) and is the point for denied ones.
    """
    saved = {name: getattr(Path, name) for name in _REPLACEMENTS}
    try:
        for name, fn in _REPLACEMENTS.items():
            setattr(Path, name, fn)
        yield
    finally:
        for name, fn in saved.items():
            setattr(Path, name, fn)


def probes_raise_on_eacces(path: Path) -> bool:
    """True when this interpreter's own ``Path.exists`` re-raises EACCES.

    The self-check for the emulation: on 3.10--3.13 it is already True without
    patching, so the context manager above is a no-op there rather than a lie
    about what is being tested. ``path`` must be under a directory the caller
    has already made untraversable.
    """
    try:
        path.exists()
    except OSError:
        return True
    return False
