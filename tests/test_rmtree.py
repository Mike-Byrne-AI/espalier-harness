"""``espalier/_rmtree.py`` -- the harness's deletes, and what they do when the
bits refuse (ledger ``DEF-734``). Pins the retry-after-chmod contract and the
rule it follows, because a green POSIX delete over a read-only file proves
nothing about the Windows attribute the class is named for.

The Windows read-only attribute cannot be produced on APFS, so the host-real
arm on POSIX uses the POSIX shape of the same refusal: a directory without its
write bit refuses the unlink of every child. The rule under test is "clear
bits only on what you were asked to delete": a locked directory INSIDE a tree
is cleared and the delete finishes; the tree's own parent, and a file's
directory, are not ours and the delete reports instead. The Windows attribute
itself (a refusal the file's own bit answers) was witnessed on 2026-09-26 on 3.12
to 3.14, and ``TestTheWindowsAttribute`` drives it for real on Windows, where
``portability.yml``'s windows-latest cell runs it (``DEF-934``); its retry logic
is driven on any host through a fake ``func``.
"""
from __future__ import annotations

import errno
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

from espalier import _rmtree
from tests._locked import locked

_RX = stat.S_IRUSR | stat.S_IXUSR  # a directory that lists and traverses but refuses a delete
_SHUT = 0  # a directory the walk cannot even enter: no read, no search, no write


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

    def test_a_locked_root_holding_a_directory_is_cleared_and_the_tree_goes(self, tmp_path, walk):
        """The tree's own root is part of the ask (DEF-3023): ``pack`` without
        its write bit, holding only ``deep/``, refuses ``deep``'s ``rmdir``, so
        ``remove_tree`` gives the root the bit and finishes, on both walks. A
        root holding files is no oracle from 3.12.4, whose fd walk hands the
        refused unlink back as a failure to enter the root."""
        pack = tmp_path / "pack"
        (pack / "deep").mkdir(parents=True)
        (pack / "deep" / "b.idx").write_bytes(b"idx")
        with locked(pack, _RX):
            _rmtree.remove_tree(pack)
            assert not os.path.exists(pack)
            pack.mkdir()  # for ``locked`` to restore onto

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


class TestTheWindowsAttribute:
    """The Windows arm of the class, driven for real: the read-only attribute
    on the file itself, the refusal the module is named for (DEF-934)."""

    @pytest.mark.skipif(os.name != "nt", reason="the Windows arm: the read-only attribute refuses an unlink only there")
    def test_a_bare_rmtree_refuses_and_the_helper_takes_the_tree_through_its_handler(
        self, tmp_path, monkeypatch,
    ):
        """``_tree``'s ``os.chmod`` sets the real read-only attribute on
        Windows, so the premise is asserted first: a bare ``shutil.rmtree``
        raises ``PermissionError`` and leaves the read-only file. Then, on a
        second tree, ``remove_tree`` deletes it, through the callback
        spelling this interpreter takes (``onexc`` from 3.12, ``onerror``
        before), and its handler fired on that file, so a green run here
        proves the handler arm rather than a delete that never refused. Runs
        only on Windows: ``portability.yml``'s windows-latest cell takes the
        ``onexc`` arm (3.12) on a pull request that changes Python; a run
        dispatched there with a newer ``python`` input takes it on 3.13 or
        3.14."""
        bare = _tree(tmp_path / "bare")
        pack = _tree(tmp_path / "helper")
        assert _rmtree._HAS_ONEXC == (sys.version_info >= (3, 12))
        spelling = "onexc" if _rmtree._HAS_ONEXC else "onerror"
        real_rmtree = shutil.rmtree
        spellings: list[str] = []

        def _rmtree_spy(path, **kwargs):
            spellings.extend(k for k in ("onexc", "onerror") if k in kwargs)
            return real_rmtree(path, **kwargs)

        real_make_handler = _rmtree._make_handler
        fired: list[tuple[str, BaseException]] = []

        def _make_handler_spy(best_effort, root):
            handler = real_make_handler(best_effort, root)

            def _recorded(func, path, exc):
                fired.append((path, exc))
                return handler(func, path, exc)

            return _recorded

        try:
            with pytest.raises(PermissionError):
                shutil.rmtree(bare)
            assert os.path.exists(bare / "a.pack"), "the bare call must leave the read-only file"
            monkeypatch.setattr(shutil, "rmtree", _rmtree_spy)
            monkeypatch.setattr(_rmtree, "_make_handler", _make_handler_spy)
            _rmtree.remove_tree(pack)
            assert not os.path.exists(pack)
            assert spellings and set(spellings) == {spelling}, f"rmtree was handed {spellings}, not {spelling}"
            refused = [(Path(p).name, type(e)) for p, e in fired]
            assert refused == [("a.pack", PermissionError)], f"the handler fired on {refused}"
        finally:
            for leftover in (bare / "a.pack", pack / "a.pack"):
                if os.path.exists(leftover):
                    os.chmod(leftover, stat.S_IWRITE | stat.S_IREAD)


