"""The count of the selected tests that never ran (DEF-2020).

pytest-xdist replaces a crashed worker up to its restart cap, four per worker
by default. Past the cap the controller stops scheduling, and under ``-q``
xdist's line saying so never prints. ``tests/_never_ran.py`` counts what never
ran in a line ``-q`` keeps, just above the final counts. The first class drives
the plugin in a real pytest child at one xdist worker whose thread-method
ceiling ends each worker. The second drives the build report's went-down
line the same way (DEF-2021), under the suite conftest's own hooks with the
tree build stubbed. A child whose own controller crashed prints no summary,
so the rows that crash workers drive a child again where it did, and the
report and the line are written where pytest printed no summary (DEF-2025).
The rest pin the line, the plugin object, the way ``tests/conftest.py`` (the
conftest this suite runs under) registers it, and the live-tree guard's xdist
note, which blames a sibling worker only where one runs.
"""
from __future__ import annotations

import inspect
import os
import re
import subprocess
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import _never_ran

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFTEST = Path(__file__).resolve().parent / "conftest.py"

_PROBE_CONFTEST = (
    "import sys\n"
    f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
    "from tests._never_ran import pytest_configure  # noqa: F401\n"
)
_CAP_REASON = " (xdist stopped replacing crashed workers: its --max-worker-restart cap is 4)"
#: What the six-test run prints: five crashes (the first worker and its four
#: replacements, xdist's default cap at one worker), then one test never runs.
_AT_THE_CAP = "1 of 6 selected tests never ran" + _CAP_REASON
#: What the same run prints when its controller raised once its five workers
#: went down (:data:`_BUILD_AND_COUNT_CONFTEST` with its raise), driven: the raise comes in
#: the fifth worker's node-down, before xdist reports the test it crashed in.
_AT_THE_CAP_CRASHED = "2 of 6 selected tests never ran" + _CAP_REASON


def _drive(tmp_path: Path, body: str, *args: str, workers: tuple[str, ...] = ("-n", "1"),
           conftest_text: str = _PROBE_CONFTEST, extra_env: dict[str, str] | None = None) -> tuple[int, list[str]]:
    """One quiet pytest child in ``tmp_path``, at one xdist worker unless
    ``workers`` says otherwise, with only ``conftest_text`` loaded (the plugin,
    unless a row passes the build report's hooks). The environment's own pytest
    and xdist settings, the Actions flag and the build stub's switch are left
    out, so the command line and ``extra_env`` are the whole of the run."""
    pytest.importorskip("xdist")
    (tmp_path / "conftest.py").write_text(conftest_text, encoding="utf-8")
    (tmp_path / "test_probe.py").write_text(body, encoding="utf-8")
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTEST_ADDOPTS", "PYTEST_TIMEOUT", "GITHUB_ACTIONS", "PROBE_BUILD_DIES",
                        "PROBE_CONTROLLER_RAISES")
           and not k.startswith("PYTEST_XDIST_")}
    env.update(extra_env or {})
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *workers, *args,
         "test_probe.py"],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=45,
    )
    return proc.returncode, [line for line in (proc.stdout + proc.stderr).splitlines() if line.strip()]


class NestedControllerCrashed(UserWarning):
    """A child run that was no reading of what its row asserts -- its own
    controller crashed, ending it in pytest's internal error before the row's
    own signal -- and that the row drove again (DEF-2025). The run's summary
    counts these (``tests/conftest.py::report_nested_controller_crashes``)."""


#: At most this many child runs per row. A child whose controller's channel to
#: a dying worker raised inside execnet ends in pytest's internal error, which
#: prints no summary: CI cells from 2026-10-18 on (DEF-2025's struck row counts
#: them), never this box (12 of 12 runs complete). The signal is the exit code,
#: never the shape execnet prints.
_ATTEMPTS = 3
#: The per-test ceiling of a row that may drive that many children, each under
#: :func:`_drive`'s 45 s bound, with room left for the kill and the teardown:
#: under the suite's 60 s the ceiling would end the row before its own failure
#: could say why (pinned against the attempts below). Not under the
#: windows-latest cell's raised 180 s either: a mark outranks that ceiling, so
#: one between the two would give these rows less room there than every
#: unmarked test (``tests/test_ci_job_bounds.py``'s slow-host pin).
_CHILDREN_CEILING_S = 180


def _completed(rc: int, lines: list[str]) -> bool:
    """A child that printed its summary: it did not end in pytest's internal error."""
    return rc != pytest.ExitCode.INTERNAL_ERROR


#: What pytest writes before each line of its internal error.
_INTERNAL_ERROR = "INTERNALERROR> "


