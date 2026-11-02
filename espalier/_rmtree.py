"""The harness's deletes, and what they do when the bits refuse.

``shutil.rmtree`` and ``Path.unlink`` both delete a file with ``os.unlink``,
and on Windows that call raises ``PermissionError`` for a file carrying the
read-only attribute -- the bit git sets on every packfile it writes, the bit
``shutil.copytree``'s default ``copy2`` preserves when ``fuse`` copies a host's
``.git``, and the bit an adopter sets with ``attrib +R`` on a hook. On POSIX the
same ``unlink`` is governed by the parent directory's write bit, so a ``0444``
file deletes without complaint there and a green macOS delete is no evidence
about the Windows one (ledger ``DEF-734``, recovered from walk 1's residue by
the walk-2 audit).

Two helpers, every site. ``remove_tree`` and ``remove_file`` are the ONLY
deletes in the two teardown modules (``cleanup``, the ``fuse`` rollback) and
``remove_tree`` the only tree removal anywhere in ``espalier/``:
``tests/test_contracts.py::TestTreeRemovalClearsReadOnly`` pins both by AST,
so the next site cannot regrow the class one call at a time.

The rule the handler follows: **clear bits only on what you were asked to
delete.** A refusal is answered by adding the owner write bit to the path that
refused and retrying once. For a tree, the refusing path's PARENT is cleared
too when that parent is inside the tree or is the tree itself (a locked
directory inside the tree refuses the unlink of every child on POSIX, which is
the shape this host can produce, and the tree's own root is part of the ask:
ledger ``DEF-3023``); the tree's own parent is not ours and is never touched,
so a tree under a read-only directory reports rather than reaches outside
itself. For a
single file the file is what was asked for; its directory is not. On Windows
the attribute lives on the file, so the file's own bit is the fix there. A
link is what was asked for and what it names is not: its bits are read and
set on the link itself, never through it (``_add_owner_bits``).

A directory the walk cannot enter is the one refusal a retry cannot answer.
``rmtree`` opens a directory before it deletes inside it (``os.open`` on its
fd walk, ``os.scandir`` on the walk Windows uses); a directory without its
read bit refuses that call, and the write bit does not give the read bit back.
Nor is ``func(path)`` the call that refused: ``os.open`` needs its flags, and
retried bare it raised ``TypeError`` past every ``except OSError`` (ledger
``DEF-5054``). And by the time the handler runs, ``rmtree`` has skipped the
subtree. So that refusal is answered by giving the directory back its owner
read, write and search bits (it is inside the tree, or is the tree) and
walking it again, once. A second refusal of the same directory is reported
under the rule below, and the walk's own later call on a directory already
removed this way, or on an entry it had queued inside one (3.10 to 3.12 make
both), is not a fault.

A second refusal is the caller's decision:

* ``best_effort=False`` (the default) re-raises it, the way a bare delete
  would have: ``cleanup`` must not report an uninstall that left files behind.
* ``best_effort=True`` swallows it, the way ``ignore_errors=True`` did: the
  ``fuse`` rollback runs inside an ``except`` that re-raises the ORIGINAL fault
  and must never mask it with a second one.

Version seam: ``shutil.rmtree`` grew ``onexc`` (receives the exception) in
3.12 and deprecated ``onerror`` (receives ``sys.exc_info()``); the floor is
3.10, so both spellings are wired and the handler reads either shape
(``_HAS_ONEXC`` picks one, read at each call so a test can drive the 3.10
spelling on a newer interpreter, whose ``rmtree`` still takes ``onerror``).

Stdlib-only, no espalier imports: importable from every engine module,
including the ones ``espalier/scanners/`` may not pull third-party code into.
"""
from __future__ import annotations

import errno
import os
import shutil
import stat
import sys
from collections.abc import Callable
from pathlib import Path

__all__ = ["remove_file", "remove_tree"]

#: The errnos that mean "the bits refused", the only condition worth a chmod
#: and a retry. A missing file (ENOENT), a busy one (EBUSY), a name that is not
#: a directory: none of those is a permission problem and a chmod would not
#: change the answer.
_PERMISSION_ERRNOS = frozenset({errno.EACCES, errno.EPERM})

#: ``rmtree`` uses the ``onexc`` spelling where the interpreter has it (3.12+).
_HAS_ONEXC = sys.version_info >= (3, 12)

