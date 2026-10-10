#!/usr/bin/env python3
"""What two lanes merged in turn cost: catch-ups, extra CI runs, and the conflicts behind them.

Four reports over the last ``--prs`` merged pull requests (the first three run
by default; ``stale`` runs when named):

``catch-ups``
    Per pull request, the catch-up merges of the base into its lane (a commit
    headed ``Merge branch 'main'`` or ``Merge remote-tracking branch
    'origin/main'``), and the ``test.yml`` runs and run attempts on its head
    branch. A lane merged with no catch-up costs one run; every catch-up under
    the up-to-date rule costs another.

``conflicts``
    Each catch-up merge replayed with ``git merge-tree`` on its two parents in a
    throwaway ``git clone --shared`` whose own ``info/attributes`` turns every
    merge driver in ``.gitattributes`` back into a plain text merge. That is the
    merge GitHub performs (it honours no driver), so a file the local merge
    resolves through ``merge=union`` still counts here; measured 2026-10-09, the
    changelog went from 0 conflicts to 10 of 30 once the driver was off. The
    clone is the only place the override is written: ``info/attributes`` of a
    linked worktree is the shared repository's, read by every checkout.

``blocks``
    For the record files, each conflict block of each replay classed by the
    lines it spans: the ledger's derived counts (its headline, class index and
    section headings), member rows, the id index, or other; the probes roster's
    ``_count`` or its entries. The class decides the remedy: a derived count two
    lanes both recompute leaves the conflicted lines once it stops being
    stored, while colliding rows need a different shape. The classifier reads
    line shapes, so a block it calls ``other`` is unread, not safe.

``stale``
    With the up-to-date rule off, a pull request merges on the CI that tested
    it with the base as of its last push. Per pull request: did the base move
    between that CI run and the merge, and was the move near its files (a path
    both changed, or a Python import between a file each changed)? The read is
    ``tools/cc/_merge_rules.py::stale_base``, the one ``ship.py status`` and
    the board run, replayed on the merge commit's parents: the first is the
    base the pull request landed on, the second its head. The stale-base
    advisory's refutation line is this count over 20 ships: re-raise when it
    is near on more than half (the up-to-date rule by another name). Measured
    2026-10-10 over 40 merges: moved on 1, near on 1.

Self-host tooling (``scripts/`` is not deployed). Stdlib, ``git`` and ``gh``,
spawned through ``tools/cc/ship.py::run`` (the ship driver's one runner: PATH
resolution, no shell, a timeout, a named refusal) rather than a second runner of
its own, which would spend a subprocess-contract pragma for a duplicate.
``--prs-json`` reads the pull-request list from a file instead of ``gh``, for an
offline re-run of the same window.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
CATCH_UP = re.compile(r"^Merge (remote-tracking )?branch '(origin/)?main'")
LEDGER = "task-packs/FORWARD_LEDGER.md"
PROBES = "task-packs/LEDGER_PROBES.json"
RECORD_FILES = ("ESPALIER_MEMORY.md", LEDGER, PROBES)
REPORTS = ("catch-ups", "conflicts", "blocks", "stale")
DEFAULT_REPORTS = REPORTS[:3]

#: ``runner(argv, cwd=...) -> (returncode, stdout, stderr)``: ship.py's ``run``.
Runner = Callable[..., "tuple[int, str, str]"]


def _ship_runner() -> Runner:
    """The ship driver's runner, loaded by path (``tools/cc`` is standalone)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_mcc_ship", ROOT / "tools" / "cc" / "ship.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run


