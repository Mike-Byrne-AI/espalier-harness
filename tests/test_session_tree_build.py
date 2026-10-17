"""The shared initialized tree is built before the first test, outside every
per-test ceiling, and a failed build is named in each test that asks for it.

Why this exists: ``initialized_repo_root`` was a session fixture built inside
whichever test requested it first, and pytest-timeout counts fixture setup
against that test's 60 s ceiling, so on the Windows runner the build alone took
over half of it and a slow run ended the whole session inside the fixture with
no test named (DEF-1177; run 38642037524 died exactly there on 2026-10-14).
``tests/conftest.py::pytest_collection_finish`` now builds it after collection.
These pin the hook's decisions -- build once, under its own spawn bound, when a
collected test asks; never where no test runs or none asks; record a failure
(naming the worker) rather than raise it; report every process's step times
at the end of the run and warn, without ever raising, on a spawn near its
bound; name a crashed xdist worker only where its build can be what it died
in (DEF-2021, driven in real child runs in tests/test_xdist_never_ran.py,
which spawns them where this module spawns none) -- and the fixture's
hand-off, including the refusal of a request the
hook could not see, without spending a real build. One test asks for the real
tree, so the hook pytest actually ran is held to it too (which is why this
module is ``integration``, not ``unit``: that test makes the hook build); the
others patch the conftest module pytest loaded, not a second import of it.
"""
from __future__ import annotations

import ast
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests._live_tree import checkout_glob

CONFTEST = Path(__file__).resolve().parent / "conftest.py"
#: The fixtures whose setup is the tree build.
def _tree_fixtures() -> set[str]:
    """Every conftest fixture whose setup is the tree build: the fixture itself
    and each one that asks for one of them, at any depth, read from conftest's
    own code (a registered ``name=`` included), never listed."""
    tree = ast.parse(CONFTEST.read_text(encoding="utf-8"))
    consts = {target.id: node.value.value for node in tree.body if isinstance(node, ast.Assign)
              and isinstance(node.value, ast.Constant) for target in node.targets if isinstance(target, ast.Name)}
    fixtures: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        decorators = [d for d in node.decorator_list if "fixture" in ast.unparse(d)]
        if not decorators:
            continue
        name = node.name
        for keyword in (kw for d in decorators if isinstance(d, ast.Call) for kw in d.keywords if kw.arg == "name"):
            value = keyword.value
            name = value.value if isinstance(value, ast.Constant) else consts.get(getattr(value, "id", ""), name)
        fixtures[name] = {a.arg for a in node.args.args + node.args.kwonlyargs}
    found = {"initialized_repo_root"}
    while more := {name for name, params in fixtures.items() if params & found} - found:
        found |= more
    return found


@pytest.fixture
def conftest(request):
    """The conftest module pytest itself loaded, whose globals the live hook
    reads (an ``import tests.conftest`` can be a second copy)."""
    (module,) = [plugin for plugin in request.config.pluginmanager.get_plugins()
                 if getattr(plugin, "__file__", None) and Path(plugin.__file__).resolve() == CONFTEST]
    return module


def _no_raised_ceiling(config):
    """A controller config stub at the suite's own 60 s ceiling, no --timeout."""
    config.getini = lambda name: "60"
    config.getoption = lambda name, default=None: None
    return config


