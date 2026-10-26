"""One stand-in for the operating system a test makes the harness read.

Two functions, kept apart on purpose:

* :func:`as_os` sets the platform the harness reads (``sys.platform``, and
  ``os.name`` only when asked) for the rest of the test, through the caller's
  ``monkeypatch``;
* :func:`without_the_alarm` deletes the ``signal`` names Windows lacks, so the
  harness's alarm-guarded paths take their Windows branch on any host.

They are two functions because of how the suite polices the alarm.
``tests/test_test_suite_contract.py::_sigalrm_offenders`` reads a unit that
deletes a name pytest-timeout's signal method reads as an arming unit, and asks
every test module that imports such a function BY NAME for
``pytestmark = pytest.mark.timeout(method="thread")``: under the signal method
the plugin's ``cancel()`` reads ``signal.SIGALRM`` after a failing call phase,
before teardown restores it, and the session ends in INTERNALERROR. A module
that imports :func:`as_os` alone is asked for nothing; one that imports
:func:`without_the_alarm` carries the mark (``tests/test_redos.py`` does), and
that contract is the rule's one home: no check here repeats it. Import the
names, never the module (``from tests import _platform_standin`` is a
whole-module import, which the contract reads as importing everything in it).

``os.name`` is opt-in because it is the dangerous half: a bare ``Path(...)``
under ``os.name == "nt"`` on a POSIX host raises ``NotImplementedError`` on
CPython 3.10 and 3.11 and builds a ``WindowsPath`` on 3.12+, so harness code
driven under it must construct no path. ``tests/test_write_guard.py::
_emulate_windows_paths`` is the one caller that needs it today, and
``tests/_report_os_name_guard.py`` covers report formation only, never the
test's own body or fixtures.

The registry (``tests/_axis_registry.py``) proves an ``os`` cell by a node
parametrised with an argument named ``os``. That argument shadows the ``os``
module inside the test function, so such a test reads ``os.name`` nowhere;
the two proving nodes do not.
"""
from __future__ import annotations

import os
import signal
import sys

import pytest

# value -> (sys.platform, os.name)
OS_VALUES: dict[str, tuple[str, str]] = {
    "linux": ("linux", "posix"),
    "macos": ("darwin", "posix"),
    "windows": ("win32", "nt"),
}

# The signal names Windows lacks, and the harness guards its alarms on.
WINDOWS_LACKS: tuple[str, ...] = ("SIGALRM", "setitimer", "ITIMER_REAL")


def as_os(monkeypatch: pytest.MonkeyPatch, value: str, *, os_name: bool = False) -> str:
    """Make the harness read ``value`` (a key of :data:`OS_VALUES`) for the rest
    of the test, and return the ``sys.platform`` it now reads. ``os_name=True``
    sets ``os.name`` too; the module docstring says what that costs."""
    platform, name = OS_VALUES[value]
    monkeypatch.setattr(sys, "platform", platform)
    if os_name:
        monkeypatch.setattr(os, "name", name)
    return platform


def without_the_alarm(monkeypatch: pytest.MonkeyPatch) -> tuple[str, ...]:
    """Delete the ``signal`` names Windows lacks for the rest of the test, and
    return them. The importing test module runs pytest-timeout's thread method;
    the suite contract asks it to (the module docstring says why)."""
    for name in WINDOWS_LACKS:
        monkeypatch.delattr(signal, name, raising=False)
    return WINDOWS_LACKS