def _shut_tree(root: Path) -> Path:
    """``root/pack/`` holding a file and ``shut/``, which holds a file and a
    nested dir with a file: the walk has to go deep after it gets back in."""
    pack = root / "pack"
    (pack / "shut" / "inner").mkdir(parents=True)
    (pack / "a.pack").write_bytes(b"pack")
    (pack / "shut" / "b.idx").write_bytes(b"idx")
    (pack / "shut" / "inner" / "c.rev").write_bytes(b"rev")
    return pack


@pytest.fixture(params=["onexc", "onerror"])
def spelling(request, monkeypatch):
    """``rmtree``'s callback spelling. The interpreter's own is left alone, so
    a row reds on an unfixed deleter by what the deleter does; the other is
    forced through the seam (3.12+ still takes the deprecated ``onerror``)."""
    native = "onexc" if sys.version_info >= (3, 12) else "onerror"
    if request.param == "onexc" and native == "onerror":
        pytest.skip("rmtree grew onexc in 3.12")
    if request.param != native:
        monkeypatch.setattr(_rmtree, "_HAS_ONEXC", request.param == "onexc")
    return request.param


def force_walk(name: str, monkeypatch) -> str:
    """Put ``rmtree`` on the walk ``name`` names, or skip where this host has
    none: the fixture below, and ``tests/test_wheel_smoke.py``'s twin parity
    row, which drives both deleters over both walks."""
    if name == "fd":
        if not getattr(shutil, "_use_fd_functions", False):
            pytest.skip("this host's rmtree has no fd walk")
    elif hasattr(shutil, "_rmtree_impl"):
        monkeypatch.setattr(shutil, "_rmtree_impl", shutil._rmtree_unsafe)
    else:
        monkeypatch.setattr(shutil, "_use_fd_functions", False)
    return name


@pytest.fixture(params=["fd", "scandir"])
def walk(request, monkeypatch):
    """``rmtree``'s walk: the fd walk opens a directory (``os.open``) before
    it deletes inside it; the walk Windows uses lists it (``os.scandir``),
    forced here through the stdlib's own switch so a host that can shut a
    directory drives it (3.14 picks the walk at import, 3.10 to 3.13 at
    each call)."""
    return force_walk(request.param, monkeypatch)