def _merge_rules():
    """``tools/cc/_merge_rules.py`` by path: the stale-base read the board and
    ``ship.py status`` run, so this census replays the same rule."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_mcc_merge_rules", ROOT / "tools" / "cc" / "_merge_rules.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def merged_prs(n: int, runner: Runner, root: Path = ROOT) -> list[dict]:
    rc, out, err = runner(["gh", "pr", "list", "--state", "merged", "--limit", str(n),
                           "--json", "number,headRefName,commits,mergeCommit"], cwd=str(root))
    if rc != 0:
        raise SystemExit(f"merge_cost_census: gh pr list failed: {err.strip()}")
    return json.loads(out or "[]")


def catch_up_commits(pr: dict) -> list[str]:
    """The oids of a pull request's catch-up merges of the base."""
    return [c["oid"] for c in pr.get("commits", []) if CATCH_UP.match(c.get("messageHeadline", ""))]


def catch_up_rows(prs: list[dict], runner: Runner, root: Path = ROOT) -> list[dict]:
    rows = []
    for pr in prs:
        rc, out, _err = runner(["gh", "run", "list", "--workflow", "test.yml", "--branch",
                                pr["headRefName"], "--limit", "50", "--json", "conclusion,attempt"],
                               cwd=str(root))
        runs = json.loads(out or "[]") if rc == 0 else []
        rows.append({
            "pr": pr["number"],
            "catch_ups": len(catch_up_commits(pr)),
            "test_runs": len(runs),
            "attempts": sum(r.get("attempt", 1) for r in runs),
            "failed_runs": sum(1 for r in runs if r.get("conclusion") == "failure"),
        })
    return rows


def driver_overrides(gitattributes: str) -> list[str]:
    """One ``<pattern> merge=text`` line per ``.gitattributes`` row naming a
    merge driver, so a replay merges those paths the way GitHub does."""
    lines = []
    for raw in gitattributes.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if any(p.startswith("merge=") for p in parts[1:]):
            lines.append(f"{parts[0]} merge=text")
    return lines


def scratch_clone(root: Path, runner: Runner) -> Path:
    """A ``--shared`` clone with every merge driver overridden in its OWN
    ``info/attributes``; the caller removes it."""
    dest = Path(tempfile.mkdtemp(prefix="merge-cost-census-")) / "clone"
    rc, _out, err = runner(["git", "clone", "-q", "--no-checkout", "--shared", str(root), str(dest)])
    if rc != 0:
        raise SystemExit(f"merge_cost_census: scratch clone failed: {err.strip()}")
    attrs = root / ".gitattributes"
    overrides = driver_overrides(attrs.read_text(encoding="utf-8")) if attrs.is_file() else []
    info = dest / ".git" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "attributes").write_text("".join(f"{o}\n" for o in overrides), encoding="utf-8")
    return dest


def replay(clone: Path, oid: str, runner: Runner) -> tuple[str | None, list[str]]:
    """``(None, [])`` for a clean replay, else ``(result tree, conflicted paths)``.
    An unreadable merge (a parent this clone lacks) raises, never reads clean."""
    parents = []
    for n in (1, 2):
        rc, out, _err = runner(["git", "-C", str(clone), "rev-parse", f"{oid}^{n}"])
        if rc != 0:
            raise SystemExit(f"merge_cost_census: {oid}^{n} is not in this clone")
        parents.append(out.strip())
    rc, out, err = runner(["git", "-C", str(clone), "merge-tree", "--write-tree", "--name-only",
                           "--no-messages", *parents])
    if rc == 0:
        return None, []
    if rc != 1:
        raise SystemExit(f"merge_cost_census: merge-tree failed on {oid}: {err.strip()}")
    lines = [l for l in out.splitlines() if l.strip()]
    return lines[0], lines[1:]


_DERIVED = re.compile(
    r"^\*\*Live:|^## §|^### §|^\| \[§C|\*\*Members \(|LIVE issues|"
    r"^\| (HYGIENE|LOGIC_BUG|OPERATOR|MAINTAINER|ADOPTER|SELF-HOST) \|", re.M)
_INDEX_ROW = re.compile(r"^\| (~~)?`[A-Z]+-\d+[a-z]*`(~~)? \| §", re.M)
_ID_ROW = re.compile(r"^\| (~~)?`[A-Z]+-\d+", re.M)


