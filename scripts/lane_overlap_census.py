"""Which concurrently open pull requests shared a FILE, and which shared a SYMBOL.

The oracle the symbol-overlap pack's Task 0 runs, and the measurement its
Motivation cites. A
symbol is ``path::qualname``: a function, a method as ``Class.method``, a class,
or a top-level assignment by each target name. Symbols are derived from the
diff by the standard library's ``ast``, on BOTH sides of every hunk: added and
changed lines in the head's version of a file, removed and changed lines in the
base's, so a rename reports both names and a hunk that deletes one function
while extending another reports both. A decorator or a comment block directly
above a definition belongs to it, when the comment is not indented deeper
than the definition. A changed line no node holds (an import, a lone comment,
a line of a file one side cannot parse, a line a side does not have) is
UNPLACED: it is counted, it meets another lane's unplaced line as a path hit,
and it is never read as "different functions"; a blank line is its function's
inside one and neutral elsewhere; a file no line of which was read is never
certified. A file that is not Python is a path tier
of its own, never a symbol. Mirror twins (``espalier/mirror_registry.py``) are
collapsed onto their source, so a lane that edits a hook and its vendored copy
meets another lane once. The mapper and the pair verdict live in
``tools/cc/_symbols.py``, which this script loads by path and keeps no copy
of; the window, the listing, the spawns and the registry's full fold of the
twins are its own.

Reads the merged pull requests of a window through ``gh``, fetches the base and
each head, and for every pair whose open windows overlapped prints one of four
verdicts per shared Python file: a shared symbol, different functions (every
changed line on both sides placed, none shared), unplaced (a shared file where
a side has unplaced lines and no symbol is shared: no certificate), or a path
tier for files that are not Python. Standard library, ``git`` and ``gh``.

    python3 scripts/lane_overlap_census.py --prs 30
    python3 scripts/lane_overlap_census.py --window 180-209 --json
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

try:  # the twins' census; scripts/ may import the engine, tools/cc may not
    sys.path.insert(0, str(REPO_ROOT))
    from espalier import mirror_registry as _mirrors
except Exception:  # noqa: BLE001 -- no registry: paths stay as spelled, and the output says so
    _mirrors = None


def _bounded_spawn():
    """``run_bounded`` from this checkout's ``tools/cc/_json_safe.py``, loaded
    by path, never an installed engine's: ``subprocess.run`` whose timeout
    holds on Windows, where ``run`` waits on a grandchild holding its pipe
    (DEF-3004); the one spawn the timed-spawn contract admits."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_json_safe_for_lane_overlap_census", REPO_ROOT / "tools" / "cc" / "_json_safe.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.run_bounded


run_bounded = _bounded_spawn()