def _what_raised(lines: list[str]) -> str:
    """The exception a child's internal error ended in, ``<Type>: <message>``,
    so a counted crash says what raised; "" where no line names one. pytest
    writes the error in the native traceback style (``Config.notify_exception``),
    whose last unindented line is the raise, and in the long style only under
    ``--fulltrace``, whose last ``E   `` line is; a progress mark can lead the
    first line (``FINTERNALERROR>``, read on a CI cell)."""
    said = [line.split(_INTERNAL_ERROR, 1)[1] for line in lines if _INTERNAL_ERROR in line]
    long_style = [text[1:].strip() for text in said if text.startswith("E ")]
    native = [text.strip() for text in said
              if text.strip() and not text[0].isspace() and not text.startswith("Traceback (")]
    named = long_style or native
    return named[-1] if named else ""


def _drive_to_a_reading(tmp_path: Path, body: str, *args: str, reading=_completed,
                        **kwargs) -> tuple[int, list[str]]:
    """:func:`_drive`, again where the child was no reading of its row: the
    first run ``reading`` accepts (by default, one that did not end in pytest's
    internal error), each in its own directory. A run that was not is a warning
    in this run's warnings summary, its attempt, exit code and what raised
    named, so the retry never hides the race it absorbs; the summary counts
    them (DEF-2025's watch). Three such runs fail by name."""
    rc, lines = 0, []
    for attempt in range(1, _ATTEMPTS + 1):
        run = tmp_path / f"attempt-{attempt}"
        run.mkdir()
        rc, lines = _drive(run, body, *args, **kwargs)
        if reading(rc, lines):
            return rc, lines
        raised = _what_raised(lines)
        warnings.warn(NestedControllerCrashed(
            f"nested run {attempt} of {_ATTEMPTS} was no reading: exit code {int(rc)}"
            + (f", {raised}" if raised else "") + "; driven again (DEF-2025)"), stacklevel=2)
    raised = _what_raised(lines)
    pytest.fail(f"all {_ATTEMPTS} nested runs were no reading of the row (the last: exit code {int(rc)}"
                + (f", {raised}" if raised else "") + f"); its lines: {lines}", pytrace=False)


class TestARealQuietRunSaysWhatNeverRan:
    @pytest.mark.timeout(_CHILDREN_CEILING_S)
    def test_past_the_restart_cap_the_count_and_the_cap_sit_above_the_final_counts(self, tmp_path):
        """Each test outlasts a one-second thread-method ceiling, which ends its
        worker; xdist names the test and replaces the worker four times, then
        stops. Without the plugin the summary is ``5 failed`` and nothing more.
        The line follows the short test summary, whose ``FAILED`` lines grow
        with every crash, so a reader of the run's last lines still has it."""
        pytest.importorskip("pytest_timeout")
        body = "import time\n" + "".join(
            f"\n\ndef test_slow_{i}():\n    time.sleep(10)\n" for i in range(6))
        rc, lines = _drive_to_a_reading(tmp_path, body, "--timeout=1", "--timeout-method=thread")
        assert rc == 1, lines
        assert lines.count(_AT_THE_CAP) == 1, lines
        at = lines.index(_AT_THE_CAP)
        assert lines[at + 1].startswith("5 failed"), lines
        assert any("short test summary info" in line for line in lines[:at]), lines

    def test_a_run_where_every_test_ran_prints_no_count(self, tmp_path):
        rc, lines = _drive(tmp_path, "".join(f"def test_ok_{i}():\n    pass\n\n" for i in range(3)))
        assert rc == 0, lines
        assert not [line for line in lines if "never ran" in line], lines

    def test_a_run_stopped_by_exitfirst_gets_the_count_and_no_reason(self, tmp_path):
        """pytest names the ``-x`` stop itself; the line adds only the count."""
        rc, lines = _drive(tmp_path, "def test_a():\n    assert 0\n\ndef test_b():\n    pass\n\n"
                                     "def test_c():\n    pass\n", "-x")
        assert rc != 0, lines
        assert "2 of 3 selected tests never ran" in lines, lines

    @pytest.mark.timeout(_CHILDREN_CEILING_S)
    def test_a_crash_past_the_cap_before_any_worker_collected_is_said(self, tmp_path):
        """Each worker dies importing the test module, so none reports a
        collection: the run selected nothing it knows of, and the cap is why."""
        rc, lines = _drive_to_a_reading(tmp_path, "import os\n\nif os.environ.get('PYTEST_XDIST_WORKER'):\n"
                                                  "    os._exit(3)\n\n\ndef test_a():\n    pass\n")
        assert rc != 0, lines
        assert "no worker finished collecting" + _CAP_REASON in lines, lines

    def test_a_green_run_with_xdist_installed_but_not_loaded_stays_green(self, tmp_path):
        """``-p no:xdist`` leaves xdist importable and its options unregistered."""
        rc, lines = _drive(tmp_path, "".join(f"def test_ok_{i}():\n    pass\n\n" for i in range(3)),
                           workers=("-p", "no:xdist"))
        assert rc == 0, lines
        assert lines[-1].startswith("3 passed"), lines
        assert not [line for line in lines if "never" in line or "Error" in line], lines

    def test_an_option_that_runs_no_test_owes_no_count(self, tmp_path):
        rc, lines = _drive(tmp_path, "def test_a():\n    pass\n", "--fixtures-per-test")
        assert rc == 0, lines
        assert not [line for line in lines if "never ran" in line], lines


