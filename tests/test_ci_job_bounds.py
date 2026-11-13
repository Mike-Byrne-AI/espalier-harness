"""Every CI job that runs the test suite stops in bounded time and, on Linux,
keeps its temp dir on the runner's disk; the portability cell runs the local
tier's two legs, and the post-merge proof runs to the end on every push.

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
import fnmatch
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
#: Where a Linux job that runs the suite points TMPDIR: under the runner's own
#: temp dir, which is on the root disk on both of GitHub's runner pools.
_RUNNER_DISK_TMP = "$RUNNER_TEMP/tmp"


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


def _can_run_on_linux(job: dict) -> bool:
    """An ubuntu label, or a matrix expression whose runner list names one."""
    runs_on = str(job.get("runs-on", ""))
    if "matrix." in runs_on:
        runs_on += str((job.get("strategy") or {}).get("matrix") or {})
    return "ubuntu" in runs_on.lower()


def _portability_test_step() -> str:
    steps = _workflows()["portability.yml"]["jobs"]["portability"]["steps"]
    (step,) = [s for s in steps if s.get("name") == "Test"]
    return str(step["run"])


def _serial_file_jobs() -> dict[tuple[str, str], dict]:
    """Every job that runs the serial files, by the census's one derivation
    (scripts/ci_job_bounds_census.py::job_runs_the_serial_files, over each job's
    own lines), so a job added tomorrow that runs them is held the day it lands
    and the census's re-measure reads the same set."""
    census, files, suite = _census(), _serial_files(), _suite_jobs()
    out: dict[tuple[str, str], dict] = {}
    for name in _workflows():
        for job_id, meta in census.read_bounds((WORKFLOWS / name).read_text(encoding="utf-8")).items():
            if census.job_runs_the_serial_files(meta["lines"], files):
                out[(name, job_id)] = suite[(name, job_id)]
    return out


def _worst_serial_mark() -> float:
    """The longest per-test timeout mark in the serial files, in seconds, read by
    the suite contract's own parser (every form it reads: a keyword, an alias, a
    module constant), the parser the census's ``serial_marks`` reads them by; a
    mark it cannot read fails here rather than reading as no mark."""
    from tests.test_test_suite_contract import _declared_timeout_sites

    sites = [(rel, label, seconds) for rel in _serial_files()
             for label, seconds, _slow in _declared_timeout_sites((REPO_ROOT / rel).read_text(encoding="utf-8"))]
    unread = [f"{rel}::{label}" for rel, label, seconds in sites if seconds == float("inf")]
    assert not unread, f"a timeout mark the parser cannot read, so the floor cannot judge it: {unread}"
    assert sites, "no per-test timeout mark in the serial files: the floor reads nothing"
    return max(seconds for _rel, _label, seconds in sites)


#: DEF-2038. Each job that runs the serial files, with the worst of its last 20
#: green runs in minutes: the whole job (checkout, install and, on a job that runs
#: both legs, the parallel one too), read by `python3
#: scripts/ci_job_bounds_census.py` on the date below, while the serial files were
#: those below; an entry whose bound was raised since carries, on its own comment,
#: the date of the read that raised it, and the date below stays the day the
#: serial files were last measured, which the roster test's message reads. The
#: reason for the floor: a test that hangs must be cut by its own timeout, naming
#: it, before the job's bound cuts the job with none named. A test at its mark adds
#: at most the mark to such a run, so the bound holds the worst mark plus this
#: worst (one test at its mark; it is conservative on a shallow checkout, where
#: tests/test_verify_pins.py's controls skip). The margin this replaced was a flat
#: 600 s on a 7.0-minute leg of 2026-10-16, which had grown to 23.5 by the read of
#: the date below. The census prints the floor at every re-measure, so growth
#: inside the files reads RAISE there; these figures are what each bound was last
#: set from, and a serial file added reds the roster test below until they cover it.
_SERIAL_JOBS_MEASURED_ON = "2026-11-11"
_SERIAL_JOBS_MEASURED_WORST = {
    ("test.yml", "test-serial"): 23.5,  # median 17.8; 80 cells, 20 runs
    ("post-merge.yml", "full-tier"): 88.1,  # median 65.2, 2026-11-12; both legs in series
    ("post-merge-windows.yml", "serial-leg"): 12.9,  # median 10.7
    ("portability.yml", "portability"): 125.1,  # median 74.4; 55 cells, 20 runs
    ("clean-checkout.yml", "clean-checkout"): 112.0,  # median 100.7, 2026-11-12
    ("release.yml", "release-check"): 47.8,  # median 37.6
}
_SERIAL_FILES_MEASURED = (
    "tests/test_redos.py", "tests/test_speedbump_irreversible.py", "tests/test_hooks.py",
    "tests/test_write_guard_time_budget.py", "tests/test_guard_metamorphic.py",
    "tests/test_powershell_reachability_differential.py", "tests/test_wheel_payload.py",
    "tests/test_declared_limits_contract.py", "tests/test_axis_registry.py", "tests/test_verify_pins.py",
)


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


