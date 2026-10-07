"""A hard bound and an honest verdict behind pytest-timeout's signal-method ceiling.

pyproject names no ``timeout_method`` (since 2026-10-07), so where SIGALRM exists
pytest-timeout's per-test ceiling is one alarm that raises ``Failed`` in the
main thread, once. That is what lets one slow test fail on its own while the run
reports the rest. It also gives up three things the thread method had, which
ended the whole process at the ceiling:

* ``Failed`` is a ``BaseException``, so code under test that catches one (the
  hooks' ``main()`` handlers do, when a test drives them in-process) swallows
  the ceiling, and a hang reads as a pass;
* after the one alarm nothing bounds the test: a cleanup that blocks again (a
  ``join``, a pool's ``__exit__``, a fixture's teardown waiting on the thing
  that hung) runs to the CI job's own limit;
* a non-daemon thread left stuck by a failed test keeps the process from
  exiting after the summary.

This plugin keeps the signal method's verdict and restores all three:

* when pytest-timeout's own alarm handler fails a test, the phase it fired in
  is flagged; if that phase still reports a pass, its ``Failed`` was caught,
  and the phase is reported failed (judged from the alarm firing, never from a
  clock, so a laptop that slept mid-test reads nothing);
* a daemon timer armed with the ceiling fires a grace period after it (the
  ceiling again, at most a minute) unless the WHOLE test protocol -- setup,
  call and teardown -- has ended, and ends the process through
  pytest-timeout's own ``timeout_timer``, the thread method's stack dump and
  exit. It is cancelled only by this plugin's protocol wrapper: pytest-timeout
  cancels its own alarm on every failed phase (``pytest_exception_interact``),
  which is exactly when a teardown is likeliest to block. Under xdist the
  worker dies and xdist names the test it was running;
* once a ceiling has fired in the session, the process is ended a minute after
  pytest unconfigures if it is still alive then (a stuck non-daemon thread).

Inert where pytest-timeout is absent or lacks an internal this plugin calls
(``missing_internals``; one named row reds then), where the method is ``thread`` (Windows,
and the modules that arm SIGALRM themselves), off the main thread (where the
plugin falls back to its thread method), and under ``func_only=True``, whose
ceiling deliberately leaves fixtures unbounded (no test here uses it).
Registered from tests/conftest.py; pinned by tests/test_timeout_backstop.py.
"""
from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable
from typing import Any

import pytest

PLUGIN_NAME = "espalier-timeout-backstop"

#: The backstop fires this long after the ceiling at most.
GRACE_CAP_S = 60.0

#: How long a process whose session saw a ceiling fire may outlive unconfigure.
EXIT_GRACE_S = 60.0

#: The pytest-timeout internals this plugin calls. A release that renames one
#: leaves the backstop unregistered and reds one named row, never every run
#: and never silently.
PLUGIN_INTERNALS = ("pytest_timeout_set_timer", "timeout_sigalrm", "timeout_timer")

#: The backstop timer of a test whose ceiling is a signal alarm.
_BACKSTOP = pytest.StashKey[threading.Timer]()

#: Set when pytest-timeout's alarm handler fails the test in the current phase.
_FIRED = pytest.StashKey[bool]()

#: The ceiling the test was armed with, in seconds (for the verdict's wording).
_CEILING = pytest.StashKey[float]()

#: Set on a session's config once any of its tests' ceilings fired.
_SESSION_FIRED = pytest.StashKey[bool]()

SWALLOWED = (
    "pytest-timeout's {ceiling:g} s per-test ceiling fired during this phase and "
    "the phase still reported a pass, so the ceiling's Failed was caught (it is a "
    "BaseException: an `except BaseException` in the code under test swallows it). "
    "Reported as a failure so a hang cannot read as green (tests/_timeout_backstop.py)."
)


def backstop_delay(ceiling: float) -> float:
    """Seconds from the ceiling's arming to the backstop: the ceiling plus a
    grace of the ceiling again, at most ``GRACE_CAP_S``."""
    return ceiling + min(GRACE_CAP_S, ceiling)


def start_backstop(nodeid: str, ceiling: float, fire: Callable[[], None]) -> threading.Timer:
    """A started daemon timer that names ``nodeid`` on stderr, then fires."""

    def name_then_fire() -> None:
        sys.stderr.write(f"\n[timeout backstop] {nodeid} outlived its {ceiling:g} s "
                         "ceiling by the grace period; ending the run\n")
        sys.stderr.flush()
        fire()

    timer = threading.Timer(backstop_delay(ceiling), name_then_fire)
    timer.daemon = True
    timer.name = f"timeout backstop {nodeid}"
    timer.start()
    return timer


def settle(item: Any, report: Any) -> None:
    """Fail ``report`` if the ceiling's alarm failed the test in this phase but
    the phase still passed. The flag is cleared either way: a phase whose
    ``Failed`` surfaced is already a failure."""
    if not item.stash.get(_FIRED, False):
        return
    item.stash[_FIRED] = False
    if report.passed:
        report.outcome = "failed"
        report.longrepr = SWALLOWED.format(ceiling=item.stash.get(_CEILING, 0.0))