def classify_block(path: str, block: list[str]) -> str:
    text = "\n".join(block)
    if path == PROBES:
        return "probes: _count" if '"_count"' in text else "probes: entries"
    if path == LEDGER:
        if _DERIVED.search(text):
            return "ledger: derived counts"
        if _INDEX_ROW.search(text):
            return "ledger: id index rows"
        if _ID_ROW.search(text):
            return "ledger: member rows"
        return "ledger: other"
    return f"{path}: block"


def conflict_blocks(text: str) -> list[list[str]]:
    """The lines of each ``<<<<<<<``..``>>>>>>>`` block, both sides together."""
    blocks, block, inside = [], [], False
    for line in text.splitlines():
        if line.startswith("<<<<<<< "):
            inside, block = True, []
        elif line.startswith(">>>>>>> ") and inside:
            blocks.append(block)
            inside = False
        elif inside and not line.startswith("======="):
            block.append(line)
    return blocks


def replay_all(prs: list[dict], clone: Path, runner: Runner) -> dict:
    files: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    merges = clean = record_only = 0
    for pr in prs:
        for oid in catch_up_commits(pr):
            merges += 1
            tree, conflicted = replay(clone, oid, runner)
            if tree is None:
                clean += 1
                continue
            files.update(conflicted)
            if set(conflicted) <= set(RECORD_FILES):
                record_only += 1
            for path in conflicted:
                if path not in (LEDGER, PROBES):
                    continue
                body = runner(["git", "-C", str(clone), "cat-file", "-p", f"{tree}:{path}"])[1]
                kinds.update(classify_block(path, b) for b in conflict_blocks(body))
    return {
        "catch_up_merges": merges, "clean": clean,
        "conflicted": merges - clean, "record_files_only": record_only,
        "files": dict(files.most_common()), "blocks": dict(kinds.most_common()),
    }


def stale_rows(prs: list[dict], runner: Runner, root: Path = ROOT, rules=None) -> list[dict]:
    """Per merged pull request, ``{"pr", "moved", "near", "unread"}``: the
    stale-base read on its merge commit's parents. A merge this clone lacks, a
    squash (one parent), or a head no run tested is ``unread``, never fresh."""
    rules = rules or _merge_rules()
    rows: list[dict] = []
    for pr in prs:
        row = {"pr": pr["number"], "moved": 0, "near": [], "unread": ""}
        rows.append(row)
        oid = str((pr.get("mergeCommit") or {}).get("oid") or "")
        rc, out, _ = runner(["git", "rev-list", "--parents", "-n", "1", oid], cwd=str(root)) if oid else (1, "", "")
        parents = out.split()[1:] if rc == 0 else []
        if len(parents) != 2:
            row["unread"] = ("no merge commit listed" if not oid else f"{oid[:7]} is not here (fetch)" if rc
                             else f"{oid[:7]} is not a two-parent merge")
            continue
        base, head = parents
        rc, out, err = runner(["gh", "run", "list", "--branch", str(pr.get("headRefName") or ""), "--event",
                               "pull_request", "--limit", "100", "--json",
                               "workflowName,createdAt,headSha,conclusion"], cwd=str(root))
        try:
            runs = json.loads(out or "[]") if rc == 0 else []
        except ValueError:
            runs = []
        rc, diff, _ = runner(["git", "diff", "--name-only", "--no-renames", f"{base}...{head}"], cwd=str(root))
        result = rules.stale_base(root, base_ref=base[:12], tested_when=rules.tested_at(runs, head),
                                  pr_paths=[ln for ln in diff.splitlines() if ln.strip()] if rc == 0 else [],
                                  pr_rev=head, run_=runner)
        row.update(moved=result.get("moved", 0), near=list(result.get("near") or []),
                   unread=str(result.get("unread") or ""))
    return rows