class TestEveryJobThatRunsTheSerialFilesOutlastsTheirMarks:
    """DEF-2038: the serial files hold the suite's longest per-test marks, and the
    jobs that run them were bounded by a flat margin that did not grow with the
    leg (test-serial's 40 under a 23.5-minute worst run and a 30-minute mark).
    Each such job's bound is the worst mark, read live, plus the job's own dated
    measured worst; the roster is derived both ways and records the serial files
    it was measured over."""

    def test_the_measured_roster_is_the_derived_population(self):
        """Dies to: a job that runs the serial files with no measured figure (a
        new one, or one the derivation stopped reading), or a figure kept for a
        job that no longer runs them."""
        assert set(_SERIAL_JOBS_MEASURED_WORST) == set(_serial_file_jobs()), sorted(_serial_file_jobs())

    def test_the_figures_cover_every_serial_file_that_runs_today(self):
        """Dies to: a serial file added with the figures left as they were, which
        is how the 600 s margin outlived the leg it was set on. A file dropped
        only loosens the floor, so it does not red."""
        added = sorted(set(_serial_files()) - set(_SERIAL_FILES_MEASURED))
        assert not added, (
            f"serial files added since the jobs were measured on {_SERIAL_JOBS_MEASURED_ON}: {added}. "
            "The census cannot read a list that has no runs yet, so add each new file's measured "
            "serial-leg time to the figures of the jobs that run it now, raise any bound the floor then "
            "asks for, add the files here, and re-measure with python3 scripts/ci_job_bounds_census.py "
            "once the jobs have 20 runs (its floor column judges them from then on).")

    @pytest.mark.parametrize("key", sorted(_SERIAL_JOBS_MEASURED_WORST), ids="/".join)
    def test_its_bound_holds_the_worst_mark_plus_its_measured_run(self, key):
        """Dies to: a bound cut under the worst mark plus the job's worst run, or a
        mark raised past what the bound holds. The job is read by PyYAML and the
        floor unrounded (the census rounds it up to five); that the census derives
        the same jobs is the roster test's to say."""
        bound = _suite_jobs()[key]["timeout-minutes"]
        floor_s = _worst_serial_mark() + _SERIAL_JOBS_MEASURED_WORST[key] * 60
        assert bound * 60 >= floor_s, (
            f"{key}: timeout-minutes {bound} is under the serial files' worst mark plus the job's "
            f"measured worst ({floor_s / 60:.1f} min)")

    def test_the_box_lock_names_a_holder_only_past_the_post_merge_worst(self):
        """tests/_box_lock.py's WAIT_CEILING_MIN names a holder older than the
        post-merge proof's measured worst run, and its comment cites that worst.
        Dies to: the full-tier figure re-measured past the ceiling with the
        ceiling left where it was, so a healthy tier is named for a stop."""
        from tests._box_lock import WAIT_CEILING_MIN

        worst = _SERIAL_JOBS_MEASURED_WORST[("post-merge.yml", "full-tier")]
        assert WAIT_CEILING_MIN > worst, (
            f"tests/_box_lock.py::WAIT_CEILING_MIN {WAIT_CEILING_MIN} is not above the post-merge "
            f"proof's measured worst, {worst} min: raise it and its comment with the figure")

    def test_the_floor_is_the_mark_plus_the_worst_rounded_up_to_five(self):
        """Dies to: the mark read as minutes, or seconds and minutes added raw, or
        rounding down."""
        floor = _census().serial_floor
        assert floor(23.5, 1800) == 55
        assert floor(25.0, 1800) == 55
        assert floor(25.1, 1800) == 60
        assert floor(12.9, 900) == 30

    def test_the_census_needs_the_floor_where_it_outranks_the_rule(self, monkeypatch, tmp_path, capsys):
        """Dies to: the census judging a job that runs the serial files by the
        1.5x rule alone, which reads ok on test-serial up to a 36.7-minute worst
        while the floor breaks past 25 (both reviewers of DEF-2038)."""
        census = _census()
        (tmp_path / "ci.yml").write_text(
            "jobs:\n  serial:\n    timeout-minutes: 55\n    steps:\n"
            "      - run: python scripts/proof_tier.py --run --tier full --leg serial\n"
            "  parallel:\n    timeout-minutes: 55\n    steps:\n"
            "      - run: python scripts/proof_tier.py --run --tier full --leg parallel\n",
            encoding="utf-8")
        monkeypatch.setattr(census, "WORKFLOWS", tmp_path)
        monkeypatch.setattr(census, "measure", lambda wf, jobs, runs, scan, repo: {
            j: {"greens": [26.0], "green_runs": 20, "cancels": [], "cuts": 0, "cut_max": None, "unread": 0}
            for j in jobs})
        assert census.main(["--json"]) == 0
        import json
        rows = {r["job"]: r for r in json.loads(capsys.readouterr().out)["rows"]}
        assert rows["serial"]["serial"] and rows["serial"]["floor"] == 60, rows["serial"]
        assert rows["serial"]["needed"] == 60 and rows["serial"]["verdict"] == "RAISE"
        assert not rows["parallel"]["serial"] and rows["parallel"]["verdict"] == "ok", rows["parallel"]

    @pytest.mark.parametrize("command, opt_in, runs_them", [
        ("python scripts/proof_tier.py --run --tier full", False, True),
        ("python scripts/proof_tier.py --run --tier full --heavy", False, True),
        ('python scripts/proof_tier.py --run --tier "$TIER" --leg serial', False, True),
        ('python scripts/proof_tier.py --run --tier "$TIER" --leg "$LEG"', False, True),
        ('python scripts/proof_tier.py --run --tier "$TIER" --leg parallel', False, False),
        ('python scripts/proof_tier.py --run --tier "$TIER" --leg=parallel', False, False),
        ('python scripts/proof_tier.py --run --leg "parallel"', False, False),
        ("python scripts/proof_tier.py --base origin/main", False, False),
        ('python -m pytest -q -n 1 -m "not heavy_e2e" $serial', False, True),
        ('python3 -m pytest -q "${serial}"', False, True),
        ("python -m pytest -q", False, True),
        ("timeout 600 pytest -q", False, True),
        ("python -m pytest tests/test_wheel_payload.py -q", False, True),
        ("python -m pytest tests/test_verify_pins.py::TestIsolation -q", False, True),
        ("python -m pytest tests/test_scope_walker.py -q", False, False),
        ("python scripts/fresh_clone_gate.py --python 3.11", False, True),
        ("python scripts/final_release_matrix.py", False, True),
        ("python scripts/release_check.py", True, True),
        ("python scripts/release_check.py", False, False),
        ("pip install build pytest setuptools", False, False),
        ('timeout 120 du -xh "$tmp/pytest-of-$(id -un)"', False, False),
        ('echo "pytest printed no summary line"', False, False),
    ])
    def test_the_derivation_reads_each_way_a_command_runs_them(self, command, opt_in, runs_them):
        assert _census().command_runs_the_serial_files(command, _serial_files(), opt_in) is runs_them

    @pytest.mark.parametrize("lines, runs_them", [
        (["      - run: |", "          python scripts/proof_tier.py --run --tier full \\",
          "            --leg parallel"], False),
        (["      - run: |", "          python scripts/proof_tier.py --run --tier full \\",
          "            --leg serial"], True),
        (["      - run: python scripts/proof_tier.py --run --leg parallel  # not --leg serial"], False),
        (["      - run: python scripts/proof_tier.py --run --leg parallel && "
          "python scripts/proof_tier.py --run --leg serial"], True),
        (["    env:", "      ESPALIER_RELEASE_CHECK_WITH_TESTS: 1", "      - run: python scripts/release_check.py"],
         True),
        (["    env:", "      ESPALIER_RELEASE_CHECK_WITH_TESTS: 'true'", "      - run: python scripts/release_check.py"],
         False),
    ])
    def test_a_job_s_lines_are_read_as_commands(self, lines, runs_them):
        """Dies to: a continuation left split, a trailing comment read as a flag,
        a second command on the line read as the first's, or an opt-in other than
        the exact 1 release_check.py reads."""
        assert _census().job_runs_the_serial_files(lines, _serial_files()) is runs_them