def flagging(original: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap pytest-timeout's ``timeout_sigalrm`` so a ceiling that fails the
    test (it returns quietly under a debugger) flags the item first."""

    def timeout_sigalrm(item: Any, settings: Any) -> None:
        __tracebackhide__ = True
        try:
            original(item, settings)
        except BaseException:
            stash = getattr(item, "stash", None)
            if stash is not None:
                stash[_FIRED] = True
            config = getattr(item, "config", None)
            if config is not None:
                config.stash[_SESSION_FIRED] = True
            raise

    timeout_sigalrm.__wrapped__ = original  # type: ignore[attr-defined]
    return timeout_sigalrm


def arm_exit_bound(status: int, grace: float = EXIT_GRACE_S,
                   end: Callable[[int], Any] = os._exit) -> threading.Timer:
    """A started daemon timer that ends the process with ``status`` after
    ``grace`` seconds -- unless it has exited by then, which a daemon thread
    does not prevent -- naming the threads that held it open."""

    def name_then_end() -> None:
        stuck = sorted(t.name for t in threading.enumerate()
                       if not t.daemon and t is not threading.main_thread())
        sys.stderr.write(f"\n[timeout backstop] the run outlived pytest by {grace:g} s after a "
                         f"ceiling fired; non-daemon threads still alive: {stuck}; ending it\n")
        sys.stderr.flush()
        end(status or 1)

    timer = threading.Timer(grace, name_then_end)
    timer.daemon = True
    timer.name = "timeout backstop exit bound"
    timer.start()
    return timer


class TimeoutBackstop:
    """The plugin object tests/conftest.py registers beside pytest-timeout.

    ``owns_patch``: this session installed the flagging handler, so it alone
    restores it and arms the exit bound -- a pytest run in-process inside a
    test (none today) neither unwraps the outer session's handler nor ends
    the outer process."""

    def __init__(self, owns_patch: bool) -> None:
        self.owns_patch = owns_patch
        self.exitstatus = 1

    @pytest.hookimpl(tryfirst=True)
    def pytest_timeout_set_timer(self, item: Any, settings: Any) -> bool:
        import pytest_timeout

        # The plugin's own arming, unchanged; this hook is firstresult, so ours
        # runs instead of the plugin's and calls it.
        pytest_timeout.pytest_timeout_set_timer(item=item, settings=settings)
        if (settings.method != "signal" or getattr(settings, "func_only", False)
                or threading.current_thread() is not threading.main_thread()
                or _BACKSTOP in item.stash):
            return True
        item.stash[_CEILING] = float(settings.timeout)
        item.stash[_BACKSTOP] = start_backstop(
            item.nodeid, float(settings.timeout),
            lambda: pytest_timeout.timeout_timer(item, settings))
        return True

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item: Any, nextitem: Any):
        yield
        timer = item.stash.get(_BACKSTOP, None)
        if timer is not None:
            timer.cancel()

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item: Any, call: Any):
        outcome = yield
        settle(item, outcome.get_result())

    def pytest_sessionfinish(self, session: Any, exitstatus: int) -> None:
        self.exitstatus = int(exitstatus)

    @pytest.hookimpl(trylast=True)
    def pytest_unconfigure(self, config: pytest.Config) -> None:
        import pytest_timeout

        if not self.owns_patch:
            return
        wrapped = getattr(pytest_timeout.timeout_sigalrm, "__wrapped__", None)
        if wrapped is not None:
            pytest_timeout.timeout_sigalrm = wrapped
        if config.stash.get(_SESSION_FIRED, False):
            arm_exit_bound(self.exitstatus)


def timeout_hooks_present(config: Any) -> bool:
    """Whether pytest-timeout's hooks are declared in this session -- however
    the plugin was loaded (an entry point, ``-p pytest_timeout``, ...)."""
    return hasattr(config.hook, "pytest_timeout_set_timer")


def missing_internals() -> list[str]:
    """The pytest-timeout internals this plugin calls that the installed plugin
    lacks. Non-empty after an upstream rename: the backstop then stands down,
    and tests/test_timeout_backstop.py reds by name rather than every run."""
    try:
        import pytest_timeout
    except ImportError:
        return list(PLUGIN_INTERNALS)
    return [name for name in PLUGIN_INTERNALS if not callable(getattr(pytest_timeout, name, None))]


def pytest_configure(config: pytest.Config) -> None:
    """Register the backstop when pytest-timeout is loaded (its hooks exist
    only then; a runtime-only install runs without either) and provides the
    internals the backstop calls."""
    manager = config.pluginmanager
    if not timeout_hooks_present(config) or manager.hasplugin(PLUGIN_NAME) or missing_internals():
        return
    import pytest_timeout

    owns_patch = getattr(pytest_timeout.timeout_sigalrm, "__wrapped__", None) is None
    if owns_patch:
        pytest_timeout.timeout_sigalrm = flagging(pytest_timeout.timeout_sigalrm)
    manager.register(TimeoutBackstop(owns_patch), PLUGIN_NAME)
