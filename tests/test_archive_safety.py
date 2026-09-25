"""TP-221: behavioral coverage for espalier/_archive_safety.py.

The pre-existing test (tests/test_no_unsafe_tarfile_extractall.py) is a
STATIC AST lint -- it never calls the helpers with a malicious member, so an
inverted comparison in `_check_member_path` ships green silently. This suite
guards that runtime path-containment check: it calls the helpers with real
path-traversal / absolute / sibling-prefix members built in `tmp_path` and
asserts the documented exception type is raised (and benign members extract).

Earn-the-red (see TP-221 pack): inverting the line-32 comparison
(`... and not member_str.startswith(dest_prefix)` -> drop the `not`) turns 5
of these 6 cases RED. The tar-traversal case is double-defended on 3.12+ by
`tf.extractall(filter="data")` and stays green under the inversion -- it is a
behavioral guarantee, not a clean earn-the-red on a 3.12+ host (documented
inline below).
"""
from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from espalier._archive_safety import (
    _check_member_path,
    safe_extract_tar,
    safe_extract_zip,
)


def _write_tar(path: Path, name: str, data: bytes = b"x") -> None:
    """Build a one-member tar at ``path`` with a member literally named ``name``.

    Using a raw ``TarInfo`` lets us plant traversal / absolute member names
    that ``tf.add(...)`` would otherwise normalize away.
    """
    with tarfile.open(path, "w") as tf:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))


def _write_zip(path: Path, name: str, data: str = "x") -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(name, data)


@pytest.mark.security
class TestArchiveSafety:
    # ---- tar ----------------------------------------------------------------

    def test_tar_traversal_member_raises(self, tmp_path):
        """A '../escape' tar member must not extract outside dest.

        NOTE: on Python 3.12+ this is double-defended -- the path check AND
        `tf.extractall(filter="data")` both reject it. This case is a
        behavioral guarantee; the clean earn-the-red for the path check is
        `test_sibling_prefix_member_raises` + the benign cases (which fail
        only on the line-32 comparison).
        """
        arc = tmp_path / "evil.tar"
        _write_tar(arc, "../escape.txt", b"pwned")
        dest = tmp_path / "out"
        dest.mkdir()
        with tarfile.open(arc) as tf:
            with pytest.raises(tarfile.TarError):
                safe_extract_tar(tf, dest)
        assert not (tmp_path / "escape.txt").exists()

    def test_tar_absolute_member_raises(self, tmp_path):
        """An absolute-path tar member ('/etc/x') escapes dest and must raise."""
        arc = tmp_path / "abs.tar"
        _write_tar(arc, "/etc/x", b"pwned")
        dest = tmp_path / "out"
        dest.mkdir()
        with tarfile.open(arc) as tf:
            with pytest.raises(tarfile.TarError):
                safe_extract_tar(tf, dest)

    def test_tar_benign_member_extracts(self, tmp_path):
        """A benign nested member extracts to dest with correct content."""
        arc = tmp_path / "ok.tar"
        _write_tar(arc, "sub/ok.txt", b"hello")
        dest = tmp_path / "out"
        dest.mkdir()
        with tarfile.open(arc) as tf:
            safe_extract_tar(tf, dest)
        extracted = dest / "sub" / "ok.txt"
        assert extracted.exists()
        assert extracted.read_bytes() == b"hello"

    # ---- _check_member_path: the sibling-prefix bug -------------------------

    def test_sibling_prefix_member_raises(self, tmp_path):
        """Classic startswith()-vs-containment bug.

        dest = /a/b ; a member resolving to /a/bc is a STRING prefix of /a/b
        but NOT a subdirectory of it. A raw `member_str.startswith(str(dest))`
        check would wrongly admit it. The helper guards against this by
        appending a trailing '/' to dest_prefix (lines 47/66:
        `... .rstrip("/") + "/"`), so /a/bc does not start with /a/b/ . We
        assert the helper RAISES -- a prefix-only check would not.
        """
        b = tmp_path / "a" / "b"
        b.mkdir(parents=True)
        dest_resolved = b.resolve()
        # Build dest_prefix exactly as the helpers do (lines 47 / 66).
        dest_prefix = str(dest_resolved).replace("\\", "/").rstrip("/") + "/"
        # '../bc' from /a/b resolves to /a/bc -- sibling, string-prefix match.
        with pytest.raises(ValueError):
            _check_member_path("../bc", dest_resolved, dest_prefix)

    # ---- zip ----------------------------------------------------------------

    def test_zip_traversal_member_raises(self, tmp_path):
        """A '../escape' zip member must raise (zip has no filter= analog)."""
        arc = tmp_path / "evil.zip"
        _write_zip(arc, "../zescape.txt", "pwn")
        dest = tmp_path / "zout"
        dest.mkdir()
        with zipfile.ZipFile(arc) as zf:
            with pytest.raises(zipfile.BadZipFile):
                safe_extract_zip(zf, dest)
        assert not (tmp_path / "zescape.txt").exists()

    def test_zip_benign_member_extracts(self, tmp_path):
        """A benign nested zip member extracts to dest with correct content."""
        arc = tmp_path / "ok.zip"
        _write_zip(arc, "zsub/ok.txt", "zhello")
        dest = tmp_path / "zout"
        dest.mkdir()
        with zipfile.ZipFile(arc) as zf:
            safe_extract_zip(zf, dest)
        extracted = dest / "zsub" / "ok.txt"
        assert extracted.exists()
        assert extracted.read_text(encoding="utf-8") == "zhello"