#: The suite conftest's hooks the build report's child runs load: the build, and
#: every read the controller makes for the report. The child runs them, never a
#: copy.
_SUITE_HOOKS = ("pytest_collection_finish", "pytest_runtest_logreport", "pytest_testnodedown",
                "pytest_terminal_summary", "pytest_xdist_node_collection_finished", "pytest_sessionfinish")
#: Their conftest: the suite's hooks, with the build stubbed where the hook reads
#: it, so the real tree is never built here. The stub returns at once, or ends
#: the xdist worker inside the build where ``PROBE_BUILD_DIES`` is set.
_BUILD_CONFTEST = (
    "import os\n"
    "import sys\n"
    "\n"
    "import pytest\n"
    "\n"
    f"sys.path[:0] = [{str(REPO_ROOT)!r}, {str(REPO_ROOT / 'tests')!r}]\n"
    "import tests.conftest as suite  # noqa: E402\n"
    "\n"
    f"for _name in {_SUITE_HOOKS!r}:\n"
    "    if hasattr(suite, _name):  # one the conftest lacks is left out, and a row reds\n"
    "        globals()[_name] = getattr(suite, _name)\n"
    "\n"
    "\n"
    "def _build(factory, timeout=None):\n"
    "    if os.environ.get('PROBE_BUILD_DIES') and os.environ.get('PYTEST_XDIST_WORKER'):\n"
    "        os._exit(3)\n"
    "    return factory.mktemp('tree')\n"
    "\n"
    "\n"
    "_reads = suite.pytest_collection_finish.__globals__\n"
    "assert '_build_initialized_repo' in _reads, 'the build moved: stub it where the hook reads it'\n"
    "_reads['_build_initialized_repo'] = _build\n"
    "\n"
    "\n"
    "@pytest.fixture(name='initialized_repo_root')\n"
    "def _tree():\n"
    "    return None\n"
)
#: The same, with a controller that raises inside a hook once its five workers
#: went down: pytest's internal error on demand, the end the runners' execnet
#: race reaches by chance (DEF-2025), where ``PROBE_CONTROLLER_RAISES`` is set.
#: The never-ran plugin rides along either way, as the suite's own conftest
#: registers it.
_BUILD_AND_COUNT_CONFTEST = _BUILD_CONFTEST + (
    "\n\n"
    "class _ControllerRaises:\n"
    "    @pytest.hookimpl(trylast=True)\n"
    "    def pytest_testnodedown(self, node, error):\n"
    "        if len(node.config.__dict__.get('_initialized_repo_build_reports', [])) >= 5:\n"
    "            raise RuntimeError('probe: the controller raises once its workers went down')\n"
    "\n\n"
    "def pytest_configure(config):\n"
    "    from tests import _never_ran\n"
    "    _never_ran.pytest_configure(config)\n"
    "    if os.environ.get('PROBE_CONTROLLER_RAISES') and not hasattr(config, 'workerinput'):\n"
    "        config.pluginmanager.register(_ControllerRaises(), 'probe-controller-raises')\n"
)
#: The probe's own raise: the signal that a child of the crashed-controller rows
#: ended where the probe ended it, not earlier in the runners' race.
_PROBE_RAISE = "probe: the controller raises once its workers went down"
_HEADER = "initialized_repo_root build, before the first test:"
_WENT_DOWN = "went down after collecting, before its first test report: in its build, or in that test's setup"


#: The control's report: the first worker and its four replacements, each named.
_NAMED_EACH_TIME = [_HEADER] + [f"  xdist worker gw{i} FAILED: {_WENT_DOWN}" for i in range(5)]


def _build_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if line == _HEADER or _WENT_DOWN in line]