def _load_symbols():
    """``tools/cc/_symbols.py`` from this checkout, loaded by path: the mapper's
    and the pair verdict's one home, never a copy here."""
    spec = importlib.util.spec_from_file_location(
        "_symbols_for_lane_overlap_census", REPO_ROOT / "tools" / "cc" / "_symbols.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_symbols = _load_symbols()


# ---------------------------------------------------------------- git and gh

def _git(*args: str) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    return run_bounded(["git", *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120, env=env, cwd=REPO_ROOT).stdout


def _gh(*args: str) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    return run_bounded(["gh", *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120, env=env, cwd=REPO_ROOT).stdout


def _fold_once(path: str) -> str:
    for row in _mirrors.MIRROR_ROWS:
        for mirror in row.mirrors:
            if mirror.endswith("/") and path.startswith(mirror):
                tail = path[len(mirror):]
                glob = _mirrors.glob_row_parts(row.sot)
                base = glob[0] if glob is not None else row.sot
                return base + tail
            if path == mirror:
                return row.sot
    return path


def canonical(path: str) -> str:
    """A mirror path folded onto its source of truth, by the registry, until
    it stops moving (a region row's host file is itself another row's twin,
    so a synced lane would land on two keys after one hop; eight hops bound
    a registry that cycles); a path on no row, or any path when the registry
    is not importable, as spelled."""
    if _mirrors is None:
        return path
    for _ in range(8):
        folded = _fold_once(path)
        if folded == path:
            return path
        path = folded
    return path


def symbols_between(base: str, head: str) -> dict[str, dict]:
    """``{canonical path: placement}`` for every file ``base..head`` changes:
    the module's reading at the repository root, every mirror twin the
    registry names folded onto its source (symbols united, counts summed)."""
    return _symbols.symbols_between(base, head, root=REPO_ROOT, fold=canonical)


def census(*, prs: int | None = None, window: tuple[int, int] | None = None, base: str = "main") -> dict:
    """The window's merged pull requests read pairwise. ``window`` pins the
    pull request numbers (inclusive) so a re-run reads the same population;
    ``prs`` takes the last N. The base is fetched first so a merge commit newer
    than the last fetch is read, not skipped; a pull request whose base or head
    cannot be read is counted in ``unread``, never dropped in silence."""
    _git("fetch", "-q", "origin", base)
    missing: list[int] = []
    if window:
        lo, hi = window
        newest = json.loads(_gh("pr", "list", "--state", "all", "--limit", "1", "--json", "number"))
        top = newest[0]["number"] if newest else hi
        listed = json.loads(_gh("pr", "list", "--state", "merged", "--limit", str(window_limit(top, lo)),
                                "--json", "number,createdAt,mergedAt,headRefOid,mergeCommit"))
        listed = [p for p in listed if lo <= p["number"] <= hi]
        found = {p["number"] for p in listed}
        missing = [n for n in range(lo, hi + 1) if n not in found]
    else:
        listed = json.loads(_gh("pr", "list", "--state", "merged", "--limit", str(prs or 30),
                                "--json", "number,createdAt,mergedAt,headRefOid,mergeCommit"))
    info: dict[int, dict] = {}
    unread: list[int] = []
    changed_total = unplaced_total = 0
    for pr in listed:
        head = pr["headRefOid"]
        merge = (pr.get("mergeCommit") or {}).get("oid")
        _git("fetch", "-q", "origin", f"refs/pull/{pr['number']}/head")
        merge_base = _git("merge-base", head, merge + "^1").strip() if merge else ""
        if not merge_base:
            unread.append(pr["number"])
            continue
        placements = symbols_between(merge_base, head)
        changed_total += sum(p["changed"] for p in placements.values())
        unplaced_total += sum(p["unplaced"] for p in placements.values())
        info[pr["number"]] = {"created": pr["createdAt"], "merged": pr["mergedAt"], "placements": placements,
                              "changed": sum(p["changed"] for p in placements.values()),
                              "unplaced": sum(p["unplaced"] for p in placements.values())}
    pairs: list[dict] = []
    concurrent_pairs = 0
    for a, b in itertools.combinations(sorted(info), 2):
        if not _symbols.concurrent(info[a], info[b]):
            continue
        concurrent_pairs += 1
        verdict = _symbols.pair_verdict(info[a]["placements"], info[b]["placements"])
        if verdict["verdict"] != "none":
            pairs.append({"a": a, "b": b, **verdict})
    verdicts = {v: sum(1 for p in pairs if p["verdict"] == v)
                for v in ("shared symbol", "unplaced", "different functions", "path only")}
    return {"prs": len(info), "unread": unread, "missing": missing, "mirrors_folded": _mirrors is not None,
            "concurrent_pairs": concurrent_pairs, "sharing_a_file": len(pairs), "verdicts": verdicts,
            "changed_lines": changed_total, "unplaced_lines": unplaced_total,
            "per_pr": {n: {"changed": i["changed"], "unplaced": i["unplaced"]} for n, i in info.items()},
            "pairs": pairs}


def window_limit(newest: int, lo: int) -> int:
    """How many merged pull requests, newest first, the listing must read to
    reach number ``lo``: every number from the newest down to it, since the
    listing counts from the newest and a fixed limit truncates a pinned
    window as merges accumulate above it (bounded at 1000, a cap on one listing)."""
    return max(1, min(1000, newest - lo + 1))


def _window(text: str) -> tuple[int, int]:
    lo, hi = text.split("-", 1)
    return int(lo), int(hi)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prs", type=int, default=30, help="the last N merged pull requests (default 30)")
    ap.add_argument("--window", type=_window, default=None,
                    help="pull request numbers LO-HI, inclusive: a window a re-run reads again")
    ap.add_argument("--base", default="main", help="the base branch on origin (default main)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    result = census(prs=args.prs, window=args.window, base=args.base)
    if args.json:
        print(json.dumps(result, indent=2, default=sorted))
        return 0
    v = result["verdicts"]
    rate = (result["unplaced_lines"] / result["changed_lines"]) if result["changed_lines"] else 0.0
    print(f"PRs read: {result['prs']} (unread: {len(result['unread'])}; numbers in the window not merged "
          f"or not listed: {len(result['missing'])}); concurrent pairs: "
          f"{result['concurrent_pairs']}; sharing a file: {result['sharing_a_file']}: "
          f"shared symbol {v['shared symbol']}, unplaced {v['unplaced']}, different functions "
          f"{v['different functions']}, path only {v['path only']}; unplaced Python lines "
          f"{result['unplaced_lines']} of {result['changed_lines']} ({rate:.1%})"
          + ("" if result["mirrors_folded"] else "; mirror twins NOT folded (registry unread)"))
    for p in result["pairs"]:
        files = ", ".join(p["files"][:3]) + (" ..." if len(p["files"]) > 3 else "")
        detail = {"shared symbol": ", ".join(p["shared"]), "unplaced": "unplaced lines in " + ", ".join(p["unplaced"]),
                  "different functions": "every changed line placed, none shared",
                  "path only": "not Python: " + ", ".join(p["paths"])}[p["verdict"]]
        print(f"  #{p['a']} & #{p['b']}: {len(p['files'])} file(s) [{files}]: {p['verdict']} ({detail})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
