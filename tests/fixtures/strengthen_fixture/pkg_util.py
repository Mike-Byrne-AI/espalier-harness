"""Second synthetic module — NO ``__all__``, so the public surface falls back
to non-underscore top-level names. Provides a trivial, pure, non-exported,
untested public helper that must rank BELOW the exported I/O symbol.
"""


def small_helper():
    """Public (no __all__ → non-underscore), untested, trivial, pure."""
    return 0
