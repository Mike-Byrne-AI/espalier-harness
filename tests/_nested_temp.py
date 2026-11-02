"""A pytest child a test launches keeps its temp dirs inside its parent
session's, so it never deletes another session's dir inside the test's clock.

pytest gives each session a numbered basetemp (``pytest-N``) under one root
per user and, when the session ends, deletes every unlocked numbered dir three
or more below the newest (``_pytest/pathlib.py::cleanup_numbered_dir``); a
session's own lock goes at its end. So the first session to end after a big
run finishes deletes that run's whole dir, and when that session is a child a
test launched, the delete runs inside the test's clock: on windows-latest the
cited-pin child of ``tests/test_declared_limits_contract.py`` paid the
parallel leg's 8.9 GB basetemp that way and ran past its 300 s bound
(DEF-5056).

So each session exports its basetemp (:data:`KEY`, from the suite's conftest)
for the children its tests launch, and a child whose temp root holds that dir
takes its basetemp inside it: given a basetemp, pytest makes no numbered dir
and deletes nothing of another session's, and the child's dir goes with the
parent's, at a later top-level session's end. Left to pytest's default: a
child whose temp root is its own (a test that moved it to watch pytest's
handling), one given ``--basetemp``, an xdist worker (xdist gives it one),
and the children of a session given a ``--basetemp`` outside the temp root
(their parent's dir is not on their root, so they are not nested). A child
that loads no suite conftest (a planted tree) or runs a clone at an older
revision cannot take this rule, so its launcher passes ``--basetemp``
(``tests/test_box_lock.py``, ``tests/test_xdist_never_ran.py``,
``scripts/verify_pins.py``).
Registered from ``tests/conftest.py``; pinned by ``tests/test_nested_temp.py``.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

#: The basetemp of the test session that launched this process.
KEY = "ESPALIER_PARENT_BASETEMP"


def parent_basetemp() -> Path | None:
    """The launching session's basetemp as the export names it, else None."""
    value = os.environ.get(KEY)
    return Path(value) if value else None


def temp_root() -> Path:
    """The dir this process's numbered dirs would go under, read as pytest
    reads it (``_pytest/tmpdir.py::TempPathFactory.getbasetemp``)."""
    return Path(os.environ.get("PYTEST_DEBUG_TEMPROOT") or tempfile.gettempdir()).resolve()


def nested_basetemp(parent: Path, pid: int) -> Path:
    """Where a child takes its basetemp inside the parent's: a fresh dir, so
    a recycled pid never hands a later child an earlier one's to empty."""
    return Path(tempfile.mkdtemp(prefix=f"nest-{pid}-", dir=parent))


def pytest_configure(config: Any) -> None:
    """Point a launched session's basetemp inside its parent's, before
    pytest's own tmpdir plugin reads the option."""
    if hasattr(config, "workerinput"):
        return
    option = getattr(config, "option", None)
    if option is None or getattr(option, "basetemp", None):
        return
    parent = parent_basetemp()
    if parent is None or not parent.is_dir():
        return
    try:
        if parent.resolve().is_relative_to(temp_root()):
            option.basetemp = str(nested_basetemp(parent, os.getpid()))
    except OSError:  # a dir that cannot be read or made leaves pytest's default
        return
