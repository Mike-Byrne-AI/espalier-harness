"""Each CI job's ``timeout-minutes`` against its measured worst green run.

DEF-1178 set every suite-running job's bound above its worst case over its
last 20 runs (2026-10-16); the suite grew and post-merge's 48.2-minute worst
became 70.7, so its 75-minute bound began cutting runs with no verdict, and
nothing said so until runs were lost. This census is the re-measure as one
command: for every job in ``.github/workflows/`` that declares a job-level
``timeout-minutes``, it reads every cell of the job's last ``--runs`` runs
holding a green cell through ``gh`` (a matrix job's cells are one run, never
one each), and prints the bound, the worst and median green cell, the bound
the rule asks for (``--factor`` times the worst, rounded up to five minutes)
and the cuts: cancelled cells in those runs that ran longer than the worst
green, which read no verdict whatever the bound was when they ran. A job whose
bound is under the rule's is marked ``RAISE``; one with a cut at its present
bound ``CUT`` (a cut run's real length is unknown, so the greens alone can
read ``ok`` over runs the bound keeps killing: read the cut run, a slow run
asks a raise and a hang a test's own timeout); one with fewer green runs than
``--runs`` ``thin``. A cut under an older, lower bound reads ``ok`` once the
bound is above it.

A job that runs ``scripts/proof_tier.py::SERIAL_FILES`` (marked ``*``) also
has a floor (DEF-2038): their worst per-test timeout mark plus the job's worst
green run, rounded up to five, so a test that hangs is cut by its own mark,
naming it, before the job's bound cuts the job with none named. Its needed
bound is the larger of the two; tests/test_ci_job_bounds.py holds the dated
figures each bound was last set from.

    python3 scripts/ci_job_bounds_census.py
    python3 scripts/ci_job_bounds_census.py --runs 20 --factor 1.5 --json

Self-host tooling (``scripts/`` is not deployed by ``init``). Needs ``gh``
signed in; ``--repo OWNER/NAME`` when run outside the checkout.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _load(name: str, rel: str):
    """A module of this checkout loaded by path, never an installed engine's."""
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


run_bounded = _load("_json_safe_for_ci_job_bounds_census", "tools/cc/_json_safe.py").run_bounded

