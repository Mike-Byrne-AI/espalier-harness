"""``espalier/assets.py`` imports ``Traversable`` from ``importlib.resources.abc``
directly: the module exists on every interpreter the floor (3.11) allows, and
``importlib.abc.Traversable`` was removed in 3.14, so there is no second home to
fall back to.
"""
# pytest-marker: default-unit
from __future__ import annotations

import espalier.assets


def test_traversable_is_a_real_runtime_symbol() -> None:
    """The direct import keeps ``Traversable`` a real class, not a string."""
    assert isinstance(espalier.assets.Traversable, type)