class TestTheSuitesTempLivesOnTheRunnerDisk:
    """DEF-3027: GitHub's AWS pool mounts /tmp as a 7.7G tmpfs with
    `usrquota`, and the full tier's parallel leg filled the runner user's quota
    there: the sampler read /tmp's use freeze at 6.1G (6,431,024 KB) from
    13:06:53 with 1.6G of the tmpfs still free, and pytest's terminal flush
    raised Errno 122 at 13:07:48 (#470's test (3.13), job 125929994703,
    2026-11-03), where the same leg reached 11G on the Azure pool, whose /tmp is
    the root disk. So every job that runs the suite on a Linux runner makes a
    directory under $RUNNER_TEMP, on the root disk on both pools (19G free on
    the AWS cell's 72G root before the tier), and exports TMPDIR to it as its
    first step, before anything writes a temp file. Made, not only named:
    tempfile.gettempdir() passes over a TMPDIR that is not a directory and
    settles on /tmp without a word."""

    @staticmethod
    def _linux_jobs() -> dict[tuple[str, str], dict]:
        return {key: job for key, job in _suite_jobs().items() if _can_run_on_linux(job)}

    def test_the_derived_population_holds_the_full_suite_jobs_and_the_proof(self):
        assert _FULL_SUITE_JOBS | {("post-merge.yml", "full-tier")} <= set(self._linux_jobs()), (
            sorted(self._linux_jobs()))

    def test_each_one_makes_its_temp_dir_and_exports_it_first(self):
        """Dies to: the step dropped, moved below a step that writes a temp file
        (the install builds in TMPDIR, the disk read samples it), or its mkdir
        dropped; and to a job added tomorrow that runs the suite without it."""
        expected = [f'mkdir -p "{_RUNNER_DISK_TMP}"', f'echo "TMPDIR={_RUNNER_DISK_TMP}" >> "$GITHUB_ENV"']
        wrong = {}
        for (name, job_id), job in sorted(self._linux_jobs().items()):
            first = (job.get("steps") or [{}])[0]
            if [line.strip() for line in str(first.get("run", "")).splitlines()] != expected:
                wrong[f"{name}::{job_id}"] = first.get("name") or first.get("uses")
        assert not wrong, (
            f"a job that runs the suite on Linux opens with the step that makes {_RUNNER_DISK_TMP} and "
            f"exports TMPDIR to it (DEF-3027); the first step here is another: {wrong}")

    def test_a_job_whose_matrix_crosses_systems_takes_the_step_on_linux_alone(self):
        """Windows' tempfile reads TMPDIR ahead of TEMP and TMP, and a macOS
        runner's TMPDIR is the system's own per-user directory, so a cross-system
        matrix (portability's) runs the step on its Linux leg only; a job on a
        fixed ubuntu label runs it unconditionally, where an `if:` could only
        skip it."""
        guards = {f"{name}::{job_id}": (job.get("steps") or [{}])[0].get("if")
                  for (name, job_id), job in sorted(self._linux_jobs().items())}
        # Any computed runner is read as one that may cross systems: an input or
        # a fallback (`inputs.os || 'ubuntu-latest'`) can name Windows as well.
        crossing = {f"{name}::{job_id}" for (name, job_id), job in self._linux_jobs().items()
                    if "${{" in str(job.get("runs-on", ""))}
        assert crossing, "no job that runs the suite has a cross-system matrix; this test reads nothing"
        assert {key: guard for key, guard in guards.items() if key in crossing} == dict.fromkeys(
            sorted(crossing), "runner.os == 'Linux'"), guards
        assert not [key for key, guard in guards.items() if key not in crossing and guard is not None], guards

    def test_no_job_off_linux_exports_a_tmpdir(self):
        """Dies to: the step copied into the Windows leg on main
        (post-merge-windows.yml), whose TMPDIR its tempfile would read first."""
        exporting = [f"{name}::{job_id}" for name, data in sorted(_workflows().items())
                     for job_id, job in ((data or {}).get("jobs") or {}).items()
                     if not _can_run_on_linux(job)
                     and any("TMPDIR=" in str(step.get("run", "")) for step in job.get("steps") or [])]
        assert not exporting, exporting

    def test_no_env_block_sets_tmpdir(self):
        """The first step's export is the one home of TMPDIR: a workflow-, job-
        or step-level `env:` naming it outranks the export for that step or
        sits beside it (a step reproducing the quota by `TMPDIR: /tmp` on the
        tier, a job env on the Windows leg), and the tests above read only the
        steps' `run` text. Dies to: any `env:` mapping in a workflow naming
        TMPDIR."""
        named = [f"{name}{where}" for name, data in sorted(_workflows().items())
                 for where, env in [("", (data or {}).get("env"))] + [
                     (f"::{job_id}{at}", block)
                     for job_id, job in ((data or {}).get("jobs") or {}).items()
                     for at, block in [("", job.get("env"))] + [
                         (f"::step {i}", step.get("env")) for i, step in enumerate(job.get("steps") or [])]]
                 if isinstance(env, dict) and "TMPDIR" in env]
        assert not named, f"an env: block sets TMPDIR, beside the first step's export (DEF-3027): {named}"


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


