#!/usr/bin/env python3
"""What ``espalier/cli.py`` costs a maintainer, read at one pinned commit.

The instrument of the cli.py audit (wave 0 of the roadmap that maps
the CLI before any of it moves). Every section is
read at ``--at``, a commit with no default. Every source text comes from git's
objects at that commit, never from the working tree, and every window is
anchored to the commit's date, never to the clock. A run without ``--at``
refuses, so two runs at one pin read one population.

    python3 scripts/cli_cost_census.py --at <P> --json                  # every section
    python3 scripts/cli_cost_census.py --at <P> functions layers        # named sections
    python3 scripts/cli_cost_census.py --at <P> collision transcripts   # Task 0's two oracles

"The CLI modules" are ``espalier/cli.py`` plus every module that receives a
definition moved out of it (``--module``, repeatable). C1, C3 and C4 count
over the whole set, so a move cannot zero them by changing which file the
events land on. C2 (``claim_overlaps``) does not: it counts an overlap only
where another seat's claim names the same CLI module the lane changed, so any
split of cli.py lowers it by construction, and it cannot grade a module move.

A section that cannot be read is named under ``unread`` with its reason, and
its key holds ``None``. It never reads as a zero.

What this script does not own it loads by path and keeps no copy of:
``tools/cc/_json_safe.py`` (the bounded spawn), ``tools/cc/_symbols.py`` (hunks
on symbols), ``scripts/merge_cost_census.py`` (the replay with drivers off, in a
throwaway shared clone), ``scripts/lane_overlap_census.py`` (concurrent pairs)
and ``tools/cc/mail.py`` (the mail fold).

Self-host tooling (``scripts/`` is not deployed). Standard library, ``git`` and
``gh``.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import functools
import hashlib
import importlib.util
import itertools
import json
import math
import os
import posixpath
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import textwrap
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = "espalier/cli.py"
#: The windowed components read the 30 days to the pin's commit date.
WINDOW_DAYS = 30
SECTIONS = ("pin", "functions", "layers", "clusters", "importers", "readers", "patches",
            "citations", "probes", "doctor_boundary", "move_cost", "ledger_rows", "collision", "transcripts",
            "lane_read")
GIT_TIMEOUT = 120.0


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


#: ``subprocess.run`` whose timeout holds on Windows (DEF-3004), from this
#: checkout's ``tools/cc/_json_safe.py``: the one spawn the timed-spawn contract admits.
run_bounded = _load("_ccc_json_safe", "tools/cc/_json_safe.py").run_bounded


@functools.lru_cache(maxsize=None)
def _symbols():
    """``tools/cc/_symbols.py`` by path: the mapper of hunks onto symbols."""
    return _load("_ccc_symbols", "tools/cc/_symbols.py")


class Unread(Exception):
    """A section that could not be read: its reason goes under ``unread``."""


#: The failures that leave a section (or one part of one) unread, never a value:
#: git past ``GIT_TIMEOUT`` (``TimeoutExpired``), a program or a file that is not
#: there (``OSError``: no git, no gh, a missing ``--prs-json``), a source that
#: does not parse (``SyntaxError``), a short read or bad JSON (``ValueError``,
#: ``JSONDecodeError`` among them) and the ``SystemExit`` a loaded census raises
#: (``merge_cost_census``'s replay and scratch clone).
_READ_FAILURES = (Unread, subprocess.TimeoutExpired, OSError, SyntaxError, ValueError, SystemExit)


def _unread(exc: BaseException) -> Unread:
    """``exc`` as an ``Unread``, its type named where it was not one already."""
    return exc if isinstance(exc, Unread) else Unread(f"{type(exc).__name__}: {exc}")


def _partial(ctx: dict, section: str, part: str, why: str) -> None:
    """Name ``<section>.<part>`` under the run's ``unread``: a part of a section
    that could not be read while the rest of it was."""
    ctx.setdefault("_partial_unread", {}).setdefault(section, {})[part] = why


def _ast_lines(text: str) -> list[str]:
    """``text``'s lines as Python's tokenizer numbers them, which ``ast`` line
    numbers index: split on ``\\r\\n``, ``\\r`` and ``\\n`` alone, where
    ``str.splitlines`` also splits on ``\\f``, ``\\v``, ``\\x1c`` to ``\\x1e``,
    ``\\x85``, U+2028 and U+2029."""
    lines = re.split(r"\r\n|\r|\n", text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines


# ---------------------------------------------------------------- git, at the pin

def git(root: Path, *args: str) -> tuple[int, str, str]:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    proc = run_bounded(["git", *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=GIT_TIMEOUT, env=env, cwd=str(root))
    return proc.returncode, proc.stdout, proc.stderr


def _iso_z(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_pin(root: Path, at: str) -> dict:
    """The pin: the full object id of ``at``, its committer date in UTC, and
    the 30-day window that ends at that date. The window is read from the
    commit, never from the clock, so a re-run a day later reads the same days."""
    rc, out, err = git(root, "rev-parse", "--verify", f"{at}^{{commit}}")
    if rc != 0:
        raise SystemExit(f"cli_cost_census: --at {at!r} is not a commit here: {err.strip()}")
    sha = out.strip()
    rc, out, err = git(root, "log", "-1", "--format=%cI", sha)
    if rc != 0 or not out.strip():
        raise SystemExit(f"cli_cost_census: cannot read the date of {sha}: {err.strip()}")
    until = datetime.fromisoformat(out.strip())
    since = until - timedelta(days=WINDOW_DAYS)
    return {"at": sha, "date": _iso_z(until), "window": {"days": WINDOW_DAYS, "since": _iso_z(since),
                                                          "until": _iso_z(until)}}


@functools.lru_cache(maxsize=None)
def source_at(root: Path, at: str, path: str) -> str | None:
    """``path``'s text at commit ``at``, or ``None`` where the commit has no
    such file: ``git show`` fails and ``git ls-tree`` lists no entry at that
    path (asked of git, never read off its words, which a translated git
    words otherwise and which name a commit git cannot find as a path not in
    it). Any other failure (a commit git cannot read, a git that cannot run)
    is ``Unread``: a failed read is never an absent file."""
    rc, out, err = git(root, "show", f"{at}:{path}")
    if rc == 0:
        return out
    rc, listed, _err = git(root, "--literal-pathspecs", "ls-tree", "-z", "--name-only", at, "--", path)
    if rc == 0 and not listed:
        return None
    raise Unread(f"git show {at[:12]}:{path} failed: {err.strip()[:200]}")


def tracked_at(root: Path, at: str) -> list[str]:
    """Every path tracked at ``at``, NUL-separated (``-z``): without it git
    quotes a path holding a non-ASCII byte, and the quoted name then reads as
    no file."""
    rc, out, err = git(root, "ls-tree", "-r", "--name-only", "-z", at)
    if rc != 0:
        raise Unread(f"git ls-tree {at} failed: {err.strip()}")
    return [p for p in out.split("\0") if p]


def blobs_at(root: Path, at: str, paths: list[str]) -> dict[str, str]:
    """Each path's text at ``at``, read in one ``git cat-file --batch``. A path
    git cannot read (absent, not a blob, or a name holding a newline, which
    the batch's line protocol cannot carry) is left out, so a caller counts
    what it read. A reply the batch cut short is ``Unread``: every entry but a
    ``missing``, ``ambiguous`` or ``submodule`` one carries a body, which is
    stepped over whatever its type, so no path's text is read as another's.
    A gitlink's ``<oid> submodule`` header, bodiless, is newer git's (the CI
    cells'; the Air's 2.39 writes none), and its path goes unread like a
    missing one."""
    asked = [p for p in paths if "\n" not in p]
    if not asked:
        return {}
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    proc = run_bounded(["git", "cat-file", "--batch"], input="".join(f"{at}:{p}\n" for p in asked).encode(),
                       capture_output=True, timeout=GIT_TIMEOUT, env=env, cwd=str(root))
    if proc.returncode != 0:
        raise Unread(f"git cat-file --batch at {at[:12]} failed")
    data, out, pos = proc.stdout, {}, 0
    for path in asked:
        end = data.find(b"\n", pos)
        if end < 0:
            raise Unread(f"git cat-file --batch at {at[:12]} replied short: no header for {path}")
        header = data[pos:end]
        pos = end + 1
        if header.endswith((b" missing", b" ambiguous", b" submodule")):
            continue
        parts = header.split()
        if len(parts) != 3 or not parts[2].isdigit():
            raise Unread(f"git cat-file --batch at {at[:12]}: a header it cannot read for {path}: {header[:80]!r}")
        size = int(parts[2])
        if pos + size + 1 > len(data):
            raise Unread(f"git cat-file --batch at {at[:12]} replied short: {path}'s body is cut")
        if parts[1] == b"blob":
            out[path] = data[pos:pos + size].decode("utf-8", errors="replace")
        pos += size + 1
    return out


# ---------------------------------------------------------------- the definitions and their graph

FUNCTION, CLASS, NAME = "function", "class", "name"


def _top_statements(body: list[ast.stmt]):
    """The module's own statements, with those inside a module-level ``if`` or
    ``try`` flattened in: a definition there is still a top-level one."""
    for node in body:
        if isinstance(node, ast.If):
            yield from _top_statements(node.body)
            yield from _top_statements(node.orelse)
        elif isinstance(node, ast.Try):
            for part in (node.body, *(h.body for h in node.handlers), node.orelse, node.finalbody):
                yield from _top_statements(part)
        else:
            yield node


def _store_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for elt in target.elts for n in _store_names(elt)]
    if isinstance(target, ast.Starred):
        return _store_names(target.value)
    return []


def definitions(tree: ast.Module) -> list[dict]:
    """Every top-level definition: each function, each class, and each name a
    module-level assignment binds, with its span. Imports are not definitions:
    they bind another module's object, priced in the importers section."""
    out: list[dict] = []
    for node in _top_statements(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            kind = CLASS if isinstance(node, ast.ClassDef) else FUNCTION
            out.append({"name": node.name, "kind": kind, "start": start, "end": node.end_lineno,
                        "node": node})
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in _store_names(target):
                    out.append({"name": name, "kind": NAME, "start": node.lineno, "end": node.end_lineno,
                                "node": node})
    seen: dict[str, dict] = {}
    for d in out:
        d["lines"] = d["end"] - d["start"] + 1
        if d["name"] in seen:  # bound twice (an if/else pair): one definition, its rebinds counted
            seen[d["name"]]["rebinds"] = seen[d["name"]].get("rebinds", 0) + 1
            seen[d["name"]].setdefault("also", []).append(d["node"])
            continue
        seen[d["name"]] = d
    return list(seen.values())


_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _new_scope(kind: str, parent: dict | None) -> dict:
    return {"kind": kind, "parent": parent, "bound": set(), "global": set(), "nonlocal": set()}


def _resolves_to_module(name: str, start: dict) -> str | None:
    """``"module"`` where a name used in scope ``start`` is the module's own
    binding, ``"global"`` where it reaches the module through a ``global``
    declaration, ``None`` where a scope on the way binds it. A class body is
    seen only from inside itself, never from a scope nested in it."""
    scope, first = start, True
    while scope["kind"] != "module":
        if first or scope["kind"] != "class":
            if name in scope["global"]:
                return "global"
            if name in scope["nonlocal"] or name in scope["bound"]:
                return None
        scope, first = scope["parent"], False
    return "module"


def _module_refs(root: ast.AST) -> tuple[set[int], set[int]]:
    """``(refs, writes)``: the ``id`` of each ``ast.Name`` under ``root`` (a
    module-level statement or expression) that names the module's own binding,
    resolved scope by scope as Python resolves it. A function, a lambda, a
    comprehension and a class body each bind their own names (parameters,
    targets, imports, nested definitions, ``except`` names, match captures; a
    walrus binds in the scope around its comprehension), so a nested scope's
    binding shadows only inside it; a definition's decorators, defaults and
    annotations, and a comprehension's first iterable, are read in the scope
    around it. ``writes``: the stores and deletes that reach the module through
    a ``global`` declaration (a module-level statement's own target is none)."""
    module = _new_scope("module", None)
    names: list[tuple[ast.Name, dict]] = []
    stack: list[tuple[ast.AST, dict]] = [(root, module)]

    def push(nodes, scope: dict) -> None:
        stack.extend((n, scope) for n in nodes if n is not None)

    def args_of(args: ast.arguments) -> list[ast.arg]:
        return [a for a in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg) if a is not None]

    while stack:
        node, cur = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            params = args_of(node.args)
            push([*getattr(node, "decorator_list", ()), *(a.annotation for a in params), *node.args.defaults,
                  *node.args.kw_defaults, getattr(node, "returns", None)], cur)
            inner = _new_scope("function", cur)
            inner["bound"].update(a.arg for a in params)
            inner["bound"].update(p.name for p in getattr(node, "type_params", ()))
            if isinstance(node, ast.Lambda):
                push([node.body], inner)
            else:
                cur["bound"].add(node.name)
                push(node.body, inner)
        elif isinstance(node, ast.ClassDef):
            cur["bound"].add(node.name)
            push([*node.decorator_list, *node.bases, *(k.value for k in node.keywords)], cur)
            push(node.body, _new_scope("class", cur))
        elif isinstance(node, _COMPREHENSIONS):
            push([node.generators[0].iter], cur)
            inner = _new_scope("comprehension", cur)
            for i, gen in enumerate(node.generators):
                push([gen.target, *gen.ifs, *([gen.iter] if i else [])], inner)
            push([node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt], inner)
        elif isinstance(node, ast.NamedExpr):
            home = cur
            while home["kind"] == "comprehension":
                home = home["parent"]
            home["bound"].add(node.target.id)
            names.append((node.target, home))
            push([node.value], cur)
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                cur["bound"].add(node.id)
            names.append((node, cur))
        elif isinstance(node, ast.Global):
            cur["global"].update(node.names)
        elif isinstance(node, ast.Nonlocal):
            cur["nonlocal"].update(node.names)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            cur["bound"].update((a.asname or a.name).split(".")[0] for a in node.names if a.name != "*")
        else:
            bound = getattr(node, "name", None) if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) \
                else getattr(node, "rest", None) if isinstance(node, ast.MatchMapping) else None
            if bound:
                cur["bound"].add(bound)
            push(ast.iter_child_nodes(node), cur)
    refs: set[int] = set()
    writes: set[int] = set()
    for node, scope in names:
        how = _resolves_to_module(node.id, scope)
        if how is None:
            continue
        refs.add(id(node))
        if how == "global" and isinstance(node.ctx, (ast.Store, ast.Del)):
            writes.add(id(node))
    return refs, writes


def _module_aliases(tree: ast.Module) -> dict[str, str]:
    """Top-level ``import x as y`` / ``from p import m as y`` aliases that name
    a module: a load of ``y.attr`` is a call through another module."""
    aliases: dict[str, str] = {}
    for node in _top_statements(tree.body):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split(".")[0]] = a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                aliases[a.asname or a.name] = f"{node.module}.{a.name}"
    return aliases


def graph(tree: ast.Module, defs: list[dict]) -> dict:
    """The call graph over the top-level definitions.

    An edge from a definition to a module-level definition is a load of its
    name (a call, a reference, a ``set_defaults(func=...)`` wiring, a member of
    a dict or tuple literal), or a WRITE: a name the definition declares
    ``global`` and assigns. A write is an edge of its own, so a latch moves
    with the functions that set it as well as those that read it. What the
    graph cannot read is counted per definition, never dropped: a ``getattr``
    with a constant name, a string constant equal to a definition's name, an
    attribute load through an imported module, and a lazy import inside the
    definition (its outbound edge to another module). Every name is resolved
    scope by scope (``_module_refs``): a lambda's parameter or a nested
    function's local shadows a module name inside that scope alone."""
    names = {d["name"] for d in defs}
    aliases = _module_aliases(tree)
    loads: dict[str, set[str]] = {n: set() for n in names}
    writes: dict[str, set[str]] = {n: set() for n in names}
    unresolved: dict[str, dict] = {}
    for d in defs:
        node, me = d["node"], d["name"]
        walk_root = node.value if d["kind"] == NAME and getattr(node, "value", None) is not None else node
        refs, stores = _module_refs(walk_root)
        u = unresolved.setdefault(me, {"getattr": 0, "string_names": 0, "through_module": 0,
                                       "lazy_imports": []})
        for sub in ast.walk(walk_root):
            if isinstance(sub, ast.Name):
                if sub.id not in names or sub.id == me and d["kind"] == NAME:
                    continue
                if isinstance(sub.ctx, ast.Load) and id(sub) in refs:
                    loads[me].add(sub.id)
                elif id(sub) in stores:
                    writes[me].add(sub.id)
            elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "getattr":
                if len(sub.args) >= 2 and isinstance(sub.args[1], ast.Constant):
                    u["getattr"] += 1
            elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value in names:
                u["string_names"] += 1
            elif (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                  and sub.value.id in aliases and id(sub.value) in refs):
                u["through_module"] += 1
            elif isinstance(sub, ast.ImportFrom) and d["kind"] != NAME:
                u["lazy_imports"].append({"module": "." * sub.level + (sub.module or ""),
                                          "names": [a.name for a in sub.names], "line": sub.lineno})
            elif isinstance(sub, ast.Import) and d["kind"] != NAME:
                u["lazy_imports"].append({"module": ",".join(a.name for a in sub.names), "names": [],
                                          "line": sub.lineno})
        loads[me].discard(me)  # recursion and a self-referencing literal are not edges
    edges = {n: sorted(loads[n] | writes[n]) for n in names}
    return {"loads": {n: sorted(v) for n, v in loads.items()},
            "writes": {n: sorted(v) for n, v in writes.items() if v},
            "edges": edges, "unresolved": unresolved}


def latches(tree: ast.Module, defs: list[dict], g: dict) -> dict:
    """The module-level names some definition declares ``global`` and assigns
    (latches), and the module-level dicts some definition changes in place
    (memos: a subscript store or a ``.update``/``.setdefault``/``.clear``/``.pop``
    call), each with every definition that reads or writes it. A unit holds a
    latch's readers and writers together or none of them."""
    kinds = {d["name"]: d["kind"] for d in defs}
    written: dict[str, set[str]] = {}
    for me, targets in g["writes"].items():
        for t in targets:
            written.setdefault(t, set()).add(me)
    memo: dict[str, set[str]] = {}
    mutators = {"update", "setdefault", "clear", "pop", "popitem", "__setitem__"}
    dict_names = {d["name"] for d in defs if d["kind"] == NAME and isinstance(getattr(d["node"], "value", None),
                                                                             (ast.Dict, ast.Call))}
    for d in defs:
        if d["kind"] == NAME:
            continue
        for sub in ast.walk(d["node"]):
            if (isinstance(sub, ast.Subscript) and isinstance(sub.ctx, ast.Store)
                    and isinstance(sub.value, ast.Name) and sub.value.id in dict_names):
                memo.setdefault(sub.value.id, set()).add(d["name"])
            elif (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                  and sub.func.attr in mutators and isinstance(sub.func.value, ast.Name)
                  and sub.func.value.id in dict_names):
                memo.setdefault(sub.func.value.id, set()).add(d["name"])

    def readers(name: str) -> list[str]:
        return sorted(me for me, targets in g["loads"].items() if name in targets and kinds.get(me) != NAME)

    return {"latches": {n: {"writers": sorted(w), "readers": readers(n)} for n, w in sorted(written.items())},
            "memos": {n: {"writers": sorted(w), "readers": readers(n)} for n, w in sorted(memo.items())}}


def parse_cli(root: Path, at: str, path: str = CLI) -> tuple[ast.Module, list[dict]]:
    text = source_at(root, at, path)
    if text is None:
        raise Unread(f"{path} is not in {at[:12]}")
    tree = ast.parse(text)
    return tree, definitions(tree)


# ---------------------------------------------------------------- sections

def section_pin(ctx: dict) -> dict:
    return dict(ctx["pin"], modules=list(ctx["modules"]))


def section_functions(ctx: dict) -> dict:
    """The top-level shape of cli.py at the pin: the counts, the largest
    definitions, the graph's edges (loads and writes), the latches and memos,
    and what the graph cannot read."""
    root, at = ctx["root"], ctx["pin"]["at"]
    text = source_at(root, at, CLI)
    tree, defs = parse_cli(root, at)
    g = graph(tree, defs)
    fns = [d for d in defs if d["kind"] == FUNCTION]
    lazy = sum(len(u["lazy_imports"]) for u in g["unresolved"].values())
    return {
        "lines": len(_ast_lines(text)) if text else 0,
        "functions": len(fns),
        "public_functions": sum(1 for d in fns if not d["name"].startswith("_")),
        "classes": sum(1 for d in defs if d["kind"] == CLASS),
        "commands": sorted(d["name"] for d in fns if d["name"].startswith("cmd_")),
        "module_names": sum(1 for d in defs if d["kind"] == NAME),
        "definitions": len(defs),
        "function_lines": sum(d["lines"] for d in fns),
        "largest": [{"name": d["name"], "lines": d["lines"]}
                    for d in sorted(fns, key=lambda d: (-d["lines"], d["name"]))[:10]],
        "edges": sum(len(v) for v in g["edges"].values()),
        "write_edges": sum(len(v) for v in g["writes"].values()),
        **latches(tree, defs, g),
        "unresolved": {"getattr": sum(u["getattr"] for u in g["unresolved"].values()),
                       "string_names": sum(u["string_names"] for u in g["unresolved"].values()),
                       "through_module": sum(u["through_module"] for u in g["unresolved"].values()),
                       "lazy_imports": lazy},
    }


