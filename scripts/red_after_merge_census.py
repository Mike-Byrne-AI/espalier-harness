"""Which checks went red after a merge, on which merge, and when the record could have said so.

The instrument behind the post-merge verdict module (``tools/cc/_post_merge.py``,
loaded here by path and never copied): it reads the merged pull requests of a
window, replays the module's ownership and transition rule as of a wall-clock
instant (``--at``: a run that started after it is dropped, one that finished
after it reads as still running), and prints, per check name, the verdict, the
merge it has held since, the leg's finish, and every change in merge order.
``--classify`` reads each red run's failing node ids from its job log and
buckets them by the ledger rows that name the failing file, so the share of
red legs that are known noise is a figure, never a reading.

    python3 scripts/red_after_merge_census.py --since 2026-10-18 --at 2026-10-18T14:15:00Z
    python3 scripts/red_after_merge_census.py --limit 60 --classify --max-logs 40
    python3 scripts/red_after_merge_census.py --json

Self-host tooling (``scripts/`` is not deployed by ``init``). Needs ``gh``
signed in; ``--repo OWNER/NAME`` when run outside the checkout.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    """A module of this checkout loaded by path, never an installed engine's."""
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_pm = _load("_post_merge_for_red_after_merge_census", "tools/cc/_post_merge.py")
run_bounded = _load("_json_safe_for_red_after_merge_census", "tools/cc/_json_safe.py").run_bounded
#: The ledger's row directory, read from the record loader's one constant (never a
#: copy of the name here: tests/test_record_fragments.py holds every reader to it).
LEDGER_DIR = REPO_ROOT / _load("_record_fragments_for_red_after_merge_census",
                               "tools/cc/_record_fragments.py").LEDGER_DIR

GH_TIMEOUT = 60.0
LOG_TIMEOUT = 180.0
NODE_ID_RE = re.compile(r"\b(?:FAILED|ERROR)\s+(tests/[\w./-]+\.py(?:::\S+)?)")   # the id ends at whitespace
RUN_JOB_RE = re.compile(r"/actions/runs/(\d+)/job/(\d+)")


# ---------------------------------------------------------------- gh reads --

def gh_json(args: list[str], repo: str | None = None) -> object:
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


def gh_text(args: list[str], repo: str | None = None, timeout: float = LOG_TIMEOUT) -> str:
    cmd = ["gh", *args] + (["-R", repo] if repo else [])
    try:
        result = run_bounded(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=timeout, cwd=str(REPO_ROOT))
    except Exception:  # noqa: BLE001 -- a census: an unreadable log is an unclassified leg
        return ""
    return result.stdout or ""


def read_merged(limit: int, since: str | None, repo: str | None) -> list[dict]:
    """The merged rows, newest first as ``gh`` lists them, cut to those merged
    on or after ``since`` (a date, read as its first instant) when given."""
    rows = _pm.read_merged(REPO_ROOT, limit, gh=lambda a: gh_json(a, repo))
    if since:
        floor = since if "T" in since else f"{since}T00:00:00Z"
        oldest = min((str(r.get("mergedAt") or "") for r in rows), default="")
        if len(rows) >= limit and oldest > floor:
            print(f"note: --limit {limit} stopped at {oldest}, after --since {floor}: the window is cut short; "
                  "raise --limit to reach it", file=sys.stderr)
        rows = [r for r in rows if str(r.get("mergedAt") or "") >= floor]
    return rows


# ---------------------------------------------------------------- classify --

def run_and_job(row: dict) -> tuple[str, str] | None:
    """The run and job ids a rollup row's ``detailsUrl`` names, or None."""
    m = RUN_JOB_RE.search(str(row.get("detailsUrl") or ""))
    return (m.group(1), m.group(2)) if m else None


def failing_node_ids(log: str) -> list[str]:
    """The node ids a failed job's log names in pytest's short test summary
    (``FAILED tests/x.py::T::t``, ``ERROR tests/x.py::T::t``), each once, in
    order; the ``ERROR at setup of T.t`` header above a traceback names no file
    and is not read."""
    seen: list[str] = []
    for m in NODE_ID_RE.finditer(log):
        node = m.group(1)
        if node not in seen:
            seen.append(node)
    return seen