def _load_post_merge():
    """``tools/cc/_post_merge.py`` under an alias: the board's base-run
    readers, held here to this tree's workflow files."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("post_merge_for_job_bounds", REPO_ROOT / "tools" / "cc" / "_post_merge.py")
    pm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pm)
    return pm


def _yaml_pushes_to(workflow: dict, base: str) -> bool:
    """GitHub's push rule read off the parsed workflow, the oracle the
    board's text reader is held to: ``on`` a word, a list or a mapping; a
    ``push`` with ``branches`` (the last matching pattern decides, ``!``
    excluding), ``branches-ignore``, or tag filters alone (tag pushes only).
    ``fnmatch`` stands in for GitHub's patterns, which differ on ``/``; this
    tree's push filters are literal branch names."""
    on = workflow.get("on", workflow.get(True))   # a bare `on:` parses as the boolean key
    if isinstance(on, str):
        return on == "push"
    if isinstance(on, list):
        return "push" in on
    if not isinstance(on, dict) or "push" not in on:
        return False
    push = on["push"] or {}
    if "branches" in push:
        hit = False
        for pattern in push["branches"]:
            if pattern.startswith("!"):
                hit = hit and not fnmatch.fnmatchcase(base, pattern[1:])
            elif fnmatch.fnmatchcase(base, pattern):
                hit = True
        return hit
    if "branches-ignore" in push:
        return not any(fnmatch.fnmatchcase(base, pattern) for pattern in push["branches-ignore"])
    return not ({"tags", "tags-ignore"} & set(push))