class TestADirectoryTheWalkCannotEnter:
    """DEF-5054: a directory with no read bit refuses the call that enters
    it, and the handler once retried that call bare -- ``os.open(path)``,
    which needs its flags, so the delete escaped every ``except OSError``
    (best effort included) as a ``TypeError``. The directory is inside what
    was asked for: its owner bits come back and it is walked again, once."""

    @pytest.mark.parametrize("best_effort", [False, True], ids=["strict", "best_effort"])
    def test_a_shut_directory_inside_the_tree_is_cleared_and_the_tree_goes(
        self, tmp_path, walk, spelling, best_effort
    ):
        pack = _shut_tree(tmp_path)
        parent_mode = _mode(tmp_path)
        with locked(pack / "shut", _SHUT):
            _rmtree.remove_tree(pack, best_effort=best_effort)
            assert not os.path.exists(pack), "the shut directory kept the tree"
            # ``locked`` restores the bits in its ``finally``: give it a target.
            (pack / "shut").mkdir(parents=True)
        assert _mode(tmp_path) == parent_mode, "the tree's own parent was chmod'ed"

    def test_a_directory_whose_bits_cannot_come_back_is_reported(
        self, tmp_path, monkeypatch, walk, spelling
    ):
        """Someone else's directory: the chmod refuses, so the second walk
        meets the same refusal. Strict raises it, chained to the first, and
        walks no third time; best effort is quiet and leaves the tree."""
        pack = _shut_tree(tmp_path)
        tried: list[str] = []

        def not_the_owner(path, mode, *a, **k):
            tried.append(os.fspath(path))
            raise PermissionError(errno.EPERM, "not the owner", str(path))

        with locked(pack / "shut", _SHUT):
            with monkeypatch.context() as m:
                m.setattr(os, "chmod", not_the_owner)
                with pytest.raises(PermissionError) as info:
                    _rmtree.remove_tree(pack)
                assert tried.count(str(pack / "shut")) == 1, f"walked again more than once: {tried}"
                _rmtree.remove_tree(pack, best_effort=True)
            assert isinstance(info.value.__cause__, PermissionError), "the first refusal is chained"
            assert os.path.isdir(pack / "shut"), "a directory it could not open was deleted"

    def test_a_directory_that_lists_but_cannot_be_searched_is_cleared_or_reported(
        self, tmp_path, walk, spelling
    ):
        """No search bit: the walk opens and lists it, then every entry
        refuses. Some walks hand that refusal back as the directory's own
        entry call and it is walked again; strict then ends cleared or with a
        ``PermissionError``, never the ``FileNotFoundError`` of an entry the
        walk had queued inside it (3.12's fd walk did, before the skip
        covered a re-walked directory's insides)."""
        pack = _shut_tree(tmp_path)
        with locked(pack / "shut", stat.S_IRUSR | stat.S_IWUSR):
            try:
                _rmtree.remove_tree(pack)
            except PermissionError:
                assert os.path.isdir(pack / "shut"), "reported, so the directory is still there"
            else:
                assert not os.path.exists(pack), "no error, so the tree must be gone"
                (pack / "shut").mkdir(parents=True)

    def test_a_deeper_refusal_keeps_its_own_cause(self, tmp_path, monkeypatch, walk, spelling):
        """A shut directory inside a shut directory, the inner one's bits not
        ours to change: the raise names the inner directory and is chained
        to the inner directory's first refusal, not the outer one's."""
        inner = tmp_path / "pack" / "outer" / "inner"
        inner.mkdir(parents=True)
        (inner / "f").write_bytes(b"x")
        real_chmod = os.chmod

        def not_the_inner_owner(path, mode, *a, **k):
            if os.path.normpath(os.fspath(path)) == os.path.normpath(str(inner)):
                raise PermissionError(errno.EPERM, "not the owner", os.fspath(path))
            return real_chmod(path, mode, *a, **k)

        with locked(inner, _SHUT), locked(inner.parent, _SHUT):
            with monkeypatch.context() as m:
                m.setattr(os, "chmod", not_the_inner_owner)
                with pytest.raises(PermissionError) as info:
                    _rmtree.remove_tree(tmp_path / "pack")
        # 3.10 and 3.11's fd walk stamp the entry's own name, relative to its dir_fd.
        assert os.path.basename(os.fspath(info.value.filename)) == "inner"
        cause = info.value.__cause__
        assert isinstance(cause, PermissionError), cause
        assert os.path.basename(os.fspath(cause.filename)) == "inner", "chained to the outer directory's refusal"

    def test_best_effort_swallows_a_walk_nested_too_deep_and_strict_raises_it(self, tmp_path, monkeypatch):
        """A chain of shut directories nests one walk per level; past the
        interpreter's depth that is a ``RecursionError``, which best effort
        must not let escape over a fault it is already handling."""

        def too_deep(path, **kwargs):
            raise RecursionError("maximum recursion depth exceeded")

        monkeypatch.setattr(shutil, "rmtree", too_deep)
        with pytest.raises(RecursionError):
            _rmtree.remove_tree(tmp_path / "pack")
        _rmtree.remove_tree(tmp_path / "pack", best_effort=True)


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


def _link_to(link: Path, target: Path) -> Path:
    """``link`` pointing at ``target``, or a skip where this host cannot make
    one (Windows without the symlink privilege)."""
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"this host cannot make a symlink: {exc}")
    return link


