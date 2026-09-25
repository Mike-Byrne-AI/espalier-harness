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
too when that parent is inside the tree (a locked directory inside the tree
refuses the unlink of every child on POSIX, which is the shape this host can
produce); the tree's own parent is not ours and is never touched, so a tree
under a read-only directory reports rather than reaches outside itself. For a
single file the file is what was asked for; its directory is not. On Windows
the attribute lives on the file, so the file's own bit is the fix there.

A second refusal is the caller's decision:

* ``best_effort=False`` (the default) re-raises it, the way a bare delete
  would have: ``cleanup`` must not report an uninstall that left files behind.
* ``best_effort=True`` swallows it, the way ``ignore_errors=True`` did: the
  ``fuse`` rollback runs inside an ``except`` that re-raises the ORIGINAL fault
  and must never mask it with a second one.

Version seam: ``shutil.rmtree`` grew ``onexc`` (receives the exception) in
3.12 and deprecated ``onerror`` (receives ``sys.exc_info()``); the floor is
3.10, so both spellings are wired and the handler reads either shape.

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


def _is_permission_refusal(exc: BaseException) -> bool:
    return isinstance(exc, OSError) and exc.errno in _PERMISSION_ERRNOS


def _add_write_bit(path: str) -> None:
    """``chmod +w`` for the owner, keeping every other bit.

    On Windows ``os.chmod`` knows one bit -- ``S_IWRITE`` clears the read-only
    attribute -- and every other bit is ignored, so the union below is exact
    there too. A path that vanished between the refusal and this call is not
    an error: the retry will report it.
    """
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return
    try:
        os.chmod(path, stat.S_IMODE(mode) | stat.S_IWUSR)
    except OSError:
        pass


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
    """The ``onexc`` callback: clear the bits, retry once, then decide."""

    def _on_failure(func: Callable[..., object], path: str, exc: BaseException) -> None:
        if not _is_permission_refusal(exc):
            if best_effort:
                return
            raise exc
        _add_write_bit(path)
        parent = os.path.dirname(path) or os.curdir
        if _is_inside(root, parent):
            # A locked directory INSIDE the tree refuses every child's
            # unlink on POSIX; the tree's own parent is not ours to touch.
            _add_write_bit(parent)
        try:
            func(path)
        except OSError as retry_exc:
            if best_effort:
                return
            raise retry_exc from exc

    return _on_failure


def _rmtree_with_handler(
    path: Path, handler: Callable[[Callable[..., object], str, BaseException], None],
) -> None:
    if sys.version_info >= (3, 12):
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
    tree) and the delete retried once. A second refusal raises, unless
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
        except OSError:
            # The top-level call itself can raise (``path`` missing, or a
            # refusal the handler chose to swallow that ``rmtree`` then
            # re-reports on the directory): best-effort means best-effort.
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