#: The context values this tree's concurrency groups build from, each one
#: push's run shares with the next push's (the oracle's own list, apart from
#: the module's, so a value the module wrongly counted as shared reds here).
_SHARED_THIS_TREE = frozenset({"github.workflow", "github.ref", "github.event_name"})
#: One expression naming a shared value and nothing else; a group is shared
#: when every ``${{`` in it opens one (portability.yml's conditional tail,
#: ``format('-{0}', github.run_id)`` on a dispatch, is not one).
_SHARED_EXPRESSION = re.compile(r"\$\{\{\s*(?:" + "|".join(re.escape(v) for v in sorted(_SHARED_THIS_TREE)) + r")\s*\}\}")


class TestTheBoardsBaseRunRoster:
    """The board's ``checks:`` line reads the push runs on the base of each
    workflow whose triggers run it on a push there (``tools/cc/board.py::
    base_run_workflows``, the post-merge proof apart), derived from the
    workflow files by a text reader, since ``tools/cc`` runs on the standard
    library alone. Until DEF-5083 the roster was the Windows leg, named by
    hand, and a red release matrix on main showed on no line."""

    def test_the_text_reader_agrees_with_pyyaml_on_every_workflow_here(self):
        """Dies to: the text reader and the parsed file disagreeing on any
        workflow in this tree, about its push trigger on main or master, or
        about whether its concurrency cancels a superseded run."""
        pm = _load_post_merge()
        workflows = _workflows()
        assert workflows, "no workflow files read"
        for name, workflow in workflows.items():
            text = (WORKFLOWS / name).read_text(encoding="utf-8")
            for base in ("main", "master"):
                assert pm.pushes_to(text, base) is _yaml_pushes_to(workflow, base), (name, base)
            concurrency = workflow.get("concurrency")
            group = str(concurrency.get("group") or "") if isinstance(concurrency, dict) else ""
            supersedes = (isinstance(concurrency, dict) and concurrency.get("cancel-in-progress") is True
                          and bool(group) and group.count("${{") == len(_SHARED_EXPRESSION.findall(group)))
            assert pm.cancels_superseded(text) is supersedes, name

    def test_the_release_matrix_and_the_windows_leg_are_on_it_and_pull_request_workflows_are_not(self):
        """The presence and absence pins beside the agreement: dies to the
        release matrix or the Windows leg dropping off the roster (or the
        release matrix's cancels named, 41 of its 100 newest push runs on main
        superseded, DEF-5083), or a pull-request-only or tag-only workflow
        read onto it. Each name pinned here is a file this tree keeps."""
        pm = _load_post_merge()

        def text(name: str) -> str:
            return (WORKFLOWS / name).read_text(encoding="utf-8")

        for name in ("release.yml", "post-merge-windows.yml", "harness-guard.yml", "post-merge.yml"):
            assert pm.pushes_to(text(name), "main"), name
        for name in ("test.yml", "portability.yml", "publish.yml"):
            assert not pm.pushes_to(text(name), "main"), name
        assert pm.cancels_superseded(text("release.yml")) and not pm.cancels_superseded(text("post-merge-windows.yml"))


