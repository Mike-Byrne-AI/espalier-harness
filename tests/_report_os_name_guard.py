"""Form every test report under the host's real ``os.name``.

WHY THIS EXISTS. ``tests/test_write_guard.py::_emulate_windows_paths`` patches
``os.name`` to ``nt`` so the hook normalisers can be driven with Windows path
semantics on a POSIX host. pytest forms a failing test's report BEFORE the
fixture teardown undoes that patch, and ``_pytest.nodes.Node._repr_failure_py``
builds ``Path(os.getcwd())`` while forming it. On CPython 3.10 and 3.11 a bare
``Path`` under ``os.name == "nt"`` refuses to construct a ``WindowsPath`` on a
POSIX host (``_from_parts`` checks the flavour's ``is_supported``), so ONE red
emulated row became a session ``INTERNALERROR`` with no failing test name --
and because the abort skipped the teardown, ``os.name`` stayed ``nt`` for the
session-finish hooks, whose own ``Path(entry)`` then died a second time. The
pre-cut review's D2 (2026-09-20): on the declared 3.10/3.11 floor a bare
``pytest`` on the guard file could not report. On 3.12+ construction succeeds
(``Path.__new__`` calls ``object.__new__``) and only a DERIVED path refuses, so
the formatter survives there and the abort was seen on the 3.10 CI cell alone.

THE FIX SHAPE. A hookwrapper around report formation: the report is formed
under the real name, and the patched value is put back afterwards so the
fixture's own undo still sees what it set. One site, every emulated row, every
interpreter. Registered by ``tests/conftest.py`` importing the hook by name;
the inner-session row in ``tests/test_write_guard.py`` (the emulation's own
class) drives a deliberately failing emulated test WITH and WITHOUT this module
and asserts the session reports in the first case and aborts in the second, so
the stressor's presence is asserted, not assumed.

Old-style ``hookwrapper=True`` deliberately: the declared floor is
``pytest>=7.0`` (``pyproject.toml``), and the new-style ``wrapper=True`` is
pytest 8+. Do not "modernise" this without moving the floor.

TWO WAYS THIS GOES QUIET, both driven by the red team (2026-09-22). (1) The
registration is one import line in ``tests/conftest.py``; dropping it is
invisible on 3.12+, where the formatter constructs anyway -- so
``tests/test_test_suite_contract.py::test_the_report_os_name_guard_is_registered``
asserts the hook is in the RUNNING session's plugin manager. (2) The wrapper
protects only what runs INSIDE it: a report-consuming plugin registered as an
outer wrapper (``tryfirst``) that builds a ``Path`` before this yield would
still abort -- hence ``tryfirst=True`` here, so this is the outermost wrapper.
A second ``pytest_runtest_makereport`` defined in the conftest itself would
shadow the imported name; ruff's ``F811`` (selected in ``pyproject.toml``)
reds that.
"""
from __future__ import annotations

import os

import pytest

#: The host's real ``os.name``, captured at import -- before any test patches it.
_REAL_OS_NAME = os.name


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """Form the report under the real ``os.name``; put the patched value back."""
    patched = os.name
    os.name = _REAL_OS_NAME
    try:
        yield
    finally:
        os.name = patched
