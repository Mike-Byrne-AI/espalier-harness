"""``espalier/_rmtree.py`` -- the harness's deletes, and what they do when the
bits refuse (ledger ``DEF-734``). Pins the retry-after-chmod contract and the
rule it follows, because a green POSIX delete over a read-only file proves
nothing about the Windows attribute the class is named for.

The Windows read-only attribute cannot be produced on APFS, so the host-real
arm here uses the POSIX shape of the same refusal: a directory without its
write bit refuses the unlink of every child. The rule under test is "clear
bits only on what you were asked to delete": a locked directory INSIDE a tree
is cleared and the delete finishes; the tree's own parent, and a file's
directory, are not ours and the delete reports instead. The Windows attribute
itself (a refusal the file's own bit answers) is the walk's to witness; its
retry logic is driven on any host through a fake ``func``.
"""
from __future__ import annotations

import errno
import os
import shutil
import stat
from pathlib import Path

import pytest

from espalier import _rmtree
from tests._locked import locked

_RX = stat.S_IRUSR | stat.S_IXUSR  # a directory that lists and traverses but refuses a delete


def _tree(root: Path) -> Path:
    """``root/pack/`` holding one 0444 file and one nested dir with a file."""
    pack = root / "pack"
    (pack / "deep").mkdir(parents=True)
    (pack / "a.pack").write_bytes(b"pack")
    (pack / "deep" / "b.idx").write_bytes(b"idx")
    os.chmod(pack / "a.pack", stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return pack


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


class TestRemoveTreeOnTheHost:
    """The POSIX arm of the class, driven for real."""

    @pytest.mark.skipif(os.name == "nt", reason="the POSIX arm: Windows needs the read-only bit cleared first, the sibling row above")
    def test_a_read_only_file_deletes_on_posix_without_help(self, tmp_path):
        """The premise, stated as a test: on POSIX the file's own bits do not
        govern unlink, so the bare call succeeds here and a green run says
        nothing about Windows (the row's own caveat)."""
        pack = _tree(tmp_path)
        shutil.rmtree(pack)
        assert not os.path.exists(pack)

    def test_a_locked_directory_inside_the_tree_is_cleared_and_the_tree_goes(self, tmp_path):
        """Earn the red: the shape this host CAN produce. A directory without
        its write bit refuses every child's unlink; ``shutil.rmtree`` raises
        and leaves the tree; ``remove_tree`` clears that directory's bit --
        it is inside the tree it was asked to delete -- and finishes."""
        pack = _tree(tmp_path)
        with locked(pack / "deep", _RX):
            with pytest.raises(PermissionError):
                shutil.rmtree(pack)
            assert os.path.exists(pack / "deep" / "b.idx"), "the bare call must leave the tree"
            _rmtree.remove_tree(pack)
            assert not os.path.exists(pack)
            # ``locked`` restores the bits in its ``finally``; the directory is
            # gone, so give it something to restore onto.
            (pack / "deep").mkdir(parents=True)

    def test_best_effort_on_a_locked_directory_inside_the_tree_still_finishes(self, tmp_path):
        pack = _tree(tmp_path)
        with locked(pack / "deep", _RX):
            _rmtree.remove_tree(pack, best_effort=True)
            assert not os.path.exists(pack)
            (pack / "deep").mkdir(parents=True)

    def test_the_trees_own_parent_is_never_touched(self, tmp_path):
        """The other half of the rule. The parent of the tree is not what was
        asked for: with it locked the children go (they are inside), the
        final ``rmdir`` of the tree itself refuses, strict raises, and the
        parent's bits are exactly what the operator set."""
        parent = tmp_path / "hardened"
        parent.mkdir()
        pack = _tree(parent)
        with locked(parent, _RX):
            with pytest.raises(PermissionError):
                _rmtree.remove_tree(pack)
            assert _mode(parent) == _RX, "the tree's parent was chmod'ed"
            assert os.path.isdir(pack), "the tree itself must survive (its parent refused)"
            _rmtree.remove_tree(pack, best_effort=True)  # quiet, and still there
            assert os.path.isdir(pack)
            assert _mode(parent) == _RX

    def test_a_missing_path_raises_strict_and_is_quiet_best_effort(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _rmtree.remove_tree(tmp_path / "absent")
        _rmtree.remove_tree(tmp_path / "absent", best_effort=True)


class TestRemoveFileOnTheHost:
    """The file arm: a hook is a file, and cleanup deletes it through this."""

    @pytest.mark.skipif(os.name == "nt", reason="the POSIX arm: Windows needs the read-only bit cleared first, the sibling row above")
    def test_a_read_only_file_deletes_on_posix_without_help(self, tmp_path):
        f = tmp_path / "hook.py"
        f.write_text("x", encoding="utf-8")
        os.chmod(f, stat.S_IRUSR)
        f.unlink()
        assert not os.path.exists(f)

    def test_a_files_directory_is_not_ours_and_the_delete_reports(self, tmp_path):
        """On POSIX the directory's write bit governs the unlink, and the
        directory is not what was asked for: strict raises without touching
        it, best-effort returns quietly with the file still there."""
        d = tmp_path / "hooks"
        d.mkdir()
        f = d / "write_guard.py"
        f.write_text("x", encoding="utf-8")
        with locked(d, _RX):
            with pytest.raises(PermissionError):
                f.unlink()
            with pytest.raises(PermissionError):
                _rmtree.remove_file(f)
            assert _mode(d) == _RX, "the file's directory was chmod'ed"
            _rmtree.remove_file(f, best_effort=True)
            assert os.path.exists(f)

    def test_a_missing_file_raises_strict_and_is_quiet_best_effort(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _rmtree.remove_file(tmp_path / "absent")
        _rmtree.remove_file(tmp_path / "absent", best_effort=True)

    def test_the_retry_after_the_files_own_bit_is_cleared(self, tmp_path, monkeypatch):
        """The Windows shape, on any host: the first unlink refuses, the
        file's own write bit is added, the second unlink succeeds."""
        f = tmp_path / "hook.py"
        f.write_text("x", encoding="utf-8")
        os.chmod(f, stat.S_IRUSR)
        real_unlink = os.unlink
        calls: list[str] = []

        def refusing_once(path, *a, **k):
            calls.append(str(path))
            if len(calls) == 1:
                raise PermissionError(errno.EACCES, "read-only attribute", str(path))
            return real_unlink(path, *a, **k)

        monkeypatch.setattr(os, "unlink", refusing_once)
        _rmtree.remove_file(f)
        assert len(calls) == 2, calls
        assert not os.path.exists(f)

    def test_a_second_refusal_raises_strict_and_is_swallowed_best_effort(self, tmp_path, monkeypatch):
        f = tmp_path / "hook.py"
        f.write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            os, "unlink",
            lambda path, *a, **k: (_ for _ in ()).throw(PermissionError(errno.EACCES, "still", str(path))),
        )
        with pytest.raises(PermissionError) as info:
            _rmtree.remove_file(f)
        assert isinstance(info.value.__cause__, PermissionError), "the first refusal is chained"
        _rmtree.remove_file(f, best_effort=True)

    def test_a_non_permission_error_is_not_retried(self, tmp_path, monkeypatch):
        calls: list[str] = []

        def busy(path, *a, **k):
            calls.append(str(path))
            raise OSError(errno.EBUSY, "busy", str(path))

        monkeypatch.setattr(os, "unlink", busy)
        with pytest.raises(OSError) as info:
            _rmtree.remove_file(tmp_path / "f")
        assert info.value.errno == errno.EBUSY
        _rmtree.remove_file(tmp_path / "f", best_effort=True)
        assert len(calls) == 2, "one attempt per call, never a retry"


class TestTheHandler:
    """The tree handler's retry logic on any host, through the ``onexc`` shape."""

    @staticmethod
    def _retry_func(calls: list, *, then: Exception | None = None):
        """The ``func`` ``rmtree`` hands the handler. ``rmtree`` itself made
        the first attempt and it refused; the handler's call is the RETRY, so
        the fake succeeds unless told what the retry should raise."""

        def func(path):
            calls.append(path)
            if then is not None:
                raise then

        return func

    def test_a_permission_refusal_clears_the_bits_inside_the_tree_and_retries_once(
        self, tmp_path, monkeypatch
    ):
        root = tmp_path / "tree"
        (root / "sub").mkdir(parents=True)
        target = root / "sub" / "f"
        target.write_text("x", encoding="utf-8")
        chmods: list[tuple[str, int]] = []
        real_chmod = os.chmod
        monkeypatch.setattr(os, "chmod", lambda p, m: (chmods.append((str(p), m)), real_chmod(p, m)))
        calls: list = []
        handler = _rmtree._make_handler(False, str(root))

        handler(self._retry_func(calls), str(target), PermissionError(errno.EACCES, "refused", str(target)))

        assert calls == [str(target)], "retried exactly once"
        touched = {p for p, _ in chmods}
        assert str(target) in touched, "the path itself gets the write bit"
        assert str(root / "sub") in touched, "and its parent, which is inside the tree"
        assert str(root) not in touched and str(tmp_path) not in touched
        assert all(m & stat.S_IWUSR for _, m in chmods), chmods

    def test_the_roots_own_parent_is_not_cleared(self, tmp_path, monkeypatch):
        root = tmp_path / "tree"
        root.mkdir()
        chmods: list[str] = []
        real_chmod = os.chmod
        monkeypatch.setattr(os, "chmod", lambda p, m: (chmods.append(str(p)), real_chmod(p, m)))
        handler = _rmtree._make_handler(True, str(root))
        handler(self._retry_func([]), str(root), PermissionError(errno.EACCES, "refused", str(root)))
        assert chmods == [str(root)], chmods

    def test_a_second_refusal_raises_strict(self, tmp_path):
        target = tmp_path / "f"
        target.write_text("x", encoding="utf-8")
        calls: list = []
        again = PermissionError(errno.EACCES, "still refused", str(target))
        handler = _rmtree._make_handler(False, str(tmp_path))
        with pytest.raises(PermissionError) as info:
            handler(self._retry_func(calls, then=again), str(target), PermissionError(errno.EACCES, "refused"))
        assert info.value is again
        assert isinstance(info.value.__cause__, PermissionError), "the first refusal is chained, not lost"

    def test_a_second_refusal_is_swallowed_best_effort(self, tmp_path):
        target = tmp_path / "f"
        target.write_text("x", encoding="utf-8")
        calls: list = []
        again = PermissionError(errno.EACCES, "still refused", str(target))
        handler = _rmtree._make_handler(True, str(tmp_path))
        handler(self._retry_func(calls, then=again), str(target), PermissionError(errno.EACCES, "refused"))
        assert len(calls) == 1

    @pytest.mark.parametrize("exc", [
        FileNotFoundError(errno.ENOENT, "gone"),
        OSError(errno.EBUSY, "busy"),
        NotADirectoryError(errno.ENOTDIR, "not a dir"),
    ])
    def test_a_non_permission_error_is_not_retried(self, tmp_path, exc):
        """A chmod changes nothing about ENOENT or EBUSY: strict re-raises the
        exception it was handed, untouched; best-effort swallows it."""
        calls: list = []

        def func(path):
            calls.append(path)

        with pytest.raises(type(exc)) as info:
            _rmtree._make_handler(False, str(tmp_path))(func, str(tmp_path / "f"), exc)
        assert info.value is exc
        _rmtree._make_handler(True, str(tmp_path))(func, str(tmp_path / "f"), exc)
        assert calls == [], "never retried"

    def test_the_write_bit_is_added_and_the_other_bits_kept(self, tmp_path):
        target = tmp_path / "f"
        target.write_text("x", encoding="utf-8")
        os.chmod(target, stat.S_IRUSR | stat.S_IRGRP)
        _rmtree._add_write_bit(str(target))
        mode = _mode(target)
        assert mode & stat.S_IWUSR
        assert mode & stat.S_IRGRP, "the group read bit survives"

    def test_a_vanished_path_does_not_break_the_bit_edit(self, tmp_path):
        _rmtree._add_write_bit(str(tmp_path / "absent"))  # no raise

    @pytest.mark.parametrize("root,path,inside", [
        ("/a/tree", "/a/tree/sub", True),
        ("/a/tree", "/a/tree/sub/deeper", True),
        ("/a/tree", "/a/tree", False),
        ("/a/tree", "/a", False),
        ("/a/tree", "/a/treehouse", False),
        ("/a/tree/", "/a/tree/x", True),
    ])
    def test_inside_is_strict_and_segment_bounded(self, root, path, inside):
        assert _rmtree._is_inside(root, path) is inside


class TestBothSpellingsOfTheStdlibSeam:
    """3.12 grew ``onexc``; the floor is 3.10, where only ``onerror`` exists.
    Whichever this interpreter has, the handler must be reached with the
    ``(func, path, exception)`` shape."""

    def test_the_handler_receives_an_exception_not_a_tuple(self, tmp_path, monkeypatch):
        seen: list = []

        def handler(func, path, exc):
            seen.append(exc)

        def fake_rmtree(path, onexc=None, onerror=None):
            err = PermissionError(errno.EACCES, "refused", str(path))
            if onexc is not None:
                onexc(os.unlink, str(path), err)
            else:
                try:
                    raise err
                except PermissionError:
                    import sys as _sys
                    onerror(os.unlink, str(path), _sys.exc_info())

        monkeypatch.setattr(shutil, "rmtree", fake_rmtree)
        _rmtree._rmtree_with_handler(tmp_path, handler)
        assert len(seen) == 1 and isinstance(seen[0], PermissionError)
