"""The count of the selected tests that never ran (DEF-2020).

pytest-xdist replaces a crashed worker up to its restart cap, four per worker
by default. Past the cap the controller stops scheduling, and under ``-q``
xdist's line saying so never prints. ``tests/_never_ran.py`` counts what never
ran in a line ``-q`` keeps, just above the final counts. The first class drives
the plugin in a real pytest child at one xdist worker whose thread-method
ceiling ends each worker. The rest pin the line, the plugin object, the way
``tests/conftest.py`` (the conftest this suite runs under) registers it, and
the live-tree guard's xdist note, which blames a sibling worker only where one
runs.
"""
from __future__ import annotations

import os
import subprocess
import sys
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


def _drive(tmp_path: Path, body: str, *args: str, workers: tuple[str, ...] = ("-n", "1")) -> tuple[int, list[str]]:
    """One quiet pytest child in ``tmp_path``, at one xdist worker unless
    ``workers`` says otherwise, with only the plugin loaded. The environment's
    own pytest and xdist settings and the Actions flag are left out, so the
    command line is the whole of the run."""
    pytest.importorskip("xdist")
    (tmp_path / "conftest.py").write_text(_PROBE_CONFTEST, encoding="utf-8")
    (tmp_path / "test_probe.py").write_text(body, encoding="utf-8")
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTEST_ADDOPTS", "PYTEST_TIMEOUT", "GITHUB_ACTIONS")
           and not k.startswith("PYTEST_XDIST_")}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *workers, *args,
         "test_probe.py"],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=45,
    )
    return proc.returncode, [line for line in (proc.stdout + proc.stderr).splitlines() if line.strip()]


class TestARealQuietRunSaysWhatNeverRan:
    def test_past_the_restart_cap_the_count_and_the_cap_sit_above_the_final_counts(self, tmp_path):
        """Each test outlasts a one-second thread-method ceiling, which ends its
        worker; xdist names the test and replaces the worker four times, then
        stops. Without the plugin the summary is ``5 failed`` and nothing more.
        The line follows the short test summary, whose ``FAILED`` lines grow
        with every crash, so a reader of the run's last lines still has it."""
        pytest.importorskip("pytest_timeout")
        body = "import time\n" + "".join(
            f"\n\ndef test_slow_{i}():\n    time.sleep(10)\n" for i in range(6))
        rc, lines = _drive(tmp_path, body, "--timeout=1", "--timeout-method=thread")
        assert rc == 1, lines
        assert _AT_THE_CAP in lines, lines
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

    def test_a_crash_past_the_cap_before_any_worker_collected_is_said(self, tmp_path):
        """Each worker dies importing the test module, so none reports a
        collection: the run selected nothing it knows of, and the cap is why."""
        rc, lines = _drive(tmp_path, "import os\n\nif os.environ.get('PYTEST_XDIST_WORKER'):\n"
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


class TestThePluginObject:
    def test_it_records_the_selected_count_and_the_crashes(self):
        plugin = _never_ran.NeverRan()
        plugin.pytest_sessionfinish(SimpleNamespace(testscollected=6))
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
        plugin = _never_ran.NeverRan()
        plugin.selected = 6
        assert _summarise(plugin, {}) == ["the never-ran count failed (RuntimeError: boom; tests/_never_ran.py)"]


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