class TestThePostMergeWindowsLegKeepsItsContracts:
    """The advisory Windows leg on main (post-merge-windows.yml, the serial
    files on windows-latest after each push): its contracts were prose in the
    header until the lane's failure-mode review, so a tidy-up could have
    undone one silently. Each test pins one."""

    @staticmethod
    def _leg() -> tuple[dict, dict]:
        workflow = _workflows()["post-merge-windows.yml"]
        (job,) = workflow["jobs"].values()
        return workflow, job

    def test_the_file_the_board_reads_exists_and_runs_on_a_push_to_main(self):
        """Dies to: the file renamed or deleted (the board's absent state is
        silent on purpose, so nothing else would say), or its trigger moved
        off the push to main the board's roster reads it by."""
        workflow, job = self._leg()
        on = workflow.get("on", workflow.get(True))   # a bare `on:` parses as the boolean key
        assert on["push"]["branches"] == ["main"] and "workflow_dispatch" in on, on
        assert _load_post_merge().pushes_to((WORKFLOWS / "post-merge-windows.yml").read_text(encoding="utf-8"), "main")
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



class TestThePortabilityDispatchKeepsTheLegsApart:
    """DEF-5064's dispatch input, as the readers see it. A dispatched run of
    `portability.yml` lands its check runs on the head it ran on; the board,
    the banner and the ship preflight keep the latest run of a check name, so
    a dispatch under the pull-request leg's own name would stand in for that
    head's full leg (failure-mode review). And the interpreter has one
    spelling: the input's default is the pull-request cells' fallback."""

    @staticmethod
    def _workflow() -> dict:
        return _workflows()["portability.yml"]

    def test_a_pull_request_leg_keeps_its_name_and_a_dispatch_carries_its_own(self):
        name = self._workflow()["jobs"]["portability"]["name"]
        assert name.startswith("${{ github.event_name == 'workflow_dispatch' && "), name
        assert name.endswith("|| format('portability ({0})', matrix.os) }}"), name
        assert "dispatched" in name and "github.event.inputs.python" in name, name

    def test_the_interpreter_is_spelled_once_and_its_fallback_is_the_inputs_default(self):
        data = self._workflow()
        default = data[True]["workflow_dispatch"]["inputs"]["python"]["default"]
        job = data["jobs"]["portability"]
        assert job["env"]["PYTHON_VERSION"] == f"${{{{ github.event.inputs.python || '{default}' }}}}"
        setup = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/setup-python@"))
        assert setup["with"]["python-version"] == "${{ env.PYTHON_VERSION }}"
        assert setup["name"] == "Set up Python ${{ env.PYTHON_VERSION }}"