class TestACrashedWorkerIsNamedOnlyWhereItsBuildCanBe:
    """DEF-2021: a worker's build report rides xdist's ``workeroutput``, which a
    crash loses, so the controller printed a went-down line for every crashed
    worker, whether its build failed, finished or never began. In real child
    runs under the suite conftest's own hooks, the line is printed only for a
    worker that finished collecting and sent no test report: where its build
    runs, or its first test's setup, which the controller cannot tell apart."""

    @pytest.mark.timeout(_CHILDREN_CEILING_S)
    def test_a_ceiling_crossing_after_a_passing_test_names_no_build(self, tmp_path):
        """The row's pin: the worker reported a test, so its build was over."""
        pytest.importorskip("pytest_timeout")
        body = ("import time\n\n\ndef test_a_passes():\n    pass\n\n\n"
                "def test_b_crosses():\n    time.sleep(10)\n")
        rc, lines = _drive_to_a_reading(tmp_path, body, "--timeout=1", "--timeout-method=thread",
                                        conftest_text=_BUILD_CONFTEST)
        assert rc == 1, lines
        assert any("test_b_crosses" in line for line in lines), lines
        assert _build_lines(lines) == [], lines

    @pytest.mark.timeout(_CHILDREN_CEILING_S)
    def test_every_test_crossing_to_the_restart_cap_names_no_build(self, tmp_path):
        """The row's drive: no test asks for the tree, and each worker sends its
        crossing test's setup report before the ceiling ends it."""
        pytest.importorskip("pytest_timeout")
        body = "import time\n" + "".join(f"\n\ndef test_slow_{i}():\n    time.sleep(10)\n" for i in range(6))
        rc, lines = _drive_to_a_reading(tmp_path, body, "--timeout=1", "--timeout-method=thread",
                                        conftest_text=_BUILD_CONFTEST)
        assert rc == 1, lines
        assert any(line.startswith("5 failed") for line in lines), lines
        assert _build_lines(lines) == [], lines

    @pytest.mark.timeout(_CHILDREN_CEILING_S)
    def test_a_worker_that_dies_collecting_names_no_build(self, tmp_path):
        """Each worker dies importing the test module: none reached a build."""
        body = ("import os\n\nif os.environ.get('PYTEST_XDIST_WORKER'):\n    os._exit(3)\n\n\n"
                "def test_a():\n    pass\n")
        rc, lines = _drive_to_a_reading(tmp_path, body, conftest_text=_BUILD_CONFTEST)
        assert rc != 0, lines
        assert _build_lines(lines) == [], lines

    @pytest.mark.timeout(_CHILDREN_CEILING_S)
    def test_a_worker_that_dies_in_its_build_is_named_each_time(self, tmp_path):
        """The control: every worker, the first and its four replacements, dies
        inside the build, after xdist heard it finish collecting."""
        body = "".join(f"def test_{i}(initialized_repo_root):\n    pass\n\n\n" for i in range(6))
        rc, lines = _drive_to_a_reading(tmp_path, body, conftest_text=_BUILD_CONFTEST,
                                        extra_env={"PROBE_BUILD_DIES": "1"})
        assert rc != 0, lines
        assert _build_lines(lines) == _NAMED_EACH_TIME, lines

    @pytest.mark.timeout(_CHILDREN_CEILING_S)
    def test_a_first_test_whose_setup_crosses_the_ceiling_is_named_as_either(self, tmp_path):
        """No test asks for the tree; the first test's fixture crosses the
        ceiling before any report is sent. From the controller that is the
        build's place, so the line names both and claims neither."""
        pytest.importorskip("pytest_timeout")
        body = ("import time\n\nimport pytest\n\n\n@pytest.fixture\ndef slow():\n    time.sleep(10)\n\n\n"
                "def test_a(slow):\n    pass\n")
        rc, lines = _drive_to_a_reading(tmp_path, body, "--timeout=1", "--timeout-method=thread",
                                        conftest_text=_BUILD_CONFTEST)
        assert rc == 1, lines
        assert _build_lines(lines) == [_HEADER, f"  xdist worker gw0 FAILED: {_WENT_DOWN}"], lines

    def test_the_child_loads_every_hook_it_names(self, conftest):
        """The child leaves out a hook the conftest lacks, so that a run on the
        unfixed conftest reds on what it prints; here the list is held whole."""
        assert [name for name in _SUITE_HOOKS if not hasattr(conftest, name)] == []


#: Six tests that each take the tree, so every worker builds it.
_SIX_IN_THE_BUILD = "".join(f"def test_{i}(initialized_repo_root):\n    pass\n\n\n" for i in range(6))


@pytest.fixture(scope="module")
def crashed(tmp_path_factory):
    """One child whose controller raised once its five workers went down,
    driven again until the probe's own raise is what ended it; a module
    fixture, not a class-scoped method, which pytest 9 deprecates."""
    return _drive_to_a_reading(
        tmp_path_factory.mktemp("crashed"), _SIX_IN_THE_BUILD, conftest_text=_BUILD_AND_COUNT_CONFTEST,
        extra_env={"PROBE_BUILD_DIES": "1", "PROBE_CONTROLLER_RAISES": "1"},
        reading=lambda rc, lines: _what_raised(lines) == f"RuntimeError: {_PROBE_RAISE}")