def render(reports: list[str], rows: list[dict] | None, replays: dict | None,
           stale: list[dict] | None = None) -> str:
    out: list[str] = []
    if rows is not None:
        n = len(rows)
        runs = sum(r["test_runs"] for r in rows)
        out.append("catch-ups (per merged pull request):")
        out.append("  pr     catch_ups  test_runs  attempts  failed_runs")
        for r in sorted(rows, key=lambda r: r["pr"]):
            out.append(f"  #{r['pr']:<5} {r['catch_ups']:>9} {r['test_runs']:>10} "
                       f"{r['attempts']:>9} {r['failed_runs']:>12}")
        out.append(
            f"  {n} merged; {sum(1 for r in rows if r['catch_ups'])} with a catch-up; "
            f"{sum(r['catch_ups'] for r in rows)} catch-ups; {runs} test runs "
            f"({runs / n:.2f} per pull request); "
            f"{sum(r['attempts'] for r in rows)} attempts" if n else "  no merged pull requests")
    if replays is not None and "conflicts" in reports:
        r = replays
        out.append(f"conflicts (catch-ups replayed as GitHub merges, drivers off): "
                   f"{r['catch_up_merges']} replayed, {r['clean']} clean, {r['conflicted']} "
                   f"conflicted ({r['record_files_only']} on the record files alone)")
        out.extend(f"  {n:>4}  {f}" for f, n in r["files"].items())
    if replays is not None and "blocks" in reports:
        out.append("blocks (record-file conflict blocks by what they span):")
        out.extend(f"  {n:>4}  {k}" for k, n in replays["blocks"].items())
    if stale is not None:
        out.append("stale (the base moved between a pull request's last CI run and its merge):")
        for r in sorted(stale, key=lambda r: r["pr"]):
            if r["moved"] or r["near"] or r["unread"]:
                out.append(f"  #{r['pr']:<5} moved {r['moved']}, near {len(r['near'])}"
                           + (f" (unread: {r['unread']})" if r["unread"] else ""))
                out.extend(f"         {n}" for n in r["near"][:3])
        read = [r for r in stale if not r["unread"] or r["near"]]
        near = sum(1 for r in stale if r["near"])
        out.append(f"  {len(stale)} merged, {len(read)} read: the base moved after the last CI run on "
                   f"{sum(1 for r in read if r['moved'])}, near the files on {near}"
                   + ("; more than half are near, so re-raise the rule" if read and near * 2 > len(read) else ""))
    return "\n".join(out)


def main(argv: list[str] | None = None, runner: Runner | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("reports", nargs="*", metavar="REPORT",
                    help=f"which reports, of {', '.join(REPORTS)} (default: {', '.join(DEFAULT_REPORTS)})")
    ap.add_argument("--prs", type=int, default=30, help="the last N merged pull requests")
    ap.add_argument("--prs-json", metavar="FILE",
                    help="read the pull-request list (gh pr list --json number,headRefName,commits) "
                         "from FILE instead of gh")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    unknown = [r for r in args.reports if r not in REPORTS]
    if unknown:
        ap.error(f"unknown report(s) {unknown}; choose from {', '.join(REPORTS)}")
    reports = list(args.reports) or list(DEFAULT_REPORTS)
    root = Path(args.root).resolve()
    runner = runner or _ship_runner()
    if args.prs_json:
        prs = json.loads(Path(args.prs_json).read_text(encoding="utf-8"))[: args.prs]
    else:
        prs = merged_prs(args.prs, runner, root)
    rows = catch_up_rows(prs, runner, root) if "catch-ups" in reports else None
    replays = None
    if "conflicts" in reports or "blocks" in reports:
        clone = scratch_clone(root, runner)
        try:
            replays = replay_all(prs, clone, runner)
        finally:
            shutil.rmtree(clone.parent, ignore_errors=True)
    stale = stale_rows(prs, runner, root) if "stale" in reports else None
    if args.json:
        print(json.dumps({"catch_ups": rows, "replays": replays, "stale": stale}, indent=2, sort_keys=True))
    else:
        print(render(reports, rows, replays, stale))
    return 0


if __name__ == "__main__":
    sys.exit(main())
