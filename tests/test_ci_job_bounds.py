"""Every CI job that runs the test suite stops in bounded time, the
portability cell runs the local tier's two legs, and the post-merge proof runs
to the end on every push.

Why this exists: none of the four jobs that run the full suite set
``timeout-minutes`` (DEF-1178), so a hang the per-test ceiling cannot reach
(collection, a worker the controller waits on, a step around pytest) ran to
GitHub's 360-minute job default while a pull request's required cells waited.
The population is derived from the workflows themselves -- every job one of
whose steps runs pytest, or a script that does -- never a hand list, so a job
added tomorrow that runs the suite is held to the bound the day it lands.

The portability cell's Test step (DEF-979) runs the parallel set under
``-n auto`` and the serial set at one worker, the serial list read from
``scripts/proof_tier.py`` when the step runs; this pins that the line it runs
prints exactly ``proof_tier.SERIAL_FILES``, so the cell and the local tier
cannot drift apart, and that both invocations carry ``-n`` (the cell names the
test that crashed a worker instead of dying with no test named).
"""
from __future__ import annotations

import contextlib
import io
import re
import sys
from pathlib import Path

import pytest

from tests._live_tree import checkout_glob

yaml = pytest.importorskip("yaml")  # a dev extra: a runtime-only install skips the file

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: A step that runs the suite: pytest itself, or one of the scripts that runs it
#: (each of these spawns pytest; none runs in a workflow today but the first four).
_RUNS_THE_SUITE = re.compile(
    r"\bpytest\b|proof_tier\.py[^\n]*--run|release_check\.py|fresh_clone_gate\.py|final_release_matrix\.py"
    r"|host_check\.py|check_handoff_landing\.py|verify_pins\.py|archive_probe\.py"
)
#: GitHub's default, which is what no bound means.
_GITHUB_DEFAULT_MINUTES = 360
#: The four jobs that run the whole suite; the derived population must hold them.
_FULL_SUITE_JOBS = {
    ("test.yml", "test"), ("test.yml", "test-serial"),
    ("clean-checkout.yml", "clean-checkout"), ("portability.yml", "portability"),
}


def _workflows() -> dict[str, dict]:
    """Every workflow GitHub runs: both extensions it reads."""
    return {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for pattern in ("*.yml", "*.yaml") for path in checkout_glob(WORKFLOWS, pattern)
    }


def _serial_files() -> tuple[str, ...]:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import proof_tier  # type: ignore[import-not-found]
    finally:
        sys.path.remove(str(REPO_ROOT / "scripts"))
    return tuple(proof_tier.SERIAL_FILES)


def _suite_jobs() -> dict[tuple[str, str], dict]:
    jobs: dict[tuple[str, str], dict] = {}
    for name, data in _workflows().items():
        for job_id, job in ((data or {}).get("jobs") or {}).items():
            runs = "\n".join(str(step.get("run", "")) for step in job.get("steps") or [])
            if _RUNS_THE_SUITE.search(runs):
                jobs[(name, job_id)] = job
    return jobs


def _portability_test_step() -> str:
    steps = _workflows()["portability.yml"]["jobs"]["portability"]["steps"]
    (step,) = [s for s in steps if s.get("name") == "Test"]
    return str(step["run"])


class TestEveryJobThatRunsTheSuiteIsBounded:
    def test_the_derived_population_holds_the_full_suite_jobs(self):
        assert _FULL_SUITE_JOBS <= set(_suite_jobs()), sorted(_suite_jobs())

    def test_every_job_that_runs_the_suite_declares_timeout_minutes(self):
        unbounded = [
            f"{name}::{job_id}" for (name, job_id), job in sorted(_suite_jobs().items())
            if not isinstance(job.get("timeout-minutes"), int)
            or not 0 < job["timeout-minutes"] < _GITHUB_DEFAULT_MINUTES
        ]
        assert not unbounded, (
            "a job that runs the test suite needs a `timeout-minutes` below GitHub's "
            f"{_GITHUB_DEFAULT_MINUTES}-minute default, above its measured worst case "
            f"(DEF-1178): {unbounded}"
        )

    def test_the_serial_cell_outlasts_its_slowest_tests_own_timeout(self):
        """The serial leg holds the suite's longest per-test timeouts; a job bound
        at or under one of them kills the job with no test named where the
        test's own mark would have failed it by name. Ten minutes on top cover
        the install and the leg's other files (its worst whole run: 7.0 min).
        The marks are read by the suite contract's own parser (every form it
        reads: a keyword, an alias, a module constant), and a mark it cannot
        read fails here rather than reading as no mark."""
        from tests.test_test_suite_contract import _declared_timeout_sites

        sites = [(rel, label, seconds) for rel in _serial_files()
                 for label, seconds, _slow in _declared_timeout_sites((REPO_ROOT / rel).read_text(encoding="utf-8"))]
        unread = [f"{rel}::{label}" for rel, label, seconds in sites if seconds == float("inf")]
        assert not unread, f"a timeout mark the parser cannot read, so the floor cannot judge it: {unread}"
        assert sites, "no per-test timeout mark in the serial files: the floor below reads nothing"
        worst = max(seconds for _rel, _label, seconds in sites)
        bound = _suite_jobs()[("test.yml", "test-serial")]["timeout-minutes"]
        assert bound * 60 >= worst + 600, (bound, worst)

    @pytest.mark.parametrize("workflow, job_id", [("test.yml", "test-serial"), ("post-merge.yml", "full-tier")])
    def test_the_jobs_that_run_verify_pins_on_full_history_keep_it(self, workflow, job_id):
        """tests/test_verify_pins.py is a serial file (DEF-2036) whose control
        rows skip on a shallow tree by design, so a checkout cut to the default
        depth would read green with none of them run. Dies to: the
        `fetch-depth: 0` dropped from either job's checkout."""
        assert "tests/test_verify_pins.py" in _serial_files()
        job = _suite_jobs()[(workflow, job_id)]
        (checkout,) = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@")]
        assert (checkout.get("with") or {}).get("fetch-depth") == 0, checkout