class TestACrashedControllerStillPrintsWhatItSaw:
    """DEF-2025: pytest prints no terminal summary for a run that ends in its
    internal error, and that is how a controller ends whose channel to a dying
    worker raised inside execnet: CI cells on 2026-10-18 lost the build report
    that way (the struck row counts them), and the control row read nothing. The parser was never
    the fault. The report and the never-ran line are written at the session's
    finish where no summary ran, once. The child here makes its controller
    raise inside a hook once its five workers went down, the internal error on
    demand; the runners' own race never showed on this box. One child serves
    the class, driven again while the probe's own raise is not what ended it:
    the race can end it earlier, and that run is no reading here."""

    _BODY = _SIX_IN_THE_BUILD

    @pytest.mark.timeout(_CHILDREN_CEILING_S)
    def test_the_child_ends_in_the_internal_error(self, crashed):
        rc, lines = crashed
        assert rc == pytest.ExitCode.INTERNAL_ERROR, lines

    @pytest.mark.timeout(_CHILDREN_CEILING_S)
    def test_the_raise_a_real_internal_error_names_is_read(self, crashed):
        """The reader against pytest's own internal error, not a written one:
        the probe's raise, and its source line is no reading of it."""
        rc, lines = crashed
        assert _what_raised(lines) == f"RuntimeError: {_PROBE_RAISE}", lines
        assert any(line.startswith(_INTERNAL_ERROR + "Traceback (") for line in lines), lines

    @pytest.mark.timeout(_CHILDREN_CEILING_S)
    def test_the_build_report_is_written_where_no_summary_ran(self, crashed):
        rc, lines = crashed
        assert _build_lines(lines) == _NAMED_EACH_TIME, lines

    @pytest.mark.timeout(_CHILDREN_CEILING_S)
    def test_the_never_ran_line_is_written_where_no_summary_ran(self, crashed):
        rc, lines = crashed
        assert [line for line in lines if "never ran" in line] == [_AT_THE_CAP_CRASHED], lines

    @pytest.mark.timeout(_CHILDREN_CEILING_S)
    def test_no_summary_asked_for_none_and_gets_none(self, tmp_path):
        """``--no-summary``: pytest prints none, and the finish writes neither
        the report nor the line in its place."""
        rc, lines = _drive_to_a_reading(tmp_path, self._BODY, "--no-summary", conftest_text=_BUILD_AND_COUNT_CONFTEST,
                                        extra_env={"PROBE_BUILD_DIES": "1"})
        assert rc == 1, lines
        assert _build_lines(lines) == [] and not [line for line in lines if "never ran" in line], lines


def _suite_finish(conftest, warned, *, summary_ran: bool) -> list[str]:
    """Run the suite conftest's session-finish wrapper around a terminal
    reporter that did, or did not, print its summary inside it, with one crashed
    worker's report recorded and ``warned`` among the run's warnings; what the
    finish wrote."""
    lines: list[str] = []
    reporter = SimpleNamespace(write_line=lines.append, stats={"warnings": warned}, no_summary=False)
    config = SimpleNamespace(
        pluginmanager=SimpleNamespace(get_plugin={"terminalreporter": reporter}.get),
        getini=lambda name: "60", getoption=lambda name, default=None: None,
        _initialized_repo_build_reports=[{"place": "xdist worker gw0", "seconds": 0.0, "steps": [],
                                          "failure": _WENT_DOWN}])
    if summary_ran:
        config.__dict__["_initialized_repo_summary_ran"] = True
    wrapper = conftest.pytest_sessionfinish(SimpleNamespace(config=config), pytest.ExitCode.INTERNAL_ERROR)
    next(wrapper)
    with pytest.raises(StopIteration):
        wrapper.send(None)
    return lines


class TestTheFinishWritesWhatTheSummaryWould:
    """DEF-2025: where pytest printed no summary, the suite conftest's finish
    writes every line the summary would have -- the build report and the
    counted retries alike (failure-mode review: the report alone left the
    counts out) -- once, and names its own failure rather than raise."""

    _WARNED = [SimpleNamespace(nodeid="tests/test_a.py::one", message="tests/test_a.py:9: HookSpawnRetried: x"),
               SimpleNamespace(nodeid="tests/test_b.py::two", message="tests/test_b.py:3: NestedControllerCrashed: y")]

    def test_where_no_summary_ran_every_line_is_written(self, conftest, monkeypatch):
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.delenv("PYTEST_TIMEOUT", raising=False)
        lines = _suite_finish(conftest, self._WARNED, summary_ran=False)
        assert lines == [_HEADER, f"  xdist worker gw0 FAILED: {_WENT_DOWN}",
                         "hook spawn retries: 1 row(s) missed once and answered on the retry:", "  tests/test_a.py::one",
                         "nested controller crashes: 1 child run(s) in 1 row(s) were driven again (DEF-2025):",
                         "  tests/test_b.py::two"], lines

    def test_where_the_summary_ran_nothing_more_is_written(self, conftest, monkeypatch):
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        assert _suite_finish(conftest, self._WARNED, summary_ran=True) == []

    def test_a_failure_in_the_finish_is_named_not_raised(self, conftest, monkeypatch):
        def broken(*args):
            raise RuntimeError("boom")

        monkeypatch.setitem(conftest.pytest_sessionfinish.__globals__, "_write_summary_lines", broken)
        assert _suite_finish(conftest, [], summary_ran=False) == [
            "the summary lines at the session's finish failed (RuntimeError: boom; tests/conftest.py)"]


