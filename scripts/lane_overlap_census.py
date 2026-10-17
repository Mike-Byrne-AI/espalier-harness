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
meets another lane once. That pack's Wave 1 moves the pure functions into
``tools/cc/_symbols.py`` and this script then imports them.

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
import ast
import itertools
import json
import os
import re
import sys
from pathlib import Path

MODULE = "<module>"
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
#: Every diff this script reads: rename detection off, so a moved file is a
#: deletion at its old path and an addition at its new one, and another lane
#: editing the old path meets it. Pinned by the test.
DIFF_ARGS: tuple[str, ...] = ("--no-renames", "--no-color", "--no-ext-diff", "--no-textconv")
_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_ASSIGN_NODES = (ast.Assign, ast.AnnAssign, ast.AugAssign)

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


# ---------------------------------------------------------------- placement

def _target_names(node: ast.AST) -> list[str]:
    """Each name an assignment target binds: ``a`` for ``a = 1``, ``a`` and
    ``b`` for ``a, b = ...``, the root name for an attribute or subscript
    (``X`` for ``X[1, 2] = ...``, so no comma reaches a symbol)."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [n for elt in node.elts for n in _target_names(elt)]
    if isinstance(node, ast.Starred):
        return _target_names(node.value)
    while isinstance(node, (ast.Subscript, ast.Attribute)):
        node = node.value
    if isinstance(node, ast.Name):
        return [node.id]
    return [ast.unparse(node)]


def spans(source: str) -> list[tuple[str, int, int, str]]:
    """``[(qualname, first_line, last_line, kind)]``, ``kind`` one of ``def``,
    ``class`` and ``name``, for every function, async
    function and class at any depth (qualified by the definitions above it:
    ``C.m``; a block such as ``if TYPE_CHECKING:`` or ``try:`` adds nothing),
    a definition's span starting at its first decorator, and for every
    module-level assignment by each target it binds. An assignment inside a
    class body is the class's, not a symbol of its own. Unparseable source
    maps nothing, so its lines read as unplaced."""
    out: list[tuple[str, int, int]] = []
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):   # 3.10 raises ValueError for a NUL byte
        return out

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _DEF_NODES):
                name = f"{prefix}{child.name}"
                lo = min([child.lineno] + [d.lineno for d in child.decorator_list])
                kind = "class" if isinstance(child, ast.ClassDef) else "def"
                out.append((name, lo, child.end_lineno or child.lineno, kind))
                walk(child, name + ".")
            elif prefix == "" and isinstance(child, _ASSIGN_NODES):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    for name in _target_names(target):
                        out.append((name, child.lineno, child.end_lineno or child.lineno, "name"))
            else:
                walk(child, prefix)

    walk(tree, "")
    return out


def innermost_spans(nodes: list[tuple[str, int, int, str]], line: int) -> list[tuple[str, int, int, str]]:
    """Every span that is the shortest one holding ``line``: one for a line
    inside a definition, each name of a tuple target for the line of
    ``a, b = ...`` (they share one span), nothing outside every node."""
    best: int | None = None
    found: list[tuple[str, int, int, str]] = []
    for span in nodes:
        _name, lo, hi, _kind = span
        if not (lo <= line <= hi):
            continue
        if best is None or (hi - lo) < best:
            best, found = hi - lo, [span]
        elif (hi - lo) == best:
            found.append(span)
    return found


def innermost(nodes: list[tuple[str, int, int, str]], line: int) -> list[str]:
    """The names of `innermost_spans`."""
    return [name for name, *_ in innermost_spans(nodes, line)]


def enclosing(nodes: list[tuple[str, int, int, str]], line: int) -> str:
    """The innermost span holding ``line`` (the first of `innermost`), else the module."""
    names = innermost(nodes, line)
    return names[0] if names else MODULE


def _indent(text: str) -> int:
    return len(text) - len(text.lstrip())


def placed(nodes: list[tuple[str, int, int, str]], lines: list[str], line: int) -> list[str]:
    """Where ``line`` (1-based) lands: a line the source does not have is the
    module, unplaced (a side that could not be read certifies nothing); a
    blank line is its function's when a function's span holds it (git
    conflicts on the edit beside it) and nothing elsewhere, neutral (the
    blank between two methods and a deletion's trailing blanks name no
    symbol, so an edit never flags a neighbour it did not touch); else its
    innermost node or nodes; for a comment outside every node, the node that
    starts right after an unbroken run of comments, when the comment is not
    indented deeper than that node (a blank breaks the run, and a comment
    indented as the body above it is unplaced); else the module, unplaced."""
    if not 0 < line <= len(lines):
        return [MODULE]
    text = lines[line - 1]
    stripped = text.strip()
    here = innermost_spans(nodes, line)
    if not stripped:
        return [name for name, _lo, _hi, kind in here if kind == "def"]
    if here:
        return [name for name, *_ in here]
    if not stripped.startswith("#"):
        return [MODULE]
    cursor = line
    while cursor <= len(lines):
        found = innermost_spans(nodes, cursor)
        if found:
            if _indent(text) <= _indent(lines[found[0][1] - 1]):
                return [name for name, *_ in found]
            return [MODULE]
        run = lines[cursor - 1].strip()
        if not run or not run.startswith("#"):
            return [MODULE]
        cursor += 1
    return [MODULE]


def symbols_meet(one: set[str], two: set[str]) -> set[str]:
    """The symbols two lanes both touch, the one rule every reader uses: an
    equal name, or a class on one side with a member of it on the other
    (``path::C`` meets ``path::C.m``, reported as the class); never the
    module, which is unplaced on both sides and a path hit at most."""
    met = {s for s in one & two if not s.endswith(f"::{MODULE}")}
    for a, b in ((one, two), (two, one)):
        for symbol in a:
            if symbol.endswith(f"::{MODULE}"):
                continue
            if any(other.startswith(symbol + ".") for other in b):
                met.add(symbol)
    return met


def _lines(source: str) -> list[str]:
    """The lines as git and ``ast`` count them: split on newlines only
    (``str.splitlines`` also splits on form feed and U+2028, and every line
    after one would read one off), without the empty tail a final newline leaves."""
    lines = source.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def changed_symbols(path: str, old_source: str, new_source: str, unified_diff: str) -> dict:
    """``{"kind", "symbols", "changed", "unplaced"}`` for one file's diff
    (``-U0`` from any producer): ``kind`` is ``python`` or ``path``; for Python
    every removed or changed line is placed in the old source and every added
    or changed line in the new, ``changed`` counts the lines read and
    ``unplaced`` the ones no node holds; for any other file the path is the
    one symbol and nothing is unplaced."""
    if not path.endswith(".py"):
        return {"kind": "path", "symbols": {path}, "changed": 0, "unplaced": 0}
    new_nodes, old_nodes = spans(new_source), spans(old_source)
    new_lines, old_lines = _lines(new_source), _lines(old_source)
    symbols: set[str] = set()
    changed = unplaced = 0
    for line in unified_diff.splitlines():
        m = HUNK_RE.match(line)
        if not m:
            continue
        old_start, old_len = int(m.group(1)), int(m.group(2) or 1)
        new_start, new_len = int(m.group(3)), int(m.group(4) or 1)
        sides = []
        if old_len > 0 and m.group(2) != "0":
            sides.append((old_nodes, old_lines, range(old_start, old_start + old_len)))
        if new_len > 0 and m.group(4) != "0":
            sides.append((new_nodes, new_lines, range(new_start, new_start + new_len)))
        for nodes, lines, span in sides:
            for ln in span:
                names = placed(nodes, lines, ln)
                if not names:                 # a blank line: neutral, neither placed nor unplaced
                    continue
                changed += 1
                if names == [MODULE]:
                    unplaced += 1
                for where in names:
                    symbols.add(f"{path}::{where}")
    return {"kind": "python", "symbols": symbols, "changed": changed, "unplaced": unplaced}


# ---------------------------------------------------------------- the pair

def concurrent(a: dict, b: dict) -> bool:
    """Two pull requests were open at once: each was created before the other merged."""
    return a["created"] < b["merged"] and b["created"] < a["merged"]


def pair_verdict(one: dict[str, dict], two: dict[str, dict]) -> dict:
    """What two lanes' placements say about each other, over the files both
    changed: ``shared`` (symbols both changed, the module excluded), ``paths``
    (files that are not Python), ``unplaced`` (Python files where a side left
    lines unplaced, or read no line at all, and no symbol is shared), ``verdict`` one of ``shared
    symbol``, ``unplaced``, ``different functions``, ``path only``, ``none``."""
    files = sorted(set(one) & set(two))
    shared: set[str] = set()
    paths: list[str] = []
    unplaced: list[str] = []
    certified: list[str] = []
    for path in files:
        a, b = one[path], two[path]
        if a["kind"] != "python" or b["kind"] != "python":
            paths.append(path)
            continue
        meet = symbols_meet(a["symbols"], b["symbols"])
        if meet:
            shared |= meet
        elif a["unplaced"] or b["unplaced"] or not a["changed"] or not b["changed"]:
            unplaced.append(path)   # a side that read no line certifies nothing
        else:
            certified.append(path)
    if shared:
        verdict = "shared symbol"
    elif unplaced:
        verdict = "unplaced"
    elif certified:
        verdict = "different functions"
    elif paths:
        verdict = "path only"
    else:
        verdict = "none"
    return {"files": files, "shared": sorted(shared), "paths": paths, "unplaced": unplaced,
            "certified": certified, "verdict": verdict}


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
    """``{canonical path: placement}`` for every file ``base..head`` changes,
    mirror twins folded onto their source (symbols united, counts summed)."""
    out: dict[str, dict] = {}
    for path in filter(None, _git("diff", "--name-only", "-z", *DIFF_ARGS, base, head).split("\0")):
        new = _git("show", f"{head}:{path}") if path.endswith(".py") else ""
        old = _git("show", f"{base}:{path}") if path.endswith(".py") else ""
        diff = _git("diff", "-U0", *DIFF_ARGS, base, head, "--", path)
        here = changed_symbols(path, old, new, diff)
        key = canonical(path)
        if key != path:
            here["symbols"] = {s.replace(path, key, 1) for s in here["symbols"]}
        if key in out:
            got = out[key]
            got["symbols"] |= here["symbols"]
            got["changed"] += here["changed"]
            got["unplaced"] += here["unplaced"]
        else:
            out[key] = here
    return out


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
        if not concurrent(info[a], info[b]):
            continue
        concurrent_pairs += 1
        verdict = pair_verdict(info[a]["placements"], info[b]["placements"])
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