class TestThePortabilityCellRunsTheLocalTiersLegs:
    @staticmethod
    def _legs() -> tuple[str, list[str]]:
        """The selection branch, and the two legs' pytest lines after its `fi`
        (YAML strips the block's indent; the branch opens on the SELECT test)."""
        before, opened = _portability_test_step().split('if [ -n "$SELECT" ]; then\n', 1)
        selection, legs = re.split(r"^fi$", opened, maxsplit=1, flags=re.M)
        return selection, [line.strip() for line in legs.splitlines() if "python -m pytest" in line]

    def test_both_invocations_run_under_xdist(self):
        """The serial-on-purpose single invocation died at a ceiling with no test
        named; both legs now run under xdist, the serial set at one worker."""
        _, pytest_lines = self._legs()
        assert [("-n auto" in line, "-n 1" in line) for line in pytest_lines] == [(True, False), (False, True)], (
            pytest_lines
        )

    def test_a_dispatched_selection_runs_at_one_worker_under_xdist(self):
        """The narrowed Windows loop chases a cell's red: run without xdist, a
        ceiling crossing there would end the session with no test named."""
        selection, _ = self._legs()
        (line,) = [line for line in selection.splitlines() if "python -m pytest" in line]
        words = line.split()
        assert ("-n", "1") in zip(words, words[1:]), line

    def test_the_slow_host_has_one_ceiling_of_its_own(self):
        """windows-latest crosses the suite's 60 s per-test ceiling where Ubuntu
        takes 37 s (measured: the Walk's 16 named worker crashes in run
        38874132596): one ceiling keyed on the host, above the ini's, set before
        the first pytest line, and nowhere else, so the other cells keep catching
        slowness at 60 s and no module list grows one crossing at a time. A mark
        outranks it, so no declared mark may sit between the two ceilings: such a
        test would get less room on the slow host than every unmarked one."""
        from tests.test_test_suite_contract import _declared_timeout_sites

        body = _portability_test_step()
        match = re.search(r'if \[ "\$RUNNER_OS" = "Windows" \]; then\n\s*export PYTEST_TIMEOUT=(\d+)\n', body)
        assert match, "the Test step no longer raises the windows-latest ceiling by RUNNER_OS"
        ini = re.search(r"(?m)^timeout = (\d+)$", (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        assert ini and int(match.group(1)) > int(ini.group(1)), (match.group(1), ini and ini.group(1))
        assert body.index(match.group(0)) < body.index("python -m pytest")
        assert body.count("PYTEST_TIMEOUT=") == 1 and "--timeout" not in body
        host, suite = int(match.group(1)), int(ini.group(1))
        between = [f"{path.name}::{label} ({seconds:g} s)"
                   for path in checkout_glob(REPO_ROOT / "tests", "test_*.py")
                   for label, seconds, _slow in _declared_timeout_sites(path.read_text(encoding="utf-8"))
                   if suite < seconds < host]
        assert between == [], (
            f"a timeout mark between the suite's {suite} s and the windows-latest cell's {host} s: on that "
            f"host a mark outranks PYTEST_TIMEOUT, so these get less room than every unmarked test: {between}")

    def test_the_serial_files_leave_the_parallel_leg_and_make_up_the_serial_one(self):
        """The derivation is pinned below; this pins its use, so a hurried edit
        that drops `$ignores` from the parallel line (the serial files then run
        under load, the macOS test_redos red DEF-979 cites, and again serially)
        or narrows the serial line reds here."""
        body = _portability_test_step()
        parallel, serial = self._legs()[1]
        assert 'for f in $serial; do ignores="$ignores --ignore=$f"; done' in body
        assert "$ignores" in parallel.split() and '-m "not heavy_e2e"' in parallel, parallel
        assert serial.split("2>&1")[0].split()[-1] == "$serial" and '-m "not heavy_e2e"' in serial, serial

    def test_the_serial_line_prints_proof_tiers_serial_files(self, monkeypatch):
        """Run the step's own derivation and compare it to the tuple, so a step
        that restated or misspelled the list reds here, not on a runner."""
        match = re.search(r"""serial="\$\(python -c '([^']*)'\)\"""", _portability_test_step())
        assert match, "the Test step no longer derives its serial list from proof_tier.py"
        monkeypatch.chdir(REPO_ROOT)
        monkeypatch.setattr(sys, "path", list(sys.path))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            exec(match.group(1), {})  # noqa: S102 - the workflow's own one-line derivation, read from the tree

        assert out.getvalue().split() == list(_serial_files())
        assert _serial_files(), "proof_tier.py names no serial files"

    @pytest.mark.parametrize("leg", ["parallel", "serial"])
    def test_each_invocation_has_its_own_summary_guard(self, leg):
        body = _portability_test_step()
        assert f"tee pytest-{leg}.txt" in body and f"died pytest-{leg}.txt" in body, leg


class TestThePostMergeProofRunsEveryTip:
    def test_no_concurrency_group_cancels_a_proof(self):
        """DEF-2015: a concurrency group cancels a post-merge run -- the running
        one under `cancel-in-progress`, a pending one without it (GitHub keeps
        one pending run per group) -- and main went unproven through whole
        stretches of merges. Each push's run goes to the end, beside the next."""
        workflow = _workflows()["post-merge.yml"]
        grouped = ["workflow"] * ("concurrency" in workflow) + [
            job_id for job_id, job in (workflow.get("jobs") or {}).items() if "concurrency" in job
        ]
        assert not grouped, f"post-merge.yml sets a concurrency group on: {grouped}"


class TestThePostMergeWindowsLegKeepsItsContracts:
    """The advisory Windows leg on main (post-merge-windows.yml, the serial
    files on windows-latest after each push): its contracts were prose in the
    header until the lane's failure-mode review, so a tidy-up could have
    undone one silently. Each test pins one."""

    @staticmethod
    def _leg() -> tuple[dict, dict]:
        import importlib.util

        spec = importlib.util.spec_from_file_location("post_merge_for_job_bounds", REPO_ROOT / "tools" / "cc" / "_post_merge.py")
        pm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pm)
        workflow = _workflows()[pm.WINDOWS_WORKFLOW]
        (job,) = workflow["jobs"].values()
        return workflow, job

    def test_the_file_the_board_reads_exists_and_runs_on_a_push_to_main(self):
        """Dies to: the file renamed or deleted (the board's absent state is
        silent on purpose, so nothing else would say), or its trigger moved."""
        workflow, job = self._leg()
        on = workflow.get("on", workflow.get(True))   # a bare `on:` parses as the boolean key
        assert on["push"]["branches"] == ["main"] and "workflow_dispatch" in on, on
        assert "windows" in str(job["runs-on"]).lower()
        assert "--leg serial" in "\n".join(str(s.get("run", "")) for s in job["steps"])

    def test_no_job_or_step_continues_on_error(self):
        """Dies to: `continue-on-error: true` (every run would conclude success
        and the board would be silent forever)."""
        _workflow, job = self._leg()
        assert "continue-on-error" not in job
        assert not [s for s in job["steps"] if "continue-on-error" in s]

    def test_the_proof_keeps_no_windows_job(self):
        """Dies to: the leg folded into post-merge.yml, whose readers read a
        run's conclusion, so a Windows flake there would ask for a revert."""
        proof = _workflows()["post-merge.yml"]
        on_windows = [job_id for job_id, job in proof["jobs"].items()
                      if "windows" in (str(job.get("runs-on", "")) + str((job.get("strategy") or {}).get("matrix") or {})).lower()]
        assert not on_windows, on_windows

    def test_its_per_test_ceiling_is_the_portability_legs(self):
        """Dies to: the two literal homes of the windows-latest ceiling
        drifting apart (portability's export and this step's env)."""
        _workflow, job = self._leg()
        (step,) = [s for s in job["steps"] if "--leg serial" in str(s.get("run", ""))]
        match = re.search(r'export PYTEST_TIMEOUT=(\d+)\n', _portability_test_step())
        assert match and str(step["env"]["PYTEST_TIMEOUT"]) == match.group(1), (step.get("env"), match and match.group(1))
        assert step.get("shell") == "bash"

    def test_its_bound_outlasts_the_serial_files_longest_mark(self):
        """The test-serial cell's rule, applied to this job: a bound at or under
        a serial file's own mark kills the job with no test named where the
        mark would have failed it by name. Dies to: the bound cut back to twice
        the measured run (ten), under the serial files' worst mark (1800 s,
        tests/test_verify_pins.py's, since DEF-2036)."""
        from tests.test_test_suite_contract import _declared_timeout_sites

        _workflow, job = self._leg()
        worst = max(seconds for rel in _serial_files()
                    for _label, seconds, _slow in _declared_timeout_sites((REPO_ROOT / rel).read_text(encoding="utf-8")))
        assert worst < float("inf") and job["timeout-minutes"] * 60 >= worst + 600, (job["timeout-minutes"], worst)
