"""Regression tests for espalier/assets.py cross-version import safety.

B-2 (OSS-launch blocker): ``from importlib.resources.abc import Traversable`` is
a 3.11+ symbol, but ``requires-python`` is ``>=3.10`` and CI runs a 3.10 matrix
leg. A bare top-level import there raises ``ModuleNotFoundError`` at
``import espalier.cli`` time, reding the first public push. The fix guards the
import with a fallback to ``importlib.abc.Traversable`` (3.10-only; that symbol
was *removed* in 3.14, so the modern location must be tried first).
"""
# pytest-marker: default-unit
from __future__ import annotations

import ast
import importlib
import importlib.abc
import sys
from pathlib import Path

import pytest

import espalier.assets

_ASSETS_SRC = Path(espalier.assets.__file__)


def test_traversable_is_a_real_runtime_symbol() -> None:
    """The guarded import keeps ``Traversable`` a real class, not a string."""
    assert isinstance(espalier.assets.Traversable, type)


def test_resources_abc_import_is_guarded_not_bare() -> None:
    """earn-the-red: the 3.11+ ``importlib.resources.abc`` import must be nested
    in a try/except, never a bare module-level import (which crashes on 3.10).
    Pre-fix this is a direct child of the module body and the assertion fails.
    """
    tree = ast.parse(_ASSETS_SRC.read_text(encoding="utf-8"))
    toplevel = [
        n.module for n in tree.body if isinstance(n, ast.ImportFrom)
    ]
    assert "importlib.resources.abc" not in toplevel, (
        "importlib.resources.abc must be guarded in try/except (3.10 lacks it), "
        "not imported bare at module level"
    )
    # It IS imported (inside the Try) and the 3.10 fallback IS present.
    nested = [
        n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
    ]
    assert "importlib.resources.abc" in nested
    assert "importlib.abc" in nested


def test_assets_imports_under_py310_like_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real module re-imports cleanly when ``importlib.resources.abc`` is
    unavailable (the 3.10 condition), resolving ``Traversable`` from the
    ``importlib.abc`` fallback.
    """
    if not hasattr(importlib.abc, "Traversable"):
        pytest.skip(
            "importlib.abc.Traversable removed on 3.14+; the fallback branch is "
            "reachable only on Python 3.10"
        )
    # Simulate 3.10: make `from importlib.resources.abc import ...` raise ImportError.
    monkeypatch.setitem(sys.modules, "importlib.resources.abc", None)
    monkeypatch.delitem(sys.modules, "espalier.assets", raising=False)
    reloaded = importlib.import_module("espalier.assets")
    assert reloaded.Traversable is importlib.abc.Traversable