GH_TIMEOUT = 60.0
_JOB_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*(?:#.*)?$")
_NAME_RE = re.compile(r"^    name:\s*(.+?)\s*$")
_BOUND_RE = re.compile(r"^    timeout-minutes:\s*(\d+)\s*(?:#.*)?$")
_CELL_SUFFIX_RE = re.compile(r" \([^()]*\)$")


def read_bounds(text: str) -> dict[str, dict]:
    """Each job under ``jobs:`` that declares a job-level ``timeout-minutes``:
    ``{job_id: {"bound": minutes, "name": its literal name or None, "lines":
    the job's non-comment lines}}``. A name that is an expression (``${{ ...
    }}``) reads as None, so the job is matched by its id. Two-space job keys and
    four-space job fields, the layout every workflow here uses; a step's
    ``timeout-minutes`` (deeper) is not a job's."""
    jobs: dict[str, dict] = {}
    in_jobs, job = False, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            in_jobs = line.rstrip() == "jobs:"
            job = None
            continue
        if not in_jobs:
            continue
        m = _JOB_RE.match(line)
        if m:
            job = m.group(1)
            jobs[job] = {"bound": None, "name": None, "lines": []}
            continue
        if job is None:
            continue
        jobs[job]["lines"].append(line)
        m = _NAME_RE.match(line)
        if m:
            name = m.group(1).strip("'\"")
            jobs[job]["name"] = None if "${{" in name else name
            continue
        m = _BOUND_RE.match(line)
        if m:
            jobs[job]["bound"] = int(m.group(1))
    return {k: v for k, v in jobs.items() if v["bound"] is not None}


def job_for(api_name: str, jobs: dict[str, dict]) -> str | None:
    """The job id a run's job name belongs to: a literal ``name:`` first, then
    the id with a matrix cell's `` (values)`` suffix taken off; None otherwise."""
    for job_id, meta in jobs.items():
        if meta["name"] and api_name == meta["name"]:
            return job_id
    base = _CELL_SUFFIX_RE.sub("", api_name)
    return base if base in jobs else None


def needed_bound(worst_minutes: float, factor: float) -> int:
    """The bound the rule asks for: ``factor`` times the worst, rounded up to five."""
    return int(math.ceil(worst_minutes * factor / 5.0) * 5)


# --- DEF-2038: the jobs that run the serial files, and their floor ---------------
#
# scripts/proof_tier.py::SERIAL_FILES hold the suite's longest per-test timeout
# marks. A job that runs them must outlast a test at its mark plus the rest of
# its run, or the runner kills the job with no test named where the mark would
# have failed one by name. The floor is the worst mark plus the job's worst green
# run, read here at every re-measure, so a leg that grows inside its files (the
# 7.0-minute leg of 2026-10-16 was 23.5 by 2026-11-11) reads RAISE here.

#: A script that runs the suite in a child. Only the tier's runner and the
#: release gate can run less than the serial files; every other one counts.
_SUITE_SCRIPT_RE = re.compile(
    r"\b(proof_tier|release_check|fresh_clone_gate|final_release_matrix|host_check"
    r"|check_handoff_landing|verify_pins|archive_probe)\.py\b")
#: pytest as a command: ``-m pytest``, or the command's head (after variable
#: assignments and a ``timeout N``). A bare word is not one (``pip install
#: pytest``, a ``pytest-of-$USER`` folder).
_PYTEST_RE = re.compile(r"-m\s+pytest\b|^(?:\w+=\S*\s+)*(?:timeout\s+\S+\s+)?pytest\b")
_TEST_PATH_RE = re.compile(r"(?<![\w/.-])(tests/[\w./-]*?\.py)\b")
_PARALLEL_LEG_RE = re.compile(r"--leg[ =]['\"]?parallel\b")
#: scripts/release_check.py runs its one unsplit ``pytest -m "not slow"`` child,
#: the serial files among it, only where this is exactly ``1``.
RELEASE_CHECK_TESTS_OPT_IN = "ESPALIER_RELEASE_CHECK_WITH_TESTS"
_OPT_IN_RE = re.compile(r"^\s*" + RELEASE_CHECK_TESTS_OPT_IN + r"""\s*:\s*['"]?1['"]?\s*$""")
_COMMAND_SPLIT_RE = re.compile(r"&&|\|\||;|\|")


def commands(lines: list[str]) -> list[str]:
    """The shell commands a job's lines hold: a ``\\`` continuation joined, a
    ``run:`` key and a trailing `` # comment`` taken off, split at ``&&``,
    ``||``, ``;`` and ``|``."""
    out: list[str] = []
    for line in "\n".join(lines).replace("\\\n", " ").splitlines():
        line = re.sub(r"^\s*(?:-\s+)?(?:run:\s*)?", "", line)
        line = re.sub(r"\s#\s.*$", "", line)
        out.extend(c.strip() for c in _COMMAND_SPLIT_RE.split(line) if c.strip())
    return out


def command_runs_the_serial_files(command: str, serial_files: tuple[str, ...], release_opt_in: bool) -> bool:
    """A command runs the serial files unless it is shown not to: the tier's
    runner on its parallel leg (or with no ``--run``), the release gate without
    its tests opt-in, or a pytest naming test files none of which is serial."""
    m = _SUITE_SCRIPT_RE.search(command)
    if m:
        if m.group(1) == "proof_tier":
            return bool(re.search(r"\s--run\b", command)) and not _PARALLEL_LEG_RE.search(command)
        if m.group(1) == "release_check":
            return release_opt_in
        return True
    if _PYTEST_RE.search(command):
        named = set(_TEST_PATH_RE.findall(command))
        return not named or bool(named & set(serial_files))
    return False


def job_runs_the_serial_files(lines: list[str], serial_files: tuple[str, ...]) -> bool:
    opt_in = any(_OPT_IN_RE.match(line) for line in lines)
    return any(command_runs_the_serial_files(c, serial_files, opt_in) for c in commands(lines))


def serial_files() -> tuple[str, ...]:
    return tuple(_load("_proof_tier_for_ci_job_bounds_census", "scripts/proof_tier.py").SERIAL_FILES)


def serial_marks(files: tuple[str, ...]) -> list[tuple[str, str, float]]:
    """Every per-test timeout mark in the serial files, ``(file, site, seconds)``,
    read by the suite contract's own parser; a mark it cannot read is ``inf``."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tests.test_test_suite_contract import _declared_timeout_sites

    return [(rel, label, seconds) for rel in files
            for label, seconds, _slow in _declared_timeout_sites((REPO_ROOT / rel).read_text(encoding="utf-8"))]


def serial_floor(worst_minutes: float, mark_seconds: float) -> int:
    """The bound a job that runs the serial files needs: their worst mark plus
    the job's worst run, rounded up to five. It covers one test at its mark."""
    return int(math.ceil((mark_seconds / 60.0 + worst_minutes) / 5.0) * 5)


def verdict(bound: int, needed: int | None, cut_max: float | None, green_runs: int, runs: int,
            unread: int = 0) -> str:
    """One job's verdict, in order: ``unread``, ``no green``, ``RAISE`` (the bound
    is under the rule's), ``CUT`` (a cell was cancelled at the present bound),
    ``thin`` (fewer green runs than asked), ``ok``."""
    if unread < 0:
        return "unread"
    if needed is None:
        return "no green"
    if bound < needed:
        return "RAISE"
    if cut_max is not None and cut_max >= bound - 0.5:
        return "CUT"
    if green_runs < runs:
        return "thin"
    return "ok"


def minutes(started: str | None, completed: str | None) -> float | None:
    if not started or not completed:
        return None
    try:
        a = datetime.fromisoformat(started.replace("Z", "+00:00"))
        b = datetime.fromisoformat(completed.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (b - a).total_seconds() / 60.0


def gh_json(args: list[str], repo: str | None) -> object:
    """One ``gh`` call, parsed; None on any failure (the caller says unread)."""
    cmd = ["gh", *args] + (["-R", repo] if repo else [])
    try:
        result = run_bounded(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=GH_TIMEOUT, cwd=str(REPO_ROOT))
    except Exception:  # noqa: BLE001 -- a census: a gh that cannot run reads nothing
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout or "")
    except ValueError:
        return None


def measure(workflow: str, jobs: dict[str, dict], runs: int, scan: int, repo: str | None) -> dict:
    """Per job of one workflow, newest runs first: the green minutes of every
    cell of its last ``runs`` runs holding a green cell (a matrix job's four
    cells are one run, never four), and the cancelled cells in those same runs
    that ran longer than the job's worst green, which reads as a cut whatever
    the bound was when it ran. A job stops counting at ``runs`` green runs; the
    scan stops when every job has, or at ``scan`` runs."""
    listed = gh_json(["run", "list", "--workflow", workflow, "--limit", str(scan),
                      "--json", "databaseId,status"], repo)
    out = {j: {"greens": [], "green_runs": 0, "cancels": [], "cuts": 0, "cut_max": None, "unread": 0}
           for j in jobs}
    if not isinstance(listed, list):
        for j in out:
            out[j]["unread"] = -1
        return out
    for run in listed:
        if run.get("status") != "completed":
            continue
        if all(v["green_runs"] >= runs for v in out.values()):
            break
        view = gh_json(["run", "view", str(run.get("databaseId")), "--json", "jobs"], repo)
        if not isinstance(view, dict):
            for v in out.values():
                v["unread"] += 1
            continue
        cells: dict[str, list[tuple[str, float]]] = {}
        for job in view.get("jobs") or []:
            job_id = job_for(str(job.get("name") or ""), jobs)
            took = minutes(job.get("startedAt"), job.get("completedAt"))
            if job_id is not None and took is not None:
                cells.setdefault(job_id, []).append((str(job.get("conclusion") or ""), took))
        for job_id, seen in cells.items():
            slot = out[job_id]
            if slot["green_runs"] >= runs:
                continue
            greens = [took for conclusion, took in seen if conclusion == "success"]
            slot["cancels"].extend(took for conclusion, took in seen if conclusion == "cancelled")
            if greens:
                slot["greens"].extend(greens)
                slot["green_runs"] += 1
    for slot in out.values():
        worst = max(slot["greens"], default=None)
        cut = [took for took in slot["cancels"] if worst is not None and took > worst]
        slot["cuts"] = len(cut)
        slot["cut_max"] = round(max(cut), 1) if cut else None
    return out


def _ascii(text: str) -> str:
    """7-bit ASCII for a printed name: a redirected Windows stdout cannot take more."""
    return text.encode("ascii", "replace").decode("ascii")


def _dash(value: object) -> str:
    return "-" if value is None else str(value)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=20, help="green runs read per job (default 20)")
    ap.add_argument("--scan", type=int, default=60, help="runs listed per workflow at most (default 60)")
    ap.add_argument("--factor", type=float, default=1.5, help="the bound asked for, times the worst (default 1.5)")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = []
    files = serial_files()
    mark: float | None = None  # read once, on the first job that runs the serial files
    # A dot-name is a sidecar (macOS writes ._name.yml beside a copied file), never a workflow.
    for path in sorted(p for p in WORKFLOWS.glob("*.y*ml") if not p.name.startswith(".")):
        jobs = read_bounds(path.read_text(encoding="utf-8"))
        if not jobs:
            continue
        measured = measure(path.name, jobs, args.runs, args.scan, args.repo)
        for job_id, meta in jobs.items():
            m = measured[job_id]
            greens = m["greens"]
            worst = max(greens) if greens else None
            serial = job_runs_the_serial_files(meta["lines"], files)
            if serial and mark is None:
                mark = max((s for _f, _l, s in serial_marks(files)), default=0.0)
            floor = (serial_floor(worst, mark) if serial and worst is not None and mark is not None
                     and mark != float("inf") else None)
            needed = needed_bound(worst, args.factor) if worst is not None else None
            row = {
                "workflow": path.name, "job": job_id, "bound": meta["bound"],
                "green_runs": m["green_runs"], "greens": len(greens),
                "worst": round(worst, 1) if worst is not None else None,
                "median": round(statistics.median(greens), 1) if greens else None,
                "serial": serial, "floor": floor,
                "needed": max(needed, floor or 0) if needed is not None else None,
                "cuts": m["cuts"], "cut_max": m["cut_max"], "unread": m["unread"],
            }
            row["verdict"] = verdict(meta["bound"], row["needed"], m["cut_max"], m["green_runs"],
                                     args.runs, m["unread"])
            rows.append(row)

    if args.json:
        print(json.dumps({"runs": args.runs, "factor": args.factor, "serial_mark_s": mark, "rows": rows},
                         indent=1))
        return 0
    print(f"CI job bounds against the worst cell of each job's last {args.runs} green runs "
          f"(rule: {args.factor}x, up to 5 min; cuts: cancelled cells longer than that worst)")
    if mark is not None:
        print(f"floor, on a job that runs the serial files (*): their worst timeout mark, "
              f"{mark:.0f} s, plus the worst, up to 5 min; needed is the larger")
    print(f"{'workflow / job':<44} {'bound':>5} {'runs':>4} {'cells':>5} {'worst':>6} {'median':>6} "
          f"{'floor':>5} {'needed':>6} {'cuts':>4} {'cutmax':>6}  verdict")
    for r in rows:
        name = r["workflow"] + " / " + r["job"] + (" *" if r["serial"] else "")
        print(f"{_ascii(name):<44} {r['bound']:>5} {r['green_runs']:>4} {r['greens']:>5} "
              f"{_dash(r['worst']):>6} {_dash(r['median']):>6} {_dash(r['floor']):>5} {_dash(r['needed']):>6} "
              f"{r['cuts']:>4} {_dash(r['cut_max']):>6}  {r['verdict']}")
    if mark == float("inf"):
        print("a timeout mark in the serial files the parser cannot read: no floor was judged")
    raise_n = sum(1 for r in rows if r["verdict"] == "RAISE")
    cut_n = sum(1 for r in rows if r["verdict"] == "CUT")
    print(f"{raise_n} of {len(rows)} bounded jobs under the rule, {cut_n} cut at their present bound")
    return 0


if __name__ == "__main__":
    sys.exit(main())