class TestANestedRunWhoseControllerCrashedIsDrivenAgain:
    """DEF-2025: a child that ends in pytest's internal error printed no
    summary, so it is no reading of what a row asserts: the row drives the
    child again, at most three times, and asserts on the first run that
    completes. Each crashed run is a warning in this run's warnings summary,
    its attempt, exit code and what raised named, and the summary counts them
    (``tests/conftest.py::report_nested_controller_crashes``), so the retry
    never hides the race it absorbs: the row's watch counts those over the 30
    merges after its fix, never the reds the retry absorbed."""

    @staticmethod
    def _children(monkeypatch, results):
        calls: list[Path] = []

        def child(tmp_path, body, *args, **kwargs):
            calls.append(tmp_path)
            return results[len(calls) - 1]

        monkeypatch.setitem(globals(), "_drive", child)
        return calls

    @pytest.mark.parametrize("style", ["native", "long"])
    def test_the_raise_is_read_in_each_style_pytest_writes(self, style):
        """Native, pytest's own, or long under ``--fulltrace``, each line after
        the prefix and the first after a progress mark: the raise read is the
        last, never the one it was raised from."""
        def send():
            try:
                raise OSError("cannot send (already closed?)")
            except OSError as exc:
                raise RuntimeError("the channel went down") from exc

        with pytest.raises(RuntimeError) as info:
            send()
        written = str(info.getrepr(funcargs=True, showlocals=False, style=style)).split("\n")
        lines = [("F" if i == 0 else "") + _INTERNAL_ERROR + line for i, line in enumerate(written)]
        assert _what_raised(lines) == "RuntimeError: the channel went down", lines

    def test_a_crashed_child_is_driven_again_and_said(self, tmp_path, monkeypatch):
        crash = ["FINTERNALERROR> Traceback (most recent call last):",
                 'INTERNALERROR>   File "execnet/gateway_base.py", line 1, in _send',
                 "INTERNALERROR> OSError: cannot send"]
        calls = self._children(monkeypatch, [(3, crash), (1, ["5 failed"])])
        with pytest.warns(NestedControllerCrashed,
                          match=r"nested run 1 of 3 was no reading: exit code 3, OSError: cannot send"):
            assert _drive_to_a_reading(tmp_path, "body") == (1, ["5 failed"])
        assert len(calls) == 2 and calls[0] != calls[1], calls

    def test_a_row_names_its_own_reading(self, tmp_path, monkeypatch):
        """The crashed-controller rows expect the internal error: their reading
        is the probe's own raise, and a run the race ended first is driven again."""
        calls = self._children(monkeypatch, [(3, ["INTERNALERROR> E   OSError: x"]), (3, [_PROBE_RAISE])])
        with pytest.warns(NestedControllerCrashed, match=r"nested run 1 of 3 was no reading: exit code 3, OSError"):
            rc, lines = _drive_to_a_reading(tmp_path, "body", reading=lambda rc, lines: _PROBE_RAISE in lines)
        assert (rc, lines, len(calls)) == (3, [_PROBE_RAISE], 2)

    def test_the_ceiling_holds_every_child_the_rows_may_drive(self):
        """Three children at :func:`_drive`'s 45 s bound, with room for the
        kill and the teardown, under the routed rows' own ceiling."""
        bound = re.search(r"timeout=(\d+),", inspect.getsource(_drive))
        assert bound, "the child's bound moved: re-read where it is set"
        assert _ATTEMPTS * int(bound.group(1)) <= _CHILDREN_CEILING_S - 10, (_ATTEMPTS, bound.group(1))

    def test_a_child_that_completes_is_read_at_once_and_unsaid(self, tmp_path, monkeypatch):
        calls = self._children(monkeypatch, [(1, ["5 failed"])])
        with warnings.catch_warnings():
            warnings.simplefilter("error", NestedControllerCrashed)
            assert _drive_to_a_reading(tmp_path, "body") == (1, ["5 failed"])
        assert len(calls) == 1, calls

    def test_three_crashed_children_fail_by_name(self, tmp_path, monkeypatch):
        calls = self._children(monkeypatch, [(3, ["INTERNALERROR> boom"])] * _ATTEMPTS)
        with pytest.warns(NestedControllerCrashed) as said, \
                pytest.raises(pytest.fail.Exception, match=r"all 3 nested runs were no reading of the row"):
            _drive_to_a_reading(tmp_path, "body")
        assert len(calls) == _ATTEMPTS and len(said) == _ATTEMPTS, (calls, [str(w.message) for w in said])

    def test_the_run_summary_counts_the_crashed_children(self, monkeypatch):
        """Each crashed child counted, its rows named once; other warnings left
        out; under GitHub Actions an annotation as well, the count DEF-2025's
        watch reads."""
        from tests.conftest import report_nested_controller_crashes

        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        said = "tests/test_x.py:9: NestedControllerCrashed: nested run {} of 3 was no reading: exit code 3"
        lines: list[str] = []
        reporter = SimpleNamespace(write_line=lines.append, stats={"warnings": [
            SimpleNamespace(nodeid="tests/test_x.py::T::one", message=said.format(1)),
            SimpleNamespace(nodeid="tests/test_x.py::T::one", message=said.format(2)),
            SimpleNamespace(nodeid="tests/test_y.py::two", message="tests/test_y.py:3: PytestRemovedIn10Warning: ..."),
        ]})
        report_nested_controller_crashes(reporter)
        head = "nested controller crashes: 2 child run(s) in 1 row(s) were driven again (DEF-2025)"
        assert lines == [head + ":", "  tests/test_x.py::T::one", f"::warning::{head}: tests/test_x.py::T::one"]
        quiet: list[str] = []
        report_nested_controller_crashes(SimpleNamespace(write_line=quiet.append, stats={"warnings": []}))
        assert quiet == []


