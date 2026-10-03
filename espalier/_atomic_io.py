"""Atomic file writes for engine-side state (TP-R9 B2/B3/B4).

Mirrors ``tools/cc/hooks/_hook_utils.atomic_write_text`` because
``espalier/`` cannot import from ``tools/cc/`` (isolation rule --
hook scripts are copied verbatim into client repos and run standalone,
so they get their own copy of the helper). Same algorithm; same
guarantees; one addition stated in the docstring below: this copy takes
a ``follow_symlinks`` keyword for the adopter's own files.

Use for every file the engine writes into an adopter's tree -- the JSON
state hook subprocesses read concurrently (``reports/repo_fingerprint.json``,
``reports/harness_config.json``, ``.espalier/integrity.json``), and equally
the cc/ docs, the seeds, the fused tree's stubs and the settings unwire on
uninstall. A whole-file write by any spelling -- ``write_text``,
``write_bytes``, a ``json``/``pickle`` dump, ``open`` in a writing mode, an
``os.open`` with a create flag, a ``shutil`` copy -- anywhere in
``espalier/`` outside the ``_vendor/`` byte mirror and the stdlib-only
``scanners/`` is what
``tests/test_atomic_io.py::TestEveryEngineWriteOfAdopterStateIsAtomic``
reds on; the exemptions carry their reason in its rosters (append-only
logs, lock files, the fused output tree, an ``--out`` that is not a
regular file). ``atomic_write_bytes`` is the verbatim twin for a copy of an
existing file (a settings backup, the CI gate script), where a text
round-trip would rewrite the line endings.

What a write does to the target's IDENTITY -- its mode, a symlink at its
path, a second hardlinked name -- is the contract ``docs/CONVENTIONS.md``
"Atomic whole-file writes" states and ``tests/test_atomic_io.py``
(``TestTargetMode``, ``TestSymlinkedTarget``) pins over every copy; the
copies themselves are a derived roster there (``_REPLACE_WRITERS``), so a
fifth inlined writer reds instead of escaping the contract.
"""
from __future__ import annotations

import os
import stat
import sys
import time
from pathlib import Path
from typing import IO, Any

# Flags for the writer's per-call tempfile: create-exclusive, never following
# a symlink planted at the random name, binary on Windows so the CRT does not
# translate newlines under the text layer. The POSIX-only flags fall back to
# 0, a no-op OR (docs/SHARP_EDGES.md "POSIX-only os.O_* flags need getattr
# guards for Windows").
_TEMPFILE_OPEN_FLAGS = (
    os.O_RDWR | os.O_CREAT | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_BINARY", 0)
)


#: ``os.replace`` attempts. Windows refuses a rename onto a file another handle
#: holds open -- a reader, or a writer mid-replace -- with ``PermissionError``,
#: so a writer racing one retries there, about a second in all; elsewhere a
#: refusal is real and raises at once. Inlined at the replace (never a helper)
#: so tests/test_atomic_io.py::_REPLACE_WRITERS keeps its roster.
_REPLACE_ATTEMPTS = 20 if sys.platform == "win32" else 1
_REPLACE_BACKOFF_S = 0.005


