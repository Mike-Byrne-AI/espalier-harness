"""Each CI job's ``timeout-minutes`` against its measured worst green run.

DEF-1178 set every suite-running job's bound above its worst case over its
last 20 runs (2026-10-16); the suite grew and post-merge's 48.2-minute worst
became 70.7, so its 75-minute bound began cutting runs with no verdict, and
nothing said so until runs were lost. This census is the re-measure as one
command: for every job in ``.github/workflows/`` that declares a job-level
``timeout-minutes``, it reads the job's last ``--runs`` green runs through
``gh`` (every matrix cell counts toward its job), and prints the bound, the
worst and median green, the bound the rule asks for (``--factor`` times the
worst, rounded up to five minutes) and the runs cut at the bound (cancelled at
or past it, which read no verdict). A job whose bound is under the rule's is
marked ``RAISE``.

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
_JOB_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
_NAME_RE = re.compile(r"^    name:\s*(.+?)\s*$")
_BOUND_RE = re.compile(r"^    timeout-minutes:\s*(\d+)\s*$")
_CELL_SUFFIX_RE = re.compile(r" \([^()]*\)$")


def read_bounds(text: str) -> dict[str, dict]:
    """Each job under ``jobs:`` that declares a job-level ``timeout-minutes``:
    ``{job_id: {"bound": minutes, "name": its literal name or None}}``. A name
    that is an expression (``${{ ... }}``) reads as None, so the job is matched
    by its id. Two-space job keys and four-space job fields, the layout every
    workflow here uses; a step's ``timeout-minutes`` (deeper) is not a job's."""
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
            jobs[job] = {"bound": None, "name": None}
            continue
        if job is None:
            continue
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
    """Green minutes and cut count per job of one workflow, newest runs first,
    until every job holds ``runs`` greens or ``scan`` runs were read."""
    listed = gh_json(["run", "list", "--workflow", workflow, "--limit", str(scan),
                      "--json", "databaseId,status"], repo)
    out = {j: {"greens": [], "cuts": 0, "unread": 0} for j in jobs}
    if not isinstance(listed, list):
        for j in out:
            out[j]["unread"] = -1
        return out
    for run in listed:
        if run.get("status") != "completed":
            continue
        if all(len(v["greens"]) >= runs for v in out.values()):
            break
        view = gh_json(["run", "view", str(run.get("databaseId")), "--json", "jobs"], repo)
        if not isinstance(view, dict):
            for v in out.values():
                v["unread"] += 1
            continue
        for job in view.get("jobs") or []:
            job_id = job_for(str(job.get("name") or ""), jobs)
            if job_id is None:
                continue
            took = minutes(job.get("startedAt"), job.get("completedAt"))
            if took is None:
                continue
            slot = out[job_id]
            if job.get("conclusion") == "success" and len(slot["greens"]) < runs:
                slot["greens"].append(took)
            elif job.get("conclusion") == "cancelled" and took >= jobs[job_id]["bound"] - 0.5:
                slot["cuts"] += 1
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=20, help="green runs read per job (default 20)")
    ap.add_argument("--scan", type=int, default=60, help="runs listed per workflow at most (default 60)")
    ap.add_argument("--factor", type=float, default=1.5, help="the bound asked for, times the worst (default 1.5)")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        jobs = read_bounds(path.read_text(encoding="utf-8"))
        if not jobs:
            continue
        measured = measure(path.name, jobs, args.runs, args.scan, args.repo)
        for job_id, meta in jobs.items():
            m = measured[job_id]
            greens = m["greens"]
            worst = max(greens) if greens else None
            row = {
                "workflow": path.name, "job": job_id, "bound": meta["bound"], "greens": len(greens),
                "worst": round(worst, 1) if worst is not None else None,
                "median": round(statistics.median(greens), 1) if greens else None,
                "needed": needed_bound(worst, args.factor) if worst is not None else None,
                "cuts": m["cuts"], "unread": m["unread"],
            }
            row["verdict"] = ("unread" if m["unread"] < 0 else "no green" if worst is None
                              else "RAISE" if meta["bound"] < row["needed"] else "ok")
            rows.append(row)

    if args.json:
        print(json.dumps({"runs": args.runs, "factor": args.factor, "rows": rows}, indent=1))
        return 0
    print(f"CI job bounds against the worst of each job's last {args.runs} green runs (rule: {args.factor}x, up to 5 min)")
    print(f"{'workflow / job':<44} {'bound':>5} {'greens':>6} {'worst':>6} {'median':>6} {'needed':>6} {'cuts':>4}  verdict")
    for r in rows:
        fmt = lambda v: "-" if v is None else str(v)  # noqa: E731
        print(f"{r['workflow'] + ' / ' + r['job']:<44} {r['bound']:>5} {r['greens']:>6} {fmt(r['worst']):>6} "
              f"{fmt(r['median']):>6} {fmt(r['needed']):>6} {r['cuts']:>4}  {r['verdict']}")
    raise_n = sum(1 for r in rows if r["verdict"] == "RAISE")
    print(f"{raise_n} of {len(rows)} bounded jobs under the rule")
    return 0


if __name__ == "__main__":
    sys.exit(main())