def _outside_file(root: Path) -> Path:
    """A 0o400 file that no delete in the test is asked for."""
    outside = root / "outside"
    outside.write_text("x", encoding="utf-8")
    os.chmod(outside, stat.S_IRUSR)
    return outside


class TestALinkIsDeletedNeverFollowed:
    """DEF-5060: the bit edit read the mode by ``os.stat`` and set it by
    ``os.chmod``, both of which follow a link, so a refused unlink of a link
    gave the link's TARGET the owner write bit, outside the tree included.
    The link is what was asked for; its target is not."""

    @pytest.mark.skipif(os.name == "nt", reason="the POSIX arm: a locked directory refuses the unlink; Windows is the read-only link below")
    @pytest.mark.parametrize("best_effort", [False, True], ids=["strict", "best_effort"])
    def test_a_refused_link_in_the_tree_never_lends_its_target_the_write_bit(self, tmp_path, best_effort):
        """The row's own drive: a 0o500 directory inside the tree holding a
        link to a 0o400 file outside it. The directory is cleared (it is
        inside the tree) and the tree goes; the file outside stays 0o400."""
        outside = _outside_file(tmp_path)
        locked_dir = tmp_path / "tree" / "d"
        locked_dir.mkdir(parents=True)
        _link_to(locked_dir / "link", outside)
        with locked(locked_dir, _RX):
            _rmtree.remove_tree(tmp_path / "tree", best_effort=best_effort)
            assert not os.path.lexists(tmp_path / "tree")
            locked_dir.mkdir(parents=True)  # for ``locked`` to restore onto
        assert _mode(outside) == stat.S_IRUSR, "the link's target outside the tree was chmod'ed"

    @pytest.mark.skipif(os.name == "nt", reason="the POSIX arm: a locked directory refuses the unlink; Windows is the read-only link below")
    def test_a_refused_link_file_never_lends_its_target_the_write_bit(self, tmp_path):
        """The file arm: the link's directory is not ours, so the delete
        reports (strict) or stays (best effort), and the file it names is
        left exactly as it was."""
        outside = _outside_file(tmp_path)
        d = tmp_path / "hooks"
        d.mkdir()
        link = _link_to(d / "write_guard.py", outside)
        with locked(d, _RX):
            with pytest.raises(PermissionError):
                _rmtree.remove_file(link)
            assert _mode(outside) == stat.S_IRUSR, "the link's target was chmod'ed"
            _rmtree.remove_file(link, best_effort=True)
            assert os.path.lexists(link)
            assert _mode(d) == _RX, "the link's directory was chmod'ed"
        assert _mode(outside) == stat.S_IRUSR

    @pytest.mark.skipif(os.name != "nt", reason="the Windows arm: the read-only attribute of the link itself")
    def test_a_read_only_link_goes_and_its_read_only_target_stays(self, tmp_path, monkeypatch):
        """A behaviour pin, not a regression pin: a bare ``os.chmod`` on
        Windows never followed a link (to 3.12 its only body sets the path's
        own attribute; from 3.13 ``follow_symlinks`` defaults to false
        there), so DEF-5060 never reached Windows. The premise is asserted
        first: the link's own read-only attribute refuses a bare unlink. Then
        the helper clears that attribute on the link itself, the link goes,
        and the read-only file it names stays read-only. Runs only on
        Windows: ``portability.yml``'s windows-latest cell takes the bare arm
        (3.12), and a run dispatched there with a newer ``python`` input takes
        the ``follow_symlinks=False`` arm (DEF-5064); each arm is also driven
        on every host through the fake below."""
        target = tmp_path / "target"
        target.write_text("x", encoding="utf-8")
        link = _link_to(tmp_path / "link", target)
        os.chmod(target, stat.S_IREAD)
        os.chmod(link, stat.S_IREAD)  # the link's own attribute: a bare chmod never follows on Windows
        # The arm this interpreter takes, stated so a run names it: the
        # keyword from 3.13 (DEF-5064's dispatched runs read this), bare before.
        assert _rmtree._CHMOD_NO_FOLLOW == (sys.version_info >= (3, 13))
        arm = {"follow_symlinks": False} if _rmtree._CHMOD_NO_FOLLOW else {}
        real_chmod = os.chmod
        chmods: list[tuple[str, dict]] = []
        monkeypatch.setattr(os, "chmod", lambda p, m, **k: (chmods.append((str(p), k)), real_chmod(p, m, **k)))
        try:
            with pytest.raises(PermissionError):
                os.unlink(link)
            _rmtree.remove_file(link)
            assert not os.path.lexists(link)
            assert chmods == [(str(link), arm)], "the helper set something other than the link's own bit, or by another arm"
            assert not os.stat(target).st_mode & stat.S_IWRITE, "the link's target lost its read-only attribute"
        finally:
            real_chmod(target, stat.S_IWRITE | stat.S_IREAD)

    @pytest.mark.parametrize("no_follow,bare_is_the_links,expected", [
        (True, False, [{"follow_symlinks": False}]),
        (False, True, [{}]),
        (False, False, []),
    ], ids=["follow_symlinks_false", "windows_to_3_12_bare", "linux_left_alone"])
    def test_a_links_own_bits_are_set_without_following_or_not_at_all(
        self, tmp_path, monkeypatch, no_follow, bare_is_the_links, expected
    ):
        """Each arm on any host, through a fake ``os.chmod`` that records and
        changes nothing: where the call can stop at the link it does; where it
        cannot, the link is left alone (a link's own mode never refuses an
        unlink on POSIX, so nothing is lost)."""
        link = _link_to(tmp_path / "link", _outside_file(tmp_path))
        calls: list[tuple[str, int, dict]] = []
        monkeypatch.setattr(os, "chmod", lambda p, m, **k: calls.append((str(p), m, k)))
        monkeypatch.setattr(_rmtree, "_CHMOD_NO_FOLLOW", no_follow)
        monkeypatch.setattr(_rmtree, "_BARE_CHMOD_IS_THE_LINKS", bare_is_the_links)

        _rmtree._add_write_bit(str(link))

        assert [k for _p, _m, k in calls] == expected, calls
        assert all(p == str(link) and m & stat.S_IWUSR for p, m, _k in calls), calls

    @pytest.mark.parametrize("no_follow,bare_is_the_links", [
        (True, False), (False, True), (False, False),
    ], ids=["follow_symlinks_false", "windows_to_3_12_bare", "linux"])
    def test_a_file_that_is_not_a_link_is_set_on_every_arm(self, tmp_path, monkeypatch, no_follow,
                                                         bare_is_the_links):
        f = tmp_path / "f"
        f.write_text("x", encoding="utf-8")
        calls: list[dict] = []
        monkeypatch.setattr(os, "chmod", lambda p, m, **k: calls.append(k))
        monkeypatch.setattr(_rmtree, "_CHMOD_NO_FOLLOW", no_follow)
        monkeypatch.setattr(_rmtree, "_BARE_CHMOD_IS_THE_LINKS", bare_is_the_links)
        _rmtree._add_write_bit(str(f))
        assert calls == [{"follow_symlinks": False} if no_follow else {}]


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
        monkeypatch.setattr(os, "chmod", lambda p, m, **k: (chmods.append((str(p), m)), real_chmod(p, m, **k)))
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
        monkeypatch.setattr(os, "chmod", lambda p, m, **k: (chmods.append(str(p)), real_chmod(p, m, **k)))
        handler = _rmtree._make_handler(True, str(root))
        handler(self._retry_func([]), str(root), PermissionError(errno.EACCES, "refused", str(root)))
        assert chmods == [str(root)], chmods

    @pytest.mark.parametrize("root_spelling", ["native", "forward_slashes", "trailing_separator"])
    def test_the_root_is_cleared_as_a_refusing_childs_parent(self, tmp_path, monkeypatch, root_spelling):
        """The tree's own root is part of the ask (DEF-3023). A ``build/`` at
        0o500 holding a subdirectory refuses that subdirectory's ``rmdir`` on
        POSIX, since the root's write bit governs it, so the root gets the
        bit as a directory inside the tree does, however the root was
        spelled; the root's own parent never does (the row above)."""
        root = tmp_path / "tree"
        (root / "sub").mkdir(parents=True)
        chmods: list[str] = []
        real_chmod = os.chmod
        monkeypatch.setattr(os, "chmod", lambda p, m, **k: (chmods.append(str(p)), real_chmod(p, m, **k)))
        calls: list = []
        child = str(root / "sub")
        spelled = {"native": str(root), "forward_slashes": root.as_posix(),
                   "trailing_separator": os.path.join(str(root), "")}[root_spelling]
        handler = _rmtree._make_handler(False, spelled)
        handler(self._retry_func(calls), child, PermissionError(errno.EACCES, "refused", child))
        assert calls == [child], "retried exactly once"
        assert chmods == [child, str(root)], chmods

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

    @pytest.mark.parametrize("enter", [os.open, os.scandir], ids=["open", "scandir"])
    @pytest.mark.parametrize("best_effort", [False, True], ids=["strict", "best_effort"])
    def test_a_refused_entry_walks_the_directory_again_never_retries_it_bare(
        self, tmp_path, enter, best_effort
    ):
        """``func(path)`` is not the call that refused when ``func`` enters a
        directory (``os.open`` needs its flags): the directory is walked
        again instead, and the walk's own later ``rmdir`` of it (3.10 to
        3.12 make one) finds nothing and is not a fault, strict included."""
        root = tmp_path / "tree"
        (root / "shut" / "inner").mkdir(parents=True)
        (root / "shut" / "inner" / "f").write_text("x", encoding="utf-8")
        handler = _rmtree._make_handler(best_effort, str(root))

        handler(enter, str(root / "shut"), PermissionError(errno.EACCES, "refused", str(root / "shut")))

        assert not os.path.exists(root / "shut")
        assert os.path.isdir(root), "only the refused directory was walked"
        handler(os.rmdir, str(root / "shut"), FileNotFoundError(errno.ENOENT, "gone", str(root / "shut")))

    def test_a_refused_entry_of_something_not_a_directory_is_reported_untouched(self, tmp_path):
        target = tmp_path / "f"
        target.write_text("x", encoding="utf-8")
        os.chmod(target, stat.S_IRUSR)
        before = _mode(target)  # 0o400 on POSIX; the read-only attribute reads 0o444 on Windows
        refused = PermissionError(errno.EACCES, "refused", str(target))
        with pytest.raises(PermissionError) as info:
            _rmtree._make_handler(False, str(tmp_path))(os.open, str(target), refused)
        assert info.value is refused
        _rmtree._make_handler(True, str(tmp_path))(os.open, str(target), refused)
        assert os.path.exists(target) and _mode(target) == before, "its bits were changed"

    def test_a_file_not_found_on_a_directory_never_walked_again_still_raises_strict(self, tmp_path):
        gone = FileNotFoundError(errno.ENOENT, "gone", str(tmp_path / "d"))
        with pytest.raises(FileNotFoundError):
            _rmtree._make_handler(False, str(tmp_path))(os.rmdir, str(tmp_path / "d"), gone)

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
    """3.12 grew ``onexc``; the floor is 3.11, where only ``onerror`` exists.
    Whichever this interpreter has, the handler must be reached with the
    ``(func, path, exception)`` shape."""

    @pytest.mark.parametrize("has_onexc", [True, False], ids=["onexc", "onerror"])
    def test_the_seam_picks_the_spelling_and_the_handler_gets_an_exception(
        self, tmp_path, monkeypatch, has_onexc
    ):
        """The seam the walk rows force a spelling through: each one reaches
        the handler with the exception, never the ``exc_info`` tuple."""
        seen: list = []
        used: list = []

        def fake_rmtree(path, onexc=None, onerror=None):
            used.append("onexc" if onexc is not None else "onerror")
            err = PermissionError(errno.EACCES, "refused", str(path))
            if onexc is not None:
                onexc(os.unlink, str(path), err)
                return
            try:
                raise err
            except PermissionError:
                onerror(os.unlink, str(path), sys.exc_info())

        monkeypatch.setattr(_rmtree, "_HAS_ONEXC", has_onexc)
        monkeypatch.setattr(shutil, "rmtree", fake_rmtree)
        _rmtree._rmtree_with_handler(tmp_path, lambda func, path, exc: seen.append(exc))
        assert used == ["onexc" if has_onexc else "onerror"]
        assert len(seen) == 1 and isinstance(seen[0], PermissionError)

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