class TestTheLine:
    @pytest.mark.parametrize(("selected", "ran", "crashes", "cap", "line"), [
        pytest.param(6, 5, 5, 4, _AT_THE_CAP, id="past-the-cap"),
        pytest.param(6, 5, 4, 4, "1 of 6 selected tests never ran", id="at-the-cap-xdist-goes-on"),
        pytest.param(3, 1, 0, None, "2 of 3 selected tests never ran", id="no-xdist"),
        pytest.param(5, 5, 5, 4, None, id="every-test-ran"),
        pytest.param(0, 0, 0, None, None, id="nothing-selected"),
        pytest.param(0, 0, 5, 4, "no worker finished collecting" + _CAP_REASON, id="crashed-before-collecting"),
        pytest.param(0, 0, 3, 4, None, id="crashed-before-collecting-under-the-cap"),
    ])
    def test_the_count_and_the_reason(self, selected, ran, crashes, cap, line):
        assert _never_ran.count_line(selected, ran, crashes, cap) == line


def _reports(*nodeids: str) -> list:
    return [pytest.TestReport(nodeid=nodeid, location=("test_probe.py", 0, nodeid), keywords={},
                              outcome="failed", longrepr=None, when=when)
            for nodeid in nodeids for when in ("setup", "call")]


def _summarise(plugin, stats, **options) -> list[str]:
    """Run the plugin's terminal-summary wrapper around nothing, at one xdist
    worker with xdist's default cap; what it wrote."""
    lines: list[str] = []
    reporter = SimpleNamespace(write_line=lines.append, stats=stats)
    config = SimpleNamespace(option=SimpleNamespace(maxworkerrestart=None, numprocesses=1, **options))
    wrapper = plugin.pytest_terminal_summary(reporter, config)
    next(wrapper)
    with pytest.raises(StopIteration):
        wrapper.send(None)
    return lines


def _finish(plugin, stats, *, summarised: bool, selected: int = 6) -> list[str]:
    """Run the plugin's session-finish wrapper around a terminal reporter that
    did, or did not, print its summary inside it; what the finish wrote."""
    lines: list[str] = []
    reporter = SimpleNamespace(write_line=lines.append, stats=stats, no_summary=False)
    config = SimpleNamespace(option=SimpleNamespace(maxworkerrestart=None, numprocesses=1),
                             pluginmanager=SimpleNamespace(get_plugin={"terminalreporter": reporter}.get))
    wrapper = plugin.pytest_sessionfinish(SimpleNamespace(testscollected=selected, config=config))
    next(wrapper)
    plugin.summarised = summarised
    with pytest.raises(StopIteration):
        wrapper.send(None)
    return lines


