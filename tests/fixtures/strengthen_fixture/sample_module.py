"""Synthetic target module for the strengthen engine earn-the-reds.

Not collected by pytest (non-``test_`` name) and never imported — its bytes
exist only as an enumeration/cross-reference target. ``__all__`` is present, so
the public surface is exactly {kept, writer}; ``helper`` (not exported) and
``_private`` (underscore) are excluded.
"""
__all__ = ["kept", "writer"]


def kept():
    """Exported, trivial, pure — and referenced by the tests/ tree (tested)."""
    return 1


def writer(path):
    """Exported and does I/O — but no test references it (untested, high risk)."""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("data")


def helper():
    """Public-looking but NOT in __all__ → excluded while __all__ is present."""
    return 2


def _private():
    """Underscore-prefixed → never public surface."""
    return 3
