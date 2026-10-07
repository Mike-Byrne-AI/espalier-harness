"""A hard bound and an honest verdict behind pytest-timeout's signal-method ceiling.

pyproject names no ``timeout_method`` (since 2026-10-07), so where SIGALRM exists
pytest-timeout's per-test ceiling is one alarm that raises ``Failed`` in the
main thread, once. That is what lets one slow test fail on its own while the run
reports the rest. It also gives up two things the thread method had, which
ended the whole process at the ceiling:

* ``Failed`` is a ``BaseException``, so code under test that catches one (the
  hooks' ``main()`` handlers do, when a test drives them in-process) swallows
  the ceiling, and a hang reads as a pass;
* after the one alarm nothing bounds the test: a cleanup that blocks again (a
  ``join``, a pool's ``__exit__``) runs to the CI job's own limit.

This plugin keeps the signal method's verdict and restores both:

* a phase that ends past the ceiling but reports a pass is reported as a
  failure -- the alarm is armed for the whole test, so a pass after it means
  its ``Failed`` was caught;
* a daemon timer fires a grace period after the ceiling (the ceiling again, at
  most a minute) and ends the process through pytest-timeout's own
  ``timeout_timer`` -- the thread method's stack dump and exit. Under xdist the
  worker dies and xdist names the test it was running.

Inert where pytest-timeout is absent, where the method is ``thread`` (Windows,
and the modules that arm SIGALRM themselves), and off the main thread, where
the plugin falls back to its thread method. Registered from tests/conftest.py;
pinned by tests/test_timeout_backstop.py.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

PLUGIN_NAME = "espalier-timeout-backstop"

#: The backstop fires this long after the ceiling at most.
GRACE_CAP_S = 60.0

#: ``(start, ceiling, settings)`` for a test whose ceiling is a signal alarm,
#: until the first phase that ends past the ceiling settles it.
_ARMED = pytest.StashKey[tuple[float, float, Any]]()

SWALLOWED = (
    "pytest-timeout's {ceiling:g} s per-test ceiling passed during this phase and "
    "the phase still reported a pass, so the ceiling's Failed was caught (it is a "
    "BaseException: an `except BaseException` in the code under test swallows it). "
    "Reported as a failure so a hang cannot read as green (tests/_timeout_backstop.py)."
)


def backstop_delay(ceiling: float) -> float:
    """Seconds from the ceiling's arming to the backstop: the ceiling plus a
    grace of the ceiling again, at most ``GRACE_CAP_S``."""
    return ceiling + min(GRACE_CAP_S, ceiling)


def arm_backstop(item: Any, ceiling: float, fire: Callable[[], None]) -> threading.Timer:
    """Start the backstop timer and chain its cancel onto ``item.cancel_timeout``,
    which pytest-timeout calls when the test ends."""
    timer = threading.Timer(backstop_delay(ceiling), fire)
    timer.daemon = True
    timer.name = f"timeout backstop {getattr(item, 'nodeid', '?')}"
    timer.start()
    cancel = getattr(item, "cancel_timeout", None)

    def cancel_both() -> None:
        timer.cancel()
        if cancel is not None:
            cancel()

    item.cancel_timeout = cancel_both
    return timer


def settle(item: Any, report: Any, stop: float, debugging: Callable[[Any], bool]) -> None:
    """Fail ``report`` if its phase ended past a signal-method ceiling yet passed.

    Only the first phase that ends past the ceiling is judged: if it failed, the
    ceiling's ``Failed`` surfaced (or something else failed first) and the later
    phases are left alone."""
    armed = item.stash.get(_ARMED, None)
    if armed is None:
        return
    start, ceiling, settings = armed
    if stop - start < ceiling:
        return
    del item.stash[_ARMED]
    if report.passed and not debugging(settings):
        report.outcome = "failed"
        report.longrepr = SWALLOWED.format(ceiling=ceiling)


def _debugging(settings: Any) -> bool:
    """pytest-timeout's own rule: under a debugger the ceiling stands down."""
    import pytest_timeout

    return not settings.disable_debugger_detection and pytest_timeout.is_debugging()


class TimeoutBackstop:
    """The plugin object tests/conftest.py registers beside pytest-timeout."""

    @pytest.hookimpl(tryfirst=True)
    def pytest_timeout_set_timer(self, item: Any, settings: Any) -> bool:
        import pytest_timeout

        # The plugin's own arming, unchanged; this hook is firstresult, so ours
        # runs instead of the plugin's and calls it.
        pytest_timeout.pytest_timeout_set_timer(item=item, settings=settings)
        if settings.method != "signal" or threading.current_thread() is not threading.main_thread():
            return True
        item.stash[_ARMED] = (time.time(), float(settings.timeout), settings)
        arm_backstop(item, float(settings.timeout),
                     lambda: pytest_timeout.timeout_timer(item, settings))
        return True

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item: Any, call: Any):
        outcome = yield
        settle(item, outcome.get_result(), call.stop, _debugging)


def pytest_configure(config: pytest.Config) -> None:
    """Register the backstop when pytest-timeout is loaded (its hooks exist
    only then; a runtime-only install runs without either)."""
    manager = config.pluginmanager
    if manager.hasplugin("timeout") and not manager.hasplugin(PLUGIN_NAME):
        manager.register(TimeoutBackstop(), PLUGIN_NAME)
