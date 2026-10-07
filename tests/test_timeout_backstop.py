"""Pins for tests/_timeout_backstop.py: behind a signal-method ceiling, a pass
after the ceiling fired is a failure, a test that blocks again -- in its body or
in a fixture's teardown -- is still ended, and the run still exits.

The logic rows run on every host. The end-to-end rows drive a real pytest child
under pytest-timeout's signal method, so they need SIGALRM: they run on the
POSIX CI cells and skip on Windows, where the method is thread and the backstop
stands down.
"""
from __future__ import annotations

# slow-exempt: three one-test pytest children of two or three seconds each, and
# only where SIGALRM exists; the rest is in-process.

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import _timeout_backstop as backstop

REPO_ROOT = Path(__file__).resolve().parent.parent

_NEEDS_SIGALRM = pytest.mark.skipif(
    not hasattr(signal, "SIGALRM"),
    reason="the signal method needs SIGALRM; this host's ceiling is the thread method",
)


def _item(fired: bool):
    item = SimpleNamespace(stash=pytest.Stash(), nodeid="t.py::test_x")
    item.stash[backstop._CEILING] = 60.0
    if fired:
        item.stash[backstop._FIRED] = True
    return item


def _report(passed: bool):
    return SimpleNamespace(passed=passed, outcome="passed" if passed else "failed",
                           longrepr=None)


class TestTheVerdictCannotBeSwallowed:
    def test_a_pass_in_the_phase_the_ceiling_fired_in_is_failed(self):
        item, report = _item(fired=True), _report(passed=True)
        backstop.settle(item, report)
        assert report.outcome == "failed" and "Failed was caught" in report.longrepr
        assert "60 s" in report.longrepr

    def test_a_phase_the_ceiling_did_not_fire_in_is_left_alone(self):
        # Judged from the alarm, never a clock: a long phase on a laptop that
        # slept mid-test is not accused.
        item, report = _item(fired=False), _report(passed=True)
        backstop.settle(item, report)
        assert report.outcome == "passed"

    def test_a_surfaced_ceiling_clears_the_flag_for_the_later_phases(self):
        item = _item(fired=True)
        call, teardown = _report(passed=False), _report(passed=True)
        backstop.settle(item, call)
        backstop.settle(item, teardown)
        assert call.outcome == "failed" and teardown.outcome == "passed"

    def test_the_handler_flags_a_ceiling_that_fails_and_not_one_that_stands_down(self):
        def fails(item, settings):
            raise pytest.fail.Exception("Timeout >60.0s")

        def stands_down(item, settings):  # pytest-timeout under a debugger
            return None

        item = _item(fired=False)
        with pytest.raises(pytest.fail.Exception):
            backstop.flagging(fails)(item, None)
        assert item.stash[backstop._FIRED] is True
        quiet = _item(fired=False)
        backstop.flagging(stands_down)(quiet, None)
        assert quiet.stash.get(backstop._FIRED, False) is False

    def test_the_installed_handler_is_the_flagging_one(self, pytestconfig):
        pytest_timeout = pytest.importorskip("pytest_timeout")
        assert pytestconfig.pluginmanager.hasplugin(backstop.PLUGIN_NAME)
        assert getattr(pytest_timeout.timeout_sigalrm, "__wrapped__", None) is not None, (
            "pytest-timeout's alarm handler is not wrapped: a swallowed ceiling would "
            "read as a pass")


class TestTheBackstopEndsATestThatBlocksAgain:
    def test_the_delay_is_the_ceiling_plus_the_ceiling_again_at_most_a_minute(self):
        assert backstop.backstop_delay(1) == 2
        assert backstop.backstop_delay(60) == 120
        assert backstop.backstop_delay(660) == 720

    def test_it_fires_after_the_delay(self):
        fired = threading.Event()
        t0 = time.monotonic()
        timer = backstop.start_backstop("t.py::test_x", 0.05, fired.set)
        assert timer.daemon, "a non-daemon backstop would hold the process open itself"
        assert fired.wait(5), "the backstop never fired"
        assert time.monotonic() - t0 >= 0.09

    def test_only_the_end_of_the_whole_protocol_cancels_it(self):
        # pytest-timeout cancels its own alarm on every failed phase; the
        # backstop is not chained to that cancel, so a teardown that blocks
        # after a surfaced ceiling is still bounded.
        fired = threading.Event()
        item = SimpleNamespace(stash=pytest.Stash(), nodeid="t.py::test_x",
                               cancel_timeout=lambda: None)
        item.stash[backstop._BACKSTOP] = backstop.start_backstop(item.nodeid, 0.05, fired.set)
        item.cancel_timeout()  # what pytest-timeout does on a failed phase
        assert fired.wait(5), "the plugin's cancel reached the backstop"
        later = threading.Event()
        item.stash[backstop._BACKSTOP] = backstop.start_backstop(item.nodeid, 0.05, later.set)
        wrapper = backstop.TimeoutBackstop().pytest_runtest_protocol(item=item, nextitem=None)
        next(wrapper)
        with pytest.raises(StopIteration):
            wrapper.send(None)
        assert not later.wait(0.3), "the protocol's end did not cancel the backstop"

    def test_a_stuck_process_is_ended_after_the_session(self):
        ended: list[int] = []
        timer = backstop.arm_exit_bound(1, grace=0.05, end=ended.append)
        assert timer.daemon
        timer.join(5)
        assert ended == [1]


