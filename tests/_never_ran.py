"""Count the selected tests that never ran, in a line ``-q`` keeps (DEF-2020).

pytest-xdist replaces a crashed worker (on Windows, pytest-timeout's thread
method ends the worker at the per-test ceiling) up to ``--max-worker-restart``,
by default four per worker. Past that cap the controller stops scheduling and
says so in a line ``-q`` never prints, so a quiet run's summary names the reds
it got and nothing says the rest never ran. On the process that prints the
run, this plugin compares the tests the session selected with the tests a
report arrived for. Where they differ, it writes one line through
``write_line``, which ``-q`` keeps. Where xdist's cap is what stopped the run,
the line says so, and it says so too when the cap stopped the run before any
worker finished collecting. A run stopped by ``-x`` or ``--maxfail`` gets the
count with no reason, since pytest names that stop itself.

The line is written after the short test summary, just above the final
counts, so a reader of the run's last lines sees it: ``scripts/host_check.py``
keeps a step's last 25 lines in its ``SUMMARY.md``, and every crash past the
first is one more ``FAILED`` line in that summary. That placement needs a
wrapper around the terminal reporter's own, so this is a plugin object that
``tests/conftest.py``'s ``pytest_configure`` registers, as it registers the
timeout backstop (old-style ``hookwrapper`` for the ``pytest>=7.0`` floor, as
``tests/_report_os_name_guard.py`` says). It is a summary aid: a failure inside
it is named in one line, never raised, so it cannot cost a run its summary.
It counts node ids, so a run that selects one id twice (``--keep-duplicates``)
or runs every test on every worker (``--dist each``) is outside what it reads;
neither appears in this tree.
"""
from __future__ import annotations

import os

import pytest

#: The name the plugin object is registered under.
PLUGIN_NAME = "never-ran"
#: Options that collect without running a test (``config.option`` attribute
#: names). No count is owed under them, and ``tests/conftest.py``'s tree build
#: reads the same tuple: nothing needs the tree there either.
NO_TEST_RUNS = ("collectonly", "showfixtures", "show_fixtures_per_test", "setupplan")


def count_line(selected: int, ran: int, crashes: int, cap: int | None) -> str | None:
    """The line for a run that selected ``selected`` tests and got a report
    for ``ran`` of them, after ``crashes`` workers went down under xdist's
    restart ``cap`` (``None`` without a crash, or without xdist); ``None``
    when nothing is owed."""
    capped = cap is not None and crashes > cap
    reason = f"xdist stopped replacing crashed workers: its --max-worker-restart cap is {cap}"
    unrun = selected - ran
    if unrun > 0:
        line = f"{unrun} of {selected} selected tests never ran"
        return f"{line} ({reason})" if capped else line
    if capped and not selected:
        return f"no worker finished collecting ({reason})"
    return None


def _restart_cap(config) -> int | None:
    """xdist's restart cap for this run, read by xdist's own function: the
    ``--max-worker-restart`` value, else four per worker. Read only after a
    worker went down, so xdist is loaded and its options exist (an installed
    xdist that ``-p no:xdist`` left unloaded registers none)."""
    from xdist.dsession import get_default_max_worker_restart

    return get_default_max_worker_restart(config)


class NeverRan:
    """The plugin object: what the session selected, how many xdist workers
    went down, and the line."""

    def __init__(self) -> None:
        self.selected = 0
        self.crashes = 0

    def pytest_sessionfinish(self, session) -> None:
        """Selected after deselection; on the xdist controller, what the
        workers collected. The terminal reporter's own finish is a wrapper that
        writes the summary after this has run."""
        self.selected = session.testscollected

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node, error) -> None:
        """xdist, on the controller: each worker that went down with an error is
        a crash toward ``--max-worker-restart``."""
        if error:
            self.crashes += 1

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_terminal_summary(self, terminalreporter, config):
        """Outermost, so the line follows the terminal reporter's short test
        summary. Nothing under an option that runs no test."""
        yield
        if any(getattr(config.option, name, False) for name in NO_TEST_RUNS):
            return
        try:
            ran = {report.nodeid for reports in terminalreporter.stats.values()
                   for report in reports if isinstance(report, pytest.TestReport)}
            cap = _restart_cap(config) if self.crashes else None
            line = count_line(self.selected, len(ran), self.crashes, cap)
        except Exception as exc:  # noqa: BLE001 - a summary aid names its own failure, never raises
            line = f"the never-ran count failed ({type(exc).__name__}: {exc}; tests/_never_ran.py)"
        if line is None:
            return
        terminalreporter.write_line(line)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            terminalreporter.write_line(f"::warning::{line}")


def pytest_configure(config) -> None:
    """Register the plugin on the process that prints the run, once: never on
    an xdist worker, whose reports reach the controller."""
    if not hasattr(config, "workerinput") and not config.pluginmanager.hasplugin(PLUGIN_NAME):
        config.pluginmanager.register(NeverRan(), PLUGIN_NAME)