def _census():
    """scripts/ci_job_bounds_census.py under an alias, never the bare name."""
    import importlib.util
    path = Path(__file__).resolve().parent.parent / "scripts" / "ci_job_bounds_census.py"
    spec = importlib.util.spec_from_file_location("_ci_job_bounds_census_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestTheBoundsCensusReadsWhatTheWorkflowsDeclare:
    """scripts/ci_job_bounds_census.py re-measures every job's bound against its
    last green runs (post-merge's 75 sat under a 70.7-minute worst and cut runs
    with no verdict, 2026-11-08). Its text reader, its job matcher, its rule and
    its cut count are pinned here; each test names the mutation it dies to."""

    def test_its_reader_finds_every_job_level_bound_pyyaml_reads(self):
        """Dies to a reader that misses a job, or reads a step's timeout as the job's."""
        census = _census()
        for name, data in _workflows().items():
            want = {job_id: job["timeout-minutes"] for job_id, job in ((data or {}).get("jobs") or {}).items()
                    if isinstance(job.get("timeout-minutes"), int)}
            text = (WORKFLOWS / name).read_text(encoding="utf-8")
            got = {job_id: meta["bound"] for job_id, meta in census.read_bounds(text).items()}
            assert got == want, name

    def test_a_matrix_cell_and_a_literal_name_find_their_job(self):
        """Dies to a matcher that strips a literal name's own parentheses, or keeps a cell's."""
        census = _census()
        jobs = {"test": {"bound": 75, "name": None},
                "release-check": {"bound": 90, "name": "release-readiness gate (publish proof tier)"}}
        assert census.job_for("test (3.11)", jobs) == "test"
        assert census.job_for("test", jobs) == "test"
        assert census.job_for("release-readiness gate (publish proof tier)", jobs) == "release-check"
        assert census.job_for("test-serial (3.11)", jobs) is None

    def test_the_rule_is_the_factor_times_the_worst_rounded_up_to_five(self):
        """Dies to rounding down, or to a factor read as a margin added."""
        census = _census()
        assert census.needed_bound(70.7, 1.5) == 110
        assert census.needed_bound(48.2, 1.5) == 75
        assert census.needed_bound(50.0, 1.5) == 75
        assert census.needed_bound(50.1, 1.5) == 80

    def test_a_cut_at_the_present_bound_is_never_ok(self):
        """Dies to a verdict read from the greens alone: a bound that kills every slow
        run keeps the greens short, so the rule's bound sits at or under it while
        runs are lost. A cut under an older, lower bound reads ok once the bound is
        above it (post-merge's 75.9-minute cuts under its raised 110)."""
        v = _census().verdict
        assert v(75, 75, 75.2, 20, 20) == "CUT"
        assert v(110, 110, 75.9, 20, 20) == "ok"
        assert v(90, 115, None, 20, 20) == "RAISE"
        assert v(90, 115, 90.0, 20, 20) == "RAISE"

    def test_the_verdict_names_a_thin_read_an_unread_one_and_no_green(self):
        """Dies to a short window read as ok, or an unread or green-less job read as ok."""
        v = _census().verdict
        assert v(40, 20, None, 12, 20) == "thin"
        assert v(40, 20, None, 20, 20) == "ok"
        assert v(30, None, None, 0, 20) == "no green"
        assert v(30, 20, None, 20, 20, unread=-1) == "unread"

    def test_a_dot_name_sidecar_beside_the_workflows_is_never_read(self, monkeypatch, tmp_path, capsys):
        """Dies to a glob with no hidden-name filter: macOS's ._name.yml sidecar is
        binary, so reading it as UTF-8 ends the census before any row prints."""
        census = _census()
        (tmp_path / "ci.yml").write_text("jobs:\n  build:\n    timeout-minutes: 30\n", encoding="utf-8")
        (tmp_path / "._ci.yml").write_bytes(b"\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X        \xff\xfe")
        monkeypatch.setattr(census, "WORKFLOWS", tmp_path)
        monkeypatch.setattr(census, "measure", lambda wf, jobs, runs, scan, repo: {
            j: {"greens": [10.0], "green_runs": 20, "cancels": [], "cuts": 0, "cut_max": None, "unread": 0}
            for j in jobs})
        assert census.main([]) == 0
        out = capsys.readouterr().out
        assert "ci.yml / build" in out and "._ci" not in out

    def _measure(self, census, monkeypatch, views, runs=20):
        def fake_gh(args, repo):
            if args[:2] == ["run", "list"]:
                return [{"databaseId": i, "status": "completed"} for i in views]
            return {"jobs": views[int(args[2])]}

        monkeypatch.setattr(census, "gh_json", fake_gh)
        jobs = {"full-tier": {"bound": 110, "name": None}, "test": {"bound": 90, "name": None}}
        return census.measure("x.yml", jobs, runs, 60, None)

    @staticmethod
    def _job(name, conclusion, start, end):
        return {"name": name, "conclusion": conclusion,
                "startedAt": f"2026-11-08T{start}:00Z", "completedAt": f"2026-11-08T{end}:00Z"}

    def test_a_cut_is_a_cancel_longer_than_the_worst_green_whatever_the_bound(self, monkeypatch):
        """Dies to counting a red or an early cancel as a cut, a red as a green, or
        judging a cut by today's bound (a 75-minute cut must still read after a raise)."""
        census, job = _census(), self._job
        views = {
            1: [job("full-tier", "success", "01:00", "02:00")],
            2: [job("full-tier", "cancelled", "03:00", "04:15")],
            3: [job("full-tier", "cancelled", "05:00", "05:10")],
            4: [job("full-tier", "failure", "06:00", "07:30")],
        }
        out = self._measure(census, monkeypatch, views)["full-tier"]
        assert out["greens"] == [60.0] and out["green_runs"] == 1
        assert out["cuts"] == 1 and out["cut_max"] == 75.0

    def test_a_matrix_runs_cells_are_one_run_toward_the_count(self, monkeypatch):
        """Dies to a cap that counts cells: four green cells a run must read two runs
        as eight cells, never as two runs' worth of a five-run window."""
        census, job = _census(), self._job
        views = {i: [job(f"test (3.1{c})", "success", "01:00", f"01:{10 * i + c:02d}") for c in range(4)]
                 for i in (1, 2, 3)}
        out = self._measure(census, monkeypatch, views, runs=2)["test"]
        assert out["green_runs"] == 2
        assert len(out["greens"]) == 8
        assert max(out["greens"]) == 23.0