@pytest.fixture
def quiet_ceiling(monkeypatch, conftest):
    """No raised ceiling from the environment (the windows-latest cell exports
    one) and no phase times from the real run, so a summary test reads only
    what it planted."""
    monkeypatch.delenv("PYTEST_TIMEOUT", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(conftest, "_PHASE_SECONDS", {})


def _session(*, asks: bool, worker: str | None = None, **options: bool):
    item = SimpleNamespace(fixturenames=["tmp_path", "initialized_repo_root"] if asks else ["tmp_path"])
    config = SimpleNamespace(option=SimpleNamespace(**{"collectonly": False, **options}), _tmp_path_factory=object())
    if worker:
        config.workerinput = {"workerid": worker}
        config.workeroutput = {}
    return SimpleNamespace(config=config, items=[item])


@pytest.fixture
def steps(monkeypatch, conftest):
    """A fresh step record, so a test's fake steps never overwrite the real
    build's in the live module."""
    fresh: list = []
    monkeypatch.setattr(conftest, "_BUILD_STEPS", fresh)
    return fresh


@pytest.fixture
def builds(monkeypatch, conftest, steps):
    calls: list[tuple[object, object]] = []

    def build(factory, timeout=None):
        calls.append((factory, timeout))
        return Path("tree")
    monkeypatch.setattr(conftest, "_build_initialized_repo", build)
    return calls


class TestTheHookBuildsBeforeTheFirstTest:
    def test_a_collected_requester_gets_the_tree_built_once_before_it_runs(self, conftest, builds):
        session = _session(asks=True)
        conftest.pytest_collection_finish(session)
        assert builds == [(session.config._tmp_path_factory, conftest._BUILD_HOOK_STEP_TIMEOUT_S)]
        assert session.config._initialized_repo_build == (Path("tree"), None)

    @pytest.mark.parametrize("option", ["collectonly", "showfixtures", "show_fixtures_per_test", "setupplan"])
    def test_nothing_is_built_where_no_test_runs(self, conftest, builds, option):
        session = _session(asks=True, **{option: True})
        conftest.pytest_collection_finish(session)
        assert builds == [] and not hasattr(session.config, "_initialized_repo_build")
        assert not hasattr(session.config, "_initialized_repo_hook_ran")

    def test_every_skip_option_is_one_pytest_still_defines(self, conftest, request):
        """A renamed option upstream would quietly build under ``--fixtures``."""
        assert [name for name in conftest._NO_TEST_RUNS if not hasattr(request.config.option, name)] == []

    def test_nothing_is_built_when_no_test_asks_but_the_hook_marks_it_ran(self, conftest, builds):
        session = _session(asks=False)
        conftest.pytest_collection_finish(session)
        assert builds == [] and not hasattr(session.config, "_initialized_repo_build")
        assert session.config._initialized_repo_hook_ran is True

    def test_a_failed_build_is_recorded_not_raised_and_names_the_worker(self, conftest, monkeypatch, steps):
        def fail(factory, timeout=None):
            raise RuntimeError("init timed out")
        monkeypatch.setattr(conftest, "_build_initialized_repo", fail)
        session = _session(asks=True, worker="gw3")
        conftest.pytest_collection_finish(session)
        tree, failure = session.config._initialized_repo_build
        assert tree is None and failure.startswith("RuntimeError: init timed out (on xdist worker gw3, after "), failure
        assert session.config.workeroutput["initialized_repo_build"]["failure"] == failure

    def test_the_build_runs_after_xdist_hears_the_worker_finish_collecting(self, conftest):
        """The went-down line is keyed on xdist's "collection finished", which
        its worker sends from its own ``pytest_collection_finish``; the build
        runs after it by the hook's own mark, not by the order the plugins
        registered in (DEF-2021). The control child run in
        tests/test_xdist_never_ran.py is the witness."""
        assert conftest.pytest_collection_finish.pytest_impl.get("trylast") is True

    def test_the_worker_is_read_from_xdist_not_the_environment(self, conftest, builds, monkeypatch):
        """A child pytest the suite spawns inherits PYTEST_XDIST_WORKER; it is
        not that worker."""
        monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw9")
        session = _session(asks=True)
        conftest.pytest_collection_finish(session)
        assert session.config._initialized_repo_build_report["place"] == "the pytest process"


@pytest.mark.usefixtures("quiet_ceiling")
class TestTheBuildIsReported:
    @staticmethod
    def _slow_build(conftest, secs):
        def build(factory, timeout=None):
            conftest._BUILD_STEPS.append(("copy", 9.0, None))
            conftest._BUILD_STEPS.append(("git add -A", secs, 50))
            return Path("tree")
        return build

    @pytest.mark.parametrize("secs,warned", [(30.0, True), (20.0, False)], ids=["past-half", "under-half"])
    def test_a_spawn_past_half_its_bound_is_warned_about(self, conftest, monkeypatch, steps, secs, warned):
        """The build runs before any test, so ``--durations`` never shows it:
        a spawn nearing its bound is said, or nobody sees the drift until the
        bound kills it. The copy has no bound and is never the near one."""
        monkeypatch.setattr(conftest, "_build_initialized_repo", self._slow_build(conftest, secs))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            conftest.pytest_collection_finish(_session(asks=True))
        said = [str(w.message) for w in caught if "neared its bound" in str(w.message)]
        assert bool(said) is warned, said
        if warned:
            assert "git add -A 30.0s of its 50s" in said[0] and "the pytest process" in said[0], said
            assert "copy" not in said[0], said

    def test_the_warning_never_raises_under_an_error_filter(self, conftest, monkeypatch, steps):
        """Under ``-W error`` an escaped warning would end the session at
        collection with no test named, DEF-1177's symptom, for a build that
        succeeded."""
        monkeypatch.setattr(conftest, "_build_initialized_repo", self._slow_build(conftest, 45.0))
        session = _session(asks=True)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("error")
            conftest.pytest_collection_finish(session)
        assert session.config._initialized_repo_build == (Path("tree"), None)
        assert any("neared its bound" in str(w.message) for w in caught), "reported, not raised"

    def test_a_worker_hands_its_steps_to_the_controller_which_prints_one_line_each(
            self, conftest, monkeypatch, steps):
        monkeypatch.setattr(conftest, "_build_initialized_repo", self._slow_build(conftest, 12.5))
        worker = _session(asks=True, worker="gw1")
        conftest.pytest_collection_finish(worker)
        report = worker.config.workeroutput["initialized_repo_build"]
        assert report["place"] == "xdist worker gw1" and report["failure"] is None
        assert report["steps"] == [["copy", 9.0, None], ["git add -A", 12.5, 50]]

        controller = SimpleNamespace()
        conftest.pytest_testnodedown(SimpleNamespace(workeroutput=worker.config.workeroutput, config=controller), None)
        conftest.pytest_testnodedown(SimpleNamespace(workeroutput={}, config=controller), None)   # built nothing
        lines: list[str] = []
        conftest.pytest_terminal_summary(SimpleNamespace(write_line=lines.append), 0, _no_raised_ceiling(controller))
        assert lines[0] == "initialized_repo_root build, before the first test:"
        assert lines[1:] == [f"  xdist worker gw1 {report['seconds']:.1f}s (copy 9.0s; git add -A 12.5s of 50s)"]

    def test_quick_steps_are_counted_not_listed(self, conftest):
        report = {"place": "the pytest process", "seconds": 20.0, "failure": None,
                  "steps": [["copy", 2.0, None], ["git init", 0.1, 120], ["git config gc.auto", 0.0, 120],
                            ["git add -A", 15.0, 120]]}
        assert conftest._build_report_line(report) == (
            "the pytest process 20.0s (copy 2.0s; git add -A 15.0s of 120s; 2 more under 0.5s)")

    @staticmethod
    def _went_down(conftest, *, collected: bool, reported: bool) -> list[str]:
        """The summary after worker gw5 went down with an error, having finished
        collecting or not and sent a test report or not."""
        controller = SimpleNamespace()
        node = SimpleNamespace(workeroutput=None, gateway=SimpleNamespace(id="gw5"), config=controller)
        if collected:
            conftest.pytest_xdist_node_collection_finished(node, ["t.py::test_a"])
        if reported:   # a teardown report: it reaches no phase sum
            conftest.pytest_runtest_logreport(
                SimpleNamespace(node=node, when="teardown", keywords={}, nodeid="t.py::test_a", duration=0.0))
        conftest.pytest_testnodedown(node, "crashed")
        lines: list[str] = []
        conftest.pytest_terminal_summary(SimpleNamespace(write_line=lines.append), 0, _no_raised_ceiling(controller))
        return lines

    def test_a_worker_that_went_down_where_its_build_runs_is_named_not_dropped(self, conftest):
        """xdist sends no output from a crashed worker; the builds made under the
        most contention are the ones that die, so their absence is said. A
        worker that finished collecting and sent no test report went down where
        its build runs."""
        lines = self._went_down(conftest, collected=True, reported=False)
        assert lines[1:] == ["  xdist worker gw5 FAILED: went down after collecting, before its first test "
                             "report: in its build, or in that test's setup"], lines

    @pytest.mark.parametrize("collected,reported", [(True, True), (False, False)],
                             ids=["after-its-first-test-report", "before-it-finished-collecting"])
    def test_a_worker_that_went_down_outside_its_build_is_not_named(self, conftest, collected, reported):
        """A test report means the build, which runs before the first test, was
        over; a worker that never finished collecting never reached it (DEF-2021).
        Either way the line would send a reader to a build that did not fail."""
        assert self._went_down(conftest, collected=collected, reported=reported) == []

    def test_a_run_that_built_nothing_prints_nothing(self, conftest):
        lines: list[str] = []
        conftest.pytest_terminal_summary(SimpleNamespace(write_line=lines.append), 0,
                                         _no_raised_ceiling(SimpleNamespace()))
        assert lines == []


@pytest.mark.usefixtures("quiet_ceiling")
class TestARaisedCeilingHidesNoSlowdown:
    """The windows-latest cell runs at PYTEST_TIMEOUT=180, so a test there that
    takes longer than the suite's 60 s passes; the run's summary names it."""

    def test_under_a_raised_ceiling_every_unmarked_test_past_the_suites_is_named(self, conftest, monkeypatch):
        monkeypatch.setenv("PYTEST_TIMEOUT", "180")
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setattr(conftest, "_PHASE_SECONDS", {"t::fast": 3.0, "t::slow": 75.5, "t::slower": 120.0})
        lines: list[str] = []
        conftest.pytest_terminal_summary(SimpleNamespace(write_line=lines.append), 0,
                                         _no_raised_ceiling(SimpleNamespace()))
        assert lines[0] == ("2 unmarked test(s) took longer than the suite's 60 s ceiling under this "
                            "run's 180 s, slowest first:"), lines
        assert lines[1:3] == ["  120.0s t::slower", "  75.5s t::slow"], lines
        assert lines[3].startswith("::warning::2 unmarked test(s)") and "t::slower 120s" in lines[3], lines

    def test_a_run_without_pytest_timeout_reads_no_ceiling_and_never_raises(self, conftest, monkeypatch):
        """pytest alone (the artifact-parity job) knows no ``timeout`` ini key and
        raises on the read; the summary hook would then end that run red after
        every test passed (run 38908556689)."""
        def unknown(name):
            raise ValueError(f"unknown configuration value: {name!r}")
        monkeypatch.setenv("PYTEST_TIMEOUT", "180")
        monkeypatch.setattr(conftest, "_PHASE_SECONDS", {"t::slow": 75.5})
        config = SimpleNamespace(getini=unknown, getoption=lambda name, default=None: default)
        lines: list[str] = []
        conftest.pytest_terminal_summary(SimpleNamespace(write_line=lines.append), 0, config)
        assert lines == [] and conftest._ceilings(config) == (0.0, 0.0)

    def test_at_the_suites_own_ceiling_nothing_is_listed(self, conftest, monkeypatch):
        monkeypatch.setattr(conftest, "_PHASE_SECONDS", {"t::slow": 75.5})
        lines: list[str] = []
        conftest.pytest_terminal_summary(SimpleNamespace(write_line=lines.append), 0,
                                         _no_raised_ceiling(SimpleNamespace()))
        assert lines == []

    def test_setup_and_call_are_summed_and_a_marked_test_is_left_out(self, conftest):
        for when, secs in (("setup", 30.0), ("call", 40.0), ("teardown", 99.0)):
            conftest.pytest_runtest_logreport(SimpleNamespace(when=when, keywords={}, nodeid="t::a", duration=secs))
        conftest.pytest_runtest_logreport(
            SimpleNamespace(when="call", keywords={"timeout": 1}, nodeid="t::m", duration=500.0))
        # The live hook also records this test's own setup; read only the planted ids.
        assert conftest._PHASE_SECONDS.get("t::a") == 70.0 and "t::m" not in conftest._PHASE_SECONDS

    @pytest.mark.timeout(30)
    def test_a_marked_tests_keywords_carry_the_mark(self, request):
        """What the report's ``keywords`` is built from: a test's own timeout
        mark is there, so the sum can leave it out."""
        assert "timeout" in request.node.keywords


class TestTheFixtureHandsOnTheBuild:
    def test_the_prebuilt_tree_is_handed_on_without_a_second_build(self, conftest, builds):
        config = SimpleNamespace(_initialized_repo_build=(Path("prebuilt"), None))
        assert conftest._initialized_repo_for(config, object()) == Path("prebuilt") and builds == []

    def test_a_failed_build_is_named_in_the_requester(self, conftest, builds):
        config = SimpleNamespace(_initialized_repo_build=(None, "RuntimeError: init timed out (after 45.0s)"))
        with pytest.raises(pytest.fail.Exception, match="the tree built before the first test failed: RuntimeError"):
            conftest._initialized_repo_for(config, object())
        assert builds == []

    def test_a_request_the_hook_never_saw_fails_by_name_instead_of_building(self, conftest, builds):
        """A dynamic request (``request.getfixturevalue``) in a session where no
        collected test names the fixture: building here would put the build back
        under the ceiling, the DEF-1177 death on a slow host."""
        config = SimpleNamespace(_initialized_repo_hook_ran=True)
        with pytest.raises(pytest.fail.Exception, match="requested where the build hook could not see it"):
            conftest._initialized_repo_for(config, object())
        assert builds == []

    def test_without_the_hook_the_fixture_builds_as_before(self, conftest, builds):
        factory = object()
        assert conftest._initialized_repo_for(SimpleNamespace(), factory) == Path("tree")
        assert builds == [(factory, None)], "the lazy path takes the build's own default bound"

    def test_each_path_is_bounded_by_what_governs_it(self, conftest):
        """The lazy path builds inside a test, so its spawns end under the 60 s
        ceiling. The hook's build is outside every ceiling, with every worker at
        once: at 50 s all four windows-latest workers' `git add -A` took the whole
        bound (run 38890464527), where 120 s let every build finish."""
        assert conftest._BUILD_LAZY_STEP_TIMEOUT_S < 60
        assert conftest._BUILD_HOOK_STEP_TIMEOUT_S > 120


class TestNoUnitModuleBuildsTheTree:
    def test_no_module_in_the_unit_slice_asks_for_the_tree(self, conftest):
        """``-m unit`` is the no-subprocess quick pass (tests/README.md); a module
        classified ``unit`` that asks for the tree makes the hook copy the
        checkout, run git and spawn ``espalier init`` before its first test.
        Read from each module's own code: a parameter naming a tree fixture, or
        the name passed to ``getfixturevalue`` or a ``usefixtures`` mark."""
        tree_fixtures = _tree_fixtures()
        offenders = []
        for path in checkout_glob(CONFTEST.parent, "test_*.py"):
            if conftest._primary_marker(path.stem) != "unit":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names = {a.arg for a in node.args.args + node.args.kwonlyargs}
                    if names & tree_fixtures:
                        offenders.append(f"{path.name}::{node.name}")
                elif (isinstance(node, ast.Call)
                      and getattr(node.func, "attr", "") in ("getfixturevalue", "usefixtures")
                      and any(isinstance(a, ast.Constant) and a.value in tree_fixtures for a in node.args)):
                    offenders.append(f"{path.name}:{node.lineno} {node.func.attr}")
        assert offenders == [], offenders

    def test_the_tree_fixtures_are_derived_from_conftest(self):
        assert {"initialized_repo_root", "self_host_tree_copy"} <= _tree_fixtures(), _tree_fixtures()

    def test_this_module_is_not_in_the_unit_slice(self, conftest):
        assert conftest._primary_marker("test_session_tree_build") == "integration"


class TestTheRealHookBuiltThisSessionsTree:
    def test_a_parameter_requester_gets_the_tree_the_hook_built(self, request, initialized_repo_root):
        """The live hook, keyed on the fixture's registered name, built this
        session's tree before the first test, and the fixture handed that tree
        on: a hook keyed on a name no test asks for would leave nothing here."""
        built = getattr(request.config, "_initialized_repo_build", None)
        assert built is not None and built == (initialized_repo_root, None), built