#: ``os.chmod`` takes ``follow_symlinks=False``: macOS (``lchmod``) and
#: Windows from 3.13. Not Linux, which has no ``lchmod``. Computed at import
#: and looked up at each call, so a test drives every arm by setting it.
_CHMOD_NO_FOLLOW = os.chmod in os.supports_follow_symlinks

#: Windows, where a bare ``os.chmod`` sets the attribute of a link itself on
#: every version: to 3.12 it is the only body (``SetFileAttributesW`` on the
#: path), and from 3.13 ``follow_symlinks`` defaults to false there
#: (``CHMOD_DEFAULT_FOLLOW_SYMLINKS`` in CPython's ``Modules/posixmodule.c``,
#: read for 3.12 and 3.13). So DEF-5060 was a POSIX defect alone.
_BARE_CHMOD_IS_THE_LINKS = os.name == "nt"


def _is_permission_refusal(exc: BaseException) -> bool:
    return isinstance(exc, OSError) and exc.errno in _PERMISSION_ERRNOS


def _enters_a_directory(func: Callable[..., object]) -> bool:
    """Is ``func`` the call ``rmtree`` makes to enter a directory? Every other
    call the stdlib's walks hand the handler (3.10 to 3.14, read) retries as
    ``func(path)``: ``unlink``, ``rmdir`` and ``lstat`` are the call itself,
    and ``close`` and ``islink`` never carry a permission errno."""
    return func is os.open or func is os.scandir


def _add_owner_bits(path: str, bits: int) -> None:
    """Add ``bits`` for the owner on ``path`` itself, keeping every other bit.

    Never through a link: a link is what was asked to be deleted and its
    target is not, and may lie outside the tree (ledger ``DEF-5060``: a
    refused unlink of a link in a locked directory gave the file it named,
    outside the tree, the write bit). So the mode is read by ``lstat`` and
    set without following where ``os.chmod`` can do that; where it cannot
    (Linux), a link is left as it is, which loses nothing, since on POSIX a
    link's own mode never refuses an unlink (its directory's write bit does).
    On Windows the link's own read-only attribute is what refuses, and both
    arms there reach it. Off Linux the set does not follow a path swapped
    for a link after the read either; on Linux a path that is not a link is
    set by the bare call, which would.

    On Windows ``os.chmod`` knows one bit -- ``S_IWRITE`` clears the read-only
    attribute -- and every other bit is ignored, so the union below is exact
    there too. A path that vanished between the refusal and this call is not
    an error: the retry will report it.
    """
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return
    wanted = stat.S_IMODE(mode) | bits
    try:
        if _CHMOD_NO_FOLLOW:
            os.chmod(path, wanted, follow_symlinks=False)
        elif _BARE_CHMOD_IS_THE_LINKS or not stat.S_ISLNK(mode):
            os.chmod(path, wanted)
    except OSError:
        pass


def _add_write_bit(path: str) -> None:
    """``chmod u+w``: the answer to every refusal but a directory's entry."""
    _add_owner_bits(path, stat.S_IWUSR)


def _is_directory(path: str) -> bool:
    """A directory, not a link to one, by ``lstat`` (never a pathlib question,
    whose answer under a refusing parent differs by interpreter)."""
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def _key(path: str) -> str:
    """The one spelling a re-walked directory is remembered by."""
    return os.path.normpath(path).replace("\\", "/")


def _is_inside(root: str, path: str) -> bool:
    """Is ``path`` strictly below ``root`` (never ``root`` itself)?

    Both sides are folded to forward slashes after ``normpath`` (the repo's
    one path-comparison idiom), so a backslash spelling on Windows and the
    POSIX one compare the same way.
    """
    root_n = os.path.normpath(root).replace("\\", "/").rstrip("/")
    path_n = os.path.normpath(path).replace("\\", "/")
    return path_n != root_n and path_n.startswith(root_n + "/")


