"""Reference file for the cross-ref earn-the-red.

Deliberately named ``uses_kept.py`` (NOT ``test_*``) so pytest never collects
or imports it, yet it lives under a ``tests/`` dir so the strengthen
cross-reference counts a code reference to ``kept`` here as a test reference.
Never executed; the bare ``kept()`` below is a textual target only.
"""


def exercise():
    return kept() == 1  # noqa: F821 -- textual cross-ref target, never run