class TestThePluginObject:
    def test_it_records_the_selected_count_and_the_crashes(self):
        plugin = _never_ran.NeverRan()
        next(plugin.pytest_sessionfinish(SimpleNamespace(testscollected=6)))
        plugin.pytest_testnodedown(SimpleNamespace(), "crashed")
        plugin.pytest_testnodedown(SimpleNamespace(), None)   # a worker that finished
        assert (plugin.selected, plugin.crashes) == (6, 1)

    def test_it_counts_tests_not_reports(self, monkeypatch):
        """Each test has a report per phase; two tests reported, three selected."""
        pytest.importorskip("xdist")
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        plugin = _never_ran.NeverRan()
        plugin.selected, plugin.crashes = 3, 0
        stats = {"failed": _reports("t::a", "t::b"), "warnings": [SimpleNamespace(nodeid="t::c")]}
        assert _summarise(plugin, stats) == ["1 of 3 selected tests never ran"]

    def test_under_github_actions_the_line_is_an_annotation_too(self, monkeypatch):
        pytest.importorskip("xdist")
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        plugin = _never_ran.NeverRan()
        plugin.selected, plugin.crashes = 6, 5
        stats = {"failed": _reports(*(f"t::{i}" for i in range(5)))}
        assert _summarise(plugin, stats) == [_AT_THE_CAP, f"::warning::{_AT_THE_CAP}"]

    @pytest.mark.parametrize("option", _never_ran.NO_TEST_RUNS)
    def test_no_count_is_owed_under_an_option_that_runs_no_test(self, option):
        plugin = _never_ran.NeverRan()
        plugin.selected = 6
        assert _summarise(plugin, {}, **{option: True}) == []

    def test_a_failure_inside_the_count_is_named_not_raised(self, monkeypatch):
        """A summary aid: the run keeps its summary and its exit code."""
        def broken(*args):
            raise RuntimeError("boom")

        monkeypatch.setattr(_never_ran, "count_line", broken)
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)   # the CI cells set it: no annotation here
        plugin = _never_ran.NeverRan()
        plugin.selected = 6
        assert _summarise(plugin, {}) == ["the never-ran count failed (RuntimeError: boom; tests/_never_ran.py)"]

    def test_where_no_summary_ran_the_finish_writes_the_line(self, monkeypatch):
        """DEF-2025: pytest's internal error prints no summary; the line is the
        crash run's, so the session's finish writes it."""
        pytest.importorskip("xdist")
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        plugin = _never_ran.NeverRan()
        plugin.crashes = 5
        stats = {"failed": _reports(*(f"t::{i}" for i in range(5)))}
        assert _finish(plugin, stats, summarised=False) == [_AT_THE_CAP]

    def test_where_the_summary_ran_the_finish_writes_nothing_more(self, monkeypatch):
        """Once: the summary wrote the line and marked that it ran."""
        pytest.importorskip("xdist")
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        plugin = _never_ran.NeverRan()
        plugin.crashes = 5
        stats = {"failed": _reports(*(f"t::{i}" for i in range(5)))}
        assert _finish(plugin, stats, summarised=True) == []


def _manager(registered: list):
    return SimpleNamespace(hasplugin=lambda name: any(n == name for _p, n in registered),
                           register=lambda plugin, name: registered.append((plugin, name)))


@pytest.fixture
def conftest(request):
    """The conftest module pytest itself loaded (an ``import tests.conftest``
    can be a second copy)."""
    (module,) = [plugin for plugin in request.config.pluginmanager.get_plugins()
                 if getattr(plugin, "__file__", None) and Path(plugin.__file__).resolve() == CONFTEST]
    return module


class TestTheSuitesConftestRegistersIt:
    def test_its_configure_registers_the_plugin_once(self, conftest):
        """A stub config without pytest-timeout's hooks, so the backstop
        stands down and only this plugin registers."""
        registered: list = []
        config = SimpleNamespace(pluginmanager=_manager(registered), hook=SimpleNamespace())
        conftest.pytest_configure(config)
        conftest.pytest_configure(config)
        assert [(type(plugin), name) for plugin, name in registered] == [
            (_never_ran.NeverRan, _never_ran.PLUGIN_NAME)]

    def test_an_xdist_worker_registers_none(self, conftest):
        registered: list = []
        config = SimpleNamespace(pluginmanager=_manager(registered), hook=SimpleNamespace(), workerinput={})
        conftest.pytest_configure(config)
        assert registered == []

    def test_this_session_has_it_unless_this_is_a_worker(self, pytestconfig):
        has = pytestconfig.pluginmanager.get_plugin(_never_ran.PLUGIN_NAME) is not None
        assert has != hasattr(pytestconfig, "workerinput")


_SIBLING = "a sibling worker can move these entries"
_OUTSIDE = "or a gate run on this checkout from outside it while the tier ran"


class TestTheLiveTreeGuardsXdistNote:
    @pytest.fixture
    def note(self, conftest, monkeypatch):
        def read(workers: str | None) -> str:
            monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
            if workers is None:
                monkeypatch.delenv("PYTEST_XDIST_WORKER_COUNT", raising=False)
            else:
                monkeypatch.setenv("PYTEST_XDIST_WORKER_COUNT", workers)
            return conftest._live_tree_xdist_note()
        return read

    def test_a_plain_run_gets_no_note(self, conftest, monkeypatch):
        monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
        assert conftest._live_tree_xdist_note() == ""

    def test_at_one_worker_no_sibling_is_blamed_but_an_outside_writer_still_is(self, note):
        """The full tier's serial leg and the host check's suite step."""
        text = note("1")
        assert "AT ONE WORKER: no sibling worker ran beside this test" in text
        assert _SIBLING not in text and _OUTSIDE in text

    def test_beside_sibling_workers_both_writers_are_named_with_the_count(self, note):
        text = note("4")
        assert "(4 workers): " + _SIBLING in text and _OUTSIDE in text

    @pytest.mark.parametrize("workers", [None, "", "auto"])
    def test_a_count_xdist_did_not_set_is_read_as_siblings_that_may_exist(self, note, workers):
        assert "(an unread number of workers): " + _SIBLING in note(workers)
