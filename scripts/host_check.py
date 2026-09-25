#!/usr/bin/env python3
"""Run Espalier's own suite and guard benches on this host and deliver the
results to the repository's remote as one commit -- nothing to paste.

This is the harness testing itself: the pytest suite that CI's portability
cell runs (``-m "not heavy_e2e"``), ``bench/powershell_guard_rehearsal.py``
(written to be run on a Windows box, where its PowerShell verdicts meet a real
shell), ``bench/guard_row_probe.py`` (the Bash-tool, home-directory and
project-root-shape rows the walks recorded, on the rehearsal's fixture) and
``bench/powershell_reachability_differential.py`` under whichever
PowerShell the host has -- and, on Windows, under Windows PowerShell 5.1 as
well when ``pwsh`` won the PATH lookup. Every step's output lands under
``reports/host-check/<label>/`` (gitignored, like the rest of ``reports/``),
with ``facts.json`` (what ran, where, on which head) and ``SUMMARY.md``
beside it.

WHY A COMMIT AND NOT A PASTE. GitHub Actions is metered on a private
repository and the cross-OS cells are the expensive ones; a second machine the
operator already owns answers the same question for nothing, but only if its
answer travels without a hand in the loop. So a run ends by writing the
results into a commit whose tree is HEAD's plus the report directory --
through a temporary index, so the working branch, the working tree and the
real index are untouched -- and pushing that single commit to
``refs/heads/host-check/<label>``. No workflow triggers on that ref. On the
other machine ``--read <label>`` (or ``--read --latest``) fetches it, writes
the files under the same path there and prints the summary.

Usage::

    python scripts/host_check.py                  # run everything, push
    python scripts/host_check.py --no-push        # run, keep the results local
    python scripts/host_check.py --skip pytest    # a bench-only run
    python scripts/host_check.py --read --latest  # on the reading side
    python scripts/host_check.py --list           # host-check refs on origin

The child environment drops ``ESPALIER_MAINTENANCE_MODE`` (CI's cell runs
without it) and forces UTF-8 on the children's stdout, because the benches
print non-ASCII markers and a Windows console default is cp1252. Stdlib only;
paths resolve from this file, so it runs from any cwd.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = REPO_ROOT / "reports" / "host-check"
REF_PREFIX = "refs/heads/host-check/"
_STAMP_RE = re.compile(r"(\d{8}-\d{4})")


def _git(*args: str, cwd: Path = REPO_ROOT, env: dict[str, str] | None = None,
         timeout: int = 300) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({result.returncode}): "
            f"{result.stderr.strip()[:400]}")
    return result.stdout.strip()


def windows_powershell() -> str | None:
    """Windows PowerShell 5.1 by its fixed path, or None off Windows."""
    root = os.environ.get("SystemRoot")
    if not root:
        return None
    exe = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(exe) if exe.exists() else None


def host_facts(repo_root: Path = REPO_ROOT) -> dict:
    """What ran where: the header of every report and the source of the label."""
    now = dt.datetime.now(dt.timezone.utc)
    return {
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "head": _git("rev-parse", "HEAD", cwd=repo_root),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo_root),
        "dirty": bool(_git("status", "--porcelain", "--untracked-files=no",
                           cwd=repo_root)),
        "tools": {name: shutil.which(name)
                  for name in ("pwsh", "powershell", "bash", "git")},
        "windows_powershell": windows_powershell(),
        "espalier_pwsh_override": os.environ.get("ESPALIER_PWSH"),
        "maintenance_mode_in_parent_env": "ESPALIER_MAINTENANCE_MODE" in os.environ,
        "utc": now.isoformat(timespec="seconds"),
        "stamp": now.strftime("%Y%m%d-%H%M"),
    }


def make_label(facts: dict) -> str:
    """``<host>-<YYYYMMDD-HHMM>-<sha7>``: sortable by time, readable by eye."""
    host = re.sub(r"[^A-Za-z0-9]+", "-", facts["host"]).strip("-").lower()[:24]
    return f"{host or 'host'}-{facts['stamp']}-{facts['head'][:7]}"


def latest_label(labels: list[str]) -> str:
    """The newest by its stamp, whatever the host name sorts like."""
    def stamp(label: str) -> str:
        hit = _STAMP_RE.search(label)
        return hit.group(1) if hit else ""
    return max(labels, key=stamp)


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "ESPALIER_MAINTENANCE_MODE"}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if extra:
        env.update(extra)
    return env


def plan_steps(facts: dict, skip: set[str] | None = None) -> list[dict]:
    """The steps in order. A step whose precondition the host lacks is
    planned with a ``skip`` reason and still appears in the report, so an
    absent PowerShell reads as absent and never as a pass."""
    skip = skip or set()
    py = sys.executable
    has_ps = bool(facts["tools"]["pwsh"] or facts["tools"]["powershell"]
                  or facts["espalier_pwsh_override"])
    steps = [
        {"name": "pytest",
         "argv": [py, "-m", "pytest", "-q", "-m", "not heavy_e2e", "-p", "no:cacheprovider"],
         "env": child_env(), "skip": None, "timeout": 3 * 3600},
        # `--root-shape all` is the default; spelled so the argv states the
        # workload the budget was sized for (three shapes: ~900 hook spawns, at
        # roughly a second each on a Windows Python).
        {"name": "rehearsal",
         "argv": [py, "bench/powershell_guard_rehearsal.py", "--repo-root", ".",
                  "--root-shape", "all"],
         "env": child_env(), "skip": None, "timeout": 5400},
        {"name": "row-probe",
         "argv": [py, "bench/guard_row_probe.py", "--repo-root", "."],
         "env": child_env(), "skip": None, "timeout": 900},
        {"name": "pwsh-differential",
         "argv": [py, "bench/powershell_reachability_differential.py"],
         "env": child_env(), "skip": None if has_ps else "no PowerShell on this host",
         "timeout": 3600},
    ]
    wps = facts["windows_powershell"]
    if wps and facts["tools"]["pwsh"] and not facts["espalier_pwsh_override"]:
        # pwsh 7 won the PATH lookup; drive Windows PowerShell 5.1 as well,
        # the interpreter the differential's own docstring names as the one
        # a Windows run can answer for.
        steps.append({"name": "ps51-differential",
                      "argv": [py, "bench/powershell_reachability_differential.py"],
                      "env": child_env({"ESPALIER_PWSH": wps}), "skip": None,
                      "timeout": 3600})
    for step in steps:
        if step["name"] in skip:
            step["skip"] = "skipped on request"
    return steps


def run_step(step: dict, out_dir: Path, repo_root: Path = REPO_ROOT) -> dict:
    log = out_dir / f"{step['name']}.txt"
    if step["skip"]:
        log.write_text(f"skipped: {step['skip']}\n", encoding="utf-8")
        return {"name": step["name"], "rc": None, "skipped": step["skip"],
                "seconds": 0.0, "tail": [f"skipped: {step['skip']}"]}
    print(f"[host-check] {step['name']}: {' '.join(step['argv'])}", flush=True)
    start = time.monotonic()
    with log.open("w", encoding="utf-8") as fh:
        fh.write("$ " + " ".join(step["argv"]) + "\n\n")
        fh.flush()
        try:
            # subprocess-contract: ok planned-step-argv-is-pytest-or-one-of-the-three-benches-see-plan_steps
            proc = subprocess.run(step["argv"], cwd=repo_root, stdout=fh,
                                  stderr=subprocess.STDOUT, env=step["env"],
                                  timeout=step["timeout"])
            rc: int | None = proc.returncode
        except subprocess.TimeoutExpired:
            rc = None
            fh.write(f"\n[host-check] timed out after {step['timeout']} s\n")
    seconds = round(time.monotonic() - start, 1)
    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
    print(f"[host-check] {step['name']}: rc={rc} in {seconds}s", flush=True)
    return {"name": step["name"], "rc": rc, "skipped": None,
            "seconds": seconds, "tail": tail}


def write_summary(out_dir: Path, facts: dict, results: list[dict]) -> str:
    tools = ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in facts["tools"].items())
    lines = [
        f"# host-check {facts['label']}",
        "",
        f"- host: {facts['host']} ({facts['platform']}), python {facts['python']}",
        f"- head: {facts['head'][:10]} on {facts['branch']}"
        + (" (dirty tree)" if facts["dirty"] else ""),
        f"- tools: {tools}; windows powershell: "
        f"{'yes' if facts['windows_powershell'] else 'no'}",
        f"- run at: {facts['utc']}",
        "",
        "| step | rc | seconds | last line |",
        "|---|---|---|---|",
    ]
    for r in results:
        last = (r["tail"][-1] if r["tail"] else "")[:100].replace("|", "\\|")
        rc = "skipped" if r["skipped"] else ("timeout" if r["rc"] is None else str(r["rc"]))
        lines.append(f"| {r['name']} | {rc} | {r['seconds']} | {last} |")
    for r in results:
        lines += ["", f"## {r['name']}", "```", *r["tail"], "```"]
    text = "\n".join(lines) + "\n"
    (out_dir / "SUMMARY.md").write_text(text, encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps({"facts": facts, "results": results}, indent=1), encoding="utf-8")
    return text


def publish(label: str, out_dir: Path, message: str, repo_root: Path = REPO_ROOT,
            remote: str = "origin") -> str:
    """Commit HEAD's tree plus the report directory through a temporary index
    and push that one commit to ``refs/heads/host-check/<label>``. The working
    branch, the working tree and the real index are not touched; an identity
    is supplied when the host has none configured."""
    rel = out_dir.relative_to(repo_root).as_posix()
    env = dict(os.environ)
    if not subprocess.run(["git", "config", "user.name"], cwd=repo_root,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60).stdout.strip():
        for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
            env[key] = "host-check"
        for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
            env[key] = "host-check@espalier.local"
    with tempfile.TemporaryDirectory() as td:
        env["GIT_INDEX_FILE"] = str(Path(td) / "index")
        _git("read-tree", "HEAD", cwd=repo_root, env=env)
        _git("add", "-f", "--", rel, cwd=repo_root, env=env)
        tree = _git("write-tree", cwd=repo_root, env=env)
        commit = _git("commit-tree", tree, "-p", "HEAD", "-m", message,
                      cwd=repo_root, env=env)
    _git("push", remote, f"{commit}:{REF_PREFIX}{label}", cwd=repo_root, timeout=600)
    return commit


def list_labels(repo_root: Path = REPO_ROOT, remote: str = "origin") -> list[str]:
    out = _git("ls-remote", "--heads", remote, "host-check/*", cwd=repo_root, timeout=120)
    return sorted(line.split("\t", 1)[1][len(REF_PREFIX):]
                  for line in out.splitlines() if "\t" in line)


def read(label: str, repo_root: Path = REPO_ROOT, remote: str = "origin") -> str:
    """Fetch one host-check ref and write its report directory here."""
    _git("fetch", remote, REF_PREFIX + label, cwd=repo_root, timeout=600)
    rel = f"reports/host-check/{label}"
    files = _git("ls-tree", "-r", "--name-only", "FETCH_HEAD", "--", rel,
                 cwd=repo_root).splitlines()
    if not files:
        raise RuntimeError(f"{REF_PREFIX}{label} carries no {rel}/")
    for name in files:
        data = subprocess.run(["git", "show", f"FETCH_HEAD:{name}"], cwd=repo_root,
                              capture_output=True, timeout=120, check=True).stdout
        target = repo_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return (repo_root / rel / "SUMMARY.md").read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--read", nargs="?", const="", metavar="LABEL",
                        help="fetch a run's report from origin and print its summary")
    parser.add_argument("--latest", action="store_true",
                        help="with --read: the newest label on origin")
    parser.add_argument("--list", action="store_true",
                        help="list the host-check labels on origin")
    parser.add_argument("--no-push", action="store_true",
                        help="run and write the report; do not publish it")
    parser.add_argument("--skip", action="append", default=[], metavar="STEP",
                        help="skip a step by name (repeatable)")
    parser.add_argument("--message", default=None,
                        help="commit message for the published report")
    args = parser.parse_args(argv)

    if args.list:
        for label in list_labels():
            print(label)
        return 0
    if args.read is not None:
        label = args.read
        if args.latest or not label:
            labels = list_labels()
            if not labels:
                print("no host-check refs on origin")
                return 1
            label = latest_label(labels)
        print(read(label), end="")
        return 0

    facts = host_facts()
    facts["label"] = make_label(facts)
    out_dir = REPORT_ROOT / facts["label"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "facts.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")
    results = [run_step(step, out_dir) for step in plan_steps(facts, set(args.skip))]
    print(write_summary(out_dir, facts, results), end="")
    failed = [r["name"] for r in results if not r["skipped"] and r["rc"] != 0]
    if not args.no_push:
        rcs = ", ".join(f"{r['name']}={'skip' if r['skipped'] else r['rc']}" for r in results)
        commit = publish(facts["label"], out_dir,
                         args.message or f"host-check: {facts['label']} ({rcs})")
        print(f"[host-check] published {commit[:10]} as {REF_PREFIX}{facts['label']}")
        print(f"[host-check] read it elsewhere with: python scripts/host_check.py "
              f"--read {facts['label']}")
    else:
        print(f"[host-check] written to {out_dir} (not published)")
    if failed:
        print(f"[host-check] steps with a non-zero exit: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
