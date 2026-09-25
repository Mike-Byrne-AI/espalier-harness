"""TP-65 — cross-platform regression test for the freshness state-cache
open-flags constant.

Windows CPython omits ``os.O_NOFOLLOW`` and ``os.O_NONBLOCK`` as POSIX-only
attributes. The previous inline OR expression
``os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC`` raised
``AttributeError`` at module-import time on Windows, crashing the
statusline and SessionStart hook on first run.

The fix moved the expression to a module-level ``_CACHE_OPEN_FLAGS``
constant built via ``getattr(os, NAME, 0)``. These tests simulate the
Windows ``os`` shape by stripping the POSIX-only attributes and
re-importing both reader modules.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import espalier
import espalier.freshness  # noqa: F401  (binds the package attribute this test must restore)


_POSIX_ONLY_ATTRS = ("O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC")


class TestCacheOpenFlagsCrossPlatform:
    def test_espalier_freshness_constant_uses_getattr_fallback(
        self, monkeypatch
    ) -> None:
        for attr in _POSIX_ONLY_ATTRS:
            monkeypatch.delattr(os, attr, raising=False)
        # ``importlib.import_module`` on a SUBMODULE rebinds it as an attribute
        # of the parent package as well as in ``sys.modules``. monkeypatch's
        # delitem only restores the ``sys.modules`` half, so without this line
        # teardown leaves TWO live ``espalier.freshness`` objects -- the original
        # in ``sys.modules`` and the re-imported one on the package -- and any
        # later ``from espalier import freshness`` reaches the wrong one. That
        # split silently emptied test_audit_accuracy's freshness verdicts.
        monkeypatch.setattr(espalier, "freshness", espalier.freshness, raising=False)
        monkeypatch.delitem(sys.modules, "espalier.freshness", raising=False)

        mod = importlib.import_module("espalier.freshness")

        assert mod._CACHE_OPEN_FLAGS == os.O_RDONLY

    def test_tools_cc_freshness_cache_constant_uses_getattr_fallback(
        self, monkeypatch
    ) -> None:
        for attr in _POSIX_ONLY_ATTRS:
            monkeypatch.delattr(os, attr, raising=False)
        monkeypatch.delitem(sys.modules, "_freshness_cache", raising=False)

        tools_cc = Path(__file__).parent.parent / "tools" / "cc"
        monkeypatch.syspath_prepend(str(tools_cc))

        mod = importlib.import_module("_freshness_cache")

        assert mod._CACHE_OPEN_FLAGS == os.O_RDONLY