def ledger_files(ledger_dir: Path = LEDGER_DIR) -> dict[str, list[str]]:
    """Which ledger rows name which test files: ``tests/<name>.py`` mentions in
    each row's text, keyed by the file, the row ids as their file stems."""
    out: dict[str, list[str]] = {}
    if not ledger_dir.is_dir():
        return out
    for path in sorted(ledger_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for file in set(re.findall(r"tests/[\w./-]+\.py", text)):
            out.setdefault(file, []).append(path.stem)
    return out


def classify(merged: list[dict], *, repo: str | None, max_logs: int,
             read_log=None, known: dict[str, list[str]] | None = None) -> dict:
    """Per red run among the merged rows' latest runs (newest merge first, at
    most ``max_logs`` logs read): its failing node ids, each bucketed by the
    ledger rows that name its file, and the leg's verdict: ``known`` when every
    failing file is named by a row, ``unclassified`` otherwise, ``unread`` when
    the log gave no node id."""
    reader = read_log or (lambda run, job: gh_text(["run", "view", run, "--job", job, "--log-failed"], repo))
    rows_by_file = ledger_files() if known is None else known
    legs: list[dict] = []
    read = 0
    for pr in _pm.by_merge_desc(merged):
        rollup = pr.get("statusCheckRollup")
        for row in _pm.latest_run_per_check(rollup if isinstance(rollup, list) else []):
            if _pm.check_outcome(row) != "red":
                continue
            if str(row.get("conclusion") or "").upper() in _pm.NO_VERDICT:
                continue
            leg = {"pr": pr.get("number"), "check": _pm.ascii_(row.get("name") or row.get("context") or ""),
                   "node_ids": [], "buckets": {}, "verdict": "unread"}
            ids = run_and_job(row)
            if ids is not None and read < max_logs:
                read += 1
                nodes = failing_node_ids(reader(*ids))
                leg["node_ids"] = nodes
                buckets: dict[str, list[str]] = {}
                for node in nodes:
                    file = node.split("::", 1)[0]
                    buckets[node] = rows_by_file.get(file, [])
                leg["buckets"] = buckets
                if nodes:
                    leg["verdict"] = "known" if all(buckets[n] for n in nodes) else "unclassified"
            legs.append(leg)
    counted = [leg for leg in legs if leg["verdict"] != "unread"]
    known_legs = sum(1 for leg in counted if leg["verdict"] == "known")
    # The base rate the file-level bucket carries: the share of test files any
    # ledger row names at all. A known share near it measures the ledger's
    # reach, not the legs' noise, and the reader must see both.
    test_files = sorted(p.as_posix() for p in (REPO_ROOT / "tests").glob("test_*.py")) if (REPO_ROOT / "tests").is_dir() else []
    named = sum(1 for f in test_files if f.split("/tests/", 1)[-1].join(["tests/", ""]) in rows_by_file
                or f"tests/{Path(f).name}" in rows_by_file)
    return {"legs": legs, "read": len(counted), "known": known_legs,
            "known_share": (known_legs / len(counted)) if counted else None,
            "files_named_by_a_row": named, "test_files": len(test_files)}


# ------------------------------------------------------------------ render --

def render(checks: dict, merged: list[dict], *, at: str | None, classified: dict | None) -> str:
    numbers = [pr.get("number") for pr in merged if isinstance(pr.get("number"), int)]
    oldest = _pm.oldest_merge(merged)
    out = [f"merged pull requests read: {len(merged)}"
           + (f" (#{oldest} oldest merge to #{max(numbers)})" if numbers else "")
           + (f"; replayed at {at}" if at else "")]
    for line in _pm.board_lines(checks, window=len(merged), oldest=oldest):
        out.append(line)
    for name in sorted(checks):
        c = checks[name]
        if not c["changes"] and not c["running"]:
            continue
        out.append(f"{c['name']}:")
        for ch in c["changes"]:
            frm = f" (from #{ch['from_pr']} {ch['from_verdict']})" if ch["from_pr"] is not None else ""
            out.append(f"  #{ch['pr']} {ch['verdict']}, merged {ch['merged_at'] or '?'}, run "
                       f"{ch['started_at'] or '?'} -> {ch['completed_at'] or 'running'}{frm}")
        if c["running"]:
            out.append(f"  running on: {', '.join(f'#{n}' for n in c['running'])}")
    if classified is not None:
        share = classified["known_share"]
        out.append(f"red legs with a log read: {classified['read']}; every failure a ledgered class: "
                   f"{classified['known']}" + (f" ({share:.0%})" if share is not None else "")
                   + f"; base rate: {classified['files_named_by_a_row']} of {classified['test_files']} test files are "
                     "named by some ledger row, so a known share near that measures the ledger's reach, not noise")
        for leg in classified["legs"]:
            out.append(f"  #{leg['pr']} {leg['check']}: {leg['verdict']}"
                       + (f" -- {', '.join(leg['node_ids'][:4])}" if leg["node_ids"] else ""))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", default=None, help="a date (YYYY-MM-DD) or ISO instant: merges on or after it")
    ap.add_argument("--limit", type=int, default=40, help="how many merged pull requests to read (default 40)")
    ap.add_argument("--at", default=None, help="replay the record as it stood at this ISO instant")
    ap.add_argument("--classify", action="store_true", help="read each red run's failing node ids and bucket them")
    ap.add_argument("--max-logs", type=int, default=30, help="the most job logs --classify reads (default 30)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--repo", default=None, help="OWNER/NAME for gh, when run outside the checkout")
    args = ap.parse_args(argv)
    merged = read_merged(args.limit, args.since, args.repo)
    if not merged:
        print("no merged pull requests read (gh signed in? --repo?)", file=sys.stderr)
        return 2
    checks = _pm.transitions(merged, at=args.at)
    classified = classify(merged, repo=args.repo, max_logs=args.max_logs) if args.classify else None
    if args.json:
        print(json.dumps({"merged": [pr.get("number") for pr in merged], "at": args.at,
                          "checks": _pm.summary(checks), "classified": classified}, indent=2, sort_keys=True))
        return 0
    print(render(checks, merged, at=args.at, classified=classified))
    return 0


if __name__ == "__main__":
    sys.exit(main())