def atomic_write_text(
    path: Path, content: str, *, encoding: str = "utf-8", follow_symlinks: bool = False,
) -> None:
    """Write ``content`` to ``path`` atomically via tempfile + ``os.replace``.

    Concurrent readers (parallel CC sessions, hook subprocesses) see
    either the old contents or the new contents -- never a torn/truncated
    file. The tempfile is created in the target's parent dir so
    ``os.replace`` is on the same filesystem (a requirement of POSIX
    atomicity; NTFS provides equivalent semantics via MoveFileEx).

    Parent directories are created as needed. The tempfile is unlinked
    on failure; on success it has been renamed onto ``path``.

    The target's identity survives the write (DEF-783, DEF-784):

    - MODE: an existing regular file keeps the bits it had (the operator's
      ``chmod +x`` on a hook script, ``chmod g+r`` on a settings file); a
      fresh file gets the mode ``open()`` would give under the process
      umask. The helper imposes no mode of its own. (Windows keeps one
      read-only bit and has no ``fchmod``; the mode leg is a no-op there.)
    - SYMLINK, decided per TARGET, not per copy. By default a symlinked
      target is REPLACED by a regular file: harness state under ``cc/``,
      ``.espalier`` and ``reports/`` is the harness's own, the readers of
      it that refuse a symlink (the plan file's ``read_text_nofollow``, the
      freshness cache's and the statusline's ``O_NOFOLLOW`` opens) can read
      what the write leaves, and no adopter manages harness state by
      dotfiles. ``follow_symlinks=True`` is for the adopter's OWN file -- a
      dotfiles-managed ``.gitignore`` or ``settings.json`` -- and rewrites
      the real file in place, its mode with it, keeping the link; the
      retire and the settings merge, repair, rewire and unwire pass it. The
      tools/cc copies carry no keyword: they write state only.
    - HARDLINK: the new bytes are a new inode, so a second name for the old
      one keeps the old bytes. A property of rename-based atomicity, not a
      defect; the harness never hardlinks its own state.

    The tempfile's visible name is capped at 64 chars so it cannot exceed
    Windows MAX_PATH (260) for an unusually long target filename.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if follow_symlinks:
        # Resolved AFTER the mkdir above: a dangling link into a directory
        # that does not exist fails at the create below instead of creating
        # that directory (a dotfiles checkout not cloned yet); init reports
        # the OSError as a one-line manual step. The tempfile lands beside
        # the REAL file, so a write killed between create and replace can
        # leave a `.<name>.<hex>.tmp` in the linked-to directory.
        path = Path(os.path.realpath(path))
    # Opened with mode 0o666 so the kernel applies the umask -- what open()
    # gives a fresh file -- where tempfile.mkstemp hardcodes 0o600 and every
    # file the harness wrote ended group-unreadable (DEF-783).
    prefix = f".{path.name[:64]}."
    for _attempt in range(100):
        tmp_path = os.path.join(str(path.parent), prefix + os.urandom(4).hex() + ".tmp")
        try:
            fd = os.open(tmp_path, _TEMPFILE_OPEN_FLAGS, 0o666)
            break
        except FileExistsError:
            continue
        except PermissionError:
            # NT raises this, not FileExistsError, when a DIRECTORY bears
            # the chosen name (the case tempfile.mkstemp retries); anything
            # else is a real refusal.
            if os.name == "nt" and os.path.isdir(tmp_path):
                continue
            raise
    else:
        raise FileExistsError(f"no free tempfile name beside {path}")
    f = None
    try:
        if hasattr(os, "fchmod"):
            # An existing regular target keeps its bits; a symlink or other
            # non-regular file at the path is not a mode to copy. A refused
            # fchmod leaves the umask mode rather than failing the write.
            try:
                st = os.stat(path, follow_symlinks=False)
                if stat.S_ISREG(st.st_mode):
                    os.fchmod(fd, stat.S_IMODE(st.st_mode))
            except OSError:
                pass
        # newline="" writes \n verbatim. Default text mode translates \n -> \r\n
        # on Windows, which inflates serialized byte-size (defeating size caps
        # that count \n) and breaks cross-platform byte-parity of hashed JSON
        # state. POSIX is unaffected (os.linesep=\n).
        f = os.fdopen(fd, "w", encoding=encoding, newline="")
        with f:
            f.write(content)
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp_path, path)
                break
            except PermissionError:
                # A refusal that cannot clear -- a directory at the target, a
                # read-only file -- raises at once; only a held handle is waited out.
                if (attempt + 1 >= _REPLACE_ATTEMPTS or os.path.isdir(path)
                        or (os.path.exists(path) and not os.access(path, os.W_OK))):
                    raise
                time.sleep(_REPLACE_BACKOFF_S * (attempt + 1))
    except BaseException:  # noqa: BLE001 -- clean up tempfile on any failure, then re-raise
        # ANY failure (OSError on replace, TypeError on non-str content,
        # UnicodeEncodeError, even KeyboardInterrupt mid-write) must unlink
        # the tempfile so no orphan is left, then re-raise the original error.
        if f is None:
            # fdopen itself raised (an unknown encoding): the fd is still ours.
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_bytes(path: Path, data: bytes, *, follow_symlinks: bool = False) -> None:
    """``atomic_write_text`` for bytes: the same tempfile-and-replace, no
    encoding or newline translation, so a copy of an existing file lands
    verbatim or not at all, and the same target-identity contract (mode
    kept, a symlinked target replaced unless ``follow_symlinks``, a
    hardlink severed). Kept as its own body rather than a shared private
    core so the text helper stays byte-identical in shape to the hook-side
    copy it mirrors."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if follow_symlinks:
        path = Path(os.path.realpath(path))
    prefix = f".{path.name[:64]}."
    for _attempt in range(100):
        tmp_path = os.path.join(str(path.parent), prefix + os.urandom(4).hex() + ".tmp")
        try:
            fd = os.open(tmp_path, _TEMPFILE_OPEN_FLAGS, 0o666)
            break
        except FileExistsError:
            continue
        except PermissionError:
            if os.name == "nt" and os.path.isdir(tmp_path):
                continue
            raise
    else:
        raise FileExistsError(f"no free tempfile name beside {path}")
    f = None
    try:
        if hasattr(os, "fchmod"):
            try:
                st = os.stat(path, follow_symlinks=False)
                if stat.S_ISREG(st.st_mode):
                    os.fchmod(fd, stat.S_IMODE(st.st_mode))
            except OSError:
                pass
        f = os.fdopen(fd, "wb")
        with f:
            f.write(data)
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp_path, path)
                break
            except PermissionError:
                # A refusal that cannot clear -- a directory at the target, a
                # read-only file -- raises at once; only a held handle is waited out.
                if (attempt + 1 >= _REPLACE_ATTEMPTS or os.path.isdir(path)
                        or (os.path.exists(path) and not os.access(path, os.W_OK))):
                    raise
                time.sleep(_REPLACE_BACKOFF_S * (attempt + 1))
    except BaseException:  # noqa: BLE001 -- clean up tempfile on any failure, then re-raise
        if f is None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