def test_a_renamed_plugin_internal_is_a_configure_error(monkeypatch):
    pytest_timeout = pytest.importorskip("pytest_timeout")
    monkeypatch.delattr(pytest_timeout, "timeout_timer")
    manager = SimpleNamespace(hasplugin=lambda name: False,
                              register=lambda *a: pytest.fail("registered without its internals"))
    config = SimpleNamespace(pluginmanager=manager,
                             hook=SimpleNamespace(pytest_timeout_set_timer=object()))
    with pytest.raises(pytest.UsageError, match="timeout_timer"):
        backstop.pytest_configure(config)


def test_the_backstop_is_registered_exactly_where_pytest_timeout_is(pytestconfig):
    # Keyed on the plugin's hooks, not its entry-point name, so a plugin loaded
    # by module (`-p pytest_timeout`) still gets the backstop.
    assert pytestconfig.pluginmanager.hasplugin(backstop.PLUGIN_NAME) == (
        backstop.timeout_hooks_present(pytestconfig))


def test_tests_run_on_the_main_thread():
    """pytest-timeout uses its signal method only on the main thread and falls
    back to the thread method elsewhere, without a word. pytest-xdist runs
    every test on its worker's main thread from 3.6 (pyproject's floor); an
    older one, or any runner that moves tests off it, reds here instead of
    quietly bringing back the whole-run kill."""
    assert threading.current_thread() is threading.main_thread()


@_NEEDS_SIGALRM
def test_this_test_is_armed(request):
    """The live session's own tests carry a backstop. Reds if the method was
    forced to thread (a `--timeout-method` in PYTEST_ADDOPTS or a CI line), or
    another plugin's set-timer hook ran instead of this one."""
    assert backstop._BACKSTOP in request.node.stash


_CONFTEST = (
    "import sys\n"
    f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
    "from tests._timeout_backstop import pytest_configure  # noqa: F401\n"
)


def _drive(tmp_path: Path, body: str) -> tuple[subprocess.CompletedProcess, float]:
    # Without the plugin, `--timeout=1` is a usage error and there is no ceiling.
    pytest.importorskip("pytest_timeout")
    (tmp_path / "conftest.py").write_text(_CONFTEST, encoding="utf-8")
    (tmp_path / "test_probe.py").write_text(body, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    t0 = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout=1",
         "test_probe.py"],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=45,
    )
    return proc, time.monotonic() - t0


@_NEEDS_SIGALRM
def test_a_swallowed_ceiling_fails_its_test_by_name(tmp_path):
    proc, _ = _drive(tmp_path, (
        "import time\n\n"
        "def test_swallows():\n"
        "    try:\n        time.sleep(30)\n"
        "    except BaseException:\n        pass\n"
    ))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "test_swallows" in out and "Failed was caught" in out, out


@_NEEDS_SIGALRM
def test_a_test_that_blocks_again_after_the_ceiling_is_ended(tmp_path):
    proc, took = _drive(tmp_path, (
        "import time\n\n"
        "def test_blocks_again():\n"
        "    while True:\n"
        "        try:\n            time.sleep(30)\n"
        "        except BaseException:\n            pass\n"
    ))
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0 and "Timeout" in out, out
    assert "test_blocks_again" in out, "the backstop's exit did not name the test"
    assert took < 30, f"the child ran {took:.1f} s: the backstop (2 s here) never ended it"


@_NEEDS_SIGALRM
def test_a_teardown_that_blocks_after_a_surfaced_ceiling_is_ended(tmp_path):
    # The ceiling's Failed propagates out of the call, so pytest-timeout cancels
    # its own alarm; the fixture's teardown then blocks on the same stuck thing.
    proc, took = _drive(tmp_path, (
        "import time\nimport pytest\n\n"
        "@pytest.fixture\ndef stuck():\n    yield\n    time.sleep(30)\n\n"
        "def test_hangs(stuck):\n    time.sleep(30)\n"
    ))
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0 and "Timeout" in out, out
    assert took < 30, f"the child ran {took:.1f} s: the teardown was never bounded"