def sccs(edges: dict[str, list[str]]) -> list[list[str]]:
    """Strongly connected components (Tarjan, iterative), each sorted; a
    component's callees come before it in the returned order (bottom-up)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for start in sorted(edges):
        if start in index:
            continue
        work = [(start, iter(sorted(edges.get(start, ()))))]
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on.add(start)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in edges:
                    continue
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on.add(nxt)
                    work.append((nxt, iter(sorted(edges.get(nxt, ())))))
                    advanced = True
                    break
                if nxt in on:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                out.append(sorted(comp))
    return out


def closure(edges: dict[str, list[str]], seeds, *, stop: set[str] = frozenset()) -> set[str]:
    """Every definition reachable from ``seeds`` (the seeds included), never
    entering a node in ``stop``."""
    seen: set[str] = set()
    todo = [s for s in seeds if s in edges]
    while todo:
        node = todo.pop()
        if node in seen:
            continue
        seen.add(node)
        todo.extend(n for n in edges.get(node, ()) if n not in seen and n not in stop)
    return seen


def order_cycles(edges: dict[str, list[str]], units: list[tuple[str, set[str]]]) -> list[dict]:
    """For units listed bottom-up, each edge from a lower unit into a higher
    one: moved in that order, the lower module would import the higher one,
    which imports it back (a cycle). Empty when the order is closed."""
    rank = {m: i for i, (_n, members) in enumerate(units) for m in members}
    out = []
    for i, (name, members) in enumerate(units):
        for m in sorted(members):
            for callee in edges.get(m, ()):
                j = rank.get(callee)
                if j is not None and j > i:
                    out.append({"unit": name, "member": m, "calls": callee, "above": units[j][0]})
    return out


#: Hand-named layer seeds (``layer_source: hand``): each layer is its seeds
#: closed under what they call, minus the layers below it. A seed that does
#: not exist at the pin is reported, never silently dropped.
#:
#: The interpreter core's two seeds reproduce the authoring read at 17d83e0
#: exactly (18 functions, 656 lines; 6 names over load edges alone, 8 once the
#: write edges are in, the two ``_detect_python_command`` writes and never
#: reads); ``_detect_python_command`` alone gives 17 and 637, since
#: ``_remedy_py`` calls the core and nothing the core calls reaches it. The
#: settings seeds are the five functions that write ``.claude/settings.json``
#: and the five public readers of it; the two with no caller at 3330a5a
#: (``rerender_fresh_settings``, ``settings_foreign_read_denies``) are left
#: to the unreached.
LAYER_SEEDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("interpreter core", ("_detect_python_command", "_remedy_py")),
    ("settings", ("merge_hooks_into_settings", "repair_hook_wiring_in_settings",
                  "rewire_interpreter_in_settings", "move_statusline_head_in_settings", "fresh_settings",
                  "settings_superseded_allows", "settings_stale_denies", "settings_allow_gaps",
                  "settings_scoped_allows", "installed_settings_profile")),
    ("deploy", ("deploy_harness",)),
)


def _functions_ctx(ctx: dict) -> tuple[ast.Module, list[dict], dict]:
    if "_cli" not in ctx:
        tree, defs = parse_cli(ctx["root"], ctx["pin"]["at"])
        ctx["_cli"] = (tree, defs, graph(tree, defs))
    return ctx["_cli"]


def _size(members: set[str], kinds: dict[str, str], lines: dict[str, int]) -> dict:
    return {"functions": sum(1 for m in members if kinds[m] == FUNCTION),
            "classes": sum(1 for m in members if kinds[m] == CLASS),
            "names": sum(1 for m in members if kinds[m] == NAME),
            "function_lines": sum(lines[m] for m in members if kinds[m] == FUNCTION)}


def ties(tree: ast.Module, defs: list[dict], g: dict) -> dict[str, tuple[str, set[str]]]:
    """Each latch and memo, with its kind and every definition that reads or
    writes it: the set a unit holds whole or not at all (Task 2, step 2)."""
    table = latches(tree, defs, g)
    return {name: (kind, set(t["writers"]) | set(t["readers"]))
            for kind, key in (("latch", "latches"), ("memo", "memos")) for name, t in table[key].items()}


def tie_closure(edges: dict[str, list[str]], members: set[str], tied: dict[str, tuple[str, set[str]]],
                below: set[str]) -> set[str]:
    """``members`` grown until it holds every tie it touches whole (the latch
    or memo and each of its readers and writers), closed under what it calls
    after each pull, never entering ``below``."""
    held = set(members)
    while True:
        pull = set()
        for name, (_kind, users) in tied.items():
            group = users | {name}
            if group & held:
                pull |= group
        grown = closure(edges, held | pull) - below
        if grown == held:
            return held
        held = grown


def section_layers(ctx: dict) -> dict:
    """The strongly connected components, the condensation's bottom-up order
    (sizes only, the multi-member components named), the hand-named layers,
    each closed under what it calls, and the cycle any other order would make.

    Each layer is its seeds' closure minus the layers below, so the bottom-up
    ``order_cycles`` is empty by construction: it checks the construction, not
    the order. What tests the order is ``absorbed_seeds`` (a lower layer whose
    closure took a higher layer's seed leaves that layer empty) and the
    reversed order's count. ``split_ties`` names each latch or memo whose
    readers and writers sit in two units, and each layer's ``tie_closed`` is
    the unit that would keep them whole. ``loads_only`` is the same layer read
    over load edges alone, the authoring read's graph."""
    tree, defs, g = _functions_ctx(ctx)
    edges = g["edges"]
    lines = {d["name"]: d["lines"] for d in defs}
    kinds = {d["name"]: d["kind"] for d in defs}
    seeded = tuple(ctx.get("layer_seeds", LAYER_SEEDS))
    tied = ties(tree, defs, g)
    comps = sccs(edges)
    layers, below, below_loads = [], set(), set()
    for i, (name, seeds) in enumerate(seeded):
        present = [s for s in seeds if s in edges]
        members = closure(edges, present) - below
        by_loads = closure(g["loads"], present) - below_loads
        higher = {s for _n, later in seeded[i + 1:] for s in later}
        grown = tie_closure(edges, members, tied, below)
        layers.append({"name": name, "layer_source": "hand", "seeds": list(seeds),
                       "missing_seeds": [s for s in seeds if s not in edges],
                       **_size(members, kinds, lines),
                       "loads_only": _size(by_loads, kinds, lines),
                       "absorbed_seeds": sorted(members & higher),
                       "tie_closed": {**_size(grown, kinds, lines), "pulled": sorted(grown - members)},
                       "members": sorted(members)})
        below |= members
        below_loads |= by_loads
    commands = {n for n in edges if n.startswith("cmd_") and kinds[n] == FUNCTION}
    units = [(layer["name"], set(layer["members"])) for layer in layers]
    units.append(("commands", closure(edges, commands) - below))
    unit_of = {m: unit for unit, members in units for m in members}
    split = []
    for name, (kind, users) in sorted(tied.items()):
        home = unit_of.get(name, "unplaced")
        held = {u: unit_of.get(u, "unplaced") for u in sorted(users)}
        if set(held.values()) - {home}:
            split.append({"tie": name, "kind": kind, "home": home, "held": held})
    return {"components": len(comps), "cyclic": [c for c in comps if len(c) > 1],
            "layers": layers, "order": [u[0] for u in units],
            "order_cycles": order_cycles(edges, units),
            "reversed_order_cycles": len(order_cycles(edges, list(reversed(units)))),
            "split_ties": split}


#: Hand grouping of the commands into concerns (``cluster_source: hand``),
#: from call 35136c's list, corrected where reach at authoring disagreed with
#: it. A command the grouping does not name stays a concern of its own.
CONCERNS: dict[str, tuple[str, ...]] = {
    "init, upgrade and deploy": ("cmd_init", "cmd_upgrade", "cmd_merge_settings", "cmd_install_ci",
                                 "cmd_fingerprint", "cmd_render_template"),
    "scan and scope-check": ("cmd_scan", "cmd_scope_check"),
}


def _ownership(edges: dict[str, list[str]], roots: dict[str, set[str]], stop: set[str]) -> dict[str, set[str]]:
    reached: dict[str, set[str]] = {}
    for root_name, seeds in roots.items():
        for m in closure(edges, seeds, stop=stop - seeds):
            reached.setdefault(m, set()).add(root_name)
    return reached


def section_clusters(ctx: dict) -> dict:
    """Ownership by command, then by concern. From each ``cmd_*`` take the
    closure: a definition reached by one command is owned by it, by several
    shared, by none unreached. The commands are the only roots (the pack's
    method, which reproduces 98 / 197 / 15 functions at 17d83e0), so the
    unreached split four ways: reached from ``main`` or ``build_parser``
    alone (``entry``), reached from another module's imports and what they
    call (``external``), from the tests' imports alone (``tests_only``), and
    the rest (``dead``). The two import reads come from the importers
    section; where it cannot be read they are ``None``, never an empty list,
    and ``dead`` is then ``None`` too, no claim, with ``clusters.importers``
    named under ``unread``; where it read in part (a ``.py`` file left
    unparsed or unread) the three splits are partial and ``clusters.importers``
    is named too. Each split is
    given over every definition and over functions alone, and the census
    asserts the sum. A command a hand concern names that the pin does not hold
    is named under ``missing_commands``, never dropped in silence."""
    _tree, defs, g = _functions_ctx(ctx)
    edges = g["edges"]
    kinds = {d["name"]: d["kind"] for d in defs}
    lines = {d["name"]: d["lines"] for d in defs}
    commands = sorted(n for n in edges if n.startswith("cmd_") and kinds[n] == FUNCTION)
    entry = {n for n in ("main", "build_parser") if n in edges}
    from_entry = closure(edges, entry, stop=set(commands))
    external, tested = ctx.get("_external_names"), ctx.get("_test_names")
    if external is None:
        try:
            imp = _importers(ctx)
        except _READ_FAILURES as exc:
            imp = None
            _partial(ctx, "clusters", "importers", f"the importers read failed, so dead is no claim: {_unread(exc)}")
        if imp is not None:
            files = imp["files"].values()
            external = sorted({n for f in files if not f["test"] for n in f["names"]})
            tested = sorted({n for f in files if f["test"] for n in f["names"]})
            left = []
            if imp["unparsed"]:
                left.append(f"{len(imp['unparsed'])} file(s) unparsed {imp['unparsed'][:5]}")
            if imp["unread"]:
                left.append(f"{len(imp['unread'])} tracked .py file(s) unread {imp['unread'][:5]}")
            if left:
                _partial(ctx, "clusters", "importers", f"the importers read left {' and '.join(left)}, so "
                                                       f"external, tests_only and dead are partial")
    outside = closure(edges, [n for n in external or () if n in edges], stop=set(commands))
    in_tests = closure(edges, [n for n in tested or () if n in edges], stop=set(commands))
    fns = {n for n in edges if kinds[n] == FUNCTION}
    total_lines = sum(lines[n] for n in fns)
    file_lines = len(_ast_lines(source_at(ctx["root"], ctx["pin"]["at"], CLI) or ""))
    concerns = dict(ctx.get("concerns", CONCERNS))

    def size(s: set[str]) -> dict:
        return {"definitions": len(s), "functions": len(s & fns),
                "function_lines": sum(lines[m] for m in s if kinds[m] == FUNCTION)}

    def tally(roots: dict[str, set[str]]) -> dict:
        reached = _ownership(edges, roots, set(commands))
        owned = {m for m, r in reached.items() if len(r) == 1}
        shared = {m for m, r in reached.items() if len(r) > 1}
        unreached = set(edges) - owned - shared
        assert len(owned) + len(shared) + len(unreached) == len(defs), "ownership does not sum to the definitions"
        per = {r: sorted(m for m, rs in reached.items() if rs == {r}) for r in roots}
        rest = unreached - from_entry
        return {"owned": size(owned), "shared": size(shared), "unreached": size(unreached),
                "functions": {"owned": len(owned & fns), "shared": len(shared & fns),
                              "unreached": len(unreached & fns)},
                "unreached_entry": sorted(unreached & from_entry),
                "unreached_external": None if external is None else sorted(rest & outside),
                "unreached_tests_only": None if tested is None else sorted(rest - outside & in_tests),
                "unreached_dead": None if external is None or tested is None else sorted(rest - outside - in_tests),
                "per_root": {r: {**size(set(ms)), "members": ms} for r, ms in per.items()},
                "shared_by": {m: sorted(reached[m]) for m in sorted(shared)}}

    by_command = tally({c: {c} for c in commands})
    named = {c for group in concerns.values() for c in group}
    concern_roots = {name: {c for c in group if c in edges} for name, group in concerns.items()}
    concern_roots.update({c: {c} for c in commands if c not in named})
    by_concern = tally(concern_roots)
    overlap = {name: {c: len(closure(edges, {c}, stop=set(commands) - {c})) for c in group if c in edges}
               for name, group in concerns.items()}
    # A concern's reach is every function its commands reach; what it owns is
    # the part no command outside it reaches. The pack's "225 functions,
    # 10,905 lines, 61% of the file" at 17d83e0 is the owned part over the
    # file's lines; the reach is larger by the functions shared outside it.
    unions = {}
    for name in concerns:
        roots = concern_roots[name]
        reach = closure(edges, roots, stop=set(commands) - roots) & fns
        own = set(by_concern["per_root"][name]["members"]) & fns
        owned_lines = sum(lines[m] for m in own)
        unions[name] = {"reach": {"functions": len(reach), "function_lines": sum(lines[m] for m in reach)},
                        "owned": {"functions": len(own), "function_lines": owned_lines,
                                  "share_of_file_lines": round(owned_lines / file_lines, 3) if file_lines else None}}
    return {"definitions": len(defs), "commands": len(commands), "function_lines": total_lines,
            "file_lines": file_lines, "by_command": by_command,
            "concerns": {"cluster_source": "hand", "groups": {k: list(v) for k, v in concerns.items()},
                         "missing_commands": sorted({c for group in concerns.values() for c in group
                                                     if c not in edges}),
                         "closure_sizes": overlap, "concern_size": unions, **by_concern},
            "external_names_read": external is not None}


#: The module path every spelling of an import of cli resolves to.
CLI_MODULE = "espalier.cli"
#: The two runs of cli no move may change: the console entry and ``-m``.
CONSOLE_ENTRY = "espalier.cli:main"
MODULE_RUN = "-m espalier.cli"


def _package_of(path: str) -> str:
    return ".".join(Path(path).with_suffix("").parts[:-1])


def _absolute(path: str, node: ast.ImportFrom) -> str:
    """The absolute module an ``ImportFrom`` names, a relative one resolved
    against ``path``'s package."""
    if not node.level:
        return node.module or ""
    base = _package_of(path).split(".")
    base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
    return ".".join([*base, node.module] if node.module else base)


def imports_of_cli(path: str, tree: ast.Module) -> list[dict]:
    """Each import of cli in one file, by AST: ``from espalier.cli import X``
    (relative spellings resolved), and an alias bound to the module itself
    (``from espalier import cli as _cli``, ``import espalier.cli``), whose
    names are the attributes loaded through it. ``lazy`` is an import inside
    a function or class body: an outbound edge that loads at call time. One in
    a module-level ``if`` or ``try`` (``try: from espalier.cli import main``)
    runs at import time, so it is top-level (``_top_statements``)."""
    top = {id(n) for n in _top_statements(tree.body)}
    out: list[dict] = []
    aliases: dict[str, bool] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = _absolute(path, node)
            if module == CLI_MODULE:
                out.append({"names": sorted(a.name for a in node.names), "line": node.lineno,
                            "lazy": id(node) not in top, "via": "from"})
            elif module == "espalier":
                for a in node.names:
                    if a.name == "cli":
                        aliases[a.asname or "cli"] = aliases.get(a.asname or "cli", True) and id(node) not in top
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == CLI_MODULE:
                    aliases[a.asname or CLI_MODULE] = id(node) not in top
    for alias, lazy in aliases.items():
        dotted = alias.split(".")
        names: set[str] = set()
        loaded: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                chain, cur = [], node.value
                while isinstance(cur, ast.Attribute):
                    chain.insert(0, cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name) and [cur.id, *chain] == dotted:
                    names.add(node.attr)
                    if isinstance(node.ctx, ast.Load):
                        loaded.add(node.attr)
        # ``stored_only``: names the file only assigns or deletes through the
        # alias (``cli.X = ...``), never reads; they are in ``names`` too.
        out.append({"names": sorted(names), "line": None, "lazy": lazy, "via": f"alias {alias}",
                    "stored_only": sorted(names - loaded)})
    return out


def _is_namespace_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Name) and node.func.id == "Namespace")
        or (isinstance(node.func, ast.Attribute) and node.func.attr == "Namespace"))


_FUNCTION_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _own_nodes(scope: ast.AST):
    """The nodes of one scope (the module or one function or class): its body,
    a nested function's or class's body left to that scope, whose decorators,
    defaults, bases and keywords are this scope's (as its own are the scope
    around it)."""
    stack = list(scope.body) if isinstance(scope.body, list) else [scope.body]
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _FUNCTION_SCOPES):
            stack.extend(n for n in (*getattr(node, "decorator_list", ()), *getattr(node, "bases", ()),
                                     *(k.value for k in getattr(node, "keywords", ()))) if n is not None)
            if not isinstance(node, ast.ClassDef):
                stack.extend(n for n in (*node.args.defaults, *node.args.kw_defaults) if n is not None)
            continue
        stack.extend(ast.iter_child_nodes(node))


def namespace_calls(tree: ast.Module, names: set[str], aliases: set[str]) -> list[dict]:
    """Each call, in one importer of cli, of a name it takes from cli that is
    handed an ``argparse.Namespace`` built by hand: passed directly, or through
    a name bound to one, read as Python resolves the name: in the call's own
    function, else the functions around it, else the module (a class body is
    not seen from a method). A Namespace one function builds is no argument of
    a call in another. The attributes it sets are a contract no parser checks,
    so a move that changes the command's attributes breaks the caller with
    nothing to catch it. ``names`` are the names the file takes; ``aliases``
    the names it binds to cli itself (``_cli.cmd_x(ns)``)."""
    scopes: list[ast.AST] = [tree, *(n for n in ast.walk(tree) if isinstance(n, _FUNCTION_SCOPES))]
    parent_of: dict[int, ast.AST | None] = {id(tree): None}
    for scope in scopes:
        for node in _own_nodes(scope):
            if isinstance(node, _FUNCTION_SCOPES):
                parent_of[id(node)] = scope
    bound: dict[int, set[str]] = {}
    built: dict[int, dict[str, ast.Call]] = {}
    for scope in scopes:
        here: set[str] = set()
        made: dict[str, ast.Call] = {}
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = scope.args
            here |= {x.arg for x in (*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg) if x is not None}
        for node in _own_nodes(scope):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                here.add(node.id)
            elif isinstance(node, _FUNCTION_SCOPES):
                here.add(getattr(node, "name", ""))
            if isinstance(node, ast.Assign) and _is_namespace_call(node.value):
                made.update({t.id: node.value for t in node.targets if isinstance(t, ast.Name)})
        bound[id(scope)], built[id(scope)] = here, made

    def namespace_named(name: str, scope: ast.AST) -> ast.Call | None:
        cur, first = scope, True
        while cur is not None:
            if first or not isinstance(cur, ast.ClassDef):
                if name in bound[id(cur)]:
                    return built[id(cur)].get(name)
            cur, first = parent_of.get(id(cur)), False
        return None

    out: dict[tuple[str, int], dict] = {}
    for scope in scopes:
        for sub in _own_nodes(scope):
            if not isinstance(sub, ast.Call):
                continue
            f = sub.func
            called = (f.id if isinstance(f, ast.Name) else
                      f.attr if isinstance(f, ast.Attribute) and _dotted(f.value) in aliases else None)
            if called not in names:
                continue
            for arg in [*sub.args, *(k.value for k in sub.keywords)]:
                ns = arg if _is_namespace_call(arg) else namespace_named(arg.id, scope) if isinstance(arg, ast.Name) else None
                if ns is not None:
                    out[(called, sub.lineno)] = {"name": called, "line": sub.lineno,
                                                 "attributes": sorted(k.arg for k in ns.keywords if k.arg)}
    return [out[k] for k in sorted(out)]


def _importers(ctx: dict) -> dict:
    if "_importers" in ctx:
        return ctx["_importers"]
    root, at = ctx["root"], ctx["pin"]["at"]
    tracked = tracked_at(root, at)
    py = [p for p in tracked if p.endswith(".py") and p not in ctx["modules"]]
    texts = blobs_at(root, at, py)
    files: dict[str, dict] = {}
    statements: dict[str, list[dict]] = {}
    namespaces: dict[str, list[dict]] = {}
    unparsed = []
    for path in sorted(texts):
        if "espalier.cli" not in texts[path] and "cli" not in texts[path]:
            continue
        try:
            tree = ast.parse(texts[path])
        except (SyntaxError, ValueError):
            unparsed.append(path)
            continue
        found = imports_of_cli(path, tree)
        if found:
            files[path] = {"names": sorted({n for f in found for n in f["names"]}),
                           "lazy": any(f["lazy"] for f in found), "sites": len(found),
                           "test": path.startswith("tests/")}
            statements[path] = found
            if not files[path]["test"]:
                namespaces[path] = namespace_calls(tree, set(files[path]["names"]),
                                                   {f["via"].split(" ", 1)[1] for f in found if f["via"] != "from"})
    ctx["_importers"] = {"files": files, "unparsed": unparsed, "read": len(texts), "tracked_py": len(py),
                         "unread": sorted(set(py) - set(texts)),
                         "tracked": tracked, "statements": statements, "namespaces": namespaces}
    return ctx["_importers"]


def section_importers(ctx: dict) -> dict:
    """Who imports cli at the pin, by AST over every tracked ``.py`` file:
    each file with the names it takes, whether lazily, and the totals outside
    tests and in them, kept apart. Then the two runs no move may change: the
    console entry in ``pyproject.toml`` and each tracked file that runs
    ``python -m espalier.cli`` (read as text, every file type). A ``.py`` file
    that does not parse or cannot be read, a file the run scan cannot read, and
    a pin with no ``pyproject.toml`` (``console_entry`` is ``None``) are each
    named under ``unread`` as ``importers.<part>``."""
    imp = _importers(ctx)
    root, at = ctx["root"], ctx["pin"]["at"]
    outside = {p: f for p, f in imp["files"].items() if not f["test"]}
    tests = {p: f for p, f in imp["files"].items() if f["test"]}
    pyproject = source_at(root, at, "pyproject.toml")
    scanned = [p for p in imp["tracked"] if p not in ctx["modules"]]
    texts = blobs_at(root, at, scanned)
    if imp["unparsed"]:
        _partial(ctx, "importers", "unparsed", f"{len(imp['unparsed'])} .py file(s) that name cli do not parse, "
                                               f"so their imports are not read: {imp['unparsed'][:5]}")
    if imp["unread"]:
        _partial(ctx, "importers", "py_files", f"{len(imp['unread'])} tracked .py file(s) could not be read: "
                                               f"{imp['unread'][:5]}")
    if len(texts) < len(scanned):
        gone = sorted(set(scanned) - set(texts))
        _partial(ctx, "importers", "module_runs", f"{len(gone)} tracked file(s) could not be read for the "
                                                  f"-m espalier.cli scan: {gone[:5]}")
    if pyproject is None:
        _partial(ctx, "importers", "console_entry", f"pyproject.toml is not in {at[:12]}")
    module_runs = sorted(p for p, t in texts.items() if "espalier.cli" in t
                         and ("-m espalier.cli" in t or '"-m", "espalier.cli"' in t or "'-m', 'espalier.cli'" in t))
    by_kind: dict[str, list[str]] = {"code": [], "docs": [], "tests": [], "records": []}
    for p in module_runs:
        by_kind[_run_kind(p)].append(p)
    return {"rule": "ast: ImportFrom resolving to espalier.cli, and attributes loaded through an alias of it",
            "py_files_read": imp["read"], "py_files_tracked": imp["tracked_py"], "unparsed": imp["unparsed"],
            "outside_tests": {"files": len(outside), "distinct_names": len({n for f in outside.values() for n in f["names"]}),
                              "by_file": outside},
            "tests": {"files": len(tests), "distinct_names": len({n for f in tests.values() for n in f["names"]})},
            "entry_points": {"console_entry": None if pyproject is None else CONSOLE_ENTRY in pyproject,
                             "module_run": {k: {"files": len(v), "paths": v} for k, v in by_kind.items()}}}


def _run_kind(path: str) -> str:
    """Where a ``-m espalier.cli`` mention lives: a record (a pack, a ledger
    row, memory; dated, never re-keyed), a test, a doc (adopters read the
    shipped copy), or code that runs it."""
    if path.startswith(("task-packs/", "memory/")):
        return "records"
    if path.startswith("tests/"):
        return "tests"
    return "docs" if path.endswith(".md") else "code"


#: The callables a test patches with: ``monkeypatch``'s, ``mock.patch`` and
#: its ``object``/``dict`` forms, by the last attribute of the call.
_PATCHERS = {"setattr": "setattr", "delattr": "delattr", "object": "patch.object", "dict": "patch.dict",
             "patch": "mock.patch", "setitem": "setitem"}
#: The last names one of those attributes must sit on to be a patcher: a
#: monkeypatch is bound to any name (``monkeypatch``, ``mp``, ``m``), so its
#: ``setattr``/``delattr``/``setitem`` take any; ``object`` and ``dict`` are
#: ``patch``'s (``patch.object``, ``mock.patch.dict``, ``mocker.patch.object``),
#: and ``patch`` is ``mock``'s or ``mocker``'s. A bare name is a patcher only as
#: ``setattr``, ``delattr``, ``setitem`` or ``patch``: a builtin ``dict(...)`` or
#: ``object()`` patches nothing. One of those attributes on any other base
#: (``mpatch.object``, an aliased ``patch``; ``um.patch``, an aliased ``mock``;
#: ``something.object``) is a patcher the census cannot tell is one.
_PATCHER_BASES = {"object": ("patch",), "dict": ("patch",), "patch": ("mock", "mocker")}
_PATCHER_NAMES = ("setattr", "delattr", "setitem", "patch")


def _patcher_kind(func: ast.AST) -> tuple[str | None, bool]:
    """``(kind, known)``: the patcher a call's callable names (``None`` for
    none), and whether its base is one ``_PATCHER_BASES`` admits (a bare name,
    and monkeypatch's attributes on any name, always are)."""
    if isinstance(func, ast.Name):
        return (_PATCHERS[func.id], True) if func.id in _PATCHER_NAMES else (None, False)
    if not isinstance(func, ast.Attribute) or func.attr not in _PATCHERS:
        return None, False
    need = _PATCHER_BASES.get(func.attr)
    base = func.value
    last = base.attr if isinstance(base, ast.Attribute) else base.id if isinstance(base, ast.Name) else None
    return _PATCHERS[func.attr], need is None or last in need


def _import_call_module(node: ast.AST) -> str | None:
    """The module a call with a constant name returns: ``__import__("a.b")``
    the top package ``a`` (no ``fromlist``), ``importlib.import_module("a.b")``
    (or a bare ``import_module``) ``a.b`` itself; else ``None``."""
    if not (isinstance(node, ast.Call) and len(node.args) == 1 and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str) and not node.args[0].value.startswith(".")):
        return None
    f = node.func
    called = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
    if called == "__import__" and not node.keywords:
        return node.args[0].value.split(".")[0]
    if called == "import_module" and not node.keywords:
        return node.args[0].value
    return None


def _cli_chain(node: ast.AST, aliases: set[str]) -> tuple[bool, list[str] | None]:
    """``(resolved, chain)`` for a patcher's first argument: ``chain`` is the
    attributes after the cli module (``[]`` for cli itself) where the argument
    reaches cli, through an alias of it, ``__import__("espalier.cli").cli`` or
    ``importlib.import_module("espalier.cli")``, else ``None``. ``resolved`` is
    False where the census cannot tell statically what the argument is (a
    subscript, a call, ``getattr(import_module("espalier." + m), a)``)."""
    dotted = _dotted(node)
    if dotted is not None:
        for a in sorted(aliases, key=len, reverse=True):
            if dotted == a:
                return True, []
            if dotted.startswith(a + "."):
                return True, dotted[len(a) + 1:].split(".")
        return True, None
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.insert(0, cur.attr)
        cur = cur.value
    module = _import_call_module(cur)
    if module is None:
        return False, None
    full = ".".join([module, *parts])
    if full == CLI_MODULE:
        return True, []
    return True, full[len(CLI_MODULE) + 1:].split(".") if full.startswith(CLI_MODULE + ".") else None