#: Windows locks one byte this far into the file. ``LockFileEx`` locks are
#: mandatory for I/O on their range, unlike ``flock``, so a lock on byte 0 of a
#: log would make every reader of that log fail; no data reaches this offset.
_LOCK_OFFSET_HIGH = 0x7FFFFFFF
_LOCKFILE_EXCLUSIVE_LOCK = 0x2
_ERROR_NOT_LOCKED = 158


def lock_file(fh: IO[Any], *, shared: bool = False) -> None:
    """Block until this process holds a lock on ``fh``'s file -- exclusive, or
    shared with other shared holders -- the way ``fcntl.flock`` does.

    POSIX is ``flock`` itself. Windows is ``LockFileEx`` on one byte far past
    any data (``_LOCK_OFFSET_HIGH``), which gives the same three properties
    across processes: an exclusive lock waits for every other holder, shared
    locks coexist, and the lock goes when the handle closes or the process
    dies. Before this, every lock site imported ``fcntl`` and ran unlocked on
    Windows, and parallel hooks lost updates there (14 of 200 counter
    increments survived eight writers, driven 2026-10-02).

    Raises ``OSError`` when the lock cannot be taken (a flock-less mount, a
    handle Windows refuses); each caller keeps its own degrade path for that.
    Never sleeps and never writes to a stream. Twin of the copy in
    ``tools/cc/_json_safe.py`` (the hooks and standalone CLIs cannot import
    ``espalier``), held equal by
    ``tests/test_surface_contract.py::test_lock_file_two_copy_parity``;
    ``tests/test_file_lock.py`` drives both across processes.
    """
    if sys.platform == "win32":
        _lock_byte(fh, 0 if shared else _LOCKFILE_EXCLUSIVE_LOCK, unlock=False)
    else:
        try:
            import fcntl
        except ImportError as exc:  # a POSIX build without fcntl: no lock to take
            raise OSError(f"no file locking on this platform: {exc}") from exc
        fcntl.flock(fh.fileno(), fcntl.LOCK_SH if shared else fcntl.LOCK_EX)


def unlock_file(fh: IO[Any]) -> None:
    """Release :func:`lock_file`'s lock. Unlocking a file this process does not
    hold is a no-op, as ``flock(LOCK_UN)`` is."""
    if sys.platform == "win32":
        _lock_byte(fh, 0, unlock=True)
    else:
        try:
            import fcntl
        except ImportError:  # fail-open: ok deliberate -- without fcntl lock_file raised, so no lock is held
            return
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _lock_byte(fh: IO[Any], flags: int, *, unlock: bool) -> None:
    """``LockFileEx`` / ``UnlockFileEx`` on the one lock byte (Windows only).
    A synchronous handle makes ``LockFileEx`` wait until the lock is granted."""
    if sys.platform != "win32":  # pragma: no cover - the callers branch first
        raise OSError("LockFileEx is Windows-only")
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _Overlapped(ctypes.Structure):
        _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                    ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                    ("hEvent", wintypes.HANDLE)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(fh.fileno()))
    overlapped = _Overlapped(0, 0, 0, _LOCK_OFFSET_HIGH, None)
    if unlock:
        ok = kernel32.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped))
    else:
        ok = kernel32.LockFileEx(handle, flags, 0, 1, 0, ctypes.byref(overlapped))
    if not ok:
        error = ctypes.get_last_error()
        if unlock and error == _ERROR_NOT_LOCKED:
            return
        raise ctypes.WinError(error)
