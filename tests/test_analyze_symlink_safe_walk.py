"""Regression: `_iter_files` must not follow directory symlinks (TP-193 R4).

Before this fix `espalier/analyze.py::_iter_files` walked with a bare
``repo_root.rglob("*")``. On CPython < 3.13 (where ``recurse_symlinks`` only
became a default-False knob in 3.13) ``rglob`` follows directory symlinks
unconditionally, so:

  * a directory-symlink LOOP traps the walk -> ``OSError(ELOOP)`` crashes
    ``espalier fingerprint`` / ``init`` on a real adopter repo; and
  * a benign symlinked vendor dir gets its files yielded TWICE (once via the
    real path, once via the link), inflating the language counts.

The fix swaps to ``os.walk`` (followlinks=False default), which never descends
a dir symlink. These tests LOCK that behavior. Honest note: on Python >= 3.13
the old ``rglob`` was already symlink-safe by default, so on a 3.13+ interpreter
these pass with or without the fix — they earn their red only on the supported
3.10-3.12 floor. They are a forward-port contract lock, not a local red.
"""
from __future__ import annotations

# pytest-marker: default-unit  (pure-function _iter_files test; not a grandfather entry)

import os

import pytest

from espalier.analyze import _iter_files

from tests._symlink_support import requires_symlink

pytestmark = requires_symlink

# Symlink creation needs privilege on Windows; skip cleanly where unavailable.
_symlinks_ok = hasattr(os, "symlink")


@pytest.mark.skipif(not _symlinks_ok, reason="platform cannot create symlinks")
def test_iter_files_does_not_double_count_through_dir_symlink(tmp_path):
    """A symlinked directory's content is yielded once (real path), not twice."""
    real = tmp_path / "real"
    real.mkdir()
    (real / "uniquely_named.py").write_text("x = 1\n", encoding="utf-8")
    # link -> real : rglob (<3.13) would yield real/uniquely_named.py AND
    # link/uniquely_named.py; os.walk(followlinks=False) yields only the former.
    os.symlink(real, tmp_path / "link", target_is_directory=True)

    names = [p.name for p in _iter_files(tmp_path)]
    assert names.count("uniquely_named.py") == 1


@pytest.mark.skipif(not _symlinks_ok, reason="platform cannot create symlinks")
def test_iter_files_survives_a_directory_symlink_loop(tmp_path):
    """A directory-symlink loop must not raise OSError(ELOOP) or hang."""
    real = tmp_path / "real"
    real.mkdir()
    (real / "f.py").write_text("y = 2\n", encoding="utf-8")
    # real/loop -> real : a classic self-referential loop.
    os.symlink(real, real / "loop", target_is_directory=True)

    # Bounded materialization — must terminate without OSError.
    files = list(_iter_files(tmp_path))
    assert any(p.name == "f.py" for p in files)
    # f.py is reached once via the real path, never multiplied through the loop.
    assert [p.name for p in files].count("f.py") == 1