def _shadowed_heads(tree: ast.Module, heads: set[str]) -> dict[int, set[str]]:
    """``{id(node): heads}`` for each node in the body of a function or
    lambda that takes a parameter named like the first name of an alias of
    cli (a fixture ``cli``): there that name is the parameter, which the
    census cannot resolve, never the import (another alias stays the import).
    The function's own decorators, defaults and annotations are read in the
    scope around it, where the name is still the import (as ``_module_refs``
    reads them)."""
    out: dict[int, set[str]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        a = fn.args
        hidden = {x.arg for x in (*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg) if x is not None} & heads
        if hidden:
            for stmt in [fn.body] if isinstance(fn, ast.Lambda) else fn.body:
                for n in ast.walk(stmt):
                    out.setdefault(id(n), set()).update(hidden)
    return out


def _through_shadow(node: ast.AST, first: ast.AST, shadowed: dict[int, set[str]]) -> bool:
    """Whether ``first`` reaches cli by a name a parameter around ``node`` shadows."""
    dotted = _dotted(first)
    return dotted is not None and dotted.split(".")[0] in shadowed.get(id(node), ())


def cli_aliases(tree: ast.Module) -> set[str]:
    """The dotted names a test file binds to the cli module itself: ``from
    espalier import cli [as x]``, ``import espalier.cli [as x]``, and a name
    assigned an import call that returns cli (``_cli_chain``:
    ``x = importlib.import_module("espalier.cli")``, a bare
    ``import_module("espalier.cli")``, ``__import__("espalier.cli").cli``),
    anywhere in the file."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "espalier" and not node.level:
            out.update(a.asname or "cli" for a in node.names if a.name == "cli")
        elif isinstance(node, ast.Import):
            out.update(a.asname or CLI_MODULE for a in node.names if a.name == CLI_MODULE)
        elif isinstance(node, ast.Assign) and _cli_chain(node.value, set()) == (True, []):
            out.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return out


def _dotted(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.insert(0, node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return ".".join([node.id, *parts])
    return None


def patch_sites(tree: ast.Module) -> tuple[list[dict], int]:
    """``(sites, unresolved_owner)``: each site in one test file that patches a
    name on cli, and the count of patcher calls whose first argument the census
    cannot resolve statically, so a site it misses is still counted somewhere.
    A site: a patcher (``_patcher_kind``) called on cli and a constant name
    (``setattr(cli, "X", ...)``, ``patch.object(cli, "X")``, ``delattr``), cli
    read through an alias, ``__import__("espalier.cli").cli`` or
    ``importlib.import_module("espalier.cli")``; a string target
    (``"espalier.cli.X"``); or an assignment ``cli.X = ...``. A patcher called
    on an attribute OF cli (``setattr(cli.shutil, "which", ...)``) patches
    another module through cli: ``through`` names it. ``setitem`` and
    ``patch.dict`` patch the object they are handed, so
    ``setitem(cli.REG, "k", v)`` and ``patch.dict(cli.REG)`` patch cli's
    ``REG``, as ``patch.dict("espalier.cli.REG")`` does. Inside a function
    that takes a parameter named like the alias the name is that parameter:
    unresolved, never cli. A string target is a site whatever the patcher's
    base is named (``um.patch("espalier.cli.Y")``, ``mocker_fixture.patch``);
    a patcher attribute on a base ``_patcher_kind`` does not know
    (``mpatch.object(cli, "X")``) whose first argument reaches cli is
    unresolved, never dropped."""
    aliases = cli_aliases(tree)
    shadowed = _shadowed_heads(tree, {a.split(".")[0] for a in aliases})
    sites: list[dict] = []
    unresolved = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            kind, known = _patcher_kind(node.func)
            if kind is None or not node.args:
                continue
            raising = next((k.value for k in node.keywords if k.arg == "raising"), None)
            raising_false = isinstance(raising, ast.Constant) and raising.value is False
            first = node.args[0]
            if isinstance(first, ast.Constant):
                if isinstance(first.value, str) and first.value.startswith(CLI_MODULE + "."):
                    rest = first.value[len(CLI_MODULE) + 1:]
                    sites.append({"target": rest.split(".")[0], "through": rest if "." in rest else None,
                                  "kind": kind, "spelling": "string", "line": node.lineno,
                                  "raising_false": raising_false})
                continue
            resolved, chain = _cli_chain(first, aliases)
            if not known:
                unresolved += 1 if chain is not None else 0
                continue
            if not resolved or (chain is not None and _through_shadow(node, first, shadowed)):
                unresolved += 1
                continue
            if chain is None:
                continue
            name = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else None
            if not chain:
                if isinstance(name, str):
                    sites.append({"target": name, "through": None, "kind": kind, "spelling": "alias",
                                  "line": node.lineno, "raising_false": raising_false})
                continue
            attr = ".".join(chain)
            if kind in ("setitem", "patch.dict"):
                through = attr if len(chain) > 1 else None
            else:
                through = f"{attr}.{name}" if isinstance(name, str) else attr
            sites.append({"target": chain[0], "through": through, "kind": kind, "spelling": "alias",
                          "line": node.lineno, "raising_false": raising_false})
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if not isinstance(t, ast.Attribute):
                    continue
                _resolved, chain = _cli_chain(t.value, aliases)
                if chain == [] and _through_shadow(node, t.value, shadowed):
                    unresolved += 1
                elif chain == []:
                    sites.append({"target": t.attr, "through": None, "kind": "assign", "spelling": "alias",
                                  "line": node.lineno, "raising_false": False})
    return sites, unresolved


def section_patches(ctx: dict) -> dict:
    """The test patches on cli at the pin, by AST over ``tests/``: distinct
    targets, sites and files; which targets cli defines and which it imports
    from elsewhere (a new module gets its own binding of those); how many
    definitions in cli load each target (a target with more than one loader
    stays green under a partial move); ``raising=False`` sites, which create a
    missing attribute in silence; and the patches of another module through
    cli. Every figure is over the CLI modules' first entry, ``espalier/cli.py``.
    ``unresolved_owner`` counts the patcher calls whose first argument the
    census cannot resolve statically (``getattr(import_module(...), a)``,
    ``sys.modules[...]``, a fixture parameter named like the alias), so a
    patch of cli the AST read misses still shows. A test file that does not
    parse or cannot be read is named under ``unread`` (``patches.unparsed``,
    ``patches.tests``)."""
    root, at = ctx["root"], ctx["pin"]["at"]
    tests = [p for p in tracked_at(root, at) if p.startswith("tests/") and p.endswith(".py")]
    texts = blobs_at(root, at, tests)
    tree_cli, defs = parse_cli(root, at)
    defined = {d["name"] for d in defs}
    by_file: dict[str, list[dict]] = {}
    unresolved: dict[str, int] = {}
    unparsed = []
    for path in sorted(texts):
        if "cli" not in texts[path]:
            continue
        try:
            found, missed = patch_sites(ast.parse(texts[path]))
        except (SyntaxError, ValueError):
            unparsed.append(path)
            continue
        if found:
            by_file[path] = found
        if missed:
            unresolved[path] = missed
    if unparsed:
        _partial(ctx, "patches", "unparsed", f"{len(unparsed)} test file(s) that name cli do not parse, so their "
                                             f"patches are not read: {unparsed[:5]}")
    if len(texts) < len(tests):
        gone = sorted(set(tests) - set(texts))
        _partial(ctx, "patches", "tests", f"{len(gone)} tracked test file(s) could not be read: {gone[:5]}")
    on_cli = [(p, s) for p, ss in by_file.items() for s in ss if s["through"] is None]
    through = [(p, s) for p, ss in by_file.items() for s in ss if s["through"] is not None]
    targets = sorted({s["target"] for _p, s in on_cli})
    loader_names: dict[str, list[str]] = {t: [] for t in targets}
    for d in defs:
        if d["kind"] == NAME:
            continue
        refs, _writes = _module_refs(d["node"])
        seen = {n.id for n in ast.walk(d["node"]) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                and id(n) in refs}
        for t in targets:
            if t in seen and t != d["name"]:
                loader_names[t].append(d["name"])
    loaders = {t: len(v) for t, v in loader_names.items()}
    # Kept for the move cost, which prices each site and loader by unit.
    ctx["_patch_sites"] = [(p, s) for p, s in on_cli]
    ctx["_patch_loaders"] = loader_names
    sites_of = {t: sum(1 for _p, s in on_cli if s["target"] == t) for t in targets}
    multi = [t for t in targets if loaders[t] > 1]
    imported = [t for t in targets if t not in defined]
    raising = {t: {"sites": sites_of[t], "raising_false": sum(1 for _p, s in on_cli if s["target"] == t and s["raising_false"])}
               for t in targets if any(s["target"] == t and s["raising_false"] for _p, s in on_cli)}
    return {"rule": "ast over tests/: a patcher (monkeypatch's setattr/delattr/setitem on any name; patch.object, "
                    "patch.dict, mock.patch) on espalier.cli (an alias of it, __import__('espalier.cli').cli, "
                    "importlib.import_module('espalier.cli')) with a constant name, a string target "
                    "'espalier.cli.X', or an assignment to an attribute of the alias; setitem and patch.dict "
                    "patch the object handed them",
            "files": len({p for p, _s in on_cli}), "sites": len(on_cli), "targets": len(targets),
            "unresolved_owner": {"calls": sum(unresolved.values()), "by_file": dict(sorted(unresolved.items()))},
            "by_kind": {k: sum(1 for _p, s in on_cli if s["kind"] == k) for k in sorted({s["kind"] for _p, s in on_cli})},
            "string_targets": sum(1 for _p, s in on_cli if s["spelling"] == "string"),
            "more_than_one_loader": {"targets": len(multi), "sites": sum(sites_of[t] for t in multi)},
            "imported_into_cli": {"targets": len(imported), "sites": sum(sites_of[t] for t in imported),
                                  "names": imported},
            "no_loader": sorted(t for t in targets if loaders[t] == 0 and t in defined),
            "raising_false": raising,
            "through_cli": {"sites": len(through), "targets": sorted({s["through"] for _p, s in through})},
            "per_target": {t: {"sites": sites_of[t], "loaders": loaders[t]} for t in targets},
            "unparsed": unparsed}


# ---------------------------------------------------------------- readers, citations, probes, ledger rows, doctor

def _tracked_texts(ctx: dict) -> dict[str, str]:
    """Every tracked file's text at the pin, read once a run in one batch. A
    blob holding a NUL is binary and left out; the tracked, read, binary and
    unread counts go in ``ctx["_texts_meta"]`` so a section can say what it read."""
    if "_texts" not in ctx:
        root, at = ctx["root"], ctx["pin"]["at"]
        tracked = tracked_at(root, at)
        texts = blobs_at(root, at, tracked)
        ctx["_texts"] = {p: t for p, t in texts.items() if "\x00" not in t}
        ctx["_texts_meta"] = {"tracked": len(tracked), "read": len(texts),
                              "binary": sorted(p for p, t in texts.items() if "\x00" in t),
                              "unread": sorted(set(tracked) - set(texts))}
    return ctx["_texts"]


def _texts_for(ctx: dict, section: str) -> dict[str, str]:
    """``_tracked_texts`` for one section, which names ``<section>.texts`` under
    ``unread`` where a tracked file could not be read: what it counts is then
    over the files read, a lower bound."""
    texts = _tracked_texts(ctx)
    unread = ctx["_texts_meta"]["unread"]
    if unread:
        _partial(ctx, section, "texts", f"{len(unread)} tracked file(s) could not be read at the pin: {unread[:5]}")
    return texts


def _clusters(ctx: dict) -> dict:
    if "_clusters" not in ctx:
        ctx["_clusters"] = section_clusters(ctx)
    return ctx["_clusters"]


def _owners(ctx: dict) -> dict[str, dict]:
    """``{definition: owner}`` from the clusters section's ownership: ``owned_by``
    one command, ``shared_by`` several, or ``unreached`` (``entry``,
    ``external``, ``tests_only``, ``dead``), with the concern that owns it (or
    the concerns that share it) beside. Where the importers read failed, an
    unreached definition the split cannot place is ``{"unreached": None}``,
    never one cli does not define."""
    if "_owners" not in ctx:
        cl = _clusters(ctx)
        by, con = cl["by_command"], cl["concerns"]
        out: dict[str, dict] = {}
        for cmd, row in by["per_root"].items():
            for m in row["members"]:
                out[m] = {"owned_by": cmd}
        for m, cmds in by["shared_by"].items():
            out[m] = {"shared_by": cmds}
        for kind in ("entry", "external", "tests_only", "dead"):
            for m in by[f"unreached_{kind}"] or ():
                out[m] = {"unreached": kind}
        for d in _functions_ctx(ctx)[1]:
            out.setdefault(d["name"], {"unreached": None})
        for name, row in con["per_root"].items():
            for m in row["members"]:
                out.setdefault(m, {})["concern"] = name
        for m, roots in con["shared_by"].items():
            out.setdefault(m, {})["concern_shared_by"] = roots
        ctx["_owners"] = out
    return ctx["_owners"]


def _owner_of(owners: dict[str, dict], name: str) -> dict:
    return owners.get(name.split(".", 1)[0], {"not_in_cli": True})


def _commands_of(owner: dict) -> list[str]:
    return [owner["owned_by"]] if "owned_by" in owner else list(owner.get("shared_by", []))


#: The readers of cli.py by path that are not loud, ``classified_by: hand`` (the
#: architecture review's read at 17d83e0, pack Task 3). ``silent``: it asserts
#: something of cli.py's text that code moved out of the file escapes with no
#: red. ``flat-module``: it scans only the top-level ``espalier/*.py``, so a
#: subpackage escapes it. A symbol of ``None`` is the whole file; ``A::b`` is a
#: method of a class. Each is checked to exist at the pin and a gone one is
#: named. A site inside a listed span takes its class; every other site the
#: AST read finds is ``loud`` (red on a move: a cost, not a risk).
READER_CLASSES: tuple[tuple[str, str | None, str], ...] = (
    ("tests/test_init_interactive_arming.py", "test_no_raw_sys_isatty_calls_in_cli", "silent"),
    ("tests/test_python_floor.py",
     "TestFloorAtTheThreeDecisionSites::test_the_two_python_2_admitting_predicates_are_narrowed_together",
     "silent"),
    ("tests/test_hook_contracts.py", "test_no_stray_literal_ten_for_stop", "silent"),
    ("tests/test_cli_deploy.py", "test_no_naked_write_text_anywhere_in_cli", "silent"),
    ("tests/test_no_bare_espalier_hints.py", "SCANNED_FILES", "silent"),
    ("tools/cc/sister_site_probe.py", None, "flat-module"),
    ("tests/test_python_floor.py", "test_every_engine_verdict_memo_is_cleared_between_tests", "flat-module"),
)
#: Where the path readers are looked for: every tracked ``.py`` under these, and the files named.
READER_ROOTS = ("tests/", "scripts/")
READER_FILES = ("tools/cc/sister_site_probe.py",)
READER_KINDS = ("symbol_key", "path_literal", "path_join")
READER_CLASS_NAMES = ("loud", "silent", "flat-module")


def named_spans(tree: ast.Module) -> dict[str, list[tuple[int, int]]]:
    """Every function, class and module-level assigned name in one file with
    its line span, keyed by its qualified name (``Class::method``) and, for a
    nested one, by its bare name too."""
    out: dict[str, list[tuple[int, int]]] = {}

    def visit(body: list[ast.stmt], prefix: str) -> None:
        for node in _top_statements(body):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                span = (min([node.lineno] + [d.lineno for d in node.decorator_list]), node.end_lineno)
                for key in {prefix + node.name, node.name}:
                    out.setdefault(key, []).append(span)
                visit(node.body, f"{prefix}{node.name}::")
            elif not prefix and isinstance(node, (ast.Assign, ast.AnnAssign)):
                for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                    for name in _store_names(target):
                        out.setdefault(name, []).append((node.lineno, node.end_lineno))

    visit(tree.body, "")
    return out


def reader_sites(tree: ast.Module, modules) -> tuple[list[dict], int]:
    """``(sites, loose)``: each place one file reads a CLI module by its path,
    by AST. A ``(module path, symbol)`` tuple key, its second element a name
    (``("espalier/cli.py", "espalier/x.py")`` is two paths, no key); a string
    constant equal to the module's path (a key's first element is the key's,
    never counted twice); and a path join whose right operand is the module's
    file name (``ROOT / "espalier" / "cli.py"``), which counts a join by the
    file name alone, so a fixture's write of ``tmp_path / "espalier" / "cli.py"``
    is one as a read of the repository's module is. A comment or a docstring that
    names the path reads nothing. ``loose`` counts the file name as a constant
    outside a join (``Path(..., "cli.py")``), a spelling no class is given."""
    paths, names = set(modules), {Path(m).name for m in modules}
    in_key: set[int] = set()
    joins: set[int] = set()
    sites: list[dict] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Tuple) and len(node.elts) == 2
                and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts)
                and node.elts[0].value in paths and re.fullmatch(r"[A-Za-z_][\w.]*", node.elts[1].value)):
            in_key.add(id(node.elts[0]))
            sites.append({"kind": "symbol_key", "line": node.lineno, "symbol": node.elts[1].value})
        elif (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
              and isinstance(node.right, ast.Constant) and node.right.value in names):
            joins.add(id(node.right))
            sites.append({"kind": "path_join", "line": node.right.lineno})
    loose = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in paths and id(node) not in in_key:
                sites.append({"kind": "path_literal", "line": node.lineno})
            elif node.value in names and id(node) not in joins:
                loose += 1
    return sorted(sites, key=lambda s: (s["line"], s["kind"])), loose


def section_readers(ctx: dict) -> dict:
    """The tests and scripts that read cli.py by its path (its text, never an
    import), by AST over every tracked ``.py`` under ``tests/`` and
    ``scripts/`` and the files ``READER_FILES`` names: each site by kind, with
    its file, classed ``loud``, ``silent`` or ``flat-module`` by the hand list
    (``READER_CLASSES``, ``classified_by: hand``), each entry checked to exist
    at the pin. A flat-module reader globs ``espalier/*.py`` and may hold no
    site at all: it is listed with its count, zero included. A scanned file
    that does not parse holds sites the read cannot see: it is named under
    ``unread`` as ``readers.unparsed``, and a file that could not be read as
    ``readers.texts``."""
    texts = _texts_for(ctx, "readers")
    modules = ctx["modules"]
    hand = tuple(ctx.get("reader_classes", READER_CLASSES))
    scanned = sorted(p for p in texts if p.endswith(".py") and (p.startswith(READER_ROOTS) or p in READER_FILES))
    trees: dict[str, ast.Module] = {}
    unparsed = []
    for p in sorted(set(scanned) | {h[0] for h in hand if h[0] in texts}):
        try:
            trees[p] = ast.parse(texts[p])
        except (SyntaxError, ValueError):
            unparsed.append(p)
    if unparsed:
        _partial(ctx, "readers", "unparsed", f"{len(unparsed)} file(s) do not parse, so their sites are not read "
                                             f"(a hand entry in one reads as missing): {unparsed[:5]}")
    entries = []
    for path, symbol, klass in hand:
        tree = trees.get(path)
        if tree is None:
            spans: list[tuple[int, int]] = []
        elif symbol is None:
            spans = [(1, max(1, len(_ast_lines(texts[path]))))]
        else:
            spans = named_spans(tree).get(symbol, [])
        entries.append({"path": path, "symbol": symbol, "class": klass, "exists": bool(spans), "spans": spans})

    def inside(entry: dict, path: str, line: int) -> bool:
        return entry["path"] == path and any(a <= line <= b for a, b in entry["spans"])

    rows, loose_files = [], {}
    # Two looser reads, kept beside: every constant equal to the path (a key's
    # first element included), and every 2-tuple whose first element is it.
    loose_reads: dict[str, dict[str, int]] = {"literals_with_key_elements": {}, "keys_any_second_element": {}}
    for p in scanned:
        if p not in trees:
            continue
        found, loose = reader_sites(trees[p], modules)
        if loose:
            loose_files[p] = loose
        for node in ast.walk(trees[p]):
            if isinstance(node, ast.Constant) and node.value in modules:
                loose_reads["literals_with_key_elements"][p] = loose_reads["literals_with_key_elements"].get(p, 0) + 1
            elif (isinstance(node, ast.Tuple) and len(node.elts) == 2 and isinstance(node.elts[0], ast.Constant)
                  and node.elts[0].value in modules):
                loose_reads["keys_any_second_element"][p] = loose_reads["keys_any_second_element"].get(p, 0) + 1
        for s in found:
            klass = next((e["class"] for e in entries if inside(e, p, s["line"])), "loud")
            rows.append({**s, "path": p, "class": klass})
    ctx["_reader_rows"] = rows  # kept for the move cost, which prices each symbol key by unit
    for e in entries:
        e["sites"] = sum(1 for r in rows if inside(e, r["path"], r["line"]))
        # A test that reads the file through a module-level name (``CLI_PATH =
        # REPO_ROOT / "espalier" / "cli.py"``) holds no site of its own: the
        # names it loads whose binding holds one are named, the site left loud.
        tree = trees.get(e["path"])
        e["via"] = []
        if tree is not None and e["symbol"] is not None and e["spans"]:
            bound = {n: s for n, s in named_spans(tree).items() if "::" not in n}
            loaded = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                      and any(a <= n.lineno <= b for a, b in e["spans"])}
            e["via"] = sorted(n for n in loaded if n in bound and n != e["symbol"] and any(
                r["path"] == e["path"] and any(a <= r["line"] <= b for a, b in bound[n]) for r in rows))

    def tally(rs: list[dict]) -> dict:
        return {k: {"sites": sum(1 for r in rs if r["kind"] == k),
                    "files": len({r["path"] for r in rs if r["kind"] == k})} for k in READER_KINDS}

    files: dict[str, dict] = {}
    for r in rows:
        f = files.setdefault(r["path"], {**{k: 0 for k in READER_KINDS}, "classes": set()})
        f[r["kind"]] += 1
        f["classes"].add(r["class"])
    return {"rule": "ast over tracked .py under tests/ and scripts/ and READER_FILES: a (module path, str) tuple, "
                    "a str constant equal to the module path (outside such a tuple), a '/' join whose right "
                    "operand is the module's file name; the path_join kind counts joins by the file name, a read "
                    "of the repository's module and a fixture's write into a tmp tree alike",
            "files_scanned": len(scanned), "unparsed": unparsed,
            "by_kind": tally(rows),
            "by_class": {c: tally([r for r in rows if r["class"] == c]) for c in READER_CLASS_NAMES},
            "keyed_symbols": sorted({r["symbol"] for r in rows if r["kind"] == "symbol_key"}),
            "hand": {"classified_by": "hand", "entries": entries,
                     "missing": [f"{e['path']}::{e['symbol']}" for e in entries if not e["exists"]]},
            "files": {p: {**f, "classes": sorted(f["classes"])} for p, f in sorted(files.items())},
            "beside": {"file_name_constants_outside_a_join": {"sites": sum(loose_files.values()),
                                                              "files": sorted(loose_files)},
                       **{k: {"sites": sum(v.values()), "files": len(v)} for k, v in loose_reads.items()}}}


#: The sweep that reds a moved citation (``tests/test_doc_source_citations.py``)
#: chooses its population by these functions, which this census ports
#: (``_is_swept``, ``_is_pack``, ``_is_struck_line``). Each is pinned by a digest
#: of its text (``rule_digest``) as it reads at 3330a5a and 17d83e0 alike. A pin
#: where one reads otherwise has its swept and unchecked splits named unread,
#: never guessed. The rules' data (the record set, the regexes, the pack
#: folders and pattern) are read from the pin by AST, never copied here.
SWEEP_TEST = "tests/test_doc_source_citations.py"
SURFACE_CONTRACT = "espalier/surface_contract.py"
SWEEP_RULES: dict[tuple[str, str], str] = {
    (SWEEP_TEST, "_swept_docs"): "3fc6159a4d20c519",
    (SWEEP_TEST, "_is_struck_row"): "0aa74225d63b1020",
    (SURFACE_CONTRACT, "is_shipped_pack"): "fd3c3dc843690190",
    (SURFACE_CONTRACT, "_normalize"): "2c52ef6660683844",
}
SWEEP_DATA = ((SWEEP_TEST, "_CODESPAN_RE"), (SWEEP_TEST, "_CELL_SPLIT_RE"), (SWEEP_TEST, "_STRUCK_SPAN_RE"),
              (SWEEP_TEST, "_ROW_NUMBER_CELL_MAX"), (SURFACE_CONTRACT, "SHIPPED_PACK_DIRS"),
              (SURFACE_CONTRACT, "_PACK_FILENAME_PATTERN"))
SWEPT_PREFIXES = ("docs/", "memory/", "changelog.d/")
LEDGER_DIR = "task-packs/ledger.d/"
PROBES_DIR = "task-packs/probes.d/"
VENDOR_CC = "espalier/_vendor/cc/"


def rule_digest(text: str, name: str) -> str | None:
    """A digest of one module-level function's text: its lines, the docstring
    and every blank or comment-only line dropped, each line's trailing space
    cut, the block dedented. Text, never ``ast.dump``, whose spelling moves
    between interpreters. ``None`` where the file has no such function."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    node = next((n for n in _top_statements(tree.body)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)
    if node is None:
        return None
    drop: set[int] = set()
    first = node.body[0] if node.body else None
    if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str) and first.lineno > node.lineno):
        drop = set(range(first.lineno, first.end_lineno + 1))
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    lines = _ast_lines(text)  # indexed by ast line numbers, so split as the tokenizer splits
    kept = [lines[i - 1].rstrip() for i in range(start, node.end_lineno + 1) if i not in drop]
    body = textwrap.dedent("\n".join(k for k in kept if k.strip() and not k.lstrip().startswith("#")))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def module_constant(text: str, name: str):
    """A module-level constant's value, by AST: a literal, a literal wrapped in
    ``frozenset``/``set``/``tuple``, or ``re.compile``'s pattern literal.
    ``Unread`` where the name is not bound to one of those."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        raise Unread(f"cannot parse the file holding {name}: {exc}") from None
    for node in _top_statements(tree.body):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        value = node.value
        if isinstance(value, ast.Call) and len(value.args) == 1 and not value.keywords:
            func = value.func.id if isinstance(value.func, ast.Name) else getattr(value.func, "attr", None)
            if func in ("frozenset", "set", "tuple", "compile"):
                value = value.args[0]
        try:
            return ast.literal_eval(value)
        except ValueError:
            raise Unread(f"{name} is not a literal at the pin") from None
    raise Unread(f"{name} is not bound at module level at the pin")


def _sweep(ctx: dict) -> dict:
    """The sweep at the pin: the declared record set (``_RECORD_SURFACE_DOCS``,
    by AST; unreadable, the citations section is unread), and the rule, read
    as ported only where every pinned function's digest and every datum reads
    (``differs`` names each that does not)."""
    if "_sweep" in ctx:
        return ctx["_sweep"]
    texts = _tracked_texts(ctx)
    rules = dict(ctx.get("sweep_rules", SWEEP_RULES))
    test = texts.get(SWEEP_TEST)
    if test is None:
        raise Unread(f"{SWEEP_TEST} is not in {ctx['pin']['at'][:12]}: no declared record set")
    out: dict = {"record": frozenset(module_constant(test, "_RECORD_SURFACE_DOCS")), "differs": []}
    for (path, fn), want in sorted(rules.items()):
        if texts.get(path) is None or rule_digest(texts[path], fn) != want:
            out["differs"].append(f"{path}::{fn}")
    data = {}
    for path, name in SWEEP_DATA:
        try:
            data[name] = module_constant(texts.get(path) or "", name)
        except Unread:
            out["differs"].append(f"{path}::{name}")
    if not out["differs"]:
        out.update(codespan=re.compile(data["_CODESPAN_RE"]), cell_split=re.compile(data["_CELL_SPLIT_RE"]),
                   struck_span=re.compile(data["_STRUCK_SPAN_RE"]), row_max=int(data["_ROW_NUMBER_CELL_MAX"]),
                   pack_dirs=tuple(data["SHIPPED_PACK_DIRS"]), pack_pattern=str(data["_PACK_FILENAME_PATTERN"]))
    ctx["_sweep"] = out
    return out


def _is_pack(path: str, sweep: dict) -> bool:
    """``espalier/surface_contract.py::is_shipped_pack``, ported (with its ``_normalize``)."""
    p = path.replace("\\", "/")
    p = p[2:] if p.startswith("./") else p
    parent, _sep, name = p.rpartition("/")
    return parent in sweep["pack_dirs"] and fnmatch.fnmatchcase(name, sweep["pack_pattern"])


def _is_swept(path: str, sweep: dict) -> bool:
    """``tests/test_doc_source_citations.py::_swept_docs``'s membership test, ported."""
    return (path.endswith(".md")
            and (path.startswith(SWEPT_PREFIXES) or "/" not in path
                 or (path.startswith("task-packs/") and not _is_pack(path, sweep)))
            and path not in sweep["record"])


def _is_struck_line(line: str, sweep: dict) -> bool:
    """``tests/test_doc_source_citations.py::_is_struck_row``, ported: a line the sweep skips as a closed record row."""
    stripped = line.lstrip(" ")
    if len(line) - len(stripped) > 3 or not stripped.startswith("|"):
        return False
    for cell in sweep["cell_split"].split(stripped)[1:3]:
        spans = sweep["codespan"].findall(cell)
        if spans:
            return len(sweep["struck_span"].findall(cell)) == len(spans)
        if len(cell.strip()) > sweep["row_max"]:
            return False
    return False


_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def ledger_fragments(texts: dict[str, str]) -> dict[str, dict]:
    """Each ledger row file at the pin (``task-packs/ledger.d/*.md``), by Task
    6's rule: line 2 split on ``|``, the cells stripped, struck when
    ``cells[1]`` starts with ``~~``. ``unescaped`` is the same line split on
    unescaped pipes only (the ledger writes a literal pipe as ``\\|``), the
    reading the pseudo-code does not state, kept beside it. A file whose line
    2 is no table row has ``cells`` of ``None`` and is never struck."""
    out = {}
    for p in sorted(texts):
        if not (p.startswith(LEDGER_DIR) and p.endswith(".md") and "/" not in p[len(LEDGER_DIR):]):
            continue
        lines = texts[p].splitlines()
        row = lines[1] if len(lines) > 1 else ""
        is_row = row.lstrip().startswith("|")
        cells = [c.strip() for c in row.split("|")] if is_row else None
        unescaped = [c.strip() for c in _UNESCAPED_PIPE.split(row)] if is_row else None
        out[p] = {"cells": cells, "unescaped": unescaped,
                  "struck": bool(cells) and len(cells) > 1 and cells[1].startswith("~~")}
    return out


CITATION_SPELLINGS = ("path_symbol", "bare_symbol", "line", "dotted")
#: The spellings that name a symbol. The line form names a line as it stood
#: when the citation was written, so it is attributed to no definition.
CITATION_SYMBOL_SPELLINGS = ("path_symbol", "bare_symbol", "dotted")


def citation_patterns(modules) -> dict[str, re.Pattern]:
    """The four spellings of a citation of a CLI module: ``espalier/cli.py::X``;
    the bare ``cli.py::X`` (its file name not preceded by a word character,
    ``/``, ``.`` or ``-``, so neither ``espalier/cli.py::`` nor
    ``test_cli.py::`` is one); the line form ``espalier/cli.py:NNN``; and the
    dotted ``espalier.cli.X``."""
    paths = "|".join(re.escape(m) for m in modules)
    names = "|".join(re.escape(Path(m).name) for m in modules)
    dotted = "|".join(re.escape(m[:-3].replace("/", ".")) for m in modules if m.endswith(".py"))
    ident = r"([A-Za-z_][A-Za-z0-9_]*)"
    return {"path_symbol": re.compile(rf"(?:{paths})::{ident}"),
            "bare_symbol": re.compile(rf"(?<![\w/.-])(?:{names})::{ident}"),
            "line": re.compile(rf"(?:{paths}):(\d+)"),
            "dotted": re.compile(rf"(?<![\w.])(?:{dotted})\.{ident}")}


def _citation_surface(path: str, sweep: dict, frags: dict[str, dict], *, by_id_cell: bool = False) -> tuple[str, str]:
    """``(split, part)`` of one tracked file, first match wins: the declared
    record set; a protected-zone file under ``tools/cc/`` (its
    ``espalier/_vendor/cc/`` twin apart); a file the sweep reads (a ledger
    fragment, or another doc); else unchecked (a pack, a ``bench/corpus``
    JSON, a ``.claude`` body or its mirror, code, other). A line of a swept
    file is struck by the sweep's own line rule (``_is_struck_line``), applied
    by the caller, never by a fragment's id cell. Where the sweep's rule
    differs at the pin, the last two are ``unread``. ``by_id_cell`` is the
    authoring's file-level read the ``beside`` figures keep: a fragment whose
    line-2 id cell starts ``~~`` is struck whole."""
    if path in sweep["record"]:
        return "record", "record_set"
    if by_id_cell and frags.get(path, {}).get("struck"):
        return "struck", "struck_fragments"
    if path.startswith("tools/cc/"):
        return "protected_zone", "sources"
    if path.startswith(VENDOR_CC):
        return "protected_zone", "vendor_twins"
    if sweep["differs"]:
        return "unread", "unread"
    if _is_swept(path, sweep):
        return "swept_live", "live_fragments" if path in frags else "docs"
    if _is_pack(path, sweep):
        return "unchecked_live", "packs"
    if path.startswith("bench/corpus/") and path.endswith(".json"):
        return "unchecked_live", "bench_corpus"
    if "/.claude/" in f"/{path}" or path.startswith("espalier/assets/claude/"):
        return "unchecked_live", "claude_bodies"
    if path.endswith((".py", ".cmd")):
        return "unchecked_live", "code"
    return "unchecked_live", "other"


_SPLIT_PARTS = {"record": ("record_set",), "struck": ("struck_fragments", "struck_lines_in_swept_docs"),
                "swept_live": ("live_fragments", "docs"),
                "unchecked_live": ("packs", "bench_corpus", "claude_bodies", "code", "other"),
                "protected_zone": ("sources", "vendor_twins"), "unread": ("unread",)}


def section_citations(ctx: dict) -> dict:
    """Every citation of a CLI module in every tracked file at the pin, every
    file type, in the four spellings, split five ways: the declared record set
    (read from the sweep at the pin); struck rows, each a line the sweep skips
    as a closed row (``_is_struck_row``, ported: its first two cells' code
    spans all struck ``~~`...`~~``), in a ledger fragment or in another swept
    doc; the files the sweep reads (live ledger fragments apart from other
    docs), a population: the sweep visits only the backticked
    ``path::symbol`` spellings in them, so a citation here goes red on a move
    only in that spelling, and the other spellings are counted beside it; the
    unchecked, which rot with no red; and the protected zone under
    ``tools/cc/``, each file beside its vendored twin. The parts sum to the
    totals, asserted. Two struck counts are kept by two rules and are not
    read against each other: ``split.struck.struck_fragments`` counts
    citations by the sweep's line rule, while ``fragments.struck`` counts
    fragments by the authoring's line-2 id cell (``cells[1]`` starts ``~~``),
    the rule ``beside`` keeps."""
    texts = _texts_for(ctx, "citations")
    modules = ctx["modules"]
    pats = citation_patterns(modules)
    sweep = _sweep(ctx)
    frags = ledger_fragments(texts)
    tokens = {Path(m).name for m in modules} | {m[:-3].replace("/", ".") for m in modules if m.endswith(".py")}
    rows: list[tuple[str, str, str, str, int]] = []
    named: list[tuple[str, str, str, str, str]] = []  # (path, split, part, spelling, symbol), one per occurrence
    substring: dict[str, list] = {}
    for path in sorted(texts):
        text = texts[path]
        if not any(t in text for t in tokens):
            continue
        split, part = _citation_surface(path, sweep, frags)
        n = sum(text.count(f"{m}::") for m in modules)
        if n:
            cell = substring.setdefault("/".join(_citation_surface(path, sweep, frags, by_id_cell=True)), [0, 0])
            cell[0] += n
            cell[1] += 1
        for line in text.splitlines():
            if not any(t in line for t in tokens):
                continue
            found = {s: rx.findall(line) for s, rx in pats.items()}
            counts = {s: len(v) for s, v in found.items()}
            if not any(counts.values()):
                continue
            s_, p_ = split, part
            if split == "swept_live" and _is_struck_line(line, sweep):
                s_, p_ = "struck", "struck_fragments" if part == "live_fragments" else "struck_lines_in_swept_docs"
            rows.extend((path, s_, p_, s, n) for s, n in counts.items() if n)
            named.extend((path, s_, p_, s, sym) for s in CITATION_SYMBOL_SPELLINGS for sym in found[s])

    def tally(sel: list[tuple]) -> dict:
        return {s: {"occurrences": sum(r[4] for r in sel if r[3] == s), "files": len({r[0] for r in sel if r[3] == s})}
                for s in CITATION_SPELLINGS}

    def part_of(split: str, part: str, paths: bool = False) -> dict:
        sel = [r for r in rows if r[1] == split and r[2] == part]
        out = tally(sel)
        if paths:
            out["paths"] = sorted({r[0] for r in sel})
        return out

    totals = tally(rows)
    split_out: dict = {}
    for split, parts in _SPLIT_PARTS.items():
        if split in ("swept_live", "unchecked_live") and sweep["differs"]:
            split_out[split] = None
            continue
        if split == "unread" and not sweep["differs"]:
            continue
        split_out[split] = {p: part_of(split, p, paths=split in ("record", "swept_live") or p != "code")
                            for p in parts}
    summed = {s: sum(part[s]["occurrences"] for parts in split_out.values() if parts for part in parts.values())
              for s in CITATION_SPELLINGS}
    assert summed == {s: totals[s]["occurrences"] for s in CITATION_SPELLINGS}, \
        f"the citation split does not sum to the totals: {summed} against {totals}"
    per_symbol: dict[str, dict[str, int]] = {}
    for _path, split, part, _s, sym in named:
        cell = per_symbol.setdefault(sym, {})
        cell[f"{split}/{part}"] = cell.get(f"{split}/{part}", 0) + 1
    assert sum(n for cell in per_symbol.values() for n in cell.values()) == sum(
        totals[s]["occurrences"] for s in CITATION_SYMBOL_SPELLINGS), "the per-symbol tally does not sum to the totals"
    ctx["_citation_named"] = named  # kept for the move cost, which prices each symbol's files by unit
    per_file: dict[str, dict[str, int]] = {}
    for path, split, _part, s, n in rows:
        if split == "protected_zone":
            per_file.setdefault(path, {})[s] = per_file.get(path, {}).get(s, 0) + n
    sources = []
    for path in sorted(p for p in per_file if p.startswith("tools/cc/")):
        twin = VENDOR_CC + path[len("tools/cc/"):]
        sources.append({"path": path, "occurrences": per_file[path], "twin": twin, "twin_in_tree": twin in texts,
                        "twin_occurrences": per_file.get(twin, {})})
    split_out["protected_zone"]["by_file"] = sources
    split_out["protected_zone"]["vendor_only"] = sorted(
        p for p in per_file if p.startswith(VENDOR_CC) and "tools/cc/" + p[len(VENDOR_CC):] not in per_file)
    exts = {"md_json": (".md", ".json"), "py_cmd": (".py", ".cmd")}

    def ext_of(path: str) -> str:
        return next((k for k, v in exts.items() if path.endswith(v)), "other")

    by_ext = {k: tally([r for r in rows if ext_of(r[0]) == k]) for k in (*exts, "other")}
    meta = ctx.get("_texts_meta", {})
    return {"rule": {"spellings": {s: rx.pattern for s, rx in pats.items()},
                     "split": "first match: record set (_RECORD_SURFACE_DOCS at the pin, by AST); tools/cc/ (its "
                              "espalier/_vendor/cc/ twin apart); the sweep's population (_swept_docs, ported and "
                              "digest-pinned), a line it skips as struck (_is_struck_row, ported) counted struck, "
                              "in a ledger fragment (task-packs/ledger.d/*.md) or another doc; else unchecked. "
                              "swept_live is a population: the sweep reds only its backticked path::symbol "
                              "spellings",
                     "beside_substring": "the authoring's read: one part per file, a ledger fragment whose "
                                         "line 2 cells[1] starts '~~' struck whole",
                     "fragments": "all: the ledger fragments; struck: those whose line 2 cells[1] starts '~~' "
                                  "(the id-cell rule beside_substring keeps), not the sweep's line rule "
                                  "split.struck.struck_fragments counts by"},
            "files_tracked": meta.get("tracked"), "files_read": meta.get("read"),
            "binary": len(meta.get("binary", [])), "files_unread": meta.get("unread", []),
            "record_set": sorted(sweep["record"]),
            "fragments": {"all": len(frags), "struck": sum(1 for f in frags.values() if f["struck"])},
            "totals": totals, "by_extension": by_ext, "split": split_out,
            "per_symbol_rule": "each occurrence in the path_symbol, bare_symbol and dotted spellings, by the symbol "
                               "it names and its 'split/part' (the line form names no symbol)",
            "per_symbol": {s: dict(sorted(v.items())) for s, v in sorted(per_symbol.items())},
            "unread": {"swept_live": f"the sweep's rule differs at the pin: {sweep['differs']}",
                       "unchecked_live": "the swept population is unread, so its complement is too"}
            if sweep["differs"] else {},
            # The authoring's read: the substring '<module>::' (no symbol required),
            # each file in one part, a line the sweep skips as struck left where its file is.
            "beside": {"substring": {f"{m}::": sum(t.count(f"{m}::") for t in texts.values()) for m in modules},
                       "substring_by_part": {k: {"occurrences": v[0], "files": v[1]}
                                             for k, v in sorted(substring.items())}}}


def probe_code(cmd: str) -> str | None:
    """The Python a probe's command runs (``python -c '<code>'``), or ``None``."""
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return None
    for i, a in enumerate(argv):
        if re.fullmatch(r"python[0-9.]*(?:\.exe)?|py", Path(a).name):
            rest = argv[i + 1:]
            return rest[rest.index("-c") + 1] if "-c" in rest[:-1] else None
    return None


def probe_reads(probe: dict, modules, defined: set[str]) -> dict:
    """How one probe reads a CLI module, and the cli symbols it names. ``subject``:
    its subject is the module (a move keeps the file, so the subject gate stays
    green). ``path``: its code holds the module's path as a string (a text or
    AST read of the file); its symbols are the string constants in a
    comparison that name a cli definition (``n.name == "cmd_init"``). ``import``:
    an import of cli or an attribute through an alias of it; ``patch``: an
    attribute stored through that alias. ``run``: ``-m espalier.cli`` or ``-m
    espalier`` in an argv list or a string, which runs the CLI (behaviour a
    move keeps) and names no symbol; a scan for the text ``espalier.cli`` in
    other files is no run. A command
    that is no ``python -c`` or does not parse is read as text (``by`` tagged
    ``(text)``, its symbols every identifier that names a cli definition)."""
    cmd = str(probe.get("cmd") or "")
    by: list[str] = []
    symbols: set[str] = set()
    if str(probe.get("subject") or "") in modules:
        by.append("subject")
    code = probe_code(cmd) if cmd else None
    tree = None
    if code is not None:
        try:
            tree = ast.parse(code)
        except (SyntaxError, ValueError):
            tree = None
    dotted = {m[:-3].replace("/", ".") for m in modules if m.endswith(".py")}
    if tree is not None:
        consts = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        if any(m in c for c in consts for m in modules):
            by.append("path")
            for node in ast.walk(tree):
                if isinstance(node, ast.Compare):
                    symbols |= {c.value for c in [node.left, *node.comparators]
                                if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value in defined}
        found = imports_of_cli("probe.py", tree)
        if found:
            by.append("import")
            symbols |= {n for f in found for n in f["names"]}
            aliases = {f["via"].split(" ", 1)[1] for f in found if f["via"].startswith("alias ")}
            if any(isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store) and _dotted(n.value) in aliases
                   for n in ast.walk(tree)):
                by.append("patch")
        runs = dotted | {d.split(".", 1)[0] for d in dotted}
        argvs = [[e.value if isinstance(e, ast.Constant) else None for e in n.elts]
                 for n in ast.walk(tree) if isinstance(n, (ast.List, ast.Tuple))]
        if (any(a == "-m" and b in runs for v in argvs for a, b in zip(v, v[1:]))
                or any(f"-m {r} " in f"{c} " for c in consts for r in runs)):
            by.append("run")
    elif cmd:
        if any(m in cmd for m in modules):
            by.append("path (text)")
        if re.search(r"\bespalier\.cli\b|\bfrom espalier import [^;\n]*\bcli\b", cmd):
            by.append("import (text)")
        if len(by) > ("subject" in by):
            symbols |= {w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", cmd) if w in defined}
    return {"by": by, "symbols": sorted(symbols), "parsed": None if not cmd else tree is not None}


#: A probe's ledger row: live, struck, a fragment whose line 2 is no table row, or no fragment.
PROBE_ROW_STATES = ("live", "struck", "not a row", "no row")


def section_probes(ctx: dict) -> dict:
    """Each ledger probe at the pin (``task-packs/probes.d/*.json``) that reads
    a CLI module, by ``probe_reads``: its row's state (the fragment's id cell,
    struck or live, or no row), the cli symbols it names, and each symbol's
    owner from the clusters section, with the commands that would move it.
    ``tools/cc/check_ledger_probes.py`` gates a probe on its subject at file
    level, and the file survives a move, so a probe that reads a moved symbol
    out of cli.py prints a new value and offers its live row as a strike. A
    fragment whose line 2 is no table row is ``not a row`` (``not_a_row``),
    never read as live; a probe file that is no JSON object is named under
    ``unread`` as ``probes.unparsed_json``."""
    texts = _texts_for(ctx, "probes")
    modules = ctx["modules"]
    _tree, defs, _g = _functions_ctx(ctx)
    defined = {d["name"] for d in defs}
    owners = _owners(ctx)
    frags = ledger_fragments(texts)
    rows, bad = [], []
    files = sorted(p for p in texts if p.startswith(PROBES_DIR) and p.endswith(".json")
                   and "/" not in p[len(PROBES_DIR):])
    for path in files:
        try:
            probe = json.loads(texts[path])
        except ValueError:
            bad.append(path)
            continue
        if not isinstance(probe, dict):
            bad.append(path)
            continue
        read = probe_reads(probe, modules, defined)
        if not read["by"]:
            continue
        pid = str(probe.get("id") or Path(path).stem)
        frag = frags.get(f"{LEDGER_DIR}{pid}.md")
        state = ("no row" if frag is None else "not a row" if frag["cells"] is None
                 else "struck" if frag["struck"] else "live")
        sym_owners = {s: _owner_of(owners, s) for s in read["symbols"]}
        rows.append({"id": pid, "file": path, "row": state, "by": read["by"], "has_cmd": bool(probe.get("cmd")),
                     "parsed": read["parsed"], "symbols": read["symbols"], "owners": sym_owners,
                     "commands": sorted({c for o in sym_owners.values() for c in _commands_of(o)}),
                     "concerns": sorted({o["concern"] for o in sym_owners.values() if "concern" in o})})
    reading = [r for r in rows if set(r["by"]) - {"subject"}]
    if bad:
        _partial(ctx, "probes", "unparsed_json", f"{len(bad)} probe file(s) are no JSON object, so what they read "
                                                 f"is not read: {bad[:5]}")
    return {"rule": "probe_reads over task-packs/probes.d/*.json at the pin; row state from "
                    "task-packs/ledger.d/<id>.md line 2 cells[1] ('~~' = struck; a line 2 that is no table row "
                    "is not a row)",
            "probes": len(files), "unparsed_json": bad,
            "reading_cli": len(reading), "subject_only": len(rows) - len(reading),
            "by_reading": {k: sum(1 for r in rows if k in r["by"])
                           for k in ("subject", "path", "import", "patch", "run", "path (text)", "import (text)")},
            "by_row": {s: sum(1 for r in rows if r["row"] == s) for s in PROBE_ROW_STATES},
            "not_a_row": sorted(r["id"] for r in rows if r["row"] == "not a row"),
            "live_reading_cli": sum(1 for r in reading if r["row"] == "live"),
            "live_any": sum(1 for r in rows if r["row"] == "live"),
            "symbols_named": {"pairs": sum(len(r["symbols"]) for r in rows),
                              "distinct": len({s for r in rows for s in r["symbols"]}),
                              "probes": sum(1 for r in rows if r["symbols"])},
            "rows": rows}


_PATH_STRIP = "`'\"()[]{}<>,;*"


def first_path_token(cell: str, *, dotfile_counts: bool) -> str | None:
    """Task 6's tokenizer: the first whitespace token of ``cell`` that is a
    path, its backticks, quotes, brackets and trailing punctuation cut and any
    ``::symbol`` or ``:line`` taken off. A path, read as the pseudo-code's
    precedence states it: it contains ``/``, or it has a leading ``.`` and an
    extension (``os.path.splitext``; ``.gitignore`` has none). With
    ``dotfile_counts`` a leading-dot name with no extension is one too."""
    for raw in cell.split():
        core = re.split(r"::|:(?=\d)", raw.strip(_PATH_STRIP), maxsplit=1)[0].rstrip(".,;:")
        if not core:
            continue
        if "/" in core:
            return core
        if core.startswith(".") and (os.path.splitext(core)[1] or (dotfile_counts and re.match(r"\.\w", core))):
            return core
    return None


def section_ledger_rows(ctx: dict) -> dict:
    """Task 6's three tiers over ``task-packs/ledger.d/*.md`` at the pin, by
    its pseudo-code: line 2, cells split on ``|`` and stripped, struck when
    ``cells[1]`` starts ``~~``. Tier 1: not struck and the first path token of
    ``cells[2]`` is a CLI module, both readings of a dotfile given. Tier 2: not
    struck and a CLI module's path in ``cells[2]``. Tier 3: not struck, not tier
    2, and ``<module>::X`` in ``cells[3]``. For each tier-2 and tier-3 row, its
    cited symbols (``<module>::X`` in any cell after the id) and each one's
    owner from the clusters section. A tracked file that could not be read is
    named under ``unread`` as ``ledger_rows.texts``."""
    texts = _texts_for(ctx, "ledger_rows")
    modules = ctx["modules"]
    owners = _owners(ctx)
    pats = citation_patterns(modules)
    frags = ledger_fragments(texts)
    not_a_row = sorted(p for p, f in frags.items() if f["cells"] is None or len(f["cells"]) < 4)
    rows = {p: f for p, f in frags.items() if p not in not_a_row}
    live = {p: f for p, f in rows.items() if not f["struck"]}

    def rid(f: dict) -> str:
        return f["cells"][1].replace("~~", "").strip("` ")

    def tiers(key: str) -> tuple[dict[bool, list[str]], set[str], set[str]]:
        cells = {p: f[key] for p, f in live.items() if f[key] is not None and len(f[key]) >= 4}
        t1 = {dot: sorted(rid(live[p]) for p, c in cells.items()
                          if first_path_token(c[2], dotfile_counts=dot) in modules) for dot in (False, True)}
        t2 = {p for p, c in cells.items() if any(m in c[2] for m in modules)}
        t3 = {p for p, c in cells.items() if p not in t2 and pats["path_symbol"].search(c[3])}
        return t1, t2, t3

    t1, t2, t3 = tiers("cells")
    u1, u2, u3 = tiers("unescaped")

    def entry(p: str, tier: int) -> dict:
        f = frags[p]
        syms = sorted({s for c in f["cells"][2:] for s in pats["path_symbol"].findall(c)})
        own = {s: _owner_of(owners, s) for s in syms}
        return {"id": rid(f), "file": p, "tier": tier, "symbols": syms, "owners": own,
                "commands": sorted({c for o in own.values() for c in _commands_of(o)})}

    def ids(paths: set[str]) -> list[str]:
        return sorted(rid(frags[p]) for p in paths)

    beside_bare = sorted(rid(f) for p, f in live.items() if p not in t2 | t3 and len(f["cells"]) >= 4
                         and pats["bare_symbol"].search(f["cells"][3]))
    beside_dotted = sorted(rid(f) for p, f in live.items() if p not in t2 | t3 and len(f["cells"]) >= 4
                           and pats["dotted"].search(f["cells"][3]))
    beside_path = sorted(rid(f) for p, f in live.items() if p not in t2 | t3 and len(f["cells"]) >= 4
                         and any(m in f["cells"][3] for m in modules))
    return {"rule": "line 2 of each task-packs/ledger.d/*.md; cells = split on every '|', stripped; struck = "
                    "cells[1] starts '~~'; tier 1 = first_path_token(cells[2]) is the module; tier 2 = the "
                    "module's path in cells[2]; tier 3 = not tier 2 and '<module>::X' in cells[3]",
            "fragments": len(frags), "not_a_row": not_a_row, "struck": sum(1 for f in rows.values() if f["struck"]),
            "live": len(live),
            "tier1": {"dotfile_not_counted": {"count": len(t1[False]), "ids": t1[False]},
                      "dotfile_counted": {"count": len(t1[True]), "ids": t1[True]},
                      "differ": sorted(set(t1[False]) ^ set(t1[True]))},
            "tier2": {"count": len(t2), "rows": [entry(p, 2) for p in sorted(t2)]},
            "tier3": {"count": len(t3), "rows": [entry(p, 3) for p in sorted(t3)]},
            "beside": {"tier3_if_bare_spelling_counted": beside_bare,
                       "tier3_if_dotted_spelling_counted": beside_dotted,
                       "tier3_if_a_path_mention_counted": beside_path,
                       "split_on_unescaped_pipes": {
                           "tier1_dotfile_not_counted": len(u1[False]), "tier1_dotfile_counted": len(u1[True]),
                           "tier2": len(u2), "tier3": len(u3),
                           "tier2_differ": ids(t2 ^ u2), "tier3_differ": ids(t3 ^ u3)}}}


DOCTOR = "espalier/doctor.py"
DOCTOR_MODULE = "espalier.doctor"


def doctor_callbacks(tree: ast.Module, defs: list[dict], members: set[str]) -> dict[str, list[str]]:
    """``{member: doctor names}``: each of ``members`` that loads a doctor name
    back, through cli's module-level alias of ``espalier.doctor``
    (``_doctor.X``), a lazy ``from espalier.doctor import X``, or a lazy alias
    of the module inside it: the edges that keep the import cycle."""
    module_aliases = {a for a, target in _module_aliases(tree).items() if target == DOCTOR_MODULE}
    out: dict[str, list[str]] = {}
    for d in defs:
        if d["name"] not in members:
            continue
        root = d["node"].value if d["kind"] == NAME and getattr(d["node"], "value", None) is not None else d["node"]
        aliases, names = set(module_aliases), set()
        for sub in ast.walk(root):
            if isinstance(sub, ast.ImportFrom):
                module = _absolute(CLI, sub)
                if module == DOCTOR_MODULE:
                    names.update(a.name for a in sub.names)
                elif module == "espalier":
                    aliases.update(a.asname or a.name for a in sub.names if a.name == "doctor")
            elif isinstance(sub, ast.Import):
                aliases.update(a.asname for a in sub.names if a.name == DOCTOR_MODULE and a.asname)
        for sub in ast.walk(root):
            if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id in aliases:
                names.add(sub.attr)
        if names:
            out[d["name"]] = sorted(names)
    return out


def section_doctor_boundary(ctx: dict) -> dict:
    """Task 5: every name ``espalier/doctor.py`` takes from cli at the pin
    (``imports_of_cli``: its from-imports and the attributes it loads through
    an alias of cli), each with its kind in cli and the commands that reach it
    (the clusters section's ownership); the names no command reaches (doctor's
    alone); the closure of all of them over cli's graph, sized; and the
    closure members that load doctor back, the edges that keep the cycle."""
    root, at = ctx["root"], ctx["pin"]["at"]
    text = source_at(root, at, DOCTOR)
    if text is None:
        raise Unread(f"{DOCTOR} is not in {at[:12]}")
    dtree = ast.parse(text)
    tree, defs, g = _functions_ctx(ctx)
    kinds = {d["name"]: d["kind"] for d in defs}
    lines = {d["name"]: d["lines"] for d in defs}
    owners = _owners(ctx)
    found = imports_of_cli(DOCTOR, dtree)
    names = sorted({n for f in found for n in f["names"]})
    statements = []
    for node in ast.walk(dtree):
        if isinstance(node, ast.ImportFrom) and (_absolute(DOCTOR, node) == CLI_MODULE or (
                _absolute(DOCTOR, node) == "espalier" and any(a.name == "cli" for a in node.names))):
            statements.append(node.lineno)
        elif isinstance(node, ast.Import) and any(a.name == CLI_MODULE for a in node.names):
            statements.append(node.lineno)
    alias_names = {f["via"].split(" ", 1)[1] for f in found if f["via"].startswith("alias ")}
    load_lines = [n.lineno for n in ast.walk(dtree) if isinstance(n, ast.Attribute) and _dotted(n.value) in alias_names]
    ddefs = [d for d in definitions(dtree) if d["kind"] != NAME]
    holders = {d["name"] for ln in [*statements, *load_lines] for d in ddefs if d["start"] <= ln <= d["end"]}
    # The same read by the innermost function holding each line, at any depth
    # (a nested helper is its own holder), keyed by its line so two of one name stay two.
    fns = [(n.lineno, n.end_lineno, n.name) for n in ast.walk(dtree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    innermost = set()
    for ln in [*statements, *load_lines]:
        holding = [f for f in fns if f[0] <= ln <= f[1]]
        if holding:
            innermost.add(min(holding, key=lambda f: (f[1] - f[0], f[0])))
    per = {}
    for n in names:
        o = _owner_of(owners, n)
        per[n] = {"kind": kinds.get(n), "reached_by": _commands_of(o), "owner": o}
    in_cli = [n for n in names if n in kinds]
    alone = sorted(n for n in in_cli if not per[n]["reached_by"])
    members = closure(g["edges"], in_cli)
    by_loads = closure(g["loads"], in_cli)
    calls_back = doctor_callbacks(tree, defs, members)
    return {"rule": "imports_of_cli over espalier/doctor.py at the pin; closure over cli's graph (loads and "
                    "writes), no stop; owners from the clusters section",
            "import_statements": len(statements), "doctor_functions": sorted(holders),
            "doctor_functions_innermost": len(innermost),
            "names": {"count": len(names), "functions": sum(1 for n in in_cli if kinds[n] == FUNCTION),
                      "classes": sum(1 for n in in_cli if kinds[n] == CLASS),
                      "constants": sum(1 for n in in_cli if kinds[n] == NAME),
                      "not_in_cli": sorted(n for n in names if n not in kinds), "per_name": per},
            "doctor_alone": alone,
            "back_edges_left_if_doctor_alone_moved": len(in_cli) - len(alone),
            "closure": {**_size(members, kinds, lines), "definitions": len(members),
                        "reached_by_no_command": sorted(m for m in members if not _commands_of(_owner_of(owners, m))),
                        "loads_only": {**_size(by_loads, kinds, lines), "definitions": len(by_loads),
                                       "write_reached": sorted(members - by_loads)}},
            "calls_back_into_doctor": calls_back,
            "call_back_edges": sum(len(v) for v in calls_back.values())}


# ---------------------------------------------------------------- the move cost per unit (Tasks 3 and 4)

def _section(ctx: dict, name: str):
    """One section's result, read once a run and kept in ``ctx``: the move
    cost reads eight sections, and one the run also prints is not read twice.
    An ``Unread`` is kept too, and raised again; so is any other failure of a
    read (``_READ_FAILURES``: git past its timeout, no git or gh, a source that
    does not parse, a short read, bad JSON, a loaded census's ``SystemExit``),
    turned into one, so one section's failure never aborts the run."""
    done = ctx.setdefault("_done", {})
    if name not in done:
        reader = SECTION_READERS.get(name)
        try:
            if reader is None:
                raise Unread("no reader for this section in this census")
            done[name] = reader(ctx)
        except _READ_FAILURES as exc:
            done[name] = _unread(exc)
    if isinstance(done[name], Unread):
        raise done[name]
    return done[name]


def _tracked(ctx: dict) -> list[str]:
    if "_tracked" not in ctx:
        ctx["_tracked"] = tracked_at(ctx["root"], ctx["pin"]["at"])
    return ctx["_tracked"]


def _module_of(path: str) -> str:
    """A tracked ``.py`` file's dotted module name (a package's ``__init__`` is the package)."""
    mod = path[:-3].replace("/", ".") if path.endswith(".py") else path.replace("/", ".")
    return mod[: -len(".__init__")] if mod.endswith(".__init__") else mod


def _imported_module(base: str, name: str, known: set[str]) -> str:
    """The module ``from base import name`` loads: ``base.name`` where that is a
    tracked module (a submodule's import), else ``base``."""
    return f"{base}.{name}" if f"{base}.{name}" in known else base


def import_bindings(tree: ast.Module, path: str, known: set[str]) -> dict[str, str]:
    """``{name: module}``: each name a top-level import of ``path`` binds (in a
    module-level ``if`` or ``try`` too), with the module it comes from. A name
    a test patches on cli that is bound here is cli's import, not a definition
    of cli: a module that receives a moved loader gets its own binding of it."""
    out: dict[str, str] = {}
    for node in _top_statements(tree.body):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            base = _absolute(path, node)
            for a in node.names:
                if a.name != "*":
                    out[a.asname or a.name] = _imported_module(base, a.name, known)
    return out


def lazy_targets(node: ast.AST, path: str, known: set[str]) -> list[dict]:
    """Each import statement inside one definition (the graph's ``lazy_imports``),
    with the modules it loads, resolved."""
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.ImportFrom):
            base = _absolute(path, sub)
            out.append({"line": sub.lineno, "modules": sorted({_imported_module(base, a.name, known) for a in sub.names})})
        elif isinstance(sub, ast.Import):
            out.append({"line": sub.lineno, "modules": sorted({a.name for a in sub.names})})
    return out


def _bound_loads(d: dict, bindings: dict[str, str]) -> set[str]:
    """The names bound by cli's top-level imports that one definition loads (a
    local of the same name excluded, scope by scope): the imports a new module
    would need too."""
    if d["kind"] == NAME:
        root = d["node"].value if getattr(d["node"], "value", None) is not None else d["node"]
    else:
        root = d["node"]
    refs, _writes = _module_refs(root)
    return {n.id for n in ast.walk(root) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
            and n.id in bindings and id(n) in refs}


def _initial_value(d: dict) -> str:
    """A module-level name's first bound value, by kind: ``bool``, ``None``,
    another constant's type, or the AST node's kind (``dict``, ``call``). A
    name a tuple unpacks (``_A, _B = False, None``) reads its own element, and
    a sign on a number (``-1``) is folded into the number."""
    node = d["node"]
    value = getattr(node, "value", None)
    if value is None:
        return "unassigned"
    for target in node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]:
        if (isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List))
                and len(target.elts) == len(value.elts) and not any(isinstance(e, ast.Starred) for e in target.elts)):
            hit = next((v for e, v in zip(target.elts, value.elts) if isinstance(e, ast.Name) and e.id == d["name"]), None)
            if hit is not None:
                value = hit
                break
    if (isinstance(value, ast.UnaryOp) and isinstance(value.op, (ast.USub, ast.UAdd))
            and isinstance(value.operand, ast.Constant) and isinstance(value.operand.value, (int, float, complex))
            and not isinstance(value.operand.value, bool)):
        return type(value.operand.value).__name__
    if isinstance(value, ast.Constant):
        return "None" if value.value is None else "bool" if isinstance(value.value, bool) else type(value.value).__name__
    return type(value).__name__.lower()


#: Each ingredient's tally, the section that holds its total, and the total.
MOVE_TOTALS: dict[str, str] = {
    "importers_outside": "importers.outside_tests.distinct_names",
    "test_imports": "importers.tests.distinct_names",
    "patch_sites": "patches.sites",
    "patch_targets": "patches.targets",
    "patch_raising_false": "patches.raising_false[*].raising_false, summed",
    "symbol_keys": "readers.by_kind.symbol_key.sites",
    "citations": "citations.totals[path_symbol, bare_symbol, dotted].occurrences, summed",
    "probes": "probes.symbols_named.pairs",
    "doctor": "doctor_boundary.names.count",
    "lazy_imports": "functions.unresolved.lazy_imports",
}

MOVE_RULES: dict[str, str] = {
    "units": "each hand layer of the layers section, priced over its members and over its tie_closed set (members "
             "and pulled); each concern of the clusters section's concern tally, over the definitions it owns "
             "(per_root): a hand group (cluster_source hand) or a command left a concern of its own (command)",
    "size": "the unit's definitions by kind; function_lines over its functions",
    "importers_outside": "imports_of_cli over each tracked .py outside tests/: per file, the members it takes, by "
                         "statement lazy (inside a function or class) or top (module level); names = distinct "
                         "members, pairs = (file, member); namespace_by_hand: a call of a member handed an "
                         "argparse.Namespace built by hand in the same scope (namespace_calls)",
    "test_imports": "imports_of_cli over tests/: the members test files take (from-imports and attributes read or "
                    "stored through an alias of cli), with the files; pairs = (file, member); stored_only_pairs: a "
                    "file that only assigns or deletes the member through the alias (cli.X = ...), never reads it, "
                    "which is a patch site too",
    "patches": "the patches section's sites on cli whose target is a member; raising_false and assign sites "
               "beside; loaders (the patches section's: definitions of cli loading the target) inside and outside "
               "the unit; left_behind_loader: a member target with loaders on both sides, so a move keeps the old "
               "patch green through the loader left behind while the moved one goes unpatched (a target whose "
               "loaders all stay behind is reached by its patch); loaded_not_member: a target outside the unit "
               "that a member loads; not told apart from a plain patch: a builtin setattr(cli, ...) or a patch "
               "passing create=True (each creates a missing attribute silently) and a patch.dict on a re-exported "
               "memo (it changes the one shared dict, so it is not stale); tests/ held none of them at 3330a5a, "
               "so a later pin that holds one misprices its branches",
    "readers": "symbol_key: the readers section's (module path, symbol) sites naming a member, by class; silent "
               "and flat_module: each hand-listed reader covering a member, a silent one covering the cli "
               "definitions a string constant in its span names, or the whole file where it names none, a "
               "flat-module one the whole file (it escapes only a move into a subpackage); path_literal and "
               "path_join sites name no symbol and are attributed to no unit",
    "citations": "the citations section's path_symbol, bare_symbol and dotted occurrences naming a member, by split "
                 "and part, with the files; in_split sums the parts that were read; the line form names no symbol "
                 "and is attributed to no unit",
    "probes": "the probes section's rows whose symbols include a member, by row state; pairs = (probe, member); a "
              "probe that reads cli and names no symbol, or reads it by subject alone, is attributed to no unit "
              "(not_attributed)",
    "outbound": "lazy: the import statements inside members, by each module they load (a statement counted once "
                "per module); top_level_imports_loaded: names bound by cli's top-level imports that a member "
                "loads, by module; back_edges: the cli definitions outside the unit its members load or write "
                "(the import of cli a new module keeps); cli_callers: the definitions outside the unit that load "
                "or write a member, members_kept_bound the members they reach (cli keeps a binding of each); "
                "cli_cycle: both exist; importer_cycles: an outbound module that imports cli, closing a cycle "
                "when it takes a member, or takes another name while cli keeps a caller",
    "doctor": "the members among the names the doctor_boundary section reads doctor taking from cli",
    "latches_across": "each latch outside the unit that a member writes or reads, in both branches: a moved "
                      "'global X' write rebinds the new module's X, which cli's readers never see, and a moved read "
                      "through a module-level 'from espalier.cli import X' reads the value at import time; only a "
                      "read or write through the module (cli.X) keeps one copy",
    "module_run": "static, read from Python's -m semantics and never run: imports_cli where the unit has back "
                  "edges, so under 'python -m espalier.cli' (cli is __main__) the new module's import of "
                  "espalier.cli loads a second module object; state_in_a_second_copy, the latches and memos "
                  "outside the unit its members touch, which would be that copy's",
    "with_reexports": "moved names stay importable from cli: stale_patch_sites, a member target with a loader "
                      "inside the unit (the patch lands on cli's binding, the moved loader reads its own), of "
                      "which the loaders_on_both_sides stay green; stale_in_both, a target outside the unit a "
                      "member loads, where the new module takes it by from-import; latches_split, the latches "
                      "among the members bound to a bool or None (the brief's cut; latches_other holds the rest, "
                      "which split the same way), which cli's re-export copies once and never sees rebound; "
                      "latches_across; memos_shared, the memo dicts among the members, one object under both "
                      "names; loud_readers, symbol_key sites of class loud, which read cli.py's text either way; "
                      "cli_cycle: cli imports the new module to re-export it, so any back edge closes a cycle",
    "without_reexports": "moved names are not importable from cli and cli reaches the ones it still loads through "
                         "the module (newmod.X): the sites that fail loudly are test imports (pairs, less the "
                         "stored_only ones), patch sites on a member target that are no raising=False and no "
                         "assignment (those create the attribute and reach nothing: silent_creates), outside "
                         "importers (pairs), and loud symbol_key sites; loud_sites is their sum, None where any "
                         "part is unread. if_cli_from_imports_what_it_still_loads: where cli instead takes the "
                         "members it still loads or writes (members_kept_bound: a 'global X' write in a cli "
                         "definition left behind counts, an upper bound over loads alone) by 'from newmod "
                         "import X', cli.X stays bound and those parts stop failing (patches then stay green "
                         "on a stale binding as with re-exports); "
                         "stale_in_both and latches_across as in the other branch",
    "sums": "each ingredient's tally over every top-level definition at the pin, plus the names it counts that "
            "cli imports (imported_into_cli) and the names cli does not bind (not_bound_in_cli), equals the "
            "section's own total (MOVE_TOTALS); the tally and the total are read from one list, so this checks "
            "only that per-name attribution drops nothing; where the section splits its own total by a rule of "
            "its own (patches: not defined in cli; doctor: not in cli), that split is checked against the "
            "census's (bound by a top-level import of cli)",
    "partition": "move_partition: the concern units are disjoint and, with the rest (shared and unreached), cover "
                 "every definition; each ingredient's per-unit figures, aggregated from the unit's own sites and "
                 "split cells, plus the tally over the rest, equal the defined total",
}


#: The partial reads of each priced section that leave its ingredients a lower
#: bound: a file the section could not parse or read holds sites it never saw.
_PARTS_PRICED = {"importers": ("unparsed", "py_files"), "patches": ("unparsed", "tests"),
                 "readers": ("unparsed", "texts"), "citations": ("texts",), "probes": ("unparsed_json", "texts")}


def _move_inputs(ctx: dict) -> dict:
    """Every ingredient's tally per name over the whole of cli at the pin,
    each beside its section's total, with the detail a unit is priced from.
    An ingredient whose section is unread has a tally of ``None`` and is
    named under ``unread``, never read as a zero. One whose section was read
    in part (a file that does not parse or could not be read: the parts
    ``_PARTS_PRICED`` names) keeps its tally, a lower bound, and is named
    under ``unread`` too."""
    tree, defs, g = _functions_ctx(ctx)
    known = {_module_of(p) for p in _tracked(ctx) if p.endswith(".py")}
    tally: dict[str, dict[str, int] | None] = {}
    total: dict[str, int | None] = {}
    own_apart: dict[str, int] = {}
    unread: dict[str, str] = {}
    detail: dict = {}

    def read(section: str, ingredients: tuple[str, ...]):
        try:
            got = _section(ctx, section)
        except Unread as exc:
            got = None
            for k in ingredients:
                unread[k] = f"the {section} section is unread: {exc}"
        parts = {p: why for p, why in ctx.get("_partial_unread", {}).get(section, {}).items()
                 if p in _PARTS_PRICED.get(section, ())}
        if got is not None and parts:
            for k in ingredients:
                unread[k] = f"the {section} section was read in part, so this is a lower bound: " + "; ".join(
                    f"{section}.{p}: {why}" for p, why in sorted(parts.items()))
        for k in ingredients:
            tally[k] = None if got is None else {}
            total[k] = None
        return got

    def add(k: str, name: str, n: int = 1) -> None:
        tally[k][name] = tally[k].get(name, 0) + n

    importers = read("importers", ("importers_outside", "test_imports"))
    if importers is not None:
        imp = _importers(ctx)
        outside: dict[str, dict[str, set[str]]] = {}
        tests: dict[str, set[str]] = {}
        stored_only: dict[str, set[str]] = {}
        for path, found in imp["statements"].items():
            read_here: set[str] = set()
            for f in found:
                read_here |= set(f["names"]) - set(f.get("stored_only", ()))
                for n in f["names"]:
                    if imp["files"][path]["test"]:
                        tests.setdefault(n, set()).add(path)
                    else:
                        outside.setdefault(n, {}).setdefault(path, set()).add("lazy" if f["lazy"] else "top")
            if imp["files"][path]["test"]:
                for n in set(imp["files"][path]["names"]) - read_here:
                    stored_only.setdefault(n, set()).add(path)
        tally["importers_outside"] = {n: 1 for n in outside}
        tally["test_imports"] = {n: 1 for n in tests}
        total["importers_outside"] = importers["outside_tests"]["distinct_names"]
        total["test_imports"] = importers["tests"]["distinct_names"]
        detail["module_run_files"] = {k: v["files"] for k, v in importers["entry_points"]["module_run"].items()}
        detail.update(outside=outside, tests=tests, test_stored_only=stored_only,
                      namespaces={p: c for p, c in sorted(imp["namespaces"].items()) if c},
                      importer_modules={_module_of(p): set(f["names"]) for p, f in imp["files"].items() if not f["test"]})

    patches = read("patches", ("patch_sites", "patch_targets", "patch_raising_false"))
    if patches is not None:
        by_target: dict[str, list[dict]] = {}
        for path, s in ctx["_patch_sites"]:
            add("patch_sites", s["target"])
            tally["patch_targets"][s["target"]] = 1
            if s["raising_false"]:
                add("patch_raising_false", s["target"])
            by_target.setdefault(s["target"], []).append({"file": path, "line": s["line"], "kind": s["kind"],
                                                          "raising_false": s["raising_false"]})
        total.update(patch_sites=patches["sites"], patch_targets=patches["targets"],
                     patch_raising_false=sum(v["raising_false"] for v in patches["raising_false"].values()))
        own_apart.update(patch_sites=patches["imported_into_cli"]["sites"],
                         patch_targets=patches["imported_into_cli"]["targets"])
        detail.update(patch_sites=by_target, loaders={t: set(v) for t, v in ctx["_patch_loaders"].items()})
        defined_names = {d["name"] for d in defs}
        detail["through_cli"] = {**patches["through_cli"], "first_part_defined_in_cli": sorted(
            {t.split(".")[0] for t in patches["through_cli"]["targets"] if t.split(".")[0] in defined_names})}

    readers = read("readers", ("symbol_keys",))
    if readers is not None:
        keys: dict[str, list[dict]] = {}
        for r in ctx["_reader_rows"]:
            if r["kind"] == "symbol_key":
                add("symbol_keys", r["symbol"])
                keys.setdefault(r["symbol"], []).append({"file": r["path"], "line": r["line"], "class": r["class"]})
        total["symbol_keys"] = readers["by_kind"]["symbol_key"]["sites"]
        texts = _tracked_texts(ctx)
        defined = {d["name"] for d in defs}
        cover = []
        for e in readers["hand"]["entries"]:
            if not e["exists"] or e["class"] not in ("silent", "flat-module"):
                continue
            named: set[str] = set()
            if e["class"] == "silent":
                try:
                    rtree = ast.parse(texts[e["path"]])
                except (SyntaxError, ValueError):
                    rtree = None
                named = {n.value for n in ast.walk(rtree or ast.Module(body=[], type_ignores=[]))
                         if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in defined
                         and any(a <= n.lineno <= b for a, b in e["spans"])}
            cover.append({"path": e["path"], "symbol": e["symbol"], "class": e["class"],
                          "covers": sorted(named) if named else "whole file"})
        detail.update(keys=keys, cover=cover,
                      reader_sites_not_attributed={k: readers["by_kind"][k]["sites"] for k in ("path_literal", "path_join")})

    citations = read("citations", ("citations",))
    if citations is not None:
        cites: dict[str, dict[tuple[str, str], list]] = {}
        for path, split, part, _s, sym in ctx["_citation_named"]:
            add("citations", sym)
            cell = cites.setdefault(sym, {}).setdefault((split, part), [0, set()])
            cell[0] += 1
            cell[1].add(path)
        total["citations"] = sum(citations["totals"][s]["occurrences"] for s in CITATION_SYMBOL_SPELLINGS)
        detail.update(cites=cites, citation_line_form=citations["totals"]["line"]["occurrences"],
                      citation_splits={split: None if parts is None else [p for p in _SPLIT_PARTS[split] if p in parts]
                                       for split, parts in citations["split"].items()})
        for split, parts in citations["split"].items():
            if parts is None:
                unread[f"citations.{split}"] = citations["unread"].get(split, "the split is unread at the pin")

    probes = read("probes", ("probes",))
    if probes is not None:
        ids: dict[str, list[tuple[str, str]]] = {}
        for r in probes["rows"]:
            for s in r["symbols"]:
                add("probes", s)
                ids.setdefault(s, []).append((r["id"], r["row"]))
        total["probes"] = probes["symbols_named"]["pairs"]
        detail["probes"] = ids
        detail["probes_not_attributed"] = {
            "reading_cli_no_symbol": sorted(r["id"] for r in probes["rows"] if set(r["by"]) - {"subject"}
                                            and not r["symbols"]),
            "subject_only": sorted(r["id"] for r in probes["rows"] if r["by"] == ["subject"])}

    doctor = read("doctor_boundary", ("doctor",))
    if doctor is not None:
        tally["doctor"] = {n: 1 for n in doctor["names"]["per_name"]}
        total["doctor"] = doctor["names"]["count"]
        own_apart["doctor"] = len(doctor["names"]["not_in_cli"])

    functions = read("functions", ("lazy_imports",))
    lazy = {d["name"]: lazy_targets(d["node"], CLI, known) for d in defs if d["kind"] != NAME}
    if functions is not None:
        tally["lazy_imports"] = {n: len(v) for n, v in lazy.items() if v}
        total["lazy_imports"] = functions["unresolved"]["lazy_imports"]
    bindings = import_bindings(tree, CLI, known)
    return {"tally": tally, "total": total, "own_apart": own_apart, "unread": unread, "detail": detail,
            "lazy": lazy, "bindings": bindings, "bound_loads": {d["name"]: _bound_loads(d, bindings) for d in defs}}


def move_sums(defs: list[dict], inp: dict) -> dict:
    """Task 3's sum, asserted for each ingredient that was read: its tally
    summed over every top-level definition at the pin, plus the names it
    counts that cli imports and those cli does not bind, equals the section's
    own total; where the section splits its own total, the two apart parts
    equal that split."""
    names = {d["name"] for d in defs}
    out = {}
    for k, tally in inp["tally"].items():
        if tally is None:
            continue
        defined = sum(tally.get(d["name"], 0) for d in defs)
        apart: dict[str, list[str]] = {"imported_into_cli": [], "not_bound_in_cli": []}
        for n in sorted(tally):
            if n not in names:
                apart["imported_into_cli" if n in inp["bindings"] else "not_bound_in_cli"].append(n)
        parts = {p: sum(tally[n] for n in v) for p, v in apart.items()}
        assert defined + parts["imported_into_cli"] + parts["not_bound_in_cli"] == inp["total"][k], \
            f"move_cost: {k} reads {defined} defined + {parts} apart against the section's {inp['total'][k]}"
        if k in inp["own_apart"]:
            assert parts["imported_into_cli"] + parts["not_bound_in_cli"] == inp["own_apart"][k], \
                f"move_cost: {k}'s apart parts {parts} against the section's own split {inp['own_apart'][k]}"
        out[k] = {"defined": defined, **parts, "section_total": inp["total"][k], "total_from": MOVE_TOTALS[k],
                  "apart": apart}
    return out


#: Each ingredient's figure on one priced unit, aggregated from the unit's own
#: sites, lists and split cells rather than from the whole-file tally.
_UNIT_FIGURE = {
    "importers_outside": lambda u: u["importers_outside"]["names"],
    "test_imports": lambda u: u["test_imports"]["names"],
    "patch_sites": lambda u: u["patches"]["sites"],
    "patch_targets": lambda u: u["patches"]["targets"],
    "patch_raising_false": lambda u: u["patches"]["raising_false"],
    "symbol_keys": lambda u: u["readers"]["symbol_key"]["sites"],
    "citations": lambda u: u["citations"]["in_split"],
    "probes": lambda u: u["probes"]["pairs"],
    "doctor": lambda u: u["doctor"]["count"],
    "lazy_imports": lambda u: u["outbound"]["lazy"]["statements"],
}


def move_partition(defs: list[dict], concerns: list[dict], inp: dict, sums: dict) -> dict:
    """The units checked against the whole file: the concern units are
    disjoint, and with the definitions no concern owns (shared and unreached)
    they cover every definition. For each ingredient that was read, the
    concerns' figures (``_UNIT_FIGURE``) plus the tally over the rest equal the
    ingredient's defined total, so a unit figure that loses a site, a member or
    a citation split part fails here. A citation split unread at the pin
    leaves that ingredient unchecked, named."""
    seen: dict[str, str] = {}
    for u in concerns:
        for m in u["members"]:
            assert m not in seen, f"move_cost: {m} is in two concern units, {seen[m]} and {u['unit']}"
            seen[m] = u["unit"]
    names = {d["name"] for d in defs}
    assert set(seen) <= names, f"move_cost: concern members that are no definition: {sorted(set(seen) - names)}"
    rest = names - set(seen)
    out: dict = {"concern_units": len(concerns), "owned": len(seen), "rest": len(rest), "ingredients": {},
                 "unchecked": {}}
    for k, figure in _UNIT_FIGURE.items():
        tally = inp["tally"].get(k)
        if tally is None or k not in sums:
            continue
        if k == "citations" and any(v is None for u in concerns for v in u["citations"]["split"].values()):
            out["unchecked"][k] = "a citation split is unread at the pin, so a unit's split cells are partial"
            continue
        units_sum = sum(figure(u) for u in concerns)
        rest_sum = sum(tally.get(n, 0) for n in rest)
        assert units_sum + rest_sum == sums[k]["defined"], \
            f"move_cost: {k}'s concern units read {units_sum} + {rest_sum} over the rest against {sums[k]['defined']}"
        out["ingredients"][k] = {"concern_units": units_sum, "rest": rest_sum, "defined": sums[k]["defined"]}
    return out


def section_move_cost(ctx: dict) -> dict:
    """Task 3's move cost per unit, sized for both re-export branches (Task 4).
    The units are each hand layer (its members, and its ``tie_closed`` set
    beside them) and each concern the clusters section computes (the
    definitions it owns). Each is priced by its size; its importers outside
    tests (the hand-built ``argparse.Namespace`` flagged); the names tests
    import; its test patches, with the loaders each target keeps outside the
    unit; its readers by path; its citations by split; the ledger probes that
    read it; its outbound edges and the cycles they would close; its doctor
    names; the latches outside it that its members touch; what a second copy
    of cli under ``-m`` would hold; and, per branch, what stays green while
    wrong and what fails loudly. An ingredient whose section is unread is
    ``None`` and named under the census's ``unread`` as
    ``move_cost.<ingredient>``, never read as zero. Every ingredient's tally
    over the whole file is summed against its section's own total
    (``move_sums``), and the concern units' own figures against that tally
    (``move_partition``)."""
    tree, defs, g = _functions_ctx(ctx)
    layers = _section(ctx, "layers")
    clusters = _clusters(ctx)
    inp = _move_inputs(ctx)
    tally, detail = inp["tally"], inp["detail"]
    kinds = {d["name"]: d["kind"] for d in defs}
    lines = {d["name"]: d["lines"] for d in defs}
    by_name = {d["name"]: d for d in defs}
    table = latches(tree, defs, g)
    sums = move_sums(defs, inp)

    def read(*keys: str) -> bool:
        return all(tally.get(k) is not None for k in keys)

    def price(members: set[str]) -> dict:
        ms = sorted(members)
        callers = {(d, m) for d, es in g["edges"].items() if d not in members for m in es if m in members}
        kept = {m for _d, m in callers}  # members a cli definition left behind still loads or writes
        out: dict = {"size": {"definitions": len(ms), **_size(members, kinds, lines)}}
        if read("importers_outside"):
            files: dict[str, dict[str, list[str]]] = {}
            for m in ms:
                for path, how in detail["outside"].get(m, {}).items():
                    for h in sorted(how):
                        files.setdefault(path, {}).setdefault(h, []).append(m)
            out["importers_outside"] = {
                "names": sum(1 for m in ms if m in detail["outside"]),
                "pairs": sum(len(detail["outside"].get(m, {})) for m in ms),
                "files": dict(sorted(files.items())),
                "namespace_by_hand": [{"file": p, **c} for p, calls in detail["namespaces"].items()
                                      for c in calls if c["name"] in members]}
            per_name = {m: len(detail["tests"][m]) for m in ms if m in detail["tests"]}
            out["test_imports"] = {"names": len(per_name),
                                   "files": len(set().union(*(detail["tests"][m] for m in per_name))),
                                   "pairs": sum(per_name.values()),
                                   "stored_only_pairs": sum(len(detail["test_stored_only"].get(m, ())) for m in ms),
                                   "per_name": per_name}
        else:
            out["importers_outside"] = out["test_imports"] = None
        if read("patch_sites"):
            per_target = {}
            for t in ms:
                sites = detail["patch_sites"].get(t)
                if not sites:
                    continue
                loaders = detail["loaders"].get(t, set())
                per_target[t] = {"sites": len(sites), "raising_false": sum(1 for s in sites if s["raising_false"]),
                                 "assign": sum(1 for s in sites if s["kind"] == "assign"),
                                 "loaders_inside": sorted(loaders & members), "loaders_outside": sorted(loaders - members)}
            left = sorted(t for t, v in per_target.items() if v["loaders_inside"] and v["loaders_outside"])
            loaded = sorted(t for t, ls in detail["loaders"].items() if t not in members and ls & members)
            out["patches"] = {
                "targets": len(per_target), "sites": sum(v["sites"] for v in per_target.values()),
                "raising_false": sum(v["raising_false"] for v in per_target.values()),
                "files": len({s["file"] for t in per_target for s in detail["patch_sites"][t]}),
                "left_behind_loader": {"targets": left, "sites": sum(per_target[t]["sites"] for t in left)},
                "loaded_not_member": {"targets": loaded, "sites": sum(len(detail["patch_sites"][t]) for t in loaded)},
                "per_target": per_target}
        else:
            out["patches"] = None
        if read("symbol_keys"):
            keyed = {m: detail["keys"][m] for m in ms if m in detail["keys"]}
            sites = [s for v in keyed.values() for s in v]
            out["readers"] = {
                "symbol_key": {"sites": len(sites), "files": len({s["file"] for s in sites}), "symbols": sorted(keyed),
                               "by_class": {c: sum(1 for s in sites if s["class"] == c) for c in READER_CLASS_NAMES}},
                **{key: [{k: v for k, v in c.items() if k != "class"} for c in detail["cover"] if c["class"] == klass
                         and ms and (c["covers"] == "whole file" or members & set(c["covers"]))]
                   for key, klass in (("silent", "silent"), ("flat_module", "flat-module"))}}
        else:
            out["readers"] = None
        if read("citations"):
            split_out: dict = {}
            for split, parts in detail["citation_splits"].items():
                if parts is None:
                    split_out[split] = None
                    continue
                split_out[split] = {}
                for p in parts:
                    cells = [detail["cites"][m][(split, p)] for m in ms if (split, p) in detail["cites"].get(m, {})]
                    split_out[split][p] = {"occurrences": sum(c[0] for c in cells),
                                           "files": len(set().union(*(c[1] for c in cells)))}
            out["citations"] = {"occurrences": sum(tally["citations"].get(m, 0) for m in ms),
                                "in_split": sum(cell["occurrences"] for split, parts in split_out.items()
                                                if parts and split != "unread" for cell in parts.values()),
                                "split": split_out}
        else:
            out["citations"] = None
        if read("probes"):
            hits = [pair for m in ms for pair in detail["probes"].get(m, [])]
            out["probes"] = {"ids": sorted({i for i, _row in hits}), "pairs": len(hits),
                             "by_row": {r: len({i for i, row in hits if row == r}) for r in PROBE_ROW_STATES}}
        else:
            out["probes"] = None
        lazy_by: dict[str, int] = {}
        for m in ms:
            for st in inp["lazy"].get(m, []):
                for mod in st["modules"]:
                    lazy_by[mod] = lazy_by.get(mod, 0) + 1
        top_by: dict[str, set[str]] = {}
        for m in ms:
            for n in inp["bound_loads"][m]:
                top_by.setdefault(inp["bindings"][n], set()).add(n)
        back = {(m, t) for m in ms for t in g["edges"][m] if t not in members}
        writes = {(m, t) for m in ms for t in g["writes"].get(m, ()) if t not in members}
        cycles = None
        if read("importers_outside"):
            cycles = []
            for mod in sorted(set(lazy_by) | set(top_by)):
                takes = detail["importer_modules"].get(mod)
                if takes is None:
                    continue
                took = sorted(takes & members)
                others = len(takes - members)
                cycles.append({"module": mod, "via": [v for v, on in (("lazy", mod in lazy_by), ("top", mod in top_by)) if on],
                               "takes_members": took, "takes_other_names": others,
                               "closes": bool(took) or (others > 0 and bool(callers))})
        out["outbound"] = {
            "lazy": {"statements": sum(len(inp["lazy"].get(m, [])) for m in ms), "by_module": dict(sorted(lazy_by.items()))},
            "top_level_imports_loaded": {mod: sorted(v) for mod, v in sorted(top_by.items())},
            "back_edges": {"definitions": len({t for _m, t in back}), "edges": len(back), "writes": len(writes),
                           "names": sorted({t for _m, t in back})},
            "cli_callers": {"definitions": len({d for d, _m in callers}), "edges": len(callers),
                            "members_kept_bound": sorted(kept)},
            "cli_cycle": bool(back) and bool(callers),
            "importer_cycles": cycles}
        out["doctor"] = None if not read("doctor") else {"names": [m for m in ms if m in tally["doctor"]],
                                                         "count": sum(1 for m in ms if m in tally["doctor"])}
        rows = [{"latch": n, "value": _initial_value(by_name[n]),
                 "users_outside": sorted((set(t["writers"]) | set(t["readers"])) - members)}
                for n, t in table["latches"].items() if n in members]
        across = [{"latch": n, "value": _initial_value(by_name[n]), "members_writing": sorted(set(t["writers"]) & members),
                   "members_reading": sorted(set(t["readers"]) & members)}
                  for n, t in table["latches"].items() if n not in members and (set(t["writers"]) | set(t["readers"])) & members]
        memos_across = sorted(n for n, t in table["memos"].items()
                              if n not in members and (set(t["writers"]) | set(t["readers"])) & members)
        out["latches_across"] = across
        out["module_run"] = {"imports_cli": bool(back),
                             "state_in_a_second_copy": sorted({a["latch"] for a in across} | set(memos_across)) if back else []}
        patches, readers_ = out["patches"], out["readers"]
        loud_readers = None if readers_ is None else readers_["symbol_key"]["by_class"]["loud"]
        stale = [] if patches is None else [t for t, v in patches["per_target"].items() if v["loaders_inside"]]
        across_names = [a["latch"] for a in across]
        out["with_reexports"] = {
            "stale_patch_sites": None if patches is None else {
                "targets": stale, "sites": sum(patches["per_target"][t]["sites"] for t in stale),
                "of_which_loaders_on_both_sides": patches["left_behind_loader"]["sites"]},
            "stale_in_both": None if patches is None else patches["loaded_not_member"],
            "latches_split": [r for r in rows if r["value"] in ("bool", "None")],
            "latches_other": [r for r in rows if r["value"] not in ("bool", "None")],
            "latches_across": across_names,
            "memos_shared": sorted(n for n in table["memos"] if n in members),
            "loud_readers": loud_readers,
            "cli_cycle": bool(back)}
        silent_of = {} if patches is None else {
            t: sum(1 for s in detail["patch_sites"][t] if s["raising_false"] or s["kind"] == "assign")
            for t in patches["per_target"]}
        silent = None if patches is None else sum(silent_of.values())
        loud_patches = None if patches is None else patches["sites"] - silent
        imports, outside = out["test_imports"], out["importers_outside"]
        loud_imports = None if imports is None else imports["pairs"] - imports["stored_only_pairs"]
        parts = (loud_imports, loud_patches, None if outside is None else outside["pairs"], loud_readers)
        loud = None if None in parts else sum(parts)
        bound_parts = (
            None if imports is None else sum(len(detail["tests"][m]) - len(detail["test_stored_only"].get(m, ()))
                                             for m in ms if m in kept and m in detail["tests"]),
            None if patches is None else sum(v["sites"] - silent_of[t] for t, v in patches["per_target"].items()
                                             if t in kept),
            None if outside is None else sum(len(detail["outside"][m]) for m in ms if m in kept and m in detail["outside"]))
        out["without_reexports"] = {
            "test_imports": None if imports is None else {
                **{k: imports[k] for k in ("names", "files", "pairs", "stored_only_pairs")}, "loud_pairs": loud_imports},
            "patches": None if patches is None else {"loud_sites": loud_patches, "silent_creates": silent},
            "outside_importers": None if outside is None else {
                "names": outside["names"], "pairs": outside["pairs"], "files": len(outside["files"])},
            "loud_readers": loud_readers,
            "loud_sites": loud,
            "if_cli_from_imports_what_it_still_loads": {
                "names": sorted(kept),
                "test_import_pairs": bound_parts[0], "patch_sites": bound_parts[1], "outside_importer_pairs": bound_parts[2],
                "loud_sites": None if loud is None or None in bound_parts else loud - sum(bound_parts)},
            "stale_in_both": None if patches is None else patches["loaded_not_member"],
            "latches_across": across_names}
        return out

    units = []
    for layer in layers["layers"]:
        base = set(layer["members"])
        for which, members in (("members", base), ("tie_closed", base | set(layer["tie_closed"]["pulled"]))):
            units.append({"unit": layer["name"], "kind": "layer", "set": which, "members": sorted(members),
                          **price(members)})
    con = clusters["concerns"]
    for name, row in con["per_root"].items():
        units.append({"unit": name, "kind": "concern", "cluster_source": "hand" if name in con["groups"] else "command",
                      "set": "owned", "members": list(row["members"]), **price(set(row["members"]))})
    partition = move_partition(defs, [u for u in units if u["kind"] == "concern"], inp, sums)
    ctx.setdefault("_partial_unread", {})["move_cost"] = dict(inp["unread"])
    return {"rule": MOVE_RULES, "units": units, "sums": sums, "partition": partition, "unread": inp["unread"],
            "not_attributed": {"reader_sites": detail.get("reader_sites_not_attributed"),
                               "citation_line_form": detail.get("citation_line_form"),
                               "probes": detail.get("probes_not_attributed"),
                               "patches_through_cli": detail.get("through_cli")},
            "module_run_files": detail.get("module_run_files"),
            "namespace_by_hand": detail.get("namespaces")}


# ---------------------------------------------------------------- the record at the pin: merges, PRs, mail

@functools.lru_cache(maxsize=None)
def _merge_cost():
    """``scripts/merge_cost_census.py`` by path: the replay with GitHub's merge
    rules (every driver off) and its catch-up rule."""
    return _load("_ccc_merge_cost", "scripts/merge_cost_census.py")


@functools.lru_cache(maxsize=None)
def _overlap():
    """``scripts/lane_overlap_census.py`` by path: the mirror fold the pair
    census reads every path through."""
    return _load("_ccc_lane_overlap", "scripts/lane_overlap_census.py")


@functools.lru_cache(maxsize=None)
def _mail():
    """``tools/cc/mail.py`` by path: its decoder, its release rule, its claim
    view and its lane-to-seat fold."""
    return _load("_ccc_mail", "tools/cc/mail.py")


#: A pull request's merge on the base: ``Merge pull request #N from owner/branch``.
PR_SUBJECT = re.compile(r"^Merge pull request #(\d+) from [^/\s]+/(\S+)")


def _stamp(text: str) -> str:
    """An ISO time from git (``+00:00``) or GitHub (``Z``) in one spelling, so
    the two sort and compare as text."""
    return _iso_z(datetime.fromisoformat(text.replace("Z", "+00:00")))


def merges_at(root: Path, at: str) -> list[dict]:
    """Every merge commit reachable from the pin, newest first: its oid, its
    parents, its committer date and its subject. One ``git log``, split on
    ``\\n`` alone: ``splitlines`` also splits a subject holding U+2028, ``\\x85``
    or ``\\x1c`` to ``\\x1e``, where git ends a record only at the newline."""
    rc, out, err = git(root, "log", "--merges", "--format=%H%x1f%P%x1f%cI%x1f%s", at)
    if rc != 0:
        raise Unread(f"git log --merges {at[:12]} failed: {err.strip()}")
    rows = []
    for line in (row for row in out.split("\n") if row):
        oid, parents, date, subject = (line.split("\x1f") + ["", "", ""])[:4]
        rows.append({"oid": oid, "parents": parents.split(), "date": _stamp(date), "subject": subject})
    return rows


def pr_merges(root: Path, at: str) -> list[dict]:
    """The pull requests merged at the pin, read from git alone: each first-
    parent merge headed ``Merge pull request #N from owner/branch``, with its
    number, its branch, its two parents (the base it landed on, its head) and
    its date. A pull request is at the pin when its merge commit is an
    ancestor of it, so no later merge can enter a pinned read."""
    rc, out, err = git(root, "log", "--first-parent", "--merges", "--format=%H", at)
    if rc != 0:
        raise Unread(f"git log --first-parent {at[:12]} failed: {err.strip()}")
    first = set(out.split())
    rows = []
    for m in merges_at(root, at):
        hit = PR_SUBJECT.match(m["subject"])
        if m["oid"] in first and hit and len(m["parents"]) == 2:
            rows.append({"number": int(hit.group(1)), "branch": hit.group(2), "merge": m["oid"],
                         "base": m["parents"][0], "head": m["parents"][1], "date": m["date"]})
    return rows


def lane_commits(root: Path, pr: dict) -> list[dict]:
    """A pull request's own commits, ``base..head`` (what GitHub lists as its
    commits), as ``merge_cost_census`` reads them: an oid and a headline."""
    rc, out, _err = git(root, "log", "--format=%H%x1f%s", f"{pr['base']}..{pr['head']}")
    if rc != 0:
        raise Unread(f"git log {pr['base'][:12]}..{pr['head'][:12]} failed")
    return [{"oid": a, "messageHeadline": b} for a, _sep, b in (row.partition("\x1f") for row in out.split("\n") if row)]


def lane_files(root: Path, pr: dict) -> tuple[str, list[str]]:
    """``(merge-base, paths)``: what the lane changed against the base it
    branched from, at its merge (``git diff --name-only -z <merge-base> <head>``,
    NUL-separated so a path git would quote reads as itself)."""
    rc, out, err = git(root, "merge-base", pr["base"], pr["head"])
    if rc != 0 or not out.strip():
        raise Unread(f"no merge-base for #{pr['number']}: {err.strip()}")
    mb = out.strip()
    rc, out, err = git(root, "diff", "--name-only", "-z", mb, pr["head"])
    if rc != 0:
        raise Unread(f"git diff {mb[:12]} {pr['head'][:12]} failed: {err.strip()}")
    return mb, [p for p in out.split("\0") if p]


def _in_window(when: str, window: dict) -> bool:
    return window["since"] <= when <= window["until"]


def _prs(ctx: dict) -> list[dict]:
    """The pull requests at the pin, each with its merge-base and files,
    read once a run."""
    if "_prs" not in ctx:
        rows = pr_merges(ctx["root"], ctx["pin"]["at"])
        for pr in rows:
            pr["merge_base"], pr["files"] = lane_files(ctx["root"], pr)
        ctx["_prs"] = rows
    return ctx["_prs"]


def _touches_cli(paths, modules) -> list[str]:
    return sorted({m for m in modules for p in paths if p == m})


def pr_meta(ctx: dict) -> dict[int, dict]:
    """``{number: {"created", "merged"}}``: when each pull request opened, the
    one fact git does not hold. Read from ``--prs-json`` (a saved ``gh pr list
    --json number,createdAt,mergedAt``) or from ``gh``, every number to #1.
    A ``--prs-json`` file that is not there or holds no list of pull requests,
    a ``gh`` that cannot run, fails or answers no JSON: ``Unread``."""
    if "_pr_meta" in ctx:
        return ctx["_pr_meta"]
    path = ctx.get("prs_json")
    source = f"--prs-json {path}" if path else "gh pr list"
    if path:
        try:
            listed = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Unread(f"--prs-json {path} unreadable: {type(exc).__name__}: {exc}") from None
    else:
        try:
            proc = run_bounded(["gh", "pr", "list", "--state", "merged", "--limit", "1000", "--json",
                                "number,createdAt,mergedAt"], capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=GIT_TIMEOUT, cwd=str(ctx["root"]))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Unread(f"gh pr list cannot run: {type(exc).__name__}: {exc}") from None
        if proc.returncode != 0:
            raise Unread(f"gh pr list failed: {proc.stderr.strip()[:200]}")
        try:
            listed = json.loads(proc.stdout or "[]")
        except ValueError as exc:
            raise Unread(f"gh pr list answered no JSON: {exc}") from None
    try:
        ctx["_pr_meta"] = {int(p["number"]): {"created": _stamp(p["createdAt"]), "merged": _stamp(p["mergedAt"])}
                           for p in listed if p.get("createdAt") and p.get("mergedAt")}
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise Unread(f"{source}: the pull requests' list is malformed: {type(exc).__name__}: {exc}") from None
    return ctx["_pr_meta"]


def mail_refs(root: Path) -> dict[str, str]:
    """``{machine: oid}`` of each remote-tracking mail ref: read once, at the
    start of a run, and written into the pin, so a re-run names what it read.
    A ``git for-each-ref`` that fails is ``Unread``, never a clone of no mail."""
    rc, out, err = git(root, "for-each-ref", "--format=%(objectname) %(refname)", "refs/remotes/origin/mail/")
    if rc != 0:
        raise Unread(f"git for-each-ref refs/remotes/origin/mail/ failed: {err.strip()[:200]}")
    refs = {}
    for line in out.splitlines():
        oid, _sp, ref = line.partition(" ")
        refs[ref.rsplit("/", 1)[-1]] = oid
    return refs


def mail_at(ctx: dict) -> dict[str, list[dict]]:
    """Every machine's messages at the pinned mail oids, cut at the pin's
    date by each message's own stamp: a message sent after P is not in a
    read at P, whatever the ref holds now. Mail refs the run could not read
    (``ctx["_mail_refs_unread"]``, set by ``census``) are ``Unread`` with
    that reason, never a clone of no mail."""
    if "_mail_at" in ctx:
        return ctx["_mail_at"]
    if ctx.get("_mail_refs_unread"):
        raise Unread(f"the mail refs could not be read: {ctx['_mail_refs_unread']}")
    refs = ctx["pin"].get("mail_refs") or {}
    if not refs:
        raise Unread("no mail refs in this clone (refs/remotes/origin/mail/*)")
    out: dict[str, list[dict]] = {}
    for machine, oid in sorted(refs.items()):
        rc, text, err = git(ctx["root"], "show", f"{oid}:mail.jsonl")
        if rc != 0:
            raise Unread(f"mail of {machine} at {oid[:12]} unreadable: {err.strip()}")
        messages, _bad = _mail().decode_lines(text)
        out[machine] = [m for m in messages if str(m.get("at") or "") <= ctx["pin"]["window"]["until"]]
    ctx["_mail_at"] = out
    ctx["_mail_seats_missing"] = sorted(mail_seats_named(out) - set(out))
    return out


#: A message id, ``<stamp>-<machine>-<six hex>``: the sender is its middle.
_MESSAGE_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-(?P<machine>[a-z0-9][a-z0-9-]*)-[0-9a-f]{6}$")


def mail_seats_named(by_machine: dict[str, list[dict]]) -> set[str]:
    """Every seat the read mail names: each message's sender, each assign's
    seat, and the sender of each message an ack answers. A seat named here
    whose mail ref the clone does not hold has claims, releases and holds
    this run cannot read, so the sections that fold the mail name it under
    ``unread`` rather than counting over the seats that are here."""
    names: set[str] = set()
    for messages in by_machine.values():
        for m in messages:
            for value in (m.get("from"), (m.get("re") or {}).get("seat")):
                if value:
                    names.add(str(value))
            hit = _MESSAGE_ID.match(str(m.get("ack") or ""))
            if hit:
                names.add(hit.group("machine"))
    return names


def _name_missing_mail_seats(ctx: dict, section: str) -> None:
    """Name ``<section>.mail_seats`` where the mail names a seat whose ref
    this clone lacks (``mail_at``)."""
    missing = ctx.get("_mail_seats_missing") or []
    if missing:
        _partial(ctx, section, "mail_seats", f"the mail names seat(s) {missing} whose mail ref this clone does not "
                                             "hold, so their claims, releases and holds are not read: fetch "
                                             "refs/heads/mail/* from origin and read again")


def claim_intervals(by_machine: dict[str, list[dict]], until: str) -> list[dict]:
    """Each claim with the stamp of the release that closed it (the mail
    driver's own release rule), or the pin's date where none did by then."""
    mail = _mail()
    out = []
    for machine, messages in by_machine.items():
        for i, m in enumerate(messages):
            if m.get("type") != "claim":
                continue
            end = next((str(r.get("at") or "") for r in messages[i + 1:]
                        if r.get("type") == "release" and mail._releases(r, m["id"], m)), None)
            _syms, _more, whole, _unplaced = mail.claim_view(m.get("re") or {})
            files = {s.split("::", 1)[0] for s in _syms}
            out.append({"id": m["id"], "machine": str(m.get("from") or machine),
                        "lane": str((m.get("re") or {}).get("lane") or ""), "start": str(m.get("at") or ""),
                        "end": end or until, "closed": end is not None, "paths": sorted(whole | files)})
    return out


def _claim_names(claim: dict, module: str) -> bool:
    return any(_mail()._touches(p, module) for p in claim["paths"])


#: The words a dispatcher uses to hold one lane for another. ``Waits for:
#: nothing`` (the assign's own line when nothing waits) is struck first.
HOLD_WORDS = re.compile(r"(?i)\b(waits? for|the other waits|hold(s|ing)? (it|the|your|its|back)|held)\b")
NO_WAIT = re.compile(r"(?i)waits for:\s*nothing[^.\n]*")
#: The dispatcher's messages that can hold a lane. A claim or a release is a
#: seat's own declaration of its files, even when the dispatcher seat sends
#: it as a worker: air's claim 66aaa6 (2026-10-08) names cli.py and "waits
#: for" in its own pack's sequencing, and is no hold.
RULING_TYPES = ("note", "ack", "assign", "request")


def names_module(text: str, module: str) -> bool:
    """``text`` names ``module`` by its path or its bare file name, as a whole
    token: ``espalier/cli.py`` and ``cli.py`` do, ``test_cli.py`` does not."""
    name = re.escape(Path(module).name)
    return re.search(rf"(?<![\w.-])(?:{re.escape(module)}|{name})(?![\w])", text) is not None


def dispatcher_at(ctx: dict) -> str | None:
    text = source_at(ctx["root"], ctx["pin"]["at"], "espalier.toml")
    try:
        value = tomllib.loads(text or "").get("dispatcher")
    except tomllib.TOMLDecodeError:
        return None
    return value if isinstance(value, str) and value else None


def replay_merges(clone: Path, oids: list[str], runner) -> dict[str, list[str]]:
    """``{oid: conflicted paths}`` for each merge that does not replay clean
    (``merge_cost_census.replay``: rc 1 is a conflict, any other rc raises)."""
    out = {}
    for oid in oids:
        _tree, conflicted = _merge_cost().replay(clone, oid, runner)
        if conflicted or _tree is not None:
            out[oid] = conflicted
    return out


def _set_attributes(clone: Path, text: str) -> None:
    (clone / ".git" / "info" / "attributes").write_text(text, encoding="utf-8")


def conflicts(ctx: dict) -> dict:
    """The replay, whole record, under two instruments named apart.

    ``lane_side``: the authoring read, every merge reachable from the pin that
    is not a pull request's merge (catch-ups and stacks), replayed twice: with
    the pin's own ``.gitattributes`` (drivers on, as the authoring replay ran)
    and with every driver off (GitHub's merge). ``catch_ups``:
    ``merge_cost_census.replay_all`` over the pin's every pull request (its
    list built from git, ``base..head`` as its commits: the ``--prs`` at the
    list's length that reaches #1), drivers off, which replays only the
    catch-up merges the list holds. A conflict on a CLI module is listed by
    oid and date under each."""
    root, at = ctx["root"], ctx["pin"]["at"]
    mcc = _merge_cost()
    runner = ctx.get("runner") or mcc._ship_runner()
    side = [m for m in merges_at(root, at) if not PR_SUBJECT.match(m["subject"])]
    dates = {m["oid"]: m["date"] for m in side}
    prs = [{"number": pr["number"], "headRefName": pr["branch"], "commits": lane_commits(root, pr)}
           for pr in _prs(ctx)]
    attrs = source_at(root, at, ".gitattributes") or ""
    clone = mcc.scratch_clone(root, runner)
    try:
        _set_attributes(clone, attrs)
        on = replay_merges(clone, [m["oid"] for m in side], runner)
        _set_attributes(clone, "".join(f"{o}\n" for o in mcc.driver_overrides(attrs)))
        off = replay_merges(clone, [m["oid"] for m in side], runner)
        caught = mcc.replay_all(prs, clone, runner)
    finally:
        shutil.rmtree(clone.parent, ignore_errors=True)
    modules = ctx["modules"]

    def on_cli(found: dict[str, list[str]]) -> list[dict]:
        return [{"oid": o, "date": dates.get(o), "paths": _touches_cli(ps, modules)}
                for o, ps in sorted(found.items(), key=lambda kv: dates.get(kv[0], "")) if _touches_cli(ps, modules)]

    cu_cli = [{"oid": c["oid"], "pr": c["pr"], "paths": _touches_cli(c["files"], modules)}
              for c in caught["per_catch_up"] if _touches_cli(c["files"], modules)]
    return {"graded": False,
            "lane_side": {"rule": "git log --merges <P>, subject not 'Merge pull request'; "
                                  "git merge-tree --write-tree on ^1 ^2 in a --shared clone",
                          "merges": len(side),
                          "drivers_on": {"conflicted_any_file": len(on), "on_cli_modules": on_cli(on)},
                          "drivers_off": {"conflicted_any_file": len(off), "on_cli_modules": on_cli(off)}},
            "catch_ups": {"rule": "merge_cost_census.replay_all over every pull request at P (base..head "
                                  "from git), drivers off",
                          "prs": len(prs), "lowest_pr": min((p["number"] for p in prs), default=None),
                          "catch_up_merges": caught["catch_up_merges"], "conflicted_any_file": caught["conflicted"],
                          "on_cli_modules": cu_cli}}


def _window_prs(ctx: dict) -> list[dict]:
    return [pr for pr in _prs(ctx) if _in_window(pr["date"], ctx["pin"]["window"])]


def concurrent_pairs(ctx: dict) -> dict:
    """C1: the window's pull requests that change a CLI module, read pairwise.
    Two were concurrent when each opened before the other merged
    (``_symbols.concurrent``). Each concurrent pair gets
    ``_symbols.pair_verdict`` over the CLI modules alone (each side's
    placements from ``_symbols.symbols_between`` at its merge-base, through the
    overlap census's mirror fold), so a pair that also shares another file is
    graded on the CLI modules. Graded: ``shared symbol`` and ``unplaced``
    (``different functions`` is certified)."""
    meta = pr_meta(ctx)
    modules = ctx["modules"]
    sym = _symbols()
    lanes = [pr for pr in _window_prs(ctx) if _touches_cli(pr["files"], modules)]
    no_meta = sorted(pr["number"] for pr in lanes if pr["number"] not in meta)
    info = {}
    for pr in lanes:
        if pr["number"] in no_meta:
            continue
        placements = sym.symbols_between(pr["merge_base"], pr["head"], root=ctx["root"], fold=_overlap().canonical)
        info[pr["number"]] = {**meta[pr["number"]],
                              "placements": {m: placements[m] for m in modules if m in placements}}
    pairs = []
    concurrent_count = 0
    for a, b in itertools.combinations(sorted(info), 2):
        if not sym.concurrent(info[a], info[b]):
            continue
        concurrent_count += 1
        v = sym.pair_verdict(info[a]["placements"], info[b]["placements"])
        pairs.append({"a": a, "b": b, "verdict": v["verdict"], "shared": v["shared"], "files": v["files"]})
    by = {v: sum(1 for p in pairs if p["verdict"] == v) for v in sym.VERDICTS}
    return {"prs": len(lanes), "numbers": sorted(pr["number"] for pr in lanes), "no_created_at": no_meta,
            "concurrent_pairs": concurrent_count, "by_verdict": by,
            "graded_count": by["shared symbol"] + by["unplaced"], "pairs": pairs}


def claim_overlaps(ctx: dict) -> dict:
    """C2: of the window's CLI-module lanes, the share whose claim window (its
    seat's first claim on the lane to the last release of one) overlapped
    another seat's claim naming the same CLI module the lane changed. A lane
    whose seat sent no claim on it has no window: counted apart, and the share
    is given both over the lanes with a window (graded) and over all. The
    stricter reading (the lane's own claim names the module too) and the
    cross-seat lane pairs are printed beside it."""
    by_machine = mail_at(ctx)
    seats = _mail().lane_seats(by_machine)
    claims = claim_intervals(by_machine, ctx["pin"]["window"]["until"])
    modules = ctx["modules"]
    rows, pairs = [], set()
    for pr in _window_prs(ctx):
        touched = _touches_cli(pr["files"], modules)
        if not touched:
            continue
        seat = seats.get(pr["branch"])
        own = [c for c in claims if c["lane"] == pr["branch"] and c["machine"] == seat]
        if not own:
            rows.append({"pr": pr["number"], "lane": pr["branch"], "seat": seat, "window": None, "overlaps": []})
            continue
        start, end = min(c["start"] for c in own), max(c["end"] for c in own)
        names_own = any(_claim_names(c, m) for c in own for m in touched)
        hits = [c for c in claims if c["machine"] != seat and c["start"] <= end and start <= c["end"]
                and any(_claim_names(c, m) for m in touched)]
        for c in hits:
            if c["lane"]:
                pairs.add(tuple(sorted((pr["branch"], c["lane"]))))
        rows.append({"pr": pr["number"], "lane": pr["branch"], "seat": seat, "window": [start, end],
                     "own_claim_names_module": names_own,
                     "overlaps": sorted({f"{c['machine']}:{c['lane'] or c['id']}" for c in hits})})
    with_window = [r for r in rows if r["window"]]
    hit = [r for r in with_window if r["overlaps"]]
    strict = [r for r in hit if r["own_claim_names_module"]]
    return {"lanes": len(rows), "with_claim_window": len(with_window),
            "no_claim": sorted(r["pr"] for r in rows if not r["window"]),
            "overlapping": len(hit),
            "share_graded": round(len(hit) / len(with_window), 3) if with_window else None,
            "share_over_all_lanes": round(len(hit) / len(rows), 3) if rows else None,
            "strict_overlapping": len(strict),
            "cross_seat_lane_pairs": len(pairs), "rows": rows}


def holds(ctx: dict) -> dict:
    """C3, whole record: the dispatcher's messages that hold a lane for
    another over a CLI module. ``declared``: its ``re.paths`` name a CLI
    module and its text, ``Waits for: nothing`` struck, holds one
    (``HOLD_WORDS``): the authoring read's lower bound. ``named_in_text``: the
    module named in the text alone, with the same words, listed by id for the
    hand read that confirms each (a word match is a candidate, never a hold).
    A dispatcher whose mail the pin's refs do not hold is ``Unread``, never a
    record of no holds. The record starts at the earliest message's stamp,
    whatever order the file keeps."""
    disp = dispatcher_at(ctx)
    if disp is None:
        raise Unread("espalier.toml at the pin names no usable dispatcher")
    by_machine = mail_at(ctx)
    if disp not in by_machine:
        raise Unread(f"no mail of the dispatcher {disp!r} at the pin (refs: {sorted(by_machine)})")
    messages = by_machine[disp]
    modules = ctx["modules"]
    declared, in_text = [], []
    for m in messages:
        if m.get("type") not in RULING_TYPES:
            continue
        text = NO_WAIT.sub("", str(m.get("text") or ""))
        if not HOLD_WORDS.search(text):
            continue
        paths = [str(p) for p in (m.get("re") or {}).get("paths") or []]
        if any(_mail()._touches(p, mod) for p in paths for mod in modules):
            declared.append(m["id"])
        elif any(names_module(text, mod) for mod in modules):
            in_text.append(m["id"])
    first = min((str(m["at"]) for m in messages if m.get("at")), default=None)
    days = None
    if first:
        days = round((datetime.fromisoformat(ctx["pin"]["window"]["until"].replace("Z", "+00:00"))
                      - datetime.fromisoformat(first.replace("Z", "+00:00"))).total_seconds() / 86400, 1)
    return {"dispatcher": disp, "record_from": first, "record_days": days, "messages": len(messages),
            "declared": declared, "named_in_text": in_text}


def catch_ups_carrying(ctx: dict) -> dict:
    """Context, never a cost (the up-to-date rule is off): the window's
    catch-up merges whose base side brought a CLI module change into a lane
    (``git diff --name-only -z <catch-up>^1 <catch-up>``). A diff git cannot
    give is ``Unread``, never a catch-up that carried nothing."""
    root, at = ctx["root"], ctx["pin"]["at"]
    catch = _merge_cost().CATCH_UP
    count = carrying = 0
    for m in merges_at(root, at):
        if not catch.match(m["subject"]) or not _in_window(m["date"], ctx["pin"]["window"]):
            continue
        count += 1
        rc, out, err = git(root, "diff", "--name-only", "-z", m["parents"][0], m["oid"])
        if rc != 0:
            raise Unread(f"git diff {m['parents'][0][:12]} {m['oid'][:12]} failed: {err.strip()[:200]}")
        if _touches_cli(out.split("\0"), ctx["modules"]):
            carrying += 1
    return {"graded": False, "catch_ups_in_window": count, "carrying_a_cli_module": carrying}


def section_collision(ctx: dict) -> dict:
    """Task 0 Item 2's oracle: the four components, each with its window and
    its count of CLI-module pull requests. A component that cannot be read
    (any of ``_READ_FAILURES``: the replay's ``SystemExit`` and a missing
    ``--prs-json`` among them) is named under the section's own ``unread``,
    never a zero, and the other components still read."""
    window = ctx["pin"]["window"]
    out: dict = {"window": window, "unread": {}}
    out["cli_module_prs_in_window"] = sum(1 for pr in _window_prs(ctx) if _touches_cli(pr["files"], ctx["modules"]))
    for key, reader in (("conflicts", conflicts), ("pairs", concurrent_pairs), ("claims", claim_overlaps),
                        ("holds", holds), ("catch_ups", catch_ups_carrying)):
        if key in ctx.get("skip_components", ()):
            out[key] = None
            out["unread"][key] = "skipped by the caller"
            continue
        try:
            out[key] = reader(ctx)
        except _READ_FAILURES as exc:
            out[key] = None
            out["unread"][key] = str(_unread(exc))
    _name_missing_mail_seats(ctx, "collision")
    return out


# ---------------------------------------------------------------- lane_read (the secondary, a length)

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)


def hunk_points(diff: str) -> list[tuple[int, bool]]:
    """``(line, insertion)`` for the base-side lines a ``-U0`` diff's hunks
    fall on: each changed or removed line, and for a pure insertion
    (``-L,0``) the line it follows, flagged."""
    points: list[tuple[int, bool]] = []
    for hit in _HUNK.finditer(diff):
        start, count = int(hit.group(1)), int(hit.group(2) if hit.group(2) is not None else 1)
        points.extend([(ln, False) for ln in range(start, start + count)] if count else [(start, True)])
    return points


def definition_at(defs: list[dict], line: int) -> dict | None:
    """The top-level function or class whose span holds ``line``. A pure
    insertion after line L is placed by L alone, so nowhere when L is between
    definitions: placing it on the one holding L + 1 charged a new function
    inserted above a definition to that definition, and read 2,816 where the
    authoring rule reads 2,784 at 17d83e0 (#433)."""
    for d in defs:
        if d["kind"] != NAME and d["start"] <= line <= d["end"]:
            return d
    return None


def lane_read_of(root: Path, mb: str, head: str, module: str) -> dict:
    """One lane's read of one module: the top-level definitions its hunks fall
    in at the merge-base, and their lengths summed there. A module the
    merge-base does not hold (the lane adds it) has no definition a hunk falls
    in there: none, of no length. A read git fails is ``Unread`` (``source_at``)."""
    text = source_at(root, mb, module)
    if text is None:
        return {"definitions": [], "lines": 0, "by_definition": {}}
    defs = definitions(ast.parse(text))
    rc, diff, err = git(root, "diff", "-U0", mb, head, "--", module)
    if rc != 0:
        raise Unread(f"git diff -U0 {mb[:12]} {head[:12]} -- {module} failed: {err.strip()}")
    hit: dict[str, int] = {}
    for ln, _insertion in hunk_points(diff):
        d = definition_at(defs, ln)
        if d is not None:
            hit[d["name"]] = d["lines"]
    return {"definitions": sorted(hit), "lines": sum(hit.values()), "by_definition": hit}


def section_lane_read(ctx: dict) -> dict:
    """The secondary, a LENGTH: per CLI-module lane merged in the window, the
    summed lengths at its merge-base of the top-level definitions its hunks
    fall in. A decomposition lowers it by construction, so it is graded only
    beside the primary (``wave_payoff``)."""
    root, modules = ctx["root"], ctx["modules"]
    rows, share = [], {}
    for pr in _window_prs(ctx):
        touched = _touches_cli(pr["files"], modules)
        if not touched:
            continue
        per = {m: lane_read_of(root, pr["merge_base"], pr["head"], m) for m in touched}
        total = sum(p["lines"] for p in per.values())
        for p in per.values():
            for name, n in p["by_definition"].items():
                share[name] = share.get(name, 0) + n
        rows.append({"pr": pr["number"], "lines": total,
                     "definitions": sorted(d for p in per.values() for d in p["definitions"])})
    values = [r["lines"] for r in rows]
    summed = sum(share.values())
    top = sorted(share.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    return {"lanes": len(rows), "median": statistics.median(values) if values else None,
            "max": max(values) if values else None, "summed": summed,
            "top_share": [{"name": n, "lines": v, "share": round(v / summed, 3)} for n, v in top] if summed else [],
            "rows": sorted(rows, key=lambda r: r["pr"])}


# ---------------------------------------------------------------- transcripts (the primary)

#: The committed rule for Item 3 (step 1, 6a91bc51b): real when all three hold.
R_FLOOR_LINES = 1500
R_OVER_E = 2.0
ALPHA = 0.05
#: Not real only where the read could have seen the effect: the realised
#: minimum detectable ratio at most this, with at least this many lanes an arm.
MDR_CEILING = 2.0
MIN_ARM = 8
#: The one-sided alpha 0.05, power 0.8 constant: z(0.95) + z(0.8).
MDD_Z = 2.49
#: A control lane's edited non-test .py files each stay under this at its merge-base.
CONTROL_MAX_LINES = 3000
#: The seats whose transcripts are on this box (2 of 4; the Windows seats' are on theirs).
BOX_SEATS = ("air", "air-work")
READ_PROGRAMS = {"sed", "cat", "head", "tail", "nl", "awk"}
SEARCH_PROGRAMS = {"grep", "rg", "ugrep", "egrep", "fgrep"}
#: Record types that repeat a request's content (the blob records): skipped, never counted twice.
SKIP_RECORDS = {"api-request-blob", "api-request", "api-request-shape"}
#: The old per-line read of a here-document's operator and tag (``<<EOF``,
#: ``<<-'EOF'``, never a here-string's ``<<<``): ``_heredoc_tags`` reads the
#: operator in its context and the delimiter as a shell word, and this regex is
#: kept only to name the commands where the two disagree
#: (``heredoc_tag_misses``).
_HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
_SAVED = re.compile(r"(?:Full output|Output) saved to:?\s*(\S+/tool-results/\S+)")


def project_folder(path: str) -> str:
    """Claude Code's project folder name for a checkout path."""
    return re.sub(r"[^A-Za-z0-9]", "-", path.replace("\\", "/"))


def _own_name(path: Path, main: bool) -> bool | None:
    """Whether a checkout's ``espalier.machine`` is its own: the main
    checkout's always is (the clone's name is its name), and a linked
    worktree's is only where git reads it from the worktree's own config
    (``--show-scope`` says ``worktree``). A linked worktree that answers the
    clone's name through the shared config (a fork's worktree no session was
    ever started in) is ``False``; a scope git would not tell is ``None``."""
    if main:
        return True
    rc, out, _err = git(path, "config", "--show-scope", "--get", "espalier.machine")
    if rc != 0 or "\t" not in out:
        return None
    return out.split("\t", 1)[0].strip() == "worktree"


def checkouts(root: Path) -> list[dict]:
    """Each checkout of this clone (``git worktree list --porcelain -z``), its
    seat name (``espalier.machine``, the per-worktree one first), whether that
    name is its own (``own_name``, from ``_own_name``; the main checkout is
    the porcelain's first entry), its project folder, and ``gone`` where its
    directory is not there (so no seat can be read for it). ``seat_error``
    names a ``git config`` that failed (an exit other than 0, or 1 for a key
    that is not set: a config file git cannot parse), so that checkout's seat
    reads unread, never "no espalier.machine". A ``git worktree list`` that
    fails is ``Unread``, never a clone of no checkouts."""
    rc, out, err = git(root, "worktree", "list", "--porcelain", "-z")
    if rc != 0:
        raise Unread(f"git worktree list failed: {err.strip()[:200]}")
    paths = [line[len("worktree "):].replace("\\", "/") for line in out.split("\0") if line.startswith("worktree ")]
    rows = []
    for idx, p in enumerate(paths):
        gone = not Path(p).is_dir()
        rc, name, err = (1, "", "") if gone else git(Path(p), "config", "--get", "espalier.machine")
        seat = name.strip() or None if rc == 0 else None
        own = None if gone or seat is None else _own_name(Path(p), main=idx == 0)
        rows.append({"path": p, "seat": seat, "own_name": own, "folder": project_folder(p), "gone": gone,
                     "seat_error": None if rc in (0, 1) else f"git config failed (exit {rc}): {err.strip()[:200]}"})
    return rows


#: The characters a word starts after: a ``#`` there opens a comment.
_WORD_BREAKS = frozenset(" \t\n;&|()<>")
#: The characters that end a here-document's delimiter word, unquoted: a blank or an operator's.
_DELIMITER_ENDS = frozenset(" \t;&|()<>")
#: The contexts a newline ends a command line in, so a here-document's body can start after it.
_COMMAND_KINDS = ("cmd", "sub", "`")
#: The contexts a ``${`` parameter expansion opens inside itself: its quotes and substitutions.
_PARAM_OPENS = (("$((", "arith"), ("$(", "sub"), ("${", "param"), ("'", "'"), ('"', '"'))


def _heredoc_word(line: str, i: int) -> tuple[str, bool, int] | None:
    """The here-document the ``<<`` at ``line[i]`` opens: ``(tag, dash, end)``,
    or ``None`` where no word follows it. After ``<<`` or ``<<-`` and any
    blanks the delimiter is a shell word, everything up to the next unquoted
    blank or operator character; the tag is that word with its quotes and
    backslashes taken out, so ``<<\\EOF``, ``<<'END X'``, ``<<E'OF'``,
    ``<<END-X``, ``<<1X`` and ``let x<<=2``'s ``=2`` each delimit a body, as
    both shells read them. ``dash`` marks ``<<-``, whose delimiter line may
    carry leading tabs."""
    n = len(line)
    j = i + 2
    dash = line.startswith("-", j)
    j += dash
    while j < n and line[j] in " \t":
        j += 1
    start, word, quote = j, [], ""
    while j < n:
        ch = line[j]
        if quote == '"' and ch == "\\" and line[j + 1:j + 2] in ('"', "\\", "$", "`"):
            word.append(line[j + 1])
            j += 2
        elif quote:
            quote = "" if ch == quote else quote
            word.append(ch if quote else "")
            j += 1
        elif ch in "'\"":
            quote = ch
            j += 1
        elif ch == "\\":
            word.append(line[j + 1:j + 2])
            j += 2
        elif ch in _DELIMITER_ENDS:
            break
        else:
            word.append(ch)
            j += 1
    if j == start:
        return None
    return "".join(word), dash, min(j, n)


def _heredoc_tags(line: str, stack: list[list]) -> list[tuple[str, bool, int]]:
    """The here-documents one line of a command opens, each ``(tag, dash,
    depth)`` (``_heredoc_word``; ``depth`` the stack's height at its ``<<``),
    read where the shell reads ``<<`` as a redirection: in a command's own
    context (the command line, a subshell, a ``$(`` there or inside double
    quotes, or a backquote inside double quotes), and never inside quotes,
    inside ``$((...))``, ``((...))`` or ``$[...]`` (a shift there), inside a
    ``${...}`` parameter expansion, or in a comment (a ``#`` that starts a
    word in that context). ``stack`` holds the contexts open at the line's
    start and is left holding those open at its end, so a quote or a
    substitution carries to the next line as the shell's does. Each entry is
    ``[kind, depth]``: ``cmd`` (the base, never popped), ``sub`` (a ``$(``),
    ``'``, ``"``, ``$'``, ``arith``, ``brack`` (a ``$[``), ``param`` (a
    ``${``), a backquote, or ``cont``: a backslash-newline that ends the line,
    carrying whether the next line starts at a word start (it starts mid-word
    unless a blank came before the backslash). The depth counts the
    parentheses (a ``${``'s braces) open inside it. Limits, named: a ``case``
    pattern's ``)`` inside a ``$(`` is read as closing it, and a backquote is
    a context only inside double quotes (on the command line it is read as a
    plain character)."""
    tags: list[tuple[str, bool, int]] = []
    i, n, brk = 0, len(line), True
    if stack[-1][0] == "cont":
        brk = stack.pop()[1]
    while i < n:
        top = stack[-1]
        kind, ch = top[0], line[i]
        if kind in ('"', "$'") and ch == "\\":
            i, brk = i + 2, False
        elif kind in ("'", "$'"):
            if ch == "'":
                stack.pop()
            i, brk = i + 1, False
        elif kind == "arith":
            if ch == "(":
                top[1] += 1
            elif ch == ")" and top[1]:
                top[1] -= 1
            elif ch == ")":
                stack.pop()
                i += 1 if line[i + 1:i + 2] == ")" else 0
            i, brk = i + 1, False
        elif kind == '"':
            if ch == '"':
                stack.pop()
                i += 1
            elif line.startswith("$((", i):
                stack.append(["arith", 0])
                i += 3
            elif line.startswith("$(", i):
                stack.append(["sub", 0])
                i += 2
            elif ch == "`":
                stack.append(["`", 0])
                i += 1
            else:
                i += 1
            brk = False
        elif kind == "brack":
            if ch == "[":
                top[1] += 1
            elif ch == "]" and top[1]:
                top[1] -= 1
            elif ch == "]":
                stack.pop()
            i, brk = i + 1, False
        elif kind == "param":
            opened = next(((c, k) for c, k in _PARAM_OPENS if line.startswith(c, i)), None)
            if ch == "\\":
                i += 2
            elif ch == "}" and not top[1]:
                stack.pop()
                i += 1
            elif opened:
                stack.append([opened[1], 0])
                i += len(opened[0])
            else:
                top[1] += 1 if ch == "{" else -1 if ch == "}" else 0
                i += 1
            brk = False
        elif ch == "\\":                              # cmd, sub or a backquote from here on
            if i + 1 == n:
                stack.append(["cont", brk])
            i, brk = i + 2, False
        elif ch == "`" and kind == "`":
            stack.pop()
            i, brk = i + 1, False
        elif ch == "#" and brk:
            close = line.find("`", i) if kind == "`" else -1
            if close < 0:
                break
            i = close
        elif line.startswith("<<<", i):
            i, brk = i + 3, False
        elif line.startswith("<<", i):
            m = _heredoc_word(line, i)
            if m:
                tags.append((m[0], m[1], len(stack)))
            i, brk = (m[2], False) if m else (i + 2, True)
        elif line.startswith("$((", i) or (brk and line.startswith("((", i)):
            stack.append(["arith", 0])
            i, brk = i + (3 if ch == "$" else 2), False
        elif line.startswith("${", i) or line.startswith("$[", i):
            stack.append(["param" if line[i + 1] == "{" else "brack", 0])
            i, brk = i + 2, False
        elif line.startswith("$(", i) or line.startswith("$'", i):
            stack.append(["sub" if line[i + 1] == "(" else "$'", 0])
            i, brk = i + 2, line[i + 1] == "("
        elif ch in "'\"":
            stack.append([ch, 0])
            i, brk = i + 1, False
        elif ch == ")" and not top[1] and kind == "sub":
            stack.pop()
            i, brk = i + 1, False
        else:
            top[1] += 1 if ch == "(" else -1 if ch == ")" and top[1] else 0
            i, brk = i + 1, ch in _WORD_BREAKS
    return tags


def _heredoc_scan(command: str) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """``(kept, read)``: the command's lines with every here-document's body
    taken out, and each line read for operators (by its index) with the tags
    ``_heredoc_tags`` found on it. A body starts after the newline that ends
    its operator's line in the operator's own context: not while a quote, an
    expansion or a backslash-newline opened after the operator is still open
    there (the shells read the body after the logical line), and a
    here-document inside a ``$(`` starts at that substitution's own newline.
    A ``<<`` body ends at the first line equal to its tag, a ``<<-`` body at
    the first equal to it once leading tabs are taken off; a body's own lines
    are never read for operators."""
    out, lines, i = [], command.split("\n"), 0
    stack: list[list] = [["cmd", 0]]
    pending: list[tuple[str, bool, int]] = []
    read: list[tuple[int, list[str]]] = []
    while i < len(lines):
        line = lines[i]
        out.append(line)
        tags = _heredoc_tags(line, stack)
        read.append((i, [t for t, _dash, _depth in tags]))
        pending += tags
        i += 1
        if not pending or stack[-1][0] not in _COMMAND_KINDS:
            continue
        here = len(stack)
        for tag, dash, _depth in [p for p in pending if p[2] >= here]:
            while i < len(lines) and (lines[i].lstrip("\t") if dash else lines[i]) != tag:
                i += 1
            i += 1
        pending = [p for p in pending if p[2] < here]
    return out, read


def strip_heredocs(command: str) -> str:
    """The command with every here-document's body taken out: a path inside
    one is the text of a message or a script, never a read. Only a ``<<`` the
    shell reads as a redirection opens one (``_heredoc_tags``, its contexts
    carried across the command's lines); its body starts and ends where the
    shells' does (``_heredoc_scan``)."""
    return "\n".join(_heredoc_scan(command)[0])


def heredoc_tag_misses(command: str) -> list[str]:
    """The tags the old per-line regex (``_HEREDOC``) finds on a line the
    scanner reads where ``_heredoc_tags`` finds no tag of that name, and that a
    later line of the command equals once stripped: a here-document the
    scanner may have missed (the ``case``-``)`` inside a ``$(`` limit among
    them), so its body was read as commands. A candidate, never a verdict:
    the count names how often to look."""
    lines = command.split("\n")
    missed = []
    for idx, tags in _heredoc_scan(command)[1]:
        for m in _HEREDOC.finditer(lines[idx]):
            if m.group(2) not in tags and any(later.strip() == m.group(2) for later in lines[idx + 1:]):
                missed.append(m.group(2))
    return missed


def shell_text(command: str) -> str:
    """The command as the shell reads it before it splits words: each
    here-document's body out (``strip_heredocs``); each backslash-newline
    continuation joined, as the shell joins it outside single quotes; and each
    comment cut, a ``#`` that starts a word outside quotes, which ends at its
    own line's end and never takes a later line (``${#x}`` and ``a#b`` are no
    comment). Quotes open on one line carry to the next, as the shell's do. An
    ANSI-C quote (``$'it\\'s'``, where a backslash escapes the quote) is handed
    on as the single-quoted word it is (``'it'"'"'s'``), which the lexer reads
    whole; its other escapes are kept as written."""
    text = strip_heredocs(command)
    out: list[str] = []
    quote, i, n, at_break = "", 0, len(text), True
    while i < n:
        ch = text[i]
        if quote == "'":
            quote = "" if ch == "'" else quote
            out.append(ch)
            i += 1
        elif quote == "$'":
            nxt = text[i + 1:i + 2] if ch == "\\" else ""
            if ch == "'":
                quote = ""
            out.append("'\"'\"'" if nxt == "'" else nxt if nxt == "\\" else text[i:i + 2] if nxt else ch)
            i += 2 if nxt else 1
        elif quote == "" and text.startswith("$'", i):
            quote = "$'"
            out.append("'")
            i += 2
            at_break = False
        elif ch == "\\":
            if text[i + 1:i + 2] == "\n":
                i += 2              # a continuation: the shell takes both out
                continue
            out.append(text[i:i + 2])
            i += 2
            at_break = False
        elif quote == '"':
            quote = "" if ch == '"' else quote
            out.append(ch)
            i += 1
        elif ch in "'\"":
            quote = ch
            out.append(ch)
            i += 1
            at_break = False
        elif ch == "#" and at_break:
            end = text.find("\n", i)
            i = n if end < 0 else end
        else:
            out.append(ch)
            i += 1
            at_break = ch in _WORD_BREAKS
    return "".join(out)


def simple_commands(command: str) -> list[tuple[list[str], bool]]:
    """``(argv, piped)`` for each simple command of a shell line, read as the
    shell reads it (``shell_text``: heredoc bodies out, continuations joined,
    comments cut line by line): split on ``;``, ``&&``, ``||``, ``|``, ``&``
    and newlines. ``piped`` marks one whose output goes into, or comes from, a
    pipe. The lexer keeps no comment character of its own, so a ``#`` it is
    handed is a word's. A command the lexer refuses (an unbalanced quote) is
    ``[]`` here; ``lexed_commands`` tells it apart, and ``calls_of`` counts it."""
    return lexed_commands(command) or []


def lexed_commands(command: str) -> list[tuple[list[str], bool]] | None:
    """``simple_commands``, or ``None`` where the lexer refuses the command."""
    text = shell_text(command).replace("\n", " ; ")
    lex = shlex.shlex(text, posix=True, punctuation_chars=";&|()")
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        tokens = list(lex)
    except ValueError:
        return None
    out, cur, seps = [], [], []
    for tok in [*tokens, ";"]:
        if tok and set(tok) <= set(";&|()"):
            if cur:
                out.append(cur)
                seps.append(tok)
            elif out:
                seps[-1] = seps[-1] if "|" in seps[-1] else tok
            cur = []
        else:
            cur.append(tok)
    piped = []
    for i, _argv in enumerate(out):
        before = seps[i - 1] if i else ""
        piped.append(before == "|" or seps[i] == "|")
    return list(zip(out, piped))


def _range(program: str, args: list[str]) -> int | None:
    """The lines a read program's own options select, or ``None`` for a
    whole file (or a range it cannot tell). ``head``'s and ``tail``'s long
    form (``--lines N``, ``--lines=N``) is read as ``-n N`` is."""
    args = [w for a in args for w in (["-n", a[len("--lines="):]] if a.startswith("--lines=") else
                                      ["-n"] if a == "--lines" else [a])]
    if program == "sed":
        total, saw = 0, False
        for a in args:
            m = re.fullmatch(r"(\d+)(?:,(\d+))?p", a)
            if m:
                saw = True
                total += (int(m.group(2)) - int(m.group(1)) + 1) if m.group(2) else 1
        return total if saw else None
    if program in ("head", "tail"):
        if any(a == "-c" or a.startswith(("-c", "--bytes")) for a in args):
            return None                 # a count of bytes selects no lines
        for i, a in enumerate(args):
            if a == "-n" and i + 1 < len(args) and args[i + 1].lstrip("-").isdigit():
                return int(args[i + 1].lstrip("-"))
            m = re.fullmatch(r"-n?(\d+)", a)
            if m:
                return int(m.group(1))
            if a == "-n" or a.startswith("+") or a.startswith("-n+"):
                return None
        return 10
    return None


#: git's global options that take their value as the next word (``-C dir``,
#: ``-c k=v``, ``--git-dir dir``); every other leading option is one word
#: (``--no-pager``, ``-P``, ``--git-dir=dir``, ``--bare``).
_GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
                                "--config-env"})


def read_operands(argv: list[str]) -> tuple[str, list[str], int | None] | None:
    """``(kind, files, range)`` for a read or a search, else ``None``.
    ``kind`` is ``read`` (the allowlist: ``sed`` without ``-i``, ``cat``,
    ``head``, ``tail``, ``nl``, ``awk``, ``git show <rev>:<path>`` after any
    of git's global options) or ``search``; the files are the whole operands
    the program reads, and a file fed on its stdin (``prog < file``) only
    where the program reads its stdin: with no file operand, or a ``-`` among
    them (``cat a < b`` reads ``a`` alone). A redirection's target is
    written, never read; a here-document's tag and a here-string's word name
    no file; the count ``-n``/``-c`` takes on ``head`` and ``tail`` is no file
    either."""
    while argv and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argv[0]):
        argv = argv[1:]
    if not argv:
        return None
    prog, args = Path(argv[0]).name, argv[1:]
    if prog == "git":
        while args and args[0].startswith("-"):
            args = args[2:] if args[0] in _GIT_VALUE_OPTIONS else args[1:]
        if args[:1] == ["show"]:
            files = [a.split(":", 1)[1] for a in args[1:] if ":" in a and not a.startswith("-") and a.split(":", 1)[1]]
            return ("read", files, None) if files else None
        if args[:1] == ["grep"]:
            return "search", [a for a in args[1:] if not a.startswith("-")][1:], None
        return None
    if prog in SEARCH_PROGRAMS:
        rest = [a for a in args if not a.startswith("-")]
        return "search", rest[1:], None
    if prog not in READ_PROGRAMS:
        return None
    if prog == "sed" and any(a.startswith("-i") or a == "--in-place" for a in args):
        return None
    files: list[str] = []
    fed: list[str] = []
    skip_next, feed_next, script_given, dash = False, False, False, False
    for a in args:
        if skip_next or feed_next:
            if feed_next:
                fed.append(a)
            skip_next = feed_next = False
            continue
        if re.fullmatch(r"\d*<<-?|<<<", a):
            skip_next = True          # a here-document's tag or a here-string's word: no file
            continue
        if a.startswith("<<"):
            continue
        if re.fullmatch(r"\d*<", a):
            feed_next = True          # the file on stdin is read
            continue
        fed_in = re.fullmatch(r"\d*<([^<>&].*)", a)
        if fed_in:
            fed.append(fed_in.group(1))
            continue
        if re.fullmatch(r"\d*>>?|&>>?|\d*<>", a):
            skip_next = True          # a redirection's target is written, never a read operand
            continue
        if re.fullmatch(r"\d*>>?\S+|&>\S+|\d*<&\S*", a):
            continue
        if a in ("-e", "-f") and prog in ("sed", "awk"):
            skip_next, script_given = True, True
            continue
        if a in ("-n", "-c", "--lines", "--bytes") and prog in ("head", "tail"):
            skip_next = True
            continue
        if a == "-":
            dash = True               # the program's stdin, among its operands
            continue
        if a.startswith("-") or a.startswith("+"):
            continue
        files.append(a)
    if prog in ("sed", "awk") and not script_given and files:
        files = files[1:]
    rng = _range(prog, args)
    return "read", files + (fed if dash or not files else []), rng


_WORKTREE_PREFIX = re.compile(r"^\.claude/worktrees/[^/]+/")
_SCRATCH_COPY = re.compile(r"/scratchpad/[^/]+/")
_DRIVE = re.compile(r"[A-Za-z]:/")


def _joined(path: str, cwd: str) -> str:
    """``path`` against ``cwd``, normalised, with ``\\`` read as ``/``."""
    p, c = path.replace("\\", "/"), (cwd or "").replace("\\", "/")
    return posixpath.normpath(p if p.startswith("/") or _DRIVE.match(p) else posixpath.join(c, p))


def _relative(path: str, cwd: str, roots: list[str], known=None) -> str | None:
    """The repository path ``path`` names, or ``None``. A worktree under a
    checkout that is gone by the read (a fork's ``.claude/worktrees/agent-*``)
    is no root any more, so its files map onto the checkout around it with the
    worktree's prefix: that prefix is taken off. A path in a tree copy under a
    session scratchpad (``.../scratchpad/<copy>/espalier/cli.py``) maps where
    ``known(rest)`` says the rest is a file at the pin. Paths, the cwd and the
    roots are compared with ``\\`` read as ``/`` (a Windows seat's)."""
    full = _joined(path, cwd)
    for r in sorted((root.replace("\\", "/") for root in roots), key=len, reverse=True):
        if full == r or full.startswith(r.rstrip("/") + "/"):
            return _WORKTREE_PREFIX.sub("", full[len(r.rstrip("/")) + 1:])
    if known is not None:
        m = _SCRATCH_COPY.search(full)
        if m and known(full[m.end():]):
            return full[m.end():]
    return None


def _program(argv: list[str]) -> str:
    """A simple command's program name, past any leading ``VAR=value``."""
    while argv and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argv[0]):
        argv = argv[1:]
    return Path(argv[0]).name if argv else ""


def _git_dir(argv: list[str], cwd: str) -> str:
    """The directory a ``git`` command runs in: its ``-C`` options joined in
    order onto ``cwd``, as git applies them, else ``cwd``."""
    while argv and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argv[0]):
        argv = argv[1:]
    where, args = cwd, argv[1:]
    while args and args[0].startswith("-"):
        if args[0] == "-C" and len(args) > 1:
            where = _joined(args[1], where)
        args = args[2:] if args[0] in _GIT_VALUE_OPTIONS else args[1:]
    return where


def _repository_root(directory: str, roots: list[str]) -> str:
    """The root of the repository a command run in ``directory`` reads: the
    checkout root holding it (the longest; a fork's worktree under
    ``.claude/worktrees/`` is its own root, as is a tree copy under a session
    scratchpad), else ``directory`` itself."""
    d = directory.replace("\\", "/").rstrip("/")
    for r in sorted((root.replace("\\", "/").rstrip("/") for root in roots), key=len, reverse=True):
        if d == r or d.startswith(r + "/"):
            m = _WORKTREE_PREFIX.match(d[len(r) + 1:] + "/") if d != r else None
            return f"{r}/{m.group(0)}".rstrip("/") if m else r
    m = _SCRATCH_COPY.search(d + "/")
    return d[:m.end() - 1] if m else d


def _show_anchor(path: str, argv: list[str], cwd: str, roots: list[str]) -> str:
    """The directory ``git show REV:path`` reads ``path`` from: the root of the
    repository the command runs in (``_git_dir``, ``_repository_root``), or
    that directory itself where ``path`` starts ``./`` or ``../``."""
    where = _git_dir(argv, cwd)
    return where if path.startswith(("./", "../")) else _repository_root(where, roots)


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def _line_count(text: str) -> int:
    return len(text.splitlines())


def calls_of(records: list[dict], roots: list[str], until: str, length, misses: dict | None = None,
             modules=()) -> list[dict]:
    """One session's file reads and searches, by the ruled rules: each
    ``tool_use`` once (deduped by id), the blob records skipped, cut at the
    pin's date by each record's own stamp. Each call carries its stamp, its
    branch, and ``reads``: ``[(repo path, lines)]``. ``length(path)`` is a
    file's length at the pin (a piped or multi-file whole read's range). A
    ``Read`` counts its result's ``numLines``, 0 included (a read past the end
    returns a warning, no line of the file); a refused one (its result
    ``is_error``, or a ``toolUseResult`` that is no dict: the over-the-token-
    limit refusal is the string ``Error: File content ... exceeds maximum
    allowed tokens``) counts 0, never its error text's lines; only a result
    with no ``numLines`` otherwise counts its text's lines. ``git show
    REV:path`` reads ``path`` from the root of the repository it runs in
    (``_show_anchor``), never the shell's cwd. ``misses``, where given, counts
    the Bash commands the lexer refuses (``unlexed``, which book nothing) and
    those ``heredoc_tag_misses`` flags (``heredoc_tag_missed``), each with how
    many hold a path of ``modules`` (``*_naming_cli``).

    Limits, named and not corrected: a saved output (``Output saved to``) that
    holds several files' reads credits each file the saved file's whole
    length when it is read back (probable); and a ``tool_use`` is de-duplicated
    within one session file, so one repeated across a resumed session's files
    would count once in each (unverified)."""
    uses: dict[str, dict] = {}
    results: dict[str, dict] = {}
    for r in records:
        if r.get("type") in SKIP_RECORDS or str(r.get("timestamp") or "")[:19] > until[:19]:
            continue
        content = (r.get("message") or {}).get("content") or []
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if r.get("type") == "assistant" and c.get("type") == "tool_use" and c.get("id") not in uses:
                uses[c["id"]] = {"id": c["id"], "name": c.get("name"), "input": c.get("input") or {},
                                 "at": str(r.get("timestamp") or ""), "branch": r.get("gitBranch") or "",
                                 "cwd": r.get("cwd") or ""}
            elif r.get("type") == "user" and c.get("type") == "tool_result":
                results.setdefault(c.get("tool_use_id"), {"text": _result_text(c.get("content")),
                                                           "meta": r.get("toolUseResult"),
                                                           "error": bool(c.get("is_error"))})
    saved: dict[str, list[str]] = {}   # a saved output's path -> the files whose read it holds
    calls = []
    for u in sorted(uses.values(), key=lambda u: (u["at"], u["id"])):
        res = results.get(u["id"]) or {"text": "", "meta": None, "error": False}
        meta = res["meta"] if isinstance(res["meta"], dict) else {}
        call = {"id": u["id"], "at": u["at"], "branch": u["branch"], "reads": [], "searches": []}
        if u["name"] == "Read":
            fp = str(u["input"].get("file_path") or "")
            num = (meta.get("file") or {}).get("numLines")
            refused = res["error"] or (u["id"] in results and not isinstance(res["meta"], dict))
            n = 0 if refused else int(num) if num is not None else _line_count(res["text"])
            if "/tool-results/" in fp:
                call["reads"] = [(src, n) for src in saved.get(fp, [])]
            else:
                rel = _relative(fp, u["cwd"], roots, length)
                if rel:
                    call["reads"] = [(rel, n)]
        elif u["name"] == "Grep":
            rel = _relative(str(u["input"].get("path") or ""), u["cwd"], roots, length)
            if rel:
                call["searches"] = [(rel, _line_count(res["text"]))]
        elif u["name"] == "Bash":
            out = str(meta.get("stdout") if meta.get("stdout") is not None else res["text"])
            hit = _SAVED.search(out)
            command = str(u["input"].get("command") or "")
            parts = lexed_commands(command)
            if misses is not None:
                naming = any(m in command for m in modules)
                for key, missed in (("unlexed", parts is None), ("heredoc_tag_missed", bool(heredoc_tag_misses(command)))):
                    misses[key] = misses.get(key, 0) + missed
                    misses[f"{key}_naming_cli"] = misses.get(f"{key}_naming_cli", 0) + (missed and naming)
            parts = parts or []
            cwd = u["cwd"]
            reads, searches = [], []
            for argv, piped in parts:
                if argv[:1] == ["cd"] and len(argv) > 1:
                    cwd = _joined(argv[1], cwd)
                    continue
                got = read_operands(argv)
                if got is None:
                    continue
                kind, files, rng = got
                show = kind == "read" and _program(argv) == "git"
                rels = [r for r in (_relative(f, _show_anchor(f, argv, cwd, roots) if show else cwd, roots, length)
                                    for f in files) if r]
                if kind == "search":
                    searches += [(r, 0) for r in rels]
                    continue
                for r in rels:
                    reads.append((r, rng, piped or len(files) > 1))
            lone = len(reads) == 1 and len([p for p in parts if read_operands(p[0])]) == 1 and not reads[0][2]
            stdout_lines = _line_count(out)
            if hit:
                saved[hit.group(1)] = [r for r, _rng, _p in reads]
            if lone:
                call["reads"] = [(reads[0][0], stdout_lines if not hit else _line_count(out.split("Preview", 1)[-1]))]
            elif reads:
                wanted = [(r, rng if rng is not None else (length(r) or stdout_lines)) for r, rng, _p in reads]
                total = sum(n for _r, n in wanted)
                scale = min(1.0, stdout_lines / total) if total else 0.0
                call["reads"] = [(r, round(n * scale)) for r, n in wanted]
            call["searches"] = [(r, stdout_lines) for r, _z in searches]
        if call["reads"] or call["searches"]:
            calls.append(call)
    return calls


def mann_whitney_greater(xs: list[float], ys: list[float]) -> float | None:
    """One-sided p that ``xs`` sit above ``ys`` (normal approximation with the
    tie correction and a continuity correction); ``None`` on an empty arm."""
    n1, n2 = len(xs), len(ys)
    if not n1 or not n2:
        return None
    pooled = sorted([(v, 0) for v in xs] + [(v, 1) for v in ys])
    ranks, i, ties = [0.0] * len(pooled), 0, 0.0
    while i < len(pooled):
        j = i
        while j + 1 < len(pooled) and pooled[j + 1][0] == pooled[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2 + 1
        t = j - i + 1
        ties += t ** 3 - t
        i = j + 1
    u = sum(r for r, (_v, arm) in zip(ranks, pooled) if arm == 0) - n1 * (n1 + 1) / 2
    n = n1 + n2
    var = n1 * n2 / 12 * ((n + 1) - ties / (n * (n - 1))) if n > 1 else 0
    if var <= 0:
        return None
    z = (u - n1 * n2 / 2 - 0.5) / var ** 0.5
    return 1 - statistics.NormalDist().cdf(z)


def item3_verdict(r: list[int], e: list[int]) -> dict:
    """Task 0 Item 3 on the committed rule: real when (a) median R is at least
    ``R_FLOOR_LINES``, (b) at least ``R_OVER_E`` times median E, and (c) the
    one-sided Mann-Whitney p is under ``ALPHA``; not real only when one fails
    and the read could have seen the effect (realised minimum detectable
    ratio at most ``MDR_CEILING``, each arm at least ``MIN_ARM``); else
    unmeasured. Two arms that read zero lines every lane are a read that saw
    nothing at all (no folder, no record placed), never an effect measured
    absent: unmeasured."""
    nt, nc = len(r), len(e)
    if nt < 2 or nc < 2:
        return {"verdict": "unmeasured", "why": f"arms of {nt} and {nc} lanes", "n_t": nt, "n_c": nc}
    if not any(r) and not any(e):
        return {"verdict": "unmeasured", "why": "both arms read zero lines in every lane", "n_t": nt, "n_c": nc}
    lt, lc = [math.log1p(v) for v in r], [math.log1p(v) for v in e]
    s = (((nt - 1) * statistics.variance(lt) + (nc - 1) * statistics.variance(lc)) / (nt + nc - 2)) ** 0.5
    mdr = math.exp(MDD_Z * s * (1 / nt + 1 / nc) ** 0.5)
    med_r, med_e = statistics.median(r), statistics.median(e)
    p = mann_whitney_greater([float(v) for v in r], [float(v) for v in e])
    a, b, c = med_r >= R_FLOOR_LINES, med_r >= R_OVER_E * med_e, p is not None and p < ALPHA
    if a and b and c:
        verdict = "real"
    elif mdr <= MDR_CEILING and nt >= MIN_ARM and nc >= MIN_ARM:
        verdict = "not real"
    else:
        verdict = "unmeasured"
    return {"verdict": verdict, "n_t": nt, "n_c": nc, "median_r": med_r, "median_e": med_e,
            "p_one_sided": None if p is None else round(p, 4), "a": a, "b": b, "c": c,
            "pooled_sd_ln": round(s, 3), "realised_mdr": round(mdr, 2)}


_STAMP_KEY = '"timestamp":'
_STAMP_VALUE = re.compile(r'\s*"([^"]{19})')


def _records(path: Path, until: str | None = None) -> tuple[int, list[dict]]:
    """``(record count, the records a call can be read from)`` of one
    transcript, streamed: a line holding neither a ``tool_use`` nor a
    ``tool_result`` is counted and never parsed (the folders run to gigabytes
    on an 8 GB box). With ``until``, the count is of the records stamped at
    or before it, so a live session appending after the pin leaves a re-run's
    count where it was (an unstamped line is not counted)."""
    count, keep = 0, []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if until is None:
                count += 1
            else:
                at = line.find(_STAMP_KEY)
                stamp = _STAMP_VALUE.match(line, at + len(_STAMP_KEY)) if at >= 0 else None
                if stamp and stamp.group(1) <= until[:19]:
                    count += 1
            if '"tool_use"' not in line and '"tool_result"' not in line:
                continue
            try:
                keep.append(json.loads(line))
            except ValueError:
                continue
    return count, keep


def lane_of(seat: str, branch: str, when: str, *, seats: dict[str, str],
            windows: dict[str, list[tuple[str, str, str]]], merged: dict[str, str]) -> str:
    """The lane a call at ``when`` on ``branch`` of ``seat`` belongs to: the
    record's own branch where it names a lane of the seat; a branch naming any
    other lane is no unit (never re-placed by the clock); the default branch
    (or none) falls back to the seat's claim windows, and so does a lane's
    branch the checkout still names after that lane merged, where the seat
    then holds exactly one other lane's claim (the work went on in another
    clone or worktree: #530, built in a scratchpad clone while the checkout
    sat on #527's merged branch)."""
    held = {lane for s, e, lane in windows.get(seat, []) if s <= when <= e}
    if branch in merged and seats.get(branch) == seat:
        others = held - {branch}
        if when[:19] > merged[branch][:19] and len(others) == 1:
            return others.pop()
        return branch
    if branch and branch not in ("main", "master", "HEAD"):
        return "other branch"
    return held.pop() if len(held) == 1 else ("ambiguous" if held else "unattributed")


def section_transcripts(ctx: dict) -> dict:
    """Task 0 Item 3's oracle: the lines of the CLI modules the seats' own
    reads returned, per merged lane of the seats on this box, against the
    lines a control lane's reads returned on the files it edited. Every
    population figure is in the output: the folders (matched case-
    insensitively), each file's record count up to the pin, and the calls
    no lane took. Subagents are counted apart, through their parent's
    ``Agent`` call. Two of the four seats, said on the section. A clone with
    no checkout of a box seat, or a population that holds no record up to the
    pin, is ``Unread``: every lane would read zero. A checkout whose seat
    cannot be read (its directory gone, or no ``espalier.machine``) is named
    under ``checkouts_without_a_seat``, never dropped in silence. A linked
    worktree that answers a box seat only through the clone's shared config
    (``own_name`` False: a fork's worktree, which no session ran in) and has
    no transcript folder is named under ``skipped_never_named`` and read as
    holding none; any other box-seat checkout with no folder is a seat's
    transcripts gone, and ``Unread``. Only the lanes of the seats whose
    folders were read (``seats``) enter the arms: a box seat with no checkout
    read here (none of this clone names it, its checkout is gone, its name or
    its config cannot be read) is named under ``unread`` as
    ``transcripts.seats`` with the reason, never a lane of zero lines. A
    command the lexer refuses books no read: ``calls.unlexed`` counts them,
    own and subagent apart, with those that hold a CLI module's path, and
    ``transcripts.unlexed`` names them under ``unread``;
    ``calls.heredoc_tag_missed`` counts the commands ``heredoc_tag_misses``
    flags, the same way."""
    root, at = ctx["root"], ctx["pin"]["at"]
    until = ctx["pin"]["window"]["until"]
    base = Path(ctx.get("projects_dir") or Path.home() / ".claude" / "projects")
    if not base.is_dir():
        raise Unread(f"no transcript folder at {base}")
    outs = ctx.get("checkouts") or checkouts(root)
    by_lower = {p.name.lower(): p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")}
    seated = [(c, by_lower.get(c["folder"].lower())) for c in outs if c["seat"] in BOX_SEATS]
    skipped = [{"path": c["path"], "folder": c["folder"], "seat": c["seat"]} for c, f in seated
               if f is None and c.get("own_name") is False]
    folders = [(c, f) for c, f in seated if not (f is None and c.get("own_name") is False)]
    unseated = [{"path": c["path"], "folder": c["folder"], "why": "directory gone" if c.get("gone") else
                 c.get("seat_error") or "no espalier.machine"} for c in outs if c["seat"] is None]
    if not folders:
        raise Unread(f"no checkout of this clone is a box seat {list(BOX_SEATS)} "
                     f"({len(outs)} checkout(s), {len(unseated)} with no seat read, "
                     f"{len(skipped)} never named with no transcript folder)")
    missing = [c["folder"] for c, f in folders if f is None]
    if missing:
        raise Unread(f"transcript folder(s) missing: {missing}")
    read_seats = sorted({c["seat"] for c, _f in folders})
    not_read = {}
    for s in BOX_SEATS:
        if s in read_seats:
            continue
        only_skipped = [k["path"] for k in skipped if k["seat"] == s]
        not_read[s] = (f"its only checkout(s) here were never named and hold no transcript folder: {only_skipped}"
                       if only_skipped else "no checkout of this clone reads as it" + (
                           f"; {len(unseated)} checkout(s) whose seat could not be read: "
                           f"{[(u['path'], u['why']) for u in unseated][:5]}" if unseated else ""))
    if not_read:
        _partial(ctx, "transcripts", "seats", "box seat(s) whose transcripts were not read, so their lanes are left "
                                              "out of both arms: " + "; ".join(f"{s}: {w}" for s, w in not_read.items()))
    roots = [c["path"] for c in outs]
    by_machine = mail_at(ctx)
    _name_missing_mail_seats(ctx, "transcripts")
    seats = _mail().lane_seats(by_machine)
    claims = claim_intervals(by_machine, until)
    lanes = {pr["branch"]: pr for pr in _window_prs(ctx) if seats.get(pr["branch"]) in read_seats}
    windows: dict[str, list[tuple[str, str, str]]] = {}
    for c in claims:
        if c["lane"] in lanes and c["machine"] == seats.get(c["lane"]):
            windows.setdefault(c["machine"], []).append((c["start"], c["end"], c["lane"]))

    @functools.lru_cache(maxsize=None)
    def length(path: str) -> int:
        return len((source_at(root, at, path) or "").splitlines())

    merged = {lane: pr["date"] for lane, pr in lanes.items()}

    def place(seat: str, branch: str, when: str) -> str:
        return lane_of(seat, branch, when, seats=seats, windows=windows, merged=merged)

    population, own, subs = [], [], []
    modules = set(ctx["modules"])
    own_misses: dict[str, int] = {}
    sub_misses: dict[str, int] = {}
    for c, folder in folders:
        agent_calls: dict[str, tuple[str, str]] = {}
        files = sorted(folder.glob("*.jsonl"))
        counts = {}
        for f in files:
            counts[f.name], recs = _records(f, until)
            for call in calls_of(recs, roots, until, length, own_misses, sorted(modules)):
                call.update(seat=c["seat"], session=f.stem, lane=place(c["seat"], call["branch"], call["at"]))
                own.append(call)
            for r in recs:
                for item in ((r.get("message") or {}).get("content") or []) if r.get("type") == "assistant" else []:
                    if isinstance(item, dict) and item.get("type") == "tool_use" and item.get("name") in ("Agent", "Task"):
                        agent_calls[item["id"]] = (str(r.get("gitBranch") or ""), str(r.get("timestamp") or ""))
            del recs
        counts = {name: n for name, n in counts.items() if n}
        population.append({"seat": c["seat"], "folder": folder.name, "files": len(counts),
                           "records": sum(counts.values()), "per_file": counts})
        for meta in sorted(folder.glob("*/subagents/*.meta.json")):
            try:
                parent = json.loads(meta.read_text(encoding="utf-8")).get("toolUseId")
            except (OSError, ValueError):
                continue
            branch, when = agent_calls.get(parent, ("", ""))
            if not when or when[:19] > until[:19]:
                continue
            log = meta.with_name(meta.name[: -len(".meta.json")] + ".jsonl")
            _n, recs = _records(log) if log.is_file() else (0, [])
            for call in calls_of(recs, roots, until, length, sub_misses, sorted(modules)):
                call.update(seat=c["seat"], session=log.stem, lane=place(c["seat"], branch, when))
                subs.append(call)
    if not sum(p["records"] for p in population):
        raise Unread(f"the box seats' transcript folders hold no record up to {until}: "
                     f"{[p['folder'] for p in population]}")

    def missed(key: str) -> dict:
        return {who: {"commands": m.get(key, 0), "naming_cli": m.get(f"{key}_naming_cli", 0)}
                for who, m in (("own", own_misses), ("subagents", sub_misses))}

    unlexed = missed("unlexed")
    if unlexed["own"]["commands"] or unlexed["subagents"]["commands"]:
        _partial(ctx, "transcripts", "unlexed", "Bash commands the lexer refuses book no read: "
                 + ", ".join(f"{w} {v['commands']} ({v['naming_cli']} holding a CLI module's path)"
                             for w, v in unlexed.items()))

    def per_lane(calls: list[dict]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for call in calls:
            row = out.setdefault(call["lane"], {"r": 0, "e": 0, "total": 0, "search_calls": 0, "calls": 0})
            edited = set(lanes[call["lane"]]["files"]) if call["lane"] in lanes else set()
            row["calls"] += 1
            for path, n in call["reads"]:
                row["total"] += n
                row["r"] += n if path in modules else 0
                row["e"] += n if path in edited else 0
            row["search_calls"] += sum(1 for path, _n in call["searches"] if path in modules)
        return out

    mine, theirs = per_lane(own), per_lane(subs)
    treatment, control = [], []
    for lane, pr in sorted(lanes.items(), key=lambda kv: kv[1]["number"]):
        row = mine.get(lane, {"r": 0, "e": 0, "total": 0, "search_calls": 0, "calls": 0})
        if _touches_cli(pr["files"], modules):
            treatment.append({"pr": pr["number"], "lane": lane, **row, "subagent_r": theirs.get(lane, {}).get("r", 0)})
        else:
            py = [p for p in pr["files"] if p.endswith(".py") and not p.startswith("tests/")]
            sizes = [len((source_at(root, pr["merge_base"], p) or "").splitlines()) for p in py]
            if all(n < CONTROL_MAX_LINES for n in sizes):
                control.append({"pr": pr["number"], "lane": lane, **row, "has_py": bool(py)})
    verdict = item3_verdict([t["r"] for t in treatment], [c["e"] for c in control])
    unplaced = {k: v["calls"] for k, v in mine.items() if k in ("ambiguous", "unattributed")}
    step = max(1, len(treatment) // 3)
    sample = [t["pr"] for t in treatment[::step][:3]] + [c["pr"] for c in control[:: max(1, len(control) // 2)][:2]]
    return {"seats": read_seats, "of_seats": 4, "seats_not_read": not_read, "population": population,
            "checkouts_without_a_seat": unseated, "skipped_never_named": skipped,
            "cutoff": until, "lanes": len(lanes), "treatment": treatment, "control": control,
            "item3": verdict,
            "beside": {"r_share_of_total": [round(t["r"] / t["total"], 3) if t["total"] else None for t in treatment],
                       "search_calls_on_cli": sum(t["search_calls"] for t in treatment),
                       "subagent_r": sum(t["subagent_r"] for t in treatment),
                       "control_with_py_only": item3_verdict([t["r"] for t in treatment],
                                                             [c["e"] for c in control if c["has_py"]])},
            "calls": {"own": len(own), "subagents": len(subs), "not_on_a_lane": unplaced,
                      "off_a_merged_branch": sum(1 for c in own if c["branch"] in lanes and c["lane"] != c["branch"]),
                      "unlexed": unlexed, "heredoc_tag_missed": missed("heredoc_tag_missed")},
            "hand_sample": sample}


#: A wave is paid on a component only when it falls by this share from its
#: baseline at P (committed at step 1, 6a91bc51b).
PAYOFF_FALL = 0.30


def wave_payoff(lane_read_before: float, lane_read_after: float, primary_paid: bool) -> dict:
    """Task 7's grade of a wave on the secondary. ``primary_paid`` is the
    primary's own grade at the wave's pin (the post-wave R against the
    baseline R under rule (a) to (c)). ``lane_read`` is never a payoff alone:
    any decomposition lowers it by construction, an arbitrary equal split of a
    function included, so its fall counts only beside a primary that paid."""
    fell = bool(lane_read_before) and (lane_read_before - lane_read_after) / lane_read_before >= PAYOFF_FALL
    return {"lane_read_fell": fell, "primary_paid": bool(primary_paid), "paid": bool(primary_paid),
            "lane_read_counts": fell and bool(primary_paid)}


SECTION_READERS = {
    "pin": section_pin,
    "functions": section_functions,
    "layers": section_layers,
    "clusters": section_clusters,
    "importers": section_importers,
    "readers": section_readers,
    "patches": section_patches,
    "citations": section_citations,
    "probes": section_probes,
    "doctor_boundary": section_doctor_boundary,
    "move_cost": section_move_cost,
    "ledger_rows": section_ledger_rows,
    "collision": section_collision,
    "lane_read": section_lane_read,
    "transcripts": section_transcripts,
}


def census(root: Path, at: str, sections: list[str], *, modules: tuple[str, ...] = (CLI,),
           extra: dict | None = None) -> dict:
    """Every named section read at ``at``. A section that cannot be read (any
    of ``_READ_FAILURES``), or has no reader yet, is ``None`` under its key and
    named under ``unread``; a part of a section that could not be read (the
    move cost's ingredients, a file that did not parse, the importers under the
    clusters' split) is named there as ``<section>.<part>``, a section the run
    read only as another's input included, so no figure rests on a part read
    in silence. The mail refs are read once, before any section: where that
    read fails (any of ``_READ_FAILURES``) the pin's ``mail_refs`` is ``None``,
    ``pin.mail_refs`` is named under ``unread``, each section that reads the
    mail is ``Unread`` with the reason, and every other section still reads."""
    ctx = {"root": root, "pin": resolve_pin(root, at), "modules": modules, **(extra or {})}
    if "mail_refs" not in ctx["pin"]:
        try:
            ctx["pin"]["mail_refs"] = (extra or {}).get("mail_refs") or mail_refs(root)
        except _READ_FAILURES as exc:
            ctx["pin"]["mail_refs"] = None
            ctx["_mail_refs_unread"] = str(_unread(exc))
            _partial(ctx, "pin", "mail_refs", ctx["_mail_refs_unread"])
    result: dict = {"unread": {}}
    for name in sections:
        reader = SECTION_READERS.get(name)
        if reader is None:
            result[name] = None
            result["unread"][name] = "no reader for this section in this census"
            continue
        try:
            result[name] = _section(ctx, name)
        except Unread as exc:
            result[name] = None
            result["unread"][name] = str(exc)
    for name, parts in sorted(ctx.get("_partial_unread", {}).items()):
        for part, why in sorted(parts.items()):
            result["unread"][f"{name}.{part}"] = why
    if "pin" not in result:
        result["pin"] = section_pin(ctx)
    return result


#: Text mode prints each section's JSON up to this many characters, and says so where it cuts.
TEXT_CUT = 400


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sections", nargs="*", metavar="SECTION",
                    help=f"which sections, of {', '.join(SECTIONS)} (default: every one)")
    ap.add_argument("--at", required=True,
                    help="the commit every section is read at (required: there is no default)")
    ap.add_argument("--module", action="append", default=[],
                    help="a module that receives a definition moved out of cli.py (repeatable)")
    ap.add_argument("--root", default=str(ROOT), help="the repository (default: this checkout)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--prs-json", metavar="FILE",
                    help="the pull requests' open times from FILE (a saved gh pr list --json "
                         "number,createdAt,mergedAt) instead of gh")
    ap.add_argument("--skip", action="append", default=[], metavar="COMPONENT",
                    help="a collision component left unread by name (conflicts, pairs, claims, holds, catch_ups)")
    args = ap.parse_args(argv)
    unknown = [s for s in args.sections if s not in SECTIONS]
    if unknown:
        ap.error(f"unknown section(s) {unknown}; choose from {', '.join(SECTIONS)}")
    sections = list(args.sections) or list(SECTIONS)
    modules = (CLI, *[m for m in args.module if m != CLI])
    extra = {"prs_json": args.prs_json, "skip_components": tuple(args.skip)}
    result = census(Path(args.root).resolve(), args.at, sections, modules=modules, extra=extra)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, default=sorted))
        return 0
    pin = result["pin"]
    print(f"cli cost census at {pin['at'][:12]} ({pin['date']}); window {pin['window']['since']} "
          f"to {pin['window']['until']}; modules: {', '.join(pin['modules'])}")
    for name in sections:
        if name == "pin":
            continue
        if result.get(name) is None:
            print(f"{name}: UNREAD ({result['unread'].get(name, '?')})")
            continue
        text = json.dumps(result[name], sort_keys=True, default=sorted)
        cut = f" ... [cut at {TEXT_CUT} of {len(text)} characters; --json prints it whole]" if len(text) > TEXT_CUT else ""
        print(f"{name}: {text[:TEXT_CUT]}{cut}")
    for key, why in sorted(result["unread"].items()):
        if "." in key:
            print(f"{key}: UNREAD ({why})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
