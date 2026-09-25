"""Symlink-capability test gate.

Creating a symlink on Windows needs a privilege (``SeCreateSymbolicLinkPrivilege``,
granted by Developer Mode or an elevated process); a stock Windows dev box
raises ``OSError`` (``WinError 1314``, "A required privilege is not held by the
client") at ``os.symlink`` / ``Path.symlink_to``. POSIX hosts and CI runners
that hold the privilege create symlinks freely.

Tests that MUST plant a real symlink to exercise the symlink-handling code
(``read_text_nofollow`` refusal, ``safe_rglob`` skip, release-archive exclusion,
dangling-symlink settings detection, …) decorate with ``@requires_symlink`` so
they RUN wherever a symlink can be created and SKIP — rather than error — where
it cannot. The symlink-handling code itself is platform-agnostic Python
(``os.path.islink`` / ``Path.is_symlink`` behave the same on Windows) and stays
covered on POSIX, so the skip forfeits re-verification on a privilege-less
Windows box, not the guarantee.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


def symlinks_supported() -> bool:
    """Return True if this process can actually create a symlink."""
    try:
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "target"
            target.write_text("x", encoding="utf-8")
            link = Path(d) / "link"
            link.symlink_to(target)
            return link.is_symlink()
    except (OSError, NotImplementedError):
        return False


SYMLINKS_SUPPORTED = symlinks_supported()

requires_symlink = pytest.mark.skipif(
    not SYMLINKS_SUPPORTED,
    reason=(
        "symlink creation not permitted here (Windows needs Developer Mode or "
        "an elevated process; WinError 1314). POSIX and privileged CI run these."
    ),
)
