"""A wait budget that keeps its place under the ceiling its test runs at (DEF-5067).

pyproject's ``timeout = 60`` is the suite's per-test ceiling, and every wait
budget under tests/ sits below the ceiling of the tests that run it
(tests/test_test_suite_contract.py, the per-test ceiling block). The Windows
legs run the suite at ``PYTEST_TIMEOUT=180`` (.github/workflows/portability.yml
and post-merge-windows.yml), so a budget written against 60 s fires there at a
quarter of its test's ceiling: ``_seeded_with_tools_cc``'s ``git add -A`` and
``git fetch`` timed out at 45 s in tests the leg gives 180 s (runs 41439992695
and 41495686553, 2026-11-02).

``scaled(n)`` is ``n`` times the running test's ceiling over the ceiling the
contract judged ``n`` against -- the test's own timeout mark where it gives
seconds, else the ini's -- so a budget stands to the ceiling it runs under as
the literal stands to the one the contract read: ``scaled(45)`` is 135 s on the
leg, 45 s at the ini's 60, and 45 s under a test's own mark, which the leg's
variable does not move. The contract reads ``scaled(45)`` as 45. The ceiling is
the one pytest-timeout armed, as tests/_timeout_backstop.py stashes it; outside
a test's protocol (collection, a hook pytest runs outside every item) and where
no ceiling is armed the factor is 1.

Call it at the wait, ``timeout=scaled(45)``: a module constant, a default or a
decorator is evaluated at import, outside every test, and keeps the literal, so
the contract refuses ``scaled`` there. Pinned by tests/test_timeout_backstop.py.

It reads the backstop conftest registered from ``sys.modules`` and imports
nothing: a caller outside pytest (a script that reaches tests/_live_tree.py)
gets the literal without loading pytest, and no second copy of the backstop can
answer for the one the session armed.
"""
from __future__ import annotations

import sys
from typing import Any

#: The module tests/conftest.py registers the backstop from.
BACKSTOP_MODULE = "tests._timeout_backstop"


def scaled(seconds: float) -> float:
    """``seconds`` times the running test's ceiling over the one it was judged against."""
    backstop = sys.modules.get(BACKSTOP_MODULE)
    armed = backstop.armed() if backstop is not None else None
    if armed is None:
        return seconds
    item, ceiling = armed
    return seconds * factor(ceiling, mark_seconds(item), ini_seconds(item.config))


def factor(ceiling: float, mark: float | None, ini: float | None) -> float:
    """The armed ``ceiling`` over the one the contract judged a budget against:
    ``mark``, the test's own timeout mark's seconds, else ``ini``. 1 where that
    one is missing or not positive."""
    judged = mark if mark is not None else ini
    if not judged or judged <= 0 or ceiling <= 0:
        return 1.0
    return ceiling / judged


def mark_seconds(item: Any) -> float | None:
    """The seconds the closest timeout mark gives, read as pytest-timeout reads
    it (``_parse_marker``: the ``timeout`` keyword, else the first argument);
    None where there is no mark or it gives none."""
    marker = item.get_closest_marker("timeout")
    if marker is None:
        return None
    seconds = marker.kwargs.get("timeout", marker.args[0] if marker.args else None)
    try:
        return None if seconds is None else float(seconds)
    except (TypeError, ValueError):
        return None


def ini_seconds(config: Any) -> float | None:
    """The ini's ``timeout``; None where it is unset or not a number."""
    try:
        return float(config.getini("timeout"))
    except (TypeError, ValueError):
        return None