def _make_handler(
    best_effort: bool, root: str,
) -> Callable[[Callable[..., object], str, BaseException], None]:
    """The ``onexc`` callback: clear the bits, retry once, then decide. A
    directory the walk could not enter is walked again instead, once."""
    rewalked: set[str] = set()

    def _under_a_rewalk(path: str) -> bool:
        key = _key(path)
        return any(key == done or key.startswith(done + "/") for done in rewalked)

    def _on_failure(func: Callable[..., object], path: str, exc: BaseException) -> None:
        if isinstance(exc, FileNotFoundError) and _under_a_rewalk(path):
            # The walk's own later call on a directory this handler already
            # removed, or on an entry it had queued inside one (3.12's fd walk).
            return
        if not _is_permission_refusal(exc):
            if best_effort:
                return
            raise exc
        if _enters_a_directory(func):
            _walk_again(path, exc)
            return
        _add_write_bit(path)
        parent = os.path.dirname(path) or os.curdir
        if _key(parent) == _key(root) or _is_inside(root, parent):
            # A locked directory inside the tree, or the tree itself, refuses
            # every child's unlink on POSIX; the tree's own parent is not ours
            # to touch.
            _add_write_bit(parent)
        try:
            func(path)
        except OSError as retry_exc:
            if best_effort:
                return
            raise retry_exc from exc

    def _walk_again(path: str, exc: BaseException) -> None:
        # ``rmtree`` handed us everything under ``root``, so the directory is
        # inside what was asked for (or is it); its parent's bit, when the
        # final rmdir needs it, is the ordinary refusal and rule above.
        if _key(path) in rewalked or not _is_directory(path):
            if best_effort:
                return
            raise exc
        rewalked.add(_key(path))
        _add_owner_bits(path, stat.S_IRWXU)
        try:
            _rmtree_with_handler(Path(path), _on_failure)
        except OSError as retry_exc:
            if best_effort:
                return
            if retry_exc.__cause__ is not None:
                raise  # a deeper refusal, already chained to its own first one
            raise retry_exc from exc

    return _on_failure


def _rmtree_with_handler(
    path: Path, handler: Callable[[Callable[..., object], str, BaseException], None],
) -> None:
    if _HAS_ONEXC:
        shutil.rmtree(path, onexc=handler)
        return

    # 3.10 / 3.11: ``onerror`` hands ``(func, path, exc_info)``; unwrap to the
    # ``onexc`` shape so one handler serves both.
    def _legacy(func: Callable[..., object], p: str, exc_info: tuple) -> None:
        handler(func, p, exc_info[1])

    shutil.rmtree(path, onerror=_legacy)


def remove_tree(path: Path | str, *, best_effort: bool = False) -> None:
    """Delete the directory tree at ``path``.

    A file or directory inside the tree whose bits refuse the delete is
    chmod'ed writable (itself, and its parent when the parent is inside the
    tree or is the tree) and the delete retried once; a directory the walk cannot enter
    gets its owner bits back and is walked again, once. A second refusal raises, unless
    ``best_effort`` is set, in which case the tree is left as far as it got
    -- the ``ignore_errors=True`` contract for callers that must not raise a
    second exception over the one they are already handling.

    A ``path`` that does not exist is a no-op under ``best_effort`` and raises
    ``FileNotFoundError`` otherwise, exactly as ``shutil.rmtree`` does.
    """
    target = Path(path)
    handler = _make_handler(best_effort, str(target))
    if best_effort:
        try:
            _rmtree_with_handler(target, handler)
        except (OSError, RecursionError):
            # The top-level call itself can raise (``path`` missing, or a
            # refusal the handler chose to swallow that ``rmtree`` then
            # re-reports on the directory), and a chain of directories each
            # walked again nests one walk per level: best-effort means
            # best-effort.
            return
        return
    _rmtree_with_handler(target, handler)


def remove_file(path: Path | str, *, best_effort: bool = False) -> None:
    """Delete the file (or symlink) at ``path``.

    The sibling of :func:`remove_tree` for the file arm of a teardown: a
    refusal is answered by clearing the file's own write bit -- the Windows
    read-only attribute -- and one retry. The file's directory is not what
    was asked for and is never touched, so on POSIX a file under a read-only
    directory reports (strict) or stays (``best_effort``), the same rule a
    tree's own parent gets.
    """
    target = str(path)
    try:
        os.unlink(target)
    except OSError as exc:
        if not _is_permission_refusal(exc):
            if best_effort:
                return
            raise
        _add_write_bit(target)
        try:
            os.unlink(target)
        except OSError as retry_exc:
            if best_effort:
                return
            raise retry_exc from exc
