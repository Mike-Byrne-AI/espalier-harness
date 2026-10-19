"""The runners' race a nested pytest child can lose, and the failure that names it.

Rows of ``tests/test_xdist_never_ran.py`` drive a pytest child whose xdist workers
die inside the build. On GitHub's macOS runners that child's own controller can
die first, inside execnet: handling a worker's collection-finished message, it
sends tests on a channel whose worker has already exited, and the child ends in
pytest's internal error before the row can read what it asserts (DEF-4032). The
row drives the child again; where every attempt ended in that race, it fails with
:class:`NestedControllerRaceLost`, a failure of its own type, so the platform
roster's expected failure (``tests/conftest.py::PLATFORM_EXPECTED_FAILURES``) can
name the race and nothing else. A timeout, another internal error, or an assertion
over a child that completed still fails as itself.

One home for the type, imported by the conftest and by the test module alike, so
the mark's ``raises`` and the driver's ``raise`` are one class: the conftest read
under a second module name would be a second class.
"""
from __future__ import annotations

import pytest

#: What the race's internal error ends in, as the driver reads a child's last raise
#: (``tests/test_xdist_never_ran.py::_what_raised``): execnet refusing to send on
#: the closed channel, raised from the write itself (a ``BrokenPipeError`` or a
#: ``ValueError: write to closed file``). Read on every red macOS leg since
#: 2026-10-18; DEF-4032 names the runs.
RACE_RAISE = "OSError: cannot send (already closed?)"


class NestedControllerRaceLost(pytest.fail.Exception):
    """Every child run a row drove ended in the runners' race: pytest's own
    failure, so the row fails wherever it is not expected to, and a type of its
    own, so the roster's expected failure absorbs this and nothing else."""


def lost_to_the_race(raised: list[str]) -> bool:
    """Whether a row lost every attempt to the race: each child's last raise, as
    the driver read it, is the race's own."""
    return bool(raised) and all(text == RACE_RAISE for text in raised)
